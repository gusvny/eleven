#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-03 集成场景：人授权的「可查面」在真 CLI 上成立（验收 C，真 docker 台）。

intent（登记于 run_scenarios.py）：
  人授权签发之后，**用户真用的两个查询入口**（server/tools/ticket.py 的 op=show /
  op=list，不是引擎内部 snapshot）必须能读出这条授权：类型（kind）、范围（scope）、
  授权人（who）、到期（expires）、状态（生效中/已过期）、消费次数（used_count）；
  签发落不可变事件（timeline `state=authorized`）；死授权（已过期）与反自签（who=agent
  角色名）在 CLI 层被 workflow intake 拒收后**不出现在可查面**，生效中计数不虚增。

  为什么单开一条子用例：本票另外两条 L3 场景（sc_authz_protected_path /
  sc_authz_overlimit_accept）读的都是引擎 snapshot 原始 meta；而验收口径 C 说的是
  **ticket show / 工单列表**这一层——它是 CLI → client.py ticket-query/ticket-list →
  Temporal query 的整条管道（KI-076 同族故障模式：管道断在中间时原始 meta 绿而用户面白）。

负锁（防恒真）：
  · 过期授权：CLI 回执 ok（送达）但 workflow 落 refused（含「已过期」），show 的 authz
    列表条目数不增、list 的 authz_active 不增（死授权不产生生效条目）；
  · who=agent 自身角色名：同上，拒收且可查面零变化；
  · 生效中计数只数本票未过期条目（exactly 1，不是 ≥1）。

与前两条场景 intent 分工（不重复）：彼二锁「闸的行为」（无授权照旧红 / 有授权真放行 /
超限不阻断），本条锁「人能看到什么」（用户查询面）。与 developer L1
（test_t260912_03_authz_cli.py 用合成 snapshot 测 _authz_view/_list 格式化）不同层：
本条跑真引擎 + 真 CLI，锁管道而不是格式化函数。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260912-03/tests/sc_authz_cli_queryable.py
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台缺件=环境红点名）。
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (os.path.join(REPO, "integration"),
           os.path.join(REPO, "integration", "t260904-02"),
           os.path.join(REPO, "integration", "t260908-01")):
    sys.path.insert(0, _p)

