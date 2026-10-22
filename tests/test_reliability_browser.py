"""UI → API → database verification; SMTP, payment provider and print are simulated."""
import os
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from tests.test_api import app
from scripts.load_probe import probe


@pytest.fixture
def operational_live(app):
    assert app.test_cli_runner().invoke(args=['seed-demo','--email','demo@example.com','--password','senha-de-teste-segura']).exit_code==0
    assert app.test_cli_runner().invoke(args=['grant-platform-admin','--email','demo@example.com']).exit_code==0
    received=[]
    app.extensions['recovery_mailer']=lambda config,email,url:received.append((email,url))
    server=make_server('127.0.0.1',0,app,threaded=True)
    base=f'http://127.0.0.1:{server.server_port}'
    app.config['PUBLIC_URL']=base
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield base,app,received
    finally:
        server.shutdown()
        thread.join(timeout=5)


def login(page,base,password='senha-de-teste-segura'):
    page.goto(base+'/entrar')
    page.get_by_label('E-mail',exact=True).fill('demo@example.com')
    page.get_by_label('Senha',exact=True).fill(password)
    page.get_by_role('button',name='Entrar no painel').click()
    expect(page.get_by_role('button',name='Visão geral',exact=True)).to_be_visible()


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_recovery_end_to_end_and_old_session_rejected(operational_live):
    base,application,received=operational_live
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        old=browser.new_context().new_page()
        login(old,base)
        page=browser.new_context(viewport={'width':390,'height':844}).new_page()
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base+'/entrar')
        page.get_by_role('link',name='Esqueci minha senha').click()
        page.get_by_label('E-mail da sua conta').fill('demo@example.com')
        page.get_by_role('button',name='Enviar link de recuperação').click()
        expect(page.locator('#recovery-content')).to_contain_text('Se houver uma conta')
        assert len(received)==1
        page.goto(received[0][1])
        expect(page.get_by_role('heading',name='Escolha uma nova senha')).to_be_visible()
        assert not page.evaluate('location.hash')
        page.get_by_label('Nova senha',exact=True).fill('nova-senha-no-browser')
        page.get_by_label('Confirme a nova senha').fill('nova-senha-no-browser')
        page.get_by_role('button',name='Salvar nova senha').click()
        expect(page.locator('#recovery-content')).to_contain_text('Senha alterada')
        assert old.request.get(base+'/api/admin/store').status==401
        login(page,base,'nova-senha-no-browser')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path='artifacts/configuracao-guiada-mobile.png',full_page=True)
        assert not errors
        browser.close()


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_print_recovery_simulation_diagnostics_and_local_load(operational_live):
    base,application,_=operational_live
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        page=context.new_page()
        page.add_init_script("window.printCalls=0;window.print=()=>{window.printCalls++};")
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        login(page,base)
        expect(page.get_by_text('Prepare sua loja para vender',exact=True)).to_be_visible()
        # A quote is a real server calculation and creates no order/charge.
        page.get_by_role('button',name='PDV / Balcão',exact=True).click()
        page.locator('[data-pos-product]').first.click()
        page.get_by_role('button',name='Adicionar ao pedido',exact=True).click()
        page.get_by_role('button',name='Finalizar pedido',exact=False).click()
        page.get_by_role('button',name='Simular valores sem criar pedido').click()
        expect(page.locator('#pos-simulation')).to_contain_text('Nenhum pedido ou cobrança foi criado')
        page.get_by_role('button',name='Fechar',exact=True).click()
        # Set up an unpaid cash order with auto printing enabled. On reopening,
        # it must be pending, never silently reprinted.
        oid=page.evaluate("""async()=>{
          const {api}=await import('/static/ui.js');
          const list=await api('/api/admin/pos/catalog');
          const product=list.products.find(x=>x.name==='Burger da casa');
          const body={customer:'Cliente Impressão',phone:'11999999999',mode:'pickup',payment:'cash',items:[{product_id:product.id,quantity:1,option_ids:[],notes:''}]};
          const quote=await api('/api/admin/pos/quote',{method:'POST',body:JSON.stringify(body)});
          const order=await api('/api/admin/orders',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({...body,expected_total:quote.total})});
          const {store}=await api('/api/admin/store');localStorage.setItem('sca.autoprint.'+store.id,'1');return order.id;
        }""")
        page.reload()
        page.get_by_role('button',name='Imprimir notinha',exact=True).click()
        expect(page.locator('#print-history')).to_contain_text('Pendente')
        assert page.evaluate('window.printCalls')==0
        page.locator('[data-journal-print]').first.click()
        page.wait_for_function('()=>window.printCalls===1')
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        expect(page.locator('#print-history')).to_contain_text('Confira se saiu no papel')
        saved=page.evaluate("Object.entries(localStorage).find(([k])=>k.startsWith('sca.print-journal.'))[1]")
        assert 'Cliente Impressão' not in saved and '11999999999' not in saved
        page.reload()
        page.get_by_role('button',name='Imprimir notinha',exact=True).click()
        expect(page.locator('#print-history')).to_contain_text('Confira se saiu no papel')
        assert page.evaluate('window.printCalls')==0
        page.get_by_role('button',name='Conferi no papel',exact=True).first.click()
        expect(page.locator('#print-history')).to_contain_text('Conferido pela equipe')
        page.get_by_role('button',name='Recebíveis online',exact=True).click()
        expect(page.get_by_role('heading',name='Seu dinheiro, com clareza.')).to_be_visible()
        page.get_by_role('button',name='Diagnóstico da loja',exact=True).click()
        expect(page.get_by_role('heading',name='Filas verificadas',exact=True)).to_be_visible()
        for width in (390,768,1440):
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        context.set_offline(True)
        expect(page.locator('#connection-status')).to_contain_text('Sem internet')
        context.set_offline(False)
        page.get_by_role('button',name='Atualizar diagnóstico').click()
        expect(page.locator('#connection-status')).to_have_class('hidden')
        page.goto(base+'/admin')
        page.get_by_role('button',name='Diagnóstico',exact=True).click()
        expect(page.get_by_role('heading',name='Serviços da plataforma')).to_be_visible()
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path='artifacts/diagnostico-operacao.png',full_page=True)
        assert not errors
        browser.close()
    result=probe(base,['/health','/','/api/store/bistro-da-vila'],count=80,workers=8)
    assert result['errors']==0
    Path('artifacts/carga-local.json').write_text(__import__('json').dumps(result,indent=2),encoding='utf-8')
