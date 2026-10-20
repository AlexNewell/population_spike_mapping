"""Invoke Blender headless on a height bundle."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess

from .config import ROOT, work_dir


def find_blender(cfg: dict) -> str:
    exe = cfg["render"].get("blender_exe") or os.environ.get("BLENDER") or shutil.which("blender")
    if not exe:  # standard install locations (Windows, macOS, Linux)
        for pattern in (r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
                        "/Applications/Blender.app/Contents/MacOS/Blender",
                        "/usr/bin/blender", "/snap/bin/blender"):
            hits = sorted(glob.glob(pattern))
            if hits:
                exe = hits[-1]
                break
    if not exe:
        raise FileNotFoundError("Blender not found: set render.blender_exe or the BLENDER env var")
    return exe


def run(cfg: dict) -> None:
    d = work_dir(cfg)
    if not (d / "heights.npz").exists():
        from . import export_heights
        export_heights.run(cfg)
    cmd = [find_blender(cfg), "-b", "--factory-startup", "-P", str(ROOT / "blender" / "build_scene.py"),
           "--", "--bundle", str(d), "--out", str(d / "render.png")]
    if cfg["render"].get("save_blend"):
        cmd += ["--blend", str(d / "scene.blend")]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("  ") or "Error" in line or "Traceback" in line:
            print(line)
    if proc.returncode != 0 or not (d / "render.png").exists():
        print(proc.stdout[-4000:], proc.stderr[-4000:])
        raise RuntimeError("Blender render failed")
