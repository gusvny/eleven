"""t260925-01 票：产出型巡检纯函数契约层单测（inspection_produce）。

覆盖（方案步2）：
  - 围栏解析强 schema（末尾恰一块；坏 JSON/多围栏缺围栏/changes 非列表/path 畸形/
    .. 逃逸/action 词表外/zero_change 非布尔 逐形态 fail-closed——消费外部输入钩子
    的畸形输入用例）；
  - id 机械铸造（同内容跨期稳定，id 不由 agent 提供）；
  - 写集闸（A2）：越界/绝对/.. 逃逸逐条点名，docs_root 内放行；
  - 保护面闸（A3）：交集点名、前缀命中、不硬失败；
  - 零 change 闸（A5）：证据缺空/与 changes 并存/形态非法逐红；含 review v2 附条件②
    口径（文档自检红不混入零 change 判定）；
  - 文档自检三查：索引双向、frontmatter 词法、显式引用存在性+越根点名（tmp 仓真
    文件夹具，不靠真外部源）；规则集可声明（附条件①：换规则集即换行为）；
  - 受限可写 pin：workspace-write 形态 + docs_root 进描述（A4：与只读钉形态可辨）；
  - 人审门/授权门载荷校验：agent 自签拒、gate 串门拒、授权清单越集拒。
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_produce as prod  # noqa: E402

GOOD_FENCE = """前言可有人话。
```json
{"changes": [{"path": "docs/a.md", "action": "modify", "summary": "补链接"}],
 "zero_change": false, "evidence": []}
```"""


# ---------- 围栏解析 ----------

def test_parse_good_and_ignores_prose():
    out = prod.parse_agent_changes(GOOD_FENCE)
    assert out["changes"] == [{"path": "docs/a.md", "action": "modify",
                               "summary": "补链接"}]
    assert out["zero_change"] is False and out["evidence"] == []


def test_parse_zero_change_explicit():
    text = ('```json\n{"changes": [], "zero_change": true,'
            ' "evidence": ["全库索引一致，链接零烂"]}\n```')
    out = prod.parse_agent_changes(text)
    assert out["zero_change"] is True and out["changes"] == []
    assert out["evidence"] == ["全库索引一致，链接零烂"]


@pytest.mark.parametrize("text,why", [
    ("没有围栏", "围栏"),
    ("```json\n{}\n```", "changes"),
    ("```json\nnot json\n```", "解析失败"),
    ("```json\n[]\n```", "映射"),
    ('```json\n{"changes": "x", "zero_change": false}\n```', "非列表"),
    ('```json\n{"changes": [{"path": "/etc/passwd", "action": "modify", "summary": "s"}],'
     ' "zero_change": false}\n```', "畸形"),
    ('```json\n{"changes": [{"path": "../x.md", "action": "modify", "summary": "s"}],'
     ' "zero_change": false}\n```', "越根"),
    ('```json\n{"changes": [{"path": "docs/a.md", "action": "rewrite", "summary": "s"}],'
     ' "zero_change": false}\n```', "词表外"),
    ('```json\n{"changes": [{"path": "docs/a.md", "action": "modify", "summary": ""}],'
     ' "zero_change": false}\n```', "summary"),
    ('```json\n{"changes": [], "zero_change": "yes"}\n```', "布尔"),
    ('```json\n{"changes": [], "zero_change": true, "evidence": 3}\n```', "字符串列表"),
])
def test_parse_malformed_fail_closed(text, why):
    with pytest.raises(prod.ProduceParseError) as ei:
        prod.parse_agent_changes(text)
    assert why in str(ei.value)


def test_mint_ids_stable_and_agent_free():
    chs = [{"path": "docs/a.md", "action": "modify", "summary": "s"}]
    a = prod.mint_change_ids(chs)
    b = prod.mint_change_ids([dict(chs[0], summary="别的摘要")])
    assert a[0]["id"] == b[0]["id"] and len(a[0]["id"]) == 12


# ---------- 写集闸（A2） ----------

def test_write_set_in_root_passes():
    assert prod.check_write_set(["docs", "docs/a.md", "docs/sub/b.md"], "docs") == []


def test_write_set_out_of_root_named():
    hits = prod.check_write_set(
        ["docs/a.md", "server/engine/x.py", "integration/sc.py", "notes/t.md",
         "../escape.md", "/abs/path.md"], "docs")
    named = {h["path"] for h in hits}
    assert named == {"server/engine/x.py", "integration/sc.py", "notes/t.md",
                     "../escape.md", "/abs/path.md"}
    assert all(h["reason"] for h in hits)


def test_write_set_empty_root_fail_closed():
    with pytest.raises(prod.SelfcheckError):
        prod.check_write_set(["docs/a.md"], "  ")


# ---------- 保护面闸（A3） ----------

def test_protected_overlap_named_not_failed():
    hits = prod.check_protected_overlap(
        ["docs/design/x.md", "docs/a.md", "docs/design/sub/y.md"],
        ["docs/design", "server/roles"])
    assert hits == ["docs/design", "docs/design/sub/y.md", "docs/design/x.md"]


def test_protected_no_overlap_empty():
    assert prod.check_protected_overlap(["docs/a.md"], ["docs/design"]) == []


# ---------- 零 change 闸（A5） ----------

def test_zero_change_without_evidence_red():
    assert "evidence" in prod.check_zero_change([], True, [])


def test_zero_change_with_changes_red():
    assert "造假" in prod.check_zero_change([{"path": "docs/a.md"}], True, ["x"])


def test_zero_change_false_without_changes_red():
    assert prod.check_zero_change([], False, []) != ""


def test_zero_change_explicit_green():
    assert prod.check_zero_change([], True, ["索引一致"]) == ""
    assert prod.check_zero_change([{"path": "docs/a.md"}], False, []) == ""


# ---------- 文档自检（tmp 仓夹具） ----------

@pytest.fixture()
def doc_repo(tmp_path):
    (tmp_path / "docs" / "sub").mkdir(parents=True)
    (tmp_path / "docs" / "a.md").write_text(
        "---\ntitle: A\ncategory: design\ntags: [x]\nstatus: active\n"
        "updated: 2026-09-25\n---\n\n# A\n见 [b](sub/b.md) 与 `docs/ghost.md`。\n",
        encoding="utf-8")
    (tmp_path / "docs" / "sub" / "b.md").write_text(
        "---\ntitle: B\ncategory: design\ntags: [x]\nstatus: active\n"
        "updated: 2026-09-25\n---\n\n# B\n", encoding="utf-8")
    (tmp_path / "docs" / "index.json").write_text(
        '{"docs": [{"path": "docs/a.md"}, {"path": "docs/sub/b.md"},'
        ' {"path": "docs/ghost.md"}]}', encoding="utf-8")
    return tmp_path


def test_doc_selfcheck_ghost_and_missing_ref(doc_repo):
    finds = prod.doc_selfcheck(doc_repo, "docs")
    by = {(f["check"], f["path"]) for f in finds}
    assert ("index", "docs/ghost.md") in by          # 幽灵条目
    assert ("ref", "docs/a.md") in by                # 引用 docs/ghost.md 不存在


def test_doc_selfcheck_green_repo(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text(
        "---\ntitle: A\ncategory: design\ntags: [x]\nstatus: active\n"
        "updated: 2026-09-25\n---\n# A\n", encoding="utf-8")
    (tmp_path / "docs" / "index.json").write_text(
        '{"docs": [{"path": "docs/a.md"}]}', encoding="utf-8")
    assert prod.doc_selfcheck(tmp_path, "docs") == []


def test_doc_selfcheck_frontmatter_and_escape(doc_repo):
    (doc_repo / "docs" / "bad.md").write_text("no fm, ref ../outside.md\n", encoding="utf-8")
    (doc_repo / "outside.md").write_text("x\n", encoding="utf-8")
    (doc_repo / "docs" / "idx.json").write_text("{}", encoding="utf-8")
    (doc_repo / "docs" / "c.md").write_text(
        "---\ntitle: C\ncategory: nope\ntags: [x]\nstatus: active\n"
        "updated: 2026-9-1\n---\n引用 `docs/idx.json` 与 `../outside.md`。\n",
        encoding="utf-8")
    (doc_repo / "docs" / "index.json").write_text(
        '{"docs": [{"path": "docs/a.md"}, {"path": "docs/sub/b.md"},'
        ' {"path": "docs/bad.md"}, {"path": "docs/c.md"}]}', encoding="utf-8")
    finds = prod.doc_selfcheck(doc_repo, "docs")
    bad = [f for f in finds if f["path"].endswith("bad.md")]
    assert bad and all(f["check"] == "frontmatter" and "缺失" in f["detail"] for f in bad)
    details = [f["detail"] for f in finds]
    assert any("词表外" in d and "category" in d for d in details)
    assert any("YYYY-MM-DD" in d for d in details)
    # ../ 逃逸在引用面直接点名（S10 口径：`../` 开头按文档目录解析，越根即点名）
    assert any("越根逃逸" in d and "../outside.md" in d for d in details)


def test_doc_selfcheck_rules_declarable(tmp_path):
    """附条件①：规则集可声明——关掉 frontmatter 检查即零 frontmatter 发现，
    换索引路径即按新路径查（引擎不写死 sandbar 约定）。"""
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "a.md").write_text("纯正文，无 frontmatter\n", encoding="utf-8")
    rules = prod.DocCheckRules(index_rel="kb/index.json", require_frontmatter=False,
                               required_fields=(), categories=(), statuses=())
    assert prod.doc_selfcheck(tmp_path, "kb", rules) == []
    # 缺省规则（带 frontmatter 检查）同仓即红
    assert any(f["check"] == "frontmatter"
               for f in prod.doc_selfcheck(tmp_path, "kb"))


# ---------- 受限可写 pin ----------

def test_produce_pin_workspace_write_named_root():
    patch = prod.produce_write_pin_patch("knowledge")
    assert "mode: 'workspace-write'" in patch
    assert "produce-doc-write" in patch
    assert "knowledge" in patch


def test_produce_pin_distinct_from_readonly_pin():
    import inspection_inspect as insp
    assert "read-only" not in prod.produce_write_pin_patch("docs")
    assert "read-only" in insp.readonly_pin_patch()


# ---------- 人审门/授权门载荷 ----------
# close 门签字校验单一真源=inspection_flow.validate_close_signature（验收 gen0
# 遗留1：produce 版语义重复件已删，本处改锁真源 + produce gate id 传参）。

import inspection_flow as flow  # noqa: E402


def test_close_signature_agent_selfsign_refused():
    _, err = flow.validate_close_signature(
        {"decision": "approve", "who": "integration", "gate": prod.PRODUCE_CLOSE_GATE_ID},
        expected_gate=prod.PRODUCE_CLOSE_GATE_ID)
    assert "不得自签" in err


def test_close_signature_gate_mismatch_refused():
    _, err = flow.validate_close_signature(
        {"decision": "approve", "who": "宿主", "gate": "inspection-close"},
        expected_gate=prod.PRODUCE_CLOSE_GATE_ID)
    assert "gate 不匹配" in err


def test_close_signature_ok_and_bad_decision():
    ok, err = flow.validate_close_signature(
        {"decision": "approve", "who": "宿主", "gate": prod.PRODUCE_CLOSE_GATE_ID},
        expected_gate=prod.PRODUCE_CLOSE_GATE_ID)
    assert ok["decision"] == "approve" and err == ""
    _, err = flow.validate_close_signature(
        {"decision": "maybe", "who": "宿主", "gate": prod.PRODUCE_CLOSE_GATE_ID},
        expected_gate=prod.PRODUCE_CLOSE_GATE_ID)
    assert "decision" in err


def test_authorize_subset_enforced():
    overlap = ["docs/design/x.md", "docs/design/y.md"]
    ok, err = prod.validate_authorize_payload(
        {"who": "宿主", "gate": prod.PRODUCE_AUTHORIZE_GATE_ID, "paths": ["docs/design/x.md"]},
        overlap)
    assert err == "" and ok["paths"] == ["docs/design/x.md"]
    _, err = prod.validate_authorize_payload(
        {"who": "宿主", "gate": prod.PRODUCE_AUTHORIZE_GATE_ID,
         "paths": ["docs/design/x.md", "server/roles/p.md"]}, overlap)
    assert "超出" in err and "server/roles/p.md" in err
    _, err = prod.validate_authorize_payload(
        {"who": "宿主", "gate": prod.PRODUCE_AUTHORIZE_GATE_ID, "paths": []}, overlap)
    assert "paths" in err
