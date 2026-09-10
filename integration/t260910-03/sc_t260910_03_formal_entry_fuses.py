#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-03 场景：正规入口多仓票全链 + 双保险丝（灰盒 L2/L3）。

intent（守护的用户可感知行为/合同，dengzhufpv 260910 缺陷回归面）：
- 正规入口创建链补传：ticket.py 同款 derive 调用（repo_write_set=写集）→ 多仓
  项目产出逐仓 repo_worktrees 明细（缺陷复现形态修复后必须双仓）；明细经
  ticket-start 二跳（dict workspace 转发）不丢（缺陷根因=此通道被堵死）；漏传=
  单仓明细缺失（旧病灶形状对照腿）；单仓项目零回归（不激活）；
- 保险丝A（开票拒收，fail-closed）：显式 worktree+成员仓写集 → ticket-start
  创建即拒收且红字**点名条目**（连接前拒收，零 Temporal 依赖；只锚「拒+点名」
  不锚措辞）；对照腿不误伤——纯根仓写集放行、多仓写集合法派生（明细在）放行
  （显式 worktree 不是绕过闸的通道，看写集归属不看派生路径）；
- 逐仓物化落成（L1 硬断言）：prepare_workspace → 双仓树均为所属仓已注册
  worktree（git worktree list 绝对路径可验）+ 清单落盘两仓条目；
- 保险丝B（合并红灯，绝不静默收口）：清单缺失（_lane_scopes 单仓回落形态=
  缺陷形态）× 成员仓写集 → merge_check 红灯、物化检查项红并点名缺失仓、
  **非冲突类**（conflict=False，不进自动消解回路，KI-047 同族防线）；merge
  同源保险丝 ok=False 不落账（成员仓 main 零新提交、泳道保留交人工）；
- 隔离台持久化契约（docker 台）：正规入口 ticket.py create 真建票与裸入口
  client.py ticket-start（无显式 worktree，勿回归红线）的 Temporal payload
  TicketInput.repo_worktrees 均含双仓（probe_wf_input 读 WorkflowExecutionStarted
  input=对外数据契约，不锚实现内部结构）；create 返回体为辅证。

与相邻场景 intent 分界：t260907-06 三场景守多仓泳道本体（归属/合并闸/fail-closed
注入面）、t260907-12 守混合形态归属、t260907-07 守 epic/project 锚定——本场景
只守「正规入口补传 + 双保险丝 + 裸入口不回归」缺陷回归面，不重复彼处 intent。

环境口径（三态契约）：stdlib 面（shared 纯函数/git 夹具）系统 python3 可跑；
temporalio 面（prepare/merge_check/merge 行为腿）缺失=ENV_FAIL exit 2 点名；
docker/隔离台库缺席=ENV_FAIL 点名（台面腿），stdlib+temporalio 腿照跑。
红线：一切被测子进程/模块的 Temporal 地址显式指隔离台或不可达桩（127.0.0.1:9），
绝不触生产 7233/8233，绝不在生产 Temporal 上真建票（真建票只发生在一次性隔离
台 namespace，跑完即拆——t260907-07 同款纪律）。
夹具红线：假多仓项目只在测试 tmp 目录自建（复制 t260907-06/lib 夹具风格并按本票
缺陷形态补混合形态=根亦 git 仓，不跨票 import 对方夹具，来源已注明），不碰真实
项目数据。隔离台/持久化探针复用 t260904-02 共享设施 lib_gate/probe_wf_input
（跨票共享基建复用先例=t260907-07，非对方票夹具）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"
INTEG = REPO / "integration"

# 红线：先于一切引擎模块 import 钉死 Temporal 地址桩（shared.py 模块级读 env），
# 进程内直调 merge/merge_check 的 _fetch_ticket_project 软降级也绝不触生产端口。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n))
    return 1 if failed else (2 if env_fail_n else 0)


def git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout


def git_ok(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _init_repo(path, rel_file):
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "ut@example.com", cwd=path)
    git("config", "user.name", "ut", cwd=path)
    f = path / rel_file
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("base\n", encoding="utf-8")
    git("add", "-A", cwd=path)
    git("commit", "-m", "base", cwd=path)


