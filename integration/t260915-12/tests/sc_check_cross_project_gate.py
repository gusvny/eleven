#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_check_cross_project_gate.py — 跨项目写操作闸离线源码锁+微型重放（t260915-12）。

登记：integration/run_scenarios.py SCENARIOS「t260915-12-cross-project-gate」。
跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260915-12/tests/sc_check_cross_project_gate.py

格式沿 sc_check_auto_rework_trace.py 既定模式：workflow 件依赖 temporalio（本环境不可
导入）故**不 import 任何 workflow/activities 模块**——shared/caller_gate 是纯函数层
（模块级零 temporalio 依赖，temporalio 全部函数内延迟导入），可安全真 import：
  A. 常量与形状锁（undeclared 策略单常量=C-0② 翻严锚点、盖章字段带默认=重放安全）
  B. 判定矩阵单点实现源码锁（shared 唯一真源；caller_gate/client/workflow 侧零复制）
  C. 真函数重放正/负/越权/畸形四子用例（含畸形输入子用例——消费外部输入的既定纪律）
  D. client 接闸结构锁（八 op 全闸/retry_qc+update 不盖章分档/cancel 先闸后 terminate）
  E. workflow 第二道落点锁（base 混入+dev_lane 三 handler+旧模板 sign 统一接闸）
  F. ticket.py 包装层锁（仓树排除 cwd 推导=C1/越权旗本层 fail-fast/对账白名单/M2 schema）
  G. run_scenarios 场景登记（t260915-12 双场景）

三态沿工程惯例：PASS exit 0 / FAIL exit 1（本场景无环境依赖，无 ENV_FAIL 形态）。
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "server" / "engine"
TOOLS = ROOT / "server" / "tools"
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
BASE = src_of("server/engine/base.py")
DEVLANE = src_of("server/engine/dev_lane.py")
WF = src_of("server/engine/workflows.py")
INSP = src_of("server/engine/inspection_flow.py")
TICKET = src_of("server/tools/ticket.py")
SHARED = src_of("server/engine/shared.py")
CALLERGATE = src_of("server/engine/caller_gate.py")
RUNSCEN = src_of("integration/run_scenarios.py")

# ---------- A. 常量与形状锁 ----------
section("A 常量与盖章字段形状（C-0② / 重放安全）")
ok(shared.UNDECLARED_POLICY == "refuse",
   "UNDECLARED_POLICY=refuse（t260925-08 翻严缺省；KI-119 收口）")
ok(shared.UNDECLARED_POLICY_ENV == "SANDBAR_UNDECLARED_POLICY"
   and shared.UNDECLARED_POLICIES == ("record", "refuse"),
   "策略旋钮在位：SANDBAR_UNDECLARED_POLICY∈{record,refuse}（畸形=fail-closed）")
ok(shared.CALLER_PROJECT_ENV == "SANDBAR_CALLER_PROJECT", "env 名=SANDBAR_CALLER_PROJECT")
ok(shared.CALLER_UNDECLARED_MARK == "__undeclared__", "undeclared 哨兵值在位")
ok(shared.CROSS_PROJECT_NOTE_LIMIT == 20000 and shared.CROSS_PROJECT_BY_LIMIT == 64,
   "越权旗上限家族（note=20000/by=64，同值不同源独立常量）")
for cls_name in ("Signature", "ReworkRequest", "PauseRequest", "HostRulingRequest"):
    fields = {f.name: f for f in dataclasses.fields(getattr(shared, cls_name))}
    ok(fields.get("caller_project") is not None and fields["caller_project"].default == ""
       and fields.get("cross_project_note") is not None
       and fields["cross_project_note"].default == "",
       "%s 盖章字段在场且默认空（老历史解码兼容）" % cls_name)

# ---------- B. 判定矩阵单点实现 ----------
section("B 判定矩阵单点实现（零复制）")
ok("def cross_project_judge(" in SHARED, "权威判定在 shared.py")
ok(SHARED.count("def cross_project_judge(") == 1, "矩阵实现恰一处")
ok("cross_project_judge" in CALLERGATE and "def judge_caller" in CALLERGATE,
   "client 侧 judge_caller 在 caller_gate（组合 shared 判定+旗面）")
# 三处消费侧都只调用、不复制矩阵（禁第二真源：搜「异项目」等矩阵语义文案的复制面）
ok("decision" in CALLERGATE and "refuse" in CALLERGATE, "caller_gate 消费三态判定")
for name, src in (("client.py", CLIENT), ("base.py", BASE), ("dev_lane.py", DEVLANE),
                  ("workflows.py", WF), ("inspection_flow.py", INSP)):
    ok("cross_project_judge" in src or "_cross_project_gate(" in src
       or "caller_gate" in src,
       "%s 接闸点引用单点实现（无本地矩阵）" % name)

