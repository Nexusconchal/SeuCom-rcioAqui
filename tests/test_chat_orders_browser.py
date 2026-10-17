"""Merchant config → authenticated callback → real order → visible dashboard.

Evolution and OpenRouter are controlled local test providers, never real customers.
"""
import json
import os
import re

import pytest
from playwright.sync_api import sync_playwright, expect

from tests.test_inbox_browser import inbox_live
from tests.test_api import app
from tests.test_inbox import event
from inbox_service import delivery_tick


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_guided_order_and_free_catalog_lookup_in_browser(inbox_live):
    live,application,callback,outgoing=inbox_live
    application.config['OPENROUTER_API_KEY']='local-test-secret'
    ai_calls=[]
    def model(body,key):
        ai_calls.append(body)
        return 200,{'model':'test/catalog:free','choices':[{'message':{'content':json.dumps({'intent':'catalog','product_ids':[1]})}}]}
    application.extensions['openrouter_http']=model
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page=browser.new_page(viewport={'width':1440,'height':1080});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(live+'/entrar');page.get_by_label('E-mail',exact=True).fill('demo@example.com')
        page.get_by_label('Senha',exact=True).fill('senha-de-teste-segura');page.get_by_role('button',name='Entrar no painel').click()
        page.get_by_role('button',name='Atendimento WhatsApp',exact=True).click()
        page.get_by_role('button',name='Ativar conversas',exact=True).click()
        page.get_by_role('button',name='Autorizar envio',exact=True).click()
        page.get_by_role('button',name='Autorizar novos envios',exact=True).click()
        page.locator('#inbox-bot').check()
        page.get_by_role('button',name='Respostas e atalhos',exact=True).click()
        page.get_by_label('Pedido guiado pelo WhatsApp',exact=True).check()
        page.get_by_label('Usar IA gratuita na consulta de produtos',exact=True).check()
        page.get_by_role('button',name='Salvar respostas e atalhos',exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible()
        def incoming(text):
            response=page.request.post(callback['url'],headers=callback['headers'],data=event(text))
            assert response.status==200
            delivery_tick(application)
        # First featured product is the burger. Extras are optional; choose none.
        incoming('FAZER PEDIDO');incoming('1');incoming('0');incoming('2');incoming('Sem cebola')
        incoming('2');incoming('2');incoming('0');incoming('1')
        thread=page.request.get(live+'/api/admin/inbox').json()['threads'][0]
        detail=page.request.get(live+f"/api/admin/inbox/{thread['id']}").json()
        assert detail['guided_order']['stage']=='review'
        assert '58,00' in detail['messages'][0]['body']
        incoming('CONFIRMAR');delivery_tick(application)
        orders=page.request.get(live+'/api/admin/orders').json()['orders']
        order=next(o for o in orders if o['source']=='whatsapp')
        assert order['total']==5800 and order['items'][0]['quantity']==2
        assert any('criado!' in item['text'] for item in outgoing)
        page.get_by_role('button',name='Atualizar',exact=True).click()
        page.locator('[data-thread]').first.click()
        expect(page.locator('#inbox-guided-state')).to_contain_text('Pedido guiado criado')
        page.get_by_role('button',name='Assumir conversa',exact=True).click()
        page.get_by_role('button',name='Consultar catálogo',exact=True).click()
        page.get_by_label('O que procurar?',exact=True).fill('Um burger com queijo')
        before=len(outgoing)
        page.get_by_role('button',name='Consultar produtos',exact=True).click()
        expect(page.locator('#catalog-lookup-text')).to_contain_text('Burger da casa')
        expect(page.locator('#catalog-lookup-mode')).to_contain_text('IA')
        page.get_by_role('button',name='Inserir na resposta para revisar',exact=True).click()
        expect(page.get_by_label('Resposta',exact=True)).to_have_value(re.compile('Burger da casa'))
        assert len(outgoing)==before and len(ai_calls)==1
        assert len(page.request.get(live+'/api/admin/orders').json()['orders'])==len(orders)
        page.screenshot(path='artifacts/pedido-chat-desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#inbox-conversation').screenshot(path='artifacts/pedido-chat-mobile.png')
        assert errors==[]
        browser.close()
