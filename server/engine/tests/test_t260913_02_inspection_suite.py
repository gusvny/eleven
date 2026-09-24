"""t260913-02 单测①：巡检自有泳道 + 套件段 + 声明决议 + 装配面。

分工照旧（t260911-02 头注同款）：可离线判定的纯函数/装配契约在这里锁；workflow 体的
真行为（搭泳道→跑全集→拆泳道）走隔离台真跑，不进 UT（conftest：UT 禁网络/真 Temporal/
真 git——因此 refname 合法性用纯词法校验，不用 `git check-ref-format` 实跑）。
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_decl as decl
import inspection_flow as flow
from inspection_deadman import suite_section


# ========================================================================================
# 泳道命名空间（不复用开发泳道）
# ========================================================================================

def _refname_illegal(branch: str) -> bool:
    """纯词法：git refname 非法形态（不实跑 git；与 check-ref-format 的关键面等价）。"""
    bad = (" ", "~", "^", ":", "?", "*", "[", "\\", "..", "@{", "//")
    return (not branch or branch.startswith("-") or branch.startswith("/")
            or branch.endswith("/") or branch.endswith(".lock")
            or any(b in branch for b in bad))


def test_lane_paths_inspection_namespace():
    wt, br = flow.inspection_lane_paths("integration-tests", "20260913", "/repo")
    assert wt == "/repo/.lane/inspection-integration-tests-20260913"
    assert br == "inspection/integration-tests/20260913"
    # 扁平一级：父目录就是 .lane（_lane_repo_root 的锚定约定，不能更深）
    assert Path(wt).parent.name == ".lane"
    assert not _refname_illegal(br)


def test_lane_paths_relative_when_no_repo_root():
    wt, _ = flow.inspection_lane_paths("docs-sync", "20260911")
    assert wt == ".lane/inspection-docs-sync-20260911"


def test_lane_namespace_disjoint_from_dev_lane():
    """与开发泳道 default_lane_paths 的输出零交集（红线：不得占用开发泳道命名）。"""
    from shared import default_lane_paths
    dev_path, dev_branch = default_lane_paths("t260913-02")
    assert dev_path.startswith(".lane/t")
    assert dev_branch.startswith("lane/")
    for inst in ("integration-tests", "docs-sync", "a"):
        wt, br = flow.inspection_lane_paths(inst, "20260913")
        assert not wt.startswith(".lane/t")
        assert br.startswith("inspection/")
        assert wt != dev_path and br != dev_branch


def test_lane_paths_reject_malformed_inputs():
    for bad_inst in ("", "UPPER", "../evil", "-lead", "x" * 65, "a/b"):
        with pytest.raises(ValueError):
            flow.inspection_lane_paths(bad_inst, "20260913")
    for bad_period in ("", "2026-09-13", "2026091", "20260913-0", "../x"):
        with pytest.raises(ValueError):
            flow.inspection_lane_paths("docs-sync", bad_period)
    assert not _refname_illegal(flow.inspection_lane_paths("integration-tests", "20260913-2")[1])


# ========================================================================================
# 残留清扫决策（水位：只清早于本期的；在跑的并发期与开发泳道不碰）
# ========================================================================================

_WT = [{"path": "/r/.lane/inspection-integration-tests-20260912", "branch": ""},
       {"path": "/r/.lane/inspection-integration-tests-20260913", "branch": ""},
       {"path": "/r/.lane/inspection-integration-tests-20260913-1", "branch": ""},
       {"path": "/r/.lane/inspection-docs-sync-20260912", "branch": ""},
       {"path": "/r/.lane/t260901-01", "branch": ""},
       {"path": "/r/.lane/t260910-03", "branch": ""}]
_BR = ["inspection/integration-tests/20260912", "inspection/integration-tests/20260913",
       "inspection/integration-tests/20260913-2", "inspection/docs-sync/20260912",
       "lane/t260901-01", "main"]


def test_sweep_plan_watermark_semantics():
    plan = flow.sweep_plan(_WT, _BR, "integration-tests", "20260913")
    assert plan["remove_worktrees"] == ["/r/.lane/inspection-integration-tests-20260912"]
    assert plan["remove_branches"] == ["inspection/integration-tests/20260912"]
    # 当期保留；水位之后的并发期让行（deferred，不删）
    assert "/r/.lane/inspection-integration-tests-20260913" in plan["keep"]
    assert "/r/.lane/inspection-integration-tests-20260913-1" in plan["deferred"]
    assert "inspection/integration-tests/20260913-2" in plan["deferred"]
    # 开发泳道与别的实例一律不碰（既不在删也不在 deferred——它们根本不入本实例命名空间）
    for x in ("/r/.lane/t260901-01", "/r/.lane/t260910-03",
              "/r/.lane/inspection-docs-sync-20260912"):
        assert x not in plan["remove_worktrees"]
    assert "lane/t260901-01" not in plan["remove_branches"]
    assert "main" not in plan["remove_branches"]


def test_sweep_plan_empty_keep_removes_all_of_instance():
    plan = flow.sweep_plan(_WT, _BR, "integration-tests", "")
    assert "/r/.lane/inspection-integration-tests-20260912" in plan["remove_worktrees"]
    assert "/r/.lane/inspection-integration-tests-20260913" in plan["remove_worktrees"]
    assert plan["deferred"] == []


def test_sweep_plan_malformed_entries_never_deleted():
    plan = flow.sweep_plan([{"branch": "x"}, "not-a-dict", {"path": 5},
                            {"path": "/r/.lane/inspection-integration-tests-2026bad"}],
                           ["inspection/integration-tests/2026bad"], "integration-tests", "20260913")
    assert plan["remove_worktrees"] == [] and plan["remove_branches"] == []
    assert len(plan["skipped"]) == 4          # 四条畸形逐条点名，不静默


def test_sweep_plan_targeted_mode_removes_exactly_one_period():
    """定向模式（拆除回落用）：只清指定期号，水位/并发期/开发泳道都不碰。"""
    plan = flow.sweep_plan(_WT, _BR, "integration-tests", "", "20260913")
    assert plan["remove_worktrees"] == ["/r/.lane/inspection-integration-tests-20260913"]
    assert plan["remove_branches"] == ["inspection/integration-tests/20260913"]
    assert "/r/.lane/inspection-integration-tests-20260912" not in plan["remove_worktrees"]
    assert "/r/.lane/inspection-integration-tests-20260913-1" not in plan["remove_worktrees"]
    assert "/r/.lane/t260901-01" not in plan["remove_worktrees"]
    # 定向模式不产出 keep/deferred 语义噪声（只有 skipped 可能非空）
    assert plan["keep"] == [] and plan["deferred"] == []
    # 不存在的期号：什么都不清（幂等：重复拆除安全）
    empty = flow.sweep_plan(_WT, _BR, "integration-tests", "", "20260901")
    assert empty["remove_worktrees"] == [] and empty["remove_branches"] == []


def test_sweep_plan_rejects_malformed_instance():
    with pytest.raises(ValueError):
        flow.sweep_plan([], [], "../evil", "20260913")


def test_parse_worktree_porcelain_shapes():
    from agent_activities import parse_worktree_porcelain
    text = ("worktree /r\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /r/.lane/t1\nHEAD def\nbranch refs/heads/lane/t1\n\n"
            "worktree /tmp/x\nHEAD 123\ndetached\nprunable\n")
    got = parse_worktree_porcelain(text)
    assert [e["path"] for e in got] == ["/r", "/r/.lane/t1", "/tmp/x"]
    assert got[1]["branch"] == "refs/heads/lane/t1"
    assert got[2]["detached"] and got[2]["prunable"]
    assert parse_worktree_porcelain("") == []
    assert parse_worktree_porcelain("garbage\nlines\n") == []


# ========================================================================================
# 声明决议（C4 三态闭式）+ suite 字段
# ========================================================================================

def _decl_text(suite_line: str = "    suite: full\n") -> str:
    return ("schema: v1\n"
            "instances:\n"
            "  - id: integration-tests\n"
            "    enabled: true\n"
            "    project_key: sandbar\n"
            + suite_line +
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 30 7 * * *\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n"
            "  - id: docs-sync\n"
            "    enabled: true\n"
            "    project_key: sandbar\n"
            "    scan_face: doc\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 10 * * 1\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n"
            "  - id: simplify-face\n"
            "    enabled: false\n"
            "    project_key: sandbar\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 0 8 * * 1\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n")


def test_suite_field_parses_and_reaches_specs(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text(), "utf-8")
    d = decl.load_inspection_decl(p)
    assert d.instance("integration-tests").suite == "full"
    assert d.instance("docs-sync").suite == ""
    specs = {s["instance_id"]: s for s in decl.build_schedule_specs(d)}
    assert specs["integration-tests"]["suite"] == "full"
    assert specs["integration-tests"]["cron"] == "30 7 * * *"
    assert specs["docs-sync"]["suite"] == ""


def test_suite_field_absent_is_backward_compatible(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text(suite_line=""), "utf-8")
    d = decl.load_inspection_decl(p)
    assert d.instance("integration-tests").suite == ""


def test_suite_field_unwired_value_fails_closed(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text(suite_line="    suite: smoke\n"), "utf-8")
    with pytest.raises(decl.DeclError) as ei:
        decl.load_inspection_decl(p)
    assert "suite" in str(ei.value) and "smoke" in str(ei.value)


def test_unknown_instance_field_still_fails_closed(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text().replace("    template: inspection-lite\n",
                                      "    template: inspection-lite\n    face: test\n", 1), "utf-8")
    with pytest.raises(decl.DeclError):
        decl.load_inspection_decl(p)


def test_resolve_instance_plan_three_states(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text(), "utf-8")
    ok = decl.resolve_instance_plan("integration-tests", p)
    assert ok["ok"] and ok["run_suite"] is True and ok["suite"] == "full"
    assert ok["cron"] == "30 7 * * *" and ok["scan_face"] == "test"
    # 启用但没声明 suite：ok=True 且 run_suite=False（与「停用」不同形）
    doc = decl.resolve_instance_plan("docs-sync", p)
    assert doc["ok"] and doc["run_suite"] is False and doc["suite"] == ""
    assert doc["scan_face"] == "doc"
    # 停用 → ok=False 点名（调度还在触发=配置漂移，不得当 no-suite 放过）
    off = decl.resolve_instance_plan("simplify-face", p)
    assert off["ok"] is False and "停用" in off["error"]
    # 不在册 → ok=False 点名
    miss = decl.resolve_instance_plan("nope", p)
    assert miss["ok"] is False and "不在声明中" in miss["error"]
    # 声明不可解析 → ok=False 点名（fail-closed）
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: v1\ninstances: []\n", "utf-8")
    err = decl.resolve_instance_plan("integration-tests", bad)
    assert err["ok"] is False and err["error"]


def test_shipped_declaration_is_daily_and_suite_full():
    """随票声明面锁定：integration-tests = 每日 07:30（Asia/Shanghai）+ suite: full
    （宿主令 260913 每日调度接真）。t260916-02：真源声明迁仓根 <repo>/inspection.yaml，
    显式按路径装载（不依赖 env/引擎旧位）。"""
    d = decl.load_inspection_decl(
        Path(__file__).resolve().parent.parent.parent.parent / "inspection.yaml")
    it = d.instance("integration-tests")
    assert it.suite == "full"
    assert it.cron == "30 7 * * *"
    assert it.tz == "Asia/Shanghai"                 # Temporal cron 默认 UTC：不带 tz 会落 15:30
    assert d.instance("docs-sync").suite == ""      # 其余实例扫描面零改动


def test_tz_field_parses_and_reaches_specs(tmp_path):
    p = tmp_path / "inspection.yaml"
    p.write_text(_decl_text().replace("    workflow: InspectionPeriodicWorkflow\n",
                                      "    tz: Asia/Shanghai\n    workflow: InspectionPeriodicWorkflow\n", 1),
                 "utf-8")
    d = decl.load_inspection_decl(p)
    assert d.instance("integration-tests").tz == "Asia/Shanghai"
    specs = {s["instance_id"]: s for s in decl.build_schedule_specs(d)}
    assert specs["integration-tests"]["tz"] == "Asia/Shanghai"
    assert specs["docs-sync"]["tz"] == ""
    plan = decl.resolve_instance_plan("integration-tests", p)
    assert plan["tz"] == "Asia/Shanghai"


def test_tz_field_malformed_fails_closed(tmp_path):
    for bad in ("8 hours", "../etc", "-lead", "a b", "x" * 65):
        p = tmp_path / "inspection.yaml"
        p.write_text(_decl_text(suite_line="    suite: full\n    tz: %s\n" % bad), "utf-8")
        with pytest.raises(decl.DeclError):
            decl.load_inspection_decl(p)


def test_deadman_default_ledger_matches_shared():
    """CLI 台账默认目录必须与 shared.INSPECTION_DIR 同口径（否则 deadman 列表面读空账，
    而票面写的是另一个目录——两张台账=漏报）。"""
    import inspection_trigger as trig
    import shared
    assert str(trig._default_ledger_dir()) == str(shared.INSPECTION_DIR)


def test_schedule_up_sets_timezone_and_teardown_has_fallback():
    """两条结构钉子（workflow 体行为走真跑，这里锁装配面）：
    ① schedule-up 把声明 tz 传进 ScheduleSpec（create+update 两路）；
    ② 拆除主路径复用 teardown_lane，且带 repo 锚定回落（跨仓泳道 teardown 锚错仓，KI-074/075 同族）。"""
    import inspect as _inspect
    import inspection_trigger as trig
    src = _inspect.getsource(trig.cmd_schedule_up)
    assert src.count("time_zone_name=tz or None") == 2      # update + create
    fsrc = _inspect.getsource(flow.InspectionPeriodicWorkflow._teardown)
    assert "teardown_lane" in fsrc
    assert "sweep_inspection_lanes" in fsrc and "remove_period" in fsrc


# ========================================================================================
# 票面扩展（套件段/追加发现/心跳合成/建议开关）
# ========================================================================================

_SCAN = {"findings": [], "summary": {"high": 0, "med": 0, "low": 0}, "heartbeat": True,
         "meta": {"scenarios": 3}}


def test_face_without_suite_is_byte_identical_to_ticket1():
    """零回归钉子：两个 defaulted 参数缺席时，票面与票①逐字段一致。"""
    face = flow.build_ticket_face("t", "i", "20260913", _SCAN)
    assert set(face) == {"ticket_id", "kind", "instance_id", "period", "red_line",
                         "heartbeat", "heartbeat_note", "summary", "findings",
                         "suggested_fix_tickets", "scan_meta"}
    assert face["heartbeat"] is True and face["summary"] == {"high": 0, "med": 0, "low": 0}


def test_face_suite_green_keeps_heartbeat_and_adds_section():
    sec = suite_section({"ran": 3, "passed": 3, "failed": 0, "env_fail": 0,
                         "details": [{"name": "a", "exit": 0}, {"name": "b", "exit": 0}],
                         "report_path": "/out/x-suite.json"}, wall_seconds=12.5)
    face = flow.build_ticket_face("t", "i", "20260913", _SCAN, suite=sec)
    assert face["heartbeat"] is True
    assert face["suite"]["ran"] == 3 and face["suite"]["wall_seconds"] == 12.5
    assert [c["name"] for c in face["suite"]["cases"]] == ["a", "b"]
    assert face["suite"]["report_path"] == "/out/x-suite.json"


def test_face_suite_red_and_extras_recount_and_kill_heartbeat():
    from inspection_deadman import deadman_findings, suite_findings
    receipt = {"ran": 2, "passed": 0, "failed": 2, "env_fail": 0, "error": "",
               "report_path": "/out/x-suite.json",
               "details": [{"name": "red-a", "exit": 1, "output_tail": "boom"},
                           {"name": "red-b", "exit": 2, "output_tail": "boom2"}]}
    sec = suite_section(receipt)
    extras = suite_findings(receipt) + deadman_findings(["20260912"], "integration-tests",
                                                        "30 7 * * *")
    face = flow.build_ticket_face("t", "i", "20260913", _SCAN,
                                  extra_findings=extras, suite=sec)
    assert face["heartbeat"] is False
    assert face["summary"]["high"] == 3          # 两条套件红 + 一条漏跑
    # 漏跑条不进开票建议（suggest=false）；套件红条进（人审后定）
    titles = " ".join(s["title"] for s in face["suggested_fix_tickets"])
    assert "套件红" in titles and "漏跑" not in titles
    assert all(s["source_inspection"] == "t" for s in face["suggested_fix_tickets"])


def test_face_suite_env_fail_is_not_heartbeat_green():
    sec = suite_section({"ran": 1, "passed": 1, "failed": 0, "env_fail": 2, "error": "",
                         "details": []})
    face = flow.build_ticket_face("t", "i", "20260913", _SCAN, suite=sec)
    assert face["heartbeat"] is False


def test_face_malformed_scan_result_still_rejected():
    with pytest.raises(ValueError):
        flow.build_ticket_face("t", "i", "20260913", {"findings": "nope"})


# ========================================================================================
# 套件回执落盘 + 台账识别（回执文件不得被当成台账票）
# ========================================================================================

def test_suite_receipt_written_and_not_a_ledger_entry(tmp_path):
    from inspection_deadman import ledger_periods
    out = tmp_path / "inspection"
    # t260916-02：回执文件名按（实例,期）派生（inspection_ledger_name 单点）；
    # instance/period 双缺时回落旧形 ticket_id 只读解析（历史票重放兜底）。
    res = flow.write_inspection_suite_receipt_impl(
        "integration-tests", "20260913", {"ran": 1, "error": ""}, out)
    assert res["file"] == "inspection-integration-tests-20260913-suite.json"
    assert res["instance_id"] == "integration-tests" and res["period"] == "20260913"
    legacy = flow.write_inspection_suite_receipt_impl(
        "", "", {"ticket_id": "inspection-integration-tests-20260913",
                 "ran": 1, "error": ""}, out)
    assert legacy["file"] == "inspection-integration-tests-20260913-suite.json"
    flow.write_inspection_report_impl(
        {"ticket_id": "inspection-integration-tests-20260913",
         "instance_id": "integration-tests", "period": "20260913"}, out)
    led = ledger_periods(out, "integration-tests")
    assert led["periods"] == {"20260913"}       # -suite.json 是已知非台账件
    assert led["malformed"] == []


def test_suite_receipt_impl_rejects_missing_ticket(tmp_path):
    with pytest.raises(ValueError):
        flow.write_inspection_suite_receipt_impl("", "", {}, tmp_path)
    with pytest.raises(ValueError):
        # 双缺且 ticket_id 非旧形（不可解析）→ 显式拒收，绝不落怪名文件
        flow.write_inspection_suite_receipt_impl("", "", {"ticket_id": "t060913-01"}, tmp_path)


def test_blocked_face_roundtrip_carries_reason_and_stage(tmp_path):
    """blocked 终态落账（dead-man 列表可读面的机械面）：票面文件带 blocked_reason/stage。"""
    import json
    face = {"ticket_id": "inspection-integration-tests-20260913", "kind": "inspection",
            "instance_id": "integration-tests", "period": "20260913",
            "heartbeat": False, "summary": {}, "findings": [],
            "blocked_reason": "泳道搭不起来：git worktree add 失败", "stage": "setup"}
    res = flow.write_inspection_report_impl(face, tmp_path)
    got = json.loads(Path(res["path"]).read_text("utf-8"))
    assert got["blocked_reason"].startswith("泳道搭不起来") and got["stage"] == "setup"


# ========================================================================================
# 超时口径 + 输入形状 + 装配面
# ========================================================================================

def test_replay_gate_locks_new_commands():
    """版本门钉子（replay 安全）：新命令只在新 run 注入——老在途票（票①② 起的 RUNNING
    实例）history 里没有 SUITE_PATCH_ID 标记 → patched() 返回 False → 走票① 旧路径。
    实测面=replay_check.py 重放四张在途老票（out/evidence_replay_check.txt 全绿）；
    这条单测锁「三个新命令点都在门后」的结构，防日后有人把 gate 挪掉。"""
    import inspect as _inspect
    assert flow.SUITE_PATCH_ID == "t260913-02-inspection-suite-stage"
    # t260916-22：run=薄分派（双版本门：SUITE 且 INSPECT → inspect 轨；否则 legacy 轨），
    # 主体外提两条轨道方法——锁随锚点更新：门在 run、声明决议在两轨道方法内且门后。
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow.run)
    assert "workflow.patched(SUITE_PATCH_ID)" in src
    assert 'workflow.patched(INSPECT_PATCH_ID)' in src, "分派门必须双门"
    # 新轨道整体在双门之后（run 分派保证），方法内无需再判门；legacy 轨内部混收
    # 新旧行为（SUITE 门 False 的老票），必须逐点判门——两条都锁。
    src_new = _inspect.getsource(flow.InspectionPeriodicWorkflow._run_inspect_period_flow)
    src_old = _inspect.getsource(flow._run_legacy_period_flow)
    assert '"resolve_inspection_plan"' in src_new
    assert "if wf._patched:" in src_old      # legacy 外提后 self→wf（模块级函数）
    idx_gate = src.index("self._patched = workflow.patched(SUITE_PATCH_ID)")
    assert idx_gate < src.index("_run_inspect_period_flow")
    blk = _inspect.getsource(flow.InspectionPeriodicWorkflow._blocked)
    # t260917-02（R7）：_blocked 增 write_ledger 开关（重定向失败路径不落账）——
    # 落账仍严格在 patched 门内，只是多了显式开关
    assert "if self._patched and write_ledger:" in blk
    assert _inspect.getsource(flow.InspectionPeriodicWorkflow.__init__).count("_patched") == 1


def test_replay_check_registers_inspection_workflows():
    """replay_check 必须注册巡检 workflow 族——旧版只注册 v2 模板族，巡检票重放被
    「not registered」挡回 = 巡检的 replay 安全检查是空的（本票实测踩到）。"""
    import replay_check
    names = {getattr(w, "__name__", "") for w in replay_check._replayer()._workflows} \
        if hasattr(replay_check._replayer(), "_workflows") else set()
    if not names:
        names = set(replay_check.TEMPLATE_TYPES)
    assert "InspectionPeriodicWorkflow" in names


def test_ledger_doc_carries_stage_machine_evidence():
    """落账文档必须自描述阶段机证据（列表可读面的 B1 口径）：stage/stage_state/status/
    timeline 四键在场，且不污染 workflow 快照的 face（timeline 只在落账里）。"""
    import inspect as _inspect
    src = _inspect.getsource(flow.InspectionPeriodicWorkflow._ledger_doc)
    for key in ("stage", "stage_state", "status", "timeline"):
        assert '"%s"' % key in src, key
    # 四处落账点都走 _ledger_doc（report 段 / 人门落点 / 收口 / blocked），不留裸 self.face 落账
    # t260916-22：落账点集中在 _finalize_and_close（两轨道共用；run 已薄分派）。
    fin_src = _inspect.getsource(flow.InspectionPeriodicWorkflow._finalize_and_close)
    run_src = _inspect.getsource(flow.InspectionPeriodicWorkflow.run)
    assert 'args=[self.face]' not in run_src and 'args=[self.face]' not in fin_src
    assert fin_src.count("_ledger_doc()") == 2      # report 段 + 收口
    assert "_write_ledger()" in fin_src             # 人门落点
    blk = _inspect.getsource(flow.InspectionPeriodicWorkflow._blocked)
    assert "_write_ledger()" in blk                 # blocked 落账（dead-man 列表可读面）


def test_ledger_doc_shape_is_writeable(tmp_path):
    """端到端形状：_ledger_doc 的产物能被落账实现写出并原样读回（含 timeline）。"""
    import json
    doc = {"ticket_id": "inspection-integration-tests-20260913", "kind": "inspection",
           "instance_id": "integration-tests", "period": "20260913",
           "heartbeat": False, "summary": {"high": 1}, "findings": [],
           "suggested_fix_tickets": [], "stage": "close", "stage_state": "awaiting-human",
           "status": "running",
           "timeline": [{"at": "2026-09-13T00:00:00+00:00", "stage": "setup",
                         "state": "running", "reason": "搭泳道"},
                        {"at": "2026-09-13T00:01:00+00:00", "stage": "close",
                         "state": "awaiting-human", "reason": "人审"}]}
    res = flow.write_inspection_report_impl(doc, tmp_path)
    got = json.loads(Path(res["path"]).read_text("utf-8"))
    assert got["stage"] == "close" and got["stage_state"] == "awaiting-human"
    assert [t["stage"] for t in got["timeline"]] == ["setup", "close"]


def test_suite_timeout_outlives_internal_deadline():
    """C5：workflow 的 start_to_close 必须大于 _run_scenarios 的内部截止，否则
    Temporal 先杀活动、活动内的超时清理永远走不到。"""
    from agent_activities import BATCH_TIMEOUT_SEC
    assert flow.SUITE_TO.total_seconds() > BATCH_TIMEOUT_SEC + 300
    assert flow.RETRY_SUITE.maximum_attempts == 1


def test_dev_lane_integ_run_to_outlives_internal_deadline():
    """开发泳道 run_integration_tests 的活动超时**必须 > 执行器内部截止**
    （BATCH_TIMEOUT_SEC + 300）——否则内层的结构化超时回报等不到，只剩 Temporal 硬杀
    （零回执、票面 ran=0）。合并注记（t260913-02 gen10 解冲突）：本票 gen1 曾把外层抬到
    120min（全集 wall 2349.6s 的实测口径）；main 侧 t260913-01 独立同修——把**内层缺省**
    收紧为 3000+300=3300s（正常套件 ≈25min，超窗交结构化回报）并保留外层 60min，随
    verify.yaml exclude_pools 生效后每票集测变轻（实测 wall 179.5s ≪ 60min）而成立。
    解冲突取 main 侧 60min（配对不变量 inner<outer 成立；只锁下界，不锁上界）；
    全集长墙钟口径在巡检侧 `flow.SUITE_TO`（恒全跑路径，两族预算独立；t260924-05
    KI-116 起两族均自 agent_activities.INTEG_GUARD_SEC 派生，手写 120min 退役）。"""
    import dev_lane
    from agent_activities import BATCH_TIMEOUT_SEC
    assert dev_lane.INTEG_RUN_TO.total_seconds() >= BATCH_TIMEOUT_SEC + 300
    # 与巡检侧 SUITE_TO 无从属关系（两族预算独立：per-ticket 集测轻量化后各自守面）


def test_input_shape_has_no_suite_switch_field():
    """套件开关不进 payload（决议读声明）；输入只多一个 defaulted decl_path
    （声明来源随票走，两向兼容：老 history 缺键→默认值；老 worker 收多键→忽略，
    实测 temporalio dataclass 解码忽略未知键）。"""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(flow.InspectionPeriodicInput)}
    # t260915-20 补键期望：project_key（实例级项目身份）进 payload——开关红线不变
    # t260925-09 补键期望：supersedes_ticket_id（终止票重开审计链接，KI-114）
    assert fields == {"instance_id", "face", "period", "repo_root", "scenarios_path",
                      "decl_path", "project_key", "supersedes_ticket_id"}
    assert not {"suite", "run_suite"} & fields      # 开关不在 payload（红线：不进 payload）
    inp = flow.InspectionPeriodicInput(instance_id="i")
    assert inp.face == "test" and inp.period == "" and inp.decl_path == ""
    assert inp.supersedes_ticket_id == ""           # 缺省空：正常起票/老 history 重放不炸


def test_activities_registered():
    import activities
    import agent_activities as aa
    names = {a.__name__ for a in activities.ALL_ACTIVITIES}
    assert {"resolve_inspection_plan", "run_inspection_deadman",
            "run_inspection_scan", "write_inspection_report"} <= names
    agent_names = {a.__name__ for a in aa.ALL_AGENT_ACTIVITIES}
    assert {"resolve_main_head", "sweep_inspection_lanes", "run_inspection_suite",
            "prepare_workspace", "teardown_lane"} <= agent_names


def test_decl_path_travels_with_trigger_but_not_schedule():
    """声明来源两处同源：trigger 把 --decl-path 随票传；**schedule-up 不传**（调度路径
    恒用 worker 缺省声明 → 「改声明即改行为」的调度语义不变）。"""
    import inspect as _inspect
    import inspection_trigger as trig
    tsrc = _inspect.getsource(trig.cmd_trigger)
    assert "decl_path=abs_decl_path(args.decl_path)" in tsrc
    ssrc = _inspect.getsource(trig.cmd_schedule_up)
    # cron 形态的建票输入**不钉**声明路径（调度每次触发读 worker 当前声明=改声明即改行为）；
    # 计数形态（watcher）钉路径（watcher 的实例集来自它启动时的那份声明）
    cron_block = ssrc[ssrc.index("client.create_schedule"):]
    assert "decl_path" not in cron_block
    wsrc = _inspect.getsource(trig._schedule_up_watcher)
    assert "decl_path=abs_decl_path(args.decl_path)" in wsrc
    # t260916-22：run 薄分派后，声明路径透传锚定两条轨道方法（两轨道都读声明）。
    for track_src in (_inspect.getsource(flow.InspectionPeriodicWorkflow._run_inspect_period_flow),
                      _inspect.getsource(flow._run_legacy_period_flow)):
        assert '"decl_path": inp.decl_path' in track_src


def test_abs_decl_path_normalization():
    """声明路径绝对化（实测缺陷回归）：trigger 的 --decl-path 由调用方 cwd 解析，而
    plan 活动在 worker 的 cwd 里读——相对路径必须归一成绝对，否则票被判「声明不可读」
    blocked（drill 实测形态）。"""
    import inspection_trigger as trig
    assert trig.abs_decl_path("") == "" and trig.abs_decl_path(None) == ""
    got = trig.abs_decl_path("out/drill/decl.yaml")
    assert got.startswith("/") and got.endswith("out/drill/decl.yaml")
    # macOS /tmp 是符号链接：比对 resolve 后的规范形，不锚平台别名
    from pathlib import Path as _P
    assert trig.abs_decl_path("/tmp/x.yaml") == str(_P("/tmp/x.yaml").resolve())


def test_trigger_paths_propagate_declaration_fields():
    """声明面必须一路透传：schedule-up 铸 cron 调度 action 时带 face/repo_root
    （t260913-02 顺手修的原缺陷；t260915-20 起铸点收拢进 _schedule_action 单点
    builder——create/update 两分支同源重铸，透传语义钉在 builder 源面上），
    且 CLI 提供 deadman / sweep-lanes 两个运维子命令。"""
    import inspect as _inspect
    import inspection_trigger as trig
    src_builder = _inspect.getsource(trig._schedule_action)
    assert "face=str(spec.get(\"scan_face\") or \"test\")" in src_builder
    assert "repo_root=resolve_repo_root(spec, explicit_repo_root)" in src_builder
    # update 分支同样重铸 action（t260915-20 R1：只改 spec/policy 刷不了 payload/SA）
    src_up = _inspect.getsource(trig.cmd_schedule_up)
    assert "_schedule_action(spec, TASK_QUEUE, args.repo_root)" in src_up
    for fn in ("cmd_deadman", "cmd_sweep_lanes"):
        assert hasattr(trig, fn)
    assert "deadman" in _inspect.getsource(trig.main)
    assert "sweep-lanes" in _inspect.getsource(trig.main)
