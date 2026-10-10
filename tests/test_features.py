import uuid
from datetime import datetime, timedelta, timezone

from app import ZONE, store_status
from tests.test_api import app, shop, send, register, payload
from tests.test_business import make_order, advance


def schedule_store(hours, open_=1, enabled=1):
    import json
    return {"enabled": enabled, "open": open_, "auto_hours": 1, "hours": json.dumps(hours)}


def at(weekday_day, hour, minute=0):
    # 2026-10-05 é uma segunda-feira.
    return datetime(2026, 10, 5 + weekday_day, hour, minute, tzinfo=ZONE)


def test_store_status_follows_schedule_and_overnight_shifts():
    store = schedule_store({"0": [["11:00", "14:00"], ["18:00", "02:00"]], "4": [["18:00", "23:00"]]})
    assert store_status(store, at(0, 12)) == (True, "Aberto até 14:00")
    assert store_status(store, at(0, 15)) == (False, "Fechado • abre hoje às 18:00")
    assert store_status(store, at(0, 23, 30))[0] is True
    assert store_status(store, at(1, 1, 30)) == (True, "Aberto até 02:00")
    assert store_status(store, at(1, 3)) == (False, "Fechado • abre sexta às 18:00")
    assert store_status(schedule_store({"0": [["11:00", "14:00"]]}, open_=0), at(0, 12))[0] is False
    assert store_status(schedule_store({"0": [["11:00", "14:00"]]}, enabled=0), at(0, 12))[0] is False


def test_hours_validation_and_closed_schedule_blocks_orders(shop):
    client, pid = shop
    store = client.get("/api/admin/store").json["store"]
    assert send(client, "PUT", "/api/admin/store", {**store, "auto_hours": True, "hours": {}}).status_code == 400
    assert send(client, "PUT", "/api/admin/store", {**store, "hours": {"0": [["25:00", "26:00"]]}}).status_code == 400
    assert send(client, "PUT", "/api/admin/store", {**store, "hours": {"9": [["10:00", "11:00"]]}}).status_code == 400
    weekday = str((datetime.now(ZONE).weekday() + 3) % 7)
    saved = send(client, "PUT", "/api/admin/store", {**store, "auto_hours": True, "hours": {weekday: [["10:00", "11:00"]]}})
    assert saved.status_code == 200 and saved.json["store"]["open_now"] is False
    assert "abre" in saved.json["store"]["status_text"]
    public = client.get("/api/store/minha-loja").json["store"]
    assert public["open_now"] is False and "blocked_reason" not in public
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), uuid.uuid4().hex).status_code == 409
    # Pedido de balcão continua permitido para a própria loja.
    assert send(client, "POST", "/api/admin/orders", payload(pid), uuid.uuid4().hex).status_code == 201


def test_delivery_fee_by_neighborhood(shop):
    client, pid = shop
    store = client.get("/api/admin/store").json["store"]
    zones = [{"name": "Centro", "fee": 300}, {"name": "Jardim Bela Vista", "fee": 800}]
    assert send(client, "PUT", "/api/admin/store", {**store, "delivery_zones": zones + [{"name": "centro", "fee": 1}]}).status_code == 400
    assert send(client, "PUT", "/api/admin/store", {**store, "delivery_zones": zones}).status_code == 200
    assert send(client, "POST", "/api/store/minha-loja/quote", payload(pid)).status_code == 400
    quote = send(client, "POST", "/api/store/minha-loja/quote", payload(pid, zone="Jardim Bela Vista")).json
    assert quote["delivery_fee"] == 800 and quote["zone"] == "Jardim Bela Vista"
    pickup = send(client, "POST", "/api/store/minha-loja/quote", payload(pid, mode="pickup")).json
    assert pickup["delivery_fee"] == 0
    order = make_order(client, pid, zone="Centro")
    assert order["delivery_fee"] == 300 and order["zone"] == "Centro"


def test_store_link_preview_and_qrcode(shop):
    client, _ = shop
    page = client.get("/loja/minha-loja")
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and "<title>Minha Loja • Peça pelo cardápio digital</title>" in html
    assert 'property="og:image"' in html and "/static/og-image.png" in html
    assert client.get("/loja/nao-existe").status_code == 404
    svg = client.get("/api/admin/qrcode")
    assert svg.status_code == 200 and svg.mimetype == "image/svg+xml" and b"<svg" in svg.data
    png = client.get("/api/admin/qrcode?format=png&download=1")
    assert png.data[:8] == b"\x89PNG\r\n\x1a\n" and "attachment" in png.headers["Content-Disposition"]
    assert app_client_without_login(client).get("/api/admin/qrcode").status_code == 401


def app_client_without_login(client):
    return client.application.test_client()


