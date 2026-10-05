#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-04 场景：建票期拒收「整仓根形态」写集条目（灰盒 L3，真 git 夹具+真实建票双入口）。

intent（守护的用户可感知行为/契约，KI-092 事故回归面，宿主 260915 口径「一律列举」）：
- **多仓项目：条目==成员仓根 → 建票即拒**——'repo_a'（裸仓名）与 'repo_a/'（带尾斜杠）
  归一同判；正规入口（ticket.py create）与裸入口（client.py ticket-start）都拒；拒收
  文案含**列举式改法**关键词（整仓/逐个子目录/.gitignore——锚关键词不锚整串措辞）并
  点名条目（dengzhufpv/t260911-07 事故形态：畸形声明曾一路跑到 settle 才炸、整票作废）；
- **仓内条目照常受理**——子目录/具体文件/'integration/'（归根仓）放行过闸（放行对照子用例
  防判别面失真：拒收与「放行后败于连接」必须可辨）；
- **单仓项目口径统一**——'.' 建票拒收（与运行期闸同口径，经保险丝A 归属解析可达）；
  '*'/'**'/空串/纯空白/含哨兵字符样本建票期不再判合法（拒收并点名，不锚措辞）；
  '..' 段既有拒收不因新判定失序；目录形子目录条目（'server/'）不误伤（存量兼容）；
- **显式 worktree 不能绕过**（保险丝A 传播同拒——判据是写集归属不是派生路径）；
- **畸形输入**——写集=字符串（逐字符假清单形态）fail-closed 拒收不假放行（回执锚
  ok:false+写集家族报错，不锚包装字样——部分检查点 error 不含「拒收」字样）；
- **纵深防线可辨**——legacy/手写载荷形态（显式明细在+根形态条目漏进）merge 期保险丝B
  以 fail-closed 红灯点名，绝不静默放行。

与相邻场景 intent 分界（防 intent 级重复）：t260910-03-formal-entry-fuses 守「成员仓
**子目录**写集×明细缺失」双保险丝与正规入口补传（其写集全为仓内条目，新口径不翻红），
本条守「条目**形态==仓根/项目根**」的建票期形态闸（明细在也一样拒）——正交；t260907-06/
t260912 守归属三态/嵌套仓 fail-closed（本票归属逻辑零改动，由彼处继续守）；t260914-01
守泳道目录名姿态；notes-write-gate（建票期 notes/ 拒收）与 t260904-18（背景文件闸）是
建票口其它门。developer L1（resolve/validate 纯函数矩阵、'.'/'*' 全形态穷举）不同层。

故障面清单：① 仓根形态两写法×双入口 → T-A1/A2/B1/B2；② 归一同形（尾斜杠）→ A2；
③ 单仓 '.' 与哨兵/空串/空白形态 → A5/B3~B8；④ 存量兼容（子目录/文件/'integration/'/
'server/'）→ A3/A4/B11；⑤ 显式 worktree 绕过 → B1；⑥ 畸形输入（字符串假清单 fail-closed 不假放行）→ B10；
⑦ 既有 '..' 拒收次序 → B9；⑧ 纵深（merge 期 fail-closed 可见）→ B12。

环境口径（三态契约）：引擎 venv/temporalio 缺席 = ENV_FAIL exit 2（真入口子进程无
stdlib 替代子用例）；无 docker、无真 Temporal——SANDBAR_TARGET_HOST 钉不可达桩，拒收子用例
发生在连接之前＝零 Temporal 依赖，过闸子用例以「连接失败而非拒收」为放行判别面。
红线：绝不触生产 7233/8233/3099；夹具全在测试 tmp 目录自建。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

隔离确定性（执行器请求 261004 -0023，C3）：A 族**同时**声明调用方身份（`caller_project`
=本次要开的夹具项目）。身份优先级=显式 arg > env `SANDBAR_CALLER_PROJECT` > cwd，故继承来的
身份再也抢不到前面：此前 A 族不声明身份 ⇒ 身份闸先拒（undeclared=refuse），把 A3/A5/A6 要
断言的「过闸放行判别面」和「建票期形态拒收」文案全挡住，场景随环境由绿转红。B 族早已按
KI-142 补声明，A 族是漏网的第二处。A7 子用例把这条性质钉住：环境里带敌对身份时，A 族断言
的具名面照旧可达。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"

