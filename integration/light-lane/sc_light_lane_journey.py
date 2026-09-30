#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_light_lane_journey.py —— 轻道（light-lane）端到端旅程（宿主令 260930，直修无票）。

intent（守护的用户可感知行为）：**一条轻道票真的走完它自己那条短段链**——
  A. **段链就是轻道那条**：真 worker + 真活动 + 桩大脑（`SANDBAR_AGENT_CMD` 可编程桩）
     驱动一张真 `light-lane` 票：桩账本（agent 实收派单的唯一观测面）逐段记录
     create_plan → implement，**且零** review_plan / design_integration_tests / arbitrate /
     acceptance_walkthrough 派单；票面 timeline/handoffs 同样零这四段痕迹。
  B. **机器闸跑的是项目声明的集成命令**：夹具泳道的 `verify.yaml` 里
     `integration.cmd` 与主仓声明**逐字相同**（`python3 integration/run_scenarios.py`），
     且闸回执里出现夹具注册表里那三条场景名——只有真执行器读真注册表才可能产出。
  C. **红转人（不仲裁、不自动重跑）**：三条在册夹具场景被植成故意失败 ⇒ 票**进 blocked**
     且票面带**完整违规集**（三条名全在，不是样本）+ 计数 + 闸回执指针 + 三条具名出路；
     blocked_detail 的结构化面 `violations_complete=true`；blocked 之后账本在观察窗内
     **不再增长**（一个 attempt 只跑一轮，绝不自动循环）；timeline 零仲裁段。
  D. **人唤醒重跑闸**：blocked 态发人信号 `retry_qc` ⇒ 闸**真的重跑**（账本新增记录，
     且第二轮以 `SANDBAR_SCENARIO_ONLY`=上轮三条红名收窄快反馈面），红转绿后引擎机械补
     **收口全量跑**（账本第三次记录，无点名面）。
  E. **绿路到人门**：票走到 `stage=merge / stage_state=awaiting-human`（轻道唯一人门），
     timeline 有 merge_check done；人签 approve → 票收口 closed + 泳道拆净（归档成功是
     拆道前置，与 dev-lane 同一批活动）。

灰盒声明：断言只落公开契约面——client.py 结构化回执、ticket-query snapshot 键
（stage/stage_state/blocked_reason/blocked_detail/timeline/handoffs/results）、夹具内的
git/文件终态、以及**本场景自己写下的桩账本**（agent 实收派单与闸跑面的观测面）。不 import
引擎内部私有结构、不锚实现命名、不锚文案字面全句。

分层与 intent 分工（防重复）：轻道段/门声明与拓扑一致性、闸判词与 blocked 契约的**纯函数
真值分支**归 L1 `server/engine/tests/test_light_lane_lane.py`（白盒，本场景不重测）；本条锁
「真 Temporal + 真 worker + 真活动」的编排行为面。与既有真票场景 intent 不同面：
t260908-01-ticket-pause-gate 守段间暂停/恢复，t260911-04 守多仓落地，本条守**轻道段链与
红转人契约**。

拓扑与隔离（precedent 形态，逐项可查）：舞台=`stage_docker` 单点起 temporal-only 一次性
测试台（带内随机端口，生产端口集硬禁，含 3099）；被测链路=真 `LightLaneWorkflow` + 真
activities + 可编程桩（`SANDBAR_AGENT_CMD`）；worker 从**夹具仓**（本仓 --depth 1 clone）
的引擎起——泳道/settle/闸/合并/归档/拆道全在夹具仓与夹具注册表内，真仓零接触。夹具泳道的
集成声明用 `integration/t260913-03/lib_pool_exclude_lane.build_lane`（既有共享夹具：真
执行器 + mini 注册表注入 + 最小 verify 声明 + 舞台桩，零 docker 零端口）——**声明命令本身
逐字不动**（=主仓同一条）。一切子进程 env 剥除泳道 worker 标记三件套后显式钉死队列/地址/
注册表。

