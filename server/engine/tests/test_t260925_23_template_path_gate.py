"""t260925-23 KI-124——外置模板段路径闸声明化：验收用例集（单测面）。

覆盖：
  - 声明化总开关：client.py 不再硬编码模板名（源码锁，`== "dev-lane"` 残留=红）；
    DevLaneWorkflow.PATH_GATE=True 源码锁（闸不得静默关）。
  - 规则解析：template_rules 生效、内建表兜底、成员判断（声明了假值规则**不**回落
    内建表，fail-closed）、畸形 rules 整体忽略（不放大）。
  - fail-closed 文案：unknown_stage 回执点名段 id、补法（PATH_GATE_RULES["<id>"]）
    与弱面白名单，不再是裸 unknown_stage。
  - 子集纪律交叉锁：模板侧深检白名单 == path_gates.TEMPLATE_WEAK_KINDS，且 ⊆ 内建
    表全 kind 词表（两表漂移=红）。
  - 加载口深检（模板级拒收）：键 ⊄ STAGES ids / kind 越面（强 kind）/ 死配置
    （RULES 在场但 PATH_GATE 非 True）/ prefixes 缺前缀表 / 合法声明放行。
  - 缺省回落零行为变化：不声明 PATH_GATE 的模板深检照常放行、gate 关。

夹具 = 临时注册根（注入 root 参数，不污染进程 env）；畸形输入全部本地桩复现，
不依赖任何外部源。
"""
import ast
import pathlib
import tempfile

import pytest

import path_gates as pg
import project_templates as pt
import shared
from shared import Stage

GOOD_TMPL = '''TEMPLATE_ID = "{tid}"
TEMPLATE_NAME = "{{disp}}"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class {cls}(TicketWorkflowBase):
    STAGES = (Stage(id="s1", name="一", role="developer", next="s2", acceptance=("a",)),
              Stage(id="s2", name="二", role="integration", next="", acceptance=("b",)))
    PATCH_ID = "{{patch}}"
    TEMPLATE_ID = "{tid}"
    TEMPLATE_NAME = "{{disp}}"{extra}

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
'''


def _project(root: pathlib.Path, key: str, modules: dict) -> pathlib.Path:
    pd = root / key
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: 测试项目\n    dirs:\n      - %s\n"
        "paths:\n  workflow_modules: %s\n"
        % (key, pd, ",".join("mods/%s" % m for m in modules)), "utf-8")
    (pd / "mods").mkdir(exist_ok=True)
    for fname, body in modules.items():
        (pd / "mods" / fname).write_text(body, "utf-8")
    return pd


@pytest.fixture(autouse=True)
def _restore_shared_tables():
    names = dict(shared.TEMPLATE_CLASS_NAMES)
    displays = dict(shared.TEMPLATE_DISPLAY_NAMES)
    rejs = list(shared.PROJECT_TEMPLATE_REJECTIONS)
    yield
    shared.TEMPLATE_CLASS_NAMES.clear()
    shared.TEMPLATE_CLASS_NAMES.update(names)
    shared.TEMPLATE_DISPLAY_NAMES.clear()
    shared.TEMPLATE_DISPLAY_NAMES.update(displays)
    shared.PROJECT_TEMPLATE_REJECTIONS.clear()
    shared.PROJECT_TEMPLATE_REJECTIONS.extend(rejs)


@pytest.fixture()
def empty_root():
    return pathlib.Path(tempfile.mkdtemp(prefix="t260925-23-"))


def _classes(root):
    res = shared.project_template_classes_merged(root=str(root))
    return getattr(res, "classes", res)


def _rejections(root):
    res = shared.project_template_scan(import_classes=True, root=str(root))
    return res.rejections


def _tmpl(extra: str = "", cls: str = "Flow", tid: str = "flow", **kw) -> str:
    body = GOOD_TMPL.format(cls=cls, tid=tid, extra=extra)
    return body


# ---- 源码锁：硬编码拆除 + dev-lane 声明在位 ----

def _class_attr_true(src: str, cls_name: str, attr: str) -> bool:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == attr for t in sub.targets):
                    return bool(getattr(ast.literal_eval(sub.value), "__bool__",
                                        lambda: True)())
    return False


def test_source_lock_client_has_no_hardcoded_gate():
    src = (pathlib.Path(__file__).resolve().parents[1] / "client.py").read_text("utf-8")
    assert 'path_gate=(str(tpl) == "dev-lane")' not in src, \
        "路径闸总开关不得硬编码模板名（KI-124）"
    assert 'getattr(cls, "PATH_GATE"' in src, "总开关须改读模板类声明"


def test_source_lock_dev_lane_declares_gate_on():
    src = (pathlib.Path(__file__).resolve().parents[1] / "dev_lane.py").read_text("utf-8")
    assert _class_attr_true(src, "DevLaneWorkflow", "PATH_GATE"), \
        "DevLaneWorkflow 须声明 PATH_GATE=True（闸不得静默关）"


# ---- 白名单交叉锁（两表漂移=红） ----

def test_weak_kinds_match_and_subset_of_builtin_vocab():
    assert pt._PATH_GATE_KINDS == tuple(pg.TEMPLATE_WEAK_KINDS)
    builtin_kinds = {r.get("kind") for r in pg.STAGE_PATH_RULES.values()}
    assert set(pg.TEMPLATE_WEAK_KINDS) <= builtin_kinds


# ---- 规则解析（judge 纯函数面，含畸形输入） ----

def test_template_rules_take_precedence_for_declared_stages():
    rules = {"s1": "write_set"}
    allowed, violations, reason = pg.judge_stage_paths(
        "s1", ["app/x.py"], write_set=["app"], template_rules=rules)
    assert (allowed, violations, reason) == (True, [], "")


