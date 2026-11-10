"""Pix e pagamento por fora: libera até a véspera do mesmo dia do mês seguinte e avisa antes."""
import uuid
from datetime import date, datetime, timedelta, timezone

from billing import ZONE, add_month, days_until_block, month_paid_until
from database import connect
from tests.test_api import app, shop, register, send  # noqa: F401


def test_month_paid_until_blocks_on_same_day_next_month():
    assert month_paid_until("", date(2026, 11, 9)) == "2026-12-08"
    assert month_paid_until("2026-10-01", date(2026, 11, 9)) == "2026-12-08"
    # Pagou adiantado: o novo mês começa depois dos dias que ainda restavam.
    assert month_paid_until("2026-12-08", date(2026, 12, 5)) == "2027-01-08"
    assert month_paid_until("", date(2027, 1, 31)) == "2027-02-27"


def test_days_until_block_warns_two_days_and_last_day():
    store = {"billing_exempt": 0, "sub_status": "", "trial_until": "", "paid_until": "2026-12-08"}
    at = lambda d: datetime(2026, 12, d, 15, tzinfo=ZONE).astimezone(timezone.utc)
    assert days_until_block(store, at(6)) == 3
    assert days_until_block(store, at(7)) == 2
    assert days_until_block(store, at(8)) == 1
    assert days_until_block(store, at(9)) is None  # bloqueada
    assert days_until_block({**store, "billing_exempt": 1}, at(7)) is None


def test_manual_receipt_frees_store_until_eve_of_next_month(app, shop):  # noqa: F811
    client, _ = shop
    app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "owner@example.com"])
    conn = connect(app.config)
    conn.execute("UPDATE stores SET trial_until='',paid_until=''")
    conn.close()
    assert client.get("/api/admin/billing").json["state"] == "expired"
    sid = client.get("/api/platform/summary").json["stores"][0]["id"]
    body = {"store_id": sid, "kind": "receipt", "description": "Mensalidade paga por Pix por fora", "amount": 6000}
    assert send(client, "POST", "/api/platform/ledger", body, uuid.uuid4().hex).status_code == 201
    billing = client.get("/api/admin/billing").json
    today = datetime.now(ZONE).date()
    assert billing["state"] == "paid"
    assert billing["paid_until"] == (add_month(today) - timedelta(days=1)).isoformat()
    assert billing["days_left"] == (add_month(today) - today).days
    conn = connect(app.config)
    conn.execute("UPDATE stores SET paid_until=?", ((today + timedelta(days=1)).isoformat(),))
    conn.close()
    assert client.get("/api/admin/billing").json["days_left"] == 2
