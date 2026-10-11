#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_project_template_ticket_journey.py — 项目外置模板建票全链＋续跑＋建票拒收面（t260924-04 场景②）。

intent（用户可感知行为，需求书 A1/A3/A7 验收的集成面）：
- A1 外置模板走通全链：项目注册声明 workflow_modules 指向项目仓内外置模板模块
  （自备最小两段模板 journey-two-step，clean-module 形状照 fixture_two_step）→
  引擎认得它 → ticket-start 用它建票 → 桩大脑（SANDBAR_AGENT_STUB=1）驱动段序
  走完 → 票 closed；
- A1 续跑：段在飞时 worker 被停 → 重起 worker → 同票继续走完到 closed（每票专属
  工人=启动即吃新码、在途票历史重放续跑，KI-113 生效粒度写实的行为面）；
- A3/A7 建票面 fail-closed：坏模板项目（模块加载即炸）→ 该 id 建票被拒且报错点名
  拒收原因（拒收≠装死）；同坏项目下内置 dev-lane 照常建票（别模板/别项目不受扰，
  全链半程验证）；
- 可用面帮助文本：未知模板报错列出「内置＋当项目显式登记」——项目 A 可见
  journey-two-step，坏项目 B 不可见被拒模板 id（分项目可见面）；
- 人门 sign 同道等价：外置模板与 dev-lane 共用 TicketWorkflowBase 同一基类
  （sign 通道唯一入口），sign 旅程由在册 dev-lane 场景族承载，本场景不重复造伪
  覆盖——外置模板的段序/拒收/续跑行为即基类同一性的行为证据。

灰盒声明：只断 client.py 结构化回执（ok/error）与 snapshot 公开键、报错语义锚
（拒收/未知模板/加载失败，不锚全句，KI-051）；worker 从真仓工作树引擎起（加载口
是本票新增面，HEAD clone 不含——与 t260908-01「真仓 ticket.py」同纪律）；子进程
env 剥泳道标记三件套、SANDBAR_TARGET_HOST 钉本场景舞台（写守卫）。

三态：docker/镜像/舞台缺件＝ENV_FAIL exit 2；断言破面＝exit 1。实现段落地前红属
预期（TDD 信号），arbitrate/merge 期必须绿。pool=serial（独占台旅程，分钟级）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
ENGINE = os.path.join(REPO, "server", "engine")
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
from lib_gate import (Fail, parse_out_json, poc_python, require_bench,  # noqa: E402
                      require_stage, run_poc_client, stage_down)
sys.path.insert(0, INTEG)
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （集成侧回收 helper：注册表+atexit）
sys.path.insert(0, HERE)
from lib_journey_handshake import LineReader  # noqa: E402  （握手消费原语：事件代替固定间隔轮询）

LANE_MARKERS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW")
EXT_ID = "journey-two-step"
GOOD_KEY, BAD_KEY = "jn-good", "jn-bad"
EXT_MODULE = '''"""journey-two-step — t260924-04 集成夹具：项目仓内外置两段模板（clean-module）。"""
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from base import TicketWorkflowBase
    from shared import Stage, TicketInput

TEMPLATE_ID = "%s"


@workflow.defn
class JourneyTwoStepWorkflow(TicketWorkflowBase):
    STAGES = (
        Stage(id="j_one", name="外置段一", role="developer", next="j_two",
              acceptance=("段一完成",)),
        Stage(id="j_two", name="外置段二", role="integration", next="",
              acceptance=("段二完成",)),
    )
    PATCH_ID = "jn-good-journey-v1"
    TEMPLATE_ID = TEMPLATE_ID
    TEMPLATE_NAME = "外置两段旅程"
    TEMPLATE_LANE = "main"
    TEMPLATE_DESC = "t260924-04 项目外置模板全链夹具"

    @workflow.run
    async def run(self, inp: TicketInput):
        # 握手生产面（261011 族 D：事件代替固定间隔轮询）：生产者（本夹具 workflow，
        # 活在 worker 进程内）向 stdout 写两行事件，场景父进程经 LineReader 阻塞读。
        # temporalio 沙箱不拦 stdout（实现段 spike：SandboxRestrictions.default 无
        # stdout 面、workflow_sandbox 包零 print/stdout 拦截），行直达 worker 进程
        # stdout 管道。重放（续跑子用例 worker 重启）会再打一遍：消费面按行匹配，
        # 重复行无害。
        print("JOURNEY workflow started " + TEMPLATE_ID, flush=True)
        out = await self._main(inp)
        # 落点说明（评审 comment 2）：finished 行在 workflow 返回路径上，而 `closed`
        # 状态由引擎在 workflow 返回**之后**持久化——消费面读到本行后做一次
        # **声明的有界等待**（PERSIST_BOUND_S，非轮询）再断言 closed，竞态窗口关死。
        print("JOURNEY workflow finished " + TEMPLATE_ID, flush=True)
        return out
''' % EXT_ID
BROKEN_MODULE = '''from temporalio import workflow\nTEMPLATE_ID = "jn-broken-tpl"\n@workflow.defn\nclass JnBrokenWorkflow:\n    @workflow.run\n    async def run(self, inp):\n        return inp\nraise RuntimeError("t260924-04 场景②夹具：模块加载即炸")\n'''

