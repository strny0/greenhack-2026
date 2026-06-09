"""run_python sandbox: transient-failure retry + working-directory isolation."""
from app import sandbox
from app.data_loader import store


def _ts() -> str:
    return store.timestamps[0]


def test_transient_failure_retries_then_succeeds(monkeypatch):
    n = {"c": 0}

    def fake(payload):
        n["c"] += 1
        if n["c"] < 3:
            return {"ok": False, "error": "transient", "retryable": True}
        return {"ok": True, "result": "done"}

    monkeypatch.setattr(sandbox, "_run_once", fake)
    out = sandbox.run_user_code("result=1", _ts())
    assert out["ok"] is True
    assert n["c"] == 3
    assert out["attempts"] == 3
    assert "retryable" not in out


def test_script_error_is_not_retried(monkeypatch):
    n = {"c": 0}

    def fake(payload):
        n["c"] += 1
        return {"ok": False, "error": "Traceback ... KeyError: 'nope'"}  # no retryable flag

    monkeypatch.setattr(sandbox, "_run_once", fake)
    out = sandbox.run_user_code("result=buses['nope']", _ts())
    assert out["ok"] is False
    assert n["c"] == 1  # deterministic script error — ran once, no retry
    assert "attempts" not in out


def test_persistent_transient_exhausts_attempts(monkeypatch):
    n = {"c": 0}

    def fake(payload):
        n["c"] += 1
        return {"ok": False, "error": "always transient", "retryable": True}

    monkeypatch.setattr(sandbox, "_run_once", fake)
    out = sandbox.run_user_code("result=1", _ts())
    assert out["ok"] is False
    assert n["c"] == 3  # capped at _MAX_ATTEMPTS
    assert out["attempts"] == 3
    assert "retryable" not in out  # internal flag stripped before returning


def test_sandbox_cwd_is_isolated_empty_dir():
    """A real run: listing '.' must show the private empty workdir, not host /tmp."""
    out = sandbox.run_user_code("import os; result = sorted(os.listdir('.'))", _ts())
    assert out["ok"] is True
    assert out["result"] == []