def test_platform_monthly_block_promo_and_notices(app, shop):
    client, pid = shop
    other = app.test_client()
    assert register(other, "outra-loja", "other@example.com").status_code == 201
    assert other.get("/api/platform/monthly").status_code == 403
    app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "owner@example.com"])
    sid = client.get("/api/admin/store").json["store"]["id"]
    order = make_order(client, pid)
    advance(client, order["id"], "preparing", "ready", "delivering", "completed")

    report = client.get("/api/platform/monthly?months=3").json
    assert len(report["months"]) == 3 and report["month"] == datetime.now(ZONE).strftime("%Y-%m")
    current = report["months"][-1]
    assert current["orders"] == 1 and current["gmv"] == order["total"] and current["new_stores"] == 2
    assert report["ranking"][0]["id"] == sid and report["ranking"][0]["gmv"] == order["total"]
    assert client.get("/api/platform/monthly?month=2026-13").status_code == 400

    # Promoção na mensalidade e inadimplência do mês.
    contract = {"commission_bps": 0, "monthly_fee": 9900, "enabled": True, "trial_until": ""}
    assert send(client, "PUT", f"/api/platform/stores/{sid}", {**contract, "promo_fee": 0}).status_code == 400
    assert send(client, "PUT", f"/api/platform/stores/{sid}", {**contract, "promo_fee": 4900, "promo_until": "2999-12-31", "promo_label": "Lançamento"}).status_code == 200
    summary = client.get("/api/platform/summary").json
    mine = next(s for s in summary["stores"] if s["id"] == sid)
    assert mine["effective_fee"] == 4900 and mine["promo_active"] and mine["overdue"] and summary["overdue"] == 4900
    assert send(client, "POST", "/api/platform/ledger", {"store_id": sid, "kind": "receipt", "description": "Mensalidade", "amount": 4900}, uuid.uuid4().hex).status_code == 201
    assert next(s for s in client.get("/api/platform/summary").json["stores"] if s["id"] == sid)["overdue"] is False

    # Bloqueio com motivo e desbloqueio.
    other_id = other.get("/api/admin/store").json["store"]["id"]
    assert send(client, "POST", f"/api/platform/stores/{other_id}/block", {"blocked": True, "reason": ""}).status_code == 400
    assert send(client, "POST", f"/api/platform/stores/{other_id}/block", {"blocked": True, "reason": "Mensalidade atrasada"}).status_code == 200
    assert other.get("/api/admin/notices").json["blocked_reason"] == "Mensalidade atrasada"
    settings = other.get("/api/admin/store").json["store"]
    assert send(other, "PUT", "/api/admin/store", {**settings, "open": True}).status_code == 403
    assert send(client, "POST", f"/api/platform/stores/{other_id}/block", {"blocked": False, "reason": ""}).status_code == 200
    assert other.get("/api/admin/notices").json["blocked_reason"] == ""

    # Avisos e promoções para todos os lojistas.
    assert send(other, "POST", "/api/platform/notices", {"title": "Oi", "body": "Teste", "kind": "info"}).status_code == 403
    created = send(client, "POST", "/api/platform/notices", {"title": "Indique e ganhe", "body": "Indique uma loja e ganhe 1 mês grátis.", "kind": "promo", "expires": "2999-01-01"})
    assert created.status_code == 201
    assert send(client, "POST", "/api/platform/notices", {"title": "Antigo", "body": "Já venceu.", "kind": "info", "expires": "2000-01-01"}).status_code == 201
    notices = other.get("/api/admin/notices").json["notices"]
    assert [n["title"] for n in notices] == ["Indique e ganhe"]
    assert send(client, "PATCH", f"/api/platform/notices/{created.json['id']}", {"active": False}).status_code == 200
    assert other.get("/api/admin/notices").json["notices"] == []


def test_owner_site_is_separate_and_not_indexed(app, shop):
    client, _ = shop
    page = client.get("/admin")
    assert page.status_code == 200 and "noindex" in page.headers["X-Robots-Tag"]
    old = client.get("/plataforma")
    assert old.status_code == 301 and old.headers["Location"].endswith("/admin")
    assert client.get("/api/platform/report").status_code == 403


def test_merchant_and_platform_reports_in_pdf_and_excel(app, shop):
    import io
    from openpyxl import load_workbook
    client, pid = shop
    order = make_order(client, pid)
    advance(client, order["id"], "preparing", "ready", "delivering", "completed")
    send(client, "POST", "/api/admin/expenses", {"description": "Gás de cozinha", "amount": 12000})
    pdf = client.get("/api/admin/report?days=30&format=pdf")
    assert pdf.status_code == 200 and pdf.data[:5] == b"%PDF-" and pdf.mimetype == "application/pdf"
    assert "relatorio-minha-loja-30-dias.pdf" in pdf.headers["Content-Disposition"]
    excel = client.get("/api/admin/report?month=" + datetime.now(ZONE).strftime("%Y-%m") + "&format=xlsx")
    book = load_workbook(io.BytesIO(excel.data))
    assert {"Resumo", "Pedidos", "Despesas", "Produtos mais vendidos"} <= set(book.sheetnames)
    assert book["Pedidos"].max_row == 2 and book["Pedidos"]["I2"].value == order["total"] / 100
    assert client.get("/api/admin/report?days=30&format=doc").status_code == 400
    app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "owner@example.com"])
    platform_pdf = client.get("/api/platform/report?format=pdf")
    assert platform_pdf.status_code == 200 and platform_pdf.data[:5] == b"%PDF-"
    platform_xlsx = load_workbook(io.BytesIO(client.get("/api/platform/report?format=xlsx").data))
    assert platform_xlsx["Últimos 12 meses"].max_row == 13
    assert client.get("/api/platform/report?month=2001-01").status_code == 400


