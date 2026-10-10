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
from notify import notify_store, vapid_keys
from payments import MercadoPago, PaymentError, seal, unseal
from billing import apply_exemptions, billing_ok, billing_state, first_billing_migration, register_billing
from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session
from markupsafe import escape
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
ZONE = ZoneInfo("America/Sao_Paulo")
STATUSES = {"new": {"preparing", "cancelled"}, "preparing": {"ready", "cancelled"},
            "ready": {"delivering", "completed", "cancelled"}, "delivering": {"completed", "cancelled"},
            "completed": set(), "cancelled": set()}
ROLE_LABELS = {"owner": "Dono", "manager": "Gerente", "cashier": "Caixa", "kitchen": "Cozinha"}
# O dono pode tudo. Os demais só acessam o que a função precisa (o servidor confere em cada chamada).
ROLE_BASE = {"admin_store", "merchant_notices", "change_password", "admin_orders", "admin_products", "drivers", "set_open",
             "push_key", "push_subscribe", "push_unsubscribe", "push_test"}
ROLE_ALLOWED = {
    "kitchen": ROLE_BASE | {"update_order"},
    "cashier": ROLE_BASE | {"update_order", "manual_order", "customers", "customer_orders", "get_summary", "add_expense",
                            "reviews", "store_qrcode", "coupons", "insights"},
}
MANAGER_DENY = {"mp_connect", "mp_disconnect", "billing_subscribe", "billing_cancel", "team_list", "team_add", "team_update", "team_password", "integrations", "create_key", "revoke_key",
                "rename_key", "delete_key", "rotate_key", "test_key", "finance_settings"}