自证与回收：L0 断言舞台端口 ∈ 舞台端口带且 ∉ `stage_docker.FORBIDDEN_PORTS`（含 3099）、
子 env 无泳道标记；finally 收回 worker（TERM→KILL）、拆台、删夹具 tmp（`SANDBAR_LIGHTLANE_
E2E_KEEP_TMP=1` 可保全现场）。

三态：docker/镜像/舞台缺席、引擎 venv 缺失=打印 `ENV_FAIL: <缺什么>` 并 exit 2；断言不符
= exit 1；全绿 = exit 0。零接触 3099。

用法：`python3 integration/light-lane/sc_light_lane_journey.py`
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)                                  # stage_docker 单点
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))      # lib_gate 共享夹具
sys.path.insert(0, os.path.join(INTEG, "t260913-03"))      # 最小真泳道夹具（build_lane）
from lib_gate import (Fail, accepted, parse_out_json, poc_python,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_pool_exclude_lane import build_lane  # noqa: E402
import stage_docker  # noqa: E402

LANE_MARKERS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW")
PROJECT_KEY = "lightlane-e2e"
TID = "lightlane-%d" % os.getpid()
WRITE_FILE = "LIGHT_LANE_PROBE.md"
# 夹具注册表里的三条秒级场景（红轮=三条全红 → 完整违规集面；绿轮=三条全绿）
GATE_NAMES = ("lightlane-fixture-alpha", "lightlane-fixture-beta", "lightlane-fixture-gamma")
# 轻道被排除的段（出现即本票失效）
EXCLUDED_STAGES = ("review_plan", "design_integration_tests", "arbitrate",
                   "acceptance_walkthrough")
# 段链（真跑序）
LIGHT_STAGES = ("create_plan", "implement", "run_integration_tests", "merge_check", "merge")

G = {"tmp": "", "fixture": "", "projects": "", "ctl": "", "gate_ledger": "",
     "stub_ledger": "", "stub": "", "worker": None}

# 桩落盘（引擎 spawn 的 agent 命令）：argv 末位=prompt；阶段名与结果文件路径从 prompt 里取。
# 同时①落一个写集内的真实文件（settle 才有物可提交）②把「实收派单」写进账本（断言面）。
STUB_SRC = r'''
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
led = os.environ.get("LIGHTLANE_STUB_LEDGER") or ""
if led:
    with open(led, "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage, "ts": time.time(),
                            "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    try:
        with open(os.path.join(os.getcwd(), "LIGHT_LANE_PROBE.md"), "a",
                  encoding="utf-8") as f:
            f.write("- %s stage ran for the ticket\n" % stage)
    except OSError:
        pass
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump({"status": "ok",
                   "summary": "[light-lane-e2e stub] %s done" % stage,
                   "report": "[light-lane-e2e stub] %s" % stage,
                   "deliverables": [], "files_changed": ["LIGHT_LANE_PROBE.md"],
                   "files_changed_shape": "ok",
                   "evidence": "light-lane-e2e stub"}, f, ensure_ascii=False)
'''

# 夹具场景脚本（控档驱动）：红/绿由**泳道之外**的控档决定（不改被验证树），并把每次
# 调用（含 SANDBAR_SCENARIO_ONLY 收窄面）落进闸账本（跑面断言面）。占位符用 <<NAME>>
# 形态而非 %-格式（脚本自身含 % 号，% 格式串会炸）。
PROBE_SRC = r'''
import json, os, sys, time
NAME = "<<NAME>>"
CTL = "<<CTL>>"
LED = "<<LED>>"
mode = "green"
try:
    with open(CTL, encoding="utf-8") as f:
        mode = (f.read().strip() or "green")
except OSError:
    mode = "green"
try:
    with open(LED, "a", encoding="utf-8") as f:
        f.write(json.dumps({"name": NAME, "mode": mode,
                            "only": os.environ.get("SANDBAR_SCENARIO_ONLY", ""),
                            "cwd": os.getcwd(), "ts": time.time()},
                           ensure_ascii=False) + "\n")
except OSError:
    pass
if mode == "red":
    sys.exit(1)
'''


def env_for(stage, extra=None):
    """子进程 env 单点：剥泳道标记三件套 + 钉舞台地址/命名空间/夹具注册表 + 台账隔离。

    `SANDBAR_CALLER_PROJECT` 在此声明（L9：建票等 gated 写操作的调用方身份）。"""
    env = dict(os.environ)
    for k in LANE_MARKERS:
        env.pop(k, None)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = stage["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = G["projects"]
    env["SANDBAR_CALLER_PROJECT"] = PROJECT_KEY
    # 台账隔离：场景结果台账与事件账本都不落机器态（夹具 tmp 内，随 tmp 回收）
    env["SANDBAR_SCENARIO_LEDGER_DIR"] = os.path.join(G["tmp"], "scenario-ledger")
    env["SANDBAR_EVENT_LEDGER_DIR"] = os.path.join(G["tmp"], "event-ledger")
    env["LIGHTLANE_STUB_LEDGER"] = G["stub_ledger"]
    # 台账复用（t260930-01）在本场景显式关掉：收口全量跑必须**真跑**（复用会让「收口
    # 跑真的发生过」变成不可判）；复用回执面由引擎 L1 与执行器自身的场景覆盖。
    env["SANDBAR_LEDGER_REUSE"] = "0"
    if extra:
        env.update(extra)
    return env


def cli(py, stage, sub, args, extra=None, timeout=180):
    rc, out = run_poc_client(py, sub, args, env_for(stage, extra), timeout=timeout)
    return parse_out_json(out)


def wait_snap(fail, py, stage, tid, pred, label, deadline_s):
    """轮询 ticket-query 直到 pred(snapshot) 成立；超时=点名红并返回 None。"""
    t0 = time.time()
    last = {}
    while time.time() - t0 < deadline_s:
        r = cli(py, stage, "ticket-query", {"ticket_id": tid})
        snap = ((r.get("result") or {}).get("snapshot") or {})
        if snap:
            last = snap
            if pred(snap):
                return snap
        time.sleep(2)
    fail.check(False, "%s（%ds 内未达；末次 stage=%s/%s blocked=%r）"
               % (label, deadline_s, last.get("stage"), last.get("stage_state"),
                  str(last.get("blocked_reason") or "")[:120]))
    return None


def print_timeline(snap, tag):
    """打印票面 timeline 的段序（证据面：轻道段链 + 被排除段确实缺席）。"""
    rows = snap.get("timeline") or []
    seq = ["%s/%s" % (e.get("stage"), e.get("state")) for e in rows]
    print("  [timeline %s] %s" % (tag, " | ".join(seq)), flush=True)
    bad = sorted({str(e.get("stage")) for e in rows} & set(EXCLUDED_STAGES))
    print("  [timeline %s] excluded stages present: %s"
          % (tag, bad or "none"), flush=True)


def read_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except ValueError:
                rows.append({"raw": ln})
    return rows


def git(*args, cwd=None):
    p = subprocess.run(["git", "-C", cwd or G["fixture"]] + list(args),
                       capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def build_fixture(fail):
    """夹具仓 + 项目注册表 + 夹具泳道声明（build_lane 单点）+ mini 场景脚本 + 一条 main 提交。"""
    fixture = os.path.join(G["tmp"], "fixture")
    clone = subprocess.run(["git", "clone", "--depth", "1", REPO, fixture],
                           capture_output=True, text=True, timeout=600)
    if clone.returncode != 0:
        fail.bail("git clone 夹具仓失败（环境）：%s" % (clone.stderr or clone.stdout)[:200], 2)
    G["fixture"] = fixture
    # --depth 1 clone 的默认分支名可能是 master/其它 → 统一成 main（泳道 base_ref=main）
    rc, br = git("rev-parse", "--abbrev-ref", "HEAD")
    cur = (br or "").strip()
    if cur and cur != "main":
        git("branch", "-m", "main")
    git("config", "user.email", "e2e@light-lane.test")
    git("config", "user.name", "light-lane-e2e")
    # 项目注册表（KI-032 硬闸消费面：ticket-start 带 project 必过锚定）
    projects = os.path.join(fixture, ".e2e-projects")
    os.makedirs(os.path.join(projects, PROJECT_KEY), exist_ok=True)
    with open(os.path.join(projects, ".migrated"), "w", encoding="utf-8") as f:
        f.write("fixture-local hermetic registry (light-lane e2e)\n")
    with open(os.path.join(projects, PROJECT_KEY, "project.yaml"), "w",
              encoding="utf-8") as f:
        f.write("# fixture-local registry: dirs -> the fixture repo itself\n"
                "schema: v1\nproject:\n  - key: %s\n    name: light-lane-fixture\n"
                "    dirs:\n      - %s\n" % (PROJECT_KEY, fixture))
    G["projects"] = projects
    # 引擎 venv 软链（prepare_workspace 的 LANE_DEP_SYMLINKS 消费面）
    target = os.path.join(REPO, "server", "engine", ".venv")
    link = os.path.join(fixture, "server", "engine", ".venv")
    if os.path.isdir(target) and not os.path.exists(link):
        os.symlink(target, link)
    # 夹具泳道声明与 mini 注册表：复用 t260913-03 build_lane（真执行器 + 注入 mini 表 +
    # 最小 verify.yaml + 舞台桩）。它写的 integration.cmd 与主仓声明逐字相同：见 L2 断言。
    build_lane(fixture, [(n, "ro", True) for n in GATE_NAMES])
    # mini 场景脚本改成控档驱动（同一张泳道可红可绿，且把调用面落账）
    mini_dir = os.path.join(fixture, "integration", "mini")
    for n in GATE_NAMES:
        with open(os.path.join(mini_dir, "%s.py" % n), "w", encoding="utf-8") as f:
            f.write(PROBE_SRC.replace("<<NAME>>", n)
                    .replace("<<CTL>>", G["ctl"])
                    .replace("<<LED>>", G["gate_ledger"]))
    # 引擎面覆盖：夹具仓 clone 自 **HEAD**，而本票被测的是**当前工作树**——把工作树里
    # server/engine 与 server/workflows 的改动（含未跟踪的新模块 light_lane.py 与
    # light-lane.yaml）逐文件覆盖进夹具仓。这才是「真跑被测代码」；不覆盖的话夹具 worker
    # 只有 HEAD 那套，起 light-lane 票会 NotFoundError（首跑实证）。
    pc = subprocess.run(["git", "status", "--porcelain", "--", "server/engine",
                         "server/workflows"], cwd=REPO, capture_output=True,
                        text=True, timeout=120)
    copied = []
    for ln in (pc.stdout or "").splitlines():
        rel = ln[3:].strip().strip('"')
        if not rel or rel.endswith("/"):
            continue
        if not (rel.endswith(".py") or rel.endswith(".yaml")):
            continue
        src = os.path.join(REPO, rel)
        dst = os.path.join(fixture, rel)
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    fail.check("server/engine/light_lane.py" in copied,
               "夹具仓覆盖引擎工作树改动（含新模块 light_lane.py；共 %d 件）"
               % len(copied))
    # 基线：把夹具声明提交到 main（泳道 worktree 从 main 分叉，才看得见它们）
    git("add", "-A")
    rc, out = git("commit", "-qm", "light-lane e2e fixture: mini integration registry")
    if rc != 0:
        fail.bail("夹具仓基线提交失败：%s" % out[:200], 2)
    return fixture


def start_worker(py, stage):
    extra = {
        "SANDBAR_TASK_QUEUES": "sandbar-ticket-%s" % TID,
        "SANDBAR_WATCH_WORKFLOW": TID,
        "SANDBAR_WATCH_INTERVAL_SEC": "2",
        # 桩大脑（可编程）：逐段回合法回执 + 落写集内文件 + 把实收派单落账本
        "SANDBAR_AGENT_CMD": "%s %s" % (py, G["stub"]),
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    log = open(os.path.join(G["tmp"], "worker.log"), "wb")
    proc = subprocess.Popen([py, os.path.join(G["fixture"], "server", "engine", "worker.py")],
                            env=env_for(stage, extra), cwd=REPO, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    G["worker"] = proc
    return proc


def stop_worker(fail, label):
    proc = G["worker"]
    if proc is None:
        return
    G["worker"] = None
    if proc.poll() is not None:
        fail.check(True, "%s：worker 已自行退出（watch 收票即退，rc=%s）" % (label, proc.returncode))
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
        fail.check(True, "%s：worker TERM 后 20s 内退出（资源回收）" % label)
    except Exception:
        fail.check(False, "%s：worker TERM 20s 未退（kill 兜底前先计红）" % label)
        proc.kill()
        proc.wait(timeout=10)


def declared_integration_cmd(verify_yaml):
    """从 verify.yaml 里取 `integration:` 段的 cmd（子集解析：缩进+键值，够用且不猜）。"""
    seen = False
    for ln in open(verify_yaml, encoding="utf-8").read().splitlines():
        if re.match(r"^integration:\s*$", ln):
            seen = True
            continue
        if seen:
            m = re.match(r"^\s+cmd:\s*(.+?)\s*$", ln)
            if m:
                return m.group(1)
            if re.match(r"^\S", ln):
                break
    return ""


def main():
    fail = Fail("light-lane workflow e2e (host-ordered direct fix, no ticket, 260930)")

    stats = {"pass": 0}

    def check(cond, msg):
        """fail.check + 通过计数（SUMMARY 行是人读面，判据仍是退出码）。"""
        r = fail.check(cond, msg)
        if r:
            stats["pass"] += 1
        return r
    stage_mod = None
    bench = None
    stage = None
    G["tmp"] = tempfile.mkdtemp(prefix="sandbar-lightlane-e2e-")
    atexit.register(lambda: shutil.rmtree(G["tmp"], ignore_errors=True)
                    if not os.environ.get("SANDBAR_LIGHTLANE_E2E_KEEP_TMP") else None)
    G["ctl"] = os.path.join(G["tmp"], "gate-mode")
    G["gate_ledger"] = os.path.join(G["tmp"], "gate-ledger.jsonl")
    G["stub_ledger"] = os.path.join(G["tmp"], "stub-ledger.jsonl")
    G["stub"] = os.path.join(G["tmp"], "ll_stub.py")
    with open(G["stub"], "w", encoding="utf-8") as f:
        f.write(STUB_SRC)
    with open(G["ctl"], "w", encoding="utf-8") as f:
        f.write("red\n")
    try:
        # ---------- L0 环境与红线自证 ----------
        bench = require_bench(fail)
        py = poc_python(bench)
        stage_mod, stage = require_stage(fail, "lightlane-e2e-%d" % os.getpid(),
                                         "lightlane-e2e-%d" % os.getpid())
        fe = int(stage["ports"]["temporal"])
        check(fe not in stage_docker.FORBIDDEN_PORTS,
                   "L0 写守卫：舞台端口 %d ∉ 禁区端口集（含 3099）" % fe)
        env0 = env_for(stage)
        check(all(k not in env0 for k in LANE_MARKERS),
                   "L0 子 env 已剥泳道 worker 标记三件套（递归/串台不可能）")
        check(env0["SANDBAR_TARGET_HOST"] == "127.0.0.1:%d" % fe,
                   "L0 全部子进程地址恒=本场景舞台（绝不回落生产 7233）")

        # ---------- L1 夹具仓 + 夹具泳道声明 ----------
        build_fixture(fail)
        fx = G["fixture"]
        main_decl = declared_integration_cmd(os.path.join(REPO, "verify.yaml"))
        lane_decl = declared_integration_cmd(os.path.join(fx, "verify.yaml"))
        check(bool(main_decl) and lane_decl == main_decl,
              "L1 夹具泳道声明的集成命令与主仓声明逐字相同（夹具 %r / 主仓 %r）"
              % (lane_decl, main_decl))

        # ---------- L2 开票（真 light-lane 模板） ----------
        start_worker(py, stage)
        # base_ref=项目主目录 HEAD 短哈希（与正规 create 路径 _base_ref 同口径）——
        # 裸 client.py ticket-start 不代算，缺它则 merge_check 的泳道基线判定红。
        _rc, br = git("rev-parse", "--short", "HEAD")
        base_ref = (br or "").strip()
        _rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "light-lane", "project": PROJECT_KEY,
            "base_ref": base_ref,
            "title": "[e2e] light-lane journey (red -> wake -> green -> human merge gate)",
            "user_request": "integration e2e: light lane short walk + red goes to a human",
            "write_set": [WRITE_FILE],
            "caller_project": PROJECT_KEY,
        }, env_for(stage), timeout=300)
        good, why = accepted(out, TID)
        check(good, "L2 真 light-lane 票受理（ticket-start，%s）" % why)
        if not good:
            fail.bail("建票未受理，后续子用例无从进行：%s" % why, 1)

        # ---------- L3 红轮：闸不绿 → blocked（完整违规集，不仲裁不自动重跑） ----------
        snap = wait_snap(fail, py, stage, TID,
                         lambda x: x.get("stage") == "run_integration_tests"
                         and x.get("stage_state") == "blocked", "L3 票停在机器闸 blocked", 600)
        if snap is not None:
            reason = str(snap.get("blocked_reason") or "")
            detail = snap.get("blocked_detail") or {}
            timeline = snap.get("timeline") or []
            handoffs = snap.get("handoffs") or []
            tl_stages = [str(e.get("stage") or "") for e in timeline]
            hf_stages = [str(e.get("stage") or "") for e in handoffs]
            # (a) 段链：轻道跑的段在，被排除的段一个都没有（派单/票面两面）
            stub_stages = [r.get("stage") for r in read_jsonl(G["stub_ledger"])]
            check(stub_stages == ["create_plan", "implement"],
                       "L3a agent 派单账本恰为轻道前两段（实得 %r）" % stub_stages)
            check(not (set(stub_stages) & set(EXCLUDED_STAGES)),
                       "L3a 被排除段零派单（review_plan/design_integration_tests/"
                       "arbitrate/acceptance_walkthrough）")
            check(not (set(tl_stages) & set(EXCLUDED_STAGES)),
                       "L3a 票面 timeline 零被排除段（实得 %r）" % sorted(set(tl_stages)))
            check(not (set(hf_stages) & set(EXCLUDED_STAGES)),
                       "L3a 票面 handoffs 零被排除段（实得 %r）" % sorted(set(hf_stages)))
            check("create_plan" in tl_stages and "implement" in tl_stages,
                       "L3a timeline 含轻道前两段")
            # (b) 机器闸真跑项目声明的命令（三条夹具场景名只有真执行器读真注册表才有）
            gate_rows = read_jsonl(G["gate_ledger"])
            round1 = [r for r in gate_rows if r.get("mode")]
            check(sorted({r.get("name") for r in gate_rows}) == sorted(GATE_NAMES),
                       "L3b 闸真跑夹具注册表三条在册场景（实得 %r）"
                       % sorted({r.get("name") for r in gate_rows}))
            check(all(r.get("only") == "" for r in round1),
                       "L3b 首轮=全量面（无 SANDBAR_SCENARIO_ONLY 收窄）")
            # (c) 完整违规集 + 计数 + 回执指针 + 出路（不在文案里给样本）
            for n in GATE_NAMES:
                check(n in reason, "L3c blocked 文案点名违规项 %s（完整集，非样本）" % n)
            check("Complete violation set (3)" in reason,
                       "L3c blocked 文案给出完整集大小")
            check(re.search(r"3 ran / 0 passed / 3 failed / \d+ env-red", reason)
                       is not None, "L3c blocked 文案带计数（实得 %r）" % reason[:200])
            check("results.run_integration_tests" in reason
                       and "integration-report" in reason,
                       "L3c blocked 文案带闸回执指针")
            check("retry_qc" in reason and "rework(to_stage=implement)" in reason
                       and "dev-lane" in reason,
                       "L3c blocked 文案带三条具名出路（重跑/打回/另开全道票）")
            check("no arbitration" in reason and "no automatic re-run" in reason,
                       "L3c blocked 文案声明轻道口径（不仲裁、不自动重跑）")
            check(bool(detail) and detail.get("violations_complete") is True,
                       "L3c blocked_detail 结构化完整集标记在场")
            check(sorted(detail.get("violations") or [])[:3] == sorted(GATE_NAMES),
                       "L3c blocked_detail.violations=完整违规集（实得 %r）"
                       % (detail.get("violations"),))
            check(int((detail.get("counts") or {}).get("failed") or 0) == 3,
                       "L3c blocked_detail.counts.failed=3")
            check(len(detail.get("remedies") or []) == 3,
                       "L3c blocked_detail 带三条出路")
            check("arbitrate" not in tl_stages,
                       "L3c 红转人：timeline 零仲裁段（不调仲裁活动）")
            print_timeline(snap, "blocked at the machine gate")
            # (d) 不自动循环：blocked 之后观察窗内闸账本不增长
            n_before = len(read_jsonl(G["gate_ledger"]))
            time.sleep(12)
            n_after = len(read_jsonl(G["gate_ledger"]))
            check(n_before == n_after,
                       "L3d 一个 attempt 只跑一轮闸（blocked 后 12s 账本零增长：%d→%d）"
                       % (n_before, n_after))

        # ---------- L4 人唤醒：retry_qc 重跑闸（红转绿）→ 收口全量跑 → 人门 ----------
        with open(G["ctl"], "w", encoding="utf-8") as f:
            f.write("green\n")
        n_before = len(read_jsonl(G["gate_ledger"]))
        wake = cli(py, stage, "ticket", {"op": "retry_qc", "ticket_id": TID,
                                         "who": "e2e-human"})
        check(wake.get("ok") is True,
                   "L4 人信号 retry_qc 受理（%s）" % str(wake.get("error") or "")[:120])
        snap2 = wait_snap(fail, py, stage, TID,
                          lambda x: x.get("stage") in ("merge_check", "merge")
                          or x.get("status") == "closed",
                          "L4 唤醒后闸重跑并推进（红转绿）", 600)
        rows2 = read_jsonl(G["gate_ledger"])[n_before:]
        check(len(rows2) >= 3,
                   "L4 唤醒后闸**真重跑**（新增账本记录 %d 条 ≥3）" % len(rows2))
        narrowed = [r for r in rows2 if r.get("only")]
        check(bool(narrowed) and set(str(narrowed[0]["only"]).split(",")) == set(GATE_NAMES),
                   "L4 第二轮=定点快反馈面（SANDBAR_SCENARIO_ONLY 点名上轮三条红名，实得 %r）"
                   % (narrowed[0].get("only") if narrowed else None))
        check(any(not r.get("only") for r in rows2),
              "L4 定点轮绿后引擎机械补收口全量跑（全量面记录在场）")
        _hf = [str(h.get("summary") or "") for h in ((snap2 or {}).get("handoffs") or [])
               if str(h.get("stage")) == "run_integration_tests"]
        check(any("narrowed to" in t for t in _hf),
              "L4 收窄跑面**如实进票面**（handoff 带 narrowed to 注记；实得 %r）"
              % (_hf[-3:],))
        _res = (snap2 or {}).get("results") or {}
        check(str((_res.get("run_integration_tests") or {}).get("summary") or "")
              .startswith("closing full run"),
              "L4 票面闸回执=收口全量跑那一次（summary 实得 %r）"
              % str((_res.get("run_integration_tests") or {}).get("summary"))[:80])
        if snap2 is not None:
            check(snap2.get("stage") in ("merge_check", "merge")
                       or snap2.get("status") == "closed",
                       "L4 绿路推进到 merge_check/merge（实得 %s/%s）"
                       % (snap2.get("stage"), snap2.get("stage_state")))
            tl2 = [str(e.get("stage") or "") for e in (snap2.get("timeline") or [])]
            check(tl2.count("run_integration_tests") >= 2,
                       "L4 闸段在票面 timeline 出现 ≥2 轮（唤醒重跑可见）")

        # ---------- L5 绿路到人门 + 人签收口（归档 → 拆道） ----------
        human = wait_snap(fail, py, stage, TID,
                          lambda x: x.get("stage") == "merge"
                          and x.get("stage_state") == "awaiting-human",
                          "L5 走到轻道唯一人门（merge）", 420)
        if human is not None:
            tl3 = human.get("timeline") or []
            done_marks = [e for e in tl3
                          if str(e.get("stage")) == "merge_check"
                          and str(e.get("state")) == "done"]
            check(bool(done_marks), "L5 timeline 有 merge_check done（程序化四项通过）")
            check(all(str(e.get("stage")) not in EXCLUDED_STAGES for e in tl3),
                       "L5 全链 timeline 零被排除段")
            sig = cli(py, stage, "ticket", {"op": "sign", "ticket_id": TID,
                                            "input": {"who": "e2e-human", "gate": "merge",
                                                      "decision": "approve",
                                                      "note": "e2e: light-lane green path"}})
            check(sig.get("ok") is True, "L5 人签 approve 受理（%s）"
                       % str(sig.get("error") or "")[:120])
            fin = wait_snap(fail, py, stage, TID,
                            lambda x: x.get("status") == "closed", "L5 票收口 closed", 420)
            if fin is not None:
                check(str(fin.get("stage_state")) == "awaiting",
                           "L5 终态 stage_state=awaiting（收口形态）")
                lane = str(((fin.get("meta") or {}).get("workspace") or {}).get("path") or "")
                rc, out = git("worktree", "list")
                check(lane and lane not in out,
                           "L5 合并成功后泳道拆净（worktree list 无该泳道）")
                rc2, heads = git("branch", "--list", "lane/*")
                check(rc2 == 0 and not heads.strip(),
                           "L5 泳道分支已删（branch lane/* 为空，实得 %r）" % heads.strip()[:120])
                rc3, log = git("log", "--oneline", "-3")
                check(rc3 == 0 and bool(log.strip()),
                           "L5 夹具 main 有落地提交（合并真发生）")
                print_timeline(fin, "closed")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 —— 崩溃路径必须留证据（点名 + 保全现场）
        import traceback
        traceback.print_exc()
        check(False, "场景中途异常：%s: %s" % (type(e).__name__, str(e)[:240]))
    finally:
        try:
            stop_worker(fail, "L6 收尾")
        except Exception as e:  # noqa: BLE001
            check(False, "worker 收尾异常：%s" % str(e)[:160])
        if stage is not None and stage_mod is not None:
            try:
                print("  stage_down: %s" % str(stage_down(stage_mod, stage))[:200], flush=True)
            except Exception as e:  # noqa: BLE001
                print("  (stage_down 容错：%s)" % str(e)[:160], flush=True)
        if not os.environ.get("SANDBAR_LIGHTLANE_E2E_KEEP_TMP"):
            shutil.rmtree(G["tmp"], ignore_errors=True)
        else:
            print("  [现场保全] %s" % G["tmp"], flush=True)
        print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
              % (stats["pass"], len(fail.fails)), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
