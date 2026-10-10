"""Pix automático pelo Mercado Pago, com a conta do próprio lojista.

O token de acesso fica criptografado no banco (chave derivada de SECRET_KEY) e
nunca volta para o navegador. A confirmação do pagamento é sempre feita
consultando o Mercado Pago, nunca confiando no que chega no webhook.
"""
import base64
import hashlib
import json
import urllib.error
import urllib.request

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("mercadopago:" + secret).encode()).digest()))


def seal(secret, token):
    return _fernet(secret).encrypt(token.encode()).decode() if token else ""


def unseal(secret, sealed):
    if not sealed:
        return ""
    try:
        return _fernet(secret).decrypt(sealed.encode()).decode()
    except InvalidToken:
        return ""


class PaymentError(Exception):
    pass


class MercadoPago:
    base = "https://api.mercadopago.com"

    def _call(self, method, path, token, body=None, idempotency=None):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if idempotency:
            headers["X-Idempotency-Key"] = idempotency
        request = urllib.request.Request(self.base + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read() or b"{}").get("message", "")
            except ValueError:
                detail = ""
            raise PaymentError(f"Mercado Pago recusou ({error.code}). {detail}".strip()) from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise PaymentError("Não foi possível falar com o Mercado Pago agora.") from error

    def me(self, token):
        return self._call("GET", "/users/me", token)

    def create_pix(self, token, payload, idempotency):
        return self._call("POST", "/v1/payments", token, payload, idempotency)

    def get_payment(self, token, payment_id):
        return self._call("GET", "/v1/payments/" + str(int(payment_id)), token)

    def cancel(self, token, payment_id):
        return self._call("PUT", "/v1/payments/" + str(int(payment_id)), token, {"status": "cancelled"})

    # Assinatura mensal da plataforma (conta do dono do SeuComércioAqui).
    def create_preapproval(self, token, payload):
        return self._call("POST", "/preapproval", token, payload)

    def get_preapproval(self, token, preapproval_id):
        return self._call("GET", "/preapproval/" + urllib.request.quote(str(preapproval_id), safe=""), token)

    def update_preapproval(self, token, preapproval_id, body):
        return self._call("PUT", "/preapproval/" + urllib.request.quote(str(preapproval_id), safe=""), token, body)

    def authorized_payments(self, token, preapproval_id):
        return self._call("GET", "/authorized_payments/search?preapproval_id=" + urllib.request.quote(str(preapproval_id), safe=""), token)

    def authorized_payment(self, token, payment_id):
        return self._call("GET", "/authorized_payments/" + str(int(payment_id)), token)
