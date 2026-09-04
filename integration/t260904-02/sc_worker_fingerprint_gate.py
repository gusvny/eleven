#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-02 场景②：worker 归属指纹 ensure 闸——真执行路径（epic 验收 2；review_plan C1 硬条件）。

intent（守护的用户可感知行为）：
- 工单 worker 自报 meta（JSON：pid / repo_root / ts），起跑早写（connect 前）；
- ensure 侧读 meta 三态判定并**留下可断言的行为记录**（review_plan C1：断言落
  公开行为输出，源级 grep 只能作辅助——契约不变的实现重构不得打破本场景）：
  · 同仓 worker 伺服同票 → 照旧不重复拉（不 spawn）；
  · 异仓 worker 伺服同票 → 拒接（不 spawn 自己的）+ 告警记录含异仓根/pid/tid
    ——绝不 kill 别人的进程（杀进程归人）；
  · meta 缺失/畸形 → 兼容跳过（不 spawn）+ 原因可辨（不哑巴，事后可查）；
- TERM worker 后 meta 被清理（资源回收）。

node.ts 对外契约（本场景守护，缺 export=红并点名——C1 附条件交付面）：
  export readWorkerMeta(path) -> obj | null        # 读+解析，坏/缺=null
  export judgeTicketWorkerMeta(meta, ownRepoRoot)
      -> 'same' | 'foreign' | 'unknown'
  export ensureTicketWorkersOnce(deps) -> { decisions: [...] }
      deps = { dataDir, repoRoot, running: [{id, queue}], spawn? }
      spawn 可注入（缺省=真 spawn）；decision = { tid, action,
        warn?: { repoRoot, pid, tid }, reason?: str }
      action ∈ 'spawned' | 'held-same' | 'held-foreign' | 'held-unknown'

红线：全程只连槽位 temporalite；不 touch 3099/生产 7233/8233。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_gate import (NODE_TS, Fail, cleanup, parse_out_json, poc_python,  # noqa: E402
                      port_listening, require_bench, check_slot_contract)

TID = "t26090402-gate"
WORKER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                         "server", "dsh", "temporal-poc", "worker.py")

NODE_GATE_EXPORTS = ("readWorkerMeta", "judgeTicketWorkerMeta", "ensureTicketWorkersOnce")

_NODE_BODY = """
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const mod = await import(pathToFileURL(process.env.NODE_TS).href)
const present = {}
for (const n of %s) present[n] = typeof mod[n] === 'function'
const missing = Object.keys(present).filter(n => !present[n])
if (missing.length) {
  console.log(JSON.stringify({ error: 'missing_export', missing }))
  process.exit(4)
}
if (process.env.GATE_OP === 'judge') {
  const meta = mod.readWorkerMeta(process.env.GATE_META)
  console.log(JSON.stringify({ meta, judge: mod.judgeTicketWorkerMeta(meta, process.env.GATE_OWN) }))
} else {
  const deps = JSON.parse(process.env.GATE_DEPS)
  const calls = []
  deps.spawn = (tid, queue) => { calls.push({ tid, queue }); return { pid: -1 } }
  const res = await mod.ensureTicketWorkersOnce(deps)
  console.log(JSON.stringify({ decisions: (res && res.decisions) ? res.decisions : res,
                               spawnCalls: calls }))
}
""" % json.dumps(list(NODE_GATE_EXPORTS))


def node_gate(op, env_extra, fail, label):
    """跑 node 动态 import node.ts 的闸探针。返回解析后的 JSON dict 或 None（已计红）。"""
    env = dict(os.environ)
    env["NODE_TS"] = NODE_TS
    env["GATE_OP"] = op
    env.update(env_extra)
    p = subprocess.run(["node", "--input-type=module", "-e", _NODE_BODY],
                       capture_output=True, text=True, timeout=90, env=env)
    if p.returncode == 4:
        j = parse_out_json(p.stdout)
        fail.check(False, "%s：node.ts 契约 export 缺失（C1 硬条件交付面）：%s（stderr=%s）"
                   % (label, j.get("missing"), (p.stderr or "").strip()[:100]))
        return None
    if p.returncode != 0:
        fail.check(False, "%s：node 闸探针非零退出 rc=%s（stderr=%s）"
                   % (label, p.returncode, (p.stderr or "").strip()[:160]))
        return None
    j = parse_out_json(p.stdout)
    fail.check(bool(j), "%s：node 闸探针产出可解析 JSON（stdout=%s）"
               % (label, p.stdout.strip()[:160]))
    return j if j else None


