"""Combinações por produto e atribuição de itens, sem alterar preços do pedido."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flask import abort, current_app, g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer


def suggestion_ids(value):
    try:
        ids = json.loads(value or '[]') if isinstance(value, str) else value
    except (ValueError, TypeError):
        return []
    return ids if isinstance(ids, list) and len(ids) <= 6 and all(type(i) is int for i in ids) else []


def signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='product-suggestion-v1')


def public_suggestions(products, sid):
    available = {p['id'] for p in products if p['stock'] != 0}
    tokens = signer()
    for product in products:
        ids = suggestion_ids(product.pop('suggestion_ids', []))
        product['suggestions'] = [
            {'product_id': target, 'token': tokens.dumps([sid, product['id'], target])}
            for target in ids if target != product['id'] and target in available
        ] if product['id'] in available else []


def attribution(raw, product, prepared, sid):
    """Accept only a signed current offer whose source is present in this order.

    Missing/expired metadata never prevents checkout. Prices and stock are always
    validated by the normal order pipeline, independently of this metadata.
    """
    token = raw.get('suggestion_token')
    if not isinstance(token, str) or len(token) > 1024:
        return None, ''
    try:
        offer = signer().loads(token, max_age=7 * 86400)
    except (BadSignature, ValueError, TypeError):
        return None, ''
    if not isinstance(offer, list) or len(offer) != 3 or any(type(i) is not int for i in offer):
        return None, ''
    store_id, source_id, target_id = offer
    if store_id != sid or target_id != product['id'] or source_id == target_id:
        return None, ''
    source = next((p for p, *_ in prepared if p['id'] == source_id), None)
    if source is None or target_id not in suggestion_ids(source['suggestion_ids']):
        return None, ''
    return source_id, source['name']


def register_upsell(app, helpers):
    h = SimpleNamespace(**helpers)

    @app.get('/api/admin/marketing/combinations')
    @h.owner
    def upsell_settings():
        products = h.rows('SELECT id,name,active,stock,suggestion_ids FROM products WHERE store_id=? ORDER BY name,id', (g.store['id'],))
        for product in products:
            product['suggestion_ids'] = suggestion_ids(product['suggestion_ids'])
        return jsonify(products=products)

    @app.put('/api/admin/marketing/combinations/<int:pid>')
    @h.owner
    def upsell_save(pid):
        ids = h.data().get('ids')
        if (not isinstance(ids, list) or len(ids) > 6 or any(type(i) is not int or i <= 0 for i in ids)
                or len(set(ids)) != len(ids) or pid in ids):
            abort(400, description='Escolha até 6 produtos diferentes, sem incluir o próprio produto.')
        with h.transaction() as conn:
            source = conn.execute('SELECT id FROM products WHERE store_id=? AND id=?', (g.store['id'], pid)).fetchone()
            if source is None:
                abort(404, description='Produto não encontrado.')
            for target in ids:
                if conn.execute('SELECT id FROM products WHERE store_id=? AND id=? AND active=1', (g.store['id'], target)).fetchone() is None:
                    abort(400, description='Escolha apenas produtos ativos desta loja.')
            conn.execute('UPDATE products SET suggestion_ids=? WHERE store_id=? AND id=?', (json.dumps(ids), g.store['id'], pid))
        return jsonify(ok=True)

    @app.get('/api/admin/marketing/combinations/report')
    @h.owner
    def upsell_report():
        if request.args.get('days', '30') not in ('7', '30', '90'):
            abort(400, description='Escolha 7, 30 ou 90 dias.')
        days = int(request.args.get('days', '30'))
        until = datetime.now(timezone.utc)
        since = (until - timedelta(days=days)).isoformat(timespec='seconds')
        until = until.isoformat(timespec='seconds')
        params = (g.store['id'], since, until)
        where = "o.store_id=? AND o.status='completed' AND o.created_at>=? AND o.created_at<=? AND i.suggested_by IS NOT NULL"
        totals = h.one(f'''SELECT COUNT(DISTINCT o.id) AS orders, COALESCE(SUM(i.quantity),0) AS units,
            COALESCE(SUM(i.quantity*i.unit_price),0) AS gross FROM order_items i JOIN orders o ON o.id=i.order_id WHERE {where}''', params)
        ranking = h.rows(f'''SELECT i.suggested_by AS source_id,i.suggested_by_name AS source_name,
            i.product_id,i.name,COUNT(DISTINCT o.id) AS orders,SUM(i.quantity) AS units,SUM(i.quantity*i.unit_price) AS gross
            FROM order_items i JOIN orders o ON o.id=i.order_id WHERE {where}
            GROUP BY i.suggested_by,i.suggested_by_name,i.product_id,i.name
            ORDER BY gross DESC,source_name,i.name LIMIT 100''', params)
        return jsonify(days=days, since=since, until=until, totals=dict(totals), ranking=ranking)
