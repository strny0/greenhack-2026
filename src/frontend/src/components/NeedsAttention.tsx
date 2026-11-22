import { useAuiState, useThreadRuntime } from "@assistant-ui/react";
import { ASK_EVENT } from "@/agent/ask-context";
import { cn } from "@/lib/utils";
import type { AlertRow } from "./Sidebar";

const MAX_SHOWN = 3;

/**
 * What needs the operator's attention this hour, ranked, right above the chat
 * (the "hypervision" idea from RTE: the system surfaces the few things worth a
 * look, and the operator asks about them in one click). Each chip asks the
 * agent why the element is flagged and what to do, and points the diagram at it.
 */
export default function NeedsAttention({
  alerts,
  simulating,
  onFocus,
  onMore,
}: {
  alerts: AlertRow[];
  simulating: boolean;
  onFocus: (ids: string[]) => void;
  onMore: () => void;
}) {
  const thread = useThreadRuntime();
  const isRunning = useAuiState((s) => s.thread.isRunning);

  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-2 border-b px-4 py-2 text-[13px] text-muted-foreground">
        <span className="size-2 rounded-full bg-[#5a6a72]" aria-hidden />
        Nothing needs attention this hour{simulating ? " in the simulation" : ""}.
      </div>
    );
  }

  const shown = alerts.slice(0, MAX_SHOWN);
  const rest = alerts.length - shown.length;

  const ask = (a: AlertRow) => {
    onFocus([a.id]);
    const what = a.kind === "line" ? `${a.label} is ${a.msg}` : `${a.label} has ${a.msg.replace(/ — /, ", ")}`;
    thread.append(`${what}. Why, and what should I do about it?`);
    window.dispatchEvent(new Event(ASK_EVENT));
  };

  return (
    <div aria-label="Needs attention" className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2">
      <span className="mr-1 text-[13px] font-medium">Needs attention</span>
      {shown.map((a) => (
        <button
          key={`${a.kind}:${a.id}`}
          type="button"
          disabled={isRunning}
          onClick={() => ask(a)}
          title={`Ask why ${a.label} is flagged`}
          className={cn(
            "inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-[13px] transition-colors hover:bg-muted disabled:opacity-50",
            a.sev === "alert" ? "border-[#f0503c]/60" : "border-[#d9a441]/50",
          )}
        >
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-full"
            style={{ background: a.sev === "alert" ? "#f0503c" : "#d9a441" }}
          />
          <span className="truncate">{a.label}</span>
          <span className="num shrink-0 text-muted-foreground">
            {a.kind === "line" ? `${a.val.toFixed(0)}%` : `${a.val.toFixed(3)} pu`}
          </span>
        </button>
      ))}
      {rest > 0 && (
        <button
          type="button"
          onClick={onMore}
          className="px-1 text-[13px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          +{rest} more
        </button>
      )}
    </div>
  );
}
