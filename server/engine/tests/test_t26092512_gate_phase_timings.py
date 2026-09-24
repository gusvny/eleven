#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260925-12：闸段（run_integration_tests 段）分相计时 UT。

覆盖：
- A 纯函数 shared.gate_phase_timings：正常拼装 / activity_sum / unattributed 口径 /
  畸形输入（None / 非数值串 / 负数 / NaN）一律 0.0 不抛不冒充 / unattributed 允许为负
  （段墙钟 < Σ相位=时钟亚秒抖动，如实给负值不 clamp——负值本身就是漂移信号）。
- B 回执 additive 兼容：IntegrationRunResult / ConflictPrepResult / ReviewGateResult /
  ChangedFilesResult 新 timing 键全带缺省 0.0；老回执 dict（无新键）重建零改动——
  review 条件①「先例取舍」对照面（本票为纯 additive 新字段，非照搬 t260922-18
  补键先例：无消费方读语义变化，缺键=缺省=「未计时」显式态）。
- C 活动级（离线零 Temporal/零模型/零网络）：
  * run_handover_legs 有界并发（t260925-12 提速②）：3 条 sleep 移交命令并发墙钟 < 串行
    墙钟；SANDBAR_HANDOVER_CONC=1 回落串行；结果按输入序回填（并发不乱序）；
    计数口径（ran/passed/failed）与串行一致；
  * 畸形条目（非对象 / 空 cmd）记名不执行、不毁整段；
  * _handover_conc env 矩阵（缺省 4 / 畸形 4 / 显式 1 / 0 与负数回落 4）；
  * verify_review_gate / changed_files 自报 wall_s 字段在场（缺省工作区形态）。
- D 结构锚（源文本）：dev_lane 段尾拼 gate_phase_timings（单写者）+ __gate_timings__
  details 行；run_scenarios 前奏墙钟观测行；integration cmd 与执行器汇总行未动
  （红线：汇总行键集是下游解析契约，本票不扩）。
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import time
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402
from shared import (ChangedFilesArgs, ChangedFilesResult,  # noqa: E402
                    ConflictPrepResult, IntegrationRunResult, ReviewGateArgs,
                    ReviewGateResult, gate_phase_timings)


# ---------- A 纯函数（契约签名=(phases: dict, wall_s)，锁于 t260925-12 场景 B1/C1/C2/C3）----------

FULL = {"pre_check_s": 1.0, "main_sync_s": 10.0, "changed_files_s": 2.0,
        "suite_s": 500.0, "handover_s": 7.0}


def test_gate_phase_timings_full_receipt_residual():
    g = gate_phase_timings(dict(FULL), 600.0)
    assert set(g) == set(FULL) | {"unattributed_s"}
    assert g["unattributed_s"] == 600.0 - sum(FULL.values())


def test_gate_phase_timings_old_receipt_no_fake_zero_phases():
    # C1：缺 timings 的老回执 → 不假造 0 相位、unattributed==全墙钟
    g = gate_phase_timings({}, 600.0)
    zeros = [k for k, v in g.items() if k != "unattributed_s" and v == 0]
    assert not zeros and g["unattributed_s"] == 600.0


def test_gate_phase_timings_malformed_values_not_attributed():
    # C2：负数/字符串/NaN/None 不炸、垃圾不入归因（相位缺席化），residual 诚实
    g = gate_phase_timings({"suite_s": -5.0, "main_sync_s": "12s",
                            "handover_s": float("nan"),
                            "changed_files_s": None, "ghost_phase_s": 3.0}, 600.0)
    assert not [k for k, v in g.items()
                if k != "unattributed_s" and (v != v or v < 0)]
    assert g["unattributed_s"] == 600.0


def test_gate_phase_timings_ghost_key_not_in_sum():
    # C3：未知键不进 Σ（residual 按 600−100 口径）
    g = gate_phase_timings({"suite_s": 100.0, "ghost_phase_s": 999.0}, 600.0)
    assert abs(g["unattributed_s"] - 500.0) < 0.05


def test_gate_phase_timings_negative_residual_kept_as_signal():
    # Σ相位 > 段墙钟（亚秒抖动）：如实给负值，不 clamp 不藏
    g = gate_phase_timings(dict(FULL, suite_s=700.0), 600.0)
    assert g["unattributed_s"] < 0


def test_gate_phase_timings_string_numbers_and_reserved_key():
    # 数值串按数值计（JSON 往返形态）；输入侧 unattributed_s 保留字忽略
    g = gate_phase_timings({"pre_check_s": "1.5", "unattributed_s": 999.0}, "100")
    assert g["pre_check_s"] == 1.5
    assert g["unattributed_s"] == 98.5
    assert gate_phase_timings(None, None)["unattributed_s"] == 0.0


# ---------- B 回执 additive 兼容 ----------

def test_receipt_dataclass_new_timing_keys_default_zero():
    for inst in (IntegrationRunResult(), ConflictPrepResult(),
                 ReviewGateResult(), ChangedFilesResult()):
        assert getattr(inst, "wall_s", None) == 0.0
    ir = IntegrationRunResult()
    assert ir.subprocess_wall_s == 0.0 and ir.handover_wall_s == 0.0


