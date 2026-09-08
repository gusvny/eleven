#!/usr/bin/env python3
"""t260901-19 T3: suggest_next precache short-circuit (activity-level, plan v3).

Contract under test:
- Order inside suggest_next: rfile idempotency -> SANDBAR_SUGGEST_STUB -> precache
  short-circuit -> spawn.
- Short-circuit fires only when args.epic/args.state_key are set, pre.json exists
  AND its state_key matches, and the cached suggestion re-passes the FULL existing
  validation (_parse_suggest_result three-state contract + TEMPLATE whitelist).
  ok form -> ok StageResult; done form -> "可结项" semantics; anything invalid or
  mismatched -> fall through to spawn (never fake-ok, never silent).
- evidence carries "precache-hit"; report wording matches _consume_suggest_result.
- Stub channel wins over the short-circuit (test isolation).
- Test hygiene: synthetic epic codes only; every written pre.json is removed.

Safety: real spawn is impossible here — agent_activities._prepare_agent_spawn is
monkeypatched to a recorder that raises a sentinel, so a buggy short-circuit shows
up as a recorded spawn attempt, never as a real agent process.

Needs temporalio SDK (prefers server/engine/.venv); missing -> ENV_FAIL
exit 2（三态契约定稿 §7.3「闸内无 SKIP」：缺 SDK=环境红）.
cwd = lane root.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "server/engine")

try:
    import temporalio  # noqa: F401
except Exception:
    print("ENV_FAIL: temporalio SDK unavailable（venv 缺失，真覆盖在有 SDK 的顶层环境跑）")
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

import shared  # noqa: E402
import agent_activities as aa  # noqa: E402

REPO = shared.REPO_ROOT
EPIC_BASE = "t-itest19"          # synthetic, matches EPIC_CODE_RE, never a real epic


class _SpawnAttempted(Exception):
    pass


passed, failed = 0, 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL %s %s" % (name, detail))


def epic(n):
    return "%s-%s" % (EPIC_BASE, n)


def make_args(ws, ep, sk):
    return shared.AgentStageArgs(
        ticket_id="t260901-19-itest", stage_id="suggest_next", role="integration",
        prompt="p", workspace={"path": ws, "type": "dir"},
        result_file=shared.result_file_for("t260901-19-itest", "suggest_next", 0,
                                           {"path": ws, "type": "dir"}),
        gen=0, epic=ep, state_key=sk)


def write_precache(ep, sk, suggestion):
    return aa._write_precache("t260901-19-itest", ep, sk, suggestion)


def run_case(suggestion=None, *, ep="a", sk="sk1", pre_sk=None, pre_epic=None,
             corrupt=False, stub=None, rfile_payload=None, drop_state_key=False,
             epic_in_args=True):
    """One short-circuit scenario. Returns (result, spawn_attempted)."""
    ws = tempfile.mkdtemp(prefix="t260901-19-t3-")
    code = pre_epic or epic(ep)
    real_spawn = aa._prepare_agent_spawn
    attempted = {"hit": False}

    def guard(*a, **k):
        attempted["hit"] = True
        raise _SpawnAttempted()

    args_ep = code if epic_in_args else ""
    args = make_args(ws, args_ep, sk)
    try:
        if corrupt:
            path = shared.epic_next_precache_path(REPO, code)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not-json", "utf-8")
        elif suggestion is not None:
            write_precache(code, pre_sk if pre_sk is not None else sk, suggestion)
            if drop_state_key:
                p = shared.epic_next_precache_path(REPO, code)
                raw = json.loads(p.read_text("utf-8"))
                del raw["state_key"]
                p.write_text(json.dumps(raw, ensure_ascii=False), "utf-8")
        if rfile_payload is not None:
            rf = Path(args.result_file)
            rf.parent.mkdir(parents=True, exist_ok=True)
            rf.write_text(json.dumps(rfile_payload, ensure_ascii=False), "utf-8")
        aa._prepare_agent_spawn = guard
        if stub is not None:
            os.environ["SANDBAR_SUGGEST_STUB"] = stub
        try:
            res = asyncio.run(aa.suggest_next(args))
        except _SpawnAttempted:
            return None, True
        finally:
            aa._prepare_agent_spawn = real_spawn
            os.environ.pop("SANDBAR_SUGGEST_STUB", None)
        return res, attempted["hit"]
    finally:
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(shared.epic_next_precache_path(REPO, code).parent,
                      ignore_errors=True)
        # mirror_to_legacy 会把新名预跑缓存镜像到旧名 .suyou/epic-next/（naming-compat 镜像面；退役账#5
        # 过渡面），镜像出的旧名副本不同步清 → no-residue 假红（t260907-12 顺修；t260907-10
        # 泳道侧独立复现同一根因并同款修复——引擎写侧镜像补旧名副本，清理必须双侧同清）。
        # 旧名同 rel 一并清理（best-effort，与镜像同口径；路径用 shared.DOT_DIR_OLD 常量）。
        shutil.rmtree(REPO / shared.DOT_DIR_OLD / "epic-next" / code,
                      ignore_errors=True)


OK_SUG = {"status": "ok", "workflow": "dev-lane", "title": "T1", "body": "b",
          "rationale": "r", "write_set": []}
DONE_SUG = {"status": "done", "summary": "没事可做"}


def main():
    # a) ok-form hit -> ok result, precache-hit marker, zero spawn
    res, spawned = run_case(dict(OK_SUG))
    check("ok-hit-no-spawn", res is not None and not spawned)
    check("ok-hit-status", res and res.status == "ok")
    check("ok-hit-marker", res and "precache-hit" in (res.evidence or ""))

    # b) done-form hit -> 可结项 semantics, zero spawn
    res, spawned = run_case(dict(DONE_SUG), ep="b")
    check("done-hit-no-spawn", res is not None and not spawned)
    check("done-hit-semantics", res and res.status == "ok" and "可结项" in res.summary)
    check("done-hit-marker", res and "precache-hit" in (res.evidence or ""))

    # c) state_key mismatch -> spawn
    _, spawned = run_case(dict(OK_SUG), ep="c", sk="sk1", pre_sk="sk-other")
    check("sk-mismatch-spawns", spawned)

    # d) corrupt pre.json -> spawn
    _, spawned = run_case(ep="d", corrupt=True)
    check("corrupt-spawns", spawned)

    # e) missing state_key in pre.json -> spawn
    _, spawned = run_case(dict(OK_SUG), ep="e", drop_state_key=True)
    check("no-statekey-spawns", spawned)

    # f) suggestion missing title -> spawn
    bad = dict(OK_SUG, title="")
    _, spawned = run_case(bad, ep="f")
    check("missing-title-spawns", spawned)

    # g) workflow not in template whitelist -> spawn (防幻觉闸 re-applied)
    halluc = dict(OK_SUG, workflow="no-such-template")
    _, spawned = run_case(halluc, ep="g")
    check("whitelist-spawns", spawned)

    # h) failed-form cache -> spawn
    _, spawned = run_case({"status": "failed", "reason": "x"}, ep="h")
    check("failed-form-spawns", spawned)

    # i) empty epic in args -> no short-circuit, spawn
    _, spawned = run_case(dict(OK_SUG), ep="i", epic_in_args=False)
    check("empty-epic-spawns", spawned)

    # j) stub channel wins over a valid cache hit (test isolation contract)
    res, spawned = run_case(dict(OK_SUG), ep="j", stub="ok")
    check("stub-precedence", res is not None and "[stub]" in (res.summary or "")
          and "precache-hit" not in (res.evidence or ""))

    # k) rfile idempotency regression: existing rfile wins, no cache marker
    res, spawned = run_case(rfile_payload=dict(OK_SUG), ep="k")
    check("rfile-idempotent", res is not None and res.status == "ok"
          and not spawned and "precache-hit" not in (res.evidence or ""))

    # l) no cache, no stub -> plain spawn path
    _, spawned = run_case(ep="l")
    check("cold-path-spawns", spawned)

    # m) hygiene: no test residue under <repoRoot>/.suyou/epic-next/  # naming-compat
    base = REPO / ".suyou" / "epic-next"  # naming-compat
    residue = [p.name for p in base.iterdir()] if base.is_dir() else []
    check("no-residue", not any(n.startswith(EPIC_BASE) for n in residue),
          str(residue))

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
