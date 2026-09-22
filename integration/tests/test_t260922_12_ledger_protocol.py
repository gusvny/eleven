#!/usr/bin/env python3
"""t260922-12 台账采信边界 × 归属组合真值表（纯函数面；门契约 L2 灰盒）。

被测面（failure_protocol 公开函数，按契约锚不锚私有）：
- ledger_trust：采信边界四条（指纹相等/commit 祖先或相同/≤7 天/宽度一致）+
  「检验到」前提（env_fail/skip 不采信）+ 畸形记录不采信，逐条给 reason；
- ledger_ts_epoch：ISO8601 带时区才可判（naive/坏串 → None，不猜时区）；
- apply_affiliation_ledger（票据⑥正反例逐条锁死，防「台账变假绿机」）：
  正例=台账红既有欠账 → record 不拦；反例1=台账绿而泳道红 → 仍拦；
  反例2=无记录/指纹不等/过期/宽度不等 → 原判定（回退实跑口径）不变；
  活基线 checked 权威优先于台账；violation 先于一切；全绿永不受牵连。

零 docker、零网络、零真台账、零进程——时间冻结在 NOW，真值表不随墙钟漂移。
"""
import datetime as _dt
import importlib.util
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "fp_t92212_under_test", REPO / "server" / "engine" / "failure_protocol.py")
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)

NOW = 1_800_000_000.0
FP = "a" * 64
FP_OTHER = "f" * 64
SHA_BASE = "b" * 40
SHA_OLD = "c" * 40


def _iso(epoch):
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).isoformat()


def rec(verdict="fail", age_s=3600.0, commit=SHA_OLD, env_fp=FP, conc=4, **over):
    """可信台账行工厂（默认=全部边界满足）；age_s=None 表示 ts 用坏值。"""
    r = {"ts": _iso(NOW - age_s) if age_s is not None else "not-a-ts",
         "commit": commit, "env_fp": env_fp, "conc_width": conc,
         "pool": "main", "scenario": "s1", "verdict": verdict,
         "wall_s": 1.0, "source": "inspection", "ticket": ""}
    r.update(over)
    return r


def lane(status="fail", name="s1", cause="self", reason="assert_mismatch",
         evidence="evidence-x"):
    return {"name": name, "suite": "main", "status": status, "cause": cause,
            "reason": reason, "dur_s": 1.0, "attempt": 1, "started": "",
            "git_sha": "", "evidence": evidence, "artifacts": []}


def base_case(status="fail", name="s1"):
    return lane(status=status, name=name,
                evidence="" if status == "not-checked" else "baseline-evidence")


LANE_FP = {"value": FP, "keys": {"python": "3.x"}}
ANS = {"trusted": True, "reason": "trusted"}


def aff(lane_cases, baseline=(), ledger=None, baseline_ok=True,
        baseline_fp=None):
    return fp.apply_affiliation_ledger(
        lane_cases, list(baseline), LANE_FP,
        baseline_fp if baseline_fp is not None else LANE_FP,
        baseline_ok=baseline_ok, ledger_answers=ledger or {})


def ans(verdict, ts="2026-09-21T08:00:00+00:00", source="inspection"):
    return dict(ANS, verdict=verdict, ts=ts, source=source)


# ---------------- ledger_ts_epoch ----------------

def test_ts_epoch_accepts_offset_and_z():
    assert fp.ledger_ts_epoch("2026-09-21T08:00:00+00:00") is not None
    assert fp.ledger_ts_epoch("2026-09-21T08:00:00Z") is not None


def test_ts_epoch_rejects_naive_garbage_empty():
    assert fp.ledger_ts_epoch("2026-09-21T08:00:00") is None   # naive 不猜时区
    assert fp.ledger_ts_epoch("not-a-ts") is None
    assert fp.ledger_ts_epoch("") is None
    assert fp.ledger_ts_epoch(None) is None
    assert fp.ledger_ts_epoch(123) is None


# ---------------- ledger_trust：四条边界 + 检验到前提，缺一不可 ----------------

def test_trust_trusted_for_checked_fail_and_pass():
    assert fp.ledger_trust(rec("fail"), FP, True, 4, NOW)["trusted"] is True
    assert fp.ledger_trust(rec("pass"), FP, True, 4, NOW)["trusted"] is True


