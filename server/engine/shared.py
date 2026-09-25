"""Temporal POC shared configuration and data contracts.

The ticket's source of truth is always the **Temporal workflow** (the v2 templates are
code, the six subclasses in base.py); workflow id = ticket id (a singleton); project
separation = the ProjectKey search attribute (stamped by ticket-start, filtered by
ticket-list --project).

Step 1's ContentPipelineWorkflow / DispatcherScanWorkflow and the demo data contracts
are kept (backward compatible).

Paths can be overridden by environment variables (temp dirs for self-tests):
  SANDBAR_WORKFLOWS_DIR  the template directory (default <repo>/server/workflows)

Final naming switch (bridged by ticket t260907-04, landed 260908): env is SANDBAR_*
repo-wide, the shared queue is the single name sandbar, and the lane coordination
directory's new name is .sandbar/ (the old name stays as a sticky read side to handle
in-flight old lanes — see the individual # naming-compat markers).
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
# 注意：shared.py 会被单文件加载面消费（ticket.py spec_from_file_location、
# 场景播种链 lib_stage_console.mjs）——仓库内兄弟模块（如 path_gates）不得
# 顶层 import（t260917-01 仲裁 gen1 code-fault 实锤：ModuleNotFoundError 连累
# 14 条场景）；需要处一律函数内延迟 import。


# ---- env naming (bridged by ticket t260907-04, final switch 260908) ----
# SANDBAR_* is the only env prefix (the old SUYOU_* names were retired with the final
# switch). The bidirectional bridge apply_env_compat was deleted as a whole function
# (the mirror ping-pong disease of KI-058 was cured by removing the bridge) —
# injection sides always write SANDBAR_*.
ENV_PREFIX = "SANDBAR_"

# ---- Paths ----
POC_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]          # server/engine -> repo root
ADMIN_PY = REPO_ROOT / "server" / "admin.py"
WORKFLOWS_DIR = pathlib.Path(os.environ.get("SANDBAR_WORKFLOWS_DIR") or (REPO_ROOT / "server" / "workflows"))
OUT_DIR = POC_DIR / "out"

# ---- Temporal endpoints ----
# Overridable by environment variables (the test environment runs its own Temporal in
# Docker, see docs/testing-guide.md):
#   SANDBAR_TARGET_HOST    Temporal gRPC address (production default 127.0.0.1:7233)
#   SANDBAR_NAMESPACE      Temporal namespace (default "default")
TARGET_HOST = os.environ.get("SANDBAR_TARGET_HOST") or "127.0.0.1:7233"
NAMESPACE = os.environ.get("SANDBAR_NAMESPACE") or "default"
# Shared queue (renamed in ticket t260907-04, final switch 260908): the single name
# sandbar. SANDBAR_TASK_QUEUE can override it (for test injection).
# SANDBAR_TASK_QUEUES (CSV) = the multi-queue mode for dedicated workers
# (ticket_worker spawn injects a ticket-specific queue group).
TASK_QUEUE = os.environ.get("SANDBAR_TASK_QUEUE") or "sandbar"
TASK_QUEUES_ENV = "SANDBAR_TASK_QUEUES"


def configured_task_queues() -> List[str]:
    """The queues this worker should poll. Multi-queue mode (SANDBAR_TASK_QUEUES CSV)
    wins; the default = the single shared queue sandbar (the old dual poll of the
    suyou-poc queue was removed with the final switch)."""
    csv = os.environ.get(TASK_QUEUES_ENV)
    if csv:
        queues = [q.strip() for q in csv.split(",") if q.strip()]
        if queues:
            return queues
    return [TASK_QUEUE]

# ---- A dedicated worker per ticket ----
# Ticket workflows stay off the shared queue: one task queue per ticket
# (sandbar-ticket-<ticket id>) plus one dedicated worker process (started at ticket
# create, exits by itself once the workflow closes out, with the inspection sweep as
# the backstop to rescue/collect it).
# The shared queue sandbar only keeps workflows that belong to no ticket
# (dispatcher-scan).
# Isolation semantics: a worker running ticket A's old code can never steal ticket B's
# tasks (the lesson of the 260824 version-poisoning incident).
TICKET_QUEUE_PREFIX = "sandbar-ticket-"
def ticket_task_queue(ticket_id: str) -> str:
    """The ticket-specific task queue name (identical on the workflow-start side and
    the dedicated-worker side)."""
    return TICKET_QUEUE_PREFIX + ticket_id


def ticket_task_queues(ticket_id: str) -> List[str]:
    """The dedicated worker's poll list (the old suyou-ticket- prefix dual poll was
    removed with the final switch; the list shape is kept for spawn-injection surface
    compatibility)."""
    return [TICKET_QUEUE_PREFIX + ticket_id]

# ---- Multi-project: ticket workflows are separated per project, on one Temporal backend ----
# ProjectKey = a Keyword search attribute whose value = the machine-level per-key
# registry key (source of truth ~/.sandbar/projects/<key>/project.yaml; see the
# 「项目注册表」 section of server/tools/ticket.py and server/project-registry.ts —
# three places, one registry stance).
# Registration: run_server.sh's launch arguments carry it; for a running server use
#   bin/temporal operator search-attribute create --name ProjectKey --type Keyword
# The test environment (docker-compose.test.yml temporalite) does the same operator
# create once after startup.
PROJECT_SA_NAME = "ProjectKey"


def project_search_attributes(project: str):
    """Build the ProjectKey typed SA (for stamping start_workflow; ticket-list
    --project filters on it). temporalio is imported inside the function — this module
    stays stdlib-only (server/tools/ticket.py loads it directly)."""
    from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes
    return TypedSearchAttributes([SearchAttributePair(SearchAttributeKey.for_keyword(PROJECT_SA_NAME), project)])

# ---- Epic linkage (260824): a ticket workflow can be tied to an epic code ----
# EpicCode = a Keyword search attribute whose value = the file stem of
# notes/epics/<code>.md.
# Registration: run_server.sh's launch arguments carry it; for a running server use
#   bin/temporal operator search-attribute create --name EpicCode --type Keyword
# The test environment (docker-compose.test.yml temporalite) does the same operator
# create once after startup.
EPIC_SA_NAME = "EpicCode"
# Legacy constant: env is frozen at import time ("set env, then import" semantics),
# while the runtime paths all go through resolve_epics_dir (ticket t260907-07 made the
# epic-document validation project-aware). Remaining consumers:
#   1. the validate_epic_code default-argument path (the only production consumer =
#      server/tools/ticket.py list --epic filtering, a leftover outside the write set —
#      external projects are still rejected on the engine anchor);
#   2. self-tests / fixtures overriding via env SANDBAR_EPICS_DIR (the same key as
#      resolve_epics_dir's live env read).
# the retired pre-run-next-ticket preparation (agent_activities) has moved to
# resolve_epics_dir and no longer consumes this constant.
EPICS_DIR = pathlib.Path(os.environ.get("SANDBAR_EPICS_DIR") or (REPO_ROOT / "notes" / "epics"))
# Code-shape whitelist: reuses the PROJECT_KEY_RE character set and also blocks
# ../../ path traversal.
EPIC_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def resolve_project_root(project_key):
    """项目主目录解析单点（t260915-20：巡检 repo_root 按项目归属解析，不再缺省引擎仓）。

    契约锚=项目接入契约 v1「项目根 = 注册条目 dirs[0]（主目录）」；与
    resolve_epics_dir 同一注册表、同一取法，但**更严**：无空 key 回落分支——
      - 空/未给 key → ValueError（巡检票没有项目身份=无主票，绝不静默扫引擎仓——
        那是 t260915-20 要杀的静默用错仓）；
      - 未知 key / 隔离条目 → lookup_project 的人话错误原样透传（带注册表根语境与
        在册 key 清单）。
    注册表根读法同 lookup_project（env SANDBAR_PROJECTS_DIR 每次现读，隔离台可注入）。
    """
    key = str(project_key or "").strip()
    if not key:
        raise ValueError("项目身份为空：repo_root 按项目解析需要非空 project_key"
                         "（无项目身份的巡检=无主票，绝不静默回落引擎仓）")
    proj = lookup_project(key)
    return pathlib.Path(str(proj["dirs"][0]))


def resolve_epics_dir(project_key):
    """The single resolution point for the epic document directory (ticket t260907-07:
    the CLI validation anchor = the project registry entry's home directory, same
    source and same rule as the ticket console UI's resolveEpicsDir — the same
    registry, the same assembly rule <home>/notes/epics).

    Three-level resolution (mirroring registry_root's "read env fresh on every call"
    precedent):
      1. env SANDBAR_EPICS_DIR non-empty → use it as read (self-test semantics
         unchanged);
      2. otherwise resolve_project_root(project_key) / notes/epics (an unknown
         key / an isolated entry is a fail-closed ValueError, never a silent retreat to
         the engine repo; the resolver is shared with t260915-20's inspection
         repo_root — one registry, one dirs[0] rule);
      3. empty/None project_key → fall back to REPO_ROOT/notes/epics (the engine
         anchor; unreachable in production, kept only for fixture / in-flight ticket
         compatibility — not a semantic promise).
    """
    env_dir = os.environ.get("SANDBAR_EPICS_DIR") or ""
    if env_dir.strip():
        return pathlib.Path(env_dir)
    key = str(project_key or "").strip()
    if not key:
        return EPICS_DIR
    return resolve_project_root(key) / "notes" / "epics"


def validate_epic_code(code: str, epics_dir=None) -> str:
    """Strict validation for ticket-start --epic (a single validation point, called by
    client.py; ticket.py only passes through and keeps no second copy). Note: a single
    validation point ≠ a single directory anchor — directory resolution always goes
    through resolve_epics_dir.

    epics_dir default None = the legacy EPICS_DIR (the engine anchor; the leftover
    ticket.py list --epic path); callers should pass resolve_epics_dir(project)
    explicitly to validate with project awareness.

    An empty string passes (tickets without an epic are allowed) → returns "". An
    illegal shape / a missing epic document → ValueError (the message carries the
    directory actually queried — key diagnostic information under a project anchor).
    Returns the normalized code (as-is; the whitelist already constrains the shape)."""
    code = str(code or "").strip()
    if not code:
        return ""
    if not EPIC_CODE_RE.match(code):
        raise ValueError(
            "立项代号形状非法：%r（要求 %s，小写字母/数字/连字符）" % (code, EPIC_CODE_RE.pattern))
    base = pathlib.Path(epics_dir) if epics_dir is not None else EPICS_DIR
    path = base / (code + ".md")
    if not path.is_file():
        existing = sorted(p.stem for p in base.glob("*.md")) if base.is_dir() else []
        raise ValueError(
            "立项代号不存在：%r（%s 无此档案）。现有代号：%s"
            % (code, path, "、".join(existing) if existing else "（目录为空或不存在）"))
    return code


def ticket_search_attributes(project: str, epic: str = ""):
    """Build the ticket's typed SA: ProjectKey always stamped, plus EpicCode when epic
    is non-empty. temporalio is imported inside the function — this module stays
    stdlib-only (server/tools/ticket.py loads it directly)."""
    from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes
    pairs = [SearchAttributePair(SearchAttributeKey.for_keyword(PROJECT_SA_NAME), project)]
    if epic:
        pairs.append(SearchAttributePair(SearchAttributeKey.for_keyword(EPIC_SA_NAME), epic))
    return TypedSearchAttributes(pairs)


# 巡检票实例/期号搜索属性（t260916-02，口径②「建议」项）：Keyword SA，去重判定
# （实例+期号显式去重）、工单板 SA 查询路径预过滤、按实例查历史期三面的检索真源。
# 注册面：dev 台 run_server.sh --search-attribute；docker 测试台 stage_docker precheck
# 幂等补建；在跑 server 用 `bin/temporal operator search-attribute create`（README §13）。
INSPECTION_INSTANCE_SA_NAME = "InspectionInstance"
INSPECTION_PERIOD_SA_NAME = "InspectionPeriod"


def inspection_search_attributes(project: str, instance_id: str = "", period: str = ""):
    """巡检票 typed SA（t260916-02）：ProjectKey（归属，与 dev-lane 同款）+
    InspectionInstance/InspectionPeriod（实例/期号检索）。instance/period 空则不盖该对
    （历史票兼容面：老票只可能有 ProjectKey）。temporalio 函数内 import（stdlib-only 纪律）。"""
    from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes
    pairs = [SearchAttributePair(SearchAttributeKey.for_keyword(PROJECT_SA_NAME), project)]
    if instance_id:
        pairs.append(SearchAttributePair(
            SearchAttributeKey.for_keyword(INSPECTION_INSTANCE_SA_NAME), instance_id))
    if period:
        pairs.append(SearchAttributePair(
            SearchAttributeKey.for_keyword(INSPECTION_PERIOD_SA_NAME), period))
    return TypedSearchAttributes(pairs)


def next_ticket_seq_from_ids(prefix: str, ids) -> int:
    """当天短 id 自增序号**纯核**（t<YYMMDD>-<NN>；t260916-02 自 server/tools/ticket.py
    _next_seq_v2 抽芯成单一真源——工单与巡检两个铸号面共用，语义漂移即双开号）：
    同前缀最大序号 +1；`%02d` 起步、≥100 自然进三位（词法 `\\d{2,}`）；畸形/异前缀 id 忽略。
    调用方负责扫描面 IO（必须覆盖**全部** workflow 类型的 id——工单店与巡检票互见，
    否则跨族撞号；见 client.py ticket-list 的 id_prefix 扫描参）。"""
    best = 0
    pat = re.compile(r"^%s-(\d{2,})$" % re.escape(str(prefix or "")))
    for tid in (ids or []):
        m = pat.match(str(tid or ""))
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


# ---- Pre-running the next ticket after epic creation (ticket t260828-08): after the merge sign-off, pre-run the integration suggestion and cache it ----
# The cache's source of truth = <repoRoot>/.sandbar/epic-next/<code>/pre.json; the
# read side = workbench src/host/epic-next.ts readPrecache (they reference each other
# and must be updated in lockstep: change one side, sync the other).
# Coexists safely with <jobId>-shaped job directories under the same root: job
# directory cleanup only deletes directories shaped 「<code>-<base36 timestamp>-<6hex>」,
# and the <code>/ subdirectories are not among them.
# ---- Integration-test machinery (follow-on to ticket t260829-07, dev-lane development ∥ test design) ----
# The test set = the repo root's integration/ directory (**committed code assets**,
# entering main through the lane like everything else);
# declaration surface = integration/run_scenarios.py's SCENARIOS registry
# [(name, intent, cmd[, pool][, "serial"?])]; each cmd runs with the repo root as
# cwd via /bin/sh -c, 900s per entry (single execution semantic — callers never
# shlex-split). The long-retired JSON manifest contract must NOT come back
# (integration/t260902-12 pins the file's absence; t260917-09 rewrote this stale
# note that had misled design work back to the dead contract).
# Confidentiality deferred (ticket t260831-02): the agent has no read sandbox and no
# physical isolation for now — it is enough that the developer prompt/handoffs neither
# steer toward nor display the test set's contents; sandbox-level limits come later.

INTEG_DIR_NAME = "integration"
# t260917-09 定语义：两个上限**有意分叉**——tests 面是「连续」（收敛即清零，复位点
# 全表见 tests_round_step），code-fault 面保持「累计」（打回修码成本更高）。
MAX_TESTS_FAULT_ROUNDS = 5     # test-set iteration cap (CONSECUTIVE tests-fault rounds judged by arbitrate)
MAX_CODE_FAULT_ROUNDS = 5      # bounce-to-developer cap (CUMULATIVE code-fault rounds judged by arbitrate)
MAX_TESTS_EXEMPT_ROUNDS = 5    # consecutive exempted (not-counted) tests-fault rounds — env-side red (scenario env_fail / supply-assembly fail) / jitter re-run green; anti-live-loop cap (t260917-09)
MAX_ACCEPTANCE_ROUNDS = 2      # acceptance-report rewrite cap (an inadequate report → bounce back to acceptance)
MAX_REVIEW_ROUNDS = 5          # plan-review bounce cap (the review_plan reject loop; consumed by review_plan_route)

ARBITRATION_VERDICTS = ("pass", "tests-fault", "code-fault")


@dataclass
class IntegrationRunArgs:
    """Inputs of run_integration_tests: run the lane's SCENARIOS registry entries
    (integration/run_scenarios.py) inside the lane."""

    ticket_id: str
    worktree: str                               # the lane root (the cmds' cwd, where the test set lives)
    attempt: int = 0                            # t260910-13：rework 代数（0=未声明；闸按此盖写规范行 attempt——K4 单写者=引擎侧）
    write_set: List[str] = field(default_factory=list)  # t260913-03：票面声明写集（integ 道例外分支求交判据；缺省空=老载荷回放）
    apply_skip_pools: bool = False              # t260913-03：每票段显式置位才消费声明（缺省=恒全跑，验收 E 机械锁）
    # t260917-08：交接运行清单（前序 agent 段沙箱受限期间移交的验证命令），集测段
    # worker 执行面逐条代跑。缺省空=老载荷/巡检/老回放零改动。命令来源=dev_lane 的
    # collect_handover_runs（results + meta['env_handover_pending'] 债表，消费后销账）。
    handover_runs: List[Dict[str, str]] = field(default_factory=list)
    # t260923 D 两层复跑：定点复跑面（SANDBAR_SCENARIO_ONLY 语义，执行器按名点跑、
    # expected=点名在册、fail-closed 校验在册性）。空=全量跑（放行唯一依据的收口
    # 跑形态）。爆炸半径/首轮决策在 dev_lane 调用点（单写者=targeted_rerun_plan）。
    only_names: List[str] = field(default_factory=list)


@dataclass
class ChangedFilesArgs:
    """t260925-04 实际改动文件清单收集入参：泳道仓内 `merge-base(main, branch)` 三点
    diff ∪ `git status --porcelain -z` 脏文件。worktree 空=引擎仓根（单仓泳道）。"""

    ticket_id: str
    worktree: str = ""                          # 泳道根（git 命令 cwd；空=REPO_ROOT）
    branch: str = ""                            # 泳道分支（merge-base 对象；空=fail-closed）


@dataclass
class ChangedFilesResult:
    """t260925-04 收集回执。files=去重后的改动文件相对路径（仓库根相对，posix 形）。
    **error 非空 = 改动清单不可得 = 调用方必须恒全跑**（fail-closed，绝不按空清单
    收窄；files 与 error 同空也不允许当「无改动」消费）。"""

    files: List[str] = field(default_factory=list)
    error: str = ""
    # t260925-12 闸段分相计时（additive）：活动自报墙钟秒（执行面，不含 Temporal
    # 调度等待）。0.0=未计时（老回放/旧 dict 回退重建点缺键=缺省值，零行为变化）。
    wall_s: float = 0.0


def gate_phase_timings(phases, wall_s):
    """t260925-12 闸段分相计时拼装（纯函数，单写者=dev_lane 段尾调用；契约场景
    integration/t260925-12/sc_t260925_12_stage_record_timings.py 锁定签名
    `(phases: dict, wall_s)` 与 residual 归账口径）。

    口径：wall_s=段墙钟（workflow.now 段入口→回执点）；phases=各相位 workflow 侧
    活动前后差（含 Temporal 调度/排队）。unattributed_s=段墙钟−Σ有效相位——排队/
    调度/段内非活动面，超时归因的第一嫌疑，永远显式给数不藏。

    畸形输入纪律（消费外部数值面，锁于场景 C1/C2/C3）：
    - 值缺失/非数值/负数/NaN/0 → 该相位**不入表**（不假造 0 相位、垃圾不入归因）；
    - 相位键白名单（pre_check_s/main_sync_s/changed_files_s/suite_s/handover_s）——
      未知键（ghost 相位）绝不进 Σ；键名 unattributed_s 的输入忽略（保留字）；
    - unattributed_s 可为负（Σ相位>段墙钟=亚秒抖动信号，如实给负不 clamp）。"""
    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f == f and f > 0.0 else None
    wall = _num(wall_s)
    out = {}
    for k, v in dict(phases or {}).items():
        if k not in ("pre_check_s", "main_sync_s", "changed_files_s",
                     "suite_s", "handover_s"):
            continue
        f = _num(v)
        if f is not None:
            out[k] = f
    out["unattributed_s"] = (wall if wall is not None else 0.0) - sum(out.values())
    return out


@dataclass
class IntegrationRunResult:
    """The run_integration_tests receipt: how many ran / how many passed / failure
    details (truncated) / raw output.

    A non-empty error = a startup-level failure such as missing infrastructure or a
    missing manifest (no test was run)."""

    ran: int = 0
    passed: int = 0
    failed: int = 0
    # ticket t260904-12: the environment-red dimension (the translation layer no longer
    # drops it)。命名互指（t260917-08）：本字段是 **int 计数**（场景环境红，入闸口径）；
    # StageResult.env_fail 是 **bool 位**（段回执层，不入闸口径）——同名异型，勿混读。
    env_fail: int = 0            # ticket t260904-12: the environment-red dimension (the translation layer no longer drops it)
    details: List[Dict[str, Any]] = field(default_factory=list)  # [{name,cmd,exit,output_tail}]
    error: str = ""
    # t260910-13 失败分类协议：闸机械归属判定面（默认空=协议未产出，老回放兼容）
    blockers: List[str] = field(default_factory=list)   # 闸拦名单（决策表 verdict=block）
    affiliation_confidence: str = ""                    # ok / unknown(fingerprint_mismatch) / unknown(baseline_unavailable)
    baseline_ref: str = ""                              # 基线 ref（main@sha），闸补
    # t260913-03 池排除回执面（少跑必须点名到回执；缺省空=未启用）
    excluded_pools: List[str] = field(default_factory=list)  # 实际排除的池名（applied 时）
    excluded_count: int = 0                                  # 被排除条目数（本轮不在册）
    forced_by: List[str] = field(default_factory=list)       # 旧口径例外分支命中面（宿主管 260914 撤除例外分支：不再拦，仅留痕）
    # t260923 D 两层复跑：本轮实际跑面回显（少跑必须可见）——空=全量；非空=定点
    # 复跑面（点名在册面），放行判定只认全量跑（dev_lane 收口拦截）。
    only_names: List[str] = field(default_factory=list)
    # t260917-08 移交命令单列计数（不进 ran/passed/failed 主口径=闸判定零改动，红线④）：
    # 前序 agent 段沙箱受限期间移交的验证命令，本段 worker 执行面逐条代跑的结果。
    handover_ran: int = 0
    handover_passed: int = 0
    handover_failed: int = 0
    # t260925-12 闸段分相计时（additive，全 0.0=老回放零漂移）：活动自报三段墙钟秒
    # ——wall_s=活动整体执行面；subprocess_wall_s=场景执行器子进程（admin call
    # verify_lane integ 全链）；handover_wall_s=移交命令段。差值=回执组装/解析等
    # 活动内开销；与 workflow 侧段墙钟的差=调度/排队面（gate_phase_timings 呈现）。
    wall_s: float = 0.0
    subprocess_wall_s: float = 0.0
    handover_wall_s: float = 0.0


@dataclass
class ReprobeRedArgs:
    """t260917-09 探针入参：红项**名单**（name→cmd 解析=执行器 SCENARIOS 单一真源，
    调用方绝不携带 cmd——activity 侧另立执行语义=双实现，禁）。"""

    ticket_id: str
    worktree: str
    names: List[str] = field(default_factory=list)


@dataclass
class ReprobeRedResult:
    """t260917-09 探针回执。定位=**证据活动，非闸面**：只决定该轮是否计入
    tests-fault 轮次上限，永不推进票面。error 非空（解析失败/不在册/超时/锁忙/
    非零退出）=探针未证全绿=调用方**保守计轮**，绝不因探针缺席放行。"""

    ran: int = 0
    passed: int = 0
    failed: int = 0
    env_fail: int = 0
    missing: List[str] = field(default_factory=list)
    entries: List[Dict[str, Any]] = field(default_factory=list)  # [{name,exit,dur_s}]
    error: str = ""

    def all_green(self) -> bool:
        """抖动判定（纯函数面，UT 直驱）：有真跑、零产品红、零环境红、零不在册、
        零 error——五条同时成立才算「红项串行复跑全绿」。"""
        return (self.error == "" and self.ran >= 1 and self.failed == 0
                and self.env_fail == 0 and not self.missing)


REPROBE_SUMMARY_MARK = "REPROBE_SUMMARY "


def parse_reprobe_summary(stdout_text: str, returncode: int) -> ReprobeRedResult:
    """解析 --reprobe stdout 的末行 REPROBE_SUMMARY（纯函数，UT 直驱四态：良/缺行/
    畸形/exit≠0）。R1 定案：fail-closed 也打汇总行——先解析行（missing/error 得以
    点名上票面），再按 returncode/行内 error/missing 补判保守计轮信号。"""
    out = ReprobeRedResult()
    line = ""
    for ln in str(stdout_text or "").splitlines():
        if ln.startswith(REPROBE_SUMMARY_MARK):
            line = ln[len(REPROBE_SUMMARY_MARK):].strip()
    if not line:
        out.error = "探针回执缺 REPROBE_SUMMARY 行（执行器提前退出？）rc=%s" % returncode
        return out
    import json as _json  # 函数内延迟 import（单文件加载面纪律，见文件头注）
    try:
        doc = _json.loads(line)
    except ValueError:  # JSONDecodeError ⊂ ValueError（单文件加载面不引 json 全名）
        out.error = "探针回执 REPROBE_SUMMARY 非法 JSON：%s" % line[:160]
        return out
    if not isinstance(doc, dict):
        out.error = "探针回执 REPROBE_SUMMARY 非对象：%s" % line[:160]
        return out
    out.ran = int(doc.get("ran") or 0)
    out.passed = int(doc.get("passed") or 0)
    out.failed = int(doc.get("failed") or 0)
    out.env_fail = int(doc.get("env_fail") or 0)
    out.missing = [str(x) for x in (doc.get("missing") or [])]
    out.entries = [dict(x) for x in (doc.get("entries") or [])
                   if isinstance(x, dict)]
    row_error = str(doc.get("error") or "")
    if returncode != 0 or row_error or out.missing:
        out.error = row_error or ("探针 exit=%s（missing=%s）"
                                  % (returncode, ",".join(out.missing) or "无"))
    return out


def integ_verify_payload(lane_root, write_set=None, apply_skip_pools=False):
    """run_integration_tests → verify_lane lane=integ 的载荷（薄壳只下单，t260913-03）。

    策略面（是否按泳道 verify.yaml 声明排除池）只由调用方显式置位——本函数只透传：
    缺省 apply_skip_pools=False = 巡检/手动/老载荷回放恒全跑（验收 E 的机械锁面）；
    置位 True（每票段）= 按声明一律跳过（宿主管 260914 口径：例外分支已撤除），
    write_set 只剩旧口径命中面留痕用途。"""
    return {'lane': 'integ', 'path': str(lane_root), 'baseline': True,
            'write_set': [str(x) for x in (write_set or [])],
            'apply_skip_pools': bool(apply_skip_pools)}


@dataclass
class SettleLaneArgs:
    """Inputs of settle_lane: the unified worker-side settle at the join point
    (implementation + test set in the same commit)."""

    ticket_id: str
    worktree: str
    stage_id: str
    gen: int
    # t260911-03 路径闸三件（defaulted——老 RUNNING 实例 replay 历史事件缺字段→默认值，
    # replay 不破；path_gate 只有新票输入钉死后才会 True，老在途票不追溯）：
    write_set: List[str] = field(default_factory=list)   # 逐仓 rebase 前的工单写集
    base_ref: str = ""                                   # 泳道分叉点（单仓锚；多仓以清单 per-repo base_ref 优先）
    path_gate: bool = False                              # 闸总开关
    # KI-124：本票模板段规则表（defaulted 空表=老事件 replay 不破；空表回落内建表）。
    path_gate_rules: Dict[str, Any] = field(default_factory=dict)
    # t260912-03 人授权结构化记录（defaulted 空表，零回归）：join 点落盘的受保护闸
    # 豁免面（workflow 侧已按票+时效过滤，activity 不读墙钟）。
    authorizations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SettleLaneResult:
    note: str = ""
    lane_commits: int = -1                      # -1 = unknown (rev-list failed)
    error: str = ""
    # t260915-01 ②：闸拒绝的结构化明细（首个拒绝 scope 的 gate_red_detail 产出）。
    # None = 非闸拒绝/老回执（dict 反序列化态经 .get 缺省，重放安全）。
    gate_refusal: Optional[Dict[str, Any]] = None


def parse_arbitration_summary(summary: str) -> str:
    r"""Extract the verdict from the arbitrate agent's summary (the FLOW_BRIEF
    contract: when the summary contains exactly **one** ``verdict=xxx`` marker, return
    xxx, and it must be ∈ ARBITRATION_VERDICTS; otherwise return "". Missing / zero /
    multiple / illegal all count as a format failure — multiple verdicts = a malformed
    arbitration summary, and picking any one of them is guessing, consistent with "on a
    parse failure the workflow side re-runs arbitrate rather than guessing"
    (ticket t260902-10 changed "take the first match" to "exactly one match or an empty
    string"; the caller dev_lane treats an empty verdict as a format fix and retries
    ≤2 rounds before blocking). The negative lookahead (?![\w-]): a legal value
    followed by a word character or hyphen (e.g. verdict=pass-fault) is not a marker,
    return ""."""
    hits = re.findall(r"verdict=(pass|tests-fault|code-fault)(?![\w-])", summary or "")
    return hits[0] if len(hits) == 1 else ""


# 人工出路四条（t260917-09 要求④：超限封面不许只写「转人工判读」）。全部是
# server/tools/ticket.py 真实存在的 op（authorize/ruling/rework/pause；无 terminate，
# 不发明出口）；前缀文案逐字保持既有断言兼容（test_integration_route / KI-061
# startswith / 场景关键词「测试集迭代」「超限」）。
_ARBITRATION_CAP_EXITS = (
    "。出路：① op=authorize（kind=arbitration_verdict，scope=[本票票号]）"
    "接受本判决→推进验收（判据：产品面已收口、余红属环境/负载抖动）；"
    "② op=ruling 宿主终裁改判；③ op=rework 打回 implement/create_plan 修正；"
    "④ op=pause 暂停交人工处置")


def integration_route(verdict: str, tests_rounds: int, code_rounds: int) -> str:
    """The arbitrate three-state route (pure function, tested directly by the
    selfcheck). Returns the next phase name or "blocked:<reason>".
    Caps (ticket t260831-02): test-set iteration and bounce-to-developer each 5 rounds;
    past the cap, blocked and handed to a human — with executable human exits named
    (t260917-09; the authorize consumption lives in arbitration_cap_route).
    NOTE the deliberate semantic fork (t260917-09): the tests cap counts CONSECUTIVE
    tests-fault rounds (reset per tests_round_step), the code-fault cap stays
    CUMULATIVE."""
    if verdict == "pass":
        return "acceptance"
    if verdict == "tests-fault":
        return "run_integration_tests" if tests_rounds <= MAX_TESTS_FAULT_ROUNDS else \
            "blocked:测试集迭代 %d 轮超限（上限 %d），转人工判读%s" % (
                tests_rounds, MAX_TESTS_FAULT_ROUNDS, _ARBITRATION_CAP_EXITS)
    if verdict == "code-fault":
        return "implement" if code_rounds <= MAX_CODE_FAULT_ROUNDS else \
            "blocked:打回 developer %d 轮超限（上限 %d），转人工判读%s" % (
                code_rounds, MAX_CODE_FAULT_ROUNDS, _ARBITRATION_CAP_EXITS)
    return "blocked:仲裁结论未知 verdict=%r，转人工判读" % verdict


def tests_round_step(verdict: str, tests_rounds: int, exempt_rounds: int, *,
                     env_side_red: bool = False, jitter_green: bool = False,
                     known_red: bool = False):
    """连续 tests-fault 轮计数器转移（纯函数，t260917-09；UT 直接驱动矩阵）。

    定案语义=**连续**：上限 MAX_TESTS_FAULT_ROUNDS 只数「连续被判 tests-fault 的仲裁
    轮」——任一轮非 tests-fault（pass / code-fault / 非法 verdict / 人工接受判决，
    调用方传伪 verdict="accept-reset" 复用本分支，R2 单写者纪律）即复位清零。与
    MAX_CODE_FAULT_ROUNDS 的累计语义有意分叉（打回修码成本更高，见常量区注释）。

    假封防护（260917 三票实证）：tests-fault 但该轮红项全在环境面（env_side_red=
    机械口径来自 IntegrationRunResult，两形态——场景级=产品红 0＋闸拦 0＋环境红≥1；
    装配级=零跑＋error 命中供给装配签名，见 tests_supply_assembly_error）或红项串行
    复跑全绿（jitter_green=负载抖动，KI-072 同族）→ 本轮**不计入**，改记连续豁免轮；
    连续豁免到 MAX_TESTS_EXEMPT_ROUNDS 由调用方转 tests_exempt_cap_blocked_text
    封面（防活循环）。

    已知红豁免（B 零新增红口径，260923）：tests-fault 而闸 blockers 为空=红面全为
    基线既有欠账/外部环境记录面（decide 判 record 的不堵票面）——重跑已知红不会绿、
    只会烧轮次到超限转人工，故本轮不计入（known_red），改记连续豁免轮；豁免仍走
    MAX_TESTS_EXEMPT_ROUNDS 独立上限（转人工触发不许归零：豁免耗尽照样见人）。

    返回 (tests_rounds, exempt_rounds, counted, note)。畸形入参（负数/非 int 轮次、
    非布尔信号）fail-closed：不抛、不静默清零成「复位」，按普通计轮处理——保守侧
    多计不少计（消费外部输入的纪律）。
    """
    if not isinstance(env_side_red, bool):
        env_side_red = False
    if not isinstance(jitter_green, bool):
        jitter_green = False
    if not isinstance(known_red, bool):
        known_red = False
    if verdict != "tests-fault":
        return 0, 0, False, "streak-reset"
    if not isinstance(tests_rounds, int) or isinstance(tests_rounds, bool) \
            or tests_rounds < 0:
        tests_rounds = 0          # 畸形归零后照常走计轮面（保守侧，不当复位用）
    if not isinstance(exempt_rounds, int) or isinstance(exempt_rounds, bool) \
            or exempt_rounds < 0:
        exempt_rounds = 0
    if env_side_red or jitter_green or known_red:
        return tests_rounds, exempt_rounds + 1, False, (
            "env-side-red" if env_side_red
            else "jitter-green" if jitter_green else "known-red")
    return tests_rounds + 1, 0, True, "counted"


# ---------------- D 两层复跑 + 爆炸半径（260923 宿主直修令） ----------------

# 共享基座前缀（爆炸半径判据，宁宽勿窄——命中=禁定点恒全跑）：引擎内核/worker/
# 闸工具/执行器与共享库/道声明。只有票面局部改动（票目录、app/ 等）才允许定点。
_SHARED_BASE_PREFIXES = (
    "server/engine/", "server/tools/", "server/dsh/", "server/admin.py",
    "integration/run_scenarios.py", "integration/stage_docker.py",
    "integration/lint_tests.py", "integration/scenario_ledger.py",
    "integration/lib_", "integration/with_stage.sh", "integration/tests/",
    "verify.yaml",
)


def blast_radius(write_set) -> str:
    """爆炸半径分类（纯函数）："shared"（写集含共享基座面，禁定点）| "localized"。
    空写集/畸形入参=shared（保守恒全跑——宁可慢不可窄，消费外部输入 fail-closed）。"""
    if not isinstance(write_set, (list, tuple)):
        return "shared"
    seen = 0
    for raw in write_set:
        if not isinstance(raw, str) or not raw.strip():
            continue
        seen += 1
        if raw.strip().lstrip("./").startswith(_SHARED_BASE_PREFIXES):
            return "shared"
    return "localized" if seen else "shared"


def changed_files_blast_radius(changed_files, diff_error: str = "") -> str:
    """文件级爆炸半径分类（纯函数，t260925-04）：输入=相对泳道基线（merge-base
    main branch）**实际改动文件**清单（git diff --name-only ∪ git status 脏文件）。
    "shared"=禁定点恒全跑 | "localized"=可定点。

    fail-closed 恒全跑方向（宁可慢不可窄）：diff_error 非空（merge-base 解析失败/
    diff 失败/超时——改动清单未知）→ shared；入参非 list/tuple → shared；清单为空
    （无改动=口径未知，绝不因「看起来没改」收窄）→ shared；**清单含畸形元素
    （非串/空白）→ shared 恒全跑**（t260925-04 rework 缺陷①：入参形状不可信=
    清单未知，半截数据不得放窄跑——与「跳过可忽略元素」严格区分）；**尾 `/` 的
    目录折叠条目 → shared 恒全跑**（缺陷②纵深防御：porcelain 折叠条目范围未知，
    宁宽勿窄；收集面已用 `-uall` 不折叠，此条兜非 `-uall` 形态的来历不明清单）。
    共享面判定**复用同一张 _SHARED_BASE_PREFIXES 表**（安全轨①：真碰场景执行器/
    基线/verify.yaml/写集台账机器 → 恒全跑，判据只有一份不漂移）。"""
    if diff_error:
        return "shared"
    if not isinstance(changed_files, (list, tuple)):
        return "shared"
    seen = 0
    for raw in changed_files:
        if not isinstance(raw, str) or not raw.strip():
            return "shared"  # 畸形元素=清单不可信，恒全跑（缺陷①修）
        n = raw.strip().lstrip("./")
        seen += 1
        if n.endswith("/"):
            return "shared"  # 目录折叠条目=范围未知，宁宽勿窄（缺陷②纵深）
        if n.startswith(_SHARED_BASE_PREFIXES):
            return "shared"
    return "localized" if seen else "shared"


# t260925-04 定点复跑签名扩展的哨兵：区分「调用方未传 changed_files」（旧口径，
# 写集粗前缀判据——老历史/未升级调用点零行为变化）与「显式传了空清单」（fail-closed
# 恒全跑）。直接用 None 当缺省做不到这个区分，故用模块级唯一对象。
_UNSET = object()


def targeted_rerun_plan(write_set, prev_red_names, first_run: bool = False,
                        changed_files=_UNSET, diff_error: str = ""):
    """定点复跑面（纯函数，260923 D）：上一轮红项名（去重、剔 __ 合成条目、剔空）。
    返回空列表=全量跑语义（首轮/共享基座/无上轮红名/畸形名单——调用方不得注入
    SANDBAR_SCENARIO_ONLY，全量是唯一放行依据的收口形态）。

    t260925-04：可选 changed_files 传入**实际改动文件清单**时，爆炸半径改按文件级
    `changed_files_blast_radius` 判（引擎票写集含粗前缀不再恒禁定点）；不传（哨兵
    缺省）=旧口径逐字（写集粗前缀判据，老历史/未升级调用点零行为变化——回放安全）。
    diff_error 非空（收集面报错：merge-base/diff/status 失败）=恒全跑，且优先于
    localized 清单——计算面报错时清单再「好看」也不得放窄。共享面安全轨①与
    fail-closed 规则见 changed_files_blast_radius。"""
    if diff_error:
        radius = "shared"
    elif changed_files is _UNSET:
        radius = blast_radius(write_set)
    else:
        radius = changed_files_blast_radius(changed_files)
    if first_run or radius != "localized":
        return []
    if not isinstance(prev_red_names, (list, tuple)):
        return []
    out = []
    for raw in prev_red_names:
        if not isinstance(raw, str):
            continue
        n = raw.strip()
        if not n or n.startswith("__") or n in out:
            continue
        out.append(n)
    return out


# 供给装配失败的机械签名（t260917-09 gen11 打回补）。真源唯一=verify_lane 乙段
# supply 装配（server/tools/verify_lane.py）两态文案：「supply 装配超时」「supply
# 装配失败」，尾巴皆带「供给面红点名，不静默」。签名取**双标记合取**——窄而准：
# 其他启动级 error（执行器整体超时/无有效输出/声明未知键）不命中、照旧保守计轮；
# 单标记误命中面（如「supply 装配好了」）被另一标记兜住。
SUPPLY_ASSEMBLY_ERROR_MARKS = ("supply 装配", "供给面红")


def tests_supply_assembly_error(error: Any) -> bool:
    """回执 error 是否命中「供给装配失败」机械签名（纯函数，t260917-09 gen11；
    UT 直驱）。命中=该轮 tests-fault 属环境面豁免（供给波动，工单要求③字面兑现，
    不计入 tests-fault 轮次）；畸形/不命中=False（保守计轮——绝不因签名解析不出
    放行，消费外部输入的 fail-closed 纪律）。"""
    if not isinstance(error, str) or not error:
        return False
    return all(m in error for m in SUPPLY_ASSEMBLY_ERROR_MARKS)


def tests_supply_assembly_note(error: Any) -> str:
    """装配级供给失败的票面留痕文案（单写者，t260920-01 票①要求①「留痕含
    「不计入」+ 点名供给面，不得静默」）：dev_lane._tests_round_account 与 UT
    共同消费本函数，文案只此一份。畸形 error（非 str/空）不抛：保守截断为可读
    前缀，绝不静默丢证据（消费外部输入的 fail-closed 纪律）。"""
    e = error if isinstance(error, str) else ""
    return ("供给面装配失败（零跑，error 命中供给装配签名：%s）——不计入 tests-fault 轮次"
            % ((e or "<空>")[:120]))


def tests_exempt_cap_blocked_text(exempt_rounds: int) -> str:
    """连续豁免轮超限的 blocked 文案（纯函数，t260917-09）：与 cap 超限同族——
    含「超限」关键词供场景/快照判据，出路四条全是 ticket.py 真实 op。authorize 的
    消费点在 dev_lane 豁免超限分支（授权在场=接受本判决复位推进，不落本封面）。"""
    return ("测试集连续 %d 轮红项均属环境面/负载抖动（连续豁免超限，上限 %d），"
            "转人工判读%s" % (exempt_rounds, MAX_TESTS_EXEMPT_ROUNDS,
                              _ARBITRATION_CAP_EXITS))


# ---- 仲裁段 settle 闸拒可辨（工单 t260917-01）----
# 病灶：settle 被路径闸拒绝时 _apply_settle_note 把回执 status 改 failed、summary
# 换成拒绝回执——仲裁结论被吞，dev_lane 的格式计数器曾把「落盘被拦」当「没写
# verdict」（t260916-19/-21 误判 blocked 的根因）。本组纯函数把两态分开：
# 闸拒可辨 → blocked 主因=闸拒（不计格式轮次）；否则照旧走格式计数。

def arbitrate_settle_refusal(summary: str, gate_refusal: Any) -> Optional[Dict[str, Any]]:
    """仲裁段回执的 settle 闸拒可辨（t260917-01 ①判定核，唯一守门点的被调纯函数）。

    判序：
      1. 结构化 gate_refusal（经 path_gates.sanitize_gate_refusal 校形）在场=权威
         （新回执，t260915-01 起）；
      2. 否则回执文本含 path_gate_reason= 键（老回执/无结构化明细）且**解析不出
         合法 verdict= 判定** → 文本可辨兜底（agent 在 summary 里原样引用机读键
         不劫持正常路由——quoted 键围栏，UT 显式覆盖）；
      3. 两者皆无 → None（调用方照旧走格式计数路径）。
    返回 {reason_code, note, next_action, files}；畸形输入不抛（fail-visible：
    可辨则辨、不可辨则 None，绝不猜）。纯函数零 IO，UT 与守门点直调。"""
    import path_gates  # 延迟 import：单文件加载面（见文件头注）不牵连仓库兄弟模块
    s = summary if isinstance(summary, str) else ""
    d = path_gates.sanitize_gate_refusal(gate_refusal) if isinstance(gate_refusal, dict) else None
    if d is not None:
        rc = str(d.get("reason_code") or "gate_refusal_unknown")
        return {
            "reason_code": rc,
            "note": s.strip() or str(d.get("evidence") or ""),
            "next_action": str(d.get("next_action") or "").strip()
                           or path_gates.next_action_hint(rc),
            "files": [str(f) for f in (d.get("files") or []) if isinstance(f, str) and f],
        }
    if parse_arbitration_summary(s):
        return None  # 结论可解析：文本里的机读键只是引用，不劫持路由
    if path_gates.is_gate_refusal(s):
        m = re.search(r"path_gate_reason=([\w-]+)", s)
        rc = m.group(1) if m else "gate_refusal_unknown"
        return {"reason_code": rc, "note": s.strip(),
                "next_action": path_gates.next_action_hint(rc), "files": []}
    return None


def arbitrate_blocked_reason(refusal: Dict[str, Any], verdict_missing: bool = True) -> str:
    """仲裁段闸拒 blocked 的票面文案（t260917-01 ②③）：主因=闸拒（拒绝回执原文
    含点名文件与合法出路），「缺 verdict」只作双因从句且明示不计格式轮次；出路
    指向真实解法（还原越界改动 / 回 main 侧走票 / retry_qc 重跑本段），绝不指向
    「补 verdict 标记」，也不发明「自动改共享资产」类假出路（受保护名单必拦——
    C5 口径：tests-fault 对共享资产红项的诚实归宿=轮次上限转人工）。单行
    （blocked_reason 票面口径；拒绝回执本身行内无换行）。畸形 refusal（缺键）
    仍有可读主因文案，不抛。"""
    import path_gates  # 延迟 import：同上（单文件加载面不牵连仓库兄弟模块）
    r = refusal if isinstance(refusal, dict) else {}
    rc = str(r.get("reason_code") or "gate_refusal_unknown")
    note = str(r.get("note") or "").strip()
    act = str(r.get("next_action") or "").strip() or path_gates.next_action_hint(rc)
    parts = ["仲裁段落盘被闸拒（主因）：%s" % (note or "路径闸拒绝（%s）" % rc),
             "下一步：%s" % act]
    if verdict_missing:
        parts.append("仲裁结论未能落盘（不计「缺 verdict=」格式轮次）——出路：还原越界改动/"
                     "回 main 侧走票后 retry_qc 重跑本段，无需补 verdict 标记")
    return "；".join(parts)


# ---- 人授权例外通道（工单 t260912-03）----
# 受保护路径闸与仲裁上限的「记名留痕、到期作废」放行钥匙。唯一入口＝既有 sign 信号面
# （Signature.authorize 可选载荷），授权与签字同源、同审计面（Temporal 不可变历史）。
# 落地形态 meta['authorizations']=[{kind,who,scope,reason,issued,expires,uses:[...]}]：
# 签发=signal 事件；每次真实消费 append uses（workflow 侧解析 settle 回执的
# path_gate_authz_used= 机读键，只真豁免才记）。默认 fail-closed 不变：无授权 /
# 不匹配 / 已过期 → 两闸行为与装通道前逐字节一致。
AUTH_PROTECTED_PATH = "protected_path"
AUTH_ARBITRATION_VERDICT = "arbitration_verdict"
AUTH_KINDS = (AUTH_PROTECTED_PATH, AUTH_ARBITRATION_VERDICT)

# intake 上限（超限=refused，不进 Temporal 事件历史）。常量同值不同源：与 host_ruling /
# pause 的 note 上限、inspection_flow.MAX_WHO_LEN 各自独立演进，不互相绑死。
AUTHZ_EXPIRES_MAX_SEC = 30 * 24 * 3600      # 授权有效期上限（防「顺手批一年」）
AUTHZ_WHO_MAX_LEN = 64                      # 与 inspection_flow.MAX_WHO_LEN 同值
AUTHZ_REASON_MAX_LEN = 20000                # 与 HOST_RULING/PAUSE_NOTE_INPUT_LIMIT 同值族
AUTHZ_SCOPE_MAX_ITEMS = 16                  # scope 条目数上界
AUTHZ_SCOPE_ITEM_MAX_LEN = 256              # 单条 scope 长度上界

# 全域 agent 角色名（反自签红线的机械口径）：与 inspection_flow.AGENT_ROLE_NAMES 同集合，
# 两集合相等由单测源码锁定（防未来只改一处判定）。
AUTHZ_AGENT_ROLE_NAMES = frozenset(
    {"developer", "integration", "ops", "product-operation", "artist"})

# settle 回执内嵌的机读键（path_gate_reason= 同族，t260910-13 先例）：
#   path_gate_authz_used=<who>@<issued>:<file1,file2>
AUTHZ_USED_KEY = "path_gate_authz_used="

# sign 信号面保留标记值（t260913-01）：client op=authorize 发 sign 信号时 gate 用本值。
# workflow 侧「authorize 载荷缺失但 gate=本值」＝载荷在传输/反序列化一跳丢失（旧 worker
# 的旧 Signature 类不含 authorize 字段，temporalio 解码对未知字段静默丢弃）→ dev_lane
# 的 sign handler 据此 refused 点名「载荷解析失败」，绝不静默回落普通签字路径。
# marker 是标量字段、旧类解码也存活，故丢失在接收侧有痕可判；单测锁它与全部模板的
# 合法 gate 值（Stage.id 全集 ∪ HUMAN_GATES ∪ CLOSE_GATE_ID）不相交。
AUTHZ_SIGNAL_GATE_MARKER = "__authorize__"

# ---- 跨项目写操作闸（t260915-12）：调用方项目身份契约 ----
# 口径：防误操作 + 全程可审计的机器层边界，非对抗性身份鉴别（env 可被有心进程伪造、
# Temporal 直连可绕过 client.py——宿主 260910 已裁身份鉴别不做，audit.py 模块头在案）。
# 四件事：身份有出处（spawn 链注入/显式参数）、不匹配 fail-closed 拒收、越权必记名、记录可对账。
# 身份 env（spawn 链注入位，非密钥；命名对齐 audit.py 的 SANDBAR_CLIENT_ENTRY 家族）：
# 值=项目注册表 key（PROJECT_KEY_RE 白名单）。注入者=包装层/宿主层代码（ticket.py 推导、
# 插件票接线 console/泳道），不是任何 agent 的自由文本。
CALLER_PROJECT_ENV = "SANDBAR_CALLER_PROJECT"
# undeclared 哨兵（盖章载荷专用，review C3）：与「空串=老 client 未盖章」两态互斥——
# undeclared 的写操作也要进 workflow 侧记名账（meta['cross_project_uses']），空值继续
# 承载解码兼容语义（老历史/老 client 解码缺字段→""→不校验不记名）。
CALLER_UNDECLARED_MARK = "__undeclared__"
# undeclared 策略常量（review C-0②：翻严单点。**缺省已翻 "refuse"——翻严执行票
#   =t260925-08（KI-119 收口：泳道 agent 身份注入已接线，undeclared 只剩不经 spawn 链
#   的旁路调用面，fail-closed）**；运维过渡旋钮见 UNDECLARED_POLICY_ENV：
#   "record" = 放行+强制记名——仅经旋钮 SANDBAR_UNDECLARED_POLICY=record 显式选入
#              （console 注入接线前的过渡期用；显式声明、有据可查，非静默降级）。
#   "refuse" = 终态：未声明身份一律结构化拒收（缺省）。
UNDECLARED_POLICY = "refuse"
# 策略旋钮（t260925-08）：值∈UNDECLARED_POLICIES 才认，畸形值=点名 raise（fail-closed，
# 不静默回落——消费面见 undeclared_policy() 与 cross_project_judge 的 fail-closed 包装）。
UNDECLARED_POLICY_ENV = "SANDBAR_UNDECLARED_POLICY"
UNDECLARED_POLICIES = ("record", "refuse")
# 注入面标签 env（t260925-08，尽力面标签非安全断言）：引擎 spawn 链（_prepare_agent_spawn）
# 注入身份时随 CALLER_PROJECT_ENV 一并设 "lane-agent"；identity_receipt 据此区分
# injected_by=lane-agent / external-env。标签只回答「身份从哪个面进来」，不回答
# 「谁注入的」——手工旁路设了同名 env 也会带标签，审计不得单凭此键下「谁操作」断言。
CALLER_SURFACE_ENV = "SANDBAR_CALLER_SURFACE"
CALLER_SURFACE_LANE_AGENT = "lane-agent"
# 越权旗自由文本上限（review C4，intake 上限家族：与 PAUSE/HOST_RULING_NOTE_INPUT_LIMIT、
# AUTHZ_WHO_MAX_LEN 同值不同源——独立常量，各自演进不互相绑死）。超限=结构化拒收。
CROSS_PROJECT_NOTE_LIMIT = 20000
CROSS_PROJECT_BY_LIMIT = 64


def undeclared_policy(env_raw: Optional[str] = None) -> str:
    """undeclared 策略解析（t260925-08 单点）：旋钮 env 值∈UNDECLARED_POLICIES 才认，
    空缺=缺省 UNDECLARED_POLICY（"refuse"），畸形值=点名 raise（fail-closed，不静默回落）。

    client 侧（judge_caller）把 raise 转成结构化拒收回执；workflow 侧（cross_project_judge
    缺省参数路径）把 raise 转 refuse+人话 why——两条路径都不静默（review N3）。"""
    raw = (str(os.environ.get(UNDECLARED_POLICY_ENV) or "")
           if env_raw is None else str(env_raw or ""))
    if not raw.strip():
        return UNDECLARED_POLICY   # 空串/纯空白=unset 语义，回落缺省（不误伤空 env 注入）
    if raw in UNDECLARED_POLICIES:  # 严格等值：不 strip 纠偏——带空白包边=误配，fail-closed
        return raw
    raise ValueError(
        "undeclared 策略旋钮 %s=%r 非法（合法值：%s）——修正或删除该 env 后重试"
        % (UNDECLARED_POLICY_ENV, raw.strip()[:64], "|".join(UNDECLARED_POLICIES)))


def path_under_any(path: str, roots: Sequence[str]) -> bool:
    """path 是否位于 roots 任一前缀之下（含等值）。双侧各试原文与 realpath 两形
    （符号链接稳健：调用方一侧可能传 /var 形、另一侧 /private/var 形）；纯字符串
    前缀判定，零 IO（目录是否存在不在此答——查无此目录=不在任何树下=推导面自然
    回落 undeclared）。"""
    p = str(path or "")
    p_real = os.path.realpath(p) if p else p
    for r in roots or ():
        r = str(r or "")
        if not r:
            continue
        try:
            r_real = os.path.realpath(r)
        except Exception:  # noqa: BLE001
            r_real = r
        for rv in {r, r_real}:
            for pv in {p, p_real}:
                if pv == rv or pv.startswith(rv.rstrip("/") + "/"):
                    return True
    return False


def project_key_for_dir(path: str, projects: Sequence[Dict[str, Any]],
                        exclude_trees: Sequence[str] = ()) -> str:
    """目录→项目 key 反查（cwd 窄兜底推导的单一实现，t260915-12）。

    - longest-prefix 命中某注册项目 dir → 返回该 key（出处=cwd×注册表，机器推导非自由文本）；
    - **引擎仓树排除（review C1，行为级）**：path 位于 exclude_trees 任一前缀之下（含等值
      与任意深度子目录）→ 一律返回 ""——仓树内的 cwd 可能是 admin.py/tools_registry 进程内
      调用（dsh 工具链 spawn cwd=repo）或 console 插件（cwd=server/engine 子目录），此时
      cwd 标识的是「被调用的引擎」而不是「调用方会话」，推导会凭空造出 declared 身份
      （违反「身份不许凭空自认」），宁可 undeclared 记名；
    - 未命中任何注册项目 → ""（undeclared）。
    符号链接稳健性：注册表条目可能写符号链接形态（如 macOS /var/...，bench.write_registry
    刻意不 deref 以锚定原文），而调用方 cwd 常 realpath（/private/var/...）——比较按
    「原文前缀」与「双侧 realpath 归一」各试一遍，任一命中即取（排除树同样双形比对）。
    纯函数：projects/exclude_trees 由调用方注入（load_projects_registry()/REPO_ROOT 的
    realpath），单测直调零环境依赖。"""
    if not str(path or "").strip():
        return ""
    if path_under_any(path, exclude_trees):
        return ""
    path_real = os.path.realpath(str(path))
    best_key, best_len = "", -1
    for p in projects or ():
        for d in (p.get("dirs") or []):
            d = str(d or "")
            if not d:
                continue
            try:
                d_real = os.path.realpath(d)
            except Exception:  # noqa: BLE001
                d_real = d
            # 双形比对：原文前缀（注册表条目锚定原文）+ 双侧 realpath（符号链接归一）
            hit = any(pv == dv or pv.startswith(dv.rstrip("/") + "/")
                      for dv in {d, d_real} for pv in {str(path), path_real})
            if hit and len(d) > best_len:
                best_key, best_len = str(p.get("key") or ""), len(d)
    return best_key if PROJECT_KEY_RE.match(best_key or "") else ""


def cross_project_judge(caller: str, target: str, note: str,
                        policy: Optional[str] = None) -> Dict[str, Any]:
    """workflow 侧第二道判定（纯函数，t260915-12；client 侧矩阵在 caller_gate.py，
    语义同源——两处各自实现原因：workflow 侧只消费盖章值、无身份解析面）。

    caller=信号载荷盖章值（""=老 client 未盖章→兼容放行，KI 兼容口径）；target=本票
    meta['project']（""=无项目身份面的引擎件→无比对对象，放行）。
    返回 {"action": "allow"|"allow_record"|"refuse", "record": dict|None, "why": str}：
    - allow        直接放行（同项目/未盖章/无项目面）；
    - allow_record 放行+记名（record 由调用方补 ts/op 后落 meta['cross_project_uses']）：
        undeclared 哨兵（policy="record" 时）或 declared 异项目带越权旗理由；
    - refuse       declared 异项目无旗（人话点名「谁要动谁的票」）或 undeclared 且
        policy="refuse"（缺省终态，t260925-08 翻严）。
    note 截断进 record（≤300 字符入账，全文不进事件历史——host_ruling 截断同族取舍）。

    policy=None（缺省）=经 undeclared_policy() 解析旋钮；旋钮畸形值不外抛（workflow 侧
    不让策略误配炸闸），转 refuse+人话 why（fail-closed 且可见，review N3）。"""
    if policy is None:
        try:
            policy = undeclared_policy()
        except ValueError as e:
            return {"action": "refuse", "record": None,
                    "why": "跨项目闸：%s（策略误配 fail-closed 拒收）" % e}
    caller = str(caller or "")
    target = str(target or "")
    note = str(note or "").strip()
    if not caller or not target:
        return {"action": "allow", "record": None, "why": ""}
    if caller == target:
        return {"action": "allow", "record": None, "why": ""}
    if caller == CALLER_UNDECLARED_MARK:
        if policy == "refuse":
            return {"action": "refuse", "record": None,
                    "why": "跨项目闸：本票属项目 %s，调用未声明身份且引擎策略=拒收"
                           "（undeclared-policy=refuse）——请经注入链声明调用方项目后再操作" % target}
        return {"action": "allow_record",
                "record": {"caller_project": CALLER_UNDECLARED_MARK, "note": note[:300]},
                "why": "跨项目闸记名：未声明调用方身份的操作落在项目 %s 的票上"
                       "%s（策略=记名放行，经旋钮 %s=record 显式选入；缺省策略=拒收）"
                       % (target, "，理由=%s" % note[:120] if note else "",
                          UNDECLARED_POLICY_ENV)}
    if note:
        return {"action": "allow_record",
                "record": {"caller_project": caller, "note": note[:300]},
                "why": "跨项目越权记名：调用方项目 %s 操作项目 %s 的票（越权旗理由=%s）"
                       % (caller, target, note[:120])}
    return {"action": "refuse", "record": None,
            "why": "跨项目写操作拒收：调用方项目身份 %s 与本票所属项目 %s 不符，且未带"
                   "越权旗（cross_project 理由必填）——只操作本项目的票，确需跨项目走"
                   "越权旗+理由（记名留痕可查）" % (caller, target)}


@dataclass
class HumanAuthorization:
    """sign 信号面的人授权载荷（工单 t260912-03）。who 由调用方注入；agent 角色名
    签发=拒收（反自签红线）。kind=protected_path 时 scope=精确路径或目录前缀；
    kind=arbitration_verdict 时 scope=[本票票号]（别票=拒收——一次授权只对指定票/
    指定路径生效）。expires/issued 为 epoch 秒，issued 由 workflow intake 用
    workflow.now() 盖写（不信任调用方）。"""

    kind: str = ""
    who: str = ""
    scope: List[str] = field(default_factory=list)
    reason: str = ""
    expires: int = 0
    issued: int = 0


def _authz_int(v: Any) -> int:
    """epoch 秒容忍转换：非数/非法一律 0（调用方按 0 处理=fail-closed）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def active_authorizations(items: Any, now_epoch: int, kind: str = "",
                          ticket_id: str = "") -> List[Dict[str, Any]]:
    """meta['authorizations'] 的清洗+生效过滤（纯函数，畸形条目不炸）。只留 dict、
    kind 合法、expires>now；kind 给定再筛类型；kind=arbitration_verdict 且给定
    ticket_id 时 scope 必须含该票号（protected_path 的 scope 是路径面，不做票号筛）。
    返回原条目引用（保序）。"""
    out: List[Dict[str, Any]] = []
    for it in items if isinstance(items, (list, tuple)) else []:
        if not isinstance(it, dict):
            continue
        if str(it.get("kind") or "") not in AUTH_KINDS:
            continue
        if kind and str(it.get("kind") or "") != kind:
            continue
        exp = _authz_int(it.get("expires"))
        if exp <= 0 or exp <= _authz_int(now_epoch):
            continue
        if kind == AUTH_ARBITRATION_VERDICT and ticket_id:
            scopes = it.get("scope")
            scopes = [str(s) for s in scopes] if isinstance(scopes, (list, tuple)) else []
            if str(ticket_id) not in scopes:
                continue
        out.append(it)
    return out


