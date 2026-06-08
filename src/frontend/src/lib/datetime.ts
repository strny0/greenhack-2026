/**
 * Pure helpers mapping between calendar dates and indices into the backend's
 * flat, ascending, hourly `timestamps[]` list. Timestamps are naive ISO strings
 * like "2024-03-11T18:00:00" (no timezone); we compare on the date prefix and
 * build Dates from local calendar fields to avoid any timezone drift.
 */

/** "2024-03-11T18:00:00" -> "2024-03-11" */
function dayKey(timestamp: string): string {
  return timestamp.slice(0, 10);
}

/** Local Date -> "YYYY-MM-DD" using local calendar fields. */
export function dateToKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** "YYYY-MM-DD" -> local Date at midnight. */
export function keyToDate(key: string): Date {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/**
 * Index of the first frame on the same calendar day as `date`. If that day is
 * not present, returns the start index of the nearest available day (by absolute
 * day distance). Assumes `timestamps` is sorted ascending.
 */
export function dayStartIndex(timestamps: string[], date: Date): number {
  if (timestamps.length === 0) return 0;
  const targetKey = dateToKey(date);
  const exact = timestamps.findIndex((t) => dayKey(t) === targetKey);
  if (exact >= 0) return exact;

  const targetMs = keyToDate(targetKey).getTime();
  let bestIdx = 0;
  let bestDist = Infinity;
  for (let i = 0; i < timestamps.length; i++) {
    // only consider the first frame of each day
    if (i > 0 && dayKey(timestamps[i]) === dayKey(timestamps[i - 1])) continue;
    const dist = Math.abs(keyToDate(dayKey(timestamps[i])).getTime() - targetMs);
    if (dist < bestDist) {
      bestDist = dist;
      bestIdx = i;
    }
  }
  return bestIdx;
}

/** Index of the last day's start, aligning down to a 24-hour boundary. */
export function lastDayStart(total: number): number {
  if (total <= 0) return 0;
  return Math.floor((total - 1) / 24) * 24;
}

/** Clamp a day-start index to [0, lastDayStart(total)]. */
export function clampWindowStart(start: number, total: number): number {
  return Math.max(0, Math.min(start, lastDayStart(total)));
}

/** First and last selectable days (local midnight) for the calendar bounds. */
export function datasetDayBounds(timestamps: string[]): { first: Date; last: Date } {
  return {
    first: keyToDate(dayKey(timestamps[0])),
    last: keyToDate(dayKey(timestamps[timestamps.length - 1])),
  };
}
