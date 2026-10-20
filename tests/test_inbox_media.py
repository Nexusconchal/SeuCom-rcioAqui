import base64
import io
import json
import uuid

import pytest
from PIL import Image

from inbox import dispatch_inbox
from inbox_media import MAX_MEDIA, validate_media
from tests.test_api import app, shop, send, register, session_token, payload
from tests.test_growth import sql
from tests.test_inbox import InboxProvider, event, setup


def photo():
    output=io.BytesIO()
    Image.new('RGB',(12,10),'orange').save(output,'PNG')
    return output.getvalue()


def audio():
    # A minimal WAV header/container: this is not sent to a real account.
    import wave
    output=io.BytesIO()
    with wave.open(output,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000)
        stream.writeframes(b'\0\0'*80)
    return output.getvalue()


class MediaProvider(InboxProvider):
    def __init__(self):super().__init__();self.media_calls=[];self.downloads=[];self.bad=False
    def send_media(self,instance,phone,media,caption=''):
        self.media_calls.append((instance,phone,media,caption))
        return (201,{}) if self.bad else (201,{'key':{'id':'local-media-id'}})
    def get_media(self,instance,key):
        self.downloads.append((instance,key))
        return 200,{'base64':base64.b64encode(b'<svg>bad</svg>' if self.bad else photo()).decode(),'mimetype':'image/png','fileName':'foto.png'}


def media_setup(c):
    old=setup(c);fake=MediaProvider();fake.token=old.token;c.application.extensions['evolution']=fake
    value=event('Olá')
    assert c.post('/webhooks/inbox/1',json=value,headers={'X-Webhook-Token':fake.token}).status_code==200
    tid=c.get('/api/admin/inbox').json['threads'][0]['id']
    assert send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True}).status_code==200
    return fake,tid


def upload(c,tid,raw=None,mime='image/png',key=None,caption=''):
    return c.post(f'/api/admin/inbox/{tid}/attachment',data={'file':(io.BytesIO(raw if raw is not None else photo()),'foto.png',mime),'caption':caption},
                  headers={'X-CSRF-Token':session_token(c),'Idempotency-Key':key or uuid.uuid4().hex})


def test_private_outgoing_photo_queue_preview_dedup_dispatch_and_erase(shop):
    c,pid=shop;fake,tid=media_setup(c);key=uuid.uuid4().hex
    r=upload(c,tid,key=key,caption='Seu pedido pronto');assert r.status_code==202,r.json
    assert fake.media_calls==[]
    assert upload(c,tid,key=key,caption='Seu pedido pronto').status_code==200
    assert upload(c,tid,key=key,caption='Outra legenda').status_code==409
    messages=c.get(f'/api/admin/inbox/{tid}').json['messages'];m=messages[0]
    assert m['media']['kind']=='image' and m['media']['mime']=='image/webp'
    assert 'base64' not in json.dumps(m) and 'sha256' not in json.dumps(m)
    preview=c.get(m['media']['url']);assert preview.status_code==200
    assert preview.mimetype=='image/webp' and preview.headers['Cache-Control']=='no-store'
    assert preview.data.startswith(b'RIFF')
    partial=c.get(m['media']['url'],headers={'Range':'bytes=0-15'})
    assert partial.status_code==206 and len(partial.data)==16
    assert c.application.test_client().get(m['media']['url']).status_code==401
    assert 'media_data' not in m
    assert 'base64' not in sql(c,'SELECT media FROM inbox_messages WHERE id=?',(m['id'],))[0]['media']
    assert dispatch_inbox(c.application)['sent']==1
    assert dispatch_inbox(c.application)['sent']==0 and len(fake.media_calls)==1
    assert fake.media_calls[0][3]=='Seu pedido pronto'
    stranger=c.application.test_client();register(stranger,slug='outra',email='other@example.com')
    assert stranger.get(m['media']['url']).status_code==404
    assert upload(stranger,tid).status_code==404
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid),uuid.uuid4().hex).status_code==201
    assert send(c,'POST','/api/admin/customers/11999999999/anonymize',{}).status_code==200
    assert c.get(m['media']['url']).status_code==404
    assert not sql(c,"SELECT media FROM inbox_messages WHERE media!=''")


