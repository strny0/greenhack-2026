import { AlertTriangle, X } from "lucide-react";
import type { DeviationAssessment, DeviationRecord } from "../types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  dev: DeviationRecord;
  triage: DeviationAssessment | null;
  onShowGenerators: () => void;
  onExplain: () => void;
  onDismiss: () => void;
}

/**
 * Prominent interrupt for a high-risk / safety-net-forced hour as the clock lands
 * on it. Shows the headline and the non-negotiable force_notify reasons, and offers
 * to pinpoint the deviating generators on the map or hand off to the AI for a verdict.
 * Dismiss is per-timestamp (App tracks it), so it re-appears on the next risky hour.
 */
export default function DeviationBanner({
  dev,
  triage,
  onShowGenerators,
  onExplain,
  onDismiss,
}: Props) {
  const forced = dev.force_notify;
  const reasons = forced && dev.force_reasons.length ? dev.force_reasons : null;
  const nGens = triage?.worst_deviations?.length ?? 0;

  return (
    <div
      role="alert"
      className={cn(
        "pointer-events-auto absolute left-1/2 top-3 z-20 w-[min(92%,560px)] -translate-x-1/2",
        "rounded-lg border bg-card/95 p-3 shadow-lg backdrop-blur",
        forced ? "border-red-500/70" : "border-amber-500/60",
      )}
    >
      <div className="flex items-start gap-2.5">
        <AlertTriangle
          className={cn("mt-0.5 size-5 shrink-0", forced ? "text-red-400" : "text-amber-400")}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                forced ? "bg-red-500/20 text-red-300" : "bg-amber-500/20 text-amber-300",
              )}
            >
              {forced ? "Action required" : `${dev.risk_tier} risk`}
            </span>
            <span className="truncate text-sm font-semibold">{dev.headline}</span>
          </div>
          {reasons && (
            <ul className="mt-1 list-disc pl-4 text-[11px] text-red-300/90">
              {reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={onShowGenerators} disabled={nGens === 0}>
              {nGens > 0 ? `Show generators (${nGens})` : "Show generators"}
            </Button>
            <Button size="sm" variant="outline" onClick={onExplain}>
              Explain (AI)
            </Button>
          </div>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  );
}
