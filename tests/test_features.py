import uuid
from datetime import datetime

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
    contract = {"commission_bps": 0, "monthly_fee": 9900, "enabled": True}
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
