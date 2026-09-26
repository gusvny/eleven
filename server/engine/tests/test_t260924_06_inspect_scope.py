"""t260924-06：inspect 段缩面（本期变化面定向审）回归棒。

覆盖（方案 v2 U1~U8；审查面缩面=「本期有什么新病灶」不是全仓普查）：
- U1/U2 parse_name_status 常规+畸形行容错、整体空=diff_error 点名；
- U3 suite_receipt_rows 坏 JSON/顶层非 dict/缺键 → suite_note 点名不炸；
- U4 ki_open_entries 文件缺失/零条目 → ki_note 点名；
- U5 上期台账缺 lane.base_ref / doc 缺失 → scope_note「无基点差分」，绝不回落全仓；
- U6 build_change_scope_text 硬上限截断：meta.truncated + scope_block 点名双断言；
- U7 端到端（SANDBAR_INSPECT_CMD 假脚本，真进程链零模型调用）：prompt 含给定清单
  与「禁止 spawn 子代理」、空 findings 强 schema 结果 ok+meta.scope 在册（预算内）、
  build_ticket_face 零发现渲染「本期无新病灶」附证据面；
- U8 桩夹具缺文件 → 既有 _err 短路语义（U8 由既有测试钉过，此处补 stub meta.scope）。
"""
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from temporalio import activity as activity_mod

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_flow as flow  # noqa: E402


# ---------------------------------------------------------------- U1 parse_name_status

def test_u1_parse_name_status_normal_and_malformed():
    rows, meta = ins.parse_name_status("M\ta.py\nA\tb/c.py\n")
    assert rows == ["M\ta.py", "A\tb/c.py"] and meta == {}
    rows, meta = ins.parse_name_status("烂行\n\x00bin\nM\tok.py\n\nR100\told.py")
    assert rows == ["M\tok.py"]
    assert meta["diff_malformed_lines"] == 3      # 烂行 + \0 行 + R100 双列


def test_u2_parse_name_status_empty_named():
    rows, meta = ins.parse_name_status("")
    assert rows == [] and "diff_error" in meta
    rows, meta = ins.parse_name_status("\n\n")
    assert rows == [] and "diff output is empty" in meta["diff_error"]   # 260927 报告英文面


# ---------------------------------------------------------------- U3 suite_receipt_rows

def test_u3_suite_receipt_rows_malformed_fail_closed(tmp_path):
    rows, meta = ins.suite_receipt_rows(tmp_path / "absent.json")
    assert rows == [] and "suite receipt" in meta["suite_note"] \
        and "not part of the review scope" in meta["suite_note"]   # 260927 报告英文面
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    rows, meta = ins.suite_receipt_rows(bad)
    assert rows == [] and "unreadable" in meta["suite_note"]   # 260927 报告英文面
    notdict = tmp_path / "arr.json"
    notdict.write_text("[]", encoding="utf-8")
    rows, meta = ins.suite_receipt_rows(notdict)
    assert rows == [] and "not a mapping at the top level" in meta["suite_note"]  # 英文面
    # 常规：error/env_fail/ran=0/details 红条目照收
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"error": "场景执行器整体超时", "env_fail": 0, "ran": 0,
                              "details": [{"name": "sc_x.py", "status": "FAIL"}]}),
                  encoding="utf-8")
    rows, meta = ins.suite_receipt_rows(ok)
    assert any("整体异常" in r for r in rows) and any("sc_x.py" in r for r in rows)
    assert meta == {}


# ---------------------------------------------------------------- U4 ki_open_entries

def test_u4_ki_open_entries_missing_and_empty(tmp_path):
    rows, meta = ins.ki_open_entries(tmp_path / "absent.md")
    assert rows == [] and "KI register unreadable" in meta["ki_note"]   # 260927 报告英文面
    empty = tmp_path / "ki.md"
    empty.write_text("# 已全部关闭\n", encoding="utf-8")
    rows, meta = ins.ki_open_entries(empty)
    assert rows == [] and "no open entries or is unparseable" in meta["ki_note"]  # 英文面
    ok = tmp_path / "ki2.md"
    ok.write_text("- KI-009 组粒度回收 open：待修\n- KI-002 closed\n", encoding="utf-8")
    rows, meta = ins.ki_open_entries(ok)
    assert len(rows) == 1 and "KI-009" in rows[0] and meta == {}


# ---------------------------------------------------------------- U5 无基点差分（活动级）

@pytest.fixture()
def base_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "src.py").write_text("value = 1\n", encoding="utf-8")
    return d


def _args(base: Path, tmp: Path, **kw) -> dict:
    a = {"instance_id": "inst", "period": "20260926", "ticket_id": "t1",
         "face": "test", "base_dir": str(base),
         "agent_home": str(tmp / "agent-home"), "timeout_sec": 120}
    a.update(kw)
    return a


@pytest.fixture()
def beats(monkeypatch):
    """活动上下文外的 heartbeat 直录（temporalio 活动外调用本会 raise）。"""
    got = []
    monkeypatch.setattr(activity_mod, "heartbeat", lambda *a, **k: got.append(a))
    return got


def test_u5_no_prev_base_no_full_repo_fallback(base_dir, tmp_path, monkeypatch, beats):
    """上期台账缺 lane.base_ref：scope_note 点名「无基点差分」，scope 文件数=0——
    绝不回落全仓（缩面纪律在畸形路径下依然成立）。"""
    monkeypatch.setenv("SANDBAR_INSPECT_STUB", "1")
    fixture = tmp_path / "fixture.json"
    fixture.write_text("```json\n%s\n```\n" % json.dumps({"findings": []}),
                       encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(fixture))
    # 烂字段形态：lane 在但 base_ref 非串
    ledger = tmp_path / "inspection-inst-20260923.json"
    ledger.write_text(json.dumps({"findings": [], "lane": {"base_ref": 123}}),
                      encoding="utf-8")
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is True
    scope = res["result"]["meta"]["scope"]
    assert scope["scope_files"] == 0
    assert "无基点差分" in scope["scope_note"]
    block_prompt_notes = [k for k in ("diff_error", "scope_note") if scope.get(k)]
    assert block_prompt_notes


