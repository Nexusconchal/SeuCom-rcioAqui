"""Fornecedores, contas e produção de insumos intermediários."""
import hashlib
import json
import re
from datetime import date
from types import SimpleNamespace

from flask import abort, g, jsonify, request

DDL = """
CREATE TABLE IF NOT EXISTS option_recipes (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), product_id INTEGER NOT NULL REFERENCES products(id),
 option_id TEXT NOT NULL, ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 UNIQUE(product_id,option_id,ingredient_id)
);
CREATE TABLE IF NOT EXISTS suppliers (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
 document TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS obligations (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), supplier_id INTEGER REFERENCES suppliers(id),
 description TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('payable','receivable')), amount INTEGER NOT NULL CHECK(amount>0),
 settled INTEGER NOT NULL DEFAULT 0 CHECK(settled>=0), due_on TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'operating',
 created_at TEXT NOT NULL, voided_at TEXT
);
CREATE TABLE IF NOT EXISTS obligation_settlements (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), obligation_id INTEGER NOT NULL REFERENCES obligations(id),
 amount INTEGER NOT NULL CHECK(amount>0), actor_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 key TEXT NOT NULL, payload_hash TEXT NOT NULL, expense_id INTEGER REFERENCES expenses(id), UNIQUE(store_id,key)
);
CREATE TABLE IF NOT EXISTS production_recipes (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), output_id INTEGER NOT NULL REFERENCES ingredients(id),
 ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), quantity INTEGER NOT NULL CHECK(quantity>0), UNIQUE(output_id,ingredient_id)
);
CREATE TABLE IF NOT EXISTS production_batches (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), output_id INTEGER NOT NULL REFERENCES ingredients(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), actor_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
 key TEXT NOT NULL, payload_hash TEXT NOT NULL, UNIQUE(store_id,key)
);
CREATE INDEX IF NOT EXISTS ix_obligations_due ON obligations(store_id,due_on);
CREATE INDEX IF NOT EXISTS ix_option_recipes ON option_recipes(store_id,product_id);
"""


def option_recipe_map(conn, sid):
    result = {}
    for row in conn.execute('''SELECT r.product_id,r.option_id,r.ingredient_id,r.quantity,i.name,i.unit,i.stock,i.unit_cost,i.active
        FROM option_recipes r JOIN ingredients i ON i.id=r.ingredient_id WHERE r.store_id=?''', (sid,)):
        result.setdefault((row['product_id'], row['option_id']), []).append(dict(row))
    return result


