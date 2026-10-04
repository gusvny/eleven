#!/usr/bin/env python3
"""sc_activity_ledger_root — the delivery ACTIVITY lands rows in the INSTANCE
projects root, and the receipt itself exposes mis-location (t261004-43,
gray-box L2, offline seconds, zero docker/Temporal service).

Incident (261004 23:41, live): workflow executor-delivery-sandbar-09380406eb72585b
returned ok:true with result.file = '.sandbar/projects/sandbar/requests.jsonl' —
a RELATIVE path — and the row physically landed at server/engine/.sandbar/…
instead of the instance projects root the host panel reads. Root cause: the
activity shell never forwarded the executing process env, so the ledger root
resolved against an empty env and came out relative to the worker cwd. Every
unit test injected env explicitly; the live call line had zero coverage
(paper-green / production-red).

User-perceivable contract locked here (anchor the promise, not the internals):

  E1 incident replay — with the executing process env shaped like the real
     worker's (HOME set to a temp instance, no projects-root override keys),
     a delivery through the REAL activity shell lands its row under
     $HOME/.sandbar/projects/<key>/requests.jsonl, the receipt is ok, and
     result.file is an ABSOLUTE path equal to that file. A relative
     result.file, or a row outside the instance root, is a FAIL — the exact
     production-red signature this ticket closes.
  E2 non-default instance — with DSH_HOME pointed at a temp instance, the row
     lands under <DSH_HOME>/sandbar/projects (NEVER a $HOME fallback): the
     temporary-instance discipline (t261003-04) must survive the env
     forwarding.
  E3 the failure is visible IN the receipt — driving the module's public
     delivery seam with an env carrying NO ledger-location keys (the pre-fix
     shape) produces a receipt whose result.file does NOT point into the
     instance projects root (it resolves against the cwd-relative root;
     relative before any receipt absolutization); the tripwire (receipt must
     be absolute AND under the instance root) flags it. If this case ever
     goes green, the seam stopped being able to reproduce the incident — the
     tripwire is dead and E1 is carrying the whole guard alone.
  E4 identity discipline unchanged under the forwarded env — with the
     executing process env poisoned with decoy identity keys
     (DSH_SESSION_ID / SANDBAR_CALLER_PROJECT / identity-src surfaces), a row
     delivered through the activity shell is attributed ONLY to the payload
     identity block, and no decoy value appears anywhere in the row or the
     receipt. Forwarding the env must move WHERE a row lands, never WHO
     raised it.

Gray-box anchoring: the activity shell is entered through its public activity
entry (asyncio.run over the registered activity callable in a subprocess with
the engine's temporalio stack); assertions land only on the printed receipt
JSON and the ledger/declaration files on disk. No venv with the stack =
ENV_FAIL (exit 2), never SKIP. Stdlib-only; tmp via TemporaryDirectory.

Intent split: the delivery contract a sandboxed executor experiences
(refusals, identity survival via the injected-env seam, idempotency) is
t261004-27's entry; THIS entry owns the env-forwarding face — where the row
lands and whether the receipt betrays a mis-location — the exact line that
had zero coverage at incident time. Malformed-input truth tables stay with
t261004-23/t261004-27; developer L1 owns the unit matrix on the fixed line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = ROOT / "server/engine"

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


def pick_stack_python():
    """The activity shell needs the temporalio stack, which lives in the
    engine venv (t260907-10 moved the engine to server/engine; this new file
    adds NO legacy-layout path — the old-layout fallback leg is retired with
    the engine-venv-compat removal ticket). None = ENV_FAIL, honestly red."""
    venv = ROOT / "server/engine/.venv/bin/python"
    return str(venv) if venv.exists() else None


KEY = "t26100443fixture"
SESSION = "t261004-43-executor-session"
DECOYS = {
    "DSH_SESSION_ID": "engine-worker-decoy-session",
    "DSH_HEADLESS_SESSION": "engine-worker-decoy-headless",
    "SANDBAR_CALLER_PROJECT": "decoy-caller-project",
    "SANDBAR_CALLER_IDENTITY_SRC": "decoy-src",
    "SANDBAR_CALLER_SURFACE": "decoy-surface",
}
BODY = {
    "kind": "approval",
    "question": "Can ticket T-43 merge now?",
    "detail": "activity ledger-root probe",
    "options": ["merge now", "hold one round"],
    "default_action": "hold",
    "expires_at": None,
}


def payload_for(key=KEY, session=SESSION):
    return {"face": "request", "key": key,
            "identity": {"project": key, "session": session,
                         "channel": "env", "identity_src": "env"},
            "body": dict(BODY)}


PROBE = r'''
import asyncio, json, os, sys
sys.path.insert(0, sys.argv[1])
import executor_delivery as ed
payload = json.loads(sys.argv[2])
receipt = asyncio.run(ed.delivery_activity(payload))
print("RECEIVE:" + json.dumps(receipt, ensure_ascii=False, default=str))
'''


def worker_env(home=None, dsh_home=None, poison=False, extra=None):
    """The executing process env, shaped like a real engine worker: caller
    identity keys ABSENT by default (poison=True plants decoys — E4's
    observation surface), ledger-location keys exactly as configured."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SANDBAR_PANEL_DIR", "SANDBAR_PROJECTS_DIR",
                        "DSH_HOME", "HOME", "DSH_SESSION_ID",
                        "DSH_HEADLESS_SESSION", "SANDBAR_CALLER_PROJECT",
                        "SANDBAR_CALLER_IDENTITY_SRC", "SANDBAR_CALLER_SURFACE")}
    if home is not None:
        env["HOME"] = str(home)
    if dsh_home is not None:
        env["DSH_HOME"] = str(dsh_home)
    if poison:
        env.update(DECOYS)
    if extra:
        env.update(extra)
    return env


