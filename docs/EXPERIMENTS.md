# Visual experiments

Each experiment is one YAML file in `config/experiments/`, deep-merged over `config/base.yaml`, and changes one thing from the baseline unless noted. The baseline is square spikes at 5 km, power 0.5, 24° camera, raking light from the west, and the gold palette. Running an experiment writes its banner, safe-area preview and merged `config.json` to `renders/experiments/<name>/`. Contact sheets go to `renders/experiments/sheet_*.png`. Renders are git-ignored, so regenerate them locally, or download the full set from the GitHub Releases.

Regenerate a group with `python scripts/run_experiments.py "config/experiments/2*.yaml" --sheet renders/experiments/sheet_20_transform.png --force`.

## Geometry (`sheet_10_geometry.png`)

| Exp | Treatment | Verdict |
|---|---|---|
| 10_terrain | Continuous surface, σ = 1.5 cells | Organic but reads as a field of cones at 5 km; small cities blur into bumps |
| 11_spikes | Square columns, 55% footprint | Most legible: discrete columns read as places, gaps give texture. **Chosen** |
| 12_needles | Tapered needles (12% top width) | Elegant up close; at banner size they thin out and lose presence |
| 13_hybrid | Smoothed rural surface plus needles above 300/km² | Nice soft base, but two visual languages compete at small sizes |

## Height transform (`sheet_20_transform.png`)

| Exp | Transform | Verdict |
|---|---|---|
| 20_linear | ρ | Honest, but only NYC registers; the rest of the country is flat |
| 21_power03 | ρ^0.3 | Punchy but noisy; every town becomes a tower |
| 22_power05 | ρ^0.5 | Balanced; became the sweep baseline |
| 23_log1p | ln(1+ρ), floor 20 | A wall of columns; magnitude story lost |
| 24_quantile | rank | Pure structure, no magnitude; the least truthful |
| 25_count | people per cell (not per km² land) | Nearly identical to 22, because cells are equal-area; differs only at coasts |

Follow-up at 2.5 km: p = 0.65 and **p = 0.75** with `min_value` 50 separate metros from towns best, and the Great Plains go dark again. After feedback round 1 the published banner settled on p = 0.68.

## Vertical exaggeration (`sheet_30_exaggeration.png`)

`max_height` of 2.5, 5 and 9 scene units, against a 60-unit map width. 2.5 is too timid at banner size, and 9 is dramatic but cluttered, with foreground columns occluding the Gulf Coast. **The finals use 7.**

## Camera (`sheet_40_camera.png`)

| Exp | View | Verdict |
|---|---|---|
| 40_cam_low | 13° elevation | Dramatic skyline, but the map shrinks to a thin strip |
| 41_cam_mid | 24° elevation | Best balance of skyline and recognizable shape for 4:1. **Chosen** |
| 42_cam_high | 42° elevation | Most map-like, but too tall for 4:1; the coasts get cropped |
| 43_cam_southeast | From the SE | Interesting; the Atlantic seaboard leads, but the West reads poorly |
| 44_northeast_corridor | DC to Boston close-up at 2.5 km, from over the Atlantic | **Strong alternate banner**: NYC as a single tower |

## Lighting (`sheet_50_lighting.png`)

| Exp | Preset | Verdict |
|---|---|---|
| 50_light_raking | Low sun from the WSW | Long shadows, moody; columns half in shade |
| 51_light_top | High soft sun plus sky | Flat; lights the land plinth grey |
| 52_light_rim | Sun from the north (backlight) | Specular glare blows out the plinth: rejected |
| 53_light_dusk | Low warm sun behind the camera | Every column lit on its visible face; land stays dark. **Chosen** |

## Palette (`sheet_60_palette.png`)

| Exp | Palette | Verdict |
|---|---|---|
| 60_pal_gold | Gold on navy-black | Warmest, highest impact. **Final** |
| 61_pal_ice | Ice blue / white | Crisp and corporate, sits well with LinkedIn's blue UI. **Alternate final** |
| 62_pal_mono | Warm white | Elegant but low energy at small sizes |
| 63_pal_gradient | Navy, teal, gold | Encodes density twice (height and hue); muddier |

