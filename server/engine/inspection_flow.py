"""inspection_flow — the inspection ticket skeleton (inspection epic ticket 1,
t260905-03).

A lightweight inspection ticket template: scan → report → human gate → close (no plan /
implement stages). One ticket per period: the period key = instance id + current date,
the ticket id is the workflow id (inspection-<instance>-<period>), and a repeated trigger
with the same ticket id is rejected by the server's AlreadyStarted — that is the
mechanical guarantee of one ticket per period (overlap semantics SKIP, borrowed from
trade-off list item 1; a ticket opens even on an all-green run — a zero-finding ticket is
the heartbeat proof).

Red line (carried on every ticket-face posting): inspection only produces reports and
ticket-opening suggestions, it never modifies code directly; every fix goes through a
dev-lane ticket that references the inspection ticket (source_inspection=<inspection
ticket id>).

Human gate (M3): reuses the existing ticket approval-gate machinery — signal sign with a
Signature payload (shared.Signature: who is injected by the caller, agents may not sign
for themselves); this template only defines its own gate id (inspection-close). Closing
is unreachable before approval (stage_state=awaiting-human really blocks) and happens
only after it.

Determinism discipline: the workflow body does zero IO and zero wall-clock (only
workflow.now()); every side effect lives in an activity (run_inspection_inspect /
verify_inspection_findings / write_inspection_report / write_inspection_verdicts, thin
shells in activities.py / agent_activities.py; the retired static scan
run_inspection_scan remains only on the legacy replay path — t260916-22).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time

# 260927 code_stamp（同 agent_activities）：本模块的 worker 载入时刻
import datetime as _dt_code
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from temporalio import workflow
from temporalio.common import RetryPolicy

# shared's module top has Path.resolve/environ (non-deterministic), so inside a workflow
# context this import must be passed through per repo convention (same as workflows.py's
# header), otherwise the sandbox validation goes red.
with workflow.unsafe.imports_passed_through():
    from shared import Signature, cross_project_judge, PROJECT_SA_NAME

# t260913-02：复用面（与 base.py/dev_lane.py 同款——imports_passed_through 内引活动函数，
# 让 dataclass 载荷/回执的类型提示在沙箱里正确解码；活动实现本身全在 agent_activities）。
with workflow.unsafe.imports_passed_through():
    from agent_activities import prepare_workspace, teardown_lane, merge

    from shared import MergeArgs, WorkspacePrep

CLOSE_GATE_ID = "inspection-close"
INSPECTION_RED_LINE = ("Inspection only produces reports and ticket-opening suggestions; it never "
                       "changes code. Every fix goes through a dev-lane ticket.")
# Agents may not sign for themselves (reusing Signature semantics): the human gate's who
# must not be one of the M10 five agent role names.
AGENT_ROLE_NAMES = frozenset({"developer", "integration", "ops", "product-operation", "artist"})
# 期号两形态（t260911-02 接线 every-n-tickets/race-first）：cron 期=纯 YYYYMMDD；
# 计数期=YYYYMMDD-<bucket>（同日多期可区分；一票一期按（实例,期号）去重不变）。
PERIOD_RE = re.compile(r"^\d{8}(-[1-9]\d*)?$")
MAX_WHO_LEN = 64

RETRY = RetryPolicy(maximum_attempts=3)
SHORT_TO = timedelta(minutes=5)
SCAN_TO = timedelta(minutes=15)
# 套件阶段 start_to_close（t260924-05 KI-116 单源化）：自 agent_activities.INTEG_GUARD_SEC
# （=内层批次 BATCH_TIMEOUT_SEC+300 守卫，唯一算出点）**派生**=守卫 + 1800s 巡检余量
# （恒全跑、不经池排除，全集比每票集测长，余量给 30min）——内层结构化超时回报必先于
# Temporal 硬杀可达；运维覆盖 SANDBAR_INTEG_BATCH_TIMEOUT_SEC 时自动同抬（旧写死
# 120min 形同虚设，且旧头注「默认 5400+300=5700s」与常量真值 3300s 不符——撒谎注释
# 随单源化一并清零）。缺省 3300+1800=5100s≈85min。不等式组由
# test_t260913_01_integ_budget_pair.py 与 test_t260924_05_ki116_budget.py 机械锁定。
with workflow.unsafe.imports_passed_through():
    from agent_activities import INTEG_GUARD_SEC
# t260928-20：事件账本发射 mixin（机制全在 base.TicketEventLedgerMixin；本文件只接线
# ——入队点=各 _enter 单一写点，冲刷点=长等待/人门/收口/_blocked 前的异步边界）。
with workflow.unsafe.imports_passed_through():
    from base import TicketEventLedgerMixin
# 260927 套件段三段预算（宿主实测校准；单一算出点全在本区块，锁测试=budget 文件）：
#
#  ① 供给上限 INTEG_SUPPLY_TO_SEC（integration.supply：daemon-probe + `stage_docker
#     ensure --services full`）——实测 ≈40min（活动 23:41:19 派出 → 跑者 integration.cmd
#     约 08:21 才启动）。给 3600s（60min，实测 + 余量）。它是**独立具名预算**：到点/失败
#     返回点名「供给段」的红，绝不与跑者的场景预算混成一笔（混成一笔就会互相吃，正是
#     t260927-01 的病根：供给 40min + 跑者 47min = 87min > 活动超时 85min，活动在跑者
#     差约 2 分钟收尾时被判死，随即拆泳道、孤儿写盘撞 ENOENT、迟到回执覆盖权威件）。
#  ② 跑者总预算 SUITE_RUN_BUDGET_SEC（套件本体）——实测 319 场景 sum(wall_s)=2630s
#     （≈44min），最慢单场景 310s，量化基线 179~2834s 波动。缺省按算式（下）得 5400s
#     （90min，实测 2× 余量，给并发抖动与长尾场景）；下限硬钉 MIN_SUITE_RUN_BUDGET_SEC
#     =5400s：运维把 SANDBAR_INTEG_BATCH_TIMEOUT_SEC 往**小**调时预算不许跟着缩到截断真
#     套件的地步（往大调则自动同抬——算式在，人守纪律退役）。
#  ③ 活动超时 SUITE_TO = 供给上限 + 跑者总预算 + 余量 SUITE_MARGIN_SEC（600s：跑者收口
#     打印 + 闸解析 + 活动确认泳道并写盘）。缺省 3600+5400+600=9600s（160min）。
#
# 三条不等式（锁测试 test_t260924_05_ki116_budget.py 新增断言，旧断言只加不减）：
#   INTEG_GUARD_SEC < 跑者总预算 < SUITE_TO
#   供给上限 + 跑者总预算 + 余量 ≤ SUITE_TO
#   （另有：跑者总预算 < 子进程链截止 < SUITE_TO，见 integ_subprocess_timeout。）
INTEG_SUPPLY_TO_SEC = 3600.0          # 供给段上限（env SANDBAR_SUPPLY_TIMEOUT_SEC 同名单点）
MIN_SUITE_RUN_BUDGET_SEC = 5400.0     # 跑者总预算下限（实测 2630s 串行 + 并发/抖动余量）
SUITE_MARGIN_SEC = 600.0              # 活动超时相对「供给+跑者」的余量


def suite_run_budget_of(guard_sec: float = INTEG_GUARD_SEC) -> float:
    """跑者侧总预算算式（唯一算出点；单测直调）：派生自内层守卫，落地下限。

    算式 `2×guard = 2×(BATCH+300)`：运维抬 SANDBAR_INTEG_BATCH_TIMEOUT_SEC 时预算自动
    同抬（旧写死值的病根清零）。floor 到 MIN_SUITE_RUN_BUDGET_SEC：守卫被调小时预算不
    缩水（截断真套件 ≠ 预算纪律）。"""
    return max(2.0 * float(guard_sec), MIN_SUITE_RUN_BUDGET_SEC)


def suite_timeout_of(supply_sec: float = INTEG_SUPPLY_TO_SEC,
                     run_budget_sec: Optional[float] = None,
                     margin_sec: float = SUITE_MARGIN_SEC) -> float:
    """活动超时算式（唯一算出点；单测直调）= 供给上限 + 跑者总预算 + 余量。

    三者必须同源派生（供给与跑者各是**独立具名预算**，活动超时是它们的上界）——任何
    一处手写都会重新长出「活动比实际需要更早判死」的错配。"""
    budget = suite_run_budget_of() if run_budget_sec is None else float(run_budget_sec)
    return float(supply_sec) + budget + float(margin_sec)


# 跑者总预算（workflow 下单给活动 → 活动经 env 下发给执行器）
SUITE_RUN_BUDGET_SEC = suite_run_budget_of()
# 套件阶段 start_to_close（旧注记 t260924-05 KI-116 单源化保留在下方）：自供给上限与跑者
# 总预算**派生**=两者之和 + 巡检余量（恒全跑、不经池排除，全集比每票集测长）。
# 缺省 3600+5400+600=9600s≈160min（旧值 5100s≈85min 被实测 87min 击穿——见上方①）。
SUITE_TO = timedelta(seconds=suite_timeout_of(INTEG_SUPPLY_TO_SEC, SUITE_RUN_BUDGET_SEC))
# 跑者总预算余量（套件段超时修复，260927 实况）：跑者必须在活动判死之前**自行收口**，
# 余量给三段：跑者收口打印 + 闸解析 + 活动确认泳道并写盘。
SUITE_RUN_MARGIN_SEC = 600.0


def suite_run_budget_sec(timeout_sec: float = None,
                         margin_sec: float = SUITE_RUN_MARGIN_SEC) -> float:
    """跑者总预算（与 SUITE_TO 同一算出点；给需要显式投影的调用方）。

    缺省（timeout 未给）=模块级 SUITE_RUN_BUDGET_SEC——**单一真源**：算式改了这里跟着
    改，调用方不重算。显式传 timeout 的旧调用面保留（`timeout − margin`），仅作投影。"""
    if timeout_sec is None:
        return float(SUITE_RUN_BUDGET_SEC)
    return float(timeout_sec) - float(margin_sec)
# 套件活动不自动重试：整轮全集重跑代价高（小时级），且「跑不成/跑红」本身就是票面数据
# （进发现清单+回执，人审/次日再跑），Temporal 重试只会把同一份失败重复烧一遍墙钟。
RETRY_SUITE = RetryPolicy(maximum_attempts=1)
# 套件段硬超时后的拆泳道宽限（必做④「teardown 不得与仍在跑的活动抢目录」）：Temporal
# 判死活动时**子进程链不被回收**（活动被杀≠孙进程死），立刻拆泳道会让孤儿进程写盘时
# 撞 ENOENT，产出误导回执。故超时分支先等这一小段（给跑者自己到点收口的时间窗），再拆。
SUITE_TIMEOUT_TEARDOWN_GRACE = timedelta(seconds=120)
# inspect 段不自动重试（t260916-22）：重试=重烧一次 LLM 配额，且「agent 未完成/输出
# 不合格」本身就是票面数据（blocked 可见、下期再来）——同 RETRY_SUITE 纪律。
RETRY_INSPECT = RetryPolicy(maximum_attempts=1)
# 漏跑核查回看窗口（天）：每日 cron 一周内应有 7 期；窗口外不追历史（漏报的收敛靠每期
# 滚动核查，靠窗口覆盖，不靠一次翻旧账）。
DEADMAN_LOOKBACK_DAYS = 7
# 版本门 id（t260913-02，replay 安全）：新增的「声明决议 + setup/suite 阶段 + 人门落账」
# 只在新 run 生效；老在途票（票①② 起的 RUNNING 实例，如 260910/260911 的
# inspection-test-face-* / inspection-mechanism-face-*）history 里没有该标记 → 走票①
# 旧路径重放，**绝不注入新命令**（否则 Temporal replay 非确定 → workflow task 永久失败、
# 老票卡死）。repo 先例=base.py 的 PAUSE_PATCH_ID / BREATHE_PATCH_ID；机器化验证=
# replay_check.py --workflow <老票 id>（本票实测四张在途老票全绿）。
SUITE_PATCH_ID = "t260913-02-inspection-suite-stage"
# 版本门 id（t260915-20，replay 安全）：无主票守卫 + sign 闸项目面收紧只在新 run 生效。
# 老 in-flight 票 history 无此标记 → patched()=False → 走旧路径（恒放行），零影响；
# 新票双空判据见 run 内守卫（README 迁移步：旧调度 payload 撞守卫=可见 blocked）。
PROJECT_PATCH_ID = "t260915-20-inspection-project-identity"
# 版本门 id（t260916-22，replay 安全）：inspect 段（agent 审查）替代 scan 段（静态扫描）
# 只在新 run 生效——run() 的分派判据=SUITE 门 **且** INSPECT 门（本票上线瞬间在途的
# SUITE 票 history 无 INSPECT 标记，继续走旧路径重放到收口，绝不中途换轨）。
INSPECT_PATCH_ID = "t260916-22-inspection-inspect-stage"
# inspect 段 start_to_close = 声明预算 + 双闸余量：活动内部 deadline=预算−60s（先超时
# 并把进程组收干净、回执「agent 未完成」），Temporal 侧再给 120s 兜底余量——Temporal
# 必须晚于内部闸死（SUITE_TO 头注同款纪律；不等式 UT 锁定）。
INSPECT_TO_EXTRA_SEC = 120.0


def inspect_start_to_close(timeout_sec: float) -> timedelta:
    """inspect 段活动 start_to_close（预算 + 兜底余量）。"""
    return timedelta(seconds=float(timeout_sec) + INSPECT_TO_EXTRA_SEC)
# 版本门 id（t260917-02，replay 安全）：旧调度 action 直发的非 t 形 fire 自愈重定向
# （spawn_inspection_period → open_period_ticket 铸 t 形票承接）只在新 run 生效。老
# in-flight 票（含 260917 的 awaiting-human 旧形壳）history 无此标记 → patched()=False
# 走旧路径收口，零影响。机器化验证=replay_check.py --workflow <老票 id>（S4 自测实测）。
REDIRECT_PATCH_ID = "t260917-02-inspection-legacy-fire-redirect"
# 版本门 id（260926，replay 安全）：lane/watchdog 面（**只读**扫非终态票的工作流时间线/
# 快照——同票重跑轮次 / tests-fault 回路停留 / 在飞静默僵尸；KI-122 追加面，KI-126 同源）
# 只在新 run 生效。老 in-flight 巡检票 history 无此标记 → patched()=False → 不注入新活动
# 命令（否则 Temporal replay 非确定 → workflow task 永久失败、老票卡死）；repo 先例=上述
# 四门同形。门求值点在 run 直线上（无 KI-061 式唤醒重放路径），不需 #seq 后缀。
LANE_WATCHDOG_PATCH_ID = "inspection-lane-watchdog-v1"
# 版本门 id（260929，replay 安全）：setup 段「泳道路径被本期残留占住 → 定向清本期残留
# （sweep remove_period=本期）→ 重试一次 prepare」只在新 run 生效。理由同上述各门：
# 老 in-flight 票（含 260926 重开实案 t260927-02：prepare 失败即 blocked）history 里
# 没有该标记 → patched()=False → 走旧路径**绝不注入新活动命令**（否则 replay 非确定 →
# workflow task 永久失败、老票卡死）。机器化验证=replay_check.py --workflow <老票 id>。
LANE_REPAIR_PATCH_ID = "inspection-lane-residue-repair-v1"
# 版本门 id（260929 补门，replay 安全）：套件段硬超时后的「拆泳道前 120s 宽限等待」
# （260927 直修 49b157a 引入 SUITE_TIMEOUT_TEARDOWN_GRACE，**当时漏了版本门**）。
# 后果实证：t260927-01（超时发生在加 sleep 之前）重放时「代码要定时器、history 是
# 活动」→ NondeterminismError，该票任何重放面全红（replay_check 实测；改前 HEAD
# 同样红＝与别的改动无关）。补门修正：老 history 无此标记 → 跳过等待（与其记录的序列
# 逐字一致）；新 run 记录标记后照旧等。存量实证：全量巡检 history 无一处带该定时器
# （六期逐条查过），故本门对存量零代价。
SUITE_TEARDOWN_GRACE_PATCH_ID = "t260927-inspection-suite-teardown-grace"
# lane/watchdog 面预算（260926）：活动内部自设扫描总预算（有界——在册非终态票可能上百张，
# 没有 worker 应答的僵尸票每次 query 都要等到超时）；Temporal 侧 start_to_close 必须**晚于**
# 内部预算，否则 Temporal 先杀、活动自己的「预算用尽」收口永远跑不到（SUITE/INSPECT 双闸
# 同款纪律，不等式由 UT 锁定）。只一次尝试（重试会把这张面翻倍，且失败本身已具名上票面）。
WATCHDOG_SCAN_BUDGET_SEC = 90.0
LANE_WATCHDOG_TO = timedelta(seconds=WATCHDOG_SCAN_BUDGET_SEC + 60)
RETRY_LANE_WATCHDOG = RetryPolicy(maximum_attempts=1)

with workflow.unsafe.imports_passed_through():
    from inspection_ticketing import has_ticket_id_shape


def legacy_fire_redirect_reason(ticket_id: str) -> str:
    """重定向守卫判据（纯函数，t260917-02 修复①）：workflow id 非 t 形 → 返回可读事由；
    t 形 → ""（正常票零影响）。

    260917 实况：旧调度 action（t260916-02 迁移前代 schedule-up 所铸）直发长跑
    workflow，服务端给 fire id 追加 `-<fire时刻UTC>` 后缀——票面 ticket_id=workflow id
    本身、无实例/期 SA，票形双缺陷全占。守卫认出「非 t 形 fire」即改道起票单点
    （open_period_ticket）铸 t 形票承接，本壳即返——消除双形（与手动路径同一入口）。

    判别单点=has_ticket_id_shape（**形状**判别，全工单票共形，非巡检票身份判别——
    语义圈死见该函数 docstring）。"""
    if has_ticket_id_shape(ticket_id):
        return ""
    return ("票号非 t 形（workflow id=%s 直当票号）——调度 action 未指向 spawner"
            "（t260916-02 接线未生效：重跑 schedule-up 刷新 action）；本票改由"
            " open_period_ticket 铸 t 形票承接" % (str(ticket_id or "") or "<空>"))


def unowned_guard_reason(project_key: str, repo_root: str) -> str:
    """无主票守卫判据（纯函数，t260915-20；单测两分支）：
    项目身份与 repo_root **双空** → 返回 blocked 事由（点名「无项目身份」与处置入口）；
    否则返回 ""（放行）。双空=旧调度 payload/旁路起票的残窗形态——有身份的票
    （repo_root 无论如何都会由起票面解析定死）照常放行；显式 --repo-root 旁路但无
    身份的票不在此拦（运维显式面，可见性缺口由行 project 空承载，不静默成有主）。
    repo_root 有值即说明起票面已经走过解析链（引擎仓静默回落被 R1 修复+守卫杀尽）。"""
    if str(project_key or "").strip():
        return ""
    if str(repo_root or "").strip():
        return ""
    return ("无项目身份（旧调度 payload/旁路起票，无 project_key 且无 repo_root）——"
            "票既无归属也无法判扫描仓，绝不静默回落引擎仓扫描；"
            "处置：重跑 inspection_trigger.py schedule-up --instance <id> --note <…>"
            "（update 分支重铸 action 即带身份）")


def sign_target_project(sa_project: str, payload_project: str) -> str:
    """sign 闸 target 解析链（纯函数，t260915-20；单测三分支）：
    本票 SA ProjectKey（起票时刻盖章，调度序无关、重放确定）优先；
    回退 payload project_key（老 history 无 SA）；双空 → ""（cross_project_judge 对
    空 target 恒放行=现状语义，代码注释预告的升级路径在这里闭环）。"""
    sa = str(sa_project or "").strip()
    if sa:
        return sa
    return str(payload_project or "").strip()


# ========================================================================================
# Pure logic (the unit-test surface): period keys / ticket ids / face rendering /
# signature validation / posting
# ========================================================================================

def period_key(now: Optional[datetime] = None) -> str:
    """Period key = the current date (YYYYMMDD) — the cron-period form. Count periods
    (YYYYMMDD-<bucket>) are minted by the ticket-count watcher
    (inspection_ticket_count.decide / count_period)."""
    dt = now or datetime.now()
    return dt.strftime("%Y%m%d")


def now_in_tz(now: datetime, tz_name: str = "") -> datetime:
    """把时刻换算到**声明时区的挂钟时间**（naive 返回；t260913-02 验收 P1 单点）。

    tz 空 = 原样返回（旧口径：票① 与未声明 tz 的实例按进程/UTC 日历，行为不变）；
    tz 无法解析（zoneinfo 数据缺失等环境面）= 原样返回——**铸号与漏跑核算走同一条
    回落链**，两侧永不换基（P1 的本质就是两侧基不同）。时区存在性由声明词法闸
    （TZ_RE）+ schedule-up/plan 的 Temporal 侧拒绝兜底，不在本函数静默猜。"""
    if not tz_name:
        return now
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001——环境面回落；两侧同链，基恒一致
        return now


def period_key_in_tz(now: datetime, tz_name: str = "") -> str:
    """声明时区口径的期号（t260913-02 验收 P1）：workflow.now() 是 **UTC**，而声明
    `tz` 后的触发时刻会落在 UTC 的前一日（07:30 Asia/Shanghai = 前一日 23:30Z）——
    期号必须按**声明时区的日历日**取，否则调度票期号恒比本地日历早一天，dead-man
    的期望键（同口径）恒等于「当期自己」→ 每张日报票一条 high 假漏跑 + CLI 每天
    exit=1（验收走查第 8 轮 P1 实锤 + 18 天稳态模拟）。
    tz 空/无法解析 = 旧口径（UTC/进程日历，票① 行为不变；两侧同回落链，基恒一致）。"""
    return now_in_tz(now, tz_name).strftime("%Y%m%d")


def validate_period_key(instance_id: str, period: str) -> None:
    """期号形状闸（t260916-02 起）：票号=workflow id（t 形，起票侧铸号，见
    inspection_ticketing.open_period_ticket），workflow 体不再铸造票号——但期号仍是
    去重键/台账键，体内在铸期回落分支后照旧闭式校验（形状非法=ValueError，与旧铸号
    校验同语义，replay 面对合法期零影响）。"""
    if not instance_id or not PERIOD_RE.match(period or ""):
        raise ValueError("票号组成非法：instance=%r period=%r（期号须 YYYYMMDD 或 "
                         "YYYYMMDD-<bucket>）" % (instance_id, period))


def inspection_ledger_name(instance_id: str, period: str) -> str:
    """台账/套件回执文件名单点（t260916-02）：`inspection-<实例>-<期>[-suite].json`。

    这是**键名约定不是票号**（票号已 t 形化）：deadman 台账扫描按文件名反解实例/期号
    （inspection_deadman.LEDGER_NAME_RE），键名稳定=漏跑核查零改动。老票重放同名——
    旧实现恰好就是这个名字（旧票号=旧形 id=实例+期），逐字节不变。"""
    if not instance_id or not PERIOD_RE.match(str(period or "")):
        raise ValueError("落账名组成非法：instance=%r period=%r（期号须 YYYYMMDD 或 "
                         "YYYYMMDD-<bucket>）" % (instance_id, period))
    return "inspection-%s-%s.json" % (instance_id, period)


def watcher_workflow_id(instance_id: str) -> str:
    """watcher workflow id（C-2，review_plan gen1 条件项）：id 从声明确定导出——同声明
    重跑 schedule-up 必命中同一 workflow（幂等拉起/复活的前提）。形状变更=运维契约
    变更，须带单测锁定（test_t260911_02_watcher.py）。"""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        raise ValueError("watcher id 组成非法：instance=%r（小写 slug）" % instance_id)
    return "inspection-watcher-%s" % instance_id


# ---- t260913-02：巡检自有泳道命名空间（不复用开发泳道 .lane/t<date>-<alias> / lane/...）----

INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
#: 巡检泳道目录名前缀（sweep/清场的命名空间闸：只认这个前缀，开发泳道一律不碰）。
LANE_DIR_PREFIX = "inspection-"
#: 巡检分支命名空间（branch 形如 inspection/<实例>/<期>）。
LANE_BRANCH_NS = "inspection/"


def inspection_lane_name(instance_id: str, period: str) -> str:
    """泳道目录名 = inspection-<实例>-<期>（扁平一级，父目录=`.lane`）。

    扁平是刻意的：`agent_activities._lane_repo_root` 按 `<repo>/.lane/<id>` 路径约定
    自锚定（cwd.parent.name == ".lane"），再深一层就落回 REPO_ROOT 回落分支；
    扁平同时保证与开发泳道 `.lane/t<date>-<alias>` 前缀零交集（命名空间隔离的机械面）。"""
    if not INSTANCE_ID_RE.match(str(instance_id or "")):
        raise ValueError("invalid instance id (lane namespace): %r" % instance_id)
    if not PERIOD_RE.match(str(period or "")):
        raise ValueError("invalid period (lane namespace): %r" % period)
    return "%s%s-%s" % (LANE_DIR_PREFIX, instance_id, period)


def inspection_lane_paths(instance_id: str, period: str,
                          repo_root: str = "") -> Tuple[str, str]:
    """(worktree 路径, 分支名)：巡检实例/期 → 自己的泳道坐标（纯函数，可离线单测）。

    repo_root 给定时出绝对路径（跨项目/隔离台用）；空则出相对 `.lane/<名>`（由活动侧
    按 REPO_ROOT 落地，与开发泳道同款回落语义）。基点（base_ref）不在这里——它是
    「开跑时 main 的 HEAD」，由 resolve_main_head 活动取，作为本期证据进票面。"""
    name = inspection_lane_name(instance_id, period)
    root = str(repo_root or "").rstrip("/")
    worktree = ("%s/.lane/%s" % (root, name)) if root else (".lane/%s" % name)
    return worktree, "%s%s/%s" % (LANE_BRANCH_NS, instance_id, period)


#: 「泳道路径被占」的机器可辨标记：prepare_workspace 的 worktree 分支把
#: `git worktree add` 的失败收成这条文案（agent_activities._prepare_worktree_lane）。
#: 认这条＝只修「路径/分支被上一张本期票的残骸占住」这一种形态；别的失败（git 身份
#: 缺失、多仓链、权限）清残留解不了，一律不碰（判不准不动）。
LANE_OCCUPIED_MARK = "worktree add"


def lane_residue_repair_plan(prep: Any, instance_id: str, period: str,
                             repo_root: str) -> Optional[Dict[str, Any]]:
    """prepare 失败 → 「定向清本期残留后重试一次」的决策（纯函数，可离线单测）。

    为什么需要（260929 实案）：巡检泳道路径/分支按 **(实例, 期)** 复用
    （inspection_lane_name），而 setup 前置的 sweep 用 `keep_period=本期` —— **刻意不碰
    本期**（那是本票自己要用的路径）。于是「具名重开同期」这条路结构性搭不起泳道：
    旧票（判决 blocked、执行已 COMPLETED）的泳道残留（worktree / 分支 / 裸目录壳）
    仍在原位，新票 `git worktree add` 必败 → setup blocked（t260927-02 实案：09-26
    10:10 首次真跑 reopen 即 blocked；该期此后两张票都 blocked，09-27 的自动班再以
    「同期已服务票出现多张」硬失败）。

    判据：prep 是 dict、ok 为假、action=="failed"、错误文案带 `worktree add`。
    命中 → 返回 sweep 活动参数（`remove_period=本期` 定向模式，忽略水位、只清本期，
    别的期/开发泳道一律不碰）+ 一句可上票面的理由；不命中 → None（不修，原样 blocked）。
    返回的 args 由 workflow 侧送 sweep_inspection_lanes 活动（活动注册面零变化）。"""
    if not isinstance(prep, dict) or prep.get("ok"):
        return None
    if str(prep.get("action") or "") != "failed":
        return None
    err = str(prep.get("error") or "")
    if LANE_OCCUPIED_MARK not in err:
        return None
    return {
        "sweep_args": {"instance_id": str(instance_id or ""),
                       "repo_root": str(repo_root or ""),
                       "keep_period": "", "remove_period": str(period or "")},
        "reason": ("Lane path/branch occupied by this period's own residue "
                   "(git worktree add failed; the setup sweep deliberately keeps the "
                   "current period). Targeted sweep of period %s (worktree + branch + "
                   "bare dir shell), then one prepare retry." % (period or "?")),
    }


def sweep_plan(worktree_entries: Any, branch_names: Any, instance_id: str,
               keep_period: str, remove_period: str = "") -> Dict[str, Any]:
    """残留清扫决策（纯函数）：本实例命名空间里**早于当期水位**的 worktree/分支 → 清；
    开发泳道、别的巡检实例、以及**水位之后**的条目一律不碰。

    水位语义（keep_period = 本期期号，字符串比较）：只清 period < keep_period 的条目。
    这样同一天并发跑的另一期（计数期 YYYYMMDD-<bucket> 词法上大于 YYYYMMDD）不会被
    误删——清场误删在跑的泳道比残留贵；而任何来源的残留（崩溃/取消）到次日水位推进后
    就被扫掉，收敛有界。keep_period 空=无水位（全清，仅供人工 CLI sweep 显式使用）。

    remove_period（t260913-02 实现段新增）：**定向模式**——只清恰好等于该期号的条目，
    忽略水位。给「拆本期」用：teardown_lane 锚在 worker 的 REPO_ROOT（跨项目/跨仓泳道
    会锚错仓，KI-074/075 同族），本函数锚在**显式传入的 repo**，所以跨仓泳道的拆除靠
    它兜底（workflow 侧：teardown 回执不干净 → 定向 sweep 一次，见 _teardown）。

    输入形状与活动侧 `git worktree list --porcelain` / `git branch --list` 的解析结果一致：
    worktree_entries=[{"path":..., "branch":...}]（branch 可空=detached）、branch_names=[str]。
    畸形条目逐项降级进 skipped（不崩、不误删：判不准的一律不动）。"""
    inst = str(instance_id or "")
    if not INSTANCE_ID_RE.match(inst):
        raise ValueError("invalid instance id (sweep): %r" % instance_id)
    dir_prefix = "%s%s-" % (LANE_DIR_PREFIX, inst)
    br_prefix = "%s%s/" % (LANE_BRANCH_NS, inst)
    keep = str(keep_period or "")
    target = str(remove_period or "")
    out: Dict[str, Any] = {"remove_worktrees": [], "remove_branches": [],
                           "keep": [], "deferred": [], "skipped": []}

    def _decide_period(period: str, label: str) -> str:
        """→ "remove" | "keep" | "defer"（判不准=defer，绝不误删）"""
        if not PERIOD_RE.match(period or ""):
            out["skipped"].append("非期号形态，未动：%s" % label)
            return "defer"
        if target:
            return "remove" if period == target else "defer"
        if keep and period == keep:
            out["keep"].append(label)
            return "keep"
        if keep and period > keep:
            out["deferred"].append(label)   # 水位之后（可能是并发在跑的另一期）：不碰
            return "defer"
        return "remove"

    for ent in (worktree_entries if isinstance(worktree_entries, list) else []):
        if not isinstance(ent, dict) or not ent.get("path"):
            out["skipped"].append("worktree 条目畸形：%r" % (ent,))
            continue
        path = str(ent["path"])
        base = path.rstrip("/").rsplit("/", 1)[-1]
        if not base.startswith(dir_prefix):
            continue                      # 开发泳道 / 别的实例：不碰
        if _decide_period(base[len(dir_prefix):], path) == "remove":
            out["remove_worktrees"].append(path)
    seen_branches = set()
    for raw in (branch_names if isinstance(branch_names, list) else []):
        br = str(raw or "").strip()
        if not br or not br.startswith(br_prefix) or br in seen_branches:
            continue
        seen_branches.add(br)
        if _decide_period(br[len(br_prefix):], br) == "remove":
            out["remove_branches"].append(br)
    return out



# ========================================================================================
# 套件段故障具名（260927 修复，必做②/④）：超时必须点名是哪一段，且不得与一般故障混装
# ========================================================================================

def is_activity_timeout_error(exc: Any) -> bool:
    """异常是否为 Temporal 活动**超时**（区别于一般故障，必做④的判据单点）。

    判据只认类型，不认文案：temporalio 在 start_to_close 到点时抛
    `temporalio.exceptions.TimeoutError`（**实测签名/SDK 形态**，ActivityError 是
    「活动失败」的另一族，不承载超时）——故本函数认三处：
      ① temporalio 的 TimeoutError 本体（生产链真形态）；
      ② asyncio.TimeoutError（工作流体/桩态直调、SDK 版本差异形态）；
      ③ 任何异常的 __cause__/__context__ 链上的上述两类（包装层形态）。
    **绝不靠 str(e) 里有没有 "timeout" 字样**——文案随 SDK 版本漂移，判据随文案漂移
    就是下一次「归因错」。未知类型一律 False（保守：落一般故障分支，可见且点名类型）。"""
    try:
        from temporalio.exceptions import TimeoutError as _ActivityTimeoutError
    except Exception:                     # noqa: BLE001——SDK 不在场（纯单测环境）：只认 asyncio
        _ActivityTimeoutError = ()        # type: ignore[assignment]
    hits = (asyncio.TimeoutError,) if not _ActivityTimeoutError \
        else (asyncio.TimeoutError, _ActivityTimeoutError)
    if isinstance(exc, hits):
        return True
    cur: Any = exc
    for _ in range(6):                      # 因果链有限深度，防自引用死循环
        cause = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
        if cause is None or cause is cur:
            break
        if isinstance(cause, hits):
            return True
        cur = cause
    return False


def suite_failure_receipt(exc: BaseException, timeout_sec: float) -> Dict[str, Any]:
    """套件活动异常 → 具名回执（纯函数，单测主面）。

    两态必须可辨（必做④）：超时 → `suite_timeout=True` 且 error 点名套件段超时与超时值；
    一般故障 → `suite_timeout=False` 且 error 点名异常类型。两态 ran/passed/failed/
    env_fail 都是 0 **但 error 非空**——「回执是故障台账，不是套件结果」这句话必须写在
    回执里（旧实现只给 ran=0 与一句含糊 error，归因指向「零场景信号」，把诊断引向错误
    方向：真因是活动超时，不是套件没跑）。"""
    if is_activity_timeout_error(exc):
        err = ("Suite stage timed out: no return within SUITE_TO=%ds (the activity was "
               "reaped; this receipt is a failure record, NOT a suite result — the suite "
               "may still be running; the authoritative conclusion is this period's "
               "timeline plus the next period)" % int(timeout_sec))
    else:
        err = "Suite activity failed: %s: %s" % (type(exc).__name__, exc)
    return {"error": err, "details": [], "ran": 0, "passed": 0, "failed": 0,
            "env_fail": 0, "suite_timeout": bool(is_activity_timeout_error(exc)),
            "suite_timeout_sec": float(timeout_sec) if is_activity_timeout_error(exc) else 0.0}


# 迟到套件回执换名后缀（必做③）：活动超时后仍存活的孤儿进程写盘时泳道/目录可能已不在，
# 它的回执**不代表套件结果**，绝不能覆盖权威回执文件。名字单点在此（inspection_deadman
# 的台账扫描认这个后缀为「已知非台账件」）。
SUITE_LATE_SUFFIX = "-suite-late"
#: 迟到回执 error 文案头（点名它是谁、为什么不可信；单测与 scene 都读这一串）。
SUITE_LATE_ERROR_PREFIX = "活动超时后孤儿进程"


def suite_late_receipt_name(base_name: str, index: int = 1) -> str:
    """迟到回执文件名：`<base>-suite-late.json`（碰撞时 `-2/-3…`，绝不覆写）。

    base_name 是 canonical 回执名（`inspection-<实例>-<期>-suite.json`）——迟到件与
    canonical 同目录、名字显式带 late，读者一眼可辨「这份不是套件结果」。"""
    stem = str(base_name or "")
    if stem.endswith(".json"):
        stem = stem[:-len(".json")]
    else:                                   # 非 .json / 空名：仍给可辨名，不抛（写面 fail-loud）
        stem = stem or "inspection-suite"
    tail = ".json" if index <= 1 else "-%d.json" % int(index)
    return "%s%s%s" % (stem, SUITE_LATE_SUFFIX, tail)


def _write_exclusive(path: Path, text: str) -> Path:
    """exclusive create 写入（'x' 模式）：目标已存在 → FileExistsError 冒泡给调用方
    换号。迟到回执**绝不覆写**任何已有文件（无静默覆盖纪律，_archive_if_other_run 同款）。"""
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(text)
    return path


def validate_trigger_args(instance_id: str, period: str) -> Optional[str]:
    """Trigger arguments fail-closed (an extension of trade-off list item 6); returns an
    error message or None."""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        return "invalid instance: %r (lowercase slug)" % instance_id
    if not PERIOD_RE.match(period or ""):
        return "invalid period: %r (expected YYYYMMDD or YYYYMMDD-<bucket>)" % period
    return None


def build_ticket_face(
    ticket_id: str,
    instance_id: str,
    period: str,
    scan_result: Dict[str, Any],
    extra_findings: Optional[List[Dict[str, Any]]] = None,
    suite: Optional[Dict[str, Any]] = None,
    lane: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Put the finding list onto the ticket face (rendering data): per-severity with
    evidence + heartbeat + ticket-opening suggestions (zero code changes).

    t260913-02 扩展（两个 defaulted 参数，老调用点逐字段不变=零回归）：
      - extra_findings：套件/漏跑等**非扫描器**来源的发现，进发现清单并重计摘要；
      - suite：套件证据段（face["suite"]），并参与心跳合成（套件不绿=不是心跳期）。

    t260916-22 扩展（建议门/摘要口径；对旧发现逐字节兼容）：
      - 建议门：带 verified 字段的发现（agent 产出）必须 verified && confidence≥0.6
        才进 suggested_fix_tickets（工单要点③），unverified（证据复核不过）与假报压制
        同斩——票面可见但不开票；legacy 静态扫描发现无 verified 字段=原门逐字节不变；
      - 摘要重计口径排除 recurring/假报压制（宿主裁定④「重复项不累计」；legacy 发现
        无这些键 → 循环结果与旧实现同值）。"""
    from inspection_inspect import SUGGEST_CONFIDENCE, is_counted
    if not ticket_id or not instance_id:
        raise ValueError("票面缺票号/实例")
    if not isinstance(scan_result, dict) or not isinstance(scan_result.get("findings"), list):
        raise ValueError("扫描结果畸形：缺 findings 列表（fail-closed，不渲染）")
    findings = list(scan_result.get("findings") or [])
    # 追加发现（t260913-02：套件红/环境红/漏跑）——defaulted 空=None 时旧路径逐字段不变
    extra = [f for f in (extra_findings or []) if isinstance(f, dict)]
    if extra:
        findings = findings + extra
    counts = scan_result.get("summary") or {"high": 0, "med": 0, "low": 0}
    if extra:
        # 重计口径与 inspection_inspect.summarize_counts 同形（追加发现的严重度必须进
        # 摘要，否则票面摘要与发现清单互斥——「红的是哪几条」在摘要里数不出来）。
        counts = {"high": 0, "med": 0, "low": 0}
        for f in findings:
            sev = str(f.get("severity") or "")
            if sev in counts and is_counted(f):
                counts[sev] += 1
    heartbeat = bool(scan_result.get("heartbeat"))
    if suite is not None:
        # 心跳合成（t260913-02）：套件在册的期，「全绿」必须含套件全绿——套件红/没跑成/
        # 0 场景都不再是心跳证明期（否则「绿票」会盖住红事）。懒 import：workflow 沙箱
        # 里按需加载（与 inspection_ticket_count 同款纪律）。
        from inspection_deadman import suite_green
        heartbeat = heartbeat and suite_green(suite)
    if lane is not None and int(lane.get("finding_count") or 0) > 0:
        # 心跳合成（260926 lane 面）：票卡在泳道里（重跑/回路/僵尸）也不是「全绿」——
        # 流程层故障不该被一张「零发现绿票」盖住（KI-122 的教训：活锁期间票面全绿）。
        heartbeat = False
    suggestions: List[Dict[str, Any]] = []
    for f in findings:
        if f.get("severity") not in ("high", "med"):
            continue
        if not f.get("suggest", True):
            continue          # 漏跑/环境红/未跑成不是「开一张修码票」能解的（显式开关）
        if f.get("verified") is not None:
            # agent 发现的建议门（t260916-22 要点③④）：机械复核过 + 置信达阈；
            # recurring（上期已在册）不重复开票——修码票应从首期那份修起。
            if f.get("verified") != "verified" or f.get("suppressed") or f.get("recurring"):
                continue
            try:
                if float(f.get("confidence") or 0.0) < SUGGEST_CONFIDENCE:
                    continue
            except (TypeError, ValueError):
                continue
        suggestions.append({
            "template": "dev-lane",
            "title": "fix: %s %s" % (f.get("scan", ""), str(f.get("subject", ""))[:60]),
            "source_inspection": ticket_id,           # the fix ticket references the inspection ticket id (epic tickets 1/4)
            "urgency": "open now" if f.get("severity") == "high" else "after human review",
            "evidence": f.get("evidence", ""),
        })
    face_out = {
        "ticket_id": ticket_id,
        "kind": "inspection",
        "instance_id": instance_id,
        "period": period,
        "red_line": INSPECTION_RED_LINE,
        "heartbeat": heartbeat,
        "heartbeat_note": "All green: zero-finding ticket (heartbeat proof)" if heartbeat else "",
        "summary": counts,
        "findings": findings,
        "suggested_fix_tickets": suggestions,
        "scan_meta": scan_result.get("meta") or {},
    }
    # 零发现显式（t260924-06 必做③）：findings 空=必须显式声明「本期无新病灶」并附
    # 证据面（审查范围计数与输入面点名），不得再出现空壳 findings=0。触发条件=meta
    # 在册 scope 证据面（inspect 缩面链路）；无 scope 的 legacy/defaulted 路径零新键
    # （零回归钉 test_face_without_suite_is_byte_identical_to_ticket1 不破——扩锁不拆锁）。
    if not findings:
        meta = scan_result.get("meta") or {}
        scope = {}
        if isinstance(meta.get("inspect"), dict):
            scope = meta["inspect"].get("scope") or {}
        elif isinstance(meta.get("scope"), dict):
            scope = meta["scope"]
        if scope:
            note_keys = ("diff_error", "diff_malformed_lines", "suite_note",
                         "ki_note", "scope_note")
            warned = ["%s=%s" % (k, scope[k]) for k in note_keys if scope.get(k)]
            face_out["zero_findings_note"] = (
                "No new defects this period (review scope: %s files; change-face diff=%s; %s)"
                % (scope.get("scope_files", 0),
                   "absent/fallback" if (scope.get("diff_error") or scope.get("scope_note"))
                   else "given",
                   "input face named: " + ", ".join(warned) if warned
                   else "no malformed input face across the four sources"))
    if suite is not None:
        face_out["suite"] = suite      # 套件证据段（逐场景红绿/摘要/回执路径，验收 B）
        # 260927 code_stamp（宿主裁定②）：票面落**一行可读**代码身份（值来自活动的
        # 回执数据——活动结果进 history，重放拿回同值，故不引入非确定面）。
        if suite.get("code_stamp"):
            face_out["code_stamp"] = str(suite["code_stamp"])
    if lane is not None:
        # lane/watchdog 证据段（260926）：计数（scanned/finding_count/by_leg）+ 阈值与
        # **阈值来源**（declaration|default，逐键回落原因）——不静默；报告面零 CJK 守门
        # 同样覆盖本段（文案全英文，数据字段=票号/stage id 不译）。
        face_out["lane"] = lane
    return face_out


