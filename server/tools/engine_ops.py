#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine_ops.py —— 引擎运作面工具（宿主 260930 当面令）：一条命令回答
「**这张票是谁在服务、它吃哪份代码、离 main 漂了多远**」。

背景（实况，设计前提）：轻道真票 t260930-09 连推 4 轮都对不上，最后靠 Temporal 历史的
activity `identity` 才查出「服务它的是另一个 worker（pid 63268）」；而 `.lane/<tid>/` 里
那份引擎代码里新常量出现 0 次（主仓 4 次）。两件事**必须一起讲**（判据各有各的面）：

  · **谁在服务** = 每张票的 workflow 由**它的专属队列**上的 worker 进程执行；进程在启动时
    把引擎模块导入内存 ⇒ **引擎修要在飞票生效必须换进程**（`restart --scope lane:<tid>`）；
  · **哪份代码在验** = 闸在**泳道树**（`.lane/<tid>`，开票那刻的快照）里跑
    `integration/run_scenarios.py` 与夹具 ⇒ 主仓的修复不带进泳道就等于没修
    （`sync <ticket>` 把 main 并进泳道一次）。

子命令（只读优先；改动类只有 sync/restart 且都走既有单点与守卫）：
  workers                     中央 worker + 每张票的泳道 worker：pid / 吃的树 / 代码指纹 /
                              是否在轮询 / 该队列**活** poller 数
  who <ticket> [--round N]    这张票最近一轮是谁服务的（逐轮 activity identity + 类型），
                              再给该进程吃的树与它的代码指纹
  drift <ticket>              推票前判据：泳道缺哪些已落 main 的引擎修 / 泳道 worker 是否
                              stale / 队列活 poller 是否恰 1 —— 有漂移即告警（exit 1）逐条点名
  sync <ticket> [--dry-run]   把 main 并进泳道一次（幂等；经 Temporal 调**引擎既有单点**
                              `prepare_conflict_resolution`，绝不手写 git merge）
  restart --scope central|lane:<tid> [--replace]
                              走 worker.py 的启动守卫（活进程拒启 / --replace 才优雅回收），
                              换手后**自证恰好一个活 poller**

输出约定：stdout **单行 JSON**（同 client.py/verify_lane.py 家族）`{"ok":…,"result"|"error":…}`；
退出码：0=正常、1=告警（drift 检出漂移 / poller 数≠1）、2=环境面不可得（Temporal 连不上、
venv 缺件）。**默认只读**；不碰 3099。

poller 计数语义（**必须按活着的进程**）：server 会保留刚退出 worker 的 poller 历史，直接数
列表长度会把「刚被换下的旧颗」读成第二颗（假红）。本工具按 identity 里的 pid 逐个
`shared.pid_alive()` 过滤：`live` / `stale_history` / `unverifiable`（异机 identity 查不了，
如实分栏，不混进 live）。
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime
import glob
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time

TOOL = pathlib.Path(__file__).resolve()
REPO = TOOL.parents[2]
ENGINE = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE))

import shared  # noqa: E402  (stdlib-only)
import ticket_worker as tw  # noqa: E402

DATA = ENGINE / "data"
ALERT_EXIT = 1
ENV_EXIT = 2


# ---------------------------------------------------------------- Temporal 可选面
# 引擎模块只在**不沙箱**的临时 worker 里按名调用（见 _run_activity）；导入失败=该面具名不可得。
try:
    from temporalio import workflow as _wf

    _TEMPORAL_OK = True
    _TEMPORAL_ERR = ""
except Exception as _e:  # noqa: BLE001
    _wf = None
    _TEMPORAL_OK = False
    _TEMPORAL_ERR = "%s: %s" % (type(_e).__name__, str(_e)[:160])

_ACTIVITY_NAMES = ("prepare_conflict_resolution", "settle_conflict_resolution")
if _TEMPORAL_OK:
    @_wf.defn
    class _EngineOpsOneShot:
        """极薄活动执行器（模块级类——SDK 拒绝 local class）。

        只做一件事：把 `{"name","payload"}` 映射到引擎既有 activity 单点并返回其 dict 结果。
        **不含任何合并/提交逻辑**（那是 activity 本体的职责，唯一实现纪律）。"""

        @_wf.run
        async def run(self, req: dict) -> dict:
            with _wf.unsafe.imports_passed_through():
                import agent_activities as _aa
                from shared import ConflictPrepArgs, ConflictSettleArgs
            registry = {"prepare_conflict_resolution": (_aa.prepare_conflict_resolution,
                                                        ConflictPrepArgs),
                        "settle_conflict_resolution": (_aa.settle_conflict_resolution,
                                                       ConflictSettleArgs)}
            name = str(req.get("name") or "")
            fn, args_cls = registry[name]
            res = await _wf.execute_activity(
                fn, args_cls(**dict(req.get("payload") or {})),
                start_to_close_timeout=datetime.timedelta(seconds=300),
                retry_policy=_wf.RetryPolicy(maximum_attempts=1)
                if hasattr(_wf, "RetryPolicy") else None)
            return dataclasses.asdict(res)


def _activity_registry():
    """临时 worker 要注册的 activity 对象（引擎既有单点本体）。"""
    with _wf.unsafe.imports_passed_through():
        import agent_activities as _aa
    return {n: getattr(_aa, n) for n in _ACTIVITY_NAMES}


# ---------------------------------------------------------------- 基础面
def _ok(result: dict) -> dict:
    return {"ok": True, "result": result}


def _err(msg: str, **extra) -> dict:
    out = {"ok": False, "error": msg}
    out.update(extra)
    return out


def _print(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, default=str))
    if payload.get("ok"):
        return 0
    return int(payload.get("exit", ALERT_EXIT))


def _iso(ts) -> str:
    try:
        v = float(ts)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    return datetime.datetime.fromtimestamp(v).isoformat(timespec="seconds")


def git(args, cwd) -> tuple:
    p = subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True,
                       text=True, timeout=120)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def tree_of_pid(pid) -> dict:
    """进程**吃的树**：cwd 解析（lsof → /proc）；查不到=具名不可得，不猜。"""
    if not pid or not shared.pid_alive(pid):
        return {"tree": "", "available": False,
                "note": "不可得：进程不在（无 cwd 可读）"}
    try:
        p = subprocess.run(["lsof", "-a", "-p", str(int(pid)), "-d", "cwd", "-Fn"],
                           capture_output=True, text=True, timeout=30)
        for ln in (p.stdout or "").splitlines():
            if ln.startswith("n"):
                return {"tree": ln[1:].strip(), "available": True, "source": "lsof cwd"}
    except Exception:  # noqa: BLE001——lsof 缺失/被拒都不是拦点，继续试 /proc
        pass
    try:
        return {"tree": os.readlink("/proc/%d/cwd" % int(pid)), "available": True,
                "source": "/proc cwd"}
    except OSError:
        pass
    return {"tree": "", "available": False,
            "note": "不可得：lsof 与 /proc 都读不到该进程 cwd（沙箱拒绝或非本机）"}


