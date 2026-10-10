import io
import os
import uuid

import psycopg
from psycopg import sql
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from app import create_app


@pytest.fixture
def app(tmp_path):
    url = os.getenv("TEST_DATABASE_URL", "")
    schema = "test_" + uuid.uuid4().hex
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret-not-for-production",
                       "DATABASE_URL": url, "DATABASE_SCHEMA": schema,
                       "STORAGE_UPLOAD_URL": "", "STORAGE_UPLOAD_TOKEN": "", "STORAGE_PUBLIC_URL": "",
                       "DATABASE_PATH": str(tmp_path / "test.sqlite3"),
                       "UPLOAD_DIR": str(tmp_path / "uploads"), "RATE_LIMIT_ENABLED": False, "PUBLIC_URL": ""})
    try:
        yield application
    finally:
        if url:
            with psycopg.connect(url, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))



def session_token(client):
    return client.get("/api/session").json["csrf"]


def send(client, method, url, value, key=None):
    headers = {"X-CSRF-Token": session_token(client)}
    if key:
        headers["Idempotency-Key"] = key
    return client.open(url, method=method, json=value, headers=headers)


def register(client, slug="minha-loja", email="owner@example.com"):
    return send(client, "POST", "/api/auth/register",
                {"name": "Dona da Loja", "email": email, "password": "uma-senha-segura", "store_name": "Minha Loja", "slug": slug, "accept_terms": True})


@pytest.fixture
def shop(app):
    client = app.test_client()
    assert register(client).status_code == 201
    store = client.get("/api/admin/store").json["store"]
    store.update(open=True, pix_key="pix@example.com", delivery_fee=500)
    assert send(client, "PUT", "/api/admin/store", store).status_code == 200
    category = client.get("/api/admin/products").json["categories"][0]["id"]
    product = send(client, "POST", "/api/admin/products",
                   {"name": "Burger", "description": "Bom demais", "price": 2900, "stock": 5,
                    "category_id": category, "extras": [{"id": "bacon", "name": "Bacon", "price": 500}],
                    "active": True, "featured": True})
    assert product.status_code == 201
    return client, product.json["id"]


def payload(pid, quantity=1, **values):
    return {"customer": "Cliente Teste", "phone": "11999999999", "mode": "delivery",
            "address": "Rua Exemplo, 123, Centro", "payment": "pix", "notes": "",
            "items": [{"product_id": pid, "quantity": quantity, "option_ids": ["bacon"], "notes": "Bem passado"}], **values}


def stock(client):
    return client.get("/api/admin/products").json["products"][0]["stock"]


def test_health_and_private_routes(app):
    client = app.test_client()
    assert client.get("/health").json["status"] == "ok"
    assert client.get("/api/admin/orders").status_code == 401
    assert client.get("/").status_code == 200
    assert "script-src 'self'" in client.get("/").headers["Content-Security-Policy"]


def test_csrf_and_foreign_origin(app):
    client = app.test_client()
    assert client.post("/api/auth/login", json={}).status_code == 403
    token = session_token(client)
    assert client.post("/api/auth/register", json={}, headers={"X-CSRF-Token": token, "Origin": "https://evil.example"}).status_code == 403


def test_registration_password_rules_and_duplicate(app):
    client = app.test_client()
    invalid = {"name": "Dona", "email": "bad", "password": "short", "store_name": "Loja", "slug": "loja"}
    assert send(client, "POST", "/api/auth/register", invalid).status_code == 400
    assert register(client).status_code == 201
    assert register(app.test_client()).status_code == 409


def test_server_prices_idempotency_and_tracking_privacy(shop):
    client, pid = shop
    body = payload(pid, 2, total=1)
    first = send(client, "POST", "/api/store/minha-loja/orders", body, "unique-request-key-123")
    assert first.status_code == 201 and first.json["total"] == 7300
    assert stock(client) == 3
    retry = send(client, "POST", "/api/store/minha-loja/orders", body, "unique-request-key-123")
    assert retry.status_code == 200 and retry.json == first.json
    assert stock(client) == 3
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), "unique-request-key-123").status_code == 409
    public = client.get("/api/track/" + first.json["token"]).json["order"]
    assert public["total"] == 7300
    assert not ({"phone", "address", "customer", "tracking_token", "tracking_hash"} & set(public))
    assert client.get("/api/track/not-a-real-token").status_code == 404


