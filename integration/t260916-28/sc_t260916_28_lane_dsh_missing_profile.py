#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-28 场景：泳道 .dsh 缺 headless profile 的静默失效 → spawn 前预检响亮 +
failed 回执六站分流 + 补件自愈（TDD 端到端，一票串三子用例）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
真起 workflow（docker 测试台 temporal-only + 真工单专属 worker + 假 dsh 桩），复现
t260916-26 的用户实报形态（泳道 .dsh 缺 profile → 票 blocked 且真因可辨，绝不压成
「agent 活动故障」），并钉住方案 v3 的两条新契约：

- 子用例 A（generic 站 + 自愈）：开票时候选链全空 → create_plan blocked，blocked_reason
  点名「泳道 .dsh 缺 + sandbar-headless」、绝不含「agent 活动故障」；
  blocked_detail.reason_code == lane_dsh_profile_missing；桩账本零 create_plan 记录
  （=预检拦在 spawn 之前，没白烧一次 agent）。补源 profile + retry_qc → 自愈推进。
- 子用例 B（parallel_impl_design 汇合边，方案 D3' 第 6 使用点）：review_plan 桩执行
  prune（删候选链源 profile 与泳道 .dsh profile 两处）→ fork 两边均撞预检 →
  blocked 点名（含「agent 报失败」+「泳道 .dsh 缺」）；绝无「实现完成」假 handoff、
  绝无 rework 条目、被拦轮桩账本零 implement/design 记录。补源 + retry → 两边重跑
  （implement/design 账本各恰 1 条）推进。
- 子用例 C（arbitrate/acceptance 门）：design 重跑桩再删 → arb_acc fork 双拦 →
  blocked(arbitrate) 点名且绝无「缺 verdict= 标记」虚报、无「格式纠正」账 →
  补源 + retry → arbitrate verdict=pass 重跑 → 滞留 failed 的 acceptance 回执被
  门消费 blocked(acceptance) 点名、绝无「验收走查打回」假叙事、无 rework →
  补源 + retry → acceptance 重跑 ok → 票到达 merge_check（全链自愈终点；其后
  终态不判——与 t260912-03 同口径）。

驱动机制（评审 R2 修正后的机械，写明防误读）：
- 假 dsh 桩：worker env SANDBAR_AGENT_CMD="dsh --profile sandbar-headless"——首词
  dsh 正是预检的触发条件（DSH_CMD[0]=="dsh"），而真链 spawn 经 PATH 解析到本桩，
  纯进程内桩，不连任何真模型。桩回执恒 status=ok（arbitrate 的 summary 带
  verdict=pass，防格式纠正循环混入被测面）。
- 缺件触发（两处删）：桩被 control.prune 列表内的 stage 调起时，删「候选链源
  profile（worker env DSH_HOME 指向的源 home）」与「泳道 .dsh profile（桩进程 env
  DSH_HOME=prep 覆盖后的泳道面）」两处——host 形态泳道 profile 跨段持久、prep 有
  exists 守卫，只删一处无法使下一 spawn 的泳道面缺件（评审 R2 的核心修正）。
- 候选链全空前提（全部子用例继承）：worker DSH_HOME=夹具源 home、HOME=无 .dsh 的 tmp
  home——两候选都无 profile 时预检才会拦，宿主真 home 不参与（可复现、不靠运气）。
- 补件自愈：场景往源 home 补 profile 目录 + retry_qc 信号 → 下一次 spawn 的 prep
  重拷 → 预检过 → 推进。t260916-26 的「手工补 profile 即愈」旅程成为一等公民。
- 轮次判定：snapshot.retry_count（=_retry_token 读数）随每次 retry_qc 递增，各子用例
  blocked 的识别用 token 阈值防「上一子用例的旧 blocked 态」串台。

断言面=snapshot 顶层 blocked_reason/blocked_detail/timeline/handoffs/meta.log/
results 与桩账本，不锚 prompt/文案整句（子串断言）。红线（testing-guide）：绝不
触碰生产 7233/8233/3099——被测 worker/client 子进程经 bench.audit_hook_env 审计
钩子，终局断言审计账本空；拆台幂等。三态：docker/镜像/temporal CLI 缺席=exit 2
ENV_FAIL（点名环境缺件，非被测红）。实现未落地=产品红（TDD 信号，红要可辨），
arbitrate/merge 期必须绿。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
from lib_gate import (Fail, read_audit_jsonl, require_bench, require_stage,  # noqa: E402
                      run_poc_client, stage_down)

