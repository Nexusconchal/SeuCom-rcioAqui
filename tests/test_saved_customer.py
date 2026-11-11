"""Cadastro do cliente guardado na loja: o telefone traz nome e endereço dos pedidos anteriores."""
import uuid

from tests.test_api import app, shop, send, payload


def order(client, pid, **values):
    result = send(client, "POST", "/api/store/minha-loja/orders", payload(pid, **values), uuid.uuid4().hex)
    assert result.status_code == 201, result.json
    return result.json


def lookup(client, phone):
    return send(client, "POST", "/api/store/minha-loja/customer", {"phone": phone}).json


def test_phone_brings_back_name_and_last_delivery_address(shop):
    client, pid = shop
    assert lookup(client, "11988887777") == {"found": False}
    order(client, pid, customer="Maria Souza", phone="(11) 98888-7777", address="Rua Antiga, 10, Centro")
    assert lookup(client, "11988887777")["address"] == "Rua Antiga, 10, Centro"
    # Mudou o endereço no pedido seguinte: o cadastro acompanha.
    order(client, pid, customer="Maria S.", phone="11988887777", address="Avenida Nova, 500, Jardim")
    found = lookup(client, "+55 11 98888-7777")
    assert found["found"] and found["customer"] == "Maria S." and found["address"] == "Avenida Nova, 500, Jardim"
    # Retirada não apaga o endereço de entrega guardado.
    order(client, pid, customer="Maria S.", phone="11988887777", mode="pickup", address="")
    assert lookup(client, "11988887777")["address"] == "Avenida Nova, 500, Jardim"
    assert lookup(client, "11900000000") == {"found": False}
    assert lookup(client, "119") == {"found": False}
    assert send(client, "POST", "/api/store/nao-existe/customer", {"phone": "11988887777"}).status_code == 404


def test_customer_who_unchecks_remember_is_not_returned(shop):
    client, pid = shop
    order(client, pid, phone="11977776666")
    assert lookup(client, "11977776666")["found"]
    order(client, pid, phone="11977776666", remember=False)
    assert lookup(client, "11977776666") == {"found": False}
