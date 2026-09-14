"""t260913-01 sign 信号面指纹 / authorize 端到端三态（纯函数面 + boot 自检，零 Temporal）。

覆盖（方案 v2 L1/L2/L3 + review C1/C2/C4/R3 的机械腿）：
  - shared.sign_face_fingerprint：形状稳定 / 幂等 / marker 在场（单一实现两端各算）；
  - marker 常量卫生：与全部模板合法 gate 值（Stage.id 全集 ∪ HUMAN_GATES ∪
    CLOSE_GATE_ID）不相交；
  - classify_query_failure 三分（C1）：absent 只认「expected but not found」；
    其它 QueryFailed=face_error 不吞成 absent；其余异常=unreachable；
  - classify_sign_face：match / mismatch（带 diff）/ 返回形状非法；
  - authz_face_refusal C2 分叉：absent+非 dev-lane 类名=wrong_template（「无人授权面」）；
    absent+DevLaneWorkflow=absent（「worker 代码早于本票」+ KI-033 血统指引）；
    absent+无类名=absent 兜底；mismatch/face_error/unreachable 各自点名；
  - evaluate_authz_landing 三态：landed（新条目）/ 同账不重报（issued 盖写去重）/
    refused（新 sign(authorize) 拒收）/ 基线去重 / 畸形快照（None、缺 meta、meta 非 dict、
    authorizations 非 list、条目非 dict）一律 pending 不炸（R3 读面）；
  - worker.verify_signal_transport：当前代码零问题（boot 自检绿，C4 窄效力口径）；
  - 事故机制文档腿：旧形 Signature（无 authorize 字段）解码同载荷 → authorize 静默
    丢弃（属性不存在）——L1/L3 存在的理由，防后人误删防线。

UT 零网络/零 Temporal/零 git；SDK 转换器经进程内 DefaultPayloadConverter 直调。
"""
import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import base  # noqa: E402
import client  # noqa: E402
import dev_lane  # noqa: E402
import inspection_flow  # noqa: E402
import shared  # noqa: E402
import workflows  # noqa: E402
import workflows_v2  # noqa: E402
from shared import (  # noqa: E402
    AUTHZ_SIGNAL_GATE_MARKER,
    HUMAN_GATES,
    HumanAuthorization,
    Signature,
    sign_face_fingerprint,
)

ABSENT_MSG = ("Query handler for 'sign_face' expected but not found, "
              "known queries: ['snapshot']")


# ---------- 指纹单一实现 ----------

def test_fingerprint_shape_and_idempotent():
    fp = sign_face_fingerprint()
    assert fp["face"] == "sign"
    assert fp["marker"] == AUTHZ_SIGNAL_GATE_MARKER
    assert "authorize" in fp["fields"]
    assert fp == sign_face_fingerprint()  # 幂等：两端各算各的才可比
    # 字段名单向锁定：Signature/HumanAuthorization 的字段集真源
    assert fp["fields"] == sorted(f.name for f in dataclasses.fields(Signature))
    assert fp["authorize_fields"] == sorted(
        f.name for f in dataclasses.fields(HumanAuthorization))


def test_marker_hygiene_disjoint_from_all_legal_gates():
    legal = set(HUMAN_GATES) | {inspection_flow.CLOSE_GATE_ID} | {"merge", ""}
    for cls in list(getattr(workflows_v2, "TEMPLATE_CLASSES", {}).values()) \
            + [dev_lane.DevLaneWorkflow, base.TicketWorkflowBase,
               workflows.ContentPipelineWorkflow]:
        for s in getattr(cls, "STAGES", ()) or ():
            legal.add(s.id)
    assert AUTHZ_SIGNAL_GATE_MARKER not in legal
    assert len(AUTHZ_SIGNAL_GATE_MARKER) >= 3  # 可 grep 的显式保留值


# ---------- classify_query_failure（C1 三分） ----------

def test_query_not_found_is_absent():
    state, detail = client.classify_query_failure("WorkflowQueryFailedError", ABSENT_MSG)
    assert state == "absent" and "expected but not found" in detail