def test_trust_env_fail_and_skip_never_trusted():
    """没检验到的行不入「main 红/绿」证据（同基线 not-checked 口径）。

    保留位经 LEDGER_VERDICTS 常量取（词表单一真源；lint L6 词表只认
    pass/fail/env_fail/na，字面量会误伤三态闸）。"""
    for v in ("env_fail", fp.LEDGER_VERDICTS[3], "unknown", ""):
        t = fp.ledger_trust(rec(v), FP, True, 4, NOW)
        assert t["trusted"] is False and t["reason"].startswith("verdict_unusable"), t


def test_trust_fingerprint_mismatch():
    t = fp.ledger_trust(rec("fail", env_fp=FP_OTHER), FP, True, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "fingerprint_mismatch"


def test_trust_commit_not_ancestor():
    t = fp.ledger_trust(rec("fail"), FP, False, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "commit_not_ancestor_of_base"


def test_trust_age_boundary_exact_7d_trusted_over_expired():
    assert fp.ledger_trust(rec("fail", age_s=7 * 86400), FP, True, 4, NOW)["trusted"] is True
    t = fp.ledger_trust(rec("fail", age_s=7 * 86400 + 1), FP, True, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "expired(>7d)"


def test_trust_future_beyond_tolerance_rejected():
    t = fp.ledger_trust(rec("fail", age_s=-3600), FP, True, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "ts_in_future"


def test_trust_width_mismatch_and_unusable():
    t = fp.ledger_trust(rec("fail", conc=1), FP, True, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "conc_width_mismatch"
    for bad in (0, True, "4", None, 4.5):
        t = fp.ledger_trust(rec("fail", conc=bad), FP, True, 4, NOW)
        assert t["trusted"] is False and t["reason"] == "conc_width_unusable", (bad, t)


def test_trust_malformed_records_rejected():
    t = fp.ledger_trust(None, FP, True, 4, NOW)
    assert t["reason"] == "ledger_record_not_dict"
    t = fp.ledger_trust({"verdict": "fail"}, FP, True, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "fingerprint_mismatch"
    t = fp.ledger_trust(rec("fail", age_s=None), FP, True, 4, NOW)
    assert t["trusted"] is False and t["reason"] == "ts_unusable"


# ---------------- apply_affiliation_ledger：票据⑥正反例逐条 ----------------

def test_positive_ledger_red_means_record_not_block():
    """正例：记账为 main 同红（既有欠账）→ record 不拦（诚实计数）。"""
    out = aff([lane()], ledger={"s1": ans("fail")})
    v = {x["name"]: x for x in out["verdicts"]}
    assert v["s1"]["verdict"] == "record"
    assert v["s1"]["why"] == "ledger_red(既有欠账·台账)"
    assert out["blockers"] == [] and "s1" in out["records"]
    assert out["ledger"]["overridden"] == ["s1"]
    assert out["ledger"]["hits_red"] == ["s1"]


def test_negative1_ledger_green_lane_red_still_blocks():
    """反例1：记账为绿、泳道红（真回归）→ 仍然拦。"""
    out = aff([lane()], ledger={"s1": ans("pass")})
    assert out["blockers"] == ["s1"] and out["records"] == []
    assert out["ledger"]["overridden"] == []
    assert out["ledger"]["hits_green"] == ["s1"]


def test_negative2_no_record_falls_back_to_block():
    """反例2a：无记录 → 回退实跑口径（fail 保守拦），绝不放过。"""
    out = aff([lane()], ledger={})
    assert out["blockers"] == ["s1"]


def test_negative2_untrusted_reasons_fall_back():
    """反例2b/2c/2d：指纹不等/过期/宽度不等 → 不采信，口径与无记录相同。"""
    out_fp = aff([lane()], ledger={"s1": dict(ans("fail"), reason="fingerprint_mismatch",
                                              trusted=False)})
    out_exp = aff([lane()], ledger={"s1": dict(ans("fail"), reason="expired(>7d)",
                                               trusted=False)})
    out_w = aff([lane()], ledger={"s1": dict(ans("fail"), reason="conc_width_mismatch",
                                             trusted=False)})
    for out in (out_fp, out_exp, out_w):
        assert out["blockers"] == ["s1"] and out["ledger"]["overridden"] == []


def test_baseline_red_authority_beats_ledger():
    """活基线 checked 结果权威：基线红（记录）不被台账绿翻案。"""
    out = aff([lane()], baseline=[base_case("fail")], ledger={"s1": ans("pass")})
    assert "s1" in out["records"] and out["blockers"] == []
    assert out["ledger"]["overridden"] == []


def test_baseline_green_beats_ledger_red():
    """基线跑过且绿 → 台账红不改判（活跑更新鲜，仍拦）。"""
    out = aff([lane()], baseline=[base_case("pass")], ledger={"s1": ans("fail")})
    assert out["blockers"] == ["s1"] and out["ledger"]["overridden"] == []
    # 佐证面仍可见（ consulted/hits_red ）
    assert out["ledger"]["hits_red"] == ["s1"]


def test_baseline_not_checked_plus_ledger_red_records():
    """基线没检验到（not-checked）+ 台账红 → record（t260922-08 病灶解）。"""
    out = aff([lane()], baseline=[base_case("not-checked")],
              ledger={"s1": ans("fail")})
    assert out["blockers"] == [] and out["ledger"]["overridden"] == ["s1"]


def test_baseline_unavailable_plus_ledger_red_records():
    """基线缺席（ok=False）+ 台账可信红 → record（依赖型场景基线起不来的翻案路）。"""
    out = aff([lane()], baseline=[], baseline_ok=False,
              ledger={"s1": ans("fail")})
    assert out["blockers"] == [] and out["ledger"]["overridden"] == ["s1"]


def test_baseline_fp_mismatch_plus_ledger_red_records():
    """泳道×基线指纹不等（不可比）不影响台账采信（台账只对 lane 现指纹比）。"""
    other = {"value": FP_OTHER, "keys": {"python": "9"}}
    out = aff([lane()], baseline=[base_case("not-checked")],
              baseline_fp=other, ledger={"s1": ans("fail")})
    assert out["blockers"] == [] and out["ledger"]["overridden"] == ["s1"]


def test_violation_blocks_regardless_of_ledger():
    """协议违约先于一切：fail×prepare 型 reason 改判+独立拦，台账红不救。"""
    out = aff([lane(reason="lock_busy")], ledger={"s1": ans("fail")})
    assert out["blockers"] == ["s1"] and out["ledger"]["overridden"] == []


def test_all_green_untouched_by_ledger():
    """全绿用例永不受牵连（哪怕台账里同名有红行）。"""
    out = aff([lane(status="pass"), lane(status="pass", name="s2")],
              ledger={"s1": ans("fail")})
    assert all(v["verdict"] == "pass" for v in out["verdicts"])
    assert out["blockers"] == [] and out["records"] == []


def test_not_checked_self_ledger_red_records_and_green_blocks():
    """not-checked×self：台账红 → record；台账绿 → 维持拦（本票造成方向不变）。"""
    nc = lane(status="not-checked", reason="other")
    out_red = aff([nc], ledger={"s1": ans("fail")})
    assert out_red["blockers"] == [] and out_red["ledger"]["overridden"] == ["s1"]
    out_green = aff([nc], ledger={"s1": ans("pass")})
    assert out_green["blockers"] == ["s1"] and out_green["ledger"]["overridden"] == []


def test_not_checked_external_record_unchanged():
    """not-checked×external 本就 record（促治理不堵），台账不改不拦。"""
    ext = lane(status="not-checked", cause="external", reason="other")
    out = aff([ext], ledger={"s1": ans("fail")})
    assert out["blockers"] == [] and "s1" in out["records"]
    assert out["ledger"]["overridden"] == []


def test_face_shape():
    """返回形状=apply_affiliation 全集 + ledger 面（消费方兼容）。"""
    out = aff([lane(), lane(status="pass", name="s2")],
              ledger={"s1": ans("fail")})
    for k in ("cases", "verdicts", "affiliation_confidence", "fp_diffs",
              "blockers", "records", "unknowns", "violations", "ledger"):
        assert k in out, k
    for k in ("consulted", "hits_red", "hits_green", "overridden"):
        assert k in out["ledger"], k
