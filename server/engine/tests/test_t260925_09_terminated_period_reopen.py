"""t260925-09 / KI-114 单测：终止期票不得永久吞掉期槽位（状态感知去重）。

病根（票面实测 20260924-25）：终止票 SA 章仍在 → find_period_ticket_ids 命中即
deduped；指针层 describe 只验「在+身份符」→ 第二重堵死。修复口径：
  - RUNNING/CONTINUED_AS_NEW=live → deduped（活期防并发，语义不变）；
  - COMPLETED=served → deduped（防台账双计）；
  - CANCELED/TERMINATED=freed → 清残指针+铸新号重开，审计链接三处
    （回执 superseded_ticket_id / 新指针 payload supersedes_ticket_id /
    inspection-reopen.jsonl 一行 JSON）；
  - FAILED/TIMED_OUT/未知/瞬态不可判 → fail-closed 显式报错，绝不静默开第二张。
  - ledger/deadman 会计：reopen journal（.jsonl）不进期号集合，同期两 run 不双计期。

UT 全程禁网络/真 Temporal；夹具复用 test_t260916_02 的 FakeClient 形制（岗位纪律
允许的夹具共享，非照搬故障模式取舍）。
运行：server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t260925_09_terminated_period_reopen.py -q
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import inspection_ticketing as tick  # noqa: E402
import shared  # noqa: E402
from test_t260916_02_inspection_ticketing import (  # noqa: E402
    FakeClient, FakeWf, FakeHandle, FakeDesc)

INS = shared.INSPECTION_INSTANCE_SA_NAME
PER = shared.INSPECTION_PERIOD_SA_NAME
INST = "integration-tests"
PERIOD = "20260916"


def open_ticket(client, tmp_path, **kw):
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(tmp_path / "ledger")
    try:
        base = dict(instance_id=INST, period=PERIOD, project_key="sandbar",
                    repo_root="/repo", scan_face="test", decl_path="", task_queue="tq")
        base.update(kw)
        return asyncio.run(tick.open_period_ticket(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def journal_of(tmp_path):
    return tmp_path / "ledger" / tick.REOPEN_JOURNAL_NAME


def sa_ticket(tid, status, tmp_path=None):
    return FakeWf(tid, status=status, sa={INS: INST, PER: PERIOD})


# ============================================================ 纯面：状态分类

def test_period_slot_verdict_classification():
    assert tick.period_slot_verdict("RUNNING") == "live"
    assert tick.period_slot_verdict("CONTINUED_AS_NEW") == "live"
    assert tick.period_slot_verdict("COMPLETED") == "served"
    assert tick.period_slot_verdict("CANCELED") == "freed"
    assert tick.period_slot_verdict("TERMINATED") == "freed"
    # 畸形输入 fail-closed：空/未知枚举/非串一律 ambiguous，绝不当释放；
    # 已知枚举名的大小写/空白变化属归一化（照常分类，非「猜」）
    assert tick.period_slot_verdict("running") == "live"
    assert tick.period_slot_verdict("  terminated  ") == "freed"
    for bad in ("", None, "FAILED", "TIMED_OUT", "WEIRD_STATE", 123, object()):
        assert tick.period_slot_verdict(bad) == "ambiguous"


# ============================================================ SA 层：终止票放行重开

def test_sa_hit_terminated_reopens_new_ticket_with_audit_chain(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "TERMINATED")])
    (tmp_path / "ledger").mkdir(parents=True)
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-04"          # 终止票占 03，新票取 04
    assert res["result"]["superseded_ticket_id"] == "t260916-03"
    assert res["result"]["deduped"] is False
    # 新票 SA 章齐全（活期去重语义不因重开丢失）
    st = client.started[0]
    assert st["sa"].get(INS) == INST and st["sa"].get(PER) == PERIOD
    assert st["payload"].supersedes_ticket_id == "t260916-03"  # 审计链接之二：input
    # 审计链接之三：reopen journal 一行合法 JSON，链接终止票与新票
    lines = journal_of(tmp_path).read_text("utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["terminated_ticket_id"] == "t260916-03"
    assert entry["new_ticket_id"] == "t260916-04"
    assert entry["instance"] == INST and entry["period"] == PERIOD
    # 新指针 payload 也带 supersedes（审计链接之一；指针此时仍在——票活着）
    ptr = json.loads((tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD)))
                     .read_text("utf-8"))
    assert ptr["ticket_id"] == "t260916-04"
    assert ptr["supersedes_ticket_id"] == "t260916-03"


def test_sa_hit_canceled_reopens_too(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "CANCELED")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-04"


def test_sa_hit_completed_still_dedups_no_double_count(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "COMPLETED")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["period_state"] == "completed"
    assert res["result"]["ticket_id"] == "t260916-03"
    assert client.started == []                      # 已服务期绝不重开（防双计）
    assert not journal_of(tmp_path).exists()


def test_sa_hit_failed_and_unknown_fail_closed(tmp_path):
    for status in ("FAILED", "TIMED_OUT", "SOMETHING_ELSE", ""):
        client = FakeClient([sa_ticket("t260916-03", status)])
        res = open_ticket(client, tmp_path)
        assert not res["ok"], status
        assert status in res["error"] or "ambiguous" in res["error"]
        assert client.started == []                  # 绝不静默开第二张
        assert not journal_of(tmp_path).exists()


def test_sa_hit_transient_describe_fail_closed(tmp_path):
    class FlakyHandle(FakeHandle):
        async def describe(self):
            raise RuntimeError("RPC unavailable: transient")
    class FlakyClient(FakeClient):
        def get_workflow_handle(self, tid):
            return FlakyHandle(self, tid)
    client = FlakyClient([sa_ticket("t260916-03", "RUNNING")])
    res = open_ticket(client, tmp_path)
    assert not res["ok"] and "不可判" in res["error"]
    assert client.started == []


def test_reopen_journal_malformed_existing_content_does_not_block(tmp_path):
    (tmp_path / "ledger").mkdir(parents=True)
    journal_of(tmp_path).write_text("not json at all\n{\"broken\": \n", encoding="utf-8")
    client = FakeClient([sa_ticket("t260916-03", "TERMINATED")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True   # 只写不读：畸形行不阻断
    lines = journal_of(tmp_path).read_text("utf-8").strip().splitlines()
    assert len(lines) == 3 and json.loads(lines[-1])["new_ticket_id"] == "t260916-04"


# ============================================================ 指针层：指向终止票

def test_pointer_to_terminated_ticket_cleared_and_reopen(tmp_path):
    old = sa_ticket("t260916-03", "TERMINATED")
    client = FakeClient([old])
    (tmp_path / "ledger").mkdir(parents=True)
    ptr = tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD))
    tick.claim_pointer(ptr, INST, PERIOD, "t260916-03", "sandbar")
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-04"
    assert res["result"]["superseded_ticket_id"] == "t260916-03"
    assert any("t260916-03" in c for c in res["result"]["stale_pointer_cleared"])
    assert json.loads(ptr.read_text("utf-8"))["ticket_id"] == "t260916-04"


def test_pointer_to_failed_ticket_fail_closed(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "FAILED")])
    (tmp_path / "ledger").mkdir(parents=True)
    tick.claim_pointer(tmp_path / ("inspection-%s-%s.ticket" % (INST, PERIOD)),
                       INST, PERIOD, "t260916-03", "sandbar")
    res = open_ticket(client, tmp_path)
    assert not res["ok"] and "FAILED" in res["error"]
    assert client.started == []


# ============================================================ 活期防并发（规格红线）

def test_after_reopen_second_trigger_dedups_live_no_third_ticket(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "TERMINATED")])
    res1 = open_ticket(client, tmp_path)
    assert res1["ok"] and res1["result"]["triggered"] is True
    # 重开成功后再次 trigger：新票 RUNNING → deduped，绝不出第三张
    res2 = open_ticket(client, tmp_path)
    assert res2["ok"] and res2["result"]["deduped"] is True
    assert res2["result"]["ticket_id"] == "t260916-04"
    assert res2["result"]["period_state"] == "live"
    assert len(client.started) == 1
    assert len(journal_of(tmp_path).read_text("utf-8").strip().splitlines()) == 1


def test_legacy_input_cls_without_supersedes_key_still_reopens(tmp_path):
    # 兼容面：旧 input 类不认 supersedes_ticket_id 键 → TypeError 收敛路照常起票
    class OldInput:
        def __init__(self, instance_id, period, repo_root, face):
            self.instance_id, self.period = instance_id, period
    client = FakeClient([sa_ticket("t260916-03", "TERMINATED")])
    res = open_ticket(client, tmp_path, input_cls=OldInput)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-04"
    assert res["result"]["superseded_ticket_id"] == "t260916-03"


# ============================================================ 会计：不双计期、journal 不入账

def test_ledger_periods_counts_period_once_with_two_runs_and_journal(tmp_path):
    from inspection_deadman import ledger_periods
    d = tmp_path / "ledger"
    d.mkdir(parents=True)
    # 同期两 run：终止票写过的台账票面 + 重开新票写同名票面（实例+期单文件），
    # 外加 reopen journal 与指针——期号集合必须仍只有一期
    (d / ("inspection-%s-%s.json" % (INST, PERIOD))).write_text("{}", encoding="utf-8")
    (d / tick.REOPEN_JOURNAL_NAME).write_text("{}\n", encoding="utf-8")
    (d / ("inspection-%s-%s.ticket" % (INST, PERIOD))).write_text("{}", encoding="utf-8")
    out = ledger_periods(d, INST)
    assert out["periods"] == {PERIOD} and out["count"] == 1
    assert out["malformed"] == []          # journal/指针不进畸形桶


def test_resolve_period_ticket_id_picks_live_among_terminated(tmp_path):
    wfs = [sa_ticket("t260916-03", "TERMINATED"), sa_ticket("t260916-04", "RUNNING")]
    res = asyncio.run(tick.resolve_period_ticket_id(FakeClient(wfs), INST, PERIOD))
    assert res["ok"] and res["ticket_id"] == "t260916-04"
    assert res["superseded"] == ["t260916-03"]
    # 多张活票仍是每期一票破坏，fail-closed 不猜
    wfs2 = [sa_ticket("t260916-04", "RUNNING"), sa_ticket("t260916-05", "RUNNING")]
    res2 = asyncio.run(tick.resolve_period_ticket_id(FakeClient(wfs2), INST, PERIOD))
    assert not res2["ok"] and "活" in res2["error"]
    # 全终止单张：resolve 如实返回票号但 live=False（管理面不承接在途操作）
    wfs3 = [sa_ticket("t260916-03", "TERMINATED")]
    res3 = asyncio.run(tick.resolve_period_ticket_id(FakeClient(wfs3), INST, PERIOD))
    assert res3["ok"] and res3["ticket_id"] == "t260916-03" and res3["live"] is False
    res4 = asyncio.run(tick.resolve_period_ticket_id(FakeClient([]), INST, PERIOD))
    assert not res4["ok"]


def test_sa_hit_multi_terminated_reopens_with_joined_superseded(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "TERMINATED"),
                         sa_ticket("t260916-04", "CANCELED")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-05"
    assert res["result"]["superseded_ticket_id"] == "t260916-03,t260916-04"
    assert len(client.started) == 1 and len(client.wfs) == 3


def test_sa_hit_served_plus_freed_complex_history_fail_closed(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "COMPLETED"),
                         sa_ticket("t260916-04", "TERMINATED")])
    res = open_ticket(client, tmp_path)
    assert not res["ok"] and "人工" in res["error"]
    assert client.started == []


# ============================================================ 260926 宿主令：具名重跑
# 「不能手动 trigger 一次巡检吗，这个是应该支持的」→ reopen_reason（非空＝人工具名）：
# 已服务(COMPLETED)/FAILED/TIMED_OUT/未知 槽位可重开（与终止票同路，审计三处+jounral
# 落 reason）；在飞期（live）仍拒；空串＝既有语义逐字不变（上面各测试即回归锁）。

class _BlindListClient(FakeClient):
    """SA 查询面「看不见」但 describe 可见（可见性滞后的真实形态）——专打指针层分支。"""

    async def list_workflows(self, query):
        return
        yield  # pragma: no cover —— 仅维持 async generator 形状


def test_reopen_reason_reruns_served_period(tmp_path):
    client = FakeClient([sa_ticket("t260916-03", "COMPLETED")])
    res = open_ticket(client, tmp_path, reopen_reason="宿主令：本期重跑（首验零信号修复）")
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["ticket_id"] == "t260916-04"
    assert res["result"]["superseded_ticket_id"] == "t260916-03"
    assert res["result"]["deduped"] is False
    assert res["result"]["reopen_reason"].startswith("宿主令")
    lines = journal_of(tmp_path).read_text("utf-8").strip().splitlines()
    entry = json.loads(lines[-1])          # 审计链接：被替代票 → 新票 + 具名理由
    assert entry["terminated_ticket_id"] == "t260916-03"
    assert entry["new_ticket_id"] == "t260916-04"
    assert entry["reason"].startswith("宿主令")
    assert len(client.started) == 1


def test_served_dedup_receipt_carries_reopen_hint(tmp_path):
    """不带具名：既有 dedup 语义不变，但回执给出重跑入口提示（ops 面可发现性）。"""
    client = FakeClient([sa_ticket("t260916-03", "COMPLETED")])
    res = open_ticket(client, tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert "reopen_reason" in res["result"]["reopen_hint"]
    assert client.started == []


def test_reopen_reason_reruns_ambiguous_failed_period(tmp_path):
    for status in ("FAILED", "TIMED_OUT", "SOMETHING_ELSE"):
        client = FakeClient([sa_ticket("t260916-03", status)])
        res = open_ticket(client, tmp_path, reopen_reason="人工裁定重跑 %s" % status)
        assert res["ok"] and res["result"]["triggered"] is True, status
        assert res["result"]["superseded_ticket_id"] == "t260916-03"
        assert len(client.started) == 1


def test_reopen_reason_refuses_live_period(tmp_path):
    """在飞期不接受重开：重跑＝双跑同一期（并发两套 suite）。"""
    client = FakeClient([sa_ticket("t260916-03", "RUNNING")])
    res = open_ticket(client, tmp_path, reopen_reason="想立刻重跑")
    assert not res["ok"] and "在飞" in res["error"]
    assert client.started == []
    assert not journal_of(tmp_path).exists()


def test_reopen_reason_pointer_layer_served_reruns(tmp_path):
    """指针层（SA 面看不见）：指向已服务票 + 具名 → 清指针、铸新号重开。"""
    client = _BlindListClient([sa_ticket("t260916-03", "COMPLETED")])
    (tmp_path / "ledger").mkdir(parents=True)
    ptr = tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD))
    tick.claim_pointer(ptr, INST, PERIOD, "t260916-03", "sandbar")
    res = open_ticket(client, tmp_path, reopen_reason="指针层具名重跑")
    assert res["ok"] and res["result"]["triggered"] is True
    assert res["result"]["superseded_ticket_id"] == "t260916-03"
    assert any("已服务期" in c for c in res["result"]["stale_pointer_cleared"])


def test_reopen_reason_pointer_layer_live_refused(tmp_path):
    client = _BlindListClient([sa_ticket("t260916-03", "RUNNING")])
    (tmp_path / "ledger").mkdir(parents=True)
    tick.claim_pointer(tmp_path / "ledger" / ("inspection-%s-%s.ticket" % (INST, PERIOD)),
                       INST, PERIOD, "t260916-03", "sandbar")
    res = open_ticket(client, tmp_path, reopen_reason="指针层想立刻重跑")
    assert not res["ok"] and "在飞" in res["error"]
    assert client.started == []
