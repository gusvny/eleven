#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_light_lane_journey.py —— 轻道（light-lane）端到端旅程（宿主令 260930，直修无票）。

intent（守护的用户可感知行为）：**一条轻道票真的走完它自己那条短段链**——
  A. **段链就是轻道那条**：真 worker + 真活动 + 桩大脑（`SANDBAR_AGENT_CMD` 可编程桩）
     驱动一张真 `light-lane` 票：桩账本（agent 实收派单的唯一观测面）逐段记录
     **implement**（轻道首段），**且零** create_plan / review_plan /
     design_integration_tests / arbitrate / acceptance_walkthrough 派单（宿主 260930 裁定：
     轻道不写方案）；票面 timeline/handoffs 同样零这五段痕迹，**并带正向断言：派单账本
     首条=implement（首段即实现）**。
  A2. **UI 证据条件段两态**（宿主 260930 第二轮裁定「把 UI 证据步加回轻道」，脚本段、
     仅 UI 票）：**非 UI 票**（主票 + 空写集票）ui_evidence 在派单面/时间线/交接面/全链
     **四处零出现**；**UI 票**（写集命中夹具 verify.yaml 的 ui_evidence.dirs 前缀）该段
     **出现且真跑**——时间线有 running/done、票据回执有记账（results.ui_evidence）、泳道
     .sandbar/screenshots/ 有截图实物，且**它跑在机器闸之前**（段序）。
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
  F. **write_set_missing 出路改写（宿主 260930）**：另开一张**空写集**的轻道票 → 实现段
     落盘被路径闸拒（reason_code=write_set_missing）→ 票面 `blocked_detail.next_action`
     **不含 create_plan**（改写为模板中立口径），原文留在 `next_action_rewritten_from`
     （可追溯）；dev-lane 的同一提示逐字不变（那条由 L1 负向锁守）。
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
# 第二张票（宿主 260930 裁定的端到端面）：**空写集**轻道票——走 write_set_missing 红，
# 用来验「轻道票面出路不指向 create_plan」在真链上成立（改写点在轻道自己的收敛点）。
TID_NOWS = "lightlane-nows-%d" % os.getpid()
# 第三张票（宿主 260930 第二轮裁定：UI 证据步加回轻道）：**UI 票**——写集命中夹具
# verify.yaml 的 ui_evidence.dirs 前缀，用来验「该段出现且真跑，且跑在机器闸之前」。
TID_UI = "lightlane-ui-%d" % os.getpid()
UI_DIR = "server/plugins/workbench/src/client/"
UI_FILE = UI_DIR + "LIGHTLANE_UI_PROBE.ts"
#: 改前原文（真源=server/engine/path_gates.py `_NEXT_ACTION_HINTS["write_set_missing"]`；
#: 字面量照抄——轻道票面必须已把它改写掉）。
HINT_BEFORE = "工单写集为空/缺失——回 create_plan 补结构化回执后再实现"
WRITE_FILE = "LIGHT_LANE_PROBE.md"
# 夹具注册表里的三条秒级场景（红轮=三条全红 → 完整违规集面；绿轮=三条全绿）
GATE_NAMES = ("lightlane-fixture-alpha", "lightlane-fixture-beta", "lightlane-fixture-gamma")
# 轻道被排除的段（出现即本票失效）：全车道有、轻道没有的那几条——被裁的四段（审方案/
# 集测设计/仲裁/验收走查）+ **create_plan**（宿主 260930 裁定轻道不写方案）。
# **ui_evidence 不在这个集合里**：它是**条件段**（第二轮裁定加回轻道）——按票分两态判：
#   · 非 UI 票（主票/空写集票）：四处（派单面/时间线/交接面/全链）**零出现**（负断言）；
#   · UI 票（TID_UI）：**出现且真跑**（running/done + 回执 + 截图实物），且跑在机器闸之前。
EXCLUDED_STAGES = ("review_plan", "design_integration_tests", "arbitrate",
                   "acceptance_walkthrough", "create_plan")
