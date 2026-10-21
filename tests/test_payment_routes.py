import uuid

import pytest

from tests.test_api import app, shop, send, payload
from tests.test_online_payments import setup_online, create_order
from tests.test_growth import sql
from tests.test_chat_orders import enable, review, turn
from chat_orders import process_chat_orders


@pytest.mark.parametrize('kind',['pix','card'])
def test_online_payment_routes_require_email_and_forbid_manual_receipt(shop,kind):
    c,pid=shop;setup_online(c,kind)
    method='pix_online' if kind=='pix' else 'card_online'
    result=send(c,'POST','/api/store/minha-loja/orders',payload(pid,payment=method),uuid.uuid4().hex)
    assert result.status_code==400 and not sql(c,'SELECT id FROM orders')
    order,token=create_order(c,pid,method)
    assert send(c,'PATCH',f"/api/admin/orders/{order['id']}",{'paid':True}).status_code==409
    assert send(c,'POST',f"/api/admin/orders/{order['id']}/receipts",{'amount':order['total'],'method':'cash'},uuid.uuid4().hex).status_code==409
    assert send(c,'POST',f"/api/admin/orders/{order['id']}/payment/refund",{}).status_code==400
    assert send(c,'DELETE','/api/admin/payments/mercadopago',{}).status_code==409


@pytest.mark.parametrize('kind',['pix','card'])
def test_guided_whatsapp_collects_real_email_before_online_payment(shop,kind):
    c,pid=shop;setup_online(c,kind);wa=enable(c)
    assert 'Informe seu e-mail' in review(c,wa)
    assert 'Confira o e-mail' in turn(c,wa,'email-invalido')
    summary=turn(c,wa,'pagador@example.test')
    assert 'CONFIRMAR' in summary
    turn(c,wa,'CONFIRMAR');assert process_chat_orders(c.application)==1
    order=sql(c,'SELECT * FROM orders')[0]
    assert order['payer_email']=='pagador@example.test' and not order['paid']
    assert order['payment']==('pix_online' if kind=='pix' else 'card_online')


def test_zero_total_order_does_not_wait_for_an_impossible_provider_charge(shop):
    c,pid=shop;provider=setup_online(c,'pix',auto=True)
    assert send(c,'POST','/api/admin/coupons',{'code':'PRESENTE','kind':'fixed','value':3400}).status_code==201
    result=send(c,'POST','/api/store/minha-loja/orders',payload(pid,mode='pickup',payment='pix_online',coupon='PRESENTE',payment_email='pagador@example.test'),uuid.uuid4().hex)
    assert result.status_code==201,result.json
    order=sql(c,'SELECT * FROM orders')[0]
    assert order['total']==0 and order['paid'] and order['status']=='preparing'
    assert not provider.created


def test_disconnect_during_provider_account_check_prevents_a_new_charge(shop):
    c,pid=shop;provider=setup_online(c);provider.create_pix=lambda *args:None
    # Create the normal durable order first, then remove its uncertain attempt.
    order,_=create_order(c,pid)
    sql(c,'DELETE FROM order_payment_transactions');sql(c,'DELETE FROM order_payment_attempts')
    sql(c,"UPDATE orders SET pix_provider_id='',pix_code='' WHERE id=?",(order['id'],))
    original=provider.me
    def disconnect(*args):
        result=original(*args);sql(c,"UPDATE stores SET mp_token=''");return result
    provider.me=disconnect
    from tests.test_online_payments import core
    from payments import PaymentError
    with pytest.raises(PaymentError):core(c,'online_create',order['store_id'],order['id'],'pix')
    assert not sql(c,'SELECT id FROM order_payment_attempts')
