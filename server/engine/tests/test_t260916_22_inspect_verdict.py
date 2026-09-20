"""t260916-22：发现级裁定面单测（inspection_trigger.cmd_verdict / deadman 排除）。

覆盖（工单验收④ + 方案 §4 步骤4）：
- CLI verdict 台账分支（--offline，零 Temporal）：载荷校验（词表/别名/who agent 拒收）、
  台账票面 findings[].verdict 原位改写、verdicts 台账追加、dedupe 幂等（重跑不重复
  落账）、finding-id 不在清单点名、坏台账不覆盖重建；
- 收口活动 write_inspection_verdicts：批量落账 + 幂等 + 畸形输入 fail-closed；
- signal 分支结构锁（票在途走 finding_verdict signal，回读校验）；
- deadman ledger_periods：verdicts/套件回执不进畸形桶（词法排除），periods 口径不变；
- 跨期压制闭环：verdict(假报) → 下期 collect_fake_ids 命中 → dedupe_and_suppress
  suppressed（组合子用例）。
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_deadman as deadman  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_trigger as trig  # noqa: E402


# ---------- 夹具 ----------

def _face_doc(ticket_id: str) -> dict:
    return {
        "ticket_id": ticket_id, "kind": "inspection", "instance_id": "inst",
        "period": "20260915", "heartbeat": False,
        "summary": {"high": 1, "med": 1, "low": 0},
        "findings": [
            {"id": "aa11bb22", "scan": "agent", "subject": "问题A", "severity": "high",
             "evidence": [{"path": "a.py", "line": 1, "quote": "x"}], "confidence": 0.9,
             "verified": "verified"},
            {"id": "cc33dd44", "scan": "agent", "subject": "问题C", "severity": "med",
             "evidence": [{"path": "c.py", "line": 3, "quote": "z"}], "confidence": 0.7,
             "verified": "verified"},
        ],
        "suggested_fix_tickets": [],
    }


@pytest.fixture()
def ledger(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "inspection"
    d.mkdir()
    (d / "inspection-inst-20260915.json").write_text(
        json.dumps(_face_doc("t260915-01"), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(d))
    return d


def _args(**kw):
    base = {"instance": "inst", "finding_id": "aa11bb22", "verdict": "假报",
            "who": "宿主", "note": "误报", "period": "20260915", "offline": True}
    base.update(kw)
    return argparse_ns(base)


class argparse_ns:
    def __init__(self, d: dict):
        self.__dict__.update(d)


# ---------- CLI verdict：台账分支 ----------

def test_verdict_ledger_leg_books_face_and_receipts(ledger: Path):
    res = asyncio.run(trig.cmd_verdict(_args()))
    assert res["ok"] is True and res["result"]["mode"] == "ledger", res
    face = json.loads((ledger / "inspection-inst-20260915.json").read_text(encoding="utf-8"))
    f0 = next(f for f in face["findings"] if f["id"] == "aa11bb22")
    assert f0["verdict"] == "false-positive" and f0["verdict_who"] == "宿主"
    assert f0["verdict_note"] == "误报"
    untouched = next(f for f in face["findings"] if f["id"] == "cc33dd44")
    assert "verdict" not in untouched
    vpath = ledger / "inspection-inst-20260915-verdicts.json"
    entries = json.loads(vpath.read_text(encoding="utf-8"))["entries"]
    assert len(entries) == 1 and entries[0]["source_ticket"] == "t260915-01"
    # 重跑=幂等（dedupe 不重复落账；票面幂等覆盖）
    res2 = asyncio.run(trig.cmd_verdict(_args()))
    assert res2["ok"] is True
    entries2 = json.loads(vpath.read_text(encoding="utf-8"))["entries"]
    assert len(entries2) == 1, "dedupe：同内容（逐键全等）重放不重复落"
    # 改口（同发现换裁定）=新裁定必追加——裁定演进全留痕，取最新消费
    res3 = asyncio.run(trig.cmd_verdict(_args(verdict="存疑", note="复核改口")))
    assert res3["ok"] is True
    entries3 = json.loads(vpath.read_text(encoding="utf-8"))["entries"]
    assert len(entries3) == 2 and entries3[-1]["verdict"] == "doubt"
    face = json.loads((ledger / "inspection-inst-20260915.json").read_text(encoding="utf-8"))
    f0 = next(f for f in face["findings"] if f["id"] == "aa11bb22")
    assert f0["verdict"] == "doubt" and f0["verified"] == "doubt"


def test_verdict_ledger_leg_rejections(ledger: Path):
    for mut, why in [
        ({"verdict": "maybe"}, "越域"),
        ({"who": "developer"}, "agent"),
        ({"who": ""}, "who"),
        ({"finding_id": ""}, "finding-id"),
        ({"finding_id": "zzzzzzzz"}, "不在本票发现清单"),
        ({"period": "bad-period"}, "period"),
    ]:
        res = asyncio.run(trig.cmd_verdict(_args(**mut)))
        assert res["ok"] is False and why in res["error"], (mut, res)


def test_verdict_bad_ledger_not_rebuilt(ledger: Path):
    bad = ledger / "inspection-inst-20260914.json"
    bad.write_text("nonsense{", encoding="utf-8")
    res = asyncio.run(trig.cmd_verdict(_args(period="20260914")))
    assert res["ok"] is False and "不可读" in res["error"]
    assert bad.read_text(encoding="utf-8") == "nonsense{", "绝不覆盖重建坏台账"


def test_verdict_missing_face_named(ledger: Path):
    res = asyncio.run(trig.cmd_verdict(_args(period="20260901")))
    assert res["ok"] is False and "不存在" in res["error"]


def test_verdict_signal_leg_structure():
    """票在途走 finding_verdict signal（结构锁：signal 名/回读校验在位）。"""
    import inspect
    src = inspect.getsource(trig.cmd_verdict)
    assert 'signal("finding_verdict"' in src
    assert 'mode": "signal"' in src or '"mode": "signal"' in src
    assert "resolve_period_ticket_id" in src
    flow_src = (POC / "inspection_flow.py").read_text(encoding="utf-8")
    assert "def finding_verdict" in flow_src, "workflow 侧 signal handler 在位"


# ---------- 收口活动 write_inspection_verdicts ----------

def test_write_inspection_verdicts_activity(ledger: Path, monkeypatch):
    from activities import write_inspection_verdicts
    entries = [{"finding_id": "aa11bb22", "verdict": "false-positive", "who": "宿主",
                "note": "", "source_ticket": "t260916-01"},
               {"finding_id": "cc33dd44", "verdict": "to-fix", "who": "宿主",
                "note": "实锤", "source_ticket": "t260916-01"}]
    # 显式 ledger_dir（INSPECTION_DIR 是 shared import 时常量，UT 指路不靠 env 时序）
    ld = {"ledger_dir": str(ledger)}
    res = asyncio.run(write_inspection_verdicts(
        {"instance_id": "inst", "period": "20260915", "entries": entries, **ld}))
    assert res["ok"] is True and res["result"]["written"] == 2
    # 收口重放（Temporal 至少一次）→ 全部 dedupe 跳过
    res2 = asyncio.run(write_inspection_verdicts(
        {"instance_id": "inst", "period": "20260915", "entries": entries, **ld}))
    assert res2["result"]["written"] == 0 and res2["result"]["skipped"] == 2
    vpath = ledger / "inspection-inst-20260915-verdicts.json"
    entries_out = json.loads(vpath.read_text(encoding="utf-8"))["entries"]
    assert [e["finding_id"] for e in entries_out] == ["aa11bb22", "cc33dd44"]
    assert all(e.get("booked_at") for e in entries_out)
    # 畸形输入 fail-closed
    for mut in [{"instance_id": "", "period": "20260915", "entries": entries},
                {"instance_id": "inst", "period": "20260915", "entries": "x"},
                {"instance_id": "inst", "period": "20260915",
                 "entries": [{"finding_id": "", "verdict": "to-fix"}]}]:
        res = asyncio.run(write_inspection_verdicts(mut))
        assert res["ok"] is False, mut


# ---------- deadman 词法排除 ----------

def test_deadman_excludes_verdicts_and_suite_receipts(ledger: Path, monkeypatch):
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(ledger))
    (ledger / "inspection-inst-20260916.json").write_text(
        json.dumps(_face_doc("t260916-01"), ensure_ascii=False), encoding="utf-8")
    (ledger / "inspection-inst-20260916-suite.json").write_text("{}", encoding="utf-8")
    (ledger / "inspection-inst-20260915-verdicts.json").write_text(
        json.dumps({"entries": [{"finding_id": "aa11bb22",
                                 "verdict": "false-positive"}]}, ensure_ascii=False),
        encoding="utf-8")
    (ledger / "inspection-inst-not-a-period.json").write_text("{}", encoding="utf-8")
    out = deadman.ledger_periods(ledger, "inst")
    assert out["periods"] == {"20260915", "20260916"}
    assert out["malformed"] == ["inspection-inst-not-a-period.json"]
    # 双源一致性：deadman 的排除后缀与 inspection_inspect 单源同值
    assert deadman.VERDICTS_RECEIPT_SUFFIX == ins.VERDICTS_RECEIPT_SUFFIX


# ---------- 跨期压制闭环（组合子用例） ----------

def test_fake_verdict_suppresses_next_period(ledger: Path):
    (ledger / "inspection-inst-20260915-verdicts.json").write_text(
        json.dumps({"entries": [{"finding_id": "aa11bb22",
                                 "verdict": "false-positive", "who": "宿主"}]},
                   ensure_ascii=False), encoding="utf-8")
    fake, notes = ins.collect_fake_ids(ledger, "inst", "20260916")
    assert fake == {"aa11bb22"} and notes == []
    # id 与上期台账同源（真实链路里=同内容铸出同 id；此处直给对照 id）
    findings = [{"subject": "问题A", "severity": "high",
                 "evidence": [{"path": "a.py", "line": 1, "quote": "x"}],
                 "why": "w", "suggestion": "", "confidence": 0.9,
                 "id": "aa11bb22", "scan": "agent"}]
    ins.dedupe_and_suppress(findings, set(), fake)
    assert findings[0]["suppressed"] is True
    assert findings[0]["verdict"] == "false-positive"
    assert ins.summarize_counts(findings) == {"high": 0, "med": 0, "low": 0}
    assert ins.heartbeat_of(findings) is True
