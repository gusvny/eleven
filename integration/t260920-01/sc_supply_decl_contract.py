#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260920-01 场景④：仓根供给声明（verify.yaml integration.supply[0]）的可执行
纪律契约（灰盒 L2，离线可判）。

用户场景（工单边界与病灶）：供给声明是 verify_lane 每轮集测**必经的机器消费面**
——它怎么写，用户每一轮都实际承受。本票病灶的声明面实况：裸 `docker info`/
`docker image inspect` 无界接触（daemon 假死挂满 900s 兜底）、失败用例 `exit 1`
（三态口径外的退出码，环境红无法被判据面识别为可豁免形态）。

收口后用户可感知行为（工单要求②③ + 边界红线「不许放宽 ENV_FAIL 三态语义」）：
  D1 声明结构纪律：supply[0] 不含无界裸 docker 接触（daemon/镜像在场门交给
     ensure 的有界门承担）、等待预算 env 旋钮已声明、失败出口全部 exit 2
     （三态不放宽；从旧 exit 1 收敛到 exit 2 是收紧方向）；
  D2 docker 缺席形态下真跑声明全文（/bin/sh -c、cwd=仓根，与闸消费同款）：
     预算内快速诚实红 exit 2 + 点名（绝不挂 900s、绝不是 exit 1）——用户在
     daemon 缺席机器上得到的是秒级可判的红点名，不是十分钟硬等。
D2 在任何机器上都可判（受限 PATH 剔除 docker 后，声明应在第一个 docker 接触点
快速收口，不触及后续段）；声明「健康机器全文可通」的回归面由每轮集测段自身的
supply 步天然承担（同一条命令每票必跑），本场景不冗余起台。

与既有资产 intent 分工（防重复声明）：
  · t260904-12 sc_supply_gate_ethred 锁 verify_lane supply 机制本体（假声明仓）
    ——本条锁**本仓真声明**的内容契约（真解析器读仓根 verify.yaml）；
  · 场景②③锁 daemon/争用等待的 CLI 行为——本条锁声明文件的静态纪律 + 缺席
    形态端到端退出码，三层互不替代。
断言锚 intent 而非字面排版：无界接触按「裸 docker info / docker image inspect
命令在场」判（有界封装的新形态不受影响——若未来票把门改回声明侧的有界形态，
本场景红=提示人审更新契约口径，属声明契约变更的预期流程）。
实现落地前红属预期（TDD 信号：现声明裸 docker 在场且失败用例 exit 1），
arbitrate/merge 期必须绿。
跑法：python3 -B integration/t260920-01/sc_supply_decl_contract.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "server" / "tools"))

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


# ---- D1 结构纪律：真解析器读仓根声明（与闸同源，零 yaml 依赖） ----
# 261027 host order: docker is retired from the test estate. The declaration must
# therefore NOT carry a docker test-stage supply any more; the live entry is the
# browser dependency (playwright-core), and it still has to satisfy the contract
# (a named need, a bounded command, exit 2 on failure, no bare unbounded probe).
from verify_lane import _cfg_load  # noqa: E402

cfg, cfg_err = _cfg_load(REPO)
ok(cfg is not None, "D0 前置：仓根 verify.yaml 可解析（got err=%r）" % (cfg_err,))
if cfg is not None:
    supply = ((cfg.get("integration") or {}).get("supply")) or []
    ok(bool(supply), "D1 供给声明在场（supply 列表非空——声明被删=供给面裸奔）")
    needs = [str((e or {}).get("need") or "") for e in supply]
    cmds = [str((e or {}).get("cmd") or "") for e in supply]
    ok(all("docker" not in n.lower() for n in needs),
       "D1g docker 供给要求已退役（宿主令 261027：未来不允许再使用 docker）")
    ok(all("docker info" not in c and "docker image inspect" not in c for c in cmds),
       "D1b 无界裸 docker info/image inspect 不在任何供给命令里")
    if supply:
        ok(all(str((e or {}).get("need") or "").strip() for e in supply),
           "D1a 每条供给声明带 need 点名（契约 ②a）")
        ok(any("playwright" in n.lower() for n in needs),
           "D1h 浏览器依赖供给仍在（browser 族仍消费，KI-036）")
        for i, c in enumerate(cmds):
            ok("exit 1" not in c,
               "D1e 供给[%d] 失败出口无 exit 1（三态不放宽；环境红要求 exit 2）" % i)
            ok("exit 1" in c or "exit 2" in c or "||" in c,
               "D1f 供给[%d] 带具名失败出口（不静默）" % i)

# ---- D2 缺席形态真跑：docker 供给已退役（宿主令 261027），本条不再适用 ----
# 原来的 D2 检验「docker 缺席时供给声明按预算内快速 exit 2 并点名 docker」。那条
# 供给已整条摘除，docker 不再是任何闸的前置，所以这里如实记 N/A 并点名原因，
# 不假装跑过、也绝不把 N/A 算成 pass。剩余供给（playwright 依赖）的失败出口纪律
# 由 D1e/D1f 静态执法。
if cfg is None:
    ok(False, "D2 声明不可读，缺席用例未执行（D0 已红归因）")
else:
    print("  N/A  D2 docker 缺席形态 —— docker 供给已按宿主令 261027 退役，"
          "本条无被测对象（不计 pass、不计 fail；纪律面由 D1g/D1e/D1f 静态执法）")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
