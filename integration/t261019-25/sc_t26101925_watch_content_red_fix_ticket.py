"""Scenario: a content red opens ONE fix ticket and never a rerun.

Ticket t261019-25 (design: executor-operational-envelope-v1 §1). Contract:
a red with content regressions opens (or REUSES) a fix ticket against the
line naming the regressing cases and the run id; the range only grows - a
rerun for a new answer is forbidden. Grey-box L3 over the real activity
face and real fixture ledgers; the ticket seam is the plan-declared
injectable ``run_watch.start_fix_ticket`` (swapped for a recorder); offline
seconds; zero docker/Temporal-server/browser; never touches 3099/7233.

Legs:
A TICKET NAMES THE GUILT - content red -> exactly one ticket whose payload
  names the run id AND each regressing scenario name AND the evidence row
  id; no closure row anywhere.
B REUSE, NOT DUPLICATE - a second tick over the same unchanged face files
  NO second ticket (reuse-first by run id).
C NEVER A RERUN - across both ticks the runs file and the rounds face are
  byte-identical (no new run header, no round activity) - the watch does
  not answer a red by re-running.

Pre-implement tree red = the named TDD signal; green required at the
integration gate/merge. Engine tree unimportable = ENV_FAIL exit 2.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib_watch_fixture as fx

RUN_ID = "run-content-r1"
REGRESSING = "sc-01"


def content_red_fixture(env, t0):
    fx.write_run(env, RUN_ID, ["pass", "fail"], t0 - 7200)
    hdr = {"id": RUN_ID,
           "cases": {"ran": 2, "passed": 1, "failed": 1, "env_failed": 0}}
    red = fx.cert_row_for(hdr, int((t0 - 7100) * 1000))
    fx.delivery_append(env, [red] + fx.develop_certify.open_freeze_rows(red))
    return red


def main():
    _, env = fx.build_env()
    fx.declare_project(env)
    t0 = fx.time.time()
    red = content_red_fixture(env, t0)
    watch_roots = [env["SANDBAR_SCENARIO_LEDGER_DIR"], env["SANDBAR_LINE_ROUND_FACE_DIR"]]
    before = fx.snapshot(watch_roots)

    calls = []

    rec_tickets = []

    def rec_fix_ticket(*a, **k):
        calls.append({"args": str(a), "kwargs": str(k)})
        tid = "tkt-rec-%d" % (len(calls),)
        rec_tickets.append(tid)
        return {"ok": True, "ticket_id": tid}

    def alive(_project, tid):
        return tid in rec_tickets

    fx.tick_deep(env, start_fix_ticket=rec_fix_ticket, ticket_open=alive)
    rows, _ = fx.read_delivery(env)
    if fx.freeze_change_rows(rows):
        fx.fail("leg A: a closure row was recorded over a CONTENT red")
    if len(calls) != 1:
        fx.fail("leg A: expected exactly one fix ticket, got %d" % len(calls))
    payload = _dumps(calls[0]) if calls else ""
    for token in (RUN_ID, REGRESSING, red["id"]):
        if token not in payload:
            fx.fail("leg A: ticket payload does not name %s (payload: %s)"
                    % (token, payload[:300]))

    fx.tick_deep(env, start_fix_ticket=rec_fix_ticket, ticket_open=alive)
    if len(calls) != 1:
        fx.fail("leg B: the second tick filed another ticket (%d total) - "
                "reuse-first by run id is the contract" % len(calls))
    after = fx.snapshot(watch_roots)
    if before != after:
        fx.fail("leg C: the run face moved across the ticks (rerun class): %s"
                % sorted(set(after) ^ set(before)))
    hdrs, _ = fx.read_run_headers(env)
    if len([h for h in hdrs if h.get("id") == RUN_ID]) != 1:
        fx.fail("leg C: the red run gained headers - a rerun happened")
    fx.ok("A/B/C: one named ticket, reused on the next tick, run face untouched")
    print("SCENARIO PASS: t261019-25-watch-content-red-fix-ticket")
    return 0


def _dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except fx.EnvMissing as e:
        print("ENV_FAIL: %s" % e)
        sys.exit(fx.ENV_FAIL)
    except fx.SurfaceMissing as e:
        fx.fail("declared watch surface missing: %s" % e)
