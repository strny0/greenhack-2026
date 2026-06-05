import { Thread } from "@/components/assistant-ui/thread";

/**
 * The agent chat *view* only. The runtime that holds the conversation lives in
 * <AgentRuntimeProvider>, mounted once high in the Sidebar so the thread
 * survives tab switches. The whole app runs the dark shadcn theme (html.dark),
 * so the Thread inherits it directly.
 */
export default function AgentChat() {
  return (
    <div className="h-full min-h-0">
      <Thread />
    </div>
  );
}
