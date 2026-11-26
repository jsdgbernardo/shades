## Current Implementation Status

### Commit checkpoint: 2026-10-15

The prototype currently provides an end-to-end Katipunan/ADMU route-planning flow. A user can click two points on a full-screen map, choose a travel time, compare two walking routes, select a route on the map or in the route drawer, and view estimated shade, sun exposure, distance, duration, and UV context.

### Study area decision

The prototype is constrained to a small Katipunan and Ateneo de Manila University study area:

- South: `14.635`
- North: `14.650`
- West: `121.065`
- East: `121.083`

This boundary is intentionally small enough for a fast prototype and includes the ADMU campus and nearby Katipunan routes.

### Implemented

- Added `backend/app.py` and `backend/routing.py` with a dependency-free Python API and local walking graph.
- Added `GET /api/health` and `POST /api/routes` endpoints.
- Added coordinate and study-area validation.
- Added a bounded OpenStreetMap walking-network extract in `datasets/katipunan-walking-network.osm` with source attribution in `datasets/README.md`.
- Added nearest-node routing with two route alternatives, distance, and estimated duration.
- Added `backend/shade.py` to parse the existing 2026 building-height GeoTIFF, calculate solar position, and classify route segments.
- Added computed shaded and sun-exposed percentages and colored route segments in the frontend.
- Added five-level teal shade colors, warm-gold sun colors, and matching map legend colors.
- Added clickable map point selection with hidden coordinate values.
- Added a full-screen navigation-style map with route overlays, route selection, floating controls, reset selection, and dark/light application themes.
- Added live Open-Meteo UV context with in-memory caching and an explicit disclaimer that UV is not a shade measurement.

### Shade estimation method

The current prototype estimates shade as follows:

1. The selected walking route is divided into consecutive route segments. Each segment is represented by its midpoint for shade analysis.
2. The backend calculates the sun's elevation and azimuth from the selected local date/time and the route's geographic position.
3. The 2026 building-height GeoTIFF is loaded into memory. Its WGS84 coordinates are converted into raster rows and columns, and non-finite or extreme nodata values are currently treated as zero height. This does not meet PRD D-01/E-03: cells without height data must be flagged as "shade unknown" and counted as direct sun, never as zero height.
4. From each segment midpoint, the algorithm samples the direction toward the sun every 2 meters, from 2 meters out to 200 meters.
5. At each sample, the building height is compared with the line-of-sight clearance:

	`required height = pedestrian eye height + distance * tan(sun elevation)`

	The prototype uses `1.7` meters as pedestrian eye height. If a sampled building is taller than the required height, the segment is considered shaded.
6. The obstruction-to-clearance ratio produces a shade level from 1 to 4 for the teal route colors. If no obstruction is detected, the segment is sun-exposed. If the sun is below the horizon, the segment is treated as shaded.

The route shade percentage is currently distance-weighted but binary at the segment level:

`shade percentage = shaded segment distance / total route distance * 100`

Therefore, any detected obstruction makes the whole tested segment count as shaded. The teal intensity shows obstruction strength visually, but does not yet weight the percentage itself.

### Verification

- Backend: 3 unit tests passed using the MSYS2 Python 3.10.6 interpreter.
- Frontend: `npm run build` passed with Vite 8.3.4.
- Backend: live requests return two walking routes and time-dependent shade estimates.
- Frontend: browser verification displays both routes, clickable route details, teal shade levels, sun segments, and the UV context card.
- Live API verification returned `UV 2.4`, category `Low`, from Open-Meteo.
- External data downloaded: only the bounded OpenStreetMap extract. UV data is requested at runtime and is not stored locally.

### Current TODO

1. Validate shade estimates against several known Katipunan/ADMU streets and selected times.
2. Confirm the building-height GeoTIFF units, source metadata, nodata meaning, and accuracy.
3. Add algorithm tests using controlled building geometries and known sun directions.
4. Measure end-to-end request time and confirm the PRD P-01 target (at least 18 of 20 requests in 10 seconds or less).
5. Add tests for unavailable UV responses, unavailable route data, invalid times, and no-route cases.
6. Add a usability check with a non-technical user and record the result.
7. Decide whether shade percentage should become intensity-weighted rather than binary per segment.

### PRD traceability checklist

Status legend: `[x]` implemented and demonstrated, `[~]` partially implemented or not fully verified, `[ ]` not implemented.

#### Functional requirements

- `[x]` **F-01**: Provides route options with shade and sun-exposure information through the API and route drawer. Evidence: live route request and browser route cards.
- `[x]` **F-02**: Recalculates solar position and shade when travel time changes. Evidence: live noon versus late-afternoon requests produced different shade percentages.
- `[x]` **F-03**: Represents mixed route segments with separate sun and shade colors. Evidence: route polylines are rendered segment by segment.
- `[x]` **F-04**: Provides two route alternatives when the local network permits. Evidence: browser displays two route options and both are drawn on the map.
- `[~]` **F-05**: The PRD score is the percentage of route length in direct sun. The backend computes `sun_exposed_percent`, but the frontend emphasizes shaded percentage; make the sun-exposure percentage the displayed score on every route.
- `[x]` **F-06**: Displays route distance, estimated duration, and exposure percentages together. Evidence: route option cards and selected-route details.
- `[x]` **F-07**: Requests UV Index at runtime and classifies it as Low through Extreme while keeping it separate from shade. Evidence: live Open-Meteo response and UV context card. A high/very-high test fixture is still needed.

#### Software requirements

- `[x]` **S-01**: Full-screen interactive Leaflet map centered on the Katipunan/ADMU study area.
- `[x]` **S-02**: Start and destination are set by place search (the start can also be the current location). Tapping the map does not set either point; it opens the details of the tapped street or route section.
- `[x]` **S-03**: Selected walking routes are drawn on the map.
- `[~]` **S-04**: Sun-exposed segments use gold and shaded segments use teal levels with a legend. The PRD also requires a non-color distinction (pattern), which is not implemented.
- `[x]` **S-05**: Travel time input defaults to the current local time and is sent to the backend.
- `[x]` **S-06**: Multiple routes can be displayed, selected, minimized, and compared.
- `[~]` **S-07**: The interface is designed for non-technical users, but no formal usability test has been completed.

#### Performance and operating conditions

- `[~]` **P-01**: The local route and raster processing completes in development tests, but no measured end-to-end benchmark has been recorded against the 10-second target.
- `[x]` **O-01**: The application validates and processes points within the bounded ADMU/Katipunan study area.

#### Constraints

- `[x]` **C-01**: Uses a walking highway graph and does not intentionally route through building interiors. Indoor-specific validation remains a recommended test.
- `[ ]` **C-02**: Walkability must come only from user ratings (S-08, S-09), be labeled as such, and never affect routing. User ratings are not implemented yet.
- `[x]` **C-03**: Labels UV as contextual and does not claim to measure thermal comfort, heat stress, or health risk.
- `[~]` **C-04**: The prototype does not use device location yet, so nothing is stored. When location (S-12, F-13) is added, it must be used only for the start point, position display and off-route detection, and never stored, logged or shared.

### Known limitations

- The walking network covers only the downloaded ADMU/Katipunan bounding box, not all of Quezon City.
- Route alternatives are produced by penalizing the first route; they are useful alternatives but are not guaranteed to be globally optimal or meaningfully different in every case.
- The building-height raster is approximately 10 m resolution. It may miss narrow structures, sidewalk-side differences, trees, awnings, and temporary shade.
- The GeoTIFF source units and detailed quality metadata have not yet been independently confirmed. Extreme floating-point nodata values are masked by the parser.
- Shade percentage is currently distance-weighted and binary per route segment: any detected obstruction marks that segment as shaded. Teal intensity communicates obstruction strength but does not yet weight the percentage.
- The shade model uses a simplified ray check from segment midpoints and does not model terrain, trees, cloud cover, covered walkways, or human movement.
- UV is contextual and retrieved from Open-Meteo at runtime. It is not used to calculate route shade, and the route request still works if the service is unavailable.
- OpenStreetMap and map-tile services require network access and may rate-limit requests. The application does not continuously track user location.

## PRD comparison and update plan

### Review date

2026-11-14

### Prototype baseline reviewed

The working prototype currently supports:

- A React/Vite full-screen Leaflet map for the bounded Katipunan/ADMU area.
- Start and destination selection by tapping the map.
- An editable travel date/time, defaulted to the browser's current local time.
- A Python API that validates the study area, returns one or two local walking routes, and reports distance and estimated walking duration.
- Segment-level sun/shade classification using solar position and the local building-height GeoTIFF.
- Shaded and sun-exposed route percentages, a backend exposure rating, route selection, a legend, dark/light themes, and UV context from Open-Meteo.

Evidence reviewed: `backend/app.py`, `backend/routing.py`, `backend/shade.py`, `backend/uv.py`, `backend/test_app.py`, `frontend/src/main.jsx`, `frontend/src/styles.css`, and `README.md`.

### Requirements already represented in the prototype

