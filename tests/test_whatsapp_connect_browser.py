"""WhatsApp caído: aviso no painel, espera no 429 e conexão pelo número (sem QR)."""
import os
import threading

import pytest
from flask import Flask, abort, jsonify, request
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from connectors import Evolution
from tests.test_api import app  # noqa: F401


@pytest.fixture
def disconnected_live(app):  # noqa: F811
    assert app.test_cli_runner().invoke(args=['seed-demo', '--email', 'demo@example.com', '--password', 'senha-de-teste-segura']).exit_code == 0
    calls = []
    service = Flask('evolution-stub-disconnected')

    @service.before_request
    def authorize():
        if request.headers.get('apikey') != 'local-contract-key':
            abort(401)

    @service.get('/instance/connectionState/test-instance')
    def state():
        return jsonify(instance={'state': 'close'})

    @service.get('/instance/connect/test-instance')
    def connect():
        calls.append(request.args.get('number', ''))
        if not request.args.get('number'):
            return jsonify(error='Too Many Requests'), 429
        return jsonify(pairingCode='WZYEH1YY', code='2@abc', count=1)

    @service.delete('/instance/logout/test-instance')
    @service.delete('/instance/delete/test-instance')
    def removed():
        calls.append('apagou')
        return jsonify(status='SUCCESS')

    provider = make_server('127.0.0.1', 0, service, threaded=True)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    app.extensions['evolution'] = Evolution(f'http://127.0.0.1:{provider.server_port}', 'local-contract-key')
    with app.app_context():
        from database import connect
        db = connect(app.config)
        try:
            db.execute("UPDATE stores SET wa_instance='test-instance',wa_enabled=1,inbox_hook_hash='x' WHERE id=1")
        finally:
            db.close()
    web = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{web.server_port}', calls
    finally:
        web.shutdown()
        provider.shutdown()


@pytest.mark.skipif(os.getenv('SKIP_BROWSER') == '1', reason='Chromium não instalado')
def test_disconnected_banner_wait_on_429_and_pairing_code(disconnected_live):
    live, calls = disconnected_live
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(live + '/entrar')
        page.get_by_label('E-mail', exact=True).fill('demo@example.com')
        page.get_by_label('Senha', exact=True).fill('senha-de-teste-segura')
        page.get_by_role('button', name='Entrar no painel').click()
        expect(page.locator('#whatsapp-notice')).to_contain_text('WhatsApp da loja desconectado')
        page.get_by_role('button', name='Reconectar', exact=True).click()
        page.locator('#inbox-connection-action').click()
        page.get_by_role('button', name='Gerar QR Code', exact=True).click()
        expect(page.locator('#inbox-pairing-status')).to_contain_text('Aguarde 3 minutos')
        expect(page.locator('#inbox-create-qr')).to_be_disabled()
        expect(page.locator('#inbox-create-qr')).to_contain_text('Aguarde')
        assert 'apagou' not in calls  # 429 não apaga a conexão
        page.reload()
        page.get_by_role('button', name='Atendimento WhatsApp', exact=True).click()
        page.locator('#inbox-connection-action').click()
        page.get_by_text('O QR Code não aparece ou não lê? Conectar pelo número').click()
        page.get_by_label('WhatsApp da loja com DDD').fill('(19) 99933-8422')
        page.get_by_role('button', name='Gerar código', exact=True).click()
        expect(page.locator('#inbox-pair-result')).to_contain_text('WZYE-H1YY')
        assert '5519999338422' in calls
        assert not errors
        browser.close()
