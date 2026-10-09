"""inspection_deadman — 漏跑（dead-man）与套件结果的纯函数面（t260913-02）。

本模块只出**纯函数**：IO（读台账目录、读时钟、读声明）全在活动壳（activities.py /
agent_activities.py）与运维通道（inspection_trigger.py）里；workflow 体零 IO 纪律不破。

两个受众面：
  1. 漏跑核查：声明 cron → 期望触发日（复用 inspection_ticket_count 的 cron 解析与
     next_cron_fire 正推）× 巡检台账目录（out/inspection/，票号文件名即期号）→ 缺日清单。
     语义：**台账里有该期的票=跑过**（哪怕 blocked——blocked 票带 blocked_reason，是「跑了
     但没跑成」的可见证据）；台账里压根没有=漏跑。
  2. 套件结果 → 票面发现（红项＝high 发现进发现清单，供人审决定开不开修复票）。

时间口径（C6）：期望触发日与期号（inspection_flow.period_key = 本地日期）**同一口径**——
调用方传本地 datetime.now()，本模块不做 UTC 换算；当日（今天）的火一律不算漏（当期票可能
正在跑、尚未落账，工单验收「07:30 前查台账不把当天误判成漏跑」）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta

# 260927 code_stamp（同 agent_activities）：本模块的 worker 载入时刻
import datetime as _dt_code
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

PERIOD_DAY_RE = re.compile(r"^\d{8}$")
# 台账文件名解析（t260913-02 验收 P1 连带修正）：`inspection-<实例>-<期号>.json` 的
# **期号锚在文件名尾部**，实例段用贪婪回溯解析——实例 id 允许含连字符且可互为前缀
# （integration-tests 与 integration-tests-00245 都是合法实例），按前缀硬切会把
# 「他实例的合法台账」误判成本实例的畸形条目（实测：日报票面恒带 med「台账畸形条目」）。
LEDGER_NAME_RE = re.compile(
    r"^inspection-(?P<inst>[a-z0-9][a-z0-9-]*?)-(?P<period>\d{8}(?:-[1-9]\d*)?)\.json$")

#: 台账文件名：inspection-<实例>-<期号>.json（期号=YYYYMMDD 或 YYYYMMDD-<bucket>）。
#: 套件回执 = inspection-<实例>-<期号>-suite.json（已知非台账件，显式忽略，不进畸形桶）。
#: 裁定台账 = inspection-<实例>-<期号>-verdicts.json（t260916-22 发现级裁定；同上忽略——
#: 后缀常量单源=inspection_inspect，两模块各持同名值=双真源锁由 UT 钉）。
LEDGER_SUFFIX = ".json"
SUITE_RECEIPT_SUFFIX = "-suite.json"
VERDICTS_RECEIPT_SUFFIX = "-verdicts.json"

#: 套件红项单列上限（防票面洪泛）：超出部分聚合成一条**可下钻**的发现（带回执文件路径，
#: 逐场景明细在回执 JSON 里）——聚合条不是「吃掉红项」，是换承载面（验收 B/D）。
SUITE_RED_DETAIL_CAP = 10

#: 漏跑发现的 severity：漏跑=巡检面本身的失效，比跑红更严重，恒 high（且 suggest=false——
#: 漏跑不是代码缺陷，开修码票是错配）。
DEADMAN_SCAN = "deadman"
SUITE_SCAN = "suite"


def make_finding(scan: str, severity: str, subject: str, evidence: str,
             suggestion: str = "", suggest: bool = True) -> Dict[str, Any]:
    """发现条目（形状与 inspection_scan.Finding.to_dict 一致 + suggest 开关）。

    suggest=False 的条目仍进发现清单/summary（可见），但不进 suggested_fix_tickets
    （漏跑/环境红不是「开一张修码票」能解的）。"""
    from inspection_scan import SEVERITY_ORDER, finding_id  # 懒 import：形状单点，不在本模块重造 id

    if severity not in SEVERITY_ORDER:
        raise ValueError("unregistered severity: %r" % severity)
    return {"id": finding_id(scan, subject), "scan": scan, "severity": severity,
            "subject": subject, "evidence": evidence, "suggestion": suggestion,
            "suggest": suggest}


# spawner 工作流类型名（t260917-02：调度 action 应指向的 workflow；与
# inspection_trigger._schedule_action 的 builder 同一事实，这里只作判别读面）
SPAWNER_WORKFLOW_TYPE = "InspectionPeriodicSpawnWorkflow"


def skip_findings(skip_count, running_actions, action_summary, missed):
    """跳火 finding 两分支（t260917-02 C1：跳火**可观测**，不再推断为准）。

    observed（可观测分支，实锤）：skip_count>0 且 running_actions>0——调度面直接计数
    在案（ScheduleInfo.num_actions_skipped_overlap / running_actions，temporalio
    1.18.2 字段实证），点名「跳火实锤：skip 计数 N、上期 action 仍在 Running」+
    处方（schedule-up / terminate）。仅计数非零但当前无 Running → 只算历史跳火痕迹，
    不出 finding（回执键已可见）——「此刻就在跳火」才升级。
    inferred（兜底分支，可辨不混装）：仅当计数不可得（None——counter 不可得/SDK 差异
    形态）且 missed 非空且 action 未指 spawner（旧直发形）→ 疑似点名（med；置信度
    降级故 med，漏跑本身的 high 由 deadman_findings 承担）。计数可得时即使非零+陈旧
    action 也走 observed，不混装。observed 命中即不再出 inferred（同因不双报）。
    每条带 leg 键（observed|inferred）。suggest=False：运维处置（schedule-up/terminate），
    开修码票是错配（同 make_finding 的漏跑口径）。"""
    wf = str((action_summary or {}).get("workflow") or "")
    stale = bool(wf) and wf != SPAWNER_WORKFLOW_TYPE
    counters_known = skip_count is not None and running_actions is not None
    if counters_known and int(skip_count) > 0 and int(running_actions) > 0:
        f = make_finding(
            DEADMAN_SCAN, "high", "Schedule skip confirmed (OverlapPolicy=SKIP)",
            "skip confirmed: skip count %d, previous action still Running x%d (a long "
            "human-gate hold occupies the Running slot, so the next fire is silently "
            "skipped) | schedule action=%s%s | action: rerun schedule-up (point the "
            "action at the spawner) + terminate the old held ticket (id in schedule_action)"
            % (int(skip_count), int(running_actions), wf or "unknown",
               "; action is stale, not pointing at the spawner" if stale else ""),
            suggest=False)
        f["leg"] = "observed"
        return [f]
    if not counters_known and missed and stale:
        f = make_finding(
            DEADMAN_SCAN, "med", "Schedule skip suspected (fallback branch)",
            "skip counters unavailable, but missed periods %s coexist with an old direct-fire "
            "action (%s, not pointing at the spawner) — the previous held gate was probably "
            "SKIPped; rerun schedule-up and the observed branch will confirm it" % (
                ", ".join(missed[:3]), wf),
            suggest=False)
        f["leg"] = "inferred"
        return [f]
    return []


# ========================================================================================
# 台账（out/inspection/）读取
# ========================================================================================

def ledger_periods(ledger_dir: Any, instance_id: str) -> Dict[str, Any]:
    """台账目录 → 本实例已落账期号集合。

    降级口径（不静默）：目录不存在=空台账（exist=False，调用方据此判定「从未跑过」）；
    畸形文件名（前缀匹配本实例但不合期号词法，且不是套件回执）逐条进 malformed 返回，
    绝不假装没看见也不因一个坏名炸掉整次核查；异实例文件直接忽略。"""
    inst = str(instance_id or "")
    prefix = "inspection-%s-" % inst
    out: Dict[str, Any] = {"exist": False, "periods": set(), "malformed": [], "count": 0}
    if not inst:
        return out
    d = Path(ledger_dir)
    if not d.is_dir():
        return out
    out["exist"] = True

    try:
        entries = sorted(d.iterdir())
    except OSError as e:
        out["malformed"].append("目录不可读（%s）：%s" % (type(e).__name__, e))
        return out
    for p in entries:
        name = p.name
        if not name.endswith(LEDGER_SUFFIX) or not name.startswith("inspection-"):
            continue
        if name.endswith(SUITE_RECEIPT_SUFFIX) \
                or name.endswith(VERDICTS_RECEIPT_SUFFIX) \
                or re.search(r"-suite-late(?:-\d+)?\.json$", name):
            continue  # 已知非台账件（套件回执 / 裁定台账 / 迟到孤儿回执 t260927）
        m = LEDGER_NAME_RE.match(name)
        if m is not None:
            if m.group("inst") == inst:
                out["periods"].add(m.group("period"))
            continue                     # 别的实例（含互为前缀的长 id）：与己无关
        # 整名不可解析：只有「本实例前缀」的才算本实例的畸形条目（异实例/异物忽略）
        if name.startswith(prefix):
            out["malformed"].append(name)
    out["count"] = len(out["periods"])
    return out


# ========================================================================================
# 漏跑判定
# ========================================================================================

def expected_fires(cron: str, now: datetime, lookback_days: int = 7) -> List[datetime]:
    """(now - lookback_days, 今日 00:00) 窗口内该 cron 的期望触发时刻（正推）。

    当日 00:00 之后的火不返回——今天的期票可能正在跑（尚未落账），不算漏（C6 边界）。
    窗口上限 lookback_days<=90 兜底（防御性：调用方参数畸形不至于把正推循环拉爆）。"""
    from inspection_ticket_count import next_cron_fire

    days = int(lookback_days)
    if days < 1:
        days = 1
    if days > 90:
        days = 90
    start = datetime.combine((now - timedelta(days=days)).date(), time.min)
    end = datetime.combine(now.date(), time.min)
    cursor = start - timedelta(minutes=1)
    fires: List[datetime] = []
    while True:
        nxt = next_cron_fire(cron, cursor)
        if nxt >= end:
            break
        fires.append(nxt)
        cursor = nxt
        if len(fires) > 4096:  # 结构上限：90 天 × 每日 = 90 条，超了说明解析器出问题
            break
    return fires


def missed_periods(cron: str, known_periods: Iterable[str], now: Optional[datetime] = None,
                   lookback_days: int = 7, grace_days: int = 0,
                   tz_name: str = "") -> List[str]:
    """期望触发日 - 已落账期号 = 漏跑期号（升序）。

    tz_name（t260913-02 验收 P1）：声明时区——期望触发日按**声明时区的日历日**计（与
    期号铸取 `period_key_in_tz` 同一条回落链：tz 空/无法解析=进程/UTC 口径），保证
    「cron+tz 触发时刻 → 期号 == 期望键」跨 UTC 日界也成立，否则每天恒报「当期自己」。

    grace_days：宽限（期号日期距今 <= grace_days 的缺日不报——给「跨时区/慢一天补跑」留面，
    缺省 0=只要过去完整的一天没落账就报）。cron 不可解析 → ValueError（显式上抛，调用方
    翻成 ok=False 点名，绝不静默当「没漏」）。"""
    dt = now or datetime.now()
    if tz_name:
        from inspection_flow import now_in_tz
        dt = now_in_tz(dt, tz_name)
    known: Set[str] = {str(p) for p in (known_periods or [])}
    grace = max(0, int(grace_days))
    missed: List[str] = []
    for fire in expected_fires(cron, dt, lookback_days):
        key = fire.strftime("%Y%m%d")
        if key in known:
            continue
        if (dt.date() - fire.date()).days <= grace:
            continue
        missed.append(key)
    return missed


def deadman_findings(missed: Sequence[str], instance_id: str, cron: str,
                     lookback_days: int = 7) -> List[Dict[str, Any]]:
    """漏跑清单 → 票面发现（high，suggest=false；期号全列不截断——漏报严重度高于跑红，C7）。"""
    periods = [str(p) for p in missed if PERIOD_DAY_RE.match(str(p)[:8])]
    if not periods:
        return []
    subject = "Missed %d period(s): %s" % (len(periods), ", ".join(periods))
    return [make_finding(
        DEADMAN_SCAN, "high", subject,
        "instance %s declares cron=%r; %d of the expected periods in the last %d day(s) were "
        "not found in the ledger (out/inspection/inspection-%s-<period>.json) — a schedule "
        "that did not fire, a failed round, or a lane that never came up all land on this "
        "one; entry point: inspection_trigger.py deadman --instance %s (list-readable face), "
        "schedule face: temporal schedule describe sandbar-inspection-%s"
        % (instance_id, cron, lookback_days, len(periods),
           instance_id, instance_id, instance_id),
        suggestion="Check the schedule and worker liveness by hand (a dead-man miss is not a code defect; do not open a fix ticket)",
        suggest=False)]


# ========================================================================================
# 套件回执 → 票面发现
# ========================================================================================

def _tail(text: Any, n: int = 400) -> str:
    s = str(text or "").strip()
    return s[-n:]


# ========================================================================================
# Suite-duration leg (t261008-43): slow-round finding + per-scenario outliers + a bigger/slower trend vs the previous round
# ========================================================================================

#: Defaults for the suite-duration keys (single source =
#: inspection_lane_watchdog.SUITE_DURATION_DEFAULTS — fetched via lazy import; this
#: module never copies the numbers, keeping one source of truth).
def _suite_duration_defaults() -> Dict[str, int]:
    from inspection_lane_watchdog import SUITE_DURATION_DEFAULTS
    return dict(SUITE_DURATION_DEFAULTS)


def _num_or_none(v: Any) -> Optional[float]:
    """Lenient numeric parse: int/float (bool excluded) -> float; anything else
    (None/str/NaN/inf) -> None. Receipt fields are facts written by the executor/gate —
    malformed always becomes None for the caller to name, never a guessed 0."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    return None


