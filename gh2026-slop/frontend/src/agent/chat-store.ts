/**
 * localStorage-backed history for the dispatcher agent chat.
 *
 * The chat itself runs on assistant-ui's in-memory `useLocalRuntime`, which only
 * ever holds ONE conversation and forgets it on reload. This store lets us keep a
 * list of past conversations the operator can reopen, rename, delete, or continue.
 *
 * The trick: assistant-ui's thread runtime can serialise its whole message tree
 * (`thread.export()`) and load one back (`thread.import()`). We persist those
 * exported repositories here, keyed by a chat id, and swap the single live thread
 * between them. No backend involvement — continuing a reopened chat works because
 * the stream adapter already replays the full message history on every send.
 */
import type { ExportedMessageRepository } from "@assistant-ui/react";

export type SavedChat = {
  id: string;
  title: string;
  /** True once the operator renames it — protects the name from autosave's auto-titling. */
  titleCustom?: boolean;
  createdAt: number;
  updatedAt: number;
  repo: ExportedMessageRepository;
};

type StoreState = {
  activeId: string | null;
  chats: SavedChat[];
};

const KEY = "gridpulse.chats.v1";
const MAX_TITLE = 60;

let state: StoreState = load();
// Cached most-recent-first view, recomputed only when state changes, so
// useSyncExternalStore sees a stable reference between updates.
let cachedList: SavedChat[] = sortChats(state.chats);
const listeners = new Set<() => void>();

function sortChats(chats: SavedChat[]): SavedChat[] {
  return [...chats].sort((a, b) => b.updatedAt - a.updatedAt);
}

// --- persistence -------------------------------------------------------------

function load(): StoreState {
  if (typeof localStorage === "undefined") return { activeId: null, chats: [] };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { activeId: null, chats: [] };
    const parsed = JSON.parse(raw) as StoreState;
    // Revive Date instances the runtime expects (JSON flattens them to strings).
    for (const c of parsed.chats) reviveRepo(c.repo);
    return { activeId: parsed.activeId ?? null, chats: parsed.chats ?? [] };
  } catch {
    return { activeId: null, chats: [] };
  }
}

function persist() {
  cachedList = sortChats(state.chats);
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Quota or private-mode failures are non-fatal for a demo; keep going in memory.
  }
  for (const fn of listeners) fn();
}

/** Walk an exported repository and turn ISO `createdAt` strings back into Dates. */
function reviveRepo(repo: ExportedMessageRepository) {
  for (const item of repo?.messages ?? []) {
    const m = item.message as { createdAt?: unknown };
    if (typeof m.createdAt === "string") m.createdAt = new Date(m.createdAt);
  }
}

// --- read API (for useSyncExternalStore) -------------------------------------

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getSnapshot(): StoreState {
  return state;
}

/** Chats most-recently-updated first — the order the history list shows them. */
export function listChats(): SavedChat[] {
  return cachedList;
}

export function getActiveId(): string | null {
  return state.activeId;
}

export function getChat(id: string): SavedChat | undefined {
  return state.chats.find((c) => c.id === id);
}

// --- write API ---------------------------------------------------------------

export function newId(): string {
  return `chat_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Start a fresh (not-yet-persisted) conversation; it appears in the list once it has content. */
export function startNewChat(): string {
  const id = newId();
  state = { ...state, activeId: id };
  persist();
  return id;
}

export function setActive(id: string | null) {
  if (state.activeId === id) return;
  state = { ...state, activeId: id };
  persist();
}

/**
 * Persist the current live thread under the active chat id, creating the entry on
 * first content. Returns the id used (callers don't usually need it). A no-op when
 * the exported repo is empty or unchanged, so merely opening a chat doesn't reorder
 * the list or bump its timestamp.
 */
export function saveActiveRepo(repo: ExportedMessageRepository): string | null {
  if (!repo?.messages?.length) return null;

  let id = state.activeId;
  if (!id) {
    id = newId();
    state = { ...state, activeId: id };
  }

  const existing = state.chats.find((c) => c.id === id);
  // A user-renamed chat keeps its name; otherwise the title tracks the first question.
  const title = existing?.titleCustom ? existing.title : deriveTitle(repo);

  if (existing && sameRepo(existing.repo, repo) && existing.title === title) {
    return id; // nothing actually changed — avoid churn / reorder
  }

  const now = Date.now();
  const next: SavedChat = existing
    ? { ...existing, title, repo, updatedAt: now }
    : { id, title, repo, createdAt: now, updatedAt: now };

  state = {
    ...state,
    chats: [next, ...state.chats.filter((c) => c.id !== id)],
  };
  persist();
  return id;
}

export function deleteChat(id: string) {
  const chats = state.chats.filter((c) => c.id !== id);
  let activeId = state.activeId;
  if (activeId === id) {
    // Fall back to the most recent remaining chat, or a clean slate.
    const next = [...chats].sort((a, b) => b.updatedAt - a.updatedAt)[0];
    activeId = next?.id ?? null;
  }
  state = { activeId, chats };
  persist();
}

export function renameChat(id: string, title: string) {
  const clean = title.trim().slice(0, MAX_TITLE) || "Untitled chat";
  state = {
    ...state,
    chats: state.chats.map((c) =>
      c.id === id ? { ...c, title: clean, titleCustom: true } : c,
    ),
  };
  persist();
}

// --- helpers -----------------------------------------------------------------

function messageText(message: any): string {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((p: any) => p?.type === "text")
    .map((p: any) => p.text as string)
    .join("");
}

/** Title = the operator's first question, trimmed. */
export function deriveTitle(repo: ExportedMessageRepository): string {
  const first = repo.messages.find((m) => m.message.role === "user");
  const text = first ? messageText(first.message).trim() : "";
  if (!text) return "New conversation";
  const oneLine = text.replace(/\s+/g, " ");
  return oneLine.length > MAX_TITLE ? `${oneLine.slice(0, MAX_TITLE - 1)}…` : oneLine;
}

function sameRepo(a: ExportedMessageRepository, b: ExportedMessageRepository): boolean {
  // Content-aware: a streaming answer keeps the same message id while its text
  // grows, so we must compare the actual payload, not just ids/counts.
  if (a.headId !== b.headId || a.messages.length !== b.messages.length) return false;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}
