"""Single-use password recovery; no token is stored in clear text or returned by API."""
import hashlib
import json
import re
import secrets
import smtplib
import ssl
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from flask import abort, jsonify, session
from werkzeug.security import generate_password_hash
from payments import NoRedirect

DDL = """
CREATE TABLE IF NOT EXISTS account_tokens (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 token_hash TEXT NOT NULL UNIQUE, auth_version INTEGER NOT NULL,
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_account_tokens_user ON account_tokens(user_id,created_at);
"""


def mail_ready(app):
    if app.extensions.get('recovery_mailer'):
        return True
    if app.config.get('RECOVERY_EMAIL_PROVIDER') == 'resend':
        return all(app.config.get(k) for k in ('RESEND_API_KEY','MAIL_FROM','PUBLIC_URL'))
    return app.config.get('RECOVERY_EMAIL_PROVIDER') == 'smtp' and all(app.config.get(k) for k in
        ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM', 'PUBLIC_URL'))


def send_recovery(config, recipient, url):
    body = ('Recebemos um pedido para redefinir sua senha.\n\n'
        + url + '\n\nO link vale por 30 minutos e pode ser usado uma única vez. '
        'Se não foi você, ignore esta mensagem. Sua senha continua a mesma.\n'
        'Depois da troca, será necessário entrar novamente em todos os aparelhos.')
    if config.get('RECOVERY_EMAIL_PROVIDER') == 'resend':
        payload = {'from':config['MAIL_FROM'], 'to':[recipient], 'subject':'Redefina sua senha • SeuComércioAqui', 'text':body}
        req = Request('https://api.resend.com/emails',data=json.dumps(payload).encode(),method='POST',
            headers={'Content-Type':'application/json','Authorization':'Bearer '+config['RESEND_API_KEY'],
                     'Idempotency-Key':hashlib.sha256(url.encode()).hexdigest()})
        with build_opener(NoRedirect).open(req,timeout=8) as response:
            raw=response.read(65537)
            if len(raw)>65536 or not isinstance(json.loads(raw).get('id'),str):
                raise ValueError('O serviço de e-mail não confirmou o envio.')
        return
    message = EmailMessage()
    message['Subject'] = 'Redefina sua senha • SeuComércioAqui'
    message['From'] = config['SMTP_FROM']
    message['To'] = recipient
    message.set_content(body)
    context = ssl.create_default_context()
    port = int(config.get('SMTP_PORT', 587))
    if port not in (465, 587):
        raise ValueError('Use SMTP com TLS na porta 465 ou 587.')
    smtp = (smtplib.SMTP_SSL(config['SMTP_HOST'], port, timeout=8, context=context) if port == 465
            else smtplib.SMTP(config['SMTP_HOST'], port, timeout=8))
    with smtp:
        if port == 587:
            smtp.starttls(context=context)
        smtp.login(config['SMTP_USER'], config['SMTP_PASSWORD'])
        smtp.send_message(message)


def register_recovery(app, helpers):
    h = SimpleNamespace(**helpers)

    @app.post('/api/auth/recovery')
    def request_recovery():
        h.limited('recovery', 5, 3600)
        value = h.data()
        email = h.text(value, 'email', 5, 254).lower()
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            abort(400, description='Confira seu e-mail.')
        if not mail_ready(app):
            abort(503, description='A recuperação por e-mail ainda não foi ativada. Fale com o suporte para recuperar o acesso.')
        base = app.config['PUBLIC_URL'].rstrip('/')
        parsed = urlsplit(base)
        if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/') or (not app.testing and parsed.scheme != 'https'):
            abort(503, description='A recuperação de acesso está temporariamente indisponível.')
        result = {'ok': True, 'message': 'Se houver uma conta com esse e-mail, enviaremos um link. Confira também a pasta de spam.'}
        user = h.one('SELECT id,auth_version,email FROM users WHERE email=?', (email,))
        current = datetime.now(timezone.utc)
        raw = secrets.token_urlsafe(32)
        # Same response for unknown accounts, cooldown and delivery failure.
        if not user:
            return jsonify(result)
        with h.transaction() as conn:
            recent = conn.execute('SELECT id FROM account_tokens WHERE user_id=? AND created_at>? LIMIT 1',
                (user['id'], (current-timedelta(minutes=2)).isoformat(timespec='seconds'))).fetchone()
            if recent:
                return jsonify(result)
            conn.execute('DELETE FROM account_tokens WHERE expires_at<?', ((current-timedelta(days=1)).isoformat(timespec='seconds'),))
            tid = conn.execute('INSERT INTO account_tokens(user_id,token_hash,auth_version,created_at,expires_at) VALUES(?,?,?,?,?)',
                (user['id'], hashlib.sha256(raw.encode()).hexdigest(), user['auth_version'],
                 current.isoformat(timespec='seconds'), (current+timedelta(minutes=30)).isoformat(timespec='seconds'))).lastrowid
        def deliver():
            with app.app_context():
                try:
                    # Fragment prevents tokens reaching HTTP request logs or referrer URLs.
                    url = base + '/entrar?recuperar=1#' + raw
                    app.extensions.get('recovery_mailer', send_recovery)(app.config, email, url)
                    h.db().execute("INSERT INTO platform_settings(key,value) VALUES('recovery.delivery_error','') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
                except Exception:
                    h.db().execute('UPDATE account_tokens SET used_at=? WHERE id=?', (h.now(), tid))
                    h.db().execute("INSERT INTO platform_settings(key,value) VALUES('recovery.delivery_error',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (h.now(),))
                    app.logger.error('Falha no envio de recuperação de acesso. Confira a configuração de e-mail.')
        # SMTP latency must not reveal whether an account exists. Sending can be
        # retried by requesting a new link after cooldown if this process stops.
        if app.testing:
            deliver()
        else:
            threading.Thread(target=deliver, daemon=True, name='recovery-mail').start()
        return jsonify(result)

    @app.post('/api/auth/recovery/complete')
    def complete_recovery():
        h.limited('recovery-complete', 12, 3600)
        value = h.data()
        raw = h.text(value, 'token', 40, 100)
        password = h.text(value, 'password', 10, 128)
        hashed = generate_password_hash(password)
        with h.transaction() as conn:
            token = conn.execute('SELECT * FROM account_tokens WHERE token_hash=?', (hashlib.sha256(raw.encode()).hexdigest(),)).fetchone()
            if not token or token['used_at'] or token['expires_at'] <= h.now():
                abort(400, description='Este link expirou ou já foi usado. Solicite outro link.')
            changed = conn.execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=? AND auth_version=?',
                (hashed, token['user_id'], token['auth_version']))
            if changed.rowcount != 1:
                abort(400, description='Este link não é mais válido. Solicite outro link.')
            conn.execute('UPDATE account_tokens SET used_at=? WHERE user_id=? AND used_at=?', (h.now(), token['user_id'], ''))
            conn.execute('INSERT INTO audit_log(actor_id,store_id,action,detail,created_at) VALUES(?,NULL,?,?,?)',
                (token['user_id'], 'auth.password_recovered', 'Sessões anteriores revogadas.', h.now()))
        session.clear()
        return jsonify(ok=True)
