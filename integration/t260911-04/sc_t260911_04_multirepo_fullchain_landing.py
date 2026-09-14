#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260911-04 场景：全链多仓旅程守卫——正规入口→真 worker→merge→成员仓 main 落仓
（补 KI-071 那一跳，灰盒 L3）。

intent（守护的用户可感知行为/合同，与相邻场景族分界=三维对齐）：
- **本场景唯一新 intent**：正规入口 ticket.py create → 真专属 worker 跑
  DevLaneWorkflow（桩脑自动过段，零模型调用）→ merge 人审签字 → merge 逐仓
  squash → **main 落仓终态** + 泳道拆除零残留。
- 与 t260907-06① journey 差在：彼=直调 activity、落**分支**；本=全链、落 main。
- 与 t260907-06② merge_gate 差在：彼=直调 merge_check/merge（KI-063 同族冒充
  全链）；本=零 activity 直调，全程走 workflow。
- 与 t260907-06③ failclosed 差在：彼=**prepare 时点**注入、直调；本=**merge
  时点**注入（删泳道清单）×全链形态。
- 与 t260910-08 差在：彼止步泳道磁盘物化、不到 merge；本走到 merge 落仓与拆道。
  （畸形明细两层互不冒充 intent 归 t260910-08，本场景不带——带了即 intent 重复。）

