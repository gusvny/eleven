"""t260912-03 人授权载荷与纯函数矩阵（shared.py / authz_gates.py 的纯面，离线零 Temporal）。

覆盖（方案 S1/S2 + review RC1-RC3/RC9 的机械子用例）：
  - 常量与上限：who 64 / reason 20000 / scope 16×256 / expires ≤ 签发+30 天；
  - 反自签：全域五角色名（源码锁定对齐 inspection_flow.AGENT_ROLE_NAMES）+ strip/lower
    归一 + 大小写/空白变体 + `-agent` 显示名后缀；
  - arbitration_cap_route：authorized=False 逐行等于 integration_route（零回归）；
    True 时只放行两条上限原因；负锁=未知 verdict / 未超限 / pass 一律照旧；
  - active_authorizations/authorization_scopes：过期/畸形/别票过滤；
  - parse_authz_used：多段/畸形/缺键；
  - split_protected vs judge_protected_paths：无授权逐字节一致（零回归机械锁）；
    豁免归属（issued 最新者胜）、scope 前缀语义（baselines2 反用例）、时效纵深防线、
    畸形记录不炸；authorized_passage_note 的记名与机读键（含换行净化/截断）。
"""
import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import authz_gates  # noqa: E402
import inspection_flow  # noqa: E402
import path_gates  # noqa: E402
import shared  # noqa: E402
from shared import (  # noqa: E402
    AUTH_ARBITRATION_VERDICT,
    AUTH_KINDS,
    AUTH_PROTECTED_PATH,
    AUTHZ_AGENT_ROLE_NAMES,
    AUTHZ_EXPIRES_MAX_SEC,
    AUTHZ_REASON_MAX_LEN,
    AUTHZ_SCOPE_ITEM_MAX_LEN,
    AUTHZ_SCOPE_MAX_ITEMS,
    AUTHZ_USED_KEY,
    AUTHZ_WHO_MAX_LEN,
    HumanAuthorization,
    Signature,
)

NOW = 1_757_000_000


def _auth(**kw):
    base = dict(kind=AUTH_PROTECTED_PATH, who="宿主", scope=["integration/baselines"],
                reason="修探测脚本期望值", expires=NOW + 3600)
    base.update(kw)
    return HumanAuthorization(**base)


# ---------- 常量与载荷形状 ----------

def test_limits_values():
    assert AUTHZ_WHO_MAX_LEN == 64
    assert AUTHZ_WHO_MAX_LEN == inspection_flow.MAX_WHO_LEN
    assert AUTHZ_REASON_MAX_LEN == 20000
    assert AUTHZ_SCOPE_MAX_ITEMS == 16
    assert AUTHZ_SCOPE_ITEM_MAX_LEN == 256
    assert AUTHZ_EXPIRES_MAX_SEC == 30 * 24 * 3600
    assert AUTH_KINDS == (AUTH_PROTECTED_PATH, AUTH_ARBITRATION_VERDICT)


def test_agent_role_names_source_lock():
    """反自签口径与 inspection_flow 的判定集合同源（防未来只改一处判定）。"""
    assert AUTHZ_AGENT_ROLE_NAMES == inspection_flow.AGENT_ROLE_NAMES
    assert AUTHZ_AGENT_ROLE_NAMES == frozenset(
        {"developer", "integration", "ops", "product-operation", "artist"})


def test_signature_authorize_defaulted_old_shape():
    """老形状 Signature（无 authorize 字段）仍可构造/序列化——老事件 replay 面。"""
    sig = Signature(who="宿主", gate="merge", decision="approve", note="ok")
    assert sig.authorize is None
    d = dataclasses.asdict(sig)
    assert d["authorize"] is None and d["who"] == "宿主"
    sig2 = Signature(who="宿主", gate="", decision="approve",
                     authorize=_auth())
    assert sig2.authorize.kind == AUTH_PROTECTED_PATH
    assert dataclasses.asdict(sig2)["authorize"]["expires"] == NOW + 3600


# ---------- intake 校验（validate_authorization） ----------

