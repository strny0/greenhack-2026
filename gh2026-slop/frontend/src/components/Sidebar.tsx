import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type {
  ContingencyResult,
  DeviationAssessment,
  DeviationRecord,
  Meta,
  PresetKey,
  ScenarioSpec,
  StateFrame,
  WeatherPoint,
  WhatIfResponse,
} from "../types";
import { tierTone } from "@/lib/deviation";
import type { Selection } from "./MapView";
import AgentChat from "./AgentChat";
import { AgentRuntimeProvider } from "../agent/AgentRuntimeProvider";
import type { GridRefCtx } from "../agent/grid-refs";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ChevronDownIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildLabelMap, formatGenTypes, labelOf, NODE_KIND_LABEL } from "@/lib/gridmeta";

interface AlertRow {
  id: string;
  kind: "line" | "node";
  sev: "alert" | "warn";
  label: string;
  kindText: string;
  msg: string;
  val: number;
}

/** Reactive media-query match (used to branch the desktop / mobile layout). */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : true,
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

interface Props {
  frame: StateFrame;
  meta: Meta;
  /**
   * The currently-viewed snapshot timestamp, derived from `meta` (the selected
   * day + hour) so it updates the *instant* the day changes — before the heavy
   * window data finishes loading. Drives the agent's grid-state context.
   */
  agentTimestamp: string;
  selected: Selection | null;
  onFocus: (ids: string[]) => void;
  onClearFocus: () => void;
  onSelect: (s: Selection | null) => void;
  onZoom: (kind: "node" | "line", id: string) => void;
  dev: DeviationRecord | null;
  triage: DeviationAssessment | null;
  onExplain: () => void;
  openChatNonce: number;
  /** Active whole-day failure simulation (its resolved spec), or null. */
  simulation: { spec: ScenarioSpec } | null;
  simLoading: boolean;
  simError: string | null;
  onActivateSim: (preset: PresetKey) => void;
  onExitSim: () => void;
}

type Tab = "alerts" | "n1" | "whatif" | "weather" | "chat";
type Tone = "alert" | "warn" | "ok" | "crit";

const TONE: Record<Tone, string> = {
  alert: "bg-red-500/15 text-red-400",
  warn: "bg-amber-500/15 text-amber-400",
  ok: "bg-emerald-500/15 text-emerald-400",
  crit: "bg-purple-500/20 text-purple-300",
};

function Pill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold", TONE[tone])}>
      {children}
    </span>
  );
}

function Item({
  onClick,
  onDoubleClick,
  title,
  pill,
  desc,
}: {
  onClick?: () => void;
  onDoubleClick?: () => void;
  title: React.ReactNode;
  pill?: React.ReactNode;
  desc?: React.ReactNode;
}) {
  return (
    <div
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      className={cn(
        "mb-2 rounded-lg border bg-background p-2.5 transition-colors",
        (onClick || onDoubleClick) && "cursor-pointer hover:border-ring",
      )}
    >
      <div className="flex items-center justify-between gap-2 font-semibold">
        <span className="truncate">{title}</span>
        {pill}
      </div>
      {desc != null && <div className="mt-0.5 text-[11px] text-muted-foreground">{desc}</div>}
    </div>
  );
}

const Note = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2.5 rounded-md border bg-background p-2 text-[11px] text-muted-foreground">
    {children}
  </div>
);

const SectionTitle = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2 mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">{children}</div>
);

const MIN_WIDTH = 320;
const MAX_WIDTH = 720;
const DEFAULT_WIDTH = 390;
const WIDTH_KEY = "sidebar-width";

