"""inspection_ticket_count — the ticket-count source for every-n-tickets / race-first
triggers (inspection epic, t260911-02).

Source of truth (plan decision 1, settled): the ticket archive directory
`<SANDBAR_PROJECTS_DIR|~/.sandbar/projects>/<key>/data/tickets/<id>/` — the landing point
of the three-stage close-out (archive = the closed semantics endpoint). Path single
points stay in shared.py (perkey_projects_root / ticket_data_dir); this module counts the
archive, it does not invent a second path contract.

Pure logic (the unit-test surface, all injectable / malformed-input degrading):
  - count_archived_tickets(projects_root, project_key): counts per-key archived tickets;
    an illegal project_key or unreadable root fails closed with a named error; entries
    that are not ticket directories degrade item by item into meta (never a fake count).
  - next_cron_fire(expr, after): the next fire time for the declaration's five-field cron
    subset (same lexicon as inspection_decl: `*` `*/n` n n-m[/n] names, comma lists);
    dom/dow keep standard cron OR semantics when both are restricted; 0 and 7 are both
    Sunday. Deterministic, no wall clock (the caller supplies `after`).
  - decide(count, baseline, n, cron_due, now): the watcher's pure decision per the plan's
    R2 rules — a count crossing the bucket boundary triggers first (cron-advance follows
    via anchor); a due cron triggers with a baseline reset; same-day coexistence is legal
    (cron period = plain YYYYMMDD, count period = YYYYMMDD-<bucket>; the cron form never
    pre-occupies a bucket).

This module imports nothing beyond the stdlib (the count surface must stay reusable from
the zero-dependency declaration lane; shared is imported lazily by callers only).
"""

from __future__ import annotations

import calendar
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# 与 inspection_decl.INSTANCE_ID_RE 同字符集（project_key 与实例 id 同词法；越界形态
# ../、绝对路径、前导 - 在此拒收——路径拼接防逃逸的第一道闸）。
PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

_TICKETS_DIRNAME = "data"
_TICKETS_LEAF = "tickets"

_MONTH_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_DOW_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

_CRON_FIELD_LIMITS = (59, 23, 31, 12, 7)   # dow 收 0–7（7 随后并入 0=周日）


def _parse_atom(atom: str, limit: int, names: Optional[Dict[str, int]], floor: int = 0) -> Tuple[int, int, int]:
    """`atom` → (min, max, step)；解析失败抛 ValueError（点名原子，调用方翻译）。
    floor：域下界（日域=1，其余=0——`*` 展开不得把域外值收进集合，否则「未受限」判定失真）。"""
    step = 1
    body = atom
    if "/" in atom:
        body, _, step_raw = atom.partition("/")
        if not step_raw.isdigit() or int(step_raw) < 1:
            raise ValueError("步进非法：%r" % atom)
        step = int(step_raw)
    if body == "*":
        return floor, limit, step
    if "-" in body:
        lo_raw, _, hi_raw = body.partition("-")
        lo = _field_value(lo_raw, names)
        hi = _field_value(hi_raw, names)
    else:
        lo = hi = _field_value(body, names)
    if lo > limit or hi > limit or lo > hi:
        raise ValueError("域值越界/倒序：%r" % atom)
    return lo, hi, step


def _field_value(raw: str, names: Optional[Dict[str, int]]) -> int:
    raw = raw.strip().lower()
    if names and raw in names:
        return names[raw]
    if not raw.isdigit():
        raise ValueError("域值非法：%r" % raw)
    return int(raw)


def parse_cron(expr: str) -> Tuple[set, set, set, set, set]:
    """五字段 cron → 每域允许值集合（与 decl 词法一致；词法不符=ValueError 点名）。"""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("cron 须五字段（got %d）：%r" % (len(fields), expr))
    out = []
    for pos, f in enumerate(fields):
        names = {0: None, 1: None, 2: None, 3: _MONTH_NAMES, 4: _DOW_NAMES}[pos]
        limit = _CRON_FIELD_LIMITS[pos]
        vals: set = set()
        floor = 1 if pos == 2 else 0     # 日域从 1 起（0 不是合法日）
        for atom in f.split(","):
            lo, hi, step = _parse_atom(atom, limit, names, floor)
            vals.update(range(lo, hi + 1, step))
        out.append(vals)
    minute, hour, dom, month, dow = out
    # 0 与 7 都是星期日（标准 cron 语义）
    if 7 in dow:
        dow = set(dow) | {0}
        dow.discard(7)
    return minute, hour, dom, month, dow


def _cron_dow(day: datetime) -> int:
    """cron 星期数（0=周日）——Python weekday() 是 0=周一，换算差一天（词法对齐 decl）。"""
    return (day.weekday() + 1) % 7


