"""Browser → HTTP API → database → dispatcher → local Evolution-compatible HTTP stub."""
import os
import re
import threading
import uuid
from pathlib import Path

import pytest
from flask import Flask, request, jsonify, abort
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from connectors import Evolution
from inbox_service import delivery_tick
from tests.test_api import app
from tests.test_inbox import event


@pytest.fixture
def inbox_live(app):
    assert app.test_cli_runner().invoke(args=['seed-demo','--email','demo@example.com','--password','senha-de-teste-segura']).exit_code==0
    callback={};outgoing=[]
    service=Flask('evolution-contract-stub')

    @service.before_request
    def authorize():
        if request.headers.get('apikey')!='local-contract-key':abort(401)

    @service.get('/instance/connectionState/test-instance')
    def connection():return jsonify(instance={'state':'open'})

    @service.post('/webhook/set/test-instance')
    def webhook():
        value=request.get_json()['webhook'];callback.update(value)
        assert value['events']==['MESSAGES_UPSERT'] and not value['byEvents']
        return jsonify(enabled=True),201

    @service.post('/message/sendText/test-instance')
    def send_text():
        value=request.get_json();outgoing.append(value)
        assert value['number'].startswith('55') and isinstance(value['text'],str)
        return jsonify(key={'id':uuid.uuid4().hex}),201

    provider_server=make_server('127.0.0.1',0,service,threaded=True)
    provider_thread=threading.Thread(target=provider_server.serve_forever,daemon=True);provider_thread.start()
    app.extensions['evolution']=Evolution(f'http://127.0.0.1:{provider_server.server_port}','local-contract-key')
    with app.app_context():
        from database import connect
        db=connect(app.config)
        try:db.execute("UPDATE stores SET wa_instance='test-instance' WHERE id=1")
        finally:db.close()
    web=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=web.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{web.server_port}',app,callback,outgoing
    finally:web.shutdown();thread.join();provider_server.shutdown();provider_thread.join()


@pytest.mark.skipif(os.getenv('SKIP_BROWSER')=='1',reason='Chromium não instalado')
def test_live_inbox_configuration_polling_drafts_quick_replies_and_http_delivery(inbox_live):
    live,app,callback,outgoing=inbox_live
    Path('artifacts').mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page=browser.new_page(viewport={'width':1440,'height':1080});errors=[];polls=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:polls.append(r.url) if r.url.endswith('/api/admin/inbox') else None)
        page.goto(live+'/entrar');page.get_by_label('E-mail',exact=True).fill('demo@example.com')
        page.get_by_label('Senha',exact=True).fill('senha-de-teste-segura');page.get_by_role('button',name='Entrar no painel').click()
        page.get_by_role('button',name='Atendimento WhatsApp',exact=True).click()
        page.get_by_role('button',name='Ativar conversas',exact=True).click()
        expect(page.get_by_role('button',name='Autorizar envio',exact=True)).to_be_enabled()
        page.get_by_role('button',name='Autorizar envio',exact=True).click()
        page.get_by_role('button',name='Autorizar novos envios',exact=True).click()
        page.locator('#inbox-bot').check()
        # Real HTTP callback into the application, using the token registered at the local stub.
        result=page.request.post(callback['url'],headers=callback['headers'],data=event('Oi, quero o cardápio'))
        assert result.status==200
        assert delivery_tick(app)['sent']==1 and len(outgoing)==1
        expect(page.locator('[data-thread]')).to_have_count(1,timeout=12000)
        page.locator('[data-thread]').click()
        expect(page.locator('.inbox-history')).to_contain_text('Aceita pelo serviço')
        page.get_by_role('button',name='Assumir conversa',exact=True).click()
        page.get_by_label('Resposta',exact=True).fill('/aguarde')
        page.get_by_role('button',name='/aguarde',exact=True).click()
        expect(page.get_by_label('Resposta',exact=True)).to_have_value(re.compile('Só um instante, Cliente'))
        with page.expect_response(lambda r:r.url.endswith('/reply') and r.request.method=='POST') as reply:
            page.get_by_role('button',name='Enviar resposta',exact=True).click()
        assert reply.value.status==202
        expect(page.get_by_label('Resposta',exact=True)).to_have_value('')
        page.get_by_label('Resposta',exact=True).fill('Novo rascunho que não pode desaparecer')
        assert delivery_tick(app)['sent']==1 and len(outgoing)==2
        expect(page.locator('.inbox-history')).to_contain_text('Só um instante, Cliente',timeout=12000)
        page.request.post(callback['url'],headers=callback['headers'],data=event('Também quero uma bebida'))
        expect(page.locator('.inbox-history')).to_contain_text('Também quero uma bebida',timeout=12000)
        expect(page.get_by_label('Resposta',exact=True)).to_have_value('Novo rascunho que não pode desaparecer')
        page.get_by_role('button',name='Montar pedido',exact=True).click()
        expect(page.get_by_label('Cliente',exact=True)).to_have_value('Cliente da conversa')
        expect(page.get_by_label('Telefone com DDD',exact=True)).to_have_value('11999999999')
        page.get_by_role('button',name='Fechar',exact=True).click()
        page.get_by_role('button',name='Respostas e atalhos',exact=True).click()
        page.get_by_role('button',name='Respostas rápidas',exact=True).click()
        page.locator('#inbox-quick-rows [data-message]').first.fill('Olá, {nome}! Seu cardápio: {link}')
        page.get_by_role('button',name='Salvar respostas e atalhos',exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible()
        page.get_by_role('button',name='Testar resposta',exact=True).click()
        page.get_by_label('Mensagem do cliente',exact=True).fill('Quero falar com um ATENDENTE')
        page.get_by_role('button',name='Ver resposta',exact=True).click()
        expect(page.locator('#inbox-simulation-result')).to_contain_text('atendente humano')
        assert len(outgoing)==2
        page.get_by_role('button',name='Fechar',exact=True).click()
        page.evaluate("document.querySelector('#toast').classList.remove('show')")
        page.screenshot(path='artifacts/atendimento-operacional-desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#inbox-conversation').screenshot(path='artifacts/atendimento-operacional-mobile.png')
        page.get_by_role('button',name='Voltar às conversas',exact=True).click()
        page.get_by_label('Buscar conversa',exact=True).fill('bebida')
        expect(page.locator('[data-thread]')).to_have_count(1)
        page.get_by_label('Buscar conversa',exact=True).fill('sem correspondência')
        expect(page.locator('[data-thread]')).to_have_count(0)
        page.get_by_role('button',name='Visão geral',exact=True).click()
        expect(page.get_by_role('heading',name='Seu dia em um olhar',exact=True)).to_be_visible()
        count=len(polls);page.wait_for_timeout(5500)
        assert len(polls)==count and errors==[]
        browser.close()
