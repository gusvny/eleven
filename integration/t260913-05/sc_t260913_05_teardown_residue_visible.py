#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260913-05 场景：拆道清理失败的**残留可见性**（全链 L3，真 docker 隔离台+真 worker）。

intent（守护的用户可感知行为/合同）：
- 多仓票走到 merge→归档→拆道收口，**成员仓清不掉**时：workflow 照常收口（残留=可回收
  垃圾的既有取舍），但公开读面（ticket show 的 log 行「泳道拆除告警」）必须**逐仓点名**
  那个仓 —— 不再笼统一条、不得静默成功；被点名的仓在磁盘/git 上有**真残留**可核对；
- 逐仓粒度：一个仓清不掉**不拖停**其它仓（另一仓与泳道容器照清）；
- 同源判定（验收 D 的组合证据）：merge 逐仓落账的仓集合与拆道逐仓点名的仓集合一致
  （同一份 `_lane_scopes` 判定，不出现两套判定漂移）。

与相邻场景的 intent 分界（防 intent 级重复）：
- t260911-04-multirepo-fullchain-landing（本票回归锚）：守**成功路径**——逐仓落 main 与
  泳道零残留（T3a/T3d/T3d'/T3d-目录）；本条故意把**一个成员仓注入成清不掉**，守失败路径
  的可见性（时间线逐仓点名）与逐仓粒度，两者断言面不重叠；
- t260907-06 / t260910-08：直调 activity / 止步磁盘物化，都不含拆道失败面；
- t260913-05-teardown-scope-contract（本票 L2）：守回执字段与三态取源；本条守**回执→
  workflow log 行→收口终态**的composition（KI-046/KI-050/KI-071/KI-076 家族教训：
  测试在场≠测试生效，故必须真链跑一次）。

故障注入（夹具级，零产品改动）：merge 人审挂起窗内对成员仓 repo_a 的泳道工作树执行
`git worktree lock` —— git 真值态：单次 `remove --force` 必失败（cannot remove a locked
working tree）且**不删目录**，注入非破坏性、可回收（finally 里 unlock）。这是"真实 git 态
注入"，不是 monkeypatch 实现内部（绑定浅：被测实现换写法也不误判）。

断言全部落磁盘/git 终态与公开读面（KI-067 辅证纪律）；worker holder+finally 全终态回收
（TERM 20s→kill 兜底计红）。实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
docker/隔离台/temporalio 缺席 = ENV_FAIL exit 2 点名（真链无 stdlib 替代子用例）。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INTEG = REPO / "integration"
POC = REPO / "server" / "engine"
# 红线桩：绝不触生产 7233/8233/3099——先钉不可达桩再 import shared（import 期读 TARGET_HOST）
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(HERE))
from lib_t260913_05 import (  # noqa: E402
    check, env_fail, summary, git, git_ok, wait_until, build_project, tmpdir, rmtree,
    branch_lane_gone, branch_lane_present, worktree_has, names_repo, segment_of,
)
sys.path.insert(0, str(POC))
import shared  # noqa: E402

TICKET = "t26091305rv"          # 本场景唯一票（拆道失败注入子用例）
PROJ = "utrv13"                 # 夹具项目键（隔离台内，project.yaml 注册）
# 自测避撞旋钮（缺省=规范 id，闸内不受影响）：并发两次同 id 会撞 workflow id/队列名
# （实测：两个 agent 同时跑本文件 → 同队列任务互吃、落盘看到的是别人的夹具）。手工
# 自测请给唯一后缀：SANDBAR_UT_RUN_SUFFIX=2。
RUN_SUFFIX = "".join(ch for ch in os.environ.get("SANDBAR_UT_RUN_SUFFIX", "")
                     if ch.isalnum() or ch in "-_")
TICKET = TICKET + RUN_SUFFIX
PROJ = PROJ + RUN_SUFFIX
STAGE_PROJ = "t26091305-rv" + RUN_SUFFIX
WS = ["docs/root.md", "repo_a/src/a.py"]
STUB_DELAY_SEC = "10"           # 桩段在飞窗（给场景写票内文件留确定性窗口）
DISK_DEADLINE = 150.0
GATE_DEADLINE = 480.0
ROOT_MARK = "root changed by ticket\n"
MEMBER_MARK = "member a changed by ticket\n"

