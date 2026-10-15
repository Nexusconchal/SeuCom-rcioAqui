from tests.test_api import app, shop, send, payload, register
from tests.test_operations import order, pay, key

def test_receipt_report_partial_payments_refunds_tenants_and_roles(shop):
    c,pid=shop
    assert send(c,'POST','/api/admin/cash/open',{'opening':0}).status_code==201
    o=order(c,pid,payment='card')
    partial=pay(c,o,1000,'pix')
    assert partial.status_code==201
    refund=send(c,'POST',f"/api/admin/orders/{o['id']}/receipts",{'amount':200,'method':'pix','kind':'refund','original_id':partial.json['id'],'reason':'Devolução parcial'},key())
    assert refund.status_code==201
    r=c.get('/api/admin/report?format=receipt&days=7')
    assert r.status_code==200 and r.is_json
    summary={x['label']:x['value'] for x in r.json['summary']}
    assert summary['Recebido líquido']=='R$ 8,00'
    assert summary['A receber']=='R$ 26,00'
    actual=next(s for s in r.json['sections'] if s['title'].startswith('Recebido líquido por forma real'))
    assert any(row==[{'label':'Forma','value':'Pix'},{'label':'Valor','value':'R$ 8,00'}] for row in actual['rows'])
    assert 'Cliente Teste' not in r.get_data(as_text=True)
    assert c.application.test_client().get('/api/admin/report?format=receipt').status_code==401
    other=c.application.test_client();register(other,slug='outra',email='outra@example.com')
    assert {x['label']:x['value'] for x in other.get('/api/admin/report?format=receipt').json['summary']}['Recebido líquido']=='R$ 0,00'
    assert send(c,'POST','/api/admin/team',{'name':'Cozinha Teste','email':'cozinha@example.com','password':'senha-segura-nova','role':'kitchen'}).status_code==201
    kitchen=c.application.test_client();send(kitchen,'POST','/api/auth/login',{'email':'cozinha@example.com','password':'senha-segura-nova'})
    assert kitchen.get('/api/admin/report?format=receipt').status_code==403
