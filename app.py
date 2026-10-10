"""SeuComércioAqui: loja pública, painel e API no mesmo serviço."""
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import click
from database import connect, initialize
from business import register_business
from storage import put_image
from flask import Flask, abort, g, jsonify, request, send_from_directory, session
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
ZONE = ZoneInfo("America/Sao_Paulo")
STATUSES = {"new": {"preparing", "cancelled"}, "preparing": {"ready", "cancelled"},
            "ready": {"delivering", "completed", "cancelled"}, "delivering": {"completed", "cancelled"},
            "completed": set(), "cancelled": set()}
LABELS = {"new": "Novo", "preparing": "Em preparo", "ready": "Pronto",
          "delivering": "Saiu para entrega", "completed": "Concluído", "cancelled": "Cancelado"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static")
    production = os.getenv("APP_ENV") == "production"
    key = os.getenv("SECRET_KEY", "")
    if production and len(key) < 32:
        raise RuntimeError("SECRET_KEY precisa ter ao menos 32 caracteres em produção.")
    app.config.update(
        SECRET_KEY=key or secrets.token_hex(32), DATABASE_PATH=os.getenv("DATABASE_PATH", str(BASE / "instance" / "seucomercio.sqlite3")),
        DATABASE_URL=os.getenv("DATABASE_URL", ""), DATABASE_SCHEMA=os.getenv("DATABASE_SCHEMA", "seucomercio"),
        STORAGE_UPLOAD_URL=os.getenv("STORAGE_UPLOAD_URL", ""), STORAGE_UPLOAD_TOKEN=os.getenv("STORAGE_UPLOAD_TOKEN", ""),
        STORAGE_PUBLIC_URL=os.getenv("STORAGE_PUBLIC_URL", ""),
        UPLOAD_DIR=os.getenv("UPLOAD_DIR", str(BASE / "instance" / "uploads")),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        MAX_FORM_PARTS=20, ALLOW_REGISTRATION=os.getenv("ALLOW_REGISTRATION", "1") == "1",
        PUBLIC_URL=(os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/"), RATE_LIMIT_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)
    hosts = os.getenv("TRUSTED_HOSTS", "")
    if hosts:
        app.config["TRUSTED_HOSTS"] = [h.strip() for h in hosts.split(",") if h.strip()]
    if os.getenv("TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0)
    if production and os.getenv("RENDER") and not app.config["DATABASE_URL"]:
        raise RuntimeError("Render exige DATABASE_URL para preservar os dados.")
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    initialize(app.config)

    def db():
        if "db" not in g:
            g.db = connect(app.config)
        return g.db

    @contextmanager
    def transaction():
        conn = db()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def one(sql, params=()):
        return db().execute(sql, params).fetchone()

    def rows(sql, params=()):
        return [dict(r) for r in db().execute(sql, params).fetchall()]

    def text(data, field, minimum=0, maximum=200):
        value = data.get(field, "")
        if not isinstance(value, str):
            abort(400, description=f"Campo {field} inválido.")
        value = value.strip()
        if not minimum <= len(value) <= maximum:
            abort(400, description=f"Preencha {field} com {minimum} a {maximum} caracteres.")
        return value

    def integer(data, field, default=0, minimum=0, maximum=100_000_000):
        value = data.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            abort(400, description=f"Campo {field} inválido.")
        return value

    def boolean(data, field, default=False):
        value = data.get(field, default)
        if not isinstance(value, bool):
            abort(400, description=f"Campo {field} inválido.")
        return int(value)

    def image_url(value):
        if not isinstance(value, str) or len(value) > 2000:
            abort(400, description="Imagem inválida.")
        if not value:
            return ""
        if re.fullmatch(r"/media/[a-f0-9]{32}\.webp", value):
            return value
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            abort(400, description="Use uma imagem HTTPS ou envie uma foto.")
        return value

    def data():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400, description="Envie um objeto JSON válido.")
        return value

    def limited(name, limit, seconds=600, per_ip=True):
        if not app.config["RATE_LIMIT_ENABLED"]:
            return
        stamp = int(time.time())
        key_hash = hashlib.sha256(f"{name}:{request.remote_addr if per_ip else 'key'}".encode()).hexdigest()
        with transaction() as conn:
            current = conn.execute("SELECT * FROM rate_limits WHERE key=?", (key_hash,)).fetchone()
            if current and current["resets_at"] > stamp:
                if current["count"] >= limit:
                    abort(429, description="Muitas tentativas. Aguarde alguns minutos.")
                conn.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key_hash,))
            else:
                conn.execute("INSERT INTO rate_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET count=excluded.count,resets_at=excluded.resets_at", (key_hash, 1, stamp + seconds))
            conn.execute("DELETE FROM rate_limits WHERE resets_at<?", (stamp - 600,))

    def owner(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = one("SELECT id,name,email,auth_version,platform_admin FROM users WHERE id=?", (session.get("uid", -1),))
            if not user or user["auth_version"] != session.get("version"):
                abort(401, description="Entre na sua conta.")
            store = one("SELECT * FROM stores WHERE owner_id=?", (user["id"],))
            if not store:
                abort(404, description="Loja não encontrada.")
            g.user, g.store = user, store
            return fn(*args, **kwargs)
        return wrapped

    def owned(table, item_id):
        record = one(f"SELECT * FROM {table} WHERE id=? AND store_id=?", (item_id, g.store["id"]))
        if not record:
            abort(404, description="Registro não encontrado.")
        return record

    def store_dict(store, private=False):
        value = dict(store)
        value["payments"] = json.loads(value["payments"])
        value["open"] = bool(value["open"])
        if not private:
            for key in ("owner_id", "created_at", "commission_bps", "monthly_fee", "payment_fees", "default_delivery_cost", "enabled"):
                value.pop(key, None)
        return value

    def product_dict(product, private=False):
        value = dict(product)
        value["extras"] = json.loads(value["extras"])
        value["active"], value["featured"] = bool(value["active"]), bool(value["featured"])
        if not private:
            value.pop("unit_cost", None)
            value.pop("low_stock", None)
            value["extras"] = [{k:v for k,v in x.items() if k!='unit_cost'} for x in value["extras"]]
        return value

    def order_dict(order, private=True):
        value = dict(order)
        value["items"] = rows("SELECT id,name,product_id,quantity,unit_price,unit_cost,extras,notes FROM order_items WHERE order_id=?", (order["id"],))
        for item in value["items"]:
            item["extras"] = json.loads(item["extras"])
            item["extras"] = [{k:v for k,v in x.items() if k!='unit_cost'} for x in item["extras"]]
            if not private:
                item.pop("unit_cost", None)
                item.pop("id", None)
        value["events"] = rows("SELECT status,created_at FROM order_events WHERE order_id=? ORDER BY id", (order["id"],))
        value["status_label"] = LABELS[value["status"]]
        if private:
            value["driver_name"] = (one("SELECT name FROM drivers WHERE id=?", (value["driver_id"],)) or {"name": ""})["name"]
        else:
            value = {k: value[k] for k in ("number", "mode", "payment", "subtotal", "discount", "delivery_fee",
                "total", "paid", "status", "status_label", "items", "events", "created_at")}
        for key in ("tracking_hash", "payload_hash", "idempotency_key"):
            value.pop(key, None)
        return value

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop("db", None)
        if connection:
            connection.close()

    @app.before_request
    def protect():
        if request.path.startswith("/api/v1/"):
            app.extensions["partner_auth"]()
            return
        if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            expected = session.get("csrf", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not secrets.compare_digest(expected, supplied):
                abort(403, description="Sua sessão expirou. Atualize a página.")
            origin = request.headers.get("Origin")
            allowed = app.config["PUBLIC_URL"] or request.host_url.rstrip("/")
            if origin and origin.rstrip("/") != allowed:
                abort(403, description="Origem da requisição inválida.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.path.startswith("/api/") or request.path.startswith("/pedido/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return send_from_directory(app.static_folder, "index.html"), error.code

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error):
        return jsonify(error="Este cadastro já existe ou possui dados inválidos."), 409

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Falha no servidor")
        return jsonify(error="Não foi possível concluir. Tente novamente."), 500

    @app.get("/health")
    def health():
        one("SELECT 1")
        return jsonify(status="ok", service="SeuComércioAqui")

    @app.get("/")
    @app.get("/entrar")
    @app.get("/painel")
    @app.get("/plataforma")
    @app.get("/loja/<slug>")
    @app.get("/pedido/<token>")
    def page(**kwargs):
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/media/<filename>")
    def media(filename):
        if not re.fullmatch(r"[a-f0-9]{32}\.webp", filename):
            abort(404)
        return send_from_directory(app.config["UPLOAD_DIR"], filename, mimetype="image/webp", max_age=31536000)

    @app.get("/api/session")
    def get_session():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        user = one("SELECT id,name,email,auth_version,platform_admin FROM users WHERE id=?", (session.get("uid", -1),))
        authenticated = bool(user and user["auth_version"] == session.get("version"))
        return jsonify(csrf=session["csrf"], user={"name": user["name"], "email": user["email"], "platform_admin": bool(user["platform_admin"])} if authenticated else None,
                       registration=app.config["ALLOW_REGISTRATION"])

    def establish(user):
        session.clear()
        session.update(uid=user["id"], version=user["auth_version"], csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return jsonify(csrf=session["csrf"], user={"name": user["name"], "email": user["email"], "platform_admin": bool(user["platform_admin"])})

    @app.post("/api/auth/register")
    def register():
        limited("register", 5, 3600)
        if not app.config["ALLOW_REGISTRATION"]:
            abort(403, description="Novos cadastros estão fechados.")
        value = data()
        name, email = text(value, "name", 2, 100), text(value, "email", 5, 254).lower()
        password, store_name = text(value, "password", 10, 128), text(value, "store_name", 2, 100)
        slug = text(value, "slug", 3, 60).lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or slug in ("admin", "api", "painel", "entrar", "static", "media"):
            abort(400, description="Use letras sem acentos, números e hífens no endereço da loja.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            abort(400, description="E-mail inválido.")
        hashed = generate_password_hash(password)
        with transaction() as conn:
            uid = conn.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                               (name, email, hashed, now())).lastrowid
            sid = conn.execute("INSERT INTO stores(owner_id,name,slug,created_at) VALUES(?,?,?,?)",
                               (uid, store_name, slug, now())).lastrowid
            conn.execute("INSERT INTO categories(store_id,name) VALUES(?,?)", (sid, "Destaques"))
        return establish(one("SELECT * FROM users WHERE id=?", (uid,))), 201

    @app.post("/api/auth/login")
    def login():
        limited("login", 15)
        value = data()
        email, password = text(value, "email", 1, 254).lower(), text(value, "password", 1, 128)
        user = one("SELECT * FROM users WHERE email=?", (email,))
        if not user or not check_password_hash(user["password_hash"], password):
            abort(401, description="E-mail ou senha incorretos.")
        return establish(user)

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.put("/api/auth/password")
    @owner
    def change_password():
        value = data()
        old, new = text(value, "current_password", 1, 128), text(value, "new_password", 10, 128)
        user = one("SELECT * FROM users WHERE id=?", (g.user["id"],))
        if not check_password_hash(user["password_hash"], old):
            abort(400, description="Senha atual incorreta.")
        db().execute("UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?",
                     (generate_password_hash(new), g.user["id"]))
        return establish(one("SELECT * FROM users WHERE id=?", (g.user["id"],)))

    @app.get("/api/store/<slug>")
    def catalog(slug):
        store = one("SELECT * FROM stores WHERE slug=?", (slug,))
        if not store:
            abort(404, description="Esta loja não foi encontrada.")
        return jsonify(store=store_dict(store), categories=rows("SELECT id,name,position FROM categories WHERE store_id=? ORDER BY position,id", (store["id"],)),
                       products=[product_dict(p) for p in db().execute("SELECT * FROM products WHERE store_id=? AND active=1 ORDER BY featured DESC,position,id", (store["id"],))])

    def coupon_discount(conn, sid, code, subtotal):
        if not code:
            return 0, None
        coupon = conn.execute("SELECT * FROM coupons WHERE store_id=? AND code=? AND active=1", (sid, code.upper())).fetchone()
        today = datetime.now(ZONE).date().isoformat()
        if not coupon or (coupon["expires"] and coupon["expires"] < today) or (coupon["max_uses"] is not None and coupon["uses"] >= coupon["max_uses"]):
            abort(400, description="Cupom inválido, vencido ou esgotado.")
        if subtotal < coupon["minimum"]:
            abort(400, description=f"Este cupom exige R$ {coupon['minimum']/100:.2f} em produtos.")
        discount = subtotal * coupon["value"] // 100 if coupon["kind"] == "percent" else coupon["value"]
        return min(discount, subtotal), coupon["id"]

    def price_items(conn, store, items):
        subtotal, quantities, prepared = 0, {}, []
        for item in items:
            if not isinstance(item, dict):
                abort(400, description="Produto inválido.")
            pid, quantity = integer(item, "product_id", minimum=1), integer(item, "quantity", minimum=1, maximum=50)
            product = conn.execute("SELECT * FROM products WHERE id=? AND store_id=? AND active=1", (pid, store["id"])).fetchone()
            if not product:
                abort(400, description="Um produto não está mais disponível.")
            selected = item.get("option_ids", [])
            if not isinstance(selected, list) or len(selected) > 12 or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
                abort(400, description="Complementos inválidos.")
            available = {x["id"]: x for x in json.loads(product["extras"])}
            if any(x not in available for x in selected):
                abort(400, description="Um complemento não está mais disponível.")
            extras = [available[x] for x in selected]
            unit = product["price"] + sum(x["price"] for x in extras)
            subtotal += quantity * unit
            quantities[pid] = quantities.get(pid, 0) + quantity
            prepared.append((product, quantity, unit, extras, text(item, "notes", 0, 200)))
        return subtotal, quantities, prepared

    @app.post("/api/store/<slug>/quote")
    def quote(slug):
        limited("quote", 120)
        value = data()
        store = one("SELECT * FROM stores WHERE slug=?", (slug,))
        if not store:
            abort(404, description="Loja não encontrada.")
        if not store["open"] or not store["enabled"]:
            abort(409, description="A loja está fechada no momento.")
        mode, items = value.get("mode"), value.get("items")
        if mode not in ("delivery", "pickup") or not isinstance(items, list) or not 1 <= len(items) <= 50:
            abort(400, description="Sacola inválida.")
        subtotal, quantities, prepared = price_items(db(), store, items)
        for product, quantity, unit, extras, notes in prepared:
            if product["stock"] is not None and quantities[product["id"]] > product["stock"]:
                abort(409, description=f"Estoque insuficiente: {product['name']}.")
        if subtotal < store["minimum_order"]:
            abort(400, description=f"Pedido mínimo de R$ {store['minimum_order']/100:.2f} em produtos.")
        discount, _ = coupon_discount(db(), store["id"], text(value, "coupon", 0, 30).upper(), subtotal)
        fee = store["delivery_fee"] if mode == "delivery" else 0
        return jsonify(subtotal=subtotal, discount=discount, delivery_fee=fee, total=subtotal-discount+fee)

    @app.post("/api/store/<slug>/orders")
    def create_order(slug):
        limited("order", 30)
        value = data()
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}", key):
            abort(400, description="Identificador do pedido inválido.")
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        customer, phone = text(value, "customer", 2, 100), text(value, "phone", 10, 20)
        if not re.fullmatch(r"[0-9+() \-]{10,20}", phone) or len(re.sub(r"\D", "", phone)) not in (10, 11, 12, 13):
            abort(400, description="Informe um telefone com DDD.")
        mode, payment = value.get("mode"), value.get("payment")
        if mode not in ("delivery", "pickup"):
            abort(400, description="Escolha entrega ou retirada.")
        address = text(value, "address", 8 if mode == "delivery" else 0, 400)
        notes = text(value, "notes", 0, 500)
        coupon_code = text(value, "coupon", 0, 30).upper()
        change_for = value.get("change_for")
        if change_for is not None:
            change_for = integer(value, "change_for", minimum=0, maximum=1_000_000)
        items = value.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            abort(400, description="Adicione produtos à sacola.")
        with transaction() as conn:
            store = conn.execute("SELECT * FROM stores WHERE slug=?", (slug,)).fetchone()
            if not store:
                abort(404, description="Loja não encontrada.")
            previous = conn.execute("SELECT * FROM orders WHERE store_id=? AND idempotency_key=?", (store["id"], key)).fetchone()
            if previous:
                if previous["payload_hash"] != digest:
                    abort(409, description="Este identificador já pertence a outro pedido.")
                return jsonify(token=previous["tracking_token"], number=previous["number"], total=previous["total"]), 200
            if (not store["open"] and not getattr(g,'manual_order',False)) or not store["enabled"]:
                abort(409, description="A loja está fechada no momento.")
            if payment not in json.loads(store["payments"]):
                abort(400, description="Forma de pagamento indisponível.")
            subtotal, quantities, prepared = price_items(conn, store, items)
            if subtotal < store["minimum_order"]:
                abort(400, description=f"Pedido mínimo de R$ {store['minimum_order']/100:.2f} em produtos.")
            for pid, quantity in quantities.items():
                product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                if product["stock"] is not None:
                    if quantity > product["stock"]:
                        abort(409, description=f"Estoque insuficiente: {product['name']}.")
                    conn.execute("UPDATE products SET stock=stock-? WHERE id=?", (quantity, pid))
            discount, coupon_id = coupon_discount(conn, store["id"], coupon_code, subtotal)
            fee = store["delivery_fee"] if mode == "delivery" else 0
            total = subtotal - discount + fee
            if "expected_total" in value and integer(value, "expected_total", maximum=10**14) != total:
                abort(409, description="O preço mudou. Confira o novo total antes de confirmar.")
            if payment == "cash" and change_for is not None and change_for < total:
                abort(400, description="O valor para troco deve cobrir o total.")
            token, stamp = secrets.token_urlsafe(32), now()
            number = conn.execute("SELECT COALESCE(MAX(number),1000)+1 FROM orders WHERE store_id=?", (store["id"],)).fetchone()[0]
            oid = conn.execute("""INSERT INTO orders(store_id,number,tracking_hash,customer,phone,mode,address,payment,change_for,notes,
                subtotal,discount,delivery_fee,total,coupon_id,idempotency_key,payload_hash,tracking_token,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (store["id"], number, hashlib.sha256(token.encode()).hexdigest(),
                customer, phone, mode, address if mode == "delivery" else "", payment, change_for if payment == "cash" else None, notes,
                subtotal, discount, fee, total, coupon_id, key, digest, token, stamp, stamp)).lastrowid
            fees=json.loads(store['payment_fees'])
            conn.execute("UPDATE orders SET delivery_cost=?,payment_fee=?,platform_fee=?,source=? WHERE id=?",
                (store['default_delivery_cost'] if mode=='delivery' else 0,
                 (total*fees.get(payment,0)+5000)//10000,
                 ((subtotal-discount)*store['commission_bps']+5000)//10000,
                 'counter' if getattr(g,'manual_order',False) else 'web',oid))
            for product, quantity, unit, extras, item_notes in prepared:
                known=product['unit_cost'] is not None and all(x.get('unit_cost') is not None for x in extras)
                cost=product['unit_cost']+sum(x['unit_cost'] for x in extras) if known else None
                conn.execute("INSERT INTO order_items(order_id,product_id,name,quantity,unit_price,unit_cost,extras,notes) VALUES(?,?,?,?,?,?,?,?)",
                             (oid, product["id"], product["name"], quantity, unit, cost, json.dumps([{k:v for k,v in x.items() if k!='unit_cost'} for x in extras]), item_notes))
            for pid, quantity in quantities.items():
                balance=conn.execute('SELECT stock FROM products WHERE id=?',(pid,)).fetchone()[0]
                if balance is not None:
                    conn.execute('INSERT INTO stock_movements(store_id,product_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                        (store['id'],pid,-quantity,balance,'Venda #'+str(number),stamp))
            conn.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)", (oid, "new", stamp))
            if coupon_id:
                conn.execute("UPDATE coupons SET uses=uses+1 WHERE id=?", (coupon_id,))
        return jsonify(token=token, number=number, total=total), 201

    @app.post('/api/admin/orders')
    @owner
    def manual_order():
        g.manual_order=True
        return create_order(g.store['slug'])

    @app.get("/api/track/<token>")
    def track(token):
        if not 30 <= len(token) <= 100:
            abort(404, description="Pedido não encontrado.")
        order = one("SELECT * FROM orders WHERE tracking_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        if not order:
            abort(404, description="Pedido não encontrado.")
        store = one("SELECT * FROM stores WHERE id=?", (order["store_id"],))
        return jsonify(order=order_dict(order, False), store=store_dict(store))

    @app.get("/api/admin/store")
    @owner
    def admin_store():
        return jsonify(store=store_dict(g.store, True))

    @app.put("/api/admin/store")
    @owner
    def update_store():
        value = data()
        name, description = text(value, "name", 2, 100), text(value, "description", 0, 500)
        phone, address = text(value, "phone", 0, 20), text(value, "address", 0, 400)
        color = text(value, "color", 7, 7)
        if not re.fullmatch(r"#[a-fA-F0-9]{6}", color):
            abort(400, description="Cor inválida.")
        payments = value.get("payments", [])
        if not g.store['enabled'] and value.get('open'):
            abort(403,description='Loja suspensa pela plataforma. Entre em contato com o suporte.')
        if not isinstance(payments, list) or not payments or any(p not in ("pix", "cash", "card") for p in payments):
            abort(400, description="Selecione ao menos uma forma de pagamento.")
        pix = text(value, "pix_key", 0, 200)
        if "pix" in payments and not pix:
            abort(400, description="Informe sua chave Pix ou desative Pix.")
        db().execute("""UPDATE stores SET name=?,description=?,phone=?,address=?,color=?,logo=?,banner=?,open=?,
            delivery_fee=?,minimum_order=?,delivery_minutes=?,pix_key=?,payments=? WHERE id=?""",
            (name, description, phone, address, color, image_url(value.get("logo", "")), image_url(value.get("banner", "")),
             boolean(value, "open"), integer(value, "delivery_fee"), integer(value, "minimum_order"),
             text(value, "delivery_minutes", 2, 40), pix, json.dumps(list(dict.fromkeys(payments))), g.store["id"]))
        return jsonify(store=store_dict(one("SELECT * FROM stores WHERE id=?", (g.store["id"],)), True))

    @app.post("/api/admin/upload")
    @owner
    def upload():
        file = request.files.get("file")
        if not file:
            abort(400, description="Selecione uma imagem.")
        try:
            Image.MAX_IMAGE_PIXELS = 20_000_000
            picture = Image.open(file.stream)
            if picture.format not in ("PNG", "JPEG", "WEBP") or picture.width * picture.height > 20_000_000:
                abort(400, description="Use PNG, JPEG ou WebP com até 20 megapixels.")
            picture.load()
            picture = ImageOps.exif_transpose(picture)
            picture.thumbnail((1800, 1800))
            picture = picture.convert("RGB")
            filename = secrets.token_hex(16) + ".webp"
            output = io.BytesIO()
            picture.save(output, "WEBP", quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
            abort(400, description="Envie uma foto PNG, JPEG ou WebP válida.")
        if app.config["STORAGE_UPLOAD_URL"]:
            url = put_image(app.config, g.store["id"], filename, output.getvalue())
        else:
            (Path(app.config["UPLOAD_DIR"]) / filename).write_bytes(output.getvalue())
            url = "/media/" + filename
        return jsonify(url=url), 201

    @app.get("/api/admin/products")
    @owner
    def admin_products():
        return jsonify(products=[product_dict(p, True) for p in db().execute("SELECT * FROM products WHERE store_id=? ORDER BY position,id", (g.store["id"],))],
                       categories=rows("SELECT * FROM categories WHERE store_id=? ORDER BY position,id", (g.store["id"],)))

    @app.post("/api/admin/categories")
    @owner
    def create_category():
        value = data()
        cid = db().execute("INSERT INTO categories(store_id,name,position) VALUES(?,?,?)",
                           (g.store["id"], text(value, "name", 1, 80), integer(value, "position"))).lastrowid
        return jsonify(id=cid), 201

    @app.delete("/api/admin/categories/<int:cid>")
    @owner
    def delete_category(cid):
        owned("categories", cid)
        with transaction() as conn:
            conn.execute("UPDATE products SET category_id=NULL WHERE category_id=? AND store_id=?", (cid, g.store["id"]))
            conn.execute("DELETE FROM categories WHERE id=?", (cid,))
        return jsonify(ok=True)

    def product_fields(value):
        category = value.get("category_id")
        if category is not None:
            if not isinstance(category, int) or isinstance(category, bool):
                abort(400, description="Categoria inválida.")
            owned("categories", category)
        stock = value.get("stock")
        if stock is not None:
            stock = integer(value, "stock", minimum=0, maximum=1_000_000)
        extras = value.get("extras", [])
        if not isinstance(extras, list) or len(extras) > 12:
            abort(400, description="Use até 12 complementos.")
        sanitized, seen = [], set()
        for extra in extras:
            if not isinstance(extra, dict):
                abort(400, description="Complemento inválido.")
            eid = text(extra, "id", 1, 40)
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", eid) or eid in seen:
                abort(400, description="Identificador de complemento inválido ou duplicado.")
            seen.add(eid)
            sanitized.append({"id": eid, "name": text(extra, "name", 1, 80), "price": integer(extra, "price"),
                              "unit_cost":None if extra.get('unit_cost') is None else integer(extra,'unit_cost')})
        return (category, text(value, "name", 2, 120), text(value, "description", 0, 500),
                integer(value, "price", minimum=1), image_url(value.get("image", "")), boolean(value, "active", True),
                boolean(value, "featured"), stock, json.dumps(sanitized), integer(value, "position"),
                None if value.get('unit_cost') is None else integer(value,'unit_cost'), integer(value,'low_stock',default=5,maximum=1000000))

    @app.post("/api/admin/products")
    @owner
    def create_product():
        fields = product_fields(data())
        with transaction() as conn:
            pid = conn.execute("""INSERT INTO products(store_id,category_id,name,description,price,image,active,featured,stock,extras,position,unit_cost,low_stock)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (g.store["id"], *fields)).lastrowid
            if fields[7] is not None:
                conn.execute('INSERT INTO stock_movements(store_id,product_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                             (g.store['id'],pid,fields[7],fields[7],'Estoque inicial',now()))
        return jsonify(id=pid), 201

    @app.put("/api/admin/products/<int:pid>")
    @owner
    def update_product(pid):
        value=data()
        fields = list(product_fields(value))
        with transaction() as conn:
            previous=owned('products',pid)
            if 'expected_stock' in value:
                expected=value['expected_stock']
                if expected is not None:
                    expected=integer(value,'expected_stock',maximum=1000000)
                if fields[7]==expected:
                    fields[7]=previous['stock']
                elif previous['stock']!=expected:
                    abort(409,description='O estoque mudou enquanto você editava. Atualize o cadastro antes de ajustar a quantidade.')
            conn.execute("""UPDATE products SET category_id=?,name=?,description=?,price=?,image=?,active=?,featured=?,
                         stock=?,extras=?,position=?,unit_cost=?,low_stock=? WHERE id=? AND store_id=?""", (*fields, pid, g.store["id"]))
            if fields[7] is not None and fields[7]!=previous['stock']:
                conn.execute('INSERT INTO stock_movements(store_id,product_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                             (g.store['id'],pid,fields[7]-(previous['stock'] or 0),fields[7],'Ajuste no cadastro',now()))
        return jsonify(ok=True)

    @app.delete("/api/admin/products/<int:pid>")
    @owner
    def archive_product(pid):
        owned("products", pid)
        db().execute("UPDATE products SET active=0 WHERE id=? AND store_id=?", (pid, g.store["id"]))
        return jsonify(ok=True)

    @app.get("/api/admin/orders")
    @owner
    def admin_orders():
        status = request.args.get("status", "")
        if status and status not in STATUSES:
            abort(400, description="Status inválido.")
        sql, params = "SELECT * FROM orders WHERE store_id=?", [g.store["id"]]
        if status:
            sql += " AND status=?"
            params.append(status)
        else:
            sql += " AND (status NOT IN ('completed','cancelled') OR created_at>=?)"
            params.append((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds"))
        return jsonify(orders=[order_dict(o) for o in db().execute(sql + " ORDER BY id DESC LIMIT 500", params)])

    @app.patch("/api/admin/orders/<int:oid>")
    @owner
    def update_order(oid):
        value = data()
        with transaction() as conn:
            order = owned("orders", oid)
            status = value.get("status", order["status"])
            if not isinstance(status, str) or status not in STATUSES:
                abort(400, description="Status inválido.")
            if status != order["status"]:
                if status not in STATUSES[order["status"]] or (order["mode"] == "pickup" and status == "delivering") or (order["mode"] == "delivery" and order["status"] == "ready" and status == "completed"):
                    abort(409, description="Esta mudança de status não é permitida.")
                if status == "cancelled":
                    for item in conn.execute("SELECT product_id,SUM(quantity) AS qty FROM order_items WHERE order_id=? GROUP BY product_id", (oid,)):
                        conn.execute("UPDATE products SET stock=stock+? WHERE id=? AND stock IS NOT NULL", (item["qty"], item["product_id"]))
                        balance=conn.execute('SELECT stock FROM products WHERE id=?',(item['product_id'],)).fetchone()[0]
                        if balance is not None:
                            conn.execute('INSERT INTO stock_movements(store_id,product_id,delta,balance,reason,created_at) VALUES(?,?,?,?,?,?)',
                                (g.store['id'],item['product_id'],item['qty'],balance,'Cancelamento #'+str(order['number']),now()))
                    if order["coupon_id"]:
                        conn.execute("UPDATE coupons SET uses=CASE WHEN uses>0 THEN uses-1 ELSE 0 END WHERE id=?", (order["coupon_id"],))
                conn.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)", (oid, status, now()))
            paid = value.get("paid", bool(order["paid"]))
            if not isinstance(paid, bool):
                abort(400, description="Pagamento inválido.")
            driver = value.get("driver_id", order["driver_id"])
            if driver is not None:
                if not isinstance(driver, int) or isinstance(driver, bool):
                    abort(400, description="Entregador inválido.")
                record = owned("drivers", driver)
                if not record["active"] and driver != order["driver_id"]:
                    abort(400, description="Entregador inativo.")
                if order["mode"] != "delivery":
                    abort(400, description="Retirada não usa entregador.")
            conn.execute("UPDATE orders SET status=?,paid=?,driver_id=?,updated_at=? WHERE id=?",
                         (status, int(paid), driver, now(), oid))
        return jsonify(order=order_dict(one("SELECT * FROM orders WHERE id=?", (oid,))))

    @app.get("/api/admin/drivers")
    @owner
    def drivers():
        return jsonify(drivers=rows("SELECT * FROM drivers WHERE store_id=? ORDER BY active DESC,name", (g.store["id"],)))

    @app.post("/api/admin/drivers")
    @owner
    def add_driver():
        value = data()
        did = db().execute("INSERT INTO drivers(store_id,name,phone,active) VALUES(?,?,?,?)",
                           (g.store["id"], text(value, "name", 2, 100), text(value, "phone", 0, 20), boolean(value, "active", True))).lastrowid
        return jsonify(id=did), 201

    @app.put("/api/admin/drivers/<int:did>")
    @owner
    def edit_driver(did):
        owned("drivers", did)
        value = data()
        db().execute("UPDATE drivers SET name=?,phone=?,active=? WHERE id=? AND store_id=?",
                     (text(value, "name", 2, 100), text(value, "phone", 0, 20), boolean(value, "active", True), did, g.store["id"]))
        return jsonify(ok=True)

    @app.get("/api/admin/coupons")
    @owner
    def coupons():
        return jsonify(coupons=rows("SELECT * FROM coupons WHERE store_id=? ORDER BY id DESC", (g.store["id"],)))

    @app.post("/api/admin/coupons")
    @owner
    def add_coupon():
        value = data()
        code = text(value, "code", 3, 30).upper()
        kind = value.get("kind")
        if not re.fullmatch(r"[A-Z0-9_-]+", code) or kind not in ("percent", "fixed"):
            abort(400, description="Cupom inválido.")
        amount = integer(value, "value", minimum=1, maximum=100 if kind == "percent" else 100_000_000)
        expires = text(value, "expires", 0, 10)
        if expires:
            try:
                datetime.strptime(expires, "%Y-%m-%d")
            except ValueError:
                abort(400, description="Validade inválida.")
        maximum = value.get("max_uses")
        if maximum is not None:
            maximum = integer(value, "max_uses", minimum=1, maximum=1_000_000)
        cid = db().execute("INSERT INTO coupons(store_id,code,kind,value,minimum,expires,max_uses) VALUES(?,?,?,?,?,?,?)",
                           (g.store["id"], code, kind, amount, integer(value, "minimum"), expires, maximum)).lastrowid
        return jsonify(id=cid), 201

    @app.patch("/api/admin/coupons/<int:cid>")
    @owner
    def toggle_coupon(cid):
        owned("coupons", cid)
        db().execute("UPDATE coupons SET active=? WHERE id=? AND store_id=?", (boolean(data(), "active"), cid, g.store["id"]))
        return jsonify(ok=True)

    def summary(days):
        midnight = datetime.now(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        start = (midnight - timedelta(days=days - 1)).astimezone(timezone.utc).isoformat(timespec="seconds")
        orders = rows("SELECT * FROM orders WHERE store_id=? AND created_at>=? AND status!='cancelled'", (g.store["id"], start))
        expenses = rows("SELECT * FROM expenses WHERE store_id=? AND created_at>=? ORDER BY id DESC", (g.store["id"], start))
        revenue = sum(o["total"] for o in orders if o["status"] == "completed")
        received = sum(o["total"] for o in orders if o["paid"])
        outgoing = sum(e["amount"] for e in expenses)
        chart = []
        for i in range(days):
            day = (midnight - timedelta(days=days - 1 - i)).date().isoformat()
            amount = sum(o["total"] for o in orders if o["status"] == "completed" and datetime.fromisoformat(o["created_at"]).astimezone(ZONE).date().isoformat() == day)
            chart.append({"date": day, "total": amount})
        completed = sum(o["status"] == "completed" for o in orders)
        return {"revenue": revenue, "received": received, "pending_payment": sum(o["total"] for o in orders if not o["paid"]),
                "expenses_total": outgoing, "balance": received - outgoing, "orders": len(orders),
                "completed": completed, "ticket": revenue // completed if completed else 0,
                "active": sum(o["status"] not in ("completed", "cancelled") for o in orders),
                "chart": chart, "expenses": expenses,
                "payments": [{"method": m, "total": sum(o["total"] for o in orders if o["paid"] and o["payment"] == m)} for m in ("pix", "cash", "card")]}

    @app.get("/api/admin/summary")
    @owner
    def get_summary():
        try:
            days = int(request.args.get("days", "7"))
        except ValueError:
            abort(400, description="Período inválido.")
        if days not in (1, 7, 30):
            abort(400, description="Use 1, 7 ou 30 dias.")
        return jsonify(summary(days))

    @app.post("/api/admin/expenses")
    @owner
    def add_expense():
        value = data()
        category=value.get('category','operating')
        if category not in ('operating','inventory'):
            abort(400,description='Categoria de despesa inválida.')
        eid = db().execute("INSERT INTO expenses(store_id,description,amount,created_at,category) VALUES(?,?,?,?,?)",
                           (g.store["id"], text(value, "description", 2, 200), integer(value, "amount", minimum=1), now(),category)).lastrowid
        return jsonify(id=eid), 201

    @app.delete("/api/admin/expenses/<int:eid>")
    @owner
    def delete_expense(eid):
        owned("expenses", eid)
        db().execute("DELETE FROM expenses WHERE id=? AND store_id=?", (eid, g.store["id"]))
        return jsonify(ok=True)

    @app.get("/api/admin/export")
    @owner
    def export_orders():
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Pedido", "Data UTC", "Cliente", "Status", "Pagamento", "Pago", "Total (R$)"])
        for order in db().execute("SELECT * FROM orders WHERE store_id=? ORDER BY id DESC", (g.store["id"],)):
            name = order["customer"]
            if name.startswith(("=", "+", "-", "@", "\t", "\r")):
                name = "'" + name
            writer.writerow([order["number"], order["created_at"], name, LABELS[order["status"]], order["payment"], "Sim" if order["paid"] else "Não", f"{order['total']/100:.2f}"])
        response = app.response_class("\ufeff" + output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = 'attachment; filename="pedidos.csv"'
        return response

    register_business(app, dict(db=db,one=one,rows=rows,owner=owner,owned=owned,data=data,text=text,integer=integer,
        boolean=boolean,transaction=transaction,limited=limited,order_dict=order_dict,now=now))

    @app.cli.command("seed-demo")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def seed_demo(email, password):
        """Cria Bistrô da Vila. Não instala senha padrão."""
        from seed import seed
        if len(password) < 10:
            raise click.ClickException("Use uma senha de ao menos 10 caracteres.")
        try:
            seed(db(), email, password)
        except sqlite3.IntegrityError as exc:
            raise click.ClickException("E-mail ou loja de demonstração já existe.") from exc
        click.echo("Loja criada. Entre em /entrar ou visite /loja/bistro-da-vila.")

    @app.cli.command("reset-password")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def reset_password(email, password):
        """Recuperação administrativa no servidor; invalida as sessões anteriores."""
        if len(password) < 10:
            raise click.ClickException("Use uma senha de ao menos 10 caracteres.")
        cursor = db().execute("UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE email=?",
                              (generate_password_hash(password), email.lower().strip()))
        if cursor.rowcount != 1:
            raise click.ClickException("Conta não encontrada.")
        click.echo("Senha redefinida.")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
