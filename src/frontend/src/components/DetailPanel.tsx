import { useEffect, useState } from "react";
import { useThreadRuntime } from "@assistant-ui/react";
import { ASK_EVENT } from "@/agent/ask-context";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { LocateFixedIcon, X } from "lucide-react";
import { api } from "../api";
import type { GridLine, GridNode, State } from "../types";
import { formatGenTypes, labelOf, NODE_KIND_LABEL } from "@/lib/gridmeta";

interface Props {
  node: GridNode | null;
  line: GridLine | null;
  /** Pre-failure values for the same element, when a simulation is active. */
  baseNode?: GridNode | null;
  baseLine?: GridLine | null;
  windowStartTs: string;
  windowCount: number;
  onClose: () => void;
  /** Fly the camera to the selected element on whichever view is active. */
  onGoTo: (kind: "node" | "line", id: string) => void;
}

const hhmm = (ts: string) => new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/** Health badge — the operator's first question about any selected element. */
const STATE_PILL: Record<State, { label: string; cls: string }> = {
  ok: { label: "OK", cls: "bg-emerald-500/15 text-emerald-400" },
  warn: { label: "Warning", cls: "bg-amber-500/15 text-amber-400" },
  alert: { label: "Alert", cls: "bg-red-500/15 text-red-400" },
  offline: { label: "Out of service", cls: "bg-slate-500/15 text-slate-400" },
};

function StatePill({ state }: { state: State }) {
  const p = STATE_PILL[state] ?? STATE_PILL.ok;
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${p.cls}`}>
      {p.label}
    </span>
  );
}

/** Questions an operator would ask about a line or a substation they clicked. */
function questionsFor(kind: "node" | "line", name: string): string[] {
  return kind === "line"
    ? [
        `Why is ${name} loaded like this right now?`,
        `What happens if ${name} trips?`,
        `How has ${name} moved over the day?`,
      ]
    : [
        `What's happening at ${name}?`,
        `What does ${name} connect to?`,
        `How has ${name} changed over the day?`,
      ];
}

/**
 * Clicking the diagram is the quickest way to start a question: suggested
 * questions about the clicked element, or the operator's own. The element is
 * already in the agent's context (the selection), so the question can be short.
 */
function AskAbout({ kind, name }: { kind: "node" | "line"; name: string }) {
  const runtime = useThreadRuntime();
  const [own, setOwn] = useState("");
  const ask = (q: string) => {
    if (!q.trim()) return;
    runtime.append(q.trim());
    window.dispatchEvent(new Event(ASK_EVENT));
    setOwn("");
  };
  return (
    <div className="mt-3 flex flex-col gap-1.5 border-t pt-3">
      <span className="text-[13px] text-muted-foreground">Ask about this</span>
      {questionsFor(kind, name).map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => ask(q)}
          className="min-h-10 rounded-lg border bg-background px-3 py-2 text-left text-sm leading-snug transition-colors hover:border-ring"
        >
          {q}
        </button>
      ))}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(own);
        }}
      >
        <label htmlFor="ask-about-own" className="sr-only">
          Ask your own question about {name}
        </label>
        <input
          id="ask-about-own"
          value={own}
          onChange={(e) => setOwn(e.target.value)}
          placeholder="Or ask your own question"
          className="h-10 w-full rounded-lg border border-input bg-muted px-3 text-sm outline-none placeholder:text-muted-foreground focus:border-ring"
        />
      </form>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right tabular-nums">{v}</span>
    </>
  );
}

