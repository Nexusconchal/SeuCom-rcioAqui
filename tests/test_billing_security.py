"""Subscription receipts must match the server's immutable billing intent."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Event

import pytest

from billing import billing_state, add_month, ZONE
from database import connect
from payments import PaymentError
from tests.test_api import app, shop, send
from tests.test_features import FakeSubscriptions


def provider(c):
    fake=FakeSubscriptions();c.application.extensions['mercadopago']=fake
    c.application.config['MP_PLATFORM_ACCESS_TOKEN']='APP_USR-test-platform'
    return fake


def sql(c,query,args=()):
    db=connect(c.application.config)
    try:return db.execute(query,args).fetchall()
    finally:db.close()


def approved(fake,pid=9000):
    fake.payments[pid].update(status='approved',date_approved=datetime.now(timezone.utc).isoformat())


@pytest.mark.parametrize('field,value',[('currency_id','USD'),('collector_id',77),('id',9001),
    ('external_reference','plan-1-other-reference'),('transaction_amount','NaN'),('payment_method_id','visa')])
def test_plan_pix_rejects_foreign_or_mismatched_payment(shop,field,value):
    c,_=shop;fake=provider(c)
    assert send(c,'POST','/api/admin/billing/pix',{}).status_code==200
    approved(fake);fake.payments[9000][field]=value
    result=send(c,'POST','/api/admin/billing/pix/check',{})
    assert result.status_code==200 and result.json['paid'] is False
    assert not sql(c,'SELECT id FROM platform_ledger')


def test_plan_pix_snapshot_survives_price_change_and_uses_real_approval_day(shop):
    c,_=shop;fake=provider(c)
    send(c,'POST','/api/admin/billing/pix',{})
    c.application.config['PLAN_PRICE']=7999
    stamp=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    fake.payments[9000].update(status='approved',date_approved=stamp)
    assert send(c,'POST','/api/admin/billing/pix/check',{}).json['paid']
    receipt=sql(c,'SELECT amount,paid_at FROM platform_ledger')[0]
    assert receipt['amount']==5999 and receipt['paid_at']==stamp[:19]+'+00:00'
    assert sql(c,'SELECT paid_until FROM stores')[0]['paid_until']==(add_month(datetime.fromisoformat(stamp).astimezone(ZONE).date())+timedelta(days=3)).isoformat()


def test_late_old_pix_webhook_is_reconciled_once_and_preserves_new_pending_code(shop):
    c,_=shop;fake=provider(c)
    send(c,'POST','/api/admin/billing/pix',{})
    sql(c,"UPDATE stores SET sub_pix_expires='2020-01-01T00:00:00+00:00'")
    second=send(c,'POST','/api/admin/billing/pix',{});assert second.status_code==200
    assert len(fake.payments)==2
    c.application.test_cli_runner().invoke(args=['grant-platform-admin','--email','owner@example.com'])
    hook=c.get('/api/platform/billing').json['webhook_url'].split('localhost')[-1]
    approved(fake,9000)
    for _ in range(2):assert c.application.test_client().post(hook,json={'type':'payment','data':{'id':'9000'}}).status_code==200
    assert len(sql(c,'SELECT id FROM platform_ledger'))==1
    assert sql(c,'SELECT sub_pix_id FROM stores')[0]['sub_pix_id']=='9001'
    first_until=sql(c,'SELECT paid_until FROM stores')[0]['paid_until']
    approved(fake,9001);assert send(c,'POST','/api/admin/billing/pix/check',{}).json['paid']
    assert len(sql(c,'SELECT id FROM platform_ledger'))==2
    assert sql(c,'SELECT paid_until FROM stores')[0]['paid_until']>first_until


def test_concurrent_plan_receipt_is_atomic(shop):
    c,_=shop;provider(c)
    def record(_):
        with c.application.test_request_context():
            return c.application.extensions['billing_record_payment'](1,'race-test',5999,datetime.now().date(),'Teste de concorrência')
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(record,range(3)))==1
    assert len(sql(c,'SELECT id FROM platform_ledger'))==1


@pytest.mark.parametrize('field,value',[('id','other-id'),('collector_id',77),('external_reference','store-999')])
def test_subscription_identity_cannot_activate_another_store(shop,field,value):
    c,_=shop;fake=provider(c)
    send(c,'POST','/api/admin/billing/subscribe',{'payer_email':'owner@example.com'})
    fake.preapprovals['pre0001'].update(status='authorized',**{field:value})
    assert send(c,'POST','/api/admin/billing/sync',{}).status_code==502
    assert sql(c,'SELECT sub_status FROM stores')[0]['sub_status']=='pending'


def test_pending_card_checkout_is_reused_and_timeout_never_creates_another(shop):
    c,_=shop;fake=provider(c)
    body={'payer_email':'owner@example.com'}
    a=send(c,'POST','/api/admin/billing/subscribe',body)
    b=send(c,'POST','/api/admin/billing/subscribe',body)
    assert a.status_code==b.status_code==200 and a.json['init_point']==b.json['init_point']
    assert len(fake.preapprovals)==1
    send(c,'POST','/api/admin/billing/cancel',{})
    calls=[]
    def timeout(*args):calls.append(args);raise PaymentError('controlled timeout')
    fake.create_preapproval=timeout
    assert send(c,'POST','/api/admin/billing/subscribe',body).status_code==502
    assert send(c,'POST','/api/admin/billing/subscribe',body).status_code==409 and len(calls)==1


def test_card_receipt_requires_full_validated_payment_and_currency(shop):
    c,_=shop;fake=provider(c)
    send(c,'POST','/api/admin/billing/subscribe',{'payer_email':'owner@example.com'})
    fake.preapprovals['pre0001']['status']='authorized'
    fake.charges['pre0001']=[{'id':123,'transaction_amount':59.99,'payment':{'id':555,'status':'approved'}}]
    fake.payments[555]={'id':555,'status':'approved','transaction_amount':59.99,'currency_id':'USD','collector_id':1,
                        'external_reference':'store-1','date_approved':datetime.now(timezone.utc).isoformat()}
    assert send(c,'POST','/api/admin/billing/sync',{}).status_code==200
    assert not sql(c,'SELECT id FROM platform_ledger')
    fake.payments[555]['currency_id']='BRL'
    assert send(c,'POST','/api/admin/billing/sync',{}).status_code==200
    assert len(sql(c,'SELECT id FROM platform_ledger'))==1


def test_authorized_card_cannot_keep_store_active_forever_and_bad_webhook_is_rejected(shop):
    c,_=shop;provider(c)
    moment=datetime.now(timezone.utc)
    assert billing_state({'billing_exempt':0,'sub_status':'authorized','trial_until':'',
        'paid_until':'2020-01-01','sub_next_payment':'2020-01-01T12:00:00Z'},moment)=='expired'
    assert billing_state({'billing_exempt':0,'sub_status':'authorized','trial_until':'',
        'paid_until':'','sub_next_payment':(moment+timedelta(days=30)).isoformat()},moment)=='expired'
    c.application.test_cli_runner().invoke(args=['grant-platform-admin','--email','owner@example.com'])
    hook=c.get('/api/platform/billing').json['webhook_url'].split('localhost')[-1]
    assert c.application.test_client().post(hook,json=['not-an-object']).status_code==400


def test_plan_does_not_start_card_and_valid_pix_together(shop):
    c,_=shop;fake=provider(c)
    assert send(c,'POST','/api/admin/billing/pix',{}).status_code==200
    assert send(c,'POST','/api/admin/billing/subscribe',{'payer_email':'owner@example.com'}).status_code==409
    assert not fake.preapprovals
    sql(c,"UPDATE stores SET sub_pix_expires='2020-01-01T00:00:00+00:00'")
    assert send(c,'POST','/api/admin/billing/subscribe',{'payer_email':'owner@example.com'}).status_code==200
    assert send(c,'POST','/api/admin/billing/pix',{}).status_code==409
    assert len(fake.payments)==1


def test_platform_test_pix_validates_account_and_amount_without_crediting_plan(shop):
    c,_=shop;fake=provider(c)
    c.application.test_cli_runner().invoke(args=['grant-platform-admin','--email','owner@example.com'])
    result=send(c,'POST','/api/platform/billing/test-pix',{});assert result.status_code==200
    approved(fake);fake.payments[9000]['transaction_amount']=.01
    assert send(c,'POST','/api/platform/billing/test-pix/check',{}).status_code==409
    fake.payments[9000]['transaction_amount']=1
    assert send(c,'POST','/api/platform/billing/test-pix/check',{}).json['approved']
    assert not sql(c,'SELECT id FROM platform_ledger')


@pytest.mark.parametrize('first,second',[('pix','pix'),('card','card'),('pix','card'),('card','pix')])
def test_parallel_plan_creation_cannot_create_duplicate_or_mixed_charges(shop,first,second):
    c,_=shop;fake=provider(c);entered=Event();release=Event();calls=[]
    method='create_pix' if first=='pix' else 'create_preapproval'
    create=getattr(fake,method)
    def held(*args):
        calls.append(args);entered.set()
        if not release.wait(5):raise PaymentError('controlled test timeout')
        return create(*args)
    setattr(fake,method,held)
    other=c.application.test_client()
    with c.session_transaction() as existing:
        copied=dict(existing)
    with other.session_transaction() as target:
        target.update(copied)
    def request(client,kind):
        return send(client,'POST','/api/admin/billing/'+('pix' if kind=='pix' else 'subscribe'),
                    {} if kind=='pix' else {'payer_email':'owner@example.com'})
    with ThreadPoolExecutor(max_workers=1) as pool:
        first_request=pool.submit(request,c,first)
        try:
            assert entered.wait(5)
            assert request(other,second).status_code==409
        finally:
            release.set()
        assert first_request.result().status_code==200
    assert len(calls)==1 and len(fake.payments)+len(fake.preapprovals)==1
