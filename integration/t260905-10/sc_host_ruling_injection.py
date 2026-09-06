#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-10 场景①：blocked 态宿主裁决注入 → arbitrate 下轮 prompt 可见（KI-053 端到端）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
真起 workflow（docker 测试台 temporal-only + 真工单专属 worker），宿主在 blocked
态经 client `ticket op=ruling` 注入裁决，断言 **arbitrate 段下一轮**的派活 prompt
带裁决文本，且注入前各轮不带；事件历史（snapshot meta.log）留痕、全文兜底
（meta.host_rulings）经 query 可查。

驱动机制（review D1 要求写明；本场景是三篇里唯一真起 workflow 的）：
- 模型边界桩：SUYOU_AGENT_CMD 指向 recorder 桩（spawn 命令单点 _prepare_agent_spawn
  的 cmd=list(DSH_CMD)，_run_agent_stage_impl 与 arbitrate 全口径生效）。recorder
  把引擎递来的 prompt 原样落 JSONL 账本（=mock 端点收到的 messages 的等价观测面，
  用户可感知产物），再按交付契约把结果文件写回（status=ok、summary 恒无 verdict=
  标记）——是纯进程内桩，不连任何真模型。
- 前序段怎么走到 arbitrate：recorder 桩让 create_plan/review_plan/implement/
  design_integration_tests 秒回合法结果；arbitrate 桩回执恒缺 verdict= 标记 →
  三次格式纠正后 _blocked("arbitrate")（引擎既有契约路径，不需要真集成测试红）。
- 裁决怎么进下轮：blocked 态发 host_ruling（只入账不唤醒）+ retry_qc（唤醒重跑
  本步）→ workflow 以 gen+1 重跑 arbitrate，build_stage_prompt 注入 meta.host_rulings，
  recorder 账本即记到带裁决的 prompt。
- 断言面=recorder 账本（agent 实收 prompt）/快照 log/host_rulings，不逐字节锚
  prompt 小节标题文案（措辞是实现副本，改文案不应红）。

红线（testing-guide）：本场景绝不触碰生产 7233/8233/3099——被测 worker/client 子进程
经 bench.audit_hook_env 审计钩子（连接生产端口=先记后抛），终局断言审计账本为空；
探活只打舞台端口。pool=exclusive（真起 workflow 占台）。

三态：docker/镜像/temporal CLI 缺席=exit 2 ENV_FAIL（点明环境缺件，非被测红）。

作者与协作注记：初稿出自并行 implement 段（共享泳道 parallel_impl_design 阶段的
既成撞面）；design_integration_tests 段（integration，场景资产所有者）复核改写并
扩充断言面——拒收两态（超大 note intake 闸/空白 note 信号层拒收）、多条裁决累积、
旧→新排序、{ts,who,note} 形状契约。断言面与 run_scenarios 登记 intent 以本版为
准；后续再改动须过 integration 复核（验收资产不得由被测方单方面演化）。
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
from lib_gate import (Fail, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)

TID = "t26090510-ruling"
PROJ_KEY = "t26090510-ruling"
RULING_NOTE = "仲裁意见（宿主）：venv 软链已补，测试红属环境面——按 fixtures 修复路径走"
RULING_WHO = "宿主（夜话仲裁席）"
RULING_NOTE2 = "仲裁意见（宿主·第二条）：检疫增强已上，blocked 重跑前先看隔离区告警再定重试面"
RULING_WHO2 = "宿主（夜话仲裁席·第二意见）"
BIG_NOTE = "超限压力测试" * 3400  # 20400 字>intake 闸（20000）：refused 拒收，不进事件历史
# （developer 段修正：×30000=210KB 走 client argv 会撞 E2BIG "Argument list too long"
#  ——闸语义只要「超限」即可，不必逼近进程参数上限）

