import type { NodeType, State } from "../types";

export const LOADING_STOPS: { pct: number; color: string }[] = [
  { pct: 0,   color: "#2ecc71" },
  { pct: 50,  color: "#9acd32" },
  { pct: 75,  color: "#f5b915" },
  { pct: 90,  color: "#ff7a45" },
  { pct: 110, color: "#ff4d4f" },
];

export const OUT_OF_SERVICE_COLOR = "#5a6677";
export const CASING_COLOR = "#05080f";

export const NODE_TYPE_COLOR: Record<NodeType, string> = {
  generation: "#2f81f7",
  load: "#e8833a",
  slack: "#b07cff",
  substation: "#6b7a90",
};

export const STATE_STROKE_COLOR: Record<State, string> = {
  ok: "#0a0e16",
  warn: "#f5b915",
  alert: "#ff4d4f",
  offline: "#5a6677",
};

export function loadingColor(pct: number | null | undefined): string {
  if (pct == null || pct < 0) return OUT_OF_SERVICE_COLOR;
  const stops = LOADING_STOPS;
  if (pct <= stops[0].pct) return stops[0].color;
  for (let i = 1; i < stops.length; i++) {
    if (pct <= stops[i].pct) {
      const a = stops[i - 1];
      const b = stops[i];
      const t = (pct - a.pct) / (b.pct - a.pct);
      return mix(a.color, b.color, t);
    }
  }
  return stops[stops.length - 1].color;
}

export function lineWidth(pct: number | null | undefined, kind: "line" | "trafo"): number {
  if (kind === "trafo") return 2.5;
  if (pct == null) return 2.6;
  return 2.6 + (Math.min(Math.max(pct, 0), 100) / 100) * (6 - 2.6);
}

export function nodeRadius(magMw: number): number {
  if (magMw <= 0) return 4;
  if (magMw >= 2000) return 15;
  if (magMw <= 500) return 4 + (magMw / 500) * (9 - 4);
  return 9 + ((magMw - 500) / 1500) * (15 - 9);
}

export function nodeColor(type: NodeType): string {
  return NODE_TYPE_COLOR[type] ?? NODE_TYPE_COLOR.substation;
}

export function nodeStrokeColor(state: State): string {
  return STATE_STROKE_COLOR[state] ?? STATE_STROKE_COLOR.ok;
}

export function nodeStrokeWidth(state: State): number {
  if (state === "alert") return 3;
  if (state === "warn") return 2;
  return 1;
}

// --- internal -----------------------------------------------------------------

function mix(a: string, b: string, t: number): string {
  const ah = hex(a);
  const bh = hex(b);
  const r = Math.round(ah[0] + (bh[0] - ah[0]) * t);
  const g = Math.round(ah[1] + (bh[1] - ah[1]) * t);
  const bl = Math.round(ah[2] + (bh[2] - ah[2]) * t);
  return `rgb(${r}, ${g}, ${bl})`;
}

function hex(s: string): [number, number, number] {
  const h = s.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
