#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-12 集成场景：跨项目写操作闸的真链路用户契约面（真 docker 台）。

intent（登记于 run_scenarios.py，名 t260915-12-gate-real-chain）：
  写操作项目一致性闸（caller-project gate）在**真实链路**（真用户入口 client.py /
  ticket.py → 真 Temporal 信号 → 真专属 worker → 真 workflow）上的用户可感知契约：
  ① declared 身份与目标票 project 不符 → fail-closed 拒收，人话点名「谁要动谁的票」
    （回执 kind=cross_project_refused + admin.log 行 override=false）；
  ② declared 同项目写操作零影响（行为不变，回执仅新增身份键 caller_project/
    identity_src）；
  ③ 越权旗 cross_project{by,reason} → 放行 + 记名（meta['cross_project_uses'] 可经
    ticket.py show 用户出口对账 + admin.log override=true；重发=按笔累计）；
  ④ 身份出处可审计：显式参数 > env(SANDBAR_CALLER_PROJECT) > cwd 窄兜底 > undeclared，
    回执 identity_src 落词汇表 arg|env|cwd|none；
  ⑤ undeclared（经旋钮 SANDBAR_UNDECLARED_POLICY=record 显式选入的记名策略）→ 放行 +
    强制记名（回执 identity_class=undeclared + 入越权对账面）——**本场景钉的是
    record 策略契约**；t260925-08 已把引擎缺省翻为 refuse（undeclared=拒收），
    本场景整体经旋钮选入 record 以继续钉记名面；缺省 refuse 由 sc_check 静态面
    与单测锁定（真函数重放），不属本场景回归面；
  ⑥ cwd 兜底仓树排除（review C1 探测器）：cwd=引擎仓内子目录必须 undeclared，不得按
    注册目录前缀误判成 declared（注册表里专门放了 dirs=[引擎仓根] 的探测条目）；
  ⑦ workflow 第二道（直发 SDK 真 stamp 解码，review C5 送达面）：盖章信号真投递后
    handler 读得到 caller_project/cross_project_note——不带头旗=refused[] 点名不执行；
    带头旗=记名放行；无盖章（老 client 等价形态）=兼容不校验；
  ⑧ retry_qc 不盖章残留诚实（方案 §8）：越权旗经 client 侧放行 + admin.log override=
    true，但 meta 记名**不增**（Temporal 历史无该 op 身份=已声明残留，非漏记）；
  ⑨ 读面零闸；cancel 过闸（带 ProjectKey SA 的工单 workflow 才闸）。

与其他场景/测试的 intent 分工（防重复）：
  · t260912-03 三场景（受保护路径/仲裁上限/可查面）锁的是**人授权载荷**（authorize）
    的闸行为与消费面，本条锁**调用方项目归属**闸——同走 sign 信号面但判据不同维；
  · t260913-01 锁 authorize 载荷传输送达面；本条 ⑦ 锁的是 stamp 标量字段的真投递，
    面相邻但判据与负锁矩阵不同；
  · t260908-01 pause 场景锁 pause intake 语义；本条只把 pause/ruling 当「任意状态可发
    的写 op 载体」测身份维，不重复 intake 面；
  · developer L1（server/engine/tests/test_t260915_12_t01/t02：纯函数矩阵 + client 接线
    桩测）与其源码锁场景（sc_check_cross_project_gate，方案 §4 由实现段交付）锁内部
    接线与判定函数；本条全部走真进程真链路，断言只落回执/admin.log/snapshot/用户
    出口四类公开契约，不同层不重复。

三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（docker/镜像/舞台/venv 缺件=环境红点名）。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260915-12/tests/sc_cross_project_gate_realchain.py
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
from lib_ki061 import (make_fixture_repo, poll, query_snapshot, send_signal,  # noqa: E402
                       spawn_worker, stage_env, wait_worker_alive)

