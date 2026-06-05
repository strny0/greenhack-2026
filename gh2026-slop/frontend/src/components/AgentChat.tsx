import { Thread } from "@/components/assistant-ui/thread";
import { GridRefContext, type GridRefCtx } from "@/agent/grid-refs";

/**
 * The agent chat *view* only. The runtime that holds the conversation lives in
 * <AgentRuntimeProvider>, mounted once high in the Sidebar so the thread
 * survives tab switches. `grid` wires the clickable element chips in the
 * agent's replies to the map (focus + select).
 */
export default function AgentChat({ grid }: { grid: GridRefCtx }) {
  return (
    <GridRefContext.Provider value={grid}>
      <div className="h-full min-h-0">
        <Thread />
      </div>
    </GridRefContext.Provider>
  );
}
