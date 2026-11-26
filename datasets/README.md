# Prototype datasets

## Study area

Metro Manila: latitude 14.35–14.79, longitude 120.90–121.15. The area is defined in `backend/area.py`.

## Walking network, places and building footprints (OpenStreetMap)

- Source: `philippines-latest.osm.pbf` from Geofabrik (https://download.geofabrik.de/asia/philippines.html).
- Licence and attribution: OpenStreetMap contributors, Open Database License (ODbL).
- Raw download: `datasets/raw/` (614 MB). It is gitignored and is only needed to rebuild.
- Build: `py -3.13 -m pip install --user osmium`, then `py -3.13 backend/build_tiles.py`. pyosmium is needed only for this build step; the API uses the Python standard library.
- Outputs, committed so the app runs without rebuilding:
  - **`tiles/{col}_{row}.json.gz`**: the walking graph in 0.02° tiles, about 2.2 km each. The API loads these on demand, and the format is described in `backend/tiles.py`.
    - **Ways kept:** walkable highway types (`routing.WALKABLE_HIGHWAYS`), excluding `access=no/private`, `foot=no` and `indoor=yes`.
    - **Indoor edges removed:** edges through enclosed ground-level buildings are dropped (PRD C-01).
  - **`derived/places.db`**: a SQLite FTS5 index of named places, used for search. The same name within about 200 m counts as one place. Written by `backend/build_places.py`, which `build_tiles.py` calls after the tiles; run `py -3.13 backend/build_places.py` on its own to rebuild only this file (it reads the committed tiles).
    - **Address** (an unindexed column, shown under each result so chain branches can be told apart): "Street, City". The street is `addr:housenumber` + `addr:street` when tagged, otherwise the nearest named walkable street within 150 m; places that are streets have no street part. The city is the containing `boundary=administrative` + `admin_level=6` area (41 cities and municipalities touch the study area), with `addr:city` only where no boundary matches.
    - **Coverage (2026-11-26 build, 150,860 places):** tagged street 40,412; nearby street 51,866; no street part 58,582 (56,065 of them are streets, 2,517 other places with no named street within 150 m); city from a boundary 150,860; no address 0.
  - **`derived/unknown-height-cells.bin`**: height-raster cells covered by OSM buildings that the raster reports as 0 m tall. The API treats them as unknown height (PRD D-01).
  - **`derived/build-info.json`**: source date, counts and the building-height report.

## Building heights

- File: `building-heights/2026_HEIGHT_GVSSM.tif`, covering about lat 14.585–14.745 and lon 120.987–121.125, which is most of Quezon City. The rasters for 2016–2030 have the same extent, and only the 2026 one is used.
- Outside the raster, route sections are "shade unknown" and count as direct sun (PRD E-03).