断言（全部落磁盘/git 终态，依 docs/testing-guide.md 260910 节「断言落终态」，
KI-067 辅证纪律：create/show 输出只作辅证，真值锚磁盘与 git）：
- T3a 成员仓 repo_a main 上恰多一个该票 squash 提交（rev-list 计数=基线+1，
  lane/* 分支已删）；
- T3b 内容正确且不串仓：repo_a/src/a.py 在 main 终态含票内写入内容；
  repo_b main 零新提交；
- T3c 根仓 main 同样恰+1、docs/root.md 落位；
- T3d 泳道拆除零残留：git worktree list 两仓均无 lane 路径 + .lane 目录不存在；
- T3e ticket show 终态非 blocked（收口链未断，辅证）；
- T4 反向腿（保险丝B 终态咬合）：同链真开票，merge 人审挂起时删泳道内
  清单 repo_worktrees.json（落点＝引擎真写点 shared.multi_manifest_path；夹具级磁盘注入=缺明细形态，
  不改产品，注入前置带在场/已删双断言防空转）→ 签字后
  merge/merge_check 红灯拦住（点名「未逐物化/保险丝B」）、workflow blocked，
  **三仓 main 提交数全部不变**——绝不静默单仓收口。

被借实现故障模式取舍清单（t260910-08 手法）：①KI-067 辅证纪律【带】；②worker
全终态回收（TERM 20s→kill 兜底计红，holder+finally 全腿覆盖）【带】；③ENV_FAIL
三态（temporalio/隔离台缺失=exit 2 点名，真链腿无 stdlib 替代）【带】；④CWD/env
敏感收口（env_for 剥 SANDBAR_*、台面 env 进程内钉入 finally 恢复）【带】；
⑤畸形明细两层互不冒充【不带，见 intent 分界】。

实现注记（桩脑写文件窗口）：SANDBAR_AGENT_STUB=1 的桩段只回执不写内容（
agent_activities L1110 起），SANDBAR_AGENT_STUB_DELAY_SEC 给每段开确定性在飞窗；
场景在泳道物化后、首段 settle 前把票内文件写进泳道逐仓工作区，worker settle
代落盘提交（agent 沙箱写不了真 .git 的既有语义）——文件内容落泳道磁盘是夹具
行为，提交走全链 settle，不旁路。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
docker/隔离台/temporalio 缺席 = ENV_FAIL exit 2 点名。
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
sys.path.insert(0, str(HERE))
from lib_t260911_04 import (  # noqa: E402
    check, env_fail, summary, git, git_ok, wait_until,
    main_count, show_json, build_mixed_project,
)

# 红线桩：绝不触生产 7233/8233/3099——shared 在 import 期读 TARGET_HOST，先钉
# 不可达桩再 import（stdlib 腿零连接；台面腿由隔离台 env 覆盖）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)
sys.path.insert(0, str(POC))
import shared  # noqa: E402

TICKET_MAIN = "t26091104fl"     # 主腿：全链到 merge 落仓
TICKET_FUSE = "t26091104fb"     # 反向腿：清单缺失注入（保险丝B 咬合）
WS = ["docs/root.md", "repo_a/src/a.py"]
PROJ = "utfl11"
PROJ_FUSE = "utfl11b"
# 桩段在飞窗：给场景写票内文件留确定性窗口（每段 6s，物化完成后立刻写入）
STUB_DELAY_SEC = "10"
DISK_DEADLINE = 150.0           # 真链磁盘物化等待上限
GATE_DEADLINE = 480.0           # merge 人审挂起/收口/blocked 等待上限
ROOT_MARK = "root changed by ticket\n"
MEMBER_MARK = "member a changed by ticket\n"

# tmp 根落仓内 .sandbar/（引擎工作区运行时区，场景收尾 rmtree 自清；不落系统
# /var/folders——headless 沙箱对仓外 tmp 的 git 子进程有过拦截实证）
_WS = REPO / ".sandbar"
_WS.mkdir(parents=True, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="t260911-04-fl-", dir=str(_WS))
FIXTURES = {}


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
        "_t26091104_ticket", str(REPO / "server" / "tools" / "ticket.py"))
    tk = importlib.util.module_from_spec(spec)
    sys.modules["_t26091104_ticket"] = tk
    spec.loader.exec_module(tk)
    return tk


def start_worker(py, tid):
    """拉本票专属 worker（桩脑：自动过段零模型调用 + 在飞窗；watch 快档）。"""
    extra = {
        "SANDBAR_TASK_QUEUES": shared.ticket_task_queue(tid),
        "SANDBAR_WATCH_WORKFLOW": tid,
        "SANDBAR_WATCH_INTERVAL_SEC": "4",
        "SANDBAR_AGENT_STUB": "1",
        "SANDBAR_AGENT_STUB_DELAY_SEC": STUB_DELAY_SEC,
        # 桩段如实申报票内文件（KI-049 门②注记不空转、write_set 刷新面不失真；
        # 真实内容落盘=夹具写入+join settle 代提交，见模块头实现注记）
        "SANDBAR_AGENT_STUB_FILES": ",".join(WS),
        "SANDBAR_SUGGEST_STUB": "ok",
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    log = open(os.path.join(tmp, "worker-%s.log" % tid), "w")
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
    """预置仲裁 verdict=pass（t260908-01 同款先例：桩大脑 summary 天然缺 verdict=，
    3 次格式纠正轮即 blocked at arbitrate——arbitrate 结果幂等缓存路径消费预置
    回执）。点目录 naming-compat：新道 .sandbar 优先、旧名 .suyou 粘性回落。"""
    sdir = lane / ".sandbar"
    if not sdir.is_dir() and (lane / ".suyou").is_dir():  # naming-compat：旧点目录回落判定
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
    payload = json.dumps({
        "status": "ok",
        "summary": "集成测试三态判定：verdict=pass（全链守卫预置，走幂等缓存路径）",
        "report": "[seeded] verdict=pass（t260911-04 全链守卫）",
        "deliverables": [], "files_changed": [],
        "evidence": "seeded by sc_t260911_04_multirepo_fullchain_landing"})
    (sdir / ("stage_arbitrate_gen%d.json" % gen)).write_text(payload, "utf-8")


def write_ticket_files(lane):
    """把票内写集文件写进泳道逐仓工作区（桩段在飞窗内的夹具行为；提交走全链
    settle 代落盘，不旁路）。"""
    (lane / "docs" / "root.md").write_text(ROOT_MARK, encoding="utf-8")
    (lane / "repo_a" / "src" / "a.py").write_text(MEMBER_MARK, encoding="utf-8")
    # 预置仲裁回执（t260908-01 lib_ki061 同族「场景预设判定」手法，走幂等读面）：
    # SANDBAR_AGENT_STUB 桩回执无 verdict= 标记，仲裁段 3 轮格式纠正后必 blocked
    #（dev_lane L1532-1538）——桩链结构性过不了仲裁边。夹具级预置 verdict=pass
    # 模拟「integration 仲裁判过」，产品零改动；settle_on_cache 路径照常落盘。
    arb = lane / ".sandbar" / "stage_arbitrate_gen0.json"
    arb.parent.mkdir(parents=True, exist_ok=True)
    arb.write_text(json.dumps({
        "status": "ok",
        "summary": "verdict=pass（场景预置：机械集成测试基线内全绿，桩链过仲裁边）",
        "report": "[fixture] 预置仲裁判定（t260911-04 守卫场景夹具），非产品改动",
        "deliverables": [], "files_changed": [], "files_changed_shape": "ok",
        "evidence": "preset by sc_t260911_04_multirepo_fullchain_landing",
    }, ensure_ascii=False), encoding="utf-8")


def _branch_has(repo, branch, rel, mark):
    rc, out, _ = git_ok("show", "%s:%s" % (branch, rel), cwd=repo)
    return rc == 0 and out == mark


def ensure_committed(lane, root, detail, deadline_s=180.0):
    """确保票内写集文件被全链 settle 落到各树 lane 分支（确定性：写→查→没吃到
    再写——桩段每段都有 settle，后续段必然补落；deadline 内未落=False）。"""
    marks = {"": ("docs/root.md", ROOT_MARK), "repo_a": ("src/a.py", MEMBER_MARK)}
    brs = {str(e["repo"]): str(e["branch"]) for e in detail}
    end = time.time() + deadline_s
    while time.time() < end:
        ok = True
        for repo_rel, (rel, mark) in marks.items():
            repo = root / repo_rel if repo_rel else root
            if not _branch_has(repo, brs[repo_rel], rel, mark):
                ok = False
        if ok:
            return True
        write_ticket_files(lane)
        time.sleep(5.0)
    return False


def create_ticket(tk, tid, title, proj=PROJ):
    """正规入口开票（辅证返回体，KI-067：异常/拒收=红灯点名，不作成功判据）。"""
    res, err = None, ""
    try:
        res = tk.run({"op": "create", "project": proj, "workflow": "dev-lane",
                      "title": title, "write_set": list(WS), "id": tid})
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:240])
    ok = isinstance(res, dict) and not err
    return ok, res, err


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


def at_merge_gate(tk, tid):
    """merge 人审挂起判定（公开读面：stage=merge + stage_state=awaiting-human）。"""
    m = show_meta(tk, tid, 4.0)
    return bool(m) and m.get("stage") == "merge" \
        and m.get("stage_state") == "awaiting-human"


def lane_gone(lane):
    return not Path(lane).exists()


def branch_lane_gone(repo):
    rc, out, _ = git_ok("branch", "--list", "lane/*", cwd=repo)
    return rc == 0 and not out.strip()


def worktree_clean(repo, lane_resolved):
    rc, out, _ = git_ok("worktree", "list", "--porcelain", cwd=repo)
    return rc == 0 and lane_resolved not in out


def git_show_main(repo, rel):
    return git("show", "main:%s" % rel, cwd=repo)


def run_leg(py, tk, tid, mixed, holder, fuse=False, proj=PROJ):
    """一条全链腿：开票→真 worker→物化→票内文件→驱动到门→（注入）→签字→终态。
    返回 dict(meta/lane/基线计数)。"""
    root = mixed
    lane_rel, _ = shared.default_lane_paths(tid)
    lane = root / lane_rel
    manifest = shared.multi_manifest_path(lane)  # 引擎真写点（协调目录解析位，t260914-01）
    base = {"root": main_count(root), "repo_a": main_count(root / "repo_a"),
            "repo_b": main_count(root / "repo_b")}

    ok, res, err = create_ticket(tk, tid, "全链多仓落仓 %s" % tid, proj)
    check("%s T1 正规入口 ticket.py create 受理（辅证，KI-067）" % tid, ok,
          "res=%r err=%s" % (res if isinstance(res, dict) else str(res)[:160], err))
    if not ok:
        return {"aborted": True, "base": base, "lane": lane, "manifest": manifest}

    holder.append((tid, start_worker(py, tid)))

    got_disk = wait_until(lambda: manifest.is_file() and (lane / "repo_a").is_dir(),
                          DISK_DEADLINE, interval=1.0)
    check("%s T2a 泳道逐仓物化（清单+子仓树在位）" % tid, got_disk,
          "lane=%s" % lane)
    if got_disk:
        # 树一在位立即写票内文件（最早 settle=首段 agent 步后，merge_check 在
        # 链尾——早写保证 commit 远在 merge_check 前落齐），随后 ensure 循环兜底
        write_ticket_files(lane)
        # 写票内文件并确保被全链 settle 落到各树 lane 分支（写→查→补写循环，
        # 不赌单次在飞窗——桩段每段都有 settle，后续段必然补落）
        wname = lane_rel.rsplit("/", 1)[-1]
        detail = shared.build_repo_worktrees(root, WS, wname)
        got_commit = ensure_committed(lane, root, detail)
        check("%s T2a' 票内写集文件已落各树 lane 分支（settle 代落盘）" % tid,
              got_commit, "lane=%s" % lane)
        # 预置仲裁 verdict=pass（早置文件静静等幂等缓存消费，t260908-01 同款）
        seed_arbitrate_pass(lane, tid)

    at_gate = wait_until(lambda: at_merge_gate(tk, tid), GATE_DEADLINE)
    _m = show_meta(tk, tid, 4.0) if not at_gate else None
    _dbg = ""
    if _m is not None:
        _tl = (_m.get("timeline") or [])[-3:]
        _dbg = "stage=%r state=%r pulse=%r timeline_tail=%s" % (
            _m.get("stage"), _m.get("stage_state"), _m.get("pulse"),
            show_json(_tl)[:500])
    check("%s T2b 全链推进到 merge 人审挂起（stage=merge awaiting-human）" % tid,
          at_gate, _dbg or "ok")

    if fuse and at_gate:
        # merge 时点夹具注入：删泳道逐仓清单（缺明细形态=单仓回落）——不改产品，
        # 保险丝B 应在 merge/merge_check 红灯拦住。清单路径=引擎真写点（t260914-01），
        # 注入前置带非空转负锁：删前确在场、删后确不在（否则注入空转=保险丝腿失效）。
        check("%s T4 注入前置：清单确在场" % tid, manifest.is_file(),
              "manifest=%s" % manifest)
        try:
            manifest.unlink()
        except OSError as e:
            check("%s T4 注入前置：清单删除成功" % tid, False, str(e))
        check("%s T4 注入前置：清单确已删除（负锁非空转）" % tid, not manifest.is_file(),
              "manifest=%s" % manifest)

    if at_gate:
        sres, serr = None, ""
        try:
            sres = tk.run({"op": "sign", "id": tid, "gate": "merge",
                           "by": "integration-ut", "decision": "approve",
                           "note": "ut 全链守卫签字"})
        except Exception as e:
            serr = "%s: %s" % (type(e).__name__, str(e)[:200])
        check("%s T2c merge 人审签字受理（正规签字面，辅证）" % tid,
              isinstance(sres, dict) and not serr,
              "res=%r err=%s" % (sres, serr))

    if fuse:
        blocked = wait_until(
            lambda: (show_meta(tk, tid, 4.0) or {}).get("stage_state") == "blocked",
            GATE_DEADLINE)
        m = show_meta(tk, tid)
        sj = show_json(m)
        check("%s T4a 注入后必须红灯拦住：workflow blocked（绝不放行收口）" % tid,
              blocked and isinstance(m, dict), "show=%s" % sj[:260])
        check("%s T4b 红灯点名保险丝B（未逐仓物化文案在公开读面可咬合）" % tid,
              ("未逐仓物化" in sj) and ("保险丝B" in sj),
              "show=%s" % sj[:400])
        ca = main_count(root / "repo_a")
        cb = main_count(root / "repo_b")
        cr = main_count(root)
        check("%s T4c 成员仓 main 提交数不变（绝不静默单仓收口）" % tid,
              ca == base["repo_a"] and cb == base["repo_b"] and cr == base["root"],
              "base=%r got root=%d a=%d b=%d" % (base, cr, ca, cb))
    else:
        # 等 workflow 终态（closed=merge 落账后的收口终点）；拆道是否零残留交
        # T3d 严格断——teardown 吞警告/多仓成员仓无清理路径属产品缺陷面，不掩盖
        closed = wait_until(
            lambda: (show_meta(tk, tid, 4.0) or {}).get("status") == "closed",
            GATE_DEADLINE)
        _m3 = None if closed else show_meta(tk, tid, 4.0)
        _dbg3 = ""
        if _m3 is not None:
            _dbg3 = "stage=%r state=%r status=%r tail=%s" % (
                _m3.get("stage"), _m3.get("stage_state"), _m3.get("status"),
                show_json((_m3.get("timeline") or [])[-3:])[:600])
        check("%s T3pre merge→归档收口完成（workflow closed）" % tid, closed,
              _dbg3 or "ok")
        if closed:
            lane_resolved = str(Path(lane).resolve())
            # T3a 成员仓恰多一个 squash 提交 + lane 分支已删
            ca = main_count(root / "repo_a")
            check("%s T3a 成员仓 main 恰多一个该票 squash 提交（基线+1）" % tid,
                  ca == base["repo_a"] + 1,
                  "base=%d got=%d" % (base["repo_a"], ca))
            check("%s T3a' 成员仓 lane/* 分支已删（拆道三清）" % tid,
                  branch_lane_gone(root / "repo_a"),
                  "branches=%r" % git_ok("branch", "--list", "lane/*",
                                         cwd=root / "repo_a")[1][:120])
            # T3b 内容正确 + 不串仓
            content_ok = False
            try:
                content_ok = git_show_main(root / "repo_a", "src/a.py") == MEMBER_MARK
            except Exception:
                pass
            check("%s T3b 成员仓 main 终态含票内写入内容" % tid, content_ok,
                  "expect=%r" % MEMBER_MARK[:40])
            cb = main_count(root / "repo_b")
            check("%s T3b' 零串仓：repo_b main 无该票提交（基线不变）" % tid,
                  cb == base["repo_b"], "base=%d got=%d" % (base["repo_b"], cb))
            # T3c 根仓落位
            cr = main_count(root)
            root_content_ok = False
            try:
                root_content_ok = git_show_main(root, "docs/root.md") == ROOT_MARK
            except Exception:
                pass
            check("%s T3c 根仓 main 恰+1 且内容落位" % tid,
                  cr == base["root"] + 1 and root_content_ok,
                  "base=%d got=%d content_ok=%s" % (base["root"], cr, root_content_ok))
            # T3d 拆道零残留
            check("%s T3d 泳道零残留：两仓 worktree 列表均无 lane 路径" % tid,
                  worktree_clean(root, lane_resolved)
                  and worktree_clean(root / "repo_a", lane_resolved),
                  "lane=%s" % lane_resolved)
            check("%s T3d' 根仓 lane/* 分支已删" % tid,
                  branch_lane_gone(root), "branches=%r"
                  % git_ok("branch", "--list", "lane/*", cwd=root)[1][:120])
            # T3d-目录（仲裁段补回）：工单验收 d 明列「git worktree 列表/目录」两面，
            # T3pre 改断 workflow closed 后目录面断言丢失=覆盖收窄，补回（不弱化）。
            check("%s T3d-目录 泳道目录不存在（拆道目录面）" % tid,
                  not Path(lane_resolved).exists(), "lane=%s" % lane_resolved)
            # T3e 收口链未断（辅证）
            m = show_meta(tk, tid)
            check("%s T3e ticket show 终态非 blocked（收口链未断，辅证）" % tid,
                  isinstance(m, dict) and m.get("stage_state") != "blocked",
                  "show=%s" % show_json(m)[:220])
    return {"aborted": False, "base": base, "lane": lane, "manifest": manifest}


def stage_legs():
    """台面腿：隔离台一次起台两腿复用（900s 预算），全程 holder+finally 回收。"""

    class _Fail:
        def bail(self, msg, code):
            print("ENV_FAIL %s" % msg, flush=True)
            raise SystemExit(2)

    sys.path.insert(0, str(INTEG))
    sys.path.insert(0, str(INTEG / "t260904-02"))
    from lib_gate import require_bench, require_stage, stage_down
    bench = require_bench(_Fail())
    py = bench.poc_python()
    proj = "t26091104-fl"
    holder = []          # (label, proc)——凡 spawn 必入册，finally 逐个回收
    stage = None
    saved = {k: os.environ.get(k) for k in
             ("SANDBAR_PROJECTS_DIR", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}

    # 常驻租约台（keep=True）：hold 腿不随锚/沙箱束死——受限沙箱曾实证短命 hold
    # 心跳被回收、宿主端口被他台重绑；常驻租约=舞台在整个两腿窗口内确定存活，
    # 用毕显式 do_down（finally）。TTL 同步给足（两腿约 8–10 分钟）。
    os.environ["SANDBAR_STAGE_LEASE_TTL_S"] = "1800"
    sys.path.insert(0, str(INTEG))
    import stage_docker as _sd
    try:
        stage = _sd.do_up_public(proj, ["temporal"],
                                 {"namespace": proj, "keep": True},
                                 _sd.DEFAULT_TIMEOUT, keep=True)
        if not stage.get("sa_registered"):
            try:
                _sd.do_down(proj)
            except Exception:
                pass
            env_fail("docker 舞台 namespace/SA 未注册（%s）——ticket 场景需要 "
                     "ProjectKey SA，环境缺供" % stage.get("sa_note"))
            sys.exit(2)
    except _sd.StageError as e:
        env_fail("docker 舞台 up 失败（%s）：%s" % (e.kind, e))
        sys.exit(2)
    os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
    os.environ["SANDBAR_NAMESPACE"] = stage["namespace"]

    try:
            # 夹具与注册表已由台前构建（FIXTURES，t260910-08 同序：夹具先行、起台在后）
            mixed_main = Path(FIXTURES["mixed_main"])
            mixed_fuse = Path(FIXTURES["mixed_fuse"])
            check("S1 夹具自证：混合形态×2=根仓+repo_a+repo_b（dengzhufpv 形态）",
                  shared.is_multi_repo_layout(mixed_main)
                  and shared.is_multi_repo_layout(mixed_fuse),
                  "mixed=%s/%s" % (mixed_main, mixed_fuse))
            os.environ["SANDBAR_PROJECTS_DIR"] = FIXTURES["regroot"]

            tk = load_ticket_module()
            # 主腿 T1–T3：全链到 merge → main 落仓 → 拆道零残留
            run_leg(py, tk, TICKET_MAIN, mixed_main, holder, fuse=False)
            # 反向腿 T4：merge 时点删清单注入 → 保险丝B 红灯咬合、绝不静默收口
            run_leg(py, tk, TICKET_FUSE, mixed_fuse, holder, fuse=True, proj=PROJ_FUSE)
            return 0
    finally:
        for label, w in holder:
            stop_worker(w, label + "（收尾回收）")
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
    # ---------- stdlib 腿：夹具自证（恒跑，隔离台缺席也可判夹具漂移） ----------
    # 夹具只建一次（同一 tmp 二次 build=重复 commit 落空，S0/S1 共用同一份）
    mixed = build_mixed_project(tmp)
    check("S0 夹具自证（stdlib 腿）：混合形态检出、子仓齐全",
          shared.is_multi_repo_layout(mixed)
          and (mixed / "repo_a" / ".git").exists()
          and (mixed / "repo_b" / ".git").exists(),
          "mixed=%s" % mixed)
    try:
        import temporalio  # noqa: F401
        has_temporalio = True
    except ImportError:
        has_temporalio = False
    if not has_temporalio:
        env_fail("temporalio 缺失——真链腿（正规入口 create→真 worker→merge→main 落仓）"
                 "无 stdlib 替代；arbitrate/merge 期 venv 环境必须实跑")
    # 夹具已在 S0 台前建好一份；两腿各一份独立夹具 + 各自项目键（前腿 merge 落
    # main 后，共用仓会让后腿基线内容恰好相同 → settle「已干净」0-commit 假象）
    mixed_fuse = build_mixed_project(tmp, name="mixed-fuse")
    regroot = Path(tmp) / "reg"
    for key, mroot in ((PROJ, mixed), (PROJ_FUSE, mixed_fuse)):
        regdir = regroot / key
        regdir.mkdir(parents=True)
        (regdir / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: %s\n    name: UT 全链 11\n    dirs:\n      - %s\n"
            % (key, mroot), "utf-8")
    FIXTURES = {"mixed_main": str(mixed), "mixed_fuse": str(mixed_fuse),
                "regroot": str(regroot)}
    stage_rc = 0
    if has_temporalio:
        stage_rc = stage_legs()
    if stage_rc == 2:
        env_fail("docker/隔离台缺席：全链腿不可执行——本场景全靠真链路无 stdlib 替代腿；"
                 "arbitrate/merge 期隔离台必须全绿")
finally:
    if not os.environ.get("SANDBAR_UT_DEBUG"):
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print("DEBUG tmp 保留：%s" % tmp, flush=True)
sys.exit(summary())
