#!/usr/bin/env python3
"""t261011-11 — the fast set's patrol face and its recorded verdict ledger.

Grey-box L3 over the REAL run_scenarios.py CLI (subprocess) plus the public
review core discovered by contract name (capability discovery, so a
contract-preserving refactor stays green). Offline seconds, zero docker /
Temporal / browser, never touches 3099/7233.

User need (ticket body): nobody can see why a member is in the fast set, what
it costs, or what it has ever caught — membership can only drift by hand
edits nobody can audit. This scenario judges the patrol face
(`--print-fast-set-review`, ONE read-only face) and the append-only verdict
ledger whose reader is that same face.

Exit codes: 0 PASS, 1 FAIL (every sub-case failing is named), 2 ENV_FAIL.
Temp fixtures live under tempfile.TemporaryDirectory and are reclaimed.
"""

import inspect
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
RS = os.path.join(REPO, "integration", "run_scenarios.py")
FAILS = []


def fail(tag, detail):
    FAILS.append("%s: %s" % (tag, detail))
    print("FAIL %s — %s" % (tag, detail), flush=True)


def py():
    v = os.path.join(REPO, "server", "engine", ".venv", "bin", "python")
    return v if os.path.exists(v) else sys.executable


def run_face(extra_args, env_extra, tmp):
    """Run the real CLI face in a subprocess with injected env seams."""
    env = dict(os.environ)
    env["SANDBAR_SCENARIO_LEDGER_DIR"] = os.path.join(tmp, "scen-ledger")
    env["SANDBAR_FAST_SET_REVIEW_LEDGER"] = os.path.join(tmp, "verdicts.jsonl")
    env.pop("SANDBAR_KNOWN_RED_ROSTER", None)  # real tree roster by default
    os.makedirs(env["SANDBAR_SCENARIO_LEDGER_DIR"], exist_ok=True)
    env.update(env_extra or {})
    p = subprocess.run(
        [py(), "-B", RS] + list(extra_args), cwd=REPO, env=env,
        capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def scen_row(name, wall_s, verdict="pass", ts="2026-10-11T08:00:00+00:00",
             run="r1", commit="t26101111a"):
    return {"ts": ts, "commit": commit, "env_fp": "fx", "conc_width": 3,
            "pool": "ro", "scenario": name, "verdict": verdict,
            "wall_s": wall_s, "source": "inspection", "ticket": "t261011-11",
            "run": run}


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_roster(path, names):
    entries = [{"name": n, "verdict": "booked", "owner": "integration",
                "retire_when": "fix landed"} for n in names]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"meta": {}, "entries": entries}, fh)


def real_members():
    """Real fast members from the ONE registry, via the public helper."""
    sys.path.insert(0, os.path.join(REPO, "integration"))
    import run_scenarios as rs  # noqa: PLC0415 — in-process, established practice
    return rs, rs.fast_set_entries()


