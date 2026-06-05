import { useMemo, useState } from "react";
import { api } from "../api";
import type { ContingencyResult, Meta, StateFrame, WeatherPoint, WhatIfResponse } from "../types";
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
import { cn } from "@/lib/utils";

interface Props {
  frame: StateFrame;
  meta: Meta;
  selected: Selection | null;
  onFocus: (ids: string[]) => void;
  onClearFocus: () => void;
  onSelect: (s: Selection | null) => void;
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
  title,
  pill,
  desc,
}: {
  onClick?: () => void;
  title: React.ReactNode;
  pill?: React.ReactNode;
  desc?: React.ReactNode;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "mb-2 rounded-lg border bg-background p-2.5 transition-colors",
        onClick && "cursor-pointer hover:border-ring",
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

export default function Sidebar({ frame, meta, selected, onFocus, onClearFocus, onSelect }: Props) {
  const [tab, setTab] = useState<Tab>("alerts");

  // client-side alerts (stay in sync with scrubber, no extra fetch)
  const alerts = useMemo(() => {
    const warn = meta.thresholds.line_loading_warn ?? 75;
    const alert = meta.thresholds.line_loading_alert ?? 90;
    const out: { id: string; kind: "line" | "node"; sev: "alert" | "warn"; msg: string; val: number }[] = [];
    for (const l of frame.lines) {
      if (l.loading_pct == null) continue;
      if (l.loading_pct >= alert) out.push({ id: l.id, kind: "line", sev: "alert", msg: `${l.name} at ${l.loading_pct}%`, val: l.loading_pct });
      else if (l.loading_pct >= warn) out.push({ id: l.id, kind: "line", sev: "warn", msg: `${l.name} at ${l.loading_pct}%`, val: l.loading_pct });
    }
    for (const n of frame.nodes) {
      if (n.state === "alert") out.push({ id: n.id, kind: "node", sev: "alert", msg: `${n.name} voltage ${n.vm_pu?.toFixed(3)} p.u. — limit breach`, val: n.vm_pu ?? 0 });
      else if (n.state === "warn") out.push({ id: n.id, kind: "node", sev: "warn", msg: `${n.name} voltage ${n.vm_pu?.toFixed(3)} p.u. — near limit`, val: n.vm_pu ?? 0 });
    }
    out.sort((a, b) => (a.sev === b.sev ? b.val - a.val : a.sev === "alert" ? -1 : 1));
    return out;
  }, [frame, meta]);

  const nAlerts = alerts.filter((a) => a.sev === "alert").length;

  // Wiring for the clickable element chips the agent emits in chat. Reuses the
  // same focus/select the rest of the sidebar uses; `has` enforces exact-match
  // (only real elements in the current frame become chips).
  const grid = useMemo<GridRefCtx>(
    () => ({
      pick: (kind, id) => {
        onFocus([id]);
        onSelect({ kind, id });
      },
      has: (kind, id) =>
        kind === "node"
          ? frame.nodes.some((n) => n.id === id)
          : frame.lines.some((l) => l.id === id),
    }),
    [frame, onFocus, onSelect],
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
    <AgentRuntimeProvider timestamp={frame.timestamp} selection={selected}>
      <aside className="flex w-[390px] flex-col border-l bg-card">
        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as Tab);
            onClearFocus();
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

          <TabsContent value="alerts" className="m-0 min-h-0 flex-1">
            <ScrollArea className="h-full">
              <div className="p-3">
                <AlertsTab alerts={alerts} onPick={(id, kind) => { onFocus([id]); onSelect({ kind, id }); }} />
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="n1" className="m-0 min-h-0 flex-1">
            <ScrollArea className="h-full">
              <div className="p-3">
                <N1Tab ts={frame.timestamp} onFocus={onFocus} onSelect={onSelect} />
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="whatif" className="m-0 min-h-0 flex-1">
            <ScrollArea className="h-full">
              <div className="p-3">
                <WhatIfTab frame={frame} onFocus={onFocus} onSelect={onSelect} />
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
        </Tabs>
      </aside>
    </AgentRuntimeProvider>
  );
}

function AlertsTab({ alerts, onPick }: { alerts: any[]; onPick: (id: string, kind: "line" | "node") => void }) {
  if (!alerts.length)
    return <Note>No active alerts or warnings at this timestamp. The grid is within limits.</Note>;
  return (
    <>
      <SectionTitle>{alerts.length} active conditions</SectionTitle>
      {alerts.map((a) => (
        <Item
          key={a.kind + a.id}
          onClick={() => onPick(a.id, a.kind)}
          title={a.id}
          pill={<Pill tone={a.sev}>{a.sev}</Pill>}
          desc={a.msg}
        />
      ))}
    </>
  );
}

function N1Tab({ ts, onFocus, onSelect }: { ts: string; onFocus: (ids: string[]) => void; onSelect: (s: Selection) => void }) {
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
            title={`trip ${r.contingency_name}`}
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
                  ? `${r.n_overloads} overloaded: ${r.overloaded.slice(0, 2).map((o) => `${o.name} ${o.loading_pct}%`).join(", ")}`
                  : "no overloads — grid survives this contingency"
                : "load flow does not converge — loss of supply / collapse"
            }
          />
        ))}
    </>
  );
}

const NONE = "__none__";

function WhatIfTab({ frame, onFocus, onSelect }: { frame: StateFrame; onFocus: (ids: string[]) => void; onSelect: (s: Selection) => void }) {
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
                {l.name} ({l.loading_pct ?? 0}%)
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
              title={d.name}
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
