import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.test_api import app, shop, send, register, payload
from tests.test_growth import sql
from tests.test_inbox import setup, event
from inbox_service import DEFAULTS, delivery_tick
from chat_orders import process_chat_orders, cart_key


def enable(c):
    fake=setup(c)
    settings=copy.deepcopy(DEFAULTS);settings['chat_enabled']=True
    assert send(c,'PUT','/api/admin/inbox/settings',settings).status_code==200
    assert send(c,'PUT','/api/admin/inbox/bot',{'enabled':True}).status_code==200
    return fake


def turn(c,fake,text,eid=None):
    response=c.post('/webhooks/inbox/1',json=event(text,eid),headers={'X-Webhook-Token':fake.token})
    assert response.status_code==200,response.json
    rows=sql(c,"SELECT body FROM inbox_messages WHERE direction='out' ORDER BY id DESC LIMIT 1")
    return rows[0]['body'] if rows else ''


def review(c,fake,mode='2',quantity='1'):
    assert 'Escolha pelo número' in turn(c,fake,'FAZER PEDIDO')
    assert 'Adicionais' in turn(c,fake,'1')
    assert 'Quantas unidades' in turn(c,fake,'1')
    assert 'observação' in turn(c,fake,quantity)
    assert 'Sua sacola' in turn(c,fake,'0')
    assert 'Como quer receber' in turn(c,fake,'2')
    text=turn(c,fake,mode)
    if mode=='1':
        assert 'endereço completo' in text
        assert 'Observação do pedido' in turn(c,fake,'Rua Exemplo, 12, Centro')
    else:assert 'Observação do pedido' in text
    assert 'Como vai pagar' in turn(c,fake,'0')
    return turn(c,fake,'1')  # fixture's first payment is Pix manual


def test_confirm_creates_standard_order_once_with_options_and_stock(shop):
    c,pid=shop;fake=enable(c)
    summary=review(c,fake,'1')
    assert '39,00' in summary and 'CONFIRMAR' in summary and 'Bacon' in summary and 'Pagamento: Pix' in summary
    assert not sql(c,'SELECT id FROM orders')
    assert 'Confirmação recebida' in turn(c,fake,'CONFIRMAR','confirm-one')
    assert 'já está sendo processada' in turn(c,fake,'CONFIRMAR','confirm-two')
    assert process_chat_orders(c.application)==1
    assert process_chat_orders(c.application)==0
    order=sql(c,'SELECT * FROM orders')[0]
    assert order['total']==3900 and order['source']=='whatsapp' and order['phone']=='11999999999'
    assert sql(c,'SELECT stock FROM products WHERE id=?',(pid,))[0]['stock']==4
    assert 'Bacon' in sql(c,'SELECT extras FROM order_items')[0]['extras']
    assert 'Pedido #1001 criado' in turn(c,fake,'CONFIRMAR')
    assert len(sql(c,'SELECT id FROM orders'))==1


def test_changed_price_requires_new_confirmation_and_never_silently_charges(shop):
    c,pid=shop;fake=enable(c);review(c,fake)
    sql(c,'UPDATE products SET price=4500 WHERE id=?',(pid,))
    turn(c,fake,'CONFIRMAR');assert process_chat_orders(c.application)==1
    assert not sql(c,'SELECT id FROM orders')
    assert 'preço mudou' in sql(c,"SELECT body FROM inbox_messages ORDER BY id DESC LIMIT 1")[0]['body']
    assert sql(c,'SELECT stock FROM products WHERE id=?',(pid,))[0]['stock']==5


@pytest.mark.parametrize('interrupt',['ATENDENTE','claim','pause','disable','close'])
def test_pending_confirmation_stops_on_handoff_pause_or_close(shop,interrupt):
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    tid=sql(c,'SELECT id FROM inbox_threads')[0]['id']
    if interrupt=='ATENDENTE':turn(c,fake,'ATENDENTE')
    elif interrupt=='claim':assert send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True}).status_code==200
    elif interrupt=='pause':assert send(c,'PUT','/api/admin/inbox/delivery',{'enabled':False}).status_code==200
    elif interrupt=='disable':assert send(c,'PUT','/api/admin/inbox/bot',{'enabled':False}).status_code==200
    else:assert send(c,'POST',f'/api/admin/inbox/{tid}/close',{}).status_code==200
    process_chat_orders(c.application)
    assert not sql(c,'SELECT id FROM orders')


