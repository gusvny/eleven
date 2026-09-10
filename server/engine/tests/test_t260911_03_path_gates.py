#!/usr/bin/env python3
"""t260911-03 路径闸单测（L1）：阶段路径闸 / 受保护路径闸 / 拒绝回执 / 畸形输入 / 源码锁定。

被测：path_gates（零 IO 纯函数，可被场景与单测直调）+ agent_activities 接线源码锁定
+ shared 数据类老事件缺字段默认值（兼容）。

UT 全程禁网络/真 Temporal/真 git；源码锁定只读源码文本与 ast。
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_gates as pg  # noqa: E402
import shared  # noqa: E402

ENGINE_DIR = Path(__file__).resolve().parent.parent


# ---------------- ① 阶段路径闸：段 × 允许面矩阵 ----------------

def test_plan_review_only_result_files():
    for st in ("create_plan", "review_plan", "acceptance_walkthrough", "merge",
               "suggest_next"):
        ok, vio, reason = pg.judge_stage_paths(st, [".sandbar/stage_x_gen0.json"])
        assert (ok, vio, reason) == (True, [], ""), st
        # 碰产品代码 = 违规（做方案/审方案/走查/合并：零代码改动）
        ok, vio, reason = pg.judge_stage_paths(
            st, ["server/engine/dev_lane.py", ".sandbar/stage_x_gen0.json"])
        assert not ok and vio == ["server/engine/dev_lane.py"], st
        assert reason == "unauthorized_path"


def test_implement_write_set_face():
    ok, vio, reason = pg.judge_stage_paths(
        "implement", ["app/src/a.py", "server/engine/x.py"],
        write_set=["app/src", "server/engine/"])
    assert (ok, vio, reason) == (True, [], "")
    ok, vio, reason = pg.judge_stage_paths(
        "implement", ["app/src/a.py", "docs/other.md"], write_set=["app/src"])
    assert not ok and vio == ["docs/other.md"] and reason == "unauthorized_path"


def test_implement_empty_write_set_fail_closed():
    # 写集空/缺失/畸形 = fail-closed 拒绝（出路=补配写集），绝不放行
    for ws in (None, [], ["", "  "], "app/src", [["x"]]):
        ok, vio, reason = pg.judge_stage_paths("implement", ["app/src/a.py"], write_set=ws)
        assert not ok and reason == "write_set_missing", repr(ws)
        assert pg.PATH_GATE_REASON_KEY in pg.gate_refusal_note("implement", vio, reason)


def test_integ_join_union_face():
    ws = ["app/src"]
    ok, _, _ = pg.judge_stage_paths("integ_join", ["app/src/a.py"], write_set=ws)
    assert ok
    ok, _, _ = pg.judge_stage_paths("integ_join", ["integration/t260911-03/x.py"], write_set=ws)
    assert ok  # design 边 = integration/ 整目录
    ok, vio, reason = pg.judge_stage_paths("integ_join", ["docs/other.md"], write_set=ws)
    assert not ok and vio == ["docs/other.md"] and reason == "unauthorized_path"
    # 汇合段写集缺失同样 fail-closed
    ok, _, reason = pg.judge_stage_paths("integ_join", ["integration/x.py"], write_set=None)
    assert ok  # integration/ 面仍在
    ok, _, reason = pg.judge_stage_paths("integ_join", ["app/src/a.py"], write_set=None)
    assert not ok and reason == "write_set_missing"


def test_design_only_integration_prefix():
    ok, _, _ = pg.judge_stage_paths(
        "design_integration_tests", ["integration/t260911-03/tests/x.py"])
    assert ok
    ok, vio, reason = pg.judge_stage_paths(
        "design_integration_tests", ["server/engine/x.py"])
    assert not ok and vio == ["server/engine/x.py"] and reason == "unauthorized_path"


def test_ui_evidence_dirs_face():
    ok, _, _ = pg.judge_stage_paths(
        "ui_evidence", ["webui/screens/a.png"], ui_dirs=["webui/screens"])
    assert ok
    ok, _, reason = pg.judge_stage_paths("ui_evidence", ["webui/other.py"], ui_dirs=["webui/screens"])
    assert not ok and reason == "unauthorized_path"
    # 声明读不到 = 空集 = fail-closed
    ok, _, reason = pg.judge_stage_paths("ui_evidence", ["webui/screens/a.png"], ui_dirs=None)
    assert not ok and reason == "ui_dirs_missing"


def test_ticket_receipts_pinned_prefix():
    # 条件 3：回执面前缀钉死 integration/<ticket_id>/，不放宽为 integration/ 整目录
    ok, _, _ = pg.judge_stage_paths(
        "run_integration_tests", ["integration/t260911-03/out.json"], ticket_id="t260911-03")
    assert ok
    ok, vio, reason = pg.judge_stage_paths(
        "run_integration_tests", ["integration/t999999-99/other.json"],
        ticket_id="t260911-03")
    assert not ok and reason == "unauthorized_path"
    # ticket_id 缺失 → 本票面不存在 → 一律拒
    ok, _, reason = pg.judge_stage_paths(
        "run_integration_tests", ["integration/t260911-03/out.json"], ticket_id="")
    assert not ok and reason == "unauthorized_path"


def test_arbitrate_test_face_and_ticket_scenario():
    ticket = "t260911-03"
    ok, _, _ = pg.judge_stage_paths(
        "arbitrate",
        ["integration/%s/tests/test_x.py" % ticket, "server/engine/tests/test_y.py",
         "integration/%s/sc_a.py" % ticket,  # 本票场景（验收 c：仲裁段只改本票场景 → 放行）
         "integration/tests/util.py",        # tests/ 目录内（测试面口径）
         "server/tools/test_runner.py"],     # test_*.py 文件名
        ticket_id=ticket)
    assert ok
    # 碰产品代码 = code-fault 打回面（宿主令：仲裁只许测试面）
    ok, vio, reason = pg.judge_stage_paths(
        "arbitrate", ["server/engine/dev_lane.py"], ticket_id=ticket)
    assert not ok and vio == ["server/engine/dev_lane.py"] and reason == "unauthorized_path"
    # 他票场景不是本票回执面
    ok, vio, _ = pg.judge_stage_paths(
        "arbitrate", ["integration/t999999-99/sc.py"], ticket_id=ticket)
    assert not ok and vio == ["integration/t999999-99/sc.py"]


def test_arbitrate_scenario_scripts_in_face_cf2():
    """CF2：tests-fault 时仲裁直接迭代 integration/ 测试集——已登记场景脚本
    （sc_*.py/.mjs，含他票）与登记表 run_scenarios.py 属测试面（登记面=正常工作面，
    不受保护）；共享资产仍由受保护闸兜底，产品代码照拒。"""
    ticket = "t260911-03"
    ok, _, _ = pg.judge_stage_paths(
        "arbitrate",
        ["integration/t260901-16/sc_t06_settle_lane_anchoring.py",  # 他票场景脚本（仲裁实测修复面）
         "integration/t260907-04/sc_naming_grep_assert.mjs",
         "integration/run_scenarios.py"],
        ticket_id=ticket)
    assert ok
    # 误伤反例：integration/ 下非场景脚本（非 sc_ 前缀、非 tests/ 目录）不在面内
    ok, vio, _ = pg.judge_stage_paths(
        "arbitrate", ["integration/lib_env.py", "integration/with_stage.sh",
                      "integration/t999999-99/sc.py"],  # sc.py 非 sc_ 前缀
        ticket_id=ticket)
    assert not ok and len(vio) == 3
    # 产品代码照拒（不因 CF2 放宽）
    ok, vio, reason = pg.judge_stage_paths(
        "arbitrate", ["server/engine/dev_lane.py"], ticket_id=ticket)
    assert not ok and reason == "unauthorized_path"
    # 共享守卫/共享电池：测试面 overlaps 但受保护闸仍拦（双闸独立执法）
    vio, reason = pg.judge_protected_paths(
        ["integration/t260902-07/tests/test_route_table.py"], exists_at_base=lambda p: True)
    assert vio and reason == "protected_path"
    # _is_scenario_script 口径边界
    assert pg._is_scenario_script("integration/t1/sc_x.py")
    assert pg._is_scenario_script("integration/t1/sub/sc_x.mjs")
    assert not pg._is_scenario_script("integration/sc_x.py")        # 缺场景目录段
    assert not pg._is_scenario_script("integration/t1/sc_x.txt")
    assert not pg._is_scenario_script("server/engine/sc_x.py")      # 非 integration/ 前缀
    assert not pg._is_scenario_script("../integration/t1/sc_x.py")  # 不安全路径


def test_merge_check_self_heal_face():
    ws = ["app/src"]
    ok, _, _ = pg.judge_stage_paths(
        "merge_check", ["app/src/late.py"], write_set=ws, ticket_id="t1")
    assert ok  # KI-009 自愈：写集内兜底
    ok, _, reason = pg.judge_stage_paths(
        "merge_check", ["docs/other.md"], write_set=ws, ticket_id="t1")
    assert not ok and reason == "unauthorized_path"  # 自愈也不许夹带写集外面


def test_unknown_stage_fail_closed():
    # 未知段：fail-closed 拒绝（不静默免检）；畸形段 id 同罪
    for st in ("some_future_stage", "", None, "acceptance"):
        ok, vio, reason = pg.judge_stage_paths(
            st, ["server/engine/dev_lane.py"])
        assert not ok and reason == "unknown_stage", repr(st)
        note = pg.gate_refusal_note(str(st or ""), vio, reason)
        assert pg.is_gate_refusal(note) and "path_gate_reason=unknown_stage" in note


def test_result_files_always_allowed_and_clean_workspace():
    for st in pg.STAGE_PATH_RULES:
        ok, vio, reason = pg.judge_stage_paths(
            st, [".sandbar/stage_x_gen0.json", ".suyou/stage_x_gen0.json"])  # naming-compat
        assert (ok, vio, reason) == (True, [], ""), st
    ok, vio, reason = pg.judge_stage_paths("implement", [], write_set=None)
    assert (ok, vio, reason) == (True, [], "")  # 空清单=无需判定（干净工作区走 no-op）


# ---------------- ② 受保护路径闸 ----------------

def test_protected_existing_at_base_refused():
    hits = [
        "integration/t260902-07/tests/test_route_table.py",
        "integration/t260902-07/tests/test_route_lookup.py",
        "integration/baselines/expectations.json",
        "verify.yaml",
        "server/model-routes.yaml",
        "server/merge-checks.yaml",
        "server/projects.yaml",
        "server/project-registry.ts",
        "server/roles/developer.yml",
        "docs/design/失败分类协议v1.md",
        "server/engine/path_gates.py",
    ]
    for f in hits:
        vio, reason = pg.judge_protected_paths([f], exists_at_base=lambda p: True)
        assert vio == [f] and reason == "protected_path", f
        note = pg.gate_refusal_note("implement", vio, reason)
        assert "path_gate_reason=protected_path" in note and f in note


def test_protected_new_file_allowed_birth_paradox():
    # 「存在才拦」：新建（base 不存在）放行——闸不挡 path_gates.py 自己的出生；
    # 落地后（新分叉泳道 base 已存在）即拦。条件 2 的两态断言。
    f = "server/engine/path_gates.py"
    vio, reason = pg.judge_protected_paths([f], exists_at_base=lambda p: False)
    assert (vio, reason) == ([], "")
    vio, reason = pg.judge_protected_paths([f], exists_at_base=lambda p: True)
    assert vio == [f] and reason == "protected_path"


def test_protected_no_anchor_fail_closed():
    # 谓词缺席/谓词故障 = 锚不可知 = 按已存在处理（fail-closed 拦，不猜）
    vio, reason = pg.judge_protected_paths(["verify.yaml"], exists_at_base=None)
    assert vio == ["verify.yaml"]

    def _boom(_):
        raise RuntimeError("git 故障")
    vio, reason = pg.judge_protected_paths(["verify.yaml"], exists_at_base=_boom)
    assert vio == ["verify.yaml"] and reason == "protected_path"


def test_run_scenarios_not_protected():
    # 名单不含登记增量类文件（避免误伤正常工作面）
    vio, reason = pg.judge_protected_paths(
        ["integration/run_scenarios.py"], exists_at_base=lambda p: True)
    assert (vio, reason) == ([], "")


def test_protected_unrelated_files_pass():
    vio, reason = pg.judge_protected_paths(
        ["app/src/a.py", "server/engine/other.py"], exists_at_base=lambda p: True)
    assert (vio, reason) == ([], "")


# ---------------- is_test_face 口径 ----------------

def test_is_test_face_boundary():
    assert pg.is_test_face("tests/test_a.py")
    assert pg.is_test_face("server/engine/tests/test_a.py")
    assert pg.is_test_face("integration/t260911-03/tests/test_a.py")
    assert pg.is_test_face("pkg/test_a.py")
    assert pg.is_test_face("pkg/foo_test.py")
    assert not pg.is_test_face("pkg/conftest.py")     # 不在 tests/ 内、非 test_* 文件名
    assert not pg.is_test_face("server/engine/dev_lane.py")
    assert not pg.is_test_face("tests_helper/x.py")   # tests 目录段必须整段匹配
    assert not pg.is_test_face("")
    assert not pg.is_test_face("../tests/test_a.py")  # 不安全路径不算测试面


# ---------------- 畸形输入（消费外部输入的畸形电池） ----------------

def test_malformed_inputs_fail_closed():
    # 脏清单畸形：非列表（含可迭代字符串——严禁逐字符裂成假清单）、None、非串条目、
    # 不安全路径 → 不进判定面；implement 段无写集时按缺面拒绝而非异常
    for bad in (None, "app/src/a.py", 123, {"a": 1}, [None, 3, "", "/abs/x.py",
                                                      "../up.py", "a\\b.py",
                                                      "we?rd.py", "x[0].py"]):
        ok, vio, reason = pg.judge_stage_paths("implement", bad, write_set=["app/src"])
        if ok:
            assert vio == [] and reason == ""  # 清洗后无剩余条目=无事可判
        else:
            assert reason in ("unauthorized_path", "write_set_missing")
    # 畸形写集条目已由 test_implement_empty_write_set_fail_closed 覆盖
    # 不安全路径被清洗出判定面（丢弃不猜）；剩余合法条目只有结果文件 → 放行
    ok, vio, reason = pg.judge_stage_paths(
        "create_plan", [".sandbar", "../.sandbar/evil", ".sandbar/../evil"],
        write_set=None)
    assert (ok, vio, reason) == (True, [], "")


def test_note_single_line_and_names_files():
    note = pg.gate_refusal_note(
        "arbitrate", ["server/engine/a.py", "server/engine/b.py", "server/engine/c.py",
                      "server/engine/d.py"], "unauthorized_path")
    assert "\n" not in note
    assert "path_gate_reason=unauthorized_path" in note
    assert "arbitrate" in note and "server/engine/a.py" in note and "等 4 项" in note
    assert "main" in note  # 出路文案在场
    assert pg.is_gate_refusal(note)
    assert not pg.is_gate_refusal("工作区已干净，无需代落盘")
    assert not pg.is_gate_refusal("")
    assert not pg.is_gate_refusal(None)


# ---------------- 写集条目匹配立场与既有 helper 的漂移锁 ----------------

def test_write_set_stance_matches_agent_activities_helper():
    import agent_activities as aa
    matrix_files = ["app/src/a.py", "app/src/b/c.py", "app/srcd.py", "app/x.py",
                    "/abs.py", "../up.py", "a\\b.py", "we?rd.py", "", None]
    matrix_ws = [
        ["app/src"], ["app/src/"], ["app"], [], None, "app/src", [""], [["x"]],
        ["app/src", "docs"],
    ]
    for ws in matrix_ws:
        for f in matrix_files:
            mine = pg._within(f, pg._entries(ws)[1]) if pg._is_safe_path(f) else False
            theirs = aa._dirty_within_write_set([f], ws) if isinstance(f, str) else False
            assert mine == theirs, (f, ws, mine, theirs)


# ---------------- 源码锁定（接线完整性，防旁路） ----------------

def _src(name: str) -> str:
    return (ENGINE_DIR / name).read_text("utf-8")


def _settle_call_sites(src: str):
    """提取 _settle_worktree_lane 的全部调用点（含平衡括号的完整调用文本）。"""
    sites = []
    idx = 0
    while True:
        i = src.find("_settle_worktree_lane(", idx)
        if i < 0:
            break
        if src[max(0, i - 4):i] != "def ":
            j = i + len("_settle_worktree_lane")
            depth = 0
            k = j
            while k < len(src):
                if src[k] == "(":
                    depth += 1
                elif src[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            sites.append(src[i:k + 1])
        idx = i + 1
    return sites


def test_source_lock_all_settle_call_sites_gated():
    """settle 落点清单锁定：6 处原始 settle 全部过闸——3 处直调（各自带闸参数）+
    4 处经 _settle_with_gate 单点拼装（generic 缓存/结果就绪两分支、_stub_stage_shortcut
    缓存、arbitrate tests-fault 分支）。数量变化 = 有新落点/旁路，必须逐一核对。"""
    src = _src("agent_activities.py")
    direct = _settle_call_sites(src)
    assert len(direct) == 3, "直调 settle 落点数量变化：%d" % len(direct)
    for s in direct:
        assert "path_gate" in s, "直调 settle 落点未带闸参数：%s" % s[:120]
    helper_calls = []
    idx = 0
    while True:
        i = src.find("_settle_with_gate(", idx)
        if i < 0:
            break
        if src[max(0, i - 4):i] != "def ":
            helper_calls.append(i)
        idx = i + 1
    assert len(helper_calls) == 4, "经闸拼装的 settle 落点数量变化：%d" % len(helper_calls)


def test_source_lock_gate_judged_before_git_add():
    src = _src("agent_activities.py")
    add_at = src.find('_git(["add"')
    gate_at = src.find("judge_stage_paths(")
    protected_at = src.find("judge_protected_paths(")
    assert 0 < gate_at < add_at, "阶段闸判定必须在任何 git add 之前（未暂存态前提）"
    assert 0 < protected_at < add_at, "受保护闸判定必须在任何 git add 之前"


def test_source_lock_stages_subset_of_rule_keys():
    """DevLaneWorkflow.STAGES id 全集 ⊆ STAGE_PATH_RULES 键集——新段忘配=单测红。"""
    tree = ast.parse(_src("dev_lane.py"))
    stage_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DevLaneWorkflow":
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    if any(isinstance(t, ast.Name) and t.id == "STAGES" for t in targets):
                        for item in ast.walk(sub.value):
                            if isinstance(item, ast.Call):
                                for kw in item.keywords:
                                    if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                                        stage_ids.add(kw.value.value)
    assert stage_ids, "未从 dev_lane 解析到 STAGES（结构变化时更新本锁定测试）"
    missing = stage_ids - set(pg.STAGE_PATH_RULES)
    assert not missing, "STAGES 段缺规则键：%s" % sorted(missing)
    # integ_join 是并行汇合的运行时传值（PHASE 词表值，非 STAGES id）——显式在键集
    assert "integ_join" in pg.STAGE_PATH_RULES


def test_source_lock_dev_lane_wiring():
    src = _src("dev_lane.py")
    # meta 总开关随派单输入钉死（replay 稳定判别锚）
    assert 'bool(getattr(inp, "path_gate", False))' in src
    # 通用 agent 步 / 两处 SettleLaneArgs / MergeCheckArgs 全部过参
    # （suggest_next 段已随 t260910-14 在 main 侧退役，其闸参数随之移除，
    #  path_gates 的 suggest_next 规则键保留为防御性键）
    assert src.count('path_gate=bool(self.meta.get("path_gate"))') >= 4
    # arb_acc 汇合与 integ_join 汇合的闸拒绝都转 blocked（不吞成日志）
    assert src.count('await self._blocked("arbitrate", s.error)') == 1
    assert src.count('await self._blocked("implement", s.error)') == 1


def test_source_lock_client_dispatch_pins_gate():
    src = _src("client.py")
    assert 'path_gate=(str(tpl) == "dev-lane")' in src


# ---------------- 数据类缺字段默认值（老在途票 replay 兼容） ----------------

def test_dataclass_defaults_backward_compatible():
    a = shared.AgentStageArgs(ticket_id="t", stage_id="implement", role="developer",
                              prompt="p")
    assert a.path_gate is False and a.write_set == [] and a.ui_dirs == [] and a.base_ref == ""
    s = shared.SettleLaneArgs(ticket_id="t", worktree="w", stage_id="implement", gen=0)
    assert s.path_gate is False and s.write_set == [] and s.base_ref == ""
    m = shared.MergeCheckArgs(ticket_id="t")
    assert m.path_gate is False
    t = shared.TicketInput(ticket_id="t", template_id="dev-lane")
    assert t.path_gate is False  # 老在途票输入反序列化 = 关闸（不追溯）
    assert shared.TicketInput(ticket_id="t", template_id="dev-lane",
                              path_gate=True).path_gate is True


# ---------------- 模块常量卫生 ----------------

def test_protected_list_hygiene():
    # 名单条目全部走 _within 匹配立场（尾斜杠条目与裸目录名等价）
    assert pg._within("integration/baselines", pg.PROTECTED_PATHS)
    assert pg._within("integration/baselines/x.json", pg.PROTECTED_PATHS)
    # 显式排除项不在名单
    assert not pg._within("integration/run_scenarios.py", pg.PROTECTED_PATHS)
    assert not pg._within(".sandbar/anything", pg.PROTECTED_PATHS)