_WS_DIR = REPO / ".sandbar"
_WS_DIR.mkdir(parents=True, exist_ok=True)
tmp = tmpdir("t260913-05-l3")
FIX = {}


def env_for(extra):
    """子进程 env：剥掉环境里全部其它 SANDBAR_*（泳道标记不得泄给被测链），
    只保留台面三键 + 显式 extra。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SANDBAR_")}
    for k in ("SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE", "SANDBAR_PROJECTS_DIR"):
        if k in os.environ:
            env[k] = os.environ[k]
    env.update(extra)
    return env


def load_ticket_module():
    """ticket.py 无 __main__ CLI（t260910-03 在案手法）：模块装载 run()。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_t26091305_ticket", str(REPO / "server" / "tools" / "ticket.py"))
    tk = importlib.util.module_from_spec(spec)
    sys.modules["_t26091305_ticket"] = tk
    spec.loader.exec_module(tk)
    return tk


def start_worker(py, tid):
    """本票专属 worker（桩脑：自动过段零模型调用 + 在飞窗；watch 快档）。"""
    extra = {
        "SANDBAR_TASK_QUEUES": shared.ticket_task_queue(tid),
        "SANDBAR_WATCH_WORKFLOW": tid,
        "SANDBAR_WATCH_INTERVAL_SEC": "4",
        "SANDBAR_AGENT_STUB": "1",
        "SANDBAR_AGENT_STUB_DELAY_SEC": STUB_DELAY_SEC,
        "SANDBAR_AGENT_STUB_FILES": ",".join(WS),   # 桩段如实申报票内文件（KI-049 门②）
        "SANDBAR_SUGGEST_STUB": "ok",
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    log = open(os.path.join(str(tmp), "worker-%s.log" % tid), "w")
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


def seed_arbitrate_pass(lane, tid):
    """预置仲裁 verdict=pass（桩大脑 summary 无 verdict=，3 次格式纠正轮必 blocked at
    arbitrate；预置走幂等缓存读面，产品零改动——t260908-01 同款手法）。"""
    sdir = lane / ".sandbar"
    if not sdir.is_dir() and (lane / ".suyou").is_dir():  # naming-compat：旧点目录粘性回落
        sdir = lane / ".suyou"  # naming-compat：旧点目录粘性回落
    sdir.mkdir(parents=True, exist_ok=True)
    gen = 0
    for fn in sdir.iterdir():
        n = fn.name
        if n.startswith("stage_arbitrate_gen") and n.endswith(".json"):
            try:
                gen = max(gen, int(n[len("stage_arbitrate_gen"):-len(".json")]) + 1)
            except ValueError:
                pass
    (sdir / ("stage_arbitrate_gen%d.json" % gen)).write_text(json.dumps({
        "status": "ok",
        "summary": "集成测试三态判定：verdict=pass（拆道可见性守卫预置，走幂等缓存路径）",
        "report": "[seeded] verdict=pass（t260913-05 拆道残留可见性守卫）",
        "deliverables": [], "files_changed": [], "files_changed_shape": "ok",
        "evidence": "preset by sc_t260913_05_teardown_residue_visible",
    }, ensure_ascii=False), encoding="utf-8")


def write_ticket_files(lane):
    """票内写集文件写进泳道逐仓工作区（桩段在飞窗内的夹具行为；提交走全链 settle
    代落盘，不旁路——agent 沙箱写不了真 .git 的既有语义）。"""
    (lane / "docs" / "root.md").write_text(ROOT_MARK, encoding="utf-8")
    (lane / "repo_a" / "src" / "a.py").write_text(MEMBER_MARK, encoding="utf-8")


def _branch_has(repo, branch, rel, mark):
    rc, out, _ = git_ok("show", "%s:%s" % (branch, rel), cwd=repo)
    return rc == 0 and out == mark


def ensure_committed(lane, root, detail, deadline_s=240.0):
    """确保票内写集文件被全链 settle 落到各树 lane 分支（写→查→补写，不赌单次在飞窗）。
    返回 (ok, 诊断串)——失败时诊断串给出逐仓 (分支, rc, 实际内容)，不让自证失败无从归因。"""
    marks = {"": ("docs/root.md", ROOT_MARK), "repo_a": ("src/a.py", MEMBER_MARK)}
    brs = {str(e["repo"]): str(e["branch"]) for e in detail}
    diag = []
    end = time.time() + deadline_s
    while time.time() < end:
        ok = True
        diag = []
        for repo_rel, (rel, mark) in marks.items():
            repo = root / repo_rel if repo_rel else root
            br = brs.get(repo_rel, "")
            rc, out, err = git_ok("show", "%s:%s" % (br, rel), cwd=repo)
            if not (rc == 0 and out == mark):
                ok = False
                diag.append("[%s] %s:%s rc=%s got=%r err=%s"
                            % (repo_rel or "root", br, rel, rc, out[:60], err.strip()[:80]))
        if ok:
            return True, "; ".join(diag) or "已落盘"
        write_ticket_files(lane)
        time.sleep(5.0)
    return False, "; ".join(diag) or "（无诊断）"


def create_ticket(tk, tid, title, proj):
    """正规入口开票（返回体只作辅证，KI-067：异常/拒收=红灯点名，不作成功判据）。"""
    res, err = None, ""
    try:
        # 260928 修（本场景 T0 在「缺省策略」下必红的真因）：裸入口 op=create 不声明调用方
        # 项目身份 ⇒ 260925-08 起策略缺省=拒收（跨项目闸 refuse），直接
        # `ValueError: Temporal 拒绝: 调用方项目身份未声明`。在跑批上下文里它能过，只因执行器
        # 给子进程 setdefault(SANDBAR_UNDECLARED_POLICY, "record")（过渡期旋钮）——那是**偶然
        # 放行**，旋钮退役即红（KI-142/KI-151 同族）。按「身份只盖章不许自认」的正规口径显式
        # 声明本场景的夹具项目（=目标票所属项目，同项目调用）。
        res = tk.run({"op": "create", "project": proj, "workflow": "dev-lane",
                      "title": title, "write_set": list(WS), "id": tid,
                      "caller_project": proj})
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:240])
    return (isinstance(res, dict) and not err), res, err


