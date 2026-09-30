#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_ops_offline.py —— `server/tools/engine_ops.py` 的离线面（宿主 260930 当面令）。

intent（守护的用户可感知行为）：**推票前「谁在服务 / 吃哪份代码 / 漂没漂」三问必须
离线也答得出来，且答不出时具名（不静默、不假绿）**。

场景构造（全在场景私有 tmp，零生产接触）：
  · 夹具仓：`main` 上一次提交（含 `server/engine/*.py`、`server/tools/verify_lane.py`）；
  · 泳道：`<夹具>/.lane/<tid>` 作为 branch `lane/<tid>` 的 worktree，钉在那一刻；
  · 之后 **main 再落一个引擎修 + 一个 .md**（⇒ 泳道落后、代码面漂移、文档面不告警）；
  · 一条**活进程**的 pid 写进夹具 `data/worker.pid`（测重启守卫的「活进程拒启」）；
  · Temporal 打到一个**死端口**（127.0.0.1:1）——依赖它的面必须**具名 ENV_FAIL**，
    不许静默 skip、不许假装验过。

判据：
  L1 `drift`（离线）= 告警退出 1，且逐条点名：泳道缺哪些**代码**文件（.md 单列不告警）、
     泳道 worker 是否 stale（指纹基准=旁车 meta 的 ts）、活 poller 数**不可得**要明说
     「不能证明恰好一颗 ⇒ 不许推票」；
  L2 `.md` 不误报：文档漂移进 `doc_files_in_main_not_in_lane` 而**不**进告警面；
  L3 `sync --dry-run` 只读：报出会并进来的文件，且**不动泳道**（HEAD 与 merge 提交数不变）；
  L4 `who`（Temporal 不可达）= 退出 2 + 具名原因（事件历史只有 server 有，绝不假装）；
  L5 `sync`（非 dry-run，Temporal 不可达）= 退出 2 + 具名原因（**不退化手写 git merge**）；
  L6 `restart --scope central`（夹具 pidfile 指向活进程）= 拒绝启动（退出 1）且具名 pid，
     且**没有**产生后台进程/日志（没 fork）——守卫先于一切；
  L7 `workers`（Temporal 不可达）= 队列 poller 面**不可得**要具名，且不得把「不可得」当作
     「0 颗」静默放过（本工具的 workers 在告警面里点名）。

三态：0=绿；1=被测红；2=环境红（git/python 缺件）。零生产接触：`--repo` 指向夹具仓、
`--host` 指死端口、pidfile/日志全在夹具 tmp；不碰 3099、不碰真仓 `.lane/`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TOOL = os.path.join(REPO, "server", "tools", "engine_ops.py")
PY = os.path.join(REPO, "server", "engine", ".venv", "bin", "python")
DEAD_HOST = "127.0.0.1:1"
TID = "t-offline-ops"
ENGINE_FILES = ("server/engine/agent_activities.py", "server/engine/dev_lane.py",
                "server/engine/light_lane.py", "server/engine/shared.py",
                "server/tools/verify_lane.py")


def sh(argv, cwd=None, timeout=120):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def git(args, cwd):
    return sh(["git", "-C", cwd] + list(args))


def run_tool(*args, repo=""):
    argv = [PY, TOOL]
    if repo:
        argv += ["--repo", repo]
    argv += list(args)
    p = subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=REPO)
    out = (p.stdout or "").strip()
    try:
        payload = json.loads(out) if out else {}
    except ValueError:
        payload = {"_raw": out[:400]}
    return p.returncode, payload, (p.stderr or "").strip()


class Fail:
    def __init__(self, title):
        self.title = title
        self.fails = []
        self.n = 0

    def check(self, cond, msg):
        self.n += 1
        print(("ok    " if cond else "FAIL  ") + msg, flush=True)
        if not cond:
            self.fails.append(msg)
        return bool(cond)

    def finish(self):
        print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (self.n - len(self.fails),
                                                           len(self.fails)), flush=True)
        if self.fails:
            print("FAIL  %s：%d 项断言未过（首因：%s）"
                  % (self.title, len(self.fails), self.fails[0]), flush=True)
            sys.exit(1)
        print("PASS  %s" % self.title, flush=True)
        sys.exit(0)


