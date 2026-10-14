import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from database import connect, initialize
from tests.test_api import app, shop, payload, register, send
from tests.test_business import advance


def sql(client, query, params=()):
    conn = connect(client.application.config)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def ingredient(client, stock=1000, cost=3000):
    result = send(client, 'POST', '/api/admin/ingredients', {'name': 'Carne bovina', 'unit': 'kg', 'stock': stock, 'low_stock': 200, 'unit_cost': cost})
    assert result.status_code == 201, result.json
    return result.json['id']


def recipe(client, pid, iid, quantity=150):
    result = send(client, 'PUT', f'/api/admin/products/{pid}/recipe', {'ingredients': [{'ingredient_id': iid, 'quantity': quantity}]})
    assert result.status_code == 200, result.json


def balance(client, iid):
    return next(i['stock'] for i in client.get('/api/admin/ingredients').json['ingredients'] if i['id'] == iid)


def test_recipe_reserves_snapshots_cost_and_restores_original_recipe_once(shop):
    client, pid = shop
    iid = ingredient(client)
    recipe(client, pid, iid)
    body = payload(pid, items=[{'product_id': pid, 'quantity': 2, 'option_ids': []}])
    key = uuid.uuid4().hex
    created = send(client, 'POST', '/api/store/minha-loja/orders', body, key)
    assert created.status_code == 201
    assert balance(client, iid) == 700
    order = client.get('/api/admin/orders').json['orders'][0]
    assert order['items'][0]['unit_cost'] == 450
    assert send(client, 'POST', '/api/store/minha-loja/orders', body, key).status_code == 200
    assert balance(client, iid) == 700
    # Changing cost/recipe cannot change the original reservation or historical cost.
    recipe(client, pid, iid, 250)
    send(client, 'PATCH', f'/api/admin/ingredients/{iid}', {'unit_cost': 4000})
    assert client.get('/api/admin/orders').json['orders'][0]['items'][0]['unit_cost'] == 450
    assert send(client, 'PATCH', f"/api/admin/orders/{order['id']}", {'status': 'cancelled'}).status_code == 200
    assert balance(client, iid) == 1000
    assert send(client, 'PATCH', f"/api/admin/orders/{order['id']}", {'status': 'cancelled'}).status_code == 200
    assert balance(client, iid) == 1000
    assert len(client.get('/api/admin/ingredients').json['movements']) == 3


def test_recipe_shared_insufficient_stock_rolls_back_product_order_and_coupon(shop):
    client, pid = shop
    iid = ingredient(client, stock=200)
    recipe(client, pid, iid)
    body = payload(pid, items=[{'product_id': pid, 'quantity': 1}, {'product_id': pid, 'quantity': 1}])
    assert send(client, 'POST', '/api/store/minha-loja/quote', body).status_code == 409
    assert send(client, 'POST', '/api/store/minha-loja/orders', body, uuid.uuid4().hex).status_code == 409
    assert balance(client, iid) == 200
    assert client.get('/api/admin/products').json['products'][0]['stock'] == 5
    assert client.get('/api/admin/orders').json['orders'] == []
    public = client.get('/api/store/minha-loja').json['products'][0]
    assert public['stock'] == 1 and 'unit_cost' not in public
    assert send(client, 'PATCH', f'/api/admin/ingredients/{iid}', {'active': False}).status_code == 200
    assert client.get('/api/store/minha-loja').json['products'][0]['stock'] == 0
    assert send(client, 'POST', '/api/store/minha-loja/orders', payload(pid), uuid.uuid4().hex).status_code == 409


def test_ingredient_reservation_is_atomic_under_concurrent_orders(app, shop):
    client, pid = shop
    iid = ingredient(client, stock=150)
    recipe(client, pid, iid)
    def buy(_):
        return send(app.test_client(), 'POST', '/api/store/minha-loja/orders', payload(pid), uuid.uuid4().hex).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(buy, range(2)))
    assert sorted(results) == [201, 409]
    assert balance(client, iid) == 0


