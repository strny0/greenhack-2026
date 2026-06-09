import { createContext, useContext, type ReactNode } from "react";
import { LocateFixedIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Turns grid references the agent writes in prose/tables into clickable chips
 * that focus + open that element on the map. Two forms are linkified:
 *   - internal ids the model still emits (e.g. `bus_012`, `branch_074_075_1`);
 *   - operator-facing DISPLAY NAMES the model now leads with (e.g.
 *     "Milpitas Jct – Metcalf Energy Center"), matched against the labels of the
 *     elements in the current frame. Longest match wins, so a branch label beats
 *     the bus labels nested inside it.
 * Either way a token only becomes a chip if it resolves to a real element.
 *
 *   - rehypeGridRefs(refs): a rehype plugin that wraps candidate tokens as tagged <a>.
 *   - GridRefLink: the markdown <a> renderer; real refs -> <GridChip>, else text.
 * Wiring to the map (pick/has/refs) comes from GridRefContext, set in Sidebar.
 */

export type GridKind = "node" | "line";

/** One linkable element in the current frame: its id and operator-facing label. */
export interface GridRef {
  kind: GridKind;
  id: string;
  label: string;
}

export interface GridRefCtx {
  /** Focus + select the element on the map. */
  pick: (kind: GridKind, id: string) => void;
  /** Focus + select *and* fly the camera to the element (double-click / reticle). */
  jump: (kind: GridKind, id: string) => void;
  /** Whether the element exists in the current frame (else rendered as text). */
  has: (kind: GridKind, id: string) => boolean;
  /** Operator-friendly display label for an element id (falls back to the id). */
  label: (kind: GridKind, id: string) => string;
  /** Every element in the current frame, so display-name mentions can be linkified. */
  refs: GridRef[];
}

export const GridRefContext = createContext<GridRefCtx | null>(null);

// bus_* are buses (nodes); branch_/line_/trafo_ are branches (lines).
const PREFIX_KIND: Record<string, GridKind> = {
  bus: "node",
  branch: "line",
  line: "line",
  trafo: "line",
};
const ID_SRC = "(?:bus|branch|line|trafo)_[A-Za-z0-9_]+";
const ID_PREFIX_RE = /^(bus|branch|line|trafo)_/;
const EXACT_RE = /^(bus|branch|line|trafo)_[A-Za-z0-9_]+$/;
// Labels shorter than this aren't linkified — too likely to collide with prose.
const MIN_LABEL_LEN = 4;

type HNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HNode[];
};

interface Matcher {
  re: RegExp | null;
  /** Resolved id + kind for a matched display-label string. */
  byLabel: Map<string, { kind: GridKind; id: string }>;
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Build one combined matcher for the current frame: internal ids *and* the
 * display labels of every element. Labels are matched longest-first so a branch
 * label ("A – B") wins over the bus labels nested inside it.
 */
function buildMatcher(refs: GridRef[]): Matcher {
  const byLabel = new Map<string, { kind: GridKind; id: string }>();
  for (const r of refs) {
    const lbl = (r.label ?? "").trim();
    if (!lbl || lbl === r.id || lbl.length < MIN_LABEL_LEN) continue;
    if (!byLabel.has(lbl)) byLabel.set(lbl, { kind: r.kind, id: r.id });
  }
  const labels = [...byLabel.keys()].sort((a, b) => b.length - a.length);
  // `\b` only guards the id alternative; labels carry their own (often multi-word)
  // boundaries and may start/end with punctuation, so a word-boundary would miss them.
  const parts = [`\\b${ID_SRC}`, ...labels.map(escapeRe)];
  const re = parts.length ? new RegExp(parts.join("|"), "g") : null;
  return { re, byLabel };
}

function splitText(value: string, matcher: Matcher): HNode[] {
  const { re, byLabel } = matcher;
  if (!re) return [{ type: "text", value }];
  re.lastIndex = 0;
  const out: HNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(value))) {
    const token = m[0];
    const pm = ID_PREFIX_RE.exec(token);
    let kind: GridKind;
    let id: string;
    if (pm) {
      kind = PREFIX_KIND[pm[1]];
      id = token;
    } else {
      const ref = byLabel.get(token);
      if (!ref) continue; // shouldn't happen, but never emit an unresolved chip
      kind = ref.kind;
      id = ref.id;
    }
    if (m.index > last) out.push({ type: "text", value: value.slice(last, m.index) });
    out.push(gridAnchor(kind, id, token));
    last = m.index + token.length;
  }
  if (out.length === 0) return [{ type: "text", value }];
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}

