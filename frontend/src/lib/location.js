// Device location, used only in the browser while the app is open (PRD C-04, C-06).
// Positions are never stored or sent anywhere except as the start of a route request.

export const MAX_ACCURACY_METERS = 50;

/**
 * Development-only simulated location, for testing without a phone.
 * Open the app with ?simulate-location, then call
 * window.__shadesSetLocation(latitude, longitude, accuracy) or window.__shadesDenyLocation().
 */
function simulatedProvider() {
  const watchers = new Map();
  let current = null;
  let denied = false;
  let nextId = 1;
  const emit = () => watchers.forEach(({ success, failure }) => {
    if (denied) failure?.({ code: 1, PERMISSION_DENIED: 1 });
    else if (current) success(current);
  });
  window.__shadesSetLocation = (latitude, longitude, accuracy = 8) => {
    denied = false;
    current = { coords: { latitude, longitude, accuracy }, timestamp: Date.now() };
    emit();
  };
  window.__shadesDenyLocation = () => { denied = true; emit(); };
  return {
    getCurrentPosition(success, failure) {
      setTimeout(() => {
        if (denied) failure?.({ code: 1 });
        else if (current) success(current);
        else failure?.({ code: 2 });
      }, 50);
    },
    watchPosition(success, failure) {
      const id = nextId++;
      watchers.set(id, { success, failure });
      setTimeout(() => {
        if (denied) failure?.({ code: 1 });
        else if (current) success(current);
      }, 0);
      return id;
    },
    clearWatch(id) { watchers.delete(id); },
  };
}

let provider = null;

export function geolocation() {
  if (provider) return provider;
  const simulate = import.meta.env.DEV && typeof window !== "undefined" && new URLSearchParams(window.location.search).has("simulate-location");
  provider = simulate ? simulatedProvider() : (typeof navigator !== "undefined" ? navigator.geolocation : null);
  return provider;
}

/** Message for a failed or imprecise location (PRD E-04). */
export function locationProblem(error) {
  if (!error) return null;
  if (error.code === 1) return "Location access denied";
  if (error.code === "accuracy") return `Location too imprecise (±${Math.round(error.accuracy)} m)`;
  if (error.code === "outside") return "You are outside the test area";
  return "Location unavailable";
}