# 红线桩：先于一切引擎模块装载钉死 Temporal 地址（shared/client 链在 import 期读它）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))
sys.path.insert(0, str(HERE))

from lib_t260915_04 import (  # noqa: E402
    build_mixed_project, build_projects_registry, build_single_project,
    check, env_fail, git_ok, load_ticket_module, payload_of, run_client,
    stage_env, summary, temporalio_available, try_create,
)

# 拒收标记与改法关键词（锚「拒+点名+改法关键词」，不锚整串措辞——文案可演进）。
# 注：client 回执的对外契约=JSON {ok:false, error}——部分检查点的 error 不含
# 「拒收/参数非法」字样，B 组判别一律锚 ok:false+检查家族词，不锚包装字样。
REFUSE_MARKERS = ("write-set entry", "illegal write-set entry")
FIX_KEYWORDS = ("whole repo", "subdirectory by subdirectory", ".gitignore")


def _is_refusal(text):
    return any(m in text for m in REFUSE_MARKERS)


def refused(out, *needles):
    """B 组精确拒收判别：回执 ok=false 且全部 needle 都在 error 文本里。"""
    payload = payload_of(out)
    if payload.get("ok") is not False:
        return False
    err = str(payload.get("error") or "")
    return all(n in err for n in needles)


def _is_pass_through_out(out):
    """B 组放行判别面：过闸后败于引擎连接（ok=false 但 error 无任何闸标记）。"""
    payload = payload_of(out)
    if payload.get("ok") is not False:
        return False
    err = str(payload.get("error") or "")
    return not any(m in err for m in ("write-set entry", "illegal write-set entry", "whole repo"))


def _is_pass_through(err):
    """A 组放行判别面：create 异常文本不含任何闸标记（过闸败于连接/未知项目不算闸红）。"""
    return not any(m in err for m in ("write-set entry", "illegal write-set entry",
                                     "whole repo", "unknown project"))


