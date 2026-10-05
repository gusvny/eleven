"""t260917-01 单测：仲裁段 settle 闸拒 ≠「缺 verdict= 标记」——计数解耦与主因/出路真实化。

覆盖口径（=create_plan gen1 方案【改动1/2/3】+ review_plan gen4 附条件 C1/C2 + 意见 C3/C4）：
  A. shared.arbitrate_settle_refusal 纯函数矩阵（结构化权威/文本兜底/quoted 键围栏/
     畸形输入必测——岗位说明书纪律）。
  B. shared.arbitrate_blocked_reason 票面文案（主因=闸拒、双因从句、真实出路、单行、
     畸形不抛）。
  C. dev_lane._arbitrate_refusal_blocked 守门点行为断言（_mk_wf 壳族先例，免 Temporal）：
     验收①闸拒+结论形状合规 → True + blocked 主因=闸拒；验收②无闸拒+缺 verdict →
     False（照旧走既有格式计数路径，既有语义零回归）。
  D. 源码锁（KI-046 R3「测试在场≠接线生效」族）：两个计数点各自被守门调用先于计数、
     计数恰 2 处、复位恰在 run_integration_tests 入口簇（C4：计数语义=段内连续）。
  E. agent_activities._apply_settle_note 回执面四模式（C1 取舍清单的机械回归锚）。

C1【附条件｜照搬取舍清单】——改动 3 触碰 t260915-01 定稿函数 _apply_settle_note
（~15 个 blocked 调用点的共用回执面），逐项声明改动不带坏 + 验证方式：
  ① 普通 note 进 evidence：E1 断言 evidence 追加「[worker settle] 」行、status/summary/
    gate_refusal 原样（改判分支整体不触发）；
  ② 闸拒改判 failed + summary 替换：E2 断言 status="failed"、summary==拒绝回执原文
    （替换语义逐字保留）；
  ③ 结构化 refusal 挂载 res.gate_refusal：E3 断言 dict 原样挂载（t260915-01 语义）；
  ④ refusal=None 直调场景逐字不变：E2/E3 对照子用例 + 既有 tests/test_t260915_01_detail_face.py
    全量回归（其 :195 test_apply_settle_note_mounts_refusal_and_negative_leg 不改一字仍绿）。
  改动 3 的唯一增量=改写前把原 summary 存证进 evidence（新行「[settle 拒绝前 summary] 」，
  E2 断言）——只增不改，四条既有模式零触碰。

C2【意见｜UT 显式化】→ A5/C5：summary 含合法 verdict= 且文本恰含 path_gate_reason= 键
→ 纯函数回 None、守门点返回 False、按 verdict 正常路由（文本兜底残余误判面的行为围栏）。

UT 全程禁网络/真 Temporal/真 git（conftest 只加 sys.path）。
运行：主树 venv `.../engine/.venv/bin/python -m pytest server/engine/tests/test_t260917_01_arb_gate_refusal.py -q`。
"""
from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities  # noqa: E402
import dev_lane  # noqa: E402
import path_gates  # noqa: E402
import shared  # noqa: E402
from shared import StageResult  # noqa: E402

NOW_DT = datetime.datetime(2026, 9, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)

PROBE = "integration/baselines/ticket-lifecycle-scenes.mjs"  # t260916-21 实证越界文件形态
REFUSAL_NOTE = path_gates.gate_refusal_note("arbitrate", [PROBE], "unauthorized_path")
REFUSAL_DETAIL = path_gates.gate_red_detail("arbitrate", [PROBE], "unauthorized_path",
                                            REFUSAL_NOTE)


# ---------- 壳（test_t260915_01 _mk_wf 族同款） ----------

async def _wake_immediately(cond) -> None:
    return None


def _mk_wf(detail_face: bool = True, meta: dict | None = None):
    """免 Temporal 运行时的 DevLaneWorkflow 壳：_blocked 所需面全桩。"""
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: NOW_DT,
        logger=SimpleNamespace(info=lambda *a, **k: None,
                               warning=lambda *a, **k: None,
                               warn=lambda *a, **k: None),
        wait_condition=_wake_immediately)
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {})
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = "t-ut"
    wf._detail_face_on = detail_face
    wf.engine_version = 2
    return wf


def _blocked_entries(wf) -> list:
    return [e for e in wf.timeline if e.get("state") == "blocked"]


# ---------- A. arbitrate_settle_refusal ----------