def test_incoming_media_retains_only_selector_handoff_and_authenticates_download(shop):
    c,pid=shop;fake,tid=media_setup(c)
    send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':False})
    send(c,'PUT','/api/admin/inbox/bot',{'enabled':True})
    value=event();value['data']['message']={'imageMessage':{'mimetype':'image/png','fileLength':200,'caption':'Foto do lanche','url':'https://127.0.0.1/private','mediaKey':'do-not-retain'}}
    assert c.post('/webhooks/inbox/1',json=value,headers={'X-Webhook-Token':fake.token}).status_code==200
    data=c.get(f'/api/admin/inbox/{tid}').json;assert data['thread']['state']=='human'
    m=data['messages'][0];assert m['media']['kind']=='image' and m['body']=='[Foto recebida] Foto do lanche'
    stored=sql(c,'SELECT media FROM inbox_messages WHERE id=?',(m['id'],))[0]['media']
    assert '127.0.0.1' not in stored and 'do-not-retain' not in stored
    assert c.get(m['media']['url']).status_code==200
    assert fake.downloads[0][1]=={'id':value['data']['key']['id'],'remoteJid':'5511999999999@s.whatsapp.net','fromMe':False}
    fake.bad=True;assert c.get(m['media']['url']).status_code==502
    assert send(c,'DELETE',f'/api/admin/inbox/{tid}',{}).status_code==200
    assert c.get(m['media']['url']).status_code==404


@pytest.mark.parametrize('wrapper',['ephemeralMessage','viewOnceMessage','viewOnceMessageV2','viewOnceMessageV2Extension'])
def test_private_or_single_view_media_is_not_downloaded(shop,wrapper):
    c,pid=shop;fake,tid=media_setup(c)
    value=event();value['data']['message']={wrapper:{'message':{'imageMessage':{'mimetype':'image/png','fileLength':100}}}}
    assert c.post('/webhooks/inbox/1',json=value,headers={'X-Webhook-Token':fake.token}).status_code==200
    assert c.get(f'/api/admin/inbox/{tid}').json['messages'][0]['media'] is None
    assert fake.downloads==[] and not sql(c,"SELECT id FROM inbox_messages WHERE media!=''")


def test_upload_rejects_spoofed_oversized_unclaimed_and_audio_caption(shop):
    c,pid=shop;fake,tid=media_setup(c)
    assert upload(c,tid,raw=b'<svg>bad</svg>',mime='image/png').status_code==400
    assert upload(c,tid,raw=b'ID3'+b'0'*MAX_MEDIA,mime='audio/mpeg').status_code==400
    assert upload(c,tid,raw=photo(),mime='audio/ogg').status_code==400
    assert upload(c,tid,raw=photo(),mime='image/svg+xml').status_code==400
    assert upload(c,tid,raw=audio(),mime='audio/wav',caption='Not supported').status_code==400
    assert upload(c,tid,raw=audio(),mime='audio/wav').status_code==202
    send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':False})
    assert upload(c,tid).status_code==409
    assert fake.media_calls==[]


def test_media_pause_review_and_uncertain_results_do_not_resend(shop):
    c,pid=shop;fake,tid=media_setup(c)
    r=upload(c,tid);assert r.status_code==202
    assert send(c,'PUT','/api/admin/inbox/delivery',{'enabled':False}).status_code==200
    assert dispatch_inbox(c.application)['sent']==0
    assert send(c,'PUT','/api/admin/inbox/delivery',{'enabled':True}).status_code==200
    assert c.get(f'/api/admin/inbox/{tid}').json['messages'][0]['status']=='held'
    assert send(c,'POST',f"/api/admin/inbox/messages/{r.json['id']}/action",{'action':'queue'}).status_code==200
    fake.bad=True
    assert dispatch_inbox(c.application)['uncertain']==1
    assert dispatch_inbox(c.application)['sent']==0 and len(fake.media_calls)==1


def test_media_validation_strips_metadata_and_normalizes_safe_name():
    result=validate_media(photo(),'image/png','../../x\r\nDanger.png')
    assert result['mime']=='image/webp' and result['name']=='x__Danger.webp'
    assert validate_media(audio(),'audio/wav','test.wav')['kind']=='audio'


