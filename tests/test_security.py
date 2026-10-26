"""Adversarial regressions. All stores, credentials and destinations are synthetic."""
import io
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.test_api import app, shop, payload, register, send
from tests.test_business import make_order, advance
from tests.test_growth import sql


def test_public_store_never_includes_billing_or_future_internal_fields(shop):
    c, pid = shop
    sql(c, "UPDATE stores SET sub_pix_id='private-id',sub_pix_code='private-billing-code',sub_pix_expires='2999-01-01',subscribed_at='2026-10-01T12:00:00Z'")
    order = send(c, 'POST', '/api/store/minha-loja/orders', payload(pid), 'security-order-key-123').json
    for path in ('/api/store/minha-loja', '/api/track/' + order['token']):
        public = c.application.test_client().get(path).json['store']
        assert not {'sub_pix_id', 'sub_pix_code', 'sub_pix_expires', 'subscribed_at', 'owner_id', 'mp_token', 'mp_webhook_key', 'wa_instance', 'inbox_hook_hash'} & public.keys()
        assert public['name'] == 'Minha Loja' and 'payments' in public


@pytest.mark.parametrize('endpoint', [
    'https://127.0.0.1/private', 'https://[::1]/private', 'https://169.254.169.254/latest',
    'https://internal.example/private', 'https://fcm.googleapis.com.attacker.test/send',
    'https://fcm.googleapis.com@attacker.test/send', 'https://fcm.googleapis.com:8443/send',
    'https://fcm.googleapis.com/send#fragment',
])
def test_push_cannot_target_arbitrary_servers(shop, endpoint):
    c, _ = shop
    response = send(c, 'POST', '/api/admin/push/subscribe', {
        'endpoint': endpoint, 'keys': {'p256dh': 'B'*87, 'auth': 'a'*22}})
    assert response.status_code == 400
    assert not sql(c, 'SELECT id FROM push_subscriptions')


def test_logout_invalidates_a_copied_cookie_without_logging_out_other_devices(shop):
    c, _ = shop
    cookie = c.get_cookie('session').value
    stolen = c.application.test_client()
    stolen.set_cookie('session', cookie)
    second = c.application.test_client()
    assert send(second, 'POST', '/api/auth/login', {'email':'owner@example.com','password':'uma-senha-segura'}).status_code == 200
    assert stolen.get('/api/admin/store').status_code == 200
    assert send(c, 'POST', '/api/auth/logout', {}).status_code == 200
    assert stolen.get('/api/admin/store').status_code == 401
    assert stolen.get('/api/session').json['user'] is None
    assert second.get('/api/admin/store').status_code == 200


