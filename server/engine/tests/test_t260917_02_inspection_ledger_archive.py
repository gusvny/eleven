"""t260917-02 修复③：台账跨票覆盖前归档留史（纯 impl 面，零网络零 Temporal）。

覆盖口径（=方案 v2 §改动清单 S1 + review R3/R6/R7）：
  A. 跨票归档：旧票账搬 archive/、canonical=最新跑、归档件 json 可读且与旧跑等值。
  B. 同票重写不归档（一次 run 落 report/人门/收口三次账，绝不自产三件假留史）。
  C. 无静默覆盖（R3）：归档名并入被归档票号+HHMMSS；同秒同 token 目标已存在 → -N
     递增 + exclusive create——归档路径绝不覆写任何已有件。
  D. 畸形输入/旧件：旧件非 JSON/无 ticket_id → 仍归档（corrupt token，原字节等值）；
     归档失败（目录不可建/写入失败）不拦新写、archive_error 点名；缺实例/期照旧抛。
  E. 不污染消费面：archive/ 子目录不进 ledger_periods（deadman 扫描）；suite 回执同规则。
运行：server/engine/.venv/bin/python -m pytest server/engine/tests/test_t260917_02_inspection_ledger_archive.py -q
"""
import json
from datetime import datetime
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_flow as flow  # noqa: E402
from inspection_deadman import ledger_periods  # noqa: E402


def _face(ticket_id: str, instance_id: str = "integration-tests", period: str = "20260916") -> dict:
    return {"ticket_id": ticket_id, "kind": "inspection", "instance_id": instance_id,
            "period": period, "findings": [{"id": "f-" + ticket_id, "severity": "low"}],
            "summary": {"low": 1}}


def _archive_files(out_dir: Path):
    d = out_dir / flow.LEDGER_ARCHIVE_DIRNAME
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


# ---------- A. 跨票归档 ----------

def test_cross_run_archive_keeps_old_readable_and_canonical_new(tmp_path):
    old, new = _face("t260916-13"), _face("t260917-01")
    out1 = flow.write_inspection_report_impl(old, tmp_path)
    assert out1["archived"] is False and out1["archive_path"] == ""   # 首写无旧件
    out2 = flow.write_inspection_report_impl(new, tmp_path)
    canonical = Path(out2["path"])
    assert json.loads(canonical.read_text(encoding="utf-8"))["ticket_id"] == "t260917-01"
    assert out2["archived"] is True and out2["archive_error"] == ""
    archived = list((tmp_path / flow.LEDGER_ARCHIVE_DIRNAME).iterdir())
    assert len(archived) == 1
    # 归档名并含被归档票号（R3）：跨票碰撞词法不可能
    assert "t260916-13" in archived[0].name
    # 旧记录可读且与旧跑等值（验收③）
    assert json.loads(archived[0].read_text(encoding="utf-8")) == old
    # 归档件在子目录：不在顶层冒充 canonical
    assert canonical.parent == tmp_path


# ---------- B. 同票重写不归档 ----------

def test_same_run_rewrite_does_not_archive(tmp_path):
    face = _face("t260917-01")
    flow.write_inspection_report_impl(face, tmp_path)
    face["human_gate"] = {"who": "宿主", "decision": "approve"}
    out = flow.write_inspection_report_impl(face, tmp_path)   # 人门段再落一次
    out = flow.write_inspection_report_impl(face, tmp_path)   # 收口段再落一次
    assert out["archived"] is False
    assert _archive_files(tmp_path) == []


def test_empty_incoming_ticket_id_matching_empty_old_does_not_archive(tmp_path):
    # 双空（老 face 无 ticket_id + 新 face 无 ticket_id）无法判别归属 → 按同票自身
    # 重写处理（幂等重写面），不归档——防老 history 重放每段落账自产假留史。
    face = {"kind": "inspection", "instance_id": "i", "period": "20260916"}
    flow.write_inspection_report_impl(face, tmp_path)
    out = flow.write_inspection_report_impl(face, tmp_path)
    assert out["archived"] is False and _archive_files(tmp_path) == []


def test_empty_incoming_but_old_has_ticket_id_archives(tmp_path):
    flow.write_inspection_report_impl(_face("t260916-13"), tmp_path)
    out = flow.write_inspection_report_impl({"kind": "inspection", "instance_id": "integration-tests",
                                             "period": "20260916"}, tmp_path)
    assert out["archived"] is True
    assert len(_archive_files(tmp_path)) == 1


# ---------- C. 无静默覆盖（R3） ----------

def test_same_second_collision_increments_suffix_never_overwrites(tmp_path):
    fixed = 1700000000.0                            # 固定钟：同秒
    stamp = datetime.fromtimestamp(fixed).strftime("%H%M%S")
    flow.write_inspection_report_impl(_face("t260916-13"), tmp_path)
    out1 = flow.write_inspection_report_impl(_face("t260917-01"), tmp_path, now_fn=lambda: fixed)
    # 极端残撞复现：手工再造「canonical 又变回旧票」再归档一次（同秒同 token）
    (tmp_path / "inspection-integration-tests-20260916.json").write_text(
        json.dumps(_face("t260916-13"), ensure_ascii=False), encoding="utf-8")
    out2 = flow.write_inspection_report_impl(_face("t260917-02"), tmp_path, now_fn=lambda: fixed)
    assert out1["archived"] and out2["archived"]
    names = _archive_files(tmp_path)
    assert len(names) == 2
    assert names[0] == ("inspection-integration-tests-20260916-t260916-13-%s-2.json" % stamp)
    assert names[1] == "inspection-integration-tests-20260916-t260916-13-%s.json" % stamp
    # 两件归档都完整可读，互不覆写
    body2 = json.loads((tmp_path / flow.LEDGER_ARCHIVE_DIRNAME / names[1]).read_text(encoding="utf-8"))
    assert body2["ticket_id"] == "t260916-13"


