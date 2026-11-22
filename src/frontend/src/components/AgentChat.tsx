import { useEffect, useRef } from "react";
import { useAuiState } from "@assistant-ui/react";
import { Thread } from "@/components/assistant-ui/thread";
import ChatHistoryBar from "@/components/ChatHistoryBar";
import { GridRefContext, findGridRefs, type GridRefCtx } from "@/agent/grid-refs";

/**
 * The diagram follows the conversation: when an answer finishes, every element
 * it mentions is highlighted on the diagram, so the operator can look up from
 * the text and see where it is. Fires once per finished answer, not on every
 * frame change, so it never fights the operator's own selection.
 */
function FollowAnswers({ grid, onHighlight }: { grid: GridRefCtx; onHighlight: (ids: string[]) => void }) {
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const messages = useAuiState((s) => s.thread.messages);
  const done = useRef<string | null>(null);

  const last = [...messages].reverse().find((m) => m.role === "assistant");
  const lastId = last?.id ?? null;

  useEffect(() => {
    if (isRunning || !last || done.current === lastId) return;
    done.current = lastId;
    const text = last.content
      .map((p) => (p.type === "text" ? p.text : ""))
      .join("\n");
    const found = findGridRefs(text, grid.refs);
    if (found.length) onHighlight(found.map((f) => f.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRunning, lastId]);

  return null;
}

/**
 * The agent chat view: the main surface of the app. The runtime that holds the
 * conversation lives in <AgentRuntimeProvider>, mounted once in App. `grid`
 * wires the clickable element chips in replies to the diagram.
 */
export default function AgentChat({
  grid,
  onHighlight,
}: {
  grid: GridRefCtx;
  onHighlight: (ids: string[]) => void;
}) {
  return (
    <GridRefContext.Provider value={grid}>
      <FollowAnswers grid={grid} onHighlight={onHighlight} />
      <div className="flex h-full min-h-0 flex-col">
        <ChatHistoryBar />
        <div className="min-h-0 flex-1">
          <Thread />
        </div>
      </div>
    </GridRefContext.Provider>
  );
}