def test_old_receipt_dict_reconstruction_without_new_keys():
    # 老历史 dict 回退重建点（dev_lane rraw dict 分支同形）：缺新键零改动兼容
    old = {"ran": 3, "passed": 2, "failed": 1, "env_fail": 0,
           "details": [{"name": "x", "cmd": "", "exit": 0, "output_tail": ""}],
           "error": "", "handover_ran": 0, "handover_passed": 0, "handover_failed": 0}
    ir = IntegrationRunResult(
        ran=int(old.get("ran") or 0), passed=int(old.get("passed") or 0),
        failed=int(old.get("failed") or 0), env_fail=int(old.get("env_fail") or 0),
        error=str(old.get("error") or ""))
    assert ir.wall_s == 0.0 and ir.subprocess_wall_s == 0.0
    # 字段全集=旧字段+恰 3 个新 timing 键（无删除无改名）
    names = {f.name for f in dataclasses.fields(IntegrationRunResult)}
    assert {"wall_s", "subprocess_wall_s", "handover_wall_s"} <= names
    assert {"ran", "passed", "failed", "env_fail", "details", "error"} <= names


# ---------- C 活动级 ----------

def _legs_sleep(n, secs=0.6):
    return [{"name": "leg%d" % i, "cmd": "sleep %s" % secs} for i in range(n)]


def test_handover_legs_parallel_faster_than_serial(tmp_path):
    legs = _legs_sleep(3)
    t0 = time.monotonic()
    par = asyncio.run(aa.run_handover_legs(legs, tmp_path))
    par_wall = time.monotonic() - t0
    assert par["ran"] == 3 and par["passed"] == 3 and par["failed"] == 0
    os.environ["SANDBAR_HANDOVER_CONC"] = "1"
    try:
        t0 = time.monotonic()
        ser = asyncio.run(aa.run_handover_legs(legs, tmp_path))
        ser_wall = time.monotonic() - t0
    finally:
        os.environ.pop("SANDBAR_HANDOVER_CONC", None)
    assert ser["ran"] == 3 and ser["passed"] == 3
    # 并发墙钟显著小于串行（3×0.6s 串行 ≈1.8s；并发 ≈0.6s；界取 1.2s 防慢机抖动）
    assert par_wall < 1.2 < ser_wall


def test_handover_legs_result_order_preserved_under_concurrency(tmp_path):
    # sleep 递减：先发后完的形态下，details 仍按输入序回填
    legs = [{"name": "slow", "cmd": "sleep 0.5; echo slow"},
            {"name": "fast", "cmd": "echo fast"}]
    out = asyncio.run(aa.run_handover_legs(legs, tmp_path))
    assert [d["name"] for d in out["details"]] == ["handover:slow", "handover:fast"]
    assert out["details"][1]["output_tail"] == "fast"


def test_handover_legs_malformed_legs_named_not_fatal(tmp_path):
    legs = [{"name": "ok", "cmd": "true"},
            "not-a-dict",                       # 非对象=记名不执行
            {"name": "empty", "cmd": "   "},    # 空命令=不执行记败
            {"name": "bad", "cmd": "exit 3"}]   # 非零=败
    out = asyncio.run(aa.run_handover_legs(legs, tmp_path))
    assert out["ran"] == 4 and out["passed"] == 1 and out["failed"] == 3
    assert out["details"][1]["name"] == "handover:<畸形分支>"
    assert out["details"][2]["exit"] == -1
    assert out["details"][3]["exit"] == 3


def test_handover_conc_env_matrix(monkeypatch):
    for env, want in [(None, 4), ("", 4), ("garbage", 4), ("1", 1),
                      ("0", 4), ("-5", 4), ("8", 8)]:
        if env is None:
            monkeypatch.delenv("SANDBAR_HANDOVER_CONC", raising=False)
        else:
            monkeypatch.setenv("SANDBAR_HANDOVER_CONC", env)
        assert aa._handover_conc() == want, env


def test_review_gate_and_changed_files_report_wall_s(tmp_path):
    missing = tmp_path / "no-such-worktree"
    res = asyncio.run(aa.verify_review_gate(
        ReviewGateArgs(ticket_id="t260925-12", worktree=str(missing))))
    assert res.git_error and res.passed is False
    assert isinstance(res.wall_s, float) and res.wall_s >= 0.0
    cf = asyncio.run(aa.changed_files(
        ChangedFilesArgs(ticket_id="t260925-12",
                         worktree=str(tmp_path), branch="")))
    assert cf.error and cf.files == []          # fail-closed 恒全跑口径未动
    assert isinstance(cf.wall_s, float) and cf.wall_s >= 0.0


# ---------- D 结构锚（源文本，防接线漂移） ----------

def test_dev_lane_wiring_source_anchors():
    src = (POC / "dev_lane.py").read_text(encoding="utf-8")
    assert "shared.gate_phase_timings(" in src          # 拼装单写者=dev_lane 段尾
    assert '"suite_s"' in src and '"handover_s"' in src  # 契约相位键名（场景 B1 同形）
    assert '"__gate_timings__"' in src                  # 票面 details 行
    assert "unattributed" in src                        # 归账口径点名
    assert 'self.meta["gate_phase_timings"]' in src     # stage record 键
    assert src.count("gate_t0 = self._now_epoch()") == 1  # 段入口单锚


def test_run_scenarios_prelude_observation_line():
    src = (REPO / "integration" / "run_scenarios.py").read_text(encoding="utf-8")
    assert "执行器前奏" in src and "_prelude_s" in src
    # INTEG_SUMMARY 汇总行键集不被本票扩（下游解析契约）
    assert 'prelude_s' not in src.split('INTEG_SUMMARY')[1].split(']')[0]


def test_verify_yaml_integration_cmd_untouched():
    # 红线：本票不触碰泳道声明（integration.cmd / supply / exclude_pools 逐字）
    y = (REPO / "verify.yaml").read_text(encoding="utf-8")
    assert "cmd: python3 integration/run_scenarios.py" in y