def test_api_keys_rename_rotate_test_and_delete(app, shop):
    client, pid = shop
    created = send(client, "POST", "/api/admin/integrations/keys", {"name": "MotoJá", "scopes": ["orders:read", "deliveries:write"]}).json
    kid, token = created["id"], created["token"]
    assert send(client, "POST", "/api/admin/integrations/test", {"token": token}).json["ok"] is True
    assert send(client, "POST", "/api/admin/integrations/test", {"token": "abc"}).json["ok"] is False
    assert send(client, "PATCH", f"/api/admin/integrations/keys/{kid}", {"name": "MotoJá Conchal"}).status_code == 200
    rotated = send(client, "POST", f"/api/admin/integrations/keys/{kid}/rotate", {}).json["token"]
    partner = app.test_client()
    assert partner.get("/api/v1/store", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert partner.get("/api/v1/store", headers={"Authorization": "Bearer " + rotated}).status_code == 200
    # Uma chave já usada em entrega sai da lista, mas o vínculo do pedido continua.
    order = make_order(client, pid)
    advance(client, order["id"], "preparing", "ready")
    auth = {"Authorization": "Bearer " + rotated}
    assert partner.post(f"/api/v1/deliveries/{order['id']}/claim", json={"external_id": "c-1", "provider": "motoja"}, headers=auth).status_code == 201
    listed = client.get("/api/admin/integrations").json
    assert listed["keys"][0]["name"] == "MotoJá Conchal" and listed["keys"][0]["deliveries"] == 1
    assert send(client, "DELETE", f"/api/admin/integrations/keys/{kid}/permanent", {}).status_code == 200
    after = client.get("/api/admin/integrations").json
    assert after["keys"] == [] and len(after["deliveries"]) == 1
    assert partner.get("/api/v1/store", headers=auth).status_code == 401
    assert send(client, "POST", "/api/admin/integrations/test", {"token": rotated}).json["ok"] is False
    # Chave nunca usada é apagada de vez; outra loja não consegue mexer.
    unused = send(client, "POST", "/api/admin/integrations/keys", {"name": "Teste", "scopes": ["orders:read"]}).json["id"]
    other = app.test_client()
    assert register(other, "outra-loja", "other@example.com").status_code == 201
    assert send(other, "DELETE", f"/api/admin/integrations/keys/{unused}/permanent", {}).status_code == 404
    assert send(client, "DELETE", f"/api/admin/integrations/keys/{unused}/permanent", {}).status_code == 200


def test_option_groups_required_sizes_and_half_and_half(shop):
    client, _ = shop
    category = client.get("/api/admin/products").json["categories"][0]["id"]
    pizza = {"name": "Pizza", "description": "", "price": 0, "category_id": category, "active": True, "unit_cost": 500,
             "extras": [{"id": "borda", "name": "Borda recheada", "price": 800, "unit_cost": 200}],
             "option_groups": [
                 {"id": "tam", "name": "Tamanho", "min": 1, "max": 1, "pricing": "sum",
                  "options": [{"id": "m", "name": "Média", "price": 3000, "unit_cost": 900}, {"id": "g", "name": "Grande", "price": 4000, "unit_cost": 1200}]},
                 {"id": "sab", "name": "Sabores", "min": 1, "max": 2, "pricing": "max",
                  "options": [{"id": "mu", "name": "Mussarela", "price": 0, "unit_cost": 300}, {"id": "ca", "name": "Calabresa", "price": 500, "unit_cost": 400}]}]}
    # Preço zero só é aceito quando há escolha obrigatória.
    assert send(client, "POST", "/api/admin/products", {**pizza, "option_groups": []}).status_code == 400
    bad = {**pizza, "option_groups": [{**pizza["option_groups"][0], "min": 3}]}
    assert send(client, "POST", "/api/admin/products", bad).status_code == 400
    pid = send(client, "POST", "/api/admin/products", pizza).json["id"]
    public = next(p for p in client.get("/api/store/minha-loja").json["products"] if p["id"] == pid)
    assert "unit_cost" not in public["option_groups"][0]["options"][0]

    def quote(ids):
        body = payload(pid, mode="pickup")
        body["items"][0]["option_ids"] = ids
        return send(client, "POST", "/api/store/minha-loja/quote", body)

    missing = quote(["mu"])
    assert missing.status_code == 400 and "Tamanho" in missing.json["error"]
    assert quote(["g", "mu", "ca", "m"]).status_code == 400
    # Grande (40) + meio a meio cobra o mais caro (5) + borda (8) = 53
    assert quote(["g", "mu", "ca", "borda"]).json["subtotal"] == 5300
    assert quote(["m", "mu"]).json["subtotal"] == 3000
    body = payload(pid, mode="pickup")
    body["items"][0]["option_ids"] = ["g", "mu", "ca"]
    assert send(client, "POST", "/api/store/minha-loja/orders", body, uuid.uuid4().hex).status_code == 201
    item = client.get("/api/admin/orders").json["orders"][0]["items"][0]
    assert item["unit_price"] == 4500 and item["unit_cost"] == 500 + 1200 + 400
    assert {x["name"] for x in item["extras"]} == {"Tamanho: Grande", "Sabores: Mussarela", "Sabores: Calabresa"}


def test_scheduled_orders_respect_hours_and_reviews(shop):
    from datetime import timedelta
    client, pid = shop
    store = client.get("/api/admin/store").json["store"]
    later = datetime.now(ZONE) + timedelta(days=2)
    day = str(later.weekday())
    # Loja fora do horário agora, aberta só no dia agendado das 10h às 22h.
    saved = send(client, "PUT", "/api/admin/store", {**store, "auto_hours": True, "hours": {day: [["10:00", "22:00"]]}})
    assert saved.status_code == 200
    good = later.replace(hour=19, minute=30).strftime("%Y-%m-%dT%H:%M")
    bad = later.replace(hour=23, minute=0).strftime("%Y-%m-%dT%H:%M")
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid, scheduled_for=good), uuid.uuid4().hex).status_code == 400
    store = client.get("/api/admin/store").json["store"]
    assert send(client, "PUT", "/api/admin/store", {**store, "allow_scheduling": True}).status_code == 200
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid, scheduled_for=bad), uuid.uuid4().hex).status_code == 400
    too_far = (datetime.now(ZONE) + timedelta(days=9)).strftime("%Y-%m-%dT%H:%M")
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid, scheduled_for=too_far), uuid.uuid4().hex).status_code == 400
    if store_status({**store, "enabled": 1, "open": 1, "auto_hours": 1, "hours": '{"%s": [["10:00", "22:00"]]}' % day})[0] is False:
        assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), uuid.uuid4().hex).status_code == 409
    created = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, scheduled_for=good), uuid.uuid4().hex)
    assert created.status_code == 201
    token = created.json["token"]
    tracked = client.get("/api/track/" + token).json["order"]
    assert tracked["scheduled_for"] and tracked["rating"] is None
    assert send(client, "POST", f"/api/track/{token}/review", {"rating": 5}).status_code == 409
    order = client.get("/api/admin/orders").json["orders"][0]
    advance(client, order["id"], "preparing", "ready", "delivering", "completed")
    assert send(client, "POST", f"/api/track/{token}/review", {"rating": 6}).status_code == 400
    assert send(client, "POST", f"/api/track/{token}/review", {"rating": 4, "comment": "Chegou quentinho"}).status_code == 200
    assert send(client, "POST", f"/api/track/{token}/review", {"rating": 1}).status_code == 409
    reviews = client.get("/api/admin/reviews").json
    assert reviews["average"] == 4.0 and reviews["reviews"][0]["review"] == "Chegou quentinho"