def main():
    if not os.path.isfile(RS):
        print("ENV_FAIL: run_scenarios.py missing: %s" % RS, flush=True)
        return 2

    # ---- A: the real-tree face exists, exits 0, and prints the declarations
    # beside the measurements (empty ledgers: no-measurement named per member).
    with tempfile.TemporaryDirectory(prefix="fsrev-a-") as tmp:
        rc, out = run_face(["--print-fast-set-review"], {}, tmp)
        if rc != 0:
            fail("A-exit", "face exited %d (want 0). output tail: %s"
                 % (rc, out[-400:]))
        for token, tag in (("cadence", "A-cadence"), ("window", "A-window")):
            if token not in out:
                fail(tag, "header does not name the declared %s" % token)
        if "budget" not in out:
            fail("A-budget", "declarations (budget/width) not printed")
        _, members = real_members()
        if len(members) < 1:
            fail("A-members", "registry has no fast members to judge")
        for e in members:
            if ("member %s " % e[0]) not in out:
                fail("A-per-member", "member %s has no line on the face"
                     % e[0])
            elif "fast-catch" not in out.split("member %s " % e[0])[1][:400]:
                fail("A-catch", "member %s line lacks its fast-catch clause"
                     % e[0])
        if "no measured cost" not in out:
            fail("A-nomeasure", "empty ledger: no-measurement case not NAMED")
        if "no recorded patrol verdict" not in out:
            fail("A-noverdict", "absent verdict ledger: the face must name "
                                "the no-recorded-verdict case, never silence")

    # ---- B: fixture scenario ledger — mean AND max, a red named as a catch,
    # and the no-catch window flag for a member with no reds.
    with tempfile.TemporaryDirectory(prefix="fsrev-b-") as tmp:
        _, members = real_members()
        names = [e[0] for e in members]
        if len(names) < 2:
            fail("B-fixtures", "need >=2 members to judge stats; got %d"
                 % len(names))
        else:
            sld = os.path.join(tmp, "scen-ledger")
            os.makedirs(sld, exist_ok=True)
            write_jsonl(os.path.join(sld, "scenario-results.jsonl"), [
                scen_row(names[0], 1.0, run="r1"),
                scen_row(names[0], 3.0, run="r2", commit="t26101111b"),
                scen_row(names[0], 3.0, verdict="fail", run="r3",
                         commit="t26101111c"),
                scen_row(names[1], 0.5, run="r1"),
                scen_row(names[1], 0.5, run="r2", commit="t26101111b"),
            ])
            rc, out = run_face(["--print-fast-set-review"], {}, tmp)
            if rc != 0:
                fail("B-exit", "face exited %d with fixture ledger" % rc)
            seg = out.split("member %s " % names[0])[1][:600] \
                if ("member %s " % names[0]) in out else ""
            if "mean=2" not in seg or "max=3" not in seg:
                fail("B-stats", "member %s: mean=2/max=3 not both shown "
                                "(got: %s)" % (names[0], seg[:200]))
            if "red" not in out.lower():
                fail("B-red", "a member red inside a judged round is not "
                              "surfaced as evidence on the face")
            seg1 = out.split("member %s " % names[1])[1][:600] \
                if ("member %s " % names[1]) in out else ""
            if "no-catch" not in out:
                fail("B-window", "no-catch-in-window flag never fires (N "
                                 "must be declared on the face, not hidden)")
            if "runs=2" not in seg1:
                fail("B-runs", "member %s: run count not shown next to the "
                               "cost" % names[1])

    # ---- C: the verdict ledger — recorded rows read back by the SAME face;
    # corrections are new rows (last wins); malformed rows named, non-fatal.
    with tempfile.TemporaryDirectory(prefix="fsrev-c-") as tmp:
        _, members = real_members()
        name = members[0][0]
        vpath = os.path.join(tmp, "verdicts.jsonl")
        base = {"at": "2026-10-10T09:00:00+00:00", "member": name,
                "cost_s": 1.5, "evidence": "mean 1.5s over 2 runs",
                "who": "integration patrol"}
        rows = [dict(base, verdict="keep"),
                dict(base, verdict="remove",
                     at="2026-10-11T09:00:00+00:00",
                     evidence="over budget contribution, corrected")]
        write_jsonl(vpath, rows)
        with open(vpath, "a", encoding="utf-8") as fh:
            fh.write("{not json\n")
            fh.write(json.dumps({"at": "", "member": name,
                                 "verdict": "maybe"}) + "\n")
        rc, out = run_face(["--print-fast-set-review"], {}, tmp)
        seg = out.split("member %s " % name)[1][:600] \
            if ("member %s " % name) in out else ""
        if "remove" not in seg:
            fail("C-correction", "last recorded verdict (remove) not shown "
                                 "for %s; corrections must be new rows whose "
                                 "reader sees the latest (got: %s)"
                                 % (name, seg[:200]))
        if "malformed" not in out.lower() and "warn" not in out.lower():
            fail("C-malformed", "malformed verdict rows not named on the face")
        if rc != 0:
            fail("C-exit", "malformed verdict rows must degrade NAMED, not "
                           "refuse the whole face (exit %d)" % rc)

    # ---- D: a member that became booked must LOSE membership — named
    # fail-closed, non-zero exit, never silently kept.
    with tempfile.TemporaryDirectory(prefix="fsrev-d-") as tmp:
        _, members = real_members()
        name = members[0][0]
        roster = os.path.join(tmp, "roster.json")
        write_roster(roster, [name])
        rc, out = run_face(["--print-fast-set-review"],
                           {"SANDBAR_KNOWN_RED_ROSTER": roster}, tmp)
        if rc == 0:
            fail("D-exit", "booked member %s: face must exit non-zero (fail "
                           "closed), got 0" % name)
        if "must-lose" not in out:
            fail("D-name", "booked member %s not NAMED as "
                           "must-lose-membership. tail: %s"
                           % (name, out[-400:]))

    # ---- E: the pure review core over a FIXTURE registry — browser-pool
    # must-lose and a coverage gap (driven from the registry's own grouping).
    sys.path.insert(0, os.path.join(REPO, "integration"))
    import run_scenarios as rs  # noqa: PLC0415
    core = getattr(rs, "fast_set_review", None)
    if core is None:
        fail("E-core", "public review core fast_set_review() missing — the "
                       "flag logic cannot be judged over a fixture registry")
    else:
        try:
            fx_members = [("fx-a", "d", "c", "ro", "fast"),
                          ("fx-b", "d", "c", "ro", "serial", "fast"),
                          ("fx-browser", "d", "c", "browser", "fast")]
            blob = json.dumps(core(
                fx_members,
                {"fx-a": {"mean_s": 150.0, "max_s": 150.0, "runs": 1},
                 "fx-b": {"mean_s": 0.5, "max_s": 0.5, "runs": 1}},
                set(), {}, {"rounds": ["r1"]}, {}, width=3), default=str)
            if "must-lose-membership:browser-pool" not in blob:
                fail("E-browser", "a browser-pool fast member is not flagged "
                                  "must-lose-membership:browser-pool over the "
                                  "fixture registry. blob: %s" % blob[:400])
            booked_blob = json.dumps(core(fx_members[:1], {}, {"fx-a"}, {},
                                         {"rounds": ["r1"]}, {}, width=3),
                                     default=str)
            if "must-lose-membership:booked" not in booked_blob:
                fail("E-booked", "a booked member is not flagged "
                                 "must-lose-membership:booked by the core")
            if "over-budget" not in blob:
                fail("E-budget", "over-budget-share flag not fired for a "
                                 "member measured far over its declared "
                                 "budget share")
            uncovered = getattr(rs, "fast_set_uncovered_pools", None)
            if uncovered is None:
                fail("E-gap-helper", "fast_set_uncovered_pools() missing — "
                                     "the coverage gap cannot be derived "
                                     "from the registry's own grouping")
            else:
                fx_reg = [("s1", "d", "c", "ro"), ("f1", "d", "c", "ro",
                                                   "fast"),
                          ("s2", "d", "c", "engine")]
                got = uncovered(fx_reg)
                if got != ["engine"]:
                    fail("E-gap", "coverage gap over fixture registry should "
                                  "name pool 'engine' only, got %r" % (got,))
        except TypeError as ex:
            fail("E-call", "core signature not consumable with fixture "
                           "inputs (%s); params=%s" % (ex, list(inspect.signature(core).parameters)))

    # ---- F: budget breach is a NAMED signal, never an auto-trim.
    with tempfile.TemporaryDirectory(prefix="fsrev-f-") as tmp:
        _, members = real_members()
        names = [e[0] for e in members]
        sld = os.path.join(tmp, "scen-ledger")
        os.makedirs(sld, exist_ok=True)
        write_jsonl(os.path.join(sld, "scenario-results.jsonl"),
                    [scen_row(n, 600.0) for n in names])
        rc, out = run_face(["--print-fast-set-review"], {}, tmp)
        if "breach" not in out.lower() and "over budget" not in out.lower():
            fail("F-signal", "measured wall clock over the declared budget "
                             "produced no named signal")
        kept = sum(1 for n in names if ("member %s " % n) in out)
        if kept != len(names):
            fail("F-trim", "set was auto-trimmed under breach: %d/%d members "
                           "still listed (a breach is a signal, never a trim)"
                           % (kept, len(names)))

    # ---- G: the declaration comment carries the cadence and the four
    # event triggers (source-text contract; wording judged by stable tokens).
    with open(RS, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"cadence[^\n]*(\d+)", src, re.IGNORECASE)
    if not m:
        fail("G-cadence", "declaration comment states no periodic cadence "
                          "interval")
    else:
        days = int(m.group(1))
        if days < 1:
            fail("G-cadence", "declared cadence %r not a positive interval"
                 % m.group(0))
        with tempfile.TemporaryDirectory(prefix="fsrev-g-") as tmp:
            _, out = run_face(["--print-fast-set-review"], {}, tmp)
            if str(days) not in out:
                fail("G-printed", "face prints cadence value that is not the "
                                  "declared %d" % days)
    for token, tag in (("MISS", "G-trigger-miss"),
                       ("red inside", "G-trigger-red"),
                       ("auto-trim", "G-trigger-budget"),
                       ("membership", "G-trigger-guards")):
        if token not in src:
            fail(tag, "declaration comment missing trigger token %r" % token)

    # ---- H: ONE face — refused to combine with the runnable entry, by name.
    with tempfile.TemporaryDirectory(prefix="fsrev-h-") as tmp:
        rc, out = run_face(["--print-fast-set-review", "--fast-set"], {}, tmp)
        if rc != 2:
            fail("H-exit", "review face + --fast-set must refuse exit 2, "
                           "got %d" % rc)
        if "REFUSED" not in out:
            fail("H-name", "the refusal does not carry the REFUSED [__fast_"
                           "set__] contract prefix")

    if FAILS:
        print("SUMMARY ran=%d pass=0 fail=%d (t261011-11 patrol face; "
              "pre-implement red on missing capabilities is the TDD signal)"
              % (len(FAILS), len(FAILS)), flush=True)
        return 1
    print("SUMMARY ran=8 pass=8 fail=0 (t261011-11: patrol face + verdict "
          "ledger judged A..H)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
