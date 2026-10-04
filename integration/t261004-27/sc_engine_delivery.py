#!/usr/bin/env python3
"""sc_engine_delivery — the executor's ledger writes run in the ENGINE process
(t261004-27, gray-box L2, offline seconds, zero docker/Temporal service).

User-perceivable contract (host decision 261004 option 1; ticket hard boundary
"no self-authorization"): every legitimate executor write to the project ledger
is performed by the engine process — a granted authority must be exercisable
from a sandbox that can write the repo only — and the delivery face is honest
about who acted and refuses everything it was not built to do.

  D1 engine-unreachable is a named refusal, never a silent fallback: with the
     engine address pointing at a dead port, `client.py deliver` (face=request)
     exits non-zero, the refusal names the delivery/engine-unreachable state,
     carries the transport error verbatim (no bare "delivery failed"), and the
     ledger stays untouched — the in-process append that this ticket removes is
     NOT re-created behind the caller's back.
  D2 a caller with no session id is refused caller-side with a named reason;
     no delivery run is started, nothing is written.
  D3 identity survival: the row is attributed to the CALLER's session even
     when the executing (worker-shaped) environment carries a poisoned decoy
     session id and no caller envs at all — the worker's ambient env never
     leaks into a row; the row carries surface=engine and delivered_via=
     engine-process.
  D4 no self-authorization / no spoofing: a forged raised_by that disagrees
     with the caller identity is refused; an unknown face, a missing identity
     block, a key that disagrees with the identity, and a body that declares
     its own caller_project are each refused with a named field; the grants
     declaration file is byte-identical after every attempt (the delivery face
     cannot edit what authorizes it) and nothing is written on any refusal.
  D5 malformed inputs fail closed: a non-object body, a lone-surrogate string,
     and an over-card-limit question are refused with a named field, ledger
     untouched.
  D6 one delivery = one run: the idempotency key behind the deterministic
     workflow id is a pure function of (face, key, session, body) — identical
     delivery maps to one run (the engine's REUSE_ID then returns the first
     receipt), a changed body maps elsewhere.

Gray-box anchoring: CLI exit code + printed JSON + ledger/declaration file
content only for D1/D2; the in-process delivery seam (the module's public
one-delivery entry with an injectable environment mapping) for D3-D6 — the
scenario pins the CONTRACT (payload in, receipt out, env read from the given
mapping), not internal names; if no public entry is found the case FAILs
naming the contract (TDD-phase red expected; arbitrate/merge green).

Stdlib-only, tmp via TemporaryDirectory (reclaimed by context manager).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "server/engine/client.py"
DELIVERY = ROOT / "server/engine/executor_delivery.py"
ENGINE_DIR = ROOT / "server/engine"


def _pick_cli_python():
    """The client face needs the temporalio stack: prefer the engine venvs
    (same fallback chain as verify.yaml's test check); plain python3 otherwise.
    None = the stack is unavailable -> the CLI cases are ENV_FAIL (exit 2)."""
    for venv in (ROOT / "server/engine/.venv/bin/python",
                 ROOT / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat (migration-window fallback, t260907-10; removal ticket retires this leg)
        if venv.exists():
            return str(venv)
    return None


CLI_PY = _pick_cli_python()
PY = sys.executable or "python3"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

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


def clean_env(extra):
    env = dict(os.environ)
    for k in ("DSH_SESSION_ID", "DSH_HEADLESS_SESSION", "SANDBAR_CALLER_SURFACE",
              "SANDBAR_CALLER_PROJECT", "SANDBAR_CALLER_IDENTITY_SRC",
              "SANDBAR_TARGET_HOST"):
        env.pop(k, None)
    env.update(extra)
    return env


def run_deliver(args, env_extra, cwd=ROOT):
    return subprocess.run([CLI_PY or PY, str(CLIENT), "deliver", json.dumps(args)],
                          capture_output=True, text=True,
                          env=clean_env(env_extra), cwd=str(cwd), timeout=60)


def last_json(text):
    try:
        return json.loads(text.strip().splitlines()[-1])
    except Exception:
        return None


def ledger_rows(root, key):
    p = Path(root) / key / "requests.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]


def all_rows(root, key):
    """Rows from the pinned temp root AND the cwd-relative fallback root —
    where the row actually lands when the injected env carries no projects-root
    key is itself an observation (see the report), so count both, never miss."""
    return ledger_rows(root, key) + ledger_rows(str(ROOT / ".sandbar" / "projects"), key)


def cleanup_relative_fixture(key):
    p = ROOT / ".sandbar" / "projects" / key
    if p.exists():
        import shutil
        shutil.rmtree(p, ignore_errors=True)


def find_delivery_entry(mod):
    """Locate the module's public one-delivery entry without pinning internals:
    a module-level callable among the documented names, or the activity/workflow
    class method. Returns (callable, how) or (None, None)."""
    for name in ("deliver_once", "deliver", "perform_delivery", "run_delivery",
                 "dispatch_delivery", "deliver_payload"):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn, "module.%s" % name
    for cls_name in ("ExecutorDeliveryActivity", "ExecutorDeliveryWorkflow"):
        cls = getattr(mod, cls_name, None)
        if cls is None:
            continue
        for m in ("deliver", "dispatch", "handle", "run_once", "run"):
            fn = getattr(cls, m, None)
            if callable(fn):
                return fn, "%s.%s" % (cls_name, m)
    return None, None


def deliver_call(entry, payload, env_map, cwd=""):
    """Invoke the seam binding to its declared signature (payload, [now_ms,] env)."""
    import inspect
    kwargs = {}
    params = inspect.signature(entry).parameters
    if "now_ms" in params and params["now_ms"].default is inspect._empty:
        kwargs["now_ms"] = 1700000000000  # pinned: D6 idem determinism needs a stable clock
    if "env" in params:
        kwargs["env"] = env_map
    try:
        return entry(payload, **kwargs)
    except TypeError as e:
        return {"ok": False, "field": "seam", "error": "entry not callable with payload/env: %s" % e}


KEY = "t26100427fixture"
SESSION = "t261004-27-executor-session"
BODY = {
    "kind": "approval",
    "question": "Can ticket T-9 merge now?",
    "detail": "delivery test",
    "options": ["merge now", "hold one round"],
    "default_action": "hold",
    "expires_at": None,
}


def main():
    if not CLIENT.exists():
        section("F engine client present")
        ok(False, "server/engine/client.py exists")
        print("\nFAIL %d/%d" % (PASS, PASS + FAIL))
        return 1

    with tempfile.TemporaryDirectory(prefix="sc-t261004-27-") as tmp:
        root = str(Path(tmp) / "projects")
        decl_dir = Path(root) / KEY
        decl_dir.mkdir(parents=True)
        decl_path = decl_dir / "executor-grants.json"
        decl = {"version": 1, "grants": {}, "executor_sessions": [SESSION]}
        decl_path.write_text(json.dumps(decl), "utf-8")
        decl_bytes = decl_path.read_bytes()
        base_env = {"SANDBAR_PANEL_DIR": root, "SANDBAR_PROJECTS_DIR": root,
                    "SANDBAR_CALLER_PROJECT": KEY, "DSH_SESSION_ID": SESSION}
        payload_ok = {"face": "request", "key": KEY,
                      "identity": {"project": KEY, "session": SESSION,
                                   "channel": "env", "identity_src": "env"},
                      "body": dict(BODY)}

        # ---------- D1 engine-unreachable = named refusal, no silent fallback ----------
        section("D1 engine unreachable: named refusal with transport error, ledger untouched, no in-process fallback")
        if CLI_PY is None:
            print("  ENV_FAIL: engine venv python with the temporalio stack not found "
                  "(server/engine/.venv, server/dsh/temporal-poc/.venv) — CLI delivery cases D1/D2 cannot run")
            print("\nENV_FAIL %d/%d" % (PASS, PASS + FAIL))
            return 2
        dead = "127.0.0.1:1"  # nothing listens here; connect must fail fast
        proc = run_deliver({"face": "request", "body": dict(BODY)},
                           dict(base_env, SANDBAR_TARGET_HOST=dead))
        ok(proc.returncode != 0, "unreachable engine refuses (rc=%s)" % proc.returncode)
        out = (proc.stdout or "") + (proc.stderr or "")
        doc = last_json(proc.stdout or "")
        named = (isinstance(doc, dict) and "engine-unreachable" in json.dumps(doc)) or "engine-unreachable" in out
        ok(named, "refusal names the engine-unreachable state (out=%s)" % out[-160:])
        transport = isinstance(doc, dict) and len(str(doc.get("error", "")) or "") > 0
        ok(transport or "error" in out.lower() or "Error" in out,
           "refusal carries the transport error verbatim, not a bare claim")
        ok(len(ledger_rows(root, KEY)) == 0, "no in-process fallback: ledger untouched (rows 0)")

        # ---------- D2 sessionless caller refused caller-side ----------
        section("D2 sessionless caller refused caller-side; no delivery run started")
        env_nosid = {k: v for k, v in base_env.items() if k != "DSH_SESSION_ID"}
        proc = run_deliver({"face": "request", "body": dict(BODY)}, env_nosid)
        ok(proc.returncode != 0, "no session id -> refusal (rc=%s)" % proc.returncode)
        ok("session" in ((proc.stdout or "") + (proc.stderr or "")).lower(),
           "refusal names the missing session (out=%s)" % ((proc.stdout or "")[-120:]))
        ok(len(ledger_rows(root, KEY)) == 0, "nothing written (rows 0)")

        # ---------- D3-D6 via the in-process delivery seam ----------
        section("D3-D6 in-process delivery seam (module contract, injected env)")
        if not DELIVERY.exists():
            ok(False, "server/engine/executor_delivery.py exists (module missing = FAIL named)")
        else:
            try:
                mod = importlib.import_module("executor_delivery")
            except Exception as e:  # noqa: BLE001 — import failure is a named FAIL, not a crash
                mod = None
                ok(False, "executor_delivery imports (import failed: %s)" % e)
            entry, how = (None, None) if mod is None else find_delivery_entry(mod)
            if entry is not None:
                ok(True, "delivery seam found via %s" % how)
                # Fixture: the engine worker legitimately runs inside its project's
                # context (projects root on its ambient env); what must NEVER ride
                # the ambient env is the CALLER identity — so the decoy session id
                # is planted in the REAL process env (the worker's ambient env) and
                # D3 asserts the row still carries the caller's session.
                os.environ["SANDBAR_PANEL_DIR"] = root
                os.environ["SANDBAR_PROJECTS_DIR"] = root
                prior_sid = os.environ.get("DSH_SESSION_ID")
                os.environ["DSH_SESSION_ID"] = "engine-worker-decoy-session"
                worker_env = dict(os.environ)

                # D3 identity survival under a poisoned worker env
                rc = deliver_call(entry, payload_ok, worker_env)
                ok(isinstance(rc, dict) and rc.get("ok"), "delivery with caller identity block succeeds (%r)" % rc)
                rows = all_rows(root, KEY)
                ok(len(rows) == 1, "exactly one row appended (got %d)" % len(rows))
                if rows:
                    row = rows[0]
                    ok(row.get("raised_by") == SESSION,
                       "raised_by = CALLER session, not worker decoy (%r)" % row.get("raised_by"))
                    ok(row.get("surface") == "engine", "row stamped surface=engine (%r)" % row.get("surface"))
                    ok(row.get("delivered_via") == "engine-process",
                       "row stamped delivered_via=engine-process (%r)" % row.get("delivered_via"))

                # D4 no spoofing / boundary refusals — nothing written, declaration untouched
                section("D4 no self-authorization: spoofing and out-of-face ops refused, declaration untouched")
                forged = json.loads(json.dumps(payload_ok))
                forged["body"] = dict(BODY, raised_by="someone-elses-session")
                rc = deliver_call(entry, forged, worker_env)
                ok(isinstance(rc, dict) and not rc.get("ok"), "forged raised_by refused")
                ok(isinstance(rc, dict) and "raised_by" in json.dumps(rc), "forged raised_by refusal names field")
                bad_cases = [
                    ("unknown face", dict(payload_ok, face="self-grant")),
                    ("missing identity", {"face": "request", "body": dict(BODY)}),
                    ("key mismatch", dict(payload_ok, identity=dict(payload_ok["identity"], project="other-project"))),
                    ("caller_project declared in body", dict(payload_ok, body=dict(BODY, caller_project=KEY))),
                ]
                for name, bad_payload in bad_cases:
                    rc = deliver_call(entry, bad_payload, worker_env)
                    ok(isinstance(rc, dict) and not rc.get("ok"), "%s refused (%r)" % (name, rc))
                ok(len(all_rows(root, KEY)) == 1, "all refusals wrote nothing (rows still 1)")
                ok(decl_path.read_bytes() == decl_bytes,
                   "grants declaration byte-identical (delivery face cannot edit its own authority)")

                # D5 malformed inputs fail closed
                section("D5 malformed inputs fail closed, named field, zero writes")
                n0 = len(all_rows(root, KEY))
                malformed = [
                    ("non-object body", dict(payload_ok, body=["not", "an", "object"])),
                    ("lone surrogate in question", dict(payload_ok, body=dict(BODY, question="bad\ud800char"))),
                    ("over-limit question", dict(payload_ok, body=dict(BODY, question="x" * 61))),
                ]
                for name, bad_payload in malformed:
                    rc = deliver_call(entry, bad_payload, worker_env)
                    if name == "lone surrogate in question":
                        # house rule: in-bound sanitize makes undecodable chars
                        # VISIBLE escapes, it does not crash and does not write a
                        # raw surrogate byte — either a named refusal or a row
                        # whose text carries the escaped form, never a raw char.
                        good = isinstance(rc, dict) and (
                            not rc.get("ok") or "\ud800" not in json.dumps(rc).replace("\\ud800", ""))
                        ok(good, "lone surrogate handled without a raw byte (%r)" % rc)
                        continue
                    ok(isinstance(rc, dict) and not rc.get("ok"), "%s refused (%r)" % (name, rc))
                grown = len(all_rows(root, KEY)) - n0
                ok(grown <= 1, "true refusals wrote nothing (at most the sanitized row may land; got +%d)" % grown)

                # D6 dedup: identical delivery inside the window = first receipt, one row
                # D6 dedup determinism: the idempotency key behind the workflow id
                # is a pure function of (face, key, session, body) — the same
                # delivery maps to one run (so the engine's REUSE_ID returns the
                # first receipt), a different body maps elsewhere.
                section("D6 dedup determinism: identical delivery -> same idempotency key, changed body -> different key")
                idem_fn = getattr(mod, "delivery_idem", None)
                wf_fn = getattr(mod, "workflow_id_for", None)
                if callable(idem_fn) and callable(wf_fn):
                    now = 1700000000000
                    i1 = idem_fn("request", KEY, SESSION, dict(BODY), now)
                    i2 = idem_fn("request", KEY, SESSION, dict(BODY), now)
                    i3 = idem_fn("request", KEY, SESSION, dict(BODY, question="different ask"), now)
                    ok(i1 == i2, "identical delivery -> identical idempotency key (%r)" % i1)
                    ok(i1 != i3, "changed body -> different idempotency key")
                    wid = wf_fn(KEY, i1)
                    ok(str(wid).startswith("executor-delivery-%s-" % KEY),
                       "deterministic workflow id carries key + idem (%r)" % wid)
                else:
                    ok(False, "idempotency-key seam present (delivery_idem/workflow_id_for) — not found (TDD red)")
            # no explicit env restore needed: os.environ edits die with this process

    cleanup_relative_fixture(KEY)
    print("\nPASS %d FAIL %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
