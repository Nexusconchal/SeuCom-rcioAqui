"""MotoJá (chamar motoboy) e mensagens de WhatsApp para o cliente, ligados ao andamento do pedido."""
import json
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flask import abort, g, jsonify, request

from connectors import Evolution, MotoJa, background, qr_image, seal, unseal, valid_motoja_url
from database import connect

FLOW = ["new", "preparing", "ready", "delivering", "completed"]
ACTIVE_MOTOJA = ("chamado", "aceito", "retirado", "na_fila")
MOTOJA_LABEL = {"chamado": "Procurando motoboy", "aceito": "Motoboy a caminho da loja", "retirado": "Motoboy levando o pedido",
                "entregue": "Entregue pelo motoboy", "na_fila": "Aguardando no MotoJá", "cancelado": "Corrida cancelada no MotoJá",
                "erro": "Não enviado ao MotoJá"}


def money(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def payment_note(order):
    if order["paid"]:
        return "PAGO - não cobrar do cliente."
    total = money(order["total"])
    if order["payment"] == "cash":
        change = f" (troco para {money(order['change_for'])})" if order["change_for"] else ""
        return f"Cobrar {total} em dinheiro{change}."
    if order["payment"] == "card":
        return f"Cobrar {total} no cartão (levar maquininha)."
    if order["payment"] == "pix_online":
        return "Pix online ainda não confirmado - confirmar com a loja."
    return f"Cliente paga {total} por Pix para a loja."


def customer_message(order, store, status, link):
    first = (order["customer"] or "").split(" ")[0]
    number, name = order["number"], store["name"]
    if status == "new":
        when = ""
        if order["scheduled_for"]:
            when = " agendado para " + datetime.fromisoformat(order["scheduled_for"]).astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m às %H:%M")
        return f"Olá, {first}! Recebemos seu pedido #{number}{when} na {name}. Total: {money(order['total'])}.\nAcompanhe aqui: {link}"
    if status == "preparing":
        return f"Seu pedido #{number} foi aceito pela {name} e já está sendo preparado."
    if status == "ready" and order["mode"] == "pickup":
        return f"Seu pedido #{number} está pronto para retirada na {name}."
    if status == "delivering":
        info = json.loads(order["motoja_info"] or "{}")
        driver = f" O motoboy {info['motoboy']} está a caminho." if info.get("motoboy") else ""
        return f"Seu pedido #{number} saiu para entrega!{driver}\nAcompanhe: {link}"
    if status == "completed":
        return f"Pedido #{number} concluído. Obrigado por pedir na {name}! Conte como foi: {link}"
    if status == "cancelled":
        return f"Seu pedido #{number} na {name} foi cancelado. Se tiver dúvida, responda esta mensagem."
    return ""


def register_order_flow(app, helpers):
    h = SimpleNamespace(**helpers)
    config = app.config
    app.extensions.setdefault("motoja", MotoJa())

    def evolution():
        return app.extensions.get("evolution") or Evolution(config.get("EVOLUTION_API_URL", ""), config.get("EVOLUTION_API_KEY", ""))

    def with_conn(task):
        conn = connect(config)
        try:
            return task(conn)
        finally:
            conn.close()

    def external_id(order):
        return f"SCA{order['store_id']}-{order['number']}"

    # ---------- WhatsApp do cliente
    def notify_customer(order_id, status):
        def run(conn):
            order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            store = conn.execute("SELECT * FROM stores WHERE id=?", (order["store_id"],)).fetchone() if order else None
            if not order or not store or not store["wa_enabled"] or not store["wa_instance"] or not evolution().ready:
                return False
            sent = set(filter(None, (order["wa_sent"] or "").split(",")))
            if status in sent or order["phone"] == "00000000000":
                return False
            text = customer_message(order, store, status, f"{h.public_base_static()}/pedido/{order['tracking_token']}")
            if not text:
                return False
            code, _ = evolution().send_text(store["wa_instance"], order["phone"], text)
            if 200 <= code < 300:
                conn.execute("UPDATE orders SET wa_sent=? WHERE id=?", (",".join(sorted(sent | {status})), order_id))
                return True
            return False
        return background(app, with_conn, run)

    # ---------- MotoJá
    def motoja_payload(conn, order):
        items = conn.execute("SELECT name,quantity,extras FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
        lines = []
        for item in items:
            extras = ", ".join(x["name"] for x in json.loads(item["extras"] or "[]"))
            lines.append({"quantity": item["quantity"], "name": item["name"] + (f" ({extras})" if extras else "")})
        note = payment_note(order) + (f" Obs.: {order['notes']}" if order["notes"] else "")
        return {"source": "api", "order": {
            "externalId": external_id(order), "customer": order["customer"], "phone": order["phone"], "address": order["address"],
            "neighborhood": order["zone"], "items": lines, "orderTotal": round(order["total"] / 100, 2),
            "deliveryFee": round(order["delivery_fee"] / 100, 2), "note": note[:300]}}

    def save_motoja(conn, order_id, status, info, delivery_id=None):
        current = conn.execute("SELECT motoja_delivery_id FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.execute("UPDATE orders SET motoja_status=?,motoja_info=?,motoja_delivery_id=?,motoja_checked_at=? WHERE id=?",
                     (status, json.dumps(info, ensure_ascii=False), delivery_id or current[0] or "", h.now(), order_id))

    def advance(conn, order, target):
        """Avança o pedido pelo caminho normal, registrando cada etapa, sem voltar atrás."""
        if order["status"] in ("completed", "cancelled") or target not in FLOW:
            return False
        start, end = FLOW.index(order["status"]), FLOW.index(target)
        if end <= start:
            return False
        stamp = h.now()
        for step in FLOW[start + 1:end + 1]:
            conn.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)", (order["id"], step, stamp))
        conn.execute("UPDATE orders SET status=?,updated_at=? WHERE id=? AND status=?", (target, stamp, order["id"], order["status"]))
        return True

    def sync_motoja(conn, order, store):
        key = unseal(config["SECRET_KEY"], store["motoja_key"], "motoja")
        code, data = app.extensions["motoja"].status(store["motoja_url"], key, external_id(order))
        if code == 404:
            save_motoja(conn, order["id"], "erro", {"message": "O MotoJá não recebeu este pedido. Use Chamar MotoJá."})
            return
        if code != 200:
            conn.execute("UPDATE orders SET motoja_checked_at=? WHERE id=?", (h.now(), order["id"]))
            return
        info = {"motoboy": data.get("motoboy", ""), "trackingUrl": data.get("trackingUrl", ""), "valor": data.get("valor", 0),
                "message": data.get("reviewReason", "")}
        delivery = data.get("deliveryStatus", "")
        status = {"pendente": "chamado", "aceita": "aceito", "retirada": "retirado", "finalizada": "entregue",
                  "aguardando_aprovacao": "entregue", "cancelada": "cancelado", "expirada": "cancelado"}.get(delivery)
        if not status:
            status = "na_fila" if data.get("capturedStatus") == "revisar" else ("chamado" if data.get("deliveryId") else "na_fila")
        save_motoja(conn, order["id"], status, info, data.get("deliveryId"))
        target = {"retirado": "delivering", "entregue": "completed"}.get(status)
        if target and advance(conn, order, target):
            notify_customer(order["id"], target)

    def send_motoja(order_id, manual=False):
        def run(conn):
            order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            store = conn.execute("SELECT * FROM stores WHERE id=?", (order["store_id"],)).fetchone() if order else None
            if not order or not store or not store["motoja_url"] or order["mode"] != "delivery":
                return "ignorado"
            if order["status"] in ("completed", "cancelled") or (order["motoja_status"] in ACTIVE_MOTOJA + ("entregue",) and not manual):
                return order["motoja_status"]
            key = unseal(config["SECRET_KEY"], store["motoja_key"], "motoja")
            code, data = app.extensions["motoja"].send(store["motoja_url"], key, motoja_payload(conn, order))
            if code == 201:
                save_motoja(conn, order_id, "chamado", {"message": "Motoboy chamado no MotoJá."}, (data.get("dispatch") or {}).get("deliveryId"))
            elif code in (200, 202):
                sync_motoja(conn, conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone(), store)
                current = conn.execute("SELECT motoja_status,motoja_info FROM orders WHERE id=?", (order_id,)).fetchone()
                if current["motoja_status"] == "erro":
                    save_motoja(conn, order_id, "na_fila", {"message": "Pedido no MotoJá aguardando conferência da loja."})
            else:
                message = {401: "A chave do MotoJá não foi aceita. Gere outra no MotoJá e conecte de novo.",
                           409: "No MotoJá, ligue “Receber pedidos do SeuComércioAqui”.",
                           0: "Não consegui falar com o MotoJá agora. Tente de novo em instantes."}.get(code, data.get("message") or "O MotoJá recusou o pedido.")
                save_motoja(conn, order_id, "erro", {"message": message})
            return conn.execute("SELECT motoja_status FROM orders WHERE id=?", (order_id,)).fetchone()[0]
        return with_conn(run) if manual else background(app, with_conn, run)

    def refresh_stale(store_id):
        def run(conn):
            limit = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(timespec="seconds")
            store = conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
            if not store or not store["motoja_url"]:
                return
            stale = conn.execute("""SELECT * FROM orders WHERE store_id=? AND motoja_status IN ('chamado','aceito','retirado','na_fila')
                AND status NOT IN ('completed','cancelled') AND motoja_checked_at<? ORDER BY motoja_checked_at LIMIT 5""", (store_id, limit)).fetchall()
            for order in stale:
                try:
                    sync_motoja(conn, order, store)
                except Exception:  # um pedido com problema não impede os outros
                    app.logger.exception("Falha ao consultar o MotoJá")
        return background(app, with_conn, run)

    def on_new_order(store_id, order_id):
        notify_customer(order_id, "new")

    def on_status(store_id, order_id, status):
        notify_customer(order_id, status)
        store = h.one("SELECT motoja_url,motoja_auto,motoja_trigger FROM stores WHERE id=?", (store_id,))
        if store and store["motoja_url"] and store["motoja_auto"] and status == store["motoja_trigger"]:
            send_motoja(order_id)

    app.extensions.update(on_new_order=on_new_order, on_status=on_status, motoja_refresh=refresh_stale)

    # ---------- Configuração no painel
    def connectors_state(store):
        return {"motoja": {"connected": bool(store["motoja_url"]), "auto": bool(store["motoja_auto"]), "trigger": store["motoja_trigger"],
                           "company": ("•••" + store["motoja_url"].split("/")[-2][-4:]) if store["motoja_url"] else ""},
                "whatsapp": {"available": evolution().ready, "linked": bool(store["wa_instance"]), "enabled": bool(store["wa_enabled"])}}

    @app.get("/api/admin/connectors")
    @h.owner
    def connectors_get():
        return jsonify(connectors_state(g.store))

    @app.put("/api/admin/motoja")
    @h.owner
    def motoja_connect():
        value = h.data()
        url = valid_motoja_url(h.text(value, "url", 20, 300), config["MOTOJA_HOSTS"])
        key = h.text(value, "key", 20, 200)
        if not url:
            abort(400, description="Cole o endereço que aparece no MotoJá (Integrações › SeuComércioAqui).")
        code, data = app.extensions["motoja"].status(url, key, "teste-conexao")
        if code == 401:
            abort(400, description="O MotoJá não aceitou a chave. Gere uma nova chave no MotoJá e cole aqui.")
        if code != 404:
            abort(502, description="Não consegui confirmar com o MotoJá. Confira o endereço e tente de novo.")
        warnings = []
        if not data.get("active"):
            warnings.append("No MotoJá, ligue “Receber pedidos do SeuComércioAqui”.")
        if not data.get("autoDispatch"):
            warnings.append("No MotoJá, ligue “Chamar motoboy automaticamente” para o motoboy ser chamado sozinho.")
        if float(data.get("saldoDisponivel") or 0) <= 0:
            warnings.append("Seu saldo no MotoJá está zerado. Deposite para as corridas serem aceitas.")
        h.db().execute("UPDATE stores SET motoja_url=?,motoja_key=?,motoja_auto=1 WHERE id=?",
                       (url, seal(config["SECRET_KEY"], key, "motoja"), g.store["id"]))
        return jsonify({**connectors_state(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))), "warnings": warnings})

    @app.patch("/api/admin/motoja")
    @h.owner
    def motoja_toggle():
        value = h.data()
        auto = h.boolean(value, "auto", bool(g.store["motoja_auto"]))
        trigger = value.get("trigger", g.store["motoja_trigger"])
        if trigger not in ("preparing", "ready"):
            abort(400, description="Escolha quando chamar o motoboy.")
        h.db().execute("UPDATE stores SET motoja_auto=?,motoja_trigger=? WHERE id=?", (auto, trigger, g.store["id"]))
        return jsonify(connectors_state(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))))

    @app.delete("/api/admin/motoja")
    @h.owner
    def motoja_disconnect():
        h.db().execute("UPDATE stores SET motoja_url='',motoja_key='',motoja_auto=0 WHERE id=?", (g.store["id"],))
        return jsonify(connectors_state(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))))

    @app.post("/api/admin/orders/<int:oid>/motoja")
    @h.owner
    def motoja_send(oid):
        order = h.owned("orders", oid)
        if not g.store["motoja_url"]:
            abort(409, description="Conecte o MotoJá em Integrações primeiro.")
        if order["mode"] != "delivery" or order["status"] in ("completed", "cancelled"):
            abort(409, description="Só pedidos de entrega em andamento podem chamar motoboy.")
        h.limited("motoja-send", 30)
        status = send_motoja(oid, manual=True)
        info = json.loads(h.one("SELECT motoja_info FROM orders WHERE id=?", (oid,))["motoja_info"] or "{}")
        return jsonify(status=status, label=MOTOJA_LABEL.get(status, ""), message=info.get("message", ""))

    @app.post("/api/admin/whatsapp/connect")
    @h.owner
    def whatsapp_connect():
        if not evolution().ready:
            abort(503, description="O WhatsApp automático ainda não foi configurado pela plataforma.")
        h.limited("wa-connect", 10)
        instance = g.store["wa_instance"] or f"sca-{g.store['id']}-{secrets.token_hex(3)}"
        code, data = evolution().create(instance)
        if code not in (200, 201) and code != 409 and "exist" not in json.dumps(data).lower():
            abort(502, description="Não consegui iniciar a conexão do WhatsApp agora.")
        image = qr_image(data)
        if not image:
            _, data = evolution().connect(instance)
            image = qr_image(data)
        h.db().execute("UPDATE stores SET wa_instance=? WHERE id=?", (instance, g.store["id"]))
        return jsonify(qr=image, pairing_code=data.get("pairingCode") or (data.get("qrcode") or {}).get("pairingCode") or "")

    @app.get("/api/admin/whatsapp/status")
    @h.owner
    def whatsapp_status():
        if not g.store["wa_instance"] or not evolution().ready:
            return jsonify(connected=False)
        code, data = evolution().state(g.store["wa_instance"])
        state = (data.get("instance") or {}).get("state") or data.get("state") or ""
        return jsonify(connected=state in ("open", "connected"))

    @app.patch("/api/admin/whatsapp")
    @h.owner
    def whatsapp_toggle():
        enabled = h.boolean(h.data(), "enabled")
        if enabled and not g.store["wa_instance"]:
            abort(409, description="Conecte o WhatsApp da loja primeiro.")
        h.db().execute("UPDATE stores SET wa_enabled=? WHERE id=?", (enabled, g.store["id"]))
        return jsonify(connectors_state(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))))

    @app.delete("/api/admin/whatsapp")
    @h.owner
    def whatsapp_disconnect():
        if g.store["wa_instance"] and evolution().ready:
            evolution().logout(g.store["wa_instance"])
        h.db().execute("UPDATE stores SET wa_instance='',wa_enabled=0 WHERE id=?", (g.store["id"],))
        return jsonify(connectors_state(h.one("SELECT * FROM stores WHERE id=?", (g.store["id"],))))

    @app.post("/api/admin/whatsapp/test")
    @h.owner
    def whatsapp_test():
        h.limited("wa-test", 10)
        phone = h.text(h.data(), "phone", 10, 20)
        if not g.store["wa_instance"] or not evolution().ready:
            abort(409, description="Conecte o WhatsApp da loja primeiro.")
        code, _ = evolution().send_text(g.store["wa_instance"], phone, f"Teste do SeuComércioAqui: as mensagens automáticas da {g.store['name']} estão funcionando.")
        if not 200 <= code < 300:
            abort(502, description="A mensagem não saiu. Confira se o WhatsApp da loja está conectado.")
        return jsonify(ok=True)
