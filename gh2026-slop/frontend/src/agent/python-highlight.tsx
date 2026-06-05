import { Fragment, type ReactNode } from "react";

/**
 * Minimal, dependency-free Python syntax highlighter.
 *
 * The dispatcher agent only ever writes Python (the `run_python` tool), so a
 * full grammar engine like shiki/prism would be megabytes of bundle + async
 * loading for one language. This single-pass regex tokenizer covers the things
 * that actually read as code — comments, strings (incl. f/r/b prefixes and
 * triple-quotes), numbers, decorators, keywords, and common builtins — and
 * leaves everything else as plain text. It returns React nodes so it drops
 * straight into a <pre>.
 */

// Order matters: comments and strings are matched before anything else so that
// `# def x` or `"for"` aren't mistaken for keywords.
const RULES: [token: string, pattern: string][] = [
  ["comment", "#[^\\n]*"],
  [
    "string",
    "(?:[rbfuRBFU]{0,3})(?:'''[\\s\\S]*?'''|\"\"\"[\\s\\S]*?\"\"\"|'(?:\\\\.|[^'\\\\\\n])*'|\"(?:\\\\.|[^\"\\\\\\n])*\")",
  ],
  ["number", "\\b(?:0[xXbBoO][0-9a-fA-F_]+|\\d[\\d_]*\\.?[\\d_]*(?:[eE][+-]?\\d+)?[jJ]?)\\b"],
  ["decorator", "@[\\w.]+"],
  [
    "keyword",
    "\\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|match|case)\\b",
  ],
  [
    "builtin",
    "\\b(?:print|len|range|int|float|str|bool|bytes|list|dict|set|tuple|frozenset|sum|min|max|abs|round|sorted|reversed|enumerate|zip|map|filter|any|all|open|type|isinstance|getattr|setattr|hasattr|repr|format|pd|np)\\b",
  ],
];

const RE = new RegExp(RULES.map(([, p]) => `(${p})`).join("|"), "g");

const CLASS: Record<string, string> = {
  comment: "text-slate-400 dark:text-slate-500 italic",
  string: "text-emerald-600 dark:text-emerald-400",
  number: "text-orange-600 dark:text-orange-400",
  decorator: "text-yellow-600 dark:text-yellow-500",
  keyword: "text-violet-600 dark:text-violet-400",
  builtin: "text-sky-600 dark:text-sky-400",
};

/** Tokenize `code` into coloured spans (plain text between matches). */
export function highlightPython(code: string): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  RE.lastIndex = 0;
  while ((m = RE.exec(code)) !== null) {
    if (m.index > last) out.push(<Fragment key={key++}>{code.slice(last, m.index)}</Fragment>);
    // Which capture group fired -> which token kind.
    const kind = RULES[m.findIndex((g, i) => i > 0 && g !== undefined) - 1]?.[0];
    out.push(
      <span key={key++} className={kind ? CLASS[kind] : undefined}>
        {m[0]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < code.length) out.push(<Fragment key={key++}>{code.slice(last)}</Fragment>);
  return out;
}