- **F-01 to F-04:** Basic walking routes, time-dependent shade analysis, segment geometry, and route alternatives are implemented for the local test area. They still need the PRD's larger acceptance runs (10 pairs/trips and expected-direction checks).
- **F-05 to F-07:** The backend computes direct-sun percentage, distance, duration, and UV category; the frontend displays sun/shade percentages and UV context. F-05's score is currently represented mainly through shaded percentage and F-07 needs a high/very-high fixture and invariance test.
- **S-01, S-03, S-05, and S-06:** Map interaction, route drawing, editable travel time, and on-screen route comparison are present.
- **O-01, C-01 and C-03:** The bounded study area, walking-only scope, and unsupported-claim boundaries are documented. C-02 and C-04 depend on features not yet built (user ratings, device location).

### Required updates, in priority order

#### P0: Complete the core route result before adding stretch features

1. **Make the route score match the PRD wording.**
   - Keep `sun_exposed_percent` as the canonical F-05 score and make it prominent on every route card.
   - Continue exposing shade percentage as a separate supporting metric.
   - Display the backend `rating` explicitly in the route drawer.
2. **Add sun-exposure minutes (F-08).**
   - Return sun-exposed distance or a directly derived `sun_minutes` value from the backend using the existing 80 m/min walking speed.
   - Display the value for every route and the selected route.
3. **Add shortest-vs-shadier comparison (F-09).**
   - Define the baseline as the shortest returned walking route.
   - When a second route exists, show percentage-point difference, minutes-in-sun difference, and extra distance; handle unavailable comparisons without misleading zeroes.
4. **Expand weather context to temperature, heat index and humidity (F-10, F-11).**
   - Extend the Open-Meteo request and cache to retrieve values for the selected local hour.
   - Show the plain air temperature and the heat index as two separate labeled readings (project decision 2026-11-16). The heat index is a weather reading for context only, not a comfort or heat-stress assessment (C-03).
   - Keep all weather values informational and independent from route generation and exposure scoring.
5. **Make context-data failure explicit but non-blocking (F-12).**
   - Return `not available` state for UV, temperature, heat index, or humidity independently.
   - Add tests proving route requests still succeed when each context value is unavailable.
6. **Add API and algorithm verification for the new core metrics.**
   - Test sun minutes and route comparisons from controlled route data.
   - Add controlled shadow tests for known building heights, sun elevations, and directions.
   - Add invalid-time, no-route, unavailable-UV, and response-schema tests.

#### P1: Complete the non-stretch user experience

7. **Support start/destination entry by search (S-02).**
   - Add a phone-friendly place search for both points, using a bounded local search list; map taps do not set points.
8. **Improve route visual accessibility (S-04).**
   - Keep the existing color legend, but add a non-color distinction (pattern, dash, or explicit segment labeling) so sun and shade remain distinguishable in grayscale.
9. **Add current-position and remaining-route behavior (F-13, F-14).**
   - Add opt-in geolocation with a position marker and updates no slower than the proposed five-second interval.
   - Project the position onto the selected route and compute remaining sun percentage, sun minutes, and distance.
   - Detect the proposed 30 m off-route threshold, ask before rerouting, and preserve the route when declined.
   - Update the scope/privacy copy and tests because the current prototype explicitly does not track location.
10. **Add the comfort window (F-15).**
    - Calculate the selected route at now, +15 minutes, and +30 minutes.
    - Recommend waiting only when a later score is at least 5 percentage points lower; otherwise recommend walking now.
    - Use only sun exposure for this recommendation and add 4-point/6-point boundary tests.
11. **Run the PRD usability and performance checks.**
    - Benchmark representative route requests and record evidence against the P-01 10-second target.
    - Test 10 route pairs/trips, three time-of-day cases, mixed segments, and three non-technical users.
    - Record actual results, not just planned checks.

#### P2: Implement the walkability and covered-section requirements

12. **Add street walkability ratings (S-08, S-09).**
    - Persist 1-5 ratings by street segment.
    - Show street averages only after the proposed minimum of three ratings.
    - Calculate route walkability as a length-weighted average and show rated-route share.
    - Keep walkability informational and independent from route choice and shade scores.
13. **Add user-maintained covered sections (S-10, S-11).**
    - Persist, correct, and remove covered marks against route/street sections.
    - Treat active covered sections as shaded for sun percentage and sun minutes.
    - Render covered sections with a distinct style and restore calculated shade when removed.
    - Decide on the persistence store and conflict behavior before implementation; the current prototype has no persistence layer or accounts.

#### P3: Optional stretch scope

14. **Evaluate MRT/LRT walk-train-walk routing (F-16 to F-19).**
    - Acquire and document station/line data and shortest rail paths.
    - Generate qualifying options only when both walks are within 1 km.
    - Estimate ride and transfer time using documented fixed assumptions.
    - Shift the second walk's solar time, label it approximate, and show total travel time.
    - Exclude the rail portion from walking exposure metrics and render it distinctly.
    - If no qualifying option exists, omit the train option without an error.

### Dependencies and decisions before implementation

- Confirm the weather provider fields and hourly semantics for temperature, humidity, and UV.
- Confirm building-height GeoTIFF units, source metadata, nodata handling, and accuracy before treating shadow results as validated.
- Choose a persistence mechanism for ratings and covered sections; this is a new architectural requirement.
- Decide the place-entry/search approach and whether geolocation is opt-in only.
- Decide whether the existing binary per-segment shade percentage remains the accepted approximation or becomes intensity-weighted.
- Treat F-16 to F-19 as stretch work after the core walking experience passes its acceptance tests.

### Suggested implementation sequence

1. Backend metrics, weather context, explicit unavailable states, and focused tests.
2. Frontend route cards/details for sun score, rating, sun minutes, and route deltas.
3. Core acceptance/performance/usability verification and documentation of measured evidence.
4. Point entry, accessible segment styling, comfort window, and opt-in live location.
5. Persistence-backed walkability and covered sections.
6. Train routing only if the stretch scope is approved and data feasibility is confirmed.

## Implementation Plan

### Objective

Build a prototype shade-optimized walking route planner for a limited test area in Quezon City. The prototype will accept a start point, destination, and travel time; generate walking route options; estimate direct-sun and shade segments using sun position and available building data; and present route comparisons in an interactive map.

### Scope and guardrails

- Focus on outdoor direct sunlight exposure only.
- Do not provide indoor routing, walkability scores from anything other than user ratings, thermal-comfort estimates, heat-stress predictions, health-risk claims, or background location tracking. Location is used only while the app is open and is never stored.
- Limit processing and testing to a defined Quezon City study area.
- Use the current time as the default travel time.
- Treat UV Index as contextual information, not as a direct shade measurement.
- Return results for a valid route request in 10 seconds or less (PRD P-01).

### Proposed architecture

1. **Frontend: React and Vite**
	- Provide start and destination inputs or map selection.
	- Provide a travel date/time control defaulting to the current time.
	- Display the interactive map, route alternatives, shaded segments, sun-exposed segments, distance, duration, exposure percentage, and an understandable exposure rating.
	- Show the selected area and clear loading, validation, no-route, and data-limitation states.

2. **Backend: Python API**
	- Validate coordinates, travel time, and study-area boundaries.
	- Obtain or generate at least two walking route alternatives while avoiding building polygons and other non-walkable areas represented by the selected dataset.
	- Calculate the sun position for the requested location and time.
	- Sample route segments and classify each segment as shaded or sun-exposed using building geometry and height data where available.
	- Calculate route distance, estimated walking duration, shaded distance, exposed distance, exposure percentage, and score/rating.
	- Return route geometry and segment classifications in a frontend-friendly JSON response.

3. **Data layer**
	- Select and document a small Quezon City study area and coordinate reference systems.
	- Acquire and inspect OpenStreetMap walking-network data, building footprints, building heights, and available PAGASA or other relevant UV/weather data.
	- Record source, date, coverage, resolution, missing values, licensing/attribution requirements, and preprocessing steps.
	- Make building-height availability an early decision gate. Where heights are unavailable, label the affected sections "shade unknown" and count them as direct sun (PRD E-03); never substitute a default or zero height.

### Implementation sequence

#### Phase 1: Requirements, data, and feasibility

- Convert the PRD requirements into a traceability checklist covering every requirement ID in the current `PRD.md`.
- Define the study-area boundary and representative start/destination test cases.
- Verify that the selected datasets cover the area and can support routing, building obstruction, and time-dependent sun calculations.
- Create a small reproducible preprocessing workflow for the road network and building data.
- Decide and document the building-height fallback before implementing the exposure algorithm.

#### Phase 2: Backend routing and exposure engine

- Set up the Python project, API endpoint, configuration, dependency management, and data-loading path.
- Implement input validation and study-area restrictions.
- Implement walking-route generation with at least two alternatives when the network permits it.
- Implement sun-position calculation for the requested local date and time.
- Implement route sampling and building-shadow classification for each segment.
- Implement route metrics and a stable exposure score/rating with explicit assumptions.
- Add structured error responses and a request-time measurement for the 10-second target.

#### Phase 3: Frontend and integration

