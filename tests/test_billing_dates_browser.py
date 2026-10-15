import os
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from database import connect
from tests.test_api import app


@pytest.mark.skipif(os.getenv('SKIP_BROWSER') == '1', reason='Chromium não instalado')
def test_platform_dates_show_year_and_brasilia_time(app):
    result = app.test_cli_runner().invoke(args=['seed-demo', '--email', 'demo@example.com', '--password', 'senha-de-teste-segura'])
    assert result.exit_code == 0, result.output
    app.test_cli_runner().invoke(args=['grant-platform-admin', '--email', 'demo@example.com'])
    conn = connect(app.config)
    conn.execute("UPDATE users SET created_at='2026-01-01T00:10:11+00:00'")
    conn.execute("UPDATE stores SET subscribed_at='2026-01-01T00:15:23+00:00',sub_status='authorized'")
    sid = conn.execute('SELECT id FROM stores').fetchone()[0]
    conn.execute("""INSERT INTO platform_ledger(store_id,kind,description,amount,created_at,paid_at,is_subscription)
                 VALUES(?,'receipt','Mensalidade de teste',5999,'2026-01-03T12:00:00+00:00','2026-01-01T01:02:03+00:00',1)""", (sid,))
    conn.close()
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
            page = browser.new_page(viewport={'width':1440,'height':1000}, timezone_id='Pacific/Honolulu')
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/admin')
            page.get_by_label('E-mail', exact=True).fill('demo@example.com')
            page.get_by_label('Senha', exact=True).fill('senha-de-teste-segura')
            page.get_by_role('button', name='Entrar na Central').click()
            page.get_by_role('button', name='Lojas e contas', exact=True).click()
            table = page.locator('#platform-stores')
            expect(table).to_contain_text('Conta criada em')
            expect(table).to_contain_text('31/12/2025, 21:10:11')
            expect(table).to_contain_text('31/12/2025, 21:15:23')
            expect(table).to_contain_text('Último pagamento aprovado')
            expect(table).to_contain_text('31/12/2025, 22:02:03')
            Path('artifacts').mkdir(exist_ok=True)
            page.screenshot(path='artifacts/admin-datas-desktop.png', full_page=True)
            for width in (390,768,1440):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        thread.join()