def local_host_aliases() -> set:
    """本机主机别名集合（poller identity 里的 host 段是 **worker 自己的**解析结果，
    与连接地址不必相同：实测 `36741@192.0.2.132` 对 `127.0.0.1:7233`）。"""
    import socket
    out = {"127.0.0.1", "localhost", "::1"}
    try:
        hn = socket.gethostname()
        out.add(hn.lower())
        try:
            out.add(socket.gethostbyname(hn))
        except OSError:
            pass
        for ip in socket.gethostbyname_ex(hn)[2]:
            out.add(ip)
    except OSError:
        pass
    return out


def repo_root_from_tree(tree: str) -> str:
    """进程 cwd → 它服务的**仓根**（逐级上溯找 `server/engine/worker.py`；找不到=原样返回）。

    为什么不能直接把 cwd 当仓根：泳道/中央 worker 的 cwd 都是 `<repo>/server/engine`
    （spawn 面 cwd=poc），把它当仓根会让代码指纹去找 `<cwd>/server/engine/*.py`（拼歪，
    指纹全空）。找不到就原样返回并在 note 里具名，不静默。"""
    if not tree:
        return ""
    p = pathlib.Path(tree)
    for cand in (p, *p.parents):
        if (cand / "server" / "engine" / "worker.py").is_file():
            return str(cand)
    return str(p)


def read_meta(pidfile) -> dict:
    meta, state, detail = shared.read_worker_meta_state(str(pidfile) + ".meta")
    return {"meta": dict(meta or {}), "state": state, "detail": detail}


def stamp_for(pid, tree, started_at="") -> dict:
    """该进程的代码指纹（复用 shared.worker_code_stamp 的唯一实现，零自造）。

    `started_at` 传**该 worker 自己的启动基准**（旁车 meta 的 ts / pidfile mtime；取不到
    就用「现在」——那样 stale 只会漏报不会误报，且 note 里写明基准来源）。
    """
    root = tree or str(REPO)
    base = started_at or datetime.datetime.now().isoformat(timespec="seconds")
    try:
        st = shared.worker_code_stamp(started_at=base, pid=(int(pid) if pid else None),
                                      repo_root=root)
    except Exception as e:  # noqa: BLE001——指纹面故障不拦主链，但必须具名
        return {"available": False, "note": "不可得：%s: %s" % (type(e).__name__, str(e)[:120]),
                "tree": root}
    st["available"] = True
    st["tree"] = root
    st["baseline"] = base
    st["line"] = shared.code_stamp_line(st)
    return st


def read_pidfile(pidfile) -> dict:
    st = shared.read_pidfile_state(str(pidfile))
    st["pidfile"] = str(pidfile)
    meta = read_meta(pidfile)
    st["meta"] = meta["meta"]
    st["meta_state"] = meta["state"]
    st["started_at"] = _iso(meta["meta"].get("ts")) or _iso(st.get("mtime"))
    return st


def classify_pollers(pollers, aliases, alive_fn) -> tuple:
    """poller 列表 → (live, stale_history, unverifiable) 三栏（**纯函数**，可判定测试）。

    判据（宿主令 260930）：**按 identity 里的 pid 验活**——server 保留刚退出 worker 的
    poller 历史，直接数长度会把「刚被换下的旧颗」读成第二颗（假红）。host 段只作附注
    （worker 自报的 host 与我们的连接地址不必相同：实测 `36741@192.0.2.132` 对
    `127.0.0.1:7233`）；identity 里没有 pid = 无法验活，进 unverifiable（不混进 live）。"""
    live, stale_hist, unver = [], [], []
    for p in pollers or []:
        ident = str(getattr(p, "identity", "") or "")
        head, _sep, rest = ident.partition("@")
        pid = int(head) if head.strip().isdigit() else None
        row = {"identity": ident,
               "last_access_time": str(getattr(p, "last_access_time", "") or ""),
               "host": rest}
        if pid is not None:
            row["host_is_local_alias"] = bool(rest) and rest.lower() in (aliases or set())
            if not rest:
                row["host_note"] = "identity 无 host 段（老 SDK 形态）"
            elif not row["host_is_local_alias"]:
                row["host_note"] = ("host 段 %r 不在本机别名集里 —— 仍按 pid 验活"
                                    "（单机运维事实），异机同名 pid 的极端情形由人复核" % rest)
        if pid is None:
            row["note"] = "identity 无 pid（无法验活）"
            unver.append(row)
        elif alive_fn(pid):
            live.append(row)
        else:
            row["note"] = "进程已不在（poller 历史残留，不算活）"
            stale_hist.append(row)
    return live, stale_hist, unver


def _queue_pollers(host: str, ns: str, queue: str) -> dict:
    """一条队列的 poller 面（**按活着的进程**分栏），Temporal 不可得=具名。"""
    try:
        from temporalio.api.taskqueue.v1 import TaskQueue
        from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
        from temporalio.client import Client
    except Exception as e:  # noqa: BLE001
        return {"queue": queue, "available": False,
                "note": "不可得：temporalio 不可用（%s）——本命令需引擎 venv 解释器"
                        % type(e).__name__,
                "live": [], "stale_history": [], "unverifiable": []}

    async def _go():
        c = await Client.connect(host, namespace=ns)
        return await c.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(namespace=ns, task_queue=TaskQueue(name=queue),
                                     report_pollers=True))

    try:
        resp = asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        return {"queue": queue, "available": False,
                "note": "不可得：describe_task_queue 失败 %s: %s"
                        % (type(e).__name__, str(e)[:160]),
                "live": [], "stale_history": [], "unverifiable": []}
    _l, _h, _u = classify_pollers(getattr(resp, "pollers", None) or [],
                                 local_host_aliases(), shared.pid_alive)
    live, stale_hist, unver = _l, _h, _u
    return {"queue": queue, "available": True, "live": live,
            "stale_history": stale_hist, "unverifiable": unver,
            "live_count": len(live), "note": "按 identity 的 pid 逐个验活（历史残留单列）"}


