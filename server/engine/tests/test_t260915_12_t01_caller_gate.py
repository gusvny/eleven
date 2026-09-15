"""t260915-12 跨项目写操作闸——纯函数层单测（t01）。

覆盖（review 条件逐条对应）：
- C1：cwd 窄兜底的**仓树整体排除**（仓根等值与任意深度子目录都不推导，宁 undeclared
  不凭空造身份）+ longest-prefix 反查 + 未命中/空路径；
- C2②：形状合法但注册表查无的 declared 值——判定矩阵不查注册表（declared 照判），
  registered 观测键由 client 侧负责（t02）；
- C4：越权旗 by/reason 必填非空 + 上限（超长=畸形腿）；
- 判定矩阵全腿：老 client 未盖章兼容、同项目、异项目无旗拒收、异项目带旗记名、
  undeclared 哨兵 record/refuse 两策略、note 入账截断；
- C-0②：UNDECLARED_POLICY 单常量值锁（"record"）；
- 四个写信号载荷的盖章字段带默认值（重放安全形状）。
全程零 Temporal/零网络/零真实环境（conftest 已把引擎目录挂进 sys.path）。
"""
import dataclasses

import pytest

import caller_gate
import shared


PROJ = [
    {"key": "sandbar", "dirs": ["/repo"]},
    {"key": "dengzhufpv", "dirs": ["/Users/user/Documents/dengzhufpv",
                                   "/Users/user/Documents/dengzhufpv/sub"]},
]
REPO_TREE = ("/repo",)
PROJ2 = [
    {"key": "sandbar", "dirs": ["/repo"]},
    {"key": "dengzhufpv", "dirs": ["/var/folders/x/repo-sub"]},  # 原文形（不 deref）
]


# ---------- 常量与策略锁（C-0②） ----------

def test_undeclared_policy_constant_locked():
    """B 策略值锁：翻 A（refuse）时必须连场景一起改——本测试就是那把锁的一部分。"""
    assert shared.UNDECLARED_POLICY == "record"


def test_env_and_mark_and_limits():
    assert shared.CALLER_PROJECT_ENV == "SANDBAR_CALLER_PROJECT"
    assert shared.CALLER_UNDECLARED_MARK == "__undeclared__"
    # C4：上限家族同值不同源（与 pause/host_ruling note、authz who 独立演进）
    assert shared.CROSS_PROJECT_NOTE_LIMIT == 20000
    assert shared.CROSS_PROJECT_BY_LIMIT == 64
    assert shared.CROSS_PROJECT_NOTE_LIMIT != 0 and shared.CROSS_PROJECT_BY_LIMIT != 0


@pytest.mark.parametrize("cls", ["Signature", "ReworkRequest", "PauseRequest",
                                 "HostRulingRequest"])
def test_stamp_fields_default_empty(cls):
    """盖章字段带默认值=老历史/老 client 解码兼容（重放安全形状，TicketInput 先例同款）。"""
    fields = {f.name: f for f in dataclasses.fields(getattr(shared, cls))}
    assert fields["caller_project"].default == ""
    assert fields["cross_project_note"].default == ""


# ---------- project_key_for_dir（C1 仓树排除 + longest-prefix） ----------

def test_key_for_dir_basic_and_longest_prefix():
    assert shared.project_key_for_dir("/repo/server/engine", PROJ, REPO_TREE) == ""
    assert shared.project_key_for_dir("/Users/user/Documents/dengzhufpv/sub/x", PROJ, REPO_TREE) == "dengzhufpv"
    assert shared.project_key_for_dir("/elsewhere", PROJ, REPO_TREE) == ""


def test_key_for_dir_repo_tree_excluded_whole_subtree():
    """C1 行为腿：仓根等值与仓内任意深度子目录一律不推导（console 插件 cwd=仓内
    子目录不得被判成 declared sandbar——否则 console 跨项目写被静默硬拒）。"""
    assert shared.project_key_for_dir("/repo", PROJ, REPO_TREE) == ""
    assert shared.project_key_for_dir("/repo/", PROJ, REPO_TREE) == ""
    assert shared.project_key_for_dir("/repo/a/b/c", PROJ, REPO_TREE) == ""
    # 排除树之外的注册目录照常推导
    assert shared.project_key_for_dir("/Users/user/Documents/dengzhufpv", PROJ, REPO_TREE) == "dengzhufpv"


def test_key_for_dir_symlink_dual_form():
    """符号链接稳健腿：注册表条目锚定原文（/var 形），cwd realpath（/private/var 形）
    ——双侧 realpath 归一后仍要命中（bench.write_registry 刻意不 deref 的对侧）。"""
    assert shared.project_key_for_dir(
        "/private/var/folders/x/repo-sub", PROJ2, ("/Users/repo",)) == "dengzhufpv"