def test_loyalty_does_not_disclose_or_spend_another_persons_rewards(shop):
    c, pid = shop
    store = c.get('/api/admin/store').json['store']
    assert send(c, 'PUT', '/api/admin/store', {**store,'loyalty_enabled':True,'loyalty_goal':2,'loyalty_reward':700}).status_code == 200
    for _ in range(2):
        order = make_order(c, pid)
        advance(c, order['id'], 'preparing', 'ready', 'delivering', 'completed')
        assert send(c,'PATCH',f"/api/admin/orders/{order['id']}",{'paid':True}).status_code == 200
    public = c.application.test_client()
    path = '/api/store/minha-loja/quote'
    unverified = send(public, 'POST', path, payload(pid)).json
    assert unverified['loyalty'] is None and unverified['loyalty_discount'] == 0
    token = 'verified-only-test-wallet-session-token-123456789'
    import hashlib
    sql(c, 'INSERT INTO wallet_sessions(store_id,phone,token_hash,expires_at) VALUES(?,?,?,?)',
        (store['id'],'11999999999',hashlib.sha256(token.encode()).hexdigest(),(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()))
    checked = send(public, 'POST', path, payload(pid,wallet_token=token)).json
    assert checked['loyalty_discount'] == 700
    assert send(public, 'POST', path, payload(pid,phone='11988888888',wallet_token=token)).status_code == 403
    created = send(public, 'POST', '/api/store/minha-loja/orders', payload(pid), 'unverified-reward-key-12')
    assert created.status_code == 201 and created.json['total'] == unverified['total']
    assert public.get('/api/track/'+created.json['token']).json['order']['loyalty'] is None


def test_connectors_never_forward_credentials_to_a_redirect():
    from connectors import http
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get('apikey')))
            self.send_response(302 if self.path == '/start' else 200)
            self.send_header('Location', '/stolen')
            self.end_headers()
            self.wfile.write(b'{}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        status, _ = http('GET', f'http://127.0.0.1:{server.server_port}/start', {'apikey':'test-only-secret'})
        assert status == 302
        assert calls == [('/start','test-only-secret')]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_invalid_persisted_push_never_reaches_network(shop, monkeypatch):
    from notify import deliver
    c, _ = shop
    def unexpected(*args, **kwargs):
        pytest.fail('An unapproved endpoint must never reach webpush')
    monkeypatch.setattr('pywebpush.webpush',unexpected)
    bad={'endpoint':'https://127.0.0.1/private','p256dh':'B'*87,'auth':'a'*22}
    assert deliver(c.application.config,[bad],{'title':'synthetic'}) == [bad['endpoint']]


def test_push_network_session_blocks_redirects_and_unknown_hosts(monkeypatch):
    from notify import PushSession
    calls=[]
    def record(self,method,url,*args,**kwargs):
        calls.append((url,kwargs['allow_redirects']))
    monkeypatch.setattr('requests.Session.request',record)
    with PushSession() as session:
        session.post('https://fcm.googleapis.com/fcm/send/test',allow_redirects=True)
        with pytest.raises(ValueError):session.post('https://127.0.0.1/private')
    assert calls == [('https://fcm.googleapis.com/fcm/send/test',False)]


def test_remote_upload_response_is_bounded_and_malformed_response_is_safe(shop,monkeypatch):
    from storage import put_image
    from werkzeug.exceptions import ServiceUnavailable
    c,_=shop
    config={**c.application.config,'STORAGE_UPLOAD_URL':'https://storage.example.test/upload',
        'STORAGE_UPLOAD_TOKEN':'test-only-upload-token-with-32-characters','STORAGE_PUBLIC_URL':'https://storage.example.test/photos'}
    for raw in (b'x'*65537,b'[]',b'invalid-json'):
        monkeypatch.setattr('storage.urlopen',lambda *a,**k:io.BytesIO(raw))
        with c.application.app_context(),pytest.raises(ServiceUnavailable):
            put_image(config,1,'a'*32+'.webp',b'synthetic')


def test_sensitive_request_paths_are_not_access_log_atoms(app):
    from flask import request
    with app.test_client() as c:
        c.get('/pedido/synthetic-private-token?secret=not-for-logs')
        assert request.environ['sca.log_route'] == '/pedido/<token>'
        c.get('/api/admin/customers/11999999999/orders')
        assert request.environ['sca.log_route'] == '/api/admin/customers/<phone>/orders'


def test_every_merchant_and_platform_route_rejects_anonymous_access(app):
    import re
    c=app.test_client()
    checked=0
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith(('/api/admin/','/api/platform/')):
            continue
        path=re.sub(r'<(?:[^:>]+:)?[^>]+>','1',rule.rule)
        method=next(m for m in ('GET','POST','PUT','PATCH','DELETE') if m in rule.methods)
        response=send(c,method,path,{}) if method!='GET' else c.get(path)
        assert response.status_code in (401,403),(method,path,response.status_code)
        checked+=1
    assert checked>120


def test_unknown_new_store_column_is_not_implicitly_published(shop):
    c,_=shop
    sql(c,"ALTER TABLE stores ADD COLUMN future_internal_secret TEXT DEFAULT 'synthetic-secret'")
    assert 'future_internal_secret' not in c.application.test_client().get('/api/store/minha-loja').json['store']


def test_password_change_attempts_are_limited_per_account(shop):
    c,_=shop
    c.application.config['RATE_LIMIT_ENABLED']=True
    for _ in range(10):
        assert send(c,'PUT','/api/auth/password',{'current_password':'wrong','new_password':'a-new-test-password'}).status_code==400
    assert send(c,'PUT','/api/auth/password',{'current_password':'wrong','new_password':'a-new-test-password'}).status_code==429


def test_runtime_and_schema_connections_require_configured_tls(monkeypatch):
    from database import Postgres, initialize
    class ConnectionObserved(Exception):
        pass
    calls=[]
    def observe(*args,**kwargs):
        calls.append(kwargs)
        assert kwargs.get('sslmode')=='require'
        raise ConnectionObserved
    monkeypatch.setattr('database.psycopg.connect',observe)
    config={'DATABASE_URL':'postgresql://synthetic.example.test/db?sslmode=disable','DATABASE_SCHEMA':'synthetic','DATABASE_SSLMODE':'require'}
    for connect in (Postgres,initialize):
        with pytest.raises(ConnectionObserved):connect(config)
    assert len(calls)==2


def test_production_rejects_plaintext_database_setting(monkeypatch,tmp_path):
    from app import create_app
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('SECRET_KEY','synthetic-production-test-secret-with-more-than-32-characters')
    with pytest.raises(RuntimeError,match='TLS'):
        create_app({'DATABASE_URL':'postgresql://synthetic.example.test/db','DATABASE_SSLMODE':'disable','UPLOAD_DIR':str(tmp_path)})
