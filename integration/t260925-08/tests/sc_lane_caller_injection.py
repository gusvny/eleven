#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_lane_caller_injection.py — lane agent 调用方身份注入链契约（t260925-08）。

登记：integration/run_scenarios.py SCENARIOS「t260925-08-lane-caller-injection」。
跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260925-08/tests/sc_lane_caller_injection.py

灰盒 L2 离线（agent_runtime 可安全 import——temporalio 全函数内延迟导入，模块头
自声明禁 import shared/agent_activities）。intent：KI-119 修法方向①的引擎半边——
泳道 agent 起的进程**自动带调用方项目身份**，同项目写零变化、跨项目必须显式旗：
  1. docker 形态 env 白名单含 SANDBAR_CALLER_PROJECT（agent 容器内身份可达的机械
     前提；白名单缺席=注入链在容器边界断，undeclared 回潮）。
  2. spawn 链注入源码锚：三个 spawn 面（_prepare_agent_spawn / arbitrate /
     inspection）在 agent_activities.py 注入 caller env——注入点缺席=闸只见
     undeclared，翻严后泳道自身被拒（用户可感知事故面）。
  3. 注入端到端行为面：合法 project 经注入形态（env 传入）解析为 declared
     src=env → judge 同项目 pass 零 notice（工单要求④「同项目写零变化」的
     用户可感知出口）；畸形 project key（大写/空格/路径穿越/超长）注入位不注入、
     解析期 raise 点名——不在注入处静默纠偏，也不给闸喂畸形身份。
  4. undeclared 兜底收口对照：无注入+无旋钮（缺省 refuse）时同一次调用被拒且
     why 点名 env 名——「注入了就放行、没注入就拒且说清缺什么」的对称面。
  5. console 红线观察面：server/ 根 admin.py 与 server/plugins/ 插件目录零改动锚——
     grep caller 注入落点只在引擎侧（agent_runtime/agent_activities），console
     侧文件不在本票触碰面（红线：console 零重启零占用；本场景为静态只读锁）。

三态：PASS exit 0 / FAIL exit 1；纯离线无环境依赖，无 ENV_FAIL 形态。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

import agent_runtime  # noqa: E402
import caller_gate  # noqa: E402
import shared  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title):
    print("\n%s" % title)


def src_of(rel):
    return (ROOT / rel).read_text("utf-8")


ACT = src_of("server/engine/agent_activities.py")
ADMIN = src_of("server/admin.py") if (ROOT / "server/admin.py").exists() else ""
DSH_PLUGIN_HITS = 0
# 260928 修：旧布局的插件目录已随 M2 搬迁消失（现布局=server/plugins/）⇒ 原观察面
# `is_dir()=False` 恒零命中
# （**假绿**：号称扫过插件目录其实一个文件没扫）。改指当前插件目录 server/plugins/。
dsh_dir = ROOT / "server" / "plugins"
if dsh_dir.is_dir():
    for p in dsh_dir.rglob("*.js"):
        try:
            if shared.CALLER_PROJECT_ENV in p.read_text("utf-8", errors="ignore"):
                DSH_PLUGIN_HITS += 1
        except OSError:
            pass

ENV_NAME = shared.CALLER_PROJECT_ENV


# ---------- 1. env 白名单 ----------
section("1 docker 形态 env 白名单含调用方身份注入两键（只加不删）")
ok(ENV_NAME in agent_runtime.ENV_ALLOWLIST,
   "ENV_ALLOWLIST 含 %s（容器边界透传身份）" % ENV_NAME)
SURFACE_NAME = shared.CALLER_SURFACE_ENV
ok(SURFACE_NAME in agent_runtime.ENV_ALLOWLIST,
   "ENV_ALLOWLIST 含 %s（注入面标签，injected_by 判别信号 review N2）" % SURFACE_NAME)
ok(("DSH_HOME", "DSH_HEADLESS_SESSION") ==
   tuple(k for k in agent_runtime.ENV_ALLOWLIST
         if k not in (ENV_NAME, SURFACE_NAME)),
   "白名单既有成员零变化（t260925-08 只加身份注入两键，不删）")

# ---------- 2. spawn 链注入源码锚 ----------
section("2 spawn 链注入源码锚（agent_activities 单点注入面）")
ok("shared.CALLER_PROJECT_ENV" in ACT,
   "agent_activities.py 引用 caller env 常量（注入面在位；三 spawn 面同经 "
   "_prepare_agent_spawn 单点，无需逐面复制）")
ok("shared.PROJECT_KEY_RE.match" in ACT,
   "注入位形状校验在位（合法才注入，不静默纠偏）")
ok("CALLER_SURFACE_LANE_AGENT" in ACT,
   "注入伴随 SURFACE 标签=lane-agent（injected_by 判别信号，review N2）")

# ---------- 3. 注入端到端行为面 ----------
section("3 注入→解析→判定 端到端（同项目写零变化）")
r = caller_gate.resolve_identity("", "proj-a", "", (), [])
ok(r == {"value": "proj-a", "src": "env", "identity_class": "declared"},
   "注入形态（env）解析=declared src=env")
g = caller_gate.judge_caller(r, "proj-a", None)
ok(g["decision"] == "pass" and g["stamp"] == "proj-a" and not g["notice"],
   "同项目写 pass 零 notice（要求④：零行为变化）")
g = caller_gate.judge_caller(r, "proj-b", None)
ok(g["decision"] == "refuse",
   "注入身份跨项目无旗=refuse（escape hatch 只剩显式旗）")
for bad in ("Proj_A", "has space", "../escape", "a" * 50):
    try:
        caller_gate.resolve_identity("", bad, "", (), [])
        ok(False, "畸形注入值 %r… → 解析期 raise" % bad[:12])
    except Exception as e:
        ok(bad in str(e), "畸形注入值 %r… → raise 点名不纠偏" % bad[:12])

# ---------- 4. 无注入对照（缺省 refuse 对称面） ----------
section("4 无注入+缺省策略=拒收且点名缺什么")
os.environ.pop(ENV_NAME, None)
os.environ.pop("SANDBAR_UNDECLARED_POLICY", None)
r = caller_gate.resolve_identity("", "", "/tmp/elsewhere", (), [])
ok(r["identity_class"] == "undeclared", "无注入且 cwd 无归属=undeclared")
g = caller_gate.judge_caller(r, "proj-a", None)
ok(g["decision"] == "refuse" and ENV_NAME in str(g.get("why")),
   "缺省 refuse：why 点名 %s（用户被告知缺什么，非无声拒绝）" % ENV_NAME)

# ---------- 5. console 红线静态观察 ----------
section("5 console 红线观察面（零改动锚，只读）")
ok(shared.CALLER_PROJECT_ENV not in ADMIN if ADMIN else True,
   "server/admin.py 无本票注入落点（console 侧接线归后续插件票，红线零接触)")
ok(DSH_PLUGIN_HITS == 0,
   "server/plugins/ 插件目录零本票 env 注入命中（3099 运行面零触碰）")

print("\n== PASS=%d FAIL=%d ==" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