def validate_close_signature(sig: Any, expected_gate: str = CLOSE_GATE_ID) -> Tuple[Optional[Dict[str, str]], str]:
    """Validate the human-gate signature (reusing Signature semantics): returns
    (normalized payload, error message). Self-signing by an agent (who matches one of the
    five agent role names) is refused — only a human may sign."""
    if isinstance(sig, Signature):
        payload = {"who": sig.who, "gate": sig.gate, "decision": sig.decision, "note": sig.note or ""}
    elif isinstance(sig, dict):
        payload = {"who": str(sig.get("who") or ""), "gate": str(sig.get("gate") or ""),
                   "decision": str(sig.get("decision") or ""), "note": str(sig.get("note") or "")}
    else:
        return None, "签字载荷类型非法：%s" % type(sig).__name__
    if not payload["who"].strip():
        return None, "签字缺 who（签字身份由调用方注入）"
    if len(payload["who"]) > MAX_WHO_LEN:
        return None, "who 超长（>%d）" % MAX_WHO_LEN
    if payload["who"].strip().lower() in AGENT_ROLE_NAMES:
        return None, "agent 不得自签（who=%r 是 agent 角色名；签字只能人）" % payload["who"]
    if payload["gate"] != expected_gate:
        return None, "签字 gate 不匹配：%r（本门=%r）" % (payload["gate"], expected_gate)
    if payload["decision"] not in ("approve", "reject"):
        return None, "decision 只认 approve/reject（got %r）" % payload["decision"]
    return payload, ""


