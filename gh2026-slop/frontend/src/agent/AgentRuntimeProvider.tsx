import { useRef, type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadMessage,
} from "@assistant-ui/react";

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

function makeAdapter(
  timestampRef: { current: string },
  selectionRef: { current: Selection },
): ChatModelAdapter {
  return {
    async *run({ messages, abortSignal }) {
      const payload = {
        timestamp: timestampRef.current,
        selection: selectionRef.current,
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

export function AgentRuntimeProvider({
  timestamp,
  selection,
  children,
}: {
  timestamp: string;
  selection: Selection;
  children: ReactNode;
}) {
  // The adapter is created once; refs let it always read the *current* frame
  // timestamp and map selection without rebuilding the runtime.
  const tsRef = useRef(timestamp);
  tsRef.current = timestamp;
  const selRef = useRef<Selection>(selection);
  selRef.current = selection;

  const adapterRef = useRef<ChatModelAdapter>();
  if (!adapterRef.current) adapterRef.current = makeAdapter(tsRef, selRef);

  const runtime = useLocalRuntime(adapterRef.current);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