def run_activity(stack_py, payload, env, cwd, probe_dir):
    """Run the REAL activity shell in a subprocess whose env is the executing
    env (the activity must read its own process env — that is the contract
    under test). cwd is deliberately the repo root: a cwd-relative ledger root
    is the mis-location this ticket closes, and the stray-root check in E1
    needs it. The probe script itself lives in the tmp dir (zero worktree
    residue). Returns (receipt, raw)."""
    probe = Path(probe_dir) / "_probe_activity.py"
    probe.write_text(PROBE, "utf-8")
    try:
        proc = subprocess.run([stack_py, str(probe), str(ENGINE_DIR),
                               json.dumps(payload)],
                              capture_output=True, text=True, timeout=60,
                              env=env, cwd=str(cwd))
    finally:
        probe.unlink(missing_ok=True)
    raw = (proc.stdout or "") + (proc.stderr or "")
    doc = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RECEIVE:"):
            try:
                doc = json.loads(line[len("RECEIVE:"):])
            except Exception:
                doc = None
    return doc, raw


def ledger_rows(root, key):
    p = Path(root) / key / "requests.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]


def instance_root_default(home):
    return Path(home) / ".sandbar" / "projects"


def instance_root_custom(dsh_home):
    return Path(dsh_home) / "sandbar" / "projects"


def plant_declaration(root, key, session):
    d = Path(root) / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "executor-grants.json").write_text(
        json.dumps({"version": 1, "grants": {}, "executor_sessions": [session]}),
        "utf-8")


