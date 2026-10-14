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
4. Measure end-to-end request time and confirm the under-three-minute requirement.
5. Add tests for unavailable UV responses, unavailable route data, invalid times, and no-route cases.
6. Add README setup instructions, API startup commands, dataset attribution, and a short demonstration workflow.
7. Create a requirements traceability table mapping the implemented behavior to the PRD acceptance criteria.

### Known limitations

- The walking network covers only the downloaded ADMU/Katipunan bounding box, not all of Quezon City.
- Route alternatives are produced by penalizing the first route; they are useful alternatives but are not guaranteed to be globally optimal or meaningfully different in every case.
- The building-height raster is approximately 10 m resolution. It may miss narrow structures, sidewalk-side differences, trees, awnings, and temporary shade.
- The GeoTIFF source units and detailed quality metadata have not yet been independently confirmed. Extreme floating-point nodata values are masked by the parser.
- Shade percentage is currently distance-weighted and binary per route segment: any detected obstruction marks that segment as shaded. Teal intensity communicates obstruction strength but does not yet weight the percentage.
- The shade model uses a simplified ray check from segment midpoints and does not model terrain, trees, cloud cover, covered walkways, or human movement.
- UV is contextual and retrieved from Open-Meteo at runtime. It is not used to calculate route shade, and the route request still works if the service is unavailable.
- OpenStreetMap and map-tile services require network access and may rate-limit requests. The application does not continuously track user location.

## Implementation Plan

### Objective

Build a prototype shade-optimized walking route planner for a limited test area in Quezon City. The prototype will accept a start point, destination, and travel time; generate walking route options; estimate direct-sun and shade segments using sun position and available building data; and present route comparisons in an interactive map.

### Scope and guardrails

- Focus on outdoor direct sunlight exposure only.
- Do not provide indoor routing, general walkability ratings, thermal-comfort estimates, heat-stress predictions, health-risk claims, or continuous location tracking.
- Limit processing and testing to a defined Quezon City study area.
- Use the current time as the default travel time.
- Treat UV Index as contextual information, not as a direct shade measurement.
- Keep the processing target below three minutes for a valid route request.

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
	- Make building-height availability an early decision gate. If reliable heights are unavailable, use a clearly documented prototype fallback such as a fixed/default height or footprint-only approximation and report its limitations.

### Implementation sequence

#### Phase 1: Requirements, data, and feasibility

- Convert the PRD requirements into a traceability checklist for F-01 to F-07, S-01 to S-07, P-01, O-01, and C-01 to C-04.
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
- Add structured error responses and a request-time measurement for the under-three-minute target.

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
- Benchmark representative requests and keep normal processing below three minutes.
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
