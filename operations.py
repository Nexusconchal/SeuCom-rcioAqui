"""Caixa por turno, recebimentos auditáveis e contas do salão."""
import hashlib
import json
import re
from types import SimpleNamespace

from flask import abort, g, jsonify, request


DDL = """
CREATE TABLE IF NOT EXISTS cash_sessions (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), opened_by INTEGER NOT NULL REFERENCES users(id),
 opening INTEGER NOT NULL CHECK(opening>=0), opened_at TEXT NOT NULL, closed_at TEXT,
 counted INTEGER, expected INTEGER, difference INTEGER, closed_by INTEGER REFERENCES users(id), notes TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_cash_open ON cash_sessions(store_id) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS cash_adjustments (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), session_id INTEGER NOT NULL REFERENCES cash_sessions(id),
 delta INTEGER NOT NULL, reason TEXT NOT NULL, actor_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_receipts (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), order_id INTEGER NOT NULL REFERENCES orders(id),
 session_id INTEGER NOT NULL REFERENCES cash_sessions(id), amount INTEGER NOT NULL CHECK(amount>0),
 method TEXT NOT NULL CHECK(method IN ('cash','pix','card')), kind TEXT NOT NULL CHECK(kind IN ('receipt','refund')),
 original_id INTEGER REFERENCES order_receipts(id), actor_id INTEGER NOT NULL REFERENCES users(id),
 reason TEXT NOT NULL DEFAULT '', key TEXT NOT NULL, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(store_id,key)
);
CREATE INDEX IF NOT EXISTS ix_receipts_order ON order_receipts(store_id,order_id);
CREATE INDEX IF NOT EXISTS ix_receipts_session ON order_receipts(session_id);
CREATE TABLE IF NOT EXISTS dining_tables (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 UNIQUE(store_id,name)
);
CREATE TABLE IF NOT EXISTS dining_accounts (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), table_id INTEGER NOT NULL REFERENCES dining_tables(id),
 customer TEXT NOT NULL, guests INTEGER NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT, opened_by INTEGER NOT NULL REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_dining_open ON dining_accounts(table_id) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS dining_orders (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), account_id INTEGER NOT NULL REFERENCES dining_accounts(id),
 order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id)
);
"""


def received(conn, sid, order):
    # Pedidos quitados antes da adoção do livro de caixa continuam quitados.
    row = conn.execute("""SELECT COUNT(*) AS n,COALESCE(SUM(CASE WHEN kind='receipt' THEN amount ELSE -amount END),0) AS amount
        FROM order_receipts WHERE store_id=? AND order_id=?""", (sid, order['id'])).fetchone()
    return row['amount'] if row['n'] else (order['total'] if order['paid'] else 0)


def receipt_state(conn,sid,orders):
    balances={o['id']:o['total'] if o['paid'] else 0 for o in orders}
    methods={};tracked=set();ids=list(balances)
    for index in range(0,len(ids),500):
        batch=ids[index:index+500]
        for r in conn.execute("SELECT order_id,method,SUM(CASE WHEN kind='receipt' THEN amount ELSE -amount END) AS amount FROM order_receipts WHERE store_id=? AND order_id IN ("+','.join('?' for _ in batch)+') GROUP BY order_id,method',(sid,*batch)):
            if r['order_id'] not in tracked:balances[r['order_id']]=0;tracked.add(r['order_id'])
            balances[r['order_id']]+=r['amount'];methods[r['method']]=methods.get(r['method'],0)+r['amount']
    for o in orders:
        if o['id'] not in tracked and o['paid']:methods[o['payment']]=methods.get(o['payment'],0)+o['total']
    return balances,methods