def test_key_for_dir_empty_and_prefix_confusion():
    """前缀混淆腿：/repoX 不得因 /repo 前缀误命中（必须按路径段比对）。"""
    assert shared.project_key_for_dir("/repository", PROJ, REPO_TREE) == ""
    assert shared.project_key_for_dir("", PROJ, REPO_TREE) == ""


# ---------- resolve_identity（解析顺序 + 形状白名单） ----------

def test_resolve_arg_beats_env():
    ident = caller_gate.resolve_identity("dengzhufpv", "sandbar",
                                         cwd="/Users/user/Documents/dengzhufpv",
                                         exclude_trees=REPO_TREE, projects=PROJ)
    assert ident == {"value": "dengzhufpv", "src": "arg", "identity_class": "declared"}


def test_resolve_env():
    ident = caller_gate.resolve_identity("", "dengzhufpv", projects=PROJ)
    assert ident["src"] == "env" and ident["value"] == "dengzhufpv"


def test_resolve_cwd_narrow_and_none():
    ident = caller_gate.resolve_identity("", "", cwd="/Users/user/Documents/dengzhufpv/x",
                                         exclude_trees=REPO_TREE, projects=PROJ)
    assert ident["src"] == "cwd" and ident["value"] == "dengzhufpv"
    ident2 = caller_gate.resolve_identity("", "", cwd="/tmp/nowhere",
                                          exclude_trees=REPO_TREE, projects=PROJ)
    assert ident2 == {"value": "", "src": "none", "identity_class": "undeclared"}
    # 仓树内 cwd（含子目录）→ 恒 undeclared（C1）
    ident3 = caller_gate.resolve_identity("", "", cwd="/repo/server/engine",
                                          exclude_trees=REPO_TREE, projects=PROJ)
    assert ident3["identity_class"] == "undeclared" and ident3["src"] == "none"


def test_resolve_blank_equals_absent():
    """空/纯空白显式值=未声明（与 audit.py「空串 env 视同未设」同款，不报错）。"""
    for blank in ("", "   "):
        ident = caller_gate.resolve_identity(blank, "", projects=PROJ)
        assert ident["identity_class"] == "undeclared"


@pytest.mark.parametrize("val", ["SANDBAR", "x" * 65, "../evil", "a b"])
def test_resolve_shape_invalid_raises(val):
    with pytest.raises(caller_gate.CallerIdentityError):
        caller_gate.resolve_identity(val, "", projects=PROJ)
    with pytest.raises(caller_gate.CallerIdentityError):
        caller_gate.resolve_identity("", val, projects=PROJ)


# ---------- validate_override（C3/C4 越权旗） ----------

def test_override_absent():
    assert caller_gate.validate_override({}) == (None, "")


def test_override_struct_ok_and_flat_ok():
    got, err = caller_gate.validate_override({"cross_project": {"by": "宿主", "reason": "代管"}})
    assert err == "" and got == {"by": "宿主", "reason": "代管"}
    got2, err2 = caller_gate.validate_override({"who": "宿主", "cross_project_reason": "救火"})
    assert err2 == "" and got2 == {"by": "宿主", "reason": "救火"}


@pytest.mark.parametrize("args,frag", [
    ({"cross_project": {"reason": "r"}}, "缺 by"),
    ({"who": "宿主", "cross_project": {"reason": "r"}}, "缺 by"),  # 结构形缺 by 不从 who 兜底（真链路相六腿）
    ({"cross_project": {"by": "x"}}, "缺 reason"),
    ({"cross_project_reason": "r"}, "缺 by"),
    ({"who": "w", "cross_project_reason": ""}, ""),  # 空扁平理由=无旗（非错误）
    ({"cross_project": "yes"}, "对象"),
    ({"cross_project": {"by": "a", "reason": "r"}, "cross_project_reason": "r"}, "只给其一"),
    ({"cross_project": {"by": "x" * 65, "reason": "r"}}, "by 超限"),
    ({"cross_project": {"by": "x", "reason": "r" * 20001}}, "reason 超限"),
])
def test_override_malformed(args, frag):
    got, err = caller_gate.validate_override(args)
    if args.get("who") == "w" and args.get("cross_project_reason") == "":
        assert got is None and err == ""  # 空 flat 理由视同无旗
    else:
        assert got is None and frag in err


# ---------- judge_caller（客户端判定矩阵） ----------

def _ident(value, iclass="declared", src="env"):
    return {"value": value, "src": src, "identity_class": iclass}


def test_judge_same_project_pass():
    v = caller_gate.judge_caller(_ident("sandbar"), "sandbar", None)
    assert v["decision"] == "pass" and v["stamp"] == "sandbar"