def test_a1_structured_refusal_is_authoritative():
    out = shared.arbitrate_settle_refusal(REFUSAL_NOTE, dict(REFUSAL_DETAIL))
    assert out is not None
    assert out["reason_code"] == "unauthorized_path"
    assert out["note"] == REFUSAL_NOTE
    assert PROBE in "、".join(out["files"])
    assert out["next_action"] == path_gates.next_action_hint("unauthorized_path")


def test_a2_structured_with_empty_summary_falls_back_to_detail_evidence():
    out = shared.arbitrate_settle_refusal("", dict(REFUSAL_DETAIL))
    assert out is not None and out["note"] == REFUSAL_DETAIL["evidence"]


def test_a3_text_only_old_receipt_still_detectable():
    out = shared.arbitrate_settle_refusal(REFUSAL_NOTE, None)
    assert out is not None
    assert out["reason_code"] == "unauthorized_path"
    assert out["note"] == REFUSAL_NOTE
    assert out["next_action"] == path_gates.next_action_hint("unauthorized_path")
    assert out["files"] == []  # 老回执无结构化面：不猜文件清单


def test_a4_status_failed_reason_code_extracted():
    note = path_gates.gate_refusal_note("arbitrate", [], "status_failed")
    out = shared.arbitrate_settle_refusal(note, None)
    assert out is not None and out["reason_code"] == "status_failed"


def test_a5_quoted_key_does_not_hijack_valid_verdict_c2():
    # C2 围栏：结论可解析 + 文本引用机读键 → 不判闸拒（按 verdict 正常路由）
    s = "verdict=code-fault 上一轮 settle 曾回 path_gate_reason=unauthorized_path，本判产品问题"
    assert shared.arbitrate_settle_refusal(s, None) is None


def test_a6_no_refusal_returns_none_both_shapes():
    assert shared.arbitrate_settle_refusal("普通总结没有标记", None) is None
    assert shared.arbitrate_settle_refusal("verdict=pass 全部通过", None) is None


def test_a7_malformed_inputs_fail_visible_never_raise():
    # summary 畸形
    assert shared.arbitrate_settle_refusal(None, None) is None
    assert shared.arbitrate_settle_refusal(123, None) is None
    # gate_refusal 畸形：不可救 → 落文本兜底（回执原文在场仍可辨）/None
    for junk in ("junk", [], 42, {}, {"reason_code": ""}, {"reason_code": 123}):
        out = shared.arbitrate_settle_refusal(REFUSAL_NOTE, junk)
        assert out is not None and out["reason_code"] == "unauthorized_path"
        assert shared.arbitrate_settle_refusal("", junk) is None


# ---------- B. arbitrate_blocked_reason ----------

def test_b1_face_text_main_cause_dual_clause_real_exit_single_line():
    text = shared.arbitrate_blocked_reason(
        {"reason_code": "unauthorized_path", "note": REFUSAL_NOTE,
         "next_action": path_gates.next_action_hint("unauthorized_path"), "files": [PROBE]})
    assert "\n" not in text
    assert "blocked by the path gate (main cause)" in text
    assert REFUSAL_NOTE in text                      # 回执原文（含点名与合法出路）逐字在
    assert "next step: " in text
    assert "the arbitration verdict failed to land" in text and "not counted as a missing verdict= format round" in text  # dual clause
    assert "revert the out-of-bounds changes" in text and "file a ticket on the main side" in text and "retry_qc" in text
    assert "no verdict= marker needed" in text              # the way out never points at adding a marker


def test_b2_verdict_missing_false_drops_dual_clause():
    text = shared.arbitrate_blocked_reason(
        {"reason_code": "unauthorized_path", "note": REFUSAL_NOTE}, verdict_missing=False)
    assert "仲裁结论未能落盘" not in text
    assert "blocked by the path gate (main cause)" in text


def test_b3_malformed_refusal_still_readable_never_raises():
    text = shared.arbitrate_blocked_reason({})
    assert "gate_refusal_unknown" in text
    assert "next step: " in text
    assert shared.arbitrate_blocked_reason(None)  # 不抛且非空


# ---------- C. 守门点行为断言（验收①②） ----------