def wait_meta(path, timeout_s=40):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        time.sleep(0.5)
    return None


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_round(fail, data_dir, meta_body, label, want_action):
    """布置 dataDir（真活 pid + meta）→ 真调 ensureTicketWorkersOnce → 断言决策+不 spawn。"""
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "worker-%s.pid" % TID), "w") as f:
        f.write(str(_STATE["pid"]))
    with open(os.path.join(data_dir, "worker-%s.meta" % TID), "w") as f:
        f.write(meta_body)
    deps = {"dataDir": data_dir, "repoRoot": _STATE["own_root"],
            "running": [{"id": TID, "queue": _STATE["queue"]}]}
    j = node_gate("ensure", {"GATE_DEPS": json.dumps(deps)}, fail, label)
    if not j:
        return None
    ds = j.get("decisions") or []
    fail.check(isinstance(ds, list) and len(ds) >= 1,
               "%s：decisions 非空（实得 %r）" % (label, ds))
    fail.check(not j.get("spawnCalls"),
               "%s：不重复 spawn（spawnCalls=%s；杀进程归人，本闸只拒接）"
               % (label, j.get("spawnCalls")))
    d = ds[0] if ds else {}
    fail.check(str(d.get("tid", "")) == TID, "%s：decision 点名工单 tid（实得 %r）" % (label, d.get("tid")))
    fail.check(d.get("action") == want_action,
               "%s：action=%s（期望 %s）" % (label, d.get("action"), want_action))
    return d


_STATE = {}


