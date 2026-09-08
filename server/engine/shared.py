"""Temporal POC 公共配置与数据契约。

260823 多项目化清理：工单真源恒为 **Temporal workflow**（v2 模版即代码，base.py 六子类）；
旧 tickets/*.json 投影目录、老 TicketWorkflow/adopt 链已删除。workflow id = 工单 id（单例）；
项目区分 = ProjectKey search attribute（ticket-start 打标，ticket-list --project 过滤）。

保留步1 的 ContentPipelineWorkflow / DispatcherScanWorkflow 与 demo 数据契约（向后兼容）。

路径可被环境变量覆盖（自测用临时目录）：
  SANDBAR_WORKFLOWS_DIR  模板目录（缺省 <repo>/server/workflows）

命名清理（t260907-04，宿主令 260907）：SUYOU_* env → SANDBAR_*、共享队列
suyou-poc → sandbar、泳道协调目录（老名→.sandbar/）。过渡期兼容见  # naming-compat
apply_env_compat / LEGACY_* 常量与 resolve_dot_dir；全量退役账收口在本目录
README「退役账」表（7 条，逐条可观测），撤任何一条前先对表。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---- env 命名过渡（t260907-04）------------------------------------------------
# 语义：SANDBAR_* 为新名真源；双向桥保证过渡期旧调用方（插件面旧代码读 SUYOU_*）
# 与新代码（读 SANDBAR_*）互见。双侧同名冲突 → 新名优先，旧名被新名覆盖。
# 触发时机：import shared 时一次性遍历＋本函数可重复显式调用（幂等）。已知限制：
# import 之后才 setenv 的路径（含 UT 的 monkeypatch）不自动过桥——UT 须在 import
# 前注入，或显式重跑 apply_env_compat(env)。ticket_worker spawn 注入直接走新名
# env，不依赖桥。
# 退役（退役账#6）：插件面票（workbench 旧名清理）收口后，桥降级为单向
# （只 SUYOU_*→SANDBAR_*，不再回写旧名），再一版整函数删除。
LEGACY_ENV_PREFIX = "SUYOU_"
ENV_PREFIX = "SANDBAR_"


def apply_env_compat(environ: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """SUYOU_*↔SANDBAR_* 双向桥（幂等）。返回桥后 env 快照（测试观测用）。"""
    env = os.environ if environ is None else environ
    # 旧→新：旧名单侧出现则补新名（新名已存在且非空时不覆盖——新名优先；
    # 新名为空串视为缺失回落旧名，与现行 `or` 缺省链的 falsy 语义一致）
    for key, value in list(env.items()):
        if key.startswith(LEGACY_ENV_PREFIX):
            new_key = ENV_PREFIX + key[len(LEGACY_ENV_PREFIX):]
            if not env.get(new_key):
                env[new_key] = value
    # 新→旧：新名回写旧名（冲突时新名赢——旧名被新名覆盖；插件面旧代码过渡期读到的
    # 恒为新名的镜像，两侧不漂移）
    for key in [k for k in env if k.startswith(ENV_PREFIX)]:
        env[LEGACY_ENV_PREFIX + key[len(ENV_PREFIX):]] = env[key]
    return dict(env)


apply_env_compat()

# ---- 路径 ----
POC_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = POC_DIR.parents[1]          # server/engine -> 仓库根
ADMIN_PY = REPO_ROOT / "server" / "admin.py"
WORKFLOWS_DIR = pathlib.Path(os.environ.get("SANDBAR_WORKFLOWS_DIR") or (REPO_ROOT / "server" / "workflows"))
OUT_DIR = POC_DIR / "out"

# ---- Temporal 接入点 ----
# 可被环境变量覆盖（测试环境走 Docker 独立 Temporal，见 docs/testing-guide.md）：
#   SANDBAR_TARGET_HOST    Temporal gRPC 地址（缺省生产 127.0.0.1:7233）
#   SANDBAR_NAMESPACE      Temporal namespace（缺省 default）
TARGET_HOST = os.environ.get("SANDBAR_TARGET_HOST") or "127.0.0.1:7233"
NAMESPACE = os.environ.get("SANDBAR_NAMESPACE") or "default"
# 共享队列（t260907-04 改名）：缺省新名 sandbar；SANDBAR_TASK_QUEUE 覆盖（单值，
# 兼容读桥桥出的旧 SANDBAR_TASK_QUEUE）。SANDBAR_TASK_QUEUES（CSV）= 专属 worker
# 的多队列模式（ticket_worker spawn 注入「新 ticket 队列,旧 ticket 队列」双 poll）。
TASK_QUEUE = os.environ.get("SANDBAR_TASK_QUEUE") or "sandbar"
# 退役账#1：旧共享队列过渡双 poll——新代码 worker 同时 poll LEGACY 旧队列（suyou-poc），让以旧队列
# 启动的在飞 workflow 自然流干；撤旧条件 = 旧队列连续一个发布周期零任务且在飞
# 起动的在飞 workflow 流干（观测面：worker 日志双队列行 + temporal
# workflow list），满足后删本常量与 worker 双注册分支。
LEGACY_TASK_QUEUE = "suyou-poc"
TASK_QUEUES_ENV = "SANDBAR_TASK_QUEUES"


def configured_task_queues() -> List[str]:
    """本 worker 应 poll 的队列清单。多队列模式（SANDBAR_TASK_QUEUES CSV）优先；
    缺省 = 新共享队列 + 旧共享队列（退役账#1 过渡双 poll）。"""
    csv = os.environ.get(TASK_QUEUES_ENV)
    if csv:
        queues = [q.strip() for q in csv.split(",") if q.strip()]
        if queues:
            return queues
    return [TASK_QUEUE, LEGACY_TASK_QUEUE]

# ---- 每工单专属 worker（260824 用户拍板）----
# 工单 workflow 不上共享队列：每张工单一个 task queue（sandbar-ticket-<工单id>）+
# 一个专属 worker 进程（ticket create 时拉起，workflow 收口后自退，巡检兜底救/收）。
# 共享队列 sandbar 只留不属任何工单的 workflow（dispatcher-scan；260904 起
# content-pipeline 已退役）。
# 隔离语义：A 工单的旧代码 worker 永远抢不到 B 工单的任务（260824 版本投毒事件教训）。
TICKET_QUEUE_PREFIX = "sandbar-ticket-"
# 退役账#2：旧 ticket 队列前缀——在飞工单的 workflow task queue 在 start 时定死为
# 旧前缀 <id> 队列；其专属 worker 重启后必须同 tid 双前缀 poll，否则旧 workflow
# 永不推进（搁浅）。撤旧条件 = 观测旧前缀队列连续一个发布周期零任务且在飞
# 清单无旧前缀起动的 workflow，随后删本常量、双前缀 poll 与 client 过滤回落。
LEGACY_TICKET_QUEUE_PREFIX = "suyou-ticket-"


def ticket_task_queue(ticket_id: str) -> str:
    """工单专属 task queue 名（新工单恒新前缀；workflow 启动与专属 worker 两边一致）。"""
    return TICKET_QUEUE_PREFIX + ticket_id


def ticket_task_queues(ticket_id: str) -> List[str]:
    """专属 worker 双 poll 清单：新前缀在前（新任务优先被新语义 worker 领）＋旧前缀
    （在飞 workflow 流干用）。共享同一 registry。"""
    return [TICKET_QUEUE_PREFIX + ticket_id, LEGACY_TICKET_QUEUE_PREFIX + ticket_id]