def build_multirepo_project(base):
    """父目录作根（无 .git）+ 两个真 git 子仓（t260907-06/lib 夹具同款形态）。"""
    root = Path(base) / "proj"
    root.mkdir(parents=True)
    _init_repo(root / "repo_a", "src/a.py")
    _init_repo(root / "repo_b", "lib/b.py")
    return root


def build_mixed_project(base):
    """混合形态（dengzhufpv 缺陷现场形态：根亦 git 仓 + 子仓并存）：
    根仓（.gitignore 忽略子仓=现场同款）+ repo_a/repo_b 两个子 git 仓。"""
    root = Path(base) / "mixed"
    root.mkdir(parents=True)
    _init_repo(root, "docs/root.md")
    (root / ".gitignore").write_text("repo_a/\nrepo_b/\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-m", "gitignore", cwd=root)
    _init_repo(root / "repo_a", "src/a.py")
    _init_repo(root / "repo_b", "lib/b.py")
    return root


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


def member_repos(entries):
    """repo_worktrees 明细里的成员仓相对路径集合（repo 非空=成员仓；空=根树）。"""
    return sorted({str(e.get("repo") or "") for e in (entries or [])
                   if isinstance(e, dict) and str(e.get("repo") or "")})


def call_with_supported_fields(cls, **kwargs):
    """容错调参工厂：只传该 dataclass 实际支持的字段（通道字段未落地时被过滤，
    行为腿自然红=TDD 信号，不因签名漂移假绿/崩溃）。"""
    import dataclasses
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in kwargs.items() if k in names})


def run_client(py, sub, args, env, timeout=180):
    """spawn <py> client.py <sub> <argsJSON>（node.ts cli 同款口径）。返回 (rc, out)。"""
    p = subprocess.run([py, str(POC / "client.py"), sub, json.dumps(args)],
                       env=env, cwd=str(REPO), capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_out_json(out):
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}


sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面（TARGET_HOST 已被上方 env 桩钉死）

