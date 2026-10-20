import io
import os
import wave
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright, expect

from inbox_service import delivery_tick
from tests.test_api import app
from tests.test_inbox import event
from tests.test_inbox_browser import inbox_live


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_workspace_customer_order_media_search_and_reconnection(inbox_live,tmp_path):
    live,app,callback,outgoing=inbox_live
    Path('artifacts').mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page=browser.new_page(viewport={'width':1728,'height':1200});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(live+'/entrar');page.get_by_label('E-mail',exact=True).fill('demo@example.com')
        page.get_by_label('Senha',exact=True).fill('senha-de-teste-segura');page.get_by_role('button',name='Entrar no painel').click()
        page.get_by_role('button',name='Atendimento WhatsApp',exact=True).click()
        page.get_by_role('button',name='Ativar conversas',exact=True).click()
        page.get_by_role('button',name='Autorizar envio',exact=True).click()
        page.get_by_role('button',name='Autorizar novos envios',exact=True).click()
        page.get_by_role('button',name='Ver conexão / QR',exact=True).click()
        page.get_by_role('button',name='Gerar QR Code',exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible(timeout=10000)
        incoming=event('Quero confirmar meu pedido')
        assert page.request.post(callback['url'],headers=callback['headers'],data=incoming).status==200
        expect(page.locator('[data-thread]')).to_have_count(1,timeout=12000)
        page.locator('[data-thread]').click();page.get_by_role('button',name='Assumir conversa',exact=True).click()
        expect(page.locator('#inbox-customer')).to_contain_text('Ainda sem pedidos')
        page.get_by_role('button',name='Montar pedido',exact=True).click()
        page.locator('#manual-order [name^="p_"]').first.fill('1')
        assert page.locator('#manual-order').evaluate('(form)=>form.checkValidity()'),page.locator('#manual-order').inner_text()
        created=[]
        page.on('response',lambda r:created.append(r) if r.url.endswith('/api/admin/orders') and r.request.method=='POST' else None)
        page.get_by_role('button',name='Criar pedido',exact=True).click()
        try:
            page.wait_for_function("()=>!document.querySelector('#modal').open || !!document.querySelector('#manual-order .form-error')?.textContent",timeout=5000)
        except Exception:
            raise AssertionError({'toast':page.locator('#toast').inner_text(),'errors':errors,'form':page.locator('#manual-order').inner_text()}) from None
        assert created,page.locator('#manual-order').inner_text()
        assert created[0].status==201,created[0].text()
        number=created[0].json()['number']
        expect(page.locator('#inbox-customer')).to_contain_text('#'+str(number))
        page.get_by_role('button',name='Usar cliente e endereço em novo pedido',exact=True).click()
        expect(page.get_by_label('Telefone com DDD',exact=True)).to_have_value('11999999999')
        page.get_by_role('button',name='Fechar',exact=True).click()
        image_event=event(eid='inbox-photo-test');image_event['data']['message']={'imageMessage':{'mimetype':'image/png','fileLength':200,'caption':'Foto da embalagem'}}
        page.request.post(callback['url'],headers=callback['headers'],data=image_event)
        expect(page.locator('[data-open-media]')).to_have_count(1,timeout=12000)
        with page.expect_response(lambda r:r.url.endswith('/media')) as picture:
            page.get_by_role('button',name='Visualizar foto').click()
        assert picture.value.status==200 and picture.value.headers['content-type'].startswith('image/webp')
        expect(page.locator('.inbox-media-image')).to_be_visible()
        page.get_by_role('button',name='Fechar',exact=True).click()
        image_path=tmp_path/'embalagem.png';Image.new('RGB',(40,30),'green').save(image_path)
        page.get_by_role('button',name='Anexar foto ou áudio',exact=True).click()
        page.get_by_label('Foto ou áudio',exact=True).set_input_files(str(image_path))
        page.get_by_label('Legenda opcional',exact=True).fill('Assim vai seu pedido')
        page.get_by_role('button',name='Confirmar envio do arquivo',exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible()
        assert delivery_tick(app)['sent']==1 and len(outgoing)==1
        expect(page.locator('.inbox-history')).to_contain_text('Assim vai seu pedido',timeout=12000)
        audio_path=tmp_path/'confirmacao.wav'
        with wave.open(str(audio_path),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*800)
        page.get_by_role('button',name='Anexar foto ou áudio',exact=True).click()
        page.get_by_label('Foto ou áudio',exact=True).set_input_files(str(audio_path))
        expect(page.get_by_label('Legenda opcional',exact=True)).to_be_disabled()
        page.get_by_role('button',name='Confirmar envio do arquivo',exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible()
        assert delivery_tick(app)['sent']==1 and len(outgoing)==2
        expect(page.get_by_role('button',name='Ouvir áudio')).to_have_count(1,timeout=12000)
        page.get_by_role('button',name='Ouvir áudio').click();expect(page.locator('audio')).to_be_visible()
        page.get_by_role('button',name='Fechar',exact=True).click()
        page.get_by_label('Buscar no histórico carregado',exact=True).fill('embalagem')
        expect(page.locator('.inbox-bubble')).to_have_count(2)
        page.get_by_label('Buscar no histórico carregado',exact=True).fill('sem resultado')
        expect(page.locator('.inbox-bubble')).to_have_count(0)
        page.get_by_label('Buscar no histórico carregado',exact=True).fill('')
        page.screenshot(path='artifacts/atendimento-workspace-desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.get_by_role('button',name='Cliente e pedidos',exact=True).click()
        expect(page.locator('#inbox-customer')).to_be_visible()
        page.locator('#inbox-workspace').screenshot(path='artifacts/atendimento-workspace-mobile.png')
        assert errors==[]
        browser.close()
