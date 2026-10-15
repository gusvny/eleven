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
                              换手后**自证恰好一个活 poller**；
                              t261009-48：换手前先出 pre-flight 面（STARTED workflow task /
                              在飞活动 / stale 指纹 / 历史大小），在飞即具名拒绝（缺省），
                              决策落 data/worker-handovers.jsonl（--force 是显式逃生口）

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

_ACTIVITY_NAMES = ("prepare_conflict_resolution", "settle_conflict_resolution",
                   "line_round_tick_engine")
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
                import activities as _acts
                from shared import ConflictPrepArgs, ConflictSettleArgs
            # name -> (activity fn, args class). None = zero-argument by
            # contract (the engine tick reads its own context).
            registry = {"prepare_conflict_resolution": (_aa.prepare_conflict_resolution,
                                                        ConflictPrepArgs),
                        "settle_conflict_resolution": (_aa.settle_conflict_resolution,
                                                       ConflictSettleArgs),
                        # 261015: the SAME activity the scheduled dispatcher tick
                        # calls, so a manual trigger has exactly the scheduled
                        # effect (run record + relative verdict + certification).
                        # Hand-running integration/line_round_runner.py cannot do
                        # that: the judgement and the record are the engine's.
                        "line_round_tick_engine": (_acts.line_round_tick_engine, None)}
            name = str(req.get("name") or "")
            fn, args_cls = registry[name]
            arg = None if args_cls is None else args_cls(**dict(req.get("payload") or {}))
            to_s = int(req.get("timeout_s") or 300)
            res = await _wf.execute_activity(
                fn, arg,
                start_to_close_timeout=datetime.timedelta(seconds=to_s),
                retry_policy=_wf.RetryPolicy(maximum_attempts=1)
                if hasattr(_wf, "RetryPolicy") else None)
            if dataclasses.is_dataclass(res):
                return dataclasses.asdict(res)
            return res if isinstance(res, dict) else {"result": str(res)}


def cmd_round(args) -> dict:
    """立刻手动跑一轮线轮（261015 宿主令：手动与定时必须**同效果**）。

    走的是定时巡检用的**同一个活动** `activities.line_round_tick_engine`，所以效果
    完全一致：跑套件 → 相对裁决 → 落运行记录 + 认证行。**手跑 runner 做不到这一点**
    （那只产逐场景证据，判断与落账都在引擎侧）。并发由引擎既有的集成跑单飞锁约束：
    轮在飞时再触发会被那把锁挡住，两种触发不并行。"""
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    to_s = int(getattr(args, "timeout", 0) or 3600)
    return _run_activity(host, ns, "line_round_tick_engine", {},
                         timeout_s=to_s)


def _activity_registry():
    """临时 worker 要注册的 activity 对象（引擎既有单点本体）。"""
    with _wf.unsafe.imports_passed_through():
        import agent_activities as _aa
        import activities as _acts
    out = {}
    for n in _ACTIVITY_NAMES:
        # the conflict-resolution pair lives in agent_activities; the line-round
        # tick lives in activities (261015) - resolve either, refuse loudly if a
        # whitelisted name has no implementation.
        obj = getattr(_aa, n, None) or getattr(_acts, n, None)
        if obj is None:
            raise AttributeError("whitelisted activity has no implementation: %s" % n)
        out[n] = obj
    return out


# ---------------------------------------------------------------- 基础面
def _ok(result: dict) -> dict:
    return {"ok": True, "result": result}


def _err(msg: str, **extra) -> dict:
    out = {"ok": False, "error": msg}
    out.update(extra)
    return out


