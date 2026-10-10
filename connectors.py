"""Conectores externos: MotoJá (chamar motoboy) e WhatsApp pela Evolution API.

Tudo que sai daqui roda em segundo plano para não atrasar o painel nem o cliente.
Chaves ficam criptografadas no banco com uma chave derivada de SECRET_KEY.
"""
import base64
import hashlib
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken

MOTOJA_URL = re.compile(r"https://([a-z0-9.-]+)/api/integrations/orders/(\d{10,13})/seucomercio")


def _fernet(secret, purpose):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"{purpose}:{secret}".encode()).digest()))


def seal(secret, value, purpose):
    return _fernet(secret, purpose).encrypt(value.encode()).decode() if value else ""


def unseal(secret, value, purpose):
    if not value:
        return ""
    try:
        return _fernet(secret, purpose).decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def http(method, url, headers=None, body=None, timeout=8):
    """(status, json). Erros de rede viram status 0."""
    request = urllib.request.Request(url, method=method, headers={"content-type": "application/json", **(headers or {})},
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except ValueError:
            return error.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return 0, {}


def valid_motoja_url(url, hosts):
    match = MOTOJA_URL.fullmatch((url or "").strip())
    if not match or match.group(1) not in hosts:
        return ""
    return match.group(0)


class MotoJa:
    def send(self, url, key, payload):
        return http("POST", url, {"x-nexus-capture-key": key}, payload, timeout=25)

    def status(self, url, key, external_id):
        return http("GET", url + "/status?externalId=" + urllib.parse.quote(external_id, safe=""), {"x-nexus-capture-key": key})


class Evolution:
    def __init__(self, base, key):
        self.base, self.key = (base or "").rstrip("/"), key or ""

    @property
    def ready(self):
        return bool(self.base and self.key)

    def _call(self, method, path, body=None, timeout=15):
        return http(method, self.base + path, {"apikey": self.key}, body, timeout)

    def create(self, instance):
        return self._call("POST", "/instance/create", {"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"})

    def connect(self, instance):
        return self._call("GET", "/instance/connect/" + urllib.parse.quote(instance, safe=""))

    def state(self, instance):
        return self._call("GET", "/instance/connectionState/" + urllib.parse.quote(instance, safe=""))

    def logout(self, instance):
        self._call("DELETE", "/instance/logout/" + urllib.parse.quote(instance, safe=""))
        return self._call("DELETE", "/instance/delete/" + urllib.parse.quote(instance, safe=""))

    def send_text(self, instance, phone, text):
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) in (10, 11):
            digits = "55" + digits
        return self._call("POST", "/message/sendText/" + urllib.parse.quote(instance, safe=""), {"number": digits, "text": text})


def background(app, task, *args):
    """Executa em segundo plano (em testes, na hora, para conferir o resultado)."""
    if app.config.get("TESTING"):
        return task(*args)
    threading.Thread(target=task, args=args, daemon=True).start()
    return None


def qr_image(data):
    raw = (data.get("qrcode") or {}).get("base64") or data.get("base64") or ""
    if raw and not raw.startswith("data:"):
        raw = "data:image/png;base64," + raw
    return raw if raw.startswith("data:image/") else ""
