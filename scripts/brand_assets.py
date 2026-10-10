"""Gera os PNGs da marca (ícone e prévia de link) a partir do mesmo desenho do logo.svg.

Uso: python scripts/brand_assets.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

STATIC = Path(__file__).resolve().parent.parent / "static"
TEAL, ORANGE, WHITE, PAPER = (16, 63, 66), (255, 122, 26), (255, 255, 255), (246, 247, 242)


def draw_logo(size, background=None):
    """Desenha o logo (viewBox 96x96) com supersampling para bordas suaves."""
    k = size * 4 / 96
    img = Image.new("RGBA", (size * 4, size * 4), background or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = lambda *v: [x * k for x in v]
    # alça
    d.arc(s(34, 10, 62, 52), 180, 360, fill=TEAL, width=int(6 * k))
    d.line(s(34, 31, 34, 34), fill=TEAL, width=int(6 * k))
    d.line(s(62, 31, 62, 34), fill=TEAL, width=int(6 * k))
    # corpo
    d.polygon(s(17, 36, 79, 36, 74, 86, 70, 91, 26, 91, 22, 86), fill=TEAL)
    d.rounded_rectangle(s(21, 70, 75, 91), radius=7 * k, fill=TEAL)
    # toldo
    for i, color in enumerate((ORANGE, WHITE, ORANGE, WHITE)):
        x = 13 + i * 17.5
        d.rectangle(s(x, 28, x + 17.5, 42), fill=color)
        d.ellipse(s(x, 42 - 8.75, x + 17.5, 42 + 8.75), fill=color)
    # olhinhos
    for x in (40, 56):
        d.rounded_rectangle(s(x - 2.5, 54.5, x + 2.5, 65.5), radius=2.5 * k, fill=WHITE)
    # sorriso
    d.arc(s(34, 56, 62, 76.5), 30, 150, fill=ORANGE, width=int(5.5 * k))
    return img.resize((size, size), Image.LANCZOS)


def font(size, bold=True):
    for name in (("seguibl.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def og_image():
    img = Image.new("RGB", (1200, 630), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1200, 630), fill=PAPER)
    d.rectangle((0, 560, 1200, 630), fill=TEAL)
    logo = draw_logo(300)
    img.paste(logo, (90, 150), logo)
    d.text((440, 190), "SeuComércio", font=font(78), fill=TEAL)
    w = d.textlength("SeuComércio", font=font(78))
    d.text((440 + w, 190), "Aqui", font=font(78), fill=ORANGE)
    d.text((444, 300), "Peça direto da loja do seu bairro.", font=font(38, False), fill=(60, 80, 82))
    d.text((444, 355), "Cardápio digital • Entrega ou retirada", font=font(32, False), fill=(90, 110, 112))
    d.text((90, 578), "Seu negócio. Mais perto.", font=font(30), fill=WHITE)
    return img


if __name__ == "__main__":
    draw_logo(512).save(STATIC / "icon-512.png")
    draw_logo(192).save(STATIC / "icon-192.png")
    draw_logo(180, PAPER + (255,)).convert("RGB").save(STATIC / "apple-touch-icon.png")
    og_image().save(STATIC / "og-image.png", optimize=True)
    print("ok")
