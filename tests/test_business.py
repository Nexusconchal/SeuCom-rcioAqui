import json
import sqlite3
import uuid

from database import connect, initialize
from tests.test_api import app, shop, send, register, payload


def make_order(client,pid,**values):
    response=send(client,'POST','/api/store/minha-loja/orders',payload(pid,**values),uuid.uuid4().hex)
    assert response.status_code==201,response.json
    return client.get('/api/admin/orders').json['orders'][0]


def advance(client,oid,*statuses):
    for status in statuses:
        result=send(client,'PATCH',f'/api/admin/orders/{oid}',{'status':status})
        assert result.status_code==200,result.json


def key_for(client,scopes=None):
    response=send(client,'POST','/api/admin/integrations/keys',{'name':'MotoJá','scopes':scopes or ['orders:read','deliveries:write']})
    assert response.status_code==201,response.json
    return response.json


def test_platform_role_cannot_be_self_granted_and_tenant_isolation(app,shop):
    client,pid=shop
    other=app.test_client()
    assert register(other,'outra-loja','other@example.com').status_code==201
    assert other.get('/api/platform/summary').status_code==403
    assert client.get('/api/session').json['user']['platform_admin'] is False
    result=app.test_cli_runner().invoke(args=['grant-platform-admin','--email','owner@example.com'])
    assert result.exit_code==0,result.output
    assert client.get('/api/session').json['user']['platform_admin'] is True
    assert len(client.get('/api/platform/summary').json['stores'])==2
    assert other.get('/api/platform/summary').status_code==403
    oid=make_order(client,pid)['id']
    assert send(other,'PATCH',f'/api/admin/orders/{oid}/costs',{'delivery_cost':0}).status_code==404
    assert send(other,'POST',f'/api/admin/stock/{pid}/adjust',{'delta':1,'reason':'Compra'}).status_code==404
    # A newly registered account cannot promote itself through request fields.
    visitor=app.test_client()
    response=send(visitor,'POST','/api/auth/register',{'name':'Visitante','email':'visit@example.com','password':'senha-segura-123',
        'store_name':'Visitante','slug':'visitante','platform_admin':True})
    assert response.status_code==201 and response.json['user']['platform_admin'] is False


def test_profit_snapshots_costs_and_excludes_inventory_purchase(app,shop):
    client,pid=shop
    product=client.get('/api/admin/products').json['products'][0]
    product.update(unit_cost=1500,extras=[{'id':'bacon','name':'Bacon','price':500,'unit_cost':200}])
    assert send(client,'PUT',f'/api/admin/products/{pid}',product).status_code==200
    assert send(client,'PUT','/api/admin/finance/settings',{'payment_fees':{'pix':250},'default_delivery_cost':650}).status_code==200
    conn=connect(app.config)
    conn.execute('UPDATE stores SET commission_bps=500');conn.close()
    order=make_order(client,pid)
    assert order['items'][0]['unit_cost']==1700 and order['payment_fee']==98 and order['platform_fee']==170
    product['unit_cost']=5000
    assert send(client,'PUT',f'/api/admin/products/{pid}',product).status_code==200
    advance(client,order['id'],'preparing','ready','delivering','completed')
    assert send(client,'POST','/api/admin/expenses',{'description':'Energia','amount':300}).status_code==201
    assert send(client,'POST','/api/admin/expenses',{'description':'Compra de estoque','amount':10000,'category':'inventory'}).status_code==201
    finance=client.get('/api/admin/finance').json
    assert finance['estimated_profit']==982 and finance['cogs']==1700 and finance['margin']==25.2
    assert all(type(finance[k]) is int for k in ('revenue','cogs','expenses','estimated_profit'))
    assert client.get('/api/admin/customers').json['customers'][0]['spent']==3900
    assert client.get('/api/admin/insights').json['top_products'][0]['total']==3400
    assert app.test_cli_runner().invoke(args=['grant-platform-admin','--email','owner@example.com']).exit_code==0
    assert client.get('/api/platform/summary').json['gross_store_sales']==3900
    assert client.get('/api/admin/summary').json['expenses_total']==10300
    public=app.test_client()
    catalog=public.get('/api/store/minha-loja').json
    assert 'unit_cost' not in catalog['products'][0]
    assert 'unit_cost' not in catalog['products'][0]['extras'][0]
    assert 'commission_bps' not in catalog['store'] and 'payment_fees' not in catalog['store']
    tracked=public.get('/api/track/'+order['tracking_token']).json['order']
    assert 'unit_cost' not in tracked['items'][0] and 'platform_fee' not in tracked
    assert 'unit_cost' not in tracked['items'][0]['extras'][0]


