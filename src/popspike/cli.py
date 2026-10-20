"""Command-line entry point: python -m popspike <step> [--config FILE] [--set key.path=value ...]"""
from __future__ import annotations

import argparse
import yaml

from .config import load_config

STEPS = ["download", "preprocess", "validate", "preview", "heights", "render", "compose", "all"]


def _parse_sets(items: list[str]) -> dict:
    out: dict = {}
    for item in items:
        key, value = item.split("=", 1)
        node = out
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = yaml.safe_load(value)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="popspike")
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--config", default=None, help="experiment YAML merged over config/base.yaml")
    ap.add_argument("--set", nargs="*", default=[], help="inline overrides, e.g. grid.resolution_m=2500")
    args = ap.parse_args(argv)
    cfg = load_config(args.config, _parse_sets(args.set))

    steps = ["download", "preprocess", "validate", "heights", "render", "compose"] if args.step == "all" else [args.step]
    for step in steps:
        print(f"=== {step} ({cfg['name']})")
        if step == "download":
            from . import download; download.run(cfg)
        elif step == "preprocess":
            from . import preprocess; preprocess.run(cfg)
        elif step == "validate":
            from . import validate; validate.run(cfg)
        elif step == "preview":
            from . import preview; preview.run(cfg)
        elif step == "heights":
            from . import export_heights; export_heights.run(cfg)
        elif step == "render":
            from . import render; render.run(cfg)
        elif step == "compose":
            from . import compose; compose.run(cfg)


if __name__ == "__main__":
    main()
