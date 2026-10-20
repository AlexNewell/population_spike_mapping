# Methods

The pipeline turns a modelled population raster into a 3D scene in six steps. Each step is a CLI command (`python -m popspike <step>`), and every parameter lives in `config/base.yaml` or an experiment override.

```
download -> preprocess -> validate -> heights -> render (Blender) -> compose
```

The analytical outputs (`pop.tif`, `density.tif`) are never modified by artistic choices. Everything visual happens downstream, in `heights` and `render`.

## 1. Source data

WorldPop 2020 global mosaic (unconstrained, ~1 km / 30″ cells, people per cell). See [DATA_SOURCES.md](DATA_SOURCES.md). A lon/lat window (−135…−55°E, 12…58°N) is cut out once, which keeps all later steps fast.

## 2. Source sanitizing (`grid.max_pixel_density`, default 100,000 people/km²)

WorldPop's modelled surface contains a few isolated "hot" pixels. The worst is **672,315 people in a single ~0.83 km² pixel in Monterrey, MX**. For comparison, the densest Manhattan pixel holds about 44k people (≈66k/km²). Left alone, that one artifact would set the height scale and make Monterrey the tallest point on the map.

Each pixel's true area is computed from its latitude: `(Δλ·111.32 km)·(Δφ·111.32 km)·cos φ`. Pixels above the cap are clamped to it. In this extent, 15 pixels were clamped (all in metropolitan Monterrey), removing 1.9 M people. Every clamped pixel is listed in [sanitized_pixels.csv](sanitized_pixels.csv). No US pixel comes close to the cap.

## 3. State-level census calibration (`grid.calibrate_to_census`)

WorldPop's 2020 numbers come from top-down projections that overshoot the actual 2020 Census in fast-growing Sun Belt states:

| | CONUS total | vs. Census | Mean abs. state error |
|---|---|---|---|
| Census 2020 (April 1 base) | 329,327,089 | | |
| WorldPop, as published | 341,337,625 | **+3.65%** | 4.78% |
| After calibration (2.5 km grid) | 331,323,886 | **+0.61%** | 0.59% |

Worst raw states: Nevada +18.5%, New Mexico +13.6%, Arizona +13.1%, Wyoming +12.4%.

Calibration works at the native ~1 km resolution. US state polygons (Natural Earth) are rasterized onto the source grid. Every pixel in state *s* is multiplied by `census_s / Σ worldpop_s`; the factors range from 0.844 (Nevada) to 1.091 (DC) and are listed in [census_calibration.csv](census_calibration.csv). WorldPop still decides *where* people are within a state, and the Census decides *how many*.

Alaska and Hawaii are excluded, because only a sliver of the Alaska panhandle falls inside the window (an early bug gave it a 58× factor). Neighbours are not calibrated.

The residual +0.6% comes from two things. Coastal pixels outside every state polygon keep factor 1. And at the final grid, cells straddling a state line are assigned by cell centre (e.g. NJ +4.6%, because cells across the Hudson are counted in New Jersey). Neither affects the shape of the surface. Full table: [validation_states_2500m.csv](validation_states_2500m.csv).

## 4. Reprojection: population-conserving binning

- **Target CRS:** EPSG:5070 (USA Contiguous Albers Equal Area). Every cell has the same true area, which density requires.
- **Extent:** x −2,800…2,700 km, y −400…3,600 km. That covers CONUS, southern Canada, northern Mexico, Cuba and the Bahamas.
- **Resolution:** 5 km for exploration, 2.5 km for the final.

Each source pixel is split into 3×3 sub-samples, each carrying 1/9 of its population. The sub-samples are projected to EPSG:5070 and summed into target cells with `np.bincount`. This conserves population exactly, unlike interpolating resamplers. It also avoids the moiré that single-centroid binning causes when ~2.5 source pixels map to one target cell.

## 5. Land fraction and density

- **Land fraction:** Natural Earth 10m land minus lakes, rasterized at 1/10 of the cell size (250 m for the 2.5 km grid), then block-averaged.
- **Water:** cells with less than 5% land are treated as water (`grid.min_land_frac`).
- **Density:** `ρ = pop / (cell_km² · max(land_frac, 0.3))`. The 0.3 denominator floor (`grid.density_land_floor`) stops shoreline cells with a sliver of land from inflating more than 3.3×. Before the floor, a Toronto shoreline cell with 6% land registered 37k/km².
- **Country and state codes:** rasterized by cell centre. Coastal land cells whose centre falls in water take the nearest code.

