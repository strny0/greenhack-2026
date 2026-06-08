"""Parent side of the Python runtime: spawn, constrain, and reap the child.

The agent's ``run_python`` tool calls :func:`run_user_code`. We treat the
script as hostile (an end user can prompt-inject the model into emitting
anything), so the containment is structural, not a denylist:

* **separate process** — a crash / segfault / infinite loop dies on its own and
  cannot take FastAPI down with it;
* **kernel rlimits** (``preexec_fn``) — caps CPU time, address space, file
  writes, and process count, so no fork bomb / 50 GB allocation;
* **wall-clock kill** — the whole process *group* is SIGKILLed past a deadline;
* **scrubbed env + isolated mode** — no ``AI_API_KEY`` (or any secret) is
  inherited, ``PYTHONPATH`` / user site are ignored;
* **neutral cwd** — runs in a temp dir, not the repo.

What the child can still do (read the data CSVs, burn a few CPU-seconds) is by
design — that's the feature.
"""
from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, engine

_CHILD = Path(__file__).resolve().parent / "sandbox_child.py"

# Resource ceilings for the child. Generous enough for pandas + a filtered pass
# over the 244 MB realtime CSV, tight enough that nothing here threatens the box.
_CPU_SECONDS = 10  # SIGXCPU after this much *CPU* time
_ADDRESS_SPACE = 2 * 1024**3  # 2 GiB virtual memory
_FILE_SIZE = 64 * 1024**2  # 64 MiB max single-file write
_WALL_TIMEOUT = 15  # seconds of real time before we SIGKILL the group

# NB: we deliberately do NOT set RLIMIT_NPROC. It is per-UID and counts *all* the
# server user's existing threads, so a fixed cap (a) breaks numpy/BLAS thread
# spawning on a busy box and (b) gives no real protection anyway. A fork bomb is
# instead bounded by: single-threaded child + RLIMIT_AS (each proc costs memory)
# + the process-group SIGKILL on timeout. Hard process-count capping belongs in a
# cgroup (`pids.max`) — worth it for a public deploy, overkill for a localhost demo.


def _preexec() -> None:  # runs in the child, after fork, before exec
    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS + 2))
    resource.setrlimit(resource.RLIMIT_AS, (_ADDRESS_SPACE, _ADDRESS_SPACE))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_SIZE, _FILE_SIZE))
    os.setsid()  # own session/process group, so we can killpg the whole subtree


def _data_paths() -> dict[str, str]:
    return {
        "buses": str(config.STATIC_DIR / "buses.csv"),
        "branches": str(config.STATIC_DIR / "branches.csv"),
        "gens": str(config.STATIC_DIR / "gens.csv"),
        "loads": str(config.STATIC_DIR / "loads.csv"),
        "gens_ts": str(config.REALTIME_DIR / "gens_ts.csv"),
        "loads_ts": str(config.REALTIME_DIR / "loads_ts.csv"),
        "fuel_prices": str(config.DATA_DIR / "other" / "Fuel prices 2024.csv"),
    }


def run_user_code(code: str, timestamp: str) -> dict:
    """Execute ``code`` in a locked-down child and return its result envelope.

    Returns one of:
      {"ok": True,  "result": ..., "stdout": str, "stdout_truncated": bool}
      {"ok": False, "error": str, "stdout"?: str}
    Always a dict — never raises — so it slots straight into a tool result.
    """
    # Solve / fetch the viewed hour HERE (in the trusted parent) and hand the
    # child plain records; the child never needs pandapower.
    frame = engine.base_frame(timestamp)
    job = {
        "code": code,
        "timestamp": frame.timestamp,
        "summary": frame.summary.model_dump(),
        "nodes": [n.model_dump() for n in frame.nodes],
        "lines": [l.model_dump() for l in frame.lines],
        "paths": _data_paths(),
    }
    payload = json.dumps(job)

    # Minimal, secret-free environment. Pin BLAS/OpenMP to one thread so the
    # child starts fast, runs deterministically, and doesn't spawn a thread pool.
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": tempfile.gettempdir(),
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }

    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", str(_CHILD)],  # -I: isolated (ignore env/site)
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=tempfile.gettempdir(),
            preexec_fn=_preexec,
            text=True,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"failed to start sandbox: {e}"}

    try:
        out, err = proc.communicate(payload, timeout=_WALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.communicate()
        return {
            "ok": False,
            "error": f"script exceeded the {_WALL_TIMEOUT}s wall-clock limit and was killed.",
        }

    if proc.returncode and proc.returncode != 0:
        # Non-zero usually means the kernel killed it (rlimit / OOM / signal).
        reason = _signal_reason(proc.returncode)
        tail = (err or "").strip().splitlines()[-3:]
        return {
            "ok": False,
            "error": f"sandbox process exited abnormally ({reason}).",
            "stderr": "\n".join(tail),
        }

    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": "sandbox produced no parseable result.",
            "stderr": (err or "").strip()[-500:],
        }


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _signal_reason(returncode: int) -> str:
    if returncode < 0:
        sig = -returncode
        name = signal.Signals(sig).name if sig in iter(signal.Signals) else f"signal {sig}"
        hints = {
            "SIGKILL": "out of memory or wall-clock kill",
            "SIGXCPU": "CPU time limit",
            "SIGXFSZ": "file size limit",
            "SIGSEGV": "segfault",
        }
        return f"{name}: {hints.get(name, 'killed')}"
    return f"exit code {returncode}"
