"""Gerar o QR Code do WhatsApp quando a loja já tem conexão criada ou o servidor falha."""
from database import connect
from tests.test_api import app, shop, send  # noqa: F401

QR = {"base64": "data:image/png;base64,iVBORw0KGgo="}


class Evo:
    ready = True

    def __init__(self, create=(201, {}), connect=(200, QR)):
        self.calls, self._create, self._connect = [], create, connect

    def create(self, instance):
        self.calls.append(("create", instance)); return self._create

    def connect(self, instance, number=""):
        self.calls.append(("connect", instance) if not number else ("connect", instance, number)); return self._connect

    def state(self, instance):
        return 200, {"instance": {"state": "close"}}

    def logout(self, instance):
        self.calls.append(("logout", instance)); return 200, {}


def set_instance(app, value):  # noqa: F811
    conn = connect(app.config)
    conn.execute("UPDATE stores SET wa_instance=?", (value,))
    conn.close()


def test_existing_instance_asks_for_new_qr_without_creating(app, shop):  # noqa: F811
    client, _ = shop
    evo = Evo(create=(403, {"response": {"message": ['This name "sca-1-abc" is already in use.']}}))
    app.extensions["evolution"] = evo
    set_instance(app, "sca-1-abc")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 200 and r.json["qr"].startswith("data:image/png;base64,")
    assert evo.calls == [("connect", "sca-1-abc")]


def test_name_already_in_use_is_reused(app, shop):  # noqa: F811
    client, _ = shop
    evo = Evo(create=(403, {"response": {"message": ['This name is already in use.']}}))
    app.extensions["evolution"] = evo
    set_instance(app, "")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 200 and r.json["qr"]
    assert [c[0] for c in evo.calls] == ["create", "connect"]


def test_deleted_instance_is_created_again(app, shop):  # noqa: F811
    client, _ = shop
    evo = Evo(create=(201, {"qrcode": QR}), connect=(404, {}))
    app.extensions["evolution"] = evo
    set_instance(app, "sca-1-old")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 200 and r.json["qr"]
    assert evo.calls == [("connect", "sca-1-old"), ("create", "sca-1-old")]


def test_provider_offline_explains_what_to_do(app, shop):  # noqa: F811
    client, _ = shop
    app.extensions["evolution"] = Evo(create=(0, {}), connect=(0, {}))
    set_instance(app, "sca-1-abc")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 503 and "não respondeu" in r.json["error"]


def test_stuck_instance_is_recreated_and_webhook_registered_again(app, shop):  # noqa: F811
    client, _ = shop
    evo = Evo(create=(201, {"qrcode": QR}), connect=(500, {"error": "Internal Server Error"}))
    app.extensions["evolution"] = evo
    conn = connect(app.config)
    conn.execute("UPDATE stores SET wa_instance='sca-1-old',inbox_hook_hash='abc'")
    conn.close()
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 200 and r.json["qr"]
    assert evo.calls[0] == ("connect", "sca-1-old") and evo.calls[1] == ("logout", "sca-1-old")
    created = evo.calls[2]
    assert created[0] == "create" and created[1] != "sca-1-old"
    conn = connect(app.config)
    row = conn.execute("SELECT wa_instance,inbox_hook_hash FROM stores").fetchone()
    conn.close()
    assert row[0] == created[1] and row[1] == ""


def test_provider_error_message_shows_code(app, shop):  # noqa: F811
    client, _ = shop
    app.extensions["evolution"] = Evo(create=(500, {}), connect=(500, {}))
    set_instance(app, "")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 502 and "código 500" in r.json["error"]


def test_pairing_code_by_phone_number(app, shop):  # noqa: F811
    client, _ = shop
    evo = Evo(connect=(200, {"pairingCode": "WZYEH1YY", "code": "2@abc", "count": 1}))
    app.extensions["evolution"] = evo
    set_instance(app, "sca-1-abc")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {"phone": "(19) 99933-8422"})
    assert r.status_code == 200 and r.json["pairing_code"] == "WZYEH1YY"
    assert evo.calls == [("connect", "sca-1-abc", "5519999338422")]
    assert send(client, "POST", "/api/admin/whatsapp/connect", {"phone": "123"}).status_code == 400


def test_too_many_attempts_waits_without_touching_the_connection(app, shop):  # noqa: F811
    client, _ = shop
    evo = Evo(connect=(429, {}))
    app.extensions["evolution"] = evo
    set_instance(app, "sca-1-abc")
    r = send(client, "POST", "/api/admin/whatsapp/connect", {})
    assert r.status_code == 429 and "Aguarde 3 minutos" in r.json["error"]
    assert evo.calls == [("connect", "sca-1-abc")]  # sem apagar nem recriar
