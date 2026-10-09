"""Inclui pequenas prévias de UI nos logs de CI para inspeção visual."""
import base64
import io
from pathlib import Path
from PIL import Image

for path in sorted(Path("artifacts").glob("*.png")):
    with Image.open(path) as picture:
        picture.thumbnail((1200, 1800))
        buffer = io.BytesIO()
        picture.convert("RGB").save(buffer, "JPEG", quality=70)
        print("UI_PREVIEW:" + path.name + ":" + base64.b64encode(buffer.getvalue()).decode("ascii"))
