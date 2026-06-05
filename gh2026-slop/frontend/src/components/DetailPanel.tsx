import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { api } from "../api";
import type { GridLine, GridNode } from "../types";

interface Props {
  node: GridNode | null;
  line: GridLine | null;
  windowStartTs: string;
  windowCount: number;
  onClose: () => void;
}

const hhmm = (ts: string) => new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

export default function DetailPanel({ node, line, windowStartTs, windowCount, onClose }: Props) {
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

  const title = node?.name ?? line?.name ?? "";

  return (
    <div className="detail">
      <span className="close" onClick={onClose}>✕</span>
      <h3>{title}</h3>
      {node && (
        <>
          <div className="meta">
            {node.type} · zone {node.zone} · {node.v_nominal_kv} kV {node.is_slack ? "· slack" : ""}
          </div>
          <div className="grid2">
            <span className="k">Voltage</span>
            <span className="v">{node.vm_pu?.toFixed(3) ?? "—"} p.u. ({node.vm_kv ?? "—"} kV)</span>
            <span className="k">Angle</span>
            <span className="v">{node.va_degree ?? "—"}°</span>
            <span className="k">Production</span>
            <span className="v">{node.production_mw} MW ({node.n_gens} gen)</span>
            <span className="k">Consumption</span>
            <span className="v">{node.consumption_mw} MW</span>
            <span className="k">Net</span>
            <span className="v">{node.net_mw} MW</span>
            <span className="k">Rated band</span>
            <span className="v">{node.min_vm_pu}–{node.max_vm_pu} p.u.</span>
          </div>
        </>
      )}
      {line && (
        <>
          <div className="meta">
            {line.kind} · {line.from_node} → {line.to_node} {line.in_service ? "" : "· OUT OF SERVICE"}
          </div>
          <div className="grid2">
            <span className="k">Loading</span>
            <span className="v">{line.loading_pct ?? "—"}%</span>
            <span className="k">P from</span>
            <span className="v">{line.p_from_mw ?? "—"} MW</span>
            <span className="k">P to</span>
            <span className="v">{line.p_to_mw ?? "—"} MW</span>
            <span className="k">Current</span>
            <span className="v">{line.i_ka ?? "—"} kA</span>
            <span className="k">Rating</span>
            <span className="v">{line.max_i_ka || "—"} kA</span>
          </div>
        </>
      )}
      <div className="section-title">{metricLabel} — window trend</div>
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
          <XAxis dataKey="t" tickFormatter={hhmm} tick={{ fontSize: 9, fill: "#8a99b0" }} interval="preserveStartEnd" minTickGap={28} />
          <YAxis tick={{ fontSize: 9, fill: "#8a99b0" }} domain={["auto", "auto"]} width={40} />
          <Tooltip
            contentStyle={{ background: "#121826", border: "1px solid #243044", fontSize: 11 }}
            labelFormatter={(t) => hhmm(String(t))}
          />
          {line && <ReferenceLine y={90} stroke="#ff4d4f" strokeDasharray="3 3" />}
          <Line type="monotone" dataKey="v" stroke="#2f81f7" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