TICKET = "t26091003fe"
WS = ["repo_a/src/a.py", "repo_b/lib/b.py"]     # 成员仓写集（缺陷同款；integration/ 由 dev-lane 自动并入）
WSFULL = WS + ["integration/"]                  # create 链实际形态
tmp = tempfile.mkdtemp(prefix="t260910-03-fe-")
try:
    # ---------- stdlib 面：正规入口创建链形状（补传后） ----------
    root = build_multirepo_project(tmp)
    # G1 修复形态：ticket.py _create 同款 derive 调用（repo_write_set=write_set）
    lane, ws, worktree, branch = shared.derive_lane_workspace(
        TICKET, "worktree", project_root=str(root), repo_write_set=list(WS))
    rws = (ws or {}).get("repo_worktrees") or []
    check("G1 正规入口补传：derive 产出双仓 repo_worktrees",
          member_repos(rws) == ["repo_a", "repo_b"]
          and len({e.get("branch") for e in rws}) == len(rws)
          and Path(worktree).resolve() == Path((ws or {}).get("path", "")).resolve()
          and Path(worktree).resolve().is_relative_to(root.resolve()),
          "rws=%r" % (rws,))
    # G1b 两跳透传：create 产出的 dict workspace 转发 ticket-start（derive 以 dict ws 收）
    # ——明细不丢（缺陷根因即此通道被堵死）。
    try:
        _l, ws2, _w, _b = shared.derive_lane_workspace(
            TICKET + "h2", "worktree", workspace=ws, worktree=str(worktree),
            branch=str(branch), project_root=str(root))
        check("G1b 创建链明细经 ticket-start 转发不丢（两跳透传）",
              member_repos((ws2 or {}).get("repo_worktrees")) == ["repo_a", "repo_b"],
              "ws2=%r" % (ws2,))
    except Exception as e:
        check("G1b 创建链明细经 ticket-start 转发不丢（两跳透传）", False,
              "%s: %s" % (type(e).__name__, e))
    # G2 缺陷形态对照：不传 repo_write_set = 旧病灶形状（单仓明细缺失）
    _l, ws_old, _w, _b = shared.derive_lane_workspace(TICKET, "worktree",
                                                      project_root=str(root))
    check("G2 缺陷形态对照：漏传即无明细（钉死旧病灶形状）",
          not ((ws_old or {}).get("repo_worktrees")), "ws_old=%r" % (ws_old,))
    # G3 单仓零回归：根即仓无子仓 → 不激活（透传 repo_write_set 也走旧路径）
    single = Path(tmp) / "single"
    _init_repo(single, "f.txt")
    _l, ws_s, _w, _b = shared.derive_lane_workspace(
        TICKET, "worktree", project_root=str(single), repo_write_set=["f.txt"])
    check("G3 单仓零回归：repo_write_set 透传不激活多仓派生",
          not ((ws_s or {}).get("repo_worktrees")), "ws_s=%r" % (ws_s,))

    # ---------- 混合形态夹具（缺陷现场形态；L2/L3/台面项目共用） ----------
    mixed = build_mixed_project(tmp)

    # 项目注册表夹具（L2 子进程腿与隔离台腿共用；utmr → 混合形态项目）
    regroot = Path(tmp) / "reg"
    regdir = regroot / "utmr"
    regdir.mkdir(parents=True)
    (regdir / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: utmr\n    name: UT 多仓\n    dirs:\n      - %s\n"
        % mixed, "utf-8")

    # ---------- temporalio 面：保险丝A/B + 逐仓物化硬断言 ----------
    if not temporalio_available():
        env_fail("temporalio 缺失——保险丝A（ticket-start 拒收面）/保险丝B（红灯面）"
                 "/prepare 逐仓物化行为腿全靠真链路，无 stdlib 替代")
    else:
        import asyncio
        import agent_activities as aa  # noqa: E402

        lane_dir = root / ".lane" / TICKET
        # G6 逐仓物化落成（L1 硬断言）：prepare_workspace 直调 → 双仓树+清单
        from shared import WorkspacePrep  # noqa: E402
        prep = WorkspacePrep(ticket_id=TICKET,
                             workspace={"type": "worktree", "path": str(lane_dir)},
                             write_set=list(WS), project_root=str(root))
        pr = asyncio.run(aa.prepare_workspace(prep))
        check("G6 prepare 双仓 created", pr.ok and pr.action.startswith("created"),
              "res=%r" % (pr,))
        trees_ok = all(
            any(Path(ln[len("worktree "):]).resolve() == (lane_dir / rel).resolve()
                for ln in git("worktree", "list", "--porcelain",
                              cwd=root / rel).splitlines()
                if ln.startswith("worktree "))
            for rel in ("repo_a", "repo_b"))
        mf = lane_dir / aa.MULTI_MANIFEST_REL  # 引擎单一真源常量（旧名路径不经新字面量）
        mf_ok = False
        if mf.is_file():
            try:
                entries = json.loads(mf.read_text("utf-8"))
                mf_ok = ({e["repo"] for e in entries} == {"repo_a", "repo_b"}
                         and all(e.get("branch") for e in entries))
            except Exception as e:
                print("清单解析异常: %s" % e)
        check("G6 L1 硬断言：双仓树均=所属仓已注册 worktree", trees_ok)
        check("G6 L1 硬断言：清单落盘两仓条目（repo/name/branch 全）", mf_ok)

        # ---------- 保险丝B（混合形态=缺陷现场形态；清单缺失=纯单仓回落） ----------
        defect_tid = TICKET + "df"
        dlane = mixed / ".lane" / defect_tid
        rc, _o, _e = git_ok("worktree", "add", "-b", "lane/" + defect_tid,
                            str(dlane), "HEAD", cwd=mixed)
        if rc != 0:
            env_fail("根仓 worktree add 失败（夹具环境问题，非被测红）：%s" % (_e or _o)[-200:])
        else:
            base_a = git("rev-parse", "HEAD", cwd=mixed / "repo_a").strip()
            # G7 纯函数面：清单缺失 × 成员仓写集 → 红灯点名缺失仓
            fuse_fn = getattr(aa, "multirepo_materialization_error", None)
            if fuse_fn is None:
                check("G7 保险丝B：清单缺失红灯点名缺失仓（绝不静默收口）", False,
                      "agent_activities.multirepo_materialization_error 缺失（红属 TDD 预期）")
            else:
                scopes = aa._lane_scopes(dlane, "lane/" + defect_tid)
                try:
                    try:
                        fuse_b = fuse_fn(dlane, list(WS), scopes)
                    except TypeError:
                        fuse_b = fuse_fn(dlane, list(WS), scopes, None)
                except Exception as e:
                    fuse_b = "EXC %s: %s" % (type(e).__name__, e)
                check("G7 保险丝B：清单缺失红灯点名缺失仓（绝不静默收口）",
                      bool(fuse_b) and "repo_a" in fuse_b and "repo_b" in fuse_b,
                      "fuse_b=%r" % (fuse_b,))
            # G7b merge_check 整体红灯 + 物化检查项红 + 非冲突类（conflict=False）
            try:
                mc = asyncio.run(aa.merge_check(call_with_supported_fields(
                    shared.MergeCheckArgs,
                    ticket_id=defect_tid, worktree=str(dlane),
                    branch="lane/" + defect_tid, base_ref="", write_set=list(WS))))
                fuse_items = [c for c in (mc.checks or [])
                              if "物化" in str(c.get("item", ""))]
                check("G7b 清单缺失×成员仓写集：merge_check 红灯且物化检查项红点名仓",
                      (not mc.green) and fuse_items
                      and all(c.get("green") is False for c in fuse_items)
                      and "repo_a" in json.dumps(fuse_items, ensure_ascii=False),
                      "green=%s fuse=%r" % (mc.green, fuse_items))
                check("G7c 物化红灯为非冲突类（conflict=False，不进自动消解回路）",
                      getattr(mc, "conflict", None) is False,
                      "conflict=%r" % (getattr(mc, "conflict", None),))
            except Exception as e:
                check("G7b 清单缺失×成员仓写集：merge_check 红灯且物化检查项红点名仓", False,
                      "异常: %s: %s" % (type(e).__name__, e))
                check("G7c 物化红灯为非冲突类（conflict=False，不进自动消解回路）", False, "同上")
            # G7d merge 收口同源保险丝：ok=False 点名、不落账、泳道保留
            try:
                mg = asyncio.run(aa.merge(call_with_supported_fields(
                    shared.MergeArgs,
                    ticket_id=defect_tid, worktree=str(dlane),
                    branch="lane/" + defect_tid,
                    write_set=list(WS), defer_teardown=True)))
                err = str(getattr(mg, "error", "") or "")
                after_a = git("rev-parse", "HEAD", cwd=mixed / "repo_a").strip()
                check("G7d merge 收口保险丝：ok=False 点名成员仓（不静默按单仓锚落账）",
                      (not getattr(mg, "ok", True)) and "repo_a" in err,
                      "mg=%r" % (mg,))
                check("G7e 成员仓 main 零新提交（不落账）+ 泳道保留交人工",
                      after_a == base_a and dlane.exists(),
                      "before=%s after=%s lane_exists=%s"
                      % (base_a[:8], after_a[:8], dlane.exists()))
            except Exception as e:
                check("G7d merge 收口保险丝：ok=False 点名成员仓（不静默按单仓锚落账）", False,
                      "异常: %s: %s" % (type(e).__name__, e))
                check("G7e 成员仓 main 零新提交（不落账）+ 泳道保留交人工", False, "同上")
            # G7f 绿对照：物化齐全（清单+树在位）→ merge_check 物化检查项绿（不误伤）
            try:
                gtid = TICKET + "gr"
                glane = mixed / ".lane" / gtid
                # 正规入口链形态：先 derive 产出明细，再按真源逐仓物化（混合形态
                # 根树=泳道容器本身，明细含 repo="" 条目；不传明细=prepare 内部
                # 推导非真源通道，与真实链不符）
                _gl, gws, _gw, _gb = shared.derive_lane_workspace(
                    gtid, "worktree", project_root=str(mixed), repo_write_set=list(WSFULL))
                grws = (gws or {}).get("repo_worktrees") or []
                gprep = asyncio.run(aa.prepare_workspace(call_with_supported_fields(
                    shared.WorkspacePrep,
                    ticket_id=gtid,
                    workspace={"type": "worktree", "path": str(glane)},
                    write_set=list(WSFULL), project_root=str(mixed),
                    repo_worktrees=[dict(e) for e in grws])))
                if not getattr(gprep, "ok", False):
                    raise AssertionError("prepare 未绿：%r" % (gprep,))
                mc2 = asyncio.run(aa.merge_check(call_with_supported_fields(
                    shared.MergeCheckArgs,
                    ticket_id=gtid, worktree=str(glane),
                    branch="lane/" + gtid, base_ref="", write_set=list(WSFULL))))
                fuse2 = [c for c in (mc2.checks or []) if "物化" in str(c.get("item", ""))]
                check("G7f 物化齐全对照：物化检查项绿（红灯不扩大化）",
                      bool(fuse2) and all(c.get("green") is True for c in fuse2),
                      "prep=%r fuse=%r" % (gprep, fuse2))
            except Exception as e:
                check("G7f 物化齐全对照：物化检查项绿（红灯不扩大化）", False,
                      "异常: %s: %s" % (type(e).__name__, e))

        # ---------- 保险丝A（子进程真入口，连接前拒收零 Temporal 依赖） ----------
        # 注册表指夹具；TARGET 指不可达桩（拒收腿根本连不上；对照腿连不上=
        # 闸放行的判别面）——绝不触生产 7233/8233。
        env_stub = dict(os.environ)
        env_stub["SANDBAR_PROJECTS_DIR"] = str(regroot)
        env_stub["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
        env_stub.pop("SANDBAR_NAMESPACE", None)
        py = sys.executable
        rc, out = run_client(py, "ticket-start", {
            "ticket_id": TICKET + "fa", "template_id": "dev-lane", "project": "utmr",
            "title": "fuseA", "worktree": str(mixed / ".lane" / ("x-" + TICKET)),
            "write_set": list(WS)}, env_stub)
        payload = parse_out_json(out)
        check("G4 保险丝A：成员仓写集×空明细拒收点名条目（显式 worktree 不能绕过）",
              payload.get("ok") is False and "repo_a/src/a.py" in out,
              "payload=%r out=%r" % (payload, out[-240:]))
        # 对照1：纯根仓写集 + 显式 worktree → 不误伤（放行过闸，败于连接非拒收）
        rc, out = run_client(py, "ticket-start", {
            "ticket_id": TICKET + "fb", "template_id": "dev-lane", "project": "utmr",
            "title": "fuseA-ctl-root", "worktree": str(mixed / ".lane" / ("y-" + TICKET)),
            "write_set": ["integration/"]}, env_stub)
        check("G5 对照：纯根仓写集不被拒收（不误伤，无成员仓点名）",
              "repo_a/src/a.py" not in out and "repo_b/lib/b.py" not in out,
              "out=%r" % (out[-240:],))
        # 对照2：多仓写集合法派生（无显式 worktree，明细在）→ 放行过闸
        rc, out = run_client(py, "ticket-start", {
            "ticket_id": TICKET + "fc", "template_id": "dev-lane", "project": "utmr",
            "title": "fuseA-ctl-derive", "write_set": list(WS)}, env_stub)
        check("G5b 对照：多仓写集合法派生不被拒收（明细在场=闸放行）",
              "参数非法" not in out and "repo_a/src/a.py" not in out,
              "out=%r" % (out[-240:],))

    # ---------- 隔离台面：正规入口 CLI 全链 + 裸入口持久化契约 ----------
    def stage_legs():
        sys.path.insert(0, str(INTEG))
        sys.path.insert(0, str(INTEG / "t260904-02"))

        class _Fail:
            def bail(self, msg, code):
                print("ENV_FAIL %s" % msg, flush=True)
                raise SystemExit(2)

        from lib_gate import require_bench, require_stage, stage_down
        bench = require_bench(_Fail())
        py = bench.poc_python()
        holder = {"stage_mod": None, "stage": None}
        proj = "t26091003-fuses"
        try:
            stage_mod, stage = require_stage(_Fail(), proj, proj)
            holder["stage_mod"], holder["stage"] = stage_mod, stage
            env_stage = dict(os.environ)
            env_stage["SANDBAR_PROJECTS_DIR"] = str(regroot)
            env_stage["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
            env_stage["SANDBAR_NAMESPACE"] = stage["namespace"]

            def probe_input(tid):
                p = subprocess.run(
                    [py, str(INTEG / "t260904-02" / "probe_wf_input.py"),
                     "127.0.0.1:%d" % stage["ports"]["temporal"], stage["namespace"], tid],
                    capture_output=True, text=True, timeout=120)
                try:
                    return json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
                except Exception:
                    return {}

            # G8 正规入口全链：ticket.py 模块装载 run(create)（ticket.py 无 __main__ CLI，
            # 库函数消费先例=t260904-08 lib_retire；env 指台 → _poc spawn 的 client.py 透传）
            saved = {k: os.environ.get(k) for k in
                     ("SANDBAR_PROJECTS_DIR", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}
            create_res, create_err = None, ""
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "_t26091003_ticket", str(REPO / "server" / "tools" / "ticket.py"))
                tk = importlib.util.module_from_spec(spec)
                sys.modules["_t26091003_ticket"] = tk
                spec.loader.exec_module(tk)
                for k, v in env_stage.items():
                    if k.startswith("SANDBAR"):
                        os.environ[k] = v
                create_res = tk.run({"op": "create", "project": "utmr",
                                     "workflow": "dev-lane",
                                     "title": "正规入口多仓全链", "write_set": list(WS),
                                     "body": "缺陷复现形态修复验证", "id": TICKET + "full"})
            except Exception as e:
                create_err = "%s: %s" % (type(e).__name__, e)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            body_ws = (create_res or {}).get("workspace") if isinstance(create_res, dict) else None
            check("G8a 正规入口 ticket.py create 真建票成功（隔离台）",
                  isinstance(create_res, dict) and create_res.get("id") == TICKET + "full",
                  "res=%r err=%s" % (create_res, create_err[:200]))
            check("G8b create 返回体带成员仓明细（辅证）",
                  set(member_repos((body_ws or {}).get("repo_worktrees")))
                  >= {"repo_a", "repo_b"},
                  "workspace=%r" % (body_ws,))
            pj = probe_input(TICKET + "full")
            inp = pj.get("input") or {}
            check("G8c 持久化 TicketInput.repo_worktrees 双仓（Temporal payload 契约）",
                  pj.get("found") is True
                  and set(member_repos(inp.get("repo_worktrees"))) >= {"repo_a", "repo_b"},
                  "probe=%r" % (pj,))
            # L4 裸入口回归（勿回归红线）：client.py ticket-start 多仓写集（无显式
            # worktree）→ 真启动，持久化明细双仓
            rc, out = run_client(py, "ticket-start", {
                "ticket_id": TICKET + "bare", "template_id": "dev-lane",
                "project": "utmr", "title": "裸入口回归票", "write_set": list(WS)},
                env_stage)
            payload = parse_out_json(out)
            check("L4a 裸入口 ticket-start 真启动成功（多仓写集无显式 worktree）",
                  payload.get("ok") is True, "payload=%r out=%r" % (payload, out[-240:]))
            pj2 = probe_input(TICKET + "bare")
            inp2 = pj2.get("input") or {}
            check("L4b 裸入口持久化 TicketInput.repo_worktrees 双仓（勿回归红线）",
                  pj2.get("found") is True
                  and set(member_repos(inp2.get("repo_worktrees"))) >= {"repo_a", "repo_b"},
                  "probe=%r" % (pj2,))
            return 0
        finally:
            if holder["stage"] is not None:
                try:
                    stage_down(holder["stage_mod"], proj)
                except Exception as e:
                    env_fail("拆台失败（残留需人工清理）：%s" % e)

    stage_rc = 0
    try:
        stage_rc = stage_legs()
    except SystemExit as e:
        stage_rc = e.code or 2
    except Exception as e:
        env_fail("台面腿异常中断：%s: %s" % (type(e).__name__, e))
        stage_rc = 2
    if stage_rc == 2:
        env_fail("docker/隔离台缺席：正规入口 CLI 全链腿与裸入口持久化腿不可执行——"
                 "创建链形状/保险丝/物化腿已在本场跑完；arbitrate/merge 期 docker 环境必须全绿")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(summary())
