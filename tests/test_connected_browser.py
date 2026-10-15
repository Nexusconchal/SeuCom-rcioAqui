import os
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server

from tests.test_api import app,send
from tests.test_growth import sql
from tests.test_inbox import InboxProvider,event


@pytest.fixture
def connected_live(app):
    assert app.test_cli_runner().invoke(args=['seed-demo','--email','demo@example.com','--password','senha-de-teste-segura']).exit_code==0
    client=app.test_client();send(client,'POST','/api/auth/login',{'email':'demo@example.com','password':'senha-de-teste-segura'})
    fake=InboxProvider();app.extensions['evolution']=fake
    sql(client,"UPDATE stores SET wa_instance='test-instance',wa_enabled=1")
    assert send(client,'PUT','/api/admin/cashback',{'enabled':True,'bps':500}).status_code==200
    server=make_server('127.0.0.1',0,app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',client,fake
    finally:server.shutdown();thread.join()


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_cashback_otp_checkout_driver_location_and_inbox_ui(connected_live):
    live,c,fake=connected_live;artifacts=Path('artifacts');artifacts.mkdir(exist_ok=True)
    products=c.get('/api/admin/products').json['products'];pid=next(p['id'] for p in products if p['name']=='Burger da casa')
    first=send(c,'POST','/api/store/bistro-da-vila/orders',{'customer':'Cliente Cashback','phone':'11999999999','payment':'pix','mode':'pickup','items':[{'product_id':pid,'quantity':1,'option_ids':[]}]},uuid.uuid4().hex)
    assert first.status_code==201
    oid=c.get('/api/admin/orders').json['orders'][0]['id']
    for status in ('preparing','ready','completed'):assert send(c,'PATCH',f'/api/admin/orders/{oid}',{'status':status}).status_code==200
    assert send(c,'PATCH',f'/api/admin/orders/{oid}',{'paid':True}).status_code==200
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None);errors=[]
        shopper=browser.new_page(viewport={'width':390,'height':844});shopper.on('pageerror',lambda e:errors.append(str(e)))
        shopper.goto(live+'/loja/bistro-da-vila');shopper.get_by_role('button',name='Ver Burger da casa',exact=True).click()
        shopper.get_by_role('button',name='Adicionar •').click();shopper.get_by_role('button',name='Ver minha sacola').click();shopper.get_by_role('button',name='Continuar pedido').click()
        shopper.get_by_label('Seu nome',exact=True).fill('Cliente Cashback');shopper.get_by_label('WhatsApp com DDD').fill('11999999999');shopper.get_by_label('Endereço completo').fill('Rua Teste, 100, Centro')
        shopper.get_by_role('button',name='Consultar e usar cashback',exact=True).click()
        expect(shopper.get_by_label('Código de 6 dígitos')).to_be_visible()
        code=next(re.search(r': (\d{6})\.',text).group(1) for _,_,text in reversed(fake.calls) if re.search(r': (\d{6})\.',text))
        shopper.get_by_label('Código de 6 dígitos').fill(code);shopper.get_by_role('button',name='Confirmar código',exact=True).click()
        shopper.get_by_label('Usar até R$ 1,45 de cashback').check()
        expect(shopper.locator('#checkout-totals')).to_contain_text('32,55')
        shopper.screenshot(path=str(artifacts/'cashback-checkout-mobile.png'),full_page=True)
        shopper.get_by_role('button',name='Confirmar pedido',exact=False).click();shopper.wait_for_url('**/pedido/**')
        order=c.get('/api/admin/orders').json['orders'][0];assert order['cashback_discount']==145
        did=send(c,'POST','/api/admin/drivers',{'name':'Entregador GPS','phone':'11988888888','active':True}).json['id']
        link=send(c,'POST',f'/api/admin/drivers/{did}/location-link',{}).json['url']
        ctx=browser.new_context(viewport={'width':390,'height':844},geolocation={'latitude':-22.32,'longitude':-47.17},permissions=['geolocation'])
        driver=ctx.new_page();driver.on('pageerror',lambda e:errors.append(str(e)));driver.goto(live+'/entregador/#'+urlparse(link).fragment)
        driver.get_by_role('button',name='Iniciar compartilhamento',exact=True).click();expect(driver.locator('#driver-position-status')).to_contain_text('Posição compartilhada')
        assert next(d for d in c.get('/api/admin/delivery-map').json['drivers'] if d['id']==did)['gps_lat']==-22.32
        driver.screenshot(path=str(artifacts/'entregador-mobile.png'),full_page=True)
        driver.get_by_role('button',name='Parar',exact=True).click();expect(driver.locator('#driver-position-status')).to_contain_text('desligado')
        assert send(c,'POST','/api/admin/inbox/connect',{}).status_code==200
        assert c.post('/webhooks/inbox/1',json=event('Gostaria de pedir um lanche'),headers={'X-Webhook-Token':fake.token}).status_code==200
        admin=browser.new_page(viewport={'width':1440,'height':1000});admin.on('pageerror',lambda e:errors.append(str(e)));admin.goto(live+'/entrar')
        admin.get_by_label('E-mail',exact=True).fill('demo@example.com');admin.get_by_label('Senha',exact=True).fill('senha-de-teste-segura');admin.get_by_role('button',name='Entrar no painel').click();admin.wait_for_url('**/painel')
        admin.get_by_role('button',name='Atendimento WhatsApp',exact=True).click();admin.locator('[data-thread]').click()
        expect(admin.locator('.inbox-history')).to_contain_text('Gostaria de pedir um lanche')
        admin.get_by_role('button',name='Assumir conversa',exact=True).click();admin.get_by_label('Resposta',exact=True).fill('Olá! Vou ajudar com seu pedido.')
        admin.get_by_role('button',name='Enviar resposta',exact=True).click();expect(admin.locator('.inbox-history')).to_contain_text('Na fila')
        admin.evaluate('window.scrollTo(0,0)')
        admin.screenshot(path=str(artifacts/'atendimento-desktop.png'),full_page=True)
        admin.get_by_role('button',name='Mapa de entregas',exact=True).click();expect(admin.get_by_role('heading',name='Pedidos de entrega',exact=True)).to_be_visible()
        admin.screenshot(path=str(artifacts/'entregas-desktop.png'),full_page=True)
        assert errors==[];browser.close()
