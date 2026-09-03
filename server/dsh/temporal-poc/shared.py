"""Temporal POC 公共配置与数据契约。

260823 多项目化清理：工单真源恒为 **Temporal workflow**（v2 模版即代码，base.py 六子类）；
旧 tickets/*.json 投影目录、老 TicketWorkflow/adopt 链已删除。workflow id = 工单 id（单例）；
项目区分 = ProjectKey search attribute（ticket-start 打标，ticket-list --project 过滤）。

保留步1 的 ContentPipelineWorkflow / DispatcherScanWorkflow 与 demo 数据契约（向后兼容）。

路径可被环境变量覆盖（自测用临时目录）：
  SUYOU_WORKFLOWS_DIR  模板目录（缺省 <repo>/server/dsh/workflows）
"""

from __future__ import annotations

import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---- 路径 ----
POC_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[2]          # server/dsh/temporal-poc -> 仓库根
ADMIN_PY = REPO_ROOT / "server" / "admin.py"
WORKFLOWS_DIR = pathlib.Path(os.environ.get("SUYOU_WORKFLOWS_DIR") or (REPO_ROOT / "server" / "dsh" / "workflows"))
OUT_DIR = POC_DIR / "out"

# ---- Temporal 接入点 ----
# 可被环境变量覆盖（测试环境走 Docker 独立 Temporal，见 docs/testing-guide.md）：
#   SUYOU_TARGET_HOST    Temporal gRPC 地址（缺省生产 127.0.0.1:7233）
#   SUYOU_NAMESPACE      Temporal namespace（缺省 default）
TARGET_HOST = os.environ.get("SUYOU_TARGET_HOST") or "127.0.0.1:7233"
NAMESPACE = os.environ.get("SUYOU_NAMESPACE") or "default"
TASK_QUEUE = os.environ.get("SUYOU_TASK_QUEUE") or "suyou-poc"

# ---- 每工单专属 worker（260824 用户拍板）----
# 工单 workflow 不上共享队列：每张工单一个 task queue（suyou-ticket-<工单id>）+
# 一个专属 worker 进程（ticket create 时拉起，workflow 收口后自退，巡检兜底救/收）。
# 共享队列 suyou-poc 只留不属任何工单的 workflow（dispatcher-scan / content-pipeline）。
# 隔离语义：A 工单的旧代码 worker 永远抢不到 B 工单的任务（260824 版本投毒事件教训）。
TICKET_QUEUE_PREFIX = "suyou-ticket-"


def ticket_task_queue(ticket_id: str) -> str:
    """工单专属 task queue 名（workflow 启动与专属 worker 轮询用同一个，两边不漂移）。"""
    return TICKET_QUEUE_PREFIX + ticket_id

# ---- 多项目化（260823）：工单 workflow 按项目区分，同一个 Temporal 后端 ----
# ProjectKey = Keyword search attribute，值 = 机器级 per-key 注册表 key
# （真源 ~/.sandbar/projects/<key>/project.yaml，sandbar M1-1 出仓；见 server/tools/ticket.py
# 「项目注册表」节与 server/dsh/suyou-projects.ts，三处同一注册表口径）。
# 注册：run_server.sh 启动参数自带；运行中的 server 用
#   bin/temporal operator search-attribute create --name ProjectKey --type Keyword
# 测试环境（docker-compose.test.yml temporalite）启动后同样 operator create 一次。
PROJECT_SA_NAME = "ProjectKey"


def project_search_attributes(project: str):
    """构造 ProjectKey typed SA（start_workflow 打标用；ticket-list --project 按它过滤）。
    temporalio 延迟到函数内 import——本模块保持 stdlib-only（server/tools/ticket.py 直载）。"""
    from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes
    return TypedSearchAttributes([SearchAttributePair(SearchAttributeKey.for_keyword(PROJECT_SA_NAME), project)])

# ---- 立项关联（epic-linkage，260824）：工单 workflow 可按立项代号关联 ----
# EpicCode = Keyword search attribute，值 = notes/epics/<代号>.md 的文件主名。
# 注册：run_server.sh 启动参数自带；运行中的 server 用
#   bin/temporal operator search-attribute create --name EpicCode --type Keyword
# 测试环境（docker-compose.test.yml temporalite）启动后同样 operator create 一次。
EPIC_SA_NAME = "EpicCode"
# 立项档案目录（env SUYOU_EPICS_DIR 可覆盖——自测指向临时目录，仿 SUYOU_WORKFLOWS_DIR 先例）。
EPICS_DIR = pathlib.Path(os.environ.get("SUYOU_EPICS_DIR") or (REPO_ROOT / "notes" / "epics"))
# 代号形状白名单：沿用 PROJECT_KEY_RE 字符集，同时防 ../../ 路径穿越。
EPIC_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def validate_epic_code(code: str) -> str:
    """ticket-start --epic 强校验（单点，client.py 调用；ticket.py 只透传不双份实现）。

    空串放行（允许无 epic 工单）→ 返回 ""。形状非法 / 立项档案不存在 → ValueError。
    返回归一后的代号（原样；白名单已约束形状）。
    """
    code = str(code or "").strip()
    if not code:
        return ""
    if not EPIC_CODE_RE.match(code):
        raise ValueError(
            "立项代号形状非法：%r（要求 %s，小写字母/数字/连字符）" % (code, EPIC_CODE_RE.pattern))
    path = EPICS_DIR / (code + ".md")
    if not path.is_file():
        existing = sorted(p.stem for p in EPICS_DIR.glob("*.md")) if EPICS_DIR.is_dir() else []
        raise ValueError(
            "立项代号不存在：%r（%s 无此档案）。现有代号：%s"
            % (code, path, "、".join(existing) if existing else "（目录为空或不存在）"))
    return code


def ticket_search_attributes(project: str, epic: str = ""):
    """构造工单 typed SA：ProjectKey 恒打 + epic 非空加打 EpicCode。
    temporalio 延迟到函数内 import——本模块保持 stdlib-only（server/tools/ticket.py 直载）。"""
    from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes
    pairs = [SearchAttributePair(SearchAttributeKey.for_keyword(PROJECT_SA_NAME), project)]
    if epic:
        pairs.append(SearchAttributePair(SearchAttributeKey.for_keyword(EPIC_SA_NAME), epic))
    return TypedSearchAttributes(pairs)


# ---- 立项下一单预跑（t260828-08）：merge 签字通过后预跑 integration 建议并落缓存 ----
# 缓存真源 = <repoRoot>/.suyou/epic-next/<code>/pre.json；读侧 = workbench
# src/host/epic-next.ts readPrecache（互指同步：改一边必须同步另一边）。
# 与同根 <jobId> 形状的 job 目录共存安全：job 目录清理（epic-next.ts cleanupOldJobs）
# 只删「<code>-<base36时间戳>-<6hex>」形状的目录，<code>/ 子目录不在其列。
# state_key 口径（与 epic-next.ts stateKeyFromRows 互指）：sorted "<id>:closed|open"
# 行以 "\n" 拼接后 sha1 hex；**当前预跑工单一律按 closed 计入**（预跑只发生在 merge
# 签字通过后，本票必然收口；host 读侧点击时工单已 closed，两侧口径对齐——否则缓存
# 永不命中，t260828-08 review 第 2 条）。

def epic_next_precache_path(repo_root, code: str) -> pathlib.Path:
    """预跑缓存文件绝对路径（写侧 agent_activities / 读侧 host epic-next.ts 同口径）。"""
    p = pathlib.Path(repo_root) / ".suyou" / "epic-next" / code
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p / "pre.json"


def epic_state_key(rows: List[Dict[str, Any]], current_ticket_id: str = "") -> str:
    """state_key = sha1(sorted "id:closed|open" 行拼接)（口径见上方区块注释）。"""
    import hashlib
    lines = sorted(
        "%s:%s" % (str(r.get("id") or ""),
                   "closed" if (r.get("closed")
                                or (current_ticket_id and str(r.get("id") or "") == current_ticket_id))
                   else "open")
        for r in rows if str(r.get("id") or ""))
    return hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass
class EpicNextPrepArgs:
    """prepare_epic_next activity 入参：立项代号 + 触发工单（state_key 强制 closed 口径用）。"""

    ticket_id: str
    epic: str


@dataclass
class EpicNextPrepResult:
    """prepare_epic_next 回执：立项全文 + 关联工单行 + state_key，全量内联（workflow 内零 IO）。"""

    exists: bool = False                        # 立项档案存在且可读
    epic_markdown: str = ""                     # notes/epics/<code>.md 全文
    tickets: List[Dict[str, Any]] = field(default_factory=list)  # [{id,status,closed}]
    state_key: str = ""


@dataclass
class EpicNextCache:
    """pre.json 缓存形状（schema 真源；TS 读侧按字段容错读）。"""

    ticket_id: str
    epic: str
    ts: int
    state_key: str
    suggestion: Dict[str, Any]                  # {status:"ok"|"done", ...}


def build_suggest_next_prompt(code: str, epic_markdown: str, tickets_summary: str,
                              workflows: List[Dict[str, str]], result_path: str) -> str:
    """预跑下一单派活指令（纯函数，零 IO）。

    与 workbench src/host/epic-next.ts buildSuggestPrompt 文案互指同步（改一边必须
    同步另一边）；结果契约三态（host validateSuggestion 只认 ok 形态，done/failed
    是 python 侧扩展）：ok 建议下一张工单 / done 立项可完结 / failed 有原因放弃。
    workflows 清单即防幻觉白名单（suggest_next 与 host readPrecache 双侧校验）。
    """
    wf_lines = "\n".join("- %s：%s" % (w.get("id", ""), w.get("name", "")) for w in workflows)
    return """【任务】你是溯游（suyou）项目的 integration 角色。本立项的一张关联工单刚通过人审即将合并，请在合并落账前预判：这个立项下一步最应该开的一张工单是什么（或者是否已经无事可做）。

【硬性要求】
1. 这是只读分析任务：除最后的结果文件外，不创建、不修改任何文件，不做任何 git 写操作。
2. 建议的工单模板必须来自下方「可用工单模板」清单，原样填 id，不得发明。
3. 结论写入结果文件：%s
   UTF-8 JSON，三态之一：
   {"status":"ok","workflow":"<模板id>","title":"<工单标题，一句话说清做什么>","body":"<工单正文：背景、要做什么、验收要点>","rationale":"<给人类看的一句话理由>","write_set":["<预计改动文件，仓库内相对路径，一条一个>"]}
   {"status":"done","summary":"<立项目标已达成的人话说明，给人类确认结项时看>"}
   {"status":"failed","reason":"<放弃原因>"}
4. 写完结果文件即结束，不要等待人类输入，不要开任何工单。

【所属立项】%s（新工单的代号由界面带入，正文无需声明绑定方式）

【立项单全文】
%s

【关联工单实时状态】
%s

【可用工单模板】
%s
""" % (result_path, code, epic_markdown,
       tickets_summary if str(tickets_summary or "").strip() else "（本立项暂无关联工单）",
       wf_lines if wf_lines.strip() else "（清单为空）")


