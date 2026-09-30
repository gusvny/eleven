"""在册红不进每轮路径——纯函数与读面单测（t260930-01，宿主裁 260930「B 档只摘在册」）。

分工：本文件锁**纯判据与读面**（挂账册哪些条目该跳、读不动时怎么办）；
`integration/t260930-01/sc_known_red_round_skip.py` 锁**黑盒行为面**（真执行器子进程
三态：开关开=具名跳过 / 开关关=照旧全跑 / 册子坏=fail-closed 照跑且具名）。
台账绿行复用是另一条判据线（判据=台账四键），其单测在 test_t260930_01_ledger_reuse.py。
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def rs():
    """按文件位装载执行器（与本仓既有电池同口径：不依赖 sys.path 前提）。"""
    spec = importlib.util.spec_from_file_location(
        "rs_known_red_under_test", REPO / "integration" / "run_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _roster(*pairs):
    return {"meta": {"max_entries": 99},
            "entries": [{"name": n, "verdict": v} for n, v in pairs]}


# ---------------- 纯判据：known_red_names ----------------

def test_booked_and_isolated_are_skippable(rs):
    r = _roster(("a", "booked"), ("b", "isolated"))
    assert rs.known_red_names(r) == ["a", "b"]


def test_unknown_verdict_is_not_skippable(rs):
    """认不得的词一律**跑**（宁慢勿窄）——名册词表演进时不得静默放宽。"""
    r = _roster(("a", "booked"), ("b", "future-verdict"), ("c", ""))
    assert rs.known_red_names(r) == ["a"]


def test_malformed_entries_are_dropped_without_raising(rs):
    r = {"meta": {}, "entries": [
        {"name": "a", "verdict": "booked"},
        {"name": "", "verdict": "booked"},
        {"name": "   ", "verdict": "isolated"},
        {"name": 123, "verdict": "booked"},
        {"name": "ok", "verdict": None},
        {"verdict": "booked"},
        "junk",
        None,
    ]}
    assert rs.known_red_names(r) == ["a"]


def test_non_dict_roster_yields_nothing(rs):
    for bad in (None, [], "x", 3, {"entries": "x"}, {"entries": None}):
        assert rs.known_red_names(bad) == []


def test_candidates_intersect_only_this_round(rs):
    """点名轮：册内但不在本轮注册面的条目**不进**跳过名单（只看本轮）。"""
    r = _roster(("a", "booked"), ("b", "booked"), ("c", "isolated"))
    assert rs.known_red_names(r, ["a", "c", "zzz"]) == ["a", "c"]
    assert rs.known_red_names(r, []) == []


def test_output_is_sorted_and_deduped(rs):
    r = {"meta": {}, "entries": [
        {"name": "b", "verdict": "booked"},
        {"name": "a", "verdict": "booked"},
        {"name": "b", "verdict": "isolated"},
    ]}
    assert rs.known_red_names(r) == ["a", "b"]


# ---------------- 读面：read_known_red_roster ----------------

def test_missing_roster_is_named_and_skips_nothing(rs, tmp_path):
    names, err = rs.read_known_red_roster(str(tmp_path))
    assert names == [] and "不在场" in err


def test_bad_json_is_named_and_skips_nothing(rs, tmp_path):
    d = tmp_path / "integration"
    d.mkdir()
    (d / "known-red-baseline.json").write_text("{bad json", encoding="utf-8")
    names, err = rs.read_known_red_roster(str(tmp_path))
    assert names == []
    assert err and ("解析失败" in err or "读取" in err)


def test_wrong_shape_is_named_and_skips_nothing(rs, tmp_path):
    d = tmp_path / "integration"
    d.mkdir()
    (d / "known-red-baseline.json").write_text(json.dumps({"meta": {}}), encoding="utf-8")
    names, err = rs.read_known_red_roster(str(tmp_path))
    assert names == [] and "形状不合法" in err


def test_env_seam_overrides_path(rs, tmp_path, monkeypatch):
    """路径覆盖缝：夹具册子/换册子不必改树（测试与运维同一缝）。"""
    p = tmp_path / "roster.json"
    p.write_text(json.dumps(_roster(("only-here", "booked"))), encoding="utf-8")
    monkeypatch.setenv(rs.KNOWN_RED_ROSTER_ENV, str(p))
    names, err = rs.read_known_red_roster(str(tmp_path / "nope"))
    assert err == "" and names == ["only-here"]


def test_real_registry_reads_and_every_entry_is_booked_or_isolated(rs):
    """真册冒烟：读得动，且逐条 verdict 都在词表内（schema 卫生另有专门测试）。"""
    names, err = rs.read_known_red_roster(str(REPO))
    assert err == ""
    payload = json.loads((REPO / "integration" / "known-red-baseline.json")
                         .read_text(encoding="utf-8"))
    assert names == sorted({e["name"] for e in payload["entries"]})
    assert all(e["verdict"] in rs.KNOWN_RED_BOOKED_VERDICTS
               for e in payload["entries"])


def test_face_truncates_and_names_total(rs):
    face = rs._known_red_face([str(i) for i in range(25)])
    assert face.endswith("（共 25 条）") and face.count(",") == rs.REUSE_PRINT_CAP - 1
    assert rs._known_red_face(["a", "b"]) == "a,b"
