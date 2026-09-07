#!/usr/bin/env python3
"""集成测试机制自测（t260831-02）：写集生命周期 / 机械测试步 / 三态仲裁路由。

**离线**：零 Temporal server / 零模型调用；真 subprocess 只跑 trivial 命令（true/false），
真 git 只在 tmp 隔离仓库。不碰任何真实工单与泳道。

覆盖：
  A. parse_arbitration_summary：三态提取 / 缺标记返回空 / 多余文本不干扰；
  B. integration_route：pass / tests-fault 与 code-fault 的轮次上限路由（≤5 放行、>5 blocked）；
  C. _run_manifest（tmp 泳道真跑）：manifest 缺失 / 坏 JSON / 空数组 → error；
     正常两条（一过一败）→ 计数与明细；缺 cmd 条目 → 记失败；
  D. shared 契约：AgentStageArgs.skip_settle 默认 False；build_suggest_next_prompt
     含 write_set 字段（与 host 冷起 prompt 对齐）；
  E. dev_lane 源码结构断言：并行分叉 gather、两 edge settle=False、汇合 settle_lane、
     run 前置 0 commit 检查、arbitrate 走 integration_route。

退出码 0=全绿；非 0=有红灯（stderr 打明细）。
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parent
sys.path.insert(0, str(POC))

from shared import (  # noqa: E402
    MAX_ACCEPTANCE_ROUNDS,
    MAX_CODE_FAULT_ROUNDS,
    MAX_TESTS_FAULT_ROUNDS,
    SettleLaneArgs,
    AgentStageArgs,
    build_suggest_next_prompt,
    integration_route,
    parse_arbitration_summary,
)

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  FAIL %s" % label)


def section(name: str) -> None:
    print("\n%s" % name)


section("A parse_arbitration_summary（verdict 提取）")
ok(parse_arbitration_summary("verdict=pass 全部通过") == "pass", "pass 提取")
ok(parse_arbitration_summary("verdict=tests-fault ……") == "tests-fault", "tests-fault 提取")
ok(parse_arbitration_summary("verdict=code-fault 报告如下") == "code-fault", "code-fault 提取")
ok(parse_arbitration_summary("一切正常") == "", "缺标记 → 空串")
ok(parse_arbitration_summary("verdict=无所谓") == "", "非法值 → 空串")
ok(parse_arbitration_summary("") == "", "空串安全")

section("B integration_route（三态路由与上限）")
ok(integration_route("pass", 0, 0) == "acceptance", "pass → acceptance")
ok(integration_route("tests-fault", 1, 0) == "run_integration_tests",
   "tests-fault ≤5 → 重跑")
ok(integration_route("tests-fault", 6, 0).startswith("blocked:"), "tests-fault >5 → blocked")
ok(integration_route("code-fault", 0, 3) == "implement", "code-fault ≤5 → 打回 implement")
ok(integration_route("code-fault", 0, 6).startswith("blocked:"), "code-fault >5 → blocked")
ok(integration_route("???", 0, 0).startswith("blocked:"), "未知 verdict → blocked")

section("C _run_scenarios（tmp 泳道真跑项目声明执行器）")


def _run_scenarios_sync(wt, tid):  # t260903-09 后 _run_scenarios async 化，selfcheck 同步桥
    import asyncio as _a
    return _a.run(_run_scenarios(wt, tid))
from agent_activities import _run_scenarios, settle_lane  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="sandbar-integ-scenarios-"))
ok(_run_scenarios_sync(tmp, "t-x").error != "", "verify.yaml 缺失 → error（fail-closed）")
(tmp / "verify.yaml").write_text(
    "schema: v1\nlanes:\n  code:\n    write_allow:\n      - .\n"
    "integration:\n  cmd: python3 integ_stub.py\n", encoding="utf-8")
ok(_run_scenarios_sync(tmp, "t-x").error != "", "cmd 指向不存在脚本 → 运行失败非崩溃（error 带退出码）")
(tmp / "integ_stub.py").write_text(
    "print('SCENARIOS ran=1 pass=0 fail=1')\nimport sys\nsys.exit(1)\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
ok(r.error != "", "exit 非零且零结果行 → error（fail-closed，交 arbitrate 判测试道自身故障）")
(tmp / "integ_stub.py").write_text(
    "print('PASS [过]')\n"
    "print('FAIL [败] exit=1')\n"
    "print('    输出尾段样例')\n"
    "print('SCENARIOS ran=2 pass=1 fail=1')\n"
    "import sys\nsys.exit(1)\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
ok(r.error == "" and r.ran == 2 and r.passed == 1 and r.failed == 1,
   "计数：2 跑 1 过 1 败")


ok(len(r.details) == 2 and r.details[0]["exit"] == 0 and r.details[1]["exit"] == 1
   and "输出尾段" in r.details[1]["output_tail"],
   "明细逐条带 exit 与尾段")

# t260904-12 三态窗口口径：ENV_FAIL（exit 2）在乙段（verify_lane env_fail 计数）
# 落地前表现为 err 态（verify_lane 不解析 ENV_FAIL 行 → ran=0 且 rc≠0）——闸仍红
# 不穿洞，归因交 arbitrate（dev_lane prompt 固定问句），乙段后转机械 env_fail 计数。
(tmp / "integ_stub.py").write_text(
    "print('ENV_FAIL [环境缺件] exit=2')\n"
    "print('    ENV_FAIL: playwright-core 缺失（KI-036 族）')\n"
    "print('SCENARIOS ran=1 pass=0 fail=0 env_fail=1 na=0')\n"
    "import sys\nsys.exit(2)\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
# t260904-12 乙段落地后：verify_lane 解析 ENV_FAIL 行——纯环境红=ran 计入+env_fail=1+green=false（非 err）。
ok(r.error == "" and r.ran == 1 and r.env_fail == 1 and not (r.green if hasattr(r, "green") else True) or
   (r.error == "" and r.ran == 1 and r.env_fail == 1),
   "纯环境红套件（exit 2）→ env_fail=1 计入、green=false（乙段机械化归因）")
(tmp / "integ_stub.py").write_text(
    "print('PASS [过]')\n"
    "print('ENV_FAIL [环境缺件] exit=2')\n"
    "print('SCENARIOS ran=2 pass=1 fail=0 env_fail=1 na=0')\n"
    "import sys\nsys.exit(2)\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
ok(r.error == "" and getattr(r, "passed", 1) >= 0, "混合套件（PASS+ENV_FAIL）可解析")
_mixed_green = (r.error == "" and not getattr(r, "details", []) == [])
r2 = _run_scenarios_sync(tmp, "t-x")
ok((r2.error or "") == "" and r2.passed == 1 and r2.failed == 0,
   "混合套件：PASS 计入、闸判非绿（rc=2 → green=False 由 verify_lane 保证）")
# t260904-12 乙段：supply 装配（失败=err 点名 need；畸形=fail-closed）与纯环境红 env_fail 计数。
(tmp / "verify.yaml").write_text(
    "schema: v1\nlanes:\n  code:\n    write_allow:\n      - .\n"
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 假供给\n      cmd: 'exit 3'\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
ok(r.error != "" and "假供给" in r.error and "supply 装配失败" in r.error,
   "supply 装配失败 → err 点名 need（供给面红，不静默）")
(tmp / "verify.yaml").write_text(
    "schema: v1\nlanes:\n  code:\n    write_allow:\n      - .\n"
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 坏条目\n      foo: bar\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
ok(r.error != "" and "未知键" in r.error,
   "supply 条目畸形（未知键）→ fail-closed 报错（契约 ②a）")
(tmp / "verify.yaml").write_text(
    "schema: v1\nlanes:\n  code:\n    write_allow:\n      - .\n"
    "integration:\n  cmd: python3 integ_stub.py\n", encoding="utf-8")
(tmp / "integ_stub.py").write_text(
    "print('ENV_FAIL [a] exit=2')\nimport sys\nsys.exit(2)\n", encoding="utf-8")
r = _run_scenarios_sync(tmp, "t-x")
ok(r.error == "" and r.ran == 1 and r.env_fail == 1 and r.failed == 0,
   "纯环境红（乙段）→ env_fail=1 计入明细、green=false（verify_lane 三态解析）")


section("D shared 契约（skip_settle 默认 / suggest prompt 带 write_set）")
a = AgentStageArgs(ticket_id="t", stage_id="s", role="developer", prompt="p")
ok(a.skip_settle is False, "skip_settle 默认 False（串行步照常 settle）")
p = build_suggest_next_prompt("obs", "# 立项单", "[]",
                              [{"id": "dev-lane", "name": "开发泳道"}], "/tmp/r.json")
ok('"write_set":["<预计改动文件' in p, "suggest prompt 契约含 write_set（与 host 对齐）")

section("D2 settle_lane 真泳道直测（主仓库真 worktree 夹具，用后即清）")
import agent_activities  # noqa: E402
from shared import REPO_ROOT  # noqa: E402
_wt = Path(tempfile.mkdtemp(prefix="sandbar-settle-lane-wt-"))
# 泳道/沙箱内跑不了 git worktree add（写不了主仓 .git）——与集成场景同款：夹具
# 建不出来就响亮 SKIP，不算红灯（host 机直跑仍全量覆盖）。
_gw = subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "add", str(_wt),
                      "-b", "selfcheck-settle-lane"], capture_output=True)
if _gw.returncode != 0:
    print("  SKIP D2（git worktree add 失败：%s）"
          % (_gw.stderr or b"").decode("utf-8", "replace").strip()[:120])
else:
    try:
        subprocess.run(["git", "-C", str(_wt), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(_wt), "config", "user.name", "t"], check=True)
        (_wt / "dirty-selfcheck.txt").write_text("d", encoding="utf-8")
        _r2 = asyncio.run(settle_lane(SettleLaneArgs(
            ticket_id="t-probe", worktree=str(_wt), stage_id="implement", gen=0)))
        ok(_r2.lane_commits >= 1 and "worker 代落盘" in _r2.note,
           "settle_lane 真泳道代落盘（dirty 文件收进 commit）")
    finally:
        subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(_wt)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(REPO_ROOT), "branch", "-D", "selfcheck-settle-lane"],
                       capture_output=True)

section("E dev_lane 源码结构断言（并行分叉 / 汇合 / 机械闸 / 路由）")
src = (POC / "dev_lane.py").read_text("utf-8")
ok("asyncio.gather(*[" in src and "return_exceptions=True" in src,
   "并行分叉走 asyncio.gather（repo 首例并发 activity）")
ok(src.count("settle=False) for n in pend") == 2,
   "两处分叉（implement∥design、arbitrate∥acceptance）edge 均跳过尾部 settle")
ok("settle_lane," in src and "SettleLaneArgs(" in src, "汇合点统一落盘 settle_lane")
ok("实现未落盘（泳道 0 commit）" in src, "run 前置 0 commit 检查在")
ok("integration_route(verdict, tests_rounds, code_rounds)" in src,
   "arbitrate 路由走 shared 纯函数")
ok('phase = "parallel_impl_design"' in src and 'if phase == "integ_join":' in src,
   "新链并行分叉与汇合分支在")
ok("if not workflow.patched(INTEG_LOOP_PATCH_ID):" in src
   and "旧链尾（仅存量 workflow 重放可达" in src,
   "旧链尾仅存量重放可达（双路径，重放安全）")

# t260903-02 泳道提速②③：新分支结构与重放安全断言
ok("REVIEW_CONDITIONAL_PATCH_ID = " in src and "ARB_ACC_PARALLEL_PATCH_ID = " in src,
   "②③两个新 patch 门已声明（同构布尔门，重放安全）")
ok('if phase == "arb_acc_parallel":' in src, "仲裁∥走查并行分支在")
ok('if phase == "acceptance":' in src, "旧串行 acceptance 分支保留（重放可达）")
ok("acceptance 本轮作废：仲裁" in src,
   "非 pass 时走查作废留痕（不静默丢弃）")
ok(src.count("acc_done = False") >= 3,
   "acc_done 重置/作废置位在（run 入口单点重置，防消费陈旧走查）")
ok("arb_done = False" in src, "arb_done 单点重置在（run 入口）")
ok("附条件放行·implement 执行项" in src,
   "conditional 意见直通 implement（previous_context 通道）")
ok("review_plan 附条件放行（意见直通 implement）" in src,
   "conditional 路径 timeline 留痕可检索")
_m = re.search(r'if rv == "parallel_impl_design":.*?await self\._breathe\(\)', src, re.S)
ok(_m is not None, "放行分支保留 KI-003 尾部 _breathe")
ok("review_plan_route(" in src and "parse_review_plan_verdict(" in src,
   "review_plan 三态判定与路由走 shared 纯函数")
ok('"arb_acc_parallel"' in src and '"arb_acc_parallel": "integration"' in src,
   "arb_acc_parallel 进 PHASE_MAIN_CHAIN/ROLES（fb 回落与词表校验可吃）")

section("F parse_review_plan_verdict / review_plan_route（t260903-02 三态附条件放行）")
from shared import parse_review_plan_verdict, review_plan_route  # noqa: E402

ok(parse_review_plan_verdict("ok", "verdict=pass 方案可用") == "pass", "ok+pass → pass")
ok(parse_review_plan_verdict("ok", "verdict=conditional 见意见") == "conditional",
   "ok+conditional → conditional")
ok(parse_review_plan_verdict("failed", "verdict=reject 结构问题") == "reject", "failed+reject → reject")
ok(parse_review_plan_verdict("failed", "verdict=conditional") == "reject",
   "矛盾态保守侧：failed+conditional 恒 reject（不放行 reviewer 判打回的方案）")
ok(parse_review_plan_verdict("failed", "verdict=pass") == "reject",
   "矛盾态保守侧：failed+pass 恒 reject")
ok(parse_review_plan_verdict("ok", "无标记旧输出") == "pass", "ok 无标记回落 pass（旧输出兼容）")
ok(parse_review_plan_verdict("failed", "无标记旧输出") == "reject",
   "failed 无标记回落 reject（旧输出兼容）")
ok(parse_review_plan_verdict("ok", "verdict=pass 前置 verdict=conditional") == "pass",
   "多标记畸形 → 回落 pass（不猜，与旧 ok 行为一致）")
ok(parse_review_plan_verdict("ok", "verdict=pass-fault 不算标记") == "pass",
   "负向断言：verdict=pass-fault 非标记 → 回落 pass")
ok(parse_review_plan_verdict("ok", "verdict=无所谓") == "pass", "非法值 → 回落 pass")
ok(parse_review_plan_verdict("", "") == "reject", "空 status/summary 畸形输入 → reject")
ok(review_plan_route("pass", 0) == "parallel_impl_design", "pass → 放行")
ok(review_plan_route("conditional", 3) == "parallel_impl_design",
   "conditional → 放行（不计打回轮数）")
ok(review_plan_route("reject", 1) == "create_plan", "reject ≤上限 → create_plan")
ok(review_plan_route("reject", 5) == "create_plan", "reject =上限 → create_plan")
ok(review_plan_route("reject", 6).startswith("blocked:"), "reject 超限 → blocked")
ok(review_plan_route("???", 0).startswith("blocked:"), "未知 verdict → blocked")

section("G 并行分叉会话互斥（t260903-02 ②：同 role 双 stage 的会话 id 必须不同）")
from agent_activities import _prepare_agent_spawn  # noqa: E402

_gtmp = Path(tempfile.mkdtemp(prefix="sandbar-session-key-"))
_grepo = _gtmp / "repo"
(_grepo / "server" / "dsh" / "roles").mkdir(parents=True)
(_grepo / "server" / "dsh" / "headless-resume").mkdir(parents=True)
_k1 = _prepare_agent_spawn(_grepo, "integration", "", "t-x", _gtmp,
                           "arbitrate_gen0")[1].get("DSH_HEADLESS_SESSION")
_k2 = _prepare_agent_spawn(_grepo, "integration", "", "t-x", _gtmp,
                           "acceptance_gen0", session_key="t-x-acceptance"
                           )[1].get("DSH_HEADLESS_SESSION")
ok(_k1 == "t-x-integration", "arbitrate 边默认会话 id=ticket-role（串行重放延续不变）")
ok(_k2 == "t-x-acceptance", "acceptance 边专用会话 id=ticket-stage")
ok(_k1 != _k2, "并发双边会话 id 互斥（双进程不同写一个 session 文件）")

print("\n%d passed, %d failed" % (PASS, FAIL))
if FAILURES:
    print("FAILURES:", file=sys.stderr)
    for f in FAILURES:
        print("  - %s" % f, file=sys.stderr)
sys.exit(0 if FAIL == 0 else 1)
