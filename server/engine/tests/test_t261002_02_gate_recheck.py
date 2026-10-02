"""归属前复验单测（t261002-02，KI-182 落成机制）。

覆盖面：
  A. 纯函数层（failure_protocol）：reprobe_receipt_all_green 五条判据逐一有牙 +
     畸形回执 fail-closed；apply_reprobe_recheck 只碰「本票的账」家族（regression
     族 block）、pass/record/unknown/violation/非该族 block 全部逐字节不动；
     全绿降级 unattributable、未证全绿/探针缺席维持 block 且 why 带复验证据；
     unattributable_face_sentence 的票面句子（英文、降级档空=零扰动）。
  B. 轻道闸面（light_lane）：blocked 文案把降级名从「本票的账」里摘出去并带上
     unattributable 句子；全降级时明写「没有红是本票的账」但**仍 blocked**（降级
     不造绿）；结构化明细带 recheck 块（additive、可 JSON 序列化、探针缺席=
     available=False 如实记）；票面行数/字数上限不破。
  C. 判定纪律锁：探针全绿**不改变**轮的绿红判词（_light_gate_verdict 只读回执
     本体——降级永不放行，堵「靠重跑碰绿」的路径）。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：仓库根 `server/engine/.venv/bin/python -m pytest server/engine/tests/test_t261002_02_gate_recheck.py -q`。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import failure_protocol as fp  # noqa: E402
import light_lane  # noqa: E402
import shared  # noqa: E402

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _receipt(**kw):
    """探针回执（dict 形状，与活动回执同键族）：默认全绿。"""
    base = dict(error="", ran=2, passed=2, failed=0, env_fail=0, missing=[])
    base.update(kw)
    return base


# ======================================================================
# A. 纯函数层
# ======================================================================

def test_all_green_requires_all_five_conditions():
    r = _receipt()
    assert fp.reprobe_receipt_all_green(r) is True
    assert fp.reprobe_receipt_all_green(_receipt(error="boom")) is False
    assert fp.reprobe_receipt_all_green(_receipt(ran=0)) is False      # 没真跑≠全绿
    assert fp.reprobe_receipt_all_green(_receipt(failed=1)) is False
    assert fp.reprobe_receipt_all_green(_receipt(env_fail=1)) is False
    assert fp.reprobe_receipt_all_green(_receipt(missing=["sc_x"])) is False


@pytest.mark.parametrize("bad", [None, "", "x", 5, True, [], {"ran": "2"},
                                 {"ran": 2}, {"ran": 2, "failed": 0,
                                              "env_fail": 0, "error": "",
                                              "missing": "sc_x"}])
def test_all_green_is_fail_closed_on_malformed_receipts(bad):
    """畸形回执（缺键/错型/非容器）一律 False——未证全绿就不降级（fail-closed）。"""
    assert fp.reprobe_receipt_all_green(bad) is False


def test_all_green_accepts_dataclass_shape():
    r = shared.ReprobeRedResult(ran=3, passed=3)
    assert fp.reprobe_receipt_all_green(r) is True
    assert fp.reprobe_receipt_all_green(shared.ReprobeRedResult(error="timeout")) is False


def _reg(name):
    return {"name": name, "verdict": "block", "why": "regression(main绿或基线不可比，保守拦)"}


def test_recheck_downgrades_only_the_regression_block_family():
    verdicts = [
        {"name": "sc_green", "verdict": "pass", "why": "green"},
        {"name": "sc_known", "verdict": "record", "why": "baseline_red(既有欠账)"},
        {"name": "sc_unk", "verdict": "unknown", "why": "cause_unknown"},
        {"name": "sc_viol", "verdict": "block",
         "why": "protocol_violation(connect_refused)", "violation": True},
        {"name": "sc_other", "verdict": "block", "why": "not_blocked_family"},
        _reg("sc_mine_a"),
        _reg("sc_mine_b"),
    ]
    out = fp.apply_reprobe_recheck(verdicts, _receipt())
    by = {v["name"]: v for v in out["verdicts"]}
    # 只有 regression 族 block 被碰
    assert by["sc_green"] == verdicts[0] and by["sc_known"] == verdicts[1]
    assert by["sc_unk"] == verdicts[2] and by["sc_viol"] == verdicts[3]
    assert by["sc_other"] == verdicts[4]
    # 全绿 ⇒ 降级 unattributable，带回执面
    for n in ("sc_mine_a", "sc_mine_b"):
        assert by[n]["verdict"] == fp.VERDICT_UNATTRIBUTABLE
        assert by[n]["why"].startswith("reprobe_green(")
        assert by[n]["recheck"]["ran"] == 2
    assert out["unattributable"] == ["sc_mine_a", "sc_mine_b"]
    assert out["rechecked"] == ["sc_mine_a", "sc_mine_b"]
    assert out["ticket_account"] == []
    assert out["recheck"]["all_green"] is True


def test_recheck_keeps_block_when_reprobe_still_red():
    out = fp.apply_reprobe_recheck([_reg("sc_mine")],
                                   _receipt(failed=1, error=""))
    v = out["verdicts"][0]
    assert v["verdict"] == "block"
    assert "reprobe_not_green(" in v["why"]      # 证据随行，人审可读
    assert out["unattributable"] == [] and out["ticket_account"] == ["sc_mine"]


def test_recheck_keeps_block_when_reprobe_absent_or_malformed():
    """探针没跑 / 回执畸形 ⇒ 原判定保留（拦不松、账不丢），fail-closed。"""
    base = _reg("sc_mine")
    for probe in (None, _receipt(ran=0), "garbage", {"ran": "x"}):
        out = fp.apply_reprobe_recheck([base], probe)
        assert out["verdicts"][0]["verdict"] == "block"
        assert out["unattributable"] == []
    out = fp.apply_reprobe_recheck([base], None)
    assert out["recheck"]["available"] is False
    assert "reprobe_not_green" in out["verdicts"][0]["why"]


def test_recheck_with_no_regression_blocks_changes_nothing():
    verdicts = [{"name": "a", "verdict": "pass", "why": "green"}]
    out = fp.apply_reprobe_recheck(verdicts, _receipt())
    assert out["verdicts"] == verdicts
    assert out["unattributable"] == [] and out["rechecked"] == []


def test_face_sentence_rules():
    sent = fp.unattributable_face_sentence(["a", "b"], ["c"])
    assert "2 red(s)" in sent and "unattributable" in sent
    assert "NOT booked as this ticket's account" in sent
    assert "still this ticket's account" in sent
    assert "still red" in sent and "a human decides" in sent   # 降级≠放行，说在票面
    assert not _CJK.search(sent), "票面句子必须是英文"
    assert fp.unattributable_face_sentence([], ["c"]) == ""    # 零降级=零扰动
    assert fp.unattributable_face_sentence(None, None) == ""


# ======================================================================
# B. 轻道闸面
# ======================================================================

async def _wake_immediately(cond) -> None:
    return None


@pytest.fixture
def _workflow_shell():
    saved = (light_lane.workflow,)
    shell = SimpleNamespace(
        patched=lambda pid: pid == light_lane.LIGHT_GATE_RECHECK_PATCH_ID,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None))
    light_lane.workflow = shell
    yield shell
    light_lane.workflow = saved


def _mk_wf():
    wf = object.__new__(light_lane.LightLaneWorkflow)
    wf.meta = {"worktree": "/tmp/wt", "gate_recheck": None}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t-ut-recheck"
    wf._detail_face_on = True
    wf.refused = []
    wf.engine_version = 2
    return wf


def _ir_red(names, **kw):
    det = [{"name": n, "cmd": "", "exit": 1, "output_tail": ""} for n in names]
    kw.setdefault("ran", len(names))
    kw.setdefault("passed", 0)
    kw.setdefault("failed", len(names))
    base = dict(details=det, error="", blockers=list(names))
    base.update(kw)
    return shared.IntegrationRunResult(**base)


def _recheck(green_names, kept_names):
    return fp.apply_reprobe_recheck(
        [_reg(n) for n in list(green_names) + list(kept_names)],
        _receipt() if not kept_names else _receipt(failed=len(kept_names)))


def test_blocked_text_keeps_account_when_reprobe_batch_is_not_all_green(_workflow_shell):
    """批量复验语义：探针一轮跑全部拦名单——**有一条红 ⇒ 整批不降级**（保守：
    不许拿「部分绿」洗账）。票面回到既有形态（Fix 面全名、无 unattributable 句）。"""
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta", "sc_gamma"]
    ir = _ir_red(names)
    rc = _recheck(green_names=[], kept_names=names)
    text = wf._light_gate_blocked_text(ir, [], "gate round 1", recheck=rc)
    assert "Fix (this ticket's account): sc_alpha, sc_beta, sc_gamma" in text
    assert "unattributable" not in text
    assert len(text.splitlines()) <= light_lane.LightLaneWorkflow.FACE_MAX_LINES
    assert len(text) <= light_lane.LightLaneWorkflow.FACE_MAX_CHARS


def test_blocked_text_when_everything_is_unattributable(_workflow_shell):
    """全降级：账面明写「没有红是本票的账」，但轮仍红仍转人（不造绿、不自动放行）。"""
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta"]
    ir = _ir_red(names)
    rc = _recheck(green_names=names, kept_names=[])
    text = wf._light_gate_blocked_text(ir, [], "gate round 2", recheck=rc)
    assert "none of the reds are this ticket's account" in text
    assert "2 red(s) re-ran standalone in this lane and passed" in text
    assert "a human decides" in text
    assert "retry_qc" in text and "rework(to_stage=implement)" in text


def test_blocked_text_without_recheck_is_byte_identical_legacy(_workflow_shell):
    """recheck=None（门关/老回放）⇒ 票面与改前逐字节同（零扰动锁）。"""
    wf = _mk_wf()
    ir = _ir_red(["sc_alpha", "sc_beta"])
    legacy = wf._light_gate_blocked_text(ir, [], "gate round 1")
    explicit = wf._light_gate_blocked_text(ir, [], "gate round 1", recheck=None)
    assert legacy == explicit
    assert "unattributable" not in legacy


def test_blocked_text_excludes_unattributable_from_the_account(_workflow_shell):
    """全绿复验：降级名从 Fix 面摘出（三选二降级 ⇒ 只剩一条可行动…即批量全绿才降级，
    此处三拦全降级 ⇒ Fix 面消失、明写 none + unattributable 句）。"""
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta", "sc_gamma"]
    ir = _ir_red(names)
    rc = _recheck(green_names=names, kept_names=[])
    text = wf._light_gate_blocked_text(ir, [], "gate round 1", recheck=rc)
    assert "Fix (this ticket's account):" not in text
    assert "3 red(s) re-ran standalone in this lane and passed" in text
    assert "unattributable (bench-family), NOT booked as this ticket's account" in text
    assert "the round is still red" in text                    # 降级≠放行
    assert not _CJK.search(text)
    assert len(text.splitlines()) <= light_lane.LightLaneWorkflow.FACE_MAX_LINES
    assert len(text) <= light_lane.LightLaneWorkflow.FACE_MAX_CHARS


def test_blocked_detail_carries_the_recheck_block(_workflow_shell):
    wf = _mk_wf()
    names = ["sc_alpha", "sc_beta"]
    ir = _ir_red(names)
    rc = _recheck(green_names=names, kept_names=[])
    d = wf._light_gate_blocked_detail(ir, [], "light_gate_red", "gate round 1",
                                      recheck=rc)
    rcb = d["recheck"]
    assert rcb["available"] is True and rcb["all_green"] is True
    assert rcb["unattributable"] == names and rcb["ticket_account"] == []
    assert rcb["ran"] == 2 and rcb["error"] == ""
    vv = {v["name"]: v["verdict"] for v in rcb["verdicts"]}
    assert vv == {n: "unattributable" for n in names}
    json.dumps(d, ensure_ascii=False)   # 票面/控制台机读契约：可序列化


def test_blocked_detail_reprobe_red_records_not_green(_workflow_shell):
    """复验有红：available=True、all_green=False、零降级——拦名单如实留在账上。"""
    wf = _mk_wf()
    rc = _recheck(green_names=[], kept_names=["sc_x"])
    d = wf._light_gate_blocked_detail(_ir_red(["sc_x"]), [], "light_gate_red", "r1",
                                      recheck=rc)
    assert d["recheck"]["available"] is True
    assert d["recheck"]["all_green"] is False
    assert d["recheck"]["unattributable"] == []
    assert d["recheck"]["ticket_account"] == ["sc_x"]
    json.dumps(d, ensure_ascii=False)


def test_blocked_detail_without_recheck_records_availability_false(_workflow_shell):
    """探针没跑（门关/老回放）⇒ recheck.available=False 如实记，绝不冒充跑过。"""
    wf = _mk_wf()
    d = wf._light_gate_blocked_detail(_ir_red(["sc_x"]), [], "light_gate_red", "r1")
    assert d["recheck"]["available"] is False
    assert d["recheck"]["unattributable"] == []
    json.dumps(d, ensure_ascii=False)


def test_verdict_reader_ignores_the_downgrade(_workflow_shell):
    """C：判定纪律锁——降级只进账本面，`_light_gate_verdict` 只读回执本体；
    回执红的轮在降级后**仍判红**（降级永不放行）。"""
    wf = _mk_wf()
    ir = _ir_red(["sc_alpha"], blockers=["sc_alpha"])
    assert wf._light_gate_verdict(ir) == "red"
    rc = _recheck(green_names=["sc_alpha"], kept_names=[])
    # 探针全绿也改不了回执本体 ⇒ 判词不动
    assert wf._light_gate_verdict(ir) == "red"
    assert rc["unattributable"] == ["sc_alpha"]
