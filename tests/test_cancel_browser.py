"""Cancelar pelo cartão do pedido: botão embaixo do avanço e confirmação antes de cancelar."""
import os

import pytest
from playwright.sync_api import sync_playwright, expect

from tests.test_browser import live  # noqa: F401


@pytest.mark.skipif(os.getenv("SKIP_BROWSER") == "1", reason="Chromium não instalado")
def test_cancel_from_order_card_asks_before_cancelling(live):  # noqa: F811
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or None)
        customer = browser.new_page()
        customer.goto(live + "/loja/bistro-da-vila")
        status = customer.evaluate("""async()=>{
            const cat=await (await fetch('/api/store/bistro-da-vila')).json();
            const product=cat.products.find(x=>!(x.option_groups||[]).some(g=>g.min>0)&&x.stock!==0);
            const s=await (await fetch('/api/session')).json();
            const r=await fetch('/api/store/bistro-da-vila/orders',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf,'Idempotency-Key':crypto.randomUUID().replace(/-/g,'')},
              body:JSON.stringify({customer:'Cliente Desistiu',phone:'11977776666',mode:'pickup',address:'',payment:'cash',notes:'',items:[{product_id:product.id,quantity:1,option_ids:[],notes:''}]})});
            return r.status;}""")
        assert status == 201
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live + "/entrar")
        page.get_by_label("E-mail", exact=True).fill("demo@example.com")
        page.get_by_label("Senha", exact=True).fill("senha-de-teste-segura")
        page.get_by_role("button", name="Entrar no painel").click()
        page.get_by_role("button", name="Pedidos", exact=True).click()
        card = page.locator(".order-card").filter(has_text="Cliente Desistiu")
        card.get_by_role("button", name="Aceitar pedido", exact=True).click()
        card = page.locator(".order-card").filter(has_text="Cliente Desistiu")
        expect(card.get_by_role("button", name="Marcar pronto", exact=True)).to_be_visible()
        card.get_by_role("button", name="Cancelar pedido", exact=True).click()
        expect(page.locator("#modal-title")).to_have_text("Tem certeza que quer cancelar?")
        page.get_by_role("button", name="Não, manter pedido", exact=True).click()
        expect(page.locator(".order-card").filter(has_text="Cliente Desistiu")).to_be_visible()
        page.locator(".order-card").filter(has_text="Cliente Desistiu").get_by_role("button", name="Cancelar pedido", exact=True).click()
        page.get_by_role("button", name="Sim, cancelar pedido", exact=True).click()
        expect(page.locator("#toast")).to_contain_text("cancelado")
        expect(page.locator(".order-card").filter(has_text="Cliente Desistiu")).to_have_count(0)
        statuses = page.evaluate("async()=>(await (await fetch('/api/admin/orders')).json()).orders.filter(o=>o.customer==='Cliente Desistiu').map(o=>o.status)")
        assert statuses == ["cancelled"]
        assert not errors
        browser.close()
