"""No celular: digitar não dá zoom na tela e quem já pediu não precisa digitar os dados de novo."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect

from tests.test_browser import live


def open_checkout(page, live):
    page.goto(live + "/loja/bistro-da-vila")
    page.get_by_role("button", name="Ver Burger da casa", exact=True).click()
    page.get_by_role("button", name="Adicionar •").click()
    page.get_by_role("button", name="Ver minha sacola").click()
    page.get_by_role("button", name="Continuar pedido").click()


@pytest.mark.skipif(os.getenv("SKIP_BROWSER") == "1", reason="Chromium não instalado")
def test_mobile_checkout_keeps_size_and_remembers_customer(live):
    Path("artifacts").mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        page = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True).new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        open_checkout(page, live)
        # Letra de 16px ou mais em todo campo: o iPhone não amplia a tela ao tocar.
        assert page.evaluate("""[...document.querySelectorAll('#checkout-form input:not([type=checkbox]):not([type=radio]),#checkout-form select,#checkout-form textarea')]
            .every(e=>parseFloat(getComputedStyle(e).fontSize)>=16)""")
        expect(page.locator("#saved-customer")).to_be_hidden()
        page.get_by_label("Seu nome", exact=True).fill("Cliente Navegador")
        page.get_by_label("WhatsApp com DDD").fill("11999999999")
        page.get_by_label("Endereço completo").fill("Rua Teste, 12, Centro")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        # Salvo enquanto digita: fechar sem pedir não perde os dados.
        open_checkout(page, live)
        card = page.locator("#saved-customer")
        expect(card).to_contain_text("Entregar para")
        expect(card).to_contain_text("Cliente Navegador • 11999999999")
        expect(card).to_contain_text("Rua Teste, 12, Centro")
        expect(page.get_by_label("Seu nome", exact=True)).to_be_hidden()
        expect(page.get_by_label("Endereço completo")).to_be_hidden()
        page.screenshot(path="artifacts/checkout-dados-salvos.png", full_page=True)
        page.get_by_text("Retirada", exact=True).click()
        expect(card).to_contain_text("Seus dados")
        expect(card).not_to_contain_text("Rua Teste")
        page.get_by_text("Entrega", exact=True).click()
        page.get_by_role("button", name="Editar", exact=True).click()
        expect(card).to_be_hidden()
        page.get_by_label("Endereço completo").fill("Avenida Nova, 500, Jardim")
        # Pedido sai com os dados lembrados, sem digitar nada.
        open_checkout(page, live)
        expect(card).to_contain_text("Avenida Nova, 500, Jardim")
        page.get_by_role("button", name="Confirmar pedido").click()
        page.wait_for_url("**/pedido/**")
        expect(page.get_by_role("heading", name="Seu pedido chegou!")).to_be_visible()
        assert errors == []
        browser.close()