TID = "t26091512a-gate"            # 被测工单（PROJECT_KEY_RE 形内）
PROJ_KEY = "sc12proj"              # 票所属项目（fixture 仓目录）
OTHER_KEY = "sc12other"            # 他项目身份（fixture 仓目录）
REPO_KEY = "sc12repo"              # dirs=[引擎仓根] 的探测条目（相八 C1 探测器用）
WHO = "宿主"                       # 写 op 操作人（人名语义，由调用方注入）
CLIENT_PY = os.path.join(REPO, "server", "engine", "client.py")
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")
ENGINE_SUBDIR = os.path.join(REPO, "server", "engine")  # 仓树内子目录（C1 探测子用例 cwd）
FIXTURE_REPO_DIR = "fixture-repo"  # make_fixture_repo 在 tmp 下建的目录名

STATS = {"ok": 0, "fail": 0}


# ---------- 入口封装（client.py 可控 cwd 版；run_poc_client 钉死 cwd=REPO 不够用） ----------

def client(py, sub, args, env, cwd=None, timeout=180):
    """spawn <py> client.py <sub> <argsJSON>，cwd 可调（身份 cwd 兜底分支的探测面）。"""
    p = subprocess.run([py, CLIENT_PY, sub, json.dumps(args, ensure_ascii=False)],
                       env=env, cwd=cwd or REPO, capture_output=True, text=True,
                       timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def receipt(out):
    return parse_out_json(out)


def cli_ticket(py, env, payload, timeout=180):
    """正规包装层入口 server/tools/ticket.py（多行 JSON：审计行在前、结果在后）。"""
    p = subprocess.run([py, TICKET_PY, json.dumps(payload, ensure_ascii=False)],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


# ---------- 票面读口（全部基线相对，防 stub 脑推进带来的本底噪声） ----------

def cpu_uses(snap):
    meta = (snap or {}).get("meta") if isinstance(snap, dict) else None
    items = (meta or {}).get("cross_project_uses")
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def refused_rows(snap):
    rows = (snap or {}).get("refused")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def paused_flag(snap):
    return bool((snap or {}).get("paused"))


def audit_rows(audit_log):
    return read_audit_jsonl(audit_log)


def env_with(env, var, key):
    e = dict(env)
    if key is None:
        e.pop(var, None)
    else:
        e[var] = key
    return e


def wait_paused(py, env, want, timeout_s=90):
    """轮询 paused 翻转到 want（pause intake 在段间门口生效，非即时）。"""
    def _probe():
        return paused_flag(query_snapshot(py, env, TID)) is want
    return poll(_probe, timeout_s) is not None


# ---------- 直发 SDK（真 stamp 解码；dict 载荷 decode-safe，t260912-03 相七同款） ----------

def direct_pause_stamp(py, state, tid, who, note, caller_project, cross_project_note):
    payload = {"who": who, "note": note}
    if caller_project is not None:
        payload["caller_project"] = caller_project
    if cross_project_note is not None:
        payload["cross_project_note"] = cross_project_note
    return send_signal(py, state, tid, "pause", payload)


def kill_worker_tree(worker):
    """本场景自己 spawn 的 worker 进程组回收（不按名字/端口扫杀别人）。"""
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
    fail = Fail("t260915-12 跨项目写操作闸真链路契约面")

    def check(cond, msg):
        r = fail.check(cond, msg)
        STATS["ok" if r else "fail"] += 1
        return r

    bench = require_bench(fail)
    py = poc_python(bench)
    tmp = tempfile.mkdtemp(prefix="t26091512a-")
    admin_log = os.path.join(tmp, "admin.log")
    stage_mod = None
    stage_name = "%s-%d" % (PROJ_KEY, os.getpid())
    worker = None
    try:
        # ---------------- 相一：装配（缺件=ENV_FAIL exit 2，不假红） ----------------
        stage_mod, state = require_stage(fail, stage_name, TID)
        fixture_repo = make_fixture_repo(tmp)
        other_repo = make_fixture_repo(os.path.join(tmp, "other"))
        reg_dir = bench.write_registry(os.path.join(tmp, "registry"), PROJ_KEY, fixture_repo)
        bench.write_registry(reg_dir, OTHER_KEY, other_repo)
        # C1 探测条目：把引擎仓根本身注册成项目 dir——若实现只排除「cwd==仓根」等值，
        # cwd=仓内子目录会被 longest-prefix 误判成该 declared 项目（review C1 行为反转）。
        bench.write_registry(reg_dir, REPO_KEY, REPO)
        env = stage_env(state, reg_dir)
        # t260925-08：引擎缺省已翻 refuse（undeclared=拒收）。本场景锁的是 record 策略
        # 契约面（记名放行全族子用例），经旋钮显式选入——显式声明，非静默降级。
        env["SANDBAR_UNDECLARED_POLICY"] = "record"
        env["SANDBAR_ADMIN_LOG"] = admin_log
        stub_path = os.path.join(tmp, "ki061_stub.py")
        with open(stub_path, "w", encoding="utf-8") as f:
            f.write(
                "import json, re, sys\n"
                "prompt = sys.argv[-1] if len(sys.argv) > 1 else \"\"\n"
                "m = re.search(r'干完把结果写到 (\\S+?\\.json)', prompt)\n"
                "if m:\n"
                "    json.dump({'status': 'ok', 'summary': '[stub] done', "
                "'report': '[stub]', 'deliverables': [], "
                "'files_changed': ['docs/ticket-notes.md'], 'evidence': 'stub'}, "
                "open(m.group(1), 'w', encoding='utf-8'), ensure_ascii=False)\n")
        stub_log = os.path.join(tmp, "stub.jsonl")
        worker = spawn_worker(py, TID, env, os.path.join(tmp, "worker.log"), stub_path,
                              stub_log, disable_ki061=False, arb_verdict="pass")
        check(worker.poll() is None, "worker 已拉起 pid=%s" % worker.pid)
        # 建票走 undeclared（无 env、cwd=仓根=仓树内）——record 旋钮下放行（缺省
        # 已翻 refuse，t260925-08）；建票面闸的反用例在相三专门打。
        rc, out = run_poc_client(py, "ticket-start", {
            "ticket_id": TID, "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "t260915-12 跨项目写闸真链路面", "write_set": ["docs/"]}, env)
        check(rc == 0 and TID in out, "ticket-start 受理（rc=%s out尾=%s）" % (rc, out[-140:]))

        def _alive():
            s = query_snapshot(py, env, TID)
            return s if isinstance(s, dict) and s.get("ticket_id") == TID else None
        if poll(_alive, 120) is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            fail.bail("workflow snapshot 不可读（票未起或 worker 未认领），后续子用例全跑不真")
        snap0 = query_snapshot(py, env, TID)
        base_uses = len(cpu_uses(snap0))
        base_refused = len(refused_rows(snap0))
        base_paused = paused_flag(snap0)
        print("  · 基线：uses=%d refused=%d paused=%s" % (base_uses, base_refused, base_paused),
              flush=True)

        # ---------------- 相二：正用例 declared 同项目零影响 + 身份键 ----------------
        n0 = len(audit_rows(admin_log))
        env_p = env_with(env, "SANDBAR_CALLER_PROJECT", PROJ_KEY)
        rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO}, env_p)
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True,
              "同项目 pause 放行（rc=%s doc=%s）" % (rc, json.dumps(doc, ensure_ascii=False)[:160]))
        check(doc.get("caller_project") == PROJ_KEY and doc.get("identity_src") == "env",
              "回执身份键 caller_project/identity_src=env（%r/%r）"
              % (doc.get("caller_project"), doc.get("identity_src")))
        check(wait_paused(py, env, True), "pause 行为真生效（snapshot.paused=True）")
        rows = audit_rows(admin_log)[n0:]
        check(any(r.get("sub") == "ticket" and r.get("caller_project") == PROJ_KEY
                  and r.get("identity_src") == "env" for r in rows),
              "admin.log 行带身份键（caller_project/identity_src）")
        rc, out = client(py, "ticket", {"op": "resume", "id": TID, "who": WHO}, env_p)
        check(rc == 0 and receipt(out).get("ok") is True, "同项目 resume 放行")
        check(wait_paused(py, env, False), "resume 行为真生效（paused=False）")

        # ---------------- 相三：反用例 declared 不匹配 fail-closed（ruling/sign/ticket-start） ----------------
        env_o = env_with(env, "SANDBAR_CALLER_PROJECT", OTHER_KEY)
        n0 = len(audit_rows(admin_log))
        rc, out = client(py, "ticket", {"op": "ruling", "id": TID, "who": WHO,
                                        "note": "相三反用例：他项目身份不得注入裁决"}, env_o)
        doc = receipt(out)
        check(doc.get("ok") is False, "他项目 ruling 拒收（doc=%s）"
              % json.dumps(doc, ensure_ascii=False)[:160])
        check(doc.get("kind") == "cross_project_refused",
              "拒收 kind=cross_project_refused（%r）" % doc.get("kind"))
        err = str(doc.get("error") or "")
        check(OTHER_KEY in err and PROJ_KEY in err and TID in err,
              "人话点名谁动谁的票（双项目键+票号在场）：%s" % err[:180])
        rc2, out2 = client(py, "ticket", {"op": "sign", "id": TID, "who": WHO,
                                          "gate": "approve"}, env_o)
        doc2 = receipt(out2)
        check(doc2.get("ok") is False and doc2.get("kind") == "cross_project_refused",
              "他项目 sign 同形状拒收（kind=%r）" % doc2.get("kind"))
        rc3, out3 = run_poc_client(py, "ticket-start", {
            "ticket_id": "t26091512b-x", "template_id": "dev-lane", "project": PROJ_KEY,
            "title": "相三反用例：他项目建票"}, env_o)
        doc3 = receipt(out3)
        check(doc3.get("ok") is False and doc3.get("kind") == "cross_project_refused",
              "他项目 ticket-start 建他项目票拒收（kind=%r）" % doc3.get("kind"))
        rows = audit_rows(admin_log)[n0:]
        check(len(rows) >= 3 and all(r.get("override") is False for r in rows
                                     if r.get("sub") in ("ticket", "ticket-start")),
              "admin.log 三笔拒收均记行且 override=false（%d 行）" % len(rows))
        s = query_snapshot(py, env, TID)
        check(len(refused_rows(s)) == base_refused,
              "拒收在 client 侧截住（信号不出手，snapshot.refused 零新增）")
        check(len(cpu_uses(s)) == base_uses, "拒收不记名（越权对账面不进）")

        # ---------------- 相四：出处优先级 显式参数 > env ----------------
        env_mixed = env_with(env, "SANDBAR_CALLER_PROJECT", OTHER_KEY)
        rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO,
                                        "caller_project": PROJ_KEY}, env_mixed)
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True and doc.get("identity_src") == "arg",
              "显式参数压过 env（identity_src=arg，本票项目放行）")
        check(wait_paused(py, env, True), "arg 子用例 pause 生效")
        rc, out = client(py, "ticket", {"op": "resume", "id": TID, "who": WHO}, env_p)
        check(rc == 0 and receipt(out).get("ok") is True, "arg 子用例 resume 放行")
        check(wait_paused(py, env, False), "arg 子用例状态可逆")
        rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO,
                                        "caller_project": OTHER_KEY},
                         env_with(env, "SANDBAR_CALLER_PROJECT", PROJ_KEY))
        doc = receipt(out)
        check(doc.get("ok") is False and doc.get("kind") == "cross_project_refused"
              and doc.get("identity_src") == "arg",
              "参数显式他项目照样拒（arg 优先，env 不能救命）")

        # ---------------- 相五：越权旗 → 放行+记名+可对账（工单 ③） ----------------
        by = "宿主"
        reason = "t260915-12 场景：宿主本人跨项目处置（越权旗子用例）"
        n0 = len(audit_rows(admin_log))
        rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO,
                                        "cross_project": {"by": by, "reason": reason}},
                         env_o)
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True and doc.get("cross_project_used") is True,
              "越权旗放行（cross_project_used=true，doc=%s）"
              % json.dumps(doc, ensure_ascii=False)[:160])

        def _uses1():
            s = query_snapshot(py, env, TID)
            return s if len(cpu_uses(s)) == base_uses + 1 else None
        s = poll(_uses1, 90)
        if s is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            s = query_snapshot(py, env, TID)
            fail.bail("越权旗记名未落账（uses=%d）——stamp 未送达或第二道未接线（C5 面）"
                      % len(cpu_uses(s)))
        it = cpu_uses(s)[-1]
        check(it.get("by") == by and str(it.get("reason") or "") == reason,
              "记名条目带 by/reason 原文（%s）" % json.dumps(it, ensure_ascii=False)[:200])
        rows = audit_rows(admin_log)[n0:]
        check(any(r.get("override") is True for r in rows), "admin.log override=true 行在")
        check(wait_paused(py, env, True), "旗放行 pause 真生效")
        rc, out = client(py, "ticket", {"op": "resume", "id": TID, "who": WHO}, env_p)
        check(rc == 0 and receipt(out).get("ok") is True, "旗子用例后 resume 放行")
        check(wait_paused(py, env, False), "旗子用例后 resume 复位")
        # 第二笔：重发=按笔记名（对账口径以笔计）
        rc, out = client(py, "ticket", {"op": "ruling", "id": TID, "who": WHO,
                                        "note": "相五第二笔：旗放行裁决注入",
                                        "cross_project": {"by": by, "reason": reason}},
                         env_o)
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True and doc.get("cross_project_used") is True,
              "第二笔旗放行（ruling 载体）")

        def _uses2():
            s = query_snapshot(py, env, TID)
            return s if len(cpu_uses(s)) == base_uses + 2 else None
        s = poll(_uses2, 90)
        check(s is not None, "重发按第二笔记名（uses=%d）"
              % len(cpu_uses(query_snapshot(py, env, TID))))
        # 用户对账出口：ticket.py show 能列出越权旗使用记录
        rc, out = cli_ticket(py, env, {"op": "show", "id": TID})
        check(rc == 0 and "cross_project_uses" in out and by in out,
              "ticket.py show 出口可对账（cross_project_uses+by 可见）")

        # ---------------- 相六：畸形旗 fail-closed（旗本身不可缺部件） ----------------
        for bad, label in (({"by": by}, "旗缺 reason"),
                           ({"reason": reason}, "旗缺 by"),
                           ({"by": by, "reason": "   "}, "旗 reason 空白")):
            rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO,
                                            "cross_project": bad}, env_o)
            doc = receipt(out)
            err = str(doc.get("error") or "")
            check(doc.get("ok") is False and ("越权旗" in err or ("by" in err and "reason" in err)),
                  "%s 拒收且人话点名（%s）" % (label, err[:120]))
        s = query_snapshot(py, env, TID)
        check(len(cpu_uses(s)) == base_uses + 2, "畸形旗不记名不放行")

        # ---------------- 相七：undeclared B 策略（现状契约：放行+强制记名） ----------------
        n0 = len(audit_rows(admin_log))
        rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO}, env)
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True, "undeclared 放行（B 策略）")
        check(doc.get("identity_class") == "undeclared",
              "回执 identity_class=undeclared（%r）" % doc.get("identity_class"))
        check(bool(str(doc.get("cross_project_notice") or "").strip()),
              "回执带 cross_project_notice 人话（记名指引在场）")
        rows = audit_rows(admin_log)[n0:]
        check(any(r.get("identity_class") == "undeclared" for r in rows),
              "admin.log 行 identity_class=undeclared")

        def _uses3():
            s = query_snapshot(py, env, TID)
            return s if len(cpu_uses(s)) == base_uses + 3 else None
        s = poll(_uses3, 90)
        check(s is not None, "undeclared 记名入越权对账面（uses=%d，方案判定矩阵第 4 行承诺）"
              % len(cpu_uses(query_snapshot(py, env, TID))))
        check(wait_paused(py, env, True), "undeclared pause 生效")
        rc, out = client(py, "ticket", {"op": "resume", "id": TID, "who": WHO}, env_p)
        check(rc == 0 and receipt(out).get("ok") is True, "undeclared 子用例 resume 放行")
        check(wait_paused(py, env, False), "undeclared 子用例状态可逆")

        # ---------------- 相八：cwd 兜底两形（C1 探测器 + 正形） ----------------
        # 实现段勘误（t260915-12 implement）：本相第一条子用例（仓内子目录 undeclared pause）
        # 按 B 策略契约照常**记名 +1**——相九/相十的 uses 计数基线据此从 base+3 起算
        # （原稿按 base+3 钉相九/相十，漏计这一笔，属场景计数漂移非实现偏差）。
        rc, out = client(py, "ticket", {"op": "pause", "id": TID, "who": WHO},
                         env, cwd=ENGINE_SUBDIR)
        doc = receipt(out)
        check(doc.get("identity_class") == "undeclared" and not doc.get("caller_project"),
              "仓内子目录 cwd 必须 undeclared（C1 检测器：若误判 declared=%r 即行为反转红）"
              % doc.get("caller_project"))
        rc, out = client(py, "ticket", {"op": "resume", "id": TID, "who": WHO},
                         env, cwd=os.path.join(tmp, FIXTURE_REPO_DIR))
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True and doc.get("identity_src") == "cwd"
              and doc.get("caller_project") == PROJ_KEY,
              "cwd 在注册项目 dir 内=推导 declared（identity_src=cwd，%r/%r）"
              % (doc.get("caller_project"), doc.get("identity_src")))
        check(wait_paused(py, env, False), "cwd 正形子用例 resume 生效")

        # ---------------- 相九：workflow 第二道直发 SDK（C5 真 stamp 解码） ----------------
        rc, out = direct_pause_stamp(py, state, TID, WHO, "相九：直发他项目章无旗",
                                     OTHER_KEY, "")
        check(rc == 0, "直发信号投递成功（rc=%s %s）" % (rc, out[-100:]))

        def _ref1():
            s = query_snapshot(py, env, TID)
            hits = [r for r in refused_rows(s)[base_refused:]
                    if OTHER_KEY in str(r.get("why") or "")]
            return s if hits else None
        s = poll(_ref1, 90)
        if s is None:
            wait_worker_alive(fail, worker, os.path.join(tmp, "worker.log"))
            fail.bail("第二道未拒（refused 无跨项目点名）——stamp 解码丢失（KI-080 形态）"
                      "或 handler 未接闸")
        check(paused_flag(s) is False, "第二道拒收不执行（paused 不变）")
        check(len(cpu_uses(s)) == base_uses + 4, "第二道拒收不记名（基线含相八 undeclared 记名笔）")
        rc, out = direct_pause_stamp(py, state, TID, WHO, "相九：直发他项目章带旗",
                                     OTHER_KEY, "相九越权旗理由（直发 SDK 送达子用例）")

        def _uses4():
            s = query_snapshot(py, env, TID)
            return s if len(cpu_uses(s)) == base_uses + 5 and paused_flag(s) else None
        s = poll(_uses4, 90)
        check(s is not None, "带头旗直发=记名放行且 pause 生效（uses=%d paused=%s）"
              % (len(cpu_uses(query_snapshot(py, env, TID))),
                 paused_flag(query_snapshot(py, env, TID))))
        # 兼容子用例须在未暂停态发（paused 时会被「重复 pause」拒收掩护，验不到无章面）
        rc, out = client(py, "ticket", {"op": "resume", "id": TID, "who": WHO}, env_p)
        check(rc == 0 and receipt(out).get("ok") is True, "兼容子用例前 resume 放行")
        check(wait_paused(py, env, False), "兼容子用例前复位（paused=False）")
        rc, out = direct_pause_stamp(py, state, TID, WHO, "相九：无章兼容子用例", None, None)

        def _compat():
            s = query_snapshot(py, env, TID)
            hits = [r for r in refused_rows(s)[base_refused:]
                    if "相九：无章" in str(r.get("why") or "")]
            return (s, hits) if paused_flag(s) or hits else None
        got = poll(_compat, 90)
        check(got is not None and not got[1],
              "无盖章兼容不校验（老 client 等价形态：pause 照常生效，不误拒不误记）")

        # ---------------- 相十：retry_qc 不盖章残留诚实（方案 §8） ----------------
        n0 = len(audit_rows(admin_log))
        rc, out = client(py, "ticket", {"op": "retry_qc", "id": TID, "who": WHO,
                                        "cross_project": {"by": by, "reason": reason}},
                         env_o)
        doc = receipt(out)
        check(rc == 0 and doc.get("ok") is True,
              "retry_qc 越权旗 client 侧放行（doc=%s）" % json.dumps(doc, ensure_ascii=False)[:140])
        rows = audit_rows(admin_log)[n0:]
        check(any(r.get("override") is True for r in rows), "retry_qc 旗行 override=true 在册")
        s = query_snapshot(py, env, TID)
        check(len(cpu_uses(s)) == base_uses + 5,
              "retry_qc 记名不增（§8 残留钉住：Temporal 历史无该 op 身份，非漏记；基线含相八记名笔）")

        # ---------------- 相十一：读面零闸 + cancel 过闸 ----------------
        rc, out = client(py, "ticket", {"op": "query", "ticket_id": TID}, env_o)
        check(rc == 0 and receipt(out).get("ok") is True, "读面零闸（他项目身份 query 放行）")
        n0 = len(audit_rows(admin_log))
        rc, out = run_poc_client(py, "cancel", {"workflow_id": TID, "reason": "相十一反用例"},
                                 env_o)
        doc = receipt(out)
        check(doc.get("ok") is False and doc.get("kind") == "cross_project_refused",
              "他项目 cancel 带票 workflow 拒收（kind=%r）" % doc.get("kind"))
        rows = audit_rows(admin_log)[n0:]
        check(any(r.get("override") is False for r in rows), "cancel 拒收 admin.log 行在")
        rc, out = run_poc_client(py, "cancel",
                                 {"workflow_id": TID, "reason": "相十一正用例收尾"},
                                 env_with(env, "SANDBAR_CALLER_PROJECT", PROJ_KEY))
        doc = receipt(out)
        # terminated 是业务结果字段：在 result 内层（README §8.1 既有契约 {ok, result}——
        # 外层只放本票新增的闸身份键，业务字段层级不变。实现段勘误：原稿误在顶层读）。
        check(rc == 0 and doc.get("ok") is True
              and (doc.get("result") or {}).get("terminated") is True,
              "同项目 cancel 放行（terminate 收尾，doc=%s）"
              % json.dumps(doc, ensure_ascii=False)[:120])
    finally:
        # 资源回收三终态：worker 进程组、舞台、tmp（各自幂等，失败点名不抛）
        kill_worker_tree(worker)
        if stage_mod is not None:
            try:
                r = stage_down(stage_mod, stage_name)
                residue = (r or {}).get("residue")
                check(not residue, "拆台零残留（residue=%r）" % residue)
            except Exception as e:  # noqa: BLE001
                check(False, "拆台失败（须人查 docker 台）：%s" % e)
        cleanup_tmp(tmp)

    print("SC sc_cross_project_gate_realchain pass=%d fail=%d (exit=%d)"
          % (STATS["ok"], STATS["fail"], 0 if not fail.fails else 1), flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