def authorization_scopes(items: Any, now_epoch: int, kind: str,
                         ticket_id: str = "") -> List[str]:
    """生效授权 × kind 的 scope 并集（去重保序，纯函数）：受保护闸的裸 scope 视图
    （供测试与降级读法；生产 args 面走结构化记录，见 authz_gates.split_protected）。"""
    out: List[str] = []
    for it in active_authorizations(items, now_epoch, kind=kind, ticket_id=ticket_id):
        scopes = it.get("scope")
        for s in (scopes if isinstance(scopes, (list, tuple)) else []):
            s = str(s)
            if s and s not in out:
                out.append(s)
    return out


def arbitration_cap_route(verdict: str, tests_rounds: int, code_rounds: int,
                          authorized: bool) -> str:
    """带人授权的仲裁三态路由（纯函数）。authorized=False → 与 integration_route
    逐字节一致（零回归）；True 时**只**把两条上限原因放行到 "acceptance"——授权语义
    是「接受本判决」，判决不存在（verdict 非法）或 blocked 原因非两条上限，授权在场
    也不放行。判定用 verdict×轮次谓词，不做 "blocked:" 字符串前缀匹配（防未来新增
    原因被静默放行）。"""
    route = integration_route(verdict, tests_rounds, code_rounds)
    if not authorized:
        return route
    if verdict == "tests-fault" and tests_rounds > MAX_TESTS_FAULT_ROUNDS:
        return "acceptance"
    if verdict == "code-fault" and code_rounds > MAX_CODE_FAULT_ROUNDS:
        return "acceptance"
    return route


def parse_authz_used(text: Any) -> List[Dict[str, str]]:
    """解析 settle 回执里的机读键 path_gate_authz_used=<who>@<issued>:<f1,f2>
    （纯函数）。多段取全部；畸形段丢弃不炸。返回 [{who, issued, files}]。"""
    out: List[Dict[str, str]] = []
    if not isinstance(text, str) or AUTHZ_USED_KEY not in text:
        return out
    for chunk in text.split(AUTHZ_USED_KEY)[1:]:
        seg = chunk
        for sep in ("；", ";", "\n", "\r"):
            seg = seg.split(sep)[0]
        seg = seg.strip()
        who, at, rest = seg.partition("@")
        issued, colon, files = rest.partition(":")
        who, issued, files = who.strip(), issued.strip(), files.strip()
        if not who or not issued.isdigit() or not colon:
            continue
        out.append({"who": who, "issued": issued, "files": files})
    return out


REVIEW_PLAN_VERDICTS = ("pass", "conditional", "reject")


def parse_review_plan_verdict(status: str, summary: str) -> str:
    """The review_plan three-state verdict (pure function, tested directly by the
    selfcheck; ticket t260903-02's "conditional pass").

    Returns "pass" | "conditional" | "reject". The contract:
    - **status=failed is always reject (the conservative side)**: when the result
      file's status contradicts the summary's verdict marker (failed +
      verdict=conditional), passing is not allowed — passing is a high-risk action, so
      take the conservative side.
    - When status=ok, judge by the summary containing exactly **one**
      ``verdict=pass|conditional|reject`` marker (negative lookahead (?![\\w-]), so
      verdict=pass-foo is not a marker); a missing / multiple / illegal marker always
      falls back to "pass" (compatible with the old two-state status=ok behavior — old
      agent output / old result files without markers don't break).
    - Any other status value (malformed) falls back to reject."""
    if (status or "") == "failed":
        return "reject"
    if (status or "") == "ok":
        hits = re.findall(r"verdict=(pass|conditional|reject)(?![\w-])", summary or "")
        if len(hits) == 1 and hits[0] in REVIEW_PLAN_VERDICTS:
            return hits[0]
        return "pass"
    return "reject"


def review_plan_route(verdict: str, plan_rounds: int) -> str:
    """The review_plan three-state route (pure function, tested directly by the
    selfcheck). Returns "create_plan" | "parallel_impl_design" or "blocked:<reason>".

    conditional (a pass with conditions) does not change the bounce level: like pass it
    goes straight to the implementation stage, and the requested changes are injected
    by the caller into implement's previous_context; it does not count against the
    bounce rounds. reject takes the existing bounce loop."""
    if verdict in ("pass", "conditional"):
        return "parallel_impl_design"
    if verdict == "reject":
        if plan_rounds <= MAX_REVIEW_ROUNDS:
            return "create_plan"
        return "blocked:方案审读打回 %d 轮超限（上限 %d）" % (
            plan_rounds + 1, MAX_REVIEW_ROUNDS)
    return "blocked:审读结论未知 verdict=%r，转人工判读" % verdict


# ---- t260922-18：泳道「主动同步 main」（机械验证前 worker 并一次）纯函数面 ----

def main_sync_conflict_route(rounds: int, files: List[str], prev_files: List[str],
                             cap: int) -> str:
    """主同步冲突消解路由（纯函数，dev_lane 主同步子回路消费）：返回 'resolve' 或
    'blocked:<人话>'。

    与 merge_check 既有冲突回路同一组防呆语义（cap 轮上限 + 同批文件集合连续两轮相同
    →转人工），cap 由调用方传 MAX_CONFLICT_ROUNDS（真源留在 dev_lane，这里不复制常量）。
    files/prev_files 由调用方带仓标识（多仓下不同仓的同名文件不构成「同批反复」，
    review 建议④）。blocked 文案含 grep 稳定锚点：「主同步冲突消解 N 轮未收敛」
    「同批文件反复冲突」。畸形入参（rounds 非正整数、files 非列表）不抛，按保守方向
    照常走防呆判（该 blocked 就 blocked，绝不因畸形放行）。"""
    try:
        rounds_i = int(rounds)
        cap_i = int(cap)
    except (TypeError, ValueError):
        rounds_i, cap_i = 10 ** 9, 0   # 畸形=视同超限，保守转人工
    files_sig = sorted(str(f) for f in (files if isinstance(files, (list, tuple)) else []))
    prev_sig = sorted(str(f) for f in (prev_files if isinstance(prev_files, (list, tuple)) else []))
    files_txt = "、".join(files_sig)[:200]
    if rounds_i > cap_i:
        return ("blocked:主同步冲突消解 %d 轮未收敛（上限 %d），转人工处置：冲突文件 %s"
                % (rounds_i - 1, cap_i, files_txt))
    if prev_sig and files_sig == prev_sig:
        return ("blocked:主同步同批文件反复冲突（连续 2 轮集合相同，第 %d 轮），转人工处置：%s"
                % (rounds_i, files_txt))
    return "resolve"


def main_sync_note(receipt: Any) -> str:
    """主同步回执 → 一行机械证据文案（纯函数；进票面 summary/evidence 与仲裁上下文）。

    receipt 形状 = {"mode": "merged"|"up_to_date", "main_sha": <40hex|短>,
    "lane_head": 短 sha 可缺}。畸形入参（None/非映射/缺键/mode 不在册/sha 空/类型错）
    不抛，返回 ""——调用方降级为显式「无主同步证据」点名，绝不铸造文案。"""
    if not isinstance(receipt, dict):
        return ""
    mode = str(receipt.get("mode") or "")
    sha = str(receipt.get("main_sha") or "").strip()
    head = str(receipt.get("lane_head") or "").strip()
    if mode not in ("merged", "up_to_date") or not sha:
        return ""
    head_txt = ("，lane HEAD=%s" % head) if head else ""
    if mode == "merged":
        return "main@%s 已并入泳道（验证前主同步%s）" % (sha[:7], head_txt)
    return "main@%s 已追平（快路径零动作%s）" % (sha[:7], head_txt)


# ---- Singleton workflow id conventions ----
def pipeline_wf_id(proposal_id: str) -> str:
    """One proposal = one workflow id. A repeated start is rejected by the server
    (AlreadyStarted)."""
    return f"content-pipeline:{proposal_id}"


def wf_id(ticket_id: str) -> str:
    """The ticket workflow id **is** the ticket id (only one orchestration for a given
    ticket can be running at any moment)."""
    return ticket_id


DISPATCHER_WF_ID = "dispatcher-scan"
SCHEDULE_ID = "sandbar-dispatcher-scan"
# The old schedule ID (a server-side persistent identifier, in its retirement window).
# scan_schedule's create/ensure path idempotently deletes the old ID before creating
# the new one (a missing handle doesn't blow up) and logs it; this delete-old line is
# kept for one release cycle (so an old-code engine running alongside cannot rebuild
# the old schedule and double-schedule), and the whole block is removed after that.

# ---- Ticket id prefix used by the demo (the cleanup scripts only recognize this
# prefix and never touch any other ticket) ----
DEMO_PREFIX = "t260821-demo-"
DEMO_TICKET = DEMO_PREFIX + "advance"

# ---- Step 1's seven-stage state machine (ContentPipelineWorkflow backward compat) ----
STAGES: List[str] = [
    "propose",
    "approve",        # human gate (signal)
    "process",
    "machine-qc",     # script gate (an activity runs the real qc_run)
    "ai-review",
    "final-review",   # human gate (signal)
    "publish",
]

HUMAN_GATES = {"approve", "final-review"}

# ---- Step 2: the script-gate mapping (deterministic, written in code; the stage
# machine = deterministic workflow code) ----
# (template_id, stage_id) -> GateSpec. Attached to the stages that "must run green
# before the stage may be left".
# qc_run scope=all / verify_lane content scope=auto / verify_lane code skip_slow=False。
DEFAULT_SCRIPT_GATES: Dict[str, Dict[str, "GateSpec"]] = {}


