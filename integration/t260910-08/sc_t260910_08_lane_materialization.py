#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-08 场景：多仓票真开票后泳道磁盘逐仓物化终态（灰盒 L3，dengzhufpv 形态）。

intent（守护的用户可感知行为/合同，工单 t260910-08 验收第 1 条的仪器）：
- 正规入口 ticket.py create 真开票（dengzhufpv 形态写集：根仓+子仓各一条）→ 真专属
  worker 跑 DevLaneWorkflow → prepare_workspace 真建泳道 → 泳道磁盘终态四件套：
  ① 泳道容器下逐成员仓工作区目录存在（repo="" 根树=容器本身是根仓已注册 worktree）；
  ② 每仓分支名 = lane/<票>-<seg>（根树 = lane/<票>-root）；
  ③ 清单 repo_worktrees.json 在引擎真写点位（shared.multi_manifest_path 解析位，
    t260914-01 起新泳道=新名协调目录），repo/name/branch 与派生明细逐条一致；
  ④ meta.repo_worktrees 非空（ticket show 读面 = dengzhufpv 取证同一读面，
    该字段此前恒 null 误导诊断）。
- Temporal 持久化契约：TicketInput.repo_worktrees 双仓在起始事件 payload
  （probe_wf_input 读面，明细进 Temporal 面不丢）。
- 单仓对照：同链真开票 → 无清单、单 worktree、meta 明细空（零回归面）。
- 畸形明细两层互不冒充（t260910-03 在案先例：类型毁形在编解码层拒、语义非法在闸层拒；
  实证注记（implement 段修订）：本仓 temporalio 的 type-hints 校验发生在 **decode 侧**
  （to_payloads 不带 type_hints=编码面不设防），故真链行为=start 受理、worker 解码面
  拒收（t260910-13 实案同款签名 "Failed converting field"）、workflow 代码永不执行）：
  (a) 类型毁形（非 dict 条目）→ start 受理但 worker 解码拒：workflow 代码不执行、
      Temporal 面无 workspace_prep、磁盘零落仓、payload 原样过线（无静默清洗）；
  (b) 语义毁形（codec 可过、闸必拒：条目缺 name）→ 真 workflow 进 blocked，
      workspace_prep.error 可读拒收点名；不崩 _init、不落单仓泳道形态。
- KI-067 设计进去：create 返回体/CLI 输出只作辅证，真值判定锚磁盘与 Temporal 侧
  效果；create 异常/空输出/拒收回执 = 红灯点名，绝不静默。

与相邻场景 intent 分界：t260910-03 守「正规入口补传+双保险丝」（derive 复刻+直调
prepare+payload 持久化），t260907-06/-12 守多仓泳道本体/混合形态归属——彼等全部
不经过 dev_lane._init 的第二跳（KI-063 同构盲区，t260910-07 真机单仓即实证）；
本场景唯一守「TicketInput→_init→meta→WorkspacePrep→activity 全跳真码 + 磁盘终态」。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
docker/隔离台库/temporalio 缺席 = ENV_FAIL exit 2 点名（真链子用例无 stdlib 替代）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INTEG = REPO / "integration"
POC = REPO / "server" / "engine"

# 红线桩：绝不触生产 7233/8233/3099——shared 在 import 期读 TARGET_HOST，先钉
# 不可达桩再 import（stdlib 子用例零连接；台面子用例由隔离台 env 覆盖）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面（TARGET_HOST 已被上方 env 桩钉死）

TICKET = "t26091008lm"          # 多仓主子用例（混合形态：根树+repo_a 树）
TICKET_SINGLE = "t26091008sg"   # 单仓对照子用例
TICKET_BAD = "t26091008bd"      # 畸形明细子用例（ty=类型毁形 / sm=语义毁形）
WS = ["docs/root.md", "repo_a/src/a.py"]   # dengzhufpv 形态：根仓+子仓各一条
PROJ_MULTI = "utmr08"
PROJ_SINGLE = "utsg08"
DISK_DEADLINE = 150.0           # 真链（create→worker→activity）磁盘终态等待上限

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name, flush=True)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""), flush=True)


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def env_exit(reason):
    env_fail(reason)
    sys.exit(2)


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


def wait_until(fn, deadline_s, interval=2.0):
    """轮询至 fn() 为真或超时（返回最后一次 fn() 值）。磁盘/快照等待共用。"""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    try:
        return bool(fn())
    except Exception:
        return False


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


