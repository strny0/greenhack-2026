import { Zap, X } from "lucide-react";
import type { ScenarioSpec, StateFrame } from "../types";
import { Button } from "@/components/ui/button";

/**
 * Always-visible strip under the TopBar while a failure simulation is active, so
 * the hypothetical scenario is never mistaken for real grid state — and so there
 * is a global exit even when another sidebar tab is open. Flags any hour whose
 * load flow diverged (islanding / collapse) in the scenario.
 */
export default function SimulationBadge({
  spec,
  frames,
  frame,
  onExit,
}: {
  spec: ScenarioSpec;
  frames: StateFrame[];
  /** The currently-viewed scenario frame, for live impact figures. */
  frame: StateFrame | null;
  onExit: () => void;
}) {
  const diverged = frames.find((f) => !f.summary.converged);
  const divTime = diverged
    ? new Date(diverged.timestamp).toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  const s = frame?.summary;

  return (
    <div className="z-10 flex items-center gap-3 border-b border-amber-500/40 bg-amber-500/15 px-4 py-1.5 text-sm">
      <Zap className="size-4 shrink-0 animate-pulse text-amber-500" />
      <span className="shrink-0 font-semibold tracking-wide text-amber-600 dark:text-amber-300">
        SIMULATION
      </span>
      <span className="truncate text-foreground/90">{spec.label}</span>
      {s && (
        <span className="shrink-0 tabular-nums text-foreground/80">
          · max line{" "}
          <span
            className={
              s.max_loading_pct >= 100
                ? "font-semibold text-red-500"
                : s.max_loading_pct >= 90
                  ? "font-semibold text-amber-600 dark:text-amber-400"
                  : "font-medium"
            }
          >
            {s.max_loading_pct}%
          </span>
          {s.n_alerts > 0 && (
            <span className="ml-2 rounded-full bg-red-500 px-1.5 py-0.5 text-[11px] font-semibold text-white">
              {s.n_alerts} alert{s.n_alerts === 1 ? "" : "s"}
            </span>
          )}
        </span>
      )}
      {divTime && (
        <span className="shrink-0 font-medium text-red-500">
          · diverged at {divTime}
        </span>
      )}
      <Button
        variant="ghost"
        size="sm"
        className="ml-auto h-7 shrink-0 gap-1 text-amber-700 hover:bg-amber-500/20 dark:text-amber-200"
        onClick={onExit}
      >
        <X className="size-3.5" /> Exit simulation
      </Button>
    </div>
  );
}
