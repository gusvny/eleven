#!/usr/bin/env python3
"""t261011-25: the line round's receipt tells prelude cost from scenario cost.

Ticket t261011-25 part 2 (host order 261011: "put a number on the round's
prelude"). Grey-box L2, offline seconds, zero docker/Temporal/browser/ports,
never touches 3099. The real run-record write path (run_scenarios
write_run_record -> build_run_header) is driven over a temp
SANDBAR_SCENARIO_LEDGER_DIR; the evidence is read back from the READER side
(scenario_ledger.read_runs + line_round_runner.read_header — the same relay
the line round's one stdout JSON uses), never from the writer's receipt.

Faces:
- A  a measured prelude lands on the header as an additive number (>= 0,
      bool-excluded) and the relay carries it verbatim;
- B  an unmeasured round keeps the key ABSENT (honest missing, never a fake
     0) and legacy headers still validate and relay unchanged;
- C  a malformed prelude_s (negative / bool / non-number) is refused BY NAME,
     both files untouched.

Pre-landing red is the expected TDD signal (the prelude receipt is not built
yet); green required at the integration gate / merge. Git missing (commit
sha unresolvable) = ENV_FAIL exit 2.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def bail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def main():
    for p in ("integration/run_scenarios.py", "integration/scenario_ledger.py",
              "integration/line_round_runner.py"):
        if not os.path.isfile(os.path.join(ROOT, p)):
            env_fail("suite asset missing: %s" % p)
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=30)
        if head.returncode != 0 or not head.stdout.strip():
            env_fail("commit sha unresolvable: %s" % head.stderr.strip()[:200])
    except FileNotFoundError:
        env_fail("git absent")
    commit = head.stdout.strip()
    env_fp = hashlib.sha256(b"t261011-25-scenario-env").hexdigest()

    os.environ["SANDBAR_TICKET_ID"] = "t261011-25"
    # Environment isolation (arbitrate gen0 fix, gate red t261011-25-prelude-
    # receipt): the GATE sets SANDBAR_INTEG_LEDGER_OWNER=gate in the scenario's
    # inherited env, and write_run_record then honestly refuses to write (the
    # gate owns the round's record). This scenario drives the executor-side
    # write path DIRECTLY over its own temp ledger, so the gate-owned
    # suppression must not leak in: pop the owner key for the scenario's own
    # process (restored below — the gate's env outside this process is never
    # touched). This is fixture isolation, not an assertion change.
    _saved_owner = os.environ.pop("SANDBAR_INTEG_LEDGER_OWNER", None)

    def _restore_owner():
        if _saved_owner is not None:
            os.environ["SANDBAR_INTEG_LEDGER_OWNER"] = _saved_owner
    import atexit
    atexit.register(_restore_owner)
    sys.path.insert(0, os.path.join(ROOT, "integration"))
    try:
        import run_scenarios
        import scenario_ledger
        import line_round_runner
    except Exception as e:  # noqa: BLE001
        env_fail("suite modules unimportable: %r" % e)

    counts = {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0}
    spec = [{"name": "sc_t261011_25_prelude_receipt_fixture_a", "suite": "main",
             "status": "pass", "dur_s": 1.0},
            {"name": "sc_t261011_25_prelude_receipt_fixture_b", "suite": "main",
             "status": "pass", "dur_s": 1.0}]

    with tempfile.TemporaryDirectory(prefix="t26101125-prelude-") as tmp:
        os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = tmp
        started = 1_700_000_000_000

        # ---- A: measured prelude lands on the header and relays verbatim ----
        try:
            run_id, face = run_scenarios.write_run_record(
                spec, counts, 30.0, started, commit, env_fp, 1, "",
                False, prelude_s=12.3)
        except TypeError as e:
            bail("prelude receipt not landed (write_run_record has no "
                 "prelude_s seam): %s" % e)
        except Exception as e:  # noqa: BLE001
            bail("run-record write raised: %r" % e)
        if not run_id:
            bail("run record not written (face=%s)" % json.dumps(face)[:300])
        headers, bad = scenario_ledger.read_runs(
            path=os.path.join(tmp, "scenario-runs.jsonl"))
        if bad:
            bail("ledger reports bad headers: %s" % bad)
        hdr = next((h for h in headers if h.get("id") == run_id), None)
        if hdr is None:
            bail("header missing for run %s" % run_id)
        pv = hdr.get("prelude_s")
        if not isinstance(pv, (int, float)) or isinstance(pv, bool) or pv < 0:
            bail("header prelude_s not a nonnegative number: %r" % (pv,))
        # reader-side relay: the same call the line round runner makes
        relayed, why = line_round_runner.read_header(
            ROOT, tmp, {"run_id": run_id})
        if relayed is None:
            bail("relay lost the header: %s" % why)
        if relayed.get("prelude_s") != pv:
            bail("relay does not carry prelude_s verbatim: %r vs %r"
                 % (relayed.get("prelude_s"), pv))

        # ---- B: unmeasured round keeps the key absent; legacy still reads ----
        run_id2, face2 = run_scenarios.write_run_record(
            spec, counts, 30.0, started, commit, env_fp, 1, "", False)
        if not run_id2:
            bail("legacy-shape run record not written (face=%s)"
                 % json.dumps(face2)[:300])
        headers2, _ = scenario_ledger.read_runs(
            path=os.path.join(tmp, "scenario-runs.jsonl"))
        hdr2 = next((h for h in headers2 if h.get("id") == run_id2), None)
        if hdr2 is None:
            bail("legacy header missing for run %s" % run_id2)
        if "prelude_s" in hdr2:
            bail("unmeasured round carries a prelude_s (%r) — a fake number "
                 "on an unmeasured path" % (hdr2["prelude_s"],))
        relayed2, why2 = line_round_runner.read_header(
            ROOT, tmp, {"run_id": run_id2})
        if relayed2 is None:
            bail("relay lost the legacy header: %s" % why2)

        # ---- C: malformed prelude_s refused by name, files untouched ----
        before = open(os.path.join(tmp, "scenario-runs.jsonl"), "rb").read()
        for bad_val in (-1.0, True, "fast"):
            bad_hdr = dict(hdr)
            bad_hdr["prelude_s"] = bad_val
            clean, why3 = scenario_ledger.validate_run_header(bad_hdr)
            if clean is not None:
                bail("malformed prelude_s %r accepted" % (bad_val,))
            if "prelude" not in str(why3):
                bail("refusal does not name the prelude check: %s" % why3)
        after = open(os.path.join(tmp, "scenario-runs.jsonl"), "rb").read()
        if after != before:
            bail("refused headers were written to the ledger")

    print("PASS: prelude receipt contract holds (A measured+relaid, "
          "B absent-when-unmeasured, C malformed refused by name)")
    sys.exit(0)


if __name__ == "__main__":
    main()
