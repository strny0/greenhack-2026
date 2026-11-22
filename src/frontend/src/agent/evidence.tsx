import { useState, type FC } from "react";
import { CheckIcon, ChevronRightIcon, LoaderIcon, SquareIcon } from "lucide-react";
import { useAuiState, useThreadRuntime } from "@assistant-ui/react";
import { useAskContext } from "@/agent/ask-context";
import { cn } from "@/lib/utils";

/**
 * Plain-words account of what the agent looked at, so an operator can check an
 * answer before acting on it. Two places use it: the live step list while the
 * agent works (with Stop), and the "How I got this" trail under each answer.
 */

type Args = Record<string, unknown> | undefined;

const str = (v: unknown) => (v == null || v === "" ? null : String(v));

/** One sentence per tool call, in the operator's words. */
export function describeStep(toolName: string, args: Args, running = false): string {
  const a = args ?? {};
  const done = !running;
  switch (toolName) {
    case "grid_summary":
      return done ? "Read the grid totals" : "Reading the grid totals";
    case "summary_at":
      return `${done ? "Read" : "Reading"} the grid totals for ${str(a.timestamp) ? fmtTs(String(a.timestamp)) : "another hour"}`;
    case "compare_to":
      return `${done ? "Compared" : "Comparing"} with ${a.hours_ago ?? 24} hours earlier`;
    case "most_loaded_lines":
      return done ? "Ranked the busiest lines" : "Ranking the busiest lines";
    case "line_detail":
      return `${done ? "Looked up" : "Looking up"} line ${str(a.line_id) ?? ""}`.trim();
    case "node_detail":
      return `${done ? "Looked up" : "Looking up"} bus ${str(a.node_id) ?? ""}`.trim();
    case "bus_neighbors":
      return `${done ? "Traced" : "Tracing"} what connects to ${str(a.bus_id) ?? "the bus"}`;
    case "active_alerts":
      return done ? "Checked the active alerts" : "Checking the active alerts";
    case "element_history":
      return `${done ? "Read" : "Reading"} the history of ${str(a.element_id) ?? "the element"}`;
    case "n1_contingency_analysis":
      return done ? "Tested every single outage (N-1)" : "Testing every single outage (N-1)";
    case "what_if":
      return whatIfStep(a, done);
    case "simulation_status":
      return done ? "Checked the running simulation" : "Checking the running simulation";
    case "forecast_deviation_triage":
      return done ? "Compared the plan with what happened" : "Comparing the plan with what happened";
    case "weather_overlay":
    case "weather":
      return done ? "Read the weather" : "Reading the weather";
    case "run_python":
      return done ? "Ran a calculation" : "Running a calculation";
    case "explain_hour":
      return done ? "Explained what is unusual about the hour" : "Explaining what is unusual about the hour";
    case "plan_adherence":
      return done ? "Checked how the day kept to plan" : "Checking how the day kept to plan";
    case "loading_context":
      return done ? "Compared loading with the rest of the year" : "Comparing loading with the rest of the year";
    case "interesting_days":
      return done ? "Looked for unusual days" : "Looking for unusual days";
    case "deep_dive":
      return done ? "Took a deep look at the hour" : "Taking a deep look at the hour";
    case "long_term_trends":
      return done ? "Read the long-term trends" : "Reading the long-term trends";
    default:
      return toolName.replace(/_/g, " ");
  }
}

function whatIfStep(a: Record<string, unknown>, done: boolean): string {
  const t = str(a.target);
  switch (a.op) {
    case "trip_line":
      return `${done ? "Simulated" : "Simulating"} line ${t ?? ""} tripping`.trim();
    case "trip_bus":
      return `${done ? "Simulated" : "Simulating"} losing bus ${t ?? ""}`.trim();
    case "scale_load":
      return `${done ? "Simulated" : "Simulating"} load at ${Math.round(Number(a.factor ?? 1) * 100)}%`;
    case "undo":
      return done ? "Undid the last simulated change" : "Undoing the last simulated change";
    case "reset":
      return done ? "Cleared the simulation" : "Clearing the simulation";
    default:
      return done ? "Checked the simulation" : "Checking the simulation";
  }
}

function fmtTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Tools that read the hour on screen, so they see a simulated grid when one is active. */
const CURRENT_HOUR_TOOLS = new Set([
  "grid_summary", "most_loaded_lines", "line_detail", "node_detail", "bus_neighbors",
  "active_alerts", "explain_hour", "loading_context", "deep_dive", "simulation_status",
]);

export interface Step {
  text: string;
  /** Which hour the lookup read, when it isn't the hour on screen. */
  hour: string | null;
  source: "Live" | "Simulation";
  running: boolean;
}

type PartLike = {
  type: string;
  toolName?: string;
  args?: unknown;
  result?: unknown;
  status?: { type: string };
};

/**
 * Turn a message's tool-call parts into steps. A step is Simulation when it
 * read a hypothetical grid: an operator simulation was on when it was asked,
 * the agent's own what-if sandbox held a move at the time, or it is a what-if.
 */
