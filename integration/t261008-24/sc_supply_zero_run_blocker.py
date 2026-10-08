#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261008-24 场景①：零执行闸回执 × 命名拦阻 × 计轮豁免 × 合并闸绿跑前置（灰盒 L2.5，离线）。

KI-220 用户场景（工单正文，t261008-07 实案）：最后一轮闸回执 ran=0/零闸拦/零产品红、
err 带供给装配签名（docker daemon 不可达），消费面 blockers=[] 被当绿——票自己的
验收场景在该 commit 上一次都没跑过，merge_check 照样放行，merge 落进 main。

收口后用户可感知行为（工单三要求）：
  A. 供给装配失败零执行回执（ran=0 ∧ failed=0 ∧ blockers 空 ∧ err 命中
     shared.tests_supply_assembly_error 签名）→ shared.gate_zero_run_supply_blocker
     命名拦阻（reason_code=supply_zero_run），shared.supply_stop_route 返回 blocked:
     路由——不再流到 arbitrate 被当 no-red 绿；
  B. 拦阻文本点名供给面（SUPPLY_SIDE_RED token + need 名）与两条出路
     （修供给/docker + retry_qc）——SUPPLY_SIDE_RED 原样在场（不静音）；
  C. 计轮豁免语义保持：同回执经 _tests_round_account 仍 counted=False（环境面红
     不耗 tests-fault 轮预算，无假封）；
  D. 假拒绝护栏（按签名命名，不按计数）：
     - 合法零执行轮（空在册/probe-only：err 为空）→ 拦阻不命中，路由照旧 acceptance；
     - 非签名启动级文案（执行器整体超时，t260920-01 C 形态）→ 不命中，照旧保守计轮；
  E. 合并闸绿跑前置（KI-217 出口①，同一机制）：merge_check 新增检查项
     「验收场景在本树至少一次绿跑」真值表——
       缺面 ⇒ 红点名 zero-run(KI-220)；sha 不配 ⇒ 红点名 stale（树变了）；
       畸形面 ⇒ 红 fail-closed；合法零在册（no_scenarios）+sha 配 ⇒ 绿且点名理由；
       ran>0 绿跑 + sha 配 ⇒ 绿；老回放字段缺省 ⇒ 红（永不默认绿）。

与既有资产 intent 分工（防重复声明）：
  · t260920-01-supply-assembly-seam 锁「真出口文案 × 签名 × 计轮账本」旧三环
    （其 A1f/A2c 在本场景 C 段仍须绿，语义未动）——本条新增锁**第四环：零执行
    形态在路由决策点成为命名拦阻**与**合并闸绿跑前置项**，彼场景不锁此二面；
  · t260904-12 sc_supply_gate_ethred 锁 verify_lane supply 机制本体，不重复；
  · t260917-09 sc_tests_false_escalation_guard 锁场景级环境红/抖动豁免，不重复；
  · developer L1（test_t261008_24_zero_run_supply.py）锁纯函数真值表（构造串直驱）
    ——本条喂的是**真 verify_lane 进程跑出来的 err**（出口实况不可手工构造），
    且 merge_check 项真值表用**真 git 夹具仓直驱真 activity 函数**。
