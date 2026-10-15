import re
import uuid
from datetime import datetime,timedelta,timezone

from campaign_queue import dispatcher
from tests.test_api import app,shop,payload,send
from tests.test_business import advance
from tests.test_growth import sql


class Provider:
    ready=True
    def __init__(self):self.calls=[];self.fail=False
    def send_text(self,instance,phone,text):
        self.calls.append((instance,phone,text))
        return (0,{}) if self.fail else (201,{'key':{'id':uuid.uuid4().hex}})


def provider(client):
    fake=Provider();client.application.extensions['evolution']=fake
    sql(client,"UPDATE stores SET wa_instance='test-instance',wa_enabled=1")
    return fake


def purchase(client,pid,**values):
    r=send(client,'POST','/api/store/minha-loja/orders',payload(pid,**values),uuid.uuid4().hex)
    assert r.status_code==201,r.json
    order=client.get('/api/admin/orders').json['orders'][0]
    return order


def verified_wallet(c,fake):
    r=send(c,'POST','/api/store/minha-loja/wallet/code',{'phone':'11999999999'});assert r.status_code==200,r.json
    code=re.search(r': (\d{6})\.',fake.calls[-1][2]).group(1)
    v=send(c,'POST','/api/store/minha-loja/wallet/verify',{'challenge':r.json['challenge'],'code':code})
    assert v.status_code==200,v.json
    return v.json


def test_cashback_requires_otp_paid_completion_and_restores_cancelled_redemption(shop):
    c,pid=shop
    assert send(c,'PUT','/api/admin/cashback',{'enabled':True,'bps':500}).status_code==409
    fake=provider(c)
    assert send(c,'PUT','/api/admin/cashback',{'enabled':True,'bps':500}).status_code==200
    first=purchase(c,pid)
    assert verified_wallet(c,fake)['balance']==0
    advance(c,first['id'],'preparing','ready','delivering','completed')
    assert verified_wallet(c,fake)['balance']==0
    send(c,'PATCH',f"/api/admin/orders/{first['id']}",{'paid':True})
    wallet=verified_wallet(c,fake)
    assert wallet['balance']==170
    assert c.get('/api/store/minha-loja/wallet').status_code==401
    assert c.get('/api/store/minha-loja/wallet',headers={'Authorization':'Bearer '+wallet['token']}).json['balance']==170
    assert send(c,'POST','/api/store/minha-loja/quote',payload(pid,wallet_token=wallet['token'],cashback_use=170,phone='11888888888')).status_code==403
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid,wallet_token=wallet['token'],cashback_use=171),uuid.uuid4().hex).status_code==409
    next_order=purchase(c,pid,wallet_token=wallet['token'],cashback_use=170)
    assert next_order['discount']==170 and next_order['cashback_discount']==170 and next_order['cashback_earned']==161
    assert c.get('/api/store/minha-loja/wallet',headers={'Authorization':'Bearer '+wallet['token']}).json['balance']==0
    assert send(c,'PATCH',f"/api/admin/orders/{next_order['id']}",{'status':'cancelled'}).status_code==200
    assert c.get('/api/store/minha-loja/wallet',headers={'Authorization':'Bearer '+wallet['token']}).json['balance']==170
    assert send(c,'POST','/api/admin/customers/11999999999/anonymize',{}).status_code==200
    assert c.get('/api/store/minha-loja/wallet',headers={'Authorization':'Bearer '+wallet['token']}).status_code==401
    assert all(r['phone']=='' for r in sql(c,'SELECT phone FROM cashback_movements'))


def test_otp_attempt_limit_persists_and_challenges_are_single_use(shop):
    c,pid=shop;fake=provider(c);send(c,'PUT','/api/admin/cashback',{'enabled':True,'bps':500})
    r=send(c,'POST','/api/store/minha-loja/wallet/code',{'phone':'11999999999'})
    code=re.search(r': (\d{6})\.',fake.calls[-1][2]).group(1)
    wrong='999999' if code!='999999' else '111111'
    for _ in range(5):
        assert send(c,'POST','/api/store/minha-loja/wallet/verify',{'challenge':r.json['challenge'],'code':wrong}).status_code==400
    assert send(c,'POST','/api/store/minha-loja/wallet/verify',{'challenge':r.json['challenge'],'code':code}).status_code==400
    assert sql(c,'SELECT attempts FROM wallet_challenges')[0]['attempts']==5
    wallet=verified_wallet(c,fake)
    assert wallet['balance']==0
    fake.fail=True
    assert send(c,'POST','/api/store/minha-loja/wallet/code',{'phone':'11999999999'}).status_code==502
    assert all(r['used_at'] for r in sql(c,'SELECT used_at FROM wallet_challenges ORDER BY id DESC LIMIT 1'))


def test_dynamic_segments_campaign_queue_cancel_and_uncertain_delivery(shop):
    c,pid=shop;fake=provider(c)
    o=purchase(c,pid,marketing_consent=True);advance(c,o['id'],'preparing','ready','delivering','completed')
    fake.calls.clear()
    seg=send(c,'POST','/api/admin/marketing/segments',{'name':'Compradores recentes','operator':'and','rules':[{'field':'orders','comparison':'gte','value':1},{'field':'days_since','comparison':'lte','value':7}]}).json['id']
    saved=c.get('/api/admin/marketing/segments').json['segments'][0]
    assert saved['total']==1 and saved['authorized']==1
    body={'name':'Oferta teste','segment':'saved:'+str(seg),'message':'Olá, {nome}! Veja na {loja}: {link}'}
    assert send(c,'POST','/api/admin/marketing/campaigns/preview',body).json['total']==1
    cid=send(c,'POST','/api/admin/marketing/campaigns',body).json['id']
    due={'due_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}
    assert send(c,'POST',f'/api/admin/marketing/campaigns/{cid}/queue',due).json['queued']==1
    repeated=send(c,'POST',f'/api/admin/marketing/campaigns/{cid}/queue',due)
    assert repeated.status_code==200 and repeated.json['queued']==0
    assert len(c.get('/api/admin/marketing/queue').json['jobs'])==1
    result=dispatcher(c.application)
    assert result['sent']==1 and len(fake.calls)==1
    assert dispatcher(c.application)['sent']==0
    cid2=send(c,'POST','/api/admin/marketing/campaigns',body).json['id']
    send(c,'POST',f'/api/admin/marketing/campaigns/{cid2}/queue',due)
    assert dispatcher(c.application)['sent']==0 # proteção contra repetição na mesma semana
    assert send(c,'POST',f'/api/admin/marketing/campaigns/{cid2}/cancel-queue',{}).status_code==200
    cid3=send(c,'POST','/api/admin/marketing/campaigns',body).json['id']
    send(c,'POST',f'/api/admin/marketing/campaigns/{cid3}/queue',due)
    sql(c,"UPDATE marketing_jobs SET claimed_at=? WHERE status='sent'",((datetime.now(timezone.utc)-timedelta(days=8)).isoformat(timespec='seconds'),))
    fake.fail=True
    assert dispatcher(c.application)['uncertain']==1
    assert dispatcher(c.application)['sent']==0 and len(fake.calls)==2
    cid4=send(c,'POST','/api/admin/marketing/campaigns',body).json['id']
    send(c,'POST',f'/api/admin/marketing/campaigns/{cid4}/queue',due)
    sql(c,'UPDATE customer_opt_ins SET consent=0')
    assert dispatcher(c.application)['cancelled']==1
