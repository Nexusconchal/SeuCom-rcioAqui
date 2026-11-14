"""Agente de impressão do Windows: busca pedidos aceitos e devolve as notinhas em texto.

O agente roda no computador da loja (PowerShell, sem navegador) e imprime direto na impressora
escolhida pelo nome. Usa uma chave de integração com a permissão print:jobs. O controle do que já
saiu fica em platform_settings (sem tabela nova): o primeiro contato marca o que já existia, para
não imprimir pedidos antigos ao instalar.
"""
import json
import textwrap
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import abort, g, jsonify, request

from operations import receipt_state

PAY = {"cash": "Dinheiro", "card": "Cartão na entrega/retirada", "pix": "Pix para a loja", "pix_online": "Pix online",
       "card_online": "Cartão online", "credit": "Fiado autorizado"}
WINDOW_HOURS = 6
KEEP = 400


def money(cents):
    return ("R$ %.2f" % ((cents or 0) / 100)).replace(".", ",")


def phone_text(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return str(value or "")


def kind_of(order):
    if order.get("source") == "counter" and order["mode"] != "delivery":
        return "BALCÃO"
    return "DELIVERY - ENTREGA" if order["mode"] == "delivery" else "DELIVERY - RETIRADA BALCÃO"


def grouped(extras):
    """Escolhas "Grupo: opção" agrupadas pelo grupo, sem o "(até N)"; o resto fica solto."""
    groups, loose = [], []
    for extra in extras:
        name = str(extra.get("name") or "")
        if ": " in name:
            title, option = name.split(": ", 1)
            title = title.split(" (")[0].strip()
            group = next((g_ for g_ in groups if g_[0] == title), None)
            if not group:
                group = (title, [])
                groups.append(group)
            same = next((o for o in group[1] if o[0] == option), None)
            if same:
                same[1] += 1
            else:
                group[1].append([option, 1])
        else:
            same = next((o for o in loose if o[0] == name), None)
            if same:
                same[1] += 1
            else:
                loose.append([name, 1])
    return groups, loose


class Ticket:
    def __init__(self, cols):
        self.cols, self.lines = cols, []

    def add(self, text="", bold=False, center=False, big=False):
        width = max(12, int(self.cols / 1.4)) if big else self.cols
        for part in textwrap.wrap(str(text), width) or [""]:
            self.lines.append({"t": part, "b": bold or big, "c": center, "s": big})

    def pair(self, left, right, bold=False):
        room = self.cols - len(right) - 1
        parts = textwrap.wrap(str(left), max(8, room)) or [""]
        for part in parts[:-1]:
            self.lines.append({"t": part, "b": bold, "c": False, "s": False})
        self.lines.append({"t": parts[-1].ljust(room) + " " + right, "b": bold, "c": False, "s": False})

    def rule(self, char="-"):
        self.lines.append({"t": char * self.cols, "b": False, "c": False, "s": False})

    def choices(self, extras):
        groups, loose = grouped(extras)
        for title, options in groups:
            self.add(" " + title, bold=True)
            for option, n in options:
                self.add(f"   {n} x {option}")
        for name, n in loose:
            self.add(f"   + {str(n) + ' x ' if n > 1 else ''}{name}")


def counter_ticket(order, store, cols, printed):
    t = Ticket(cols)
    t.add(kind_of(order), center=True, big=True)
    t.add(store["name"].upper(), bold=True, center=True)
    t.add(f"Pedido Nº: {order['number']} - {order['local_created']}", bold=True)
    t.add(f"{order['customer']} {phone_text(order['phone'])}", bold=True)
    if order.get("customer_orders"):
        t.add(f"{order['customer_orders']} pedido{'s' if order['customer_orders'] != 1 else ''}", bold=True)
    if order.get("scheduled_label"):
        t.add("AGENDADO: " + order["scheduled_label"], bold=True)
    if order["mode"] == "delivery":
        t.rule()
        t.add("ENTREGA" + (" - " + order["zone"] if order.get("zone") else ""), bold=True)
        t.add(order["address"], bold=True)
    t.rule("=")
    t.pair("PRODUTO", "VENDA", bold=True)
    t.rule("=")
    for item in order["items"]:
        t.pair(item["name"], money(item["unit_price"] * item["quantity"]), bold=True)
        t.add(f"{item['quantity']}x UN {money(item['unit_price'])}")
        t.choices(item["extras"])
        if item.get("notes"):
            t.add("   OBS: " + item["notes"], bold=True)
        t.rule()
    if order.get("notes"):
        t.add("OBS. DO PEDIDO: " + order["notes"], bold=True)
        t.rule()
    t.pair("Produtos", money(order["subtotal"]))
    if order["delivery_fee"]:
        t.pair("Entrega", money(order["delivery_fee"]))
    if order["discount"]:
        t.pair("Desconto", "- " + money(order["discount"]))
    t.rule("=")
    t.pair("Valor total", money(order["total"]), bold=True)
    t.pair("Valor pago", money(order["paid_amount"]))
    t.pair("Cobrar do cliente", money(order["due"]), bold=True)
    t.rule()
    pay = PAY.get(order["payment"], order["payment"]) + (" - JÁ PAGO" if order["paid"] else "")
    t.add(pay, bold=True, center=True)
    if order.get("change_for") and not order["paid"]:
        t.add(f"Troco para {money(order['change_for'])} (levar {money(max(0, order['change_for'] - order['due']))})", bold=True, center=True)
    t.rule()
    t.add(printed, center=True)
    t.add("SeuComércioAqui - documento não fiscal", center=True)
    return t.lines


def kitchen_ticket(order, cols, printed):
    t = Ticket(cols)
    t.add(kind_of(order) + " (COZINHA)", center=True, big=True)
    t.add(order["customer"], center=True, big=True)
    t.add(f"Pedido Nº: {order['number']}", center=True, big=True)
    t.add("Impresso: " + printed, center=True, bold=True)
    if order.get("scheduled_label"):
        t.add("AGENDADO: " + order["scheduled_label"], bold=True, center=True)
    t.rule()
    for item in order["items"]:
        t.add(f"{item['quantity']} x {item['name'].upper()}", big=True)
        t.choices(item["extras"])
        if item.get("notes"):
            t.add("   OBS: " + item["notes"], bold=True)
    if order.get("notes"):
        t.rule()
        t.add("OBS. DO PEDIDO: " + order["notes"], bold=True)
    t.rule()
    return t.lines


def register_print_agent(app, helpers):
    h = SimpleNamespace(**helpers)

    def state_key(sid):
        return f"print.agent.{sid}"

    def read_state(conn, sid):
        row = conn.execute("SELECT value FROM platform_settings WHERE key=?", (state_key(sid),)).fetchone()
        try:
            value = json.loads(row["value"]) if row else None
        except (TypeError, ValueError):
            value = None
        return value if isinstance(value, dict) else None

    def write_state(conn, sid, value):
        conn.execute("INSERT INTO platform_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (state_key(sid), json.dumps(value, separators=(",", ":"))))

    def eligible(conn, store):
        since = (datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)).isoformat(timespec="seconds")
        rows = conn.execute("""SELECT * FROM orders WHERE store_id=? AND created_at>=?
            AND status IN ('preparing','ready','delivering','completed') ORDER BY id LIMIT 200""", (store["id"], since)).fetchall()
        return [r for r in rows if r["payment"] not in ("pix_online", "card_online") or r["paid"] or r["total"] == 0]

    def scoped():
        if "print:jobs" not in json.loads(g.api_key["scopes"]):
            abort(403, description="Esta chave não tem a permissão print:jobs.")

    def columns():
        raw = request.args.get("cols", "42")
        if not raw.isdigit() or not 24 <= int(raw) <= 64:
            abort(400, description="Informe cols entre 24 e 64.")
        return int(raw)

    @app.get("/api/v1/print/jobs")
    def print_jobs():
        scoped()
        cols, store = columns(), g.store
        zone = ZoneInfo(store["timezone"] or "America/Sao_Paulo")
        with h.transaction() as conn:
            orders = eligible(conn, store)
            state = read_state(conn, store["id"])
            stamp = h.now()
            if state is None:
                # Primeira vez: o que já existia não é impresso.
                write_state(conn, store["id"], {"seen": stamp, "printed": [o["id"] for o in orders][-KEEP:]})
                orders = []
            else:
                if state.get("seen", "") < (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(timespec="seconds"):
                    write_state(conn, store["id"], {**state, "seen": stamp})
                done = set(state.get("printed", []))
                orders = [o for o in orders if o["id"] not in done][:10]
            balances = receipt_state(conn, store["id"], orders)[0] if orders else {}
            jobs = []
            printed = datetime.now(zone).strftime("%d/%m/%Y %H:%M")
            for raw in orders:
                order = dict(raw)
                items = conn.execute("SELECT name,quantity,unit_price,extras,notes FROM order_items WHERE order_id=? ORDER BY id", (raw["id"],)).fetchall()
                order["items"] = [{**dict(i), "extras": json.loads(i["extras"] or "[]")} for i in items]
                received = balances.get(raw["id"], 0)
                order["due"] = 0 if order["paid"] or order["payment"] == "credit" else max(0, order["total"] - received)
                order["paid_amount"] = order["total"] if order["paid"] else max(0, order["total"] - order["due"])
                order["local_created"] = datetime.fromisoformat(order["created_at"]).astimezone(zone).strftime("%d/%m %H:%M")
                order["scheduled_label"] = datetime.fromisoformat(order["scheduled_for"]).astimezone(zone).strftime("%d/%m às %H:%M") if order.get("scheduled_for") else ""
                order["customer_orders"] = conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE store_id=? AND status!='cancelled' AND phone=?", (store["id"], order["phone"])).fetchone()[0] if order["phone"] not in ("", "00000000000") else 0
                jobs.append({"id": raw["id"], "number": raw["number"], "counter": counter_ticket(order, store, cols, printed),
                             "kitchen": kitchen_ticket(order, cols, printed)})
        body = json.dumps({"jobs": jobs}, ensure_ascii=True)
        return app.response_class(body, mimetype="application/json")

    @app.post("/api/v1/print/jobs/<int:oid>/done")
    def print_done(oid):
        scoped()
        with h.transaction() as conn:
            if not conn.execute("SELECT id FROM orders WHERE id=? AND store_id=?", (oid, g.store["id"])).fetchone():
                abort(404, description="Pedido não encontrado.")
            state = read_state(conn, g.store["id"]) or {"printed": []}
            printed = [x for x in state.get("printed", []) if x != oid] + [oid]
            write_state(conn, g.store["id"], {**state, "seen": h.now(), "printed": printed[-KEEP:]})
        return jsonify(ok=True)

    @app.get("/api/admin/print-agent")
    @h.owner
    def print_agent_status():
        state = read_state(h.db(), g.store["id"]) or {}
        seen = state.get("seen", "")
        active = bool(seen) and seen >= (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="seconds")
        return jsonify(active=active, last_seen=seen)
