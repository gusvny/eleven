#!/usr/bin/env python3
"""乙段闸：supply 供给面 + ENV_FAIL 行解析契约（t260904-12 乙段核心承诺）。

intent：乙段落地后闸的两项用户可感知承诺（契约 ②a supply 字段表 + ②b-1 三态
协议 + ②b-2 env_fail 必含）——
  S1  supply 先于 integration.cmd 执行（供给产物在场是场景能跑的前提）；
  S2  supply 命令失败=闸红且**点名 need**（不静默放行——退役的「缺供给当
      没有」旧语义不许还魂）；
  S3  supply 声明畸形（条目缺 cmd/非映射）=fail-closed 红且给原因（外部输入
      畸形三态纪律：声明被解析器消费，畸形必须显式红）；
  S4  ENV_FAIL 行畸形（缺 exit= 字段）沿 FAIL 惯例 fallback：name=整行、
      exit=-1，场景仍计入、闸仍不绿（畸形不蒸发）；
  S5  env_fail 计数入闸返回形状（②b-2 必含）且 env_fail>0 → green=false
      （绿判据含 env_fail=0）。
断言只绑公开契约面（闸回执形状/need 点名/计数），不锚内部实现。

对照组：无 supply 声明 + PASS 桩 = 绿（夹具与调用链有效自证）。

安全红线：fixture 落系统临时目录，不触真仓库；supply 桩为本地临时目录内的
python 脚本（无网络/docker/长驻进程）；经 admin.py 真入口调闸。
"""
import json
import shutil
import subprocess
import sys
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
        cwd=str(REPO), capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        return {"ok": False, "stderr": (p.stderr or "")[-300:]}
    try:
        parsed = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "stderr": "unparseable: " + p.stdout[-200:]}
    inner = parsed.get("result") if isinstance(parsed, dict) else None
    if isinstance(inner, dict) and ("green" in inner or "err" in inner):
        return {"ok": True, "result": inner}
    return {"ok": parsed.get("ok") is True if isinstance(parsed, dict) else False,
            "result": inner if isinstance(inner, dict) else parsed}


def make_fixture(yaml_integration_block, stub_text, extra_files=None):
    td = tempfile.mkdtemp(prefix="t12supply-")
    repo = Path(td)
    (repo / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - src/\n"
        + yaml_integration_block)
    (repo / "integ_stub.py").write_text(stub_text)
    for name, text in (extra_files or {}).items():
        (repo / name).write_text(text)
    return repo


MARKER_PROBE = "\n".join([
    "from pathlib import Path",
    "if Path('supply_marker').is_file():",
    "    print('PASS [供给先行序]')",
    "    print('SCENARIOS ran=1 pass=1 fail=0 env_fail=0 na=0 (0s)')",
    "    import sys",
    "    sys.exit(0)",
    "print('FAIL 供给产物缺席——supply 未先行执行')",
    "print('SCENARIOS ran=1 pass=0 fail=1 env_fail=0 na=0 (0s)')",
    "import sys",
    "sys.exit(1)",
    "",
])
ENV_STUB = "\n".join([
    "print('ENV_FAIL [browser池场景] exit=2')",
    "print('    缺 playwright-core')",
    "print('SCENARIOS ran=1 pass=0 fail=0 env_fail=1 na=0 (0s)')",
    "import sys; sys.exit(2)",
    "",
])
MALFORMED_ENV_STUB = "\n".join([
    "print('ENV_FAIL [畸形场景] exit字段缺失')",
    "print('SCENARIOS ran=1 pass=0 fail=0 env_fail=0 na=0 (0s)')",
    "import sys; sys.exit(2)",
    "",
])
SUPPLY_OK = "from pathlib import Path\nPath('supply_marker').write_text('1')\n"
SUPPLY_BAD = "import sys\nprint('boom：供给物不齐')\nsys.exit(1)\n"