def test_cancel_back_search_quantity_and_default_opt_in(shop):
    c,pid=shop;fake=setup(c);send(c,'PUT','/api/admin/inbox/bot',{'enabled':True})
    turn(c,fake,'FAZER PEDIDO')
    assert not sql(c,"SELECT key FROM platform_settings WHERE key LIKE 'inbox.cart.%'")
    settings=copy.deepcopy(DEFAULTS);settings['chat_enabled']=True;send(c,'PUT','/api/admin/inbox/settings',settings)
    tid=sql(c,'SELECT id FROM inbox_threads')[0]['id']
    # Enabling guided orders never steals an existing human handoff.
    assert send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':False}).status_code==200
    turn(c,fake,'FAZER PEDIDO');assert 'Burger' in turn(c,fake,'BUSCAR burger')
    turn(c,fake,'1');assert 'inválida' in turn(c,fake,'2')
    turn(c,fake,'0');assert '1 a 50' in turn(c,fake,'999')
    turn(c,fake,'1');turn(c,fake,'Sem cebola');assert 'Sua sacola' in turn(c,fake,'VOLTAR')
    assert 'cancelada' in turn(c,fake,'CANCELAR')
    assert not sql(c,"SELECT key FROM platform_settings WHERE key LIKE 'inbox.cart.%'")


def test_two_processors_only_create_one_and_crash_recovers_same_key(shop):
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _:process_chat_orders(c.application),range(2)))==1
    assert len(sql(c,'SELECT id FROM orders'))==1


def test_crash_after_commit_recovers_without_second_order_or_stock_decrement(shop):
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    original=c.application.extensions['chat_place_order']
    def interrupted(*args,**kwargs):
        original(*args,**kwargs)
        raise TimeoutError('controlled interruption after commit')
    c.application.extensions['chat_place_order']=interrupted
    assert process_chat_orders(c.application)==0
    assert len(sql(c,'SELECT id FROM orders'))==1
    row=sql(c,"SELECT key,value FROM platform_settings WHERE key LIKE 'inbox.cart.%'")[0]
    cart=json.loads(row['value']);cart['claimed_at']='2020-01-01T00:00:00+00:00'
    sql(c,'UPDATE platform_settings SET value=? WHERE key=?',(json.dumps(cart),row['key']))
    c.application.extensions['chat_place_order']=original
    assert process_chat_orders(c.application)==1
    assert len(sql(c,'SELECT id FROM orders'))==1
    assert sql(c,'SELECT stock FROM products WHERE id=?',(pid,))[0]['stock']==4


def test_handoff_between_worker_claim_and_order_transaction_still_stops_creation(shop):
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    tid=sql(c,'SELECT id FROM inbox_threads')[0]['id']
    original=c.application.extensions['chat_place_order']
    def handoff(*args,**kwargs):
        assert send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True}).status_code==200
        return original(*args,**kwargs)
    c.application.extensions['chat_place_order']=handoff
    process_chat_orders(c.application)
    assert not sql(c,'SELECT id FROM orders')


def test_http_error_after_commit_is_not_reported_as_a_missing_order(shop):
    from werkzeug.exceptions import BadGateway
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    original=c.application.extensions['chat_place_order']
    def after_commit(*args,**kwargs):
        original(*args,**kwargs)
        raise BadGateway('controlled post-commit notification failure')
    c.application.extensions['chat_place_order']=after_commit
    assert process_chat_orders(c.application)==1
    assert len(sql(c,'SELECT id FROM orders'))==1
    assert 'criado!' in sql(c,'SELECT body FROM inbox_messages ORDER BY id DESC LIMIT 1')[0]['body']


def test_created_order_receipt_survives_human_handoff_but_respects_sending_gate(shop):
    from inbox import dispatch_inbox
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR');process_chat_orders(c.application)
    tid=sql(c,'SELECT id FROM inbox_threads')[0]['id']
    send(c,'POST',f'/api/admin/inbox/{tid}/claim',{'claim':True})
    assert dispatch_inbox(c.application)['sent']==1
    assert 'criado!' in fake.calls[-1][2]
    assert len(sql(c,'SELECT id FROM orders'))==1