def test_judge_mismatch_no_flag_refuse():
    v = caller_gate.judge_caller(_ident("dengzhufpv"), "sandbar", None)
    assert v["decision"] == "refuse"
    assert "dengzhufpv" in v["why"] and "sandbar" in v["why"]  # 人话点名谁动谁的票


def test_judge_mismatch_with_flag_override():
    v = caller_gate.judge_caller(_ident("dengzhufpv"), "sandbar",
                                 {"by": "宿主", "reason": "代管收口"})
    assert v["decision"] == "pass_override" and v["override_used"] is True
    assert "宿主" in v["notice"] and "代管收口" in v["notice"]


def test_judge_undeclared_record_and_refuse_flip():
    v = caller_gate.judge_caller(_ident("", "undeclared", "none"), "sandbar", None)
    assert v["decision"] == "record_undeclared"
    assert v["stamp"] == shared.CALLER_UNDECLARED_MARK
    assert "未声明" in v["notice"]
    # C2②：undeclared 时即便带旗也按 undeclared 记名（旗不升格身份）
    v2 = caller_gate.judge_caller(_ident("", "undeclared", "none"), "sandbar",
                                  {"by": "x", "reason": "r"})
    assert v2["decision"] == "record_undeclared"
    # 翻 A（终态）：同输入直接拒
    v3 = caller_gate.judge_caller(_ident("", "undeclared", "none"), "sandbar", None) \
        if shared.UNDECLARED_POLICY == "refuse" else None
    if v3 is not None:
        assert v3["decision"] == "refuse"


def test_judge_engine_internal_target_empty():
    """cancel 打在无 ProjectKey SA 的引擎件上=无比对对象，恒放行。"""
    v = caller_gate.judge_caller(_ident("dengzhufpv"), "", None)
    assert v["decision"] == "pass"


def test_judge_registered_is_not_consulted():
    """C2②：判定不查注册表——形状合法但未注册的 key 仍按 declared 判（误配显式暴露）。"""
    v = caller_gate.judge_caller(_ident("ghost-project"), "sandbar", None)
    assert v["decision"] == "refuse"


# ---------- shared.cross_project_judge（workflow 侧第二道） ----------

def test_wf_judge_unstamped_and_targetless_allow():
    assert shared.cross_project_judge("", "sandbar", "")["action"] == "allow"
    assert shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "", "")["action"] == "allow"
    assert shared.cross_project_judge("dengzhufpv", "", "")["action"] == "allow"


def test_wf_judge_same_and_mismatch():
    assert shared.cross_project_judge("sandbar", "sandbar", "")["action"] == "allow"
    g = shared.cross_project_judge("dengzhufpv", "sandbar", "")
    assert g["action"] == "refuse" and "dengzhufpv" in g["why"] and "sandbar" in g["why"]
    g2 = shared.cross_project_judge("dengzhufpv", "sandbar", "宿主代管")
    assert g2["action"] == "allow_record"
    assert g2["record"]["caller_project"] == "dengzhufpv"
    assert g2["record"]["note"] == "宿主代管"


def test_wf_judge_undeclared_sentinel_record():
    g = shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "sandbar", "")
    assert g["action"] == "allow_record"
    assert g["record"]["caller_project"] == shared.CALLER_UNDECLARED_MARK
    g2 = shared.cross_project_judge(shared.CALLER_UNDECLARED_MARK, "sandbar", "", policy="refuse")
    assert g2["action"] == "refuse"


def test_wf_judge_note_truncated_into_record():
    g = shared.cross_project_judge("dengzhufpv", "sandbar", "x" * 5000)
    assert g["action"] == "allow_record"
    assert len(g["record"]["note"]) == 300  # 入账截断（防 note 巨物进 meta）


# ---------- identity_receipt（回执键构造） ----------

def test_receipt_keys_shape():
    ident = _ident("dengzhufpv")
    verdict = caller_gate.judge_caller(ident, "sandbar",
                                       {"by": "宿主", "reason": "r"})
    keys = caller_gate.identity_receipt(ident, verdict)
    assert keys["caller_project"] == "dengzhufpv"
    assert keys["identity_src"] == "env" and keys["identity_class"] == "declared"
    assert keys["cross_project_used"] is True and "cross_project_notice" in keys


def test_receipt_undeclared_empty_value_with_class():
    ident = _ident("", "undeclared", "none")
    verdict = caller_gate.judge_caller(ident, "sandbar", None)
    keys = caller_gate.identity_receipt(ident, verdict)
    assert keys["caller_project"] == ""  # 面向人：undeclared 用空值+class 表达
    assert keys["identity_class"] == "undeclared"
