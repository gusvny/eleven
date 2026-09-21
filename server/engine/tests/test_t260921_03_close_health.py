"""t260921-03 收口健康度——引擎侧 UT（行键 + 详情面键 + 推导单点）。

黑盒口径不依赖真 Temporal（temporalio 导入桩同 t260919-02 先例，本文件只测纯函数
与行组装函数，不需要 FakeClient 全链）。覆盖（对应票面验收①②③与 review 意见）：
  A. _close_health_of 推导单点真值表：未收口=''、终态成功有产物=ok、实案 blocked
     面无报告=abnormal、失败族=failed、面不可读=unreadable、畸形 face 全降级不抛。
  B. 反用例：面无受阻记录且有产物（report_path 在）不判异常；被标异常必带事实
     原文，KI-018①：占位语不进数据字段）；受阻面+文件在（t260917-02 落账实案
     真形态）仍 abnormal——健康度看面不看文件名。
  C. _row_from_inspection_face：实案复现夹具（面快照 blocked + exec COMPLETED +
     无报告）→ 行 close_health=abnormal 且 status/stage_state 词面**原样保留**
     （对账=增量表达，不改写历史面）；degraded 行=unreadable；键只加（既有键全在）。
  D. _row_from_meta：dev-lane 无产物契约——COMPLETED→ok、RUNNING→''、失败→failed。
  E. _inspection_query_meta：详情面四键（exec_status/close_health/
     close_health_reason/close_time_txt）只加不改既有键；畸形 snap 全降级。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "integration" / "t260901-23"))
sys.path.insert(0, str(REPO / "server" / "engine"))

import _stub_temporalio  # noqa: E402
_stub_temporalio.install()

import client as client_mod  # noqa: E402  # 桩环境下的真 client.py

# ---------------------------------------------------------------- 夹具


def _realcase_snap(blocked_reason="只读审查 agent 起不来（dsh 报 unknown preset \"read-only\"）",
                   report_path=None):
    """实案复现夹具（t260920-02/t260921-01 形态）：workflow 正常 return（Temporal
    COMPLETED），终态快照=业务 blocked 面——findings 0、无 report_path、带事实原因。"""
    face = {
        "ticket_id": "t260920-02", "kind": "inspection",
        "instance_id": "integration-tests", "period": "20260920",
        "heartbeat": False, "summary": {}, "findings": [],
        "suggested_fix_tickets": [], "blocked_reason": blocked_reason,
        "stage": "inspect",
    }
    if report_path:
        face["report_path"] = report_path
    return {
        "id": "t260920-02", "kind": "inspection", "template": "inspection-lite",
        "stage": "inspect", "stage_state": "blocked", "status": "blocked",
        "face": face,
        "timeline": [{"stage": "inspect", "state": "blocked", "at": 1759000000}],
    }


def _ok_snap():
    """正常收口夹具：有报告（clean 期 0 发现也落报告）。"""
    snap = _realcase_snap(blocked_reason="")
    snap["status"] = "closed"
    snap["stage_state"] = "done"
    snap["stage"] = "close"
    snap["face"]["report_path"] = "out/inspection/integration-tests/20260920.json"
    snap["face"]["blocked_reason"] = ""
    snap["face"]["heartbeat"] = True
    return snap


# ---------------------------------------------------------------- A. 推导单点

def test_a_truth_table():
    f = client_mod._close_health_of
    # 未收口：空/在飞/换代继续——健康度不可判，不给（''）
    assert f("") == ("", "")
    assert f("RUNNING") == ("", "")
    assert f("CONTINUED_AS_NEW") == ("", "")
    # 终态成功有产物 = ok（reason 空=没有异常可说）——巡检侧（require_artifacts）
    assert f("COMPLETED", {"report_path": "out/x.json"}, require_artifacts=True) == ("ok", "")
    # dev-lane 侧（缺省，无产物契约）：终态成功即 ok，face 不参与
    assert f("COMPLETED") == ("ok", "")
    assert f("COMPLETED", {"anything": 1}) == ("ok", "")
    # 实案形态：终态成功但无报告 = abnormal，原因带事实
    h, r = f("COMPLETED", _realcase_snap()["face"], require_artifacts=True)
    assert h == "abnormal"
    assert "本期无报告" in r and "发现 0 条" in r
    # 实案真形态（live 对账发现，t260917-02 起）：blocked 收口也落账（dead-man 面），
    # 落账走 report 同名约定 → report_path 在场但内容=受阻面镜像。健康度看面不看
    # 文件名：仍是 abnormal，且 reason 点名镜像事实（不许被文件名骗成 ok）。
    h2, r2 = f("COMPLETED", _realcase_snap(report_path="out/inspection/x-20260920.json")["face"],
               require_artifacts=True)
    assert h2 == "abnormal"
    assert "面快照 blocked" in r2 and "落账文件为受阻面镜像" in r2 and "发现 0 条" in r2
    # 失败族（补集口径，t260919-02 零回归）
    for st in ("FAILED", "CANCELED", "TIMED_OUT", "SOME_NEW_TERMINAL"):
        h, r = f(st)
        assert h == "failed" and st in r, st
    # TERMINATED 在本推导里同归 failed——板面既有纪律不上板（client.py:1922），
    # 行层永不可达；此处只钉纯函数口径，板面缺席归集成场景断言。
    assert f("TERMINATED")[0] == "failed"
    # degraded 优先（仅窗内闭合行读取失败路径传入；显式存疑，不冒充 ok/abnormal）
    assert f("COMPLETED", {"report_path": "x"}, degraded=True)[0] == "unreadable"
    assert f("", None, degraded=True)[0] == "unreadable"


def test_a_malformed_face():
    f = client_mod._close_health_of
    # face 非字典 / 空（巡检侧 require_artifacts）→ 已结束但无面可核 = unreadable
    # （绝不冒充 ok）；dev-lane 同形输入缺省 ok（无产物契约，对照行）
    for bad in (None, "x", 42, [], {}):
        h, r = f("COMPLETED", bad, require_artifacts=True)
        assert h == "unreadable", bad
        assert "不可读" in r or "无票面" in r, bad
        assert f("COMPLETED", bad) == ("ok", ""), bad
    # 键值畸形逐键降级：report_path 非串=缺失、findings 非列表=0、blocked_reason 非串=无
    h, r = f("COMPLETED", {"report_path": 42, "findings": "x", "blocked_reason": True},
             require_artifacts=True)
    assert h == "abnormal" and "发现 0 条" in r and "面快照 blocked" not in r


def test_b_anti_cases():
    f = client_mod._close_health_of
    # 反用例③：正常收口（面无受阻记录 + 报告在）绝不被标异常
    face = dict(_realcase_snap(blocked_reason="")["face"])
    face["report_path"] = "out/inspection/x/20260921.json"
    assert f("COMPLETED", face, require_artifacts=True) == ("ok", "")
    # 有意修订（live 对账发现后收紧，根因见 test_a 真值表注释）：旧断言「面里残留
    # blocked 字样+文件在 → ok」是对 reality 的误钉——t260917-02 起 blocked 收口
    # 落账同名文件，受阻面+文件在=实案形态，必须 abnormal（对账不反向撒谎的
    # 真含义是「面无受阻+报告在 → ok」，不是「文件在 → ok」）。
    h, r = f("COMPLETED", _realcase_snap(report_path="out/x.json")["face"],
             require_artifacts=True)
    assert h == "abnormal" and "受阻面镜像" in r
    # 被标异常必带具体原因：blocked 原文进 reason（不许无因异常）
    _h, r = f("COMPLETED", _realcase_snap(blocked_reason="模型账号配额 429")["face"],
              require_artifacts=True)
    assert "模型账号配额 429" in r
    # reason 只放事实：占位语（刷新重试/刷新无效）绝不出现（KI-018①）
    for st, face_ in (("COMPLETED", _realcase_snap()["face"]), ("FAILED", None)):
        _h, r = f(st, face_)
        assert "刷新" not in r


# ---------------------------------------------------------------- C. 巡检行

def test_c_inspection_row_realcase():
    row = client_mod._row_from_inspection_face(
        "t260920-02", _realcase_snap(), "sandbar", "engine-hardening",
        "COMPLETED", 1759000100, 1758999000,
        instance_id="integration-tests", period="20260920", match_via="sa")
    # 实案复现用例②：行自带异常收口标记 + 事实原因
    assert row["close_health"] == "abnormal"
    assert "read-only" in row["close_health_reason"] and "本期无报告" in row["close_health_reason"]
    assert row["exec_status"] == "COMPLETED"
    # 对账=增量表达：面快照词面原样保留（不改写历史面——方案备选 B 否决点的行级钉）
    assert row["status"] == "blocked" and row["stage_state"] == "blocked"
    assert row["stage"] == "inspect"
    # 键只加：既有行键全在（spot-check 关键面）
    for k in ("id", "project", "epic", "kind", "title", "status", "stage", "stage_state",
              "engine", "exec_status", "findings", "report_path", "awaiting_gate",
              "blocked_reason", "instance_id", "period", "match_via", "close_ts",
              "authz_active", "close_health", "close_health_reason"):
        assert k in row, k


def test_c_inspection_row_ok_and_degraded():
    # 正常收口：ok + reason 空（行不贴异常徽标的数据前提）
    row = client_mod._row_from_inspection_face(
        "t260920-03", _ok_snap(), "sandbar", "", "COMPLETED", 1759000100, 1758999000)
    assert row["close_health"] == "ok" and row["close_health_reason"] == ""
    # degraded 窗内闭合行：unreadable（status 钉 running 的既有形状不变——
    # t260915-08 review 执行项1 的行数据面零改动，可见性承接改由 UI 异常收口段负责）
    row2 = client_mod._row_from_inspection_face(
        "t-x", {}, "sandbar", "", "COMPLETED", 1759000100, 1758999000, degraded=True)
    assert row2["close_health"] == "unreadable"
    assert row2["status"] == "running" and row2["stage_state"] == "running"
    # 失败族巡检行（_terminal_failed 分支调用形态：空 snap）→ failed + 终态词
    row3 = client_mod._row_from_inspection_face(
        "t-y", {}, "sandbar", "", "FAILED", 1759000100, 1758999000)
    assert row3["close_health"] == "failed" and "FAILED" in row3["close_health_reason"]


# ---------------------------------------------------------------- D. dev-lane 行

def test_d_meta_row_health():
    meta = {"status": "closed", "stage_state": "awaiting", "title": "t",
            "updated": 1758999000}
    row = client_mod._row_from_meta("t260919-01", meta, "COMPLETED")
    # dev-lane 无产物契约：终态成功即 ok（缺产物判定不泛化）
    assert row["close_health"] == "ok" and row["close_health_reason"] == ""
    row2 = client_mod._row_from_meta("t2", meta, "RUNNING")
    assert row2["close_health"] == "" and row2["close_health_reason"] == ""
    row3 = client_mod._row_from_meta("t3", meta, "CANCELED")
    assert row3["close_health"] == "failed" and "CANCELED" in row3["close_health_reason"]


# ---------------------------------------------------------------- E. 详情面

def test_e_query_meta_additive_keys():
    meta = client_mod._inspection_query_meta(
        "t260920-02", _realcase_snap(), "COMPLETED", "09-20 22:30:00")
    # 详情终态对账四键（键只加；review 意见3：统一命名 close_health_reason）
    assert meta["exec_status"] == "COMPLETED"
    assert meta["close_health"] == "abnormal"
    assert "read-only" in meta["close_health_reason"]
    assert meta["close_time_txt"] == "09-20 22:30:00"
    # 既有键全在且值不变（只加不改级——详情消费方零破坏）
    for k, v in (("id", "t260920-02"), ("kind", "inspection"), ("status", "blocked"),
                 ("stage_state", "blocked"), ("stage", "inspect"),
                 ("instance_id", "integration-tests"), ("period", "20260920"),
                 ("report_path", ""), ("gate_id", meta["gate_id"]),
                 ("engine", client_mod.INSPECTION_ROW_ENGINE)):
        assert meta[k] == v, k


def test_e_query_meta_states_and_degrade():
    snap = _realcase_snap()
    # 在跑详情：exec 透传、健康度 ''（未收口不给）
    m = client_mod._inspection_query_meta("t1", snap, "RUNNING", "")
    assert m["exec_status"] == "RUNNING" and m["close_health"] == ""
    assert m["close_health_reason"] == ""
    # 缺省调用（老调用点形状）：exec_status=None 化、健康度 ''，不抛
    m2 = client_mod._inspection_query_meta("t1", snap)
    assert m2["exec_status"] is None and m2["close_health"] == ""
    assert m2["close_time_txt"] == ""
    # 畸形 snap（face 非字典）→ 全降级不抛：已结束无面可核 = unreadable
    bad = {"id": "t2", "kind": "inspection", "status": "blocked",
           "stage_state": "blocked", "face": "garbage"}
    m3 = client_mod._inspection_query_meta("t2", bad, "COMPLETED", "")
    assert m3["close_health"] == "unreadable" and m3["blocked_reason"] == ""
    # 正常收口详情：ok
    m4 = client_mod._inspection_query_meta("t3", _ok_snap(), "COMPLETED", "09-21 08:00:00")
    assert m4["close_health"] == "ok" and m4["close_health_reason"] == ""
