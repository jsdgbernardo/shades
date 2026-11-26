# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Shades is a phone-first web app that gives shade-aware walking routes across Metro Manila (building heights cover Quezon City only). It is a Python API (`backend/`) plus a React + Vite + MapLibre single-page frontend (`frontend/`).

## Current direction (read before changing anything)

- **`PRD.md` is the source of truth.**
  - Every non-stretch requirement has an implementation. LOG.md's dated entries record what was verified and what still needs people or a phone.
  - F-16 to F-19, D-04 and C-07 (train routing) are stretch goals and are not built.
- **The UI follows `reference/home page.png`**:
  - a full-bleed OSM map in its original colours (the user tried greyscale and softened versions and prefers the original); routes get a white casing so they stand out
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

The tests import `app` as a top-level module, so they must run with `backend/` on the path (`-s backend` does this). Importing `app` reads the GeoTIFF and build-info, and opens the places index and the SQLite store, which takes about 2 s. Graph tiles load lazily as routes need them. Tests that write ratings or covered marks patch `app.STORE` with a temporary `Store`. Tests that build routes patch `app.fetch_weather` so they don't hit the network.

The map data is prebuilt and committed (`datasets/tiles/`, `datasets/derived/`). Rebuild it only when the OSM source changes. This needs the Geofabrik Philippines PBF in `datasets/raw/` (gitignored) and pyosmium, a build-only dependency, under Python 3.13:

```powershell
py -3.13 -m pip install osmium; py -3.13 backend\build_tiles.py    # ~3–4 min; see datasets/README.md
```

```powershell
cd frontend; npm install; npm run dev -- --host 127.0.0.1    # http://127.0.0.1:5173; /api is proxied to SHADES_API_PORT (default 8000); VITE_API_URL overrides
cd frontend; npm run phone                                   # build + preview on 127.0.0.1:4173 for the Cloudflare tunnel (see README "Use on your phone")
cd frontend; npm test                                        # vitest (pure helpers in src/lib)
cd frontend; npx vitest run src/lib/geo.test.js              # single test file
cd frontend; npm run build
```

`.claude/launch.json` runs the API on 8010 (with `data/preview.db`, so test ratings stay out of the real store) and Vite on 5180 for previews, because the user often has their own servers on 8000 and 5173. Opening `/?simulate-location` in dev adds `window.__shadesSetLocation(lat, lon, accuracy)` and `window.__shadesDenyLocation()` for testing the location flows. `frontend/dist/` and `frontend/node_modules/` are tracked in git even though `.gitignore` now lists `node_modules/`. Rebuild `dist` rather than editing it.

## Architecture

**Backend** (`backend/`, a stdlib `http.server`, no framework). The module-level singletons are built once at import: `WALKING_GRAPH` (over a `TileStore`), `HEIGHT_RASTER`, `PLACE_INDEX` and `STORE`. The handler functions `create_*_response(...)` return `(status, body)` and are what the tests call directly, with no HTTP involved.