def test_validate_ok_both_kinds():
    assert authz_gates.validate_authorization(_auth(), NOW, "t1") == ""
    assert authz_gates.validate_authorization(
        _auth(kind=AUTH_ARBITRATION_VERDICT, scope=["t1"]), NOW, "t1") == ""
    # dict 形态（CLI/场景两形兼容）同样可校验
    assert authz_gates.validate_authorization(
        {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["verify.yaml"],
         "reason": "r", "expires": NOW + 10}, NOW, "t1") == ""


def test_validate_rejects_malformed():
    assert "kind 非法" in authz_gates.validate_authorization(_auth(kind="x"), NOW, "t1")
    assert authz_gates.validate_authorization(None, NOW, "t1")
    assert "缺 who" in authz_gates.validate_authorization(_auth(who="  "), NOW, "t1")
    assert "who 超长" in authz_gates.validate_authorization(
        _auth(who="人" * (AUTHZ_WHO_MAX_LEN + 1)), NOW, "t1")
    assert "缺 reason" in authz_gates.validate_authorization(_auth(reason=" \n "), NOW, "t1")
    assert "reason 超长" in authz_gates.validate_authorization(
        _auth(reason="x" * (AUTHZ_REASON_MAX_LEN + 1)), NOW, "t1")
    assert "scope 空" in authz_gates.validate_authorization(_auth(scope=[]), NOW, "t1")
    assert "scope 条目超限" in authz_gates.validate_authorization(
        _auth(scope=["a/b"] * (AUTHZ_SCOPE_MAX_ITEMS + 1)), NOW, "t1")
    assert "scope 条目超长" in authz_gates.validate_authorization(
        _auth(scope=["a" * (AUTHZ_SCOPE_ITEM_MAX_LEN + 1)]), NOW, "t1")
    assert "scope 含空白条目" in authz_gates.validate_authorization(
        _auth(scope=["  "]), NOW, "t1")


@pytest.mark.parametrize("bad", ["/abs/x", "../x", "a/../../b", "a*b", "a?b", "a\\b", "a[1]"])
def test_validate_rejects_unsafe_scope(bad):
    assert "scope 条目非法路径" in authz_gates.validate_authorization(
        _auth(scope=[bad]), NOW, "t1")


@pytest.mark.parametrize("who", ["developer", "integration", "ops", "product-operation",
                                 "artist", "Developer", " INTEGRATION ", "integration-agent",
                                 "developer-agent"])
def test_anti_self_sign(who):
    """反自签红线：五角色名（含大小写/空白变体）与 agent 显示名后缀一律拒收。"""
    err = authz_gates.validate_authorization(_auth(who=who), NOW, "t1")
    assert "agent 不得自签" in err


@pytest.mark.parametrize("who", ["宿主", "op-local", "张三", "human", "integrations"])
def test_human_names_pass(who):
    assert authz_gates.validate_authorization(_auth(who=who), NOW, "t1") == ""


def test_validate_expires_bounds():
    assert "expires 缺失或非法" in authz_gates.validate_authorization(
        _auth(expires=0), NOW, "t1")
    assert "已过期" in authz_gates.validate_authorization(_auth(expires=NOW), NOW, "t1")
    assert "已过期" in authz_gates.validate_authorization(_auth(expires=NOW - 1), NOW, "t1")
    assert authz_gates.validate_authorization(
        _auth(expires=NOW + AUTHZ_EXPIRES_MAX_SEC), NOW, "t1") == ""
    assert "expires 超上限" in authz_gates.validate_authorization(
        _auth(expires=NOW + AUTHZ_EXPIRES_MAX_SEC + 1), NOW, "t1")


def test_arbitration_scope_must_be_this_ticket():
    err = authz_gates.validate_authorization(
        _auth(kind=AUTH_ARBITRATION_VERDICT, scope=["t-other"]), NOW, "t1")
    assert "必须恰为本票票号" in err
    err = authz_gates.validate_authorization(
        _auth(kind=AUTH_ARBITRATION_VERDICT, scope=["t1", "t2"]), NOW, "t1")
    assert "必须恰为本票票号" in err
    assert "缺本票票号上下文" in authz_gates.validate_authorization(
        _auth(kind=AUTH_ARBITRATION_VERDICT, scope=["t1"]), NOW, "")