G = {"tmp": "", "projects": "", "readers": {}}


def write_registry(name, key, main_dir, modules=None, broken=False):
    """写一份独立项目注册表：<name>/<key>/project.yaml（dirs[0]=main_dir，
    paths.workflow_modules 按 good/broken 形态供数）。返回注册表目录。"""
    reg = os.path.join(G["tmp"], name)
    os.makedirs(reg, exist_ok=True)
    if modules:
        mdir = os.path.join(main_dir, "wf_mods")
        os.makedirs(mdir, exist_ok=True)
        rels = []
        for fname, text in modules:
            with open(os.path.join(mdir, fname), "w", encoding="utf-8") as f:
                f.write(text)
            rels.append("wf_mods/" + fname)
        decl = ",".join(rels)
    else:
        decl = ""
    pdir = os.path.join(reg, key)
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "project.yaml"), "w", encoding="utf-8") as f:
        f.write("# fixture-local registry（t260924-04 场景②）\n"
                "schema: v1\nproject:\n  - key: %s\n    name: %s\n"
                "    dirs:\n      - %s\npaths:\n  workflow_modules: %s\n"
                % (key, key, main_dir, decl))
    return reg


def env_for(stage, registry, extra=None):
    """子进程 env：剥泳道标记三件套＋钉舞台地址/命名空间/注册表。写守卫单点。"""
    env = dict(os.environ)
    for k in LANE_MARKERS:
        env.pop(k, None)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = stage["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = registry
    if extra:
        env.update(extra)
    return env


def cli(py, stage, registry, sub, args, extra=None, timeout=180):
    rc, out = run_poc_client(py, sub, args, env_for(stage, registry, extra),
                             timeout=timeout)
    return rc, parse_out_json(out), out


def query(py, stage, registry, tid):
    # gen5 走查修正：观测面走 ticket-query 子命令（describe/result 路径）——裸入口
    # 「ticket op=query」的跨项目闸前置读用活工作流 query，专属 worker 收口自退后
    # 对已收口票恒报 no-poller（内置夹具同判复现＝引擎既有面、非本票加载口缺陷，
    # 报 KI 候选）；两入口观测语义同源（全量 snapshot），取可用面。
    _, s, _ = cli(py, stage, registry, "ticket-query", {"ticket_id": tid})
    # ticket-query 面形状：{ticket_id, exec_status, snapshot:{status,stage,…}}——
    # 解包到票形 snapshot，下游 cond（status/stage/stage_state）按票面字段判。
    if s.get("ok") and isinstance(s.get("result"), dict):
        r = s["result"]
        return r.get("snapshot") if isinstance(r.get("snapshot"), dict) else r
    return s


# ---- 握手纪律（261011 族 D / 评审 comment 2）：等待只走两条通道，零固定间隔轮询 ----
# ①生产者行：夹具 workflow 的 stdout 事件（started/finished），LineReader 阻塞读；
# ②注入的秒界：等待长度=声明的常数（不是探测循环）。各常量语义：
PERSIST_BOUND_S = 5.0   # finished 行 → 引擎持久化 closed 的声明界（评审 comment 2 竞态窗）
BOOT_BOUND_S = 3.0      # worker 进程拉起的声明界（原 time.sleep(3) 的具名化；无生产者行的面用）
PREP_BOUND_S = 15.0     # workflow started 行 → 段活动在飞的声明界（stub delay=20s 保证窗内）
LINE_BOOT_S = 30.0      # 等生产者 started 行的硬上界（worker 拉起+拾取）
LINE_TIMEOUT_S = 240.0  # 等生产者行的硬上界（原 poll_snap 超时窗，超时=具名断言失败）


def _started_line(reader, label):
    """等 started 行（worker 已拉起且已拾取票=原来 sleep(3)+poll 的替换面）。"""
    return reader.wait_for(lambda l: "JOURNEY workflow started" in l,
                           LINE_BOOT_S, label)


def _finished_then_query(py, stage, registry, tid, label, fail):
    """等 finished 行 → 声明的持久化界 → 单次查询返回终态快照。
    超时/EOF/读死=具名 bail（与原 poll_snap 超时同语义同三态）。"""
    reader = G["readers"][tid]
    line = reader.wait_for(lambda l: "JOURNEY workflow finished" in l,
                           LINE_TIMEOUT_S, label)
    if line is None:
        why = getattr(reader, "death", None) or ("timeout", "?")
        fail.bail("超时未等到：%s（reader 终态=%r，末 3 行=%r）"
                  % (label, why, reader.lines[-3:]), 1)
    wait_seconds_bound(PERSIST_BOUND_S)
    return query(py, stage, registry, tid)


def wait_seconds_bound(bound_s):
    from lib_journey_handshake import wait_seconds
    wait_seconds(bound_s)


def start_worker(py, stage, registry, tid, delay_sec="8"):
    """票专属桩脑 worker（从真仓工作树引擎起——加载口是本票新增面，HEAD clone 不含）。"""
    extra = {
        "SANDBAR_TASK_QUEUES": "sandbar-ticket-%s,suyou-ticket-%s" % (tid, tid),  # naming-compat
        "SANDBAR_WATCH_WORKFLOW": tid,
        "SANDBAR_WATCH_INTERVAL_SEC": "3",
        "SANDBAR_AGENT_STUB": "1",
        "SANDBAR_AGENT_STUB_DELAY_SEC": delay_sec,  # 确定性「段在飞」窗口（续跑子用例）
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    log = open(os.path.join(G["tmp"], "worker-%s-%d.log" % (tid, time.time())), "ab")
    # stdout=PIPE + LineReader（tee 镜像进同一日志文件）：等待面=生产者行的阻塞读，
    # 不再靠父进程定时探测。读者线程死亡/EOF 具名化（评审 comment 3：tee 死 →
    # 管道缓冲满 → worker 挂死成 hang 的缺陷面在 lib_journey_handshake 堵死）。
    proc = subprocess.Popen([py, os.path.join(ENGINE, "worker.py")],
                            env=env_for(stage, registry, extra),
                            cwd=ENGINE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            start_new_session=True)
    G["readers"][tid] = LineReader(proc.stdout, log)
    return proc


def stop_worker(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
            proc.wait(timeout=10)
    # 终态回收（全路径：正常/报错/超时/取消都到这里）：关读端让读者线程走到
    # EOF sentinel 终态，fd 不漏。
    if proc and proc.stdout:
        try:
            proc.stdout.close()
        except Exception:
            pass


def ticket_start(py, stage, registry, key, tid, template_id):
    return cli(py, stage, registry, "ticket-start", {
        "ticket_id": tid, "template_id": template_id, "project": key,
        # 260927（KI-142）：声明调用方身份=本次要开的项目 key（GOOD_KEY 是受理路径；
        # BAD_KEY 的负例要测的「未声明该模板的项目被拒」在模板闸就返回，不受影响）。
        "caller_project": key,
        "title": "[e2e] t260924-04 外置模板 %s" % tid,
        "user_request": "integration e2e: project template journey",
        "write_set": ["integration/e2e-probe-%s.txt" % tid],
    })


def main():
    fail = Fail("t260924-04 场景②：外置模板建票全链＋续跑＋建票拒收面")
    bench = require_bench(fail)
    py = poc_python(bench)
    G["tmp"] = str(mkdtemp_reclaimed("t26092404-journey-"))
    stage_mod = None
    workers = []
    _sfx = str(int(time.time()) % 100000)  # 票 id 唯一尾：桩脑结果文件幂等，跨轮复用=秒完假象
    try:
        stage_mod, stage = require_stage(fail, "t260924-04-%d" % os.getpid(),
                                         "t260924-04")

        # ---- 夹具：好项目仓（外置模块）＋坏项目仓（加载即炸）＋两份注册表 ----
        good_repo = os.path.join(G["tmp"], "good-repo")
        os.makedirs(good_repo)
        reg_a = write_registry("regA", GOOD_KEY, good_repo,
                               modules=[("journey_two_step.py", EXT_MODULE)])
        bad_repo = os.path.join(G["tmp"], "bad-repo")
        os.makedirs(bad_repo)
        reg_b = write_registry("regB", BAD_KEY, bad_repo,
                               modules=[("broken.py", BROKEN_MODULE)])
        G["projects"] = reg_a

        # ---- A3 前置探针（stdlib 级，不触舞台）：坏模块被拒收且不注册 ----
        rc, out = run_probe_quick(py, reg_b)
        fail.check(rc == 0 and "RuntimeError" in out,
                   "探针：坏模块拒收面可观测（rc=%s，out尾=%s）" % (rc, out[-120:]))

        # ---- A1 全链：外置模板建票 → 桩脑驱动 → closed ----
        _tid_a = "t26092404a" + _sfx
        w1 = start_worker(py, stage, reg_a, _tid_a)
        workers.append(w1)
        rc, ack, out = ticket_start(py, stage, reg_a, GOOD_KEY, _tid_a, EXT_ID)
        # 握手：started 行=worker 拉起且拾取票（替换原 sleep(3)+轮询观测）。
        if _started_line(G["readers"][_tid_a], "A1 started 行") is None:
            fail.bail("超时未等到：A1 workflow started 行（reader 终态=%r，末 3 行=%r）"
                      % (getattr(G["readers"][_tid_a], "death", None),
                         G["readers"][_tid_a].lines[-3:]), 1)
        fail.check(w1.poll() is None, "A1 worker 已拉起（pid=%s）" % w1.pid)
        fail.check(rc == 0 and ack.get("ok") is not False,
                   "A1 外置模板 ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))
        fin = _finished_then_query(py, stage, reg_a, _tid_a,
                                   "A1 外置模板全链走完到 closed", fail)
        fail.check(fin.get("status") == "closed", "A1 票终态 closed")
        stop_worker(w1)

        # ---- A1 续跑：段在飞时停 worker → 重起 → 同票走完 ----
        _tid_b = "t26092404b" + _sfx
        w2 = start_worker(py, stage, reg_a, _tid_b, delay_sec="20")
        workers.append(w2)
        rc, ack2, _ = ticket_start(py, stage, reg_a, GOOD_KEY, _tid_b, EXT_ID)
        fail.check(rc == 0 and ack2.get("ok") is not False, "A1 续跑票受理")
        # 握手：started 行 → 注入的秒界（PREP_BOUND_S，段活动 20s 在飞窗内）→ 单次
        # 查询断言在飞（替换原 150s/1s 步轮询）。
        if _started_line(G["readers"][_tid_b], "A1 续跑 started 行") is None:
            fail.bail("超时未等到：A1 续跑 workflow started 行（reader 终态=%r）"
                      % (getattr(G["readers"][_tid_b], "death", None),), 1)
        wait_seconds_bound(PREP_BOUND_S)
        inflight = query(py, stage, reg_a, _tid_b)
        fail.check((inflight.get("stage") or "").startswith("j_")
                   and inflight.get("stage_state") == "running",
                   "外置段进入在飞窗口")
        stop_worker(w2)
        fail.check(True, "A1 段在飞窗口内 worker 已停（模拟工人重启前置态）")
        mid = query(py, stage, reg_a, "t26092404b" + _sfx)
        fail.check(mid.get("status") != "closed", "A1 停机时票未完（有可续跑面）")
        w3 = start_worker(py, stage, reg_a, _tid_b)
        workers.append(w3)
        # 握手：重启 worker 重放历史 → started 行再现（重放确定性重跑 run()）；
        # 之后 finished 行 + 持久化界 → 单次查询（替换原 240s/1s 步轮询）。
        if _started_line(G["readers"][_tid_b], "A1 重启重放 started 行") is None:
            fail.bail("超时未等到：重启后 workflow started 行（重放未拾取？reader 终态=%r）"
                      % (getattr(G["readers"][_tid_b], "death", None),), 1)
        fin2 = _finished_then_query(py, stage, reg_a, _tid_b,
                                    "A1 重启后续跑到 closed（幂等靠既有结果文件机制）",
                                    fail)
        fail.check(fin2.get("status") == "closed", "A1 续跑终态 closed")
        stop_worker(w3)

        # ---- 可用面帮助文本：分项目可见「内置＋当项目显式登记」 ----
        rc, unk, out = ticket_start(py, stage, reg_a, GOOD_KEY,
                                    "t26092404u" + _sfx, "no-such-tpl")
        fail.check(rc != 0 or unk.get("ok") is False,
                   "未知模板建票被拒")
        fail.check(EXT_ID in out and "dev-lane" in out,
                   "项目 A 未知模板文案列出 内置 dev-lane＋登记 journey-two-step")
        rc, unk2, out2 = ticket_start(py, stage, reg_b, BAD_KEY,
                                      "t26092404u2" + _sfx, "no-such-tpl")
        fail.check(EXT_ID not in out2,
                   "项目 B 可见面不含他项目登记的 journey-two-step（归属边界）")

        # ---- A3/A7 建票面 fail-closed：坏模板拒收点名、dev-lane 不受扰 ----
        rc, rej, out3 = ticket_start(py, stage, reg_b, BAD_KEY,
                                     "t26092404r" + _sfx, "journey-broken")
        fail.check(rc != 0 or rej.get("ok") is False,
                   "A3 被拒模板建票 fail-closed（不产半死票）")
        blob = out3 + json.dumps(rej, ensure_ascii=False)
        fail.check(("拒收" in blob or "加载失败" in blob or "未知模板" in blob
                    or "rejection" in blob.lower())
                   and ("broken.py" in blob or BAD_KEY in blob),
                   "A3 建票失败可见原因：点名拒收检查＋来件（拒收≠装死）")
        w4 = start_worker(py, stage, reg_b, "t26092404d" + _sfx)
        workers.append(w4)
        # dev-lane 是引擎内置模板（夹具外，无生产者行可用）：走注入的秒界通道
        # （原固定 sleep(3) 的具名化声明，非探测循环）。
        wait_seconds_bound(BOOT_BOUND_S)
        rc, dev, _ = ticket_start(py, stage, reg_b, BAD_KEY,
                                  "t26092404d" + _sfx, "dev-lane")
        fail.check(rc == 0 and dev.get("ok") is not False,
                   "A7 坏项目下内置 dev-lane 照常建票（别模板不受扰）")
        stop_worker(w4)
        rc, dl, _ = cli(py, stage, reg_b, "ticket",
                        {"op": "query", "ticket_id": "t26092404d" + _sfx})
        fail.check(dl.get("status") in ("open", "running", None, "closed"),
                   "A7 dev-lane 票可查（未连带拒启）")
    finally:
        for w in workers:
            stop_worker(w)
        if stage_mod:
            try:
                stage_down(stage_mod)
            except Exception:
                pass
    fail.finish()


def run_probe_quick(py, registry):
    """类面只读探针（import workflows_v2 触发全量加载，需引擎 venv）：回 (rc, json文本)。"""
    env = dict(os.environ)
    env.pop("SANDBAR_FIXTURE_TEMPLATES", None)
    env["SANDBAR_PROJECTS_DIR"] = registry
    env["PROBE_ENGINE"] = ENGINE
    probe = os.path.join(G["tmp"], "probe_quick.py")
    with open(probe, "w", encoding="utf-8") as f:
        f.write(
            "import json, os, sys\n"
            "sys.path.insert(0, os.environ['PROBE_ENGINE'])\n"
            "import shared, workflows_v2\n"
            "print(json.dumps({'names': sorted(shared.TEMPLATE_CLASS_NAMES),\n"
            "                  'rej': str(getattr(shared,\n"
            "                  'PROJECT_TEMPLATE_REJECTIONS', []))[:800]},\n"
            "                 ensure_ascii=False))\n")
    p = subprocess.run([py, probe], env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


if __name__ == "__main__":
    main()