def _print(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8", "backslashreplace").decode("utf-8"))
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
                                            {"name": activity_name, "payload": payload,
                                             "timeout_s": int(timeout_s)},
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


# ---------------------------------------------------------------- restart pre-flight (t261009-48: look before you kill)
# Field provenance (named, not fabricated):
#   ticket          = the --scope lane:<ticket> argument itself (never parsed out of payloads)
#   stage/stage_state = the workflow's `snapshot` query (the same face the ticket reads);
#                       when the query fails the refusal says `stage=unavailable` with the reason
#   gen             = snapshot["gens"][stage]; absent there = `gen=unavailable` (named)
#   attempt/elapsed = DescribeWorkflowExecutionResponse (pending activity: attempt + last_started_time)
#   worker stale    = the existing stamp_for face (unchanged)
HANDOVER_RECORD_NAME = "worker-handovers.jsonl"
INFLIGHT_POLICY_DEFAULT_WAIT_S = 300.0
#: history-event count from which the tool names the continue-as-new hint (report only).
LONG_HISTORY_EVENT_COUNT = 5000


def _ts_epoch(t) -> float:
    """Best-effort epoch seconds from a proto Timestamp / float / None; 0.0 = unknown."""
    try:
        if t is None:
            return 0.0
        if hasattr(t, "ToDatetime"):
            return t.ToDatetime().timestamp()
        return float(t)
    except Exception:  # noqa: BLE001 — a malformed timestamp degrades to "unknown", never a fake value
        return 0.0


def _pending_activity_rows(pending, now=None) -> list:
    """DescribeWorkflowExecutionResponse.pending_activities → plain rows."""
    now = time.time() if now is None else now
    rows = []
    for p in pending or []:
        started = _ts_epoch(getattr(p, "last_started_time", None))
        rows.append({
            "activity_type": str(getattr(getattr(p, "activity_type", None), "name", "") or ""),
            "state": str(getattr(getattr(p, "state", None), "name", "") or "").lower(),
            "attempt": int(getattr(p, "attempt", 0) or 0),
            "last_worker_identity": str(getattr(p, "last_worker_identity", "") or ""),
            "last_started_at": (datetime.datetime.fromtimestamp(started).isoformat(timespec="seconds")
                                 if started else ""),
            "running_s": int(max(0.0, now - started)) if started else None,
        })
    return rows


def _workflow_task_face(raw, now=None) -> dict:
    """The pending workflow task face — the 499 s orphan condition (KI-01M4GF5R8NHQNATH7WD7SKF94X).

    proto3 message field: an unset field returns a default instance, so use HasField
    (same discipline as `_has_field` in the `who` parser above)."""
    now = time.time() if now is None else now
    try:
        present = bool(raw.HasField("pending_workflow_task"))
    except Exception:  # noqa: BLE001 — fake/malformed objects without the field
        present = getattr(raw, "pending_workflow_task", None) is not None
    if not present:
        return {"present": False, "state": "", "attempt": 0, "started_at": "", "running_s": None}
    p = getattr(raw, "pending_workflow_task")
    started = _ts_epoch(getattr(p, "started_time", None))
    return {"present": True,
            "state": str(getattr(getattr(p, "state", None), "name", "") or "").lower(),
            "attempt": int(getattr(p, "attempt", 0) or 0),
            "started_at": (datetime.datetime.fromtimestamp(started).isoformat(timespec="seconds")
                           if started else ""),
            "running_s": int(max(0.0, now - started)) if started else None}


def _stage_face(host: str, ns: str, tid: str) -> dict:
    """The ticket's stage/gen face from the workflow's own `snapshot` query.

    Provenance per plan review: stage/stage_state come from the snapshot top level, gen
    from snapshot["gens"][stage]. Unobtainable = named unavailable, never fabricated."""
    try:
        from temporalio.client import Client

        async def _go():
            c = await Client.connect(host, namespace=ns)
            h = c.get_workflow_handle(tid)
            return await h.query("snapshot")

        snap = asyncio.run(_go()) or {}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "stage": None, "stage_state": None, "gen": None,
                "note": "unavailable: snapshot query failed (%s: %s)"
                        % (type(e).__name__, str(e)[:120])}
    if not isinstance(snap, dict):
        return {"available": False, "stage": None, "stage_state": None, "gen": None,
                "note": "unavailable: snapshot query returned %s" % type(snap).__name__}
    stage = str(snap.get("stage") or "")
    gens = snap.get("gens") if isinstance(snap.get("gens"), dict) else {}
    gen = gens.get(stage) if stage else None
    return {"available": True,
            "stage": stage or None, "stage_state": snap.get("stage_state") or None,
            "gen": (int(gen) if isinstance(gen, (int, float)) else None),
            "note": "" if (stage and gen is not None) else
                    ("named unavailable: snapshot has no gen for stage %r" % stage if stage
                     else "named unavailable: snapshot has no stage")}


