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

    def connect(self, instance):
        self.calls.append(("connect", instance)); return self._connect

    def state(self, instance):
        return 200, {"instance": {"state": "close"}}


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
