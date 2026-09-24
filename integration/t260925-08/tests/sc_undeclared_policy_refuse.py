#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_undeclared_policy_refuse.py — undeclared 策略翻严后的闸行为契约（t260925-08）。

登记：integration/run_scenarios.py SCENARIOS「t260925-08-undeclared-refuse-flip」。
跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260925-08/tests/sc_undeclared_policy_refuse.py

灰盒 L2 离线（shared/caller_gate 纯函数层真 import，t260915-12 源码锁场景同款模式）。
intent（t260915-12 既有双场景锁的是「record 现状」，本场景锁 KI-119 收口后的新契约，
不互替）：
  1. 策略缺省=refuse（翻严锚，KI-119 风险②收口）——undeclared 调用方对项目票写操作
     fail-closed 拒收，why 点名缺失身份 env 名（SANDBAR_CALLER_PROJECT）与注入链指引，
     绝不静默回落记名放行（用户可感知：未接线调用面被拒且被告知缺什么）。
  2. 运维旋钮：SANDBAR_UNDECLARED_POLICY 显式选 record → 行为与旧 B 策略同形
     （stamp=哨兵、notice 在场、identity_class=undeclared 如实记名）——过渡期杠杆。
  3. 旋钮畸形值 fail-closed：非法值 raise 点名非法值本身（报错必须说哪个检查失败，
     绝不静默回落任一策略）；空串=视同未设置（unset 语义，不误伤空 env 注入）。
  4. 零回归面（工单要求④）：declared 同项目 pass（stamp=值、无 notice）；
     engine-internal（target=""）恒 pass；declared 异项目无旗 refuse / 带合规越权旗
     pass_override——唯一 sanctioned escape hatch 语义原样。
  5. 源码结构锚：client.py 回执含 injected_by 尽力面标签（审计「身份从哪个面进来」，
     值域 {lane-agent, external-env}）；shared/caller_gate 策略消费改走函数单点
     （不再直读常量——旋钮与缺省翻严的机械前提）。
  6. 畸形输入：身份形状非法（大写/空格/路径穿越串）解析期 raise 点名（既有纪律，
     注入合法化不因翻严回潮）。

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


CLIENT = src_of("server/engine/client.py")
SHARED = src_of("server/engine/shared.py")
CALLERGATE = src_of("server/engine/caller_gate.py")


def clear_knob():
    os.environ.pop("SANDBAR_UNDECLARED_POLICY", None)


def policy_default():
    clear_knob()
    try:
        return shared.undeclared_policy()
    except Exception:
        return "raise"


def policy_with(value):
    os.environ["SANDBAR_UNDECLARED_POLICY"] = value
    try:
        return shared.undeclared_policy()
    except Exception as e:
        return ("raise", str(e))


UNDECLARED = {"value": "", "src": "none", "identity_class": "undeclared"}
DECLARED_A = {"value": "proj-a", "src": "env", "identity_class": "declared"}


# ---------- 1. 缺省翻严 ----------
section("1 缺省策略=refuse（KI-119 翻严锚）")
ok(policy_default() == "refuse",
   "undeclared_policy() 缺省=refuse（不再回落 record）")
ok(hasattr(shared, "UNDECLARED_POLICY_ENV")
   and shared.UNDECLARED_POLICY_ENV == "SANDBAR_UNDECLARED_POLICY",
   "旋钮 env 名常量在位=SANDBAR_UNDECLARED_POLICY")

g = caller_gate.judge_caller(dict(UNDECLARED), "proj-b", None)
ok(g.get("decision") == "refuse",
   "undeclared 对他项目票写=refuse（fail-closed，非记名放行）")
why = str(g.get("why") or "")
ok(shared.CALLER_PROJECT_ENV in why,
   "refuse why 点名缺失身份 env 名 SANDBAR_CALLER_PROJECT")
ok(g.get("stamp") == "" and not g.get("override_used"),
   "拒收路径零盖章零越权旗消费")

# ---------- 2. 运维旋钮=record 回旧形 ----------
section("2 旋钮显式 record=旧 B 策略同形（过渡杠杆）")
ok(policy_with("record") == "record", "旋钮=record 被认")
g = caller_gate.judge_caller(dict(UNDECLARED), "proj-b", None)
ok(g.get("decision") == "record_undeclared",
   "record 下 undeclared=记名放行（decision=record_undeclared）")
ok(g.get("stamp") == shared.CALLER_UNDECLARED_MARK,
   "记名盖章=哨兵值（与旧 B 策略同形）")
ok(bool(g.get("notice")), "record 下 notice 在场（如实告知未声明+策略）")
ok(policy_with("refuse") == "refuse", "旋钮=refuse 被认（显式与缺省同值合法）")
clear_knob()

