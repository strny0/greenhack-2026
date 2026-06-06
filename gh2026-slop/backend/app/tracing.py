"""Server-side usage log for the dispatcher agent.

The frontend keeps each visitor's chat history in their own browser (localStorage),
so the operator can't see it. This module appends one JSON line per agent turn to a
log file on the server, giving a single place to answer "did anyone use the chat,
and what did they ask?".

Records are deliberately lightweight (latest question + the agent's reply + a bit of
context), not the full message tree. Writes are best-effort and never raise into the
request path — tracing must never break the chat itself.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from . import config

_lock = threading.Lock()


def _client_ip(headers: dict, fallback: str | None) -> str | None:
    """Real client IP, honouring the nginx/ZeroTier reverse proxy in front of us."""
    fwd = headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("x-real-ip") or fallback


def build_record(
    *,
    headers: dict,
    client_host: str | None,
    messages: list[dict],
    timestamp: str,
    selection: dict | None,
    simulation: dict | None,
    reply: str,
    tools: list[str],
    error: str | None,
) -> dict[str, Any]:
    """Assemble a trace record for one completed (or aborted) agent turn."""
    last_user = next(
        (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
        None,
    )
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ip": _client_ip(headers, client_host),
        "ua": headers.get("user-agent"),
        "viewed_hour": timestamp,
        "selection": selection,
        "sim_active": bool(simulation),
        "n_messages": len(messages),
        "question": last_user,
        "reply": reply or None,
        "tools": tools or None,
        "error": error,
    }


def append(record: dict[str, Any]) -> None:
    """Append one record as a JSON line. Best-effort: failures are swallowed."""
    if not config.CHAT_TRACING:
        return
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            config.CHAT_TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with config.CHAT_TRACE_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001 — tracing must never break the request
        pass


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    """Most-recent-first list of trace records, for the admin view."""
    path = config.CHAT_TRACE_FILE
    if not path.is_file():
        return []
    try:
        with _lock, path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def stats() -> dict[str, Any]:
    """Quick rollup for the admin view header: turns, unique IPs, last activity."""
    records = read_recent(limit=10_000)
    ips = {r.get("ip") for r in records if r.get("ip")}
    return {
        "total_turns": len(records),
        "unique_ips": len(ips),
        "last_activity": records[0]["ts"] if records else None,
        "tracing_enabled": config.CHAT_TRACING,
    }
