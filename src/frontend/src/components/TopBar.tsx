import { Pause, Play } from "lucide-react";
import type { StateFrame } from "../types";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import DateTimePicker from "./DateTimePicker";
import BookmarksMenu from "./BookmarksMenu";

interface Props {
  frame: StateFrame;
  frames: StateFrame[];
  idx: number;
  setIdx: (i: number) => void;
  playing: boolean;
  togglePlay: () => void;
  mode?: "map" | "sld";
  onModeChange?: (m: "map" | "sld") => void;
  selectedDate: Date;
  dayBounds: { first: Date; last: Date };
  windowLoading: boolean;
  canPrev: boolean;
  canNext: boolean;
  onSelectDate: (date: Date) => void;
  onSelectBookmark: (date: Date) => void;
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
  className,
}: {
  label: string;
  value: string;
  tone?: "bad" | "warn";
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col", className)}>
      <dt className="whitespace-nowrap text-[12px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "num m-0 whitespace-nowrap text-[17px] font-medium",
          tone === "bad" && "text-destructive",
          tone === "warn" && "text-[#d9a441]",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/** Wordmark: a pulse inside a ring, the grid's heartbeat. */
function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
        <circle cx="13" cy="13" r="11" fill="none" stroke="var(--primary)" strokeWidth="2" />
        <path d="M3 13h5l2.5-5 5 10 2.5-5h5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      </svg>
      <span className="whitespace-nowrap text-lg font-bold tracking-[-0.01em]">Smooth Operator</span>
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
  onSelectBookmark,
  onStepDay,
}: Props) {
  const s = frame.summary;
  return (
    <header className="z-10 flex flex-wrap items-center gap-x-6 gap-y-2 border-b bg-card px-5 py-2.5 lg:flex-nowrap">
      <Brand />

      <dl className="m-0 hidden flex-1 gap-5 lg:flex">
        <Kpi
          label="Generation"
          value={`${s.total_generation_mw.toLocaleString()} MW`}
        />
        <Kpi label="Load" value={`${s.total_load_mw.toLocaleString()} MW`} />
        <Kpi
          className="hidden min-[1440px]:flex"
          label="Balancing"
          value={`${s.slack_mw > 0 ? "+" : ""}${s.slack_mw} MW`}
        />
        <Kpi
          label="Busiest line"
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
          label="Alerts / warnings"
          value={`${s.n_alerts} / ${s.n_warnings}`}
          tone={s.n_alerts > 0 ? "bad" : s.n_warnings > 0 ? "warn" : undefined}
        />
        <Kpi
          label="Load flow"
          value={s.converged ? "Converged" : "No solution"}
          tone={s.converged ? undefined : "bad"}
          // Only worth the space on narrower screens when it has failed.
          className={s.converged ? "hidden min-[1440px]:flex" : undefined}
        />
      </dl>

      <div className="flex w-full flex-wrap items-center gap-3 md:w-auto md:flex-nowrap md:min-w-[360px] md:flex-1 lg:min-w-[400px] lg:flex-none">
        <Button
          variant="outline"
          size="icon"
          onClick={togglePlay}
          title="Play / pause"
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </Button>
        <BookmarksMenu currentDate={selectedDate} onSelect={onSelectBookmark} />
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
        <span className="num min-w-[52px] text-right text-[18px] font-semibold" title={fmt(frame.timestamp)}>
          {new Date(frame.timestamp).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </header>
  );
}
