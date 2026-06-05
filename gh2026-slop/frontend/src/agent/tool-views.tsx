"use client";

import { memo, useContext, useState, type ReactNode } from "react";
import {
  ActivityIcon,
  ChevronDownIcon,
  CircleIcon,
  GaugeIcon,
  ListOrderedIcon,
  LoaderIcon,
  SearchIcon,
  TriangleAlertIcon,
  WaypointsIcon,
  type LucideIcon,
} from "lucide-react";
import type {
  ToolCallMessagePartComponent,
  ToolCallMessagePartStatus,
} from "@assistant-ui/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { loadingColor, NODE_TYPE_COLOR, STATE_STROKE_COLOR } from "@/components/styling";
import { GridRefContext, type GridKind } from "@/agent/grid-refs";

/**
 * Domain-aware renderers for the dispatcher agent's tool calls.
 *
 * The chat used to dump every tool result as raw JSON. Each tool here has a
 * known, typed shape, so we render a purpose-built mini-view instead: the
 * collapsed header carries the answer (a one-liner), expanding reveals a small
 * visual (gauge / ranked bars / sparkline / neighbour chips), and the raw JSON
 * stays available behind a "Raw" toggle for power users.
 *
 * Unknown tools fall through to <ToolFallback> (see thread.tsx). Wiring to the
 * map (focus + select an element) is reused from grid-refs via GridRefContext.
 */

// --- small helpers -----------------------------------------------------------

/** Branch ids start with branch/line/trafo; everything else (bus_*) is a node. */
function kindOf(id: string): GridKind {
  return /^bus_/.test(id) ? "node" : "line";
}

function fmtPower(mw: number | null | undefined): string {
  if (mw == null) return "–";
  const abs = Math.abs(mw);
  if (abs >= 1000) return `${(mw / 1000).toFixed(abs >= 10000 ? 0 : 1)} GW`;
  return `${Math.round(mw)} MW`;
}

function fmtPct(pct: number | null | undefined): string {
  if (pct == null) return "–";
  return `${pct % 1 === 0 ? pct : pct.toFixed(1)}%`;
}

function signed(mw: number | null | undefined): string {
  if (mw == null) return "–";
  return `${mw > 0 ? "+" : ""}${fmtPower(mw)}`;
}

// --- shared primitives -------------------------------------------------------

/** Clickable element id that focuses + selects the element on the map. */
function ElementChip({ id, children }: { id: string; children?: ReactNode }) {
  const ctx = useContext(GridRefContext);
  const kind = kindOf(id);
  const dot = kind === "node" ? "bg-sky-400" : "bg-emerald-400";
  const interactive = ctx?.has(kind, id);
  const className = cn(
    "mx-px inline-flex items-center gap-1 rounded border px-1.5 py-px align-baseline font-mono text-[0.82em]",
    "border-border bg-muted/60 text-foreground",
    interactive && "cursor-pointer transition-colors hover:border-ring hover:bg-accent",
  );
  const inner = (
    <>
      <span className={cn("inline-block size-1.5 shrink-0 rounded-full", dot)} />
      {children ?? id}
    </>
  );
  if (!interactive) return <span className={className}>{inner}</span>;
  return (
    <button
      type="button"
      onClick={() => ctx!.pick(kind, id)}
      title={`Show ${id} on the map`}
      className={className}
    >
      {inner}
    </button>
  );
}

/** Horizontal loading bar coloured by the same ramp the map uses. */
function LoadingBar({ pct }: { pct: number | null | undefined }) {
  const v = pct == null ? 0 : Math.max(0, Math.min(pct, 100));
  return (
    <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
      <div
        className="h-full rounded-full transition-[width]"
        style={{ width: `${v}%`, backgroundColor: loadingColor(pct) }}
      />
    </div>
  );
}

