#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260913-01 集成场景：人授权通道的「真信号送达面」+ 接收侧丢失可见化（真 docker 台）。

intent（登记于 run_scenarios.py，名 t260913-01-authz-signal-delivery）：
  人授权唯一入口（server/tools/ticket.py op=authorize → Signature.authorize → sign 信号）
  在**真实投递链**（真用户 CLI → 真 Temporal 信号 → 真专属 worker → 真 workflow）上必须
  送达并被 intake 落账——本票事故面正是「载荷在传输/解码一跳静默丢失后回落普通签字，
  回执 delivered=true 只证送达」（integration 侧 260913 三条实锤复现）。故本场景全部子用例
  走真信号投递，不以直调纯函数代替：

  相一  sign_face 指纹 query 在场（新公开契约）：worker 内存 signal 面自述可被客户端实时
        核验——陈旧 worker（无此 query）结构性 absent，是「重启判据/拒发」的根。
  相二  A 子用例：protected_path 授权真信号 → meta.authorizations 落条且 who/issued/expires/
        scope/reason/uses 完整 + timeline 签发事件 + 回执 landing 机读键（验收 A 送达半边；
        消费半边=settle 放行+path_gate_authz_used，由在册 sc_authz_protected_path 锁定）。
  相三  负锁①过期授权（真 CLI）→ refused「已过期」、不落账、回执 landing="refused"。
  相四  负锁②arbitration_verdict scope=别票（真 CLI）→ refused 点名别票票号、不落账。
  相五  负锁③who=agent 角色名（真 CLI）→ 反自签拒收、不落账。
  相六  负锁④marker 保留值真往返子用例（直发 SDK 信号：gate=marker 而 authorize 缺失=传输
        丢失后的解码等价形态）→ refused want=sign(authorize)、why 点名「载荷解析失败」
        且与「非人审等待中」可辨、不落账（验收 C 的可辨文案由此子用例机械锁定）。
  相七  负锁⑤畸形 decode-safe 载荷（直发 SDK：authorize=裸 dict 缺字段）→ intake 语义
        拒收、不落账。类型不兼容毒载荷（如 authorize=123）**故意不用**：它会让
        value_to_type 抛 TypeError 进 workflow task 重试循环（毒消息，KI 候选③），
        不属本票验收面。

与其他场景的 intent 分工（防重复）：
  · t260912-03-authz-protected-path 锁「闸的行为」（无授权红/有授权 settle 放行+记名）；
  · t260912-03-authz-overlimit-accept 锁「仲裁超限回灌消费面」（uses≥1/推进/判决原文）
    ——即本票验收 B 子用例与 D 的「B 有真信号场景」由它承担，本场景不重复烧；
  · t260912-03-authz-cli-queryable 锁「用户可查面管道」（show/list）；
  · 本条锁「送达面 + 接收侧丢失可见化 + 真信号负锁矩阵」。与 developer L1（指纹/分类/
    落账纯函数单测）不同层。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台缺件=环境红点名）。
实现段落地前红属预期（TDD 信号：相一/相二回执键/相三回执键/相六），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260913-01/tests/sc_authz_signal_delivery.py
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
           os.path.join(REPO, "integration", "t260908-01"),
           os.path.join(REPO, "server", "engine")):
    sys.path.insert(0, _p)

