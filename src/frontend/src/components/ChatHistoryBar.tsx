import { useState } from "react";
import {
  CheckIcon,
  HistoryIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useChatHistory } from "@/agent/AgentRuntimeProvider";

/** Compact "n minutes ago" style timestamp for the history list. */
function ago(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return d < 7 ? `${d}d ago` : new Date(ts).toLocaleDateString();
}

/**
 * Slim bar above the agent thread: shows the current conversation, opens a history
 * dropdown to switch between saved chats (rename / delete inline), and starts a new
 * one. The conversations themselves live in the chat-store + thread runtime; this is
 * just their control surface.
 */
export default function ChatHistoryBar() {
  const { chats, activeId, openChat, newChat, deleteChat, renameChat } = useChatHistory();
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const active = chats.find((c) => c.id === activeId);

  const startRename = (id: string, title: string) => {
    setEditingId(id);
    setDraft(title);
  };
  const commitRename = () => {
    if (editingId) renameChat(editingId, draft);
    setEditingId(null);
  };

  return (
    <div className="flex items-center gap-1 border-b px-2 py-1.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 min-w-0 flex-1 justify-start gap-1.5 px-2 text-xs font-medium"
            title="Chat history"
          >
            <HistoryIcon className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">{active?.title ?? "New conversation"}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 p-0" sideOffset={6}>
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              History · {chats.length}
            </span>
          </div>
          <ScrollArea className="max-h-72">
            {chats.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                No saved chats yet. Start talking — conversations are saved here
                automatically.
              </div>
            ) : (
              <ul className="p-1">
                {chats.map((c) => {
                  const isActive = c.id === activeId;
                  const isEditing = c.id === editingId;
                  return (
                    <li key={c.id}>
                      {isEditing ? (
                        <div className="flex items-center gap-1 p-1">
                          <Input
                            autoFocus
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") commitRename();
                              if (e.key === "Escape") setEditingId(null);
                            }}
                            className="h-7 text-xs"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7 shrink-0"
                            onClick={commitRename}
                            title="Save name"
                          >
                            <CheckIcon className="size-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-7 shrink-0"
                            onClick={() => setEditingId(null)}
                            title="Cancel"
                          >
                            <XIcon className="size-3.5" />
                          </Button>
                        </div>
                      ) : (
                        <div
                          className={cn(
                            "group flex items-center gap-1 rounded-md px-2 py-1.5",
                            isActive ? "bg-accent" : "hover:bg-accent/60",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => {
                              openChat(c.id);
                              setOpen(false);
                            }}
                            className="flex min-w-0 flex-1 flex-col items-start text-left"
                          >
                            <span className="w-full truncate text-xs font-medium">
                              {c.title}
                            </span>
                            <span className="text-[10px] text-muted-foreground">
                              {ago(c.updatedAt)}
                            </span>
                          </button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                            onClick={() => startRename(c.id, c.title)}
                            title="Rename"
                          >
                            <PencilIcon className="size-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-6 shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                            onClick={() => deleteChat(c.id)}
                            title="Delete chat"
                          >
                            <Trash2Icon className="size-3" />
                          </Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </ScrollArea>
        </PopoverContent>
      </Popover>

      <Button
        variant="ghost"
        size="icon"
        className="size-7 shrink-0"
        onClick={() => {
          newChat();
          setOpen(false);
        }}
        title="New chat"
      >
        <PlusIcon className="size-4" />
      </Button>
    </div>
  );
}
