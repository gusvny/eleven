#!/usr/bin/env python3
"""t260912-01 执行器两套计数单源化回归（集成 L2/L3，灰盒）。

用户可感知契约（被钉面）：同一次跑里，执行器的两套汇总——文本三态行
`SCENARIOS ran=…` 与规范行明细重算行 `INTEG_SUMMARY {…}`——必须同源同值；
子进程（场景）stdout 里的任何 JSON 行**不得**进入计数（既不灌水、也不顶替
真实红绿），执行器 stdout 里能被闸当规范行解析的候选必须与 INTEG_SUMMARY
一致（闸复核权威=闸重算，verify_lane 逐行 strip 后 `{`/`[` 即候选）；
两套计数一旦分叉=汇总谎报，必须响亮产品红（FAIL [__executor__] 点名 + rc=1），
绝不静默放行（宿主 260912 实锤：SCENARIOS ran=223 pass=209 fail=2 env_fail=12
与 INTEG_SUMMARY pass=210 fail=1 四数分叉照常出绿）。

故障面覆盖：嵌套/外来 JSON 灌水与真红顶替（②病灶）、畸形行三态（非对象/
缺字段/坏 JSON）不炸不计数、通过桩混入 JSON 不双计、闸候选污染、谎报双向
（灌水/漏收/综合行与退出码相反）必红。

intent 分界：与 t260910-13-failure-protocol-gate（彼=闸解析/归属决策表真缝，
经 admin.py 调 verify_lane）不同面——本条守**执行器自身**两套计数的单源化与
谎报即红；与 t260910-13-executor-fail-closed（彼=条目完整性：池级异常上浮、
spawn 分类落红、ran==在册数）不同面——本条守**计数纯度**，条目数不变。
协议注入缝全部走公共函数（failure_protocol.recount / parse_spec_line /
lib_result.spec_line），不锚执行器内部私有名。

退出契约：末行 SUMMARY；exit 1 iff fail>0。实现段落地前红属预期（TDD 信号，
S1/S2/S3 族钉的是未落地修复），arbitrate/merge 期必须绿。
"""
import contextlib
import io
import json
import re
import sys
from importlib import util as _ilu
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "server" / "engine"))
import failure_protocol as fp   # 与 run_scenarios 内 import 同一 sys.modules 对象（公共注入缝）
import lib_result               # 综合行生产出口（公共注入缝）

passed = failed = 0