# ---------- C. 真函数重放：正 / 负 / 越权 / 畸形 ----------
section("C 真函数重放（正/负/越权/畸形四子用例）")
# C1 正用例：同项目 / 老未盖章 / 无项目面
ok(shared.cross_project_judge("sandbar", "sandbar", "")["action"] == "allow",
   "正：同项目放行")
ok(shared.cross_project_judge("", "sandbar", "")["action"] == "allow",
   "正：老 client 未盖章=兼容放行")
ok(shared.cross_project_judge("dengzhufpv", "", "")["action"] == "allow",
   "正：无项目面引擎件放行")
ident_same = caller_gate.resolve_identity("sandbar", "", projects=[])
v_same = caller_gate.judge_caller(ident_same, "sandbar", None)
ok(v_same["decision"] == "pass" and v_same["stamp"] == "sandbar", "正：client 侧同项目 pass")

# C2 反用例：异项目无旗=两层一致拒收+人话点名
g_neg = shared.cross_project_judge("dengzhufpv", "sandbar", "")
ok(g_neg["action"] == "refuse" and "dengzhufpv" in g_neg["why"]
   and "sandbar" in g_neg["why"], "负：workflow 侧拒收点名双项目")
v_neg = caller_gate.judge_caller(caller_gate.resolve_identity("dengzhufpv", ""), "sandbar", None)
ok(v_neg["decision"] == "refuse" and "dengzhufpv" in v_neg["why"]
   and "sandbar" in v_neg["why"], "负：client 侧拒收点名双项目")
v_und = caller_gate.judge_caller({"value": "", "src": "none",
                                  "identity_class": "undeclared"}, "sandbar", None)
ok(v_und["decision"] == "refuse" and shared.CALLER_PROJECT_ENV in v_und["why"],
   "负（t260925-08 翻严缺省）：undeclared=拒收且 why 点名缺失身份 env")
ok(shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "sandbar", "",
                              policy="record")["action"] == "allow_record",
   "record 旋钮路径真实存在：policy=record 时哨兵记名放行（显式选入的过渡策略）")

# C3 越权子用例：旗→放行+记名（by/reason 原文入账；note 截断 300）
g_flag = shared.cross_project_judge("dengzhufpv", "sandbar", "宿主代管收口")
ok(g_flag["action"] == "allow_record" and g_flag["record"]["caller_project"] == "dengzhufpv"
   and g_flag["record"]["note"] == "宿主代管收口", "越权：workflow 侧记名放行且原文入账")
ov = caller_gate.validate_override({"cross_project": {"by": "宿主", "reason": "代管"}})
v_flag = caller_gate.judge_caller(caller_gate.resolve_identity("dengzhufpv", ""), "sandbar", ov[0])
ok(ov == ({"by": "宿主", "reason": "代管"}, "") and v_flag["decision"] == "pass_override"
   and v_flag["override_used"] is True and "宿主" in v_flag["notice"],
   "越权：client 侧 pass_override+notice 带 by")
g_big = shared.cross_project_judge("dengzhufpv", "sandbar", "x" * 5000)
ok(g_big["action"] == "allow_record" and len(g_big["record"]["note"]) == 300,
   "越权：note 入账截断 300（防巨物进 meta）")

# C4 畸形子用例（消费外部输入的畸形用例纪律）
ok(caller_gate.validate_override({}) == (None, ""), "畸形：无旗=无旗（非错误）")
for bad, frag in (({"cross_project": {"reason": "r"}}, "by"),
                  ({"cross_project": {"by": "x"}}, "reason"),
                  ({"cross_project_reason": "r"}, "by"),
                  ({"cross_project": {"by": "x" * 65, "reason": "r"}}, "超限"),
                  ({"cross_project": {"by": "x", "reason": "r" * 20001}}, "超限")):
    got, err = caller_gate.validate_override(bad)
    ok(got is None and frag in err, "畸形旗拒收：%s…→%s" % (list(bad)[0][:28], err[:24]))
got, err = caller_gate.validate_override({"cross_project": ["by", "reason"]})
ok(got is None and "对象" in err, "畸形：旗=非对象（list）拒收")
got, err = caller_gate.validate_override(
    {"cross_project": {"by": "a", "reason": "r"}, "cross_project_reason": "dup"})
ok(got is None and "只给其一" in err, "畸形：双形理由同给=拒收")
for bad_id in ("SANDBAR", "x" * 65, "../evil", "a b", ""):
    try:
        caller_gate.resolve_identity(bad_id, "", projects=[])
        raised = bad_id == ""  # 空串=视同未声明，不 raise（audit 同款口径）
    except caller_gate.CallerIdentityError:
        raised = True
    ok(raised, "畸形身份 %r：形状白名单拦住（空串=视同未声明）" % bad_id[:16])
