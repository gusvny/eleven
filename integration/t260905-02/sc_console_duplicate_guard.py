#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260905-02 场景③：多 console 同槽防重与辨析文案（工单正文行为 3）。

intent（守护的用户可感知行为）：
- server 单例：同槽（同 config.port）temporal server 已有监听者 → 第二个 console
  的 supervisor 静默认领现役实例（不重复 spawn、不报错）——双 console 不打架；
- worker 单例：daemon worker pidfile 在册且进程存活 → 双 console 均不重复拉起；
  且 dispose 只停「本会话 spawn 的」——在册他人 worker 不被顺手杀（资源归属）；
- 工单 worker 抢注互斥＋辨析文案：同 tid 工单 worker 的 pidfile 抢注失败
  （O_EXCL 'wx' 必败注入：pidfile 位被占）→ 辨析文案在文（「已被别的实例抢先
  注册，停掉重复 spawn」语义）、重复拉起的 child 当场被 SIGTERM 回收（日志 fd
  持有者归零观测，无孤儿存活）、成功 spawn 文案不出现（防「报了错又装成功」
  两开花）；
- dispose 收口：两次 apply 的 dispose 可调、幂等二连不抛、定时器清空
  （node 自然退出=事件循环空，挂死=执行器超时红）。

intent 分工（防 intent 级重复）：
- t260904-02-worker-fingerprint-gate＝ensureTicketWorkersOnce 纯决策面三态
  （同仓/异仓/未知，spawn 可注入）；本条＝apply 全真路径的双 console 防重
  （端口探测/pidfile 存活探测/真 spawnTicketWorker 的 'wx' 互斥与辨析文案）——
  纯决策面不含 'wx' 互斥分支，彼场景替代不了本条；
- 本条异常子用例经真 apply→ensureTicketWorkers→spawnTicketWorker 走真 child 路径，
  pidfile 位以目录占位使 'wx' 确定性必败（readPid 对目录返回 null→按缺位推进
  →写注必撞）——故障注入不靠时序竞态。

三态契约：docker 台缺席=ENV_FAIL exit 2；node 缺席=ENV_FAIL 点名；被测 python
子进程（cli 的 client.py、被 spawn 的 worker.py）零连生产（审计钩子经 env 继承
护体+自证子用例）；日志锚兼容正则锚语义不锁措辞（KI-051）。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "t260904-02"))                    # lib_gate
sys.path.insert(0, os.path.dirname(_HERE))                                     # integration/
sys.path.insert(0, _HERE)                                                      # lib_t26090502
from lib_gate import (NODE_TS, Fail, cleanup, parse_out_json,  # noqa: E402
                      poc_python, read_audit_jsonl, require_bench, require_stage,
                      run_poc_client, stage_down, wait_port_released)
import stage_docker  # noqa: E402
from lib_t26090502 import POC, child_env, log_holders, pid_alive  # noqa: E402

