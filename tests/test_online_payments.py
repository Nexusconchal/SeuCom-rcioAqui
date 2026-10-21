import uuid
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from payments import PaymentError
from tests.test_api import app,shop,send,payload
from tests.test_features import FakeMercadoPago
from tests.test_growth import sql


class OnlineProvider(FakeMercadoPago):
    def __init__(self):
        super().__init__();self.preferences=[];self.refunds=[];self.timeout_pix=False;self.timeout_card=False
    def create_pix(self,token,value,key):
        result=super().create_pix(token,value,key)
        self.payments[int(result['id'])]['point_of_interaction']=result['point_of_interaction']
        if self.timeout_pix:
            self.timeout_pix=False;raise PaymentError('timeout after provider commit')
        return result
    def create_preference(self,token,value,key):
        result={**value,'id':'pref-'+str(len(self.preferences)+1),'collector_id':1,
                'init_point':'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=local-test'}
        self.preferences.append(result)
        if self.timeout_card:
            self.timeout_card=False;raise PaymentError('timeout after preference creation')
        return result
    def search_preferences(self,token,reference):
        return {'elements':[p for p in self.preferences if p['external_reference']==reference]}
    def get_preference(self,token,pref):return next(p for p in self.preferences if p['id']==pref)
    def update_preference(self,token,pref,value):
        p=self.get_preference(token,pref);p.update(value);return p
    def search_payments(self,token,reference):
        return {'results':[p for p in self.payments.values() if p['external_reference']==reference]}
    def approve_card(self,index=0,pid=20001,**values):
        pref=self.preferences[index]
        p={'id':pid,'status':'approved','collector_id':1,'currency_id':'BRL','payment_type_id':'credit_card',
           'payment_method_id':'visa','external_reference':pref['external_reference'],
           'transaction_amount':sum(i['unit_price']*i['quantity'] for i in pref['items']),
           'transaction_amount_refunded':0,'fee_details':[{'amount':1.25}],'date_approved':'2026-10-21T12:00:00Z',**values}
        self.payments[pid]=p;return p
    def refund(self,token,pid,key):
        if not any(r[1]==key for r in self.refunds):self.refunds.append((str(pid),key))
        self.payments[int(pid)].update(status='refunded',transaction_amount_refunded=self.payments[int(pid)]['transaction_amount'])
        return {'id':str(pid),'status':'approved'}


def setup_online(c,kind='pix',auto=False):
    provider=OnlineProvider();c.application.extensions['mercadopago']=provider
    assert send(c,'PUT','/api/admin/payments/mercadopago',{'access_token':'APP_USR-valido-123456789012345'}).status_code==200
    store=c.get('/api/admin/store').json['store'];store.update(payments=['pix_online' if kind=='pix' else 'card_online'],auto_accept=auto)
    assert send(c,'PUT','/api/admin/store',store).status_code==200
    assert send(c,'PUT','/api/admin/operation-settings',{'timezone':'America/Sao_Paulo','auto_accept':auto}).status_code==200
    return provider


def create_order(c,pid,method='pix_online'):
    response=send(c,'POST','/api/store/minha-loja/orders',payload(pid,payment=method,payment_email='cliente@example.test'),uuid.uuid4().hex)
    assert response.status_code==201,response.json
    order=sql(c,'SELECT * FROM orders ORDER BY id DESC LIMIT 1')[0]
    return dict(order),response.json['token']


def core(c,name,*args):
    with c.application.test_request_context('/'):
        return c.application.extensions[name](*args)


def test_pix_retries_reuse_attempt_after_provider_timeout(shop):
    c,pid=shop;provider=setup_online(c);provider.timeout_pix=True
    order,token=create_order(c,pid)
    assert len(provider.created)==1
    first=sql(c,'SELECT * FROM order_payment_attempts')[0]
    assert first['status']=='uncertain'
    core(c,'online_create',order['store_id'],order['id'],'pix')
    assert len(provider.created)==1 and len(sql(c,'SELECT * FROM order_payment_attempts'))==1
    after=sql(c,'SELECT * FROM order_payment_attempts')[0]
    assert after['idempotency_key']==first['idempotency_key'] and after['status']=='pending'
    assert provider.created[0][1]['payer']['email']=='cliente@example.test'
    assert c.get('/api/track/'+token).json['order']['pix']['code']


def test_old_pix_is_reconciled_after_renewal_without_duplicate_sale(shop):
    c,pid=shop;provider=setup_online(c)
    order,token=create_order(c,pid)
    sql(c,"UPDATE order_payment_attempts SET expires_at='2020-01-01T00:00:00+00:00'")
    sql(c,"UPDATE orders SET pix_expires='2020-01-01T00:00:00+00:00'")
    core(c,'online_create',order['store_id'],order['id'],'pix')
    assert len(provider.created)==2
    provider.payments[9000]['status']='approved'
    store=sql(c,'SELECT * FROM stores WHERE id=1')[0]
    assert core(c,'online_webhook',store,9000)
    assert sql(c,'SELECT paid FROM orders')[0]['paid']==1
    assert len(sql(c,'SELECT * FROM order_payment_attempts'))==2
    assert len(sql(c,'SELECT * FROM orders'))==1


