"""Scenario: the watch stays silent on green, and acts EXACTLY ONCE.

Ticket t261019-25 (design: executor-operational-envelope-v1 §1). User-
perceivable contract: a green certification is nothing to act on; a tick
that finds an actionable condition performs exactly ONE action and never a
bundle. Grey-box L3 over the real activity face and real fixture ledgers;
offline seconds; zero docker/Temporal-server/browser; never touches
3099/7233.

Legs:
A GREEN SILENCE - latest certification green, nothing pending: one tick
  writes NOTHING anywhere (delivery ledger, runs file, requests ledger,
  rounds face) - byte-identical snapshots read back from disk.
B EXACTLY-ONE-ACTION - a fixture that satisfies TWO actionable conditions
  at once (an env-only red whose releasing green cert exists, plus a
  stalled/silent face): the tick produces the single higher-precedence
  action and nothing else - exactly one new delivery row, zero requests,
  no ticket seam call.

Pre-implement tree red = the named TDD signal; green required at the
integration gate/merge. Engine tree unimportable = ENV_FAIL exit 2.
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib_watch_fixture as fx

NOW = fx.sl  # noqa: F841 (clarity only)


def main():
    root, env = fx.build_env()
    fx.declare_project(env)

    # ---- Leg A: green silence ----
    commit = fx.hexs(40)
    fx.write_run(env, "run-green-aaaa", ["pass", "pass"], fx.time.time() - 3600,
                 revision=commit)
    green = fx.cert_row_for(
        {"id": "run-green-aaaa", "cases": {"ran": 2, "passed": 2,
                                           "failed": 0, "env_failed": 0}},
        int((fx.time.time() - 3500) * 1000))
    fx.delivery_append(env, [fx.landing_row("t-old", int((fx.time.time() - 7200) * 1000)),
                             green])
    watch_roots = [env["SANDBAR_DELIVERY_LEDGER_DIR"], env["SANDBAR_SCENARIO_LEDGER_DIR"],
                   env["SANDBAR_PANEL_DIR"], env["SANDBAR_LINE_ROUND_FACE_DIR"]]
    before = fx.snapshot(watch_roots)
    fx.tick(env)
    after = fx.snapshot(watch_roots)
    if before != after:
        changed = sorted(set(after) ^ set(before)) or ["bytes-changed"]
        fx.fail("leg A: a green tick wrote to the face: %s" % changed)
    if fx.read_requests(env):
        fx.fail("leg A: a green tick filed a request")
    fx.ok("leg A: green tick wrote nothing (byte-identical, reader side)")

    # ---- Leg B: exactly one action under two conditions ----
    root2, env2 = fx.build_env()
    fx.declare_project(env2)
    t0 = fx.time.time()
    fx.write_run(env2, "run-red-bbbb1", ["env_fail", "env_fail"], t0 - 7200)
    red_hdr = {"id": "run-red-bbbb1",
               "cases": {"ran": 2, "passed": 0, "failed": 0, "env_failed": 2}}
    red = fx.cert_row_for(red_hdr, int((t0 - 7100) * 1000))
    fx.delivery_append(env2, [red] + fx.develop_certify.open_freeze_rows(red))
    fx.write_run(env2, "run-green-bbbb2", ["pass", "pass"], t0 - 3600)
    green2 = fx.cert_row_for(
        {"id": "run-green-bbbb2", "cases": {"ran": 2, "passed": 2,
                                            "failed": 0, "env_failed": 0}},
        int((t0 - 3500) * 1000))
    fx.delivery_append(env2, [green2])
    # second condition: a round that ended with no run row (silent)
    fx.silent_round(env2, "run-silent-bbbb3")

    calls = []
    try:
        import run_watch
        run_watch.start_fix_ticket = lambda *a, **k: calls.append((a, k)) or {"ok": True}
    except ImportError:
        pass  # module absent -> the tick itself will name it

    before2 = fx.snapshot([env2["SANDBAR_PANEL_DIR"]])
    fx.tick(env2)
    rows, _bad = fx.read_delivery(env2)
    new_rows = [r for r in rows if r.get("seq", 0) > 0 and r not in
                [red, green2]]
    changes = fx.freeze_change_rows(rows)
    if len(changes) != 1:
        fx.fail("leg B: expected exactly ONE closure row, got %d" % len(changes))
    if calls:
        fx.fail("leg B: a ticket was opened alongside the closure (%d calls)"
                % len(calls))
    reqs = fx.read_requests(env2)
    if reqs:
        fx.fail("leg B: a request was filed alongside the closure: %r" % (reqs[:1],))
    if before2 != fx.snapshot([env2["SANDBAR_PANEL_DIR"]]):
        fx.fail("leg B: requests face changed under an exactly-one-action tick")
    fx.ok("leg B: two actionable conditions, exactly one action (closure row only)")
    print("SCENARIO PASS: t261019-25-watch-green-silence-one-action")
    return 0


SurfaceMissing_like = fx.SurfaceMissing

if __name__ == "__main__":
    try:
        sys.exit(main())
    except fx.EnvMissing as e:
        print("ENV_FAIL: %s" % e)
        sys.exit(fx.ENV_FAIL)
    except fx.SurfaceMissing as e:
        fx.fail("declared watch surface missing: %s" % e)
