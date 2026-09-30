# -*- coding: utf-8 -*-
"""t260930-02 变更面选择器·**执行器侧**（L1 单元层，被测=integration/run_scenarios.py
的 `--print-surface-plan` 面）。

分层（intent 分工，防重复；同目录三个文件的边界）：
  · 本文件 = 执行器侧机械判据与计划组装——路径归属/忽略判定、声明面加载三态、计划的
    全部 fail-closed 分支、console 标记派生、引用面与 **artifacts 派生**（改 src 连带
    改构建产物，只加载产物、不起控制台的场景族只按 console 判会整族漏掉=欠近似）；
  · `server/engine/tests/test_t260930_02_surface_plan.py`（引擎侧，同票并行件）=回执解析
    真值表、`surface_plan` 活动四态回全量、接线结构锁——本文件不重测；
  · `integration/t260930-02/sc_surface_plan_query.py`（L3）=真注册表 + 真子进程黑盒跑
    查询的端到端状态机——本文件不重测同一意图（只做夹具化的纯函数面与一条真榜自检）。

跑法：`server/engine/.venv/bin/python -m pytest server/engine/tests -q`（缺 venv 用任一
装 pytest 的解释器）。全程 stdlib + 临时目录夹具：零 docker、零 Temporal、零控制台
（红线：永不接触 3099）、零端口、零真跑——只读查询面自身不起任何场景。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]   # server/engine/tests → 仓根


def _rs():
    """按文件位装载被测执行器（不 import，避免 sys.path 侧效应污染同会话其他测试）。"""
    spec = importlib.util.spec_from_file_location(
        "_rs_under_test_t260930_02_query", REPO / "integration" / "run_scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RS = _rs()
DOC = json.loads((REPO / "integration" / "scenario-surfaces.json").read_text(encoding="utf-8"))
ALWAYS = list(DOC["always"])


# ---------------------------------------------------------------- 夹具

def _fake_doc(surfaces=None, always=None, ignored=None, max_surfaces=16, policy="夹具声明面"):
    """最小合法声明面（各段只改动被测那一维）。"""
    return {
        "meta": {"policy": policy, "max_surfaces": max_surfaces},
        "surfaces": surfaces if surfaces is not None else [
            {"id": "fake-panel", "paths": ["server/plugins/fake-panel/"],
             "artifacts": ["server/plugins/fake-panel/lib/"],
             "console": False, "names": []}],
        "always": ALWAYS if always is None else always,
        "ignored_paths": ["out/", ".sandbar/"] if ignored is None else ignored,
    }


def _fake_tree(tmp_path, files=None):
    """假仓树（只放夹具场景脚本，判据=脚本路径/正文里的路径串与标记串）。"""
    root = tmp_path / "tree"
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return str(root)


def _write_doc(tmp_path, obj, name="surfaces.json"):
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- A. 路径判定

def test_a1_prefix_hit_is_segment_wise_not_raw_string():
    """目录前缀按**段**判：server/plugins/ui/ 不得命中 server/plugins/ui-check/。"""
    assert RS._prefix_hit("server/plugins/ui/src/x.ts", ["server/plugins/ui/"]) == "server/plugins/ui"
    assert RS._prefix_hit("server/plugins/ui-check/src/x.ts", ["server/plugins/ui/"]) == ""
    assert RS._prefix_hit("server/plugins/ui", ["server/plugins/ui/"]) == "server/plugins/ui"


def test_a2_prefix_hit_normalizes_dot_slash_and_backslashes():
    assert RS._prefix_hit("./server/plugins/ui/x.ts", ["./server/plugins/ui/"]) != ""
    assert RS._prefix_hit("server\\plugins\\ui\\x.ts", ["server/plugins/ui/"]) != ""


def test_a3_ignored_paths_are_prefix_based():
    assert RS._prefix_hit("out/integration-report-1.json", ["out/"]) == "out"
    assert RS._prefix_hit("outbox/x", ["out/"]) == ""          # 段边界：不误吞 outbox/
    assert RS._prefix_hit(".sandbar/evidence/a.png", [".sandbar/"]) == ".sandbar"
    assert RS._prefix_hit("docs/x.md", ["out/", ".sandbar/"]) == ""


def test_a4_surface_lookup_returns_first_declared_match():
    doc = _fake_doc(surfaces=[
        {"id": "a", "paths": ["server/plugins/x/"], "artifacts": [], "console": False, "names": []},
        {"id": "b", "paths": ["server/plugins/x/src/"], "artifacts": [], "console": True, "names": []},
    ])
    assert RS._surface_of_path("server/plugins/x/src/y.ts", doc)["id"] == "a"
    assert RS._surface_of_path("server/plugins/y/z.ts", doc) is None


# ---------------------------------------------------------------- B. 声明面加载三态

def test_b1_real_declaration_loads_and_is_self_consistent():
    """真声明面：合法且有内容（policy 非空、面数在帽内、每面都有 artifacts 键）。"""
    doc, err = RS.load_surfaces_doc(str(REPO / "integration" / "scenario-surfaces.json"))
    assert err is None and doc is not None
    assert doc["meta"]["policy"].strip()
    assert len(doc["surfaces"]) <= doc["meta"]["max_surfaces"]
    for s in doc["surfaces"]:
        assert "artifacts" in s and isinstance(s["artifacts"], list)


def test_b2_missing_doc_is_named_error(tmp_path):
    doc, err = RS.load_surfaces_doc(str(tmp_path / "nope.json"))
    assert doc is None and err == "surface-doc-missing"


def test_b3_malformed_doc_variants_all_fail_closed(tmp_path):
    """畸形形态逐个点名（半张表不可信）：不是对象/缺 meta/坏 cap/空面表/
    缺 artifacts 键/console 非布尔/id 重名/超帽/always 非列表/names 含非串。"""
    good = _fake_doc()
    cases = {}
    bad_surfaces_type = dict(good)
    bad_surfaces_type["surfaces"] = "x"
    cases["surfaces-not-list"] = bad_surfaces_type
    no_meta = dict(good)
    no_meta.pop("meta")
    cases["no-meta"] = no_meta
    bad_policy = _fake_doc(policy="   ")
    cases["blank-policy"] = bad_policy
    bad_cap = _fake_doc(max_surfaces=0)
    cases["bad-cap"] = bad_cap
    cases["empty-surfaces"] = _fake_doc(surfaces=[])
    no_art = _fake_doc()
    no_art["surfaces"][0].pop("artifacts")
    cases["missing-artifacts"] = no_art
    bad_console = _fake_doc()
    bad_console["surfaces"][0]["console"] = "yes"
    cases["console-not-bool"] = bad_console
    cases["dup-id"] = _fake_doc(surfaces=[
        {"id": "a", "paths": ["server/plugins/a/"], "artifacts": [], "console": False, "names": []},
        {"id": "a", "paths": ["server/plugins/b/"], "artifacts": [], "console": False, "names": []}])
    over = _fake_doc(max_surfaces=1)
    over["surfaces"] = [{"id": "a", "paths": ["p/"], "artifacts": [], "console": False, "names": []},
                        {"id": "b", "paths": ["q/"], "artifacts": [], "console": False, "names": []}]
    cases["over-cap"] = over
    cases["always-not-list"] = _fake_doc(always="not-a-list")
    bad_names = _fake_doc()
    bad_names["surfaces"][0]["names"] = [1]
    cases["names-has-non-str"] = bad_names
    for label, obj in cases.items():
        path = _write_doc(tmp_path, obj, name="bad-%s.json" % label)
        assert RS.load_surfaces_doc(path) == (None, "surface-doc-malformed"), label
    p = tmp_path / "arr.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert RS.load_surfaces_doc(str(p)) == (None, "surface-doc-malformed")


def test_b4_broken_json_is_malformed(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json at all", encoding="utf-8")
    assert RS.load_surfaces_doc(str(p)) == (None, "surface-doc-malformed")


def test_b5_env_override_points_at_fixture_doc(tmp_path, monkeypatch):
    """env 覆盖=夹具/电池入口；相对路径按仓根解析（不按 cwd——cwd 是泳道副本时必须
    仍指向被验证树自己那份声明）。"""
    p = _write_doc(tmp_path, _fake_doc())
    monkeypatch.setenv(RS.SURFACES_DOC_ENV, p)
    assert RS.surfaces_doc_path() == p
    monkeypatch.setenv(RS.SURFACES_DOC_ENV, "does/not/exist.json")
    assert RS.surfaces_doc_path() == str(REPO / "does/not/exist.json")
    monkeypatch.delenv(RS.SURFACES_DOC_ENV, raising=False)
    assert RS.surfaces_doc_path() == str(REPO / "integration" / "scenario-surfaces.json")


# ---------------------------------------------------------------- C. 计划组装的 fail-closed 分支

def test_c1_empty_changed_list_is_full_no_changed_files():
    plan = RS.build_surface_plan([], _fake_doc())
    assert plan["mode"] == "full" and plan["reason"] == "no-changed-files"
    assert plan["names"] == [] and plan["expected"] == len(RS.SCENARIOS)


def test_c2_blank_entries_do_not_count_as_a_change():
    plan = RS.build_surface_plan(["", "   ", None], _fake_doc())
    assert plan["mode"] == "full" and plan["reason"] == "no-changed-files"


def test_c3_missing_doc_is_full_with_doc_error(tmp_path):
    doc, err = RS.load_surfaces_doc(str(tmp_path / "nope.json"))
    plan = RS.build_surface_plan(["server/plugins/fake-panel/src/x.ts"], doc, err)
    assert plan["mode"] == "full" and plan["reason"] == "surface-doc-missing"


def test_c4_unclassified_path_is_full_and_names_the_path():
    plan = RS.build_surface_plan(["verify.yaml"], _fake_doc())
    assert plan["mode"] == "full" and plan["reason"] == "unclassified-path:verify.yaml"
    assert plan["names"] == []


def test_c5_ignored_path_alone_still_targets_the_always_guards():
    """只剩运行产物域的改动=不构成改动面：定点面=always 守卫（绝不当「空跑全绿」，
    也绝不当全量）。"""
    plan = RS.build_surface_plan(["out/integration-report-1.json"], _fake_doc())
    assert plan["mode"] == "targeted" and plan["reason"] == "ok"
    assert plan["surfaces"] == [] and plan["names"] == sorted(set(ALWAYS))


def test_c6_scenario_asset_under_integration_is_full():
    """integration/** 是场景资产自身（共享面）：改动即全量，reason 走冻结词表
    （差别只在 notes 里点名「场景资产」——词表不另造 token）。"""
    for p in ("integration/run_scenarios.py", "integration/t260930-02/sc_x.py",
              "integration/lint_tests.py", "integration/scenario-surfaces.json"):
        plan = RS.build_surface_plan([p], _fake_doc())
        assert plan["mode"] == "full", p
        assert plan["reason"] == "unclassified-path:%s" % p, p
        assert plan["names"] == []
        assert any("场景资产" in n for n in plan["notes"]), p


def test_c7_unknown_selector_name_is_full_never_silently_skipped():
    """always 里的错名，与**未命中面** names 里的错名，都判 full（配置缺陷越早响亮越好）。"""
    plan = RS.build_surface_plan(["server/plugins/fake-panel/src/x.ts"],
                                 _fake_doc(always=["no-such-scenario"]))
    assert plan["mode"] == "full" and plan["reason"] == "unknown-selector"
    doc = _fake_doc(surfaces=[
        {"id": "other", "paths": ["server/plugins/other/"], "artifacts": [],
         "console": False, "names": ["also-not-registered"]}])
    plan = RS.build_surface_plan(["server/plugins/fake-panel/src/x.ts"], doc)
    assert plan["mode"] == "full" and plan["reason"] == "unknown-selector"


def test_c8_empty_result_set_is_full_empty_plan():
    """声明面里 always 为空、命中面也没有 names/引用面 → 名单为空=不放行（full）。"""
    doc = _fake_doc(always=[], surfaces=[
        {"id": "quiet", "paths": ["server/plugins/quiet/"], "artifacts": [],
         "console": False, "names": []}])
    plan = RS.build_surface_plan(["server/plugins/quiet/src/x.ts"], doc)
    assert plan["mode"] == "full" and plan["reason"] == "empty-plan"


def test_c9_first_unclassified_path_wins_and_is_named():
    """多条未声明路径：reason 点名第一条（人可追），notes 里给出全量条数。"""
    plan = RS.build_surface_plan(["server/engine/shared.py", "verify.yaml"], _fake_doc())
    assert plan["reason"] == "unclassified-path:server/engine/shared.py"
    assert any("verify.yaml" in n for n in plan["notes"])


def test_c10_targeted_plan_shape_is_frozen():
    """定点计划的键面与算术：键集恰为冻结契约、expected=len(names)、排序去重、
    每个名字都在册。"""
    plan = RS.build_surface_plan(["server/plugins/fake-panel/src/x.ts"], _fake_doc())
    assert set(plan) == {"mode", "reason", "surfaces", "names", "expected", "notes"}
    assert plan["mode"] == "targeted" and plan["reason"] == "ok"
    assert plan["expected"] == len(plan["names"])
    assert plan["names"] == sorted(set(plan["names"]))
    known = {e[0] for e in RS.SCENARIOS}
    assert all(n in known for n in plan["names"])


def test_c11_plan_is_pure_and_deterministic():
    """同一入参两次算出逐字节相同的计划（无隐藏状态漂移）。"""
    a = RS.build_surface_plan(["server/plugins/fake-panel/src/x.ts"], _fake_doc())
    b = RS.build_surface_plan(["server/plugins/fake-panel/src/x.ts"], _fake_doc())
    assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


def test_c12_mixed_ignored_and_classified_paths_keep_the_surface():
    """忽略路径不参与归类，但不影响其余路径的分类结果（也不报 unclassified）。"""
    plan = RS.build_surface_plan(["out/x.json", "server/plugins/fake-panel/src/x.ts"],
                                 _fake_doc())
    assert plan["mode"] == "targeted" and plan["surfaces"] == ["fake-panel"]


# ---------------------------------------------------------------- D. console 派生（假注册表）

def _reg(*entries):
    return list(entries)


def test_d1_marker_detected_over_closure_path(tmp_path):
    root = _fake_tree(tmp_path, {
        "scripts/uses_stage.mjs": "import { x } from './lib_stage_console.mjs'\n",
    })
    reg = _reg(("sc-stage", "夹具", "node scripts/uses_stage.mjs", "ro"),
               ("sc-plain", "夹具", "python3 scripts/plain.py", "ro"))
    assert RS.console_booting_names(reg, root) == ["sc-stage"]


def test_d2_marker_detected_over_closure_text(tmp_path):
    """标记在**被 import 的共享助手正文里**（起台单点就那么被调）也算——这条正是
    「只认文件路径」会漏的形态。"""
    root = _fake_tree(tmp_path, {
        "scripts/a.mjs": "import { h } from './helper.mjs'\nh()\n",
        "scripts/helper.mjs": "export function h(){ spawn('integration/stage_docker.py') }\n",
    })
    reg = _reg(("sc-via-helper", "夹具", "node scripts/a.mjs", "ro"))
    assert RS.console_booting_names(reg, root) == ["sc-via-helper"]


def test_d3_browser_pools_count_as_console_without_any_marker(tmp_path):
    root = _fake_tree(tmp_path, {"scripts/plain.py": "print(1)\n"})
    reg = _reg(("sc-browser", "夹具", "python3 scripts/plain.py", "browser"),
               ("sc-browser-free", "夹具", "python3 scripts/plain.py", "browser-free"),
               ("sc-ro", "夹具", "python3 scripts/plain.py", "ro"))
    assert RS.console_booting_names(reg, root) == ["sc-browser", "sc-browser-free"]


def test_d4_no_marker_no_pool_means_not_console(tmp_path):
    root = _fake_tree(tmp_path, {"scripts/plain.py": "print('hello')\n"})
    reg = _reg(("sc-plain", "夹具", "python3 scripts/plain.py", "ro"))
    assert RS.console_booting_names(reg, root) == []


def test_d5_runner_declaration_text_is_not_evidence(tmp_path):
    """自引用守卫：执行器自身正文里列着全仓路径与全部标记名，拿它当「消费证据」等于
    恒真——只扫它的路径不扫正文。"""
    root = _fake_tree(tmp_path, {
        "integration/run_scenarios.py": "CONSOLE = 'stage_docker lib_stage_console'\n",
        "scripts/importer.py": "import run_scenarios\n",
    })
    reg = _reg(("sc-imports-runner", "夹具", "python3 scripts/importer.py", "ro"))
    assert RS.console_booting_names(reg, root) == []


def test_d6_markers_over_cmd_text_count(tmp_path):
    root = _fake_tree(tmp_path, {"scripts/plain.py": "print(1)\n"})
    reg = _reg(("sc-cmd-stage", "夹具",
                "sh -c 'bash integration/with_stage.sh python3 scripts/plain.py'", "ro"))
    assert RS.console_booting_names(reg, root) == ["sc-cmd-stage"]


# ---------------------------------------------------------------- E. 引用面 + artifacts 派生

def test_e1_changed_path_reference_pulls_the_consumer_in(tmp_path):
    root = _fake_tree(tmp_path, {
        "scripts/reads_src.py": "SRC = 'server/plugins/fake-panel/src/widget.ts'\n",
        "scripts/unrelated.py": "print('nothing here')\n",
    })
    reg = _reg(("sc-reads-src", "夹具", "python3 scripts/reads_src.py", "ro"),
               ("sc-unrelated", "夹具", "python3 scripts/unrelated.py", "ro"))
    got = RS.names_referencing_paths(["server/plugins/fake-panel/src/widget.ts"], reg, root)
    assert got == ["sc-reads-src"]


def test_e2_bare_directory_needle_needs_a_word_boundary(tmp_path):
    """词尾边界：短前缀不得把**别的名字**（notes-write-gate 之于 notes）算成命中。"""
    root = _fake_tree(tmp_path, {
        "scripts/other.py": "NAME = 'notes-write-gate'\n",
        "scripts/really.py": "P = os.path.join('notes', 'x.md')\n",
    })
    reg = _reg(("sc-name-noise", "夹具", "python3 scripts/other.py", "ro"),
               ("sc-real", "夹具", "python3 scripts/really.py", "ro"))
    assert RS.names_referencing_paths(["notes/"], reg, root) == ["sc-real"]


def test_e3_artifacts_derivation_pulls_bundle_consumers_in(tmp_path):
    """**本票欠近似缺口的回归用例**：改 surface 的 src → 该面的 artifacts（构建产物）
    前缀算派生改动路径 → 只加载/解析产物、从不起控制台的场景必须被纳入。
    本例 surface 的 console=False，且没有任何场景引用被改的 src 路径——故该场景
    只能由 artifacts 派生拿到（三路归零再点亮的自证写法）。"""
    root = _fake_tree(tmp_path, {
        "scripts/bundle_loader.mjs": "const p = 'server/plugins/fake-panel/lib/client.js'\n",
        "scripts/nothing.mjs": "console.log('x')\n",
    })
    reg = _reg(("sc-bundle-loader", "夹具（只读产物，不起控制台）",
                "node scripts/bundle_loader.mjs", "ro"),
               ("sc-nothing", "夹具", "node scripts/nothing.mjs", "ro"))
    doc = _fake_doc(always=[], surfaces=[
        {"id": "fake-panel", "paths": ["server/plugins/fake-panel/"],
         "artifacts": ["server/plugins/fake-panel/lib/"],
         "console": False, "names": []}])
    # 前提自证：console 面与 src 引用面都拿不到它（否则本用例证明不了产物派生）。
    assert RS.console_booting_names(reg, root) == []
    assert RS.names_referencing_paths(["server/plugins/fake-panel/src/widget.ts"],
                                      reg, root) == []
    plan = RS.build_surface_plan(["server/plugins/fake-panel/src/widget.ts"], doc,
                                 registry=reg, repo_root=root)
    assert plan["mode"] == "targeted", plan
    assert "sc-bundle-loader" in plan["names"]      # ← 产物派生把它捞回来了
    assert "sc-nothing" not in plan["names"]
    assert any("fake-panel/lib/" in n for n in plan["notes"])


def test_e4_surface_without_artifacts_must_say_so_explicitly(tmp_path):
    """「有 paths 但产物面判不出」不静默：artifacts 键缺席=声明面畸形=full；
    显式 []（无产物面）=合法，只按声明走。"""
    doc = _fake_doc(always=[], surfaces=[
        {"id": "no-build", "paths": ["server/plugins/no-build/"],
         "console": False, "names": []}])
    p = _write_doc(tmp_path, doc)
    assert RS.load_surfaces_doc(p) == (None, "surface-doc-malformed")
    ok_doc = _fake_doc(always=[], surfaces=[
        {"id": "no-build", "paths": ["server/plugins/no-build/"], "artifacts": [],
         "console": False, "names": ["t260904-02-doctor-zombie"]}])
    plan = RS.build_surface_plan(["server/plugins/no-build/src/x.ts"], ok_doc)
    assert plan["mode"] == "targeted"
    assert plan["names"] == ["t260904-02-doctor-zombie"]


def test_e5_matched_surface_names_are_added(tmp_path):
    doc = _fake_doc(always=[], surfaces=[
        {"id": "s", "paths": ["server/plugins/s/"], "artifacts": [],
         "console": False, "names": ["t260904-02-doctor-zombie"]}])
    plan = RS.build_surface_plan(["server/plugins/s/src/x.ts"], doc)
    assert plan["names"] == ["t260904-02-doctor-zombie"]


def test_e6_console_surface_pulls_the_console_set_and_reports_it(tmp_path):
    root = _fake_tree(tmp_path, {"scripts/a.mjs": "import '../lib_stage_console.mjs'\n"})
    reg = _reg(("sc-console", "夹具", "node scripts/a.mjs", "ro"),
               ("sc-plain", "夹具", "python3 scripts/plain.py", "ro"))
    doc = _fake_doc(always=[], surfaces=[
        {"id": "ui", "paths": ["server/plugins/ui/"], "artifacts": [],
         "console": True, "names": []}])
    plan = RS.build_surface_plan(["server/plugins/ui/src/x.ts"], doc,
                                 registry=reg, repo_root=root)
    assert plan["mode"] == "targeted" and plan["names"] == ["sc-console"]
    assert any("console" in n for n in plan["notes"])


def test_e7_non_console_surface_does_not_drag_the_console_set_in(tmp_path):
    """反向对照（防「console 面判定恒真」的假绿）：console=false 的面不得把控制台族
    拉进来——否则「谁起控制台」这条判据等于没判。"""
    root = _fake_tree(tmp_path, {
        "scripts/a.mjs": "import '../lib_stage_console.mjs'\n",
        "scripts/plain.mjs": "console.log('x')\n",
    })
    reg = _reg(("sc-console", "夹具", "node scripts/a.mjs", "ro"),
               ("sc-quiet", "夹具", "node scripts/plain.mjs", "ro"))
    doc = _fake_doc(always=[], surfaces=[
        {"id": "quiet", "paths": ["server/plugins/quiet/"], "artifacts": [],
         "console": False, "names": []}])
    plan = RS.build_surface_plan(["server/plugins/quiet/src/x.ts"], doc,
                                 registry=reg, repo_root=root)
    # 无 always、无 names、无引用面 → 空名单 → full（不放行）；关键是 console 族不入面。
    assert plan["mode"] == "full" and plan["reason"] == "empty-plan"


# ---------------------------------------------------------------- F. 真声明面自洽（真注册表）

def test_f1_always_names_all_exist_in_the_real_registry():
    """always 每条都必须在册（错名=unknown-selector=full，绝不静默跳过）——真榜自检。"""
    known = {e[0] for e in RS.SCENARIOS}
    assert [n for n in ALWAYS if n not in known] == []


def test_f2_surface_names_all_exist_in_the_real_registry():
    known = {e[0] for e in RS.SCENARIOS}
    assert [n for s in DOC["surfaces"] for n in s["names"] if n not in known] == []


def test_f3_always_entries_stay_on_the_cheap_offline_side():
    """always 只收「不起产品面」的守卫：不得来自 browser/browser-free（起隔离台）与
    engine（起 docker 舞台）两族——它们贵且依赖供给，放进来会把每轮定点拖成环境红。"""
    by = {e[0]: e for e in RS.SCENARIOS}
    bad = [n for n in ALWAYS if RS.pool_of(by[n]) in ("browser", "browser-free", "engine")]
    assert bad == [], bad


def test_f4_real_declaration_covers_every_plugin_dir_on_disk():
    """声明面不得漏插件目录：server/plugins/ 下每个目录都要被某个 surface 覆盖
    （新插件落地忘了声明=该面改动恒 unclassified=full；本条把它变成显式红）。"""
    plugin_dirs = sorted(p.name for p in (REPO / "server" / "plugins").iterdir()
                         if p.is_dir())
    declared = set()
    for s in DOC["surfaces"]:
        for p in s["paths"]:
            if p.startswith("server/plugins/"):
                declared.add(p.split("/")[2])
    assert plugin_dirs, "server/plugins 下没有目录（判据面失效）"
    assert set(plugin_dirs) == declared, (sorted(set(plugin_dirs) - declared),
                                          sorted(declared - set(plugin_dirs)))


def test_f5_artifact_prefixes_match_the_real_build_scripts():
    """有构建产物（lib/client.js）的插件面必须声明产物前缀；无构建的插件面显式 []。
    判据机械取自 package.json 的 build 脚本 + lib/ 实况（防手抄漂移）。"""
    by_id = {s["id"]: s for s in DOC["surfaces"]}
    arts_of = lambda name: sorted(a for s in by_id.values() for a in s["artifacts"]
                                  if a.startswith("server/plugins/%s/" % name))
    for name in ("workbench", "ui", "knowledge", "providers"):
        pkg = json.loads((REPO / "server" / "plugins" / name / "package.json")
                         .read_text(encoding="utf-8"))
        assert "build" in (pkg.get("scripts") or {}), name
        assert (REPO / "server" / "plugins" / name / "lib" / "client.js").is_file(), name
        assert arts_of(name) == ["server/plugins/%s/lib/" % name], (name, arts_of(name))
    for name in ("watchdog", "temporal-tools", "executor-panel"):
        pkg = json.loads((REPO / "server" / "plugins" / name / "package.json")
                         .read_text(encoding="utf-8"))
        assert "build" not in (pkg.get("scripts") or {}), name
        assert arts_of(name) == [], (name, arts_of(name))


def test_f6_workbench_src_change_includes_the_bundle_consumers_on_the_real_registry():
    """真注册表上的欠近似缺口钉：改 workbench/src/** 时，**只加载产物、不起控制台**的
    场景（bundle 装载/构建门）必须在名单里（console 面之外的产物派生）。"""
    plan = RS.build_surface_plan(["server/plugins/workbench/src/client/theme.ts"], DOC)
    assert plan["mode"] == "targeted" and plan["surfaces"] == ["workbench-ui"]
    console = set(RS.console_booting_names())
    for name in ("t260903-13-workbench-bundle-loads", "t260902-05-t06-ui-build-gate"):
        assert name in plan["names"], name
        assert name not in console, ("该场景本就不起控制台，只能靠产物派生拿到：", name)
    assert set(ALWAYS) <= set(plan["names"])


def test_f7_plugin_scoped_plans_are_strictly_narrower_than_full():
    """经济性主张本体：插件面改动算出的定点名单必须**真比全量窄**（防「定点=换皮全量」），
    且仍是过近似（含 always 全量守卫）。"""
    total = len(RS.SCENARIOS)
    for s in DOC["surfaces"]:
        sample = s["paths"][0] + "src/x.ts"
        plan = RS.build_surface_plan([sample], DOC)
        assert plan["mode"] == "targeted", (s["id"], plan["reason"])
        assert 0 < len(plan["names"]) < total, (s["id"], len(plan["names"]))
        assert set(ALWAYS) <= set(plan["names"]), s["id"]


def test_f8_non_console_plugin_surfaces_still_cover_their_own_scenarios():
    """非 console 插件面（watchdog / temporal-tools）不得只剩 always：靠「引用面」
    把驱动该插件的在册场景整族带上（否则=欠近似）。"""
    plan = RS.build_surface_plan(["server/plugins/watchdog/src/x.ts"], DOC)
    assert plan["mode"] == "targeted"
    wd = [n for n in plan["names"] if n.startswith("t260928-28-watchdog")
          or n.startswith("t260929-08-watchdog")]
    assert len(wd) >= 8, wd
    plan2 = RS.build_surface_plan(["server/plugins/temporal-tools/node.ts"], DOC)
    assert set(ALWAYS) < set(plan2["names"])       # 严格超集：至少多出自己那条


def test_f9_console_face_is_derived_and_declared_surfaces_are_marked_console():
    """console 面=机械派生（非手写名单），且「会改控制台渲染的插件面」都被标了
    console=true（漏标=该面改动不进控制台族=欠近似）。"""
    console = RS.console_booting_names()
    by_id = {s["id"]: s for s in DOC["surfaces"]}
    for sid in ("workbench-ui", "executor-panel", "admin-ui", "knowledge-plugin",
                "providers-plugin"):
        assert by_id[sid]["console"] is True, sid
    for sid in ("watchdog", "temporal-tools", "docs-kb", "notes-kb"):
        assert by_id[sid]["console"] is False, sid
    assert len(console) > 50, len(console)          # 派生面非空转（假绿防线）
    assert len(console) < len(RS.SCENARIOS)


# ---------------------------------------------------------------- G. 改动清单入参解析

def test_g1_csv_and_file_forms(tmp_path):
    csv = "a/b.ts, c/d.ts\n e/f.ts"
    paths, src = RS._read_changed_files(csv)
    assert paths == ["a/b.ts", "c/d.ts", "e/f.ts"] and "CSV" in src
    lst = tmp_path / "changed.txt"
    lst.write_text("# 注释行\nserver/plugins/ui/src/x.ts\n\nnotes/x.md\n", encoding="utf-8")
    paths, src = RS._read_changed_files(str(lst))
    assert paths == ["server/plugins/ui/src/x.ts", "notes/x.md"] and "文件" in src


def test_g2_existing_source_file_argument_is_a_single_changed_path():
    """歧义形态（入参正好是一个存在的**源码文件**，如引擎按单条路径传参时）：
    当单个改动路径，绝不当清单读——否则源码正文会炸成一堆垃圾 token
    （实测 400+ 条噪音里编不出任何可信面）。"""
    src = str(REPO / "integration" / "run_scenarios.py")
    paths, note = RS._read_changed_files(src)
    assert paths == [src] and "单个改动路径" in note


def test_g3_empty_argument_is_empty_list():
    assert RS._read_changed_files("")[0] == []


def test_g4_engine_side_invocation_shape_is_accepted():
    """消费方（引擎 surface_plan 活动）的实调形态=**逗号拼串**：必须被当 CSV 收下，
    且与逐条传入算出同一计划。"""
    files = ["server/plugins/workbench/src/client/theme.ts",
             "server/plugins/watchdog/src/x.ts"]
    paths, note = RS._read_changed_files(",".join(files))
    assert paths == files and "CSV" in note
    assert (RS.build_surface_plan(files, DOC)["names"]
            == RS.build_surface_plan(paths, DOC)["names"])


# ---------------------------------------------------------------- H. CLI 面（不起场景、不占锁）

def _run_cli(args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env.pop("SANDBAR_SCENARIO_SURFACES", None)
    env.update({k: str(v) for k, v in (env_extra or {}).items()})
    return subprocess.run([sys.executable, "integration/run_scenarios.py", *args],
                          cwd=str(cwd or REPO), capture_output=True, text=True,
                          timeout=180, env=env)


def test_h1_cli_prints_exactly_one_json_line_and_exits_zero():
    p = _run_cli(["--print-surface-plan", "server/plugins/workbench/src/client/theme.ts"])
    assert p.returncode == 0, p.stderr[-500:]
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, lines[:3]
    plan = json.loads(lines[0])
    assert plan["mode"] == "targeted" and plan["reason"] == "ok"
    assert set(ALWAYS) <= set(plan["names"])


def test_h2_cli_full_states_still_exit_zero_and_say_why():
    """full 也退出 0（判定在 JSON 的 mode/reason 里），且 reason 具名。"""
    for arg, mode, reason in (
            ("integration/run_scenarios.py", "full",
             "unclassified-path:integration/run_scenarios.py"),
            ("verify.yaml", "full", "unclassified-path:verify.yaml"),
            ("", "full", "no-changed-files")):
        p = _run_cli(["--print-surface-plan", arg])
        assert p.returncode == 0, p.stderr[-300:]
        plan = json.loads(p.stdout.strip().splitlines()[-1])
        assert (plan["mode"], plan["reason"]) == (mode, reason), (arg, plan)
        assert plan["names"] == [] and plan["expected"] == len(RS.SCENARIOS)


def test_h3_cli_does_not_take_the_run_lock(tmp_path):
    """只读查询面**不占同泳道单飞锁**（与 --print-pool-assets 同类）：锁档路径指到
    临时区后，本查询跑完不得造出锁档。"""
    lock = tmp_path / "run.lock"
    p = _run_cli(["--print-surface-plan", "server/plugins/watchdog/src/x.ts"],
                 env_extra={"SANDBAR_INTEG_RUN_LOCK_PATH": str(lock)})
    assert p.returncode == 0, p.stderr[-300:]
    assert not lock.exists(), "查询面占了单飞锁（闸会被挡出）"


def test_h4_cli_does_not_start_any_scenario():
    """不起任何场景：给一个必然被命中的插件面，stdout 只有那一行 JSON——
    没有任何 PASS/FAIL 规范行、没有汇总行。"""
    p = _run_cli(["--print-surface-plan", "server/plugins/workbench/src/client/theme.ts"])
    assert "PASS [" not in p.stdout and "FAIL [" not in p.stdout
    assert "INTEG_SUMMARY" not in p.stdout and "SCENARIOS ran=" not in p.stdout


def test_h5_cli_env_override_selects_the_fixture_doc(tmp_path):
    """声明面可换（夹具/电池入口）：env 指向不存在的文件 ⇒ 具名 full（绝不回落默认面）。"""
    p = _run_cli(["--print-surface-plan", "server/plugins/workbench/src/client/theme.ts"],
                 env_extra={"SANDBAR_SCENARIO_SURFACES": str(tmp_path / "nope.json")})
    plan = json.loads(p.stdout.strip().splitlines()[-1])
    assert p.returncode == 0 and plan["mode"] == "full"
    assert plan["reason"] == "surface-doc-missing"


def test_h6_marker_set_is_the_declared_five():
    """标记集冻结自证（改判据必须同批改模块头注与本断言）。"""
    assert RS.CONSOLE_MARKERS == ("lib_stage_console", "stage_console", "bench_console",
                                  "with_stage.sh", "stage_docker")
    assert RS.CONSOLE_POOLS == ("browser", "browser-free")
    assert RS.PLAN_REASON_TOKENS == ("ok", "no-changed-files", "unclassified-path",
                                     "surface-doc-missing", "surface-doc-malformed",
                                     "unknown-selector", "empty-plan")


def test_h7_every_reason_the_code_emits_is_in_the_frozen_vocabulary():
    """全分支 reason 词表自证：每一态都必须落在冻结词表内（消费方按它分派）。"""
    for ch in ([], ["verify.yaml"], ["integration/run_scenarios.py"], ["out/x"]):
        plan = RS.build_surface_plan(ch, _fake_doc())
        assert plan["reason"].split(":", 1)[0] in RS.PLAN_REASON_TOKENS, plan["reason"]
    quiet = _fake_doc(always=[], surfaces=[
        {"id": "quiet", "paths": ["server/plugins/quiet/"], "artifacts": [],
         "console": False, "names": []}])
    for ch, doc, err in (
            ([], None, "surface-doc-missing"),
            ([], None, "surface-doc-malformed"),
            (["server/plugins/fake-panel/src/x.ts"], _fake_doc(always=["nope"]), None),
            (["server/plugins/quiet/src/x.ts"], quiet, None)):
        plan = RS.build_surface_plan(ch, doc, err)
        assert plan["reason"].split(":", 1)[0] in RS.PLAN_REASON_TOKENS, plan


def test_h8_new_assets_carry_no_retired_terminology_and_no_retired_name():
    """新资产不得引入废止术语与退役标识（L7 家族自证；真源=docs/terminology.md）。

    执行器整文件不做退役标识扫描：它正文里的存量旧标识是历史欠账（按专门迁移票处置，
    本票不碰）。故对执行器只扫**本票新增段**（变更面选择器一节）。"""
    banned = "\u817f"          # 按义替换表已废止的旧行话（chr 构词防自咬）
    retired = "su" + "you"     # 退役标识：拼接构词，断言自身不得构成命中（自引用免疫）
    for rel in ("integration/scenario-surfaces.json",
                "integration/t260930-02/sc_surface_plan_query.py",
                "server/engine/tests/test_t260930_02_surface_plan_query.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert banned not in text, rel
        assert retired not in text, rel
    runner = (REPO / "integration" / "run_scenarios.py").read_text(encoding="utf-8")
    head, sep, tail = runner.partition("t260930-02：变更面选择器")
    assert sep, "执行器里找不到本票新增段锚（判据面失效）"
    section = tail.split("def reprobe_main", 1)[0]
    assert banned not in section
    assert retired not in section, section[:200]