# ---- 多项目化（260823）：工单 workflow 按项目区分，同一个 Temporal 后端 ----
# ProjectKey = Keyword search attribute，值 = 机器级 per-key 注册表 key
# （真源 ~/.sandbar/projects/<key>/project.yaml，sandbar M1-1 出仓；见 server/tools/ticket.py
# 「项目注册表」节与 server/suyou-projects.ts，三处同一注册表口径）。
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
# legacy 常量：import 时固化 env（「先设 env 后 import」语义），运行路径一律走
# resolve_epics_dir（t260907-07 立项单校验项目感知化）。接线后剩余消费面：
#   1. validate_epic_code 默认参数路径（唯一生产消费=server/tools/ticket.py:422
#      list --epic 过滤，写集外遗留——对 external 项目仍按引擎锚拒收）；
#   2. 自测/夹具经 env SUYOU_EPICS_DIR 覆盖（自测语义，与 resolve_epics_dir 的
#      env 现读同键）。
# prepare_epic_next（agent_activities）已迁 resolve_epics_dir，不再消费本常量。
EPICS_DIR = pathlib.Path(os.environ.get("SUYOU_EPICS_DIR") or (REPO_ROOT / "notes" / "epics"))
# 代号形状白名单：沿用 PROJECT_KEY_RE 字符集，同时防 ../../ 路径穿越。
EPIC_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def resolve_epics_dir(project_key):
    """立项档案目录解析单点（t260907-07：CLI 校验锚点=项目注册条目主目录，与
    工单台 UI resolveEpicsDir 同源同规——同一注册表、同一拼装规则 <主目录>/notes/epics）。

    三级解析（仿 registry_root 的「每次调用现读 env」先例；照搬取舍逐项：
    ①env 空串→回落项目锚，带；②env 先 import 后设→现读即生效，带（本票主旨）；
    ③env 指向不存在目录→不预检，由调用侧报错文案兜住，带；④legacy env 互压
    （registry 侧 SUYOU_PROJECTS_YAML＞SANDBAR_PROJECTS_DIR）→不带（epic 目录无
    legacy 单文件模式，引入反增歧义）；⑤隔离条目/空表抛错语义→经 lookup_project
    复用天然继承）：
      1. env SUYOU_EPICS_DIR 非空 → 现读即用（自测语义不变）；
      2. 否则 lookup_project(project_key)['dirs'][0] / notes/epics（未知 key/
         隔离条目 ValueError fail-closed，不静默退引擎仓——契约④三态总纲）；
      3. project_key 空/None → 兜底 REPO_ROOT/notes/epics（引擎锚；生产不可达
         路径——ticket-start 入口拦空 project，仅夹具/在飞工单兼容用，不构成
         语义承诺）。
    """
    env_dir = os.environ.get("SUYOU_EPICS_DIR") or ""
    if env_dir.strip():
        return pathlib.Path(env_dir)
    key = str(project_key or "").strip()
    if not key:
        return EPICS_DIR
    proj = lookup_project(key)
    return pathlib.Path(str(proj["dirs"][0])) / "notes" / "epics"


def validate_epic_code(code: str, epics_dir=None) -> str:
    """ticket-start --epic 强校验（校验单点，client.py 调用；ticket.py 只透传不
    双份实现）。注意：校验单点≠目录锚点单点——目录解析统一走 resolve_epics_dir。

    epics_dir 缺省 None = legacy EPICS_DIR（引擎锚，ticket.py list --epic 遗留
    路径）；调用方应显式传 resolve_epics_dir(project) 做项目感知校验。

    空串放行（允许无 epic 工单）→ 返回 ""。形状非法 / 立项档案不存在 → ValueError
    （文案带实际查询目录——项目锚下即项目主目录 notes/epics，GAP-B 类问题的
    关键诊断信息）。返回归一后的代号（原样；白名单已约束形状）。
    """
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
    """构造工单 typed SA：ProjectKey 恒打 + epic 非空加打 EpicCode。
    temporalio 延迟到函数内 import——本模块保持 stdlib-only（server/tools/ticket.py 直载）。"""
    from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes
    pairs = [SearchAttributePair(SearchAttributeKey.for_keyword(PROJECT_SA_NAME), project)]
    if epic:
        pairs.append(SearchAttributePair(SearchAttributeKey.for_keyword(EPIC_SA_NAME), epic))
    return TypedSearchAttributes(pairs)


# ---- 立项下一单预跑（t260828-08）：merge 签字通过后预跑 integration 建议并落缓存 ----
# 缓存真源 = <repoRoot>/.sandbar/epic-next/<code>/pre.json；读侧 = workbench
# src/host/epic-next.ts readPrecache（互指同步：改一边必须同步另一边）。
# 与同根 <jobId> 形状的 job 目录共存安全：job 目录清理（epic-next.ts cleanupOldJobs）
# 只删「<code>-<base36时间戳>-<6hex>」形状的目录，<code>/ 子目录不在其列。
# state_key 口径（与 epic-next.ts stateKeyFromRows 互指）：sorted "<id>:closed|open"
# 行以 "\n" 拼接后 sha1 hex；**当前预跑工单一律按 closed 计入**（预跑只发生在 merge
# 签字通过后，本票必然收口；host 读侧点击时工单已 closed，两侧口径对齐——否则缓存
# 永不命中，t260828-08 review 第 2 条）。