def test_unknown_costs_stay_unknown_and_can_be_completed(shop):
    client,pid=shop
    order=make_order(client,pid)
    advance(client,order['id'],'preparing','ready','delivering','completed')
    f=client.get('/api/admin/finance').json
    assert f['estimated_profit'] is None and f['missing_cost_orders']==1
    response=send(client,'PATCH',f"/api/admin/orders/{order['id']}/costs",{'delivery_cost':0,'payment_fee':0,
        'items':[{'id':order['items'][0]['id'],'unit_cost':0}]})
    assert response.status_code==200,response.json
    assert client.get('/api/admin/finance').json['estimated_profit']==3900
    advance(client,order['id'])


def test_partner_auth_scopes_claims_events_and_revocation(app,shop):
    client,pid=shop
    key=key_for(client)
    partner=app.test_client()
    headers={'Authorization':'Bearer '+key['token']}
    assert partner.get('/api/v1/store').status_code==401
    assert partner.get('/api/v1/store',headers=headers).status_code==200
    order=make_order(client,pid)
    assert partner.get('/api/v1/deliveries',headers=headers).json['deliveries']==[]
    body={'provider':'motoja','external_id':'job-123','delivery_cost':650}
    path=f"/api/v1/deliveries/{order['id']}"
    assert partner.post(path+'/claim',json=body,headers=headers).status_code==409
    advance(client,order['id'],'preparing','ready')
    deliveries=partner.get('/api/v1/deliveries',headers=headers).json['deliveries']
    assert len(deliveries)==1 and 'platform_fee' not in deliveries[0] and 'tracking_token' not in deliveries[0]
    assert partner.post(path+'/claim',json=body,headers=headers).status_code==201
    assert partner.post(path+'/claim',json=body,headers=headers).json['duplicate'] is True
    assert partner.post(path+'/claim',json={**body,'external_id':'another'},headers=headers).status_code==409
    event={'event_id':'motoja-start-123','status':'delivering'}
    assert partner.post(path+'/events',json={'event_id':'motoja-end-123','status':'completed'},headers=headers).status_code==409
    assert partner.post(path+'/events',json=event,headers=headers).status_code==200
    assert partner.post(path+'/events',json=event,headers=headers).json['duplicate'] is True
    assert partner.post(path+'/events',json={**event,'status':'completed'},headers=headers).status_code==409
    assert partner.post(path+'/events',json={'event_id':'motoja-end-123','status':'completed'},headers=headers).status_code==200
    current=client.get('/api/admin/orders?status=completed').json['orders'][0]
    assert current['paid']==0 and current['delivery_cost']==650
    assert len(current['events'])==5
    # API keys are never accepted on cookie-based owner endpoints.
    assert partner.get('/api/admin/finance',headers=headers).status_code==401
    readonly=key_for(client,['orders:read'])
    assert partner.post(path+'/claim',json=body,headers={'Authorization':'Bearer '+readonly['token']}).status_code==403
    other=app.test_client();assert register(other,'other','other@example.com').status_code==201
    otherkey=key_for(other)
    assert partner.post(path+'/claim',json=body,headers={'Authorization':'Bearer '+otherkey['token']}).status_code==404
    listed=client.get('/api/admin/integrations').json
    assert key['token'] not in json.dumps(listed) and 'token_hash' not in json.dumps(listed)
    assert send(client,'DELETE','/api/admin/integrations/keys/'+str(key['id']),{}).status_code==200
    assert partner.get('/api/v1/store',headers=headers).status_code==401