- Set up the React/Vite application and map library.
- Build the route request form with current-time default, coordinate selection, and validation feedback.
- Connect the form to the backend and render route alternatives on the map.
- Use distinct, accessible visual styles for shaded and sun-exposed segments.
- Add route comparison details for exposure, distance, and duration, plus UV context when data is available.
- Add loading, error, unavailable-data, and no-route states without implying unsupported health or comfort conclusions.

#### Phase 4: Verification and prototype refinement

- Test the same origin and destination at different times and confirm that sun/shade classifications can change.
- Confirm that routes show mixed shaded and exposed segments where the data supports them.
- Confirm that at least two alternatives can be displayed and compared for suitable test cases.
- Test default current time, invalid inputs, points outside the study area, unavailable routes, and missing UV/building-height data.
- Benchmark representative requests and keep them at 10 seconds or less.
- Perform visual and usability checks for map readability and non-technical interpretation.
- Document known accuracy limitations, dataset gaps, assumptions, and unsupported claims.

### Test and acceptance checklist

- Functional tests cover route generation, time-dependent exposure, segment classification, route comparison, route metrics, and UV context.
- API tests verify validation, response schema, error handling, and study-area restrictions.
- Algorithm tests use controlled geometries and known sun directions to verify shade classification.
- Frontend tests verify form submission, current-time default, map rendering, route selection, legend/labels, and error states.
- Integration tests verify a complete request from the React interface through the Python API.
- Performance tests measure end-to-end request time for representative routes.
- Existing tests are rerun after each major implementation step; tests are added where needed and are not weakened to make the implementation pass.

### Completion criteria

The prototype is complete when a user can select valid start and destination points and a travel time within the Quezon City study area, receive at least one walking route with sunlight/shade information, compare available alternatives, see distance and duration, and understand the result without technical knowledge. The final documentation must state the data sources, assumptions, building-height method or fallback, test evidence, performance result, and all known limitations.

## 2026-11-16: Phase 1, core route engine aligned with PRD

### Changes

- Added `backend/osm.py`: one parse of the OSM extract, shared by routing, shade and (later) place search.
- `backend/shade.py`:
  - Nodata raster cells are now unknown (NaN), not zero.
  - OSM building footprints whose raster cells are all 0 m are marked as buildings without height (D-01). In the study raster, 529 of 5,334 OSM footprints have no height and 4,805 have one.
  - Routes are cut into pieces of about 10 m and labeled `shaded`, `sun`, `unknown` or `covered`. Matching pieces merge into sections, and each section has a reason (F-03, I-01, E-03).
  - The figures are computed as follows:
    - `sun_percent` = (sun + unknown) length ÷ total length (F-05).
    - `sun_minutes` = (sun + unknown) length ÷ 80 m/min (F-08).
    - `unknown_percent` is reported with each route.
  - The old Low/Moderate/High rating was removed.
- `backend/routing.py`:
  - Routing now uses A* with a straight-line heuristic.
  - The shadier route uses the cost shaded m + 3 × (sun + unknown) m (F-04). It is returned only if its sun % is lower than the shortest route's. Otherwise a "no shadier alternative" note is returned.
  - Each edge keeps its OSM way id and an edge key, for ratings and covered marks.
  - Vehicle `oneway` tags no longer restrict pedestrians; only `oneway:foot` does.
- `backend/weather.py` replaces `uv.py`:
  - It returns UV, temperature, humidity and the NWS heat index, each with its own `available` / `not available` state (F-07, F-10, F-11, F-12).
  - Failed fetches are not cached.
- `backend/app.py`:
  - Routes are labeled Shortest and Shadier, and the response includes:
    - the comparison (F-09)
    - the comfort window at +0/+15/+30 min, with "wait" only if a later time is at least 5 points lower (F-15)
    - the assumptions (C-05)
    - the building-height report
  - The outside-area and no-route error messages now tell the user what to do (E-01, E-02).
  - Request logging is disabled (C-04).

### Verification

- `python -m unittest discover -s backend -p 'test_*.py'` → 42 tests, OK (Python 3.10.6). New files: `test_shade.py`, `test_solar.py`, `test_routing.py`, `test_comfort.py` and `test_weather.py`. `test_app.py` was updated to the new response schema.
- D-02: `solar_position` matches an independent implementation of the NOAA spreadsheet algorithm within 1° at 09:00, 12:00 and 15:00 on 4 dates. This is not compared against the NOAA website directly.
- A* gives the same path cost as Dijkstra on 10 sampled pairs, for both the distance cost and the shade cost.
- Smoke run with ADMU (14.6407, 121.0748) → (14.6378, 121.0776) on 2026-10-15:

  | Time  | Shortest sun % | Shadier sun % | Extra distance | Request time |
  | ----- | -------------- | ------------- | -------------- | ------------ |
  | 09:00 | 86.3           | 72.1          | 13.7 m         | 0.12 s or less |
  | 12:00 | 98.0           | 84.4          | 13.7 m         | 0.12 s or less |
  | 15:00 | 79.1           | 64.0          | 39.5 m         | 0.12 s or less |

  Request time excludes the weather fetch. The app takes about 2.3 s to start.

## 2026-11-16: Phases 2–4, reference UI, search and live walk, ratings and covered marks

### Changes

- **Frontend rebuilt to match `reference/home page.png`.** `main.jsx` was split into `App.jsx`, `components/` and `lib/`.
  - **Top:** a white location card ("Your Location" in blue, "Destination" in orange-brown, a dotted connector and a swap button) and a "Leave Now" pill. The pill shows the temperature and heat index in red, or "not available". The dark theme was removed.
  - **Results:** a collapsible bottom sheet showing:
    - side-by-side Shortest and Shadier cards: sun %, minutes in sun, distance, walk time, unknown % and walkability (S-06)
    - the comparison (F-09)
    - the E-03 note
    - the comfort window (F-15)
    - UV and humidity, labeled as context
    - the assumptions (C-05)
  - **Map:** each label is drawn with a different pattern (sun solid, shaded dotted, unknown dashed with "?" markers, covered double line), with a legend (S-04). Tapping a section shows its reason (I-01).
  - **Default time fixed:** it now uses local time and is sent with the device's UTC offset. Before, the default was UTC read as Manila time, which put it 8 h off.
- **Search (S-02):** `GET /api/places` searches 784 named places from the OSM extract, inside the study area only.
- **Weather (F-10):** `GET /api/weather` provides the header readings before any route is requested.
- **Location (S-12, E-04):** the current location becomes the start when permission is granted, accuracy is ≤ 50 m and the user is inside the area. Otherwise a message is shown and the start is set manually.
- **Live walk (F-13, F-14, C-06):**
  - Uses `watchPosition` plus a 5 s poll.
  - Remaining figures are computed client-side from the sections ahead.
  - Leaving the route by more than 30 m brings up a reroute prompt, and the route changes only if the user accepts.
  - Tracking pauses while the page is hidden.
- **Offline:** a "No connection" banner appears on `offline` events or failed fetches (O-03).
- **SQLite storage** in `data/shades.db`:
  - Street ratings (1–5) and covered marks are stored per street section, with the endpoints `/api/streets/nearest`, `/api/streets/{way}/ratings` and `/api/covered` (S-08, S-10, D-03).
  - Streets with fewer than 3 ratings show "not enough ratings".
  - Route walkability is a length-weighted average labeled "based on user ratings". It is computed after the routes are chosen (S-09, C-02).
  - Covered sections count as shaded in the figures and in the shadier-route cost (S-11).
- **UI:** "Rate a street or mark a covered walkway" mode in the sheet.
- **Repo setup:**
  - Added `.gitignore` for `__pycache__/`, `node_modules/` and `data/*.db`. Files already tracked stay tracked.
  - Added `.claude/launch.json`, with preview ports 8010 and 5180.
  - Added `SHADES_API_PORT` and `SHADES_DB` overrides.
- Added `backend/acceptance.py`, which produces the scripted PRD evidence.

### Verification

- **Backend tests:** `python -m unittest discover -s backend -p 'test_*.py'` → 58 tests, OK. New: `test_places.py` and `test_storage.py`. After this run, one covered-mark assertion was made unconditional, and `test_storage` was rerun on its own (10 tests, OK).
- **Frontend tests (before the Phase 4 UI):** `npx vitest run` → 9 tests, OK (`geo.test.js` and `time.test.js`), and `npm run build` OK.
- **Browser preview at 360×740, with simulated location:**
  - The start was set from the simulated location, and a search for "Rizal Library" selected the destination.
  - Two route cards appeared (Shortest 53% / Shadier 48% at 3:28 PM), with the comparison and the comfort window.
  - Tapping a section showed its reason.
  - Live walk: at the start the remaining figures equal the full route (548 m, 48%, 3 min). There is no prompt 10 m off the route.
  - The off-route prompt appeared about 35 m from the route. "Keep this route" kept it. "Recalculate" rerouted from the position (615 m / 636 m).
  - The offline banner showed and then hid.
  - In street mode, tapping the map selected a 22 m footway section, which showed "Not enough ratings yet (0 of 3 needed)".