def epic_next_precache_path(repo_root, code: str) -> pathlib.Path:
    """预跑缓存文件绝对路径（写侧 agent_activities / 读侧 host epic-next.ts 同口径）。
    目录面走 resolve_dot_dir（新名 .sandbar/ 优先、LEGACY 老仓老名粘滞）——老仓粘滞
    旧名时插件面读侧（仍读老名 epic-next 路径）天然不断供；新名仓由写侧镜像补旧名
    （mirror_to_legacy，退役账#5），插件面过渡期同样不断供。"""
    p = lane_dot_path(repo_root, "epic-next", code)
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
    """prepare_epic_next activity 入参：立项代号 + 触发工单（state_key 强制 closed 口径用）。
    project（t260907-07）：项目 key，prepare 读立项档案按 resolve_epics_dir(project)
    锚项目主目录；缺省空串=引擎锚兜底（在飞工单旧载荷兼容，dataclass 默认值解码）。"""

    ticket_id: str
    epic: str
    project: str = ""


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
    return """【任务】你是 sandbar 项目的 integration 角色。本立项的一张关联工单刚通过人审即将合并，请在合并落账前预判：这个立项下一步最应该开的一张工单是什么（或者是否已经无事可做）。

【硬性要求】
1. 这是只读分析任务：除最后的结果文件外，不创建、不修改任何文件，不做任何 git 写操作。
2. 建议的工单模板必须来自下方「可用工单模板」清单，原样填 id，不得发明。
   可用模板面（260904 宿主令收窄）仅 dev-lane：下一单出路只有两类——开新 dev-lane 票，
   或 main 侧直跑验证（无需开票，用 status=done 表达）。
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
    env_fail: int = 0            # t260904-12：环境红维（F-A 修复——翻译层不再丢弃）
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
SCHEDULE_ID = "sandbar-dispatcher-scan"
# 退役账#3：旧 schedule ID（服务端持久标识）。scan_schedule 的 create/ensure 路径
# 建新 ID 前幂等 delete 旧 ID（句柄不存在不炸），日志留痕；本删旧行保留一个发布
# 周期（防旧代码引擎并存时重建旧 schedule 造成双调度），超期整段删除。
LEGACY_SCHEDULE_ID = "suyou-dispatcher-scan"

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
SCAN_DIR = pathlib.Path(os.environ.get("SANDBAR_SCAN_DIR") or (OUT_DIR / "scan"))
# 巡检票落账目录（inspection 票①，t260905-03；env 覆盖供自测用临时目录；
# 缺省 out/inspection，运行产物不入库）。新变量名按宿主令 260904 用 sandbar 前缀
#（存量 SUYOU_* 是历史欠账，只随专门迁移票处置，新造一律不用）。
INSPECTION_DIR = pathlib.Path(os.environ.get("SANDBAR_INSPECTION_DIR") or (OUT_DIR / "inspection"))
# 「疑似卡死」停留时长阈值（小时）。env 可调；activity 读取，不进 workflow 体。
SCAN_STUCK_HOURS = float(os.environ.get("SANDBAR_SCAN_STUCK_HOURS") or 48)
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

# dir 类工作空间根：非开发工单（cleanup/运营类）的隔离目录约定 /tmp/sandbar-ws/<工单id>。
# （M11 v2：env SANDBAR_WS_DIR_BASE 可覆盖——自测指向临时目录，真 /tmp 零污染。）
# 退役账#7：旧 base 粘滞——既有 dir 工单的目录在 LEGACY base（/tmp/suyou-ws）/<id>，ws 路径解析
# 时旧 base 下已存在该工单目录则沿用旧路径（在飞不炸）；退役条件 = LEGACY base
# 存量工单目录清零（观测：ls 旧 base 为空）后删 LEGACY_WS_DIR_BASE 与粘滞分支。
WS_DIR_BASE = os.environ.get("SANDBAR_WS_DIR_BASE") or "/tmp/sandbar-ws"
LEGACY_WS_DIR_BASE = "/tmp/suyou-ws"


def ws_dir_path(ticket_id: str) -> str:
    """dir 类工单工作空间路径（新 base 缺省；旧 base 下已存在同 id 目录→粘滞沿用）。"""
    legacy = pathlib.Path(LEGACY_WS_DIR_BASE) / ticket_id
    if legacy.is_dir():
        return str(legacy)
    return WS_DIR_BASE + "/" + ticket_id


# ---- 泳道协调目录命名过渡（t260907-04）：.sandbar/ → .sandbar/ --------------------
# 解析优先级（三条，次序不可动）：
#   1. base/.sandbar 存在 → 新名（此 base 的 .sandbar/ 若存在仅是插件面镜像，
#      只写不读——镜像目录对解析不可见，防粘滞判定被自身产物自反翻转，R-1）；
#   2. elif base/.sandbar 存在 → 旧名（老泳道粘滞：整生命周期读写都钉旧名，
#      绝不同 base 混用两名，交接/归档零劈叉）；
#   3. else → 新名（create=True 时首写建 .sandbar/，插件面镜像由 mirror 帮手补）。
# 带外建 .sandbar（人工/工具误建）会按规则 1 翻转为新名——单次翻转后权威仍唯一，
# 视为显式迁改名，不是 bug。
# 退役：粘滞分支（规则 2）退役条件 = .sandbar/ 泳道存量清零（README 退役账外独立
# 观测）；镜像帮手退役条件 = 插件面票（workbench 旧名清理）收口（退役账#5）。两者解耦。
DOT_DIR_NEW = ".sandbar"
DOT_DIR_OLD = ".suyou"  # naming-compat
MIRROR_RELPATHS = ("screenshots", "epic-next")   # 插件面真实读点，仅此两类镜像


def resolve_dot_dir(base, create: bool = False) -> pathlib.Path:
    """按三条优先级解析 base 下的泳道协调目录（.sandbar/ 新名优先、DOT_DIR_OLD 粘滞回落）。"""
    b = pathlib.Path(base)
    new = b / DOT_DIR_NEW
    old = b / DOT_DIR_OLD
    if new.exists():
        return new                       # 规则 1：新名权威；旧名仅镜像（只写不读）
    if old.exists():
        return old                       # 规则 2：老泳道粘滞
    if create:                           # 规则 3：创建侧恒新名
        new.mkdir(parents=True, exist_ok=True)
    return new


def lane_dot_path(base, *parts, create: bool = False) -> pathlib.Path:
    """解析后的协调目录下的相对路径（引擎写点/读点统一入口）。"""
    return resolve_dot_dir(base, create=create).joinpath(*parts)


def mirror_to_legacy(base, rel: pathlib.Path) -> bool:
    """插件面过渡镜像：把 base 新名协调目录内的 rel 文件复制到 DOT_DIR_OLD 目录同相对路径。
    仅当解析结果为新名（老泳道本就在旧名，无需镜像）且 rel 顶级目录在
    MIRROR_RELPATHS 白名单内才镜像；best-effort，失败不影响主链。
    退役（退役账#5）：插件面票收口后删本函数与全部调用点。"""
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
    """worktree 泳道默认命名（.lane/t<日期>-<别名> / lane/t<日期>-<别名>；宿主令
    20260903 改名 .worktrees→.lane——名字反映概念不反映 git 细节；旧名兼容见
    _lane_repo_root/replay_check）。

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
    return ".lane/" + wname, "lane/" + wname


# ---------- 票B（t260907-06）：多 repo 项目（父目录作根、repos 为子目录）仓锚推导 ----------
#
# 目录模型真源=docs/design/sandbar项目接入契约v1.md §①a：多 repo 项目=父目录作项目
# 目录、各 repo 为子目录。一票涉多仓时（由写集路径归属推导），泳道=<项目根>/.lane/<id>/
# 普通目录容器，其下每仓一棵树 <lane>/<仓相对项目根路径>；单仓项目（项目根=仓根）
# 不走本节任何函数的激活路径——行为零变化（回归面）。

# refname 安全段清洗族（与 default_lane_paths alias 同一口径）：refname 非法字符
# （空格/~/^/:/?/*/[/\ 等）统一压成 '-'，防 worktree add -b 直接 fail-closed
# （review gen1 附条件 2）。
REFNAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_branch_segment(seg: str) -> str:
    """仓目录名/路径段 → refname 安全段。清洗后为空兜底 'repo'（防全非法名字段）。"""
    s = REFNAME_UNSAFE_RE.sub("-", str(seg)).strip("-")
    return s or "repo"


def flatten_branch_suffix(repo_rel: str) -> str:
    """仓相对项目根路径 → 分支名后缀段（'/'→'-' 再过 refname 清洗）。

    唯一性由仓路径唯一性构造保证（同 basename 形态不碰撞；嵌套仓本身
    fail-closed，见 repos_under 不递归）。"""
    return sanitize_branch_segment(str(repo_rel).replace("/", "-"))


def repos_under(project_root) -> List[pathlib.Path]:
    """项目根下可作泳道挂靠的 git 仓清单（本节唯一扫描真源）。

    - 项目根本身含 .git（目录或 gitfile）→ [项目根] + **一层子仓**集合
      （t260907-12 放宽：根=知识库仓 + 子仓并存的混合形态，根仓也在候选集合内；
      根下无子仓 → 恒 [项目根]，单仓项目行为零变化）；
    - 根不含 .git → 同口径扫**一层**子目录（含 .git 目录或 .git 文件=worktree
      形态仓）。
    一层口径是不变量防线的护栏：引擎自留泳道 .lane/<id>（直属子目录下的二层，
    其 .git=gitfile 指回本仓）绝不能进仓集合，否则带历史泳道的单仓项目
    （sandbar 自身）会被误判多仓形态全链误激活；二层容器目录下的仓（docs/nested
    等）同属集合外，按嵌套仓 fail-closed 拒收——resolve_repos_for_paths 的归属
    候选限定本集合，集合外仓内写集路径创建即拒收，不静默归上层仓（跨仓误结算
    比拒收更糟）。"""
    root = pathlib.Path(project_root)
    repos: List[pathlib.Path] = []
    if (root / ".git").exists():
        repos.append(root)
    if root.is_dir():
        try:
            children = sorted(root.iterdir())
        except OSError:
            children = []  # 不可读目录 best-effort 跳过（扫描真源不因权限炸）
        for child in children:
            if child.is_dir() and (child / ".git").exists():
                repos.append(child)
    return repos


def is_multi_repo_layout(project_root) -> bool:
    """多仓泳道推导激活判定（t260907-12 单点谓词，derive 与 prepare 通道腿共用）。

    True=真多仓形态：根无 .git 且扫得到子仓（票B 原形态），或根=仓 + 至少一个
    子仓并存（混合形态，dengzhufpv 形态）。False=单仓项目（根含 .git 且无子仓）
    ——调用方走旧单仓路径，行为零变化；根无 .git 且无仓同样 False（无仓开不了票，
    由 resolve 的空集合拒收兜底）。"""
    root = pathlib.Path(project_root)
    repos = repos_under(root)
    return bool(repos) and (len(repos) > 1 or not (root / ".git").exists())


def _repo_rel(repo: pathlib.Path, rels) -> str:
    for r, rel in rels:
        if r == repo:
            return rel
    return ""


def resolve_repos_for_paths(project_root, paths) -> Dict[str, List[str]]:
    """写集路径 → 所属仓归属（票B 仓锚推导单一真源）。

    返回 {仓绝对路径字符串: [写集条目…]}；任一条目非法 → ValueError（创建即拒收，
    把「跑 1.5 小时后才暴露」提前到创建瞬间）。口径：
      - 条目必须是项目根相对 posix 路径（非绝对、无 .. 逃逸）；
      - 归属=repos_under 集合内**最长前缀**仓；集合外（含嵌套仓内）→ ValueError；
      - 空仓集合 → ValueError（父目录作根的项目一个仓都没有，开不了工单）。"""
    root = pathlib.Path(project_root).resolve()
    repos = repos_under(root)
    if not repos:
        raise ValueError("项目根 %s 下未发现任何 git 仓（多 repo 项目=父目录作根，"
                         "需先建/clone 子仓再开票；引擎不代建仓）" % root)
    # 仓 → 项目根相对 posix 前缀（长前缀优先，保归属最内层已登记仓）
    # 仓 → 项目根相对 posix 前缀（根仓=空串——relative_to 对根本身产 "."，须归一；
    # 长前缀优先，保归属最内层已登记仓）
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
        owner = None
        for repo, rel in rels:
            # rel=""（根仓，t260907-12 混合形态）→ 兜底命中一切根下路径；
            # 子仓 rel 更长且排序在前 → 最长前缀优先，子仓路径归子仓。
            if not rel or entry == rel or entry.startswith(rel + "/"):
                owner = repo
                break
        if owner is None:
            raise ValueError("写集条目 %r 不落在项目根 %s 下任何 git 仓内"
                             "（嵌套仓 fail-closed：嵌套仓内文件不可开票）" % (entry, root))
        # 嵌套仓判定：归属路径的中途目录若自带 .git 且不在仓集合内 → 该条目实属
        # 集合外嵌套仓，拒收（不静默归外层仓=错仓落账前奏；t260907-06 场景③ F2）。
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
    """项目根相对写集 → 树根相对子集（多仓逐树白名单判据的重基单点）。

    repo_rel=""（单仓）原样透传（回归面：单仓判据逐字节不变）；非空时剥仓前缀，
    不属本仓的条目不进子集。条目恰等于仓目录名本身时不产出（写集语义是仓内
    文件路径，创建校验已挡目录条目，这里兜畸形不炸）。"""
    ws = list(write_set or [])
    if not repo_rel:
        return ws
    prefix = repo_rel + "/"
    return [p[len(prefix):] for p in ws
            if isinstance(p, str) and p.startswith(prefix)]


def build_repo_worktrees(project_root, write_set, lane_dir_name: str) -> List[Dict[str, str]]:
    """由写集归属推导多仓泳道明细（meta.repo_worktrees 形状唯一构造点）。

    返回 [{"repo": 仓相对项目根路径, "name": refname 安全段, "branch": 泳道分支}]；
    树路径 = repo（同名构造，两边零漂移）。分支名 = lane/<泳道目录名>-<压平段>。
    任一输入非法 → ValueError 透传（resolve_repos_for_paths 的 fail-closed 口径）。"""
    if not write_set or not isinstance(write_set, list):
        raise ValueError("多仓泳道推导需要非空写集（write_set 为归属推导唯一输入）")
    root = pathlib.Path(project_root).resolve()  # macOS /var→/private/var 同源化
    base = sanitize_branch_segment(lane_dir_name)
    entries: List[Dict[str, str]] = []
    seen_branch = set()
    for repo_abs, _paths in resolve_repos_for_paths(project_root, write_set).items():
        repo_rel = pathlib.Path(repo_abs).relative_to(root).as_posix()
        if repo_rel == ".":
            repo_rel = ""  # 根仓树（t260907-12 混合形态）：rel 归一空串
        # repo_rel=""（根仓树，t260907-12 混合形态）→ name 显式 "root"（树路径
        # =泳道容器本身）；子仓名恰为 root 的理论碰撞由 seen_branch fail-closed 兜住。
        name = flatten_branch_suffix(repo_rel) if repo_rel else "root"
        branch = "lane/%s-%s" % (base, name)
        if branch in seen_branch:
            raise ValueError("多仓分支名碰撞: %s（压平清洗后仍同名的仓路径需人工改名）" % branch)
        seen_branch.add(branch)
        entries.append({"repo": repo_rel, "name": name, "branch": branch})
    if not entries:
        raise ValueError("多仓泳道推导产出空仓集合（写集 %r）" % (write_set,))
    return entries


def derive_lane_workspace(
        ticket_id: str, template_lane: str, lane: str = "",
        workspace: Optional[Dict[str, str]] = None,
        worktree: str = "", branch: str = "",
        template_workspace_dir: bool = False,
        project_root: str = "",
        repo_write_set: Optional[List[str]] = None,
) -> Tuple[str, Optional[Dict[str, str]], str, str]:
    """lane / workspace / worktree / branch 的推导与校验（创建链路单一真源）。

    project_root（跨项目，t260903-10 首战教训）：给了则把相对泳道路径存成
    绝对路径（锚项目注册目录）——下游九处 ``if not p.is_absolute(): REPO_ROOT/p``
    全走直通分支，引擎根与项目根解耦。缺省空=旧行为（相对路径，运行侧锚
    引擎根，兼容引擎住在项目里的历史 payload）。

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
        # 票B（t260907-06）多仓推导：仅在**真多仓形态**激活（t260907-12 起判定
        # 收敛到 is_multi_repo_layout 单点谓词）——lane=worktree、project_root 给
        # 定、无显式 workspace/worktree 组合、且根无 .git 有子仓（票B 原形态）或
        # 根=仓+子仓并存（混合形态）。任一条件不满足（含单仓项目=根含 .git 且无
        # 子仓、legacy 根无仓布局、dir 道、显式组合）→ repo_write_set 静默忽略，
        # 旧路径零回归（t260904-02 注册锚回归面）。真多仓下推导失败（逃逸/嵌套/
        # 不在仓内）→ ValueError 创建即拒收（fail-closed，不给静默归仓）。
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
            branch = "lane/" + _lane_dir  # meta 兼容占位；真实分支逐仓在 repo_worktrees
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
    # 票B 多仓泳道：workspace.repo_worktrees 在场即多仓票——逐仓校验形状
    #（repo 为项目根相对路径字符串、**允许空串=根仓树**（t260907-12 混合形态，
    # 树=泳道容器本身）、name/branch 非空字符串、branch 唯一）。
    rw = ws.get("repo_worktrees")
    if rw is not None:
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