def test_c1_gate_refusal_well_formed_conclusion_blocked_with_gate_main_cause():
    """验收①：闸拒 + 结论形状合规（改写前 verdict 在场、随存证 evidence 保留）→
    守门 True + blocked 主因=闸拒（「缺 verdict」只是双因从句）。"""
    for detail_face in (True, False):
        wf = _mk_wf(detail_face)
        res = StageResult(
            status="failed", summary=REFUSAL_NOTE, gate_refusal=dict(REFUSAL_DETAIL),
            # 改动3 存证形态：被替换的结论原文留在 evidence
            evidence="[settle 拒绝前 summary] verdict=tests-fault 红项属共享电池")
        blocked = asyncio.run(wf._arbitrate_refusal_blocked(res))
        assert blocked is True
        entries = _blocked_entries(wf)
        assert len(entries) == 1 and entries[0]["stage"] == "arbitrate"
        why = entries[0]["reason"]
        assert "blocked by the path gate (main cause)" in why and REFUSAL_NOTE in why
        assert "no verdict= marker needed" in why
        if detail_face:
            assert wf.meta.get("blocked_reason") == ""   # 门开：唤醒即清（t260915-01 ①）
        else:
            assert wf.meta.get("blocked_reason") == why  # 门关：入口写点照旧


def test_c1b_text_only_old_receipt_also_guarded():
    wf = _mk_wf(False)
    res = StageResult(status="failed", summary=REFUSAL_NOTE)  # 老回执：无结构化键
    assert asyncio.run(wf._arbitrate_refusal_blocked(res)) is True
    assert len(_blocked_entries(wf)) == 1


def test_c2_no_refusal_missing_verdict_still_counts_format_path():
    """验收②：无闸拒 + 缺 verdict → 守门 False（照旧走既有格式计数路径，计数器
    增量语义零改动——既有 blocked 文案/纠正轮/上限全部原样）。"""
    wf = _mk_wf(True)
    res = StageResult(status="ok", summary="stub 段完成（无 verdict 标记）")
    assert asyncio.run(wf._arbitrate_refusal_blocked(res)) is False
    assert _blocked_entries(wf) == []
    assert wf.meta.get("blocked_reason") in (None, "")


def test_c3_verdict_ok_never_guarded_even_with_quoted_key_c2():
    wf = _mk_wf(True)
    res = StageResult(status="ok",
                      summary="verdict=pass 引用上文 path_gate_reason=unauthorized_path")
    assert asyncio.run(wf._arbitrate_refusal_blocked(res)) is False
    assert _blocked_entries(wf) == []


def test_c4_duck_typed_receipt_without_gate_refusal_is_safe():
    wf = _mk_wf(True)
    res = SimpleNamespace(status="ok", summary="verdict=pass")  # 无 gate_refusal 属性
    assert asyncio.run(wf._arbitrate_refusal_blocked(res)) is False


# ---------- D. 源码锁（KI-046 R3） ----------

def _src() -> str:
    return (POC / "dev_lane.py").read_text(encoding="utf-8")


def test_d1_exactly_two_counting_sites_each_guarded_before_counting():
    src = _src()
    assert src.count("arb_format_rounds += 1") == 2, "格式计数点恰两处（串行/并行叉）"
    assert src.count("await self._arbitrate_refusal_blocked(") == 2, \
        "守门调用恰两处（串行 res / 纠正用例 rraw）"
    g1 = src.find("await self._arbitrate_refusal_blocked(res)")
    c1 = src.find("arb_format_rounds += 1")
    assert 0 < g1 < c1, "串行分支：守门必须先于计数（闸拒不计入的结构保证）"
    g2 = src.find("await self._arbitrate_refusal_blocked(rraw)")
    assert g2 > c1, "纠正用例守门在串行计数点之后（源序）"
    m2 = src.find("arb_res = rraw", g2)
    assert 0 < g2 < m2, "纠正用例：守门先于纠正结果记忆（闸拒不进 arb_res）"


def test_d2_reset_lives_in_run_integration_tests_entry_cluster_c4():
    src = _src()
    assert src.count("arb_format_rounds = 0") == 2, "初始化 + 段入口复位恰两处"
    i_section = src.find('if phase == "run_integration_tests":')
    i_reset = src.find("arb_format_rounds = 0", i_section)
    i_precheck = src.find("# Pre-check", i_section)
    assert 0 < i_section < i_reset < i_precheck, "复位必须落在段入口状态簇内（t260903-02 同簇）"