ok(shared.project_key_for_dir("/repox", [{"key": "sandbar", "dirs": ["/repo"]}], ("/repo",)) == "",
   "畸形路径：前缀混淆 /repox 不因 /repo 误命中")
ok(shared.project_key_for_dir("/repo/a/b", [{"key": "sandbar", "dirs": ["/repo"]}], ("/repo",)) == "",
   "C1：仓内任意深度子目录不推导（整树排除，非仓根等值）")

# ---------- D. client 接闸结构锁 ----------
section("D client 接闸结构锁（八 op 全闸 / 分档 / cancel 三态）")
m_gated = re.search(r"_GATED_TICKET_OPS\s*=\s*\(([^)]*)\)", CLIENT)
gated_ops = set(re.findall(r'"([a-z_-]+)"', m_gated.group(1))) if m_gated else set()
ok(gated_ops == {"sign", "authorize", "rework", "retry_qc", "ruling",
                 "pause", "resume", "update"},
   "写 op 闸集合恰为八 op（实测 %s）" % sorted(gated_ops))
m_unstamped = re.search(r"_UNSTAMPED_NOTICE_OPS\s*=\s*\(([^)]*)\)", CLIENT)
unstamped = set(re.findall(r'"([a-z_-]+)"', m_unstamped.group(1))) if m_unstamped else set()
ok(unstamped == {"retry_qc", "update", "cancel", "ticket-start"},
   "不盖章 op 分档恰为四（C3 诚实残留，实测 %s）" % sorted(unstamped))
for op, win in (("sign", 700), ("authorize", 2600), ("rework", 700), ("ruling", 700)):
    pat = r'op == "%s".{0,%d}?caller_project=gate\["stamp"\]' % (op, win)
    ok(re.search(pat, CLIENT, re.S) is not None, "%s 载荷盖章下发（caller_project=stamp）" % op)
ok(re.search(r'op in \("pause", "resume"\).{0,900}?caller_project=gate\["stamp"\]',
             CLIENT, re.S) is not None, "pause/resume 载荷盖章下发（共用分支）")
ok('caller_project=gate["stamp"] if gate else ""' in CLIENT, "盖章缺省=空串（未闸兼容形）")
ok("gate = await _write_gate(handle, tid, args)" in CLIENT, "闸前置唯一入口在位")
ok("record_undeclared" in CLIENT and "仅在 admin.log" in CLIENT,
   "C3 分档：不盖章 op 的 notice 说实话（记名只在 admin.log）")
ok("_gate_receipt(_ok(" in CLIENT, "成功回执统一并身份键")
ok(re.search(r"async def cmd_cancel.*?validate_override.*?describe\(\).*?"
             r"PROJECT_SA_NAME.*?judge_caller.*?terminate", CLIENT, re.S) is not None,
   "cancel：旗校验→describe 前置→judge→terminate（先闸后终结）")
ok("未执行任何动作" in CLIENT and "KIND_TRANSIENT" in CLIENT,
   "cancel/快照瞬时失败=结构化拒收不放行（C2① KI-025 口径）")
ok("_is_not_found_exc" in CLIENT, "not_found/transient 分级复用既有判定")
ok("identity_class=\"engine-internal\"" in CLIENT, "无项目 SA 引擎件=engine-internal 记名放行")
ok("（目标票 %s，属项目 %s）" in CLIENT, "拒收文案点名目标票号+项目")
ok("resolve_identity" in CLIENT and "exclude_trees=(os.path.realpath(str(REPO_ROOT)),)"
   in CLIENT, "client 身份解析带仓树排除（C1）")
ok("load_projects_registry" in CLIENT, "注册表装载注入（cwd 兜底数据源）")

# ---------- E. workflow 第二道落点 ----------
section("E workflow 第二道落点（混入 + 三模板统一）")
ok("class TicketCrossProjectMixin" in BASE, "base.py 闸混入在位")
ok("class TicketWorkflowBase(TicketPauseMixin, TicketCrossProjectMixin):" in BASE,
   "TicketWorkflowBase 双混入")
# 260928 修：类声明由单行字面量改为「含这两个混入（允许续行/允许再加混入）」——
# t260928-13 给 DevLaneWorkflow 加了 TicketEventLedgerMixin（事件台账接线）后，
# 原单行字面量判据必然长红。意图不变：DevLaneWorkflow 必须同时接暂停混入与跨项目混入。
_dl_decl = DEVLANE[DEVLANE.index("class DevLaneWorkflow"):DEVLANE.index("class DevLaneWorkflow") + 200]
ok("TicketPauseMixin" in _dl_decl and "TicketCrossProjectMixin" in _dl_decl,
   "DevLaneWorkflow 双混入（容许额外混入与续行）")
