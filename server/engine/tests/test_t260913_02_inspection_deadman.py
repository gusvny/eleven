"""t260913-02 单测②：漏跑（dead-man）与套件结果的纯函数面（含畸形输入用例）。

纪律（岗位说明书）：消费外部输入（台账文件/回执 JSON/声明）的实现，单测必带畸形输入，
用固定文件/桩复现，不靠真外部源。
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_deadman as dm
import inspection_flow as flow
import activities as activities_mod
import inspection_trigger as _trig
from inspection_flow import now_in_tz as _now_in_tz, period_key_in_tz as _pk_in_tz


# ========================================================================================
# 台账读取
# ========================================================================================

def _mk(tmp_path: Path, names) -> Path:
    d = tmp_path / "inspection"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("{}", "utf-8")
    return d


def test_ledger_periods_normal_and_bucket(tmp_path):
    d = _mk(tmp_path, ["inspection-integration-tests-20260912.json",
                       "inspection-integration-tests-20260913-2.json",
                       "inspection-integration-tests-20260913-suite.json",
                       "inspection-docs-sync-20260912.json",
                       "other.txt"])
    led = dm.ledger_periods(d, "integration-tests")
    assert led["exist"] and led["periods"] == {"20260912", "20260913-2"}
    assert led["malformed"] == []


def test_ledger_periods_missing_dir_is_empty_not_error(tmp_path):
    led = dm.ledger_periods(tmp_path / "nope", "integration-tests")
    assert led["exist"] is False and led["periods"] == set() and led["count"] == 0


def test_ledger_periods_malformed_names_are_reported(tmp_path):
    d = _mk(tmp_path, ["inspection-integration-tests-2026-09-12.json",
                       "inspection-integration-tests-.json",
                       "inspection-integration-tests-20260912.json"])
    led = dm.ledger_periods(d, "integration-tests")
    assert led["periods"] == {"20260912"}
    assert sorted(led["malformed"]) == ["inspection-integration-tests-.json",
                                        "inspection-integration-tests-2026-09-12.json"]


def test_ledger_periods_prefix_sibling_attribution(tmp_path):
    """P1 连带修正（本票日报票面恒带 med「台账畸形条目」的真根因）：互为前缀的实例 id
    （integration-tests vs integration-tests-00245）必须各自归账——前缀硬切会把「他实例
    的合法台账」误判成本实例畸形条目。期号锚在文件名尾部解析。"""
    d = _mk(tmp_path, ["inspection-integration-tests-00245-20260914.json",
                       "inspection-integration-tests-20260913.json",
                       "inspection-integration-tests-20260913-1.json",
                       "inspection-integration-tests-2026-09-14.json"])
    mine = dm.ledger_periods(d, "integration-tests")
    assert mine["periods"] == {"20260913", "20260913-1"}
    # 无法解析且带本实例前缀 → 畸形（点名不静默）
    assert mine["malformed"] == ["inspection-integration-tests-2026-09-14.json"]
    # 长实例自己归自己的账
    sib = dm.ledger_periods(d, "integration-tests-00245")
    assert sib["periods"] == {"20260914"} and sib["malformed"] == []


def test_ledger_periods_empty_instance_is_empty(tmp_path):
    d = _mk(tmp_path, ["inspection-a-20260912.json"])
    assert dm.ledger_periods(d, "")["periods"] == set()


def test_ledger_periods_prefix_does_not_cross_instances(tmp_path):
    """前缀相近的实例名不得互串（integration-tests vs integration-tests-2）。"""
    d = _mk(tmp_path, ["inspection-integration-tests-2-20260912.json",
                       "inspection-integration-tests-20260912.json"])
    assert dm.ledger_periods(d, "integration-tests")["periods"] == {"20260912"}


# ========================================================================================
# 漏跑判定（cron × 台账）
# ========================================================================================

def test_missed_periods_none_when_all_ran():
    now = datetime(2026, 9, 13, 8, 0)
    known = ["202609%02d" % d for d in range(6, 13)]
    assert dm.missed_periods("30 7 * * *", known, now) == []


def test_missed_periods_reports_gap_only():
    now = datetime(2026, 9, 13, 8, 0)
    known = ["20260906", "20260907", "20260910", "20260911", "20260912"]
    assert dm.missed_periods("30 7 * * *", known, now) == ["20260908", "20260909"]


def test_missed_periods_today_never_flagged():
    """C6 边界：当日 07:30 之后的「今天」不算漏（当期票可能正在跑、尚未落账）。"""
    now = datetime(2026, 9, 13, 9, 0)          # 已过 07:30
    known = ["202609%02d" % d for d in range(6, 13)]   # 09-06..09-12 全在册
    assert dm.missed_periods("30 7 * * *", known, now) == []


def test_missed_periods_grace_defers_recent_miss():
    now = datetime(2026, 9, 13, 8, 0)
    known = ["20260906", "20260907", "20260908", "20260909", "20260910"]
    assert dm.missed_periods("30 7 * * *", known, now) == ["20260911", "20260912"]
    assert dm.missed_periods("30 7 * * *", known, now, grace_days=1) == ["20260911"]
    assert dm.missed_periods("30 7 * * *", known, now, grace_days=2) == []


def test_missed_periods_weekly_cron_and_lookback():
    now = datetime(2026, 9, 17, 12, 0)          # 周四；周一 10:00 该跑
    known = ["20260907", "20260914"]
    assert dm.missed_periods("0 10 * * 1", known, now) == []
    assert dm.missed_periods("0 10 * * 1", ["20260907"], now) == ["20260914"]
    # 回看窗口限制：更早的周一（09-07）不在窗口内（不翻旧账）
    assert dm.missed_periods("0 10 * * 1", ["20260914"], now, lookback_days=3) == []
    assert dm.missed_periods("0 10 * * 1", [], now, lookback_days=3) == ["20260914"]


def test_missed_periods_lookback_clamped():
    now = datetime(2026, 9, 13, 8, 0)
    out = dm.missed_periods("30 7 * * *", [], now, lookback_days=0)   # 畸形小值 → 下限 1
    assert out == ["20260912"]
    out2 = dm.missed_periods("30 7 * * *", [], now, lookback_days=10 ** 6)  # 上限 90
    assert len(out2) == 90


def test_missed_periods_bad_cron_raises():
    with pytest.raises(ValueError):
        dm.missed_periods("not a cron", [], datetime(2026, 9, 13, 8, 0))
    with pytest.raises(ValueError):
        dm.missed_periods("99 99 * * *", [], datetime(2026, 9, 13, 8, 0))


def test_expected_fires_window_is_half_open():
    fires = dm.expected_fires("30 7 * * *", datetime(2026, 9, 13, 8, 0), lookback_days=3)
    assert [f.strftime("%Y%m%d") for f in fires] == ["20260910", "20260911", "20260912"]
    assert all(f.hour == 7 and f.minute == 30 for f in fires)


# ========================================================================================
# 漏跑发现 / 套件发现
# ========================================================================================

def test_deadman_findings_high_suggest_false_and_not_truncated():
    missed = ["202609%02d" % d for d in range(1, 8)]
    got = dm.deadman_findings(missed, "integration-tests", "30 7 * * *")
    assert len(got) == 1
    f = got[0]
    assert f["severity"] == "high" and f["suggest"] is False and f["scan"] == "deadman"
    for p in missed:
        assert p in f["subject"]           # C7：期号全列，不进截断池
    assert "deadman" in f["evidence"]      # 指回 CLI 可读面


def test_deadman_findings_empty_when_no_miss():
    assert dm.deadman_findings([], "i", "30 7 * * *") == []


def _receipt(**kw):
    base = {"ran": 0, "passed": 0, "failed": 0, "env_fail": 0, "error": "",
            "report_path": "/out/x-suite.json", "details": []}
    base.update(kw)
    return base


def test_suite_findings_all_green_is_empty():
    assert dm.suite_findings(_receipt(ran=3, passed=3)) == []


def test_suite_findings_error_is_high_not_a_code_fix():
    got = dm.suite_findings(_receipt(error="场景执行器整体超时（>5700s）"))
    assert len(got) == 1 and got[0]["severity"] == "high"
    assert "套件未跑成" in got[0]["subject"] and got[0]["suggest"] is False
    assert "/out/x-suite.json" in got[0]["evidence"]


def test_suite_findings_ran_zero_is_alarm():
    got = dm.suite_findings(_receipt(ran=0))
    assert len(got) == 1 and got[0]["severity"] == "high"
    assert "ran=0" in got[0]["subject"]


def test_suite_findings_reds_capped_with_drilldown():
    details = [{"name": "sc-%d" % i, "exit": 1, "output_tail": "boom%d" % i} for i in range(13)]
    got = dm.suite_findings(_receipt(ran=13, failed=13, details=details))
    per_item = [f for f in got if f["subject"].startswith("套件红：")]
    agg = [f for f in got if f["subject"].startswith("另有")]
    assert len(per_item) == dm.SUITE_RED_DETAIL_CAP == 10
    assert len(agg) == 1 and "3 条" in agg[0]["subject"]
    assert "/out/x-suite.json" in agg[0]["evidence"]     # 聚合条可下钻（C7）
    assert all(f["severity"] == "high" for f in got)


def test_suite_findings_env_fail_is_med_and_no_fix_ticket():
    got = dm.suite_findings(_receipt(ran=2, passed=0, env_fail=2,
                                     details=[{"name": "a", "exit": 2}, {"name": "b", "exit": 2}]))
    env = [f for f in got if f["scan"] == "suite" and f["severity"] == "med"]
    assert len(env) == 1 and env[0]["suggest"] is False


def test_suite_findings_malformed_inputs_fail_loud():
    assert dm.suite_findings("nope")[0]["severity"] == "high"
    assert dm.suite_findings(None)[0]["severity"] == "high"
    got = dm.suite_findings(_receipt(ran="many"))
    assert got and got[0]["severity"] == "high" and "畸形" in got[0]["subject"]
    # details 里有畸形条目：exit 缺失按红处理（判不了红绿=不得不看），非 dict 条目点名降级
    got2 = dm.suite_findings(_receipt(ran=1, failed=1,
                                      details=[{"name": "x", "exit": None}, "junk"]))
    assert any("套件红：x" in f["subject"] for f in got2)
    assert any("畸形 1 条" in f["subject"] for f in got2)


def test_suite_section_shapes_and_malformed():
    sec = dm.suite_section(_receipt(ran=2, passed=1, failed=1,
                                    details=[{"name": "a", "exit": 0},
                                             {"name": "b", "exit": 1}]), wall_seconds=9.5)
    assert sec["ran"] == 2 and sec["failed"] == 1 and sec["wall_seconds"] == 9.5
    assert [c["exit"] for c in sec["cases"]] == [0, 1]
    bad = dm.suite_section("junk")
    assert bad["ok"] is False and bad["cases"] == []


def test_suite_green_matrix():
    assert dm.suite_green({"ok": True, "ran": 2, "failed": 0, "env_fail": 0}) is True
    assert dm.suite_green({"ok": True, "ran": 0, "failed": 0, "env_fail": 0}) is False
    assert dm.suite_green({"ok": True, "ran": 2, "failed": 1, "env_fail": 0}) is False
    assert dm.suite_green({"ok": True, "ran": 2, "failed": 0, "env_fail": 1}) is False
    assert dm.suite_green({"ok": False, "ran": 2, "failed": 0, "env_fail": 0}) is False
    assert dm.suite_green(None) is False
    assert dm.suite_green({"ok": True, "ran": "x"}) is False


# ================= t260913-02 验收 P1：期号与期望键同一时区口径 =================

def test_period_key_in_tz_crosses_utc_day_boundary():
    """触发时刻 2026-09-14T23:30Z（=声明 tz Asia/Shanghai 的 09-15 07:30）→ 期号必须取
    **声明时区的日历日** 20260915（跨 UTC 日界正是 P1 的错位源）；tz 空=旧口径。"""
    from inspection_flow import period_key_in_tz
    fire = datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc)
    assert period_key_in_tz(fire, "Asia/Shanghai") == "20260915"
    assert period_key_in_tz(fire, "") == "20260914"          # 旧口径（tz 空）不变


def test_cross_boundary_cron_tz_fire_matches_deadman_expected_key():
    """评审点名单测：cron+tz 触发时刻 → 期号 == 期望键（P1 跨界）。
    期号铸取（period_key_in_tz）与漏跑期望键（missed_periods/expected_fires）走
    同一条声明 tz 回落链——两侧永不换基。"""
    from inspection_flow import now_in_tz, period_key_in_tz
    fire_utc = datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc)
    mint = period_key_in_tz(fire_utc, "Asia/Shanghai")
    # deadman 侧：把 now 放到「次日早上」的声明时区挂钟上评估期望触发日（deadman 只
    # 期望过去的火）——该次跨日界触发的期望键必须 == 铸出的期号
    after = now_in_tz(datetime(2026, 9, 16, 8, 0), "Asia/Shanghai")
    fires = dm.expected_fires("30 7 * * *", after, lookback_days=1)
    assert [f.strftime("%Y%m%d") for f in fires] == [mint]


def test_missed_periods_tz_basis_no_false_alarm_at_steady_state():
    """P1 回归（18 天稳态模拟的最小形态）：每日 07:30 Asia/Shanghai、台账按同口径
    齐 → 不告警（修前：期望键用本地日、铸号用 UTC 日 → 恒报「当期自己」）。"""
    now_cst = dm.now_in_tz(datetime(2026, 9, 15, 8, 0), "Asia/Shanghai")         if hasattr(dm, "now_in_tz") else datetime(2026, 9, 15, 8, 0)
    from inspection_flow import now_in_tz
    now_cst = now_in_tz(datetime(2026, 9, 15, 8, 0), "Asia/Shanghai")
    known = ["202609%02d" % d for d in range(8, 15)]           # 09-08..09-14 七天齐
    assert dm.missed_periods("30 7 * * *", known, datetime(2026, 9, 15, 8, 0),
                             7, 0, "Asia/Shanghai") == []
    # 缺一天 → 精确报那一天（真漏跑仍响）
    known.remove("20260912")
    assert dm.missed_periods("30 7 * * *", known, datetime(2026, 9, 15, 8, 0),
                             7, 0, "Asia/Shanghai") == ["20260912"]


def test_deadman_tz_passthrough_wired():
    """tz 必须从声明一路走到核算面：workflow deadman 活动参数、deadman 活动、CLI 三处
    都带 tz（任一处断链就回到 P1 的两侧换基）。"""
    import inspect as _inspect
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow._deadman_findings)
    assert '"tz": plan.get("tz") or ""' in src
    act = _inspect.getsource(activities_mod.run_inspection_deadman)
    assert 'tz_name = str(args.get("tz") or "")' in act
    assert "tz_name)" in act          # 透传进 missed_periods
    trig = _inspect.getsource(_trig.cmd_deadman)
    assert "it.tz" in trig


def test_read_suite_receipt_missing_and_malformed(tmp_path):
    assert dm.read_suite_receipt(tmp_path / "nope.json")["ok"] is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", "utf-8")
    assert dm.read_suite_receipt(bad)["ok"] is False
    arr = tmp_path / "arr.json"
    arr.write_text("[1,2]", "utf-8")
    assert dm.read_suite_receipt(arr)["ok"] is False
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"ran": 1}), "utf-8")
    r = dm.read_suite_receipt(good)
    assert r["ok"] and r["receipt"]["ran"] == 1


# ========================================================================================
# t260917-02（C1）：跳火 finding 两分支（observed 实锤 / inferred 兜底，leg 可辨不混装）
# ========================================================================================

STALE = {"workflow": "InspectionPeriodicWorkflow"}
FRESH = {"workflow": "InspectionPeriodicSpawnWorkflow"}


def test_skip_observed_leg_namesskip_count_and_running():
    fs = dm.skip_findings(2, 1, STALE, [])
    assert len(fs) == 1
    f = fs[0]
    assert f["leg"] == "observed" and f["severity"] == "high" and f["suggest"] is False
    assert "跳火实锤" in f["evidence"] and "skip 计数 2" in f["evidence"]
    assert "仍在 Running" in f["evidence"] and "schedule-up" in f["evidence"]


def test_skip_observed_suppresses_inferred():
    # observed 命中（即使 action 陈旧+missed 非空）→ 只出一条，不混装
    fs = dm.skip_findings(1, 1, STALE, ["20260915"])
    assert len(fs) == 1 and fs[0]["leg"] == "observed"


def test_skip_needs_both_count_and_running():
    # 计数非零但当前无 Running（历史跳火痕迹）→ 不出 finding（回执键承载可见性）
    assert dm.skip_findings(2, 0, STALE, []) == []
    assert dm.skip_findings(0, 3, STALE, []) == []


def test_skip_inferred_only_when_counters_unknown():
    fs = dm.skip_findings(None, None, STALE, ["20260914", "20260915"])
    assert len(fs) == 1 and fs[0]["leg"] == "inferred" and fs[0]["severity"] == "med"
    assert "20260914" in fs[0]["evidence"] and "兜底" in fs[0]["subject"]
    # 计数可得且全零 → 不推断（报错必须精确：无实锤不出疑似）
    assert dm.skip_findings(0, 0, STALE, ["20260914"]) == []


def test_skip_no_finding_when_action_points_spawner():
    assert dm.skip_findings(None, None, FRESH, ["20260914"]) == []   # action 已指 spawner
    assert dm.skip_findings(None, None, None, ["20260914"]) == []    # action 摘要不可得
    assert dm.skip_findings(0, 0, FRESH, []) == []                   # 全净
