#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 场景③：suggest_next 退役 cutover 的在飞重放兼容（方案 T1-2 三层的机械面）。

intent（登记于 run_scenarios.py，本文件为其执行体）：
  子用例一（通过子用例·唯一通过子用例）：docker 测试台上驱动一条**无 suggestion 命令**的在飞 history
    （复用 t260908-01 lib_ki061.drive_to_overlimit_blocked 的成熟驱动：create_plan 桩会话
    + arbitrate 超限 blocked + retry 循环——全在 merge 签字之前，绝无
    prepare_epic_next/suggest_next 活动命令），replay_check（只读，指向测试台）用当前
    （退役后）代码回放 → 零分歧 ok=true（cutover 对在飞票安全的机械证明）；
  子用例二（通过子用例·全集）：replay_check 对测试台全 RUNNING 集回放 → 全 ok（drain 核验同款闸）；
  子用例三（负向子用例·预期响亮红）：夹具 history（含 prepare_epic_next/suggest_next 活动命令的
    旧形态导出件）→ replay_check --history 用退役后代码回放**必须响亮失败**——红是预期，
    留档=「含 suggestion 命令 history 与删除后代码不可重放」边界证明 + drain 必要性
    机械证据。夹具缺席=该子用例显式红点名（不静默跳过；夹具由 integration 在 acceptance 段
    备齐，生成程序见 fixtures/README，两条路：①退役前代码在测试台驱动 merge 签字
    （SANDBAR_SUGGEST_STUB 桩）后 temporal CLI show 导出；②从生产 t260910-06/09/10
    （COMPLETED，只读）导出）。
三态：docker/镜像/舞台缺件=ENV_FAIL exit 2（require_stage 直译）；断言破面=exit 1。
实现落地前子用例一/二天然绿（代码尚含旧路径，回放无分歧），子用例三红属预期（TDD 信号）；
arbitrate/merge 期：三子用例按上述语义绿。与 t260908-01 场景② intent 不同面：彼锁 KI-061
marker 消费重放，本条锁退役 cutover 的命令序兼容边界。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260908-01"))
from lib_gate import Fail, poc_python, require_bench, require_stage, stage_down  # noqa: E402
from lib_ki061 import POC_DIR, drive_to_overlimit_blocked, make_fixture_repo  # noqa: E402

TID = "t26091014c-retire"
PROJ_KEY = "t26091014c"
FIXTURE = os.path.join(HERE, "fixtures", "history_with_suggest_next.json")


def run_replay_check(py, state, tid=None, history=None):
    """replay_check 只读回放（指向测试台，不碰任何真环境）。返回 (rc, payload)。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = state["namespace"]
    cmd = [py, os.path.join(POC_DIR, "replay_check.py")]
    if history:
        cmd += ["--history", history]
    elif tid:
        cmd += ["--workflow", tid]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    try:
        return p.returncode, json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        return p.returncode, {"ok": False, "parse_error": (p.stdout or p.stderr)[:200]}


def main():
    fail = Fail("t260910-14 ③退役 cutover 重放兼容")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091014c-")
    stage_mod = None
    worker = None
    try:
        stage_mod, stage = require_stage(fail, "%s-%d" % (PROJ_KEY, os.getpid()), "t26091014c")
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        os.environ["_KI061_REG_DIR"] = reg_dir
        # 驱动一条无 suggestion 命令的在飞 history（merge 签字前的复杂真实形态）
        worker, env, stub_log = drive_to_overlimit_blocked(
            py, fail, tmp, TID, stage, PROJ_KEY, None)

        rc, payload = run_replay_check(py, stage, tid=TID)
        r = (payload.get("results") or [{}])
        r0 = r[0] if r else {}
        fail.check(rc == 0 and payload.get("ok") is True and r0.get("ok") is True,
                   "子用例一：退役后代码回放无 suggestion 命令的在飞 history 零分歧"
                   "（rc=%s ok=%s r0=%s）" % (rc, payload.get("ok"), json.dumps(r0, ensure_ascii=False)[:160]))

        rc, payload = run_replay_check(py, stage)
        results = payload.get("results") or []
        bad = [x for x in results if not x.get("ok")]
        fail.check(payload.get("ok") is True and not bad,
                   "子用例二：全 RUNNING 集回放零分歧=drain 闸同款（n=%d bad=%s）"
                   % (len(results), json.dumps(bad[:1], ensure_ascii=False)[:160]))

        # 负向子用例：含 suggestion 命令的旧 history 必须响亮红（边界留档）
        if not os.path.isfile(FIXTURE):
            fail.check(False,
                       "子用例三：负向夹具缺席（%s）——integration 须在 acceptance 段按 fixtures/README "
                       "程序导出含 prepare_epic_next/suggest_next 活动命令的旧形态 history（红=预期口径）"
                       % os.path.relpath(FIXTURE, REPO))
        else:
            rc, payload = run_replay_check(py, stage, history=FIXTURE)
            loud = (rc != 0) or (payload.get("ok") is False) or \
                any(not x.get("ok") for x in (payload.get("results") or []))
            fail.check(loud, "子用例三：含 suggestion 命令 history 回放响亮红（预期边界；rc=%s ok=%s）"
                       % (rc, payload.get("ok")))
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
        if stage_mod is not None:
            stage_down(stage_mod, "%s-%d" % (PROJ_KEY, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()


if __name__ == "__main__":
    main()
