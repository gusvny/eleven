# -*- coding: utf-8 -*-
"""t260915-01 详情数据面集成场景共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

借用既有台架库（前置/基础步骤共享复用纪律，不另起炉灶）：
- integration/t260904-02/lib_gate.py：Fail 行式断言、隔离台 require_stage/require_bench/
  stage_down、引擎 client 子进程 run_poc_client/parse_out_json、poc_python（venv 解释器）。
- integration/t260908-01/lib_ki061.py：夹具仓 make_fixture_repo、舞台 env stage_env、
  专属 worker spawn_worker、信号直发 send_signal、snapshot 查询 query_snapshot、轮询 poll、
  wait_worker_alive（桩脑全链先例=t260908-01 pause/ki061 族）。

铁律（沿 t260908-01 台架纪律）：
- 一切 git 写入只发生在 tempfile 临时仓/一次性隔离台；场景对仓库工作区零写入；
- 被测子进程 Temporal 地址只指一次性隔离台（stage_env 钉 TARGET_HOST/NAMESPACE）；
- spawn 的 worker 收尾 TERM→KILL 兜底；文案锚语义词不锚字面（KI-051）；
- 断言锚 snapshot / CLI 回执 / timeline / meta 公开契约，不锚引擎内部结构；
- 探针路径的「必被拒」用真判定器（path_gates.judge_stage_paths）现场选，不复制规则表。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
POC = os.path.join(REPO, "server", "engine")
TICKET_TOOLS = os.path.join(REPO, "server", "tools", "ticket.py")
for _p in (REPO, os.path.join(REPO, "integration"),
           os.path.join(REPO, "integration", "t260904-02"),
           os.path.join(REPO, "integration", "t260908-01"),
           POC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib_gate import (  # noqa: E402
    Fail, require_bench, require_stage, stage_down, poc_python,
    run_poc_client, parse_out_json,
)
from lib_ki061 import (  # noqa: E402
    make_fixture_repo, stage_env, spawn_worker, send_signal,
    query_snapshot, poll, wait_worker_alive,
)

PROBE_STEM = "zz_t26091501_probe"

# 桩大脑（改自 lib_ki061.ARB_STUB）：分叉两 Edge 各睡数秒，把并行窗口拉宽到
# 轮询可采样（stub 其余段秒级完成，2s 轮询可能错过 parallel_stages 非空窗）。
DETAIL_STUB = r"""
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"阶段：([a-z_]+)（", prompt)
stage = m.group(1) if m else "unknown"
with open(os.environ["KI061_STUB_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"stage": stage, "ts": time.time()},
                       ensure_ascii=False) + "\n")
if stage in ("implement", "design_integration_tests",
             "arbitrate", "acceptance_walkthrough"):
    time.sleep(6)  # 拉宽两个并行分叉窗（impl∥design、arb∥acc），供轮询采样相位键
