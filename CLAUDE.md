# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Shades is a phone-first web app that gives shade-aware walking routes for the Katipunan / Ateneo de Manila University area of Quezon City. It is a Python API (`backend/`) plus a React + Vite + Leaflet single-page frontend (`frontend/`).

## Current direction (read before changing anything)

- **`PRD.md` is the source of truth.**
  - Every non-stretch requirement has an implementation. LOG.md's dated entries record what was verified and what still needs people or a phone.
  - F-16 to F-19, D-04 and C-07 (train routing) are stretch goals and are not built.
- **The UI follows `reference/home page.png`**:
  - a full-bleed OSM map
  - a floating white card with "Your Location" (blue, circle icon) and "Destination" (orange-brown, pin icon), joined by a dotted line, with a swap button
  - a pill row with "Leave Now" and the temperature in red
  - a round locate button at the bottom right
  - a white bottom sheet for results
  
  Keep new UI in that style.
- **Temperature display:** the reference mock's "Feels like 34°" is replaced by two labeled readings, the plain air temperature and the heat index. This is a project decision that extends F-10.
  - The heat index is a weather reading for context only. Never call it "feels like" or describe it as comfort, heat stress or risk (C-03).
  - Show "not available" for each missing value on its own (F-12).
- **When PRD.md and LOG.md disagree, PRD.md wins.** Remove or rewrite the conflicting LOG.md text to match the PRD. Everything else in LOG.md is append-only.
- `SKILL.md` is an "apple-design" skill: guidance on fluid, spring-based, interruptible web UI motion. Use it for gesture and sheet interactions.

## Commands

The backend uses only the Python standard library (3.10+). There is no requirements file and nothing to install. Run all commands from the repo root.

```powershell
python backend\app.py                                        # API on http://127.0.0.1:8000 (SHADES_API_PORT, SHADES_DB override)
python -m unittest discover -s backend -p 'test_*.py' -v     # all backend tests
python -m unittest discover -s backend -p 'test_*.py' -k test_four_point_gain_says_walk_now   # single test
python backend\acceptance.py                                 # scripted PRD evidence (uses live weather), prints Markdown
```

On this machine `python` may resolve to the Microsoft Store alias. The interpreter used during development is `C:\msys64\mingw64\bin\python.exe`.

The tests import `app` as a top-level module, so they must run with `backend/` on the path (`-s backend` does this). Importing `app` parses the OSM extract and the GeoTIFF and opens the SQLite store, which takes about 2–3 s. Tests that write ratings or covered marks patch `app.STORE` with a temporary `Store`. Tests that build routes patch `app.fetch_weather` so they don't hit the network.

```powershell
cd frontend; npm install; npm run dev -- --host 127.0.0.1    # http://127.0.0.1:5173 (VITE_API_URL overrides the API)
cd frontend; npm test                                        # vitest (pure helpers in src/lib)
cd frontend; npx vitest run src/lib/geo.test.js              # single test file
cd frontend; npm run build
```

`.claude/launch.json` runs the API on 8010 (with `data/preview.db`, so test ratings stay out of the real store) and Vite on 5180 for previews, because the user often has their own servers on 8000 and 5173. Opening `/?simulate-location` in dev adds `window.__shadesSetLocation(lat, lon, accuracy)` and `window.__shadesDenyLocation()` for testing the location flows. `frontend/dist/` and `frontend/node_modules/` are tracked in git even though `.gitignore` now lists `node_modules/`. Rebuild `dist` rather than editing it.

## Architecture

**Backend** (`backend/`, a stdlib `http.server`, no framework). The module-level singletons are built once at import: `OSM_DATA`, `WALKING_GRAPH`, `HEIGHT_RASTER`, `PLACE_INDEX` and `STORE`. The handler functions `create_*_response(...)` return `(status, body)` and are what the tests call directly, with no HTTP involved.

- `osm.py`: a single parse of `datasets/katipunan-walking-network.osm`. It provides nodes, ways, named nodes and building footprints.
- `shade.py`:
  - A hand-written GeoTIFF reader (tiled, PackBits, float32), with NaN meaning unknown height.
  - `mark_unknown_footprints()` sets the cells of any OSM building whose raster height is all 0 to NaN (D-01).
  - `solar_position()` uses NOAA's general equations in Asia/Manila time.
  - `ExposureModel` belongs to one travel time. It cuts segments into pieces of about 10 m and ray-marches toward the sun every 2 m. The labels are:
    - `shaded`: a known building taller than `1.7 + d·tan(elev)`, or the sun is below the horizon
    - `unknown`: there is no known blocker but some sample has no height
    - `sun`
    - `covered`: applied from user marks
  - Results are memoized per segment.
  - `analyze_route()` merges pieces into sections with reasons and computes the figures: `sun_percent` and `sun_minutes` treat **unknown as sun** (E-03), and covered counts as shaded (S-11).
- `routing.py`:
  - `WalkingGraph` uses **A\*** with a haversine heuristic. Costs must be ≥ the edge length to keep it exact, and a test checks this against Dijkstra.
  - Each edge keeps its OSM `way_id`, and `edge_key()` = `"way:nodeLow-nodeHigh"`. These ids are what ratings and covered marks are stored against.
  - Vehicle `oneway` tags are ignored for pedestrians.
  - Edges through enclosed ground-level OSM buildings are dropped at build time (C-01; `osm.is_enclosed_ground_building`, `FootprintIndex`). Open roofs, raised buildings and `tunnel=building_passage` ways stay walkable.
- `app.py`:
  - **Shortest route:** cost = length.
  - **Shadier route:** cost = shaded + 3 × (sun + unknown), via `exposure_cost`. It is returned only if its sun % is lower.
  - Each route also gets:
    - `comparison` (F-09)
    - `comfort_window`: +0/+15/+30 min, with `recommend()` saying "wait" only if a later time is at least 5 points lower (F-15)
    - `walkability`, computed after the routes are chosen
  - Weather is fetched after routing.
  - `log_message` is silenced so locations are never logged (C-04).
- `weather.py`: Open-Meteo hourly UV, temperature and humidity, plus an NWS heat index. Each reading is `{"status": "available"|"not available"}`. Failures are not cached.
- `places.py`: offline search over the names in the OSM extract, one entry per name.
- `storage.py`: SQLite in `data/shades.db` (gitignored), opening one connection per call because the server is threaded. Streets with fewer than 3 ratings show "not enough ratings". Route walkability is the length-weighted average over rated streets.

**Frontend** (`frontend/src/`):
- `App.jsx` holds all state:
  - trip points
  - leave-now versus a chosen time (sent as an ISO string with the device offset; see `lib/time.js`)
  - the route request
  - the live walk: `watchPosition` plus a 5 s poll, paused on `visibilitychange`
  - the off-route prompt at 30 m
  - street mode (taps go to `/api/streets/nearest` instead of setting points)
  - covered marks
- `components/MapView.jsx` wraps raw Leaflet:
  - Section styles differ by pattern as well as colour (S-04).
  - Tapping a section opens a popup with its reason (I-01).
- `lib/geo.js` projects a position onto the route and computes the remaining figures client-side (F-13).
- `lib/location.js` handles geolocation errors and accuracy (E-04) and contains the dev simulator.

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