def test_private_media_budget_is_enforced_before_queueing(shop,monkeypatch):
    c,pid=shop;fake,tid=media_setup(c)
    monkeypatch.setattr('inbox.STORE_MEDIA_BUDGET',32)
    assert upload(c,tid).status_code==409
    assert not sql(c,"SELECT id FROM inbox_messages WHERE direction='out'") and fake.media_calls==[]


def test_sent_upload_bytes_expire_without_deleting_history_or_uncertain_queue(shop):
    c,pid=shop;fake,tid=media_setup(c)
    first=upload(c,tid);second=upload(c,tid);third=upload(c,tid)
    for response,status in ((first,'sent'),(second,'cancelled'),(third,'uncertain')):
        sql(c,"UPDATE inbox_messages SET status=?,created_at='2020-01-01T00:00:00+00:00',sent_at=NULL WHERE id=?",(status,response.json['id']))
    assert dispatch_inbox(c.application)['sent']==0
    result=c.get(f'/api/admin/inbox/{tid}').json['messages']
    expired=[m for m in result if m['id'] in (first.json['id'],second.json['id'])]
    assert all(m['media']['available'] is False and m['body']=='[Foto enviada]' for m in expired)
    assert all(c.get(m['media']['url']).status_code==410 for m in expired)
    assert all(not sql(c,'SELECT media_data FROM inbox_messages WHERE id=?',(m['id'],))[0]['media_data'] for m in expired)
    assert sql(c,'SELECT media_data FROM inbox_messages WHERE id=?',(third.json['id'],))[0]['media_data']
    assert fake.media_calls==[]


def test_cashier_can_review_media_only_in_own_store_after_claim(shop):
    c,pid=shop;fake,tid=media_setup(c);created=upload(c,tid)
    assert send(c,'POST','/api/admin/team',{'name':'Caixa','email':'media-cashier@example.com','password':'senha-segura-nova','role':'cashier'}).status_code==201
    cashier=c.application.test_client()
    assert send(cashier,'POST','/api/auth/login',{'email':'media-cashier@example.com','password':'senha-segura-nova'}).status_code==200
    url=f"/api/admin/inbox/messages/{created.json['id']}/media"
    assert cashier.get(url).status_code==200
    assert upload(cashier,tid).status_code==409
    send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':False})
    assert send(cashier,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True}).status_code==200
    assert upload(cashier,tid).status_code==202


def test_evolution_media_transport_contract_bounded_no_redirect_credentials():
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from connectors import Evolution
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path,self.headers.get('apikey'),body))
            if self.path=='/redirect':
                self.send_response(302);self.send_header('Location','/stolen');self.end_headers();return
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            if self.path=='/large':
                try:self.wfile.write(b'x'*(6*1024*1024+1))
                except (BrokenPipeError,ConnectionResetError):pass
            else:self.wfile.write(json.dumps({'key':{'id':'confirmed'},'base64':base64.b64encode(photo()).decode(),'mimetype':'image/png'}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        provider=Evolution(f'http://127.0.0.1:{server.server_port}','test-only-secret')
        assert provider.get_media('loja 1',{'id':'media-id'})[0]==200
        assert received[-1][0]=='/chat/getBase64FromMediaMessage/loja%201'
        assert received[-1][2]=={'message':{'key':{'id':'media-id'}},'convertToMp4':False}
        assert provider.send_media('loja','11999999999',validate_media(photo(),'image/png'),'Confira')[0]==200
        assert received[-1][2]['number']=='5511999999999' and received[-1][2]['caption']=='Confira'
        assert provider.send_media('loja','11999999999',validate_media(audio(),'audio/wav'))[0]==200
        assert received[-1][0]=='/message/sendWhatsAppAudio/loja' and received[-1][2]['encoding'] is True
        assert provider._media_call('/redirect',{})==(0,{})
        assert not any(path=='/stolen' for path,_,_ in received)
        assert provider._media_call('/large',{})==(0,{})
        assert all(key=='test-only-secret' for _,key,_ in received)
    finally:server.shutdown();worker.join();server.server_close()
