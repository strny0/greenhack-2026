import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Meta, PresetKey, ScenarioSpec, StateFrame } from "./types";
import MapView, { Selection } from "./components/MapView";
import SldView from "./components/SldView";
import TopBar from "./components/TopBar";
import Legend from "./components/Legend";
import DetailPanel from "./components/DetailPanel";
import Sidebar from "./components/Sidebar";
import SimulationBadge from "./components/SimulationBadge";
import ComingHours from "./components/ComingHours";
import { AgentRuntimeProvider } from "./agent/AgentRuntimeProvider";
import { AskContextCtx, type AskContext } from "./agent/ask-context";
import { labelOf } from "./lib/gridmeta";
import { cn } from "./lib/utils";
import {
  clampWindowStart,
  datasetDayBounds,
  dayStartIndex,
  keyToDate,
  lastDayStart,
} from "./lib/datetime";

const DAY_FRAMES = 24; // one calendar day per loaded window

// The diagram pane shares the screen with the chat. Operator-resizable; the
// chat takes the rest. Width persists across reloads.
const DIAGRAM_MIN = 360;
// The diagram gets 60% of the width by default; the chat keeps at least 420px.
// Stored as a fraction so the split holds across screen sizes.
const DIAGRAM_DEFAULT_FRAC = 0.6;
const CHAT_MIN = 420;
const DIAGRAM_KEY = "diagram-frac";

