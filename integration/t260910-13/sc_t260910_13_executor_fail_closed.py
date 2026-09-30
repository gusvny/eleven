#!/usr/bin/env python3
"""t260910-13 执行器 fail-closed 回归（t260911 仲裁 code-fault 打回的 L1 钉）。

故障复刻面（out/integration-report-260911-004654.json 实锤）：池级 submit 不存
句柄 → 池内异常从不上浮 → 条目静默丢失、汇总自洽、rc=0 照常绿。

本场景 monkeypatch 级钉三层修复（裁决验收①②③逐条）：
- A 层②：池级异常必须上浮=响亮产品红中止（rc=1，FAIL [__executor__] 点名）；
- B 层①：spawn OSError 在 _run_entry 内按协议分类落红（not-checked×external，
  evidence 点名 spawn 失败原文），条目不丢、ran==在册数、rc=2；
- C 层③：ran==在册数是唯一机械不变式（complete 自校验；INTEG_SUMMARY 带
  expected 供闸复核——闸侧子用例见 sc_..._gate.py S9c）。

与 t260910-13-failure-protocol-gate intent 分界：彼守闸的规范行解析与归属判定，
本条守执行器自身的 fail-closed（条目完整性），同票两面不互替。
t260912-01 缺陷①修订（260913 merge 与 main 侧同病灶修法合流）：注入从「第 N 次
subprocess.run」改锚「条目面 spawn 调用点」（argv=[…, "/bin/sh", "-c", <条目命令>]），
与起跑前两处 preflight 解耦——t260910-14 `_docker_hygiene`（docker 三连+except 吞面）
与 t260912-02 `_sweep_residue_stages`（sweep 子进程，响亮留痕不中止；旧注入被它们
先行消费、hygiene 还吞异常 → B 层假红守门狗自身失效）；双桩注册为 serial（池内严格
串行）使注入顺序由构造确定；B0 两子用例=注入点命中条目 spawn 调用点 + 顺序归属首条目
（解耦证据）。
退出契约：末行 SUMMARY；exit 1 iff fail>0。
"""
import io
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
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
    with no_narrowing_env():              # 260930：剥继承旋钮再跑内层执行器
        with contextlib.redirect_stdout(buf):
            try:
                code = rs.main()
            except SystemExit as ex:   # 兼容防御（main 不应 SystemExit）
                code = ex.code
    return code, buf.getvalue()


STUB_OK = ("stub-ok", "stub intent", "true", "serial")            # /bin/sh -c true → PASS
STUB2_OK = ("stub-ok-2", "stub intent 2", "true", "serial")
# 四元组第 4 元 "serial" = 池内严格串行（run_scenarios pool 约定）：双桩顺序由构造
# 确定——缺省 conc_pools（main:3）会把两条桩并发跑，「第 N 次」型注入计数有读改写
# 竞态（t260912-01 review C2），serial 根除，三层注入归属均确定。

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
# 注入锚=「条目面 spawn」调用点（argv=[…, "/bin/sh", "-c", <条目命令>]），与起跑前
# preflight 解耦（t260912-01 缺陷①）：起跑前已有两处 preflight 先调 subprocess——
# t260910-14 `_docker_hygiene`（docker 三连 + except 吞面，静默）与 t260912-02
# `_sweep_residue_stages`（sweep 子进程，响亮留痕不中止）；旧「第 1 次
# subprocess.run」注入被它们先行消费（hygiene 还吞异常）→ B 层假红守门狗自身失效
# （单跑稳定 pass=5 fail=2 实锤；260913 首轮套件实测 B1 rc=0/B2 缺原文）。
# preflight 面调用只计数不注入；计数仅观测打印（不作断言——防 preflight 未来退役
# 造成假红）。解耦证据=B0 两子用例：注入点命中条目 spawn 调用点 + 故障顺序归属首条目。
rs = load_rs()
rs.SCENARIOS = [STUB_OK, STUB2_OK]
_real_subprocess_run = rs.subprocess.run
_calls2 = {"entry": 0, "other": 0}   # entry=条目面 spawn；other=preflight 等非条目面（观测）


def _oserror_run(*a, **kw):
    argv = a[0] if a else kw.get("args")
    is_entry_spawn = (isinstance(argv, (list, tuple)) and len(argv) >= 2
                      and argv[0] == "/bin/sh" and argv[1] == "-c")
    if is_entry_spawn:
        _calls2["entry"] += 1
        if _calls2["entry"] == 1:
            raise OSError("spawn 失败面：资源暂时不可用")
    else:
        _calls2["other"] += 1
    return _real_subprocess_run(*a, **kw)


rs.subprocess.run = _oserror_run
try:
    code, out = run_main(rs)
finally:
    rs.subprocess.run = _real_subprocess_run
ok(_calls2["entry"] >= 1,
   "B0a 注入点命中条目 spawn 调用点（实得 %d 次；preflight 面 %d 次未注入）"
   % (_calls2["entry"], _calls2["other"]))
ok(code == 2, "B1 spawn OSError → not-checked 落红（rc=2 环境红，条目不丢）",
   "rc=%r" % code)
ok("spawn 失败面" in out and '"cause": "external"' in out.replace("'", '"'),
   "B2 evidence 点名 spawn 失败原文 + cause=external", out[:600])
ok("ran=2 " in out, "B3 条目不丢：ran==在册数 2", out)
ok("ENV_FAIL [stub-ok] exit=-8" in out and "PASS [stub-ok-2]" in out,
   "B0b 顺序归属：注入落首条目 stub-ok 的 spawn 面、次条目 stub-ok-2 照常"
   "（与 preflight 解耦；双桩 serial 顺序确定）",
   "entry=%(entry)d other=%(other)d" % _calls2 + " out尾=%r" % out[-300:])

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