# ---------- 3. 旋钮畸形值 fail-closed ----------
section("3 旋钮畸形值=raise 点名（不静默回落）")
# 契约锚：raise 发生+文案点名 env 名（=说清哪个检查失败）；非法词本身逐字回显。
# 带空白包边的合法词（' refuse'/'record '）：实现严格等值不纠偏、文案回显剥边后的
# 值——回显形态不锚原始字节，只锚「raise+点名 env 名+非合法放行」（仲裁 gen0 定）。
for bad in ("allow", "REFUSE", "r"):
    r = policy_with(bad)
    ok(isinstance(r, tuple) and r[0] == "raise" and bad in r[1],
       "畸形值 %r → raise 且点名该值" % bad)
for padded in (" refuse", "record "):
    r = policy_with(padded)
    ok(isinstance(r, tuple) and r[0] == "raise"
       and shared.UNDECLARED_POLICY_ENV in r[1] and padded.strip() in r[1],
       "空白包边合法词 %r → raise（严格等值不纠偏）且回显剥边值+点名 env 名" % padded)
clear_knob()
ok(policy_default() == "refuse", "空串/缺旋钮回缺省（空串=unset 语义不炸）")
os.environ["SANDBAR_UNDECLARED_POLICY"] = ""
ok(policy_default() == "refuse", "空串旋钮=视同未设置（回落缺省 refuse）")
os.environ.pop("SANDBAR_UNDECLARED_POLICY", None)

# ---------- 4. 零回归面 ----------
section("4 同项目/引擎件/越权旗零回归（工单要求④）")
g = caller_gate.judge_caller(dict(DECLARED_A), "proj-a", None)
ok(g.get("decision") == "pass" and g.get("stamp") == "proj-a" and not g.get("notice"),
   "declared 同项目=pass 零变化（stamp=值、无 notice）")
g = caller_gate.judge_caller(dict(UNDECLARED), "", None)
ok(g.get("decision") == "pass", "engine-internal（target=\"\"）恒 pass（策略翻严不波及）")
g = caller_gate.judge_caller(dict(DECLARED_A), "proj-b", None)
ok(g.get("decision") == "refuse" and "proj-a" in str(g.get("why"))
   and "proj-b" in str(g.get("why")),
   "declared 异项目无旗=refuse 且人话点名双项目（既有形状）")
ov, ovwhy = caller_gate.validate_override(
    {"cross_project": {"by": "host", "reason": "代签"}})
g = caller_gate.judge_caller(dict(DECLARED_A), "proj-b", ov)
ok(g.get("decision") == "pass_override" and g.get("override_used")
   and "host" in str(g.get("notice")) and "代签" in str(g.get("notice")),
   "合规越权旗=pass_override（唯一 escape hatch 语义原样，notice 记名 by/理由）")
bad, badwhy = caller_gate.validate_override({"cross_project": {"by": "host"}})
ok(bad is None and badwhy, "畸形旗（缺 reason）fail-closed 拒收不静默")
clear_knob()

# ---------- 5. 源码结构锚 ----------
section("5 源码结构锚（策略单点消费+injected_by 尽力面标签）")
ok("shared.UNDECLARED_POLICY" not in
   CALLERGATE.replace("UNDECLARED_POLICY_ENV", "").replace("shared.undeclared_policy", ""),
   "caller_gate 不再直读策略常量（改走 undeclared_policy() 单点）")
ok("undeclared_policy()" in SHARED and "undeclared_policy()" in CALLERGATE,
   "策略消费经 undeclared_policy() 单点（旋钮+缺省翻严的机械前提）")
ok("injected_by" in CLIENT, "client 回执含 injected_by 键（审计身份进入面）")
for label in ("lane-agent", "external-env"):
    ok(label in CLIENT, "injected_by 值域含 %r" % label)
ok("尽力面" in CLIENT or "非安全断言" in CLIENT,
   "injected_by 语义边界入源码注释（尽力面标签，非安全断言——R3）")

# ---------- 6. 畸形身份输入 ----------
section("6 畸形身份=解析期 raise 点名（注入合法化不回潮）")
for bad in ("Proj_A", "has space", "../escape", "a" * 50):
    try:
        caller_gate.resolve_identity(bad, "", "", (), [])
        ok(False, "畸形 caller_project %r → raise" % bad[:12])
    except Exception as e:
        ok(bad in str(e), "畸形 caller_project %r… → raise 点名（got: %s…）"
           % (bad[:12], str(e)[:40]))
r = caller_gate.resolve_identity("", "proj-a", "", (), [])
ok(r["src"] == "env" and r["identity_class"] == "declared",
   "env 注入身份解析为 declared src=env（注入链出口面）")
clear_knob()

print("\n== PASS=%d FAIL=%d ==" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
