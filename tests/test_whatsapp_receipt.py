"""Mensagens de WhatsApp para o cliente no estilo comprovante."""
import json

from order_flow import customer_message

STORE = {"name": "JS Palmeiras", "address": "Avenida União, 891", "delivery_minutes": "45 min"}


def order(**values):
    base = {"customer": "Rafael Souza", "number": 98, "scheduled_for": "", "mode": "pickup", "address": "",
            "payment": "card", "change_for": None, "paid": 0, "delivery_fee": 0, "discount": 0, "total": 2400,
            "notes": "", "motoja_info": "{}"}
    return {**base, **values}


ITEMS = [{"name": "Marmita M (Média) – Segunda", "quantity": 1, "unit_price": 2400, "notes": "",
          "extras": json.dumps([{"name": "Mistura: Frango Grelhado"}, {"name": "Guarnições: Creme de Milho"}])}]


def test_new_order_message_lists_items_pickup_and_payment():
    text = customer_message(order(), STORE, "new", "https://x/pedido/abc", ITEMS)
    assert text.startswith("*Rafael*, recebemos o seu pedido *#98*")
    assert "1x Marmita M (Média) – Segunda (Mistura: Frango Grelhado, Guarnições: Creme de Milho) - R$ 24,00" in text
    assert "Retirar em: Avenida União, 891. Tempo estimado: 45 min." in text
    assert "Cartão na entrega/retirada" in text and "https://x/pedido/abc" in text


def test_delivery_cash_change_and_follow_up_messages():
    o = order(mode="delivery", address="Rua A, 10 - Centro", payment="cash", change_for=5000, delivery_fee=500, total=2900)
    text = customer_message(o, STORE, "new", "L", ITEMS)
    assert "Entrega: R$ 5,00" in text and "*Total: R$ 29,00*" in text
    assert "Entregar em: Rua A, 10 - Centro." in text and "Dinheiro (troco para R$ 50,00)" in text
    assert customer_message(o, STORE, "preparing", "L") == "Pedido #98 confirmado! ✅ Já estamos preparando o seu pedido."
    review = customer_message(o, STORE, "completed", "https://x/pedido/abc")
    assert "Como foi a sua experiência?" in review and "https://x/pedido/abc" in review