# ---- 派活上下文索引化（KI-035，t260904-03，宿主令 260904 拍板）----
# 旧制已退役：按 workflow 映射表+标题关键词推导，把设计文档以「必读、按序先读」
# 塞进每段派活头——agent 每会话全文读机制主档（与票面相关性无关的重复 token
# 消耗），且映射与 docs/ 实况手工耦合（260904 迁移即断链，留守 sandbar 的项目域
# 文档仍被指向）。新制=恒定知识库规约：目录=docs/README.md，agent 对照工单
# 标题/写集判断相关性，相关的读全文、不相关不读；结算 note 列「参考 docs 清单」
# 作审计。勿再按 workflow/标题推导必读文档（旧表取值与退役全案见 KI-035 行；
# 零残留由 integration/t260904-03 场景守卫机械把关）。


# 段专项条款（M5②：content-pipeline ai-review 段接 knowledge review 闭环；模板已退役 260904）。
# 本表为留存数据：派活头引擎与 t260904-03 守卫仍在消费。
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
# （不覆盖，agent 用 profile 默认模型）。表=server/model-routes.yaml（工单台
# 「模型」页签可视化编辑，下一次 spawn 即生效——无生成步骤）。契约①d（v1.6）：
# 表路径可由项目注册条目 paths.model_routes 声明（见 routes_file_for_spawn），
# 未声明回落本常量——sandbar 不声明 paths，逐字节零回归。

MODEL_ROUTES_REL = "server/model-routes.yaml"
MODEL_ROUTES_FILE = REPO_ROOT / MODEL_ROUTES_REL