def duration_readings(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Suite receipt -> duration readings (pure): {runner_sec, ran, unreadable, runner_src}.

    - runner_sec takes runner_used_sec (the runner wall clock the gate receipt carries;
      missing/malformed falls back to wall_seconds — both missing/malformed =
      unreadable, never a guessed 0 posing as "instant");
    - ran feeds the trend's per-scenario average; malformed (non-numeric/negative) =
      ran=None (the trend reports raw counts only, no average);
    - unreadable = an English list of per-item reasons; non-empty makes the caller
      emit the named "duration unreadable" note — never a silent green."""
    out: Dict[str, Any] = {"runner_sec": None, "ran": None, "unreadable": [],
                           "runner_src": "", "ran_unreadable": ""}
    if not isinstance(receipt, dict):
        out["unreadable"].append("receipt is not a mapping (%s)" % type(receipt).__name__)
        return out
    runner = _num_or_none(receipt.get("runner_used_sec"))
    src = "runner_used_sec"
    if runner is None or runner < 0:
        runner = _num_or_none(receipt.get("wall_seconds"))
        src = "wall_seconds"
    if runner is None or runner < 0:
        out["unreadable"].append(
            "no readable duration: runner_used_sec=%r wall_seconds=%r"
            % (receipt.get("runner_used_sec"), receipt.get("wall_seconds")))
    else:
        out["runner_sec"] = runner
        out["runner_src"] = src
    ran = _num_or_none(receipt.get("ran"))
    if ran is None or ran < 0:
        msg = "ran is not a non-negative number (%r)" % (receipt.get("ran"),)
        out["unreadable"].append(msg)
        out["ran_unreadable"] = msg
    else:
        out["ran"] = int(ran)
    return out


def scenario_outliers(receipt: Dict[str, Any], threshold_sec: float,
                      cap: int = SUITE_RED_DETAIL_CAP) -> Dict[str, Any]:
    """Per-scenario outlier face (pure): details entries whose dur_s crosses the
    threshold, sorted descending, capped at `cap`.

    Data source = the per-scenario dur_s the gate receipt carries (the t261008-43
    engine-side additive passthrough; an old receipt without it = carried=False and
    the caller names "no per-scenario durations" instead of a silent "no outliers").
    Over-cap entries aggregate into a count (never silently truncated); the per-
    scenario detail lives in the receipt JSON. Malformed dur_s (non-numeric) is
    never guessed or counted — it lands in the `bad` count. `__`-prefixed summary
    rows (__pool_exclude__ etc.) are not scenarios and never enter the list."""
    out: Dict[str, Any] = {"carried": False, "hits": [], "over_cap": 0, "bad": 0}
    if not isinstance(receipt, dict):
        return out
    details = receipt.get("details") if isinstance(receipt.get("details"), list) else []
    hits: List[Dict[str, Any]] = []
    for d in details:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "")
        if not name or name.startswith("__"):
            continue
        dur = _num_or_none(d.get("dur_s"))
        if dur is None:
            if d.get("dur_s") is not None:
                out["bad"] += 1           # key present but malformed: named, not counted
            continue
        out["carried"] = True
        if dur > threshold_sec:
            hits.append({"name": name, "dur_s": dur,
                         "pool": str(d.get("pool") or "main")})
    hits.sort(key=lambda h: -h["dur_s"])
    out["hits"] = hits[:cap]
    out["over_cap"] = max(0, len(hits) - cap)
    return out


def duration_findings(receipt: Dict[str, Any], thresholds: Any,
                      threshold_note: str = "") -> List[Dict[str, Any]]:
    """Suite-duration leg -> findings (pure; wired at the tail of suite_findings).

    Classification discipline (host order 261008, pinned by UTs):
      - a slow round is a cost/attention signal, NOT a product red: severity=med,
        suggest=False — never into suggested_fix_tickets, never a tests-fault (that
        is the lane-watchdog face; this leg does not touch it);
      - the only escalation is the hang shape (runner_used_sec >= run_budget_sec):
        severity=high but still suggest=False — a hang is an ops-disposal signal,
        a fix ticket is the wrong tool (the finding text says so explicitly so it
        does not read as a missing label);
      - error / ran==0 / reds / env_fail are judged independently: a round that both
        ran long and failed keeps BOTH sets of findings — no merging, no suppression;
      - the trend compares against the previous round (prev_round, the raw dict the
        activity shell read and passed in) on three numbers: ran, runner/wall
        seconds, and the per-scenario average (runner_sec/ran); avg up >25% =>
        slower; ran up >10% => bigger (a suite that merely grew in scenario count
        with a flat average is reported bigger, NOT slower — the 261008 host order
        verbatim); both shapes can coexist and are both reported. A previous round
        that is unreadable or was truncated => say so, never use missing data as a
        baseline; ran==0 makes the average incomputable => report raw counts and
        name "average not computable", no slower/bigger classification.
    """
    thr = dict(_suite_duration_defaults())
    if isinstance(thresholds, dict):
        for k in thr:
            v = _num_or_none(thresholds.get(k))
            if v is not None and v > 0:
                thr[k] = v
    note = str(threshold_note or "threshold source=default")
    findings: List[Dict[str, Any]] = []
    rd = duration_readings(receipt)
    receipt_path = (receipt.get("report_path") if isinstance(receipt, dict) else None) \
        or "(no receipt written)"
    truncated = False
    if isinstance(receipt, dict):
        truncated = bool(receipt.get("interrupted")) \
            or bool(isinstance(receipt.get("budget"), dict) and receipt["budget"].get("exhausted"))
    if [r for r in rd["unreadable"] if r != rd["ran_unreadable"]]:
        findings.append(make_finding(
            SUITE_SCAN, "med", "Suite duration unreadable",
            "%s — the duration leg cannot judge this round (never a silent pass); "
            "check the receipt by hand | receipt file %s"
            % ("; ".join(rd["unreadable"]), receipt_path),
            suggest=False))
        return findings
    if rd["ran_unreadable"]:
        # malformed ran != unreadable duration: slow-round/outliers still judge (no average), but the malformation itself is named, never swallowed
        findings.append(make_finding(
            SUITE_SCAN, "med", "Suite receipt ran field malformed",
            "%s — trend average and outlier counts carry the raw duration only "
            "(never guessed) | receipt file %s" % (rd["ran_unreadable"], receipt_path),
            suggest=False))
    runner_sec = float(rd["runner_sec"])
    ran = rd["ran"]
    runner_min = runner_sec / 60.0
    # ---- slow-round judgement ----
    if runner_min >= thr["suite_slow_round_min"]:
        budget = _num_or_none(receipt.get("run_budget_sec")) if isinstance(receipt, dict) else None
        hang = budget is not None and budget > 0 and runner_sec >= budget
        findings.append(make_finding(
            SUITE_SCAN, "high" if hang else "med",
            "Suite round slow: %.1f min (threshold %d min)%s"
            % (runner_min, thr["suite_slow_round_min"],
               " — hang-shaped (at/over run_budget; still suggest=false, an ops signal "
               "not a fix ticket)" if hang else ""),
            "round took %.1f min (%s=%.1fs, ran=%s scenarios) >= threshold %d min "
            "| %s | NOT a product red and NOT a tests-fault: running long is a cost/attention "
            "signal — open no fix ticket, triage the cost by hand%s | receipt file %s"
            % (runner_min, rd.get("runner_src") or "runner_used_sec", runner_sec,
               ran if ran is not None else "?", thr["suite_slow_round_min"], note,
               "; NOTE this round was truncated (interrupted/budget-exhausted) — the "
               "duration is a truncated-round duration, not a full-suite time"
               if truncated else "",
               receipt_path),
            suggest=False))
    # ---- per-scenario outliers ----
    so = scenario_outliers(receipt, thr["suite_slow_scenario_sec"])
    if so["bad"]:
        findings.append(make_finding(
            SUITE_SCAN, "med", "Suite per-scenario durations malformed: %d" % so["bad"],
            "%d detail entries carry a non-numeric dur_s — excluded from the outlier face, "
            "never guessed | receipt file %s" % (so["bad"], receipt_path),
            suggest=False))
    if so["hits"] or so["over_cap"]:
        listed = ", ".join("%s (%s, %.1fs)" % (h["name"], h["pool"], h["dur_s"])
                           for h in so["hits"])
        more = ("; and %d more over the threshold (drill-down: sort the receipt's details "
                "by dur_s)" % so["over_cap"]) if so["over_cap"] else ""
        findings.append(make_finding(
            SUITE_SCAN, "med",
            "Suite slow scenarios: %d over %ds%s"
            % (len(so["hits"]) + so["over_cap"], thr["suite_slow_scenario_sec"],
               " (%d listed)" % len(so["hits"]) if so["over_cap"] else ""),
            "per-scenario outliers (threshold %ds, %s): %s%s | NOT a product red: slow "
            "scenarios are cost signals (often the known-expensive pools); triage by hand "
            "| receipt file %s"
            % (thr["suite_slow_scenario_sec"], note, listed, more, receipt_path),
            suggest=False))
    elif not so["carried"] and isinstance(receipt.get("details"), list) \
            and any(isinstance(d, dict) and str(d.get("name") or "")
                    and not str(d.get("name")).startswith("__")
                    for d in receipt["details"]):
        findings.append(make_finding(
            SUITE_SCAN, "med", "Suite receipt carries no per-scenario durations",
            "the detail entries have no dur_s (old gate form) — the outlier face cannot "
            "name slow scenarios this round; per-scenario timing needs the cases passthrough "
            "| receipt file %s" % receipt_path,
            suggest=False))
    # ---- trend (vs the previous round; unreadable is stated, never guessed) ----
    prev = receipt.get("prev_round") if isinstance(receipt, dict) else None
    trend_lines: List[str] = []
    slower = bigger = False
    if not isinstance(prev, dict):
        trend_lines.append("no previous round readable for this instance — trend not "
                           "computed (stated, not guessed)")
    else:
        preason = str(prev.get("unreadable") or "")
        ptruncated = bool(prev.get("truncated"))
        p_ran = _num_or_none(prev.get("ran"))
        p_runner = _num_or_none(prev.get("runner_used_sec"))
        if p_runner is None or p_runner < 0:
            p_runner = _num_or_none(prev.get("wall_seconds"))
        if preason or p_runner is None or p_ran is None:
            trend_lines.append("previous round not readable (%s) — trend not computed"
                               % (preason or "missing/invalid ran or duration"))
        elif ptruncated:
            trend_lines.append(
                "previous round (%s) was truncated (interrupted/budget-exhausted) — its "
                "per-scenario average is a truncated-round average, trend not computed off "
                "it (a killed round would fake a speed-up)" % (prev.get("period") or "?"))
        else:
            p_ran = int(p_ran)
            avg_now = (runner_sec / ran) if (ran is not None and ran > 0) else None
            avg_prev = p_runner / p_ran if p_ran > 0 else None
            trend_lines.append(
                "previous round %s: ran=%d runner=%.1fs (avg %.1fs/scenario)"
                % (prev.get("period") or "?", p_ran, p_runner,
                   avg_prev if avg_prev is not None else -1.0))
            if ran is None:
                trend_lines.append("this round's ran is unreadable — avg not computable")
            elif avg_now is None or avg_prev is None:
                trend_lines.append(
                    "per-scenario average not computable (ran=0 on the %s side) — raw "
                    "counts only, no slower/bigger classification"
                    % ("this" if avg_now is None else "previous"))
            else:
                if avg_now > avg_prev * 1.25:
                    slower = True
                    trend_lines.append(
                        "SLOWER: per-scenario average %.1fs vs %.1fs (+%.0f%%)"
                        % (avg_now, avg_prev, (avg_now / avg_prev - 1) * 100))
                if ran > p_ran * 1.1:
                    bigger = True
                    trend_lines.append(
                        "BIGGER: %d scenarios vs %d (+%d) — count growth, per-scenario "
                        "average %s" % (ran, p_ran, ran - p_ran,
                                        "up too" if slower else "flat"))
                if not slower and not bigger:
                    trend_lines.append("steady: scenario count and per-scenario average "
                                       "within tolerance vs the previous round")
    if slower or bigger:
        findings.append(make_finding(
            SUITE_SCAN, "med",
            "Suite trend vs previous round: %s" % (("slower" if slower else "")
                                                   + (" bigger" if bigger else "")).strip(),
            "this round: ran=%s runner=%.1fs | %s | NOT a product red and NOT a "
            "tests-fault — a suite that grew in scenario count is 'bigger', not 'slower' "
            "| receipt file %s"
            % (ran if ran is not None else "?", runner_sec,
               "; ".join(trend_lines), receipt_path),
            suggest=False))
    return findings


#: Period parsing for suite-receipt filenames (LEDGER_NAME_RE does not cover the
#: -suite suffix — ledger entries and suite receipts are two name shapes; this row
#: exists only for the function below and keeps its lexicon verbatim identical).
_SUITE_LEDGER_NAME_RE = re.compile(
    r"^inspection-(?P<inst>[a-z0-9][a-z0-9-]*?)-(?P<period>\d{8}(?:-[1-9]\d*)?)"
    r"-suite\.json$")


def previous_suite_receipt_path(ledger_dir: Any, instance_id: str, period: str) -> Optional[str]:
    """Ledger dir -> this instance's LATEST suite receipt strictly earlier than
    `period` (a pure listing function: no writes, no content reads).

    IO (actually reading file contents) lives in the activity shell; this function
    only lists and filters by filename lexicon — late orphans (-suite-late(-N)) and
    other instances never become candidates; returns None when nothing qualifies
    (the caller states "no previous round", never impersonated by another
    instance/period)."""
    inst = str(instance_id or "")
    if not inst:
        return None
    d = Path(str(ledger_dir))
    if not d.is_dir():
        return None
    try:
        names = sorted(p.name for p in d.iterdir())
    except OSError:
        return None
    best: Optional[Tuple[str, str]] = None   # (period, name)
    for name in names:
        if not name.endswith(SUITE_RECEIPT_SUFFIX) or "-suite-late" in name:
            continue
        m = _SUITE_LEDGER_NAME_RE.match(name)
        if m is None or m.group("inst") != inst:
            continue
        p = m.group("period")
        if str(period) and p >= str(period):
            continue                          # only strictly earlier periods qualify
        if best is None or p > best[0]:
            best = (p, name)
    return str(d / best[1]) if best else None


def suite_findings(receipt: Dict[str, Any], thresholds: Any = None,
                   threshold_note: str = "") -> List[Dict[str, Any]]:
    """套件回执（run_inspection_suite 的 result 形状）→ 发现清单。

    机械映射（红=high；环境红=med；「没跑成」=high）：
      - error 非空（lane 内没跑起来 / verify_lane 畸形输出 / 整体超时）→ high「套件未跑成」；
      - ran==0（无 error）→ high「全集未真正执行」——红线「不得以跳过或删减场景换取跑通」的
        机械面：0 场景的绿不是绿；
      - 逐红项（details 里 exit!=0）→ 各一条 high（前 SUITE_RED_DETAIL_CAP 条单列，超出聚合）；
      - env_fail>0 → med「环境红 N 条」（非代码红，suggest=false——先修环境）。
    畸形输入（非 dict / 字段类型怪）一律按「没跑成」处理并点名，绝不静默当全绿。"""
    if not isinstance(receipt, dict):
        return [make_finding(SUITE_SCAN, "high", "Suite receipt malformed (not a mapping)",
                         "receipt type=%s — treated as did-not-run, never silently green" % type(receipt).__name__,
                         suggest=False)]
    findings: List[Dict[str, Any]] = []
    err = str(receipt.get("error") or "").strip()
    if err:
        # 260927 第二刀（宿主要求②）：**两态必须分开点名**——
        #   ①「被打断」：执行器墙到点被回收，但它已跑过 N 条（进度件可读）——不是「0 场景」、
        #      不是产品红，是容量/截断面；末条与进度件路径点名（可续跑/可抬墙）。
        #   ②「未跑成」：真的一件都没产出/环境面失败——原样 high「套件未跑成」。
        # 混成一态的最坏后果：把「跑了 319 条里的 200 条」读成「套件零信号」，归因又被引偏。
        _prog = receipt.get("progress") if isinstance(receipt.get("progress"), dict) else {}
        try:
            _pran = int(receipt.get("ran") or 0)
        except (TypeError, ValueError):
            _pran = 0
        if receipt.get("interrupted") and _pran > 0:
            findings.append(make_finding(
                SUITE_SCAN, "high", "Suite interrupted: %d scenarios ran but no summary" % _pran,
                "The executor wall reaped it (this is NOT a product red and NOT '0 scenarios'): completed face "
                "pass=%s fail=%s env_fail=%s, last=%s | action: raise the executor wall or narrow "
                "the scope and rerun; completed list in the progress file %s | receipt file %s"
                % (receipt.get("passed", 0), receipt.get("failed", 0),
                   receipt.get("env_fail", 0), _prog.get("last") or "?",
                   _prog.get("path") or "(progress block in the receipt)",
                   receipt.get("report_path") or "(no receipt written)"),
                suggest=False))
        else:
            findings.append(make_finding(
                SUITE_SCAN, "high", "Suite did not run to completion: %s" % err[:80],
                "lane round did not complete (this is NOT a scenario red): %s | receipt file %s"
                % (_tail(err), receipt.get("report_path") or "(no receipt written)"),
                suggestion="Check the suite environment/lane by hand (rerun next period or trigger manually)", suggest=False))
    try:
        ran = int(receipt.get("ran") or 0)
        failed = int(receipt.get("failed") or 0)
        env_fail = int(receipt.get("env_fail") or 0)
    except (TypeError, ValueError) as e:
        findings.append(make_finding(SUITE_SCAN, "high", "Suite receipt count fields malformed",
                                 "ran/failed/env_fail are not integers (%s) — treated as did-not-run, never silent"
                                 % type(e).__name__, suggest=False))
        return findings
    if not err and ran == 0:
        findings.append(make_finding(
            SUITE_SCAN, "high", "full suite did not really run (ran=0)",
            "verify_lane lane=integ reported 0 scenarios — skipping or trimming scenarios must never buy "
            "green; check the scenario registry by hand | receipt file %s" % (receipt.get("report_path") or "(no receipt written)"),
            suggest=False))
    details = receipt.get("details") if isinstance(receipt.get("details"), list) else []
    reds: List[Any] = []
    malformed_details = 0
    for d in details:
        if not isinstance(d, dict):
            malformed_details += 1        # 畸形条目：不静默吞（下面点名），也不当作绿
            continue
        raw_exit = d.get("exit")
        try:
            ex: Any = int(raw_exit)
        except (TypeError, ValueError):
            ex = None                     # exit 缺失/非整数：判不了红绿 → 按红处理（fail-loud）
        if ex is None or ex != 0:
            reds.append((d, "（exit 畸形：%r）" % (raw_exit,) if ex is None else ex))
    if malformed_details:
        findings.append(make_finding(
            SUITE_SCAN, "med", "Suite receipt details malformed: %d" % malformed_details,
            "%d per-scenario red/green entries are unparseable — evidence incomplete; check the receipt by hand %s"
            % (malformed_details, receipt.get("report_path") or "(no receipt written)"),
            suggest=False))
    for d, ex in reds[:SUITE_RED_DETAIL_CAP]:
        name = str(d.get("name") or "（无名场景）")
        findings.append(make_finding(
            SUITE_SCAN, "high", "Suite red: %s" % name,
            "exit=%s | output tail: %s" % (ex, _tail(d.get("output_tail"))),
            suggestion="Human review decides: open a dev-lane fix ticket (source_inspection=<this inspection ticket>)"))
    if len(reds) > SUITE_RED_DETAIL_CAP:
        more = reds[SUITE_RED_DETAIL_CAP:]
        findings.append(make_finding(
            SUITE_SCAN, "high", "%d more suite red items (drill-down)" % len(more),
            "per-scenario detail is in the suite receipt: %s | not listed: %s"
            % (receipt.get("report_path") or "(no receipt written)",
               "、".join(str(d.get("name") or "（无名）") for d, _ in more[:20])),
            suggestion="Human review decides: triage item by item from the receipt file"))
    if env_fail > 0:
        findings.append(make_finding(
            SUITE_SCAN, "med", "Suite environment red: %d" % env_fail,
            "environment red is NOT a code red (missing supply/dependency/image); fix the environment "
            "before judging code | receipt file %s"
            % (receipt.get("report_path") or "(no receipt written)"),
            suggest=False))
    # 260927 总预算耗尽（必做②）：**独立可见发现**——不是产品红（未跑的场景根本没验到）、
    # 也不是「零信号」（中性 ran=0 会把诊断引向错误方向），更不是绿。点名已跑/未跑计数
    # 与未跑批清单（执行器结构化带上来的 budget.unrun）；severity=high 且 suggest=false
    # （容量/预算面，开「修码票」是错配）。
    budget = receipt.get("budget") if isinstance(receipt.get("budget"), dict) else {}
    if budget.get("exhausted"):
        unrun = [str(x) for x in (budget.get("unrun") or [])]
        findings.append(make_finding(
            SUITE_SCAN, "high",
            "Suite budget exhausted: %s scenarios never ran" % (budget.get("unrun_count") or len(unrun)),
            "self-finalized after %s scenarios when the budget ran out (budget %ss) — unrun batch list: %s "
            "| NOT a product red: these scenarios were never verified; action: raise the budget, narrow "
            "the scope, or split into batches and rerun — truncation must never buy green | receipt file %s"
            % (receipt.get("ran", 0), budget.get("budget_sec") or "not recorded",
               ", ".join(unrun[:20]) if unrun else
               "(executor sent no list; see the per-item ENV_FAIL lines in the receipt)",
               receipt.get("report_path") or "(no receipt written)"),
            suggest=False))
    # 260927 迟到孤儿回执（必做③）：这份件不代表套件结果（活动超时后孤儿进程写的）——
    # 点名它并显式说明「不得当套件结论消费」；它的 error 已在上方按「未跑成」报过红，
    # 这里补一条可读的处置指引（重跑下一期 / 手查泳道）。
    if receipt.get("late"):
        findings.append(make_finding(
            SUITE_SCAN, "high", "Suite receipt is a late orphan (does not represent the suite result)",
            "an orphan process wrote it after the activity timed out; renamed to -suite-late.json so the "
            "authoritative receipt stays intact: %s | authoritative conclusion lives in this period's "
            "ledger/timeline and the next period | receipt file %s"
            % (_tail(receipt.get("late_error"), 300),
               receipt.get("report_path") or "(no receipt written)"),
            suggest=False))
    # t261008-43 suite-duration leg: thresholds=None (old callers / old replay) skips
    # the whole leg, byte-identical zero regression; when passed, duration findings
    # are APPENDED after the existing ones — never suppressing or merging
    # error/ran==0/reds/env_fail.
    if thresholds is not None:
        findings.extend(duration_findings(receipt, thresholds, threshold_note))
    return findings


def suite_section(receipt: Dict[str, Any], wall_seconds: Any = None) -> Dict[str, Any]:
    """套件证据段（进票面 face["suite"]）：逐场景红绿 + 摘要 + 回执路径（验收 B）。

    cases 只带 name/exit（逐场景红绿）；输出尾与明细在回执 JSON（票面不刷屏）。"""
    if not isinstance(receipt, dict):
        return {"ok": False, "error": "回执畸形（%s）" % type(receipt).__name__,
                "cases": [], "report_path": ""}
    details = receipt.get("details") if isinstance(receipt.get("details"), list) else []
    cases = [{"name": str(d.get("name") or ""), "exit": int(d.get("exit") or 0)}
             for d in details if isinstance(d, dict)]
    # 260927：套件段透出「超时/预算耗尽/迟到孤儿」三态与两笔分相墙钟（供给/跑者）——
    # 票面与报告要能把「跑不完」与「没跑成」分开读，不得只剩一个中性 ran=0。
    # 缺键（老回放/老载荷形态）一律不进新键，逐字节零回归。
    out = {
        "ok": not str(receipt.get("error") or "").strip(),
        "error": str(receipt.get("error") or ""),
        "ran": int(receipt.get("ran") or 0),
        "passed": int(receipt.get("passed") or 0),
        "failed": int(receipt.get("failed") or 0),
        "env_fail": int(receipt.get("env_fail") or 0),
        "wall_seconds": (float(wall_seconds) if wall_seconds is not None
                         else receipt.get("wall_seconds")),
        "worktree": str(receipt.get("worktree") or ""),
        "base_ref": str(receipt.get("base_ref") or ""),
        "report_path": str(receipt.get("report_path") or ""),
        "blockers": [str(b) for b in (receipt.get("blockers") or [])],
        "cases": cases,
    }
    if receipt.get("suite_timeout"):
        out["suite_timeout"] = True
        out["suite_timeout_sec"] = float(receipt.get("suite_timeout_sec") or 0.0)
    if receipt.get("late"):
        out["late"] = True
        out["late_error"] = str(receipt.get("late_error") or "")
    # 260927 第二刀：被打断面（执行器墙到点被回收）——票面要能读出「已跑 N 条但无汇总」
    if receipt.get("interrupted"):
        out["interrupted"] = True
        if isinstance(receipt.get("progress"), dict) and receipt["progress"]:
            out["progress"] = dict(receipt["progress"])
    if isinstance(receipt.get("budget"), dict) and receipt["budget"]:
        out["budget"] = dict(receipt["budget"])
    # 260927 code_stamp：套件段带一行代码身份（票面据此一眼判「跑的是哪版码」）
    if receipt.get("code_stamp"):
        out["code_stamp"] = str(receipt["code_stamp"])
    if isinstance(receipt.get("code_stamp_detail"), dict) and receipt["code_stamp_detail"]:
        out["code_stamp_detail"] = dict(receipt["code_stamp_detail"])
    for k in ("supply_used_sec", "runner_used_sec", "run_budget_sec", "supply_timeout_sec"):
        if receipt.get(k) is not None:
            out[k] = receipt[k]
    # t261008-43 duration-leg passthrough (additive; absent keys add nothing, old
    # receipts drift nothing): the threshold source line (the ticket face reads at a
    # glance who set the bar) and the raw previous-round comparison face (the
    # human-readable trend evidence).
    if receipt.get("duration_threshold_note"):
        out["duration_threshold_note"] = str(receipt["duration_threshold_note"])
    if isinstance(receipt.get("prev_round"), dict) and receipt["prev_round"]:
        out["prev_round"] = dict(receipt["prev_round"])
    return out


def suite_green(section: Any) -> bool:
    """套件段是否全绿（心跳合成用）：跑成 ∧ ran>0 ∧ 无红 ∧ 无环境红。"""
    if not isinstance(section, dict):
        return False
    try:
        return (bool(section.get("ok")) and int(section.get("ran") or 0) > 0
                and int(section.get("failed") or 0) == 0
                and int(section.get("env_fail") or 0) == 0)
    except (TypeError, ValueError):
        return False


def read_suite_receipt(path: Any) -> Dict[str, Any]:
    """套件回执文件 → dict（畸形/缺失=ok=False 点名；测试与 CLI 复用）。"""
    p = Path(str(path))
    if not p.is_file():
        return {"ok": False, "error": "套件回执不存在：%s" % p}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "套件回执不可解析（%s）：%s" % (type(e).__name__, e)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "套件回执非映射（%s）" % type(data).__name__}
    return {"ok": True, "receipt": data}

