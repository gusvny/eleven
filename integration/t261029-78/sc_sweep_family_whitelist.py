#!/usr/bin/env python3
"""sc_sweep_family_whitelist — the sweeper's declared families and the guards around them.

t261029-78, grey-box L3. Fabricated temp root (zero dependence on the host's real temp
dir), offline, seconds, zero docker, zero Temporal, never touches 3099/7233.

Measured fault (host temp dir, 2026-10-29 around 20:00): 212 GB, 113,118 top-level
entries, and the sweeper reclaimed 877.6 MB because its prefix whitelist only knew the
producer families of 260926/260927/261002. The families that fill the disk today are
dz3-pyc (35,074 dirs, 1.3-4.0 MB each => tens of GB), t261014-08-pyc (36,311 empty dirs),
t261018-04-ut (9,498), dz3-no-numpy (2,565), agg-test (2,389), coverage-test (1,768).

intent — ONE face, four claims:
  A THE DECLARATION IS DATA: every measured family is declared with a reason, a project
    and a producer file:line, the effective whitelist is core + declared, the core list
    (drift-locked to the engine water line) is unchanged, and a half-written record is a
    NAMED refusal rather than a family that silently never matches.
  B BY CONSTRUCTION on a fabricated root: a stale entry of a newly declared family is
    swept; a fresh one is kept (the age floor bites); an unlisted family is never swept;
    an EXCLUDED_PREFIXES family is never swept.
  C THE GUARDS KEEP THEIR TEETH FOR THE NEW FAMILIES: a file held by a live flock is kept
    and named; a directory whose cwd carries a live process is kept and named.
  D THE RECEIPT IS PER FAMILY IN BOTH MODES: --apply prints the same lines the dry-run
    prints (same layout, real numbers), and the family that was swept is visible on it
    instead of collapsing into one total.

Intent split: the judgment functions (scan buckets, file/dir split, BATCH2 regression lock,
carrier-by-cwd truth table) belong to developer L1
(server/engine/tests/test_t260927_tmp_fixture_family.py,
integration/tests/test_t261001_fixture_carriers.py); the sweeper CLI safety quadrants
belong to t261002-13/sc_tmp_backlog_sweep_safety.py. THIS entry uniquely owns the declared
family list and the per-family receipt in applied mode.

cost: seconds (two real CLI sweeps over a fabricated root of six entries + one refusal).
Timing: no evidence is bought with a wait. The two helper processes (lock holder, cwd
carrier) live exactly as long as this scenario - each blocks on its own stdin and the
teardown closes the pipe - and the only ceiling is the injectable per-run child guard
SANDBAR_SWEEP_FAMILY_CHILD_CEILING_SEC (missing knob = 120s), which fires as a NAMED
environment red instead of hanging the round.
Three-state: tool/venv/fcntl absent = ENV_FAIL exit 2; assertion failed = FAIL exit 1;
all green = PASS exit 0.

Run (cwd = repo root): python3 integration/t261029-78/sc_sweep_family_whitelist.py
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SWEEP = ROOT / "integration" / "tools" / "sweep_tmp_fixtures.py"
PY = sys.executable

#: The families the 2026-10-29 measurement named (ticket spec, counts re-taken by this
#: scenario's author before the change: 36,961 / 35,898 / 9,693 / 2,660 / 2,389 / 1,768).
MEASURED_FAMILIES = ("t261014-08-pyc", "dz3-pyc", "t261018-04-ut", "dz3-no-numpy",
                     "agg-test", "coverage-test")
STALE_H = 9.0          # far past the 6h default age gate
FRESH_H = 0.25         # far below it: "a suite is running in here"

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def die_env(msg):
    print("ENV_FAIL: " + msg, file=sys.stderr)
    sys.exit(2)


def load_sweep():
    """The sweeper module itself (in-process): declaration data is read, never re-typed."""
    spec = importlib.util.spec_from_file_location("sweep_probe", str(SWEEP))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_entry(root, name, age_h, kind="dir", payload=b"x" * 2048):
    """Create one fixture entry with a chosen age (the sweeper judges mtime, nothing else)."""
    p = Path(root) / name
    if kind == "file":
        p.write_text("held", encoding="utf-8")
    else:
        p.mkdir(parents=True)
        inner = p / "inner"
        inner.mkdir()
        (inner / "payload.bin").write_bytes(payload)
    old = time.time() - age_h * 3600.0
    os.utime(str(p), (old, old))
    return p


#: Hard-kill guard for ONE sweeper child run - never a condition this scenario waits on.
#: Injectable on the project's knob convention (a slow host widens it without editing this
#: file), and the class the case declares is `cost: seconds`, so no elapsed time is ever the
#: evidence: the receipt is. The guard fires as a NAMED environment red naming the child and
#: the knob, so a hang can never present as a silent pass or a bare traceback.
CHILD_CEILING_S = float(os.environ.get("SANDBAR_SWEEP_FAMILY_CHILD_CEILING_SEC", "120"))


def run_tool(args):
    """One real sweeper CLI run under the injectable child ceiling."""
    try:
        return subprocess.run([PY, str(SWEEP)] + args, cwd=str(ROOT),
                              capture_output=True, text=True, timeout=CHILD_CEILING_S)
    except subprocess.TimeoutExpired:
        die_env("child ceiling fired: `sweep_tmp_fixtures.py %s` did not finish in %.0fs "
                "(knob SANDBAR_SWEEP_FAMILY_CHILD_CEILING_SEC) - the failing check is the "
                "sweeper CLI run itself" % (" ".join(args), CHILD_CEILING_S))


def family_lines(text):
    """The per-family receipt lines (the shared printer's output) from a run's log."""
    return [ln.rstrip() for ln in text.splitlines() if ln.strip().startswith("family ")]


def family_template(line):
    """A receipt line's LAYOUT: digits and the mode-dependent swept label normalised away.

    Two modes printing "the same lines" means same layout and same fields - the numbers
    are supposed to differ (candidates vs real deletions).
    """
    flat = re.sub(r"\b(would-sweep|swept)=", "SWEPT=", line)
    return re.sub(r"\d+(\.\d+)?([A-Za-z]{1,2})?", "#", flat)


def row_of(payload, prefix):
    return next((r for r in payload.get("per_family") or [] if r["prefix"] == prefix), None)


def main():
    if not SWEEP.is_file():
        die_env("sweeper missing: %s" % SWEEP)
    try:
        import fcntl  # noqa: F401  (the live-lock guard needs it)
    except ImportError:
        die_env("fcntl unavailable on this platform (live-lock subcase cannot run)")
    try:
        sw = load_sweep()
    except Exception as e:                        # noqa: BLE001 - named env failure
        die_env("sweeper not importable: %s: %s" % (type(e).__name__, e))

    sys.path.insert(0, str(ROOT / "integration"))
    import lib_tmp_reclaim as lr  # noqa: E402

    # ---- A. the declaration is data, complete, and fail-closed ----------------------
    print("A. declared family list (data, reason + provenance)")
    for fam in MEASURED_FAMILIES:
        ok(fam in sw.DECLARED_PREFIXES, "A declared: %s is on the declared family list" % fam)
    complete = []
    for rec in sw.DECLARED_FAMILIES:
        if all(str(getattr(rec, f) or "").strip() for f in
               ("prefix", "kind", "project", "reason", "producer", "measured", "added_by")):
            complete.append(rec.prefix)
        else:
            print("    incomplete record: %r" % (rec,))
    ok(len(complete) == len(sw.DECLARED_FAMILIES),
       "A every declared family carries kind/project/reason/producer/measured/added_by")
    ok(all(":" in rec.producer for rec in sw.DECLARED_FAMILIES),
       "A every declared family names a producer file:line (provenance, not a guess)")
    core = tuple(sw.TMP_FIXTURE_PREFIXES)
    ok(tuple(sw.SWEEP_PREFIXES[:len(core)]) == core,
       "A the effective whitelist starts with the unchanged, drift-locked core list")
    ok(tuple(sw.SWEEP_PREFIXES[len(core):]) == tuple(
        p for p in sw.DECLARED_PREFIXES if p not in core),
       "A the effective whitelist appends exactly the declared families")
    ok(not [p for p in sw.DECLARED_PREFIXES if p in core],
       "A no declared family hides inside the core list (the extension is what covers them)")
    ok(sw.declaration_errors() == [], "A the shipped declaration is clean (no named defect)")
    bad = sw.FixtureFamily("dz3-pyc", "dir", "project-vision", "", "fpv-midnight/check.py:625",
                           "measured", "t261029-78")
    bad_errs = sw.declaration_errors(families=(bad,))
    ok(bool(bad_errs) and "reason" in bad_errs[0],
       "A a record with no reason is a NAMED defect (half-written data is refused)")
    # A declared prefix that a core prefix already covers would be matched by the core
    # family first: the declaration would look present and never own an entry.
    shadowed = sw.FixtureFamily("t260907-06-ut-extra", "dir", "sandbar", "r", "p:1", "m",
                                "t261029-78")
    ok(any("shadowed" in e for e in sw.declaration_errors(families=(shadowed,))),
       "A a declared prefix shadowed by a core prefix is a NAMED defect")

    # ---- fabricated root: one entry per claim ---------------------------------------
    box = lr.mkdtemp_reclaimed("t261029-78-sc-whitelist-")
    stale_declared = make_entry(box, "dz3-pyc-stale", STALE_H)
    fresh_declared = make_entry(box, "t261014-08-pyc-fresh", FRESH_H)
    stale_ut = make_entry(box, "t261018-04-ut-stale", STALE_H)
    unlisted = make_entry(box, "unlisted-family-stale", STALE_H)
    excluded = make_entry(box, "com.google.Chrome.aged", STALE_H)
    held_lock = make_entry(box, "dz3-pyc-held.lock", STALE_H, kind="file")
    carrier_dir = make_entry(box, "dz3-no-numpy-carrier", STALE_H)

    # Both helpers live exactly as long as this scenario does: each blocks reading its own
    # stdin and the teardown closes that pipe, so the child exits on EOF. Lifetime is the
    # parent's, never a wall clock - no timer is slept on the production or the test side,
    # and a scenario that dies mid-run leaves no child counting down to its own end.
    # The holder announces the lock only after flock() returned, so the parent never races
    # the guard it is testing and never waits for a duration to pass.
    holder = subprocess.Popen(
        [PY, "-c",
         "import fcntl,sys;f=open(sys.argv[1],'r+');fcntl.flock(f,fcntl.LOCK_EX);"
         "print('locked',flush=True);sys.stdin.read()", str(held_lock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    carrier = None
    try:
        ok(holder.stdout.readline().strip() == "locked",
           "C0 the lock holder signalled the flock it holds (a named handshake, not a wait)")

        # The carrier must simply stay alive inside its fixture dir while the sweeps run:
        # the sweeper judges a carrier by the process cwd, not by its command line.
        carrier = subprocess.Popen([PY, "-c", "import sys;sys.stdin.read()"],
                                   cwd=str(carrier_dir), stdin=subprocess.PIPE)

        # ---- B/C/D on the dry-run ---------------------------------------------------
        dry = run_tool(["--root", str(box), "--json"])
        ok(dry.returncode == 0, "B0 dry-run exits 0")
        dj = {}
        try:
            dj = json.loads(dry.stdout)
        except ValueError:
            ok(False, "B0 dry-run emits machine-readable JSON on stdout")
        dry_text = dry.stderr
        ok(stale_declared.exists() and stale_declared.is_dir(),
           "B0 dry-run deleted nothing (the stale declared dir is still there)")
        row = row_of(dj, "dz3-pyc") or {}
        ok(row.get("swept", 0) >= 1,
           "B1 a stale entry of a newly declared family is a sweep candidate (dz3-pyc)")
        fresh_row = row_of(dj, "t261014-08-pyc") or {}
        ok(fresh_declared.exists() and fresh_row.get("live", 0) >= 1
           and fresh_row.get("swept", 0) == 0,
           "B2 a fresh entry of a declared family is kept, counted live and not a candidate"
           " (age floor)")
        ok(unlisted.exists() and not row_of(dj, "unlisted-family-"),
           "B3 an unlisted family is never swept (outside the whitelist, untouched)")
        ok(excluded.exists() and (dj.get("excluded_by_prefix") or {}).get("com.google.Chrome."),
           "B4 an EXCLUDED_PREFIXES family is never swept (and stays visible per family)")
        ok(held_lock.exists() and any("dz3-pyc-held" in n
                                      for n in (dj.get("locks_kept_named") or [])),
           "C1 a file held by a live flock is kept and named on the dry-run receipt")
        ok(carrier_dir.exists() and "dz3-no-numpy-carrier" in (dj.get("carriers") or {}),
           "C2 a dir whose cwd carries a live process is kept and named (carrier)")
        dry_rows = family_lines(dry_text)
        ok(bool(dry_rows), "D1 the dry-run prints per-family receipt lines")
        ok(any(re.match(r"\s*family dz3-pyc\s", ln) for ln in dry_rows),
           "D1b the newly declared family has its own receipt line")
        ok(any("why:" in ln for ln in dry_text.splitlines())
           and any("who:" in ln for ln in dry_text.splitlines()),
           "D1c a declared family's receipt line carries its reason and provenance")
        ok("ENGINE MIRROR GAP:" in dry_text,
           "D1d the engine water-line gap for the new families is NAMED, not silent")
        ok(any("dz3-pyc-held.lock (lock held by a live process)" in ln
               for ln in dry_text.splitlines()),
           "C1b the kept lock is named with its reason on the family receipt")

        # ---- B/C/D on the applied sweep --------------------------------------------
        applied = run_tool(["--root", str(box), "--json", "--apply"])
        ok(applied.returncode == 0, "B5 --apply exits 0")
        aj = {}
        try:
            aj = json.loads(applied.stdout)
        except ValueError:
            ok(False, "B5 --apply emits machine-readable JSON on stdout")
        apply_text = applied.stderr
        ok(not stale_declared.exists(),
           "B1b the stale entry of the declared family was really swept by --apply")
        ok(not stale_ut.exists(),
           "B1c a second declared family (t261018-04-ut) was swept too")
        ok(fresh_declared.exists(), "B2b the fresh entry survived the applied sweep")
        ok((row_of(aj, "t261014-08-pyc") or {}).get("live", 0) >= 1,
           "B2c the applied receipt counts the fresh declared family as kept live")
        ok(unlisted.exists(), "B3b the unlisted family survived the applied sweep")
        ok(excluded.exists(), "B4b the excluded family survived the applied sweep")
        ok(held_lock.exists() and any("dz3-pyc-held" in n
                                      for n in (aj.get("locks_kept_named") or [])),
           "C1c the live-locked file is kept and named by --apply")
        ok(carrier_dir.exists(),
           "C2c the carrier dir is kept by --apply (no --kill-carriers)")
        ok(any("dz3-no-numpy-carrier" in n for n in (aj.get("carriers_named") or [])),
           "C2d the kept carrier is named on the applied receipt")
        apply_rows = family_lines(apply_text)
        ok(bool(apply_rows), "D2 --apply prints per-family receipt lines (not only a total)")
        arow = row_of(aj, "dz3-pyc") or {}
        ok(arow.get("swept", 0) >= 1 and arow.get("freed_bytes", 0) > 0,
           "D3 the applied receipt shows the swept family with its count and freed bytes")
        ok(any("swept=" in ln for ln in apply_rows),
           "D3b the applied receipt carries a real swept column (not would-sweep)")
        dry_tpl = {ln.split()[1]: family_template(ln) for ln in dry_rows}
        apply_tpl = {ln.split()[1]: family_template(ln) for ln in apply_rows}
        shared = sorted(set(dry_tpl) & set(apply_tpl))
        ok(bool(shared) and all(dry_tpl[k] == apply_tpl[k] for k in shared),
           "D4 dry-run and --apply print the SAME per-family lines (layout identical)")
        ok(set(apply_tpl) <= set(sw.SWEEP_PREFIXES),
           "D5 every applied receipt line names a declared/core family (nothing invented)")

        # ---- the 1h floor still refuses --------------------------------------------
        floor = run_tool(["--root", str(box), "--apply", "--max-age-h", "0.5"])
        ok(floor.returncode != 0 and "REFUSED" in (floor.stdout + floor.stderr),
           "E1 --apply below the 1h hard floor is still refused by name")
    finally:
        # Closed stdin is the whole shutdown protocol: the child sees EOF and leaves by
        # itself, so no helper ever outlives its parent. terminate/kill stay as belt and
        # braces for a child wedged outside its read (20s here is a reap guard, never a
        # condition the scenario waits on).
        for proc in (carrier, holder):
            if proc is None:
                continue
            try:
                if proc.stdin is not None and not proc.stdin.closed:
                    proc.stdin.close()
            except OSError:                        # already gone between poll and close
                pass
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
        lr.reclaim_registered()
        if box.exists():                          # belt and braces: the receipt is the claim
            shutil.rmtree(str(box), ignore_errors=True)

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
