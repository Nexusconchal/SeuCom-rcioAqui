import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from inbox import dispatch_inbox
from inbox_service import DEFAULTS, delivery_tick
from tests.test_api import app, shop, send, register
from tests.test_growth import sql
from tests.test_inbox import InboxProvider, event


def connect(client, enabled=False):
    fake=InboxProvider();client.application.extensions['evolution']=fake
    sql(client,"UPDATE stores SET wa_instance='test-instance' WHERE id=1")
    assert send(client,'POST','/api/admin/inbox/connect',{}).status_code==200
    if enabled:assert send(client,'PUT','/api/admin/inbox/delivery',{'enabled':True}).status_code==200
    return fake


def incoming(client, fake, text='ATENDENTE'):
    result=client.post('/webhooks/inbox/1',json=event(text),headers={'X-Webhook-Token':fake.token})
    assert result.status_code==200
    return client.get('/api/admin/inbox').json['threads'][0]['id']


def reply(client, tid, text='Vou conferir seu pedido.'):
    assert send(client,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True}).status_code==200
    result=send(client,'POST',f'/api/admin/inbox/{tid}/reply',{'message':text},uuid.uuid4().hex)
    assert result.status_code==202
    return result.json['id']


def test_activation_never_releases_historical_replies_without_review(shop):
    c,_=shop;fake=connect(c);tid=incoming(c,fake);mid=reply(c,tid)
    assert c.get('/api/admin/inbox').json['sending'] is False
    assert dispatch_inbox(c.application)['sent']==0 and fake.calls==[]
    assert send(c,'PUT','/api/admin/inbox/delivery',{'enabled':True}).status_code==200
    assert sql(c,'SELECT status FROM inbox_messages WHERE id=?',(mid,))[0]['status']=='held'
    assert dispatch_inbox(c.application)['sent']==0
    assert send(c,'POST',f'/api/admin/inbox/messages/{mid}/action',{'action':'queue'}).status_code==200
    assert dispatch_inbox(c.application)['sent']==1
    assert send(c,'POST',f'/api/admin/inbox/messages/{mid}/action',{'action':'queue'}).status_code==409
    assert dispatch_inbox(c.application)['sent']==0
    next_id=reply(c,tid)
    assert send(c,'PUT','/api/admin/inbox/delivery',{'enabled':False}).status_code==200
    assert dispatch_inbox(c.application)['sent']==0
    assert sql(c,'SELECT status FROM inbox_messages WHERE id=?',(next_id,))[0]['status']=='held'


def test_dispatchers_claim_each_reply_only_once(shop):
    c,_=shop;fake=connect(c,True);tid=incoming(c,fake)
    for i in range(6):reply(c,tid,'Resposta '+str(i))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:dispatch_inbox(c.application,10),range(2)))
    assert sum(r['sent'] for r in results)==6
    assert len(fake.calls)==6 and len({call[2] for call in fake.calls})==6


def test_custom_rules_preview_closed_hours_and_human_priority(shop):
    c,_=shop;fake=connect(c,True)
    settings=copy.deepcopy(DEFAULTS)
    settings['rules'].append({'id':'vegan','name':'Opção vegana','keywords':['opção vegana'],'enabled':True,'message':'Olá, {nome}! Confira na {loja}: {link}'})
    assert send(c,'PUT','/api/admin/inbox/settings',settings).status_code==200
    preview=send(c,'POST','/api/admin/inbox/preview',{'message':'Tem OPÇÃO VEGANA?'}).json
    assert 'Confira na Minha Loja' in preview['reply'] and '{nome}' not in preview['reply']
    assert fake.calls==[] and c.get('/api/admin/inbox').json['threads']==[]
    send(c,'PUT','/api/admin/inbox/bot',{'enabled':True})
    tid=incoming(c,fake,'Queria uma opção vegana, por favor')
    assert dispatch_inbox(c.application)['sent']==1
    assert c.post('/webhooks/inbox/1',json=event('quero um ATENDENTE para ajudar'),headers={'X-Webhook-Token':fake.token}).status_code==200
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['state']=='human'
    assert dispatch_inbox(c.application)['sent']==0
    sql(c,'UPDATE stores SET open=0 WHERE id=1')
    preview=send(c,'POST','/api/admin/inbox/preview',{'message':'olá'}).json
    assert 'fechada' in preview['reply']


@pytest.mark.parametrize('change',[
    lambda s:s.update(closed_message='{segredo}'),
    lambda s:s['rules'][0].update(keywords=['atendente']),
    lambda s:s['rules'][0].update(keywords=[' ']),
    lambda s:s['quick_replies'].append(s['quick_replies'][0]),
    lambda s:s['rules'][0].update(enabled='true'),
    lambda s:s.update(quick_replies=[{}]),
])
def test_invalid_settings_are_rejected_and_do_not_change_saved_config(shop,change):
    c,_=shop;settings=copy.deepcopy(DEFAULTS);change(settings)
    assert send(c,'PUT','/api/admin/inbox/settings',settings).status_code==400
    assert c.get('/api/admin/inbox').json['settings']==DEFAULTS