- **Not yet run after the Phase 4 frontend changes:** the full backend suite, vitest, `npm run build`, `backend/acceptance.py`, and the browser check of submitting ratings and toggling a covered mark. During this session the command safety check kept failing, so these commands could not run.
- **Pending manual checks** (people, a phone or a site visit): S-07 usability with 3 users, A-01 field check of 30 points, F-13/F-14/C-06 on a real phone, O-02 on a real phone, O-03 with the network actually off, and P-01 over a mobile connection.

## 2026-11-16: Verification after Phase 4, and a C-01 fix

### C-01 fix

The first acceptance run found 12 of 30 requests with route pieces inside OSM building footprints, 359 m in total. They came from three kinds of footprint:
- open roofs (`building=roof`)
- raised structures (`layer=1`)
- some real ground-level buildings, such as a 3-storey retail building and houses

`WalkingGraph.from_osm` now leaves out walking edges whose 25/50/75% points fall inside an enclosed ground-level building. That excludes 10 edges. These are still walkable:
- open roofs, canopies and carports
- buildings with `layer >= 1` or a minimum level above ground
- ways tagged `tunnel=building_passage`

Ways tagged `indoor=yes` are excluded entirely. Two new tests in `test_routing.py` cover the C-01 rule.

### Verification (all run in this session)

- **Backend tests:** `python -m unittest discover -s backend -p 'test_*.py'` → 60 tests, OK.
- **Frontend:** `npm test` (vitest) → 9 tests, OK. `npm run build` → OK.
- **Acceptance:** `python backend/acceptance.py` after the C-01 fix. It used 10 seeded pairs 300–1,500 m apart at 09:00, 12:00 and 15:00, with live Open-Meteo weather. Changing the graph changed the sampled pairs.

  | Requirement | Result |
  | --- | --- |
  | P-01 | 30 of 30 requests in 10 s or less (median 2.04 s, max 2.42 s). Measured in-process, without HTTP or phone network time; most of the time is the weather fetch. |
  | F-01 | 30 of 30 returned routes with sun figures. |
  | F-02 | 9 of 10 trips differ across the three times. |
  | F-03 | 27 of 30 have both shaded and sunny sections. |
  | F-04 | 14 of 30 returned a shadier alternative. The rest got the "no shadier alternative" note: no path with a lower sun % was found under the 3× sun weighting. |
  | C-01 | 0 of 30 pass through an enclosed ground-level building. |
  | D-01 | 4,805 of 5,334 OSM footprints have height data, and 529 are flagged unknown. |

- **Browser check at 360×740 against a separate preview database (`data/preview.db`):**
  - Street mode: tapping the map selected a 22 m footway section showing "Not enough ratings yet (0 of 3 needed)".
  - Rating it 4, 5 and 3 changed it to "4.0 / 5 from 3 ratings".
  - "Mark this section as covered" saved one covered section, which was drawn in purple on the map.
  - Removing the mark left 0 covered sections.
  - All API requests on a clean page load returned 200.

### Still open

- **F-04:** fewer than half of the sampled trips get a shadier alternative. Raising the sun weight or adding a distinct non-shadier alternative would change the routing design, so it is left as a decision.
- **Pending manual checks:** S-07 usability with 3 users, A-01 field check of 30 points, F-13/F-14/C-06 and O-02 on a real phone, O-03 with the network actually off, and P-01 over a mobile connection.

## 2026-11-16: Street details open from a map tap; tap-to-pin removed

### Changes

- **Street details on tap.** Tapping a route section, or any street on the map, opens a bottom modal (`StreetModal` in `frontend/src/components/StreetPanel.jsx`) that shows:
  - for a route section: its label and reason (I-01), which replaces the old Leaflet popup
  - the street's walkability from user ratings, with 1–5 rating buttons (S-08, S-09)
  - a toggle to mark the highlighted street section as covered, or remove the mark (S-10)
  
  The modal closes with the Close button, a tap on the backdrop, or Escape.
- **Old street mode removed.** The separate "Rate a street or mark a covered walkway" mode and its button are gone.
- **No more tap-to-pin.** Tapping the map no longer sets the start or destination. They come from search or device location only. All wording that mentioned tapping the map was updated.
- **PRD S-02 updated.** S-02 now says points are set by search (or the current location for the start), and that map taps open street or section details instead of setting points.

### Verification

- **Browser at 1366×768 with simulated location:**
  - A map tap away from any route opened the modal for a 72 m footway and set no destination.
  - Escape closed the modal.
  - After searching "Rizal Library", tapping a route section opened the modal with "Shaded: Shaded by buildings up to about 12 m tall on the W side, toward the sun. 146 m route section", the walkability, and the covered toggle. The tapped stretch was highlighted on the map.
  - Marking it covered gave 1 covered section, and removing the mark gave 0. A backdrop tap closed the modal.
  - No console errors from the app's components.
- **Frontend:** `npx vitest run` → 9 tests, OK. `npm run build` → OK.

## 2026-11-16: Compact UI following SKILL.md

### Changes

- **Smaller controls everywhere.**

  | Element | Before | After |
  | --- | --- | --- |
  | Location card rows | 44 px | 36 px |
  | Time pill | 42 px | 34 px |
  | Locate button | 60 px | 44 px |
  | Rating and covered buttons | 42 px | 32 px |
  
  The legend is now a single line that can wrap.
- **Drag sheet for results** (`RouteSheet.jsx`, `lib/spring.js`), built with the SKILL.md gesture rules:
  - The sheet starts as a small peek. It shows the route cards, sun %, minutes in sun, distance and walk time. The shadier card also shows its difference from the shortest route (F-09) and the unknown share (E-03). Below the cards is a one-line best-time hint and a Start button.
  - Drag or tap the handle to reveal the comfort window, UV and humidity, and the assumptions (C-05).
  - The drag tracks the finger 1:1 after an 8 px threshold and rubber-bands past either end. On release it projects momentum (d = 0.998) to pick the nearest snap point.
  - It then settles on an interruptible spring: response 0.3, damping 0.8 after a flick and 1.0 otherwise.
  - With reduced motion, the sheet jumps instead of animating.
- **Non-blocking cards.** The street details and the off-route prompt are compact cards (about 128 px) that replace the sheet while open. There is no dimming scrim, so the map stays visible and can still be tapped.
- **Translucent surfaces.** Cards use `backdrop-filter` with a frosted fallback for `prefers-reduced-transparency`. They become solid with borders for `prefers-contrast: more`.
- **Press feedback.** Buttons scale to 0.97 on press.
- **Instructional text removed:**
  - the idle hint
  - the route "tap a section" tip
  - the rating-scale captions (the 1–5 meaning is now an accessible label)
  - the search placeholder hint
  - the weather and walkability disclaimers in the sheet
  
  Location problems are now short messages, such as "Location access denied". With no route, the sheet doesn't show and the whole map is visible.

### Verification

- **Frontend:** `npx vitest run` → 15 tests, OK (6 new in `spring.test.js`: projection, snap choice, rubber-band, spring settle and overshoot, release velocity). `npm run build` → OK.
- **Browser at 1366×768, with a route to Rizal Library:**
  - The top cards end at 183 px of a 720 px phone, and the collapsed sheet shows 146 px, so about 58% of the phone height between them is clear map.
  - Dragging the handle down collapsed the sheet (offset 218 px), and dragging up opened it.
  - Tapping a route section opened the 128 px street card with no scrim.
- **Browser at 360×740:** no horizontal scroll, and the top cards end at 126 px.
- **Gesture test caveat:** synthetic pointer events from a script didn't move the sheet, but real mouse drags did. The touch feel on a real phone is not yet checked.

## 2026-11-16: Comfort-window times can be shown on the map

### Changes

- **Clickable time chips.** The Now, +15 min and +30 min chips in the route sheet are now buttons. Choosing one redraws the selected route's sun and shade sections on the map for that time.
- **Default selection.** "Now" is selected by default and after every new route request. The lowest score is no longer highlighted; the "Less sun at …" line in the peek still names the best time (F-15).
- **Plain scores.** The chips show the score without a percent sign, for example "15" instead of "15%". The route cards still show the sun share as a percentage (F-05).
- **API.** `comfort_window.times[]` entries now include the full `exposure` (sections and figures) for each time. The entry at offset 0 equals the route's own exposure.
- **Unchanged.** The route cards and the live walk keep using the "now" figures.

### Verification

- **Backend:** `python -m unittest discover -s backend -p 'test_*.py'` → 61 tests, OK. The new test in `test_comfort.py` checks that each time has its own sections, that "now" equals the route's exposure, and that each time's score matches its sections.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.
- **Browser at 1366×768, route to Rizal Library:**
  - Chips showed "Now 4 / +15 min 0 / +30 min 0", with Now selected on load.
  - Choosing +15 or +30 removed the two direct-sun (orange) sections from the map.
  - Choosing Now restored them.

## 2026-11-16: Comfort-window chips show percentages again

- The Now, +15 min and +30 min chips show the sun share as a percentage again, for example "15%". This matches the route cards and PRD F-05, which defines the score as a percentage of route length.
- Showing the figure as a bare number looked like a score where higher is better, but for this figure lower is better. The chips are still clickable and still drive the map.
- **Verification:** `npm run build` → OK.