def show_meta(tk, tid, deadline_s=30.0):
    """ticket show 读面轮询（公开取证面），返回 meta dict 或 None。"""
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
    if os.environ.get("SANDBAR_UT_DEBUG"):
        print("DEBUG show(%s) 最后读面=%r" % (tid, str(last)[:200]), flush=True)
    return None


def show_json(meta):
    try:
        return json.dumps(meta, ensure_ascii=False, default=str)
    except Exception:
        return str(meta)


def at_merge_gate(tk, tid):
    m = show_meta(tk, tid, 4.0)
    return bool(m) and m.get("stage") == "merge" and m.get("stage_state") == "awaiting-human"


def main_count(repo):
    return int(git("rev-list", "--count", "main", cwd=repo).strip())


def teardown_warn_row(meta):
    """公开读面的「泳道拆除告警」行原文（meta.log 优先；缺则从整体读面抓取）。"""
    for row in (meta.get("log") or []):
        txt = str(row.get("note") if isinstance(row, dict) else row)
        if "泳道拆除告警" in txt:
            return txt
    sj = show_json(meta)
    i = sj.find("泳道拆除告警")
    return sj[i:i + 500] if i >= 0 else ""


def run_leg(py, tk):
    """唯一子用例：开票→真 worker→物化→驱动到 merge 门→注入成员仓 lock→签字→收口终态。"""
    root = Path(FIX["mixed"])
    lane_rel, _ = shared.default_lane_paths(TICKET)
    lane = root / lane_rel
    manifest = shared.multi_manifest_path(lane)  # 引擎真写点（协调目录解析位，t260914-01）
    base = {"root": main_count(root), "repo_a": main_count(root / "repo_a"),
            "repo_b": main_count(root / "repo_b")}
    holder = []
    member_branch = ""
    injected = False
    try:
        ok, res, err = create_ticket(tk, TICKET, "拆道残留可见性 %s" % TICKET, PROJ)
        check("T0 正规入口 ticket.py create 受理（辅证，KI-067）", ok,
              "res=%r err=%s" % (res if isinstance(res, dict) else str(res)[:160], err))
        if not ok:
            return
        holder.append((TICKET, start_worker(py, TICKET)))
        got_disk = wait_until(lambda: manifest.is_file() and (lane / "repo_a").is_dir(),
                              DISK_DEADLINE, interval=1.0)
        check("T1 泳道逐仓物化（清单 + 子仓树在位）", got_disk, "lane=%s" % lane)
        if not got_disk:
            return
        write_ticket_files(lane)
        seed_arbitrate_pass(lane, TICKET)   # 早置：静静等幂等缓存消费（不得排在长等待之后）
        detail = shared.build_repo_worktrees(root, WS, lane_rel.rsplit("/", 1)[-1])
        got_commit, commit_diag = ensure_committed(lane, root, detail)
        check("T1' 票内写集文件已落各树 lane 分支（settle 代落盘）", got_commit, commit_diag)
        member_branch = {str(e["repo"]): str(e["branch"]) for e in detail}.get("repo_a", "")
        at_gate = wait_until(lambda: at_merge_gate(tk, TICKET), GATE_DEADLINE)
        if not at_gate:
            _m = show_meta(tk, TICKET, 4.0)
            # 260928 加（报错必须精确，KI-153 教训）：T2 超时原来只说「无读面」，说不出
            # **链停在哪一段**——复跑一次 12 分钟却拿不到可归因证据。改为把 worker 日志尾
            # 与最后读面一起落进断言证据（日志本就在 tmp 里，只是从没被读出来过）。
            _wt = ""
            try:
                _wl = tmp / ("worker-%s.log" % TICKET)
                if _wl.is_file():
                    _wt = _wl.read_text(encoding="utf-8", errors="replace")[-1200:]
            except Exception as _e:  # noqa: BLE001
                _wt = "（worker 日志不可读：%s）" % str(_e)[:80]
            check("T2 全链推进到 merge 人审挂起（stage=merge awaiting-human）", False,
                  "show=%s ｜ worker 日志尾=%s"
                  % ((show_json(_m)[:400] if isinstance(_m, dict) else "无读面"), _wt.replace("\n", " ⏎ ")))
            return
        check("T2 全链推进到 merge 人审挂起（stage=merge awaiting-human）", True)
        # ---- 注入：成员仓 repo_a 的泳道工作树 lock（真实 git 态，非产品改动）----
        rc = git_ok("worktree", "lock", str(lane / "repo_a"), cwd=root / "repo_a")[0]
        injected = rc == 0
        check("T3 注入前置：成员仓泳道工作树 lock 成功（拆道将真实失败且不删目录）",
              injected, "rc=%s" % rc)
        sres = None
        try:
            sres = tk.run({"op": "sign", "id": TICKET, "gate": "merge",
                           "by": "integration-ut", "decision": "approve",
                           # 同上：签字也是 gated op，须声明调用方项目身份
                           "caller_project": PROJ,
                           "note": "ut 拆道可见性守卫签字"})
        except Exception as e:
            sres = "%s: %s" % (type(e).__name__, str(e)[:200])
        check("T4 merge 人审签字受理（正规签字面，辅证）",
              isinstance(sres, dict), "res=%r" % (sres if isinstance(sres, dict) else str(sres)[:200],))
        closed = wait_until(
            lambda: (show_meta(tk, TICKET, 4.0) or {}).get("status") == "closed",
            GATE_DEADLINE)
        m = show_meta(tk, TICKET)
        check("T5 清理失败不阻断收口：workflow 走到 closed", closed,
              "show=%s" % show_json(m)[:400])
        if not closed:
            return
        row = teardown_warn_row(m) if isinstance(m, dict) else ""
        check("T6 残留可见（验收 C：不得静默成功）：公开读面有「泳道拆除告警」行",
              bool(row), "show=%s" % show_json(m)[:500])
        check("T7 该行逐仓点名失败仓 repo_a（不再笼统一条）",
              names_repo(row, "repo_a"), "row=%r" % row[:300])
        check("T8 点名段带失败指示（说清哪个检查失败）",
              any(k in row for k in ("失败", "locked", "锁定")),
              "seg=%r" % segment_of(row, "repo_a"))
        check("T9 一仓清不掉不拖停其它仓：根仓三清（分支已删 + 注册已清 + 容器目录不存在）",
              branch_lane_gone(root) and not worktree_has(root, lane)
              and not Path(lane).exists(),
              "root_branches=%r" % git_ok("branch", "--list", "lane/*", cwd=root)[1][:160])
        check("T10 注入仓残留在场（负锁非空转：注入确实让清理失败）",
              worktree_has(root / "repo_a", lane / "repo_a")
              and (branch_lane_present(root / "repo_a", member_branch) if member_branch else False),
              "repo_a 注册=%s 分支=%r" % (
                  worktree_has(root / "repo_a", lane / "repo_a"),
                  git_ok("branch", "--list", "lane/*", cwd=root / "repo_a")[1][:160]))
        ca, cb = main_count(root / "repo_a"), main_count(root / "repo_b")
        check("T11 不串仓：repo_b main 提交数不变（基线 %d）" % base["repo_b"],
              cb == base["repo_b"], "base=%d got=%d" % (base["repo_b"], cb))
        check("T12 同源判定组合证据（验收 D）：merge 逐仓落账的仓集合（根+repo_a 各 +1）"
              "与拆道逐仓点名的仓集合一致（repo_a 被点名、根遭清理）",
              main_count(root) == base["root"] + 1 and ca == base["repo_a"] + 1
              and names_repo(row, "repo_a") and branch_lane_gone(root),
              "base=%r got root=%d a=%d" % (base, main_count(root), ca))
    finally:
        # 注入回收：路径可能已随容器目录被删，unlock 容忍失败（注册仍在也能解）
        if injected:
            git_ok("worktree", "unlock", str(lane / "repo_a"), cwd=root / "repo_a")
        for label, w in holder:
            stop_worker(w, label)


