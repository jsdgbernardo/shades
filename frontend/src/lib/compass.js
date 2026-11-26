// Which way the phone points, for the cone on the user's dot. The heading stays on the device:
// it is never sent or stored (PRD C-04).

import { isSimulated } from "./location.js";

const MIN_INTERVAL_MS = 100; // at most about 10 updates a second
const MIN_CHANGE_DEG = 2;
const SMOOTHING = 0.35; // share of each new reading that is taken in

const normalize = (degrees) => ((degrees % 360) + 360) % 360;

/** Smallest difference between two headings, in degrees (0 to 180). */
export function angleDiff(a, b) {
  const diff = Math.abs(normalize(a) - normalize(b));
  return diff > 180 ? 360 - diff : diff;
}

/**
 * Compass heading (degrees clockwise from north) from a device orientation event, or null when
 * the event has no absolute direction. `screenAngle` turns it for landscape screens.
 */
export function headingFromEvent(event, screenAngle = 0) {
  let heading = null;
  if (typeof event.webkitCompassHeading === "number" && event.webkitCompassHeading >= 0) {
    heading = event.webkitCompassHeading; // iPhone: already clockwise from north
  } else if (event.absolute && typeof event.alpha === "number") {
    heading = 360 - event.alpha; // alpha turns counterclockwise
  }
  return heading === null ? null : normalize(heading + screenAngle);
}

/** Moves `previous` part of the way to `next` along the shorter way round, so 359° to 1° never spins. */
export function smoothHeading(previous, next, factor = SMOOTHING) {
  if (previous === null || previous === undefined) return normalize(next);
  const x = Math.cos(previous * Math.PI / 180) * (1 - factor) + Math.cos(next * Math.PI / 180) * factor;
  const y = Math.sin(previous * Math.PI / 180) * (1 - factor) + Math.sin(next * Math.PI / 180) * factor;
  return normalize(Math.atan2(y, x) * 180 / Math.PI);
}

let permission = null;

/** iPhone only shows the compass after a permission prompt, which must come from a tap. Asks once. */
export function requestCompassPermission() {
  const request = typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission;
  if (!request || permission) return permission ?? Promise.resolve("granted");
  permission = request.call(DeviceOrientationEvent).catch(() => "denied");
  return permission;
}

/** Calls onHeading with a smoothed heading as it changes. Returns a function that stops it. */
export function watchHeading(onHeading) {
  if (typeof window === "undefined") return () => {};
  let smoothed = null;
  let reported = null;
  let lastTime = 0;
  const report = (raw) => {
    if (raw === null) return;
    smoothed = smoothHeading(smoothed, raw);
    const now = performance.now();
    if (now - lastTime < MIN_INTERVAL_MS) return;
    if (reported !== null && angleDiff(reported, smoothed) < MIN_CHANGE_DEG) return;
    lastTime = now;
    reported = smoothed;
    onHeading(Math.round(smoothed));
  };
  const screenAngle = () => window.screen?.orientation?.angle ?? window.orientation ?? 0;
  const onOrientation = (event) => report(headingFromEvent(event, screenAngle()));
  const onSimulated = (event) => {
    smoothed = null; // a simulated heading is exact
    reported = null;
    lastTime = 0;
    report(normalize(event.detail));
  };
  // Android Chrome gives a north-based alpha only on deviceorientationabsolute.
  const eventName = "ondeviceorientationabsolute" in window ? "deviceorientationabsolute" : "deviceorientation";
  window.addEventListener(eventName, onOrientation);
  if (isSimulated()) window.addEventListener("shades:heading", onSimulated);
  return () => {
    window.removeEventListener(eventName, onOrientation);
    window.removeEventListener("shades:heading", onSimulated);
  };
}