# ---- S1 supply 先行序：成功 supply 写标记，cmd 桩验证标记在场 ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 供给标记\n      cmd: python3 supply_ok.py\n",
    MARKER_PROBE, {"supply_ok.py": SUPPLY_OK})
res = call_gate(repo)
ok(res.get("ok") is True, "S0 调用成功（admin.py 真入口）")
if res.get("ok"):
    r = res["result"]
    ok(r.get("green") is True,
       "S1 supply 先于 cmd 执行（标记在场→cmd 桩 PASS→绿；supply 未先行则此红）")
    ok(r.get("env_fail") == 0, "S1b 全过回执 env_fail=0（②b-2 必含字段）")
shutil.rmtree(repo, ignore_errors=True)

# ---- S2 supply 失败=红点名 need ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - need: 3199隔离台\n      cmd: python3 supply_bad.py\n",
    MARKER_PROBE, {"supply_bad.py": SUPPLY_BAD})
res = call_gate(repo)
if res.get("ok"):
    r = res["result"]
    blob = json.dumps(r, ensure_ascii=False)
    ok(r.get("green") is False, "S2 supply 失败 → 闸不绿（不静默）")
    ok("3199隔离台" in blob, "S2b 红点名 need（回执内可见缺什么，修复指引面）")
else:
    ok(False, "S2/S2b 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- S3 supply 声明畸形=fail-closed ----
repo = make_fixture(
    "integration:\n  cmd: python3 integ_stub.py\n  supply:\n"
    "    - 只写了need没有cmd\n",
    MARKER_PROBE)
res = call_gate(repo)
if res.get("ok"):
    r = res["result"]
    ok(r.get("green") is False, "S3 supply 声明畸形 → 闸不绿（fail-closed 不静默）")
    ok(bool(r.get("err")), "S3b 畸形给原因（err 在场，可归因声明面而非执行器面）")
else:
    ok(False, "S3/S3b 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- S4 ENV_FAIL 行畸形 fallback：name=整行、exit=-1、仍计入、闸不绿 ----
repo = make_fixture("integration:\n  cmd: python3 integ_stub.py\n",
                    MALFORMED_ENV_STUB)
res = call_gate(repo)
if res.get("ok"):
    r = res["result"]
    scen = r.get("scenarios") or []
    bad = [s for s in scen if s.get("exit") == -1 or "ENV_FAIL" in str(s.get("name", ""))]
    ok(r.get("green") is False, "S4 畸形 ENV_FAIL 行 → 闸不绿（畸形不蒸发）")
    ok(bool(bad), "S4b 畸形行沿 FAIL 惯例 fallback（name=整行/exit=-1，场景计入）")
else:
    ok(False, "S4/S4b 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- S5 env_fail 计数入形状且 >0 → 不绿 ----
repo = make_fixture("integration:\n  cmd: python3 integ_stub.py\n", ENV_STUB)
res = call_gate(repo)
if res.get("ok"):
    r = res["result"]
    ok(r.get("env_fail") == 1, "S5 env_fail 计数入回执（②b-2 必含，甲段曾有此即 err 态）")
    ok(r.get("green") is False, "S5b env_fail>0 → 不绿（绿判据含 env_fail=0）")
else:
    ok(False, "S5/S5b 调用失败: " + str(res.get("stderr")))
shutil.rmtree(repo, ignore_errors=True)

# ---- 对照组：无 supply + PASS 桩 → 绿 ----
repo = make_fixture("integration:\n  cmd: python3 integ_stub.py\n",
                    "print('PASS [对照]')\n"
                    "print('SCENARIOS ran=1 pass=1 fail=0 env_fail=0 na=0 (0s)')\n"
                    "import sys\n"
                    "sys.exit(0)\n")
res = call_gate(repo)
ok(res.get("ok") is True and res.get("result", {}).get("green") is True,
   "C1 对照组 PASS 桩 → 绿（红/绿差异归因于 supply/环境红面而非夹具）")
shutil.rmtree(repo, ignore_errors=True)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
