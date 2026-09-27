#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-14 负向重放夹具生成器（fixtures/README 路①的执行体，integration acceptance 段一次性）。

产物：本目录 history_with_suggest_next.json —— 含 prepare_epic_next / suggest_next
活动命令的旧形态 dev-lane history（temporal CLI `workflow show -o json` 同形状，
replay_check --history 可消费）。

做法（零生产接触）：把退役前代码（implement 提交之父 e8b6fe0，git archive 导出，
不动主库 .git）放到 /tmp 隔离树，在**自建 docker 隔离台**（require_stage 起临时台，
随机端口）上用退役前 worker 驱动一条真票全链（全段桩会话 + SANDBAR_SUGGEST_STUB=ok
桩建议 + arbitrate verdict=pass 一次过），到 merge 人工门签字放行 → merge 落库 →
suggest_next 段真实调度 prepare_epic_next + suggest_next 活动（桩秒回）→ closed；
temporalio SDK 只读 fetch_history 导出（与 replay_check 同级只读口径）。

环境红线：SANDBAR_PROJECTS_DIR 指夹具注册表（零真环境写）；不碰生产台/真注册表/
~/.sandbar；机器级状态零变更（迁移动作不属本脚本）。

用法：server/engine/.venv/bin/python integration/t260910-14/fixtures/make_pre_retire_history.py
  --pre-tree DIR   退役前代码树（缺省自动 git archive 到 /tmp/pre-retire-t260910-14）
  --keep           保留临时目录与退役前树（排查用）
退出：0=夹具已落且自证含 suggestion 活动命令；1=任一步失败（点名哪步）。
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260904-02"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260908-01"))

from lib_gate import Fail, parse_out_json, poc_python, require_bench, require_stage, stage_down  # noqa: E402
from lib_ki061 import ARB_STUB, make_fixture_repo, stage_env  # noqa: E402

PRE_COMMIT = "e8b6fe0"          # implement 落盘提交之父 = 退役前代码
DEFAULT_PRE_TREE = "/tmp/pre-retire-t260910-14"
TID = "t26091014fx-fixgen"
PROJ_KEY = "t26091014fx"
EPIC = "ep-fixgen"
OUT = os.path.join(HERE, "history_with_suggest_next.json")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def say(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg, flush=True)
    return ok


def prepare_pre_tree(path):
    """退役前代码树：git archive 导出（只读主库对象，不写主库 .git）。"""
    if os.path.isdir(os.path.join(path, "server", "engine")):
        say(True, "退役前树已就位（复用 %s）" % path)
        return True
    os.makedirs(path, exist_ok=True)
    r = sh("git -C %s archive %s | tar -x -C %s" % (REPO, PRE_COMMIT, path), shell=True)
    if r.returncode != 0:
        say(False, "git archive 导出失败：%s" % (r.stderr or "")[-200:])
        return False
    dev_lane = open(os.path.join(path, "server", "engine", "dev_lane.py"), encoding="utf-8").read()
    if "suggest_next" not in dev_lane:
        say(False, "退役前树不含 suggest_next（导错版本 %s）" % PRE_COMMIT)
        return False
    return say(True, "退役前树导出（%s @ %s，dev_lane 含 suggest_next 段）" % (path, PRE_COMMIT))