# ---- 集成测试机制（t260829-07 后续，dev-lane 并行开发 ∥ 测试设计）----
# 测试集 = 仓库根 integration/ 目录（**提交的代码资产**，随泳道正常进 main）；
# manifest 契约：integration/manifest.json = [{"name": str, "cmd": str, "cwd": str?}]，
# cmd 以泳道根为 cwd 直接执行（shell 语义由 worker 用 shlex 切分后逐条跑）。
# 保密后置（用户拍板 2026-08-31）：agent 无读沙箱，物理隔离暂不做——developer 的
# prompt/handoffs 不引导、不展示测试集内容即可，沙箱级限制后续再做。

INTEG_DIR_NAME = "integration"
INTEG_MANIFEST = "manifest.json"
MAX_TESTS_FAULT_ROUNDS = 5     # 测试集迭代上限（arbitrate 判 tests-fault 的连续轮数）
MAX_CODE_FAULT_ROUNDS = 5      # 打回 developer 上限（arbitrate 判 code-fault 的累计轮数）
MAX_ACCEPTANCE_ROUNDS = 2      # 验收报告重写上限（报告不合格 → 打回 acceptance 重写）
MAX_REVIEW_ROUNDS = 5          # 方案审读打回上限（review_plan reject 循环；t260903-02 起 review_plan_route 消费）

ARBITRATION_VERDICTS = ("pass", "tests-fault", "code-fault")


@dataclass
class IntegrationRunArgs:
    """run_integration_tests 入参：泳道内按 integration/manifest.json 逐条跑测试。"""

    ticket_id: str
    worktree: str                               # 泳道根（cmd 的 cwd，测试集所在）


@dataclass
class IntegrationRunResult:
    """run_integration_tests 回执：ran 条数 / 通过条数 / 失败明细（截断）/ 原始输出。

    error 非空 = 基础设施/manifest 缺失等启动层失败（未跑任何测试）。"""

    ran: int = 0
    passed: int = 0
    failed: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)  # [{name,cmd,exit,output_tail}]
    error: str = ""


@dataclass
class SettleLaneArgs:
    """settle_lane 入参：汇合点统一代落盘（实现+测试集同 commit）。"""

    ticket_id: str
    worktree: str
    stage_id: str
    gen: int


@dataclass
class SettleLaneResult:
    note: str = ""
    lane_commits: int = -1                      # -1 = 未知（rev-list 失败）
    error: str = ""


def parse_arbitration_summary(summary: str) -> str:
    r"""从 arbitrate agent 的 summary 提取 verdict（FLOW_BRIEF 契约：summary 含
    **唯一** ``verdict=xxx`` 标记则取 xxx，且必须 ∈ ARBITRATION_VERDICTS；
    否则返回 ""。缺失/零个/多个/非法都算格式缺失——多个 verdict=畸形仲裁摘要，
    取任何一个都是猜，与「解析失败由 workflow 侧重跑 arbitrate，不猜」一致
    （t260902-10：由「取首个匹配」改为「唯一匹配否则空串」；调用方 dev_lane
    空 verdict 走格式纠正重试 ≤2 轮再 blocked，安全）。负向断言 (?![\w-])：
    合法值后跟词字符或连字符（如 verdict=pass-fault）不算标记，返回 ""。"""
    hits = re.findall(r"verdict=(pass|tests-fault|code-fault)(?![\w-])", summary or "")
    return hits[0] if len(hits) == 1 else ""


def integration_route(verdict: str, tests_rounds: int, code_rounds: int) -> str:
    """arbitrate 三态路由（纯函数，selfcheck 直测）。返回下一 phase 名或 "blocked:<原因>"。
    上限（用户拍板 2026-08-31）：测试集迭代 / 打回 developer 各 5 轮，超限 blocked 交人。"""
    if verdict == "pass":
        return "acceptance"
    if verdict == "tests-fault":
        return "run_integration_tests" if tests_rounds <= MAX_TESTS_FAULT_ROUNDS else \
            "blocked:测试集迭代 %d 轮超限（上限 %d），转人工判读" % (
                tests_rounds, MAX_TESTS_FAULT_ROUNDS)
    if verdict == "code-fault":
        return "implement" if code_rounds <= MAX_CODE_FAULT_ROUNDS else \
            "blocked:打回 developer %d 轮超限（上限 %d），转人工判读" % (
                code_rounds, MAX_CODE_FAULT_ROUNDS)
    return "blocked:仲裁结论未知 verdict=%r，转人工判读" % verdict


REVIEW_PLAN_VERDICTS = ("pass", "conditional", "reject")


def parse_review_plan_verdict(status: str, summary: str) -> str:
    """review_plan 三态判定（纯函数，selfcheck 直测；t260903-02「附条件放行」）。

    返回 "pass" | "conditional" | "reject"。契约：
    - **status=failed 恒 reject（保守侧）**：结果文件 status 与 summary verdict 标记
      矛盾时（failed + verdict=conditional）不许放行——放行是高风险动作，取保守侧。
    - status=ok 时按 summary 含**唯一** ``verdict=pass|conditional|reject`` 标记判定
      （负向断言 (?![\\w-])，verdict=pass-foo 不算标记）；标记缺/多/非法一律回落
      "pass"（与旧二态 status=ok 行为兼容——旧 agent 输出/旧结果文件无标记不破）。
    - status 其它值（畸形）回落 reject。"""
    if (status or "") == "failed":
        return "reject"
    if (status or "") == "ok":
        hits = re.findall(r"verdict=(pass|conditional|reject)(?![\w-])", summary or "")
        if len(hits) == 1 and hits[0] in REVIEW_PLAN_VERDICTS:
            return hits[0]
        return "pass"
    return "reject"


def review_plan_route(verdict: str, plan_rounds: int) -> str:
    """review_plan 三态路由（纯函数，selfcheck 直测）。返回 "create_plan" |
    "parallel_impl_design" 或 "blocked:<原因>"。

    conditional（附条件放行）不改打回级：与 pass 同样直通实现段，修改意见由调用方
    注入 implement 的 previous_context；不计打回轮数。reject 走既有打回环。"""
    if verdict in ("pass", "conditional"):
        return "parallel_impl_design"
    if verdict == "reject":
        if plan_rounds <= MAX_REVIEW_ROUNDS:
            return "create_plan"
        return "blocked:方案审读打回 %d 轮超限（上限 %d）" % (
            plan_rounds + 1, MAX_REVIEW_ROUNDS)
    return "blocked:审读结论未知 verdict=%r，转人工判读" % verdict


# ---- 单例 workflow id 约定 ----
def pipeline_wf_id(proposal_id: str) -> str:
    """一张提案 = 一个 workflow id。重复 start 会被服务端拒绝（AlreadyStarted）。"""
    return f"content-pipeline:{proposal_id}"


def wf_id(ticket_id: str) -> str:
    """工单 workflow id **就是**工单 id（同一工单同一时刻只可能有一条编排在跑）。"""
    return ticket_id


DISPATCHER_WF_ID = "dispatcher-scan"
SCHEDULE_ID = "suyou-dispatcher-scan"

# ---- demo 用的工单 id 前缀（清场脚本只认这个前缀，绝不碰其它工单）----
DEMO_PREFIX = "t260821-demo-"
DEMO_TICKET = DEMO_PREFIX + "advance"

# ---- 步1 七段状态机（ContentPipelineWorkflow 向后兼容）----
STAGES: List[str] = [
    "propose",
    "approve",        # 人门（signal）
    "process",
    "machine-qc",     # 脚本门（activity 跑真 qc_run）
    "ai-review",
    "final-review",   # 人门（signal）
    "publish",
]

HUMAN_GATES = {"approve", "final-review"}

# ---- 步2：脚本门映射（确定性，写在代码里；stage 机=确定性 workflow 代码）----
# (template_id, stage_id) -> GateSpec。挂在「离开该段前必须跑绿」的段上。
# qc_run scope=all / verify_lane content scope=auto / verify_lane code skip_slow=False。
DEFAULT_SCRIPT_GATES: Dict[str, Dict[str, "GateSpec"]] = {}


def default_gate_for(template_id: str, stage_id: str) -> Optional["GateSpec"]:
    """确定性脚本门：按 (模板, 段) 返回 GateSpec，无则 None。"""
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


# ---- 步1 数据契约（向后兼容）----
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


# ---- 步2 数据契约（TicketWorkflow）----
@dataclass
class EngineCall:
    """一次真实引擎调用：`python3 server/admin.py call <tool> <args-json>`。"""

    tool: str                                  # ticket | workflow | qc_run | verify_lane …
    args: Dict[str, Any] = field(default_factory=dict)
    why: str = ""                              # 进历史的人话


@dataclass
class EngineResult:
    """引擎回执。业务拒绝（ValueError）不抛异常，走 ok=False 交 workflow 判断。"""

    ok: bool
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    run_id: str = ""
    exit_code: int = 0
    cmd: str = ""


@dataclass
class GateSpec:
    """脚本门：跑真实验收脚本，绿才放行。默认 cmd=`admin.py call <tool> <args>`。"""

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
    """人门签字（signal 载荷）。who=签字人身份，由调用方注入，agent 不得自签自己的角色名。"""

    who: str
    gate: str = "approve"          # approve | final-review（或其它 exit=human 段 id）
    decision: str = "approve"      # approve | reject
    note: str = ""


@dataclass
class StageAttempt:
    """agent 试图直接改状态的记录（一律拒绝，留痕）。"""

    who: str
    want_stage: str
    reason: str = ""


# 工单状态机常量（与 server/tools/ticket.py 同口径）
TICKET_STATUSES = ("dispatched", "settled", "verified", "closed", "rework")
TICKET_STAGE_STATES = ("running", "awaiting", "awaiting-human", "blocked")


# ========================================================================================
# M6（t260821-m6-scan-expand）：自治巡检扩权 —— settled/awaiting-human 工单检查报告
#
# 本区契约与纯函数只服务 activity 层（scan_tickets_report / write_scan_report）与自测；
# workflow 体只消费 activity 返回值，不直接读这里的目录/阈值常量做 IO（确定性规约）。
# 建议动作只有三档（可签/待补/疑似卡死）——巡检只出建议不出决定，签字只能人（红线）。
# ========================================================================================

