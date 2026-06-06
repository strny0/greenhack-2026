// Shared helpers for the continuous deviation-risk surface (ribbon + alerts panel).
//
// The risk ribbon is a unified severity string: each hour's mark combines the grid
// alerts/warnings already derived client-side from the solved frame (line loading +
// voltage) with the precomputed plan-deviation risk tier. These helpers keep that
// combination in one place so the TopBar ribbon and the Sidebar alerts panel agree.
import type { DeviationRecord, Meta, RiskTier, StateFrame } from "../types";

export type GridSeverity = "alert" | "warn" | null;

/** Worst grid condition in a solved frame — mirrors the Sidebar `alerts` memo. */
export function frameSeverity(frame: StateFrame, meta: Meta): GridSeverity {
  const warn = meta.thresholds.line_loading_warn ?? 75;
  const alert = meta.thresholds.line_loading_alert ?? 90;
  let sev: GridSeverity = null;
  for (const l of frame.lines) {
    if (l.loading_pct == null) continue;
    if (l.loading_pct >= alert) return "alert";
    if (l.loading_pct >= warn) sev = "warn";
  }
  for (const n of frame.nodes) {
    if (n.state === "alert") return "alert";
    if (n.state === "warn") sev = sev ?? "warn";
  }
  return sev;
}

/** Unified 0..3 severity level (0 none, 1 low, 2 medium, 3 high). */
export type Level = 0 | 1 | 2 | 3;

const TIER_LEVEL: Record<RiskTier, Level> = { none: 0, low: 1, medium: 2, high: 3 };

function gridLevel(sev: GridSeverity): Level {
  return sev === "alert" ? 3 : sev === "warn" ? 2 : 0;
}

export function tierLevel(tier: RiskTier | undefined): Level {
  return tier ? TIER_LEVEL[tier] : 0;
}

/** Combined ribbon level for an hour: max of grid severity and deviation tier. */
export function combinedLevel(
  frame: StateFrame,
  dev: DeviationRecord | null | undefined,
  meta: Meta,
): Level {
  return Math.max(gridLevel(frameSeverity(frame, meta)), tierLevel(dev?.risk_tier)) as Level;
}

/** Fill colour for a ribbon stripe at each level (transparent when none). */
export const LEVEL_FILL: Record<Level, string> = {
  0: "transparent",
  1: "rgba(245, 158, 11, 0.35)", // faint amber — low
  2: "rgb(245, 158, 11)", // amber — medium / warn
  3: "rgb(239, 68, 68)", // red — high / alert
};

/** Map a deviation risk tier to the Sidebar `Pill` tone vocabulary. */
export function tierTone(tier: RiskTier): "alert" | "warn" | "ok" | "crit" {
  return tier === "high" ? "alert" : tier === "medium" ? "warn" : tier === "low" ? "ok" : "ok";
}