from lib_gate import (Fail, parse_out_json, poc_python, read_audit_jsonl,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_ki061 import (ARB_STUB, make_fixture_repo, poll, query_snapshot,  # noqa: E402
                       read_stub_log, send_signal, spawn_worker, stage_env,
                       wait_worker_alive)

# marker 保留值：优先取引擎单一真源（implement 落地后在场）；缺位时回落方案钉死的
# wire 字面值——两条子用例都只锁「线上的这个 token」，不锁常量名。
try:
    from shared import AUTHZ_SIGNAL_GATE_MARKER as _MARKER  # noqa: E402
    MARKER, MARKER_SRC = _MARKER, "shared.AUTHZ_SIGNAL_GATE_MARKER"
except Exception:  # noqa: BLE001  实现段落地前：常量不在场，用方案字面值
    MARKER, MARKER_SRC = "__authorize__", "方案字面值（引擎常量未落地）"

TID = "t26091301a-authz-d"
PROJ_KEY = "t26091301a"
WHO = "宿主"                       # CLI 子用例的授权人（人名，非 agent 角色名）
WHO_DIRECT = "host-operator"       # 直发 SDK 子用例的 who（ASCII，规避 locale 面）
REASON = "t260913-01 场景：批准本票改共享电池期望值（送达面子用例）"
SCOPE = "integration/baselines"
OTHER_TID = "t26099999-99"         # 别票票号（负锁②）
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")

STATS = {"ok": 0, "fail": 0}


# ---------- 真用户 CLI（server/tools/ticket.py，与 t260912-03 场景同款夹具） ----------

def cli(py, env, payload, timeout=180):
    p = subprocess.run([py, TICKET_PY, json.dumps(payload, ensure_ascii=False)],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


_RESULT_MARKERS = ("result", "tickets", "stage_state", "authorizations",
                   "signatures", "refused", "deliverables")


def cli_json(out):
    """ticket.py 的 stdout=多行 JSON（审计行在前、结果在后）——按结果特征键选行。"""
    best = None
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            d = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and any(k in d for k in _RESULT_MARKERS):
            best = d
        elif best is None:
            best = d
    return best if best is not None else parse_out_json(out)


def unwrap(doc):
    if isinstance(doc, dict) and "ok" in doc and isinstance(doc.get("result"), (dict, list)):
        return doc["result"]
    return doc


def receipt_holder(doc, key):
    """回执机读键定位（容忍顶层/result 两形——键的**在场与取值**是契约，落点不锚）。"""
    for holder in (doc, unwrap(doc)):
        if isinstance(holder, dict) and key in holder:
            return holder
    return None


# ---------- 票面读口（snapshot：refused 顶层、授权条目在 meta 下——R3 读面） ----------

def authz_items(snap):
    """授权条目可读面（meta['authorizations'] 为主、顶层容错；镜像 t260912-03 helper）。"""
    for holder in (snap or {}, (snap or {}).get("meta") or {}):
        items = holder.get("authorizations") if isinstance(holder, dict) else None
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
    return []


def refused_items(snap):
    rows = (snap or {}).get("refused")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def authorized_events(snap):
    tl = (snap or {}).get("timeline")
    if not isinstance(tl, list):
        return []
    return [e for e in tl if isinstance(e, dict) and str(e.get("state") or "") == "authorized"]


def snapshot_state(py, env):
    s = query_snapshot(py, env, TID)
    return (len(authz_items(s)), len(refused_items(s)), len(authorized_events(s)), s)


def poll_negative(py, env, worker, wlog, base, pred, timeout_s=90):
    """负锁轮询：等「新 refused 命中 pred」；授权计数一变=负锁被穿透，立即回报不干等。
    返回 (outcome, snap, entry)：outcome ∈ hit / landed / timeout。"""
    b_az, b_ref, b_tl, _ = base

    def _probe():
        az, ref, tl, s = snapshot_state(py, env)
        if az != b_az or tl != b_tl:
            return ("landed", s, None)
        for r in refused_items(s)[b_ref:]:
            if pred(r):
                return ("hit", s, r)
        return None
    hit = poll(_probe, timeout_s)
    if hit is None:
        wait_worker_alive(__fail, worker, wlog)
        az, ref, tl, s = snapshot_state(py, env)
        if az != b_az or tl != b_tl:
            return ("landed", s, None)
        return ("timeout", s, None)
    return hit


# ---------- 直连 SDK 面（真信号/真 query，不经 CLI 白名单；lib_ki061.send_signal 同款） ----------

def direct_query(py, state, tid, name, timeout=60):
    script = (
        "import asyncio, json\n"
        "from temporalio.client import Client\n"
        "async def main():\n"
        "    c = await Client.connect('127.0.0.1:%d', namespace='%s')\n"
        "    try:\n"
        "        v = await c.get_workflow_handle('%s').query('%s')\n"
        "        print(json.dumps({'ok': True, 'value': v}, ensure_ascii=False, default=str))\n"
        "    except Exception as e:\n"
        "        print(json.dumps({'ok': False, 'err_type': type(e).__name__, "
        "'err': str(e)[:200]}, ensure_ascii=False))\n"
        "asyncio.run(main())\n"
        % (state["ports"]["temporal"], state["namespace"], tid, name))
    p = subprocess.run([py, "-c", script], capture_output=True, text=True, timeout=timeout)
    doc = {}
    for ln in (p.stdout or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                doc = json.loads(ln)
            except Exception:  # noqa: BLE001
                pass
    if not doc:
        doc = {"ok": False, "err_type": "no_json", "err": ((p.stdout or "") + (p.stderr or ""))[-200:]}
    return doc


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


__fail = None  # poll_negative 里 wait_worker_alive 需要点名通道（main 内赋值）


def main():
    global __fail
    fail = Fail("t260913-01 人授权真信号送达面 + 接收侧丢失可见化")
    __fail = fail

    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091301a-")
    audit_dir = os.path.join(tmp, "audit")
    os.makedirs(audit_dir, exist_ok=True)
    audit_env, audit_log = bench.audit_hook_env(audit_dir)
    stage_mod = None
    stage_name = "%s-%d" % (PROJ_KEY, os.getpid())
    worker = None
    stage_downed = False
    print("  · marker 保留值来源：%s = %r" % (MARKER_SRC, MARKER), flush=True)
    try:
        stage_mod, state = require_stage(fail, stage_name, TID)
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY,
                                       make_fixture_repo(tmp))
        env = stage_env(state, reg_dir, audit_env)
        # 260927（KI-142）：env 级声明调用方身份——本场景后面 authorize（经 ticket.py）
        # 等写 op 共用同一 env；不声明则建票先被身份闸拒收，整条旅程无从谈起。
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
            "title": "t260913-01 人授权真信号送达面", "write_set": ["docs/"]}, env)
        check(rc == 0 and TID in out, "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-140:]))

        def _alive():
            s = query_snapshot(py, env, TID)
            return s if isinstance(s, dict) and s.get("ticket_id") == TID else None
        if poll(_alive, 120) is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            fail.bail("workflow snapshot 不可读（票未起或 worker 未认领），后续子用例全跑不真")
        base0 = snapshot_state(py, env)
        print("  · 基线：authorizations=%d refused=%d authorized 事件=%d"
              % (base0[0], base0[1], base0[2]), flush=True)

        # ---------------- 相一：sign_face 指纹 query 在场（新公开契约） ----------------
        q = direct_query(py, state, TID, "sign_face")
        if not q.get("ok"):
            check(False, "sign_face query 在场且可答（收到 %s: %s——方案 L2 未落地或未注册？）"
                  % (q.get("err_type"), q.get("err")))
        else:
            v = q.get("value")
            check(isinstance(v, dict), "sign_face 返回 dict（收到 %s）" % type(v).__name__)
            check(isinstance(v, dict) and v.get("face") == "sign",
                  "sign_face 自述面=sign（收到 %r）" % (v or {}).get("face"))
            fields = (v or {}).get("fields") if isinstance(v, dict) else None
            check(isinstance(fields, list) and "authorize" in fields,
                  "sign_face 字段集含 authorize（嵌套载荷面在场）：%r" % (fields,))
            check(isinstance(v, dict) and bool(str(v.get("marker") or "").strip()),
                  "sign_face 带 marker 保留值（接收侧丢失可见化的对端凭据）")

        # ---------------- 相二：A 子用例——protected_path 授权真信号送达+落账 ----------------
        exp_future = int(time.time()) + 3600
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": WHO,
                                "kind": "protected_path", "scope": [SCOPE],
                                "reason": REASON, "expires": exp_future})
        doc = cli_json(out)
        check(doc.get("ok") is True, "A 子用例 CLI op=authorize 受理（rc=%s out尾=%s）"
              % (rc, out[-160:]))

        def _landed():
            az, ref, tl, s = snapshot_state(py, env)
            return s if az == base0[0] + 1 else None
        s = poll(_landed, 90)
        if s is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            s = query_snapshot(py, env, TID)
            fail.bail("A 子用例授权未落账（authorizations=%d；refused尾=%s）——载荷在投递/解码"
                      "一跳丢失或 intake 未生效（本票事故形态）"
                      % (len(authz_items(s)),
                         json.dumps(refused_items(s)[-1:], ensure_ascii=False)[:260]))
        items = authz_items(s)
        it = items[-1]
        print("  · A 子用例证据：authorizations 尾条=%s" % json.dumps(it, ensure_ascii=False)[:300],
              flush=True)
        check(len(items) == base0[0] + 1, "A 子用例落账恰 +1 条（%d→%d）" % (base0[0], len(items)))
        check(str(it.get("who") or "") == WHO, "落账 who 记名=%r" % it.get("who"))
        check(str(it.get("kind") or "") == "protected_path", "落账 kind=%r" % it.get("kind"))
        check([str(x) for x in (it.get("scope") or [])] == [SCOPE],
              "落账 scope=%r" % (it.get("scope"),))
        check(str(it.get("reason") or "") == REASON, "落账 reason 记名（为什么批）")
        check(int(it.get("expires") or 0) == exp_future, "落账 expires=%s（原样入账）"
              % it.get("expires"))
        check(int(it.get("issued") or 0) > 0, "落账 issued>0（workflow 盖写签发时刻）")
        check(isinstance(it.get("uses"), list) and len(it.get("uses") or []) == 0,
              "落账 uses 空（未消费不留痕）")
        check(len(authorized_events(s)) == base0[2] + 1,
              "签发落不可变事件（timeline state=authorized，%d→%d）"
              % (base0[2], len(authorized_events(s))))
        holder = receipt_holder(doc, "landing")
        check(holder is not None and holder.get("landing") == "landed",
              "回执带 landing=landed 机读键（人不用翻票面就知道真落账了）")
        h2 = receipt_holder(doc, "authorization")
        check(isinstance(h2, dict) and str((h2.get("authorization") or {}).get("who") or "") == WHO,
              "回执带 authorization 记名块（who 可读）")

        # ---------------- 相三：负锁① 过期授权（真 CLI） ----------------
        base1 = snapshot_state(py, env)
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": WHO,
                                "kind": "protected_path", "scope": [SCOPE],
                                "reason": REASON, "expires": int(time.time()) - 10})
        doc = cli_json(out)
        check(doc.get("ok") is True, "负锁① 过期授权送达（回执 ok；权威判定在 workflow intake）")
        outcome, s, entry = poll_negative(
            py, env, worker, os.path.join(tmp, "worker.log"), base1,
            lambda r: "already passed" in str(r.get("why") or ""))
        check(outcome == "hit",
              "负锁① 拒收点名「已过期」（outcome=%s；refused尾=%s）"
              % (outcome, json.dumps(refused_items(s)[-1:], ensure_ascii=False)[:220]))
        check(len(authz_items(s)) == base1[0],
              "负锁① 死授权不落账（authorizations=%d）" % len(authz_items(s)))
        holder = receipt_holder(doc, "landing")
        check(holder is not None and holder.get("landing") == "refused",
              "负锁① 回执 landing=refused 机读键（送达≠生效，回执可辨）")

        # ---------------- 相四：负锁② arbitration_verdict scope=别票（真 CLI） ----------------
        base2 = snapshot_state(py, env)
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": WHO,
                                "kind": "arbitration_verdict", "scope": [OTHER_TID],
                                "reason": REASON, "expires": exp_future})
        check(cli_json(out).get("ok") is True, "负锁② 别票授权送达（判定在 intake）")
        outcome, s, entry = poll_negative(
            py, env, worker, os.path.join(tmp, "worker.log"), base2,
            lambda r: (str(r.get("want") or "") == "sign(authorize)"
                       and (OTHER_TID in str(r.get("why") or "")
                            or "票号" in str(r.get("why") or "")
                            or "scope" in str(r.get("why") or ""))))
        check(outcome == "hit",
              "负锁② 拒收点名票号约束（outcome=%s；why尾=%s）——别票授权不生效"
              % (outcome, str((entry or {}).get("why") or "")[-140:]))
        check(len(authz_items(s)) == base2[0],
              "负锁② 别票授权不落账（authorizations=%d）" % len(authz_items(s)))

        # ---------------- 相五：负锁③ who=agent 角色名（真 CLI，反自签） ----------------
        base3 = snapshot_state(py, env)
        rc, out = cli(py, env, {"op": "authorize", "id": TID, "who": "developer",
                                "kind": "protected_path", "scope": [SCOPE],
                                "reason": REASON, "expires": exp_future})
        check(cli_json(out).get("ok") is True, "负锁③ 自签载荷送达（拒收在 workflow intake）")
        outcome, s, entry = poll_negative(
            py, env, worker, os.path.join(tmp, "worker.log"), base3,
            lambda r: "developer" in str(r.get("why") or ""))
        check(outcome == "hit",
              "负锁③ 反自签拒收点名 who（outcome=%s；why尾=%s）"
              % (outcome, str((entry or {}).get("why") or "")[-140:]))
        check(len(authz_items(s)) == base3[0],
              "负锁③ 自签不落账（authorizations=%d）" % len(authz_items(s)))

        # ---------------- 相六：负锁④ marker 真往返子用例（直发 SDK=传输丢失等价形态） ----------------
        base4 = snapshot_state(py, env)
        rc, out = send_signal(py, state, TID, "sign",
                              {"who": WHO_DIRECT, "gate": MARKER,
                               "decision": "approve", "note": ""})
        check(rc == 0, "负锁④ marker 信号直发成功（rc=%s out尾=%s）" % (rc, out[-140:]))
        outcome, s, entry = poll_negative(
            py, env, worker, os.path.join(tmp, "worker.log"), base4,
            lambda r: (str(r.get("want") or "") == "sign(authorize)"
                       and "authorize payload parse failed" in str(r.get("why") or "")
                       and "not awaiting human review" not in str(r.get("why") or "")))
        check(outcome == "hit",
              "负锁④ marker 在场而载荷缺失 → refused 点名「载荷解析失败」且与"
              "「非人审等待中」可辨（outcome=%s；refused尾=%s）——静默回落普通签字=本票事故形态"
              % (outcome, json.dumps(refused_items(s)[-1:], ensure_ascii=False)[:220]))
        check(len(authz_items(s)) == base4[0],
              "负锁④ 不落账（authorizations=%d）" % len(authz_items(s)))

        # ---------------- 相七：负锁⑤ 畸形 decode-safe 载荷（直发 SDK） ----------------
        base5 = snapshot_state(py, env)
        rc, out = send_signal(py, state, TID, "sign",
                              {"who": WHO_DIRECT, "gate": "", "decision": "approve",
                               "note": "", "authorize": {"kind": "protected_path"}})
        check(rc == 0, "负锁⑤ 畸形（裸 dict 缺字段）信号直发成功（rc=%s）" % rc)
        outcome, s, entry = poll_negative(
            py, env, worker, os.path.join(tmp, "worker.log"), base5,
            lambda r: (str(r.get("want") or "") == "sign(authorize)"
                       and bool(str(r.get("why") or "").strip())
                       and "not awaiting human review" not in str(r.get("why") or "")))
        check(outcome == "hit",
              "负锁⑤ 畸形载荷到 intake 被语义拒收（outcome=%s；want=sign(authorize) why非空；"
              "毒载荷 authorize=123 不用=value_to_type TypeError 会进 workflow task 重试循环）"
              % outcome)
        check(len(authz_items(s)) == base5[0],
              "负锁⑤ 不落账（authorizations=%d）" % len(authz_items(s)))

        # ---------------- 收口：负锁矩阵合计 + 红线审计 + 拆台零残留 ----------------
        az_f, ref_f, tl_f, s_f = snapshot_state(py, env)
        check(az_f == base0[0] + 1 and tl_f == base0[2] + 1,
              "全程恰一条生效授权+一条签发事件（5 条负锁全未落账；az=%d tl=%d）"
              % (az_f, tl_f))
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
            except Exception:  # noqa: BLE001
                pass
        if os.environ.get("T26091301_KEEP_TMP") == "1":
            print("TMP preserved（T26091301_KEEP_TMP=1）: %s" % tmp, flush=True)
        else:
            cleanup_tmp(tmp)
    print("SC sc_authz_signal_delivery pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)


if __name__ == "__main__":
    main()