def _worker_face(pf) -> dict:
    """Target worker's pidfile + stale-stamp face (the existing faces, reused)."""
    st = read_pidfile(pf) if pf is not None and pathlib.Path(pf).exists() else \
        {"state": "no-pidfile", "pid": None, "started_at": "", "detail": "pidfile not found"}
    pid = st.get("pid")
    tree = tree_of_pid(pid) if st.get("state") == "live" else \
        {"tree": "", "available": False, "note": "unavailable: process not running"}
    return {"pid": pid, "state": st.get("state"), "started_at": st.get("started_at", ""),
            "tree": repo_root_from_tree(tree.get("tree", "")),
            "stamp": stamp_for(pid, repo_root_from_tree(tree.get("tree", "")),
                               st.get("started_at", ""))}


def _ticket_preflight(host: str, ns: str, tid: str, pf=None, now=None) -> dict:
    """One describe + one snapshot query → the operator's pre-flight face.

    Unavailable (Temporal down, ticket absent, temporalio missing) is a **named face**
    (`available: False` + note), not an exception — the report must print even then."""
    now = time.time() if now is None else now
    face = {"ticket": tid, "available": False, "workflow_status": "",
            "pending_workflow_task": {"present": False, "state": "", "attempt": 0,
                                      "started_at": "", "running_s": None},
            "pending_activities": [], "stage_face": None,
            "history": {"event_count": None, "size_bytes": None}, "note": ""}
    try:
        from temporalio.client import Client

        async def _go():
            c = await Client.connect(host, namespace=ns)
            h = c.get_workflow_handle(tid)
            return await h.describe()

        desc = asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        face["note"] = ("unavailable: describe failed (%s: %s) — the in-flight face cannot be "
                        "read for this scope" % (type(e).__name__, str(e)[:160]))
        face["stage_face"] = _stage_face(host, ns, tid)
        face["worker"] = _worker_face(pf)
        return face
    raw = getattr(desc, "raw_description", None) or desc
    face["available"] = True
    try:
        info = getattr(raw, "workflow_execution_info", None)
        face["workflow_status"] = str(getattr(getattr(info, "status", None), "name", "") or "")
    except Exception:  # noqa: BLE001 — malformed status degrades to empty string
        pass
    face["pending_workflow_task"] = _workflow_task_face(raw, now=now)
    face["pending_activities"] = _pending_activity_rows(
        getattr(raw, "pending_activities", None), now=now)
    face["history"] = {"event_count": int(getattr(raw, "history_length", 0) or 0) or None,
                       "size_bytes": int(getattr(raw, "history_size_bytes", 0) or 0) or None}
    face["stage_face"] = _stage_face(host, ns, tid)
    face["worker"] = _worker_face(pf)
    return face


def handover_blockers(preflight: dict) -> list:
    """Pre-flight face → the list of things a TERM would destroy (pure, testable)."""
    blockers = []
    wt = preflight.get("pending_workflow_task") or {}
    if wt.get("present"):
        blockers.append({
            "kind": "started_workflow_task", "state": wt.get("state") or "unknown",
            "attempt": wt.get("attempt"), "running_s": wt.get("running_s"),
            "risk": ("TERM orphans this workflow task; nothing resumes it until its "
                     "start-to-close timeout expires (499 s observed, KI-01M4GF5R8NHQNATH7WD7SKF94X)")})
    for r in preflight.get("pending_activities") or []:
        blockers.append({
            "kind": "in_flight_activity", "activity": r.get("activity_type") or "unknown",
            "attempt": r.get("attempt"), "running_s": r.get("running_s"),
            "last_worker_identity": r.get("last_worker_identity") or "",
            "risk": ("TERM lets it drain for the grace period (SANDBAR_WORKER_GRACEFUL_SHUTDOWN_SEC, "
                     "default 1800); if it cannot finish, the round is cancelled and the ticket "
                     "records the worker termination (KI-01M4H1DN2Z10J973DD6PBMPB4W)")})
    return blockers


def refusal_message(tid: str, blockers: list, stage_face: dict) -> str:
    """A refusal names ticket, stage, generation, and elapsed time — spec item 2."""
    stage = (stage_face or {}).get("stage")
    gen = (stage_face or {}).get("gen")
    stage_s = ("stage=%s" % stage if stage else
               "stage=unavailable(%s)" % ((stage_face or {}).get("note") or "unknown"))
    gen_s = "gen=%s" % gen if gen is not None else "gen=unavailable"
    parts = []
    for b in blockers:
        if b.get("kind") == "started_workflow_task":
            parts.append("STARTED workflow task (state=%s attempt=%s running=%ss)"
                         % (b.get("state"), b.get("attempt"), b.get("running_s")))
        else:
            parts.append("in-flight agent activity %s (attempt=%s running=%ss)"
                         % (b.get("activity"), b.get("attempt"), b.get("running_s")))
    return ("refusing handover of %s: %s — %s, %s. Those in-flight items would be destroyed "
            "by a TERM. Re-run with --force to proceed anyway (recorded as forced), or "
            "--inflight-policy wait --inflight-wait <sec> to wait for a round boundary"
            % (tid, "; ".join(parts), stage_s, gen_s))


