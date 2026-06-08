import type { GridLine, GridNode, NodeType } from "../types";

/** Operator-friendly display name: override label first, raw id as fallback. */
export function labelOf(el: { label?: string; name?: string; id: string }): string {
  return el.label || el.name || el.id;
}

/** Human label for a bus's role in the grid. */
export const NODE_KIND_LABEL: Record<NodeType, string> = {
  generation: "Generator",
  load: "Load",
  substation: "Substation",
  slack: "Slack bus",
};

/** Friendly names for the raw generator fuel-type keys coming from the dataset. */
export const GEN_TYPE_LABEL: Record<string, string> = {
  solar: "Solar",
  wind: "Wind",
  hydro: "Hydro",
  biomass: "Biomass",
  geothermal: "Geothermal",
  steam_coal: "Coal",
  combined_cycle_gas: "Combined-cycle gas",
  combustion_gas: "Gas turbine",
  internal_combustion_gas: "Gas engine",
  steam_gas: "Gas (steam)",
  steam_other: "Steam",
  combustion_oil: "Oil",
};

export function genTypeLabel(key: string): string {
  return GEN_TYPE_LABEL[key] ?? key.replace(/_/g, " ");
}

/** "Solar, Hydro, Gas turbine" — the bus's fuel mix, ranked by capacity. */
export function formatGenTypes(types: string[] | undefined): string {
  if (!types || !types.length) return "";
  return types.map(genTypeLabel).join(", ");
}

/**
 * Icon categories the map renders. Generation buses use their dominant fuel
 * type; everything else uses its grid role. Keep keys in sync with mapIcons.ts.
 */
export type IconCategory =
  | "solar"
  | "wind"
  | "hydro"
  | "biomass"
  | "geothermal"
  | "coal"
  | "gas"
  | "oil"
  | "generation"
  | "load"
  | "substation"
  | "slack";

const FUEL_ICON: Record<string, IconCategory> = {
  solar: "solar",
  wind: "wind",
  hydro: "hydro",
  biomass: "biomass",
  geothermal: "geothermal",
  steam_coal: "coal",
  combined_cycle_gas: "gas",
  combustion_gas: "gas",
  internal_combustion_gas: "gas",
  steam_gas: "gas",
  combustion_oil: "oil",
  steam_other: "generation",
};

/** Pick the map icon for a node: dominant fuel for generators, role otherwise. */
export function iconCategoryForNode(node: Pick<GridNode, "type" | "gen_types" | "is_slack">): IconCategory {
  if (node.is_slack) return "slack";
  if (node.type === "generation") {
    const primary = node.gen_types?.[0];
    return (primary && FUEL_ICON[primary]) || "generation";
  }
  if (node.type === "load") return "load";
  if (node.type === "slack") return "slack";
  return "substation";
}

/** Build an id -> display-label map across all elements in a frame. */
export function buildLabelMap(nodes: GridNode[], lines: GridLine[]): Record<string, string> {
  const m: Record<string, string> = {};
  for (const n of nodes) m[n.id] = labelOf(n);
  for (const l of lines) m[l.id] = labelOf(l);
  return m;
}