def stage_legs():
    """台面子用例：隔离台一次起台（两子用例复用同款预算；本场景单子用例，台面生命周期覆盖全程）。"""

    class _Fail:
        def bail(self, msg, code):
            print("ENV_FAIL %s" % msg, flush=True)
            raise SystemExit(2)

    sys.path.insert(0, str(INTEG))
    sys.path.insert(0, str(INTEG / "t260904-02"))
    from lib_gate import require_bench
    bench = require_bench(_Fail())
    py = bench.poc_python()
    proj = STAGE_PROJ
    saved = {k: os.environ.get(k) for k in
             ("SANDBAR_PROJECTS_DIR", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}
    os.environ["SANDBAR_STAGE_LEASE_TTL_S"] = "1800"
    import stage_docker as _sd
    stage = None
    try:
        stage = _sd.do_up_public(proj, ["temporal"],
                                 {"namespace": proj, "keep": True},
                                 _sd.DEFAULT_TIMEOUT, keep=True)
        if not stage.get("sa_registered"):
            try:
                _sd.do_down(proj)
            except Exception:
                pass
            env_fail("docker 舞台 namespace/SA 未注册（%s）——ticket 场景需要 ProjectKey SA"
                     % stage.get("sa_note"))
            return 2
        os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
        os.environ["SANDBAR_NAMESPACE"] = stage["namespace"]
        os.environ["SANDBAR_PROJECTS_DIR"] = FIX["regroot"]
        tk = load_ticket_module()
        run_leg(py, tk)
        return 0
    except _sd.StageError as e:
        env_fail("docker 舞台 up 失败（%s）：%s" % (e.kind, e))
        return 2
    finally:
        try:
            _sd.do_down(proj)
        except Exception as e:
            env_fail("拆台失败（残留需人工清理）：%s" % e)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


try:
    # ---------- stdlib 子用例：夹具自证（恒跑，隔离台缺席也可判夹具漂移） ----------
    proj_root = build_project(tmp, "mixed")["root"]
    check("S0 夹具自证（stdlib 子用例）：混合形态检出、子仓齐全",
          shared.is_multi_repo_layout(proj_root)
          and (proj_root / "repo_a" / ".git").exists()
          and (proj_root / "repo_b" / ".git").exists(),
          "root=%s" % proj_root)
    try:
        import temporalio  # noqa: F401
        has_temporalio = True
    except ImportError:
        has_temporalio = False
    if not has_temporalio:
        env_fail("temporalio 缺失——真链子用例（create→真 worker→merge→拆道→残留可见性）"
                 "无 stdlib 替代；arbitrate/merge 期 venv 环境必须实跑")
    regroot = Path(tmp) / "reg"
    regdir = regroot / PROJ
    regdir.mkdir(parents=True)
    (regdir / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: UT 拆道 13\n    dirs:\n      - %s\n"
        % (PROJ, proj_root), "utf-8")
    FIX.update({"mixed": str(proj_root), "regroot": str(regroot)})
    if has_temporalio:
        stage_legs()
finally:
    if not os.environ.get("SANDBAR_UT_DEBUG"):
        rmtree(tmp)
    else:
        print("DEBUG tmp 保留：%s" % tmp, flush=True)
sys.exit(summary())
