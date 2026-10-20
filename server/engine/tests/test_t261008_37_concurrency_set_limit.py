# -*- coding: utf-8 -*-
"""t261008-37 CL-2b engine concurrency-limit write entry - unit tests.

Covers the ticket's evidence bars:
- L1 truth table: every illegal payload refused BY NAME with BOTH the
  declaration file and the audit file byte-identical (sha256 before/after,
  proven not asserted); a legal integer and "unlimited" land; the audit row
  carries ts/by/from/to and the receipt's audit_row equals the file's tail
  line (KI-198: writer-says == reader-sees);
- zero side effect on refusal (hash comparison on every refusal case);
- audit-append failure rolls the declaration back (rollback exercised for
  real by pointing the audit path at a directory - no mocks);
- first Save creates the declaration (from=null), the same path the scenario
  probe exercises;
- read face (ticket item 5): read_state reflects the new limit immediately;
- enforcement semantics (ticket item 6): lowering touches no holder/queue
  byte, raising drains the queue through the EXISTING release promotion (no
  new code);
- L3: the REAL spawn the panel uses (client.py concurrency-limit-write)
  against an isolated projects root - exit-code contract, receipt shape
  matching the panel parser contract (top-level boolean saved + audit_row
  ts/by/from/to), malformed-argv refusal, unknown-subcommand refusal intact
  (the panel's engine-entry-absent detection), and the ticket.py read face
  agreeing with the written declaration;
- admin.log trail: the entry attempt lands an audit row even on refusal
  (KI-067 review comment - the raw-receipt entry cannot use _emit, so it
  logs through audit.audit_call directly).

Zero Temporal / zero network / zero git; the declaration root is injected
into a temp dir via SANDBAR_PROJECTS_DIR.
"""
import hashlib
import json
import time
import os
import subprocess
import sys

import pytest

import concurrency as cc  # noqa: E402
import shared  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CLIENT_PY = os.path.join(REPO, "server", "engine", "client.py")
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Isolated bench: root + one project with declaration limit=2 and an
    empty audit file. Returns (root, key)."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    key = "proj-alpha"
    d = root / key
    d.mkdir()
    (d / cc.DECL_FILE).write_text(json.dumps({"version": 1, "limit": 2}),
                                  encoding="utf-8")
    (d / cc.AUDIT_FILE).write_text("", encoding="utf-8")
    return root, key


def _pair_bytes(root, key):
    d = root / key
    out = {}
    for name in (cc.DECL_FILE, cc.AUDIT_FILE):
        p = d / name
        if p.is_dir():
            out[name] = "<dir>"       # the rollback test points the audit path
        else:                         # at a directory on purpose
            out[name] = p.read_bytes() if p.exists() else None
    return out


def _pair_unchanged(root, key, before):
    assert _pair_bytes(root, key) == before, \
        "a refused write must leave BOTH files byte-identical"


def _tail_row(root, key):
    p = root / key / cc.AUDIT_FILE
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lines[-1])


# ---------- L1 truth table: refusals are named and touch nothing ----------

REFUSALS = [
    ("payload-not-object", None, "payload must be a JSON object"),
    ("payload-string", "nope", "payload must be a JSON object"),
    ("missing-project", {"limit": 5, "by": "host"}, "project key"),
    ("empty-project", {"project": "", "limit": 5, "by": "host"}, "project key"),
    ("bad-project-key", {"project": "BAD_KEY!", "limit": 5, "by": "host"},
     "PROJECT_KEY_RE"),
    ("missing-limit", {"project": "proj-alpha", "by": "host"},
     "limit key is missing"),
    ("zero", {"project": "proj-alpha", "limit": 0, "by": "host"},
     "Out-of-range"),
    ("eleven", {"project": "proj-alpha", "limit": 11, "by": "host"},
     "Out-of-range"),
    ("negative", {"project": "proj-alpha", "limit": -1, "by": "host"},
     "Out-of-range"),
    ("numeric-string", {"project": "proj-alpha", "limit": "3", "by": "host"},
     "Malformed concurrency-limit"),
    ("float", {"project": "proj-alpha", "limit": 5.5, "by": "host"},
     "Malformed concurrency-limit"),
    ("boolean", {"project": "proj-alpha", "limit": True, "by": "host"},
     "Malformed concurrency-limit"),
    ("null-limit", {"project": "proj-alpha", "limit": None, "by": "host"},
     "Malformed concurrency-limit"),
    ("unknown-word", {"project": "proj-alpha", "limit": "nope", "by": "host"},
     "Malformed concurrency-limit"),
    ("missing-by", {"project": "proj-alpha", "limit": 5}, "by must be"),
    ("empty-by", {"project": "proj-alpha", "limit": 5, "by": "  "}, "by must be"),
    ("non-string-by", {"project": "proj-alpha", "limit": 5, "by": 7}, "by must be"),
    ("boolean-by", {"project": "proj-alpha", "limit": 5, "by": True}, "by must be"),
    ("source-not-object", {"project": "proj-alpha", "limit": 5, "by": "host",
                           "source": "x"}, "source must be a JSON object"),
]


