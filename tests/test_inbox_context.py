import uuid

from tests.test_api import app, shop, register, payload, send
from tests.test_growth import sql
from tests.test_inbox import setup, event


def test_context_normalizes_phone_and_never_crosses_stores(shop):
    c,pid=shop;provider=setup(c)
    assert c.post('/webhooks/inbox/1',json=event('Quero pedir'),headers={'X-Webhook-Token':provider.token}).status_code==200
    tid=c.get('/api/admin/inbox').json['threads'][0]['id']
    assert c.get(f'/api/admin/inbox/{tid}/context').json['summary']['orders']==0
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid,phone='+55 (11) 99999-9999'),uuid.uuid4().hex).status_code==201
    sql(c,"UPDATE orders SET status='completed',paid=1")
    other=c.application.test_client();assert register(other,'outra-loja','other@example.com').status_code==201
    assert other.get(f'/api/admin/inbox/{tid}/context').status_code==404
    # Even a matching number in another store must not contribute to this customer.
    sql(c,"UPDATE orders SET phone='+55 (11) 99999-9999' WHERE store_id=2")
    response=c.get(f'/api/admin/inbox/{tid}/context');value=response.json
    assert response.headers['Cache-Control']=='no-store'
    assert value['summary']['orders']==1 and value['summary']['spent']==3900 and value['summary']['active']==0
    order=value['orders'][0]
    assert order['items'][0]['name']=='Burger'
    assert order['items'][0]['options']==['Bacon']
    assert not {'tracking_token','tracking_hash','payload_hash','idempotency_key','pix_provider_id'} & order.keys()
    assert c.application.test_client().get(f'/api/admin/inbox/{tid}/context').status_code==401


def test_context_keeps_cancelled_order_visible_without_counting_it_as_sale(shop):
    c,pid=shop;provider=setup(c)
    c.post('/webhooks/inbox/1',json=event('Oi'),headers={'X-Webhook-Token':provider.token})
    tid=c.get('/api/admin/inbox').json['threads'][0]['id']
    send(c,'POST','/api/store/minha-loja/orders',payload(pid),uuid.uuid4().hex)
    sql(c,"UPDATE orders SET status='cancelled'")
    value=c.get(f'/api/admin/inbox/{tid}/context').json
    assert value['summary']['orders']==0 and value['summary']['spent']==0
    assert value['orders'][0]['status']=='cancelled'
