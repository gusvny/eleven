# -*- coding: utf-8 -*-
"""t260908-01 共享夹具（本票两场景 sc_ki061_* 共用；非 sc_ 前缀＝共享代码不登记）。

提供：docker 舞台环境组装 / fixture 仓 / 引擎 spawn 桩（arbitrate 可控 verdict）/
工单专属 worker 拉起 / signal 直发 / snapshot 轮询。骨架抄自 t260905-10
sc_host_ruling_injection.py（该夹具已实锤跑通「桩链路到 arbitrate blocked」全程）。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
from lib_gate import (Fail, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402,F401
                      require_bench, require_stage, run_poc_client, stage_down)

# 引擎目录定位（t260907-10 摊平后=server/engine；回落旧路径一轮，摘除票删旧子用例）
POC_DIR = os.path.join(REPO, "server", "engine")
if not os.path.isdir(POC_DIR):
    POC_DIR = os.path.join(REPO, "server", "dsh", "temporal-poc")  # engine-venv-compat

# KI-061 修复契约（create_plan v2 S3 拍板）：测试开关读定于 worker 构造期，
# 置 1=模拟修复前 worker（重置守卫失效）；缺省=修复启用。场景硬编码此名——
# implement 改名=场景红（TDD 信号，契约面点名）。
ENV_DISABLE_KI061 = "SANDBAR_TEST_DISABLE_KI061"
# 本场景自有桩的 verdict 开关（worker 环境读定；两相各起一个 worker，切换即换回执）
ENV_ARB_STUB_VERDICT = "SANDBAR_KI061_SC_ARB_VERDICT"


# 引擎 spawn 命令桩：argv=[py, stub, ...flags, <prompt>]，prompt 恒末位。
# ①prompt 原样落 JSONL 账本（断言面=agent 实收 prompt）；②arbitrate 桩按
# ARB_STUB_VERDICT 回三态 verdict（tests-fault→6 轮超限 blocked / pass→过仲裁边）；
# 其余段回合法 ok（秒过）。files_changed 带一条 docs 改动（settle 有物可落）。
ARB_STUB = r"""
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
with open(os.environ["KI061_STUB_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"stage": stage, "ts": time.time(), "prompt": prompt},
                       ensure_ascii=False) + "\n")
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    if stage == "arbitrate":
        verdict = os.environ.get("SANDBAR_KI061_SC_ARB_VERDICT", "tests-fault")
        body = {"status": "ok",
                "summary": "verdict=%s（ki061 桩：集成测试集仍红，需迭代测试集）" % verdict,
                "report": "[ki061-stub] 机械仲裁回执 verdict=%s" % verdict,
                "deliverables": [], "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "ki061-stub"}
    else:
        body = {"status": "ok", "summary": "[ki061-stub] %s 完成" % stage,
                "report": "[ki061-stub] 桩回执", "deliverables": [],
                "files_changed": ["docs/ticket-notes.md"],
                "files_changed_shape": "ok", "evidence": "ki061-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


def make_fixture_repo(tmp):
    """fixture 项目仓：git init + 首 commit（骨架抄 t260905-10）。"""
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


def stage_env(state, registry_dir, audit_env=None):
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % state["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = state["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = registry_dir
    if audit_env:
        env.update(audit_env)
    return env


def spawn_worker(py, tid, env, log_path, stub_path, stub_log,
                 disable_ki061=False, arb_verdict="tests-fault"):
    """工单专属 worker（前台跑，watch 收口自退）。worker 构造期读定的两个开关：
    disable_ki061→SANDBAR_TEST_DISABLE_KI061=1（模拟修复前 worker，两相闸的相一）；
    arb_verdict→桩的 arbitrate 三态回执。"""
    wenv = dict(env)
    # 队列契约对齐 ticket_worker.spawn（t260907-04 退役账#2）：新票 workflow 起在
    # sandbar-ticket-<tid>（shared.ticket_task_queue 新前缀），专属 worker 必须新旧
    # 双前缀 CSV poll——旧单值 SANDBAR_TASK_QUEUE 只 poll 旧前缀（骨架抄自
    # t260905-10 时的过期契约，本票 260908 首跑实证：workflow 起在新前缀队列无人
    # 认领，票卡 create_plan 零推进、query 派单超时）。
    wenv["SANDBAR_TASK_QUEUES"] = "sandbar-ticket-%s,suyou-ticket-%s" % (tid, tid)  # naming-compat
    wenv["SANDBAR_WATCH_WORKFLOW"] = tid
    wenv["SANDBAR_WATCH_INTERVAL_SEC"] = "2"
    wenv["SANDBAR_AGENT_CMD"] = "%s %s" % (py, stub_path)
    wenv["KI061_STUB_LOG"] = stub_log
    wenv[ENV_ARB_STUB_VERDICT] = arb_verdict
    if disable_ki061:
        wenv[ENV_DISABLE_KI061] = "1"
    else:
        wenv.pop(ENV_DISABLE_KI061, None)
    logf = open(log_path, "ab")
    return subprocess.Popen([py, os.path.join(POC_DIR, "worker.py")],
                            env=wenv, cwd=POC_DIR,
                            stdout=logf, stderr=subprocess.STDOUT,
                            start_new_session=True)


def send_signal(py, state, tid, name, payload):
    """绕过 client op 白名单直发 signal（retry_qc/host_ruling 契约面）。"""
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


LAST_Q = {"rc": None, "out": ""}  # 末次 query 原始回执（失败归因用，抄 t260905-10 _LAST_Q 同款）


def query_snapshot(py, env, tid):
    rc, out = run_poc_client(py, "ticket", {"op": "query", "ticket_id": tid}, env)
    LAST_Q.update(rc=rc, out=(out or "")[:300])
    return ((parse_json_loose(out).get("result") or {}).get("snapshot")) or {}


def parse_json_loose(out):
    s = out or ""
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return {}


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


def arb_gens(rows):
    """账本里 arbitrate 边的 spawn 序列（gen 从 prompt 里「第 N 次进本段」人话提取）。"""
    out = []
    for r in rows:
        if r.get("stage") != "arbitrate":
            continue
        m = re.search(r"第 (\d+) 次进本段", r.get("prompt") or "")
        out.append({"gen": int(m.group(1)) if m else -1,
                    "prompt": r.get("prompt") or ""})
    return out


def poll(fn, timeout_s, interval=1.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    return None


def wait_worker_alive(fail, worker, wlog):
    """worker 提前退出=即时点名（日志尾随附，不干等到超时才发现）。"""
    if worker.poll() is not None:
        try:
            tail = open(wlog, encoding="utf-8").read()[-600:]
        except OSError:
            tail = "<log 不可读>"
        fail.bail("worker 提前退出（rc=%s）——日志尾：%s" % (worker.returncode, tail))


def drive_to_overlimit_blocked(py, fail, tmp, tid, state, proj_key, audit_env,
                               poll_s=420):
    """相一公共驱动：DISABLE=1 worker ＋ tests-fault 桩 → 6 轮超限 blocked。
    返回 (worker, env, stub_log)。proj_key=fixture 注册表 key（registry 已就位）。"""
    stub_path = os.path.join(tmp, "ki061_stub.py")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(ARB_STUB)
    stub_log = os.path.join(tmp, "stub.jsonl")
    env = stage_env(state, os.environ["_KI061_REG_DIR"], audit_env)
    worker = spawn_worker(py, tid, env, os.path.join(tmp, "workerA.log"),
                          stub_path, stub_log, disable_ki061=True,
                          arb_verdict="tests-fault")
    wlog = os.path.join(tmp, "workerA.log")
    fail.check(worker.poll() is None, "相一 worker（DISABLE=1）已拉起 pid=%s" % worker.pid)

    rc, out = run_poc_client(py, "ticket-start", {
        "ticket_id": tid, "template_id": "dev-lane", "project": proj_key,
        "title": "KI-061 超限唤醒两相闸", "write_set": ["docs/"]}, env)
    fail.check(rc == 0 and tid in out,
               "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))

    def _blocked():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)  # bail
        s = query_snapshot(py, env, tid)
        # 并行分叉期 meta.stage 报「分叉内最后进入的单边」（acceptance_walkthrough），
        # 超限 blocked 挂在 arbitrate 边时 snapshot stage 不一定是 "arbitrate"
        #（与 selfcheck 相一 _stuck 同口径；260908 首跑实证 stage=acceptance_walkthrough）。
        if (s.get("stage") in ("arbitrate", "arb_acc_parallel", "acceptance_walkthrough")
                and s.get("stage_state") == "blocked"
                and "超限" in json.dumps(s, ensure_ascii=False)):
            return s
        return None
    snap = poll(_blocked, poll_s)
    if snap is None:
        wait_worker_alive(fail, worker, wlog)
        s = query_snapshot(py, env, tid)
        fail.bail("相一未在 %ds 内到达超限 blocked（现 stage=%s state=%s）"
                  % (poll_s, s.get("stage"), s.get("stage_state")))
    fail.check(True, "相一到达超限 blocked（复刻 02:12 卡死前置态）")
    return worker, env, stub_log
