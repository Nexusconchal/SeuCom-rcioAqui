"""Mês grátis contado da criação da conta; assinar não dá mês extra."""
from datetime import datetime, timedelta, timezone

from billing import add_month, billing_state, free_days_left, free_month_migration
from database import connect
from tests.test_api import app, register, send, shop  # noqa: F401  (fixtures)
from tests.test_features import FakeSubscriptions


def test_new_store_gets_one_month_from_signup(app, shop):
    client, _ = shop
    info = client.get("/api/admin/billing").json
    until = datetime.fromisoformat(info["trial_until"])
    assert info["state"] == "trial" and 27 <= (until - datetime.now(timezone.utc)).days <= 31
    assert info["first_charge"] == info["trial_until"]


def test_subscribing_on_day_25_keeps_only_the_remaining_days(app, shop):
    client, _ = shop
    mp = FakeSubscriptions()
    app.extensions["mercadopago"] = mp
    app.config["MP_PLATFORM_ACCESS_TOKEN"] = "APP_USR-plataforma"
    conn = connect(app.config)
    conn.execute("UPDATE stores SET trial_until=? WHERE slug='minha-loja'",
                 ((datetime.now(timezone.utc) + timedelta(days=5, hours=-1)).isoformat(timespec="seconds"),))
    conn.close()
    assert send(client, "POST", "/api/admin/billing/subscribe", {"payer_email": "dona@example.com"}).status_code == 200
    recurring = mp.preapprovals["pre0001"]["payload"]["auto_recurring"]
    assert recurring["free_trial"] == {"frequency": 5, "frequency_type": "days"}


def test_free_days_and_grace_after_trial():
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    assert free_days_left((now + timedelta(days=4, hours=2)).isoformat(), now) == 5
    assert free_days_left((now - timedelta(minutes=1)).isoformat(), now) == 0 and free_days_left("", now) == 0
    ended = (now - timedelta(days=1)).isoformat()
    store = {"billing_exempt": 0, "sub_status": "authorized", "paid_until": "", "trial_until": ended}
    assert billing_state(store, now) == "active"
    assert billing_state({**store, "trial_until": (now - timedelta(days=4)).isoformat()}, now) == "expired"
    assert billing_state({**store, "sub_status": ""}, now) == "expired"


def test_migration_counts_free_month_from_account_creation(app):
    client = app.test_client()
    assert register(client).status_code == 201
    created = datetime.now(timezone.utc) - timedelta(days=21)
    conn = connect(app.config)
    conn.execute("UPDATE stores SET created_at=?,trial_until=? WHERE slug='minha-loja'",
                 (created.isoformat(timespec="seconds"), (created + timedelta(days=1)).isoformat(timespec="seconds")))
    conn.execute("DELETE FROM platform_settings WHERE key='billing_free_month_v2'")
    free_month_migration(conn)
    trial = conn.execute("SELECT trial_until FROM stores WHERE slug='minha-loja'").fetchone()[0]
    conn.close()
    assert trial == add_month(created.replace(microsecond=0)).isoformat(timespec="seconds")
    assert client.get("/api/admin/billing").json["state"] == "trial"


def test_pix_paid_during_free_month_starts_after_it(app, shop):
    client, _ = shop
    mp = FakeSubscriptions()
    app.extensions["mercadopago"] = mp
    app.config["MP_PLATFORM_ACCESS_TOKEN"] = "APP_USR-plataforma"
    trial = client.get("/api/admin/billing").json["trial_until"]
    assert send(client, "POST", "/api/admin/billing/pix", {}).status_code == 200
    mp.payments[9000].update(status="approved", date_approved=datetime.now(timezone.utc).isoformat())
    assert send(client, "POST", "/api/admin/billing/pix/check", {}).json["paid"]
    conn = connect(app.config)
    paid_until = conn.execute("SELECT paid_until FROM stores WHERE slug='minha-loja'").fetchone()[0]
    conn.close()
    from billing import ZONE
    assert paid_until == (add_month(datetime.fromisoformat(trial).astimezone(ZONE).date()) - timedelta(days=1)).isoformat()
