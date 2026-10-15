import uuid
from urllib.parse import urlparse,parse_qs

from tests.test_api import app,shop,send,register,payload
from tests.test_growth import ingredient,balance,sql


def test_network_invite_requires_target_owner_and_one_time_acceptance(shop):
    c,pid=shop
    assert send(c,'POST','/api/admin/network',{'name':'Nossa rede','slug':'nossa-rede','description':'Unidades da cidade'}).status_code==200
    target=c.application.test_client();register(target,slug='outra-unidade',email='target@example.com')
    stranger=c.application.test_client();register(stranger,slug='terceira-loja',email='stranger@example.com')
    invite=send(c,'POST','/api/admin/network/invite',{'store_slug':'outra-unidade'}).json['url']
    token=parse_qs(urlparse(invite).query)['rede_convite'][0]
    assert send(stranger,'POST','/api/admin/network/accept',{'token':token}).status_code==404
    assert len(c.get('/api/network/nossa-rede').json['stores'])==1
    assert send(target,'POST','/api/admin/network/preview-invite',{'token':token}).json['invite']['name']=='Nossa rede'
    assert send(target,'POST','/api/admin/network/accept',{'token':token}).status_code==200
    public=c.get('/api/network/nossa-rede').json
    assert len(public['stores'])==2 and all('owner_id' not in s and 'billing_exempt' not in s for s in public['stores'])
    assert send(target,'POST','/api/admin/network/accept',{'token':token}).json['already_accepted']
    sid=target.get('/api/admin/store').json['store']['id']
    assert send(c,'DELETE',f'/api/admin/network/stores/{sid}',{}).status_code==200
    assert send(target,'POST','/api/admin/network/accept',{'token':token}).status_code==409
    assert len(c.get('/api/network/nossa-rede').json['stores'])==1


def test_fractional_flavours_reserve_exact_shared_ingredient_and_snapshot_cost(shop):
    c,pid=shop;iid=ingredient(c,stock=150,cost=10000)
    p=c.get('/api/admin/products').json['products'][0]
    p['extras']=[];p['unit_cost']=0;p['option_groups']=[{'id':'sabores','name':'Sabores','min':2,'max':2,'pricing':'average','recipe_share':True,
        'options':[{'id':'um','name':'Sabor um','price':1000,'unit_cost':None},{'id':'dois','name':'Sabor dois','price':2000,'unit_cost':None}]}]
    assert send(c,'PUT',f'/api/admin/products/{pid}',p).status_code==200
    # Both recipes consume the same ingredient. Half of each: 50 + 100 = 150.
    for oid,quantity in [('um',100),('dois',200)]:
        assert send(c,'PUT',f'/api/admin/products/{pid}/options/{oid}/recipe',{'ingredients':[{'ingredient_id':iid,'quantity':quantity}]}).status_code==200
    public=c.get('/api/store/minha-loja').json['products'][0]
    assert all(o['available'] for o in public['option_groups'][0]['options'])
    body=payload(pid,items=[{'product_id':pid,'quantity':1,'option_ids':['um','dois']}])
    r=send(c,'POST','/api/store/minha-loja/orders',body,uuid.uuid4().hex)
    assert r.status_code==201,r.json
    o=c.get('/api/admin/orders').json['orders'][0]
    assert o['subtotal']==4400 and o['items'][0]['unit_cost']==1500 and balance(c,iid)==0
    assert send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'status':'cancelled'}).status_code==200
    assert balance(c,iid)==150


def test_kitchen_per_item_readiness_and_sector_snapshot(shop):
    c,pid=shop
    r=send(c,'POST','/api/admin/products',{'name':'Suco de teste','price':1000,'production_sector':'Bar','active':True})
    second=r.json['id'];body=payload(pid,items=[{'product_id':pid,'quantity':1,'option_ids':[]},{'product_id':second,'quantity':1,'option_ids':[]}])
    assert send(c,'POST','/api/store/minha-loja/orders',body,uuid.uuid4().hex).status_code==201
    o=c.get('/api/admin/orders').json['orders'][0];items=o['items'];assert {i['production_sector'] for i in items}=={'Cozinha','Bar'}
    p=c.get('/api/admin/products').json['products'][1];p['production_sector']='Bebidas';send(c,'PUT',f'/api/admin/products/{second}',p)
    for item in items:
        assert send(c,'PATCH',f"/api/admin/order-items/{item['id']}/kitchen",{'state':'ready'}).status_code==409
        assert send(c,'PATCH',f"/api/admin/order-items/{item['id']}/kitchen",{'state':'preparing'}).status_code==200
        assert send(c,'PATCH',f"/api/admin/order-items/{item['id']}/kitchen",{'state':'ready'}).status_code==200
        status=c.get('/api/admin/orders').json['orders'][0]['status']
        assert status==('preparing' if item==items[0] else 'ready')
    updated=c.get('/api/admin/orders').json['orders'][0]
    assert {i['production_sector'] for i in updated['items']}=={'Cozinha','Bar'}
    assert [e['status'] for e in updated['events']]==['new','preparing','ready']
