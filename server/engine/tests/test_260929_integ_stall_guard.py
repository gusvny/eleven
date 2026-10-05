"""260929 单测（宿主令直修）：集成轮**测量面零变化 ⇒ 不重跑全套**（判停转人审）。

起因（t260929-22 实案，宿主问「为什么又跑这么多遍」）：裁判连续四轮 `verdict=tests-fault`，
判词逐字加重「本票面绿、余红待宿主裁、**转人工判读**」，代码自 implement gen4 起一字未动——
但每一轮仍被路由回 `run_integration_tests` 重跑整套 353 场景（~30 分钟/趟）。根因：
`shared.integration_route` 判 tests-fault **只看连续轮数 ≤ 5**，不看这一轮测到的东西与上一轮
是否逐字相同。修法（本单测锁三层）：

  ①判据（纯函数 `shared.gate_round_signature`）：闸拦名单 / 具名环境红 / 四计数 / 归属置信 /
    基线 ref / 逐条失败明细（name×exit）——**逐项相同才同签名**；任一项变即变；畸形/缺字段
    ⇒ 空串（**判不准不判停**，fail-safe，绝不因读不出而误停）。
  ②状态机（`DevLaneWorkflow._integ_round_stall`）：首轮记签名、次轮起同签名判停并累计轮数；
    判停文案必须点名「连续 N 轮零变化 + 转人审 + retry_qc 可复活」（报错必须精确）。
  ③接线：两个分支（串行 / arbitrate∥acceptance 平行叉）各一处，且都在
    `workflow.patched(INTEG_STALL_PATCH_ID)` 门内（老在途票 history 无此标记 → patched()=False
    → 旧路径逐字不变，重放零新命令），判停后果=**转人审**（`_blocked_over_limit`），不是重跑。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_integ_stall_guard.py -q
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane  # noqa: E402
import shared  # noqa: E402


class _Receipt:
    """闸回执形状（只带 sign 判据用到的字段；与 agents_activities 上送面同键）。"""

    def __init__(self, **kw):
        self.blockers = kw.get("blockers", ["b1", "b2"])
        self.env_red = kw.get("env_red", ["e1"])
        self.ran = kw.get("ran", 353)
        self.passed = kw.get("passed", 323)
        self.failed = kw.get("failed", 19)
        self.env_fail = kw.get("env_fail", 11)
        self.details = kw.get("details", [{"name": "x", "exit": 1}])
        self.affiliation_confidence = kw.get("affiliation_confidence", "ok")
        self.baseline_ref = kw.get("baseline_ref", "main@f67852d")


class _Stub:
    def __init__(self):
        self.meta = {}

    def stall(self, receipt):
        return dev_lane.DevLaneWorkflow._integ_round_stall(self, receipt)


# ---------------- ①判据 ----------------

def test_identical_receipts_share_a_signature():
    assert shared.gate_round_signature(_Receipt()) == shared.gate_round_signature(_Receipt())
    # 名单顺序无关（同一批红的书写顺序不该算变化）
    a = shared.gate_round_signature(_Receipt(blockers=["b2", "b1"]))
    b = shared.gate_round_signature(_Receipt(blockers=["b1", "b2"]))
    assert a == b


@pytest.mark.parametrize("kw", [
    {"blockers": ["b1"]},                       # 拦名单变（少一条 = main 修好了它）
    {"blockers": ["b1", "b2", "b3"]},           # 多一条新红
    {"env_red": ["e1", "e2"]},                  # 具名环境红变
    {"ran": 352}, {"passed": 322}, {"failed": 18}, {"env_fail": 10},   # 四计数任一变
    {"affiliation_confidence": "unknown(fingerprint_mismatch)"},       # 归属置信变
    {"baseline_ref": "main@deadbeef"},                                 # 基线 ref 变
    {"details": [{"name": "x", "exit": 2}]},                           # 逐条失败明细变
    {"details": [{"name": "y", "exit": 1}]},
])
def test_any_measured_change_breaks_the_signature(kw):
    assert shared.gate_round_signature(_Receipt()) != shared.gate_round_signature(_Receipt(**kw))


@pytest.mark.parametrize("bad", [None, {}, "boom", 42, _Receipt(blockers=None),
                                 _Receipt(env_red=None), _Receipt(ran="x")])
def test_illegible_receipts_never_sign(bad):
    """判不准**不判停**：老回执/畸形/崩半截 → 空签名 ⇒ 照旧重跑（保守方向永远是多跑）。"""
    assert shared.gate_round_signature(bad) == ""


# ---------------- ②状态机 ----------------

def test_first_round_records_then_identical_round_stalls():
    s = _Stub()
    first = s.stall(_Receipt())
    assert first["stall"] is False and first["rounds"] == 1
    assert s.meta["integ_signature"] and s.meta["integ_signature_rounds"] == 1
    second = s.stall(_Receipt())
    assert second["stall"] is True and second["rounds"] == 2
    third = s.stall(_Receipt())
    assert third["rounds"] == 3, "连续同签名的轮数要累计（判词里要点名「连续 N 轮」）"


def test_stall_note_names_the_state_and_the_human_exit():
    s = _Stub()
    s.stall(_Receipt())
    note = s.stall(_Receipt())["note"]
    assert "2 consecutive rounds" in note and "byte-identical" in note and "human" in note
    assert "retry_qc" in note, "出路必须可执行（人裁后 retry_qc 复活）"


def test_a_changed_measurement_resumes_reruns():
    s = _Stub()
    s.stall(_Receipt())
    assert s.stall(_Receipt())["stall"] is True
    # 闸面变了（例如 main 修好一条 blocker，或多出一条新红）→ 不许判停，重新计轮
    assert s.stall(_Receipt(blockers=["b1"]))["stall"] is False
    assert s.meta["integ_signature_rounds"] == 1


def test_illegible_receipt_is_never_stalled():
    s = _Stub()
    assert s.stall(None)["stall"] is False
    assert s.stall(None)["stall"] is False
    assert "integ_signature" not in s.meta, "读不出就别记账（免得把空签名当「同状态」）"


# ---------------- ③接线 ----------------

def test_stall_guard_is_wired_in_both_branches_behind_its_patch_gate():
    src = Path(dev_lane.__file__).read_text("utf-8")
    assert dev_lane.INTEG_STALL_PATCH_ID == "t260929-integ-stall-guard"
    assert src.count("workflow.patched(INTEG_STALL_PATCH_ID)") == 2, \
        "串行 + 平行叉各一处（漏一处＝那个分支照样白烧全套）"
    assert src.count("self._integ_round_stall(cur_integ)") == 2
    # 判停后果必须是**转人审**（_blocked_over_limit），不是 continue 回 run_integration_tests
    blocks = src.split("workflow.patched(INTEG_STALL_PATCH_ID)")[1:]
    for b in blocks:
        head = b.split("continue", 1)[0]
        assert "_blocked_over_limit(stall" in head, "判停必须落到人审出口（不是静默 continue）"


def test_route_semantics_unchanged_for_the_counted_path():
    """零回归锁：轮数上限的既有语义逐字不动（本修法只**旁路**同状态轮，不改上限判据）。"""
    assert shared.integration_route("tests-fault", 1, 0) == "run_integration_tests"
    assert shared.integration_route("tests-fault", 5, 0) == "run_integration_tests"
    assert shared.integration_route("tests-fault", 6, 0).startswith("blocked:")
    assert shared.integration_route("code-fault", 0, 1) == "implement"
    assert shared.integration_route("pass", 9, 9) == "acceptance"


# ---------------- ④自我证明：两处判停分支确实在门内（AST 祖先链） ----------------

def test_stall_branches_are_inside_their_patch_gate():
    """自证钉（同 test_t260917_09 先例）：两个 `_blocked_over_limit(stall…)` 分支的
    **AST 祖先链**里必须有 `workflow.patched(INTEG_STALL_PATCH_ID)` 的 if——分支即便
    文本上「看着在门内」，挪出门外这条也会先红（源码文本锁不够，用祖先链核实）。"""
    import ast
    src = Path(dev_lane.__file__).read_text("utf-8")
    tree = ast.parse(src)
    hits = []          # (lineno, has_gate_ancestor)

    def gate_call(node) -> bool:
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "patched"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "workflow"
                and node.args and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "INTEG_STALL_PATCH_ID")

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit(self, node):
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                f = node.value.func
                if isinstance(f, ast.Attribute) and f.attr == "_blocked_over_limit":
                    arg = node.value.args[0] if node.value.args else None
                    if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name) \
                            and arg.value.id in ("stall", "stall2"):
                        gated = any(isinstance(n, ast.If) and gate_call(n.test)
                                    for n in self.stack)
                        hits.append((node.lineno, gated))
            self.stack.append(node)
            super().generic_visit(node)
            self.stack.pop()

    V().visit(tree)
    assert len(hits) == 2, "判停分支应有两处（串行 + 并行汇合侧），实得 %d" % len(hits)
    assert all(g for _, g in hits), \
        "判停分支必须落在 workflow.patched(INTEG_STALL_PATCH_ID) 门内（否则老 history 重放会发新命令）：%s" % hits