def decide_handover(blockers: list, force: bool, policy: str) -> str:
    """Pure disposition decision: clear | forced | wait | refused.

    Precedence (plan review item 2): --force wins over --inflight-policy wait; a nonsense
    policy value is rejected by the CLI layer before this runs."""
    if not blockers:
        return "clear"
    if force:
        return "forced"
    if policy == "wait":
        return "wait"
    return "refused"


def wait_for_round_boundary(fetch, wait_s: float, poll_s: float = 5.0, sleep=time.sleep) -> dict:
    """Bounded poll of the pre-flight face until the workflow reaches a round boundary.

    `fetch` is injectable (tests pass a stub; production passes a _ticket_preflight
    closure). Returns {"cleared": bool, "waited_s": ..., "last_blockers": [...]}."""
    t0 = time.time()
    blockers: list = []
    while True:
        blockers = handover_blockers(fetch())
        if not blockers:
            return {"cleared": True, "waited_s": round(time.time() - t0, 1), "last_blockers": []}
        if time.time() - t0 >= wait_s:
            return {"cleared": False, "waited_s": round(time.time() - t0, 1),
                    "last_blockers": blockers}
        sleep(poll_s)


def handover_record_path() -> pathlib.Path:
    """Absolute record path (plan review item 4a: always echoed absolute)."""
    return (DATA / HANDOVER_RECORD_NAME).resolve()


def append_handover_record(record: dict) -> dict:
    """Append one JSON line, single O_APPEND write (review item 4b: no interleaved half-lines).

    Tolerates pre-existing garbage in the file (append-only; never rewrites). A write
    failure is named and returned, never raised into the handover itself."""
    path = handover_record_path()
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8", "backslashreplace"))
        finally:
            os.close(fd)
        return {"path": str(path), "written": True, "note": ""}
    except OSError as e:
        return {"path": str(path), "written": False,
                "note": "record write failed (%s: %s) — the handover itself is unaffected"
                        % (type(e).__name__, e)}


def build_handover_record(*, scope: str, tid: str, reason: str, policy: str,
                          preflight: dict, blockers: list, disposition: str,
                          outcome: str, error: str = "") -> dict:
    """The decision record (spec item 3): who asked, why, what was in flight, disposition.

    aborted_a_round is true only when a handover actually went ahead (disposition=forced)
    on top of an in-flight item — a wait-timeout ends in refusal, so no kill, no abort
    (plan review item 3)."""
    stage_face = preflight.get("stage_face") or {}
    return {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "ticket": tid or None,
        "requested_by": _requested_by(),
        "reason": reason,
        "inflight_policy": policy,
        "inflight_at_decision": {"blockers": blockers, "stage": stage_face.get("stage"),
                                 "stage_state": stage_face.get("stage_state"),
                                 "gen": stage_face.get("gen"),
                                 "history": preflight.get("history")},
        "disposition": disposition,
        "aborted_a_round": bool(disposition == "forced" and blockers),
        "outcome": outcome,
        "error": error,
    }


def _requested_by() -> str:
    import getpass
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 — no passwd entry / odd environment
        user = "unknown"
    return ("%s via engine_ops.py %s" % (user, " ".join(sys.argv[1:])))[:400]


def _continue_as_new_hint(preflight: dict) -> str:
    """Report-only hint (spec item 5): never an automatic action."""
    hist = preflight.get("history") or {}
    n = hist.get("event_count")
    if not n or n < LONG_HISTORY_EVENT_COUNT:
        return ""
    return ("long history: %s events (%s bytes) — a handover plus a replay of this history "
            "is the expensive case; continue-as-new is the lever, and this tool only "
            "reports it (it never rewrites a workflow)"
            % (n, hist.get("size_bytes")))