def default_gate_for(template_id: str, stage_id: str) -> Optional["GateSpec"]:
    """The deterministic script gate: returns the GateSpec for (template, stage), or
    None when there is none."""
    table = {
        ("content-pipeline", "machine-qc"): GateSpec(
            stage="machine-qc", tool="qc_run", args={"scope": "all"}, label="qc_run all"),
        ("content-pipeline", "publish"): GateSpec(
            stage="publish", tool="verify_lane", args={"lane": "content", "scope": "auto"},
            label="verify_lane content"),
        ("regression", "regress"): GateSpec(
            stage="regress", tool="verify_lane", args={"lane": "code"}, label="verify_lane code"),
    }
    return table.get((template_id, stage_id))


# ---- Step 1 data contracts (backward compatible) ----
@dataclass
class QcRequest:
    scope: str = "260627"
    cmd: Optional[List[str]] = None
    label: str = "qc_run"


@dataclass
class QcResult:
    green: bool
    red_count: int
    scope: str
    label: str
    exit_code: int
    checks: List[Dict[str, Any]] = field(default_factory=list)
    raw_head: str = ""


@dataclass
class PipelineInput:
    proposal_id: str
    title: str = ""
    qc: QcRequest = field(default_factory=QcRequest)


@dataclass
class TicketScan:
    total: int
    by_status: Dict[str, int]
    stuck: List[str]
    exit_code: int


# ---- Step 2 data contracts (TicketWorkflow) ----
@dataclass
class EngineCall:
    """One real engine call: `python3 server/admin.py call <tool> <args-json>`."""

    tool: str                                  # ticket | workflow | qc_run | verify_lane …
    args: Dict[str, Any] = field(default_factory=dict)
    why: str = ""                              # the human-readable line that enters the history


@dataclass
class EngineResult:
    """The engine receipt. A business rejection (ValueError) raises nothing; it comes
    back as ok=False for the workflow to judge."""

    ok: bool
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    run_id: str = ""
    exit_code: int = 0
    cmd: str = ""


@dataclass
class GateSpec:
    """A script gate: runs the real acceptance script and only lets the ticket through
    on green. Default cmd = `admin.py call <tool> <args>`."""

    stage: str
    tool: str = "qc_run"
    args: Dict[str, Any] = field(default_factory=dict)
    label: str = ""
    cmd: Optional[List[str]] = None


@dataclass
class GateResult:
    green: bool
    red_count: int
    label: str
    exit_code: int
    checks: List[Dict[str, Any]] = field(default_factory=list)
    raw_head: str = ""


@dataclass
class Signature:
    """A human-gate signature (the signal payload). who = the signer's identity,
    injected by the caller; an agent may never sign under its own role name."""

    who: str
    gate: str = "approve"          # approve | final-review (or another exit=human stage id)
    decision: str = "approve"      # approve | reject
    note: str = ""
    # t260912-03：人授权载荷（唯一入口＝本 sign 信号面）。defaulted=None——老历史事件
    # 反序列化缺字段→None，签字语义逐字节不变；带 authorize 的载荷只在 dev_lane
    # 的 sign handler 被接受，其余三个 handler（base/workflows/inspection_flow）显式拒收。
    authorize: Optional[HumanAuthorization] = None
    # t260915-12 跨项目闸盖章（client.py 过闸后写入，调用方传入值被盖写）：带默认值字段
    # =老历史/老 client 解码→""→workflow 侧不校验不记名（重放安全，TicketInput 先例同款）。
    # caller_project 取值=注册表 key | CALLER_UNDECLARED_MARK（undeclared 记名）；
    # cross_project_note=越权旗理由（空=无旗）。四个写信号载荷同款字段=同族契约。
    caller_project: str = ""
    cross_project_note: str = ""


def sign_face_fingerprint() -> Dict[str, Any]:
    """sign 信号面指纹（t260913-01，单一实现，两端各算各的）。

    dev_lane 的 `sign_face` query 在 **worker 进程内**算一次（旧 worker 没有这个 query
    ⇒ 客户端 query 报「expected but not found」＝结构性陈旧判别）；CLI（每调用新进程、
    代码必新）比对两边指纹：字段集漂移 ⇒ mismatch（带 diff）。据此把「磁盘修了、
    进程没重启」的事故形态在使用点实时点名，authorize 不再盲投旧 worker。
    纯计算、零状态、重放安全（query handler 只读）。"""
    return {
        "face": "sign",
        "fields": sorted(f.name for f in dataclasses.fields(Signature)),
        "authorize_fields": sorted(f.name for f in dataclasses.fields(HumanAuthorization)),
        "marker": AUTHZ_SIGNAL_GATE_MARKER,
    }


@dataclass
class StageAttempt:
    """A record of the agent trying to change state directly (always refused, kept for
    the record)."""

    who: str
    want_stage: str
    reason: str = ""


# Ticket state-machine constants (the same stance as server/tools/ticket.py)
TICKET_STATUSES = ("dispatched", "settled", "verified", "closed", "rework")
TICKET_STAGE_STATES = ("running", "awaiting", "awaiting-human", "blocked")


# ========================================================================================
# Autonomous inspection with expanded scope (ticket t260821-m6-scan-expand): a check
# report over settled / awaiting-human tickets
#
# This section's contracts and pure functions serve only the activity layer
# (scan_tickets_report / write_scan_report) and the self-tests; the workflow body only
# consumes activity return values and never reads the directory/threshold constants
# here to do IO (the determinism rule).
# There are only three suggestion levels (signable / needs work / suspected stuck) —
# inspection only suggests, it never decides; only a human may sign (a red line).
# ========================================================================================

# Where reports are written (env override for self-test temp dirs; default the POC's
# out/scan — a run artifact, gitignored, not committed).
SCAN_DIR = pathlib.Path(os.environ.get("SANDBAR_SCAN_DIR") or (OUT_DIR / "scan"))
# The inspection ticket ledger directory (ticket t260905-03; env override for self-test
# temp dirs; default out/inspection, a run artifact, not committed). The new variable
# name takes the sandbar prefix per the 260904 host order (pre-existing SANDBAR_* are a
# historical debt handled only by a dedicated migration ticket; nothing new may use one).
INSPECTION_DIR = pathlib.Path(os.environ.get("SANDBAR_INSPECTION_DIR") or (OUT_DIR / "inspection"))
# The 「suspected stuck」 dwell-time threshold (hours). env-tunable; read by the
# activity, never enters the workflow body.
SCAN_STUCK_HOURS = float(os.environ.get("SANDBAR_SCAN_STUCK_HOURS") or 48)
# The three suggestion levels (reports are sorted in this order: most urgent first).
SCAN_SUGGESTIONS = ("疑似卡死", "待补", "可签")
# The report red-line statement (written into every report, shown the same way in the
# console).
SCAN_RED_LINE = "巡检只出建议不出决定；签字只能人（sign who=用户/总管）。"


@dataclass
class ScanTicketItem:
    """One pending ticket's inspection row (the fields are the columns of the ticket
    console's 「巡检报告」 section)."""

    ticket_id: str
    title: str = ""
    status: str = ""
    stage: str = ""
    stage_state: str = ""
    dwell_hours: float = 0.0                 # dwell time (since the last projection / log / pending activity)
    acceptance_done: int = 0                 # how many of this stage's acceptance checklist items are checked
    acceptance_total: int = 0                # this stage's acceptance checklist total
    pending_count: int = 0                   # how many pending entries await a ruling
    gate_label: str = ""                     # the latest script-gate label (empty when none)
    gate_green: Optional[bool] = None        # the latest script-gate red/green (None = no record / unavailable)
    suggestion: str = ""                     # suspected stuck / needs work / signable
    reasons: List[str] = field(default_factory=list)


@dataclass
class ScanReport:
    """One inspection's full report (write_scan_report writes out/scan/<date>.json)."""

    generated_at: str
    total_tickets: int
    by_status: Dict[str, int]
    items: List[ScanTicketItem] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)   # suggestion → count
    stuck_hours: float = SCAN_STUCK_HOURS
    exit_code: int = 0
    # The unfiled list (epic-linkage acceptance criterion 3): in-flight ticket ids with
    # no EpicCode (sorted). Opening a ticket without an epic is allowed, but inspection
    # keeps an eye on it; closed tickets are not collected (collecting all history would
    # only multiply noise).
    unfiled: List[str] = field(default_factory=list)


def is_pending_decision(t: Dict[str, Any]) -> bool:
    """The 「pending decision」 test: not closed and (status=settled or
    stage_state=awaiting-human)."""
    if str(t.get("status") or "") == "closed":
        return False
    return (str(t.get("status") or "") == "settled"
            or str(t.get("stage_state") or "") == "awaiting-human")


def _last_activity_ts(t: Dict[str, Any]) -> int:
    """The ticket's last activity time: the max of the projection's updated / log /
    pending."""
    ts = int(t.get("updated") or 0)
    for l in (t.get("log") or []):
        if isinstance(l, dict):
            ts = max(ts, int(l.get("ts") or 0))
    for p in (t.get("pending") or []):
        if isinstance(p, dict):
            ts = max(ts, int(p.get("ts") or 0))
    return ts


def gate_from_log(t: Dict[str, Any]) -> Dict[str, Any]:
    """Script-gate fallback (when Temporal is unreachable): scan the ticket's log in
    reverse for a 「脚本门」 record and read its red/green."""
    for l in reversed(t.get("log") or []):
        note = str((l or {}).get("note") or "")
        if "脚本门" in note:
            return {"label": note[:60], "green": (False if "红灯" in note else None),
                    "source": "log"}
    return {"label": "", "green": None, "source": "无脚本门记录"}


def build_scan_item(t: Dict[str, Any], gate_label: str = "",
                    gate_green: Optional[bool] = None, gate_source: str = "",
                    now_ts: float = 0.0,
                    stuck_hours: float = SCAN_STUCK_HOURS) -> ScanTicketItem:
    """Compute an inspection row from the ticket JSON (the full show output) plus the
    script-gate information. Pure function, self-testable without Temporal.

    Suggestion rules (suggest only, never decide):
      1. dwell ≥ threshold → suspected stuck (highest priority, including a long-waiting
         human gate);
      2. awaiting-human → signable (a human gate waiting for a signature; acceptance is
         all-checked mechanically by sign at signing time);
      3. settled: acceptance not fully checked / the script gate's latest result red →
         needs work; otherwise → signable (acceptance can advance).
    """
    stage = str(t.get("stage") or "")
    acc = [x for x in (t.get("acceptance") or [])]
    checks = []
    if stage and isinstance(t.get("checks"), dict):
        checks = [c for c in (t["checks"].get(stage) or []) if isinstance(c, dict)]
    # The check-rate stance: only count checks whose item is in the current acceptance
    # list — orphan checks left over from earlier stages (an item no longer in
    # acceptance, e.g. old records after a rework re-entered the stage) don't count,
    # otherwise the check rate is distorted.
    acc_items = {str(x) for x in acc}
    done = sum(1 for c in checks
               if c.get("done") and (not acc_items or str(c.get("item") or "") in acc_items))
    total = len(acc)
    pend = [p for p in (t.get("pending") or [])]
    dwell = round(max(0.0, (float(now_ts) - _last_activity_ts(t)) / 3600.0), 1)
    status = str(t.get("status") or "")
    state = str(t.get("stage_state") or "")
    reasons: List[str] = []
    if dwell >= stuck_hours:
        suggestion = "疑似卡死"
        reasons.append("停留 %.1fh ≥ 阈值 %.0fh，期间无任何进展" % (dwell, stuck_hours))
    elif state == "awaiting-human":
        suggestion = "可签"
        reasons.append("人门 %s 挂起待人签字（sign 只能人：approve/reject）" % (stage or "?"))
        if pend:
            reasons.append("另有 %d 条 pending 待裁决说明，签字前过目" % len(pend))
    elif status == "settled":
        issues: List[str] = []
        if total and done < total:
            issues.append("验收清单勾选 %d/%d 未齐（总管验收打勾后可推进）" % (done, total))
        if gate_green is False:
            issues.append("脚本门 %s 最近一次红灯（修好重跑）" % (gate_label or "?"))
        if issues:
            suggestion = "待补"
            reasons.extend(issues)
        else:
            suggestion = "可签"
            if total:
                reasons.append("已交付且验收 %d/%d 全勾，可 advance 推进" % (done, total))
            else:
                reasons.append("已交付（无验收清单），可验收收口")
    else:
        suggestion = "待补"
        reasons.append("状态 %s/%s 非常规待决，需人工判读" % (status, state))
    if gate_green is True:
        reasons.append("脚本门 %s 最近绿灯" % (gate_label or "?"))
    elif gate_green is None and gate_source:
        reasons.append("脚本门：%s" % gate_source)
    return ScanTicketItem(
        ticket_id=str(t.get("id") or ""),
        title=str(t.get("title") or ""),
        status=status,
        stage=stage,
        stage_state=state,
        dwell_hours=dwell,
        acceptance_done=done,
        acceptance_total=total,
        pending_count=len(pend),
        gate_label=gate_label,
        gate_green=gate_green,
        suggestion=suggestion,
        reasons=reasons,
    )


def scan_summary(items: List[ScanTicketItem]) -> Dict[str, int]:
    """Suggestion → count (all three levels always appear, so the console can render
    directly)."""
    s: Dict[str, int] = {k: 0 for k in SCAN_SUGGESTIONS}
    for it in items:
        s[it.suggestion] = s.get(it.suggestion, 0) + 1
    return s


# ========================================================================================
# Workspace mechanization + dispatch-next context assembly (ticket t260821-m45-ticket-engine)
#
# This section is the **single source of truth**: the dispatch-next generators of both
# ticket.py (the old engine path) and workflows.py (the Temporal TicketWorkflow) take
# from here, so the two sides' dispatch prompts cannot drift.
# Every function depends only on its inputs and this module's constants (pure
# functions, executable deterministically inside a workflow sandbox).
# ========================================================================================

# Root for dir-type workspaces: the isolated-directory convention for non-development
# tickets (cleanup / ops) /tmp/sandbar-ws/<ticket id>.
# env SANDBAR_WS_DIR_BASE can override it — self-tests point at a temp dir so the real
# /tmp stays untouched.
WS_DIR_BASE = os.environ.get("SANDBAR_WS_DIR_BASE") or "/tmp/sandbar-ws"


def ws_dir_path(ticket_id: str) -> str:
    """The dir-type ticket workspace path (the old /tmp/suyou-ws base stickiness was
    removed with the final switch — the leftover directories have been cleared)."""
    return WS_DIR_BASE + "/" + ticket_id


# ---- Lane coordination directory naming transition (ticket t260907-04) ----
# Resolution priority (three rules, the order is not negotiable):
#   1. base/.sandbar exists → the new name (if this base also has a .sandbar/, it is
#      only the plugin-face mirror, written but never read — mirror directories are
#      invisible to resolution, so the stickiness decision cannot be flipped by its own
#      artifacts);
#   2. elif base/.suyou exists → the old name (old-lane stickiness: reads and writes
#      are pinned to the old name for the lane's whole life; the two names are never
#      mixed within one base, so handover/archiving never forks);
#   3. else → the new name (with create=True the first write creates .sandbar/, and the
#      plugin-face mirror is filled in by the mirror helper).
# An out-of-band .sandbar (created by a human or a tool by mistake) flips resolution to
# the new name per rule 1 — after that single flip the authority is still unique; treat
# it as an explicit migration rename, not a bug.
# Retirement: the sticky branch (rule 2) retires when the .suyou lane stock reaches
# zero; the mirror helper retires when the plugin-face old-name cleanup closes out. The
# two are decoupled.
DOT_DIR_NEW = ".sandbar"
DOT_DIR_OLD = ".suyou"  # naming-compat
MIRROR_RELPATHS = ("screenshots", "epic-next")   # the plugin face's real read points; only these two are mirrored


def resolve_dot_dir(base, create: bool = False) -> pathlib.Path:
    """Resolve the lane coordination directory under base by the three priorities (the
    new name .sandbar/ wins, with a sticky fallback to DOT_DIR_OLD)."""
    b = pathlib.Path(base)
    new = b / DOT_DIR_NEW
    old = b / DOT_DIR_OLD
    if new.exists():
        return new                       # rule 1: the new name is authoritative; the old name is mirror-only (write, never read)
    if old.exists():
        return old                       # rule 2: old-lane stickiness
    if create:                           # rule 3: the creating side always uses the new name
        new.mkdir(parents=True, exist_ok=True)
    return new


def lane_dot_path(base, *parts, create: bool = False) -> pathlib.Path:
    """A relative path inside the resolved coordination directory (the single entry
    point for the engine's write and read points)."""
    return resolve_dot_dir(base, create=create).joinpath(*parts)


# 多仓泳道清单（repo_worktrees.json）的盘上路径真源：写侧一律落解析位（新泳道=新名
# 协调目录），读侧可开启老名镜像回落（见 multi_manifest_path）。清单名与解析规则都收
# 在这一处——「多处各抄一份名字」是同族教训（KI-074/KI-077，t260914-01 收单源）。
MULTI_MANIFEST_NAME = "repo_worktrees.json"


def multi_manifest_path(base, create: bool = False,
                        legacy_fallback: bool = False) -> pathlib.Path:
    """多仓泳道清单的盘上路径（写读两侧唯一入口）。

    legacy_fallback=True（读侧专用，t260914-01）：解析位不在场时回落到老名固定镜像
    位。存量泳道若已带杂散新名目录而清单仍留在老名（改名过渡期的现实形态），读侧不得
    因为解析规则翻到新名就看不见清单——回落保证与「直读老名」的旧行为一致，单仓回落 /
    损坏清单 RuntimeError 等既有判定语义一概不动。写侧（create=True）不得开回落：新泳道
    只落解析位，否则又是一次「新泳道诞出老名目录」。
    """
    p = lane_dot_path(base, MULTI_MANIFEST_NAME, create=create)
    if legacy_fallback and not p.is_file():
        legacy = pathlib.Path(base) / DOT_DIR_OLD / MULTI_MANIFEST_NAME
        if legacy.is_file():
            return legacy
    return p


def mirror_to_legacy(base, rel: pathlib.Path) -> bool:
    """Transitional mirror for the plugin face: copy the rel file from base's new-name
    coordination directory to the same relative path under DOT_DIR_OLD.
    Only mirrors when resolution yields the new name (an old lane already lives under
    the old name and needs no mirror) and rel's top-level directory is in the
    MIRROR_RELPATHS whitelist; best-effort, a failure never affects the main chain.
    Retirement condition = the plugin-face old-name cleanup closing out, at which point
    this function and all its call sites are deleted."""
    b = pathlib.Path(base)
    if resolve_dot_dir(b) != b / DOT_DIR_NEW:
        return False
    parts = pathlib.Path(rel).parts
    if not parts or parts[0] not in MIRROR_RELPATHS:
        return False
    try:
        src = b / DOT_DIR_NEW / rel
        if src.is_file():
            dst = b / DOT_DIR_OLD / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
    except OSError:
        return False
    return False

WORKSPACE_TYPES = ("worktree", "dir")


def workspace_of(meta: Dict[str, Any], template_lane: str = "") -> Optional[Dict[str, str]]:
    """The ticket's workspace {type: worktree|dir, path}.

    Reads meta['workspace'] first (the M4 field); when an old ticket lacks it, derive
    from the lane (a worktree lane); lane=main with no workspace → None (direct main-tree
    edits, no separate space). Backward compatible.
    """
    ws = meta.get("workspace")
    if isinstance(ws, dict) and ws.get("type") in WORKSPACE_TYPES and ws.get("path"):
        return {"type": str(ws["type"]), "path": str(ws["path"])}
    if template_lane == "worktree" and meta.get("worktree"):
        return {"type": "worktree", "path": str(meta["worktree"])}
    return None


# ---- lane=worktree derivation and validation (the single source of truth for the
# creation chain) ----
# Rules written by three incidents (notes/inbox/260824-ticket-start-lane-params.md):
#   t260824-04 passed only lane=worktree with the lane fields empty → prepare_workspace
#     skipped → the agent ran in an empty directory doing nothing;
#   t260824-10 passed bare worktree/branch strings with no workspace dict → skipped the
#     same way;
#   t260824-11 passed workspace+branch but omitted the worktree string → merge_check
#     silently fell back to the main tree, "clean workspace" was polluted by the main
#     tree's dirty files, and verify_lane tested the wrong code (a fake green).
# The rule: both creation paths (server/tools/ticket.py create / a bare client.py
# ticket-start call) must go through derive_lane_workspace and may no longer derive or
# pass through on their own; the workflow side additionally backstops with
# lane_workspace_gate_error (so an old payload or a future new entry cannot bypass the
# creation validation) — better blocked awaiting a human than silently degraded to the
# main tree / a temp directory.
LANE_WORKTREE = "worktree"


def default_lane_paths(ticket_id: str) -> Tuple[str, str]:
    """Default worktree-lane naming (.lane/t<date>-<alias> / lane/t<date>-<alias>; the
    20260903 host order renamed .worktrees → .lane — the name reflects the concept, not
    a git detail; old-name compatibility in _lane_repo_root / replay_check).

    Chinese text / long strings never enter directory or branch names, they stay in the
    ticket/UI; date + alias keeps it deterministic and collision-free; a purely Chinese
    title falls back to a short md5 hash.
    """
    name = ticket_id if ticket_id.startswith("t") else "t" + ticket_id
    date_part, rest = "", name
    m = re.match(r"^t?(\d{6})-(.*)$", name)
    if m:
        date_part, rest = m.group(1), m.group(2)
    alias = re.sub(r"[^A-Za-z0-9_.-]+", "-", rest).strip("-")
    alias = re.sub(r"-{2,}", "-", alias)[:24].strip("-")
    if not alias:
        import hashlib
        alias = hashlib.md5(rest.encode("utf-8")).hexdigest()[:6]
    wname = ("t%s-%s" % (date_part, alias)) if date_part else ("t" + alias)
    return ".lane/" + wname, "lane/" + wname


# ---------- Ticket t260907-06: multi-repo projects (the parent directory as root, repos as subdirectories) — repo anchor derivation ----------
#
# Directory model: a multi-repo project = the parent directory as the project directory
# and each repo as a subdirectory. When one ticket spans several repos (derived from
# which repo the write-set paths belong to), the lane = <project root>/.lane/<id>/, an
# ordinary directory container holding one tree per repo at <lane>/<repo path relative
# to the project root>; a single-repo project (project root = repo root) never takes any
# activated path in this section — zero behavior change (regression surface).

# The refname-safe segment cleaning family (the same stance as default_lane_paths'
# alias): refname-illegal characters (space / ~ / ^ / : / ? / * / [ / \ and so on) are
# uniformly squeezed to '-', so worktree add -b doesn't fail closed outright.
REFNAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_branch_segment(seg: str) -> str:
    """A repo directory name / path segment → a refname-safe segment. If cleaning
    leaves it empty, fall back to 'repo' (guards an all-illegal name field)."""
    s = REFNAME_UNSAFE_RE.sub("-", str(seg)).strip("-")
    return s or "repo"


def flatten_branch_suffix(repo_rel: str) -> str:
    """A repo path relative to the project root → a branch-name suffix segment
    ('/' → '-', then refname cleaning).

    Uniqueness is guaranteed structurally by repo-path uniqueness (same-basename shapes
    don't collide; nested repos themselves are fail-closed — see repos_under, which does
    not recurse)."""
    return sanitize_branch_segment(str(repo_rel).replace("/", "-"))


def repos_under(project_root) -> List[pathlib.Path]:
    """The git repos under the project root that a lane can attach to (this section's
    only scanning source of truth).

    - If the project root itself has a .git (directory or gitfile) → [project root] plus
      the **one-level-down child repo** set (relaxed by ticket t260907-12: the mixed
      shape where the root is a knowledge repo and child repos coexist — the root repo is
      in the candidate set too; with no child repos under the root it is always
      [project root], so single-repo behavior is unchanged);
    - if the root has no .git → scan **one level** of subdirectories with the same
      stance (a .git directory or a .git file = a worktree-shaped repo).
    The one-level stance is the invariant line's guardrail: the engine's own lanes
    .lane/<id> (a second-level directory directly under the root, whose .git is a gitfile
    pointing back at this repo) must never enter the repo set, otherwise a single-repo
    project carrying historical lanes (sandbar itself) would be misjudged as multi-repo
    and the whole chain would activate by mistake; repos under second-level container
    directories are likewise outside the set and rejected fail-closed as nested repos —
    a write-set path inside an out-of-set repo is rejected at creation, never silently
    attributed to the parent repo (settling against the wrong repo is worse than
    rejecting)."""
    root = pathlib.Path(project_root)
    repos: List[pathlib.Path] = []
    if (root / ".git").exists():
        repos.append(root)
    if root.is_dir():
        try:
            children = sorted(root.iterdir())
        except OSError:
            children = []  # skip unreadable directories best-effort (the scanning source of truth must not die on permissions)
        for child in children:
            if child.is_dir() and (child / ".git").exists():
                repos.append(child)
    return repos


def is_multi_repo_layout(project_root) -> bool:
    """Activation test for multi-repo lane derivation (ticket t260907-12's single
    predicate, shared by the derive and prepare channel legs).

    True = a genuine multi-repo shape: the root has no .git and child repos are found,
    or the root is a repo with at least one child repo alongside (the mixed shape).
    False = a single-repo project (the root has .git and no child repos) — the caller
    takes the old single-repo path with zero behavior change; a root with neither .git
    nor repos is also False (no repos means no ticket; resolve's empty-set rejection is
    the backstop)."""
    root = pathlib.Path(project_root)
    repos = repos_under(root)
    return bool(repos) and (len(repos) > 1 or not (root / ".git").exists())


def _repo_rel(repo: pathlib.Path, rels) -> str:
    for r, rel in rels:
        if r == repo:
            return rel
    return ""


def _repo_root_entry_example(repo_dir: pathlib.Path, prefix: str = "") -> str:
    """整仓拒收文案的列举实例（t260915-04）：仓顶层真实条目≤3（目录带尾斜杠、隐藏项
    跳过），加仓前缀让用户可直接粘进写集。读盘失败/空目录 → 空串（文案省略例句，
    拒收判定不受影响——例句只是人话，不是判定输入）。仅拒收路径上调用，零常驻 IO。"""
    try:
        names = sorted(
            (p.name + "/" if p.is_dir() else p.name)
            for p in repo_dir.iterdir() if not p.name.startswith("."))
    except OSError:
        return ""
    if not names:
        return ""
    return "、".join((prefix + "/" + n) if prefix else n for n in names[:3])


def resolve_repos_for_paths(project_root, paths) -> Dict[str, List[str]]:
    """Write-set paths → which repo owns them (ticket t260907-06's single source of
    truth for repo anchor derivation).

    Returns {repo absolute path string: [write-set entries…]}; any illegal entry →
    ValueError (rejected at creation, pulling "surfaces only after running 1.5 hours"
    forward to the moment of creation). The stance:
      - an entry must be a project-root-relative posix path (not absolute, no ..
        escape);
      - ownership = the **longest-prefix** repo within the repos_under set; outside the
        set (including inside nested repos) → ValueError;
      - an empty repo set → ValueError (a parent-directory-as-root project with no repos
        at all cannot open tickets)."""
    root = pathlib.Path(project_root).resolve()
    repos = repos_under(root)
    if not repos:
        raise ValueError("项目根 %s 下未发现任何 git 仓（多 repo 项目=父目录作根，"
                         "需先建/clone 子仓再开票；引擎不代建仓）" % root)
    # Repo → project-root-relative posix prefix (the root repo = the empty string —
    # relative_to produces "." for the root itself, which must be normalized; longer
    # prefixes first, so ownership lands on the innermost registered repo)
    rels = sorted(((r, "" if r == root else r.relative_to(root).as_posix()) for r in repos),
                  key=lambda x: len(x[1]), reverse=True)
    owner_set = {str(r) for r in repos}
    out: Dict[str, List[str]] = {}
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("写集条目非法（非字符串或空白）: %r" % (raw,))
        entry = raw.strip()
        pp = pathlib.PurePosixPath(entry)
        if pp.is_absolute() or ".." in pp.parts:
            raise ValueError("写集条目必须为项目根相对路径且不得逃逸项目根: %r" % raw)
        # t260915-04（建票期拒收「整仓根形态」，宿主 260915 口径：写集一律列举、
        # 不得把某个 repo 的整个根目录作为写集）：条目归一（PurePosixPath 消尾斜杠/
        # 内嵌 './'）后等于项目根（"."——单仓=整仓；混合形态=根仓）或等于任一成员仓
        # 的根相对路径（如 "fpv-toolchain"；"fpv-toolchain/""fpv-toolchain//"
        # "fpv-toolchain/." 归一后同形）→ 拒收。根因：整仓条目运行期被
        # rebase_write_set 按前缀剥成空串，写集闸 fail-closed 判整仓禁写
        # （dengzhufpv/t260911-07 整票作废形态）——在创建时刻拦下，不给静默失效
        # 留入口，与「嵌套仓 fail-closed」同族。归一结果只用于本判定：归属（最长
        # 前缀）与嵌套仓 fail-closed 逻辑零改动。
        norm = pp.as_posix()
        if norm == "." or any(rel and norm == rel for _r, rel in rels):
            if norm == ".":
                target = "项目根本体（单仓=整仓；混合形态=根仓）"
                example = _repo_root_entry_example(root)
            else:
                target = "成员仓 %s 的整仓根目录" % norm
                example = _repo_root_entry_example(root / norm, norm)
            raise ValueError(
                "写集条目 %r 等于%s——整仓条目运行期会被剥前缀成空串，写集闸 "
                "fail-closed 判整仓禁写（dengzhufpv/t260911-07 整票作废形态）。"
                "要覆盖整仓＝逐个子目录+根文件列举（参照该仓 .gitignore）%s"
                % (raw, target, ("，例：" + example) if example else ""))
        owner = None
        for repo, rel in rels:
            # rel="" (the root repo, the mixed shape) → matches everything under the
            # root as a fallback; child repos have longer rels and sort first → longest
            # prefix wins, so a child repo's paths belong to the child repo.
            if not rel or entry == rel or entry.startswith(rel + "/"):
                owner = repo
                break
        if owner is None:
            raise ValueError("写集条目 %r 不落在项目根 %s 下任何 git 仓内"
                             "（嵌套仓 fail-closed：嵌套仓内文件不可开票）" % (entry, root))
        # Nested-repo test: if an intermediate directory of the owned path has its own
        # .git and is not in the repo set → the entry really belongs to an out-of-set
        # nested repo, reject (never silently attribute it to the outer repo = the
        # prelude to booking against the wrong repo).
        cursor = owner
        for part in entry[len(_repo_rel(owner, rels)):].split("/"):
            cursor = cursor / part
            if part and (cursor / ".git").exists() and str(cursor.resolve()) not in owner_set:
                raise ValueError(
                    "写集条目 %r 落在集合外嵌套仓 %s 内（嵌套仓 fail-closed："
                    "嵌套仓语义属另票，不静默归外层仓 %s）" % (entry, cursor, owner))
        out.setdefault(str(owner.resolve()), []).append(entry)
    return out


def rebase_write_set(write_set, repo_rel: str) -> List[str]:
    """A project-root-relative write set → a tree-root-relative subset (the single
    rebase point for the multi-repo per-tree whitelist test).

    repo_rel="" (single repo) passes through unchanged (regression surface: the
    single-repo test stays byte-identical); when non-empty, the repo prefix is stripped
    and entries that don't belong to this repo don't enter the subset. An entry exactly
    equal to the repo directory name produces nothing (the write-set semantics are
    file paths inside a repo, creation validation already blocks directory entries, and
    this just tolerates the malformed case without blowing up)."""
    ws = list(write_set or [])
    if not repo_rel:
        return ws
    prefix = repo_rel + "/"
    # t260914-02（dengzhufpv/t260911-07 实测）：剥前缀后**必须滤掉空串**。仓名条目
    # （如 "fpv-toolchain/"，多仓票的常见写法：只想圈住成员仓、不逐子目录列）满足
    # startswith(prefix)，剥完剩 ""——而空白条目会被写集闸判「写集非法」fail-closed
    # （path_gates._entries / agent_activities._dirty_within_write_set 同立场），
    # 于是该成员仓整仓禁写、settle 报 write_set_missing 卡死整票。文档早已声明
    # 「等于仓名的条目产出空」，实现此前与之不符；此处对齐文档，不改变既有非空子集语义。
    out = [p[len(prefix):] for p in ws
           if isinstance(p, str) and p.startswith(prefix)]
    return [p for p in out if p.strip()]


def build_repo_worktrees(project_root, write_set, lane_dir_name: str) -> List[Dict[str, str]]:
    """Derive the multi-repo lane details from write-set ownership (the only
    constructor of meta.repo_worktrees' shape).

    Returns [{"repo": the repo path relative to the project root, "name": a
    refname-safe segment, "branch": the lane branch}]; the tree path = repo (built from
    the same name, so the two sides cannot drift). Branch name =
    lane/<lane directory name>-<flattened segment>. Any illegal input → ValueError
    propagates (resolve_repos_for_paths' fail-closed stance)."""
    if not write_set or not isinstance(write_set, list):
        raise ValueError("多仓泳道推导需要非空写集（write_set 为归属推导唯一输入）")
    root = pathlib.Path(project_root).resolve()  # macOS /var → /private/var normalization
    base = sanitize_branch_segment(lane_dir_name)
    entries: List[Dict[str, str]] = []
    seen_branch = set()
    for repo_abs, _paths in resolve_repos_for_paths(project_root, write_set).items():
        repo_rel = pathlib.Path(repo_abs).relative_to(root).as_posix()
        if repo_rel == ".":
            repo_rel = ""  # the root-repo tree (the mixed shape): rel normalized to the empty string
        # repo_rel="" (the root-repo tree) → name explicitly "root" (the tree path = the
        # lane container itself); the theoretical collision of a child repo literally
        # named root is caught by seen_branch fail-closed.
        name = flatten_branch_suffix(repo_rel) if repo_rel else "root"
        branch = "lane/%s-%s" % (base, name)
        if branch in seen_branch:
            raise ValueError("多仓分支名碰撞: %s（压平清洗后仍同名的仓路径需人工改名）" % branch)
        seen_branch.add(branch)
        entries.append({"repo": repo_rel, "name": name, "branch": branch})
    if not entries:
        raise ValueError("多仓泳道推导产出空仓集合（写集 %r）" % (write_set,))
    return entries


