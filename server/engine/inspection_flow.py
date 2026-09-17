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
workflow.now()); every side effect lives in an activity (run_inspection_scan /
write_inspection_report, thin shells in activities.py).
"""

from __future__ import annotations

import json
import os
import re
import time
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
    from agent_activities import prepare_workspace, teardown_lane

    from shared import MergeArgs, WorkspacePrep

CLOSE_GATE_ID = "inspection-close"
INSPECTION_RED_LINE = "巡检只出报告与开票建议，绝不直接改码；修复一律走 dev-lane 工单。"
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
# 套件阶段 start_to_close：必须**显式大于** agent_activities._run_scenarios 的内部截止
# （BATCH_TIMEOUT_SEC + 300，默认 5400+300=5700s≈95min）——否则 Temporal 先杀活动，
# 活动内的超时清理路径永远走不到（UI_CAPTURE_TIMEOUT_SEC 头注同款纪律）。
# 单测 test_suite_timeout_outlives_internal_deadline 锁定该不等式。
SUITE_TO = timedelta(minutes=120)
# 套件活动不自动重试：整轮全集重跑代价高（小时级），且「跑不成/跑红」本身就是票面数据
# （进发现清单+回执，人审/次日再跑），Temporal 重试只会把同一份失败重复烧一遍墙钟。
RETRY_SUITE = RetryPolicy(maximum_attempts=1)
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
# 版本门 id（t260917-02，replay 安全）：旧调度 action 直发的非 t 形 fire 自愈重定向
# （spawn_inspection_period → open_period_ticket 铸 t 形票承接）只在新 run 生效。老
# in-flight 票（含 260917 的 awaiting-human 旧形壳）history 无此标记 → patched()=False
# 走旧路径收口，零影响。机器化验证=replay_check.py --workflow <老票 id>（S4 自测实测）。
REDIRECT_PATCH_ID = "t260917-02-inspection-legacy-fire-redirect"

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
    """无主票守卫判据（纯函数，t260915-20；单测两腿）：
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
    """sign 闸 target 解析链（纯函数，t260915-20；单测三腿）：
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
    去重键/台账键，体内在铸期回落腿后照旧闭式校验（形状非法=ValueError，与旧铸号
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
        raise ValueError("实例 id 非法（泳道命名空间）：%r" % instance_id)
    if not PERIOD_RE.match(str(period or "")):
        raise ValueError("期号非法（泳道命名空间）：%r" % period)
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
        raise ValueError("实例 id 非法（sweep）：%r" % instance_id)
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



def validate_trigger_args(instance_id: str, period: str) -> Optional[str]:
    """Trigger arguments fail-closed (an extension of trade-off list item 6); returns an
    error message or None."""
    if not instance_id or not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", instance_id):
        return "instance 非法：%r（小写 slug）" % instance_id
    if not PERIOD_RE.match(period or ""):
        return "period 非法：%r（须 YYYYMMDD 或 YYYYMMDD-<bucket>）" % period
    return None


def build_ticket_face(
    ticket_id: str,
    instance_id: str,
    period: str,
    scan_result: Dict[str, Any],
    extra_findings: Optional[List[Dict[str, Any]]] = None,
    suite: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Put the finding list onto the ticket face (rendering data): per-severity with
    evidence + heartbeat + ticket-opening suggestions (zero code changes).

    t260913-02 扩展（两个 defaulted 参数，老调用点逐字段不变=零回归）：
      - extra_findings：套件/漏跑等**非扫描器**来源的发现，进发现清单并重计摘要；
      - suite：套件证据段（face["suite"]），并参与心跳合成（套件不绿=不是心跳期）。"""
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
        # 重计口径与 inspection_scan.summarize 同形（追加发现的严重度必须进摘要，
        # 否则票面摘要与发现清单互斥——「红的是哪几条」在摘要里数不出来）
        counts = {"high": 0, "med": 0, "low": 0}
        for f in findings:
            sev = str(f.get("severity") or "")
            if sev in counts:
                counts[sev] += 1
    heartbeat = bool(scan_result.get("heartbeat"))
    if suite is not None:
        # 心跳合成（t260913-02）：套件在册的期，「全绿」必须含套件全绿——套件红/没跑成/
        # 0 场景都不再是心跳证明期（否则「绿票」会盖住红事）。懒 import：workflow 沙箱
        # 里按需加载（与 inspection_ticket_count 同款纪律）。
        from inspection_deadman import suite_green
        heartbeat = heartbeat and suite_green(suite)
    suggestions: List[Dict[str, Any]] = []
    for f in findings:
        if f.get("severity") not in ("high", "med"):
            continue
        if not f.get("suggest", True):
            continue          # 漏跑/环境红/未跑成不是「开一张修码票」能解的（显式开关）
        suggestions.append({
            "template": "dev-lane",
            "title": "修:%s %s" % (f.get("scan", ""), str(f.get("subject", ""))[:60]),
            "source_inspection": ticket_id,           # the fix ticket references the inspection ticket id (epic tickets 1/4)
            "urgency": "立即开票" if f.get("severity") == "high" else "人审后定",
            "evidence": f.get("evidence", ""),
        })
    face_out = {
        "ticket_id": ticket_id,
        "kind": "inspection",
        "instance_id": instance_id,
        "period": period,
        "red_line": INSPECTION_RED_LINE,
        "heartbeat": heartbeat,
        "heartbeat_note": "全绿期=零发现票（心跳证明）" if heartbeat else "",
        "summary": counts,
        "findings": findings,
        "suggested_fix_tickets": suggestions,
        "scan_meta": scan_result.get("meta") or {},
    }
    if suite is not None:
        face_out["suite"] = suite      # 套件证据段（逐场景红绿/摘要/回执路径，验收 B）
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
        out["archive_error"] = "旧件不可读（不归档，新写照常）：%s: %s" % (type(e).__name__, e)
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
        out["archive_error"] = "归档目录不可建（不归档，新写照常）：%s: %s" % (type(e).__name__, e)
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
            out["archive_error"] = "归档写入失败（不归档，新写照常）：%s: %s" % (type(e).__name__, e)
            return out
    else:
        out["archive_error"] = ("归档重试耗尽（%s-*.%s 已有 99 件，不归档不覆写，新写照常）"
                                % (base, path.suffix.lstrip(".")))
        return out
    try:
        path.unlink()
    except OSError as e:
        # 归档已落定但原件移除失败：canonical 新写将覆盖同名原件——留史不丢（archive 已有），
        # 事由仍要点名（「归档了但 canonical 写入前的原件删除失败」是异常形态）。
        out["archive_error"] = "归档后原件移除失败：%s: %s" % (type(e).__name__, e)
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
                                        now_fn: Callable[[], float] = time.time) -> Dict[str, Any]:
    """套件回执落盘（t260913-02；t260916-02 文件名按实例+期派生）：
    out/inspection/inspection-<实例>-<期>-suite.json（同票重跑覆盖）。

    票面只放逐场景红绿/摘要（不刷屏），**输出尾与全量明细在这里**——票面里的聚合红项
    与 deadman 条目都指回这个文件（可下钻，验收 B/D 的「可读」面）。文件名以 -suite.json
    结尾，台账扫描（inspection_deadman.ledger_periods）显式识别为已知非台账件。
    instance/period 双缺时回落**legacy 只读解析** receipt.ticket_id（旧形 id 含实例/期；
    服务老在途票重放——读面，绝不铸造旧形新票）。"""
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
    path = out_dir / (inspection_ledger_name(instance_id, period)[:-len(".json")]
                      + "-suite.json")
    archived = _archive_if_other_run(path, str((receipt or {}).get("ticket_id") or ""), now_fn=now_fn)
    path.write_text(json.dumps(dict(receipt or {}), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"file": path.name, "path": str(path),
            "ticket_id": str((receipt or {}).get("ticket_id") or ""),
            "instance_id": instance_id, "period": period,
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


# ========================================================================================
# t260916-05：机器可读阶段声明（编码真源=本 workflow 侧代码；展示面=template_topology
# 的 inspection-lite 导出，一致性锁=tests/test_t260916_05_inspection_topology.py——
# 「STAGES 改了不改导出面，此处必红」，dev-lane 范式同款）。
# 最小字段（派单规格）：id/name/next/人门标记（exit）/套件档开关（suite_only）；
# parts 是展示用执行器组合（shared.PART_KINDS 子集，巡检段全程序化、close 带人签）。
# 与 flow 实际调用点对齐：setup/suite 只在声明 run_suite=full 的期出现（run() 两处
# `if run_suite:` 守卫）→ suite_only=True，展示面画条件段（optional 虚节点注记）；
# scan/report/close 每期必经。
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


def _inspection_topology() -> Dict[str, Any]:
    """本模板的展示面拓扑导出（t260916-05；snapshot query 消费）。懒 import
    template_topology：workflow 沙箱里按需加载（build_ticket_face 懒 import
    inspection_deadman 同款）；被导模块零 IO 零 temporalio 依赖，纯查表安全。
    未声明模板返回 None=消费方回落，绝不猜拓扑。"""
    from template_topology import export_template_topology
    return export_template_topology("inspection-lite")


@workflow.defn
class InspectionPeriodicWorkflow:
    """One inspection-period ticket. State machine: scan → report → close (human gate) →
    a terminal closed state.
    Business refusals do not raise: a scan/posting failure → a blocked terminal ticket
    (visible, queryable), never a fake green."""

    #: t260916-05 阶段声明（编码真源）：声明序=执行序；展示面（template_topology
    #: inspection-lite 导出）与一致性锁都以它为对齐锚。
    STAGES = (
        InspectionStage(id="setup", name="泳道准备", next="scan",
                        suite_only=True, parts=("script",)),
        InspectionStage(id="scan", name="扫描", next="suite", parts=("script",)),
        InspectionStage(id="suite", name="巡检泳道套件", next="report",
                        suite_only=True, parts=("script",)),
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
        self._input: Optional[InspectionPeriodicInput] = None  # run 入口钉存（sign 闸 payload 回退链）

    def _enter(self, stage: str, state: str = "running", reason: str = "") -> None:
        self.stage = stage
        self.stage_state = state
        self.timeline.append({
            "at": workflow.now().isoformat(timespec="seconds"),
            "stage": stage, "state": state, "reason": reason})

    @workflow.signal
    def sign(self, sig: Signature) -> None:
        """Human-gate signature (the existing approval-gate machinery). A signature whose
        gate does not match is ignored with a note, never accepted by mistake.

        t260912-03：本巡检模板无授权面——带 authorize 的载荷在 validate 之前显式拒收
        （validate_close_signature 不感知 authorize，若放行会被当作普通人门签字）。"""
        if getattr(sig, "authorize", None) is not None:
            self._gate_err = "本巡检模板无人授权面，authorize 载荷拒收（不落签字）"
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
        }

    @workflow.run
    async def run(self, inp: InspectionPeriodicInput) -> Dict[str, Any]:
        repo_root = str(inp.repo_root or "")
        self._input = inp   # sign 闸 payload 回退链 / snapshot project 面的真源钉存
        # 版本门（replay 安全，见 SUITE_PATCH_ID 头注）：老在途票在这里拿到 False，
        # 于是一路走票① 旧路径（scan→report→close），一个新命令都不注入。
        self._patched = workflow.patched(SUITE_PATCH_ID)
        # 无主票守卫（t260915-20，PROJECT_PATCH_ID 新命令）：项目身份与 repo_root 双空
        # 的新票 → blocked 终态点名（可见不静默）——杀「静默回落引擎仓扫描」的最后残窗
        # （旧调度 payload 在 R1 修复+schedule-up 重跑后收敛为零，守卫兜住漏刷的口子）。
        # 老 in-flight 票：PROJECT_PATCH_ID patched()=False 走旧路径，零影响。
        if self._patched and workflow.patched(PROJECT_PATCH_ID):
            guard = unowned_guard_reason(getattr(inp, "project_key", ""), repo_root)
            if guard:
                # 期号铸取在守卫之后（守卫票不值得跑 plan 活动）；票号=真实 workflow id，
                # 期号如实用输入期（调度路为空、手动路为触发期）——blocked 落账可索引。
                return await self._blocked(
                    workflow.info().workflow_id, inp, str(inp.period or ""), "guard", guard, None)
        plan: Dict[str, Any] = {}
        plan_raw: Any = None
        if self._patched:
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
            if self._patched else period_key(workflow.now()))
        # 票号 = 真实 workflow id（t260916-02：起票侧经 inspection_ticketing.open_period_ticket
        # 铸 t 形号并显式去重（实例+期号 SA），id 不再编码实例/期——老在途票（旧形 id）重放
        # 时该值同样是旧形 id，输出逐字节不变，replay 安全零新 patch 门）。
        validate_period_key(inp.instance_id, period)
        ticket_id = workflow.info().workflow_id
        if self._patched and not (plan_raw or {}).get("ok"):
            return await self._blocked(
                ticket_id, inp, period, "setup",
                "声明决议失败：%s" % ((plan_raw or {}).get("error") or "未知"), None)
        # ---- 重定向守卫（t260917-02，REDIRECT_PATCH_ID 新命令；replay 安全不变量：
        # 本分支内的新 activity 调用对老 history 永不可达——patched()=False 时零新命令）。
        # 非 t 形 fire（旧调度 action 直发）在此改道起票单点铸 t 形票承接，本壳即返：
        # 不跑扫描、不写台账、不进人门——扫描与人门只属于承接票，一期一跑不双份。
        if self._patched and workflow.patched(REDIRECT_PATCH_ID):
            redirect_reason = legacy_fire_redirect_reason(ticket_id)
            if redirect_reason:
                return await self._redirect_and_finish(ticket_id, inp, period, redirect_reason)
        run_suite = bool(plan.get("run_suite"))
        lane: Optional[Dict[str, str]] = None
        suite_section: Optional[Dict[str, Any]] = None
        extra_findings: List[Dict[str, Any]] = []
        if run_suite:
            lane, blocked = await self._setup_lane(ticket_id, inp, period, repo_root)
            if blocked is not None:
                return blocked
        # C4（t260910-09 review）：时间线文案带 face 值——新面票不再误写「测试面」；face 字段透传进 activity 分派
        self._enter("scan", "running", "%s 面扫描（实例 %s 期 %s）" % (inp.face, inp.instance_id, period))
        scan_result: Dict[str, Any] = await workflow.execute_activity(
            "run_inspection_scan",
            args=[{"repo_root": inp.repo_root, "scenarios_path": inp.scenarios_path,
                   "face": inp.face}],
            start_to_close_timeout=SCAN_TO, retry_policy=RETRY)
        if not scan_result.get("ok"):
            return await self._blocked(
                ticket_id, inp, period, "scan",
                str(scan_result.get("error") or "扫描失败"), lane)
        if run_suite:
            # 漏跑核查（dead-man 面①：进本期票面；面②=inspection_trigger.py deadman）
            extra_findings += await self._deadman_findings(inp, plan)
        if run_suite:
            self._enter("suite", "running",
                        "巡检自有泳道跑集成全集（lane 基点 %s）" % (lane or {}).get("base_ref", ""))
            suite_section, suite_findings, teardown_note = await self._run_suite(
                ticket_id, inp, period, lane or {})
            extra_findings += suite_findings
            self._enter("suite", "running", "泳道拆除：%s" % teardown_note)
            if teardown_note.startswith("未净"):
                # 残留=可恢复垃圾（既有 teardown 语义：不拦收口），但要可见（验收 D 的
                # 「不得静默」）；不进开票建议——它不是代码缺陷，清场入口=sweep/CLI。
                from inspection_deadman import make_finding
                extra_findings.append(make_finding(
                    "suite", "med", "泳道拆除未净",
                    "%s ｜ 清场入口：inspection_trigger.py sweep-lanes --instance %s"
                    % (teardown_note, inp.instance_id), suggest=False))
        # 时间线文案：无追加发现时与票①逐字一致（零回归面）；有追加才展开两段计数
        scan_n = len(scan_result["result"].get("findings") or [])
        self._enter("report", "running",
                    ("发现清单落票面（扫描 %d + 追加 %d 条）" % (scan_n, len(extra_findings)))
                    if extra_findings else ("发现清单落票面（%d 条）" % scan_n))
        self.face = build_ticket_face(ticket_id, inp.instance_id, period, scan_result["result"],
                                      extra_findings=extra_findings, suite=suite_section)
        if lane:
            # 跨项目/隔离台的基点证据进票面（验收 A：基点=开跑时 main HEAD）
            self.face["lane"] = dict(lane)
        written: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self._ledger_doc()],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if written.get("ok"):
            self.face["report_path"] = written["result"].get("path", "")
        # Human gate: closing is unreachable before approval (awaiting-human really blocks)
        self._enter("close", "awaiting-human", "人审发现清单：sign(gate=%s) approve=收口 / reject=毙单收口" % CLOSE_GATE_ID)
        # 人门一落就再落一次账：列表可读面（离线读者）要能看见「本期已跑完、正等人审」，
        # 否则它只在 report 段那一版（stage 序列停在 report，读者以为流程没走到门）。
        if self._patched:      # 新命令：老在途票不注入（replay 安全）
            await self._write_ledger()
        await workflow.wait_condition(lambda: self._close_sig is not None)
        self.decision = self._close_sig["decision"]  # type: ignore[index]
        self.status = "closed"
        self.face["human_gate"] = dict(self._close_sig or {})
        self._enter("close", "running", "收口：人门决策=%s（who=%s）" % (self.decision, (self._close_sig or {}).get("who", "")))
        final: Dict[str, Any] = await workflow.execute_activity(
            "write_inspection_report", args=[self._ledger_doc()],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if final.get("ok"):
            self.face["report_path"] = final["result"].get("path", "")
        self._enter("close", "done", "巡检票收口（决策=%s，发现 high=%s/med=%s/low=%s）" % (
            self.decision, self.face.get("summary", {}).get("high", 0),
            self.face.get("summary", {}).get("med", 0), self.face.get("summary", {}).get("low", 0)))
        return self.snapshot()

    # ---- t260913-02：泳道段与终态收口（全部走活动；workflow 体零 IO 零墙钟）----

    def _ledger_doc(self) -> Dict[str, Any]:
        """落账文档 = 票面 + **阶段机证据**（stage/stage_state/status/timeline）。

        为什么落账要带 timeline：`out/inspection/<票号>.json` 是本期对**离线读者**（人 /
        CLI / 运维脚本）唯一的完整面——没有阶段机证据，读者答不出「这期跑到哪、卡在哪段、
        人门过没过」（t260913-02 场景② 的 B1 腿正是按这个口径读落账的）。workflow snapshot
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
                            "落账失败：%s" % ((written or {}).get("error") or "未知"))
        except Exception as e:  # noqa: BLE001
            self._enter(self.stage or "report", self.stage_state or "running",
                        "落账故障：%s: %s" % (type(e).__name__, e))

    async def _setup_lane(
        self, ticket_id: str, inp: "InspectionPeriodicInput", period: str, repo_root: str,
    ) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, Any]]]:
        """搭本期自有泳道：sweep（清非当期残留）→ resolve_main_head（基点）→ prepare。

        C2 次序是刻意的：`prepare_workspace` 对「目录已是本仓 worktree」走 **reused** 分支
        且不校验基点——不清残留就搭，上一期崩下来的同路径目录会让本期静默建在旧基点，
        直接顶撞验收 A。返回值 (lane, blocked_snapshot)；blocked 非空=终态已收口。"""
        self._enter("setup", "running",
                    "巡检自有泳道：搭本期工作副本（实例 %s 期 %s）" % (inp.instance_id, period))
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
                    "残留清扫：worktree %d / 分支 %d（keep=%s，让行 %d%s）"
                    % (len(sweep_res.get("removed_worktrees") or []),
                       len(sweep_res.get("removed_branches") or []), period,
                       len(sweep_res.get("deferred") or []),
                       "" if (swept or {}).get("ok") else
                       "；清扫失败：%s" % ((swept or {}).get("error") or "")))
        head: Any = await workflow.execute_activity(
            "resolve_main_head", args=[{"repo_root": repo_root}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        head_res = (head or {}).get("result") or {}
        if not (head or {}).get("ok") or not head_res.get("sha"):
            return None, await self._blocked(
                ticket_id, inp, period, "setup",
                "基点解析失败（main HEAD）：%s" % ((head or {}).get("error") or "未知"), None)
        lane = {"worktree": worktree, "branch": branch, "base_ref": str(head_res["sha"]),
                "base_ref_name": str(head_res.get("ref") or "main"),
                # 拆除回落清扫用的锚（repo 锚定，跨项目不锚错仓）
                "instance_id": inp.instance_id, "repo_root": repo_root, "period": period}
        prep_raw: Any = await workflow.execute_activity(
            prepare_workspace,
            WorkspacePrep(ticket_id=ticket_id,
                          workspace={"type": "worktree", "path": worktree},
                          branch=branch, base_ref=lane["base_ref"]),
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        prep = prep_raw if isinstance(prep_raw, dict) else {
            "ok": getattr(prep_raw, "ok", False), "action": getattr(prep_raw, "action", ""),
            "path": getattr(prep_raw, "path", ""), "error": getattr(prep_raw, "error", "")}
        if not prep.get("ok"):
            # 半建（分支可能已生）也要清：尝试拆除但不当残留报警（这次本来就没搭成）
            return None, await self._blocked(
                ticket_id, inp, period, "setup",
                "泳道搭不起来（action=%s）：%s" % (prep.get("action"), prep.get("error")),
                dict(lane, _suppress_residue="1"))
        lane["action"] = str(prep.get("action") or "")
        self._enter("setup", "running",
                    "泳道就绪：%s（%s，基点 %s）"
                    % (prep.get("path") or worktree, lane["action"], lane["base_ref"]))
        if "reused" in lane["action"]:
            # C2 验证面：残留未清干净时这里会显形（票面可读），不静默
            self._enter("setup", "running",
                        "注意：本期泳道走 reused（目录已是本仓 worktree）——sweep 未覆盖的残留，"
                        "基点以 git 实况为准")
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
        缺键回落 legacy 只读解析，确定性不受影响）。"""
        from inspection_deadman import suite_findings, suite_section
        receipt: Dict[str, Any]
        try:
            raw: Any = await workflow.execute_activity(
                "run_inspection_suite",
                args=[{"ticket_id": ticket_id, "worktree": lane.get("worktree", ""),
                       "base_ref": lane.get("base_ref", ""),
                       "instance_id": inp.instance_id, "period": period}],
                start_to_close_timeout=SUITE_TO, retry_policy=RETRY_SUITE)
            if (raw or {}).get("ok"):
                receipt = dict((raw or {}).get("result") or {})
            else:
                receipt = {"error": str((raw or {}).get("error") or "套件活动失败"),
                           "details": [], "ran": 0, "passed": 0, "failed": 0, "env_fail": 0}
        except Exception as e:  # noqa: BLE001——活动故障=可见数据（high 发现），不是期票崩塌
            receipt = {"error": "套件活动故障：%s: %s" % (type(e).__name__, e),
                       "details": [], "ran": 0, "passed": 0, "failed": 0, "env_fail": 0}
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
            return "无泳道（无需拆除）"
        residue = ""
        try:
            td: Any = await workflow.execute_activity(
                teardown_lane,
                MergeArgs(ticket_id=ticket_id, worktree=lane["worktree"], branch=lane["branch"]),
                start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
            ok = bool(getattr(td, "ok", False)) if not isinstance(td, dict) else bool(td.get("ok"))
            err = getattr(td, "error", "") if not isinstance(td, dict) else str(td.get("error") or "")
            if ok and not err:
                return "已清（teardown_lane：worktree+branch 零残留）"
            residue = err or "teardown 回执 ok 但带告警"
        except Exception as e:  # noqa: BLE001——拆除故障=残留（有界收敛：定向 sweep/次日/CLI）
            residue = "teardown 活动故障 %s: %s" % (type(e).__name__, e)
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
            if (sw or {}).get("ok") and (res.get("removed_worktrees") or res.get("removed_branches")):
                return "已清（teardown_lane 未净后回落 repo 锚定定向 sweep：%s；原报 %s）" % (
                    "worktree %d / 分支 %d" % (len(res.get("removed_worktrees") or []),
                                               len(res.get("removed_branches") or [])),
                    residue[:160])
            fallback = str((sw or {}).get("error") or "定向 sweep 无可清条目")
        except Exception as e:  # noqa: BLE001
            fallback = "定向 sweep 故障 %s: %s" % (type(e).__name__, e)
        if not report_residue:
            return "拆除尝试（本期未搭成，告警面不启用）：%s" % residue
        return "未净：%s；回落清扫亦未净：%s" % (residue, fallback)

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
            return [make_finding("deadman", "high", "漏跑核查未跑成",
                             "run_inspection_deadman 故障：%s: %s（本期的漏跑判定缺席）"
                             % (type(e).__name__, e), suggest=False)]
        if not (raw or {}).get("ok"):
            return [make_finding("deadman", "high", "漏跑核查未跑成",
                             str((raw or {}).get("error") or "未知"), suggest=False)]
        res = (raw or {}).get("result") or {}
        findings = res.get("findings") if isinstance(res.get("findings"), list) else []
        if res.get("malformed"):
            findings = findings + [make_finding(
                "deadman", "med", "台账畸形条目 %d 个" % len(res["malformed"]),
                "out/inspection 下本实例前缀但非期号词法的文件：%s"
                % "、".join(str(x) for x in res["malformed"][:10]), suggest=False)]
        return findings

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
                        "旧形 fire 重定向完成：本期由 t 形票 %s 承接（%s；dedup_source=%s）"
                        % (target or "?",
                           "deduped 复用既有票" if deduped else "新起票", source))
            self.face["redirect"] = {"from": ticket_id, "to": target, "deduped": deduped,
                                     "dedup_source": source, "period": period,
                                     "instance": inp.instance_id, "reason": redirect_reason}
            return self.snapshot()
        return await self._blocked(
            ticket_id, inp, period, "setup",
            "重定向失败：%s ｜ spawn 回执：%s ｜ 本壳不落账——该期 deadman 漏跑是唯一绊线"
            % (redirect_reason, str((spawn_res or {}).get("error") or "未知")),
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
            self._enter(stage, "blocked", "泳道拆除：%s" % note)
        # blocked 也落账（dead-man 面：不落账的 blocked 在列表面不可见），并带阶段机证据；
        # 老在途票不注入该新命令（replay 安全；它们的 blocked 面仍走票① 的纯快照语义）。
        # write_ledger=False（t260917-02 重定向失败路径）：本壳名下不落账——它的台账名
        # （实例,期）与承接票相同，落了会把真票账盖成 blocked 面）；该期可见性交给
        # deadman 漏跑绊线（与 deadman 跳火点名成链）。
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
    # 腿 g2 实测）。缺省空=worker 侧缺省/env（生产缺省即此形态）。
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
class InspectionTicketCountWatcherWorkflow:
    """常驻轮询调度器：计数 → 纯决策（decide）→ 开期票（票号幂等=一票一期去重兜底）。
    取消/失败终态随 workflow 自身收敛（Temporal 持久化）；死亡+复活=schedule-up
    （inspection_trigger.py）——本票新引入的可死机制的 KI-049 对答。"""

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
        self._last_event = {"at": workflow.now().isoformat(timespec="seconds"),
                            "stage": stage, "state": state, "reason": reason}

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
        self._enter("poll", "running", "计数 watcher 运行（实例 %s，n=%d，源=archive-dir:%s，"
                    "cron=%s）" % (inp.instance_id, inp.n, inp.project_key, inp.cron or "无"))
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
                self._enter("poll", "running", "计数失败（本轮不判触发）：%s" % self.last_error)
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
                                "%s 触发 → 期 %s（deduped=%s，基线=%d）"
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
class InspectionPeriodicSpawnWorkflow:
    """每期一票的起票薄壳（调度器，非票）。体=单 activity 调用；activity 失败 →
    ApplicationError(non_retryable) → schedule recent_actions 可见（绝不静默吞火）。"""

    @workflow.query
    def snapshot(self) -> Dict[str, Any]:
        return {"id": workflow.info().workflow_id, "kind": "inspection-spawner"}

    @workflow.run
    async def run(self, inp: InspectionSpawnInput) -> Dict[str, Any]:
        # 输入形状 fail-closed：无实例名的 spawner 绝不「跑着但什么都不做」
        if not inp.instance_id:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError("spawn 输入非法：instance 空", non_retryable=True)
        res: Dict[str, Any] = await workflow.execute_activity(
            "spawn_inspection_period",
            args=[{"instance_id": inp.instance_id, "face": inp.face,
                   "repo_root": inp.repo_root, "project_key": inp.project_key,
                   "decl_path": inp.decl_path}],
            start_to_close_timeout=SHORT_TO, retry_policy=RETRY)
        if not (res or {}).get("ok"):
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(str((res or {}).get("error") or "起票失败（无事由）"),
                                   non_retryable=True)
        return (res or {}).get("result") or {}
