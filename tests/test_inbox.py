import uuid

from inbox import dispatch_inbox
from tests.test_api import app,shop,send,register
from tests.test_growth import sql
from tests.test_wallet_campaigns import Provider,provider


class InboxProvider(Provider):
    def set_webhook(self,instance,url,token):self.token=token;return 201,{}


def setup(c):
    fake=InboxProvider();c.application.extensions['evolution']=fake
    sql(c,"UPDATE stores SET wa_instance='test-instance'")
    assert send(c,'POST','/api/admin/inbox/connect',{}).status_code==200
    return fake


def event(message='menu',eid=None,**keys):
    return {'event':'messages.upsert','instance':'test-instance','data':{'key':{'id':eid or uuid.uuid4().hex,'remoteJid':'5511999999999@s.whatsapp.net','fromMe':False,**keys},'pushName':'Cliente da conversa','message':{'conversation':message}}}


def test_authenticated_webhook_dedup_handoff_and_human_reply_queue(shop):
    c,pid=shop;fake=setup(c)
    assert 'inbox_hook_hash' not in c.get('/api/store/minha-loja').json['store']
    assert c.post('/webhooks/inbox/1',json=event()).status_code==401
    headers={'X-Webhook-Token':fake.token};body=event()
    assert send(c,'PUT','/api/admin/inbox/bot',{'enabled':True}).status_code==200
    assert c.post('/webhooks/inbox/1',json={**body,'instance':'other-instance'},headers=headers).status_code==403
    assert c.post('/webhooks/inbox/1',json=body,headers=headers).status_code==200
    assert c.post('/webhooks/inbox/1',json=body,headers=headers).json['duplicate']
    thread=c.get('/api/admin/inbox').json['threads'][0]
    assert thread['unread']==1
    assert len(c.get(f"/api/admin/inbox/{thread['id']}").json['messages'])==2
    assert c.post('/webhooks/inbox/1',json=event('ATENDENTE'),headers=headers).status_code==200
    assert dispatch_inbox(c.application)['sent']==0 and fake.calls==[]
    assert send(c,'POST',f"/api/admin/inbox/{thread['id']}/reply",{'message':'Olá, como posso ajudar?'},uuid.uuid4().hex).status_code==409
    assert send(c,'POST',f"/api/admin/inbox/{thread['id']}/claim",{'claim':True}).status_code==200
    key=uuid.uuid4().hex;url=f"/api/admin/inbox/{thread['id']}/reply"
    assert send(c,'POST',url,{'message':'Olá, como posso ajudar?'},key).status_code==202
    assert send(c,'POST',url,{'message':'Olá, como posso ajudar?'},key).status_code==200
    assert send(c,'POST',url,{'message':'Outra resposta'},key).status_code==409
    assert dispatch_inbox(c.application)['sent']==1
    assert dispatch_inbox(c.application)['sent']==0 and len(fake.calls)==1
    messages=c.get(f"/api/admin/inbox/{thread['id']}").json['messages']
    assert messages[0]['status']=='sent'
    stranger=c.application.test_client();register(stranger,slug='loja-outra',email='other@example.com')
    assert stranger.get(f"/api/admin/inbox/{thread['id']}").status_code==404
    assert c.post('/webhooks/inbox/1',json=event(fromMe=True),headers=headers).json['ignored']
    assert c.post('/webhooks/inbox/1',json=event(remoteJid='12345@g.us'),headers=headers).json['ignored']


def test_keyword_response_and_uncertain_reply_are_not_sent_twice(shop):
    c,pid=shop;fake=setup(c);headers={'X-Webhook-Token':fake.token}
    send(c,'PUT','/api/admin/inbox/bot',{'enabled':True})
    c.post('/webhooks/inbox/1',json=event('cardápio'),headers=headers)
    assert dispatch_inbox(c.application)['sent']==1
    assert '/loja/minha-loja' in fake.calls[-1][2]
    assert dispatch_inbox(c.application)['sent']==0
    tid=c.get('/api/admin/inbox').json['threads'][0]['id']
    send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True})
    send(c,'POST',f'/api/admin/inbox/{tid}/reply',{'message':'Resposta com falha simulada'},uuid.uuid4().hex)
    fake.fail=True
    assert dispatch_inbox(c.application)['uncertain']==1
    assert dispatch_inbox(c.application)['sent']==0 and len(fake.calls)==2