def test_assignment_settings_and_message_actions_are_tenant_scoped(shop):
    c,_=shop;fake=connect(c,True);tid=incoming(c,fake);mid=reply(c,tid)
    foreign=c.application.test_client();assert register(foreign,slug='outra',email='outra@example.com').status_code==201
    assert foreign.get('/api/admin/inbox').json['threads']==[]
    assert foreign.get(f'/api/admin/inbox/{tid}').status_code==404
    assert send(foreign,'POST',f'/api/admin/inbox/messages/{mid}/action',{'action':'cancel'}).status_code==404
    assert send(foreign,'POST',f'/api/admin/inbox/{tid}/assign',{'user_id':1}).status_code==404
    own=copy.deepcopy(DEFAULTS);own['closed_message']='Texto exclusivo da loja'
    assert send(c,'PUT','/api/admin/inbox/settings',own).status_code==200
    assert foreign.get('/api/admin/inbox').json['settings']==DEFAULTS
    assert send(c,'POST',f'/api/admin/inbox/{tid}/assign',{'user_id':2}).status_code==404
    assert send(c,'POST',f'/api/admin/inbox/{tid}/assign',{'user_id':1}).status_code==200
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['assigned_name']=='Dona da Loja'


def test_media_handoff_pagination_and_payload_validation(shop):
    c,_=shop;fake=connect(c,True);body=event();body['data']['message']={'imageMessage':{'caption':'Veja meu pedido'}}
    assert c.post('/webhooks/inbox/1',json=body,headers={'X-Webhook-Token':fake.token}).status_code==200
    tid=c.get('/api/admin/inbox').json['threads'][0]['id']
    assert c.get(f'/api/admin/inbox/{tid}').json['thread']['state']=='human'
    for i in range(105):
        sql(c,"INSERT INTO inbox_messages(store_id,thread_id,direction,body,external_id,status,created_at) VALUES(1,?,'in',?,?,'received','2026-10-17T10:00:00+00:00')",(tid,'Mensagem '+str(i),'page:'+str(i)))
    first=c.get(f'/api/admin/inbox/{tid}').json
    assert len(first['messages'])==100 and first['has_more']
    older=c.get(f"/api/admin/inbox/{tid}?before={first['messages'][-1]['id']}").json
    assert len(older['messages'])==6 and not older['has_more']
    assert c.get(f'/api/admin/inbox/{tid}?before=invalid').status_code==400
    for key in ([],{'remoteJid':[]},{'remoteJid':'123@lid','remoteJidAlt':[]}):
        bad=event();bad['data']['key']=key
        assert c.post('/webhooks/inbox/1',json=bad,headers={'X-Webhook-Token':fake.token}).status_code in (200,400)


def test_embedded_delivery_runs_once_and_stops_cleanly(shop):
    c,_=shop;fake=connect(c,True);tid=incoming(c,fake);reply(c,tid)
    ready=threading.Event();original=fake.send_text
    def fake_send(*args):
        result=original(*args);ready.set();return result
    fake.send_text=fake_send
    app=c.application;app.testing=False
    try:
        c.get('/health');first=app.extensions['inbox_dispatch_thread']
        c.get('/health');assert app.extensions['inbox_dispatch_thread'] is first
        assert ready.wait(5)
    finally:
        app.extensions['inbox_dispatch_stop'].set();first.join(timeout=5);app.testing=True
    assert not first.is_alive() and len(fake.calls)==1
    assert c.get('/api/admin/inbox').json['delivery']['running']


def test_disconnect_pauses_sending_and_preserves_unattempted_reply(shop):
    c,_=shop;fake=connect(c,True);tid=incoming(c,fake);mid=reply(c,tid)
    fake.logout=lambda instance:(200,{})
    assert send(c,'DELETE','/api/admin/whatsapp',{}).status_code==200
    state=c.get('/api/admin/inbox').json
    assert not state['sending'] and not state['configured'] and not state['linked']
    assert sql(c,'SELECT status FROM inbox_messages WHERE id=?',(mid,))[0]['status']=='held'
    assert dispatch_inbox(c.application)['sent']==0


def test_expired_replies_require_review_and_duplicate_activation_is_safe(shop):
    c,_=shop;fake=connect(c,True);tid=incoming(c,fake);mid=reply(c,tid)
    assert send(c,'PUT','/api/admin/inbox/delivery',{'enabled':True}).status_code==200
    assert sql(c,'SELECT status FROM inbox_messages WHERE id=?',(mid,))[0]['status']=='queued'
    sql(c,"UPDATE inbox_messages SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?",(mid,))
    assert dispatch_inbox(c.application)['sent']==0
    assert send(c,'POST',f'/api/admin/inbox/messages/{mid}/action',{'action':'queue'}).status_code==200
    assert dispatch_inbox(c.application)['sent']==1
    assert sql(c,'SELECT created_at FROM inbox_messages WHERE id=?',(mid,))[0]['created_at'].startswith('2020')


def test_cashier_cannot_enable_delivery_edit_bot_or_assign_foreign_staff(shop):
    c,_=shop;fake=connect(c,True);tid=incoming(c,fake)
    created=send(c,'POST','/api/admin/team',{'name':'Caixa','email':'cashier@example.com','password':'senha-segura-nova','role':'cashier'})
    assert created.status_code==201
    cashier=c.application.test_client();assert send(cashier,'POST','/api/auth/login',{'email':'cashier@example.com','password':'senha-segura-nova'}).status_code==200
    assert cashier.get('/api/admin/inbox/connection').json['connected']
    assert send(cashier,'PUT','/api/admin/inbox/delivery',{'enabled':True}).status_code==403
    assert send(cashier,'PUT','/api/admin/inbox/settings',copy.deepcopy(DEFAULTS)).status_code==403
    assert send(cashier,'POST',f'/api/admin/inbox/{tid}/assign',{'user_id':1}).status_code==403
    assert send(cashier,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True}).status_code==200
    assert send(cashier,'POST',f'/api/admin/inbox/{tid}/reply',{'message':'Resposta autorizada do caixa'},uuid.uuid4().hex).status_code==202