def test_recipe_cost_missing_and_quantity_validation_isolation(app, shop):
    client, pid = shop
    iid = ingredient(client, cost=None)
    recipe(client, pid, iid)
    bad = [{'ingredient_id': iid, 'quantity': 0}, {'ingredient_id': iid, 'quantity': True}, {'ingredient_id': iid, 'quantity': .15}]
    for line in bad:
        assert send(client, 'PUT', f'/api/admin/products/{pid}/recipe', {'ingredients': [line]}).status_code == 400
    assert send(client, 'PUT', f'/api/admin/products/{pid}/recipe', {'ingredients': [{'ingredient_id': iid, 'quantity': 1}] * 2}).status_code == 400
    assert send(client, 'POST', f'/api/admin/ingredients/{iid}/adjust', {'delta': -1001, 'reason': 'Perda'}).status_code == 400
    assert balance(client, iid) == 1000
    other = app.test_client()
    register(other, 'outra-loja', 'other@example.com')
    assert send(other, 'PATCH', f'/api/admin/ingredients/{iid}', {'name': 'Roubo'}).status_code == 404
    assert send(other, 'PUT', f'/api/admin/products/{pid}/recipe', {'ingredients': []}).status_code == 404
    assert other.get('/api/admin/ingredients').json['ingredients'] == []
    assert send(client, 'POST', '/api/store/minha-loja/orders', payload(pid), uuid.uuid4().hex).status_code == 201
    assert client.get('/api/admin/orders').json['orders'][0]['items'][0]['unit_cost'] is None
    # Existing data survives running the additive migration again.
    initialize(app.config)
    assert balance(client, iid) == 850


def capture(client, pid, consent=True):
    token = send(client, 'POST', '/api/store/minha-loja/shopping', {'event': 'visit'}).json['token']
    body = {'event': 'checkout', 'token': token, 'items': payload(pid)['items'], 'recovery_consent': consent,
        'customer': 'Cliente Teste', 'phone': '(11) 99999-9999'}
    result = send(client, 'POST', '/api/store/minha-loja/shopping', body)
    assert result.status_code == 200, result.json
    return token


def age_session(client, token, days=0, minutes=31):
    import hashlib
    stamp = (datetime.now(timezone.utc) - timedelta(days=days, minutes=minutes)).isoformat(timespec='seconds')
    sql(client, 'UPDATE shopping_sessions SET updated_at=? WHERE token_hash=?', (stamp, hashlib.sha256(token.encode()).hexdigest()))


def link_from(message, key):
    for part in message.split():
        if part.startswith('http') and key in part:
            return parse_qs(urlparse(part).query)[key][0]
    raise AssertionError(message)


def test_recovery_consent_private_payload_signed_expiry_and_conversion(app, shop):
    client, pid = shop
    token = capture(client, pid)
    assert client.get('/api/admin/marketing').json['abandoned'] == []
    age_session(client, token)
    summary = client.get('/api/admin/marketing').json
    assert summary['funnel'] == {'visits': 1, 'carts': 1, 'checkouts': 1, 'orders': 0, 'conversion': 0.0}
    lead = summary['abandoned'][0]
    recovery = link_from(lead['message'], 'recuperar')
    url = '/api/store/minha-loja/recover/' + recovery
    result = app.test_client().get(url)
    assert result.status_code == 200
    assert set(result.json) == {'items'} and 'phone' not in result.get_data(as_text=True)
    assert client.get(url + 'x').status_code == 404
    other = app.test_client()
    register(other, 'outra-loja', 'other@example.com')
    assert other.get('/api/store/outra-loja/recover/' + recovery).status_code == 404
    assert other.get('/api/admin/marketing').json['abandoned'] == []
    created = send(client, 'POST', '/api/store/minha-loja/orders', payload(pid, shopping_token=token), uuid.uuid4().hex)
    assert created.status_code == 201
    assert client.get(url).status_code == 404
    summary = client.get('/api/admin/marketing').json
    assert summary['funnel']['orders'] == 1 and summary['funnel']['conversion'] == 100.0
    assert summary['abandoned'] == []


def test_no_recovery_contacts_without_consent_and_public_optout(shop):
    client, pid = shop
    token = capture(client, pid, consent=False)
    age_session(client, token)
    assert client.get('/api/admin/marketing').json['abandoned'] == []
    assert sql(client, 'SELECT customer,phone FROM shopping_sessions')[0]['phone'] == ''
    token = capture(client, pid)
    age_session(client, token)
    lead = client.get('/api/admin/marketing').json['abandoned'][0]
    key = link_from(lead['message'], 'cancelar_recuperacao')
    assert send(client, 'POST', '/api/store/minha-loja/recovery-unsubscribe/' + key, {}).status_code == 200
    assert client.get('/api/admin/marketing').json['abandoned'] == []
    assert all(not row['phone'] for row in sql(client, 'SELECT phone FROM shopping_sessions'))