export function buildSteps(parts: readonly PartLike[], operatorSim: boolean): Step[] {
  let sandbox = false;
  const steps: Step[] = [];
  for (const p of parts) {
    if (p.type !== "tool-call" || !p.toolName) continue;
    const args = (p.args ?? undefined) as Args;
    const running = p.result === undefined;
    let source: Step["source"] = "Live";
    if (p.toolName === "what_if") {
      const r = p.result as { n_actions?: number } | undefined;
      if (r && typeof r.n_actions === "number") sandbox = r.n_actions > 0;
      source = args?.op === "reset" && !operatorSim ? "Live" : "Simulation";
    } else if (CURRENT_HOUR_TOOLS.has(p.toolName) && (operatorSim || sandbox)) {
      source = "Simulation";
    }
    const ts = str(args?.timestamp) ?? str(args?.day);
    steps.push({
      text: describeStep(p.toolName, args, running),
      hour: ts ? fmtTs(ts) : null,
      source,
      running,
    });
  }
  return steps;
}

const SourceBadge: FC<{ source: Step["source"] }> = ({ source }) => (
  <span
    className={cn(
      "shrink-0 rounded px-1.5 py-px text-[11px] font-medium",
      source === "Live"
        ? "bg-muted text-muted-foreground"
        : "border border-sim-border bg-sim-surface text-foreground",
    )}
  >
    {source}
  </span>
);

/** Snapshot of the ask context when the message first rendered. */
function useAskedAbout() {
  const ctx = useAskContext();
  const [snap] = useState(() => ({
    hour: ctx?.hourLabel ?? null,
    sim: !!ctx?.simulationLabel,
  }));
  return snap;
}

/**
 * Shown in place of the collapsed tool group while the agent is working: each
 * lookup as it happens, so a slow answer is never a blank spinner, and a Stop
 * button for when it is heading the wrong way.
 */
export const LiveSteps: FC<{ indices: readonly number[] }> = ({ indices }) => {
  const parts = useAuiState((s) => s.message.parts) as readonly PartLike[];
  const asked = useAskedAbout();
  const thread = useThreadRuntime();
  const steps = buildSteps(indices.map((i) => parts[i]).filter(Boolean), asked.sim);

  return (
    <div className="rounded-lg border border-agent-border bg-agent-surface/40 px-3 py-2.5" aria-live="polite">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-[#8ed1c1]">Working on it</span>
        <button
          type="button"
          onClick={() => thread.cancelRun()}
          className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[12px] text-muted-foreground hover:text-foreground"
        >
          <SquareIcon className="size-3 fill-current" /> Stop
        </button>
      </div>
      <ol className="space-y-1">
        {steps.map((s, i) => (
          <li key={i} className="flex items-center gap-2 text-[14px]">
            {s.running ? (
              <LoaderIcon className="size-3.5 shrink-0 animate-spin text-[#8ed1c1]" />
            ) : (
              <CheckIcon className="size-3.5 shrink-0 text-muted-foreground" />
            )}
            <span className={cn("min-w-0 flex-1 truncate", s.running ? "text-foreground" : "text-muted-foreground")}>
              {s.text}
              {s.hour && <span className="num"> · {s.hour}</span>}
            </span>
            <SourceBadge source={s.source} />
          </li>
        ))}
      </ol>
    </div>
  );
};

/**
 * "How I got this", under a finished answer: every lookup behind it in plain
 * words, the hour each one read, and whether it was the live recorded grid or
 * a simulation. Folded by default to one line, so it never crowds the answer.
 */
export const EvidenceTrail: FC = () => {
  const parts = useAuiState((s) => s.message.parts) as readonly PartLike[];
  const running = useAuiState((s) => s.message.status?.type === "running");
  const asked = useAskedAbout();
  const [open, setOpen] = useState(false);
  if (running) return null;
  const steps = buildSteps(parts, asked.sim);
  if (!steps.length) return null;

  const nSim = steps.filter((s) => s.source === "Simulation").length;
  const sourceText =
    nSim === 0 ? "all live data" : nSim === steps.length ? "all simulated" : `${nSim} simulated, ${steps.length - nSim} live`;

  return (
    <div data-slot="evidence-trail" className="mt-3 border-t border-border/70 pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-start text-[13px] text-muted-foreground hover:text-foreground"
      >
        <ChevronRightIcon className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <span className="font-medium text-foreground/90">How I got this</span>
        <span>
          · {steps.length} {steps.length === 1 ? "lookup" : "lookups"}, {sourceText}
          {asked.hour && <span className="num">, {asked.hour}</span>}
        </span>
      </button>
      {open && (
        <ol className="mt-1.5 space-y-1 pl-5">
          {steps.map((s, i) => (
            <li key={i} className="flex items-center gap-2 text-[14px]">
              <span className="num w-4 shrink-0 text-right text-muted-foreground">{i + 1}</span>
              <span className="min-w-0 flex-1">
                {s.text}
                {s.hour && <span className="num text-muted-foreground"> · {s.hour}</span>}
              </span>
              <SourceBadge source={s.source} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};
