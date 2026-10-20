# Data sources

All inputs are downloaded by `python -m popspike download` into `<data root>/raw/`, which records each file's URL, retrieval time, size and SHA-256 in `<data root>/raw/manifest.json`. The data root is `~/popspike_data` by default, outside the repo; set `POPSPIKE_DATA` to move it. The total is about 900 MB, almost all of it the WorldPop mosaic.

| Key | Dataset | Use | License |
|---|---|---|---|
| `worldpop` | **WorldPop Global 2000–2020, 2020 mosaic, 1 km aggregated** (`ppp_2020_1km_Aggregated.tif`): unconstrained, top-down modelled people per 30″ cell | Population counts for the US, Canada, Mexico and the Caribbean in one seamless grid | CC BY 4.0 |
| `ne_land`, `ne_lakes` | Natural Earth 1:10m land and lakes | Land fraction per cell (land minus lakes), coastline mask | Public domain |
| `ne_countries` | Natural Earth 1:10m admin-0 countries | Country code per cell (US vs. neighbours) | Public domain |
| `ne_states` | Natural Earth 1:10m admin-1 states/provinces | US state per cell, validation, outline overlay | Public domain |
| `census_states` | U.S. Census Bureau state totals (`NST-EST2024-ALLDATA.csv`), column `ESTIMATESBASE2020`: the April 1, 2020 population base derived from the 2020 Census (keyless; the decennial API now requires a key) | Independent validation of the gridded totals | Public domain (U.S. Gov.) |

## Why WorldPop at 1 km (and not Census blocks or 100 m)

- The 3D mesh uses 2.5–5 km cells, so a 1 km source already oversamples the final grid 6–25×. The 100 m US raster (`usa_ppp_2020.tif`, several GB) adds no detail at this scale.
- A single global mosaic covers the neighbours too, so there are no seams between countries.
- Census blocks are authoritative but come as about 8 million polygons, which is heavy to process for little visual gain at banner scale. They are still used for validation: Census 2020 state totals are compared with the gridded WorldPop sums (see `docs/METHODS.md`).
- WorldPop values are *modelled* counts per cell, not measured density. Density is derived in this pipeline as count divided by land area (see METHODS).

## Citation

> WorldPop (www.worldpop.org — School of Geography and Environmental Science, University of Southampton; Department of Geography and Geosciences, University of Louisville; Departement de Geographie, Universite de Namur) and Center for International Earth Science Information Network (CIESIN), Columbia University (2018). Global High Resolution Population Denominators Project — Funded by The Bill and Melinda Gates Foundation (OPP1134076). https://dx.doi.org/10.5258/SOTON/WP00647

> Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com.

> U.S. Census Bureau, Population Division, Annual Estimates of the Resident Population for the United States, Regions, States (NST-EST2024-ALLDATA), April 1, 2020 estimates base.

A short attribution line suitable for a LinkedIn post: *"Data: WorldPop 2020 (CC BY 4.0), Natural Earth. Rendered with Python + Blender."*
