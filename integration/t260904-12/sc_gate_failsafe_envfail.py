#!/usr/bin/env python3
"""闸 fail-closed 对 ENV_FAIL 执行器输出（t260904-12 甲段核心承诺，KI-046 反面）。

intent：t260904-07 实锤「场景干净 SKIP→exit 0→闸计过→收口放行」的闸穿透。
本场景钉死反向承诺：执行器按新契约输出（ENV_FAIL 行 + SUMMARY env_fail 计数
+ 总退出码 2）时，verify_lane lane=integ 必判**不绿**——ENV_FAIL 不可穿闸。
两态分支断言（同 gen2 方案 R4 修法①纪律，杜绝「断言先反转、闸还旧语义」的
必红空窗）：green=false 甲乙两段恒真；甲段态（闸未认 ENV_FAIL 行）=err 态在
场且 err 文案点名 exit=2；乙段态（闸解析 env_fail）=ran/exit/tail 逐项在案。
断言只绑公开契约面，不锚内部实现。

对照组：exit 0 + PASS 桩 = 绿（证明夹具与调用链本身有效，红不是夹具残废）。

安全红线：fixture 落系统临时目录，不触真仓库；经 admin.py 真入口调闸。
"""
import json
import subprocess
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


def call_gate(fixture_repo):
    p = subprocess.run(
        [sys.executable, "server/admin.py", "call", "verify_lane",
         json.dumps({"lane": "integ", "path": str(fixture_repo)})],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,
        env=clean_narrowing_env())
    if p.returncode != 0:
        return {"ok": False, "stderr": (p.stderr or "")[-300:]}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stderr": "unparseable: " + p.stdout[-200:]}
    # admin 回执 = {ok, result:{gate形状}} 包装（同 workbench API 惯例），解一层。
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if isinstance(inner, dict) and ("green" in inner or "err" in inner):
        return {"ok": True, "result": inner}
    return {"ok": parsed.get("ok") is True if isinstance(parsed, dict) else False,
            "result": inner if isinstance(inner, dict) else parsed}


def make_fixture(stub_text):
    """临时仓：verify.yaml 声明 integration.cmd → 桩（write_allow 非空=引擎契约）。"""
    td = tempfile.mkdtemp(prefix="t12gate-")
    repo = Path(td)
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        "integration:\n  cmd: python3 integ_stub.py\n")
    (repo / "integ_stub.py").write_text(stub_text)
    return repo


ENV_STUB = "\n".join([
    "print('ENV_FAIL [browser池场景] exit=2')",
    "print('    缺 playwright-core：主树未装配进泳道')",
    "print('SCENARIOS ran=1 pass=0 fail=0 env_fail=1 na=0 (0s)')",
    "import sys",
    "sys.exit(2)",
    "",
])
PASS_STUB = "\n".join([
    "print('PASS [好场景]')",
    "print('SCENARIOS ran=1 pass=1 fail=0 env_fail=0 na=0 (0s)')",
    "import sys",
    "sys.exit(0)",
    "",
])

# ---- 主断言：ENV_FAIL 输出 + rc2 → 闸必红（两态分支，R4 修法①同款纪律） ----
# 甲段态（闸未解析 ENV_FAIL 行）：归 err 态但 green=false 恒成立，err 文案必须点名
# exit=2（报错精确：不得谎称「无结果」而不给退出码线索）。
# 乙段态（闸解析 ENV_FAIL/env_fail）：ran=1、scenarios[].exit=2、缺什么尾段在案。
repo = make_fixture(ENV_STUB)
res = call_gate(repo)
ok(res.get("ok") is True, "G0 调用成功（admin.py 真入口）")
if res.get("ok"):
    r = res["result"]
    ok(r.get("green") is False, "G1 ENV_FAIL 执行器输出 → 闸不绿（不可穿闸，甲乙两段恒真）")
    scen = (r.get("scenarios") or [{}])[0] if r.get("ran") else {}
    if r.get("ran"):
        ok(r.get("err") is None, "G2 乙段态：非 err（场景红非测试道故障）")
        ok(r.get("ran") == 1, "G3 乙段态：ran=1（场景计入）")
        ok(scen.get("exit") == 2, "G4 乙段态：scenarios[].exit=2 在案（环境红可归因）")
        ok("browser池场景" in str(scen.get("name", "")), "G5 乙段态：场景名在案")
        ok("playwright-core" in str(scen.get("output_tail", "")),
           "G6 乙段态：缩进尾段缺什么收进 output_tail（供给修复指引面）")
    else:
        err_text = str(r.get("err") or "")
        ok(bool(err_text), "G2 甲段态：err 态在场（闸未认 ENV_FAIL 行，ran=0+rc≠0）")
        ok("exit=2" in err_text or "exit 2" in err_text,
           "G3 甲段态：err 文案点名 exit=2（报错精确，可分流供给修复而非误判执行器坏）")
else:
    ok(False, "G1-G6 调用失败: " + str(res.get("stderr")))
import shutil
shutil.rmtree(repo, ignore_errors=True)

# ---- 对照组：PASS 桩 rc0 → 绿（夹具有效性自证） ----
repo = make_fixture(PASS_STUB)
res = call_gate(repo)
ok(res.get("ok") is True and res.get("result", {}).get("green") is True,
   "C1 对照组 exit0 PASS 桩 → 闸绿（红/绿差异归因于执行器输出而非夹具）")
shutil.rmtree(repo, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
