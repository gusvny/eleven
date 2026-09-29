#!/usr/bin/env python3
"""Fast static lint for test assets (added by host order t260902).

Runs in seconds right after writing code — a red here, not after waiting for
the whole suite. It covers the reverse side of four real accidents seen in
practice:
  L1 syntax: compile-check every integration/**/*.py and workbench/tests/*.mjs
        (bad hyphens in names, unbalanced brackets go red here, not at
        pytest collection time)
  L2 collection: engine/tests pytest --collect-only (import errors,
        missing fixtures)
  L3 paths: relative imports in workbench/tests/*.mjs must resolve
        (a wrong depth goes red immediately)
  L4 registry: SCENARIOS entries structurally complete — unique names,
        non-empty intent, cmd scripts must exist
  L5 orphans: test-shaped files under integration/**/ not in SCENARIOS and
        not in the exemption table → warning
  L8 tmp hygiene: a file that calls mkdtemp* must reclaim somewhere in the same
        file (registry + exit hook / rmtree / TemporaryDirectory / dispose) —
        new call sites on a file with no reclaim verb → warning (260926: the
        $TMPDIR leak reached 400k dirs / 98.6% older than 6h before anyone
        noticed; this is the mechanical brake against new debt)

Usage: python3 integration/lint_tests.py (cwd = repo root; exit 0 = pass)
       python3 integration/lint_tests.py --write-tmpdir-baseline   # regenerate L8's
       grandfather list (existing debt; only new debt may turn L8 yellow)
"""
import atexit
import json
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INTEG = REPO / "integration"
WB_TESTS = REPO / "server/plugins/workbench/tests"          # ← project parameter (fork: change here)
WD_TESTS = REPO / "server/plugins/watchdog/tests"           # t260928-28: watchdog UT 纳入 L1/L3 同一套静态锁
TP_TESTS = REPO / "server/engine/tests"          # ← project parameter
VENV_PY = REPO / "server/engine/.venv/bin/python"  # ← project parameter
# 260926 磁盘泄漏修（同类普查发现）：本目录此前从不回收——宿主 $TMPDIR 实测
# `lint-pyc-*` 攒了 6153 个 / 约 6.0GB（每次 lint 落一份全仓 pyc，10.7 天）。
# atexit 兜底：正常/异常/早退所有终态都回收；导入本模块的场景（t260920-03）同样受此回收。
PYC = tempfile.mkdtemp(prefix="lint-pyc-")
atexit.register(shutil.rmtree, PYC, ignore_errors=True)

errors, warns = [], []


def err(msg):
    errors.append(msg)
    print("ERROR " + msg, flush=True)


def warn(msg):
    warns.append(msg)
    print("WARN  " + msg, flush=True)


def ok(msg):
    print("ok    " + msg, flush=True)


# L1 syntax
def lint_syntax():
    n_py = n_mjs = 0
    for f in INTEG.rglob("*.py"):
        try:
            py_compile.compile(str(f), cfile=str(Path(PYC) / (f.name + ".pyc")), doraise=True)
            n_py += 1
        except py_compile.PyCompileError as e:
            err("L1 语法 %s: %s" % (f.relative_to(REPO), str(e).splitlines()[-1][:120]))
    for tests_dir in (WB_TESTS, WD_TESTS):
        if tests_dir.is_dir():
            for f in tests_dir.glob("*.mjs"):
                p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
                if p.returncode != 0:
                    err("L1 语法 %s: %s" % (f.relative_to(REPO), (p.stderr or "").splitlines()[-1][:120]))
                else:
                    n_mjs += 1
    # Also syntax-check every integration/**/*.mjs (t260907-04: a mechanical
    # sweep appended a python-style `# naming-compat` line into an mjs file,
    # and the SyntaxError only blew up when the suite ran — this second-level
    # lint should have caught it; L1 originally checked only workbench/tests
    # mjs, which left the blind spot)
    for f in INTEG.rglob("*.mjs"):
        p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        if p.returncode != 0:
            err("L1 语法 %s: %s" % (f.relative_to(REPO), (p.stderr or "").splitlines()[-1][:120]))
        else:
            n_mjs += 1
    ok("L1 语法：py %d / mjs %d 通过" % (n_py, n_mjs))


