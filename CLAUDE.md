# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Shades is a phone-first web app that gives shade-aware walking routes for the Katipunan / Ateneo de Manila University area of Quezon City. It is a Python API (`backend/`) plus a React + Vite + Leaflet single-page frontend (`frontend/`).

## Current direction (read before changing anything)

- **`PRD.md` is the source of truth.** The prototype covers only part of it. The prototype must be brought in line with PRD.md. `LOG.md` → "PRD comparison and update plan" lists the gaps by priority (P0 to P3) and a suggested order. Work through it in that order. F-16 to F-19, D-04 and C-07 (train routing) are stretch goals. Do them only after everything else in the PRD is done.
- **The UI must match the look of `reference/`** (`reference/home page.png`). That means a full-bleed map inside a phone frame and a floating white rounded card at the top with "Your Location" (blue, circle icon) and "Destination" (orange/brown, pin icon) joined by a dotted line, plus a swap button. Below that card sits a smaller pill row: "Leave Now" with a clock on the left and the temperature on the right in red. A round re-center/locate button sits at the bottom right. The current `frontend/src/styles.css` uses a different layout (brand mark, search card, route sheet) and needs reworking.
- **Temperature display:** the reference mock's "Feels like 34°" pill is replaced by two labeled readings, the plain air temperature and the heat index (a project decision that extends F-10). Use the reference's styling for both. Present the heat index as a weather reading for context only. Don't call it "feels like" and don't describe it as comfort, heat stress or risk (C-03). It must never affect routes or scores. When either value is missing, show "not available" (F-12).
- **When PRD.md and LOG.md disagree, PRD.md wins.** Remove or rewrite the conflicting LOG.md text to match the PRD. Everything else in LOG.md is append-only.
- `SKILL.md` is an "apple-design" skill: guidance on fluid, spring-based, interruptible web UI motion. Use it for gesture and sheet interactions.

## Commands

The backend uses only the Python standard library (3.10+). There is no requirements file and nothing to install. Run all commands from the repo root.

```powershell
python backend\app.py                                        # API on http://127.0.0.1:8000
python -m unittest discover -s backend -p 'test_*.py' -v     # all backend tests
python -m unittest discover -s backend -p 'test_*.py' -k test_route_request_rejects_points_outside_study_area   # single test
```

On this machine `python` may resolve to the Microsoft Store alias. The interpreter used during development is `C:\msys64\mingw64\bin\python.exe`.

The tests import `app` as a top-level module, so they must run with `backend/` on the path (`-s backend` does this). Importing `app` loads the OSM graph and the GeoTIFF when the module loads, so even unit tests take a few seconds.

```powershell
cd frontend; npm install; npm run dev -- --host 127.0.0.1    # http://127.0.0.1:5173
cd frontend; npm run build                                   # only frontend check; no linter or JS tests are configured
```

`frontend/dist/` is committed build output. Rebuild it rather than editing it by hand.

## Architecture

**Backend** (`backend/`, a stdlib `http.server`, no framework):
- `app.py`: the HTTP handler (`GET /api/health`, `POST /api/routes`), the study-area bounding box (`STUDY_AREA`, lat 14.635–14.650, lon 121.065–121.083), and validation. `create_route_response(payload)` is the pure function that the tests call directly, with no HTTP involved. The walking speed is hard-coded at 80 m/min (`duration_minutes = distance / 80`). The graph and raster are module-level singletons built once at import.
- `routing.py`: `WalkingGraph.from_osm()` parses `datasets/katipunan-walking-network.osm` into an adjacency dict, filtered by `WALKABLE_HIGHWAYS`, and runs Dijkstra from the nearest nodes. The **second ("alternative") route** comes from re-running Dijkstra with the first route's edges penalized ×2.8. It is not a shade-optimized search yet. Routes are labeled "Walking route 1/2", not "shortest" or "shadier".
- `shade.py`: a hand-written GeoTIFF reader (tiled, PackBits, float32) for `datasets/building-heights/2026_HEIGHT_GVSSM.tif` (no GDAL or rasterio). It also does a NOAA-style `solar_position()` in Asia/Manila time. `analyze_route()` takes each segment midpoint and ray-marches toward the sun every 2 m out to 200 m. A segment counts as shaded if any building is taller than `1.7 + d·tan(elevation)`. The shade level (1–4) only drives the colour. Percentages are binary and weighted by distance. Known PRD gaps: nodata and out-of-raster cells currently become **0 height** rather than "shade unknown" (E-03 and D-01 require flagging), and the sun below the horizon counts as shaded.
- `uv.py`: Open-Meteo hourly UV, cached in memory per (rounded lat/lon, hour), returning `{"status": "available" | "unavailable", ...}`. It must never block or alter routing (F-07, F-12). Temperature, heat index and humidity (F-10, F-11) are not fetched yet. Tests mock it with `@patch("app.fetch_uv_context")`.

**Frontend** (`frontend/src/`): everything lives in `main.jsx` (`App`, `MapView` wrapping raw Leaflet, `RouteCard`, `ContextChip`) and `styles.css`. `API_URL` is hard-coded to `http://127.0.0.1:8000`. Points are chosen by tapping the map (first tap sets the start, second sets the destination). On desktop the app renders inside a CSS phone frame. On real phones the frame is removed. The light and dark theme applies to the whole app.

**Data** (`datasets/`): the OSM extract is the bbox `121.065,14.635,121.083,14.650` (ODbL, see `datasets/README.md`). Height rasters exist for 2016–2030, but only 2026 is used.

## Project rules

- After each major implementation step, run the tests, including the existing ones, to make sure no implemented feature has broken.
- Add or modify tests when the task needs them or when new behaviour needs verifying. Never weaken or remove existing tests just to make an implementation pass.
- Never claim a test or verification passed unless you actually ran it. Report uncertainty when the evidence is insufficient.
- `LOG.md` is the build log. Add new entries and preserve existing content, except for text that conflicts with PRD.md (see above).
- Do not rewrite Git history or force-push.

## PRD constraints that commonly affect code

- UV, temperature, heat index, humidity and walkability are **context only**. They must never change routes or scores (F-07, F-10, F-11, S-09, C-02).
- The sun-exposure score = sun-exposed length ÷ total length (F-05). Minutes in sun = sun length ÷ walking speed (F-08). "Shade unknown" counts as sun (E-03).
- Don't use wording about thermal comfort, heat stress or health risk (C-03). State the clear-sky / no-trees assumption in the UI (C-05). Location is never stored or logged (C-04).
- It must be usable at 360 px wide (O-02). Sun and shade sections must be distinguishable without colour (S-04).