**Result (2.5 km):** median land cell 1.0/km², 99th percentile 1,124/km², 99.99th percentile 15,092/km². The US maximum is 44,705/km² (Upper East Side, Manhattan).

## 6. Height transforms (`height.*`, `src/popspike/transform.py`)

All transforms are monotonic, so they change emphasis but never the order of densities.

| Transform | Formula | Effect (see `renders/experiments/sheet_20_transform.png`) |
|---|---|---|
| linear | h = ρ | Honest but extreme: only NYC and a few cores register |
| power | h = ρ^p | p = 0.75 keeps a clear metro hierarchy, and the published banner uses 0.68 to lift mid-size metros slightly; p = 0.5 and 0.3 lift towns until the Plains fill in |
| log1p | h = ln(1+ρ) | Settlement pattern; magnitude is lost ("people live everywhere") |
| quantile | h = rank(ρ) | Pure structure; magnitude discarded |

Choices that apply to all transforms:

- **Floor:** cells below `height.floor` get zero height.
- **Normalization (`height.normalize: us`):** the densest US cell (Manhattan) = 1.0. The few neighbour cells above it (Port-au-Prince, sanitized Monterrey) are clipped to 1.0.
- **Neighbour scale (`height.neighbor_scale`):** the final uses 0. Canada, Mexico and the Caribbean appear as land silhouettes without columns, which keeps the focus on the US. This is a display choice only; the analytical rasters keep their populations. Experiments 10–74 show neighbours at true height, faded toward the background.
- **Density vs. count:** `height.quantity: count` uses people per cell instead of people per km² of land (experiment 25). Because cells are equal-area, the two differ only at coasts.

## 7. Geometry (`blender/build_scene.py`)

Blender needs only its bundled numpy. The handoff is `heights.npz` plus `config.json`. Meshes are built with `foreach_set`, so even the largest scene builds in a couple of seconds.

| Type | Construction |
|---|---|
| terrain | One vertex per cell centre at `base + h·max_height`; quads wherever any corner is land; smooth shaded; optional masked Gaussian (normalized convolution, so coasts don't bleed into the sea) |
| spikes | One prism per cell above `spikes.min_value`, footprint `0.55·cell` (gaps show), optional `taper` for needles; merged into a single mesh (113k columns in the final) |
| hybrid | Low-pass surface (σ = 4 cells, capped at 20% of max height) plus tapered needles where ρ ≥ 300/km², rising from the surface |

Vertical exaggeration is `geometry.max_height` in scene units against a 60-unit map width. The final uses 7.0, so the Manhattan column rises about 640 km in map-scale terms (7/60 of 5,500 km).

## 8. Shading, lighting, camera

- **Material:** Principled BSDF. Base colour comes from a palette ramp driven by the per-vertex `h` attribute, with emission only above `emission_from`. Neighbours are darkened (`neighbor_dim`) and faded toward the background (`neighbor_fade`).
- **Atmosphere:** depth fade mixes toward the background colour by camera distance (a cheap stand-in for atmospheric perspective). The sea is a plane in the background colour that emits only toward the camera, so the land floats on darkness, the data extent's edges vanish, and a tinted sea never lights the columns. An optional `column_fog` palette key lets columns fade toward a different (neutral) colour than the land, so a tinted background doesn't tint the gold.
- **Lighting presets:** `raking_west`, `top_ao`, `rim`, `dusk_south`. The final uses `dusk_south`: a warm sun 9° above the horizon, behind the camera, plus a cool fill.
- **Camera:** perspective, 50 mm, 24° elevation, from the SSW (azimuth −12°). A lens shift moves the map right, leaving dark space on the left for the profile photo.
- **Render:** Cycles on GPU (OptiX), 256 samples, OpenImageDenoise. AgX view transform, Medium High Contrast look.

## 9. Composition and export (`src/popspike/compose.py`)

- **Vignette:** a light vignette, biased toward the left.
- **Exports:** 3168×792 master; 1584×396 PNG and JPG (q95, 4:4:4), downscaled with Lanczos.
- **Safe-area preview:** an approximate LinkedIn desktop profile-photo footprint (lower left), plus the side regions lost in a 3:1 mobile crop. LinkedIn doesn't publish exact geometry and it varies by viewport, so treat the overlay as a planning aid.