# 台账留史目录名（t260917-02）：canonical 文件同目录下的 archive/ 子目录——
# inspection_deadman.ledger_periods 用 iterdir 顶层扫 *.json，子目录天然不进漏跑扫描；
# 用可见的非隐藏名（不用 .archive），运维人工清理时看得见（README 注记：不自动清理）。
LEDGER_ARCHIVE_DIRNAME = "archive"


#: 泳道拆除结果**机器 token**（260927 单源改造同纪律）：下游判「是否未净」认 token，
#: 不认人话——文案可英文化/可改写，判据不受影响（旧版 startswith("未净") 把判据钉在
#: 会被翻译的中文上，正是「改文案即静默改行为」的形态）。
TEARDOWN_OK = "TEARDOWN_OK"
TEARDOWN_RESIDUE = "TEARDOWN_RESIDUE"


def _archive_ticket_token(old_ticket_id: str) -> str:
    """归档名里的被归档票号 token（t260917-02）：只留文件名安全字符，其余压 '-'——
    t 形号/旧形号/服务端后缀形（含冒号、T/Z）都能安全落名；空/不可判 → 'corrupt'
    （旧内容不可解析或无 ticket_id 时的诚实标记，绝不冒充可判票号）。"""
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(old_ticket_id or "").strip())
    return token.strip("-") or "corrupt"


def _archive_if_other_run(path: Path, incoming_ticket_id: str,
                          now_fn: Callable[[], float] = time.time) -> Dict[str, Any]:
    """跨票覆盖前把旧台账/回执搬进 archive/（t260917-02 修复③；纯 impl，activity 侧用）。

    判定：旧文件存在且其 ticket_id != 本次 incoming ticket_id → 归档；相等（含双空）
    → 同票自身重写（一次 run 落三次账：report 段/人门段/收口段），绝不归档——否则
    每张票自产三件假「留史」。旧内容不可解析为 JSON 或无 ticket_id → 仍归档（token=
    corrupt，原字节整体搬移），防畸形旧件被新跑静默清掉。

    无静默覆盖（review R3）：归档目标 = `<stem>-<token>-<HHMMSS>[-N].json`，用
    exclusive create（open 'xb'）——目标已存在（同秒同 token 的极端残撞）→ N+1 重试，
    绝不覆写任何已有归档件；重试耗尽 → 放弃归档但把事由记进 archive_error（canonical
    新写照常进行=最新态优先，丢史可归责）。原文件只在归档字节落定后才移除。

    返回（additive，activity 回执透传）：{"archived": bool, "archive_path": str,
    "archive_error": str}——失败不 raise（落账主流程绝不因留史失败而断）。"""
    out: Dict[str, Any] = {"archived": False, "archive_path": "", "archive_error": ""}
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return out                                  # 首次落账：无旧件可归档
    except OSError as e:
        out["archive_error"] = "old file unreadable (not archived, new write proceeds): %s: %s" % (type(e).__name__, e)
        return out
    old_ticket_id = ""
    old_corrupt = False
    try:
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict):
            old_ticket_id = str(parsed.get("ticket_id") or "")
    except Exception:                          # noqa: BLE001——畸形旧件：仍归档留证
        old_ticket_id = ""
        old_corrupt = True
    if not old_corrupt and old_ticket_id == str(incoming_ticket_id or ""):
        return out                             # 同票自身重写：不是「另一跑」，不归档
                                               # （含双空=老 face 无 ticket_id 的幂等重写面；
                                               #  可解析但无票号的旧件在 incoming 非空时
                                               #  照常归档，token=corrupt）
    token = _archive_ticket_token(old_ticket_id)
    stamp = datetime.fromtimestamp(now_fn()).strftime("%H%M%S")
    archive_dir = path.parent / LEDGER_ARCHIVE_DIRNAME
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        out["archive_error"] = "archive dir not creatable (not archived, new write proceeds): %s: %s" % (type(e).__name__, e)
        return out
    base = "%s-%s-%s" % (path.stem, token, stamp)
    for n in range(1, 100):                         # 无静默覆盖：存在即换号，绝不覆写
        candidate = archive_dir / ("%s%s%s" % (base, ("" if n == 1 else "-%d" % n),
                                               path.suffix))
        try:
            with open(candidate, "xb") as fh:
                fh.write(raw)
            break
        except FileExistsError:
            continue                                # 同秒同 token 残撞 → -2/-3…
        except OSError as e:
            out["archive_error"] = "archive write failed (not archived, new write proceeds): %s: %s" % (type(e).__name__, e)
            return out
    else:
        out["archive_error"] = ("archive retries exhausted (%s-*.%s already has 99 files; "
                                "nothing archived, nothing overwritten, new write proceeds)"
                                % (base, path.suffix.lstrip(".")))
        return out
    try:
        path.unlink()
    except OSError as e:
        # 归档已落定但原件移除失败：canonical 新写将覆盖同名原件——留史不丢（archive 已有），
        # 事由仍要点名（「归档了但 canonical 写入前的原件删除失败」是异常形态）。
        out["archive_error"] = "original not removed after archiving: %s: %s" % (type(e).__name__, e)
    out["archived"] = True
    out["archive_path"] = str(candidate)
    return out


def write_inspection_report_impl(face: Dict[str, Any], out_dir: Path,
                                 now_fn: Callable[[], float] = time.time) -> Dict[str, Any]:
    """Posting (a pure impl; the activity is a thin shell around it):
    out/inspection/inspection-<实例>-<期>.json（t260916-02：文件名按实例+期派生
    （inspection_ledger_name 单点）——键名约定不是票号，票号 t 形化后 deadman 台账
    扫描零改动；同票重跑覆盖同一文件）。

    t260917-02 修复③：跨票覆盖前旧件自动搬 archive/ 留史（_archive_if_other_run 单点；
    同票自身重写不归档）——canonical=每期最新一份，archive/=每跑一份。回执键 additive
    （archived/archive_path/archive_error），老 worker/老调用零破坏。"""
    instance_id = str(face.get("instance_id") or "")
    period = str(face.get("period") or "")
    if not instance_id or not period:
        raise ValueError("落账缺实例/期号（face.instance_id/period）")
    name = inspection_ledger_name(instance_id, period)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    archived = _archive_if_other_run(path, str(face.get("ticket_id") or ""), now_fn=now_fn)
    path.write_text(json.dumps(face, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"file": name, "path": str(path),
            "ticket_id": str(face.get("ticket_id") or ""),
            "archived": archived["archived"],
            "archive_path": archived["archive_path"],
            "archive_error": archived["archive_error"]}


def write_inspection_suite_receipt_impl(instance_id: str, period: str,
                                        receipt: Dict[str, Any], out_dir: Path,
                                        now_fn: Callable[[], float] = time.time,
                                        fallback_name: str = "",
                                        late_error: str = "") -> Dict[str, Any]:
    """套件回执落盘（t260913-02；t260916-02 文件名按实例+期派生）：
    out/inspection/inspection-<实例>-<期>-suite.json（同票重跑覆盖）。

    票面只放逐场景红绿/摘要（不刷屏），**输出尾与全量明细在这里**——票面里的聚合红项
    与 deadman 条目都指回这个文件（可下钻，验收 B/D 的「可读」面）。文件名以 -suite.json
    结尾，台账扫描（inspection_deadman.ledger_periods）显式识别为已知非台账件。
    instance/period 双缺时回落**legacy 只读解析** receipt.ticket_id（旧形 id 含实例/期；
    服务老在途票重放——读面，绝不铸造旧形新票）。

    fallback_name / late_error（260927 迟到孤儿面，必做③）：活动在写盘前已确认泳道/目录
    不在（给出迟到原因）→ 本回执**不代表套件结果**，绝不写 canonical 名（那会覆盖权威
    回执，t260927-01 实况），改落 `-suite-late[-N].json`（exclusive create，碰撞换号，
    绝不覆写任何已有文件），error 点名「活动超时后孤儿进程…」。回执键 additive：
    late=True + late_error 便于读者与运维一眼分流。两参数任一非空即迟到（换名一律由
    本函数按单点算，调用方不自己拼文件名）。

    两态（canonical / late）都先经 _archive_if_other_run 留史：跨票覆盖前旧件搬 archive/，
    同票自身重写不归档（旧语义逐字不变）。"""
    instance_id = str(instance_id or "")
    period = str(period or "")
    if not instance_id or not period:
        m = re.match(r"^inspection-(.+)-(\d{8}(?:-[1-9]\d*)?)$",
                     str((receipt or {}).get("ticket_id") or ""))
        if not m:
            raise ValueError("套件回执缺实例/期号（且 ticket_id 非旧形可解析）")
        instance_id, period = m.group(1), m.group(2)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = (inspection_ledger_name(instance_id, period)[:-len(".json")]
                 + "-suite.json")
    payload = dict(receipt or {})
    # 迟到判据：调用方给出迟到**原因**（late_error）或显式换名（fallback_name）即迟到——
    # 两个入口都收（调用点只给原因；换名由本函数按单点算，调用方不自己拼文件名）。
    late = bool(str(fallback_name or "").strip() or str(late_error or "").strip())
    if late:
        payload["late"] = True
        payload["late_error"] = str(late_error or "")
        target = None
        for n in range(1, 100):              # 迟到件绝不覆写：存在即换号
            cand = out_dir / suite_late_receipt_name(base_name, n)
            try:
                _write_exclusive(
                    cand, json.dumps(payload, ensure_ascii=False, indent=2))
                target = cand
                break
            except FileExistsError:
                continue
            except OSError as e:
                raise OSError("迟到套件回执落盘失败（不覆写 canonical）：%s: %s"
                              % (type(e).__name__, e)) from e
        if target is None:
            raise OSError("迟到套件回执换号耗尽（%s-*.json 已有 99 件，绝不覆写）"
                          % (base_name[:-len(".json")] + SUITE_LATE_SUFFIX))
        return {"file": target.name, "path": str(target),
                "ticket_id": str(payload.get("ticket_id") or ""),
                "instance_id": instance_id, "period": period,
                "late": True, "late_error": str(late_error or ""),
                "archived": False, "archive_path": "", "archive_error": ""}
    path = out_dir / base_name
    archived = _archive_if_other_run(path, str(payload.get("ticket_id") or ""),
                                     now_fn=now_fn)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"file": path.name, "path": str(path),
            "ticket_id": str(payload.get("ticket_id") or ""),
            "instance_id": instance_id, "period": period, "late": False,
            "archived": archived["archived"],
            "archive_path": archived["archive_path"],
            "archive_error": archived["archive_error"]}


# ========================================================================================
# Workflow: (setup →) scan → (suite →) report → human gate → close
#   setup/suite 只在声明 suite=full 的期出现（t260913-02）；其余实例与票①逐字一致。
# ========================================================================================

@dataclass
class InspectionPeriodicInput:
    """Input for one inspection period (declaration instance + period key; an empty
    period = derived from workflow.now() — the schedule-triggered path)."""

    instance_id: str
    # 兼容红线（t260910-11）：声明 schema 的 face 字段已除名（零消费者），但本输入
    # 结构保留 face 并给默认值——历史 workflow 重放按字段名解码，删字段会解码报错。
    # 新代码不得再消费该值（报告输出里的 "face" 键已随本票删除）。
    face: str = "test"
    period: str = ""
    repo_root: str = ""
    scenarios_path: str = ""
    # 声明来源（t260913-02 实现段）：触发侧（--decl-path）钉的声明文件路径随票走，保证
    # 「触发面校验用的声明」与「workflow 运行期读的声明」是同一份（否则在册/停用判定分家：
    # 隔离台场景按 --decl-path 注入夹具声明，worker 却读进程缺省 → 票被判「不在册」blocked）。
    # 缺省空=用 worker 侧缺省/env（**调度路径恒为空**——schedule-up 不写本字段，所以「改声明
    # 即改行为」的调度语义不变）。兼容两向皆安全：老 history 无此键→默认值；老 worker 收到
    # 多出的键→dataclass 解码忽略未知键（实测）。
    decl_path: str = ""
    # 实例级项目身份（t260915-20）：本票归属哪个项目（=起票时刻声明的实例 project_key）。
    # 起票三路（trigger / schedule-up / watcher activity）一律显式填；SA ProjectKey 与
    # 本字段是同一事实的两个面（SA=检索面、payload=票面），同值由集成场景钉住。
    # 缺省空=兼容老 history 重放（face 同款纪律：按字段名解码，缺键取默认不炸）——
    # 但双空（无身份也无 repo_root）的**新**票会被无主守卫拦成 blocked（PROJECT_PATCH_ID）。
    project_key: str = ""
    # 被替代的终止票号（t260925-09 / KI-114）：终止期票重开时起票面写入的审计链接
    # （同期的「终止旧票 → 活新票」两 run 链）。缺省空=正常起票/老 history 重放不炸。
    supersedes_ticket_id: str = ""


