#!/usr/bin/env python3
"""定点复跑入口契约·走查取证可复用面（t260924-09，registry: t260924-09-fixed-rerun-entry）。

意图（灰盒 L3，ro 池，真执行器 CLI 黑盒子进程，秒级零 docker）：
工单必做②要求「提供或钉死定点复跑入口（单条名/红项名单）」——走查/仲裁 agent
复现本票 journey 场景红时只跑该条。本场景守执行器公开 CLI 上这条通道真的可用、
且可叠加闸口径、产出逐条耗时（必做④对照证据「定点 vs 全量」的数据前提）：

- A 定点复跑：`--only <在册名>` 恰跑该 1 条，PASS 行点名该名且带逐条耗时
  `(<N.N>s)`（对照证据两列耗时里「定点单条耗时」一列的机械来源——无逐条耗时
  则必做④只能拿跨场景数字顶替，t260924-04 review C1 打回的正是这个）；
- B 定点×闸口径叠加：`--only <名> --exclude-pools engine,exclusive`（走查
  合规定点形态）行为与 A 一致——定点主通道不因叠加排除声明而变味；
- C 叠加下 fail-closed 保持：`--only` 含不在册名 → exit 2、一条不跑、零起台
  （t260922-12 ④契约在叠加形态下原样——点名错=调用方 bug，绝不静默跑剩下的）。

intent 分工：t260922-12 场景族/developer L1 已守 --only fail-closed 与解析层
纯面——本条不重复，只守「走查取证视角的定点复跑可用性」：恰一条、逐条耗时在
案、叠加闸口径不变味。t260913-03 守池排除旋钮本体，本条把排除当既定参数消费。
选点 t260903-12-ver-semver-rc（离线秒级、零 docker 零端口）作定点对象——
被点名条目自身的行为不在本场景断言面（归其自己的注册条目）。
执行器缺席 / 定点条目自身 ENV_FAIL（依赖缺席）= ENV_FAIL exit 2。
"""
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import env_fail  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
EXEC = [sys.executable, "integration/run_scenarios.py"]
FIXED = "t260924-09-walkthrough-copy-discipline"


def run_cli(args, timeout=180):
    t0 = time.time()
    # 仲裁 gen1：剥批台/定点注入标记——本场景守执行器 CLI 顶层契约，嵌套子进程
    # 继承闸 worker 的批台注入（SANDBAR_STAGE_BATCH）会走批消费缝语义（闸内
    # ENV_FAIL 形态），与被测契约无关；剥法同 t260914-04 剥泳道标记先例。
    # 走查 gen2：真根因=同泳道单飞锁——外层执行器持锁期间嵌套 run_scenarios
    # 必抢锁失败 exit 2（run_scenarios._acquire_run_lock，环境红收口），A/B 主
    # 通道在闸内结构性不可绿。本场景是「嵌套黑盒调用」非「并发全轮共用泳道」，
    # 正是该旋钮的显式豁免语义（SANDBAR_INTEG_ALLOW_CONCURRENT=1），旋钮打开
    # 时执行器自身留痕（INTEG_RUN_LOCK 已显式关闭行），串台责任由调用方承担
    # ——本场景零起台零共享台面，无串台对象。
    # 260930：收窄/策略旋钮单点清理（原先只剥两个键，KNOWN_RED/GATE_*/POOL_CONC 等
    # 仍会继承）；本夹具显式声明的那两档在下面给。
    env = clean_narrowing_env({"SANDBAR_INTEG_ALLOW_CONCURRENT": "1"})
    p = subprocess.run(EXEC + args, cwd=str(REPO), capture_output=True,
                       text=True, timeout=timeout, env=env)
    return p.returncode, p.stdout + p.stderr, time.time() - t0


def main():
    rc, out, _ = run_cli(["--only", FIXED])
    if rc == 2:
        # 单飞锁已豁免（上方 env），此处 rc=2 只剩被点名条目自身环境红一态
        env_fail("定点复跑对象自身环境红：%s｜执行器原文尾段=%s"
                 % (FIXED, out.strip()[-200:]))
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：" + detail) if detail else ""))

    # ---- A 定点复跑：恰一条 + PASS 点名 + 逐条耗时在案 ----
    check("A1 --only 恰跑 1 条且绿（定点通道可用）",
          rc == 0 and "ran=1 pass=1" in out,
          "exit=%s（执行器汇总行形状漂移时按 FAIL 归因）" % rc)
    check("A2 PASS 行点名该条并带逐条耗时 (N.Ns)——必做④定点列的数据前提",
          ("PASS [%s] (" % FIXED) in out,
          "PASS 行无耗时括注=对照证据只能拿跨场景数字顶替（review C1 病灶复燃）")

    # ---- B 定点 × 闸口径叠加 ----
    rc, out2, _ = run_cli(["--only", FIXED,
                           "--exclude-pools", "engine,exclusive"])
    check("B1 叠加闸口径后定点行为不变（走查合规定点形态）",
          rc == 0 and ("PASS [%s] (" % FIXED) in out2,
          "exit=%s" % rc)

    # ---- C 叠加下 fail-closed：不在册名一条不跑、零起台 ----
    rc3, out3, wall = run_cli(
        ["--only", "%s,does-not-exist-xyz" % FIXED,
         "--exclude-pools", "engine,exclusive"], timeout=60)
    check("C1 叠加形态下不在册名仍 fail-closed exit 2",
          rc3 == 2 and "一条都未跑" in out3,
          "exit=%s（静默跑剩下的=点名契约在叠加形态下破洞）" % rc3)
    check("C2 fail-closed 快速短路零起台（秒级返回）", wall < 30,
          "wall=%.1fs——fail-closed 不该烧起台面" % wall)

    n_fail = legs.count(False)
    print("SUMMARY t260924-09-fixed-rerun-entry: %d/%d 绿"
          % (len(legs) - n_fail, len(legs)))
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
