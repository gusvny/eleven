"""t260916-22：inspect 段契约纯函数层单测（inspection_inspect.py）。

覆盖（工单验收②③④的纯函数面 + 方案 §4 步骤1 清单）：
- 输出契约：围栏 JSON 恰一块纪律（0/2 块、坏 JSON、findings 非列表）、逐条 schema
  畸形点名（缺 subject/severity 越域/缺空 evidence/证据项缺键/行号非法/quote 空或超限/
  confidence 越域）、多余键丢弃；
- id 铸造：跨期稳定（空白差异/证据顺序换同 id）、内容变即新 id；
- 证据机械复核：坏路径/绝对路径/越界/坏行号/引文不符逐项降级 unverified + reason 点名；
  空白差异应过；多证据部分坏=unverified+坏项点名；
- 跨期去重与假报压制、预算截断（41→40、recurring 不占预算）、汇总/心跳；
- 上期台账与裁定台账读取（畸形输入：坏 JSON/缺 findings/非列表 → None+点名 note）；
- verdict 纯面：词表/别名/非法、apply_verdict_to_face 命中/未命中；
- prompt/分面/persona/read-only pin。
"""
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_inspect as ins  # noqa: E402


# ---------- 夹具 ----------

def fenced(findings: list) -> str:
    return "审查结论如下。\n```json\n%s\n```\n以上。" % json.dumps({"findings": findings},
                                                                ensure_ascii=False)


def good_finding(**kw) -> dict:
    f = {"subject": "守卫断言引用已删除函数 src/a.py:12",
         "severity": "med",
         "evidence": [{"path": "src/a.py", "line": 12, "quote": "assert old_fn()"}],
         "why": "断言对象不存在，守卫已失效",
         "suggestion": "改断言到新函数",
         "confidence": 0.8}
    f.update(kw)
    return f


# ---------- 输出契约 ----------

def test_parse_ok_and_normalization():
    fs = ins.parse_agent_findings(fenced([good_finding(), good_finding(
        subject="s2", severity="low", evidence=[{"path": "./b.md", "line": 3, "quote": "q"}],
        why="w", extra_key="垃圾应被丢弃")]))
    assert len(fs) == 2
    assert fs[0]["severity"] == "med" and fs[0]["confidence"] == 0.8
    assert "extra_key" not in fs[1]
    assert fs[1]["evidence"][0]["path"] == "b.md"      # ./ 前缀规范化


@pytest.mark.parametrize("text", [
    "", "没有围栏块", "```json\n{\"findings\": []}\n``` 前面一块 ```json\n{\"findings\": []}\n```",
])
def test_parse_fence_count_fail_closed(text):
    with pytest.raises(ins.InspectParseError, match="恰一块"):
        ins.parse_agent_findings(text)


def test_parse_bad_json_named():
    with pytest.raises(ins.InspectParseError):
        ins.parse_agent_findings("x\n```json\n{\"findings\": [} bad\n```\n")


def test_parse_findings_not_list():
    with pytest.raises(ins.InspectParseError, match="列表"):
        ins.parse_agent_findings("```json\n{\"findings\": \"x\"}\n```")


@pytest.mark.parametrize("mut, why", [
    ({"subject": ""}, "subject"),
    ({"subject": None}, "subject"),
    ({"severity": "huge"}, "severity"),
    ({"evidence": []}, "evidence"),
    ({"evidence": None}, "evidence"),
    ({"evidence": [{"path": "a", "line": -1, "quote": "q"}]}, "line"),
    ({"evidence": [{"path": "a", "line": "2", "quote": "q"}]}, "line"),
    ({"evidence": [{"path": "", "line": 1, "quote": "q"}]}, "path"),
    ({"evidence": [{"path": "a", "line": 1, "quote": "  "}]}, "quote"),
    ({"evidence": [{"path": "a", "line": 1}]}, "quote"),
    ({"evidence": [{"path": "a", "line": 1, "quote": "x" * 201}]}, "超长"),
    ({"confidence": 1.5}, "confidence"),
    ({"confidence": "high"}, "confidence"),
    ({"why": ""}, "why"),
])
def test_parse_schema_mutations_named_by_index(mut, why):
    raw = good_finding(**mut)
    with pytest.raises(ins.InspectParseError) as ei:
        ins.parse_agent_findings(fenced([good_finding(), raw]))
    assert "findings[2]" in str(ei.value) and why in str(ei.value)


