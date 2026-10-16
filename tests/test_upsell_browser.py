"""Configurar → oferecer → escolher complementos → comprar → medir, no navegador."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.test_browser import live


@pytest.mark.skipif(os.getenv('SKIP_BROWSER') == '1', reason='Chromium não instalado')
def test_contextual_suggestion_checkout_and_report(live):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        admin = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        admin.on('pageerror', lambda e: errors.append(str(e)))
        admin.goto(live + '/entrar')
        admin.get_by_label('E-mail', exact=True).fill('demo@example.com')
        admin.get_by_label('Senha', exact=True).fill('senha-de-teste-segura')
        admin.get_by_role('button', name='Entrar no painel').click()
        admin.get_by_role('button', name='Marketing', exact=True).click()
        source = admin.locator('#combination-form [name=source]')
        source.select_option(label='Suco natural')
        admin.locator('#combination-search').fill('burger')
        admin.get_by_role('button', name='+ Burger da casa', exact=True).click()
        admin.locator('#combination-search').fill('batata')
        admin.get_by_role('button', name='+ Batata da vila', exact=True).click()
        admin.get_by_role('button', name='Subir Batata da vila', exact=True).click()
        expect(admin.locator('#combination-selected li').first).to_contain_text('Batata da vila')
        # Switching sources preserves the unsaved draft for the original source.
        source.select_option(label='Burger da casa')
        source.select_option(label='Suco natural')
        expect(admin.locator('#combination-selected li')).to_have_count(2)
        admin.get_by_role('button', name='Salvar combinações', exact=True).click()
        expect(admin.locator('#combination-status')).to_contain_text('Combinações salvas')
        source_id = int(source.input_value())
        Path('artifacts').mkdir(exist_ok=True)
        admin.locator('.combination-panel').screenshot(path='artifacts/combinacoes-configuracao.png')

        customer = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        page = customer.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(live + '/loja/bistro-da-vila')
        page.get_by_role('button', name='Ver Suco natural', exact=True).click()
        page.get_by_role('button', name='Adicionar •').click()
        expect(page.get_by_role('heading', name='Combina com Suco natural', exact=True)).to_be_visible()
        expect(page.locator('[data-combination]').first).to_have_text('Escolher Batata da vila')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='artifacts/combinacoes-oferta-mobile.png', full_page=True)
        page.get_by_role('button', name='Escolher Burger da casa', exact=True).click()
        page.get_by_label('Bacon crocante').check()
        page.get_by_role('button', name='Adicionar •').click()
        page.reload()  # Attribution survives a refreshed cart, without trusting saved prices.
        page.get_by_role('button', name='Ver minha sacola').click()
        expect(page.locator('.cart-lines')).to_contain_text('Bacon crocante')
        page.get_by_role('button', name='Continuar pedido', exact=True).click()
        page.get_by_label('Seu nome', exact=True).fill('Teste Combinação')
        page.get_by_label('WhatsApp com DDD').fill('11999999999')
        page.get_by_label('Endereço completo').fill('Rua Teste, 12, Centro')
        page.get_by_role('button', name='Confirmar pedido').click()
        page.wait_for_url('**/pedido/**')

        # Complete only the fictitious local order, then inspect the real report UI/API.
        token = admin.request.get(live + '/api/session').json()['csrf']
        order = next(o for o in admin.request.get(live + '/api/admin/orders').json()['orders'] if o['customer'] == 'Teste Combinação')
        item = next(i for i in order['items'] if i['suggested_by'] == source_id)
        assert item['name'] == 'Burger da casa' and item['unit_price'] == 3400
        for status in ('preparing', 'ready', 'delivering', 'completed'):
            response = admin.request.patch(live + '/api/admin/orders/' + str(order['id']), headers={'X-CSRF-Token': token}, data={'status': status})
            assert response.status == 200
        admin.reload()
        admin.get_by_role('button', name='Marketing', exact=True).click()
        expect(admin.locator('#combination-report')).to_contain_text('R$ 34,00')
        expect(admin.locator('#combination-report tbody')).to_contain_text('Suco natural')
        admin.locator('#combination-days').select_option('7')
        expect(admin.locator('#combination-report')).to_contain_text('R$ 34,00')
        admin.locator('#combination-report').screenshot(path='artifacts/combinacoes-resultado.png')
        admin.set_viewport_size({'width': 390, 'height': 844})
        assert admin.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