def main():
    fail = Fail("t260904-02 ②worker 归属指纹 ensure 闸（真执行路径）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26090402-gate-")
    slot = None
    worker = None
    try:
        # ---------- ① 槽位台 + 真 worker（自报 meta，起跑早写） ----------
        slot = bench.acquire_slot()
        check_slot_contract(fail, slot, "槽")
        slot.start_temporalite()
        fail.check(port_listening(slot.frontend_port), "槽 frontend %d 探活" % slot.frontend_port)
        meta_path = os.path.join(tmp, "worker-%s.meta" % TID)
        wenv = dict(os.environ)
        wenv.update({
            "SUYOU_TASK_QUEUE": "bench-gate-%d" % slot.index,
            "SUYOU_WATCH_WORKFLOW": "t260904-02-gate-none",  # 不存在的 workflow：watch 查询失败不退出
            "SUYOU_TARGET_HOST": "127.0.0.1:%d" % slot.frontend_port,
            "SUYOU_NAMESPACE": slot.namespace,
            "SUYOU_WORKER_META": meta_path,
        })
        worker = subprocess.Popen([py, os.path.abspath(WORKER_PY)], env=wenv,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        meta = wait_meta(meta_path)
        fail.check(meta is not None,
                   "worker 起跑早写 meta（connect 前；40s 内落盘 %s）" % meta_path)
        if meta is None:
            fail.bail("worker 未自报 meta——指纹链路未交付，后续断言无从谈起", 1)
        _STATE["pid"] = worker.pid
        _STATE["own_root"] = str(meta.get("repo_root") or "")
        _STATE["queue"] = "bench-gate-%d" % slot.index
        fail.check(int(meta.get("pid", -1)) == worker.pid,
                   "meta.pid 与真进程一致（meta=%r worker.pid=%s）" % (meta.get("pid"), worker.pid))
        fail.check(os.path.isabs(_STATE["own_root"]) and bool(_STATE["own_root"]),
                   "meta.repo_root 为非空绝对路径（实得 %r）" % _STATE["own_root"])
        fail.check("ts" in meta, "meta 含 ts 字段（形状契约）")
        fail.check(pid_alive(worker.pid), "worker 进程活（伺服同票形态成立）")

        # ---------- ② judge 三态真值（导出契约+参数面） ----------
        fake_foreign = os.path.join(tmp, "fake-foreign-root")
        good_meta = os.path.join(tmp, "m-good.json")
        with open(good_meta, "w") as f:
            json.dump({"pid": worker.pid, "repo_root": _STATE["own_root"], "ts": 1}, f)
        foreign_meta = os.path.join(tmp, "m-foreign.json")
        with open(foreign_meta, "w") as f:
            json.dump({"pid": worker.pid, "repo_root": fake_foreign, "ts": 1}, f)
        bad_meta = os.path.join(tmp, "m-bad.json")
        with open(bad_meta, "w") as f:
            f.write('{"pid": "not-a-number", "repo_root": ')  # 坏 JSON
        for m, own, want, label in (
                (good_meta, _STATE["own_root"], "same", "同仓判定"),
                (foreign_meta, _STATE["own_root"], "foreign", "异仓判定"),
                (foreign_meta, fake_foreign, "same", "对方视角同仓"),
                (bad_meta, _STATE["own_root"], "unknown", "畸形 meta 判定")):
            j = node_gate("judge", {"GATE_META": m, "GATE_OWN": own}, fail, label)
            if j:
                fail.check(j.get("judge") == want,
                           "%s：judge=%r（期望 %r）——readWorkerMeta+judgeTicketWorkerMeta 真值"
                           % (label, j.get("judge"), want))

        # ---------- ③ ensure 真执行三态（C1 主断言：行为输出非源级 grep） ----------
        d1 = ensure_round(fail, os.path.join(tmp, "ens-same"),
                          json.dumps(meta), "同仓：照旧不重复拉", "held-same")
        d2 = ensure_round(fail, os.path.join(tmp, "ens-foreign"),
                          json.dumps({"pid": worker.pid, "repo_root": fake_foreign, "ts": 1}),
                          "异仓：拒接+告警记录", "held-foreign")
        if d2 is not None:
            warn = d2.get("warn") or {}
            fail.check(str(warn.get("repoRoot", "")) == fake_foreign,
                       "异仓告警记录含对方仓根（实得 %r）" % warn.get("repoRoot"))
            fail.check(int(warn.get("pid", -1)) == worker.pid,
                       "异仓告警记录含对方 pid（实得 %r）" % warn.get("pid"))
            fail.check(str(warn.get("tid", "")) == TID,
                       "异仓告警记录含工单 tid（实得 %r）" % warn.get("tid"))
        d3 = ensure_round(fail, os.path.join(tmp, "ens-unknown"),
                          '{"pid": 1, ', "畸形 meta：兼容跳过+原因可辨", "held-unknown")
        if d3 is not None:
            fail.check(bool(str(d3.get("reason") or "")),
                       "unknown 决策带 reason（meta 路径/失败原因，事后可查不哑巴）")

        # ---------- ④ 资源回收：TERM → 进程退 + meta 清理 ----------
        worker.terminate()
        try:
            worker.wait(timeout=15)
            fail.check(True, "TERM 后 worker 15s 内退出")
        except Exception:
            fail.check(False, "TERM 后 worker 15s 内未退（kill 兜底前先计红）")
            worker.kill()
            worker.wait(timeout=10)
        gone = not os.path.exists(meta_path)
        t0 = time.time()
        while not gone and time.time() - t0 < 8:
            gone = not os.path.exists(meta_path)
            time.sleep(0.5)
        fail.check(gone, "worker 优雅退清理自报 meta（%s）" % meta_path)
    finally:
        if worker is not None and worker.poll() is None:
            try:
                worker.kill()
            except Exception:
                pass
        if slot is not None:
            try:
                slot.stop()
            except Exception:
                pass
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