def build_fixture(tmp):
    """夹具仓 + 泳道（落后 main 一个引擎修）。返回 (repo, lane, files)。"""
    repo = os.path.join(tmp, "fixture")
    os.makedirs(repo)
    git(["init", "-q", "-b", "main"], repo)
    git(["config", "user.email", "ops@e2e.test"], repo)
    git(["config", "user.name", "engine-ops-e2e"], repo)
    for rel in ENGINE_FILES + ("server/engine/README.md",):
        fp = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("# fixture module %s\n" % rel)
    os.makedirs(os.path.join(repo, "server", "engine", "data"), exist_ok=True)
    git(["add", "-A"], repo)
    git(["commit", "-qm", "fixture baseline"], repo)
    lane = os.path.join(repo, ".lane", TID)
    os.makedirs(os.path.dirname(lane), exist_ok=True)
    rc, out = git(["worktree", "add", "-q", "-b", "lane/%s" % TID, lane], repo)
    if rc != 0:
        return None, None, "worktree add 失败：%s" % out[:200]
    # main 前进：一个引擎修（代码面）+ 一个说明（文档面，**不该**告警）
    with open(os.path.join(repo, "server", "engine", "light_lane.py"), "a",
              encoding="utf-8") as f:
        f.write("# main-side engine fix (must be synced into the lane before pushing)\n")
    with open(os.path.join(repo, "server", "engine", "README.md"), "a",
              encoding="utf-8") as f:
        f.write("doc-only change (must NOT raise a drift alert)\n")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "engine fix + doc change on main"], repo)
    return repo, lane, ""