# ---------------------------------------------------------------- subcommand: workers
def _queues_of(tid: str) -> list:
    """某票的队列集（单点=引擎的 shared.ticket_task_queues，不在工具里抄命名规则）。

    为什么不走 ticket_worker 的同名包装：那个包装会去**目标仓**加载它的 `shared.py`
    （离线夹具仓没有该文件 ⇒ 工具内部异常）；队列命名是引擎级约定，用本工具已导入的
    `shared` 即可，跨仓也稳。"""
    try:
        return list(shared.ticket_task_queues(tid))
    except Exception:  # noqa: BLE001——命名面不可得=回落单队列（仍具名可见）
        return ["sandbar-ticket-%s" % tid]


def _enumerate_workers() -> list:
    out = []
    for pf in sorted(DATA.glob("worker*.pid")):
        name = pf.name
        m = re.match(r"worker-(.+)\.pid$", name)
        kind, tid = ("central", "") if name == "worker.pid" else \
                    (("lane", m.group(1)) if m else ("other", ""))
        st = read_pidfile(pf)
        pid = st.get("pid")
        tree = tree_of_pid(pid) if st["state"] == "live" else \
            {"tree": "", "available": False, "note": "不可得：进程不在"}
        queues = (_queues_of(tid) if tid else shared.configured_task_queues())
        out.append({
            "kind": kind, "ticket": tid, "pid": pid, "pidfile": str(pf),
            "state": st["state"], "detail": st["detail"],
            "started_at": st["started_at"],
            "meta_repo_root": str(st["meta"].get("repo_root") or ""),
            "cwd": tree.get("tree", ""),
            "tree": repo_root_from_tree(tree.get("tree", "")) or
                    str(st["meta"].get("repo_root") or ""),
            "tree_available": bool(tree.get("available")),
            "tree_note": tree.get("note", ""),
            "queues": queues,
            "stamp": stamp_for(pid, repo_root_from_tree(tree.get("tree", ""))
                               or str(st["meta"].get("repo_root") or ""),
                               st["started_at"]),
        })
    return out


def cmd_workers(args) -> dict:
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    wks = _enumerate_workers()
    queues = []
    for q in sorted({q for w in wks for q in w["queues"]}):
        queues.append(_queue_pollers(host, ns, q))
    # 每颗 worker「是否在轮询」= 它的 pid 是否出现在其队列的 live poller 里
    for w in wks:
        live_pids = set()
        for q in queues:
            if q["queue"] in w["queues"]:
                live_pids |= {int(x["identity"].split("@")[0])
                              for x in q["live"] if x["identity"].split("@")[0].isdigit()}
        if w["state"] != "live":
            w["polling"] = False
            w["polling_note"] = "进程不在 ⇒ 不轮询"
        elif not any(q["available"] for q in queues if q["queue"] in w["queues"]):
            w["polling"] = None
            w["polling_note"] = "不可得：poller 面拉不到（不冒充）"
        else:
            w["polling"] = (w["pid"] in live_pids)
            w["polling_note"] = ""
    alerts = []
    for q in queues:
        if not q["available"]:
            alerts.append("队列 %s 的活 poller 数不可得：%s" % (q["queue"], q["note"]))
        elif q["live_count"] != 1:
            alerts.append("队列 %s 的**活** poller 数=%d（应为 1）——同队列并存会让结果"
                          "不可归因到代码版本" % (q["queue"], q["live_count"]))
    res = {"repo": str(REPO), "host": host, "namespace": ns,
           "workers": wks, "queues": queues, "alerts": alerts,
           "live_poller_rule": "server 保留刚退出者的 poller 历史 ⇒ 只按活进程计数",
           "handover_rule": ("换手只有一种做法：按 pidfile TERM 现有 worker，等控制台 "
                             "temporal-tools supervisor 自动拉起（keepalive 缺省 5s）再验"
                             "「新 pid + 活 poller=1」。**不要自己起 worker**：从 agent 会话起的"
                             "worker 继承该会话沙箱（workspace-write），工作区外写 fail-closed "
                             "⇒ 票归档 EPERM（t260930-09 实案）")}
    if alerts:
        return {"ok": False, "exit": ALERT_EXIT, "error": "；".join(alerts), "result": res}
    return _ok(res)


# ---------------------------------------------------------------- subcommand: who
def _ev_time(ev) -> str:
    """事件时点 → ISO 串（protobuf Timestamp 的 repr 不可读：'seconds: 1790771016'）。"""
    t = getattr(ev, "event_time", None)
    if t is None:
        return ""
    try:
        return t.ToDatetime().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001——老形态/畸形时点不拦主链，回落原样
        return str(t)[:40]


def _has_field(ev, name: str) -> bool:
    """proto3 的 oneof 字段：**未设置时取属性会拿到默认实例**（不是 None）——
    必须用 HasField 判定，否则会把 Completed/TimedOut 等事件读成「Started 但 identity 空」。"""
    try:
        return bool(ev.HasField(name))
    except Exception:  # noqa: BLE001
        return False


def _history_rows(events) -> list:
    """事件历史 → 逐条 activity 执行（类型 + identity + 时点）。"""
    sched = {}
    for ev in events:
        if not _has_field(ev, "activity_task_scheduled_event_attributes"):
            continue
        a = ev.activity_task_scheduled_event_attributes
        sched[int(getattr(ev, "event_id", 0) or 0)] = {
            "activity": str(getattr(getattr(a, "activity_type", None), "name", "") or ""),
            "input": str(getattr(a, "input", None) or "")[:200]}
    rows = []
    for ev in events:
        if not _has_field(ev, "activity_task_started_event_attributes"):
            continue
        a = ev.activity_task_started_event_attributes
        sid = int(getattr(a, "scheduled_event_id", 0) or 0)
        rows.append({
            "event_id": int(getattr(ev, "event_id", 0) or 0),
            "at": _ev_time(ev),
            "activity": (sched.get(sid) or {}).get("activity", "(未配对)"),
            "identity": str(getattr(a, "identity", "") or ""),
            "attempt": int(getattr(a, "attempt", 0) or 0),
        })
    return rows


