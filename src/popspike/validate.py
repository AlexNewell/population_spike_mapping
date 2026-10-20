"""Validation: compare gridded WorldPop totals with Census 2020 state counts; draw an outline overlay."""
from __future__ import annotations

import csv
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from .config import processed_dir
from .preprocess import CONUS_EXCLUDE, _vectors, census_totals


def _read(d, name):
    with rasterio.open(d / f"{name}.tif") as src:
        return src.read(1), src.bounds


def run(cfg: dict) -> None:
    d = processed_dir(cfg)
    pop, bounds = _read(d, "pop")
    raw, _ = _read(d, "pop_worldpop_raw")
    state, _ = _read(d, "state")
    density, _ = _read(d, "density")
    country, _ = _read(d, "country")
    names = {int(k): v for k, v in json.loads((d / "states.json").read_text()).items()}

    census = census_totals(cfg)
    n_ids = max(names) + 1
    sums = np.bincount(state.ravel(), weights=pop.ravel(), minlength=n_ids)
    sums_raw = np.bincount(state.ravel(), weights=raw.ravel(), minlength=n_ids)
    table = []
    for idx, name in sorted(names.items(), key=lambda kv: kv[1]):
        if name in CONUS_EXCLUDE or name not in census:
            continue
        c, wr, wp = census[name], float(sums_raw[idx]), float(sums[idx])
        table.append((name, c, round(wr), (wr - c) / c * 100, round(wp), (wp - c) / c * 100))
    total_c = sum(r[1] for r in table)
    total_r = sum(r[2] for r in table)
    total_w = sum(r[4] for r in table)
    mape_raw = np.mean([abs(r[3]) for r in table])
    mape = np.mean([abs(r[5]) for r in table])

    report = d / "validation_states.csv"
    with open(report, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state", "census_2020", "worldpop_raw_5km", "raw_pct_diff", "final_5km", "final_pct_diff"])
        w.writerows([(n, c, wr, f"{pr:+.2f}", wp, f"{p:+.2f}") for n, c, wr, pr, wp, p in table])
        w.writerow(["CONUS+DC", total_c, total_r, f"{(total_r - total_c) / total_c * 100:+.2f}",
                    total_w, f"{(total_w - total_c) / total_c * 100:+.2f}"])

    by_country = {k: float(pop[country == v].sum()) for k, v in [("USA", 1), ("CAN", 2), ("MEX", 3), ("other", 4)]}
    summary = dict(conus_census=total_c,
                   raw=dict(conus=total_r, conus_pct_diff=(total_r - total_c) / total_c * 100,
                            state_mean_abs_pct_diff=mape_raw,
                            worst_states=[r[:4] for r in sorted(table, key=lambda r: -abs(r[3]))[:5]]),
                   final=dict(conus=total_w, conus_pct_diff=(total_w - total_c) / total_c * 100,
                              state_mean_abs_pct_diff=mape,
                              worst_states=[(r[0], r[1], r[4], r[5])
                                            for r in sorted(table, key=lambda r: -abs(r[5]))[:5]]),
                   population_by_country_in_extent=by_country,
                   density_percentiles={p: float(np.percentile(density[density > 0], p))
                                        for p in (50, 90, 99, 99.9, 99.99)},
                   max_density=float(density.max()))
    (d / "validation_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"  CONUS census {total_c:,} | raw WorldPop {total_r:,} ({summary['raw']['conus_pct_diff']:+.2f}%, "
          f"state MAPE {mape_raw:.2f}%) | final {total_w:,} ({summary['final']['conus_pct_diff']:+.2f}%, "
          f"state MAPE {mape:.2f}%)")

    # overlay: log density + state outlines (checks registration of data and boundaries)
    fig, ax = plt.subplots(figsize=(16, 11), dpi=110)
    fig.patch.set_facecolor("#05070d")
    ax.set_facecolor("#05070d")
    ext = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    ax.imshow(np.log10(1 + density), extent=ext, cmap="magma", vmin=0, vmax=4, interpolation="nearest")
    _vectors(cfg, "ne_states").boundary.plot(ax=ax, color="#4fc3f7", linewidth=0.3, alpha=0.7)
    ax.set_xlim(ext[:2]); ax.set_ylim(ext[2:]); ax.axis("off")
    out = d / "validation_overlay.png"
    fig.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  -> {report}, {out}")
