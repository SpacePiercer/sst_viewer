---
name: coastal-points
description: Generate groups of SST sample points along a new coastline stretch — 3 points 1/3/5 km offshore per group, evenly spaced along the shore, bays skipped — writing the region's .txt and .csv. Use when the user asks for coastal points / offshore sample points for a new region, or invokes /coastal-points.
---

# coastal-points — offshore sample points for a new coast

The engine already exists: `scripts\make_coast_points.py`. It walks a
coastline at 1 km resolution (global-land-mask), drops a group every ~28 km,
places 3 points 1/3/5 km offshore along the coast normal, skips bays, and drops
any point sitting <d km from another shoreline. Your job is to add a REGIONS
entry for the new stretch and run it — never hand-compute points.

## 1. Interview for the region (one message)

Ask only what the script needs:

- **name** — kebab/underscore id, e.g. `sakhalin_east`.
- **start** — `(lon, lat)` seed at the south/first end of the stretch.
- **stop** — either `("lat_max", <lat>)` (walk north until latitude passes it)
  or `("point", (lon, lat))` (walk to a named cape).
- **conditions** — confirm defaults or override: `ALONG_KM=28` spacing,
  `OFFSETS_KM=(1,3,5)`. These are module-level; only change if the user asks.
- **known bad mask?** — if the land mask is wrong somewhere (phantom cape/bay
  from cloud/ice), get `drop_above_lat` and/or `manual_east=[(lat,lon),...]`
  village-shore points to pin manually (see the `primorsky_south` entry).

## 2. Add the REGIONS entry + run

Add the dict to `REGIONS` in `make_coast_points.py` (match the existing
entries), then:

```
conda run -n mfa_env python scripts/make_coast_points.py <name>
```

The script writes `<out>.csv` (group,distance_km,latitude,longitude) and
`<out>.txt` (one `lat, lon` per line) into `data\`.

## 3. Report + verify

Relay the script's stdout: groups / points / dropped(too-near-shore) / partial
groups / bay-km-skipped / start+end coords. Sanity check: groups should span
the requested latitude range with ~28 km gaps; a big `dropped` or `partial`
count usually means a bad mask stretch → offer the `drop_above_lat` /
`manual_east` override and rerun.

If the user later wants a different spacing or offset set for one region only,
prefer making those per-region keys (like `stop`) over editing the module
globals — keeps other regions reproducible.