m = re.search(r"干完把结果写到 (\S+?\.json)", prompt)
if m:
    rfile = m.group(1)
    body = {"status": "ok", "summary": "[t26091501-stub] %s 完成" % stage,
            "report": "[t26091501-stub] 桩回执", "deliverables": [],
            "files_changed": [], "files_changed_shape": "ok",
            "evidence": "t26091501-stub"}
    with open(rfile, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
"""


def judge_violation_probe(stage_id, write_set, ticket_id="t260915-01"):
    """用真判定器选一条「必被拒」的探针相对路径（oracle=被测闸本身）。

    返回 (rel_path, reason_code, violations)；找不到可判违规的候选 → (None, None, None)。
    """
    import path_gates  # noqa: E402  (POC 已入 sys.path)
    candidates = ["%s_%d.py" % (PROBE_STEM, i) for i in range(6)]
    for rel in candidates:
        allowed, violations, reason = path_gates.judge_stage_paths(
            stage_id, [rel], write_set=list(write_set or []), ticket_id=ticket_id)
        if not allowed and violations:
            return rel, reason, list(violations)
    return None, None, None


def judge_violation_set(stage_id, write_set, rels, ticket_id="t260915-01"):
    """对一组探针路径跑真判定器，返回 (violations, reason_code)。"""
    import path_gates  # noqa: E402
    allowed, violations, reason = path_gates.judge_stage_paths(
        stage_id, list(rels), write_set=list(write_set or []), ticket_id=ticket_id)
    return (list(violations), reason) if not allowed else ([], "")


def write_probe(ws_root, rel):
    """把探针文件写进泳道工作区（场景自清理由调用方负责 unlink）。"""
    p = os.path.join(ws_root, rel)
    os.makedirs(os.path.dirname(p) or ws_root, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("# t260915-01 路径闸探针（集成场景写入，可删）\n")
    return p


def delete_tracked(ws_root, rel):
    """Delete a TRACKED lane file: the violation shape the settle still refuses.

    The engine's settle auto-remediates two shapes (t260916-19 ②, matrix revised
    by t261016-19 Face 2a): an untracked new file is quarantined, and an
    out-of-write-set unstaged `M` is diff-archived and restored from HEAD. A
    DELETION (`D`) is deliberately never auto-disposed - "delete intent is not
    machine-judgeable" - so a deletion of a tracked file outside the write set is
    the shape that still produces the real path-gate refusal (blocked ticket +
    gate receipt) this leg asserts. Returns the relative path for restore_tracked.
    """
    os.unlink(os.path.join(ws_root, rel))
    return rel


def restore_tracked(ws_root, rel):
    """Put a deleted tracked lane file back from HEAD (the wake-up precondition)."""
    import subprocess
    subprocess.run(["git", "-C", ws_root, "checkout", "--", rel], check=True,
                   capture_output=True, text=True)


#: Last snapshot each wait helper observed. An expired ceiling must carry the
#: state actually reached, never only the number of seconds (host order 261022,
#: grading rule 3): "did not reach <state> in N s" + this text.
LAST = {"snap": {}}


def last_snapshot_text(limit=600):
    """A compact rendering of the last observed snapshot (expiry evidence)."""
    snap = LAST.get("snap") or {}
    if not snap:
        return "<no snapshot observed>"
    try:
        text = json.dumps(snap, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(snap)
    return text if len(text) <= limit else text[:limit] + "…"


def _observe(snap):
    """Record what a poll iteration saw (expiry evidence), return it back."""
    LAST["snap"] = snap or {}
    return snap


def _worker_word(worker):
    if worker is None:
        return "no worker handle"
    if worker.poll() is None:
        return "worker alive"
    return "worker exited rc=%s" % worker.returncode


def wait_stage_running(py, env, tid, worker, wlog, fail, stage, timeout_s):
    """轮询到指定段 running（且 workspace 已知）→ 返回 snapshot；超时 bail。"""
    def _hit():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)
        s = _observe(query_snapshot(py, env, tid))
        if (s or {}).get("stage") == stage \
                and (s or {}).get("stage_state") == "running" \
                and (s or {}).get("workspace"):
            return s
        return None
    snap = poll(_hit, timeout_s)
    if snap is None:
        fail.bail("did not reach stage=%s state=running (with a workspace) in "
                  "%ds - last snapshot: %s (%s)"
                  % (stage, timeout_s, last_snapshot_text(), _worker_word(worker)))
    return snap


def wait_blocked(py, env, tid, worker, wlog, fail, timeout_s, marker=""):
    """轮询到 stage_state=blocked（可附加 marker 语义锚）→ 返回 snapshot。

    Fail fast, then wait (host order 261022): when a MARKER is asked for and the
    ticket is already blocked without it, the wanted state cannot arrive from
    that block (it needs a wake signal), so the red lands at once and names the
    receipt actually seen instead of burning the ceiling.
    """
    t0 = time.time()

    # 261026: the marker is judged on the FACE FIELDS it is supposed to land in
    # (blocked_reason + blocked_detail), never on a dump of the whole snapshot.
    # Measured: the whole-snapshot test matched a marker that a LATER timeline /
    # log string carried, the wait returned while blocked_reason was still empty,
    # and the caller's face assertion then failed with '' - a wait that reports
    # success but proves nothing (the round-in-red / alone-in-green witness).
    def _marker_hit(s):
        if not marker:
            return True
        face = json.dumps({k: s.get(k) for k in ("blocked_reason", "blocked_detail")},
                          ensure_ascii=False)
        return marker in face

    def _hit():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)
        s = _observe(query_snapshot(py, env, tid))
        if (s or {}).get("stage_state") == "blocked" and _marker_hit(s or {}):
            return s
        return None

    def _contradiction():
        if not marker:
            return None
        s = query_snapshot(py, env, tid)
        if (s or {}).get("stage_state") != "blocked":
            return None
        if _marker_hit(s or {}):
            return None
        return s

    deadline = t0 + timeout_s
    snap = None
    while time.time() < deadline:
        snap = _hit()
        if snap is not None:
            return snap
        bad = _contradiction()
        if bad is not None:
            fail.bail("did not reach stage_state=blocked carrying marker %r - the "
                      "ticket is BLOCKED after %.1fs with a different receipt: %r "
                      "(stage=%s; a wake signal would be needed to move it, so the "
                      "ceiling is not waited out) - last snapshot: %s (%s)"
                      % (marker, time.time() - t0,
                         str(bad.get("blocked_reason") or "")[:300],
                         bad.get("stage"), last_snapshot_text(),
                         _worker_word(worker)))
        time.sleep(1.0)
    fail.bail("did not reach stage_state=blocked%s in %ds - last snapshot: "
              "%s (%s)"
              % ((" carrying marker %r" % marker) if marker else "",
                 timeout_s, last_snapshot_text(), _worker_word(worker)))


def wait_unblocked(py, env, tid, worker, wlog, fail, timeout_s):
    """blocked → 唤醒（retry_qc/rework 生效，stage_state 离开 blocked）→ 返回 snapshot。"""
    def _hit():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)
        s = _observe(query_snapshot(py, env, tid))
        if (s or {}).get("stage_state") != "blocked":
            return s
        return None
    snap = poll(_hit, timeout_s)
    if snap is None:
        fail.bail("did not reach a non-blocked stage_state (the blocked wake-up) "
                  "in %ds - last snapshot: %s (%s)"
                  % (timeout_s, last_snapshot_text(), _worker_word(worker)))
    return snap


def wait_fork_window(py, env, tid, worker, wlog, fail, timeout_s):
    """轮询到并行分叉窗（meta.parallel_stages 非空）→ 返回 snapshot。

    Expiry returns None: the caller owns the assertion and its message (it
    names the state and appends last_snapshot_text())."""
    def _hit():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)
        s = _observe(query_snapshot(py, env, tid))
        if (s or {}).get("meta", {}).get("parallel_stages"):
            return s
        return None
    snap = poll(_hit, timeout_s)
    return snap


def wait_fork_left(py, env, tid, worker, wlog, fail, timeout_s):
    """轮询到离开并行分叉窗（meta.parallel_stages 空/缺）→ 返回 snapshot。

    Expiry returns None: the caller owns the assertion and its message."""
    def _hit():
        if worker.poll() is not None:
            wait_worker_alive(fail, worker, wlog)
        s = _observe(query_snapshot(py, env, tid))
        if not (s or {}).get("meta", {}).get("parallel_stages"):
            return s
        return None
    snap = poll(_hit, timeout_s)
    return snap


def blocked_timeline_entries(snap):
    """timeline 里 state=blocked 的条目（at,stage,state,reason 四元组列表，留痕锚）。"""
    return [(e.get("at"), e.get("stage"), e.get("state"), e.get("reason"))
            for e in (snap.get("timeline") or []) if e.get("state") == "blocked"]


def ticket_show_face(py, env, tid, admin_log, timeout=120):
    """正规入口 ticket.py show 的投影面（跨组件缝：引擎 snapshot → ticket.py 投影）。

    调用契约：单 JSON argv（'{"op":"show","ticket_id":...}'，_cli 只收一个 JSON 对象）；
    红线：直 spawn 每次调用自记 admin.log（默认写进仓 server/admin.log）——本助手
    钉 SANDBAR_ADMIN_LOG 到场景临时目录，仓库工作区零写入。
    返回 (rc, face_dict_or_None, raw)。face 解析失败时 raw 供断言消息点名。"""
    import subprocess
    import tempfile
    my_env = dict(env)
    if not my_env.get("SANDBAR_ADMIN_LOG"):
        my_env["SANDBAR_ADMIN_LOG"] = admin_log or os.path.join(
            tempfile.mkdtemp(prefix="t26091501-admin-"), "admin.log")
    payload = json.dumps({"op": "show", "id": tid}, ensure_ascii=False)
    raw = ""
    p = None
    # 只读 query 幂等：非 ok 重试一次（本地全形态复现不出的环境性抖动自愈窗口；
    # 失败时 raw 带 argv 形状诊断点名——错误若是「参数不是合法 JSON」说明 argv 层丢参）
    for attempt in (0, 1):
        p = subprocess.run([py, TICKET_TOOLS, payload], env=my_env,
                           cwd=REPO, capture_output=True, text=True, timeout=timeout)
        raw = ((p.stdout or "") + (p.stderr or "")).strip()
        out = parse_out_json(p.stdout)
        if out.get("ok"):
            break
        if attempt == 0:
            import time as _t
            _t.sleep(2)
    return p.returncode, (out.get("result") if out.get("ok") else None), raw
