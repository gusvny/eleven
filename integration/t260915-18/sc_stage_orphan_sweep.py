#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-18 场景②：孤儿容器清扫的半径与判据（灰盒 L3，工单②「自愈」机械入口，
integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）——sweep 的孤儿
清扫（「本管域容器而无租约」= KI-077 当日 37 孤儿形态）必须拆得掉、点得了名，
且**半径可限定、绝不波及前缀外/他票的容器**：

- 正腿：真起台后孤儿化（杀 hold + 删租约=真孤儿，非合成），sweep（孤儿模式
  开 + 年龄阀 0 + 前缀限定本票）必须 dry-run 先认领不拆、真跑 condemned
  点名 + 容器清零 + rc=0；
- 半径限定（本设计段新增的硬契约，理由见下方「为什么」）：condemned 集合
  **必须全部命中本票前缀**——前缀不匹配的同域孤儿（P_nopfx）不得被判拆，
  域外容器（working_dir 仓外）即便前缀命中也不得拆（in-domain 闸高于前缀）；
- 负锁×3（防判据恒真）：
  (α) 租约在册且新鲜的台（hold 活）——租约安全阀，不拆；
  (β) 年龄阀内的孤儿（SANDBAR_STAGE_ORPHAN_MIN_AGE_S 大于容器年龄）——阀内
      不拆；且同一孤儿在阀=0 时必被拆（阀是唯一保护者，防「恒不拆」假绿）；
  (γ) 前缀命中但 working_dir 在仓外（域外容器）——不拆；
- 共享供给台（sandbar-test-integ，他票在管域容器代表）全程零接触。

为什么半径限定是硬契约（本设计段对抗发现 F1，260915 当日实爆）：孤儿容器是
**全机全局**可见的（docker 按标签枚举），而「宿主点头真拆存量」是本票红线
（KI-077 先例=宿主授权清场；create_plan gen1 自己也承诺「存量只 dry-run 点
名」）。无半径 + 缺省开 + 接在 up/ensure 挂点的孤儿清扫 = **任何一次起台都
是一次无授权清场**——260915 17:51 宿主实爆：实现段在飞代码下一次普通 up 的
挂点清扫把宿主存量孤儿（29 只，t26090402/t26091202/t26090502 家族）顺序真
拆（docker events 铁证），process 未过宿主。故清扫半径必须可限定（本场景锚
SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX，实现可选等效机制但必须过本场景断言：
前缀外 condemned 为空 + 前缀外孤儿容器全活）。

与既有场景 intent 分工：t260912-02-sweep-owner-gone 锚**有租约**残台的主人
存在性判定矩阵（租约面手术注入）；本条锚**无租约**孤儿（容器面形态，租约
文件缺失即失明的 KI-077 家族）、清扫半径与年龄阀，判据对象不同不互替。