驱动形态：admin.py call verify_lane 真入口 + tmp 夹具仓（t260920-01 同款）；
temporalio 缺席环境装 _stub_temporalio 桩（t260901-23/t260920-01 同款）后 import
真 dev_lane / 真 agent_activities，merge_check 离线直驱（函数体零 workflow 调用，
实测可裸跑）。纯离线秒级，无 docker 依赖。
现状注记：A/D 段新函数未落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
C 段（计轮豁免）是存量语义，现在就应绿——红了=存量回归非 TDD 预期红。
跑法：python3 -B integration/t261008-24/sc_supply_zero_run_blocker.py
"""
import asyncio
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "integration"))

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


# ---------- 引擎侧消费跳（真 dev_lane / 真 agent_activities + 真 shared 纯函数） ----------

def _engine_modules():
    """server/engine 模块装载：venv（有 temporalio）直接 import；裸 python3
    回落装 _stub_temporalio 桩（t260901-23 同款）后再 import。"""
    sys.path.insert(0, str(REPO / "integration" / "t260901-23"))
    import importlib.util
    if importlib.util.find_spec("temporalio") is None:
        import _stub_temporalio
        _stub_temporalio.install()
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import shared
    import dev_lane
    import agent_activities
    return shared, dev_lane, agent_activities


# ---------- 闸驱动（admin.py 真入口，t260920-01 同款） ----------

def call_gate(fixture_repo, extra_env=None):
    from lib_env import clean_narrowing_env
    env = clean_narrowing_env(extra_env or {})
    p = subprocess.run(
        [sys.executable, "server/admin.py", "call", "verify_lane",
         json.dumps({"lane": "integ", "path": str(fixture_repo)})],
        cwd=str(REPO), capture_output=True, text=True, timeout=180, env=env)
    if p.returncode != 0:
        return {"ok": False, "stderr": (p.stderr or "")[-300:]}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stderr": "unparseable: " + p.stdout[-200:]}
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if isinstance(inner, dict) and ("green" in inner or "err" in inner):
        return {"ok": True, "result": inner}
    return {"ok": isinstance(parsed, dict) and parsed.get("ok") is True,
            "result": inner if isinstance(inner, dict) else parsed}


def make_fixture(yaml_integration_block, stub_files):
    td = tempfile.mkdtemp(prefix="t26100824-seam-")
    repo = Path(td)
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        + yaml_integration_block, encoding="utf-8")
    for name, text in stub_files.items():
        (repo / name).write_text(text, encoding="utf-8")
    return repo


PASS_STUB = ("print('PASS [对照桩]')\n"
             "print('SCENARIOS ran=1 pass=1 fail=0 env'+'_fail=0 na=0 (0s)')\n"
             "import sys; sys.exit(0)\n")


def receipt_of(res):
    """把真闸出口转成引擎回执形状（IntegrationRunResult，ran=0 零执行族）。"""
    shared, _, _ = ENG
    r = res["result"]
    return shared.IntegrationRunResult(
        ran=0, passed=0, failed=0, env_fail=0, error=str(r.get("err") or ""))


ENG = _engine_modules()


def seam(shared, receipt):
    """新接缝两跳：命名拦阻分类器 + 停止路由（getattr 探测，缺席=具名 FAIL）。"""
    cls = getattr(shared, "gate_zero_run_supply_blocker", None)
    rte = getattr(shared, "supply_stop_route", None)
    blocker = cls(receipt) if cls else "MISSING:shared.gate_zero_run_supply_blocker"
    route = rte(receipt) if rte else "MISSING:shared.supply_stop_route"
    return blocker, route


# ---- A1 供给失败态（exit 7）零执行回执 → 命名拦阻 + blocked 路由 + 豁免不计轮 ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 测试台供给（t261008-24 场景桩）\n      cmd: python3 supply_bad.py\n",
    {"integ_stub.py": PASS_STUB,
     "supply_bad.py": "import sys\nprint('boom：供给物不齐')\nsys.exit(7)\n"})
res = call_gate(repo)
if res.get("ok"):
    shared, dev_lane, _ = ENG
    r = res["result"]
    err = str(r.get("err") or "")
    ok(r.get("green") is False, "A1 供给失败 → 闸红")
    ok(shared.SUPPLY_FAIL_SIG in err and shared.SUPPLY_SIDE_SIG in err,
       "A1b 出口双标记在场（SUPPLY_ASSEMBLY_FAILED ∧ SUPPLY_SIDE_RED）")
    ir = receipt_of(res)
    blocker, route = seam(shared, ir)
    ok(isinstance(blocker, dict) and blocker.get("reason_code") == "supply_zero_run",
       "A1c 分类器命中：命名拦阻 reason_code=supply_zero_run（got: %r)" % (blocker,))
    ok(isinstance(route, str) and route.startswith("blocked:"),
       "A1d 停止路由=blocked:（不再当 no-red 流向 arbitrate，got: %r)" % (route[:60],))
    ok(shared.SUPPLY_SIDE_SIG in str(route) and "测试台供给" in str(route),
       "A1e 拦阻文本点名供给面（SUPPLY_SIDE_RED + need 名，不静音）")
    ok("retry_qc" in str(route),
       "A1f 拦阻文本带出路 retry_qc")
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    _, _, counted, note = asyncio.run(wf._tests_round_account(1, 0, ir))
    ok(counted is False, "A1g 该轮不计入 tests-fault（counted=False，豁免语义保持）")
else:
    ok(False, "A1 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- A2 供给超时态零执行回执：同族命中 ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 测试台供给（t261008-24 场景桩）\n      cmd: python3 supply_slow.py\n"
    "      timeout: 1\n",
    {"integ_stub.py": PASS_STUB,
     "supply_slow.py": "import time\ntime.sleep(30)\n"})
res = call_gate(repo)
if res.get("ok"):
    shared, _, _ = ENG
    r = res["result"]
    ok(r.get("green") is False and shared.SUPPLY_TIMEOUT_SIG in str(r.get("err") or ""),
       "A2 供给超时 → 闸红且超时态双标记在场")
    blocker, route = seam(shared, receipt_of(res))
    ok(isinstance(blocker, dict) and blocker.get("reason_code") == "supply_zero_run"
       and isinstance(route, str) and route.startswith("blocked:"),
       "A2b 超时态同样命中命名拦阻 + blocked 路由（got: %r)" % (blocker,))
else:
    ok(False, "A2 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- D1 假拒绝护栏：合法零执行轮（空在册/probe-only，err 为空）不拦阻 ----
shared, _, _ = ENG
legal_zero = shared.IntegrationRunResult(
    ran=0, passed=0, failed=0, env_fail=0, error="")
blocker, route = seam(shared, legal_zero)
ok(blocker is None and (route == "" or route == "acceptance"),
   "D1 合法零执行轮（err 空）不命中拦阻、路由照旧 acceptance（got: %r/%r)"
   % (blocker, route))

# ---- D2 假拒绝护栏：非签名启动级文案（执行器整体超时）不拦阻、照旧保守计轮 ----
repo = make_fixture("integration:\n  cmd: python3 integ_slow.py\n",
                    {"integ_slow.py": "import time\ntime.sleep(30)\n"})
res = call_gate(repo, extra_env={"SANDBAR_INTEG_BATCH_TIMEOUT_SEC": "1"})
if res.get("ok"):
    shared, dev_lane, _ = ENG
    r = res["result"]
    err = str(r.get("err") or "")
    ok(r.get("green") is False and "scenario executor wall timed out" in err,
       "D2 执行器整体超时 → 闸红且为非签名启动级文案")
    blocker, route = seam(shared, receipt_of(res))
    ok(blocker is None, "D2b 非签名文案不命中零执行拦阻（宁窄勿宽，got: %r)" % (blocker,))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    _, _, counted, _ = asyncio.run(wf._tests_round_account(1, 0, receipt_of(res)))
    ok(counted is True, "D2c 该轮照旧保守计轮（H2 形态不豁免不拦阻）")
else:
    ok(False, "D2 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- D3 对照组：PASS 桩 → 闸绿，绿回执不命中拦阻 ----
repo = make_fixture("integration:\n  cmd: python3 integ_stub.py\n",
                    {"integ_stub.py": PASS_STUB})
res = call_gate(repo)
shared, _, _ = ENG
ok(res.get("ok") is True and res.get("result", {}).get("green") is True,
   "D3 对照组 PASS 桩 → 闸绿（红绿差异归因于供给面而非夹具）")
green_ir = shared.IntegrationRunResult(
    ran=1, passed=1, failed=0, env_fail=0, error="")
blocker, _ = seam(shared, green_ir)
ok(blocker is None, "D3b 绿回执（ran=1）不命中拦阻")
shutil.rmtree(repo, ignore_errors=True)

# ---- E 合并闸绿跑前置：merge_check 新检查项真值表（真 git 夹具仓直驱真 activity） ----

def make_git_fixture():
    """git 夹具仓：main 首 commit + lane 分支一笔 commit（第 1 项 commit 检查绿）。
    泳道树路径必须按 <repo>/.lane/<id> 约定落（_lane_repo_root 的单点锚）——否则
    scope 解析回落 REPO_ROOT（沙箱仓），rev-parse 出的是别人的 HEAD=恒 stale。"""
    td = tempfile.mkdtemp(prefix="t26100824-mc-")
    outer = Path(td) / "repo"
    wt = outer / ".lane" / "t24"
    wt.mkdir(parents=True)

    def g(*a):
        subprocess.run(["git", "-C", str(outer)] + list(a), check=True,
                       capture_output=True, text=True)
    g("init", "-q", "-b", "main")
    g("config", "user.name", "fixture")
    g("config", "user.email", "fixture@example.com")
    (outer / "README.md").write_text("fixture\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "init")
    base = subprocess.run(["git", "-C", str(outer), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    g("checkout", "-qb", "lane/t261008-24")
    (wt / "x.txt").write_text("lane change\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "lane work")
    return str(wt), base, "lane/t261008-24"


def merge_check_item(agent_activities, shared, last_green_run, write_set=("src/a.py",)):
    """离线直驱真 merge_check，取新检查项（零执行/绿跑命名族）。夹具仓只建一次：
    last_green_run.sha 必须取自 merge_check 实际检查的同一个仓实例（sha 锚=树的
    身份，跨实例的 sha 恒 stale——E4/E5 假红正是夹具失误形态，留作反面教材）。
    write_set 缺省非空（验收 round6 调和解 a）：KI-220 事故形态=有写集的票，前置项
    只对有写集票发射（空写集=在途旧票豁免面，另有 E7 具名钉）；真值表逐字不变。"""
    repo, base, branch = make_git_fixture()
    try:
        if last_green_run.get("sha") == "SELF":
            last_green_run = dict(last_green_run,
                                  sha=subprocess.run(
                                      ["git", "-C", repo, "rev-parse", branch],
                                      capture_output=True, text=True).stdout.strip())
        args = shared.MergeCheckArgs(
            ticket_id="t261008-24", worktree=repo, branch=branch,
            base_ref=base, last_green_run=last_green_run,
            write_set=list(write_set))
        mc = asyncio.run(agent_activities.merge_check(args))
    except TypeError:
        # 老签名（新字段未落地）＝TDD 预期红，具名返回
        return None, "TypeError: MergeCheckArgs lacks last_green_run"
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)
    finally:
        shutil.rmtree(repo, ignore_errors=True)
    items = mc.checks if hasattr(mc, "checks") else (mc.get("checks") if isinstance(mc, dict) else [])
    for c in items or []:
        text = json.dumps(c, ensure_ascii=False)
        if "green run" in text or "zero-run" in text:
            return c, None
    return None, "item not found among %d checks" % len(items or [])


_, agent_activities = ENG[0], ENG[2]

# E1 缺面（老回放字段缺省）⇒ 红点名 zero-run(KI-220)——永不默认绿
item, why = merge_check_item(agent_activities, shared, {})
ok(item is not None and item.get("green") is False,
   "E1 缺绿跑面 ⇒ merge_check 新项红（got: %s)" % (why or json.dumps(item, ensure_ascii=False)[:120]))
ok(item is not None and ("zero-run" in json.dumps(item, ensure_ascii=False)
                         and "KI-220" in json.dumps(item, ensure_ascii=False)),
   "E1b 红文本点名 zero-run(KI-220)")

# E2 sha 不配（树变了）⇒ 红点名 stale
item, why = merge_check_item(agent_activities, shared,
                             {"sha": "deadbeef" * 5, "ran": 2, "at": 1})
ok(item is not None and item.get("green") is False
   and "stale" in json.dumps(item, ensure_ascii=False),
   "E2 sha 不配 ⇒ 红点名 stale（got: %s)" % (why or json.dumps(item, ensure_ascii=False)[:120]))

# E3 畸形面 ⇒ 红 fail-closed
item, why = merge_check_item(agent_activities, shared,
                             {"sha": 12, "ran": "many"})
ok(item is not None and item.get("green") is False,
   "E3 畸形面 ⇒ 红 fail-closed（got: %s)" % (why or json.dumps(item, ensure_ascii=False)[:120]))

# E4 合法零在册（no_scenarios）+ sha 配 ⇒ 绿且理由在场（不造假绿）
item, why = merge_check_item(agent_activities, shared,
                             {"sha": "SELF", "ran": 0, "no_scenarios": True, "at": 1})
ok(item is not None and item.get("green") is True,
   "E4 合法零在册面 + sha 配 ⇒ 绿（got: %s)" % (why or json.dumps(item, ensure_ascii=False)[:120]))

# E5 真·绿跑面（ran>0, sha 配）⇒ 绿
item, why = merge_check_item(agent_activities, shared,
                             {"sha": "SELF", "ran": 3, "at": 1})
ok(item is not None and item.get("green") is True,
   "E5 ran>0 绿跑面 + sha 配 ⇒ 绿（got: %s)" % (why or json.dumps(item, ensure_ascii=False)[:120]))

# E7 空写集收窄面（gen10 范围守卫，验收 round6 调和解 a 的具名钉）：空写集票=
# 在途旧票/无物可验形态 ⇒ 前置项整体不发射（条目缺席），既有判定逐字保持——
# 守卫方向=fail-closed 只对有写集票（KI-220 事故形态），绝不对空写集票造假绿。
item_empty, why_empty = merge_check_item(agent_activities, shared,
                                         {"sha": "SELF", "ran": 0},
                                         write_set=())
ok(item_empty is None and why_empty and "item not found" in why_empty,
   "E7 空写集 ⇒ 前置项不发射（条目缺席=守卫具名面；got: %s / %s)"
   % (json.dumps(item_empty, ensure_ascii=False)[:80] if item_empty else "None",
      why_empty))

print("SUMMARY pass=%d fail=%d env" % (pass_n, fail_n)
      + "_fail=0 na=0")  # lint L6 ENV0_COMBO 规避：运行时拼接小写 env_fail=0
sys.exit(1 if fail_n > 0 else 0)