def test_cart_erasure_and_foreign_store_isolation(shop):
    c,pid=shop;fake=enable(c);review(c,fake,'1')
    stranger=c.application.test_client();register(stranger,slug='outra-loja',email='outra@example.com')
    assert stranger.get('/api/admin/inbox').json['threads']==[]
    # Customer exclusion also erases unpublished carts and their address.
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid),uuid.uuid4().hex).status_code==201
    assert send(c,'POST','/api/admin/customers/11999999999/anonymize',{}).status_code==200
    assert not sql(c,"SELECT key FROM platform_settings WHERE key LIKE 'inbox.cart.%'")


def test_worker_creates_order_and_sends_receipt_via_existing_queue(shop):
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    assert delivery_tick(c.application)['sent']>=1
    assert any('criado!' in call[2] for call in fake.calls)


@pytest.mark.parametrize('changed',['stock','closed','expired'])
def test_confirmation_revalidates_stock_open_state_and_age(shop,changed):
    c,pid=shop;fake=enable(c);review(c,fake);turn(c,fake,'CONFIRMAR')
    if changed=='stock':sql(c,'UPDATE products SET stock=0 WHERE id=?',(pid,))
    elif changed=='closed':sql(c,'UPDATE stores SET open=0 WHERE id=1')
    else:
        row=sql(c,"SELECT key,value FROM platform_settings WHERE key LIKE 'inbox.cart.%'")[0]
        cart=json.loads(row['value']);cart['submitted_at']='2020-01-01T00:00:00+00:00'
        sql(c,'UPDATE platform_settings SET value=? WHERE key=?',(json.dumps(cart),row['key']))
    process_chat_orders(c.application)
    assert not sql(c,'SELECT id FROM orders')


def test_required_options_neighborhood_and_cash_change(shop):
    c,pid=shop;fake=enable(c)
    products=c.get('/api/admin/products').json['products'];product=next(p for p in products if p['id']==pid)
    product['option_groups']=[{'id':'size','name':'Tamanho','min':1,'max':1,'options':[{'id':'large','name':'Grande','price':200}]}]
    assert send(c,'PUT',f'/api/admin/products/{pid}',product).status_code==200
    store=c.get('/api/admin/store').json['store'];store.update(payments=['cash'],delivery_zones=[{'name':'Centro','fee':700}])
    assert send(c,'PUT','/api/admin/store',store).status_code==200
    turn(c,fake,'FAZER PEDIDO');assert 'Tamanho' in turn(c,fake,'1')
    assert 'inválida' in turn(c,fake,'0')
    assert 'Adicionais' in turn(c,fake,'1')
    turn(c,fake,'0');turn(c,fake,'1');turn(c,fake,'0');turn(c,fake,'2')
    assert 'Centro' in turn(c,fake,'1')
    turn(c,fake,'1');turn(c,fake,'Rua Teste, 12, Centro');turn(c,fake,'0');turn(c,fake,'1')
    assert '38,00' in turn(c,fake,'50,00')
    turn(c,fake,'CONFIRMAR');process_chat_orders(c.application)
    order=sql(c,'SELECT * FROM orders')[0]
    assert order['change_for']==5000 and order['delivery_fee']==700 and order['subtotal']==3100


def test_free_ai_is_opt_in_and_returns_only_current_catalog_values(shop):
    c,pid=shop;c.application.config['OPENROUTER_API_KEY']='local-fake-key'
    calls=[]
    def model(body,key):
        calls.append(body)
        return 200,{'model':'example/model:free','choices':[{'message':{'content':json.dumps({'intent':'catalog','product_ids':[pid]})}}]}
    c.application.extensions['openrouter_http']=model
    url='/api/admin/inbox/catalog-lookup'
    assert send(c,'POST',url,{'question':'Burger'}).json['mode']=='local' and not calls
    settings=copy.deepcopy(DEFAULTS);settings['ai_enabled']=True;send(c,'PUT','/api/admin/inbox/settings',settings)
    result=send(c,'POST',url,{'question':'Um lanche com bacon'})
    assert result.status_code==200 and result.json['mode']=='ai' and '29,00' in result.json['reply']
    assert calls[0]['model']=='openrouter/free' and 'models' not in calls[0] and 'tools' not in calls[0]
    assert 'phone' not in json.dumps(calls[0]) and 'local-fake-key' not in json.dumps(result.json)
    for question in ('rua Teste 12','email@example.com','11999999999','(11) 9999-9999'):
        assert send(c,'POST',url,{'question':question}).status_code==400
    assert not sql(c,'SELECT id FROM orders')


