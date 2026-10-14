"""CRM, campanhas revisáveis e recuperação de sacolas com autorização do cliente."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote

from flask import abort, g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

SEGMENTS = {'all': 'Todos', 'new': 'Primeira compra', 'loyal': 'Recorrentes', 'vip': 'VIP', 'inactive': 'Sem comprar há 30 dias'}
PHONE = "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,' ',''),'-',''),'(',''),')',''),'+','')"
NORMAL_PHONE = f"CASE WHEN LENGTH({PHONE})>11 AND SUBSTR({PHONE},1,2)='55' THEN SUBSTR({PHONE},3) ELSE {PHONE} END"


def phone_key(phone):
    digits = re.sub(r'\D', '', phone or '')
    return digits[2:] if len(digits) > 11 and digits.startswith('55') else digits


def validate_phone(value):
    if not isinstance(value, str) or len(value) > 20 or not re.fullmatch(r'[0-9+() \-]+', value):
        abort(400, description='Informe um WhatsApp válido com DDD.')
    key = phone_key(value)
    if len(key) not in (10, 11) or not key.strip('0'):
        abort(400, description='Informe um WhatsApp válido com DDD.')
    return key


def register_marketing(app, helpers):
    h = SimpleNamespace(**helpers)
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

    def sign(kind, sid, record):
        return signer.dumps([sid, record], salt='marketing-' + kind)

    def read_token(kind, token, sid, seconds):
        try:
            store_id, record = signer.loads(token, salt='marketing-' + kind, max_age=seconds)
        except (BadSignature, ValueError, TypeError):
            abort(404, description='Este link expirou ou não está disponível.')
        if store_id != sid:
            abort(404, description='Este link não pertence a esta loja.')
        return record

    def store(slug):
        value = h.one('SELECT * FROM stores WHERE slug=?', (slug,))
        if not value:
            abort(404, description='Loja não encontrada.')
        return value

    def stamp_before(days=0, minutes=0):
        return (datetime.now(timezone.utc) - timedelta(days=days, minutes=minutes)).isoformat(timespec='seconds')

    def hash_token(token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,80}', token):
            abort(400, description='Sessão do cardápio inválida.')
        return hashlib.sha256(token.encode()).hexdigest()

    def opted_order(conn, sid, oid, value):
        consent = h.boolean(value, 'marketing_consent')
        if consent:
            phone = validate_phone(value['phone'])
            conn.execute('''INSERT INTO customer_opt_ins(store_id,phone,consent,updated_at) VALUES(?,?,1,?)
                ON CONFLICT(store_id,phone) DO UPDATE SET consent=1,updated_at=excluded.updated_at''', (sid, phone, h.now()))
        token = value.get('shopping_token')
        if token:
            conn.execute('''UPDATE shopping_sessions SET order_id=?,items='[]',phone='',customer='',recovery_consent=0,updated_at=?
                WHERE store_id=? AND token_hash=? AND order_id IS NULL''', (oid, h.now(), sid, hash_token(token)))
        recovery = value.get('recovery_token')
        if recovery:
            record = read_token('cart', recovery, sid, 7 * 86400)
            conn.execute('''UPDATE shopping_sessions SET order_id=?,items='[]',phone='',customer='',recovery_consent=0,updated_at=?
                WHERE store_id=? AND id=? AND order_id IS NULL AND recovery_consent=1''', (oid, h.now(), sid, record))

    app.extensions['marketing_order'] = opted_order

    @app.post('/api/store/<slug>/shopping')
    def shopping_event(slug):
        h.limited('shopping', 180)
        s, value = store(slug), h.data()
        event = value.get('event')
        if event not in ('visit', 'cart', 'checkout'):
            abort(400, description='Etapa do cardápio inválida.')
        token = value.get('token') or secrets.token_urlsafe(32)
        digest = hash_token(token)
        consent = h.boolean(value, 'recovery_consent')
        customer = h.text(value, 'customer', 2, 100) if consent else ''
        phone = validate_phone(value.get('phone')) if consent else ''
        with h.transaction() as conn:
            existing = conn.execute('SELECT * FROM shopping_sessions WHERE store_id=? AND token_hash=?', (s['id'], digest)).fetchone()
            if value.get('token') and not existing:
                abort(404, description='Sessão expirada. Abra o cardápio novamente.')
            if existing and existing['order_id']:
                return jsonify(token=token)
            items, subtotal = [], 0
            if event != 'visit':
                raw = value.get('items')
                if not isinstance(raw, list) or len(raw) > 50:
                    abort(400, description='Sacola inválida.')
                if raw:
                    subtotal, _, prepared = h.price_items(conn, s, raw)
                    items = [{'product_id': p['id'], 'quantity': qty, 'option_ids': [x['id'] for x in extras], 'notes': ''}
                        for p, qty, _, extras, _, _ in prepared]
            stamp = h.now()
            if not existing:
                record = conn.execute('INSERT INTO shopping_sessions(store_id,token_hash,created_at,updated_at) VALUES(?,?,?,?)',
                    (s['id'], digest, stamp, stamp)).lastrowid
            else:
                record = existing['id']
            if event != 'visit':
                conn.execute('''UPDATE shopping_sessions SET items=?,subtotal=?,customer=?,phone=?,recovery_consent=?,updated_at=?,
                    cart_at=COALESCE(cart_at,?),checkout_at=COALESCE(checkout_at,?) WHERE id=?''',
                    (json.dumps(items), subtotal, customer, phone, consent if items else 0, stamp, stamp if items else None,
                     stamp if event == 'checkout' and items else None, record))
            # Short retention for anonymous sessions and unfinished checkout contacts.
            conn.execute('DELETE FROM shopping_sessions WHERE store_id=? AND created_at<?', (s['id'], stamp_before(days=30)))
            conn.execute("UPDATE shopping_sessions SET phone='',customer='',items='[]',recovery_consent=0 WHERE store_id=? AND updated_at<?",
                (s['id'], stamp_before(days=7)))
        return jsonify(token=token)

    @app.get('/api/store/<slug>/recover/<token>')
    def recover_cart(slug, token):
        h.limited('recover', 60)
        s = store(slug)
        record = read_token('cart', token, s['id'], 7 * 86400)
        lead = h.one('SELECT * FROM shopping_sessions WHERE store_id=? AND id=?', (s['id'], record))
        if not lead or lead['order_id'] or not lead['recovery_consent'] or lead['updated_at'] < stamp_before(days=7):
            abort(404, description='Esta sacola expirou ou já foi concluída.')
        # Contact details never appear in the public recovery response.
        return jsonify(items=json.loads(lead['items']))

    @app.post('/api/store/<slug>/unsubscribe/<token>')
    def marketing_unsubscribe(slug, token):
        s = store(slug)
        record = read_token('optout', token, s['id'], 366 * 86400)
        with h.transaction() as conn:
            profile = conn.execute('SELECT phone FROM customer_opt_ins WHERE id=? AND store_id=?', (record, s['id'])).fetchone()
            if not profile:
                abort(404, description='Preferência não encontrada.')
            conn.execute('UPDATE customer_opt_ins SET consent=0,updated_at=? WHERE id=? AND store_id=?', (h.now(), record, s['id']))
            conn.execute("UPDATE shopping_sessions SET recovery_consent=0,phone='',customer='' WHERE store_id=? AND phone=?", (s['id'], profile['phone']))
        return jsonify(ok=True)

    @app.post('/api/store/<slug>/recovery-unsubscribe/<token>')
    def recovery_unsubscribe(slug, token):
        s = store(slug)
        record = read_token('cart', token, s['id'], 7 * 86400)
        h.db().execute("UPDATE shopping_sessions SET recovery_consent=0,phone='',customer='',items='[]' WHERE id=? AND store_id=?", (record, s['id']))
        return jsonify(ok=True)

    def customers(sid):
        records = h.rows(f'''SELECT {NORMAL_PHONE} AS phone,MAX(customer) AS name,
            COUNT(*) AS orders,SUM(total) AS spent,MIN(created_at) AS first_order,MAX(created_at) AS last_order
            FROM orders WHERE store_id=? AND status='completed' GROUP BY {NORMAL_PHONE} ORDER BY spent DESC''', (sid,))
        profiles = {p['phone']: p for p in h.rows('SELECT id,phone,consent FROM customer_opt_ins WHERE store_id=?', (sid,))}
        output = []
        for c in records:
            if len(c['phone']) not in (10, 11) or not c['phone'].strip('0'):
                continue
            c['ticket'] = c['spent'] // c['orders']
            c['days_since'] = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(c['last_order'])).days)
            c['segment'] = 'inactive' if c['days_since'] >= 30 else 'vip' if c['orders'] >= 5 else 'new' if c['orders'] == 1 else 'loyal'
            profile = profiles.get(c['phone'])
            c['consent'] = bool(profile and profile['consent'])
            c['profile_id'] = profile['id'] if profile else None
            output.append(c)
        return output

    @app.get('/api/admin/marketing')
    @h.owner
    def marketing_overview():
        sid = g.store['id']
        start = stamp_before(days=30)
        funnel = dict(h.one('''SELECT COUNT(*) AS visits,
            COUNT(cart_at) AS carts,COUNT(checkout_at) AS checkouts,COUNT(DISTINCT order_id) AS orders
            FROM shopping_sessions WHERE store_id=? AND created_at>=?''', (sid, start)))
        funnel['conversion'] = round(funnel['orders'] * 100 / funnel['visits'], 1) if funnel['visits'] else 0
        audience = customers(sid)
        abandoned = h.rows(f'''SELECT c.id,c.customer,c.phone,c.subtotal,c.updated_at FROM shopping_sessions c
            WHERE c.store_id=? AND c.order_id IS NULL AND c.recovery_consent=1 AND c.items!='[]'
            AND c.updated_at<=? AND c.updated_at>=?
            AND NOT EXISTS(SELECT 1 FROM orders WHERE store_id=c.store_id AND {NORMAL_PHONE}=c.phone
                AND status!='cancelled' AND created_at>=c.updated_at)
            AND NOT EXISTS(SELECT 1 FROM shopping_sessions newer WHERE newer.store_id=c.store_id AND newer.phone=c.phone
                AND newer.id>c.id AND newer.recovery_consent=1)
            ORDER BY c.updated_at DESC LIMIT 100''', (sid, stamp_before(minutes=30), stamp_before(days=7)))
        for lead in abandoned:
            token = sign('cart', sid, lead['id'])
            url = h.public_base() + '/loja/' + quote(g.store['slug']) + '?recuperar=' + quote(token)
            optout = h.public_base() + '/loja/' + quote(g.store['slug']) + '?cancelar_recuperacao=' + quote(token)
            lead['message'] = f"Olá, {lead['customer'].split(' ')[0]}! Sua sacola na {g.store['name']} ficou salva. Quer continuar? {url}\nNão receber lembretes desta sacola: {optout}"
        return jsonify(funnel=funnel, customers=audience, abandoned=abandoned, segments=SEGMENTS,
            campaigns=h.rows('SELECT * FROM marketing_campaigns WHERE store_id=? ORDER BY id DESC LIMIT 30', (sid,)),
            suggested=h.rows('SELECT id,name,suggested,active FROM products WHERE store_id=? ORDER BY name', (sid,)))

    @app.put('/api/admin/marketing/suggestions')
    @h.owner
    def marketing_suggestions():
        ids = h.data().get('product_ids')
        if not isinstance(ids, list) or len(ids) > 12 or any(isinstance(x, bool) or not isinstance(x, int) for x in ids) or len(set(ids)) != len(ids):
            abort(400, description='Escolha até 12 produtos diferentes para sugerir.')
        with h.transaction() as conn:
            for pid in ids:
                product = h.owned('products', pid)
                if not product['active']:
                    abort(400, description='Sugira apenas produtos ativos.')
            conn.execute('UPDATE products SET suggested=0 WHERE store_id=?', (g.store['id'],))
            for pid in ids:
                conn.execute('UPDATE products SET suggested=1 WHERE store_id=? AND id=?', (g.store['id'], pid))
        return jsonify(ok=True)

    def campaign_fields(value):
        segment = value.get('segment')
        if segment not in SEGMENTS:
            abort(400, description='Público da campanha inválido.')
        return h.text(value, 'name', 3, 100), segment, h.text(value, 'message', 10, 800)

    @app.post('/api/admin/marketing/campaigns/preview')
    @h.owner
    def campaign_preview():
        h.limited('campaign-preview', 30)
        name, segment, message = campaign_fields(h.data())
        audience = [c for c in customers(g.store['id']) if c['consent'] and (segment == 'all' or c['segment'] == segment)]
        recipients = []
        for c in audience[:100]:
            optout = h.public_base() + '/loja/' + quote(g.store['slug']) + '?cancelar_promocoes=' + quote(sign('optout', g.store['id'], c['profile_id']))
            personalized = message.replace('{nome}', c['name'].split(' ')[0]).replace('{loja}', g.store['name']).replace(
                '{link}', h.public_base() + '/loja/' + quote(g.store['slug']))
            recipients.append({'name': c['name'], 'phone': c['phone'], 'message': personalized + '\nNão receber promoções: ' + optout})
        return jsonify(name=name, total=len(audience), recipients=recipients)

    @app.post('/api/admin/marketing/campaigns')
    @h.owner
    def campaign_save():
        name, segment, message = campaign_fields(h.data())
        cid = h.db().execute('INSERT INTO marketing_campaigns(store_id,name,segment,message,created_at) VALUES(?,?,?,?,?)',
            (g.store['id'], name, segment, message, h.now())).lastrowid
        return jsonify(id=cid), 201