def test_quote_and_coupon_consumed_only_once(shop):
    client, pid = shop
    assert send(client, "POST", "/api/admin/coupons", {"code": "BOASVINDAS", "kind": "percent", "value": 10, "max_uses": 1}).status_code == 201
    body = payload(pid, coupon="BOASVINDAS")
    quote = send(client, "POST", "/api/store/minha-loja/quote", body)
    assert quote.status_code == 200 and quote.json["total"] == 3560
    assert stock(client) == 5
    first = send(client, "POST", "/api/store/minha-loja/orders", body, "coupon-request-111")
    assert first.status_code == 201 and first.json["total"] == 3560
    assert send(client, "POST", "/api/store/minha-loja/orders", body, "coupon-request-222").status_code == 400
    assert stock(client) == 4


def test_duplicate_product_lines_cannot_oversell(shop):
    client, pid = shop
    body = payload(pid, 3)
    body["items"].append(body["items"][0].copy())
    assert send(client, "POST", "/api/store/minha-loja/orders", body, "oversell-request-1").status_code == 409
    assert stock(client) == 5
    assert not client.get("/api/admin/orders").json["orders"]


def test_bad_extras_closed_store_minimum_and_cash(shop):
    client, pid = shop
    body = payload(pid)
    body["items"][0]["option_ids"] = ["unknown"]
    assert send(client, "POST", "/api/store/minha-loja/orders", body, "invalid-extra-key-1").status_code == 400
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid, payment="cash", change_for=10), "cash-invalid-key-1").status_code == 400
    assert stock(client) == 5
    store = client.get("/api/admin/store").json["store"]
    store["minimum_order"] = 10000
    send(client, "PUT", "/api/admin/store", store)
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), "minimum-order-key-1").status_code == 400
    store["open"] = False
    send(client, "PUT", "/api/admin/store", store)
    assert send(client, "POST", "/api/store/minha-loja/orders", payload(pid), "closed-store-key-1").status_code == 409


def test_tenant_isolation_in_every_owner_entity(app, shop):
    first, pid = shop
    first_category = first.get("/api/admin/products").json["categories"][0]["id"]
    send(first, "POST", "/api/store/minha-loja/orders", payload(pid), "tenant-order-key-1")
    order_id = first.get("/api/admin/orders").json["orders"][0]["id"]
    driver_id = send(first, "POST", "/api/admin/drivers", {"name": "Entregador"}).json["id"]
    coupon_id = send(first, "POST", "/api/admin/coupons", {"code": "PRIMEIRO", "kind": "fixed", "value": 100}).json["id"]
    expense_id = send(first, "POST", "/api/admin/expenses", {"description": "Compra", "amount": 100}).json["id"]
    second = app.test_client()
    assert register(second, "outra-loja", "other@example.com").status_code == 201
    assert second.get("/api/admin/products").json["products"] == []
    assert second.get("/api/admin/orders").json["orders"] == []
    assert send(second, "DELETE", f"/api/admin/products/{pid}", {}).status_code == 404
    assert send(second, "DELETE", f"/api/admin/categories/{first_category}", {}).status_code == 404
    assert send(second, "PATCH", f"/api/admin/orders/{order_id}", {"paid": True}).status_code == 404
    assert send(second, "PUT", f"/api/admin/drivers/{driver_id}", {"name": "Hack"}).status_code == 404
    assert send(second, "PATCH", f"/api/admin/coupons/{coupon_id}", {"active": False}).status_code == 404
    assert send(second, "DELETE", f"/api/admin/expenses/{expense_id}", {}).status_code == 404
    assert send(second, "POST", "/api/admin/products", {"name": "Teste", "price": 100, "category_id": first_category}).status_code == 404


def test_transitions_cancel_restock_exactly_once(shop):
    client, pid = shop
    send(client, "POST", "/api/store/minha-loja/orders", payload(pid), "cancel-test-key-11")
    oid = client.get("/api/admin/orders").json["orders"][0]["id"]
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "completed"}).status_code == 409
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "preparing"}).status_code == 200
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "cancelled"}).status_code == 200
    assert stock(client) == 5
    send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "cancelled"})
    assert stock(client) == 5
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "new"}).status_code == 409


def test_pickup_payment_summary_and_csv(shop):
    client, pid = shop
    result = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, mode="pickup", address="", payment="card"), "pickup-test-key-11")
    assert result.status_code == 201 and result.json["total"] == 3400
    oid = client.get("/api/admin/orders").json["orders"][0]["id"]
    for status in ("preparing", "ready"):
        assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": status}).status_code == 200
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "delivering"}).status_code == 409
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "completed", "paid": True}).status_code == 200
    send(client, "POST", "/api/admin/expenses", {"description": "Embalagens", "amount": 400})
    summary = client.get("/api/admin/summary?days=1").json
    assert summary["revenue"] == 3400 and summary["received"] == 3400 and summary["balance"] == 3000
    assert client.get("/api/admin/export").status_code == 200
    assert "Pedido;Data UTC" in client.get("/api/admin/export").get_data(as_text=True)


