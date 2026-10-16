import json
import uuid
from unittest.mock import patch

import pytest

from database import initialize
from tests.test_api import app, shop, payload, register, send
from tests.test_business import advance
from tests.test_growth import sql
from upsell import signer


BASE = '/api/admin/marketing/combinations'


def product(client, name='Suco', **values):
    response = send(client, 'POST', '/api/admin/products', {'name': name, 'price': 700, 'active': True, **values})
    assert response.status_code == 201, response.json
    return response.json['id']


def update(client, pid, **values):
    saved = next(p for p in client.get('/api/admin/products').json['products'] if p['id'] == pid)
    response = send(client, 'PUT', f'/api/admin/products/{pid}', {**saved, **values})
    assert response.status_code == 200, response.json


def offer(client, source):
    products = client.get('/api/store/minha-loja').json['products']
    return next(p for p in products if p['id'] == source)['suggestions'][0]['token']


def order(client, source, target, token, **values):
    items = [{'product_id': source, 'quantity': 1, 'option_ids': []},
             {'product_id': target, 'quantity': 2, 'option_ids': [], 'suggestion_token': token}]
    return send(client, 'POST', '/api/store/minha-loja/orders', payload(source, **{'items': items, **values}), uuid.uuid4().hex)


def test_configuration_is_ordered_tenant_safe_and_private(shop, app):
    client, source = shop
    target, other = product(client), product(client, 'Batata')
    foreign = app.test_client()
    assert register(foreign, 'outra-loja', 'other@example.com').status_code == 201
    foreign_id = product(foreign)
    for ids in ([source], [target, target], [foreign_id], [True], ['1'], None, list(range(100, 107))):
        assert send(client, 'PUT', BASE + f'/{source}', {'ids': ids}).status_code == 400
    assert send(foreign, 'PUT', BASE + f'/{source}', {'ids': []}).status_code == 404
    inactive = product(client, 'Inativo', active=False)
    assert send(client, 'PUT', BASE + f'/{source}', {'ids': [inactive]}).status_code == 400
    assert send(client, 'PUT', BASE + f'/{source}', {'ids': [other, target]}).status_code == 200
    saved = next(p for p in client.get(BASE).json['products'] if p['id'] == source)
    assert saved['suggestion_ids'] == [other, target]
    catalog = client.get('/api/store/minha-loja').json['products']
    public = next(p for p in catalog if p['id'] == source)
    assert 'suggestion_ids' not in public and 'unit_cost' not in public
    assert [o['product_id'] for o in public['suggestions']] == [other, target]
    assert all('unit_cost' not in p for p in catalog)
    assert foreign.get(BASE + '/report').json['totals']['gross'] == 0
    anonymous = app.test_client()
    assert anonymous.get(BASE).status_code == 401
    for role in ('cashier', 'kitchen', 'manager'):
        email = role + '@example.com'
        member = send(client, 'POST', '/api/admin/team', {'name': 'Equipe Teste', 'email': email, 'password': 'senha-segura-nova', 'role': role})
        assert member.status_code == 201, member.json
        staff = app.test_client()
        assert send(staff, 'POST', '/api/auth/login', {'email': email, 'password': 'senha-segura-nova'}).status_code == 200
        expected = 200 if role == 'manager' else 403
        assert staff.get(BASE).status_code == expected
        assert staff.get(BASE + '/report').status_code == expected
        assert send(staff, 'PUT', BASE + f'/{source}', {'ids': [target]}).status_code == expected


def test_availability_rules_and_stock_apply_to_offers(shop):
    client, source = shop
    target = product(client, stock=0)
    assert send(client, 'PUT', BASE + f'/{source}', {'ids': [target]}).status_code == 200
    assert next(p for p in client.get('/api/store/minha-loja').json['products'] if p['id'] == source)['suggestions'] == []
    update(client, target, stock=4)
    assert offer(client, source)
    rule = {'name': 'Delivery oculto', 'product_id': target, 'kind': 'visibility', 'channels': ['web'],
            'days': list(range(7)), 'start_time': '00:00', 'end_time': '00:00', 'value': 0}
    result = send(client, 'POST', '/api/admin/catalog-rules', rule)
    assert result.status_code == 200
    assert next(p for p in client.get('/api/store/minha-loja').json['products'] if p['id'] == source)['suggestions'] == []
    assert send(client, 'DELETE', '/api/admin/catalog-rules/' + str(result.json['id']), {}).status_code == 200
    assert offer(client, source)
    update(client, target, active=False)
    assert next(p for p in client.get('/api/store/minha-loja').json['products'] if p['id'] == source)['suggestions'] == []


