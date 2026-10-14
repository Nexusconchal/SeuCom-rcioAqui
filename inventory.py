"""Fichas técnicas em milésimos de kg/l/un, sem arredondamento de estoque."""
from collections import defaultdict
from types import SimpleNamespace

from flask import abort, g, jsonify


def recipe_map(conn, sid):
    result = defaultdict(list)
    for row in conn.execute("""SELECT r.product_id,r.ingredient_id,r.quantity,i.name,i.unit,i.stock,i.unit_cost,i.active
            FROM recipes r JOIN ingredients i ON i.id=r.ingredient_id WHERE r.store_id=?""", (sid,)):
        result[row['product_id']].append(dict(row))
    return result


def recipe_info(lines):
    if not lines:
        return None, None
    capacity = min(i['stock'] // i['quantity'] if i['active'] else 0 for i in lines)
    cost = None if any(i['unit_cost'] is None for i in lines) else sum(
        (i['quantity'] * i['unit_cost'] + 500) // 1000 for i in lines)
    return capacity, cost


def ingredient_demand(recipes, quantities):
    demand = defaultdict(int)
    ingredients = {}
    for pid, quantity in quantities.items():
        for ingredient in recipes.get(pid, []):
            demand[ingredient['ingredient_id']] += ingredient['quantity'] * quantity
            ingredients[ingredient['ingredient_id']] = ingredient
    for iid, quantity in demand.items():
        if not ingredients[iid]['active'] or quantity > ingredients[iid]['stock']:
            abort(409, description=f"Ingrediente insuficiente: {ingredients[iid]['name']}.")
    return demand


def reserve_ingredients(conn, sid, quantities, oid, number, stamp):
    demand = ingredient_demand(recipe_map(conn, sid), quantities)
    for iid, amount in demand.items():
        conn.execute('UPDATE ingredients SET stock=stock-? WHERE id=? AND store_id=?', (amount, iid, sid))
        balance = conn.execute('SELECT stock FROM ingredients WHERE id=?', (iid,)).fetchone()[0]
        conn.execute('''INSERT INTO ingredient_movements(store_id,ingredient_id,order_id,delta,balance,reason,created_at)
            VALUES(?,?,?,?,?,?,?)''', (sid, iid, oid, -amount, balance, 'Venda #' + str(number), stamp))


def restore_ingredients(conn, sid, oid, number, stamp):
    # Restore exactly what was reserved, even if the recipe has since changed.
    movements = conn.execute('SELECT ingredient_id,delta FROM ingredient_movements WHERE order_id=? AND delta<0', (oid,)).fetchall()
    for move in movements:
        amount, iid = -move['delta'], move['ingredient_id']
        conn.execute('UPDATE ingredients SET stock=stock+? WHERE id=? AND store_id=?', (amount, iid, sid))
        balance = conn.execute('SELECT stock FROM ingredients WHERE id=?', (iid,)).fetchone()[0]
        conn.execute('''INSERT INTO ingredient_movements(store_id,ingredient_id,order_id,delta,balance,reason,created_at)
            VALUES(?,?,?,?,?,?,?)''', (sid, iid, oid, amount, balance, 'Cancelamento #' + str(number), stamp))


def register_inventory(app, helpers):
    h = SimpleNamespace(**helpers)

    @app.get('/api/admin/ingredients')
    @h.owner
    def ingredients_list():
        sid = g.store['id']
        recipes = recipe_map(h.db(), sid)
        products = h.rows('SELECT id,name,price,unit_cost,active FROM products WHERE store_id=? ORDER BY name', (sid,))
        for product in products:
            product['recipe'] = recipes.get(product['id'], [])
            product['capacity'], product['recipe_cost'] = recipe_info(product['recipe'])
        return jsonify(ingredients=h.rows('SELECT * FROM ingredients WHERE store_id=? ORDER BY active DESC,name', (sid,)),
            products=products, movements=h.rows('''SELECT m.*,i.name,i.unit FROM ingredient_movements m JOIN ingredients i
                ON i.id=m.ingredient_id WHERE m.store_id=? ORDER BY m.id DESC LIMIT 100''', (sid,)))

    @app.post('/api/admin/ingredients')
    @h.owner
    def ingredient_add():
        value = h.data()
        name = h.text(value, 'name', 2, 100)
        unit = value.get('unit')
        if unit not in ('kg', 'l', 'un'):
            abort(400, description='Escolha kg, litro ou unidade.')
        stock = h.integer(value, 'stock', maximum=10**9)
        low = h.integer(value, 'low_stock', maximum=10**9)
        cost = None if value.get('unit_cost') is None else h.integer(value, 'unit_cost')
        with h.transaction() as conn:
            iid = conn.execute('INSERT INTO ingredients(store_id,name,unit,stock,low_stock,unit_cost) VALUES(?,?,?,?,?,?)',
                (g.store['id'], name, unit, stock, low, cost)).lastrowid
            if stock:
                conn.execute('''INSERT INTO ingredient_movements(store_id,ingredient_id,delta,balance,reason,created_at)
                    VALUES(?,?,?,?,?,?)''', (g.store['id'], iid, stock, stock, 'Estoque inicial', h.now()))
        return jsonify(id=iid), 201

    @app.patch('/api/admin/ingredients/<int:iid>')
    @h.owner
    def ingredient_update(iid):
        value = h.data()
        with h.transaction() as conn:
            current = h.owned('ingredients', iid)
            # Unit and balance are immutable here: use a justified movement for stock.
            cost = current['unit_cost'] if 'unit_cost' not in value else (
                None if value['unit_cost'] is None else h.integer(value, 'unit_cost'))
            conn.execute('UPDATE ingredients SET name=?,low_stock=?,unit_cost=?,active=? WHERE id=? AND store_id=?',
                (h.text(value, 'name', 2, 100) if 'name' in value else current['name'],
                 h.integer(value, 'low_stock', current['low_stock'], maximum=10**9), cost,
                 h.boolean(value, 'active', bool(current['active'])), iid, g.store['id']))
        return jsonify(ok=True)

    @app.post('/api/admin/ingredients/<int:iid>/adjust')
    @h.owner
    def ingredient_adjust(iid):
        value = h.data()
        delta = h.integer(value, 'delta', minimum=-10**9, maximum=10**9)
        reason = h.text(value, 'reason', 3, 200)
        if not delta:
            abort(400, description='Informe uma quantidade diferente de zero.')
        with h.transaction() as conn:
            current = h.owned('ingredients', iid)
            balance = current['stock'] + delta
            if not 0 <= balance <= 10**9:
                abort(400, description='A movimentação deixa o saldo fora do limite permitido.')
            conn.execute('UPDATE ingredients SET stock=? WHERE id=? AND store_id=?', (balance, iid, g.store['id']))
            conn.execute('''INSERT INTO ingredient_movements(store_id,ingredient_id,delta,balance,reason,created_at)
                VALUES(?,?,?,?,?,?)''', (g.store['id'], iid, delta, balance, reason, h.now()))
        return jsonify(balance=balance)

    @app.put('/api/admin/products/<int:pid>/recipe')
    @h.owner
    def recipe_save(pid):
        value = h.data()
        lines = value.get('ingredients')
        if not isinstance(lines, list) or len(lines) > 50:
            abort(400, description='Ficha técnica inválida.')
        prepared, seen = [], set()
        with h.transaction() as conn:
            h.owned('products', pid)
            for line in lines:
                if not isinstance(line, dict):
                    abort(400, description='Ingrediente inválido.')
                iid = h.integer(line, 'ingredient_id', minimum=1)
                ingredient = h.owned('ingredients', iid)
                if iid in seen or not ingredient['active']:
                    abort(400, description='Use cada ingrediente ativo uma vez na receita.')
                seen.add(iid)
                prepared.append((g.store['id'], pid, iid, h.integer(line, 'quantity', minimum=1, maximum=10**9)))
            conn.execute('DELETE FROM recipes WHERE product_id=? AND store_id=?', (pid, g.store['id']))
            for line in prepared:
                conn.execute('INSERT INTO recipes(store_id,product_id,ingredient_id,quantity) VALUES(?,?,?,?)', line)
        return jsonify(ok=True)
