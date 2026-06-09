"""Sandbox child: executes ONE agent-supplied script, then exits.

This file is run as a *standalone* script (``python -I sandbox_child.py``) in a
fresh process by ``sandbox.py`` — never imported by the server. That separation
is the whole point: the code it runs is written by an LLM that an end user can
steer (prompt injection), so it is treated as hostile. The parent applies
kernel resource limits (CPU / address space / file size / processes) and a
wall-clock kill via ``preexec_fn`` before this code gets control; here we only
(a) take away the network, (b) hand the script clean pandas DataFrames, and
(c) capture whatever it produces.

Protocol (all on stdio, so the parent needs no extra fds):
    stdin  : one JSON "job"  {code, timestamp, summary, nodes, lines, paths}
    stdout : one JSON "envelope" {ok, result, stdout, error}  (and NOTHING else)
The script's own ``print`` output is captured into the envelope's ``stdout`` so
it can never corrupt the protocol.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback


# --- hardening ---------------------------------------------------------------


def _disable_network() -> None:
    """Best-effort: neuter the stdlib socket layer so a script can't phone home.

    This is defence-in-depth, not a hermetic seal (a determined script could
    reach for lower-level interfaces). The real containment is the parent's
    rlimits + timeout + the fact that no secrets live in this process's env.
    """
    import socket

    def _blocked(*_a, **_k):
        raise OSError("network access is disabled in this sandbox")

    # Keep the socket *class* importable (so `import http.client` etc. still
    # work) but make every way of actually reaching the network fail cleanly.
    socket.socket.connect = _blocked  # type: ignore[assignment]
    socket.socket.connect_ex = _blocked  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.create_server = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]


# --- JSON sanitisation (numpy / pandas scalars aren't json-native) -----------


def _san(obj):
    item = getattr(obj, "item", None)  # numpy scalar -> python scalar
    if callable(item):
        try:
            return obj.item()
        except (ValueError, TypeError):
            pass
    return str(obj)


def _describe(value):
    """Turn the script's ``result`` into something compact and json-safe.

    DataFrames/Series get a shape + a capped preview instead of dumping a
    million rows back through the model's context window.
    """
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        pd = None

    if pd is not None and isinstance(value, pd.DataFrame):
        return {
            "_type": "dataframe",
            "shape": list(value.shape),
            "columns": [str(c) for c in value.columns],
            "preview": value.head(50).to_dict("records"),
            "truncated": len(value) > 50,
        }
    if pd is not None and isinstance(value, pd.Series):
        head = value.head(50)
        return {
            "_type": "series",
            "length": int(value.shape[0]),
            "name": str(value.name) if value.name is not None else None,
            "preview": {str(k): v for k, v in head.to_dict().items()},
            "truncated": len(value) > 50,
        }
    return value


# --- the data the script is handed -------------------------------------------


def _build_namespace(job: dict) -> dict:
    """Assemble the globals the script runs against.

    Everything the agent needs is a ready-made pandas DataFrame (the 90% case:
    the static tables + the *currently viewed* solved hour). The two huge
    realtime CSVs are exposed as lazy, filtered helpers so a script can't
    accidentally pull 244 MB into memory.
    """
    import numpy as np
    import pandas as pd

    paths = job["paths"]

    # Static metadata — small, load eagerly.
    buses = pd.read_csv(paths["buses"])
    branches = pd.read_csv(paths["branches"])
    gens = pd.read_csv(paths["gens"])
    loads = pd.read_csv(paths["loads"])

    # The solved hour the operator is looking at, handed over from the parent
    # as records so we don't re-run pandapower in here. Columns match the
    # backend's Node / Line model exactly (the agent already knows them).
    nodes = pd.DataFrame(job["nodes"])
    lines = pd.DataFrame(job["lines"])

    def gen_dispatch(gen_name=None, start=None, end=None):
        """Per-generator realtime dispatch (the 244 MB ``gens_ts``), filtered.

        Pass a ``gen_name`` (and optional ISO ``start``/``end``) — the file is
        streamed in chunks and filtered, so memory stays bounded. Returns a
        DataFrame [datetime, gen_name, in_service, p_mw, ...]."""
        return _filtered_ts(
            pd, paths["gens_ts"], "gen_name", gen_name, start, end, index_col=0
        )

    def load_demand(load_name=None, start=None, end=None):
        """Per-load realtime demand (``loads_ts``), filtered the same way.
        Returns [datetime, load_name, in_service, p_mw, q_mvar]."""
        return _filtered_ts(
            pd, paths["loads_ts"], "load_name", load_name, start, end, index_col=None
        )

    def fuel_prices():
        """Daily 2024 fuel prices by region (coal / gas / biomass / ...)."""
        return pd.read_csv(paths["fuel_prices"])

    # Full data catalog (where everything lives + what's in it), keyed by name.
    # Lets a script discover the dataset & the precomputed gridstats bundle
    # rather than guessing paths. See read_table / gridstats below.
    catalog = {s["key"]: s for s in job.get("catalog", [])}

    def read_table(key):
        """Load any catalogued tabular source by key into a DataFrame (or dict for
        JSON). Use `catalog` to see what's available. Huge time-series and whole
        directories are not loadable this way — use the named helpers instead."""
        src = catalog.get(key)
        if src is None:
            raise KeyError(f"unknown data key {key!r}; available: {sorted(catalog)}")
        fmt, path = src["fmt"], src["path"]
        if fmt == "parquet":
            return pd.read_parquet(path)
        if fmt == "json":
            with open(path) as fh:
                return json.load(fh)
        if fmt == "csv":
            if src.get("lazy"):
                raise ValueError(
                    f"{key} is a large time-series; use {src.get('helper') or 'a helper'} "
                    "to filter it instead of read_table()."
                )
            return pd.read_csv(path)
        raise ValueError(
            f"{key} is a {fmt} ({path}); read individual files inside it directly."
        )

    def gridstats(name="metrics"):
        """Read a table from the precomputed gridstats bundle by short name, e.g.
        'metrics', 'branch_loadings', 'forecast', 'realtime', 'residuals',
        'branch_pct90', 'interesting_days', 'baselines'. No re-solving — these are
        a full year of stats, instant to read."""
        return read_table(f"gs_{name}")

    ns: dict = {
        "__builtins__": __builtins__,  # full builtins; containment is the OS, not a denylist
        "pd": pd,
        "np": np,
        "buses": buses,
        "branches": branches,
        "gens": gens,
        "loads": loads,
        "nodes": nodes,
        "lines": lines,
        "summary": job["summary"],
        "timestamp": job["timestamp"],
        "gen_dispatch": gen_dispatch,
        "load_demand": load_demand,
        "fuel_prices": fuel_prices,
        "catalog": catalog,
        "read_table": read_table,
        "gridstats": gridstats,
    }
    return ns


def _filtered_ts(pd, path, key, value, start, end, index_col):
    out = []
    for chunk in pd.read_csv(
        path, chunksize=250_000, index_col=index_col, parse_dates=["datetime"]
    ):
        if value is not None:
            chunk = chunk[chunk[key] == value]
        if start is not None:
            chunk = chunk[chunk["datetime"] >= pd.Timestamp(start)]
        if end is not None:
            chunk = chunk[chunk["datetime"] <= pd.Timestamp(end)]
        if len(chunk):
            out.append(chunk)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# --- entry point -------------------------------------------------------------

_MAX_STDOUT = 8000  # chars of script print() output returned to the model


def main() -> None:
    _disable_network()
    try:
        job = json.loads(sys.stdin.read())
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"bad job payload: {e}"}))
        return

    buf = io.StringIO()
    envelope: dict
    try:
        ns = _build_namespace(job)
        compiled = compile(job["code"], "<agent-script>", "exec")
        with contextlib.redirect_stdout(buf):
            exec(compiled, ns)  # noqa: S102 - this is the whole point of the file
        out = buf.getvalue()
        envelope = {
            "ok": True,
            "result": _describe(ns.get("result")),
            "stdout": out[:_MAX_STDOUT],
            "stdout_truncated": len(out) > _MAX_STDOUT,
        }
    except Exception:  # noqa: BLE001 - report any script error back to the model
        out = buf.getvalue()
        envelope = {
            "ok": False,
            "error": traceback.format_exc(limit=3),
            "stdout": out[:_MAX_STDOUT],
        }

    # The envelope is the ONLY thing on real stdout.
    sys.stdout.write(json.dumps(envelope, default=_san))


if __name__ == "__main__":
    main()