def multirepo_fuse_a_error(project_root, write_set, repo_worktrees) -> str:
    """保险丝A（开票拒收，工单 t260910-03）：多仓写集 × 空 repo_worktrees 的
    fail-closed 背闸（dengzhufpv 260910 缺陷：ticket.py 预派生漏传 repo_write_set
    → 单仓 workspace 显式转发 → 成员仓零落仓）。

    语义：写集条目经 resolve_repos_for_paths 归属到**非项目根本体**的成员仓，
    而 repo_worktrees 为空（明细缺失）→ 返回点名条目+归属仓的拒收文案；
    否则返回 ""（放行）。
      - 单仓项目（全部条目归根本体）恒放行——零回归面；
      - repo_worktrees 非空（明细已在，哪怕未必穷尽写集归属）→ 放行：明细的
        **完备性**归保险丝B 在 merge_check 逐仓物化判定，两道保险丝各守一态
        （A 守创建时刻明细缺失，B 守合并时刻物化落成），不在此重复判完备；
      - 显式 workspace/worktree 不能绕过：判据是写集归属，不是派生路径；
      - project_root 为空=归属锚缺失：fail-closed 拒收并点名全部条目（t260910-08
        收口——此前借 Path("").resolve()=cwd 兜底解析，判定随运行目录翻转，
        环境依赖即缺陷；现在零 IO，cwd 无关）；
      - resolve_repos_for_paths 自身的 ValueError（逃逸/嵌套仓/空仓集/条目畸形）
        原样上抛——归属真源故障同样 fail-closed，绝不静默放行。
    真纯函数（无 git 子进程、无 IO），client.py ticket-start 单点消费。"""
    entries = list(write_set or [])
    if not entries:
        return ""
    if isinstance(repo_worktrees, list) and repo_worktrees:
        return ""
    # Ticket t260910-08（cwd 敏感红收口）: an empty project_root = no ownership
    # anchor at all. Previously this fell through to resolve_repos_for_paths(""),
    # where Path("").resolve() = the *current working directory* — the verdict then
    # depended on the directory pytest happened to run from (repo root → offender
    # named; /tmp → the "no git repos" exemption → silently passed). Same input,
    # different cwd, opposite verdict = the verdict is meaningless. The stance is
    # now pinned by the test's own declared reading: no anchor → every write-set
    # entry is an offender → fail-closed reject naming the entries (no repo scan,
    # no cwd dependency — 真纯函数承诺兑现).
    if not project_root:
        return ("保险丝A拒收（t260910-03）：写集条目命中成员仓路径但 project_root 缺失"
                "（归属锚不在）且派生结果 repo_worktrees 为空——无法证伪多仓票缺逐仓"
                "明细=成员仓零落仓（dengzhufpv 260910 缺陷形态），fail-closed 拒收。"
                "%s。请走正规创建链（不显式传 workspace/worktree），由 "
                "derive_lane_workspace 按写集归属产出逐仓明细。"
                % "；".join("<-%s" % e for e in entries))
    root = str(pathlib.Path(project_root).resolve())
    try:
        mapping = resolve_repos_for_paths(project_root, entries)
    except ValueError as e:
        if "未发现任何 git 仓" in str(e):
            return ""  # 仓集合为空=无成员仓可言，保险丝不适用（存量无 .git 注册目录面）
        raise  # 逃逸/嵌套仓/条目畸形：fail-closed 照旧拒收
    offenders = []
    for repo_abs, paths in mapping.items():
        if str(pathlib.Path(repo_abs).resolve()) == root:
            continue  # 归属根仓的条目不触发（单仓/混合形态的根树部分）
        offenders.append((pathlib.Path(repo_abs).name or str(repo_abs), paths))
    if not offenders:
        return ""
    return ("保险丝A拒收（t260910-03）：写集条目命中成员仓路径但派生结果 "
            "repo_worktrees 为空——多仓票缺逐仓明细=成员仓零落仓（dengzhufpv "
            "260910 缺陷形态），拒收。%s。请走正规创建链（不显式传 "
            "workspace/worktree），由 derive_lane_workspace 按写集归属产出逐仓明细。"
            % "；".join("[%s]<-%s" % (name, ",".join(paths)) for name, paths in offenders))


def derive_lane_workspace(
        ticket_id: str, template_lane: str, lane: str = "",
        workspace: Optional[Dict[str, str]] = None,
        worktree: str = "", branch: str = "",
        template_workspace_dir: bool = False,
        project_root: str = "",
        repo_write_set: Optional[List[str]] = None,
) -> Tuple[str, Optional[Dict[str, str]], str, str]:
    """Derivation and validation of lane / workspace / worktree / branch (the single
    source of truth for the creation chain).

    project_root (cross-project, ticket t260903-10): when given, relative lane paths are
    stored as absolute paths (anchored at the project's registered directory) — the nine
    downstream ``if not p.is_absolute(): REPO_ROOT/p`` sites all take the pass-through
    branch, decoupling the engine root from the project root. The default empty = the
    old behavior (relative paths, the runtime side anchoring the engine root, compatible
    with historical payloads where the engine lived inside the project).

    Returns (lane, workspace, worktree, branch); illegal → ValueError (rejected at
    creation, pulling the "surfaces only after running 1.5 hours" error forward to the
    moment of creation). Rules:
      1. lane = explicit or the template lane.
      2. An explicit workspace must be shaped {"type": worktree|dir, "path": non-empty},
         otherwise ValueError.
      3. lane=worktree:
         - a workspace given with type != worktree → ValueError (no chance of a silent
           downgrade);
         - workspace.path and the worktree string both given but different → ValueError
           (the two fields must name the same lane: prepare_workspace uses the former,
           merge_check/merge the latter — two versions of the truth guarantee an
           accident);
         - if one is missing, fill it from the other (path ↔ worktree); if both are
           missing → derived by default_lane_paths;
         - branch default = lane/<lane directory name>.
      4. A non-worktree lane + template_workspace_dir → default
         {type:dir, WS_DIR_BASE/<ticket id>}; otherwise workspace stays None (the
         main-tree lane edits directly, no separate space).
    """
    lane = str(lane or "") or str(template_lane or "")
    ws = None
    if workspace is not None:
        if not isinstance(workspace, dict) or workspace.get("type") not in WORKSPACE_TYPES \
                or not isinstance(workspace.get("path"), str) or not workspace.get("path"):
            raise ValueError(
                "workspace 必须形如 {\"type\":\"worktree|dir\",\"path\":\"...\"}，实际 %r"
                % (workspace,))
        ws = {"type": str(workspace["type"]), "path": str(workspace["path"])}
        # t260910-03：上游（ticket.py 正规入口）经同一本函数派生的多仓明细挂在
        # workspace dict 上，这里重建 dict 时必须保留——否则明细在创建链第二跳被
        # 丢弃，保险丝A 会对正规入口误拒（显式转发 ≠ 旁路：明细来自同一单点派生）。
        if isinstance(workspace.get("repo_worktrees"), list):
            ws["repo_worktrees"] = workspace["repo_worktrees"]
    worktree = str(worktree or "")
    branch = str(branch or "")
    if lane == LANE_WORKTREE:
        if ws is not None and ws["type"] != LANE_WORKTREE:
            raise ValueError(
                "lane=worktree 的工单 workspace.type 必须是 worktree（实际 %r）——"
                "不给 dir/主树静默降级的机会（t260824-04 教训）" % ws["type"])
        if ws is not None and worktree and ws["path"] != worktree:
            raise ValueError(
                "workspace.path（%s）与 worktree（%s）不一致——两字段必须同指一个泳道，"
                "否则 merge_check/merge 与 prepare_workspace 各跑各的（t260824-11 教训）"
                % (ws["path"], worktree))
        # Ticket t260907-06 multi-repo derivation: activates only in a **genuine
        # multi-repo shape** (the test converges on the single is_multi_repo_layout
        # predicate) — lane=worktree, project_root given, no explicit
        # workspace/worktree combination, and either the root has no .git but has child
        # repos, or the root is a repo with child repos alongside (the mixed shape).
        # Any unmet condition → repo_write_set is silently ignored and the old path has
        # zero regression. In a genuine multi-repo shape a derivation failure (escape /
        # nesting / outside any repo) → ValueError, rejected at creation (fail-closed,
        # never a silent attribution to some repo).
        if (repo_write_set and lane == LANE_WORKTREE and project_root
                and ws is None and not worktree
                and is_multi_repo_layout(project_root)):
            _lane_rel, _b = default_lane_paths(ticket_id)
            _lane_dir = _lane_rel.rsplit("/", 1)[-1]
            _entries = build_repo_worktrees(pathlib.Path(project_root), repo_write_set,
                                            _lane_dir)
            ws = {"type": LANE_WORKTREE,
                  "path": project_root.rstrip("/") + "/" + _lane_rel,
                  "repo_worktrees": _entries}
            worktree = str(ws["path"])
            branch = "lane/" + _lane_dir  # a meta-compatible placeholder; the real per-repo branches live in repo_worktrees
        if ws is not None:
            worktree = worktree or ws["path"]
        elif worktree:
            ws = {"type": LANE_WORKTREE, "path": worktree}
        else:
            worktree, branch = default_lane_paths(ticket_id)
            ws = {"type": LANE_WORKTREE, "path": worktree}
        if not branch:
            branch = "lane/" + ws["path"].rstrip("/").rsplit("/", 1)[-1]
    elif ws is None and template_workspace_dir:
        ws = {"type": "dir", "path": ws_dir_path(ticket_id)}
    if project_root and ws is not None and not ws["path"].startswith("/"):
        ws = {"type": ws["type"], "path": project_root.rstrip("/") + "/" + ws["path"]}
        if worktree and not worktree.startswith("/"):
            worktree = project_root.rstrip("/") + "/" + worktree
    return lane, ws, worktree, branch


def lane_workspace_gate_error(meta: Dict[str, Any]) -> str:
    """The workflow side's last line of defense: when meta declares lane=worktree but
    the lane fields are incomplete/inconsistent → an error message (the caller returns a
    blocked receipt and refuses to run); when complete → "".

    The creation chain already derives and validates at a single point
    (derive_lane_workspace); this catches "old tickets / hand-written payloads / future
    new entry points" bypassing the creation validation — better blocked awaiting a
    human than silently degraded to the main tree / a temp directory.
    """
    if str(meta.get("lane") or "") != LANE_WORKTREE:
        return ""
    ws = meta.get("workspace")
    if not (isinstance(ws, dict) and ws.get("type") == LANE_WORKTREE and ws.get("path")):
        return ("lane=worktree 但 workspace 未登记 worktree 泳道（实际 %r）——创建链路漏推导，"
                "拒跑。请核对 ticket-start/create 入参（t260824-04 教训）" % (ws,))
    wt = str(meta.get("worktree") or "")
    if not wt:
        return ("lane=worktree 但 worktree 字段为空——merge_check/merge 会静默回落主树"
                "（t260824-11 教训），拒跑。正确值应为 %s" % ws["path"])
    if wt != str(ws["path"]):
        return ("workspace.path（%s）与 worktree（%s）不一致——两字段必须同指一个泳道，拒跑"
                % (ws["path"], wt))
    if not str(meta.get("branch") or ""):
        return "lane=worktree 但 branch 字段为空——泳道分支缺失，拒跑"
    # Ticket t260907-06 multi-repo lanes: repo_worktrees present = a multi-repo ticket —
    # validate the shape per repo (repo is a project-root-relative path string, **an
    # empty string allowed = the root-repo tree** (the mixed shape, where the tree = the
    # lane container itself), name/branch non-empty strings, branch unique).
    # Ticket t260908-02 read order: the source of truth has been lifted to meta's top
    # level (TicketInput.repo_worktrees lands in meta); an empty top-level list = the new
    # field's default (a single-repo ticket), pass straight through; when falling back to
    # the old position nested in ws, the existing contract is kept (present = validate,
    # including an empty list = details missing, reject), catching "future new entry
    # points / hand-written payloads / fixtures calling directly" that bypass the
    # creation chain — not old RUNNING tickets (a payload of the old shape fails at the
    # very first decode hop and cannot be in flight).
    if "repo_worktrees" in meta:
        return _repo_worktrees_gate_error(meta.get("repo_worktrees") or None)
    return _repo_worktrees_gate_error(ws.get("repo_worktrees"))


def _repo_worktrees_gate_error(rw):
    """Per-repo shape/semantics validation of repo_worktrees (rw=None = not a multi-repo
    ticket, pass)."""
    if rw is None:
        return ""
    if not isinstance(rw, list) or not rw:
        return ("workspace.repo_worktrees 形状非法（须非空列表，实际 %r）——多仓泳道"
                "明细缺失，拒跑（t260907-06 票B：meta.repo_worktrees=唯一真源）" % (rw,))
    seen = set()
    for e in rw:
        if not isinstance(e, dict):
            return ("workspace.repo_worktrees 条目须为对象，实际 %r——拒跑" % (e,))
        if not isinstance(e.get("repo"), str):
            return ("workspace.repo_worktrees 条目 repo 字段缺失或非字符串（%r）——"
                    "拒跑" % (e,))
        if not (isinstance(e.get("name"), str) and e["name"]):
            return ("workspace.repo_worktrees 条目 name 字段缺失或为空（%r）——拒跑" % (e,))
        if not (isinstance(e.get("branch"), str) and e["branch"]):
            return ("workspace.repo_worktrees 条目 branch 字段缺失或为空（%r）——拒跑"
                    % (e,))
        if e["branch"] in seen:
            return ("workspace.repo_worktrees 分支名碰撞: %s——拒跑" % e["branch"])
        seen.add(e["branch"])
    return ""


# An explicit contract (ticket t260822-m4③): 「one space, one agent / a handover relay」.
#   Occupancy = while the ticket's stage_state=running, the space has an owner;
#   Transfer = a rework / the next dispatch-next swaps the agent, and the taker reuses
#   the same space.
OWNERSHIP_CONTRACT = (
    "工作空间契约（M4「一个空间一个 agent / 转移接力」）：\n"
    "  - 占用：本工单 stage_state=running 期间，上述工作空间归你（当前 agent）独占——"
    "不得进入其它工单的泳道/隔离目录，产物也不得写到本空间之外。\n"
    "  - 转移：rework 或下一次 dispatch-next 即换 agent 接力，接手方复用同一空间——"
    "所以中间产物必须落盘可接力（worktree 小步 commit / dir 产物全落隔离目录并列清单）。"
)


def _workspace_clause(ws: Optional[Dict[str, str]], meta: Dict[str, Any]) -> str:
    """The dispatch-next workspace clause (three shapes by type: a worktree lane / a dir
    isolated directory / the main tree).

    M16: the workspace has already been created/reused by the workflow's first activity
    (prepare_workspace) — the agent walks straight in and works; it must not run git
    worktree add / mkdir itself.
    """
    if ws and ws["type"] == "worktree":
        wt = ws["path"]
        br = str(meta.get("branch") or "")
        base = str(meta.get("base_ref") or "")
        return (
            "工作空间（worktree 泳道，持久化条款 QA A2.1/A2.2）：%s 已由 workflow 第一个 "
            "activity（prepare_workspace）创建/复用（基点=create 时主树 HEAD %s，base_ref 已登记，"
            "分支 %s），**勿重建勿新建，直接进入干活，勿自行 git worktree add / mkdir**。"
            "泳道跨 agent 会话持久，本次 agent 若挂掉，下次起来仍用同一泳道，"
            "中间产物/分支改动全部还在。"
            "开工前先在泳道内 git status 快照上报总管（脏/冲突先裁决再动手），"
            "再 git fetch main + rebase 主树最新（冲突由总管协调原作者判读消解）。"
            % (wt, base, br))
    if ws and ws["type"] == "dir":
        return (
            "工作空间（dir 隔离目录，M4②）：%s 已由 workflow 第一个 activity（prepare_workspace）"
            "mkdir -p，**直接进入干活，勿自行 mkdir**。本工单一切临时产物、备份、"
            "脚本输出、报告一律落此目录，不散落仓库其它位置或 $TMPDIR 他处；"
            "结算 note 附产物清单（逐项路径+一句话说明），转移/收口时接手方凭清单接管。"
            % ws["path"])
    return "工作空间：主树（数据道，不建 worktree 不开隔离目录），小步落盘直接提交。"


# ---- Indexing the dispatch context (KI-035, ticket t260904-03) ----
# The old regime is retired: a workflow mapping table + title keywords decided which
# design documents were pushed into every stage's dispatch header as 「required reading,
# in this order」 — the agent re-read the whole mechanism document every session (token
# spend unrelated to the ticket at hand), and the mapping was hand-coupled to the actual
# state of docs/ (the 260904 migration broke it, while documents of projects staying on
# sandbar were still being pointed at). The new regime = a constant knowledge-base rule:
# the directory = docs/README.md; the agent judges relevance against the ticket's
# title/write set, reading in full what is relevant and skipping what is not; the settle
# note lists a 「docs consulted」 list for audit. Never again derive required reading
# from workflow/title (the old table's values and the full retirement case are in the
# KI-035 row; zero residue is mechanically enforced by the
# integration/t260904-03 scenario guard).


# Stage-specific clauses (ticket t260822-m5②): the content-pipeline ai-review stage (retired 260904)
# wired the knowledge review closed loop.
# This table is retained data: the dispatch-header engine and the t260904-03 guard still
# consume it.
STAGE_CLAUSES: Dict[Tuple[str, str], List[str]] = {
    ("content-pipeline", "ai-review"): [
        "审校落盘条款（M5 review 闭环）：逐块意见落 docs/reviews 制式——"
        "python3 server/plugins/knowledge/review_store.py save '<json>'"
        "（block_key 取知识库 /sandbar-knowledge/api/diff 的块键；整篇意见用 doc: 前缀自由锚点）；"
        "报告附 python3 server/plugins/knowledge/review_store.py rework <path> 生成的"
        "一键复制返工指令（可直接贴进 ticket rework note）。",
    ],
}


# ========================================================================================
# Ticket t260822-m10: dispatch-next picks the dispatch instance per stage
#
# One role can have several dispatch instances (product-operation's four specializations:
# production / review / verification / data extraction).
# This table = the single source of truth for template stage → specialization kind
# (**fewer but safer**: only mappings where "this stage must be carried by a
# specialization instance" belong here; when unsure, leave it out; stages with no
# mapping use the default instance dispatch_<role>).
# The specializations' model homes are written in KIND_MODELS for prompt display (source
# of truth = the tasks section of model-routes.yaml, with a cross-assertion in
# smoke_routes.py to prevent drift).
# ========================================================================================

STAGE_DISPATCH_KIND: Dict[Tuple[str, str], str] = {
    ("content-pipeline", "ai-review"): "proofread",   # the AI review stage → the review specialization instance
    ("proofread", "review"): "proofread",             # the standalone review stage → the review specialization instance
    ("regression", "regress"): "qa",                  # the standalone regression stage → the verification specialization instance
    ("dev-lane", "integration_review"): "qa",         # integration review (a diff review) → the verification specialization instance
}

KIND_LABELS: Dict[str, str] = {"proofread": "审校", "qa": "验证", "analyst": "出数"}
# Still referenced by the v1 old engine (build_dispatch_prompt, frozen for replay) — do
# not delete:
KIND_DOCS: Dict[str, str] = {"proofread": "proofreader.md", "qa": "qa.md", "analyst": "analyst.md"}
KIND_MODELS: Dict[str, str] = {"proofread": "zai/glm-5.2", "qa": "zai/glm-5.2", "analyst": "zai/glm-5.2"}

# ---- Runtime model routing (the only consumer left after gen.py retired: an agent
# activity looks up the table at spawn time) ----
# Lookup rule: roles.<role>.tasks.<kind> → roles.<role> → default; if all miss, return
# None (no override, the agent uses the profile's default model). The single truth
# source is the file declared by the project registry entry's paths.model_routes
# (contract ①d; see routes_file_for_spawn). The in-repo server/model-routes.yaml was
# retired (t260914-05): a stale in-repo table that the read side silently falls back to
# is worse than having no table at all — a missing table gets named loudly, a stale one
# gets used silently (260914 live incidents A/B both pinned agents to a dead account).

# 路由表解析四态（t260910-14 三态化；t260914-05 兜底分支退役）：state ∈
#   ok           —— 声明指向文件存在且可解析（真源生效）
#   decl_missing —— 条目未声明 paths.model_routes（无表，不回落任何仓内文件）
#   file_missing —— 声明存在但文件缺失
#   bad_content  —— 声明文件存在但不可解析（含读不了/目录当表/yaml 顶层非映射：标量、
#                   列表；以及查表链形状坏：roles/条目/tasks 值非映射，260915 gen2 收口）
# 任何非 ok 态：table=None、path=声明路径（decl_missing 为 ""），并由本函数单点
# **点名告警**（state+path+指纹+原因，decl_missing 附建表建议落点）——查表侧回落
# profile 默认再由消费方点名一次，禁静默。指纹=fingerprint（实际读到字节的 sha256 前 12）。


def routes_fingerprint(path: Any) -> str:
    """内容指纹：实际读到字节的 sha256 前 12 位（"sha256:<12hex>"）；无字节可读=""。"""
    try:
        data = pathlib.Path(path).read_bytes()
    except Exception:
        return ""
    return "sha256:" + hashlib.sha256(data).hexdigest()[:12]


def _routes_landing_hint() -> str:
    """缺表点名时给的建表建议落点与模板指引（人可见话术，防「不知道去哪建表」）。"""
    return ("建表建议落点 ~/.sandbar/projects/<key>/model-routes.yaml"
            "（模板=docs/model-routes-sample.yaml，落 paths.model_routes 声明后生效）")


def _log_routes_state(state: str, path: Any, fingerprint: str, error: str) -> None:
    """非 ok 态单点点名：state+path+指纹+原因——任何消费方都共享同一条留痕。"""
    logging.getLogger(__name__).warning(
        "[model_route] 路由表解析非 ok（state=%s，读=%s，指纹=%s）：%s",
        state, str(path) or "（无表）", fingerprint or "（无字节）", error)


def _routes_table_shape_error(table: Dict[str, Any]) -> Optional[str]:
    """查表链形状校验（260915 gen2，P5 另一半）：roles/条目/tasks 在位时必须是映射。

    消费方 model_route_for 沿链 .get 取值——这些位置出现标量/列表会让 spawn 以
    AttributeError 晦涩崩溃（260915 独立探针实证）。回 None=形状可用；回 str=人话
    原因（resolve 层收进 bad_content 点名，带字节指纹）。default 段非映射**不拦**：
    消费方 isinstance 容错、查表链跳过=default 不命中，语义既有且不崩（不为它扩态，
    防语义漂移）。"""
    roles = table.get("roles")
    if roles is not None and not isinstance(roles, dict):
        return "roles 段不是映射（yaml 顶层 roles=%s）" % type(roles).__name__
    for name, entry in (roles or {}).items():
        if entry is not None and not isinstance(entry, dict):
            return "roles.%s 条目不是映射（=%s）" % (name, type(entry).__name__)
        tasks = (entry or {}).get("tasks")
        if tasks is not None and not isinstance(tasks, dict):
            return "roles.%s.tasks 不是映射（=%s）" % (name, type(tasks).__name__)
    return None


def resolve_routes_table(project_key: str) -> Dict[str, Any]:
    """Model route table resolution — 单一入口（真源=paths.model_routes 指向的文件；
    UI 读写与引擎查表共用同一解析，contract ①d）。

    Returns {"state", "declared", "path", "table", "error", "fingerprint"}:
      state       —— 上方四态之一
      declared    —— 声明的绝对路径（未声明=None）
      path        —— 声明指向的文件（未声明=""；不再回落任何仓内表）
      table       —— 解析成功的表（dict）或 None（非 ok 态一律 None）
      error       —— 非 ok 态的人话原因（ok 态为空串）
      fingerprint —— 本分支实际读到字节的 sha256 前 12（"sha256:<12hex>"）；无字节可读=""
    非 ok 态在本函数内单点 WARNING 点名（state+path+指纹+原因）；条目文件本身解析不了
    仍照旧 fail-closed（ProjectPathsError 传播）。"""
    import yaml  # pyyaml（engine venv）
    info = project_paths(project_key)
    declared = info["model_routes"]
    if declared is None:
        err = ("未声明 paths.model_routes（读侧不再回落仓内表；条目=%s）；%s"
               % (info["entry"] or "（条目缺失/未注册）", _routes_landing_hint()))
        _log_routes_state("decl_missing", "", "", err)
        return {"state": "decl_missing", "declared": None, "path": "", "table": None,
                "error": err, "fingerprint": ""}
    declared = pathlib.Path(declared)
    try:
        raw = declared.read_bytes()
    except FileNotFoundError:
        err = "声明指向的路由表文件缺失：%s；%s" % (declared, _routes_landing_hint())
        _log_routes_state("file_missing", declared, "", err)
        return {"state": "file_missing", "declared": declared, "path": declared,
                "table": None, "error": err, "fingerprint": ""}
    except Exception as e:  # 目录当表/权限/不可读：坏表族（无字节可指纹）
        err = "声明指向的路由表不可解析（读取失败）：%s（%s）" % (declared, str(e)[:160])
        _log_routes_state("bad_content", declared, "", err)
        return {"state": "bad_content", "declared": declared, "path": declared,
                "table": None, "error": err, "fingerprint": ""}
    fp = "sha256:" + hashlib.sha256(raw).hexdigest()[:12]
    try:
        parsed = yaml.safe_load(raw.decode("utf-8"))
    except Exception as e:
        err = "声明指向的路由表不可解析：%s（%s）" % (declared, str(e)[:160])
        _log_routes_state("bad_content", declared, fp, err)
        return {"state": "bad_content", "declared": declared, "path": declared,
                "table": None, "error": err, "fingerprint": fp}
    table = parsed or {}   # 空文件/空文档=空表（软语义：条目缺→查表回落 profile 默认，契约 ①d）
    if not isinstance(table, dict):
        # 可解析但顶层非映射（标量/列表）：UI 半一直判 bad_content（行式解析器拒收），
        # py 半若放行，消费方 model_route_for 会在 .get 处 AttributeError 晦涩崩溃——
        # 统一收进 bad_content 点名态（py/TS 同判，t260914-05 P5 收紧）。
        err = ("声明指向的路由表不是映射结构（yaml 顶层=%s）：%s（须为 default:/roles: 键值映射）"
               % (type(parsed).__name__, declared))
        _log_routes_state("bad_content", declared, fp, err)
        return {"state": "bad_content", "declared": declared, "path": declared,
                "table": None, "error": err, "fingerprint": fp}
    shape_err = _routes_table_shape_error(table)
    if shape_err:
        # 形状坏表（roles/条目/tasks 值非映射）：同族收口（260915 gen2）——消费方沿链
        # .get 必崩，与顶层非映射一样收进 bad_content 点名，禁晦涩堆栈。
        err = "声明指向的路由表形状不可用：%s：%s" % (shape_err, declared)
        _log_routes_state("bad_content", declared, fp, err)
        return {"state": "bad_content", "declared": declared, "path": declared,
                "table": None, "error": err, "fingerprint": fp}
    return {"state": "ok", "declared": declared, "path": declared, "table": table,
            "error": "", "fingerprint": fp}


def model_route_for(role: str, kind: str = "",
                    routes_file: Optional[pathlib.Path] = None,
                    table: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, str]]:
    """Read the model route table for (role, kind)'s provider/model. Called from the
    activity side (IO allowed).

    routes_file 必选单点（t260910-14：常量隐式缺省取消；或直接传 resolve_routes_table
    的 table 免二次 IO）。文件读取失败/顶层非映射/查表链形状坏=None 但**留痕**（logging
    warning 点名路径与原因，KI-030 收窄——不再静默；260915 P5/gen2 收紧：非映射与形状坏
    表不再 AttributeError 晦涩崩溃，与 resolve_routes_table 的 bad_content 同判）；解析
    容错（缺条目/缺字段→default→None）语义不变。"""
    if table is None:
        if routes_file is None:
            raise ValueError("model_route_for: routes_file 必选（t260910-14 单点化）——"
                             "或传 resolve_routes_table 的 table")
        try:
            import yaml  # pyyaml (engine venv)
            loaded = yaml.safe_load(pathlib.Path(routes_file).read_text("utf-8"))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[model_route_for] 路由表读取失败（回落 profile 默认，留痕）：%s（%s）",
                routes_file, str(e)[:160])
            return None
        table = loaded or {}   # 空文件=空表（软语义）
        if not isinstance(table, dict):
            import logging
            logging.getLogger(__name__).warning(
                "[model_route_for] 路由表顶层非映射（回落 profile 默认，留痕）：%s"
                "（yaml 顶层=%s，须为 default:/roles: 键值映射）",
                routes_file, type(loaded).__name__)
            return None
        shape_err = _routes_table_shape_error(table)
        if shape_err:
            import logging
            logging.getLogger(__name__).warning(
                "[model_route_for] 路由表形状不可用（回落 profile 默认，留痕）：%s（%s）",
                routes_file, shape_err)
            return None
    eff = LEGACY_ROLE.get(role, role)
    # 直传表（绕过 resolve）形状坏=不命中（点名归 resolve 面与直读留痕），此处只防崩
    roles = table.get("roles") if isinstance(table, dict) else None
    entry = (roles.get(eff) if isinstance(roles, dict) else None) or {}
    if not isinstance(entry, dict):
        entry = {}
    cands = []
    if kind:
        tasks = entry.get("tasks")
        cands.append(tasks.get(kind) if isinstance(tasks, dict) else None)
    cands.append(entry)
    cands.append(table.get("default"))
    for cand in cands:
        if isinstance(cand, dict) and cand.get("provider") and cand.get("model"):
            return {"provider": str(cand["provider"]), "model": str(cand["model"])}
    return None

# Retired role → new role fallback (the template snapshots pinned inside running
# tickets still carry the old role ids; new tickets always use the new templates and new
# roles).
# Normalize the role first, then apply the specialization: the old template's ai-review
# stage had role=proofreader → product-operation with the proofread specialization.
LEGACY_ROLE: Dict[str, str] = {
    "dispatcher": "integration",
    "editor": "product-operation",
    "proofreader": "product-operation",
    "qa": "product-operation",
    "analyst": "product-operation",
}


def dispatch_instance_for(workflow_id: str, stage: str, role: str) -> Tuple[str, str, str]:
    """Pick the dispatch tool instance name by (workflow, stage, role). Returns
    (tool_name, effective_role, kind) (kind = '' when there is none; effective_role =
    the new role id after normalizing the old role)."""
    eff = LEGACY_ROLE.get(role, role)
    kind = STAGE_DISPATCH_KIND.get((workflow_id, stage), "")
    tool = "dispatch_" + eff.replace("-", "_") + (("_" + kind) if kind else "")
    return tool, eff, kind


