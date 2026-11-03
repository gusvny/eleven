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
  - document self-check: the frontmatter fields and the explicit references (+ the
    out-of-tree escape, named) over a real tmp tree, never a real external source; the
    rule set is declarable (condition 1: a different rule set is a different behaviour);
    since t261103-21 the index leg is gone (index consistency is M1's, on the project
    tree) and the verdict names, every call, what was NOT judged and who owns it;
  - t261103-21 family guard: no shipped engine/plugin surface names an in-repository
    documentation index (nor calls it the machine index), and the retired docs-face
    scanner is imported by no live module;
  - 受限可写 pin：workspace-write 形态 + docs_root 进描述（A4：与只读钉形态可辨）；
  - 人审门/授权门载荷校验：agent 自签拒、gate 串门拒、授权清单越集拒。
"""
import re
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
    # t261103-21: the tree carries a legacy in-repository index on purpose -- the
    # self-check must IGNORE it (it judges no in-repository index at all any more).
    (tmp_path / "docs" / "index.json").write_text(
        '{"docs": [{"path": "docs/a.md"}, {"path": "docs/sub/b.md"},'
        ' {"path": "docs/ghost.md"}]}', encoding="utf-8")
    return tmp_path


def test_doc_selfcheck_index_leg_gone_refs_still_judged(doc_repo):
    """t261103-21: the in-repository index is not read (no "index" findings), while the
    checks that judge THIS tree's own files keep firing."""
    finds = prod.doc_selfcheck(doc_repo, "docs")
    assert [f for f in finds if f["check"] == "index"] == []
    assert any("ghost.md" in f["detail"] for f in finds if f["check"] == "ref")


def test_doc_selfcheck_verdict_names_dropped_index_leg(doc_repo):
    """The dropped coverage is named, never a bare empty list: the verdict says what it
    judged and hands the index leg to its owner by name."""
    verdict = prod.doc_selfcheck_verdict(doc_repo, "docs")
    assert set(verdict) == {"findings", "judged", "not_judged"}
    assert verdict["judged"]["pages"] == 2
    assert verdict["judged"]["checks"] == ["frontmatter", "ref"]
    named = {n["check"]: n for n in verdict["not_judged"]}
    assert "inspection_doc_mech" in named["index"]["owner"]
    assert "project" in named["index"]["reason"]
    assert "docs" not in named            # a tree with pages judged does not claim blindness


def test_doc_selfcheck_verdict_names_a_quiet_face(tmp_path):
    """A tree that holds no page CAN go quiet -- then the verdict says so by name."""
    (tmp_path / "docs").mkdir()
    verdict = prod.doc_selfcheck_verdict(tmp_path, "docs")
    assert verdict["findings"] == [] and verdict["judged"]["pages"] == 0
    named = {n["check"]: n for n in verdict["not_judged"]}
    assert "nothing to judge" in named["docs"]["reason"]
    # an absent root is a named finding, not a silent pass
    (tmp_path / "docs").rmdir()
    finds = prod.doc_selfcheck(tmp_path, "docs")
    assert [f for f in finds if f["check"] == "root"]


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
    """Condition ①: the rule set is declarable -- turning the frontmatter check off
    yields no frontmatter finding, and the verdict stops claiming that check."""
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "a.md").write_text("pure body, no frontmatter\n", encoding="utf-8")
    rules = prod.DocCheckRules(require_frontmatter=False,
                               required_fields=(), categories=(), statuses=())
    verdict = prod.doc_selfcheck_verdict(tmp_path, "kb", rules)
    assert verdict["findings"] == [] and verdict["judged"]["checks"] == ["ref"]
    # default rules (frontmatter check on) red on the same tree
    assert any(f["check"] == "frontmatter"
               for f in prod.doc_selfcheck(tmp_path, "kb"))


def test_doc_check_rules_carry_no_index_rule():
    """The dropped index leg cannot regrow through the rule set: there is no index path
    field to point at an in-repository copy."""
    assert not hasattr(prod.DocCheckRules(), "index_rel")


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


# ============================================================================
# t261103-21 — the docs-index family guard: the family cannot regrow.
#
# What went wrong (the family): the documentation index used to be a file committed
# inside the repository, and one seam after another read it as a truth source. The
# index is a DERIVED artefact now and lives in the project's own data directory
# (docs/design/project-docs-roots-v1.md goal 5), so an in-repository copy has no
# consumer, sits outside every rebuild, and drifts while nothing notices. This
# section locks the three shapes that let it come back:
#   G1 a shipped module/asset names a repository-relative documentation index path;
#   G2 a shipped string calls that in-repository file "the machine index";
#   G3 the retired docs-face scanner is imported by a live module again.
# The allowed set below is a named list, not a silent skip: each entry states why it
# is legitimate, and a new site is red by construction.
# ============================================================================