# ---------------------------------------------------------------- U6 硬上限截断

def test_u6_change_scope_text_truncation_named():
    rows = ["M\tf%03d.py" % i for i in range(10)]
    block, meta = ins.build_change_scope_text(rows, [], [], {}, "", 1, 4)
    assert meta["scope_files"] == 4 and meta["truncated"] == 6
    assert "截断弃置 6 个" in block and "M\tf003.py" in block and "M\tf004.py" not in block
    block, meta = ins.build_change_scope_text(rows[:2], [], [], {}, "", 4, 40)
    assert "truncated" not in meta and "截断" not in block
    # 空变化面：显式「本期变化面为空」，不空转
    block, meta = ins.build_change_scope_text([], [], [], {}, "", 4, 40)
    assert "本期变化面为空" in block and meta["scope_files"] == 0


# ---------------------------------------------------------------- U7 端到端（假脚本真链）

@pytest.fixture()
def fake_dsh(tmp_path: Path):
    """假 dsh 脚本：把收到的 prompt 存档，末尾输出恰一块空 findings 围栏，exit 0。"""
    out = tmp_path / "fake_prompt_capture.txt"
    script = tmp_path / "fake_dsh.py"
    script.write_text(
        "import sys\n"
        "open(%r, 'w', encoding='utf-8').write(sys.argv[-1])\n"
        "print('审查完毕（零发现）')\n"
        "print('```json')\n"
        "print('{\"findings\": []}')\n"
        "print('```')\n" % str(out), encoding="utf-8")
    sh = tmp_path / "fake_dsh.sh"
    sh.write_text("#!/bin/sh\nexec %s %s \"$@\"\n"
                  % (sys.executable, script), encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    return sh, out


def test_u7_e2e_scoped_prompt_and_explicit_zero_findings(
        base_dir, tmp_path, monkeypatch, fake_dsh, beats):
    monkeypatch.delenv("SANDBAR_INSPECT_STUB", raising=False)
    sh, capture = fake_dsh
    monkeypatch.setenv("SANDBAR_INSPECT_CMD", "%s --patch p1 --patch p2" % sh)
    # 上期台账（带基点）+ 套件回执 + KI 册齐全 → 四路输入进 prompt
    ledger = tmp_path / "inspection-inst-20260923.json"
    ledger.write_text(json.dumps({
        "findings": [{"id": "abcdef12", "subject": "旧发现", "severity": "low"}],
        "lane": {"base_ref": "deadbeef"}}), encoding="utf-8")
    suite = tmp_path / "inspection-inst-20260926-suite.json"
    suite.write_text(json.dumps({"error": "", "env_fail": 0, "ran": 0, "details": []}),
                     encoding="utf-8")
    ki = base_dir / "notes" / "debts"
    ki.mkdir(parents=True)
    (ki / "known-issues.md").write_text("- KI-001 例子 open\n", encoding="utf-8")
    res = asyncio.run(aa.run_inspection_inspect(_args(
        base_dir, tmp_path, base_head="cafebabe",
        suite_receipt=str(suite), ledger_dir=str(tmp_path))))
    assert res["ok"] is True, res
    result = res["result"]
    # 强 schema 结果（零发现也显式）+ 预算内（假脚本秒级，远小于预算）
    assert result["findings"] == []
    assert result["meta"]["scope"]["scope_files"] == 0      # 无真 git 仓 → diff_error 回落
    assert "diff_error" in result["meta"]["scope"]
    assert result["meta"]["used_sec"] < 60
    # prompt 含给定清单与硬规则（不靠 agent 自律）
    prompt = capture.read_text(encoding="utf-8")
    assert "审查范围=本清单" in prompt and "禁止 spawn 任何子代理" in prompt
    assert "ran=0" in prompt or "零运行" in prompt
    assert "KI-001" in prompt
    assert "旧发现" in prompt
    # 票面：零发现渲染「本期无新病灶」附证据面
    face = flow.build_ticket_face("t1", "inst", "20260926", {
        "findings": [], "summary": {"high": 0, "med": 0, "low": 0},
        "meta": {"inspect": {"scope": result["meta"]["scope"]}}})
    note = face["zero_findings_note"]
    # 260927 报告英文面（宿主令）：零发现声明的措辞改英文——断言 re-point（意图不变）
    assert "No new defects this period" in note and "input face named" in note \
        and "diff_error" in note
    # 有发现时绝不出零发现声明（对偶断言）
    face2 = flow.build_ticket_face("t1", "inst", "20260926", {
        "findings": [{"subject": "s", "severity": "low", "scan": "agent"}],
        "summary": {"high": 0, "med": 0, "low": 1}})
    assert "zero_findings_note" not in face2


# ---------------------------------------------------------------- U8 桩夹具缺文件

def test_u8_stub_missing_fixture_and_scope_in_stub_meta(base_dir, tmp_path, monkeypatch, beats):
    monkeypatch.setenv("SANDBAR_INSPECT_STUB", "1")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(tmp_path / "absent.json"))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is False and "夹具缺失" in res["error"]
    # 桩路径 meta 也带 scope（零发现显式证据面对桩面同样在册）
    fixture = tmp_path / "fixture.json"
    fixture.write_text("```json\n{\"findings\": []}\n```\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(fixture))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is True and res["result"]["findings"] == []
    assert "scope" in res["result"]["meta"]