def model_route_for(role: str, kind: str = "",
                    routes_file: Optional[pathlib.Path] = None) -> Optional[Dict[str, str]]:
    """读模型路由表查 (role, kind) 的 provider/model。activity 侧调用（允许 IO）。

    routes_file 缺省 MODEL_ROUTES_FILE；项目声明 paths.model_routes 时由
    routes_file_for_spawn 解析传入（契约①d）。表文件缺失/内容不可解析 = 返回
    None（既有容错语义——agent 用 profile 默认模型；①d「锚点 vs 内容」明文：
    本函数容错覆盖表内容，声不声明同语义，fail-closed 只归锚点判定）。"""
    try:
        import yaml  # pyyaml（engine venv）
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
# M11 v2（t260822-m11-template-as-code）：模版即代码 —— workflow 类共享契约
# （260824 起 code-lane/build-workbench 已删；260904 宿主令 content-pipeline/
# proofread/regression/cleanup 四模版退役，现仅存 dev-lane；历史文档中「五模版/
# 六模版」为删前措辞）
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
    revision_to: str = ""                      # rework 缺省回退目标（原 content-pipeline 修订回路，已退役 260904）
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
    # t260904-18 门①（知识库设计.md §1 工单引用铁律，260904 宿主令）：票面引用的
    # 背景文件清单（仓库相对路径）——建票入口 validate_background_refs 已校验
    # 「已提交且干净（HEAD 态）」，此处原样带入作票面记录；缺省空=旧票不追溯。
    refs: List[str] = field(default_factory=list)
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
    # t260904-18 KI-049 门②：files_changed 的原始形状（解析层保形，消费点判 emptiness
    # 政策）。三态：absent=回执无此字段（旧票/旧回执兼容）；ok=list[str]；
    # malformed=字段在但不是字符串列表（字符串/数字/含非串元素——解析层拒收毁形，
    # 消费点据此可见红，杜绝「字符串逐字符迭代成单字符假列表」绕过新闸）。
    # 带默认值：旧 RUNNING 实例重放历史事件无此字段不破回放。
    files_changed_shape: str = "absent"
    evidence: str = ""


def normalize_files_changed(raw: Any):
    """create_plan 回执 files_changed 保形归一（纯函数，t260904-18 KI-049 门② R1）。

    返回 (files, shape)：shape ∈ "absent" | "ok" | "malformed"。
      - raw is None → ([], "absent")：回执无字段（旧票回落，消费点按跳过语义）；
      - raw 是列表且全为字符串 → (strip 去空后清单, "ok")：emptiness（是否空数组）
        政策留给消费点（design_integration_tests 等段空数组合法）；
      - 其余（字符串/数字/字典/含非字符串元素的列表）→ ([], "malformed")：
        **拒收毁形不清洗**——旧实现 `[str(x) for x in raw]` 会把字符串
        "server/foo.py" 逐字符迭代成单字符假列表，静默绕过闸并污染写集
        （KI-049 姊妹形态，评审 R1 实锤）。畸形在解析层定形，消费点可见红。

    三个解析点（agent_activities._read_result / base / dev_lane 的 activity 回包
    归一处）统一走本函数，替换原强转毁形。"""
    if raw is None:
        return [], "absent"
    if not isinstance(raw, list):
        return [], "malformed"
    if any(not isinstance(x, str) for x in raw):
        return [], "malformed"
    return [x.strip() for x in raw if x.strip()], "ok"


@dataclass
class ReworkRequest:
    """rework signal 载荷：回目标段重跑。target_stage 空 = 缺省（当前段 revision_to 或上一段）。"""

    who: str
    target_stage: str = ""
    note: str = ""


@dataclass
class HostRulingRequest:
    """host_ruling signal 载荷（KI-053，t260905-10 面①）：宿主人工意见的正规注入
    通道，任何状态可发（含 blocked）。who/note 均必填非空——空/纯空白由 workflow
    侧拒收进 refused；note 超 HOST_RULING_NOTE_INPUT_LIMIT 同拒（intake 闸，
    不让超大载荷进 Temporal 事件历史）。"""

    who: str
    note: str


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
    # 票B（t260907-06）多仓通道：write_set+project_root 在场且项目根无 .git（父目录
    # 作根的多 repo 项目）→ prepare 由写集归属推导 repo_worktrees（meta 唯一真源在
    # 建票链 derive_lane_workspace；prepare 按真源推导物校验盘面）。字段带默认值=
    # 存量 RUNNING 实例重放缺键回落，不破回放。单仓项目两字段被忽略（零回归）。
    write_set: List[str] = field(default_factory=list)
    project_root: str = ""


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

# UI 文件口径（t260904-18 KI-050 声明制后的**兼容回落数据源**，不再是活路径真源）：
#   活路径（merge_check 3.6 / ui_changed_paths / review_gate patched 分支）一律吃
#   项目声明（verify.yaml ui_evidence.dirs，load_ui_evidence 装载）；本常量仅供
#   prefixes=None 的旧票重放与冻结/未 patch 分支回落（重放确定性必需），膨胀收窄
#   不再改这里——改 sandbar 的 verify.yaml 声明。物理退役随存量 RUNNING 实例清零。
UI_WRITE_PREFIXES = (
    "server/plugins/workbench/src/client/",
    "server/plugins/workbench/lib/",
    "server/plugins/providers/src/client/",
    "app/src/",
    "app/index.html",
)


# 截图证据目录（t260907-04 起新泳道缺省 .sandbar/screenshots；老泳道由
# ui_evidence_dir() 粘滞解析回 .sandbar/screenshots——capture.mjs --out 与 merge_check
# 闸都走帮手同一解析，不各自判目录名）。本常量仅作文案缺省展示与 fixture 用。
UI_EVIDENCE_DIR = DOT_DIR_NEW + "/screenshots"


def ui_evidence_dir(worktree) -> pathlib.Path:
    """泳道截图目录（粘滞解析：resolve_dot_dir(worktree)/screenshots）。"""
    return lane_dot_path(worktree, "screenshots")

# 截图证据归档目录（相对主树 REPO_ROOT；prepare_ui_evidence 成功后把泳道截图
# 拷进来：<REPO_ROOT>/.sandbar/evidence/<ticket_id>/（老主树 .sandbar/ 粘滞）。泳道
# merge 后拆树，report 里引图不死链靠这份归档；host 只读端点 node.ts evidence
# 路由同口径读它——node 侧 SANDBAR_EVIDENCE_DIR env 覆盖（=归档基目录本体，自测
# 指向临时目录；旧 SUYOU_ 名由 apply_env_compat 双向桥兼容）与
# agent_activities._archive_shots 同名 env 互指，改一边同步另一边）
EVIDENCE_DIR = DOT_DIR_NEW + "/evidence"


def evidence_base(repo_root=None) -> pathlib.Path:
    """主树归档基目录（env 覆盖优先；否则主树协调目录粘滞解析 /evidence）。"""
    env = os.environ.get("SANDBAR_EVIDENCE_DIR")
    if env:
        return pathlib.Path(env)
    return lane_dot_path(repo_root or REPO_ROOT, "evidence")


def match_ui_paths(paths: Any, prefixes: Any = None) -> List[str]:
    """路径清单 × UI 口径前缀表 → 命中的 UI 路径（保序去重，纯函数，无 IO）。

    KI-044 根修（t260904-13）的谓词单点入口：UI 票判定吃**实际 diff 路径**
    （git diff --name-only <merge-base>...branch 的产物 × 本函数），不吃声明写集
    ——声明口径 ≠ 实际写面，粒度越粗关卡越弱（t260904-05 实证：声明整个父目录
    即绕过）。

    KI-050 声明制（t260904-18）：前缀表来源改为**项目声明**（verify.yaml
    ui_evidence.dirs，load_ui_evidence 装载）——参数 prefixes 显式传声明清单；
    prefixes=None（缺省）回落模块级 UI_WRITE_PREFIXES，**仅限旧票重放与冻结/
    未 patch 分支的兼容回落数据源**（注释见该常量处），活路径（merge_check 3.6 /
    ui_changed_paths / review_gate patched 分支）一律显式传声明——不许新调用点
    用单参形态新写。

    容错：非列表/元组、None、空集 → 空清单；元素两端空白 strip；非字符串元素
    忽略；路径按仓库相对路径前缀比对。"""
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
    """写集命中 UI 口径即 UI 票（纯函数，无 IO）——委托 match_ui_paths 单点维护。

    KI-044（t260904-13）后本函数仅存两处合法调用面：review_gate 机械复核
    （dev_lane，声明口径语义）与旧链尾冻结分支（存量实例重放兼容）；UI 票判定
    主通路已换 diff 源（ui_changed_paths activity 与 merge_check 3.6 共用
    agent_activities._ui_diff_paths），勿在新判定路径再引入本函数。
    KI-050 声明制（t260904-18）：prefixes 语义同 match_ui_paths——review_gate
    patched 分支显式传项目声明清单；None 仅限旧分支回落兼容数据源。"""
    return bool(match_ui_paths(write_set, prefixes))