# ---------- 夹具（t260910-03 同款形态：前置与基础步骤共享复用） ----------

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


def build_mixed_project(base):
    """混合形态（dengzhufpv 缺陷现场形态）：根亦 git 仓 + repo_a/repo_b 子仓
    （.gitignore 忽略子仓=现场同款）。写集只命中根+repo_a（形态=双树）。"""
    root = Path(base) / "mixed"
    root.mkdir(parents=True)
    _init_repo(root, "docs/root.md")
    (root / ".gitignore").write_text("repo_a/\nrepo_b/\n", encoding="utf-8")
    git("add", "-A", cwd=root)
    git("commit", "-m", "gitignore", cwd=root)
    _init_repo(root / "repo_a", "src/a.py")
    _init_repo(root / "repo_b", "lib/b.py")
    return root


def build_single_project(base):
    """单仓对照（根即仓、无子仓——零回归面）。"""
    root = Path(base) / "single"
    _init_repo(root, "f.txt")
    return root


def member_repos(entries):
    """repo_worktrees 明细里的成员仓相对路径集合（repo 非空=成员仓；空=根树）。"""
    return sorted({str(e.get("repo") or "") for e in (entries or [])
                   if isinstance(e, dict) and str(e.get("repo") or "")})


def repo_seq(entries):
    """明细条目的 repo 有序列表（**含空串根树条目**）——主子用例断言用全序比对，
    不用 member_repos（它滤掉空串根树条目，混形态对照会假红）。"""
    return [str(e.get("repo") or "") for e in (entries or []) if isinstance(e, dict)]


# ---------- 台面驱动（lib_gate 共享设施 + 专属 worker，t260908-01 同款手法） ----------

def env_for(extra):
    """子进程 env：剥掉环境里全部其它 SANDBAR_*（本场景自身可能在泳道内被派发，
    环境标记不得泄给被测链），只保留台面三键+显式 extra。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SANDBAR_")}
    for k in ("SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE", "SANDBAR_PROJECTS_DIR"):
        if k in os.environ:
            env[k] = os.environ[k]
    env.update(extra)
    return env


def load_ticket_module():
    """ticket.py 无 __main__ CLI（t260910-03 G8 在案手法）：模块装载 run()。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_t26091008_ticket", str(REPO / "server" / "tools" / "ticket.py"))
    tk = importlib.util.module_from_spec(spec)
    sys.modules["_t26091008_ticket"] = tk
    spec.loader.exec_module(tk)
    return tk