# ---------- id 铸造 ----------

def test_mint_id_stable_across_whitespace_and_evidence_order():
    a = good_finding()
    b = good_finding(subject=" 守卫断言引用已删除函数  src/a.py:12 ",
                     why="断言对象不存在，守卫已失效  ",
                     evidence=[{"path": "src/a.py", "line": 12, "quote": "assert \t old_fn()  "}])
    b2 = good_finding(evidence=[dict(a["evidence"][0]), {"path": "src/z.py", "line": 1, "quote": "z"}])
    b3 = good_finding(evidence=[{"path": "src/z.py", "line": 1, "quote": "z"},
                                dict(a["evidence"][0])])
    assert ins.mint_finding_id(a) == ins.mint_finding_id(b)
    assert ins.mint_finding_id(b2) == ins.mint_finding_id(b3)   # 证据顺序不影响 id
    assert len(ins.mint_finding_id(a)) == 8


def test_mint_id_changes_with_content():
    base = ins.mint_finding_id(good_finding())
    assert ins.mint_finding_id(good_finding(subject="另一问题")) != base
    assert ins.mint_finding_id(good_finding(why="理由不同")) != base
    assert ins.mint_finding_id(good_finding(
        evidence=[{"path": "src/a.py", "line": 13, "quote": "assert old_fn()"}])) != base
    assert ins.mint_finding_id(good_finding(
        evidence=[{"path": "src/a.py", "line": 12, "quote": "assert new_fn()"}])) != base


def test_with_ids_tags_scan_agent():
    fs = ins.with_ids([good_finding()])
    assert fs[0]["scan"] == "agent" and fs[0]["id"] == ins.mint_finding_id(fs[0])


# ---------- 证据机械复核（验收②） ----------

