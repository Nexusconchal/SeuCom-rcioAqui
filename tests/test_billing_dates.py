"""Account creation, subscription confirmation and real approval instants stay distinct."""
import uuid

from database import connect
from tests.test_api import app, shop, register, send
from tests.test_features import FakeSubscriptions


def summary(app, client):
    app.test_cli_runner().invoke(args=['grant-platform-admin', '--email', 'owner@example.com'])
    return client.get('/api/platform/summary?days=1').json['stores'][0]


def test_account_creation_and_manual_plan_records(app, shop):
    client, _ = shop
    conn = connect(app.config)
    conn.execute("UPDATE users SET created_at='2025-12-31T23:59:58+00:00'")
    conn.execute("UPDATE stores SET created_at='2026-01-02T01:02:03+00:00'")
    conn.close()
    item = summary(app, client)
    sid = item['id']
    assert item['account_created_at'] == '2025-12-31T23:59:58+00:00'
    assert item['created_at'] != item['account_created_at']
    assert not item['subscribed_at'] and item['last_plan_paid_at'] is None
    partial = {'store_id': sid, 'kind': 'receipt', 'description': 'Recebimento parcial', 'amount': 100}
    assert send(client, 'POST', '/api/platform/ledger', partial, uuid.uuid4().hex).status_code == 201
    assert not summary(app, client)['last_plan_payment_recorded_at']
    full = {**partial, 'description': 'Mensalidade manual', 'amount': 5999}
    key = uuid.uuid4().hex
    recorded = send(client, 'POST', '/api/platform/ledger', full, key)
    assert recorded.status_code == 201
    item = summary(app, client)
    confirmed = item['subscribed_at']
    assert confirmed and item['last_plan_payment_recorded_at']
    assert item['last_plan_paid_at'] == ''  # manual entry is not a bank approval instant
    assert send(client, 'POST', '/api/platform/ledger', full, key).json['duplicate']
    assert summary(app, client)['subscribed_at'] == confirmed
    assert send(client, 'DELETE', '/api/platform/ledger/' + str(recorded.json['id']), {}).status_code == 200
    assert summary(app, client)['last_plan_payment_recorded_at'] is None
    other = app.test_client()
    assert register(other, 'outra', 'another@example.com').status_code == 201
    assert other.get('/api/platform/summary').status_code == 403
    assert app.test_client().get('/api/platform/summary').status_code == 401


def test_card_approval_uses_payment_instant_not_invoice_date(app, shop):
    client, _ = shop
    mp = FakeSubscriptions()
    app.extensions['mercadopago'] = mp
    app.config['MP_PLATFORM_ACCESS_TOKEN'] = 'test-platform-token'
    assert send(client, 'POST', '/api/admin/billing/subscribe', {'payer_email': 'owner@example.com'}).status_code == 200
    assert not summary(app, client)['subscribed_at']
    mp.preapprovals['pre0001']['status'] = 'authorized'
    assert send(client, 'POST', '/api/admin/billing/sync', {}).status_code == 200
    confirmed = summary(app, client)['subscribed_at']
    assert confirmed and summary(app, client)['last_plan_paid_at'] is None  # free trial isn't a payment
    mp.payments[555] = {'id': 555, 'status': 'approved', 'date_approved': '2026-01-01T00:15:23Z'}
    mp.charges['pre0001'].append({'id': 777, 'transaction_amount': 59.99, 'debit_date': '2025-12-30',
                                'payment': {'id': 555, 'status': 'approved'}})
    for _ in range(2):
        assert send(client, 'POST', '/api/admin/billing/sync', {}).status_code == 200
    item = summary(app, client)
    assert item['subscribed_at'] == confirmed
    assert item['last_plan_paid_at'] == '2026-01-01T00:15:23+00:00'
    conn = connect(app.config)
    assert conn.execute("SELECT COUNT(*) FROM platform_ledger WHERE is_subscription=1").fetchone()[0] == 1
    conn.close()
    assert send(client, 'POST', '/api/admin/billing/cancel', {}).status_code == 200
    assert send(client, 'POST', '/api/admin/billing/subscribe', {'payer_email': 'owner@example.com'}).status_code == 200
    mp.preapprovals['pre0002']['status'] = 'authorized'
    assert send(client, 'POST', '/api/admin/billing/sync', {}).status_code == 200
    assert summary(app, client)['subscribed_at'] == confirmed


def test_pix_keeps_actual_approval_and_unknown_time_is_not_invented(app, shop):
    from billing import billing_timestamp
    client, _ = shop
    mp = FakeSubscriptions()
    app.extensions['mercadopago'] = mp
    app.config['MP_PLATFORM_ACCESS_TOKEN'] = 'test-platform-token'
    assert send(client, 'POST', '/api/admin/billing/pix', {}).status_code == 200
    mp.payments[9000].update(status='approved', date_approved='2026-10-15T08:25:42-03:00')
    assert send(client, 'POST', '/api/admin/billing/pix/check', {}).json['paid']
    item = summary(app, client)
    assert item['last_plan_paid_at'] == '2026-10-15T11:25:42+00:00'
    assert item['subscribed_at'] and item['last_plan_payment_recorded_at']
    for unknown in ('', None, '2026-10-15', '2026-10-15T08:25:42', 'invalid'):
        assert billing_timestamp(unknown) == ''
    assert billing_timestamp('2026-01-01T00:15:23Z') == '2026-01-01T00:15:23+00:00'