def start_worker(py, tid, tmpdir):
    """拉本票专属 worker（桩大脑：自写结果文件，零模型调用；watch 快档）。"""
    extra = {
        "SANDBAR_TASK_QUEUES": shared.ticket_task_queue(tid),
        "SANDBAR_WATCH_WORKFLOW": tid,
        "SANDBAR_WATCH_INTERVAL_SEC": "4",
        "SANDBAR_AGENT_STUB": "1",
        "SANDBAR_SUGGEST_STUB": "ok",
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    log = open(os.path.join(tmpdir, "worker-%s.log" % tid), "w")
    return subprocess.Popen([py, str(POC / "worker.py")], env=env_for(extra),
                            stdout=log, stderr=subprocess.STDOUT)


def stop_worker(proc, label):
    """资源回收（每个 spawn 的每个终态都有回收）：TERM 20s 内退出，否则 kill 兜底计红。"""
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
        check("%s：worker TERM 后 20s 内退出（资源回收）" % label, True)
    except Exception:
        check("%s：worker TERM 后 20s 内退出（资源回收）" % label, False, "kill 兜底")
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass


def probe_input(py, stage, tid):
    """t260904-02 共享探针：读 WorkflowExecutionStarted 的 input payload。"""
    p = subprocess.run(
        [py, str(INTEG / "t260904-02" / "probe_wf_input.py"),
         "127.0.0.1:%d" % stage["ports"]["temporal"], stage["namespace"], tid],
        capture_output=True, text=True, timeout=120)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    except Exception:
        return {}


PROBE_SRC = r'''
# 畸形注入探针（场景运行时写入 tmp，非仓库资产）：手拼 TicketInput 直接
# start_workflow（旁路 ticket-start 派生面——只有旁路才能携带手写明细）。
# argv: <ticket_id> <project> <repo_worktrees JSON> <workspace_path>
# stdout 单行 JSON：{"started": bool, "error"?: "..."}
import asyncio, json, sys
sys.path.insert(0, "__POC__")
import shared
from shared import TicketInput
from workflows_v2 import TEMPLATE_CLASSES


async def main():
    tid, proj, rws, ws_path = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
    cls = TEMPLATE_CLASSES.get("dev-lane")
    inp = TicketInput(ticket_id=tid, template_id="dev-lane", project=proj,
                      title="畸形明细注入", lane="worktree",
                      workspace={"type": "worktree", "path": ws_path},
                      worktree=ws_path, branch="lane/" + tid,
                      write_set=["repo_a/src/a.py"], repo_worktrees=rws,
                      user_request="integration t260910-08 malformed inject")
    try:
        from temporalio.client import Client
        c = await Client.connect(shared.TARGET_HOST, namespace=shared.NAMESPACE)
        await c.start_workflow(cls.run, inp, id=tid,
                               task_queue=shared.ticket_task_queue(tid))
        print(json.dumps({"started": True}))
    except Exception as e:
        print(json.dumps({"started": False,
                          "error": "%s: %s" % (type(e).__name__, str(e)[:240])}))


asyncio.run(main())
'''


def write_probe(tmpdir):
    p = Path(tmpdir) / "probe_start_malformed.py"
    p.write_text(PROBE_SRC.replace("__POC__", str(POC)), encoding="utf-8")
    return p


def run_probe(py, probe, tid, proj, rws, ws_path):
    p = subprocess.run([py, str(probe), tid, proj, json.dumps(rws), str(ws_path)],
                       env=env_for({}), capture_output=True, text=True, timeout=120)
    for ln in ((p.stdout or "") + (p.stderr or "")).splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {"started": None, "error": (p.stderr or p.stdout or "")[-200:]}


# ---------- 主流程 ----------

tmp = tempfile.mkdtemp(prefix="t260910-08-mat-")
try:
    # ---------- stdlib 子用例：夹具自证（夹具漂移=假红/假绿防线，恒跑） ----------
    mixed = build_mixed_project(tmp)
    single = build_single_project(tmp)
    check("S1 夹具自证：混合形态=根仓+子仓并存（dengzhufpv 形态）",
          shared.is_multi_repo_layout(mixed)
          and (mixed / ".git").exists() and (mixed / "repo_a" / ".git").exists(),
          "mixed=%s" % mixed)
    check("S2 夹具自证：单仓项目不激活多仓形态",
          not shared.is_multi_repo_layout(single), "single=%s" % single)

    # 项目注册表夹具（台面子用例与 ticket.py create 共用）
    regroot = Path(tmp) / "reg"
    for key, name, root in ((PROJ_MULTI, "UT 多仓 08", mixed),
                            (PROJ_SINGLE, "UT 单仓 08", single)):
        regdir = regroot / key
        regdir.mkdir(parents=True)
        (regdir / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
            % (key, name, root), "utf-8")

    if not temporalio_available():
        env_exit("temporalio 缺失——真链子用例（ticket.py create→worker→磁盘终态）"
                 "无 stdlib 替代；arbitrate/merge 期 venv 环境必须实跑")

    def stage_legs():
        class _Fail:
            def bail(self, msg, code):
                print("ENV_FAIL %s" % msg, flush=True)
                raise SystemExit(2)

        sys.path.insert(0, str(INTEG))
        sys.path.insert(0, str(INTEG / "t260904-02"))
        from lib_gate import require_bench, require_stage, stage_down
        bench = require_bench(_Fail())
        py = bench.poc_python()
        proj = "t26091008-mat"
        holder = {"stage_mod": None, "workers": []}
        saved = {k: os.environ.get(k) for k in
                 ("SANDBAR_PROJECTS_DIR", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}

        def spawn_worker(tid, label):
            w = start_worker(py, tid, tmp)
            holder["workers"].append((label, w))
            return w

        try:
            stage_mod, stage = require_stage(_Fail(), proj, proj)
            holder["stage_mod"] = stage_mod
            # 台面 env 钉进本进程（ticket.py 模块装载与 probe 子进程同源）；
            # 恢复在 finally（绝不把台面 env 泄还给调用方）。
            os.environ["SANDBAR_PROJECTS_DIR"] = str(regroot)
            os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
            os.environ["SANDBAR_NAMESPACE"] = stage["namespace"]

            tk = load_ticket_module()
            # 泳道目录=创建链单点派生（default_lane_paths：票号→.lane/t<date>-<alias>，
            # 与 create 实际落点同源——手写 .lane/<票号> 与派生名不等=磁盘断言永久假红）
            lane_rel, _lane_br = shared.default_lane_paths(TICKET)
            lane = mixed / lane_rel
            manifest = shared.multi_manifest_path(lane)  # 引擎真写点（协调目录解析位，t260914-01）
            # 期望明细=创建链同一单点派生（build_repo_worktrees 纯函数，无 git 子进程）
            detail = shared.build_repo_worktrees(mixed, WS, lane_rel.rsplit("/", 1)[-1])

            def tk_show(tid, deadline_s=30.0):
                """ticket show 读面（=dengzhufpv 取证同面）：轮询至可读，返回 meta 或 None。"""
                end = time.time() + deadline_s
                last = None
                while time.time() < end:
                    try:
                        last = tk.run({"op": "show", "id": tid})
                        if isinstance(last, dict):
                            return last
                    except Exception as e:
                        last = "%s: %s" % (type(e).__name__, str(e)[:160])
                    time.sleep(2.0)
                return None if not isinstance(last, str) else last

            # ---------- T1/T2/T3 多仓主子用例：真开票→真 worker→磁盘终态四件套 ----------
            create_res, create_err = None, ""
            try:
                create_res = tk.run({"op": "create", "project": PROJ_MULTI,
                                     "workflow": "dev-lane", "title": "多仓真开票物化",
                                     "write_set": list(WS), "id": TICKET})
            except Exception as e:
                create_err = "%s: %s" % (type(e).__name__, str(e)[:240])
            bad_create = (not isinstance(create_res, dict)) or create_err
            check("T1 正规入口 ticket.py create 真开票受理（辅证，KI-067：不作成功判据）",
                  isinstance(create_res, dict) and create_res.get("id") == TICKET,
                  "res=%r err=%s" % (create_res if isinstance(create_res, dict) else str(create_res)[:160], create_err))

            def disk_ready():
                return manifest.is_file() and (lane / "repo_a").is_dir()

            if bad_create:
                for nm in ("T3a", "T3b", "T3c", "T3d", "T4"):
                    check(nm + "（依赖 create 受理）", False, "create 失败：%s" % (create_err or create_res))
            else:
                spawn_worker(TICKET, "T2")
                got_disk = wait_until(disk_ready, DISK_DEADLINE)
                # 四件套①：逐仓工作区目录在位（根树=容器本身是根仓已注册 worktree）
                # git 上报已解析路径（macOS /var→/private/var），比对侧同款 resolve。
                rc, out_a, _ = git_ok("worktree", "list", "--porcelain", cwd=mixed / "repo_a")
                rc2, out_root, _ = git_ok("worktree", "list", "--porcelain", cwd=mixed)
                check("T3a 磁盘终态①：子仓树与根树（容器本身）均为所属仓已注册 worktree",
                      got_disk and (str((lane / "repo_a").resolve()) in out_a) and (str(lane.resolve()) in out_root),
                      "got_disk=%s repo_a_list=%r root_list=%r" % (got_disk, out_a[:160], out_root[:160]))
                # 四件套②：每仓 HEAD 分支=创建链派生的 branch（根树=-root、子仓=-repo_a）
                def _head_branch(repo_rel):
                    d = lane / repo_rel if repo_rel else lane
                    return git("rev-parse", "--abbrev-ref", "HEAD",
                               cwd=d).strip() if d.is_dir() else ""
                exp_br = {str(e["repo"]): str(e["branch"]) for e in detail}
                got_br = {r: _head_branch(r) for r in exp_br}
                check("T3b 磁盘终态②：分支名 lane/<票>-<seg>（逐仓对派生 branch）",
                      got_br == exp_br,
                      "got=%r exp=%r" % (got_br, exp_br))
                # 四件套③：清单在位且与明细逐条一致（repo/name/branch 三元组集合）
                mf = []
                try:
                    mf = json.loads(manifest.read_text("utf-8")) if manifest.is_file() else []
                except Exception:
                    mf = []
                mf_triples = sorted((str(e.get("repo") or ""), str(e.get("name") or ""),
                                     str(e.get("branch") or "")) for e in mf if isinstance(e, dict))
                exp_triples = sorted((str(e["repo"]), str(e["name"]), str(e["branch"]))
                                     for e in detail)
                check("T3c 磁盘终态③：清单 repo/name/branch 与派生明细一致（含根树条目）",
                      mf_triples == exp_triples,
                      "manifest=%r exp=%r" % (mf_triples, exp_triples))
                # 四件套④：meta.repo_worktrees 非空（取证同读面，此前恒 null）
                meta = tk_show(TICKET)
                mr = meta.get("repo_worktrees") if isinstance(meta, dict) else None
                check("T3d 磁盘终态④：meta.repo_worktrees 非空且与派生明细同源（含根树条目）",
                      isinstance(meta, dict) and isinstance(mr, list) and mr
                      and repo_seq(mr) == repo_seq(detail),
                      "show_read=%r" % (str(meta)[:220],))
                wp = meta.get("workspace_prep") if isinstance(meta, dict) else None
                check("T3e workspace_prep 收据=多仓 created（非单仓形态）",
                      isinstance(wp, dict) and wp.get("action") == "created"
                      and wp.get("kind") == "worktree",
                      "wp=%r show_read=%r" % (wp, str(meta)[:160]))
                # T4 Temporal 持久化契约：起始事件 payload 明细双仓
                pj = probe_input(py, stage, TICKET)
                inp = pj.get("input") or {}
                check("T4 持久化 TicketInput.repo_worktrees 双仓（对外数据契约）",
                      pj.get("found") is True
                      and repo_seq(inp.get("repo_worktrees")) == repo_seq(detail),
                      "probe=%r repo_seq=%r" % (str(pj)[:400], repo_seq(inp.get("repo_worktrees"))))

            # ---------- T5 单仓对照子用例：同链真开票零回归 ----------
            s_res, s_err = None, ""
            try:
                s_res = tk.run({"op": "create", "project": PROJ_SINGLE,
                                "workflow": "dev-lane", "title": "单仓对照",
                                "write_set": ["f.txt"], "id": TICKET_SINGLE})
            except Exception as e:
                s_err = "%s: %s" % (type(e).__name__, str(e)[:200])
            lane_s_rel, _ = shared.default_lane_paths(TICKET_SINGLE)
            lane_s = single / lane_s_rel
            mf_s = shared.multi_manifest_path(lane_s)  # 单仓对照子用例：真写点无清单（不该有）
            if (not isinstance(s_res, dict)) or s_err:
                for nm in ("T5a", "T5b", "T5c"):
                    check(nm + "（依赖 create 受理）", False, "create 失败：%s" % (s_err or s_res))
            else:
                spawn_worker(TICKET_SINGLE, "T5")

                def single_prep_created():
                    m = tk_show(TICKET_SINGLE, 4.0)
                    if not isinstance(m, dict):
                        return False
                    return (m.get("workspace_prep") or {}).get("action") == "created"

                wait_until(single_prep_created, DISK_DEADLINE)
                s_meta = tk_show(TICKET_SINGLE)
                s_wp = s_meta.get("workspace_prep") if isinstance(s_meta, dict) else None
                check("T5a 单仓 workspace_prep=created（旧路径无回归）",
                      isinstance(s_wp, dict) and s_wp.get("action") == "created",
                      "wp=%r meta=%s" % (s_wp, type(s_meta).__name__))
                rc, out_w, _ = git_ok("worktree", "list", "--porcelain", cwd=single)
                check("T5b 单仓泳道=根仓已注册 worktree、无清单（不落多仓形态）",
                      (str(lane_s.resolve()) in out_w) and not mf_s.exists(),
                      "lane_list=%r manifest_exists=%s" % (out_w[:160], mf_s.exists()))
                check("T5c 单仓 meta.repo_worktrees 空（不激活多仓明细）",
                      isinstance(s_meta, dict) and not s_meta.get("repo_worktrees"),
                      "mr=%r" % ((s_meta or {}).get("repo_worktrees"),))

            # ---------- T6 畸形子用例 a：类型毁形 → worker 解码面拒收（workflow 代码不执行） ----------
            probe = write_probe(tmp)
            ty_id = TICKET + "ty"
            ty_lane_rel, _ = shared.default_lane_paths(ty_id)
            ty_lane = mixed / ty_lane_rel
            r6 = run_probe(py, probe, ty_id, PROJ_MULTI, [42], str(ty_lane))
            # 实证（implement 段，本仓 venv temporalio）：to_payloads 不带 type_hints
            # =编码面不设防 → start 受理；type-hints 校验发生在 worker 解码面（
            # t260910-13 实案同款签名 "Failed converting field"）→ workflow 代码永不执行。
            check("T6a 类型毁形 start 受理（编码面不设防=事实；拒收在解码面）",
                  r6.get("started") is True, "probe=%r" % (r6,))
            w6 = spawn_worker(ty_id, "T6")

            def ty_log_reject():
                try:
                    with open(os.path.join(tmp, "worker-%s.log" % ty_id),
                              encoding="utf-8", errors="replace") as f:
                        return "Failed converting" in f.read()
                except OSError:
                    return False
            got6 = wait_until(ty_log_reject, 120.0)
            try:
                with open(os.path.join(tmp, "worker-%s.log" % ty_id),
                          encoding="utf-8", errors="replace") as f:
                    tail6 = f.read()[-200:]
            except OSError:
                tail6 = "<log 不可读>"
            check("T6b 解码面拒收实锤：worker 日志含 Failed converting（解码校验=ticket "
                  "面零漂移）", got6, "log_tail=%r" % (tail6,))
            pj6 = probe_input(py, stage, ty_id)
            inp6 = pj6.get("input") or {}
            check("T6c payload 原样过线（Temporal 无静默清洗）",
                  pj6.get("found") is True and inp6.get("repo_worktrees") == [42],
                  "probe=%r" % (str(pj6)[:200],))
            check("T6d 磁盘零落仓（workflow 代码不执行=不进闸不物化，绝不静默单仓）",
                  not ty_lane.exists(), "lane_exists=%s" % (ty_lane.exists(),))

            # ---------- T7 畸形子用例 b：语义毁形 → 闸拒收 blocked（不崩不落单仓） ----------
            sm_id = TICKET + "sm"
            sm_lane_rel, _ = shared.default_lane_paths(sm_id)
            lane_sm = mixed / sm_lane_rel
            r7 = run_probe(py, probe, sm_id, PROJ_MULTI,
                           [{"repo": "repo_a", "branch": "lane/x"}],   # 缺 name：codec 可过、闸必拒
                           lane_sm)
            check("T7a 语义毁形（缺 name）可过编码层真启动（分层不冒充）",
                  r7.get("started") is True, "probe=%r" % (r7,))
            if r7.get("started") is True:
                spawn_worker(sm_id, "T7")

                def blocked_ready():
                    m = tk_show(sm_id, 4.0)
                    if not isinstance(m, dict):
                        return False
                    wp = m.get("workspace_prep") or {}
                    return m.get("stage_state") == "blocked" or bool(wp.get("error"))

                got_blocked = wait_until(blocked_ready, DISK_DEADLINE)
                m7 = tk_show(sm_id) if got_blocked else None
                err7 = (m7.get("workspace_prep") or {}).get("error") if isinstance(m7, dict) else None
                check("T7b 语义毁形进 blocked 且拒收文案可读点名（不崩 _init）",
                      got_blocked and isinstance(err7, str) and "name" in err7,
                      "got=%s meta=%s err=%r" % (got_blocked, type(m7).__name__, err7))
                check("T7c 语义毁形不落任何泳道形态（无清单无树=绝不静默单仓）",
                      not lane_sm.exists(),
                      "lane_exists=%s" % (lane_sm.exists(),))
            stop_all = holder["workers"]
            for label, w in stop_all:
                stop_worker(w, label)
            holder["workers"] = []
            return 0
        finally:
            for label, w in holder["workers"]:
                stop_worker(w, label + "（收尾回收）")
            if holder["stage_mod"] is not None:
                try:
                    stage_down(holder["stage_mod"], proj)
                except Exception as e:
                    env_fail("拆台失败（残留需人工清理）：%s" % e)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    stage_rc = 0
    try:
        stage_rc = stage_legs()
    except SystemExit as e:
        stage_rc = e.code or 2
    except Exception as e:
        env_fail("台面子用例异常中断：%s: %s" % (type(e).__name__, str(e)[:200]))
        stage_rc = 2
    if stage_rc == 2:
        env_fail("docker/隔离台缺席：真链子用例（正规入口 create→worker→磁盘终态/单仓对照/"
                 "畸形两层）不可执行——本场景全靠真链路无 stdlib 替代子用例；"
                 "arbitrate/merge 期隔离台必须全绿")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(summary())