# 报告落盘目录（env 覆盖供自测用临时目录；缺省 POC out/scan，运行产物，gitignore 不入库）。
SCAN_DIR = pathlib.Path(os.environ.get("SUYOU_SCAN_DIR") or (OUT_DIR / "scan"))
# 「疑似卡死」停留时长阈值（小时）。env 可调；activity 读取，不进 workflow 体。
SCAN_STUCK_HOURS = float(os.environ.get("SUYOU_SCAN_STUCK_HOURS") or 48)
# 建议动作三档（report 排序按此序：最紧急在前）。
SCAN_SUGGESTIONS = ("疑似卡死", "待补", "可签")
# 报告红线声明（落进每份报告，台面展示同款）。
SCAN_RED_LINE = "巡检只出建议不出决定；签字只能人（sign who=用户/总管）。"


@dataclass
class ScanTicketItem:
    """一张待决工单的巡检条目（字段即工单台「巡检报告」区的列）。"""

    ticket_id: str
    title: str = ""
    status: str = ""
    stage: str = ""
    stage_state: str = ""
    dwell_hours: float = 0.0                 # 停留时长（距最后一次投影/日志/pending 活动）
    acceptance_done: int = 0                 # 当前段验收清单已勾数
    acceptance_total: int = 0                # 当前段验收清单总数
    pending_count: int = 0                   # 未决 pending 条数
    gate_label: str = ""                     # 最近一次脚本门标签（无则空）
    gate_green: Optional[bool] = None        # 最近一次脚本门红绿灯（None=无记录/不可得）
    suggestion: str = ""                     # 疑似卡死 / 待补 / 可签
    reasons: List[str] = field(default_factory=list)


@dataclass
class ScanReport:
    """一次巡检的完整报告（write_scan_report 落盘 out/scan/<日期>.json）。"""

    generated_at: str
    total_tickets: int
    by_status: Dict[str, int]
    items: List[ScanTicketItem] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)   # 建议动作 → 张数
    stuck_hours: float = SCAN_STUCK_HOURS
    exit_code: int = 0
    # 未归档清单（epic-linkage 验收标准 3）：无 EpicCode 的在途工单 id（sorted）。
    # 允许无 epic 开工单，但巡检要盯到它；closed 不收（历史工单全收只会增殖噪音）。
    unfiled: List[str] = field(default_factory=list)


def is_pending_decision(t: Dict[str, Any]) -> bool:
    """「待决」判定：未 closed 且（status=settled 或 stage_state=awaiting-human）。"""
    if str(t.get("status") or "") == "closed":
        return False
    return (str(t.get("status") or "") == "settled"
            or str(t.get("stage_state") or "") == "awaiting-human")


def _last_activity_ts(t: Dict[str, Any]) -> int:
    """工单最后一次活动时间：投影 updated / log / pending 三者取最大。"""
    ts = int(t.get("updated") or 0)
    for l in (t.get("log") or []):
        if isinstance(l, dict):
            ts = max(ts, int(l.get("ts") or 0))
    for p in (t.get("pending") or []):
        if isinstance(p, dict):
            ts = max(ts, int(p.get("ts") or 0))
    return ts


def gate_from_log(t: Dict[str, Any]) -> Dict[str, Any]:
    """脚本门兜底（Temporal 不可达时）：从工单 log 倒序找「脚本门」记录判红绿灯。"""
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
    """由工单 JSON（show 全量）+ 脚本门信息算巡检条目。纯函数，可脱 Temporal 自测。

    建议规则（只出建议不出决定）：
      1. 停留 ≥ 阈值 → 疑似卡死（最优先，含人门久候）；
      2. awaiting-human → 可签（人门待人签字；验收在签字时由 sign 机械全勾）；
      3. settled：验收未勾齐 / 脚本门最近一次红 → 待补；否则 → 可签（可验收推进）。
    """
    stage = str(t.get("stage") or "")
    acc = [x for x in (t.get("acceptance") or [])]
    checks = []
    if stage and isinstance(t.get("checks"), dict):
        checks = [c for c in (t["checks"].get(stage) or []) if isinstance(c, dict)]
    # 勾选率口径：只数「条目在当前验收清单里」的勾选——历史段残留的孤儿 check
    # （item 不在 acceptance，如 rework 回段后的旧记录）不计入，否则勾选率失真。
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
    """建议动作 → 张数（三档全出现，便于台面直接渲染）。"""
    s: Dict[str, int] = {k: 0 for k in SCAN_SUGGESTIONS}
    for it in items:
        s[it.suggestion] = s.get(it.suggestion, 0) + 1
    return s


# ========================================================================================
# M4/M5（t260821-m45-ticket-engine）：工作空间机制化 + dispatch-next 上下文装配
#
# 本区是**单一真源**：ticket.py（旧引擎路径）与 workflows.py（Temporal TicketWorkflow）
# 的 dispatch-next 生成器都从这里取，两边派活指令不漂移。
# 全部函数只依赖入参与本模块常量（纯函数，可在 workflow sandbox 里确定性执行）。
# ========================================================================================

# dir 类工作空间根：非开发工单（cleanup/运营类）的隔离目录约定 /tmp/suyou-ws/<工单id>。
# （M11 v2：env SUYOU_WS_DIR_BASE 可覆盖——自测指向临时目录，真 /tmp 零污染。）
WS_DIR_BASE = os.environ.get("SUYOU_WS_DIR_BASE") or "/tmp/suyou-ws"

WORKSPACE_TYPES = ("worktree", "dir")


def workspace_of(meta: Dict[str, Any], template_lane: str = "") -> Optional[Dict[str, str]]:
    """工单的工作空间 {type: worktree|dir, path}。

    优先读 meta['workspace']（M4 新字段）；旧工单无此字段时按 lane 推导（worktree 泳道），
    lane=main 且无 workspace → None（主树直改，无独立空间）。向后兼容。
    """
    ws = meta.get("workspace")
    if isinstance(ws, dict) and ws.get("type") in WORKSPACE_TYPES and ws.get("path"):
        return {"type": str(ws["type"]), "path": str(ws["path"])}
    if template_lane == "worktree" and meta.get("worktree"):
        return {"type": "worktree", "path": str(meta["worktree"])}
    return None


# ---- lane=worktree 推导与校验（创建链路单一真源，260825）----
# 三次事故立的规矩（notes/inbox/260824-ticket-start-lane-params.md）：
#   t260824-04 只传 lane=worktree、泳道字段全空 → prepare_workspace 跳过 → agent 空目录空跑；
#   t260824-10 只传裸 worktree/branch 字符串、无 workspace dict → 同样跳过；
#   t260824-11 传了 workspace+branch 漏 worktree 字符串 → merge_check 静默回落主树，
#     「工作区干净」被主树脏文件误伤、verify_lane 测错代码（假绿）。
# 规矩：两条创建路径（server/tools/ticket.py create / client.py ticket-start 裸调）都必须
# 过 derive_lane_workspace，不得再各自推导或透传；workflow 侧再以 lane_workspace_gate_error
# 兜底（防旧 payload/未来新入口绕过创建校验）——宁可 blocked 等人，不静默降级主树/临时目录。
LANE_WORKTREE = "worktree"


def default_lane_paths(ticket_id: str) -> Tuple[str, str]:
    """worktree 泳道默认命名（.worktrees/t<日期>-<别名> / lane/t<日期>-<别名>）。

    中文/长串不进目录与分支名，只留在工单/UI；日期+别名保证确定性且避免撞名；
    纯中文标题 → md5 短哈希兜底。（原 ticket.py _wf_paths，上收为单一真源。）
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
    return ".worktrees/" + wname, "lane/" + wname


def derive_lane_workspace(
        ticket_id: str, template_lane: str, lane: str = "",
        workspace: Optional[Dict[str, str]] = None,
        worktree: str = "", branch: str = "",
        template_workspace_dir: bool = False,
) -> Tuple[str, Optional[Dict[str, str]], str, str]:
    """lane / workspace / worktree / branch 的推导与校验（创建链路单一真源）。

    返回 (lane, workspace, worktree, branch)；非法 → ValueError（创建即拒收，
    把「跑 1.5 小时后才暴露」的错提前到创建瞬间）。规则：
      1. lane = 显式 or 模板 lane。
      2. 显式 workspace 形状必须是 {"type": worktree|dir, "path": 非空}，否则 ValueError。
      3. lane=worktree：
         - workspace 显式给了但 type!=worktree → ValueError（不给静默降级的机会）；
         - workspace.path 与 worktree 字符串都给且不一致 → ValueError（两字段必须同指
           一个泳道：prepare_workspace 用前者、merge_check/merge 用后者，两张皮必出事故）；
         - 缺一补一（path ↔ worktree 互填），都缺 → default_lane_paths 推导；
         - branch 缺省 = lane/<泳道目录名>。
      4. 非 worktree 道 + template_workspace_dir → 缺省 {type:dir, WS_DIR_BASE/<工单id>}；
         否则 workspace 保持 None（主树道直改，无独立空间）。
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
        ws = {"type": "dir", "path": WS_DIR_BASE + "/" + ticket_id}
    return lane, ws, worktree, branch


def lane_workspace_gate_error(meta: Dict[str, Any]) -> str:
    """workflow 侧最后防线：meta 声明 lane=worktree 但泳道字段不齐/不一致 → 错误文案
    （调用方走 blocked 回执拒跑）；齐 → ""。

    创建链路已单点推导+校验（derive_lane_workspace），这里兜「旧工单/手写 payload/
    未来新入口」绕过创建校验的情况——宁可 blocked 等人，不静默降级主树/临时目录。
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
    return ""


# M4③ 显式契约：「一个空间一个 agent / 转移接力」。
#   占用 = 工单 stage_state=running 期间空间有主；
#   转移 = rework / dispatch-next 换 agent，接手方复用同一空间。
OWNERSHIP_CONTRACT = (
    "工作空间契约（M4「一个空间一个 agent / 转移接力」）：\n"
    "  - 占用：本工单 stage_state=running 期间，上述工作空间归你（当前 agent）独占——"
    "不得进入其它工单的泳道/隔离目录，产物也不得写到本空间之外。\n"
    "  - 转移：rework 或下一次 dispatch-next 即换 agent 接力，接手方复用同一空间——"
    "所以中间产物必须落盘可接力（worktree 小步 commit / dir 产物全落隔离目录并列清单）。"
)


def _workspace_clause(ws: Optional[Dict[str, str]], meta: Dict[str, Any]) -> str:
    """dispatch-next 的工作空间条款（按类型分三种：worktree 泳道 / dir 隔离目录 / 主树）。

    M16：工作区已由 workflow 第一个 activity（prepare_workspace）创建/复用——
    agent 直接进入干活，勿自行 git worktree add / mkdir。
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