ENGINE = Path(__file__).resolve().parent.parent          # server/engine
REPO_ROOT = ENGINE.parent.parent                          # the repository root

#: A repository-relative documentation index path. The derived home prints as
#: `<projects root>/<key>/data/docs/index.json`, so `data/docs/index.json` is NOT a hit.
REPO_INDEX_PATH_RE = re.compile(r"(?<!data/)docs/index\.json")
#: The field/constant name a reader uses to point at such a path.
INDEX_PATH_IDENT_RE = re.compile(r"\bindex_rel\b|\bINDEX_REL\b")
#: The phrase that used to describe the in-repository file as if it were the artefact.
#: The legacy Chinese form is written as \u escapes on purpose: this source carries no
#: CJK literal (the copy-language gate) and no copy-marker exemption (t261004-36 banned
#: the temporary `data` id), while the compiled pattern still matches the real phrase.
MACHINE_INDEX_PHRASE_RE = re.compile(
    r"machine[\s-]+index|" + "\u673a\u5668\u7d22\u5f15", re.IGNORECASE)

#: G1: the only shipped files allowed to name an in-repository index, with the reason.
IN_REPO_INDEX_ALLOWED = {
    "server/engine/inspection_scan_doc.py": (
        "retired static scanner (t260916-22): replay-only, kept one version, its S8 leg is "
        "frozen and pinned by the module's own L1 battery and by the t260911-02 scenario; no "
        "live module imports it (G3)"),
    "server/engine/inspection_doc_mech.py": (
        "M1 names the index artefact in its finding labels (`docs/index.json` is the label of "
        "the default root, kept byte-compatible with pre-t261103-17 findings); the leg itself "
        "reads the derived index through docs_roots.index_dir"),
}

#: G1/G2 heritage ceiling: the one legacy dispatch-prompt line pair that is grandfathered
#: (host instruction, t261103-21) -- it stays BYTE-IDENTICAL to main instead of being
#: rewritten, and the corrected fact ships as an English line right beside it. Pinned by
#: line digest rather than by text on purpose: this source carries no CJK literal, and a
#: rewrite to a NEW in-repository-index line has a different digest, so it goes red. The
#: declared number is a CEILING: a later cleanup that deletes the legacy line is fine
#: (delete the entry with it), but one more occurrence than declared is red.
GRANDFATHERED_LINES = {
    "3e76a865739e3893": (2, "two legacy agent-prompt lines in server/engine/shared.py: the "
                            "'machine index + docs/index.json' wording, kept byte-identical to "
                            "main with an English correction line beside it"),
}

#: Directories whose .py/.ts files are not shipped surfaces (test fixtures and builds).
_NOT_SHIPPED = ("tests", "fixtures", "out", "bin", "node_modules", "lib")


def _shipped(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT)
    return not any(part in _NOT_SHIPPED for part in rel.parts)


def _shipped_sources():
    """Every shipped source file of the two delivery surfaces this guard covers: the
    engine (server/engine/**/*.py) and the plugin family (server/plugins/** .ts/.tsx/.mjs/
    .json). Test fixtures and built bundles are not shipped strings and stay out."""
    found = []
    for path in sorted(ENGINE.rglob("*.py")):
        if _shipped(path):
            found.append(path)
    for pattern in ("*.ts", "*.tsx", "*.mjs", "*.json", "*.cjs"):
        for path in sorted((REPO_ROOT / "server" / "plugins").rglob(pattern)):
            if _shipped(path):
                found.append(path)
    return found


def _digest(line: str) -> str:
    """The pin for a grandfathered line (see GRANDFATHERED_LINES)."""
    import hashlib
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:16]


def _grandfathered(line: str) -> bool:
    return _digest(line) in GRANDFATHERED_LINES