/** Voltage marker positioned within its [min,max] p.u. band. */
function VoltageBar({
  vm,
  min,
  max,
}: {
  vm: number | null | undefined;
  min: number | null | undefined;
  max: number | null | undefined;
}) {
  const lo = min ?? 0.9;
  const hi = max ?? 1.1;
  const v = vm ?? lo;
  const pos = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1))) * 100;
  const out = vm != null && (vm < lo || vm > hi);
  return (
    <div className="relative h-1.5 w-full rounded-full bg-gradient-to-r from-rose-500/40 via-emerald-500/50 to-rose-500/40">
      <div
        className={cn(
          "absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-background",
          out ? "bg-rose-500" : "bg-emerald-400",
        )}
        style={{ left: `${pos}%` }}
      />
    </div>
  );
}

/** Compact labelled value. */
function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5" title={hint}>
      <span className="text-muted-foreground text-[0.7rem] uppercase tracking-wide">
        {label}
      </span>
      <span className="font-mono text-sm tabular-nums">{value}</span>
    </div>
  );
}

const STATE_BADGE: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  warn: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  alert: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
  offline: "bg-muted text-muted-foreground",
};

function StateBadge({ state }: { state?: string }) {
  if (!state) return null;
  return (
    <span
      className={cn(
        "rounded px-1.5 py-px text-[0.7rem] font-medium uppercase",
        STATE_BADGE[state] ?? STATE_BADGE.offline,
      )}
    >
      {state}
    </span>
  );
}

