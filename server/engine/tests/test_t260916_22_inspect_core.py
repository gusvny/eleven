"""t260916-22：inspect 段契约纯函数层单测（inspection_inspect.py）。

覆盖（工单验收②③④的纯函数面 + 方案 §4 步骤1 清单）：
- 输出契约：围栏 JSON 恰一块纪律（0/2 块、坏 JSON、findings 非列表）、逐条 schema
  畸形点名（缺 subject/severity 越域/缺空 evidence/证据项缺键/行号非法/quote 空或
  空白【超长已改软提醒，不在畸形列——宿主令 260921】/confidence 越域）、多余键丢弃；
- id 铸造：跨期稳定（空白差异/证据顺序换同 id）、内容变即新 id；
- 证据机械复核：坏路径/绝对路径/越界/坏行号/引文不符逐项降级 unverified + reason 点名；
  空白差异应过；多证据部分坏=unverified+坏项点名；
- 引文超长软提醒（宿主令 260921，t260922-01 事故回归）：227 字→在册+截断标注+人话
  点名；恰 200 不标零新键；多证据只标超长项；截断保前缀→复核仍 verified、不符仍
  unverified；计数 quote_overlong_warn 口径=保留集（被预算截掉不计）；prompt 软语义
  +阈值单点可配；
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
    # 注意：超长（"x"*201）不再是畸形——宿主令 260921 改软提醒，见下方专组用例
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
    """line=0 是复核语义不是结构畸形（场景子用例3 八态契约）：解析层放行、复核必降级。"""
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


# ---------- 引文超长软提醒（宿主令 260921：软提醒不判红；t260922-01 事故回归） ----------

def test_overlong_quote_parsed_soft_with_annotation_and_note():
    """227 字引文（t260922-01 事故形态）→ 解析成功、条目在册、截断标注+人话点名。

    旧口径：>200 字=InspectParseError→整份巡检报废（findings=0、建议全陪葬）；
    新口径：该条照常入册，超长引文截断保纯前缀+逐条点名（软提醒≠静默）。"""
    raw = "长" * 227
    fs = ins.parse_agent_findings(fenced([good_finding(
        evidence=[{"path": "src/a.py", "line": 12, "quote": raw}])]))
    assert len(fs) == 1, "该条照常入册（不判红不报废）"
    ev = fs[0]["evidence"][0]
    assert ev["quote"] == raw[:ins.MAX_QUOTE_CHARS], "截断=纯原文前缀（无省略号拼接）"
    assert ev["quote_truncated"] is True and ev["quote_original_chars"] == 227
    (note,) = fs[0]["quote_warns"]
    assert "第 1 条" in note and "evidence[0]" in note
    assert "227" in note and "200" in note and "截断" in note


def test_quote_boundary_exact_limit_not_flagged_over_by_one_flagged():
    """恰在上限=不标（条目零新键逐字节兼容）；超 1 字即标。"""
    fs = ins.parse_agent_findings(fenced([good_finding(
        evidence=[{"path": "a", "line": 1, "quote": "x" * 200}])]))
    ev = fs[0]["evidence"][0]
    assert len(ev["quote"]) == 200
    assert "quote_truncated" not in ev and "quote_original_chars" not in ev
    assert "quote_warns" not in fs[0]
    fs2 = ins.parse_agent_findings(fenced([good_finding(
        evidence=[{"path": "a", "line": 1, "quote": "x" * 201}])]))
    assert fs2[0]["evidence"][0]["quote_original_chars"] == 201


def test_overlong_flags_only_the_overlong_item():
    """多证据只标超长项，其余项零新键；点名可对回证据序。"""
    fs = ins.parse_agent_findings(fenced([good_finding(evidence=[
        {"path": "a", "line": 1, "quote": "短引文"},
        {"path": "a", "line": 2, "quote": "y" * 300}])]))
    evs = fs[0]["evidence"]
    assert "quote_truncated" not in evs[0] and evs[1]["quote_truncated"] is True
    assert len(fs[0]["quote_warns"]) == 1 and "evidence[1]" in fs[0]["quote_warns"][0]


def test_overlong_parse_is_deterministic_for_id_mint():
    """截断确定性→同内容解析两次同 id（跨期去重键不漂）。"""
    msg = fenced([good_finding(
        evidence=[{"path": "src/a.py", "line": 12, "quote": "z" * 227}])])
    i1 = ins.mint_finding_id(ins.parse_agent_findings(msg)[0])
    i2 = ins.mint_finding_id(ins.parse_agent_findings(msg)[0])
    assert i1 == i2


def test_recheck_truncated_quote_prefix_passes_mismatch_still_unverified(tree):
    """复核语义不变：截断保前缀→子串校验仍过=verified；引文本身不符→仍 unverified。"""
    long_line = "assert old_fn()  # " + "上下文补充说明" * 40    # >227 字的真实行
    p = tree / "src" / "a.py"
    lines = p.read_text(encoding="utf-8").splitlines()
    lines[11] = long_line                     # 0 基 index 11 = 第 12 行（证据锚行）
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fs = ins.parse_agent_findings(fenced([good_finding(
        evidence=[{"path": "src/a.py", "line": 12, "quote": long_line[:227]}])]))
    (out,) = ins.recheck_evidence(fs, tree)
    assert out["verified"] == "verified" and "unverified_reasons" not in out
    fs2 = ins.parse_agent_findings(fenced([good_finding(
        evidence=[{"path": "src/a.py", "line": 12, "quote": "这句引文根本不在行内" * 30}])]))
    (out2,) = ins.recheck_evidence(fs2, tree)
    assert out2["verified"] == "unverified" and out2["unverified_reasons"]


def test_count_quote_overlong_truth_table():
    """计数口径真值表（含畸形输入不炸——消费外部输入纪律）。"""
    f1 = {"evidence": [{"quote_truncated": True}, {}]}
    f2 = {"evidence": [{"quote_truncated": True}, {"quote_truncated": True}]}
    assert ins.count_quote_overlong([]) == 0
    assert ins.count_quote_overlong([f1]) == 1
    assert ins.count_quote_overlong([f1, f2]) == 3
    assert ins.count_quote_overlong([{"evidence": []}, {"evidence": None}, {}]) == 0
    assert ins.count_quote_overlong([None, "垃圾", 7]) == 0


def test_budget_meta_counts_quote_overlong_on_kept_set():
    """review 条件②：计数口径=保留集——被预算截掉的条目不在票面在册，计数也不含它。"""
    over_kept = good_finding(subject="超长在册", confidence=0.9,
                             evidence=[{"path": "a", "line": 1, "quote": "x" * 227}])
    over_dropped = good_finding(subject="超长被截", severity="low", confidence=0.9,
                                evidence=[{"path": "a", "line": 1, "quote": "y" * 227}])
    fs = ins.with_ids(ins.parse_agent_findings(
        fenced([good_finding(), over_kept, over_dropped])))
    kept, meta = ins.apply_budget(fs, 2)
    assert meta["truncated"] == 1 and all(f["subject"] != "超长被截" for f in kept)
    assert meta["quote_overlong_warn"] == 1, "只计保留集（与票面 quote_warns 可对账）"
    _, meta0 = ins.apply_budget(ins.with_ids(ins.parse_agent_findings(
        fenced([good_finding()]))), 40)
    assert meta0["quote_overlong_warn"] == 0, "无超长=计数位 0（键恒在场）"


def test_prompt_quote_soft_semantics_and_limit_follows_constant(monkeypatch):
    """prompt 软语义（验收判据⑤）：不得再写「必须 ≤N 字」必须式；阈值单点可配。"""
    p = ins.build_inspect_prompt("i", "p", "test", "b", "h", 10)
    assert "200 字内" in p and "截断" in p and "点名" in p
    assert "≤200 字" not in p and "必须 ≤" not in p, "软语义：超长不判红，不逼模型守字数"
    monkeypatch.setattr(ins, "MAX_QUOTE_CHARS", 50)
    p50 = ins.build_inspect_prompt("i", "p", "test", "b", "h", 10)
    assert "50 字内" in p50 and "≤50 字" not in p50, "阈值改常量单点全链生效"


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
    assert ids is None and "跨期去重分支缺席" in note
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
    with pytest.raises(ValueError, match="no overwrite rebuild"):
        ins.append_verdict_entry(bad, {"finding_id": "c", "verdict": "doubt", "who": "x"})
    bad2 = tmp_path / "bad2.json"
    bad2.write_text('{"entries": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"malformed \(missing entries list\)"):
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
    with pytest.raises(ValueError, match="out of range"):
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
    # t261004-42 rework: the test-face criteria block was rewritten in English
    # (the copy-language gate L15 treats a touched prompt line as an added line,
    # so the block now complies with the writing standard) and extended with the
    # tier-admission A/B/C block — the tier rule genuinely belongs in the prompt
    # (ticket deliverable C), so the pinned needle follows the new contract
    # wording; the pin itself is not loosened. The A/B/C labels are pinned by
    # test_t261004_42_inspect_tier_criteria.py.
    for needle in ("巡检审查任务", "只读审查员", "绝不修改", "证据", "恰好一块", "40 条",
                   "confidence", "/tmp/base", "abc123", "/tmp/s.json", "- x",
                   "Guard still valid", "Tier admission A/B/C"):
        assert needle in p, needle
    assert ins.build_inspect_prompt("i", "p", "doc", "b", "h", 10)
    assert ins.build_inspect_prompt("i", "p", "mechanism", "b", "h", 10)
    assert ins.build_inspect_prompt("i", "p", "simplify", "b", "h", 10)
    assert ins.build_inspect_prompt("i", "p", "stage", "b", "h", 10)
    assert "无套件档" in ins.build_inspect_prompt("i", "p", "test", "b", "h", 10)
    assert "上期无台账" in ins.build_inspect_prompt("i", "p", "test", "b", "h", 10)


def test_prompt_unknown_face_fails_closed():
    with pytest.raises(ValueError, match="not wired"):
        ins.build_inspect_prompt("i", "p", "typo", "b", "h", 10)


def test_profile_faces_vocabulary():
    assert set(ins.PROFILE_FACES) == {"test", "doc", "stage", "mechanism", "simplify"}
    assert set(ins.PROFILE_TEXTS) == set(ins.PROFILE_FACES)


def test_persona_and_readonly_pin_patch_shape():
    persona = ins.build_persona_patch()
    assert "id: system-prompt" in persona and "只读审查员" in persona
    pin = ins.readonly_pin_patch()
    # 260920 修正（宿主令「直接修」，实案 t260920-02）：dsh 0.1.1-rc.2 的权限预设表缺省
    # 只有 workspace-write/danger-full-access，直接引用 'read-only' 会 boot 即拒启；
    # 而换成 workspace-write 会把只读沙箱改写成可写（预设自带 sandbox）——故补丁自带
    # read-only 表项，只读语义（sandbox read-only + approval ask）逐字保留。
    assert "mode: 'read-only'" in pin and "defaultPreset: 'read-only'" in pin
    assert "      read-only:\n        sandbox: 'read-only'\n        approval: 'ask'" in pin
    assert "- id: sandbox-policy" in pin and "- id: permission" in pin
    assert "- id: sandbox-policy" in pin and "- id: permission" in pin
