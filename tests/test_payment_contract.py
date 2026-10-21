"""Exercise the real HTTP adapter against a local server, never Mercado Pago."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from payments import MercadoPago, PaymentError, safe_checkout_url


@pytest.fixture
def provider_http():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def handle_request(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            calls.append((self.command,self.path,dict(self.headers),json.loads(body) if body else None))
            if self.path=='/redirect':
                self.send_response(302);self.send_header('Location','/leaked');self.end_headers();return
            value=b'[' if self.path=='/invalid' else b'x'*(1024*1024+2) if self.path=='/large' else b'{"ok":true}'
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(value)));self.end_headers()
            try:self.wfile.write(value)
            except OSError:pass
        do_GET=do_POST=do_PUT=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    provider=MercadoPago();provider.base=f'http://127.0.0.1:{server.server_port}'
    try:yield provider,calls
    finally:server.shutdown();server.server_close();thread.join()


def test_connector_sends_hosted_checkout_refund_and_query_contract(provider_http):
    provider,calls=provider_http
    provider.create_preference('local-secret',{'items':[{'currency_id':'BRL'}]},'stable-create')
    provider.refund('local-secret',123,'stable-refund')
    provider.search_preferences('local-secret','sca & 1')
    provider.update_preference('local-secret','pref/other',{'expires':True})
    assert calls[0][0:2]==('POST','/checkout/preferences')
    assert calls[0][2]['Authorization']=='Bearer local-secret'
    assert calls[0][2]['X-Idempotency-Key']=='stable-create'
    assert calls[1][0:2]==('POST','/v1/payments/123/refunds')
    assert calls[1][2]['X-Idempotency-Key']=='stable-refund' and calls[1][3]=={}
    assert parse_qs(urlsplit(calls[2][1]).query)['external_reference']==['sca & 1']
    assert calls[3][0:2]==('PUT','/checkout/preferences/pref%2Fother')


def test_connector_never_forwards_credentials_on_redirect_or_trusts_bad_json(provider_http):
    provider,calls=provider_http
    for path in ('/redirect','/invalid','/large'):
        with pytest.raises(PaymentError):provider._call('GET',path,'local-secret')
    assert all(path!='/leaked' for _,path,_,_ in calls)


@pytest.mark.parametrize('url',[
    'http://www.mercadopago.com.br/checkout/x','https://www.mercadopago.com.br.attacker.test/checkout/x',
    'https://user@www.mercadopago.com.br/checkout/x','https://www.mercadopago.com.br:444/checkout/x',
    'javascript:alert(1)','https://www.mercadopago.com.br/unrelated','//www.mercadopago.com.br/checkout/x',
])
def test_checkout_rejects_redirect_outside_provider(url):
    assert not safe_checkout_url(url)
