"""t261019-17: the close-out guard must be able to resolve the delivery ledger
inside the Temporal workflow sandbox.

Measured 261019: t261019-02 put `develop_certify.ledger_path()` on the merge close-out path,
which runs in the sandbox; `ledger_path` reads `os.environ`, the sandbox raised
RestrictedWorkflowAccessError, and two tickets were refused with "delivery ledger unreadable".
The fix pins the root at the process entry (worker.py, not sandboxed) and reads the pin without
touching the environment; an unpinned process keeps the legacy env path.

The sandbox is simulated the way Temporal does it: any attribute access on `os.environ` raises.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import develop_certify as dc  # noqa: E402
import shared  # noqa: E402


class _SandboxedEnviron(dict):
    """The delivery-ledger key is the one the sandbox refuses; everything else keeps
    working so pytest's own environment reads are unaffected."""

    def get(self, key, *a, **k):
        if key == dc.LEDGER_DIR_ENV:
            raise RuntimeError("RestrictedWorkflowAccessError: Cannot access "
                               "os.environ.get from inside a workflow.")
        return super().get(key, *a, **k)

    def __getitem__(self, key):
        if key == dc.LEDGER_DIR_ENV:
            raise RuntimeError("RestrictedWorkflowAccessError: Cannot access os.environ "
                               "from inside a workflow.")
        return super().__getitem__(key)


@pytest.fixture()
def sandbox(monkeypatch):
    """Pin a ledger root, then make the environment unreadable (the sandbox)."""
    monkeypatch.setattr(shared, "_DELIVERY_LEDGER_DIR", "", raising=False)
    shared.note_delivery_ledger_dir("/tmp/ledger-pinned")
    monkeypatch.setattr(os, "environ", _SandboxedEnviron(os.environ))
    return None


def test_pinned_root_resolves_inside_the_sandbox(sandbox):
    path = dc.ledger_path("sandbar")
    assert str(path) == "/tmp/ledger-pinned/sandbar.jsonl"


def test_unpinned_process_keeps_the_legacy_env_path(monkeypatch):
    monkeypatch.setattr(shared, "_DELIVERY_LEDGER_DIR", "", raising=False)
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", "/tmp/ledger-env")
    assert str(dc.ledger_path("sandbar")) == "/tmp/ledger-env/sandbar.jsonl"


def test_unpinned_sandbox_still_fails_loudly(monkeypatch):
    """No pin + no env readable = the read fails; the guard translates it into a named
    refusal (fail-closed). Never a silent empty ledger."""
    monkeypatch.setattr(shared, "_DELIVERY_LEDGER_DIR", "", raising=False)
    monkeypatch.setattr(os, "environ", _SandboxedEnviron(os.environ))
    with pytest.raises(RuntimeError):
        dc.ledger_path("sandbar")


def test_worker_pins_the_root_at_startup():
    src = (Path(__file__).resolve().parents[1] / "worker.py").read_text()
    assert "note_delivery_ledger_dir" in src


def test_guard_uses_the_resolved_path_without_env(sandbox):
    """The close-out guard resolves the ledger through ledger_path, so the pinned root
    is enough for it to read the store (empty store -> no refusal)."""
    assert dc.ledger_path("sandbar").exists() is False  # nothing written
    assert dc.read_rows(dc.ledger_path("sandbar")) == ([], [])