from lib_gate import (Fail, accepted, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_ki061 import (ARB_STUB, make_fixture_repo, poll, read_stub_log,  # noqa: E402
                       spawn_worker, stage_env, wait_worker_alive)

TID = "t26091203c-authz-q"
PROJ_KEY = "t26091203c"
WHO = "宿主"
REASON = "t260912-03 场景：批准本票改共享电池期望值（可查面子用例）"
SCOPE = "integration/baselines"
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")

STATS = {"ok": 0, "fail": 0}


def cli(py, env, payload, timeout=180):
    """真用户入口：server/tools/ticket.py '<json>'（不是裸 client.py，不是引擎内部面）。"""
    p = subprocess.run([py, TICKET_PY, json.dumps(payload, ensure_ascii=False)],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


_RESULT_MARKERS = ("result", "tickets", "stage_state", "authorizations",
                   "signatures", "refused", "deliverables")


def cli_json(out):
    """ticket.py 的 JSON 回执解析。

    ticket.py 的 stdout 是**多行 JSON**：审计行（双行审计：ticket.py-direct + client.py，
    共享 call_id）在前，结果 JSON 在后（__main__ 末尾 print(json.dumps(out))）。所以
    不能取第一行也不能取首 { 到末 } 的整段（跨两文档必坏）——按「结果文档特征键」
    （tickets/stage_state/authorizations/...）选最后一条命中的行。"""
    best = None
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            d = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        if any(k in d for k in _RESULT_MARKERS):
            best = d
        elif best is None:
            best = d
    return best if best is not None else parse_out_json(out)


def unwrap(doc):
    """ticket.py 结果形状：{'ok':true,'result':<载荷>} —— 取出载荷（show 的载荷=meta dict，
    list 的载荷={'count','tickets'}）；非包装形状原样返回。"""
    if isinstance(doc, dict) and "ok" in doc and isinstance(doc.get("result"), (dict, list)):
        return doc["result"]
    return doc


def show(py, env):
    rc, out = cli(py, env, {"op": "show", "id": TID})
    return rc, unwrap(cli_json(out)), out


def ticket_list(py, env):
    rc, out = cli(py, env, {"op": "list", "project": PROJ_KEY})
    return rc, unwrap(cli_json(out)), out


def row_for(doc, tid):
    for r in (doc.get("tickets") or []):
        if isinstance(r, dict) and str(r.get("id") or "") == tid:
            return r
    return None


def kill_worker_tree(worker):
    """worker 全终态回收（本场景自己 spawn 的进程组；不按名字/端口扫杀别人）。"""
    if worker is None or worker.poll() is not None:
        return
    try:
        os.killpg(worker.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        worker.wait(timeout=10)
    except Exception:  # noqa: BLE001
        try:
            worker.kill()
        except Exception:  # noqa: BLE001
            pass


def cleanup_tmp(tmp):
    for _ in range(5):
        try:
            shutil.rmtree(tmp)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(1)
    print("  · 警告：tmp 未能回收：%s" % tmp, flush=True)
    return False


def main():
    fail = Fail("t260912-03 人授权可查面（真 CLI：ticket show / ticket list）")

    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091203c-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    stage_name = "%s-%d" % (PROJ_KEY, os.getpid())
    worker = None
    stage_downed = False
    try:
        stage_mod, stage = require_stage(fail, stage_name, TID)
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        env = stage_env(stage, reg_dir, audit_env)
        # 260927（KI-142）：三条 authorize 经 ticket.py 走同一 env（gated 写），一处声明。
        env["SANDBAR_CALLER_PROJECT"] = PROJ_KEY
        stub_path = os.path.join(tmp, "ki061_stub.py")
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(ARB_STUB)
        worker = spawn_worker(py, TID, env, os.path.join(tmp, "worker.log"), stub_path,
                              os.path.join(tmp, "stub.jsonl"),
                              disable_ki061=False, arb_verdict="pass")
        check(worker.poll() is None, "worker 已拉起 pid=%s" % worker.pid)
        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "t260912-03 人授权可查面", "write_set": ["docs/"]}, env)
        _ok, _why = accepted(out, TID)          # 260927（KI-142）：受理只认 ok=true
        check(rc == 0 and _ok, "ticket-start 受理（%s）" % _why)

        # ---------------- 相一：生效授权在 ticket show / list 上可读 ----------------
        exp_future = int(time.time()) + 3600
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": WHO,
                               "kind": "protected_path", "scope": [SCOPE],
                               "reason": REASON, "expires": exp_future})
        doc = parse_out_json(out)
        check(doc.get("ok") is True, "CLI op=authorize 受理（rc=%s out尾=%s）"
              % (rc, out[-160:]))

        # 相一 A：工单列表（用户主列表面）须给出生效中计数
        def _listed():
            row = row_for(ticket_list(py, env)[1], TID)
            return row if row is not None and int(row.get("authz_active") or 0) == 1 else None
        row = poll(_listed, 90)
        if row is None:
            rcL0, dL0, outL0 = ticket_list(py, env)
            row0 = row_for(dL0, TID)
            fail.bail("工单列表未给出生效中授权计数（row=%s count=%s out尾=%s）"
                      % (json.dumps(row0, ensure_ascii=False)[:200], dL0.get("count"),
                         (outL0 or "")[-200:]))
        print("  相一 A 证据：list row authz_active=%s" % row.get("authz_active"), flush=True)
        check(True, "工单列表行给出生效中授权数 authz_active=1（谁批的票上有 N 条一眼可见）")

        # 相一 B：ticket show 明细面（类型/范围/授权人/到期/状态/消费次数 + 签发事件）
        def _visible():
            rc2, d2, _ = show(py, env)
            items = d2.get("authz") if isinstance(d2, dict) else None
            if isinstance(items, list) and items:
                return d2
            return None
        d = poll(_visible, 90)
        if d is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            rc2, d2, out2 = show(py, env)
            src = d2.get("authorizations")
            fail.bail("ticket show 读不到授权条目：顶层键=%s；"
                      "meta 源头 authorizations 在场=%s（%s 条）——验收 C 的 show 面断"
                      % (sorted(d2.keys())[:14], isinstance(src, list),
                         len(src) if isinstance(src, list) else "n/a"))  # noqa
        items = d.get("authz") or []
        it = items[0]
        print("  相一 证据：show.authz=%s" % json.dumps(it, ensure_ascii=False)[:300],
              flush=True)
        check(len(items) == 1, "show 的 authz 恰好 1 条（%d）" % len(items))
        check(it.get("kind") == "protected_path", "show 读出类型 kind=%r" % it.get("kind"))
        check([str(x) for x in (it.get("scope") or [])] == [SCOPE],
              "show 读出范围 scope=%r" % (it.get("scope"),))
        check(str(it.get("who") or "") == WHO, "show 读出授权人 who=%r" % it.get("who"))
        check(int(it.get("expires") or 0) == exp_future,
              "show 读出到期 expires=%s" % it.get("expires"))
        check(str(it.get("status") or "") == "生效中",
              "show 读出状态 status=%r" % it.get("status"))
        check(int(it.get("used_count") or 0) == 0,
              "show 读出消费次数 used_count=%s（未使用过）" % it.get("used_count"))
        check(d.get("authz_active") == 1, "show 的 authz_active=%s" % d.get("authz_active"))
        tl = [e for e in (d.get("timeline") or [])
              if isinstance(e, dict) and str(e.get("state") or "") == "authorized"]
        check(bool(tl), "签发落不可变事件（timeline state=authorized，%d 条）" % len(tl))
        check(bool(tl) and WHO in json.dumps(tl[-1], ensure_ascii=False)
              and SCOPE in json.dumps(tl[-1], ensure_ascii=False),
              "签发事件点名授权人与范围（谁批的、批的哪条）")

        rcL, dL, outL = ticket_list(py, env)
        row2 = row_for(dL, TID)
        check(row2 is not None and row2.get("authz_active") == 1,
              "工单列表行仍给出生效中计数（authz_active=%s）"
              % (row2 or {}).get("authz_active"))

        # ---------------- 相二：过期授权 → 拒收且可查面零变化（负锁） ----------------
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": WHO,
                               "kind": "protected_path", "scope": [SCOPE],
                               "reason": REASON, "expires": int(time.time()) - 10})
        doc = parse_out_json(out)
        check(doc.get("ok") is True and unwrap(doc).get("delivered") is True,
              "过期授权经 sign 面送达（回执 ok；权威判定在 workflow）")

        def _refused():
            rc2, d2, _ = show(py, env)
            if "already passed" in json.dumps(d2.get("refused") or [], ensure_ascii=False):
                return d2
            return None
        dr = poll(_refused, 90)
        if dr is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            s = show(py, env)[1]
            fail.bail("过期授权未被 workflow 拒收登记（refused=%s）"
                      % json.dumps(s.get("refused") or [], ensure_ascii=False)[:300])
        print("  相二 证据：refused尾=%s"
              % json.dumps(dr.get("refused") or [], ensure_ascii=False)[-200:], flush=True)
        check("already passed" in json.dumps(dr.get("refused") or [], ensure_ascii=False),
              "拒收文案点名原因是「已过期」（不说没有 X，说哪个检查失败）")
        check(len(dr.get("authz") or []) == 1 and dr.get("authz_active") == 1,
              "死授权不进可查面（authz=%d authz_active=%s）"
              % (len(dr.get("authz") or []), dr.get("authz_active")))
        row2 = row_for(ticket_list(py, env)[1], TID)
        check(row2 is not None and row2.get("authz_active") == 1,
              "工单列表生效中计数不因死授权虚增（authz_active=%s）"
              % (row2 or {}).get("authz_active"))

        # ---------------- 相三：who=agent 角色名 → 拒收且可查面零变化（负锁） ----------------
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": "developer",
                               "kind": "protected_path", "scope": [SCOPE],
                               "reason": REASON, "expires": exp_future})
        check(parse_out_json(out).get("ok") is True,
              "自签载荷送达（回执 ok；拒收在 workflow intake，不在包装层）")

        def _selfsign_refused():
            rc2, d2, _ = show(py, env)
            txt = json.dumps(d2.get("refused") or [], ensure_ascii=False)
            if "developer" in txt and len(d2.get("authz") or []) == 1:
                return d2
            return None
        ds = poll(_selfsign_refused, 90)
        if ds is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            ds = show(py, env)[1]
        txt = json.dumps(ds.get("refused") or [], ensure_ascii=False)
        check("developer" in txt, "自签被拒收并落 refused（点名 who）")
        check(len(ds.get("authz") or []) == 1 and ds.get("authz_active") == 1,
              "自签不产生生效条目（authz=%d authz_active=%s）"
              % (len(ds.get("authz") or []), ds.get("authz_active")))

        # ---------------- 红线审计 + 拆台零残留 ----------------
        audit = read_audit_jsonl(audit_log)
        check(not audit, "审计账本为空（未触碰生产 7233/8233/3099）：%d 条" % len(audit))
        kill_worker_tree(worker)
        down = stage_down(stage_mod, stage_name)
        stage_downed = True
        resid = (down or {}).get("residue") if isinstance(down, dict) else down
        check(not resid, "拆台零残留（residue=%s）" % (resid,))
        print("  · 仲裁桩调用次数=%d（本场景不驱动上游判定，仅证 worker 活）"
              % len(read_stub_log(os.path.join(tmp, "stub.jsonl"))), flush=True)
    finally:
        kill_worker_tree(worker)
        if stage_mod is not None and not stage_downed:
            try:
                stage_down(stage_mod, stage_name)
            except Exception:
                pass
        if os.environ.get("KI061_KEEP_TMP") == "1":
            print("TMP preserved（KI061_KEEP_TMP=1）: %s" % tmp, flush=True)
        else:
            cleanup_tmp(tmp)
    print("SC sc_authz_cli_queryable pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
