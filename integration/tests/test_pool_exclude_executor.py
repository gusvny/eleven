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
- H 缺省路径与改前执行器（git HEAD 快照）在假表上逐字节一致（验收 B 的源码级 A/B；
  前提=HEAD 快照不含批台机制——本票 t260921-06 落盘后 HEAD 已含之，前提失效期 H1
  转 N/A 点名（三态契约：系统状态条件子用例），H2 负锁照常执法）。

安全红线：假场景脚本全部落 TemporaryDirectory（真仓零触碰）；每子用例显式 env 桩
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
# 缺省 INTEG_SUMMARY 键集基线（B3 逐键全等锁）。**新增键必须来这里登记一次**——
# 该锁的意义就是逼每个往回执里加键的改动显式登记（防「悄悄多一个键」把消费方打散）。
# 260928 登记两键（本锁在 main 上长红的真因：后续票加了键、基线没跟）：
#   budget_env = 260928 集成预算 env 键（run_scenarios 预算旋钮随回执回显，缺席="absent"）；
#   timings    = 执行器耗时分解（prelude_s/scenarios_s，t260913-02 前后的可观测面）。
# 260929 登记两键（直修 B1·宿主令不开票）：环境红**具名**通道——
#   env_red_names = 判为环境面的场景名（判据=执行器既有 env_like：exit 2 / spawn -8），
#                   排序去重；env_red_count = 其条数（int）。恒在场（全绿时 []/0）。
DEFAULT_SUMMARY_KEYS = {
    "ran", "pass", "fail", "not_checked", "wall_s", "concurrency",
    "pool_config", "env_fingerprint", "expected", "budget_env", "timings",
    "env_red_names", "env_red_count",
}