@pytest.mark.parametrize("name,payload,needle", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_refusal_named_and_zero_side_effect(proj, name, payload, needle):
    root, key = proj
    before = _pair_bytes(root, key)
    r = cc.set_limit(payload)
    assert r.get("saved") is False, name
    assert isinstance(r.get("reason"), str) and r["reason"], name
    assert needle in r["reason"], (name, r["reason"])
    _pair_unchanged(root, key, before)


def test_unknown_extra_keys_ignored(proj):
    """The scenario probe payload carries caller_project - ignored, not refused."""
    root, key = proj
    r = cc.set_limit({"project": key, "limit": 3, "by": "host",
                      "caller_project": key})
    assert r["saved"] is True


# ---------- legal writes land: integer + unlimited ----------

def test_save_integer(proj):
    root, key = proj
    r = cc.set_limit({"project": key, "limit": 5, "by": "host", "source": {}})
    assert r["saved"] is True
    assert r["project"] == key and r["limit"] == 5
    decl = json.loads((root / key / cc.DECL_FILE).read_text(encoding="utf-8"))
    assert decl == {"version": 1, "limit": 5}
    row = _tail_row(root, key)
    # audit row shape: ts / by / from / to; actor IS the payload by
    assert isinstance(row["ts"], float) and row["by"] == "host"
    assert row["from"] == 2 and row["to"] == 5
    # KI-198: the receipt's audit row equals what landed in the file
    assert r["audit_row"] == {"ts": row["ts"], "by": row["by"],
                              "from": row["from"], "to": row["to"]}


def test_save_unlimited(proj):
    root, key = proj
    r = cc.set_limit({"project": key, "limit": "unlimited", "by": "host"})
    assert r["saved"] is True and r["limit"] == "unlimited"
    decl = json.loads((root / key / cc.DECL_FILE).read_text(encoding="utf-8"))
    assert decl == {"version": 1, "limit": "unlimited"}
    assert cc.load_limit(key) is None
    assert _tail_row(root, key)["to"] == "unlimited"
    # the read face models unlimited as limit=None immediately
    assert cc.read_state(key)["unlimited"] is True


def test_first_save_creates_declaration(proj, tmp_path, monkeypatch):
    root, _ = proj
    key = "brand-new"
    r = cc.set_limit({"project": key, "limit": 3, "by": "host"})
    assert r["saved"] is True
    decl = json.loads((root / key / cc.DECL_FILE).read_text(encoding="utf-8"))
    assert decl == {"version": 1, "limit": 3}
    row = _tail_row(root, key)
    assert row["from"] is None and row["to"] == 3   # first Save: nothing before
    assert cc.read_state(key)["limit"] == 3


def test_same_value_resave_is_audited(proj):
    root, key = proj
    r = cc.set_limit({"project": key, "limit": 2, "by": "host"})
    assert r["saved"] is True
    row = _tail_row(root, key)
    assert row["from"] == 2 and row["to"] == 2


# ---------- rollback: audit-append failure restores the declaration ----------

def test_audit_failure_rolls_declaration_back(proj):
    root, key = proj
    audit_file = root / key / cc.AUDIT_FILE
    audit_file.unlink()
    audit_file.mkdir()          # append now fails with IsADirectoryError
    before = _pair_bytes(root, key)
    r = cc.set_limit({"project": key, "limit": 5, "by": "host"})
    assert r["saved"] is False and "Concurrency-limit write" in r["reason"]
    _pair_unchanged(root, key, before)   # declaration restored, byte-identical


# ---------- read face + enforcement semantics (ticket items 5 and 6) ----------

def test_read_face_reflects_new_limit_immediately(proj):
    root, key = proj
    assert cc.read_state(key)["limit"] == 2
    cc.set_limit({"project": key, "limit": 5, "by": "host"})
    assert cc.read_state(key)["limit"] == 5   # no restart, no cache


def test_lowering_touches_no_holder_or_queue_byte(proj):
    root, key = proj
    state = {"version": 1, "holders": [{"ticket": "t1", "since": 1.0,
                                        "reason": "running"}],
             # 261019: `since` is the waiter's HEARTBEAT, not "queued at"
             # (concurrency.QUEUE_STALE_S) - seed it as a live poll would.
             "queue": [{"ticket": "t2", "since": time.time()}]}
    (root / key / cc.STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    before = (root / key / cc.STATE_FILE).read_bytes()
    r = cc.set_limit({"project": key, "limit": 1, "by": "host"})
    assert r["saved"] is True
    # EXISTING guarantee (no new code): the holder keeps its slot; only the
    # next acquire judges against the lower limit.
    assert (root / key / cc.STATE_FILE).read_bytes() == before
    face = cc.read_state(key)
    assert len(face["holders"]) == 1 and face["limit"] == 1


def test_raising_drains_through_existing_release_promotion(proj):
    root, key = proj
    state = {"version": 1, "holders": [{"ticket": "t1", "since": 1.0,
                                        "reason": "running"}],
             # 261019: `since` is the waiter's HEARTBEAT, not "queued at"
             # (concurrency.QUEUE_STALE_S) - seed it as a live poll would.
             "queue": [{"ticket": "t2", "since": time.time()}]}
    (root / key / cc.STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    # the write itself promotes nothing - drain rides the EXISTING promotion
    # path (release/reconcile), which re-reads the limit per event
    r = cc.set_limit({"project": key, "limit": 5, "by": "host"})
    assert r["saved"] is True
    assert len(json.loads((root / key / cc.STATE_FILE)
              .read_text(encoding="utf-8"))["holders"]) == 1
    res = cc.release(key, "t1", "terminated")
    assert res["promoted"] == "t2" and res["holders"] == 1


# ---------- L3: the REAL spawn the panel uses ----------

def _spawn(root, argv, timeout=60):
    env = dict(os.environ, SANDBAR_PROJECTS_DIR=str(root))
    return subprocess.run(
        [sys.executable, "-B", CLIENT_PY] + argv,
        cwd=REPO, env=env, timeout=timeout, capture_output=True, text=True)


def _spawn_write(root, payload):
    return _spawn(root, ["concurrency-limit-write", json.dumps(payload)])


def test_spawn_save_and_panel_contract(proj):
    pytest.importorskip("temporalio",
                        reason="client.py imports temporalio at module top; "
                               "run under server/engine/.venv/bin/python")
    root, key = proj
    p = _spawn_write(root, {"project": key, "limit": 5, "by": "host",
                            "source": {}})
    assert p.returncode == 0, p.stdout + p.stderr   # exit contract: 0 = ok
    lines = [l for l in p.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1                          # one line of JSON
    r = json.loads(lines[0])
    # the panel parser contract: top-level boolean saved; saved:true MUST
    # carry the audit_row shape (ts number / by string) plus from/to
    assert r["saved"] is True and r["project"] == key and r["limit"] == 5
    assert isinstance(r["audit_row"]["ts"], (int, float))
    assert r["audit_row"]["by"] == "host"
    assert r["audit_row"]["from"] == 2 and r["audit_row"]["to"] == 5
    # reader agreement: declaration bytes, audit tail, read face all match
    assert json.loads((root / key / cc.DECL_FILE)
                      .read_text(encoding="utf-8")) == {"version": 1, "limit": 5}
    assert r["audit_row"] == {k: _tail_row(root, key)[k]
                              for k in ("ts", "by", "from", "to")}
    env = dict(os.environ, SANDBAR_PROJECTS_DIR=str(root))
    rd = subprocess.run([sys.executable, "-B", TICKET_PY, json.dumps(
        {"op": "concurrency", "project": key, "caller_project": key})],
        cwd=REPO, env=env, timeout=60, capture_output=True, text=True)
    receipt = json.loads(rd.stdout.strip().splitlines()[-1])
    assert receipt["ok"] is True and receipt["result"]["limit"] == 5


def test_spawn_refusal_exit_code_and_bytes(proj):
    pytest.importorskip("temporalio",
                        reason="client.py imports temporalio at module top; "
                               "run under server/engine/.venv/bin/python")
    root, key = proj
    before = _pair_bytes(root, key)
    p = _spawn_write(root, {"project": key, "limit": 11, "by": "host"})
    assert p.returncode != 0                        # refusal exits non-zero
    r = json.loads([l for l in p.stdout.strip().splitlines()
                    if l.strip()][-1])
    assert r["saved"] is False and "Out-of-range" in r["reason"]
    _pair_unchanged(root, key, before)


def test_spawn_malformed_argv_refused(proj):
    pytest.importorskip("temporalio",
                        reason="client.py imports temporalio at module top; "
                               "run under server/engine/.venv/bin/python")
    root, key = proj
    before = _pair_bytes(root, key)
    p = _spawn(root, ["concurrency-limit-write", "{not json"])
    assert p.returncode != 0
    r = json.loads(p.stdout.strip().splitlines()[-1])
    assert r["saved"] is False and "not valid JSON" in r["reason"]
    _pair_unchanged(root, key, before)


def test_unknown_subcommand_refusal_intact(proj):
    """The panel's engine-entry-absent detection matches the unknown-
    subcommand wording - the new branch must not swallow it."""
    pytest.importorskip("temporalio",
                        reason="client.py imports temporalio at module top; "
                               "run under server/engine/.venv/bin/python")
    p = _spawn(proj[0], ["no-such-subcommand", "{}"])
    # the CJK wording below is engine DATA (the panel matches it via unicode
    # escapes in concurrency.ts ABSENT_ENTRY_RE), written escaped here to keep
    # new copy faces English per the 261004 writing standard
    cjk_unknown = "\u672a\u77e5\u5b50\u547d\u4ee4"
    assert cjk_unknown in p.stdout   # unknown-subcommand refusal, not swallowed


def test_usage_names_the_entry(proj):
    p = _spawn(proj[0], ["--help"])
    assert "concurrency-limit-write" in p.stdout


# ---------- admin.log trail (KI-067 review comment) ----------

def test_attempt_lands_admin_log_even_on_refusal(proj):
    """The raw-receipt entry cannot use _emit, so the shell logs through
    audit.audit_call itself: attempt AND refusal both land a row (KI-067)."""
    pytest.importorskip("temporalio",
                        reason="client.py imports temporalio at module top; "
                               "run under server/engine/.venv/bin/python")
    root, key = proj
    admin_log = root / "_admin.log"
    env = dict(os.environ, SANDBAR_PROJECTS_DIR=str(root),
               SANDBAR_ADMIN_LOG=str(admin_log))
    p = subprocess.run(
        [sys.executable, "-B", CLIENT_PY, "concurrency-limit-write",
         json.dumps({"project": key, "limit": 11, "by": "host"})],
        cwd=REPO, env=env, timeout=60, capture_output=True, text=True)
    assert p.returncode != 0
    text = admin_log.read_text(encoding="utf-8")
    assert "concurrency-limit-write" in text
    row = json.loads([l for l in text.strip().splitlines() if l.strip()][-1])
    assert row["sub"] == "concurrency-limit-write" and row["ok"] is False


# ---------- declaration path family sanity ----------

def test_declaration_path_under_perkey_root(proj):
    root, key = proj
    assert cc.declaration_path(key) == os.path.join(str(root), key, cc.DECL_FILE)
    assert cc.audit_path(key).endswith(cc.AUDIT_FILE)
