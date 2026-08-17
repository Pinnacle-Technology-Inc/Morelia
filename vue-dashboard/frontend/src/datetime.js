export const CENTRAL_TIME_ZONE = "America/Chicago";

const EXPLICIT_TIME_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const ISO_DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/** Parse API datetimes as UTC when SQLite has removed their timezone suffix. */
export function parseApiTimestamp(value) {
  if (value instanceof Date) return new Date(value.getTime());
  if (typeof value === "number") return new Date(value);
  if (typeof value !== "string" || !value.trim()) return new Date(Number.NaN);

  const timestamp = value.trim();
  const normalized = ISO_DATE_TIME.test(timestamp) && !EXPLICIT_TIME_ZONE.test(timestamp)
    ? `${timestamp}Z`
    : timestamp;
  return new Date(normalized);
}

export function timestampMs(value) {
  const timestamp = parseApiTimestamp(value).getTime();
  return Number.isNaN(timestamp) ? null : timestamp;
}

export function formatCentralTimestamp(value, options = {}) {
  const { fallback = "—", ...formatOptions } = options;
  const timestamp = parseApiTimestamp(value);
  if (Number.isNaN(timestamp.getTime())) return fallback;

  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
    ...formatOptions,
    timeZone: CENTRAL_TIME_ZONE,
  }).format(timestamp);
}

export function formatCentralDate(value, options = {}) {
  return formatCentralTimestamp(value, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: undefined,
    minute: undefined,
    second: undefined,
    timeZoneName: undefined,
    ...options,
  });
}

export function formatCentralTime(value, options = {}) {
  return formatCentralTimestamp(value, {
    year: undefined,
    month: undefined,
    day: undefined,
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
    ...options,
  });
}
