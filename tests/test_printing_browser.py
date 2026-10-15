"""Windows browser printing boundary; no hardware or real spooler job is claimed."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect

from tests.test_browser import live


@pytest.mark.skipif(os.getenv('SKIP_BROWSER') == '1', reason='Chromium não instalado')
def test_printer_profiles_layout_queue_and_cancel(live):
    artifacts = Path('artifacts')
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script("""window.printJobs=[]; window.print=()=>window.printJobs.push({
            html:document.querySelector('#print-area').innerHTML,
            width:document.querySelector('#print-area').style.getPropertyValue('--ticket-width')});""")
        page.goto(live + '/entrar')
        page.get_by_label('E-mail', exact=True).fill('demo@example.com')
        page.get_by_label('Senha', exact=True).fill('senha-de-teste-segura')
        page.get_by_role('button', name='Entrar no painel').click()
        page.get_by_role('button', name='Imprimir notinha', exact=True).click()
        expect(page.get_by_text('Escolha sua impressora na janela de impressão', exact=True)).to_be_visible()
        assert page.locator('#paper-width option').count() == 6
        page.locator('#driverslip').check()
        for profile, width in [('80',72),('58',48),('76',68),('112',104),('a4',190),('custom',32)]:
            page.get_by_label('Largura do papel', exact=True).select_option(profile)
            if profile == 'custom':
                page.get_by_label('Área útil de impressão em milímetros').fill(str(width))
                page.get_by_label('Área útil de impressão em milímetros').blur()
            page.get_by_label('Tamanho das letras na notinha').select_option('16')
            page.get_by_role('button', name='Ver prévia', exact=True).click()
            expect(page.locator('#print-preview-sheet')).to_contain_text('documento não fiscal')
            expect(page.locator('#print-preview-sheet')).to_contain_text('VIA DO MOTOBOY')
            expect(page.locator('#print-preview-sheet')).to_contain_text('ação, açúcar, café')
            assert page.locator('#print-preview-sheet .ticket').first.evaluate('(e)=>Math.abs(e.getBoundingClientRect().width-'+str(width)+'*96/25.4)<1')
            if profile == '58':
                page.screenshot(path=str(artifacts / 'impressora-previa-58.png'), full_page=True)
            page.get_by_role('button', name='Fechar', exact=True).click()
            previous = page.evaluate('window.printJobs.length')
            page.get_by_role('button', name='Imprimir teste', exact=True).click()
            page.wait_for_function('(n)=>window.printJobs.length===n+1', arg=previous)
            assert page.evaluate('window.printJobs.at(-1).width') == str(width)+'mm'
            page.emulate_media(media='print')
            assert page.locator('#app').evaluate('(e)=>getComputedStyle(e).display') == 'none'
            assert page.locator('#print-area .ticket').count() == 2
            assert page.locator('#print-area').evaluate("""root=>[...root.querySelectorAll('.ticket,.t-calibration')].every(ticket=>{
                const box=ticket.getBoundingClientRect();return [...ticket.querySelectorAll('*')].every(e=>{
                    const b=e.getBoundingClientRect();return b.right<=box.right+1&&b.left>=box.left-1;
                });})""")
            params = {'format':'A4'} if profile == 'a4' else {'width':str(int(profile) if profile.isdigit() else width+8)+'mm','height':'300mm'}
            pdf = page.pdf(path=str(artifacts / ('impressao-'+profile+'.pdf')), print_background=False, display_header_footer=False, **params)
            assert pdf.startswith(b'%PDF-') and len(pdf)>1000
            page.emulate_media(media='screen')
            page.evaluate("window.dispatchEvent(new Event('afterprint'))")
            expect(page.locator('#print-area')).to_be_empty()
        page.get_by_label('Largura do papel', exact=True).select_option('58')
        page.get_by_label('Área útil de impressão em milímetros').fill('999')
        page.get_by_label('Área útil de impressão em milímetros').blur()
        expect(page.get_by_label('Área útil de impressão em milímetros')).to_have_value('48')
        page.get_by_label('Largura do papel', exact=True).select_option('custom')
        expect(page.get_by_label('Área útil de impressão em milímetros')).to_have_value('32')
        page.reload()
        page.get_by_role('button', name='Imprimir notinha', exact=True).click()
        expect(page.get_by_label('Largura do papel', exact=True)).to_have_value('custom')
        expect(page.get_by_label('Área útil de impressão em milímetros')).to_have_value('32')
        expect(page.get_by_label('Tamanho das letras na notinha')).to_have_value('16')
        # A closed/cancelled dialog releases the next print, without claiming physical delivery.
        page.get_by_role('button', name='Imprimir teste', exact=True).click()
        page.wait_for_function('()=>window.printJobs.length===1')
        page.get_by_role('button', name='Imprimir teste', exact=True).click()
        assert page.evaluate('window.printJobs.length') == 1
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        page.wait_for_function('()=>window.printJobs.length===2')
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        expect(page.locator('#print-area')).to_be_empty()
        page.evaluate("()=>{window.print=()=>{throw new Error('printer unavailable')};}")
        page.get_by_role('button', name='Imprimir teste', exact=True).click()
        expect(page.locator('#toast')).to_contain_text('Não consegui abrir a impressão')
        expect(page.locator('body')).not_to_have_class('printing-ticket')
        for width in (390,768,1440):
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(artifacts / 'impressora-windows.png'), full_page=True)
        assert not errors
        browser.close()
