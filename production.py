"""Progresso por item: o pedido fica pronto quando todos os itens estão prontos."""
from types import SimpleNamespace

from flask import abort,g,jsonify


def register_production(app,helpers):
    h=SimpleNamespace(**helpers)

    @app.patch('/api/admin/order-items/<int:iid>/kitchen')
    @h.owner
    def kitchen_item_update(iid):
        value=h.data();state=value.get('state')
        if state not in ('preparing','ready'):abort(400,description='Escolha em preparo ou pronto.')
        changed=False
        with h.transaction() as conn:
            item=conn.execute('SELECT i.*,o.store_id,o.status FROM order_items i JOIN orders o ON o.id=i.order_id WHERE i.id=? AND o.store_id=?',(iid,g.store['id'])).fetchone()
            if not item:abort(404,description='Item não encontrado.')
            if item['kitchen_state']==state:return jsonify(ok=True,status=item['status'])
            if item['status'] not in ('new','preparing') or (item['kitchen_state'],state) not in (('new','preparing'),('preparing','ready')):
                abort(409,description='Este item não pode avançar para essa etapa agora.')
            conn.execute('UPDATE order_items SET kitchen_state=? WHERE id=?',(state,iid))
            remaining=conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id=? AND kitchen_state!='ready'",(item['order_id'],)).fetchone()[0]
            status='preparing' if remaining else 'ready'
            changed=status!=item['status']
            if changed:
                conn.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(status,h.now(),item['order_id']))
                conn.execute('INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)',(item['order_id'],status,h.now()))
        if changed:app.extensions['on_status'](g.store['id'],item['order_id'],status)
        return jsonify(ok=True,status=status)