export default function DetailPanel({ node, line, baseNode, baseLine, windowStartTs, windowCount, onClose, onGoTo }: Props) {
  const [data, setData] = useState<{ t: string; v: number | null }[]>([]);
  const [metricLabel, setMetricLabel] = useState("");

  useEffect(() => {
    const el = node ?? line;
    if (!el) return;
    const kind = node ? "node" : "line";
    const metric = node ? "vm_pu" : "loading";
    setMetricLabel(node ? "Voltage (p.u.)" : "Loading (%)");
    api
      .timeseries(el.id, kind as "node" | "line", metric, windowStartTs, Math.min(windowCount, 48))
      .then((r) => setData(r.t.map((t, i) => ({ t, v: r.v[i] }))))
      .catch(() => setData([]));
  }, [node, line, windowStartTs, windowCount]);

  const el = node ?? line;
  const title = node ? labelOf(node) : line ? labelOf(line) : "";
  const genTypes = node ? formatGenTypes(node.gen_types) : "";

  return (
    <div className="absolute bottom-3 left-3 z-20 max-h-[calc(100%-1.5rem)] w-[calc(100%-1.5rem)] max-w-[360px] overflow-y-auto rounded-xl border bg-popover/95 p-4 shadow-[0_14px_40px_rgba(5,12,16,.55)] backdrop-blur">
      <button
        className="absolute right-2 top-2 text-muted-foreground transition-colors hover:text-foreground"
        onClick={onClose}
        aria-label="Close details"
      >
        <X className="size-4" />
      </button>
      <div className="mb-0.5 flex items-center gap-1.5 pr-5">
        <h3 className="text-base font-semibold leading-snug">{title}</h3>
        {el && (
          <button
            type="button"
            onClick={() => onGoTo(node ? "node" : "line", el.id)}
            title={`Go to ${title} (zoom in on the current view)`}
            aria-label={`Go to ${title}`}
            className="inline-flex shrink-0 cursor-pointer items-center rounded p-0.5 text-muted-foreground/60 transition-colors hover:text-foreground"
          >
            <LocateFixedIcon className="size-3.5" />
          </button>
        )}
      </div>
      {el && labelOf(el) !== el.id && (
        <div className="-mt-0.5 mb-1.5 font-mono text-[10px] text-muted-foreground/70">{el.id}</div>
      )}

      {node && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <StatePill state={node.state} />
            <span>{node.is_slack ? "Slack bus" : NODE_KIND_LABEL[node.type]} · zone {node.zone} · {node.v_nominal_kv} kV</span>
          </div>
          {genTypes && (
            <div className="mb-2 text-[11px]">
              <span className="text-muted-foreground">Generator type: </span>
              <span className="font-medium text-foreground">{genTypes}</span>
            </div>
          )}
          {baseNode && baseNode.state !== node.state && (
            <div className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px]">
              <span className="text-muted-foreground">Simulation: </span>
              <span className="font-medium uppercase">
                {baseNode.state} → {node.state}
              </span>
            </div>
          )}
          <div className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <Row k="Voltage" v={`${node.vm_pu?.toFixed(3) ?? "—"} p.u. (${node.vm_kv ?? "—"} kV)`} />
            <Row k="Rated band" v={`${node.min_vm_pu}–${node.max_vm_pu} p.u.`} />
            <Row k="Net" v={`${node.net_mw} MW`} />
            <Row k="Production" v={`${node.production_mw} MW (${node.n_gens} gen)`} />
            <Row k="Consumption" v={`${node.consumption_mw} MW`} />
          </div>
        </>
      )}
      {line && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <StatePill state={line.state} />
            <span>{line.kind} · {line.from_node} → {line.to_node}</span>
          </div>
          {baseLine && baseLine.loading_pct != null && line.loading_pct != null && (
            <div className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px]">
              <span className="text-muted-foreground">Simulation: </span>
              <span className="font-medium tabular-nums">
                {baseLine.loading_pct}% → {line.loading_pct}%
              </span>{" "}
              <span className="tabular-nums text-amber-600 dark:text-amber-400">
                ({line.loading_pct - baseLine.loading_pct > 0 ? "+" : ""}
                {Math.round((line.loading_pct - baseLine.loading_pct) * 10) / 10}pp)
              </span>
            </div>
          )}
          <div className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <Row k="Loading" v={`${line.loading_pct ?? "—"}%`} />
            <Row
              k="Headroom"
              v={line.loading_pct != null ? `${Math.max(0, Math.round(100 - line.loading_pct))} pp` : "—"}
            />
            <Row k="P from" v={`${line.p_from_mw ?? "—"} MW`} />
            <Row k="P to" v={`${line.p_to_mw ?? "—"} MW`} />
            <Row k="Current / rating" v={`${line.i_ka ?? "—"} / ${line.max_i_ka || "—"} kA`} />
          </div>
        </>
      )}

      <div className="mb-1 mt-1 text-[12px] text-muted-foreground">
        {metricLabel} over the day
      </div>
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
          <XAxis dataKey="t" tickFormatter={hhmm} tick={{ fontSize: 10, fill: "#9daeb6" }} interval="preserveStartEnd" minTickGap={28} />
          <YAxis tick={{ fontSize: 10, fill: "#9daeb6" }} domain={["auto", "auto"]} width={40} />
          <Tooltip
            contentStyle={{ background: "#22333b", border: "1px solid #34454f", borderRadius: 6, fontSize: 12 }}
            labelFormatter={(t) => hhmm(String(t))}
          />
          {line && <ReferenceLine y={90} stroke="#f0503c" strokeDasharray="3 3" />}
          <Line type="monotone" dataKey="v" stroke="#afc0c8" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      {el && <AskAbout kind={node ? "node" : "line"} name={title} />}
    </div>
  );
}