ok(DEVLANE.count("_cross_project_gate(") - DEVLANE.count("def _cross_project_gate(") == 3,
   "dev_lane 三落点（sign/rework/host_ruling，实测 %d 处调用）"
   % (DEVLANE.count("_cross_project_gate(") - DEVLANE.count("def _cross_project_gate(")))
ok(BASE.count("_cross_project_gate(") - BASE.count("def _cross_project_gate(") == 6,
   "base 六落点（sign/rework/pause/resume/cancel_notice + **close_out_notice**=260928 宿主令④"
   "的人工记名收口，与 cancel_notice 同款过闸，实测 %d 处调用）"
   % (BASE.count("_cross_project_gate(") - BASE.count("def _cross_project_gate(")))
ok("def _cross_project_gate(self" in BASE and "cross_project_judge(" in BASE,
   "混入体消费单点判定（base 不自带矩阵）")
ok('rec.update({"ts": self._now_epoch(), "op": op, "by": who})' in BASE,
   "记名条目带 ts/op/by（by=信号 who 原文，对账面列得出谁在动）")
ok('rec["reason"] = rec.get("note", "")' in BASE,
   "记名条目带 reason 键（对账面词=reason，与场景/README 契约同词；note 保留为 shared 层词）")
ok('"cross-project-recorded"' in BASE, "timeline 记名事件在位")
ok("cross_project_judge" in WF,
   "旧模板族 sign 统一接闸（260904 退役模板与在役面同过闸，源码锁同款判定）")
ok("cross_project_judge" in INSP, "旧模板 inspection sign 统一接闸")
ok("PAUSE_PATCH_ID" in BASE and BASE.index("workflow.patched(PAUSE_PATCH_ID)")
   < BASE.index('"pause", who, "pause")'),
   "pause 的 R4 patched 分支优先级保留（老实例兼容先于闸）")

# ---------- F. ticket.py 包装层 ----------
section("F ticket.py 包装层（身份推导 / 越权旗 / 对账面 / M2 schema）")
ok("def _resolve_caller" in TICKET and "project_key_for_dir" in TICKET
   and "os.path.realpath(str(s.REPO_ROOT))" in TICKET,
   "包装层身份推导=同一排除口径（C1：仓树内不推导）")
ok("def _cross_project_flag" in TICKET and "CROSS_PROJECT_NOTE_LIMIT" in TICKET,
   "越权旗本层 fail-fast（形状/必填/上限，与 client 同族校验）")
ok("_write_op_poc('ticket', payload, a)" in TICKET
   and "_write_op_poc('ticket-start', payload, a)" in TICKET,
   "写 op 统一出口（ticket/ticket-start 两入口同走）")
ok("def _poc(subcmd, payload, caller=None)" in TICKET
   and "s.CALLER_PROJECT_ENV" in TICKET, "_poc env 注入身份（spawn 链出处）")
ok(TICKET.count("_write_op_poc(") - 1 == 10,
   "写面统一出口恰 10 调用点（rework/sign/retry_qc/authorize/ruling/update/ticket-start + "
   "pause|resume 共用一处 + ticket-cancel：t260922-10（bf85990）按设计补的 cancel 接闸"
   "走同一出口，260923 A 清账登记同步；ruling=F2 收口补的包装层出口，与 schema enum "
   "宣告对齐；**ticket-close-out**=260928 宿主令④（人工记名收口，与 ticket-cancel 同款"
   "who+reason 必填、_write_gate 过闸、close_out_notice 信号留痕后 terminate）——本计数"
   "存在的意义就是逼每新增一个写入口都来这条断言登记一次，实测 %d）"
   % (TICKET.count("_write_op_poc(") - 1))
ok("'cross_project_uses'" in TICKET, "对账白名单 cross_project_uses 在 _v2_query")
ok("'caller_project'" in TICKET and "'cross_project'" in TICKET
   and "'cross_project_reason'" in TICKET, "M2 schema：身份参数+越权旗双形入 schema")
ok(re.search(r"'authorize',\s*'ruling'", TICKET) is not None,
   "M2 schema：op enum 补 authorize|ruling")

# ---------- G. 场景登记 ----------
section("G run_scenarios 登记（双场景）")
ok("t260915-12-gate-real-chain" in RUNSCEN, "真链路场景已登记")
ok("t260915-12-cross-project-gate" in RUNSCEN, "离线源码锁场景已登记")
ok("sc_check_cross_project_gate.py" in RUNSCEN, "登记指向本脚本")

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
