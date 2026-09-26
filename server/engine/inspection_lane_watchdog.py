#!/usr/bin/env python3
"""inspection_lane_watchdog — 「票卡在泳道里」的纯判据面（KI-122 追加面 / KI-126 同源）。

宿主追问（260926）「巡检发现这个问题了吗」→ **没有**：巡检各面只读**制品与代码**（套件回执、
变化面 diff、KI 清单、台账），**没有一面读票的工作流时间线**——而活锁只体现在泳道层（同一票
`gate → tests-fault → 重跑` 的循环）。KI-122 最早是人（integration 岗）读票时间线发现的，
不是巡检发现的。本模块补这一路：与 `suite`/`deadman`/`skip` 族**并列的机械发现源**。

三族发现（英文文案；数据字段=票号/stage id/verdict/轮次壁钟等**不译**）：

  ① `rerun-rounds`      同票重跑轮次 > N（N=`rerun_rounds`，缺省 3）→ med；> 2N → high。
                        点名票号 + 轮次 + 每轮墙钟（由相邻「进入本步」记录的 at 差分；末轮
                        「在飞」）。
  ② `tests-fault-loop`  停在 tests-fault 回路超时：最近一次仲裁判决 = tests-fault 而下判决
                        之后停留 > `fault_loop_min`（缺省 90 分钟）→ high。点名票号 + 判决
                        + 停留时长（判决已下却不收敛）。
  ③ `inflight-silent`   在飞超阈值无进展（僵尸票，KI-126 同源）：距时间线最后一条进展 >
                        `inflight_silent_min`（缺省 120 分钟）→ high。点名票号 + stage +
                        静默时长。**不适用于「不在飞」的三态**（260926 复核缺陷⑤）：`paused`
                        （KI-122 的止血动作本身）/ `status=blocked` / `stage_state=awaiting*`
                        （等待人门，设计内可挂数小时到数日）——这三态**不出本族**，改在
                        `meta.suppressed`/`section.suppressed` 逐条点名（降级可见，但不假报
                        「in flight」：文案「while in flight」对它们与事实相反，且每期含一张
                        等人签字票就会把 `lane.finding_count>0 ⇒ heartbeat=False` 打成恒假）。

  ⓪ `data-unreadable` 读面降级（260926 复核缺陷⑥，low）：快照读不懂（`parse_notes` 非空）
                        且**三族都无命中** → 一条 low 发现（逐个点名读不懂的项）。为什么必须
                        有：读不到快照事实的票与真正干净的票在结果上不可区分（对非 dev-lane
                        模板、老票、快照键漂移的票尤其危险，而本面按 B3 明确扫**全部项目**的
                        票）——「畸形一律逐项降级并点名，绝不当成零发现静默吞」是本模块自己
                        的纪律。有命中族时 notes 已随各自 evidence 上台面，不重复出条。

第四判据（260926 补，**宿主级**而非票级；宿主两次追问「巡检为什么没发现」）：

  ④ `tmp-fixture-water` 测试夹具临时目录水位：`$TMPDIR` 顶层**白名单前缀**（测试夹具）
                        的真目录数 > `tmp_fixture_max_dirs`（缺省 1000）或最老目录年龄 >
                        `tmp_fixture_max_age_h`（缺省 6h）→ med；两条同时越线 → high。
                        为什么单列一族：①②③ 看的是**票卡在泳道里**，而 260926 这轮事故是
                        **磁盘在漏**（`$TMPDIR` 顶层实测 407,294 个目录、401,578 个 >6h
                        =98.6%，大头是 `mkdtemp` 夹具从不回收）——三族几何上就看不见它。
                        判据只吃活动壳**只读**扫出来的 `(name, mtime)`（本模块零 IO），
                        白名单外一律不计（宿主 temp 里还有别的程序的东西）；处置动作写在
                        why 里（跑 `integration/tools/sweep_tmp_fixtures.py` 回收存量 +
                        查生产者侧新漏点）。

纪律（与巡检红线一致，本模块=纯函数，零 IO/零网络/零临时依赖）：
  - **绝不写状态、绝不推进票**：本模块只吃快照事实、只吐发现条目；读面 IO 全在活动壳
    （activities.run_inspection_lane_watchdog，只 query 只 list）。
  - **每票聚合**：同一票命中多族 → **一条**发现（`legs` 列全部命中族），不按族刷屏。
  - **suggest=False**：三族都是**流程层**故障（票/回路/供给节奏），不是被审仓里某文件某行的
    代码缺陷——开「修码票」是错配（同 deadman 漏跑口径）；处置动作写在 why 里。
  - 畸形入参（快照非 dict / 时间戳不可解 / 轮次非数）一律**逐项降级并点名**，绝不抛、
    绝不当成「零发现」静默吞。

阈值来源（宿主 260926 护栏②）：声明侧 `inspection.yaml` 实例级 `watchdog:` 档
（`rerun_rounds`/`fault_loop_min`/`inflight_silent_min`）；缺失/畸形 → 回落本模块缺省，且
**面/回执上点名来源**（`threshold_source`=declaration|default + 逐键回落原因），不静默。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 发现来源标记（票面 findings[].scan；与 deadman/suite/agent 等并列）
LANE_SCAN = "lane"

#: 三族 token（发现条目的 legs 列表；机读计数按此聚合）——**票级**三族语义不动
LEG_RERUN = "rerun-rounds"
LEG_FAULT_LOOP = "tests-fault-loop"
LEG_INFLIGHT = "inflight-silent"
LANE_LEGS = (LEG_RERUN, LEG_FAULT_LOOP, LEG_INFLIGHT)

#: 第四判据 token（宿主级水位；不进 LANE_LEGS——票级三族的计数口径与断言保持逐字不变）
LEG_TMP_FIXTURE = "tmp-fixture-water"

#: 第五 token（读面降级，low）：快照读不懂且票级三族无命中时的具名发现（260926 复核缺陷⑥）。
#: **不进 LANE_LEGS**：三族是「票卡在泳道里」的判定面，本族是「没读成」的可见性面，塞进
#: 三族会把按族聚合的计数口径（含既有逐字断言）改掉；它只在真降级时出现在 by_leg 里。
LEG_DATA_UNREADABLE = "data-unreadable"

#: ③族（inflight-silent）**不适用**的票态（260926 复核缺陷⑤）：这三态都不是「在飞」——
#: paused=KI-122 止血动作本身；blocked=等人审签字；stage_state 含 awaiting=等**人门**
#: （base.py 设计内可挂数小时/数日）。命中这三态时本族不出条，逐条进 meta.suppressed。
INFLIGHT_INAPPLICABLE_STATUS = "blocked"

#: 已知测试夹具前缀白名单（**同一份清单**也用于 integration/tools/sweep_tmp_fixtures.py；
#: 两处一致性由机械漂移锁钉住：server/engine/tests/test_t260926_tmp_fixture_water.py
#: ::test_e1_prefix_whitelist_single_source）。白名单之外一律不计入水位——宿主 temp 目录里
#: 还有别的程序（实测 `com.google.Chrome.*` 4,380 个目录）与别项目（`nusuyou-*`）的东西。
TMP_FIXTURE_PREFIXES = (
    "integ-e2e-fixture-",
    "lint-pyc-",
    "fix10-", "fix14-", "fix17-",
    "pathgate-",
    "t260907-06-ut-",
    "t260907-12-ut",
    "sandbar-agent-presets-",
    "t26092212-", "t260906-", "lease-ut-", "t260904-02-", "t260901-21-",
    "t02-lane", "venv-compat-root", "t26090704-lane",
    "wb-",
)

#: 模块缺省阈值（真源；声明侧同名键可覆盖）。rerun_rounds 缺省 3 = 抓得住今天这种
#: 「同一票 5 轮 × ~2h 全量」的形态；两道时间阈值单位=分钟。
DEFAULT_RERUN_ROUNDS = 3
DEFAULT_FAULT_LOOP_MIN = 90
DEFAULT_INFLIGHT_SILENT_MIN = 120

WATCHDOG_KEYS = ("rerun_rounds", "fault_loop_min", "inflight_silent_min")
#: 键 → (下限, 上限)：rerun_rounds 正整数上限防呆；两道时间阈值上限=7 天（10080 分钟）
WATCHDOG_RANGES = {"rerun_rounds": (1, 1000),
                   "fault_loop_min": (1, 10080),
                   "inflight_silent_min": (1, 10080)}
WATCHDOG_DEFAULTS = {"rerun_rounds": DEFAULT_RERUN_ROUNDS,
                     "fault_loop_min": DEFAULT_FAULT_LOOP_MIN,
                     "inflight_silent_min": DEFAULT_INFLIGHT_SILENT_MIN}

#: 第四判据（水位）阈值键/缺省/范围：**独立三件套**——票级三族的缺省字典与取值语义
#: 逐字不变（票级面消费方与既有断言零回归），水位面走 WATCHDOG_ALL_* 的并集。
#: max_dirs 取 1000 的理由：修前的实况是 27.7 万（四个数量级），1000 稳稳抓住「漏了」的
#: 形态；而现存 69 个未回收夹具库跑一天的量级在数百以内，不该天天报（阈值可声明可环境
#: 覆盖）。max_age_h 取 6h：与清扫器/`.mjs` 复收器的龄阈值同口径——「没有任何活套件会用到
#: 它了」的那条线，越过它=有人该回收而没回收。
DEFAULT_TMP_FIXTURE_MAX_DIRS = 1000
DEFAULT_TMP_FIXTURE_MAX_AGE_H = 6
TMP_WATCHDOG_KEYS = ("tmp_fixture_max_dirs", "tmp_fixture_max_age_h")
TMP_WATCHDOG_RANGES = {"tmp_fixture_max_dirs": (1, 10_000_000),
                       "tmp_fixture_max_age_h": (1, 8760)}
TMP_WATCHDOG_DEFAULTS = {"tmp_fixture_max_dirs": DEFAULT_TMP_FIXTURE_MAX_DIRS,
                         "tmp_fixture_max_age_h": DEFAULT_TMP_FIXTURE_MAX_AGE_H}

#: 声明档的**合法键全集**（票级三键 + 水位两键）与合并字典：声明解析件（inspection_decl）
#: 用前者判「未知字段」，水位面用后者取值——两处都从这里取，绝不各造一份。
WATCHDOG_ALL_KEYS = WATCHDOG_KEYS + TMP_WATCHDOG_KEYS
WATCHDOG_ALL_RANGES = dict(WATCHDOG_RANGES, **TMP_WATCHDOG_RANGES)
WATCHDOG_ALL_DEFAULTS = dict(WATCHDOG_DEFAULTS, **TMP_WATCHDOG_DEFAULTS)

THRESHOLD_SOURCE_DECL = "declaration"
THRESHOLD_SOURCE_DEFAULT = "default"
#: 第三来源（水位面独有）：运维经环境变量显式覆盖缺省。**绝不静默**——被点名在
#: threshold_note / 票面段里；声明侧仍是优先级最高（改声明即改行为），env 只补声明没写的键。
THRESHOLD_SOURCE_ENV = "env"

#: 环境变量名（真源；活动壳读取后**传入**纯函数，本模块自己不读环境）
TMP_ENV_MAX_DIRS = "SANDBAR_TMP_FIXTURE_MAX_DIRS"
TMP_ENV_MAX_AGE_H = "SANDBAR_TMP_FIXTURE_MAX_AGE_H"

#: 发现清单里的证据文本上限（防票面洪泛；超长截断并点名）
EVIDENCE_CAP = 1200
#: 每轮墙钟单列条数上限（超出的轮次只报计数）
WALL_LIST_CAP = 8
#: 水位证据里逐前缀明细的条数上限（只列命中数最多的前 N 个）
PREFIX_LIST_CAP = 8

_INT_RE = re.compile(r"^\d+$")


# ========================================================================================
# 阈值：声明档 → 生效值 + 来源（纯函数；畸形一律回落缺省并点名，不抛）
# ========================================================================================

def resolve_thresholds(raw: Any = None):
    """声明 `watchdog:` 档 → (thresholds, source, note, problems)。

    - raw 非映射 / 键不在 WATCHDOG_KEYS / 值非正整数或越界 → 该键回落模块缺省；
    - source=declaration 仅当**每个**键都来自声明且合法；否则 default；
    - note=英文一行（面/回执展示用，点名来源与逐键回落原因）；
    - problems=逐键英文原因列表（声明校验件据此 fail-closed 报错；运行期消费方按缺省跑）。

    纯函数零 IO：**绝不**在这里读文件/环境——来源判定只看入参（调用方给的就是声明解析结果）。
    """
    thr = dict(WATCHDOG_DEFAULTS)
    problems: List[str] = []
    if raw is None:
        return thr, THRESHOLD_SOURCE_DEFAULT, (
            "threshold source=default (no watchdog declaration; module defaults "
            "%s)" % _fmt_thresholds(thr)), problems
    if not isinstance(raw, dict):
        problems.append("watchdog declaration is not a mapping (%s)" % type(raw).__name__)
        return thr, THRESHOLD_SOURCE_DEFAULT, (
            "threshold source=default (watchdog declaration malformed: not a mapping)"), problems
    unknown = sorted(set(raw) - set(WATCHDOG_ALL_KEYS))
    if unknown:
        problems.append("unknown watchdog keys: %s (allowed: %s)"
                        % (", ".join(unknown), ", ".join(WATCHDOG_KEYS)))
    for k in WATCHDOG_KEYS:
        if k not in raw:
            problems.append("%s absent -> module default %d" % (k, WATCHDOG_DEFAULTS[k]))
            continue
        v = raw.get(k)
        lo, hi = WATCHDOG_RANGES[k]
        ok = (isinstance(v, str) and _INT_RE.match(v) and lo <= int(v) <= hi) \
            or (isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi)
        if not ok:
            problems.append("%s=%r rejected (integer %d~%d) -> module default %d"
                            % (k, v, lo, hi, WATCHDOG_DEFAULTS[k]))
            continue
        thr[k] = int(v)
    from_decl = not problems
    source = THRESHOLD_SOURCE_DECL if from_decl else THRESHOLD_SOURCE_DEFAULT
    note = ("threshold source=%s (%s)" % (
        source, _fmt_thresholds(thr) if from_decl
        else "fallbacks: " + "; ".join(problems)))
    return thr, source, note, problems


def _fmt_thresholds(thr: Dict[str, Any]) -> str:
    return ("rerun_rounds=%d fault_loop_min=%d inflight_silent_min=%d"
            % (int(thr.get("rerun_rounds") or 0), int(thr.get("fault_loop_min") or 0),
               int(thr.get("inflight_silent_min") or 0)))


def resolve_tmp_thresholds(raw: Any = None, env: Any = None):
    """水位面阈值（第四判据）→ (thresholds, source, note, problems)。

    优先级（逐键）：**声明** > 环境变量覆盖 > 模块缺省。为什么 env 排在声明之后：
    「改声明即改行为」是本项目的单源纪律——声明写了的值任何人都不能悄悄改掉；env 只补
    声明**没写**的键（运维临时放宽/收紧），且来源必须点名（绝不静默）。

    - raw=声明 `watchdog:` 档原值（str，YAML 子集无类型推断）；env={"SANDBAR_...": str|None}；
    - 键缺失/畸形/越界 → 逐键回落并在 problems 里点名（消费方按缺省跑，声明校验件据此报错）；
    - source ∈ {declaration, env, default}；note=英文一行，带逐键来源（票面/回执展示用）；
    - 纯函数零 IO：**不读文件、不读进程环境**——env 由调用方（活动壳）读好传进来。
    """
    thr = dict(TMP_WATCHDOG_DEFAULTS)
    problems: List[str] = []
    origin: Dict[str, str] = {k: THRESHOLD_SOURCE_DEFAULT for k in TMP_WATCHDOG_KEYS}
    decl = raw if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        problems.append("watchdog declaration is not a mapping (%s)" % type(raw).__name__)
    env_map = env if isinstance(env, dict) else {}
    for k in TMP_WATCHDOG_KEYS:
        lo, hi = TMP_WATCHDOG_RANGES[k]
        if k in decl:
            v = decl.get(k)
            ok = (isinstance(v, str) and _INT_RE.match(v) and lo <= int(v) <= hi) \
                or (isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi)
            if ok:
                thr[k] = int(v)
                origin[k] = THRESHOLD_SOURCE_DECL
                continue
            problems.append("declared %s=%r rejected (integer %d~%d) -> fallback"
                            % (k, v, lo, hi))
        env_name = TMP_ENV_MAX_DIRS if k == "tmp_fixture_max_dirs" else TMP_ENV_MAX_AGE_H
        ev = env_map.get(env_name)
        if ev not in (None, ""):
            ok = (isinstance(ev, str) and _INT_RE.match(ev) and lo <= int(ev) <= hi) \
                or (isinstance(ev, int) and not isinstance(ev, bool) and lo <= ev <= hi)
            if ok:
                thr[k] = int(ev)
                origin[k] = THRESHOLD_SOURCE_ENV
                continue
            problems.append("env %s=%r rejected (integer %d~%d) -> fallback"
                            % (env_name, ev, lo, hi))
        if k not in decl:
            problems.append("%s absent -> module default %d" % (k, TMP_WATCHDOG_DEFAULTS[k]))
    origins = set(origin.values())
    source = (THRESHOLD_SOURCE_DECL if origins == {THRESHOLD_SOURCE_DECL}
              else THRESHOLD_SOURCE_ENV if THRESHOLD_SOURCE_ENV in origins
              else THRESHOLD_SOURCE_DEFAULT)
    note = "threshold source=%s (%s)" % (
        source, ", ".join("%s=%d/%s" % (k, int(thr[k]), origin[k]) for k in TMP_WATCHDOG_KEYS))
    if problems:
        note += " | fallbacks: " + "; ".join(problems)
    return thr, source, note, problems


# ========================================================================================
# 快照 → 票事实（纯函数：dict → 规范事实；畸形逐项降级并点名）
# ========================================================================================

def parse_iso_epoch(value: Any) -> float:
    """ISO 时间串 → epoch 秒（不可解=0.0，绝不抛；0.0=「未测到」而不是「此刻」）。"""
    if not isinstance(value, str) or not value.strip():
        return 0.0
    txt = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(txt).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _num(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f else 0.0     # NaN → 0.0


def facts_from_snapshot(ticket_id: str, project: str, snapshot: Any,
                        *, workflow_id: str = "", now_ts: float = 0.0) -> Dict[str, Any]:
    """票快照（query("snapshot") 的 JSON 结果）→ 规范事实字典（纯函数，零 IO）。

    只读面用到的键：`stage`/`stage_state`/`status`/`gens`/`results`/`timeline`/`meta`。
    数据畸形逐项降级进 `parse_notes`（可见、不静默）：缺键=该事实为「未测到」（0/""），
    绝不当成「无问题」的默认值参与判据（消费外部输入的 fail-closed 纪律）。

    判决解析用 `shared.parse_arbitration_summary`（**单写者**：与 dev_lane 仲裁路由同一份
    判据），本模块不另造 verdict 识别法。
    """
    notes: List[str] = []
    facts: Dict[str, Any] = {
        "ticket_id": str(ticket_id or ""), "project": str(project or ""),
        "workflow_id": str(workflow_id or ticket_id or ""),
        "stage": "", "stage_state": "", "status": "",
        "verdict": "", "verdict_at": 0.0,
        "suite_rounds": 0, "suite_entries": [],
        "last_activity_at": 0.0, "created_at": 0.0,
        "paused": False, "blocked_reason": "",
        "parse_notes": notes,
    }
    if not isinstance(snapshot, dict) or not snapshot:
        notes.append("snapshot missing or not an object (%s)" % type(snapshot).__name__)
        return facts
    facts["stage"] = str(snapshot.get("stage") or "")
    facts["stage_state"] = str(snapshot.get("stage_state") or "")
    facts["status"] = str(snapshot.get("status") or "")
    facts["paused"] = bool(snapshot.get("paused"))
    facts["blocked_reason"] = str(snapshot.get("blocked_reason") or "")
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    facts["created_at"] = _num(meta.get("created"))
    if not facts["created_at"]:
        notes.append("meta.created absent/unparseable (ticket age unknown)")

    # ---- 重跑轮次与每轮墙钟：真源=时间线「进入本步」记录（stage+state=running），
    # ---- 交叉核对 gens[stage]（快照的代数计数；两者不一致取大者并在 note 点名）。
    timeline = snapshot.get("timeline") if isinstance(snapshot.get("timeline"), list) else []
    if not isinstance(snapshot.get("timeline"), list):
        notes.append("timeline absent/not a list (re-run rounds unknown)")
    entries: List[float] = []
    gens_seen: List[int] = []
    ats: List[float] = []
    for e in timeline:
        if not isinstance(e, dict):
            notes.append("timeline entry is not an object (skipped)")
            continue
        at = parse_iso_epoch(e.get("at"))
        if at:
            ats.append(at)
        elif e.get("at"):
            notes.append("timeline entry has an unparseable at=%r" % (e.get("at"),))
        if str(e.get("stage") or "") != "run_integration_tests":
            continue
        if str(e.get("state") or "") != "running":
            continue
        entries.append(at)
        g = e.get("gen")
        if isinstance(g, int) and not isinstance(g, bool) and g > 0:
            gens_seen.append(g)
    gens = snapshot.get("gens") if isinstance(snapshot.get("gens"), dict) else {}
    gen_count = gens.get("run_integration_tests")
    gen_count = int(gen_count) if isinstance(gen_count, int) and not isinstance(gen_count, bool) \
        and gen_count > 0 else 0
    facts["suite_entries"] = sorted(a for a in entries if a)
    facts["suite_rounds"] = max(len(facts["suite_entries"]), max(gens_seen or [0]), gen_count)
    if entries and not facts["suite_entries"]:
        notes.append("suite entries present but every at is unparseable (wall clock unavailable)")
    if gen_count and len(facts["suite_entries"]) and gen_count != len(facts["suite_entries"]):
        notes.append("gens[run_integration_tests]=%d != timeline entries %d (taking the larger)"
                     % (gen_count, len(facts["suite_entries"])))

    # ---- 最近一次仲裁判决：真源=results.arbitrate.summary（单写者解析）+ 判决进入时刻
    # ---- （时间线上最后一次 arbitrate/running 记录的 at）。
    verdict, verdict_at = "", 0.0
    results = snapshot.get("results") if isinstance(snapshot.get("results"), dict) else {}
    arb = results.get("arbitrate") if isinstance(results.get("arbitrate"), dict) else {}
    raw_summary = arb.get("summary")
    from shared import parse_arbitration_summary   # 懒 import：纯函数、零 IO、沙箱安全
    verdict = parse_arbitration_summary(raw_summary if isinstance(raw_summary, str) else "")
    for e in timeline:
        if not isinstance(e, dict) or str(e.get("stage") or "") != "arbitrate":
            continue
        if str(e.get("state") or "") != "running":
            continue
        at = parse_iso_epoch(e.get("at"))
        if at:
            verdict_at = max(verdict_at, at)
    if results and "arbitrate" not in results:
        notes.append("results.arbitrate absent (arbitration verdict unknown)")
    if verdict_at and not verdict:
        notes.append("no tests-fault/pass/code-fault verdict in the latest arbitration summary")
    facts["verdict"], facts["verdict_at"] = verdict, verdict_at

    # ---- 最后进展时刻：时间线最大 at ∪ meta.log 最大 ts ∪ meta.updated（全部未测到=0）。
    log = meta.get("log") if isinstance(meta.get("log"), list) else []
    log_ts = max([_num(x.get("ts")) for x in log if isinstance(x, dict)] or [0.0])
    updated = _num(meta.get("updated"))
    candidates = [t for t in (max(ats) if ats else 0.0, log_ts, updated) if t]
    facts["last_activity_at"] = max(candidates) if candidates else 0.0
    if not facts["last_activity_at"]:
        notes.append("no progress timestamp available (timeline/log/updated all empty)")
    return facts


# ========================================================================================
# 判据（纯函数：事实 → 发现）
# ========================================================================================

def _mins(sec: float) -> str:
    m = max(0.0, sec) / 60.0
    return "%.1fmin" % m if m < 100 else "%.1fh" % (m / 60.0)


def _wall_text(entries: Sequence[float], now_ts: float,
               in_flight: bool = True) -> Tuple[str, float]:
    """每轮墙钟（相邻「进入本步」记录的 at 差分；末轮=至今，仅在**当前仍在跑套件**时
    标 in flight，否则标 last round to date）。返回 (可读文本, 末轮时长秒)。
    畸形/空 → 空文本（有则给，无则不给）。"""
    if not entries:
        return "", 0.0
    parts: List[str] = []
    for i in range(len(entries) - 1):
        d = entries[i + 1] - entries[i]
        if d >= 0:
            parts.append(_mins(d))
    tail = max(0.0, (now_ts or entries[-1]) - entries[-1])
    if len(entries) >= 2 or in_flight:
        parts.append("%s (%s)" % (_mins(tail), "in flight" if in_flight
                                  else "last round to date"))
    shown = parts[:WALL_LIST_CAP]
    text = ", ".join(shown)
    if len(parts) > WALL_LIST_CAP:
        text += ", ... (%d more)" % (len(parts) - WALL_LIST_CAP)
    return text, tail


def lane_legs(facts: Dict[str, Any], now_ts: float,
              thresholds: Dict[str, Any],
              suppressed: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """逐票三族判定（纯函数）→ 命中族列表（每条=一份英文文案 + severity + leg token）。

    `suppressed`（可选出参）：③族因「不在飞」的票态而不适用时，把具名原因逐条追加进去
    （调用方进 meta/section 的 suppressed 面——降级可见，但不假报 in flight）。"""
    legs: List[Dict[str, Any]] = []
    if not isinstance(facts, dict):
        return legs
    tid = str(facts.get("ticket_id") or "")
    n_rounds = int(facts.get("suite_rounds") or 0)
    rerun_n = int(thresholds.get("rerun_rounds") or DEFAULT_RERUN_ROUNDS)
    loop_min = int(thresholds.get("fault_loop_min") or DEFAULT_FAULT_LOOP_MIN)
    silent_min = int(thresholds.get("inflight_silent_min") or DEFAULT_INFLIGHT_SILENT_MIN)
    entries = [t for t in (facts.get("suite_entries") or []) if isinstance(t, (int, float)) and t]
    entries = sorted(float(t) for t in entries)
    stage = str(facts.get("stage") or "?")
    stage_state = str(facts.get("stage_state") or "?")
    project = str(facts.get("project") or "?")
    where = "project=%s stage=%s/%s status=%s" % (project, stage, stage_state,
                                                 str(facts.get("status") or "?"))

    # ① 同票重跑轮次 > N
    if n_rounds > rerun_n:
        wall, _ = _wall_text(entries, now_ts,
                             in_flight=(stage == "run_integration_tests"))
        # severity 阶梯（机械、可判）：>N → med；≥2N → high（今天实案 6 轮 × ~1h 即 high）
        sev = "high" if n_rounds >= 2 * rerun_n else "med"
        legs.append({
            "leg": LEG_RERUN, "severity": sev,
            "subject": "%s re-ran the integration suite %d times (threshold %d)"
                       % (tid, n_rounds, rerun_n),
            "why": "the same ticket re-entered run_integration_tests %d times (> watchdog "
                   "threshold %d): the loop is not converging, or external handling keeps "
                   "re-driving it (KI-122 family). Action: read the ticket timeline, then "
                   "either accept the arbitration verdict, rework, or pause the ticket — "
                   "the workflow does not stop by itself." % (n_rounds, rerun_n),
            "evidence": ("suite re-runs=%d > threshold %d | per-round wall: %s | %s"
                         % (n_rounds, rerun_n, wall or "unavailable", where)),
        })

    # ② 停在 tests-fault 回路超时（判决已下却不收敛）
    verdict = str(facts.get("verdict") or "")
    verdict_at = float(facts.get("verdict_at") or 0.0)
    if verdict == "tests-fault" and verdict_at and now_ts > verdict_at:
        dwell = now_ts - verdict_at
        if dwell > loop_min * 60:
            legs.append({
                "leg": LEG_FAULT_LOOP, "severity": "high",
                "subject": "%s has been stuck in the tests-fault loop for %s (threshold %dmin)"
                           % (tid, _mins(dwell), loop_min),
                "why": "arbitration already returned verdict=tests-fault %s ago and the ticket "
                       "has not converged since (rounds=%d): the verdict was handed down but "
                       "the loop did not advance (KI-122: the verdict must be adopted or "
                       "escalated to a human). Action: read the arbitration summary and "
                       "decide (accept verdict / rework / pause)."
                       % (_mins(dwell), n_rounds),
                "evidence": ("verdict=%s handed down %s ago > threshold %dmin | arbitration "
                             "rounds=%d suite re-runs=%d | %s"
                             % (verdict, _mins(dwell), loop_min, verdict_at and
                                len(entries) or 0, n_rounds, where)),
            })

    # ③ 在飞超阈值无进展（僵尸票，KI-126 同源）——**只对真在飞的票**：paused / blocked /
    #    awaiting* 三态是设计内的非在飞态（等待人处置/人门），报「while in flight」既与事实
    #    相反（报错精确纪律），又会把每期含等人签字票的巡检打成「非全绿」；改逐条降级点名。
    last = float(facts.get("last_activity_at") or 0.0)
    not_in_flight = []
    if facts.get("paused") is True:
        not_in_flight.append("paused=True (stop-the-bleeding action, KI-122)")
    if str(facts.get("status") or "") == INFLIGHT_INAPPLICABLE_STATUS:
        not_in_flight.append("status=%s (waiting on a human decision)" % INFLIGHT_INAPPLICABLE_STATUS)
    if "awaiting" in stage_state.lower():
        not_in_flight.append("stage_state=%s (waiting on a human gate)" % stage_state)
    if last and now_ts > last:
        silent = now_ts - last
        if silent > silent_min * 60 and not not_in_flight:
            legs.append({
                "leg": LEG_INFLIGHT, "severity": "high",
                "subject": "%s has been silent for %s while in flight (threshold %dmin)"
                           % (tid, _mins(silent), silent_min),
                "why": "the ticket is non-terminal but its last recorded progress is %s old "
                       "(> watchdog threshold %dmin): a zombie/stalled flight (KI-126 family — "
                       "no stage transition, no handoff, no log line). Action: check the ticket "
                       "worker and the current stage, then rework/pause/terminate."
                       % (_mins(silent), silent_min),
                "evidence": ("silent %s > threshold %dmin | last progress at %s | suite "
                             "re-runs=%d | %s"
                             % (_mins(silent), silent_min,
                                _iso(last) if last else "unknown", n_rounds, where)),
            })
        elif silent > silent_min * 60 and not_in_flight and suppressed is not None:
            suppressed.append(
                "%s: inflight-silent NOT reported — the ticket is not in flight (%s); silent %s"
                % (tid, ", ".join(not_in_flight), _mins(silent)))
    # ⓪ 读面降级（缺陷⑥）：三族都无命中而快照读不懂 → low 一条，绝不静默当成「票干净」。
    if not legs and facts.get("parse_notes"):
        notes = [str(n) for n in facts["parse_notes"] if str(n)]
        legs.append({
            "leg": LEG_DATA_UNREADABLE, "severity": "low",
            "subject": ("lane facts could not be read (%d degraded item(s)) — zero "
                        "findings here is NOT a clean bill" % len(notes)),
            "why": "the ticket snapshot could not be parsed into lane facts, so no "
                   "rerun/loop/silence judgement could be made for this ticket: it is "
                   "UNVERIFIED, not verified-clean. Action: check the snapshot shape the "
                   "face reports for it (stage/gens/timeline/meta) — a non-dev-lane template, "
                   "an old ticket, or a snapshot key drift reads as unreadable here.",
            "evidence": ("zero legs hit but the snapshot parse degraded into %d note(s) | %s"
                         % (len(notes), where)),
        })
    if facts.get("parse_notes"):
        for leg in legs:
            leg["evidence"] += " | data notes: %s" % "; ".join(
                str(n) for n in facts["parse_notes"])[:300]
    for leg in legs:
        leg["evidence"] = leg["evidence"][:EVIDENCE_CAP]
    return legs


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError, TypeError):
        return "unknown"


def lane_findings(tickets: Any, *, now_ts: float,
                  thresholds: Optional[Dict[str, Any]] = None,
                  tickets_meta: Optional[Dict[str, Any]] = None):
    """整批票 → (findings, meta)：**每票聚合一条**发现（命中多族时 legs 列全）。

    发现形状与 deadman/suite 族同源（inspection_deadman.make_finding；suggest=False——
    流程层故障不开修码票）。meta 带计数（scanned / with_findings / by_leg）与畸形名单。
    入参畸形（tickets 非列表/条目非 dict）不抛：逐条跳过并点名。
    """
    thr = dict(WATCHDOG_DEFAULTS)
    if isinstance(thresholds, dict):
        for k in WATCHDOG_KEYS:
            v = thresholds.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                thr[k] = v
    out: List[Dict[str, Any]] = []
    by_leg = {k: 0 for k in LANE_LEGS}
    skipped: List[str] = []
    suppressed: List[str] = []
    scanned = 0
    for f in (tickets if isinstance(tickets, list) else []):
        if not isinstance(f, dict):
            skipped.append("ticket facts is not an object (%s)" % type(f).__name__)
            continue
        if not str(f.get("ticket_id") or ""):
            skipped.append("ticket facts without ticket_id (skipped)")
            continue
        scanned += 1
        legs = lane_legs(f, float(now_ts or 0.0), thr, suppressed)
        if not legs:
            continue
        for leg in legs:
            by_leg[leg["leg"]] = by_leg.get(leg["leg"], 0) + 1
        sev = ("high" if any(l["severity"] == "high" for l in legs)
               else "med" if any(l["severity"] == "med" for l in legs)
               else "low")
        # 聚合主语按族组成选前缀：只有读面降级族时说「stuck in the lane」与事实不符
        # （票不一定卡住，是**没读成**——报错精确纪律）。
        if all(str(l["leg"]) == LEG_DATA_UNREADABLE for l in legs):
            subject = "%s: %s" % (f["ticket_id"],
                                  " + ".join(str(l["subject"]) for l in legs))
        else:
            subject = "%s stuck in the lane: %s" % (
                f["ticket_id"], " + ".join(str(l["subject"]) for l in legs))
        from inspection_deadman import make_finding   # 懒 import：发现形状单点（同 deadman）
        finding = make_finding(
            LANE_SCAN, sev, subject,
            " || ".join(str(l["evidence"]) for l in legs),
            suggest=False)
        finding["legs"] = [str(l["leg"]) for l in legs]
        # why：多族时逐族拼（叙述字段，报告面语言闸按 NARRATIVE_FIELDS 扫它）
        finding["why"] = " ".join(str(l["why"]) for l in legs)
        finding["ticket_id"] = str(f["ticket_id"])
        finding["project"] = str(f.get("project") or "")
        out.append(finding)
    meta = {"scan": LANE_SCAN, "scanned": scanned,
            "non_terminal": int((tickets_meta or {}).get("non_terminal") or scanned)
                            if isinstance(tickets_meta, dict) else scanned,
            "with_findings": len(out), "by_leg": by_leg, "skipped": skipped,
            "suppressed": suppressed,
            "thresholds": dict(thr)}
    return out, meta


def _by_leg_all(raw: Any) -> Dict[str, int]:
    """by_leg 归一（票级三族 + 水位一族，全部给 0 槽）：计数面「这一期看了哪几族」可见，
    零命中也要看得见槽位（缺槽=读的人以为没这族）。畸形计数逐项归零（不抛）。"""
    out = {k: 0 for k in (list(LANE_LEGS) + [LEG_TMP_FIXTURE])}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[str(k)] = int(v or 0)
            except (TypeError, ValueError):
                out[str(k)] = 0
    return out


def lane_section(findings: Any, meta: Any, *, source: str = "",
                 source_note: str = "") -> Dict[str, Any]:
    """票面/回执的 lane 段（计数可见 + 阈值来源可见；畸形入参不抛）。"""
    f = [x for x in (findings if isinstance(findings, list) else []) if isinstance(x, dict)]
    m = meta if isinstance(meta, dict) else {}
    return {
        "scan": LANE_SCAN,
        "scanned": int(m.get("scanned") or 0),
        "non_terminal": int(m.get("non_terminal") or 0),
        "finding_count": len(f),
        "by_leg": _by_leg_all(m.get("by_leg")),
        "max_severity": ("high" if any(x.get("severity") == "high" for x in f)
                         else "med" if any(x.get("severity") == "med" for x in f)
                         else "low" if f else ""),
        "thresholds": dict(m.get("thresholds") or {}),
        "threshold_source": str(source or THRESHOLD_SOURCE_DEFAULT),
        "threshold_note": str(source_note or ""),
        "skipped": list(m.get("skipped") or []),
        # 降级可见面（260926 复核缺陷⑤）：③族因「不在飞」票态而不适用时逐条点名——
        # 不出假发现，但也不允许「什么都没说」（静默的零与真的零必须可区分）。
        "suppressed": list(m.get("suppressed") or []),
    }


# ========================================================================================
# 第四判据：测试夹具临时目录水位（纯函数；扫描 IO 全在活动壳）
# ========================================================================================

def tmp_fixture_facts(scan: Any, *, now_ts: float = 0.0,
                      prefixes: Sequence[str] = TMP_FIXTURE_PREFIXES) -> Dict[str, Any]:
    """只读扫描回执 → 水位事实（纯函数零 IO）。

    scan 形状（活动壳给的）：{"root": str, "entries": [{"name","mtime"}, ...],
                              "entries_seen": int, "untouched": int,
                              "skipped": [str], "scan_error": str, "scanned_at": float}
    纪律：
      - 只统计**白名单前缀的真目录**（白名单外一律不计——宿主 temp 里还有别的程序的东西）；
      - 畸形条目逐条进 `malformed` 并点名，**绝不抛、绝不当成水位 0**（把读不懂当没漏=假绿）；
      - `scan_error` 非空 = 水位未知（消费方出「扫描不到」的具名发现，不静默当零）；
      - `now_ts=0` 时用 `scan["scanned_at"]`，两者都没有则年龄=未知（0.0）并点名。
    """
    out: Dict[str, Any] = {
        "root": "", "dirs": 0, "live": 0, "oldest_age_h": 0.0, "oldest_name": "",
        "by_prefix": {}, "entries_seen": 0, "untouched": 0, "epochs": 0,
        "malformed": [], "skipped": [], "scan_error": "", "scanned_at": 0.0,
        "age_unknown": False, "truncated": False,
    }
    if not isinstance(scan, dict):
        out["malformed"].append("scan result is not an object (%s)" % type(scan).__name__)
        return out
    out["root"] = str(scan.get("root") or "")
    for k in ("entries_seen", "untouched"):
        v = scan.get(k)
        out[k] = int(v) if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
    out["scan_error"] = str(scan.get("scan_error") or "")
    out["skipped"] = [str(x) for x in (scan.get("skipped") or []) if str(x)]
    out["truncated"] = bool(scan.get("truncated"))
    ts = float(now_ts or 0.0) or _num(scan.get("scanned_at"))
    out["scanned_at"] = ts
    by_prefix: Dict[str, int] = {p: 0 for p in prefixes}
    entries = scan.get("entries")
    if not isinstance(entries, list):
        out["malformed"].append("entries absent/not a list (water level unknown, not zero)")
        out["age_unknown"] = True
        out["by_prefix"] = by_prefix
        return out
    ages: List[float] = []
    for e in entries:
        if not isinstance(e, dict):
            out["malformed"].append("entry is not an object (skipped)")
            continue
        name = str(e.get("name") or "")
        if not name:
            out["malformed"].append("entry without a name (skipped)")
            continue
        pref = next((p for p in prefixes if name.startswith(p)), "")
        if not pref:
            # 白名单外：不计（扫描面本不该给，给了就点名——判据面不静默吞异常输入）
            out["malformed"].append("%s: outside the whitelist (not counted)" % name[:80])
            continue
        by_prefix[pref] = by_prefix.get(pref, 0) + 1
        out["dirs"] += 1
        mtime = _num(e.get("mtime"))
        if mtime <= 0:
            out["age_unknown"] = True
            out["malformed"].append("%s: mtime missing/unparseable (age unknown)" % name[:80])
            continue
        out["epochs"] += 1
        if ts:
            ages.append(max(0.0, (ts - mtime) / 3600.0))
    out["by_prefix"] = by_prefix
    if ages:
        oldest = max(ages)
        out["oldest_age_h"] = oldest
        # 最老目录名：取到那个年龄对应的条目（同名年龄并列取排序首个，机械可判）
        names = sorted(str(e.get("name")) for e in entries
                       if isinstance(e, dict) and _num(e.get("mtime")) > 0
                       and abs(max(0.0, (ts - _num(e.get("mtime"))) / 3600.0) - oldest) < 1e-9)
        out["oldest_name"] = names[0] if names else ""
    elif out["dirs"]:
        out["age_unknown"] = True
    return out


def tmp_fixture_prefix_text(facts: Dict[str, Any], cap: int = PREFIX_LIST_CAP) -> str:
    """逐前缀明细（按命中数降序，最多 cap 个；空=空串）。"""
    by = facts.get("by_prefix") if isinstance(facts, dict) else {}
    if not isinstance(by, dict):
        return ""
    pairs = sorted(((k, int(v or 0)) for k, v in by.items() if int(v or 0) > 0),
                   key=lambda kv: (-kv[1], kv[0]))
    if not pairs:
        return ""
    text = ", ".join("%s=%d" % (k, v) for k, v in pairs[:cap])
    if len(pairs) > cap:
        text += ", ... (%d more prefixes)" % (len(pairs) - cap)
    return text


def tmp_fixture_legs(facts: Dict[str, Any], thresholds: Dict[str, Any]) -> List[Dict[str, Any]]:
    """水位判定（纯函数）→ 命中族列表（0 或 1 条：这是**宿主级**面，不按票聚合）。

    判据（两条任一越线即出发现——严格大于，与票级面同口径）：
      ① 白名单夹具目录数 > `tmp_fixture_max_dirs`；
      ② 最老目录年龄 > `tmp_fixture_max_age_h`（「没有任何活套件会用」的 6h 线）。
    只越一条 → med；两条同时越 → high（今天的实况：27.7 万个 + 300+ 小时，两条都越）。
    年龄/扫描错误未知时不判年龄（保守，不假报），但**证据里点名未知**——不静默。
    """
    if not isinstance(facts, dict):
        return []
    max_dirs = int(thresholds.get("tmp_fixture_max_dirs") or DEFAULT_TMP_FIXTURE_MAX_DIRS)
    max_age_h = float(thresholds.get("tmp_fixture_max_age_h") or DEFAULT_TMP_FIXTURE_MAX_AGE_H)
    dirs = int(facts.get("dirs") or 0)
    oldest = float(facts.get("oldest_age_h") or 0.0)
    over_count = dirs > max_dirs
    over_age = bool(facts.get("epochs")) and oldest > max_age_h
    if not (over_count or over_age):
        return []
    root = str(facts.get("root") or "?")
    where = "root=%s" % root
    per = tmp_fixture_prefix_text(facts)
    if over_count and over_age:
        subject = ("test fixture temp dirs: %d dirs (threshold %d) and the oldest is %.1fh old "
                   "(threshold %dh) under %s" % (dirs, max_dirs, oldest, int(max_age_h), root))
    elif over_count:
        subject = ("test fixture temp dirs: %d dirs (threshold %d) under %s"
                   % (dirs, max_dirs, root))
    else:
        subject = ("test fixture temp dirs: the oldest is %.1fh old (threshold %dh) under %s"
                   % (oldest, int(max_age_h), root))
    evidence = ("test fixture dirs=%d (threshold %d) | oldest=%s (%s) | by prefix: %s | "
                "scanned %d top-level entries (%d outside the whitelist, untouched) | %s"
                % (dirs, max_dirs,
                   ("%.1fh" % oldest) if facts.get("epochs") else "unknown",
                   (facts.get("oldest_name") or "?")[:80],
                   per or "none", int(facts.get("entries_seen") or 0),
                   int(facts.get("untouched") or 0), where))
    if facts.get("age_unknown"):
        evidence += " | age unknown for some entries (not judged on age)"
    if facts.get("truncated"):
        evidence += " | scan truncated by the entry cap (counts are a lower bound)"
    if facts.get("scan_error"):
        evidence += " | scan error: %s" % str(facts["scan_error"])[:200]
    if facts.get("malformed"):
        evidence += " | data notes: %s" % "; ".join(
            str(x) for x in facts["malformed"])[:300]
    return [{
        "leg": LEG_TMP_FIXTURE, "severity": "high" if (over_count and over_age) else "med",
        "subject": subject,
        "why": "test-fixture temp dirs under the system temp root are piling up (%d dirs, "
               "oldest %s): no running suite can still be using them, so nobody reclaimed them "
               "— the 260926 shape where $TMPDIR reached 407,294 dirs / 98.6%% older than 6h and "
               "no inspection face looked at the disk at all. Action: run "
               "`python3 integration/tools/sweep_tmp_fixtures.py` (dry-run first, then --apply) "
               "to reclaim the backlog, then check the producer side for a new leak "
               "(mkdtemp without a registry + exit hook: L8 in integration/lint_tests.py)."
               % (dirs, ("%.1fh" % oldest) if facts.get("epochs") else "unknown"),
        "evidence": evidence[:EVIDENCE_CAP],
    }]


def tmp_fixture_scan_result(scan: Any, thresholds: Dict[str, Any], *, source: str = "",
                            note: str = "", now_ts: float = 0.0) -> Dict[str, Any]:
    """扫描回执 → 水位面回执（facts + 发现清单 + 段）。纯函数，畸形一律显式化不抛。

    零发现 = findings 空、段计数 0（**看得见**「扫了、没越线」）；扫描不到 = 一条具名
    med 发现 + 段里点名（绝不把「没扫到」渲染成「全绿」——这是本面存在的全部理由）；
    逐条读不懂/截断 = 各一条 low 发现（不静默，但也不假装是漏水）。"""
    facts = tmp_fixture_facts(scan, now_ts=now_ts)
    findings: List[Dict[str, Any]] = []
    from inspection_deadman import make_finding
    unreadable = (not isinstance(scan, dict)) or bool(facts["scan_error"]) or \
        not isinstance(scan.get("entries"), list)
    if unreadable:
        err = facts["scan_error"] or "; ".join(str(x) for x in facts["malformed"])[:300] \
            or "scan result malformed"
        findings.append(make_finding(
            LANE_SCAN, "med", "test fixture temp dirs could not be scanned",
            "the temp-root water level is unknown this period (root=%s): %s — a silent zero "
            "here would render the disk face green, so it is named instead. Check the temp "
            "root's readability, then re-run the inspection period."
            % (facts.get("root") or "?", err), suggest=False))
    else:
        legs = tmp_fixture_legs(facts, thresholds)
        if legs:
            leg = legs[0]
            f = make_finding(LANE_SCAN, leg["severity"], leg["subject"], leg["evidence"],
                             suggest=False)
            f["legs"] = [LEG_TMP_FIXTURE]
            f["why"] = leg["why"]
            f["scope"] = "host"      # 宿主级发现：不属于任何一张票（ticket_id 不编）
            f["ticket_id"] = ""
            f["project"] = ""
            findings.append(f)
        if facts["malformed"]:
            findings.append(make_finding(
                LANE_SCAN, "low",
                "test fixture temp dir scan skipped %d unreadable/malformed entry(ies)"
                % len(facts["malformed"]),
                "these entries carry no usable (name, mtime) pair, so they are excluded from "
                "the water level (no guess, no silent drop): %s"
                % "; ".join(str(x) for x in facts["malformed"])[:300], suggest=False))
        if facts["truncated"]:
            findings.append(make_finding(
                LANE_SCAN, "low", "test fixture temp dir scan was truncated",
                "the scan stopped at the top-level entry cap: the reported directory count is "
                "a LOWER bound (root=%s, entries seen=%d)"
                % (facts.get("root") or "?", int(facts.get("entries_seen") or 0)),
                suggest=False))
    return {"facts": facts,
            "findings": findings,
            "section": tmp_fixture_section(facts, findings, thresholds,
                                           source=source, note=note)}


def tmp_fixture_section(facts: Any, findings: Any, thresholds: Any, *, source: str = "",
                        note: str = "") -> Dict[str, Any]:
    """水位段（票面/回执）：计数 + 逐前缀 + 最老 + 阈值与**来源**（声明|env|缺省）全可见。"""
    f = [x for x in (findings if isinstance(findings, list) else []) if isinstance(x, dict)]
    fct = facts if isinstance(facts, dict) else {}
    thr = thresholds if isinstance(thresholds, dict) else {}
    return {
        "scan": LANE_SCAN,
        "scope": "host",
        "root": str(fct.get("root") or ""),
        "dirs": int(fct.get("dirs") or 0),
        "by_prefix": dict(fct.get("by_prefix") or {}),
        "oldest_age_h": float(fct.get("oldest_age_h") or 0.0),
        "oldest_name": str(fct.get("oldest_name") or ""),
        "entries_seen": int(fct.get("entries_seen") or 0),
        "untouched": int(fct.get("untouched") or 0),
        "age_unknown": bool(fct.get("age_unknown")),
        "scan_error": str(fct.get("scan_error") or ""),
        "malformed": list(fct.get("malformed") or []),
        "skipped": list(fct.get("skipped") or []),
        "finding_count": len(f),
        "by_leg": _by_leg_all({LEG_TMP_FIXTURE: len([x for x in f if LEG_TMP_FIXTURE in
                                                     (x.get("legs") or [])])}),
        "max_severity": ("high" if any(x.get("severity") == "high" for x in f)
                         else "med" if f else ""),
        "thresholds": {k: int(thr.get(k) or TMP_WATCHDOG_DEFAULTS[k]) for k in TMP_WATCHDOG_KEYS},
        "threshold_source": str(source or THRESHOLD_SOURCE_DEFAULT),
        "threshold_note": str(note or ""),
    }


def merge_lane_section(lane: Any, tmp: Any) -> Dict[str, Any]:
    """把水位段并进 lane 段（**计数单点**）：finding_count/by_leg/max_severity 合并，
    水位段原样挂 `tmp_fixture`。段计数与发现清单必须互斥不得漂移（读的人按段计数判绿），
    所以合并只此一处。任一侧 None/畸形都不抛（并进来的是什么就报什么）。"""
    out = dict(lane) if isinstance(lane, dict) else {}
    t = tmp if isinstance(tmp, dict) else None
    if not t:
        return out
    out["tmp_fixture"] = t
    out["finding_count"] = int(out.get("finding_count") or 0) + int(t.get("finding_count") or 0)
    by = _by_leg_all(out.get("by_leg"))
    for k, v in _by_leg_all(t.get("by_leg")).items():
        if v:
            by[k] = by.get(k, 0) + int(v)
    out["by_leg"] = by
    sev_rank = {"": 0, "low": 1, "med": 2, "high": 3}
    cur = str(out.get("max_severity") or "")
    new = str(t.get("max_severity") or "")
    out["max_severity"] = new if sev_rank.get(new, 0) > sev_rank.get(cur, 0) else cur
    return out
