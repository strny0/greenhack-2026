export type State = "ok" | "warn" | "alert" | "offline";
export type NodeType = "generation" | "load" | "substation" | "slack";

export interface GridNode {
  id: string;
  name: string;
  /** Operator-friendly display name from overrides; falls back to `name`. */
  label: string;
  type: NodeType;
  /** Generator fuel types at this bus, ranked by capacity (e.g. ["solar","hydro"]). */
  gen_types: string[];
  zone: string;
  lat: number;
  lon: number;
  v_nominal_kv: number;
  is_slack: boolean;
  min_vm_pu: number;
  max_vm_pu: number;
  vm_pu: number | null;
  vm_kv: number | null;
  va_degree: number | null;
  production_mw: number;
  consumption_mw: number;
  net_mw: number;
  n_gens: number;
  n_loads: number;
  state: State;
}

export interface GridLine {
  id: string;
  name: string;
  /** Operator-friendly display name from overrides; falls back to `name`. */
  label: string;
  from_node: string;
  to_node: string;
  kind: "line" | "trafo";
  max_i_ka: number;
  loading_pct: number | null;
  p_from_mw: number | null;
  p_to_mw: number | null;
  i_ka: number | null;
  in_service: boolean;
  state: State;
}

export interface FrameSummary {
  timestamp: string;
  converged: boolean;
  total_generation_mw: number;
  total_load_mw: number;
  slack_mw: number;
  losses_mw: number;
  max_loading_pct: number;
  n_alerts: number;
  n_warnings: number;
}

export interface StateFrame {
  timestamp: string;
  summary: FrameSummary;
  nodes: GridNode[];
  lines: GridLine[];
}

export interface Alert {
  id: string;
  severity: "warn" | "alert";
  category: "line_loading" | "voltage" | "n1_contingency";
  element_kind: "line" | "node";
  element_id: string;
  message: string;
  value: number | null;
}

export interface ContingencyResult {
  contingency_id: string;
  contingency_name: string;
  converged: boolean;
  max_loading_pct: number;
  n_overloads: number;
  overloaded: { id: string; name: string; loading_pct: number }[];
}

export interface WhatIfResponse {
  base: StateFrame;
  scenario: StateFrame;
  diffs: { id: string; name: string; before: number; after: number; delta: number }[];
  new_alerts: Alert[];
}

export type PresetKey =
  | "trip_most_loaded_line"
  | "trip_largest_generator"
  | "load_surge";

/** A concrete failure scenario resolved from a preset, applied across the day. */
export interface ScenarioSpec {
  preset: string;
  label: string;
  disconnect_lines: string[];
  trip_nodes: string[];
  load_scale: number;
  resolved: string[];
  feasible: boolean;
  reason: string;
}

export interface WhatIfWindowResponse {
  scenario: ScenarioSpec;
  frames: StateFrame[];
}

export interface Meta {
  count: number;
  timestamps: string[];
  default_window: { start: number; count: number; idx?: number };
  bbox: { lon_min: number; lon_max: number; lat_min: number; lat_max: number };
  sld_coords: Record<string, [number, number]>;
  sld_bbox: { x_min: number; x_max: number; y_min: number; y_max: number };
  thresholds: Record<string, number>;
  suggested_questions: string[];
  engine: string;
}

export interface WeatherPoint {
  bus: string;
  lon: number;
  lat: number;
  solar_mw: number;
  cloud_cover_now: number | null;
  cloud_cover_3h: number | null;
  cloud_trend_3h: number;
  wind_speed_10m: number | null;
  shortwave_radiation: number | null;
  solar_risk: boolean;
}
