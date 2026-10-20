"""Scenario: run-stalled and run-silent requests - the line stops silently
only for a person who never looks.

Ticket t261019-25 (design: executor-operational-envelope-v1 §1 + review
ruling R2). Contract: pending landings with no round for N hours get a
``run-stalled`` request naming the last round, its verdict and the pending
range - filed ONCE (deduped while open); a round that ended with no run row
is retried once, and only a SECOND silent end becomes a ``run-silent``
request (never a silent accept); a corrupted idempotency state file fails
toward RE-action, never toward silence (R2). Grey-box L3 over the real
activity face and real fixture ledgers; offline seconds; zero docker/
Temporal-server/browser; never touches 3099/7233.

Legs:
A STALLED - old last round + newer landing row -> one ``run-stalled``
  request naming the last run id, its verdict and the landing; a second
  tick files no duplicate.
B SILENT LADDER - a round dir with no run row: first tick -> NO
  run-silent request yet (the retry happens first); second tick over the
  still-silent round -> the ``run-silent`` request exists.
C RECOVERY - the silent round's row APPEARS (header lands): a later tick
  files no run-silent request for it.
D CORRUPT STATE - garbage in ``run_watch_state.json``: the tick still acts
  (request filed / action taken) and never crashes into silence (R2).

Pre-implement tree red = the named TDD signal; green required at the
integration gate/merge. Engine tree unimportable = ENV_FAIL exit 2.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib_watch_fixture as fx


def _fail(msg):
    FAILURES.append(msg)

OLD_S = time.time() - 48 * 3600  # 48h old: beyond any sane N-hours threshold


def green_round_fixture(env, run_id, at_s):
    fx.write_run(env, run_id, ["pass", "pass"], at_s)
    return fx.cert_row_for(
        {"id": run_id, "cases": {"ran": 2, "passed": 2,
                                 "failed": 0, "env_failed": 0}},
        int((at_s + 5) * 1000))


def kinds(env):
    return sorted(r.get("kind") or r.get("question", "")[:0]
                  for r in fx.read_requests(env))


def request_kinds(env):
    return [r.get("kind") for r in fx.read_requests(env)]


FAILURES = []


def chk(cond, msg):
    if not cond:
        FAILURES.append(msg)


def main():
    # ---- Leg A: stalled + dedupe ----
    _, env = fx.build_env()
    fx.declare_project(env)
    green = green_round_fixture(env, "run-last-a1", OLD_S)
    fx.delivery_append(env, [green])
    ldg = fx.landing_row("t-pending-a2", int((OLD_S + 3600) * 1000))
    fx.delivery_append(env, [ldg])
    fx.tick(env)
    reqs = fx.read_requests(env)
    stalled = [r for r in reqs if r.get("kind") == "run-stalled"]
    if len(stalled) == 1:
        blob = json.dumps(stalled[0], ensure_ascii=False, default=str)
        for token in ("run-last-a1", "green", ldg["id"]):
            if token not in blob:
                _fail("leg A: the request does not name %s (row: %s)"
                      % (token, blob[:300]))
    else:
        _fail("leg A: expected exactly one run-stalled request, got %d (%s)"
              % (len(stalled), request_kinds(env)))
    fx.tick(env)
    reqs2 = fx.read_requests(env)
    if len([r for r in reqs2 if r.get("kind") == "run-stalled"]) != 1:
        _fail("leg A: the second tick filed a duplicate run-stalled request")
    fx.ok("leg A: one run-stalled request naming round, verdict and pending "
          "landing; deduped on the next tick")

    # ---- Leg B: silent ladder (retry once, then the request) ----
    _, env = fx.build_env()
    fx.declare_project(env)
    fx.silent_round(env, "run-silent-b1")
    retries = []

    def rec_retry(*a, **k):
        retries.append(str(a))
        return {"ok": True}

    fx.tick_deep(env, retry_round=rec_retry)
    if [r for r in fx.read_requests(env) if r.get("kind") == "run-silent"]:
        _fail("leg B: the FIRST silent end already filed run-silent - the "
                "retry must come first")
    if not retries:
        _fail("leg B: the first silent end did not perform the named retry")
    fx.tick_deep(env, retry_round=rec_retry)
    silent = [r for r in fx.read_requests(env) if r.get("kind") == "run-silent"]
    if len(silent) != 1:
        _fail("leg B: expected one run-silent request after the second "
                "silent end, got %d" % len(silent))
    if "run-silent-b1" not in json.dumps(silent[0], default=str):
        _fail("leg B: the run-silent request does not name the silent round")
    fx.ok("leg B: first silent end = retry, second = one run-silent request")

    # ---- Leg C: recovery - the row appears, no request ----
    _, env = fx.build_env()
    fx.declare_project(env)
    fx.silent_round(env, "run-late-c1")
    fx.tick_deep(env, retry_round=lambda *a, **k: {"ok": True})
    fx.write_run(env, "run-late-c1", ["pass"], time.time() - 60)
    fx.tick_deep(env, retry_round=lambda *a, **k: {"ok": True})
    late = [r for r in fx.read_requests(env)
            if r.get("kind") == "run-silent" and "run-late-c1"
            in json.dumps(r, default=str)]
    if late:
        _fail("leg C: a run-silent request was filed after the row appeared")
    fx.ok("leg C: row appearing after the retry -> no run-silent request")

    # ---- Leg D: corrupt state -> re-action, never silence ----
    _, env = fx.build_env()
    fx.declare_project(env)
    green = green_round_fixture(env, "run-last-d1", OLD_S)
    fx.delivery_append(env, [green])
    fx.delivery_append(env, [fx.landing_row("t-pending-d2",
                                            int((OLD_S + 3600) * 1000))])
    dev = pathlib.Path(env["SANDBAR_PROJECTS_DIR"]) / fx.PROJECT / "data" / "develop"
    dev.mkdir(parents=True, exist_ok=True)
    (dev / "run_watch_state.json").write_text("{not json at all", encoding="utf-8")
    fx.tick(env)
    if not [r for r in fx.read_requests(env) if r.get("kind") == "run-stalled"]:
        _fail("leg D: a corrupt state file silenced the watch - it must "
                "fail toward re-action (R2)")
    fx.ok("leg D: corrupt state file -> the watch still acts")

    if FAILURES:
        for m in FAILURES:
            print("FAIL: %s" % m)
        return 1
    print("SCENARIO PASS: t261019-25-watch-stalled-silent-requests")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except fx.EnvMissing as e:
        print("ENV_FAIL: %s" % e)
        sys.exit(fx.ENV_FAIL)
    except fx.SurfaceMissing as e:
        fx.fail("declared watch surface missing: %s" % e)