# M5① 必读上下文清单映射表（宁少勿滥：只放「该 workflow 的工单大概率必读」的文档；
# 拿不准不进表，宁缺。CLAUDE.md 与岗位说明书是保底两项，不进表）。
WORKFLOW_CONTEXT: Dict[str, List[str]] = {
    "content-pipeline": ["pipeline/proposals/README.md", "docs/design/平台架构设计.md"],
    "dev-lane": ["docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md"],
}

# 标题/关键词推导（二级，宁少勿滥：只收高置信关键词）。
TITLE_CONTEXT_RULES: List[Tuple[str, List[str]]] = [
    (r"工单引擎|工单工作流|temporal|dispatch|派活",
     ["docs/design/工单工作流台设计.md",
      "docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md"]),
    (r"知识库|review|审校", ["docs/design/知识库设计.md"]),
    (r"掌握", ["docs/design/掌握模型设计.md"]),
    (r"营造|建城", ["docs/design/营造建造循环设计.md"]),
]


def context_docs(workflow_id: str, title: str) -> List[str]:
    """按工单 workflow/标题推导相关设计文档（去重保序）。"""
    out: List[str] = []
    for p in WORKFLOW_CONTEXT.get(workflow_id, []):
        if p not in out:
            out.append(p)
    for pat, docs in TITLE_CONTEXT_RULES:
        if re.search(pat, title or "", re.I):
            for p in docs:
                if p not in out:
                    out.append(p)
    return out


# 段专项条款（M5②：content-pipeline ai-review 段接 knowledge review 闭环）。
STAGE_CLAUSES: Dict[Tuple[str, str], List[str]] = {
    ("content-pipeline", "ai-review"): [
        "审校落盘条款（M5 review 闭环）：逐块意见落 docs/reviews 制式——"
        "python3 server/dsh/knowledge/review_store.py save '<json>'"
        "（block_key 取知识库 /suyou-knowledge/api/diff 的块键；整篇意见用 doc: 前缀自由锚点）；"
        "报告附 python3 server/dsh/knowledge/review_store.py rework <path> 生成的"
        "一键复制返工指令（可直接贴进 ticket rework note）。",
    ],
}


# ========================================================================================
# M10④（t260822-m10-role-consolidation）：dispatch-next 按 stage 选 dispatch 实例
#
# 五角色定稿后，同一 role 可有多个 dispatch 实例（product-operation 的加工/审校/验证/出数
# 四分工）。本表 = 模板 stage → 分工 kind 的唯一真源（**宁少勿滥**：只放「该 stage 必须由
# 分工实例承载」的映射，拿不准不进表；无映射的段走默认实例 dispatch_<role>）。
# 分工的模型家写在 KIND_MODELS 供 prompt 展示（真源=model-routes.yaml 的 tasks 段，
# smoke_routes.py 有交叉断言防漂移）。
# ========================================================================================

STAGE_DISPATCH_KIND: Dict[Tuple[str, str], str] = {
    ("content-pipeline", "ai-review"): "proofread",   # AI 审校段 → 审校分工实例
    ("proofread", "review"): "proofread",             # 独立审读段 → 审校分工实例
    ("regression", "regress"): "qa",                  # 独立回归段 → 验证分工实例
    ("dev-lane", "integration_review"): "qa",         # 集成审读（diff 审读）→ 验证分工实例
}

KIND_LABELS: Dict[str, str] = {"proofread": "审校", "qa": "验证", "analyst": "出数"}
# v1 旧引擎（build_dispatch_prompt，replay 冻结）仍引用，勿删：
KIND_DOCS: Dict[str, str] = {"proofread": "proofreader.md", "qa": "qa.md", "analyst": "analyst.md"}
KIND_MODELS: Dict[str, str] = {"proofread": "zai/glm-5.2", "qa": "zai/glm-5.2", "analyst": "zai/glm-5.2"}

# ---- 运行时模型路由（gen.py 退役后唯一消费者：agent activity spawn 时查表）----
# 查表规则：roles.<role>.tasks.<kind> → roles.<role> → default；全落空返回 None
# （不覆盖，agent 用 profile 默认模型）。表=server/dsh/model-routes.yaml（工单台
# 「模型」页签可视化编辑，下一次 spawn 即生效——无生成步骤）。契约①d（v1.6）：
# 表路径可由项目注册条目 paths.model_routes 声明（见 routes_file_for_spawn），
# 未声明回落本常量——suyou 不声明 paths，逐字节零回归。

MODEL_ROUTES_REL = "server/dsh/model-routes.yaml"
MODEL_ROUTES_FILE = REPO_ROOT / MODEL_ROUTES_REL


def model_route_for(role: str, kind: str = "",
                    routes_file: Optional[pathlib.Path] = None) -> Optional[Dict[str, str]]:
    """读模型路由表查 (role, kind) 的 provider/model。activity 侧调用（允许 IO）。

    routes_file 缺省 MODEL_ROUTES_FILE；项目声明 paths.model_routes 时由
    routes_file_for_spawn 解析传入（契约①d）。表文件缺失/内容不可解析 = 返回
    None（既有容错语义——agent 用 profile 默认模型；①d「锚点 vs 内容」明文：
    本函数容错覆盖表内容，声不声明同语义，fail-closed 只归锚点判定）。"""
    try:
        import yaml  # pyyaml（temporal-poc venv）
        table = yaml.safe_load((routes_file or MODEL_ROUTES_FILE).read_text("utf-8")) or {}
    except Exception:
        return None
    eff = LEGACY_ROLE.get(role, role)
    entry = (table.get("roles") or {}).get(eff) or {}
    cands = []
    if kind:
        cands.append((entry.get("tasks") or {}).get(kind))
    cands.append(entry)
    cands.append(table.get("default"))
    for cand in cands:
        if isinstance(cand, dict) and cand.get("provider") and cand.get("model"):
            return {"provider": str(cand["provider"]), "model": str(cand["model"])}
    return None

# 退役角色 → 新角色兜底（在跑工单模板快照钉死仍带旧 role id；新工单一律新模板新 role）。
# 先归一角色再套分工：旧模板 ai-review 段 role=proofreader → product-operation + proofread 分工。
LEGACY_ROLE: Dict[str, str] = {
    "dispatcher": "integration",
    "editor": "product-operation",
    "proofreader": "product-operation",
    "qa": "product-operation",
    "analyst": "product-operation",
}


def dispatch_instance_for(workflow_id: str, stage: str, role: str) -> Tuple[str, str, str]:
    """按 (workflow, stage, role) 选派活工具实例名。返回 (tool_name, effective_role, kind)
    （kind 无则 ''；effective_role = 旧 role 归一后的新角色 id）。"""
    eff = LEGACY_ROLE.get(role, role)
    kind = STAGE_DISPATCH_KIND.get((workflow_id, stage), "")
    tool = "dispatch_" + eff.replace("-", "_") + (("_" + kind) if kind else "")
    return tool, eff, kind


