#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-18 场景③：ui_evidence 声明制（门③，KI-050，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同）：
- UI 截图证据的目录由**项目声明**定（verify.yaml 顶层 ui_evidence），引擎只留机制
  （diff×声明目录判定+截图执行）；UI_WRITE_PREFIXES 五路径硬编码退役为数据；
- 声明落 verify.yaml 不撞「未知顶层键」fail-closed 雷（t260903-11 实锤同雷位）：
  verify_lane 白名单收 ui_evidence；dirs 畸形（非 dict / dirs 非字符串列表）=红且
  点名字段（契约②三态总纲：畸形≠缺省，不静默当缺省）；
- merge_check 截图证据项四分支（无声明项目过合并闸=行为可见非静默，验收③）：
  ①声明在场+diff 命中=现状红绿判定（闸没松，无 png 仍红）；
  ②声明在场+diff 未命中=不出项（拓扑级缺席）；
  ③声明缺省+diff 健康=出项 green+可见 note「ui_evidence 未声明」（缺席可见非静默，不是假绿）；
  ④diff 故障=红 fail-closed——机制故障不因缺省豁免（对照子用例：缺省不松闸）；
- load_ui_evidence 三态（缺失/畸形/ok）；
- sandbar 自身五路径迁入仓根 verify.yaml（数据迁移=行为等价 rod：声明集合≡旧
  UI_WRITE_PREFIXES 五路径）；
- review_gate 活路径接线（UI_EVIDENCE_DECL_PATCH_ID patched 门 + meta 预载
  ui_evidence_dirs，activity 读盘 workflow 只读 meta=重放安全）源码锁。

