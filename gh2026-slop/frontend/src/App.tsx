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
  // A "fly the camera here" request. The nonce makes repeated jumps to the same
  // element re-trigger the view's effect (a new object identity each time).
  const [zoomTo, setZoomTo] = useState<{ kind: "node" | "line"; id: string; nonce: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"map" | "sld">("sld");
  const [progress, setProgress] = useState(0);
  const timer = useRef<number | null>(null);

  // load meta + initial window
  useEffect(() => {
    (async () => {
      try {
        const m = await api.meta();
        setMeta(m);
        // meta is in; reserve a sliver of the bar for it, then stream the window
        setProgress(0.04);
        const w = await api.windowProgress(
          m.default_window.start,
          m.default_window.count,
          (f) => setProgress(0.04 + f * 0.96),
        );
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
  const zoom = (kind: "node" | "line", id: string) =>
    setZoomTo({ kind, id, nonce: Date.now() });

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
      <div className="flex h-screen flex-col items-center justify-center bg-background">
        <div className="w-72 max-w-[80vw]">
          <div className="mb-3 text-center text-sm font-medium tracking-wide text-foreground">
            Loading <span className="smooth-shimmer">Smooth Operator</span>…
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
          <div className="mt-2 text-center text-xs tabular-nums text-muted-foreground">
            {progress < 0.04
              ? "Contacting backend…"
              : progress < 1
                ? `Fetching grid state… ${Math.round(progress * 100)}%`
                : "Rendering…"}
          </div>
        </div>
      </div>
    );

  return (
    <div className="flex h-[100dvh] flex-col bg-background text-foreground">
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
      {/* Mobile: stack the map above a collapsible chat/sidebar sheet.
          Desktop (md+): map left, resizable sidebar on the right. */}
      <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-0 flex-1">
          {mode === "map" ? (
            <MapView
              frame={frame}
              meta={meta}
              highlight={highlight}
              selected={selected}
              onSelect={setSelected}
              zoomTo={zoomTo}
            />
          ) : (
            <SldView
              frame={frame}
              meta={meta}
              highlight={highlight}
              selected={selected}
              onSelect={setSelected}
              zoomTo={zoomTo}
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
          onZoom={zoom}
        />
      </div>
    </div>
  );
}
