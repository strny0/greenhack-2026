import { describe, expect, it } from "vitest";
import { rehypeGridRefs } from "./grid-refs";

type N = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: N[] };
const refs = [
  { kind: "line" as const, id: "branch_030_038_1", label: "Bay Point Jct – Colfax Tap" },
  { kind: "node" as const, id: "bus_030", label: "Bay Point Jct" },
];
const run = (children: N[]) => {
  const tree: N = { type: "root", children: [{ type: "element", tagName: "p", children }] };
  rehypeGridRefs(refs)(tree as never);
  return tree.children![0].children!;
};
const render = (ns: N[]) =>
  ns.map((n) => (n.tagName === "a" ? `[${n.properties!.title}]` : n.value ?? "")).join("");

describe("grid ref chips", () => {
  it("drops a repeated chip written as Name (id)", () => {
    const out = run([{ type: "text", value: "Tripping Bay Point Jct – Colfax Tap (branch_030_038_1) has little effect." }]);
    expect(render(out)).toBe("Tripping [line:branch_030_038_1] has little effect.");
  });

  it("drops a repeated chip when the id is inline code", () => {
    const out = run([
      { type: "text", value: "At Bay Point Jct (" },
      { type: "element", tagName: "code", children: [{ type: "text", value: "bus_030" }] },
      { type: "text", value: ") voltage is high." },
    ]);
    expect(render(out)).toBe("At [node:bus_030] voltage is high.");
  });

  it("keeps two chips for two different elements", () => {
    const out = run([{ type: "text", value: "Bay Point Jct (branch_030_038_1)" }]);
    expect(render(out)).toBe("[node:bus_030] ([line:branch_030_038_1])");
  });
});
