import type { StateFrame } from "../types";

interface Props {
  frame: StateFrame;
  frames: StateFrame[];
  idx: number;
  setIdx: (i: number) => void;
  playing: boolean;
  togglePlay: () => void;
}

const fmt = (ts: string) =>
  new Date(ts).toLocaleString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

export default function TopBar({ frame, frames, idx, setIdx, playing, togglePlay }: Props) {
  const s = frame.summary;
  return (
    <div className="topbar">
      <div className="brand">
        <span className="pulse-dot" />
        <div>
          <h1>GRID&nbsp;PULSE</h1>
          <div className="sub">ČEPS · transmission situational awareness</div>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi">
          <span className="label">Generation</span>
          <span className="value">{s.total_generation_mw.toLocaleString()} MW</span>
        </div>
        <div className="kpi">
          <span className="label">Load</span>
          <span className="value">{s.total_load_mw.toLocaleString()} MW</span>
        </div>
        <div className="kpi">
          <span className="label">Balancing</span>
          <span className="value">{s.slack_mw > 0 ? "+" : ""}{s.slack_mw} MW</span>
        </div>
        <div className="kpi">
          <span className="label">Max line load</span>
          <span className={"value " + (s.max_loading_pct >= 90 ? "bad" : s.max_loading_pct >= 75 ? "warnv" : "")}>
            {s.max_loading_pct}%
          </span>
        </div>
        <div className="kpi">
          <span className="label">Alerts</span>
          <span className={"value " + (s.n_alerts > 0 ? "bad" : s.n_warnings > 0 ? "warnv" : "")}>
            {s.n_alerts} / {s.n_warnings}w
          </span>
        </div>
        <div className="kpi">
          <span className="label">Solver</span>
          <span className={"value " + (s.converged ? "" : "bad")}>{s.converged ? "converged" : "diverged"}</span>
        </div>
      </div>

      <div className="scrubber">
        <button className="btn play" onClick={togglePlay} title="Play / pause">
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(0, frames.length - 1)}
          value={idx}
          onChange={(e) => setIdx(Number(e.target.value))}
        />
        <span className="ts">{fmt(frame.timestamp)}</span>
      </div>
    </div>
  );
}