- `area.py`: the study area (a Metro Manila box), the 0.02° tile grid (`tile_of`, shared by build and runtime) and `MAX_TRIP_M` (10 km).
- `build_tiles.py` (build only, pyosmium): streams the PBF and writes:
  - `datasets/tiles/{col}_{row}.json.gz`: walkable nodes, directed edges `[a, b, length, way]` (each in its start node's tile) and way labels
  - `datasets/derived/places.db` (FTS5), `unknown-height-cells.bin` (D-01) and `build-info.json` (counts)
  - `datasets/derived/ways.db` (way → tiles), through `build_ways.py`, which can also rebuild it from the committed tiles alone
  - Indoor edges (C-01) and disconnected fragments under 200 nodes are dropped here.
- `tiles.py`: `TileStore` loads tiles lazily into an LRU cache and answers `neighbors`, `nodes_near` and `edges_near`. `tiles_of_way` uses `ways.db` to load a street's tiles, so saved ratings and marks resolve right after a restart.
- `osm.py`: only `is_enclosed_ground_building` and `FootprintIndex`, used by the build.
- `shade.py`:
  - A hand-written GeoTIFF reader (tiled, PackBits, float32), with NaN meaning unknown height.
  - `mark_unknown_footprints()` (at build time) finds the cells of any OSM building whose raster height is all 0; `mark_unknown_cells()` sets them to NaN at startup (D-01). Outside the Quezon City raster every sample is unknown.
  - `solar_position()` uses NOAA's general equations in Asia/Manila time.
  - `ExposureModel` belongs to one travel time. It cuts segments into pieces of about 10 m and ray-marches toward the sun every 2 m. The labels are:
    - `shaded`: a known building taller than `1.7 + d·tan(elev)`, or the sun is below the horizon
    - `unknown`: there is no known blocker but some sample has no height
    - `sun`
    - `covered`: applied from user marks
  - Results are memoized per segment.
  - `analyze_route()` merges pieces into sections with reasons and computes the figures: `sun_percent` and `sun_minutes` treat **unknown as sun** (E-03), and covered counts as shaded (S-11).
- `routing.py`:
  - `WalkingGraph` uses **A\*** with a haversine heuristic over the tile store, so only tiles along the corridor load. Costs must be ≥ the edge length to keep it exact, and a test checks this against Dijkstra. `max_cost` stops a hopeless search early.
  - Each edge keeps its OSM `way_id`, and `edge_key()` = `"way:nodeLow-nodeHigh"`. These ids are what ratings and covered marks are stored against.
  - Vehicle `oneway` tags are ignored for pedestrians.
  - Edges through enclosed ground-level OSM buildings are dropped at build time (C-01; `osm.is_enclosed_ground_building`, `FootprintIndex`). Open roofs, raised buildings and `tunnel=building_passage` ways stay walkable.
- `app.py`:
  - Trips over 10 km straight-line are refused, and points with no path within 400 m get a message.
  - **Shortest route:** cost = length, search limited to 3 × straight-line + 5 km, up to `MAX_WALK_M` (15 km).
  - **Shadier route:** cost = shaded + 3 × (sun + unknown), via `exposure_cost`, limited to 3 × the shortest route's length (lossless). It is returned only if its sun % is lower.
  - Each route also gets:
    - `comparison` (F-09)
    - `comfort_window`: +0/+15/+30 min, with `recommend()` saying "wait" only if a later time is at least 5 points lower (F-15)
    - `walkability`, computed after the routes are chosen
  - Weather is fetched after routing, for the start rounded to 0.1° (C-04).
  - Points travel only in POST bodies, never in URLs, because hosts log URLs (C-04).
  - `log_message` is silenced so locations are never logged (C-04).
- `weather.py`: Open-Meteo hourly UV, temperature and humidity, plus an NWS heat index. Each reading is `{"status": "available"|"not available"}`. Failures are not cached.
- `places.py`: offline FTS5 search over `places.db` (prefix matches first, then by distance to the other trip point via `near=lat,lon`).
- `storage.py`: `open_store()` picks `TursoStore` (hosted SQLite over https with `urllib`) when `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are set, `NoStore` on Vercel without them, and otherwise `Store`: SQLite in `data/shades.db` (gitignored), one connection per call because the server is threaded. When the store raises `StoreError`, routes still work and saves return 503. Streets with fewer than 3 ratings show "not enough ratings". Route walkability is the length-weighted average over rated streets.

**Frontend** (`frontend/src/`):
- `App.jsx` holds all state:
  - trip points
  - leave-now versus a chosen time (sent as an ISO string with the device offset; see `lib/time.js`)
  - the route request
  - the live walk: `watchPosition` plus a 5 s poll, paused on `visibilitychange`
  - the off-route prompt at 30 m
  - map taps: start and destination are set only by search or GPS. A tap on a route section or a street calls `/api/streets/nearest` and opens `StreetModal` (`components/StreetPanel.jsx`), which shows the section reason, rating and covered toggle. This follows PRD S-02.
  - covered marks: not drawn on their own. They show only as `covered` sections of a generated route, plus the one section open in the street card (so a new mark is visible on save, S-10).
  - routes are computed only on "Find routes" (or an accepted reroute); changing start, destination or time clears results
- `components/MapView.jsx` wraps MapLibre GL with the OpenFreeMap vector style:
  - The map rotates (two-finger twist, right-drag or Ctrl+drag) but never tilts. A compass button appears when it is turned; tapping it returns north-up.
  - Section styles differ by pattern as well as colour (S-04).
  - Taps go to `onTap(latlng, section | null)` (I-01).
- `components/RouteSheet.jsx` is the whole bottom stack: the legend and locate row, then a drag sheet (peek ↔ expanded, physics in `lib/spring.js` per SKILL.md) or an `overlay` card (street details, off-route prompt) that replaces it. Keep the UI compact and free of how-to text; the user wants most of the map visible at all times.
- **Navigation mode** (walk + GPS fix): `lib/nav.js` derives manoeuvres from route geometry (bearing change ≥ 30° over ±12 m, merged within 15 m; street names only when the API edge has `named: true`) and the course-up heading. `App.jsx` swaps the top cards for `NavBanner` and the sheet for `NavBar` (`components/NavPanel.jsx`). While `following` (state in `App.jsx`), `MapView` keeps the user 60% down the screen and turns with MapLibre's native bearing so labels stay upright; zooming stays around the user, and the user's zoom is kept across GPS updates. A drag or twist pauses following (`onUserMovedMap`), and GPS updates then move only the arrow until **Re-center**. Taps stay off while navigating. Arrival: within `ARRIVE_METERS` (30 m) of the route's end, along the route or in a straight line (`hasArrived`). GPS denied or unavailable (not timeout) drops back to the normal sheet.
- Place search never sends a GPS point as `near` (C-04).
- `lib/geo.js` projects a position onto the route and computes the remaining figures client-side (F-13).
- `lib/location.js` handles geolocation errors and accuracy (E-04) and contains the dev simulator.

**Hosting** (Vercel Hobby, README "Use on your phone without a laptop"): `vercel.json` builds the frontend and rewrites `/api/*` to `api/index.py`, whose `handler` subclasses `app.RequestHandler` and restores the client's path. The bundle has only the files in `includeFiles`; add any new runtime data file there. The disk is read-only, Python is 3.13, and instances start cold, so never rely on state from an earlier request.

**Data** (`datasets/`): built from the Geofabrik Philippines extract clipped to Metro Manila (ODbL, see `datasets/README.md`). Building heights cover Quezon City only; elsewhere shade is unknown and counts as sun (accepted). Height rasters exist for 2016–2030, but only 2026 is used.

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