LABELS = {"new": "Novo", "preparing": "Em preparo", "ready": "Pronto",
          "delivering": "Saiu para entrega", "completed": "Concluído", "cancelled": "Cancelado"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


PHONE_SQL = "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,' ',''),'-',''),'(',''),')',''),'+','')"


def phone_key(phone):
    """Telefone só com números e sem o 55 do Brasil, para reconhecer o mesmo cliente."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[2:] if len(digits) > 11 and digits.startswith("55") else digits


WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def minutes(value):
    return int(value[:2]) * 60 + int(value[3:])


def store_status(store, moment=None):
    """Situação da loja para o cliente: (aceita pedidos, texto curto)."""
    # A assinatura vale pelo momento atual (a loja pode assinar antes do horário agendado).
    if not store["enabled"] or not billing_ok(store):
        return False, "Indisponível no momento"
    if not store["open"]:
        return False, "Fechado no momento"
    if not store["auto_hours"]:
        return True, "Aberto agora"
    hours = json.loads(store["hours"] or "{}")
    moment = (moment or datetime.now(ZONE)).astimezone(ZONE)
    day, current = moment.weekday(), moment.hour * 60 + moment.minute
    for start, end in hours.get(str(day), []):
        s, e = minutes(start), minutes(end)
        if (s < e and s <= current < e) or (e <= s and current >= s):
            return True, "Aberto até " + end
    for start, end in hours.get(str((day - 1) % 7), []):
        if minutes(end) <= minutes(start) and current < minutes(end):
            return True, "Aberto até " + end
    for offset in range(8):
        weekday = (day + offset) % 7
        for start, _ in sorted(hours.get(str(weekday), [])):
            if offset == 0 and minutes(start) <= current:
                continue
            label = "hoje" if offset == 0 else "amanhã" if offset == 1 else WEEKDAYS[weekday]
            return False, f"Fechado • abre {label} às {start}"
    return False, "Fechado no momento"


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
        STORAGE_PUBLIC_URL=os.getenv("STORAGE_PUBLIC_URL", ""), TRIAL_DAYS=int(os.getenv("TRIAL_DAYS", "1")),
        MP_PLATFORM_ACCESS_TOKEN=os.getenv("MP_PLATFORM_ACCESS_TOKEN", ""), PLAN_PRICE=int(os.getenv("PLAN_PRICE_CENTS", "5999")),
        PLAN_FREE_MONTHS=int(os.getenv("PLAN_FREE_MONTHS", "1")), BILLING_EXEMPT_EMAILS=os.getenv("BILLING_EXEMPT_EMAILS", ""),
        VAPID_PRIVATE_KEY=os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n"), PUSH_CONTACT=os.getenv("PUSH_CONTACT", "suporte@seucomercioaqui.com.br"),
        UPLOAD_DIR=os.getenv("UPLOAD_DIR", str(BASE / "instance" / "uploads")),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        MAX_FORM_PARTS=20, ALLOW_REGISTRATION=os.getenv("ALLOW_REGISTRATION", "1") == "1",
        PUBLIC_URL=(os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/"), RATE_LIMIT_ENABLED=True,
        # Arquivos do app sempre revalidados: depois de publicar, o navegador pega a versão nova (304 quando igual).
        SEND_FILE_MAX_AGE_DEFAULT=0,
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
    app.extensions.setdefault("mercadopago", MercadoPago())
    with app.app_context():
        startup = connect(app.config)
        try:
            first_billing_migration(startup, app.config)
            apply_exemptions(startup, app.config)
        except Exception:  # nunca impedir o site de subir por causa da rotina de cobrança
            app.logger.exception("Falha ao preparar as assinaturas na inicialização")
        finally:
            startup.close()

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
            store, role = one("SELECT * FROM stores WHERE owner_id=?", (user["id"],)), "owner"
            if not store:
                member = one("SELECT * FROM store_members WHERE user_id=? AND active=1", (user["id"],))
                if member:
                    store, role = one("SELECT * FROM stores WHERE id=?", (member["store_id"],)), member["role"]
            if not store:
                abort(404, description="Loja não encontrada.")
            endpoint = request.endpoint or ""
            if role != "owner" and (endpoint in MANAGER_DENY if role == "manager" else endpoint not in ROLE_ALLOWED[role]):
                abort(403, description=f"O acesso de {ROLE_LABELS[role]} não permite esta ação. Fale com o dono da loja.")
            g.user, g.store, g.role = user, store, role
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
        value["hours"] = json.loads(value["hours"] or "{}")
        value["delivery_zones"] = json.loads(value["delivery_zones"] or "[]")
        value["open"], value["auto_hours"] = bool(value["open"]), bool(value["auto_hours"])
        value["allow_scheduling"], value["loyalty_enabled"] = bool(value["allow_scheduling"]), bool(value["loyalty_enabled"])
        value["open_now"], value["status_text"] = store_status(store)
        value["mp_connected"] = bool(value.pop("mp_token", ""))
        value["billing_state"] = billing_state(store)
        for key in ("sub_id", "sub_checked_at"):
            value.pop(key, None)
        value.pop("mp_webhook_key", None)
        if not value["mp_connected"]:
            value["payments"] = [p for p in value["payments"] if p != "pix_online"]
        if not private:
            value.pop("mp_account", None)
            for key in ("billing_exempt", "sub_status", "sub_payer_email", "sub_next_payment", "sub_used_trial", "paid_until", "trial_until", "billing_state"):
                value.pop(key, None)
            for key in ("owner_id", "created_at", "commission_bps", "monthly_fee", "payment_fees", "default_delivery_cost", "enabled",
                        "blocked_reason", "promo_fee", "promo_until", "promo_label"):
                value.pop(key, None)
        return value

    def delivery_fee(store, mode, value):
        """Taxa de entrega: por bairro quando a loja cadastrou bairros, senão a taxa única."""
        if mode != "delivery":
            return 0, ""
        zones = json.loads(store["delivery_zones"] or "[]")
        if not zones:
            return store["delivery_fee"], ""
        name = text(value, "zone", 0, 60)
        zone = next((z for z in zones if z["name"] == name), None)
        if not zone:
            abort(400, description="Escolha o seu bairro para calcular a entrega.")
        return zone["fee"], zone["name"]

    def schedule(store, value):
        """Horário agendado (UTC ISO) ou '' para agora. Agendar exige a opção ligada e cair dentro do horário da loja."""
        raw = value.get("scheduled_for") or ""
        if not raw:
            return ""
        if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw):
            abort(400, description="Horário de agendamento inválido.")
        if not store["allow_scheduling"]:
            abort(400, description="Esta loja não aceita pedidos agendados.")
        try:
            moment = datetime.strptime(raw, "%Y-%m-%dT%H:%M").replace(tzinfo=ZONE)
        except ValueError:
            abort(400, description="Horário de agendamento inválido.")
        current = datetime.now(ZONE)
        if moment < current + timedelta(minutes=20) or moment > current + timedelta(days=7):
            abort(400, description="Agende com pelo menos 20 minutos de antecedência e até 7 dias.")
        if not store["enabled"] or not store["open"] or (store["auto_hours"] and not store_status(store, moment)[0]):
            abort(400, description="A loja não estará aberta nesse horário. Escolha outro.")
        return moment.astimezone(timezone.utc).isoformat(timespec="seconds")

    def hours_field(value):
        hours = value.get("hours", {})
        if not isinstance(hours, dict) or any(k not in {str(d) for d in range(7)} for k in hours):
            abort(400, description="Horário de funcionamento inválido.")
        result = {}
        for day, shifts in hours.items():
            if not isinstance(shifts, list) or len(shifts) > 3:
                abort(400, description="Use até 3 turnos por dia.")
            clean = []
            for shift in shifts:
                if (not isinstance(shift, list) or len(shift) != 2 or not all(isinstance(t, str) and HHMM.fullmatch(t) for t in shift)
                        or shift[0] == shift[1]):
                    abort(400, description=f"Horário inválido na {WEEKDAYS[int(day)]}.")
                clean.append(shift)
            if clean:
                result[day] = sorted(clean)
        return result

    def zones_field(value):
        zones = value.get("delivery_zones", [])
        if not isinstance(zones, list) or len(zones) > 100:
            abort(400, description="Use até 100 bairros.")
        result, seen = [], set()
        for zone in zones:
            if not isinstance(zone, dict):
                abort(400, description="Bairro inválido.")
            name = text(zone, "name", 2, 60)
            if name.lower() in seen:
                abort(400, description=f"O bairro {name} está repetido.")
            seen.add(name.lower())
            result.append({"name": name, "fee": integer(zone, "fee", maximum=100_000)})
        return result

    def product_dict(product, private=False):
        value = dict(product)
        value["extras"] = json.loads(value["extras"])
        value["option_groups"] = json.loads(value["option_groups"] or "[]")
        value["active"], value["featured"] = bool(value["active"]), bool(value["featured"])
        if not private:
            value.pop("unit_cost", None)
            value.pop("low_stock", None)
            value["extras"] = [{k:v for k,v in x.items() if k!='unit_cost'} for x in value["extras"]]
            for group in value["option_groups"]:
                group["options"] = [{k:v for k,v in x.items() if k!='unit_cost'} for x in group["options"]]
        return value

    def choose_options(product, selected):
        """Valida as escolhas do cliente e devolve (preço unitário, custo unitário ou None, opções escolhidas)."""
        if not isinstance(selected, list) or len(selected) > 60 or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
            abort(400, description="Complementos inválidos.")
        extras = json.loads(product["extras"])
        groups = json.loads(product["option_groups"] or "[]")
        available = {x["id"]: (None, x) for x in extras}
        for group in groups:
            for option in group["options"]:
                available[option["id"]] = (group, option)
        if any(x not in available for x in selected):
            abort(400, description=f"Uma opção de {product['name']} não está mais disponível. Escolha de novo.")
        price, costs, chosen = product["price"], [product["unit_cost"]], []
        for x in selected:
            group, option = available[x]
            if group is None:
                price += option["price"]
                costs.append(option.get("unit_cost"))
                chosen.append(option)
        for group in groups:
            picked = [available[x][1] for x in selected if available[x][0] is group]
            if not group["min"] <= len(picked) <= group["max"]:
                need = (f"escolha {group['min']}" if group["min"] == group["max"] else
                        f"escolha de {group['min']} a {group['max']}" if group["min"] else f"escolha até {group['max']}")
                abort(400, description=f"{product['name']}: {need} em {group['name']}.")
            if picked and group["pricing"] == "max":
                top = max(picked, key=lambda o: o["price"])
                price += top["price"]
                costs.append(top.get("unit_cost"))
            else:
                price += sum(o["price"] for o in picked)
                costs.extend(o.get("unit_cost") for o in picked)
            chosen.extend({**o, "name": group["name"] + ": " + o["name"]} for o in picked)
        cost = None if any(c is None for c in costs) else sum(costs)
        return price, cost, chosen

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
            value = {k: value[k] for k in ("number", "mode", "zone", "scheduled_for", "rating", "payment", "subtotal", "discount", "delivery_fee",
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
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self' https://viacep.com.br; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
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

    def public_base():
        return app.config["PUBLIC_URL"] or request.host_url.rstrip("/")

    @app.get("/")
    @app.get("/entrar")
    @app.get("/painel")
    @app.get("/pedido/<token>")
    def page(**kwargs):
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/termos")
    @app.get("/privacidade")
    def legal_page():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/admin")
    def owner_site():
        """Central do Dono: endereço próprio, fora de qualquer menu das lojas."""
        response = send_from_directory(app.static_folder, "index.html")
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/plataforma")
    def old_platform_address():
        return redirect("/admin", 301)

    @app.get("/loja/<slug>")
    def store_page(slug):
        """Mesma aplicação, com título e prévia próprios para o link compartilhado no WhatsApp."""
        html = (Path(app.static_folder) / "index.html").read_text(encoding="utf-8")
        store = one("SELECT name,description,logo,banner,slug FROM stores WHERE slug=?", (slug,))
        if store:
            base = public_base()
            picture = store["banner"] or store["logo"]
            picture = (base + picture if picture.startswith("/") else picture) if picture else base + "/static/og-image.png"
            title = escape(store["name"] + " • Peça pelo cardápio digital")
            summary = escape(store["description"] or "Veja o cardápio e faça seu pedido com entrega ou retirada.")
            meta = (f'<meta property="og:type" content="website"><meta property="og:title" content="{title}">'
                    f'<meta property="og:description" content="{summary}"><meta property="og:image" content="{escape(picture)}">'
                    f'<meta property="og:url" content="{escape(base + "/loja/" + store["slug"])}"><meta name="twitter:card" content="summary_large_image">')
            html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1)
            html = re.sub(r'<meta name="description"[^>]*>', f'<meta name="description" content="{summary}">', html, count=1)
            html = re.sub(r'<meta property="og:[^>]*>|<meta name="twitter:[^>]*>', "", html)
            html = html.replace("</head>", meta + "\n</head>", 1)
        response = app.response_class(html, mimetype="text/html")
        return response, 200 if store else 404

    @app.get("/api/admin/qrcode")
    @owner
    def store_qrcode():
        import segno
        code = segno.make(public_base() + "/loja/" + g.store["slug"], error="m")
        output = io.BytesIO()
        if request.args.get("format") == "png":
            code.save(output, kind="png", scale=16, border=2, dark="#103f42")
            mimetype, extension = "image/png", "png"
        else:
            code.save(output, kind="svg", scale=10, border=2, dark="#103f42", xmldecl=False)
            mimetype, extension = "image/svg+xml", "svg"
        response = app.response_class(output.getvalue(), mimetype=mimetype)
        if request.args.get("download"):
            response.headers["Content-Disposition"] = f'attachment; filename="qrcode-{g.store["slug"]}.{extension}"'
        return response

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
        db().execute("UPDATE users SET last_login_at=? WHERE id=?", (now(), user["id"]))
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
        if value.get("accept_terms") is not True:
            abort(400, description="Para criar a loja, aceite os Termos de uso e a Política de privacidade.")
        hashed = generate_password_hash(password)
        trial = (datetime.now(timezone.utc) + timedelta(days=app.config["TRIAL_DAYS"])).isoformat(timespec="seconds") if app.config["TRIAL_DAYS"] > 0 else ""
        with transaction() as conn:
            uid = conn.execute("INSERT INTO users(name,email,password_hash,created_at,terms_accepted_at) VALUES(?,?,?,?,?)",
                               (name, email, hashed, now(), now())).lastrowid
            sid = conn.execute("INSERT INTO stores(owner_id,name,slug,created_at,trial_until,monthly_fee) VALUES(?,?,?,?,?,?)",
                               (uid, store_name, slug, now(), trial, app.config["PLAN_PRICE"])).lastrowid
            apply_exemptions(conn, app.config)
            conn.execute("INSERT INTO categories(store_id,name) VALUES(?,?)", (sid, "Destaques"))
        return establish(one("SELECT * FROM users WHERE id=?", (uid,))), 201

    @app.post("/api/auth/login")
    def login():
        limited("login", 15)
        value = data()
        email, password = text(value, "email", 1, 254).lower(), text(value, "password", 1, 128)
        # Além do limite por IP, limita tentativas por conta (protege contra ataque distribuído).
        limited("login-account:" + hashlib.sha256(email.encode()).hexdigest(), 10, 900, per_ip=False)
        user = one("SELECT * FROM users WHERE email=?", (email,))
        if not user or not check_password_hash(user["password_hash"], password):
            abort(401, description="E-mail ou senha incorretos.")
        if user["platform_admin"]:
            db().execute("INSERT INTO audit_log(actor_id,store_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                         (user["id"], None, "auth.admin_login", request.remote_addr or "", now()))
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

    def customer_orders_by_phone(conn, sid, phone):
        key = phone_key(phone)
        if len(key) < 10:
            return []
        found = conn.execute(f"SELECT id,phone,status,loyalty_discount FROM orders WHERE store_id=? AND {PHONE_SQL} LIKE ?",
                             (sid, "%" + key[-9:])).fetchall()
        return [o for o in found if phone_key(o["phone"]) == key]

    def loyalty_status(conn, store, phone):
        if not store["loyalty_enabled"] or not phone:
            return None
        history = customer_orders_by_phone(conn, store["id"], phone)
        completed = sum(o["status"] == "completed" for o in history)
        used = sum(o["status"] != "cancelled" and o["loyalty_discount"] > 0 for o in history)
        goal = max(1, store["loyalty_goal"])
        available = completed // goal > used
        return {"goal": goal, "reward": store["loyalty_reward"], "completed": completed, "available": available,
                "remaining": 0 if available else goal - completed % goal}

    def coupon_discount(conn, sid, code, subtotal, phone=""):
        if not code:
            return 0, None
        coupon = conn.execute("SELECT * FROM coupons WHERE store_id=? AND code=? AND active=1", (sid, code.upper())).fetchone()
        today = datetime.now(ZONE).date().isoformat()
        if not coupon or (coupon["expires"] and coupon["expires"] < today) or (coupon["max_uses"] is not None and coupon["uses"] >= coupon["max_uses"]):
            abort(400, description="Cupom inválido, vencido ou esgotado.")
        if subtotal < coupon["minimum"]:
            abort(400, description=f"Este cupom exige R$ {coupon['minimum']/100:.2f} em produtos.")
        if coupon["first_order"]:
            if len(phone_key(phone)) < 10:
                abort(400, description="Informe seu WhatsApp para usar o cupom de primeira compra.")
            if any(o["status"] != "cancelled" for o in customer_orders_by_phone(conn, sid, phone)):
                abort(400, description="Este cupom é só para a primeira compra na loja.")
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
            unit, cost, extras = choose_options(product, item.get("option_ids", []))
            subtotal += quantity * unit
            quantities[pid] = quantities.get(pid, 0) + quantity
            prepared.append((product, quantity, unit, extras, text(item, "notes", 0, 200), cost))
        return subtotal, quantities, prepared

    @app.post("/api/store/<slug>/quote")
    def quote(slug):
        limited("quote", 120)
        value = data()
        store = one("SELECT * FROM stores WHERE slug=?", (slug,))
        if not store:
            abort(404, description="Loja não encontrada.")
        accepting, status_text = store_status(store)
        if not schedule(store, value) and not accepting:
            abort(409, description="A loja não está aceitando pedidos agora. " + status_text + ".")
        mode, items = value.get("mode"), value.get("items")
        if mode not in ("delivery", "pickup") or not isinstance(items, list) or not 1 <= len(items) <= 50:
            abort(400, description="Sacola inválida.")
        subtotal, quantities, prepared = price_items(db(), store, items)
        for product, quantity, unit, extras, notes, _ in prepared:
            if product["stock"] is not None and quantities[product["id"]] > product["stock"]:
                abort(409, description=f"Estoque insuficiente: {product['name']}.")
        if subtotal < store["minimum_order"]:
            abort(400, description=f"Pedido mínimo de R$ {store['minimum_order']/100:.2f} em produtos.")
        phone = text(value, "phone", 0, 20)
        discount, _ = coupon_discount(db(), store["id"], text(value, "coupon", 0, 30).upper(), subtotal, phone)
        loyalty = loyalty_status(db(), store, phone)
        reward = min(loyalty["reward"], subtotal - discount) if loyalty and loyalty["available"] else 0
        fee, zone = delivery_fee(store, mode, value)
        return jsonify(subtotal=subtotal, discount=discount + reward, loyalty_discount=reward, loyalty=loyalty,
                       delivery_fee=fee, zone=zone, total=subtotal-discount-reward+fee)

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
            accepting, status_text = store_status(store)
            scheduled = schedule(store, value)
            if not store["enabled"] or (not accepting and not scheduled and not getattr(g, 'manual_order', False)):
                abort(409, description="A loja não está aceitando pedidos agora. " + status_text + ".")
            if payment not in json.loads(store["payments"]) or (payment == "pix_online" and not store["mp_token"]):
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
            discount, coupon_id = coupon_discount(conn, store["id"], coupon_code, subtotal, phone)
            loyalty = loyalty_status(conn, store, phone)
            reward = min(loyalty["reward"], subtotal - discount) if loyalty and loyalty["available"] else 0
            discount += reward
            fee, zone = delivery_fee(store, mode, value)
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
            conn.execute("UPDATE orders SET loyalty_discount=? WHERE id=?", (reward, oid))
            conn.execute("UPDATE orders SET delivery_cost=?,payment_fee=?,platform_fee=?,source=?,zone=?,scheduled_for=? WHERE id=?",
                (store['default_delivery_cost'] if mode=='delivery' else 0,
                 (total*fees.get(payment,0)+5000)//10000,
                 ((subtotal-discount)*store['commission_bps']+5000)//10000,
                 'counter' if getattr(g,'manual_order',False) else 'web',zone,scheduled,oid))
            for product, quantity, unit, extras, item_notes, cost in prepared:
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
        if payment == "pix_online":
            try:
                create_pix(store["id"], oid)
            except PaymentError:
                app.logger.warning("Pix automático não gerado para o pedido %s", oid)
        if not getattr(g, "manual_order", False):
            when = (" • agendado " + datetime.fromisoformat(scheduled).astimezone(ZONE).strftime("%d/%m %H:%M")) if scheduled else ""
            notify_store(app, store["id"], {"title": f"Novo pedido #{number}", "tag": f"pedido-{oid}", "url": "/painel",
                                            "body": f"{customer} • R$ {total/100:.2f}".replace(".", ",") + (" • entrega" if mode == "delivery" else " • retirada") + when})
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
        if order["payment"] == "pix_online" and not order["paid"] and order["pix_provider_id"] and order["status"] != "cancelled":
            last = order["pix_checked_at"]
            if not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(seconds=8):
                try:
                    sync_pix(order, store)
                except PaymentError:
                    pass
                order = one("SELECT * FROM orders WHERE id=?", (order["id"],))
        public = order_dict(order, False)
        public["loyalty"] = loyalty_status(db(), store, order["phone"])
        public["loyalty_discount"] = order["loyalty_discount"]
        if order["payment"] == "pix_online":
            public["pix"] = {"code": order["pix_code"] if not order["paid"] else "", "expires": order["pix_expires"],
                             "expired": bool(order["pix_expires"] and datetime.fromisoformat(order["pix_expires"]) < datetime.now(timezone.utc))}
        return jsonify(order=public, store=store_dict(store))

    def mp_token(store):
        token = unseal(app.config["SECRET_KEY"], store["mp_token"])
        if not token:
            raise PaymentError("Conta do Mercado Pago não conectada.")
        return token

    def create_pix(store_id, oid):
        store = one("SELECT * FROM stores WHERE id=?", (store_id,))
        order = one("SELECT * FROM orders WHERE id=? AND store_id=?", (oid, store_id))
        attempt = order["pix_attempts"] + 1
        db().execute("UPDATE orders SET pix_attempts=? WHERE id=?", (attempt, oid))
        expires = datetime.now(ZONE) + timedelta(minutes=30)
        payload = {"transaction_amount": round(order["total"] / 100, 2), "payment_method_id": "pix",
                   "description": f"Pedido #{order['number']} - {store['name']}"[:200], "external_reference": f"sca-{store_id}-{oid}",
                   "date_of_expiration": expires.isoformat(timespec="milliseconds"),
                   "payer": {"email": f"pedido{oid}.loja{store_id}@seucomercioaqui.com.br", "first_name": order["customer"].split(" ")[0][:40]}}
        base = public_base()
        if base.startswith("https://") and store["mp_webhook_key"]:
            payload["notification_url"] = f"{base}/webhooks/mercadopago/{store['mp_webhook_key']}"
        result = app.extensions["mercadopago"].create_pix(mp_token(store), payload, f"sca-{store_id}-{oid}-{attempt}")
        code = ((result.get("point_of_interaction") or {}).get("transaction_data") or {}).get("qr_code", "")
        if not result.get("id") or not code:
            raise PaymentError("O Mercado Pago não devolveu o código Pix.")
        db().execute("UPDATE orders SET pix_provider_id=?,pix_code=?,pix_expires=?,pix_checked_at=? WHERE id=?",
                     (str(result["id"]), code, expires.astimezone(timezone.utc).isoformat(timespec="seconds"), now(), oid))

    def sync_pix(order, store):
        """Consulta o Mercado Pago e marca como pago só se o valor e o pedido baterem."""
        db().execute("UPDATE orders SET pix_checked_at=? WHERE id=?", (now(), order["id"]))
        info = app.extensions["mercadopago"].get_payment(mp_token(store), order["pix_provider_id"])
        approved = (info.get("status") == "approved" and info.get("external_reference") == f"sca-{store['id']}-{order['id']}"
                    and round(float(info.get("transaction_amount", 0)) * 100) == order["total"])
        if approved and not order["paid"]:
            fee = sum(round(float(f.get("amount", 0)) * 100) for f in info.get("fee_details") or [])
            db().execute("UPDATE orders SET paid=1,payment_fee=?,updated_at=? WHERE id=? AND paid=0", (fee, now(), order["id"]))
            notify_store(app, store["id"], {"title": f"Pix confirmado • pedido #{order['number']}", "tag": f"pago-{order['id']}",
                                            "url": "/painel", "body": f"{order['customer']} pagou R$ {order['total']/100:.2f}".replace(".", ",")})
        return info.get("status")

    @app.get("/api/track/<token>/pix.svg")
    def pix_qrcode(token):
        import segno
        order = one("SELECT * FROM orders WHERE tracking_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        if not order or order["payment"] != "pix_online" or not order["pix_code"] or order["paid"]:
            abort(404, description="Pix não encontrado.")
        output = io.BytesIO()
        segno.make(order["pix_code"], error="m").save(output, kind="svg", scale=8, border=2, xmldecl=False)
        response = app.response_class(output.getvalue(), mimetype="image/svg+xml")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/track/<token>/pix")
    def renew_pix(token):
        limited("pix-renew", 10)
        order = one("SELECT * FROM orders WHERE tracking_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        if not order or order["payment"] != "pix_online":
            abort(404, description="Pedido não encontrado.")
        if order["paid"] or order["status"] == "cancelled":
            abort(409, description="Este pedido não precisa de um novo Pix.")
        if order["pix_attempts"] >= 5:
            abort(409, description="Limite de tentativas atingido. Fale com a loja.")
        if order["pix_code"] and order["pix_expires"] and datetime.fromisoformat(order["pix_expires"]) > datetime.now(timezone.utc):
            return jsonify(ok=True)
        try:
            create_pix(order["store_id"], order["id"])
        except PaymentError as error:
            abort(502, description=str(error))
        return jsonify(ok=True)

    @app.post("/webhooks/mercadopago/<key>")
    def mercadopago_webhook(key):
        limited("mp-webhook", 300, 60)
        store = one("SELECT * FROM stores WHERE mp_webhook_key=?", (key,)) if re.fullmatch(r"[A-Za-z0-9_-]{20,80}", key) else None
        if not store:
            return jsonify(ok=True)
        body = request.get_json(silent=True) or {}
        payment_id = str((body.get("data") or {}).get("id") or request.args.get("data.id") or request.args.get("id") or "")
        if payment_id.isdigit():
            order = one("SELECT * FROM orders WHERE store_id=? AND pix_provider_id=?", (store["id"], payment_id))
            if order and not order["paid"]:
                try:
                    sync_pix(order, store)
                except PaymentError:
                    pass
        return jsonify(ok=True)

    @app.put("/api/admin/payments/mercadopago")
    @owner
    def mp_connect():
        token = text(data(), "access_token", 20, 200)
        if not re.fullmatch(r"(APP_USR|TEST)-[A-Za-z0-9-]+", token):
            abort(400, description="Cole o Access Token do Mercado Pago (começa com APP_USR-).")
        try:
            account = app.extensions["mercadopago"].me(token)
        except PaymentError as error:
            abort(400, description="Token não aceito pelo Mercado Pago. Confira se copiou o Access Token de produção. " + str(error))
        label = account.get("nickname") or account.get("email") or str(account.get("id", ""))
        key = g.store["mp_webhook_key"] or secrets.token_urlsafe(24)
        db().execute("UPDATE stores SET mp_token=?,mp_account=?,mp_webhook_key=? WHERE id=?",
                     (seal(app.config["SECRET_KEY"], token), label, key, g.store["id"]))
        return jsonify(connected=True, account=label)

    @app.delete("/api/admin/payments/mercadopago")
    @owner
    def mp_disconnect():
        payments = [p for p in json.loads(g.store["payments"]) if p != "pix_online"] or ["cash"]
        db().execute("UPDATE stores SET mp_token='',mp_account='',payments=? WHERE id=?", (json.dumps(payments), g.store["id"]))
        return jsonify(connected=False)

    @app.post("/api/track/<token>/review")
    def review_order(token):
        limited("review", 20)
        value = data()
        rating = integer(value, "rating", minimum=1, maximum=5)
        comment = text(value, "comment", 0, 500)
        with transaction() as conn:
            order = conn.execute("SELECT * FROM orders WHERE tracking_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not order:
                abort(404, description="Pedido não encontrado.")
            if order["status"] != "completed":
                abort(409, description="Você pode avaliar quando o pedido for concluído.")
            if order["rating"] is not None:
                abort(409, description="Este pedido já foi avaliado. Obrigado!")
            conn.execute("UPDATE orders SET rating=?,review=?,reviewed_at=? WHERE id=?", (rating, comment, now(), order["id"]))
        return jsonify(ok=True)

    @app.get("/api/admin/reviews")
    @owner
    def reviews():
        stats = one("SELECT COUNT(rating) AS total,AVG(rating) AS average FROM orders WHERE store_id=? AND rating IS NOT NULL", (g.store["id"],))
        return jsonify(total=stats["total"], average=round(float(stats["average"]), 1) if stats["average"] is not None else None,
                       reviews=rows("SELECT number,customer,rating,review,reviewed_at FROM orders WHERE store_id=? AND rating IS NOT NULL ORDER BY reviewed_at DESC LIMIT 50", (g.store["id"],)))

    @app.get("/api/admin/store")
    @owner
    def admin_store():
        return jsonify(store=store_dict(g.store, True), role=g.role, role_label=ROLE_LABELS[g.role])

    @app.get("/sw.js")
    def service_worker():
        response = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript", max_age=0)
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/admin/push/key")
    @owner
    def push_key():
        return jsonify(public_key=vapid_keys(app.config, db())[1])

    @app.post("/api/admin/push/subscribe")
    @owner
    def push_subscribe():
        value = data()
        endpoint = text(value, "endpoint", 20, 600)
        keys = value.get("keys")
        if not endpoint.startswith("https://") or not isinstance(keys, dict):
            abort(400, description="Assinatura de aviso inválida.")
        p256dh, auth_key = text(keys, "p256dh", 20, 200), text(keys, "auth", 10, 100)
        with transaction() as conn:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
            if conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id=?", (g.user["id"],)).fetchone()[0] >= 10:
                conn.execute("DELETE FROM push_subscriptions WHERE id=(SELECT MIN(id) FROM push_subscriptions WHERE user_id=?)", (g.user["id"],))
            conn.execute("INSERT INTO push_subscriptions(store_id,user_id,endpoint,p256dh,auth,created_at) VALUES(?,?,?,?,?,?)",
                         (g.store["id"], g.user["id"], endpoint, p256dh, auth_key, now()))
        return jsonify(ok=True), 201

    @app.post("/api/admin/push/unsubscribe")
    @owner
    def push_unsubscribe():
        endpoint = text(data(), "endpoint", 1, 600)
        db().execute("DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?", (endpoint, g.user["id"]))
        return jsonify(ok=True)

    @app.post("/api/admin/push/test")
    @owner
    def push_test():
        limited("push-test", 10)
        sent = notify_store(app, g.store["id"], {"title": "Teste de aviso", "body": "Tudo certo! Os pedidos novos vão chegar assim.",
                                                 "tag": "teste", "url": "/painel"}, user_id=g.user["id"])
        return jsonify(ok=True, sent=sent)

    @app.post("/api/admin/store/open")
    @owner
    def set_open():
        is_open = boolean(data(), "open")
        if is_open and not g.store["enabled"]:
            abort(403, description="Loja suspensa pela plataforma. Entre em contato com o suporte.")
        db().execute("UPDATE stores SET open=? WHERE id=?", (is_open, g.store["id"]))
        return jsonify(store=store_dict(one("SELECT * FROM stores WHERE id=?", (g.store["id"],)), True))

    def team_member(mid):
        member = one("SELECT * FROM store_members WHERE id=? AND store_id=?", (mid, g.store["id"]))
        if not member:
            abort(404, description="Pessoa da equipe não encontrada.")
        return member

    def role_field(value):
        role = value.get("role")
        if role not in ("manager", "cashier", "kitchen"):
            abort(400, description="Escolha a função: gerente, caixa ou cozinha.")
        return role

    @app.get("/api/admin/team")
    @owner
    def team_list():
        return jsonify(members=rows("""SELECT m.id,m.role,m.active,m.created_at,u.name,u.email,u.last_login_at FROM store_members m
            JOIN users u ON u.id=m.user_id WHERE m.store_id=? ORDER BY m.active DESC,u.name""", (g.store["id"],)))

    @app.post("/api/admin/team")
    @owner
    def team_add():
        value = data()
        name, email = text(value, "name", 2, 100), text(value, "email", 5, 254).lower()
        password, role = text(value, "password", 10, 128), role_field(value)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            abort(400, description="E-mail inválido.")
        if one("SELECT COUNT(*) FROM store_members WHERE store_id=?", (g.store["id"],))[0] >= 30:
            abort(409, description="Limite de 30 pessoas na equipe.")
        if one("SELECT id FROM users WHERE email=?", (email,)):
            abort(409, description="Este e-mail já tem uma conta. Use outro e-mail para esta pessoa.")
        with transaction() as conn:
            uid = conn.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                               (name, email, generate_password_hash(password), now())).lastrowid
            mid = conn.execute("INSERT INTO store_members(store_id,user_id,role,created_at) VALUES(?,?,?,?)",
                               (g.store["id"], uid, role, now())).lastrowid
            conn.execute("INSERT INTO audit_log(actor_id,store_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                         (g.user["id"], g.store["id"], "team.add", f"{email} ({ROLE_LABELS[role]})", now()))
        return jsonify(id=mid), 201

    @app.patch("/api/admin/team/<int:mid>")
    @owner
    def team_update(mid):
        member, value = team_member(mid), data()
        role = role_field(value) if "role" in value else member["role"]
        active = boolean(value, "active", bool(member["active"]))
        with transaction() as conn:
            conn.execute("UPDATE store_members SET role=?,active=? WHERE id=?", (role, active, mid))
            if role != member["role"] or active != member["active"]:
                # Encerra as sessões abertas para valer a nova permissão na hora.
                conn.execute("UPDATE users SET auth_version=auth_version+1 WHERE id=?", (member["user_id"],))
        return jsonify(ok=True)

    @app.post("/api/admin/team/<int:mid>/password")
    @owner
    def team_password(mid):
        member = team_member(mid)
        password = text(data(), "password", 10, 128)
        db().execute("UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?",
                     (generate_password_hash(password), member["user_id"]))
        return jsonify(ok=True)

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
        if not isinstance(payments, list) or not payments or any(p not in ("pix", "pix_online", "cash", "card") for p in payments):
            abort(400, description="Selecione ao menos uma forma de pagamento.")
        if "pix_online" in payments and not g.store["mp_token"]:
            abort(400, description="Conecte sua conta do Mercado Pago para usar o Pix automático.")
        pix = text(value, "pix_key", 0, 200)
        if "pix" in payments and not pix and "pix_online" not in payments:
            abort(400, description="Informe sua chave Pix ou desative Pix.")
        hours = hours_field(value) if "hours" in value else json.loads(g.store["hours"] or "{}")
        zones = zones_field(value) if "delivery_zones" in value else json.loads(g.store["delivery_zones"] or "[]")
        auto_hours = boolean(value, "auto_hours", bool(g.store["auto_hours"]))
        allow_scheduling = boolean(value, "allow_scheduling", bool(g.store["allow_scheduling"]))
        loyalty_enabled = boolean(value, "loyalty_enabled", bool(g.store["loyalty_enabled"]))
        loyalty_goal = integer(value, "loyalty_goal", g.store["loyalty_goal"], minimum=2, maximum=100)
        loyalty_reward = integer(value, "loyalty_reward", g.store["loyalty_reward"], minimum=100, maximum=100_000)
        if auto_hours and not hours:
            abort(400, description="Informe ao menos um dia de funcionamento ou desative o horário automático.")
        db().execute("""UPDATE stores SET name=?,description=?,phone=?,address=?,color=?,logo=?,banner=?,open=?,
            delivery_fee=?,minimum_order=?,delivery_minutes=?,pix_key=?,payments=?,hours=?,auto_hours=?,delivery_zones=?,allow_scheduling=?,loyalty_enabled=?,loyalty_goal=?,loyalty_reward=? WHERE id=?""",
            (name, description, phone, address, color, image_url(value.get("logo", "")), image_url(value.get("banner", "")),
             boolean(value, "open"), integer(value, "delivery_fee"), integer(value, "minimum_order"),
             text(value, "delivery_minutes", 2, 40), pix, json.dumps(list(dict.fromkeys(payments))),
             json.dumps(hours), int(auto_hours), json.dumps(zones, ensure_ascii=False), int(allow_scheduling), loyalty_enabled, loyalty_goal, loyalty_reward, g.store["id"]))
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
        groups = value.get("option_groups", [])
        if not isinstance(groups, list) or len(groups) > 10:
            abort(400, description="Use até 10 grupos de escolha.")
        clean_groups = []
        for group in groups:
            if not isinstance(group, dict):
                abort(400, description="Grupo de escolha inválido.")
            gid, gname = text(group, "id", 1, 40), text(group, "name", 1, 60)
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", gid):
                abort(400, description="Identificador de grupo inválido.")
            options = group.get("options", [])
            if not isinstance(options, list) or not 1 <= len(options) <= 30:
                abort(400, description=f"O grupo {gname} precisa de 1 a 30 opções.")
            low, high = integer(group, "min", maximum=30), integer(group, "max", minimum=1, maximum=30)
            if low > high or low > len(options):
                abort(400, description=f"No grupo {gname}, o mínimo não pode passar do máximo nem da quantidade de opções.")
            pricing = group.get("pricing", "sum")
            if pricing not in ("sum", "max"):
                abort(400, description="Forma de cobrança do grupo inválida.")
            clean = []
            for option in options:
                if not isinstance(option, dict):
                    abort(400, description="Opção inválida.")
                oid = text(option, "id", 1, 40)
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", oid) or oid in seen:
                    abort(400, description="Identificador de opção inválido ou duplicado.")
                seen.add(oid)
                clean.append({"id": oid, "name": text(option, "name", 1, 80), "price": integer(option, "price"),
                              "unit_cost": None if option.get("unit_cost") is None else integer(option, "unit_cost")})
            clean_groups.append({"id": gid, "name": gname, "min": low, "max": min(high, len(clean)), "pricing": pricing, "options": clean})
        required = any(g["min"] > 0 for g in clean_groups)
        return (category, text(value, "name", 2, 120), text(value, "description", 0, 500),
                integer(value, "price", minimum=0 if required else 1), image_url(value.get("image", "")), boolean(value, "active", True),
                boolean(value, "featured"), stock, json.dumps(sanitized), integer(value, "position"),
                None if value.get('unit_cost') is None else integer(value,'unit_cost'), integer(value,'low_stock',default=5,maximum=1000000),
                json.dumps(clean_groups, ensure_ascii=False))

    @app.post("/api/admin/products")
    @owner
    def create_product():
        fields = product_fields(data())
        with transaction() as conn:
            pid = conn.execute("""INSERT INTO products(store_id,category_id,name,description,price,image,active,featured,stock,extras,position,unit_cost,low_stock,option_groups)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (g.store["id"], *fields)).lastrowid
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
                         stock=?,extras=?,position=?,unit_cost=?,low_stock=?,option_groups=? WHERE id=? AND store_id=?""", (*fields, pid, g.store["id"]))
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
        if g.role == "kitchen":
            # Cozinha só avança o preparo: não mexe em pagamento, entregador nem cancela.
            value = {"status": value.get("status")} if "status" in value else {}
            if value.get("status") == "cancelled":
                abort(403, description="O acesso de Cozinha não pode cancelar pedidos.")
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
                    if order["payment"] == "pix_online" and order["pix_provider_id"] and not order["paid"]:
                        try:
                            app.extensions["mercadopago"].cancel(mp_token(g.store), order["pix_provider_id"])
                        except PaymentError:
                            pass
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
        cid = db().execute("INSERT INTO coupons(store_id,code,kind,value,minimum,expires,max_uses,first_order) VALUES(?,?,?,?,?,?,?,?)",
                           (g.store["id"], code, kind, amount, integer(value, "minimum"), expires, maximum, boolean(value, "first_order"))).lastrowid
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
                "payments": [{"method": m, "total": sum(o["total"] for o in orders if o["paid"] and o["payment"] == m)} for m in ("pix", "pix_online", "cash", "card")]}

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

    def audit_entry(action, detail="", sid=None):
        db().execute("INSERT INTO audit_log(actor_id,store_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                     (g.user["id"] if getattr(g, "user", None) else None, sid, action, detail, now()))

    register_billing(app, dict(db=db, one=one, rows=rows, owner=owner, data=data, text=text, transaction=transaction,
                               limited=limited, now=now, public_base=public_base, audit=audit_entry))

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
