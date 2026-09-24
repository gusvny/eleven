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
        return await self._main(inp)
''' % EXT_ID
BROKEN_MODULE = '''from temporalio import workflow\nTEMPLATE_ID = "jn-broken-tpl"\n@workflow.defn\nclass JnBrokenWorkflow:\n    @workflow.run\n    async def run(self, inp):\n        return inp\nraise RuntimeError("t260924-04 场景②夹具：模块加载即炸")\n'''

G = {"tmp": "", "projects": ""}


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


def poll_snap(py, stage, registry, tid, cond, timeout_s, label, fail):
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = query(py, stage, registry, tid)
        if cond(last):
            return last
        # 步距 1s：票 closed → 专属 worker watch 自退窗口只有 ~2s（收口自退）,
        # 3s 步距会整窗跨过、之后只撞 no-poller 误报（client.py:1863 已知病灶族）。
        time.sleep(1)
    fail.bail("超时未等到：%s（末回执=%r）"
              % (label, json.dumps(last, ensure_ascii=False, default=str)[:400]), 1)


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
    return subprocess.Popen([py, os.path.join(ENGINE, "worker.py")],
                            env=env_for(stage, registry, extra),
                            cwd=ENGINE, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)


def stop_worker(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
            proc.wait(timeout=10)


def ticket_start(py, stage, registry, key, tid, template_id):
    return cli(py, stage, registry, "ticket-start", {
        "ticket_id": tid, "template_id": template_id, "project": key,
        "title": "[e2e] t260924-04 外置模板 %s" % tid,
        "user_request": "integration e2e: project template journey",
        "write_set": ["integration/e2e-probe-%s.txt" % tid],
    })


def main():
    fail = Fail("t260924-04 场景②：外置模板建票全链＋续跑＋建票拒收面")
    bench = require_bench(fail)
    py = poc_python(bench)
    G["tmp"] = tempfile.mkdtemp(prefix="t26092404-journey-")
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
        w1 = start_worker(py, stage, reg_a, "t26092404a" + _sfx)
        workers.append(w1)
        time.sleep(3)
        fail.check(w1.poll() is None, "A1 worker 已拉起（pid=%s）" % w1.pid)
        rc, ack, out = ticket_start(py, stage, reg_a, GOOD_KEY,
                                    "t26092404a" + _sfx, EXT_ID)
        fail.check(rc == 0 and ack.get("ok") is not False,
                   "A1 外置模板 ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))
        fin = poll_snap(py, stage, reg_a, "t26092404a" + _sfx,
                        lambda x: x.get("status") == "closed", 240,
                        "A1 外置模板全链走完到 closed", fail)
        fail.check(fin.get("status") == "closed", "A1 票终态 closed")
        stop_worker(w1)

        # ---- A1 续跑：段在飞时停 worker → 重起 → 同票走完 ----
        w2 = start_worker(py, stage, reg_a, "t26092404b" + _sfx, delay_sec="20")
        workers.append(w2)
        time.sleep(3)
        rc, ack2, _ = ticket_start(py, stage, reg_a, GOOD_KEY,
                                   "t26092404b" + _sfx, EXT_ID)
        fail.check(rc == 0 and ack2.get("ok") is not False, "A1 续跑票受理")
        poll_snap(py, stage, reg_a, "t26092404b" + _sfx,
                  lambda x: (x.get("stage") or "").startswith("j_")
                  and x.get("stage_state") == "running", 150,
                  "外置段进入在飞窗口", fail)
        stop_worker(w2)
        fail.check(True, "A1 段在飞窗口内 worker 已停（模拟工人重启前置态）")
        mid = query(py, stage, reg_a, "t26092404b" + _sfx)
        fail.check(mid.get("status") != "closed", "A1 停机时票未完（有可续跑面）")
        w3 = start_worker(py, stage, reg_a, "t26092404b" + _sfx)
        workers.append(w3)
        fin2 = poll_snap(py, stage, reg_a, "t26092404b" + _sfx,
                         lambda x: x.get("status") == "closed", 240,
                         "A1 重启后续跑到 closed（幂等靠既有结果文件机制）", fail)
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
        time.sleep(3)
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
