import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from merchandising import apply_rules
from database import connect
from tests.test_api import app, shop, send, payload, register
from tests.test_growth import ingredient, recipe, balance, sql


def key():
    return uuid.uuid4().hex


def order(client,pid,**changes):
    result=send(client,'POST','/api/admin/orders',payload(pid,mode='pickup',phone='',**changes),key())
    assert result.status_code==201,result.json
    return client.get('/api/admin/orders').json['orders'][0]


def pay(client,o,amount,method='cash',**changes):
    return send(client,'POST',f"/api/admin/orders/{o['id']}/receipts",dict(amount=amount,method=method,**changes),key())


def test_partial_payments_refunds_shift_history_and_report(shop):
    c,pid=shop
    assert send(c,'POST','/api/admin/cash/open',{'opening':10000}).status_code==201
    assert send(c,'POST','/api/admin/cash/open',{'opening':0}).status_code==409
    o=order(c,pid)
    assert o['total']==3400 and not o['paid']
    first=pay(c,o,1000)
    assert first.status_code==201 and first.json['remaining']==2400
    assert not c.get('/api/admin/orders').json['orders'][0]['paid']
    assert pay(c,o,2401).status_code==409
    assert pay(c,o,2400,'pix').status_code==201
    assert c.get('/api/admin/orders').json['orders'][0]['paid']
    assert send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'paid':False}).status_code==409
    assert pay(c,o,501,'pix',kind='refund',original_id=first.json['id'],reason='Devolução').status_code==409
    refund=pay(c,o,500,kind='refund',original_id=first.json['id'],reason='Devolução parcial')
    assert refund.status_code==201 and refund.json['remaining']==500
    state=c.get('/api/admin/cash').json
    assert state['current']['expected_now']==10500
    assert state['current']['totals']=={'cash':500,'pix':2400}
    assert send(c,'POST','/api/admin/cash/adjust',{'delta':-10600,'reason':'Sangria'}).status_code==409
    assert send(c,'POST','/api/admin/cash/adjust',{'delta':-500,'reason':'Sangria'}).status_code==201
    assert send(c,'POST','/api/admin/cash/close',{'counted':9990}).status_code==400
    assert send(c,'POST','/api/admin/cash/close',{'counted':9990,'notes':'Faltaram dez centavos'}).json['difference']==-10
    assert pay(c,o,500).status_code==409
    assert send(c,'POST','/api/admin/cash/open',{'opening':0}).status_code==201
    assert pay(c,o,500,'card').status_code==201
    for fmt in ('xlsx','pdf'):
        r=c.get('/api/admin/report?format='+fmt+'&from=2026-01-01&to=2026-12-31')
        assert r.status_code==200
        assert r.data.startswith(b'PK' if fmt=='xlsx' else b'%PDF')
    assert c.get('/api/admin/report?from=2026-10-02&to=2026-10-01').status_code==400


def test_cash_idempotency_and_tenant_and_role_isolation(shop):
    c,pid=shop
    send(c,'POST','/api/admin/cash/open',{'opening':0})
    o=order(c,pid)
    k=key();body={'amount':1000,'method':'pix'}
    first=send(c,'POST',f"/api/admin/orders/{o['id']}/receipts",body,k)
    again=send(c,'POST',f"/api/admin/orders/{o['id']}/receipts",body,k)
    assert first.status_code==201 and again.status_code==200 and first.json['id']==again.json['id']
    assert send(c,'POST',f"/api/admin/orders/{o['id']}/receipts",{**body,'amount':1200},k).status_code==409
    assert c.post('/api/admin/cash/close',json={'counted':0}).status_code==403
    stranger=c.application.test_client();register(stranger,slug='outra-loja',email='other@example.com')
    assert pay(stranger,o,1000).status_code==404
    member=send(c,'POST','/api/admin/team',{'name':'Caixa Teste','email':'cash@example.com','password':'senha-segura-nova','role':'cashier'})
    assert member.status_code==201,member.json
    cashier=c.application.test_client();assert send(cashier,'POST','/api/auth/login',{'email':'cash@example.com','password':'senha-segura-nova'}).status_code==200
    assert cashier.get('/api/admin/cash').status_code==200
    assert cashier.get('/api/admin/pos/catalog').status_code==200
    assert cashier.get('/api/admin/report?format=pdf').status_code==200
    assert cashier.get('/api/admin/purchasing').status_code==403
    assert send(cashier,'POST','/api/admin/dining/tables',{'name':'Mesa 1'}).status_code==403


