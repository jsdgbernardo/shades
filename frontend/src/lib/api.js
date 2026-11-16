export const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export class ConnectionError extends Error {
  constructor() {
    super("No connection. Check your internet connection and try again.");
    this.name = "ConnectionError";
  }
}

async function request(path, options = {}) {
  if (typeof navigator !== "undefined" && navigator.onLine === false) throw new ConnectionError();
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    });
  } catch {
    throw new ConnectionError();
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Something went wrong. Please try again.");
  return payload;
}

export function fetchRoutes({ start, destination, travelTime }) {
  return request("/api/routes", {
    method: "POST",
    body: JSON.stringify({ start, destination, travel_time: travelTime }),
  });
}

export function fetchWeather(travelTime) {
  return request(`/api/weather?time=${encodeURIComponent(travelTime)}`);
}

export function searchPlaces(query) {
  return request(`/api/places?q=${encodeURIComponent(query)}`);
}

export function fetchNearestStreet(latitude, longitude) {
  return request(`/api/streets/nearest?lat=${latitude}&lon=${longitude}`);
}

export function rateStreet(wayId, rating) {
  return request(`/api/streets/${wayId}/ratings`, { method: "POST", body: JSON.stringify({ rating }) });
}

export function setCovered(edgeKey, covered) {
  return request(`/api/covered/${encodeURIComponent(edgeKey)}`, { method: covered ? "PUT" : "DELETE" });
}

export function fetchCovered() {
  return request("/api/covered");
}