def test_suite_receipt_same_second_collision_never_overwrites(tmp_path):
    fixed = 1700000000.0
    stamp = datetime.fromtimestamp(fixed).strftime("%H%M%S")
    inst, period = "integration-tests", "20260916"
    flow.write_inspection_suite_receipt_impl(inst, period, {"ticket_id": "t260916-13", "x": 1}, tmp_path)
    r1 = flow.write_inspection_suite_receipt_impl(inst, period, {"ticket_id": "t260917-01", "x": 2}, tmp_path,
                                                  now_fn=lambda: fixed)
    (tmp_path / "inspection-integration-tests-20260916-suite.json").write_text(
        json.dumps({"ticket_id": "t260916-13", "x": 1}), encoding="utf-8")
    r2 = flow.write_inspection_suite_receipt_impl(inst, period, {"ticket_id": "t260917-02", "x": 3}, tmp_path,
                                                  now_fn=lambda: fixed)
    assert r1["archived"] and r2["archived"]
    names = _archive_files(tmp_path)
    assert names[0] == ("inspection-integration-tests-20260916-suite-t260916-13-%s-2.json" % stamp)
    assert names[1] == "inspection-integration-tests-20260916-suite-t260916-13-%s.json" % stamp


# ---------- D. 畸形旧件 / 归档失败 / 畸形输入 ----------

def test_malformed_old_file_archived_with_corrupt_token_bytes_equal(tmp_path):
    path = tmp_path / "inspection-integration-tests-20260916.json"
    raw = b"{not-json-at-all"
    path.write_bytes(raw)
    out = flow.write_inspection_report_impl(_face("t260917-01"), tmp_path)
    assert out["archived"] is True and out["archive_error"] == ""
    names = _archive_files(tmp_path)
    assert len(names) == 1 and "-corrupt-" in names[0]
    assert (tmp_path / flow.LEDGER_ARCHIVE_DIRNAME / names[0]).read_bytes() == raw
    assert json.loads((tmp_path / out["path"]).read_text(encoding="utf-8"))["ticket_id"] == "t260917-01"


def test_old_json_without_ticket_id_archived_as_corrupt(tmp_path):
    path = tmp_path / "inspection-integration-tests-20260916.json"
    path.write_text(json.dumps({"kind": "inspection", "note": "无票号的来历不明件"}), encoding="utf-8")
    out = flow.write_inspection_report_impl(_face("t260917-01"), tmp_path)
    assert out["archived"] is True
    assert "-corrupt-" in _archive_files(tmp_path)[0]


def test_archive_failure_does_not_block_new_write(tmp_path):
    # archive 名被同名文件占用 → mkdir 失败 → 归档放弃但 archive_error 点名，新写照常
    (tmp_path / flow.LEDGER_ARCHIVE_DIRNAME).write_text("不是目录", encoding="utf-8")
    flow.write_inspection_report_impl(_face("t260916-13"), tmp_path)
    out = flow.write_inspection_report_impl(_face("t260917-01"), tmp_path)
    assert out["archived"] is False
    assert "归档目录不可建" in out["archive_error"]
    assert json.loads(Path(out["path"]).read_text(encoding="utf-8"))["ticket_id"] == "t260917-01"


def test_malformed_inputs_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        flow.write_inspection_report_impl({"instance_id": "", "period": "20260916"}, tmp_path)
    with pytest.raises(ValueError):
        flow.write_inspection_report_impl({"instance_id": "i", "period": ""}, tmp_path)
    with pytest.raises(ValueError):
        flow.write_inspection_suite_receipt_impl("", "", {"ticket_id": "no-shape"}, tmp_path)


def test_archive_token_sanitizes_server_suffixed_id(tmp_path):
    # 服务端后缀形 id（含冒号）安全落名（t 形词法之外的真实形态，260917 实况）
    flow.write_inspection_report_impl(
        _face("inspection-integration-tests-period-2026-09-16T23:30:00Z"), tmp_path)
    out = flow.write_inspection_report_impl(_face("t260917-01"), tmp_path)
    assert out["archived"] is True
    name = _archive_files(tmp_path)[0]
    assert ":" not in name and "period-2026-09-16T23-30-00Z" in name


# ---------- E. 不污染消费面 ----------

def test_archive_dir_does_not_pollute_ledger_scan(tmp_path):
    flow.write_inspection_report_impl(_face("t260916-13"), tmp_path)
    flow.write_inspection_report_impl(_face("t260917-01"), tmp_path)
    led = ledger_periods(tmp_path, "integration-tests")
    assert led["periods"] == {"20260916"}
    assert led["malformed"] == []
    suite = flow.write_inspection_suite_receipt_impl("integration-tests", "20260916",
                                                     {"ticket_id": "t260917-01"}, tmp_path)
    assert suite["archived"] is False                      # 首写套件回执无旧件
    led2 = ledger_periods(tmp_path, "integration-tests")
    assert led2["periods"] == {"20260916"} and led2["malformed"] == []
