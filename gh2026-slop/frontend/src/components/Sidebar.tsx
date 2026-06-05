import { useMemo, useState } from "react";
import { api } from "../api";
import type { ContingencyResult, Meta, StateFrame, WeatherPoint, WhatIfResponse } from "../types";
import type { Selection } from "./MapView";

interface Props {
  frame: StateFrame;
  meta: Meta;
  onFocus: (ids: string[]) => void;
  onClearFocus: () => void;
  onSelect: (s: Selection | null) => void;
}

type Tab = "alerts" | "n1" | "whatif" | "weather" | "chat";

export default function Sidebar({ frame, meta, onFocus, onClearFocus, onSelect }: Props) {
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

  return (
    <div className="sidebar">
      <div className="tabs">
        {([
          ["alerts", "Alerts", nAlerts],
          ["n1", "N-1", 0],
          ["whatif", "What-if", 0],
          ["weather", "Weather", 0],
          ["chat", "Chat", 0],
        ] as [Tab, string, number][]).map(([t, label, badge]) => (
          <div key={t} className={"tab" + (tab === t ? " active" : "")} onClick={() => { setTab(t); onClearFocus(); }}>
            {label}
            {badge > 0 && <span className="badge">{badge}</span>}
          </div>
        ))}
      </div>
      <div className="tab-body">
        {tab === "alerts" && (
          <AlertsTab alerts={alerts} onPick={(id, kind) => { onFocus([id]); onSelect({ kind, id }); }} />
        )}
        {tab === "n1" && <N1Tab ts={frame.timestamp} onFocus={onFocus} onSelect={onSelect} />}
        {tab === "whatif" && <WhatIfTab frame={frame} onFocus={onFocus} onSelect={onSelect} />}
        {tab === "weather" && <WeatherTab />}
        {tab === "chat" && <ChatTab ts={frame.timestamp} meta={meta} />}
      </div>
    </div>
  );
}