@pytest.mark.parametrize('field,value',[('currency_id','USD'),('collector_id',99),('transaction_amount',1),('external_reference','other'),('payment_method_id','visa')])
def test_pix_never_approves_foreign_amount_currency_collector_or_method(shop,field,value):
    c,pid=shop;provider=setup_online(c);order,_=create_order(c,pid)
    provider.payments[9000].update(status='approved');provider.payments[9000][field]=value
    store=sql(c,'SELECT * FROM stores')[0]
    with pytest.raises(PaymentError):core(c,'online_webhook',store,9000)
    assert not sql(c,'SELECT paid FROM orders')[0]['paid']


def test_hosted_card_return_is_not_proof_then_sync_approves_once_and_starts_kitchen(shop):
    c,pid=shop;provider=setup_online(c,'card',auto=True);order,token=create_order(c,pid,'card_online')
    assert len(provider.preferences)==1
    pref=provider.preferences[0]
    assert pref['items'][0]['currency_id']=='BRL' and pref['items'][0]['unit_price']==39
    assert not sql(c,'SELECT paid FROM orders')[0]['paid']
    assert sql(c,'SELECT status FROM orders')[0]['status']=='new'
    assert not c.get('/api/track/'+token+'?status=approved&payment_id=999').json['order']['paid']
    provider.approve_card();store=sql(c,'SELECT * FROM stores')[0]
    assert core(c,'online_webhook',store,20001)
    assert core(c,'online_webhook',store,20001)
    result=sql(c,'SELECT * FROM orders')[0]
    assert result['paid']==1 and result['status']=='preparing' and result['payment_fee']==125
    assert len(sql(c,"SELECT * FROM order_events WHERE status='preparing'"))==1
    assert len(sql(c,'SELECT * FROM order_payment_transactions'))==1
    assert all(x['kitchen_state']=='preparing' for x in sql(c,'SELECT * FROM order_items'))


def test_preference_timeout_is_recovered_by_exact_reference_without_second_checkout(shop):
    c,pid=shop;provider=setup_online(c,'card');provider.timeout_card=True
    order,_=create_order(c,pid,'card_online')
    assert len(provider.preferences)==1
    result=core(c,'online_create',1,order['id'],'card')
    assert result['checkout_url'].startswith('https://www.mercadopago.com.br/checkout/')
    assert len(provider.preferences)==1


def test_refund_and_chargeback_remove_paid_without_reopening_cancelled_order(shop):
    c,pid=shop;provider=setup_online(c,'card');order,_=create_order(c,pid,'card_online');provider.approve_card()
    store=sql(c,'SELECT * FROM stores')[0]
    core(c,'online_webhook',store,20001)
    core(c,'online_refund',store,order)
    assert not sql(c,'SELECT paid FROM orders')[0]['paid'] and len(provider.refunds)==1
    with pytest.raises(PaymentError):core(c,'online_refund',store,order)
    assert len(provider.refunds)==1
    result=core(c,'online_state',order)
    assert result['status']=='refunded' and not result['paid']


def test_late_card_payment_after_cancellation_is_review_and_never_prepares(shop):
    c,pid=shop;provider=setup_online(c,'card',auto=True);order,_=create_order(c,pid,'card_online')
    sql(c,"UPDATE orders SET status='cancelled'")
    provider.approve_card();store=sql(c,'SELECT * FROM stores')[0]
    core(c,'online_webhook',store,20001)
    result=core(c,'online_state',order)
    assert result['review'] and result['status']=='review'
    assert sql(c,'SELECT status FROM orders')[0]['status']=='cancelled'
    assert not sql(c,"SELECT id FROM order_events WHERE status='preparing'")


def test_duplicate_approved_payment_is_flagged_for_review(shop):
    c,pid=shop;provider=setup_online(c,'card');order,_=create_order(c,pid,'card_online')
    provider.approve_card(pid=20001);provider.approve_card(pid=20002)
    store=sql(c,'SELECT * FROM stores')[0]
    core(c,'online_sync',order,store)
    assert core(c,'online_state',order)['review']
    assert len(sql(c,'SELECT id FROM orders'))==1
    with pytest.raises(PaymentError):core(c,'online_refund',store,order)


def test_partial_refund_and_replayed_approval_never_restore_full_paid(shop):
    c,pid=shop;provider=setup_online(c,'card');order,_=create_order(c,pid,'card_online');p=provider.approve_card(transaction_amount_refunded=10)
    store=sql(c,'SELECT * FROM stores')[0]
    core(c,'online_webhook',store,20001)
    assert not sql(c,'SELECT paid FROM orders')[0]['paid'] and core(c,'online_state',order)['review']
    p['status']='refunded';p['transaction_amount_refunded']=39
    core(c,'online_webhook',store,20001)
    p['status']='approved';p['transaction_amount_refunded']=0
    core(c,'online_webhook',store,20001)
    assert not sql(c,'SELECT paid FROM orders')[0]['paid']


