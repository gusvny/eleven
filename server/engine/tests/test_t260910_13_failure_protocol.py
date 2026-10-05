#!/usr/bin/env python3
"""t260910-13 失败分类协议纯函数单测（L1，零 IO 零网络零 git）。

覆盖：解析（含畸形电池）/ 三态收紧双端 / 指纹键级 diff 与排除键 / 决策表
全行 / 基线缺席与指纹不等降级 / 汇总重算 / 同名去重。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import failure_protocol as fp  # noqa: E402


def case(name="s1", status="fail", cause="self", reason="assert_mismatch",
         evidence="AssertionError: x != y", **kw):
    d = {"name": name, "suite": "t", "status": status, "cause": cause,
         "reason": reason, "dur_s": 1.2, "attempt": 1, "started": "2026-09-10T00:00:00",
         "git_sha": "abc", "evidence": evidence, "artifacts": []}
    d.update(kw)
    return d


# ---------------- 解析 ----------------

def test_parse_spec_line_roundtrip():
    line = json.dumps(case())
    obj = fp.parse_spec_line(line)
    assert obj["name"] == "s1" and obj["status"] == "fail"


def test_parse_spec_line_ignores_legacy_text_lines():
    assert fp.parse_spec_line("PASS [x] (1.0s)") is None
    assert fp.parse_spec_line("ENV_FAIL [x] exit=2") is None
    assert fp.parse_spec_line("SCENARIOS ran=1 pass=1 fail=0 env_fail=0 na=0") is None


def test_malformed_battery():
    # 非 JSON 的花括号行 / 半行 / 字段错型 / 缺必需字段 / 未知 status / JSON 数组
    bad_lines = [
        "{not json",
        '{"name": "x"',                     # 半行
        '{"name": 1, "status": "fail"}',    # name 错型
        '{"name": "x"}',                    # 缺 status
        '{"name": "x", "status": "ENV_FAIL"}',  # 未知 status
        '["a", "b"]',                       # 非对象
        '{"name": "", "status": "pass"}',   # 空名
    ]
    for ln in bad_lines:
        r = fp.parse_spec_line(ln)
        assert r is not None and "__malformed__" in r, ln
    # 空白行不算规范行也不算畸形（无内容）
    assert fp.parse_spec_line("") is None


def test_evidence_one_line():
    assert fp.evidence_one_line("a\nb") == "a\\nb"
    assert fp.evidence_one_line("a\r\nb") == "a\\nb"
    assert "\n" not in fp.evidence_one_line("x\ny\nz")
    assert fp.evidence_one_line(None) == ""
    # 带引号走 json.dumps 转义后 roundtrip 回得来
    line = json.dumps({"name": "e", "status": "pass",
                       "evidence": fp.evidence_one_line('he said "hi"\nbye')})
    assert json.loads(line)["evidence"] == 'he said "hi"\\nbye'


# ---------------- 三态收紧 ----------------

def test_violation_fail_with_prepare_reason():
    c, viols = fp.enforce_semantics(fp.normalize_case(
        case(status="fail", reason="connect_refused", cause="external",
             evidence="ENV_FAIL: docker 不可用")))
    assert c["status"] == "not-checked" and c.get("violation") is True
    assert c["reason"] == "connect_refused"          # reason 原样保留
    assert viols and "must not report fail" in viols[0]


def test_unbacked_env_fail_becomes_fail():
    c, viols = fp.enforce_semantics(fp.normalize_case(
        case(status="not-checked", cause="external", reason="missing_asset",
             evidence="")))
    assert c["status"] == "fail" and c.get("unbacked_env_fail") is True
    assert "fail-closed" in viols[0]


def test_backed_env_fail_stays_not_checked():
    c, viols = fp.enforce_semantics(fp.normalize_case(
        case(status="not-checked", cause="external", reason="missing_asset",
             evidence="ENV_FAIL: playwright-core 缺失")))
    assert c["status"] == "not-checked" and not viols


# ---------------- 指纹 ----------------

def test_fingerprint_excludes_ticket_context_keys():
    a = fp.env_fingerprint({"python": "3.11", "SANDBAR_TASK_QUEUE": "q1",
                            "SANDBAR_WATCH_WORKFLOW": "w"})
    b = fp.env_fingerprint({"python": "3.11", "SANDBAR_TASK_QUEUE": "q2",
                            "SANDBAR_WATCH_WORKFLOW": "w2"})
    assert a["value"] == b["value"]          # 语境键排除 → lane/基线不恒 diff
    assert "SANDBAR_TASK_QUEUE" not in a["keys"]


def test_fingerprint_diff_keys():
    a = fp.env_fingerprint({"python": "3.11", "node": "22"})
    b = fp.env_fingerprint({"python": "3.12", "node": "22", "docker": "27"})
    d = fp.fingerprint_diff(a, b)
    keys = {x["key"] for x in d}
    assert keys == {"python", "docker"}


def test_fingerprint_stable_ordering():
    a = fp.env_fingerprint({"x": "1", "y": "2"})
    b = fp.env_fingerprint({"y": "2", "x": "1"})
    assert a["value"] == b["value"]


# ---------------- 决策表 ----------------

def _red(names):
    return {n: case(name=n) for n in names}


def test_true_regression_blocks():
    v = fp.decide(fp.normalize_case(case()), {}, True, True)
    assert v["verdict"] == "block" and "regression" in v["why"]


def test_baseline_red_records_not_block():
    v = fp.decide(fp.normalize_case(case(name="doc-contrast")),
                  _red(["doc-contrast"]), True, True)
    assert v["verdict"] == "record" and "existing debt" in v["why"]


def test_not_checked_self_main_green_blocks():
    v = fp.decide(fp.normalize_case(case(status="not-checked", cause="self",
                                         reason="lock_busy", evidence="lock held")),
                  {}, True, True)
    assert v["verdict"] == "block"


def test_not_checked_external_records():
    v = fp.decide(fp.normalize_case(case(status="not-checked", cause="external",
                                         reason="missing_asset", evidence="缺 X")),
                  {}, True, True)
    assert v["verdict"] == "record"


def test_violation_blocks_even_if_baseline_red():
    c = fp.normalize_case(case(status="fail", reason="self_precheck"))
    c, _ = fp.enforce_semantics(c)
    v = fp.decide(c, _red(["s1"]), True, True)
    assert v["verdict"] == "block" and v.get("violation") is True


def test_baseline_not_checked_never_in_red_list():
    # 基线同场景 not-checked（裸基线树缺依赖）→ 不进红名单 → 泳道 checked fail 仍拦
    baseline = [fp.normalize_case(case(name="s1", status="not-checked",
                                       cause="external", reason="missing_asset",
                                       evidence="no venv"))]
    red = fp._baseline_red_set(baseline)
    assert "s1" not in red
    v = fp.decide(fp.normalize_case(case(name="s1")), red, True, True)
    assert v["verdict"] == "block"


def test_baseline_red_entry_carries_evidence():
    baseline = [fp.normalize_case(case(name="s1", evidence="AssertionError: boom"))]
    red = fp._baseline_red_set(baseline)
    assert red["s1"]["evidence"] == "AssertionError: boom"   # K2


def test_fingerprint_mismatch_not_checked_unknown():
    r = fp.apply_affiliation(
        [fp.normalize_case(case(name="s1", status="not-checked", cause="self",
                                evidence="lock"))],
        [fp.normalize_case(case(name="s1"))],
        fp.env_fingerprint({"python": "3.11"}),
        fp.env_fingerprint({"python": "3.12"}),
        baseline_ok=True)
    assert r["affiliation_confidence"] == "unknown(fingerprint_mismatch)"
    assert r["blockers"] == [] and r["unknowns"] == ["s1"]
    assert r["fp_diffs"] and r["fp_diffs"][0]["key"] == "python"


def test_fingerprint_mismatch_fail_still_blocks_conservatively():
    # 真红必拦不因基线不可比松绑（保守方向）
    r = fp.apply_affiliation(
        [fp.normalize_case(case())],
        [], fp.env_fingerprint({"python": "3.11"}),
        fp.env_fingerprint({"python": "3.12"}), baseline_ok=True)
    assert r["blockers"] == ["s1"]


def test_baseline_unavailable_fail_blocks_not_checked_unknown():
    r = fp.apply_affiliation(
        [fp.normalize_case(case()),
         fp.normalize_case(case(name="nc", status="not-checked", cause="external",
                                evidence="缺 X")),
         fp.normalize_case(case(name="ok2", status="pass")),
         fp.normalize_case(case(name="v", status="fail", reason="lock_busy",
                                cause="external", evidence="busy"))],
        [], fp.env_fingerprint({}), fp.env_fingerprint({}), baseline_ok=False)
    assert r["affiliation_confidence"] == "unknown(baseline_unavailable)"
    by = {v["name"]: v for v in r["verdicts"]}
    assert by["s1"]["verdict"] == "block"          # 真红必拦（保守）
    assert by["nc"]["verdict"] == "unknown"        # 答不了锅不硬裁
    assert by["ok2"]["verdict"] == "pass"          # 绿永不受牵连
    assert by["v"]["verdict"] == "block" and by["v"].get("violation")  # 违约照拦


def test_full_affiliation_pass_cases_never_block():
    r = fp.apply_affiliation(
        [fp.normalize_case(case(name="g", status="pass"))],
        [], fp.env_fingerprint({}), fp.env_fingerprint({}), baseline_ok=True)
    assert r["blockers"] == [] and r["verdicts"][0]["verdict"] == "pass"


# ---------------- 汇总 / 去重 ----------------

def test_recount_and_summarize():
    cases = [fp.normalize_case(case(name="a", status="pass")),
             fp.normalize_case(case(name="b")),
             fp.normalize_case(case(name="c", status="not-checked",
                                    evidence="ENV_FAIL: x"))]
    s = fp.summarize(cases, wall_s=12.34, concurrency=3, pool_config="main:3,ro:3",
                     env_fp="deadbeef", baseline_ref="main@abc")
    assert (s["ran"], s["pass"], s["fail"], s["not_checked"]) == (3, 1, 1, 1)
    assert s["wall_s"] == 12.3 and s["concurrency"] == 3
    assert s["env_fingerprint"] == "deadbeef" and s["baseline_ref"] == "main@abc"


def test_gate_recount_is_authority_vs_executor():
    # 执行器谎报（C6/C8）：闸以明细重算为准
    cases = [fp.normalize_case(case(name="a"))]
    executor_claimed = {"ran": 1, "pass": 1, "fail": 0}
    real = fp.recount(cases)
    assert real != executor_claimed and real["fail"] == 1


def test_dedupe_keeps_last_and_reports():
    c1 = fp.normalize_case(case(name="x", status="fail"))
    c2 = fp.normalize_case(case(name="x", status="pass"))
    out, dupes = fp.dedupe_cases([c1, c2])
    assert [c["status"] for c in out] == ["pass"] and dupes == ["x"]
    out, dupes = fp.dedupe_cases([c1])
    assert dupes == []


# ---------------- 闸拦→回执计数换算（走查 gen1 问题七覆盖） ----------------

def test_apply_gate_blockers_not_checked_moves_env_to_failed():
    f, e = fp.apply_gate_blockers(1, 2, {"a": "not-checked", "b": "not-checked"},
                                  ["a", "b"])
    assert (f, e) == (3, 0)


def test_apply_gate_blockers_fail_case_untouched():
    assert fp.apply_gate_blockers(1, 1, {"a": "fail"}, ["a"]) == (1, 1)


def test_apply_gate_blockers_unknown_case_counts_defensively():
    assert fp.apply_gate_blockers(0, 0, {}, ["ghost"]) == (1, 0)


def test_apply_gate_blockers_empty_noop():
    assert fp.apply_gate_blockers(2, 3, {"a": "fail"}, []) == (2, 3)


# ---------------- 超时标签语义（走查 gen1 问题④） ----------------

def test_timeout_reason_is_not_prepare_violation():
    c = fp.normalize_case(case(status="fail", reason="timeout",
                               evidence="超时（>900s）"))
    c2, viols = fp.enforce_semantics(c)
    assert c2["status"] == "fail" and not viols   # 超时按断言级红走归属表，不算违约


# ---------------- 260926 KI-122①「加保险」：活基线逐名答案（只读派生物） ----------------

def test_baseline_answers_red_green_and_no_answer():
    """逐名答案三态：基线 checked fail=red / 跑过且 pass=green / **没跑到或 not-checked
    或基线缺席或指纹不等=无答案**（缺名）。C1 口径：基线答不了锅时**不许冒充答案**。"""
    lane = [fp.normalize_case(case(name="a-red")),
            fp.normalize_case(case(name="b-green")),
            fp.normalize_case(case(name="c-uncovered")),
            fp.normalize_case(case(name="d-notchecked", status="not-checked",
                                   cause="external", reason="timeout",
                                   evidence="env red"))]
    base = [fp.normalize_case(case(name="a-red")),
            fp.normalize_case(case(name="b-green", status="pass", reason="ok",
                                   evidence="pass")),
            fp.normalize_case(case(name="d-notchecked", status="not-checked",
                                   cause="external", reason="timeout",
                                   evidence="env red"))]
    fp_v = {"value": "x"}
    ans = fp.baseline_answers(lane, base, fp_v, fp_v, True)
    assert ans == {"a-red": "red", "b-green": "green"}, ans
    assert "c-uncovered" not in ans and "d-notchecked" not in ans
    # 反例①：基线缺席（baseline_ok=False）→ 全无答案（绝不因缺席给「绿」）
    assert fp.baseline_answers(lane, base, fp_v, fp_v, False) == {}
    # 反例②：指纹不等 → 全无答案（不可比）
    assert fp.baseline_answers(lane, base, fp_v, {"value": "y"}, True) == {}
    # 反例③：畸形入参不抛（条目非 dict/名字空白/基线非列表）
    assert fp.baseline_answers([None, {}, {"name": "  "}], base, fp_v, fp_v, True) == {}
    assert fp.baseline_answers(lane, None, fp_v, fp_v, True) == {}
    # 与闸判定同源：同一输入下 decide 对 a-red 判 record、对 b-green 判 block（判据零改动）
    aff = fp.apply_affiliation(lane, base, fp_v, fp_v, True)
    assert set(aff["blockers"]) == {"b-green", "c-uncovered"}
    assert "a-red" in aff["records"]
    assert "d-notchecked" in aff["records"]      # not-checked×external=促治理不堵（record）
