import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type AssistantRuntime,
  type ChatModelAdapter,
  type ThreadMessage,
} from "@assistant-ui/react";
import * as store from "./chat-store";
import type { SavedChat } from "./chat-store";

/**
 * Custom assistant-ui runtime that streams from our Python agent harness
 * (`POST /api/agent/stream`, NDJSON). Each line is one event:
 *
 *   {type:"text", delta}            incremental answer text
 *   {type:"reasoning", delta}       incremental model thinking (optional)
 *   {type:"tool-call", id,name,args} a tool invocation
 *   {type:"tool-result", id,result}  its result
 *   {type:"error", message} | {type:"done"}
 *
 * We rebuild the message as an ordered list of content parts so the rendered
 * thread mirrors the real agent timeline: reasoning → tool calls → answer.
 */

type Part =
  | { type: "text"; text: string }
  | { type: "reasoning"; text: string }
  | {
      type: "tool-call";
      toolCallId: string;
      toolName: string;
      args: Record<string, any>;
      argsText: string;
      result?: unknown;
    };

function messageText(m: ThreadMessage): string {
  return m.content
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("");
}

type Selection = { kind: "node" | "line"; id: string } | null;
type Simulation = import("../types").ScenarioSpec | null;

function makeAdapter(
  timestampRef: { current: string },
  selectionRef: { current: Selection },
  simulationRef: { current: Simulation },
): ChatModelAdapter {
  return {
    async *run({ messages, abortSignal }) {
      const payload = {
        timestamp: timestampRef.current,
        selection: selectionRef.current,
        // Sending the active scenario on every request is what makes the agent
        // aware a simulation is running (drives its system-prompt injection).
        simulation: simulationRef.current,
        messages: messages
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ role: m.role, content: messageText(m) })),
      };

      const res = await fetch("/api/agent/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: abortSignal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`agent stream failed: ${res.status} ${res.statusText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const parts: Part[] = [];
      const toolIndex = new Map<string, number>();
      let buffer = "";

      const snapshot = () => ({ content: parts.map((p) => ({ ...p })) });

      const handle = (ev: any) => {
        switch (ev.type) {
          case "text":
          case "reasoning": {
            const type: "text" | "reasoning" = ev.type;
            const last = parts[parts.length - 1];
            if (last && (last.type === "text" || last.type === "reasoning") && last.type === type) {
              last.text += String(ev.delta);
            } else {
              parts.push({ type, text: String(ev.delta) });
            }
            break;
          }
          case "tool-call": {
            toolIndex.set(ev.id, parts.length);
            const args = (ev.args ?? {}) as Record<string, any>;
            parts.push({
              type: "tool-call",
              toolCallId: ev.id,
              toolName: ev.name,
              args,
              argsText: JSON.stringify(args),
            });
            break;
          }
          case "tool-result": {
            const i = toolIndex.get(ev.id);
            if (i != null) {
              const p = parts[i];
              if (p.type === "tool-call") p.result = ev.result;
            }
            break;
          }
          case "error": {
            const last = parts[parts.length - 1];
            const text = `\n\n⚠️ ${ev.message}`;
            if (last && last.type === "text") last.text += text;
            else parts.push({ type: "text", text });
            break;
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          let ev: any;
          try {
            ev = JSON.parse(line);
          } catch {
            continue;
          }
          if (ev.type === "done") return;
          handle(ev);
          yield snapshot();
        }
      }
    },
  };
}

// --- chat history ------------------------------------------------------------

export type ChatHistoryApi = {
  chats: SavedChat[];
  activeId: string | null;
  /** Load a saved conversation into the live thread. */
  openChat: (id: string) => void;
  /** Clear the thread and begin a brand-new conversation. */
  newChat: () => void;
  deleteChat: (id: string) => void;
  renameChat: (id: string, title: string) => void;
};

const ChatHistoryContext = createContext<ChatHistoryApi | null>(null);

/** Access the saved-chat history (list, open, new, delete, rename). */
export function useChatHistory(): ChatHistoryApi {
  const ctx = useContext(ChatHistoryContext);
  if (!ctx) throw new Error("useChatHistory must be used within <AgentRuntimeProvider>");
  return ctx;
}

/**
 * Bridges the live assistant-ui thread to the persistent chat store:
 *  - on mount, restores the last-active conversation,
 *  - autosaves the thread (debounced) as the operator talks,
 *  - exposes open / new / delete / rename to the history UI.
 */
function ChatHistoryController({
  runtime,
  children,
}: {
  runtime: AssistantRuntime;
  children: ReactNode;
}) {
  const chats = useSyncExternalStore(store.subscribe, store.listChats);
  const activeId = useSyncExternalStore(store.subscribe, store.getActiveId);

  // While we programmatically import/reset the thread, the resulting change
  // notifications must NOT trigger an autosave (it would reorder/rewrite chats).
  const suppress = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();

  const withSuppressedSave = (fn: () => void) => {
    suppress.current = true;
    fn();
    // Clear after the thread's change notifications have flushed.
    setTimeout(() => {
      suppress.current = false;
    }, 0);
  };

  // Restore the last-active conversation once, on first mount.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const id = store.getActiveId();
    const chat = id ? store.getChat(id) : undefined;
    if (chat) withSuppressedSave(() => runtime.thread.import(chat.repo));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Autosave: debounce thread changes and persist the exported repository.
  useEffect(() => {
    const unsub = runtime.thread.subscribe(() => {
      if (suppress.current) return;
      clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        store.saveActiveRepo(runtime.thread.export());
      }, 500);
    });
    return () => {
      unsub();
      clearTimeout(saveTimer.current);
    };
  }, [runtime]);

  const api = useMemo<ChatHistoryApi>(
    () => ({
      chats,
      activeId,
      openChat: (id) => {
        const chat = store.getChat(id);
        if (!chat) return;
        store.setActive(id);
        withSuppressedSave(() => runtime.thread.import(chat.repo));
      },
      newChat: () => {
        store.startNewChat();
        withSuppressedSave(() => runtime.thread.reset());
      },
      deleteChat: (id) => {
        const wasActive = store.getActiveId() === id;
        store.deleteChat(id);
        if (!wasActive) return;
        // The active chat was removed — load whatever the store fell back to.
        const next = store.getActiveId();
        const chat = next ? store.getChat(next) : undefined;
        withSuppressedSave(() =>
          chat ? runtime.thread.import(chat.repo) : runtime.thread.reset(),
        );
      },
      renameChat: (id, title) => store.renameChat(id, title),
    }),
    [chats, activeId, runtime],
  );

  return <ChatHistoryContext.Provider value={api}>{children}</ChatHistoryContext.Provider>;
}

export function AgentRuntimeProvider({
  timestamp,
  selection,
  simulation = null,
  children,
}: {
  timestamp: string;
  selection: Selection;
  simulation?: Simulation;
  children: ReactNode;
}) {
  // The adapter is created once; refs let it always read the *current* frame
  // timestamp, map selection, and active simulation without rebuilding the runtime.
  const tsRef = useRef(timestamp);
  tsRef.current = timestamp;
  const selRef = useRef<Selection>(selection);
  selRef.current = selection;
  const simRef = useRef<Simulation>(simulation);
  simRef.current = simulation;

  const adapterRef = useRef<ChatModelAdapter>();
  if (!adapterRef.current) adapterRef.current = makeAdapter(tsRef, selRef, simRef);

  const runtime = useLocalRuntime(adapterRef.current);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ChatHistoryController runtime={runtime}>{children}</ChatHistoryController>
    </AssistantRuntimeProvider>
  );
}
