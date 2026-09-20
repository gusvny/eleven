#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260908-02 场景：混合形态工单 payload 编解码缝（TicketInput/WorkspacePrep 一等字段，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同）：混合形态项目（根 git 仓+子仓，dengzhufpv
形态）开票时，建票链推导出的多仓泳道明细（repo_worktrees）必须以**一等字段**
（dataclass 显形注解）穿越 Temporal payload 编解码两跳——workflow 启动输入
（TicketInput）与工作区准备 activity 入参（WorkspacePrep）——不再以 list 藏在
workspace dict 值里撞类型注解（t260907-13 实锤：worker「Failed converting field
workspace」，workflow 起不来=dengzhufpv T2 停摆）。拆分子用例：

- 形状契约子用例（stdlib）：TicketInput/WorkspacePrep 均有 repo_worktrees 字段、
  带 default_factory=list 缺省（存量 RUNNING 实例重放缺键不破回放面）；derive
  产物可无痕拆分——pop 掉 repo_worktrees 后 workspace 只剩 {type, path}；
- 编解码缝子用例（temporalio）：拆分链产物 TicketInput(workspace=纯形状,
  repo_worktrees=明细) 经 DataConverter 默认 payload converter 编解码往返全等
  （=workflow 启动面不再 TypeError）；WorkspacePrep 第二跳同款往返全等（=activity
  入参面）；单仓对照子用例往返绿且 repo_worktrees 恒 []（单仓/纯容器零回归）；
- 畸形分层子用例（报错必须精确）：类型毁形（repo_worktrees 条目非对象）在**编解码层**
  拒（from_payloads 抛错=启动面拒绝）；形状合法但语义非法（branch 碰撞/条目缺
  name）在**闸层**拒（lane_workspace_gate_error 文案可辨），两层断言互不冒充；
- 闸新位/旧位子用例（stdlib）：新位 meta 顶层 repo_worktrees 畸形照拒（fail-closed
  不弱化）；旧位 workspace 内嵌回落兼容同样照拒（存量直调通道不逃检）；
- 行为通道子用例（temporalio，夹具直调 prepare_workspace 公开 activity 入口）：
  一等字段通道端到端生效——prep.repo_worktrees 到达 prepare 即逐仓挂树 created、
  清单落盘；旧形状（ws 内嵌）回落通道仍工作（修复不得破坏既有直调兼容面）。

