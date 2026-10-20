"""t261016-19 — engine out-of-scope disposal hygiene (unit tier, L1).

Three faces, one settle path:
  Face 1  the lane's own virtualenv is judged an out-of-scope write and moved to
          quarantine (t261016-15: 68-69 reds, all `.venv-<ticket>/...`).
  Face 2a the disposal's unstaged-M branch auto-reverted the lane's in-flight fix
          (t261016-11 "THIRD settle drop", t261016-09).
  Face 2b a committed deletion orphaned a module another delivered file still
          imports (foreign_write.py vs agent_activities.py, KI-01M4PAVBP6E...).

Borrowed mechanisms carry their source fault-modes (review comment 3):
  - KI-009 parser stance (fail-closed on malformed paths) -> truth table below;
  - freshness-exemption lesson (no silent zero-count exemption note) -> the
    settle-filter note face is pinned via the pure predicate + the exempt note
    is assembled only when the count is > 0 (grep-pin in this file);
  - t261004-34 lesson (idempotent re-run) -> the filter is a pure set
    difference, re-running it is a no-op (asserted).
The engine module is imported under the real engine venv (temporalio present).
"""

import json
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_activities  # noqa: E402
import shared  # noqa: E402


# ---- Face 1: is_engine_runtime_path — the exempt set, pinned exactly ----

@pytest.mark.parametrize("path,expected", [
    # the incident shape: the lane's own venv, first component
    (".venv-t261016-15/lib/python3.9/site-packages/x.py", True),
    # KI-015 family: status -z never quote-wraps; unicode names must judge on shape
    (".venv-t1/lib/pkg-ünïcode.dist-info/RECORD", True),
    (".venv/bin/python", True),
    (".venv-t261016-15", True),
    # the engine venv carried by a lane tree
    ("server/engine/.venv/bin/python", True),
    ("server/engine/.venv/lib/x.py", True),
    # NOT exempt: over-broad matches would exempt real out-of-write-set edits
    ("src/.venv/x.py", False),
    ("venv/x.py", False),
    (".venvfoo/x.py", False),
    ("server/engine/.venvfoo/x.py", False),
    ("server/engine/main.py", False),
    ("a/.venv-t1/x", False),
])
def test_engine_runtime_path_truth_table(path, expected):
    assert shared.is_engine_runtime_path(path) is expected


@pytest.mark.parametrize("bad", [None, 42, "", "/abs/.venv/x", ".venv/../evil",
                                 "a/../b", "a//b", "/", []])
def test_engine_runtime_path_malformed_fail_closed(bad):
    # fail-closed: malformed input is never exempted (KI-009 parser stance)
    assert shared.is_engine_runtime_path(bad) is False


def test_engine_runtime_path_idempotent_reapply():
    # t261004-34 lesson: the exemption must survive a re-run unchanged (replay-safe)
    dirty = [".venv-t1/lib/x.py", "server/engine/main.py", ".venv/bin/py"]
    exempt = [f for f in dirty if shared.is_engine_runtime_path(f)]
    keep = [f for f in dirty if f not in exempt]
    exempt2 = [f for f in keep if shared.is_engine_runtime_path(f)]
    assert exempt2 == []
    assert keep == ["server/engine/main.py"]


# ---- Face 2a: the disposal matrix — ?? moved, M left in place, no checkout ----

class _GitRecorder:
    """Record _git argv calls. The reconciled 261017 contract DOES perform one
    `git checkout --` (the archived revert of an out-of-write-set edit), so calls are
    recorded rather than forbidden; a test that must forbid it asserts on rec.calls."""

    def __init__(self, rc=0, out=""):
        self.calls = []
        self.rc = rc
        self.out = out

    def __call__(self, args, cwd=None):
        self.calls.append(list(args))
        r = type("R", (), {"returncode": self.rc, "stdout": self.out, "stderr": ""})
        return r