与相邻场景 intent 分界：t260904-13 三场景守判定源/闸输出/patched 接线编排
（KI-044 面），本条守**声明制新契约面**（KI-050）；本条 3.6 四分支子用例经真 merge_check
驱动（真 git 夹具仓，复用 lib_ki044 共享夹具+桩 admin 隔离 verify_lane 语义面）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（merge_check 行为子用例），verify_lane/声明/源码锁子用例照跑。
"""
import json
import shutil
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260904_18 import (  # noqa: E402
    REPO, POC, TOOLS, check, summary, env_fail, temporalio_available,
    merge_fixture_repo, FIXTURE_STUB_ADMIN, ui_evidence_yaml,
)

sys.path.insert(0, str(POC))
sys.path.insert(0, str(TOOLS))
import shared       # noqa: E402  纯标准库
import verify_lane  # noqa: E402  纯标准库

DL_SRC = (POC / "dev_lane.py").read_text(encoding="utf-8")
VL_SRC = (TOOLS / "verify_lane.py").read_text(encoding="utf-8")
VY_SRC = (REPO / "verify.yaml").read_text(encoding="utf-8")

# ---------- 源码契约锁 / 数据迁移 rod（处处可跑） ----------
check("R1 review_gate 接线 patched 门（UI_EVIDENCE_DECL_PATCH_ID 在场）",
      "UI_EVIDENCE_DECL_PATCH_ID" in DL_SRC)
check("R2 声明 dirs 经 meta 预载（ui_evidence_dirs，activity 读盘 workflow 只读）",
      "ui_evidence_dirs" in DL_SRC)
check("R3 verify_lane 顶层白名单收 ui_evidence（未知顶层键雷不触发）",
      "'ui_evidence'" in VL_SRC)
check("R4 sandbar 声明迁移在案（仓根 verify.yaml 顶层 ui_evidence）",
      "ui_evidence:" in VY_SRC)
legacy = list(getattr(shared, "UI_WRITE_PREFIXES", ()) or ())
check("R5 迁移等价 rod：legacy 五路径全部落入仓根 verify.yaml（声明≡旧表）",
      bool(legacy) and all(p in VY_SRC for p in legacy),
      "legacy=%r" % (legacy,))


def run_code_lane(tmpdir):
    with no_narrowing_env():              # 260930：进程内调闸剥继承旋钮
        return verify_lane.run({"lane": "code", "path": str(tmpdir)})


# ---------- verify_lane 白名单/形态子用例（stdlib 处处可跑；真解析器） ----------
d1 = Path(tempfile.mkdtemp(prefix="t260904-18-vy-ok-"))
try:
    (d1 / "verify.yaml").write_text(ui_evidence_yaml(["web/ui/"]), encoding="utf-8")
    res = run_code_lane(d1)
    blob = json.dumps(res, ensure_ascii=False)
    check("W1 合法 ui_evidence → code 道不因新顶层键 fail-closed（绿）",
          res.get("green") is True and "未知顶层键" not in blob, blob[:220])
finally:
    shutil.rmtree(d1, ignore_errors=True)

d2 = Path(tempfile.mkdtemp(prefix="t260904-18-vy-bad-"))
try:
    (d2 / "verify.yaml").write_text(ui_evidence_yaml("web/ui"), encoding="utf-8")
    res = run_code_lane(d2)
    blob = json.dumps(res, ensure_ascii=False)
    check("W2 dirs 畸形（字符串）→ fail-closed 红且点名字段（畸形≠缺省）",
          res.get("green") is False and "dirs" in blob, blob[:220])
finally:
    shutil.rmtree(d2, ignore_errors=True)

d3 = Path(tempfile.mkdtemp(prefix="t260904-18-vy-ctrl-"))
try:
    (d3 / "verify.yaml").write_text(ui_evidence_yaml(None), encoding="utf-8")
    res = run_code_lane(d3)
    check("W3 对照：无 ui_evidence 的声明 → 现状不回归（绿）", res.get("green") is True)
finally:
    shutil.rmtree(d3, ignore_errors=True)

# ---------- load_ui_evidence 三态（stdlib；声明读取器单点） ----------
lue = getattr(shared, "load_ui_evidence", None)
check("U0 被测承诺面在场（shared.load_ui_evidence）", lue is not None)
if lue is not None:
    d = Path(tempfile.mkdtemp(prefix="t260904-18-lue-"))
    try:
        (d / "verify.yaml").write_text(ui_evidence_yaml(None), encoding="utf-8")
        r_absent = lue(d)                      # 无 ui_evidence 键 → 缺省态
        (d / "verify.yaml").write_text(ui_evidence_yaml("web/ui"), encoding="utf-8")
        r_bad = lue(d)                         # dirs 标量 → 畸形态
        (d / "verify.yaml").write_text(ui_evidence_yaml(["web/ui/"]), encoding="utf-8")
        r_ok = lue(d)                          # 合法 → ok+dirs
        def tri(r):
            return tuple(r) if isinstance(r, tuple) else (r,)
        check("U1 缺失态 → absent（声明关闭口径，非异常）",
              tri(r_absent)[0] == "absent", repr(r_absent)[:160])
        check("U2 畸形态（dirs 标量）→ malformed（畸形≠缺省，不静默降档）",
              tri(r_bad)[0] == "malformed", repr(r_bad)[:160])
        check("U3 合法态 → ok 且 dirs 如实解析",
              tri(r_ok)[0] == "ok" and tri(r_ok)[1] == ["web/ui/"], repr(r_ok)[:160])
    finally:
        shutil.rmtree(d, ignore_errors=True)

# ---------- merge_check 3.6 四分支行为子用例（temporalio 面；真 merge_check + 真 git 夹具） ----------
if not temporalio_available():
    env_fail("temporalio 不可用（本泳道无 venv）：merge_check 3.6 四分支行为子用例不可执行——"
             "verify_lane/声明/源码锁子用例已在本场跑完；arbitrate/merge 期 venv 环境必须全绿")
else:
    import asyncio  # noqa: E402
    import agent_activities  # noqa: E402
    from agent_activities import MergeCheckArgs  # noqa: E402

    def ui_items(checks):
        return [c for c in checks if str(c.get("item", "")).startswith("UI 截图证据")]

    def run_merge(lane_files, branch="lane"):
        tmp, mb = merge_fixture_repo(lane_files)
        try:
            res = asyncio.run(agent_activities.merge_check(MergeCheckArgs(
                ticket_id="t26090418scui", worktree=str(tmp), branch=branch,
                base_ref=mb, write_set=["web/ui/"])))
            return ui_items(res.checks)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ①声明在场+diff 命中：现状红绿判定（无 png → 红，闸没松）
    items = run_merge({
        "web/ui/a.ts": "export {}\n",
        "verify.yaml": ui_evidence_yaml(["web/ui/"]),
    })
    check("M1 声明在场+diff 命中 → 闸红（无 png），detail 留命中路径",
          len(items) == 1 and items[0].get("green") is False
          and "web/ui/a.ts" in str(items[0].get("detail", "")),
          "items=%r" % (items,))

    # ③声明缺省+diff 健康：green + 可见 note（行为可见非静默，缺席不是假绿）
    items = run_merge({
        "web/ui/a.ts": "export {}\n",
        "verify.yaml": ui_evidence_yaml(None),
    })
    check("M2 声明缺省+diff 健康 → 截图项 green+可见 note（未声明）",
          len(items) == 1 and items[0].get("green") is True
          and "not declared" in str(items[0].get("detail", "")),
          "items=%r" % (items,))

    # 声明畸形：红且点名（畸形≠缺省）
    items = run_merge({
        "web/ui/a.ts": "export {}\n",
        "verify.yaml": ui_evidence_yaml("web/ui"),
    })
    check("M3 声明畸形 → 截图项红且点名 ui_evidence",
          len(items) == 1 and items[0].get("green") is False
          and "ui_evidence" in str(items[0].get("detail", "")),
          "items=%r" % (items,))

    # ④diff 故障（机制故障）：缺省不豁免，仍红 fail-closed（对照子用例：闸没松）
    items = run_merge({
        "web/ui/a.ts": "export {}\n",
        "verify.yaml": ui_evidence_yaml(None),
    }, branch="ghost-branch")
    check("M4 diff 故障（坏分支）→ 红不静默（缺省不豁免机制故障）",
          len(items) == 1 and items[0].get("green") is False, "items=%r" % (items,))

    # ②声明在场+diff 未命中：不出项（拓扑级缺席，不误伤纯引擎票）
    items = run_merge({
        "server/engine.py": "# engine only\n",
        "verify.yaml": ui_evidence_yaml(["web/ui/"]),
    })
    check("M5 声明在场+diff 未命中 → 不出项（不误伤）", len(items) == 0, "items=%r" % (items,))

sys.exit(summary())