## 2026-11-17: "Origin" when location is unavailable; quieter empty fields and missing readings

### Changes

- **"Origin" fallback.** When device location is denied, unavailable, too imprecise or outside the test area (E-04), the empty start field now shows "Origin" instead of "Your Location". It switches back to "Your Location" once a location fix succeeds.
- **Faded placeholders.** Empty start and destination fields keep their blue and orange-brown tint at 50% opacity, so they no longer look like chosen values.
- **Muted missing weather.** Readings that are not available now show as "Temp n/a" and "Heat index n/a" in muted grey, not bold red. Available readings stay red, as in the reference (F-12).

### Verification

- **Browser at 1366×768 with simulated location:**
  - Before a fix, the start field showed the "Origin" placeholder at 0.5 opacity, with a "Location unavailable" toast.
  - After setting a location and tapping locate, the start became "Your Location".
- **Weather:** Open-Meteo did not answer within the 5 s timeout during this check. `/api/weather` returned "not available" for every reading, and the pill showed both readings muted.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Search results no longer hidden under the time pill

- **Bug.** The place-search results drop down from the location card. Because the time pill comes later in the page and is a translucent layer, it drew on top of the list and hid the first result.
- **Fix.** The location card now sits on a higher layer (`z-index: 2`) than the time pill (`z-index: 1`).
- **Verification.** In the browser at 1366×768, searching "leong hall" showed "Dr. Ricardo Leong Hall" over the pill area, and the element at the list's centre was the results list. `npm run build` → OK.

## 2026-11-17: Routes computed on demand with a "Find routes" button

### Changes

- **No auto-compute.** Routes are no longer computed as soon as the start and destination are set. A compact "Find routes" button appears at the bottom once both are set. While a request runs it shows "Finding routes…".
- **Changing the trip clears results.** Changing the start or destination (including swapping them) or the departure time clears the old results and any live walk. The button then shows again, and no request is sent until it is tapped.
- **Unchanged.**
  - Accepting "Recalculate" during a walk (F-14) still reroutes immediately, because that tap is the user's request.
  - Rating a street or toggling a covered mark refreshes routes only when routes are already shown.

### Verification

- **Browser at 1366×768 with simulated location:**
  - With the start set and the destination "Rizal Library" chosen, "Find routes" was shown and 0 `/api/routes` requests were made.
  - Tapping it showed "Finding routes…", then the results, with 1 request.
  - Swapping start and destination cleared the results and showed the button with 0 new requests.
  - During a walk about 65 m off the route, "Recalculate" made 1 request automatically and the walk stayed active.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Legend shows only the styles on the map

- **Change.** The map legend now lists only the labels drawn on the map:
  - the selected route's section labels, at the chosen comfort-window time
  - "Covered", when any user-marked covered section is drawn
  
  Most routes show just "Direct sun" and "Shaded" on one line.
- **Covered style kept.** The user suggested dropping "Covered" because covered sections count as shaded. They do count as shaded in the figures (S-11), but S-11 also requires a distinct "covered" style. So the style stays, and its legend entry appears only when covered sections are on the map.
- **Verification.** Browser at 1366×768, route to Rizal Library in the evening, with 2 covered marks in the preview database:
  - The legend showed "Shaded" and "Covered" on one line, 23 px tall instead of 37.6 px.
  - The map strokes matched: teal shaded and purple covered.
  - `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Covered marks drawn only as part of a route

### Changes

- **Covered marks no longer drawn everywhere.** Previously every saved covered mark was drawn on the map at all times. Now a mark appears only:
  - as a "covered" section of a generated route that passes through it (S-11 style), or
  - for the one street section open in the street card while it is marked covered, so a new mark is visible on the map when it is saved (S-10).
- **Legend.** It shows "Covered" only in those two cases.
- **Cleanup.** The frontend no longer fetches `/api/covered`; that endpoint stays in the API.

### Verification

- **Browser at 1366×768:** the preview database held 2 covered marks.
  - 0 purple lines were drawn on load.
  - Opening a footway and marking it covered drew 1 purple line, and unmarking removed it.
  - Closing the card left 0 purple lines. The test mark was removed, so the database is back to its 2 marks.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Route card layout tidied

### Changes

- **Difference line moved.** The "−28 pts · −1 min sun · +108 m" line was removed from the shadier route card. PRD F-09 still requires the differences to be displayed, so they now appear as one line in the pulled-up details, for example "Shadier route: 2 percentage points less sun, <1 min less in sun, 1 m longer."
- **Card order.** Each card now shows its lines in this order:
  1. route name
  2. total walk time and distance
  3. minutes in sun
  4. the unknown share and walkability, when present
- **Score alignment.** The sun share is pinned in a right-hand column with `line-height: 1`, so its top lines up with the top of the route name.

### Verification

- **Browser at 1366×768:** route to Dr. Ricardo Leong Hall at 3:00 PM.
  - The cards read "Shortest | 5 min walk · 358 m | 3 min in sun | 72%" and "Shadier | 5 min walk · 359 m | 3 min in sun | 70%".
  - On both cards, the top of the score matched the top of the route name (difference under 0.5 px).
  - The difference line appeared in the details.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Assumptions list shortened to one line

- **Change.** The 4-line assumptions list in the route details is now one muted line: "Clear sky · building shade only · 80 m/min". Hovering over the line still shows the full notes as a tooltip.
- **What it still covers.** This keeps the clear-sky and building-only limit (C-05) and the stated walking speed (F-06).
- **Notes dropped from the list.**
  - "Unknown counts as sun": the route card already says "counted as sun" whenever a route has unknown sections (E-03).
  - "Covered walkways count only where users have marked them".
- **Verification.** In the open preview, the line read "Clear sky · building shade only · 80 m/min" at 14 px tall. `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: The route sheet shows that it can move

### Changes

- **Grabber that points the way.** The faint grab bar is now two darker halves that bend:
  - into "^" when the sheet is collapsed, meaning pull up
  - into "v" when it is open, meaning pull down
  
  The bend follows the drag continuously through a `--sheet-progress` CSS variable that the spring updates, and the bar is flat halfway (SKILL.md §8, "hint in the direction of the gesture"). Hovering or pressing darkens it, and tapping it still toggles the sheet.
- **Scroll edge fade.** When the opened details hold more content than fits, the bottom 28 px of the details fade out (SKILL.md §12). The fade goes away once you scroll to the end.

### Verification

- **Browser at 1280×600:** route to Dr. Ricardo Leong Hall at 3:00 PM.
  - Collapsed: progress 0, and the left half rotated −18° (shape "^").
  - Opened: progress 1, and the left half rotated +18° (shape "v").
- **Browser at 1024×500:** the open details overflowed and showed the fade. Scrolled to the end, there was no fade.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Straight grab bar restored; sliver and nudge show the sheet can be pulled up

### Changes

- **Straight grab bar.** The bending "^/v" grabber from the previous entry was removed at the user's request. The sheet has a plain straight grab bar again, slightly larger and darker than before (36×5 px).
- **Sliver of the details.** While collapsed, the sheet now leaves 26 px of the details showing under the route cards, fading out downward. The cut-off content hints that there is more to pull up. The fade is driven by `--sheet-progress`, so it slides away as the sheet opens, and nothing is faded when the sheet is fully open.
- **One-time nudge.** When new routes appear, the sheet lifts about 12 px and springs back once (spring damping 0.55, response 0.4). It is skipped when the device asks for reduced motion.
- **Kept.** The bottom fade on the opened details while more content is below.

### Verification

- **Browser at 1366×768:** route to Dr. Ricardo Leong Hall at 3:00 PM.
  - The collapsed sheet rested at a 115 px offset, with 26 px of the details visible under the cards.
  - The grab bar is 36 px wide.
- **Nudge:** the browser pane reports `prefers-reduced-motion: reduce`, so the nudge correctly did not play (0 px). With that setting overridden in the page, the sheet lifted 12 px and settled back to 115 px.
- **Frontend:** `npx vitest run` → 15 tests, OK. `npm run build` → OK.

## 2026-11-17: Equal spacing in the route details

- **Change.** The blocks in the opened route details (the comparison line, the Now/+15/+30 chips, the UV and humidity line, and the limits line) are now spaced evenly with a 10 px flex gap. Before, each block had its own margin (6, 0, 8 and 4 px), so the chips sat tight under the comparison line.
- **Verification.** In the preview, the gaps between the four blocks measured 10, 10 and 10 px. `npm run build` → OK.

## 2026-11-17: Time chips centre-aligned

- **Change.** In the Now/+15/+30 chips, the time label and the percentage are now aligned on their vertical centres instead of their text baselines.
- **Verification.** In the preview, the centres of the label and the percentage differed by 0 px on all three chips. `npm run build` → OK.

## 2026-11-17: Navigation mode during the walk (GPS only)

### Changes