注入面声明：孤儿化=杀 hold + 删租约（真实形态）；域外容器=docker run 挂
compose 工程标签 + 仓外 working_dir。docker 缺席=ENV_FAIL exit 2。
"""
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

from lib_case import (  # noqa: E402
    ENV_ORPHAN_MIN_AGE_S,
    ENV_SWEEP_ORPHAN_PREFIX,
    ENV_SWEEP_ORPHANS,
    check,
    compose_containers,
    container_alive,
    docker_present,
    envfail,
    finish,
    foreign_container,
    guarded_down,
    iso_root18,
    orphanize,
    rm_foreign_container,
    rm_rf,
    stage_tag,
    sweep,
    up_ok,
    up_stage,
    wait_until,
)

PRI = "t26091518-os-"             # 半径旋钮断言面（本票正腿工程名全部命中它）


def _sweep(root, valve, extra=None):
    env = {ENV_SWEEP_ORPHANS: "1", ENV_ORPHAN_MIN_AGE_S: str(valve),
           ENV_SWEEP_ORPHAN_PREFIX: PRI}
    env.update(extra or {})
    return sweep(root, env_extra=env)


def main():
    if not docker_present():
        envfail("docker 不可用（docker info 失败）——测试台一律走 docker，"
                "启动 Docker/OrbStack 后重试")
        finish()
    tag = "%d" % (int(time.time()) % 100000)
    root = iso_root18("orphan-sweep-" + tag)
    p_orph = stage_tag("t26091518-os-orph-" + tag)      # 正腿孤儿（前缀命中）
    p_keep = stage_tag("t26091518-os-keep-" + tag)      # 负锁α：租约新鲜
    p_valve = stage_tag("t26091518-os-valve-" + tag)    # 负锁β：年龄阀内孤儿
    p_nopfx = stage_tag("t26091518-osx-nopfx-" + tag)   # 半径对照：前缀不匹配
    p_forgn = stage_tag("t26091518-os-fgn-" + tag)      # 负锁γ：前缀命中但域外
    mine = [p_orph, p_keep, p_valve, p_nopfx]
    cid_f = outside = None
    try:
        # ---- 注入：四台真台 + 一只域外容器 ----
        for proj, label in ((p_orph, "正腿孤儿台"), (p_keep, "负锁α 台"),
                            (p_valve, "负锁β 台"), (p_nopfx, "半径对照台")):
            proc, _ = up_stage(root, proj)
            if not up_ok(proc, "%s起台" % label):
                return
        if not orphanize(root, p_orph):
            envfail("正腿孤儿化失败（租约文件删不掉）")
            return
        if not orphanize(root, p_nopfx):
            envfail("半径对照台孤儿化失败（租约文件删不掉）")
            return
        cid_f, outside = foreign_container(p_forgn)
        if not cid_f:
            envfail("域外容器注入失败（docker run 不可用）")
            return
        supply_ids = _supply_ids()

        # ---- dry-run：只认领不拆 ----
        dproc, drpt = sweep(root, "--dry-run", env_extra={
            ENV_SWEEP_ORPHANS: "1", ENV_ORPHAN_MIN_AGE_S: "0",
            ENV_SWEEP_ORPHAN_PREFIX: PRI})
        dcond = [c.get("project") for c in ((drpt or {}).get("condemned") or [])]
        check(p_orph in dcond, "dry-run 认领孤儿台（condemned 含 %s，未执行）"
              % p_orph)
        check(len(compose_containers(p_orph)) > 0, "dry-run 不拆：孤儿台容器仍在")

        # ---- sweep#1（阀=0）：正腿 + 半径 + α/γ 负锁 ----
        rproc, rpt = _sweep(root, 0)
        cond = [c.get("project") for c in ((rpt or {}).get("condemned") or [])]
        check(rproc.returncode == 0,
              "真 sweep rc=0（拆台动作全部成功，失败须上抛非零）｜rc=%s"
              % rproc.returncode)
        check(p_orph in cond, "正腿：孤儿台被判拆并逐条点名（condemned 含 %s）"
              % p_orph)
        check(all(str(c).startswith(PRI) for c in cond),
              "半径限定：condemned 全部命中前缀 %s（前缀外零判拆）｜%s" % (PRI, cond))
        check(p_nopfx not in cond,
              "半径限定：前缀不匹配的同域孤儿不在 condemned（%s 不得被无半径"
              "清扫波及）" % p_nopfx)
        check(wait_until(lambda: len(compose_containers(p_orph)) == 0, 60),
              "正腿：孤儿台容器清零（容器+网络+卷随 down 回收）")
        check(len(compose_containers(p_keep)) > 0,
              "负锁α：租约在册且新鲜的台零接触（租约安全阀）")
        check(len(compose_containers(p_valve)) > 0,
              "负锁α'：未孤儿化的台零接触（本轮 sweep 只动孤儿面）")
        check(container_alive(cid_f),
              "负锁γ：前缀命中但 working_dir 域外的容器不拆（in-domain 闸"
              "高于前缀）")
        check(len(compose_containers(p_nopfx)) > 0,
              "半径守卫：前缀不匹配孤儿容器仍活（condemned 之外不得有拆台动作）")
        if supply_ids:
            check(all(container_alive(c) for c in supply_ids),
                  "半径守卫：共享供给台（他票在管域容器）零接触（%d 只原样）"
                  % len(supply_ids))
        else:
            check(True, "半径守卫：共享供给台不在场（standalone 跑法），半径由"
                        "前缀断言与负锁γ 承担")

        # ---- sweep#2（阀=3600）：孤儿化 P_valve 后年龄阀内不拆 ----
        if not orphanize(root, p_valve):
            envfail("负锁β 孤儿化失败（租约文件删不掉）")
            return
        vproc, vrpt = _sweep(root, 3600)
        vcond = [c.get("project") for c in ((vrpt or {}).get("condemned") or [])]
        check(p_valve not in vcond and len(compose_containers(p_valve)) > 0,
              "负锁β：年龄阀内孤儿不拆（SANDBAR_STAGE_ORPHAN_MIN_AGE_S 生效，"
              "阀内 skipped 逐条带原因）")

        # ---- sweep#3（阀=0）：同一孤儿必被拆——阀是唯一保护者，防恒不拆假绿 ----
        fproc, frpt = _sweep(root, 0)
        fcond = [c.get("project") for c in ((frpt or {}).get("condemned") or [])]
        check(p_valve in fcond and wait_until(
            lambda: len(compose_containers(p_valve)) == 0, 60),
            "正腿补强：阀=0 时同一孤儿被拆（年龄阀是唯一保护者，不是恒不拆）")
    finally:
        guarded_down(mine, root)
        rm_foreign_container(cid_f)
        if outside:
            shutil.rmtree(outside, ignore_errors=True)
        rm_rf(root)
    finish()


def _supply_ids():
    import subprocess
    p = subprocess.run(
        ["docker", "ps", "-q", "--filter",
         "label=com.docker.compose.project=sandbar-test-integ"],
        capture_output=True, text=True, timeout=30)
    return [x for x in (p.stdout or "").split() if x.strip()]


if __name__ == "__main__":
    main()