def main():
    fail = Fail("engine_ops offline faces (host order 260930)")
    tmp = tempfile.mkdtemp(prefix="engine-ops-e2e-")
    procs = []
    try:
        try:
            py = PY if os.path.isfile(PY) else sys.executable
            rc, _ = sh(["git", "--version"])
            if rc != 0:
                raise RuntimeError("git 不可用")
        except Exception as e:  # noqa: BLE001
            print("ENV_FAIL: 环境缺件（%s）——exit 2" % e)
            return 2
        repo, lane, err = build_fixture(tmp)
        if repo is None:
            print("ENV_FAIL: 夹具构造失败（%s）——exit 2" % err)
            return 2
        # 夹具 data/worker.pid 指向一个**活**进程（测「活进程拒启」）
        sleeper = subprocess.Popen([py, "-c", "import time\nwhile True: time.sleep(0.2)"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(sleeper)
        pidfile = os.path.join(repo, "server", "engine", "data", "worker.pid")
        with open(pidfile, "w", encoding="utf-8") as f:
            f.write(str(sleeper.pid))
        # 旁车 meta：ts 设为 1 分钟前（指纹基准）
        with open(pidfile + ".meta", "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": 1, "pid": sleeper.pid, "repo_root": repo,
                                "ts": int(time.time()) - 60}))

        # ---------- L1/L2 drift：告警 + 逐条点名 + .md 不误报 ----------
        rc, d, _err = run_tool("drift", TID, "--host", DEAD_HOST, repo=repo)
        res = d.get("result") or {}
        fail.check(rc == 1, "L1 drift 有漂移 ⇒ 告警退出 1（实得 %r）" % rc)
        fail.check(res.get("verdict") == "drift", "L1 verdict=drift（实得 %r）"
                  % res.get("verdict"))
        code_files = res.get("engine_files_in_main_not_in_lane") or []
        fail.check("server/engine/light_lane.py" in code_files,
                   "L1 点名泳道缺的**代码**文件（实得 %r）" % code_files[:4])
        fail.check(res.get("behind_commits") in (1, 2),
                   "L1 报出落后提交数（实得 %r）" % res.get("behind_commits"))
        docs = res.get("doc_files_in_main_not_in_lane") or []
        fail.check("server/engine/README.md" in docs,
                   "L2 文档漂移单列（实得 %r）" % docs[:3])
        fail.check(all(not f.endswith(".md") for f in code_files),
                   "L2 **.md 不进漂移告警面**（实得 %r）" % code_files[:4])
        alerts = "；".join(res.get("alerts") or [])
        fail.check("已落 main 的引擎面文件" in alerts, "L1 告警人话点名（实得 %r）" % alerts[:120])
        fail.check("不可得" in alerts and "poller" in alerts,
                   "L1 Temporal 不可达 ⇒ 活 poller 数**具名不可得**并拦住推票（实得 %r）"
                   % alerts[-160:])

        # ---------- L3 sync --dry-run：只读（不动泳道） ----------
        _rc, head0 = git(["rev-parse", "HEAD"], lane)
        _rc, cnt0 = git(["rev-list", "--count", "HEAD"], lane)
        rc, sres, _err = run_tool("sync", TID, "--dry-run", "--host", DEAD_HOST, repo=repo)
        r = sres.get("result") or {}
        fail.check(rc == 0 and r.get("dry_run") is True,
                   "L3 sync --dry-run 正常返回（rc=%r）" % rc)
        fail.check("server/engine/light_lane.py" in (r.get("engine_files_incoming") or []),
                   "L3 dry-run 报出会并进来的引擎文件（实得 %r）"
                   % (r.get("engine_files_incoming") or [])[:4])
        _rc, head1 = git(["rev-parse", "HEAD"], lane)
        _rc, cnt1 = git(["rev-list", "--count", "HEAD"], lane)
        fail.check(head0.strip() == head1.strip() and cnt0.strip() == cnt1.strip(),
                   "L3 dry-run **不动泳道**（HEAD %s→%s，提交数 %s→%s）"
                   % (head0.strip()[:8], head1.strip()[:8], cnt0.strip(), cnt1.strip()))

        # ---------- L4 who（Temporal 不可达）= 具名 ENV_FAIL ----------
        rc, wres, _err = run_tool("who", TID, "--host", DEAD_HOST, repo=repo)
        fail.check(rc == 2 and wres.get("ok") is False
                   and "事件历史" in str(wres.get("error") or ""),
                   "L4 who 不可得 ⇒ 退出 2 + 具名原因（实得 rc=%r err=%r）"
                   % (rc, str(wres.get("error"))[:120]))

        # ---------- L5 sync（真跑，Temporal 不可达）= 具名 ENV_FAIL，**不退化手写 merge** ----------
        rc, sres2, _err = run_tool("sync", TID, "--host", DEAD_HOST, repo=repo)
        fail.check(rc == 2 and sres2.get("ok") is False,
                   "L5 sync 真跑遇 Temporal 不可达 ⇒ 退出 2（实得 %r）" % rc)
        _e5 = str(sres2.get("error") or "")
        fail.check(any(k in _e5 for k in ("prepare_conflict_resolution", "temporalio",
                                         "activity", "不可得")),
                   "L5 报错点名走的是 activity 单点（不退化手写 merge；实得 %r）"
                   % _e5[:160])
        rc4, out4 = git(["log", "--oneline", "-1", "HEAD"], lane)
        fail.check(rc4 == 0 and "fixture baseline" in out4,
                   "L5 失败路径**没有**手写 merge 落盘（泳道 HEAD 仍=夹具基线：%r）"
                   % out4.strip()[:80])

        # ---------- L6 restart：夹具泳道 pidfile 指向**活进程** ⇒ 工具自己的拒绝面 ----------
        # 纯本地面（拒绝发生在任何 spawn 之前）：`--replace` 缺席 ⇒ 不许起第二颗。
        lane_pf = os.path.join(repo, "server", "engine", "data", "worker-%s.pid" % TID)
        with open(lane_pf, "w", encoding="utf-8") as f:
            f.write(str(sleeper.pid))
        lane_log = os.path.join(repo, "server", "engine", "data", "worker-%s.log" % TID)
        rc, rres, _err = run_tool("restart", "--scope", "lane:%s" % TID, "--host", DEAD_HOST,
                                  repo=repo)
        fail.check(rc == 1 and rres.get("ok") is False,
                   "L6 泳道活进程在场 ⇒ 拒绝启动（实得 rc=%r）" % rc)
        fail.check(str(sleeper.pid) in str(rres.get("error") or ""),
                   "L6 拒绝面点名活进程 pid（实得 %r）" % str(rres.get("error"))[:160])
        fail.check("--replace" in str(rres.get("error") or ""),
                   "L6 拒绝面给出 --replace 出路")
        fail.check(str(sleeper.pid) == open(lane_pf, encoding="utf-8").read().strip(),
                   "L6 拒绝路径不改写泳道 pidfile")
        fail.check(not os.path.exists(lane_log),
                   "L6 拒绝路径不产生泳道后台日志（没 fork、没起第二颗）")
        # central 档：夹具仓没有 worker.py ⇒ 必须**具名不可得**，不许让 python 裸错当结果
        rc, cres, _err = run_tool("restart", "--scope", "central", "--host", DEAD_HOST,
                                  repo=repo)
        fail.check(rc == 2 and "不在" in str(cres.get("error") or ""),
                   "L6 central 缺件 ⇒ 具名不可得（实得 rc=%r err=%r）"
                   % (rc, str(cres.get("error"))[:120]))

        # ---------- L7 workers：poller 不可得必须具名 ----------
        rc, wres, _err = run_tool("workers", "--host", DEAD_HOST, repo=repo)
        res7 = wres.get("result") or {}
        q = (res7.get("queues") or [{}])[0]
        fail.check(q.get("available") is False and "不可得" in str(q.get("note") or ""),
                   "L7 队列 poller 面不可得 ⇒ 具名（实得 %r）" % q.get("note"))
        fail.check(any("不可得" in a for a in (res7.get("alerts") or [])),
                   "L7 告警面点名不可得（不得当作 0 颗静默放过；实得 %r）"
                   % (res7.get("alerts") or [])[:1])
        fail.check(str(sleeper.pid) in json.dumps(res7, ensure_ascii=False),
                   "L7 workers 面列出夹具里的活 worker（pid）")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    fail.finish()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