- **Navigation view.** Once a walk has a GPS fix, the app switches to a navigation view.
  - **Top:** a teal turn banner replaces the location card and time pill. It shows the next manoeuvre's arrow, the distance to it (rounded to 5 or 10 m) and the street, or "Arrive at destination".
  - **Bottom:** a slim bar replaces the route sheet. It shows time left, distance left, the arrival clock time, and the sun share and minutes in sun on the rest of the route (F-13), plus a red End button.
  - **Map:** it follows the user at zoom 18, with the user 60% down the screen, and rotates course-up. The user marker becomes a heading arrow.
  - **Map interaction:** gestures and taps are off while navigating.
  - **Attribution:** a small "© OpenStreetMap contributors" label replaces the attribution control, which sits off-screen on the rotated map.
- **How turns are found** (`lib/nav.js`):
  - A turn is a bearing change of at least 30°, measured over ±12 m.
  - Turns within 15 m of each other are merged.
  - Turns are classed as bear, turn, sharp or U-turn.
  - The heading comes from the route ahead, so it is stable even when standing still.
- **How the map rotates.** Leaflet cannot rotate, so the map element is resized to a square that covers the phone at any angle, centred on the user's on-screen spot, and rotated with CSS. It always turns the shortest way.
- **Street names.** The API's route edges now carry `named`, which is true only for real OSM street names. Unnamed paths are left out of instructions instead of saying "onto Footway".
- **GPS only.**
  - Without a fix, the walk keeps the normal sheet with "Locating…" and the location message.
  - If GPS is denied or unavailable mid-walk, the view drops back to the normal sheet. A timeout doesn't, since it can just mean the walker is standing still.
  - Off-route prompts (F-14) still appear in place of the bottom bar.
  - Ending the walk restores the normal map and fits the route.
- **Dev simulator fix.** A new watch now gets the "denied" state instead of the last position.

### Verification

- **Backend:** `python -m unittest discover -s backend -p 'test_*.py'` → 62 tests, OK. The new test checks the `named` flag on route edges.
- **Frontend:** `npx vitest run` → 22 tests, OK. 7 are new in `nav.test.js`: bearings, turn classes, manoeuvre detection with street names, unnamed paths, ignoring small kinks, next-turn distance and arrival, and heading. One of them first failed on an exact 70 m check against a 69.89 m haversine distance, so it now uses an approximate comparison like the other distance checks. `npm run build` → OK.
- **Browser at 1366×768, simulated walk along the route to Rizal Library (526 m):**
  - The banner went from "100 m · Sharp right" to "45 m", then "Bear left", "Turn right" and "Arrive at destination", ending at "5 m".
  - Time and distance left went from "7 min / 530 m" to "<1 min / 5 m".
  - The map rotation changed with each leg. The user arrow sat at the centre, 60% down the screen.
  - With location denied before starting, there was no navigation, the normal sheet showed "Locating…" and "Location access denied", and the map was not rotated.
  - GPS returning turned navigation on. GPS denied mid-walk dropped back to the sheet.
  - End restored the search cards and an unrotated map sized to the phone.
- **Test caveats.**
  - The browser pane reports the page as hidden, which pauses GPS by design (C-06), so the walk test made the page report visible.
  - Real-phone behaviour is not checked: compass, motion, GPS jitter and how the rotation feels.

## 2026-11-17: Pinch zoom while navigating; monotone map and route casing

### Changes

- **Pinch zoom while navigating.** Pinch, double-tap and mouse-wheel zoom are now on during navigation, using Leaflet's `"center"` zoom mode.
  - It zooms around the map centre, which is the user, and the pinch scale doesn't depend on the CSS rotation, so it works on the rotated map.
  - Panning stays off, because the map follows the user.
  - Navigation starts at zoom 18. After that, GPS updates keep the zoom the user chose.
- **Monotone map.** The OSM tiles are now greyscale through a CSS filter on `.leaflet-tile-pane`, so POI icons fade to grey and the coloured route stands out. While navigating the map is washed out further, so tilted labels recede.
- **CARTO tried and dropped.** CARTO Positron (`light_all` and `light_nolabels`) was tried first, but its tiles now show "API KEY REQUIRED" without an account, so it was not used.
- **Route casing.** Each route now has a white outline underneath, like navigation apps: 12 px for the selected route and 9 px for the other one, which is a lighter grey.

### Verification

- **Browser at 1366×768:**
  - Tiles come from `*.tile.openstreetmap.org`, with the filter `grayscale(1) contrast(.85) brightness(1.06)`, or `contrast(.7) brightness(1.12)` while navigating.
  - Starting a walk set zoom 18. Three wheel steps zoomed out to 16, and a GPS update kept 16.
  - Screenshots showed a grey map with the teal route and white casing, and a lighter map while navigating.
- **Frontend:** `npx vitest run` → 22 tests, OK. `npm run build` → OK.
- **Not checked:** a real two-finger pinch on a phone.

## 2026-11-17: Map colour partly restored

- **Change.** The user found the greyscale map too monotone. The tile filter now keeps some colour:
  - normally `saturate(.45) contrast(.92) brightness(1.04)`
  - while navigating `saturate(.4) contrast(.82) brightness(1.08)`
  
  POI icons and buildings keep soft tints, while the route still stands out.
- **Banner colour contrast (WCAG ratio).** Checked for the user's question about a yellow banner. Nothing was changed yet; the choice is pending.

  | Banner colour | White text | Dark #202124 text |
  | --- | --- | --- |
  | teal #16766f (current) | 5.45 | 2.96 |
  | brown #b0651f | 4.44 | 3.62 |
  | sun orange #e8892b | 2.61 | 6.17 |
  | amber #f2b705 | 1.82 | 8.86 |

- **Verification.** The computed filter in the preview was `saturate(0.4) contrast(0.82) brightness(1.08)` while navigating. `npm run build` → OK.

## 2026-11-17: Turn banner in brand brown

- **Change.** The navigation turn banner is now brand brown with white text, as chosen by the user, instead of teal.
  - The brand brown #b0651f gives 4.44:1 with white, just under WCAG AA 4.5:1 for the small instruction line.
  - The banner uses a barely darker #ad631e (4.58:1) instead.
  - It is now solid rather than translucent, so a light map behind it can't lower the contrast.
- **Verification.** In the preview while navigating, the banner computed to `rgb(173, 99, 30)` with white text ("100 m / Sharp right"). `npm run build` → OK.

## 2026-11-17: Original map colours restored

- **Change.** At the user's request, the CSS filter on the map tiles was removed, so the map shows OpenStreetMap's original colours again, both normally and while navigating.
- **Kept.** The white casing under the routes still helps them stand out.
- **Verification.** In the preview, the computed tile-pane filter is `none`. `npm run build` → OK.

## 2026-11-17: Walk ends on arrival

### Changes

- **Arrival.** During a walk, a GPS fix within 15 m of the end of the route, while on the route, now counts as arrival (`hasArrived` in `lib/nav.js`).
  - The walk stops following GPS and leaves the navigation view. The map un-rotates and fits the route again.
  - An arrival card replaces the bottom bar: "You've arrived at <place>", with the time taken, the route distance, and the minutes and share in sun from the route's figures.
  - Done dismisses the card and returns to the normal route sheet, where Start is available again.
- **Clearing.** Changing the trip clears an open arrival card.

### Verification

- **Frontend:** `npx vitest run` → 24 tests, OK. 2 are new: the 15 m threshold, and the summary figures. `npm run build` → OK.
- **Browser at 390×844, simulated GPS walk to Rizal Library (526 m, 15 m steps every 0.7 s):**
  - Turn-by-turn ran as before ("Sharp right", "Bear left", "Turn right", "Arrive at destination").
  - At 525 m (1 m left) the walk ended. The card read "You've arrived at Rizal Library | <1 min · 530 m · 0 min in sun (0%) | Done".
  - Navigation was gone, the search cards were back and the map was unrotated.
  - Done removed the card and showed the route sheet with Start.
- **Caveat.** Time taken shows "<1 min" because the simulated walk took about 25 s of real time.

## 2026-11-18: Floating cards spaced like the top cards

- **Change.** The navigation bar and the other floating bottom cards (arrival, street card, reroute prompt, messages, Find routes) now sit as far from the bottom as the top cards sit from the top, with the same side margins.
  - New CSS variables `--bottom-gap` and `--side-gap` hold these gaps. Before, the cards were 14 px from the bottom in the phone frame and 2 px on a real phone, with 10 px sides.
- **Unit fix.** `--top-offset` now uses container-query height units (`6cqh`, with `.phone` set to `container-type: size`) instead of `6%`. A percentage in a margin is a share of the width, so the bottom gap had come out 3 px smaller than the top gap.
- **Real phones.** The bottom gap uses the bottom safe area.
- **Verification.**
  - In the 1366×768 phone frame (360×720 phone), the top gap was 43 px, the bottom gap 43 px and the sides 12 px.
  - At 390×844 (full-screen phone layout), the gaps were 10 / 10 / 10 px, with no horizontal scroll.
  - `npx vitest run` → 24 tests, OK. `npm run build` → OK.

## 2026-11-18: Phone access over any network through a Cloudflare tunnel

### Changes