def register_purchasing(app, helpers):
    h = SimpleNamespace(**helpers)

    def valid_date(value):
        try:
            return date.fromisoformat(h.text(value, 'due_on', 10, 10)).isoformat()
        except ValueError:
            abort(400, description='Informe uma data de vencimento válida.')

    def lines(value, output=None):
        items = value.get('ingredients')
        if not isinstance(items, list) or len(items) > 50:
            abort(400, description='Ficha técnica inválida.')
        result, seen = [], set()
        for line in items:
            if not isinstance(line, dict):
                abort(400, description='Ingrediente inválido.')
            iid = h.integer(line, 'ingredient_id', minimum=1)
            ingredient = h.owned('ingredients', iid)
            if iid in seen or iid == output or not ingredient['active']:
                abort(400, description='Use cada ingrediente ativo uma vez; o resultado não pode consumir a si próprio.')
            seen.add(iid)
            result.append((iid, h.integer(line, 'quantity', minimum=1, maximum=10**9)))
        return result

    def idempotency(value, context):
        key = request.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', key):
            abort(400, description='Identificador da operação inválido.')
        return key, hashlib.sha256(json.dumps([context, value], sort_keys=True).encode()).hexdigest()

    @app.put('/api/admin/products/<int:pid>/options/<option_id>/recipe')
    @h.owner
    def option_recipe_save(pid, option_id):
        value = h.data()
        with h.transaction() as conn:
            product = h.owned('products', pid)
            options = json.loads(product['extras']) + [o for group in json.loads(product['option_groups']) for o in group['options']]
            if not any(o['id'] == option_id for o in options):
                abort(404, description='Complemento não encontrado.')
            prepared = lines(value)
            conn.execute('DELETE FROM option_recipes WHERE store_id=? AND product_id=? AND option_id=?', (g.store['id'], pid, option_id))
            for iid, quantity in prepared:
                conn.execute('INSERT INTO option_recipes(store_id,product_id,option_id,ingredient_id,quantity) VALUES(?,?,?,?,?)', (g.store['id'], pid, option_id, iid, quantity))
        return jsonify(ok=True)

    @app.get('/api/admin/purchasing')
    @h.owner
    def purchasing_overview():
        sid = g.store['id']
        return jsonify(suppliers=h.rows('SELECT * FROM suppliers WHERE store_id=? ORDER BY active DESC,name', (sid,)),
            obligations=h.rows('SELECT b.*,s.name AS supplier,o.number AS order_number FROM obligations b LEFT JOIN suppliers s ON s.id=b.supplier_id LEFT JOIN orders o ON o.id=b.order_id WHERE b.store_id=? ORDER BY b.due_on,b.id DESC LIMIT 500', (sid,)),
            settlements=h.rows('SELECT x.*,b.description,b.kind FROM obligation_settlements x JOIN obligations b ON b.id=x.obligation_id WHERE x.store_id=? ORDER BY x.id DESC LIMIT 100', (sid,)),
            ingredients=h.rows('SELECT * FROM ingredients WHERE store_id=? ORDER BY name', (sid,)),
            production=h.rows('SELECT * FROM production_recipes WHERE store_id=?', (sid,)),
            batches=h.rows('SELECT b.*,i.name,i.unit FROM production_batches b JOIN ingredients i ON i.id=b.output_id WHERE b.store_id=? ORDER BY b.id DESC LIMIT 50', (sid,)))

    @app.post('/api/admin/suppliers')
    @app.put('/api/admin/suppliers/<int:sid>')
    @h.owner
    def supplier_save(sid=None):
        value = h.data()
        if sid is not None:
            h.owned('suppliers', sid)
        fields = (h.text(value, 'name', 2, 100), h.text(value, 'phone', 0, 20), h.text(value, 'document', 0, 30), h.text(value, 'notes', 0, 500), h.boolean(value, 'active', True))
        if sid is None:
            sid = h.db().execute('INSERT INTO suppliers(store_id,name,phone,document,notes,active) VALUES(?,?,?,?,?,?)', (g.store['id'], *fields)).lastrowid
        else:
            h.db().execute('UPDATE suppliers SET name=?,phone=?,document=?,notes=?,active=? WHERE id=? AND store_id=?', (*fields, sid, g.store['id']))
        return jsonify(id=sid)

    @app.post('/api/admin/obligations')
    @h.owner
    def obligation_add():
        value = h.data()
        supplier = value.get('supplier_id')
        if supplier is not None:
            supplier = h.integer(value, 'supplier_id', minimum=1)
            h.owned('suppliers', supplier)
        kind, category = value.get('kind'), value.get('category', 'operating')
        if kind not in ('payable', 'receivable') or category not in ('operating', 'inventory'):
            abort(400, description='Tipo de conta ou categoria inválida.')
        bid = h.db().execute('INSERT INTO obligations(store_id,supplier_id,description,kind,amount,due_on,category,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (g.store['id'], supplier, h.text(value, 'description', 2, 200), kind, h.integer(value, 'amount', minimum=1, maximum=10**9), valid_date(value), category, h.now())).lastrowid
        return jsonify(id=bid), 201

    @app.post('/api/admin/obligations/<int:bid>/settle')
    @h.owner
    def obligation_settle(bid):
        value = h.data()
        key, digest = idempotency(value, bid)
        amount = h.integer(value, 'amount', minimum=1, maximum=10**9)
        with h.transaction() as conn:
            current = h.owned('obligations', bid)
            if current['order_id'] is not None:
                abort(409,description='Receba o fiado no Caixa para manter o pedido e a conta conciliados.')
            previous = conn.execute('SELECT * FROM obligation_settlements WHERE store_id=? AND key=?', (g.store['id'], key)).fetchone()
            if previous:
                if previous['payload_hash'] != digest:
                    abort(409, description='Este identificador já foi usado em outra baixa.')
                return jsonify(id=previous['id']), 200
            if current['voided_at'] or amount > current['amount'] - current['settled']:
                abort(409, description='A conta foi cancelada ou o valor excede o saldo.')
            expense = None
            if current['kind'] == 'payable':
                expense = conn.execute('INSERT INTO expenses(store_id,description,amount,created_at,category) VALUES(?,?,?,?,?)',
                    (g.store['id'], 'Conta #' + str(bid) + ' • ' + current['description'], amount, h.now(), current['category'])).lastrowid
            rid = conn.execute('INSERT INTO obligation_settlements(store_id,obligation_id,amount,actor_id,created_at,key,payload_hash,expense_id) VALUES(?,?,?,?,?,?,?,?)',
                (g.store['id'], bid, amount, g.user['id'], h.now(), key, digest, expense)).lastrowid
            conn.execute('UPDATE obligations SET settled=settled+? WHERE id=?', (amount, bid))
        return jsonify(id=rid), 201

    @app.post('/api/admin/obligations/<int:bid>/void')
    @h.owner
    def obligation_void(bid):
        with h.transaction() as conn:
            current = h.owned('obligations', bid)
            if current['settled'] or current['voided_at']:
                abort(409, description='Uma conta com baixas ou já cancelada não pode ser cancelada novamente.')
            conn.execute('UPDATE obligations SET voided_at=? WHERE id=?', (h.now(), bid))
        return jsonify(ok=True)

    @app.put('/api/admin/ingredients/<int:iid>/production-recipe')
    @h.owner
    def production_recipe_save(iid):
        value = h.data()
        with h.transaction() as conn:
            h.owned('ingredients', iid)
            prepared = lines(value, iid)
            # A ficha produz 1 kg/l/un do resultado. Não há cascata implícita: cada lote tem entradas e saída reais.
            conn.execute('DELETE FROM production_recipes WHERE output_id=? AND store_id=?', (iid, g.store['id']))
            for ingredient, quantity in prepared:
                conn.execute('INSERT INTO production_recipes(store_id,output_id,ingredient_id,quantity) VALUES(?,?,?,?)', (g.store['id'], iid, ingredient, quantity))
        return jsonify(ok=True)

    @app.post('/api/admin/ingredients/<int:iid>/produce')
    @h.owner
    def production_run(iid):
        value = h.data()
        key, digest = idempotency(value, iid)
        quantity = h.integer(value, 'quantity', minimum=1, maximum=10**9)
        with h.transaction() as conn:
            output = h.owned('ingredients', iid)
            previous = conn.execute('SELECT * FROM production_batches WHERE store_id=? AND key=?', (g.store['id'], key)).fetchone()
            if previous:
                if previous['payload_hash'] != digest:
                    abort(409, description='Este identificador já pertence a outro lote.')
                return jsonify(id=previous['id']), 200
            recipe = conn.execute('''SELECT r.*,i.stock,i.unit_cost,i.active,i.name FROM production_recipes r JOIN ingredients i ON i.id=r.ingredient_id
                WHERE r.store_id=? AND r.output_id=?''', (g.store['id'], iid)).fetchall()
            if not recipe or not output['active'] or output['stock'] + quantity > 10**9:
                abort(409, description='Cadastre a ficha de produção e confira o saldo do resultado.')
            demands = [(r, (r['quantity'] * quantity + 999) // 1000) for r in recipe]
            if any(not r['active'] or amount > r['stock'] for r, amount in demands):
                abort(409, description='Estoque insuficiente para produzir este lote.')
            bid = conn.execute('INSERT INTO production_batches(store_id,output_id,quantity,actor_id,created_at,key,payload_hash) VALUES(?,?,?,?,?,?,?)',
                (g.store['id'], iid, quantity, g.user['id'], h.now(), key, digest)).lastrowid
            cost = None if any(r['unit_cost'] is None for r in recipe) else sum((amount * r['unit_cost'] + 500) // 1000 for r, amount in demands)
            for r, amount in demands:
                conn.execute('UPDATE ingredients SET stock=stock-? WHERE id=?', (amount, r['ingredient_id']))
                conn.execute('INSERT INTO ingredient_movements(store_id,ingredient_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                    (g.store['id'], r['ingredient_id'], -amount, r['stock'] - amount, 'Produção #' + str(bid), h.now()))
            new_cost = None if cost is None or (output['stock'] and output['unit_cost'] is None) else (
                ((output['stock'] * (output['unit_cost'] or 0) + cost * 1000) + (output['stock'] + quantity)//2) // (output['stock'] + quantity))
            conn.execute('UPDATE ingredients SET stock=stock+?,unit_cost=? WHERE id=?', (quantity, new_cost, iid))
            conn.execute('INSERT INTO ingredient_movements(store_id,ingredient_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                (g.store['id'], iid, quantity, output['stock'] + quantity, 'Produção #' + str(bid), h.now()))
        return jsonify(id=bid), 201