def test_concurrent_receipts_cannot_overpay(shop):
    c,pid=shop;send(c,'POST','/api/admin/cash/open',{'opening':0});o=order(c,pid)
    def attempt(_):
        client=c.application.test_client()
        send(client,'POST','/api/auth/login',{'email':'owner@example.com','password':'uma-senha-segura'})
        return pay(client,o,2000,'pix').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,range(2)))==[201,409]
    assert c.get('/api/admin/cash').json['orders'][0]['received']==2000


def test_dining_orders_transfer_close_and_public_account_rejection(shop):
    c,pid=shop
    t1=send(c,'POST','/api/admin/dining/tables',{'name':'Mesa 1'}).json['id']
    t2=send(c,'POST','/api/admin/dining/tables',{'name':'Mesa 2'}).json['id']
    aid=send(c,'POST',f'/api/admin/dining/tables/{t1}/open',{'customer':'Família Silva','guests':3}).json['id']
    assert send(c,'POST',f'/api/admin/dining/tables/{t1}/open',{'customer':'Outra família'}).status_code==409
    public=send(c,'POST','/api/store/minha-loja/orders',payload(pid,account_id=aid),key())
    assert public.status_code==400
    o=order(c,pid,account_id=aid)
    assert send(c,'POST',f'/api/admin/dining/accounts/{aid}/close',{}).status_code==409
    assert send(c,'POST',f'/api/admin/dining/accounts/{aid}/transfer',{'table_id':t2}).status_code==200
    send(c,'POST','/api/admin/cash/open',{'opening':0});assert pay(c,o,o['total'],'pix').status_code==201
    for status in ('preparing','ready','completed'):
        assert send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'status':status}).status_code==200
    assert send(c,'POST',f'/api/admin/dining/accounts/{aid}/close',{}).status_code==200
    assert all(t['account'] is None for t in c.get('/api/admin/dining').json['tables'])
    assert send(c,'POST','/api/admin/orders',payload(pid,account_id=aid,mode='pickup'),key()).status_code==409


def test_option_quantity_recipe_shared_demand_and_cancellation_snapshot(shop):
    c,pid=shop;iid=ingredient(c,stock=1000,cost=4000);recipe(c,pid,iid,100)
    p=c.get('/api/admin/products').json['products'][0];p['extras'][0]['max_quantity']=3
    assert send(c,'PUT',f'/api/admin/products/{pid}',p).status_code==200
    assert send(c,'PUT',f'/api/admin/products/{pid}/options/bacon/recipe',{'ingredients':[{'ingredient_id':iid,'quantity':200}]}).status_code==200
    body=payload(pid,quantity=2,items=[{'product_id':pid,'quantity':2,'option_ids':['bacon','bacon']}])
    q=send(c,'POST','/api/store/minha-loja/quote',body);assert q.status_code==200 and q.json['total']==8300
    created=send(c,'POST','/api/store/minha-loja/orders',body,key());assert created.status_code==201,created.json
    assert balance(c,iid)==0
    o=c.get('/api/admin/orders').json['orders'][0]
    assert o['items'][0]['unit_cost']==2000
    assert c.get('/api/store/minha-loja').json['products'][0]['extras'][0]['available'] is False
    assert send(c,'PUT',f'/api/admin/products/{pid}/options/bacon/recipe',{'ingredients':[]}).status_code==200
    assert send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'status':'cancelled'}).status_code==200
    assert balance(c,iid)==1000
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid,items=[{'product_id':pid,'quantity':1,'option_ids':['bacon']*4}]),key()).status_code==400


