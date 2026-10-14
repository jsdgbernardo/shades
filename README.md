# Shades

Shade-optimized walking route prototype for the Katipunan and Ateneo de Manila University area.

## Prerequisites

- Python 3.10 or newer
- Node.js 20 or newer and npm
- Internet access for OpenStreetMap map tiles and live Open-Meteo UV context

The application does not require an API key. The walking network and building-height raster used by the prototype are already stored in `datasets/`.

## Launch the application

Run the backend and frontend in two separate PowerShell terminals from the repository root.

### 1. Start the Python API

```powershell
python backend\app.py
```

The API runs at `http://127.0.0.1:8000`.

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

Open `http://127.0.0.1:5173/` in a browser.

## Use the prototype

1. Click the map once to choose the start point.
2. Click the map again to choose the destination.
3. Select a travel time and click **Preview route**.
4. Compare the two generated walking routes in the route drawer.
5. Click a route on the map or in the drawer to view its details.
6. Use **Reset selection** to choose new points.

The map theme button changes the entire application between dark and light mode.

## Verification commands

Run backend tests from the repository root:

```powershell
python -m unittest discover -s backend -p 'test_*.py' -v
```

Build the frontend:

```powershell
Set-Location frontend
npm run build
```

## Data and scope

- The walking network is a bounded OpenStreetMap extract documented in `datasets/README.md`.
- Building heights come from the local 2026 GeoTIFF in `datasets/building-heights/`.
- UV Index is requested at runtime from Open-Meteo and is shown only as contextual information, not as a shade measurement.
- The prototype is limited to the ADMU/Katipunan bounding box and does not provide continuous location tracking, indoor routing, general walkability ratings, thermal comfort, heat-stress, or health-risk predictions.