def test_recovery_in_new_session_closes_original_without_double_counting(shop):
    client, pid = shop
    original = capture(client, pid)
    age_session(client, original)
    lead = client.get('/api/admin/marketing').json['abandoned'][0]
    recovery = link_from(lead['message'], 'recuperar')
    new_session = capture(client, pid, consent=False)
    result = send(client, 'POST', '/api/store/minha-loja/orders', payload(pid, shopping_token=new_session, recovery_token=recovery), uuid.uuid4().hex)
    assert result.status_code == 201
    assert client.get('/api/store/minha-loja/recover/' + recovery).status_code == 404
    funnel = client.get('/api/admin/marketing').json['funnel']
    assert funnel['visits'] == 2 and funnel['orders'] == 1 and funnel['conversion'] == 50.0


def test_crm_completed_orders_optin_normalization_preview_and_unsubscribe(shop):
    client, pid = shop
    first = send(client, 'POST', '/api/store/minha-loja/orders', payload(pid, phone='(11) 99999-9999', marketing_consent=True), uuid.uuid4().hex)
    oid = client.get('/api/admin/orders').json['orders'][0]['id']
    advance(client, oid, 'preparing', 'ready', 'delivering', 'completed')
    second = send(client, 'POST', '/api/store/minha-loja/orders', payload(pid, phone='+55 11 99999-9999'), uuid.uuid4().hex)
    assert first.status_code == second.status_code == 201
    oid = client.get('/api/admin/orders').json['orders'][0]['id']
    advance(client, oid, 'preparing', 'ready', 'delivering', 'completed')
    customers = client.get('/api/admin/marketing').json['customers']
    assert len(customers) == 1 and customers[0]['orders'] == 2 and customers[0]['segment'] == 'loyal' and customers[0]['consent']
    campaign = {'name': 'Sexta do burger', 'segment': 'all', 'message': 'Olá, {nome}! Venha para {loja}: {link}'}
    preview = send(client, 'POST', '/api/admin/marketing/campaigns/preview', campaign)
    assert preview.status_code == 200 and preview.json['total'] == 1
    assert 'Olá, Cliente!' in preview.json['recipients'][0]['message']
    assert send(client, 'POST', '/api/admin/marketing/campaigns', campaign).status_code == 201
    assert len(client.get('/api/admin/marketing').json['campaigns']) == 1
    token = link_from(preview.json['recipients'][0]['message'], 'cancelar_promocoes')
    assert send(client, 'POST', '/api/store/minha-loja/unsubscribe/' + token, {}).status_code == 200
    assert send(client, 'POST', '/api/admin/marketing/campaigns/preview', campaign).json['total'] == 0
    assert client.get('/api/admin/customers').json['customers'][0]['orders'] == 2
    assert len(client.get('/api/admin/customers/11999999999/orders').json['orders']) == 2
    assert send(client, 'POST', '/api/admin/customers/11999999999/anonymize', {}).status_code == 200
    assert all(o['customer'] == 'Cliente removido' for o in client.get('/api/admin/orders').json['orders'])


def test_marketing_roles_csrf_suggestions_and_anonymization(app, shop):
    client, pid = shop
    for role in ('kitchen', 'cashier'):
        send(client, 'POST', '/api/admin/team', {'name': 'Pessoa ' + role, 'email': role + '@example.com', 'password': 'uma-senha-segura', 'role': role})
        member = app.test_client()
        send(member, 'POST', '/api/auth/login', {'email': role + '@example.com', 'password': 'uma-senha-segura'})
        assert member.get('/api/admin/marketing').status_code == 403
        assert member.get('/api/admin/ingredients').status_code == 403
    assert app.test_client().get('/api/admin/marketing').status_code == 401
    assert client.post('/api/admin/marketing/suggestions', json={'product_ids': [pid]}).status_code == 403
    assert send(client, 'PUT', '/api/admin/marketing/suggestions', {'product_ids': [pid]}).status_code == 200
    assert client.get('/api/store/minha-loja').json['products'][0]['suggested'] == 1
    assert send(client, 'PUT', '/api/admin/marketing/suggestions', {'product_ids': [pid, pid]}).status_code == 400
    assert send(client, 'POST', '/api/store/minha-loja/orders', payload(pid, marketing_consent=True), uuid.uuid4().hex).status_code == 201
    capture(client, pid)
    assert send(client, 'POST', '/api/admin/customers/11999999999/anonymize', {}).status_code == 200
    assert sql(client, 'SELECT * FROM customer_opt_ins') == []
    assert all(not c['phone'] for c in sql(client, 'SELECT phone FROM shopping_sessions'))
