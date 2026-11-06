"""Banco de imagens no Chromium: lojista escolhe uma foto pronta e o cliente vê o aviso de imagem ilustrativa."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect

from tests.test_browser import live  # noqa: F401  (fixture do servidor com a loja demo)


@pytest.mark.skipif(os.getenv("SKIP_BROWSER") == "1", reason="Chromium não instalado")
def test_owner_picks_photo_from_image_bank(live):  # noqa: F811
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live + "/entrar")
        page.get_by_label("E-mail", exact=True).fill("demo@example.com")
        page.get_by_label("Senha", exact=True).fill("senha-de-teste-segura")
        page.get_by_role("button", name="Entrar no painel").click()
        page.wait_for_url("**/painel")
        page.get_by_role("button", name="Cardápio", exact=True).click()
        page.get_by_role("button", name="Novo produto", exact=True).click()
        page.get_by_label("Nome do produto").fill("Pizza de calabresa")
        page.get_by_role("button", name="Escolher no banco de imagens").click()
        bank = page.locator("#image-bank")
        expect(bank.get_by_role("heading", name="Banco de imagens")).to_be_visible()
        first = bank.locator(".bank-item").first
        expect(first).to_contain_text("Pizza de calabresa")
        page.wait_for_function("() => Array.from(document.querySelectorAll('#image-bank img')).slice(0, 8).every(img => img.complete && img.naturalWidth > 0)")
        page.screenshot(path=str(artifacts / "banco-imagens-desktop.png"))
        bank.get_by_role("button", name="Todas").click()
        bank.get_by_role("searchbox").fill("")
        expect(bank.locator(".bank-item")).to_have_count(len(page.evaluate("fetch('/static/banco-imagens/catalogo.json').then(r => r.json()).then(d => d.imagens)")))
        bank.get_by_role("searchbox").fill("marmita")
        expect(bank.locator(".bank-item").first).to_be_visible()
        bank.get_by_role("searchbox").fill("pizza calabresa")
        expect(first).to_contain_text("Pizza de calabresa")
        first.click()
        expect(bank).not_to_be_visible()
        form = page.locator("#product-form")
        expect(form.locator("[name=image]")).to_have_value("/static/banco-imagens/pizza-de-calabresa.webp")
        expect(form.locator(".upload-preview")).to_be_visible()
        form.get_by_label("Preço", exact=True).fill("49.90")
        form.get_by_role("button", name="Salvar produto").click()
        expect(page.locator("#modal")).not_to_be_visible()

        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True).new_page()
        phone.on("pageerror", lambda error: errors.append(str(error)))
        phone.goto(live + "/loja/bistro-da-vila")
        phone.get_by_role("button", name="Ver Pizza de calabresa", exact=True).click()
        expect(phone.get_by_text("Imagem ilustrativa")).to_be_visible()
        expect(phone.get_by_role("link", name="créditos da foto")).to_have_attribute("href", "/static/banco-imagens/creditos.html")
        assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth")
        # O painel em celular já é desenhado com 760px (antes desta mudança); aqui conferimos a janela do banco numa tela estreita.
        owner = browser.new_page(viewport={"width": 390, "height": 844})
        owner.on("pageerror", lambda error: errors.append(str(error)))
        owner.goto(live + "/entrar")
        owner.get_by_label("E-mail", exact=True).fill("demo@example.com")
        owner.get_by_label("Senha", exact=True).fill("senha-de-teste-segura")
        owner.get_by_role("button", name="Entrar no painel").click()
        owner.wait_for_url("**/painel")
        owner.get_by_role("button", name="Cardápio", exact=True).click()
        owner.get_by_role("button", name="Novo produto", exact=True).click()
        owner.get_by_role("button", name="Escolher no banco de imagens").click()
        mobile_bank = owner.locator("#image-bank")
        expect(mobile_bank.get_by_role("heading", name="Banco de imagens")).to_be_visible()
        box = mobile_bank.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        owner.wait_for_function("() => Array.from(document.querySelectorAll('#image-bank img')).slice(0, 6).every(img => img.complete && img.naturalWidth > 0)")
        owner.screenshot(path=str(artifacts / "banco-imagens-celular.png"))
        assert errors == []
        browser.close()
