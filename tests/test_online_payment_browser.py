"""Local provider fixture only: customer checkout -> ledger -> merchant -> refund."""
import os
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from tests.test_api import app, shop, send
from tests.test_online_payments import setup_online
from tests.test_growth import sql


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
@pytest.mark.parametrize('kind',['pix','card'])
def test_online_customer_checkout_and_owner_refund(shop,kind):
    client,pid=shop;provider=setup_online(client,kind,auto=True)
    server=make_server('127.0.0.1',0,client.application,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    live=f'http://127.0.0.1:{server.server_port}'
    Path('artifacts').mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            page=browser.new_page(viewport={'width':390,'height':844});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('https://www.mercadopago.com.br/**',lambda r:r.fulfill(status=200,body='<h1>Checkout do provedor simulado</h1>'))
            page.goto(live+'/loja/minha-loja')
            page.get_by_role('button',name='Ver Burger',exact=True).click()
            page.get_by_role('button',name='Adicionar •').click()
            page.get_by_role('button',name='Ver minha sacola').click()
            page.get_by_role('button',name='Continuar pedido').click()
            page.get_by_label('Seu nome',exact=True).fill('Cliente Pagamento')
            page.get_by_label('WhatsApp com DDD').fill('11999999999')
            page.get_by_label('Endereço completo').fill('Rua Teste, 123, Centro')
            page.get_by_label('E-mail para o pagamento online',exact=True).fill('pagador@example.test')
            page.get_by_role('button',name='Confirmar pedido').click()
            page.wait_for_url('**/pedido/**');tracking=page.url
            expect(page.get_by_role('heading',name='Aguardando pagamento',exact=True)).to_have_count(1)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if kind=='pix':expect(page.get_by_role('button',name='Copiar Pix',exact=True)).to_be_visible()
            else:
                page.get_by_role('button',name='Pagar no Mercado Pago',exact=True).click()
                expect(page.get_by_role('heading',name='Checkout do provedor simulado')).to_be_visible()
                page.goto(tracking+'?status=approved&payment_id=99999')
                expect(page.get_by_role('heading',name='Aguardando pagamento',exact=True)).to_have_count(1)
            page.screenshot(path=f'artifacts/pagamento-{kind}-mobile.png',full_page=True)
            order=sql(client,'SELECT * FROM orders ORDER BY id DESC LIMIT 1')[0]
            assert not order['paid'] and order['status']=='new'
            assert send(client,'PATCH',f"/api/admin/orders/{order['id']}",{'status':'preparing'}).status_code==409
            if kind=='pix':provider.payments[9000]['status']='approved'
            else:provider.approve_card()
            page.reload()
            expect(page.get_by_role('heading',name='Pagamento confirmado',exact=True)).to_be_visible(timeout=20000)
            paid=sql(client,'SELECT * FROM orders WHERE id=?',(order['id'],))[0]
            assert paid['paid'] and paid['status']=='preparing'
            assert paid['payer_email']=='pagador@example.test'
            assert 'payer_email' not in client.get('/api/track/'+tracking.rsplit('/',1)[1]).json['order']
            page.set_viewport_size({'width':1440,'height':1000})
            page.goto(live+'/entrar');page.get_by_label('E-mail',exact=True).fill('owner@example.com')
            page.get_by_label('Senha',exact=True).fill('uma-senha-segura')
            page.get_by_role('button',name='Entrar no painel').click()
            page.locator('[data-detail]').first.click()
            expect(page.get_by_role('button',name='Estornar pagamento',exact=True)).to_be_visible()
            expect(page.get_by_label('Pagamento confirmado',exact=True)).to_be_disabled()
            page.screenshot(path=f'artifacts/pagamento-{kind}-lojista.png',full_page=True)
            page.get_by_role('button',name='Estornar pagamento',exact=True).click()
            assert not provider.refunds
            page.get_by_role('button',name='Confirmar estorno integral',exact=True).click()
            expect(page.locator('#modal')).not_to_be_visible()
            assert len(provider.refunds)==1
            page.goto(tracking)
            expect(page.get_by_role('heading',name='Pagamento estornado',exact=True)).to_be_visible()
            assert not sql(client,'SELECT paid FROM orders WHERE id=?',(order['id'],))[0]['paid']
            page.goto(live+'/painel')
            page.get_by_role('button',name='PDV / Balcão',exact=True).click()
            page.locator('[data-pos-product]').first.click()
            page.get_by_role('button',name='Adicionar ao pedido',exact=True).click()
            page.get_by_role('button',name='Finalizar pedido',exact=False).click()
            page.get_by_label('E-mail para o pagamento online',exact=True).fill('balcao@example.test')
            expect(page.locator('#pos-payment-note')).to_contain_text('aguarda confirmação')
            page.get_by_role('button',name='Criar pedido',exact=True).click()
            expect(page.get_by_role('link',name='Abrir cobrança',exact=True)).to_be_visible()
            counter=sql(client,'SELECT * FROM orders ORDER BY id DESC LIMIT 1')[0]
            assert counter['source']=='counter' and counter['payer_email']=='balcao@example.test'
            assert not counter['paid'] and counter['status']=='new'
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown();thread.join()
