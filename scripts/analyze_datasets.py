#!/usr/bin/env python3
"""Analyze all CSV files in a dataset directory and produce a schema + statistics markdown report."""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

# Threshold: if a column has <= this many unique values, treat as categorical
CATEGORICAL_THRESHOLD = 20


def infer_type(values: list[str]) -> str:
    """Infer column type from a sample of string values."""
    non_empty = [v for v in values if v.strip() != ""]
    if not non_empty:
        return "string (all empty)"

    # Try bool first
    bool_vals = {"true", "false"}
    if all(v.lower() in bool_vals for v in non_empty):
        return "boolean"

    # Try int
    try:
        [int(v) for v in non_empty]
        return "integer"
    except ValueError:
        pass

    # Try float
    try:
        [float(v) for v in non_empty]
        return "float"
    except ValueError:
        pass

    return "string"


def numeric_stats(values: list[str]) -> dict:
    """Compute min/max/mean/null_count for numeric values."""
    nums = []
    nulls = 0
    for v in values:
        if v.strip() == "":
            nulls += 1
        else:
            try:
                nums.append(float(v))
            except ValueError:
                return {}
    if not nums:
        return {}
    return {
        "min": min(nums),
        "max": max(nums),
        "mean": sum(nums) / len(nums),
        "null_count": nulls,
    }


def analyze_csv(path: Path, max_rows: int = 50000) -> dict:
    """Read a CSV and return schema + stats."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        # Strip BOM/whitespace from column names
        columns = [c.strip() for c in columns]
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append({k.strip(): v for k, v in row.items()})

    total_rows = len(rows)
    col_info = {}

    for col in columns:
        if not col:
            continue
        values = [r.get(col, "") for r in rows]
        dtype = infer_type(values)

        entry: dict = {"type": dtype}

        unique_vals = set(v.strip() for v in values if v.strip() != "")
        entry["unique_count"] = len(unique_vals)
        entry["null_count"] = sum(1 for v in values if v.strip() == "")

        if dtype in ("float", "integer"):
            stats = numeric_stats(values)
            if stats:
                entry.update(stats)
            if len(unique_vals) <= CATEGORICAL_THRESHOLD:
                entry["categorical"] = True
                entry["values"] = sorted(unique_vals, key=lambda x: float(x) if dtype in ("float", "integer") else x)
        elif dtype in ("string", "boolean"):
            if len(unique_vals) <= CATEGORICAL_THRESHOLD:
                entry["categorical"] = True
                entry["values"] = sorted(unique_vals)

        col_info[col] = entry

    return {
        "columns": columns,
        "col_info": col_info,
        "row_count": total_rows,
    }


def _schema_key(path: Path) -> tuple[str, ...]:
    """Return the column header tuple for a CSV (fast, reads only first line)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    return tuple(c.strip() for c in header)


def _stem_pattern(stem: str) -> str:
    """Remove all embedded digit sequences to get a canonical name pattern."""
    return re.sub(r"\d+", "#", stem)


def group_files(csv_files: list[Path]) -> list[dict]:
    """
    Group files that share the same directory AND the same column schema.
    Within a group, a common name pattern is derived by replacing digit
    runs with '#'.  Groups are ordered: singletons before multi-file groups,
    then alphabetically.
    """
    # Build (directory, schema_key) -> [paths]
    clusters: dict[tuple, list[Path]] = defaultdict(list)
    for p in csv_files:
        key = (p.parent, _schema_key(p))
        clusters[key].append(p)

    groups = []
    for (directory, schema_cols), members in clusters.items():
        members_sorted = sorted(
            members,
            key=lambda p: (
                re.sub(r"\d+", "", p.stem),
                int(re.search(r"\d+", p.stem).group()) if re.search(r"\d+", p.stem) else 0,
            ),
        )
        representative = members_sorted[0]
        analysis = analyze_csv(representative)

        # Derive a display name from common stem pattern
        patterns = {_stem_pattern(p.stem) for p in members_sorted}
        if len(patterns) == 1:
            base_name = list(patterns)[0].replace("#", "N")
        else:
            # Fallback: use the directory name
            base_name = directory.name

        groups.append({
            "files": members_sorted,
            "base_name": base_name,
            "directory": directory,
            "representative": representative,
            "analysis": analysis,
            "consistent_schema": True,  # by construction (grouped by schema)
            "is_group": len(members) > 1,
        })

    # Sort: singletons first (alphabetically), then groups (alphabetically)
    groups.sort(key=lambda g: (g["is_group"], g["base_name"].lower()))
    return groups


