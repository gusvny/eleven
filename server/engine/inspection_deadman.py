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
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

PERIOD_DAY_RE = re.compile(r"^\d{8}$")
# 台账文件名解析（t260913-02 验收 P1 连带修正）：`inspection-<实例>-<期号>.json` 的
# **期号锚在文件名尾部**，实例段用贪婪回溯解析——实例 id 允许含连字符且可互为前缀
# （integration-tests 与 integration-tests-00245 都是合法实例），按前缀硬切会把
# 「他实例的合法台账」误判成本实例的畸形条目（实测：日报票面恒带 med「台账畸形条目」）。
LEDGER_NAME_RE = re.compile(
    r"^inspection-(?P<inst>[a-z0-9][a-z0-9-]*?)-(?P<period>\d{8}(?:-[1-9]\d*)?)\.json$")

#: 台账文件名：inspection-<实例>-<期号>.json（期号=YYYYMMDD 或 YYYYMMDD-<bucket>）。
#: 套件回执 = inspection-<实例>-<期号>-suite.json（已知非台账件，显式忽略，不进畸形桶）。
LEDGER_SUFFIX = ".json"
SUITE_RECEIPT_SUFFIX = "-suite.json"

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
        raise ValueError("未登记严重度：%r" % severity)
    return {"id": finding_id(scan, subject), "scan": scan, "severity": severity,
            "subject": subject, "evidence": evidence, "suggestion": suggestion,
            "suggest": suggest}


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
        if name.endswith(SUITE_RECEIPT_SUFFIX):
            continue  # 已知非台账件（套件回执）
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
    subject = "漏跑 %d 期：%s" % (len(periods), "、".join(periods))
    return [make_finding(
        DEADMAN_SCAN, "high", subject,
        "实例 %s 声明 cron=%r，近 %d 天窗口内应有 %d 期未在台账 "
        "(out/inspection/inspection-%s-<期>.json) 中找到——调度未触发 / 流程失败 / "
        "泳道未搭成三种情形都会落在这一条上；排查入口：inspection_trigger.py deadman "
        "--instance %s（列表可读面），调度面：temporal schedule describe "
        "sandbar-inspection-%s" % (instance_id, cron, lookback_days, len(periods),
                                   instance_id, instance_id, instance_id),
        suggestion="人工核查调度与 worker 活性（dead-man 不是代码缺陷，不开修码票）",
        suggest=False)]


# ========================================================================================
# 套件回执 → 票面发现
# ========================================================================================

def _tail(text: Any, n: int = 400) -> str:
    s = str(text or "").strip()
    return s[-n:]


def suite_findings(receipt: Dict[str, Any]) -> List[Dict[str, Any]]:
    """套件回执（run_inspection_suite 的 result 形状）→ 发现清单。

    机械映射（红=high；环境红=med；「没跑成」=high）：
      - error 非空（lane 内没跑起来 / verify_lane 畸形输出 / 整体超时）→ high「套件未跑成」；
      - ran==0（无 error）→ high「全集未真正执行」——红线「不得以跳过或删减场景换取跑通」的
        机械面：0 场景的绿不是绿；
      - 逐红项（details 里 exit!=0）→ 各一条 high（前 SUITE_RED_DETAIL_CAP 条单列，超出聚合）；
      - env_fail>0 → med「环境红 N 条」（非代码红，suggest=false——先修环境）。
    畸形输入（非 dict / 字段类型怪）一律按「没跑成」处理并点名，绝不静默当全绿。"""
    if not isinstance(receipt, dict):
        return [make_finding(SUITE_SCAN, "high", "套件回执畸形（非映射）",
                         "回执类型=%s——按未跑成处理，不静默当全绿" % type(receipt).__name__,
                         suggest=False)]
    findings: List[Dict[str, Any]] = []
    err = str(receipt.get("error") or "").strip()
    if err:
        findings.append(make_finding(
            SUITE_SCAN, "high", "套件未跑成：%s" % err[:80],
            "lane 内未跑完成（不是场景红）：%s ｜ 回执文件 %s"
            % (_tail(err), receipt.get("report_path") or "（未落回执）"),
            suggestion="人工核查套件环境/泳道（重跑下一期或手动触发）", suggest=False))
    try:
        ran = int(receipt.get("ran") or 0)
        failed = int(receipt.get("failed") or 0)
        env_fail = int(receipt.get("env_fail") or 0)
    except (TypeError, ValueError) as e:
        findings.append(make_finding(SUITE_SCAN, "high", "套件回执计数字段畸形",
                                 "ran/failed/env_fail 非整数（%s）——按未跑成处理，不静默"
                                 % type(e).__name__, suggest=False))
        return findings
    if not err and ran == 0:
        findings.append(make_finding(
            SUITE_SCAN, "high", "全集未真正执行（ran=0）",
            "verify_lane lane=integ 报 0 个场景——不得以跳过或删减场景换取跑通，"
            "必须人工核查场景注册表 ｜ 回执文件 %s" % (receipt.get("report_path") or "（未落回执）"),
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
            SUITE_SCAN, "med", "套件回执 details 畸形 %d 条" % malformed_details,
            "逐场景红绿有 %d 条不可解析条目——证据不完整，人工核查回执文件 %s"
            % (malformed_details, receipt.get("report_path") or "（未落回执）"),
            suggest=False))
    for d, ex in reds[:SUITE_RED_DETAIL_CAP]:
        name = str(d.get("name") or "（无名场景）")
        findings.append(make_finding(
            SUITE_SCAN, "high", "套件红：%s" % name,
            "exit=%s ｜ 输出尾：%s" % (ex, _tail(d.get("output_tail"))),
            suggestion="人审后定：开 dev-lane 修复票（source_inspection=本期巡检票）"))
    if len(reds) > SUITE_RED_DETAIL_CAP:
        more = reds[SUITE_RED_DETAIL_CAP:]
        findings.append(make_finding(
            SUITE_SCAN, "high", "另有 %d 条套件红项（可下钻）" % len(more),
            "逐场景明细在套件回执文件：%s ｜ 未单列：%s"
            % (receipt.get("report_path") or "（未落回执）",
               "、".join(str(d.get("name") or "（无名）") for d, _ in more[:20])),
            suggestion="人审后定：按回执文件逐条分流"))
    if env_fail > 0:
        findings.append(make_finding(
            SUITE_SCAN, "med", "套件环境红 %d 条" % env_fail,
            "环境红=不是代码红（供应/依赖/镜像缺席）；先修环境再判代码 ｜ 回执文件 %s"
            % (receipt.get("report_path") or "（未落回执）"),
            suggest=False))
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
    return {
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