def test_authorization_record_overwrites_issued():
    rec = authz_gates.authorization_record(_auth(issued=1), NOW)
    assert rec["issued"] == NOW and rec["uses"] == []
    assert rec["who"] == "宿主" and rec["scope"] == ["integration/baselines"]
    assert rec["expires"] == NOW + 3600


# ---------- 生效过滤（active_authorizations / authorization_scopes） ----------

def test_active_authorizations_filters():
    items = [
        {"kind": AUTH_PROTECTED_PATH, "who": "a", "scope": ["x"], "expires": NOW + 5},
        {"kind": AUTH_PROTECTED_PATH, "who": "b", "scope": ["y"], "expires": NOW - 1},
        {"kind": "bogus", "who": "c", "scope": ["z"], "expires": NOW + 5},
        "not-a-dict",
        {"kind": AUTH_ARBITRATION_VERDICT, "who": "d", "scope": ["t1"], "expires": NOW + 5},
        {"kind": AUTH_ARBITRATION_VERDICT, "who": "e", "scope": ["t-other"],
         "expires": NOW + 5},
    ]
    allkinds = shared.active_authorizations(items, NOW)
    # 不带 kind/票号筛：过期/bogus/非 dict 丢弃，其余原样（票号筛只在 kind=仲裁判决时生效）
    assert [i["who"] for i in allkinds] == ["a", "d", "e"]
    prot = shared.active_authorizations(items, NOW, kind=AUTH_PROTECTED_PATH)
    assert [i["who"] for i in prot] == ["a"]
    arb = shared.active_authorizations(items, NOW, kind=AUTH_ARBITRATION_VERDICT,
                                       ticket_id="t1")
    assert [i["who"] for i in arb] == ["d"]                    # 别票 e 被票号筛掉
    assert shared.active_authorizations(None, NOW) == []
    assert shared.active_authorizations("x", NOW) == []


def test_authorization_scopes_dedup_order():
    items = [
        {"kind": AUTH_PROTECTED_PATH, "who": "a", "scope": ["a/", "b"], "expires": NOW + 5},
        {"kind": AUTH_PROTECTED_PATH, "who": "b", "scope": ["b", "c"], "expires": NOW + 5},
        {"kind": AUTH_PROTECTED_PATH, "who": "c", "scope": ["d"], "expires": NOW - 1},
    ]
    assert shared.authorization_scopes(items, NOW, AUTH_PROTECTED_PATH) == ["a/", "b", "c"]


# ---------- 仲裁路由（零回归 + 放行面收窄） ----------

def test_cap_route_unauthorized_byte_identical():
    for verdict in ("pass", "tests-fault", "code-fault", "???", ""):
        for tr in range(0, 8):
            for cr in range(0, 8):
                assert shared.arbitration_cap_route(verdict, tr, cr, False) == \
                    shared.integration_route(verdict, tr, cr)


def test_cap_route_authorized_only_two_caps():
    M = shared.MAX_TESTS_FAULT_ROUNDS
    C = shared.MAX_CODE_FAULT_ROUNDS
    assert shared.arbitration_cap_route("tests-fault", M + 1, 0, True) == "acceptance"
    assert shared.arbitration_cap_route("code-fault", 0, C + 1, True) == "acceptance"
    # 未超限：授权不放行、也不改变原路由
    assert shared.arbitration_cap_route("tests-fault", M, 0, True) == "run_integration_tests"
    assert shared.arbitration_cap_route("code-fault", 0, C, True) == "implement"
    assert shared.arbitration_cap_route("pass", 99, 99, True) == "acceptance"


def test_cap_route_authorized_unknown_verdict_still_blocked():
    """负锁（RC3）：判决不存在＝无从「接受本判决」——畸形/未知 verdict 授权在场也 blocked，
    且不得被任何未来新增的 blocked 原因静默放行（谓词判定，非字符串前缀）。"""
    for bad in ("", "???", "Pass", "skip", None):
        r = shared.arbitration_cap_route(bad, 99, 99, True)
        assert r.startswith("blocked:") and "verdict" in r


# ---------- 机读键解析 ----------

