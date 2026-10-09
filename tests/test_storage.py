"""O upload remoto não envia o original e falhas não viram sucesso."""
import io
import json
from urllib.error import HTTPError

import pytest
from PIL import Image

from tests.test_api import app, shop, session_token


def test_remote_upload_reencodes_photo(app, shop, monkeypatch):
    client, _ = shop
    app.config.update(STORAGE_UPLOAD_URL="https://example.supabase.co/functions/v1/commerce-upload",
        STORAGE_UPLOAD_TOKEN="test-only-token-with-at-least-32-characters",
        STORAGE_PUBLIC_URL="https://example.supabase.co/storage/v1/object/public/commerce-photos")
    received = {}

    def remote(request, timeout):
        received["request"] = request
        assert request.get_method() == "POST" and timeout == 30
        assert request.get_header("Content-type") == "image/webp"
        assert request.get_header("Authorization").startswith("Bearer ")
        photo = Image.open(io.BytesIO(request.data))
        assert photo.format == "WEBP" and photo.size == (20, 20)
        path = request.get_header("X-object-path")
        response = io.BytesIO(json.dumps({"url": app.config["STORAGE_PUBLIC_URL"] + "/" + path}).encode())
        return response

    monkeypatch.setattr("storage.urlopen", remote)
    source = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(source, "PNG")
    source.seek(0)
    response = client.post("/api/admin/upload", data={"file": (source, "original.png")},
        headers={"X-CSRF-Token": session_token(client)})
    assert response.status_code == 201
    assert response.json["url"].startswith(app.config["STORAGE_PUBLIC_URL"] + "/")
    assert not list(__import__("pathlib").Path(app.config["UPLOAD_DIR"]).glob("*.webp"))


def test_remote_storage_failure_is_retryable(app, shop, monkeypatch):
    client, _ = shop
    app.config.update(STORAGE_UPLOAD_URL="https://example.supabase.co/functions/v1/commerce-upload",
        STORAGE_UPLOAD_TOKEN="test-only-token-with-at-least-32-characters",
        STORAGE_PUBLIC_URL="https://example.supabase.co/storage/v1/object/public/commerce-photos")
    def fail(request, timeout):
        raise HTTPError(request.full_url, 503, "Unavailable", {}, None)
    monkeypatch.setattr("storage.urlopen", fail)
    source = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(source, "PNG")
    source.seek(0)
    response = client.post("/api/admin/upload", data={"file": (source, "test.png")},
        headers={"X-CSRF-Token": session_token(client)})
    assert response.status_code == 503 and "foto" in response.json["error"]