TAG = "dup-%d" % os.getpid()
PROJ_KEY = "t26090502-dup"
TID = "t26090502-%s" % TAG
DATA_DIR = os.path.join(POC, "data")   # 工单 worker pidfile/meta/log 的真实落点（node.ts 由 repo 推导）
# node 驱动体：动态 import node.ts，fake ctx（logger 记行+tools.register 空转）。
# 无 process.exit：dispose 若未清 keepalive/ticketEnsure 定时器，事件循环不空、
# node 挂死=执行器超时红——定时器回收的可观测面。
NODE_BODY = r"""
import { pathToFileURL } from 'node:url'
import { format } from 'node:util'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const mk = () => {
  const lines = []
  const rec = (lvl) => (...a) => lines.push(lvl + ' ' + format(...a))
  return { lines, ctx: { logger: { info: rec('info'), warn: rec('warn'), error: rec('error') },
                         tools: { register() {} } } }
}
const mod = await import(pathToFileURL(process.env.NODE_TS).href)
const need = ['apply', 'ensureTicketWorkersOnce']
const missing = need.filter((n) => typeof mod[n] !== 'function')
if (missing.length) {
  console.log(JSON.stringify({ error: 'missing_export', missing }))
  process.exit(4)
}
const cfg = JSON.parse(process.env.CFG)
const out = { errors: [] }
try {
  if (process.env.OP === 'mutex') {
    const c = mk()
    const dC = mod.apply(c.ctx, cfg)
    await sleep(Number(process.env.WAIT_MS || 10000))
    out.c = c.lines
    out.disposeType = typeof dC
    if (typeof dC === 'function') dC()
  } else {
    const a = mk()
    const dA = mod.apply(a.ctx, cfg)
    const b = mk()
    const dB = mod.apply(b.ctx, cfg)
    await sleep(Number(process.env.WAIT_MS || 8000))
    out.a = a.lines
    out.b = b.lines
    out.disposeAType = typeof dA
    out.disposeBType = typeof dB
    if (typeof dA === 'function') { dA(); dA() }  // dispose 幂等二连
    if (typeof dB === 'function') dB()
  }
  await sleep(2000)
} catch (e) {
  out.errors.push(String((e && e.stack) || e))
}
console.log(JSON.stringify(out))
"""


