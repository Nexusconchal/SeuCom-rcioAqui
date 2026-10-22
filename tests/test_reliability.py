"""Security boundaries and honest operator diagnostics; no real financial calls."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from tests.test_api import app, shop, register, send
from tests.test_growth import sql
from tests.test_online_payments import setup_online, create_order
from account_recovery import send_recovery


def mailer(c):
    received = []
    c.application.config['PUBLIC_URL'] = 'https://example.test'
    c.application.extensions['recovery_mailer'] = lambda config, email, url: received.append((email, url))
    return received


def complete(c, token, password='nova-senha-muito-segura'):
    return send(c, 'POST', '/api/auth/recovery/complete', {'token':token, 'password':password})


def test_recovery_no_provider_has_honest_same_response(app):
    c = app.test_client()
    assert register(c).status_code == 201
    app.config.update(SMTP_HOST='',SMTP_USER='',SMTP_PASSWORD='',SMTP_FROM='',RESEND_API_KEY='',MAIL_FROM='')
    assert not c.get('/api/session').json['recovery_available']
    known = send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'})
    unknown = send(c,'POST','/api/auth/recovery',{'email':'nobody@example.com'})
    assert known.status_code == unknown.status_code == 503
    assert known.json == unknown.json


def test_https_recovery_provider_contract_without_real_email(monkeypatch):
    captured=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return b'{"id":"test-message-id"}'
    class Opener:
        def open(self,req,timeout):
            captured.append((req,timeout))
            return Response()
    monkeypatch.setattr('account_recovery.build_opener',lambda *_:Opener())
    config={'RECOVERY_EMAIL_PROVIDER':'resend','MAIL_FROM':'teste@example.test','RESEND_API_KEY':'test-key-not-real'}
    send_recovery(config,'owner@example.test','https://example.test/entrar?recuperar=1#single-use-test')
    req,timeout=captured[0]
    assert req.full_url=='https://api.resend.com/emails' and timeout==8
    payload=json.loads(req.data)
    assert set(payload)=={'from','to','subject','text'}
    assert payload['to']==['owner@example.test']
    assert '#single-use-test' in payload['text']
    assert len(req.get_header('Idempotency-key'))==64


def test_recovery_single_use_fragment_and_session_revocation(shop):
    c, _ = shop
    received = mailer(c)
    old = c.application.test_client()
    assert send(old,'POST','/api/auth/login',{'email':'owner@example.com','password':'uma-senha-segura'}).status_code == 200
    r = send(c,'POST','/api/auth/recovery',{'email':'OWNER@example.com'})
    assert r.status_code == 200 and 'token' not in r.json
    token = urlsplit(received[0][1]).fragment
    assert urlsplit(received[0][1]).path == '/entrar'
    assert token not in urlsplit(received[0][1]).query
    row = sql(c,'SELECT * FROM account_tokens')[0]
    assert row['token_hash'] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(dict(row))
    assert c.post('/api/auth/recovery/complete',json={'token':token,'password':'nova-senha-muito-segura'}).status_code == 403
    assert complete(c,token).status_code == 200
    assert old.get('/api/admin/store').status_code == 401
    assert complete(c,token).status_code == 400
    assert send(c,'POST','/api/auth/login',{'email':'owner@example.com','password':'uma-senha-segura'}).status_code == 401
    assert send(c,'POST','/api/auth/login',{'email':'owner@example.com','password':'nova-senha-muito-segura'}).status_code == 200


def test_recovery_cooldown_expiry_failure_and_version_change(shop):
    c,_ = shop
    received=mailer(c)
    good=send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'})
    unknown=send(c,'POST','/api/auth/recovery',{'email':'unknown@example.com'})
    again=send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'})
    assert good.json == unknown.json == again.json and len(received)==1
    token=urlsplit(received[0][1]).fragment
    sql(c,"UPDATE account_tokens SET expires_at='2000-01-01T00:00:00+00:00'")
    assert complete(c,token).status_code==400
    sql(c,'DELETE FROM account_tokens')
    def failure(*_): raise OSError('smtp unavailable')
    c.application.extensions['recovery_mailer']=failure
    assert send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'}).json == good.json
    assert sql(c,'SELECT * FROM account_tokens')[0]['used_at']
    sql(c,'UPDATE users SET platform_admin=1')
    assert c.get('/api/platform/operations/health').json['mail_delivery_error']
    sql(c,'DELETE FROM account_tokens')
    received=mailer(c)
    send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'})
    token=urlsplit(received[0][1]).fragment
    sql(c,'UPDATE users SET auth_version=auth_version+1')
    assert complete(c,token).status_code==400


def test_recovery_concurrent_use_only_one_wins(shop):
    c,_=shop
    received=mailer(c)
    send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'})
    token=urlsplit(received[0][1]).fragment
    def run(_):
        return complete(c.application.test_client(),token).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(run,range(2)))
    assert sorted(codes)==[200,400]
    assert sql(c,'SELECT auth_version FROM users')[0]['auth_version']==2


def test_recovery_request_rate_limit_and_trusted_url(shop):
    c,_=shop
    received=mailer(c)
    c.application.config['PUBLIC_URL']='https://attacker@example.test'
    assert send(c,'POST','/api/auth/recovery',{'email':'owner@example.com'}).status_code==503
    assert not received
    c.application.config.update(PUBLIC_URL='https://example.test',RATE_LIMIT_ENABLED=True)
    for _ in range(5):
        assert send(c,'POST','/api/auth/recovery',{'email':'unknown@example.com'}).status_code==200
    assert send(c,'POST','/api/auth/recovery',{'email':'unknown@example.com'}).status_code==429


def test_setup_scoped_manual_checks_and_print_authorization(shop):
    c,pid=shop
    state=c.get('/api/admin/setup').json
    assert next(x for x in state['items'] if x['id']=='products')['done']
    assert not next(x for x in state['items'] if x['id']=='printing')['done']
    assert send(c,'POST','/api/admin/setup/check',{'item':'printing','checked':True}).status_code==200
    assert next(x for x in c.get('/api/admin/setup').json['items'] if x['id']=='printing')['done']
    assert send(c,'POST','/api/admin/setup/check',{'item':'payments','checked':True}).status_code==400
    assert not sql(c,'SELECT * FROM orders')
    c2=c.application.test_client()
    assert register(c2,'another-shop','other@example.com').status_code==201
    assert not next(x for x in c2.get('/api/admin/setup').json['items'] if x['id']=='printing')['done']
    provider=setup_online(c)
    order,_=create_order(c,pid)
    assert c.get('/api/admin/print-orders/'+str(order['id'])).status_code==200
    assert c2.get('/api/admin/print-orders/'+str(order['id'])).status_code==404
    assert c.application.test_client().get('/api/admin/print-orders/'+str(order['id'])).status_code==401


def test_receivables_released_pending_unknown_and_refund(shop):
    c,pid=shop
    provider=setup_online(c,'card')
    order,_=create_order(c,pid,'card_online')
    provider.approve_card(transaction_details={'net_received_amount':37.75},money_release_status='pending',money_release_date='2026-11-01T12:00:00Z')
    assert send(c,'POST',f"/api/admin/orders/{order['id']}/payment/check",{}).status_code==200
    r=c.get('/api/admin/receivables').json
    assert r['totals']['gross']==3900 and r['totals']['fees']==125
    assert r['totals']['pending']==3775 and r['totals']['released']==0
    assert r['transactions'][0]['release_at']=='2026-11-01T12:00:00+00:00'
    provider.payments[20001]['money_release_status']='released'
    assert send(c,'POST',f"/api/admin/orders/{order['id']}/payment/check",{}).status_code==200
    r=c.get('/api/admin/receivables').json
    assert r['totals']['released']==3775 and r['totals']['pending']==0
    provider.payments[20001]['transaction_amount_refunded']=10
    assert send(c,'POST',f"/api/admin/orders/{order['id']}/payment/check",{}).status_code==200
    r=c.get('/api/admin/receivables').json
    assert r['totals']['released']==0 and r['totals']['unknown']==1 and r['totals']['refunded']==1000
    # Malformed optional fields never block canonical payment reconciliation.
    provider.payments[20001].update(transaction_details={'net_received_amount':'masked'},money_release_status='anything',money_release_date='invalid')
    assert send(c,'POST',f"/api/admin/orders/{order['id']}/payment/check",{}).status_code==200
    r=c.get('/api/admin/receivables').json
    assert r['transactions'][0]['net_amount'] is None
    assert r['transactions'][0]['release_status']==''
    c2=c.application.test_client()
    assert register(c2,'another-shop','other@example.com').status_code==201
    assert c2.get('/api/admin/receivables').json['transactions']==[]
    assert c2.get('/api/admin/receivables').json['totals']['gross']==0
    assert c.get('/api/admin/receivables?days=9999').status_code==400


def test_operational_alerts_scoped_and_platform_protected(shop):
    c,pid=shop
    provider=setup_online(c)
    provider.timeout_pix=True
    order,_=create_order(c,pid)
    r=c.get('/api/admin/operations/health')
    assert r.status_code==200 and r.headers['X-Request-ID']
    assert r.json['counts']['payments_uncertain']==1
    assert any(a['code']=='payments' for a in r.json['alerts'])
    assert 'mail_ready' not in r.json and 'process_sample' not in r.json
    assert c.get('/api/platform/operations/health').status_code==403
    other=c.application.test_client()
    assert register(other,'another-shop','other@example.com').status_code==201
    assert other.get('/api/admin/operations/health').json['counts']['payments_uncertain']==0
    assert other.get('/api/admin/receivables').json['attempts']==[]
    sql(c,'UPDATE users SET platform_admin=1 WHERE id=?',(order['store_id'],))
    global_health=c.get('/api/platform/operations/health')
    assert global_health.status_code==200 and global_health.json['counts']['payments_uncertain']==1
    result=c.application.test_cli_runner().invoke(args=['operations-check'])
    assert result.exit_code==1 and 'payments_uncertain' in result.output