def test_password_change_revokes_existing_session(app, shop):
    client, _ = shop
    old = app.test_client()
    assert send(old, "POST", "/api/auth/login", {"email": "owner@example.com", "password": "uma-senha-segura"}).status_code == 200
    assert send(client, "PUT", "/api/auth/password", {"current_password": "uma-senha-segura", "new_password": "nova-senha-segura"}).status_code == 200
    assert old.get("/api/admin/store").status_code == 401
    assert client.get("/api/admin/store").status_code == 200


def test_upload_reencoded_and_invalid_file_rejected(shop):
    client, _ = shop
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), "green").save(buffer, "PNG")
    buffer.seek(0)
    uploaded = client.post("/api/admin/upload", data={"file": (buffer, "test.png")}, headers={"X-CSRF-Token": session_token(client)})
    assert uploaded.status_code == 201 and uploaded.json["url"].endswith(".webp")
    assert client.get(uploaded.json["url"]).mimetype == "image/webp"
    invalid = client.post("/api/admin/upload", data={"file": (io.BytesIO(b"<script>bad</script>"), "evil.png")}, headers={"X-CSRF-Token": session_token(client)})
    assert invalid.status_code == 400 and client.get("/media/not-valid.webp").status_code == 404


def test_parallel_orders_reserve_last_stock_atomically(app, shop):
    client, pid = shop
    product = client.get("/api/admin/products").json["products"][0]
    product["stock"] = 1
    assert send(client, "PUT", f"/api/admin/products/{pid}", product).status_code == 200
    def place(index):
        customer = app.test_client()
        return send(customer, "POST", "/api/store/minha-loja/orders", payload(pid), f"concurrent-request-{index}").status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(place, range(2)))
    assert statuses == [201, 409] and stock(client) == 0


def test_rate_limiter(app):
    app.config["RATE_LIMIT_ENABLED"] = True
    client = app.test_client()
    # Por conta: 10 tentativas erradas bloqueiam aquele e-mail, mesmo vindo de vários IPs.
    for _ in range(10):
        assert send(client, "POST", "/api/auth/login", {"email": "none@example.com", "password": "wrong"}).status_code == 401
    assert send(client, "POST", "/api/auth/login", {"email": "none@example.com", "password": "wrong"}).status_code == 429
    # Por IP: depois de 15 tentativas no total, outros e-mails também são bloqueados.
    for i in range(4):
        assert send(client, "POST", "/api/auth/login", {"email": f"other{i}@example.com", "password": "wrong"}).status_code == 401
    assert send(client, "POST", "/api/auth/login", {"email": "last@example.com", "password": "wrong"}).status_code == 429


def test_price_change_requires_new_confirmation(shop):
    client, pid = shop
    body = payload(pid, expected_total=3900)
    product = client.get("/api/admin/products").json["products"][0]
    product["price"] = 3000
    assert send(client, "PUT", f"/api/admin/products/{pid}", product).status_code == 200
    rejected = send(client, "POST", "/api/store/minha-loja/orders", body, "changed-price-key-1")
    assert rejected.status_code == 409 and stock(client) == 5
    quote = send(client, "POST", "/api/store/minha-loja/quote", body)
    assert quote.json["total"] == 4000
    body["expected_total"] = 4000
    assert send(client, "POST", "/api/store/minha-loja/orders", body, "changed-price-key-2").status_code == 201


def test_paused_assigned_driver_does_not_block_order_progress(shop):
    client, pid = shop
    send(client, "POST", "/api/store/minha-loja/orders", payload(pid), "driver-status-key-1")
    oid = client.get("/api/admin/orders").json["orders"][0]["id"]
    driver = send(client, "POST", "/api/admin/drivers", {"name": "Entregador Teste"}).json["id"]
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"driver_id": driver}).status_code == 200
    assert send(client, "PUT", f"/api/admin/drivers/{driver}", {"name": "Entregador Teste", "active": False}).status_code == 200
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": "preparing"}).status_code == 200
    assert send(client, "PATCH", f"/api/admin/orders/{oid}", {"status": {"invalid": True}}).status_code == 400
    second = send(client, "POST", "/api/store/minha-loja/orders", payload(pid), "driver-status-key-2")
    assert second.status_code == 201
    other = client.get("/api/admin/orders").json["orders"][0]["id"]
    assert send(client, "PATCH", f"/api/admin/orders/{other}", {"driver_id": driver}).status_code == 400
