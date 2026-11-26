# Shades

Shade-aware walking routes across Metro Manila, with building-height shade data for Quezon City (including Katipunan and Ateneo de Manila University). For a trip and a departure time, Shades shows the shortest route and a shadier alternative. For each route it shows how much is in direct sun, the minutes spent in the sun, the distance and the walking time.

## Prerequisites

- Python 3.10 or newer. The backend uses only the standard library, so there is nothing to `pip install`.
- Node.js 20 or newer and npm.
- Internet access for the OpenStreetMap map tiles and the live Open-Meteo weather readings.

The application does not require an API key. The walking network and the building-height raster are already stored in `datasets/`.

## Launch the application

Run the backend and frontend in two separate PowerShell terminals from the repository root.

### 1. Start the Python API

```powershell
python backend\app.py
```

The API runs at `http://127.0.0.1:8000`.
- Set `SHADES_API_PORT` to use another port.
- Set `SHADES_DB` to store ratings and covered marks somewhere other than `data/shades.db`.

On Windows, if `python` opens the Microsoft Store alias, run the command with the Python interpreter selected in VS Code instead. For the development environment used for this prototype:

```powershell
& 'C:\msys64\mingw64\bin\python.exe' backend\app.py
```

### 2. Start the React/Vite frontend

```powershell
Set-Location frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/` in a browser. Vite passes `/api` requests to the API on port 8000. If the API runs on another port, start Vite with `SHADES_API_PORT` set to that port, for example `$env:SHADES_API_PORT='8010'`.

On a desktop-sized browser, the app is displayed inside a virtual phone frame so the mobile layout can be tested without a physical device. On a real phone, the frame is removed and the app uses the full viewport.

### 3. Stop the application

Press `Ctrl+C` in each terminal running the backend and frontend.

## Use on your phone without a laptop (Vercel)

The whole app runs on Vercel's free Hobby plan: the website, plus the Python API as one function (`api/index.py`, configured in `vercel.json`). Ratings and covered marks are kept in a free Turso database, because Vercel does not keep files.

One-time setup:

1. **Turso** ([turso.tech](https://turso.tech)): create a database in the closest region offered. Copy its URL (`libsql://…`) and create a token for it.
2. **Vercel** ([vercel.com](https://vercel.com)): sign in with GitHub and import this repository. Leave **Root Directory** empty (not `frontend`) and keep the settings it reads from `vercel.json`.
3. In the Vercel project, open **Settings → Environment Variables** and add these two, then redeploy:
   - `TURSO_DATABASE_URL`: the Turso URL
   - `TURSO_AUTH_TOKEN`: the Turso token (a secret; never commit it)
4. In **Settings → Deployment Protection**, make sure the production link does not ask visitors to log in.
5. On the phone, open the `https://….vercel.app` link and choose **Add to Home Screen**. Shades then opens full-screen like an app. It still needs internet.

Good to know:

- **Updates:** every push to `main` redeploys.
- **First open:** after a quiet period the first request is slower while the server starts.
- **Without Turso:** routes still work, but ratings show "not available" and cannot be saved.
- **Limits:** the Hobby plan includes 4 CPU-hours a month. Beyond its limits the app is paused.
- **Anyone with the link can use it** and add ratings or covered marks.
- **Privacy:** Vercel logs request URLs, so points are sent only in request bodies.

## Use on your phone through your laptop (any network)

A free Cloudflare Quick Tunnel gives the app a public https link that works over mobile data. No account is needed. Phones only share GPS with https pages, so the tunnel also enables the location features.

One-time setup:

```powershell
winget install --id Cloudflare.cloudflared
```

Then run these in three terminals from the repository root:

```powershell
python backend\app.py
```

```powershell
cd frontend; npm run phone
```

```powershell
cloudflared tunnel --url http://127.0.0.1:4173
```

`npm run phone` builds the app and serves it on `127.0.0.1:4173`, passing `/api` to the API. Open the `https://…trycloudflare.com` link that `cloudflared` prints on your phone.

- **Keep the laptop running:** it must stay on and awake while you use the phone.
- **New link each time:** the link changes whenever the tunnel restarts.
- **Anyone can use it:** anyone with the link can open the app and add ratings or covered marks, so press `Ctrl+C` in the tunnel terminal when you're done.
- **Privacy:** traffic is encrypted to Cloudflare. Your location is sent only inside route requests and is never logged.
- **Restart old API copies:** if an older copy of the API is still running on port 8000, stop it and start it again so the phone gets the current version.

## Use the prototype

1. Allow location access to use your current position as the start point. Alternatively, type a place name in **Your Location**.
2. Type a place name in **Destination**, for example "Rizal Library". Start and destination are set by search or location only; tapping the map does not drop a pin.
3. **Leave Now** uses the current time. Tap it to choose another time.
4. Compare the **Shortest** and **Shadier** route cards. Each shows the share of the route in direct sun, the minutes in the sun, the distance and the walking time.
5. Tap a coloured section of the route, or any street on the map, to open its details. The details show:
   - why a route section is labelled sunny, shaded, covered or shade unknown
   - the street's walkability, with buttons to rate it 1–5
   - a button to mark the highlighted stretch as a covered walkway, or remove the mark
6. Twist the map with two fingers (right-drag or Ctrl+drag on a computer) to rotate it; the compass button turns it back to north-up.
7. Swipe the route sheet up (from anywhere on it) to see the details, and swipe it down again to collapse it. Swiping the collapsed sheet down hides the routes but keeps the trip, so **Find routes** brings them back. The sheet shows:
   - the sun share now, in 15 minutes and in 30 minutes
   - **Start**, which begins the walk. With a GPS fix the app switches to navigation: a banner with the next turn and its distance, a map that follows you and rotates in your direction of travel, and a bar with time and distance left and the sun on the rest of the route. Drag or twist the map to look around; **Re-center** brings it back to you. The walk ends with a summary within about 30 m of the destination. Without GPS the walk shows "Locating…" and keeps the normal view.

The temperature and heat index in the top bar are weather readings for context only. They never change routes or scores.

### When a shadier route is offered

The app always searches for a shadier route, but shows one only when it finds a better one. Otherwise the sheet says "No shadier alternative was found for this trip at this time."

**How the shadier route is chosen** (`exposure_cost` and `SHADIER_SUN_WEIGHT = 3` in `backend/app.py`):

- **The search:** it finds the path with the lowest score, where a **shaded** or **covered** metre scores **1** and a **sunny** or **shade-unknown** metre scores **3**. In other words, each sunny metre avoided can pay for up to 2 extra metres of walking in shade. There is no fixed limit on extra distance.
- **The check:** the result is shown only if it is a **different path** from the shortest route and its **sun % is lower**. The comparison uses the percentage, so a longer detour can have a lower sun % but a similar number of minutes in the sun. The cards show both figures.

For example, if the shortest route is 500 m and all in sun (score 1,500), a fully shaded detour is offered if it is under 1,500 m. If the shortest route is already fully shaded, nothing can beat it.

**Common reasons only the shortest route appears:**

- **The sun is down or very low.** Every section counts as shaded, so the shortest route is already 0% sun.
- **The shortest route is already the shadiest.**
- **No detour pays off.** On short trips, or where there is only one path, a detour adds more walking than it saves in sun.
- **The trip is outside Quezon City.** There is no building-height data there, so every route is about 100% "shade unknown", counted as sun, and none can beat the shortest.
- **It is around midday.** With the sun overhead, buildings cast short shadows. Mid-morning and mid-afternoon give more chances for a shadier route.

The weight of 3 is a design choice, not a PRD value. The PRD requires only that the shadier route has less sun exposure (F-04) and that weather and walkability never affect it. A higher weight accepts longer detours for shade. A lower one offers shadier routes less often but keeps them closer in length to the shortest.

### Testing location without a phone

In development, open `http://127.0.0.1:5173/?simulate-location`. Then use the browser console:
- `window.__shadesSetLocation(14.6407, 121.0748, 8)` sets the position (latitude, longitude, accuracy in metres).
- `window.__shadesDenyLocation()` simulates refused location permission.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /api/routes` | Takes `{start, destination, travel_time}` and returns the routes, sections, comparison, comfort window, weather and walkability. |
| `GET /api/weather?time=` | UV, temperature, humidity and heat index for the study area. Each reading is either available or not available. |
| `POST /api/places` | Takes `{q, near?}` and searches named places in the local OSM extract. |
| `POST /api/streets/nearest` | Takes `{latitude, longitude}` and returns the street section nearest to a tapped point, with its walkability. |
| `POST /api/streets/{way_id}/ratings` | Takes `{rating: 1..5}`. |
| `GET /api/covered` | Lists the sections that users have marked as covered. |
| `PUT` / `DELETE /api/covered/{edge_key}` | Marks or unmarks a section as covered. |

## Verification commands

Backend tests (from the repository root):

```powershell
python -m unittest discover -s backend -p 'test_*.py' -v
```

Frontend tests and build:

```powershell
Set-Location frontend
npm test
npm run build
```

Acceptance evidence, which uses live weather and prints a Markdown report:

```powershell
python backend\acceptance.py
```

## Data and scope

- The walking network is a bounded OpenStreetMap extract documented in `datasets/README.md`.
- Building heights come from the local 2026 GeoTIFF in `datasets/building-heights/`.
  - OSM building footprints that have no height in the raster are flagged as **shade unknown**.
  - Shade-unknown sections count as direct sun.
- Shade comes from buildings only. Trees, awnings and clouds are not modelled; a clear sky is assumed.
- Covered walkways count as shaded only where users have marked them.
- Walkability scores come only from user ratings. They never affect routing.
- Location is used only while the app is open: to set the start point, show your position and detect when you leave the route. It is never stored or logged.
- The prototype covers a Metro Manila bounding box and walking trips up to 10 km. Building heights exist only for Quezon City, so elsewhere shade is "unknown" and counts as sun. Map data is prebuilt into tiles; see `datasets/README.md` to rebuild it. It does not provide indoor routing, thermal comfort, heat-stress or health-risk predictions. The MRT/LRT train option (PRD F-16–F-19) is not built.
