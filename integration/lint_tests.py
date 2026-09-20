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

Usage: python3 integration/lint_tests.py (cwd = repo root; exit 0 = pass)
"""
import json
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INTEG = REPO / "integration"
WB_TESTS = REPO / "server/plugins/workbench/tests"          # ← project parameter (fork: change here)
TP_TESTS = REPO / "server/engine/tests"          # ← project parameter
VENV_PY = REPO / "server/engine/.venv/bin/python"  # ← project parameter
PYC = tempfile.mkdtemp(prefix="lint-pyc-")

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
    if WB_TESTS.is_dir():
        for f in WB_TESTS.glob("*.mjs"):
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
    if not WB_TESTS.is_dir():
        return
    bad = 0
    for f in WB_TESTS.glob("*.mjs"):
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


def lint_terminology():
    """L7 术语废止看守（宿主令 260920）：行话「腿」不得新增。

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
    for p in REPO.rglob("*"):
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


def main():
    lint_syntax()
    lint_collect()
    lint_mjs_imports()
    lint_registry()
    lint_three_state()
    lint_terminology()
    n_e, n_w = len(errors), len(warns)
    print("LINT done: %d error / %d warn" % (n_e, n_w))
    return 1 if n_e else 0


if __name__ == "__main__":
    sys.exit(main())
