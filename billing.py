"""Assinatura mensal das lojas, cobrada no cartão pelo Mercado Pago (conta da plataforma).

Regras: teste grátis curto ao criar a conta; ao assinar, o primeiro mês sai por R$ 0
(uma vez por loja) e depois o Mercado Pago cobra o valor do plano todo mês. A loja
recebe pedidos enquanto estiver isenta, em teste ou paga até uma data.
Uma autorização de cartão não substitui o recebimento. Contas isentas são definidas por hash do e-mail (nada de e-mail no código),
pela variável BILLING_EXEMPT_EMAILS ou pelo dono da plataforma na Central.
"""
import hashlib
import io
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

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
    moment = moment or datetime.now(timezone.utc)
    today = moment.astimezone(ZONE).date().isoformat()
    if status == "authorized":
        if _get(store, 'paid_until', '') >= today or trial_active(_get(store, 'trial_until', ''), moment):
            return "active"
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


def billing_timestamp(value):
    """Keep real provider instants; a date without a time/offset is not an instant."""
    if not isinstance(value, str) or 'T' not in value:
        return ''
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            return ''
        return moment.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (ValueError, OverflowError):
        return ''


def amount_cents(value):
    try:
        amount = Decimal(str(value)) * 100
        return int(amount) if amount.is_finite() and amount == amount.to_integral_value() and 0 <= amount <= 100_000_000 else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def secure_checkout_url(value):
    try:
        url = urlsplit(value)
        return bool(url.scheme == 'https' and url.hostname == 'www.mercadopago.com.br'
                    and not url.username and not url.password and url.port in (None,443)
                    and url.path.startswith('/subscriptions/'))
    except (ValueError, TypeError):
        return False


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

    def setting(key, conn=None):
        row=(conn or h.db()).execute('SELECT value FROM platform_settings WHERE key=?',(key,)).fetchone()
        try:return json.loads(row['value']) if row else {}
        except (ValueError,TypeError):return {}

    def remember(key, value, conn=None):
        (conn or h.db()).execute('INSERT INTO platform_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               (key,json.dumps(value,separators=(',',':'))))

    def platform_account():
        if not hasattr(g,'billing_account'):
            value=mp().me(token())
            if not isinstance(value,dict) or not str(value.get('id','')).isdigit():
                raise PaymentError('Não foi possível conferir a conta de recebimento da plataforma.')
            g.billing_account=str(value['id'])
        return g.billing_account

    def matching_payment(value, expected, pid):
        return (isinstance(value,dict) and str(value.get('id',''))==str(pid)
                and value.get('currency_id')=='BRL' and value.get('external_reference')==expected['reference']
                and amount_cents(value.get('transaction_amount'))==expected['amount']
                and str(value.get('collector_id',''))==str(expected['collector']))

    def info(store):
        state = billing_state(store)
        return {"state": state, "ok": state in OK_STATES, "price": price(), "free_months": config["PLAN_FREE_MONTHS"] if not store["sub_used_trial"] else 0,
                "trial_until": store["trial_until"] if trial_active(store["trial_until"]) else "", "sub_status": store["sub_status"],
                "payer_email": store["sub_payer_email"], "next_payment": store["sub_next_payment"], "paid_until": store["paid_until"],
                "configured": bool(config.get("MP_PLATFORM_ACCESS_TOKEN")), "manage_url": "https://www.mercadopago.com.br/subscriptions",
                "pix_pending": bool(store['sub_pix_id']), "pix_expires": store['sub_pix_expires'],
                "payments":h.rows("SELECT amount,description,paid_at,created_at FROM platform_ledger WHERE store_id=? AND is_subscription=1 AND kind='receipt' AND voided_at IS NULL ORDER BY id DESC LIMIT 12",(store['id'],)) if getattr(g,"role",None)=="owner" else []}

    def record_payment(store_id, payment_id, amount, paid_on, description, paid_at='', stack=False):
        """Lança o recebimento na Central do Dono uma única vez e libera a loja até o próximo mês."""
        key = "mp-sub-" + str(payment_id)
        with h.transaction() as conn:
            if conn.execute("SELECT id FROM platform_ledger WHERE idempotency_key=?", (key,)).fetchone():
                return False
            stamp = h.now()
            conn.execute("""INSERT INTO platform_ledger(store_id,kind,description,amount,created_at,idempotency_key,payload_hash,paid_at,is_subscription)
                VALUES(?,?,?,?,?,?,?,?,1)""", (store_id, "receipt", description, amount, stamp, key, "mercadopago", billing_timestamp(paid_at)))
            current = conn.execute("SELECT paid_until FROM stores WHERE id=?", (store_id,)).fetchone()[0]
            if stack and current and current >= paid_on.isoformat():
                paid_on=date.fromisoformat(current)
            conn.execute("UPDATE stores SET paid_until=?,subscribed_at=CASE WHEN subscribed_at='' THEN ? ELSE subscribed_at END WHERE id=?",
                         (extend_paid_until(current, paid_on), stamp, store_id))
        return True

    def sync(store):
        if not store["sub_id"] or not config.get("MP_PLATFORM_ACCESS_TOKEN"):
            return store
        detail=mp().get_preapproval(token(),store['sub_id'])
        expected=setting('billing.subscription.'+store['sub_id']) or {
            'reference':f"store-{store['id']}",'amount':price(),'collector':platform_account(),'free_months':0}
        recurring=detail.get('auto_recurring') or {}
        if (str(detail.get('id',''))!=store['sub_id'] or detail.get('external_reference')!=expected['reference']
                or str(detail.get('collector_id',''))!=str(expected['collector']) or platform_account()!=str(expected['collector'])
                or recurring.get('currency_id')!='BRL' or amount_cents(recurring.get('transaction_amount'))!=expected['amount']
                or recurring.get('frequency')!=1 or recurring.get('frequency_type')!='months'):
            raise PaymentError('Os dados da assinatura não correspondem ao plano e à conta da plataforma. Peça uma conferência ao suporte.')
        status=detail.get('status')
        if status not in ('pending','authorized','paused','cancelled'):
            raise PaymentError('Situação de assinatura não reconhecida. Tente atualizar mais tarde.')
        next_payment=billing_timestamp(detail.get('next_payment_date'))
        stamp=h.now()
        with h.transaction() as conn:
            current=conn.execute('SELECT * FROM stores WHERE id=?',(store['id'],)).fetchone()
            if current['sub_id']!=store['sub_id']:return current
            meta=setting('billing.subscription.'+store['sub_id'],conn) or expected
            if status=='authorized' and meta.get('free_months',0)>0 and not meta.get('trial_granted'):
                until=datetime.fromisoformat(stamp)
                for _ in range(min(meta['free_months'],12)):
                    until=add_month(until)
                trial_until=max(current['trial_until'] or '',until.isoformat(timespec='seconds'))
                conn.execute('UPDATE stores SET trial_until=? WHERE id=?',(trial_until,store['id']))
                meta['trial_granted']=True;remember('billing.subscription.'+store['sub_id'],meta,conn)
            confirmed=stamp if status=='authorized' and current['sub_status']!='authorized' else ''
            conn.execute("UPDATE stores SET sub_status=?,sub_next_payment=?,sub_checked_at=?,subscribed_at=CASE WHEN subscribed_at='' THEN ? ELSE subscribed_at END WHERE id=?",
                         (status,next_payment,stamp,confirmed,store['id']))
        results=mp().authorized_payments(token(),store['sub_id']).get('results') or []
        for item in results:
            if not isinstance(item,dict) or item.get('preapproval_id')!=store['sub_id'] or item.get('currency_id')!='BRL':continue
            payment=item.get('payment') or {};pid=payment.get('id')
            if payment.get('status')!='approved' or not str(pid or '').isdigit():continue
            if h.one('SELECT id FROM platform_ledger WHERE idempotency_key=?',('mp-sub-'+str(pid),)):continue
            approved=mp().get_payment(token(),pid)
            if (not matching_payment(approved,expected,pid) or approved.get('status')!='approved'
                    or amount_cents(approved.get('transaction_amount_refunded',0))!=0):continue
            paid_at=billing_timestamp(approved.get('date_approved'))
            if not paid_at:continue
            paid_on=datetime.fromisoformat(paid_at).astimezone(ZONE).date()
            record_payment(store['id'],pid,expected['amount'],paid_on,'Assinatura mensal (Mercado Pago)',paid_at)
        return h.one('SELECT * FROM stores WHERE id=?',(store['id'],))

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
        if store['sub_pix_id']:
            try:
                paid=check_plan_pix(store)
            except PaymentError:
                abort(502,description='Não foi possível conferir o Pix anterior. Atualize a situação antes de mudar para cartão.')
            if not paid and store['sub_pix_expires']>h.now():
                abort(409,description='Há um Pix de mensalidade ainda válido. Aguarde a confirmação ou o vencimento antes de iniciar a cobrança no cartão.')
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
        account=platform_account()
        if store['sub_id'] and store['sub_status']=='pending':
            detail=mp().get_preapproval(token(),store['sub_id'])
            if (detail.get('external_reference')==f"store-{store['id']}" and str(detail.get('collector_id',''))==account
                    and detail.get('status')=='pending' and secure_checkout_url(detail.get('init_point',''))):
                return jsonify(init_point=detail['init_point'])
            abort(409,description='Há uma assinatura pendente. Atualize a situação antes de iniciar outra.')
        intent_key='billing.creating.card.'+str(store['id'])
        with h.transaction() as conn:
            latest=conn.execute('SELECT sub_id,sub_status,sub_pix_id FROM stores WHERE id=?',(store['id'],)).fetchone()
            if latest['sub_id']!=store['sub_id'] or latest['sub_status']!=store['sub_status'] or (latest['sub_pix_id'] and latest['sub_pix_id']!=store['sub_pix_id']):
                abort(409,description='A assinatura foi atualizada em outra tentativa. Atualize a situação antes de continuar.')
            if setting('billing.creating.pix.'+str(store['id']),conn).get('state')=='creating':
                abort(409,description='Um Pix aguarda conferência. Atualize a situação antes de mudar para cartão.')
            intent=setting(intent_key,conn)
            if intent.get('state') in ('creating','uncertain'):
                abort(409,description='Uma criação de assinatura aguarda conferência. Atualize a situação ou peça ajuda ao suporte antes de repetir.')
            intent={'state':'creating','key':'plan-card-'+secrets.token_hex(16),'at':h.now()}
            remember(intent_key,intent,conn)
        try:
            created=mp().create_preapproval(token(),payload,intent['key'])
        except PaymentError:
            remember(intent_key,{**intent,'state':'uncertain'})
            abort(502,description='Não foi possível confirmar a criação da assinatura. Evite repetir; confira no Mercado Pago ou com o suporte.')
        if not created.get('id') or not secure_checkout_url(created.get('init_point','')):
            remember(intent_key,{**intent,'state':'uncertain'})
            abort(502,description='O Mercado Pago não devolveu um endereço seguro para a assinatura. Peça conferência ao suporte.')
        with h.transaction() as conn:
            remember('billing.subscription.'+str(created['id']),{'store_id':store['id'],'reference':payload['external_reference'],
                     'amount':price(),'collector':account,'free_months':config['PLAN_FREE_MONTHS'] if recurring.get('free_trial') else 0},conn)
            remember(intent_key,{**intent,'state':'done','id':str(created['id'])},conn)
            conn.execute("UPDATE stores SET sub_id=?,sub_status='pending',sub_payer_email=?,sub_used_trial=?,sub_checked_at=? WHERE id=?",
                         (str(created['id']),payer,int(bool(recurring.get('free_trial')) or store['sub_used_trial']),h.now(),store['id']))
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

    # ---------- Mensalidade por Pix (paga um mês por vez)
    def create_plan_pix(amount, reference, description, payer, idempotency, expiration=None):
        expires = datetime.fromisoformat(expiration) if expiration else datetime.now(ZONE) + timedelta(minutes=30)
        payload = {"transaction_amount": round(amount / 100, 2), "payment_method_id": "pix", "description": description,
                   "external_reference": reference, "date_of_expiration": expires.isoformat(timespec="milliseconds"),
                   "payer": {"email": payer}}
        base = h.public_base()
        if base.startswith("https://"):
            payload["notification_url"] = f"{base}/webhooks/mercadopago-assinaturas/{webhook_secret()}"
        result = mp().create_pix(token(), payload, idempotency)
        code = ((result.get("point_of_interaction") or {}).get("transaction_data") or {}).get("qr_code", "")
        if not str(result.get("id", "")).isdigit() or not isinstance(code,str) or not 20<=len(code)<=2048:
            raise PaymentError("O Mercado Pago não devolveu o código Pix. Confira se a sua conta tem uma chave Pix cadastrada.")
        return str(result["id"]), code, expires.astimezone(timezone.utc).isoformat(timespec="seconds")

    def check_plan_pix(store, payment_id=None):
        """Verify a specific immutable intent, including old Pix links after renewal."""
        pid=str(payment_id or store['sub_pix_id'] or '')
        if not pid:return False
        value=mp().get_payment(token(),pid)
        expected=setting('billing.pix.'+pid)
        if not expected:
            # Legacy links have no snapshot: only migrate a full identity match.
            reference=value.get('external_reference','')
            if not isinstance(reference,str) or not re.fullmatch(r"plan-"+str(store['id'])+r"-[a-f0-9]{8,64}",reference):return False
            expected={'store_id':store['id'],'reference':reference,'amount':price(),'collector':platform_account()}
        if (expected.get('store_id')!=store['id'] or platform_account()!=str(expected['collector'])
                or not matching_payment(value,expected,pid) or value.get('payment_method_id')!='pix'):
            return False
        status=value.get('status','pending');expected['status']=status
        remember('billing.pix.'+pid,expected)
        ok=status=='approved' and amount_cents(value.get('transaction_amount_refunded',0))==0
        if ok:
            paid_at=billing_timestamp(value.get('date_approved'))
            # A verified creation instant is the fallback period anchor, never the time of a late poll.
            period_at=paid_at or billing_timestamp(value.get('date_created'))
            if not period_at:return False
            paid_on=datetime.fromisoformat(period_at).astimezone(ZONE).date()
            record_payment(store['id'],'pix-'+pid,expected['amount'],paid_on,'Mensalidade por Pix (Mercado Pago)',paid_at,stack=True)
            h.db().execute("UPDATE stores SET sub_pix_id='',sub_pix_code='',sub_pix_expires='' WHERE id=? AND sub_pix_id=?",(store['id'],pid))
        return ok

    def qr_svg(code):
        import segno
        output = io.BytesIO()
        segno.make(code, error="m").save(output, kind="svg", scale=8, border=2, xmldecl=False)
        response = app.response_class(output.getvalue(), mimetype="image/svg+xml")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/admin/billing/pix")
    @h.owner
    def billing_pix():
        store=g.store
        if store['billing_exempt']:abort(409,description='Sua loja tem uso gratuito, não precisa pagar.')
        if store['sub_status'] in ('authorized','pending','paused'):
            abort(409,description='Sua loja tem uma assinatura no cartão ativa ou pendente. Cancele essa assinatura antes de pagar outro mês por Pix.')
        h.limited('billing-pix',10,3600)
        account=platform_account()
        try:
            if store['sub_pix_id'] and check_plan_pix(store):return jsonify(paid=True,billing=info(h.one('SELECT * FROM stores WHERE id=?',(store['id'],))))
        except PaymentError:
            abort(502,description='Não foi possível conferir o Pix anterior. Tente novamente antes de gerar outra cobrança.')
        if store['sub_pix_code'] and store['sub_pix_expires']>datetime.now(timezone.utc).isoformat():
            meta=setting('billing.pix.'+store['sub_pix_id'])
            return jsonify(code=store['sub_pix_code'],amount=meta.get('amount',price()),expires=store['sub_pix_expires'])
        intent_key='billing.creating.pix.'+str(store['id'])
        with h.transaction() as conn:
            latest=conn.execute('SELECT sub_pix_id,sub_status FROM stores WHERE id=?',(store['id'],)).fetchone()
            if latest['sub_pix_id']!=store['sub_pix_id'] or latest['sub_status'] in ('authorized','pending','paused'):
                abort(409,description='O Pix foi atualizado em outra tentativa. Atualize a situação antes de continuar.')
            if setting('billing.creating.card.'+str(store['id']),conn).get('state') in ('creating','uncertain'):
                abort(409,description='Uma assinatura no cartão aguarda conferência. Atualize a situação antes de gerar Pix.')
            intent=setting(intent_key,conn)
            if intent.get('state')=='creating':
                at=billing_timestamp(intent.get('at'))
                if at and datetime.fromisoformat(at)>datetime.now(timezone.utc)-timedelta(seconds=45):
                    abort(409,description='O Pix está sendo preparado. Aguarde alguns segundos antes de tentar novamente.')
            else:
                intent={'state':'creating','reference':f"plan-{store['id']}-{secrets.token_hex(8)}",'amount':price(),
                        'collector':account,'key':'plan-pix-'+secrets.token_hex(16),'expires':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),
                        'payer':g.user['email']}
            intent['at']=h.now();remember(intent_key,intent,conn)
        try:
            pid,code,expires=create_plan_pix(intent['amount'],intent['reference'],'SeuComércioAqui - mensalidade',
                                             intent['payer'],intent['key'],intent['expires'])
        except PaymentError:
            abort(502,description='Não foi possível confirmar a geração do Pix. A próxima tentativa recupera a mesma cobrança; aguarde alguns segundos.')
        with h.transaction() as conn:
            remember('billing.pix.'+pid,{'store_id':store['id'],'reference':intent['reference'],'amount':intent['amount'],
                     'collector':intent['collector'],'expires':expires,'status':'pending'},conn)
            remember(intent_key,{**intent,'state':'done','id':pid},conn)
            conn.execute('UPDATE stores SET sub_pix_id=?,sub_pix_code=?,sub_pix_expires=? WHERE id=?',(pid,code,expires,store['id']))
        h.audit('billing.pix',pid,store['id'])
        return jsonify(code=code,amount=intent['amount'],expires=expires)

    @app.get("/api/admin/billing/pix.svg")
    @h.owner
    def billing_pix_qr():
        if not g.store["sub_pix_code"]:
            abort(404, description="Gere o Pix primeiro.")
        return qr_svg(g.store["sub_pix_code"])

    @app.post("/api/admin/billing/pix/check")
    @h.owner
    def billing_pix_check():
        h.limited("billing-pix-check", 120)
        try:
            paid = check_plan_pix(g.store)
        except PaymentError as error:
            abort(502, description=str(error))
        return jsonify(paid=paid or (not g.store["sub_pix_id"] and billing_state(g.store)=="paid"), expired=bool(g.store["sub_pix_expires"] and g.store["sub_pix_expires"]<h.now()), billing=info(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))))

    # ---------- Teste de R$ 1,00 do dono da plataforma
    def test_pix_state():
        row = h.one("SELECT value FROM platform_settings WHERE key='test_pix'")
        return json.loads(row["value"]) if row else {}

    @app.post("/api/platform/billing/test-pix")
    def platform_test_pix():
        platform_only()
        h.limited("platform-test-pix", 10, 3600)
        reference=f"teste-{secrets.token_hex(6)}"
        try:
            collector=platform_account()
            payer=h.one('SELECT email FROM users WHERE id=?',(g.user['id'],))['email']
            pid, code, expires = create_plan_pix(100, reference, "SeuComércioAqui - teste de R$ 1,00",
                                                 payer, "teste-" + secrets.token_hex(10))
        except PaymentError as error:
            abort(502, description=str(error))
        state = {"id": pid, "code": code, "expires": expires, "status": "pending",'reference':reference,'amount':100,'collector':collector}
        remember('test_pix',state)
        return jsonify(state)

    @app.get("/api/platform/billing/test-pix.svg")
    def platform_test_pix_qr():
        platform_only()
        state = test_pix_state()
        if not state.get("code"):
            abort(404, description="Gere o Pix de teste primeiro.")
        return qr_svg(state["code"])

    @app.post("/api/platform/billing/test-pix/check")
    def platform_test_pix_check():
        platform_only()
        state = test_pix_state()
        if not state.get("id"):
            abort(404, description="Gere o Pix de teste primeiro.")
        try:
            payment = mp().get_payment(token(), state["id"])
            valid=(state.get('reference') and state.get('collector') and platform_account()==str(state['collector'])
                   and matching_payment(payment,state,state['id']) and payment.get('payment_method_id')=='pix')
        except PaymentError as error:
            abort(502, description=str(error))
        if not valid:
            abort(409,description='Os dados do teste não puderam ser conferidos. Consulte o Mercado Pago antes de gerar outro.')
        state["status"] = payment.get("status", "pending")
        state["net"] = amount_cents((payment.get("transaction_details") or {}).get("net_received_amount") or 0) or 0
        h.db().execute("UPDATE platform_settings SET value=? WHERE key='test_pix'", (json.dumps(state),))
        return jsonify(status=state["status"], approved=state["status"] == "approved" and amount_cents(payment.get('transaction_amount_refunded',0))==0, net=state["net"])

    @app.post("/webhooks/mercadopago-assinaturas/<secret>")
    def billing_webhook(secret):
        h.limited("billing-webhook", 300, 60)
        if secret != webhook_secret():
            return jsonify(ok=True)
        body = request.get_json(silent=True) or {}
        if not isinstance(body,dict) or not isinstance(body.get('data',{}),dict):abort(400)
        kind = body.get("type") or request.args.get("type") or ""
        ref = str((body.get("data") or {}).get("id") or request.args.get("data.id") or "")
        try:
            if kind == "payment" and ref.isdigit():
                meta=setting('billing.pix.'+ref)
                store=h.one('SELECT * FROM stores WHERE id=?',(meta['store_id'],)) if meta.get('store_id') else h.one('SELECT * FROM stores WHERE sub_pix_id=?',(ref,))
                if store:
                    check_plan_pix(store,ref)
                return jsonify(ok=True)
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