def test_team_roles_are_enforced_by_the_server(app, shop):
    client, pid = shop
    def member(email, role):
        assert send(client, "POST", "/api/admin/team", {"name": "Pessoa " + role, "email": email, "password": "senha-da-equipe-1", "role": role}).status_code == 201
        person = app.test_client()
        assert send(person, "POST", "/api/auth/login", {"email": email, "password": "senha-da-equipe-1"}).status_code == 200
        return person
    assert send(client, "POST", "/api/admin/team", {"name": "X", "email": "owner@example.com", "password": "senha-da-equipe-1", "role": "cashier"}).status_code in (400, 409)
    assert send(client, "POST", "/api/admin/team", {"name": "Xis", "email": "dono2@example.com", "password": "senha-da-equipe-1", "role": "owner"}).status_code == 400
    kitchen, cashier, manager = member("cozinha@example.com", "kitchen"), member("caixa@example.com", "cashier"), member("gerente@example.com", "manager")
    assert kitchen.get("/api/admin/store").json["role"] == "kitchen"
    order = make_order(client, pid)
    # Cozinha: vê e avança pedidos, mas não confirma pagamento, não cancela e não vê vendas.
    assert send(kitchen, "PATCH", f"/api/admin/orders/{order['id']}", {"status": "preparing", "paid": True}).status_code == 200
    assert not client.get("/api/admin/orders").json["orders"][0]["paid"]
    assert send(kitchen, "PATCH", f"/api/admin/orders/{order['id']}", {"status": "cancelled"}).status_code == 403
    for url in ("/api/admin/summary?days=1", "/api/admin/finance", "/api/admin/team", "/api/admin/report?days=7"):
        assert kitchen.get(url).status_code == 403
    assert send(kitchen, "PUT", "/api/admin/store", client.get("/api/admin/store").json["store"]).status_code == 403
    # Caixa: pedidos, balcão e vendas; sem cardápio, financeiro ou integrações.
    assert cashier.get("/api/admin/summary?days=1").status_code == 200
    assert send(cashier, "POST", "/api/admin/orders", payload(pid), uuid.uuid4().hex).status_code == 201
    assert send(cashier, "POST", "/api/admin/products", {"name": "Hack", "price": 1}).status_code == 403
    assert cashier.get("/api/admin/integrations").status_code == 403
    assert send(cashier, "POST", "/api/admin/store/open", {"open": False}).status_code == 200
    # Gerente: quase tudo, menos equipe e integrações.
    assert manager.get("/api/admin/finance").status_code == 200
    assert manager.get("/api/admin/team").status_code == 403
    assert send(manager, "POST", "/api/admin/integrations/keys", {"name": "x", "scopes": ["orders:read"]}).status_code == 403
    # Desativar derruba a sessão na hora; trocar a função também.
    members = client.get("/api/admin/team").json["members"]
    cid = next(m["id"] for m in members if m["email"] == "caixa@example.com")
    assert send(client, "PATCH", f"/api/admin/team/{cid}", {"active": False}).status_code == 200
    assert cashier.get("/api/admin/orders").status_code == 401
    kid = next(m["id"] for m in members if m["email"] == "cozinha@example.com")
    assert send(client, "PATCH", f"/api/admin/team/{kid}", {"role": "cashier"}).status_code == 200
    assert kitchen.get("/api/admin/orders").status_code == 401
    # Outra loja não enxerga nem altera a equipe desta.
    other = app.test_client()
    assert register(other, "outra-loja", "other@example.com").status_code == 201
    assert other.get("/api/admin/team").json["members"] == []
    assert send(other, "PATCH", f"/api/admin/team/{kid}", {"active": False}).status_code == 404


def test_push_subscription_and_new_order_alert(app, shop):
    client, pid = shop
    sent = []

    def fake_deliver(config, subscriptions, message):
        sent.append((len(subscriptions), message))
        return [s["endpoint"] for s in subscriptions if "morto" in s["endpoint"]]

    app.extensions["push_deliver"] = fake_deliver
    worker = client.get("/sw.js")
    assert worker.status_code == 200 and worker.headers["Service-Worker-Allowed"] == "/"
    key = client.get("/api/admin/push/key").json["public_key"]
    assert len(key) == 87 and client.get("/api/admin/push/key").json["public_key"] == key
    sub = {"endpoint": "https://push.example.com/aparelho-1", "keys": {"p256dh": "B" * 87, "auth": "a" * 22}}
    assert send(client, "POST", "/api/admin/push/subscribe", {**sub, "endpoint": "http://inseguro.example.com/x"}).status_code == 400
    assert send(client, "POST", "/api/admin/push/subscribe", sub).status_code == 201
    assert send(client, "POST", "/api/admin/push/subscribe", {**sub, "endpoint": "https://push.example.com/morto"}).status_code == 201
    make_order(client, pid)
    count, message = sent[-1]
    assert count == 2 and message["title"].startswith("Novo pedido #") and "Cliente Teste" in message["body"]
    # O aparelho que não existe mais é removido sozinho.
    assert send(client, "POST", "/api/admin/push/test", {}).json["sent"] == 1
    # Pedido de balcão não dispara aviso para a própria loja.
    before = len(sent)
    assert send(client, "POST", "/api/admin/orders", payload(pid), uuid.uuid4().hex).status_code == 201
    assert len(sent) == before
    assert send(client, "POST", "/api/admin/push/unsubscribe", {"endpoint": sub["endpoint"]}).status_code == 200
    assert send(client, "POST", "/api/admin/push/test", {}).json["sent"] == 0


