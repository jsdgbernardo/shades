const pad = (value) => String(value).padStart(2, "0");

/** Local "YYYY-MM-DDTHH:mm" for a datetime-local input (not UTC). */
export function toInputValue(date = new Date()) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** "YYYY-MM-DDTHH:mm" read as device-local time -> ISO string with the device's UTC offset. */
export function toOffsetIso(inputValue) {
  const date = new Date(inputValue);
  if (Number.isNaN(date.getTime())) return null;
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const hours = pad(Math.floor(Math.abs(offset) / 60));
  const minutes = pad(Math.abs(offset) % 60);
  return `${inputValue.slice(0, 16)}:00${sign}${hours}:${minutes}`;
}

/** Clock time such as "3:30 PM" for an ISO string or Date. */
export function formatClock(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** True when the input value is within a minute of the current time. */
export function isNow(inputValue, now = new Date()) {
  const date = new Date(inputValue);
  return Math.abs(date.getTime() - now.getTime()) < 60_000 * 2;
}