def _dom_dow_match(day: datetime, dom: set, dow: set, dom_restricted: bool, dow_restricted: bool) -> bool:
    if dom_restricted and dow_restricted:
        # 标准 cron：两域都受限时 OR
        return day.day in dom or _cron_dow(day) in dow
    return ((day.day in dom if dom_restricted else True)
            and (_cron_dow(day) in dow if dow_restricted else True))


def next_cron_fire(expr: str, after: datetime) -> datetime:
    """after 之后的下一次命中（不含 after 本身）；一年内无命中=ValueError（点名表达式，
    不静默返回远期——表达式可解析但永不该触发是声明事故，须显式暴露）。"""
    minute, hour, dom, month, dow = parse_cron(expr)
    dom_restricted = dom != set(range(1, 32))
    dow_restricted = dow != set(range(7))
    day = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    for _ in range(1461):  # 四年搜索上限（闰年日 02-29 形态需跨到下一闰年；上限内无命中才判永不触发）
        if _dom_dow_match(day, dom, dow, dom_restricted, dow_restricted) and day.month in month:
            for hm in range(24 * 60):
                cand = day.replace(hour=hm // 60, minute=hm % 60)
                if cand > after and cand.minute in minute and cand.hour in hour:
                    return cand
        day = (day + timedelta(days=1)).replace(hour=0, minute=0)
        # 月份位数在换日后重查（上循环已含 month 判定）
    raise ValueError("cron %r 四年内无命中（声明可解析但永不触发=显式报错）" % expr)


def count_archived_tickets(projects_root: str, project_key: str) -> Dict[str, Any]:
    """计数：per-key 归档目录下的一级条目数（每张已归档票=一个 <id> 目录）。
    fail-closed：project_key 词法非法 / 根或 key 目录不存在 → ok=False 带点名错误
    （不猜 0——「0 张」与「数不了」是两个事实）；混杂条目（文件、点前缀杂物）逐项
    降级进 meta.skipped，不假绿不崩。"""
    key = str(project_key or "").strip()
    if not PROJECT_KEY_RE.match(key):
        return {"ok": False, "error": "project_key 非法：%r（白名单 %s）" % (key, PROJECT_KEY_RE.pattern)}
    root = Path(projects_root) if projects_root else None
    if root is None:
        # 与 shared.perkey_projects_root 同语义（env 覆盖，空/相对=未设）。
        env = os.environ.get("SANDBAR_PROJECTS_DIR") or ""
        root = Path(env) if env and os.path.isabs(env) else (
            Path.home() / ".sandbar" / "projects")
    key_dir = root / key / _TICKETS_DIRNAME / _TICKETS_LEAF
    if not key_dir.is_dir():
        return {"ok": False, "error": "计数源不可达：%s 不存在或不是目录（project_key=%s）"
                % (key_dir, key)}
    entries = sorted(key_dir.iterdir())
    count = 0
    skipped = []
    for e in entries:
        if e.is_dir() and not e.name.startswith("."):
            count += 1
        else:
            skipped.append(e.name)
    return {"ok": True, "result": {"count": count, "project_key": key,
                                   "meta": {"skipped": skipped, "root": str(key_dir)}}}


def count_period(now: datetime, bucket: int) -> str:
    """计数触发的期号 = YYYYMMDD-<bucket>（桶号=基线计数//n；cron 期不预占桶）。"""
    return "%s-%d" % (now.strftime("%Y%m%d"), bucket)


def decide(count: int, baseline: int, n: int, cron_due: bool, now: datetime) -> Dict[str, Any]:
    """watcher 单轮纯决策（R2 语义的单点实现，验收 e 的断言锚）：
      - 计数越桶（count//n > baseline//n）→ count 触发：期号=当日-桶号，基线复位为
        当前计数（复位后同桶不再二触=天然 dedup）；cron 相位推进由调用方把 anchor=now
        落进下轮（计数触发优先于 cron——先到者取更早事件，轮询粒度内计数先判）。
      - 否则 cron 到点 → cron 触发：期号=纯当日，基线复位为当前计数（cron 触发后
        基线复位——R2 另一侧）。
      - 都不满足 → 不触发，状态原样。
    触发事件定义期界：桶号随基线复位单调、不必连续（review_plan gen1 已核自洽）。"""
    if n < 1:
        raise ValueError("n 必须 ≥1（got %d）" % n)
    if count < 0 or baseline < 0:
        raise ValueError("count/baseline 非负（got count=%r baseline=%r）" % (count, baseline))
    count_bucket = count // n
    base_bucket = baseline // n
    if count_bucket > base_bucket:
        return {"trigger": "count", "period": count_period(now, count_bucket),
                "baseline": count, "anchor": now}
    if cron_due:
        return {"trigger": "cron", "period": now.strftime("%Y%m%d"),
                "baseline": count, "anchor": now}
    return {"trigger": None, "period": "", "baseline": baseline, "anchor": None}


def days_in_month(year: int, month: int) -> int:
    """日历工具（cron 月尾边界单测用；calendar 引在这里集中）。"""
    return calendar.monthrange(year, month)[1]