class FakeMercadoPago:
    def __init__(self):
        self.payments, self.created, self.cancelled = {}, [], []

    def me(self, token):
        from payments import PaymentError
        if token != "APP_USR-valido-123456789012345":
            raise PaymentError("Mercado Pago recusou (401).")
        return {"id": 1, "nickname": "LOJA_TESTE"}

    def create_pix(self, token, payload, idempotency):
        pid = 9000 + len(self.created)
        self.created.append((token, payload, idempotency))
        self.payments[pid] = {"id": pid, "status": "pending", "external_reference": payload["external_reference"],
                              "transaction_amount": payload["transaction_amount"], "fee_details": [{"amount": 0.99}]}
        return {"id": pid, "point_of_interaction": {"transaction_data": {"qr_code": "00020126PIXCOPIAECOLA" + str(pid)}}}

    def get_payment(self, token, pid):
        return self.payments[int(pid)]

    def cancel(self, token, pid):
        self.cancelled.append(int(pid))


def test_pix_online_with_mercado_pago(app, shop):
    client, pid = shop
    mp = FakeMercadoPago()
    app.extensions["mercadopago"] = mp
    store = client.get("/api/admin/store").json["store"]
    assert send(client, "PUT", "/api/admin/store", {**store, "payments": ["pix_online"]}).status_code == 400
    assert send(client, "PUT", "/api/admin/payments/mercadopago", {"access_token": "APP_USR-errado-0000000000000"}).status_code == 400
    connected = send(client, "PUT", "/api/admin/payments/mercadopago", {"access_token": "APP_USR-valido-123456789012345"})
    assert connected.json == {"connected": True, "account": "LOJA_TESTE"}
    store = client.get("/api/admin/store").json["store"]
    assert store["mp_connected"] is True and "mp_token" not in store and "mp_webhook_key" not in store
    assert send(client, "PUT", "/api/admin/store", {**store, "payments": ["pix_online", "cash"]}).status_code == 200
    assert client.get("/api/store/minha-loja").json["store"]["payments"] == ["pix_online", "cash"]
    # Token nunca fica legível no banco.
    from database import connect
    conn = connect(app.config)
    raw = conn.execute("SELECT mp_token,mp_webhook_key FROM stores").fetchone()
    conn.close()
    assert "APP_USR" not in raw[0]
    created = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, payment="pix_online"), uuid.uuid4().hex)
    assert created.status_code == 201
    token = created.json["token"]
    tracked = client.get("/api/track/" + token).json["order"]
    assert tracked["pix"]["code"].startswith("00020126") and tracked["paid"] == 0
    assert mp.created[0][1]["transaction_amount"] == created.json["total"] / 100
    assert client.get(f"/api/track/{token}/pix.svg").mimetype == "image/svg+xml"
    # Webhook com valor diferente não confirma; com o pagamento aprovado e o valor certo, confirma.
    payment_id = int(mp.created[0][1]["external_reference"].split("-")[2]) and 9000
    mp.payments[payment_id]["status"] = "approved"
    mp.payments[payment_id]["transaction_amount"] = 1.0
    hook = app.test_client().post(f"/webhooks/mercadopago/{raw[1]}", json={"data": {"id": str(payment_id)}})
    assert hook.status_code == 200 and not client.get("/api/admin/orders").json["orders"][0]["paid"]
    mp.payments[payment_id]["transaction_amount"] = created.json["total"] / 100
    assert app.test_client().post("/webhooks/mercadopago/chave-falsa-que-nao-existe-123", json={"data": {"id": str(payment_id)}}).status_code == 200
    assert not client.get("/api/admin/orders").json["orders"][0]["paid"]
    app.test_client().post(f"/webhooks/mercadopago/{raw[1]}", json={"data": {"id": str(payment_id)}})
    order = client.get("/api/admin/orders").json["orders"][0]
    assert order["paid"] and order["payment_fee"] == 99
    assert client.get(f"/api/track/{token}/pix.svg").status_code == 404
    # Cancelar um Pix ainda pendente avisa o Mercado Pago.
    second = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, payment="pix_online"), uuid.uuid4().hex).json
    oid = client.get("/api/admin/orders").json["orders"][0]["id"]
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "cancelled"}).status_code == 200
    assert mp.cancelled == [9001]
    assert send(client, "POST", f"/api/track/{second['token']}/pix", {}).status_code == 409
    # Desconectar remove o Pix automático das formas de pagamento.
    assert send(client, "DELETE", "/api/admin/payments/mercadopago", {}).status_code == 200
    assert client.get("/api/store/minha-loja").json["store"]["payments"] == ["cash"]


