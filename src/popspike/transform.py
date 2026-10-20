"""Height transforms: analytical raster (density or count) -> normalised height in [0, 1].

All functions are monotonic, so the ordering of densities is preserved; only visual emphasis changes.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def to_height(value: np.ndarray, hcfg: dict, reference: np.ndarray | None = None) -> np.ndarray:
    """Monotonic transform, normalised so the maximum inside `reference` (default: everywhere) is 1.

    Cells above that maximum (only possible outside the reference area) are clipped to 1.
    """
    v = np.where(value >= float(hcfg["floor"]), value, 0.0).astype("float64")
    pos = v > 0
    if hcfg.get("clip_percentile"):
        ceiling = np.percentile(v[pos], float(hcfg["clip_percentile"]))
        v = np.minimum(v, ceiling)
    kind = hcfg["transform"]
    if kind == "log1p":
        h = np.log1p(v)
    elif kind == "power":
        h = v ** float(hcfg["power"])
    elif kind == "linear":
        h = v
    elif kind == "quantile":
        h = np.zeros_like(v)
        order = np.argsort(v[pos], kind="stable")
        ranks = np.empty(order.size)
        ranks[order] = np.arange(1, order.size + 1)
        h[pos] = ranks / order.size
    else:
        raise ValueError(f"unknown transform {kind!r}")
    ref = reference if reference is not None else np.ones(h.shape, dtype=bool)
    h = np.minimum(h / h[ref].max(), 1.0)
    return h.astype("float32")


def masked_smooth(h: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing restricted to `mask` (normalised convolution, so coasts don't bleed into sea)."""
    if sigma <= 0:
        return h
    m = mask.astype("float32")
    num = ndimage.gaussian_filter(h * m, sigma)
    den = ndimage.gaussian_filter(m, sigma)
    return np.where(mask, num / np.maximum(den, 1e-6), 0).astype("float32")


def hybrid_layers(h: np.ndarray, density: np.ndarray, mask: np.ndarray, hy: dict):
    """Low-pass surface (capped) + needle heights for cells above the density threshold."""
    surface = masked_smooth(h, mask, float(hy["surface_sigma"]))
    surface = np.minimum(surface, float(hy["surface_cap"]))
    spikes = np.where(density >= float(hy["spike_min_value"]), np.maximum(h, surface), 0).astype("float32")
    return surface.astype("float32"), spikes