/** Tiny inline SVG sparkline; nulls break the line. */
function Sparkline({
  values,
  width = 240,
  height = 40,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
}) {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const n = values.length;
  const x = (i: number) => (n === 1 ? 0 : (i / (n - 1)) * width);
  const y = (v: number) => height - ((v - min) / span) * (height - 4) - 2;

  let d = "";
  values.forEach((v, i) => {
    if (v == null) return;
    d += `${d && values[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
  });
  let lastIdx = -1;
  for (let i = 0; i < values.length; i++) if (values[i] != null) lastIdx = i;
  const last = lastIdx >= 0 ? (values[lastIdx] as number) : null;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="text-primary"
    >
      <path d={d.trim()} fill="none" stroke="currentColor" strokeWidth={1.5} />
      {last != null && (
        <circle cx={x(lastIdx)} cy={y(last)} r={2.5} fill="currentColor" />
      )}
    </svg>
  );
}

// --- card shell --------------------------------------------------------------

function ToolCard({
  icon: Icon,
  accent,
  title,
  summary,
  status,
  children,
  rawResult,
}: {
  icon: LucideIcon;
  accent: string;
  title: string;
  summary: ReactNode;
  status?: ToolCallMessagePartStatus;
  children: ReactNode;
  rawResult: unknown;
}) {
  const [open, setOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const running = (status?.type ?? "complete") === "running" || summary == null;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="group/tool w-full rounded-lg border py-2.5"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 text-sm">
        {running ? (
          <LoaderIcon className="size-4 shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <Icon className={cn("size-4 shrink-0", accent)} />
        )}
        <span className="min-w-0 grow text-start leading-snug">
          {running ? (
            <span className="text-muted-foreground shimmer">{title}…</span>
          ) : (
            summary
          )}
        </span>
        <ChevronDownIcon
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            "group-data-[state=closed]/tool:-rotate-90",
          )}
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden text-sm data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <div className="mt-2.5 border-t px-3 pt-2.5">
          {children}
          <Collapsible open={rawOpen} onOpenChange={setRawOpen} className="mt-2.5">
            <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs transition-colors">
              <ChevronDownIcon
                className={cn("size-3 transition-transform", !rawOpen && "-rotate-90")}
              />
              Raw
            </CollapsibleTrigger>
            <CollapsibleContent className="overflow-hidden">
              <pre className="text-muted-foreground mt-1.5 max-h-64 overflow-auto rounded bg-muted/50 p-2 text-[0.7rem] whitespace-pre-wrap">
                {typeof rawResult === "string"
                  ? rawResult
                  : JSON.stringify(rawResult, null, 2)}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

// --- per-tool views ----------------------------------------------------------

type ToolView = {
  icon: LucideIcon;
  accent: string;
  /** Friendly label shown while the call is still running. */
  title: string;
  /** One-line summary for the collapsed header (null while loading). */
  summary: (r: any) => ReactNode;
  Detail: (p: { result: any }) => JSX.Element;
};

const SectionGrid = ({ children }: { children: ReactNode }) => (
  <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">{children}</div>
);

const ACCENT = {
  lookup: "text-sky-500",
  rank: "text-violet-500",
  topo: "text-emerald-500",
  history: "text-amber-500",
} as const;

const VIEWS: Record<string, ToolView> = {
  grid_summary: {
    icon: GaugeIcon,
    accent: ACCENT.lookup,
    title: "Reading grid summary",
    summary: (r) => (
      <span>
        Grid — {fmtPower(r.total_generation_mw)} gen · {fmtPower(r.total_load_mw)}{" "}
        load · max line <b>{fmtPct(r.max_line_loading_pct)}</b> ·{" "}
        {r.n_alerts} alerts / {r.n_warnings} warn
      </span>
    ),
    Detail: ({ result: r }) => (
      <div className="flex flex-col gap-3">
        <SectionGrid>
          <Stat label="Generation" value={fmtPower(r.total_generation_mw)} />
          <Stat label="Load" value={fmtPower(r.total_load_mw)} />
          <Stat label="Losses" value={fmtPower(r.losses_mw)} />
          <Stat label="Balancing" value={signed(r.external_balancing_mw)} />
          <Stat label="Buses" value={r.n_buses} />
          <Stat label="Branches" value={r.n_branches} />
        </SectionGrid>
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Max line loading</span>
            <span className="font-mono">{fmtPct(r.max_line_loading_pct)}</span>
          </div>
          <LoadingBar pct={r.max_line_loading_pct} />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={cn(
              "rounded px-1.5 py-px font-medium",
              r.converged
                ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                : "bg-rose-500/15 text-rose-600 dark:text-rose-400",
            )}
          >
            {r.converged ? "converged" : "not converged"}
          </span>
          <span className="text-muted-foreground">{r.timestamp}</span>
        </div>
      </div>
    ),
  },

  line_detail: {
    icon: SearchIcon,
    accent: ACCENT.lookup,
    title: "Inspecting line",
    summary: (r) => (
      <span>
        <ElementChip id={r.id} /> — <b>{fmtPct(r.loading_pct)}</b> ·{" "}
        {fmtPower(r.p_from_mw)} · {r.state}
      </span>
    ),
    Detail: ({ result: r }) => (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-xs">
          <ElementChip id={r.from} />
          <span className="text-muted-foreground">→</span>
          <ElementChip id={r.to} />
          <span className="text-muted-foreground">({r.kind})</span>
          <span className="grow" />
          <StateBadge state={r.state} />
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Loading</span>
            <span className="font-mono">{fmtPct(r.loading_pct)}</span>
          </div>
          <LoadingBar pct={r.loading_pct} />
        </div>
        <SectionGrid>
          <Stat label="P from" value={fmtPower(r.p_from_mw)} />
          <Stat label="P to" value={fmtPower(r.p_to_mw)} />
          <Stat label="Current" value={r.i_ka != null ? `${r.i_ka} kA` : "–"} />
          <Stat label="Max I" value={r.max_i_ka != null ? `${r.max_i_ka.toFixed?.(2) ?? r.max_i_ka} kA` : "–"} />
        </SectionGrid>
      </div>
    ),
  },

  node_detail: {
    icon: SearchIcon,
    accent: ACCENT.lookup,
    title: "Inspecting bus",
    summary: (r) => (
      <span>
        <ElementChip id={r.id} /> — {r.type} · <b>{r.vm_pu} p.u.</b> ·{" "}
        {signed(r.net_mw)}
      </span>
    ),
    Detail: ({ result: r }) => (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-xs">
          <span
            className="rounded px-1.5 py-px font-medium text-white"
            style={{ backgroundColor: NODE_TYPE_COLOR[r.type as keyof typeof NODE_TYPE_COLOR] ?? "#6b7a90" }}
          >
            {r.type}
          </span>
          {r.is_slack && (
            <span className="rounded bg-violet-500/15 px-1.5 py-px font-medium text-violet-500">
              slack
            </span>
          )}
          <span className="text-muted-foreground">
            zone {r.zone} · {r.v_nominal_kv} kV
          </span>
          <span className="grow" />
          <StateBadge state={r.state} />
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">
              Voltage {r.min_vm_pu}–{r.max_vm_pu} p.u.
            </span>
            <span className="font-mono">
              {r.vm_pu} p.u.{r.vm_kv != null ? ` (${r.vm_kv} kV)` : ""}
            </span>
          </div>
          <VoltageBar vm={r.vm_pu} min={r.min_vm_pu} max={r.max_vm_pu} />
        </div>
        <SectionGrid>
          <Stat label="Production" value={fmtPower(r.production_mw)} />
          <Stat label="Consumption" value={fmtPower(r.consumption_mw)} />
          <Stat label="Net" value={signed(r.net_mw)} />
        </SectionGrid>
      </div>
    ),
  },

  most_loaded_lines: {
    icon: ListOrderedIcon,
    accent: ACCENT.rank,
    title: "Ranking line loading",
    summary: (r) => {
      const top = Array.isArray(r) ? r[0] : undefined;
      return (
        <span>
          Top {Array.isArray(r) ? r.length : 0} lines — busiest{" "}
          <b>{fmtPct(top?.loading_pct)}</b>
          {top ? <> (<ElementChip id={top.id} />)</> : null}
        </span>
      );
    },
    Detail: ({ result: r }) => (
      <div className="flex flex-col gap-1.5">
        {(Array.isArray(r) ? r : []).map((l: any) => (
          <div key={l.id} className="flex items-center gap-2">
            <span className="w-[7.5rem] shrink-0 truncate">
              <ElementChip id={l.id} />
            </span>
            <span className="grow">
              <LoadingBar pct={l.loading_pct} />
            </span>
            <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums">
              {fmtPct(l.loading_pct)}
            </span>
          </div>
        ))}
      </div>
    ),
  },

  active_alerts: {
    icon: TriangleAlertIcon,
    accent: ACCENT.rank,
    title: "Checking active alerts",
    summary: (r) => {
      const arr = Array.isArray(r) ? r : [];
      const alerts = arr.filter((a) => a.severity === "alert").length;
      const warns = arr.length - alerts;
      if (arr.length === 0) return <span>No active alerts or warnings</span>;
      return (
        <span>
          <b>{alerts}</b> alerts · <b>{warns}</b> warnings
        </span>
      );
    },
    Detail: ({ result: r }) => {
      const arr = Array.isArray(r) ? r : [];
      if (arr.length === 0)
        return <p className="text-muted-foreground">Nothing flagged this hour.</p>;
      return (
        <div className="flex flex-col gap-1.5">
          {arr.map((a: any, i: number) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <CircleIcon
                className="mt-0.5 size-2 shrink-0"
                style={{
                  color: STATE_STROKE_COLOR[a.severity as keyof typeof STATE_STROKE_COLOR] ?? "#888",
                  fill: "currentColor",
                }}
              />
              {a.element_id && <ElementChip id={a.element_id} />}
              <span className="text-muted-foreground grow">{a.message}</span>
            </div>
          ))}
        </div>
      );
    },
  },

  bus_neighbors: {
    icon: WaypointsIcon,
    accent: ACCENT.topo,
    title: "Tracing connections",
    summary: (r) => (
      <span>
        <ElementChip id={r.bus} /> — <b>{r.branches?.length ?? 0}</b> branches ·{" "}
        <b>{r.neighbors?.length ?? 0}</b> buses ≤{r.hops} hop
        {r.hops === 1 ? "" : "s"}
      </span>
    ),
    Detail: ({ result: r }) => {
      const neighbors: any[] = Array.isArray(r.neighbors) ? r.neighbors : [];
      const byHop = new Map<number, any[]>();
      for (const n of neighbors) {
        const arr = byHop.get(n.hops) ?? [];
        arr.push(n);
        byHop.set(n.hops, arr);
      }
      const hops = [...byHop.keys()].sort((a, b) => a - b);
      return (
        <div className="flex flex-col gap-2.5">
          {hops.map((h) => (
            <div key={h} className="flex flex-col gap-1">
              <span className="text-muted-foreground text-[0.7rem] uppercase tracking-wide">
                {h} hop{h === 1 ? "" : "s"} · {byHop.get(h)!.length}
              </span>
              <div className="flex flex-wrap gap-1">
                {byHop.get(h)!.map((n) => (
                  <span key={n.bus} className="inline-flex items-center gap-1">
                    <ElementChip id={n.bus} />
                    <span
                      className="size-1.5 rounded-full"
                      style={{
                        backgroundColor:
                          NODE_TYPE_COLOR[n.type as keyof typeof NODE_TYPE_COLOR] ?? "#6b7a90",
                      }}
                      title={n.type}
                    />
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      );
    },
  },

  element_history: {
    icon: ActivityIcon,
    accent: ACCENT.history,
    title: "Reading history",
    summary: (r) => {
      const v: (number | null)[] = Array.isArray(r.v) ? r.v : [];
      const nums = v.filter((x): x is number => x != null);
      const now = nums.length ? nums[nums.length - 1] : null;
      const first = nums.length ? nums[0] : null;
      const unit = r.metric === "loading" ? "%" : r.metric === "vm_pu" ? "" : " MW";
      const arrow =
        now != null && first != null ? (now > first ? "▲" : now < first ? "▼" : "→") : "";
      return (
        <span>
          <ElementChip id={r.element_id} /> {r.metric} · {nums.length}h —{" "}
          <b>
            {now != null ? `${Math.round(now * 10) / 10}${unit}` : "–"}
          </b>{" "}
          {arrow && first != null && (
            <span className="text-muted-foreground">
              {arrow} from {Math.round(first * 10) / 10}
              {unit}
            </span>
          )}
        </span>
      );
    },
    Detail: ({ result: r }) => {
      const v: (number | null)[] = Array.isArray(r.v) ? r.v : [];
      const nums = v.filter((x): x is number => x != null);
      const unit = r.metric === "loading" ? "%" : r.metric === "vm_pu" ? " p.u." : " MW";
      return (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs">
            <ElementChip id={r.element_id} />
            <span className="text-muted-foreground">
              {r.metric} · {v.length} hourly points
            </span>
          </div>
          <Sparkline values={v} />
          {nums.length > 0 && (
            <div className="flex justify-between text-[0.7rem] text-muted-foreground">
              <span>min {Math.round(Math.min(...nums) * 10) / 10}{unit}</span>
              <span>max {Math.round(Math.max(...nums) * 10) / 10}{unit}</span>
            </div>
          )}
          {(r.truncated_past || r.truncated_future) && (
            <p className="text-[0.7rem] text-amber-600 dark:text-amber-400">
              window hit the dataset edge
            </p>
          )}
        </div>
      );
    },
  },
};

// --- entry point -------------------------------------------------------------

function hasError(result: unknown): result is { error: string } {
  return (
    typeof result === "object" &&
    result !== null &&
    typeof (result as any).error === "string"
  );
}

/**
 * Renders a domain card for known tools; returns null for everything else so
 * the caller can fall back to <ToolFallback>.
 */
const ToolCallViewImpl: ToolCallMessagePartComponent = ({
  toolName,
  result,
  status,
}) => {
  const view = VIEWS[toolName];
  if (!view) return null as unknown as JSX.Element;

  const ready = result !== undefined && !hasError(result);
  const errored = hasError(result);

  return (
    <ToolCard
      icon={view.icon}
      accent={view.accent}
      title={view.title}
      status={status}
      rawResult={result}
      summary={
        errored ? (
          <span className="text-rose-500">{(result as any).error}</span>
        ) : ready ? (
          safeSummary(view, result)
        ) : null
      }
    >
      {ready ? <view.Detail result={result} /> : null}
    </ToolCard>
  );
};

/** A malformed result shouldn't crash the whole thread. */
function safeSummary(view: ToolView, result: unknown): ReactNode {
  try {
    return view.summary(result);
  } catch {
    return <span className="text-muted-foreground">done</span>;
  }
}

export const ToolCallView = memo(ToolCallViewImpl);
ToolCallView.displayName = "ToolCallView";

/** Whether a dedicated view exists for this tool name. */
export function hasToolView(toolName: string): boolean {
  return toolName in VIEWS;
}
