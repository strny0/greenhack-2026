import type { StateFrame, State } from "../types";

export interface LineDelta {
  /** scenario loading − base loading, in percentage points (rounded 0.1). */
  deltaLoading: number;
  /** the line went out of service in the scenario (it was in service in base). */
  tripped: boolean;
  /** a notable positive mover (≥ MOVER_THRESHOLD pp more loaded). */
  mover: boolean;
}

export interface NodeDelta {
  /** the bus's state got worse in the scenario (e.g. ok → warn/alert). */
  worsened: boolean;
}

const SEV: Record<State, number> = { ok: 0, offline: 1, warn: 1, alert: 2 };

/** A line whose loading jumps by at least this many points reads as a "mover". */
export const MOVER_THRESHOLD = 8;

export function lineDeltas(
  base: StateFrame,
  scen: StateFrame,
): Record<string, LineDelta> {
  const baseById = new Map(base.lines.map((l) => [l.id, l]));
  const out: Record<string, LineDelta> = {};
  for (const l of scen.lines) {
    const b = baseById.get(l.id);
    const before = b?.loading_pct ?? null;
    const after = l.loading_pct ?? null;
    const delta = before != null && after != null ? after - before : 0;
    const tripped = !l.in_service && (b?.in_service ?? true);
    out[l.id] = {
      deltaLoading: Math.round(delta * 10) / 10,
      tripped,
      mover: delta >= MOVER_THRESHOLD,
    };
  }
  return out;
}

export function nodeDeltas(
  base: StateFrame,
  scen: StateFrame,
): Record<string, NodeDelta> {
  const baseById = new Map(base.nodes.map((n) => [n.id, n]));
  const out: Record<string, NodeDelta> = {};
  for (const n of scen.nodes) {
    const b = baseById.get(n.id);
    out[n.id] = { worsened: b ? SEV[n.state] > SEV[b.state] : false };
  }
  return out;
}
