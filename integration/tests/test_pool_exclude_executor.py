#!/usr/bin/env python3
"""执行器池排除旋钮机械自证（t260913-03）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：每票集测段可按
注册表自有的池名做纯机械排除——被排除池的条目不在本轮在册数（不计 ran/expected；
不是「跑了判过」，也不是静默少跑）；排除面必须在汇总里点名；缺省（无旋钮）路径
零新增行/键（逐键全等锚）；配置错误（未知池/非法 token）不在执行器主路径判红
（那会与既有注入式电池的假场景表冲突），而由 --print-pool-assets 单点判红。

覆盖：
- A 排除生效：假表三池注 engine → 该池不计 ran/expected、点名行原文、条件键在场；
- B 缺省零新增：显式隔离 os.environ → SUMMARY 键集与缺省形态逐键全等、无排除行；
- C 零命中：假表无该池 → 响亮 WARN + 少 0 条、rc 不变、WARN 行前缀形状锁；
- D 非法 token：剥离+逐条点名、合法部分照常生效、rc 不变；
- E 回归：既有两条执行器电池（三态出口 / 条目完整性）在排除 env 继承下照常绿；
- F --print-pool-assets：真注册表派生（未知池 exit 2 点名；cmd token ∪ import 闭包
  ∪ integration/ 根共享基建面；环境前缀 token 不误收；非被排除池资产不入面）；
- G 资产面负锁：ro/browser 池场景文件不被误收（方向=宁可多跑，不得漏跑被排除池面）；
- H 缺省路径与改前执行器（git HEAD 快照）在假表上逐字节一致（验收 B 的源码级 A/B）。

安全红线：假场景脚本全部落 TemporaryDirectory（真仓零触碰）；每腿显式 env 桩
save/restore（既有先例无 os.environ 隔离，排除环境下会自我污染）；rs.SCENARIOS
替换 try/finally 还原；运行时卫生钩子置空（本电池不测 docker 面）。零端口零
docker 零控制台，秒级。
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_KEY = "SANDBAR_SCENARIO_EXCLUDE_POOLS"
DEFAULT_SUMMARY_KEYS = {
    "ran", "pass", "fail", "not_checked", "wall_s", "concurrency",
    "pool_config", "env_fingerprint", "expected",
}

_spec = importlib.util.spec_from_file_location(
    "rs_exclude_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

pass_n = fail_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + (" | " + str(detail)[:500] if detail else ""))


@contextlib.contextmanager
def env_stub(value, extra=None):
    """显式 env 桩：save/restore；value=None 表示清除该键（缺省形态腿必须清）。
    extra=额外键值（如 SANDBAR_POOL_CONC=1 求确定序），出块一律还原。"""
    keys = [ENV_KEY] + list((extra or {}).keys())
    saved = {k: os.environ.get(k) for k in keys}
    if value is None:
        os.environ.pop(ENV_KEY, None)
    else:
        os.environ[ENV_KEY] = value
    for k, v in (extra or {}).items():
        os.environ[k] = str(v)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def drive(entries, exclude_env, mod=None, extra_env=None):
    """注入假场景表跑执行器主路径，返回 (rc, stdout)。

    entries=(名, 池, 脚本文本)，池为 None=main。假脚本落临时目录并把 cwd 移进去
    （main 的 out/ 报告落档不污染真仓）；SCENARIOS 替换 try/finally 还原；卫生
    钩子置空（sweep/docker hygiene 属真 docker 面，本电池不测）。mod=被测模块
    （缺省=本仓执行器；H 腿用改前快照）。
    """
    mod = mod or rs
    with tempfile.TemporaryDirectory(prefix="t913ex-") as td:
        td_path = Path(td)
        table = []
        for i, (name, pool, script) in enumerate(entries):
            p = td_path / ("s%d.py" % i)
            p.write_text(script)
            item = (name, "假场景（t260913-03 注入）", "python3 %s" % p)
            if pool:
                item = item + (pool,)
            table.append(item)
        saved_scen = mod.SCENARIOS
        saved_sweep, saved_hygiene = mod._sweep_residue_stages, mod._docker_hygiene
        mod.SCENARIOS = table
        mod._sweep_residue_stages = lambda: None
        mod._docker_hygiene = lambda: None
        cwd_saved = os.getcwd()
        buf = io.StringIO()
        try:
            os.chdir(td)
            with env_stub(exclude_env, extra_env):
                with contextlib.redirect_stdout(buf):
                    rc = mod.main()
        finally:
            mod.SCENARIOS = saved_scen
            mod._sweep_residue_stages = saved_sweep
            mod._docker_hygiene = saved_hygiene
            os.chdir(cwd_saved)
        return rc, buf.getvalue()


def summary_of(out):
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


def scenarios_line(out):
    for ln in out.splitlines():
        if ln.startswith("SCENARIOS ran="):
            return ln
    return ""


TRIO = [("t913-main", None, "print('m')\n"),
        ("t913-ro", "ro", "print('r')\n"),
        ("t913-engine", "engine", "print('e')\n")]

# ---- A 排除生效 ----
rc, out = drive(TRIO, "engine")
ok(rc == 0, "A1 排除生效 rc=0", rc)
ok("本轮跳过池=engine（少 1 条）" in out, "A2 点名行原文（少 N 条）", out[-500:])
ok("PASS [t913-main]" in out and "PASS [t913-ro]" in out
   and "PASS [t913-engine]" not in out, "A3 被排除条目零行、其余照跑")
ok(out.count("PASS [") == 2 and "ran=2 " in scenarios_line(out)
   and "pass=2 " in scenarios_line(out), "A4 ran/pass=本轮在册（2 条）", scenarios_line(out))
_sum = summary_of(out)
ok(bool(_sum) and _sum.get("expected") == 2, "A5 INTEG_SUMMARY.expected=本轮在册数", _sum)
ok(bool(_sum) and _sum.get("excluded_pools") == ["engine"]
   and _sum.get("excluded_count") == 1, "A6 条件键 excluded_pools/excluded_count 真值", _sum)

# ---- B 缺省零新增（显式 env 隔离）----
rc, out = drive(TRIO, None)
ok(rc == 0 and "ran=3 " in scenarios_line(out), "B1 缺省全跑 rc=0/ran=3", scenarios_line(out))
ok("本轮跳过池=" not in out and "EXCLUDE_POOLS_WARN" not in out,
   "B2 缺省零排除行/零 WARN")
_sum = summary_of(out)
ok(bool(_sum) and set(_sum.keys()) == DEFAULT_SUMMARY_KEYS,
   "B3 缺省 INTEG_SUMMARY 键集逐键全等（零新增）", sorted(_sum or {}))
ok("excluded_pools" not in (_sum or {}) and "excluded_count" not in (_sum or {}),
   "B4 缺省无排除条件键")

# ---- C 零命中（响亮不红）----
rc, out = drive([("t913-main", None, "print('m')\n")], "engine")
ok(rc == 0, "C1 零命中 rc 不变（0）", rc)
ok("EXCLUDE_POOLS_WARN [engine]" in out and "在册池" in out, "C2 零命中响亮 WARN 点名")
ok("本轮跳过池=engine（少 0 条）" in out, "C3 点名行如实报 0 条（不静默）")
_sum = summary_of(out)
ok(bool(_sum) and _sum.get("excluded_count") == 0, "C4 条件键如实 count=0", _sum)
_warns = [ln for ln in out.splitlines() if "EXCLUDE_POOLS_WARN" in ln]
ok(bool(_warns) and all(ln.startswith("EXCLUDE_POOLS_WARN [") for ln in _warns)
   and not any(ln.startswith(("PASS [", "FAIL [", "ENV_FAIL [", "{", "["))
   for ln in _warns), "C5 WARN 行前缀形状锁（不撞明细/规范行解析面）", _warns[:2])

# ---- D 非法 token：剥离+点名，合法部分照常生效 ----
rc, out = drive([("t913-main", None, "print('m')\n"),
                 ("t913-engine", "engine", "print('e')\n")],
                "Engine, engine ,, bad token")
ok(rc == 0, "D1 非法 token 不改变退出码语义（rc=0）", rc)
ok("EXCLUDE_POOLS_WARN [Engine]" in out and "EXCLUDE_POOLS_WARN [bad token]" in out,
   "D2 非法 token 逐条点名")
ok("本轮跳过池=engine（少 1 条）" in out and "PASS [t913-engine]" not in out,
   "D3 合法部分照常生效")

# ---- E 既有电池在排除 env 继承下照常绿（R2 机械回归腿）----
for _path, _label in ((REPO / "integration/t260904-12/sc_executor_three_state.py",
                       "三态出口电池"),
                      (REPO / "integration/t260910-13/sc_t260910_13_executor_fail_closed.py",
                       "条目完整性电池")):
    _p = subprocess.run([sys.executable, str(_path)], cwd=str(REPO),
                        capture_output=True, text=True, timeout=900,
                        env=dict(os.environ, **{ENV_KEY: "engine,exclusive"}))
    ok(_p.returncode == 0, "E %s 在排除 env 继承下照常绿" % _label,
       ((_p.stdout or "") + (_p.stderr or ""))[-400:])

# ---- F --print-pool-assets：真注册表派生 ----
def run_assets(arg):
    return subprocess.run([sys.executable, str(REPO / "integration" / "run_scenarios.py"),
                           "--print-pool-assets", arg],
                          cwd=str(REPO), capture_output=True, text=True, timeout=300)


_p = run_assets("engine,exclusive")
ok(_p.returncode == 0, "F1 合法池名 exit 0", _p.returncode)
_data = None
try:
    _data = json.loads((_p.stdout or "").strip().splitlines()[-1])
    ok(True, "F2 输出单行 JSON 可解析")
except (ValueError, IndexError) as _e:
    ok(False, "F2 输出单行 JSON 可解析", "%s | %s" % (_e, _p.stdout[-300:]))
_assets = (_data or {}).get("assets") or []
ok((_data or {}).get("pools") == ["engine", "exclusive"], "F3 池名回显", (_data or {}).get("pools"))
ok(bool(_assets) and all(a.startswith("integration/") and (REPO / a).is_file()
                         for a in _assets), "F4 资产全为 integration/ 前缀且真存在（%d 条）" % len(_assets))
ok(not any("=" in a for a in _assets), "F5 环境前缀 token（PY=…）不误收")
ok("integration/lib_env.py" in _assets and "integration/lib_result.py" in _assets
   and "integration/stage_docker.mjs" in _assets and "integration/with_stage.sh" in _assets,
   "F6 根共享基建面（协议库/舞台链）在资产面", _assets[:12])
ok(any(a.endswith("sc_worker_fingerprint_gate.py") for a in _assets),
   "F7 被排除池场景文件在资产面")
ok(any(re.search(r"lib_[a-z0-9_]+\.py$", a) and "/t2609" in a for a in _assets),
   "F8 import 闭包纳入票内共享库（cmd token 之外的面）", _assets[:12])
ok("integration/sc_scenarios_guard_drift.py" not in _assets
   and "integration/baselines/sc_lane_parallel_dom.mjs" not in _assets,
   "F9 负锁：非被排除池场景文件不入资产面")
_p2 = run_assets("engin")
ok(_p2.returncode == 2 and "engin" in (_p2.stdout + _p2.stderr),
   "F10 未知池 exit 2 点名（闸侧单点判红）", _p2.returncode)
_p3 = run_assets("engine,bad token")
ok(_p3.returncode == 2, "F11 非法池名 exit 2（闸侧单点判红）", _p3.returncode)

# ---- H 缺省路径与改前执行器逐字节一致（验收 B 的源码级 A/B，只读取改前快照）----
def _norm_run(out):
    """归一化耗时/时间戳/指纹等运行语境字段（结构面逐字节比对）。"""
    out = re.sub(r'"dur_s": [\d.]+', '"dur_s": N', out)
    out = re.sub(r'"started": "[^"]*"', '"started": "T"', out)
    out = re.sub(r"\d+(?:\.\d+)?s", "Ns", out)
    out = re.sub(r'"wall_s": [\d.]+', '"wall_s": N', out)
    out = re.sub(r'"env_fingerprint": "[0-9a-f]+"', '"env_fingerprint": "F"', out)
    out = re.sub(r"integration-report-\d+-\d+\.json", "integration-report-T.json", out)
    return out


_old = subprocess.run(["git", "show", "HEAD:integration/run_scenarios.py"],
                      cwd=str(REPO), capture_output=True, text=True, timeout=60)
if _old.returncode != 0 or not _old.stdout.strip():
    ok(False, "H0 改前执行器快照可取（git show HEAD:integration/run_scenarios.py）",
       _old.stderr[-300:])
else:
    with tempfile.TemporaryDirectory(prefix="t913old-") as _td:
        _old_py = Path(_td) / "rs_before.py"
        _old_py.write_text(_old.stdout, encoding="utf-8")
        # 执行器按自身目录 import lib_result（规范行综合面）：快照必须与它同目录，
        # 否则改前执行器在临时目录里 import 失败 → 池级异常，A/B 比对失去意义
        import shutil as _shutil
        _shutil.copy2(REPO / "integration" / "lib_result.py",
                      Path(_td) / "lib_result.py")
        _spec_old = importlib.util.spec_from_file_location("rs_before_under_test", _old_py)
        _mod_old = importlib.util.module_from_spec(_spec_old)
        _spec_old.loader.exec_module(_mod_old)
        # 串行跑（SANDBAR_POOL_CONC=1）：池间并发会让输出行序不确定，逐字节比对必须确定序
        _serial = {"SANDBAR_POOL_CONC": "1", "SANDBAR_CONC_POOLS": ""}
        _rc_a, _out_a = drive(TRIO, None, mod=_mod_old, extra_env=_serial)
        _rc_b, _out_b = drive(TRIO, None, mod=rs, extra_env=_serial)
        _ha, _hb = _norm_run(_out_a), _norm_run(_out_b)
        _diff = next((i for i, (x, y) in enumerate(zip(_ha.splitlines(), _hb.splitlines()))
                      if x != y), None)
        ok(_rc_a == 0 and _rc_b == 0 and _ha == _hb,
           "H1 缺省路径（无旋钮）输出与改前执行器逐字节一致",
           "首处差异行=%s" % (_diff if _diff is not None else "-"))

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