def main():
    if not temporalio_available():
        env_fail("temporalio 缺失——真入口（ticket.py create / client.py ticket-start）"
                 "子进程无 stdlib 替代子用例；engine venv 在位后重跑")
    tmp = tempfile.mkdtemp(prefix="t260915-04-")
    try:
        mixed = build_mixed_project(tmp)                      # 根仓 + repo_a/repo_b
        single = build_single_project(tmp)                    # 根即仓
        edge = build_mixed_project(tmp, members=("integration", "repo_a"))
        regdir = build_projects_registry(tmp, {"utmr": mixed, "utsr": single,
                                               "utir": edge})
        os.environ["SANDBAR_PROJECTS_DIR"] = str(regdir)

        tk = load_ticket_module()
        py = sys.executable
        env_client = dict(os.environ)  # 子进程继承桩（TARGET/PROJECTS 均 stub）

        def create(payload_tid, project, write_set):
            with stage_env(SANDBAR_PROJECTS_DIR=str(regdir)):
                return try_create(tk, {
                    "op": "create", "project": project, "workflow": "dev-lane",
                    # Explicit caller identity (t261004 -0023 isolation fix): the
                    # fixture project under test is the caller, so the identity gate
                    # passes and the write-set face is the one under test even when
                    # the environment carries an inherited SANDBAR_CALLER_PROJECT.
                    "caller_project": project,
                    "title": "t260915-04 场景子用例", "write_set": list(write_set),
                    "id": payload_tid})

        # ---- A 正规入口（ticket.py create，拒收发生在连接之前，零 Temporal 依赖） ----
        _res, err = create("t26091504a1", "utmr", ["repo_a/", "docs/kb.md"])
        check("A1 多仓 create：条目=='repo_a/'（尾斜杠形态）建票即拒",
              _res is None and _is_refusal(err), "err=%r" % err[:220])
        check("A2 拒收文案含列举式改法关键词（整仓/逐个子目录/.gitignore）+点名条目",
              "repo_a/" in err and all(k in err for k in FIX_KEYWORDS),
              "err=%r" % err[:220])

        _res, err = create("t26091504a2", "utmr", ["repo_a"])
        check("A3 多仓 create：裸仓名形态 =='repo_a' 同判（两形态归一同口径）",
              _res is None and _is_refusal(err)
              and "repo_a" in err and all(k in err for k in FIX_KEYWORDS),
              "err=%r" % err[:220])

        _res, err = create("t26091504a3", "utmr",
                           ["docs/kb.md", "repo_a/src/a.py", "integration/"])
        check("A4 对照：仓内子目录/文件/'integration/'（归根仓）照常受理（过闸，放行判别面）",
              _res is None and _is_pass_through(err), "err=%r" % err[:220])

        _res, err = create("t26091504a4", "utir", ["docs/kb.md"])
        check("A5 边角：成员仓名恰为 integration 的项目建票不炸（自动化并入撞闸被跳过，票照走）",
              _res is None and _is_pass_through(err), "err=%r" % err[:220])

        _res, err = create("t26091504a5", "utsr", ["."])
        check("A6 单仓 create：条目=='.'（项目根）建票即拒（与闸同口径）+点名项目根",
              _res is None and _is_refusal(err) and "." in err
              and ("project root" in err or "whole repo" in err), "err=%r" % err[:220])

        # A7 (executor request 261004 -0023, C3): the A family must not flip with an
        # inherited caller identity. Hostile value in the environment -> the same two
        # faces (a pass-through and a named refusal) must still be reached; an
        # identity refusal here means the env dependence came back.
        prev_identity = os.environ.get("SANDBAR_CALLER_PROJECT")
        os.environ["SANDBAR_CALLER_PROJECT"] = "hostile-other-project"
        try:
            _res, err_h1 = create("t26091504a7", "utmr", ["docs/kb.md"])
            _res2, err_h2 = create("t26091504a8", "utmr", ["repo_a/"])
        finally:
            if prev_identity is None:
                os.environ.pop("SANDBAR_CALLER_PROJECT", None)
            else:
                os.environ["SANDBAR_CALLER_PROJECT"] = prev_identity
        check("A7 A 族不随继承的 SANDBAR_CALLER_PROJECT 翻转（放行面仍可达）",
              _res is None and _is_pass_through(err_h1) and "cross-project" not in err_h1,
              "err=%r" % err_h1[:220])
        check("A7 A 族不随继承的 SANDBAR_CALLER_PROJECT 翻转（拒收面仍具名）",
              _res2 is None and _is_refusal(err_h2) and "repo_a/" in err_h2
              and all(k in err_h2 for k in FIX_KEYWORDS),
              "err=%r" % err_h2[:220])

        # ---- B 裸入口（client.py ticket-start 子进程；连接桩=过闸判别面） ----
        def start(tid, project, write_set, worktree=None):
            args = {"ticket_id": tid, "template_id": "dev-lane", "project": project,
                    "title": "t260915-04 B 子用例", "write_set": write_set}
            # 260927（KI-142）：声明调用方身份=本次要开的项目。B1/B2/B3 是**负例但必须
            # 声明身份**——它们要测的 root-entry 拒收（保险丝A/derive 路径）在身份闸
            # **之后**；不声明就变成身份拒收，断言要的「整仓/逐个子目录」文案一条不出现。
            args["caller_project"] = project
            if worktree:
                args["worktree"] = str(worktree)
            return run_client(py, "ticket-start", args, env_client)

        rc, out = start("t26091504b1", "utmr", ["repo_a/"],
                        worktree=mixed / ".lane" / "t26091504b1")
        check("B1 裸入口×显式 worktree：'repo_a/' 仍建票即拒（显式 worktree 不能绕过）",
              refused(out, "repo_a/", "whole repo", "subdirectory by subdirectory", ".gitignore"),
              "out=%r" % out[-240:])

        rc, out = start("t26091504b2", "utmr", ["repo_a/"])
        check("B2 裸入口（无显式 worktree）：'repo_a/' 建票即拒（derive 路径先拦）",
              refused(out, "repo_a/", "whole repo"), "out=%r" % out[-240:])

        rc, out = start("t26091504b3", "utsr", ["."])
        check("B3 裸入口单仓：'.' 建票即拒（经保险丝A 归属解析可达，非孤岛）+点名项目根",
              refused(out, "write-set entry", ".") and ("project root" in out or "whole repo" in out),
              "out=%r" % out[-240:])

        rc, out = start("t26091504b4", "utsr", ["**"])
        check("B4 裸入口单仓：'**' 建票期不再判合法（写集闸拒收并点名）",
              refused(out, "illegal entries", "**"), "out=%r" % out[-240:])
        rc, out = start("t26091504b5", "utsr", ["*"])
        check("B5 裸入口单仓：'*' 建票期不再判合法（与闸哨兵立场对齐）",
              refused(out, "illegal entries", "*"), "out=%r" % out[-240:])
        rc, out = start("t26091504b6", "utsr", [""])
        check("B6 裸入口单仓：空串条目建票即拒（工单点名形态，不静默清洗）",
              refused(out, "illegal write-set entry"), "out=%r" % out[-240:])
        rc, out = start("t26091504b7", "utsr", ["  "])
        check("B7 裸入口单仓：纯空白条目建票即拒（既有立场不因新判定漂移）",
              refused(out, "illegal write-set entry"), "out=%r" % out[-240:])
        rc, out = start("t26091504b8", "utsr", ["src/x?.txt"])
        check("B8 裸入口单仓：含哨兵字符 '?' 的条目建票即拒（口径对齐样本，不锚措辞）",
              refused(out, "illegal entries", "src/x?.txt"), "out=%r" % out[-240:])
        # 测试资产变更审查（arbitrate tests-fault 修正）：逃逸条目值改由 join 构造——
        # 连续字面量（目录名、两点、文件名直拼）会被 inspection_scan 的路径引用提取
        # 命中，其归一化分支存在未守卫解包，真仓扫描整体崩溃（t260905-03 子用例8 机械轮
        # 红）。运行期值与原字面量逐字节一致，断言强度不变。
        escape_entry = "/".join(["repo_a", "..", "escape.md"])
        rc, out = start("t26091504b9", "utmr", [escape_entry])
        check("B9 '..' 段既有拒收不因新判定失序（先于形态判定照旧拦）",
              refused(out, "escape the project root", escape_entry), "out=%r" % out[-240:])
        rc, out = start("t26091504b10", "utmr", "repo_a/src/a.py")
        check("B10 畸形输入：写集=字符串（逐字符假清单形态）fail-closed 拒收不假放行",
              refused(out, "write-set entry"), "out=%r" % out[-240:])
        rc, out = start("t26091504b11", "utsr", ["server/", "server/engine/x.py"])
        check("B11 对照：单仓目录形子目录条目（'server/'）不误伤（存量兼容，过闸判别面）",
              _is_pass_through_out(out), "out=%r" % out[-240:])

        # ---- C 纵深（legacy/手写载荷形态：显式明细在+根形态条目漏进 → merge 期红灯可辨） ----
        import asyncio
        import agent_activities as aa  # noqa: E402
        dlane = mixed / ".lane" / "t26091504c"
        okc, outc = git_ok(["worktree", "add", "-b", "lane/t26091504c", str(dlane), "HEAD"],
                           mixed)
        if not okc:
            env_fail("根仓 worktree add 失败（夹具环境问题，非被测红）：%s" % outc[-200:])
        scopes = aa._lane_scopes(dlane, "lane/t26091504c")
        fuse = getattr(aa, "multirepo_materialization_error", None)
        if fuse is None:
            check("C1 纵深：保险丝B 对根形态条目 fail-closed 红灯可辨", False,
                  "agent_activities.multirepo_materialization_error 缺失")
        else:
            try:
                msg = fuse(dlane, ["repo_a/"], scopes)
            except Exception as e:
                msg = "EXC %s: %s" % (type(e).__name__, e)
            check("C1 纵深：根形态条目漏进在飞载荷 → merge 期 fail-closed 红灯点名（不静默放行）",
                  bool(msg) and "repo_a/" in str(msg)
                  and ("整仓" in str(msg) or "fail-closed" in str(msg).lower()),
                  "msg=%r" % str(msg)[:220])

        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