def load_ui_evidence(root: Any):
    """读项目根 verify.yaml 的 ui_evidence 声明（KI-050 声明制，t260904-18 门③）。

    返回 (dirs, note, mode) 三态（对表 verify_lane._cfg_load 同族口径）：
      - ("ok", dirs, "")：声明在场且形状合法（ui_evidence 为映射、dirs 为字符串
        列表；supply 保留字段本版引擎不消费，读时不校验）；
      - ("absent", [], "…note…")：verify.yaml 缺失或无 ui_evidence 键——按项目
        声明关闭：截图证据项 green+可见 note（非 SKIP 非假绿），由调用方拼项；
      - ("malformed", [], "…err…")：声明在场但形状非法（dirs 缺失/非字符串列表）
        ——fail-closed 红，调用方点名 err（畸形 ≠ 缺省，契约②三态总纲）。

    读盘函数：只在 activity/CLI 侧调用（agent_activities / verify_lane 同族），
    workflow 内禁调（确定性纪律；workflow 侧走 meta 预载）。解析用 verify.yaml
    最小子集：本函数只认 `ui_evidence:` 顶层块 + `dirs:` 两空格缩进 `- ` 列表，
    其余块不碰（verify_lane 是道的装载与结构校验真源，两边白名单同票同步）。
    root 缺失/不可读按 absent 处理（泳道根无 verify.yaml 是合法声明态）。"""
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
                # 行内值（如 `ui_evidence: foo`）= 非映射声明，畸形态
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
        # 块内其它键（supply 等）：本版引擎不消费，跳过；但更深层缩进的孤儿行
        # （既不在 dirs 列表里又比块头缩进更深且不是键值行）按畸形处理
        if ":" not in stripped and not stripped.startswith("- "):
            return "malformed", [], "ui_evidence 块含无法解析的行: %s" % stripped
        in_dirs = False
    if not saw_block:
        # 文件里没有 ui_evidence 键 = 声明缺省态（absent），不是畸形
        return "absent", [], "verify.yaml 无 ui_evidence 声明（截图证据项按项目声明缺席）"
    if not saw_dirs:
        return "malformed", [], "ui_evidence 声明缺 dirs 列表"
    return "ok", dirs, ""


