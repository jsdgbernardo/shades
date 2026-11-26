# Field tests

These checks need a phone, a second device or a real walk, so the automated tests can't cover them. Each section names the PRD requirement, the steps, what counts as a pass, and a table for results. When a section is done, copy its results into a dated LOG.md entry.

**Setup**

- **Site:** https://shades-jsb.vercel.app/ (production, with the Turso database).
- **Timing readout:** add `?timing` to the address to show it under the top cards. It shows:
  - **Routes**: tapping **Find routes** until the routes are drawn.
  - **Fix→figures**: a GPS update until the walk figures are on screen.

  The timing stays on the phone and is never sent.
- **Record** the phone model, browser, and network (mobile data or Wi-Fi) for every session.
- **Real data:** ratings and covered marks are shared with everyone. Remove test marks afterwards; remove test ratings with **Remove** in the street card.

---

## P-01: routes within 10 s on mobile data

1. Turn Wi-Fi off. Open `https://shades-jsb.vercel.app/?timing`.
2. Run 20 trips across Metro Manila, mixing short (under 1 km), medium (2–5 km) and long (5–10 km) ones, inside and outside Quezon City.
3. For each trip, tap **Find routes** and note the **Routes** figure.

**Pass:** at least 18 of 20 under 10 s. The readout's "over 10 s" count gives the total.

| # | From → to | Distance | Seconds | Routes shown |
| --- | --- | --- | --- | --- |
| 1 | | | | |
| … | | | | |
| 20 | | | | |

The first request after a quiet period includes the server starting up. Note which trip that was.

## P-02: walk figures update within 2 s

1. With `?timing`, start a walk on a route and walk about 20 position updates (a few minutes).
2. Read **Fix→figures** at the end.

**Pass:** at least 19 of 20 updates within 2 s ("0 or 1 of 20 over 2 s").

| Date | Phone | Updates | Slowest | Over 2 s |
| --- | --- | --- | --- | --- |
| | | | | |

## F-13 and arrival: the live walk

1. Start a walk with GPS on. The navigation banner and bar should appear.
2. Check that minutes left, distance left and sun ahead go down as you walk.
3. Walk to the destination. "You've arrived" should appear about 30 m before it, with up to 3 streets to rate.

**Pass:** the figures go down as you walk, and the arrival card appears near the end.

| Date | Route | Figures went down | Arrival distance | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

## F-14: leaving the route

1. During a walk, stand about 10 m off the route, then walk to about 50 m off it.
2. At 10 m: no prompt. At 50 m: the prompt "About … m off the route. Recalculate from here?" appears.
3. Tap **Keep** once. The route shouldn't change.
4. Leave again and tap **Recalculate**. A new route should start from where you are.

**Pass:** no prompt at 10 m, a prompt at 50 m, and the route changes only after **Recalculate**.

| Date | 10 m: prompt? | 50 m: prompt? | Keep kept route | Recalculate worked |
| --- | --- | --- | --- | --- |
| | | | | |

## S-12 and E-04: location permission and accuracy

1. **Allow** location on first open: the origin shows "Your Location", and the blue dot appears.
2. In the browser's site settings, **block** location and reload: the origin says "Origin" and you can still search for a start.
3. Indoors or in a weak signal spot: note whether "Location too imprecise" appears instead of a wrong position.

| Date | Allowed: start set | Blocked: can search | Weak signal message |
| --- | --- | --- | --- |
| | | | |

## D-03: saved and shared after a restart

1. **Phone A:** rate a street (tap it on the map) and mark a short stretch as covered.
2. Redeploy the site: Vercel → Deployments → **Redeploy** on the latest one. Wait until it's live.
3. **Phone B** (or another browser): open the same street. The rating count and the covered mark should be there.
4. On phone A, tap **Remove** next to "Your rating" and turn the covered mark off. Check phone B again.

**Pass:** phone B sees both after the redeploy, and both are gone after removing.

| Date | B sees rating | B sees mark | Both removed |
| --- | --- | --- | --- |
| | | | |

## C-04: no location in logs or storage

1. After a test walk, open Vercel → the project → **Logs** for the last hour.
2. Search for `14.` and `121.`
3. In Turso, look at the `ratings` and `covered_marks` tables.

**Pass:**
- Log lines show paths only, such as `/api/routes` and `/api/places`, with no coordinates in the request paths or search params.
- The tables hold only street ids, edge keys and dates: no coordinates and no times.

| Date | Coordinates in logs? | Coordinates or times in tables? |
| --- | --- | --- |
| | | |

## Newer features, quick checks on a phone

| Check | What to do | Pass |
| --- | --- | --- |
| Heading cone | Turn around with the app open | The cone turns with you. On iPhone, the permission prompt appears on the first locate or Start tap. |
| Rotate and Re-center | Twist with two fingers; drag the map during a walk | The map rotates; **Re-center** appears and brings it back. |
| Choose on map | Origin or Destination → **Choose on map**, drag, **Set** | The pin's street name shows, and the field reads "Pinned · …". |
| Covered here | Tap it under a covered walkway during a walk | "Marked as covered · Undo" appears. **Undo** removes the mark. |
| Rate after walk | Finish a walk | Up to 3 streets to rate. A second walk doesn't ask about the same streets. |
| Change rating | Rate a street twice in its card | "Your rating" shows the new number, and the rating count doesn't go up. |
| Home screen | Add to Home Screen, open from the icon | Opens full-screen. |
| Battery | Leave the app open for 15 min | Note the battery drop. |
