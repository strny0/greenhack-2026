import { useEffect, useMemo, useRef, useState, MouseEvent, WheelEvent } from "react";
import type { Meta, StateFrame, GridLine, GridNode } from "../types";
import {
  CASING_COLOR,
  loadingColor,
  lineWidth,
  nodeRadius,
  STATE_STROKE_COLOR,
} from "./styling";
import type { Selection } from "./MapView";
import { formatGenTypes, labelOf, NODE_KIND_LABEL } from "@/lib/gridmeta";

// Classic SLD palette — single dark color for all bus bars; equipment type is
// communicated by the attached symbol (G in circle for generators, ↓ for loads,
// two-coil glyph mid-branch for transformers).
const BAR_COLOR = "#2d3a55";
const SYMBOL_COLOR = "#1a2233";
const SLACK_COLOR = "#b07cff";

interface Props {
  frame: StateFrame;
  meta: Meta;
  highlight: Set<string>;
  selected: Selection | null;
  onSelect: (s: Selection | null) => void;
  /** A "frame the camera here" request; the nonce re-triggers repeated jumps. */
  zoomTo: { kind: "node" | "line"; id: string; nonce: number } | null;
}

// SVG y grows down. The dataset y range is negative; smaller (more-negative)
// values lie on top of the IEEE-118 layout. Negating y per-element puts the
// expected top of the diagram at the top of the SVG.
function screenY(y: number): number {
  return -y;
}

// --- SLD primitives -----------------------------------------------------------

const BAR_THICKNESS = 8;     // schematic units; ~5px at default zoom
const ROUTE_OFFSET = 28;     // detour distance for same-y bus pairs
const PARALLEL_STAGGER = 14; // midY separation per parallel circuit

function circuitNum(lineId: string): number {
  const m = lineId.match(/_(\d+)$/);
  return m ? parseInt(m[1], 10) : 1;
}

// --- layout: distribute branch attachment points along each bus bar ----------

type Layout = {
  barLength: (nodeId: string) => number;
  attachX: (nodeId: string, lineId: string) => number;
};

function buildLayout(
  nodes: GridNode[],
  lines: GridLine[],
  coords: Record<string, [number, number]>,
): Layout {
  // for each bus, list incident branches with the "other" endpoint
  const incident = new Map<string, { lineId: string; other: string }[]>();
  for (const l of lines) {
    if (!coords[l.from_node] || !coords[l.to_node]) continue;
    if (!incident.has(l.from_node)) incident.set(l.from_node, []);
    if (!incident.has(l.to_node)) incident.set(l.to_node, []);
    incident.get(l.from_node)!.push({ lineId: l.id, other: l.to_node });
    incident.get(l.to_node)!.push({ lineId: l.id, other: l.from_node });
  }

  // sort each bus's branches left-to-right by the other endpoint's x,
  // then by lineId so parallel circuits get a deterministic order
  for (const list of incident.values()) {
    list.sort((a, b) => {
      const ca = coords[a.other];
      const cb = coords[b.other];
      const dx = (ca?.[0] ?? 0) - (cb?.[0] ?? 0);
      if (dx !== 0) return dx;
      return a.lineId.localeCompare(b.lineId);
    });
  }

  // bar length wants to scale with magnitude AND branch count, but never
  // exceed ~70% of the distance to the closest bus on the same row, or bars
  // collide. Same-row = y within Y_TOL units (bars share screen height).
  const magOf = new Map<string, number>();
  for (const n of nodes) magOf.set(n.id, Math.max(n.production_mw, n.consumption_mw, 0));

  const Y_TOL = 25;
  const MIN_BAR = 18;
  const MAX_BAR = 90;
  const ABS_GAP = 12; // guaranteed empty schematic units between adjacent bars

  function closestNeighborDx(busId: string): number {
    const ci = coords[busId];
    if (!ci) return MAX_BAR * 2;
    let best = Infinity;
    for (const m of nodes) {
      if (m.id === busId) continue;
      const cj = coords[m.id];
      if (!cj) continue;
      if (Math.abs(cj[1] - ci[1]) > Y_TOL) continue;
      const dx = Math.abs(cj[0] - ci[0]);
      if (dx > 0 && dx < best) best = dx;
    }
    return Number.isFinite(best) ? best : MAX_BAR * 2;
  }

  const barLen = new Map<string, number>();
  for (const n of nodes) {
    const baseLen = Math.max(24, Math.min(MAX_BAR, nodeRadius(magOf.get(n.id) ?? 0) * 4));
    const k = incident.get(n.id)?.length ?? 0;
    const byBranches = Math.max(24, k * 10);
    const desired = Math.max(baseLen, byBranches);
    // cap so that when both this bar and its closest same-row neighbour are
    // at their cap, the gap between their ends is exactly ABS_GAP.
    const cap = Math.max(MIN_BAR, closestNeighborDx(n.id) - ABS_GAP);
    barLen.set(n.id, Math.min(desired, cap));
  }

  // attachment x: distribute branches evenly along the bar, in the sorted order
  function attachX(busId: string, lineId: string): number {
    const list = incident.get(busId);
    const c = coords[busId];
    if (!list || !c) return c?.[0] ?? 0;
    if (list.length === 1) return c[0];
    const idx = list.findIndex((b) => b.lineId === lineId);
    if (idx < 0) return c[0];
    const len = barLen.get(busId) ?? 30;
    const t = (idx + 0.5) / list.length;
    return c[0] - len / 2 + t * len;
  }

  return {
    barLength: (id) => barLen.get(id) ?? 30,
    attachX,
  };
}