def validate_background_refs(refs: Any, project_root: Any):
    """建票背景文件闸（t260904-18 门①；知识库设计.md §1 工单引用铁律，
    260904 宿主令「没提交的 note 不让建工单」）。

    票面引用的背景文件必须**已提交且干净（HEAD 态）**——泳道读的是 HEAD 冻结
    副本，脏改版 agent 读不到。逐文件两查：
      ① `git ls-files --error-unmatch`：已跟踪=已提交进 HEAD 祖先（未跟踪/不存在
         即拒——「未提交」点名）；
      ② `git status --porcelain -- <file>`：输出必须为空（暂存/未暂存/改类型等
         任何脏态即拒——「带脏改」点名，git add 暂存新文件 `A ` 态同样被②捕获）。

    返回 (ok, err)：ok=True 放行建票；err 为逐文件点名的拒收文案（报错必须精确
    ——哪个文件、什么原因）。refs 为 None/空清单 → (True, "")（缺省不校验，
    存量在飞票不追溯，backlog 行口径）；refs 非列表 → 拒收（字符串会被逐字符
    迭代成假清单，t260902-10 同族判例）；条目形态过 _valid_write_set_entry
    （绝对路径/..）→ 拒收。

    查盘函数：只在建票入口（client.py ticket-start，_connect() 之前——拒收路径
    不依赖 Temporal 可达）调用；workflow 内禁调。git 不可用=拒收（fail-closed，
    不静默放行）。"""
    if refs is None or refs == []:
        return True, ""
    if not isinstance(refs, list):
        return False, ("refs 须为路径列表（实际 %s：%r——字符串会被逐字符迭代成假清单）"
                       % (type(refs).__name__, str(refs)[:80]))
    bad_shape = [r for r in refs if not _valid_write_set_entry(r)]
    if bad_shape:
        return False, ("背景文件引用含非法条目（须为仓库内相对路径，禁绝对路径与 '..'）："
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
    worktree: str = ""                        # 泳道 worktree 路径（截图落 <worktree>/.sandbar/screenshots/）
    screenshots_dir: str = ""                 # 缺省 <worktree>/.sandbar/screenshots


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
class UiChangedPathsArgs:
    """ui_changed_paths activity 入参（t260904-13 KI-044 根修：UI 票判定换 diff 源）。"""

    ticket_id: str
    worktree: str = ""                        # 泳道 worktree 路径（diff 锚泳道所属仓，_lane_repo_root）
    branch: str = ""                          # 泳道分支名
    base_ref: str = ""                        # 建票基点（留痕/回放兼容；diff 基线走 merge-base，不吃钉死基点）


@dataclass
class UiChangedPathsResult:
    """ui_changed_paths 回执（git 失败不抛——ui_paths 空即 fail-closed，调用方按「UI 票待证」处理）。"""

    ui_paths: List[str] = field(default_factory=list)  # diff 命中 UI 口径的路径（保序）
    detail: str = ""                          # 判定口径与错误留痕（log / results evidence 消费）


@dataclass
class UiEvidenceDeclArgs:
    """ui_evidence_decl activity 入参（t260904-18 KI-050 门③：声明预载）。

    泳道起跑时读泳道根 verify.yaml 的 ui_evidence 声明落 meta（读盘在 activity、
    workflow 只读 meta=重放安全）；review_gate patched 分支据此判 UI 票。"""

    ticket_id: str
    worktree: str = ""                        # 泳道 worktree 路径（声明读 <worktree>/verify.yaml）


@dataclass
class UiEvidenceDeclResult:
    """ui_evidence_decl 回执（三态同 load_ui_evidence；失败不抛——消费点按声明缺省兜底）。"""

    mode: str = "absent"                      # ok | absent | malformed
    dirs: List[str] = field(default_factory=list)  # 声明的截图证据目录（mode=ok 时有意义）
    note: str = ""                            # 缺省/畸形留痕（log 消费）


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
    随泳道拆除丢失」。worktree 为空 = 主树道工单——协调目录取主树根（resolve_dot_dir 粘滞解析）
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
    """agent 段工作目录：工单登记的 workspace 优先；无 → /tmp/sandbar-ws/<工单id> 隔离目录（LEGACY 老 base 粘滞）
    （主树道工单的 agent 也在仓库根干活，但结果文件/日志一律落隔离目录，主树零污染）。"""
    if isinstance(inp_ws, dict) and inp_ws.get("type") in WORKSPACE_TYPES and inp_ws.get("path"):
        return {"type": str(inp_ws["type"]), "path": str(inp_ws["path"])}
    return {"type": "dir", "path": ws_dir_path(ticket_id)}


def result_file_for(ticket_id: str, stage_id: str, gen: int,
                    ws: Optional[Dict[str, str]]) -> str:
    """本段第 gen 次进入的结果文件绝对路径（幂等锚点；rework 重跑 gen+1 换新文件）。
    目录面走 resolve_dot_dir（写点：老泳道粘滞旧名，新泳道落 .sandbar/，不混用）。"""
    base = (ws or {}).get("path") or ws_dir_path(ticket_id)
    p = pathlib.Path(base)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(lane_dot_path(p, "stage_%s_gen%d.json" % (stage_id, gen)))


def agent_log_for(ticket_id: str, stage_id: str,
                  gen: int, ws: Optional[Dict[str, str]]) -> str:
    """agent 运行日志路径（写点：同 result_file_for 的粘滞口径，不许盲 sed 成新名——
    老泳道日志写进新名目录会绕过粘滞，交接/归档双侧失踪）。"""
    base = (ws or {}).get("path") or ws_dir_path(ticket_id)
    p = pathlib.Path(base)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(lane_dot_path(p, "agent_%s_gen%d.log" % (stage_id, gen)))


# stage 级验收增项（t260901-09）：常驻检查项挂在 prompt 组装真源（build_stage_prompt），
# 按 stage id 键控——build_stage_prompt 由 base.py 与 dev_lane.py 共用，键不命中
# 即零变化（对 base 系 workflow 无影响）；文案自带「不涉及则标注不适用」兜底。
STAGE_ACCEPTANCE_EXTRA: Dict[str, Tuple[str, ...]] = {
    "acceptance_walkthrough": (
        "若本票涉及 UI/泳道图渲染，验收报告必含『并行期 UI 呈现』检查项：并行分叉期"
        "步骤条双边同亮（两步同帧 data-s=running 且各带 ∥ 标记）+ 状态行报"
        "『并行分叉中』，以隔离台实拍/DOM 断言输出为证；不涉及 UI 则标注『不适用』并说明",
        # doc-lifecycle 票②（t260905-01）：收口两问——沉淀触发器+反向同步闸。答与不答
        # 都不阻塞验收，但必须写进结果文件 doc_sediment / doc_conflicts 字段留痕
        # （引擎侧 apply_doc_gate 判读登记；未答也是一条记录，矛盾条目登记债册）。
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


# ---- KI-053（t260905-10 面①）宿主裁决注入面常量 ----
# prompt 只消费末 N 条（旧→新排序，最新贴着「现在」）；note 超 LIMIT 截断加
# _CAP_TRUNC_MARK 标记（不静默切断——review R2 取舍①：agent 不得误以为读到完整
# 指令）；被截全文与掉出 prompt 的旧裁决兜底在 meta['host_rulings']（ticket query
# snapshot 可读）+ 注入留痕事件历史（R2 取舍②）；prompt 预算硬上界
# ≈5×(1200+行头~80)+小节框架 ≈6.6KB，不随裁决数线性膨胀（R2 取舍③）。
HOST_RULING_PROMPT_MAX = 5
HOST_RULING_NOTE_LIMIT = 1200
# 裁决 note 的 intake 上限（dev_lane signal 入参闸，review D2）：超限拒收进 refused
# （文案点名），不进 Temporal 事件历史——与 cap_previous_context 的 HARD_LIMIT 同值族。
HOST_RULING_NOTE_INPUT_LIMIT = 20000


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
        "   ② 知识库：docs/ = 定稿知识库，目录=docs/README.md（每篇一句话用途；"
        "机器索引 docs/index.json 备用）。动手前对照目录与你的标题/写集判断相关"
        "设计文档，相关的读全文，不相关不读。",
    ]
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
    sec = 5
    # KI-053（t260905-10 面①）：宿主裁决注入面——人工意见的正规通道（blocked 态可
    # 注入，注入留痕事件历史）。arbitrate/acceptance 等机械段 prompt 同样消费，
    # 人工意见不再只能借 create_plan/implement 的 rework 备注转达。无裁决时本节
    # 不出现，后续段号维持既有 5/6/7 排布（零回归）。
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
    # 阶段重跑上下文继承：调用方只在本段重跑时才传非空 previous_context，
    # 非空即注入（不拿 gen 当守卫——dev_lane 的 gen 是 0 基，gen>1 会漏掉第一次打回）
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


# 模板 id → workflow 类名（client.py ticket-start 选类唯一真源；worker 注册列表与此表一致）
# 260904 宿主令：仅存 dev-lane（content-pipeline/proofread/regression/cleanup 已退役）
TEMPLATE_CLASS_NAMES: Dict[str, str] = {
    "dev-lane": "DevLaneWorkflow",
}

# ---- 引擎数据出仓归档路径（sandbar M1-3，t260902-02）----
# 归档真源 = 机器级 per-key 数据目录（契约 v1.4 ①c）：完结工单的 stage 结果/结算
# 报告、会话落盘、UI 证据复制进 <root>/<key>/data/tickets/<id>/，泳道拆除不丢。
# 这段 PROJECT_KEY_RE 是 M1-2 起真源（原在 agent_activities.py，本单上移）：
# 与 server/suyou-projects.ts 的 PROJECT_KEY_RE 同款字符集，兼防 ../ 路径穿越
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
#     白名单）→ 未声明，消费点回落现行约定（sandbar 零改动零回归）；
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

DEFAULT_ROLES_DIR = "server/roles"   # 回落约定：角色目录（相对项目根）

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
    fail-closed 判定；未声明回落 <cwd>/server/roles（现行约定，worktree
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
#   入档 = .sandbar/stage_*.json（stage 结果/结算报告）、.sandbar/screenshots/**/*.png
#   （UI 证据，保相对层级）、.dsh/sessions/<repo-slug>/*（会话落盘事件文件）
#   排除（记入 manifest.excluded_rules，不入档）= agent_*.log（worker spawn 运行时
#   日志）、model_patch_*.yml / resume_patch_*.yml（引擎内部续接物）、.dsh/profiles/**
#   与一切 .credentials.yaml（凭据绝不入档）。会话目录缺失 = 软处理（manifest 记
#   absent），同 usage 端点「历史工单无会话文件」的既有降级口径。
ARCHIVE_INCLUDE_STAGE_GLOB = DOT_DIR_NEW + "/stage_*.json"
ARCHIVE_INCLUDE_SHOTS_GLOB = DOT_DIR_NEW + "/screenshots/**/*.png"
ARCHIVE_INCLUDE_SESSIONS_DIR = ".dsh/sessions"
ARCHIVE_EXCLUDED_RULES = (
    "agent_*.log（worker spawn 运行时日志）",
    "model_patch_*.yml / resume_patch_*.yml（引擎内部续接物）",
    ".dsh/profiles/**（profile 镜像）",
    "**/.credentials.yaml（凭据绝不入档）",
)


# 模板 id → 台面展示名（build_suggest_next_prompt 的白名单清单用；host 侧 buildSuggestPrompt
# 的 name 来自 workflow list op，同一语义——改名两边同步）。dev-lane 名与 DevLaneWorkflow.TEMPLATE_NAME 同源。
# 260904 宿主令：仅存 dev-lane（content-pipeline/proofread/regression/cleanup 已退役）
TEMPLATE_DISPLAY_NAMES: Dict[str, str] = {
    "dev-lane": "开发泳道",
}


# ---- 项目注册表（单一真源，t260904-02 自 server/tools/ticket.py 上收）----
# 起因=KI-032（260904 t260904-01 首开脑裂）：裸 client.py ticket-start 不锚
# project_root，泳道相对路径落仓由执行 worker 的 REPO_ROOT 决定。硬闸要求
# client.py 与 ticket.py 用**同一份**装载器锚 project（与 ticket.py:664-669 同源），
# 双份复制必漂移（t260824-04/-10/-11 三次事故的教训），故整块上收至此。
# ticket.py 保留薄壳委托（对外函数名与错误文案逐字不变）；client.py 直 import 本节。
# 本节保持 stdlib-only（server/tools/ticket.py 直载本模块的既定约束）。
# 注意：json/time 的 import 放在本节而非文件头——追加式修订不整体漂移行号
# （notes/debts/known-issues.md 多条条目按行号锚定本文件）。
import json as _json                                # noqa: E402
import time as _time                                # noqa: E402

# 一次性迁移源（旧单文件）。真源=机器级 per-key 目录
# ~/.sandbar/projects/<key>/project.yaml（装载=扫 */project.yaml，与
# server/suyou-projects.ts 同一注册表、两边各自最小解析、语义同构）。
# env 优先级（每次调用现读）：SANDBAR_PROJECTS_YAML（legacy 单文件模式，旧格式
# projects: 列表，行为与 260823 版一致）> SANDBAR_PROJECTS_DIR > ~/.sandbar/projects。
# 单条目畸形/版本不支持=该项目隔离（fail-closed 可见，不炸其他项目）；目录名必须
# 过 PROJECT_KEY_RE 白名单（定义见上=M1-2 真源，勿再复制，acceptance P3 收敛），
# 条目 key 必须与目录名全等；迁移判据只认 .migrated 标记。
PROJECTS_YAML = REPO_ROOT / 'server' / 'projects.yaml'


def registry_root():
    """per-key 注册表根目录（每次调用现读 env，防「先 import 后设 env」覆盖失效）。"""
    return pathlib.Path(os.environ.get('SANDBAR_PROJECTS_DIR') or (pathlib.Path.home() / '.sandbar' / 'projects'))


def strip_registry_line(raw):
    """剥行尾注释 + 右空白；整行注释/空行返回 None（跳过）。本注册表值不含 #。"""
    line = re.sub(r'#.*$', '', raw).rstrip()
    return line if line.strip() else None


def parse_legacy_registry_file(text, label):
    """旧格式单文件解析（projects: 列表）——legacy env 模式与迁移源共用，
    行为与 260823 版 parseProjectsYaml 一致（含 key 重复检查），写坏大声报错。"""
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
    """per-key 单条目解析（project.yaml，契约① schema v1 固定形状）：

        schema: v1            （必带；缺失=畸形；非 v1=版本不支持 fail-closed）
        project:
          - key: <key>
            name: <名>
            dirs:
              - /abs/path

    key 白名单校验在此做；key 与目录名全等的核对由装载方做。"""
    cur = None
    in_dirs = False
    saw_project = False
    in_paths = False   # ①d 放开（t260903 切换夜落地，债 notes/debts/ 对应项销账）：
    schema = None      # 顶层 paths: 节装载器透传不解析（语义/锚点 fail-closed 归
    for i, raw in enumerate(text.split('\n'), 1):  # shared.project_paths ①d 读取器）
        line = strip_registry_line(raw)
        if line is None:
            continue
        if in_paths:
            if raw[:1].isspace():
                continue    # paths 节内行：透传（①d 读取器负责形状与锚点）
            in_paths = False    # 非缩进行=paths 节结束，落回正常顶层处理
        if line == 'paths:':
            in_paths = True
            continue
        if not raw[:1].isspace() and line != 'project:' and not line.startswith('schema:') and i > 1:
            raise ValueError('%s:%d 顶层只认 schema:/project:/paths:' % (label, i))
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
    """per-key 条目序列化（迁移用）：严格子集可往返（值不含 # / 换行，迁移时校验）。"""
    lines = ['# 由 %s 自动迁移（sandbar M1-1），格式=契约① per-key 注册条目，勿手改' % seed_label,
             'schema: v1', 'project:', '  - key: %s' % p['key'], '    name: %s' % p['name'], '    dirs:']
    lines += ['      - %s' % d for d in p['dirs']]
    return '\n'.join(lines) + '\n'


def scan_registry(root):
    """扫注册表根目录：好条目进 projects，坏条目进 quarantined（fail-closed 可见不炸全表）。"""
    projects = []
    quarantined = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith('.'):
            continue
        f = child / 'project.yaml'
        if not f.is_file():
            continue  # 无注册条目的目录（如 data/ 保留位）跳过
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
    """一次性迁移：旧单文件 → per-key 目录。tmp+rename 原子入位；.migrated 独占创建。
    任一步失败抛错（fail-closed）；已入位条目留在现场，下次启动命中半迁移分支显式报出。"""
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
        # 幂等：已有同字节条目直接跳过（二次调用零重写；并发双迁亦收敛）
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
        pass  # 并发首启：另一个进程已写标记，内容等价，忽略


def _registry_tmp_name(target):
    """并发安全的临时文件名：进程唯一后缀（确定性 tmp 名会被并发双迁互踩，
    赢家 rename 后输家撞 FileNotFoundError，t260901-14 集成测试实测）。"""
    return '%s.tmp.%s.%s' % (target, os.getpid(), _time.time_ns())


def _expected_registry_entries(projects, seed_label):
    """迁移期望表：种子每条目 → 迁移会写出的精确文本（续迁判等用）。"""
    return {p['key']: serialize_registry_project(p, seed_label) for p in projects}


def _resume_registry_migration(root, expected, on_disk_keys):
    """续迁：只补写种子里缺失的条目（盘上已有的不动，防覆盖人工改动），最后补 .migrated。"""
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
        pass  # 并发：另一个进程已写标记，内容等价，忽略


def ensure_registry_migrated(root):
    """per-key 模式装载前的一致性检查：跳过判据只认 .migrated。无标记且根里有内容时，
    区分三类现场（修订 v2.1，实现期自测发现——字面「有内容无标记=fail-closed」会把
    正常手工注册的注册表全部判死）：
    - 纯人工注册表（盘上 key 与种子零交集，或种子不在时）→ 接受；
    - 崩溃残留/丢标记（盘上全是种子条目的精确文本子集，无隔离）→ 续迁补齐 + 补标记；
    - 混合现场（部分相关但不可复现）→ fail-closed 抛错，人工处置，不静默跳过。"""
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
        return  # 纯人工注册表：种子不在，无从判定也无从迁移，接受现状
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
        return  # 纯人工注册表（与种子无关），接受现状
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
    """装载注册表全量，返回 (projects, quarantined)。
    legacy env（SANDBAR_PROJECTS_YAML）在位时走旧单文件模式（无隔离概念）。"""
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
    """空注册表统一报错（三分支全显式）：无任何条目 / 全部被隔离（列原因）。"""
    if projects:
        return
    if quarantined:
        reasons = '；'.join('%s（%s）' % (q['dir'], q['error']) for q in quarantined)
        raise ValueError('注册表没有任何可用项目条目：全部 %d 条被隔离——%s'
                         % (len(quarantined), reasons))
    raise ValueError('注册表没有任何项目条目')


def lookup_project(key):
    """按 key 查注册表项目；缺失/未知一律 ValueError（无默认值）。返回 {key,name,dirs}。
    key 对应隔离条目时错误文案带目录+原因（fail-closed 可见，不静默当未知）。"""
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
    """显式给的绝对路径必须落在该项目注册目录之一（防把别的项目的目录登记进来）；
    相对路径不拦（执行侧对项目主目录解析）。"""
    for label, p in (('workspace', (ws or {}).get('path') or ''), ('worktree', worktree or '')):
        if p.startswith('/') and not any(p == d or p.startswith(d.rstrip('/') + '/') for d in proj['dirs']):
            raise ValueError('%s 路径 %s 不在项目 %s 的注册目录内（%s）'
                             % (label, p, proj['key'], '、'.join(proj['dirs'])))


# ---- worker 归属指纹（KI-033，t260904-02）----
# 工单 worker 注册带引擎仓指纹：worker 自写 meta JSON（repo_root 绝对路径），
# temporal-tools ensureTicketWorkers 读取判定异仓（告警+拒接，不杀别人进程）。
# 指纹=repo_root realpath 而非 git HEAD——同仓先后 commit 不该误判异仓
# （supervisor 与 worker 常是先后从同一棵树起的）。纯函数落此（stdlib-only），
# worker.py 只留薄接线。
WORKER_META_VERSION = 1


def worker_meta_payload(repo_root=None, pid=None) -> Dict[str, Any]:
    """meta JSON 内容：{version, pid, repo_root, ts}（ts=epoch 秒；字段名=工单场景
    契约）。repo_root 走 realpath（比对双方用同一规范化口径，符号链接差异不产生
    假异仓）。"""
    root = os.path.realpath(str(repo_root if repo_root is not None else REPO_ROOT))
    return {
        'version': WORKER_META_VERSION,
        'pid': int(pid if pid is not None else os.getpid()),
        'repo_root': root,
        'ts': int(_time.time()),
    }


def write_worker_meta(path, repo_root=None, pid=None) -> Optional[Dict[str, Any]]:
    """best-effort 写 meta（归属指纹是可观测性增强，写失败不阻断 worker 启动——
    ensure 侧对缺失态有 unknown 处理，不会因写失败而误判异仓）。返回 payload。"""
    payload = worker_meta_payload(repo_root=repo_root, pid=pid)
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
    """读 meta，返回 (meta|None, state, detail)。state 四态：
    ok / missing（文件不在）/ malformed（JSON 坏或形状错）/ read_error（其它读失败）。
    失败态分开报，保证 ensure 侧兼容跳过时可定位（review C3：不许哑巴）。"""
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
    """引擎 venv 解释器解析（t260907-10 目录重构回落链）。

    新路径 server/engine/.venv 优先；回落旧路径 server/dsh/temporal-poc/.venv
    （迁移窗口期一轮——主树 .venv 物理迁移完成前后各有一段旧路径存活期；
    回落摘除票落地后本函数退化为单路径）。
    畸形输入 fail-closed：repo_root 不存在/非目录/候选非普通文件/不可执行 → None，
    由调用方显式报错或回落系统解释器，不静默假装可用。
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
