import { describe, expect, it } from "vitest";
import { LOADING_BANDS, LOADING_STOPS, bandLabel, loadingColor } from "./styling";

// loadingColor returns "rgb(r, g, b)" when it interpolates; compare as hex.
const hex = (c: string) => {
  const m = c.match(/^rgb\((\d+), (\d+), (\d+)\)$/);
  return m ? "#" + m.slice(1).map((n) => Number(n).toString(16).padStart(2, "0")).join("") : c;
};

describe("loading bands", () => {
  it("colours each line with its band's colour", () => {
    expect(hex(loadingColor(50))).toBe("#5a6a72");
    expect(hex(loadingColor(51))).toBe("#d9a441");
    expect(hex(loadingColor(80))).toBe("#d9a441");
    expect(hex(loadingColor(81))).toBe("#ee7a3b");
    expect(hex(loadingColor(100))).toBe("#ee7a3b");
    expect(hex(loadingColor(130))).toBe("#f0503c");
  });

  it("keeps the colour stops strictly ascending for the map", () => {
    for (let i = 1; i < LOADING_STOPS.length; i++) {
      expect(LOADING_STOPS[i].pct).toBeGreaterThan(LOADING_STOPS[i - 1].pct);
    }
  });

  it("labels the legend from the same thresholds", () => {
    expect(LOADING_BANDS.map(bandLabel)).toEqual([
      "Under 50%, normal",
      "50 to 80%, watch",
      "80 to 100%, act soon",
      "Over 100%, overloaded",
    ]);
  });
});