const hourLabel = (ts: string) =>
  ts
    ? new Date(ts).toLocaleString("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

/** Reactive media-query match (desktop side-by-side vs stacked on phones). */
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

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [frames, setFrames] = useState<StateFrame[]>([]);
  const [idx, setIdx] = useState(0);
  const [windowStart, setWindowStart] = useState<number | null>(null);
  const [windowLoading, setWindowLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  // A "fly the camera here" request. The nonce makes repeated jumps to the same
  // element re-trigger the view's effect (a new object identity each time).
  const [zoomTo, setZoomTo] = useState<{ kind: "node" | "line"; id: string; nonce: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"map" | "sld">("sld");
  const [progress, setProgress] = useState(0);
  // Active whole-day failure simulation. When set, the views render the scenario
  // frames; the base frames are kept so the overlay can show the delta vs normal.
  const [simulation, setSimulation] = useState<{
    spec: ScenarioSpec;
    baseFrames: StateFrame[];
    scenarioFrames: StateFrame[];
  } | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const isDesktop = useMediaQuery("(min-width: 900px)");
  const [diagramFrac, setDiagramFrac] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(DIAGRAM_KEY));
      return saved > 0.15 && saved < 0.9 ? saved : DIAGRAM_DEFAULT_FRAC;
    } catch {
      return DIAGRAM_DEFAULT_FRAC;
    }
  });
  const resizing = useRef(false);
  const onResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    resizing.current = true;
  }, []);
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (!resizing.current) return;
      // Handle sits on the pane's left edge; keep at least CHAT_MIN for the chat.
      const vw = window.innerWidth;
      const px = Math.min(vw - CHAT_MIN, Math.max(DIAGRAM_MIN, vw - e.clientX));
      setDiagramFrac(px / vw);
    };
    const onUp = () => {
      if (!resizing.current) return;
      resizing.current = false;
      try {
        localStorage.setItem(DIAGRAM_KEY, String(diagramFrac));
      } catch {
        /* storage unavailable: the split just isn't remembered */
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [diagramFrac]);
  // The first window load shows the full-screen progress bar and jumps to the
  // evening peak; later loads (a date change) keep the old frames on screen.
  const initialLoad = useRef(true);
  // Loaded day-windows, keyed by start index. Stepping to a day we've already
  // seen (or prefetched) is instant. Bounded so we don't hoard a whole year.
  const windowCache = useRef<Map<number, StateFrame[]>>(new Map());
  const inFlight = useRef<Set<number>>(new Set());

  // load meta, then point at the default day (its window load is the effect below)
  useEffect(() => {
    (async () => {
      try {
        const m = await api.meta();
        setMeta(m);
        setProgress(0.04);
        setWindowStart(clampWindowStart(m.default_window.start, m.count));
      } catch (e: any) {
        setError(String(e));
      }
    })();
  }, []);

  // load the 24h window whenever the selected day changes
  useEffect(() => {
    if (!meta || windowStart == null) return;
    let cancelled = false;
    const isInitial = initialLoad.current;
    const total = meta.count;
    const CACHE_CAP = 24; // ~24 days of frames kept in memory

    const cacheSet = (start: number, w: StateFrame[]) => {
      const c = windowCache.current;
      c.delete(start);
      c.set(start, w); // (re)insert as most-recent
      while (c.size > CACHE_CAP) c.delete(c.keys().next().value as number);
    };

    // Warm the previous/next day in the background so left/right stepping is
    // instant (also warms the backend's per-frame LRU).
    const prefetchNeighbors = (start: number) => {
      for (const s of [start - DAY_FRAMES, start + DAY_FRAMES]) {
        if (s < 0 || s > lastDayStart(total)) continue;
        if (windowCache.current.has(s) || inFlight.current.has(s)) continue;
        inFlight.current.add(s);
        api
          .window(s, DAY_FRAMES)
          .then((w) => cacheSet(s, w))
          .catch(() => {})
          .finally(() => inFlight.current.delete(s));
      }
    };

    const apply = (w: StateFrame[]) => {
      setFrames(w);
      if (isInitial) {
        // Land on the backend's configured default hour; fall back to the evening
        // peak (~18:00) if the meta didn't carry an explicit offset.
        const want = meta.default_window.idx;
        const target =
          want != null ? want : w.findIndex((f) => f.timestamp.endsWith("T18:00:00"));
        setIdx(Math.max(0, Math.min(target, w.length - 1)));
        initialLoad.current = false;
      } else {
        // aligned 24h days -> keeping idx keeps the same hour-of-day
        setIdx((i) => Math.min(i, Math.max(0, w.length - 1)));
      }
      prefetchNeighbors(windowStart);
    };

    if (!isInitial) setPlaying(false);

    const cached = windowCache.current.get(windowStart);
    if (cached) {
      setWindowLoading(false);
      apply(cached);
      return () => {
        cancelled = true;
      };
    }

    setWindowLoading(true);
    (async () => {
      try {
        const w = await api.windowProgress(
          windowStart,
          DAY_FRAMES,
          isInitial ? (f) => setProgress(0.04 + f * 0.96) : undefined,
        );
        if (cancelled) return;
        cacheSet(windowStart, w);
        apply(w);
      } catch (e: any) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setWindowLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [meta, windowStart]);

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

  // What the views render: scenario frames when a simulation is active, else the
  // real loaded window. `baseFrame` (the un-failed hour) feeds the delta overlay.
  const renderFrames = simulation ? simulation.scenarioFrames : frames;
  const frame = renderFrames[idx] ?? null;
  const baseFrame = simulation ? simulation.baseFrames[idx] ?? null : null;
  const windowStartTs = frames[0]?.timestamp ?? "";

  const total = meta?.count ?? 0;
  // Day changes are bound to the loaded day, so they exit any active simulation.
  const selectDate = (date: Date) => {
    if (!meta) return;
    setSimulation(null);
    setWindowStart(clampWindowStart(dayStartIndex(meta.timestamps, date), total));
  };
  // Bookmarks point at a *moment*, not just a day: jump to the day and land on
  // noon (hour 12 of the aligned 24h window) regardless of the hour we were on.
  const selectBookmark = (date: Date) => {
    if (!meta) return;
    setSimulation(null);
    setWindowStart(clampWindowStart(dayStartIndex(meta.timestamps, date), total));
    setIdx(12);
  };
  const stepDay = (delta: -1 | 1) => {
    setSimulation(null);
    setWindowStart((s) => (s == null ? s : clampWindowStart(s + delta * DAY_FRAMES, total)));
  };

  // Apply a failure preset to the whole loaded day: fetch the 24h scenario window,
  // keep the current frames as the base for delta overlays, and render the scenario.
  const activateSim = async (preset: PresetKey) => {
    if (windowStart == null || !frames.length) return;
    const base = frames;
    setSimError(null);
    setSimLoading(true);
    try {
      const r = await api.whatifWindow(windowStart, DAY_FRAMES, preset);
      setSimulation({ spec: r.scenario, baseFrames: base, scenarioFrames: r.frames });
      setPlaying(false);
    } catch (e: any) {
      setSimError(String(e?.message ?? e));
    } finally {
      setSimLoading(false);
    }
  };
  const exitSim = () => {
    setSimulation(null);
    setSimError(null);
  };

  // The viewed snapshot timestamp, read straight from `meta` (selected day +
  // hour-of-day). Unlike `frame.timestamp` this updates the instant the day
  // changes — before the window's grid data finishes loading — so the agent's
  // context never lags behind a jump to an uncached day (e.g. via a bookmark).
  const currentTs =
    meta && windowStart != null
      ? meta.timestamps[Math.min(windowStart + idx, total - 1)] ?? ""
      : "";

  const selectedDate = useMemo(
    () =>
      meta && windowStart != null
        ? keyToDate(meta.timestamps[windowStart].slice(0, 10))
        : new Date(),
    [meta, windowStart],
  );
  const dayBounds = useMemo(
    () => (meta ? datasetDayBounds(meta.timestamps) : { first: new Date(), last: new Date() }),
    [meta],
  );
  const canPrev = windowStart != null && windowStart > 0;
  const canNext = windowStart != null && windowStart < lastDayStart(total);

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
  // Pre-failure values for the selected element, so DetailPanel can show the delta.
  const baseNode = useMemo(
    () => (selected?.kind === "node" ? baseFrame?.nodes.find((n) => n.id === selected.id) ?? null : null),
    [selected, baseFrame],
  );
  const baseLine = useMemo(
    () => (selected?.kind === "line" ? baseFrame?.lines.find((l) => l.id === selected.id) ?? null : null),
    [selected, baseFrame],
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

  const selectedEl = selectedNode ?? selectedLine;
  const askContext: AskContext = {
    hourLabel: hourLabel(currentTs || frame.timestamp),
    selectionLabel: selectedEl ? labelOf(selectedEl) : null,
    simulationLabel: simulation ? simulation.spec.label : null,
    clearSelection: () => setSelected(null),
  };

  const diagram = (
    <section
      aria-label="Grid diagram"
      className={cn(
        "relative flex min-h-0 flex-col border-border bg-background",
        isDesktop ? "h-full shrink-0 border-l" : "h-[44dvh] shrink-0 border-b",
      )}
      style={
        isDesktop
          ? { width: `${diagramFrac * 100}%`, minWidth: DIAGRAM_MIN, maxWidth: `calc(100% - ${CHAT_MIN}px)` }
          : undefined
      }
    >
      {isDesktop && (
        <div
          onPointerDown={onResizeStart}
          className="absolute -left-1 top-0 z-30 h-full w-2 cursor-col-resize select-none transition-colors hover:bg-primary/30"
          title="Drag to resize"
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2">
        <div
          role="tablist"
          aria-label="Diagram view"
          className="inline-flex rounded-[10px] border bg-card p-[3px]"
        >
          {([
            ["map", "Map"],
            ["sld", "Schematic"],
          ] as const).map(([m, label]) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                "h-8 rounded-[7px] px-3 text-sm font-medium transition-colors",
                mode === m ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-[13px] text-muted-foreground">
          Click a line or substation to ask about it
        </span>
      </div>
      <div className={cn("relative min-h-0 flex-1", simulation && "sim-frame")}>
        {mode === "map" ? (
          <MapView
            frame={frame}
            meta={meta}
            highlight={highlight}
            selected={selected}
            onSelect={setSelected}
            zoomTo={zoomTo}
            baseFrame={baseFrame}
            simulating={!!simulation}
          />
        ) : (
          <SldView
            frame={frame}
            meta={meta}
            highlight={highlight}
            selected={selected}
            onSelect={setSelected}
            zoomTo={zoomTo}
            baseFrame={baseFrame}
            simulating={!!simulation}
          />
        )}
        <Legend showBusIcons={mode === "map"} />
      </div>
      {(selectedNode || selectedLine) && (
        <DetailPanel
          node={selectedNode}
          line={selectedLine}
          baseNode={baseNode}
          baseLine={baseLine}
          windowStartTs={windowStartTs}
          windowCount={renderFrames.length}
          onClose={() => setSelected(null)}
          onGoTo={zoom}
        />
      )}
      <ComingHours
        frames={renderFrames}
        idx={idx}
        simulating={!!simulation}
        onPick={(i) => {
          setPlaying(false);
          setIdx(i);
        }}
      />
    </section>
  );

  return (
    // One agent runtime for the whole app, so the chat, the diagram's
    // "ask about this" card and the composer's context row share it.
    <AgentRuntimeProvider
      timestamp={currentTs || frame.timestamp}
      selection={selected}
      simulation={simulation?.spec ?? null}
    >
      <AskContextCtx.Provider value={askContext}>
        <div className="dark flex h-[100dvh] flex-col bg-background text-foreground">
          <TopBar
            frame={frame}
            frames={renderFrames}
            idx={idx}
            setIdx={(i) => {
              setPlaying(false);
              setIdx(i);
            }}
            playing={playing}
            togglePlay={() => setPlaying((p) => !p)}
            selectedDate={selectedDate}
            dayBounds={dayBounds}
            windowLoading={windowLoading}
            canPrev={canPrev && !windowLoading}
            canNext={canNext && !windowLoading}
            onSelectDate={selectDate}
            onSelectBookmark={selectBookmark}
            onStepDay={stepDay}
          />
          {simulation && (
            <SimulationBadge
              spec={simulation.spec}
              frames={simulation.scenarioFrames}
              frame={frame}
              onExit={exitSim}
            />
          )}
          {/* Chat is the main surface; the diagram sits beside it on desktop and
              above it on phones. */}
          <div className={cn("relative flex min-h-0 flex-1", isDesktop ? "flex-row" : "flex-col")}>
            {!isDesktop && diagram}
            <Sidebar
              frame={frame}
              meta={meta}
              selected={selected}
              onFocus={focus}
              onClearFocus={clearFocus}
              onSelect={setSelected}
              onZoom={zoom}
              simulation={simulation ? { spec: simulation.spec } : null}
              simLoading={simLoading}
              simError={simError}
              onActivateSim={activateSim}
              onExitSim={exitSim}
            />
            {isDesktop && diagram}
          </div>
        </div>
      </AskContextCtx.Provider>
    </AgentRuntimeProvider>
  );
}
