#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-06 场景：KI-067 工单操作入口收口（灰盒 L2/L3）。

intent（用户可感知契约，按工单钦点场景逐条 + 无差别审计/entry_hint 故障面）：
- 静默失败根治：正规入口 ticket.py 任何 op 失败 = 非零退出 + stdout 结构化
  {ok:false,error}（绝不空输出——260910 两次实证的病灶形态：空输出+退出 0+无审计）；
  无参/畸形 argsJSON/-h 同样非零（本 CLI 无交互面，防「空跑被上游当成功」）；
- 无差别自审计：client.py 每次调用无论来源都记 admin.log（含被拒收子命令、
  argsJSON 非法、连接失败、-h——拒收不记录=盲区仍在，KI-067 本体）；source 记
  env SANDBAR_CLIENT_ENTRY 原值（缺省字面量 bare）；
- 回执嵌提醒：裸入口回执（含成功与失败回执）附 entry_hint；env 精确等值 'ticket'
  （ticket.py 转发自报家门）则安静；其余任意值（'ticket.py'/'1'/空串）一律不获
  静默——静默待遇仅由代码路径的精确值触发；参数面注入（args 塞 source 同名字段）
  不影响标记。口径：claimed-source 非身份鉴别（宿主 260910 裁非安全语义）；
- 双行审计契约：ticket.py 直调一次 = admin.log 两行（source=ticket.py-direct 与
  source=ticket）且 call_id 一致（关联键）；有意双行，不是重复记 bug；
- sign/retry_qc 包进正规入口（who 仍由调用方注入，包装层只加审计不加权力）：
  retry_qc 贴 workflow 裸串契约——timeline reason 以 who 开头且无 dict 乱码
  （{who,note} 误转发即现形）；note 非空在 CLI 层显式拒收点名 note；sign 通道
  可达（delivered=true）且 Signature payload 形状落 workflow 可观测面
  （fresh 票非人门 → refused 条目 want 含 sign、who 原样——refused 是文档化
  回执面，同 pause KI-061 族）；人门签字接受面属 workflow 门逻辑（developer L1
  覆盖），本场景不重复。

与相邻场景 intent 分界：t260910-03 守正规入口多仓派生+双保险丝（create 链），
本场景守「入口收口」面（退出码/审计/entry_hint/sign/retry_qc 包装），不重叠；
t260908-01 守 pause/retry_qc 的 workflow 幂等与唤醒语义，本场景只守 CLI 包装与
审计/提醒面，不重复彼处 workflow 侧语义。

环境口径（三态契约 t260904-12：PASS/FAIL/ENV_FAIL 三态判定，无跳过语义）：A 段（stdlib）系统 python3 直跑
恒跑；temporalio 缺失 = B/C 段 ENV_FAIL exit 2 点名；docker/bench/隔离台库缺席
= C 段 ENV_FAIL 点名（A/B 照跑）。全部子用例 N/A 不可能出现（A 段无条件跑）。
红线：一切被测子进程的 Temporal 地址显式指不可达桩（127.0.0.1:9）或一次性
隔离台 namespace，绝不触生产 7233/8233/3099；审计观察走 env SANDBAR_ADMIN_LOG
覆盖的 tmp 文件，不污染仓内真 admin.log。
TDD：implement 落地前本场景红属预期（此刻 ticket.py 直调=空输出退出 0，正是
KI-067 病灶形状，A 段红即信号）；arbitrate/merge 期必须绿。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"
TICKET_PY = REPO / "server" / "tools" / "ticket.py"
INTEG = REPO / "integration"

# 红线：先于一切引擎面 import/spawn 钉死不可达桩（shared.py/client.py 模块级读 env）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)

sys.path.insert(0, str(INTEG))
sys.path.insert(0, str(INTEG / "t260904-02"))

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d" % (passed, failed, env_fail_n))
    return 1 if failed else (2 if env_fail_n else 0)


def stub_env(extra=None):
    """桩段被测子进程环境：不可达桩 + 审计落 tmp（契约 env 名：SANDBAR_ADMIN_LOG）。"""
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
    env.pop("SANDBAR_NAMESPACE", None)
    if extra:
        env.update(extra)
    return env