def test_platform_ledger_idempotency_contract_and_suspension(app,shop):
    client,pid=shop
    app.test_cli_runner().invoke(args=['grant-platform-admin','--email','owner@example.com'])
    sid=client.get('/api/admin/store').json['store']['id']
    value={'store_id':sid,'kind':'receipt','description':'Mensalidade paga','amount':9900}
    key=uuid.uuid4().hex
    assert send(client,'POST','/api/platform/ledger',value,key).status_code==201
    assert send(client,'POST','/api/platform/ledger',value,key).json['duplicate'] is True
    assert send(client,'POST','/api/platform/ledger',{**value,'amount':8800},key).status_code==409
    assert send(client,'POST','/api/platform/ledger',{'store_id':sid,'kind':'expense','description':'Servidor','amount':700},uuid.uuid4().hex).status_code==201
    report=client.get('/api/platform/summary').json
    assert report['received']==9900 and report['cash_result']==9200 and report['stores'][0]['received']==9900
    receipt=next(e for e in report['ledger'] if e['kind']=='receipt')
    assert send(client,'DELETE',f"/api/platform/ledger/{receipt['id']}",{}).status_code==200
    assert send(client,'DELETE',f"/api/platform/ledger/{receipt['id']}",{}).status_code==200
    corrected=client.get('/api/platform/summary').json
    assert corrected['received']==0 and corrected['cash_result']==-700
    assert next(e for e in corrected['ledger'] if e['id']==receipt['id'])['voided_at']
    assert send(client,'PUT',f'/api/platform/stores/{sid}',{'commission_bps':500,'monthly_fee':9900,'enabled':False}).status_code==200
    partner=app.test_client();key=key_for(client)
    assert partner.get('/api/v1/store',headers={'Authorization':'Bearer '+key['token']}).status_code==403
    assert send(client,'POST','/api/store/minha-loja/orders',payload(pid),uuid.uuid4().hex).status_code==409
    settings=client.get('/api/admin/store').json['store'];settings['open']=True
    assert send(client,'PUT','/api/admin/store',settings).status_code==403


def test_stock_cancellation_customer_history_and_manual_order(shop):
    client,pid=shop
    assert send(client,'POST',f'/api/admin/stock/{pid}/adjust',{'delta':5,'reason':'Compra'}).status_code==200
    order=make_order(client,pid)
    advance(client,order['id'],'cancelled')
    stock=client.get('/api/admin/stock').json
    assert stock['products'][0]['stock']==10
    assert any(m['reason'].startswith('Cancelamento') for m in stock['movements'])
    settings=client.get('/api/admin/store').json['store'];settings['open']=False
    assert send(client,'PUT','/api/admin/store',settings).status_code==200
    result=send(client,'POST','/api/admin/orders',payload(pid,mode='pickup'),uuid.uuid4().hex)
    assert result.status_code==201,result.json
    order=client.get('/api/admin/orders').json['orders'][0]
    assert order['source']=='counter' and order['delivery_cost']==0
    customers=client.get('/api/admin/customers').json['customers']
    assert len(customers)==1 and customers[0]['orders']==1
    assert len(client.get('/api/admin/customers/11999999999/orders').json['orders'])==2


def test_legacy_sqlite_upgrade_preserves_data(tmp_path):
    from pathlib import Path
    from app import create_app
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript(Path('schema.sql').read_text(encoding='utf-8'))
        conn.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES('Original','old@example.com','hash','2026-01-01')")
    config={'TESTING':True,'DATABASE_PATH':str(path),'DATABASE_URL':'','UPLOAD_DIR':str(tmp_path/'uploads')}
    application=create_app(config)
    initialize(application.config)
    conn=connect(application.config)
    assert conn.execute('SELECT name,platform_admin FROM users').fetchone()['name']=='Original'
    assert conn.execute('SELECT platform_admin FROM users').fetchone()[0]==0
    assert 'unit_cost' in [r[1] for r in conn.execute('PRAGMA table_info(products)')]
    conn.close()


def test_editing_cost_does_not_restore_stale_stock(shop):
    client,pid=shop
    old=client.get('/api/admin/products').json['products'][0]
    make_order(client,pid)
    value={**old,'expected_stock':old['stock'],'unit_cost':1000}
    assert send(client,'PUT',f'/api/admin/products/{pid}',value).status_code==200
    product=client.get('/api/admin/products').json['products'][0]
    assert product['stock']==4 and product['unit_cost']==1000
    value['stock']=9
    assert send(client,'PUT',f'/api/admin/products/{pid}',value).status_code==409
    assert send(client,'POST',f'/api/admin/stock/{pid}/adjust',{'delta':-5,'reason':'Perda'}).status_code==400


def test_partner_limit_is_bound_to_key_not_ip(app,shop):
    import hashlib
    import time
    client,pid=shop
    key=key_for(client)
    app.config['RATE_LIMIT_ENABLED']=True
    digest=hashlib.sha256(f"partner-key-{key['id']}:key".encode()).hexdigest()
    conn=connect(app.config)
    conn.execute('INSERT INTO rate_limits VALUES(?,?,?)',(digest,120,int(time.time())+60))
    conn.close()
    partner=app.test_client()
    for ip in ('127.0.0.1','192.0.2.5'):
        assert partner.get('/api/v1/store',headers={'Authorization':'Bearer '+key['token']},environ_overrides={'REMOTE_ADDR':ip}).status_code==429
