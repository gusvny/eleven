"""Scenario: the env-only red release rule and its fail directions.

Ticket t261019-25 (design: executor-operational-envelope-v1 §1 + review
ruling R4). Contract: a red whose new-regression set is environment-only is
not content guilt. The watch (a) records the closure through the engine's
own releasing rule when a green certification after the red exists - one
``closed`` freeze-change row via the engine writer, the certification rows
themselves untouched; (b) opens a fix ticket naming the environment face
and the evidence row when no releasing green exists; (c) NEVER closes over
a content red (mixed red = ticket); (d) classifies env-only only on
PRESENT evidence - missing/torn case rows fail toward "not environment-only"
(the fix ticket), never toward a closure (R4). Grey-box L3, real activity
face over real fixture ledgers; offline seconds; zero docker/Temporal/
browser; never touches 3099/7233.

Pre-implement tree red = the named TDD signal; green required at the
integration gate/merge. Engine tree unimportable = ENV_FAIL exit 2.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib_watch_fixture as fx


def env_red_fixture(env, t0, run_id="run-env-r1", verdicts=("env_fail", "env_fail")):
    fx.write_run(env, run_id, list(verdicts), t0 - 7200)
    hdr = {"id": run_id,
           "cases": {"ran": len(verdicts), "passed": 0, "failed": 0,
                     "env_failed": len(verdicts)}}
    red = fx.cert_row_for(hdr, int((t0 - 7100) * 1000))
    fx.delivery_append(env, [red] + fx.develop_certify.open_freeze_rows(red))
    return red


def main():
    # ---- Leg A: releasing green exists -> exactly one closure row ----
    _, env = fx.build_env()
    fx.declare_project(env)
    t0 = fx.time.time()
    red = env_red_fixture(env, t0)
    fx.write_run(env, "run-env-g2", ["pass", "pass"], t0 - 3600)
    green = fx.cert_row_for(
        {"id": "run-env-g2", "cases": {"ran": 2, "passed": 2,
                                       "failed": 0, "env_failed": 0}},
        int((t0 - 3500) * 1000))
    fx.delivery_append(env, [green])
    rows_before, _ = fx.read_delivery(env)
    fx.tick(env)
    rows, bad = fx.read_delivery(env)
    if bad:
        fx.fail("leg A: ledger read back bad rows: %r" % bad[:1])
    changes = [r for r in fx.freeze_change_rows(rows)
               if r not in fx.freeze_change_rows(rows_before)]
    if len(changes) != 1:
        fx.fail("leg A: expected exactly one new freeze_change row, got %d"
                % len(changes))
    ch = changes[0]
    if ch.get("change") != "closed":
        fx.fail("leg A: the change is not 'closed': %r" % ch.get("change"))
    if ch.get("by") != "run-watch":
        fx.fail("leg A: the closure was not recorded by the watch: %r"
                % ch.get("by"))
    blob = json_dumps(ch)
    # the row acted ON is the red certification: the reader reaches it through
    # the episode (freeze id -> cause), the release cert is named on the row
    episodes = {r.get("id"): r for r in rows
                if r.get("kind") == fx.develop_certify.KIND_FREEZE}
    ep = episodes.get(ch.get("freeze"))
    if ep is None:
        fx.fail("leg A: the closure names an unknown freeze episode")
    elif ep.get("cause") != red["id"]:
        fx.fail("leg A: the episode does not key to the red cert %s (cause=%r)"
                % (red["id"], ep.get("cause")))
    if "run-env-g2" not in blob and "cert" not in blob:
        fx.fail("leg A: the closure does not name the releasing green cert "
                "(reader-side row: %s)" % blob[:200])
    if "run-env-r1" not in blob and ep is None:
        fx.fail("leg A: neither the row nor the episode names the red run")
    rows_now = dict((r.get("id"), r) for r in rows)
    for r in rows_before:
        rid = r.get("id")
        if rid and rows_now.get(rid) != r:
            fx.fail("leg A: an existing record was EDITED (id=%s) - facts are "
                    "append-only" % rid)
    fx.ok("leg A: closure recorded once via the engine writer, certs untouched")

    # ---- Leg B: no releasing green -> fix ticket, never a closure ----
    _, env = fx.build_env()
    fx.declare_project(env)
    red = env_red_fixture(env, fx.time.time())
    calls = []
    fx.tick_deep(env, start_fix_ticket=lambda *a, **k:
                 calls.append({"args": str(a)}) or {"ok": True, "ticket_id": "t-b"})
    rows, _ = fx.read_delivery(env)
    if fx.freeze_change_rows(rows):
        fx.fail("leg B: a closure was recorded without a releasing green cert")
    if not calls:
        fx.fail("leg B: no fix ticket opened for the unreleased env-only red")
    else:
        blob = json_dumps(calls[0])
        if "env" not in blob.lower() or red["id"] not in blob:
            fx.fail("leg B: the ticket does not name the environment face and "
                    "the evidence row: %s" % blob[:300])
    fx.ok("leg B: unreleased env-only red -> fix ticket naming face + evidence row")

    # ---- Leg C: mixed red -> ticket, never closure (C1) ----
    _, env = fx.build_env()
    fx.declare_project(env)
    env_red_fixture(env, fx.time.time(), run_id="run-mix-r3",
                    verdicts=("env_fail", "fail"))
    calls = []
    fx.tick_deep(env, start_fix_ticket=lambda *a, **k:
                 calls.append({"args": str(a)}) or {"ok": True})
    rows, _ = fx.read_delivery(env)
    if fx.freeze_change_rows(rows):
        fx.fail("leg C: a closure was recorded over a red carrying a content "
                "regression")
    if not calls:
        fx.fail("leg C: mixed red produced no fix ticket")
    fx.ok("leg C: mixed red -> fix ticket, never closure")

    # ---- Leg D: torn case rows -> fail toward ticket (R4) ----
    _, env = fx.build_env()
    fx.declare_project(env)
    env_red_fixture(env, fx.time.time(), run_id="run-torn-r4")
    scen = pathlib.Path(env["SANDBAR_SCENARIO_LEDGER_DIR"]) / "scenario-runs.jsonl"
    if scen.is_file():
        with open(str(scen), "a", encoding="utf-8") as fh:
            fh.write('{"v": "run-ledger-v1", "id": "run-torn-r4", "TORN"\n')
    calls = []
    fx.tick_deep(env, start_fix_ticket=lambda *a, **k:
                 calls.append({"args": str(a)}) or {"ok": True})
    rows, _ = fx.read_delivery(env)
    if fx.freeze_change_rows(rows):
        fx.fail("leg D: closure recorded while the red run's case evidence is "
                "torn - env-only must be classified on present evidence only")
    if not calls:
        fx.fail("leg D: torn evidence produced no fix ticket (fail direction R4)")
    fx.ok("leg D: torn case evidence -> not env-only -> fix ticket (R4)")

    print("SCENARIO PASS: t261019-25-watch-env-red-release-rule")
    return 0


def json_dumps(obj):
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