与相邻场景 intent 分界：t260907-06 三场景守「父目录作根」多仓形态的归属/合并闸/
fail-closed 全链（经 write_set+project_root 推导通道）；t260907-12 守混合形态
derive 激活与逐仓挂载全链——两者均不触 payload 编解码缝（当年夹具直调绕过该缝
正是本 bug 漏网根因，KI-049③缝契约同族教训）。本场景只守「多仓明细穿越 Temporal
编解码两跳+畸形分层拒绝」这一缝。实现落地前红属预期（TDD 信号），arbitrate/merge
期必须绿；temporalio 缺失=ENV_FAIL 点名（编解码/行为子用例），stdlib 形状/闸契约子用例照跑。
"""
import sys
import typing
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "t260912"))

from lib_t260912 import (  # noqa: E402
    POC, check, summary, env_fail, temporalio_available, git,
    build_mixed_project, build_single_repo_project, read_manifest,
    lane_worktree_registered, cleanup, shared_workspace_prep_cls,
    call_with_supported_fields, CapabilityMissing,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面

TICKET_MX = "t260908mx"   # 混合形态主子用例
TICKET_SG = "t260908sg"   # 单仓对照
WS_MX = ["docs/kb.md", "repo_a/src/a.py"]   # 双命中：根树+repo_a 子树
WS_SG = ["src/main.py"]

root_mx, repos_mx = build_mixed_project(prefix="t260908-02-mixed-")
root_sg = build_single_repo_project(prefix="t260908-02-single-")

# ---------- 拆分规则（生产链公开形状：client 建票口对 derive 产物的处理） ----------
def derive_split(root, ticket_id, write_set):
    """derive → 按一等字段契约拆分 → (纯 ws, repo_worktrees 明细)。

    拆分以「pop 内嵌键」表达：derive 无论产内嵌形状（现实现）还是纯形状（未来
    实现自由），pop 无痕拆出/落空两态均得 (纯 ws, 明细|None)——场景锚契约不锚
    derive 内部形状（契约不变的实现重构不得打破本场景）。"""
    _lane, ws, _wt, _br = shared.derive_lane_workspace(
        ticket_id, "worktree", lane="", workspace=None, worktree="", branch="",
        template_workspace_dir=False, project_root=str(root),
        repo_write_set=list(write_set))
    rws = ws.pop("repo_worktrees", None)
    return ws, rws

def ticket_input(**kw):
    import shared
    return call_with_supported_fields(shared.TicketInput, template_id="dev-lane", **kw)

# ---------- M1 形状契约子用例（stdlib，系统 python3 可跑） ----------
def _fields_with_default(cls):
    import dataclasses
    return {f.name: f for f in dataclasses.fields(cls)}

f_ti = _fields_with_default(shared.TicketInput)
check("M1a TicketInput 形状：repo_worktrees 一等字段在场（t260907-13 缺口）",
      "repo_worktrees" in f_ti,
      "fields=%s" % sorted(f_ti))
if "repo_worktrees" in f_ti:
    # shared.py 有 from __future__ import annotations 时 f.type 为字符串形态，两态等价接受
    want = {str(typing.List[typing.Dict[str, str]]), "List[Dict[str, str]]"}
    check("M1a-1 注解显形=List[Dict[str, str]]（形状显式，非 Any 放宽）",
          str(f_ti["repo_worktrees"].type) in want,
          "got %r" % (f_ti["repo_worktrees"].type,))
    check("M1a-2 带缺省 default_factory=list（存量 RUNNING 实例重放缺键不破回放）",
          f_ti["repo_worktrees"].default_factory is list,
          "default_factory=%r" % (f_ti["repo_worktrees"].default_factory,))
f_wp = _fields_with_default(shared_workspace_prep_cls())
check("M1b WorkspacePrep 形状：repo_worktrees 一等字段在场（第二跳同病同步修）",
      "repo_worktrees" in f_wp,
      "fields=%s" % sorted(f_wp))
if "repo_worktrees" in f_wp:
    check("M1b-1 带缺省 default_factory=list（replay-safe）",
          f_wp["repo_worktrees"].default_factory is list,
          "default_factory=%r" % (f_wp["repo_worktrees"].default_factory,))

ws_mx, rws_mx = derive_split(root_mx, TICKET_MX, WS_MX)
check("M1c 混合 derive 产物可无痕拆分：pop 后 workspace 只剩 {type, path}",
      set(ws_mx) == {"type", "path"},
      "residual keys=%s" % sorted(ws_mx))
check("M1c-1 拆出明细形状：非空 list，条目含 repo/name/branch",
      isinstance(rws_mx, list) and rws_mx
      and all({"repo", "name", "branch"} <= set(e) for e in rws_mx if isinstance(e, dict)),
      "rws=%r" % (rws_mx,))
ws_sg, rws_sg = derive_split(root_sg, TICKET_SG, WS_SG)
check("M1d 单仓对照：derive 产物无内嵌键、拆分恒空（零回归面）",
      set(ws_sg) == {"type", "path"} and not rws_sg,
      "ws=%r rws=%r" % (ws_sg, rws_sg))

# ---------- 闸子用例（stdlib）：畸形分层之「闸层」+ 新位/旧位 ----------
def _good_entry(name, branch):
    return {"repo": "repo_a", "name": name, "branch": branch}

gate = shared.lane_workspace_gate_error
meta_new_bad = {"lane": "worktree", "workspace": dict(ws_mx),
                "worktree": ws_mx.get("path", ""), "branch": "lane/x",
                "repo_worktrees": [_good_entry("a", "lane/one"), _good_entry("b", "lane/one")]}
err_new = gate(meta_new_bad)
check("M2a 闸新位：meta 顶层 repo_worktrees 分支碰撞 → 拒且文案可辨（fail-closed 新位不漏）",
      bool(err_new) and "碰撞" in err_new,
      "err=%r" % (err_new,))
meta_new_ok = dict(meta_new_bad)
meta_new_ok["repo_worktrees"] = [_good_entry("a", "lane/one"), _good_entry("b", "lane/two")]
err_new_ok = gate(meta_new_ok)
check("M2a-1 闸新位：合法条目放行（返回空）", err_new_ok == "", "err=%r" % (err_new_ok,))
meta_old_bad = {"lane": "worktree",
                "workspace": dict(ws_mx, repo_worktrees=[_good_entry("a", "lane/one"),
                                                         _good_entry("b", "lane/one")]),
                "worktree": ws_mx.get("path", ""), "branch": "lane/x"}
err_old = gate(meta_old_bad)
check("M2b 闸旧位回落：workspace 内嵌旧形状畸形 → 仍拒（回落兼容不弱化检）",
      bool(err_old) and "碰撞" in err_old,
      "err=%r" % (err_old,))

# ---------- M3 编解码缝子用例（temporalio 面） ----------
if not temporalio_available():
    env_fail("temporalio 缺失：M3 编解码缝子用例与 M4 行为通道子用例无法执行（pip install temporalio）")
else:
    from temporalio.converter import DataConverter
    pc = DataConverter.default.payload_converter

    def roundtrip(obj, cls):
        # 编码不带提示（1.18 to_payloads 无 type_hints 参）、解码带注解——与 worker
        # 实况同构：worker 收到的是 workflow 侧编码的 payload，按 dataclass 注解还原
        payload = pc.to_payloads([obj])
        (back,) = pc.from_payloads(payload, [cls])
        return back

    # M3a 主子用例（=t260907-13 启动面）：拆分链产物过编解码，一等字段往返存活
    try:
        inp = ticket_input(ticket_id=TICKET_MX, workspace=ws_mx, repo_worktrees=rws_mx or [])
    except CapabilityMissing:
        inp = None
        check("M3a TicketInput 编解码往返：一等字段在场", False,
              "TicketInput 不支持 repo_worktrees 字段（工单正文点名缺口未落地）")
    if inp is not None:
        try:
            back = roundtrip(inp, shared.TicketInput)
            got_rws = getattr(back, "repo_worktrees", None)
            check("M3a 混合形态 TicketInput 编解码往返成功（启动面不再 TypeError）",
                  getattr(back, "workspace", None) == ws_mx and got_rws == (rws_mx or []),
                  "workspace=%r repo_worktrees=%r" % (getattr(back, "workspace", None), got_rws))
            check("M3a-1 workspace 回包无内嵌 repo_worktrees 键（纯形状契约）",
                  isinstance(back.workspace, dict) and "repo_worktrees" not in back.workspace,
                  "keys=%s" % sorted(back.workspace or {}))
        except Exception as e:  # noqa: BLE001
            check("M3a 混合形态 TicketInput 编解码往返成功（启动面不再 TypeError）", False,
                  "%s: %s" % (type(e).__name__, e))

    # M3b 第二跳：WorkspacePrep 同款往返（activity 入参面）
    try:
        prep = call_with_supported_fields(shared_workspace_prep_cls(),
                                          ticket_id=TICKET_MX, workspace=ws_mx,
                                          branch="lane/x", repo_worktrees=rws_mx or [])
    except CapabilityMissing:
        prep = None
        check("M3b WorkspacePrep 编解码往返：一等字段在场", False,
              "WorkspacePrep 不支持 repo_worktrees 字段（第二跳未同步）")
    if prep is not None:
        try:
            back = roundtrip(prep, shared_workspace_prep_cls())
            got_rws = getattr(back, "repo_worktrees", None)
            check("M3b WorkspacePrep 编解码往返全等（第二跳入参面）",
                  got_rws == (rws_mx or []) and getattr(back, "workspace", None) == ws_mx,
                  "repo_worktrees=%r" % (got_rws,))
        except Exception as e:  # noqa: BLE001
            check("M3b WorkspacePrep 编解码往返全等（第二跳入参面）", False,
                  "%s: %s" % (type(e).__name__, e))

    # M3c 畸形分层之「编解码层」：类型毁形在 from_payloads 拒（启动面拒绝），不冒充闸层
    try:
        bad = ticket_input(ticket_id=TICKET_MX, workspace=ws_mx, repo_worktrees=["not-a-dict"])
    except CapabilityMissing:
        bad = None
        check("M3c 编解码层畸形拒收：一等字段在场", False, "字段缺失无法构造毁形样本")
    if bad is not None:
        try:
            roundtrip(bad, shared.TicketInput)
            check("M3c 编解码层畸形拒收：repo_worktrees 条目非对象 → from_payloads 抛",
                  False, "往返成功未拒（类型注解护栏失效）")
        except Exception as e:  # noqa: BLE001
            check("M3c 编解码层畸形拒收：repo_worktrees 条目非对象 → from_payloads 抛",
                  isinstance(e, (TypeError, ValueError)),
                  "%s: %s" % (type(e).__name__, e))

    # M3d 单仓对照编解码（零回归）：repo_worktrees 恒 []，往返绿
    try:
        inp_sg = ticket_input(ticket_id=TICKET_SG, workspace=ws_sg, repo_worktrees=[])
    except CapabilityMissing:
        inp_sg = None
        check("M3d 单仓对照编解码往返：一等字段在场", False, "字段缺失")
    if inp_sg is not None:
        try:
            back = roundtrip(inp_sg, shared.TicketInput)
            check("M3d 单仓对照编解码往返：repo_worktrees 恒 []、workspace 纯形状",
                  getattr(back, "repo_worktrees", "missing") == []
                  and getattr(back, "workspace", None) == ws_sg,
                  "repo_worktrees=%r workspace=%r"
                  % (getattr(back, "repo_worktrees", "missing"), getattr(back, "workspace", None)))
        except Exception as e:  # noqa: BLE001
            check("M3d 单仓对照编解码往返：repo_worktrees 恒 []、workspace 纯形状", False,
                  "%s: %s" % (type(e).__name__, e))

    # ---------- M4 行为通道子用例（直调 prepare_workspace 公开 activity 入口） ----------
    import asyncio
    import agent_activities  # noqa: E402

    lane_rel, _b = shared.default_lane_paths(TICKET_MX)
    container = root_mx / ".lane" / lane_rel.split("/", 1)[1]

    # M4a 一等字段通道端到端：prep.repo_worktrees 到达 prepare → 逐仓挂树+清单落盘
    try:
        prep_m4 = call_with_supported_fields(shared_workspace_prep_cls(),
                                             ticket_id=TICKET_MX, workspace=dict(ws_mx),
                                             branch="lane/x", repo_worktrees=rws_mx or [])
        res = asyncio.run(agent_activities.prepare_workspace(prep_m4))
        check("M4a 一等字段通道：prepare 回执 ok/created（新字段真到达 activity）",
              bool(res.ok) and str(res.action).startswith("created"),
              "ok=%r action=%r error=%r" % (res.ok, res.action, res.error))
        tree_a = container / "repo_a"
        check("M4a-1 逐仓树在位：repo_a 树=repo_a 已注册 worktree",
              lane_worktree_registered(repos_mx["repo_a"], tree_a),
              "tree=%s" % tree_a)
        mf = read_manifest(container)
        check("M4a-2 清单落盘非空（repo_worktrees 公开契约镜像面）",
              isinstance(mf, list) and len(mf) >= 2,
              "manifest=%r" % (mf,))
    except CapabilityMissing as e:
        check("M4a 一等字段通道：prepare 回执 ok/created（新字段真到达 activity）", False,
              "WorkspacePrep 不支持 repo_worktrees 字段: %s" % e)
    except Exception as e:  # noqa: BLE001
        check("M4a 一等字段通道：prepare 回执 ok/created（新字段真到达 activity）", False,
              "%s: %s" % (type(e).__name__, e))

    # M4b 旧形状回落通道兼容（修复不得破坏直调兼容面）
    try:
        prep_old = call_with_supported_fields(shared_workspace_prep_cls(),
                                              ticket_id=TICKET_MX + "b",
                                              workspace=dict(ws_mx, repo_worktrees=rws_mx or []),
                                              branch="lane/y")
        res_old = asyncio.run(agent_activities.prepare_workspace(prep_old))
        check("M4b 旧形状回落通道：ws 内嵌明细直调 → 仍 ok（兼容面不弱化）",
              bool(res_old), "ok=%r error=%r" % (res_old.ok, res_old.error))
    except CapabilityMissing as e:
        check("M4b 旧形状回落通道：ws 内嵌明细直调 → 仍 ok（兼容面不弱化）", False,
              "构造失败: %s" % e)
    except Exception as e:  # noqa: BLE001
        check("M4b 旧形状回落通道：ws 内嵌明细直调 → 仍 ok（兼容面不弱化）", False,
              "%s: %s" % (type(e).__name__, e))

cleanup(root_mx, root_sg)
sys.exit(summary())
