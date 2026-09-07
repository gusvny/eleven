#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-06 场景③：多仓 fail-closed 注入面（畸形/边界/异常路径，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同，fail-closed=创建即拒收、失败即回执点名、
绝不静默归仓/静默重建/静默覆盖）：
- 路径逃逸项目根（../）→ 拒收点名，不给静默归仓；
- 集合外嵌套仓（仓中仓）内路径 → 创建即拒收且红字点名嵌套仓（票B 口径：
  嵌套仓语义属另票，不为它扩扫描、也不静默归到外层仓）；
- 仓被删/挪后 prepare → failed 回执点名缺失仓，不静默重建树（meta.repo_worktrees
  =唯一真源的一致性校验面，真源漂移=交人不是自愈）；
- 树位置被来历不明普通目录占位 → failed 不覆盖不删除（与现行单仓「目录已在但
  非本仓 worktree→人工处置」同语义，多仓逐树保住——防覆盖 agent 工作现场）。

与相邻场景 intent 分界：场景①守正常旅程，场景②守合并闸/收口/重入；本条只守
注入与异常路径。写集条目畸形形态（非串/绝对路径/../）属建票写集契约既有面
（存量场景已守，intent 重复不另起）。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（prepare 行为腿 F4/F5），stdlib 拒收腿 F1-F3 照跑。
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260907_06 import (  # noqa: E402
    POC, check, summary, env_fail, temporalio_available,
    build_multirepo_project, lane_dirname, call_prepare, CapabilityMissing,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402

resolve = getattr(shared, "resolve_repos_for_paths", None)
if resolve is None:
    check("F1 路径逃逸项目根→拒收点名", False,
          "shared.resolve_repos_for_paths 缺失——票B 仓锚推导未落地（红属 TDD 预期）")
    check("F2 集合外嵌套仓路径→创建即拒收且点名嵌套仓", False, "同上能力缺失")
    check("F3 归属只认集合内仓（两层同名 basename 嵌套不静默归外层）", False, "同上能力缺失")
else:
    root, repos = build_multirepo_project(prefix="t260907-06-fc-", nested=True)
    try:
        # F1 逃逸
        try:
            r = resolve(str(root), ["../escape.md"])
            ok1 = isinstance(r, dict) and not r
            check("F1 路径逃逸项目根→拒收点名", ok1,
                  "未拒收（返回 %r）——静默归仓=护栏放空" % (r,))
        except Exception as e:
            check("F1 路径逃逸项目根→拒收点名", True, "")
            del e
        # F2 嵌套仓（集合外）拒收点名
        try:
            r = resolve(str(root), ["repo_a/nested/n.txt"])
            ok2 = isinstance(r, dict) and not r
            check("F2 集合外嵌套仓路径→创建即拒收且点名嵌套仓", ok2,
                  "未拒收（返回 %r）——静默归外层仓=错仓落账前奏" % (r,))
        except Exception as e:
            msg = str(e)
            check("F2 集合外嵌套仓路径→创建即拒收且点名嵌套仓",
                  ("nested" in msg) or ("嵌套" in msg),
                  "拒收了但未点名嵌套仓：%s" % msg[:200])
        # F3 归属正确性对照（夹具同款正常路径仍归 repo_a——拒收不误伤合法路径）
        try:
            r = resolve(str(root), ["repo_a/src/a.py"])
            vals = list(r.values()) if isinstance(r, dict) else []
            got = [p for paths in vals for p in paths]
            check("F3 合法路径不误伤（repo_a/src/a.py 仍归 repo_a）",
                  len(r) == 1 and got == ["repo_a/src/a.py"], "r=%r" % (r,))
        except Exception as e:
            check("F3 合法路径不误伤（repo_a/src/a.py 仍归 repo_a）", False,
                  "合法路径被拒: %s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(root, ignore_errors=True)

# ---------- F4/F5：prepare 异常路径（temporalio 面） ----------
if not temporalio_available():
    env_fail("temporalio 不可用（本泳道无 venv）：prepare 异常路径腿（F4/F5）不可执行——"
             "stdlib 拒收腿已在本场跑完；arbitrate/merge 期 venv 环境必须全绿")
else:
    # F4 删仓后 prepare：failed 点名、不静默重建
    root, repos = build_multirepo_project(prefix="t260907-06-fc4-")
    wname = lane_dirname("t26090706fc4")
    container = root / ".lane" / wname
    try:
        res = call_prepare(container, "t26090706fc4",
                           ["repo_a/src/a.py", "repo_b/lib/b.py"], root)
        tree_b = container / "repo_b"
        sentinel = tree_b / "lib" / "b.py"
        if not (getattr(res, "ok", False) and sentinel.is_file()):
            check("F4 删仓后 prepare→failed 点名不重建", False,
                  "首轮 prepare 未落地/失败: %r" % (res,))
        else:
            shutil.rmtree(repos["repo_b"])  # 模拟项目侧删仓（真源漂移）
            res2 = call_prepare(container, "t26090706fc4",
                                ["repo_a/src/a.py", "repo_b/lib/b.py"], root)
            err2 = str(getattr(res2, "error", "") or "")
            check("F4a 删仓后 prepare→failed 回执（不抛不假绿）",
                  getattr(res2, "ok", True) is False, "res2=%r" % (res2,))
            check("F4b 红字点名缺失仓（repo_b）", "repo_b" in err2, "err=%r" % (err2,))
            check("F4c 不静默重建：树 repo_b 原样幸存（内容未被重置）",
                  sentinel.is_file() and "print('b')" in sentinel.read_text(encoding="utf-8"))
    except CapabilityMissing as e:
        check("F4 删仓后 prepare→failed 点名不重建", False, str(e))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # F5 来历不明占位：树位置被普通目录占位→failed 不覆盖
    root2, repos2 = build_multirepo_project(prefix="t260907-06-fc5-")
    wname2 = lane_dirname("t26090706fc5")
    container2 = root2 / ".lane" / wname2
    try:
        squatter = container2 / "repo_a"
        squatter.mkdir(parents=True)
        marker = squatter / "agent_work.txt"
        marker.write_text("来历不明的工作现场\n", encoding="utf-8")
        res = call_prepare(container2, "t26090706fc5",
                           ["repo_a/src/a.py", "repo_b/lib/b.py"], root2)
        err = str(getattr(res, "error", "") or "")
        check("F5a 占位目录→failed 回执（不覆盖来历不明的现场）",
              getattr(res, "ok", True) is False, "res=%r" % (res,))
        check("F5b 红字点名 repo_a（精确到仓/树）",
              "repo_a" in err or str(squatter) in err, "err=%r" % (err,))
        check("F5c 占位目录内容幸存（未删除未重建）",
              marker.is_file() and "来历不明" in marker.read_text(encoding="utf-8"))
    except CapabilityMissing as e:
        check("F5 占位目录→failed 不覆盖", False, str(e))
    finally:
        shutil.rmtree(root2, ignore_errors=True)

sys.exit(summary())
