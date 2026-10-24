#!/usr/bin/env python3
"""sc_dup_decl_guard_bites.py — t261024-21 duplicate-declaration guard bites.

Intent (grey-box L3, offline seconds, read-only over the real tree, zero
docker/browser, never touches 3099/7233): the Epics tab rendered blank because
panel-page.ts carried TWO closure-top-level declarations of the same name
(renderEpics, and the metrics epics-card renderer), and the later one shadowed
the former for the whole closure. The ticket mandates a regression check that
fails loudly if a duplicate top-level function declaration reappears in
panel-page.ts. The developer's L1 unit test owns the check itself (positive
control on the fixed page, synthetic negative control). THIS entry is the
adversarial probe no other scenario owns: it proves the guard BITES on a real
mutated copy of the production page — i.e. it is wired to the real file, not
only to a synthetic in-test snippet, and it fails loudly (non-zero exit) when
the defect is present.

Legs:
  A1 the panel page is readable AND the developer guard test exists (its
     absence before the implement stage is the named TDD-phase red, not env).
  A2 the same detection contract (closure-top-level named functions = lines
     starting with exactly two spaces + `function NAME`) finds ZERO duplicate
     names in the real page (green after the fix; red before — TDD signal).
  A3 mutation probe in memory: appending a duplicate of an existing top-level
     name to a COPY of the page source makes the detector report exactly that
     name, and a deeper-indented (nested) same-named function does NOT count.
  A4 guard-bites end to end: in a scratch copy of the plugin source+test tree,
     `node --test` on the developer guard test is green on the pristine copy
     and RED on a copy whose page carries an injected duplicate declaration —
     the guard must fail loudly, naming the duplicated identifier.
  A5 the real tree is never mutated (byte-compare of the page file
     before/after; all mutations happen in a temp copy).

Intent split: the guard's own truth table (synthetic positive/negative, the
anchor regex) is developer L1 per the ticket; the Epics-tab render journey is
owned by t261021-13-epic-doc-link-opens-reader and
t261005-10-ui2-epics-docs-metrics-tabs-journey (both booked known-red until
this ticket lands); the Metrics-tab faces are owned by
t261021-07-metrics-tab-mock-anchors. This entry owns only "the guard bites on
the real file".

node missing/unrunnable = ENV_FAIL exit 2 (KI-036 family discipline: an env
gap must not masquerade as a red or a green). Guard test missing at pre-
implement = FAIL named (TDD red expected; arbitrate/merge must be green).
"""
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO / "server/plugins/executor-panel/src/host/panel-page.ts"
GUARD_TEST = REPO / ("server/plugins/executor-panel/tests/"
                     "t261024-21-no-duplicate-top-level-functions.test.mjs")

TOP_FN = re.compile(r"^  function ([A-Za-z_$][\w$]*)", re.M)

results = []


def case(name, ok, reason=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {reason}" if reason else ""))


def dup_names(src):
    """Names declared more than once at closure top level (2-space indent)."""
    seen = TOP_FN.findall(src)
    return sorted({n for n in seen if seen.count(n) > 1})


def run_guard(tree_page, tmp):
    """Run the developer guard test against a scratch tree; return exit code."""
    test = tmp / "server/plugins/executor-panel/tests"
    test.mkdir(parents=True, exist_ok=True)
    shutil.copy2(GUARD_TEST, test / GUARD_TEST.name)
    env_page = tmp / "server/plugins/executor-panel/src/host/panel-page.ts"
    env_page.parent.mkdir(parents=True, exist_ok=True)
    env_page.write_bytes(tree_page)
    repo_root = tmp  # the test resolves REPO as five levels up from its own file
    proc = subprocess.run(
        ["node", "--test", str(test / GUARD_TEST.name)],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
             "TMPDIR": str(tmp)},
        cwd=str(repo_root))
    return proc


def main():
    case("A1-page-and-guard-test-present", PAGE.is_file() and GUARD_TEST.is_file(),
         f"page={PAGE} guard_test={GUARD_TEST}")
    if not PAGE.is_file():
        finish()
    if not GUARD_TEST.is_file():
        print("FAIL-named: guard test missing (pre-implement TDD red is expected; "
              "arbitrate/merge requires it green)")
        finish()

    before = PAGE.read_bytes()
    src = before.decode("utf-8", errors="replace")

    dups = dup_names(src)
    case("A2-no-duplicate-top-level-names-in-real-page", len(dups) == 0,
         (f"duplicated top-level names: {dups}" if dups else "no duplicate top-level names"))

    # A3 mutation probe, in memory only.
    victim = "renderEpics" if "renderEpics" in TOP_FN.findall(src) else (TOP_FN.findall(src) or ["zzz"])[0]
    mutated = src + f"\n  function {victim}(){{}}\n"
    got = dup_names(mutated)
    case("A3a-detector-flags-injected-duplicate", got == [victim],
         f"injected duplicate of {victim}; detector reported {got}")
    nested = src + f"\nfunction wrap(){{\n    function {victim}(){{}}\n}}\n"
    case("A3b-nested-same-name-not-counted", dup_names(nested) == [],
         "a deeper-indented same-named function must not count as top-level")

    with tempfile.TemporaryDirectory(prefix="sandbar-t261024-21-") as td:
        tmp = pathlib.Path(td)
        pristine = run_guard(before, tmp)
        mutated_tree = before + f"\n  function {victim}(){{}}\n".encode()
        bitten = run_guard(mutated_tree, tmp)
        out = (bitten.stdout + bitten.stderr)
        case("A4a-guard-green-on-pristine-copy", pristine.returncode == 0,
             f"exit={pristine.returncode}")
        case("A4b-guard-red-on-mutated-copy", bitten.returncode != 0,
             f"exit={bitten.returncode}; tail={out[-200:]!r}")
        case("A4c-guard-names-the-duplicate", victim in out,
             f"guard output must name {victim}")

    case("A5-tree-unmutated", PAGE.read_bytes() == before, "page file byte-identical after the probe")
    finish()


def finish():
    fail = results.count(False)
    env = 0
    print(f"SUMMARY pass={len(results) - fail} fail={fail} env_fail={env} na=0")
    sys.exit(2 if env else (1 if fail else 0))


if __name__ == "__main__":
    node = shutil.which("node")
    if node is None:
        print("ENV_FAIL: node not found on PATH — the guard-bite legs cannot run (KI-036 family)")
        print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
        sys.exit(2)
    main()