# ========================================================================================
# t260916-05：机器可读阶段声明（编码真源=本 workflow 侧代码；展示面=template_topology
# 的 inspection-lite 导出，一致性锁=tests/test_t260916_05_inspection_topology.py——
# 「STAGES 改了不改导出面，此处必红」，dev-lane 范式同款）。
# 最小字段（派单规格）：id/name/next/人门标记（exit）/套件档开关（suite_only）；
# parts 是展示用执行器组合（shared.PART_KINDS 子集，巡检段全程序化、close 带人签）。
# 与 flow 实际调用点对齐：setup/suite 只在声明 run_suite=full 的期出现（run() 的
# `if run_suite:` 守卫）→ suite_only=True，展示面画条件段（optional 虚节点注记）；
# inspect/report/close 每期必经（t260916-22：scan 段退役、inspect 段接位——旧路径
# 只剩老在途票 replay，其 timeline 里的 scan 字样来自 history，不来自 STAGES）。
# ========================================================================================

@dataclass(frozen=True)
class InspectionStage:
    """One inspection stage (an element of InspectionPeriodicWorkflow.STAGES).
    kind projects like shared.Stage: exit='human' → a human-gate stage; otherwise a
    programmatic (script/gate) stage — inspection has no agent-narration stages."""

    id: str
    name: str
    next: str = ""                    # 展示/快照面；驱动跟 STAGES 声明序（末段空=收口）
    exit: str = ""                    # 'human' = 人门段（sign 信号 + wait_condition）
    suite_only: bool = False          # 套件档开关：仅声明 run_suite=full 的期出现
    parts: Tuple[str, ...] = ()       # 执行器组合（shared.PART_KINDS 子集；展示面）

    @property
    def kind(self) -> str:
        if self.exit == "human":
            return "human"
        return "gate"


#: 前置终态段位标签（不是流程段、不入拓扑图）：无主票守卫的 blocked 落点。
#: 单列登记而不塞进 STAGES——图面节点必须是真实阶段链；源码锁把 `_enter`/`_blocked`
#: 的段位字面量全集对齐 STAGES∪PRE_FLOW_STAGES，防未来新增标签静默绕锁。
PRE_FLOW_STAGES: Tuple[str, ...] = ("guard",)


@dataclass
class FindingVerdict:
    """发现级裁定信号载荷（t260916-22 要点⑥）：人门签字附或签后 CLI 逐条标注。

    gate 语义与 sign 相同（gate 不匹配=忽略+点名，绝不误收）；who 必须是人（agent
    角色名拒收，validate_close_signature 同语义）。verdict 收英文 token 与中文别名
    （假报/待修/存疑，normalize_verdict 归一）。signal 只改内存票面+timeline（零
    活动调用=回放安全）；verdicts 台账由收口段一次写齐（_finalize_and_close），
    收口后的裁定走 CLI 直写台账。"""

    gate: str = CLOSE_GATE_ID
    finding_id: str = ""
    verdict: str = ""          # false-positive / to-fix / doubt（或中文别名）
    who: str = ""
    note: str = ""


def validate_finding_verdict_payload(
    sig: Any, expected_gate: str = CLOSE_GATE_ID,
) -> Tuple[Dict[str, str], str]:
    """裁定信号载荷校验（纯函数，单测主面；sign 闸同语义）：
    who 非空/≤64/非 agent 角色名、gate 匹配、finding_id 非空、verdict 归一。
    返回 (归一 payload, 错误信息)；err 非空=拒收（signal 面只记 _gate_err 不炸）。"""
    if isinstance(sig, FindingVerdict):
        raw = {"finding_id": sig.finding_id, "verdict": sig.verdict,
               "who": sig.who, "note": sig.note or "", "gate": sig.gate}
    elif isinstance(sig, dict):
        raw = {"finding_id": str(sig.get("finding_id") or ""),
               "verdict": str(sig.get("verdict") or ""),
               "who": str(sig.get("who") or ""),
               "note": str(sig.get("note") or ""),
               "gate": str(sig.get("gate") or "")}
    else:
        return {}, "裁定载荷类型非法：%s" % type(sig).__name__
    if not raw["who"].strip():
        return {}, "裁定缺 who（裁定身份由调用方注入）"
    if len(raw["who"]) > MAX_WHO_LEN:
        return {}, "who 超长（>%d）" % MAX_WHO_LEN
    if raw["who"].strip().lower() in AGENT_ROLE_NAMES:
        return {}, "agent 不得裁定（who=%r 是 agent 角色名；裁定只能人）" % raw["who"]
    if raw["gate"] != expected_gate:
        return {}, "裁定 gate 不匹配：%r（本门=%r）" % (raw["gate"], expected_gate)
    if not raw["finding_id"].strip():
        return {}, "裁定缺 finding-id（逐条标注，绝不整票批改）"
    from inspection_inspect import normalize_verdict
    try:
        raw["verdict"] = normalize_verdict(raw["verdict"])
    except ValueError as e:
        return {}, str(e)
    return raw, ""


def _inspection_topology() -> Dict[str, Any]:
    """本模板的展示面拓扑导出（t260916-05；snapshot query 消费）。懒 import
    template_topology：workflow 沙箱里按需加载（build_ticket_face 懒 import
    inspection_deadman 同款）；被导模块零 IO 零 temporalio 依赖，纯查表安全。
    未声明模板返回 None=消费方回落，绝不猜拓扑。"""
    from template_topology import export_template_topology
    return export_template_topology("inspection-lite")