# L2 pytest collection
def lint_collect():
    td = TP_TESTS
    if not td.is_dir():
        return
    venv_py = VENV_PY
    py = str(venv_py) if venv_py.exists() else sys.executable
    # Check the tool itself first (t260903-11): pytest missing = a missing
    # tool surface (visible WARN), not a "collection failure" — the error
    # must say exactly which check could not run.
    probe = subprocess.run([py, "-c", "import pytest"], capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        warn("L2 pytest 不可用（%s 无 pytest）：收集检查无法执行——工具面缺失，非收集失败"
             % ("venv" if venv_py.exists() else "系统解释器"))
        return
    p = subprocess.run([py, "-m", "pytest", str(td), "-q", "--collect-only"],
                       capture_output=True, text=True, timeout=180)
    m = re.search(r"(\d+) errors?", p.stdout)
    if p.returncode != 0 and (m is None or int(m.group(1)) > 0):
        first = next((l for l in p.stdout.splitlines() if l.startswith("E ")), "")
        err("L2 pytest 收集失败：%s" % (first[:140] or p.stdout[-140:]))
    else:
        cnt = re.search(r"(\d+) tests? collected", p.stdout)
        ok("L2 pytest 收集：%s 条" % (cnt.group(1) if cnt else "?"))


# L3 mjs relative import resolution
def lint_mjs_imports():
    bad = 0
    for tests_dir in (WB_TESTS, WD_TESTS):
        if not tests_dir.is_dir():
            continue
        for f in tests_dir.glob("*.mjs"):
            text = f.read_text()
            for m in re.finditer(r"""(?:from\s+|import\s*\(\s*)['"](\.\.?/[^'"]+)['"]""", text):
                tgt = (f.parent / m.group(1)).resolve()
                if not tgt.exists():
                    err("L3 import 悬空 %s → %s" % (f.name, m.group(1)))
                    bad += 1
    if bad == 0:
        ok("L3 mjs 相对 import 全部可解析")


# L4/L5 SCENARIOS registry
EXEMPT = {
    "conftest.py", "fixture.py", "fixture.mjs", "lib.mjs", "cases.json",
    "golden.mjs", "reconcile-tokens.mjs", "build-info.mjs", "lib",
    # t260901-20: the aggregate entry is registered; t0*.mjs are its sub-checks
    "t01_gate_shape.mjs", "t01_params_cache.mjs", "t02_cache_lifecycle.mjs",
    "t03_views_e2e.mjs", "t04_cli_door.mjs", "t05_dual_door.mjs",
    "t07_acceptance_walkthrough.mjs", "t06_results_doc.mjs",
    "registry-loader.py", "README.md", "check.sh", "smoke-realdata-report.md",
}
TEST_SHAPE = re.compile(r"^sc_")


def lint_registry():
    sys.path.insert(0, str(INTEG))
    import run_scenarios as rs  # noqa: E402
    names = [e[0] for e in rs.SCENARIOS]
    if len(names) != len(set(names)):
        dup = [n for n in set(names) if names.count(n) > 1]
        err("L4 清单重名：%s" % dup)
    missing_intent = [e[0] for e in rs.SCENARIOS if len(e) < 2 or not str(e[1]).strip()]
    if missing_intent:
        err("L4 intent 缺失：%s" % missing_intent)
    bad_cmd = []
    for entry in rs.SCENARIOS:
        name, intent, cmd = entry[0], entry[1], entry[2]
        script = next((p for p in str(cmd).split() if p.startswith("integration/")), None)
        if script and not (REPO / script).exists():
            bad_cmd.append("%s → %s" % (name, script))
    if bad_cmd:
        err("L4 cmd 脚本悬空：%s" % "; ".join(bad_cmd[:5]))
    if not errors:
        ok("L4 清单：%d 条三元组完整" % len(names))
    # L5 orphans (pure pattern match): an sc_* file not registered is an
    # error; non-sc_ files are shared code and fine
    registered = set()
    for entry in rs.SCENARIOS:
        name, intent, cmd = entry[0], entry[1], entry[2]
        for p in str(cmd).split():
            if p.startswith("integration/"):
                registered.add((REPO / p).resolve())
    # t260904-12 deregistration whitelist (final doc §7.3 "cannot run in the
    # gate" channel; the file stays in the repo for the main-repo manual list
    # and is not in SCENARIOS — see the ticket-lifecycle entry under
    # "Known limitations" in README)
    DEREGISTERED = {INTEG / "baselines" / "sc_ticket_lifecycle.mjs",
                    INTEG / "t260917-01" / "sc_t260917_01_arb_gate_refusal.mjs"}
    orphans = [str(f.relative_to(REPO)) for f in INTEG.rglob("sc_*")
               if f.is_file() and f.resolve() not in registered
               and f.resolve() not in DEREGISTERED]
    if orphans:
        err("L5 孤儿场景（sc_ 未登记）：%s" % orphans[:6])
    else:
        ok("L5 无孤儿（非 sc_ 文件视为共享代码，不检查）")


# L6 three-state contract (t260904-12: no SKIP inside the gate, final doc
# §7.3) — anchored on real shapes, not on the literal [SKIP] text (the runtime
# template string `[$ {status.toUpperCase()}]` is invisible to grep, so a
# literal match would be vacuously true).
SKIP_STATE = re.compile(r"""['"`]skip['"`]""")            # skip status literal in mjs/py
SKIP_SUMMARY = re.compile(r"skip=\{|\bskip=%d|skip=\$\{|SUMMARY[^\n]*\bskip=")
ENV0_COMBO = re.compile(                                   # missing-env → exit 0 combo
    r"ENV_FAIL[^\n]*\n[^\n]*exit\(0\)|skip[^\n]*\n[^\n]*exit\(0\)", re.I)
# Comment lines and "retired" notes do not participate (historical mentions
# are legal; the behavior side is pinned by the summarize-shape guard and the
# guard scenarios)
RETIRED = re.compile("退役")


def _code_lines(text):
    for ln in text.splitlines():
        st = ln.strip()
        if RETIRED.search(ln) or st.startswith("//") or st.startswith("#") or st.startswith("*"):
            continue
        yield ln
SKIP_WHITELIST = {  # files with comment-only historical mentions (by file
    "bench.py",        # name; residue is reconciled by the closing evidence)
    "run_scenarios.py",  # docstring note about the old semantics
}


def lint_three_state():
    bad_state, bad_sum, bad_combo = [], [], []
    for f in list(INTEG.rglob("*.mjs")) + list(INTEG.rglob("*.py")):
        if f.name in SKIP_WHITELIST or f.name == "lint_tests.py":
            continue
        text = f.read_text(errors="replace")
        rel = f.relative_to(REPO)
        for i, ln in enumerate(_code_lines(text), 1):
            if SKIP_STATE.search(ln):
                bad_state.append("%s:%d" % (rel, i))
            if SKIP_SUMMARY.search(ln):
                bad_sum.append("%s:%d" % (rel, i))
        if ENV0_COMBO.search("\n".join(_code_lines(text))):
            bad_combo.append(str(rel))
    if bad_state:
        err("L6 skip 状态值残留（词表只认 pass/fail/env_fail/na）：%s" % bad_state[:8])
    else:
        ok("L6 无 skip 状态值残留")
    if bad_sum:
        err("L6 SUMMARY 旧形状 skip= 计数残留：%s" % bad_sum[:8])
    else:
        ok("L6 SUMMARY 无 skip 计数")
    if bad_combo:
        err("L6 「skip→exit 0」语义组合残留（缺环境必须 exit 2）：%s" % bad_combo[:8])
    else:
        ok("L6 无 skip→exit0 语义组合")
    # makeResults/summarize shape guard: a custom summarize in mjs must use
    # the three-state exit codes
    for f in INTEG.rglob("*.mjs"):
        text = f.read_text(errors="replace")
        if "function summarize" in text or "summarize()" in text and "process.exit" in text:
            if re.search(r"process\.exit\(f > 0 \? 1 : 0\)", text):
                err("L6 %s summarize 仍旧二态退出码（须 f>0||allNa?1:(e>0?2:0)）" % f.relative_to(REPO))
                break
    else:
        ok("L6 summarize 退出码形状合规")


def _lint_targets():
    """L7 的待判文件集：**git 认识的文件**（已跟踪 + 未跟踪但未被忽略）。

    为什么不用 REPO.rglob 全量：仓里存在宿主侧被 gitignore 的配置目录
    （host 侧 epic 声明那类），它们不进版本库、别的 checkout 里根本不存在——拿它们判红是
    「不可复现的红」，看守必须只判仓库内容。反之泳道里新写、还没提交的场景
    文件（未跟踪但未被忽略）必须判——新用法正是在那里产生。非 git 目录
    （或 git 不可用）退化为 rglob，宁严不松。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-c", "-o", "--exclude-standard", "-z"],
            capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            return [REPO / r for r in out.stdout.split("\0") if r]
    except Exception:                            # noqa: BLE001 —— git 不可用=退化不判错
        pass
    return [p for p in REPO.rglob("*") if p.is_file()]


def lint_terminology():
    """L7 术语废止看守（宿主令 260920）：行话旧称（被禁词，真源=docs/terminology.md「禁用对照」）不得新增。

    判据=**按文件的出现次数基线**（integration/terminology-baseline.json，随本规则
    一起落盘）：① 基线里没有的文件出现该词 → 红；② 基线里有的文件超出记录次数
    （=在既有文件里新增用法）→ 红；③ 基线 allowlist（值 -1，如 docs/terminology.md
    本身必须能写出被禁词）不受限。红行点名文件与实际/上限，方便定位。

    为什么是「次数上限」而不是「零容忍」：存量 260920 实测约 3170 处 / 405 文件
    （integration 2664／server 442／docs 34／notes 30），一次清空会让闸全红；次数上限
    让**新增立刻红**、同时随替换批次自然收缩（基线只许下调，下调随替换票一起改）。
    """
    baseline_f = INTEG / "terminology-baseline.json"
    if not baseline_f.is_file():
        err("L7 术语基线缺失：%s（看守无法判定，fail-closed）" % baseline_f.name)
        return
    try:
        base = json.loads(baseline_f.read_text(encoding="utf-8"))
        counts = base.get("counts") or {}
        term = str(base.get("term") or "")
    except Exception as e:                       # noqa: BLE001 —— 畸形基线=红不猜
        err("L7 术语基线畸形（%s: %s）" % (type(e).__name__, e))
        return
    if not term or not isinstance(counts, dict):
        err("L7 术语基线缺 term/counts 键")
        return
    exts = {".py", ".mjs", ".js", ".ts", ".tsx", ".md", ".yaml", ".yml",
            ".json", ".sh", ".txt", ".cjs"}
    skip_dirs = {".git", ".lane", ".sandbox", ".sandbar", "node_modules",
                 "__pycache__", ".venv", "out", "data", ".pytest_cache"}
    hits, total = [], 0
    for p in _lint_targets():
        if not p.is_file() or p.suffix not in exts:
            continue
        rel_parts = set(p.relative_to(REPO).parts[:-1])
        if rel_parts & skip_dirs:
            continue
        rel = str(p.relative_to(REPO))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:                        # noqa: BLE001 —— 读不动=不判它，不改判
            continue
        n = text.count(term)
        if not n:
            continue
        total += n
        cap = counts.get(rel)
        if cap is None:
            hits.append("%s：%d 处（不在基线内）" % (rel, n))
        elif cap != -1 and n > cap:
            hits.append("%s：%d 处 > 基线 %d 处（新增用法）" % (rel, n, cap))
    if hits:
        err("L7 术语废止：「%s」不得新增——%s；替换词见 docs/terminology.md 禁用对照"
            % (term, "；".join(hits[:8]) + ("…" if len(hits) > 8 else "")))
    else:
        ok("L7 术语废止看守：无新增「%s」（存量 %d 处，随替换批次下调基线）" % (term, total))


# ---- L8 测试临时目录卫生（260926 磁盘泄漏修：宿主 $TMPDIR 顶层 407,294 个目录、
# 401,578 个 >6h（98.6%）的同类普查产物）。判据=**纯文本机械检查**：文件里出现
# `mkdtemp(`/`mkdtempSync(` 就必须在**同一文件**里出现回收动词（注册表 + exit 钩子、
# rmtree、TemporaryDirectory、dispose/reap 任一）。为什么按文件而不是按调用点：回收
# 可以写在别处（共享 helper、夹具基类），只有「整个文件一个回收动词都没有」才是真漏点
# ——这正是 `test_multirepo_anchor.py`（1.7 万目录）与 `stage_docker.py`（2 万目录）的形态。
# 存量债（约 70 个文件，多为共享夹具库）进 baseline **豁免**（值=mkdtemp 调用点数）：
# 只有 ①基线外的新文件用 mkdtemp 且零回收动词，或 ②基线内文件**新增**调用点 → 黄。
# 警告级、不阻断（本闸防新债，不负责追缴存量——存量由清扫器与巡检水位面处置）。
TMPDIR_BASELINE = INTEG / "tmpdir-baseline.json"
MKD_TMP = re.compile(r"mkdtempSync\s*\(|mkdtemp\s*\(")
RECLAIM_TOKENS = ("rmtree", "rmSync", "unlink", "TemporaryDirectory", "atexit",
                  "dispose", "reap", "cleanup", "remove(", "rm(")
TMP_HYGIENE_EXTS = {".py", ".mjs", ".js", ".cjs", ".ts"}


def tmpdir_users():
    """→ {rel: mkdtemp 调用点数}（只含「零回收动词」的文件；L8 与基线再生成共用同一判据）。"""
    skip_dirs = {".git", ".lane", ".sandbox", ".sandbar", "node_modules",
                 "__pycache__", ".venv", "out", "data", ".pytest_cache"}
    out = {}
    for p in _lint_targets():
        if not p.is_file() or p.suffix not in TMP_HYGIENE_EXTS:
            continue
        if set(p.relative_to(REPO).parts[:-1]) & skip_dirs:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:                            # noqa: BLE001 —— 读不动=不判，不改判
            continue
        n = len(MKD_TMP.findall(text))
        if not n:
            continue
        if any(tok in text for tok in RECLAIM_TOKENS):
            continue
        out[str(p.relative_to(REPO))] = n
    return out


def write_tmpdir_baseline():
    users = tmpdir_users()
    TMPDIR_BASELINE.write_text(json.dumps({
        "rule": "L8: a file calling mkdtemp* must reclaim in the same file; "
                "grandfathered here (value = mkdtemp call sites); only NEW debt warns",
        "generated_by": "python3 integration/lint_tests.py --write-tmpdir-baseline",
        "files": users}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("L8 baseline written: %s (%d grandfathered files)" % (TMPDIR_BASELINE.name, len(users)))
    return 0


#: L9 严格档：True=缺身份即 error；False=先给 warning（存量清理期间）。
#: 260927 当天已把全部 36 处调用点分类完（声明身份 / 显式豁免标记），故直接翻 True——
#: 从此新增一处「既不声明身份、又不带豁免标记」的建票调用点即红（KI-142 修法方向③）。
L9_STRICT = True

#: L9 显式豁免注释：故意测「拒收」的调用点**必须**带这一行说明（写在调用点上方或
#: 参数块内），而不是靠「恰好没写身份」蒙混——豁免本身也必须是可复核的判定。
L9_ALLOW = "L9-allow: expects-refusal"


def _ticket_start_sites():
    """所有裸入口建票调用点：`integration/**/*.py` 里出现 `"ticket-start"` 的行。

    为什么单列这一项（260927 KI-142）：引擎 t260925-08 把 undeclared 策略由 record
    翻成 refuse 之后，凡「不声明调用方项目」的建票调用都会被跨项目闸 fail-closed 拒收
    ——而拒收回执 rc=0 且回显票号，场景里手写的 `rc==0 and tid in out` 断言于是**假绿**：
    票根本没建出来，旅程却继续往下等（实案 sc_detail_lane_reds 干等 240s 报 workflow
    not found，烂了很久没人知道，因为它在会被跳过的 engine 池里）。本项把「必须声明
    身份」变成机械可查的东西：要么声明（arg 的 `caller_project`，或调用点之前就设好的
    env `SANDBAR_CALLER_PROJECT`），要么显式带注释 `%s`。
    """ % L9_ALLOW
    sites = []
    for p in sorted(INTEG.rglob("*.py")):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:                              # noqa: BLE001 —— 读不到=不判（L1 会咬语法）
            continue
        for i, ln in enumerate(lines):
            if '"ticket-start"' not in ln:
                continue
            head = "\n".join(lines[:i])                # 调用点之前：env 声明面
            win = "\n".join(lines[max(0, i - 6):i + 18])   # 调用点附近：arg 与注释面
            declared = ("caller_project" in win
                        or "SANDBAR_CALLER_PROJECT" in head
                        or "SANDBAR_UNDECLARED_POLICY" in head or "SANDBAR_UNDECLARED_POLICY" in win)
            allowed = L9_ALLOW in win
            sites.append({"file": str(p.relative_to(REPO)), "line": i + 1,
                          "declared": declared, "allowed": allowed})
    return sites


def lint_ticket_start_identity():
    sites = _ticket_start_sites()
    naked = [s for s in sites if not s["declared"] and not s["allowed"]]
    if not naked:
        ok("L9 ticket-start identity: %d call site(s), all declare caller identity "
           "or carry the %r marker" % (len(sites), L9_ALLOW))
        return
    msg = ("L9 ticket-start identity: %d of %d bare-entry creation call site(s) neither "
           "declare the caller project nor carry the %r marker — such a call is refused by "
           "the cross-project gate (ok=false, kind=cross_project_refused) while the usual "
           "`rc==0 and tid in out` assertion still reads green: %s | fix: pass "
           "caller_project=<own project key> in the args, or set SANDBAR_CALLER_PROJECT in "
           "the scenario env before the call; for deliberate refusal cases add the marker "
           "comment. See KI-142."
           % (len(naked), len(sites), L9_ALLOW,
              "; ".join("%s:%d" % (s["file"], s["line"]) for s in naked[:8])))
    (err if L9_STRICT else warn)(msg)


def lint_tmpdir_hygiene():
    if not TMPDIR_BASELINE.is_file():
        warn("L8 临时目录卫生：基线缺失 %s（本项无法判定；再生成："
             "python3 integration/lint_tests.py --write-tmpdir-baseline）" % TMPDIR_BASELINE.name)
        return
    try:
        base = json.loads(TMPDIR_BASELINE.read_text(encoding="utf-8")).get("files") or {}
    except Exception as e:                           # noqa: BLE001 —— 畸形基线=黄不猜
        warn("L8 临时目录卫生：基线畸形（%s: %s）——本项未能判定" % (type(e).__name__, e))
        return
    new_files, grown = [], []
    for rel, n in sorted(tmpdir_users().items()):
        cap = base.get(rel)
        if cap is None:
            new_files.append("%s (%d call site%s, no reclaim verb)" % (rel, n, "" if n == 1 else "s"))
        elif n > cap:
            grown.append("%s (%d > baseline %d)" % (rel, n, cap))
    if new_files or grown:
        warn("L8 tmp-dir hygiene: mkdtemp without any reclaim verb in the same file — %s%s"
             " | fix: registry + exit hook (e.g. server/engine/tests/_tmp_reclaim.py) or "
             "rmtree/TemporaryDirectory; batch registry: %s"
             % ("; ".join(new_files[:6]), ("; " + "; ".join(grown[:4])) if grown else "",
                TMPDIR_BASELINE.name))
    else:
        ok("L8 tmp-dir hygiene: no new mkdtemp-without-reclaim (baseline %d grandfathered file%s)"
           % (len(base), "" if len(base) == 1 else "s"))


# ── L10 机制化匹配（t260929-09：字面量盲区翻车后的重写）──────────────────────
# 事故教训：旧闸只认 `spawn('dsh', …)` 字面量，真弹窗源 host-prompt-bench.mjs 用的是
# 变量二进制 `spawn(dshCmd, …)`——闸报「5 处全合规」而第 6 处（真凶）根本没被扫。
# 新判据（满足任一即「dsh 族启动点」，必须携带 --no-open）：
#   R1 二进制是字符串字面量 `dsh` 或以 `/dsh` 结尾的路径；
#   R2 argv 数组提及 `--profile`（带 profile 的进程族⇒dsh 启动家族，与二进制写法无关——
#      正是这条抓住了肇事形态）；
#   R3 二进制是 dsh 命名的表达式（标识符含 dsh，如 dshCmd/dshBin；或 bin.js/bin/dsh 路径片段）。
# 豁免必须显式且带理由（静默≠豁免）：`L10-allow:` 注记（调用行、argv 文本或紧邻上一行）、
# 只跑 `--version` 的探针（不启控制台）。
L10_CALL_RE = re.compile(
    r"""\b(?:spawn|spawnSync|execFile|execFileSync)\s*\(\s*(?P<bin>.{0,160}?)\s*,\s*\[(?P<argv>[^\]]*)\]""",
    re.S)
_L10_DSH_BIN_LITERAL_RE = re.compile(r"""^\s*['"][^'"]*/?dsh['"]\s*$""")
_L10_DSH_EXPR_RE = re.compile(r"(?i)dsh|bin\.js")


def l10_dsh_why(bin_expr, argv):
    """分类：该启动点为何算 dsh 族（None=不属于本闸管辖）。"""
    if _L10_DSH_BIN_LITERAL_RE.match(bin_expr):
        return "literal dsh binary"
    if "--profile" in argv:
        return "argv carries --profile"
    if _L10_DSH_EXPR_RE.search(bin_expr):
        return "dsh-named binary expression"
    return None


def _l10_classify(text):
    """全量分类：[(lineno, argv, why, kind)]，kind ∈ bad/compliant/exempt/probe。

    内部缝（闸本体用）；对外测试缝见 _l10_launch_sites。
    """
    sites = []
    lines = text.splitlines()
    for m in L10_CALL_RE.finditer(text):
        argv = m.group("argv")
        why = l10_dsh_why(m.group("bin"), argv)
        if why is None:
            continue
        line = text[:m.start()].count("\n") + 1
        cur = lines[line - 1] if line - 1 < len(lines) else ""
        prev = lines[line - 2] if line >= 2 else ""
        if "L10-allow:" in argv or "L10-allow:" in cur or "L10-allow:" in prev:
            kind = "exempt"
        elif "--version" in argv:
            kind = "probe"
        elif "--no-open" in argv:
            kind = "compliant"
        else:
            kind = "bad"
        sites.append((line, argv, why, kind))
    return sites


def _l10_launch_sites(text):
    """对外测试缝（t260929-09 场景契约）：返回本闸**管辖内**的启动点。

    [(lineno, argv_text, why)]——只含 dsh 族且未被豁免（L10-allow 注记 / --version
    探针不计入；compliant 与 bad 都算管辖内，是否缺旗由调用方看 argv 判）。
    """
    return [(ln, argv, why) for (ln, argv, why, kind) in _l10_classify(text)
            if kind in ("bad", "compliant")]



# .sh 启动面：两类「人手启动即开浏览器」的豁免面，逐个具名＋理由（静默跳过 .sh=旧闸盲区之二）。
L10_SH_TARGET_RE = re.compile(r"start-console\.sh|stage_console\.sh|\bdsh\b")
# .sh 行的「命令位 dsh」判据：dsh 须处命令位（行首/控制符后/裸行首命令），排除
# pgrep 模式串（PAT='dsh …'）、docker 镜像 tag（test-dsh:dsh-…）等词缀形态误报。
L10_SH_CMDPOS_RE = re.compile(
    r"(?:^|[;&|(]\s*|`\s*|\bexec\s+|\bsudo\s+|\bthen\s+|\bdo\s+|\bdocker\s+run\s+\S+\s+)"
    r"(?:[A-Za-z_]\w*=\S+\s+)*dsh(?:\s|$)")
L10_HUMAN_FACING = {
    "start-console.sh": "human operator console entry (repo root) — browser opens by design when a person starts it",
    "stage_console.sh": "human-facing staging tool (server/tools) — --no-open is an opt-in flag by design",
}
# 自动化启动面点名清单：闸必须在这几处真的看到 --no-open 证据（防「扫了个寂寞」的空转绿）。
# 与 t260929-09 场景 SH_INVOKERS 同单（capture-lane 面=真起台文件 capture-lane.mjs；
# bench_console.mjs 自身无任何 dsh 启动面，作假面入列反而制造假红，已在场景侧更正）。
L10_AUTOMATION_FACES = [
    ("server/ui-check/capture-lane.mjs", "capture-lane"),
    ("integration/t260904-17/lib_fix17.mjs", "lib_fix17"),
    ("integration/t260905-07/lib_t260905.mjs", "lib_t260905"),
    ("integration/t260916-26/lib_t260916_26_bench.mjs", "lib_t260916_26_bench"),
    ("integration/t260916-25/sc_stage_console_guardrails.mjs", "t260916-25 guardrails scenario"),
    ("integration/tests/test_start_console_bits.py", "test_start_console_bits"),
]
# 空转绿证据判据：--no-open 与启动词同文件在场（启动词=spawn 族/runShell/runStep/启动脚本名）。
L10_FACE_LAUNCH_TOKEN_RE = re.compile(
    r"spawn|execFile|run_shell\s*\(|runStep\s*\(|start-console\.sh|stage_console\.sh")


def lint_console_no_open():
    """L10 控制台启动面必须 --no-open（260929 宿主实报「浏览器不停跳新窗口」的机械闸）。

    事故：**宿主正在工作**时浏览器不停跳新窗口。根因族=**测试/工具起的 dsh 控制台没带
    `--no-open`**⇒ `dsh web` 每次都去打开宿主机默认浏览器；套件一跑（每个控制台类场景一个台）
    或一个**泄漏的旧台**被守护重启，就会持续弹窗。260929 二次翻车：真弹窗源
    host-prompt-bench.mjs 用变量二进制 `spawn(dshCmd,…)`，旧闸（只认字面量 `spawn('dsh',…)`）
    报「5 处全合规」而真凶是没被扫的第 6 处——故判据从字面量升级为机制（见 L10_CALL_RE 三规则）。
    判据：仓内所有 **dsh 族进程启动点**（含变量二进制与 .sh 启动面）必须携带 `--no-open`；
    只跑 `--version` 的探针不在此限（不启控制台）。
    豁免（必须显式带理由）：任何带 `L10-allow:` 注记的行；.sh 面（js/py 扫描不覆盖 bash，
    单独 L10b 扫）里两类**具名**人手启动豁免（L10_HUMAN_FACING）——静默跳过 .sh 即旧盲区。
    """
    bad = []
    scanned = 0
    _skip = {"node_modules", ".git", ".lane", ".venv", "out", ".sandbar", "__pycache__"}
    cands = []
    for path in REPO.rglob("*"):
        # 泳道教训（t260929-09 实测复现）：skip 集必须对**仓内相对路径**判定——
        # 绝对 parts 会在泳道 worktree（…/sandbar/.lane/<票>/…）整体命中 `.lane`
        # 而把全仓候选清零，扫描空转绿。这正是本票要杀的盲区形态，顺手根治。
        if any(part in _skip for part in path.relative_to(REPO).parts):
            continue
        if path.suffix in (".mjs", ".ts", ".py") and path.is_file():
            cands.append(path)
    for path in cands:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line, _argv, _why, kind in _l10_classify(text):
            if kind == "bad":
                bad.append("%s:%d" % (path.relative_to(REPO), line))
            elif kind == "compliant":
                scanned += 1
    # L10b：.sh 启动面（自动化调用必须 --no-open；人手豁免面具名放行）
    sh_faces = {"compliant": 0, "human": 0}
    for path in REPO.rglob("*.sh"):
        if any(part in _skip for part in path.relative_to(REPO).parts):
            continue
        rel = str(path.relative_to(REPO))
        is_human_launcher = path.name in L10_HUMAN_FACING
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, raw in enumerate(lines, 1):
            stripped = raw.strip()
            if stripped.startswith("#") or not L10_SH_TARGET_RE.search(raw):
                continue
            if "--no-open" in raw or "L10-allow:" in raw:
                sh_faces["compliant"] += 1
            elif is_human_launcher or any(name in raw for name in L10_HUMAN_FACING):
                sh_faces["human"] += 1        # 具名人手豁免（理由见 L10_HUMAN_FACING）
            elif "--version" in raw:
                pass                          # 版本探针：不启控制台（与 js/py 面同规则）
            elif not L10_SH_CMDPOS_RE.search(raw):
                pass                          # dsh 只以词缀/镜像 tag/模式串形态出现，非启动面
            else:
                bad.append("%s:%d (sh face, no --no-open)" % (rel, i))
    # 空转绿守卫：点名自动化面必须真的被闸看见 --no-open 证据，否则闸=装饰品。
    blind = []
    for rel, label in L10_AUTOMATION_FACES:
        p = REPO / rel
        if not p.is_file():
            blind.append("%s (file missing)" % label)
            continue
        ftext = p.read_text(encoding="utf-8", errors="replace")
        seen = ("--no-open" in ftext
                and (L10_FACE_LAUNCH_TOKEN_RE.search(ftext) is not None
                     or any(k == "compliant" for _l, _a, _w, k in _l10_classify(ftext))))
        if not seen:
            blind.append("%s (no --no-open evidence at a launch face)" % label)
    if bad:
        err("L10 控制台启动面缺 --no-open（%d 处；宿主浏览器会被弹窗）——%s"
            "（dsh web 每次都开宿主默认浏览器；补 `--no-open`，或加 `L10-allow:<理由>` 注记）"
            % (len(bad), "; ".join(bad[:6])))
    else:
        ok("L10 控制台启动面 --no-open 齐备（dsh 启动点 %d 处；sh 面 --no-open %d 处，"
           "具名人手豁免 %d 处：%s）"
           % (scanned, sh_faces["compliant"], sh_faces["human"],
              "; ".join("%s=%s" % (k, v) for k, v in L10_HUMAN_FACING.items())))
    if blind:
        err("L10 空转绿守卫：点名自动化启动面闸没看见 --no-open 证据——%s"
            "（闸形同虚设即盲区复发；核对启动面是否改道绕过）" % "; ".join(blind))
    else:
        ok("L10 空转绿守卫：全部点名自动化启动面均见 --no-open 证据（%d 个面）"
           % len(L10_AUTOMATION_FACES))


def main():
    lint_syntax()
    lint_collect()
    lint_mjs_imports()
    lint_registry()
    lint_three_state()
    lint_terminology()
    lint_tmpdir_hygiene()
    lint_ticket_start_identity()
    lint_console_no_open()
    n_e, n_w = len(errors), len(warns)
    print("LINT done: %d error / %d warn" % (n_e, n_w))
    return 1 if n_e else 0


if __name__ == "__main__":
    if "--write-tmpdir-baseline" in sys.argv[1:]:      # 父列表再生成（见 lint_tmpdir_hygiene）
        sys.exit(write_tmpdir_baseline())
    sys.exit(main())