TID = "t26091628-lanedsh"
PROJ_KEY = "t26091628-lanedsh"

# 各子用例 blocked 的 retry token 阈值（retry_qc 每次唤醒 _retry_token +1）。
TOK_A = 0   # 子用例 A：开票后第一次 blocked
TOK_B = 1   # 子用例 B：子用例 A retry 之后
TOK_C_ARB = 2
TOK_C_ACC = 3

STUB = r"""
# 引擎 spawn 命令桩（假 dsh）：argv=[dsh, --profile, sandbar-headless, ...flags, <prompt>]
# ——引擎按 dsh CLI 组装命令（DSH_CMD 首词 dsh=预检触发条件），prompt 恒为末位 argv。
# 职责：①prompt 与动作落账本（STUB_LOG，JSONL，供场景断言「spawn 了没有/几次」）；
# ②control（SANDBAR_TEST_STUB_CONTROL）的 prune 列表含本 stage → 先删候选链源
# profile（SANDBAR_TEST_SRC_DSH_HOME）与泳道 .dsh profile（env DSH_HOME）两处
# （t260916-28 子用例 B/C 缺件触发=两处删机械，只删一处无法使泳道面缺件）；
# ③按交付契约写回执（status=ok；arbitrate 的 summary 带 verdict=pass）。rc=0。
import json, os, re, shutil, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
action = "reply"
ctrl_path = os.environ.get("SANDBAR_TEST_STUB_CONTROL") or ""
if ctrl_path:
    try:
        with open(ctrl_path, encoding="utf-8") as cf:
            ctrl = json.load(cf)
        if stage in (ctrl.get("prune") or []):
            action = "prune_profile"
            for root in (os.environ.get("SANDBAR_TEST_SRC_DSH_HOME") or "",
                         os.environ.get("DSH_HOME") or ""):
                if root:
                    shutil.rmtree(os.path.join(root, "profiles", "sandbar-headless"),
                                  ignore_errors=True)
    except Exception as e:
        action = "control-error:" + str(e)[:80]
log = os.environ.get("STUB_LOG") or ""
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage, "action": action, "ts": time.time(),
                            "prompt": prompt}, ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    summary = "[stub] %s 段完成" % stage
    if stage == "arbitrate":
        summary = "verdict=pass " + summary
    # files_changed 声明要兑现，但只在改动段落盘：create_plan/review_plan/arbitrate/
    # acceptance 是零代码改动段（阶段路径闸只许结果/回执文件），写 docs/ 会被
    # unauthorized_path 拒落盘 → blocked（第一轮实跑证据）。改动面由 implement/
    # design 段落盘，integ_join 的 settle_lane 统一收进 commit（merge_check 的
    # 0-commit 预检见 commit）。零改动段声明非空不写盘不触发任何校验（bash-3 证据：
    # WRITE_SET_FAULT 只查空声明，无「声明文件必须在盘」校验）。
    if stage in ("implement", "design_integration_tests"):
        try:
            os.makedirs("docs", exist_ok=True)
            with open("docs/ticket-notes.md", "a", encoding="utf-8") as tf:
                tf.write("\n- [stub] %s 段回执（t260916-28 场景桩）\n" % stage)
        except OSError:
            pass
    body = {"status": "ok", "summary": summary,
            "report": "[stub] 桩回执（t260916-28）",
            "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
            "files_changed_shape": "ok", "evidence": "t26091628-stub"}
    with open(m.group(1), "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


def make_fixture_repo(tmp):
    """fixture 项目仓：git init + repo 级身份（HOME 被 worker env 指到空 tmp home，
    repo 级身份是 prepare_workspace 身份守卫的放行面）+ 首 commit。"""
    repo = os.path.join(tmp, "fixture-repo")
    os.makedirs(repo)

    def g(*a):
        subprocess.run(["git", "-C", repo] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("fixture\n")
    g("add", "-A")
    g("commit", "-qm", "init")
    return repo


def ensure_source_profile(src_dsh):
    """补件自愈的「补源」半边：往候选链源 home 补最小 profile 目录（内容不重要——
    桩链不启动真 dsh，消费面是 prep 的 copytree 与预检的目录存在性）。"""
    p = os.path.join(src_dsh, "profiles", "sandbar-headless")
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(p, "marker.json"), "w", encoding="utf-8") as f:
        f.write('{"fixture": "t260916-28"}')
    return p


def spawn_worker(py, tid, env, log_path, stub_path):
    """工单专属 worker（前台跑，watch 收口自退）。env 语义：
    - DSH_HOME=源 home（_src_dsh_home 的第一候选；夹具可控）
    - HOME=空 tmp home（第二候选落空——候选链全空前提，不靠宿主真 home 运气）
    - PATH 前置桩目录 + SANDBAR_AGENT_CMD 首词 dsh（预检触发条件本体）
    - STUB 三键经进程环境继承到桩进程（prep env=dict(os.environ) 语义）。
    """
    wenv = dict(env)
    wenv["SANDBAR_TASK_QUEUES"] = "sandbar-ticket-%s,suyou-ticket-%s" % (tid, tid)  # naming-compat
    wenv["SANDBAR_WATCH_WORKFLOW"] = tid
    wenv["SANDBAR_WATCH_INTERVAL_SEC"] = "2"
    wenv["SANDBAR_AGENT_CMD"] = "dsh --profile sandbar-headless"
    wenv["SANDBAR_TEST_SRC_DSH_HOME"] = wenv["DSH_HOME"]
    logf = open(log_path, "ab")
    return subprocess.Popen([py, os.path.join(REPO, "server", "engine",
                                               "worker.py")],
                            env=wenv, cwd=os.path.join(REPO, "server", "engine"),
                            stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)


def send_retry_qc(py, state, tid):
    """retry_qc signal（client op 白名单外，直接 temporalio 驱动；payload=who）。"""
    script = (
        "import asyncio\n"
        "from temporalio.client import Client\n"
        "async def main():\n"
        "    c = await Client.connect('127.0.0.1:%d', namespace='%s')\n"
        "    await c.get_workflow_handle('%s').signal('retry_qc', '宿主')\n"
        "asyncio.run(main())\n" % (state["ports"]["temporal"], state["namespace"], tid))
    p = subprocess.run([py, "-c", script], capture_output=True, text=True, timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_json_loose(out):
    s = out or ""
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return {}


def query_snapshot(py, env, tid):
    rc, out = run_poc_client(py, "ticket", {"op": "query", "ticket_id": tid}, env)
    return ((parse_json_loose(out).get("result") or {}).get("snapshot")) or {}


def read_stub_log(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return rows


def stub_count(rows, prefix):
    return len([r for r in rows if str(r.get("stage") or "").startswith(prefix)])


def poll(fn, timeout_s, interval=2.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    return None


def main():
    fail = Fail("t260916-28 泳道 .dsh 缺 profile 静默失效→预检响亮+六站分流+补件自愈")
    bench = require_bench(fail)
    py = bench.poc_python()
    tmp = tempfile.mkdtemp(prefix="t26091628-lanedsh-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)

    src_dsh = os.path.join(tmp, "dsh-home")           # 候选链第一候选（worker DSH_HOME）
    os.makedirs(os.path.join(src_dsh, "profiles"), exist_ok=True)
    with open(os.path.join(src_dsh, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write("providers: {}\n")                     # settings 在位：被测面只有 profile 缺件
    empty_home = os.path.join(tmp, "empty-home")       # 候选链第二候选（HOME）——落空
    os.makedirs(empty_home, exist_ok=True)
    stub_bin = os.path.join(tmp, "bin")
    os.makedirs(stub_bin, exist_ok=True)
    stub_path = os.path.join(stub_bin, "dsh")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nexec '%s' '%s' \"$@\"\n" % (py, os.path.join(tmp, "stub.py")))
    os.chmod(stub_path, 0o755)
    with open(os.path.join(tmp, "stub.py"), "w", encoding="utf-8") as f:
        f.write(STUB)
    control_path = os.path.join(tmp, "control.json")
    with open(control_path, "w", encoding="utf-8") as f:
        json.dump({"prune": ["review_plan", "design_integration_tests"]}, f)
    stub_log = os.path.join(tmp, "stub.jsonl")

    stage_mod = None
    stage = None
    worker = None
    try:
        # ---------- ① 舞台 + fixture 注册表 + 专属 worker ----------
        stage_mod, stage = require_stage(fail, "t26091628-lanedsh-%d" % os.getpid(),
                                         "t26091628-lanedsh")
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        env = dict(os.environ)
        env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
        env["SANDBAR_NAMESPACE"] = stage["namespace"]
        env["SANDBAR_PROJECTS_DIR"] = reg_dir
        env.update(audit_env)
        env["DSH_HOME"] = src_dsh
        env["HOME"] = empty_home
        env["PATH"] = stub_bin + os.pathsep + env.get("PATH", "")
        env["SANDBAR_TEST_STUB_CONTROL"] = control_path
        env["STUB_LOG"] = stub_log

        worker = spawn_worker(py, TID, env, os.path.join(tmp, "worker.log"), stub_path)
        fail.check(worker.poll() is None, "专属 worker 已拉起（pid=%s）" % worker.pid)

        # ---------- ② 开票：子用例 A create_plan 预检拦 ----------
        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "泳道缺 profile 静默失效端到端", "write_set": ["docs/"]}, env)
        fail.check(rc == 0 and TID in out,
                   "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))

        last = {"snap": {}}

        def _blocked(reason_need, tok_min):
            def _q():
                s = query_snapshot(py, env, TID)
                if s:
                    last["snap"] = s
                if (s.get("stage_state") == "blocked"
                        and s.get("retry_count", 0) >= tok_min
                        and reason_need in str(s.get("blocked_reason") or "")):
                    return s
                return None
            return _q

        snap = poll(_blocked("泳道 .dsh 缺", TOK_A), 180)
        if snap is None and worker.poll() is not None:
            try:
                tail = open(os.path.join(tmp, "worker.log"), encoding="utf-8").read()[-600:]
            except OSError:
                tail = "<log 不可读>"
            fail.check(False, "worker 提前退出（rc=%s）——日志尾：%s"
                       % (worker.returncode, tail))
        _ls = last["snap"]
        fail.check(snap is not None,
                   "子用例A：到达 blocked（180s 末见 stage=%s state=%s reason=%s）"
                   % (_ls.get("stage"), _ls.get("stage_state"),
                      str(_ls.get("blocked_reason") or "")[:120]))
        if snap is None:
            fail.finish()
            return
        reason = str(snap.get("blocked_reason") or "")
        fail.check("泳道 .dsh 缺" in reason and "sandbar-headless" in reason,
                   "子用例A：blocked_reason 点名（含「泳道 .dsh 缺」+「sandbar-headless」）")
        fail.check("agent 活动故障" not in reason,
                   "子用例A：绝不压成「agent 活动故障」（本票要杀的形态）")
        bd = snap.get("blocked_detail")
        fail.check(isinstance(bd, dict) and bd.get("reason_code") == "lane_dsh_profile_missing",
                   "子用例A：blocked_detail.reason_code==lane_dsh_profile_missing（机读可辨）")
        rows = read_stub_log(stub_log)
        fail.check(stub_count(rows, "create_plan") == 0,
                   "子用例A：桩账本零 create_plan 记录（=预检拦在 spawn 前，没白烧 agent）")

        # ---------- ③ 子用例 A 自愈：补源 profile + retry_qc ----------
        ensure_source_profile(src_dsh)
        rc, out = send_retry_qc(py, stage, TID)
        fail.check(rc == 0, "子用例A：补源 profile + retry_qc 唤醒（rc=%s）" % rc)

        def _plan_done():
            s = query_snapshot(py, env, TID)
            if s:
                last["snap"] = s
            # status=="ok" 判定：blocked（failed）回执也入 results（dev_lane :962
            # 无 status 过滤），只看键存在会在 blocked 轮瞬间误命中、读到空账本。
            rp = (s.get("results") or {}).get("create_plan") or {}
            rows = read_stub_log(stub_log)
            if rp.get("status") == "ok" and stub_count(rows, "create_plan") >= 1:
                return s
            return None
        snap = poll(_plan_done, 150)
        fail.check(snap is not None,
                   "子用例A：补件后 create_plan 真跑完成（150s 末 results=%s）"
                   % sorted((last["snap"].get("results") or {}).keys()))
        rows = read_stub_log(stub_log)
        fail.check(stub_count(rows, "create_plan") >= 1,
                   "子用例A：自愈后桩账本有 create_plan 记录（=spawn 真发生，旅程闭环）")

        # ---------- ④ 子用例 B：impl fork 汇合边（D3' 第 6 使用点） ----------
        # review_plan 桩 prune（删两处）→ fork 两边均撞预检 → blocked 点名
        snap = poll(_blocked("泳道 .dsh 缺", TOK_B), 240)
        _ls = last["snap"]
        fail.check(snap is not None,
                   "子用例B：到达 fork 拦截 blocked（240s 末见 stage=%s state=%s）"
                   % (_ls.get("stage"), _ls.get("stage_state")))
        if snap is None:
            fail.finish()
            return
        reason = str(snap.get("blocked_reason") or "")
        fail.check("agent 报失败" in reason and "泳道 .dsh 缺" in reason,
                   "子用例B：blocked_reason 含「agent 报失败」+「泳道 .dsh 缺」（六站分流同族文案）")
        bd = snap.get("blocked_detail")
        fail.check(isinstance(bd, dict) and bd.get("reason_code") == "lane_dsh_profile_missing",
                   "子用例B：blocked_detail.reason_code==lane_dsh_profile_missing")
        blocked_tl = [e for e in (snap.get("timeline") or []) if e.get("state") == "blocked"]
        fail.check(any(e.get("stage") in ("implement", "design_integration_tests")
                       for e in blocked_tl),
                   "子用例B：timeline 有 fork 边的 blocked 条目（stage=implement/design_integration_tests）")
        handoffs = snap.get("handoffs") or []
        fail.check(not [h for h in handoffs
                        if "实现完成" in str(h.get("summary") or "")
                        or "集成测试集就绪" in str(h.get("summary") or "")],
                   "子用例B：绝无「实现完成/集成测试集就绪」假 handoff（failed 回执不被吞成完成）")
        fail.check(not [e for e in (snap.get("timeline") or []) if e.get("state") == "rework"],
                   "子用例B：绝无 rework 条目（不白烧打回轮）")
        rows = read_stub_log(stub_log)
        fail.check(stub_count(rows, "implement") == 0 and stub_count(rows, "design_integration_tests") == 0,
                   "子用例B：被拦轮桩账本零 implement/design 记录（=拦在 spawn 前；汇合边不吞回执）")

        # ---------- ⑤ 子用例 B 自愈 → 子用例 C 第一次 blocked(arbitrate) ----------
        ensure_source_profile(src_dsh)
        rc, out = send_retry_qc(py, stage, TID)
        fail.check(rc == 0, "子用例B：补源 profile + retry_qc 唤醒（rc=%s）" % rc)

        # design 重跑桩 prune（两处删）→ integ_join/机械段照常 → arb_acc fork 双拦
        snap = poll(_blocked("泳道 .dsh 缺", TOK_C_ARB), 300)
        _ls = last["snap"]
        fail.check(snap is not None,
                   "子用例C：到达 blocked（300s 末见 stage=%s state=%s reason=%s）"
                   % (_ls.get("stage"), _ls.get("stage_state"),
                      str(_ls.get("blocked_reason") or "")[:120]))
        if snap is None:
            fail.finish()
            return
        fail.check(snap.get("stage") in ("arbitrate", "acceptance_walkthrough"),
                   "子用例C：第一次 blocked 落在 arb_acc fork 双站之一（stage=%s；fork 双边均"
                   "撞预检——门 2 先拦 arbitrate、门 5 随后消费滞留回执拦 acceptance，"
                   "poll 相位决定先抓到哪站，两站都在被测面内）" % snap.get("stage"))
        reason = str(snap.get("blocked_reason") or "")
        fail.check("agent 报失败" in reason and "泳道 .dsh 缺" in reason,
                   "子用例C：blocked_reason 含「agent 报失败」+「泳道 .dsh 缺」")
        fail.check("缺 verdict= 标记" not in reason,
                   "子用例C：绝无「缺 verdict= 标记」虚报（failed 回执不进格式纠正循环）")
        log_notes = "｜".join(str(e.get("note") or "") for e in ((snap.get("meta") or {}).get("log") or []))
        fail.check("格式纠正" not in log_notes,
                   "子用例C：meta.log 无「格式纠正」账（计数不被污染）")
        rows = read_stub_log(stub_log)
        n_arb_now = stub_count(rows, "arbitrate")
        fail.check(n_arb_now in (0, 1),
                   "子用例C：arbitrate 桩账本 ∈{0,1}（抓到双拦初态=0；抓到滞留消费态=重跑恰 1；"
                   "实得 %d）" % n_arb_now)
        fail.check(stub_count(rows, "implement") == 1 and stub_count(rows, "design_integration_tests") == 1,
                   "子用例B自愈证据：重跑后 implement/design 账本各恰 1 条（ done 标志未置、真重跑）")

        # ---------- ⑥ 子用例 C 自愈 1：arbitrate verdict=pass 重跑 → acceptance 拦截 ----------
        ensure_source_profile(src_dsh)
        rc, out = send_retry_qc(py, stage, TID)
        fail.check(rc == 0, "子用例C：补源 + retry_qc（第 2 次，rc=%s）" % rc)

        def _acc_blocked():
            s = query_snapshot(py, env, TID)
            if s:
                last["snap"] = s
            if s.get("stage_state") != "blocked" or s.get("retry_count", 0) < TOK_C_ACC:
                return None
            # snapshot.stage 停在最后 _enter 的边（fork 双站语境下与哪站 blocked 无关
            # ——dev_lane :675 只在步进入时更新），门 5 的受阻站名看 timeline 条目。
            tl = [e for e in (s.get("timeline") or []) if e.get("state") == "blocked"]
            if any(e.get("stage") == "acceptance_walkthrough" for e in tl):
                return s
            return None
        snap = poll(_acc_blocked, 240)
        _ls = last["snap"]
        fail.check(snap is not None,
                   "子用例C：arbitrate 重跑后 acceptance blocked 到达（240s 末见 stage=%s state=%s reason=%s）"
                   % (_ls.get("stage"), _ls.get("stage_state"),
                      str(_ls.get("blocked_reason") or "")[:120]))
        if snap is None:
            fail.finish()
            return
        reason = str(snap.get("blocked_reason") or "")
        fail.check("agent 报失败" in reason,
                   "子用例C：acceptance blocked 点名（含「agent 报失败」，滞留 failed 回执被门消费）")
        fail.check("验收走查打回" not in reason,
                   "子用例C：绝无「验收走查打回」假叙事（不污染 acc_rounds、不白烧 implement）")
        fail.check(not [e for e in (snap.get("timeline") or []) if e.get("state") == "rework"],
                   "子用例C：全程绝无 rework 条目")
        rows = read_stub_log(stub_log)
        fail.check(stub_count(rows, "arbitrate") == 1,
                   "子用例C：arbitrate 恰重跑 1 次（verdict=pass 回执，桩账本为证）")
        fail.check(stub_count(rows, "acceptance") == 0,
                   "子用例C：桩账本零 acceptance 记录（=拦在 spawn 前）")

        # ---------- ⑦ 子用例 C 自愈 2：acceptance 重跑 ok → merge_check 到达 ----------
        ensure_source_profile(src_dsh)
        rc, out = send_retry_qc(py, stage, TID)
        fail.check(rc == 0, "子用例C：补源 + retry_qc（第 3 次，rc=%s）" % rc)

        def _merge_check():
            s = query_snapshot(py, env, TID)
            if s:
                last["snap"] = s
            return s if s.get("stage") == "merge_check" else None
        snap = poll(_merge_check, 240)
        fail.check(snap is not None,
                   "子用例C：全链自愈终点——票到达 merge_check（240s 末见 stage=%s state=%s；"
                   "其后终态不判，与 t260912-03 同口径）"
                   % (last["snap"].get("stage"), last["snap"].get("stage_state")))
        rows = read_stub_log(stub_log)
        fail.check(stub_count(rows, "acceptance") == 1,
                   "子用例C：acceptance 重跑 ok（账本恰 1 条，全链闭环）")

        # ---------- ⑧ 红线：被测子进程零触碰生产端口 ----------
        arows = read_audit_jsonl(audit_log)
        fail.check(not arows, "审计账本为空：被测子进程零连生产端口（实得 %d 条）" % len(arows))
    finally:
        # ---------- 终态回收：worker TERM→KILL 兜底；舞台 down 幂等 ----------
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=10)
        if stage is not None:
            try:
                stage_down(stage_mod, stage["project"])
            except Exception:
                pass
    fail.finish()


if __name__ == "__main__":
    main()