## Finalists (`sheet_70_finalists.png`)

Experiments 70–74 combine the winners (dusk light, 6.5 exaggeration) across 5 km vs. 2.5 km, spikes vs. needles vs. hybrid, and gold vs. ice. The combination was too bright and busy at p = 0.5, which led to the p = 0.75 / `min_value` 50 refinement.

Showing neighbour columns at true height revealed a composition problem. Monterrey sits in the foreground next to South Texas and rises nearly as tall as Manhattan, and Toronto and Montreal break the northern skyline. The final therefore draws neighbours as land silhouettes only (`height.neighbor_scale: 0`).

## Final (`renders/final/`)

- **80_final_gold:** spikes at 2.5 km (113,201 columns), power 0.75, `max_height` 7, dusk light, gold. 3168×792 at 256 samples, plus the 1584×396 export.
- **81_final_ice:** identical, in the ice-blue palette.
- **84_final_gold_navy_tint1:** the published banner (see the feedback rounds below): power 0.68, brightened mid-density gold, very subtle navy background.

## Feedback round 1: readability at display size

Reviewer feedback: mid-density areas may go nearly invisible at LinkedIn's display sizes, and the top peaks pull attention to the edges. Two variants were made from 80. The comparison at roughly displayed sizes (about 804 px desktop card, about 390 px phone) is in `renders/final/compare_display_sizes.png`.

Luminance below is measured on the masters. Mid-columns are pixels at 0.08–0.45 luminance in 80, within the central-US band.

| Variant | Change | Background | Mid-columns | Peaks (p99.95) | Lit area, central US |
|---|---|---|---|---|---|
| 80_final_gold | baseline | 0.027 | 0.198 | 0.750 | 17.5% |
| 82_final_gold_bright_mids | low/mid ramp stops ×1.25 | 0.027 (same) | 0.234 (**+18%**) | 0.785 (+5%) | 19.3% |
| 83_final_gold_bright_compressed | as 82, plus power 0.75 → 0.68 | 0.027 (same) | 0.262 (**+32%**) | 0.801 (+7%) | 24.2% |

83 shows the most structure at phone size, and NYC remains clearly the tallest peak.

## Feedback round 2: subtle navy background

Experiments 84–86 take 83 and tint the background, sea and land floor navy, leaving the gold ramp unchanged. Comparisons: `renders/final/compare_navy_tint.png` and `renders/final/compare_navy_tint_phone.png`.

| Variant | Background input | Background as rendered (sRGB) | Gold column interiors |
|---|---|---|---|
| 83 (reference) | `#05080f` | (2, 8, 17): reads black | (198, 139, 72) |
| 84 tint1 | `#060b18` | (2, 14, 31): **very subtle navy** | (198, 139, 73) |
| 85 tint2 | `#070d1e` | (1, 18, 42): clearly navy, still dark | (198, 139, 73) |
| 86 tint3 | `#080f24` | (1, 22, 53): deep blue | (198, 139, 73) |

Two technical findings:

- **AgX and +1.7 exposure amplify dark tints strongly.** The first attempt (`#07102a`, `#0a1638`) rendered as (0, 26, 63) and royal blue, so the steps were redone much finer.
- **The tint initially leaked into the gold.** Column interiors gained +5 to +12 in blue with unchanged red and green, a purely additive navy component that dropped saturation from 0.64 to 0.57. The cause was the depth fog, which blends each surface toward the background colour. The fix is a separate `column_fog` palette key: columns fade toward the original neutral near-black, while the land floor still fades toward navy, so the horizon stays seamless. The flat sea was also made camera-ray-only, so a tinted sea can never light the scene.

## Lessons recorded along the way

- A single artifact pixel (Monterrey, 672k people) set the height scale until source sanitizing was added (METHODS §2).
- A lit sea plane turned the background mid-grey and exposed the data extent's straight edges. An unlit sea in the background colour fixed both.
- Neighbour dimming that only darkens base colour still lets specular highlights through. Fading toward the background colour works.
