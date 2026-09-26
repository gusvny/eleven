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
                        静默时长。

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

#: 三族 token（发现条目的 legs 列表；机读计数按此聚合）
LEG_RERUN = "rerun-rounds"
LEG_FAULT_LOOP = "tests-fault-loop"
LEG_INFLIGHT = "inflight-silent"
LANE_LEGS = (LEG_RERUN, LEG_FAULT_LOOP, LEG_INFLIGHT)

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

THRESHOLD_SOURCE_DECL = "declaration"
THRESHOLD_SOURCE_DEFAULT = "default"

#: 发现清单里的证据文本上限（防票面洪泛；超长截断并点名）
EVIDENCE_CAP = 1200
#: 每轮墙钟单列条数上限（超出的轮次只报计数）
WALL_LIST_CAP = 8

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
    unknown = sorted(set(raw) - set(WATCHDOG_KEYS))
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
              thresholds: Dict[str, Any]) -> List[Dict[str, Any]]:
    """逐票三族判定（纯函数）→ 命中族列表（每条=一份英文文案 + severity + leg token）。"""
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

    # ③ 在飞超阈值无进展（僵尸票，KI-126 同源）
    last = float(facts.get("last_activity_at") or 0.0)
    if last and now_ts > last:
        silent = now_ts - last
        if silent > silent_min * 60:
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
    scanned = 0
    for f in (tickets if isinstance(tickets, list) else []):
        if not isinstance(f, dict):
            skipped.append("ticket facts is not an object (%s)" % type(f).__name__)
            continue
        if not str(f.get("ticket_id") or ""):
            skipped.append("ticket facts without ticket_id (skipped)")
            continue
        scanned += 1
        legs = lane_legs(f, float(now_ts or 0.0), thr)
        if not legs:
            continue
        for leg in legs:
            by_leg[leg["leg"]] = by_leg.get(leg["leg"], 0) + 1
        sev = "high" if any(l["severity"] == "high" for l in legs) else "med"
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
            "thresholds": dict(thr)}
    return out, meta


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
        "by_leg": dict(m.get("by_leg") or {}),
        "max_severity": ("high" if any(x.get("severity") == "high" for x in f)
                         else "med" if f else ""),
        "thresholds": dict(m.get("thresholds") or {}),
        "threshold_source": str(source or THRESHOLD_SOURCE_DEFAULT),
        "threshold_note": str(source_note or ""),
        "skipped": list(m.get("skipped") or []),
    }
