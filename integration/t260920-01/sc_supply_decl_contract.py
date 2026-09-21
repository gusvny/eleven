#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260920-01 场景④：仓根供给声明（verify.yaml integration.supply[0]）的可执行
纪律契约（灰盒 L2，离线可判）。

用户场景（工单边界与病灶）：供给声明是 verify_lane 每轮集测**必经的机器消费面**
——它怎么写，用户每一轮都实际承受。本票病灶的声明面实况：裸 `docker info`/
`docker image inspect` 无界接触（daemon 假死挂满 900s 兜底）、失败腿 `exit 1`
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
实现落地前红属预期（TDD 信号：现声明裸 docker 在场且失败腿 exit 1），
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
from verify_lane import _cfg_load  # noqa: E402

cfg, cfg_err = _cfg_load(REPO)
ok(cfg is not None, "D0 前置：仓根 verify.yaml 可解析（got err=%r）" % (cfg_err,))
if cfg is not None:
    supply = ((cfg.get("integration") or {}).get("supply")) or []
    ok(bool(supply), "D1 供给声明在场（supply 列表非空——声明被删=供给面裸奔）")
    if supply:
        s0 = supply[0]
        cmd = str(s0.get("cmd") or "")
        ok(bool(str(s0.get("need") or "").strip()),
           "D1a 首条供给声明带 need 点名（契约 ②a）")
        ok("docker info" not in cmd,
           "D1b 无界裸 docker info 已摘除（daemon 门交有界封装）")
        ok("docker image inspect" not in cmd,
           "D1c 无界裸 docker image inspect 已摘除（镜像门交有界封装）")
        ok("SANDBAR_STAGE_WAIT_BUDGET_S" in cmd,
           "D1d 等待预算 env 旋钮已声明（要求③的声明面）")
        ok("exit 1" not in cmd,
           "D1e 失败出口无 exit 1（三态不放宽；环境红语义要求 exit 2）")
        ok("exit 2" in cmd, "D1f 失败出口 exit 2 在场（三态诚实红）")

# ---- D2 缺席形态真跑：预算内快速红 exit 2 + 点名（任何机器可判） ----
if cfg is not None and supply:
    env = dict(os.environ)
    # 受限 PATH：剔除**所有** docker 所在目录（多路径安装形态——只剔第一个会让
    # daemon 健康机器上的缺席腿调到真 docker，前提构造失效，260920 仲裁实锤）；
    # 无 docker 机器天然满足。保留系统命令。
    env["PATH"] = os.pathsep.join(
        d for d in env.get("PATH", "").split(os.pathsep)
        if d and not os.path.exists(os.path.join(d, "docker")))
    # 自清卫兵：实现后声明若把无 docker 接触的段排前（软链腿），不能往仓里
    # 留新文件——记录软链目标存在性，跑后新建则删（幂等声明不应有净写入）。
    link = REPO / "server" / "engine" / "bin" / "temporal"
    link_before = link.exists()
    # 缺席形态由实现按「未就绪」反复探到预算收口（契约内）——注入小预算使本腿
    # 墙钟可断言（预算内收口），不依赖缺省 120s。
    env["SANDBAR_STAGE_WAIT_BUDGET_S"] = "2"
    t0 = time.time()
    try:
        p = subprocess.run(["/bin/sh", "-c", cmd], cwd=str(REPO),
                           capture_output=True, text=True, timeout=120, env=env)
        rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = "TIMEOUT", ""
    wall = time.time() - t0
    if not link_before and link.exists():
        try:
            link.unlink()
        except OSError:
            pass
    ok(rc == 2, "D2 缺席形态真跑声明 → exit 2 诚实红（got rc=%s）" % (rc,))
    ok(wall < 60,
       "D2b 预算内快速收口绝不硬等（wall=%.1fs，900s 兜底只在真正挂死时垫底）"
       % wall)
    ok("ENV_FAIL" in out, "D2c 输出带 ENV_FAIL 三态标记（got: %s)"
       % out[:80].replace("\n", " "))
    ok("docker" in out, "D2d 点名 docker（缺什么说什么，不静默）")
else:
    ok(False, "D2 声明不可读，缺席腿未执行（D1/D0 已红归因）")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
