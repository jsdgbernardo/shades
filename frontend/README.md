# Shades frontend

The frontend is a React/Vite mobile-first route planner for the Katipunan and Ateneo study area. On a desktop browser it is centered in a phone-sized canvas; at widths below 520px it expands to the full viewport.

## Design colors

The visual language follows the supplied mobile reference:

- **Paper** `#F8F6F1` — warm surfaces and the route sheet.
- **Ink** `#25302C` — primary text and controls.
- **Shade green** `#3D8D78` — shaded route sections and positive exposure results.
- **Sun orange** `#C96A21` — direct-sun sections, primary actions, and the active destination state.
- **Location blue** `#258FBE` — the current-location marker and start state.

Map tiles are provided by OpenStreetMap. Route requests are sent to `http://127.0.0.1:8000/api/routes`, matching the Python backend documented in the repository README.

## Run

```powershell
npm install
npm run dev -- --host 127.0.0.1
```
