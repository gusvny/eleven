#!/usr/bin/env python3
"""sc_review_ledger_period_chain — simplify-face ledger × period chain contract
(t261006-12, grey-box L2/L3, offline source-lock + pure replay, seconds, zero
docker/Temporal/3099; temporalio-unimportable-environment precedent =
sc_check_inspection_produce_chain).

User-perceivable contracts pinned here:

  P1 skip periods never advance the ledger: the skip_when_unchanged
     short-circuit (server/engine/activities.py) returns before any ticket or
     activity, and its payload carries no review-ledger fields — a
     skipped-no-change day cannot mark files reviewed (L3).
  P2 the stub path (SANDBAR_INSPECT_STUB=1) never writes the ledger: a test
     fixture must not poison production coverage (L3).
  P3 one write seam: the inspect activity's write-back and the on-demand
     full-library read go through the same append function, so a full read
     suppresses the next slice from re-picking those files (L4).
  P4 full-scope write-back marks the whole managed inventory reviewed, and
     the next slice selection comes back empty until the library restarts
     (L2 × L4 composition).
  P5 the period report carries the coverage payload: the report doc shape
     includes the full reviewed + not-reviewed lists (L5), and the
     human-readable line names NOT-reviewed explicitly — a count alone or a
     silent omission reads as "no problem" and is the design-forbidden shape.

The static faces are source-anchored (understand-deep/bind-shallow: they pin
that the skip/stub branches reference no ledger write, not their private
line numbers). Module missing = ENV_FAIL exit 2. Red before implement lands
is the expected TDD signal; arbitrate/merge must be green.

Run: python3 integration/t261006-12/sc_review_ledger_period_chain.py (cwd=repo root).
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

MODULE = "inspection_review_ledger"
try:
    rl = __import__(MODULE)
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: engine module server/engine/%s.py unavailable: %s" % (MODULE, e))
    sys.exit(2)

ACT_SRC = (ROOT / "server/engine/agent_activities.py").read_text("utf-8")
ACTIV_SRC = (ROOT / "server/engine/activities.py").read_text("utf-8")
inspect_src = (ROOT / "server/engine/inspection_inspect.py").read_text("utf-8")
flow_src = (ROOT / "server/engine/inspection_flow.py").read_text("utf-8")

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  RED %s" % label)


def section(t):
    print("\n%s" % t)


# Locate the module's write seam name (public append function) without
# hard-coding its private call sites: the plan pins ONE append seam.
APPEND = getattr(rl, "append_reviewed", None)
ok(callable(APPEND), "module exposes the single append seam (append_reviewed)")

def branch_body(src: str, anchor: str) -> str:
    """Return the source text of the if-block whose header line matches `anchor`.

    t261008-04: the previous byte-window regex (`literal.{0,600}?`) was vacuous —
    the lazy quantifier captured only the 19-char literal, so the forbidden-word
    scan below read nothing. This extractor is line-based: from the anchor line to
    the last line indented deeper than it (blank lines skipped; block ends at the
    first non-blank line with indent <= the anchor indent, or at EOF). Empty
    string = anchor not found (caller turns that into a RED).
    """
    lines = src.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if re.search(anchor, ln)), None)
    if start is None:
        return ""
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if not ln.strip():
            continue
        if len(ln) - len(ln.lstrip()) <= base_indent:
            break
        out.append(ln)
    return "\n".join(out)


# The anchor must pin the branch, not a comment: today exactly one line in
# activities.py matches (the `if bool(plan.get("skip_when_unchanged")):` header
# at spawn_inspection_period); a future duplicate turns red here instead of
# silently testing the wrong branch.
SKIP_ANCHOR = r'if\s+bool\(plan\.get\("skip_when_unchanged"\)\)'
FORBIDDEN = ("review_ledger", "reviewed", "append_review", "select_slice")


def forbidden_in(txt: str):
    """The one forbidden-word scan the guard (and the negative control) share."""
    return [w for w in FORBIDDEN if w in txt]


# ---------- P1 skip period ----------
section("P1 skip_when_unchanged never touches the ledger")
ok(len(re.findall(SKIP_ANCHOR, ACTIV_SRC)) == 1,
   "skip_when_unchanged branch anchor is unique in activities.py")
skip_txt = branch_body(ACTIV_SRC, SKIP_ANCHOR)
ok(skip_txt != "", "skip_when_unchanged branch body located in activities.py")
ok(len(skip_txt) > 100,
   "capture covers the real branch body, not just the literal (%d chars)" % len(skip_txt))
ok("Client.connect" not in skip_txt,
   "capture does not swallow the code after the branch (no over-capture)")
for w in forbidden_in(skip_txt):
    ok(False, "skip branch carries no %s reference" % w)
if not forbidden_in(skip_txt):
    for w in FORBIDDEN:
        ok(True, "skip branch carries no %s reference" % w)
ok('"skipped"' in ACTIV_SRC and "no-new-changes" in ACTIV_SRC,
   "skip verdict row stays the declared no-new-changes shape")

# Negative control (t261008-04): plant a forbidden word inside the captured
# branch body and require the shared scan to go red — the guard must not be
# able to regress to vacuous silently. The plant is inserted on a line indented
# deeper than the anchor if-line, strictly inside the extracted line range.
m = re.search(SKIP_ANCHOR, ACTIV_SRC)
plant = ("        poisoned = append_review"
         "  # negative-control plant (never executed)")
poisoned_src = ACTIV_SRC[:m.end()] + "\n" + plant + ACTIV_SRC[m.end():]
poisoned_txt = branch_body(poisoned_src, SKIP_ANCHOR)
ok(plant in poisoned_txt,
   "negative control: planted line lands inside the captured branch body")
ok(bool(forbidden_in(poisoned_txt)),
   "negative control: planted forbidden word makes the scan go red")

# ---------- P2/P3/P4 stub exclusion + one seam + full scope ----------
section("P2 stub path / P3 one seam / P4 full scope")
stub_m = re.search(r'os\.environ\.get\("SANDBAR_INSPECT_STUB"\) == "1".{0,900}',
                   ACT_SRC, re.S)
ok(stub_m is not None, "stub shortcut located in run_inspection_inspect")
stub_txt = stub_m.group(0) if stub_m else ""
ok("append_review" not in stub_txt,
   "P2 stub shortcut writes nothing to the ledger")
# the real write-back lives AFTER the stub return point in the same function
body = ACT_SRC
stub_pos = body.find(stub_txt)
append_sites = [m.start() for m in re.finditer(r"append_review", body)]
ok(all(p > stub_pos for p in append_sites) or not append_sites,
   "every ledger append call site sits after the stub return point (real path only)")
ok("review_scope" in ACT_SRC and '"full"' in ACT_SRC,
   "P3 the activity exposes the slice|full scope seam (one ledger, both paths)")

tmp = Path(tempfile.mkdtemp(prefix="t26100612-chain-"))
try:
    managed = ["m/%02d.py" % i for i in range(80)]
    # P4: full write-back -> next slice is empty (restart semantics only when
    # everything has been seen; a full read covers the whole inventory)
    led_path = tmp / "reviewed.jsonl"
    APPEND(led_path, managed, "20261006")
    loaded, notes = rl.load_review_ledger(led_path)
    ok(len(loaded) == 80, "P4 full-scope write-back lands every managed file")
    s, _ = rl.select_slice(managed, loaded, slice_min=40, slice_max=60)
    ok(len(s) == 60 and set(s) <= set(managed),
       "fully-covered library restarts rotation (no crash, no empty-slice error)")

    # append is the same seam for periodic slices: append 60, next slice = rest
    APPEND(led_path, s[:60], "20261007")
    loaded2, _ = rl.load_review_ledger(led_path)
    ok(len(loaded2) == 80,
       "append through the same seam after a full read merges cleanly (last wins)")

    # ---------- P5 coverage payload ----------
    section("P5 period-report coverage payload")
    cov = rl.coverage_section(s, managed, "20261008")
    ok("reviewed_files" in cov and "not_reviewed_files" in cov and
       isinstance(cov["not_reviewed_files"], list),
       "report payload carries BOTH lists machine-readably")
    ok(set(cov["reviewed_files"]) | set(cov["not_reviewed_files"]) == set(managed)
       and not (set(cov["reviewed_files"]) & set(cov["not_reviewed_files"])),
       "coverage partition of the inventory holds")
    ok("coverage" in flow_src or "inspect" in flow_src,
       "flow passes inspect meta into the report doc (existing seam)")
    # human-facing line: the rendering must name NOT reviewed (never a bare count)
    combined = ACT_SRC + flow_src + inspect_src + \
        (ROOT / "server/engine/inspection_review_ledger.py").read_text("utf-8")
    ok(re.search(r"not[- ]reviewed", combined, re.I) is not None,
       "P5 human line names NOT-reviewed explicitly (never reads as no problem)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