def format_num(x: float) -> str:
    if x == int(x):
        return str(int(x))
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    return f"{x:.4g}"


def render_markdown(groups: list[dict], dataset_root: Path, max_rows: int = 50000) -> str:
    lines = [
        "# Dataset Schema & Statistics",
        "",
        f"_Generated from `{dataset_root}/`_",
        "",
        "## Table of Contents",
        "",
    ]

    # TOC
    for g in groups:
        anchor = re.sub(r"[^a-z0-9-]", "-", g["base_name"].lower()).strip("-")
        if g["is_group"]:
            lines.append(f"- [{g['base_name']}](#{anchor}) — {len(g['files'])} files (grouped)")
        else:
            lines.append(f"- [{g['base_name']}](#{anchor})")

    lines += ["", "---", ""]

    for g in groups:
        anchor = re.sub(r"[^a-z0-9-]", "-", g["base_name"].lower()).strip("-")
        analysis = g["analysis"]
        files = g["files"]
        rep = g["representative"]
        rel_dir = g["directory"].relative_to(dataset_root)

        lines.append(f"## {g['base_name']}")
        lines.append("")

        if g["is_group"]:
            # Show range if there's a consistent digit run
            nums = [re.search(r"\d+", f.stem) for f in files]
            nums = [int(m.group()) for m in nums if m]
            if nums:
                example_name = g["base_name"].replace("N", f"{min(nums)}–{max(nums)}", 1)
                lines.append(f"**Type:** Group of {len(files)} files (e.g. `{example_name}.csv`)")
            else:
                lines.append(f"**Type:** Group of {len(files)} files")
            lines.append(f"**Directory:** `{rel_dir}/`")
            lines.append(f"**Schema consistent:** {'Yes' if g['consistent_schema'] else 'No — schemas differ!'}")
            lines.append(f"**Representative file:** `{rep.name}` ({analysis['row_count']:,} rows sampled)")
        else:
            lines.append(f"**Type:** Single file — `{rep.name}`")
            lines.append(f"**Directory:** `{rel_dir}/`")
            actual_rows = analysis["row_count"]
            if actual_rows >= max_rows:
                lines.append(f"**Rows:** {actual_rows:,}+ (sampled first {max_rows:,})")
            else:
                lines.append(f"**Rows:** {actual_rows:,}")

        lines.append("")

        # Column table
        lines.append("| Column | Type | Unique | Nulls | Min | Max | Mean | Notes |")
        lines.append("|--------|------|--------|-------|-----|-----|------|-------|")

        for col in analysis["columns"]:
            if not col:
                continue
            info = analysis["col_info"].get(col, {})
            dtype = info.get("type", "")
            unique = str(info.get("unique_count", ""))
            nulls = str(info.get("null_count", 0))
            mn = format_num(info["min"]) if "min" in info else ""
            mx = format_num(info["max"]) if "max" in info else ""
            mean = format_num(info["mean"]) if "mean" in info else ""
            notes = ""
            if info.get("categorical"):
                vals = info.get("values", [])
                vals_str = ", ".join(f"`{v}`" for v in vals[:15])
                if len(vals) > 15:
                    vals_str += f", … ({len(vals)} total)"
                notes = f"categorical: {vals_str}"
            lines.append(f"| `{col}` | {dtype} | {unique} | {nulls} | {mn} | {mx} | {mean} | {notes} |")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze CSV files in a directory and produce a schema/statistics markdown report."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory to scan recursively for CSV files",
    )
    parser.add_argument(
        "output_file",
        type=Path,
        help="Path for the output markdown file",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=50000,
        metavar="N",
        help="Maximum rows to sample per file for statistics (default: 50000)",
    )
    args = parser.parse_args()

    dataset_root = args.input_dir.resolve()
    if not dataset_root.is_dir():
        parser.error(f"Input directory does not exist: {dataset_root}")

    csv_files = sorted(dataset_root.rglob("*.csv"))
    print(f"Found {len(csv_files)} CSV files.")

    groups = group_files(csv_files)
    print(f"Identified {len(groups)} logical table(s).")

    md = render_markdown(groups, dataset_root=dataset_root, max_rows=args.max_rows)
    args.output_file.write_text(md, encoding="utf-8")
    print(f"Report written to: {args.output_file}")


if __name__ == "__main__":
    main()