def run_py(py, script, args_json, extra_env=None, timeout=180):
    """spawn <py> <script> '<json>'（ticket.py 与 client.py 同构首参 JSON 口径）。"""
    env = stub_env(extra_env)
    p = subprocess.run([py, str(script), args_json], env=env, cwd=str(REPO),
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "")


def parse_out_json(out):
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return {}


def read_audit(path):
    """读审计 JSONL（不存在/坏行容错，坏行保 _raw 不静默丢）。"""
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    rows.append({"_raw": ln})
    return rows


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


tmp = tempfile.mkdtemp(prefix="t260910-06-audit-")
AUDIT_LOG = os.path.join(tmp, "admin-audit.jsonl")
AUDIT_ENV = {"SANDBAR_ADMIN_LOG": AUDIT_LOG}

# ============ A 段（stdlib，恒跑）：正规入口退出码/结构化错误面 ============
print("---- A 段：ticket.py 直调（stdlib 面，无 Temporal 依赖） ----")

# A1 钦点④：create 缺 project → 非零退出 + 结构化错误（绝不空输出）
rc, out = run_py(sys.executable, TICKET_PY, json.dumps({"op": "create", "title": "x"}))
receipt = parse_out_json(out)
check("A1 create 缺 project：非零退出+结构化错误（绝不空输出）",
      rc != 0 and receipt.get("ok") is False and str(receipt.get("error") or "").strip(),
      "rc=%r stdout前200=%r（空输出+退出0=KI-067 病灶形状）" % (rc, (out or "")[:200]))

# A2 无参 → 非零；畸形 argsJSON → 非零 + 结构化
p = subprocess.run([sys.executable, str(TICKET_PY)], env=stub_env(AUDIT_ENV),
                   cwd=str(REPO), capture_output=True, text=True, timeout=60)
check("A2a ticket.py 无参：非零退出（防空跑当成功）",
      p.returncode != 0, "rc=%r" % p.returncode)
rc, out = run_py(sys.executable, TICKET_PY, "{not-json")
receipt = parse_out_json(out)
check("A2b 畸形 argsJSON：非零退出+结构化错误",
      rc != 0 and receipt.get("ok") is False and receipt.get("error"),
      "rc=%r out=%r" % (rc, (out or "")[:200]))

# A3 retry_qc note 非空 → CLI 层显式拒收点名 note（连接前，stdlib 可验）
rc, out = run_py(sys.executable, TICKET_PY,
                 json.dumps({"op": "retry_qc", "id": "t-x", "who": "ut",
                             "note": "带话"}))
receipt = parse_out_json(out)
check("A3 retry_qc note 非空：显式拒收（非零+点名 note，不静默蒸发）",
      rc != 0 and receipt.get("ok") is False and "note" in str(receipt.get("error") or ""),
      "rc=%r out=%r" % (rc, (out or "")[:200]))

# A4 -h → 非零（防误用契约：本 CLI 无交互面）
p = subprocess.run([sys.executable, str(TICKET_PY), "-h"], env=stub_env(AUDIT_ENV),
                   cwd=str(REPO), capture_output=True, text=True, timeout=60)
check("A4 ticket.py -h：非零退出（用法输出在，退出码非 0）",
      p.returncode != 0 and ("op" in (p.stdout or "") or "用法" in (p.stdout or "")),
      "rc=%r out=%r" % (p.returncode, (p.stdout or "")[:120]))

# ============ B 段（temporalio+不可达桩）：无差别审计 + entry_hint 面 ============
print("---- B 段：client.py 无差别审计/entry_hint（不可达桩，拒收也记） ----")
if not temporalio_available():
    env_fail("temporalio 缺失——B 段（client.py 回执/审计真进程子用例）与 C 段（隔离台子用例）"
             "全靠真链路，无 stdlib 替代；A 段 stdlib 子用例已照跑")