def test_d3_prompt_invite_replaced_in_both_places_and_agnostic():
    """改动4（修向④）：两处「直接迭代 integration/ 测试集」的无面邀请文案收窄；
    且 dev_lane 项目无关不变量（integration/t260902-12 守卫同口径：零 baselines
    字样——仲裁 gen1 code-fault 伴随项修复的 UT 锁）。"""
    src = _src()
    assert "tests-fault 时直接迭代它" not in src
    assert "你直接迭代 integration/ 里的" not in src
    assert "共享电池、场景库等仓库级受保护资产" in src    # 收窄文案（不点名仓库专属路径）
    assert "只迭代本段允许面内的测试资产" in src                 # arb_ctx 收窄文案（同向）
    import re as _re
    assert not _re.search(r"notes/|known-issues|baselines|\.worktrees/", src), \
        "dev_lane 项目专属路径零命中（test_project_agnostic ① 同口径）"


# ---------- F. 单文件加载面守卫（仲裁 gen1 主因修复的回归锚） ----------

def test_f1_shared_importable_as_single_file_without_engine_on_syspath():
    """shared.py 被 importlib 单文件加载（ticket.py _poc_shared 同款：无 engine
    sys.path）时必须可 exec——仓库兄弟模块只能延迟 import（gen0 顶层 import
    path_gates 曾连累 14 条场景：ModuleNotFoundError）。"""
    import subprocess
    code = (
        "import importlib.util, sys, os\n"
        f"shared_path = {str(POC / 'shared.py')!r}\n"
        f"banned = {str(POC)!r}\n"
        "sys.path = [p for p in sys.path if not (p and os.path.abspath(p) == banned)]\n"
        "assert not any(os.path.abspath(p or os.getcwd()) == banned for p in sys.path)\n"
        "spec = importlib.util.spec_from_file_location('_poc_shared', shared_path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['_poc_shared'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "assert callable(mod.arbitrate_settle_refusal) and callable(mod.arbitrate_blocked_reason)\n"
        "print('single-file-ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=120, cwd=str(POC.parent))  # cwd=server/：'' 不指 engine
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert "single-file-ok" in proc.stdout


def test_f2_lazy_call_site_still_resolves_in_engine_context():
    """正常引擎上下文（engine 目录在 sys.path，pytest 同款）里两个纯函数调用面
    不受延迟 import 影响——path_gates 解析成功、判定语义不变。"""
    import path_gates  # noqa: F401  # 证明本进程可解析
    out = shared.arbitrate_settle_refusal(
        path_gates.gate_refusal_note("arbitrate", ["x.txt"], "unauthorized_path"), None)
    assert out is not None and out["reason_code"] == "unauthorized_path"


# ---------- E. _apply_settle_note 四模式（C1 机械回归锚） ----------

def _res(**kw) -> StageResult:
    base = dict(status="ok", summary="原结论 verdict=tests-fault", report="",
                deliverables=[], files_changed=[], evidence="原始证据")
    base.update(kw)
    return StageResult(**base)


def test_e1_normal_note_appends_evidence_only():
    res = _res()
    out = agent_activities._apply_settle_note(res, "worker 代落盘 commit abc")
    assert out.status == "ok" and out.summary == "原结论 verdict=tests-fault"
    assert "[worker settle] worker 代落盘 commit abc" in out.evidence
    assert out.gate_refusal is None


def test_e2_gate_refusal_replaces_summary_and_preserves_original_in_evidence():
    res = _res()
    out = agent_activities._apply_settle_note(res, REFUSAL_NOTE)
    assert out.status == "failed" and out.summary == REFUSAL_NOTE      # ② 改判+替换逐字保留
    assert "[settle 拒绝前 summary] 原结论 verdict=tests-fault" in out.evidence  # 改动3 增量
    assert "[worker settle] " in out.evidence                          # ① 普通 note 行为不变
    assert out.gate_refusal is None                                    # ④ refusal=None 不挂


def test_e3_structured_refusal_mounted_unchanged():
    res = _res()
    out = agent_activities._apply_settle_note(res, REFUSAL_NOTE, refusal=dict(REFUSAL_DETAIL))
    assert out.gate_refusal == dict(REFUSAL_DETAIL)                    # ③ 挂载语义原样
    assert out.summary == REFUSAL_NOTE and out.status == "failed"


def test_e4_empty_note_returns_res_untouched():
    res = _res(evidence="E")
    out = agent_activities._apply_settle_note(res, "")
    assert out.evidence == "E" and out.status == "ok"