- **One local address.** The app is now served from a single address so a public link can reach it.
  - `frontend/vite.config.js` proxies `/api` to the Python API (`127.0.0.1:${SHADES_API_PORT || 8000}`) for both `vite` and `vite preview`.
  - It accepts `.trycloudflare.com` host names.
  - The frontend's default `API_URL` is now `""`, meaning same-origin `/api/...`. `VITE_API_URL` still overrides it.
- **`npm run phone`.** Builds the app and serves it with `vite preview` on `127.0.0.1:4173`. The API stays bound to `127.0.0.1`.
- **cloudflared installed.** Version 2026.11.1 was installed with winget (installer hash verified) after the user approved it. `cloudflared tunnel --url http://127.0.0.1:4173` gives a public https link that works over mobile data. That https link is what lets phone browsers share GPS with the app.
- **Docs and preview config.**
  - README has a "Use on your phone" section, with the caveats: keep the laptop on, the link changes on restart, anyone with the link can use it, and location is still never logged.
  - `.claude/launch.json` has a `phone` preview, which uses the 8010 preview API.

### Verification

- **Frontend:** `npx vitest run` → 24 tests, OK. `npm run build` → OK.
- **Locally:** `http://127.0.0.1:4173/api/health` → ok, `/api/places?q=Rizal Lib` → results, and the page → 200. The built app called `/api/weather` on its own origin.
- **Through the tunnel** (`https://manual-fuzzy-explaining-officers.trycloudflare.com`, a temporary link):
  - `/api/health` → 200, the page → 200, and `POST /api/routes` → 200.
  - In the browser pane the app loaded with `isSecureContext: true`, geolocation available, and same-origin API calls.
- **Not done:** opening the link on the user's phone over mobile data needs the user's phone.
- **Note:** two processes were already listening on `127.0.0.1:8000` (PIDs 22080 and 23220), probably older copies of the API. The check used the current preview API on 8010 instead.

## 2026-11-18: Vector map (MapLibre GL + OpenFreeMap) in place of Leaflet raster tiles

### Changes

- **Sharper map that rotates for real.** The OSM raster tiles were blurry on phone screens, and Leaflet could only fake course-up by enlarging and CSS-rotating the map element. The user chose a vector map with no API key.
  - `leaflet` was removed and `maplibre-gl` (6.19.0) added. `main.jsx` imports `maplibre-gl/dist/maplibre-gl.css` instead of Leaflet's CSS.
  - The basemap is the OpenFreeMap "liberty" style (`https://tiles.openfreemap.org/styles/liberty`), in its own colours. It renders at the screen's pixel density.
  - Vite pre-bundles the library, which breaks its built-in worker lookup, so `MapView.jsx` points `setWorkerUrl` at `maplibre-gl/dist/maplibre-gl-worker.mjs?url`.
- **`MapView.jsx` rewritten; same props and ref methods** (`fitGeometry`, `panTo`, `resetView`), so `App.jsx` is unchanged apart from one line.
  - Routes, sections, covered marks and the highlight are GeoJSON sources with line layers. They keep the old look: white casing (12 px selected, 9 px others), sun solid orange, shaded teal with a white dotted overlay, unknown grey dashed with "?" markers at section midpoints, covered purple with a white centre line, and other routes grey. Patterns still differ without colour (S-04).
  - The tapped section or street highlight now draws on top of the route. Before, the selected route's white casing hid it on route sections.
  - Markers are DOM markers with the existing `map-point` and `map-heading` classes. The heading arrow uses `rotationAlignment: "map"` and is rotated to the heading.
  - Taps use `queryRenderedFeatures` with a ±6 px box. A section opens the street card, another route selects it, and anything else is a plain street tap with `{lat, lng}`.
  - The map starts at the same centre (Katipunan, zoom 17). Panning is limited to roughly Metro Manila (lat 14.30–14.85, lon 120.85–121.20, min zoom 11) so it keeps working as the study area grows. The study-area logic in `App.jsx` was not touched.
  - Outside navigation the map stays north-up, with rotate and tilt gestures off.
- **Navigation mode uses native rotation.**
  - Each GPS update calls `easeTo` with the heading as bearing and top padding of 20% of the height, so the user sits 60% down.
  - Entering navigation zooms to 18. This zoom stays pending until it is reached, because back-to-back GPS updates were cancelling the first animation and leaving the map at the route-fit zoom. After that, updates keep the user's zoom. A pinch or wheel zoom also cancels the pending zoom.
  - Pan, keyboard, box zoom and map taps are off. Pinch and wheel zoom stay on around the centre (the user).
  - Leaving navigation drops the padding, turns back to north-up and re-enables gestures. The route fit uses bearing 0.
- **Attribution.** MapLibre's compact attribution is at the top right, just below the top cards, where the bottom sheet cannot cover it. It folds to its (i) button when a route is fitted. The Leaflet rotation CSS (`.map--navigating`, `.leaflet-*`) and the separate `.nav-attribution` overlay in `App.jsx` were removed.
- **Hot reload.** Every map effect checks that its map is still mounted. A hot reload re-runs effects with the removed map still in state, which had crashed the page.

### Verification

- **Frontend:** `npx vitest run` → 24 tests, OK. `npm run build` → OK (Vite warns that the main chunk is over 500 kB, because MapLibre is bundled in).
- **Browser preview** (Vite on 5180 with `/?simulate-location`). The working-tree backend could not start, because the Metro Manila tiling work in progress needs `datasets/derived/build-info.json`. The check used the committed backend (HEAD), run from a scratch copy on port 8010 with its own scratch database, so test ratings did not reach `data/`.
  - The vector map is crisp at device pixel ratio 1.25, with street and POI labels.
  - A route to "Rizal Library" at 9:00 drew sun, shaded and (after marking) covered sections with the right patterns, plus the start and destination markers.
  - Tapping a section opened the street card with the section reason. Marking it covered showed the purple section right away. The mark was then removed again.
  - The +30 min chip redrew the route (91% → 92% sun).
  - For a trip to Gonzaga Cafeteria at 10:00 (two routes), the other route rendered grey. Picking the Shadier card swapped which route was grey.
  - **Simulated walk:**
    - The map rotated to the heading (bearing 89° when walking east), with labels upright.
    - The user arrow sat at exactly 50% across and 60% down and pointed up.
    - The zoom went to 18. A wheel zoom to 17.6 was kept after the next GPS update.
    - Panning was off, and a tap on the route opened nothing.
  - **End of walk:** bearing 0 and padding 0, gestures back on, and the route re-fitted.
- **Not verified:**
  - The "?" markers on unknown sections: none of about 70 probed trips at 10:00 had an unknown section with the committed backend.
  - Tapping a grey alternate route to select it: in the tested trip it ran entirely under the selected route.
  - Pinch-zoom and rotation on a real phone.
- **Known overlap:** after a route fit, the folded attribution (i) button can sit over the destination marker when the destination is near the top right.
- **Follow-up (same day):** at the Metro Manila session's request, `STUDY_BOUNDS` in `MapView.jsx` is now the Metro Manila study area (S 14.35, N 14.79, W 120.90, E 121.15), matching `/api/health`. Nothing imports it. The pan limit (`MAX_BOUNDS`, lat 14.30–14.85, lon 120.85–121.20) already covered this box with a small margin. The initial view stays on Katipunan. `npx vitest run` → 24 tests, OK. `npm run build` → OK.

## 2026-11-18: Metro Manila study area with on-demand graph tiles

The test area grows from the 2 km Katipunan box to Metro Manila (S 14.35, N 14.79, W 120.90, E 121.15; `backend/area.py`). Building heights still cover only Quezon City. Elsewhere every section is "shade unknown" and counts as sun (E-03), which the user accepted. PRD O-01 now names Metro Manila.

### Data build

- **Source and build:** the Geofabrik Philippines extract (614 MB, `datasets/raw/`, gitignored), streamed once by `backend/build_tiles.py` with pyosmium 4.3.2 under Python 3.13, a build-only dependency. The API stays stdlib-only.
- **Read:** 162,161 walkable ways, 1,662,924 buildings and 182,455 named features.
- **Graph:**
  - Written as 253 tiles of 0.02°, 15.9 MB gzipped JSON, in `datasets/tiles/`.
  - 1,212,485 directed edges.
  - Dropped: 4,383 indoor edges (C-01) and 23,609 edges in disconnected fragments under 200 nodes. Those fragments made snapped points unroutable and sent A\* across the city.
- **Derived files** (15 MB, `datasets/derived/`): `places.db` (150,860 places, FTS5), `unknown-height-cells.bin` (D-01: 413,178 of 645,517 buildings in the raster have heights, 232,339 are flagged unknown) and `build-info.json`.
- **Build time:** 208 s.
- **Removed:** `datasets/katipunan-walking-network.osm` and the XML loader.

### Runtime

- **Tiles:** `tiles.TileStore` loads tiles lazily into an LRU cache, so API startup is 2.2 s whatever the area size.
- **Search limits in `route_nodes(max_cost=…)`:**
  - The shortest search allows 3 × straight-line + 5 km, up to 15 km. A first limit of 2.5 × + 1 km failed a real 337 m trip whose only path is 4.5 km.
  - The shadier search is limited to 3 × the shortest route's length. That limit is lossless, since the most an edge can cost is 3 × its length.
