"""Envia somente fotos WebP reprocessadas para o Storage remoto."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import abort


def put_image(config, store_id, filename, content):
    path = f"{store_id}/{filename}"
    if not re.fullmatch(r"[1-9][0-9]*/[a-f0-9]{32}\.webp", path):
        raise ValueError("Caminho de foto inválido.")
    endpoint, token = config["STORAGE_UPLOAD_URL"], config["STORAGE_UPLOAD_TOKEN"]
    if not endpoint.startswith("https://") or len(token) < 32:
        raise RuntimeError("Configure o endpoint e a credencial de upload.")
    request = Request(endpoint, data=content, method="POST", headers={
        "Authorization": "Bearer " + token, "Content-Type": "image/webp", "X-Object-Path": path})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        expected = config["STORAGE_PUBLIC_URL"].rstrip("/") + "/" + path
        if result.get("url") != expected:
            raise ValueError("Resposta de armazenamento inválida.")
        return expected
    except (HTTPError, URLError, TimeoutError, ValueError):
        abort(503, description="Não foi possível salvar a foto. Tente novamente.")
