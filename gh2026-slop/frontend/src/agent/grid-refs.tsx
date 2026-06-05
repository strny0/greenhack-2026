import { createContext, useContext, type ReactNode } from "react";
import { LocateFixedIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Turns grid identifiers the agent writes in prose/tables (e.g. `bus_012`,
 * `branch_074_075_1`) into clickable chips that focus + open that element on the
 * map. Exact-match: a token only becomes a chip if it's a real element in the
 * current frame; otherwise it renders as plain text.
 *
 *   - rehypeGridRefs: a rehype plugin that wraps candidate tokens as tagged <a>.
 *   - GridRefLink: the markdown <a> renderer; real refs -> <GridChip>, else text.
 * Wiring to the map (pick/has) comes from GridRefContext, set in AgentChat.
 */

export type GridKind = "node" | "line";

export interface GridRefCtx {
  /** Focus + select the element on the map. */
  pick: (kind: GridKind, id: string) => void;
  /** Focus + select *and* fly the camera to the element (double-click / reticle). */
  jump: (kind: GridKind, id: string) => void;
  /** Whether the element exists in the current frame (else rendered as text). */
  has: (kind: GridKind, id: string) => boolean;
}

export const GridRefContext = createContext<GridRefCtx | null>(null);

// bus_* are buses (nodes); branch_/line_/trafo_ are branches (lines).
const PREFIX_KIND: Record<string, GridKind> = {
  bus: "node",
  branch: "line",
  line: "line",
  trafo: "line",
};
const TOKEN_RE = /\b(bus|branch|line|trafo)_[A-Za-z0-9_]+/g;
const EXACT_RE = /^(bus|branch|line|trafo)_[A-Za-z0-9_]+$/;

type HNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HNode[];
};

function splitText(value: string): HNode[] {
  TOKEN_RE.lastIndex = 0;
  const out: HNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(value))) {
    const token = m[0];
    const kind = PREFIX_KIND[m[1]];
    if (m.index > last) out.push({ type: "text", value: value.slice(last, m.index) });
    out.push(gridAnchor(kind, token));
    last = m.index + token.length;
  }
  if (out.length === 0) return [{ type: "text", value }];
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}

function gridAnchor(kind: GridKind, token: string): HNode {
  return {
    type: "element",
    tagName: "a",
    properties: { className: ["grid-ref"], title: `${kind}:${token}` },
    children: [{ type: "text", value: token }],
  };
}

/**
 * rehype plugin: linkify grid identifiers. Handles plain text *and* inline code
 * (the model often wraps the headline id in backticks). Skips links and fenced
 * code blocks (<pre>).
 */
export function rehypeGridRefs() {
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
        next.push(...splitText(child.value));
      } else if (child.type === "element" && child.tagName === "code") {
        // Inline code that is *exactly* one grid id -> swap the code box for a
        // chip; anything else is left as normal inline code.
        const text = child.children?.length === 1 ? child.children[0].value ?? "" : "";
        const m = EXACT_RE.exec(text);
        if (m) next.push(gridAnchor(PREFIX_KIND[m[1]], text));
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
  return (
    <span
      // Double-click anywhere on the chip flies the camera to the element; a
      // single click just focuses/selects it (cheaper, no camera move).
      onDoubleClick={() => ctx.jump(kind, id)}
      className={cn(
        "mx-px inline-flex items-center gap-1 rounded border pr-0.5 pl-1.5 align-baseline font-mono text-[0.82em] transition-colors",
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
        {children ?? id}
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