def ok(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok  %s" % label)
    else:
        failed += 1
        print("  FAIL %s %s" % (label, str(detail)[:400]))


def load_rs():
    spec = _ilu.spec_from_file_location(
        "rs_count_purity", str(REPO / "integration" / "run_scenarios.py"))
    rs = _ilu.module_from_spec(spec)
    spec.loader.exec_module(rs)
    return rs


def run_main(rs, scenarios):
    """被测面=执行器结算计数；docker 卫生与本票无关，桩掉（隔离 + 秒级）。
    260913 merge 后执行器起跑有**两处** preflight（t260910-14 `_docker_hygiene` +
    t260912-02 `_sweep_residue_stages`）——一并桩掉，否则 docker 完备宿主上每腿
    真跑 sweep（单次超时上限 300s）会把本回归拖爆。"""
    rs.SCENARIOS = list(scenarios)
    rs._docker_hygiene = lambda: None
    rs._sweep_residue_stages = lambda: None
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            code = rs.main()
        except SystemExit as ex:   # 兼容防御（main 不应 SystemExit）
            code = ex.code
    return code, buf.getvalue()


def parse_summary(out):
    """两套汇总行的公开读面：文本三态行 + INTEG_SUMMARY JSON 行。"""
    m = re.search(r"^SCENARIOS ran=(\d+) pass=(\d+) fail=(\d+) env_fail=(\d+) na=(\d+)",
                  out, re.M)
    scen = None
    if m:
        scen = {"ran": int(m.group(1)), "pass": int(m.group(2)),
                "fail": int(m.group(3)), "env_fail": int(m.group(4))}
    smry = None
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                smry = json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                smry = None
    return scen, smry


def gate_candidates(out):
    """闸同款解析口径（verify_lane：逐行 strip 后首字符 {/[ 即候选）。"""
    cands, malformed = [], []
    for ln in out.splitlines():
        s = ln.strip()
        if s[:1] in ("{", "["):
            p = fp.parse_spec_line(s)
            if p is None or "__malformed__" in p:
                malformed.append(s[:120])
            else:
                cands.append(fp.normalize_case(p))
    return cands, malformed


# ---------------- 桩条目（serial 四元组：池内严格串行，顺序由构造确定） ----------------
NESTED = '{"name":"nested","status":"pass","evidence":"x"}'
LEAK_FAIL = ("stub-leak-fail", "嵌套 JSON 混入 stdout 的失败桩（验收②合成样）",
             "printf '%%s\\n' '%s'; echo l1; echo l2; echo l3; echo l4; exit 1" % NESTED,
             "serial")
LEAK_PASS = ("stub-leak-pass", "嵌套 JSON 混入 stdout 的成功桩（灌水面）",
             "printf '%%s\\n' '{\"name\":\"nested-pass\",\"status\":\"pass\"}'; echo done",
             "serial")
MALFORMED = ("stub-malformed", "畸形行混入 stdout 的成功桩",
             "printf '%%s\\n' '{not-json' '[1,2' '{\"noname\":1}'; true", "serial")
P1 = ("stub-ok", "纯桩：直接成功", "true", "serial")
P2 = ("stub-ok-2", "纯桩二：直接成功", "true", "serial")
FLIP_P2F = ("stub-flip-to-fail", "综合行被翻转成 fail 的成功桩（分叉注入）", "true", "serial")
FLIP_F2P = ("stub-flip-to-pass", "综合行被翻转成 pass 的失败桩（分叉注入）", "false", "serial")

# ---------------- S0 对照：纯桩双行一致（自校验不误伤正常面） ----------------
rs = load_rs()
code, out = run_main(rs, [P1, P2])
scen, smry = parse_summary(out)
ok(code == 0, "S0a 纯桩全绿 → rc=0", "rc=%r" % code)
ok(scen == {"ran": 2, "pass": 2, "fail": 0, "env_fail": 0},
   "S0b SCENARIOS 行=2/2/0/0", scen)
ok(bool(smry) and smry.get("ran") == 2 and smry.get("pass") == 2
   and smry.get("fail") == 0 and smry.get("not_checked") == 0,
   "S0c INTEG_SUMMARY 与文本行逐字段一致", smry)
ok(bool(smry) and smry.get("expected") == 2,
   "S0d INTEG_SUMMARY.expected=在册数（ran==在册数判据在场）", smry)

# ---------------- S1 验收②合成样：嵌套 JSON 不得顶替真红 ----------------
rs = load_rs()
code, out = run_main(rs, [LEAK_FAIL])
scen, smry = parse_summary(out)
ok(code == 1 and scen == {"ran": 1, "pass": 0, "fail": 1, "env_fail": 0},
   "S1a 失败桩真红如实在文本行（fail=1 非 pass）", "rc=%r scen=%r" % (code, scen))
ok(bool(smry) and smry.get("ran") == 1 and smry.get("pass") == 0
   and smry.get("fail") == 1 and smry.get("not_checked") == 0,
   "S1b INTEG_SUMMARY 不被嵌套 pass 行灌水/重分类（明细=本层综合）", smry)
ok(bool(smry) and smry.get("expected") == 1,
   "S1c expected=在册数（嵌套行不算在册）", smry)

# ---------------- S1c 通过桩混入 JSON：不灌水不双计 ----------------
rs = load_rs()
code, out = run_main(rs, [LEAK_PASS])
scen, smry = parse_summary(out)
ok(code == 0 and scen == {"ran": 1, "pass": 1, "fail": 0, "env_fail": 0},
   "S1d 成功桩混入 JSON → 文本行照常 1/1", "rc=%r scen=%r" % (code, scen))
ok(bool(smry) and smry.get("ran") == 1 and smry.get("pass") == 1,
   "S1e 明细 ran=1 pass=1（嵌套行不双计）", smry)

# ---------------- S1b 畸形行：不炸、不计数、两行一致 ----------------
rs = load_rs()
code, out = run_main(rs, [MALFORMED])
scen, smry = parse_summary(out)
ok(code == 0, "S1f 畸形行不炸执行器（rc=0）", "rc=%r" % code)
ok("INTEG_SUMMARY_ERROR" not in out, "S1g 汇总行无错误留痕（畸形行静默不影响计数面）",
   out[-300:])
ok(bool(smry) and scen is not None and smry.get("ran") == scen["ran"]
   and smry.get("pass") == scen["pass"],
   "S1h 畸形行不计数、两行一致", (scen, smry))

# ---------------- S2 闸同款解析腿：闸候选=本层综合行，无嵌套名 ----------------
rs = load_rs()
code, out = run_main(rs, [LEAK_FAIL])
cands, malformed = gate_candidates(out)
names = sorted({c["name"] for c in cands})
ok(names == ["stub-leak-fail"],
   "S2a 闸候选只含本层综合行（嵌套 JSON 不成候选）", names)
ok(not malformed, "S2b 闸侧零畸形候选（回显面无坏行）", malformed)
_, smry = parse_summary(out)
real = fp.recount(cands) if cands else None
ok(bool(real and smry) and real["ran"] == smry.get("ran")
   and real["pass"] == smry.get("pass") and real["fail"] == smry.get("fail")
   and real["not_checked"] == smry.get("not_checked"),
   "S2c 闸重算==INTEG_SUMMARY 逐字段（复核权威可对上）", (real, smry))
ok(bool(real and smry) and real["ran"] == smry.get("expected"),
   "S2d 闸重算 ran==在册数（清单完整）", (real, smry))

# ---------------- S3 负锁：谎报必红（注入缝=协议/综合行公共函数） ----------------
# S3a 灌水：recount 面多出 1 ran + 1 pass（模拟任何未来路径向明细灌水）
rs = load_rs()
_orig_recount = fp.recount


def _inflate(cases):
    r = dict(_orig_recount(cases))
    r["ran"] += 1
    r["pass"] += 1
    return r


fp.recount = _inflate
try:
    code, out = run_main(rs, [LEAK_PASS])
finally:
    fp.recount = _orig_recount
ok(code == 1, "S3a 灌水（明细多 1ran+1pass）→ rc=1 谎报必红", "rc=%r" % code)
ok("FAIL [__executor__]" in out, "S3a' 分叉点名 FAIL [__executor__]（不静默）", out[-300:])

# S3b 漏收：首条综合行解析丢弃 → 明细 ran<rc ran（双桩：单条目漏收落在声明的
# 降级路径里，明细空=回落旧计数，机械不可检出——故本腿必须 ≥2 条目）
rs = load_rs()
_orig_parse = fp.parse_spec_line
_state = {"n": 0}


def _drop_first(line):
    _state["n"] += 1
    if _state["n"] == 1:
        return None
    return _orig_parse(line)


fp.parse_spec_line = _drop_first
try:
    code, out = run_main(rs, [P1, P2])
finally:
    fp.parse_spec_line = _orig_parse
ok(code == 1, "S3b 漏收（明细 ran<rc ran）→ rc=1 谎报必红", "rc=%r" % code)
ok("FAIL [__executor__]" in out, "S3b' 漏收点名 FAIL [__executor__]", out[-300:])

# S3c/d 分叉双向：综合行与退出码相反（行生产出口翻转）
_orig_spec_line = lib_result.spec_line


def _flip_to_fail(**kw):
    if kw.get("name") == FLIP_P2F[0]:
        kw = dict(kw)
        kw.update(status="fail", cause="self", reason="assert_mismatch",
                  evidence="注入：规范行与退出码相反（谎报样本）")
    return _orig_spec_line(**kw)


lib_result.spec_line = _flip_to_fail
try:
    code, out = run_main(rs, [FLIP_P2F])
finally:
    lib_result.spec_line = _orig_spec_line
ok(code == 1 and "FAIL [__executor__]" in out,
   "S3c 行翻转 fail×退出0 → 谎报必红（rc=1 + 点名）", "rc=%r" % code)

_orig_spec_line = lib_result.spec_line


def _flip_to_pass(**kw):
    if kw.get("name") == FLIP_F2P[0]:
        kw = dict(kw)
        kw.update(status="pass")
    return _orig_spec_line(**kw)


lib_result.spec_line = _flip_to_pass
try:
    code, out = run_main(rs, [FLIP_F2P])
finally:
    lib_result.spec_line = _orig_spec_line
ok("FAIL [__executor__]" in out,
   "S3d 行翻转 pass×退出1 → 明细与计数分叉必被点名（产品红在场）", out[-300:])

# ---------------- S3e _counts_mismatch 纯函数单元三态（t260912-01 方案 #3） ----------------
# 与 S3a/b/c/d 的全管线腿互补：helper 直调三态锁「分叉识别」本身，不依赖管线组装。
# K3 降级边界在案：明细为空（含单条目独苗被漏收）= 声明降级面——INTEG_SUMMARY 走
# rc 回落支路、helper 返 None 不判红；此时执行器 stdout 上的综合行仍在、闸侧独立
# recount 与 rc 计数一致，不构成谎报面。故漏收可机械检出的前提=明细非空且 ran<rc
# ran（S3b 用 ≥2 条目正是此前提）。
case_pass = fp.normalize_case(json.loads(NESTED))
case_fail = fp.normalize_case(json.loads(NESTED.replace('"pass"', '"fail"')))
ok(rs._counts_mismatch([case_pass], 1, 1, 0, 0) is None,
   "S3e-1 helper：明细与 rc 一致 → None")
ok(rs._counts_mismatch([case_pass, case_fail], 1, 1, 0, 0) is not None,
   "S3e-2 helper：灌水（明细多一条）→ 点名")
ok(rs._counts_mismatch([case_pass], 2, 2, 0, 0) is not None,
   "S3e-3 helper：漏收（明细缺一条）→ 点名")
ok(rs._counts_mismatch([], 1, 1, 0, 0) is None,
   "S3e-4 helper：空明细=声明降级面 → None（K3 边界在案）")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
sys.exit(1 if failed else 0)
