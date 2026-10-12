"""Suporte: conversa entre cada loja e o dono da plataforma (Central do Dono)."""
from functools import wraps
from types import SimpleNamespace

from flask import abort, g, jsonify, session

from notify import notify_store

TOPICS = {"pedidos": "Pedidos", "pagamento": "Pagamento e mensalidade", "impressora": "Impressora", "motoja": "MotoJá",
          "cardapio": "Cardápio", "outro": "Outro assunto"}


def register_support(app, helpers):
    h = SimpleNamespace(**helpers)

    def platform(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = h.one("SELECT id,name,auth_version,platform_admin FROM users WHERE id=?", (session.get("uid", -1),))
            if not user or user["auth_version"] != session.get("version"):
                abort(401, description="Entre na sua conta.")
            if not user["platform_admin"]:
                abort(403, description="Esta área é exclusiva do dono da plataforma.")
            g.user = user
            return fn(*args, **kwargs)
        return wrapped

    def thread(sid):
        return h.rows("""SELECT m.id,m.from_platform,m.kind,m.topic,m.body,m.created_at,m.read_at,COALESCE(u.name,'') AS author
            FROM support_messages m LEFT JOIN users u ON u.id=m.author_id WHERE m.store_id=? ORDER BY m.id LIMIT 500""", (sid,))

    def message(value, platform_side):
        kind = "chat" if platform_side else value.get("kind", "chat")
        if kind not in ("chat", "problem"):
            abort(400, description="Tipo de mensagem inválido.")
        topic = value.get("topic", "") if kind == "problem" else ""
        if topic and topic not in TOPICS:
            abort(400, description="Assunto inválido.")
        return kind, TOPICS.get(topic, ""), h.text(value, "body", 2, 2000)

    @app.get("/api/admin/support")
    @h.owner
    def support_thread():
        messages = thread(g.store["id"])
        h.db().execute("UPDATE support_messages SET read_at=? WHERE store_id=? AND from_platform=1 AND read_at IS NULL", (h.now(), g.store["id"]))
        return jsonify(messages=messages, topics=TOPICS)

    @app.get("/api/admin/support/unread")
    @h.owner
    def support_unread():
        row = h.one("SELECT COUNT(*) FROM support_messages WHERE store_id=? AND from_platform=1 AND read_at IS NULL", (g.store["id"],))
        return jsonify(unread=row[0])

    @app.post("/api/admin/support")
    @h.owner
    def support_send():
        h.limited("support", 30)
        kind, topic, body = message(h.data(), False)
        h.db().execute("INSERT INTO support_messages(store_id,author_id,from_platform,kind,topic,body,created_at) VALUES(?,?,0,?,?,?,?)",
                       (g.store["id"], g.user["id"], kind, topic, body, h.now()))
        return jsonify(messages=thread(g.store["id"])), 201

    @app.get("/api/platform/support")
    @platform
    def platform_support_list():
        threads = h.rows("""SELECT s.id,s.name,s.slug,s.phone,MAX(m.created_at) AS last_at,
              CAST(SUM(CASE WHEN m.from_platform=0 AND m.read_at IS NULL THEN 1 ELSE 0 END) AS INTEGER) AS unread,
              (SELECT body FROM support_messages x WHERE x.store_id=s.id ORDER BY x.id DESC LIMIT 1) AS last_body,
              (SELECT from_platform FROM support_messages x WHERE x.store_id=s.id ORDER BY x.id DESC LIMIT 1) AS last_from_platform
            FROM support_messages m JOIN stores s ON s.id=m.store_id GROUP BY s.id,s.name,s.slug,s.phone ORDER BY last_at DESC LIMIT 200""")
        return jsonify(threads=threads, unread=sum(int(t["unread"] or 0) for t in threads))

    @app.get("/api/platform/support/<int:sid>")
    @platform
    def platform_support_thread(sid):
        store = h.one("SELECT id,name,slug,phone FROM stores WHERE id=?", (sid,))
        if not store:
            abort(404)
        messages = thread(sid)
        h.db().execute("UPDATE support_messages SET read_at=? WHERE store_id=? AND from_platform=0 AND read_at IS NULL", (h.now(), sid))
        return jsonify(store=dict(store), messages=messages)

    @app.post("/api/platform/support/<int:sid>")
    @platform
    def platform_support_reply(sid):
        if not h.one("SELECT id FROM stores WHERE id=?", (sid,)):
            abort(404)
        _, _, body = message(h.data(), True)
        h.db().execute("INSERT INTO support_messages(store_id,author_id,from_platform,kind,topic,body,created_at) VALUES(?,?,1,'chat','',?,?)",
                       (sid, g.user["id"], body, h.now()))
        notify_store(app, sid, {"title": "O suporte respondeu", "body": body[:120], "tag": "suporte", "url": "/painel?aba=suporte"})
        return jsonify(messages=thread(sid)), 201
