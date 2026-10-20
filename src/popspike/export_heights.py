"""Turn the analytical rasters into a height bundle (.npz + config JSON) that Blender can read with numpy only."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio

from .config import processed_dir, publish_dir, work_dir
from .transform import hybrid_layers, masked_smooth, to_height


def _read(d: Path, name: str) -> np.ndarray:
    with rasterio.open(d / f"{name}.tif") as src:
        return src.read(1)


def run(cfg: dict) -> Path:
    src = processed_dir(cfg)
    density, pop = _read(src, "density"), _read(src, "pop")
    land_frac, country = _read(src, "land_frac"), _read(src, "country")
    land = land_frac >= float(cfg["grid"]["min_land_frac"])

    hcfg = cfg["height"]
    value = density if hcfg["quantity"] == "density" else pop
    ref = (country == 1) if hcfg.get("normalize", "us") == "us" else None
    h = to_height(value, hcfg, ref)
    h = masked_smooth(h, land, float(hcfg["smooth_sigma"]))
    if float(hcfg["neighbor_scale"]) != 1.0:
        h = np.where(country == 1, h, h * float(hcfg["neighbor_scale"]))

    bundle = dict(height=h, land=land.astype("uint8"), country=country, value=value.astype("float32"))
    if cfg["geometry"]["type"] == "hybrid":
        hy = cfg["geometry"]["hybrid"]
        surface, spikes = hybrid_layers(h, value, land, hy)
        bundle.update(surface=surface, spikes=spikes)

    d = work_dir(cfg)
    npz = d / "heights.npz"
    np.savez_compressed(npz, **bundle)
    for target in (d, publish_dir(cfg)):  # repo copy documents how the image was made
        (target / "config.json").write_text(json.dumps(cfg, indent=2))
    n_pos = int((h > 0).sum())
    print(f"  heights {h.shape}, {n_pos:,} non-zero cells -> {npz}")
    return npz
