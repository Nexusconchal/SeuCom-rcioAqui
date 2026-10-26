"""Real Chromium checkout → OTP → server-side reward; provider is a test double."""
import os
import re
import threading

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from tests.test_api import app, shop, send
from tests.test_business import make_order, advance
from tests.test_wallet_campaigns import provider


@pytest.mark.skipif(os.getenv('SKIP_BROWSER') == '1', reason='Chromium não instalado')
def test_loyalty_verification_checkout_and_mismatched_phone(shop):
    c,pid=shop
    s=c.get('/api/admin/store').json['store']
    assert send(c,'PUT','/api/admin/store',{**s,'loyalty_enabled':True,'loyalty_goal':2,'loyalty_reward':700}).status_code==200
    for _ in range(2):
        order=make_order(c,pid)
        advance(c,order['id'],'preparing','ready','delivering','completed')
        assert send(c,'PATCH',f"/api/admin/orders/{order['id']}",{'paid':True}).status_code==200
    fake=provider(c)
    server=make_server('127.0.0.1',0,c.application,threaded=True)
    base=f'http://127.0.0.1:{server.server_port}'
    c.application.config['PUBLIC_URL']=base
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            page=browser.new_page(viewport={'width':390,'height':844})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/loja/minha-loja')
            page.get_by_role('button',name='Ver Burger',exact=True).click()
            page.get_by_role('button',name='Adicionar •').click()
            page.get_by_role('button',name='Ver minha sacola').click()
            page.get_by_role('button',name='Continuar pedido').click()
            page.get_by_label('Seu nome',exact=True).fill('Cliente de teste')
            page.get_by_label('WhatsApp com DDD').fill('11999999999')
            page.get_by_label('Endereço completo').fill('Rua de teste, 123')
            page.get_by_label('Endereço completo').press('Tab')
            expect(page.locator('#checkout-totals')).not_to_contain_text('Prêmio de fidelidade')
            page.get_by_role('button',name='Confirmar WhatsApp e consultar recompensas').click()
            expect(page.get_by_label('Código de 6 dígitos')).to_be_visible()
            code=re.search(r': (\d{6})\.',fake.calls[-1][2]).group(1)
            page.get_by_label('Código de 6 dígitos').fill(code)
            page.get_by_role('button',name='Confirmar código',exact=True).click()
            expect(page.locator('#checkout-totals')).to_contain_text('Prêmio de fidelidade')
            page.get_by_label('WhatsApp com DDD').fill('11988888888')
            expect(page.locator('#checkout-totals')).not_to_contain_text('Prêmio de fidelidade')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
