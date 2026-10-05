"""t260911-02 单测：票计数源与 watcher 纯逻辑（inspection_ticket_count）。

畸形输入纪律：project_key 越界 / root 缺失 / 混杂条目 / cron 词法坏 / decide 非法参数，
全部就地点名（fail-closed 或逐项降级），不假绿不崩。
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_ticket_count as tc


# ---------- count_archived_tickets ----------

def _mk_archive(root: Path, key: str, tickets, junk=()):
    d = root / key / "data" / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    for t in tickets:
        (d / t).mkdir()
    for j in junk:
        p = d / j
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8") if "." in j else p.mkdir()


def test_count_ok_and_junk_degraded_to_meta(tmp_path):
    _mk_archive(tmp_path, "sandbar", ["t-a", "t-b"], junk=["loose.txt", ".hidden"])
    r = tc.count_archived_tickets(str(tmp_path), "sandbar")
    assert r["ok"] is True and r["result"]["count"] == 2
    assert sorted(r["result"]["meta"]["skipped"]) == [".hidden", "loose.txt"]


def test_count_empty_dir_is_zero(tmp_path):
    _mk_archive(tmp_path, "k", [])
    r = tc.count_archived_tickets(str(tmp_path), "k")
    assert r["ok"] is True and r["result"]["count"] == 0


def test_count_illegal_project_key_fail_closed(tmp_path):
    for bad in ("../evil", "/abs", "", "UPPER", "-lead"):
        r = tc.count_archived_tickets(str(tmp_path), bad)
        assert r["ok"] is False and "project_key" in r["error"], bad


def test_count_missing_root_is_named_not_zero(tmp_path):
    r = tc.count_archived_tickets(str(tmp_path / "nope"), "k")
    assert r["ok"] is False and "不可达" in r["error"] and "k" in r["error"]


def test_count_env_root_respected(monkeypatch, tmp_path):
    _mk_archive(tmp_path, "envk", ["t1"])
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    r = tc.count_archived_tickets("", "envk")
    assert r["ok"] is True and r["result"]["count"] == 1


# ---------- next_cron_fire ----------

def test_cron_next_basic_and_step():
    assert tc.next_cron_fire("0 9 * * 1", datetime(2026, 9, 11, 10, 0)) == \
        datetime(2026, 9, 14, 9, 0)                      # 周五10点 → 下周一
    assert tc.next_cron_fire("*/15 8 * * *", datetime(2026, 9, 11, 8, 0)) == \
        datetime(2026, 9, 11, 8, 15)                     # 步进：不含 after 本身
    assert tc.next_cron_fire("0 9 1 * *", datetime(2026, 9, 11, 0, 0)) == \
        datetime(2026, 10, 1, 9, 0)                      # 跨月


def test_cron_month_end_and_names():
    # 9 月无 31 → 跳到 10-31（月尾边界）
    assert tc.next_cron_fire("0 0 31 * *", datetime(2026, 9, 11)) == datetime(2026, 10, 31, 0, 0)
    assert tc.next_cron_fire("0 0 * * mon", datetime(2026, 9, 11)) == datetime(2026, 9, 14)
    assert tc.next_cron_fire("0 0 29 2 *", datetime(2026, 1, 1)) == datetime(2028, 2, 29)  # 闰年


def test_cron_dow_7_is_sunday():
    # 2026-09-13 是周日：0 与 7 等价
    assert tc.next_cron_fire("0 0 * * 7", datetime(2026, 9, 11)) == datetime(2026, 9, 13)
    assert tc.next_cron_fire("0 0 * * 0", datetime(2026, 9, 11)) == datetime(2026, 9, 13)


def test_cron_malformed_named():
    for expr in ("61 9 * * *", "0 9 *", "* * * * * *", "0 9 * * foo", "abc"):
        with pytest.raises(ValueError):
            tc.parse_cron(expr)


def test_cron_never_firing_named_within_four_years():
    # 2 月 30 日：可解析词法但四年内无命中 → 显式报错（不静默返回远期）
    with pytest.raises(ValueError, match="no firing within four years"):
        tc.next_cron_fire("0 0 30 2 *", datetime(2026, 1, 1))


# ---------- decide（R2 语义单点） ----------

NOW = datetime(2026, 9, 11, 12, 0)


def test_decide_count_crossing_triggers_and_resets():
    d = tc.decide(41, 20, 20, False, NOW)
    assert d["trigger"] == "count" and d["period"] == "20260911-2" and d["baseline"] == 41


def test_decide_same_bucket_no_retrigger():
    assert tc.decide(41, 41, 20, False, NOW)["trigger"] is None


def test_decide_cron_due_resets_baseline_and_period_plain():
    d = tc.decide(41, 41, 20, True, NOW)
    assert d["trigger"] == "cron" and d["period"] == "20260911" and d["baseline"] == 41


def test_decide_count_takes_precedence_over_cron():
    d = tc.decide(60, 40, 20, True, NOW)
    assert d["trigger"] == "count" and d["period"] == "20260911-3"


def test_decide_bucket_monotonic_not_contiguous_after_reset():
    # 基线复位后桶号从当前计数重算：不必连续（触发事件定义期界）
    d1 = tc.decide(100, 0, 20, False, NOW)      # → bucket 5
    assert d1["period"] == "20260911-5"
    d2 = tc.decide(105, 100, 20, False, NOW)    # 基线=100 → bucket 5 同桶不触
    assert d2["trigger"] is None
    d3 = tc.decide(120, 100, 20, False, NOW)    # bucket 6
    assert d3["period"] == "20260911-6"


def test_decide_malformed_args_named():
    for args in ((5, 0, 0, False, NOW), (-1, 0, 5, False, NOW), (0, -1, 5, False, NOW)):
        with pytest.raises(ValueError):
            tc.decide(*args)


def test_count_period_shape():
    assert tc.count_period(datetime(2026, 9, 11), 3) == "20260911-3"