def test_disposal_moves_untracked_and_reverts_modified_with_archive(tmp_path, monkeypatch):
    """261017 reconciliation (host ruling): the untracked file is still moved to
    quarantine, and the out-of-write-set M is now diff-archived then reverted with
    `git checkout --` — the t26091619-incident-replay contract ("a shared tool must not
    end up committed by the settle; the change stays recoverable via git apply") that
    the delivered cases pin, and the reason the t261016-19 Face 2a retirement could not
    stand. The engine runtime and a write_set_missing refusal still leave the file in
    place (separate tests)."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "new.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "fix.py").write_text("fix = 'in-flight'\n", encoding="utf-8")
    diff_text = ("--- a/pkg/fix.py\n+++ b/pkg/fix.py\n@@ -1 +1 @@\n-fix = 'HEAD'\n"
                 "+fix = 'in-flight'\n")
    rec = _GitRecorder(out=diff_text)
    monkeypatch.setattr(agent_activities, "_git", rec)
    handled, unhandled = agent_activities._remediate_unauthorized_violations(
        tmp_path, "arbitrate", 0,
        ["pkg/new.py", "pkg/fix.py"],
        [("??"[:1] + "?", "pkg/new.py"), (" M", "pkg/fix.py")],
        reason="unauthorized_path")
    # the untracked new file is moved to quarantine, path preserved
    assert any("pkg/new.py" in h for h in handled)
    assert not (tmp_path / "pkg" / "new.py").exists()
    batches = list((tmp_path / ".sandbar" / "quarantine").glob("unauth-arbitrate-gen0*"))
    assert len(batches) == 1
    assert (batches[0] / "pkg" / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    # the M file: archived first, then reverted by exactly one `git checkout --`
    diffs = sorted(batches[0].glob("*.diff"))
    assert len(diffs) == 1
    assert "in-flight" in diffs[0].read_text(encoding="utf-8")
    assert ["checkout", "--", "pkg/fix.py"] in [c for c in rec.calls]
    assert ["diff", "--", "pkg/fix.py"] in [c for c in rec.calls]
    # manifest records both actions; the M one is reverted and names its archive
    manifest = json.loads((batches[0] / "manifest.json").read_text(encoding="utf-8"))
    actions = {it["path"]: it["action"] for it in manifest["items"]}
    assert actions["pkg/new.py"] == "moved"
    assert actions["pkg/fix.py"] == "reverted"
    assert manifest["ticket_stage"] == "arbitrate"


def test_disposal_missing_source_and_unknown_xy_fail_closed(tmp_path, monkeypatch):
    rec = _GitRecorder()
    monkeypatch.setattr(agent_activities, "_git", rec)
    handled, unhandled = agent_activities._remediate_unauthorized_violations(
        tmp_path, "arbitrate", 1,
        ["gone.py", "staged.py", "deleted.py"],
        [("??"[:1] + "?", "gone.py"), ("M ", "staged.py"), (" D", "deleted.py")])
    assert handled == []
    assert set(unhandled) == {"gone.py", "staged.py", "deleted.py"}
    # nothing archivable -> no batch dir left behind (no empty quarantine noise)
    assert not list((tmp_path / ".sandbar" / "quarantine").glob("unauth-*"))


# ---- Face 2b: deleted module still imported — the named gate check ----

def test_import_integrity_catches_the_incident_shape():
    deleted = ["server/engine/foreign_write.py"]
    sources = {
        "server/engine/agent_activities.py": textwrap.dedent("""\
            import json
            import foreign_write
            from foreign_write import helper
            x = 1
            """),
        "server/engine/shared.py": "import os\n",
    }
    violations, skipped = agent_activities.deleted_modules_still_imported(deleted, sources)
    assert violations == ["foreign_write still imported by server/engine/agent_activities.py"]
    assert skipped == []


def test_import_integrity_clean_and_dotted_shapes():
    src = textwrap.dedent("""\
        from a.b.foreign_write import helper
        import a.foreign_write.sub
        """)
    v, s = agent_activities.deleted_modules_still_imported(
        ["server/engine/foreign_write.py"], {"x.py": src})
    assert len(v) == 1 and "x.py" in v[0] and s == []
    # deleted but truly unimported -> clean
    v, s = agent_activities.deleted_modules_still_imported(
        ["server/engine/lonely.py"], {"x.py": "import foreign_write\n"})
    assert (v, s) == ([], [])


def test_import_integrity_malformed_and_traversal_inputs():
    # non-.py / malformed deleted entries are ignored (fail-closed, no crash)
    v, s = agent_activities.deleted_modules_still_imported(
        ["", None, 42, "notpython.txt", "notes/readme.md"], {"x.py": "import m\n"})
    assert (v, s) == ([], [])
    # an unparseable importer source is a NAMED skip, never a silent pass
    v, s = agent_activities.deleted_modules_still_imported(
        ["a/m.py"], {"broken.py": "def f(:\n", "ok.py": "import m\n"})
    assert v == ["m still imported by ok.py"]
    assert s == ["broken.py"]
    # non-str source text is ignored, empty inputs degenerate cleanly
    v, s = agent_activities.deleted_modules_still_imported(["a/m.py"], {"b.py": None})
    assert (v, s) == ([], [])
    assert agent_activities.deleted_modules_still_imported([], {}) == ([], [])


# ---- the settle-filter exemption note is never silent-zero (borrowed fault-mode) ----

def test_exempt_note_only_assembled_on_nonempty():
    # grep-pin: the note is built inside `if _runtime_exempt:` — a zero-count
    # exemption must leave no note face (freshness-exemption lesson, t261002-10 gen1-4)
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent_activities.py"), encoding="utf-8").read()
    assert "if _runtime_exempt:" in src
    assert src.count("runtime_exempt_note") >= 4  # build, log, append, early-return
