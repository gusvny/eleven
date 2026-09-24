#!/usr/bin/env python3
"""i02 —— spawn 链接线守卫（t260901-21，用户场景回归面）：

用户场景：项目凭据出仓后，每个 spawn 出来的泳道/预跑/仲裁/验收 agent 都应拿到
**本工单所属项目**的凭据源；只要有一个 spawn 调用点漏传 project，该 agent 就静默
回落 legacy 全局凭据——对多项目用户是「换 key 后旧项目仍用旧 key」级别的回归，
且表面看不出错（凭据缺失才有 MISSING_CREDENTIAL，回落是静默的）。

本测试守卫四条接线（零 Temporal 依赖，源级断言）：
  1. _prepare_agent_spawn 签名收 project；
  2. 调用点（_run_agent_stage_impl / arbitrate /
     acceptance_walkthrough）各自先 `await _fetch_ticket_project(...)`；
  3. 每个 _prepare_agent_spawn( 调用都带 project=project；
  4. _fetch_ticket_project 的降级语义在位（try/except + timeout，软失败返回 ""）。

跑法：python3 integration/t260901-21/i02_spawn_wiring.py（cwd=泳道根）
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "server" / "engine" / "agent_activities.py"

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok " + label)
    else:
        FAIL += 1
        print("  FAIL " + label)


src = SRC.read_text()

# 1 签名收 project
sig = re.search(r"def _prepare_agent_spawn\(([^)]*)\)", src, re.S)
ok(sig is not None and re.search(r"project\s*[:=]", sig.group(1)) is not None,
   "_prepare_agent_spawn 签名含 project 参数")

# 2/3 逐调用点接线：函数体内先 fetch 再传 project=project
ok(src.count("_prepare_agent_spawn(") == 6,  # 1 定义 + 5 调用（t260916-22：inspect 段第 4 调用点；t260925-01：产出型巡检 produce 段新增第 5 调用点——extend-locks 有意同步，非拆锁）
   "调用点数 = 5（实际 _prepare_agent_spawn( 出现 %d 次，含定义）" % src.count("_prepare_agent_spawn("))

# 按函数切块（顶层 async def 边界），逐块查接线
funcs = re.split(r"\n(?=async def |def )", src)
hosts = ["_run_agent_stage_impl", "arbitrate", "acceptance_walkthrough"]


def resolve(host):
    """t260916-29：长活动外包了 worker_termination_guard 薄壳（worker 停机取消归因），
    spawn 接线本体移到 _<host>_body——本检查跟随薄壳找本体（壳无 spawn 面）。"""
    body = next((f for f in funcs if f.startswith("async def %s(" % host)), None)
    if body and "worker_termination_guard" in body:
        inner = next((f for f in funcs
                      if f.startswith("async def _%s_body(" % host)), None)
        if inner:
            return inner
    return body


for host in hosts:
    body = resolve(host)
    if body is None:
        ok(False, "%s：函数未找到" % host)
        continue
    has_fetch = re.search(r"=\s*await\s+_fetch_ticket_project\(", body) is not None
    calls = body.count("_prepare_agent_spawn(")
    wired = len(re.findall(r"project\s*=\s*project\b", body))
    ok(has_fetch, "%s：先 await _fetch_ticket_project" % host)
    ok(calls >= 1 and wired >= calls,
       "%s：_prepare_agent_spawn 调用 %d 处全部传 project=project（实传 %d）" % (host, calls, wired))

# 4 _fetch_ticket_project 软失败语义在位
fetch = next((f for f in funcs if f.startswith("async def _fetch_ticket_project(")), None)
ok(fetch is not None, "_fetch_ticket_project 在位")
if fetch:
    ok("except" in fetch and "return \"\"" in fetch.replace("'", '"'),
       "_fetch_ticket_project 异常降级返回空串（软失败，不弄挂 spawn）")
    ok("timeout" in fetch, "_fetch_ticket_project 查询带超时")

# 5 巡检 inspect 段（t260916-22）第 4 调用点：project 不走 _fetch_ticket_project——
# 巡检票身份=起票时刻声明的实例 project_key（t260915-20），由 workflow 输入透传进活动
# args；接线语义同守：spawn 必须带 project=project，且来源钉死在活动 args（防静默回落
# legacy 全局凭据）。
insp_body = next((f for f in funcs if f.startswith("async def run_inspection_inspect(")), None)
ok(insp_body is not None, "run_inspection_inspect：函数在位（第 4 调用点 host）")
if insp_body:
    ok('args.get("project_key")' in insp_body,
       "inspect：project 源=活动 args.project_key（巡检票身份语义，t260915-20）")
    ok(re.search(r"_prepare_agent_spawn\([^)]*project\s*=\s*project", insp_body, re.S) is not None,
       "inspect：_prepare_agent_spawn 传 project=project")

# 第 5 调用点（t260925-01）：产出型巡检 produce 段同守——project 源=args.project_key
# 且 spawn 传 project=project（巡检票身份语义随 produce 链延续，漏传=凭据静默错挂）。
prod_body = next((f for f in funcs if f.startswith("async def run_inspection_produce(")), None)
ok(prod_body is not None, "run_inspection_produce：函数在位（第 5 调用点 host）")
if prod_body:
    ok('args.get("project_key")' in prod_body,
       "produce：project 源=活动 args.project_key（巡检票身份语义）")
    ok(re.search(r"_prepare_agent_spawn\([^)]*project\s*=\s*project", prod_body, re.S) is not None,
       "produce：_prepare_agent_spawn 传 project=project")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
