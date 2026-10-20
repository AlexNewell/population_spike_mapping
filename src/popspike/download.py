"""Fetch raw inputs (WorldPop, Natural Earth, Census totals) and record a checksum manifest."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import zipfile
from pathlib import Path

import requests

from .config import data_root, raw_path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url: str, dest: Path) -> None:
    """Stream to <dest>.part, resuming from a previous partial download when the server allows it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    done = tmp.stat().st_size if tmp.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with requests.get(url, stream=True, timeout=120, headers=headers) as r:
        r.raise_for_status()
        if "text/html" in r.headers.get("content-type", ""):
            raise RuntimeError(f"{url} returned an HTML page, not data")
        if r.status_code != 206:
            done = 0
        total = done + int(r.headers.get("content-length", 0))
        if done:
            print(f"  resuming {dest.name} at {done / total:.1%}")
        with open(tmp, "ab" if done else "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total and done % (50 << 20) < (1 << 20):
                    print(f"  {dest.name}: {done / total:5.1%}", flush=True)
    tmp.replace(dest)


def run(cfg: dict) -> None:
    manifest_path = data_root(cfg) / cfg["data"]["raw_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for key, src in cfg["data"]["sources"].items():
        dest = raw_path(cfg, key)
        if dest.exists():
            print(f"[skip] {key}: {dest}")
        else:
            print(f"[get ] {key}: {src['url']}")
            _fetch(src["url"], dest)
            manifest[key] = {
                "url": src["url"],
                "file": src["file"],
                "retrieved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "bytes": dest.stat().st_size,
                "sha256": _sha256(dest),
            }
        if dest.suffix == ".zip":
            out = dest.with_suffix("")
            if not out.exists():
                with zipfile.ZipFile(dest) as z:
                    z.extractall(out)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"manifest -> {manifest_path}")
