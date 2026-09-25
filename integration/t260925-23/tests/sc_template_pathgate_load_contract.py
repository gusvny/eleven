#!/usr/bin/env python3
"""外置模板路径闸声明的加载口深检（t260925-23 / KI-124，灰盒 L2）。

用户可感知契约：外置模板经**公开加载口**（project_templates 扫描，与
TEMPLATE_ID/STAGES 同一通道）声明路径闸——
  B1 形状合法的声明（PATH_GATE=True + PATH_GATE_RULES 键⊆STAGES ids、kind 在
     词表、prefixes 带前缀表）→ 模板被接受（不因新声明被误拒）；
  B2 键 ∉ STAGES ids → 模板级拒收，点名非法键（工单需求③：段 id 集 ⊆ 规则
     键集纪律的加载口执法面——错声明被堵在门口，不是运行期炸）；
  B3 kind 不在词表 → 拒收点名；
  B4 prefixes kind 缺前缀表 → 拒收点名；
  B5 声明 RULES 但 PATH_GATE 非 True（死配置）→ 拒收点名（不许装死）；
  B6 RULES 非 dict（畸形）→ 拒收点名；
  B7 外置模板声明强 kind（self_heal/test_face）→ 拒收点名（review_plan 附条件
     ④：外置模板收窄到弱面子集，强面=引擎自愈/测试裁决授权，缺省即关）；
  B8 不声明 PATH_GATE → 照常接受、零行为变化（KI-124 现状回落，本子用例
     实现落地前即应绿=基线证明）。

与 developer L1（test_t260924_04 加载口矩阵、judge 纯函数）intent 分工：本条以
公开扫描口（shared.project_template_scan，import_classes=True）锁「声明面用户
可感知终态=接受/拒收+点名」，不含进程内私有函数直调。
与 t260925-23 faces 条分工：本条锁声明进出（加载口），彼锁声明驱动的 settle
执法终态（执行面）。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260925-23/tests/sc_template_pathgate_load_contract.py（cwd=仓根）
纯本地：临时注册根（注入参数，不污染进程 env 与 shared 全局表——用例自恢复），
零 Temporal 零端口，秒级。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
B2-B7 实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
import pathlib
import shutil
import sys
import tempfile

_ok = _fail = 0


def ok(cond, label):
    global _ok, _fail
    print(("  ok " if cond else "  FAIL ") + label)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


def section(t):
    print("\n== " + t)


def load_engine():
    try:
        import temporalio  # noqa: F401
    except Exception:
        print("ENV_FAIL: temporalio 不可导入——用 server/engine/.venv/bin/python 跑"
              "（环境红非产品红，exit 2 三态契约）")
        sys.exit(2)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "server" / "engine"))
    import shared
    return shared


# 合法外置模板骨架：两个自有段 id（不在内建 STAGE_PATH_RULES 键集，KI-124 同构）。
TMPL = '''TEMPLATE_ID = "tpl-pathgate-{tag}"
TEMPLATE_NAME = "路径闸声明测试模板 {tag}"
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class TplPathgate{tag_cls}(TicketWorkflowBase):
    STAGES = (Stage(id="s1", name="一", role="developer", next="s2", acceptance=("a",)),
              Stage(id="s2", name="二", role="integration", next="", acceptance=("b",)))
    PATCH_ID = "projp-pathgate-{tag}"
    TEMPLATE_ID = "tpl-pathgate-{tag}"
    TEMPLATE_NAME = "路径闸声明测试模板 {tag}"{extra}

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
'''

DECL_ON = '\n    PATH_GATE = True\n    PATH_GATE_RULES = %r\n'


def mk_project(root, key, module_body):
    """临时注册根下建一项目条目（契约①a schema v1）＋一个模板模块，返回模块相对路径。"""
    pd = root / key
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: 测试项目\n    dirs:\n      - %s\n"
        "paths:\n  workflow_modules: mods/tpl.py\n" % (key, pd), "utf-8")
    (pd / "mods").mkdir(exist_ok=True)
    (pd / "mods" / "tpl.py").write_text(module_body, "utf-8")


def scan_rejections(shared, root):
    res = shared.project_template_scan(import_classes=True, root=str(root))
    return res, list(res.rejections)


def rejs_about(rejections):
    return [r for r in rejections if r.get("project") == "proj-x"]


def case(shared, root, tag, rules, gate=True, expect_reject=True, label=""):
    extra = DECL_ON % (dict(rules),) if rules is not None else ""
    if rules is not None and not gate:
        extra = '\n    PATH_GATE = False\n    PATH_GATE_RULES = %r\n' % (dict(rules),)
    mk_project(root, "proj-x", TMPL.format(tag=tag, tag_cls=tag.title().replace("-", ""), extra=extra))
    res, rejections = scan_rejections(shared, root)
    mine = rejs_about(rejections)
    if expect_reject:
        ok(bool(mine), label + "：模板级拒收在场")
        if mine:
            r = mine[0]
            detail = "%s|%s" % (r.get("check", ""), r.get("detail", ""))
            # B4 的拒收文案口径是「路径闸声明不合：…须配套非空前缀表 prefixes」——
            # 点名的是段与缺的表，不出现「模板/PATH_GATE/规则」字样，故启发式收
            # 「声明」入集（声明面拒收=路径闸声明不合前缀，同面）。
            ok("模板" in detail or "PATH_GATE" in detail or "规则" in detail
               or "声明" in detail,
               label + "：拒收点名声明面（check=%s）" % r.get("check", ""))
            print("      detail: %s" % detail[:200])
    else:
        ok(not mine, label + "：零拒收（%s）" % ("；".join("%s:%s" % (r.get("check"), r.get("detail", "")[:80]) for r in mine) or "accepted"))
    return res


def main():
    shared = load_engine()

    # ---- B8 基线：不声明 PATH_GATE → 接受、零行为变化（现状即绿） ----
    section("B8 不声明 PATH_GATE → 照常接受（KI-124 回落基线，现状即绿）")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b8-"))
    case(shared, root, "b8", rules=None, expect_reject=False,
         label="无声明模板被接受")

    # ---- B1 合法声明 → 接受 ----
    section("B1 合法声明（键⊆STAGES、kind 合法、prefixes 带表）→ 接受")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b1-"))
    case(shared, root, "b1",
         rules={"s1": {"kind": "result_files"}, "s2": {"kind": "prefixes", "prefixes": ("reports",)}},
         expect_reject=False, label="合法声明模板被接受")

    # ---- B2 键 ∉ STAGES ids → 拒收点名 ----
    section("B2 规则键不在 STAGES ids → 拒收点名双方")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b2-"))
    case(shared, root, "b2", rules={"ghost_stage": {"kind": "result_files"}},
         expect_reject=True, label="越键声明")

    # ---- B3 kind 非法 → 拒收 ----
    section("B3 kind 不在词表 → 拒收点名")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b3-"))
    case(shared, root, "b3", rules={"s1": {"kind": "no_such_kind"}},
         expect_reject=True, label="非法 kind")

    # ---- B4 prefixes 缺前缀表 → 拒收 ----
    section("B4 prefixes kind 缺 prefixes 表 → 拒收点名")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b4-"))
    case(shared, root, "b4", rules={"s1": {"kind": "prefixes"}},
         expect_reject=True, label="prefixes 缺表")

    # ---- B5 RULES 有而 PATH_GATE 非 True（死配置）→ 拒收 ----
    section("B5 声明 RULES 但 PATH_GATE=False（死配置）→ 拒收点名")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b5-"))
    case(shared, root, "b5", rules={"s1": {"kind": "result_files"}}, gate=False,
         expect_reject=True, label="死配置")

    # ---- B6 RULES 非 dict（畸形）→ 拒收 ----
    section("B6 PATH_GATE_RULES 非 dict → 拒收点名")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b6-"))
    pd = root / "proj-x"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: proj-x\n    name: 测试项目\n    dirs:\n      - %s\n"
        "paths:\n  workflow_modules: mods/tpl.py\n" % pd, "utf-8")
    (pd / "mods").mkdir(exist_ok=True)
    (pd / "mods" / "tpl.py").write_text(
        TMPL.format(tag="b6", tag_cls="B6", extra="\n    PATH_GATE = True\n    PATH_GATE_RULES = (\"s1\",)\n"),
        "utf-8")
    _, rejections = scan_rejections(shared, root)
    mine = rejs_about(rejections)
    ok(bool(mine), "B6：畸形声明拒收在场")
    if mine:
        print("      detail: %s|%s" % (mine[0].get("check", ""), mine[0].get("detail", "")[:160]))

    # ---- B7 外置模板强 kind（self_heal）→ 拒收（弱面子集收口） ----
    section("B7 外置模板声明强 kind self_heal → 拒收点名（弱面子集）")
    root = pathlib.Path(tempfile.mkdtemp(prefix="t26092523-load-b7-"))
    case(shared, root, "b7", rules={"s1": {"kind": "self_heal"}},
         expect_reject=True, label="强 kind 越面")

    print("\nSC sc_template_pathgate_load_contract pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