def test_terms_trial_loyalty_and_first_order_coupon(app, shop):
    client, pid = shop
    fresh = app.test_client()
    body = {"name": "Nova", "email": "nova@example.com", "password": "uma-senha-segura", "store_name": "Nova", "slug": "nova-loja"}
    assert send(fresh, "POST", "/api/auth/register", body).status_code == 400
    assert send(fresh, "POST", "/api/auth/register", {**body, "accept_terms": True}).status_code == 201
    billing = fresh.get("/api/admin/notices").json["billing"]
    assert billing["state"] == "trial" and billing["trial_until"] > datetime.now(timezone.utc).isoformat()
    app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "owner@example.com"])
    nova = next(s for s in client.get("/api/platform/summary").json["stores"] if s["slug"] == "nova-loja")
    assert nova["trial"] and not nova["overdue"]
    # Cupom de primeira compra.
    assert send(client, "POST", "/api/admin/coupons", {"code": "PRIMEIRA", "kind": "fixed", "value": 500, "first_order": True}).status_code == 201
    quote = lambda **v: send(client, "POST", "/api/store/minha-loja/quote", payload(pid, **v))
    assert quote(coupon="PRIMEIRA", phone="").status_code == 400
    assert quote(coupon="PRIMEIRA", phone="(11) 98888-7777").json["discount"] == 500
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid, phone="11988887777", coupon="PRIMEIRA"), uuid.uuid4().hex).status_code == 201
    assert quote(coupon="PRIMEIRA", phone="+55 11 98888-7777").status_code == 400
    # Fidelidade: a cada 2 pedidos concluídos, R$ 7 de desconto no próximo.
    store = client.get("/api/admin/store").json["store"]
    assert send(client, "PUT", "/api/admin/store", {**store, "loyalty_enabled": True, "loyalty_goal": 2, "loyalty_reward": 700}).status_code == 200
    phone = "11977776666"
    for _ in range(2):
        order = make_order(client, pid, phone=phone)
        advance(client, order["id"], "preparing", "ready", "delivering", "completed")
    q = quote(phone="(11) 97777-6666").json
    assert q["loyalty_discount"] == 700 and q["loyalty"]["available"]
    created = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, phone=phone), uuid.uuid4().hex)
    assert created.json["total"] == q["total"]
    again = quote(phone=phone).json
    assert again["loyalty_discount"] == 0 and again["loyalty"]["remaining"] == 2
    assert client.get("/api/track/" + created.json["token"]).json["order"]["loyalty_discount"] == 700


def test_lgpd_anonymize_and_spreadsheet_import(app, shop):
    import io as _io
    client, pid = shop
    make_order(client, pid, phone="11966665555", customer="Maria Privada")
    assert send(client, "POST", "/api/admin/customers/11966665555/anonymize", {}).json["orders"] == 1
    order = client.get("/api/admin/orders").json["orders"][0]
    assert order["customer"] == "Cliente removido" and order["address"] == "" and order["total"] > 0
    assert send(client, "POST", "/api/admin/customers/11966665555/anonymize", {}).status_code == 404
    template = client.get("/api/admin/products/template")
    assert template.status_code == 200
    csv_data = ("Categoria;Produto;Descrição;Preço;Foto (link https);Estoque;Destaque\n"
                "Pizzas;Calabresa;Molho e calabresa;R$ 45,90;;;sim\n"
                "Pizzas;X;curto;10;;;\n"
                "Bebidas;Suco;;abc;;;\n"
                "Bebidas;Água;500 ml;3.5;http://inseguro.com/a.jpg;;\n"
                "Bebidas;Refri;Lata;6;;12;\n").encode("utf-8")
    result = client.post("/api/admin/products/import", data={"file": (_io.BytesIO(csv_data), "cardapio.csv")},
                         headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]}, content_type="multipart/form-data")
    assert result.status_code == 200, result.json
    assert result.json["created"] == 2 and [s["line"] for s in result.json["skipped"]] == [3, 4, 5]
    products = {p["name"]: p for p in client.get("/api/admin/products").json["products"]}
    assert products["Calabresa"]["price"] == 4590 and products["Calabresa"]["featured"] and products["Refri"]["stock"] == 12
    xlsx = client.post("/api/admin/products/import", data={"file": (_io.BytesIO(template.data), "modelo.xlsx")},
                       headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]}, content_type="multipart/form-data")
    assert xlsx.json["created"] == 3


class FakeSubscriptions(FakeMercadoPago):
    def __init__(self):
        super().__init__()
        self.preapprovals, self.charges = {}, {}

    def create_preapproval(self, token, payload):
        pid = "pre%04d" % (len(self.preapprovals) + 1)
        self.preapprovals[pid] = {"id": pid, "status": "pending", "external_reference": payload["external_reference"], "payload": payload}
        self.charges[pid] = []
        return {"id": pid, "status": "pending", "init_point": "https://www.mercadopago.com.br/subscriptions/checkout?preapproval_id=" + pid}

    def get_preapproval(self, token, pid):
        return {k: v for k, v in self.preapprovals[pid].items() if k != "payload"}

    def update_preapproval(self, token, pid, body):
        self.preapprovals[pid].update(body)
        return self.preapprovals[pid]

    def authorized_payments(self, token, pid):
        return {"results": self.charges[pid]}

    def authorized_payment(self, token, payment_id):
        return next({"preapproval_id": p} for p, items in self.charges.items() for c in items if c["id"] == int(payment_id))


