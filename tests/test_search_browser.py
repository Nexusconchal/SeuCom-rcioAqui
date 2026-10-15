"""Search, quick navigation and receipt reports through the actual browser/API."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from tests.test_browser import live

@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_search_shortcut_and_receipt_report(live):
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(live+'/loja/bistro-da-vila')
        page.locator('#menu-search').fill('brioche pao')
        expect(page.locator('.product-card')).to_have_count(1)
        page.locator('#menu-search').fill('inexistente')
        expect(page.get_by_text('Nada por aqui ainda')).to_be_visible()
        page.goto(live+'/entrar')
        page.get_by_label('E-mail',exact=True).fill('demo@example.com')
        page.get_by_label('Senha',exact=True).fill('senha-de-teste-segura')
        page.get_by_role('button',name='Entrar no painel').click()
        page.get_by_role('button',name='PDV / Balcão',exact=True).click()
        page.locator('#pos-search').fill('3* brioche pao')
        expect(page.locator('[data-pos-product]')).to_have_count(1)
        page.locator('#pos-search').press('Enter')
        expect(page.get_by_label('Quantidade',exact=True)).to_have_value('3')
        page.get_by_role('button',name='Adicionar ao pedido',exact=True).click()
        expect(page.locator('#pos-cart')).to_contain_text('3 × Burger da casa')
        page.locator('#pos-search').fill('51* burger')
        expect(page.locator('#pos-search-help')).to_contain_text('1 a 50')
        expect(page.locator('[data-pos-product]')).to_have_count(0)
        page.keyboard.press('Control+k')
        page.locator('#quick-query').fill('relatorio')
        expect(page.locator('[data-quick]')).to_have_count(1)
        page.locator('#quick-query').press('Enter')
        expect(page.locator('#report-form')).to_be_visible()
        token=page.request.get(live+'/api/session').json()['csrf']
        ready=next(o for o in page.request.get(live+'/api/admin/orders').json()['orders'] if o['status']=='ready')
        for status in ('delivering','completed'):
            result=page.request.patch(live+'/api/admin/orders/'+str(ready['id']),headers={'X-CSRF-Token':token},data={'status':status})
            assert result.status==200
        page.locator('#report-form [name=format]').select_option('receipt')
        expect(page.locator('#report-paper-label')).to_be_visible()
        page.locator('#report-form [name=paper]').select_option('58')
        page.get_by_role('button',name='Gerar relatório',exact=True).last.click()
        expect(page.locator('#report-receipt-sheet')).to_contain_text('RESUMO DE GESTÃO')
        expect(page.locator('#report-receipt-sheet')).to_contain_text('Documento não fiscal')
        expect(page.locator('#report-receipt-sheet')).to_contain_text('Recebido líquido por forma real')
        expect(page.locator('#report-receipt-sheet')).to_contain_text('Quantidade')
        assert page.locator('#report-receipt-sheet').evaluate('(root)=>[...root.querySelectorAll(".t-report-number")].every(e=>{const r=document.createRange();r.selectNodeContents(e);return r.getClientRects().length===1;})')
        assert page.locator('#report-receipt-sheet').evaluate('(e)=>Math.abs(e.getBoundingClientRect().width-48*96/25.4)<1')
        assert page.locator('#report-receipt-sheet').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        Path('artifacts').mkdir(exist_ok=True)
        page.screenshot(path='artifacts/relatorio-bobina-58.png',full_page=True)
        page.evaluate('()=>{window.printJobs=[];window.print=()=>window.printJobs.push(document.querySelector("#print-area").innerHTML);}')
        page.get_by_role('button',name='Imprimir resumo',exact=True).click()
        page.wait_for_function('()=>window.printJobs.length===1')
        assert 'RESUMO DE GESTÃO' in page.evaluate('window.printJobs[0]')
        page.evaluate('window.dispatchEvent(new Event("afterprint"))')
        expect(page.locator('#print-area')).to_be_empty()
        for width in (390,768):
            page.set_viewport_size({'width':width,'height':900})
            page.keyboard.press('Control+k')
            page.locator('#quick-query').fill('impressao')
            expect(page.locator('[data-quick="printing"]')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.keyboard.press('Escape')
            expect(page.locator('#modal')).not_to_be_visible()
        # A persisted recent page never bypasses a kitchen member's permissions.
        token=page.request.get(live+'/api/session').json()['csrf']
        result=page.request.post(live+'/api/admin/team',headers={'X-CSRF-Token':token},data={'name':'Cozinha Busca','email':'kitchen-search@example.com','password':'senha-segura-nova','role':'kitchen'})
        assert result.status==201
        page.get_by_role('button',name='Sair',exact=True).click()
        page.get_by_label('E-mail',exact=True).fill('kitchen-search@example.com')
        page.get_by_label('Senha',exact=True).fill('senha-segura-nova')
        page.get_by_role('button',name='Entrar no painel').click()
        page.get_by_role('button',name='Buscar no painel (Ctrl+K)',exact=True).click()
        page.locator('#quick-query').fill('relatorio')
        expect(page.locator('[data-quick]')).to_have_count(0)
        expect(page.get_by_text('Nenhuma página encontrada')).to_be_visible()
        assert not errors
        browser.close()