# 段链（真跑序；宿主 260930：无方案段、无 UI 证据段——首段即 implement）。
LIGHT_STAGES = ("implement", "run_integration_tests", "merge_check", "merge")

G = {"tmp": "", "fixture": "", "projects": "", "ctl": "", "gate_ledger": "",
     "stub_ledger": "", "stub": "", "workers": []}

# 桩落盘（引擎 spawn 的 agent 命令）：argv 末位=prompt；阶段名与结果文件路径从 prompt 里取。
# 同时①落一个写集内的真实文件（settle 才有物可提交）②把「实收派单」写进账本（断言面）。
STUB_SRC = r'''
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
mt = re.search(r"工单 (\S+?)（", prompt)
ticket = mt.group(1) if mt else "unknown"
led = os.environ.get("LIGHTLANE_STUB_LEDGER") or ""
if led:
    with open(led, "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage, "ticket": ticket, "ts": time.time(),
                            "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    extra = [x.strip() for x in
             (os.environ.get("LIGHTLANE_STUB_WRITE_FILES") or "").split(",") if x.strip()]
    for rel in ["LIGHT_LANE_PROBE.md"] + extra:
        p2 = os.path.join(os.getcwd(), rel)
        try:
            os.makedirs(os.path.dirname(p2), exist_ok=True)
            with open(p2, "a", encoding="utf-8") as f:
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


def light_neutral_hint():
    """轻道的中立出路口径（真源=引擎 light_lane.LIGHT_NEUTRAL_NEXT_ACTION）。

    不抄字面量：真源改了这里跟着变（否则场景会拿旧文案假绿）。引擎模块 import 走
    `light_lane`（它与 temporalio 同环境），失败时退回读源码常量并响亮点名。"""
    sys.path.insert(0, os.path.join(REPO, "server", "engine"))
    try:
        import light_lane as _ll
        return str(_ll.LIGHT_NEUTRAL_NEXT_ACTION)
    except Exception as e:  # noqa: BLE001——不允许静默：退回源码抓取并把原因打出来
        print("  (light_neutral_hint: import 失败，回落源码抓取：%s: %s)"
              % (type(e).__name__, e), flush=True)
        txt = open(os.path.join(REPO, "server", "engine", "light_lane.py"),
                   encoding="utf-8").read()
        m = re.search(r"LIGHT_NEUTRAL_NEXT_ACTION = \((.*?)\)\n", txt, re.S)
        if not m:
            return ""
        return "".join(re.findall(r'"([^"]*)"', m.group(1)))


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


def stub_stages_of(tid):
    """本**票**的 agent 派单序列（桩账本按票号过滤——同一 worker 服务多张票）。"""
    return [r.get("stage") for r in read_jsonl(G["stub_ledger"]) if r.get("ticket") == tid]


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
    # ui_evidence 声明（宿主 260930 第二轮：UI 票那条分支要用它判「这是 UI 票」）。
    # build_lane 写的是最小 verify.yaml，这里按既有键形状追加 ui_evidence.dirs
    # （键名/缩进与主仓 verify.yaml 同款；声明是**数据**，判据仍只在引擎里）。
    with open(os.path.join(fixture, "verify.yaml"), "a", encoding="utf-8") as f:
        f.write("ui_evidence:\n  dirs:\n    - %s\n" % UI_DIR)
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


def start_worker(py, stage, queues=None, stub_files="", watch=None):
    extra = {
        # 一票一队列是引擎的既有形态（worker 只 poll 派给它的队列）；本场景两张票
        # （主票 TID + 空写集票 TID_NOWS）共用一个 worker，故队列面显式列两条。
        "SANDBAR_TASK_QUEUES": queues or ("sandbar-ticket-%s,sandbar-ticket-%s"
                                          % (TID, TID_NOWS)),
        "SANDBAR_WATCH_WORKFLOW": watch or TID,
        "SANDBAR_WATCH_INTERVAL_SEC": "2",
        # 桩大脑（可编程）：逐段回合法回执 + 落写集内文件 + 把实收派单落账本
        "SANDBAR_AGENT_CMD": "%s %s" % (py, G["stub"]),
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    if stub_files:
        extra["LIGHTLANE_STUB_WRITE_FILES"] = stub_files
    log = open(os.path.join(G["tmp"], "worker.log"), "wb")
    proc = subprocess.Popen([py, os.path.join(G["fixture"], "server", "engine", "worker.py")],
                            env=env_for(stage, extra), cwd=REPO, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    G["workers"].append(proc)
    return proc


def stop_worker(fail, label, proc=None):
    """停一个 worker（缺省=最近起的那个）。多票各有专属 worker，台账在 G['workers']。"""
    if proc is None:
        if not G["workers"]:
            return
        proc = G["workers"].pop()
    elif proc in G["workers"]:
        G["workers"].remove(proc)
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


def stop_all_workers(fail, label):
    """收尾：停掉本场景起过的**全部** worker（一票一 worker，逐个点名回收）。"""
    procs, G["workers"] = list(G["workers"]), []
    for i, proc in enumerate(procs):
        stop_worker(fail, "%s#%d" % (label, i + 1), proc)


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

        # ---------- L2c UI 票：ui_evidence 条件段「出现且真跑，且在机器闸之前」 ----------
        # 独立 worker（一票一队列）：该票的桩额外写 UI 路径文件，使改动面命中夹具
        # verify.yaml 声明的 ui_evidence.dirs → helper 判为 UI 票 → 条件段真跑。
        ui_worker = start_worker(py, stage, queues="sandbar-ticket-%s" % TID_UI,
                                 stub_files=UI_FILE, watch=TID_UI)
        _rc, _br2 = git("rev-parse", "--short", "HEAD")
        _rc3, out3 = run_poc_client(py, "ticket-start", {
            "ticket_id": TID_UI, "template_id": "light-lane", "project": PROJECT_KEY,
            "base_ref": (_br2 or "").strip(),
            "title": "[e2e] light-lane UI ticket (conditional ui_evidence stage)",
            "user_request": "integration e2e: a UI-surface change must run the ui_evidence stage before the gate",
            "write_set": [UI_FILE],
            "caller_project": PROJECT_KEY,
        }, env_for(stage), timeout=300)
        good3, why3 = accepted(out3, TID_UI)
        check(good3, "L2c UI 票受理（%s）" % why3)
        if good3:
            s3 = wait_snap(fail, py, stage, TID_UI,
                           lambda x: x.get("stage") == "run_integration_tests"
                           and x.get("stage_state") == "blocked",
                           "L2c UI 票走到机器闸（先跑过 UI 证据段）", 420)
            if s3 is not None:
                tl_ui = [(str(e.get("stage")), str(e.get("state")))
                         for e in (s3.get("timeline") or [])]
                seq_ui = [st for st, _s in tl_ui]
                check(("ui_evidence", "running") in tl_ui and ("ui_evidence", "done") in tl_ui,
                      "L2c **UI 票**：ui_evidence 出现且真跑（时间线 running/done；实得 %r）"
                      % [x for x in tl_ui if x[0] == "ui_evidence"])
                rec_ui = (s3.get("results") or {}).get("ui_evidence") or {}
                check(str(rec_ui.get("status")) == "ok" and bool(rec_ui.get("deliverables")),
                      "L2c UI 票：票据回执有记账（results.ui_evidence status=%r shots=%r）"
                      % (rec_ui.get("status"), rec_ui.get("deliverables")))
                # 段序：ui_evidence 两条都排在 implement/done 之后、机器闸 running 之前
                i_impl_done = tl_ui.index(("implement", "done")) if ("implement", "done") in tl_ui else -1
                i_ui_run = (tl_ui.index(("ui_evidence", "running"))
                            if ("ui_evidence", "running") in tl_ui else -1)
                i_ui_done = (tl_ui.index(("ui_evidence", "done"))
                             if ("ui_evidence", "done") in tl_ui else -1)
                i_gate = (tl_ui.index(("run_integration_tests", "running"))
                          if ("run_integration_tests", "running") in tl_ui else -1)
                check(-1 < i_impl_done < i_ui_run <= i_ui_done < i_gate,
                      "L2c UI 票段序：implement→ui_evidence→机器闸（下标 %r）"
                      % [i_impl_done, i_ui_run, i_ui_done, i_gate])
                check("handoffs" in s3 and any(str(h.get("stage")) == "ui_evidence"
                                               for h in (s3.get("handoffs") or [])),
                      "L2c UI 票：交接面有 ui_evidence 记账")
                check(not (set(seq_ui) & set(EXCLUDED_STAGES)),
                      "L2c UI 票仍零被裁段（实得 %r）" % sorted(set(seq_ui)))
                # 截图实物：泳道 .sandbar/screenshots/ 下真有 png（隔离台桩写 1x1 PNG）
                lane_ui = str(((s3.get("meta") or {}).get("workspace") or {}).get("path") or "")
                shots = []
                if lane_ui:
                    import glob as _glob
                    shots = _glob.glob(os.path.join(lane_ui, ".sandbar", "screenshots", "*.png"))
                check(bool(shots), "L2c UI 票：泳道 .sandbar/screenshots/ 有截图实物（%d 张）"
                      % len(shots))
                print_timeline(s3, "UI ticket at the machine gate")
            stop_worker(fail, "L2c UI 票 worker 收尾", ui_worker)

        # ---------- L2b write_set_missing 出路改写（宿主 260930 裁定的端到端面） ----------
        # 空写集票（显式声明 no_file_changes）+ 桩照旧落文件 → 落盘路径闸拒
        # (reason_code=write_set_missing)；轻道票面出路必须已改写掉指向 create_plan 的那句。
        _rc, br = git("rev-parse", "--short", "HEAD")
        _rc2, out2 = run_poc_client(py, "ticket-start", {
            "ticket_id": TID_NOWS, "template_id": "light-lane", "project": PROJECT_KEY,
            "base_ref": (br or "").strip(),
            "title": "[e2e] light-lane write-set gate face (no write set declared)",
            "user_request": "integration e2e: the write_set_missing remedy must not point at a stage this lane does not have",
            "write_set": [], "allow_empty_write_set": True,
            "caller_project": PROJECT_KEY,
        }, env_for(stage), timeout=300)
        good2, why2 = accepted(out2, TID_NOWS)
        check(good2, "L2b 空写集轻道票受理（%s）" % why2)
        if good2:
            s2 = wait_snap(fail, py, stage, TID_NOWS,
                           lambda x: x.get("stage") == "implement"
                           and x.get("stage_state") == "blocked",
                           "L2b 空写集票在 implement 落盘被拒后 blocked", 420)
            if s2 is not None:
                d2 = s2.get("blocked_detail") or {}
                check(str(d2.get("reason_code") or "") == "write_set_missing",
                      "L2b 红灯 reason_code=write_set_missing（实得 %r）"
                      % d2.get("reason_code"))
                na2 = str(d2.get("next_action") or "")
                check("create_plan" not in na2,
                      "L2b **轻道票面出路不含 create_plan**（实得 %r）" % na2[:160])
                check(na2 and na2 == light_neutral_hint(),
                      "L2b 出路=本场景自算的模板中立口径（实得 %r）" % na2[:120])
                check(str(d2.get("next_action_rewritten_from") or "") == HINT_BEFORE,
                      "L2b 改写原文留痕=改前共享串（实得 %r）"
                      % str(d2.get("next_action_rewritten_from"))[:80])
                check("create_plan" not in str(s2.get("blocked_reason") or ""),
                      "L2b blocked_reason 文本面同样不含 create_plan")

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
            stub_stages = stub_stages_of(TID)
            check(stub_stages == ["implement"],
                       "L3a agent 派单账本恰为轻道唯一 agent 段（实得 %r）" % stub_stages)
            check(bool(stub_stages) and stub_stages[0] == "implement",
                       "L3a **首段就是 implement**（派单账本首条=%r；无方案段）"
                       % (stub_stages[0] if stub_stages else None))
            check(not (set(stub_stages) & set(EXCLUDED_STAGES)),
                       "L3a 被排除段零派单（create_plan/review_plan/"
                       "design_integration_tests/arbitrate/acceptance_walkthrough）")
            check("ui_evidence" not in stub_stages,
                  "L3a **非 UI 票**：ui_evidence 零派单（条件段不适用；UI 票正向面见 L2c）")
            check("create_plan" not in stub_stages,
                  "L3a **轻道没有方案段**（派单面负断言）")
            check(not (set(tl_stages) & set(EXCLUDED_STAGES)),
                       "L3a 票面 timeline 零被排除段（实得 %r）" % sorted(set(tl_stages)))
            check("ui_evidence" not in tl_stages,
                  "L3a **非 UI 票**：ui_evidence 零时间线痕迹（条件段不适用）")
            check("create_plan" not in tl_stages,
                  "L3a **轻道没有方案段**（时间线负断言）")
            check(not (set(hf_stages) & set(EXCLUDED_STAGES)),
                       "L3a 票面 handoffs 零被排除段（实得 %r）" % sorted(set(hf_stages)))
            check("ui_evidence" not in hf_stages,
                  "L3a **非 UI 票**：ui_evidence 零交接面记账（条件段不适用）")
            check("create_plan" not in hf_stages,
                  "L3a **轻道没有方案段**（交接面负断言）")
            check("implement" in tl_stages,
                       "L3a timeline 含轻道首段 implement")
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
            # 260930 三处面缺陷的端到端面（真票 t260930-09 触发；本场景这轮无环境红、
            # 无基线答案 → 正好验「none 态」与「unknown 保守方向」两半）
            check(detail.get("env_red_state") in ("none", "named", "unnameable"),
                  "L3c ①环境红面带三态标注（实得 %r）" % detail.get("env_red_state"))
            check(int(detail.get("env_red_count") or 0)
                  == int((detail.get("counts") or {}).get("env_fail") or 0),
                  "L3c ①环境红计数与 counts.env_fail 一致")
            if not int((detail.get("counts") or {}).get("env_fail") or 0):
                check(detail.get("env_red_state") == "none",
                      "L3c ①无环境红 → none（票面不加环境红段）")
            attr_e2e = detail.get("attribution") or {}
            labeled = (list(attr_e2e.get("lane_only") or []) + list(attr_e2e.get("main_red_too") or [])
                       + list(attr_e2e.get("unknown") or []))
            check(sorted(labeled) == sorted(detail.get("violations") or []),
                  "L3c ③逐名归因覆盖**每一个**红名（%d 名；三类=%d）"
                  % (len(detail.get("violations") or []), len(labeled)))
            check("NEVER read as main-green" in str(attr_e2e.get("rule") or ""),
                  "L3c ③unknown 的保守口径在结构化面点名")
            check("Red attribution against main" in (reason or ""),
                  "L3c ③归因面进 blocked 文案")
            check("unknown (no baseline answer — NOT main-green and NOT a landing permit)"
                  in (reason or "") if attr_e2e.get("unknown") else True,
                  "L3c ③有 unknown 时文案点名其保守读法")
            kr_e2e = (detail.get("round") or {}).get("known_red")
            check(isinstance(kr_e2e, dict) and kr_e2e.get("injected") is True,
                  "L3c ②在册红豁免面：注入事实可见（实得 %r）" % (kr_e2e,))
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

        # ---------- L3e rework 拒收面：打回已删段必须具名拒收（不落未知相位） ----------
        n_disp_before = len(stub_stages_of(TID))
        rw = cli(py, stage, "ticket", {"op": "rework", "ticket_id": TID,
                                       "to_stage": "create_plan",
                                       "note": "e2e: ask for a stage this lane does not have",
                                       "by": "e2e-human"})
        check(rw.get("ok") is True, "L3e rework 信号受理（%s）"
              % str(rw.get("error") or "")[:120])
        refused_snap = wait_snap(fail, py, stage, TID,
                                 lambda x: any(str(r.get("want") or "") == "rework(create_plan)"
                                               for r in (x.get("refused") or [])),
                                 "L3e 已删段的 rework 落 refused 记录", 180)
        if refused_snap is not None:
            why = "; ".join(str(r.get("why") or "") for r in (refused_snap.get("refused") or []))
            check("not a light-lane stage" in why and "create_plan" in why,
                  "L3e 拒收面具名（点名目标不是轻道段；实得 %r）" % why[:200])
            check("implement" in why,
                  "L3e 拒收面列出合法目标（含 implement）")
            check(str(refused_snap.get("stage")) in LIGHT_STAGES,
                  "L3e 拒收后票仍在轻道段内（不落未知相位；实得 %r）"
                  % refused_snap.get("stage"))
            check(len(stub_stages_of(TID)) == n_disp_before,
                  "L3e 拒收没有触发任何 agent 派单（本票账本零增长：%d→%d）"
                  % (n_disp_before, len(stub_stages_of(TID))))

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
                  "L5 全链 timeline 零被裁段（create_plan/审方案/集测设计/仲裁/走查）")
            check("ui_evidence" not in tl3,
                  "L5 **非 UI 票**：全链时间线零 ui_evidence（条件段不适用；UI 票见 L2c）")
            tl3_ids = [str(e.get("stage")) for e in tl3]
            check("create_plan" not in tl3_ids and bool(tl3_ids)
                  and tl3_ids[0] == "implement",
                  "L5 **轻道没有方案段**且首段即 implement（全链时间线首项=%r）"
                  % (tl3_ids[0] if tl3_ids else None))
            # L5b rework 实证：打回 implement（首段）→ agent 真重跑 → 重走闸 → 回到人门
            n_impl_before = len([st for st in stub_stages_of(TID) if st == "implement"])
            rw2 = cli(py, stage, "ticket", {"op": "rework", "ticket_id": TID,
                                            "to_stage": "implement",
                                            "note": "e2e: send it back to the first stage",
                                            "by": "e2e-human"})
            check(rw2.get("ok") is True, "L5b rework(to_stage=implement) 受理（%s）"
                  % str(rw2.get("error") or "")[:120])
            back = wait_snap(fail, py, stage, TID,
                             lambda x: x.get("stage") == "merge"
                             and x.get("stage_state") == "awaiting-human"
                             and len([e for e in (x.get("timeline") or [])
                                      if str(e.get("stage")) == "implement"
                                      and str(e.get("state")) == "running"]) >= 2,
                             "L5b rework 后重走全链回到人门（implement 二次进入）", 420)
            if back is not None:
                n_impl_after = len([st for st in stub_stages_of(TID) if st == "implement"])
                check(n_impl_after == n_impl_before + 1,
                      "L5b rework **落到首段 implement**（agent 真重跑：派单账本 %d→%d）"
                      % (n_impl_before, n_impl_after))
                tl_back = [str(e.get("stage")) for e in (back.get("timeline") or [])]
                check("create_plan" not in tl_back and "ui_evidence" not in tl_back,
                      "L5b 重走后仍零被裁段（实得 %r）" % sorted(set(tl_back)))
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
                my_branch = str(((fin.get("meta") or {}).get("branch")) or "")
                rc2, heads = git("branch", "--list", "lane/*")
                check(rc2 == 0 and bool(my_branch) and my_branch not in heads,
                      "L5 本票泳道分支已删（branch=%r；现存 lane/*=%r）"
                      % (my_branch, heads.strip()[:120]))
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
            stop_all_workers(fail, "L6 收尾")
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
