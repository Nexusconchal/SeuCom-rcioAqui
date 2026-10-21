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
import urllib.parse

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


def safe_checkout_url(value):
    """Only the provider's HTTPS checkout can receive the browser redirect."""
    if not isinstance(value, str) or len(value)>3000:return ''
    try:
        url=urllib.parse.urlsplit(value)
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443):return ''
        if url.hostname not in ('www.mercadopago.com.br','mercadopago.com.br','sandbox.mercadopago.com.br'):return ''
        if not url.path.startswith(('/checkout/','/subscriptions/checkout','/preapproval/')):return ''
        return value
    except ValueError:return ''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class MercadoPago:
    base = "https://api.mercadopago.com"

    def _call(self, method, path, token, body=None, idempotency=None):
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if idempotency:
            headers["X-Idempotency-Key"] = idempotency
        request = urllib.request.Request(self.base + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
                raw=response.read(1024*1024+1)
                if len(raw)>1024*1024:raise PaymentError('Resposta do pagamento acima do limite.')
                value=json.loads(raw or b'{}')
                if not isinstance(value,dict):raise PaymentError('Resposta inválida do serviço de pagamento.')
                return value
        except urllib.error.HTTPError as error:
            raise PaymentError(f"Mercado Pago recusou ({error.code}). Confira os dados ou tente novamente.") from error
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
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
    def create_preapproval(self, token, payload, idempotency=None):
        return self._call("POST", "/preapproval", token, payload, idempotency)

    def create_preference(self,token,payload,idempotency):
        return self._call('POST','/checkout/preferences',token,payload,idempotency)

    def search_payments(self,token,external_reference):
        query=urllib.parse.urlencode({'external_reference':external_reference,'sort':'date_created','criteria':'desc','limit':50})
        return self._call('GET','/v1/payments/search?'+query,token)

    def search_preferences(self,token,external_reference):
        query=urllib.parse.urlencode({'external_reference':external_reference,'limit':50})
        return self._call('GET','/checkout/preferences/search?'+query,token)

    def get_preference(self,token,preference_id):
        return self._call('GET','/checkout/preferences/'+urllib.parse.quote(str(preference_id),safe=''),token)

    def update_preference(self,token,preference_id,body):
        return self._call('PUT','/checkout/preferences/'+urllib.parse.quote(str(preference_id),safe=''),token,body)

    def refund(self,token,payment_id,idempotency):
        return self._call('POST','/v1/payments/'+str(int(payment_id))+'/refunds',token,{},idempotency)

    def get_preapproval(self, token, preapproval_id):
        return self._call("GET", "/preapproval/" + urllib.request.quote(str(preapproval_id), safe=""), token)

    def update_preapproval(self, token, preapproval_id, body):
        return self._call("PUT", "/preapproval/" + urllib.request.quote(str(preapproval_id), safe=""), token, body)

    def authorized_payments(self, token, preapproval_id):
        return self._call("GET", "/authorized_payments/search?preapproval_id=" + urllib.request.quote(str(preapproval_id), safe=""), token)

    def authorized_payment(self, token, payment_id):
        return self._call("GET", "/authorized_payments/" + str(int(payment_id)), token)
