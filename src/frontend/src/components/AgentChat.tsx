import { Thread } from "@/components/assistant-ui/thread";
import ChatHistoryBar from "@/components/ChatHistoryBar";
import { GridRefContext, type GridRefCtx } from "@/agent/grid-refs";

/**
 * The agent chat *view* only. The runtime that holds the conversation lives in
 * <AgentRuntimeProvider>, mounted once high in the Sidebar so the thread
 * survives tab switches. `grid` wires the clickable element chips in the
 * agent's replies to the map (focus + select). The history bar on top lets the
 * operator switch between, rename, and delete saved conversations.
 */
export default function AgentChat({ grid }: { grid: GridRefCtx }) {
  return (
    <GridRefContext.Provider value={grid}>
      <div className="flex h-full min-h-0 flex-col">
        <ChatHistoryBar />
        <div className="min-h-0 flex-1">
          <Thread />
        </div>
      </div>
    </GridRefContext.Provider>
  );
}