def test_other_query_failure_is_face_error_not_absent():
    state, detail = client.classify_query_failure("WorkflowQueryFailedError",
                                                  "handler boom")
    assert state == "face_error" and "handler boom" in detail
    assert state != "absent"  # C1：不得把 handler 失败吞成「旧 worker」


def test_other_exceptions_are_unreachable():
    for name, msg in (("RPCTimeoutError", "deadline exceeded"),
                      ("RPCError", "unavailable"),
                      ("NotFoundError", "workflow not found")):
        state, detail = client.classify_query_failure(name, msg)
        assert state == "unreachable" and name in detail


# ---------- classify_sign_face ----------

def test_sign_face_match_and_mismatch():
    fp = sign_face_fingerprint()
    assert client.classify_sign_face("ok", dict(fp), fp) == ("match", "")
    drifted = dict(fp)
    drifted["fields"] = fp["fields"] + ["sneaky"]
    state, detail = client.classify_sign_face("ok", drifted, fp)
    assert state == "mismatch" and "sneaky" in detail and "cli=" in detail


def test_sign_face_bad_shape_is_face_error():
    state, _ = client.classify_sign_face("ok", "junk", sign_face_fingerprint())
    assert state == "face_error"


# ---------- authz_face_refusal（C2 分叉） ----------

def test_absent_on_non_devlane_template_is_wrong_template():
    kind, msg = client.authz_face_refusal("absent", ABSENT_MSG,
                                          "BaseWorkflow", "base")
    assert kind == client.KIND_AUTHZ_FACE_WRONG_TEMPLATE
    assert "无人授权面" in msg and "未投递" in msg


def test_absent_on_devlane_is_stale_worker():
    kind, msg = client.authz_face_refusal("absent", ABSENT_MSG,
                                          "DevLaneWorkflow", "dev-lane")
    assert kind == client.KIND_AUTHZ_FACE_ABSENT
    assert "worker 代码早于本票" in msg and "已拒发" in msg
    assert "KI-033" in msg and "repo_root" in msg  # KI-033 血统指引（R8c）


def test_absent_without_class_info_falls_back_to_absent():
    kind, msg = client.authz_face_refusal("absent", ABSENT_MSG, "", "")
    assert kind == client.KIND_AUTHZ_FACE_ABSENT and "已拒发" in msg


def test_mismatch_face_error_unreachable_wording():
    k1, m1 = client.authz_face_refusal("mismatch", "fields: …", "DevLaneWorkflow",
                                       "dev-lane")
    assert k1 == client.KIND_AUTHZ_FACE_MISMATCH and "指纹不符" in m1
    k2, m2 = client.authz_face_refusal("face_error", "boom")
    assert k2 == client.KIND_AUTHZ_FACE_ERROR and "不得当作旧 worker" in m2
    k3, m3 = client.authz_face_refusal("unreachable", "RPCTimeoutError: deadline")
    assert k3 == client.KIND_AUTHZ_FACE_UNREACHABLE and "已拒发" in m3


# ---------- evaluate_authz_landing（R3 读面 + 三态） ----------

def _snap(authz=None, refused=None, with_meta=True):
    if not with_meta:
        return {"refused": refused or []}
    return {"refused": refused or [], "meta": {"authorizations": authz or []}}


NOW = 1_757_000_000


def _entry(who="宿主", kind="protected_path", expires=NOW + 3600, issued=NOW):
    return {"kind": kind, "who": who, "scope": ["integration/baselines"],
            "reason": "修期望值", "expires": expires, "issued": issued, "uses": []}


def test_landing_landed_on_new_entry():
    st, rec = client.evaluate_authz_landing([], [], _snap([_entry()]),
                                            "宿主", "protected_path", NOW + 3600)
    assert st == "landed" and rec["issued"] == NOW