def expire_trial(app, slug="minha-loja"):
    from database import connect
    conn = connect(app.config)
    conn.execute("UPDATE stores SET trial_until=? WHERE slug=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), slug))
    conn.close()


def test_subscription_trial_free_month_and_monthly_charge(app, shop):
    client, pid = shop
    mp = FakeSubscriptions()
    app.extensions["mercadopago"] = mp
    # Sem token da plataforma não dá para assinar.
    assert send(client, "POST", "/api/admin/billing/subscribe", {"payer_email": "dona@example.com"}).status_code == 503
    app.config["MP_PLATFORM_ACCESS_TOKEN"] = "APP_USR-plataforma"
    info = client.get("/api/admin/billing").json
    assert info["state"] == "trial" and info["price"] == 5999 and info["free_months"] == 1
    # Acabou o dia grátis: a loja para de receber pedidos.
    expire_trial(app)
    assert client.get("/api/admin/billing").json["state"] == "expired"
    assert client.get("/api/store/minha-loja").json["store"]["open_now"] is False
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), uuid.uuid4().hex).status_code == 409
    started = send(client, "POST", "/api/admin/billing/subscribe", {"payer_email": "dona@example.com"})
    assert started.status_code == 200 and "preapproval_id=pre0001" in started.json["init_point"]
    recurring = mp.preapprovals["pre0001"]["payload"]["auto_recurring"]
    assert recurring["transaction_amount"] == 59.99 and recurring["free_trial"] == {"frequency": 1, "frequency_type": "months"}
    # Cartão cadastrado: assinatura autorizada (1º mês grátis) e a loja volta a vender.
    mp.preapprovals["pre0001"]["status"] = "authorized"
    secret = client.get("/api/platform/billing")
    app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "owner@example.com"])
    hook_url = client.get("/api/platform/billing").json["webhook_url"]
    assert app.test_client().post(hook_url.split("localhost")[-1], json={"type": "subscription_preapproval", "data": {"id": "pre0001"}}).status_code == 200
    assert client.get("/api/admin/billing").json["state"] == "active"
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), uuid.uuid4().hex).status_code == 201
    # Cobrança mensal aprovada vira recebimento na Central do Dono, uma vez só.
    mp.charges["pre0001"].append({"id": 777, "transaction_amount": 59.99, "debit_date": datetime.now(ZONE).date().isoformat(), "payment": {"id": 555, "status": "approved"}})
    for _ in range(2):
        app.test_client().post(hook_url.split("localhost")[-1], json={"type": "subscription_authorized_payment", "data": {"id": "777"}})
        send(client, "POST", "/api/admin/billing/sync", {})
    report = client.get("/api/platform/summary").json
    assert report["received"] == 5999 and len([l for l in report["ledger"] if l["kind"] == "receipt"]) == 1
    # Cancelou: continua liberada até o fim do mês pago e o próximo assinar não ganha outro mês grátis.
    assert send(client, "POST", "/api/admin/billing/cancel", {}).json["state"] == "paid"
    again = send(client, "POST", "/api/admin/billing/subscribe", {"payer_email": "dona@example.com"})
    assert "free_trial" not in mp.preapprovals["pre0002"]["payload"]["auto_recurring"]
    # Webhook com segredo errado é ignorado.
    assert app.test_client().post("/webhooks/mercadopago-assinaturas/errado", json={"data": {"id": "pre0001"}}).status_code == 200
    overview = client.get("/api/platform/billing").json
    assert overview["paying"] == 1 and overview["monthly_recurring"] == 5999


def test_exempt_account_never_pays(app):
    import hashlib
    from billing import EXEMPT_HASHES, billing_state
    EXEMPT_HASHES.add(hashlib.sha256(b"gratis@example.com").hexdigest())
    try:
        client = app.test_client()
        assert register(client, "loja-gratis", "Gratis@Example.com").status_code == 201
        expire_trial(app, "loja-gratis")
        assert client.get("/api/admin/billing").json["state"] == "exempt"
        assert send(client, "POST", "/api/admin/billing/subscribe", {"payer_email": "gratis@example.com"}).status_code == 409
        app.config["BILLING_EXEMPT_EMAILS"] = ""
        other = app.test_client()
        assert register(other, "loja-paga", "paga@example.com").status_code == 201
        expire_trial(app, "loja-paga")
        assert other.get("/api/admin/billing").json["state"] == "expired"
    finally:
        EXEMPT_HASHES.discard(hashlib.sha256(b"gratis@example.com").hexdigest())
    assert billing_state({"billing_exempt": 0, "sub_status": "", "paid_until": "", "trial_until": ""}) == "expired"


class FakeMotoJa:
    def __init__(self):
        self.sent, self.deliveries, self.key = [], {}, "chave-do-motoja-1234567890"

    def send(self, url, key, payload):
        if key != self.key:
            return 401, {"error": "chave_captura_invalida"}
        self.sent.append((url, payload))
        ext = payload["order"]["externalId"]
        self.deliveries[ext] = {"deliveryStatus": "pendente", "deliveryId": "ent-" + ext, "motoboy": ""}
        return 201, {"ok": True, "dispatch": {"deliveryId": "ent-" + ext}}

    def status(self, url, key, external_id):
        if key != self.key:
            return 401, {}
        if external_id not in self.deliveries:
            return 404, {"error": "pedido_nao_encontrado", "active": True, "autoDispatch": True, "saldoDisponivel": 50}
        d = self.deliveries[external_id]
        return 200, {"ok": True, "capturedStatus": "enviado_motoboy", "trackingUrl": "https://motoboy-conchal.onrender.com/entrega/" + d["deliveryId"], **d}


class FakeEvolution:
    ready = True

    def __init__(self):
        self.messages = []

    def create(self, instance):
        return 201, {"qrcode": {"base64": "iVBORw0KGgo="}}

    def connect(self, instance):
        return 200, {}

    def state(self, instance):
        return 200, {"instance": {"state": "open"}}

    def logout(self, instance):
        return 200, {}

    def send_text(self, instance, phone, text):
        self.messages.append((phone, text))
        return 201, {}


MOTOJA_URL = "https://motoboy-conchal.onrender.com/api/integrations/orders/19999990000/seucomercio"


