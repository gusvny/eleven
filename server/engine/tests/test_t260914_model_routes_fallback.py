"""t260914-05 模型路由表兜底腿退役（L1 单测）：三态可辨 + 点名告警 + 指纹 + 畸形输入。

被测：shared.resolve_routes_table / routes_fingerprint。t260914-05 起仓内兜底表
（server/model-routes.yaml）退役：非 ok 态一律无表（table=None），由解析层单点
WARNING 点名 state+path+指纹+原因（decl_missing 附建表建议落点）；查表侧回落
profile 默认由消费方（agent_activities）再点名——禁静默。消费方那条留痕属 spawn
缝隙面，由 integration/t260903-03 场景钉（本文件不重复）。

口径（票面 AC1，全部可机械断言）：
  ok           state=ok、path=声明文件、指纹=文件字节摘要、零告警；
  decl_missing path=""、table=None、指纹空、告警含「未声明」+条目路径+建表建议；
  file_missing path=声明路径、table=None、指纹空、告警含「文件缺失」+路径；
  bad_content  path=声明路径、table=None、指纹=坏文件字节摘要（可读字节照指纹，
               定位坏版本）；目录当表同态（无字节→指纹空）；**可解析但顶层非映射
               （标量/列表/标量值）同判 bad_content**（260915 P5：py/TS 同判，消费方
               不再 AttributeError 晦涩崩溃）；空文件=空表（ok，软语义保持）；
  三态互异 + **反毒断言**：decl_missing 下仓内表即使在位也不接管读（现场 A/B 的
  毒面=「表在场但过期被静默用错」的机械反证）。
查表语义零改动（红线）：(role,kind)→tasks→role→default→None 链路原样回归。
UT 全程零真环境写：注册表/表全在临时目录（SANDBAR_PROJECTS_DIR monkeypatch 注入）。
"""
import hashlib
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import shared  # noqa: E402

GOOD_TABLE = (
    "default:\n"
    "  provider: dft-prov\n"
    "  model: dft-model\n"
    "roles:\n"
    "  developer:\n"
    "    provider: dev-prov\n"
    "    model: dev-model\n"
    "  integration:\n"
    "    provider: int-prov\n"
    "    model: int-model\n"
)

_REPO_TABLE = Path(shared.__file__).resolve().parents[1] / "model-routes.yaml"


def _sha(path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def texts(self):
        return [r.getMessage() for r in self.records]


@pytest.fixture()
def routes_env(tmp_path, monkeypatch):
    """隔离注册表根 + shared 模块 logger 告警捕获（退出还原，零真环境写）。"""
    reg = tmp_path / "reg"
    reg.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))

    def mk_entry(key, paths_lines=None):
        d = reg / key
        d.mkdir(parents=True, exist_ok=True)
        lines = ["schema: v1", "project:", "  - key: %s" % key, "    name: t26091405",
                 "    dirs:", "      - %s" % (tmp_path / ("repo-" + key))]
        if paths_lines:
            lines += ["paths:"] + ["  %s: %s" % (k, v) for k, v in paths_lines]
        (d / "project.yaml").write_text("\n".join(lines) + "\n", "utf-8")
        return d / "project.yaml"

    cap = _Capture()
    logger = logging.getLogger(shared.__name__)
    old_level = logger.level
    logger.addHandler(cap)
    logger.setLevel(logging.WARNING)
    yield mk_entry, cap
    logger.removeHandler(cap)
    logger.setLevel(old_level)


def _declared_table(tmp_path, name="routes.yaml", text=GOOD_TABLE):
    d = tmp_path / "tbl"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text(text, "utf-8")
    return f


# ---------------- ok：真源生效、指纹=字节摘要、零告警 ----------------

def test_ok_state_fingerprint_and_no_warning(routes_env, tmp_path):
    mk, cap = routes_env
    table = _declared_table(tmp_path)
    mk("okk", [("model_routes", str(table))])
    r = shared.resolve_routes_table("okk")
    assert r["state"] == "ok"
    assert Path(r["path"]) == table and Path(r["declared"]) == table
    assert r["error"] == ""
    assert r["fingerprint"] == _sha(table)
    assert r["table"]["roles"]["developer"] == {"provider": "dev-prov", "model": "dev-model"}
    assert cap.texts() == [], "ok 态不得产生任何告警"


