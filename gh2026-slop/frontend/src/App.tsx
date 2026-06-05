import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Meta, StateFrame } from "./types";
import MapView, { Selection } from "./components/MapView";
import SldView from "./components/SldView";
import TopBar from "./components/TopBar";
import Legend from "./components/Legend";
import DetailPanel from "./components/DetailPanel";
import Sidebar from "./components/Sidebar";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [frames, setFrames] = useState<StateFrame[]>([]);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"map" | "sld">("sld");
  const timer = useRef<number | null>(null);

  // load meta + initial window
  useEffect(() => {
    (async () => {
      try {
        const m = await api.meta();
        setMeta(m);
        const w = await api.window(m.default_window.start, m.default_window.count);
        setFrames(w);
        // start at an interesting hour (evening peak ~18:00) if present
        const peak = w.findIndex((f) => f.timestamp.endsWith("T18:00:00"));
        setIdx(peak >= 0 ? peak : 0);
      } catch (e: any) {
        setError(String(e));
      }
    })();
  }, []);

  // playback loop
  useEffect(() => {
    if (playing && frames.length) {
      timer.current = window.setInterval(() => {
        setIdx((i) => (i + 1) % frames.length);
      }, 900);
    }
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [playing, frames.length]);

  const frame = frames[idx] ?? null;
  const windowStartTs = frames[0]?.timestamp ?? "";

  const focus = (ids: string[]) => setHighlight(new Set(ids));
  const clearFocus = () => setHighlight(new Set());

  const selectedNode = useMemo(
    () => (selected?.kind === "node" ? frame?.nodes.find((n) => n.id === selected.id) ?? null : null),
    [selected, frame],
  );
  const selectedLine = useMemo(
    () => (selected?.kind === "line" ? frame?.lines.find((l) => l.id === selected.id) ?? null : null),
    [selected, frame],
  );

  if (error)
    return (
      <div className="flex h-screen items-center justify-center bg-background px-6 text-center text-muted-foreground">
        Backend unreachable: {error}. Start it with{" "}
        <code className="mx-1 rounded bg-muted px-1.5 py-0.5 text-foreground">cd backend &amp;&amp; ./run.sh</code>
      </div>
    );
  if (!meta || !frame)
    return (
      <div className="flex h-screen items-center justify-center bg-background text-muted-foreground">
        Loading Grid Pulse…
      </div>
    );

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <TopBar
        frame={frame}
        frames={frames}
        idx={idx}
        setIdx={(i) => {
          setPlaying(false);
          setIdx(i);
        }}
        playing={playing}
        togglePlay={() => setPlaying((p) => !p)}
        mode={mode}
        onModeChange={setMode}
      />
      <div className="relative flex min-h-0 flex-1">
        <div className="relative flex-1">
          {mode === "map" ? (
            <MapView
              frame={frame}
              meta={meta}
              highlight={highlight}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <SldView
              frame={frame}
              meta={meta}
              highlight={highlight}
              selected={selected}
              onSelect={setSelected}
            />
          )}
          <Legend />
          {(selectedNode || selectedLine) && (
            <DetailPanel
              node={selectedNode}
              line={selectedLine}
              windowStartTs={windowStartTs}
              windowCount={frames.length}
              onClose={() => setSelected(null)}
            />
          )}
        </div>
        <Sidebar
          frame={frame}
          meta={meta}
          selected={selected}
          onFocus={focus}
          onClearFocus={clearFocus}
          onSelect={setSelected}
        />
      </div>
    </div>
  );
}
