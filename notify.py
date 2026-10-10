"""Avisos push (Web Push/VAPID) para quem opera a loja.

As chaves VAPID vêm de VAPID_PRIVATE_KEY (PEM) ou são geradas uma vez e guardadas
criptografadas no banco com uma chave derivada de SECRET_KEY.
"""
import base64
import hashlib
import json
import threading

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from database import connect


def _fernet(secret):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("vapid:" + secret).encode()).digest()))


def _public_b64(private_key):
    raw = private_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def vapid_keys(config, conn):
    """(PEM da chave privada, chave pública em base64url para o navegador)."""
    pem = config.get("VAPID_PRIVATE_KEY", "")
    if not pem:
        row = conn.execute("SELECT value FROM platform_settings WHERE key='vapid_private'").fetchone()
        if row:
            try:
                pem = _fernet(config["SECRET_KEY"]).decrypt(row[0].encode()).decode()
            except InvalidToken:
                pem = ""
        if not pem:
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
            token = _fernet(config["SECRET_KEY"]).encrypt(pem.encode()).decode()
            conn.execute("DELETE FROM platform_settings WHERE key='vapid_private'")
            conn.execute("INSERT INTO platform_settings(key,value) VALUES(?,?)", ("vapid_private", token))
            conn.execute("DELETE FROM push_subscriptions")  # assinaturas antigas não valem com chave nova
    private = serialization.load_pem_private_key(pem.encode(), password=None)
    return pem, _public_b64(private)


def deliver(config, subscriptions, message):
    """Envia e devolve os endpoints que não existem mais (para apagar)."""
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush
    conn = connect(config)
    try:
        pem, _ = vapid_keys(config, conn)
    finally:
        conn.close()
    signer = Vapid.from_pem(pem.encode())
    gone = []
    for sub in subscriptions:
        try:
            webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                     data=json.dumps(message), vapid_private_key=signer,
                     vapid_claims={"sub": "mailto:" + config.get("PUSH_CONTACT", "suporte@seucomercioaqui.com.br")},
                     ttl=600, timeout=8)
        except WebPushException as error:
            if error.response is not None and error.response.status_code in (404, 410):
                gone.append(sub["endpoint"])
        except Exception:  # um aparelho com problema não pode impedir os outros
            continue
    return gone


def notify_store(app, store_id, message, user_id=None):
    """Dispara em segundo plano para não atrasar o pedido do cliente."""
    config = dict(app.config)

    def run():
        conn = connect(config)
        try:
            sql, params = "SELECT endpoint,p256dh,auth FROM push_subscriptions WHERE store_id=?", [store_id]
            if user_id:
                sql += " AND user_id=?"
                params.append(user_id)
            subs = [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
        if not subs:
            return 0
        gone = app.extensions.get("push_deliver", deliver)(config, subs, message)
        if gone:
            conn = connect(config)
            try:
                for endpoint in gone:
                    conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
            finally:
                conn.close()
        return len(subs) - len(gone)

    if config.get("TESTING"):
        return run()
    threading.Thread(target=run, daemon=True).start()
    return None
