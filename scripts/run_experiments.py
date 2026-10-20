"""Render every experiment config matching a glob, optionally building a contact sheet.

    python scripts/run_experiments.py "config/experiments/1*.yaml" --sheet renders/experiments/sheet_10_geometry.png
    python scripts/run_experiments.py "config/experiments/84_final_gold_navy_tint1.yaml" --force
"""
import argparse
import glob
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from popspike import compose, export_heights, render  # noqa: E402
from popspike.config import load_config, publish_dir  # noqa: E402


def main(pattern: str, sheet: str | None, force: bool = False) -> None:
    paths = []
    for p in sorted(glob.glob(str(ROOT / pattern))):
        cfg = load_config(p)
        d = publish_dir(cfg)
        if force or not (d / "banner_1584x396.png").exists():
            t = time.time()
            print(f"=== {cfg['name']}")
            export_heights.run(cfg)
            render.run(cfg)
            compose.run(cfg)
            print(f"    {time.time() - t:.0f}s")
        paths.append(d / "banner_1584x396.png")
    if sheet:
        compose.contact_sheet(paths, ROOT / sheet)
        print(f"contact sheet -> {sheet}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", help="glob of experiment YAMLs, relative to the repo root")
    ap.add_argument("--sheet", default=None, help="write a contact sheet of the results to this PNG")
    ap.add_argument("--force", action="store_true", help="re-render even if a banner already exists")
    args = ap.parse_args()
    main(args.pattern, args.sheet, args.force)
