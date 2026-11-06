"""Banco de imagens ilustrativas: catálogo íntegro, licenças livres e uso no produto."""
import json
import re
from pathlib import Path

from PIL import Image

from tests.test_api import app, send, register  # noqa: F401  (fixtures e utilitários)

BANK = Path(__file__).resolve().parent.parent / "static" / "banco-imagens"
LICENSES = re.compile(r"^(CC0|Public domain|PD.*|CC BY(-SA)? [0-9.]+.*)$", re.I)


def catalog():
    return json.loads((BANK / "catalogo.json").read_text(encoding="utf-8"))


def test_catalog_files_licenses_and_credits_are_consistent():
    data = catalog()
    images = data["imagens"]
    assert len(images) >= 100
    assert len({item["id"] for item in images}) == len(images)
    credits = (BANK / "creditos.html").read_text(encoding="utf-8")
    for item in images:
        assert item["categoria"] in data["categorias"]
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.webp", item["arquivo"])
        assert LICENSES.match(item["licenca"]), item
        assert item["fonte"].startswith(("https://www.flickr.com/", "https://commons.wikimedia.org/"))
        assert item["fonte"] in credits
        with Image.open(BANK / item["arquivo"]) as picture:
            assert picture.format == "WEBP" and picture.size == (600, 600)
    assert set(path.name for path in BANK.glob("*.webp")) == {item["arquivo"] for item in images}


def test_product_accepts_only_existing_bank_images(app):  # noqa: F811
    client = app.test_client()
    assert register(client).status_code == 201
    picture = "/static/banco-imagens/" + catalog()["imagens"][0]["arquivo"]
    base = {"name": "Pizza", "description": "", "price": 4000, "active": True}
    created = send(client, "POST", "/api/admin/products", {**base, "image": picture})
    assert created.status_code == 201
    assert client.get("/api/admin/products").json["products"][0]["image"] == picture
    assert client.get(picture).status_code == 200
    for invalid in ("/static/banco-imagens/nao-existe.webp", "/static/banco-imagens/../app.js",
                    "/static/banco-imagens/catalogo.json", "/static/app.js"):
        assert send(client, "POST", "/api/admin/products", {**base, "image": invalid}).status_code == 400