def build_dispatch_prompt(tid: str, meta: Dict[str, Any], template_lane: str,
                          stage_def: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """The dispatch-next dispatch prompt (the single generator shared by ticket.py's old
    path and the TicketWorkflow).

    Returns (prompt_text, parts). parts lets the caller expose the pieces in a
    structured form (context / workspace and so on).
    """
    stage = str(meta.get("stage") or "")
    role = str(stage_def.get("role") or "")
    acc = list(stage_def.get("acceptance") or [])
    ws_list = list(meta.get("write_set") or [])
    wid = str(meta.get("workflow_id") or "")
    title = str(meta.get("title") or "")
    ws = workspace_of(meta, template_lane)
    # Pick the dispatch instance per stage (the old role normalized first; a
    # specialization stage picks the specialization instance)
    tool, eff_role, kind = dispatch_instance_for(wid, stage, role)
    # Contract ①d (ticket t260903-03): the directory base of role_doc/kind_doc comes
    # from the registered entry's declared paths.roles_dir, falling back to
    # DEFAULT_ROLES_DIR when undeclared (the relative-path string shape matches
    # pre-change behavior).
    # The prompt is only textual guidance; a missing declared anchor reports red at the
    # spawn-time real consumer (roles_dir_for_spawn); an entry file that itself cannot
    # be parsed still fails closed as usual (ProjectPathsError propagates).
    roles_rel = roles_rel_for_prompt(str(meta.get("project") or ""))
    role_doc = "%s/%s.md" % (roles_rel, eff_role)
    kind_doc = ("%s/%s" % (roles_rel, KIND_DOCS[kind])) if kind else ""
    role_show = eff_role + ("（旧 role %s 已归一）" % role if role != eff_role else "")
    if kind:
        role_show += "（分工=%s）" % KIND_LABELS[kind]

    header = [
        "【派活指令】工单 %s（%s）当前阶段：%s（%s，角色=%s）"
        % (tid, title, stage, stage_def.get("name", ""), role_show),
        "1. 必读上下文清单（按序先读再动手）：",
        "   ① CLAUDE.md（仓库根，项目交接说明——**只读**，不得修改）",
        "   ② %s（岗位说明书全文：铁律/红线/交接物约定；判断不了记录交回，不硬改）%s"
        % (role_doc, (" + %s（分工卡，同读）" % kind_doc) if kind else ""),
        "   ③ 知识库：docs/ = 定稿知识库，目录=docs/README.md（每篇一句话用途；"
        "机器索引 docs/index.json 备用）。动手前对照目录与你的标题/写集判断相关"
        "设计文档，相关的读全文，不相关不读。",
    ]
    items = [
        "工单：admin.py call ticket show {\"id\":\"%s\"} 读工单全文（写集/验收/交接物/挂起项）。" % tid,
        "派活工具：%s（%s）。"
        % (tool, ("分工实例：%s分工，模型 %s（审校家——与加工生成不同家，异模型交叉不变弱）；"
                  "只判不改纪律不因角色合并而松动" % (KIND_LABELS[kind], KIND_MODELS[kind]))
           if kind else "默认实例"),
    ]
    if ws_list:
        items.append("写集（只允许动这些）：%s" % "；".join(ws_list))
    items.append(_workspace_clause(ws, meta))
    items.append(OWNERSHIP_CONTRACT)
    if acc:
        items.append("验收清单（预写死，结算时自检，总管/qa 复核）：%s" % "；".join(acc))
    for clause in STAGE_CLAUSES.get((wid, stage), []):
        items.append("段专项条款：%s" % clause)
    if stage_def.get("exit") == "human":
        items.append("出口条件：本段完成后推进将进入 awaiting-human（等人工签字），结算时注明等待人工终审。")
    items.append("小步落盘：每项变更一个 commit（message 写清根因/方案），不要攒到最后一次性提交。")
    items.append("结算：admin.py call ticket update {\"id\":\"%s\",\"status\":\"settled\",\"note\":\"<验收输出>\"}，"
                 "note 附验收结果与遗留问题（dir 类工作空间另附产物清单），"
                 "末列参考 docs 清单（读过哪些路径；空则写无）。" % tid)
    lines = header + ["%d. %s" % (i + 2, it) for i, it in enumerate(items)]
    prompt = "\n".join(lines)
    parts = {
        "role": eff_role,
        "role_doc": role_doc,
        "kind_doc": kind_doc,
        "dispatch_tool": tool,
        "dispatch_kind": kind,
        "ticket_id": tid,
        "context": ["CLAUDE.md", role_doc] + ([kind_doc] if kind_doc else []),
        "write_set": ws_list,
        "acceptance": acc,
        "workspace": ws,
        "workspace_clause": _workspace_clause(ws, meta),
        "ownership_contract": OWNERSHIP_CONTRACT,
        "small_steps": "每项变更一个 commit；settled 附验收输出",
    }
    return prompt, parts


# ========================================================================================
# Ticket t260822-m11: templates as code — the workflow-class shared contract
# (code-lane/build-workbench deleted; content-pipeline/proofread/regression/cleanup retired 260904,
# leaving only dev-lane; the 「five templates / six templates」 wording in historical
# documents predates the deletion)
#
# The source of truth = code: each template's stage chain is translated straight from
# yaml into the STAGES class attribute (Stage tuples) of its subclass, and
# workflows/*.yaml is demoted to a reference snapshot generated by gen_workflows_doc.py
# (never hand-edited).
# Everything in this section is pure data / pure functions: deterministically usable
# inside a workflow sandbox, zero IO.
# ========================================================================================

# The v2 engine marker (snapshot['engine']; ticket.py/client.py route old/new paths on it)
ENGINE_V2 = "template-as-code-v2"
ENGINE_VERSION_V2 = 3

# The executor enumeration (ticket t260828-01, the observability ticket 「executors made
# visible」): a declaration of the combination of a stage's internal activities (parts) —
# agent = 🤖 run by the agent / script = ⚙️ script, programmatic / human = 👤 manual.
# No single value per stage (implement = agent + script and merge = human + script are
# mixed executions that already exist; a single value would force the code to lie). The
# dynamic source of truth is still the Temporal history; parts is only a static
# declaration (used by the ticket console badges).
PART_KINDS: Tuple[str, ...] = ("agent", "script", "human")


@dataclass(frozen=True)
class Stage:
    """The definition of one stage (an element of a subclass's STAGES class attribute).
    kind derives from exit/agent: exit='human' → a human-gate stage; agent=False → a pure
    script-gate stage; otherwise an agent stage (which may still carry a trailing gate).
    parts = the executor-combination declaration (an ordered subset of PART_KINDS):
    display metadata only — the engine's plumbing (result-file polling /
    prepare_human_gate's mechanical preparation / a no-op settle) doesn't count, while
    scripts required to land business output do (implement's worker settle, merge's
    booking + lane teardown)."""

    id: str
    name: str
    role: str                                  # the five roles (ticket t260822-m10): developer/integration/ops/product-operation/artist
    desc: str = ""
    acceptance: Tuple[str, ...] = ()
    next: str = ""                             # for display/snapshot; the driver follows the STAGES order
    exit: str = ""                             # 'human' = a human-gate stage (signal + wait_condition)
    fanout: int = 0                            # the review-type fan-out declaration (kept from yaml, currently 1)
    revision_to: str = ""                      # the rework default fallback target (the old content-pipeline revision loop, retired 260904)
    agent: bool = True                         # False = a pure script-gate stage (no agent activity, only the gate runs)
    gate: Optional[GateSpec] = None            # trailing gate: must run green after this stage's output lands before advancing
    parts: Tuple[str, ...] = ()                # the executor combination (a subset of PART_KINDS); empty = undeclared (the UI soft-degrades to 「—」)

    @property
    def kind(self) -> str:
        if self.exit == "human":
            return "human"
        if not self.agent:
            return "gate"
        return "agent"


@dataclass
class TicketInput:
    """The v2 workflow input: every business attribute is pinned at creation
    (deterministic); the stage chain lives in subclass code and never enters the
    input."""

    ticket_id: str
    template_id: str
    project: str = ""                            # the project key (the machine-level per-key registry ~/.sandbar/projects/<key>/project.yaml); empty = illegal, blocked at the ticket-start entry
    epic: str = ""                               # the epic code (notes/epics/<code>.md must exist); empty = not tied to an epic
    title: str = ""
    lane: str = ""
    workspace: Optional[Dict[str, str]] = None   # {type: worktree|dir, path} | None
    # Ticket t260908-02 (proven by t260907-13): the per-repo details of a multi-repo /
    # mixed-shape lane are promoted to a first-class field (an explicit shape).
    # Previously derive_lane_workspace embedded a list[dict] into the workspace value,
    # which conflicts with the Dict[str, str] annotation → a TypeError decoding the
    # Temporal dataclass payload (worker log "Failed converting field workspace") and a
    # failed workflow start. The field has a default = existing RUNNING instances replay
    # with the key missing and fall back, without breaking replay.
    repo_worktrees: List[Dict[str, str]] = field(default_factory=list)
    # Ticket t260910-08: the project's registered root directory (the same source
    # client.py's ticket-start derives from, proj["dirs"][0]). Carried into
    # meta.project_root so the workflow's WorkspacePrep can feed prepare_workspace's
    # fallback ring ③ (write_set + project_root → per-repo derivation) — without it
    # the ring is dead and a multi-repo ticket silently materializes single-repo
    # (the dengzhufpv t260910-07 incident). Default empty = existing RUNNING
    # instances replay with the key missing and fall back, without breaking replay.
    project_root: str = ""
    worktree: str = ""
    branch: str = ""
    base_ref: str = ""
    proposal_id: str = ""
    book_path: str = ""
    write_set: List[str] = field(default_factory=list)
    # Ticket t260904-18 gate ① (知识库设计.md §1's ticket-reference iron rule, host order
    # 260904): the list of background files the ticket references (repo-relative paths) —
    # the creation entry's validate_background_refs has already verified 「committed and
    # clean (the HEAD state)」, and they are carried here verbatim as part of the ticket
    # record; the default empty = old tickets are not retroactively covered.
    refs: List[str] = field(default_factory=list)
    # Ticket t260829-07's write-set lifecycle: the ticket creation explicitly declares
    # 「this ticket changes no files」 (only allow_empty_write_set can set it true) — the
    # mechanical re-check gate then skips the 「lane has 0 commits」 test.
    no_file_changes: bool = False
    acceptance_extra: List[str] = field(default_factory=list)  # A5.5: per-instance additions (appended to the first stage's checklist)
    deliverables: str = ""
    # Body = the original user request (ticket t260822-m16: user_request kept verbatim,
    # taking precedence when present; the default falls back to body);
    # spec = the processed dispatch specification (a separate field, never overwriting
    # the body).
    user_request: str = ""
    spec: str = ""
    body: str = ""
    created: int = 0
    gate_overrides: Dict[str, GateSpec] = field(default_factory=dict)  # gate replacement for self-tests (always empty in production)
    # t260911-03 阶段路径闸/受保护路径闸的总开关：随派单输入钉死（replay 稳定的判别锚）
    # ——老在途票的已记录输入无此字段 → getattr 缺省 False，永久关闸（patch 门保护，
    # 不追溯）；新 dev-lane 票由 dispatch 入口置 True（见 client.py ticket-start）。
    path_gate: bool = False
    # KI-124（t260925-23）：段路径闸的本票模板规则表——建票时自模板类 PATH_GATE_RULES
    # 声明钉死（client.py ticket-start 读类属性，replay 稳定；键=段 id，值=允许面 kind
    # 串或 {"kind":…, "prefixes":…}）。缺省空表=老在途票/不声明模板回落内建
    # STAGE_PATH_RULES，零行为变化。声明面合法性（键 ⊆ STAGES ids、kind ∈ 弱面白名单）
    # 由加载口深检把守（project_templates），此处只透传不校验。
    path_gate_rules: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StageResult:
    """An agent stage's result (= the in-memory form of the workspace result file; the
    format is exactly {status,summary,report,deliverables,files_changed,evidence}).

    Three layers: summary = the console's one-liner (lists / handover timelines); report
    = a human-readable markdown progress report (detail cards / handover injection /
    bounce injection); evidence = machine-stance raw evidence (collapsed by default)."""

    status: str = "ok"                         # ok | failed
    summary: str = ""
    report: str = ""
    deliverables: List[str] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    # Ticket t260904-18, KI-049 gate ②: files_changed's original shape (the parsing layer
    # preserves the shape; the consumer decides the emptiness policy). Three states:
    # absent = the receipt has no such field (compat with old tickets/receipts);
    # ok = list[str]; malformed = the field is present but not a list of strings (the
    # parsing layer rejects the shape-destroying form so consumers can visibly go red,
    # ruling out 「a string iterated character-by-character into a fake list of single
    # chars」 bypassing the new gate). Has a default: old RUNNING instances replaying
    # historical events without this field don't break.
    files_changed_shape: str = "absent"
    evidence: str = ""
    # t260915-01 ②：闸拒绝的结构化明细（path_gates.gate_red_detail 产出，经
    # _apply_settle_note 挂载）。None = 非闸拒绝/老回执（缺省值保证在途实例重放
    # 历史事件不破，演进安全惯例）；消费侧必经 sanitize_gate_refusal 校形。
    gate_refusal: Optional[Dict[str, Any]] = None
    # t260917-08：段回执的环境信号位（一等形式，与产品红/测试红/实现缺位正交）。
    # env_fail=True = 「验证未运行，原因是 agent 执行面环境受限」（如 bash 沙箱
    # fail-closed，KI-083），**不是**交付失败、不翻转任何红绿判定；它只改变
    # 「谁来跑验证」（移交命令由后续机械段 worker 执行面承接）与真因可见性。
    # 命名互指（同名异型防混读）：IntegrationRunResult.env_fail 是 **int 计数**
    # （t260904-12 场景环境红维度，入闸口径）；本字段是 **bool 位**（段回执层，
    # 不入闸口径）。缺省 False/""/[] = 老回执重放安全（gate_refusal 先例）。
    env_fail: bool = False
    env_reason: str = ""                       # 缺什么（原文摘录）；环境红必须点名缺什么（失败分类协议纪律）
    # 交接运行清单（normalize_handover_runs 校形后的有效命令）：agent 执行面受限期间
    # 没能亲自跑的验证，由后续机械段（dev-lane=run_integration_tests）的 worker
    # 执行面承接执行；无机械段的模板=移交命令留债票面（meta['env_handover_pending']）
    # 人审处置。条目={name,cmd}；畸形条目进 handover_dropped 逐条记名，不静默丢。
    handover_runs: List[Dict[str, str]] = field(default_factory=list)
    # 被 normalize 丢弃/截断的条目名单（透明面：dropped 摘要进票面注记/活动日志/
    # 仲裁上下文，「不静默丢」三处可查——review M4）。
    handover_dropped: List[str] = field(default_factory=list)
    # t260921-04（宿主令 260921「developer 段单测可跑、集成禁跑」）：执法扫描命中
    # 清单（每条 {cmd,entry,segment,seq}）——worker 执行面扫 agent 会话流水的
    # tool/call 执行帧得出，命中=段红+票面点名。缺省 [] = 老回执重放安全
    # （gate_refusal/env_fail 先例）。
    integration_violations: List[Dict[str, str]] = field(default_factory=list)
    # 扫描未覆盖/异常的响亮注记（零静默；**不翻红绿**——K2 观察项：同票同角色续
    # 同会话使「多回合 note」常驻，属说明性信号非失败信号）。缺省 "" 同上。
    integration_scan_note: str = ""
    # t260924-09（KI-117 走查/仲裁段取证面瘦身）：取证面护栏命中清单（每条
    # {cmd,kind,detail,cmd_index,seq}）——worker 执行面扫 integration 角色 agent 段
    # 会话流水得出：定点复跑豁免；口径漂移/口径含非法 token/全量超上限（每段
    # 非定点全套 ≤1 趟）=段红+票面点名。缺省 [] = 老回执重放安全。
    full_suite_violations: List[Dict[str, str]] = field(default_factory=list)


# handover_runs 的形状上限（t260917-08：防御面非功能面——条数/长度上限在 normalize
# 单点收紧，防超长清单拖垮机械段执行与票面）。
HANDOVER_MAX_LEGS = 20
HANDOVER_CMD_MAX = 500
HANDOVER_NAME_MAX = 120


def normalize_handover_runs(raw: Any):
    """交接运行清单的形状保持规范化（t260917-08；镜像 normalize_files_changed 的
    三态纪律，KI-049 gate ②同源教训）。

    Returns (legs, shape, dropped):
      - raw is None → ([], "absent", [])：老回执无此键（按无交接处理）；
      - raw 是列表 → 逐条校验：条目须为 dict 且 name/cmd 为非空 str；name 超
        HANDOVER_NAME_MAX 截断保留（名字无害），cmd 超 HANDOVER_CMD_MAX **整条
        丢弃记名**（半条命令可能误执行——fail-closed，绝不截断执行）；条数超
        HANDOVER_MAX_LEGS 的尾部记名丢弃。有合法条目，或空列表（显式「无可交接」）
        → shape="ok"（丢弃面进 dropped 名单）；列表在但条目无一合法 → "malformed"；
      - 其它类型（字符串/数字/dict）→ ([], "malformed", ["handover_runs 非列表"])。

    「不静默丢」落面：dropped 名单由解析点存进 StageResult.handover_dropped，
    经 env_note_for 进票面注记/活动日志/仲裁上下文。空列表形状合法；空清单的语义
    裁定（env_fail=true 且有效命令 0 = 未验证且无移交命令，不得当已验证）在
    env_note_for（R4 语义层），不在本函数沉默跳过。"""
    if raw is None:
        return [], "absent", []
    if not isinstance(raw, list):
        return [], "malformed", ["handover_runs 非列表"]
    legs: List[Dict[str, str]] = []
    dropped: List[str] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            dropped.append("条目%d:非对象" % i)
            continue
        name = item.get("name")
        cmd = item.get("cmd")
        if not isinstance(name, str) or not name.strip() \
                or not isinstance(cmd, str) or not cmd.strip():
            dropped.append("条目%d:name/cmd 缺失或非字符串" % i)
            continue
        if len(cmd) > HANDOVER_CMD_MAX:
            dropped.append("条目%d:cmd 超 %d 字符整条丢弃（不截断执行）"
                           % (i, HANDOVER_CMD_MAX))
            continue
        if len(name) > HANDOVER_NAME_MAX:
            dropped.append("条目%d:name 超 %d 字符截断保留" % (i, HANDOVER_NAME_MAX))
            name = name[:HANDOVER_NAME_MAX]
        if len(legs) >= HANDOVER_MAX_LEGS:
            dropped.append("条目%d:超上限 %d 条丢弃" % (i, HANDOVER_MAX_LEGS))
            continue
        legs.append({"name": name.strip(), "cmd": cmd.strip()})
    # 形状判定：空列表=合法形状（agent 显式声明「无可交接」，与缺键 absent 相区分；
    # 「空清单当不当已验证」的语义裁定在 env_note_for——R4 语义层，不在本函数沉默
    # 跳过也不误标 malformed）；列表在但条目全非法 → "malformed"（丢弃面进 dropped）。
    return legs, ("ok" if (legs or not dropped) else "malformed"), dropped


def agent_env_failed_reason(res: Any) -> str:
    """agent 段回执的环境型失败 → blocked 票面文案（t260917-08 要求②）。

    仅 status=failed 且 env_fail=True 时返回单行文案：点名「agent 沙箱不可用
    （环境）」+ env_reason 摘要 + 后续出路（验证交由后续段 worker 执行面承接、
    票不停摆）。其余形态（ok+env_fail / failed 无 env 信号 / 畸形对象）返回 ""
    ——调用方回落既有「agent 报失败：」文案（零改动）。畸形不抛（getattr 防御，
    纯函数，UT 直调）。与闸拒专道的优先级：gate_refusal/lane_dsh/仲裁闸拒路径
    的回执不挂 env 日志扫描（activity 侧 M1 裁定），env_fail 恒 False，结构上
    无竞争——env 文案永不遮更具体的真因。"""
    if not getattr(res, "env_fail", False):
        return ""
    if str(getattr(res, "status", "")) != "failed":
        return ""
    reason = str(getattr(res, "env_reason", "") or "").replace("\n", " ")[:160]
    return ("agent 沙箱不可用（环境）：%s。该段验证未运行，非实现缺位；"
            "验证交由后续段 worker 执行面承接（移交命令），票不停摆。"
            "出路：retry_qc 重跑 / rework 打回 / 修复执行面（容器形态）"
            % (reason or "原因未声明"))


def env_note_for(res: Any) -> str:
    """段回执的环境注记单源（t260917-08 R4/M4）：票面 results[step]['env_note']、
    活动日志、仲裁/走查上下文三处共用此措辞，防各处漂移。

    - 非 env_fail → ""（零注记，零回归）；
    - env_fail 且有效移交命令 >0 → 「环境受限未验证；移交 N 条命令待执行：<前 3 名>」；
    - env_fail 且有效命令 =0 → 「环境受限未验证且无移交命令（不当作已验证）」+ 弃单
      摘要（R4 fail-closed：空清单不许把「未验证」洗成合规；仲裁契约要求 verdict
      必须处置）。"""
    if not getattr(res, "env_fail", False):
        return ""
    legs = getattr(res, "handover_runs", None) or []
    dropped = getattr(res, "handover_dropped", None) or []
    if legs:
        names = [str(l.get("name") or "") for l in legs[:3]]
        more = "等" if len(legs) > 3 else ""
        return "环境受限未验证；移交 %d 条命令待执行：%s%s" % (len(legs), "、".join(names), more)
    note = "环境受限未验证且无移交命令（不当作已验证）"
    if dropped:
        note += "；弃 %d 条：%s" % (len(dropped), "; ".join(dropped[:2]))
    return note


def normalize_files_changed(raw: Any):
    """Shape-preserving normalization of the create_plan receipt's files_changed (pure
    function, ticket t260904-18 KI-049 gate ②).

    Returns (files, shape): shape ∈ "absent" | "ok" | "malformed".
      - raw is None → ([], "absent"): the receipt has no field (old-ticket fallback; the
        consumer applies skip semantics);
      - raw is a list of all strings → (the stripped, emptied-out list, "ok"): the
        emptiness (is it an empty array) policy belongs to the consumer (empty arrays are
        legal in stages such as design_integration_tests);
      - anything else (a string / number / dict / a list with non-string elements) →
        ([], "malformed"): **reject the shape-destroying form, never clean it** — the old
        `[str(x) for x in raw]` would iterate the string "server/foo.py"
        character-by-character into a fake list of single chars, silently bypassing the
        gate and polluting the write set.

    All three parsing points (agent_activities._read_result / base / dev_lane's activity
    reply normalization) go through this function, replacing the old shape-destroying
    coercion."""
    if raw is None:
        return [], "absent"
    if not isinstance(raw, list):
        return [], "malformed"
    if any(not isinstance(x, str) for x in raw):
        return [], "malformed"
    return [x.strip() for x in raw if x.strip()], "ok"


@dataclass
class ReworkRequest:
    """The rework signal payload: go back to a target stage and re-run. An empty
    target_stage = the default (the current stage's revision_to, or the previous
    stage)."""

    who: str
    target_stage: str = ""
    note: str = ""
    # t260915-12 跨项目闸盖章（同 Signature 家族契约；带默认=重放安全）。
    caller_project: str = ""
    cross_project_note: str = ""


@dataclass
class HostRulingRequest:
    """The host_ruling signal payload (KI-053): the formal injection channel for the
    host's human opinion, sendable in any state (including blocked). Both who and note
    are required and non-empty — empty / pure whitespace is refused by the workflow side
    into refused; a note over HOST_RULING_NOTE_INPUT_LIMIT is refused the same way (an
    intake gate, so oversized payloads never enter the event history)."""

    who: str
    note: str
    # t260915-12 跨项目闸盖章（同 Signature 家族契约；带默认=重放安全）。
    caller_project: str = ""
    cross_project_note: str = ""


# ---- Ticket pause（工单 t260908-01，设计基准=notes/epics/ticket-pause.md）----
# pause/resume 与 sign/rework/ruling 同族：只从 client.py CLI 信号通道进，agent
# prompt/activities 无发送入口。粒度=段间暂停（当前段含在飞 activity 自然跑完，
# workflow 停在段间门口等 resume）。机制真源=base.py 的 TicketPauseMixin。
PAUSE_PATCH_ID = "ticket-pause-v1"
# note 上限与 HOST_RULING_NOTE_INPUT_LIMIT 同值同源（intake gate：超限拒收、不进
# 事件历史），但独立常量——两机制未来取值可能各自演进，不互相绑死。
PAUSE_NOTE_INPUT_LIMIT = 20000

# 测试台桩旋钮族（t260908-01）：这些 env 只应由测试线束设置（桩大脑/桩截图/夹具
# 模板门/桩段时长）。机械闸（merge_check 的泳道内 verify_lane）与被测契约 UT 的
# 子进程必须剥除它们——否则桩旋钮随 worker env 漏进被测进程，把真实行为换成桩
# 行为造成假红。
# 生产 worker 从不设置它们，剥除对生产是恒等操作。
TEST_STUB_ENV_KNOBS = ("SANDBAR_AGENT_STUB", "SANDBAR_AGENT_STUB_FILES",
                       "SANDBAR_AGENT_STUB_DELAY_SEC",
                       "SANDBAR_UI_CAPTURE_STUB", "SANDBAR_FIXTURE_TEMPLATES",
                       # t260917-08：桩回执的环境信号注入旋钮（env_fail/env_reason/
                       # handover 清单 JSON 文件路径）——同族纪律：随机械闸与被测
                       # 子进程剥除，桩行为不得漏进被测进程换假行为。
                       "SANDBAR_AGENT_STUB_ENV_FAIL", "SANDBAR_AGENT_STUB_ENV_REASON",
                       "SANDBAR_AGENT_STUB_HANDOVER")

# worker 路由旋钮族（t260908-01 r10 实证追加）：这些 env 指挥 worker 进程自身
# （poll 哪些队列/watch 哪张票/退出口径），verify_lane 的 pytest 子进程不是
# worker——漏进去会让 worker 配置 UT 读到测试台值假红（SANDBAR_WATCH_INTERVAL_SEC
# 漏进 watch_interval_sec 缺省断言实证）。merge_check 的泳道内 verify_lane 调用点
# 与 TEST_STUB_ENV_KNOBS 一并剥除；对「恰好在跑 verify 的 worker 自身」无影响
# （剥的是子进程 env，不是本进程）。
WORKER_ROUTING_ENV_KNOBS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES",
                            "SANDBAR_WATCH_WORKFLOW", "SANDBAR_WATCH_INTERVAL_SEC")


@dataclass
class PauseRequest:
    """The pause / resume signal payload（工单 t260908-01）。who=操作人（身份注入，
    与 Signature 同一份代签纪律——agent 不得以自己角色名发起）；note=可选理由
    （intake gate：who 空/纯空白拒收、note 超 PAUSE_NOTE_INPUT_LIMIT 拒收，均落
    refused 不进事件历史，host_ruling 同款双形态）。"""

    who: str
    note: str = ""
    # t260915-12 跨项目闸盖章（同 Signature 家族契约；带默认=重放安全）。
    caller_project: str = ""
    cross_project_note: str = ""


@dataclass
class AgentStageArgs:
    """Inputs of an agent-stage activity (the activity name = the stage name; the
    implementation is generic, dispatching per stage)."""

    ticket_id: str
    stage_id: str
    role: str
    prompt: str                                # the dispatch prompt (assembled by a pure function on the workflow side, deterministic)
    workspace: Optional[Dict[str, str]] = None
    result_file: str = ""                      # the idempotence anchor: if it exists, read it directly (safe to re-run)
    log_file: str = ""
    gen: int = 0                               # how many times this stage has been entered (a rework re-run gets a fresh result file)
    max_polls: int = 0                         # 0 = default (the activity-side constant)
    # t260910-14 退役注记：epic/state_key 曾专属「预跑下一单」段（已整链退役）；字段
    # 保留为恒空默认——老 history 事件反序列化仍带这两键，删字段会让旧票重放
    # TypeError（解码安全优先于字段洁癖）。
    epic: str = ""                             # retired (t260910-14): kept for old-event decoding, always empty
    state_key: str = ""                        # retired (t260910-14): kept for old-event decoding, always empty
    workflow_id: str = ""                      # the template id (used to look up STAGE_DISPATCH_KIND for specialization-level model routing)
    previous_context: str = ""                 # the previous run's context (inherited from the workflow history when the same stage re-runs)
    # Ticket t260829-07: during the parallel fork both implement and design skip the
    # trailing settle (so neither settles the other's half-finished work); the unified
    # settle is handled by the settle_lane activity at the join point.
    skip_settle: bool = False
    # t260911-03 路径闸四件（defaulted——老序列化事件缺字段→默认值，skip_settle 先例；
    # path_gate 只有新票输入（TicketInput.path_gate）钉死后才会 True，老在途票不追溯）：
    write_set: List[str] = field(default_factory=list)   # 段允许面：implement/integ_join 的写集
    ui_dirs: List[str] = field(default_factory=list)     # 段允许面：ui_evidence 的 verify.yaml ui_evidence.dirs
    base_ref: str = ""                                   # 泳道分叉点（受保护闸「存在才拦」的锚，非 HEAD）
    path_gate: bool = False                              # 闸总开关
    # KI-124：本票模板段规则表（TicketInput.path_gate_rules 透传，defaulted 空表=
    # 老事件 replay 不破；空表回落内建 STAGE_PATH_RULES，语义不变）。
    path_gate_rules: Dict[str, Any] = field(default_factory=dict)
    # t260912-03 人授权结构化记录（defaulted 空表——老事件 replay 缺字段→[]，零回归）：
    # workflow 侧已按「kind=protected_path + 本票 + expires>workflow.now()」过滤；
    # activity 侧只据此做受保护闸的豁免摘除与记名，不读墙钟（重放/复跑判定不吃时钟）。
    authorizations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HumanGatePrep:
    """Inputs/receipt of the human-gate mechanical preparation activity: assembles the
    review context (diff / proposal excerpt / previous stage's deliverables)."""

    ticket_id: str
    stage_id: str
    proposal_id: str = ""
    workspace: Optional[Dict[str, str]] = None
    worktree: str = ""
    base_ref: str = ""
    title: str = ""


@dataclass
class HumanGateContext:
    ok: bool = True
    context_text: str = ""                     # the mechanical context shown to the signer (rendered into the snapshot)
    note: str = ""


@dataclass
class WorkspacePrep:
    """Inputs of the workspace preparation activity (M16: the workspace is created by the
    workflow's first activity, the agent no longer does it itself)."""

    ticket_id: str
    workspace: Optional[Dict[str, str]] = None  # {type: worktree|dir, path} | None (main tree = None)
    branch: str = ""                            # the worktree lane's new branch name (registered at create)
    base_ref: str = ""                          # the base point (the main-tree HEAD at create; empty = the default HEAD)
    # Ticket t260907-06 multi-repo channel: when write_set + project_root are present and
    # the project root has no .git (a multi-repo project with the parent directory as
    # root) → prepare derives repo_worktrees from write-set ownership (the meta source of
    # truth is the creation chain's derive_lane_workspace; prepare verifies the disk
    # against what the source of truth derived). Defaulted fields = existing RUNNING
    # instances replay with the key missing and fall back, without breaking replay. For a
    # single-repo project both fields are ignored (zero regression).
    write_set: List[str] = field(default_factory=list)
    project_root: str = ""
    # Ticket t260908-02: the per-repo details are promoted to a first-class field, the
    # same way as TicketInput.repo_worktrees — the second hop (workflow → activity)
    # previously also stuffed a workspace containing a list into a Dict[str, str]
    # annotation, and Temporal's codec would blow up a second time on the activity side.
    # Defaulted = replay-safe.
    repo_worktrees: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class WorkspacePrepResult:
    """The workspace preparation receipt (failure does not raise — the receipt goes back
    to the workflow to turn blocked and wait for retry_qc / rework triage)."""

    ok: bool = True
    kind: str = ""        # worktree | dir | main (the main tree / no separate space)
    action: str = ""      # created | reused | ensured | skipped | failed
    path: str = ""
    error: str = ""       # the reason on failed (e.g. the directory exists but is not a worktree of this repo)


def build_workspace_prep(ticket_id: str, meta: Dict[str, Any]) -> "WorkspacePrep":
    """Single construction point of WorkspacePrep from ticket meta (ticket t260910-08).

    The t260910-07 incident's root cause was exactly this construction being
    duplicated (dev_lane.run / base._prepare_workspace): the dev_lane copy was
    silently starved — meta.repo_worktrees was never carried by _init and
    write_set/project_root were never fed, so prepare_workspace's three read rings
    (① prep.repo_worktrees ② ws["repo_worktrees"] ③ write_set+project_root
    derivation) were all empty and every multi-repo ticket materialized as a
    single-repo lane. Collapsing both call sites onto this one function makes the
    three feeds structurally un-droppable, and the binding-anchor UT
    (test_t260910_08_lane_materialization.py::test_workspace_prep_construction_is_single_point)
    reds the moment either workflow family inlines WorkspacePrep(...) again.

    meta is the workflow's ticket ledger dict (all reads defensive with defaults —
    replay of old RUNNING instances may lack any of the newer keys)."""
    return WorkspacePrep(
        ticket_id=ticket_id,
        workspace=meta.get("workspace"),
        repo_worktrees=list(meta.get("repo_worktrees") or []),
        branch=str(meta.get("branch") or ""),
        base_ref=str(meta.get("base_ref") or ""),
        write_set=list(meta.get("write_set") or []),
        project_root=str(meta.get("project_root") or ""))


@dataclass
class MergeCheckArgs:
    """Inputs of the merge_check activity (dev-lane: the programmatic pre-merge checks,
    no agent).

    It adds exactly the check ticket t260824-01 was missing: on that ticket the agent
    never committed, the verify gate ran against the main tree (the changes were in the
    worktree, the main-tree diff was empty → the whitelist check was a no-op) and
    everything went green in a fake closed loop. So this activity hard-requires: the lane
    has commits, the workspace is clean, and verify runs inside the lane."""

    ticket_id: str
    worktree: str = ""                        # the lane worktree path (repo-relative or absolute)
    branch: str = ""                          # the lane branch name
    base_ref: str = ""                        # the base point (the main-tree HEAD at create)
    # Ticket t260828-09's UI evidence gate: the ticket's write set carried in verbatim
    # (the dev_lane call site passes meta["write_set"]); defaulted — old RUNNING
    # instances replaying historical events have no such field, so replay doesn't break.
    write_set: List[str] = field(default_factory=list)
    # t260911-03 路径闸：merge_check 的 KI-009 自愈 settle 同受闸（defaulted，老事件
    # 缺字段→False=不自愈受闸、行为与旧版一致）；base_ref/write_set 复用上两字段。
    path_gate: bool = False
    # KI-124：本票模板段规则表（defaulted 空表=老事件 replay 不破；空表回落内建表）。
    path_gate_rules: Dict[str, Any] = field(default_factory=dict)
    # t260912-03 人授权结构化记录（defaulted 空表，零回归）：自愈 settle 的受保护闸
    # 豁免面与 workflow 侧一致（workflow 已按票+时效过滤）。
    authorizations: List[Dict[str, Any]] = field(default_factory=list)
    # t260921-09 三态判据（实证 nusuyou t260920-04：多仓票某仓声明在写集但本票零改动，
    # 被逐仓「泳道分支有 commit」必判红，票在最后一道机械门前无正当出路）：建票声明
    # 「本票无文件改动」（allow_empty_write_set → meta.no_file_changes）时豁免整票零
    # commit 全局闸——与 review_gate_verdict 的豁免口径同源。defaulted False=老事件
    # 回放不破（同 path_gate t260911-03 先例）。
    no_file_changes: bool = False


# ---- Ticket t260828-09: the UI acceptance machinery (the screenshot channel + look-at-the-image review + merge_check's evidence gate) ----

# The UI file stance (**the compatibility fallback data source** after ticket t260904-18's
# KI-050 declaration regime, no longer the live path's source of truth):
#   live paths (merge_check 3.6 / ui_changed_paths / the review_gate patched branch) all
#   consume the project declaration (verify.yaml ui_evidence.dirs, loaded by
#   load_ui_evidence); this constant serves only the prefixes=None replay of old tickets
#   and the frozen/unpatched branch fallback (required for replay determinism). Widening
#   or narrowing it no longer happens here — change sandbar's verify.yaml declaration.
# Physical retirement follows the stock of RUNNING instances reaching zero.
UI_WRITE_PREFIXES = (
    "server/plugins/workbench/src/client/",
    "server/plugins/workbench/lib/",
    "server/plugins/providers/src/client/",
    "app/src/",
    "app/index.html",
)


# The screenshot evidence directory (new lanes default to .sandbar/screenshots; old
# lanes are resolved back to the old name by ui_evidence_dir()'s sticky resolution —
# capture.mjs's --out and merge_check's gate both go through the helper's one
# resolution rather than each judging the directory name).
# This constant is for default display text and fixtures only.
UI_EVIDENCE_DIR = DOT_DIR_NEW + "/screenshots"


def ui_evidence_dir(worktree) -> pathlib.Path:
    """The lane's screenshot directory (sticky resolution:
    resolve_dot_dir(worktree)/screenshots)."""
    return lane_dot_path(worktree, "screenshots")

# The screenshot evidence archive directory (relative to the main tree REPO_ROOT; after
# prepare_ui_evidence succeeds it copies the lane's screenshots in here: the main tree's
# coordination directory, sticky resolution, /evidence). After a lane merges its tree is
# torn down, and this archive is what keeps the images referenced in a report from
# becoming dead links; the host's read-only endpoint, node.ts's evidence route, reads it
# with the same stance — the node-side SANDBAR_EVIDENCE_DIR env override (= the archive
# base directory itself, pointed at a temp dir by self-tests) and
# agent_activities._archive_shots reference the same env name: change one side, sync the
# other)
EVIDENCE_DIR = DOT_DIR_NEW + "/evidence"


def evidence_base(repo_root=None) -> pathlib.Path:
    """The main tree's archive base directory (the env override wins; otherwise the main
    tree's coordination directory resolved stickily, /evidence)."""
    env = os.environ.get("SANDBAR_EVIDENCE_DIR")
    if env:
        return pathlib.Path(env)
    return lane_dot_path(repo_root or REPO_ROOT, "evidence")


def match_ui_paths(paths: Any, prefixes: Any = None) -> List[str]:
    """A path list × the UI stance's prefix table → the UI paths that hit (order
    preserved, deduped; pure function, no IO).

    The single predicate entry of KI-044's root fix (ticket t260904-13): UI-ticket
    detection consumes the **actual diff paths** (the output of
    git diff --name-only <merge-base>...branch × this function), not the declared write
    set — a declared stance ≠ the real write surface, and the coarser the granularity the
    weaker the gate (declaring a whole parent directory bypasses it).

    KI-050's declaration regime (ticket t260904-18): the prefix table now comes from the
    **project declaration** (verify.yaml ui_evidence.dirs); prefixes=None (the default)
    falls back to the module-level UI_WRITE_PREFIXES, **only as the compatibility
    fallback data source for old-ticket replay and frozen/unpatched branches** — live
    paths always pass the declaration explicitly, and new call sites may not be written
    in the single-argument form.

    Tolerance: a non-list/tuple, None, or an empty set → an empty list; elements are
    stripped at both ends; non-string elements are ignored; paths are compared by
    repo-relative prefix."""
    if prefixes is None:
        prefixes = UI_WRITE_PREFIXES
    if not paths or not isinstance(paths, (list, tuple)):
        return []
    hits: List[str] = []
    for w in paths:
        if not isinstance(w, str):
            continue
        p = w.strip()
        for pref in prefixes:
            if p == pref.rstrip("/") or p.startswith(pref):
                if p not in hits:
                    hits.append(p)
                break
    return hits


def is_ui_write_set(write_set: Any, prefixes: Any = None) -> bool:
    """A write set that hits the UI stance means a UI ticket (pure function, no IO) —
    delegated to match_ui_paths as the single maintained point.

    After KI-044 (ticket t260904-13) this function has only two legitimate call surfaces:
    review_gate's mechanical re-check (dev_lane, the declaration-stance semantics) and
    the old chain tail's frozen branch (compat with replaying existing instances); the
    main UI-ticket detection path has switched to the diff source (the ui_changed_paths
    activity and merge_check 3.6 share agent_activities._ui_diff_paths), so never
    introduce this function into a new judgement path.
    KI-050's declaration regime (ticket t260904-18): prefixes means the same as in
    match_ui_paths — the review_gate patched branch passes the project's declaration list
    explicitly; None is only for the old branch's fallback compatibility data source."""
    return bool(match_ui_paths(write_set, prefixes))