- **Trip limits:**
  - Trips over 10 km straight-line get a 422.
  - Points with no path within 400 m get "There is no walking path near the …".
- **Place search:**
  - Uses FTS5.
  - Ranks by prefix, then by distance to the other trip point (`near=lat,lon`), or to Katipunan (`area.HOME`) when none is set. Without that default, the many "Rizal" places across Metro Manila pushed out Rizal Library.
  - About 10 ms per query.
- **Frontend:**
  - `App.jsx` reads the study area from `/api/health`, falling back to the Metro Manila box.
  - Messages now say "outside Metro Manila" and "No places found in Metro Manila".

### Verification

- **Backend:** `python -m unittest discover -s backend -p 'test_*.py'` → 69 tests, OK. New tests cover:
  - a route across a tile boundary
  - a Makati route that is over 90% unknown
  - the 10 km refusal
  - a point in Manila Bay
  - the search limit
  - Makati, BGC and Manila place search
  - nearest-branch ranking
- **Timing** (in-process, weather patched out; cold then warm):

  | Trip | Cold | Warm | Tiles loaded |
  | --- | --- | --- | --- |
  | Katipunan 0.5 km | 0.28 s | 0.11 s | 9 |
  | Katipunan → UP Diliman (2 km) | 0.50 s | 0.44 s | 3 |
  | Makati 0.7 km | 0.44 s | 0.30 s | 9 |
  | Cubao → Katipunan (4.5 km) | 2.0 s | 2.2 s | 5 |
  | Manila Bay | 0.01 s (422) | | |

  Before the fragment fix, Makati failed with a 422 after 8–10 s and 252 tile loads. Longer routes are now dominated by shade ray-marching, not data loading.
- **`backend/acceptance.py`** (live weather; 6 Katipunan, 2 Makati and 2 Manila pairs at three times):
  - P-01: 30 of 30 requests within 10 s (median 1.67 s, max 4.22 s).
  - F-01: 30 of 30 returned routes with sun figures.
  - F-04: 7 of 30 returned a shadier alternative.
  - 36 tiles were loaded for the run.
- **Frontend:** `npx vitest run` → 24 tests, OK. `vite build` into a scratch directory → OK.
- **Browser check** (preview API on 8010, Vite on 5180, after the vector-map session finished):
  - Place search found Greenbelt 4 and Ayala Triangle Gardens.
  - The Makati route (477 m) drew on the MapLibre map. At about 19:00 it was fully shaded, because the sun was down.
  - Through the same API at 12:00, the Makati route is 100% "unknown" and counts as 100% sun.
  - A 12.6 km trip returned the "Too far" message, and `/api/health` returned the Metro Manila area.
- **Not verified:**
  - The "?" markers on unknown sections in the browser.
  - Use on a phone.

## 2026-11-24: Ready to run on Vercel, with fixes to long routes, restarts and location privacy

The app can now run without the laptop: the website and the Python API on Vercel, ratings and covered marks in Turso (hosted SQLite). It is **not deployed yet**.

### Problems found and fixed

- **Long routes missed P-01.** A 9.7 km trip took 10 to 15 s. The 2026-11-18 acceptance run sampled trips of 300–1500 m and its timings stopped at 4.5 km, so neither showed this. `ExposureModel.classify_point` now skips stretches of a sight line that no building can reach. `test_shade_speed.py` compares it with a copy of the old algorithm.
- **Ratings and covered marks failed after a restart (D-03).** Since the 2026-11-18 tile change, a street was found only if its tile was already loaded, so saving returned 404 and `/api/covered` dropped marks. `datasets/derived/ways.db` (157,738 ways, 2.2 MB, from `build_ways.py`) now says which tiles to load.
- **Location privacy (C-04):**
  - The exact start was sent to the weather service. It is now rounded to 0.1° (about 11 km).
  - `/api/places` and `/api/streets/nearest` carried points in URLs, which hosts log. They are now POST with a JSON body.
  - Place search sent the GPS position as `near` when it was the other trip point. It no longer does, so with a GPS start the results rank from Katipunan.
- **CLAUDE.md:** a corrupted build command, an out-of-date search limit and the old Leaflet description were corrected.

### Added

- **`storage.TursoStore`**, chosen when `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are set. When the database cannot be reached, routes still work, walkability is "not available" and saves return 503. On Vercel without those settings, `NoStore` does the same.
- **Vercel:** `api/index.py`, `vercel.json` (Singapore region), `.vercelignore`, `.python-version` (3.13).
- **Home screen:** web manifest and icons, so the phone can open Shades full-screen.
- **Time zone:** Manila time is a fixed UTC+8 in `area.py`, since a host may have no time-zone files.

### Verification

- **Backend:** 90 tests, OK on Python 3.10 and on 3.13.
- **Frontend:** `npx vitest run` → 24 tests, OK. `npm run build` → OK.
- **Bundle rehearsal:** a copy with only the files Vercel would get (38 MB), on Python 3.13 on this laptop, with no time-zone files and no database, over HTTP through `api/index.py`. Import 1.61 s. The weather lookup was live.
  - The 9.7 km trip: 3.58 s with cold tiles, 3.15 s warm.
  - 20 trips from 0.6 to 9.5 km apart, at 8:00, 10:00, 12:00 and 15:00: 20 of 20 within 10 s (median 2.11 s, max 4.55 s).
- **Browser preview:** with a simulated GPS start, search, route and street card worked, with no console errors. The GPS point was sent only in `POST /api/routes`. A covered mark was still listed after the API was restarted, and was then removed.
- **Not verified:** the real Turso service, the deployed site (including Vercel's path form, cold start, speed and logs), and use on a phone. P-01 is defined on a mobile connection, which these timings are not.

## 2026-11-24: Deployed on Vercel

Live at https://shades-az5g-kohl.vercel.app/ (Vercel Hobby, Singapore region, Turso database). It is public.

- **Deploy problem:** the first two builds failed at the install step. The build passed after the project settings were changed following advice to clear Root Directory; the settings themselves were not inspected. `vercel.json` also moved from `npm ci` to `npm install`.
- **Live timing** (from the laptop, no mobile network): the same 20 trips as the rehearsal, 0.6 to 9.5 km apart, all within 10 s (median 2.24 s, max 6.15 s). The 9.7 km trip took 5.59 s, then 4.89 s.
- **Live checks:** search, streets, weather, the 10 km refusal and rating validation answered as expected. A covered mark was saved, listed, seen on its street and removed, so Turso reads and writes work. In the browser at 375 px wide, a search and a route worked with no console errors and no sideways scrolling.
- **Not verified:** saving a rating, data after a redeploy or on a second device (D-03), coordinates in Vercel's logs (C-04), a cold start after idle time, and use on a phone (GPS, navigation, home screen, mobile-data timing for P-01).

## 2026-11-26: Rotatable map, looking around while navigating, arrival at 30 m

- **Rotation:** the map turns with a two-finger twist (right-drag or Ctrl+drag on a computer) and never tilts. When it is turned, a compass button appears above the locate button; tapping it returns north-up.
- **Navigation:** the map follows the user as before until they drag or twist it. GPS updates then move only the arrow, and a **Re-center** button returns to following, direction-up. Zooming keeps following. Tapping the compass while navigating turns the map north-up and pauses following. Taps on streets stay off while navigating.
- **Zoom fix:** zooming while following is meant to keep the user in place, but MapLibre ignores the "around centre" setting when zoom is already on. In the old code too, a wheel zoom moved the user off-centre (to 73%, 91% of the screen in the preview). The handlers are now switched off and on again with the setting.
- **Arrival:** `ARRIVE_METERS` is 30 (was 15). `hasArrived` also counts a straight-line distance to the route's end within 30 m, so cutting a corner near the end still arrives. A route shorter than about 30 m arrives as soon as the walk starts.

### Verification

- `npx vitest run` → 25 tests, OK (new arrival tests). `npm run build` → OK. Backend: 90 tests, OK.
- **Browser preview** (`/?simulate-location`, 526 m route from Katipunan to Rizal Library). Gestures were driven with synthetic pointer, mouse and wheel events:
  - Ctrl+drag turned the map (compass needle at 148.8°). The compass tap returned it north-up, and the compass hid again.
  - While walking, the arrow held at 50% across and 60% down over five GPS updates.
  - A drag moved the arrow to 16%, 72%, and the next GPS update did not snap the map back. Re-center appeared and returned the arrow to 50%, 60%. A Ctrl+drag twist also paused following.
  - A wheel zoom while following kept the arrow at 50%, 60% and showed no Re-center.
  - Ending the walk brought back the locate button.
  - Arrival: still navigating at 60 m and 35 m left. The summary card appeared at 27 m.
- **Known:** the one GPS update that lands while a zoom gesture is finishing is skipped (existing behaviour), so the map re-centres on the next update.
- **Not verified:** real two-finger twist and pan on a phone, and arrival on a real walk.
