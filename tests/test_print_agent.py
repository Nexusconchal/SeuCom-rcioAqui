"""Agente de impressão: pega só pedidos aceitos e novos, com as duas notinhas em texto, uma vez."""
import uuid

from database import connect
from tests.test_api import app, shop, send, payload  # noqa: F401


def agent_key(client, scopes=("print:jobs",)):
    r = send(client, "POST", "/api/admin/integrations/keys", {"name": "Agente de impressão", "scopes": list(scopes)})
    assert r.status_code == 201
    return {"Authorization": "Bearer " + r.json["token"]}


def order(client, pid):
    r = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, payment="cash"), uuid.uuid4().hex)
    assert r.status_code == 201
    return r.json


def accept_all(app):  # noqa: F811
    conn = connect(app.config)
    conn.execute("UPDATE stores SET auto_accept=1")
    conn.close()


def test_agent_prints_new_accepted_orders_once(app, shop):  # noqa: F811
    client, pid = shop
    accept_all(app)
    order(client, pid)  # já existia antes de instalar: não sai
    key = agent_key(client)
    agent = app.test_client()
    first = agent.get("/api/v1/print/jobs?cols=42", headers=key)
    assert first.status_code == 200 and first.json["jobs"] == []
    created = order(client, pid)
    jobs = agent.get("/api/v1/print/jobs?cols=42", headers=key).json["jobs"]
    assert [j["number"] for j in jobs] == [created["number"]]
    counter = [line["t"] for line in jobs[0]["counter"]]
    kitchen = [line["t"] for line in jobs[0]["kitchen"]]
    assert any("DELIVERY - ENTREGA" in t for t in counter) and any("Cobrar do cliente" in t for t in counter)
    assert any("Bacon" in t for t in counter) and all(len(t) <= 42 for t in counter)
    assert any("(COZINHA)" in t for t in kitchen) and any("BURGER" in t for t in kitchen)
    assert not any("Valor total" in t for t in kitchen)
    assert agent.post(f"/api/v1/print/jobs/{jobs[0]['id']}/done", headers=key).status_code == 200
    assert agent.get("/api/v1/print/jobs?cols=32", headers=key).json["jobs"] == []
    assert client.get("/api/admin/print-agent").json["active"] is True


def test_agent_skips_orders_waiting_acceptance_and_needs_scope(app, shop):  # noqa: F811
    client, pid = shop
    key = agent_key(client)
    agent = app.test_client()
    agent.get("/api/v1/print/jobs", headers=key)
    order(client, pid)  # sem aceite automático: fica "novo" e não imprime
    assert agent.get("/api/v1/print/jobs", headers=key).json["jobs"] == []
    other = agent_key(client, ("orders:read",))
    assert agent.get("/api/v1/print/jobs", headers=other).status_code == 403
    assert agent.get("/api/v1/print/jobs?cols=5", headers=key).status_code == 400