def register_operations(app, helpers):
    h = SimpleNamespace(**helpers)

    def active_session(conn):
        row = conn.execute('SELECT * FROM cash_sessions WHERE store_id=? AND closed_at IS NULL', (g.store['id'],)).fetchone()
        if not row:
            abort(409, description='Abra um turno no Caixa antes de registrar o recebimento.')
        return row

    def audit(conn, action, detail):
        conn.execute('INSERT INTO audit_log(actor_id,store_id,action,detail,created_at) VALUES(?,?,?,?,?)',
                     (g.user['id'], g.store['id'], action, detail, h.now()))

    def confirm_from_order(conn,order,status):
        current=conn.execute('SELECT * FROM cash_sessions WHERE store_id=? AND closed_at IS NULL',(order['store_id'],)).fetchone()
        if not current or not order['total']:return
        if status=='cancelled':abort(409,description='Não receba um pedido cancelado. Use recebimento e estorno no Caixa.')
        if order['payment'] not in ('cash','pix','card'):return
        value={'amount':order['total'],'method':order['payment'],'kind':'receipt','reason':'Confirmado pelo pedido'}
        digest=hashlib.sha256(json.dumps({'order':order['id'],'value':value},sort_keys=True).encode()).hexdigest()
        conn.execute("""INSERT INTO order_receipts(store_id,order_id,session_id,amount,method,kind,actor_id,reason,key,payload_hash,created_at)
            VALUES(?,?,?,?,?,'receipt',?,?,?,?,?)""",(order['store_id'],order['id'],current['id'],order['total'],order['payment'],g.user['id'],value['reason'],f"confirm-order-{order['id']}-paid",digest,h.now()))
        audit(conn,'cash.receipt',str(order['id'])+':'+str(order['total']))

    app.extensions['cash_confirm_from_order']=confirm_from_order

    def session_info(row):
        result = dict(row)
        totals = h.rows("""SELECT method,COALESCE(SUM(CASE WHEN kind='receipt' THEN amount ELSE -amount END),0) AS amount
            FROM order_receipts WHERE session_id=? GROUP BY method""", (row['id'],))
        result['totals'] = {t['method']: t['amount'] for t in totals}
        result['adjustments'] = h.rows('SELECT * FROM cash_adjustments WHERE session_id=? ORDER BY id', (row['id'],))
        result['expected_now'] = row['opening'] + result['totals'].get('cash', 0) + sum(x['delta'] for x in result['adjustments'])
        return result

    @app.get('/api/admin/cash')
    @h.owner
    def cash_overview():
        sid = g.store['id']
        current = h.one('SELECT * FROM cash_sessions WHERE store_id=? AND closed_at IS NULL', (sid,))
        history = h.rows('SELECT * FROM cash_sessions WHERE store_id=? AND closed_at IS NOT NULL ORDER BY id DESC LIMIT 30', (sid,))
        orders = h.rows("SELECT id,number,customer,payment,total,paid,status,created_at FROM orders WHERE store_id=? AND status!='cancelled' ORDER BY id DESC LIMIT 200", (sid,))
        balances,_=receipt_state(h.db(),sid,orders)
        for order in orders:
            order['received'] = balances[order['id']]
            order['remaining'] = max(0, order['total'] - order['received'])
        return jsonify(current=session_info(current) if current else None, history=history, orders=orders,
            receipts=h.rows('SELECT r.*,o.number,o.customer FROM order_receipts r JOIN orders o ON o.id=r.order_id WHERE r.store_id=? ORDER BY r.id DESC LIMIT 100', (sid,)))

    @app.post('/api/admin/cash/open')
    @h.owner
    def cash_open():
        value = h.data()
        with h.transaction() as conn:
            if conn.execute('SELECT id FROM cash_sessions WHERE store_id=? AND closed_at IS NULL', (g.store['id'],)).fetchone():
                abort(409, description='Já existe um turno aberto.')
            cid = conn.execute('INSERT INTO cash_sessions(store_id,opened_by,opening,opened_at,notes) VALUES(?,?,?,?,?)',
                (g.store['id'], g.user['id'], h.integer(value, 'opening', maximum=10**9), h.now(), h.text(value, 'notes', 0, 300))).lastrowid
            audit(conn, 'cash.open', str(cid))
        return jsonify(id=cid), 201

    @app.post('/api/admin/cash/adjust')
    @h.owner
    def cash_adjust():
        value = h.data()
        delta = h.integer(value, 'delta', minimum=-10**9, maximum=10**9)
        if not delta:
            abort(400, description='Informe um valor diferente de zero.')
        with h.transaction() as conn:
            current = active_session(conn)
            if session_info(current)['expected_now'] + delta < 0:
                abort(409, description='A retirada é maior que o dinheiro esperado no caixa.')
            conn.execute('INSERT INTO cash_adjustments(store_id,session_id,delta,reason,actor_id,created_at) VALUES(?,?,?,?,?,?)',
                (g.store['id'], current['id'], delta, h.text(value, 'reason', 3, 200), g.user['id'], h.now()))
            audit(conn, 'cash.adjust', str(current['id']) + ':' + str(delta))
        return jsonify(ok=True), 201

    @app.post('/api/admin/cash/close')
    @h.owner
    def cash_close():
        value = h.data()
        with h.transaction() as conn:
            current = active_session(conn)
            expected = session_info(current)['expected_now']
            counted = h.integer(value, 'counted', maximum=10**9)
            notes = h.text(value, 'notes', 0, 300)
            if counted != expected and len(notes) < 3:
                abort(400, description='Explique a diferença encontrada na conferência.')
            conn.execute('UPDATE cash_sessions SET closed_at=?,closed_by=?,counted=?,expected=?,difference=?,notes=? WHERE id=?',
                (h.now(), g.user['id'], counted, expected, counted - expected, notes, current['id']))
            audit(conn, 'cash.close', str(current['id']))
        return jsonify(expected=expected, difference=counted-expected)

    @app.post('/api/admin/orders/<int:oid>/receipts')
    @h.owner
    def order_receive(oid):
        value = h.data()
        key = request.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', key):
            abort(400, description='Identificador do recebimento inválido.')
        digest = hashlib.sha256(json.dumps({'order': oid, 'value': value}, sort_keys=True).encode()).hexdigest()
        amount = h.integer(value, 'amount', minimum=1, maximum=10**9)
        kind, method = value.get('kind', 'receipt'), value.get('method')
        if kind not in ('receipt', 'refund') or method not in ('cash', 'pix', 'card'):
            abort(400, description='Escolha recebimento ou estorno e a forma de pagamento.')
        with h.transaction() as conn:
            order = h.owned('orders', oid)
            previous = conn.execute('SELECT * FROM order_receipts WHERE store_id=? AND key=?', (g.store['id'], key)).fetchone()
            if previous:
                if previous['payload_hash'] != digest:
                    abort(409, description='Este identificador já pertence a outra operação.')
                return jsonify(id=previous['id']), 200
            if order['payment'] in ('pix_online','card_online'):
                abort(409,description='Recebimentos e estornos online são feitos pela integração, sem lançamento manual no caixa.')
            current = active_session(conn)
            balance = received(conn, g.store['id'], order)
            original = None
            reason = h.text(value, 'reason', 3 if kind == 'refund' else 0, 200)
            if kind == 'receipt':
                if order['status'] == 'cancelled' or amount > order['total'] - balance:
                    abort(409, description='O valor excede o saldo do pedido ou o pedido foi cancelado.')
            else:
                original = h.integer(value, 'original_id', minimum=1)
                receipt = h.owned('order_receipts', original)
                refunded = conn.execute("SELECT COALESCE(SUM(amount),0) FROM order_receipts WHERE original_id=? AND kind='refund'", (original,)).fetchone()[0]
                if receipt['kind'] != 'receipt' or receipt['order_id'] != oid or receipt['method'] != method or amount > receipt['amount'] - refunded:
                    abort(409, description='Este estorno excede o recebimento original ou usa outra forma de pagamento.')
                if method == 'cash' and amount > session_info(current)['expected_now']:
                    abort(409, description='Não há dinheiro suficiente neste caixa para o estorno.')
            rid = conn.execute('''INSERT INTO order_receipts(store_id,order_id,session_id,amount,method,kind,original_id,actor_id,reason,key,payload_hash,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (g.store['id'], oid, current['id'], amount, method, kind, original, g.user['id'], reason, key, digest, h.now())).lastrowid
            net = balance + (amount if kind == 'receipt' else -amount)
            conn.execute('UPDATE orders SET paid=?,updated_at=? WHERE id=?', (int(net >= order['total']), h.now(), oid))
            app.extensions['credit_payment'](conn, oid, net)
            audit(conn, 'cash.' + kind, str(oid) + ':' + str(amount))
        return jsonify(id=rid, received=net, remaining=max(0, order['total'] - net)), 201

    @app.get('/api/admin/dining')
    @h.owner
    def dining_list():
        sid = g.store['id']
        tables = h.rows('SELECT * FROM dining_tables WHERE store_id=? ORDER BY name', (sid,))
        for table in tables:
            account = h.one('SELECT * FROM dining_accounts WHERE table_id=? AND closed_at IS NULL', (table['id'],))
            if account:
                account = dict(account)
                account['orders'] = h.rows('SELECT o.* FROM dining_orders d JOIN orders o ON o.id=d.order_id WHERE d.account_id=? ORDER BY o.id', (account['id'],))
                account['orders'] = [dict(id=o['id'], number=o['number'], total=o['total'], status=o['status'], paid=bool(o['paid']), received=received(h.db(), sid, o)) for o in account['orders']]
                account['total'] = sum(o['total'] for o in account['orders'] if o['status'] != 'cancelled')
                account['remaining'] = sum(max(0, o['total'] - o['received']) for o in account['orders'] if o['status'] != 'cancelled')
            table['account'] = account
        return jsonify(tables=tables)

    @app.post('/api/admin/dining/tables')
    @h.owner
    def dining_table_add():
        if g.role == 'cashier':
            abort(403)
        value = h.data()
        tid = h.db().execute('INSERT INTO dining_tables(store_id,name) VALUES(?,?)', (g.store['id'], h.text(value, 'name', 1, 60))).lastrowid
        return jsonify(id=tid), 201

    @app.post('/api/admin/dining/tables/<int:tid>/open')
    @h.owner
    def dining_open(tid):
        value = h.data()
        with h.transaction() as conn:
            table = h.owned('dining_tables', tid)
            if not table['active']:
                abort(409, description='Mesa indisponível.')
            if conn.execute('SELECT id FROM dining_accounts WHERE table_id=? AND closed_at IS NULL', (tid,)).fetchone():
                abort(409, description='Esta mesa já está ocupada.')
            aid = conn.execute('INSERT INTO dining_accounts(store_id,table_id,customer,guests,opened_at,opened_by) VALUES(?,?,?,?,?,?)',
                (g.store['id'], tid, h.text(value, 'customer', 2, 100), h.integer(value, 'guests', default=1, minimum=1, maximum=100), h.now(), g.user['id'])).lastrowid
            audit(conn, 'dining.open', str(aid))
        return jsonify(id=aid), 201

    @app.post('/api/admin/dining/accounts/<int:aid>/transfer')
    @h.owner
    def dining_transfer(aid):
        value = h.data()
        with h.transaction() as conn:
            account = h.owned('dining_accounts', aid)
            target = h.owned('dining_tables', h.integer(value, 'table_id', minimum=1))
            if account['closed_at'] or not target['active'] or conn.execute('SELECT id FROM dining_accounts WHERE table_id=? AND closed_at IS NULL', (target['id'],)).fetchone():
                abort(409, description='A conta está encerrada ou a mesa de destino está ocupada.')
            conn.execute('UPDATE dining_accounts SET table_id=? WHERE id=?', (target['id'], aid))
            audit(conn, 'dining.transfer', str(aid) + ':' + str(target['id']))
        return jsonify(ok=True)

    @app.post('/api/admin/dining/accounts/<int:aid>/close')
    @h.owner
    def dining_close(aid):
        with h.transaction() as conn:
            account = h.owned('dining_accounts', aid)
            if account['closed_at']:
                abort(409, description='Esta conta já foi encerrada.')
            orders = conn.execute('SELECT o.* FROM dining_orders d JOIN orders o ON o.id=d.order_id WHERE d.account_id=?', (aid,)).fetchall()
            if any(o['status'] not in ('completed', 'cancelled') or (o['status'] != 'cancelled' and received(conn, g.store['id'], o) < o['total']) for o in orders):
                abort(409, description='Conclua o atendimento e receba os pedidos pendentes antes de liberar a mesa.')
            if any(o['status'] == 'cancelled' and received(conn, g.store['id'], o) > 0 for o in orders):
                abort(409, description='Estorne os pedidos cancelados antes de liberar a mesa.')
            conn.execute('UPDATE dining_accounts SET closed_at=? WHERE id=?', (h.now(), aid))
            audit(conn, 'dining.close', str(aid))
        return jsonify(ok=True)

    def attach_dining(conn, store, oid, value):
        aid = value.get('account_id')
        if aid is None:
            return
        if not getattr(g, 'manual_order', False) or not isinstance(aid, int) or isinstance(aid, bool):
            abort(400, description='A conta do salão só pode ser usada pelo atendimento da loja.')
        account = conn.execute('SELECT * FROM dining_accounts WHERE id=? AND store_id=? AND closed_at IS NULL', (aid, store['id'])).fetchone()
        if not account or value.get('mode') != 'pickup':
            abort(409, description='Conta encerrada, inválida ou incompatível com entrega.')
        conn.execute('INSERT INTO dining_orders(store_id,account_id,order_id) VALUES(?,?,?)', (store['id'], aid, oid))

    app.extensions['attach_dining'] = attach_dining
