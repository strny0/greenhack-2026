import { describe, expect, it } from "vitest";
import type { GridLine, GridNode, StateFrame } from "../types";
import { lineDeltas, nodeDeltas, MOVER_THRESHOLD } from "./simdelta";

const line = (id: string, loading: number | null, inService = true): GridLine =>
  ({
    id,
    name: id,
    label: id,
    from_node: "A",
    to_node: "B",
    kind: "line",
    max_i_ka: 1,
    loading_pct: loading,
    p_from_mw: null,
    p_to_mw: null,
    i_ka: null,
    in_service: inService,
    state: "ok",
  }) as GridLine;

const node = (id: string, state: GridNode["state"]): GridNode =>
  ({ id, name: id, label: id, type: "load", state } as unknown as GridNode);

const frame = (lines: GridLine[], nodes: GridNode[]): StateFrame =>
  ({ timestamp: "t", summary: {} as any, lines, nodes }) as StateFrame;

describe("lineDeltas", () => {
  const base = frame([line("L1", 60), line("L2", 40), line("L3", 30)], []);
  const scen = frame(
    [line("L1", 104), line("L2", 43), line("L3", 30, false)],
    [],
  );
  const d = lineDeltas(base, scen);

  it("computes signed delta loading", () => {
    expect(d.L1.deltaLoading).toBe(44);
    expect(d.L2.deltaLoading).toBe(3);
  });

  it("flags movers at or above the threshold", () => {
    expect(MOVER_THRESHOLD).toBe(8);
    expect(d.L1.mover).toBe(true); // +44 pp
    expect(d.L2.mover).toBe(false); // +3 pp
  });

  it("flags a line that went out of service as tripped", () => {
    expect(d.L3.tripped).toBe(true);
    expect(d.L1.tripped).toBe(false);
  });
});

describe("nodeDeltas", () => {
  it("flags buses whose state worsened", () => {
    const base = frame([], [node("N1", "ok"), node("N2", "warn"), node("N3", "alert")]);
    const scen = frame([], [node("N1", "alert"), node("N2", "warn"), node("N3", "alert")]);
    const d = nodeDeltas(base, scen);
    expect(d.N1.worsened).toBe(true); // ok -> alert
    expect(d.N2.worsened).toBe(false); // unchanged
    expect(d.N3.worsened).toBe(false); // already alert
  });
});