def load_ui_evidence(root: Any):
    """Read the ui_evidence declaration from the project root's verify.yaml (KI-050's
    declaration regime, ticket t260904-18).

    Returns (dirs, note, mode), three states:
      - ("ok", dirs, ""): the declaration is present and legally shaped;
      - ("absent", [], "…note…"): verify.yaml is missing or has no ui_evidence key —
        treated as disabled per the project declaration: the screenshot evidence item is
        green + a visible note (not a SKIP, not a fake green), and the caller assembles
        the item;
      - ("malformed", [], "…err…"): the declaration is present but illegally shaped —
        a fail-closed red, and the caller names err (malformed ≠ absent).

    This is a disk-reading function: call it only from the activity/CLI side (the
    agent_activities / verify_lane family), never inside a workflow (the workflow side
    consumes the meta preload). This function only recognizes the minimal subset of a
    top-level `ui_evidence:` block plus a `dirs:` list of two-space-indented `- ` items
    and touches no other block (verify_lane is the source of truth for loading and
    structurally validating the lane, and the two sides' whitelists were synced in the
    same ticket). A missing/unreadable root is treated as absent (a lane root with no
    verify.yaml is a legal declaration state)."""
    try:
        base = pathlib.Path(root)
        text = (base / "verify.yaml").read_text("utf-8")
    except Exception:
        return "absent", [], "verify.yaml 不可读（声明缺省态）"
    lines = text.replace("\t", "  ").splitlines()
    in_block = False
    in_dirs = False
    saw_block = False
    dirs: List[str] = []
    saw_dirs = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            in_block = stripped == "ui_evidence:"
            in_dirs = False
            if in_block:
                saw_block = True
            if stripped.startswith("ui_evidence:") and stripped != "ui_evidence:":
                # An inline value (e.g. `ui_evidence: foo`) = a non-mapping declaration, the malformed state
                return "malformed", [], ("ui_evidence 须为映射（实际行内标量 %r）"
                                         % stripped.split(":", 1)[1].strip())
            continue
        if not in_block:
            continue
        if stripped.startswith("dirs:") or stripped == "dirs:":
            in_dirs = True
            saw_dirs = True
            inline = stripped.split(":", 1)[1].strip()
            if inline:
                if inline.startswith("[") and inline.endswith("]"):
                    inner = inline[1:-1].strip()
                    dirs = [t.strip().strip("\"'") for t in inner.split(",") if t.strip()]
                    return "ok", dirs, ""
                return "malformed", [], "ui_evidence.dirs 须为列表（实际 %r）" % inline
            continue
        if stripped.startswith("- ") and in_dirs and indent >= 2:
            item = stripped[2:].strip().strip("\"'")
            if not item:
                return "malformed", [], "ui_evidence.dirs 含空条目"
            dirs.append(item)
            continue
        # Other keys inside the block (supply etc.): this engine version doesn't consume
        # them, skip; but deeper-indented orphan lines (neither in the dirs list nor
        # deeper than the block header without being a key-value line) are treated as
        # malformed
        if ":" not in stripped and not stripped.startswith("- "):
            return "malformed", [], "ui_evidence 块含无法解析的行: %s" % stripped
        in_dirs = False
    if not saw_block:
        # No ui_evidence key in the file = the declaration-absent state, not malformed
        return "absent", [], "verify.yaml 无 ui_evidence 声明（截图证据项按项目声明缺席）"
    if not saw_dirs:
        return "malformed", [], "ui_evidence 声明缺 dirs 列表"
    return "ok", dirs, ""


def validate_background_refs(refs: Any, project_root: Any):
    """The ticket-creation background-file gate (ticket t260904-18 gate ①;
    知识库设计.md §1's ticket-reference iron rule; the 260904 host order: 「an
    uncommitted note may not open a ticket」).

    Background files referenced by the ticket must be **committed and clean (the HEAD
    state)** — the lane reads the HEAD-frozen copy, so an agent cannot read a dirty,
    modified version. Two checks per file:
      ① `git ls-files --error-unmatch`: tracked = committed into a HEAD ancestor
         (untracked / nonexistent is refused — named as 「uncommitted」);
      ② `git status --porcelain -- <file>`: the output must be empty (any dirty state —
         staged / unstaged / type changed — is refused, named as 「carrying dirty
         changes」; a newly staged file in the `A ` state is caught by ② as well).

    Returns (ok, err): ok=True lets the ticket be created; err is the per-file refusal
    text (the error must be precise — which file, and why). refs None / an empty list →
    (True, "") (unchecked by default; in-flight tickets are not retroactively covered);
    a non-list refs → refused (a string would be iterated character-by-character into a
    fake list, the t260902-10 family precedent); an entry failing _valid_write_set_entry
    (absolute paths / ..) → refused.

    A disk-reading function: called only at the ticket-creation entry (client.py
    ticket-start, before _connect() — the refusal path does not depend on Temporal being
    reachable); never inside a workflow. git unavailable = refuse (fail-closed, never a
    silent pass)."""
    if refs is None or refs == []:
        return True, ""
    if not isinstance(refs, list):
        return False, ("refs 须为路径列表（实际 %s：%r——字符串会被逐字符迭代成假清单）"
                       % (type(refs).__name__, str(refs)[:80]))
    bad_shape = [r for r in refs if not _valid_write_set_entry(r)]
    if bad_shape:
        return False, ("背景文件引用含非法条目（须为仓库内相对路径；禁绝对路径、'..'、"
                       "'.' 整仓形态与通配哨兵 ?!*[]——t260915-04 与写集闸同口径）："
                       + "、".join(str(b) for b in bad_shape[:8]))
    problems = []
    for r in refs:
        rel = str(r).strip()
        try:
            p1 = subprocess.run(
                ["git", "-C", str(project_root), "ls-files", "--error-unmatch", "--", rel],
                capture_output=True, text=True, timeout=30)
            p2 = subprocess.run(
                ["git", "-C", str(project_root), "status", "--porcelain", "--", rel],
                capture_output=True, text=True, timeout=30)
        except Exception as e:
            return False, "背景文件校验失败（git 不可用，fail-closed）：%s: %s" % (
                type(e).__name__, e)
        if p1.returncode != 0:
            problems.append("%s（未提交：不在 HEAD 跟踪清单——先提交再建票）" % rel)
            continue
        dirty = (p2.stdout or "").strip()
        if p2.returncode != 0 or dirty:
            problems.append("%s（带未提交改动：%s——先提交再建票）" % (
                rel, dirty.replace("\n", "；")[:120] if dirty else "status 查询失败"))
    if problems:
        return False, ("工单引用的背景文件未过「已提交且干净」闸（KI-049 同源宿主令）："
                       + "；".join(problems))
    return True, ""


def _valid_write_set_entry(p: Any) -> bool:
    """Write-set entry legality (pure function): a repo-relative path — non-string /
    empty / absolute / containing '..' / a backslash path are all illegal (no boundary
    check, no disk access; the shape check is enough).

    t260915-04 口径统一（与运行期写集闸同立场，收「建票说合法、闸说不合法」漂移）：
      - '.' 形态（'./'/'.//' 归一后同形）非法——等于项目根=整仓；闸面本就事实性
        永不匹配（unauthorized_path），归属面曾归根仓透传（单仓/混合形态），两处
        口径在此对齐；
      - 含 git 通配哨兵字符 ?!*[] 的条目非法——镜像 path_gates._is_safe_path /
        agent_activities._dirty_within_write_set 对文件侧的既有哨兵立场：条目含
        哨兵=建票拒收；条目不含哨兵时，闸面对哨兵文件名本就 fail-closed 不认，
        故这是口径对齐不是新造分岔。文件名含哨兵的合法 POSIX 文件自此不可经写集
        授权（宿主 260915 口径：一律列举+哨兵不可写），记录防误摘。"""
    if not isinstance(p, str):
        return False
    s = p.strip()
    if not s or s.startswith("/") or s.startswith("\\") or "\\" in s:
        return False
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():  # a Windows drive letter C:/…
        return False
    if ".." in s.split("/"):
        return False
    if pathlib.PurePosixPath(s).as_posix() == ".":  # '.'/'./'/'.//' = 项目根（整仓）
        return False
    if any(ch in s for ch in "?!*[]"):  # git 通配哨兵，镜像 path_gates._is_safe_path
        return False
    return True


def validate_write_set_args(write_set: Any, allow_empty: bool):
    """Ticket-creation write-set validation (pure function, t260829-07 A1).

    Returns (ok, flags, err):
      ok           whether the ticket may be created
      flags        {"no_file_changes": bool} — set true on an empty write set with an
                   explicit declaration
      err          the refusal text (including both ways out); an empty string when
                   ok=True
    The stance: write_set None → treated as an empty set (a deliberate tolerance locked
    in by the existing selfcheck selfcheck_write_lifecycle and client.py's creation
    entry); a non-list write set (including a string — accepting it would let a for loop
    iterate it into a list of single chars and a fake guard, t260902-10) → refused; a
    non-empty write set → pass (each entry's shape is validated; illegal entries are
    refused directly on the client side — ticket creation is where the guard starts, so
    no silent cleaning); an empty set + allow_empty_write_set → pass and record
    no_file_changes; an empty set with no declaration → refuse."""
    if write_set is not None and not isinstance(write_set, list):
        return False, {}, ("写集须为列表（实际 %s）：字符串会被逐字符迭代成假护栏，"
                           "请传 [\"路径\", …] 或 None" % type(write_set).__name__)
    ws = [w.strip() for w in (write_set or []) if isinstance(w, str)]
    bad = [w for w in (write_set or []) if not _valid_write_set_entry(w)]
    if bad:
        return False, {}, ("写集含非法条目（须为仓库内相对路径；禁绝对路径、'..'、"
                           "'.' 整仓形态与通配哨兵 ?!*[]——t260915-04 与写集闸同口径）：%s"
                           % "、".join(str(b) for b in bad[:5]))
    if ws:
        return True, {"no_file_changes": False}, ""
    if allow_empty:
        return True, {"no_file_changes": True}, ""
    return False, {}, (
        "写集为空：agent 将没有白名单护栏、UI 票判定失效。两条出路："
        "① 传 write_set 列出本票预计改动文件清单；"
        "② 确实无文件改动时传 allow_empty_write_set=true 显式声明（meta 记 no_file_changes）。")


def refresh_write_set(initial: Any, plan_files: Any):
    """The write set follows the plan (pure function, ticket t260829-07).

    merged = the legal entries of initial ∪ plan_files (order preserved: initial first
    then additions, deduped after strip). **A union, not a replacement** (a deliberate
    deviation from 「refresh to the plan's list」): the initial write set is a human /
    suggestion prior, and a prior should not be washed away when the plan forgets to
    list it; the verify_lane whitelist is a cap on what is allowed, not a mandatory list,
    so extra files only leave extra headroom — no red light, not in the diff.
    Three-state stance:
      - illegal entries in plan_files (non-string / absolute / containing '..' /
        out-of-bounds shapes) are dropped into dropped — refuse the entry, not the run;
      - added = plan_files' legal entries − initial (the caller records an
        「authorization extension」 on the timeline);
      - initial goes through the same shape filter (validated at the creation entry; this
        is the backstop).
    """
    def _clean(seq):
        out, dropped = [], []
        for p in (seq or []):
            if not _valid_write_set_entry(p):
                if p is not None:
                    dropped.append(p if isinstance(p, str) else repr(p))
                continue
            s = p.strip()
            if s not in out:
                out.append(s)
        return out, dropped

    init, init_dropped = _clean(initial)
    plan, plan_dropped = _clean(plan_files)
    merged = list(init)
    added = []
    for p in plan:
        if p not in merged:
            merged.append(p)
            added.append(p)
    return merged, added, init_dropped + plan_dropped


@dataclass
class ReviewGateArgs:
    """Inputs of the verify_review_gate activity (t260829-07: mechanizing the review
    criteria, pure git/files with zero LLM)."""

    ticket_id: str
    worktree: str = ""                        # the lane worktree (git -C queries the lane's commit count)
    write_set: List[str] = field(default_factory=list)
    no_file_changes: bool = False             # the creation declared 「this ticket changes no files」 → skip the 0-commit gate


@dataclass
class ReviewGateResult:
    """The verify_review_gate receipt. Three-state error precision (ticket t260829-07):

    - an empty git_error = the lane commit query succeeded and lane_commits is
      meaningful; non-empty = the query failed and lane_commits=-1 is the sentinel
      (0 may never mean "couldn't ask" — recording 0 on an exception would misreport a
      git fault as "the implementation never landed", which may be the opposite of the
      truth).
    - An empty shots_path_error = the screenshots path is fine (nonexistent = nothing was
      shot, equivalent to 0 png, safe to claim missing); non-empty = the path exists but
      is broken (a file / unreadable) and png_count=-1 (you may not claim missing)."""

    git_error: str = ""
    lane_commits: int = -1
    shots_path_error: str = ""
    png_count: int = -1
    passed: bool = True
    reasons: List[str] = field(default_factory=list)
    # t260925-12 闸段分相计时（additive，口径同 ChangedFilesResult.wall_s）。
    wall_s: float = 0.0


def review_gate_verdict(git_error: str, lane_commits: int, shots_path_error: str,
                        png_count: int, no_file_changes: bool, is_ui: bool):
    """The mechanical review re-check verdict (pure function, ticket t260829-07; tested
    directly by the selfcheck without temporalio).

    Returns (rework, note): a non-empty rework = the forced bounce text (injected into
    implement as prev_ctx); a non-empty note = an explanation of the skip (recorded on
    the timeline, visible rather than silent, no bounce). Error-precision discipline: a
    failed query may never assert 「not landed / evidence missing」 — an assertion must
    point the same way as the facts."""
    if git_error:
        return "", "机械复核跳过：git 查询失败：%s" % git_error
    if lane_commits == 0 and not no_file_changes:
        return "机械复核：实现未落盘（泳道 0 commit）", ""
    if shots_path_error:
        return "", "机械复核跳过：截图路径异常：%s" % shots_path_error
    if png_count == 0 and is_ui:
        return "机械复核：UI 证据缺失（screenshots 无 png）", ""
    return "", ""


# ---- t260921-09: 多仓 merge_check「泳道分支有 commit」三态判定（判据对齐票）----
# 事实源：nusuyou t260920-04（4 仓 macOS 收口票，service 仓声明在写集但本票零改动）——
# 旧判据 green=(git log 成功 and n>0) 把「许可面」当「义务清单」（本文件 refresh_write_set
# docstring 早已写明相反口径：白名单是允许写的上限，不是必须清单），某仓合法零改动被逐仓
# 必判红，agent 只能伪造改动过闸或整票作废。对齐先例=本文件 review_gate_verdict 的整票级
# 口径（0 commit 且非 no_file_changes 才红）。判定粒度=仓（resolve_repos_for_paths 归属后
# 同仓目录合并为一条判定），严禁逐条目化（工单 t260921-09 第 0 条粒度锁）。

# 查询失败哨兵：沿 review_gate_verdict 的 error-precision 纪律（其 docstring：0 may never
# mean "couldn't ask"——git 故障记 0 = 把「问不到」误报成「没落盘」）。git 故障记 -1，
# 绝不记 0；消费方对 -1 不得产出「零 commit」类文案。
LANE_COMMITS_QUERY_FAILED = -1


def lane_commit_verdict(lane_commits, committed_diff_count, uncommitted_count):
    """逐仓「泳道分支有 commit」三态判定（纯函数，零 git/零 IO）。

    消费方=agent_activities._lane_commits_check_item（git I/O 薄壳）。输入：
      lane_commits          base..branch 提交数（-1=查询失败哨兵）；
      committed_diff_count  提交面差异数（git diff --name-only base branch 行数）；
      uncommitted_count     未提交差异数（git status --porcelain 行数）。
    返回 (green, reason_code)：
      n>0                    → (True,  "has_commits")        旧绿路径，逐项零回归；
      n==0 且两差异面均无差异 → (True,  "no_changes_no_diff") 本仓确实零改动=合法终态
                               （不红但回执点名可见，不静默；整票零 commit 由
                               multirepo_zero_commit_error 全局闸另行把关）；
      n==0 且任一差异面有差异 → (False, "no_commits")        这才是「实现未落盘」；
      n<0 / 输入畸形          → (False, "commit_query_failed")
                               查询失败=不可判定，fail-closed 红，但绝不断言「未落盘」
                               （error precision：报错必须与事实同向）。
    畸形输入（None/bool/非 int/意外负数）一律不抛、按查询失败红 fail-closed；差异计数
    畸形=不可证「无差异」→ 不给 amber（宁可红，不可假绿）。"""
    def _bad(v):
        return (not isinstance(v, int)) or isinstance(v, bool) or v < LANE_COMMITS_QUERY_FAILED

    if _bad(lane_commits):
        return False, "commit_query_failed"
    if lane_commits > 0:
        return True, "has_commits"
    if lane_commits == LANE_COMMITS_QUERY_FAILED:
        return False, "commit_query_failed"
    # lane_commits == 0：无提交，看两差异面（面计数畸形=不可证无差异，fail-closed）
    if _bad(committed_diff_count) or _bad(uncommitted_count):
        return False, "commit_query_failed"
    if committed_diff_count == 0 and uncommitted_count == 0:
        return True, "no_changes_no_diff"
    return False, "no_commits"


def multirepo_zero_commit_error(per_repo_commits, no_file_changes):
    """整票零 commit 全局闸（纯函数；merge_check 聚合层消费）。

    宿主裁定②（2026-09-21 当面）：保留「整票至少一个仓有 commit」——逐仓三态把「某仓
    确实零改动」转成合法终态后，由本闸保住原防伪需求（什么都没提交却全绿）。排除
    no_file_changes 票（与 review_gate_verdict 同一豁免口径）后，全部仓计数均为 0 →
    返回点名各仓的拒收文案；否则返回 ""（放行）。

    不可判定即跳过（绝不误判「整票零 commit」）：任一仓计数为查询失败哨兵 -1（或有
    commit / 畸形非 int）→ 返回 ""——含查询失败仓时该仓的红由逐仓 commit_query_failed
    fail-closed 承担，全局闸不得叠加「整票零 commit」的错误文案与错误出路（review C1）。
    真纯函数：无 git 子进程、无 IO；畸形键/值不抛。"""
    if no_file_changes:
        return ""
    counts = dict(per_repo_commits or {})
    if not counts:
        return ""
    zero_repos = []
    for name, n in counts.items():
        if (not isinstance(n, int)) or isinstance(n, bool) or n != 0:
            return ""  # 有 commit / 查询失败(-1) / 畸形 → 全局闸不可判「全零」，跳过
        zero_repos.append(str(name))
    return ("整票零 commit（%s）——若各仓确无本票改动，建票时应以 allow_empty_write_set "
            "声明（no_file_changes）；否则排查实现段 settle 代落盘后发 retry_qc"
            % "、".join(zero_repos))


@dataclass
class UiEvidenceArgs:
    """Inputs of the prepare_ui_evidence activity (t260828-09: the worker runs
    ui-check/capture.mjs to take the screenshots)."""

    ticket_id: str
    worktree: str = ""                        # the lane worktree path (screenshots land in <worktree>/.sandbar/screenshots/)
    screenshots_dir: str = ""                 # default <worktree>/.sandbar/screenshots


@dataclass
class UiEvidenceResult:
    """The prepare_ui_evidence receipt (failure does not raise — missing screenshots are
    closed out by merge_check's evidence gate going red)."""

    ok: bool = False
    shots: List[str] = field(default_factory=list)  # the screenshot filenames produced successfully (no directories)
    # A 「name (mtime iso)」 list, one line per screenshot (computed in the activity and
    # carried back — the workflow side's zero-IO discipline; dev_lane splices it straight
    # into the review prompt so the agent can compare screenshot timestamps and old
    # images cannot pose as fresh ones)
    shot_lines: List[str] = field(default_factory=list)
    detail: str = ""                          # the failure reason / success summary (a trace for the prompt and the gate)
    skipped: bool = False                     # set true when skipped as a non-UI ticket (a backstop semantic; the workflow side normally guards this)


@dataclass
class UiChangedPathsArgs:
    """Inputs of the ui_changed_paths activity (t260904-13, the KI-044 root fix: UI-ticket
    detection switched to a diff source)."""

    ticket_id: str
    worktree: str = ""                        # the lane worktree path (the diff anchors the repo owning the lane, _lane_repo_root)
    branch: str = ""                          # the lane branch name
    base_ref: str = ""                        # the creation base point (for the record / replay compat; the diff baseline uses merge-base and ignores the pinned base point)


@dataclass
class UiChangedPathsResult:
    """The ui_changed_paths receipt (a git failure doesn't raise — empty ui_paths is
    fail-closed, and the caller treats it as 「UI ticket, evidence pending」)."""

    ui_paths: List[str] = field(default_factory=list)  # the paths whose diff hit the UI stance (order preserved)
    detail: str = ""                          # the judgement stance and error trace (consumed by log / results evidence)


@dataclass
class UiEvidenceDeclArgs:
    """Inputs of the ui_evidence_decl activity (t260904-18 KI-050 gate ③: the declaration
    preload).

    When the lane starts, the ui_evidence declaration is read from the lane root's
    verify.yaml into meta (the disk read happens in the activity while the workflow only
    reads meta = replay safe); the review_gate patched branch judges UI tickets from it."""

    ticket_id: str
    worktree: str = ""                        # the lane worktree path (the declaration is read from <worktree>/verify.yaml)


@dataclass
class UiEvidenceDeclResult:
    """The ui_evidence_decl receipt (three states as in load_ui_evidence; failure doesn't
    raise — the consumer falls back to the declaration-absent stance)."""

    mode: str = "absent"                      # ok | absent | malformed
    dirs: List[str] = field(default_factory=list)  # the declared screenshot evidence directories (meaningful when mode=ok)
    note: str = ""                            # the absent/malformed trace (consumed by the log)


@dataclass
class MergeCheckResult:
    """The merge_check receipt (red lights don't raise — the receipt goes back to the
    workflow for triage).

    Ticket t260826-01's automatic conflict resolution loop: red lights split into two
    classes — conflict=True (a merge rehearsal conflict, handed to the workflow to bounce
    back to implement automatically) and conflict=False (any other red, stay blocked for
    a human). The conflict test is 「the merge rehearsal item is red AND a non-empty
    conflict_files was parsed」 (merge-tree's rc=1 alone is not enough: git faults such as
    a bad ref also return rc=1 with no conflict files, and misclassifying them as a
    resolvable conflict would spin the resolution loop idly). And whenever any of the
    other three items is red (no commits / a dirty workspace / verify_lane red),
    conflict=False unconditionally: a human solves the underlying problem first — never
    resolve while sick."""

    green: bool = False
    checks: List[Dict[str, Any]] = field(default_factory=list)  # [{item, green, detail}]
    error: str = ""                           # the reason on an infrastructure fault (git unavailable etc.)
    conflict: bool = False                    # True = a merge rehearsal conflict (auto-resolve); False = any other red (blocked)
    conflict_files: List[str] = field(default_factory=list)  # the conflict file list (parsed from the merge-tree output)
    merge_tree_excerpt: str = ""              # a truncated merge-tree output excerpt (carried out and injected into the agent's conflict-resolution prompt)


@dataclass
class ConflictPrepArgs:
    """Inputs of the prepare_conflict_resolution activity (ticket t260826-01: the worker
    runs the merge and leaves the conflict state in place).

    The agent sandbox cannot write the real .git (a worktree's .git is a gitfile pointing
    at the main repo), so it cannot git merge by itself — the worker (unsandboxed) runs
    the merge instead, the conflict-marked files stay in the lane workspace, and the
    agent only edits the markers away (the same contract as the implement step's 「the
    agent writes, the worker settles」)."""

    ticket_id: str
    worktree: str = ""                        # the lane worktree path (repo-relative or absolute)
    branch: str = ""                          # the lane branch name
    base_ref: str = ""                        # the target ref to merge into the lane (the current stance = main, no rebase swap)


@dataclass
class ConflictPrepResult:
    """The prepare_conflict_resolution receipt (failure doesn't raise — the receipt goes
    back to the workflow for triage)."""

    ok: bool = False
    conflict_files: List[str] = field(default_factory=list)  # the conflict file list (the UU/AA lines)
    merge_output: str = ""                    # a truncated git merge output (the agent's conflict-resolution context)
    already_clean: bool = False               # True = the merge found no conflicts (the race backstop: base_ref untouched, go straight back to merge_check)
    error: str = ""                           # the reason on an infrastructure fault (a missing ref / a merge exception etc.)
    # ---- t260922-18 主同步（机械验证前并 main 一次）证据面：三键全带缺省，老历史
    # dict 回退重建点零改动兼容（漏键=缺省值，消费方按「无证据」显式点名，不猜）。
    target_sha: str = ""                      # 本次合并目标 ref 的完整 sha（机械证据：main@sha 进票面）
    lane_head: str = ""                       # 动作后泳道 HEAD 短 sha（快路径/干净合并/冲突现场语义见活动 docstring）
    up_to_date: bool = False                  # True = 目标 ref 已是 HEAD 祖先（is-ancestor 快路径零动作返回，幂等）
    # t260925-12 闸段分相计时（additive，口径同 ChangedFilesResult.wall_s）。
    wall_s: float = 0.0


@dataclass
class ConflictSettleArgs:
    """Inputs of the settle_conflict_resolution activity (the worker settles after the
    agent resolved the conflicts)."""

    ticket_id: str
    worktree: str = ""
    branch: str = ""
    base_ref: str = ""
    round_no: int = 0                         # the conflict resolution round (written into the commit message and the log)


@dataclass
class ConflictSettleResult:
    """The settle_conflict_resolution receipt (failure doesn't raise — the receipt goes
    back to the workflow for triage)."""

    ok: bool = False
    commit: str = ""                          # the short hash of the landed merge commit
    remaining_files: List[str] = field(default_factory=list)  # files still carrying unresolved conflicts (non-empty = the agent didn't finish)
    error: str = ""


@dataclass
class MergeArgs:
    """Inputs of the merge activity (the real merge after human sign-off, plus lane
    teardown).

    defer_teardown (ticket t260902-02, M1-3): when True, the inline lane cleanup is
    **skipped after the squash booking** and handed to the later teardown_lane activity
    (the three-stage close-out merge → archive → teardown); False = the old semantics
    (inline cleanup after booking). Defaulting the field to False is the payload
    compatibility device (the patched gate only gates the workflow-side branch and cannot
    reach the activity's behavior version): existing historical inputs are serialized
    **without this key**, and temporalio's dataclass deserialization falls back to the
    default False for a missing key → the old inline-cleanup semantics, so after a new
    worker deploy the existing tickets still tear their lane down normally at sign-off
    with zero residue."""

    ticket_id: str
    worktree: str = ""
    branch: str = ""
    base_ref: str = ""
    defer_teardown: bool = False
    # 保险丝B 输入（t260910-03）：票面写集，merge 循环逐仓 squash 前跑
    # multirepo_materialization_error 用。payload 兼容先例=defer_teardown：在途旧票
    # 序列化无此键，反序列化回落空列表。语义明示：**空列表=保险丝不触发**（在途旧票
    # 已过 merge_check 前置闸，按旧语义收口，不追溯红灯）——这是兼容约定，不是
    # 静默降级；新票由 dev_lane 构造处恒传 meta.write_set。
    write_set: List[str] = field(default_factory=list)
    # 拆道逐仓化输入（t260913-05）：teardown_lane 的成员仓明细，由 workflow 侧传
    # meta.repo_worktrees（唯一真源，条目形状 {repo,name,branch}，build_repo_worktrees
    # 定形）。payload 兼容先例=defer_teardown/write_set：在途旧票序列化无此键，反序列化
    # 回落空列表。语义明示：**空列表=不提供救源**——teardown 回落到盘上清单镜像（与
    # merge 同输入，正常态），清单缺失再回落旧单仓路径（引擎仓泳道命令流逐字节不变）；
    # 有值而盘上清单已随部分拆除消失时用它点名成员仓（堵「重试回落单仓锚 → 成员仓静默
    # 残留」）。merge 不消费本字段。
    repo_worktrees: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ArchiveArgs:
    """Inputs of the archive_ticket activity (ticket t260902-02 M1-3: exporting a
    finished ticket's data).

    The archive source of truth is exported to the per-key data directory (contract v1.4
    ①c), curing 「a finished ticket's stage reports vanishing with the lane teardown」. An
    empty worktree = a main-tree-lane ticket — the coordination directory is taken from
    the main-tree root (resolve_dot_dir's sticky resolution) for archiving (proxy files
    are a gray area; archiving is the sweep, never a silent pass). The meta snapshot is
    passed in by the workflow side (the workflow-never-touches-disk discipline); the file
    list and the copying are scanned fresh by the activity under the ARCHIVE_INCLUDE_*
    stance."""

    ticket_id: str
    project_key: str = ""             # the key the archive belongs to (must pass the PROJECT_KEY_RE whitelist)
    worktree: str = ""                # the lane worktree path (repo-relative or absolute)
    meta: Dict[str, Any] = field(default_factory=dict)  # the ticket's meta snapshot (stage/status/timeline/handoffs/checks…)
    legacy: bool = False              # True = archive-legacy's honest accounting for an existing ticket (the manifest records a reason, no file payload)


@dataclass
class ArchiveResult:
    """The archive_ticket receipt (failures raise, fail-closed — archive success is the
    precondition for tearing down the lane, no degradation).

    Idempotent: a rerun overwrites the same paths (safe under Temporal retries).
    retained = the lane is still in place (in the new order archive runs before
    teardown), always True for this ticket; False appears only in the archive-legacy
    no-worktree scenario (the lane was torn down long ago). files = manifest.files
    carried back (for the workflow side's records)."""

    ok: bool = False
    archive_path: str = ""            # the absolute path of the data/tickets/<id>/ directory
    retained: bool = True             # whether the lane is still in place (True = awaiting teardown_lane; False = legacy, no lane)
    files: List[Dict[str, Any]] = field(default_factory=list)   # a mirror of manifest.files
    absent: List[str] = field(default_factory=list)             # a mirror of manifest.absent
    error: str = ""                   # the failure reason (the workflow side assembles the blocked text from it)


@dataclass
class MergeResult:
    """The merge receipt (conflicts/faults don't raise — the receipt goes back to the
    workflow to turn blocked for human handling)."""

    ok: bool = False
    # KI-048 (t260911-05): action gains "dirty" — a main-workspace dirt rejection is
    # git's local-change protection, NOT a conflict; misclassifying it as conflict
    # made the workflow auto-bounce (t260904-14: a first sign-off silently consumed).
    action: str = ""      # merged | conflict | dirty | failed
    merge_commit: str = ""
    error: str = ""
    # Failure-classification protocol reason code (open vocabulary, never empty on a
    # failure — unclassifiable shapes fall to merge_fault, never coerced to conflict):
    #   main_staged / main_dirty / untracked_collision / conflict / merge_fault
    reason: str = ""
    # Named files blocking the merge (KI-048 件②: the human-gate/ticket face must see
    # WHICH file). Default empty = old receipts deserialize untouched.
    files: List[str] = field(default_factory=list)


# ---- Result file / log paths (pure functions; the activity and the prompt assembly
# share this one source of truth, so they cannot drift) ----

def stage_workspace(inp_ws: Optional[Dict[str, str]], ticket_id: str) -> Optional[Dict[str, str]]:
    """The agent stage's working directory: the ticket's registered workspace wins; with
    none → the /tmp/sandbar-ws/<ticket id> isolated directory (LEGACY old-base stickiness)
    (an agent on a main-tree lane also works in the repo root, but result files / logs
    always land in the isolated directory, leaving the main tree untouched)."""
    if isinstance(inp_ws, dict) and inp_ws.get("type") in WORKSPACE_TYPES and inp_ws.get("path"):
        return {"type": str(inp_ws["type"]), "path": str(inp_ws["path"])}
    return {"type": "dir", "path": ws_dir_path(ticket_id)}


def result_file_for(ticket_id: str, stage_id: str, gen: int,
                    ws: Optional[Dict[str, str]]) -> str:
    """The absolute path of this stage's result file for entry number gen (the
    idempotence anchor; a rework re-run uses gen+1 for a fresh file).
    The directory surface goes through resolve_dot_dir (a write point: an old lane stays
    sticky on the old name, a new lane lands in .sandbar/, never mixed)."""
    base = (ws or {}).get("path") or ws_dir_path(ticket_id)
    p = pathlib.Path(base)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(lane_dot_path(p, "stage_%s_gen%d.json" % (stage_id, gen)))


def agent_log_for(ticket_id: str, stage_id: str,
                  gen: int, ws: Optional[Dict[str, str]]) -> str:
    """The agent run log path (a write point: the same sticky stance as result_file_for —
    never blindly sed it to the new name; writing an old lane's logs into the new-name
    directory would bypass the stickiness and the logs would vanish from both the handover
    and the archive)."""
    base = (ws or {}).get("path") or ws_dir_path(ticket_id)
    p = pathlib.Path(base)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(lane_dot_path(p, "agent_%s_gen%d.log" % (stage_id, gen)))


# Stage-level acceptance extras (ticket t260901-09): standing check items hung on the
# prompt assembly source of truth (build_stage_prompt), keyed by stage id —
# build_stage_prompt is shared by base.py and dev_lane.py, so a missing key means zero
# change (no effect on base-family workflows); the wording carries its own 「if not
# applicable, mark it not applicable」 backstop.
STAGE_ACCEPTANCE_EXTRA: Dict[str, Tuple[str, ...]] = {
    "acceptance_walkthrough": (
        "若本票涉及 UI/泳道图渲染，验收报告必含『并行期 UI 呈现』检查项：并行分叉期"
        "步骤条双边同亮（两步同帧 data-s=running 且各带 ∥ 标记）+ 状态行报"
        "『并行分叉中』，以隔离台实拍/DOM 断言输出为证；不涉及 UI 则标注『不适用』并说明",
        # Ticket t260905-01 (doc-lifecycle ticket ②): the two close-out questions — a
        # sedimentation trigger plus a reverse-sync gate. Answering or not never blocks
        # acceptance, but the answer must be recorded in the result file's doc_sediment /
        # doc_conflicts fields (the engine side's apply_doc_gate judges and registers;
        # an unanswered question is still a record, and contradiction entries go into the
        # debt ledger).
        "收口两问（答与不答都不阻塞验收，但必须留痕）：①沉淀一问——盘点本票 "
        "deliverables，判断是否留下值得沉淀进 docs/ 的事实；有则预填建议"
        "（target=建议文档路径/分类，reason=理由，从改动清单与验收结论推导），"
        "确无可沉淀则显式写 want=false 并说明；②反向同步闸——对照本票实现，核对 "
        "docs/ 既有文档关键主张是否被推翻；有矛盾逐条列 doc/claim/actual 三要素，"
        "只报你实际读过的文档，禁止凭印象。两问结论写进结果文件 doc_sediment / "
        "doc_conflicts 字段；矛盾条目由引擎登记债册（pending-doc-sync），"
        "人审签字前由 merge 执行人转正进 notes/debts/known-issues.md 或 docs 债册，"
        "未转正不得视为已闭环",
    ),
}


# ---------- Capping previous_context (ticket t260901-19: bounce feedback verbatim + history summaries capped) ----------
# The capped class = the six history line types assembled by base.py (a closed prefix
# table, matching base.py's history line format character for character).
# Note: if base later adds history line types beyond 「- 上次*」 they would escape the
# cap — the pass-through lines' 20000-character hard cap backstops that (against a
# malformed giant line); this table is not chased after the fact.
CAP_PREV_LINE_PREFIXES: Tuple[str, ...] = (
    "- 上次状态：", "- 上次摘要：", "- 上次报告：",
    "- 上次产物：", "- 上次改动文件：", "- 上次验收证据：",
)
CAP_PREV_LINE_LIMIT = 800        # the capped class's per-line limit
CAP_PREV_TOTAL_LIMIT = 4000      # the capped class's total limit (over the limit, lines are dropped from the tail)
CAP_PREV_HARD_LIMIT = 20000      # the pass-through lines' hard cap (only guards against malformation; normal payloads are far below this)
_CAP_TRUNC_MARK = "…（截断）"
_CAP_OMIT_MARK = "…（后续历史已省略）"