export default function Sidebar({
  frame,
  meta,
  agentTimestamp,
  selected,
  onFocus,
  onClearFocus,
  onSelect,
  onZoom,
  dev,
  triage,
  onExplain,
  openChatNonce,
  simulation,
  simLoading,
  simError,
  onActivateSim,
  onExitSim,
}: Props) {
  // On phones the panel becomes a collapsible bottom sheet under the map; on
  // desktop it's the resizable right rail. `mobileOpen` drives the sheet height.
  const isDesktop = useMediaQuery("(min-width: 768px)");
  // Default to Chat on mobile (the panel's primary use there); Alerts on desktop.
  const [tab, setTab] = useState<Tab>(isDesktop ? "alerts" : "chat");
  const [mobileOpen, setMobileOpen] = useState(false);

  // "Explain (AI)" from the banner / deviation section opens the Chat tab.
  useEffect(() => {
    if (openChatNonce > 0) {
      setTab("chat");
      setMobileOpen(true);
    }
  }, [openChatNonce]);

  // Operator-resizable panel. Width persists across reloads; the map area is
  // flex-1 and reflows around whatever width we land on.
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(WIDTH_KEY));
    return saved >= MIN_WIDTH && saved <= MAX_WIDTH ? saved : DEFAULT_WIDTH;
  });
  const dragging = useRef(false);

  const onResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
  }, []);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return;
      // Handle sits on the panel's left edge, so width grows as the cursor moves left.
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth - e.clientX));
      setWidth(next);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      localStorage.setItem(WIDTH_KEY, String(width));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [width]);

  // client-side alerts (stay in sync with scrubber, no extra fetch)
  const alerts = useMemo(() => {
    const warn = meta.thresholds.line_loading_warn ?? 75;
    const alert = meta.thresholds.line_loading_alert ?? 90;
    const out: AlertRow[] = [];
    for (const l of frame.lines) {
      if (l.loading_pct == null) continue;
      const kindText = l.kind === "trafo" ? "Transformer" : "Transmission line";
      if (l.loading_pct >= alert) out.push({ id: l.id, kind: "line", sev: "alert", label: labelOf(l), kindText, msg: `loaded at ${l.loading_pct}%`, val: l.loading_pct });
      else if (l.loading_pct >= warn) out.push({ id: l.id, kind: "line", sev: "warn", label: labelOf(l), kindText, msg: `loaded at ${l.loading_pct}%`, val: l.loading_pct });
    }
    for (const n of frame.nodes) {
      const role = n.is_slack ? "Slack bus" : NODE_KIND_LABEL[n.type];
      const gens = formatGenTypes(n.gen_types);
      const kindText = gens ? `${role} · ${gens}` : role;
      if (n.state === "alert") out.push({ id: n.id, kind: "node", sev: "alert", label: labelOf(n), kindText, msg: `voltage ${n.vm_pu?.toFixed(3)} p.u. — limit breach`, val: n.vm_pu ?? 0 });
      else if (n.state === "warn") out.push({ id: n.id, kind: "node", sev: "warn", label: labelOf(n), kindText, msg: `voltage ${n.vm_pu?.toFixed(3)} p.u. — near limit`, val: n.vm_pu ?? 0 });
    }
    out.sort((a, b) => (a.sev === b.sev ? b.val - a.val : a.sev === "alert" ? -1 : 1));
    return out;
  }, [frame, meta]);

  // The Alerts tab badge also lights when the current hour is a high / forced
  // plan-deviation, even if no line/voltage limit is breached.
  const devUrgent = !!dev && (dev.risk_tier === "high" || dev.force_notify);
  const nAlerts = Math.max(alerts.filter((a) => a.sev === "alert").length, devUrgent ? 1 : 0);

  // id -> override display label, for the server-computed N-1 / what-if results.
  const labels = useMemo(() => buildLabelMap(frame.nodes, frame.lines), [frame]);

  // Wiring for the clickable element chips the agent emits in chat. Reuses the
  // same focus/select the rest of the sidebar uses; `has` enforces exact-match
  // (only real elements in the current frame become chips).
  const grid = useMemo<GridRefCtx>(
    () => ({
      pick: (kind, id) => {
        onFocus([id]);
        onSelect({ kind, id });
      },
      jump: (kind, id) => {
        onFocus([id]);
        onSelect({ kind, id });
        onZoom(kind, id);
      },
      has: (kind, id) =>
        kind === "node"
          ? frame.nodes.some((n) => n.id === id)
          : frame.lines.some((l) => l.id === id),
      label: (_kind, id) => labels[id] ?? id,
    }),
    [frame, labels, onFocus, onSelect, onZoom],
  );

  const TABS: [Tab, string, number][] = [
    ["alerts", "Alerts", nAlerts],
    ["n1", "N-1", 0],
    ["whatif", "What-if", 0],
    ["weather", "Weather", 0],
    ["chat", "Chat", 0],
  ];

  return (
    // The runtime provider is mounted once, above the tab body, so the agent
    // conversation persists when the operator switches tabs.
    <AgentRuntimeProvider timestamp={agentTimestamp || frame.timestamp} selection={selected} simulation={simulation?.spec ?? null}>
      <aside
        className={cn(
          "relative flex flex-col bg-card",
          isDesktop
            ? "h-full shrink-0 border-l"
            : "w-full shrink-0 border-t",
        )}
        style={
          isDesktop
            ? { width }
            : { height: mobileOpen ? "60dvh" : undefined }
        }
      >
        {/* Desktop: drag handle on the left edge to resize the panel. */}
        {isDesktop && (
          <div
            onPointerDown={onResizeStart}
            className="absolute -left-1 top-0 z-10 h-full w-2 cursor-col-resize select-none transition-colors hover:bg-primary/30"
            title="Drag to resize"
          />
        )}

        {/* Mobile: grab bar that expands/collapses the bottom sheet. */}
        {!isDesktop && (
          <button
            type="button"
            onClick={() => setMobileOpen((o) => !o)}
            aria-expanded={mobileOpen}
            aria-label={mobileOpen ? "Collapse panel" : "Expand panel"}
            className="flex w-full items-center justify-center border-b py-1.5 text-muted-foreground active:bg-accent"
          >
            <ChevronDownIcon
              className={cn(
                "size-4 transition-transform",
                !mobileOpen && "rotate-180",
              )}
            />
          </button>
        )}

        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as Tab);
            onClearFocus();
            // tapping a tab on mobile also opens the sheet
            if (!isDesktop) setMobileOpen(true);
          }}
          className="flex min-h-0 flex-1 flex-col gap-0"
        >
          <TabsList className="h-auto w-full justify-stretch gap-0 rounded-none border-b bg-transparent p-0">
            {TABS.map(([t, label, badge]) => (
              <TabsTrigger
                key={t}
                value={t}
                className="flex-1 rounded-none border-0 border-b-2 border-transparent py-2.5 text-xs text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none"
              >
                {label}
                {badge > 0 && (
                  <span className="ml-1 inline-flex min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] text-white">
                    {badge}
                  </span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* On mobile the tab body is hidden until the sheet is expanded, so a
              collapsed panel is just the grab bar + tab strip under the map. */}
          <div
            className={cn(
              "flex min-h-0 flex-1 flex-col",
              !isDesktop && !mobileOpen && "hidden",
            )}
          >
            <TabsContent value="alerts" className="m-0 min-h-0 flex-1">
              <ScrollArea className="h-full">
                <div className="p-3">
                  <AlertsTab
                    alerts={alerts}
                    dev={dev}
                    triage={triage}
                    onExplain={onExplain}
                    onPick={(id, kind) => { onFocus([id]); onSelect({ kind, id }); }}
                    onZoom={(id, kind) => { onFocus([id]); onSelect({ kind, id }); onZoom(kind, id); }}
                  />
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="n1" className="m-0 min-h-0 flex-1">
              <ScrollArea className="h-full">
                <div className="p-3">
                  <N1Tab ts={frame.timestamp} labels={labels} onFocus={onFocus} onSelect={onSelect} />
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="whatif" className="m-0 min-h-0 flex-1">
              <ScrollArea className="h-full">
                <div className="p-3">
                  <WhatIfTab
                    frame={frame}
                    labels={labels}
                    onFocus={onFocus}
                    onSelect={onSelect}
                    simulation={simulation}
                    simLoading={simLoading}
                    simError={simError}
                    onActivateSim={onActivateSim}
                    onExitSim={onExitSim}
                  />
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="weather" className="m-0 min-h-0 flex-1">
              <ScrollArea className="h-full">
                <div className="p-3">
                  <WeatherTab />
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="chat" className="m-0 min-h-0 flex-1">
              <AgentChat grid={grid} />
            </TabsContent>
          </div>
        </Tabs>
      </aside>
    </AgentRuntimeProvider>
  );
}

function PlanDeviationSection({
  dev,
  triage,
  onExplain,
  onPick,
}: {
  dev: DeviationRecord;
  triage: DeviationAssessment | null;
  onExplain: () => void;
  onPick: (id: string, kind: "line" | "node") => void;
}) {
  const tierLabel = dev.force_notify ? "action required" : `${dev.risk_tier} risk`;
  const worst = triage?.worst_deviations ?? [];
  return (
    <>
      <SectionTitle>Plan deviation</SectionTitle>
      <Item
        title={dev.headline}
        pill={<Pill tone={dev.force_notify ? "alert" : tierTone(dev.risk_tier)}>{tierLabel}</Pill>}
        desc={
          <>
            solar {dev.solar_delta_mw >= 0 ? "+" : ""}
            {dev.solar_delta_mw} MW · wind {dev.wind_delta_mw >= 0 ? "+" : ""}
            {dev.wind_delta_mw} MW · max line {dev.max_line_loading_pct}% · balancing{" "}
            {dev.slack_mw >= 0 ? "+" : ""}
            {dev.slack_mw} MW
            {dev.force_notify && dev.force_reasons.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-red-300/90">
                {dev.force_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </>
        }
      />
      {dev.risk_tier !== "none" && (
        <Button variant="outline" size="sm" className="mb-2 w-full" onClick={onExplain}>
          Explain with AI
        </Button>
      )}
      {worst.length > 0 && (
        <>
          <SectionTitle>Worst generators ({worst.length})</SectionTitle>
          {worst.slice(0, 8).map((d) => (
            <Item
              key={d.gen}
              onClick={() => d.bus && onPick(d.bus, "node")}
              title={`${d.gen}${d.bus ? ` · ${d.bus}` : ""}`}
              pill={<Pill tone={d.kind === "solar" ? "warn" : "ok"}>{d.kind}</Pill>}
              desc={
                <>
                  plan {d.planned_mw} MW → actual {d.actual_mw} MW (Δ {d.delta_mw >= 0 ? "+" : ""}
                  {d.delta_mw} MW{d.pct != null ? `, ${d.pct >= 0 ? "+" : ""}${d.pct}%` : ""})
                </>
              }
            />
          ))}
        </>
      )}
    </>
  );
}

function AlertsTab({
  alerts,
  dev,
  triage,
  onExplain,
  onPick,
  onZoom,
}: {
  alerts: AlertRow[];
  dev: DeviationRecord | null;
  triage: DeviationAssessment | null;
  onExplain: () => void;
  onPick: (id: string, kind: "line" | "node") => void;
  onZoom: (id: string, kind: "line" | "node") => void;
}) {
  const showDeviation = !!dev && (dev.risk_tier !== "none" || dev.force_notify);
  return (
    <>
      {showDeviation && (
        <PlanDeviationSection dev={dev!} triage={triage} onExplain={onExplain} onPick={onPick} />
      )}
      {alerts.length > 0 ? (
        <>
          <SectionTitle>{alerts.length} active grid conditions · double-click to zoom</SectionTitle>
          {alerts.map((a) => (
            <Item
              key={a.kind + a.id}
              onClick={() => onPick(a.id, a.kind)}
              onDoubleClick={() => onZoom(a.id, a.kind)}
              title={a.label}
              pill={<Pill tone={a.sev}>{a.sev}</Pill>}
              desc={
                <>
                  <span className="font-medium text-foreground/80">{a.kindText}</span>
                  {" — "}
                  {a.msg}
                </>
              }
            />
          ))}
        </>
      ) : (
        !showDeviation && (
          <Note>No active alerts or warnings at this timestamp. The grid is within limits.</Note>
        )
      )}
    </>
  );
}

function N1Tab({ ts, labels, onFocus, onSelect }: { ts: string; labels: Record<string, string>; onFocus: (ids: string[]) => void; onSelect: (s: Selection) => void }) {
  const [res, setRes] = useState<ContingencyResult[] | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const r = await api.n1(ts, 60);
      setRes(r.results);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Note>
        Deterministic N-1 security analysis: trip each line, re-solve the load flow, and rank by worst
        resulting stress. Non-converging trips = islanding / voltage collapse (most critical).
      </Note>
      <Button className="mb-2.5 w-full" onClick={run} disabled={loading}>
        {loading ? "Running load flows…" : "Run N-1 analysis"}
      </Button>
      {res &&
        res.slice(0, 25).map((r) => (
          <Item
            key={r.contingency_id}
            onClick={() => {
              onFocus([r.contingency_id, ...r.overloaded.map((o) => o.id)]);
              onSelect({ kind: "line", id: r.contingency_id });
            }}
            title={`trip ${labels[r.contingency_id] ?? r.contingency_name}`}
            pill={
              r.converged ? (
                <Pill tone={r.max_loading_pct >= 100 ? "alert" : r.max_loading_pct >= 90 ? "warn" : "ok"}>
                  {r.max_loading_pct}%
                </Pill>
              ) : (
                <Pill tone="crit">islanding</Pill>
              )
            }
            desc={
              r.converged
                ? r.n_overloads > 0
                  ? `${r.n_overloads} overloaded: ${r.overloaded.slice(0, 2).map((o) => `${labels[o.id] ?? o.name} ${o.loading_pct}%`).join(", ")}`
                  : "no overloads — grid survives this contingency"
                : "load flow does not converge — loss of supply / collapse"
            }
          />
        ))}
    </>
  );
}

const NONE = "__none__";

const SIM_PRESETS: { key: PresetKey; label: string }[] = [
  { key: "trip_most_loaded_line", label: "Trip most-loaded line" },
  { key: "trip_largest_generator", label: "Trip largest generator" },
  { key: "load_surge", label: "Load surge (+50% demand)" },
];

function WhatIfTab({
  frame,
  labels,
  onFocus,
  onSelect,
  simulation,
  simLoading,
  simError,
  onActivateSim,
  onExitSim,
}: {
  frame: StateFrame;
  labels: Record<string, string>;
  onFocus: (ids: string[]) => void;
  onSelect: (s: Selection) => void;
  simulation: { spec: ScenarioSpec } | null;
  simLoading: boolean;
  simError: string | null;
  onActivateSim: (preset: PresetKey) => void;
  onExitSim: () => void;
}) {
  const [disc, setDisc] = useState<string>(NONE);
  const [scale, setScale] = useState(1.0);
  const [res, setRes] = useState<WhatIfResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const lines = useMemo(() => [...frame.lines].sort((a, b) => (b.loading_pct ?? 0) - (a.loading_pct ?? 0)), [frame]);

  const run = async () => {
    setLoading(true);
    try {
      const lineId = disc === NONE ? "" : disc;
      const r = await api.whatif({
        timestamp: frame.timestamp,
        disconnect_lines: lineId ? [lineId] : [],
        load_scale: scale,
      });
      setRes(r);
      const ids = [lineId, ...r.diffs.slice(0, 8).map((d) => d.id)].filter(Boolean);
      onFocus(ids);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Whole-day failure simulation — overrides the loaded day live across both
          views. Sits above the single-hour manual what-if below. */}
      <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5">
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
          ⚡ Live failure simulation
        </div>
        {simulation ? (
          <>
            <div className="mb-2 text-[11px] text-muted-foreground">{simulation.spec.label}</div>
            <Button variant="outline" className="w-full" onClick={onExitSim}>
              Exit simulation
            </Button>
          </>
        ) : (
          <>
            <div className="mb-2 text-[11px] text-muted-foreground">
              Apply a failure to the whole loaded day and watch alerts, buses and lines react.
            </div>
            <div className="flex flex-col gap-1.5">
              {SIM_PRESETS.map((p) => (
                <Button
                  key={p.key}
                  variant="outline"
                  className="w-full justify-start"
                  disabled={simLoading}
                  onClick={() => onActivateSim(p.key)}
                >
                  {p.label}
                </Button>
              ))}
            </div>
            {simLoading && (
              <div className="mt-2 text-[11px] text-muted-foreground">Solving 24 hours…</div>
            )}
            {simError && <div className="mt-2 text-[11px] text-red-500">{simError}</div>}
          </>
        )}
      </div>

      <Note>Apply operator actions and re-run a real load flow. The map highlights what moves.</Note>
      <div className="mb-2.5">
        <label className="mb-1 block text-[11px] text-muted-foreground">Disconnect a line</label>
        <Select value={disc} onValueChange={setDisc}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="— none —" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>— none —</SelectItem>
            {lines.map((l) => (
              <SelectItem key={l.id} value={l.id}>
                {labelOf(l)} ({l.loading_pct ?? 0}%)
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="mb-2.5">
        <label className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>Load multiplier</span>
          <span className="text-foreground">×{scale.toFixed(2)}</span>
        </label>
        <Slider min={0.8} max={1.6} step={0.05} value={[scale]} onValueChange={(v) => setScale(v[0])} />
      </div>
      <Button className="mb-2.5 w-full" onClick={run} disabled={loading}>
        {loading ? "Solving…" : "Run scenario"}
      </Button>
      {res && (
        <>
          <Item
            title="Result"
            pill={
              <Pill tone={res.scenario.summary.converged ? (res.scenario.summary.max_loading_pct >= 100 ? "alert" : "ok") : "crit"}>
                {res.scenario.summary.converged ? `max ${res.scenario.summary.max_loading_pct}%` : "diverged"}
              </Pill>
            }
            desc={
              <>
                base max {res.base.summary.max_loading_pct}% → scenario{" "}
                {res.scenario.summary.converged ? `${res.scenario.summary.max_loading_pct}%` : "voltage collapse / islanding"} ·{" "}
                {res.new_alerts.length} new alert(s)
              </>
            }
          />
          <SectionTitle>Biggest loading changes</SectionTitle>
          {res.diffs.slice(0, 10).map((d) => (
            <Item
              key={d.id}
              onClick={() => onSelect({ kind: "line", id: d.id })}
              title={labels[d.id] ?? d.name}
              pill={
                <Pill tone={d.after >= 100 ? "alert" : d.after >= 90 ? "warn" : "ok"}>
                  {d.before}% → {d.after}%
                </Pill>
              }
              desc={`Δ ${d.delta > 0 ? "+" : ""}${d.delta} pts`}
            />
          ))}
        </>
      )}
    </>
  );
}

function WeatherTab() {
  const [data, setData] = useState<{ points: WeatherPoint[]; summary: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const run = async () => {
    setLoading(true);
    try {
      setData(await api.weather());
    } finally {
      setLoading(false);
    }
  };
  return (
    <>
      <Note>
        Live cloud cover &amp; wind (Open-Meteo) at the largest solar hubs, projected onto Czechia. The solar-drop
        flag is a lightweight heuristic — not a trained model.
      </Note>
      <Button className="mb-2.5 w-full" onClick={run} disabled={loading}>
        {loading ? "Fetching forecast…" : "Fetch weather overlay"}
      </Button>
      {data && <Item title="Summary" desc={data.summary} />}
      {data?.points.map((p) => (
        <Item
          key={p.bus}
          title={`${p.bus} · ${p.solar_mw} MW PV`}
          pill={<Pill tone={p.solar_risk ? "warn" : "ok"}>{p.solar_risk ? "PV drop risk" : "stable"}</Pill>}
          desc={`cloud ${p.cloud_cover_now}% → ${p.cloud_cover_3h}% (3h) · wind ${p.wind_speed_10m} km/h`}
        />
      ))}
    </>
  );
}
