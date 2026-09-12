#!/usr/bin/env python3
"""t260910-13 执行器 fail-closed 回归（t260911 仲裁 code-fault 打回的 L1 钉）。

故障复刻面（out/integration-report-260911-004654.json 实锤）：池级 submit 不存
句柄 → 池内异常从不上浮 → 条目静默丢失、汇总自洽、rc=0 照常绿。

本场景 monkeypatch 级钉三层修复（裁决验收①②③逐条）：
- A 层②：池级异常必须上浮=响亮产品红中止（rc=1，FAIL [__executor__] 点名）；
- B 层①：spawn OSError 在 _run_entry 内按协议分类落红（not-checked×external，
  evidence 点名 spawn 失败原文），条目不丢、ran==在册数、rc=2；
- C 层③：ran==在册数是唯一机械不变式（complete 自校验；INTEG_SUMMARY 带
  expected 供闸复核——闸侧腿见 sc_..._gate.py S9c）。

与 t260910-13-failure-protocol-gate intent 分界：彼守闸的规范行解析与归属判定，
本条守执行器自身的 fail-closed（条目完整性），同票两面不互替。
退出契约：末行 SUMMARY；exit 1 iff fail>0。
"""
import io
import json
import sys
import contextlib
from pathlib import Path
from importlib import util as _ilu

REPO = Path(__file__).resolve().parents[2]
passed = failed = 0


def ok(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok  %s" % label)
    else:
        failed += 1
        print("  FAIL %s %s" % (label, detail))


def load_rs():
    spec = _ilu.spec_from_file_location(
        "rs_failclosed", str(REPO / "integration" / "run_scenarios.py"))
    rs = _ilu.module_from_spec(spec)
    spec.loader.exec_module(rs)
    return rs


def run_main(rs):
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            code = rs.main()
        except SystemExit as ex:   # 兼容防御（main 不应 SystemExit）
            code = ex.code
    return code, buf.getvalue()


STUB_OK = ("stub-ok", "stub intent", "true")            # /bin/sh -c true → PASS
STUB2_OK = ("stub-ok-2", "stub intent 2", "true")

# ---------------- A 层：池级异常上浮=响亮产品红 ----------------
rs = load_rs()
rs.SCENARIOS = [STUB_OK, STUB2_OK]
calls = {"n": 0}
_orig_run_entry = rs._run_entry


def _boom_first(entry):
    calls["n"] += 1
    if calls["n"] == 1:
        raise OSError(24, "Too many open files")   # 池内穿透形态复刻
    return _orig_run_entry(entry)


rs._run_entry = _boom_first
code, out = run_main(rs)
rs._run_entry = _orig_run_entry
ok(code == 1, "A1 池级异常 → rc=1 响亮产品红（非静默绿）", "rc=%r" % code)
ok("FAIL [__executor__]" in out and "池级异常" in out,
   "A2 异常点名 FAIL [__executor__]（可见非无痕）", out[-300:])

# ---------------- B 层：spawn OSError 按协议分类落红 ----------------
# 注入点必须钉在**条目 spawn 调用点**（`/bin/sh -c <条命令>`），不能是「首个
# subprocess.run」：起跑前已有两处 preflight 会先调用（t260910-14 `_docker_hygiene`
# 静默吞异常；t260912-02 `_sweep_residue_stages` 响亮留痕不中止），首个调用被它们
# 吃掉后异常根本到不了 _run_entry，本层就退化成恒绿空转（260913 首轮套件实测
# B1 rc=0/B2 缺原文；基线 6054e58 已有 hygiene，属存量退位非本票引入）。按调用点
# 注入后，断言强度不变：entry spawn 的 OSError 仍须分类 not-checked×external、rc=2、
# evidence 点名原文、条目不丢——正是本条 intent 写的「在 _run_entry 内」。
rs = load_rs()
rs.SCENARIOS = [STUB_OK, STUB2_OK]
_real_subprocess_run = rs.subprocess.run
_calls2 = {"n": 0}


def _oserror_run(*a, **kw):
    argv = a[0] if a else kw.get("args")
    is_entry_spawn = (isinstance(argv, (list, tuple)) and len(argv) >= 2
                      and argv[0] == "/bin/sh" and argv[1] == "-c")
    if is_entry_spawn:
        _calls2["n"] += 1
        if _calls2["n"] == 1:
            raise OSError("spawn 失败面：资源暂时不可用")
    return _real_subprocess_run(*a, **kw)


rs.subprocess.run = _oserror_run
code, out = run_main(rs)
rs.subprocess.run = _real_subprocess_run
ok(_calls2["n"] >= 1, "B0 注入点命中条目 spawn 调用点（实得 %d 次）" % _calls2["n"])
ok(code == 2, "B1 spawn OSError → not-checked 落红（rc=2 环境红，条目不丢）",
   "rc=%r" % code)
ok("spawn 失败面" in out and '"cause": "external"' in out.replace("'", '"'),
   "B2 evidence 点名 spawn 失败原文 + cause=external", out[:600])
ok("ran=2 " in out, "B3 条目不丢：ran==在册数 2", out)

# ---------------- C 层：ran==在册数 不变式 + INTEG_SUMMARY.expected ----------------
rs = load_rs()
rs.SCENARIOS = [STUB_OK, STUB2_OK]
code, out = run_main(rs)
ok(code == 0, "C1 双桩全绿 → rc=0（自校验不误伤正常面）", "rc=%r" % code)
summ = [ln for ln in out.splitlines() if ln.startswith("INTEG_SUMMARY ")]
ok(bool(summ) and json.loads(summ[0][len("INTEG_SUMMARY "):]).get("expected") == 2,
   "C2 INTEG_SUMMARY.expected=在册数（闸复核 ran==expected 的判据在案）", summ)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
sys.exit(1 if failed else 0)