else:
    n0 = len(read_audit(AUDIT_LOG))

    # B1 钦点①骨架：裸入口回执带 entry_hint + admin.log 有痕（连接失败也记——
    # 无差别审计的精髓：拒收/失败不记=盲区）
    n0 = len(read_audit(AUDIT_LOG))
    p = subprocess.run([sys.executable, str(POC / "client.py"), "ticket-list",
                        json.dumps({})], env=stub_env(AUDIT_ENV), cwd=str(REPO),
                       capture_output=True, text=True, timeout=180)
    rc, out = p.returncode, (p.stdout or "")
    receipt = parse_out_json(out)
    rows = read_audit(AUDIT_LOG)[n0:]
    check("B1 裸入口回执带 entry_hint + admin.log 有痕（连接失败也记）",
          rc == 0 and receipt.get("ok") is False and receipt.get("entry_hint")
          and any(r.get("source") == "bare" and r.get("ok") is False
                  for r in rows if not r.get("_raw")),
          "rc=%r hint=%r 新审计行=%r" % (rc, receipt.get("entry_hint"),
                                        [r.get("source") for r in rows]))

    # B2 钦点②+⑤env 面：精确 'ticket' 才安静；任意值不获静默且 source 记原值
    n_b2 = len(read_audit(AUDIT_LOG))
    p = subprocess.run([sys.executable, str(POC / "client.py"), "ticket-list",
                        json.dumps({})],
                       env=stub_env(dict(AUDIT_ENV,
                                         SANDBAR_CLIENT_ENTRY="ticket")),
                       cwd=str(REPO), capture_output=True, text=True, timeout=180)
    receipt_t = parse_out_json(p.stdout or "")
    rows_ticket = [r for r in read_audit(AUDIT_LOG)[n_b2:]
                   if r.get("source") == "ticket"]
    check("B2a env 精确 'ticket'：回执安静（无 entry_hint）",
          receipt_t.get("ok") is False and "entry_hint" not in receipt_t
          and rows_ticket,
          "hint=%r ticket行数=%d" % (receipt_t.get("entry_hint"), len(rows_ticket)))

    p = subprocess.run([sys.executable, str(POC / "client.py"), "ticket-list",
                        json.dumps({})],
                       env=stub_env(dict(AUDIT_ENV,
                                         SANDBAR_CLIENT_ENTRY="ticket.py")),
                       cwd=str(REPO), capture_output=True, text=True, timeout=180)
    receipt_e = parse_out_json(p.stdout or "")
    all_rows = read_audit(AUDIT_LOG)
    row_e = [r for r in all_rows if r.get("source") == "ticket.py"]
    check("B2b env 任意值 'ticket.py'：回执仍带 hint + source 记原值（claimed-source）",
          "entry_hint" in receipt_e and bool(row_e),
          "hint在=%s 原值行数=%d" % ("entry_hint" in receipt_e, len(row_e)))

    # B3 钦点⑤参数面：args 塞 source 同名字段——标记不受参数污染
    p = subprocess.run([sys.executable, str(POC / "client.py"), "ticket-list",
                        json.dumps({"source": "ticket"})],
                       env=stub_env(AUDIT_ENV), cwd=str(REPO),
                       capture_output=True, text=True, timeout=180)
    receipt_a = parse_out_json(p.stdout or "")
    check("B3 参数面注入 source 字段：不获静默（hint 仍在）",
          "entry_hint" in receipt_a, "hint=%r" % receipt_a.get("entry_hint"))

    # B4 无差别审计：被拒收调用（未知子命令）也记
    n_before = len(read_audit(AUDIT_LOG))
    p = subprocess.run([sys.executable, str(POC / "client.py"), "no-such-sub"],
                       env=stub_env(AUDIT_ENV), cwd=str(REPO),
                       capture_output=True, text=True, timeout=60)
    new_rows = read_audit(AUDIT_LOG)[n_before:]
    check("B4 被拒收调用（未知子命令）admin.log 也有痕",
          p.returncode == 0 and parse_out_json(p.stdout or "").get("ok") is False
          and len(new_rows) >= 1,
          "rc=%r 新行数=%d" % (p.returncode, len(new_rows)))

    # B5 钦点③审计面：正规入口直调（桩上连接失败）→ 非零退出+结构化错误+
    # admin.log 双行（ticket.py-direct 与 ticket）call_id 一致（双行契约+关联键）
    n_before = len(read_audit(AUDIT_LOG))
    rc, out = run_py(sys.executable, TICKET_PY,
                     json.dumps({"op": "sign", "id": "t-stub", "by": "ut-integ"}),
                     extra_env=AUDIT_ENV)
    receipt = parse_out_json(out)
    new_rows = [r for r in read_audit(AUDIT_LOG)[n_before:] if not r.get("_raw")]
    by_call = {}
    for r in new_rows:
        cid = r.get("call_id")
        if cid:
            by_call.setdefault(cid, set()).add(r.get("source"))
    paired = [c for c, srcs in by_call.items()
              if {"ticket.py-direct", "ticket"} <= set(srcs or set())]
    check("B5 正规入口 sign（桩）：非零退出+结构化错误+双行审计 call_id 关联",
          rc != 0 and receipt.get("ok") is False and paired,
          "rc=%r 双行组=%r 全行source=%r" % (rc, paired,
                                            [r.get("source") for r in new_rows]))