def test_undeclared_external_stage_falls_back_then_fail_closed():
    # 内建表无此键、模板未声明 → unknown_stage（fail-closed 不变）
    allowed, violations, reason = pg.judge_stage_paths(
        "ext_stage", ["a.py"], write_set=["."], template_rules={"other": "write_set"})
    assert (allowed, reason) == (False, "unknown_stage")
    assert violations == ["a.py"]


def test_declared_falsy_rule_never_shadows_back_to_builtin():
    # 成员判断：声明了假值规则不得静默跌回内建表（falsy 遮蔽=装死）
    for bad in ("", {}, None, {"kind": ""}, {"kind": 7}):
        allowed, _v, reason = pg.judge_stage_paths(
            "create_plan", ["docs/x.md"], template_rules={"create_plan": bad})
        assert allowed is False and reason == "unknown_stage", \
            "声明假值规则须 fail-closed（输入=%r）" % (bad,)


def test_malformed_template_rules_ignored_fail_closed():
    # 畸形 rules（非 dict / None）整体忽略 → 回内建表语义，不放大
    for bad in (None, "write_set", 7, ["write_set"]):
        allowed, _v, reason = pg.judge_stage_paths(
            "create_plan", ["server/engine/x.py"], template_rules=bad)
        # create_plan 在内建表=仅结果文件：代码文件照旧判违规（语义不变）
        assert allowed is False and reason == "unauthorized_path"


def test_prefix_dict_form_rule():
    rules = {"integ": {"kind": "prefixes", "prefixes": ("integration",)}}
    allowed, _v, reason = pg.judge_stage_paths(
        "integ", ["integration/t1/sc_x.py"], template_rules=rules)
    assert (allowed, reason) == (True, "")


def test_unknown_stage_note_names_stage_and_remedy():
    note = pg.gate_refusal_note("ext_stage", ["a.py"], "unknown_stage")
    assert "unknown_stage" in note and pg.PATH_GATE_REASON_KEY in note
    assert "ext_stage" in note, "回执须点名缺规则的段"
    assert 'PATH_GATE_RULES["ext_stage"]' in note, "回执须点名补法"
    assert "result_files" in note, "回执须点名弱面白名单"
    assert "合法出路" in note, "出路文案在场（fail-closed 但给合法出路，对齐 faces 场景 A3）"


def test_next_action_hint_unknown_stage_names_remedy():
    hint = pg.next_action_hint("unknown_stage")
    assert "PATH_GATE_RULES" in hint


# ---- 加载口深检（模板级拒收） ----

def test_loader_accepts_well_declared_template(empty_root):
    extra = ('\n    PATH_GATE = True\n    PATH_GATE_RULES = {"s1": "write_set",\n'
             '                    "s2": {"kind": "prefixes", "prefixes": ("integration",)}}')
    _project(empty_root, "p1", {"ok.py": _tmpl(extra=extra)})
    classes = _classes(empty_root)
    assert "flow" in classes
    assert _rejections(empty_root) == []


def test_loader_rejects_rules_key_outside_stage_ids(empty_root):
    extra = ('\n    PATH_GATE = True\n    PATH_GATE_RULES = {"s1": "write_set",'
             '\n                    "ghost": "write_set"}')
    _project(empty_root, "p1", {"bad.py": _tmpl(extra=extra)})
    assert "flow" not in _classes(empty_root)
    rejs = _rejections(empty_root)
    assert any("子集" in r["detail"] or "越界键" in r["detail"] and "ghost" in r["detail"]
               for r in rejs if r["check"] == "畸形"), rejs


def test_loader_rejects_strong_kind(empty_root):
    extra = '\n    PATH_GATE = True\n    PATH_GATE_RULES = {"s1": "self_heal"}'
    _project(empty_root, "p1", {"bad.py": _tmpl(extra=extra)})
    assert "flow" not in _classes(empty_root)
    rejs = _rejections(empty_root)
    assert any("kind 非法" in r["detail"] and "self_heal" in r["detail"]
               for r in rejs if r["check"] == "畸形"), rejs


def test_loader_rejects_dead_config_rules_without_gate(empty_root):
    extra = '\n    PATH_GATE_RULES = {"s1": "write_set"}'
    _project(empty_root, "p1", {"bad.py": _tmpl(extra=extra)})
    assert "flow" not in _classes(empty_root)
    rejs = _rejections(empty_root)
    assert any("死配置" in r["detail"] for r in rejs if r["check"] == "畸形"), rejs


def test_loader_rejects_gate_true_with_missing_or_bad_rules(empty_root):
    for extra in ('\n    PATH_GATE = True',
                  '\n    PATH_GATE = True\n    PATH_GATE_RULES = "write_set"'):
        root = pathlib.Path(tempfile.mkdtemp(prefix="t260925-23-"))
        try:
            _project(root, "p1", {"bad.py": _tmpl(extra=extra)})
            assert "flow" not in _classes(root)
            rejs = _rejections(root)
            assert any("PATH_GATE_RULES" in r["detail"]
                       for r in rejs if r["check"] == "畸形"), rejs
        finally:
            pass


def test_loader_rejects_prefixes_without_prefix_table(empty_root):
    extra = '\n    PATH_GATE = True\n    PATH_GATE_RULES = {"s1": {"kind": "prefixes"}}'
    _project(empty_root, "p1", {"bad.py": _tmpl(extra=extra)})
    assert "flow" not in _classes(empty_root)
    rejs = _rejections(empty_root)
    assert any("prefixes" in r["detail"] for r in rejs if r["check"] == "畸形"), rejs


def test_loader_undeclared_template_zero_behavior_change(empty_root):
    _project(empty_root, "p1", {"ok.py": _tmpl()})
    assert "flow" in _classes(empty_root)
    assert _rejections(empty_root) == []