function AlertsTab({ alerts, onPick }: { alerts: any[]; onPick: (id: string, kind: "line" | "node") => void }) {
  if (!alerts.length) return <div className="note">No active alerts or warnings at this timestamp. The grid is within limits.</div>;
  return (
    <>
      <div className="section-title">{alerts.length} active conditions</div>
      {alerts.map((a) => (
        <div key={a.kind + a.id} className="item" onClick={() => onPick(a.id, a.kind)}>
          <div className="title">
            <span>{a.id}</span>
            <span className={"pill " + a.sev}>{a.sev}</span>
          </div>
          <div className="desc">{a.msg}</div>
        </div>
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
      <div className="note">
        Deterministic N-1 security analysis: trip each line, re-solve the load flow, and rank by worst
        resulting stress. Non-converging trips = islanding / voltage collapse (most critical).
      </div>
      <button className="btn primary" onClick={run} disabled={loading} style={{ width: "100%", marginBottom: 10 }}>
        {loading ? "Running load flows…" : "Run N-1 analysis"}
      </button>
      {res &&
        res.slice(0, 25).map((r) => (
          <div
            key={r.contingency_id}
            className="item"
            onClick={() => {
              onFocus([r.contingency_id, ...r.overloaded.map((o) => o.id)]);
              onSelect({ kind: "line", id: r.contingency_id });
            }}
          >
            <div className="title">
              <span>trip {r.contingency_name}</span>
              {r.converged ? (
                <span className={"pill " + (r.max_loading_pct >= 100 ? "alert" : r.max_loading_pct >= 90 ? "warn" : "ok")}>
                  {r.max_loading_pct}%
                </span>
              ) : (
                <span className="pill crit">islanding</span>
              )}
            </div>
            <div className="desc">
              {r.converged
                ? r.n_overloads > 0
                  ? `${r.n_overloads} overloaded: ${r.overloaded.slice(0, 2).map((o) => `${o.name} ${o.loading_pct}%`).join(", ")}`
                  : "no overloads — grid survives this contingency"
                : "load flow does not converge — loss of supply / collapse"}
            </div>
          </div>
        ))}
    </>
  );
}

function WhatIfTab({ frame, onFocus, onSelect }: { frame: StateFrame; onFocus: (ids: string[]) => void; onSelect: (s: Selection) => void }) {
  const [disc, setDisc] = useState("");
  const [scale, setScale] = useState(1.0);
  const [res, setRes] = useState<WhatIfResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const lines = useMemo(() => [...frame.lines].sort((a, b) => (b.loading_pct ?? 0) - (a.loading_pct ?? 0)), [frame]);

  const run = async () => {
    setLoading(true);
    try {
      const r = await api.whatif({
        timestamp: frame.timestamp,
        disconnect_lines: disc ? [disc] : [],
        load_scale: scale,
      });
      setRes(r);
      const ids = [disc, ...r.diffs.slice(0, 8).map((d) => d.id)].filter(Boolean);
      onFocus(ids);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="note">Apply operator actions and re-run a real load flow. The map highlights what moves.</div>
      <div className="field">
        <label>Disconnect a line</label>
        <select value={disc} onChange={(e) => setDisc(e.target.value)}>
          <option value="">— none —</option>
          {lines.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name} ({l.loading_pct ?? 0}%)
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>
          Load multiplier <span className="range-val">×{scale.toFixed(2)}</span>
        </label>
        <input type="range" min={0.8} max={1.6} step={0.05} value={scale} onChange={(e) => setScale(Number(e.target.value))} />
      </div>
      <button className="btn primary" onClick={run} disabled={loading} style={{ width: "100%", marginBottom: 10 }}>
        {loading ? "Solving…" : "Run scenario"}
      </button>
      {res && (
        <>
          <div className="item" style={{ cursor: "default" }}>
            <div className="title">
              <span>Result</span>
              <span className={"pill " + (res.scenario.summary.converged ? (res.scenario.summary.max_loading_pct >= 100 ? "alert" : "ok") : "crit")}>
                {res.scenario.summary.converged ? `max ${res.scenario.summary.max_loading_pct}%` : "diverged"}
              </span>
            </div>
            <div className="desc">
              base max {res.base.summary.max_loading_pct}% → scenario {res.scenario.summary.converged ? `${res.scenario.summary.max_loading_pct}%` : "voltage collapse / islanding"} ·{" "}
              {res.new_alerts.length} new alert(s)
            </div>
          </div>
          <div className="section-title">Biggest loading changes</div>
          {res.diffs.slice(0, 10).map((d) => (
            <div key={d.id} className="item" onClick={() => onSelect({ kind: "line", id: d.id })}>
              <div className="title">
                <span>{d.name}</span>
                <span className={"pill " + (d.after >= 100 ? "alert" : d.after >= 90 ? "warn" : "ok")}>
                  {d.before}% → {d.after}%
                </span>
              </div>
              <div className="desc">Δ {d.delta > 0 ? "+" : ""}{d.delta} pts</div>
            </div>
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
      <div className="note">
        Live cloud cover &amp; wind (Open-Meteo) at the largest solar hubs, projected onto Czechia. The solar-drop
        flag is a lightweight heuristic — not a trained model.
      </div>
      <button className="btn primary" onClick={run} disabled={loading} style={{ width: "100%", marginBottom: 10 }}>
        {loading ? "Fetching forecast…" : "Fetch weather overlay"}
      </button>
      {data && <div className="item" style={{ cursor: "default" }}><div className="desc">{data.summary}</div></div>}
      {data?.points.map((p) => (
        <div key={p.bus} className="item" style={{ cursor: "default" }}>
          <div className="title">
            <span>{p.bus} · {p.solar_mw} MW PV</span>
            <span className={"pill " + (p.solar_risk ? "warn" : "ok")}>{p.solar_risk ? "PV drop risk" : "stable"}</span>
          </div>
          <div className="desc">
            cloud {p.cloud_cover_now}% → {p.cloud_cover_3h}% (3h) · wind {p.wind_speed_10m} km/h
          </div>
        </div>
      ))}
    </>
  );
}

function ChatTab({ ts, meta }: { ts: string; meta: Meta }) {
  const [log, setLog] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const next = [...log, { role: "user", content: text }];
    setLog(next);
    setInput("");
    setBusy(true);
    try {
      const r = await api.chat(ts, next);
      setLog([...next, { role: "assistant", content: r.reply }]);
    } catch (e: any) {
      setLog([...next, { role: "assistant", content: "Error: " + e }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chat">
      <div className="chat-log">
        {log.length === 0 && <div className="note">Ask the dispatcher assistant about the current grid state. Answers are grounded in the live snapshot.</div>}
        {log.map((m, i) => (
          <div key={i} className={"msg " + m.role}>{m.content}</div>
        ))}
        {busy && <div className="msg assistant">…</div>}
      </div>
      <div className="chat-suggestions">
        {meta.suggested_questions.slice(0, 5).map((q) => (
          <span key={q} className="chip" onClick={() => send(q)}>{q}</span>
        ))}
      </div>
      <div className="chat-input">
        <input
          value={input}
          placeholder="Ask about the grid…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
        />
        <button className="btn primary" onClick={() => send(input)} disabled={busy}>Send</button>
      </div>
    </div>
  );
}
