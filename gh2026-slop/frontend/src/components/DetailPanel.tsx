import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { LocateFixedIcon, X } from "lucide-react";
import { api } from "../api";
import type { GridLine, GridNode } from "../types";
import { formatGenTypes, labelOf, NODE_KIND_LABEL } from "@/lib/gridmeta";

interface Props {
  node: GridNode | null;
  line: GridLine | null;
  windowStartTs: string;
  windowCount: number;
  onClose: () => void;
  /** Fly the camera to the selected element on whichever view is active. */
  onGoTo: (kind: "node" | "line", id: string) => void;
}

const hhmm = (ts: string) => new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right tabular-nums">{v}</span>
    </>
  );
}

export default function DetailPanel({ node, line, windowStartTs, windowCount, onClose, onGoTo }: Props) {
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
    <div className="absolute bottom-3 left-3 z-20 w-[calc(100%-1.5rem)] max-w-[340px] rounded-xl border bg-card/95 p-3.5 shadow-lg backdrop-blur">
      <button
        className="absolute right-2 top-2 text-muted-foreground transition-colors hover:text-foreground"
        onClick={onClose}
      >
        <X className="size-4" />
      </button>
      <div className="mb-0.5 flex items-center gap-1.5 pr-5">
        <h3 className="text-sm font-semibold">{title}</h3>
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

      {node && (
        <>
          <div className="mb-2 text-[11px] text-muted-foreground">
            {node.is_slack ? "Slack bus" : NODE_KIND_LABEL[node.type]} · zone {node.zone} · {node.v_nominal_kv} kV
          </div>
          {genTypes && (
            <div className="mb-2 text-[11px]">
              <span className="text-muted-foreground">Generator type: </span>
              <span className="font-medium text-foreground">{genTypes}</span>
            </div>
          )}
          <div className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <Row k="Voltage" v={`${node.vm_pu?.toFixed(3) ?? "—"} p.u. (${node.vm_kv ?? "—"} kV)`} />
            <Row k="Angle" v={`${node.va_degree ?? "—"}°`} />
            <Row k="Production" v={`${node.production_mw} MW (${node.n_gens} gen)`} />
            <Row k="Consumption" v={`${node.consumption_mw} MW`} />
            <Row k="Net" v={`${node.net_mw} MW`} />
            <Row k="Rated band" v={`${node.min_vm_pu}–${node.max_vm_pu} p.u.`} />
          </div>
        </>
      )}
      {line && (
        <>
          <div className="mb-2 text-[11px] text-muted-foreground">
            {line.kind} · {line.from_node} → {line.to_node} {line.in_service ? "" : "· OUT OF SERVICE"}
          </div>
          <div className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <Row k="Loading" v={`${line.loading_pct ?? "—"}%`} />
            <Row k="P from" v={`${line.p_from_mw ?? "—"} MW`} />
            <Row k="P to" v={`${line.p_to_mw ?? "—"} MW`} />
            <Row k="Current" v={`${line.i_ka ?? "—"} kA`} />
            <Row k="Rating" v={`${line.max_i_ka || "—"} kA`} />
          </div>
        </>
      )}

      <div className="mb-1 mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">
        {metricLabel} — window trend
      </div>
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
          <XAxis dataKey="t" tickFormatter={hhmm} tick={{ fontSize: 9, fill: "#a1a1aa" }} interval="preserveStartEnd" minTickGap={28} />
          <YAxis tick={{ fontSize: 9, fill: "#a1a1aa" }} domain={["auto", "auto"]} width={40} />
          <Tooltip
            contentStyle={{ background: "#1f1f23", border: "1px solid #3f3f46", borderRadius: 6, fontSize: 11 }}
            labelFormatter={(t) => hhmm(String(t))}
          />
          {line && <ReferenceLine y={90} stroke="#ef4444" strokeDasharray="3 3" />}
          <Line type="monotone" dataKey="v" stroke="#3b82f6" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