def test_parse_authz_used():
    txt = ("worker 代落盘 x；%s张三@%d:a.mjs,b.mjs；"
           "%s李四@%d:verify.yaml" % (AUTHZ_USED_KEY, NOW, AUTHZ_USED_KEY, NOW + 1))
    got = shared.parse_authz_used(txt)
    assert got == [{"who": "张三", "issued": str(NOW), "files": "a.mjs,b.mjs"},
                   {"who": "李四", "issued": str(NOW + 1), "files": "verify.yaml"}]
    assert shared.parse_authz_used("") == []
    assert shared.parse_authz_used(None) == []
    assert shared.parse_authz_used("无键回执") == []
    # 畸形段（缺 @ / issued 非数）丢弃不炸
    assert shared.parse_authz_used("%sno-at-sign:files" % AUTHZ_USED_KEY) == []
    assert shared.parse_authz_used("%swho@abc:f" % AUTHZ_USED_KEY) == []


# ---------- 受保护豁免（split_protected / exempt_authorized） ----------

FILES = ["integration/baselines/sc_battery.py", "docs/design/contract-v1.md",
         "server/engine/keep.py"]


def _always(p=True):
    return lambda path: p


@pytest.mark.parametrize("authz", [(), None, [], "garbage", [{"kind": "bogus"}]])
def test_split_protected_identity_without_authz(authz):
    """无授权（含畸形授权面）＝ 与 judge_protected_paths 逐字节一致（零回归机械锁）。"""
    for pred in (_always(True), _always(False)):
        exp, _ = path_gates.judge_protected_paths(FILES, exists_at_base=pred)
        got, passed = authz_gates.split_protected(FILES, exists_at_base=pred,
                                                  authorizations=authz)
        assert got == exp
        assert passed == []


def test_split_protected_exact_and_prefix():
    rec = {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["integration/baselines"],
           "reason": "r", "issued": NOW, "expires": NOW + 10}
    got, passed = authz_gates.split_protected(FILES, exists_at_base=_always(True),
                                              authorizations=[rec])
    assert got == ["docs/design/contract-v1.md"]      # 未覆盖的照旧红
    assert passed == [{"path": "integration/baselines/sc_battery.py", "who": "宿主",
                       "issued": NOW, "reason": "r"}]
    # 精确路径条目同义
    rec2 = dict(rec, scope=["integration/baselines/sc_battery.py"])
    got2, passed2 = authz_gates.split_protected(FILES, exists_at_base=_always(True),
                                                authorizations=[rec2])
    assert got2 == ["docs/design/contract-v1.md"] and len(passed2) == 1


def test_scope_prefix_does_not_overmatch():
    """RC9 反用例：`integration/baselines` 不命中 `integration/baselines2/...`（_within 语义）。"""
    files = ["integration/baselines2/sc_x.py"]
    rec = {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["integration/baselines"],
           "reason": "r", "issued": NOW, "expires": NOW + 10}
    # baselines2 不在保护名单内→本就无 violation；用名单内文件验证匹配函数本身
    assert not path_gates._within("integration/baselines2/sc_x.py", ["integration/baselines"])
    assert path_gates._within("integration/baselines/sc_x.py", ["integration/baselines"])
    got, passed = authz_gates.split_protected(files, exists_at_base=_always(True),
                                              authorizations=[rec])
    assert got == [] and passed == []
    assert authz_gates._match("integration/baselines2/sc_x.py", [
        {"who": "宿主", "issued": NOW, "reason": "r", "scope": ["integration/baselines"]}]) is None


def test_exemption_attribution_two_authorizations():
    """C1：两条授权覆盖不同路径 → 逐条可归因，不得串味。"""
    files = ["integration/baselines/a.py", "docs/design/b.md"]
    recs = [
        {"kind": AUTH_PROTECTED_PATH, "who": "张三", "scope": ["integration/baselines"],
         "reason": "修期望值", "issued": NOW, "expires": NOW + 10},
        {"kind": AUTH_PROTECTED_PATH, "who": "李四", "scope": ["docs/design"],
         "reason": "改契约", "issued": NOW + 1, "expires": NOW + 10},
    ]
    got, passed = authz_gates.split_protected(files, exists_at_base=_always(True),
                                              authorizations=recs)
    assert got == []
    by_path = {p["path"]: p for p in passed}
    assert by_path["integration/baselines/a.py"]["who"] == "张三"
    assert by_path["docs/design/b.md"]["who"] == "李四"
    note = authz_gates.authorized_passage_note(passed)
    assert "张三" in note and "李四" in note
    keys = shared.parse_authz_used(note)
    assert {k["who"] for k in keys} == {"张三", "李四"}
    gotk = {k["who"]: k["files"] for k in keys}
    assert gotk["张三"] == "integration/baselines/a.py"
    assert gotk["李四"] == "docs/design/b.md"