_spec = importlib.util.spec_from_file_location(
    "rs_exclude_under_test", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

pass_n = fail_n = na_n = 0


def ok(cond, label, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label + (" | " + str(detail)[:500] if detail else ""))


def na(label, reason):
    """N/A 段（三态契约：仅系统状态条件子用例可 N/A；全 N/A=场景红由 finish 兜底）。"""
    global na_n
    na_n += 1
    print("  N/A: %s（%s）" % (label, str(reason)[:400]))


@contextlib.contextmanager
def env_stub(value, extra=None):
    """显式 env 桩：save/restore；value=None 表示清除该键（缺省形态子用例必须清）。
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
    （缺省=本仓执行器；H 子用例用改前快照）。
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
        # t260921-06 arbitrate：批台预起/收口（t260921-06 批级共享）是真 docker 面钩子，
        # 与下方卫生钩子同族——本电池头注红线「零端口零 docker 零控制台」要求一并置空；
        # 否则含 engine/exclusive 条目的假表缺省轮会真起台（快照模块在 tmp 语境则预起
        # 失败整轮拒跑），既违约电池契约又让 A/B 比对失真。改前快照模块无此钩子=跳过。
        saved_preboot = saved_teardown = None
        if hasattr(mod, "batch_preboot"):
            saved_preboot, saved_teardown = mod.batch_preboot, mod.batch_teardown
            mod.batch_preboot = lambda consumers: True
            mod.batch_teardown = lambda: None
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
            if saved_preboot is not None:
                mod.batch_preboot, mod.batch_teardown = saved_preboot, saved_teardown
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

# ---- C6/C7 环境红具名通道（260929 直修 B1，纯加性）----
# 口径：只有计数没有名单时，闸/票面答不出「红的是哪几条」；C6 锁**全绿时键在场且为空**
# （消费方无需分支），C7 锁**真值来自既有 env_like 判据**（exit 2）+ 既有计数/rc 零改动。
ok(bool(_sum) and _sum.get("env_red_names") == [] and _sum.get("env_red_count") == 0,
   "C6 全绿轮 env_red_names=[] 且 env_red_count=0（键在场，缺省非缺键）", _sum)
rc, out = drive([("t913-green", None, "print('g')\n"),
                 ("t913-envred", None, "import sys\nsys.exit(2)\n"),
                 ("t913-prodred", None, "import sys\nsys.exit(1)\n")], None)
_sum = summary_of(out)
ok(rc == 1, "C7a 产品红优先的 rc 三态语义不变（1）", rc)
ok(bool(_sum) and _sum.get("env_red_names") == ["t913-envred"]
   and _sum.get("env_red_count") == 1,
   "C7b 环境红具名=判为 env_like 的那条（产品红不入名单）", _sum)
ok(bool(_sum) and (_sum.get("ran"), _sum.get("pass"), _sum.get("fail"),
                   _sum.get("not_checked")) == (3, 1, 1, 1),
   "C7c 既有计数逐项不变（3/1/1/1）", _sum)

# ---- D 非法 token：剥离+点名，合法部分照常生效 ----
rc, out = drive([("t913-main", None, "print('m')\n"),
                 ("t913-engine", "engine", "print('e')\n")],
                "Engine, engine ,, bad token")
ok(rc == 0, "D1 非法 token 不改变退出码语义（rc=0）", rc)
ok("EXCLUDE_POOLS_WARN [Engine]" in out and "EXCLUDE_POOLS_WARN [bad token]" in out,
   "D2 非法 token 逐条点名")
ok("本轮跳过池=engine（少 1 条）" in out and "PASS [t913-engine]" not in out,
   "D3 合法部分照常生效")

# ---- E 既有电池在排除 env 继承下照常绿（R2 机械回归用例）----
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
    """归一化耗时/时间戳/指纹等运行语境字段（结构面逐字节比对）。

    t260914-01（arbitrate 段 tests-fault 迭代）补两类**墙钟噪声派生**的注释面：
    ①每池「并行关键路径=是/否」——判据是 `s == max(池耗时)`，毫秒级抖动即翻面；
    ②「耗时分解」块内的行序（每池串行合计按耗时降序、最慢 Top15 按 dur_s 排序，
      近似并列时次序不稳）。两处都是**机器快慢的产物，不是池排除旋钮的行为**，
    参与逐字节比对＝负载下一次假红（实测 260914 10:26 全量跑红，单跑 6/6 绿）。
    归一化只掩时间派生注释：rc、每条场景行、清单/汇总键值、池归属一律照旧逐字节比对；
    同处新增 H2 负锁证明归一化不吞行为差异（否则 H1 会退化成恒真）。
    """
    out = re.sub(r'"dur_s": [\d.]+', '"dur_s": N', out)
    out = re.sub(r'"started": "[^"]*"', '"started": "T"', out)
    out = re.sub(r"\d+(?:\.\d+)?s", "Ns", out)
    out = re.sub(r'"wall_s": [\d.]+', '"wall_s": N', out)
    out = re.sub(r'"env_fingerprint": "[0-9a-f]+"', '"env_fingerprint": "F"', out)
    out = re.sub(r"integration-report-\d+-\d+\.json", "integration-report-T.json", out)
    # 同族抖动（第二批）：块内行自带**耗时派生布尔**「并行关键路径=是/否」（判据
    # s == max(by_pool.values())）——耗时并列时该布尔自身翻面（实测同模块连跑可得是/否两种），
    # 与耗时数值同类属运行语境字段，一并归一为 "?"（确定序场景下该字段本无信息差）。
    out = re.sub(r"并行关键路径=[是否]", "并行关键路径=?", out)
    # t260913-01 仲裁修（H1 抖动根治）：执行器有两个**按耗时排序**的报告块，耗时并列时
    # 次序随调度抖动——实测同一模块连跑 6 次得 3 种池序（main,ro,engine ×4 /
    # ro,engine,main ×1 / main,engine,ro ×1），列值已被上行归一为 "Ns" 后仅剩顺序差异，
    # H1 的逐字节比对因此必假红（契约不可满足）。此处对这两块**块内行排序**：内容仍逐字节
    # 比对，只归一调度抖动；其余行序保持严格逐字节。
    _lines, _res, _i = out.splitlines(), [], 0
    _heads = ("耗时分解", "最慢 Top15")
    while _i < len(_lines):
        _res.append(_lines[_i])
        if any(_lines[_i].startswith(h) for h in _heads):
            _j = _i + 1
            while _j < len(_lines) and _lines[_j].startswith("  "):
                _j += 1
            _res.extend(sorted(_lines[_i + 1:_j]))
            _i = _j
            continue
        _i += 1
    return "\n".join(_res)


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
        # t260921-06 arbitrate 前提判定：A/B 的语义前提=HEAD 是「改前」快照。批台机制
        # 随本票 implement 已由 worker 代落盘进 HEAD（0ac0aa2）后，「改前」对象不存在，
        # 且快照执行器在 tmp 语境（清单/stage_docker 缺席）会按批台契约拒绝开跑——
        # 与工作树执行器的输出差是**运行语境差**而非行为差，逐字节比对不可满足也不可比。
        # 该前提失效期 H1 转 N/A（点名理由与覆盖承担者），其余段与 H2 负锁照常执法。
        _head_is_pre_batch = not any(
            k in _old.stdout for k in ("batch_preboot", "BATCH_STAGE_WARN", "batch-stage"))
        if not _head_is_pre_batch:
            # 前提失效期仍取当前执行器 TRIO 基线：H2 负锁需要 _hb 作比对锚。
            _rc_b, _out_b = drive(TRIO, None, mod=rs, extra_env=_serial)
            _hb = _norm_run(_out_b)
            na("H1 缺省路径（无旋钮）输出与改前执行器逐字节一致",
               "前提失效：HEAD 快照已含批台机制（worker 代落盘），「改前」对象不存在；"
               "缺省路径回归由看守① t260921-06-batch-runner-form（真全轮形态）+本电池其余段"
               "+H2 负锁承担；premise=batch_preboot|BATCH_STAGE_WARN|batch-stage ∈ HEAD 快照")
        else:
            _rc_a, _out_a = drive(TRIO, None, mod=_mod_old, extra_env=_serial)
            _rc_b, _out_b = drive(TRIO, None, mod=rs, extra_env=_serial)
            _ha, _hb = _norm_run(_out_a), _norm_run(_out_b)
            _la, _lb = _ha.splitlines(), _hb.splitlines()
            _diff = next((i for i, (x, y) in enumerate(zip(_la, _lb)) if x != y), None)
            _dd = ""
            if _ha != _hb:   # 报错必须可诊：点名首处差异行的两侧原文与行数（旧版只说「行号」）
                _i = _diff if _diff is not None else min(len(_la), len(_lb))
                _dd = "首处差异行=%d（行数 %d/%d）｜A: %s｜B: %s" % (
                    _i, len(_la), len(_lb),
                    (_la[_i] if _i < len(_la) else "<A 无此行>")[:200],
                    (_lb[_i] if _i < len(_lb) else "<B 无此行>")[:200])
            ok(_rc_a == 0 and _rc_b == 0 and _ha == _hb,
               "H1 缺省路径（无旋钮）输出与改前执行器逐字节一致", _dd)
        # H2 负锁（t260914-01 arbiter 补）：归一化不得吞行为差异——多一条 main 条目的
        # 探针表跑当前执行器，归一化后必须与 TRIO 的结果不同（否则 H1 是恒真断言）。
        _QUAD = TRIO + [("t913-main2", None, "print('m2')\n")]
        _rc_c, _out_c = drive(_QUAD, None, extra_env=_serial)
        _hc = _norm_run(_out_c)
        ok(_rc_c == 0 and _hc != _hb,
           "H2 负锁：归一化不吞行为差异（探针表多一条条目必须可比出来）",
           "rc=%s 归一化后与 H1 相同=%s" % (_rc_c, _hc == _hb))

print("SUMMARY pass=%d fail=%d env_fail=0 na=%d" % (pass_n, fail_n, na_n))
sys.exit(1 if (fail_n > 0 or (pass_n + fail_n == 0 and na_n > 0)) else 0)
