#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景：清扫成本与失败可见性（灰盒 L3，工单验收 D 的机械入口，
integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 零残台时单次扫描+清理 ≤5 秒（连续三遍取每遍计时不取均值——长尾才算数），
  且 rc=0、零点名（没有残台就不得编造点名）；
- 清理失败必须响亮上抛：注入一条「主人目录已删」的残台 + 置坏 docker 桩
  （PATH 前置一个必失败的 docker 假体，只遮蔽 docker 不遮蔽 git）→ sweep
  必须非零退出并在输出点名该残台——静默吞掉=红（不得无声假装扫过）；
- 撤桩重扫：健康 PATH 下同一残台被正常拆掉（清理恢复路径真通）；
- 幂等二扫仍在成本预算内。

与既有场景 intent 分工：t260912-02-sweep-owner-gone 锚判拆矩阵与负锁（拆谁/
不拆谁），本条锚 **成本与失败可见性**（拆得快不快、失败了看不看得见）——
intent 不同面不互替。登记 exclusive：≤5s 是负载敏感断言（KI-072 家族），
并发池会把它打假红。docker 缺席=ENV_FAIL exit 2。实现段落地前红属预期
（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_lifecycle_case import (  # noqa: E402
    check,
    craft_lease,
    docker_present,
    docker_shim_dir,
    envfail,
    finish,
    guarded_down,
    iso_root,
    kill_holder,
    read_lease_file,
    rm_rf,
    sleep_holder,
    stage_tag,
    sweep,
)

TAG = stage_tag("t26091202-sweepcost")
ROOT = iso_root("sweepcost")
SWEEP_BUDGET_S = 5.0
ROUNDS = 3


def timed_sweep(*args, **kw):
    t0 = time.time()
    proc, report = sweep(ROOT, *args, **kw)
    return proc, report, time.time() - t0


def main():
    if not docker_present():
        envfail("docker 缺席——清扫成本面不可验（启动 Docker/OrbStack 后重试）")
        finish()

    holder = None
    gone = None
    victim = "%s-victim" % TAG
    try:
        # ---- 零残台：三遍扫描，每遍 ≤5s、rc=0、零点名 ----
        for i in range(ROUNDS):
            proc, report, wall = timed_sweep(timeout=120)
            check(proc.returncode == 0,
                  "空扫第 %d 遍 rc=0（实得 %s）" % (i + 1, proc.returncode))
            check(wall <= SWEEP_BUDGET_S,
                  "空扫第 %d 遍 ≤5s（实得 %.2fs）" % (i + 1, wall))
        # 零残台不得编造点名：输出里不得出现任何工程名词行——以「无 JSON 条目」
        # 为判据（报告缺席/空集合都算过，点名了不存在的工程才算红）。
        proc0, report0, _w = timed_sweep(timeout=120)
        check(proc0.returncode == 0, "空扫复测 rc=0")
        if report0 is not None:
            vals = _json_values(report0)
            tagged = [v for v in vals if TAG in str(v)]
            check(not tagged, "零残台零点名（报告点名了不存在的 %s）" % tagged[:3])
        else:
            check(TAG not in (proc0.stdout or ""),
                  "零残台零点名（文本输出不得出现工程名）")

        # ---- 失败必须响亮：残台 + 坏 docker 桩 ----
        gone = tempfile.mkdtemp(prefix="sandbar-t26091202-costgone-")
        rm_rf(gone)   # 主人目录已删
        holder = sleep_holder()
        craft_lease(ROOT, victim, state="up", holder_pid=holder.pid,
                    owner_root=gone)
        shim = docker_shim_dir()
        try:
            proc_bad, _r = sweep(ROOT, timeout=180,
                                 env_extra={"PATH": shim + os.pathsep
                                            + os.environ.get("PATH", "")})
            check(proc_bad.returncode != 0,
                  "清理失败非零退出（不得静默；实得 rc=%s）" % proc_bad.returncode)
            blob = (proc_bad.stdout or "") + (proc_bad.stderr or "")
            check(victim in blob, "失败输出点名残台工程（%s 是否在输出：%s）"
                  % (victim, victim in blob))
        finally:
            rm_rf(shim)

        # ---- 撤桩恢复：健康 PATH 下同一残台被正常拆掉 ----
        proc_ok, _r = sweep(ROOT, timeout=300)
        check(proc_ok.returncode == 0, "撤桩后清扫 rc=0（实得 %s）"
              % proc_ok.returncode)
        check(read_lease_file(ROOT, victim) is None,
              "恢复路径：残台租约被正常释放")
        _proc_clean, _rep, wall_clean = timed_sweep(timeout=120)
        check(wall_clean <= SWEEP_BUDGET_S,
              "幂等二扫仍在预算内（%.2fs ≤ 5s）" % wall_clean)
    finally:
        if holder is not None:
            kill_holder(holder)
        guarded_down([victim], ROOT)
        if gone:
            rm_rf(gone)
        try:
            os.remove(os.path.join(ROOT, "project-%s.json" % victim))
        except OSError:
            pass
    finish()


def _json_values(obj):
    out = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _json_values(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _json_values(v)
    elif isinstance(obj, str):
        out.add(obj)
    return out


if __name__ == "__main__":
    main()
