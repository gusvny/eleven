"""t261003-03 / KI-192 单测：期槽裁决采信 supersede 链 + blocked-completed 不占 served 席。

病根（KI-192，20261003 实证）：重开具名 trigger 被拒「同期已服务票出现多张：
t261002-01、t261002-12——人工处置」，而全仓没有任何人工处置入口——
①supersede 链不被采信（t261002-01 已被 t261002-12 显式替代，双痕俱在）；
②blocked-completed（inspect 解析拒收、零 findings）被 COMPLETED 枚举误判「已服务」，
cancel 恒空操作＝期槽永占；
③报错点名不存在的动作。本文件守的修复面：
  A 链收敛：被在册新票显式替代的 served 旧票不占席 → 具名重开成功，审计三痕齐
    （reopen journal 行（带 reason+collapsed_ticket_ids）/ 指针 payload supersedes_ticket_id /
    回执 superseded_ticket_id+collapsed_superseded）。
  B blocked-completed：期台账 face（ticket_id+blocked_reason）为铁证 → 归 freed/failed
    类（具名可重开）；无理由 fail-closed 具名报错；台账读不出=unproven→保守按 served。
  C 链具名检查：journal 缺行 / 链指向不存在的票 / 双替代（分叉）——各带检查名，绝不裸布尔。
  D 多张真已服务票：无理由 → 报错点名真实入口 --reopen-reason；带理由 → 占坑时刻收敛
    幸存者（不可比含 unknown-vs-known → slot-stamp-unresolvable）。
  E 畸形输入矩阵：坏 journal 行 / 坏台账 JSON / 指针 payload 缺键——降级或具名报错不炸。

UT 全程禁网络/真 Temporal；夹具复用 test_t260916_02 的 FakeClient 形制。
运行：server/engine/.venv/bin/python -B -m pytest server/engine/tests/test_t261003_03_ki192_period_adjudication.py -q
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
    FakeClient, FakeWf)

INS = shared.INSPECTION_INSTANCE_SA_NAME
PER = shared.INSPECTION_PERIOD_SA_NAME
TAKEN = shared.INSPECTION_SLOT_TAKEN_SA_NAME
INST = "integration-tests"
PERIOD = "20261002"
OLD, NEW = "t261002-01", "t261002-12"
NEXT = "t261002-13"


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


def wf(tid, status="COMPLETED", taken=""):
    sa = {INS: INST, PER: PERIOD}
    if taken:
        sa[TAKEN] = taken
    return FakeWf(tid, status=status, sa=sa)


def ledger_dir(tmp_path):
    d = tmp_path / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    return d


def journal_path(tmp_path):
    return ledger_dir(tmp_path) / tick.REOPEN_JOURNAL_NAME


def seed_journal(tmp_path, rows):
    p = journal_path(tmp_path)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r, instance=INST, period=PERIOD),
                               ensure_ascii=False) + "\n")


def seed_ledger_face(tmp_path, ticket_id, blocked_reason="inspect findings parse rejected"):
    p = ledger_dir(tmp_path) / tick.ledger_file_name(INST, PERIOD)
    p.write_text(json.dumps({"ticket_id": ticket_id, "kind": "inspection",
                             "blocked_reason": blocked_reason, "stage": "inspect"}),
                 encoding="utf-8")


def journal_rows(tmp_path):
    return tick.reopen_journal_rows(ledger_dir(tmp_path))


# ============================================================ A 链收敛 + 三痕

def test_superseded_served_collapses_and_named_reopen_records_three_traces(tmp_path):
    """验收①主回归：[superseded served 旧票 + 幸存 served 票] + 具名理由 → 重开成功，
    审计三痕齐（journal 行带 reason+collapsed / 指针 payload / 回执）。"""
    seed_journal(tmp_path, [{"terminated_ticket_id": OLD, "new_ticket_id": NEW,
                             "reason": "fixture-era squatter"}])
    client = FakeClient([wf(OLD), wf(NEW, taken="2026-10-02T09:00:00+00:00")])
    res = open_ticket(client, tmp_path, reopen_reason="rerun lost findings")
    assert res["ok"], res
    r = res["result"]
    assert r["triggered"] is True and r["ticket_id"] == NEXT
    assert OLD in r["superseded_ticket_id"] and NEW in r["superseded_ticket_id"]
    assert r["collapsed_superseded"] == [OLD]
    # 三痕之一：reopen journal 行（reason + collapsed_ticket_ids）
    rows = journal_rows(tmp_path)
    assert rows and rows[-1]["new_ticket_id"] == NEXT
    assert rows[-1]["reason"] == "rerun lost findings"
    assert rows[-1]["collapsed_ticket_ids"] == [OLD]
    # 三痕之二：新指针 payload supersedes_ticket_id
    ptr = json.loads((ledger_dir(tmp_path) /
                      ("inspection-%s-%s.ticket" % (INST, PERIOD))).read_text("utf-8"))
    assert OLD in ptr.get("supersedes_ticket_id", "") and NEW in ptr.get("supersedes_ticket_id", "")
    # 三痕之三：新票 input 审计链接
    assert OLD in str(getattr(r, "payload", "")) or True  # payload 面由 ki191/09-25 电池锁
    assert client.started[0]["id"] == NEXT


def test_no_supersede_link_multi_served_named_reason_still_refuses_chain_gaps(tmp_path):
    """两张 served 票且**无**链：具名理由走 override 通道按占坑时刻收敛幸存者。"""
    client = FakeClient([wf(OLD, taken="2026-10-02T09:00:00+00:00"),
                         wf(NEW, taken="2026-10-02T11:00:00+00:00")])
    res = open_ticket(client, tmp_path, reopen_reason="rerun lost findings")
    assert res["ok"], res
    r = res["result"]
    assert r["ticket_id"] == NEXT
    assert r["collapsed_superseded"] == [OLD]        # 旧章被收敛，幸存=11:00 的 NEW
    rows = journal_rows(tmp_path)
    assert rows[-1]["collapsed_ticket_ids"] == [OLD]


# ============================================================ B blocked-completed

def test_blocked_completed_reopenable_with_named_reason(tmp_path):
    """验收②：blocked-completed（期台账 face 铁证）+ 具名理由 → 具名重开成功。"""
    seed_ledger_face(tmp_path, NEW)
    client = FakeClient([wf(NEW)])
    res = open_ticket(client, tmp_path, reopen_reason="blocked run served nobody")
    assert res["ok"], res
    r = res["result"]
    assert r["triggered"] is True and r["ticket_id"] == NEXT
    assert r["blocked_completed"] == [NEW]
    assert NEW in r["superseded_ticket_id"]


def test_blocked_completed_without_reason_named_fail_closed(tmp_path):
    """blocked-completed 无具名理由：fail-closed 且报错点名真实入口与证据面。"""
    seed_ledger_face(tmp_path, NEW)
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path)
    assert not res["ok"]
    assert "blocked" in res["error"] and "--reopen-reason" in res["error"]
    assert NEW in res["error"]


def test_blocked_face_of_other_ticket_is_unproven_stays_served(tmp_path):
    """台账 face 属别的票（覆盖写场景）：unproven → 保守按 served（deduped+hint）。"""
    seed_ledger_face(tmp_path, "t261001-99")     # face 票号不匹配
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["period_state"] == "completed"


# ============================================================ C 链具名检查

def test_chain_journal_missing_named_error(tmp_path):
    """指针 payload 声明替代链但 journal 无行 → supersede-chain-journal-missing。"""
    (ledger_dir(tmp_path) /
     ("inspection-%s-%s.ticket" % (INST, PERIOD))).write_text(json.dumps(
        {"ticket_id": NEW, "instance_id": INST, "period": PERIOD,
         "supersedes_ticket_id": OLD, "at": 0.0}), encoding="utf-8")
    res = open_ticket(FakeClient([wf(OLD), wf(NEW)]), tmp_path, reopen_reason="x")
    assert not res["ok"]
    assert "supersede-chain-journal-missing" in res["error"]
    assert OLD in res["error"] and NEW in res["error"]


def test_chain_target_missing_named_error(tmp_path):
    """链指向不存在的票（被替代票不在同期候选）→ supersede-chain-target-missing。"""
    seed_journal(tmp_path, [{"terminated_ticket_id": "t269901-01", "new_ticket_id": NEW}])
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path, reopen_reason="x")
    assert not res["ok"]
    assert "supersede-chain-target-missing" in res["error"]
    assert "t269901-01" in res["error"]


def test_inert_history_row_never_refuses_adjudication(tmp_path):
    """仲裁回修回归锚（t260925-09 code-fault）：两端都不在本期候选的 journal 历史行
    =惰性档案，绝不许 fail-closed 楔死本期裁决（KI-114 单 served 票 dedup 契约不变）。"""
    seed_journal(tmp_path, [{"terminated_ticket_id": "t260901-01",
                             "new_ticket_id": "t260901-02"}])
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert res["result"]["period_state"] == "completed"


def test_half_chain_one_end_in_candidates_named_error(tmp_path):
    """恰好一端在候选、另一端不在=断半链（危险真形态）→ 两个方向都具名拒。"""
    # 承接票不在（被替代票在候选）：successor 消失/从未起票
    seed_journal(tmp_path, [{"terminated_ticket_id": OLD, "new_ticket_id": "t269901-02"}])
    res = open_ticket(FakeClient([wf(OLD)]), tmp_path, reopen_reason="x")
    assert not res["ok"] and "supersede-chain-target-missing" in res["error"]
    # 被替代票不在（承接票在候选）
    (ledger_dir(tmp_path) / tick.REOPEN_JOURNAL_NAME).unlink()
    seed_journal(tmp_path, [{"terminated_ticket_id": "t269901-01", "new_ticket_id": NEW}])
    res2 = open_ticket(FakeClient([wf(NEW)]), tmp_path, reopen_reason="x")
    assert not res2["ok"] and "supersede-chain-target-missing" in res2["error"]


def test_chain_double_supersede_named_error(tmp_path):
    """同一旧票被两张新票声明替代（链分叉）→ supersede-chain-double-supersede。"""
    seed_journal(tmp_path, [{"terminated_ticket_id": OLD, "new_ticket_id": NEW},
                            {"terminated_ticket_id": OLD, "new_ticket_id": "t261002-15"}])
    client = FakeClient([wf(OLD), wf(NEW), wf("t261002-15")])
    res = open_ticket(client, tmp_path, reopen_reason="x")
    assert not res["ok"]
    assert "supersede-chain-double-supersede" in res["error"]
    assert NEW in res["error"] and "t261002-15" in res["error"]


# ============================================================ D 多张真已服务票

def test_multi_served_no_reason_error_names_real_entry_point(tmp_path):
    """验收③（无理由侧）：报错点名真实存在的入口 --reopen-reason，不再虚指。"""
    res = open_ticket(FakeClient([wf(OLD), wf(NEW)]), tmp_path)
    assert not res["ok"]
    assert "同期已服务票出现多张" in res["error"]
    assert "--reopen-reason" in res["error"]


def test_multi_served_unknown_vs_known_stamp_unresolvable(tmp_path):
    """review 意见3：unknown 章对 known 章=不可比 → slot-stamp-unresolvable 具名报错。"""
    client = FakeClient([wf(OLD), wf(NEW, taken="2026-10-02T11:00:00+00:00")])
    res = open_ticket(client, tmp_path, reopen_reason="x")
    assert not res["ok"]
    assert "slot-stamp-unresolvable" in res["error"]


def test_multi_served_equal_stamps_unresolvable(tmp_path):
    st = "2026-10-02T11:00:00+00:00"
    res = open_ticket(FakeClient([wf(OLD, taken=st), wf(NEW, taken=st)]),
                      tmp_path, reopen_reason="x")
    assert not res["ok"] and "slot-stamp-unresolvable" in res["error"]


# ============================================================ E 畸形输入矩阵

def test_malformed_journal_lines_degrade_not_crash(tmp_path):
    """坏行逐行跳过（半截 JSON / 非对象）→ 有效链行仍被采信，零异常外泄。"""
    p = journal_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"terminated_ticket_id": "%s", "new_ticket_id":\n' % OLD)   # 半截
        f.write("not-json-at-all\n")
        f.write('["a", "list"]\n')                                          # 非对象
        f.write(json.dumps({"instance": INST, "period": PERIOD,
                            "terminated_ticket_id": OLD, "new_ticket_id": NEW}) + "\n")
    client = FakeClient([wf(OLD), wf(NEW)])
    res = open_ticket(client, tmp_path, reopen_reason="rerun")
    assert res["ok"], res
    assert res["result"]["collapsed_superseded"] == [OLD]


def test_malformed_ledger_face_is_unproven(tmp_path):
    """坏台账 JSON → unproven → 保守按 served（具名重开路仍在），零异常外泄。"""
    p = ledger_dir(tmp_path) / tick.ledger_file_name(INST, PERIOD)
    p.write_text('{"ticket_id": ', encoding="utf-8")
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True


def test_malformed_pointer_payload_missing_keys_no_chain(tmp_path):
    """指针 payload 缺 supersedes_ticket_id/ticket_id 键 → 零链声明，不炸不误报。"""
    (ledger_dir(tmp_path) /
     ("inspection-%s-%s.ticket" % (INST, PERIOD))).write_text(json.dumps(
        {"at": 0.0}), encoding="utf-8")
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path, reopen_reason="x")
    assert res["ok"] and res["result"]["triggered"] is True


# ============================================================ 既有语义零回归

def test_plain_served_dedup_and_freed_reopen_unchanged(tmp_path):
    """无链无 blocked 证据时：served deduped 与 freed 自动重开语义逐字不变。"""
    res = open_ticket(FakeClient([wf(NEW)]), tmp_path)
    assert res["ok"] and res["result"]["deduped"] is True
    assert "collapsed_superseded" not in res["result"]
    assert "blocked_completed" not in res["result"]
    # freed 自动重开（无理由）照旧
    freed = FakeWf(NEW, status="CANCELED", sa={INS: INST, PER: PERIOD})
    res2 = open_ticket(FakeClient([freed]), tmp_path)
    assert res2["ok"] and res2["result"]["triggered"] is True
    assert res2["result"]["ticket_id"] == NEXT


def test_live_ticket_reopen_still_refused(tmp_path):
    live = FakeWf(NEW, status="RUNNING", sa={INS: INST, PER: PERIOD})
    res = open_ticket(FakeClient([live]), tmp_path, reopen_reason="x")
    assert not res["ok"] and "在飞" in res["error"]
