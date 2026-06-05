# Dataset Schema & Statistics

_Generated from `/home/jstrnad/source/greenhack/dataset/`_

## Table of Contents

- [branches](#branches)
- [bus_coordinates](#bus-coordinates)
- [buses](#buses)
- [Fuel prices N](#fuel-prices-n)
- [gens](#gens)
- [gens_ts](#gens-ts)
- [loads](#loads)
- [loads_ts](#loads-ts)
- [LoadRNDA](#loadrnda) — 3 files (grouped)
- [SolarNDA](#solarnda) — 75 files (grouped)
- [WindNDA](#windnda) — 17 files (grouped)

---

## branches

**Type:** Single file — `branches.csv`
**Directory:** `data/static/`
**Rows:** 186

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `branch_name` | string | 186 | 0 |  |  |  |  |
| `from_bus` | string | 100 | 0 |  |  |  |  |
| `to_bus` | string | 111 | 0 |  |  |  |  |
| `parallel` | integer | 2 | 0 | 1 | 2 | 1.038 | categorical: `1`, `2` |
| `in_service` | boolean | 1 | 0 |  |  |  | categorical: `True` |
| `r_ohm` | float | 152 | 0 | 0 | 18.76 | 5.434 |  |
| `x_ohm` | float | 169 | 0 | 1.52 | 117.4 | 24.41 |  |
| `b_µs` | float | 157 | 0 | 0 | 1,033.40 | 200.5 |  |
| `trafo_ratio_rel` | float | 3 | 177 | 0.935 | 0.985 | 0.9544 | categorical: `0.935`, `0.96`, `0.985` |
| `max_i_ka` | float | 7 | 0 | 1.004 | 14.64 | 3.197 | categorical: `1.004087`, `2.510219`, `2.844914`, `2.928588`, `5.857177`, `7.112286`, `14.642942` |

## bus_coordinates

**Type:** Single file — `bus_coordinates.csv`
**Directory:** `data/static/`
**Rows:** 118

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `bus_name` | string | 118 | 0 |  |  |  |  |
| `x_coordinate` | integer | 81 | 0 | 190 | 2140 | 1,292.95 |  |
| `y_coordinate` | integer | 60 | 0 | -1704 | -164 | -690.1 |  |

## buses

**Type:** Single file — `buses.csv`
**Directory:** `data/static/`
**Rows:** 118

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `bus_name` | string | 118 | 0 |  |  |  |  |
| `region` | string | 3 | 0 |  |  |  | categorical: `r1`, `r2`, `r3` |
| `in_service` | boolean | 1 | 0 |  |  |  | categorical: `True` |
| `v_rated_kv` | integer | 2 | 0 | 138 | 345 | 159.1 | categorical: `138`, `345` |
| `is_slack` | boolean | 2 | 0 |  |  |  | categorical: `False`, `True` |
| `min_v_pu` | float | 1 | 0 | 0.8 | 0.8 | 0.8 | categorical: `0.8` |
| `max_v_pu` | float | 1 | 0 | 1.2 | 1.2 | 1.2 | categorical: `1.2` |
| `x_coordinate` | float | 81 | 0 | 190 | 2140 | 1,292.95 |  |
| `y_coordinate` | float | 60 | 0 | -1704 | -164 | -690.1 |  |

## Fuel prices N

**Type:** Single file — `Fuel prices 2024.csv`
**Directory:** `data/other/`
**Rows:** 12

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `Datetime` | string | 12 | 0 |  |  |  | categorical: `1-Apr`, `1-Aug`, `1-Dec`, `1-Feb`, `1-Jan`, `1-Jul`, `1-Jun`, `1-Mar`, `1-May`, `1-Nov`, `1-Oct`, `1-Sep` |
| `Coal R1` | float | 1 | 0 | 1.8 | 1.8 | 1.8 | categorical: `1.8` |
| `Oil Distillate R1` | integer | 1 | 0 | 21 | 21 | 21 | categorical: `21` |
| `Oil Distillate R2` | integer | 1 | 0 | 21 | 21 | 21 | categorical: `21` |
| `Biomass R1` | float | 1 | 0 | 2.4 | 2.4 | 2.4 | categorical: `2.4` |
| `Biomass R2` | float | 1 | 0 | 2.4 | 2.4 | 2.4 | categorical: `2.4` |
| `Biomass R3` | float | 1 | 0 | 2.4 | 2.4 | 2.4 | categorical: `2.4` |
| `Natural Gas R1` | float | 1 | 0 | 5.4 | 5.4 | 5.4 | categorical: `5.4` |
| `Natural Gas R2` | float | 1 | 0 | 5.4 | 5.4 | 5.4 | categorical: `5.4` |
| `Natural Gas R3` | float | 1 | 0 | 5.4 | 5.4 | 5.4 | categorical: `5.4` |
| `Geo R1` | integer | 1 | 0 | 0 | 0 | 0 | categorical: `0` |

## gens

**Type:** Single file — `gens.csv`
**Directory:** `data/static/`
**Rows:** 321

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `gen_name` | string | 321 | 0 |  |  |  |  |
| `bus_name` | string | 52 | 0 |  |  |  |  |
| `opt_category` | string | 3 | 0 |  |  |  | categorical: `day_ahead`, `non_optimized`, `real_time` |
| `max_p_mw` | float | 220 | 0 | 0.01012 | 1,225.31 | 112 |  |
| `min_p_mw` | float | 1 | 0 | 0 | 0 | 0 | categorical: `0.0` |

## gens_ts

**Type:** Single file — `gens_ts.csv`
**Directory:** `data/realtime/`
**Rows:** 50,000+ (sampled first 50,000)

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `datetime` | string | 156 | 0 |  |  |  |  |
| `gen_name` | string | 321 | 0 |  |  |  |  |
| `in_service` | boolean | 2 | 0 |  |  |  | categorical: `False`, `True` |
| `p_mw` | float | 33029 | 0 | -2.887e-11 | 933.2 | 28.77 |  |
| `max_q_mvar` | float | 226 | 1132 | 0.007084 | 857.7 | 79.08 |  |
| `min_q_mvar` | float | 226 | 1132 | -367.6 | -0.003036 | -33.89 |  |
| `max_p_mw` | float | 226 | 1132 | 0.01012 | 1,225.31 | 113 |  |
| `min_p_mw` | float | 2 | 1132 | 0 | 0 | 0 | categorical: `-0.0`, `0.0` |

## loads

**Type:** Single file — `loads.csv`
**Directory:** `data/static/`
**Rows:** 91

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `load_name` | string | 91 | 0 |  |  |  |  |
| `bus_name` | string | 91 | 0 |  |  |  |  |

## loads_ts

**Type:** Single file — `loads_ts.csv`
**Directory:** `data/realtime/`
**Rows:** 50,000+ (sampled first 50,000)

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `datetime` | string | 550 | 0 |  |  |  |  |
| `load_name` | string | 91 | 0 |  |  |  |  |
| `in_service` | boolean | 1 | 0 |  |  |  | categorical: `True` |
| `p_mw` | float | 37252 | 0 | 4.875 | 443.4 | 98.02 |  |
| `q_mvar` | float | 35837 | 0 | 0 | 235.1 | 39.5 |  |

## LoadRNDA

**Type:** Group of 3 files (e.g. `LoadR1–3DA.csv`)
**Directory:** `data/forecasts/DA/Load/`
**Schema consistent:** Yes
**Representative file:** `LoadR1DA.csv` (8,784 rows sampled)

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `DATETIME` | string | 8784 | 0 |  |  |  |  |
| `value` | float | 8751 | 0 | 4,102.77 | 8,637.18 | 5,979.28 |  |

## SolarNDA

**Type:** Group of 75 files (e.g. `Solar1–75DA.csv`)
**Directory:** `data/forecasts/DA/Solar/`
**Schema consistent:** Yes
**Representative file:** `Solar1DA.csv` (8,784 rows sampled)

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `DATETIME` | string | 8784 | 0 |  |  |  |  |
| `value` | float | 4559 | 0 | 0 | 723.3 | 161.5 |  |

## WindNDA

**Type:** Group of 17 files (e.g. `Wind1–17DA.csv`)
**Directory:** `data/forecasts/DA/Wind/`
**Schema consistent:** Yes
**Representative file:** `Wind1DA.csv` (8,784 rows sampled)

| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |
|--------|------|--------|-------|-----|-----|------|-------|
| `DATETIME` | string | 8784 | 0 |  |  |  |  |
| `value` | float | 8703 | 0 | 0 | 6.197 | 2.497 |  |
