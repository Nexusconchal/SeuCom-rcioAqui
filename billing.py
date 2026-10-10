"""Assinatura mensal das lojas, cobrada no cartão pelo Mercado Pago (conta da plataforma).

Regras: teste grátis curto ao criar a conta; ao assinar, o primeiro mês sai por R$ 0
(uma vez por loja) e depois o Mercado Pago cobra o valor do plano todo mês. A loja
recebe pedidos enquanto estiver isenta, em teste, com assinatura autorizada ou paga
até uma data. Contas isentas são definidas por hash do e-mail (nada de e-mail no código),
pela variável BILLING_EXEMPT_EMAILS ou pelo dono da plataforma na Central.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import abort, g, jsonify, request, session

from payments import PaymentError

ZONE = ZoneInfo("America/Sao_Paulo")
# sha256 de e-mails com uso gratuito permanente (pedido do dono da plataforma).
EXEMPT_HASHES = {"577b44580877bd631b9d074d467d724ca1f9ce2a32ac05795eaa20fd3ca48b34"}
OK_STATES = {"exempt", "active", "paid", "trial"}


def _get(store, key, default=None):
    try:
        value = store[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def add_month(day):
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    for last in (31, 30, 29, 28):
        try:
            return day.replace(year=year, month=month, day=min(day.day, last))
        except ValueError:
            continue


def trial_active(value, moment=None):
    if not value:
        return False
    moment = moment or datetime.now(timezone.utc)
    if len(value) == 10:
        return value >= moment.astimezone(ZONE).date().isoformat()
    return datetime.fromisoformat(value) > moment


def billing_state(store, moment=None):
    """Situação da assinatura a partir só dos dados da loja."""
    if _get(store, "billing_exempt", 1):
        return "exempt"
    status = _get(store, "sub_status", "")
    if status == "authorized":
        return "active"
    today = (moment or datetime.now(timezone.utc)).astimezone(ZONE).date().isoformat()
    if _get(store, "paid_until", "") >= today:
        return "paid"
    if trial_active(_get(store, "trial_until", ""), moment):
        return "trial"
    if status in ("pending", "paused", "cancelled"):
        return status
    return "expired"


def billing_ok(store, moment=None):
    return billing_state(store, moment) in OK_STATES


def extend_paid_until(current, paid_on):
    """Pagamento em `paid_on` libera até um mês depois (mais 3 dias de tolerância)."""
    until = (add_month(paid_on) + timedelta(days=3)).isoformat()
    return max(current or "", until)


def register_billing(app, helpers):
    h = SimpleNamespace(**helpers)
    config = app.config

    def mp():
        return app.extensions["mercadopago"]

    def token():
        value = config.get("MP_PLATFORM_ACCESS_TOKEN", "")
        if not value:
            abort(503, description="A assinatura ainda não foi configurada pela plataforma. Fale com o suporte.")
        return value

    def webhook_secret():
        return hashlib.sha256(("billing-webhook:" + config["SECRET_KEY"]).encode()).hexdigest()[:32]

    def platform_only():
        user = h.one("SELECT id,auth_version,platform_admin FROM users WHERE id=?", (session.get("uid", -1),))
        if not user or user["auth_version"] != session.get("version"):
            abort(401, description="Entre na sua conta.")
        if not user["platform_admin"]:
            abort(403, description="Esta área é exclusiva do dono da plataforma.")
        g.user = user

    def price():
        return config["PLAN_PRICE"]

    def info(store):
        state = billing_state(store)
        return {"state": state, "ok": state in OK_STATES, "price": price(), "free_months": config["PLAN_FREE_MONTHS"] if not store["sub_used_trial"] else 0,
                "trial_until": store["trial_until"] if trial_active(store["trial_until"]) else "", "sub_status": store["sub_status"],
                "payer_email": store["sub_payer_email"], "next_payment": store["sub_next_payment"], "paid_until": store["paid_until"],
                "configured": bool(config.get("MP_PLATFORM_ACCESS_TOKEN")), "manage_url": "https://www.mercadopago.com.br/subscriptions"}

    def record_payment(store_id, payment_id, amount, paid_on, description):
        """Lança o recebimento na Central do Dono uma única vez e libera a loja até o próximo mês."""
        key = "mp-sub-" + str(payment_id)
        with h.transaction() as conn:
            if conn.execute("SELECT id FROM platform_ledger WHERE idempotency_key=?", (key,)).fetchone():
                return False
            conn.execute("""INSERT INTO platform_ledger(store_id,kind,description,amount,created_at,idempotency_key,payload_hash)
                VALUES(?,?,?,?,?,?,?)""", (store_id, "receipt", description, amount, h.now(), key, "mercadopago"))
            current = conn.execute("SELECT paid_until FROM stores WHERE id=?", (store_id,)).fetchone()[0]
            conn.execute("UPDATE stores SET paid_until=? WHERE id=?", (extend_paid_until(current, paid_on), store_id))
        return True

    def sync(store):
        if not store["sub_id"] or not config.get("MP_PLATFORM_ACCESS_TOKEN"):
            return store
        h.db().execute("UPDATE stores SET sub_checked_at=? WHERE id=?", (h.now(), store["id"]))
        detail = mp().get_preapproval(token(), store["sub_id"])
        if detail.get("external_reference") not in (None, "", f"store-{store['id']}"):
            return store
        status = detail.get("status") or store["sub_status"]
        next_payment = (detail.get("next_payment_date") or "")[:25]
        h.db().execute("UPDATE stores SET sub_status=?,sub_next_payment=? WHERE id=?", (status, next_payment, store["id"]))
        results = mp().authorized_payments(token(), store["sub_id"]).get("results") or []
        for item in results:
            payment = item.get("payment") or {}
            if payment.get("status") != "approved":
                continue
            amount = round(float(item.get("transaction_amount") or 0) * 100)
            if amount <= 0:
                continue
            raw_date = (item.get("debit_date") or item.get("date_created") or h.now())[:10]
            try:
                paid_on = date.fromisoformat(raw_date)
            except ValueError:
                paid_on = datetime.now(ZONE).date()
            record_payment(store["id"], payment.get("id") or item.get("id"), amount, paid_on, "Assinatura mensal (Mercado Pago)")
        return h.one("SELECT * FROM stores WHERE id=?", (store["id"],))

    app.extensions["billing_sync"] = sync
    app.extensions["billing_info"] = info
    app.extensions["billing_record_payment"] = record_payment

    def fresh(store, minutes=30):
        """Consulta o Mercado Pago de vez em quando, mesmo sem webhook configurado."""
        last = store["sub_checked_at"]
        if store["sub_id"] and (not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(minutes=minutes)):
            try:
                return sync(store)
            except PaymentError:
                app.logger.warning("Não foi possível consultar a assinatura da loja %s", store["id"])
        return store

    app.extensions["billing_fresh"] = fresh

    @app.get("/api/admin/billing")
    @h.owner
    def billing_status():
        return jsonify(info(fresh(g.store, 5)))

    @app.post("/api/admin/billing/subscribe")
    @h.owner
    def billing_subscribe():
        store = g.store
        if store["billing_exempt"]:
            abort(409, description="Sua loja tem uso gratuito, não precisa assinar.")
        if store["sub_status"] == "authorized":
            abort(409, description="Sua assinatura já está ativa.")
        payer = h.text(h.data(), "payer_email", 5, 254).lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", payer):
            abort(400, description="Informe o e-mail da sua conta do Mercado Pago.")
        h.limited("billing-subscribe", 10, 3600)
        recurring = {"frequency": 1, "frequency_type": "months", "transaction_amount": round(price() / 100, 2), "currency_id": "BRL"}
        if config["PLAN_FREE_MONTHS"] > 0 and not store["sub_used_trial"]:
            recurring["free_trial"] = {"frequency": config["PLAN_FREE_MONTHS"], "frequency_type": "months"}
        payload = {"reason": "SeuComércioAqui - Plano mensal", "external_reference": f"store-{store['id']}",
                   "payer_email": payer, "back_url": h.public_base() + "/painel?assinatura=1",
                   "auto_recurring": recurring, "status": "pending"}
        if store["sub_id"] and store["sub_status"] == "pending":
            try:
                mp().update_preapproval(token(), store["sub_id"], {"status": "cancelled"})
            except PaymentError:
                pass
        try:
            created = mp().create_preapproval(token(), payload)
        except PaymentError as error:
            abort(502, description="O Mercado Pago não aceitou criar a assinatura agora. " + str(error))
        if not created.get("id") or not created.get("init_point"):
            abort(502, description="O Mercado Pago não devolveu o link da assinatura.")
        h.db().execute("UPDATE stores SET sub_id=?,sub_status=?,sub_payer_email=?,sub_used_trial=?,sub_checked_at=? WHERE id=?",
                       (created["id"], created.get("status") or "pending", payer, int(bool(recurring.get("free_trial")) or store["sub_used_trial"]), h.now(), store["id"]))
        h.audit("billing.subscribe", payer, store["id"])
        return jsonify(init_point=created["init_point"])

    @app.post("/api/admin/billing/sync")
    @h.owner
    def billing_refresh():
        try:
            store = sync(g.store)
        except PaymentError as error:
            abort(502, description=str(error))
        return jsonify(info(store))

    @app.post("/api/admin/billing/cancel")
    @h.owner
    def billing_cancel():
        if not g.store["sub_id"] or g.store["sub_status"] not in ("authorized", "pending", "paused"):
            abort(409, description="Não há assinatura ativa para cancelar.")
        try:
            mp().update_preapproval(token(), g.store["sub_id"], {"status": "cancelled"})
        except PaymentError as error:
            abort(502, description=str(error))
        h.db().execute("UPDATE stores SET sub_status='cancelled' WHERE id=?", (g.store["id"],))
        h.audit("billing.cancel", "", g.store["id"])
        return jsonify(info(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))))

    @app.post("/webhooks/mercadopago-assinaturas/<secret>")
    def billing_webhook(secret):
        h.limited("billing-webhook", 300, 60)
        if secret != webhook_secret():
            return jsonify(ok=True)
        body = request.get_json(silent=True) or {}
        kind = body.get("type") or request.args.get("type") or ""
        ref = str((body.get("data") or {}).get("id") or request.args.get("data.id") or "")
        try:
            if kind == "subscription_authorized_payment" and ref.isdigit():
                ref = str(mp().authorized_payment(token(), ref).get("preapproval_id") or "")
            if ref and re.fullmatch(r"[A-Za-z0-9_-]{6,80}", ref):
                store = h.one("SELECT * FROM stores WHERE sub_id=?", (ref,))
                if store:
                    sync(store)
        except PaymentError:
            pass
        return jsonify(ok=True)

    @app.get("/api/platform/billing")
    def platform_billing():
        platform_only()
        stores = h.rows("SELECT * FROM stores")
        states = [billing_state(s) for s in stores]
        paying = sum(st in ("active", "paid") for st in states)
        return jsonify(configured=bool(config.get("MP_PLATFORM_ACCESS_TOKEN")), price=price(), free_months=config["PLAN_FREE_MONTHS"],
                       trial_days=config["TRIAL_DAYS"], webhook_url=h.public_base() + "/webhooks/mercadopago-assinaturas/" + webhook_secret(),
                       paying=paying, trial=states.count("trial"), exempt=states.count("exempt"),
                       blocked=sum(st not in OK_STATES for st in states), monthly_recurring=paying * price())

    @app.post("/api/platform/billing/sync")
    def platform_billing_sync():
        platform_only()
        done = 0
        for store in h.rows("SELECT * FROM stores WHERE sub_id!='' ORDER BY sub_checked_at LIMIT 50"):
            try:
                sync(store)
                done += 1
            except PaymentError:
                continue
        return jsonify(synced=done)


def apply_exemptions(conn, config):
    """Marca como isentas as lojas cujos donos estão na lista (hash do e-mail ou variável de ambiente)."""
    listed = {e.strip().lower() for e in config.get("BILLING_EXEMPT_EMAILS", "").split(",") if e.strip()}
    hashes = EXEMPT_HASHES | {hashlib.sha256(e.encode()).hexdigest() for e in listed}
    for row in conn.execute("SELECT s.id,u.email FROM stores s JOIN users u ON u.id=s.owner_id WHERE s.billing_exempt=0").fetchall():
        if hashlib.sha256(row[1].strip().lower().encode()).hexdigest() in hashes:
            conn.execute("UPDATE stores SET billing_exempt=1 WHERE id=?", (row[0],))


def first_billing_migration(conn, config):
    """Uma vez: lojas antigas ganham 3 dias para assinar, em vez de serem pausadas na hora."""
    if conn.execute("SELECT value FROM platform_settings WHERE key='billing_v1'").fetchone():
        return
    grace = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(timespec="seconds")
    conn.execute("UPDATE stores SET trial_until=? WHERE sub_id='' AND paid_until='' AND billing_exempt=0 AND (trial_until='' OR trial_until<?)",
                 (grace, grace))
    conn.execute("UPDATE stores SET monthly_fee=? WHERE monthly_fee=0", (config["PLAN_PRICE"],))
    conn.execute("INSERT INTO platform_settings(key,value) VALUES('billing_v1',?)", (json.dumps({"at": grace}),))
