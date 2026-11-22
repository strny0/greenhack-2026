import { useAuiState, useThreadRuntime } from "@assistant-ui/react";
import { ASK_EVENT } from "@/agent/ask-context";
import { cn } from "@/lib/utils";
import type { AlertRow } from "./Sidebar";

const MAX_SHOWN = 3;

interface Item {
  key: string;
  sev: "alert" | "warn";
  label: string;
  value: string | null;
  ids: string[];
  question: string;
}

/**
 * One chip per thing worth a look. Lines and voltage alerts stay individual,
 * worst first; voltage warnings are folded into one chip per direction, since
 * forty buses at the same value is one story, not forty.
 */
function groupAlerts(alerts: AlertRow[]): Item[] {
  const one = (a: AlertRow): Item => ({
    key: `${a.kind}:${a.id}`,
    sev: a.sev,
    label: a.label,
    value: a.kind === "line" ? `${a.val.toFixed(0)}%` : `${a.val.toFixed(3)} pu`,
    ids: [a.id],
    // The id rides along in brackets so the agent can look the element up
    // directly instead of searching for it by name.
    question:
      a.kind === "line"
        ? `${a.label} (${a.id}) is ${a.msg}. Why, and what should I do about it?`
        : `${a.label} (${a.id}) has ${a.msg.replace(/ — /, ", ")}. Why, and what should I do about it?`,
  });
  const lineAlerts = alerts.filter((a) => a.kind === "line" && a.sev === "alert").map(one);
  const nodeAlerts = alerts.filter((a) => a.kind === "node" && a.sev === "alert").map(one);
  const lineWarns = alerts.filter((a) => a.kind === "line" && a.sev === "warn").map(one);
  const groups: Item[] = [];
  for (const [dir, test] of [["high", (v: number) => v >= 1], ["low", (v: number) => v < 1]] as const) {
    const ws = alerts.filter((a) => a.kind === "node" && a.sev === "warn" && test(a.val));
    if (!ws.length) continue;
    if (ws.length === 1) { groups.push(one(ws[0])); continue; }
    const vals = ws.map((w) => w.val);
    const lo = Math.min(...vals).toFixed(3);
    const hi = Math.max(...vals).toFixed(3);
    const range = lo === hi ? `${hi} pu` : `${lo} to ${hi} pu`;
    groups.push({
      key: `vgroup:${dir}`,
      sev: "warn",
      label: `${ws.length} buses with ${dir} voltage`,
      value: range,
      ids: ws.map((w) => w.id),
      question: `${ws.length} buses have ${dir} voltage warnings (${range}). Is that a real problem or a modelling artefact, and should I act?`,
    });
  }
  return [...lineAlerts, ...nodeAlerts, ...lineWarns, ...groups];
}

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

  const items = groupAlerts(alerts);
  const shown = items.slice(0, MAX_SHOWN);
  const rest = items.slice(MAX_SHOWN).reduce((n, it) => n + it.ids.length, 0);

  const ask = (it: Item) => {
    onFocus(it.ids);
    thread.append(it.question);
    window.dispatchEvent(new Event(ASK_EVENT));
  };

  return (
    <div aria-label="Needs attention" className="flex items-center gap-1.5 overflow-x-auto border-b px-4 py-2 [scrollbar-width:none]">
      <span className="mr-1 shrink-0 text-[13px] font-medium">Needs attention</span>
      {shown.map((it) => (
        <button
          key={it.key}
          type="button"
          disabled={isRunning}
          onClick={() => ask(it)}
          title={it.question}
          className={cn(
            "inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-[13px] transition-colors hover:bg-muted disabled:opacity-50",
            it.sev === "alert" ? "border-[#f0503c]/60" : "border-[#d9a441]/50",
          )}
        >
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-full"
            style={{ background: it.sev === "alert" ? "#f0503c" : "#d9a441" }}
          />
          <span className="truncate">{it.label}</span>
          {it.value && <span className="num shrink-0 text-muted-foreground">{it.value}</span>}
        </button>
      ))}
      {rest > 0 && (
        <button
          type="button"
          onClick={onMore}
          className="shrink-0 px-1 text-[13px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          +{rest} more
        </button>
      )}
    </div>
  );
}
