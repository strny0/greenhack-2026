import { Pause, Play } from "lucide-react";
import type { StateFrame } from "../types";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import DateTimePicker from "./DateTimePicker";

interface Props {
  frame: StateFrame;
  frames: StateFrame[];
  idx: number;
  setIdx: (i: number) => void;
  playing: boolean;
  togglePlay: () => void;
  mode: "map" | "sld";
  onModeChange: (m: "map" | "sld") => void;
  selectedDate: Date;
  dayBounds: { first: Date; last: Date };
  windowLoading: boolean;
  canPrev: boolean;
  canNext: boolean;
  onSelectDate: (date: Date) => void;
  onStepDay: (delta: -1 | 1) => void;
}

const fmt = (ts: string) =>
  new Date(ts).toLocaleString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bad" | "warn";
}) {
  return (
    <div className="flex min-w-[72px] flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "text-[15px] font-semibold tabular-nums",
          tone === "bad" && "text-red-400",
          tone === "warn" && "text-amber-400",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export default function TopBar({
  frame,
  frames,
  idx,
  setIdx,
  playing,
  togglePlay,
  mode,
  onModeChange,
  selectedDate,
  dayBounds,
  windowLoading,
  canPrev,
  canNext,
  onSelectDate,
  onStepDay,
}: Props) {
  const s = frame.summary;
  return (
    <header className="z-10 flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-card px-4 py-2">
      <div className="flex items-center gap-2.5">
        <div>
          <h1 className="flex flex-col text-base font-semibold leading-tight tracking-wide">
            <span className="smooth-shimmer inline-block">Smooth</span>
            <span className="pl-5">Operator</span>
          </h1>
        </div>
      </div>

      <div
        className="flex overflow-hidden rounded-md border"
        role="tablist"
        aria-label="Visualization mode"
      >
        <Button
          role="tab"
          aria-selected={mode === "map"}
          variant={mode === "map" ? "default" : "ghost"}
          size="sm"
          className="rounded-none border-0"
          onClick={() => onModeChange("map")}
          title="Map view"
        >
          🗺 Map
        </Button>
        <Button
          role="tab"
          aria-selected={mode === "sld"}
          variant={mode === "sld" ? "default" : "ghost"}
          size="sm"
          className="rounded-none border-0"
          onClick={() => onModeChange("sld")}
          title="Schematic (single-line diagram) view"
        >
          ▦ Schematic
        </Button>
      </div>

      <div className="hidden flex-1 gap-5 lg:flex">
        <Kpi
          label="Generation"
          value={`${s.total_generation_mw.toLocaleString()} MW`}
        />
        <Kpi label="Load" value={`${s.total_load_mw.toLocaleString()} MW`} />
        <Kpi
          label="Balancing"
          value={`${s.slack_mw > 0 ? "+" : ""}${s.slack_mw} MW`}
        />
        <Kpi
          label="Max line load"
          value={`${s.max_loading_pct}%`}
          tone={
            s.max_loading_pct >= 90
              ? "bad"
              : s.max_loading_pct >= 75
                ? "warn"
                : undefined
          }
        />
        <Kpi
          label="Alerts"
          value={`${s.n_alerts} / ${s.n_warnings}w`}
          tone={s.n_alerts > 0 ? "bad" : s.n_warnings > 0 ? "warn" : undefined}
        />
        <Kpi
          label="Solver"
          value={s.converged ? "converged" : "diverged"}
          tone={s.converged ? undefined : "bad"}
        />
      </div>

      <div className="flex w-full flex-wrap items-center gap-3 md:w-auto md:flex-nowrap md:min-w-[360px] md:flex-1 lg:min-w-[560px] lg:flex-none">
        <Button
          variant="outline"
          size="icon"
          onClick={togglePlay}
          title="Play / pause"
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </Button>
        <DateTimePicker
          date={selectedDate}
          bounds={dayBounds}
          loading={windowLoading}
          canPrev={canPrev}
          canNext={canNext}
          onSelect={onSelectDate}
          onStep={onStepDay}
        />
        <Slider
          className="min-w-[120px] flex-1"
          min={0}
          max={Math.max(0, frames.length - 1)}
          step={1}
          value={[idx]}
          onValueChange={(v) => setIdx(v[0])}
        />
        <span className="min-w-[150px] text-right tabular-nums">
          {fmt(frame.timestamp)}
        </span>
      </div>
    </header>
  );
}