PROBE_SEAM = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
import executor_delivery as ed
payload = json.loads(sys.argv[2])
receipt = ed.perform_delivery(payload, 1700000000000, env=json.loads(sys.argv[3]))
print("RECEIVE:" + json.dumps(receipt, ensure_ascii=False, default=str))
'''


def run_seam(stack_py, payload, env_map, cwd, home=None):
    """Drive the module's PUBLIC delivery seam (the declared env parameter —
    the injected-env contract t261004-27 already anchors) in a subprocess
    whose cwd is a tmp dir, so the cwd-relative root the pre-fix shape
    resolves to is real, plantable, and leaves zero worktree residue. The
    declaration load reads the REAL process env (perkey_projects_root), so
    the subprocess HOME is pointed at a temp instance to keep the fixture
    self-contained and zero-touch on the real home."""
    probe = Path(cwd) / "_probe_seam.py"
    probe.write_text(PROBE_SEAM, "utf-8")
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
        for k in ("SANDBAR_PROJECTS_DIR", "SANDBAR_PANEL_DIR"):
            env.pop(k, None)
    try:
        proc = subprocess.run([stack_py, str(probe), str(ENGINE_DIR),
                               json.dumps(payload), json.dumps(env_map)],
                              capture_output=True, text=True, timeout=60,
                              cwd=str(cwd), env=env)
    finally:
        probe.unlink(missing_ok=True)
    doc = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RECEIVE:"):
            try:
                doc = json.loads(line[len("RECEIVE:"):])
            except Exception:
                doc = None
    return doc, (proc.stdout or "") + (proc.stderr or "")


def receipt_triwire(receipt, expected_file):
    """The mis-location tripwire: an ok receipt must name the expected ledger
    file with an ABSOLUTE path; anything else (relative, wrong root) = red."""
    if not isinstance(receipt, dict) or receipt.get("ok") is not True:
        return False, "receipt not ok"
    f = (receipt.get("result") or {}).get("file")
    if not isinstance(f, str) or not f:
        return False, "receipt carries no result.file"
    if not os.path.isabs(f):
        return False, "result.file is RELATIVE (%s) — the incident signature" % f
    if Path(f) != Path(expected_file):
        return False, "result.file %s != expected %s" % (f, expected_file)
    return True, ""


def main():
    section("F engine stack present")
    stack_py = pick_stack_python()
    if stack_py is None:
        print("  ENV_FAIL: no engine venv python with the temporalio stack "
              "(server/engine/.venv) — the activity shell cannot be entered; "
              "nothing is asserted")
        print("\nENV_FAIL %d/%d" % (PASS, PASS + FAIL))
        return 2
    ok(True, "engine stack python found (%s)" % stack_py)
    ok((ENGINE_DIR / "executor_delivery.py").exists(),
       "server/engine/executor_delivery.py exists")

    cwd = str(ROOT)  # NOT server/engine: a cwd-relative root must never receive the row
    with tempfile.TemporaryDirectory(prefix="sc-t261004-43-") as tmp:
        # ---------- E1 incident replay through the real activity shell ----------
        section("E1 incident replay: activity lands the row in the instance projects root, receipt absolute")
        home = Path(tmp) / "home"
        root1 = instance_root_default(home)
        plant_declaration(root1, KEY, SESSION)
        env1 = worker_env(home=home, poison=True)
        doc1, raw1 = run_activity(stack_py, payload_for(), env1, cwd, tmp)
        expected1 = root1 / KEY / "requests.jsonl"
        trip, why = receipt_triwire(doc1, expected1)
        ok(trip, "receipt ok + result.file ABSOLUTE and equal to the instance-root ledger file (%s)"
           % (why or expected1))
        rows = ledger_rows(root1, KEY)
        ok(len(rows) == 1, "exactly one row physically at $HOME/.sandbar/projects/%s/requests.jsonl (found %d)"
           % (KEY, len(rows)))
        ok(bool(rows) and rows[0].get("raised_by") == SESSION,
           "row attributed to the payload session (%s)" % (rows[0].get("raised_by") if rows else "no row"))
        ok(bool(rows) and rows[0].get("surface") == "engine",
           "row carries surface=engine (engine-process delivery)")
        stray = ledger_rows(str(Path(cwd) / ".sandbar" / "projects"), KEY)
        ok(len(stray) == 0,
           "no row in the cwd-relative root (%s/.sandbar/projects) — the mis-location never recurs silently"
           % cwd)
        if not trip:
            print("  [evidence] raw probe output tail: %s" % raw1[-400:])

        # ---------- E2 non-default instance: DSH_HOME, never a $HOME fallback ----------
        section("E2 non-default instance: DSH_HOME decides, never a $HOME fallback")
        dsh_home = Path(tmp) / "dsh-instance"
        root2 = instance_root_custom(dsh_home)
        plant_declaration(root2, KEY, SESSION)
        env2 = worker_env(home=home, dsh_home=dsh_home)
        doc2, raw2 = run_activity(stack_py, payload_for(), env2, cwd, tmp)
        expected2 = root2 / KEY / "requests.jsonl"
        trip2, why2 = receipt_triwire(doc2, expected2)
        ok(trip2, "non-default instance: receipt file absolute under <DSH_HOME>/sandbar/projects (%s)"
           % (why2 or expected2))
        ok(len(ledger_rows(root2, KEY)) == 1,
           "row physically under <DSH_HOME>/sandbar/projects (temporary-instance discipline holds)")
        ok(len(ledger_rows(root1, KEY)) == 1,
           "the $HOME instance is untouched by the DSH_HOME delivery (no double write)")
        if not trip2:
            print("  [evidence] raw probe output tail: %s" % raw2[-400:])

        # ---------- E3 the pre-fix shape must stay reproducible and flaggable ----------
        section("E3 tripwire liveness: an env with no ledger-location keys yields a receipt OUTSIDE the instance root, which the tripwire flags")
        rel_root = Path(tmp) / "prefix-cwd" / ".sandbar" / "projects"
        decl_home = Path(tmp) / "prefix-home"
        plant_declaration(decl_home / ".sandbar" / "projects", KEY, SESSION)
        seam_cwd = str(Path(tmp) / "prefix-cwd")
        os.makedirs(seam_cwd, exist_ok=True)
        doc3, raw3 = run_seam(stack_py, payload_for(), {}, seam_cwd, home=decl_home)
        f = (doc3.get("result") or {}).get("file") if isinstance(doc3, dict) else None
        ok(isinstance(doc3, dict) and doc3.get("ok") is True,
           "pre-fix shape (env with NO location keys) still deliverable through the public seam (%s)"
           % ("" if doc3 and doc3.get("ok") else json.dumps(doc3, ensure_ascii=False)[:160] if doc3 else raw3[-200:]))
        under_instance = bool(f) and str(Path(f).resolve()).startswith(
            str((decl_home / ".sandbar" / "projects").resolve()))
        ok(isinstance(f, str) and f and not under_instance,
           "with NO location keys the receipt does NOT point into the instance projects root "
           "— the mis-location is visible in the receipt itself (file=%r)" % (f,))
        t, w = receipt_triwire(doc3, decl_home / ".sandbar" / "projects" / KEY / "requests.jsonl")
        ok(not t, "the tripwire FLAGS the mis-located receipt (red reason: %s)" % w)
        ok(len(ledger_rows(rel_root, KEY)) == 1,
           "the pre-fix row lands in the cwd-relative root — exactly the production-red shape this ticket closes")

        # ---------- E4 identity discipline under the forwarded env ----------
        section("E4 forwarded env moves WHERE the row lands, never WHO raised it")
        if isinstance(doc1, dict) and doc1.get("ok") is True:
            blob1 = json.dumps(doc1, ensure_ascii=False)
            rows1 = ledger_rows(root1, KEY)
            row_blob = json.dumps(rows1, ensure_ascii=False) if rows1 else ""
            ok(all(d not in blob1 for d in DECOYS.values()),
               "no decoy identity value appears in the receipt")
            ok(all(d not in row_blob for d in DECOYS.values()),
               "no decoy identity value appears in the row")
            ok(bool(rows1) and rows1[0].get("raised_by") == SESSION,
               "raised_by comes only from the payload identity block")
            ok(bool(rows1) and rows1[0].get("delivered_via") == "engine-process",
               "row keeps the engine-process delivery stamp")
        else:
            ok(False, "E1 receipt usable for identity checks (E1 must be green here)")

    print("\n%s %d/%d" % ("FAIL" if FAIL else "PASS", PASS, PASS + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
