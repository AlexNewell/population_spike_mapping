"""Post-processing: grade, export banner sizes, LinkedIn safe-area previews, experiment contact sheets.

The LinkedIn overlay geometry is approximate (LinkedIn does not publish exact numbers and it varies by
viewport); it is a planning aid, not a guarantee.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import ROOT, publish_dir, work_dir

BANNER = (1584, 396)
MASTER = (3168, 792)


def grade(img: Image.Image, cfg: dict) -> Image.Image:
    g = cfg.get("compose", {})
    a = np.asarray(img.convert("RGB")).astype("float32") / 255
    vig = float(g.get("vignette", 0.25))
    if vig:
        h, w = a.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        # elliptical falloff, biased so the left edge (profile photo side) darkens a bit more
        r = np.sqrt(((xx / w - 0.55) / 0.62) ** 2 + ((yy / h - 0.5) / 0.75) ** 2)
        a *= (1 - vig * np.clip(r - 0.55, 0, 1) ** 1.5)[..., None]
    return Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype("uint8"))


def safe_area(img: Image.Image) -> Image.Image:
    """Overlay approximate desktop profile-photo footprint and mobile side crop on a banner-size image."""
    im = img.convert("RGB").resize(BANNER, Image.LANCZOS)
    ov = Image.new("RGBA", BANNER, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    w, h = BANNER
    # desktop: photo circle overlapping lower-left (≈ 0.035W..0.17W, bottom ~45% of height and below)
    cx, cy, rad = int(0.105 * w), int(h * 1.02), int(0.075 * w)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(255, 60, 60, 90), outline=(255, 90, 90, 220), width=2)
    # mobile: banner shown roughly 3:1 centre crop, photo centred-left
    crop_w = int(h * 3)
    x0 = (w - crop_w) // 2
    d.rectangle([0, 0, x0, h], fill=(60, 140, 255, 55))
    d.rectangle([w - x0, 0, w, h], fill=(60, 140, 255, 55))
    d.line([x0, 0, x0, h], fill=(80, 160, 255, 200), width=1)
    d.line([w - x0, 0, w - x0, h], fill=(80, 160, 255, 200), width=1)
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


def contact_sheet(paths: list[Path], out: Path, cols: int = 2, thumb_w: int = 792) -> None:
    thumb_h = thumb_w // 4
    label_h = 22
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    for k, p in enumerate(paths):
        x, y = (k % cols) * thumb_w, (k // cols) * (thumb_h + label_h)
        sheet.paste(Image.open(p).convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS), (x, y + label_h))
        d.text((x + 6, y + 3), p.parent.name, fill=(220, 220, 220), font=font)
    sheet.save(out)


def run(cfg: dict) -> None:
    img = Image.open(work_dir(cfg) / "render.png")
    d = publish_dir(cfg)
    graded = grade(img, cfg)
    if graded.size == MASTER:
        graded.save(d / "banner_master_3168x792.png")
    banner = graded.resize(BANNER, Image.LANCZOS)
    banner.save(d / "banner_1584x396.png")
    banner.save(d / "banner_1584x396.jpg", quality=95, subsampling=0)
    safe_area(graded).save(d / "safe_area_preview.png")
    print(f"  -> {d.relative_to(ROOT)}/banner_1584x396.png (+ safe_area_preview.png)")


def sheet_cli(folder: str, out: str, cols: int = 2) -> None:
    paths = sorted(Path(folder).glob("*/banner_1584x396.png"))
    contact_sheet(paths, Path(out), cols)
    print(f"contact sheet of {len(paths)} -> {out}")


if __name__ == "__main__":
    import sys
    sheet_cli(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2)
