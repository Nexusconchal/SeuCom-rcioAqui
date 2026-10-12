"""Suporte: loja manda mensagem, o dono da plataforma responde e a loja é avisada."""
import support
from tests.test_api import app, register, send  # noqa: F401  (fixture)


def platform_client(app):
    admin = app.test_client()
    assert register(admin, "plataforma", "admin@example.com").status_code == 201
    assert app.test_cli_runner().invoke(args=["grant-platform-admin", "--email", "admin@example.com"]).exit_code == 0
    return admin


def test_store_and_platform_talk(app, monkeypatch):
    pushes = []
    monkeypatch.setattr(support, "notify_store", lambda app_, sid, message, user_id=None: pushes.append((sid, message)))
    shop = app.test_client()
    assert register(shop).status_code == 201
    assert shop.get("/api/admin/support").json["messages"] == []
    assert send(shop, "POST", "/api/admin/support", {"kind": "problem", "topic": "invalido", "body": "Oi"}).status_code == 400
    sent = send(shop, "POST", "/api/admin/support", {"kind": "problem", "topic": "impressora", "body": "A notinha sai em branco"})
    assert sent.status_code == 201 and sent.json["messages"][0]["topic"] == "Impressora"
    # Loja comum não entra na caixa de entrada da plataforma.
    assert shop.get("/api/platform/support").status_code == 403
    admin = platform_client(app)
    inbox = admin.get("/api/platform/support").json
    assert inbox["unread"] == 1 and inbox["threads"][0]["name"] == "Minha Loja"
    sid = inbox["threads"][0]["id"]
    assert admin.get(f"/api/platform/support/{sid}").json["messages"][0]["body"] == "A notinha sai em branco"
    assert admin.get("/api/platform/support").json["unread"] == 0
    reply = send(admin, "POST", f"/api/platform/support/{sid}", {"body": "Já corrigimos, atualize o painel."})
    assert reply.status_code == 201 and pushes and pushes[-1][0] == sid
    assert shop.get("/api/admin/support/unread").json["unread"] == 1
    thread = shop.get("/api/admin/support").json["messages"]
    assert [m["from_platform"] for m in thread] == [0, 1]
    assert shop.get("/api/admin/support/unread").json["unread"] == 0
    # Outra loja não vê a conversa.
    other = app.test_client()
    assert register(other, "outra-loja", "other@example.com").status_code == 201
    assert other.get("/api/admin/support").json["messages"] == []