RECORDER = r"""
# 引擎 spawn 命令桩（SUYOU_AGENT_CMD 指向本脚本）：argv=[py, recorder, ...flags, <prompt>]
# ——引擎按 dsh CLI 组装命令（--patch 等 flag 在前），prompt 恒为末位 argv。
# 职责：①prompt 原样落账本（JSONL，供场景断言）；②按交付契约把结果文件写回
# （status=ok，summary 恒不带 verdict= 标记 → arbitrate 三次格式纠正后 blocked）。
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
with open(os.environ["RECORDER_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"stage": stage, "ts": time.time(), "prompt": prompt},
                       ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    body = {"status": "ok", "summary": "[recorder] %s 完成" % stage,
            "report": "[recorder] 桩回执（无 verdict 标记）",
            "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
            "files_changed_shape": "ok", "evidence": "recorder-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


def stage_env(state, registry_dir, audit_env=None):
    env = dict(os.environ)
    env["SUYOU_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SUYOU_NAMESPACE"] = state["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = registry_dir
    if audit_env:
        env.update(audit_env)
    return env


def make_fixture_repo(tmp):
    """fixture 项目仓：git init + repo 级身份（面③处置承诺的正向面）+ 首 commit。"""
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


def spawn_worker(py, tid, env, log_path, recorder_path, recorder_log):
    """工单专属 worker（前台跑，watch 收口自退；不走 --daemon——双叉会让日志与
    进程脱离场景管控）。返回 Popen。"""
    wenv = dict(env)
    wenv["SUYOU_TASK_QUEUE"] = "suyou-ticket-%s" % tid
    wenv["SUYOU_WATCH_WORKFLOW"] = tid
    wenv["SANDBAR_WATCH_INTERVAL_SEC"] = "2"
    wenv["SUYOU_AGENT_CMD"] = "%s %s" % (py, recorder_path)
    wenv["RECORDER_LOG"] = recorder_log
    logf = open(log_path, "ab")
    return subprocess.Popen([py, os.path.join(REPO, "server", "dsh", "temporal-poc",
                                               "worker.py")],
                            env=wenv, cwd=os.path.join(REPO, "server", "dsh", "temporal-poc"),
                            stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)


def send_retry_qc(py, state, tid):
    """retry_qc signal（client op 白名单外，直接 temporalio 驱动；payload=who 字符串）。"""
    script = (
        "import asyncio\n"
        "from temporalio.client import Client\n"
        "async def main():\n"
        "    c = await Client.connect('127.0.0.1:%d', namespace='%s')\n"
        "    await c.get_workflow_handle('%s').signal('retry_qc', '宿主')\n"
        "asyncio.run(main())\n" % (state["ports"]["temporal"], state["namespace"], tid))
    p = subprocess.run([py, "-c", script], capture_output=True, text=True, timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def send_raw_signal(py, state, tid, name, payload):
    """绕过 client op 白名单直发 signal（payload 原样过线）——钉 workflow 侧
    信号契约本身（拒收三态/载荷解码），client 包装层管不着的面。"""
    script = (
        "import asyncio\n"
        "from temporalio.client import Client\n"
        "async def main():\n"
        "    c = await Client.connect('127.0.0.1:%d', namespace='%s')\n"
        "    await c.get_workflow_handle('%s').signal(%r, %r)\n"
        "asyncio.run(main())\n"
        % (state["ports"]["temporal"], state["namespace"], tid, name, payload))
    p = subprocess.run([py, "-c", script], capture_output=True, text=True, timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_json_loose(out):
    """宽松 JSON 提取：client 回执含多行/先导杂行——取首 { 到末 } 整段解析
    （单行 parse_out_json 对多行回执会抓到内层行恒空，快照轮空假红）。"""
    s = out or ""
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return {}


_LAST_Q = {"rc": None, "out": ""}


def query_snapshot(py, env, tid):
    rc, out = run_poc_client(py, "ticket", {"op": "query", "ticket_id": tid}, env)
    _LAST_Q.update(rc=rc, out=(out or "")[:240])
    return ((parse_json_loose(out).get("result") or {}).get("snapshot")) or {}


def read_recorder_log(path):
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


def poll(fn, timeout_s, interval=1.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    return None


def main():
    fail = Fail("t260905-10 ①blocked 态宿主裁决注入→arbitrate 下轮 prompt 可见")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26090510-ruling-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    recorder_path = os.path.join(tmp, "recorder.py")
    with open(recorder_path, "w", encoding="utf-8") as f:
        f.write("import time\n" + RECORDER)
    recorder_log = os.path.join(tmp, "recorder.jsonl")
    stage_mod = None
    stage = None
    worker = None
    try:
        # ---------- ① 起 docker 舞台 + fixture 注册表 + 专属 worker ----------
        stage_mod, stage = require_stage(fail, "t26090510-ruling-%d" % os.getpid(),
                                         "t26090510-ruling")
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        env = stage_env(stage, reg_dir, audit_env)
        worker = spawn_worker(py, TID, env, os.path.join(tmp, "worker.log"),
                              recorder_path, recorder_log)
        wlog = os.path.join(tmp, "worker.log")
        fail.check(worker.poll() is None, "专属 worker 已拉起（pid=%s）" % worker.pid)

        # ---------- ② 开票：recorder 桩链路跑到 blocked(arbitrate) ----------
        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "宿主裁决注入端到端", "write_set": ["docs/"]}, env)
        # 回执是多行 JSON（describe 明细），不逐行 parse——rc==0 且票号在场即受理
        fail.check(rc == 0 and TID in out,
                   "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))

        last_seen = {"snap": {}}

        def _blocked_at_arbitrate():
            s = query_snapshot(py, env, TID)
            if s:
                last_seen["snap"] = s
            if s.get("stage") == "arbitrate" and s.get("stage_state") == "blocked":
                return s
            return None
        snap = poll(_blocked_at_arbitrate, 420)
        if snap is None and worker.poll() is not None:
            try:
                tail = open(wlog, encoding="utf-8").read()[-600:]
            except OSError:
                tail = "<log 不可读>"
            fail.check(False, "worker 提前退出（rc=%s）——日志尾：%s"
                       % (worker.returncode, tail))
        _ls = last_seen["snap"]
        fail.check(snap is not None,
                   "桩链路到达 blocked(arbitrate)（420s 末见 stage=%s state=%s status=%s；"
                   "已过段=%s；末次 query rc=%s）"
                   % (_ls.get("stage"), _ls.get("stage_state"), _ls.get("status"),
                      sorted((_ls.get("results") or {}).keys()), _LAST_Q["rc"]))
        if snap is None:
            fail.finish()
            return

        pre_rows = [r for r in read_recorder_log(recorder_log) if r.get("stage") == "arbitrate"]
        fail.check(bool(pre_rows), "blocked 前已有 arbitrate 派活 %d 轮（桩链路账本在位）" % len(pre_rows))
        fail.check(not [r for r in pre_rows if RULING_NOTE in (r.get("prompt") or "")],
                   "注入前各轮 prompt 不带裁决文本（对照组）")

        # ---------- ③ blocked 态注入裁决（client op=ruling）＋ retry_qc 唤醒 ----------
        rc, out = run_poc_client(py, "ticket", {
            "op": "ruling", "ticket_id": TID, "who": RULING_WHO, "note": RULING_NOTE}, env)
        r = (parse_json_loose(out).get("result") or {})
        fail.check(rc == 0 and r.get("signal") == "host_ruling" and r.get("delivered"),
                   "op=ruling 受理并发信（rc=%s out=%s）" % (rc, out[-160:]))
        snap = query_snapshot(py, env, TID)
        fail.check(snap.get("stage") == "arbitrate" and snap.get("stage_state") == "blocked",
                   "裁决只入账不唤醒：仍 blocked(arbitrate)")
        rulings = (snap.get("meta") or {}).get("host_rulings") or []
        fail.check(any(x.get("note") == RULING_NOTE and x.get("who") == RULING_WHO
                       for x in rulings),
                   "全文兜底可查：meta.host_rulings 含 {ts,who,note} 条目（query 面）")
        log_notes = "｜".join(str(e.get("note") or "") for e in (snap.get("meta") or {}).get("log") or [])
        fail.check("宿主裁决注入" in log_notes, "事件历史留痕：meta.log 有注入账")
        fail.check(bool(rulings) and all(x.get("ts") for x in rulings),
                   "裁决条目形状 {ts,who,note}：ts 在位（何时留痕）")

        # ---------- ③b 拒收两态 + 累积第二裁决（仍 blocked，未唤醒） ----------
        refused0 = len(snap.get("refused") or [])

        def _refused_grew(delta):
            def _q():
                s = query_snapshot(py, env, TID)
                return s if len(s.get("refused") or []) >= refused0 + delta else None
            return _q

        rc, out = run_poc_client(py, "ticket", {
            "op": "ruling", "ticket_id": TID, "who": RULING_WHO, "note": BIG_NOTE}, env)
        fail.check(rc == 0, "超大 note client 受理发信（rc=%s）" % rc)
        got = poll(_refused_grew(1), 30)
        fail.check(got is not None, "超大 note 被 intake 闸拒收进 refused（不进事件历史）")
        snap = query_snapshot(py, env, TID)
        fail.check(len((snap.get("meta") or {}).get("host_rulings") or []) == 1,
                   "超大 note 拒收后 meta.host_rulings 仍 1 条（载荷不入账）")

        rc, out = send_raw_signal(py, stage, TID, "host_ruling",
                                  {"who": RULING_WHO, "note": "   "})
        fail.check(rc == 0, "纯空白 note 直发信号上线（rc=%s %s）" % (rc, out[-120:]))
        got = poll(_refused_grew(2), 30)
        fail.check(got is not None, "空白 note workflow 侧拒收进 refused（信号层契约，非仅 client）")

        rc, out = run_poc_client(py, "ticket", {
            "op": "ruling", "ticket_id": TID, "who": RULING_WHO2, "note": RULING_NOTE2}, env)
        fail.check(rc == 0, "第二条裁决受理（rc=%s）" % rc)

        def _two_rulings():
            s = query_snapshot(py, env, TID)
            return s if len((s.get("meta") or {}).get("host_rulings") or []) >= 2 else None
        snap = poll(_two_rulings, 30)
        fail.check(snap is not None and snap.get("stage_state") == "blocked",
                   "两条裁决累积入账且仍未唤醒 blocked")

        rc, out = send_retry_qc(py, stage, TID)
        fail.check(rc == 0, "retry_qc 唤醒（rc=%s %s）" % (rc, out[-120:]))

        def _arb_with_ruling():
            rows = [r for r in read_recorder_log(recorder_log) if r.get("stage") == "arbitrate"]
            for r in rows[len(pre_rows):]:   # 只看注入后的新增轮
                if RULING_NOTE in (r.get("prompt") or ""):
                    return r
            return None
        hit = poll(_arb_with_ruling, 300)
        fail.check(hit is not None, "arbitrate 下轮 prompt 含裁决文本（验收①核心）")
        if hit:
            prompt = hit.get("prompt") or ""
            fail.check(RULING_WHO in prompt, "下轮 prompt 同时带裁决人")
            fail.check(RULING_NOTE2 in prompt, "下轮 prompt 含第二条裁决（多条累积全可见）")
            fail.check(RULING_WHO2 in prompt, "下轮 prompt 带第二条裁决人")
            fail.check(prompt.find(RULING_NOTE) < prompt.find(RULING_NOTE2),
                       "旧→新排序（先发的在前，最新贴着现在）")
            # 锚小节头特征「宿主裁决注入（」——票题「宿主裁决注入端到端」不带全角
            # 括号，不会被题名抢配（断言才不是撞题名的假绿）
            fail.check(prompt.find(RULING_NOTE) > prompt.find("宿主裁决注入（") > -1,
                       "裁决在小节头之后出现（注入面结构在位）")

        # ---------- ④ 红线：被测子进程零触碰生产端口 ----------
        rows = read_audit_jsonl(audit_log)
        fail.check(not rows, "审计账本为空：被测子进程零连生产端口（实得 %d 条）" % len(rows))
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
