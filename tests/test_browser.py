"""Compras e gestão exercitadas num Chromium real, em desktop e celular."""
import os
import sqlite3
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from app import create_app


@pytest.fixture
def live(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "browser-test-secret",
                       "DATABASE_URL": "", "STORAGE_UPLOAD_URL": "",
                       "DATABASE_PATH": str(tmp_path / "browser.sqlite3"),
                       "UPLOAD_DIR": str(tmp_path / "uploads"), "RATE_LIMIT_ENABLED": False, "PUBLIC_URL": ""})
    result = app.test_cli_runner().invoke(args=["seed-demo", "--email", "demo@example.com", "--password", "senha-de-teste-segura"])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(app.config["DATABASE_PATH"]) as connection:
        connection.execute("UPDATE stores SET phone=? WHERE slug=?", ("11999999999", "bistro-da-vila"))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


@pytest.mark.skipif(os.getenv("SKIP_BROWSER") == "1", reason="Chromium não instalado")
def test_mobile_checkout_and_desktop_management(live):
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = mobile.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live + "/loja/bistro-da-vila")
        expect(page.get_by_role("heading", name="Bistrô da Vila", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate("document.querySelectorAll('img').forEach(img => img.loading='eager')")
        page.wait_for_function("() => Array.from(document.images).every(img => img.complete)", timeout=20000)
        page.screenshot(path=str(artifacts / "cardapio-mobile.png"), full_page=True)
        page.get_by_role("button", name="Ver Burger da casa", exact=True).click()
        page.get_by_label("Bacon crocante").check()
        page.get_by_role("button", name="Adicionar •").click()
        page.get_by_role("button", name="Ver minha sacola").click()
        page.get_by_role("button", name="Continuar pedido").click()
        page.get_by_label("Seu nome", exact=True).fill("Cliente Navegador")
        page.get_by_label("WhatsApp com DDD").fill("11999999999")
        page.get_by_label("Endereço completo").fill("Rua Teste, 12, Centro")
        page.get_by_label("Cupom de desconto").fill("BEMVINDO10")
        page.get_by_role("button", name="Aplicar", exact=True).click()
        expect(page.locator("#checkout-totals")).to_contain_text("35,60")
        page.screenshot(path=str(artifacts / "checkout-mobile.png"), full_page=True)
        page.get_by_role("button", name="Confirmar pedido").click()
        page.wait_for_url("**/pedido/**")
        expect(page.get_by_role("heading", name="Seu pedido chegou!")).to_be_visible()
        expect(page.get_by_role("heading", name="Pague com Pix")).to_be_visible()
        page.screenshot(path=str(artifacts / "acompanhamento-mobile.png"), full_page=True)
        expect(page.get_by_role("link", name="Falar com a loja")).to_have_attribute("href", "https://wa.me/5511999999999?text=Ol%C3%A1!%20Gostaria%20de%20falar%20sobre%20o%20pedido%20%231045")
        tracking = page.url
        desktop = browser.new_context(viewport={"width": 1440, "height": 1000})
        admin = desktop.new_page()
        admin.on("pageerror", lambda error: errors.append(str(error)))
        admin.goto(live + "/entrar")
        admin.get_by_label("E-mail", exact=True).fill("demo@example.com")
        admin.get_by_label("Senha", exact=True).fill("senha-de-teste-segura")
        admin.get_by_role("button", name="Entrar no painel").click()
        admin.wait_for_url("**/painel")
        expect(admin.get_by_role("heading", name="Seu dia em um olhar")).to_be_visible()
        expect(admin.get_by_text("Cliente Navegador", exact=True)).to_be_visible()
        assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth")
        admin.screenshot(path=str(artifacts / "painel-desktop.png"), full_page=True)
        admin.get_by_role("button", name="Pedidos", exact=True).click()
        admin.get_by_role("button", name="Ver pedido 1045", exact=True).click()
        admin.get_by_label("Pagamento confirmado", exact=True).check()
        admin.get_by_role("button", name="Salvar atualização").click()
        expect(admin.locator("#modal")).not_to_be_visible()
        card = admin.locator(".order-card").filter(has_text="Cliente Navegador")
        card.get_by_role("button", name="Aceitar pedido", exact=True).click()
        expect(card.get_by_role("button", name="Marcar pronto", exact=True)).to_be_visible()
        card.get_by_role("button", name="Marcar pronto", exact=True).click()
        expect(card.get_by_role("button", name="Saiu para entrega", exact=True)).to_be_visible()
        card.get_by_role("button", name="Saiu para entrega", exact=True).click()
        expect(card.get_by_role("button", name="Concluir entrega", exact=True)).to_be_visible()
        card.get_by_role("button", name="Concluir entrega", exact=True).click()
        expect(admin.locator("#orders-area").get_by_text("Cliente Navegador", exact=True)).not_to_be_visible()
        page.goto(tracking)
        expect(page.get_by_role("heading", name="Tudo certo por aqui.")).to_be_visible()
        expect(page.get_by_text("Pagamento confirmado", exact=True)).to_be_visible()
        admin.get_by_role("button", name="Cardápio", exact=True).click()
        expect(admin.get_by_role("heading", name="Produtos da loja", exact=True)).to_be_visible()
        admin.get_by_role("button", name="Novo produto", exact=True).click()
        admin.get_by_label("Nome do produto").fill("Produto do navegador")
        admin.get_by_label("Preço", exact=True).fill("12.50")
        admin.get_by_role("button", name="Salvar produto", exact=True).click()
        expect(admin.get_by_text("Produto do navegador", exact=True)).to_be_visible()
        admin.get_by_role("button", name="Vendas", exact=True).click()
        expect(admin.get_by_role("heading", name="Os números do seu negócio")).to_be_visible()
        expect(admin.locator(".metric").filter(has_text="Vendas concluídas")).to_contain_text("35,60")
        admin.screenshot(path=str(artifacts / "vendas-desktop.png"), full_page=True)
        admin.set_viewport_size({"width": 390, "height": 844})
        admin.get_by_role("button", name="Visão geral", exact=True).click()
        expect(admin.get_by_role("heading", name="Seu dia em um olhar")).to_be_visible()
        assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth")
        admin.locator("#toast").evaluate("(element) => element.classList.remove('show')")
        admin.screenshot(path=str(artifacts / "painel-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()


@pytest.mark.skipif(os.getenv("SKIP_BROWSER") == "1", reason="Chromium não instalado")
def test_new_store_registration_settings_and_product(live):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(live + "/entrar?cadastro=1")
        page.get_by_label("Seu nome", exact=True).fill("Nova Dona")
        page.get_by_label("Nome do comércio", exact=True).fill("Minha Loja Nova")
        page.get_by_label("E-mail", exact=True).fill("new@example.com")
        page.get_by_label("Senha", exact=True).fill("senha-muito-segura")
        page.get_by_role("button", name="Criar minha loja", exact=True).click()
        page.wait_for_url("**/painel")
        expect(page.get_by_role("button", name="Loja fechada")).to_be_visible()
        page.get_by_role("button", name="Configurações", exact=True).click()
        page.get_by_label("Chave Pix", exact=True).fill("new@example.com")
        page.get_by_role("button", name="Salvar configurações").click()
        expect(page.locator("#toast")).to_contain_text("Sua loja foi atualizada")
        page.get_by_role("button", name="Loja fechada").click()
        expect(page.get_by_role("button", name="Loja aberta")).to_be_visible()
        page.get_by_role("button", name="Cardápio", exact=True).click()
        page.get_by_role("button", name="Novo produto", exact=True).click()
        page.get_by_label("Nome do produto").fill("Meu primeiro produto")
        page.get_by_label("Preço", exact=True).fill("15.00")
        page.get_by_role("button", name="Salvar produto", exact=True).click()
        expect(page.get_by_text("Meu primeiro produto", exact=True)).to_be_visible()
        page.goto(live + "/loja/minha-loja-nova")
        expect(page.get_by_role("heading", name="Minha Loja Nova", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Ver Meu primeiro produto")).to_be_visible()
        browser.close()