#: indirection point for tests (monkeypatched to stub the Temporal faces)
_PREFLIGHT_FETCH = _ticket_preflight


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

    t261009-48: before any signal is sent, the pre-flight face is built and printed —
    whether a STARTED workflow task or an agent activity is in flight (ticket/stage/gen/
    attempt/elapsed), the worker's stale stamp, and the history size. When the pre-flight
    shows work a TERM would destroy, the handover is refused by name by default; the
    operator chooses `--inflight-policy wait --inflight-wait <sec>` (bounded round-boundary
    wait) or `--force` (explicit escape hatch, recorded as forced). Every decision appends
    one line to `data/worker-handovers.jsonl` (who/why/in-flight/disposition/aborted-round).

    绝不自己起 worker（宿主 260930 纠正；理由见 `_kill_and_wait_for_respawn` 文档串与
    docs/ops/engine-worker-and-lane-operations.md 的实况案例）。`--replace` 现在只是
    「TERM 后等拉起」这件事的显式别名（旧语义「先停旧再起新的」已删除）。"""
    host = args.host or shared.TARGET_HOST
    ns = args.ns or shared.NAMESPACE
    scope = str(args.scope or "")
    wait_s = float(getattr(args, "wait", 60) or 60)
    old_drain_s = float(getattr(args, "old_drain", OLD_DRAIN_WAIT_S) or OLD_DRAIN_WAIT_S)
    policy = str(getattr(args, "inflight_policy", "") or "refuse")
    if policy not in ("refuse", "wait"):
        return {"ok": False, "exit": ENV_EXIT,
                "error": "restart --inflight-policy only accepts refuse | wait (got %r)"
                         % policy}
    force = bool(getattr(args, "force", False))
    reason = str(getattr(args, "reason", "") or "")
    wait_inflight_s = float(getattr(args, "inflight_wait", INFLIGHT_POLICY_DEFAULT_WAIT_S)
                            or INFLIGHT_POLICY_DEFAULT_WAIT_S)
    if scope == "central":
        pf, queues = DATA / "worker.pid", shared.configured_task_queues()
        tid = ""
    elif scope.startswith("lane:"):
        tid = scope.split(":", 1)[1].strip()
        if not tid:
            return {"ok": False, "exit": ENV_EXIT,
                    "error": "restart --scope lane:<ticket> 缺票号"}
        pf, queues = tw._pidfile(tid), _queues_of(tid)
    else:
        return {"ok": False, "exit": ENV_EXIT,
                "error": "restart --scope 只接受 central 或 lane:<ticket>（实得 %r）" % scope}

    # ---------------- pre-flight: look before you kill (spec item 1) ----------------
    if tid:
        preflight = _PREFLIGHT_FETCH(host, ns, tid, pf=pf)
    else:
        # central scope serves many tickets; no single workflow face exists. The worker
        # stamp/poller faces still print; the in-flight face is named unavailable, and
        # the limitation is carried into the handover record (never silently passed off
        # as "clear").
        preflight = {"ticket": None, "available": False, "workflow_status": "",
                     "pending_workflow_task": {"present": False, "state": "", "attempt": 0,
                                               "started_at": "", "running_s": None},
                     "pending_activities": [],
                     "stage_face": {"available": False, "stage": None, "stage_state": None,
                                    "gen": None,
                                    "note": "unavailable: central scope has no single "
                                            "ticket workflow"},
                     "history": {"event_count": None, "size_bytes": None},
                     "worker": _worker_face(pf),
                     "note": "central scope: in-flight face unavailable (one worker serves "
                             "many tickets); the pre-flight covers the stale stamp only"}
    blockers = handover_blockers(preflight)
    decision = decide_handover(blockers, force, policy)

    # ---------------- wait for a round boundary (named bounded wait) ----------------
    wait_note = ""
    if decision == "wait":
        fetch = lambda: _PREFLIGHT_FETCH(host, ns, tid, pf=pf)  # noqa: E731
        res_w = wait_for_round_boundary(fetch, wait_inflight_s)
        if res_w["cleared"]:
            decision, blockers = "waited", []
            wait_note = "waited %.0fs for a round boundary, then proceeded" % res_w["waited_s"]
        else:
            decision = "refused"
            wait_note = ("still in flight after %.0fs of waiting (round boundary never "
                         "reached)" % res_w["waited_s"])
            blockers = res_w["last_blockers"] or blockers

    # ---------------- refusal path: report printed, record written, nothing signalled ---
    if decision == "refused":
        record = build_handover_record(scope=scope, tid=tid, reason=reason, policy=policy,
                                       preflight=preflight, blockers=blockers,
                                       disposition="refused", outcome="refused",
                                       error=wait_note or
                                             (blockers[0].get("risk") if blockers else ""))
        rec_face = append_handover_record(record)
        msg = refusal_message(tid, blockers, preflight.get("stage_face"))
        if wait_note:
            msg = "%s — %s" % (msg, wait_note)
        return {"ok": False, "exit": ALERT_EXIT, "error": msg,
                "result": {"scope": scope, "disposition": "refused", "forced": False,
                           "preflight": preflight, "blockers": blockers,
                           "record": rec_face, "record_path": str(rec_face["path"]),
                           "aborted_a_round": False}}

    # ---------------- proceeding dispositions: clear / forced / waited ----------------
    res = _kill_and_wait_for_respawn(host, ns, pf, queues, wait_s, old_drain_s)
    res["scope"] = scope
    res["preflight"] = preflight
    res["blockers"] = blockers
    res["disposition"] = decision
    res["forced"] = decision == "forced"
    res["aborted_a_round"] = bool(decision == "forced" and blockers)
    res["wait_note"] = wait_note
    outcome = "handover_ok" if not res.get("error") else "handover_failed"
    record = build_handover_record(scope=scope, tid=tid, reason=reason, policy=policy,
                                   preflight=preflight, blockers=blockers,
                                   disposition=decision, outcome=outcome,
                                   error=str(res.get("error") or ""))
    rec_face = append_handover_record(record)
    res["record"] = rec_face
    res["record_path"] = str(rec_face["path"])
    hint_extra = _continue_as_new_hint(preflight)
    res["hint"] = ("换手后请用 `who <ticket>` 确认后续闸轮落**新 pid**；"
                   "启动 worker 的唯一自动面=控制台 temporal-tools supervisor"
                   "（本工具只 kill、不自己起：agent 会话起的 worker 会继承沙箱，"
                   "工作区外写 fail-closed ⇒ 票归档 EPERM，t260930-09 实案）")
    if decision == "forced":
        res["hint"] += ("；--force 在案：换手记录已具名 forced 与在飞项"
                        + ("（aborted_a_round=true）" if res["aborted_a_round"] else ""))
    if hint_extra:
        res["hint"] += "；" + hint_extra
    if preflight.get("note"):
        res["preflight_note"] = preflight["note"]
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
    rd = sub.add_parser("round", parents=[common],
                        help="立刻手动跑一轮线轮（与定时同一活动，效果一致；受集成跑单飞锁）")
    rd.add_argument("--timeout", type=int, default=3600,
                    help="活动预算秒（一轮实测 30–40 分钟，缺省 3600）")
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
    r.add_argument("--inflight-policy", choices=["refuse", "wait"], default="refuse",
                   help="t261009-48: what to do when the pre-flight shows a STARTED workflow "
                        "task or an in-flight agent activity. refuse (default, safe) = do not "
                        "signal, name what is in flight; wait = bounded wait for a round "
                        "boundary, then proceed. --force overrides either (documented "
                        "precedence: --force wins)")
    r.add_argument("--inflight-wait", type=float, default=INFLIGHT_POLICY_DEFAULT_WAIT_S,
                   help="bounded seconds for --inflight-policy wait (default 300); timeout "
                        "ends in a named refusal, never a kill")
    r.add_argument("--force", action="store_true",
                   help="explicit escape hatch: proceed even with work in flight; recorded "
                        "as disposition=forced in the handover record (and as "
                        "aborted_a_round=true when an item was in flight at the TERM)")
    r.add_argument("--reason", default="",
                   help="why this handover is asked for (recorded verbatim in the handover "
                        "record)")
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
             "sync": cmd_sync, "restart": cmd_restart, "round": cmd_round}
    try:
        return _print(table[args.cmd](args))
    except Exception as e:  # noqa: BLE001——工具绝不裸崩：结构化报错
        import traceback
        traceback.print_exc(file=sys.stderr)
        return _print(_err("工具内部异常 %s: %s" % (type(e).__name__, str(e)[:300]),
                           exit=ENV_EXIT))


if __name__ == "__main__":
    sys.exit(main())