@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    (d / "src").mkdir(parents=True)
    # 12 行处放断言行（good_finding 的证据锚=src/a.py:12）
    lines = ["# padding %d" % i for i in range(1, 12)] + ["assert old_fn()", "line thirteen"]
    (d / "src" / "a.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "docs").mkdir()
    (d / "docs" / "r.md").write_text("文档标题\n内容带\t制表与  空格\n", encoding="utf-8")
    return d


def test_recheck_ok_verified(tree):
    fs = ins.recheck_evidence([good_finding()], tree)
    assert fs[0]["verified"] == "verified" and "unverified_reasons" not in fs[0]


def test_recheck_whitespace_tolerance(tree):
    f = good_finding(evidence=[{"path": "src/a.py", "line": 12, "quote": "assert \t old_fn() "}])
    f2 = good_finding(evidence=[{"path": "docs/r.md", "line": 2, "quote": "内容带 制表与 空格"}])
    out = ins.recheck_evidence([f, f2], tree)
    assert all(x["verified"] == "verified" for x in out)


def test_parse_line_zero_is_structural_ok_recheck_degrades():
    """line=0 是复核语义不是结构畸形（场景腿3 八态契约）：解析层放行、复核必降级。"""
    fs = ins.parse_agent_findings(
        fenced([good_finding(evidence=[{"path": "src/a.py", "line": 0, "quote": "x"}])]))
    assert fs[0]["evidence"][0]["line"] == 0


def test_recheck_bad_path_out_of_range_quote_mismatch_named(tree):
    fs = [good_finding(evidence=[{"path": "src/missing.py", "line": 1, "quote": "x"}]),
          good_finding(evidence=[{"path": "src/a.py", "line": 99, "quote": "x"}]),
          good_finding(evidence=[{"path": "src/a.py", "line": 1, "quote": "完全不同的内容"}]),
          good_finding(evidence=[{"path": "../outside.py", "line": 1, "quote": "x"}]),
          good_finding(evidence=[{"path": "/etc/hostname", "line": 1, "quote": "x"}]),
          good_finding(evidence=[{"path": "src/a.py", "line": 0, "quote": "x"}])]
    out = ins.recheck_evidence(fs, tree)
    tags = [(f["verified"], f["unverified_reasons"]) for f in out]
    assert all(v == "unverified" for v, _ in tags)
    assert any("不存在" in r[0] for _, r in tags)
    assert any("越界" in r[0] for _, r in tags)
    assert any("引文与文件内容不符" in r[0] for _, r in tags)
    assert any("越界" in r[0] for _, r in tags[5:6])   # 行号 0 → 范围判定拦下


def test_recheck_partial_bad_evidence_names_only_bad_item(tree):
    f = good_finding(evidence=[{"path": "src/a.py", "line": 1, "quote": "# padding 1"},
                               {"path": "src/a.py", "line": 500, "quote": "x"}])
    (out,) = ins.recheck_evidence([f], tree)
    assert out["verified"] == "unverified"
    assert len(out["unverified_reasons"]) == 1 and "500" in out["unverified_reasons"][0]


# ---------- 去重/压制/预算/汇总/心跳 ----------

def _tag(fs, **kw):
    for f in fs:
        f.update(kw)
    return fs


def test_dedupe_and_suppress_marks_only_matches():
    fs = ins.with_ids([good_finding(), good_finding(subject="新问题 s2"), good_finding(subject="旧问题 s3")])
    prev = {fs[0]["id"]}
    fake = {fs[2]["id"]}
    ins.dedupe_and_suppress(fs, prev, fake)
    assert fs[0]["recurring"] is True
    assert fs[1].get("recurring") is None and fs[1].get("suppressed") is None
    assert fs[2]["suppressed"] is True and fs[2]["verdict"] == ins.VERDICT_FAKE


def test_budget_truncates_41_to_40_by_severity():
    fs = []
    for i in range(41):
        fs.append(good_finding(subject="问题 %d" % i, severity="low" if i == 40 else "med",
                               confidence=0.5 + i * 0.001))
    fs = ins.with_ids(fs)
    kept, meta = ins.apply_budget(fs, 40)
    assert meta["truncated"] == 1
    assert len(kept) == 40
    assert all(f["subject"] != "问题 40" for f in kept)   # low + 最低置信被截


def test_budget_recurring_and_suppressed_do_not_consume_cap():
    fs = ins.with_ids([good_finding(subject="新 %d" % i) for i in range(40)])
    fs += ins.with_ids([good_finding(subject="老 %d" % i) for i in range(5)])
    ins.dedupe_and_suppress(fs[40:], {f["id"] for f in fs[40:]}, set())   # recurring
    ins.dedupe_and_suppress(fs[45:], set(), {f["id"] for f in fs[45:]})   # suppressed
    kept, meta = ins.apply_budget(fs, 40)
    assert meta["truncated"] == 0 and len(kept) == 45


def test_budget_orders_by_severity_then_confidence():
    fs = ins.with_ids([good_finding(subject="m%d" % i, severity="med", confidence=0.6) for i in range(39)]
                      + [good_finding(subject="the-high", severity="high", confidence=0.1),
                         good_finding(subject="drop-low", severity="med", confidence=0.59)])
    kept, meta = ins.apply_budget(fs, 40)
    assert meta["truncated"] == 1
    assert any(f["subject"] == "the-high" for f in kept)
    assert not any(f["subject"] == "drop-low" for f in kept)


def test_summarize_and_heartbeat_exclude_recurring_suppressed():
    fs = ins.with_ids([good_finding(subject="新 high", severity="high"),
                       good_finding(subject="老 med", severity="med")])
    ins.dedupe_and_suppress(fs[1:], {fs[1]["id"]}, set())
    fs2 = ins.with_ids([good_finding(subject="假 low", severity="low")])
    ins.dedupe_and_suppress(fs2, set(), {fs2[0]["id"]})
    counts = ins.summarize_counts(fs + fs2)
    assert counts == {"high": 1, "med": 0, "low": 0}
    assert ins.heartbeat_of(fs + fs2) is False
    assert ins.heartbeat_of(fs[1:] + fs2) is True       # 只剩 recurring/压制 → 心跳


def test_period_sort_key_numeric_buckets():
    assert ins.period_sort_key("20260916") < ins.period_sort_key("20260916-1")
    assert ins.period_sort_key("20260916-2") < ins.period_sort_key("20260916-10")
    assert ins.period_sort_key("20260915") < ins.period_sort_key("20260916")
    assert ins.period_sort_key("bad") == (0, 0)


# ---------- 上期台账 / 裁定台账（畸形输入点名，R7②） ----------

def test_read_prev_ledger_ids_paths(tmp_path: Path):
    d = tmp_path / "out"
    d.mkdir()
    ids, note = ins.read_prev_ledger_ids(d, "inst", "20260916")
    assert ids == set() and "无更早期" in note

    def write(period, doc, suffix=".json"):
        (d / ("inspection-inst-%s%s" % (period, suffix))).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    write("20260914", {"findings": [{"id": "aaa"}, {"id": "bbb"}]})
    write("20260915", {"findings": [{"id": "ccc"}]})
    write("20260915", {"suite": True}, suffix="-suite.json")     # 非台账件
    write("20260915", {"entries": []}, suffix="-verdicts.json")  # 非台账件
    ids, note = ins.read_prev_ledger_ids(d, "inst", "20260916")
    assert ids == {"ccc"} and "20260915" in note
    # 期号词法外的同名文件不进候选
    (d / "inspection-inst-latest.json").write_text("{}", encoding="utf-8")
    ids, _ = ins.read_prev_ledger_ids(d, "inst", "20260916")
    assert ids == {"ccc"}


def test_read_prev_ledger_ids_malformed_named(tmp_path: Path):
    d = tmp_path / "out"
    d.mkdir()
    (d / "inspection-inst-20260915.json").write_text("{bad json", encoding="utf-8")
    ids, note = ins.read_prev_ledger_ids(d, "inst", "20260916")
    assert ids is None and "跨期去重腿缺席" in note
    (d / "inspection-inst-20260915.json").write_text('{"findings": "x"}', encoding="utf-8")
    ids, note = ins.read_prev_ledger_ids(d, "inst", "20260916")
    assert ids is None and "缺 findings" in note


def test_verdicts_file_roundtrip_and_malformed(tmp_path: Path):
    p = tmp_path / "inspection-i-20260915-verdicts.json"
    ins.append_verdict_entry(p, {"finding_id": "a", "verdict": "false-positive", "who": "宿主"})
    ins.append_verdict_entry(p, {"finding_id": "b", "verdict": "to-fix", "who": "宿主"})
    res = ins.read_verdicts_file(p)
    assert [e["finding_id"] for e in res["entries"]] == ["a", "b"] and not res["error"]
    assert ins.read_verdicts_file(tmp_path / "nope.json") == {"entries": [], "error": ""}
    bad = tmp_path / "bad.json"
    bad.write_text("nonsense{", encoding="utf-8")
    assert ins.read_verdicts_file(bad)["error"]
    with pytest.raises(ValueError, match="不覆盖重建"):
        ins.append_verdict_entry(bad, {"finding_id": "c", "verdict": "doubt", "who": "x"})
    bad2 = tmp_path / "bad2.json"
    bad2.write_text('{"entries": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="形状坏"):
        ins.append_verdict_entry(bad2, {})


def test_collect_fake_ids_multi_period_and_malformed_note(tmp_path: Path):
    d = tmp_path / "out"
    d.mkdir()
    def verdicts(period, entries):
        (d / ("inspection-i-%s-verdicts.json" % period)).write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    verdicts("20260914", [{"finding_id": "old1", "verdict": "false-positive"},
                          {"finding_id": "old2", "verdict": "to-fix"}])
    verdicts("20260915", [{"finding_id": "new1", "verdict": "false-positive"}])
    (d / "inspection-i-20260913-verdicts.json").write_text("broken", encoding="utf-8")
    fake, notes = ins.collect_fake_ids(d, "i", "20260916")
    assert fake == {"old1", "new1"}
    assert any("20260913" in n for n in notes)
    # 当期自己的裁定不算（防「标了假报当期就消失」自指）
    fake2, _ = ins.collect_fake_ids(d, "i", "20260914")
    assert "new1" not in fake2


# ---------- verdict 纯面 ----------

def test_normalize_verdict_tokens_and_aliases():
    assert ins.normalize_verdict("false-positive") == "false-positive"
    assert ins.normalize_verdict(" 假报 ") == "false-positive"
    assert ins.normalize_verdict("待修") == "to-fix"
    assert ins.normalize_verdict("存疑") == "doubt"
    with pytest.raises(ValueError, match="越域"):
        ins.normalize_verdict("maybe")


def test_apply_verdict_to_face():
    face = {"findings": [{"id": "a1", "subject": "s1"}, {"id": "a2", "subject": "s2"}]}
    assert ins.apply_verdict_to_face(face, "a2", "to-fix", "宿主", "实锤") == ""
    assert face["findings"][1]["verdict"] == "to-fix"
    assert face["findings"][1]["verdict_who"] == "宿主"
    assert "不在本票" in ins.apply_verdict_to_face(face, "zz", "to-fix", "x", "")
    assert ins.apply_verdict_to_face(face, "", "to-fix", "x", "") == "finding-id 缺失"
    assert ins.apply_verdict_to_face({}, "a", "to-fix", "x", "").startswith("票面缺 findings")


# ---------- prompt / 分面 / persona / pin ----------

def test_prompt_contains_contract_and_budget():
    p = ins.build_inspect_prompt("inst", "20260916", "test", "/tmp/base", "abc123",
                                 max_findings=40, suite_receipt="/tmp/s.json", prev_summary="- x")
    for needle in ("巡检审查任务", "只读审查员", "绝不修改", "证据", "恰好一块", "40 条",
                   "confidence", "/tmp/base", "abc123", "/tmp/s.json", "- x",
                   "守卫是否还有效"):
        assert needle in p, needle
    assert ins.build_inspect_prompt("i", "p", "doc", "b", "h", 10)
    assert ins.build_inspect_prompt("i", "p", "mechanism", "b", "h", 10)
    assert ins.build_inspect_prompt("i", "p", "simplify", "b", "h", 10)
    assert ins.build_inspect_prompt("i", "p", "stage", "b", "h", 10)
    assert "无套件档" in ins.build_inspect_prompt("i", "p", "test", "b", "h", 10)
    assert "上期无台账" in ins.build_inspect_prompt("i", "p", "test", "b", "h", 10)


def test_prompt_unknown_face_fails_closed():
    with pytest.raises(ValueError, match="未接线"):
        ins.build_inspect_prompt("i", "p", "typo", "b", "h", 10)


def test_profile_faces_vocabulary():
    assert set(ins.PROFILE_FACES) == {"test", "doc", "stage", "mechanism", "simplify"}
    assert set(ins.PROFILE_TEXTS) == set(ins.PROFILE_FACES)


def test_persona_and_readonly_pin_patch_shape():
    persona = ins.build_persona_patch()
    assert "id: system-prompt" in persona and "只读审查员" in persona
    pin = ins.readonly_pin_patch()
    # 260920 修正（宿主令「直接修」，实案 t260920-02）：permission 预设名回归受支持值——
    # 生产 dsh 0.1.1-rc.2 的预设表只有 workspace-write/danger-full-access，写死 'read-only'
    # 会让巡检 inspect 段 boot 即拒启（unknown preset）。只读红线由 sandbox 模式承担。
    assert "mode: 'read-only'" in pin and "defaultPreset: 'workspace-write'" in pin
    assert "defaultPreset: 'read-only'" not in pin
    assert "- id: sandbox-policy" in pin and "- id: permission" in pin