# ---------------- decl_missing：无表、path=""、点名含条目路径与建表建议 ----------------

def test_decl_missing_no_fallback_even_if_repo_table_present(routes_env, tmp_path):
    mk, cap = routes_env
    entry = mk("nopath")
    r = shared.resolve_routes_table("nopath")
    assert r["state"] == "decl_missing"
    assert r["declared"] is None and r["path"] == "" and r["table"] is None
    assert r["fingerprint"] == ""
    assert "未声明" in r["error"]
    assert str(entry) in r["error"], "error 须点名注册条目路径"
    assert "docs/model-routes-sample.yaml" in r["error"], "error 须给建表模板指引"
    # 反毒断言：仓内表即使在位也不接管读（(a) 删除后本断言同样成立）
    if _REPO_TABLE.is_file():
        assert r["table"] is None and r["path"] == ""
    msgs = cap.texts()
    assert any("[model_route]" in m and "state=decl_missing" in m and "指纹=" in m for m in msgs), msgs


def test_decl_missing_unknown_key_names_entry_missing(routes_env):
    mk, cap = routes_env
    mk("known")
    r = shared.resolve_routes_table("ghost-key")
    assert r["state"] == "decl_missing" and r["table"] is None and r["path"] == ""
    assert "条目缺失/未注册" in r["error"]
    assert any("state=decl_missing" in m for m in cap.texts())


# ---------------- file_missing：path=声明路径、无表、点名 ----------------

def test_file_missing(routes_env, tmp_path):
    mk, cap = routes_env
    absent = tmp_path / "tbl" / "absent.yaml"
    mk("fm", [("model_routes", str(absent))])
    r = shared.resolve_routes_table("fm")
    assert r["state"] == "file_missing"
    assert r["table"] is None and r["fingerprint"] == ""
    assert Path(r["path"]) == absent and Path(r["declared"]) == absent
    assert "文件缺失" in r["error"] and str(absent) in r["error"]
    assert any("state=file_missing" in m and "指纹=" in m for m in cap.texts())


# ---------------- bad_content：可读字节照指纹；目录当表无字节 ----------------

def test_bad_content_unparseable_keeps_fingerprint(routes_env, tmp_path):
    mk, cap = routes_env
    bad = _declared_table(tmp_path, "bad.yaml", "roles: [unclosed\n  provider: :::\n")
    mk("bc", [("model_routes", str(bad))])
    r = shared.resolve_routes_table("bc")
    assert r["state"] == "bad_content"
    assert r["table"] is None
    assert Path(r["path"]) == bad
    assert r["fingerprint"] == _sha(bad), "坏文件的字节指纹可读，用于定位坏版本"
    assert "不可解析" in r["error"] and str(bad) in r["error"]
    assert any("state=bad_content" in m and "sha256:" in m for m in cap.texts())


def test_bad_content_dir_as_table(routes_env, tmp_path):
    mk, cap = routes_env
    d = tmp_path / "dirtable"
    d.mkdir()
    mk("dirt", [("model_routes", str(d))])
    r = shared.resolve_routes_table("dirt")
    assert r["state"] == "bad_content" and r["table"] is None
    assert r["fingerprint"] == "", "目录读不出字节=指纹空串"
    assert "不可解析" in r["error"]
    assert any("state=bad_content" in m for m in cap.texts())


# ---------------- 非映射表（260915 P5 收紧）：可解析但顶层非 dict → bad_content ----------------

@pytest.mark.parametrize("text,shape", [("just-a-scalar", "str"), ("- a\n- b\n", "list"),
                                        ("42\n", "int"), ("true\n", "bool")])
