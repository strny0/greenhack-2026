import { Thread } from "@/components/assistant-ui/thread";

/**
 * The agent chat *view* only. The runtime that holds the conversation lives in
 * <AgentRuntimeProvider>, mounted once high in the Sidebar so the thread
 * survives tab switches. `.dark` makes the shadcn theme adopt the dark
 * dispatcher palette to match the rest of the app.
 */
export default function AgentChat() {
  return (
    <div className="dark aui-chat">
      <Thread />
    </div>
  );
}