@pytest.mark.parametrize('failure',['quota','foreign','paid','bad_json','outage'])
def test_ai_failure_never_calls_paid_model_or_blocks_local_lookup(shop,failure):
    c,pid=shop;c.application.config['OPENROUTER_API_KEY']='fake'
    settings=copy.deepcopy(DEFAULTS);settings['ai_enabled']=True;send(c,'PUT','/api/admin/inbox/settings',settings)
    calls=[]
    def model(body,key):
        calls.append(body)
        if failure=='outage':raise TimeoutError()
        if failure=='quota':return 429,{}
        return 200,{'model':'paid/model' if failure=='paid' else 'x:free','choices':[{'message':{'content':'bad' if failure=='bad_json' else json.dumps({'intent':'catalog','product_ids':[99999]})}}]}
    c.application.extensions['openrouter_http']=model
    response=send(c,'POST','/api/admin/inbox/catalog-lookup',{'question':'burger'})
    assert response.status_code==200 and response.json['mode']=='local' and 'Burger' in response.json['reply'] and len(calls)==1


def test_ai_daily_quota_and_authentication_are_enforced(shop):
    c,pid=shop;c.application.config['OPENROUTER_API_KEY']='fake'
    settings=copy.deepcopy(DEFAULTS);settings['ai_enabled']=True;send(c,'PUT','/api/admin/inbox/settings',settings)
    calls=[]
    def model(body,key):
        calls.append(body)
        return 200,{'model':'x:free','choices':[{'message':{'content':json.dumps({'intent':'catalog','product_ids':[pid]})}}]}
    c.application.extensions['openrouter_http']=model
    url='/api/admin/inbox/catalog-lookup'
    for _ in range(10):assert send(c,'POST',url,{'question':'burger'}).json['mode']=='ai'
    assert send(c,'POST',url,{'question':'burger'}).json['reason']=='quota' and len(calls)==10
    assert c.application.test_client().post(url,json={'question':'burger'}).status_code in (401,403)


def test_free_transport_uses_http_contract_blocks_redirect_and_bounds_response(shop,monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler,HTTPServer
    import catalog_ai
    c,pid=shop;c.application.config['OPENROUTER_API_KEY']='local-transport-test'
    settings=copy.deepcopy(DEFAULTS);settings['ai_enabled']=True;send(c,'PUT','/api/admin/inbox/settings',settings)
    state={'mode':'ok','leaks':0,'requests':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            state['leaks']+=1;self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        def do_POST(self):
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers['Authorization']=='Bearer local-transport-test'
            state['requests'].append(value)
            if state['mode']=='redirect':
                self.send_response(302);self.send_header('Location','/leak');self.end_headers();return
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'x'*70000 if state['mode']=='big' else json.dumps({'model':'x:free','choices':[{'message':{'content':json.dumps({'intent':'catalog','product_ids':[pid]})}}]}).encode())
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(catalog_ai,'URL',f'http://127.0.0.1:{server.server_port}/ai')
    try:
        url='/api/admin/inbox/catalog-lookup'
        assert send(c,'POST',url,{'question':'burger'}).json['mode']=='ai'
        assert state['requests'][0]['model']=='openrouter/free'
        state['mode']='redirect';assert send(c,'POST',url,{'question':'burger'}).json['mode']=='local'
        state['mode']='big';assert send(c,'POST',url,{'question':'burger'}).json['mode']=='local'
        assert state['leaks']==0
    finally:server.shutdown();thread.join();server.server_close()
