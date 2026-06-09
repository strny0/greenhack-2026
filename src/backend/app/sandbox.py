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
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from . import data_index, engine

_CHILD = Path(__file__).resolve().parent / "sandbox_child.py"

# Resource ceilings for the child. Generous enough for pandas + a filtered pass
# over the 244 MB realtime CSV or the gridstats parquet bundle, tight enough that
# nothing here threatens the box. CPU is the binding constraint for heavy work;
# wall-clock is the backstop that also reaps a sleeping/blocked child.
_CPU_SECONDS = 80  # SIGXCPU after this much *CPU* time
_ADDRESS_SPACE = 2 * 1024**3  # 2 GiB virtual memory
_FILE_SIZE = 64 * 1024**2  # 64 MiB max single-file write
_WALL_TIMEOUT = 90  # seconds of real time before we SIGKILL the group
_MAX_ATTEMPTS = 3  # transient sandbox failures are retried up to this many times total

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


def run_user_code(code: str, timestamp: str) -> dict:
    """Execute ``code`` in a locked-down child and return its result envelope.

    Returns one of:
      {"ok": True,  "result": ..., "stdout": str, "stdout_truncated": bool}
      {"ok": False, "error": str, "stdout"?: str}
    Always a dict — never raises — so it slots straight into a tool result.

    A *transient* sandbox failure (couldn't start the child, the child crashed on
    a signal / OOM, or it produced no parseable output) is retried up to
    ``_MAX_ATTEMPTS`` times — these are flaky and a fresh process often succeeds.
    A *deterministic* outcome (success, a Python error from the script itself, or
    a wall-clock timeout) is returned immediately: re-running identical code would
    only reproduce it, so the model should see it and adapt instead. ``attempts``
    is added to the envelope when more than one try was made.
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
        "paths": data_index.paths_map(),
        "catalog": data_index.catalog_records(),
    }
    payload = json.dumps(job)

    attempt = 0
    result: dict = {"ok": False, "error": "sandbox did not run"}
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result = _run_once(payload)
        if not result.get("retryable") or attempt == _MAX_ATTEMPTS:
            break
    result.pop("retryable", None)  # internal flag, never surfaced to the caller
    if attempt > 1:
        result["attempts"] = attempt
    return result


def _run_once(payload: str) -> dict:
    """One sandbox invocation. Transient/infrastructure failures carry
    ``"retryable": True`` so :func:`run_user_code` can try again; a clean result
    or a script-level error (parsed from the child's stdout) does not."""
    # A FRESH, private working directory per run: the child runs with cwd here, so
    # a script that lists '.' sees an empty dir — never the host's shared /tmp
    # (which would leak sockets, credential caches, etc.). Torn down afterwards.
    workdir = tempfile.mkdtemp(prefix="gridpy_")

    # Minimal, secret-free environment. Pin BLAS/OpenMP to one thread so the
    # child starts fast, runs deterministically, and doesn't spawn a thread pool.
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": workdir,
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }

    try:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", str(_CHILD)],  # -I: isolated (ignore env/site)
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=workdir,
                preexec_fn=_preexec,
                text=True,
            )
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"failed to start sandbox: {e}", "retryable": True}

        try:
            out, err = proc.communicate(payload, timeout=_WALL_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.communicate()
            # Deterministic: a slow script will just time out again — don't retry.
            return {
                "ok": False,
                "error": f"script exceeded the {_WALL_TIMEOUT}s wall-clock limit and was killed.",
            }

        if proc.returncode and proc.returncode != 0:
            # Non-zero usually means the kernel killed it (rlimit / OOM / signal) —
            # often transient (e.g. a momentary memory spike), so retryable.
            reason = _signal_reason(proc.returncode)
            tail = (err or "").strip().splitlines()[-3:]
            return {
                "ok": False,
                "error": f"sandbox process exited abnormally ({reason}).",
                "stderr": "\n".join(tail),
                "retryable": True,
            }

        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": "sandbox produced no parseable result.",
                "stderr": (err or "").strip()[-500:],
                "retryable": True,
            }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
