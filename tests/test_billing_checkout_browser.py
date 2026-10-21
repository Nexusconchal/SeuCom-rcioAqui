import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from tests.test_api import app
from tests.test_features import FakeSubscriptions


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_merchant_plan_pix_confirmation_and_private_history(app):
    assert app.test_cli_runner().invoke(args=['seed-demo','--email','demo@example.com','--password','senha-de-teste-segura']).exit_code==0
    fake=FakeSubscriptions();app.extensions['mercadopago']=fake;app.config['MP_PLATFORM_ACCESS_TOKEN']='test-platform'
    server=make_server('127.0.0.1',0,app,threaded=True)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/entrar')
            page.get_by_label('E-mail',exact=True).fill('demo@example.com')
            page.get_by_label('Senha',exact=True).fill('senha-de-teste-segura')
            page.get_by_role('button',name='Entrar no painel').click()
            page.get_by_role('button',name='Assinar agora',exact=True).click()
            page.get_by_role('button',name='Pix (paga o mês)',exact=True).click()
            page.get_by_role('button',name='Gerar Pix de R$ 59,99',exact=True).click()
            expect(page.locator('#pix-area')).to_contain_text('00020126')
            expect(page.locator('#pix-expiration')).to_contain_text('Válido por')
            Path('artifacts').mkdir(exist_ok=True)
            page.screenshot(path='artifacts/mensalidade-pix.png',full_page=True)
            fake.payments[9000].update(status='approved',date_approved=datetime.now(timezone.utc).isoformat())
            page.get_by_role('button',name='Já paguei, conferir',exact=True).click()
            expect(page.locator('#modal')).not_to_be_visible()
            response=page.request.get(f'http://127.0.0.1:{server.server_port}/api/admin/billing')
            assert response.status==200 and response.json()['state']=='paid'
            assert len(response.json()['payments'])==1 and response.json()['payments'][0]['amount']==5999
            assert errors==[] and len(fake.created)==1
            browser.close()
    finally:server.shutdown();worker.join()