def test_exemption_newest_issued_wins():
    files = ["verify.yaml"]
    recs = [
        {"kind": AUTH_PROTECTED_PATH, "who": "旧", "scope": ["verify.yaml"],
         "reason": "旧批", "issued": NOW, "expires": NOW + 10},
        {"kind": AUTH_PROTECTED_PATH, "who": "新", "scope": ["verify.yaml"],
         "reason": "新批", "issued": NOW + 5, "expires": NOW + 10},
    ]
    got, passed = authz_gates.split_protected(files, exists_at_base=_always(True),
                                              authorizations=recs)
    assert got == [] and passed[0]["who"] == "新"


def test_exemption_expiry_defense_in_depth():
    """纵深防线：now_epoch 给定时过期记录不豁免（workflow 侧已过滤；此处防误传）。"""
    files = ["verify.yaml"]
    recs = [{"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["verify.yaml"],
             "reason": "r", "issued": NOW, "expires": NOW + 10}]
    got, passed = authz_gates.split_protected(files, exists_at_base=_always(True),
                                              authorizations=recs, now_epoch=NOW + 11)
    assert got == ["verify.yaml"] and passed == []
    got2, passed2 = authz_gates.split_protected(files, exists_at_base=_always(True),
                                                authorizations=recs, now_epoch=NOW + 10)
    assert got2 == ["verify.yaml"] and passed2 == []       # 边界：expires==now 视为过期
    got3, passed3 = authz_gates.split_protected(files, exists_at_base=_always(True),
                                                authorizations=recs, now_epoch=None)
    assert got3 == [] and len(passed3) == 1                # 不给时刻=信任 workflow 已过滤


def test_exemption_ignores_malformed_records():
    files = ["verify.yaml"]
    recs = [{"kind": AUTH_PROTECTED_PATH, "who": "", "scope": ["verify.yaml"],
             "issued": NOW, "expires": NOW + 10},
            {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": [],
             "issued": NOW, "expires": NOW + 10},
            {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["verify.yaml"]},
            "not-a-dict", 7]
    got, passed = authz_gates.split_protected(files, exists_at_base=_always(True),
                                              authorizations=recs)
    # 第三条（scope 命中、无 expires）视为有效（expires 缺省不参与判定；workflow 侧已把时效
    # 关口前移）；前两条结构不全被丢弃；非 dict 丢弃不炸
    assert got == [] and passed and passed[0]["who"] == "宿主"


def test_exempt_authorized_empty_and_identity():
    assert authz_gates.exempt_authorized([]) == ([], [])
    assert authz_gates.exempt_authorized(None) == ([], [])
    v = ["verify.yaml", "docs/design/a.md"]
    got, passed = authz_gates.exempt_authorized(v)
    assert got == v and passed == []                        # 逐字节等于入参
    r = {"kind": AUTH_PROTECTED_PATH, "who": "宿主", "scope": ["docs/design"],
         "reason": "r", "issued": NOW, "expires": NOW + 10}
    got2, passed2 = authz_gates.exempt_authorized(v, [r])
    assert got2 == ["verify.yaml"] and passed2[0]["path"] == "docs/design/a.md"


def test_authorized_passage_note_sanitized():
    long_reason = "理由第一行\n第二行 " + "x" * 300
    passed = [{"path": "verify.yaml", "who": "宿主", "issued": NOW, "reason": long_reason}]
    note = authz_gates.authorized_passage_note(passed)
    assert "\n" not in note and "\r" not in note            # 单行（settle note 以「；」拼接）
    assert "…（全文见 meta.authorizations）" in note
    assert authz_gates.authorized_passage_note([]) == ""
    assert authz_gates.authorized_passage_note(None) == ""
    keys = shared.parse_authz_used(note)
    assert keys == [{"who": "宿主", "issued": str(NOW), "files": "verify.yaml"}]
