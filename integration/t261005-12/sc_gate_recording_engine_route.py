#!/usr/bin/env python3
"""sc_gate_recording_engine_route.py — t261005-12: the gated-action ledger is
written by the ENGINE process; a sandboxed caller cannot reach it, and the
failure is never silent.

Grey-box L3, offline (no docker, no Temporal, no browser, zero contact with
3099/7233). Drives the engine's public gate funnel `client._executor_grant_gate`
and the production delivery dispatch `executor_delivery` (face table + default
handlers — the engine worker's own `actions-record` entry) against an isolated
SANDBAR_PROJECTS_DIR. The Temporal transport between the two is the only thing
not real here; the full-stack live path (worker + console/worker restart,
t261004-43 dependency) is the arbitrate-stage proof, not this entry.

User-perceivable faces under judgment (ticket requirements 1/2/3):
  A  caller-side: after a gate pass whose engine delivery is UNAVAILABLE, the
     caller process itself writes ZERO rows into the project ledger — the
     pre-fix shape (in-process append) is a named FAIL, not green.
  B  caller-side: the same unavailable delivery leaves the gate VERDICT
     unchanged (fail-open discipline) and the recording state NAMED on the
     gate face (record_note names the failed check; never a fabricated
     "recorded" claim — KI-193 fake-receipt lesson).
  C  engine-side: the captured delivery payload (face actions-record) fed
     through the PRODUCTION delivery dispatch lands ONE row at the documented
     ledger path with the documented fields (op/ticket/decision).
  D  identity discipline: the payload's identity block is the gate's
     ALREADY-RESOLVED identity (the declared session) — the row records that
     session, never a caller-asserted value.
  E  row boundary unchanged (t261004-11): an enforced pass lands a row and a
     delivery payload; an EXEMPT pass lands neither.
  F  reader-visible failure face: when the engine-side append itself fails
     (unwritable ledger directory injected), the engine leaves a machine-
     readable last-failure marker (JSON with at/why/error) next to the ledger,
     and the marker holds the LAST failure only (not an unbounded log).
  G  malformed delivery payload (garbage body to the actions-record face) is
     refused with a named error — never a crash, never a half-row.

Intent split: gate verdict truth tables / cap / epic scoping belong to
t261004-19-open-ticket-epic-gate-verdicts; ledger schema/idem/replay semantics
to t261004-11-ledger-record-and-replay; panel empty-state and malformed-row
reading faces to t261003-10-recent-actions-real-source (the marker's panel
read face to sc_recent_actions_failure_face.mjs, same ticket); cmd_deliver CLI
identity resolution to the developer L1 battery. This entry owns only the
routing contract (engine writes, caller does not) and the named-failure faces.

Three-state discipline (t260904-12): engine venv fallback chain exhausted =
ENV_FAIL exit 2; the routing seam / marker face not landed = FAIL exit 1 with
the face named (TDD-phase red is expected; arbitrate/merge must be green).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "integration"))

from lib_env import env_fail  # noqa: E402

ENGINE_DIR = os.path.join(REPO, "server", "engine")

PY = os.path.join(ENGINE_DIR, ".venv", "bin", "python")
if not os.path.isfile(PY):
    PY = os.path.join(REPO, "server", "dsh", "temporal-poc", ".venv", "bin", "python")  # engine-venv-compat
if not os.path.isfile(PY):
    found = shutil.which("python3")
    if not found:
        env_fail("no python3 available (engine venv fallback chain exhausted)")
    PY = found

KEY = "proj-t26100512"
SESSION = "sess-t26100512-exec-1"
TICKET = "t261005-12"


def inner():
    """The whole battery, inside the engine venv interpreter with an isolated
    projects root. Prints one LEG line per case and a SUMMARY line; exit 0
    only when every leg passed."""
    sys.path.insert(0, ENGINE_DIR)
    os.chdir(ENGINE_DIR)
    root = sys.argv[sys.argv.index("--root") + 1]
    os.environ["SANDBAR_PROJECTS_DIR"] = root
    os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "arg"
    os.environ["DSH_SESSION_ID"] = SESSION
    os.environ.pop("SANDBAR_CALLER_SURFACE", None)

    import asyncio

    import client
    import executor_actions
    import executor_delivery

    # t261005-12: the gate records through the engine, so judging + recording are
    # one async funnel now (asyncio.run at the scenario boundary; faces unchanged).
    legs = []

    def run(coro):
        return asyncio.run(coro)


    def leg(name, ok, reason=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + reason) if reason else ""))

    def ledger_path():
        return os.path.join(root, KEY, "ledger", "executor-actions.jsonl")

    def rows():
        p = ledger_path()
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f.read().splitlines() if l.strip()]

    # Gate precondition (mechanical, not judged): the executor session is DECLARED
    # in the project declaration (grants.sign=true + executor_sessions names the
    # session) so judge("sign") is an enforced pass — the same shape as the live
    # 261005 measurement quoted in the ticket.
    decl_dir = os.path.join(root, KEY)
    os.makedirs(decl_dir, exist_ok=True)
    with open(os.path.join(decl_dir, "executor-grants.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "grants": {"sign": True},
                   "executor_sessions": [SESSION]}, f)

    def gate():
        return run(client._executor_grant_gate({"src": "arg", "value": KEY}, "sign", KEY,
                                               ticket=TICKET))

    def dispatch(payload):
        import time
        return executor_delivery.perform_delivery(payload, int(time.time() * 1000))

    # ---- A + B: gate pass with the engine delivery unavailable ----------------
    # Force the delivery submission unavailable at the seam the plan declares
    # (client._submit_engine_delivery). If no seam exists (pre-implement),
    # recording still runs in-process and A2 must go red — that IS the defect.
    seam_forced = False
    try:
        def _broken(*a, **k):
            raise RuntimeError("scenario-injected: engine delivery unavailable")
        client._submit_engine_delivery = _broken
        seam_forced = True
    except AttributeError:
        pass

    g = gate()
    caller_rows = rows()
    leg("A1-routing-seam-present", seam_forced,
        "" if seam_forced else "client._submit_engine_delivery absent — "
        "gate recording still caller-side (pre-implement red expected)")
    leg("A2-caller-writes-no-row", len(caller_rows) == 0,
        "caller_rows=%d %s" % (len(caller_rows), json.dumps(caller_rows, default=str)[:300]))
    note = json.dumps(g.get("keys", {}), default=str) + "|" + str(g.get("record_note") or "")
    leg("B1-verdict-unchanged", g.get("err") is None, str(g.get("err"))[:200])
    leg("B2-failure-named", "unavailable" in note.lower(),
        "gate face: %s" % note[:300])

    # ---- C + D + E: engine side via the production delivery dispatch ----------
    captured = []
    if seam_forced:
        def _capture(identity, face, body):
            # The production submission builds the envelope key from the
            # identity's project (executor_delivery.delivery_payload); the
            # capture mirrors that so the payload is dispatch-shaped.
            captured.append({"identity": identity, "face": face, "body": body,
                             "key": str((identity or {}).get("project") or "")})
            return {"ok": True}
        client._submit_engine_delivery = _capture
        g2 = gate()
        leg("C1-gate-still-clean-with-working-engine", g2.get("err") is None,
            str(g2.get("err"))[:200])
        payload = captured[0] if captured else None
        leg("C2-payload-captured", payload is not None,
            "captured=%s" % json.dumps(captured, default=str)[:300])
        if payload:
            leg("C3-face-is-actions-record", payload.get("face") == "actions-record",
                "face=%s" % payload.get("face"))
            res = dispatch(payload)
            rws = rows()
            leg("C4-engine-row-lands", len(rws) == 1,
                "rows=%s dispatch=%s" % (json.dumps(rws, default=str)[:300],
                                         json.dumps(res, default=str)[:200]))
            if rws:
                r = rws[0]
                leg("C5-row-fields", r.get("op") == "sign"
                    and r.get("ticket") == TICKET and r.get("decision") == "allowed",
                    json.dumps(r, default=str)[:300])
                # D: identity discipline — the row records the gate-resolved
                # declared session; a caller-asserted name must not appear.
                fake = "sess-CALLER-ASSERTED-not-real"
                payload2 = json.loads(json.dumps(payload, default=str))
                payload2["body"]["session"] = fake
                dispatch(payload2)
                rws2 = rows()
                same = [x for x in rws2 if fake in json.dumps(x)]
                leg("D1-caller-asserted-session-not-recorded", len(same) == 0,
                    "rows=%d forged=%d" % (len(rws2), len(same)))
                leg("D2-declared-session-recorded",
                    any(SESSION in json.dumps(x) for x in rws2),
                    json.dumps(rws2[-1:], default=str)[:300])
            # E: exempt pass produces no delivery payload and no row.
            n_before = len(captured)
            rows_before = len(rows())
            os.environ["SANDBAR_CALLER_SURFACE"] = "lane-agent"
            os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "env"
            ge = run(client._executor_grant_gate({"src": "env", "value": KEY}, "sign", KEY,
                                                 ticket=TICKET))
            os.environ.pop("SANDBAR_CALLER_SURFACE", None)
            os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "arg"
            leg("E1-exempt-no-payload-no-row",
                len(captured) == n_before and len(rows()) == rows_before
                and ge.get("err") is None,
                "captured_delta=%d rows_delta=%d err=%s"
                % (len(captured) - n_before, len(rows()) - rows_before,
                   str(ge.get("err"))[:150]))
        else:
            for n in ("C3-face-is-actions-record", "C4-engine-row-lands",
                      "C5-row-fields", "D1-caller-asserted-session-not-recorded",
                      "D2-declared-session-recorded", "E1-exempt-no-payload-no-row"):
                leg(n, False, "no payload captured (seam present but silent)")
    else:
        for n in ("C1-gate-still-clean-with-working-engine", "C2-payload-captured",
                  "C3-face-is-actions-record", "C4-engine-row-lands", "C5-row-fields",
                  "D1-caller-asserted-session-not-recorded",
                  "D2-declared-session-recorded", "E1-exempt-no-payload-no-row"):
            leg(n, False, "skipped: routing seam absent (pre-implement red)")

    # ---- F: reader-visible last-failure marker (engine side, injected) --------
    ledger_dir = os.path.join(root, KEY, "ledger")
    # The marker lives at the PROJECT ROOT (t261005-12): a failure commonly means
    # the ledger directory itself is unwritable, so the readable face must sit one
    # level up, where the engine can still write and the panel can still read.
    marker_path = os.path.join(root, KEY, "executor-actions.last-failure.json")
    os.chmod(ledger_dir, 0o500)
    ledger_file = os.path.join(ledger_dir, "executor-actions.jsonl")
    # The ledger FILE already exists here (row landed in leg C) — appending to
    # an existing file needs no directory write, so the injection must also
    # strip the file itself to reproduce the sandboxed-caller denial.
    if os.path.exists(ledger_file):
        os.chmod(ledger_file, 0o400)
    try:
        raised = None
        try:
            executor_actions.record_executor_action(KEY, "sign", ticket=TICKET,
                                                    session=SESSION, decision="allowed")
        except Exception as e:
            raised = str(e)
        leg("F1-marker-written", os.path.exists(marker_path),
            "append_raise=%s exists=%s" % (str(raised)[:120], os.path.exists(marker_path)))
        if os.path.exists(marker_path):
            try:
                m = json.load(open(marker_path, encoding="utf-8"))
                leg("F2-marker-fields-readable",
                    all(k in m for k in ("at", "why", "error")),
                    json.dumps(m, default=str)[:250])
                # a second failure keeps exactly one marker (last-failure face)
                executor_actions.record_executor_action(KEY, "sign", ticket=TICKET + "-2",
                                                        session=SESSION, decision="allowed")
                m2 = json.load(open(marker_path, encoding="utf-8"))
                leg("F3-marker-last-only", TICKET + "-2" in json.dumps(m2),
                    json.dumps(m2, default=str)[:250])
            except Exception as e:
                leg("F2-marker-fields-readable", False, "marker unreadable: %r" % e)
                leg("F3-marker-last-only", False, "marker unreadable: %r" % e)
        else:
            leg("F2-marker-fields-readable", False, "marker absent")
            leg("F3-marker-last-only", False, "marker absent")
    finally:
        if os.path.exists(ledger_file):
            os.chmod(ledger_file, 0o600)
        os.chmod(ledger_dir, 0o700)

    # ---- G: malformed payload to the production face --------------------------
    try:
        bad = {"identity": {"src": "arg", "value": KEY}, "face": "actions-record",
               "body": {"op": {"x": 1}, "key": None, "ticket": 5,
                        "verdict": "not-a-dict", "session": [], "channel": None}}
        res = dispatch(bad)
        named = bool(res.get("err") or res.get("refused")
                     or (res.get("ok") is False and res.get("error")))
        leg("G1-malformed-refused-named", named, json.dumps(res, default=str)[:250])
        leg("G2-malformed-no-half-row", len(rows()) in (0, 1, 2),
            "rows=%d" % len(rows()))  # no crash; exact count is C/E's face
    except Exception as e:
        leg("G1-malformed-refused-named", False, "raised: %r" % (e,))
        leg("G2-malformed-no-half-row", False, "raised: %r" % (e,))

    n_fail = legs.count(False)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (legs.count(True), n_fail))
    sys.exit(0 if n_fail == 0 else 1)


def main():
    root = tempfile.mkdtemp(prefix="t26100512-engine-")
    atexit.register(lambda: shutil.rmtree(root, ignore_errors=True))
    proj = os.path.join(root, KEY)
    os.makedirs(os.path.join(proj, "ledger"))
    with open(os.path.join(proj, "executor-grants.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "grants": {"sign": True},
                   "executor_sessions": [SESSION],
                   "updated_by": "scenario", "updated_at": 0}, f)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": os.environ.get("HOME", root)}
    p = subprocess.run([PY, __file__, "--inner", "--root", root],
                       capture_output=True, text=True, timeout=600, env=env)
    sys.stdout.write(p.stdout)
    if p.returncode not in (0, 1):
        env_fail("inner driver rc=%s stderr=%s" % (p.returncode, p.stderr[-400:]))
    if "SUMMARY" not in p.stdout:
        # inner crashed before any SUMMARY — an honest product red with the
        # named cause, never a silent green (t260904-12 three-state).
        print("[FAIL] inner-battery-completed — crashed before SUMMARY; "
              "stderr tail: %s" % p.stderr[-500:])
        print("SUMMARY pass=0 fail=1 env_fail=0 na=0")
        sys.exit(1)
    sys.exit(p.returncode)


if __name__ == "__main__":
    if "--inner" in sys.argv:
        inner()
    else:
        main()
