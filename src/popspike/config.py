"""Config loading: base.yaml deep-merged with an optional experiment override."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = ROOT / "config" / "base.yaml"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    cfg = yaml.safe_load(BASE_CONFIG.read_text())
    if path and Path(path).resolve() != BASE_CONFIG:
        cfg = deep_merge(cfg, yaml.safe_load(Path(path).read_text()) or {})
    if overrides:
        cfg = deep_merge(cfg, overrides)
    return cfg


def data_root(cfg: dict) -> Path:
    """Data lives outside the repo; POPSPIKE_DATA overrides data.root."""
    return Path(os.environ.get("POPSPIKE_DATA") or cfg["data"]["root"]).expanduser().resolve()


def raw_path(cfg: dict, key: str) -> Path:
    return data_root(cfg) / cfg["data"]["raw_dir"] / cfg["data"]["sources"][key]["file"]


def processed_dir(cfg: dict) -> Path:
    d = data_root(cfg) / cfg["data"]["processed_dir"] / f"{int(cfg['grid']['resolution_m'])}m"
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(cfg: dict) -> Path:
    """Per-experiment intermediates (heights.npz, 16-bit render): outside the repo."""
    d = data_root(cfg) / cfg["data"]["work_dir"] / cfg["name"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def publish_dir(cfg: dict) -> Path:
    """Small final outputs (banner PNG/JPG, previews, merged config): inside the repo."""
    d = ROOT / cfg["output"]["dir"] / cfg["name"]
    d.mkdir(parents=True, exist_ok=True)
    return d
