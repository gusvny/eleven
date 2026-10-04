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
  L11 integration gate settlement (B2, host order 260929): the engine's section
        status failure condition must NOT contain `env_fail` (environment red is
        recorded by name, never a failure face / never a re-run reason), and
        run_scenarios' INTEG_SUMMARY must carry `env_red_names` (the named
        channel without which "not blocked" would become "silent").
  L16 anchor manifest (t261004-20): every engine test file and every registered
        scenario script must carry an anchor label in integration/test_anchors.json
        (behaviour | contract | production-snapshot | source-text); a
        production-snapshot label must name its sync_path; stale entries are
        errors. This is the assertion-anchor judgement made machine-readable —
        different face from the old-repo-literal migration-path-hygiene scenario
        family (that one guards retired repo paths; this one guards what each
        test's assertions are anchored to).
  L17 home-path ban (t261004-20): an absolute /Users/<name>/ or /home/<name>/
        path inside an engine test or scenario script is an error — tests must
        inspect the tree they run in (repo-root resolution), not the machine
        that wrote them. Exemptions are explicit per file:line with a reason.
        Different face from the migration-path-hygiene scenario (old-repo literal
        guard) — see L16 note; the two are complementary, not duplicates.
  L18 snapshot discipline (t261004-20): a production-snapshot label in the
        manifest and a `@pytest.mark.production_snapshot` marker must go together
        on engine tests — an undeclared snapshot assertion (label without marker,
        or marker without label) is refused; the marker names the file to update
        when the production value changes (sync_path in the manifest).

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


# ── L11 集成门判据收口（B2，宿主 260929 令）：环境红不拦、不重跑、不静默 ──────────
#: 段 status 的失败条件**不得**再含 env_fail（源码字面钉）。语义（宿主口径）：门只对
#: 本票新增产品红 + 未挂账产品红判红；环境红具名记录、不拦、不重跑。
L11_DEV_LANE = "server/engine/dev_lane.py"
L11_RUNNER = "integration/run_scenarios.py"
_L11_STATUS_RE = re.compile(
    r'"status"\s*:\s*"failed"\s*if\s*\(([^)]*)\)\s*else\s*"ok"')
_L11_ENV_RED_KEY = "env_red_names"


def lint_integration_gate_settlement():
    """L11：B2「集成门判据收口」的回潮闸（机械字面判据，秒级）。

    两钉（任一失守即 err——它们各自是「环境红又被当失败面/名单面被静默」的入口）：
      ① `dev_lane.py` 段 status 的失败条件不得含 `env_fail`：环境红（供给/共享台面）
         不构成段失败，改了它=每票每轮被环境红锁死（B2 要掐断的那条链）；
      ② `run_scenarios.py` 的 INTEG_SUMMARY 必须带 `env_red_names` 键：具名通道是
         「不拦但不许静默」的唯一兑现面，键没了=红名单再次不可读（B1 回退）。
    判据读源码字符串（不回退成注释/文档面）；两文件缺席也报 err（fail-closed）。"""
    dl = REPO / L11_DEV_LANE
    if not dl.is_file():
        err("L11 %s 缺席——集成门判据收口无法判定（fail-closed）" % L11_DEV_LANE)
        return
    src = dl.read_text(encoding="utf-8", errors="replace")
    hits = _L11_STATUS_RE.findall(src)
    if not hits:
        err("L11 段 status 失败条件锚未命中（%s 的 `\"status\": \"failed\" if (...) else "
            "\"ok\"` 形态变了）——判据收口闸形同虚设，请同步本判据" % L11_DEV_LANE)
    else:
        bad = [c for c in hits if "env_fail" in c]
        if bad:
            err("L11 段 status 失败条件含 env_fail（%s）——环境红又被当失败面（B2 回退："
                "每票每轮被环境红锁死）；环境红只具名记录，判据=ir.error or ir.failed"
                % ("; ".join(c.strip() for c in bad)))
        else:
            ok("L11 段 status 失败条件已摘 env_fail（%d 处：%s）"
               % (len(hits), "; ".join(c.strip() for c in hits)))
    rs = REPO / L11_RUNNER
    if not rs.is_file():
        err("L11 %s 缺席——具名通道无法判定（fail-closed）" % L11_RUNNER)
        return
    rsrc = rs.read_text(encoding="utf-8", errors="replace")
    if '"%s"' % _L11_ENV_RED_KEY not in rsrc:
        err("L11 INTEG_SUMMARY 缺 `%s` 键（%s）——环境红具名通道失守（B1 回退：红名单"
            "不可读，票面答不出红的是哪几条）" % (_L11_ENV_RED_KEY, L11_RUNNER))
    else:
        ok("L11 INTEG_SUMMARY 带 `%s` 键（环境红具名通道在场）" % _L11_ENV_RED_KEY)



# ---- L12 收窄旋钮继承看守（260930：真票 t260930-09 全族缺陷的机械回归锁）----
# 病根：泳道轮的闸环境带着本轮收窄面（SANDBAR_SCENARIO_ONLY=<改动面>）；场景/夹具自己
# 再起**执行器或闸**时子进程（或进程内调用）继承了它 → 内层被收窄成不含夹具点名的面 →
# 断言成片红（实测 4 条：t260913-03-* 的池排除族；同一轮里的
# t260916-25-stage-console-selfcheck-red **不是**本族——A/B 实测（普通环境 vs 全旋钮
# 收窄环境）两跑全绿，且该场景链上（stage_console.sh / lib_stage_ui_surface.mjs）不读
# 任何本族旋钮，它的泳道轮红是台面/端口竞争，不归本看守）。
# 纪律：**被测面必须由夹具显式声明，绝不继承外层泳道轮的收窄/策略旋钮**；清理单点=
# integration/lib_env.clean_narrowing_env（子进程）/ no_narrowing_env（进程内）。
# 本规则=**凡起执行器/闸的文件必须出现该单点名**（可白名单+理由），漏走即红。
L12_WHITELIST = {
    # 文件 → 理由（为什么它不需要清理）
    "integration/run_scenarios.py": "执行器自身（被调用方，不是调用点）",
    "integration/lib_env.py": "清理单点自身（定义处）",
    # 误判面（含令牌但不起执行器/闸）：夹具**文本**里写的合成会话/声明串，不是调用点。
    # 判据=这些字面量只进 write_session/tool_frame 这类夹具构造器，从不进 subprocess。
    "integration/t260921-04/sc_discipline_receipt_journey.py":
        "合成会话夹具文本里含 run_scenarios.py 字面量（不是 spawn；该场景零子进程执行器）",
}
L12_EXECUTOR_TOKENS = ("run_scenarios.py", "call", "verify_lane")
L12_HELPER_MARKERS = ("clean_narrowing_env", "no_narrowing_env", "cleanNarrowingEnv",
                      "lib_env")


def _l12_balanced_call(text, open_paren_idx):
    """从 `(` 起取括号配平的调用文本（任意嵌套）；畸形（未闭合）=取到文末。"""
    depth = 0
    for i in range(open_paren_idx, len(text)):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_paren_idx:i + 1]
    return text[open_paren_idx:]