def test_programmed_prices_visibility_server_channels_and_auto_accept(shop):
    c,pid=shop
    rule={'name':'Almoço no delivery','product_id':pid,'kind':'price','channels':['web'],'days':list(range(7)),'start_time':'00:00','end_time':'00:00','value':1900}
    assert send(c,'POST','/api/admin/catalog-rules',rule).status_code==200
    assert c.get('/api/store/minha-loja').json['products'][0]['price']==1900
    assert c.get('/api/admin/pos/catalog').json['products'][0]['price']==2900
    assert send(c,'POST','/api/store/minha-loja/quote',payload(pid)).json['total']==2900
    assert send(c,'POST','/api/admin/catalog-rules',{**rule,'kind':'visibility','value':0,'priority':1}).status_code==200
    assert c.get('/api/store/minha-loja').json['products']==[]
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid),key()).status_code==409
    assert send(c,'PUT','/api/admin/operation-settings',{'timezone':'America/Manaus','auto_accept':True}).status_code==200
    o=order(c,pid);assert o['status']=='preparing' and len(o['events'])==2
    assert send(c,'PUT','/api/admin/operation-settings',{'timezone':'invalid'}).status_code==400
    conn=connect(c.application.config)
    try:
        store=conn.execute('SELECT * FROM stores').fetchone();p=conn.execute('SELECT * FROM products').fetchone()
        conn.execute("UPDATE catalog_rules SET start_time='22:00',end_time='02:00',days='[0]' WHERE kind='price'")
        # Tuesday 01:00 Manaus = Tuesday 05:00 UTC; overnight belongs to Monday.
        assert apply_rules(conn,store,p,'web',datetime(2026,10,6,5,tzinfo=timezone.utc))['price']==1900
        assert apply_rules(conn,store,p,'web',datetime(2026,10,6,7,tzinfo=timezone.utc))['price']==2900
    finally:conn.close()


def test_production_batch_and_financial_settlements_are_atomic_and_idempotent(shop):
    c,pid=shop;iid=ingredient(c,stock=2000,cost=2000)
    output=send(c,'POST','/api/admin/ingredients',{'name':'Molho pronto','unit':'kg','stock':0,'low_stock':100,'unit_cost':None}).json['id']
    assert send(c,'PUT',f'/api/admin/ingredients/{output}/production-recipe',{'ingredients':[{'ingredient_id':iid,'quantity':500}]}).status_code==200
    k=key();body={'quantity':1000}
    assert send(c,'POST',f'/api/admin/ingredients/{output}/produce',body,k).status_code==201
    assert send(c,'POST',f'/api/admin/ingredients/{output}/produce',body,k).status_code==200
    assert balance(c,iid)==1500 and balance(c,output)==1000
    row=next(i for i in c.get('/api/admin/ingredients').json['ingredients'] if i['id']==output)
    assert row['unit_cost']==1000
    assert send(c,'POST',f'/api/admin/ingredients/{output}/produce',{'quantity':4000},key()).status_code==409
    assert balance(c,iid)==1500 and balance(c,output)==1000
    supplier=send(c,'POST','/api/admin/suppliers',{'name':'Fornecedor Teste'}).json['id']
    bill=send(c,'POST','/api/admin/obligations',{'supplier_id':supplier,'description':'Compra de carne','kind':'payable','amount':10000,'due_on':'2026-11-10','category':'inventory'}).json['id']
    k=key();body={'amount':4000}
    assert send(c,'POST',f'/api/admin/obligations/{bill}/settle',body,k).status_code==201
    assert send(c,'POST',f'/api/admin/obligations/{bill}/settle',body,k).status_code==200
    assert send(c,'POST',f'/api/admin/obligations/{bill}/settle',{'amount':6001},key()).status_code==409
    assert send(c,'POST',f'/api/admin/obligations/{bill}/void',{}).status_code==409
    assert [dict(r) for r in sql(c,'SELECT amount,category FROM expenses')]==[{'amount':4000,'category':'inventory'}]
