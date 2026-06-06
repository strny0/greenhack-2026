import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Meta, StateFrame } from "./types";
import MapView, { Selection } from "./components/MapView";
import SldView from "./components/SldView";
import TopBar from "./components/TopBar";
import Legend from "./components/Legend";
import DetailPanel from "./components/DetailPanel";
import Sidebar from "./components/Sidebar";
import {
  clampWindowStart,
  datasetDayBounds,
  dayStartIndex,
  keyToDate,
  lastDayStart,
} from "./lib/datetime";

const DAY_FRAMES = 24; // one calendar day per loaded window

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
  const timer = useRef<number | null>(null);
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
        // start at an interesting hour (evening peak ~18:00) if present
        const peak = w.findIndex((f) => f.timestamp.endsWith("T18:00:00"));
        setIdx(peak >= 0 ? peak : 0);
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

  const frame = frames[idx] ?? null;
  const windowStartTs = frames[0]?.timestamp ?? "";

  const total = meta?.count ?? 0;
  const selectDate = (date: Date) => {
    if (!meta) return;
    setWindowStart(clampWindowStart(dayStartIndex(meta.timestamps, date), total));
  };
  // Bookmarks point at a *moment*, not just a day: jump to the day and land on
  // noon (hour 12 of the aligned 24h window) regardless of the hour we were on.
  const selectBookmark = (date: Date) => {
    if (!meta) return;
    setWindowStart(clampWindowStart(dayStartIndex(meta.timestamps, date), total));
    setIdx(12);
  };
  const stepDay = (delta: -1 | 1) =>
    setWindowStart((s) => (s == null ? s : clampWindowStart(s + delta * DAY_FRAMES, total)));

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
        selectedDate={selectedDate}
        dayBounds={dayBounds}
        windowLoading={windowLoading}
        canPrev={canPrev && !windowLoading}
        canNext={canNext && !windowLoading}
        onSelectDate={selectDate}
        onSelectBookmark={selectBookmark}
        onStepDay={stepDay}
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
          <Legend showBusIcons={mode === "map"} />
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
          agentTimestamp={currentTs}
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
