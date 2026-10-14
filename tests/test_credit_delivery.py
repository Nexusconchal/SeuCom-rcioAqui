import io
import uuid
from concurrent.futures import ThreadPoolExecutor

from openpyxl import load_workbook

from tests.test_api import app,shop,send,payload,register
from tests.test_growth import sql
from tests.test_operations import pay


def credit_order(c,pid):
    return send(c,'POST','/api/admin/orders',payload(pid,mode='pickup',payment='credit'),uuid.uuid4().hex)


def test_credit_limit_concurrent_purchase_payment_and_cancel_reconcile(shop):
    c,pid=shop
    assert send(c,'POST','/api/admin/credit',{'name':'Cliente do Fiado','phone':'11999999999','credit_limit':5000}).status_code==200
    assert send(c,'POST','/api/store/minha-loja/orders',payload(pid,payment='credit'),uuid.uuid4().hex).status_code==400
    def attempt(_):
        client=c.application.test_client();send(client,'POST','/api/auth/login',{'email':'owner@example.com','password':'uma-senha-segura'})
        return credit_order(client,pid).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,range(2)))==[201,409]
    o=c.get('/api/admin/orders').json['orders'][0]
    assert c.get('/api/admin/credit').json['accounts'][0]['debt']==3400
    assert send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'paid':True}).status_code==409
    send(c,'POST','/api/admin/cash/open',{'opening':0})
    assert pay(c,o,1000,'pix').status_code==201
    bill=c.get('/api/admin/purchasing').json['obligations'][0]
    assert bill['order_id']==o['id'] and bill['settled']==1000
    assert send(c,'POST',f"/api/admin/obligations/{bill['id']}/settle",{'amount':2400},uuid.uuid4().hex).status_code==409
    assert c.get('/api/admin/credit').json['accounts'][0]['available']==2600
    assert send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'status':'cancelled'}).status_code==200
    assert c.get('/api/admin/credit').json['accounts'][0]['debt']==0
    assert c.get('/api/admin/purchasing').json['obligations'][0]['voided_at']
    assert pay(c,o,1000,'pix',kind='refund',original_id=c.get('/api/admin/cash').json['receipts'][0]['id'],reason='Pedido cancelado').status_code==201
    assert c.get('/api/admin/report?format=pdf').status_code==200


def test_postal_fees_minimum_free_delivery_blocked_area_and_version(shop):
    c,pid=shop
    zone={'name':'Centro','min_cep':13835000,'max_cep':13835999,'fee':800,'minimum':3000,'free_above':6000}
    version=c.get('/api/admin/shipping').json['version']
    assert send(c,'PUT','/api/admin/shipping',{'zones':[zone],'expected_version':version}).status_code==200
    assert send(c,'PUT','/api/admin/shipping',{'zones':[],'expected_version':version}).status_code==409
    assert send(c,'POST','/api/store/minha-loja/quote',payload(pid)).status_code==400
    q=send(c,'POST','/api/store/minha-loja/quote',payload(pid,cep='13835-001'))
    assert q.status_code==200 and q.json['delivery_fee']==800 and q.json['zone']=='Centro'
    assert send(c,'POST','/api/store/minha-loja/quote',payload(pid,cep='13835001',quantity=2)).json['delivery_fee']==0
    assert send(c,'POST','/api/store/minha-loja/quote',payload(pid,cep='13836000')).status_code==409
    blocked={**zone,'name':'Área bloqueada','min_cep':13835010,'max_cep':13835020,'enabled':False,'priority':1}
    send(c,'PUT','/api/admin/shipping',{'zones':[zone,blocked]})
    assert send(c,'POST','/api/store/minha-loja/quote',payload(pid,cep='13835015')).status_code==409
    created=send(c,'POST','/api/store/minha-loja/orders',payload(pid,cep='13835001',latitude=-22.32,longitude=-47.17),uuid.uuid4().hex)
    assert created.status_code==201 and created.json['total']==4200
    row=sql(c,'SELECT postal_code,latitude,longitude FROM orders')[0]
    assert row['postal_code']=='13835001' and row['latitude']==-22.32


def test_driver_revocable_link_location_scope_and_atomic_batch_dispatch(shop):
    c,pid=shop
    did=send(c,'POST','/api/admin/drivers',{'name':'Entregador Teste','phone':'11988888888','active':True}).json['id']
    url=send(c,'POST',f'/api/admin/drivers/{did}/location-link',{}).json['url'];token=url.split(':')[-1]
    bearer={'Authorization':'Bearer '+token}
    driver=c.application.test_client()
    assert driver.get('/api/driver/route',headers=bearer).status_code==200
    assert driver.get('/api/admin/delivery-map').status_code==401
    csrf=driver.get('/api/session').json['csrf']
    assert driver.post('/api/driver/location',json={'latitude':-22.32,'longitude':-47.17,'accuracy':15},headers={**bearer,'X-CSRF-Token':csrf}).status_code==200
    assert 'gps_hash' not in c.get('/api/admin/drivers').json['drivers'][0]
    assert c.get('/api/admin/delivery-map').json['drivers'][0]['gps_lat']==-22.32
    orders=[]
    for _ in range(2):
        send(c,'POST','/api/store/minha-loja/orders',payload(pid),uuid.uuid4().hex)
        o=c.get('/api/admin/orders').json['orders'][0];orders.append(o)
        send(c,'PATCH',f"/api/admin/orders/{o['id']}",{'status':'preparing'})
    send(c,'PATCH',f"/api/admin/orders/{orders[0]['id']}",{'status':'ready'})
    dispatch={'order_ids':[o['id'] for o in orders],'driver_id':did}
    assert send(c,'POST','/api/admin/delivery-map/dispatch',dispatch).status_code==409
    assert all(o['status']!='delivering' for o in c.get('/api/admin/orders').json['orders'])
    send(c,'PATCH',f"/api/admin/orders/{orders[1]['id']}",{'status':'ready'})
    assert send(c,'POST','/api/admin/delivery-map/dispatch',dispatch).json['dispatched']==2
    assert len(driver.get('/api/driver/route',headers=bearer).json['orders'])==2
    assert send(c,'POST',f'/api/admin/drivers/{did}/location-link',{'revoke':True}).status_code==200
    assert driver.get('/api/driver/route',headers=bearer).status_code==401
    assert c.get('/api/admin/delivery-map').json['drivers'][0]['gps_lat'] is None


def test_report_literal_customer_strings_and_partial_payment_summary(shop):
    c,pid=shop
    send(c,'POST','/api/store/minha-loja/orders',payload(pid,customer='=HYPERLINK("https://example.test","Cliente")'),uuid.uuid4().hex)
    o=c.get('/api/admin/orders').json['orders'][0];send(c,'POST','/api/admin/cash/open',{'opening':0});pay(c,o,1000,'pix')
    s=c.get('/api/admin/summary?days=7').json
    assert s['received']==1000 and s['pending_payment']==2900
    assert next(p for p in s['payments'] if p['method']=='pix')['total']==1000
    report=c.get('/api/admin/report?format=xlsx')
    book=load_workbook(io.BytesIO(report.data));cell=book['Pedidos']['C2']
    assert cell.value.startswith('=HYPERLINK') and cell.data_type=='s'