def run_node(node_env, timeout_s=150):
    """跑 node 驱动体。返回 (rc, parsed_out|None, node_pid)。"""
    p = subprocess.Popen(["node", "--input-type=module", "-e", NODE_BODY],
                         env=node_env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return p.returncode or -1, None, p.pid
    j = parse_out_json(out)
    return p.returncode, (j if j else None), p.pid


def main():
    fail = Fail("t260905-02 ③双 console 同槽防重（server/worker 单例+抢注互斥辨析）")
    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="sandbar-it-t26090502-dup-")
    stage_state = None
    sleeper = None
    audit_env = audit_log = None
    tid_paths = [os.path.join(DATA_DIR, "worker-%s.pid" % TID),
                 os.path.join(DATA_DIR, "worker-%s.log" % TID),
                 os.path.join(DATA_DIR, "worker-%s.meta" % TID)]
    try:
        # ---------- ① 起台 + fixture ----------
        _, state = require_stage(fail, "t26090502-%s" % TAG, "dup-%s" % TAG)
        stage_state = state
        host = "127.0.0.1:%d" % state["ports"]["temporal"]
        port = state["ports"]["temporal"]
        fail.check(port not in bench.PROD_PORTS, "舞台端口不在生产禁区面（%d）" % port)
        proj = os.path.join(tmp, "proj")
        os.makedirs(proj, exist_ok=True)
        reg = bench.write_registry(os.path.join(tmp, "reg"), PROJ_KEY, proj)
        audit_env, audit_log = bench.audit_hook_env(os.path.join(tmp, "audit"))
        env0 = child_env(host, state["namespace"], audit_env,
                         {"SANDBAR_PROJECTS_DIR": reg})
        # 260927（KI-142）：调用方身份一处声明——本 env 后面还有 gated 写 op（cancel），
        # 只补建票会「前面绿、后面红」。值=本场景自己的夹具项目 key。
        env0["SANDBAR_CALLER_PROJECT"] = PROJ_KEY

        # daemon worker pidfile 夹具：活 pid 占位（sleep 子进程，非 worker，零时间连接）
        sleeper = subprocess.Popen(["sleep", "600"])
        pidfile = os.path.join(tmp, "daemon-worker.pid")
        with open(pidfile, "w") as f:
            f.write(str(sleeper.pid))
        cfg = {"repo": os.path.realpath(os.path.join(_HERE, "..", "..")),
               "python": py, "port": port, "pidfile": pidfile,
               "serverLog": os.path.join(tmp, "server.log"),
               "workerLog": os.path.join(tmp, "worker.log"),
               "keepaliveMs": 3600000, "ticketEnsureMs": 3600000}

        def node_env(op, wait_ms):
            e = dict(os.environ)
            e["NODE_TS"] = NODE_TS
            e["OP"] = op
            e["WAIT_MS"] = str(wait_ms)
            e["CFG"] = json.dumps(cfg)
            e["SANDBAR_TARGET_HOST"] = host          # apply 内部 cli/ensure 子进程只连舞台
            e["SANDBAR_NAMESPACE"] = state["namespace"]
            e["SANDBAR_PROJECTS_DIR"] = reg
            e.update(audit_env or {})
            return e

        # ---------- ② 正常子用例：双 console 静默认领（server 单例+worker 单例） ----------
        rc1, out1, npid1 = run_node(node_env("dup", 8000))
        if rc1 == 4:
            fail.check(False, "node.ts 契约 export 缺失：%s"
                       % (out1 or {}).get("missing"))
            out1 = None
        else:
            fail.check(rc1 == 0 and out1 is not None,
                       "双 console 驱动自然退出 rc=0（dispose 清定时器可观测；rc=%s）" % rc1)
        if out1:
            fail.check(not out1.get("errors"),
                       "驱动体零异常（errors=%s）" % out1.get("errors"))
            fail.check(out1.get("disposeAType") == "function"
                       and out1.get("disposeBType") == "function",
                       "两次 apply 都返回 dispose（实得 %s/%s）"
                       % (out1.get("disposeAType"), out1.get("disposeBType")))
            for label in ("a", "b"):
                lines = out1.get(label) or []
                joined = "\n".join(lines)
                fail.check(not any(("已 spawn temporal server" in ln or
                                    "已 spawn worker" in ln) for ln in lines),
                           "console %s 不重复 spawn server/worker（静默认领现役实例）" % label)
                fail.check("boot 失败" not in joined,
                           "console %s 零 boot 失败（认领不是报错）" % label)
            fail.check(pid_alive(sleeper.pid),
                       "在册 daemon worker（夹具 sleep pid=%d）未被 dispose 顺手杀" % sleeper.pid)
            with open(pidfile) as f:
                fail.check(f.read().strip() == str(sleeper.pid),
                           "在册 worker pidfile 内容原样（归属未被篡改）")

        # ---------- ③ 异常子用例：工单 worker pidfile 抢注互斥 + 辨析文案 ----------
        rc_t, out_t = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "防重辨析场景票", "write_set": ["docs/"]}, env0)
        jt = parse_out_json(out_t)
        fail.check(rc_t == 0 and jt.get("ok") is True,
                   "开票成功（rc=%s out=%s）" % (rc_t, out_t.strip()[:100]))
        listed = False
        deadline = time.time() + 30
        while time.time() < deadline:
            _, out_r = run_poc_client(py, "running-tickets", {}, env0)
            rows = (parse_out_json(out_r).get("result") or {}).get("running") or []
            if any(r.get("id") == TID for r in rows):
                listed = True
                break
            time.sleep(1.0)
        fail.check(listed, "工单 RUNNING 在册（running-tickets 可见 tid=%s）" % TID)
        # 'wx' 必败注入：pidfile 位以目录占位（readPid 对目录=null→按缺位推进→写注必撞 EEXIST）
        os.makedirs(tid_paths[0], exist_ok=True)
        rc2, out2, npid2 = None, None, None
        p2 = subprocess.Popen(["node", "--input-type=module", "-e", NODE_BODY],
                              env=node_env("mutex", 10000), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        time.sleep(16)  # 给 boot ensure 轮（serverAlive→cli→spawn→'wx' 撞→SIGTERM）留足窗口
        # 重复 child 回收观测：child 的 stdout/stderr=node 开的工单 worker 日志 fd，
        # 持有者归零即 child 已死（lsof 文件持有者查询，沙箱可用；ps 类名目观测被拒）
        holders = log_holders(tid_paths[1])
        deadline = time.time() + 10
        while holders and time.time() < deadline:
            time.sleep(2)
            holders = log_holders(tid_paths[1])
        try:
            o2, _ = p2.communicate(timeout=90)
            rc2 = p2.returncode
        except subprocess.TimeoutExpired:
            p2.kill()
            o2, _ = p2.communicate()
            rc2 = -1
        out2 = parse_out_json(o2)
        fail.check(rc2 == 0 and out2 is not None,
                   "互斥驱动自然退出 rc=0（rc=%s）" % rc2)
        if out2:
            lines = out2.get("c") or []
            fail.check(any("抢先注册" in ln and TID in ln for ln in lines),
                       "辨析文案在文且点名 tid（「已被别的实例抢先注册，停掉重复 spawn」语义）")
            fail.check(not any("已 spawn 工单 worker" in ln for ln in lines),
                       "抢注失败分支无成功 spawn 文案（不两开花）")
            fail.check(out2.get("disposeType") == "function",
                       "apply 返回 dispose（实得 %s）" % out2.get("disposeType"))
        if holders is None:
            print("N/A  重复 child 回收观测：lsof 文件持有者查询在本环境不可用"
                  "（观测面缺失，非被测行为红；互斥分支本身已由辨析文案子用例判定）", flush=True)
        else:
            fail.check(holders == [],
                       "重复拉起的 child 已被 SIGTERM 回收（日志文件零存活持有者；实得 %s）"
                       % holders)
        fail.check(os.path.exists(tid_paths[1]),
                   "重复 child 确被真拉起过（工单 worker 日志文件在：%s）" % tid_paths[1])

        # ---------- ④ 红线：零连生产 + 审计钩子自证 ----------
        hits = read_audit_jsonl(audit_log)
        fail.check(not hits,
                   "被测 python 子进程（cli/被 spawn worker）零生产连接尝试（审计 %d 条：%s）"
                   % (len(hits), json.dumps(hits, ensure_ascii=False)[:120]))
        self_env = dict(os.environ)
        self_env.update(audit_env)
        self_env["SANDBAR_AUDIT_SELFTEST"] = "1"
        p = subprocess.run([py, "-c",
                            "import socket; socket.create_connection(('127.0.0.1', 7233), timeout=2)"],
                           env=self_env, capture_output=True, text=True, timeout=30)
        self_hits = read_audit_jsonl(audit_log)
        fail.check(p.returncode != 0 and any("7233" in json.dumps(h) for h in self_hits),
                   "审计钩子自证：故意连 7233 被阻断（rc=%s）且留记录（%d 条）"
                   % (p.returncode, len(self_hits)))

        # ---------- ⑤ teardown：工单收口 + 真实 dataDir 只清本 tid + 拆台 ----------
        try:
            run_poc_client(py, "cancel", {"workflow_id": TID}, env0)
        except Exception:
            pass
        d = stage_down(stage_docker, state["project"])
        stage_state = None
        fail.check(d.get("residue") == [],
                   "舞台 down 后零残留容器（实得 %s）" % (d.get("residue"),))
        released, held = wait_port_released(port)
        fail.check(released, "舞台 temporal 端口已释放（%s）"
                   % ("已释放" if released else "仍被占用 pid=%s" % held))
    finally:
        if sleeper is not None and sleeper.poll() is None:
            try:
                sleeper.terminate()
                sleeper.wait(timeout=5)
            except Exception:
                pass
        for rel in tid_paths:
            try:
                if os.path.isdir(rel):
                    os.rmdir(rel)          # 只可能是我们 mkdir 的空目录桩
                elif os.path.exists(rel):
                    os.remove(rel)
            except OSError:
                pass
        if stage_state is not None:
            try:
                stage_docker.do_down(stage_state["project"])
            except Exception:
                pass
        cleanup(tmp)
    fail.finish()


if __name__ == "__main__":
    main()
