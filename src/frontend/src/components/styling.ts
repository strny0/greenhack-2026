import type { NodeType, State } from "../types";

/**
 * Line-loading bands: the one source for both the line colours and the legend.
 * Normal stays grey, colour only where attention is needed (ISA-101 HMI). Amber
 * to red also step down in lightness, so they read for colour-blind operators,
 * and the agent's sea-glass highlight never collides with them.
 */
export const LOADING_BANDS: { from: number; to: number | null; color: string; label: string }[] = [
  { from: 0,   to: 50,   color: "#5a6a72", label: "normal" },
  { from: 50,  to: 80,   color: "#d9a441", label: "watch" },
  { from: 80,  to: 100,  color: "#ee7a3b", label: "act soon" },
  { from: 100, to: null, color: "#f0503c", label: "overloaded" },
];

/** Legend text for a band, e.g. "50 to 80%, watch". */
export function bandLabel(b: (typeof LOADING_BANDS)[number]): string {
  if (b.from === 0) return `Under ${b.to}%, ${b.label}`;
  if (b.to == null) return `Over ${b.from}%, ${b.label}`;
  return `${b.from} to ${b.to}%, ${b.label}`;
}

// Colour stops derived from the bands: a slight grey ramp inside "normal",
// then a hard step at each band edge, so a line is exactly its band's colour.
const STEP = 0.01;
export const LOADING_STOPS: { pct: number; color: string }[] = [
  { pct: 0, color: "#4a5961" },
  ...LOADING_BANDS.flatMap((b, i) =>
    i === 0
      ? [{ pct: b.to as number, color: b.color }]
      : [
          { pct: b.from + STEP, color: b.color },
          ...(b.to != null ? [{ pct: b.to, color: b.color }] : []),
        ],
  ),
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