def cmd_who(args) -> dict:
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    try:
        from temporalio.client import Client
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit": ENV_EXIT,
                "error": "不可得：temporalio 不可用（%s）——who 需引擎 venv 解释器，"
                         "事件历史只有 server 有" % type(e).__name__}
    tid = str(args.ticket)

    async def _go():
        c = await Client.connect(host, namespace=ns)
        h = c.get_workflow_handle(tid)
        desc = await h.describe()
        hist = await h.fetch_history()
        return desc, hist

    try:
        desc, hist = asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit": ENV_EXIT,
                "error": "不可得：取 %s 的事件历史失败 %s: %s（Temporal %s 不可达或票不存在）"
                         % (tid, type(e).__name__, str(e)[:200], host)}
    rows = _history_rows(getattr(hist, "events", None) or [])
    gate_rows = [r for r in rows if r["activity"] == "run_integration_tests"]
    rounds = [{"round": i + 1, **r} for i, r in enumerate(gate_rows)]
    sel = None
    if rounds:
        want = int(args.round) if args.round else len(rounds)
        sel = next((r for r in rounds if r["round"] == want), rounds[-1])
    serving = {}
    if sel:
        ident = sel["identity"]
        head = ident.split("@", 1)[0]
        pid = int(head) if head.isdigit() else None
        tree = tree_of_pid(pid) if pid else {"tree": "", "available": False,
                                             "note": "不可得：identity 无 pid（%r）" % ident}
        pf = (DATA / ("worker-%s.pid" % tid)) if (DATA / ("worker-%s.pid" % tid)).exists() \
            else (DATA / "worker.pid")
        st = read_pidfile(pf) if pf.exists() else {"state": "absent", "pid": None,
                                                   "detail": "无 pidfile"}
        base = st.get("started_at") or ""
        serving = {
            "identity": ident, "pid": pid,
            "alive": bool(pid and shared.pid_alive(pid)),
            "cwd": tree.get("tree", ""), "tree": repo_root_from_tree(tree.get("tree", "")),
            "tree_available": bool(tree.get("available")),
            "tree_note": tree.get("note", ""),
            "pidfile": str(pf), "pidfile_state": st.get("state"),
            "pidfile_pid": st.get("pid"),
            "registered_for_this_ticket": bool(st.get("pid") == pid) if pid else False,
            "stamp": stamp_for(pid, repo_root_from_tree(tree.get("tree", "")), base) if pid else
                     {"available": False, "note": "不可得：identity 无 pid"},
            "note": ("服务进程与 pidfile 台账一致" if pid and st.get("pid") == pid
                     else "服务进程**不在本票 pidfile 台账里**（可能是中央 worker 或他票 worker "
                          "领到了本票的 task —— 具名不静默）"),
        }
    res = {
        "ticket": tid,
        "workflow_status": str(getattr(desc.status, "name", "") or ""),
        "workflow_type": str(getattr(desc, "workflow_type", "") or ""),
        "gate_rounds": rounds,
        "gate_round_count": len(rounds),
        "selected_round": (sel or {}).get("round"),
        "serving_worker": serving,
        "activities": rows[-40:],
        "source": "Temporal 事件历史 ActivityTaskStarted.identity（逐轮，含 activity 类型）",
    }
    if not rounds:
        res["note"] = ("事件历史里没有 run_integration_tests 活动（票还没到闸相位）；"
                       "activities 栏给了最近 40 条 activity 的 identity")
    return _ok(res)


# ---------------------------------------------------------------- subcommand: drift
def _lane_paths(host: str, ns: str, tid: str) -> dict:
    """泳道树与分支：优先票面快照（真源），回落 <repo>/.lane/<tid>（具名）。"""
    try:
        from temporalio.client import Client

        async def _go():
            c = await Client.connect(host, namespace=ns)
            h = c.get_workflow_handle(tid)
            return await h.query("snapshot")

        snap = asyncio.run(_go())
        ws = ((snap.get("meta") or {}).get("workspace") or {})
        path = str(ws.get("path") or "") or str((snap.get("meta") or {}).get("worktree") or "")
        branch = str((snap.get("meta") or {}).get("branch") or "")
        if path:
            return {"path": path, "branch": branch, "source": "ticket snapshot",
                    "available": True, "note": ""}
    except Exception as e:  # noqa: BLE001
        fallback = REPO / ".lane" / tid
        return {"path": str(fallback) if fallback.exists() else "", "branch": "",
                "source": "fallback .lane/%s" % tid, "available": bool(fallback.exists()),
                "note": "票面快照不可得（%s: %s）⇒ 回落 %s"
                        % (type(e).__name__, str(e)[:120], fallback)}
    fallback = REPO / ".lane" / tid
    return {"path": str(fallback) if fallback.exists() else "", "branch": "",
            "source": "fallback .lane/%s" % tid, "available": bool(fallback.exists()),
            "note": "快照里没有 workspace.path ⇒ 回落 %s" % fallback}


ENGINE_FACE = ("server/engine", "server/tools", "server/workflows", "server/installer")