def cap_previous_context(text: Any) -> str:
    """Cap previous_context (pure function): only the capped class of history lines gets
    truncated, everything else passes through untouched.

    - The capped class (a prefix hit on CAP_PREV_LINE_PREFIXES): a line over 800 is cut
      to 800 + an elision marker; past 4000 in total, lines are dropped from the tail
      (history lines run oldest-last, so the tail is the oldest), and once anything was
      dropped a tail note is added.
    - The pass-through class: 「- 打回原因：」 lines and every line with an unrecognized
      prefix (bare bounce feedback, structured bounce blocks, arb_ctx single-line JSON —
      dev_lane's payloads) are kept verbatim, only truncated at 20000 characters per line
      to guard against malformation — these lines carry the bounce feedback / machine
      results, and cutting them would hollow out the next round's input (ticket
      t260901-19).
    - Defensive normalization: None / non-string / whitespace-only → an empty string; an
      empty string → returns an empty string (the caller's injection guard is
      unchanged)."""
    if not isinstance(text, str) or not text.strip():
        return ""
    capped: List[Tuple[bool, str]] = []  # (is a capped-class line, the line text)
    for ln in text.splitlines():
        if ln.startswith(CAP_PREV_LINE_PREFIXES):
            if len(ln) > CAP_PREV_LINE_LIMIT:
                ln = ln[:CAP_PREV_LINE_LIMIT] + _CAP_TRUNC_MARK
            capped.append((True, ln))
        else:
            if len(ln) > CAP_PREV_HARD_LIMIT:
                ln = ln[:CAP_PREV_HARD_LIMIT] + _CAP_TRUNC_MARK
            capped.append((False, ln))
    total = sum(len(ln) for is_cap, ln in capped if is_cap)
    out: List[str] = []
    dropped = False
    for is_cap, ln in reversed(capped):
        if is_cap and total > CAP_PREV_TOTAL_LIMIT:
            total -= len(ln)
            dropped = True
            continue
        out.append(ln)
    out.reverse()
    if dropped:
        out.append(_CAP_OMIT_MARK)
    return "\n".join(out)


# ---- KI-053 (ticket t260905-10) constants for the host-ruling injection surface ----
# The prompt consumes only the last N entries (ordered old → new, the newest hugging
# 「now」); a note over LIMIT is truncated with a _CAP_TRUNC_MARK marker (never cut
# silently — the agent must not believe it read the complete instruction); the full
# truncated text and any older rulings that fell out of the prompt are backstopped in
# meta['host_rulings'] (readable from the snapshot) plus the injection-trace event
# history; the prompt's hard budget ceiling ≈ 5×(1200 + ~80 of line header) + section
# framing ≈ 6.6KB, so it does not grow linearly with the number of rulings.
HOST_RULING_PROMPT_MAX = 5
HOST_RULING_NOTE_LIMIT = 1200
# The intake cap for a ruling note (dev_lane's signal input gate): over the limit it is
# refused into refused (the text names it) and never enters the event history — the same
# value family as cap_previous_context's HARD_LIMIT.
HOST_RULING_NOTE_INPUT_LIMIT = 20000


def build_stage_prompt(ticket_id: str, meta: Dict[str, Any], stage: Stage,
                       handoffs: List[Dict[str, Any]], result_file: str,
                       gen: int, previous_context: str = "") -> str:
    """An agent stage's dispatch prompt (pure function, zero IO — called
    deterministically inside the workflow).
    Context = the ticket's business attributes + the previous stage's handoff summaries +
    the result-file contract.
    A non-empty previous_context is appended (the last run's output + the bounce reason,
    from the workflow history).
    Note that gen is only the display value of 「how many times this stage was entered」 —
    the engines disagree on the base (base is 1-based, dev_lane 0-based), so it is never
    used as an injection guard (a gen>1 guard once swallowed the first bounce feedback of
    the 0-based engine, ticket t260828-04)."""
    ws = stage_workspace(meta.get("workspace"), ticket_id)
    lines = [
        "【派活指令】工单 %s（%s）阶段：%s（%s，角色=%s，第 %d 次进本段）"
        % (ticket_id, meta.get("title") or "", stage.id, stage.name, stage.role, gen),
        "1. 必读上下文（按序先读再动手）：",
        "   ① CLAUDE.md（仓库根，项目交接说明——**只读**，不得修改）",
        "   （岗位说明书已随角色 preset 烘焙进你的 persona，无需另读文件）",
        "   （取证效率纪律：只读侦察期一次 bash 批量读——多文件/多 grep 合一条调用"
        "（如 for f in A B C; do echo == $f; sed -n '1,50p' $f; done），"
        "禁止逐文件往返烧时；每轮模型往返都是分钟级成本。写改动仍小步分次。）",
        "   ② 知识库：docs/ = 定稿知识库，目录=docs/README.md（每篇一句话用途；"
        "机器索引 docs/index.json 备用）。动手前对照目录与你的标题/写集判断相关"
        "设计文档，相关的读全文，不相关不读。",
    ]
    # Body = the original user request (ticket t260822-m16: user_request kept verbatim,
    # taking precedence when present; the default falls back to body); the processed
    # dispatch specification is presented separately (spec) and no longer mixed into the
    # body.
    body = str(meta.get("user_request") or meta.get("body") or "").strip()
    spec = str(meta.get("spec") or "").strip()
    if body or spec:
        lines.append("2. 工单正文（原始用户需求，用户原话逐字保留）：")
        if body:
            lines.append("\n".join("   " + ln for ln in body.splitlines()) if "\n" in body else "   " + body)
        else:
            lines.append("   （无正文）")
        if spec:
            lines.append("   加工后派发规格（供执行参考，不覆盖正文）：\n" + spec)
    if meta.get("write_set"):
        lines.append("3. 写集（只允许动这些）：%s" % "；".join(meta["write_set"]))
    acceptance_items = list(stage.acceptance) + list(STAGE_ACCEPTANCE_EXTRA.get(stage.id) or ())
    if acceptance_items:
        lines.append("4. 本段验收清单（结算自检用）：%s" % "；".join(acceptance_items))
    sec = 5
    # KI-053 (ticket t260905-10): the host-ruling injection surface — the formal channel
    # for human opinions (injectable even in the blocked state, with the injection traced
    # into the event history). Mechanical-stage prompts such as arbitrate/acceptance
    # consume it too, so a human opinion no longer has to travel via create_plan /
    # implement's rework note. With no rulings this section doesn't appear and the
    # following section numbers keep the existing 5/6/7 layout (zero regression).
    rulings = [r for r in (meta.get("host_rulings") or []) if isinstance(r, dict)]
    if rulings:
        lines.append("%d. 宿主裁决注入（人工意见正规通道，按此校准执行方向；旧→新排序，"
                     "末尾最新；完整清单与被截全文见工单 meta.host_rulings）：" % sec)
        sec += 1
        for r in rulings[-HOST_RULING_PROMPT_MAX:]:
            note = str(r.get("note") or "")
            if len(note) > HOST_RULING_NOTE_LIMIT:
                note = note[:HOST_RULING_NOTE_LIMIT] + _CAP_TRUNC_MARK
            lines.append("   - [%s %s] %s" % (str(r.get("ts") or "?"),
                                              str(r.get("who") or "?"), note))
    prev = [h for h in (handoffs or []) if isinstance(h, dict)]
    if prev:
        lines.append("%d. 前段交接（倒序，最近在前；正文=前段报告，含怎么验证的/遗留风险）：" % sec)
        sec += 1
        for h in reversed(prev[-3:]):
            body = str(h.get("report") or "") or str(h.get("summary") or "")
            lines.append("   - [%s] %s" % (h.get("stage", "?"), body[:1200]))
    # Stage re-run context inheritance: the caller passes a non-empty previous_context
    # only when this stage is re-running, and non-empty means injected (gen is never the
    # guard — dev_lane's gen is 0-based, so a gen>1 guard would miss the first bounce)
    n = sec
    prev_ctx_text = cap_previous_context(previous_context)
    if prev_ctx_text:
        lines.append("%d. 上次运行上下文（阶段重跑上下文继承：同 role 再次调用时 prompt 注入上次产出+打回原因）：" % n)
        for ln in prev_ctx_text.splitlines():
            lines.append("   " + ln)
        n += 1
    lines.append("%d. 工作目录：%s（%s）——已由 workflow 第一个 activity（prepare_workspace）创建/复用，"
                 "**直接进入干活，勿自行 git worktree add / mkdir**；一切读写在此空间内；"
                 % (n, ws["path"], ws["type"]))
    lines.append("   " + OWNERSHIP_CONTRACT.replace("\n", "\n   "))
    lines += [
        "%d. 交付契约（硬性）：干完把结果写到 %s，JSON 格式：" % (n + 1, result_file),
        '   {"status":"ok|failed","summary":"台面一句话","report":"人读进展报告",'
        '"deliverables":["产物路径…"],"files_changed":["改动文件…"],"evidence":"原始证据"}',
        "   环境不可用契约（t260917-08）：agent bash 沙箱不可用（命令工具报 sandbox_apply denied /"
        " no sandbox backend / SANDBOX_UNAVAILABLE）时：**文件面产物照常交付**，结果文件加"
        ' "env_fail":true 与 "env_reason":"<缺什么，日志原文摘录>"；没能亲自跑的验证逐条写'
        ' "handover_runs":[{"name":"<≤120字符>","cmd":"<≤500字符，泳道根可独立执行>"}]（≤20 条），'
        "由后续机械段 worker 执行面承接——票不停摆。不许谎报 status=failed（交付并未失败），"
        "也不许用 status=ok 掩盖「验证未运行」——env_fail 位就是「未验证」的显式声明；"
        "env_fail=true 而不交清单=票面点名「未验证且无移交命令」，仲裁不当已验证。"
        "无机械段的工作流模板：移交命令留债票面，人审处置。",
        "   三层口径（各喂各的读者，别混）：",
        "   - summary：≤40 字，结论+对象（如「入轨三处防呆纪律，自测全绿」）。给工单台列表行。",
        "   - report：给人看的进展报告，markdown，短。固定小节「做了什么 / 怎么验证的 /"
        " 遗留与风险」（没有内容的小节省略；review 步的意见在这里分条写）。",
        "     读者是不熟悉本工单的人和你自己的下一棒——写清楚而不是写压缩长句。",
        "   - evidence：机器口径原始证据（命令/路径/关键输出），台面默认折叠，不用照顾可读性。",
        "   结算 note 末列参考 docs 清单（读过哪些路径；空则写无）——"
        "integration merge 关卡核对文档漂移的观测点。",
        "   结果文件是幂等锚点：已存在则本段视为已完成（重跑安全），所以只在真正完成后写。",
        "%d. 落盘口径：改动写进写集内文件即可，**不要自己 git commit / git add / git worktree，"
        "也不要改 .git 文件、不要用 GIT_DIR 指向自建仓库**（headless 沙箱写不了真 .git——"
        "worktree 的 .git 是指向主库的 gitfile，物理上提交不了；你交付结果文件后 worker 会"
        "确定性代落盘为一个 commit，自建假仓库/改写 gitfile 都会被 worker 检出并隔离）。"
        "判断不了的写进 report 的「遗留与风险」交回，不硬改。" % (n + 2),
    ]
    return "\n".join(lines)


# Template id → workflow class name (the single source of truth for client.py
# ticket-start's class choice; the worker registration list matches this table)
# 260904 host order: only dev-lane remains (content-pipeline/proofread/regression/cleanup
# retired)
TEMPLATE_CLASS_NAMES: Dict[str, str] = {
    "dev-lane": "DevLaneWorkflow",
}
# 夹具模板环境门（工单 t260908-01）：SANDBAR_FIXTURE_TEMPLATES=1 时把测试夹具模板
# fixture-two-step 挂进注册表——生产/闸内默认面恰为 {dev-lane}（sc_template_face
# _narrowing 的收窄断言以默认面为准，env 只在测试场景 worker 子进程注入），夹具
# 模板永不上生产板。workflows_v2 的 TEMPLATE_CLASSES/ALL_WORKFLOWS_V2 同款同门。
FIXTURE_TEMPLATES_ENV = "SANDBAR_FIXTURE_TEMPLATES"
if os.environ.get(FIXTURE_TEMPLATES_ENV) == "1":
    TEMPLATE_CLASS_NAMES["fixture-two-step"] = "FixtureTwoStepWorkflow"

# ---- The engine's data-export archive paths (ticket t260902-02, M1-3) ----
# The archive source of truth = the machine-level per-key data directory (contract v1.4
# ①c): a finished ticket's stage results / settle reports, session records and UI
# evidence are copied into <root>/<key>/data/tickets/<id>/, so tearing down the lane
# loses nothing.
# This PROJECT_KEY_RE is the source of truth (originally in agent_activities.py, moved up
# by that ticket): the same character set as server/project-registry.ts's PROJECT_KEY_RE,
# and it also blocks ../ path traversal (per-key credential/archive paths all splice in a
# directory name). EPIC_CODE_RE is another copy of the same character set (the same
# anti-traversal semantics); the two are deliberately not merged (each carries its own
# comment on where the character set comes from).

PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def perkey_projects_root() -> pathlib.Path:
    """The per-key project directory root (the source of truth; env is read fresh on
    every call, mirroring project-registry.ts's registryRoot semantics). The env
    semantics differ deliberately from the TS side: an empty or relative
    SANDBAR_PROJECTS_DIR = treated as unset, falling back to the default root — TS's `??`
    does not reject an empty string (which would point at the root directory itself),
    while here it is rejected explicitly rather than guessed."""
    root = os.environ.get("SANDBAR_PROJECTS_DIR") or ""
    if not root or not os.path.isabs(root):
        return pathlib.Path.home() / ".sandbar" / "projects"
    return pathlib.Path(root)


def ticket_data_dir(project_key: str, ticket_id: str) -> pathlib.Path:
    """A finished ticket's archive directory (M1-3):
    <SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/data/tickets/<id>/.

    Both project_key and ticket_id must pass the PROJECT_KEY_RE whitelist — both are
    spliced into the archive path from external meta, so any boundary violation (../, a
    leading "-", etc.) raises ValueError, and the caller may not do its own fallback
    splicing."""
    key = str(project_key or "").strip()
    if not PROJECT_KEY_RE.match(key):
        raise ValueError("project_key 形状非法：%r（白名单 %s）" % (key, PROJECT_KEY_RE.pattern))
    tid = str(ticket_id or "").strip()
    if not PROJECT_KEY_RE.match(tid):
        raise ValueError("ticket_id 形状非法：%r（白名单 %s）" % (tid, PROJECT_KEY_RE.pattern))
    return perkey_projects_root() / key / "data" / "tickets" / tid


# ---- Contract ①d: the project.yaml paths section — in-project path declarations
# (ticket t260903-03) ----
# The engine may not hardcode 「some fixed path inside the project」 (a precondition of
# sandbar's M2 physical migration): the two in-project paths — the roles directory and
# the model route table — are declared by the project in the registry entry's optional
# top-level paths section (relative to the project root), and the engine reads them
# through this reader. The contract's source of truth =
# docs/design/sandbar项目接入契约v1.md ①d:
#   The four fallback classes (no paths section / a missing key inside it / the entry
#     file doesn't exist / an empty project key or one failing the whitelist) →
#     undeclared; the consumer falls back to the current convention (zero change, zero
#     regression for sandbar);
#   A malformed declared value / an unparseable top-level shape in the entry file / a
#     declared anchor missing or the wrong kind → fail-closed red (ProjectPathsError)
#     naming the entry file or the resolved path — a broken file must never be silently
#     treated as 「missing」;
#   Anchor versus contents: a missing per-role file keeps the soft skip, and a corrupt
#     route table inherits the lookup tolerance (model_route_for returns None → the
#     default model) — the four states only cover declared values and anchors.
# Resolution base differs: roles_dir is relative to the spawn cwd (the lane worktree,
# ticket snapshot semantics), model_routes is relative to the entry's dirs[0] (the home
# directory; the runtime source of truth follows the main repo).
# Hand-written parsing, stdlib-only (the system python3 has no pyyaml; at spawn time the
# only reader of the entry file is this reader, while the loader runs only at ticket
# creation / registration): the top level only accepts schema:/project:/paths:, a missing
# schema = malformed, a non-v1 schema = unsupported version; the shape of the fields
# inside project: belongs to the loader (①a), and only the first item of the dirs list is
# taken here as the resolution base. Values may not contain # (a trailing # starts a
# truncation), the same stance as the loader's _strip_line.

DEFAULT_ROLES_DIR = "server/roles"   # the fallback convention: the roles directory (relative to the project root)

# t260921-14 增 dsh_bin：dsh 二进制路径钉（机器级放宽口径，同 model_routes 家族；
# 未知键红/重复键红由 _entry_paths_parse 的 closed set 自动覆盖新键）。
# t260924-04 增 workflow_modules：项目外置工作流模板模块清单（`,` 分隔多项，每项
# 相对项目主目录 dirs[0]；加载口语义见 project_templates.py 与加载口文档）。`,
# 分隔是本键新语义：逐项 strip 后判空（空项=畸形点名第 N 项），逐项过 _decl_rel
# 同款校验（绝对/.. 越界/非标量各红）；值含 # 仍按①d 既有 stance 截断（加载口
# 文档明示不支持）；不放行机器级 ~/绝对形态（t260910-14 放宽不外溢到本键，将来
# 要机器级另票放宽）。
PATHS_DECL_KEYS = ("roles_dir", "model_routes", "inspection_decl", "dsh_bin",
                   "workflow_modules")


class ProjectPathsError(ValueError):
    """Contract ①d fail-closed: a malformed declared value / an unparseable entry file /
    a declared anchor missing or misplaced."""