def test_landing_dedup_by_issued_and_other_expires():
    base = [_entry()]
    st, _ = client.evaluate_authz_landing(base, [], _snap(base),
                                          "宿主", "protected_path", NOW + 3600)
    assert st == "pending"  # 同账（issued 相同）不重报
    # 重发同授权 → intake 盖写新 issued → 新账
    st2, _ = client.evaluate_authz_landing(base, [], _snap([_entry(issued=NOW + 5)]),
                                           "宿主", "protected_path", NOW + 3600)
    assert st2 == "landed"
    # who/kind/expires 任一不符不认账
    assert client.evaluate_authz_landing([], [], _snap([_entry()]),
                                         "别人", "protected_path", NOW + 3600)[0] == "pending"
    assert client.evaluate_authz_landing([], [], _snap([_entry()]),
                                         "宿主", "arbitration_verdict", NOW + 3600)[0] == "pending"
    assert client.evaluate_authz_landing([], [], _snap([_entry()]),
                                         "宿主", "protected_path", NOW + 9999)[0] == "pending"


def test_landing_refused_new_entry_only():
    old = {"want": "sign(authorize)", "who": "宿主", "why": "expires 已过期（旧）"}
    new = {"want": "sign(authorize)", "who": "宿主", "why": "expires 已过期（新）"}
    st, why = client.evaluate_authz_landing([], [old], _snap([], [old, new]),
                                            "宿主", "protected_path", NOW + 3600)
    assert st == "refused" and why == "expires 已过期（新）"
    # 只有基线内的旧拒收 → pending
    assert client.evaluate_authz_landing([], [old], _snap([], [old]),
                                         "宿主", "protected_path", NOW + 3600)[0] == "pending"
    # 普通签字拒收（want≠sign(authorize)）不算授权拒收
    plain = {"want": "sign()", "who": "宿主", "why": "当前步 arbitrate 非人审等待中，签字无效"}
    assert client.evaluate_authz_landing([], [], _snap([], [plain]),
                                         "宿主", "protected_path", NOW + 3600)[0] == "pending"


@pytest.mark.parametrize("snap", [
    None, {}, {"meta": None}, {"meta": "junk"}, {"meta": {}},
    {"meta": {"authorizations": "junk"}},
    {"meta": {"authorizations": [None, "junk", 3]}},
    {"refused": "junk"}, {"refused": [None, 7]},
])
def test_landing_malformed_snapshots_degrade_to_pending(snap):
    st, payload = client.evaluate_authz_landing([], [], snap,
                                                "宿主", "protected_path", NOW + 3600)
    assert st == "pending" and payload == ""


def test_landing_baseline_malformed_entries_do_not_crash():
    st, _ = client.evaluate_authz_landing(["junk", None], ["junk"],
                                          _snap([_entry()]), "宿主",
                                          "protected_path", NOW + 3600)
    assert st == "landed"  # 基线坏条目跳过，不炸、不误吞新账


# ---------- worker boot 自检（窄效力） ----------

def test_verify_signal_transport_green_on_current_code():
    import worker
    assert worker.verify_signal_transport() == []


def test_incident_mechanism_documented_by_old_class_drop():
    """事故机制文档腿：t260912-03 之前的旧 Signature（无 authorize 字段）解码同一
    载荷 → authorize 被静默丢弃（属性不存在）→ handler getattr 默认 None → 普通签字
    路径。这是 marker/gate 标记 + boot 自检 + face 指纹三层防线存在的根据。"""
    import temporalio.converter as conv

    @dataclasses.dataclass
    class OldSignature:  # t260912-03 前的类形状
        who: str
        gate: str = "approve"
        decision: str = "approve"
        note: str = ""

    pc = conv.DefaultPayloadConverter()
    sig = Signature(who="h", gate=AUTHZ_SIGNAL_GATE_MARKER, decision="approve",
                    authorize=HumanAuthorization(kind="protected_path", who="x",
                                                 scope=["a"], reason="r", expires=9))
    out = pc.from_payload(pc.to_payload(sig), OldSignature)
    assert getattr(out, "authorize", "ABSENT") == "ABSENT"  # 静默丢弃复现
