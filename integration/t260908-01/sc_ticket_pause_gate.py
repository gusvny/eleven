#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260908-01 场景：工单段间暂停/恢复（pause/resume）全链路 + 通用性断言。

intent（守护的用户可感知行为，宿主 260908 拍板①-④的验收面）：
- 段间暂停粒度：进行中的工单按「暂停」→ 当前段（含在飞 agent activity）自然跑完，
  workflow 停在段间门口（snapshot.paused=true、paused_phase=at_gate、timeline 有
  paused-waiting），观察窗内不派下一段；「恢复」→ timeline resumed、接着走完全链
  到 closed。
- 反馈可辨（信号幂等）：重复 pause → refused 点名「已暂停」语义；空态 resume →
  refused 点名「未暂停」语义；畸形 payload（who 纯空白 / note 超限）→ intake gate
  拒收且置位不发生（paused 恒 false）。
- 列表入口数据源契约：暂停中 ticket-list 行携带 paused 标记（UI 徽标的唯一数据源）。
- pause×rework 显式语义：暂停中发 rework 压在门口不执行；恢复后先打回（目标段
  重新进入）再推进。
- 仅人门：pause/resume 只经 client.py ticket op 信号通道（本场景全部信号走该通道，
  与 sign/rework 同族）；对未注册模板（通用性 env 门关）开票即拒且点名「未知模板」。
- 通用性（拍板④）：同一暂停行为在一个**非 dev-lane 模板**（fixture_two_step，
  SANDBAR_FIXTURE_TEMPLATES=1 环境门注册）上同样生效——新模板接线即生效。

灰盒声明：断言只落公开契约面——client.py CLI 结构化回执（ok/error）、ticket-query
snapshot 键（paused/paused_phase/timeline/refused/results/meta）、ticket-list 行键、
「未知模板」拒收语义。文案锚语义词（已暂停/未暂停/非空/超限/未知模板）不锚字面全句
（KI-051 纪律）；不 import 引擎内部、不读 workflow 私有结构。

拓扑与嵌套护栏收窄声明（review_plan R3 核准形态）：
- 舞台=stage_docker 单点起 temporal-only 一次性测试台（带内随机端口，生产端口集
  硬禁）；docker/镜像缺席=ENV_FAIL exit 2 点名。
- 被测链路=真 DevLaneWorkflow+真 activities+桩大脑（SANDBAR_AGENT_STUB=1），worker
  从**夹具仓**（本仓 --depth 1 clone）的引擎起——泳道/settle/merge 全在夹具仓内，
  真仓零接触（ticket-lifecycle 先例形态）。
- 一切子进程 env 剥除泳道 worker 标记三件套（SANDBAR_TASK_QUEUE/SANDBAR_TASK_QUEUES/
  SANDBAR_WATCH_WORKFLOW）后显式钉死：队列=sandbar-ticket-<本场景票id>（绝不含泳道
  队列）、SANDBAR_TARGET_HOST=本场景舞台地址。递归不可能：①舞台是一次性服务端，
  泳道引擎物理不连它；②子 env 无泳道标记；③L0 自证腿断言剥除生效。护栏原文
  （sc_ticket_lifecycle.mjs nestedGuard）与其移出闸处置不动——本场景拓扑不同，
  递归论据按构造不成立，闸内（docker 在场）可到 PASS。
- 写守卫：开票子进程的 SANDBAR_TARGET_HOST 恒=本场景舞台地址（L0 断言该地址
  host=127.0.0.1 且端口 ∉ stage_docker.FORBIDDEN_PORTS）；绝不缺省回落生产 7233。

预算注记：900s/条（run_scenarios CMD_TIMEOUT）。桩脑+短路（t260908-01 KI-061 票
已把 arbitrate/acceptance_walkthrough 接上 stub 短路）下主旅程实测分钟级；两票共用
一台一夹具仓。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

KI 相邻面：KI-008（暂停中 snapshot 可查=门是 await 点，L3.2 显式断言查询照常）；
KI-018（暂停期相位语境=paused_phase 二态+timeline 标记，防「信号存在但误导」）；
KI-003（patched 回放安全与老实例拒收文案归 developer selfcheck_pause.py——行为面
合成不出 pre-patch history，本场景不做伪覆盖，review_plan 附条件②钦定）。

t260914-04 扩腿（KI-079 收口，review_plan C1-C5 条件已内建）：
- L0b=离线契约腿：调 integration/t260914-04/offline_ticket_pause_entry.py（零
  Temporal：ticket.py pause/resume 包装层载荷逐键/D1 身份闸/CLI 畸形输入）；