def test_non_mapping_table_is_bad_content(routes_env, tmp_path, text, shape):
    """py/TS 同判：UI 半行式解析器一直拒收非映射文件，py 半放行会让消费方
    model_route_for 在 .get 处 AttributeError 晦涩崩溃——统一收进 bad_content 点名态。"""
    mk, cap = routes_env
    f = _declared_table(tmp_path, "nonmap.yaml", text)
    mk("nm-" + shape, [("model_routes", str(f))])
    r = shared.resolve_routes_table("nm-" + shape)
    assert r["state"] == "bad_content", "顶层=%s 须判坏表（实得 %s）" % (shape, r["state"])
    assert r["table"] is None
    assert r["fingerprint"] == _sha(f), "可读字节的坏文件照指纹"
    assert "不是映射结构" in r["error"] and shape in r["error"] and str(f) in r["error"]
    assert any("state=bad_content" in m and "sha256:" in m for m in cap.texts())
    # 消费面两条路都不再崩：
    # ① table=None（resolve 判坏后的形态）→ 回落 None（profile 默认）；
    # ② 直读路径 routes_file=同一坏文件 → 留痕回落 None（P5 第二层：不再 AttributeError）
    assert shared.model_route_for("developer", table=r["table"], routes_file=r["path"]) is None
    assert shared.model_route_for("developer", routes_file=f) is None
    assert any("顶层非映射" in m for m in cap.texts()), "直读路径留痕点名非映射"


def test_empty_table_file_stays_ok(routes_env, tmp_path):
    """空文件/空文档=空表（软语义保持，契约 ①d）：条目缺→查表回落 profile 默认。"""
    mk, cap = routes_env
    f = _declared_table(tmp_path, "empty.yaml", "")
    mk("empty", [("model_routes", str(f))])
    r = shared.resolve_routes_table("empty")
    assert r["state"] == "ok" and r["table"] == {}
    assert r["fingerprint"] == _sha(f)
    assert cap.texts() == []


# ---------------- 形状坏表（260915 gen2，P5 另一半）：查表链上值非映射 → bad_content ----------------

@pytest.mark.parametrize("key,text,why", [
    ("shape-roles", "roles: just-a-string\ndefault:\n  provider: p\n  model: m\n",
     "roles 段不是映射"),
    ("shape-entry", "roles:\n  developer: oops\n", "roles.developer 条目不是映射"),
    ("shape-tasks", "roles:\n  developer:\n    tasks: not-a-map\n",
     "roles.developer.tasks 不是映射"),
])
def test_shape_broken_table_is_bad_content(routes_env, tmp_path, key, text, why):
    """roles/条目/tasks 值非映射：消费方沿链 .get 必崩（260915 独立探针实证
    AttributeError）——resolve 层收进 bad_content 点名（带指纹），与顶层非映射同族。"""
    mk, cap = routes_env
    f = _declared_table(tmp_path, "shape.yaml", text)
    mk(key, [("model_routes", str(f))])
    r = shared.resolve_routes_table(key)
    assert r["state"] == "bad_content", why
    assert r["table"] is None
    assert r["fingerprint"] == _sha(f), "可读字节的形状坏表照指纹"
    assert "形状不可用" in r["error"] and why in r["error"] and str(f) in r["error"]
    assert any("state=bad_content" in m and "sha256:" in m for m in cap.texts())
    # 消费面不再崩：直读路径留痕回落 None（=profile 默认，禁静默口径不变）
    assert shared.model_route_for("developer", "implement", routes_file=f) is None
    assert any("形状不可用" in m for m in cap.texts()), "直读路径留痕点名形状坏"


def test_shape_broken_direct_table_tolerance(routes_env):
    """直传表（绕过 resolve）形状坏=不崩、不命中（点名归 resolve 面与直读留痕，此处只防崩）。"""
    assert shared.model_route_for("developer", table={"roles": "oops"}) is None
    assert shared.model_route_for("developer", "qa",
                                  table={"roles": {"developer": {"tasks": "x"}}}) is None