def test_concurrent_pix_renewal_only_creates_one_remote_charge(shop):
    c,pid=shop;provider=setup_online(c);order,_=create_order(c,pid)
    sql(c,"UPDATE order_payment_attempts SET expires_at='2020-01-01T00:00:00+00:00'")
    entered=Event();release=Event();original=provider.create_pix
    def delayed(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    provider.create_pix=delayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(core,c,'online_create',1,order['id'],'pix')
        try:
            assert entered.wait(10)
            second=pool.submit(core,c,'online_create',1,order['id'],'pix').result(timeout=10)
            assert second['status']=='creating'
        finally:release.set()
        assert first.result(timeout=10)['status']=='pending'
    assert len(provider.created)==2 and len(sql(c,'SELECT * FROM order_payment_attempts'))==2


def test_legacy_pix_remains_reconcilable_without_payer_email(shop):
    c,pid=shop;provider=setup_online(c);order,_=create_order(c,pid)
    sql(c,'DELETE FROM order_payment_transactions');sql(c,'DELETE FROM order_payment_attempts')
    sql(c,"UPDATE orders SET payer_email=''")
    provider.payments[9000].update(external_reference=f"sca-1-{order['id']}",status='approved')
    store=sql(c,'SELECT * FROM stores')[0]
    assert core(c,'online_webhook',store,9000)
    assert sql(c,'SELECT paid FROM orders')[0]['paid']


def test_unverified_pix_creation_never_exposes_a_qr(shop):
    c,pid=shop;provider=setup_online(c);original=provider.create_pix
    def wrong_currency(*args):
        result=original(*args);provider.payments[int(result['id'])]['currency_id']='USD';return result
    provider.create_pix=wrong_currency
    order,_=create_order(c,pid)
    result=core(c,'online_state',order)
    assert not result['paid'] and not result['code'] and result['status']=='uncertain'


def test_unsafe_hosted_checkout_is_not_exposed(shop):
    c,pid=shop;provider=setup_online(c,'card');original=provider.create_preference
    def unsafe(*args):
        result=original(*args);result['init_point']='https://mercadopago.com.br.attacker.test/checkout/';return result
    provider.create_preference=unsafe
    order,_=create_order(c,pid,'card_online')
    result=core(c,'online_state',order)
    assert not result['checkout_url'] and result['status']=='uncertain'


def test_historical_payment_can_be_refunded_after_store_disconnect(shop):
    c,pid=shop;provider=setup_online(c,'card');order,_=create_order(c,pid,'card_online');provider.approve_card()
    store=sql(c,'SELECT * FROM stores')[0];core(c,'online_webhook',store,20001)
    sql(c,"UPDATE stores SET mp_token=''")
    store=sql(c,'SELECT * FROM stores')[0]
    result=core(c,'online_refund',store,order)
    assert result['status']=='refunded' and len(provider.refunds)==1
    assert 'APP_USR' not in sql(c,'SELECT credential FROM order_payment_attempts')[0]['credential']


def test_interrupted_refund_resumes_with_same_key_after_lease(shop):
    c,pid=shop;provider=setup_online(c,'card');order,_=create_order(c,pid,'card_online');provider.approve_card()
    store=sql(c,'SELECT * FROM stores')[0];core(c,'online_webhook',store,20001)
    sql(c,"UPDATE order_payment_transactions SET refund_state='processing',refund_key='stable-old-key',refund_started_at='2020-01-01T00:00:00+00:00'")
    core(c,'online_refund',store,order)
    assert provider.refunds==[('20001','stable-old-key')]


def test_expired_uncertain_pix_never_blindly_reposts_charge(shop):
    c,pid=shop;provider=setup_online(c);provider.timeout_pix=True;order,_=create_order(c,pid)
    sql(c,"UPDATE order_payment_attempts SET expires_at='2020-01-01T00:00:00+00:00'")
    provider.search_payments=lambda *args:{'results':[]}
    with pytest.raises(PaymentError):core(c,'online_create',1,order['id'],'pix')
    assert len(provider.created)==1 and len(sql(c,'SELECT * FROM order_payment_attempts'))==1


@pytest.mark.parametrize('kind',['pix','card'])
@pytest.mark.parametrize('timeout',[False,True])
def test_cancellation_during_remote_creation_never_exposes_checkout_and_expires_it(shop,kind,timeout):
    c,pid=shop;provider=setup_online(c,kind)
    if timeout:setattr(provider,'timeout_'+kind,True)
    name='create_pix' if kind=='pix' else 'create_preference';original=getattr(provider,name)
    def cancelled_during_http(*args):
        # Represents another worker committing cancellation while HTTP is open.
        sql(c,"UPDATE orders SET status='cancelled'")
        return original(*args)
    setattr(provider,name,cancelled_during_http)
    order,_=create_order(c,pid,'pix_online' if kind=='pix' else 'card_online')
    result=core(c,'online_state',order)
    assert result['status']=='cancelled' and not result['code'] and not result['checkout_url']
    attempt=sql(c,'SELECT * FROM order_payment_attempts')[0]
    assert attempt['status']=='cancelled'
    if kind=='pix':assert provider.cancelled==[9000]
    else:assert provider.preferences[0]['expires'] is True