// halfway-Z orthogonal routing between two distinct attachment points
function routePath(
  ax: number, ay: number,
  bx: number, by: number,
  midOffset: number = 0,
): string {
  if (Math.abs(by - ay) < 1) {
    // same-y: detour perpendicular to the bars so the branch doesn't lie on them
    const y2 = ay + ROUTE_OFFSET + midOffset;
    return `M ${ax} ${ay} L ${ax} ${y2} L ${bx} ${y2} L ${bx} ${by}`;
  }
  if (Math.abs(bx - ax) < 1) {
    return `M ${ax} ${ay} L ${bx} ${by}`;
  }
  const midY = (ay + by) / 2 + midOffset;
  return `M ${ax} ${ay} L ${ax} ${midY} L ${bx} ${midY} L ${bx} ${by}`;
}

// --- component ----------------------------------------------------------------

type Tooltip = { x: number; y: number; html: string } | null;

export default function SldView({ frame, meta, highlight, selected, onSelect, zoomTo }: Props) {
  const bbox = meta.sld_bbox;
  const coords = meta.sld_coords;

  const layout = useMemo(
    () => buildLayout(frame.nodes, frame.lines, coords),
    [frame.nodes, frame.lines, coords],
  );

  // pre-compute region bounding boxes (R1/R2/R3 dashed groupings from the
  // dataset's `zone` field). Each box contains every bus in that zone, with
  // padding for symbols and the dashed border itself.
  const regions = useMemo(() => {
    const byZone = new Map<string, GridNode[]>();
    for (const n of frame.nodes) {
      if (!coords[n.id]) continue;
      const z = n.zone || "";
      if (!byZone.has(z)) byZone.set(z, []);
      byZone.get(z)!.push(n);
    }
    const SYM_MARGIN = 32; // room for gen/load symbols above/below bars
    const PAD = 28;
    return Array.from(byZone.entries())
      .filter(([z]) => z.length > 0)
      .map(([zone, ns]) => {
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        for (const n of ns) {
          const c = coords[n.id];
          const len = layout.barLength(n.id);
          const sy = screenY(c[1]);
          minX = Math.min(minX, c[0] - len / 2);
          maxX = Math.max(maxX, c[0] + len / 2);
          minY = Math.min(minY, sy - SYM_MARGIN);
          maxY = Math.max(maxY, sy + SYM_MARGIN);
        }
        return {
          zone,
          x: minX - PAD,
          y: minY - PAD,
          w: maxX - minX + 2 * PAD,
          h: maxY - minY + 2 * PAD,
        };
      })
      .sort((a, b) => a.zone.localeCompare(b.zone));
  }, [frame.nodes, coords, layout]);

  // pre-compute one set of geometric values per branch so every layer
  // (casing / halo / branch / selection) renders identical paths, and so we
  // can drop a transformer glyph at the path's horizontal midpoint
  const branchGeom = useMemo(() => {
    return frame.lines.map((l) => {
      const a = coords[l.from_node];
      const b = coords[l.to_node];
      if (!a || !b) return null;
      const ax = layout.attachX(l.from_node, l.id);
      const bx = layout.attachX(l.to_node, l.id);
      const ay = screenY(a[1]);
      const by = screenY(b[1]);
      const midOffset = (circuitNum(l.id) - 1) * PARALLEL_STAGGER;
      const sameY = Math.abs(by - ay) < 1;
      const midY = sameY ? ay + ROUTE_OFFSET + midOffset : (ay + by) / 2 + midOffset;
      const midX = (ax + bx) / 2;
      return { l, ax, ay, bx, by, midX, midY, d: routePath(ax, ay, bx, by, midOffset) };
    });
  }, [frame.lines, coords, layout]);

  const initial = useMemo(() => {
    const w = bbox.x_max - bbox.x_min;
    const h = bbox.y_max - bbox.y_min;
    const pad = Math.max(w, h) * 0.06;
    const sy_min = -bbox.y_max;
    return { x: bbox.x_min - pad, y: sy_min - pad, w: w + 2 * pad, h: h + 2 * pad };
  }, [bbox]);

  type Box = { x: number; y: number; w: number; h: number };
  const [view, setView] = useState<Box>(initial);
  const [tip, setTip] = useState<Tooltip>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  // viewBox tween. `viewRef` mirrors the committed view so an animation always
  // starts from where we actually are; `animRef` holds the in-flight rAF id so
  // a new jump or any direct interaction (wheel/drag) can interrupt it.
  const viewRef = useRef(view);
  viewRef.current = view;
  const animRef = useRef<number | null>(null);
  const cancelAnim = () => {
    if (animRef.current != null) {
      cancelAnimationFrame(animRef.current);
      animRef.current = null;
    }
  };
  // Smoothly fly the viewBox to `target`: pan the centre linearly while scaling
  // the size geometrically (so a zoom feels even, not lurching), eased out.
  const animateTo = (target: Box, duration = 600) => {
    cancelAnim();
    const start = viewRef.current;
    const t0 = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3); // easeOutCubic
    const step = (now: number) => {
      const k = ease(Math.min(1, (now - t0) / duration));
      const scx = start.x + start.w / 2, scy = start.y + start.h / 2;
      const tcx = target.x + target.w / 2, tcy = target.y + target.h / 2;
      const w = start.w * Math.pow(target.w / start.w, k);
      const h = start.h * Math.pow(target.h / start.h, k);
      const cx = scx + (tcx - scx) * k;
      const cy = scy + (tcy - scy) * k;
      setView({ x: cx - w / 2, y: cy - h / 2, w, h });
      animRef.current = k < 1 ? requestAnimationFrame(step) : null;
    };
    animRef.current = requestAnimationFrame(step);
  };
  // stop any tween when the component unmounts
  useEffect(() => cancelAnim, []);

  const lastBbox = useRef(bbox);
  if (lastBbox.current !== bbox) {
    lastBbox.current = bbox;
    setView(initial);
  }

  // frame the requested element (chat chip double-click / reticle) by flying the
  // viewBox to a tight box centred on it. Aspect ratio is taken from `initial`
  // so the on-screen zoom is consistent regardless of the current pan/zoom.
  useEffect(() => {
    if (!zoomTo) return;
    const aspect = initial.w / initial.h;
    let cx: number, cy: number, tw: number;
    if (zoomTo.kind === "node") {
      const c = coords[zoomTo.id];
      if (!c) return;
      cx = c[0];
      cy = screenY(c[1]);
      tw = initial.w / 6;
    } else {
      const g = branchGeom.find((x) => x?.l.id === zoomTo.id);
      if (!g) return;
      const minX = Math.min(g.ax, g.bx), maxX = Math.max(g.ax, g.bx);
      const minY = Math.min(g.ay, g.by, g.midY), maxY = Math.max(g.ay, g.by, g.midY);
      cx = (minX + maxX) / 2;
      cy = (minY + maxY) / 2;
      tw = Math.max(maxX - minX, (maxY - minY) * aspect, initial.w / 8) * 1.6;
    }
    const minSize = Math.max(initial.w, initial.h) * 0.05;
    const maxSize = Math.max(initial.w, initial.h) * 4;
    tw = Math.max(minSize, Math.min(maxSize, tw));
    const th = tw / aspect;
    animateTo({ x: cx - tw / 2, y: cy - th / 2, w: tw, h: th });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoomTo]);

  const setTipFor = (e: MouseEvent, html: string) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, html });
  };

  const onWheel = (e: WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    cancelAnim();
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const vx = view.x + (mx / rect.width) * view.w;
    const vy = view.y + (my / rect.height) * view.h;
    const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const minSize = Math.max(initial.w, initial.h) * 0.05;
    const maxSize = Math.max(initial.w, initial.h) * 4;
    const newW = Math.max(minSize, Math.min(maxSize, view.w * factor));
    const newH = Math.max(minSize, Math.min(maxSize, view.h * factor));
    const newX = vx - (mx / rect.width) * newW;
    const newY = vy - (my / rect.height) * newH;
    setView({ x: newX, y: newY, w: newW, h: newH });
  };

  const onMouseDown = (e: MouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    const tag = (e.target as Element).tagName;
    if (tag !== "rect" && tag !== "svg") return;
    cancelAnim();
    dragRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    (e.currentTarget as SVGSVGElement).classList.add("dragging");
  };
  const onMouseMove = (e: MouseEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const dx = ((e.clientX - drag.x) / rect.width) * view.w;
    const dy = ((e.clientY - drag.y) / rect.height) * view.h;
    setView((v) => ({ ...v, x: drag.vx - dx, y: drag.vy - dy }));
  };
  const endDrag = (e: MouseEvent<SVGSVGElement>) => {
    dragRef.current = null;
    e.currentTarget.classList.remove("dragging");
  };
  const onDoubleClick = (e: MouseEvent<SVGSVGElement>) => {
    const tag = (e.target as Element).tagName;
    if (tag !== "rect" && tag !== "svg") return;
    animateTo(initial);
  };

  const lineTip = (l: GridLine) =>
    `<b>${labelOf(l)}</b><br/>${l.loading_pct == null || l.loading_pct < 0 ? "out of service" : Math.round(l.loading_pct) + "% loaded"}`;
  const nodeTip = (n: GridNode) => {
    const role = n.is_slack ? "Slack bus" : NODE_KIND_LABEL[n.type];
    const gens = formatGenTypes(n.gen_types);
    return `<b>${labelOf(n)}</b><br/>${role}${gens ? ` · ${gens}` : ""} · ${(n.vm_pu ?? 0).toFixed(3)} p.u.`;
  };

  const selectedLineGeom =
    selected?.kind === "line" ? branchGeom.find((g) => g?.l.id === selected.id) ?? null : null;

  return (
    <div className="sld-wrap" ref={wrapRef}>
      <svg
        className="sld-svg"
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        preserveAspectRatio="xMidYMid meet"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={(e) => {
          endDrag(e);
          setTip(null);
        }}
        onDoubleClick={onDoubleClick}
      >
        <rect x={initial.x} y={initial.y} width={initial.w * 10} height={initial.h * 10} fill="#f5f6f8" />

        {/* region groupings — dashed rounded rectangles + label */}
        <g style={{ pointerEvents: "none" }}>
          {regions.map((r) => (
            <g key={`region-${r.zone}`}>
              <rect
                x={r.x}
                y={r.y}
                width={r.w}
                height={r.h}
                rx={16}
                ry={16}
                fill="none"
                stroke="#8a99b0"
                strokeWidth={1.5}
                strokeDasharray="10 6"
                strokeOpacity={0.65}
              />
              <text
                x={r.x + 14}
                y={r.y + 24}
                fontSize={20}
                fontWeight={700}
                fill="#8a99b0"
                fillOpacity={0.7}
                fontFamily="sans-serif"
                letterSpacing={1.5}
              >
                {`Region ${r.zone.toUpperCase()}`}
              </text>
            </g>
          ))}
        </g>

        {/* line casing — dark wide stroke beneath the colored branch */}
        <g>
          {branchGeom.map((g) => {
            if (!g) return null;
            const w = lineWidth(g.l.loading_pct, g.l.kind) + 3;
            return (
              <path
                key={`c-${g.l.id}`}
                d={g.d}
                fill="none"
                stroke={CASING_COLOR}
                strokeOpacity={0.75}
                strokeWidth={w}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          })}
        </g>

        {/* highlight halo for lines */}
        <g>
          {branchGeom.map((g) => {
            if (!g || !highlight.has(g.l.id)) return null;
            return (
              <path
                key={`h-${g.l.id}`}
                d={g.d}
                fill="none"
                stroke="#ffd84d"
                strokeOpacity={0.7}
                strokeWidth={14}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            );
          })}
        </g>

        {/* branches — colored by loading, orthogonal routed */}
        <g>
          {branchGeom.map((g) => {
            if (!g) return null;
            const l = g.l;
            return (
              <path
                key={`l-${l.id}`}
                d={g.d}
                fill="none"
                stroke={loadingColor(l.loading_pct)}
                strokeWidth={lineWidth(l.loading_pct, l.kind)}
                strokeOpacity={l.in_service ? 1 : 0.3}
                strokeDasharray={l.in_service ? undefined : "6 4"}
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ cursor: "pointer" }}
                onMouseEnter={(e) => setTipFor(e, lineTip(l))}
                onMouseMove={(e) => setTipFor(e, lineTip(l))}
                onMouseLeave={() => setTip(null)}
                onClick={() => onSelect({ kind: "line", id: l.id })}
              />
            );
          })}
        </g>

        {/* selection ring for selected line */}
        {selectedLineGeom && (
          <path
            d={selectedLineGeom.d}
            fill="none"
            stroke="#2f81f7"
            strokeOpacity={0.55}
            strokeWidth={lineWidth(selectedLineGeom.l.loading_pct, selectedLineGeom.l.kind) + 8}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ pointerEvents: "none" }}
          />
        )}

        {/* bus bar highlight halo (yellow glow beneath the bar) */}
        <g>
          {frame.nodes.map((n) => {
            if (!highlight.has(n.id)) return null;
            const c = coords[n.id];
            if (!c) return null;
            const len = layout.barLength(n.id);
            const sy = screenY(c[1]);
            return (
              <rect
                key={`nh-${n.id}`}
                x={c[0] - len / 2 - 8}
                y={sy - BAR_THICKNESS / 2 - 8}
                width={len + 16}
                height={BAR_THICKNESS + 16}
                rx={4}
                fill="#ffd84d"
                fillOpacity={0.55}
              />
            );
          })}
        </g>

        {/* bus state halo (warn/alert wider stroke beneath bar) */}
        <g>
          {frame.nodes.map((n) => {
            if (n.state === "ok") return null;
            const c = coords[n.id];
            if (!c) return null;
            const len = layout.barLength(n.id);
            const sy = screenY(c[1]);
            return (
              <line
                key={`ns-${n.id}`}
                x1={c[0] - len / 2}
                y1={sy}
                x2={c[0] + len / 2}
                y2={sy}
                stroke={STATE_STROKE_COLOR[n.state]}
                strokeOpacity={0.85}
                strokeWidth={BAR_THICKNESS + 6}
                strokeLinecap="round"
              />
            );
          })}
        </g>

        {/* transformer glyph — two overlapping circles at the branch midpoint */}
        <g>
          {branchGeom.map((g) => {
            if (!g || g.l.kind !== "trafo") return null;
            const r = 5;
            return (
              <g key={`tr-${g.l.id}`} style={{ pointerEvents: "none" }}>
                <circle cx={g.midX - r * 0.7} cy={g.midY} r={r} fill="#ffffff" stroke={SYMBOL_COLOR} strokeWidth={1.4} />
                <circle cx={g.midX + r * 0.7} cy={g.midY} r={r} fill="#ffffff" stroke={SYMBOL_COLOR} strokeWidth={1.4} fillOpacity={0} />
              </g>
            );
          })}
        </g>

        {/* bus bars — classic SLD primitive, uniform dark stroke */}
        <g>
          {frame.nodes.map((n) => {
            const c = coords[n.id];
            if (!c) return null;
            const len = layout.barLength(n.id);
            const sy = screenY(c[1]);
            return (
              <line
                key={`n-${n.id}`}
                x1={c[0] - len / 2}
                y1={sy}
                x2={c[0] + len / 2}
                y2={sy}
                stroke={BAR_COLOR}
                strokeWidth={BAR_THICKNESS}
                strokeLinecap="round"
                style={{ cursor: "pointer" }}
                onMouseEnter={(e) => setTipFor(e, nodeTip(n))}
                onMouseMove={(e) => setTipFor(e, nodeTip(n))}
                onMouseLeave={() => setTip(null)}
                onClick={() => onSelect({ kind: "node", id: n.id })}
              />
            );
          })}
        </g>

        {/* equipment symbols: G in circle above (gen/slack), ↓ below (load) */}
        <g>
          {frame.nodes.map((n) => {
            const c = coords[n.id];
            if (!c) return null;
            const x = c[0];
            const sy = screenY(c[1]);
            const showGen = n.n_gens > 0 || n.type === "slack" || n.type === "generation";
            const showLoad = n.n_loads > 0 || n.type === "load";
            const isSlack = n.is_slack || n.type === "slack";
            return (
              <g key={`sym-${n.id}`} style={{ pointerEvents: "none" }}>
                {showGen && (
                  <>
                    <line
                      x1={x}
                      y1={sy - BAR_THICKNESS / 2}
                      x2={x}
                      y2={sy - 16}
                      stroke={SYMBOL_COLOR}
                      strokeWidth={1.4}
                    />
                    <circle
                      cx={x}
                      cy={sy - 24}
                      r={8}
                      fill={isSlack ? SLACK_COLOR : "#ffffff"}
                      stroke={SYMBOL_COLOR}
                      strokeWidth={1.4}
                    />
                    <text
                      x={x}
                      y={sy - 24}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize={11}
                      fontWeight={700}
                      fill={isSlack ? "#ffffff" : SYMBOL_COLOR}
                      fontFamily="serif"
                    >
                      {isSlack ? "S" : "G"}
                    </text>
                  </>
                )}
                {showLoad && (
                  <>
                    <line
                      x1={x}
                      y1={sy + BAR_THICKNESS / 2}
                      x2={x}
                      y2={sy + 14}
                      stroke={SYMBOL_COLOR}
                      strokeWidth={1.4}
                    />
                    <polygon
                      points={`${x - 5},${sy + 14} ${x + 5},${sy + 14} ${x},${sy + 24}`}
                      fill={SYMBOL_COLOR}
                    />
                  </>
                )}
              </g>
            );
          })}
        </g>

        {/* selection ring for selected bus (rectangle around the bar) */}
        {selected?.kind === "node" &&
          (() => {
            const n = frame.nodes.find((x) => x.id === selected.id);
            if (!n) return null;
            const c = coords[n.id];
            if (!c) return null;
            const len = layout.barLength(n.id);
            const sy = screenY(c[1]);
            return (
              <rect
                x={c[0] - len / 2 - 4}
                y={sy - BAR_THICKNESS / 2 - 4}
                width={len + 8}
                height={BAR_THICKNESS + 8}
                rx={3}
                fill="none"
                stroke="#2f81f7"
                strokeWidth={2.5}
                style={{ pointerEvents: "none" }}
              />
            );
          })()}
      </svg>

      {tip && (
        <div className="sld-tooltip" style={{ left: tip.x, top: tip.y }} dangerouslySetInnerHTML={{ __html: tip.html }} />
      )}
    </div>
  );
}