- L3.6b=正规入口腿：宪章所教形式经**真仓工作树** ticket.py（C1：夹具仓 clone 自
  HEAD 没有 implement 期新 op；既有 CLI 腿本就跑真仓 client.py 同口径）——回执 ok
  且无 entry_hint、refused who=注入身份、本票 snapshot timeline+refused 零
  op-local、缺 by 在 CLI 层拒收。
- 层次分工（C5）：「who 空白→workflow refused」仍由 L3.1 裸入口腿承载；「重复
  pause/空态 resume/note 超限」两入口各验一笔，正规入口这轮断 who==注入值（C3：
  timeline 身份断言用 any 命中口径，op-local 零命中限定本票 snapshot 范围）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))  # lib_gate 共享腿（先例场景同仓复用）
sys.path.insert(0, INTEG)                              # stage_docker 单点
from lib_gate import (Fail, cleanup, parse_out_json, poc_python, port_listening,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
import stage_docker  # noqa: E402

LANE_MARKERS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW")
FIXTURE_TEMPLATE_ID = "fixture-two-step"   # 方案钉名：server/engine/fixtures/fixture_two_step.py 注册的模板 id
EPIC_CODE = "integ-pause"
PROJECT_KEY = "sandbar"
NOTE_LIMIT = 20000                         # PAUSE_NOTE_INPUT_LIMIT 契约值（host_ruling 同源）

G = {"tmp": "", "fixture": "", "projects": "", "epics": ""}


# ------------------------------------------------------------------ 基础腿

def env_for(stage, extra=None):
    """子进程 env：剥泳道标记三件套 + 钉舞台地址/命名空间/夹具注册表。写守卫在此单点。"""
    env = dict(os.environ)
    for k in LANE_MARKERS:
        env.pop(k, None)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = stage["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = G["projects"]
    env["SANDBAR_EPICS_DIR"] = G["epics"]
    if extra:
        env.update(extra)
    return env


def cli(py, stage, sub, args, extra=None, timeout=180):
    """跑 client.py <sub> <argsJSON>，返回解析后的回执 dict（取不到={}）。"""
    rc, out = run_poc_client(py, sub, args, env_for(stage, extra), timeout=timeout)
    return parse_out_json(out)


def tk_cli(py, stage, payload, timeout=180):
    """跑真仓工作树 server/tools/ticket.py <整条 JSON>（t260914-04 正规入口）。

    C1（review_plan）：必须走真仓工作树——既有 CLI 腿跑的就是真仓 client.py
    （run_poc_client，cwd=REPO），夹具仓 clone 自 HEAD、implement 期没有新 op；
    SANDBAR_ADMIN_LOG 指场景 tmp（C6，sc_ki067_entry_audit 先例）。返回解析后的
    回执 dict（ticket.py 直 spawn=stdout 单行 JSON 契约）。"""
    env = env_for(stage, {"SANDBAR_ADMIN_LOG": os.path.join(G["tmp"], "admin-entry.log")})
    p = subprocess.run([py, os.path.join(REPO, "server", "tools", "ticket.py"),
                        json.dumps(payload, ensure_ascii=False)],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return parse_out_json((p.stdout or "") + (p.stderr or ""))


def wait_snap(fail, py, stage, tid, pred, label, deadline_s):
    """轮询 ticket-query 直到 pred(snapshot) 成立。返回 snapshot 或 None（已计红）。

    COMPLETED 票由 result() 路径回最终 snapshot（client.py 公开契约），全程可轮。"""
    t0 = time.time()
    snap = None
    while time.time() - t0 < deadline_s:
        body = cli(py, stage, "ticket-query", {"ticket_id": tid})
        if body.get("ok"):
            snap = (body.get("result") or {}).get("snapshot")
            if isinstance(snap, dict) and pred(snap):
                return snap
        else:
            err = str(body.get("error") or "")
            if "不存在" in err or "not found" in err.lower():
                fail.check(False, "%s：workflow 消失（%s）" % (label, err[:120]))
                return None
        time.sleep(2)
    tail = ""
    if isinstance(snap, dict):
        tl = snap.get("timeline") or []
        if tl:
            last = tl[-1]
            tail = "｜timeline 末条 %s/%s: %s" % (last.get("stage"), last.get("state"),
                                            str(last.get("reason") or "")[:160])
    fail.check(False, "%s：%ds 超时（末态 stage=%s/%s status=%s%s）"
               % (label, deadline_s,
                  (snap or {}).get("stage"), (snap or {}).get("stage_state"),
                  (snap or {}).get("status"), tail))
    return None


def refused_has(snap, want_sub, why_sub):
    """snapshot.refused 中存在 want 含 want_sub 且 why 含 why_sub 的条目（语义锚）。"""
    for r in (snap or {}).get("refused") or []:
        if want_sub in str(r.get("want") or "") and why_sub in str(r.get("why") or ""):
            return True
    return False


def refused_who_among(snap, want_sub, why_sub, who):
    """refused 中 want/why 语义匹配条目里**是否存在**该 who（身份透传的机械断言）。

    必须是存在性判定，不能写「首条匹配的 who == 注入值」：同一语义锚的既有腿条目
    （L3.1/L3.3 全是 e2e-host）排在更早、首条永远是它们——首条相等式 wait 谓词永假
    ＝实现正确也假红（t260914-04 design 段修正）。"""
    for r in (snap or {}).get("refused") or []:
        if (want_sub in str(r.get("want") or "") and why_sub in str(r.get("why") or "")
                and str(r.get("who") or "") == who):
            return True
    return False


def timeline_states(snap, state_sub):
    return [e for e in (snap or {}).get("timeline") or []
            if state_sub in str(e.get("state") or "")]


def stage_running_marks(snap, stage_id):
    return [e for e in (snap or {}).get("timeline") or []
            if str(e.get("stage") or "") == stage_id and str(e.get("state") or "") == "running"]


def build_fixture(fail):
    """夹具仓=本仓 --depth 1 clone + 注册表/立项单 fixture 化 + 依赖软链（precedent 形态）。

    泳道/settle/merge 全落夹具仓；真仓零接触。返回 False=已计环境红。"""
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="t26090801-pause-"))
    # realpath 归一（r6 实证）：macOS 上 mkdtemp 给 /var/folders/...（/var 是
    # /private/var 的 symlink），而引擎 REPO_ROOT 走 Path.resolve()——两侧路径
    # 不归一会被 _ensure_lane_deps 判成「跨项目泳道」跳过依赖软链（泳道无 .venv
    # → merge_check 的 verify_lane pytest 红）。闸内路径无 symlink 时本行是恒等。
    G["tmp"] = tmp
    common = subprocess.run(["git", "-C", REPO, "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True, timeout=30)
    main_checkout = os.path.dirname(common.stdout.strip()) if common.returncode == 0 else ""
    fixture = os.path.join(tmp, "fixture")
    clone = subprocess.run(["git", "clone", "--depth", "1", REPO, fixture],
                           capture_output=True, text=True, timeout=300)
    if clone.returncode != 0:
        fail.bail("git clone 夹具仓失败（环境）：%s" % (clone.stderr or clone.stdout)[:200],
                  stage_docker.EXIT_ENV)
    G["fixture"] = fixture
    # 基线分支对齐（t260908-01 implement r5 实证）：--depth 1 clone 的默认分支名
    # 跟随源仓 HEAD 分支（泳道分支名），不是 main——merge_check 的写集白名单基线
    # merge-base main × lane/<tid> 会 rc=128 红灯。当前分支统一改名 main。
    cur_br = subprocess.run(["git", "-C", fixture, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, timeout=15)
    if cur_br.returncode == 0 and cur_br.stdout.strip() != "main":
        ren = subprocess.run(["git", "-C", fixture, "branch", "-m", "main"],
                             capture_output=True, text=True, timeout=15)
        if ren.returncode != 0:
            fail.bail("夹具仓基线分支改名 main 失败：%s" % (ren.stderr or ren.stdout)[:160],
                      stage_docker.EXIT_ENV)
    subprocess.run(["git", "-C", fixture, "config", "user.email", "e2e@pause.test"], timeout=15)
    subprocess.run(["git", "-C", fixture, "config", "user.name", "integ-pause-e2e"], timeout=15)
    # 项目注册表 fixture 化（KI-032 硬闸消费面：ticket-start 带 project 必过锚定）
    projects = os.path.join(fixture, ".e2e-projects")
    os.makedirs(os.path.join(projects, PROJECT_KEY), exist_ok=True)
    with open(os.path.join(projects, ".migrated"), "w") as f:
        f.write("fixture-local hermetic registry (ticket-pause e2e)\n")
    with open(os.path.join(projects, PROJECT_KEY, "project.yaml"), "w") as f:
        f.write("# fixture-local registry：dirs -> 夹具仓自身，全链隔离机器态\n"
                "schema: v1\nproject:\n  - key: %s\n    name: integ-pause-fixture\n"
                "    dirs:\n      - %s\n" % (PROJECT_KEY, fixture))
    G["projects"] = projects
    # 立项单（ticket-start epic 校验）
    epics = os.path.join(fixture, "notes", "epics")
    os.makedirs(epics, exist_ok=True)
    with open(os.path.join(epics, "%s.md" % EPIC_CODE), "w") as f:
        f.write("# 立项单：integ-pause\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `%s` |\n"
                "| 状态 | 已立项（执行中） |\n" % EPIC_CODE)
    G["epics"] = epics
    # 引擎 venv 软链（prepare_workspace 的 LANE_DEP_SYMLINKS 消费面）
    if main_checkout:
        target = os.path.join(main_checkout, "server", "engine", ".venv")
        link = os.path.join(fixture, "server", "engine", ".venv")
        if os.path.isdir(target) and not os.path.exists(link):
            os.symlink(target, link)
    return True


def start_worker(py, stage, tid, fixture_templates=False):
    """从夹具仓引擎起桩脑 worker：钉本票专属队列+剥泳道标记（env_for 单点）。"""
    extra = {
        "SANDBAR_TASK_QUEUES": "sandbar-ticket-%s" % tid,
        "SANDBAR_WATCH_WORKFLOW": tid,
        "SANDBAR_WATCH_INTERVAL_SEC": "4",     # watch 快档（t260905-02 旋钮，收票即退）
        "SANDBAR_AGENT_STUB": "1",             # 桩大脑：自写结果文件，零模型调用
        "SANDBAR_AGENT_STUB_DELAY_SEC": "6",   # 桩段时长（t260908-01 引擎旋钮）：
                                               # 确定性的「段在飞」窗口——秒过桩段下
                                               # 暂停信号永远落在段外，在飞粒度不可验
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    if fixture_templates:
        extra["SANDBAR_FIXTURE_TEMPLATES"] = "1"
    log = open(os.path.join(G["tmp"], "worker-%s.log" % tid), "w")
    return subprocess.Popen([py, os.path.join(G["fixture"], "server", "engine", "worker.py")],
                            env=env_for(stage, extra), stdout=log, stderr=subprocess.STDOUT)


def stop_worker(fail, proc, label):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
        fail.check(True, "%s：worker TERM 后 20s 内退出（资源回收）" % label)
    except Exception:
        fail.check(False, "%s：worker TERM 20s 未退（kill 兜底前先计红）" % label)
        proc.kill()
        proc.wait(timeout=10)


def ticket_start(py, stage, tid, template_id, extra=None):
    return cli(py, stage, "ticket-start", {
        "ticket_id": tid, "template_id": template_id, "project": PROJECT_KEY,
        "title": "[e2e] 段间暂停 %s" % tid, "epic": EPIC_CODE,
        "user_request": "integration e2e: ticket pause gate",
        "write_set": ["integration/e2e-probe-%s.txt" % tid],
    }, extra=extra)


def signal_pause(py, stage, tid, who, note=""):
    return cli(py, stage, "ticket", {"op": "pause", "ticket_id": tid,
                                     "input": {"who": who, "note": note}})


def signal_resume(py, stage, tid, who, note=""):
    return cli(py, stage, "ticket", {"op": "resume", "ticket_id": tid,
                                     "input": {"who": who, "note": note}})


# ------------------------------------------------------------------ 主流程

def main():
    fail = Fail("t260908-01 工单段间暂停/恢复（pause/resume）门")
    bench = require_bench(fail)
    py = poc_python(bench)
    workers = []
    slot = None
    stage_mod, stage = None, None
    try:
        # ---------- L0 环境链 + 拓扑自证 ----------
        stage_mod, stage = require_stage(fail, "t26090801-pause-%d" % os.getpid(),
                                         "stage-pause-%d" % os.getpid())
        slot = stage["project"]
        fe = int(stage["ports"]["temporal"])
        fail.check(port_listening(fe), "L0 舞台 temporal %d 探活" % fe)
        fail.check(fe not in stage_docker.FORBIDDEN_PORTS,
                   "L0 写守卫：舞台端口 %d ∉ 禁区 %s（绝不回落生产 7233）"
                   % (fe, sorted(stage_docker.FORBIDDEN_PORTS)))
        env0 = env_for(stage)
        fail.check(all(k not in env0 for k in LANE_MARKERS),
                   "L0 拓扑自证：子进程 env 已剥泳道标记三件套 %s" % (LANE_MARKERS,))
        fail.check(env0["SANDBAR_TARGET_HOST"] == "127.0.0.1:%d" % fe,
                   "L0 写守卫：开票面 SANDBAR_TARGET_HOST 恒=本场景舞台地址")
        build_fixture(fail)

        # ---------- L0b 离线契约腿（t260914-04）：ticket.py pause/resume 包装层 ----------
        # 零 Temporal（载荷形状/D1 身份闸/CLI 畸形输入）；单独可秒跑，闸内由此携带执行。
        off = subprocess.run([sys.executable,
                              os.path.join(REPO, "integration", "t260914-04",
                                           "offline_ticket_pause_entry.py")],
                             cwd=REPO, capture_output=True, text=True, timeout=120)
        off_tail = ((off.stdout or "").strip().splitlines() or [""])[-1]
        fail.check(off.returncode == 0,
                   "L0b 离线契约脚本全绿（包装层载荷/D1/畸形输入；实得 %s）"
                   % (off_tail or (off.stderr or "")[:120]))

        # ---------- L1 通用性 env 门负腿：门关时 fixture 模板不可开票 ----------
        neg = ticket_start(py, stage, "pause-e2e-neg-%x" % os.getpid(), FIXTURE_TEMPLATE_ID)
        fail.check(neg.get("ok") is False and "未知模板" in str(neg.get("error") or ""),
                   "L1 env 门关：fixture 模板开票即拒且点名「未知模板」（实得 %s）"
                   % str(neg.get("error") or neg)[:160])

        # ---------- L2 通用性腿：非 dev-lane 模板同款暂停生效 ----------
        tid2 = "pause-e2e-fx-%x" % os.getpid()
        w2 = start_worker(py, stage, tid2, fixture_templates=True)
        workers.append(w2)
        r2 = ticket_start(py, stage, tid2, FIXTURE_TEMPLATE_ID,
                          extra={"SANDBAR_FIXTURE_TEMPLATES": "1"})
        fail.check(r2.get("ok") is True,
                   "L2 env 门开：fixture 两段模板开票成功（实得 %s）"
                   % str(r2.get("error") or r2.get("result") or r2)[:160])
        if r2.get("ok") is True:
            s = wait_snap(fail, py, stage, tid2,
                          lambda x: bool(x.get("stage")) and x.get("stage_state") == "running",
                          "L2 首段进入 running", 240)
            if s:
                p2 = signal_pause(py, stage, tid2, "e2e-host", "通用性腿暂停")
                fail.check(p2.get("ok") is True, "L2 pause 信号通道回执 ok（人门通道）")
                s = wait_snap(fail, py, stage, tid2,
                              lambda x: x.get("paused") is True and x.get("paused_phase") == "at_gate",
                              "L2 停在段间门口（paused+at_gate）", 240)
                if s:
                    fail.check(bool(timeline_states(s, "paused-waiting")),
                               "L2 timeline 有 paused-waiting 标记")
                    s0 = str(s.get("stage") or "")
                    # 观察窗：不派下一段（stage 冻结）
                    frozen = True
                    t0 = time.time()
                    while time.time() - t0 < 20:
                        cur = cli(py, stage, "ticket-query", {"ticket_id": tid2})
                        cs = (cur.get("result") or {}).get("snapshot") or {}
                        if str(cs.get("stage") or "") != s0 or cs.get("paused") is not True:
                            frozen = False
                            break
                        time.sleep(2)
                    fail.check(frozen, "L2 观察窗 20s 内不派下一段（stage 冻结于 %r）" % s0)
                    signal_resume(py, stage, tid2, "e2e-host")
                    fin = wait_snap(fail, py, stage, tid2,
                                    lambda x: x.get("status") == "closed",
                                    "L2 恢复后走完（closed）", 300)
                    if fin:
                        fail.check(bool(timeline_states(fin, "resumed")),
                                   "L2 timeline 有 resumed 标记")
                        fail.check(fin.get("paused") is False,
                                   "L2 终态 paused=false（置位清干净）")

        # ---------- L3 主旅程：dev-lane 真链路 ----------
        tid1 = "pause-e2e-main-%x" % os.getpid()
        w1 = start_worker(py, stage, tid1)
        workers.append(w1)
        r1 = ticket_start(py, stage, tid1, "dev-lane")
        fail.check(r1.get("ok") is True, "L3 dev-lane 开票 ok（实得 %s）"
                   % str(r1.get("error") or r1)[:160])
        if r1.get("ok") is not True:
            fail.bail("dev-lane 开票失败，主旅程无从谈起", 1)

        # L3.1 反馈腿（暂停前）：空态 resume + 畸形 pause 双形态，全部可辨拒收且不置位。
        # 拒收可落两层（皆合法）：CLI 结构化拒收（ok:false+语义词）或 workflow refused
        # 清单条目——断言「可辨拒收发生」这个 intent，不锚拒收落在哪一层。
        cases = [
            ("resume-empty", signal_resume(py, stage, tid1, "e2e-host"), "resume", "未"),
            ("pause-who-blank", signal_pause(py, stage, tid1, "   "), "pause", "非空"),
            ("pause-note-over", signal_pause(py, stage, tid1, "e2e-host", "x" * (NOTE_LIMIT + 1)),
             "pause", "超限"),
        ]
        def _case_settled(snap):
            for name, receipt, want_sub, why_sub in cases:
                cli_refused = receipt.get("ok") is False and why_sub in str(receipt.get("error") or "")
                if not cli_refused and not refused_has(snap, want_sub, why_sub):
                    return False
            return True
        s = wait_snap(fail, py, stage, tid1, _case_settled,
                      "L3.1 空态 resume/who 空白/note 超限 三笔拒收可辨（CLI 层或 refused 清单）", 120)
        if s:
            fail.check(s.get("paused") is False,
                       "L3.1 畸形/空态信号全拒收不置位（paused 恒 false）")

        # L3.2 暂停门：在飞段（create_plan running）发 pause → 段自然跑完 → 停门口
        s = wait_snap(fail, py, stage, tid1,
                      lambda x: x.get("stage") == "create_plan" and x.get("stage_state") == "running",
                      "L3.2 create_plan 在飞", 240)
        if not s:
            fail.bail("create_plan 迟迟未在飞——stub 链路未交付或舞台异常", 1)
        signal_pause(py, stage, tid1, "e2e-host", "主旅程暂停")
        s = wait_snap(fail, py, stage, tid1,
                      lambda x: x.get("paused") is True and x.get("paused_phase") == "at_gate",
                      "L3.2 在飞段跑完后停在段间门口", 240)
        if not s:
            fail.bail("暂停门未生效（240s 未到 at_gate）", 1)
        fail.check(bool((s.get("results") or {}).get("create_plan")),
                   "L3.2 段间粒度：暂停时 create_plan 已自然跑完（results 有本段条目）")
        fail.check(bool(timeline_states(s, "paused-waiting")),
                   "L3.2 timeline 有 paused-waiting（暂停期相位语境，KI-018 面）")
        q = cli(py, stage, "ticket-query", {"ticket_id": tid1})
        fail.check(q.get("ok") is True and isinstance((q.get("result") or {}).get("snapshot"), dict),
                   "L3.2 暂停中 snapshot 照常可查（门是 await 点，KI-008 面）")
        s0 = str(s.get("stage") or "")
        frozen = True
        t0 = time.time()
        while time.time() - t0 < 25:
            cur = cli(py, stage, "ticket-query", {"ticket_id": tid1})
            cs = (cur.get("result") or {}).get("snapshot") or {}
            if str(cs.get("stage") or "") != s0:
                frozen = False
                break
            time.sleep(2)
        fail.check(frozen, "L3.2 观察窗 25s 不派下一段（stage 冻结于 %r）" % s0)

        # L3.3 幂等：重复 pause → refused 可辨
        signal_pause(py, stage, tid1, "e2e-host", "重复暂停")
        s = wait_snap(fail, py, stage, tid1,
                      lambda x: refused_has(x, "pause", "已") and
                                any("暂停" in str(r.get("why") or "") for r in x.get("refused") or []),
                      "L3.3 重复 pause refused 点名「已暂停」语义", 90)
        if s:
            fail.check(s.get("paused") is True, "L3.3 重复 pause 是幂等拒绝不翻状态")

        # L3.4 列表行数据源契约：暂停中 ticket-list 行带 paused
        body = cli(py, stage, "ticket-list", {"project": PROJECT_KEY})
        rows = (body.get("result") or {}).get("tickets") or []
        row = next((r for r in rows if r.get("id") == tid1), None)
        fail.check(row is not None, "L3.4 ticket-list 含本票行（列表入口数据源）")
        if row is not None:
            fail.check(row.get("paused") is True,
                       "L3.4 暂停中列表行 paused=true（UI 徽标数据源契约；实得 %r）"
                       % row.get("paused"))

        # L3.5 pause×rework：暂停中 rework 压门口不执行
        cli(py, stage, "ticket", {"op": "rework", "ticket_id": tid1,
                                  "to_stage": "create_plan", "who": "e2e-host",
                                  "note": "e2e：暂停中打回应压门口"})
        held = True
        t0 = time.time()
        while time.time() - t0 < 15:
            cur = cli(py, stage, "ticket-query", {"ticket_id": tid1})
            cs = (cur.get("result") or {}).get("snapshot") or {}
            if len(stage_running_marks(cs, "create_plan")) > 1:
                held = False
                break
            time.sleep(2)
        fail.check(held, "L3.5 暂停中 rework 压门口不执行（create_plan 未重进入）")

        # L3.6 恢复：先打回（create_plan 重进入）再推进
        signal_resume(py, stage, tid1, "e2e-host")
        s = wait_snap(fail, py, stage, tid1,
                      lambda x: len(stage_running_marks(x, "create_plan")) >= 2,
                      "L3.6 resume 后先执行压门口的 rework（create_plan 重进入）", 300)
        if s:
            tl = s.get("timeline") or []
            resumed_idx = next((i for i, e in enumerate(tl)
                                if "resumed" in str(e.get("state") or "")), -1)
            second_cp = [i for i, e in enumerate(tl)
                         if str(e.get("stage") or "") == "create_plan"
                         and str(e.get("state") or "") == "running"]
            fail.check(resumed_idx >= 0 and len(second_cp) >= 2 and second_cp[1] > resumed_idx,
                       "L3.6 因果序：resumed 在前、打回重进入在后")
            fail.check(bool([e for e in tl if "rework" in str(e.get("state") or "")]),
                       "L3.6 timeline 有 rework 痕迹（打回可观测）")

        # ---------- L3.6b 正规入口腿（t260914-04，KI-079）：宪章所教形式经 ticket.py ----------
        # 落点=C2：只落 tid1、L3.6 之后（L3.7 末断言读首个 paused-waiting/resumed 的
        # 首现序，本周期晚于首现不扰动），且以 resume 收尾（否则 L3.7 的 merge 人门
        # 会被暂停门挡住）。C5 分工：「who 空白→workflow refused」由 L3.1 裸入口腿
        # 承载，正规入口在 CLI 层即拒（D1）；note 长度不在 CLI 层抢答（单点=workflow
        # intake），故 note 超限经正规入口仍落 refused。
        tk_who = "charter-human"
        p0 = tk_cli(py, stage, {"op": "pause", "id": tid1, "by": tk_who,
                                "note": "正规入口腿暂停"})
        fail.check(p0.get("ok") is True and (p0.get("result") or {}).get("delivered") is True,
                   "L3.6b 宪章形式 pause 经 ticket.py 回执 ok（验收①；实得 %s）"
                   % str(p0.get("error") or p0)[:160])
        fail.check("entry_hint" not in json.dumps(p0),
                   "L3.6b 正规入口回执无 entry_hint（非裸入口待遇）")
        wait_snap(fail, py, stage, tid1,
                  lambda x: x.get("paused") is True and x.get("paused_phase") == "at_gate",
                  "L3.6b 正规入口 pause 停段间门口", 240)
        # 重复 pause + note 超限：回执都是投递 ok——拒收判定在 workflow intake
        tk_cli(py, stage, {"op": "pause", "id": tid1, "by": tk_who, "note": "重复暂停"})
        tk_cli(py, stage, {"op": "pause", "id": tid1, "by": tk_who,
                           "note": "x" * (NOTE_LIMIT + 1)})
        wait_snap(fail, py, stage, tid1,
                  lambda x: (refused_who_among(x, "pause", "已", tk_who)
                             and refused_who_among(x, "pause", "超限", tk_who)),
                  "L3.6b 重复 pause/note 超限 落 refused 且 who=注入值（验收④）", 120)
        # 恢复（正规入口）+ 空态 resume：拒收语义与裸口一致
        r0 = tk_cli(py, stage, {"op": "resume", "id": tid1, "by": tk_who})
        fail.check(r0.get("ok") is True and (r0.get("result") or {}).get("delivered") is True,
                   "L3.6b 正规入口 resume 回执 ok（以 resume 收尾，C2b）")
        tk_cli(py, stage, {"op": "resume", "id": tid1, "by": tk_who})
        wait_snap(fail, py, stage, tid1,
                  lambda x: x.get("paused") is False
                            and refused_who_among(x, "resume", "未", tk_who),
                  "L3.6b 恢复生效+空态 resume refused 且 who=注入值（验收④）", 120)
        # D1 负锁：缺 by → CLI 层结构化拒收（不触引擎，票不置位）
        d1 = tk_cli(py, stage, {"op": "pause", "id": tid1})
        fail.check(d1.get("ok") is False and "by|who" in str(d1.get("error") or ""),
                   "L3.6b 缺 by → CLI 层结构化拒收（D1；C5：不进 refused[]；实得 %s）"
                   % str(d1)[:160])
        # who 机械断言（验收②；C3 口径=any 命中 + 限定本票 snapshot timeline+refused）
        cur = cli(py, stage, "ticket-query", {"ticket_id": tid1})
        cs = (cur.get("result") or {}).get("snapshot") or {}
        hits = [e for e in (cs.get("timeline") or [])
                if tk_who in str(e.get("reason") or "")]
        fail.check(bool(hits), "L3.6b timeline 有含注入身份 %r 的条目（C3 any 口径）" % tk_who)
        blob = json.dumps({"timeline": cs.get("timeline") or [],
                           "refused": cs.get("refused") or []}, ensure_ascii=False)
        fail.check("op-local" not in blob,
                   "L3.6b 本票 snapshot timeline+refused 全量零 op-local（验收②）")

        # L3.7 恢复后走完：探针脏泳道 → run_integration_tests 窗口预置仲裁 pass →
        # merge 人门 sign approve → closed
        lane = str(((s or {}).get("meta") or {}).get("workspace", {}) and
                   ((s.get("meta") or {}).get("workspace") or {}).get("path") or "")
        if not lane:
            cur = cli(py, stage, "ticket-query", {"ticket_id": tid1})
            lane = str((((cur.get("result") or {}).get("snapshot") or {})
                        .get("meta") or {}).get("workspace", {}).get("path") or "")
        fail.check(bool(lane) and os.path.isabs(lane),
                   "L3.7 泳道路径绝对锚定（KI-032 面；实得 %r）" % lane)
        if lane:
            probe = os.path.join(lane, "integration", "e2e-probe-%s.txt" % tid1)
            os.makedirs(os.path.dirname(probe), exist_ok=True)
            with open(probe, "w") as f:
                f.write("probe by ticket-pause e2e\n")
            # 预置仲裁 verdict=pass（幂等缓存路径，_stub_stage_shortcut 消费）。
            # 不依赖捕捉 run_integration_tests 相位窗：verify_lane 在夹具仓秒红，
            # 相位以秒计，2s 轮询大概率错过（首跑实证 420s 超时=窗口错过非链断）——
            # 早置文件静静等消费即可，gen=现存最大+1（首轮 arbitrate=gen0）。
            # 点目录与引擎 resolve_dot_dir 同规则：新名 .sandbar 优先、旧名
            # .suyou 仅粘性回落（naming-compat：目录读侧回落）——夹具泳道是新道，
            # 仲裁结果幂等缓存在 .sandbar/（t260908-01 implement 修正：初版照
            # ticket-lifecycle 先例写死 .suyou（naming-compat：先例旧名引用），
            # 新道引擎读不到=预置失效，L3.7 必红）。
            sdir = os.path.join(lane, ".sandbar")
            legacy_dir = os.path.join(lane, ".suyou")  # naming-compat：旧点目录粘性回落判定
            if not os.path.isdir(sdir) and os.path.isdir(legacy_dir):
                sdir = legacy_dir
            os.makedirs(sdir, exist_ok=True)
            gen = 0
            for fn in os.listdir(sdir):
                if fn.startswith("stage_arbitrate_gen") and fn.endswith(".json"):
                    try:
                        gen = max(gen, int(fn[len("stage_arbitrate_gen"):-len(".json")]) + 1)
                    except ValueError:
                        pass
            with open(os.path.join(sdir, "stage_arbitrate_gen%d.json" % gen), "w") as f:
                json.dump({"status": "ok",
                           "summary": "集成测试三态判定：verdict=pass（e2e 预置，走幂等缓存路径）",
                           "report": "[e2e seeded] verdict=pass",
                           "deliverables": [], "files_changed": [],
                           "evidence": "seeded by sc_ticket_pause_gate"}, f, ensure_ascii=False)
            s = wait_snap(fail, py, stage, tid1,
                          lambda x: x.get("stage") == "merge" and x.get("stage_state") == "awaiting-human",
                          "L3.7 走到 merge 人门", 420)
            if s:
                fail.check(bool(stage_running_marks(s, "run_integration_tests")),
                           "L3.7 链过机械集成测试段（timeline 有 run_integration_tests running 痕迹）")
                sig = cli(py, stage, "ticket", {"op": "sign", "ticket_id": tid1,
                                                "input": {"who": "e2e-human", "gate": "merge",
                                                          "decision": "approve",
                                                          "note": "e2e 放行"}})
                fail.check(sig.get("ok") is True, "L3.7 sign approve 回执 ok")
                fin = wait_snap(fail, py, stage, tid1,
                                lambda x: x.get("status") == "closed",
                                "L3.7 恢复后走完到 closed", 300)
                if fin:
                    fail.check(fin.get("paused") is False, "L3.7 终态 paused=false")
                    tl = fin.get("timeline") or []
                    pw = next((i for i, e in enumerate(tl)
                               if "paused-waiting" in str(e.get("state") or "")), -1)
                    rs = next((i for i, e in enumerate(tl)
                               if "resumed" in str(e.get("state") or "")), -1)
                    fail.check(pw >= 0 and rs > pw,
                               "L3.7 全链因果：paused-waiting → resumed → 走完")
    finally:
        for w in workers:
            stop_worker(fail, w, "teardown")
        if slot is not None and stage_mod is not None:
            try:
                stage_down(stage_mod, slot)
            except Exception:
                pass
        if G["tmp"] and not os.environ.get("SANDBAR_PAUSE_E2E_KEEP_TMP"):
            shutil.rmtree(G["tmp"], ignore_errors=True)
        elif G["tmp"]:
            print("[diag] SANDBAR_PAUSE_E2E_KEEP_TMP：现场保留于 %s" % G["tmp"])
    fail.finish()


if __name__ == "__main__":
    main()
