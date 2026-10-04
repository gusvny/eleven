#!/usr/bin/env python3
"""sc_engine_request_filing — the executor files a request through the engine, and
nobody else can (t261004-23, gray-box L2, offline seconds, zero docker/Temporal).

User-perceivable contract (host decision 261004, option 1): after the panel write
gate closes POST /api/requests to non-console callers (KI-181 chain), the executor
still has a way to raise a request — an engine-side entry point — and that entry
point is truthful about who filed and refuses everything else:

  T1 real filing: an executor-channel caller (declared session) files a valid
     request; the row lands in <projects_root>/<key>/requests.jsonl with
     raised_by = the resolved session id and an explicit engine source marker
     (surface: "engine"); the row carries the ledger shape (kind, question,
     detail, options, default_action, expires_at).
  T2 identity truthfulness: a caller whose session is not declared for the
     project, and a caller with no session at all, are refused with a named
     reason and the ledger stays untouched (no anonymous filing).
  T3 named refusals (write-side half of the 261003 redesign §8 contract):
     empty question; question over the card limit (60 chars); options that are
     not 2–4 short labels (one item / five items / a non-string item); missing
     default_action when there are no options; a body that is not the expected
     shape (non-object JSON / non-JSON argv). Every refusal names the failed
     field and writes nothing.

Gray-box anchoring: CLI exit code, printed JSON, and ledger file content only.
No internal function names, no line numbers, no execution order. The module
missing = FAIL with the name (TDD-phase red expected; arbitrate/merge green).

Stdlib-only, tmp via TemporaryDirectory (reclaimed by context manager).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "server/engine/executor_requests.py"
PY = sys.executable or "python3"

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(t):
    print("\n%s" % t)


def run_cli(args, env_extra, cwd):
    env = dict(os.environ)
    # The engine spawn chain injects the lane-agent identity (SANDBAR_CALLER_SURFACE
    # etc.); the scenario drives its own caller identity, so strip those first.
    for k in ("DSH_SESSION_ID", "DSH_HEADLESS_SESSION",
              "SANDBAR_CALLER_SURFACE", "SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC"):
        env.pop(k, None)
    env.update(env_extra)
    return subprocess.run(
        [PY, str(CLI), json.dumps(args)] if args is not None else [PY, str(CLI)],
        capture_output=True, text=True, env=env, cwd=str(cwd), timeout=60)


def ledger_rows(root, key):
    p = Path(root) / key / "requests.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]


def refusal_text(proc):
    return (proc.stdout or "") + (proc.stderr or "")


def field_named(text, field):
    """The refusal names the failed field: either a structured `field` key or the
    field name inside the human-facing error. Tolerant to both landed shapes."""
    try:
        doc = json.loads(text.strip().splitlines()[-1])
    except Exception:
        doc = None
    if isinstance(doc, dict):
        if str(doc.get("field", "")) == field or doc.get("ok") is False and field in json.dumps(doc):
            return True
    return field in text


KEY = "t26100423fixture"
SESSION = "t261004-23-executor-session"

if not CLI.exists():
    section("F engine entry module present")
    ok(False, "server/engine/executor_requests.py exists (module missing = FAIL named)")
    print("\nFAIL %d/%d" % (PASS, PASS + FAIL))
    sys.exit(1)

with tempfile.TemporaryDirectory(prefix="sc-t261004-23-") as tmp:
    root = str(Path(tmp) / "projects")
    # Fixture: the host names the executor session in the project's grants
    # declaration (the sanctioned identity source), pinned into the temp root.
    decl_dir = Path(root) / KEY
    decl_dir.mkdir(parents=True)
    (decl_dir / "executor-grants.json").write_text(json.dumps(
        {"version": 1, "grants": {}, "executor_sessions": [SESSION]}), "utf-8")
    # ---------- T1 real filing ----------
    section("T1 执行器通道实发：行落账、raised_by=解析出的会话、surface=engine")
    env_ok = {
        "SANDBAR_PANEL_DIR": root,
        "SANDBAR_PROJECTS_DIR": root,
        "SANDBAR_CALLER_PROJECT": KEY,
        "DSH_SESSION_ID": SESSION,
    }
    body = {
        "kind": "approval",
        "question": "Can ticket T-9 merge now?",
        "detail": "engine test suite green",
        "options": ["merge now", "hold one round"],
        "default_action": "hold",
        "expires_at": None,
    }
    proc = run_cli(body, env_ok, ROOT)
    ok(proc.returncode == 0, "executor-channel filing exits 0 (rc=%s, err=%s)" % (proc.returncode, (proc.stderr or "")[-160:]))
    rows = ledger_rows(root, KEY)
    ok(len(rows) == 1, "exactly one row appended (got %d)" % len(rows))
    if rows:
        row = rows[0]
        ok(row.get("raised_by") == SESSION, "raised_by = resolved executor session (%r)" % row.get("raised_by"))
        ok(row.get("surface") == "engine", "explicit source marker surface=engine (%r)" % row.get("surface"))
        for f in ("kind", "question", "detail", "options", "default_action", "expires_at"):
            ok(f in row, "row carries ledger field %s" % f)
        ok(row.get("question") == body["question"], "question text lands verbatim")

    # ---------- T2 identity truthfulness ----------
    section("T2 身份不可匿名：未声明会话/无会话拒绝且账本零写入")
    proc = run_cli(body, {"SANDBAR_PANEL_DIR": root, "SANDBAR_CALLER_PROJECT": KEY,
                          "DSH_SESSION_ID": "some-other-undeclared-session"}, ROOT)
    ok(proc.returncode != 0, "undeclared session refused (rc=%s)" % proc.returncode)
    ok(len(ledger_rows(root, KEY)) == 1, "refused filing writes nothing (rows still 1)")
    proc = run_cli(body, {"SANDBAR_PANEL_DIR": root, "SANDBAR_CALLER_PROJECT": KEY}, ROOT)
    ok(proc.returncode != 0, "caller with no session id refused (rc=%s)" % proc.returncode)
    ok(len(ledger_rows(root, KEY)) == 1, "anonymous filing writes nothing (rows still 1)")

    # ---------- T3 named refusals ----------
    section("T3 契约拒绝面：每个畸形形状拒收且点名失败字段（账本零写入）")
    cases = [
        ("empty question", {"kind": "approval", "question": "   ", "default_action": "hold"}, "question"),
        ("over-long question", {"kind": "approval", "question": "x" * 61, "default_action": "hold"}, "question"),
        ("one option", {"kind": "approval", "question": "q?", "options": ["only"], "default_action": "hold"}, "options"),
        ("five options", {"kind": "approval", "question": "q?", "options": ["a", "b", "c", "d", "e"], "default_action": "hold"}, "options"),
        ("non-string option", {"kind": "approval", "question": "q?", "options": ["a", 7], "default_action": "hold"}, "options"),
        ("missing default_action", {"kind": "approval", "question": "q?"}, "default_action"),
        ("non-object body", ["not", "an", "object"], "body"),
    ]
    for name, bad_body, field in cases:
        proc = run_cli(bad_body, env_ok, ROOT)
        ok(proc.returncode != 0, "%s refused (rc=%s)" % (name, proc.returncode))
        ok(field_named(refusal_text(proc), field), "%s refusal names field %r (out=%s)" % (name, field, refusal_text(proc)[-120:]))
    ok(len(ledger_rows(root, KEY)) == 1, "all refusals wrote nothing (rows still 1)")

    # Adversarial: the caller may not attribute the row to someone else.
    proc = run_cli(dict(body, raised_by="someone-elses-session"), env_ok, ROOT)
    ok(proc.returncode != 0, "raised_by spoof (claimed != resolved session) refused (rc=%s)" % proc.returncode)
    ok(field_named(refusal_text(proc), "raised_by"), "raised_by spoof refusal names field 'raised_by'")
    ok(len(ledger_rows(root, KEY)) == 1, "spoofed filing wrote nothing (rows still 1)")

    # non-JSON argv (drive the CLI with a raw argv, not run_cli's json wrapper)
    env = dict(os.environ)
    env.update(env_ok)
    proc = subprocess.run([PY, str(CLI), "{not json"], capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)
    ok(proc.returncode != 0, "non-JSON argv refused (rc=%s)" % proc.returncode)
    ok(field_named(refusal_text(proc), "body"), "non-JSON argv refusal names field 'body'")

print("\nPASS %d FAIL %d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
