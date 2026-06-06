import { describe, expect, it } from "vitest";
import {
  clampWindowStart,
  datasetDayBounds,
  dateToKey,
  dayStartIndex,
  keyToDate,
  lastDayStart,
} from "./datetime";

// Fixture: 3 contiguous days, 24 hourly frames each (72 total).
// Day starts at indices 0, 24, 48.
const TS: string[] = [];
for (const day of ["2024-03-10", "2024-03-11", "2024-03-12"]) {
  for (let h = 0; h < 24; h++) {
    TS.push(`${day}T${String(h).padStart(2, "0")}:00:00`);
  }
}

describe("dateToKey / keyToDate", () => {
  it("round-trips a local date through a YYYY-MM-DD key", () => {
    expect(dateToKey(new Date(2024, 2, 11))).toBe("2024-03-11"); // month is 0-indexed
    expect(dateToKey(keyToDate("2024-03-11"))).toBe("2024-03-11");
  });
});

describe("dayStartIndex", () => {
  it("returns the first frame index of an exact day", () => {
    expect(dayStartIndex(TS, keyToDate("2024-03-10"))).toBe(0);
    expect(dayStartIndex(TS, keyToDate("2024-03-11"))).toBe(24);
    expect(dayStartIndex(TS, new Date(2024, 2, 12))).toBe(48);
  });
  it("falls back to the nearest available day-start when out of range", () => {
    expect(dayStartIndex(TS, keyToDate("2023-12-01"))).toBe(0); // before -> first day
    expect(dayStartIndex(TS, keyToDate("2024-09-20"))).toBe(48); // after -> last day
  });
});

describe("lastDayStart", () => {
  it("aligns the last index down to a 24h boundary", () => {
    expect(lastDayStart(72)).toBe(48);
    expect(lastDayStart(8760)).toBe(8736);
    expect(lastDayStart(0)).toBe(0);
  });
});

describe("clampWindowStart", () => {
  it("clamps to the valid day-start range", () => {
    expect(clampWindowStart(-24, 72)).toBe(0);
    expect(clampWindowStart(24, 72)).toBe(24);
    expect(clampWindowStart(100, 72)).toBe(48);
  });
});

describe("datasetDayBounds", () => {
  it("returns the first and last selectable day at local midnight", () => {
    const { first, last } = datasetDayBounds(TS);
    expect(dateToKey(first)).toBe("2024-03-10");
    expect(dateToKey(last)).toBe("2024-03-12");
  });
});