def _l12_reasons_for(text, suffix):
    """单文件检测面（纯函数，无 IO）：返回「为什么算起执行器/闸」的理由表。

    抽出来是为了**自证可执行**——看守的牙必须能在合成文本上真跑一遍，而不是断言
    「字面量在不在」（260930 修正：原来的自证只查字符串，等于没牙）。"""
    why = []
    calls = []
    for m in re.finditer(
            r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\(", text):
        calls.append(_l12_balanced_call(text, text.index("(", m.start())))
    for m in re.finditer(r"\b(?:spawnSync|spawn|execSync|execFileSync)\s*\(", text):
        calls.append(_l12_balanced_call(text, text.index("(", m.start())))
    for call in calls:
        if "run_scenarios.py" in call or "verify_lane" in call:
            why.append("子进程起执行器/闸")
            break
    # 间接形态（同族必须一并看守，否则新写法绕过）：
    #  (c) 令牌出现在**命令向量字面量**被 subprocess 使用（EXEC = [..., "integration/
    #      run_scenarios.py"]）；(d) 令牌经**本地包装壳**起（sh(...)/run_cli(...)/
    #      call_gate(...) 家族）。两条都要求文件确实用 subprocess/spawnSync 才有可能算。
    uses_proc = ("subprocess." in text) or ("spawnSync" in text)
    if uses_proc and re.search(
            r"\[[^\]]*(?:run_scenarios\.py|verify_lane)[^\]]*\]", text, re.S):
        why.append("命令向量字面量起执行器/闸")
    elif uses_proc and re.search(
            r"\b(?:sh|run|run_cli|call_gate|callLane|call_verify_lane|run_executor|"
            r"call_lane|run_gate)\s*\([^)]*(?:verify_lane|run_scenarios\.py)", text, re.S):
        why.append("经包装壳起执行器/闸")
    if suffix == ".py":
        if re.search(r"verify_lane\.run\(", text):
            why.append("进程内直调 verify_lane.run")
        if re.search(r"\brs\.main\(|\bmod\.main\(|\bRS\.main\(", text):
            why.append("进程内直调执行器 main()")
    return why


def _l12_spawn_sites():
    """逐文件判定「是否起执行器/闸」：**按括号配平的整条调用**取文本（子进程形态 +
    进程内直调形态 + mjs spawnSync），不做窗口模糊匹配——夹具文件里作为**字符串**出现
    的 verify.yaml 文本不算调用点（检测面单点=`_l12_reasons_for`，其自证在
    `lint_narrowing_env_inheritance` 里对合成文本做实跑）。"""
    sites = []
    for p in sorted(INTEG.rglob("*")):
        if not p.is_file() or p.suffix not in (".py", ".mjs", ".js", ".sh"):
            continue
        rel = str(p.relative_to(REPO))
        if rel in L12_WHITELIST:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        why = _l12_reasons_for(text, p.suffix)
        if why:
            sites.append({"file": rel, "why": why, "clean": any(
                mk in text for mk in L12_HELPER_MARKERS)})
    return sites


def lint_narrowing_env_inheritance():
    """L12：起执行器/闸的文件必须走收窄旋钮清理单点（lib_env），否则内层面被继承收窄。"""
    sites = _l12_spawn_sites()
    naked = [s for s in sites if not s["clean"]]
    # 自证（260930 修正：**真跑检测面**，不是查字面量）——合成犯例必被抓、带清理单点的
    # 合成例必放行、无关 spawn 不得误报；三条都不碰真树。
    fake_bad = ("import subprocess\n"
                "subprocess.run([sys.executable, 'integration/run_scenarios.py'])\n")
    fake_ok = ("import subprocess\n"
               "from lib_env import clean_narrowing_env\n"
               "subprocess.run([sys.executable, 'integration/run_scenarios.py'],"
               " env=clean_narrowing_env())\n")
    fake_inproc = ("import run_scenarios as rs\n"
                   "rc = rs.main()\n")
    fake_noise = ("import subprocess\n"
                  "subprocess.run(['ls', '-la'])\n")
    bad_why = _l12_reasons_for(fake_bad, ".py")
    ok_why = _l12_reasons_for(fake_ok, ".py")
    ip_why = _l12_reasons_for(fake_inproc, ".py")
    noise_why = _l12_reasons_for(fake_noise, ".py")
    proof = []
    if not bad_why:
        proof.append("合成犯例（子进程起执行器、无清理单点）没被抓")
    if not ok_why:
        proof.append("合成干净例（带 clean_narrowing_env）没被判为调用点")
    if "clean_narrowing_env" not in fake_ok:
        proof.append("合成例的清理标记判据不成立")
    if not ip_why:
        proof.append("合成犯例（进程内 rs.main()）没被抓")
    if noise_why:
        proof.append("无关 spawn 被误报=%r" % noise_why)
    if proof:
        err("L12 自证失败（看守没牙）：%s" % "；".join(proof))
        return
    if naked:
        err("L12 收窄旋钮继承看守：%d 处起执行器/闸的调用点没走清理单点（继承外层泳道轮的"
            " SANDBAR_SCENARIO_ONLY 等收窄旋钮会把内层被测面收窄——t260930-09 全族缺陷）"
            "：%s | 修法：env=clean_narrowing_env(...)（子进程）或 with no_narrowing_env():"
            "（进程内）；确有理由的登记到 lint_tests.L12_WHITELIST 并写理由"
            % (len(naked), "；".join("%s（%s）" % (s["file"], "/".join(s["why"]))
                                     for s in naked[:8])))
        return
    ok("L12 收窄旋钮继承看守：%d 处起执行器/闸的调用点全部走清理单点（lib_env）" % len(sites))

# ---- L13 工具面 stdout 通道（261001：verify_lane 的 stdout 备注把闸回执整轮打掉）----
#: 经 `admin.py call <tool>` **进程内**执行、且引擎把 admin 的 stdout 当 JSON 信封解析的工具。
#: 判据：这些模块里出现任何「能落到 stdout 的裸 print」= 信封被污染 ⇒ `json.loads` 失败 ⇒
#: 那一轮真跑出来的结果全丢（t261001-10 第 9 轮实案：135 ran / 116 pass / 5 env-red 的
#: 一轮变成 "no receipt (gate error: verify_lane integ produced no valid output)"）。
L13_INPROC_TOOLS = ("server/tools/verify_lane.py",)
#: 允许的出口：stderr 备注助手（`_note(...)`）——人话走 stderr，stdout 只放信封。
L13_NOTE_HELPER = "_note("


def _l13_bare_stdout_prints(text):
    """返回裸 print 的行号（把括号前的续行参数也算进来判 `file=`；`print(` 后紧跟括号内的
    参数里出现 `file=` 即视为走了 stderr）。"""
    out, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"\s*print\(", line):
            continue
        # 收集本 print 调用的整段（最多追 6 行或到括号配平）
        depth, buf = 0, []
        for j in range(i, min(i + 8, len(lines))):
            buf.append(lines[j])
            depth += lines[j].count("(") - lines[j].count(")")
            if depth <= 0:
                break
        blob = "\n".join(buf)
        if "file=" in blob:
            continue
        out.append(i + 1)
    return out


def lint_tool_stdout_channel():
    """L13：进程内工具模块不得把备注打到 stdout（人话一律 stderr / `_note`）。"""
    for rel in L13_INPROC_TOOLS:
        f = REPO / rel
        if not f.exists():
            err("L13 %s 缺席——stdout 通道判据无法判定（fail-closed）" % rel)
            return
        txt = f.read_text(encoding="utf-8")
        bare = _l13_bare_stdout_prints(txt)
        # 自证（不碰真树）：合成犯例必被抓、stderr 形态必放行、多行 file= 形态必放行
        fake_bad = "def f():\n    print('note')\n"
        fake_ok = "def f():\n    print('note', file=sys.stderr)\n"
        fake_multi = "def f():\n    print('note %s' % x,\n          file=sys.stderr)\n"
        proof = []
        if _l13_bare_stdout_prints(fake_bad) != [2]:
            proof.append("合成犯例没被抓")
        if _l13_bare_stdout_prints(fake_ok):
            proof.append("stderr 形态被误报")
        if _l13_bare_stdout_prints(fake_multi):
            proof.append("多行 file= 形态被误报")
        if proof:
            err("L13 自证失败（看守没牙）：%s" % "；".join(proof))
            return
        if bare:
            err("L13 进程内工具把备注打到了 stdout（%s 第 %s 行）——`admin.py call` 的信封会"
                "被这行污染，引擎 `json.loads(stdout)` 直接失败，那一轮的闸结果整轮被丢"
                "（t261001-10 第 9 轮实案）；修法：人话走 `%s`（stderr）"
                % (rel, ",".join(str(x) for x in bare[:8]), L13_NOTE_HELPER))
            return
        if L13_NOTE_HELPER not in txt:
            err("L13 %s 里找不到 stderr 备注出口 %s——本判据的「允许出口」被改名/删除，"
                "判据形同虚设，请同步" % (rel, L13_NOTE_HELPER))
            return
    ok("L13 工具面 stdout 通道：%d 个进程内工具模块零裸 print（人话走 %s→stderr）"
       % (len(L13_INPROC_TOOLS), L13_NOTE_HELPER))


def _load_integ_module(name, rel):
    """按文件位装载 integration/<rel>（不依赖包导入；t261002-14 起两处共用）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(INTEG / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lint_vocab_cross_language_locks():
    """L14（t261002-14）：跨语言词表机械互锁——
      · integration/lib_env.py 的 NARROWING_ENV_PREFIXES/NAMES 必须 与
        integration/lib_env.mjs 的 NARROWING_PREFIXES/NAMES 逐元素相同；
      · server/engine/executor_grants.py 的 GRANT_OPS 必须与
        executor-panel executor-grants.ts GRANT_OPS、grants.ts FIXED_OPS
        （经 'reject'→'send-back' 别名归一）逐元素同序相同。
    判据本体是纯函数（narrowing_lock_report / grant_ops_lock_report），
    「单侧独改必被抓」的漂移面由 integration/t261002-14/test_vocab_locks.py
    夹具单测钉住；本 lint 只吃真文件。判据函数提不出字面量=报告行（fail-closed）。"""
    try:
        lib_env_mod = _load_integ_module("_lint_lib_env_t261002_14", "lib_env.py")
        sys.path.insert(0, str(REPO / "server" / "engine"))
        import executor_grants as eg_mod
    except Exception as e:  # noqa: BLE001 —— 判据装载失败=lint 面坏，fail-closed
        err("L14 判据模块装载失败（fail-closed）：%s: %s" % (type(e).__name__, e))
        return
    rep = lib_env_mod.narrowing_lock_report(
        (INTEG / "lib_env.py").read_text(encoding="utf-8"),
        (INTEG / "lib_env.mjs").read_text(encoding="utf-8"))
    if rep:
        err("L14 收窄旋钮清单双语言漂移（lib_env.py vs lib_env.mjs）：%s；"
            "改任一侧必须同轮改另一侧（词表真源注释见 lib_env.py 260930 组）"
            % "; ".join(rep[:6]))
        return
    rep2 = eg_mod.grant_ops_lock_report(
        (REPO / "server/engine/executor_grants.py").read_text(encoding="utf-8"),
        (REPO / "server/plugins/executor-panel/src/host/executor-grants.ts").read_text(encoding="utf-8"),
        (REPO / "server/plugins/executor-panel/src/host/grants.ts").read_text(encoding="utf-8"))
    if rep2:
        err("L14 授权操作词表三面漂移（executor_grants.py / executor-grants.ts / "
            "grants.ts）：%s；改任一面必须同轮改其余两面（'reject'↔'send-back' "
            "别名归一后比对，词表真源=引擎 GRANT_OPS 注释组）" % "; ".join(rep2[:6]))
        return
    ok("L14 词表互锁：收窄旋钮双语言逐元素相同；授权操作三面（含别名归一）同词表同序")


# ---- L16/L17/L18 assertion anchors (t261004-20) -------------------------------

ANCHOR_MANIFEST = INTEG / "test_anchors.json"
ANCHOR_VOCAB = ("behaviour", "contract", "production-snapshot", "source-text")


def _load_anchor_manifest():
    try:
        return json.loads(ANCHOR_MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 —— 清单缺失/畸形=fail-closed 点名
        err("L16 anchor 清单不可读（fail-closed）：%s: %s" % (ANCHOR_MANIFEST.name, e))
        return None


def lint_anchor_manifest():
    """L16（t261004-20）：anchor 清单覆盖面/词表/同步路径。覆盖两棵树：
    server/engine/tests/test_*.py 与 SCENARIOS 在册场景脚本；每个文件必须有词表内
    标签；production-snapshot 必须给 sync_path（值变时改哪个文件）；清单里的死条目
    同样报错（防清单腐烂）。"""
    m = _load_anchor_manifest()
    if m is None:
        return
    for tree in ("engine_tests", "scenarios"):
        if tree not in m or not isinstance(m[tree], dict):
            err("L16 anchor 清单缺 %s 节" % tree)
            return
    covered = set(m["engine_tests"]) | set(m["scenarios"])
    # coverage: engine tests
    missing = [str(p.relative_to(REPO)) for p in sorted((REPO / "server/engine/tests").glob("test_*.py"))
               if str(p.relative_to(REPO)) not in m["engine_tests"]]
    # coverage: registered scenario scripts (same extraction as L4)
    sys.path.insert(0, str(INTEG))
    import run_scenarios as rs  # noqa: E402
    scen_scripts = sorted({p for e in rs.SCENARIOS for p in str(e[2]).split()
                           if p.startswith("integration/") and (REPO / p).exists()})
    missing += [p for p in scen_scripts if p not in m["scenarios"]]
    if missing:
        err("L16 anchor 缺标签（新文件进两棵树必须申报 anchor）：%s" % missing[:6])
    # stale entries
    stale = [k for k in m["engine_tests"] if not (REPO / k).exists()]
    stale += [k for k in m["scenarios"]
              if not (REPO / k).exists() or (k not in scen_scripts)]
    if stale:
        err("L16 anchor 死条目（文件已删/场景已注销，清单须同步）：%s" % stale[:6])
    # vocabulary + sync path
    bad_vocab, no_sync = [], []
    for tree in ("engine_tests", "scenarios"):
        for k, v in m[tree].items():
            a = (v or {}).get("anchor")
            if a not in ANCHOR_VOCAB:
                bad_vocab.append("%s=%r" % (k, a))
            if a == "production-snapshot" and not (v or {}).get("sync_path"):
                no_sync.append(k)
    if bad_vocab:
        err("L16 anchor 词表外标签（只认 %s）：%s" % ("/".join(ANCHOR_VOCAB), bad_vocab[:6]))
    if no_sync:
        err("L16 production-snapshot 缺 sync_path（值变时改哪个文件必须具名）：%s" % no_sync[:6])
    if not (missing or stale or bad_vocab or no_sync):
        ok("L16 anchor 清单：%d 引擎测试 + %d 场景全覆盖，词表内，快照项均具名 sync_path"
           % (len(m["engine_tests"]), len(m["scenarios"])))


# L17 exemptions: file → list of (line-anchor, reason). An exemption entry whose
# anchor line no longer exists is itself an error (the list cannot rot silently).
HOME_PATH_RE = re.compile(r"(?<![\w.])/(?:Users|home)/[A-Za-z0-9._-]+/")
L17_IN_SCOPE = ("server/engine/tests/", "integration/")
L17_EXEMPT = {
    "server/engine/tests/test_t260915_12_t01_caller_gate.py":
        [("/Users/user/Documents/dengzhufpv", "fixture domain data (foreign project path), never opened")],
    "server/engine/tests/test_t260916_21_admin_log_rotation.py":
        [("/Users/user/Documents/dengzhufpv", "fixture domain data (foreign project path), never opened")],
    "server/engine/tests/test_260929_inspection_lane_residue_repair.py":
        [("git worktree add /Users/user/Documents/sandbar", "verbatim quoted REAL_OCCUPIED failure message")],
    "server/engine/tests/test_t260917_02_inspection_redirect.py":
        [("Users/x/Documents/sandbar", "synthetic identity fixture (deliberately fake username), compared for equality, never resolved")],
    "server/engine/tests/test_t260921_14_dsh_path_pin.py":
        [("Users/x/.sandbar/dsh-015", "synthetic dsh-runner fixture (deliberately fake username), never resolved against the tree")],
    "integration/t260907-01/sc_migration_path_hygiene.mjs":
        [("Users/user/Documents/", "the old-repo hygiene guard's own NEEDLE (split-constructed) and its docstring story — exempt by file: regex-blind by design")],
    "integration/t261004-20/sc_test_anchor_brakes.py":
        [("Users/user/Documents/sandbar/inspection.yaml", "fault-injection constant (the /Users shape this ticket's brake scenario plants and removes)"),
         ("home/user/Documents/sandbar/inspection.yaml", "fault-injection constant (the /home shape, same brake scenario)")],
    "integration/t261004-20/sc_rewritten_decl_tests_lane_green.py":
        [("Users/user/Documents/sandbar", "the regression-pin needle itself (R3 asserts the two incident files no longer contain it)")],
    "integration/t260929-03/sc_executor_panel_page.mjs":
        [("home/x/.sandbar/projects/alpha", "synthetic config fixture (deliberately fake username), rendered as provenance text, never resolved")],
}


def lint_home_paths():
    """L17（t261004-20）：引擎测试/场景脚本内禁绝对家目录路径——测试必须检查它所跑的
    那棵树（仓根解析），不得绑写测试时的机器。豁免表逐条带理由；豁免条目失配即报
    （豁免不许静默腐烂）。"""
    targets = sorted((REPO / "server/engine/tests").glob("test_*.py"))
    targets += [p for pat in ("sc_*.py", "sc_*.mjs", "*/sc_*.py", "*/sc_*.mjs")
                for p in INTEG.glob(pat)]
    fired, exempt_seen = [], set()
    for p in targets:
        rel = str(p.relative_to(REPO))
        allowed = L17_EXEMPT.get(rel, [])
        for no, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in HOME_PATH_RE.finditer(line):
                hit = line.strip()[:120]
                excuse = next((a for a, _ in allowed if a in line), None)
                if excuse:
                    exempt_seen.add((rel, excuse))
                else:
                    fired.append("%s:%d %s" % (rel, no, hit))
    stale_exempt = [(rel, a) for rel, pairs in L17_EXEMPT.items()
                    for a, _why in pairs if (rel, a) not in exempt_seen]
    if stale_exempt:
        err("L17 豁免条目失配（锚行已不在，豁免须同步删除）：%s"
            % ["%s :: %s" % s for s in stale_exempt[:4]])
    if fired:
        err("L17 测试/场景内绝对家目录路径（改仓根解析；豁免须逐条具名理由）：%s"
            % fired[:6])
    if not fired and not stale_exempt:
        ok("L17 家目录路径： %d 个测试/场景文件零命中（豁免 %d 条均在位）"
           % (len(targets), len(exempt_seen)))


def lint_snapshot_discipline():
    """L18（t261004-20）：production-snapshot 申报纪律——引擎测试里的
    @pytest.mark.production_snapshot 标记与清单里的 production-snapshot 标签必须
    成对出现：有标记无标签=未申报的快照断言（拒收）；有标签无标记=申报了却不肯
    戴标记（同样拒收）。场景脚本不适用（非 pytest，走 L16 覆盖）。"""
    m = _load_anchor_manifest()
    if m is None:
        return
    marked = set()
    for p in sorted((REPO / "server/engine/tests").glob("test_*.py")):
        if re.search(r"^@pytest\.mark\.production_snapshot\b",
                     p.read_text(encoding="utf-8", errors="replace"), re.M):
            marked.add(str(p.relative_to(REPO)))
    labelled = {k for k, v in m.get("engine_tests", {}).items()
                if (v or {}).get("anchor") == "production-snapshot"}
    undeclared = sorted(marked - labelled)
    unmarked = sorted(labelled - marked)
    if undeclared:
        err("L18 未申报快照断言（有 snapshot 标记、清单无 production-snapshot 标签）：%s"
            % undeclared[:6])
    if unmarked:
        err("L18 申报不落实（清单 production-snapshot 但测试缺 @pytest.mark.production_snapshot）：%s"
            % unmarked[:6])
    if not undeclared and not unmarked:
        ok("L18 快照纪律：标记与清单标签成对（%d 个已申报快照测试）" % len(marked))


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
    lint_integration_gate_settlement()
    lint_narrowing_env_inheritance()
    lint_tool_stdout_channel()
    lint_vocab_cross_language_locks()
    # L15 copy-language gate (t261004-24): new product copy must stay English
    # (writing-standard §1/§2). Implementation lives in integration/lint_copy_language.py
    # (standalone entry there); wired here in-process like L7 so every lane that runs
    # this static gate carries the rule.
    from lint_copy_language import lint_copy_language as _l15
    _l15(errors)
    lint_anchor_manifest()
    lint_home_paths()
    lint_snapshot_discipline()
    n_e, n_w = len(errors), len(warns)
    print("LINT done: %d error / %d warn" % (n_e, n_w))
    return 1 if n_e else 0


if __name__ == "__main__":
    if "--write-tmpdir-baseline" in sys.argv[1:]:      # 父列表再生成（见 lint_tmpdir_hygiene）
        sys.exit(write_tmpdir_baseline())
    sys.exit(main())