def build_dispatch_prompt(tid: str, meta: Dict[str, Any], template_lane: str,
                          stage_def: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """dispatch-next 派活指令（ticket.py 旧路径与 TicketWorkflow 共用的单一生成器）。

    返回 (prompt_text, parts)。parts 供调用方结构化透出（context/workspace 等）。
    """
    stage = str(meta.get("stage") or "")
    role = str(stage_def.get("role") or "")
    acc = list(stage_def.get("acceptance") or [])
    ws_list = list(meta.get("write_set") or [])
    wid = str(meta.get("workflow_id") or "")
    title = str(meta.get("title") or "")
    ws = workspace_of(meta, template_lane)
    ctx_docs = context_docs(wid, title)
    # M10④：按 stage 选 dispatch 实例（旧 role 先归一；分工段选分工实例）
    tool, eff_role, kind = dispatch_instance_for(wid, stage, role)
    # 契约①d（t260903-03）：role_doc/kind_doc 的目录基准经注册条目 paths.roles_dir
    # 声明取值，未声明回落 DEFAULT_ROLES_DIR（相对路径字符串形态与改前一致）。
    # prompt 只是文本指引，声明锚点缺失的红在 spawn 真消费点报（roles_dir_for_spawn）；
    # 条目文件本身不可解析照常 fail-closed（ProjectPathsError 上抛）。
    roles_rel = roles_rel_for_prompt(str(meta.get("project") or ""))
    role_doc = "%s/%s.md" % (roles_rel, eff_role)
    kind_doc = ("%s/%s" % (roles_rel, KIND_DOCS[kind])) if kind else ""
    role_show = eff_role + ("（旧 role %s 已归一）" % role if role != eff_role else "")
    if kind:
        role_show += "（分工=%s）" % KIND_LABELS[kind]

    header = [
        "【派活指令】工单 %s（%s）当前阶段：%s（%s，角色=%s）"
        % (tid, title, stage, stage_def.get("name", ""), role_show),
        "1. 必读上下文清单（M5①，按序先读再动手）：",
        "   ① CLAUDE.md（仓库根，项目交接说明——**只读**，不得修改）",
        "   ② %s（岗位说明书全文：铁律/红线/交接物约定；判断不了记录交回，不硬改）%s"
        % (role_doc, (" + %s（分工卡，同读）" % kind_doc) if kind else ""),
        "   ③ 推导设计文档（按 workflow/标题，映射表宁少勿滥）：%s"
        % ("；".join(ctx_docs) if ctx_docs else "无（本工单无推导项，①②足够）"),
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
                 "note 附验收结果与遗留问题（dir 类工作空间另附产物清单）。" % tid)
    lines = header + ["%d. %s" % (i + 2, it) for i, it in enumerate(items)]
    prompt = "\n".join(lines)
    parts = {
        "role": eff_role,
        "role_doc": role_doc,
        "kind_doc": kind_doc,
        "dispatch_tool": tool,
        "dispatch_kind": kind,
        "ticket_id": tid,
        "context": ["CLAUDE.md", role_doc] + ([kind_doc] if kind_doc else []) + ctx_docs,
        "write_set": ws_list,
        "acceptance": acc,
        "workspace": ws,
        "workspace_clause": _workspace_clause(ws, meta),
        "ownership_contract": OWNERSHIP_CONTRACT,
        "small_steps": "每项变更一个 commit；settled 附验收输出",
    }
    return prompt, parts


# ========================================================================================
# M11 v2（t260822-m11-template-as-code）：模版即代码 —— 五模版 workflow 类共享契约
# （260824 起 code-lane/build-workbench 已删，现存 dev-lane/content-pipeline/proofread/
# regression/cleanup 五个；历史文档中「六模版」为删前措辞）
#
# 真源=代码：各套模版的 stage 链从 yaml 直译进各子类的 STAGES 类属性（Stage 元组），
# workflows/*.yaml 降为 gen_workflows_doc.py 生成的参考快照（勿手改）。
# 本区全部是纯数据/纯函数：workflow sandbox 内可确定性使用，零 IO。
# ========================================================================================

# v2 引擎标记（snapshot['engine']；ticket.py/client.py 据此分流新旧路径）
ENGINE_V2 = "template-as-code-v2"
ENGINE_VERSION_V2 = 3

# 执行主体枚举（t260828-01，observability 立项「执行主体可见」）：
# stage 内部活动（parts）的组合态声明——agent=🤖 agent 执行 / script=⚙️ 脚本·程序化 /
# human=👤 人工。不做 stage 单值（implement=agent+脚本、merge=人+脚本 的混合执行已存在，
# 单值是逼代码说谎）。动态真源仍为 Temporal history，parts 只是静态声明（工单台徽标用）。
PART_KINDS: Tuple[str, ...] = ("agent", "script", "human")


@dataclass(frozen=True)
class Stage:
    """一段的定义（子类 STAGES 类属性的元素）。kind 由 exit/agent 派生：
    exit='human' → 人门段；agent=False → 纯脚本门段；否则 agent 段（可再挂 gate 尾门）。
    parts=执行主体组合声明（PART_KINDS 子集，有序元组）：仅展示元数据，
    引擎管道件（结果文件轮询/prepare_human_gate 机械准备/no-op settle）不计，
    业务产物落账必需的脚本计入（implement 的 worker 代落盘、merge 的落账+泳道清理）。"""

    id: str
    name: str
    role: str                                  # M10 五角色：developer/integration/ops/product-operation/artist
    desc: str = ""
    acceptance: Tuple[str, ...] = ()
    next: str = ""                             # 展示/快照用；驱动以 STAGES 序为准
    exit: str = ""                             # 'human' = 人门段（signal+wait_condition）
    fanout: int = 0                            # 审读类扇出声明（保留自 yaml，当前=1）
    revision_to: str = ""                      # rework 缺省回退目标（content-pipeline 修订回路）
    agent: bool = True                         # False = 纯脚本门段（无 agent 活动，只跑 gate）
    gate: Optional[GateSpec] = None            # 尾门：本段产物落定后必须跑绿才推进
    parts: Tuple[str, ...] = ()                # 执行主体组合（PART_KINDS 子集）；空=未声明（UI 软降级「—」）

    @property
    def kind(self) -> str:
        if self.exit == "human":
            return "human"
        if not self.agent:
            return "gate"
        return "agent"


@dataclass
class TicketInput:
    """v2 workflow 输入：创建即钉死全部业务属性（确定性）；stage 链在子类代码里不进输入。"""

    ticket_id: str
    template_id: str
    project: str = ""                            # 项目 key（机器级 per-key 注册表 ~/.sandbar/projects/<key>/project.yaml）；空=非法，ticket-start 入口拦截
    epic: str = ""                               # 立项代号（notes/epics/<代号>.md 必须存在）；空=不关联立项
    title: str = ""
    lane: str = ""
    workspace: Optional[Dict[str, str]] = None   # {type: worktree|dir, path} | None
    worktree: str = ""
    branch: str = ""
    base_ref: str = ""
    proposal_id: str = ""
    book_path: str = ""
    write_set: List[str] = field(default_factory=list)
    # t260829-07 写集生命周期：建票显式声明「本票无文件改动」（allow_empty_write_set
    # 才可能置真）——机械复核闸据此跳过「泳道 0 commit」判定。
    no_file_changes: bool = False
    acceptance_extra: List[str] = field(default_factory=list)  # A5.5：实例增项（追加到首段清单）
    deliverables: str = ""
    # M16：正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body）；
    # spec=加工后派发规格（独立字段，不覆盖正文）。
    user_request: str = ""
    spec: str = ""
    body: str = ""
    created: int = 0
    gate_overrides: Dict[str, GateSpec] = field(default_factory=dict)  # 自测门替换（生产恒空）


@dataclass
class StageResult:
    """agent 段结果（= 工作空间结果文件的内存形态；格式即 {status,summary,report,
    deliverables,files_changed,evidence}）。

    三层口径：summary=台面一句话（列表/交接时间线）；report=人读进展报告 markdown
    （详情卡片/交接注入/打回注入）；evidence=机器口径原始证据（默认折叠）。"""

    status: str = "ok"                         # ok | failed
    summary: str = ""
    report: str = ""
    deliverables: List[str] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    evidence: str = ""


@dataclass
class ReworkRequest:
    """rework signal 载荷：回目标段重跑。target_stage 空 = 缺省（当前段 revision_to 或上一段）。"""

    who: str
    target_stage: str = ""
    note: str = ""


@dataclass
class AgentStageArgs:
    """agent 段 activity 入参（activity 名=stage 名；实现通用，按 stage 派活）。"""

    ticket_id: str
    stage_id: str
    role: str
    prompt: str                                # 派活指令（workflow 侧纯函数组装，确定性）
    workspace: Optional[Dict[str, str]] = None
    result_file: str = ""                      # 幂等锚点：存在即直接读（重跑安全）
    log_file: str = ""
    gen: int = 0                               # 第几次进本段（rework 重跑换新结果文件）
    max_polls: int = 0                         # 0=缺省（activity 侧常量）
    # t260828-08 suggest_next 专用（通用 agent 步留空；加默认字段对旧事件序列化向后兼容）：
    epic: str = ""                             # 立项代号（缓存写入路径 + 档案锚点）
    state_key: str = ""                        # prepare_epic_next 算出的 state_key（缓存比对键）
    workflow_id: str = ""                      # 模板 id（分工级模型路由查 STAGE_DISPATCH_KIND 用）
    previous_context: str = ""                 # 上次运行上下文（同 stage 重跑时从工作流历史继承）
    # t260829-07 集成测试机制：并行分叉期 implement/design 都跳过尾部 settle（防止把
    # 对方半成品一起代落盘），统一落盘由汇合点的 settle_lane activity 承担。
    skip_settle: bool = False


@dataclass
class HumanGatePrep:
    """人门段机械准备 activity 入参/回执：组装审查上下文（diff/提案摘录/前段产物清单）。"""

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
    context_text: str = ""                     # 给签字人看的机械上下文（进 snapshot 展示）
    note: str = ""


@dataclass
class WorkspacePrep:
    """工作区准备 activity 入参（M16：工作区由 workflow 第一个 activity 创建，agent 不再自己搞）。"""

    ticket_id: str
    workspace: Optional[Dict[str, str]] = None  # {type: worktree|dir, path} | None（主树=None）
    branch: str = ""                            # worktree 泳道的新分支名（create 已登记）
    base_ref: str = ""                          # 基点（create 时主树 HEAD；空=缺省 HEAD）


@dataclass
class WorkspacePrepResult:
    """工作区准备回执（失败不抛——回执交 workflow 转 blocked 等 retry_qc / rework 判读）。"""

    ok: bool = True
    kind: str = ""        # worktree | dir | main（主树/无独立空间）
    action: str = ""      # created | reused | ensured | skipped | failed
    path: str = ""
    error: str = ""       # failed 时给原因（如目录已存在但非本仓库 worktree）


@dataclass
class MergeCheckArgs:
    """merge_check activity 入参（260824 dev-lane：合并前的程序化检查，无 agent）。

    补的正是 t260824-01 漏掉的检查：那张工单 agent 全程未 commit，verify 门跑在
    主树上（改动在 worktree，主树 diff 为空 → 白名单检查形同虚设）全绿假闭环。
    所以本 activity 硬性要求：泳道有 commit、工作区干净、verify 跑在泳道内。"""

    ticket_id: str
    worktree: str = ""                        # 泳道 worktree 路径（相对仓库根或绝对）
    branch: str = ""                          # 泳道分支名
    base_ref: str = ""                        # 基点（create 时主树 HEAD）
    # t260828-09 UI 证据闸：工单写集原样带入（dev_lane 调用点从 meta["write_set"] 传）；
    # 带默认值——旧 RUNNING 实例重放历史事件时无此字段，不破回放。
    write_set: List[str] = field(default_factory=list)


# ---- t260828-09：UI 验收机制（截图通道 + 看图审读 + merge_check 证据闸）----

# UI 文件口径（单点维护：膨胀或收窄只改这里）：
#   控制台 workbench 前端源码/产物、providers 前端源码、app 客户端源码与入口页。
UI_WRITE_PREFIXES = (
    "server/dsh/workbench/src/client/",
    "server/dsh/workbench/lib/",
    "server/dsh/providers/src/client/",
    "app/src/",
    "app/index.html",
)


# 截图证据目录（相对泳道 worktree 根；capture.mjs --out 与 merge_check 闸同口径）
UI_EVIDENCE_DIR = ".suyou/screenshots"

# 截图证据归档目录（相对主树 REPO_ROOT；prepare_ui_evidence 成功后把泳道截图
# 拷进来：<REPO_ROOT>/.suyou/evidence/<ticket_id>/。泳道 merge 后拆树，report 里
# 引图不死链靠这份归档；host 只读端点 node.ts evidence 路由同口径读它——
# node 侧 SUYOU_EVIDENCE_DIR env 覆盖（=归档基目录本体，自测指向临时目录）与
# agent_activities._archive_shots 同名 env 互指，改一边同步另一边）
EVIDENCE_DIR = ".suyou/evidence"


def is_ui_write_set(write_set: Any) -> bool:
    """写集命中 UI 口径即 UI 票（纯函数，无 IO）。

    容错：元素两端空白 strip；非字符串元素忽略；None/空集 → False。
    路径按仓库相对路径前缀比对。"""
    if not write_set:
        return False
    for w in write_set:
        if not isinstance(w, str):
            continue
        p = w.strip()
        for pref in UI_WRITE_PREFIXES:
            if p == pref.rstrip("/") or p.startswith(pref):
                return True
    return False


def _valid_write_set_entry(p: Any) -> bool:
    """写集条目合法性（纯函数）：仓库内相对路径——非字符串/空串/绝对路径/含 '..'/
    反斜杠路径一律非法（不越界判断不查盘，形态判断足够）。"""
    if not isinstance(p, str):
        return False
    s = p.strip()
    if not s or s.startswith("/") or s.startswith("\\") or "\\" in s:
        return False
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():  # Windows 盘符 C:/…
        return False
    return ".." not in s.split("/")


def validate_write_set_args(write_set: Any, allow_empty: bool):
    """建票写集校验（纯函数，t260829-07 A1）。

    返回 (ok, flags, err)：
      ok           是否放行建票
      flags        {"no_file_changes": bool}——空写集+显式声明时置真
      err          拒收文案（含两条出路），ok=True 时为空串
    口径：写集为 None → 按空集口径（既有自检 selfcheck_write_lifecycle 与
    client.py 建票口锁定的有意容错）；写集非 list（含字符串——不拒收会被
    for 迭代成单字符列表变假护栏，t260902-10）→ 拒收；写集非空 → 放行
    （条目形态逐条校验，非法条目在 client 侧直接拒收——建票是护栏起点，
    不静默清洗）；空集 + allow_empty_write_set → 放行并记 no_file_changes；
    空集且无声明 → 拒收。"""
    if write_set is not None and not isinstance(write_set, list):
        return False, {}, ("写集须为列表（实际 %s）：字符串会被逐字符迭代成假护栏，"
                           "请传 [\"路径\", …] 或 None" % type(write_set).__name__)
    ws = [w.strip() for w in (write_set or []) if isinstance(w, str)]
    bad = [w for w in (write_set or []) if not _valid_write_set_entry(w)]
    if bad:
        return False, {}, ("写集含非法条目（须为仓库内相对路径，禁绝对路径与 '..'）：%s"
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
    """写集跟随方案（纯函数，t260829-07 A3）。

    merged = initial ∪ plan_files 合法条目（保序：先 initial 后新增，去重 strip）。
    **并集而非替换**（有意偏差于「刷新为方案清单」）：初始写集是人/建议先验，
    方案漏列时先验不应被冲掉；verify_lane 白名单是上限放行不是强制清单，多余
    文件只多留余量，不红灯、不进 diff。
    三态口径：
      - plan_files 里非法条目（非字符串/绝对路径/含 '..'/越界形态）丢弃进
        dropped——拒条不拒次；
      - added = plan_files 合法条目 − initial（调用方记 timeline「授权扩展」）；
      - initial 同样过形态过滤（建票口已校验，这里兜底）。
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
    """verify_review_gate activity 入参（t260829-07：审读判据机械化，纯 git/文件零 LLM）。"""

    ticket_id: str
    worktree: str = ""                        # 泳道 worktree（git -C 查询泳道 commit 数）
    write_set: List[str] = field(default_factory=list)
    no_file_changes: bool = False             # 建票声明「本票无文件改动」→ 跳过 0-commit 闸


@dataclass
class ReviewGateResult:
    """verify_review_gate 回执。报错精确性三态（t260829-07 review 第 2 轮）：

    - git_error 空串 = 泳道 commit 查询成功，lane_commits 有意义；非空 = 查询失败，
      lane_commits=-1 哨兵（禁止用 0 表达「查不了」——「异常记 0」会把 git 故障
      误报成「实现未落盘」，与事实可能相反）。
    - shots_path_error 空串 = screenshots 路径正常（不存在=没拍，等价 0 png，可断言
      缺失）；非空 = 路径存在但异常（是文件/不可读），png_count=-1（不可断言缺失）。"""

    git_error: str = ""
    lane_commits: int = -1
    shots_path_error: str = ""
    png_count: int = -1
    passed: bool = True
    reasons: List[str] = field(default_factory=list)


def review_gate_verdict(git_error: str, lane_commits: int, shots_path_error: str,
                        png_count: int, no_file_changes: bool, is_ui: bool):
    """审读机械复核判定（纯函数，t260829-07 B2；selfcheck 直测不依赖 temporalio）。

    返回 (rework, note)：rework 非空 = 强制打回文案（prev_ctx 注入 implement）；
    note 非空 = 跳过说明（记 timeline，可见不静默不打回）。报错精确性纪律：
    查询失败不得断言「未落盘/证据缺失」——断言必须与事实同向。"""
    if git_error:
        return "", "机械复核跳过：git 查询失败：%s" % git_error
    if lane_commits == 0 and not no_file_changes:
        return "机械复核：实现未落盘（泳道 0 commit）", ""
    if shots_path_error:
        return "", "机械复核跳过：截图路径异常：%s" % shots_path_error
    if png_count == 0 and is_ui:
        return "机械复核：UI 证据缺失（screenshots 无 png）", ""
    return "", ""


@dataclass
class UiEvidenceArgs:
    """prepare_ui_evidence activity 入参（t260828-09：worker 代跑 ui-check/capture.mjs 截图）。"""

    ticket_id: str
    worktree: str = ""                        # 泳道 worktree 路径（截图落 <worktree>/.suyou/screenshots/）
    screenshots_dir: str = ""                 # 缺省 <worktree>/.suyou/screenshots


@dataclass
class UiEvidenceResult:
    """prepare_ui_evidence 回执（失败不抛——截图缺失由 merge_check 证据闸红灯收口）。"""

    ok: bool = False
    shots: List[str] = field(default_factory=list)  # 成功产出的截图文件名（不含目录）
    # 每张截图一行的「名（mtime iso）」清单（activity 侧算好带回——workflow 侧零 IO
    # 纪律，dev_lane 直接拼进审读 prompt，供 agent 比对截图落盘时间防旧图充数）
    shot_lines: List[str] = field(default_factory=list)
    detail: str = ""                          # 失败原因 / 成功摘要（给 prompt 与 gate 留痕）
    skipped: bool = False                     # 非 UI 票跳过时置真（兜底语义，正常由 workflow 侧守卫）


@dataclass
class MergeCheckResult:
    """merge_check 回执（红灯不抛——回执交 workflow 判读）。

    t260826-01 冲突自动消解回路：红灯细分两类——conflict=True（merge 预演冲突，
    交 workflow 自动打回 implement 消解）与 conflict=False（其它红灯，维持
    blocked 等人）。conflict 判定以「merge 预演项红且解析到非空 conflict_files」
    为准（不能只看 merge-tree rc=1：bad ref 等 git 异常也 rc=1 但无冲突文件，
    误判成可消解冲突会让消解回路空转——review M1）。且其它三项（无 commit /
    工作区脏 / verify_lane 红）任一项红时一律 conflict=False：先让人解掉基础
    问题，不带病消解。"""

    green: bool = False
    checks: List[Dict[str, Any]] = field(default_factory=list)  # [{item, green, detail}]
    error: str = ""                           # 基础设施故障（git 不可用等）时给原因
    conflict: bool = False                    # True=merge 预演冲突（自动消解）；False=其它红灯（blocked）
    conflict_files: List[str] = field(default_factory=list)  # 冲突文件清单（解析自 merge-tree 输出）
    merge_tree_excerpt: str = ""              # merge-tree 输出摘要（截断带出，注入 agent 解冲突 prompt）


@dataclass
class ConflictPrepArgs:
    """prepare_conflict_resolution activity 入参（t260826-01：worker 代跑 merge 留冲突现场）。

    agent 沙箱写不了真 .git（worktree 的 .git 是指向主库的 gitfile），没法自己
    git merge——所以合并由 worker（无沙箱）代跑，冲突标记文件留在泳道工作区，
    agent 只负责编辑解标记（与 implement 步「agent 写、worker 代落盘」同契约）。"""

    ticket_id: str
    worktree: str = ""                        # 泳道 worktree 路径（相对仓库根或绝对）
    branch: str = ""                          # 泳道分支名
    base_ref: str = ""                        # 要合进泳道的目标 ref（现状口径=main，不换 rebase）


@dataclass
class ConflictPrepResult:
    """prepare_conflict_resolution 回执（失败不抛——回执交 workflow 判读）。"""

    ok: bool = False
    conflict_files: List[str] = field(default_factory=list)  # 冲突文件清单（UU/AA 行）
    merge_output: str = ""                    # git merge 输出截断（agent 解冲突上下文）
    already_clean: bool = False               # True=合并零冲突（竞态兜底：base_ref 未动，直接回 merge_check）
    error: str = ""                           # 基础设施故障（ref 不存在/merge 异常等）时给原因


@dataclass
class ConflictSettleArgs:
    """settle_conflict_resolution activity 入参（agent 解完冲突后 worker 代落盘）。"""

    ticket_id: str
    worktree: str = ""
    branch: str = ""
    base_ref: str = ""
    round_no: int = 0                         # 冲突消解轮次（写进 commit message 与日志）


@dataclass
class ConflictSettleResult:
    """settle_conflict_resolution 回执（失败不抛——回执交 workflow 判读）。"""

    ok: bool = False
    commit: str = ""                          # 落盘的合并提交短 hash
    remaining_files: List[str] = field(default_factory=list)  # 仍有未解冲突的文件（非空=agent 没解干净）
    error: str = ""


@dataclass
class MergeArgs:
    """merge activity 入参（人审签字通过后执行的真实合并 + 泳道清理）。

    defer_teardown（M1-3，t260902-02）：True 时 squash 落账后**跳过内联泳道清理**，
    交后续 teardown_lane activity（merge→archive→teardown 三段收口）；False = 旧
    语义（落账后内联清理）。字段带默认值 False 的负载兼容手段（patched 门只门
    workflow 侧分支、管不到 activity 行为版本）：存量历史输入序列化时**无此键**，
    temporalio dataclass 反序列化对缺键字段回落默认值 False → 走旧内联清理语义，
    新 worker 部署后存量工单签字收口照常拆泳道、零残留（1.18.2 实测锁定）。"""

    ticket_id: str
    worktree: str = ""
    branch: str = ""
    base_ref: str = ""
    defer_teardown: bool = False


@dataclass
class ArchiveArgs:
    """archive_ticket activity 入参（M1-3，t260902-02：完结工单数据出仓归档）。

    归档真源出仓到 per-key 数据目录（契约 v1.4 ①c），根治「完结工单 stage 报告
    随泳道拆除丢失」。worktree 为空 = 主树道工单——.suyou/ 换 REPO_ROOT/.suyou 根
    归档（代理文件属灰面，归档即清扫，不静默放过）。meta 快照由 workflow 侧传入
    （workflow 不查盘纪律）；文件清单与拷贝由 activity 按 ARCHIVE_INCLUDE_* 口径现扫。"""

    ticket_id: str
    project_key: str = ""             # 归档归属 key（过 PROJECT_KEY_RE 白名单）
    worktree: str = ""                # 泳道 worktree 路径（相对仓库根或绝对）
    meta: Dict[str, Any] = field(default_factory=dict)  # 工单 meta 快照（stage/status/timeline/handoffs/checks…）
    legacy: bool = False              # True = archive-legacy 存量诚实过账（manifest 记 reason，无文件负载）


@dataclass
class ArchiveResult:
    """archive_ticket 回执（失败抛错 fail-closed——归档成功是拆泳道的前提，不降级）。

    幂等：重跑覆盖同路径（Temporal 重试安全）。retained = 泳道仍在原位（新顺序
    archive 在 teardown 之前），本单恒 True；False 只在 archive-legacy 无 worktree
    路径场景出现（泳道早已拆除）。files = manifest.files 回带（workflow 侧留痕用）。"""

    ok: bool = False
    archive_path: str = ""            # data/tickets/<id>/ 目录绝对路径
    retained: bool = True             # 泳道是否仍在原位（True=待 teardown_lane 拆；False= legacy 无泳道）
    files: List[Dict[str, Any]] = field(default_factory=list)   # manifest.files 镜像
    absent: List[str] = field(default_factory=list)             # manifest.absent 镜像
    error: str = ""                   # 失败原因（workflow 侧拼 blocked 文案）


@dataclass
class MergeResult:
    """merge 回执（冲突/故障不抛——回执交 workflow 转 blocked 等人处置）。"""

    ok: bool = False
    action: str = ""      # merged | conflict | failed
    merge_commit: str = ""
    error: str = ""


# ---- 结果文件/日志路径（纯函数；activity 与 prompt 组装共用同一真源，防漂移）----

def stage_workspace(inp_ws: Optional[Dict[str, str]], ticket_id: str) -> Optional[Dict[str, str]]:
    """agent 段工作目录：工单登记的 workspace 优先；无 → /tmp/suyou-ws/<工单id> 隔离目录
    （主树道工单的 agent 也在仓库根干活，但结果文件/日志一律落隔离目录，主树零污染）。"""
    if isinstance(inp_ws, dict) and inp_ws.get("type") in WORKSPACE_TYPES and inp_ws.get("path"):
        return {"type": str(inp_ws["type"]), "path": str(inp_ws["path"])}
    return {"type": "dir", "path": WS_DIR_BASE + "/" + ticket_id}


def result_file_for(ticket_id: str, stage_id: str, gen: int,
                    ws: Optional[Dict[str, str]]) -> str:
    """本段第 gen 次进入的结果文件绝对路径（幂等锚点；rework 重跑 gen+1 换新文件）。"""
    base = (ws or {}).get("path") or (WS_DIR_BASE + "/" + ticket_id)
    p = pathlib.Path(base)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return "%s/.suyou/stage_%s_gen%d.json" % (str(p), stage_id, gen)


def agent_log_for(ticket_id: str, stage_id: str, gen: int,
                  ws: Optional[Dict[str, str]]) -> str:
    base = (ws or {}).get("path") or (WS_DIR_BASE + "/" + ticket_id)
    p = pathlib.Path(base)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return "%s/.suyou/agent_%s_gen%d.log" % (str(p), stage_id, gen)


# stage 级验收增项（t260901-09）：常驻检查项挂在 prompt 组装真源（build_stage_prompt），
# 按 stage id 键控——build_stage_prompt 由 base.py 与 dev_lane.py 共用，键不命中
# 即零变化（对 base 系 workflow 无影响）；文案自带「不涉及则标注不适用」兜底。
STAGE_ACCEPTANCE_EXTRA: Dict[str, Tuple[str, ...]] = {
    "acceptance_walkthrough": (
        "若本票涉及 UI/泳道图渲染，验收报告必含『并行期 UI 呈现』检查项：并行分叉期"
        "步骤条双边同亮（两步同帧 data-s=running 且各带 ∥ 标记）+ 状态行报"
        "『并行分叉中』，以隔离台实拍/DOM 断言输出为证；不涉及 UI 则标注『不适用』并说明",
    ),
}


# ---------- previous_context 封顶（t260901-19：打回意见逐字 + 历史摘要封顶） ----------
# 封顶类 = base.py 组装的六类历史行（封闭前缀表，逐字对齐 base.py:225-235）。
# 注意：base 未来新增「- 上次*」以外的历史行类型会逃逸封顶——由透传行 2 万字符
# 硬顶兜底（防畸形巨型行），不追改本表。
CAP_PREV_LINE_PREFIXES: Tuple[str, ...] = (
    "- 上次状态：", "- 上次摘要：", "- 上次报告：",
    "- 上次产物：", "- 上次改动文件：", "- 上次验收证据：",
)
CAP_PREV_LINE_LIMIT = 800        # 封顶类单行上限
CAP_PREV_TOTAL_LIMIT = 4000      # 封顶类合计上限（超限从尾部行丢弃）
CAP_PREV_HARD_LIMIT = 20000      # 透传行硬顶（只防畸形，正常负载远低于此）
_CAP_TRUNC_MARK = "…（截断）"
_CAP_OMIT_MARK = "…（后续历史已省略）"


def cap_previous_context(text: Any) -> str:
    """previous_context 封顶（纯函数）：只截封顶类历史行，其余一律透传。

    - 封顶类（前缀命中 CAP_PREV_LINE_PREFIXES）：单行超 800 截到 800+省略标记；
      合计超 4000 从尾部行丢弃（历史行按新旧排列，尾部是最旧的），丢过即加尾注。
    - 透传类：「- 打回原因：」行与一切未识别前缀的行（裸打回意见、结构化打回块、
      arb_ctx 单行 JSON 等 dev_lane 负载）原样保留，仅单行超 2 万字符时截断防畸形
      ——这些行是打回意见/机器结果的载体，截了会掏空下一棒的输入（t260901-19
      review 第 2 轮打回项 1）。
    - 防御性归一：None/非字符串/空白串 → 空串；空串 → 返回空串（调用方注入守卫不变）。"""
    if not isinstance(text, str) or not text.strip():
        return ""
    capped: List[Tuple[bool, str]] = []  # (是否封顶类, 行文本)
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


def build_stage_prompt(ticket_id: str, meta: Dict[str, Any], stage: Stage,
                       handoffs: List[Dict[str, Any]], result_file: str,
                       gen: int, previous_context: str = "") -> str:
    """agent 段派活指令（纯函数，零 IO——workflow 内确定性调用）。
    上下文=工单业务属性 + 前段 handoff 摘要 + 结果文件契约。
    previous_context 非空即追加（上次运行产出+打回原因，来自工作流历史）。
    注意 gen 只是「第几次进本段」的展示值——各引擎基制不一（base 1 基/dev_lane 0 基），
    不拿它当注入守卫（曾因 gen>1 守卫吞掉 0 基引擎第一次打回的意见，t260828-04）。"""
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
    ]
    ctx = context_docs(str(meta.get("workflow_id") or meta.get("template_id") or ""),
                       str(meta.get("title") or ""))
    if ctx:
        lines.append("   ② 推导设计文档：%s" % "；".join(ctx))
    # M16：正文=原始用户需求（user_request 逐字保留，显式优先；缺省回落 body），
    # 加工后派发规格独立呈现（spec），不再混入正文。
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
    prev = [h for h in (handoffs or []) if isinstance(h, dict)]
    if prev:
        lines.append("5. 前段交接（倒序，最近在前；正文=前段报告，含怎么验证的/遗留风险）：")
        for h in reversed(prev[-3:]):
            body = str(h.get("report") or "") or str(h.get("summary") or "")
            lines.append("   - [%s] %s" % (h.get("stage", "?"), body[:1200]))
    # 阶段重跑上下文继承：调用方只在本段重跑时才传非空 previous_context，
    # 非空即注入（不拿 gen 当守卫——dev_lane 的 gen 是 0 基，gen>1 会漏掉第一次打回）
    n = 6
    prev_ctx_text = cap_previous_context(previous_context)
    if prev_ctx_text:
        lines.append("6. 上次运行上下文（阶段重跑上下文继承：同 role 再次调用时 prompt 注入上次产出+打回原因）：")
        for ln in prev_ctx_text.splitlines():
            lines.append("   " + ln)
        n = 7
    lines.append("%d. 工作目录：%s（%s）——已由 workflow 第一个 activity（prepare_workspace）创建/复用，"
                 "**直接进入干活，勿自行 git worktree add / mkdir**；一切读写在此空间内；"
                 % (n, ws["path"], ws["type"]))
    lines.append("   " + OWNERSHIP_CONTRACT.replace("\n", "\n   "))
    lines += [
        "%d. 交付契约（硬性）：干完把结果写到 %s，JSON 格式：" % (n + 1, result_file),
        '   {"status":"ok|failed","summary":"台面一句话","report":"人读进展报告",'
        '"deliverables":["产物路径…"],"files_changed":["改动文件…"],"evidence":"原始证据"}',
        "   三层口径（各喂各的读者，别混）：",
        "   - summary：≤40 字，结论+对象（如「入轨三处防呆纪律，自测全绿」）。给工单台列表行。",
        "   - report：给人看的进展报告，markdown，短。固定小节「做了什么 / 怎么验证的 /"
        " 遗留与风险」（没有内容的小节省略；review 步的意见在这里分条写）。",
        "     读者是不熟悉本工单的人和你自己的下一棒——写清楚而不是写压缩长句。",
        "   - evidence：机器口径原始证据（命令/路径/关键输出），台面默认折叠，不用照顾可读性。",
        "   结果文件是幂等锚点：已存在则本段视为已完成（重跑安全），所以只在真正完成后写。",
        "%d. 落盘口径：改动写进写集内文件即可，**不要自己 git commit / git add / git worktree，"
        "也不要改 .git 文件、不要用 GIT_DIR 指向自建仓库**（headless 沙箱写不了真 .git——"
        "worktree 的 .git 是指向主库的 gitfile，物理上提交不了；你交付结果文件后 worker 会"
        "确定性代落盘为一个 commit，自建假仓库/改写 gitfile 都会被 worker 检出并隔离）。"
        "判断不了的写进 report 的「遗留与风险」交回，不硬改。" % (n + 2),
    ]
    return "\n".join(lines)


# 模板 id → workflow 类名（client.py ticket-start 选类唯一真源；worker 注册列表与此表一致）
TEMPLATE_CLASS_NAMES: Dict[str, str] = {
    "dev-lane": "DevLaneWorkflow",
    "content-pipeline": "ContentPipelineTicketWorkflow",
    "proofread": "ProofreadWorkflow",
    "regression": "RegressionWorkflow",
    "cleanup": "CleanupWorkflow",
}

# ---- 引擎数据出仓归档路径（sandbar M1-3，t260902-02）----
# 归档真源 = 机器级 per-key 数据目录（契约 v1.4 ①c）：完结工单的 stage 结果/结算
# 报告、会话落盘、UI 证据复制进 <root>/<key>/data/tickets/<id>/，泳道拆除不丢。
# 这段 PROJECT_KEY_RE 是 M1-2 起真源（原在 agent_activities.py，本单上移）：
# 与 server/dsh/suyou-projects.ts 的 PROJECT_KEY_RE 同款字符集，兼防 ../ 路径穿越
# （per-key 凭据/归档路径都要拼目录名）。EPIC_CODE_RE 是既有同款字符集的另一处
# 拷贝（防穿越语义同），两处刻意不合并（各自注释说明字符集来源）。

PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def perkey_projects_root() -> pathlib.Path:
    """per-key 项目目录根（M1-2 真源上移；每次调用现读 env，仿 suyou-projects.ts
    registryRoot 语义）。env 语义与 M1-2 有意差异一致：SANDBAR_PROJECTS_DIR 为空串或
    相对路径 = 视为未设置回落默认根——TS 的 `??` 不剔空串（空串会指到根目录本身），
    这里显式拒绝，不猜。"""
    root = os.environ.get("SANDBAR_PROJECTS_DIR") or ""
    if not root or not os.path.isabs(root):
        return pathlib.Path.home() / ".sandbar" / "projects"
    return pathlib.Path(root)


def ticket_data_dir(project_key: str, ticket_id: str) -> pathlib.Path:
    """完结工单归档目录（M1-3）：<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/data/tickets/<id>/。

    project_key / ticket_id 双双过 PROJECT_KEY_RE 白名单——两者都由外部 meta 拼进
    归档路径，任一越界（../、- 开头等）即 ValueError，调用方不得自行兜底拼接。"""
    key = str(project_key or "").strip()
    if not PROJECT_KEY_RE.match(key):
        raise ValueError("project_key 形状非法：%r（白名单 %s）" % (key, PROJECT_KEY_RE.pattern))
    tid = str(ticket_id or "").strip()
    if not PROJECT_KEY_RE.match(tid):
        raise ValueError("ticket_id 形状非法：%r（白名单 %s）" % (tid, PROJECT_KEY_RE.pattern))
    return perkey_projects_root() / key / "data" / "tickets" / tid


# ---- 契约①d：project.yaml paths 节——项目内路径声明（t260903-03）----
# 引擎不得约定「项目内某固定路径」（sandbar M2 物理搬迁前置）：角色目录与模型
# 路由表两处项目内路径由项目在注册条目顶层可选 paths 节声明（相对项目根），引擎
# 经本读取器取值。契约真源 = docs/design/sandbar项目接入契约v1.md ①d（v1.6）：
#   回落四类（无 paths 节 / 节内缺键 / 条目文件不存在 / project key 空 or 不过
#     白名单）→ 未声明，消费点回落现行约定（suyou 零改动零回归）；
#   声明值畸形 / 条目文件顶层形状不可解析 / 声明锚点缺失或类型错位 → fail-closed
#     红（ProjectPathsError），点名条目文件或解析后路径——三态总纲：文件烂不得
#     按「缺失」静默回落（review R1 裁定）；
#   锚点 vs 内容：per-role 文件缺失维持软跳过、路由表内容损坏继承查表容错
#     （model_route_for 返回 None → 默认模型）——四态只覆盖声明值与锚点。
# 解析基准差异：roles_dir 相对 spawn cwd（泳道 worktree，工单快照语义），
# model_routes 相对条目 dirs[0]（主目录，运行时真源随主仓）。
# 手写解析 stdlib-only（系统 python3 无 pyyaml；spawn 时段条目文件唯一读者是本
# 读取器，装载器只在建票/注册时运行）：顶层只认 schema:/project:/paths:，
# schema 缺失=畸形、非 v1=版本不支持；project: 节内字段形状归装载器（①a）管，
# 这里只取 dirs 列表首项作解析基准。值不含 #（行尾 # 起截断），与装载器
# _strip_line 同口径。过渡状态：现行装载器顶层白名单未放开 paths——声明即被
# ①a 隔离，①d 以放开工单落地为生效前提（债务见 notes/debts/）。

DEFAULT_ROLES_DIR = "server/dsh/roles"   # 回落约定：角色目录（相对项目根）

PATHS_DECL_KEYS = ("roles_dir", "model_routes")


class ProjectPathsError(ValueError):
    """契约①d fail-closed：声明值畸形 / 条目文件不可解析 / 声明锚点缺失或错位。"""


def _entry_paths_parse(text: str, label: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """条目文件最小解析：返回 (paths 声明 dict 或 None, dirs 首项或 None)。
    顶层形状不可解析 = ProjectPathsError（不回落——R1：烂文件必须红）。"""
    schema: Optional[str] = None
    paths: Optional[Dict[str, str]] = None
    main_dir: Optional[str] = None
    section = ""  # 当前所在顶层节名（"" = 还没见到任何顶层键）
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
            # 条目字段形状归装载器管，这里只抓 dirs 列表首项（绝对路径）作解析基准
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
    """paths 声明值校验（契约①d）：非空相对路径，禁绝对/越界/非标量。"""
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


def project_paths(project_key: str, roles_base: str = "",
                  routes_base: str = "") -> Dict[str, Any]:
    """读注册条目 project.yaml 的 paths 节（契约①d 唯一读取入口）。返回：
      {"roles_dir": Path|None, "roles_rel": str|None,
       "model_routes": Path|None, "model_routes_rel": str|None, "main_dir": str|None}

    未声明（回落四类任一）→ 两个 Path/rel 均为 None，消费点回落现行约定；
    声明 → 解析后绝对路径（roles_base 缺省 os.getcwd()，routes_base 缺省条目
    dirs[0]）。本函数只做「解析与声明值校验」——锚点存在性/类型判定归各消费
    点 helper（roles_dir_for_spawn / routes_file_for_spawn，判定基准与真消费
    基准同源，避免单键消费误判另一键锚点）。条目文件只有存在且 key 合法才被
    解析——文件烂 = ProjectPathsError，不静默回落。roles_base / routes_base
    为测试注入位（production 调用点只传 roles_base=str(cwd)）。"""
    key = str(project_key or "").strip()
    info: Dict[str, Any] = {"roles_dir": None, "roles_rel": None,
                            "model_routes": None, "model_routes_rel": None,
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
        rel = _decl_rel("model_routes", paths["model_routes"], label)
        info["model_routes"] = pathlib.Path(base) / rel
        info["model_routes_rel"] = rel
    if "roles_dir" in paths:
        rel = _decl_rel("roles_dir", paths["roles_dir"], label)
        info["roles_dir"] = pathlib.Path(roles_base or os.getcwd()) / rel
        info["roles_rel"] = rel
    return info


def _require_anchor(label: str, key: str, p: pathlib.Path, want: str) -> None:
    """声明锚点存在性/类型判定（fail-closed 红，点名条目文件与解析后路径）。
    缺失与类型错位分开报——语义不同（①d 四态表），红级相同。只判声明锚点，
    回落路径的存在性归各消费点既有软语义（未声明缺失=软跳过/容错，不硬失败）。"""
    if not p.exists():
        raise ProjectPathsError("%s: paths.%s 声明锚点不存在（fail-closed 红）：%s" % (label, key, p))
    if want == "dir" and not p.is_dir():
        raise ProjectPathsError("%s: paths.%s 声明锚点不是目录（类型错位，fail-closed 红）：%s" % (label, key, p))
    if want == "file" and not p.is_file():
        raise ProjectPathsError("%s: paths.%s 声明锚点不是文件（类型错位，fail-closed 红）：%s" % (label, key, p))


def roles_dir_for_spawn(project_key: str, cwd) -> pathlib.Path:
    """spawn 消费点①：角色 preset patch 目录。声明 = project_paths 解析 + 锚点
    fail-closed 判定；未声明回落 <cwd>/server/dsh/roles（现行约定，worktree
    工单快照语义不变，目录缺失不在此炸——具体 <role>.yml 缺失的软跳过归调用点
    既有逻辑，声明与未声明在这层同软）。"""
    info = project_paths(project_key, roles_base=str(cwd))
    if info["roles_dir"] is not None:
        _require_anchor(info["entry"], "roles_dir", info["roles_dir"], "dir")
        return info["roles_dir"]
    return pathlib.Path(cwd) / DEFAULT_ROLES_DIR


def routes_file_for_spawn(project_key: str) -> pathlib.Path:
    """spawn 消费点②：模型路由表文件。声明 = project_paths 解析 + 锚点
    fail-closed 判定；未声明回落 MODEL_ROUTES_FILE（主仓现行约定，逐字节零
    回归）。表内容损坏的容错归 model_route_for（返回 None → 默认模型，①d
    「锚点 vs 内容」明文）。只判 model_routes 锚点，不碰 roles 锚点。"""
    info = project_paths(project_key)
    if info["model_routes"] is not None:
        _require_anchor(info["entry"], "model_routes", info["model_routes"], "file")
        return info["model_routes"]
    return MODEL_ROUTES_FILE


def roles_rel_for_prompt(project_key: str) -> str:
    """prompt 装配消费点：role_doc/kind_doc 的目录基准（相对路径字符串）。
    声明 = 声明值；未声明 = DEFAULT_ROLES_DIR（拼出的文本与改前一致）。
    锚点存在性不在此判（prompt 只是文本指引，红在 spawn 真消费点报）；条目
    文件不可解析照常 fail-closed（ProjectPathsError 上抛）。"""
    info = project_paths(project_key)
    return info["roles_rel"] or DEFAULT_ROLES_DIR


# 归档文件清单口径（契约 v1.4 ①c 附录；activity 扫描与将来消费侧共用同一真源）：
#   入档 = .suyou/stage_*.json（stage 结果/结算报告）、.suyou/screenshots/**/*.png
#   （UI 证据，保相对层级）、.dsh/sessions/<repo-slug>/*（会话落盘事件文件）
#   排除（记入 manifest.excluded_rules，不入档）= agent_*.log（worker spawn 运行时
#   日志）、model_patch_*.yml / resume_patch_*.yml（引擎内部续接物）、.dsh/profiles/**
#   与一切 .credentials.yaml（凭据绝不入档）。会话目录缺失 = 软处理（manifest 记
#   absent），同 usage 端点「历史工单无会话文件」的既有降级口径。
ARCHIVE_INCLUDE_STAGE_GLOB = ".suyou/stage_*.json"
ARCHIVE_INCLUDE_SHOTS_GLOB = ".suyou/screenshots/**/*.png"
ARCHIVE_INCLUDE_SESSIONS_DIR = ".dsh/sessions"
ARCHIVE_EXCLUDED_RULES = (
    "agent_*.log（worker spawn 运行时日志）",
    "model_patch_*.yml / resume_patch_*.yml（引擎内部续接物）",
    ".dsh/profiles/**（profile 镜像）",
    "**/.credentials.yaml（凭据绝不入档）",
)


# 模板 id → 台面展示名（build_suggest_next_prompt 的白名单清单用；host 侧 buildSuggestPrompt
# 的 name 来自 workflow list op，同一语义——改名两边同步）。dev-lane 名与 DevLaneWorkflow.TEMPLATE_NAME 同源。
TEMPLATE_DISPLAY_NAMES: Dict[str, str] = {
    "dev-lane": "开发泳道",
    "content-pipeline": "内容管线",
    "proofread": "审校",
    "regression": "回归",
    "cleanup": "清理",
}
