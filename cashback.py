"""Cashback em centavos; resgate exige prova de posse do WhatsApp."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

from flask import abort,g,jsonify,request

from connectors import Evolution
from marketing import NORMAL_PHONE,phone_key,validate_phone

DDL="""
CREATE TABLE IF NOT EXISTS wallet_challenges (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), phone TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
 code_hash TEXT NOT NULL, expires_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, used_at TEXT
);
CREATE TABLE IF NOT EXISTS wallet_sessions (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), phone TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cashback_movements (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), phone TEXT NOT NULL,
 order_id INTEGER NOT NULL REFERENCES orders(id), delta INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('redemption','reversal')),
 created_at TEXT NOT NULL, UNIQUE(order_id,kind)
);
CREATE INDEX IF NOT EXISTS ix_cashback_phone ON cashback_movements(store_id,phone);
"""


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def wallet_balance(conn,sid,phone):
    earned=conn.execute(f"SELECT COALESCE(SUM(cashback_earned),0) FROM orders WHERE store_id=? AND {NORMAL_PHONE}=? AND status='completed' AND paid=1",(sid,phone)).fetchone()[0]
    spent=conn.execute('SELECT COALESCE(SUM(delta),0) FROM cashback_movements WHERE store_id=? AND phone=?',(sid,phone)).fetchone()[0]
    return max(0,earned+spent)


def register_cashback(app,helpers):
    h=SimpleNamespace(**helpers)

    def provider():
        return app.extensions.get('evolution') or Evolution(app.config.get('EVOLUTION_API_URL',''),app.config.get('EVOLUTION_API_KEY',''))

    def store(slug):
        s=h.one('SELECT * FROM stores WHERE slug=?',(slug,))
        if not s:abort(404,description='Loja não encontrada.')
        return s

    def authenticated(conn,sid,token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,80}',token):
            abort(401,description='Confirme seu telefone para usar o cashback.')
        session=conn.execute('SELECT * FROM wallet_sessions WHERE store_id=? AND token_hash=? AND expires_at>?',(sid,digest(token),h.now())).fetchone()
        if not session:abort(401,description='A confirmação do cashback expirou. Solicite um novo código.')
        return session['phone']

    @app.post('/api/store/<slug>/wallet/code')
    def wallet_code(slug):
        s=store(slug);value=h.data();phone=validate_phone(value.get('phone'))
        h.limited('wallet-code',6,900)
        h.limited('wallet-code:'+str(s['id'])+':'+digest(phone),3,900,per_ip=False)
        if not s['cashback_enabled'] or not s['wa_instance'] or not provider().ready:
            abort(409,description='O cashback desta loja ainda não está disponível.')
        token,code=secrets.token_urlsafe(32),str(secrets.randbelow(1000000)).zfill(6)
        code_hash=hmac.new(app.config['SECRET_KEY'].encode(),(token+':'+code).encode(),'sha256').hexdigest()
        with h.transaction() as conn:
            conn.execute('DELETE FROM wallet_challenges WHERE expires_at<?',(h.now(),))
            conn.execute('DELETE FROM wallet_sessions WHERE expires_at<?',(h.now(),))
            conn.execute('UPDATE wallet_challenges SET used_at=? WHERE store_id=? AND phone=? AND used_at IS NULL',(h.now(),s['id'],phone))
            cid=conn.execute('INSERT INTO wallet_challenges(store_id,phone,token_hash,code_hash,expires_at) VALUES(?,?,?,?,?)',(s['id'],phone,digest(token),code_hash,(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(timespec='seconds'))).lastrowid
        try:
            status,_=provider().send_text(s['wa_instance'],phone,f'Seu código de cashback na {s["name"]}: {code}. Válido por 5 minutos. Não compartilhe este código.')
        except Exception:status=0
        if status not in (200,201):
            h.db().execute('UPDATE wallet_challenges SET used_at=? WHERE id=?',(h.now(),cid))
            abort(502,description='Não foi possível enviar o código. Tente novamente mais tarde.')
        return jsonify(challenge=token)

    @app.post('/api/store/<slug>/wallet/verify')
    def wallet_verify(slug):
        s=store(slug);value=h.data();h.limited('wallet-verify',30,900)
        token=h.text(value,'challenge',40,80);code=h.text(value,'code',6,6)
        proposed=hmac.new(app.config['SECRET_KEY'].encode(),(token+':'+code).encode(),'sha256').hexdigest()
        valid=False;wallet_token=None
        with h.transaction() as conn:
            challenge=conn.execute('SELECT * FROM wallet_challenges WHERE store_id=? AND token_hash=?',(s['id'],digest(token))).fetchone()
            if challenge and not challenge['used_at'] and challenge['expires_at']>h.now() and challenge['attempts']<5:
                conn.execute('UPDATE wallet_challenges SET attempts=attempts+1 WHERE id=?',(challenge['id'],))
                valid=hmac.compare_digest(challenge['code_hash'],proposed)
                if valid:
                    wallet_token=secrets.token_urlsafe(32)
                    conn.execute('UPDATE wallet_challenges SET used_at=? WHERE id=?',(h.now(),challenge['id']))
                    conn.execute('INSERT INTO wallet_sessions(store_id,phone,token_hash,expires_at) VALUES(?,?,?,?)',(s['id'],challenge['phone'],digest(wallet_token),(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(timespec='seconds')))
                    balance=wallet_balance(conn,s['id'],challenge['phone'])
        if not valid:abort(400,description='Código inválido, expirado ou com tentativas esgotadas.')
        return jsonify(token=wallet_token,balance=balance)

    @app.get('/api/store/<slug>/wallet')
    def wallet_get(slug):
        s=store(slug)
        phone=authenticated(h.db(),s['id'],request.headers.get('Authorization','').removeprefix('Bearer '))
        return jsonify(balance=wallet_balance(h.db(),s['id'],phone))

    @app.get('/api/admin/cashback')
    @h.owner
    def cashback_settings():
        return jsonify(enabled=bool(g.store['cashback_enabled']),bps=g.store['cashback_bps'],
            configured=provider().ready and bool(g.store['wa_instance']),
            movements=h.rows('SELECT m.*,o.number FROM cashback_movements m JOIN orders o ON o.id=m.order_id WHERE m.store_id=? ORDER BY m.id DESC LIMIT 100',(g.store['id'],)))

    @app.put('/api/admin/cashback')
    @h.owner
    def cashback_save():
        value=h.data();enabled=h.boolean(value,'enabled');bps=h.integer(value,'bps',maximum=2000)
        if enabled and (not provider().ready or not g.store['wa_instance'] or not bps):
            abort(409,description='Conecte o WhatsApp e informe o percentual para ativar o cashback.')
        h.db().execute('UPDATE stores SET cashback_enabled=?,cashback_bps=? WHERE id=?',(enabled,bps,g.store['id']))
        return jsonify(ok=True)

    def discount(conn,s,value,maximum):
        amount=h.integer(value,'cashback_use',default=0,maximum=10**9)
        if not amount:return 0
        if not s['cashback_enabled']:abort(409,description='O resgate de cashback está pausado nesta loja.')
        phone=authenticated(conn,s['id'],value.get('wallet_token'))
        if phone!=phone_key(value.get('phone','')):abort(403,description='O cashback pertence ao telefone confirmado.')
        balance=wallet_balance(conn,s['id'],phone)
        if amount>balance:abort(409,description='O saldo de cashback mudou. Confira e tente novamente.')
        return min(amount,maximum)

    def reserve(conn,s,oid,value,amount,remaining):
        phone=phone_key(value.get('phone',''))
        earned=(remaining*s['cashback_bps'])//10000 if s['cashback_enabled'] and len(phone) in (10,11) else 0
        conn.execute('UPDATE orders SET cashback_discount=?,cashback_earned=? WHERE id=?',(amount,earned,oid))
        if amount:
            conn.execute('INSERT INTO cashback_movements(store_id,phone,order_id,delta,kind,created_at) VALUES(?,?,?,?,?,?)',(s['id'],phone,oid,-amount,'redemption',h.now()))

    def restore(conn,sid,oid):
        move=conn.execute("SELECT * FROM cashback_movements WHERE store_id=? AND order_id=? AND kind='redemption'",(sid,oid)).fetchone()
        if move:
            conn.execute("INSERT INTO cashback_movements(store_id,phone,order_id,delta,kind,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(order_id,kind) DO NOTHING",(sid,move['phone'],oid,-move['delta'],'reversal',h.now()))

    app.extensions.update(wallet_discount=discount,wallet_reserve=reserve,wallet_restore=restore)