def cmd_drift(args) -> dict:
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    tid = str(args.ticket)
    lane = _lane_paths(host, ns, tid)
    alerts, items = [], {}
    if not lane["available"]:
        alerts.append("泳道树不可得：%s" % lane["note"])
        return {"ok": False, "exit": ENV_EXIT, "error": "；".join(alerts),
                "result": {"ticket": tid, "lane": lane}}

    path = lane["path"]
    rc, mb = git(["merge-base", "HEAD", "main"], path)
    if rc != 0 or not mb:
        alerts.append("merge-base(main, HEAD) 取不到（%s）——无法判漂移" % (mb or "无输出")[:160])
        return {"ok": False, "exit": ENV_EXIT, "error": "；".join(alerts),
                "result": {"ticket": tid, "lane": lane}}
    mb = mb.splitlines()[0].strip()
    rc2, behind = git(["rev-list", "--count", "HEAD..main"], path)
    rc3, files = git(["diff", "--name-only", "%s..main" % mb], path)
    if rc3 != 0:
        # 输入必须检查：git 报错时它把错误文本打到 stdout/stderr —— 当成文件名列表就会造出
        # 假漂移清单（夹具实测：缺某个 ENGINE_FACE 目录时 git 直接 fatal）。具名不可得。
        alerts.append("git 面不可得（diff %s..main rc=%s）：%s" % (mb, rc3, (files or "")[:200]))
        return {"ok": False, "exit": ENV_EXIT, "error": "；".join(alerts),
                "result": {"ticket": tid, "lane": lane}}
    all_files = [f for f in (files or "").splitlines()
                 if f.strip() and f.startswith(ENGINE_FACE)]
    # 代码文件才算漂移（文档/说明不影响行为：单列出来给人看，但不告警——少一个假红面）
    engine_files = [f for f in all_files if not f.lower().endswith(".md")]
    doc_files = [f for f in all_files if f.lower().endswith(".md")]
    items["behind_commits"] = int(behind) if rc2 == 0 and behind.isdigit() else None
    items["engine_files_in_main_not_in_lane"] = engine_files
    items["doc_files_in_main_not_in_lane"] = doc_files
    items["merge_base"] = mb
    # 泳道自己的引擎副本 vs main：逐模块内容比对（可复现判据，不靠 mtime 猜）
    drift_modules = []
    for rel in engine_files:
        lp = os.path.join(path, rel)
        mp = os.path.join(str(REPO), rel)
        same = False
        try:
            with open(lp, "rb") as a, open(mp, "rb") as b:
                same = a.read() == b.read()
        except OSError:
            same = False
        drift_modules.append({"module": rel, "same_bytes": same,
                              "lane_missing": not os.path.isfile(lp)})
    items["modules"] = drift_modules
    if engine_files:
        alerts.append("泳道缺 %d 个**已落 main 的引擎面文件**（先 sync 再推票）：%s"
                      % (len(engine_files), ", ".join(engine_files[:8])))
    # 泳道 worker：stale 判据（模块 mtime 晚于该 worker 启动基准）
    pf = DATA / ("worker-%s.pid" % tid)
    worker = read_pidfile(pf) if pf.exists() else {"state": "absent", "detail": "无本票 pidfile",
                                                   "pid": None, "started_at": ""}
    tree = tree_of_pid(worker.get("pid")) if worker.get("state") == "live" else \
        {"tree": "", "available": False, "note": "不可得：本票 worker 不在"}
    stamp = None
    if worker["state"] == "live":
        stamp = stamp_for(worker["pid"], repo_root_from_tree(tree.get("tree", "")),
                          worker.get("started_at", ""))
        if stamp.get("stale"):
            alerts.append("泳道 worker（pid=%s，起于 %s）**代码指纹 stale**：%s —— 换进程前"
                          "它跑的是改动前的码" % (worker["pid"], worker.get("started_at"),
                                                ",".join(stamp["stale"])))
    items["lane_worker"] = {"pidfile": str(pf), "state": worker["state"],
                            "pid": worker.get("pid"), "started_at": worker.get("started_at"),
                            "cwd": tree.get("tree", ""),
                            "tree": repo_root_from_tree(tree.get("tree", "")),
                            "tree_note": tree.get("note", ""),
                            "stamp": stamp}
    # 活 poller 数（本票队列）
    queues = _queues_of(tid) if pf.exists() or (REPO / ".lane" / tid).exists() \
        else [_queues_of(tid)[0]]
    items["pollers"] = [_queue_pollers(host, ns, q) for q in queues]
    for q in items["pollers"]:
        if not q["available"]:
            alerts.append("队列 %s 的活 poller 数**不可得**（%s）——不能证明恰好一颗 ⇒ 不许推票"
                          % (q["queue"], q["note"]))
        elif q["live_count"] != 1:
            alerts.append("队列 %s 活 poller 数=%d（应为 1）：%s"
                          % (q["queue"], q["live_count"],
                             [x["identity"] for x in q["live"] + q["stale_history"]]))
    res = {"ticket": tid, "lane": lane, "verdict": "drift" if alerts else "clean",
           "alerts": alerts, **items,
           "rule": "推票前三条：①泳道无已落 main 的引擎漂移 ②泳道 worker 不是 stale "
                   "③本票队列活 poller 恰 1；引擎修要生效须**同步树 + 换进程**，而换进程"
                   "=kill 后等 supervisor 自动拉起（不要自己起 worker）"}
    if alerts:
        return {"ok": False, "exit": ALERT_EXIT, "error": "；".join(alerts), "result": res}
    return _ok(res)


# ---------------------------------------------------------------- subcommand: sync
def _run_activity(host: str, ns: str, activity_name: str, payload: dict,
                  timeout_s: int = 300) -> dict:
    """经 Temporal activity 执行引擎既有单点（唯一实现纪律：不自造合并动作）。

    做法：本进程起一个**只服务这一个活动**的临时 worker（队列私有、UnsandboxedWorkflowRunner
    ——避免沙箱重复导入引擎模块），用一个极薄的内建 workflow 调那个 activity，跑完即退。
    被测动作仍是 `agent_activities.prepare_conflict_resolution` / `settle_conflict_resolution`
    本体（CLI 绝不手写 git merge）。

    注：那个薄 workflow 必须是**模块级类**（SDK 实测：local class 直接 ValueError
    "Local classes unsupported, @workflow.run cannot be on a local class"——L3 场景逮到过）。
    """
    if not _TEMPORAL_OK:
        return {"ok": False, "exit": ENV_EXIT,
                "error": "不可得：sync 需引擎 venv + temporalio（%s）" % _TEMPORAL_ERR}
    try:
        from temporalio.client import Client
        from temporalio.worker import UnsandboxedWorkflowRunner, Worker
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit": ENV_EXIT, "error": "不可得：%s" % type(e).__name__}
    if activity_name not in _ACTIVITY_NAMES:
        return {"ok": False, "exit": ENV_EXIT, "error": "未知活动 %r" % activity_name}
    registry = _activity_registry()
    queue = "sandbar-engine-ops-%d" % os.getpid()
    wf_id = "engine-ops-%s-%d" % (activity_name, int(time.time() * 1000))

    async def _go():
        c = await Client.connect(host, namespace=ns)
        async with Worker(c, task_queue=queue, workflows=[_EngineOpsOneShot],
                          activities=list(registry.values()),
                          workflow_runner=UnsandboxedWorkflowRunner()):
            return await c.execute_workflow(_EngineOpsOneShot.run,
                                            {"name": activity_name, "payload": payload},
                                            id=wf_id, task_queue=queue)

    try:
        return {"ok": True, "result": asyncio.run(_go())}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit": ENV_EXIT,
                "error": "activity %s 执行失败（走 Temporal activity 单点，绝不手写 git merge）"
                         " %s: %s" % (activity_name, type(e).__name__, str(e)[:300])}