async def _prepare_lane_activity(ticket_id: str, worktree: str, branch: str,
                                 base_ref: str) -> Dict[str, Any]:
    """prepare_workspace 活动调用一次（两个巡检 workflow 类共用同一形状：正常路径与
    「清本期残留后重试」两次调用在 history 里逐字同形、回执归一）。"""
    prep_raw: Any = await workflow.execute_activity(
        prepare_workspace,
        WorkspacePrep(ticket_id=ticket_id,
                      workspace={"type": "worktree", "path": worktree},
                      branch=branch, base_ref=base_ref),
        start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
    if isinstance(prep_raw, dict):
        return prep_raw
    return {"ok": getattr(prep_raw, "ok", False), "action": getattr(prep_raw, "action", ""),
            "path": getattr(prep_raw, "path", ""), "error": getattr(prep_raw, "error", "")}


async def _lane_residue_repair(plan: Dict[str, Any], ticket_id: str, worktree: str,
                               branch: str, base_ref: str) -> Dict[str, Any]:
    """按修复计划定向清本期残留（sweep remove_period）→ 重试一次 prepare。

    返回修复回执 {reason, sweep:{...}, retry:"ok"|<错误尾>, prep:<新回执>}——票面 blocked
    文案与时间线都引用它（写清「试过什么、结果如何」，不许含糊）。报告链
    （InspectionPeriodicWorkflow）与产出链（InspectionProduceWorkflow）共用本壳：两条链
    的泳道坐标同一套命名（inspection_lane_name），残留形态与修法只有一份。"""
    swept2: Any = await workflow.execute_activity(
        "sweep_inspection_lanes", args=[plan["sweep_args"]],
        start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
    sres = (swept2 or {}).get("result") or {}
    prep2 = await _prepare_lane_activity(ticket_id, worktree, branch, base_ref)
    return {
        "reason": plan["reason"],
        "sweep": {
            "ok": bool((swept2 or {}).get("ok")),
            "removed_worktrees": list(sres.get("removed_worktrees") or []),
            "removed_branches": list(sres.get("removed_branches") or []),
            "removed_dir_stubs": list(sres.get("removed_dir_stubs") or []),
            "errors": list(sres.get("errors") or []),
            "error": str((swept2 or {}).get("error") or "")},
        "retry": "ok" if prep2.get("ok") else str(prep2.get("error") or "unknown")[:400],
        "prep": prep2,
    }


def _lane_repair_note(repair: Dict[str, Any]) -> str:
    """修复回执 → 时间线一行（英文，人可读；票面/时间线是给跨项目收件人的）。"""
    sw = repair.get("sweep") or {}
    return ("Residue repair: swept %d worktree(s) / %d branch(es) / %d dir shell(s) "
            "(errors %s) → prepare retry %s"
            % (len(sw.get("removed_worktrees") or []), len(sw.get("removed_branches") or []),
               len(sw.get("removed_dir_stubs") or []), sw.get("errors") or "none",
               "succeeded" if repair.get("retry") == "ok"
               else "failed: %s" % (repair.get("retry") or "unknown")))


def _lane_repair_detail(repair: Dict[str, Any]) -> str:
    """修复回执 → blocked 文案附注（写清「试过什么、结果如何」，不许含糊）。"""
    sw = repair.get("sweep") or {}
    return (" | residue repair attempted: swept %d worktree(s) / %d branch(es) / %d dir "
            "shell(s) (errors %s) → retry %s"
            % (len(sw.get("removed_worktrees") or []), len(sw.get("removed_branches") or []),
               len(sw.get("removed_dir_stubs") or []), sw.get("errors") or "none",
               repair.get("retry") or "unknown"))


@workflow.defn
class InspectionPeriodicWorkflow(TicketEventLedgerMixin):
    """One inspection-period ticket. State machine: scan → report → close (human gate) →
    a terminal closed state.
    Business refusals do not raise: a scan/posting failure → a blocked terminal ticket
    (visible, queryable), never a fake green."""

    #: t260916-05 阶段声明（编码真源）：声明序=执行序；展示面（template_topology
    #: inspection-lite 导出）与一致性锁都以它为对齐锚。
    #: t260916-22 段序（INSPECT_PATCH_ID 门内）：setup → suite → inspect → report →
    #: close——scan 段（静态扫描）退役，inspect 段（只读 agent 审查）接位；suite 提到
    #: inspect 前（inspect 的 prompt 引用当期套件回执）。老在途票 replay 走旧路径，
    #: STAGES 只服务新票+展示面（replay 快照面不重算 STAGES——timeline 在 history）。
    STAGES = (
        InspectionStage(id="setup", name="泳道准备", next="suite",
                        suite_only=True, parts=("script",)),
        InspectionStage(id="suite", name="巡检泳道套件", next="inspect",
                        suite_only=True, parts=("script",)),
        InspectionStage(id="inspect", name="巡检审查", next="report", parts=("script",)),
        InspectionStage(id="report", name="落账", next="close", parts=("script",)),
        InspectionStage(id="close", name="人审收口", next="", exit="human",
                        parts=("human", "script")),
    )

    def __init__(self) -> None:
        self.stage: str = ""
        self.stage_state: str = "running"
        self.status: str = "running"
        self.decision: str = ""
        self.face: Dict[str, Any] = {}
        self.timeline: List[Dict[str, Any]] = []
        self._close_sig: Optional[Dict[str, str]] = None
        self._gate_err: str = ""
        self._patched: bool = False      # 版本门结果（老 history 缺标记 → 走票① 旧路径）
        self._code_stamp: str = ""       # 260927：活动带回的代码身份行（票面兜底用）
        self._input: Optional[InspectionPeriodicInput] = None  # run 入口钉存（sign 闸 payload 回退链）

    def _enter(self, stage: str, state: str = "running", reason: str = "") -> None:
        self.stage = stage
        self.stage_state = state
        entry = {
            "at": workflow.now().isoformat(timespec="seconds"),
            "stage": stage, "state": state, "reason": reason}
        self.timeline.append(entry)
        # t260928-20：事件账本入队（唯一入队点，机制在 TicketEventLedgerMixin；
        # patched 门内，老实例重放零变化；flush 由各异步边界/收口点承担）。
        # gen 维度：本族 timeline 条目无 gen（无轮次概念）——账面行按 mixin 纪律
        # 记文档化常量 0（诚实：0=本族无代数维度，绝不伪造代数）。
        self._ledger_enqueue(entry)

    def _ledger_project(self) -> str:
        """本票项目身份（t260915-20 链路）：SA ProjectKey 同源的 payload 真源；
        mixin 缺省读 meta——本族无 meta，身份在 _input.project_key。"""
        return str(getattr(getattr(self, "_input", None), "project_key", "") or "")

    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """Human-gate signature (the existing approval-gate machinery). A signature whose
        gate does not match is ignored with a note, never accepted by mistake.

        t260912-03：本巡检模板无授权面——带 authorize 的载荷在 validate 之前显式拒收
        （validate_close_signature 不感知 authorize，若放行会被当作普通人门签字）。"""
        if getattr(sig, "authorize", None) is not None:
            self._gate_err = ("this inspection template has no authorization face; authorize payload "
                          "rejected (no signature recorded)")
            workflow.logger.warning("拒收 authorize 载荷：本巡检模板无人授权面")
            return
        # t260915-12 跨项目闸（第二道，统一接闸不留分叉）；t260915-20 升级：target=
        # 本票项目身份（SA ProjectKey 优先、payload project_key 回退，双空=""恒放行
        # =老 history 现状不变）——异项目 caller 对已归属巡检票签字即结构化拒收。
        sa_project = ""
        try:
            pairs = workflow.info().typed_search_attributes or []
            for pair in pairs:
                if str(getattr(getattr(pair, "key", None), "name", "")) == PROJECT_SA_NAME:
                    sa_project = str(getattr(pair, "value", "") or "")
                    break
        except Exception:  # noqa: BLE001——SA 读面故障回落 payload 链（闸不因读面炸而失效）
            sa_project = ""
        # _input 缺席防御：signal 先于 run 的 handler 直调形态（object.__new__ 面）不炸
        target = sign_target_project(sa_project, str(getattr(getattr(self, "_input", None),
                                                             "project_key", "") or ""))
        g = cross_project_judge(str(getattr(sig, "caller_project", "") or ""), target,
                                str(getattr(sig, "cross_project_note", "") or ""))
        if g["action"] == "refuse":
            self._gate_err = g["why"]
            workflow.logger.warning("%s", g["why"])
            return
        payload, err = validate_close_signature(sig)
        if err:
            self._gate_err = err
            workflow.logger.warning("拒收签字：%s", err)
            return
        if self._close_sig is None:
            self._close_sig = payload

    @workflow.signal
    def finding_verdict(self, sig: FindingVerdict) -> None:
        """发现级裁定（t260916-22 要点⑥）：人对单条发现标 假报/待修/存疑。

        纯内存改 face + timeline，零活动调用=回放安全；verdicts 台账在收口段一次
        写齐（跨期压制消费），收口后的裁定走 CLI 直写台账。拒收（载荷坏/门不匹配/
        agent 名）只记 _gate_err 不炸不误收——sign 闸同语义。"""
        if not getattr(self, "_patched", False):
            self._gate_err = ("finding_verdict is a t260916-22 command: not injected on replay of an "
                          "old ticket (rejected)")
            return
        payload, err = validate_finding_verdict_payload(sig)
        if err:
            self._gate_err = err
            workflow.logger.warning("拒收裁定：%s", err)
            return
        from inspection_inspect import apply_verdict_to_face
        err = apply_verdict_to_face(self.face, payload["finding_id"], payload["verdict"],
                                    payload["who"], payload["note"])
        if err:
            self._gate_err = "verdict not recorded: %s" % err
            workflow.logger.warning("裁定未落：%s", err)
            return
        self._enter("close", self.stage_state or "running",
                    "Finding verdict: %s -> %s (who=%s%s)"
                    % (payload["finding_id"], payload["verdict"], payload["who"],
                       ", note=%s" % payload["note"] if payload["note"] else ""))

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        """Ticket-face snapshot (consumed by the workbench / ops channel; shape = a
        ticket: stage/stage_state/status/face/timeline)."""
        return {
            "id": workflow.info().workflow_id,
            "kind": "inspection",
            "template": "inspection-lite",
            # 票归属项目（t260915-20）：payload 侧真源（query 加键安全，非记录面）；
            # 与 SA ProjectKey 同值（起票三路同源写入），ticket_receipt/工单行各自取面
            "project": str(getattr(self._input, "project_key", "") or ""),
            "stage": self.stage,
            "stage_state": self.stage_state,
            "status": self.status,
            "decision": self.decision,
            "face": self.face,
            "timeline": self.timeline,
            "gate_error": self._gate_err,
            # t260916-05：模板拓扑导出（门内 additive 键=旧实例重放零新键；纯函数查表
            # 零 IO；查询体只读缓存位 _patched，不触 SDK 门判定——R1 同纪律，dev_lane
            # snapshot 的 _detail_face_on 同款）。消费链：client.py _inspection_query_meta
            # 透传 → workbench detail.topology → 泳道图（buildLaneMap；None=未声明模板
            # 回落，绝不猜拓扑）。
            **({"topology": _inspection_topology()}
               if getattr(self, "_patched", False) else {}),
            # t260928-20（review C1）：事件账本迁移标记（[{i,seq,run}]；timeline 条目
            # 本身零标记，票面形状逐字不变）——终态取消/超时硬杀下 pending 未冲即亡时
            # 取消面权威留痕可由 op=ledger_rebuild 从 timeline+marks 补齐（dev_lane
            # 同款增量键；门内 additive=老实例快照零新键，重放安全）。
            **({"ledger_marks": [dict(m) for m in (self._ledger_marks or [])]}
               if getattr(self, "_patched", False) else {}),
        }

    @workflow.run
    async def run(self, inp: InspectionPeriodicInput) -> Dict[str, Any]:
        repo_root = str(inp.repo_root or "")
        self._input = inp   # sign 闸 payload 回退链 / snapshot project 面的真源钉存
        # 版本门（replay 安全，见 SUITE_PATCH_ID 头注）：老在途票在这里拿到 False，
        # 于是一路走票① 旧路径，一个新命令都不注入。
        self._patched = workflow.patched(SUITE_PATCH_ID)
        # 轨道分派（t260916-22）：SUITE 门且 INSPECT 门都开 = inspect 轨（agent 审查）；
        # 只开 SUITE 门的过渡窗在途票（本票上线瞬间在途）继续走旧路径重放到收口——
        # 中途换轨=history 注入新命令=非确定（replay 红线），门判据是「双门」不是新门。
        if self._patched and workflow.patched(INSPECT_PATCH_ID):
            return await self._run_inspect_period_flow(inp, repo_root)
        return await _run_legacy_period_flow(self, inp, repo_root)

    # ---- t260916-22：inspect 轨道（setup → suite → inspect → report → close）----

    async def _run_inspect_period_flow(
        self, inp: InspectionPeriodicInput, repo_root: str,
    ) -> Dict[str, Any]:
        """agent 审查轨道：静态扫描退役（run_inspection_scan 调用点=0），scan 段换成
        inspect 段（只读 agent 产出强 schema 发现 → report 段机械复核）。

        与旧轨道同构复用：声明决议/期号铸取/setup/suite/deadman/收口人门全部同源；
        差异只有两段——inspect 段活动（替代 run_inspection_scan）与 verify 段活动
        （机械复核链，report 段内）。审查基座=repo_root（suite 期泳道在 suite 段内
        已拆，review 裁定：不为审查专搭只读泳道；meta 记 base_dir 可见）。"""
        ticket_id = workflow.info().workflow_id
        # 无主票守卫（t260915-20）：两轨道同守——项目身份与 repo_root 双空 → blocked
        # 终态点名，绝不静默回落引擎仓审查（新轨道审查基座=repo_root，更不能无主）。
        if workflow.patched(PROJECT_PATCH_ID):
            guard = unowned_guard_reason(getattr(inp, "project_key", ""), repo_root)
            if guard:
                return await self._blocked(
                    ticket_id, inp, str(inp.period or ""), "guard", guard, None)
        # ---- 声明决议 + 期号铸取（与旧轨道同源同序） ----
        plan_raw: Any = await workflow.execute_activity(
            "resolve_inspection_plan",
            args=[{"instance_id": inp.instance_id, "decl_path": inp.decl_path}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        plan: Dict[str, Any] = (plan_raw or {}).get("result") or {}
        period = inp.period or period_key_in_tz(workflow.now(), str(plan.get("tz") or ""))
        validate_period_key(inp.instance_id, period)
        if not (plan_raw or {}).get("ok"):
            return await self._blocked(
                ticket_id, inp, period, "setup",
                "Declaration resolution failed: %s" % ((plan_raw or {}).get("error") or "unknown"), None)
        # ---- 重定向守卫（t260917-02，REDIRECT_PATCH_ID 新命令；replay 安全不变量：
        # 本分支内的新 activity 调用对老 history 永不可达——patched()=False 时零新命令）。
        # 非 t 形 fire（旧调度 action 直发）在此改道起票单点铸 t 形票承接，本壳即返：
        # 不跑扫描、不写台账、不进人门——扫描与人门只属于承接票，一期一跑不双份。
        if self._patched and workflow.patched(REDIRECT_PATCH_ID):
            redirect_reason = legacy_fire_redirect_reason(ticket_id)
            if redirect_reason:
                return await self._redirect_and_finish(ticket_id, inp, period, redirect_reason)
        # inspect 段预算（声明实例段可配；缺省=宿主裁定③起步 40 条/30 分钟；分面空=
        # 回落 scan_face）。懒 import：stdlib-only 模块，workflow 沙箱内按需加载
        # （build_ticket_face 懒 import inspection_deadman 同款纪律）。
        from inspection_inspect import (DEFAULT_INSPECT_TIMEOUT_MIN,
                                        DEFAULT_MAX_FINDINGS)
        ins_cfg = dict(plan.get("inspect") or {})
        max_findings = int(ins_cfg.get("max_findings") or DEFAULT_MAX_FINDINGS)
        timeout_min = int(ins_cfg.get("timeout_min") or DEFAULT_INSPECT_TIMEOUT_MIN)
        inspect_profile = str(ins_cfg.get("profile") or "") or str(
            plan.get("scan_face") or "test")
        inspect_budget_sec = float(timeout_min) * 60.0
        # ---- setup / suite（suite 段在 inspect 前：inspect prompt 引用当期回执） ----
        run_suite = bool(plan.get("run_suite"))
        lane: Optional[Dict[str, str]] = None
        suite_section: Optional[Dict[str, Any]] = None
        extra_findings: List[Dict[str, Any]] = []
        if run_suite:
            lane, blocked = await self._setup_lane(ticket_id, inp, period, repo_root)
            if blocked is not None:
                return blocked
            self._enter("suite", "running",
                        "Running the full integration suite in the inspection lane (lane base %s)"
                      % (lane or {}).get("base_ref", ""))
            suite_section, suite_findings, teardown_note = await self._run_suite(
                ticket_id, inp, period, lane or {})
            extra_findings += suite_findings
            if suite_section.get("suite_timeout"):
                # 套件段硬超时（活动被判死）：本段必须自己点名——拆泳道前先等一小段，
                # 不与**未被回收的子进程链**抢目录（它们此刻还能写盘，抢了就会产出
                # 「admin.log ENOENT」那种把真因引偏的迟到回执，t260927-01 实况）。
                self._enter("suite", "running",
                            "Suite stage hard timeout: %s" % (suite_section.get("error") or "")[:160])
                # t260928-20：长等待前冲账（等拆除宽限窗口期间账面应可见本迁移）
                await self._ledger_flush()
                # 260929：本 sleep 是 260927 直修（49b157a）加的，**当时漏了版本门** →
                # 走这条分支的老 history（t260927-01 实况：加 sleep 之前超时的那一期）
                # 重放时「代码要定时器、history 是活动」→ Temporal 非确定 → 该票任何
                # 重放面全红（replay_check 实证，改前 HEAD 同样红）。补门修正：老 history
                # 无此标记 → 跳过等待（与它们记录的序列逐字一致）；新 run 记录标记后照旧等
                # （等待本身是那次修复的要义，不许删）。全量巡检 history 实证无一处带该定时器
                # （六期逐条查过），故本门对存量零代价。
                if workflow.patched(SUITE_TEARDOWN_GRACE_PATCH_ID):
                    await workflow.sleep(SUITE_TIMEOUT_TEARDOWN_GRACE)
                    self._enter("suite", "running",
                                "Suite stage hard timeout: waiting %ds before tearing the lane down (never "
                                "races a child chain that was not reaped)"
                                % int(SUITE_TIMEOUT_TEARDOWN_GRACE.total_seconds()))
                else:
                    self._enter("suite", "running",
                                "Suite stage hard timeout: tearing the lane down without the 120s grace "
                                "wait (pre-260927 history replay: no timer in this run's history)")
            self._enter("suite", "running", "Lane teardown: %s" % teardown_note)
            if teardown_note.startswith(TEARDOWN_RESIDUE):
                from inspection_deadman import make_finding
                extra_findings.append(make_finding(
                    "suite", "med", "Lane teardown left residue",
                    "%s | sweep entry point: inspection_trigger.py sweep-lanes --instance %s"
                    % (teardown_note, inp.instance_id), suggest=False))
            # 漏跑核查（dead-man 面①）仍在 suite 块内、不占段位（与旧轨道同源）
            extra_findings += await self._deadman_findings(inp, plan)
        # ---- lane/watchdog 面（260926）：只读扫非终态票的工作流时间线/快照 ----
        # （KI-122 追加面：巡检各面此前只读制品与代码、没有一面读票时间线，而活锁只体现在
        # 泳道层；KI-126 僵尸票同源。绝不写状态、绝不推进票——只 list + query。）
        lane_section: Optional[Dict[str, Any]] = None
        if workflow.patched(LANE_WATCHDOG_PATCH_ID):
            self._enter("inspect", "running",
                        "Read-only lane/watchdog sweep (non-terminal ticket timelines: "
                        "re-run rounds / tests-fault loop dwell / in-flight silence)")
            lane_section, lane_findings = await self._lane_watchdog(inp, plan)
            extra_findings += lane_findings
            if lane_section:
                tmp_sec = lane_section.get("tmp_fixture") or {}
                self._enter("inspect", "running",
                            "Lane/watchdog sweep done (scanned %s non-terminal tickets, %s "
                            "finding(s); %s; test-fixture temp dirs: %s dirs / oldest %sh / "
                            "%s finding(s), threshold source %s)"
                            % (lane_section.get("scanned"), lane_section.get("finding_count"),
                               lane_section.get("threshold_note") or "",
                               tmp_sec.get("dirs", "?"), tmp_sec.get("oldest_age_h", "?"),
                               tmp_sec.get("finding_count", "?"),
                               tmp_sec.get("threshold_source", "?")))
        # ---- inspect 段：只读 agent 审查（预算双闸：内部 deadline=预算−60s） ----
        # （无套件档的期不进 suite 段——suite_only 语义由源码锁钉死；档位状态并入
        # inspect 段文案可见，不静默）
        self._enter("inspect", "running",
                    "Read-only agent review (face %s, budget %d findings / %d minutes%s)"
                    % (inspect_profile, max_findings, timeout_min,
                       "" if run_suite else "; no suite tier this period (not enabled in the declaration), no suite receipt to read"))
        base_dir = repo_root or "."
        # 套件回执/agent_home/台账目录路径由活动侧按 INSPECTION_DIR 派生（worker 进程
        # 无沙箱面；workflow 体零路径计算零模块级属性读——头注纪律）。
        inspect_raw: Any = await workflow.execute_activity(
            "run_inspection_inspect",
            args=[{"instance_id": inp.instance_id, "period": period,
                   "ticket_id": ticket_id, "face": str(plan.get("scan_face") or "test"),
                   "inspect_profile": inspect_profile, "base_dir": base_dir,
                   "base_head": (lane or {}).get("base_ref", ""),
                   "project_key": getattr(inp, "project_key", ""),
                   "max_findings": max_findings, "timeout_sec": inspect_budget_sec,
                   "inspect_max_shards": int((ins_cfg.get("max_shards")) or 0),
                   "inspect_max_files_per_shard":
                       int((ins_cfg.get("max_files_per_shard")) or 0)}],
            start_to_close_timeout=inspect_start_to_close(inspect_budget_sec),
            retry_policy=RETRY_INSPECT)
        if not (inspect_raw or {}).get("ok"):
            return await self._blocked(
                ticket_id, inp, period, "inspect",
                str((inspect_raw or {}).get("error") or "inspect stage failed"), lane)
        ins_result = (inspect_raw or {}).get("result") or {}
        # ---- report 段：机械复核（证据复核/去重压制/预算/汇总——纯函数链在活动内） ----
        self._enter("report", "running",
                    "Mechanical evidence recheck (%d agent findings)" % len(ins_result.get("findings") or []))
        verify_raw: Any = await workflow.execute_activity(
            "verify_inspection_findings",
            args=[{"instance_id": inp.instance_id, "period": period,
                   "base_dir": base_dir, "findings": ins_result.get("findings") or [],
                   "max_findings": max_findings}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if not (verify_raw or {}).get("ok"):
            return await self._blocked(
                ticket_id, inp, period, "report",
                str((verify_raw or {}).get("error") or "recheck failed"), lane)
        result = (verify_raw or {}).get("result") or {}
        vmeta = dict(result.get("meta") or {})
        ins_meta = dict(ins_result.get("meta") or {})
        ins_meta.pop("output_log", None)   # agent 原始日志路径进 meta 太吵，落 agent-home 留档即可
        vmeta["inspect"] = ins_meta
        # 预算护栏（t260924-06 必做④）：缩面后 60 分钟预算内应有余量；used_sec 超 90%
        # 预算=票面点名——先报实测数据再谈调预算，不许默认再抬。
        used_sec = float(ins_meta.get("used_sec") or 0.0)
        if used_sec > 0.9 * inspect_budget_sec:
            self.face["budget_note"] = (
                "inspect stage measured %.0fs of a %.0fs budget (>90%%) — report the "
                "measurement before discussing a budget raise; do not raise it by default"
                % (used_sec, inspect_budget_sec))
        self._enter("report", "running",
                    "Recheck done (unverified %d / deduped %d / suppressed %d / truncated %s)"
                    % (vmeta.get("unverified", 0), vmeta.get("deduped", 0),
                       vmeta.get("suppressed", 0), vmeta.get("truncated", 0)))
        self.face = build_ticket_face(ticket_id, inp.instance_id, period, result,
                                      extra_findings=extra_findings, suite=suite_section,
                                      lane=lane_section)
        # 260927 code_stamp 兜底：套件段没带（无套件档的期）而漏跑活动带了 → 补进票面
        if not self.face.get("code_stamp") and self._code_stamp:
            self.face["code_stamp"] = self._code_stamp
        self.face["scan_meta"] = vmeta
        if lane:
            self.face["lane"] = dict(lane)
        return await self._finalize_and_close(ticket_id, inp, period, lane)

    async def _finalize_and_close(
        self, ticket_id: str, inp: InspectionPeriodicInput, period: str,
        lane: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        """落账 → 人门 → 收口（两条轨道共用的尾段；旧轨道搬移自 run() 主体，语句序
        不变——老票重放逐字节等价由既有 UT+场景锁）。"""
        written: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self._ledger_doc()],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if written.get("ok"):
            self.face["report_path"] = written["result"].get("path", "")
        # Human gate: closing is unreachable before approval (awaiting-human really blocks)
        self._enter("close", "awaiting-human", "Human review of the finding list: sign(gate=%s) approve=close / reject=kill the ticket" % CLOSE_GATE_ID)
        # 人门一落就再落一次账：列表可读面（离线读者）要能看见「本期已跑完、正等人审」，
        # 否则它只在 report 段那一版（stage 序列停在 report，读者以为流程没走到门）。
        # t260928-20：人门前冲账（等待窗内 watchdog/panel 可见 awaiting-human 迁移）。
        await self._ledger_flush()
        if self._patched:      # 新命令：老在途票不注入（replay 安全）
            await self._write_ledger()
        await workflow.wait_condition(lambda: self._close_sig is not None)
        self.decision = self._close_sig["decision"]  # type: ignore[index]
        self.status = "closed"
        self.face["human_gate"] = dict(self._close_sig or {})
        self._enter("close", "running", "Closing: human-gate decision=%s (who=%s)" % (self.decision, (self._close_sig or {}).get("who", "")))
        # 票面裁定落 verdicts 台账（t260916-22 要点⑥：签内 signal 只改内存票面（回放
        # 安全零活动），跨期压制消费的台账在收口时一次写齐；已收口后的裁定走 CLI 直写）。
        entries = [{"finding_id": str(f.get("id") or ""), "verdict": str(f.get("verdict")),
                    "who": str(f.get("verdict_who") or ""), "note": str(f.get("verdict_note") or ""),
                    "source_ticket": ticket_id}
                   for f in (self.face.get("findings") or [])
                   if isinstance(f, dict) and f.get("verdict")]
        if entries:
            await workflow.execute_activity(
                "write_inspection_verdicts",
                args=[{"instance_id": inp.instance_id, "period": period,
                       "entries": entries}],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        final: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self._ledger_doc()],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if final.get("ok"):
            self.face["report_path"] = final["result"].get("path", "")
        self._enter("close", "done", "Inspection ticket closed (decision=%s, findings high=%s/med=%s/low=%s)" % (
            self.decision, self.face.get("summary", {}).get("high", 0),
            self.face.get("summary", {}).get("med", 0), self.face.get("summary", {}).get("low", 0)))
        # t260928-20：收口 return 前冲账（终态迁移必须离开 pending，防硬杀丢行）
        await self._ledger_flush()
        return self.snapshot()

    # ---- t260913-02：泳道段与终态收口（全部走活动；workflow 体零 IO 零墙钟）----

    def _ledger_doc(self) -> Dict[str, Any]:
        """落账文档 = 票面 + **阶段机证据**（stage/stage_state/status/timeline）。

        为什么落账要带 timeline：`out/inspection/<票号>.json` 是本期对**离线读者**（人 /
        CLI / 运维脚本）唯一的完整面——没有阶段机证据，读者答不出「这期跑到哪、卡在哪段、
        人门过没过」（t260913-02 场景② 的 B1 子用例正是按这个口径读落账的）。workflow snapshot
        不塞 timeline：快照自己有实时 timeline，重复塞只会让每次 query 的载荷翻倍。"""
        doc: Dict[str, Any] = dict(self.face)
        doc["stage"] = self.stage
        doc["stage_state"] = self.stage_state
        doc["status"] = self.status
        doc["timeline"] = [dict(t) for t in self.timeline]
        return doc

    async def _write_ledger(self) -> None:
        """落一次账（幂等覆盖同一文件）；失败只进时间线，绝不 raise/遮蔽终态。"""
        try:
            written: Any = await workflow.execute_activity(
                "write_inspection_report", args=[self._ledger_doc()],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            if (written or {}).get("ok"):
                self.face["report_path"] = (written.get("result") or {}).get("path", "")
            else:
                self._enter(self.stage or "report", self.stage_state or "running",
                            "Ledger write failed: %s" % ((written or {}).get("error") or "unknown"))
        except Exception as e:  # noqa: BLE001
            self._enter(self.stage or "report", self.stage_state or "running",
                        "Ledger write error: %s: %s" % (type(e).__name__, e))

    async def _setup_lane(
        self, ticket_id: str, inp: "InspectionPeriodicInput", period: str, repo_root: str,
    ) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, Any]]]:
        """搭本期自有泳道：sweep（清非当期残留）→ resolve_main_head（基点）→ prepare。

        C2 次序是刻意的：`prepare_workspace` 对「目录已是本仓 worktree」走 **reused** 分支
        且不校验基点——不清残留就搭，上一期崩下来的同路径目录会让本期静默建在旧基点，
        直接顶撞验收 A。返回值 (lane, blocked_snapshot)；blocked 非空=终态已收口。"""
        self._enter("setup", "running",
                    "Inspection lane: preparing this period's working copy (instance %s period %s)" % (inp.instance_id, period))
        try:
            worktree, branch = inspection_lane_paths(inp.instance_id, period, repo_root)
        except ValueError as e:      # 输入形状问题：闭式 blocked，不进活动
            return None, await self._blocked(ticket_id, inp, period, "setup", str(e), None)
        swept: Any = await workflow.execute_activity(
            "sweep_inspection_lanes",
            args=[{"instance_id": inp.instance_id, "repo_root": repo_root,
                   "keep_period": period}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        sweep_res = (swept or {}).get("result") or {}
        self._enter("setup", "running",
                    "Residue sweep: worktrees %d / branches %d (keep=%s, deferred %d%s)"
                    % (len(sweep_res.get("removed_worktrees") or []),
                       len(sweep_res.get("removed_branches") or []), period,
                       len(sweep_res.get("deferred") or []),
                       "" if (swept or {}).get("ok") else
                       "; sweep failed: %s" % ((swept or {}).get("error") or "")))
        head: Any = await workflow.execute_activity(
            "resolve_main_head", args=[{"repo_root": repo_root}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        head_res = (head or {}).get("result") or {}
        if not (head or {}).get("ok") or not head_res.get("sha"):
            return None, await self._blocked(
                ticket_id, inp, period, "setup",
                "Base resolution failed (main HEAD): %s" % ((head or {}).get("error") or "unknown"), None)
        lane = {"worktree": worktree, "branch": branch, "base_ref": str(head_res["sha"]),
                "base_ref_name": str(head_res.get("ref") or "main"),
                # 拆除回落清扫用的锚（repo 锚定，跨项目不锚错仓）
                "instance_id": inp.instance_id, "repo_root": repo_root, "period": period}
        prep = await _prepare_lane_activity(ticket_id, worktree, branch, lane["base_ref"])
        # 260929：prepare 失败且形态是「本期泳道路径/分支被自己的残骸占住」→ 定向清本期
        # 残留后重试一次（重开同期结构性搭不起泳道的修法；判据=lane_residue_repair_plan
        # 纯函数，patch 门保老 history 重放零新命令）。
        repair: Optional[Dict[str, Any]] = None
        if not prep.get("ok") and workflow.patched(LANE_REPAIR_PATCH_ID):
            plan = lane_residue_repair_plan(prep, inp.instance_id, period, repo_root)
            if plan is not None:
                self._enter("setup", "running", plan["reason"])
                repair = await _lane_residue_repair(
                    plan, ticket_id, worktree, branch, lane["base_ref"])
                self._enter("setup", "running", _lane_repair_note(repair))
                if (repair.get("prep") or {}).get("ok"):
                    prep = repair["prep"]
                    lane["repaired"] = "1"
        if not prep.get("ok"):
            # 半建（分支可能已生）也要清：尝试拆除但不当残留报警（这次本来就没搭成）
            detail = "Lane could not be prepared (action=%s): %s" % (prep.get("action"), prep.get("error"))
            if repair is not None:
                detail += _lane_repair_detail(repair)
            return None, await self._blocked(
                ticket_id, inp, period, "setup", detail,
                dict(lane, _suppress_residue="1"))
        lane["action"] = str(prep.get("action") or "")
        self._enter("setup", "running",
                    "Lane ready: %s (%s, base %s)"
                    % (prep.get("path") or worktree, lane["action"], lane["base_ref"]))
        if "reused" in lane["action"]:
            # C2 验证面：残留未清干净时这里会显形（票面可读），不静默
            self._enter("setup", "running",
                        "Note: this period's lane is reused (the directory is already a worktree of this "
                        "repo) — residue the sweep did not cover; the base is whatever git "
                        "actually reports")
        return lane, None

    async def _run_suite(
        self, ticket_id: str, inp: "InspectionPeriodicInput", period: str,
        lane: Dict[str, str],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
        """跑全集 + 拆泳道。返回 (票面套件段, 套件发现, 拆除说明)。

        套件活动**不 raise 到 workflow 外**：跑不成是一等数据（high 发现 + 回执），
        由人审/次日消化——绝不让一次套件故障把巡检期票变成不可读的崩。
        t260916-02：activity args 增 instance_id/period（套件回执文件名按实例+期派生，
        票号 t 形化后不再能从票号反解；老 history 重放用记录的旧 args，activity 侧对
        缺键回落 legacy 只读解析，确定性不受影响）。
        260927：args 增 run_budget_sec（跑者侧总预算）与 supply_timeout_sec（供给段独立
        上限）——套件到点自行收口返回，供给到点点名报红，两者都不再等 Temporal 判死；
        异常分支两态具名（超时 vs 一般故障，见 suite_failure_receipt），超时后拆泳道前先
        等一小段（不与被判死后仍存活的子进程抢目录，免得产出 ENOENT 那种误导回执）。"""
        from inspection_deadman import suite_findings, suite_section
        receipt: Dict[str, Any]
        try:
            raw: Any = await workflow.execute_activity(
                "run_inspection_suite",
                args=[{"ticket_id": ticket_id, "worktree": lane.get("worktree", ""),
                       "base_ref": lane.get("base_ref", ""),
                       "instance_id": inp.instance_id, "period": period,
                       "run_budget_sec": float(SUITE_RUN_BUDGET_SEC),
                       "supply_timeout_sec": float(INTEG_SUPPLY_TO_SEC),
                       "suite_timeout_sec": float(SUITE_TO.total_seconds())}],
                start_to_close_timeout=SUITE_TO, retry_policy=RETRY_SUITE)
            if (raw or {}).get("ok"):
                receipt = dict((raw or {}).get("result") or {})
            else:
                receipt = {"error": str((raw or {}).get("error") or "suite activity failed"),
                           "details": [], "ran": 0, "passed": 0, "failed": 0, "env_fail": 0}
        except Exception as e:  # noqa: BLE001——活动故障=可见数据（high 发现），不是期票崩塌
            receipt = suite_failure_receipt(e, SUITE_TO.total_seconds())
        findings = suite_findings(receipt)
        teardown_note = await self._teardown(ticket_id, lane, report_residue=True)
        return suite_section(receipt), findings, teardown_note

    async def _teardown(self, ticket_id: str, lane: Optional[Dict[str, str]],
                        report_residue: bool) -> str:
        """拆泳道（幂等）。任何失败都只回报文字，绝不 raise、绝不遮蔽终态语义。

        主路径=复用 teardown_lane（幂等：worktree remove --force + branch -D）；但它锚在
        worker 的 REPO_ROOT，**跨项目/跨仓泳道会锚错仓**（KI-074/075 同族：路径写死即断）。
        所以回执不干净时回落到 repo 锚定的定向 sweep（remove_period=本期，只清本期，
        不碰并发期/开发泳道）——残留收敛仍然有界且可读，不是静默放过。"""
        if not lane or not lane.get("worktree") or not lane.get("branch"):
            return "%s: no lane (nothing to tear down)" % TEARDOWN_OK
        residue = ""
        try:
            td: Any = await workflow.execute_activity(
                teardown_lane,
                MergeArgs(ticket_id=ticket_id, worktree=lane["worktree"], branch=lane["branch"]),
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            ok = bool(getattr(td, "ok", False)) if not isinstance(td, dict) else bool(td.get("ok"))
            err = getattr(td, "error", "") if not isinstance(td, dict) else str(td.get("error") or "")
            if ok and not err:
                return "%s: cleaned (teardown_lane: worktree+branch, zero residue)" % TEARDOWN_OK
            residue = err or "teardown receipt ok but with a warning"
        except Exception as e:  # noqa: BLE001——拆除故障=残留（有界收敛：定向 sweep/次日/CLI）
            residue = "teardown activity error %s: %s" % (type(e).__name__, e)
        # 回落：repo 锚定的定向清扫（只清本期）
        fallback = ""
        try:
            sw: Any = await workflow.execute_activity(
                "sweep_inspection_lanes",
                args=[{"instance_id": lane.get("instance_id", ""),
                       "repo_root": lane.get("repo_root", ""),
                       "keep_period": "", "remove_period": lane.get("period", "")}],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            res = (sw or {}).get("result") or {}
            if ((sw or {}).get("ok") and (res.get("removed_worktrees")
                                          or res.get("removed_branches")
                                          or res.get("removed_dir_stubs"))):
                return ("%s: cleaned (fell back to the repo-anchored targeted sweep after "
                    "teardown_lane residue: %s; original report %s)") % (TEARDOWN_OK, 
                    "worktree %d / 分支 %d / 目录壳 %d" % (
                        len(res.get("removed_worktrees") or []),
                        len(res.get("removed_branches") or []),
                        len(res.get("removed_dir_stubs") or [])),
                    residue[:160])
            fallback = str((sw or {}).get("error") or "targeted sweep found nothing to clean")
        except Exception as e:  # noqa: BLE001
            fallback = "targeted sweep error %s: %s" % (type(e).__name__, e)
        if not report_residue:
            return "%s: teardown attempted (lane never came up; residue warning disabled): %s" % (TEARDOWN_OK, residue)
        return "%s: %s; fallback sweep also left residue: %s" % (TEARDOWN_RESIDUE, residue, fallback)

    async def _deadman_findings(self, inp: "InspectionPeriodicInput",
                                plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        """漏跑核查（进本期票面）。活动失败=显式 high 发现（漏报面本身不能静默）。"""
        from inspection_deadman import make_finding
        try:
            raw: Any = await workflow.execute_activity(
                "run_inspection_deadman",
                args=[{"instance_id": inp.instance_id, "cron": plan.get("cron") or "",
                       "lookback_days": DEADMAN_LOOKBACK_DAYS,
                       "tz": plan.get("tz") or ""}],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        except Exception as e:  # noqa: BLE001
            return [make_finding("deadman", "high", "Dead-man check did not run",
                             "run_inspection_deadman failed: %s: %s (this period's "
                             "missed-period verdict is absent)"
                             % (type(e).__name__, e), suggest=False)]
        if not (raw or {}).get("ok"):
            return [make_finding("deadman", "high", "Dead-man check did not run",
                             str((raw or {}).get("error") or "unknown"), suggest=False)]
        res = (raw or {}).get("result") or {}
        # 260927 code_stamp：漏跑活动带回的代码身份暂存（无套件档的期也能上票面；
        # 值来自活动结果=重放同值，安全）
        self._code_stamp = str(res.get("code_stamp") or self._code_stamp)
        findings = res.get("findings") if isinstance(res.get("findings"), list) else []
        if res.get("malformed"):
            findings = findings + [make_finding(
                "deadman", "med", "Ledger entries malformed: %d" % len(res["malformed"]),
                "files under out/inspection with this instance's prefix but no period "
                "lexeme: %s"
                % "、".join(str(x) for x in res["malformed"][:10]), suggest=False)]
        return findings

    async def _lane_watchdog(self, inp: "InspectionPeriodicInput",
                             plan: Dict[str, Any]):
        """lane/watchdog 面（260926，KI-122 追加面 / KI-126 同源）：只读扫非终态票的
        工作流时间线/快照 + **测试夹具临时目录水位**（第四判据）→ (票面 lane 段, 发现清单)。

        活动失败=显式 high 发现（**这个面本身不能静默**——否则「巡检没发现」的盲区会
        再长回来）；阈值档来自声明 plan.watchdog（缺省/畸形的回落与来源点名由纯函数面
        resolve_thresholds / resolve_tmp_thresholds 给，随 lane 段上票面）。
        第四判据是**宿主级**发现（不挂任何票），随活动回执的 tmp_fixture 段并进同一发现
        清单与同一 lane 段计数（计数合并单点=merge_lane_section，段与清单不许漂移）。"""
        from inspection_deadman import make_finding
        try:
            raw: Any = await workflow.execute_activity(
                "run_inspection_lane_watchdog",
                args=[{"watchdog": dict(plan.get("watchdog") or {}),
                       "scan_budget_sec": float(WATCHDOG_SCAN_BUDGET_SEC)}],
                start_to_close_timeout=LANE_WATCHDOG_TO, retry_policy=RETRY_LANE_WATCHDOG)
        except Exception as e:  # noqa: BLE001
            return None, [make_finding(
                "lane", "high", "Lane/watchdog sweep did not run",
                "run_inspection_lane_watchdog failed: %s: %s (this period has no verdict "
                "on stuck in-flight tickets — re-run the inspection period)"
                % (type(e).__name__, e), suggest=False)]
        if not (raw or {}).get("ok"):
            return None, [make_finding(
                "lane", "high", "Lane/watchdog sweep did not run",
                str((raw or {}).get("error") or "unknown"), suggest=False)]
        res = (raw or {}).get("result") or {}
        findings = res.get("findings") if isinstance(res.get("findings"), list) else []
        # 票面段：优先吃活动侧算好的**合并段**（票级三族 + 宿主水位；计数合并单点在纯函数
        # 面，工作流侧零算法/零新 import）；老在途回执没有该字段 → 退回票级段，逐字段同旧形。
        section = (res.get("section_merged") if isinstance(res.get("section_merged"), dict)
                   else res.get("section") if isinstance(res.get("section"), dict) else None)
        meta = res.get("meta") if isinstance(res.get("meta"), dict) else {}
        # 第四判据（夹具临时目录水位）：宿主级发现挂进同一发现清单（段计数已由活动合并）。
        # 缺字段/畸形=当没有（老 worker 回执形态），此时清单与段逐字段与旧实现同形。
        tmp = res.get("tmp_fixture") if isinstance(res.get("tmp_fixture"), dict) else {}
        tmp_findings = [f for f in (tmp.get("findings") or []) if isinstance(f, dict)]
        if tmp_findings:
            findings = findings + tmp_findings
        # 查询/枚举面的故障点名进票面（单票快照查不到=点名，绝不静默当「这票没问题」）
        errs = [str(x) for x in (meta.get("unreadable") or [])]
        # 读失败分类点名（t261001-05，单点文案在 lw.unreadable_finding_specs）：两类分开
        # 计数分开文案——瞬态（超时无应答，已重试一次）=巡检期故障证据；永久（如
        # "Workflow Task in failed state"）=需要人。fail-closed 不变：读不到的票绝不静默
        # 当「这票没问题」。老回执（无分类键）=单条旧形文案（不猜类，重放确定性不破）。
        errs = [str(x) for x in (meta.get("unreadable") or [])]
        if errs:
            from inspection_lane_watchdog import unreadable_finding_specs
            findings = findings + [make_finding(
                "lane", s["severity"], s["subject"], s["evidence"], suggest=False)
                for s in unreadable_finding_specs(meta)]
        skipped = [str(x) for x in (meta.get("errors") or [])]
        if skipped:
            findings = findings + [make_finding(
                "lane", "low", "Lane/watchdog sweep skipped %d ticket(s)" % len(skipped),
                "out-of-scope non-terminal tickets (project not in the registry / no "
                "ProjectKey identity) — named for completeness, not a stuck-state verdict: %s"
                % "; ".join(skipped[:10]), suggest=False)]
        if meta.get("enum_note"):
            findings = findings + [make_finding(
                "lane", "low", "Lane/watchdog sweep was truncated",
                str(meta["enum_note"]), suggest=False)]
        return section, findings

    async def _redirect_and_finish(self, ticket_id: str, inp: "InspectionPeriodicInput",
                                   period: str, redirect_reason: str) -> Dict[str, Any]:
        """旧形 fire 自愈重定向（t260917-02 修复①核心）。

        借用清单（review R1-A 落地版）：spawn_inspection_period → open_period_ticket 的
        语义**全数继承**（并发去重全链/指针三态/验票不可判让位/无 SA 可信 dedup/SA 三件套
        盖章），本方法零重实现；dedup_source 三值（sa_query|pointer|already_started）逐字
        透传进 face.redirect + timeline（可辨不混装）。
        输入面取舍：face 不采信旧 payload（空传 → 活动按当前声明决议 scan_face，守「改
        声明即改行为」）；身份缺项由活动侧回退链补齐（args → plan.instance_project_key →
        fail-closed 显式失败）。
        终态两态：成功=redirected（face.redirect 结构化回执；本壳不跑扫描/不写台账/
        不进人门）；失败=blocked（**不落账**——该期无本壳台账，deadman 漏跑是唯一绊线，
        与 deadman 跳火点名成链）。"""
        self._enter("setup", "running", redirect_reason)
        spawn_res: Dict[str, Any] = await workflow.execute_activity(
            "spawn_inspection_period",
            args=[{"instance_id": inp.instance_id,
                   "face": "",
                   "repo_root": str(getattr(inp, "repo_root", "") or ""),
                   "project_key": str(getattr(inp, "project_key", "") or ""),
                   "decl_path": str(getattr(inp, "decl_path", "") or ""),
                   "period": period}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if (spawn_res or {}).get("ok"):
            result = (spawn_res or {}).get("result") or {}
            target = str(result.get("ticket_id") or "")
            deduped = bool(result.get("deduped"))
            source = str(result.get("dedup_source") or "-")
            self._enter("setup", "redirected",
                        "Legacy-fire redirect done: this period is carried by t-shaped ticket %s (%s; "
                        "dedup_source=%s)"
                        % (target or "?",
                           "deduped: reusing the existing ticket" if deduped else "newly opened", source))
            self.face["redirect"] = {"from": ticket_id, "to": target, "deduped": deduped,
                                     "dedup_source": source, "period": period,
                                     "instance": inp.instance_id, "reason": redirect_reason}
            return self.snapshot()
        return await self._blocked(
            ticket_id, inp, period, "setup",
            "Redirect failed: %s | spawn receipt: %s | this shell writes no ledger — the "
            "period's dead-man miss is the only tripwire"
            % (redirect_reason, str((spawn_res or {}).get("error") or "unknown")),
            None, write_ledger=False)

    async def _blocked(self, ticket_id: str, inp: "InspectionPeriodicInput", period: str,
                       stage: str, reason: str, lane: Optional[Dict[str, str]],
                       write_ledger: bool = True) -> Dict[str, Any]:
        """终态收口：blocked 票面 + **落账**（dead-man 面：不落账的 blocked 在列表面不可见）
        + 泳道拆除（幂等；搭不起来的那条路径只尝试不报警）。"""
        self.status = "blocked"
        self._enter(stage, "blocked", reason)
        self.face = {"ticket_id": ticket_id, "kind": "inspection", "instance_id": inp.instance_id,
                     "period": period, "red_line": INSPECTION_RED_LINE,
                     "heartbeat": False, "summary": {}, "findings": [],
                     "suggested_fix_tickets": [], "blocked_reason": reason, "stage": stage}
        if lane:
            suppress = bool(lane.pop("_suppress_residue", ""))
            note = await self._teardown(ticket_id, lane, report_residue=not suppress)
            self.face["lane"] = {k: v for k, v in lane.items() if not k.startswith("_")}
            self.face["lane_teardown"] = note
            self._enter(stage, "blocked", "Lane teardown: %s" % note)
        # blocked 也落账（dead-man 面：不落账的 blocked 在列表面不可见），并带阶段机证据；
        # 老在途票不注入该新命令（replay 安全；它们的 blocked 面仍走票① 的纯快照语义）。
        # write_ledger=False（t260917-02 重定向失败路径）：本壳名下不落账——它的台账名
        # （实例,期）与承接票相同，落了会把真票账盖成 blocked 面）；该期可见性交给
        # deadman 漏跑绊线（与 deadman 跳火点名成链）。
        # t260928-20：终态前冲账（blocked 是可见终态，迁移不得留在 pending 里等硬杀）。
        # 老实例 pending 恒空=零活动命令（重放零变化）。
        await self._ledger_flush()
        if self._patched and write_ledger:
            await self._write_ledger()
        return self.snapshot()


# ========================================================================================
# Ticket-count watcher（t260911-02）：every-n-tickets / race-first 的通用调度器。
# 每个启用的计数 kind 实例一个；workflow id=inspection-watcher-<instance>（从声明确定
# 导出——schedule-up 幂等拉起/复活的前提，C-2）。语义按方案 R2：计数越桶先触发
# （期号=YYYYMMDD-<bucket>）；cron 到点触发并复位基线（期号=纯 YYYYMMDD）；双侧规则
# 单点在 inspection_ticket_count.decide（单测面）。确定性纪律同主 workflow：workflow
# 体零 IO 零钟表（计数与开票都在 activity，唯一时间源=workflow.now()）。
# ========================================================================================

@dataclass
class InspectionWatcherInput:
    """Watcher 输入，全部由声明 spec 导出（schedule-up 是唯一生产侧拉起点）。
    baseline / cron_anchor / triggered_total 三字段跨 continue_as_new 携带状态
    （无界历史治理：每 WATCHER_MAX_ITERATIONS 轮换一代历史）。"""

    instance_id: str
    n: int = 0
    cron: str = ""
    scan_face: str = "test"
    repo_root: str = ""
    # 声明来源（t260913-02）：watcher 是计数 kind 的开票拉起点，它开的票同样要让
    # 「调度/触发用的声明」与「workflow 运行期读的声明」同源（否则隔离台夹具实例
    # 在 worker 缺省声明里不存在 → 票被 blocked → 同桶重复触发不去重，t260911-02
    # 子用例 g2 实测）。缺省空=worker 侧缺省/env（生产缺省即此形态）。
    decl_path: str = ""
    project_key: str = ""
    # 实例级项目身份（t260915-20，命名与上方 project_key 计数源键**显式区分**）：
    # 本 watcher 开的期票归属哪个项目——schedule-up 起票面注入、watcher 开票 args
    # 透传、activity 写进 InspectionPeriodicInput.project_key + 盖 ProjectKey SA，
    # 全链用身份键，绝不串计数源键（身份≠计数源，串键=静默错挂）。
    # 缺省空=老 history 解码安全（face/decl_path 同款纪律）；空身份+空 repo_root 的
    # 期票会被无主守卫拦成 blocked（跨部署存量旧 watcher 的可见过渡窗，README 迁移步④）。
    instance_project_key: str = ""
    poll_seconds: float = 60.0
    baseline: int = -1                 # -1 = 基线未立（首轮成功计数即立，不回看历史票）
    cron_anchor: str = ""              # ISO datetime；空=cron 侧未激活
    triggered_total: int = 0


WATCHER_MAX_ITERATIONS = 500   # continue_as_new 节流（默认 60s 轮询≈每 8.3 小时换一代）


@workflow.defn
class InspectionTicketCountWatcherWorkflow(TicketEventLedgerMixin):
    """常驻轮询调度器：计数 → 纯决策（decide）→ 开期票（票号幂等=一票一期去重兜底）。
    取消/失败终态随 workflow 自身收敛（Temporal 持久化）；死亡+复活=schedule-up
    （inspection_trigger.py）——本票新引入的可死机制的 KI-049 对答。

    t260928-20：引擎级账面发射器（`_ledger_scope="engine"`——调度器不是票，行落
    引擎所属项目账本，活动侧解析 engine-owner）。入队点=本类 _enter（迁移本就稀疏：
    启动 / 计数失败 / 触发），冲刷点=每轮 sleep 前 + continue_as_new 前。换代
    （continue_as_new）天然换 run_id——账面 seq/run_id 每代独立，idem 不会跨代串键
    （运维侧读到「多代各一行 poll running」是预期形态，不是重复）。"""

    _ledger_scope = "engine"

    def __init__(self) -> None:
        self.last_count: int = -1
        self.last_error: str = ""
        self.last_trigger: Dict[str, Any] = {}
        self.iterations: int = 0
        self._baseline: int = -1
        self._triggered_total: int = 0
        self._next_fire: Optional[datetime] = None
        self._last_event: Dict[str, Any] = {}

    def _enter(self, stage: str, state: str, reason: str) -> None:
        at = workflow.now().isoformat(timespec="seconds")
        self._last_event = {"at": at, "stage": stage, "state": state, "reason": reason}
        # t260928-20：引擎行入队（_ledger_note 便桥走 mixin 同一入队点；patched 门内
        # ——老 watcher 实例重放零变化）
        self._ledger_note(stage, state, reason)

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        """活性/运维面（`watcher` 子命令消费）：没有这份快照，死 watcher 不可见
        （KI-049 族纪律）。"""
        return {
            "id": workflow.info().workflow_id,
            "kind": "inspection-watcher",
            "last_count": self.last_count,
            "last_error": self.last_error,
            "last_trigger": self.last_trigger,
            "triggered_total": self._triggered_total,
            "baseline": self._baseline,
            "next_cron_fire": self._next_fire.isoformat(timespec="seconds") if self._next_fire else "",
            "iterations": self.iterations,
            "last_event": self._last_event,
        }

    @workflow.run
    async def run(self, inp: InspectionWatcherInput) -> Dict[str, Any]:
        # 输入形状 fail-closed：畸形 watcher 绝不「跑着但什么都不做」
        if not inp.instance_id or not inp.project_key or inp.n < 1:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(
                "watcher 输入非法：instance=%r project_key=%r n=%r"
                % (inp.instance_id, inp.project_key, inp.n), non_retryable=True)
        from inspection_ticket_count import decide, next_cron_fire
        self._baseline = inp.baseline
        self._triggered_total = inp.triggered_total
        anchor: datetime = (datetime.fromisoformat(inp.cron_anchor)
                            if inp.cron_anchor else workflow.now())
        self._next_fire = next_cron_fire(inp.cron, anchor) if inp.cron else None
        self._enter("poll", "running", "Counting watcher running (instance %s, n=%d, source=archive-dir:%s, "
                    "cron=%s)" % (inp.instance_id, inp.n, inp.project_key, inp.cron or "none"))
        while True:
            res: Dict[str, Any] = await workflow.execute_activity(
                "count_archived_tickets",
                args=[{"project_key": inp.project_key}],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            now = workflow.now()
            cron_due = False
            if res.get("ok"):
                self.last_count = int((res.get("result") or {}).get("count", -1))
                self.last_error = ""
                if self._baseline < 0:
                    # 初始基线=0（存量计数按桶即判：当前计数已达 k*n 即触发当期；watcher
                    # 死亡复活后同桶重放由票号幂等去重兜底，不会双开票）
                    self._baseline = 0
                if self._next_fire is not None and now >= self._next_fire:
                    cron_due = True
            else:
                # 计数失败：如实进快照，绝不拿旧计数或 0 假判（「数不了」≠「0 张」）
                self.last_error = str(res.get("error") or "count failed")
                self._enter("poll", "running", "count failed (no trigger decision this round): %s" % self.last_error)
            if res.get("ok") and self._baseline >= 0:
                d = decide(self.last_count, self._baseline, inp.n, cron_due, now)
                if d["trigger"]:
                    # 开票 args 全链带实例级身份键（t260915-20 R2）：activity 端
                    # InspectionPeriodicInput.project_key + ProjectKey SA 都取它，
                    # 与计数源 project_key（上面喂 count 的键）作用域不同不互串。
                    opened: Dict[str, Any] = await workflow.execute_activity(
                        "trigger_inspection_period",
                        args=[{"instance_id": inp.instance_id, "period": d["period"],
                               "repo_root": inp.repo_root, "scan_face": inp.scan_face,
                               "decl_path": inp.decl_path,
                               "instance_project_key": inp.instance_project_key}],
                        start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
                    deduped = bool((opened.get("result") or {}).get("deduped"))
                    self.last_trigger = {"kind": d["trigger"], "period": d["period"],
                                         "deduped": deduped}
                    self._triggered_total += 1
                    self._baseline = d["baseline"]
                    anchor = now                          # R2：任一侧触发都推进 cron 相位
                    self._next_fire = next_cron_fire(inp.cron, anchor) if inp.cron else None
                    self._enter("trigger", "running",
                                "%s trigger -> period %s (deduped=%s, baseline=%d)"
                                % (d["trigger"], d["period"], deduped, self._baseline))
            self.iterations += 1
            if self.iterations >= WATCHER_MAX_ITERATIONS:
                # 换代显式携带 instance_project_key（t260915-20：换代不丢身份——
                # 丢了身份，本代之后开的票全部撞无主守卫=blocked）
                workflow.continue_as_new(InspectionWatcherInput(
                    instance_id=inp.instance_id, n=inp.n, cron=inp.cron,
                    scan_face=inp.scan_face, repo_root=inp.repo_root,
                    decl_path=inp.decl_path,
                    project_key=inp.project_key,
                    instance_project_key=inp.instance_project_key,
                    poll_seconds=inp.poll_seconds,
                    baseline=self._baseline,
                    cron_anchor=anchor.isoformat(timespec="seconds"),
                    triggered_total=self._triggered_total))
            # t260928-20：换代/轮询前冲账（continue_as_new 后 pending 即亡——
            # 本代迁移必须在换代命令前投出；轮询 sleep 前同理，账面延迟有界）
            await self._ledger_flush()
            await workflow.sleep(timedelta(seconds=inp.poll_seconds))


# ========================================================================================
# spawner：cron 调度 → 真票 的起票薄壳（t260916-02）
#   Temporal Schedule 的 action 参数是静态的，铸不了「起票瞬间分配」的 t 形号——
#   故调度目标改为本 workflow（id=inspection-spawn-<实例>，固定，重叠 SKIP 同现状），
#   体=一个 activity（spawn_inspection_period：期号铸取+铸号去重+盖 SA+起真票）即完。
#   spawner 是调度器不是票：绝不进 client.INSPECTION_BOARD_TYPES（同 watcher）。
# ========================================================================================

@dataclass
class InspectionSpawnInput:
    """spawner 输入（调度面声明决议的静态部分；期号/票号都由 activity 起票时刻定）。

    decl_path 恒空（cron 调度形态）：spawner 每 fire 都读 worker 当前声明（聚合解析）
    ——「改声明即改行为」的调度语义不变（与旧 action 直发 InspectionPeriodicWorkflow
    同一纪律；显式 --decl-path 只属手动/夹具路径）。"""

    instance_id: str
    face: str = "test"
    repo_root: str = ""
    project_key: str = ""
    decl_path: str = ""


SPAWN_WORKFLOW_TYPE_NAME = "InspectionPeriodicSpawnWorkflow"


def spawn_workflow_id(instance_id: str) -> str:
    """spawner workflow id（形状单点，同 watcher_workflow_id 纪律：同声明重跑 schedule-up
    必命中同一 workflow——幂等 update 的前提）。"""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        raise ValueError("spawn id 组成非法：instance=%r（小写 slug）" % instance_id)
    return "inspection-spawn-%s" % instance_id


@workflow.defn
class InspectionPeriodicSpawnWorkflow(TicketEventLedgerMixin):
    """每期一票的起票薄壳（调度器，非票）。体=单 activity 调用；activity 失败 →
    ApplicationError(non_retryable) → schedule recent_actions 可见（绝不静默吞火）。

    t260928-20：引擎级账面发射器（`_ledger_scope="engine"`；行落引擎所属项目账本，
    活动侧解析 engine-owner）。短命壳（一进一出）：start 一行 + 结果一行，return 前
    一次冲账即尽（seq 只记真实迁移，不凑数）。"""

    _ledger_scope = "engine"

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        return {"id": workflow.info().workflow_id, "kind": "inspection-spawner"}

    @workflow.run
    async def run(self, inp: InspectionSpawnInput) -> Dict[str, Any]:
        # 输入形状 fail-closed：无实例名的 spawner 绝不「跑着但什么都不做」
        if not inp.instance_id:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError("spawn 输入非法：instance 空", non_retryable=True)
        self._ledger_note("spawn", "running",
                          "Spawning period ticket (instance %s, face=%s, project=%s)"
                          % (inp.instance_id, inp.face, inp.project_key or ""))
        res: Dict[str, Any] = await workflow.execute_activity(
            "spawn_inspection_period",
            args=[{"instance_id": inp.instance_id, "face": inp.face,
                   "repo_root": inp.repo_root, "project_key": inp.project_key,
                   "decl_path": inp.decl_path}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if not (res or {}).get("ok"):
            self._ledger_note("spawn", "failed",
                              "Spawn failed: %s" % str((res or {}).get("error") or "起票失败（无事由）")[:200])
            await self._ledger_flush()
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(str((res or {}).get("error") or "起票失败（无事由）"),
                                   non_retryable=True)
        result: Dict[str, Any] = (res or {}).get("result") or {}
        # KI-191（t261002-11）回执点名修：①根因=读错键（`ticket`，实际键是
        # `ticket_id`）⇒ 每条回执都打 `ticket=?`，t261002-01 占坑事故多日无人发现——
        # 现在必须点名去重到哪张票；②补占坑时刻（slot_taken_at；deduped 票无章时
        # 如实 unknown，不伪造）；③夹具标记可见（fixture 占坑对真班透明）。
        self._ledger_note(
            "spawn", "done",
            "Period ticket spawned (instance %s, ticket=%s, deduped=%s, "
            "slot_taken_at=%s, fixture=%s%s)"
            % (inp.instance_id,
               str(result.get("ticket_id") or "?"),
               bool(result.get("deduped")),
               str(result.get("slot_taken_at") or "unknown"),
               bool(result.get("fixture")),
               (", skipped_fixture_tickets=%s"
                % ",".join(result.get("skipped_fixture_tickets") or []))
               if result.get("skipped_fixture_tickets") else ""))
        # t260928-20：return 前冲账（短命壳收口点=唯一冲刷点）
        await self._ledger_flush()
        return result


# ========================================================================================
# t260916-22：旧轨道（静态扫描）——scan 段已退役（run_inspection_scan 调用点=0），本
# 函数从 run() 主体**原样外提**（语句序不变，self→wf）：唯一消费者=老在途票 replay
# （SUITE 门开而 INSPECT 门未开的过渡窗票、SUITE 门未开的老票）。外提同时让 "scan"
# 段位字面离开 InspectionPeriodicWorkflow 类块——源码锁（test_t260916_05）的类块
# _enter 字面量全集只认新轨道段位，legacy 不进锁面（新票不可能再走进该段）。
# ========================================================================================

async def _run_legacy_period_flow(wf: "InspectionPeriodicWorkflow",
                                  inp: InspectionPeriodicInput, repo_root: str,
                                  ) -> Dict[str, Any]:
    """票① 旧路径（scan → report → close）：【已退役（t260916-22），仅存服务 replay】。"""
    # 无主票守卫（t260915-20，PROJECT_PATCH_ID 新命令）：项目身份与 repo_root 双空
    # 的新票 → blocked 终态点名（可见不静默）——杀「静默回落引擎仓扫描」的最后残窗
    # （旧调度 payload 在 R1 修复+schedule-up 重跑后收敛为零，守卫兜住漏刷的口子）。
    # 老 in-flight 票：PROJECT_PATCH_ID patched()=False 走旧路径，零影响。
    if wf._patched and workflow.patched(PROJECT_PATCH_ID):
        guard = unowned_guard_reason(getattr(inp, "project_key", ""), repo_root)
        if guard:
            # 期号铸取在守卫之后（守卫票不值得跑 plan 活动）；票号=真实 workflow id，
            # 期号如实用输入期（调度路为空、手动路为触发期）——blocked 落账可索引。
            return await wf._blocked(
                workflow.info().workflow_id, inp, str(inp.period or ""), "guard", guard, None)
    plan: Dict[str, Any] = {}
    plan_raw: Any = None
    if wf._patched:
        # ---- 声明决议（t260913-02）：本期跑不跑套件由**当前声明**说了算，不进输入 payload。
        #      先于期号铸取：期号要按声明 tz 的日历日取（见 period_key_in_tz，P1）----
        plan_raw = await workflow.execute_activity(
            "resolve_inspection_plan",
            args=[{"instance_id": inp.instance_id, "decl_path": inp.decl_path}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        plan = (plan_raw or {}).get("result") or {}
    # ---- 期号铸取（t260913-02 验收 P1）：声明 tz 的日历日。workflow.now() 是 UTC，
    # 声明 tz 后的触发时刻会落在 UTC 前一日（07:30 Asia/Shanghai = 前一日 23:30Z）——
    # 不换算则调度票期号恒比本地日历早一天，dead-man 期望键（同口径核算）恒等于
    # 「当期自己」→ 每张日报票一条 high 假漏跑 + CLI 每天 exit=1。旧口径（tz 空 /
    # 未 patched 的老票）= UTC/进程日历不变；两侧（铸号/漏跑核算）走同一条回落链。
    period = inp.period or (
        period_key_in_tz(workflow.now(), str(plan.get("tz") or ""))
        if wf._patched else period_key(workflow.now()))
    # 票号 = 真实 workflow id（t260916-02：起票侧经 inspection_ticketing.open_period_ticket
    # 铸 t 形号并显式去重（实例+期号 SA），id 不再编码实例/期——老在途票（旧形 id）重放
    # 时该值同样是旧形 id，输出逐字节不变，replay 安全零新 patch 门）。
    validate_period_key(inp.instance_id, period)
    ticket_id = workflow.info().workflow_id
    if wf._patched and not (plan_raw or {}).get("ok"):
        return await wf._blocked(
            ticket_id, inp, period, "setup",
            "Declaration resolution failed: %s" % ((plan_raw or {}).get("error") or "unknown"), None)
    run_suite = bool(plan.get("run_suite"))
    lane: Optional[Dict[str, str]] = None
    suite_section: Optional[Dict[str, Any]] = None
    extra_findings: List[Dict[str, Any]] = []
    if run_suite:
        lane, blocked = await wf._setup_lane(ticket_id, inp, period, repo_root)
        if blocked is not None:
            return blocked
    # C4（t260910-09 review）：时间线文案带 face 值——新面票不再误写「测试面」；face 字段透传进 activity 分派
    wf._enter("scan", "running", "%s-face scan (instance %s period %s)" % (inp.face, inp.instance_id, period))
    scan_result: Dict[str, Any] = await workflow.execute_activity(
        "run_inspection_scan",
        args=[{"repo_root": inp.repo_root, "scenarios_path": inp.scenarios_path,
               "face": inp.face}],
        start_to_close_timeout=SCAN_TO, retry_policy=RETRY)
    if not scan_result.get("ok"):
        return await wf._blocked(
            ticket_id, inp, period, "scan",
            str(scan_result.get("error") or "scan failed"), lane)
    if run_suite:
        # 漏跑核查（dead-man 面①：进本期票面；面②=inspection_trigger.py deadman）
        extra_findings += await wf._deadman_findings(inp, plan)
    if run_suite:
        wf._enter("suite", "running",
                  "Running the full integration suite in the inspection lane (lane base %s)"
                      % (lane or {}).get("base_ref", ""))
        suite_section, suite_findings, teardown_note = await wf._run_suite(
            ticket_id, inp, period, lane or {})
        extra_findings += suite_findings
        wf._enter("suite", "running", "Lane teardown: %s" % teardown_note)
        if teardown_note.startswith(TEARDOWN_RESIDUE):
            # 残留=可恢复垃圾（既有 teardown 语义：不拦收口），但要可见（验收 D 的
            # 「不得静默」）；不进开票建议——它不是代码缺陷，清场入口=sweep/CLI。
            from inspection_deadman import make_finding
            extra_findings.append(make_finding(
                "suite", "med", "Lane teardown left residue",
                "%s | sweep entry point: inspection_trigger.py sweep-lanes --instance %s"
                % (teardown_note, inp.instance_id), suggest=False))
    # 时间线文案：无追加发现时与票①逐字一致（零回归面）；有追加才展开两段计数
    scan_n = len(scan_result["result"].get("findings") or [])
    wf._enter("report", "running",
              ("Finding list posted to the ticket face (scan %d + extra %d)" % (scan_n, len(extra_findings)))
              if extra_findings else ("Finding list posted to the ticket face (%d items)" % scan_n))
    wf.face = build_ticket_face(ticket_id, inp.instance_id, period, scan_result["result"],
                                extra_findings=extra_findings, suite=suite_section)
    if lane:
        # 跨项目/隔离台的基点证据进票面（验收 A：基点=开跑时 main HEAD）
        wf.face["lane"] = dict(lane)
    return await wf._finalize_and_close(ticket_id, inp, period, lane)


# ════════════════════════════════════════════════════════════════════════════════
# t260925-01：产出型巡检 workflow（与 dev-lane 分链；段序=setup → produce → 自检
# → 报告(含 diff) → 人审门 approve=merge / reject=discard）。
#
# 与 InspectionPeriodicWorkflow 的分工：报告链（本文件上方类）不动一行——produce
# 是**独立 @workflow.defn 类**（方案备选 A 否决理由：塞进同一 defn 会把老在途票
# replay 面拖进回归风险；工单明令「需要和 devlane 不同的工作流」）。复用面与故障
# 模式取舍清单（create_plan v2 C1，9 项）在方案文件，此处只落差异点：
#   - 人审唯一合并入口：sign 门（produce gate id，不带旧字面值防串门）；approve 走
#     既有 merge 活动（squash、一票一 commit），reject 走 teardown_lane 丢弃（报告
#     先行落账，diff 留痕可追溯——台账在门前后各写一次）；
#   - 保护面同票授权：authorize 门（清单必须是本期 protected_overlap 子集，窄通）；
#     授权后 produce 段对授权文件复跑一次，再回人审门；
#   - 拒收三态（out_of_root / zero_change_error / 未授权保护面）任一在场时 approve
#     信号拒收点名——fail-closed，绝不带红灯落 main；
#   - 队列口径（KI-113）：produce 起票走 per-ticket 队列（open_period_ticket
#     per_ticket_queue=True），不落共享队列。
# ════════════════════════════════════════════════════════════════════════════════

PRODUCE_DEFAULT_TIMEOUT_SEC = 1800.0
# 产出型巡检两门 id（字面真源在本文件——workflow 消费方；produce 纯函数层的同名
# 常量是其缺省参数镜像，等值由 UT 锁死）。不带报告链 CLOSE_GATE_ID 字面值（防串门）。
PRODUCE_CLOSE_GATE_ID = "inspection-produce-close"
PRODUCE_AUTHORIZE_GATE_ID = "inspection-produce-protect-authorize"


@dataclass
class InspectionProduceInput:
    """产出型巡检期票输入（字段与 InspectionPeriodicInput 同名同义者语义一致；
    compat 红线同款：多出的键老 worker 解码忽略）。"""

    instance_id: str
    # 兼容面（同 InspectionPeriodicInput.face 纪律）：open_period_ticket 起票统一传
    # face 键——缺字段会 TypeError，故保留并给默认值；produce 链不消费该值。
    face: str = "doc"
    period: str = ""
    repo_root: str = ""
    decl_path: str = ""
    project_key: str = ""


@workflow.defn
class InspectionProduceWorkflow(TicketEventLedgerMixin):
    """One produce-mode inspection period: lane → produce → self-check → report with
    diff → human gate (approve=merge into main / reject=discard). Business refusals
    become a blocked terminal ticket (visible, queryable), never a fake green."""

    STAGES = ("setup", "produce", "selfcheck", "report", "close")

    def __init__(self) -> None:
        self.stage: str = ""
        self.stage_state: str = "running"
        self.status: str = "running"
        self.decision: str = ""
        self.face: Dict[str, Any] = {}
        self.timeline: List[Dict[str, Any]] = []
        self._close_sig: Optional[Dict[str, str]] = None
        self._authorized: List[str] = []          # 已授权保护路径（窄通清单）
        self._rerun_paths: List[str] = []         # authorize 门置；produce 复跑消费
        self._input: Optional[InspectionProduceInput] = None
        self._gate_err: str = ""

    def _enter(self, stage: str, state: str = "running", reason: str = "") -> None:
        self.stage = stage
        self.stage_state = state
        entry = {
            "at": workflow.now().isoformat(timespec="seconds"),
            "stage": stage, "state": state, "reason": reason}
        self.timeline.append(entry)
        # t260928-20：事件账本入队（唯一入队点；gen=文档化常量 0，同 report 链注）
        self._ledger_enqueue(entry)

    def _ledger_project(self) -> str:
        """本票项目身份：_input.project_key（t260915-20 链路，mixin 缺省读 meta——
        本族无 meta）。"""
        return str(getattr(getattr(self, "_input", None), "project_key", "") or "")

    # ---- 阻塞三态判定（纯读，approve 闸与场景共用口径） ----
    def _approve_blockers(self, sc: Dict[str, Any]) -> List[str]:
        blockers: List[str] = []
        if sc.get("out_of_root"):
            blockers.append("越界写集拒收（A2）：%s" % "、".join(
                "%s（%s）" % (h.get("path"), h.get("reason"))
                for h in (sc.get("out_of_root") or [])))
        if sc.get("zero_change_error"):
            blockers.append("零 change 声明判红（A5）：%s"
                            % sc["zero_change_error"])
        unauthorized = [p for p in (sc.get("protected_overlap") or [])
                        if p not in set(self._authorized)]
        if unauthorized:
            blockers.append("保护面未授权（A3）：%s——签 authorize 门（gate=%s）后"
                            "produce 段对授权文件复跑" % ("、".join(unauthorized),
                                                      PRODUCE_AUTHORIZE_GATE_ID))
        return blockers

    # ---- signals ----

    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """人审门（approve=merge / reject=discard）。gate 不匹配忽略不误收；
        agent 角色名拒收（agents never self-sign）；红灯在场时 approve 拒收点名。"""
        payload, err = validate_close_signature(
            {"who": getattr(sig, "who", ""), "gate": getattr(sig, "gate", ""),
             "decision": getattr(sig, "decision", ""), "note": getattr(sig, "note", "")},
            expected_gate=PRODUCE_CLOSE_GATE_ID)
        if err:
            self._gate_err = err
            workflow.logger.warning("拒收签字：%s", err)
            return
        if payload["decision"] == "approve":
            blockers = self._approve_blockers(self.face.get("selfcheck") or {})
            if blockers:
                self._gate_err = "approve 拒收（红灯在场）：%s" % "；".join(blockers)
                workflow.logger.warning("%s", self._gate_err)
                return
        if self._close_sig is None:
            self._close_sig = payload

    @workflow.signal
    def authorize(self, sig: Any) -> None:
        """保护面同票授权（A3）：paths ⊆ 本期 protected_overlap；授权后对授权文件
        复跑 produce（run 循环消费 _authorized）。"""
        from inspection_produce import validate_authorize_payload  # 懒 import（沙箱纪律）
        payload, err = validate_authorize_payload(
            sig if isinstance(sig, dict) else {
                "who": getattr(sig, "who", ""), "note": getattr(sig, "note", ""),
                "gate": getattr(sig, "gate", ""), "paths": getattr(sig, "paths", [])},
            self.face.get("selfcheck", {}).get("protected_overlap") or [])
        if err:
            self._gate_err = err
            workflow.logger.warning("拒收授权：%s", err)
            return
        self._authorized = sorted(set(self._authorized) | set(payload["paths"]))
        self._enter("close", self.stage_state or "running",
                    "Protected-face authorization (who=%s): %s — produce rerun in progress"
                    % (payload["who"], "、".join(payload["paths"])))
        # 标记复跑请求；run 侧 wait_condition 循环消费
        self._rerun_paths = list(payload["paths"])

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": workflow.info().workflow_id,
            "kind": "inspection",
            "template": "inspection-produce",
            "project": str(getattr(self._input, "project_key", "") or ""),
            "stage": self.stage,
            "stage_state": self.stage_state,
            "status": self.status,
            "decision": self.decision,
            "face": self.face,
            "timeline": self.timeline,
            "gate_error": self._gate_err,
            # t260928-20（review C1）：事件账本迁移标记（门内 additive 增量键；同
            # report 链 snapshot 注——取消/硬杀面的账面缺口由 ledger_rebuild 补齐）。
            **({"ledger_marks": [dict(m) for m in (self._ledger_marks or [])]}
               if getattr(self, "_patched", False) else {}),
        }

    # ---- run ----

    @workflow.run
    async def run(self, inp: InspectionProduceInput) -> Dict[str, Any]:
        ticket_id = workflow.info().workflow_id
        repo_root = str(inp.repo_root or "")
        # 声明决议（与报告链同源活动）：produce 模式校验 + docs_root 取声明值（A6）
        plan_raw: Any = await workflow.execute_activity(
            "resolve_inspection_plan",
            args=[{"instance_id": inp.instance_id, "decl_path": inp.decl_path}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if not (plan_raw or {}).get("ok"):
            return await self._blocked(
                ticket_id, inp, "setup",
                "Declaration resolution failed: %s" % ((plan_raw or {}).get("error") or "unknown"), None)
        plan: Dict[str, Any] = (plan_raw or {}).get("result") or {}
        if str(plan.get("mode") or "report") != "produce":
            return await self._blocked(
                ticket_id, inp, "setup",
                "instance mode=%r is not produce (report-chain instances use InspectionPeriodicWorkflow)"
                % str(plan.get("mode") or "report"), None)
        docs_root = str(plan.get("docs_root") or "docs")
        period = inp.period or period_key_in_tz(workflow.now(), str(plan.get("tz") or ""))
        validate_period_key(inp.instance_id, period)
        # ---- setup：清残留 → 基点 → prepare_workspace（与报告链 _setup_lane 同源
        #      活动序；独立实现防两链 replay 面互相牵连） ----
        self._enter("setup", "running", "produce-mode inspection lane (docs_root=%s)" % docs_root)
        try:
            worktree, branch = inspection_lane_paths(inp.instance_id, period, repo_root)
        except ValueError as e:
            return await self._blocked(ticket_id, inp, "setup", str(e), None)
        swept: Any = await workflow.execute_activity(
            "sweep_inspection_lanes",
            args=[{"instance_id": inp.instance_id, "repo_root": repo_root,
                   "keep_period": period}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        head: Any = await workflow.execute_activity(
            "resolve_main_head", args=[{"repo_root": repo_root}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        head_res = (head or {}).get("result") or {}
        if not (head or {}).get("ok") or not head_res.get("sha"):
            return await self._blocked(
                ticket_id, inp, "setup",
                "Base resolution failed (main HEAD): %s" % ((head or {}).get("error") or "unknown"), None)
        lane = {"worktree": worktree, "branch": branch,
                "base_ref": str(head_res["sha"]), "docs_root": docs_root,
                "instance_id": inp.instance_id, "repo_root": repo_root,
                "period": period}
        prep = await _prepare_lane_activity(ticket_id, worktree, branch, lane["base_ref"])
        # 260929：与报告链同源（同类面全量排查）——产出链的泳道坐标同一套命名，重开同期
        # 撞的是同一种残留；patch 门同形（LANE_REPAIR_PATCH_ID，同一改动一个门）。
        repair: Optional[Dict[str, Any]] = None
        if not prep.get("ok") and workflow.patched(LANE_REPAIR_PATCH_ID):
            plan = lane_residue_repair_plan(prep, inp.instance_id, period, repo_root)
            if plan is not None:
                self._enter("setup", "running", plan["reason"])
                repair = await _lane_residue_repair(
                    plan, ticket_id, worktree, branch, lane["base_ref"])
                self._enter("setup", "running", _lane_repair_note(repair))
                if (repair.get("prep") or {}).get("ok"):
                    prep = repair["prep"]
                    lane["repaired"] = "1"
        if not prep.get("ok"):
            detail = "Lane could not be prepared (action=%s): %s" % (prep.get("action"), prep.get("error"))
            if repair is not None:
                detail += _lane_repair_detail(repair)
            return await self._blocked(ticket_id, inp, "setup", detail, lane)
        self._enter("setup", "running", "Lane ready: %s (base %s)"
                    % (worktree, lane["base_ref"]))
        # ---- produce → 自检（首趟；授权复跑的门循环在 _finalize_and_close） ----
        result: Dict[str, Any] = {}
        produce_raw: Any = await workflow.execute_activity(
            "run_inspection_produce",
            args=[{"instance_id": inp.instance_id, "period": period,
                   "ticket_id": ticket_id, "docs_root": docs_root,
                   "base_dir": worktree, "base_ref": lane["base_ref"],
                   "project_key": getattr(inp, "project_key", ""),
                   "timeout_sec": PRODUCE_DEFAULT_TIMEOUT_SEC,
                   "focus": []}],
            start_to_close_timeout=timedelta(
                seconds=PRODUCE_DEFAULT_TIMEOUT_SEC + 300),
            retry_policy=RetryPolicy(maximum_attempts=1))
        if not (produce_raw or {}).get("ok"):
            return await self._blocked(
                ticket_id, inp, "produce",
                str((produce_raw or {}).get("error") or "produce stage failed"), lane)
        result = (produce_raw or {}).get("result") or {}
        sc = dict(result.get("selfcheck") or {})
        sc["authorized_paths"] = list(self._authorized)
        # ---- report：面 + 台账（diff/自检/零 change 全量进报告——A5 显式，不留空壳） ----
        self._enter("report", "running",
                    "Self-check done (diff %d files; out-of-scope %d / protected %d / zero-change=%s / "
                  "doc-check red %d)"
                    % (len(sc.get("all_paths") or []), len(sc.get("out_of_root") or []),
                       len(sc.get("protected_overlap") or []),
                       "none" if not sc.get("zero_change_error") else "red",
                       len(sc.get("doc_findings") or [])))
        self.face = {
            "ticket_id": ticket_id, "instance_id": inp.instance_id,
            "period": period, "template": "inspection-produce",
            "docs_root": docs_root, "lane": lane,
            "mode": "produce",
            "changes": result.get("changes") or [],
            "zero_change": bool(result.get("zero_change")),
            "zero_change_conclusion": (
                "本期零 change（显式声明，证据 %d 条）" % len(result.get("evidence") or [])
                if result.get("zero_change") else "本期产出 %d 条 change 待人审"
                % len(result.get("changes") or [])),
            "evidence": result.get("evidence") or [],
            "selfcheck": sc,
            "meta": dict(result.get("meta") or {}),
        }
        return await self._finalize_and_close(ticket_id, inp, period, lane)

    def _ledger_doc(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = dict(self.face)
        doc["stage"] = self.stage
        doc["stage_state"] = self.stage_state
        doc["status"] = self.status
        doc["timeline"] = [dict(t) for t in self.timeline]
        return doc

    async def _write_ledger(self) -> None:
        try:
            written: Any = await workflow.execute_activity(
                "write_inspection_report", args=[self._ledger_doc()],
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            if (written or {}).get("ok"):
                self.face["report_path"] = (written.get("result") or {}).get("path", "")
            else:
                self._enter(self.stage or "report", self.stage_state or "running",
                            "Ledger write failed: %s" % ((written or {}).get("error") or "unknown"))
        except Exception as e:  # noqa: BLE001
            self._enter(self.stage or "report", self.stage_state or "running",
                        "Ledger write error: %s: %s" % (type(e).__name__, e))

    async def _finalize_and_close(
        self, ticket_id: str, inp: InspectionProduceInput, period: str,
        lane: Optional[Dict[str, str]],
    ) -> Dict[str, Any]:
        # 人门循环（F-1 修复，验收 gen0）：等待位 = 签字 **或** 授权复跑请求。
        # authorize 门置 _rerun_paths → 本循环对授权文件复跑 produce → 重算
        # selfcheck/face → 重落台账 → 回到门（授权→同票复跑产出→再人审合并）。
        while True:
            # 台账先落（C5：reject 也留痕——diff 已在台账，丢弃后可追溯）
            await self._write_ledger()
            gate_note = "人审 change：sign(gate=%s) approve=合并 main / reject=丢弃本期" \
                        % PRODUCE_CLOSE_GATE_ID
            if (self.face.get("selfcheck") or {}).get("protected_overlap"):
                gate_note += "；保护面在场：authorize(gate=%s) 同票授权后复跑" \
                             % PRODUCE_AUTHORIZE_GATE_ID
            self._enter("close", "awaiting-human", gate_note)
            await self._write_ledger()
            # t260928-20：人门前冲账（等待窗内 watchdog/panel 可见 awaiting-human）
            await self._ledger_flush()
            await workflow.wait_condition(
                lambda: self._close_sig is not None or bool(self._rerun_paths))
            if self._close_sig is not None:
                break
            # ---- 授权复跑（消费 _rerun_paths；门文案承诺的动作在此兑现） ----
            rerun_paths = list(self._rerun_paths)
            self._rerun_paths = []
            self._enter("produce", "running",
                        "Protected-face authorized rerun (focus=%s)" % ", ".join(rerun_paths))
            produce_raw: Any = await workflow.execute_activity(
                "run_inspection_produce",
                args=[{"instance_id": inp.instance_id, "period": period,
                       "ticket_id": ticket_id,
                       "docs_root": str((self.face.get("docs_root") or "docs")),
                       "base_dir": str((lane or {}).get("worktree") or ""),
                       "base_ref": str((lane or {}).get("base_ref") or ""),
                       "project_key": getattr(inp, "project_key", ""),
                       "timeout_sec": PRODUCE_DEFAULT_TIMEOUT_SEC,
                       "focus": rerun_paths}],
                start_to_close_timeout=timedelta(
                    seconds=PRODUCE_DEFAULT_TIMEOUT_SEC + 300),
                retry_policy=RetryPolicy(maximum_attempts=1))
            if not (produce_raw or {}).get("ok"):
                return await self._blocked(
                    ticket_id, inp, "produce",
                    "Authorized rerun failed: %s" % ((produce_raw or {}).get("error") or "unknown"),
                    lane)
            result = (produce_raw or {}).get("result") or {}
            sc = dict(result.get("selfcheck") or {})
            sc["authorized_paths"] = list(self._authorized)
            self.face["changes"] = result.get("changes") or []
            self.face["zero_change"] = bool(result.get("zero_change"))
            self.face["evidence"] = result.get("evidence") or []
            self.face["selfcheck"] = sc
            self.face["meta"] = dict(result.get("meta") or {})
            self._enter("report", "running",
                        "Authorized rerun done (diff %d files; protected %d / out-of-scope %d) — back to "
                  "the human gate"
                        % (len(sc.get("all_paths") or []),
                           len(sc.get("protected_overlap") or []),
                           len(sc.get("out_of_root") or [])))
        self.decision = self._close_sig["decision"]  # type: ignore[index]
        self.face["human_gate"] = dict(self._close_sig or {})
        self._enter("close", "running",
                    "Human-gate decision=%s (who=%s)" % (self.decision, (self._close_sig or {}).get("who", "")))
        merge_err = ""
        if self.decision == "approve":
            merged: Any = await workflow.execute_activity(
                merge,
                MergeArgs(ticket_id=ticket_id, worktree=str((lane or {}).get("worktree") or ""),
                          branch=str((lane or {}).get("branch") or ""),
                          base_ref=str((lane or {}).get("base_ref") or ""),
                          defer_teardown=True,
                          write_set=list((self.face.get("selfcheck") or {})
                                         .get("all_paths") or [])),
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            if not (merged or {}).get("ok"):
                merge_err = str((merged or {}).get("error") or "merge 失败")
                self.face["merge_error"] = merge_err
        self.status = "closed"
        # 台账再落（终态；C5：reject/approve 后台账都在，diff 可追溯）
        await self._write_ledger()
        # 拆道（reject=丢弃本期；approve=合并后代落）。失败不遮蔽终态（时间线点名）。
        torn: Any = await workflow.execute_activity(
            teardown_lane,
            MergeArgs(ticket_id=ticket_id,
                      worktree=str((lane or {}).get("worktree") or ""),
                      branch=str((lane or {}).get("branch") or "")),
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if not (torn or {}).get("ok"):
            self._enter("close", "done", "Lane teardown left residue: %s"
                        % ((torn or {}).get("error") or "unknown"))
        self._enter("close", "done",
                    "Produce-mode inspection closed (decision=%s%s)" % (
                        self.decision, "; merge red handed to a human" if merge_err else ""))
        # t260928-20：收口 return 前冲账（终态迁移必须离开 pending）
        await self._ledger_flush()
        return self.snapshot()

    async def _blocked(self, ticket_id: str, inp: InspectionProduceInput, stage: str,
                       reason: str, lane: Optional[Dict[str, str]]) -> Dict[str, Any]:
        """闭式 blocked 终态（可见可查，绝不假绿）。"""
        self._enter(stage, "blocked", reason)
        self.status = "blocked"
        if lane:
            self.face["lane"] = dict(lane)
        self.face["blocked_reason"] = reason
        # t260928-20：终态前冲账（老实例 pending 恒空=零活动命令，重放零变化）
        await self._ledger_flush()
        await self._write_ledger()
        return self.snapshot()