def pre_client(py, tree, sub, args, env, timeout=120):
    """退役前树的 client 调用（驱动工具与被驱代码同版本，history 形态保真）。"""
    p = subprocess.run([py, os.path.join(tree, "server", "engine", "client.py"),
                        sub, json.dumps(args)],
                       env=env, cwd=os.path.join(tree, "server", "engine"),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def query_snap(py, tree, env, tid):
    rc, out = pre_client(py, tree, "ticket", {"op": "query", "ticket_id": tid}, env)
    return ((parse_out_json(out).get("result") or {}).get("snapshot")) or {}


def poll(fn, timeout_s, interval=2.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    return None


async def export_history(host, ns, tid):
    from temporalio.client import Client
    c = await Client.connect(host, namespace=ns)
    h = c.get_workflow_handle(tid)
    history = await h.fetch_history()
    return json.loads(history.to_json())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pre-tree", default=DEFAULT_PRE_TREE)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    fail = Fail("t260910-14 负向夹具生成（路①退役前代码×隔离台×桩）")
    bench = require_bench(fail)
    py = poc_python(bench)
    stage_mod = None
    worker = None
    tmp = tempfile.mkdtemp(prefix="t26091014fx-")
    ok = True
    try:
        if not prepare_pre_tree(args.pre_tree):
            return 1

        stage_mod, state = require_stage(fail, "%s-%d" % (PROJ_KEY, os.getpid()), "t26091014fx")

        # 夹具仓 + 立项单档案（suggest_next 活动读的面）
        repo = make_fixture_repo(tmp)
        epics_dir = os.path.join(repo, "notes", "epics")
        os.makedirs(epics_dir, exist_ok=True)
        with open(os.path.join(epics_dir, "%s.md" % EPIC), "w", encoding="utf-8") as f:
            f.write("# 【立项单】%s\n\n夹具立项单：供退役前 prepare_epic_next 读取（生成含 suggestion 活动命令的 history）。\n" % EPIC)
        registry = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY, repo)

        env = stage_env(state, registry)
        env["SANDBAR_TASK_QUEUES"] = "sandbar-ticket-%s,suyou-ticket-%s" % (TID, TID)
        env["SANDBAR_WATCH_WORKFLOW"] = TID
        env["SANDBAR_WATCH_INTERVAL_SEC"] = "2"
        stub_path = os.path.join(tmp, "agent_stub.py")
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(ARB_STUB)
        env["SANDBAR_AGENT_CMD"] = "%s %s" % (py, stub_path)
        env["KI061_STUB_LOG"] = os.path.join(tmp, "stub.jsonl")
        env["SANDBAR_KI061_SC_ARB_VERDICT"] = "pass"   # 仲裁一次过，直奔 merge 门
        env["SANDBAR_SUGGEST_STUB"] = "ok"             # 建议桩：零模型调用秒回
        # 260927（KI-142）：本夹具走**退役前树**的 client（PRE_COMMIT 早于身份闸），
        # 今天不受影响；但 PRE_COMMIT 一旦被提高到 260915-12 之后，建票与 sign 都会
        # 被身份闸拒收——这里先声明好，旧 client 忽略未知键、无害，且免疫该漂移。
        env["SANDBAR_CALLER_PROJECT"] = PROJ_KEY

        pre_engine = os.path.join(args.pre_tree, "server", "engine")
        logf = open(os.path.join(tmp, "worker.log"), "ab")
        worker = subprocess.Popen([py, os.path.join(pre_engine, "worker.py")],
                                  env=env, cwd=pre_engine,
                                  stdout=logf, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        ok &= say(worker.poll() is None, "退役前 worker 已拉起 pid=%s" % worker.pid)

        rc, out = pre_client(py, args.pre_tree, "ticket-start",
                             {"ticket_id": TID, "template_id": "dev-lane",
                              "project": PROJ_KEY, "title": "t260910-14 负向夹具生成票",
                              "write_set": ["docs/"], "epic": EPIC}, env)
        started = rc == 0 and TID in out
        ok &= say(started, "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-160:]))
        if not started:
            wlog = open(os.path.join(tmp, "worker.log"), encoding="utf-8", errors="replace").read()[-500:]
            print("worker 日志尾：%s" % wlog)
            return 1

        wlog_path = os.path.join(tmp, "worker.log")

        def _dead():
            if worker.poll() is not None:
                try:
                    tail = open(wlog_path, encoding="utf-8", errors="replace").read()[-600:]
                except OSError:
                    tail = "<log 不可读>"
                print("FAIL worker 提前退出（rc=%s）日志尾：%s" % (worker.returncode, tail))
                raise SystemExit(1)

        def _at_merge_gate():
            _dead()
            s = query_snap(py, args.pre_tree, env, TID)
            if s.get("stage") == "merge":
                return s
            return None
        snap = poll(_at_merge_gate, 420)
        if snap is None:
            _dead()
            s = query_snap(py, args.pre_tree, env, TID)
            ok &= say(False, "未在 420s 内到达 merge 门（现 stage=%s state=%s status=%s）"
                      % (s.get("stage"), s.get("stage_state"), s.get("status")))
            return 1
        ok &= say(True, "到达 merge 人工门（stage=merge state=%s）" % snap.get("stage_state"))

        rc, out = pre_client(py, args.pre_tree, "ticket",
                             {"op": "sign", "ticket_id": TID, "gate": "merge",
                              "who": "integration-fixture", "decision": "approve",
                              "note": "t260910-14 夹具生成：放行使 suggest_next 段真实调度"}, env)
        ok &= say(rc == 0, "merge 签字放行（rc=%s out尾=%s）" % (rc, out[-140:]))

        def _closed():
            _dead()
            s = query_snap(py, args.pre_tree, env, TID)
            st = s.get("status") or (s.get("meta") or {}).get("status")
            if st == "closed":
                return s
            return None
        fin = poll(_closed, 420)
        if fin is None:
            s = query_snap(py, args.pre_tree, env, TID)
            ok &= say(False, "签字后未在 420s 内 closed（现 stage=%s state=%s）"
                      % (s.get("stage"), s.get("stage_state")))
            return 1
        ok &= say(True, "票已 closed（suggest_next 段随 merge 签字真实跑过）")

        data = asyncio.run(export_history("127.0.0.1:%d" % state["ports"]["temporal"],
                                          state["namespace"], TID))
        text = json.dumps(data, ensure_ascii=False)
        has_epic_prep = "prepare_epic_next" in text
        has_suggest = '"suggest_next"' in text or "suggest_next" in text
        has_sched = "Scheduled" in text
        ok &= say(has_epic_prep and has_sched,
                  "自证：history 含 suggestion 活动命令（prepare_epic_next=%s suggest_next=%s "
                  "含调度事件=%s，events=%d）" % (has_epic_prep, has_suggest, has_sched,
                                                 len(data.get("events") or [])))
        if not (has_epic_prep and has_sched):
            return 1
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        ok &= say(os.path.getsize(OUT) > 0, "夹具已落 %s（%d 字节）" % (os.path.relpath(OUT, REPO),
                                                                    os.path.getsize(OUT)))
        return 0 if ok else 1
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
        if stage_mod is not None:
            try:
                stage_down(stage_mod, "%s-%d" % (PROJ_KEY, os.getpid()))
            except Exception:
                pass
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("（--keep：临时件留 %s）" % tmp)


if __name__ == "__main__":
    sys.exit(main())