def test_default_non_map_stays_tolerated(routes_env, tmp_path):
    """default 值非映射=既有容错（消费方 isinstance 跳过、不崩、default 不命中）：
    不为它扩 bad_content（防语义漂移）；查表链上会 .get 的位置（roles/条目/tasks）才点名。"""
    mk, cap = routes_env
    f = _declared_table(tmp_path, "dft.yaml",
                        "roles:\n  developer:\n    provider: p\n    model: m\ndefault: [x]\n")
    mk("dft", [("model_routes", str(f))])
    r = shared.resolve_routes_table("dft")
    assert r["state"] == "ok" and r["table"]["default"] == ["x"]
    assert shared.model_route_for("ghost", table=r["table"], routes_file=r["path"]) is None
    assert cap.texts() == []


# ---------------- 三态互异（票面 AC1「三态各自可辨」的参数化全盖） ----------------

def test_three_states_mutually_distinct(routes_env, tmp_path):
    mk, cap = routes_env
    bad = _declared_table(tmp_path, "bad.yaml", "roles: [unclosed\n")
    mk("s-decl")  # 未声明
    mk("s-file", [("model_routes", str(tmp_path / "tbl" / "absent.yaml"))])
    mk("s-bad", [("model_routes", str(bad))])
    states = {shared.resolve_routes_table(k)["state"] for k in ("s-decl", "s-file", "s-bad")}
    assert states == {"decl_missing", "file_missing", "bad_content"}
    # 非空表路径互异 + 指纹形状两态空一态有
    rs = {k: shared.resolve_routes_table(k) for k in ("s-decl", "s-file", "s-bad")}
    assert rs["s-decl"]["fingerprint"] == "" and rs["s-file"]["fingerprint"] == ""
    assert rs["s-bad"]["fingerprint"].startswith("sha256:")
    assert len({r["state"] + "|" + r["error"][:24] for r in rs.values()}) == 3
    assert len(cap.texts()) >= 6, "每个非 ok 态每次解析都点名（engine 单点+消费可捕获）"


# ---------------- 畸形声明值 fail-closed（不静默猜） ----------------

def test_malformed_declarations_fail_closed(routes_env, tmp_path):
    mk, _ = routes_env
    for key, val in (("dotdot", "../escape.yaml"), ("blank", "   "),
                     ("nonscalar", "{a: 1}"), ("boguskey", "x")):
        mk("mal-" + key, [(("model_routes", val) if key != "boguskey" else ("bogus_key", val))])
        with pytest.raises(shared.ProjectPathsError):
            shared.resolve_routes_table("mal-" + key)


# ---------------- 查表语义零改动（红线回归） ----------------

def test_lookup_semantics_unchanged(routes_env, tmp_path):
    mk, _ = routes_env
    table = _declared_table(tmp_path)
    mk("lk", [("model_routes", str(table))])
    r = shared.resolve_routes_table("lk")
    t = r["table"]
    rf = r["path"]
    assert shared.model_route_for("developer", table=t, routes_file=rf) == \
        {"provider": "dev-prov", "model": "dev-model"}
    assert shared.model_route_for("integration", "proofread", table=t, routes_file=rf) == \
        {"provider": "int-prov", "model": "int-model"}
    assert shared.model_route_for("ghost", table=t, routes_file=rf) == \
        {"provider": "dft-prov", "model": "dft-model"}
    assert shared.model_route_for("ghost", "qa", table=t, routes_file=rf) == \
        {"provider": "dft-prov", "model": "dft-model"}
    # 表在但全空（无命中也无 default）→ None（profile 默认），语义不变
    assert shared.model_route_for("ghost", "qa", table={}) is None
    with pytest.raises(ValueError):
        shared.model_route_for("integration")  # 无路径无表 → 拒绝（单点化不回退）


# ---------------- 指纹助手 ----------------

def test_routes_fingerprint_helper(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text("a: 1\n", "utf-8")
    assert shared.routes_fingerprint(f) == _sha(f)
    assert shared.routes_fingerprint(tmp_path / "nope.yaml") == ""
    assert shared.routes_fingerprint(tmp_path) == ""