def _entry_paths_parse(text: str, label: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Minimal parse of the entry file: returns (the paths declaration dict or None, the
    first dirs item or None).
    An unparseable top-level shape = ProjectPathsError (never a fallback — R1: a broken
    file must go red)."""
    schema: Optional[str] = None
    paths: Optional[Dict[str, str]] = None
    main_dir: Optional[str] = None
    section = ""  # the top-level section we are currently in ("" = no top-level key seen yet)
    for i, raw in enumerate(text.split("\n"), 1):
        line = re.sub(r"#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        if not raw[:1].isspace():
            m = re.match(r"^([a-z]+):(.*)$", line)
            if not m:
                raise ProjectPathsError(
                    "%s:%d 顶层无法解析（只认 schema:/project:/paths:）：%s" % (label, i, line.strip()[:60]))
            key, val = m.group(1), m.group(2).strip()
            if key not in ("schema", "project", "paths"):
                raise ProjectPathsError("%s:%d 顶层只认 schema:/project:/paths:，见 %s:" % (label, i, key))
            if key in ("project", "paths") and val:
                raise ProjectPathsError("%s:%d %s: 后必须换行给内容" % (label, i, key))
            if key == "schema":
                if schema is not None:
                    raise ProjectPathsError("%s:%d schema: 重复" % (label, i))
                schema = val
            elif section == key:
                raise ProjectPathsError("%s:%d %s: 重复" % (label, i, key))
            if key == "paths":
                paths = {}
            section = key
            continue
        if section == "paths":
            m = re.match(r"^  ([a-z_]+):\s*(.*)$", line)
            if not m:
                raise ProjectPathsError(
                    "%s:%d paths 节只认两空格缩进的 key: value（键值同行标量）：%s" % (label, i, line.strip()[:60]))
            k, v = m.group(1), m.group(2).strip()
            if k not in PATHS_DECL_KEYS:
                raise ProjectPathsError(
                    "%s:%d paths 节不认的键: %s（只认 %s——未知键不静默过滤，同 ②c 纲）" % (label, i, k, "、".join(PATHS_DECL_KEYS)))
            if k in paths:
                raise ProjectPathsError("%s:%d paths.%s 重复" % (label, i, k))
            paths[k] = v
        elif section == "project":
            # The entry fields' shape belongs to the loader; here we only grab the first
            # item of the dirs list (an absolute path) as the resolution base
            if main_dir is None:
                m_item = re.match(r"^\s+-\s+(.+)$", line)
                if m_item and m_item.group(1).strip().startswith("/"):
                    main_dir = m_item.group(1).strip()
        else:
            raise ProjectPathsError("%s:%d 缩进行出现在任何顶层键之前（结构不合法）" % (label, i))
    if schema is None:
        raise ProjectPathsError("%s: schema: 缺失（版本是接入前提，不猜）" % label)
    if schema != "v1":
        raise ProjectPathsError("%s: schema 版本不支持：声明 %s，支持集 {v1}" % (label, schema))
    return paths, main_dir


def _decl_rel(key: str, v: str, label: str) -> str:
    """Validate a paths declaration value (contract ①d): a non-empty relative path;
    absolute / out-of-bounds / non-scalar are forbidden."""
    v = v.strip()
    if not v:
        raise ProjectPathsError("%s: paths.%s 声明值为空或纯空白（strip 后判空，畸形）" % (label, key))
    if v[:1] in "{[":
        raise ProjectPathsError("%s: paths.%s 声明值非标量: %s" % (label, key, v[:40]))
    if v.startswith(("/", "~")) or (len(v) > 1 and v[1] == ":"):
        raise ProjectPathsError("%s: paths.%s 必须是相对项目根的路径，见绝对路径: %s" % (label, key, v[:60]))
    if any(p == ".." for p in pathlib.PurePosixPath(v).parts):
        raise ProjectPathsError("%s: paths.%s 禁止 .. 越界: %s" % (label, key, v))
    return v


def _decl_routes_path(key: str, v: str, label: str) -> str:
    """paths.model_routes 专用声明校验（t260910-14 解析放宽）：相对路径语义不变；
    额外允许机器级形态——`~/…`（展开到当前用户家）与绝对路径（含 Windows 盘符）。
    展开后仍拒绝 `..` 逃逸与空/非标量。返回原声明串（解析成绝对路径由调用方做）。"""
    v = v.strip()
    if not v:
        raise ProjectPathsError("%s: paths.%s 声明值为空或纯空白（strip 后判空，畸形）" % (label, key))
    if v[:1] in "{[":
        raise ProjectPathsError("%s: paths.%s 声明值非标量: %s" % (label, key, v[:40]))
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]  # 引号包裹的标量：剥引号后判空/解析（与 TS 解析器同判，t260910-14）
        if v == "":
            raise ProjectPathsError("%s: paths.%s 声明值为空（strip 后判空，畸形）" % (label, key))
    if any(p == ".." for p in pathlib.PurePosixPath(v).parts):
        raise ProjectPathsError("%s: paths.%s 禁止 .. 越界（机器级形态同样适用）: %s" % (label, key, v))
    return v


def _resolve_decl_routes_path(v: str) -> pathlib.Path:
    """把 _decl_routes_path 放行的声明值解析成绝对路径：`~`/绝对 → expanduser 后原样；
    相对 → 调用方拼项目主目录（project_paths 内 base / v）。"""
    if v == "~" or v.startswith("~/"):
        return pathlib.Path(v).expanduser()
    if pathlib.PurePosixPath(v).is_absolute() or (len(v) > 1 and v[1] == ":"):
        return pathlib.Path(v)
    return pathlib.Path(v)  # 相对：由调用方拼 base


def project_paths(project_key: str, roles_base: str = "",
                  routes_base: str = "") -> Dict[str, Any]:
    """Read the paths section of a registered entry's project.yaml (contract ①d's only
    read entry point). Returns:
      {"roles_dir": Path|None, "roles_rel": str|None,
       "model_routes": Path|None, "model_routes_rel": str|None,
       "inspection_decl": Path|None, "inspection_decl_rel": str|None,
       "dsh_bin": Path|None, "dsh_bin_rel": str|None, "main_dir": str|None}

    Undeclared (any of the four fallback classes) → both the Path and the rel are None and
    the consumer falls back to the current convention; declared → the resolved absolute
    path (roles_base defaults to os.getcwd(), routes_base to the entry's dirs[0]). This
    function only does 「parsing and declared-value validation」 — anchor existence / kind
    decisions belong to each consumer's helper (roles_dir_for_spawn /
    routes_file_for_spawn, so the judging base and the real consumption base share a
    source and consuming one key cannot misjudge the other key's anchor). The entry file is
    parsed only when it exists and the key is legal — a broken file = ProjectPathsError,
    never a silent fallback. roles_base / routes_base are test injection points
    (production call sites pass only roles_base=str(cwd))."""
    key = str(project_key or "").strip()
    info: Dict[str, Any] = {"roles_dir": None, "roles_rel": None,
                            "model_routes": None, "model_routes_rel": None,
                            "inspection_decl": None, "inspection_decl_rel": None,
                            "dsh_bin": None, "dsh_bin_rel": None,
                            "workflow_modules": None, "workflow_modules_rel": None,
                            "main_dir": None, "entry": None}
    if not key or not PROJECT_KEY_RE.match(key):
        return info
    entry = perkey_projects_root() / key / "project.yaml"
    if not entry.is_file():
        return info
    label = str(entry)
    info["entry"] = label
    try:
        text = entry.read_text("utf-8")
    except UnicodeDecodeError as e:
        raise ProjectPathsError("%s 非 UTF-8 不可解析（fail-closed，契约①d）：%s" % (label, str(e)[:120]))
    except OSError as e:
        raise ProjectPathsError("%s 不可读（fail-closed，契约①d）：%s" % (label, str(e)[:200]))
    paths, main_dir = _entry_paths_parse(text, label)
    info["main_dir"] = main_dir
    if not paths:
        return info
    if "model_routes" in paths:
        base = routes_base or main_dir
        if not base:
            raise ProjectPathsError(
                "%s: paths.model_routes 已声明但条目缺可用 dirs 首项，无法定项目主目录（畸形）" % label)
        raw = _decl_routes_path("model_routes", paths["model_routes"], label)
        resolved = _resolve_decl_routes_path(raw)
        if resolved.is_absolute():
            info["model_routes"] = resolved          # 机器级/绝对形态（t260910-14 放宽）
        else:
            info["model_routes"] = pathlib.Path(base) / resolved  # 相对：项目主目录下，语义不变
        info["model_routes_rel"] = raw
    if "inspection_decl" in paths:
        # 巡检声明落位指路（t260916-02）：与 model_routes 同一机器级放宽口径（~/…、绝对、
        # 相对拼项目主目录）；校验词法照抄 _decl_routes_path，但**回落语义不照抄**——
        # 路由表缺文件是分态软回落+兜底表（KI-030 收窄口径），巡检声明的缺席=「该项目
        # 无巡检面」（absent 响应语义）、坏形/不可读=消费侧项目级显式降级点名。锚点判定
        # 归消费方（inspection_decl.resolve_project_decl_path，四态表同款 fail-closed）。
        base = routes_base or main_dir
        if not base:
            raise ProjectPathsError(
                "%s: paths.inspection_decl 已声明但条目缺可用 dirs 首项，无法定项目主目录（畸形）" % label)
        raw = _decl_routes_path("inspection_decl", paths["inspection_decl"], label)
        resolved = _resolve_decl_routes_path(raw)
        if resolved.is_absolute():
            info["inspection_decl"] = resolved          # 机器级/绝对形态（同 t260910-14 放宽）
        else:
            info["inspection_decl"] = pathlib.Path(base) / resolved  # 相对：项目主目录下
        info["inspection_decl_rel"] = raw
    if "dsh_bin" in paths:
        # dsh 二进制路径钉（t260921-14）：与 model_routes 同一机器级放宽口径（~/…、绝对、
        # 相对拼项目主目录）；校验词法照抄 _decl_routes_path，但**回落语义不照抄路由表**
        # （取舍清单 #14，落 test_t260921_14_dsh_path_pin.py 头注）——缺省（未声明）=裸
        # `dsh` 走 PATH，本身是完整配置非降级；声明在场=消费侧 fail-closed（锚点缺失/
        # 类型错位/不可执行=红，见 dsh_bin_for_spawn），绝无「仓内兜底二进制」形态。
        base = routes_base or main_dir
        if not base:
            raise ProjectPathsError(
                "%s: paths.dsh_bin 已声明但条目缺可用 dirs 首项，无法定项目主目录（畸形）" % label)
        raw = _decl_routes_path("dsh_bin", paths["dsh_bin"], label)
        resolved = _resolve_decl_routes_path(raw)
        if resolved.is_absolute():
            info["dsh_bin"] = resolved          # 机器级/绝对形态（同 t260910-14 放宽）
        else:
            info["dsh_bin"] = pathlib.Path(base) / resolved  # 相对：项目主目录下
        info["dsh_bin_rel"] = raw
    if "roles_dir" in paths:
        rel = _decl_rel("roles_dir", paths["roles_dir"], label)
        info["roles_dir"] = pathlib.Path(roles_base or os.getcwd()) / rel
        info["roles_rel"] = rel
    if "workflow_modules" in paths:
        # 项目外置工作流模板模块清单（t260924-04）：`,` 分隔多项，每项相对项目主目录
        # （dirs[0]）——不放行机器级形态；逐项校验（空项/绝对/.. 越界/非标量各红，点名
        # 第 N 项）。锚点存在性不在此判（加载器按「加载失败」拒收点名，缺锚≠静默跳过）。
        base = main_dir
        if not base:
            raise ProjectPathsError(
                "%s: paths.workflow_modules 已声明但条目缺可用 dirs 首项，无法定项目主目录（畸形）" % label)
        raw_items: List[str] = []
        for i, item in enumerate(str(paths["workflow_modules"]).split(","), 1):
            rel_item = _decl_rel("workflow_modules", item, "%s 第 %d 项" % (label, i))
            raw_items.append(rel_item)
        info["workflow_modules"] = [pathlib.Path(base) / it for it in raw_items]
        info["workflow_modules_rel"] = ",".join(raw_items)
    return info


def _require_anchor(label: str, key: str, p: pathlib.Path, want: str) -> None:
    """Anchor existence/kind decision for a declaration (fail-closed red, naming the
    entry file and the resolved path).
    A missing anchor and a mis-typed anchor are reported separately — the semantics
    differ (①d's four-state table), the red level is the same. Only declared anchors are
    judged; existence of fallback paths belongs to each consumer's existing soft semantics
    (missing while undeclared = a soft skip / tolerance, not a hard failure)."""
    if not p.exists():
        raise ProjectPathsError("%s: paths.%s 声明锚点不存在（fail-closed 红）：%s" % (label, key, p))
    if want == "dir" and not p.is_dir():
        raise ProjectPathsError("%s: paths.%s 声明锚点不是目录（类型错位，fail-closed 红）：%s" % (label, key, p))
    if want == "file" and not p.is_file():
        raise ProjectPathsError("%s: paths.%s 声明锚点不是文件（类型错位，fail-closed 红）：%s" % (label, key, p))


def roles_dir_for_spawn(project_key: str, cwd) -> pathlib.Path:
    """Spawn consumer ①: the role preset patch directory. Declared = project_paths
    parsing + a fail-closed anchor decision; undeclared falls back to
    <cwd>/server/roles (the current convention, the worktree ticket snapshot semantics
    unchanged; a missing directory doesn't blow up here — the soft skip for a missing
    concrete <role>.yml belongs to the call site's existing logic, and declared and
    undeclared are equally soft at this layer)."""
    info = project_paths(project_key, roles_base=str(cwd))
    if info["roles_dir"] is not None:
        _require_anchor(info["entry"], "roles_dir", info["roles_dir"], "dir")
        return info["roles_dir"]
    return pathlib.Path(cwd) / DEFAULT_ROLES_DIR


def dsh_bin_for_spawn(project_key: str) -> Optional[pathlib.Path]:
    """Spawn consumer ④（t260921-14）：dsh 二进制路径钉。未声明 → None（调用方保持裸
    `dsh` 走 PATH 的现状——缺省是完整配置非降级，可见性由 dsh_pin 版本面 info/日志
    点名，不加每-spawn warning 噪声）；声明在场 → 解析 + fail-closed 锚点判定：缺失/
    不是文件/不可执行（os.access X_OK）一律 ProjectPathsError 点名条目与解析后路径。
    翻钉坏了还回落旧 dsh = 票面要防的「同票两段行为分叉」本身，宁红不静默；与
    --version 探测失败两级分明（取舍清单 #10/#13：声明面缺陷红拦 spawn，探测失败=
    观测面照记不拦）。回退 = 删/注释该声明行（引擎层一行回退，票面交付④）。"""
    info = project_paths(project_key)
    p = info["dsh_bin"]
    if p is None:
        return None
    _require_anchor(info["entry"], "dsh_bin", p, "file")
    if not os.access(p, os.X_OK):
        raise ProjectPathsError(
            "%s: paths.dsh_bin 声明锚点不可执行（fail-closed 红；翻钉坏了不回落裸 dsh，"
            "回退=删/注释该声明行）：%s" % (info["entry"], p))
    return p


def routes_file_for_spawn(project_key: str) -> Dict[str, Any]:
    """Spawn consumer ②（t260910-14 重构；t260914-05 兜底分支退役）：路由表解析（真源=
    声明指向文件）。声明缺失/文件缺失/内容坏三态分别可辨且**点名告警**（解析层单点
    WARNING 含 state+path+指纹，消费方再点名「本轮模型=profile 默认」）——agent 仍可跑，
    但绝不静默回落任何仓内兜底表。返回 resolve_routes_table 的判别 dict
    （{"state","declared","path","table","error","fingerprint"}）。roles 锚点不受影响
    （_require_anchor 只剩 roles_dir 消费）。"""
    return resolve_routes_table(project_key)


def roles_rel_for_prompt(project_key: str) -> str:
    """The prompt-assembly consumer: the directory base of role_doc/kind_doc (a relative
    path string).
    Declared = the declared value; undeclared = DEFAULT_ROLES_DIR (the assembled text
    matches pre-change behavior). Anchor existence is not decided here (the prompt is
    only textual guidance; red reports at the spawn-time real consumer); an unparseable
    entry file still fails closed as usual (ProjectPathsError propagates)."""
    info = project_paths(project_key)
    return info["roles_rel"] or DEFAULT_ROLES_DIR


# The archive file-list stance (contract v1.4 ①c appendix; the activity's scan and the
# future consumers share this one source of truth):
#   Archived = .sandbar/stage_*.json (stage results / settle reports),
#   .sandbar/screenshots/**/*.png (UI evidence, relative layout preserved),
#   .dsh/sessions/<repo-slug>/* (session event files).
#   Excluded (recorded in manifest.excluded_rules, never archived) = agent_*.log (worker
#   spawn runtime logs), model_patch_*.yml / resume_patch_*.yml (engine-internal
#   continuation artifacts), .dsh/profiles/** and every .credentials.yaml (credentials
#   are never archived). A missing session directory = handled softly (the manifest
#   records absent), the same degraded stance as the usage endpoint's 「a historical
#   ticket has no session files」.
ARCHIVE_INCLUDE_STAGE_GLOB = DOT_DIR_NEW + "/stage_*.json"
ARCHIVE_INCLUDE_SHOTS_GLOB = DOT_DIR_NEW + "/screenshots/**/*.png"
ARCHIVE_INCLUDE_SESSIONS_DIR = ".dsh/sessions"
ARCHIVE_EXCLUDED_RULES = (
    "agent_*.log（worker spawn 运行时日志）",
    "model_patch_*.yml / resume_patch_*.yml（引擎内部续接物）",
    ".dsh/profiles/**（profile 镜像）",
    "**/.credentials.yaml（凭据绝不入档）",
)


# Template id → console display name (the dev-lane name shares a source
# with DevLaneWorkflow.TEMPLATE_NAME. Host order 260904: only dev-lane remains (the
# other templates retired). t260910-14 注记：原预跑段防幻觉白名单消费面随
# 功能退役，本表其余消费面（工单台展示等）不变。
TEMPLATE_DISPLAY_NAMES: Dict[str, str] = {
    "dev-lane": "开发泳道",
}
if os.environ.get(FIXTURE_TEMPLATES_ENV) == "1":
    # 与 TEMPLATE_CLASS_NAMES 同门（上段）：收窄断言以默认面为准。
    TEMPLATE_DISPLAY_NAMES["fixture-two-step"] = "夹具两段"


# ---- The project registry (the single source of truth, collected here from
# server/tools/ticket.py in ticket t260904-02) ----
# The cause = KI-032: a bare client.py ticket-start did not anchor project_root, so which
# repo a relative lane path landed in was decided by the executing worker's REPO_ROOT
# (a split brain). The hard gate requires client.py and ticket.py to use **the same**
# loader to anchor the project — two copies inevitably drift (the lesson of the three
# incidents t260824-04/-10/-11) — so the whole block was collected here.
# ticket.py keeps a thin shell delegating (external function names and error texts
# verbatim unchanged); client.py imports this section directly.
# This section stays stdlib-only (the established constraint that
# server/tools/ticket.py loads this module directly).
# Note: the json/time imports sit in this section rather than at the file head, so an
# append-style revision doesn't shift every line number (several entries in
# notes/debts/known-issues.md anchor this file by line number).
import json as _json                                # noqa: E402
import time as _time                                # noqa: E402

# The one-time migration source (the old single file). The source of truth = the
# machine-level per-key directory ~/.sandbar/projects/<key>/project.yaml (loading =
# scanning */project.yaml — the same registry as server/project-registry.ts, each side
# with its own minimal parse, semantically isomorphic).
# env priority (read fresh on every call): SANDBAR_PROJECTS_YAML (the legacy single-file
# mode, the old projects: list format) > SANDBAR_PROJECTS_DIR > ~/.sandbar/projects.
# A malformed entry / an unsupported version = that project is isolated (visibly
# fail-closed, other projects unaffected); the directory name must pass the
# PROJECT_KEY_RE whitelist, an entry's key must equal its directory name exactly, and the
# migration test only recognizes the .migrated marker.
PROJECTS_YAML = REPO_ROOT / 'server' / 'projects.yaml'


def registry_root():
    """The per-key registry root directory (env is read fresh on every call, so an env
    set after import still takes effect)."""
    return pathlib.Path(os.environ.get('SANDBAR_PROJECTS_DIR') or (pathlib.Path.home() / '.sandbar' / 'projects'))


def strip_registry_line(raw):
    """Strip a trailing comment + trailing whitespace; return None (skip) for a
    whole-line comment / a blank line. Values in this registry contain no #."""
    line = re.sub(r'#.*$', '', raw).rstrip()
    return line if line.strip() else None


def parse_legacy_registry_file(text, label):
    """The old single-file format parse (a projects: list) — shared by the legacy env
    mode and the migration source; behavior matches the 260823 parseProjectsYaml
    (including the duplicate-key check), and a broken file reports loudly."""
    projects = []
    cur = None
    in_dirs = False
    saw_root = False
    for i, raw in enumerate(text.split('\n'), 1):
        line = strip_registry_line(raw)
        if line is None:
            continue
        if not raw[:1].isspace() and line != 'projects:' and i > 1:
            raise ValueError('%s:%d 顶层只认 projects:' % (label, i))
        if line == 'projects:':
            if saw_root:
                raise ValueError('%s:%d projects: 重复' % (label, i))
            saw_root = True
            continue
        if not saw_root:
            raise ValueError('%s:%d 首行必须是 projects:' % (label, i))
        m_item = re.match(r'^\s+-\s+(.+)$', line)
        m_kv = re.match(r'^\s+([a-z]+):\s*(.*)$', line)
        if m_item:
            content = m_item.group(1).strip()
            kv = re.match(r'^([a-z]+):\s*(.*)$', content)
            if kv:
                if kv.group(1) != 'key' or not kv.group(2):
                    raise ValueError('%s:%d 条目首键必须是 key' % (label, i))
                key = kv.group(2).strip()
                if not PROJECT_KEY_RE.match(key):
                    raise ValueError('%s:%d key 不合法: %s' % (label, i, key))
                cur = {'key': key, 'name': '', 'dirs': []}
                projects.append(cur)
                in_dirs = False
                continue
            if cur is None or not in_dirs:
                raise ValueError('%s:%d 列表项出现位置不对: %s' % (label, i, content))
            if not content.startswith('/'):
                raise ValueError('%s:%d dirs 必须是绝对路径: %s' % (label, i, content))
            cur['dirs'].append(content)
            continue
        if m_kv and cur is not None:
            k, v = m_kv.group(1), m_kv.group(2)
            if k == 'name':
                cur['name'] = v.strip()
                in_dirs = False
                continue
            if k == 'dirs':
                if v.strip():
                    raise ValueError('%s:%d dirs: 后必须换行给列表' % (label, i))
                in_dirs = True
                continue
            raise ValueError('%s:%d 不认的键: %s' % (label, i, k))
        raise ValueError('%s:%d 解析失败: %s' % (label, i, line.strip()))
    if not projects:
        raise ValueError('%s: 没有任何项目条目' % label)
    for p in projects:
        if not p['name']:
            raise ValueError('%s: 项目 %s 缺 name' % (label, p['key']))
        if not p['dirs']:
            raise ValueError('%s: 项目 %s 缺 dirs' % (label, p['key']))
    keys = set(p['key'] for p in projects)
    if len(keys) != len(projects):
        raise ValueError('%s: key 重复' % label)
    return projects


def parse_project_file(text, label):
    """Parse one per-key entry (project.yaml, contract ①'s schema v1 fixed shape):

        schema: v1            (required; missing = malformed; non-v1 = unsupported
                               version, fail-closed)
        project:
          - key: <key>
            name: <name>
            dirs:
              - /abs/path

    Top-level tolerance (additive fields, t260916-21): paths: and admin_log: sections
    pass through unparsed — old readers never break when a new field lands (the admin_log
    block's semantics live in engine audit.py's config reader; this loader only tolerates
    its presence).

    The key whitelist check happens here; verifying that the key equals the directory
    name is the loader's job."""
    cur = None
    in_dirs = False
    saw_project = False
    in_paths = False   # ①d: the top-level paths: section passes through the loader unparsed (semantics / anchors are fail-closed in
    in_admin_log = False  # t260916-21: the top-level admin_log: section (admin.log 轮转面配置，additive 字段)
    schema = None      # shared.project_paths's ①d reader)
    for i, raw in enumerate(text.split('\n'), 1):  # the shape of fields inside project: belongs to the loader
        line = strip_registry_line(raw)
        if line is None:
            continue
        if in_paths:
            if raw[:1].isspace():
                continue    # a line inside the paths section: pass through (the ①d reader owns shape and anchors)
            in_paths = False    # a non-indented line = the paths section is over, back to normal top-level handling
        if in_admin_log:
            if raw[:1].isspace():
                continue    # a line inside the admin_log section: pass through (audit.py 的配置读面 owns shape——engine 读「引擎所属项目」条目，宿主 260916 定稿)
            in_admin_log = False
        if line == 'paths:':
            in_paths = True
            continue
        if line == 'admin_log:':
            in_admin_log = True
            continue
        if not raw[:1].isspace() and line != 'project:' and not line.startswith('schema:') and i > 1:
            raise ValueError('%s:%d 顶层只认 schema:/project:/paths:/admin_log:' % (label, i))
        if line == 'project:':
            if saw_project:
                raise ValueError('%s:%d project: 重复' % (label, i))
            saw_project = True
            continue
        m_top = re.match(r'^([a-z]+):\s*(.+)$', line)
        if m_top and not saw_project and not raw[:1].isspace():
            if m_top.group(1) != 'schema':
                raise ValueError('%s:%d 顶层只认 schema: 与 project:' % (label, i))
            schema = m_top.group(2).strip()
            if schema != 'v1':
                raise ValueError('%s:%d schema 版本不支持：声明 %s，支持集 {v1}' % (label, i, schema))
            continue
        if not saw_project:
            raise ValueError('%s:%d 顶层只认 schema: 与 project:' % (label, i))
        m_item = re.match(r'^\s+-\s+(.+)$', line)
        m_kv = re.match(r'^\s+([a-z]+):\s*(.*)$', line)
        if m_item:
            content = m_item.group(1).strip()
            kv = re.match(r'^([a-z]+):\s*(.*)$', content)
            if kv:
                if cur is not None:
                    raise ValueError('%s:%d 单条目文件出现第二个条目' % (label, i))
                if kv.group(1) != 'key' or not kv.group(2):
                    raise ValueError('%s:%d 条目首键必须是 key' % (label, i))
                key = kv.group(2).strip()
                if not PROJECT_KEY_RE.match(key):
                    raise ValueError('%s:%d key 不合法: %s' % (label, i, key))
                cur = {'key': key, 'name': '', 'dirs': []}
                in_dirs = False
                continue
            if cur is None or not in_dirs:
                raise ValueError('%s:%d 列表项出现位置不对: %s' % (label, i, content))
            if not content.startswith('/'):
                raise ValueError('%s:%d dirs 必须是绝对路径: %s' % (label, i, content))
            cur['dirs'].append(content)
            continue
        if m_kv and cur is not None:
            k, v = m_kv.group(1), m_kv.group(2)
            if k == 'name':
                cur['name'] = v.strip()
                in_dirs = False
                continue
            if k == 'dirs':
                if v.strip():
                    raise ValueError('%s:%d dirs: 后必须换行给列表' % (label, i))
                in_dirs = True
                continue
            raise ValueError('%s:%d 不认的键: %s' % (label, i, k))
        raise ValueError('%s:%d 解析失败: %s' % (label, i, line.strip()))
    if schema is None:
        raise ValueError('%s: schema: 缺失（版本是接入前提，不猜）' % label)
    if cur is None:
        raise ValueError('%s: 没有任何项目条目' % label)
    if not cur['name']:
        raise ValueError('%s: 项目 %s 缺 name' % (label, cur['key']))
    if not cur['dirs']:
        raise ValueError('%s: 项目 %s 缺 dirs' % (label, cur['key']))
    return cur


def serialize_registry_project(p, seed_label):
    """Serialize a per-key entry (for migration): a strict subset that round-trips (no #
    / newline in values, verified at migration time)."""
    lines = ['# 由 %s 自动迁移（sandbar M1-1），格式=契约① per-key 注册条目，勿手改' % seed_label,
             'schema: v1', 'project:', '  - key: %s' % p['key'], '    name: %s' % p['name'], '    dirs:']
    lines += ['      - %s' % d for d in p['dirs']]
    return '\n'.join(lines) + '\n'


def scan_registry(root):
    """Scan the registry root: good entries go into projects, bad ones into quarantined
    (visibly fail-closed without killing the whole table)."""
    projects = []
    quarantined = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith('.'):
            continue
        f = child / 'project.yaml'
        if not f.is_file():
            continue  # skip directories with no registry entry (e.g. a data/ placeholder)
        label = str(f)
        if not PROJECT_KEY_RE.match(child.name):
            quarantined.append({'dir': str(child),
                                'error': '%s: 目录名不合法（key 白名单：小写字母/数字/中划线）：%s'
                                         % (label, child.name)})
            continue
        try:
            p = parse_project_file(f.read_text('utf-8'), label)
            if p['key'] != child.name:
                raise ValueError('%s: key 与目录名不等：%s ≠ %s' % (label, p['key'], child.name))
            projects.append(p)
        except ValueError as e:
            quarantined.append({'dir': str(child), 'error': str(e)})
    return projects, quarantined


def migrate_registry(root, seed):
    """One-time migration: the old single file → the per-key directories. tmp + rename for
    an atomic landing; .migrated is created exclusively. Any step failing raises
    (fail-closed); already-landed entries stay where they are, and the next startup hits
    the half-migrated branch and reports it explicitly."""
    seed_label = str(seed)
    projects = parse_legacy_registry_file(seed.read_text('utf-8'), seed_label)
    for p in projects:
        for field, value in [('key', p['key']), ('name', p['name'])] + [('dirs', d) for d in p['dirs']]:
            if '#' in value or '\n' in value:
                raise ValueError('迁移源 %s：项目 %s 的 %s 含 # 或换行，严格子集无法表示，'
                                 '拒绝迁移（请人工改源表）' % (seed_label, p['key'], field))
    root.mkdir(parents=True, exist_ok=True)
    for p in projects:
        d = root / p['key']
        d.mkdir(parents=True, exist_ok=True)
        content = serialize_registry_project(p, seed_label)
        target = d / 'project.yaml'
        # Idempotent: an identical-bytes entry already present is skipped (a second call
        # rewrites nothing; concurrent double migrations also converge)
        if target.is_file() and target.read_text('utf-8') == content:
            continue
        tmp = pathlib.Path(_registry_tmp_name(target))
        tmp.write_text(content, 'utf-8')
        os.replace(tmp, target)
    try:
        fd = os.open(str(root / '.migrated'), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as fh:
            fh.write('source: %s\nmigrated_at: %s\n' % (seed_label, _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())))
    except FileExistsError:
        pass  # a concurrent first start: another process already wrote the marker with equivalent contents, ignore


def _registry_tmp_name(target):
    """A concurrency-safe temp filename with a process-unique suffix (a deterministic tmp
    name gets trampled by concurrent double migrations — after the winner renames, the
    loser hits FileNotFoundError; reproduced in ticket t260901-14's integration test)."""
    return '%s.tmp.%s.%s' % (target, os.getpid(), _time.time_ns())


def _expected_registry_entries(projects, seed_label):
    """The migration expectation table: each seed entry → the exact text migration will
    write (used for the resume-migration equality test)."""
    return {p['key']: serialize_registry_project(p, seed_label) for p in projects}


def _resume_registry_migration(root, expected, on_disk_keys):
    """Resume the migration: only write the seed entries that are missing (entries already
    on disk are left alone, so manual edits are never overwritten), then add .migrated."""
    for key, content in expected.items():
        if key in on_disk_keys:
            continue
        d = root / key
        d.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(_registry_tmp_name(d / 'project.yaml'))
        tmp.write_text(content, 'utf-8')
        os.replace(tmp, d / 'project.yaml')
    try:
        fd = os.open(str(root / '.migrated'), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as fh:
            fh.write('source: %s\nmigrated_at: %s\n' % (PROJECTS_YAML, _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())))
    except FileExistsError:
        pass  # concurrent: another process already wrote the marker with equivalent contents, ignore


def ensure_registry_migrated(root):
    """A consistency check before loading in per-key mode: the skip test only trusts
    .migrated. With no marker but content in the root, three kinds of scene are told apart
    (a literal 「content without a marker = fail-closed」 would condemn every normally
    hand-registered registry — found during the implementation self-test):
    - a purely manual registry (no intersection between the on-disk keys and the seed, or
      no seed at all) → accept;
    - crash leftovers / a lost marker (everything on disk is an exact text subset of the
      seed entries, nothing quarantined) → resume the migration to fill the gaps + add the
      marker;
    - a mixed scene (partly related but not reproducible) → fail-closed raise, human
      triage, never a silent skip."""
    if (root / '.migrated').is_file():
        return
    projects, quarantined = scan_registry(root)
    on_disk = len(projects) + len(quarantined)
    if on_disk == 0:
        if not PROJECTS_YAML.is_file():
            raise ValueError('注册表根目录不存在：%s，且无迁移源 %s（fail-closed，不静默视为空注册表）'
                             % (root, PROJECTS_YAML))
        migrate_registry(root, PROJECTS_YAML)
        return
    if not PROJECTS_YAML.is_file():
        return  # a purely manual registry: no seed, so there is nothing to judge or migrate from — accept the state
    try:
        expected = _expected_registry_entries(
            parse_legacy_registry_file(PROJECTS_YAML.read_text('utf-8'), str(PROJECTS_YAML)), str(PROJECTS_YAML))
    except ValueError as e:
        raise ValueError('注册表现场无法判定：%s 有 %d 个项目条目但无 .migrated 标记，'
                         '且迁移源 %s 不可解析（%s）。处置：修复或移除迁移源后重试。拒绝静默跳过。'
                         % (root, on_disk, PROJECTS_YAML, e))
    seed_keys = set(expected.keys())
    on_disk_keys = set([p['key'] for p in projects] + [pathlib.Path(q['dir']).name for q in quarantined])
    if not (on_disk_keys & seed_keys):
        return  # a purely manual registry (unrelated to the seed), accept the state
    pure_subset = (not quarantined and all(
        p['key'] in seed_keys
        and (root / p['key'] / 'project.yaml').read_text('utf-8') == expected.get(p['key'])
        for p in projects))
    if pure_subset:
        _resume_registry_migration(root, expected, on_disk_keys)
        return
    raise ValueError('注册表现场无法判定：%s 有 %d 个项目条目、无 .migrated 标记，'
                     '且内容与迁移源 %s 部分相关但不能完全复现（混合现场：可能是崩溃残留叠了人工改动）。'
                     '处置：确认后补写标记、清除该目录重迁，或移除/修复迁移源。拒绝静默跳过。'
                     % (root, on_disk, PROJECTS_YAML))


def load_projects_registry():
    """Load the whole registry, returning (projects, quarantined).
    When the legacy env (SANDBAR_PROJECTS_YAML) is set, the old single-file mode is used
    (no quarantine concept)."""
    legacy = os.environ.get('SANDBAR_PROJECTS_YAML')
    if legacy:
        return parse_legacy_registry_file(pathlib.Path(legacy).read_text('utf-8'), legacy), []
    root = registry_root()
    if not root.is_dir():
        if not PROJECTS_YAML.is_file():
            raise ValueError('注册表根目录不存在：%s，且无迁移源 %s（fail-closed，不静默视为空注册表）'
                             % (root, PROJECTS_YAML))
        migrate_registry(root, PROJECTS_YAML)
    else:
        ensure_registry_migrated(root)
    return scan_registry(root)


def assert_registry_nonempty(projects, quarantined):
    """A single error path for an empty registry (all three branches explicit): no entries
    at all / everything quarantined (with reasons)."""
    if projects:
        return
    if quarantined:
        reasons = '；'.join('%s（%s）' % (q['dir'], q['error']) for q in quarantined)
        raise ValueError('注册表没有任何可用项目条目：全部 %d 条被隔离——%s'
                         % (len(quarantined), reasons))
    raise ValueError('注册表没有任何项目条目')


def list_registered_projects():
    """全量注册项目清单（t260916-02 巡检聚合遍历面）：唯一装载器 `load_projects_registry`
    的薄壳——跳过/隔离/迁移语义**逐字同源**，绝不另造第二套扫描规则（两套规则漂移=遍历面
    虚增/漏计实例）。返回 (projects, quarantined)：
      projects 条目 = {key,name,dirs}（可用条目）；quarantined 条目 = {dir,error}
    （装载失败被隔离的条目——聚合消费方决定如何点名，绝不静默吞）。
    注册表根不存在且无迁移源 = 上游 loader 的 ValueError 原样上抛（fail-closed）。"""
    return load_projects_registry()


def lookup_project(key):
    """Look up a registry project by key; missing/unknown always raise ValueError (no
    defaults). Returns {key,name,dirs}.
    When the key matches a quarantined entry, the error carries the directory + reason
    (visibly fail-closed rather than silently treated as unknown)."""
    if not key or not PROJECT_KEY_RE.match(key):
        raise ValueError('project 不合法（注册表 key 白名单：小写字母/数字/中划线），实际 %r' % (key,))
    projects, quarantined = load_projects_registry()
    assert_registry_nonempty(projects, quarantined)
    for p in projects:
        if p['key'] == key:
            return p
    for q in quarantined:
        if pathlib.Path(q['dir']).name == key:
            raise ValueError('项目 %s 注册条目已隔离：%s：%s' % (key, q['dir'], q['error']))
    known = '、'.join(p['key'] for p in projects)
    raise ValueError('未知项目 %r（已注册：%s）' % (key, known))


def check_paths_under_project(proj, ws, worktree):
    """An explicitly given absolute path must land inside one of the project's registered
    directories (so another project's directory cannot be registered here); relative paths
    are not blocked (the executing side resolves them against the project home)."""
    for label, p in (('workspace', (ws or {}).get('path') or ''), ('worktree', worktree or '')):
        if p.startswith('/') and not any(p == d or p.startswith(d.rstrip('/') + '/') for d in proj['dirs']):
            raise ValueError('%s 路径 %s 不在项目 %s 的注册目录内（%s）'
                             % (label, p, proj['key'], '、'.join(proj['dirs'])))


# ---- Worker ownership fingerprint (KI-033, ticket t260904-02) ----
# A ticket worker registers with an engine-repo fingerprint: the worker writes its own
# meta JSON (the repo_root absolute path), and temporal-tools ensureTicketWorkers reads
# it to detect a foreign repo (warn + refuse the work, never killing someone else's
# process).
# The fingerprint = repo_root's realpath, not git HEAD — successive commits in the same
# repo must not be misjudged as foreign (the supervisor and the worker are often started
# one after the other from the same tree). The pure functions live here (stdlib-only) and
# worker.py keeps only thin wiring.
WORKER_META_VERSION = 1


def worker_meta_payload(repo_root=None, pid=None, dsh_face=None) -> Dict[str, Any]:
    """The meta JSON contents: {version, pid, repo_root, ts} (ts = epoch seconds; the
    field names are the ticket-scenario contract). repo_root goes through realpath (both
    sides of the comparison use the same normalization, so symlink differences cannot
    produce a fake foreign repo).

    dsh_face（t260916-24 版本面）：调用方传入时增列 'dsh' 键（dsh_pin.dsh_face_payload
    的产物，记录本 worker 用的 dsh 版本与来源）；None = 不写该键（既有形状逐字节不变，
    读侧 read_worker_meta_state 只按需取键，增列向后兼容）。"""
    root = os.path.realpath(str(repo_root if repo_root is not None else REPO_ROOT))
    payload = {
        'version': WORKER_META_VERSION,
        'pid': int(pid if pid is not None else os.getpid()),
        'repo_root': root,
        'ts': int(_time.time()),
    }
    if dsh_face is not None:
        payload['dsh'] = dsh_face
    return payload


def write_worker_meta(path, repo_root=None, pid=None, dsh_face=None) -> Optional[Dict[str, Any]]:
    """Best-effort meta write (the ownership fingerprint is an observability enhancement;
    a write failure never blocks the worker from starting — the ensure side handles the
    missing state as unknown and cannot misjudge a foreign repo because of it). Returns
    the payload."""
    payload = worker_meta_payload(repo_root=repo_root, pid=pid, dsh_face=dsh_face)
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name('%s.tmp.%d' % (p.name, payload['pid']))
        tmp.write_text(_json.dumps(payload, ensure_ascii=False), 'utf-8')
        os.replace(tmp, p)
        return payload
    except OSError:
        return payload


def read_worker_meta_state(path) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Read the meta, returning (meta|None, state, detail). Four states:
    ok / missing (the file isn't there) / malformed (broken JSON or the wrong shape) /
    read_error (any other read failure).
    Failure states are reported separately so the ensure side can locate the problem when
    it skips compatibly (no going mute)."""
    try:
        raw = pathlib.Path(path).read_text('utf-8')
    except FileNotFoundError:
        return None, 'missing', '文件不存在：%s' % path
    except OSError as e:
        return None, 'read_error', '%s: %s' % (type(e).__name__, e)
    try:
        data = _json.loads(raw)
    except ValueError as e:
        return None, 'malformed', 'JSON 不可解析：%s' % e
    if not isinstance(data, dict) or not isinstance(data.get('repo_root'), str) \
            or not data.get('repo_root') or not isinstance(data.get('pid'), int) \
            or isinstance(data.get('pid'), bool):
        return None, 'malformed', '形状不符（需 version/pid:int/repo_root:str）'
    return data, 'ok', ''


def engine_venv_python(repo_root) -> Optional[pathlib.Path]:
    """Resolve the engine venv interpreter (ticket t260907-10's directory restructure
    fallback chain).

    The new path server/engine/.venv wins; it falls back to the old path
    server/dsh/temporal-poc/.venv (engine-venv-compat fallback; one migration-window round — the old path lives on for
    a while before and after the main tree's .venv is physically moved; once the fallback
    is removed this function degenerates to a single path).
    Malformed input fails closed: a nonexistent / non-directory repo_root, a candidate
    that isn't a regular file, or a non-executable one → None, and the caller reports the
    error explicitly or falls back to the system interpreter rather than silently
    pretending it works.
    """
    base = pathlib.Path(repo_root)
    for rel in (("server", "engine"), ("server", "dsh", "temporal-poc")):
        cand = base.joinpath(*rel) / ".venv" / "bin" / "python"
        try:
            if cand.is_file() and os.access(str(cand), os.X_OK):
                return cand
        except OSError:
            continue
    return None


# ---- worker 停机取消的归因面（t260916-29）----
# 缺陷链：票专属 worker 是 console 子进程；修复前 Worker 未设 graceful_shutdown_timeout
# （SDK 缺省 0=立即取消），console 重启/重载 → 全部子 worker SIGTERM → 在飞 agent 活动
# 被立即取消，阶段机把取消统一报成无信息的「agent 活动故障（已重试）」。本节是工作流侧
# 的归因/文案/重跑纯函数（stdlib-only）；活动侧「取消→ApplicationError」转换在
# agent_activities.worker_termination_guard，worker 侧宽限配置在
# worker.graceful_shutdown_timeout_sec。

WORKER_TERMINATED_ERROR_TYPE = "worker_terminated"
"""activity 侧把「worker 停机/重载致取消」转成的 ApplicationError.type。工作流侧
classify_worker_termination 只认这个 type；其余一切失败（限流/传输/代码故障/心跳超时/
兄弟边被杀等）都不得落此类。"""

WORKER_SHUTDOWN_RETRY_PATCH_ID = "agent-stage-worker-shutdown-retry"
"""重跑兜底的 boolean patched 门（家族规则见 dev_lane 第一个 PATCH_ID 注）：在途老
history 重放恒 False，控制流变更（重跑一次）对老实例不可见，否则重放命令序歧变。"""


def classify_worker_termination(exc) -> bool:
    """判断工作流侧捕到的异常是否「worker 停机（停机/重载）致取消」。

    判据：沿 ActivityError.cause / __cause__ 链找 type==WORKER_TERMINATED_ERROR_TYPE
    的 ApplicationError。鸭子类型只认 `.type` 属性——本模块不 import temporalio
    （shared.py 须保持 stdlib-only：ticket_worker.py 在无 SDK 的系统 python 下按
    文件路径直载本文件）。畸形输入（None、非异常对象、cause 挂野对象、cause 成环、
    超深链）一律 False 不炸——归因只在证据充分时成立，宁可归「活动故障」也不冒认
    「worker 终止」（KI-093「兄弟边被杀」症状是普通活动失败，不得被洗成 worker 停机）。
    """
    seen = set()
    depth = 0
    cur = exc
    while cur is not None and depth < 8:
        key = id(cur)
        if key in seen:
            return False  # cause 成环=证据不充分，不归因
        seen.add(key)
        if getattr(cur, "type", None) == WORKER_TERMINATED_ERROR_TYPE:
            return True
        nxt = getattr(cur, "cause", None)
        if nxt is None:
            nxt = getattr(cur, "__cause__", None)
        cur = nxt
        depth += 1
    return False


def format_agent_stage_failure(ticket_id, stage_id, exc, gen=None) -> str:
    """agent 段活动异常 → 票面 blocked 文案（全部 catch 位的唯一出口）。

    worker 停机致取消 → 「worker 被外部终止（停机/重载），活动已取消（票 X 段 Y
    第 N 次）」——绝不与限流/传输/代码故障混淆（t260916-29 要求②）；其余逐字维持
    旧文案「agent 活动故障（已重试）：<类型>: <信息>」。本函数只改文案不改控制流，
    对在途实例 replay 安全；改控制流的重跑兜底走 retry_once_on_worker_termination
    （patched 门内）。gen=None 省略次数字段（并行边等不便取代数的点位）。
    """
    if classify_worker_termination(exc):
        gen_part = "" if gen is None else "，第 %s 次" % gen
        return ("worker 被外部终止（停机/重载），活动已取消（票 %s 段 %s%s）"
                % (ticket_id, stage_id, gen_part))
    return "agent 活动故障（已重试）：%s: %s" % (type(exc).__name__, exc)


async def retry_once_on_worker_termination(run_once, *, gate, on_retry=None):
    """在飞 agent 活动被 worker 停机取消 → 自动重跑一次（t260916-29 要求④）。

    run_once：零参异步 callable（封好一次 execute_activity 及其超时/重试策略）；
    gate：调用方传入 workflow.patched(WORKER_SHUTDOWN_RETRY_PATCH_ID) 的结果——
    控制流变更必须在 patched 门内，老 history 重放恒 False 永不重跑。仅当
    「gate 开 且 classify_worker_termination 为真」才重跑一次；第二次仍失败或任何
    其它异常原样抛出（调用方 catch 位落 blocked 文案）。工作流自身的取消
    （CancelledError 是 BaseException）不进 except Exception，取消语义不吞。
    """
    try:
        return await run_once()
    except Exception as e:
        if not gate or not classify_worker_termination(e):
            raise
        if on_retry is not None:
            on_retry(e)
        return await run_once()


# ============================================================================
# 项目外置工作流模板面（t260924-04，票 1）：shared 侧名面 glue。
# 真源 = project_templates.scan()（参数注入式，本模块绝不反向 import 它——
# ticket.py 以 '_poc_shared' 别名 spec 装载本模块，别名双装载下 import shared
# 会裂出第二套表）。名面（源码扫描，stdlib）在此模块级并入两表；类面（引擎 venv
# importlib 全量）由 workflows_v2 import 时经 project_template_classes_merged
# 并入并回写两表（深检拒掉的 id 撤下）——引擎进程内两表恒一致，交叉自检不破。
# ============================================================================

PROJECT_TEMPLATE_REJECTIONS: List[Dict[str, str]] = []


def _load_project_templates_mod():
    """按路径装载 project_templates（与 ticket.py 装载本模块同款 spec 手法；正常
    import 环境下 sys.modules 已有真名则直接复用，两路同模块零裂变）。"""
    import sys as _sys
    existing = _sys.modules.get("project_templates")
    if existing is not None:
        return existing
    import importlib.util as _ilu
    path = POC_DIR / "project_templates.py"
    spec = _ilu.spec_from_file_location("_poc_project_templates", path)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["_poc_project_templates"] = mod
    spec.loader.exec_module(mod)
    return mod


def project_template_scan(import_classes: bool, root=None):
    """项目外置模板扫描（依赖全部注入；root=None 用真实注册根——env 现读语义）。
    root 注入 = 测试钉面：扫描期间临时指 SANDBAR_PROJECTS_DIR（perkey_projects_root
    与 project_paths 均按 env 现读语义取根，指 env 一处即两处同源），完毕恢复。"""
    pt = _load_project_templates_mod()
    old_env = os.environ.get("SANDBAR_PROJECTS_DIR")
    if root is not None:
        os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    try:
        if root is None:
            keys = [p["key"] for p in load_projects_registry()[0]]
        else:
            rootp = pathlib.Path(root)
            keys = sorted(d.name for d in rootp.iterdir()
                          if d.is_dir() and (d / "project.yaml").is_file()
                          and PROJECT_KEY_RE.match(d.name)) if rootp.is_dir() else []
        # t260924-04 打回修复（arbitrate D1）：传给 scan 的「先占方」必须是内置∪夹具
        # 快照（_PT_BUILTIN_KEYS，glue 并入前钉），**不得**是已被名面 glue 并入项目
        # id 的现表——否则类面扫描把本项目自己的 id 当占用方，外置模板全量自撞拒收、
        # v2 合并恒空（D2 标签失真同根因）。
        _bn = {k: v for k, v in TEMPLATE_CLASS_NAMES.items() if k in _PT_BUILTIN_KEYS}
        _bd = {k: v for k, v in TEMPLATE_DISPLAY_NAMES.items() if k in _PT_BUILTIN_KEYS}
        return pt.scan(perkey_root=lambda: pathlib.Path(root) if root else perkey_projects_root(),
                       project_keys=lambda: keys,
                       resolve_decl=lambda k: project_paths(k),
                       engine_dir=POC_DIR,
                       builtin_names=_bn,
                       builtin_displays=_bd,
                       part_kinds=PART_KINDS,
                       import_classes=import_classes)
    finally:
        if root is not None:
            if old_env is None:
                os.environ.pop("SANDBAR_PROJECTS_DIR", None)
            else:
                os.environ["SANDBAR_PROJECTS_DIR"] = old_env


def project_template_names_merged(root=None) -> Dict[str, str]:
    """合并视图：内置∪夹具∪项目名面登记（不加载类；测试注入 root 钉默认面）。

    260925 修（兑现本函数自己的契约——文档承诺「注入 root 时本机真实注册表有/无登记
    都不影响断言」）：起点按注入态分岔。root 注入=测试/自检钉面，起点取**内置∪夹具
    快照 `_PT_BUILTIN_KEYS`**；若沿用活的 `TEMPLATE_CLASS_NAMES`，导入期名面 glue 已把
    本机真实登记的项目 id 并进该表 → 注入形同虚设（t260924-04 的 A2/默认面收窄两锁在
    「机器上有注册」时必红：t260925 复原 nusuyou 声明即触发）。root=None 走真实语义，
    起点仍是活表（含 glue 并入项），行为逐字不变。"""
    if root is not None:
        names = {k: v for k, v in TEMPLATE_CLASS_NAMES.items() if k in _PT_BUILTIN_KEYS}
    else:
        names = dict(TEMPLATE_CLASS_NAMES)
    res = project_template_scan(import_classes=False, root=root)
    res.merged_names(names, {})  # display 表不动（仅测试视图用）
    return names


def project_template_classes_merged(root=None):
    """类面合并（引擎 venv 专用，workflows_v2 import 时调用）：全量加载＋形状深检，
    深检结果回写 shared 两表（撤下名面已并入但深检拒掉的 id），拒收清单更新到
    PROJECT_TEMPLATE_REJECTIONS。返回 ScanResult（.classes = id → 类）。"""
    global PROJECT_TEMPLATE_REJECTIONS
    res = project_template_scan(import_classes=True, root=root)
    PROJECT_TEMPLATE_REJECTIONS = res.rejections
    # 回写对象 = 内置∪夹具（_PT_BUILTIN_KEYS，模块级名面并入前钉快照）之外的名面项
    res.reconcile(TEMPLATE_CLASS_NAMES, TEMPLATE_DISPLAY_NAMES,
                  builtin_keys=set(_PT_BUILTIN_KEYS))
    return res


def project_template_rejection_note(project_key: str = "", root=None) -> str:
    """建票文案的拒收明细段（fail-closed 点名：检查项＋双方/缺什么）。project_key
    给定时只点名该项目（无 project 调用面给全量）。无拒收 = 空串（文案逐字不变）。"""
    rejs = PROJECT_TEMPLATE_REJECTIONS
    if root is not None:  # 测试/名面即时视图
        rejs = project_template_scan(import_classes=False, root=root).rejections
    if project_key:
        rejs = [r for r in rejs if r.get("project") == project_key]
    if not rejs:
        return ""
    return "；项目模板拒收明细：" + "；".join(
        "[%s/%s] %s：%s" % (r.get("project", ""), r.get("module", ""),
                            r.get("check", ""), r.get("detail", ""))
        for r in rejs)


# 模块级名面并入（置于本段末：perkey_projects_root / project_paths /
# load_projects_registry 均已定义）。加载器自身故障不炸 import——转结构化拒收记录
# 高声挂在建票文案面（「拒收≠装死」；绝不静默当「未声明」）。
_PT_BUILTIN_KEYS = frozenset(TEMPLATE_CLASS_NAMES)
# t260926-03（KI-123）：内置∪夹具快照的公开别名——ticket.py create 模板闸用它判
# 「内置快路径（不 spawn 权威面查询）」，杜绝工具面硬编码模板名（KI-124 同纪律：
# client.py 源码锁 `== "dev-lane"` 残留即红的既有约定，同款不落 ticket.py）。
BUILTIN_TEMPLATE_KEYS = _PT_BUILTIN_KEYS
try:
    _pt_res = project_template_scan(import_classes=False)
    PROJECT_TEMPLATE_REJECTIONS = _pt_res.rejections
    _pt_res.merged_names(TEMPLATE_CLASS_NAMES, TEMPLATE_DISPLAY_NAMES)
except Exception as _pt_err:  # 加载器故障：点名挂账，不静默、不炸共享装载
    PROJECT_TEMPLATE_REJECTIONS = [{"project": "", "module": "",
                                    "check": "加载器故障",
                                    "detail": str(_pt_err)[:240]}]