# ============ C 段（docker 隔离台，真票真链路）：sign/retry_qc 包装面 ============
print("---- C 段：隔离台真票 sign/retry_qc（一次性 namespace，跑完即拆） ----")
bench = None
stage_mod = None
stage = None
worker = None
stage_project = "t26091006-ki067-%d" % os.getpid()
try:
    from lib_gate import accepted, require_bench, require_stage, stage_down  # noqa: E402

    class _Fail:
        def check(self, cond, msg):
            check(msg, cond)
        def bail(self, msg, code=2):
            env_fail(msg)
            sys.exit(code)

    if not temporalio_available():
        env_fail("temporalio 缺失——C 段真票子用例无法跑（B/A 子用例已照跑）")
    else:
        bench = require_bench(_Fail())
        stage_mod, stage = require_stage(_Fail(), stage_project,
                                         "stage-ki067-%d" % os.getpid())
        fe = int(stage["ports"]["temporal"])
        py = str(POC / ".venv" / "bin" / "python")
        if not os.path.isfile(py):
            py = sys.executable

        # 夹具：项目注册表（KI-032 锚定闸消费面）+ fixture 仓（骨架抄 t260908-01）
        import time as _time
        regdir = Path(tmp) / "reg"
        repo = Path(tmp) / "fixture-repo"
        repo.mkdir(parents=True)
        def _g(*a):
            subprocess.run(["git", "-C", str(repo)] + list(a), check=True,
                           capture_output=True, text=True)
        _g("init", "-q", "-b", "main")
        _g("config", "user.name", "fixture")
        _g("config", "user.email", "fixture@example.com")
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        _g("add", "-A")
        _g("commit", "-qm", "init")
        regdir.mkdir(parents=True)
        (regdir / "ki067").mkdir()
        (regdir / "ki067" / "project.yaml").write_text(
            "schema: v1\nproject:\n  - key: ki067\n    name: KI067 入口收口\n"
            "    dirs:\n      - %s\n" % repo, encoding="utf-8")

        stage_env_ = dict(os.environ)
        stage_env_["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % fe
        stage_env_["SANDBAR_NAMESPACE"] = stage["namespace"]
        stage_env_["SANDBAR_PROJECTS_DIR"] = str(regdir)
        # 260927（KI-142）：一处声明调用方身份（后面 retry_qc / sign 也是 gated 写）。
        stage_env_["SANDBAR_CALLER_PROJECT"] = "ki067"
        stage_env_.update(AUDIT_ENV)

        # C0 建真票（dev-lane；无 worker 时真 workflow 的 query 会挂起到超时——
        # fixture_ticket_fake 头注释实证的引擎面行为——故起专属 worker + 挂起桩
        # agent：桩永不退出 → activity 永挂 → 票停在 create_plan 段，workflow
        # 任务可应答 query/signal。贴真 workflow 契约，不复制信号面。）
        TID = "t26091006ki067"
        p = subprocess.run([py, str(POC / "client.py"), "ticket-start",
                            json.dumps({"ticket_id": TID, "template_id": "dev-lane",
                                        "project": "ki067",
                                        "title": "KI-067 入口收口台面子用例",
                                        "write_set": ["docs/"]})],
                           env=stage_env_, cwd=str(REPO),
                           capture_output=True, text=True, timeout=180)
        _c0_ok, _c0_why = accepted(p.stdout or "", TID)   # 260927（KI-142）：受理只认 ok=true
        check("C0 隔离台建真票（正规 project 锚过闸）",
              p.returncode == 0 and _c0_ok,
              "rc=%r 受理=%s out尾=%r" % (p.returncode, _c0_why, (p.stdout or "")[-160:]))

        # 挂起桩 agent：prompt 恒末位（引擎 spawn 契约，同 lib_ki061 桩先例）；
        # 桩读到位即长眠——activity 不完成，票恒停在首个 agent 段。
        stub_path = Path(tmp) / "ki067_park_stub.py"
        stub_path.write_text("import sys, time\nsys.argv and time.sleep(3600)\n",
                             encoding="utf-8")
        wenv = dict(stage_env_)
        wenv["SANDBAR_TASK_QUEUES"] = "sandbar-ticket-%s,suyou-ticket-%s" % (TID, TID)  # naming-compat（t260907-04 旧队列前缀双 poll 契约，lib_ki061 同款）
        wenv["SANDBAR_AGENT_CMD"] = "%s %s" % (py, stub_path)
        wlog = open(Path(tmp) / "worker.log", "ab")
        worker = subprocess.Popen([py, str(POC / "worker.py")], env=wenv,
                                  cwd=str(POC), stdout=wlog, stderr=subprocess.STDOUT)
        try:
            worker.wait(timeout=3)
            env_fail("ticket worker 提前退出（rc=%s，日志尾=%r）——C 段真票子用例无法跑"
                     % (worker.returncode, (Path(tmp) / "worker.log").read_text()[-300:]))
        except subprocess.TimeoutExpired:
            pass  # 3s 仍存活=worker 正常拉起

        def query_snapshot():
            """snapshot 查询走官方公开通道（client.py ticket op=query，读
            result.snapshot——同 lib_ki061 已实证口径；裸 gRPC query 在容器台
            上 h2/超时不稳，官方通道即被测契约本身）。"""
            r = subprocess.run([py, str(POC / "client.py"), "ticket",
                                json.dumps({"op": "query", "ticket_id": TID})],
                               env=stage_env_, cwd=str(REPO),
                               capture_output=True, text=True, timeout=120)
            out = (r.stdout or "")
            i, j = out.find("{"), out.rfind("}")
            if i < 0 or j <= i:
                return {"_err": "无 JSON（rc=%s out=%r stderr=%r）"
                        % (r.returncode, out[:120], (r.stderr or "")[-160:])}
            try:
                whole = json.loads(out[i:j + 1])
            except Exception as e:
                return {"_err": "JSON 解析失败：%s out=%r" % (e, out[:160])}
            if not whole.get("ok"):
                return {"_err": "query 回执 not ok：%s" % json.dumps(
                    whole, ensure_ascii=False)[:200]}
            return (whole.get("result") or {}).get("snapshot") or {
                "_err": "result.snapshot 缺（result=%r)" % (whole.get("result"),)}

        def poll_snap(pred, timeout_s=90):
            deadline = _time.time() + timeout_s
            while _time.time() < deadline:
                s = query_snapshot()
                if s and not s.get("_err") and pred(s):
                    return s
                _time.sleep(3)
            return query_snapshot()

        snap0 = poll_snap(lambda s: s.get("ticket_id") == TID or s.get("stage"),
                          timeout_s=240)
        check("C0b 真票 snapshot 可查（worker 在场，票停 create_plan 段）",
              bool(snap0) and not snap0.get("_err")
              and (snap0.get("stage") or "") == "create_plan",
              "snapshot=%r worker存活=%s" % (json.dumps(snap0, ensure_ascii=False)[:220],
                                             worker.poll() is None))

        # C1 钦点④包装：正规入口 retry_qc → delivered + 裸串契约（timeline reason
        # 以 who 开头、无 dict 乱码）+ 幂等计数可观测
        n_before = len(read_audit(AUDIT_LOG))
        p = subprocess.run([py, str(TICKET_PY),
                            json.dumps({"op": "retry_qc", "id": TID,
                                        "by": "ut-integ"})],
                           env=stage_env_, cwd=str(REPO),
                           capture_output=True, text=True, timeout=180)
        r1 = parse_out_json(p.stdout or "")
        p2 = subprocess.run([py, str(TICKET_PY),
                             json.dumps({"op": "retry_qc", "id": TID,
                                         "by": "ut-integ"})],
                            env=stage_env_, cwd=str(REPO),
                            capture_output=True, text=True, timeout=180)
        r2 = parse_out_json(p2.stdout or "")
        snap1 = query_snapshot()
        dump1 = json.dumps(snap1, ensure_ascii=False)
        garbage = "'who'" in dump1  # dict 误转发进裸串形参的现形特征
        n_new = [r for r in read_audit(AUDIT_LOG)[n_before:] if not r.get("_raw")]
        by_call = {}
        for r in n_new:
            if r.get("call_id") and str(r.get("sub") or "").startswith("ticket"):
                by_call.setdefault(r["call_id"], set()).add(r.get("source"))
        paired = [c for c, s_ in by_call.items()
                  if {"ticket.py-direct", "ticket"} <= set(s_ or set())]
        check("C1 正规入口 retry_qc：delivered + timeline 以 who 记（裸串契约）+ 双行审计",
              p.returncode == 0 and r1.get("ok") and p2.returncode == 0
              and r2.get("ok")
              and "requests rerun" in dump1 and "ut-integ" in dump1 and not garbage
              and len(paired) >= 1,
              "rc=%r ok=%r garbage=%s 双行组=%d 全行=%r dump片=%r"
              % (p.returncode, r1.get("ok"), garbage, len(paired),
                 [(r.get("sub"), r.get("source")) for r in n_new], dump1[:200]))

        # C2 钦点③：正规入口 sign 可用（delivered）+ payload 形状落 workflow
        # 可观测面（fresh 票非人门 → refused 条目 want 含 sign、who 原样）
        # + admin.log 双行 call_id 关联
        n_before = len(read_audit(AUDIT_LOG))
        ref0 = len(snap1.get("refused") or [])
        p = subprocess.run([py, str(TICKET_PY),
                            json.dumps({"op": "sign", "id": TID,
                                        "by": "ut-signer"})],
                           env=stage_env_, cwd=str(REPO),
                           capture_output=True, text=True, timeout=180)
        rs = parse_out_json(p.stdout or "")
        snap2 = query_snapshot()
        refnew = (snap2.get("refused") or [])[ref0:]
        sign_ref = [r for r in refnew
                    if "sign" in str(r.get("want") or "")
                    and r.get("who") == "ut-signer"]
        n_new = [r for r in read_audit(AUDIT_LOG)[n_before:] if not r.get("_raw")]
        by_call = {}
        for r in n_new:
            if r.get("call_id") and str(r.get("sub") or "").startswith("ticket"):
                by_call.setdefault(r["call_id"], set()).add(r.get("source"))
        paired = [c for c, s_ in by_call.items()
                  if {"ticket.py-direct", "ticket"} <= set(s_ or set())]
        check("C2 正规入口 sign：delivered=true + payload 形状落 refused（who 原样）+ 双行审计",
              p.returncode == 0 and rs.get("ok") and bool(sign_ref) and bool(paired),
              "rc=%r ok=%r refused新增=%r 双行组=%d 全行=%r snap_err=%r"
              % (p.returncode, rs.get("ok"), refnew, len(paired),
                 [(r.get("sub"), r.get("source")) for r in n_new],
                 snap2.get("_err")))
finally:
    try:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
    except Exception:
        pass
    if stage_mod is not None:
        try:
            stage_down(stage_mod, stage_project)
        except Exception as e:
            print("拆台异常（不影响判定口径）: %s" % e)

sys.exit(summary())
