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
    <div role="status" className="sim-hatch z-10 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-sim-border px-5 py-2 text-[15px]">
      <Zap className="size-4 shrink-0 text-[#ee7a3b]" aria-hidden="true" />
      <span className="shrink-0 font-semibold">Simulation, not live</span>
      <span className="truncate text-foreground/90">{spec.label}</span>
      {s && (
        <span className="num shrink-0 text-foreground/85">
          Busiest line{" "}
          <span
            className={
              s.max_loading_pct >= 100
                ? "font-semibold text-destructive"
                : s.max_loading_pct >= 90
                  ? "font-semibold text-[#ee7a3b]"
                  : "font-medium"
            }
          >
            {s.max_loading_pct}%
          </span>
          {s.n_alerts > 0 && (
            <span className="ml-2 rounded-full bg-destructive px-1.5 py-0.5 text-[12px] font-semibold text-[#172229]">
              {s.n_alerts} alert{s.n_alerts === 1 ? "" : "s"}
            </span>
          )}
        </span>
      )}
      {divTime && (
        <span className="shrink-0 font-medium text-destructive">
          No solution from {divTime}
        </span>
      )}
      <Button
        size="sm"
        className="ml-auto h-9 shrink-0 gap-1.5 bg-foreground px-3 text-[14px] font-semibold text-background hover:bg-foreground/90"
        onClick={onExit}
      >
        <X className="size-3.5" aria-hidden="true" /> Back to live
      </Button>
    </div>
  );
}
