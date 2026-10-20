"""Customer context beside a conversation, restricted to the current store."""
import json
from types import SimpleNamespace

from flask import g, jsonify

from marketing import NORMAL_PHONE, phone_key


def register_inbox_context(app, helpers):
    h = SimpleNamespace(**helpers)

    @app.get('/api/admin/inbox/<int:tid>/context')
    @h.owner
    def inbox_context(tid):
        thread = h.owned('inbox_threads', tid)
        params = (g.store['id'], phone_key(thread['phone']))
        where = f'store_id=? AND {NORMAL_PHONE}=?'
        summary = h.one(f'''SELECT COUNT(*) AS orders,
            SUM(CASE WHEN status='completed' THEN total ELSE 0 END) AS spent,
            SUM(CASE WHEN status NOT IN ('completed','cancelled') THEN 1 ELSE 0 END) AS active,
            MIN(created_at) AS first_order,MAX(created_at) AS last_order
            FROM orders WHERE {where} AND status!='cancelled' ''', params)
        recent = h.rows(f'''SELECT id,number,customer,status,total,paid,mode,address,payment,created_at
            FROM orders WHERE {where} ORDER BY id DESC LIMIT 8''', params)
        item_groups = {order['id']: [] for order in recent}
        if recent:
            placeholders = ','.join('?' for _ in recent)
            for item in h.rows(f'SELECT order_id,name,quantity,extras FROM order_items WHERE order_id IN ({placeholders}) ORDER BY id', tuple(item_groups)):
                oid = item.pop('order_id')
                try:
                    choices = json.loads(item.pop('extras'))
                    item['options'] = [v['name'] for v in choices if isinstance(v, dict) and isinstance(v.get('name'), str)]
                except (ValueError, TypeError):
                    item['options'] = []
                item_groups[oid].append(item)
        for order in recent:
            order['items'] = item_groups[order['id']]
        response = jsonify(customer={'name': thread['name'], 'phone': thread['phone']},
                           summary={**dict(summary), 'spent': summary['spent'] or 0, 'active': summary['active'] or 0}, orders=recent)
        response.headers['Cache-Control'] = 'no-store'
        return response
