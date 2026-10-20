"""Fast 2D previews of the height field (hillshade) for quick iteration before Blender."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LightSource

from .config import ROOT, publish_dir, work_dir
from .export_heights import run as export


def run(cfg: dict) -> None:
    w, d = work_dir(cfg), publish_dir(cfg)
    if not (w / "heights.npz").exists():
        export(cfg)
    b = np.load(w / "heights.npz")
    h = b["surface"] if "surface" in b else b["height"]
    ls = LightSource(azdeg=255, altdeg=20)
    rgb = ls.shade(h * cfg["geometry"]["max_height"] * 40, cmap=plt.get_cmap("cividis"),
                   blend_mode="soft", vert_exag=1)
    rgb[b["land"] == 0] = (0.02, 0.03, 0.06, 1)
    plt.imsave(d / "preview_hillshade.png", rgb)
    print(f"  -> {(d / 'preview_hillshade.png').relative_to(ROOT)}")