def test_motoja_switch_calls_driver_and_follows_delivery(app, shop):
    client, pid = shop
    moto = FakeMotoJa()
    app.extensions["motoja"] = moto
    assert send(client, "PUT", "/api/admin/motoja", {"url": "https://evil.example.com/api/integrations/orders/19999990000/seucomercio", "key": moto.key}).status_code == 400
    assert send(client, "PUT", "/api/admin/motoja", {"url": MOTOJA_URL, "key": "chave-errada-000000000000"}).status_code == 400
    connected = send(client, "PUT", "/api/admin/motoja", {"url": MOTOJA_URL, "key": moto.key}).json
    assert connected["motoja"]["connected"] and connected["motoja"]["auto"] and connected["warnings"] == []
    store = client.get("/api/admin/store").json["store"]
    assert "motoja_key" not in store and store["motoja_connected"] is True
    assert "motoja_url" not in client.get("/api/store/minha-loja").json["store"]
    # Ao aceitar o pedido de entrega, o motoboy é chamado sozinho com a forma de pagamento.
    order = make_order(client, pid, payment="cash", change_for=10000)
    advance(client, order["id"], "preparing")
    url, payload = moto.sent[-1]
    assert payload["order"]["externalId"].endswith("-" + str(order["number"])) and "Cobrar" in payload["order"]["note"] and "troco" in payload["order"]["note"]
    assert payload["order"]["orderTotal"] == order["total"] / 100
    ext = payload["order"]["externalId"]
    # Motoboy aceita, retira e entrega: o pedido acompanha sozinho.
    moto.deliveries[ext].update(deliveryStatus="retirada", motoboy="João")
    from database import connect
    conn = connect(app.config)
    conn.execute("UPDATE orders SET motoja_checked_at='' WHERE id=?", (order["id"],))
    conn.close()
    current = next(o for o in client.get("/api/admin/orders").json["orders"] if o["id"] == order["id"])
    current = next(o for o in client.get("/api/admin/orders").json["orders"] if o["id"] == order["id"])
    assert current["status"] == "delivering" and current["motoja"]["motoboy"] == "João"
    moto.deliveries[ext]["deliveryStatus"] = "finalizada"
    conn = connect(app.config)
    conn.execute("UPDATE orders SET motoja_checked_at='' WHERE id=?", (order["id"],))
    conn.close()
    client.get("/api/admin/orders")
    assert next(o for o in client.get("/api/admin/orders?status=completed").json["orders"] if o["id"] == order["id"])["status"] == "completed"
    # Chavinha desligada: não chama sozinho, mas dá para chamar na mão. Retirada nunca chama.
    assert send(client, "PATCH", "/api/admin/motoja", {"auto": False}).json["motoja"]["auto"] is False
    second = make_order(client, pid)
    advance(client, second["id"], "preparing")
    assert len(moto.sent) == 1
    manual = send(client, "POST", f"/api/admin/orders/{second['id']}/motoja", {}).json
    assert manual["status"] == "chamado" and len(moto.sent) == 2
    pickup = make_order(client, pid, mode="pickup")
    assert send(client, "POST", f"/api/admin/orders/{pickup['id']}/motoja", {}).status_code == 409
    assert send(client, "DELETE", "/api/admin/motoja", {}).json["motoja"]["connected"] is False


def test_whatsapp_automatic_messages(app, shop):
    client, pid = shop
    evo = FakeEvolution()
    app.extensions["evolution"] = evo
    assert send(client, "PATCH", "/api/admin/whatsapp", {"enabled": True}).status_code == 409
    qr = send(client, "POST", "/api/admin/whatsapp/connect", {}).json
    assert qr["qr"].startswith("data:image/png;base64,")
    assert client.get("/api/admin/whatsapp/status").json["connected"] is True
    assert send(client, "PATCH", "/api/admin/whatsapp", {"enabled": True}).json["whatsapp"]["enabled"] is True
    order = make_order(client, pid, phone="(11) 98888-1111")
    assert evo.messages[-1][0] == "(11) 98888-1111" and "Recebemos seu pedido" in evo.messages[-1][1] and "/pedido/" in evo.messages[-1][1]
    advance(client, order["id"], "preparing", "ready", "delivering", "completed")
    texts = [t for _, t in evo.messages]
    assert any("sendo preparado" in t for t in texts) and any("saiu para entrega" in t for t in texts) and any("concluído" in t for t in texts)
    assert not any("pronto para retirada" in t for t in texts)  # entrega não manda o aviso de retirada
    count = len(evo.messages)
    send(client, "PATCH", "/api/admin/whatsapp", {"enabled": False})
    make_order(client, pid)
    assert len(evo.messages) == count
    assert send(client, "POST", "/api/admin/whatsapp/test", {"phone": "11977776666"}).status_code == 200


def test_monthly_pix_and_owner_one_real_test(app, shop):
    client, pid = shop
    mp = FakeSubscriptions()
    app.extensions["mercadopago"] = mp
    app.config["MP_PLATFORM_ACCESS_TOKEN"] = "APP_USR-plataforma"
    expire_trial(app)
    pix = send(client, "POST", "/api/admin/billing/pix", {}).json
    assert pix["code"].startswith("00020126") and pix["amount"] == 5999
    assert send(client, "POST", "/api/admin/billing/pix", {}).json["code"] == pix["code"]  # mesmo Pix enquanto vale
    assert client.get("/api/admin/billing/pix.svg").mimetype == "image/svg+xml"
    payment = mp.payments[9000]
    assert payment["transaction_amount"] == 59.99
    assert send(client, "POST", "/api/admin/billing/pix/check", {}).json["paid"] is False
    payment["status"] = "approved"
    # Webhook do Mercado Pago confirma e libera a loja por um mês, lançando o recebimento uma vez.
    app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "owner@example.com"])
    hook = client.get("/api/platform/billing").json["webhook_url"].split("localhost")[-1]
    app.test_client().post(hook, json={"type": "payment", "data": {"id": "9000"}})
    billing = client.get("/api/admin/billing").json
    assert billing["state"] == "paid" and billing["paid_until"] > datetime.now(ZONE).date().isoformat()
    assert client.get("/api/platform/summary").json["received"] == 5999
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), uuid.uuid4().hex).status_code == 201
    # Teste de R$ 1,00 do dono.
    other = app.test_client()
    assert register(other, "outra", "x@example.com").status_code == 201
    assert send(other, "POST", "/api/platform/billing/test-pix", {}).status_code == 403
    test = send(client, "POST", "/api/platform/billing/test-pix", {}).json
    assert mp.payments[int(test["id"])]["transaction_amount"] == 1.0
    assert client.get("/api/platform/billing/test-pix.svg").status_code == 200
    assert send(client, "POST", "/api/platform/billing/test-pix/check", {}).json["approved"] is False
    mp.payments[int(test["id"])]["status"] = "approved"
    assert send(client, "POST", "/api/platform/billing/test-pix/check", {}).json["approved"] is True