def test_offer_never_bypasses_stock_options_or_programmed_prices(shop):
    client, source = shop
    target = product(client, stock=1, option_groups=[{'id': 'flavor', 'name': 'Sabor', 'min': 1, 'max': 1,
                     'options': [{'id': 'orange', 'name': 'Laranja', 'price': 100}]}])
    send(client, 'PUT', BASE + f'/{source}', {'ids': [target]})
    token = offer(client, source)
    assert order(client, source, target, token).status_code == 400  # Missing mandatory choice.
    items = [{'product_id': source, 'quantity': 1, 'option_ids': []},
             {'product_id': target, 'quantity': 2, 'option_ids': ['orange'], 'suggestion_token': token}]
    assert order(client, source, target, token, items=items).status_code == 409
    items[1]['quantity'] = 1
    rule = {'name': 'Preço web', 'product_id': target, 'kind': 'price', 'channels': ['web'],
            'days': list(range(7)), 'start_time': '00:00', 'end_time': '00:00', 'value': 600}
    assert send(client, 'POST', '/api/admin/catalog-rules', rule).status_code == 200
    assert order(client, source, target, token, items=items).status_code == 201
    saved = client.get('/api/admin/orders').json['orders'][0]
    line = next(i for i in saved['items'] if i['product_id'] == target)
    assert line['unit_price'] == 700 and line['suggested_by'] == source
    assert next(p for p in client.get('/api/admin/products').json['products'] if p['id'] == target)['stock'] == 0
    assert client.put(BASE + f'/{source}', json={'ids': []}).status_code == 403


def test_attributed_order_uses_server_prices_completed_only_and_historical_names(shop):
    client, source = shop
    target = product(client)
    send(client, 'PUT', BASE + f'/{source}', {'ids': [target]})
    token = offer(client, source)
    key = uuid.uuid4().hex
    body = payload(source, items=[{'product_id': source, 'quantity': 1, 'option_ids': []},
                                 {'product_id': target, 'quantity': 2, 'option_ids': [], 'suggestion_token': token, 'unit_price': 1}])
    created = send(client, 'POST', '/api/store/minha-loja/orders', body, key)
    assert created.status_code == 201, created.json
    assert send(client, 'POST', '/api/store/minha-loja/orders', body, key).status_code == 200
    saved = client.get('/api/admin/orders').json['orders'][0]
    line = next(i for i in saved['items'] if i['product_id'] == target)
    assert line['unit_price'] == 700
    assert line['suggested_by'] == source and line['suggested_by_name'] == 'Burger'
    assert client.get(BASE + '/report').json['totals'] == {'orders': 0, 'units': 0, 'gross': 0}
    advance(client, saved['id'], 'preparing', 'ready', 'delivering', 'completed')
    # Later menu changes cannot rewrite historical attribution.
    send(client, 'PUT', BASE + f'/{source}', {'ids': []})
    update(client, source, name='Novo Burger')
    update(client, target, name='Novo Suco', price=900)
    result = client.get(BASE + '/report?days=7').json
    assert result['totals'] == {'orders': 1, 'units': 2, 'gross': 1400}
    assert result['ranking'][0]['source_name'] == 'Burger'
    assert result['ranking'][0]['name'] == 'Suco'
    assert client.get(BASE + '/report?days=365').status_code == 400


@pytest.mark.parametrize('kind', ['forged', 'expired', 'no-source', 'removed', 'foreign', 'wrong-target', 'malformed'])
def test_invalid_attribution_does_not_block_checkout_or_inflate_report(shop, kind):
    client, source = shop
    target = product(client)
    send(client, 'PUT', BASE + f'/{source}', {'ids': [target]})
    token = offer(client, source)
    if kind == 'forged':
        token += 'corrupted'
    elif kind == 'expired':
        with client.application.app_context(), patch('time.time', return_value=1):
            token = signer().dumps([1, source, target])
    elif kind == 'removed':
        send(client, 'PUT', BASE + f'/{source}', {'ids': []})
    elif kind in ('foreign', 'wrong-target', 'malformed'):
        with client.application.app_context():
            sid = client.get('/api/admin/store').json['store']['id']
            value = [sid + 999, source, target] if kind == 'foreign' else [sid, source, target + 999] if kind == 'wrong-target' else {'source': source}
            token = signer().dumps(value)
    extra = {'items': [{'product_id': target, 'quantity': 2, 'option_ids': [], 'suggestion_token': token}]} if kind == 'no-source' else {}
    assert order(client, source, target, token, **extra).status_code == 201
    saved = client.get('/api/admin/orders').json['orders'][0]
    assert next(i for i in saved['items'] if i['product_id'] == target)['suggested_by'] is None
    advance(client, saved['id'], 'preparing', 'ready', 'delivering', 'completed')
    assert client.get(BASE + '/report').json['totals']['gross'] == 0


def test_cancelled_old_and_plain_orders_are_excluded_and_migration_repeats(shop):
    client, source = shop
    target = product(client)
    send(client, 'PUT', BASE + f'/{source}', {'ids': [target]})
    token = offer(client, source)
    for i in range(3):
        assert order(client, source, target, token if i != 2 else '').status_code == 201
        saved = client.get('/api/admin/orders').json['orders'][0]
        if i == 0:
            advance(client, saved['id'], 'cancelled')
        else:
            advance(client, saved['id'], 'preparing', 'ready', 'delivering', 'completed')
            if i == 1:
                sql(client, "UPDATE orders SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?", (saved['id'],))
    assert client.get(BASE + '/report').json['totals']['orders'] == 0
    initialize(client.application.config)
    initialize(client.application.config)
    assert json.loads(sql(client, 'SELECT suggestion_ids FROM products WHERE id=?', (source,))[0]['suggestion_ids']) == [target]
    assert len(sql(client, 'SELECT id FROM orders')) == 3