def cmd_sync(args) -> dict:
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    tid = str(args.ticket)
    lane = _lane_paths(host, ns, tid)
    if not lane["available"]:
        return {"ok": False, "exit": ENV_EXIT,
                "error": "泳道树不可得：%s" % lane["note"], "result": {"lane": lane}}
    path, branch = lane["path"], lane["branch"]
    rc, anc = git(["merge-base", "--is-ancestor", "main", "HEAD"], path)
    dry = {"ticket": tid, "lane": lane, "already_up_to_date": (rc == 0),
           "dry_run": bool(args.dry_run)}
    if rc == 0:
        dry["action"] = "none（main 已是泳道 HEAD 的祖先=已追平，幂等零动作）"
    else:
        _rcf, files = git(["diff", "--name-only", "HEAD..main"], path)
        dry["action"] = "会经 prepare_conflict_resolution 把 main 并进泳道一次"
        dry["engine_files_incoming"] = [f for f in (files or "").splitlines()
                                        if f.strip() and f.startswith(ENGINE_FACE)]
        if _rcf != 0:
            dry["git_note"] = "git diff rc=%s（清单可能不完整）" % _rcf
    if args.dry_run:
        return _ok(dry)
    if args.abort:
        out = _run_activity(host, ns, "settle_conflict_resolution",
                            {"ticket_id": tid, "worktree": path, "branch": branch,
                             "base_ref": "main", "round_no": 0, "abort": True})
        if not out["ok"]:
            return out
        return _ok({"ticket": tid, "action": "abort（复位半合并态，走既有 settle 单点）",
                    "result": out["result"]})
    out = _run_activity(host, ns, "prepare_conflict_resolution",
                        {"ticket_id": tid, "worktree": path, "branch": branch,
                         "base_ref": "main"})
    if not out["ok"]:
        return out
    r = out["result"]
    if r.get("up_to_date"):
        return _ok({"ticket": tid, "action": "already up to date（is-ancestor 快路径，零动作）",
                    "prep": r})
    if r.get("conflict_files"):
        return {"ok": False, "exit": ALERT_EXIT,
                "error": "泳道与 main 有冲突（%d 个文件）：%s —— 本工具**不代解冲突**；"
                         "让引擎走既有消解回路（票面发 rework(to_stage=implement)），"
                         "或人工解完再 sync；要复位半合并态用 `sync %s --abort`"
                         % (len(r["conflict_files"]), ", ".join(r["conflict_files"][:8]), tid),
                "result": {"ticket": tid, "prep": r}}
    if not r.get("ok"):
        return {"ok": False, "exit": ALERT_EXIT,
                "error": "主同步失败（非冲突）：%s" % (r.get("error") or "未知"),
                "result": {"ticket": tid, "prep": r}}
    # 干净合并 = prepare 自己已落合并提交（engine 既有语义：rc=0 ⇒ 已提交）
    return _ok({"ticket": tid, "action": "merged（prepare_conflict_resolution 单点已落合并提交）",
                "prep": r,
                "hint": "闸在泳道树里跑夹具；合并后请对在飞票再确认泳道 worker 是否需换进程"
                        "（restart --scope lane:%s）" % tid})


