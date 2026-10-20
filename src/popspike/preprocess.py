"""Geospatial preprocessing: WorldPop counts -> EPSG:5070 grid of population, land fraction and density.

Outputs (<data root>/processed/<res>m/):
  pop.tif        people per cell (float32), population-conserving (census-calibrated if enabled)
  pop_worldpop_raw.tif  same, sanitized but not census-calibrated
  land_frac.tif  fraction of each cell that is land (Natural Earth land minus lakes)
  density.tif    people per km² of land (float32); 0 where land_frac < min_land_frac
  country.tif    uint8 country code (see COUNTRY_CODES), 0 = water
  state.tif      uint8 US state index (see states.json), 0 = not US
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from scipy import ndimage

from .config import processed_dir, raw_path

COUNTRY_CODES = {"USA": 1, "CAN": 2, "MEX": 3}  # everything else on land -> 4
OTHER = 4
# only partly (Alaska panhandle) or not at all inside the clip window: never calibrate these
CONUS_EXCLUDE = {"Alaska", "Hawaii", "Puerto Rico"}


def grid_spec(cfg: dict):
    xmin, ymin, xmax, ymax = cfg["grid"]["extent"]
    res = float(cfg["grid"]["resolution_m"])
    nx, ny = int(round((xmax - xmin) / res)), int(round((ymax - ymin) / res))
    return from_origin(xmin, ymax, res, res), nx, ny, res


def clip_worldpop(cfg: dict) -> Path:
    """Cut the lon/lat window out of the global mosaic (once) to keep later steps fast."""
    src_path = raw_path(cfg, "worldpop")
    out = src_path.with_name("worldpop_clip.tif")
    if out.exists():
        return out
    w, s, e, n = cfg["data"]["clip_bbox_lonlat"]
    with rasterio.open(src_path) as src:
        win = from_bounds(w, s, e, n, src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win, masked=True).filled(0).astype("float32")
        arr[arr < 0] = 0
        prof = src.profile | dict(
            driver="GTiff", height=arr.shape[0], width=arr.shape[1], dtype="float32",
            transform=src.window_transform(win), nodata=None, compress="deflate",
            predictor=3, tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER",
        )
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr, 1)
    print(f"  clipped WorldPop {arr.shape} total={arr.sum():,.0f}")
    return out


def bin_population(clip_path: Path, transform, nx: int, ny: int, sub: int = 3,
                   factor: np.ndarray | None = None) -> np.ndarray:
    """Project each source pixel (split into sub x sub samples) to EPSG:5070 and sum into the grid.

    Exactly conserves population inside the extent and avoids the aliasing of single-centroid binning.
    """
    to_albers = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    grid = np.zeros(ny * nx, dtype="float64")
    x0, y0, res = transform.c, transform.f, transform.a
    offs = (np.arange(sub) + 0.5) / sub
    with rasterio.open(clip_path) as src:
        st = src.transform
        for _, win in src.block_windows(1):
            block = src.read(1, window=win)
            if factor is not None:
                block = block * factor[win.row_off:win.row_off + win.height, win.col_off:win.col_off + win.width]
            rr, cc = np.nonzero(block > 0)
            if rr.size == 0:
                continue
            vals = block[rr, cc].astype("float64") / (sub * sub)
            # sub-sample positions in pixel space -> lon/lat
            dr, dc = np.meshgrid(offs, offs, indexing="ij")
            r = (rr[:, None] + win.row_off + dr.ravel()[None, :]).ravel()
            c = (cc[:, None] + win.col_off + dc.ravel()[None, :]).ravel()
            lon = st.c + c * st.a
            lat = st.f + r * st.e
            x, y = to_albers.transform(lon, lat)
            gi = np.floor((x - x0) / res).astype(np.int64)
            gj = np.floor((y0 - y) / res).astype(np.int64)
            ok = (gi >= 0) & (gi < nx) & (gj >= 0) & (gj < ny)
            grid += np.bincount(gj[ok] * nx + gi[ok], weights=np.repeat(vals, sub * sub)[ok],
                                minlength=grid.size)
    return grid.reshape(ny, nx).astype("float32")


def _vectors(cfg: dict, key: str, crs: str | None = None) -> gpd.GeoDataFrame:
    folder = raw_path(cfg, key).with_suffix("")
    shp = next(folder.rglob("*.shp"))
    gdf = gpd.read_file(shp)
    w, s, e, n = cfg["data"]["clip_bbox_lonlat"]
    gdf = gdf.cx[w - 5:e + 5, s - 5:n + 5]
    gdf = gdf.set_geometry(gdf.geometry.clip_by_rect(w - 5, s - 5, e + 5, n + 5))
    gdf = gdf[~gdf.geometry.is_empty]
    return gdf.to_crs(crs or cfg["grid"]["crs"])


def census_totals(cfg: dict) -> dict[str, int]:
    """April 1 2020 state populations (Census-based estimates base), keyed by state name."""
    with open(raw_path(cfg, "census_states"), newline="", encoding="latin-1") as f:
        return {r["NAME"]: int(r["ESTIMATESBASE2020"]) for r in csv.DictReader(f) if r["SUMLEV"] == "040"}


def sanitize_factor(cfg: dict, clip_path: Path, out: Path) -> np.ndarray:
    """Per-pixel factor that clamps physically implausible source pixels to grid.max_pixel_density.

    WorldPop's modelled surface contains a few isolated hot pixels (e.g. ~672k people in one ~0.8 km²
    pixel in Monterrey, MX, where Manhattan's densest pixel holds ~44k). Clamping them keeps one
    artifact from defining the height scale. Every clamped pixel is logged with the people removed.
    """
    cap_density = cfg["grid"].get("max_pixel_density")
    with rasterio.open(clip_path) as src:
        arr, st = src.read(1), src.transform
    factor = np.ones(arr.shape, dtype="float32")
    if not cap_density:
        return factor
    lat = st.f + (np.arange(arr.shape[0]) + 0.5) * st.e
    km_per_deg = 111.32
    area = (abs(st.a) * km_per_deg) * (abs(st.e) * km_per_deg) * np.cos(np.radians(lat))  # km² per row
    cap = (cap_density * area)[:, None]
    hot = arr > cap
    factor[hot] = (np.broadcast_to(cap, arr.shape)[hot] / arr[hot]).astype("float32")
    rr, cc = np.nonzero(hot)
    rows = []
    for r, c in zip(rr, cc):
        lon, la = st.c + (c + 0.5) * st.a, st.f + (r + 0.5) * st.e
        rows.append((f"{la:.4f}", f"{lon:.4f}", round(float(arr[r, c])), round(float(cap[r, 0])),
                     round(float(arr[r, c] - cap[r, 0]))))
    with open(out / "sanitized_pixels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lat", "lon", "worldpop_people", "cap_people", "removed"])
        w.writerows(rows)
    print(f"  sanitize: {len(rows)} pixels above {cap_density:,.0f}/km2, "
          f"{sum(r[4] for r in rows):,.0f} people removed (see sanitized_pixels.csv)")
    return factor


def census_calibration(cfg: dict, clip_path: Path, out: Path, pre: np.ndarray | None = None) -> np.ndarray:
    """Per-source-pixel factor that rescales each US state's WorldPop total to the 2020 Census count.

    Computed at the native ~1 km resolution, so the 5 km grid's coarse borders don't bias the factors.
    WorldPop still decides where people are within a state; the Census decides how many there are.
    Non-US pixels (and the rare coastal pixel outside every state polygon) keep factor 1.
    """
    with rasterio.open(clip_path) as src:
        arr, st = src.read(1), src.transform
    if pre is not None:
        arr = arr * pre
    states = _vectors(cfg, "ne_states", crs="EPSG:4326")
    states = states[states["adm0_a3"] == "USA"].reset_index(drop=True)
    ids = rasterize(zip(states.geometry, range(1, len(states) + 1)), out_shape=arr.shape,
                    transform=st, fill=0, dtype="uint8")
    sums = np.bincount(ids.ravel(), weights=arr.ravel(), minlength=len(states) + 1)
    census = census_totals(cfg)
    lut = np.ones(len(states) + 1, dtype="float32")
    rows = []
    for i, name in enumerate(states["name"], start=1):
        if name in census and name not in CONUS_EXCLUDE and sums[i] > 0:
            lut[i] = census[name] / sums[i]
            rows.append((name, census[name], round(sums[i]), f"{lut[i]:.4f}"))
    with open(out / "census_calibration.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["state", "census_2020", "worldpop_2020_native", "factor"])
        w.writerows(sorted(rows))
    print(f"  census calibration: {len(rows)} states, factors {min(float(r[3]) for r in rows):.3f}.."
          f"{max(float(r[3]) for r in rows):.3f}")
    return lut[ids]


def land_fraction(cfg: dict, transform, nx: int, ny: int) -> np.ndarray:
    k = int(cfg["grid"]["land_supersample"])
    fine_t = from_origin(transform.c, transform.f, transform.a / k, transform.a / k)
    land = _vectors(cfg, "ne_land")
    lakes = _vectors(cfg, "ne_lakes")
    shapes = [(g, 1) for g in land.geometry] + [(g, 0) for g in lakes.geometry]
    fine = rasterize(shapes, out_shape=(ny * k, nx * k), transform=fine_t, fill=0, dtype="uint8")
    return fine.reshape(ny, k, nx, k).mean(axis=(1, 3)).astype("float32")


def _fill_nearest(codes: np.ndarray, where: np.ndarray) -> np.ndarray:
    """Give cells in `where` that have code 0 the code of the nearest coded cell."""
    _, (ii, jj) = ndimage.distance_transform_edt(codes == 0, return_indices=True)
    out = codes.copy()
    out[where & (codes == 0)] = codes[ii, jj][where & (codes == 0)]
    return out


def write(path: Path, arr: np.ndarray, transform, crs: str) -> None:
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype=arr.dtype, crs=crs, transform=transform, compress="deflate") as dst:
        dst.write(arr, 1)


def run(cfg: dict) -> None:
    out = processed_dir(cfg)
    transform, nx, ny, res = grid_spec(cfg)
    crs = cfg["grid"]["crs"]
    print(f"  grid {nx} x {ny} @ {res:.0f} m")

    clip = clip_worldpop(cfg)
    clean = sanitize_factor(cfg, clip, out)
    pop_raw = bin_population(clip, transform, nx, ny, factor=clean)
    if cfg["grid"].get("calibrate_to_census"):
        pop = bin_population(clip, transform, nx, ny, factor=clean * census_calibration(cfg, clip, out, clean))
    else:
        pop = pop_raw
    print(f"  population in extent: {pop.sum():,.0f}")

    lf = land_fraction(cfg, transform, nx, ny)
    has_land = lf > 0

    countries = _vectors(cfg, "ne_countries")
    iso = countries["ADM0_A3"].map(lambda a: COUNTRY_CODES.get(a, OTHER))
    country = rasterize(zip(countries.geometry, iso), out_shape=(ny, nx), transform=transform,
                        fill=0, dtype="uint8")
    country = _fill_nearest(country, has_land | (pop > 0))

    states = _vectors(cfg, "ne_states")
    states = states[states["adm0_a3"] == "USA"].reset_index(drop=True)
    state_names = {i + 1: n for i, n in enumerate(states["name"])}
    state = rasterize(zip(states.geometry, range(1, len(states) + 1)), out_shape=(ny, nx),
                      transform=transform, fill=0, dtype="uint8")
    state = _fill_nearest(state, country == 1)
    state[country != 1] = 0

    cell_km2 = (res / 1000.0) ** 2
    min_lf = float(cfg["grid"]["min_land_frac"])
    # denominator floor: a shoreline cell with a sliver of land can't be inflated more than 1/floor
    floor_lf = max(min_lf, float(cfg["grid"].get("density_land_floor", min_lf)))
    density = np.where(lf >= min_lf, pop / (cell_km2 * np.maximum(lf, floor_lf)), 0).astype("float32")

    for name, arr in [("pop", pop), ("pop_worldpop_raw", pop_raw), ("land_frac", lf), ("density", density),
                      ("country", country), ("state", state)]:
        write(out / f"{name}.tif", arr, transform, crs)
    (out / "states.json").write_text(json.dumps(state_names, indent=1))
    meta = dict(extent=cfg["grid"]["extent"], resolution_m=res, nx=nx, ny=ny, crs=crs,
                population_total=float(pop.sum()), max_density=float(density.max()))
    (out / "grid.json").write_text(json.dumps(meta, indent=2))
    print(f"  max density {density.max():,.0f}/km2  -> {out}")
