import type { StateFrame } from "../types";
import { loadingColor } from "./styling";
import { cn } from "@/lib/utils";

const hh = (ts: string) =>
  new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/**
 * The next few hours beside the diagram, so the operator sees where the grid is
 * heading and not only where it is (situation awareness level 3, projection).
 * The dataset is a recorded year, so these are the recorded next hours, and the
 * label says so. Clicking an hour jumps the diagram and the chat to it.
 */
export default function ComingHours({
  frames,
  idx,
  onPick,
  simulating,
  count = 3,
}: {
  frames: StateFrame[];
  idx: number;
  onPick: (i: number) => void;
  simulating: boolean;
  count?: number;
}) {
  const next = frames
    .slice(idx + 1, idx + 1 + count)
    .map((f, k) => ({ f, i: idx + 1 + k }));
  if (!frames[idx]) return null;

  return (
    <div
      aria-label="Coming hours"
      className="flex items-stretch gap-2 border-t bg-card/40 px-3 py-2"
    >
      <div className="flex w-[92px] shrink-0 flex-col justify-center leading-tight">
        <span className="text-[13px] font-medium">Coming hours</span>
        <span className="text-[11px] text-muted-foreground">
          {simulating ? "simulated" : "recorded"}
        </span>
      </div>
      {next.length === 0 && (
        <span className="self-center text-[13px] text-muted-foreground">
          Last hour of the loaded day
        </span>
      )}
      {next.map(({ f, i }) => {
        const s = f.summary;
        const pct = s.max_loading_pct;
        return (
          <button
            key={f.timestamp}
            type="button"
            onClick={() => onPick(i)}
            title={`Show ${hh(f.timestamp)} on the diagram`}
            className={cn(
              "flex min-w-0 flex-1 flex-col gap-1 rounded-md border px-2.5 py-1.5 text-start transition-colors hover:bg-muted",
              !s.converged && "border-destructive",
            )}
          >
            <span className="flex items-baseline justify-between gap-2">
              <span className="num text-[13px] text-muted-foreground">{hh(f.timestamp)}</span>
              <span className="num text-[15px] font-semibold" title="Busiest line">{pct.toFixed(0)}%</span>
            </span>
            <span className="h-1 w-full overflow-hidden rounded-full bg-muted">
              <span
                className="block h-full rounded-full"
                style={{ width: `${Math.min(100, pct)}%`, background: loadingColor(pct) }}
              />
            </span>
            <span className="num truncate text-[12px] text-muted-foreground">
              {!s.converged
                ? "load flow fails"
                : `${s.n_alerts} ${s.n_alerts === 1 ? "alert" : "alerts"} · ${s.n_warnings} ${s.n_warnings === 1 ? "warning" : "warnings"}`}
            </span>
          </button>
        );
      })}
    </div>
  );
}