# ---------------------------------------------------------------- subcommand: restart
def _wait_dead(pid, timeout=90.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not shared.pid_alive(pid):
            return True
        time.sleep(0.3)
    return not shared.pid_alive(pid)


def _proof_single_poller(host, ns, queues, expect_pid=None) -> dict:
    """换手后自证：每条队列**活** poller 恰 1（且就是新进程，若给了 pid）。"""
    out = []
    ok = True
    for q in queues:
        row = _queue_pollers(host, ns, q)
        row["expected_pid"] = expect_pid
        if not row["available"]:
            row["verdict"] = "unverified"
            ok = False
        elif row["live_count"] != 1:
            row["verdict"] = "alert"
            ok = False
        elif expect_pid and not any(int(x["identity"].split("@")[0]) == int(expect_pid)
                                    for x in row["live"]
                                    if x["identity"].split("@")[0].isdigit()):
            row["verdict"] = "wrong-pid"
            ok = False
        else:
            row["verdict"] = "ok"
        out.append(row)
    return {"ok": ok, "queues": out}


#: 旧 worker 排空（优雅停等在飞活动）的有界等待。为什么必须单独一段：优雅停**要等在飞
#: 活动收口**，负载高的机器上可能几十秒；换手瞬间旧进程仍在排空是**合法中间态**，
#: 不能当成「poller 数不为 1」判失败（宿主 260930 打回：同一场景两台机器一绿一红）。
OLD_DRAIN_WAIT_S = 90.0
#: 采样间隔（poller 面**轮询式**采样）：单次采样正是那个假红的来源。
POLL_SAMPLE_S = 1.0


def _poll_sample(host, ns, queues, old_pid=None) -> dict:
    """一次 poller 面采样（活计数分栏）；面不可得=具名，不冒充。"""
    rows = [_queue_pollers(host, ns, q) for q in queues]
    live = [{"queue": r["queue"], "pid": int(x["identity"].split("@")[0]),
             "identity": x["identity"]}
            for r in rows if r.get("available")
            for x in (r.get("live") or []) if x["identity"].split("@")[0].isdigit()]
    return {"available": all(r.get("available") for r in rows),
            "live": live, "live_count": len(live),
            "queues": rows,
            "note": "" if all(r.get("available") for r in rows)
                    else "；".join("%s：%s" % (r["queue"], r.get("note")) for r in rows
                                   if not r.get("available"))[:200],
            "old_pid_in_live": bool(old_pid) and any(x["pid"] == old_pid for x in live)}


def _kill_and_wait_for_respawn(host, ns, pf, queues, wait_s: float,
                              old_drain_s: float = OLD_DRAIN_WAIT_S) -> dict:
    """**只 kill、等自动拉起**（宿主 260930 纠正后的唯一换手口径）。

    为什么不许自己起（今天实况）：从 agent 会话起的 worker 会**继承该会话的沙箱**
    （workspace-write）——工作区外的写全部 fail-closed，真票 t260930-09 归档时直接
    `PermissionError: [Errno 1] Operation not permitted:
    '/Users/user/.sandbar/projects/sandbar/data/tickets/t260930-09'` → `merge/blocked`。
    正确做法=按 pidfile TERM 现有 worker，**由控制台侧 temporal-tools supervisor 的
    keepalive（缺省 5s）自动拉起**（它不受本会话沙箱约束）。

    **四段有界序列**（宿主 260930 打回后定稿；每段各自有界、中间态具名、判据轮询式）：
      ① TERM 旧（按 pidfile 定位，优雅信号）；
      ② 等旧 pid **真的消失**（`pid_alive==false`，上界 `own_drain_s`=90s）——这期间若
         supervisor 已把新 pid 写进 pidfile，是**合法中间态**：结果里具名
         `phase=old-drain … new_pid=… still_alive=true`，**不判失败**；
      ③ 旧消失后，等**新 pid 出现 ∧ 活 ∧ 在轮询本队列**（上界 `wait_s`=60s，**轮询式采样**）；
      ④ 此刻才断言「本队列活 poller 恰 1 且就是新 pid」；仍有别的活 poller ⇒ 真失败
         （把全部活 poller 逐个点名）。
    任一段超时 ⇒ 失败，并点名**是哪一段**（old-drain / respawn / poller-face），绝不自己起 worker。
    """
    before = read_pidfile(pf)
    old_pid = before.get("pid")
    out = {"mode": "kill-and-wait-for-respawn", "pidfile": str(pf),
           "armed_by": "console temporal-tools supervisor keepalive（缺省 5s）",
           "before": before, "old_pid": old_pid, "new_pid": None,
           "old_drain_wait_s": old_drain_s, "respawn_wait_s": wait_s,
           "phases": [], "samples": [], "pollers_proof": None, "error": ""}
    if before["state"] != "live":
        out["error"] = ("无在册**活** worker（pidfile=%s 状态=%s：%s）——kill-only 换手无事可做。"
                        "若这张票/这条队列应该有人在服务，先查控制台里 temporal-tools "
                        "supervisor 是否在跑（它负责自动拉起）；本工具**绝不自己起 worker**"
                        "（沙箱继承会让工作区外写 fail-closed：票归档 EPERM，t260930-09 实案）"
                        % (pf, before["state"], before.get("detail") or ""))
        out["phase_failed"] = "no-live-worker"
        return out
    try:
        os.kill(int(old_pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as e:
        out["error"] = ("TERM 旧 worker pid=%s 失败（%s: %s）——未做任何其他动作"
                        % (old_pid, type(e).__name__, e))
        out["phase_failed"] = "term"
        return out

    # ---------------- ② 等旧 pid 排空（合法中间态具名，不判失败） ----------------
    t0 = time.time()
    new_pid_seen = None
    while True:
        still = shared.pid_alive(old_pid)
        st = read_pidfile(pf)
        cand = st.get("pid") if st["state"] == "live" else None
        if cand and cand != old_pid:
            new_pid_seen = cand
        sample = _poll_sample(host, ns, queues, old_pid=old_pid)
        out["samples"].append({"t": round(time.time() - t0, 1), "phase": "old-drain",
                               "old_alive": still,
                               "new_pid_seen_while_draining": new_pid_seen,
                               "live_pollers": [x["identity"] for x in sample["live"]],
                               "poller_face_available": sample["available"]})
        if not still:
            break
        if time.time() - t0 >= old_drain_s:
            out["phases"].append({"phase": "old-drain", "drained": False,
                                  "waited_s": round(time.time() - t0, 1),
                                  "new_pid_seen_while_draining": new_pid_seen})
            out["error"] = ("旧 worker pid=%s 在 %.0fs 内未排空（优雅停要等在飞活动收口；"
                            "换手**卡在这一段**）。它仍在跑 ⇒ 此刻不是失败于 poller 计数，"
                            "而是旧进程还没退：查它的日志（data/worker*.log）看「停机点名」"
                            "里的在飞活动，必要时人工处置。**本工具不自己起 worker**"
                            % (old_pid, old_drain_s))
            out["phase_failed"] = "old-drain"
            return out
        time.sleep(POLL_SAMPLE_S)
    out["phases"].append({"phase": "old-drain", "drained": True,
                          "waited_s": round(time.time() - t0, 1),
                          "new_pid_seen_while_draining": new_pid_seen,
                          "note": ("旧进程排空期间 supervisor 已起新 pid（合法中间态，不判失败）"
                                   if new_pid_seen else "旧进程已排空")})

    # ---------------- ③ 等新 pid 出现 ∧ 活 ∧ 在轮询本队列（轮询式采样） ----------------
    t1 = time.time()
    new_pid, polling = None, False
    while time.time() - t1 < wait_s:
        st = read_pidfile(pf)
        pid = st.get("pid") if st["state"] == "live" else None
        sample = _poll_sample(host, ns, queues)
        polling = bool(pid and any(x["pid"] == pid for x in sample["live"]))
        out["samples"].append({"t": round(time.time() - t1, 1), "phase": "respawn",
                               "new_pid": pid, "poller_face_available": sample["available"],
                               "live_pollers": [x["identity"] for x in sample["live"]]})
        if pid and sample["available"] and polling:
            new_pid = pid
            break
        if pid and not sample["available"]:
            # 面不可得时无法证明「在轮询」——不冒充，等满后按 poller-face 段报
            pass
        new_pid = pid or new_pid
        time.sleep(POLL_SAMPLE_S)
    out["waited_s"] = round(time.time() - t1, 1)
    out["new_pid"] = new_pid
    out["after"] = read_pidfile(pf)
    final = _poll_sample(host, ns, queues)
    out["phases"].append({"phase": "respawn", "new_pid": new_pid,
                          "polling": polling,
                          "poller_face_available": final["available"],
                          "waited_s": out["waited_s"]})
    if not new_pid:
        out["error"] = ("supervisor 未在 %.0fs 内拉起（pidfile=%s 里始终没出现新的活 pid；"
                        "旧 pid=%s 已排空）。查控制台（3099 会话）里 temporal-tools supervisor "
                        "是否在跑（其 keepalive 缺省 5s；它才是唯一的自动拉起面）。"
                        "**本工具不自己起 worker**——从 agent 会话起会继承沙箱，工作区外写 "
                        "fail-closed（票归档 EPERM，t260930-09 实案）"
                        % (wait_s, pf, old_pid))
        out["phase_failed"] = "respawn"
        return out
    if not final["available"]:
        q0 = next((q for q in (final.get("queues") or []) if not q.get("available")), {})
        out["error"] = ("换手已发生（新 pid=%r，旧 pid=%s 已排空）但 **poller 面不可得**："
                        "不能证明「恰好一颗在轮询本队列」⇒ 不报成功（不冒充）。原因：%s"
                        % (new_pid, old_pid, str((q0 or {}).get("note") or final.get("note"))[:160]))
        out["phase_failed"] = "poller-face"
        return out
    if not (new_pid and polling):
        out["error"] = ("supervisor 未在 %.0fs 内拉起（新 pid 出现但未在轮询本队列，或新 pid "
                        "始终没出现）：pidfile=%s 里是 %r（旧 pid=%s 已排空）。"
                        "查控制台（3099 会话）里 temporal-tools supervisor 是否在跑"
                        "（其 keepalive 缺省 5s；它才是唯一的自动拉起面）。"
                        "**本工具不自己起 worker**——从 agent 会话起会继承沙箱，"
                        "工作区外写 fail-closed（票归档 EPERM，t260930-09 实案）"
                        % (wait_s, pf, out["after"].get("pid"), old_pid))
        out["phase_failed"] = "respawn"
        return out

    # ---------------- ④ 此刻才断言「活 poller 恰 1 且就是新 pid」 ----------------
    proof = _proof_single_poller(host, ns, queues, expect_pid=new_pid)
    out["pollers_proof"] = proof
    if not proof["ok"]:
        q0 = proof["queues"][0] if proof["queues"] else {}
        out["error"] = ("换手后 poller 数不为 1 或不是新进程（本队列活 poller=%r，新 pid=%s，"
                        "旧 pid=%s 已排空）：真失败，逐个点名"
                        % ([x["identity"] for x in (q0.get("live") or [])
                            + (q0.get("stale_history") or [])], new_pid, old_pid))
        out["phase_failed"] = "poller-count"
        return out
    out["phases"].append({"phase": "verified", "live_poller": new_pid})
    return out


def cmd_restart(args) -> dict:
    """**kill-only 换手**：TERM 现有 worker，等 supervisor 自动拉起并自证恰好一颗活 poller。

    绝不自己起 worker（宿主 260930 纠正；理由见 `_kill_and_wait_for_respawn` 文档串与
    docs/ops/engine-worker-and-lane-operations.md 的实况案例）。`--replace` 现在只是
    「TERM 后等拉起」这件事的显式别名（旧语义「先停旧再起新的」已删除）。"""
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    scope = str(args.scope or "")
    wait_s = float(getattr(args, "wait", 60) or 60)
    old_drain_s = float(getattr(args, "old_drain", OLD_DRAIN_WAIT_S) or OLD_DRAIN_WAIT_S)
    if scope == "central":
        pf, queues = DATA / "worker.pid", shared.configured_task_queues()
    elif scope.startswith("lane:"):
        tid = scope.split(":", 1)[1].strip()
        if not tid:
            return {"ok": False, "exit": ENV_EXIT,
                    "error": "restart --scope lane:<ticket> 缺票号"}
        pf, queues = tw._pidfile(tid), _queues_of(tid)
    else:
        return {"ok": False, "exit": ENV_EXIT,
                "error": "restart --scope 只接受 central 或 lane:<ticket>（实得 %r）" % scope}
    res = _kill_and_wait_for_respawn(host, ns, pf, queues, wait_s, old_drain_s)
    res["scope"] = scope
    res["hint"] = ("换手后请用 `who <ticket>` 确认后续闸轮落**新 pid**；"
                   "启动 worker 的唯一自动面=控制台 temporal-tools supervisor"
                   "（本工具只 kill、不自己起：agent 会话起的 worker 会继承沙箱，"
                   "工作区外写 fail-closed ⇒ 票归档 EPERM，t260930-09 实案）")
    if res.get("error"):
        return {"ok": False, "exit": ALERT_EXIT, "error": res["error"], "result": res}
    return _ok(res)


# ---------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    # 全局开关同时挂顶层与各子命令（放前放后都认）。**default=SUPPRESS 是关键**：
    # 若子命令里也写 default=""，argparse 会在解析子命令时把顶层已给的值覆盖成 ""——
    # 实测「--repo 放在子命令前被静默丢掉」，工具于是读错仓（假面）。SUPPRESS=缺席即不设，
    # 顶层给的值得以保留。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=argparse.SUPPRESS,
                        help="Temporal 地址（缺省=引擎 TARGET_HOST）")
    common.add_argument("--ns", default=argparse.SUPPRESS,
                        help="namespace（缺省=引擎 NAMESPACE）")
    common.add_argument("--repo", default=argparse.SUPPRESS,
                        help="仓根（缺省=本工具所在仓；多项目/夹具测试用）")
    p = argparse.ArgumentParser(
        description="引擎运作面工具：谁在服务这张票 / 它吃哪份代码 / 漂没漂",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
        epilog="退出码：0=正常、1=告警（漂移/poller≠1）、2=环境面不可得；"
               "全局开关 --host/--ns/--repo 放子命令前后都认")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("workers", parents=[common], help="中央 + 各票泳道 worker 面")
    w = sub.add_parser("who", parents=[common], help="这张票最近一轮是谁服务的")
    w.add_argument("ticket")
    w.add_argument("--round", type=int, default=0, help="第几轮闸（1-based；缺省=最近一轮）")
    d = sub.add_parser("drift", parents=[common], help="推票前判据（漂移/指纹/poller 数）")
    d.add_argument("ticket")
    s2 = sub.add_parser("sync", parents=[common], help="把 main 并进泳道一次（幂等）")
    s2.add_argument("ticket")
    s2.add_argument("--dry-run", action="store_true")
    s2.add_argument("--abort", action="store_true", help="复位半合并态（走既有 settle 单点）")
    r = sub.add_parser("restart", parents=[common],
                       help="换手 worker（**只 kill**，等 supervisor 自动拉起并自证）")
    r.add_argument("--scope", required=True, help="central | lane:<ticket>")
    r.add_argument("--replace", action="store_true",
                   help="（别名）TERM 现有 worker 后等 supervisor 自动拉起——这已是缺省语义；"
                        "旧语义「先停旧再起新的」已删除：工具**绝不自己起 worker**"
                        "（沙箱继承会让工作区外写 fail-closed：票归档 EPERM）")
    r.add_argument("--wait", type=float, default=60.0,
                   help="等自动拉起的上界秒数（缺省 60；超时=具名告警 + exit 1，点名哪一段）")
    r.add_argument("--old-drain", type=float, default=OLD_DRAIN_WAIT_S,
                   help="等**旧 worker 排空**（优雅停等在飞活动）的上界秒数（缺省 90）。"
                        "排空期间 supervisor 已起新 pid 属合法中间态，不判失败")
    return p


def main() -> int:
    args = build_parser().parse_args()
    args.host = getattr(args, "host", "") or ""
    args.ns = getattr(args, "ns", "") or ""
    args.repo = getattr(args, "repo", "") or ""
    if args.repo:
        # `--repo`：换仓根（多项目运维 / 夹具测试）。DATA 跟着换 ⇒ pidfile 面也落在目标仓，
        # 绝不误读本仓的 worker 台账。
        global REPO, ENGINE, DATA
        REPO = pathlib.Path(args.repo).resolve()
        ENGINE = REPO / "server" / "engine"
        DATA = ENGINE / "data"
        # 泳道 worker 的再起面（ticket_worker）也按**目标仓**重定向——否则它会去起本仓的
        # worker（离线夹具实测踩到：真仓 data/ 下多了一颗 worker-t-*.pid 与活进程）。
        tw.set_root(ENGINE)
    table = {"workers": cmd_workers, "who": cmd_who, "drift": cmd_drift,
             "sync": cmd_sync, "restart": cmd_restart}
    try:
        return _print(table[args.cmd](args))
    except Exception as e:  # noqa: BLE001——工具绝不裸崩：结构化报错
        import traceback
        traceback.print_exc(file=sys.stderr)
        return _print(_err("工具内部异常 %s: %s" % (type(e).__name__, str(e)[:300]),
                           exit=ENV_EXIT))


if __name__ == "__main__":
    sys.exit(main())