function gridAnchor(kind: GridKind, id: string, text: string): HNode {
  return {
    type: "element",
    tagName: "a",
    // title carries the resolved id; the visible text is whatever the model wrote
    // (id or label) — GridChip re-derives the canonical label for display.
    properties: { className: ["grid-ref"], title: `${kind}:${id}` },
    children: [{ type: "text", value: text }],
  };
}

/**
 * rehype plugin: linkify grid ids and display labels. Handles plain text *and*
 * inline code (the model often wraps an id in backticks). Skips links and fenced
 * code blocks (<pre>). Pass the current frame's `refs` so labels can be matched.
 */
export function rehypeGridRefs(refs: GridRef[] = []) {
  const matcher = buildMatcher(refs);
  const walk = (node: HNode, skip: boolean) => {
    if (!node.children) return;
    const tag = node.type === "element" ? node.tagName : "";
    const childSkip = skip || tag === "a" || tag === "pre";
    const next: HNode[] = [];
    for (const child of node.children) {
      if (childSkip) {
        walk(child, childSkip);
        next.push(child);
      } else if (child.type === "text" && child.value) {
        next.push(...splitText(child.value, matcher));
      } else if (child.type === "element" && child.tagName === "code") {
        // Inline code that is *exactly* one grid id -> swap the code box for a
        // chip; anything else is left as normal inline code.
        const text = child.children?.length === 1 ? child.children[0].value ?? "" : "";
        const em = EXACT_RE.exec(text);
        if (em) next.push(gridAnchor(PREFIX_KIND[em[1]], text, text));
        else next.push(child);
      } else {
        walk(child, childSkip);
        next.push(child);
      }
    }
    node.children = next;
  };
  return (tree: HNode) => walk(tree, false);
}

function GridChip({ kind, id, children }: { kind: GridKind; id: string; children?: ReactNode }) {
  const ctx = useContext(GridRefContext);
  // Exact-match: only a real element in the current frame becomes a chip.
  if (!ctx || !ctx.has(kind, id)) return <>{children ?? id}</>;
  // Prefer the operator-friendly override label over the raw id the model wrote.
  const display = ctx.label(kind, id);
  return (
    <span
      // Double-click anywhere on the chip flies the camera to the element; a
      // single click just focuses/selects it (cheaper, no camera move).
      onDoubleClick={() => ctx.jump(kind, id)}
      className={cn(
        "mx-px inline-flex items-center gap-1 rounded border pr-0.5 pl-1.5 align-baseline text-[0.82em] transition-colors",
        display === id ? "font-mono" : "font-medium",
        "border-border bg-muted/60 text-foreground hover:border-ring hover:bg-accent",
      )}
    >
      <button
        type="button"
        onClick={() => ctx.pick(kind, id)}
        title={`Show ${id} on the map (double-click to zoom)`}
        className="inline-flex cursor-pointer items-center gap-1 py-px"
      >
        <span
          className={cn(
            "inline-block size-1.5 shrink-0 rounded-full",
            kind === "node" ? "bg-sky-400" : "bg-emerald-400",
          )}
        />
        {display}
      </button>
      <button
        type="button"
        onClick={() => ctx.jump(kind, id)}
        title={`Zoom to ${id} on the map`}
        aria-label={`Zoom to ${id} on the map`}
        className="text-muted-foreground hover:text-foreground inline-flex cursor-pointer items-center rounded p-0.5 transition-colors"
      >
        <LocateFixedIcon className="size-3" />
      </button>
    </span>
  );
}

/** Drop-in markdown <a> renderer: grid refs become chips, everything else a link. */
export function GridRefLink({
  className,
  title,
  children,
  ...props
}: React.ComponentPropsWithoutRef<"a">) {
  const isGridRef = typeof className === "string" && className.split(" ").includes("grid-ref");
  if (isGridRef && typeof title === "string") {
    const sep = title.indexOf(":");
    const kind = title.slice(0, sep) as GridKind;
    const id = title.slice(sep + 1);
    return <GridChip kind={kind} id={id}>{children}</GridChip>;
  }
  return (
    <a
      className={cn("aui-md-a text-primary hover:text-primary/80 underline underline-offset-2", className)}
      title={title}
      {...props}
    >
      {children}
    </a>
  );
}