def _hits(regex, path: Path):
    """(lineno, line) of every match, read as UTF-8 with a lossy decode so one odd file
    never hides the rest of the scan."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:                      # an unreadable shipped file is not a pass
        raise AssertionError("shipped file unreadable: %s (%s)" % (path, e))
    return [(no, line) for no, line in enumerate(text.splitlines(), 1)
            if regex.search(line)]


def test_g1_no_shipped_source_names_an_in_repository_index():
    """G1: the in-repository index has no reader left, so a shipped file that names it is
    a regression -- unless it is one of the named retirements above."""
    hits = {}
    for path in _shipped_sources():
        found = _hits(REPO_INDEX_PATH_RE, path)
        if path.suffix == ".py":
            found += _hits(INDEX_PATH_IDENT_RE, path)
        found = [(no, line) for no, line in found if not _grandfathered(line)]
        if found:
            hits[str(path.relative_to(REPO_ROOT))] = found
    unexpected = {p: v for p, v in hits.items() if p not in IN_REPO_INDEX_ALLOWED}
    assert not unexpected, (
        "an in-repository documentation index is named by a shipped file that is not a "
        "declared retirement (the index is derived and lives outside the repository): %s"
        % {p: ["%d: %s" % (no, line.strip()[:120]) for no, line in v]
           for p, v in unexpected.items()})


def test_g2_no_shipped_string_calls_the_in_repository_index_the_machine_index():
    """G2: the phrase is legitimate only where it describes the DERIVED index. A line
    that pairs the phrase with a repository-relative index path is the old claim."""
    offenders = {}
    for path in _shipped_sources():
        for no, line in _hits(MACHINE_INDEX_PHRASE_RE, path):
            if REPO_INDEX_PATH_RE.search(line) and not _grandfathered(line):
                offenders.setdefault(str(path.relative_to(REPO_ROOT)), []).append(
                    "%d: %s" % (no, line.strip()[:140]))
    assert not offenders, (
        "a shipped string calls the in-repository index 'the machine index' (the machine "
        "index is the derived artefact in the project data directory): %s" % offenders)


def test_g3_the_retired_docs_face_scanner_has_no_live_importer():
    """G3: retiring the face=doc wiring (t261103-21) is worth nothing if the retired
    scanner gets imported again somewhere else in the engine."""
    importers = {}
    for path in _shipped_sources():
        if path.suffix != ".py" or path.name == "inspection_scan_doc.py":
            continue
        found = [ln for ln in _hits(re.compile(r"^\s*(from|import)\s+inspection_scan_doc\b"),
                                    path)]
        if found:
            importers[str(path.relative_to(REPO_ROOT))] = ["%d" % no for no, _ in found]
    assert not importers, (
        "a live engine module imports the retired docs-face scanner (inspection_scan_doc, "
        "t260916-22 / face=doc retired by t261103-21): %s" % importers)


def test_g4_the_produce_selfcheck_holds_no_index_rule():
    """G4 (module face of G1): the produce self-check cannot be re-pointed at an
    in-repository index through its rule set, and its source names no such path."""
    assert not hasattr(prod.DocCheckRules(), "index_rel")
    src = (ENGINE / "inspection_produce.py").read_text(encoding="utf-8")
    assert not REPO_INDEX_PATH_RE.search(src), (
        "inspection_produce names a repository-relative documentation index path")


def _grandfathered_over_cap(seen):
    """Cap judge (pure, so it is provable on synthetic counts): each declared grandfathered
    line may appear at most `cap` times across the scanned surfaces."""
    over = []
    for dig, (cap, reason) in GRANDFATHERED_LINES.items():
        n = seen.get(dig, 0)
        if n > cap:
            over.append("%s: %d > cap %d (%s)" % (dig, n, cap, reason))
    return over


def test_g5_grandfathered_lines_are_capped_not_a_loophole():
    """The heritage ceiling is a cap, not an exemption: the declared grandfathered line may
    not appear more often than declared anywhere in the scanned surfaces, and the judge
    itself is proven on synthetic counts (a green from a judge never seen red is not
    trusted)."""
    dig, (cap, _reason) = next(iter(GRANDFATHERED_LINES.items()))
    assert _grandfathered_over_cap({dig: cap}) == []
    assert _grandfathered_over_cap({dig: cap + 1}), "the cap judge must fire above the cap"
    seen = {}
    for path in _shipped_sources():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not (REPO_INDEX_PATH_RE.search(line) or MACHINE_INDEX_PHRASE_RE.search(line)):
                continue
            dig = _digest(line)
            if dig in GRANDFATHERED_LINES:
                seen[dig] = seen.get(dig, 0) + 1
    assert _grandfathered_over_cap(seen) == []
