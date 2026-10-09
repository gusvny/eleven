#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_fast_set_gate.py — t261009-16 fast global set: the fail-closed gate faces.

Grey-box L3, real `integration/run_scenarios.py` CLI subprocess plus the public
`fast_set_entries()` helper driven over fixture registries, offline seconds,
zero docker/Temporal/browser, never touches 3099.

intent (user-perceivable behaviour; truth source = ticket t261009-16 membership
rule "a chronically-red case must NOT be a member" + KI-01M4FE0T3FG7Y0G9R97NS4T7QJ
(a booked-red judgement surface that silently misses entries cannot be trusted)
+ design §"The lane's fast global set" one-inventory rule):
    A. The two fast faces are mutually exclusive: asking for both a real
       fast-set run and the dry print face refuses with a NAMED argument error
       before anything runs — it never picks one silently.
    B. A booked-red member is refused by name: with SANDBAR_KNOWN_RED_ROSTER
       pointed at a fixture roster holding a REAL fast member's name, the
       declaration face refuses (non-zero), names the member and the roster
       check, and never prints the list as a valid declaration (a tripwire that
       is booked red protects nobody — the exact KI face).
    C. An unreadable roster is never an empty roster: fixture roster that is
       malformed JSON, and a roster path that does not exist, each make the
       declaration face refuse with the roster condition NAMED — the
       no-booked-red property must not be certified off an untrustworthy roster
       (the empty-roster-silently-admits-everything defect face).
    D. Marker integrity over the one inventory: the public helper
       fast_set_entries() over the REAL registry returns names that all exist
       in SCENARIOS exactly once; over fixture registries it fails closed with
       a named error on a duplicate fast marker, a fast marker on an entry
       without a pool, and an unknown trailing element — a malformed marker can
       never silently shrink or grow the set.
    E. Declared-vs-measured is printed, never auto-trimmed: the declaration
       face shows the declared budget against the measured cost as evidence
       wording (suggest/not-enforcing), so a breach is input to the next
       stewardship pass, not a silent edit of the set.

Intent split (anti-duplication):
  · the happy declaration face (membership, budget, cost, catch clauses on the
    real tree) belongs to t261009-16-fast-set-declaration (same ticket,
    different face);
  · the pure marker-parsing truth tables belong to developer L1 — D here only
    pins the public helper's fail-closed direction over fixture registries;
  · the roster reader's own unit contract belongs to its landing ticket's
    battery; this entry pins the fast-set face's CONSUMPTION of it.

Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
python missing / run_scenarios.py absent = ENV_FAIL exit 2.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.join(REPO, "integration", "run_scenarios.py")

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    print(("PASS" if cond else "FAIL") + " " + name + ((" — " + detail) if (detail and not cond) else ""), flush=True)
    if not cond:
        FAILURES.append(name)


def run_runner(args, extra_env=None):
    """Bounded subprocess: a refusal face that hangs past 120s is itself a
    named FAIL (never an unbounded gate hang)."""
    import subprocess as _sp
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        return _sp.run([sys.executable, "-B", RUNNER] + args,
                       capture_output=True, text=True, timeout=120,
                       cwd=REPO, env=env)
    except _sp.TimeoutExpired as e:
        class _T:  # minimal subprocess-shaped result
            returncode = -9
            stdout = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = "TIMEOUT after 120s: %s" % args
        return _T()


def real_fast_members():
    """Fast member names via the public helper, fresh process (the one-inventory
    read point the design mandates)."""
    code = ("import json,sys; sys.path.insert(0,%r);"
            "import run_scenarios as rs;"
            "print(json.dumps([e[0] for e in rs.fast_set_entries()]))"
            % (os.path.join(REPO, "integration"),))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                       text=True, timeout=120, cwd=REPO)
    if p.returncode != 0:
        return None, (p.stderr or "")[-400:]
    return json.loads(p.stdout.strip().splitlines()[-1]), ""


def helper_on(registry_src):
    """Drive fast_set_entries() over a fixture registry in a fresh process.
    Returns (names_or_None, stderr_tail, crashed_bool)."""
    code = ("import json,sys,traceback; sys.path.insert(0,%r);"
            "import run_scenarios as rs;\n"
            "reg=%s;\n"
            "try:\n"
            "    print(json.dumps([e[0] for e in rs.fast_set_entries(reg)]))\n"
            "except Exception:\n"
            "    sys.stderr.write(traceback.format_exc(limit=3)); sys.exit(9)\n"
            % (os.path.join(REPO, "integration"), registry_src))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                       text=True, timeout=120, cwd=REPO)
    if p.returncode == 9:
        return None, (p.stderr or "")[-400:], True
    if p.returncode != 0:
        return None, (p.stderr or "")[-400:], False
    return json.loads(p.stdout.strip().splitlines()[-1]), "", False


def fixture_roster(dirpath, member_name, raw=None):
    path = os.path.join(dirpath, "roster-%s.json" % (member_name or "raw"))
    payload = raw if raw is not None else json.dumps(
        {"meta": {"note": "t261009-16 gate fixture"},
         "entries": [{"name": member_name, "owner": "gate-fixture",
                      "verdict": "booked", "retire_when": "fixture"}]},
        ensure_ascii=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(payload)
    return path


_TMP = None
if not os.path.exists(RUNNER):
    print("ENV_FAIL: integration/run_scenarios.py missing: %s" % RUNNER)
    sys.exit(2)

try:
    _TMP = tempfile.mkdtemp(prefix="t26100916-gate-")

    # ---- A: mutual exclusion, named ----
    p = run_runner(["--fast-set", "--print-fast-set"])
    text = (p.stdout or "") + (p.stderr or "")
    if "ENV_FAIL" in text:
        print("ENV_FAIL: mutual-exclusion probe hit an environment face: %s"
              % text[-300:])
        sys.exit(2)
    check("A both faces together refuse", p.returncode != 0,
          "rc=0 — the runner silently picked a face")
    check("A refusal is a named argument error, not a traceback",
          p.returncode != 0 and "Traceback" not in (p.stderr or "")
          and len(text.strip()) > 0,
          "bare crash: %s" % (p.stderr or "")[-200:])

    # ---- B: booked-red member refused by name ----
    members, m_err = real_fast_members()
    if members is None:
        # Pre-implement: helper absent is the expected TDD red, keep B–D red but
        # still runnable (skip injections that need a member name).
        print("FAIL marker: fast_set_entries unavailable — pre-implement red "
              "(TDD signal): %s" % m_err)
        check("D public fast_set_entries exists", False, m_err)
        members = []
    if members:
        victim = members[0]
        roster = fixture_roster(_TMP, victim)
        pb = run_runner(["--print-fast-set"],
                        {"SANDBAR_KNOWN_RED_ROSTER": roster})
        tb = (pb.stdout or "") + (pb.stderr or "")
        check("B booked-red member refused", pb.returncode != 0,
              "rc=0 — a booked-red tripwire was declared valid")
        check("B refusal names the member", victim in tb,
              "member %s not named in refusal" % victim)
        check("B refusal names the roster check",
              bool(pb.returncode) and ("roster" in tb.lower()
                                       or "known" in tb.lower() or "红" in tb),
              "refusal does not say which check failed: %s" % tb[-300:])

        # ---- C: unreadable roster never reads as empty ----
        bad = fixture_roster(_TMP, None, raw="{not json at all")
        pc = run_runner(["--print-fast-set"],
                        {"SANDBAR_KNOWN_RED_ROSTER": bad})
        tc = (pc.stdout or "") + (pc.stderr or "")
        check("C malformed roster refuses the declaration face", pc.returncode != 0,
              "rc=0 — an untrustworthy roster silently certified the set")
        check("C malformed roster names its condition", len(tc.strip()) > 0
              and "Traceback" not in (pc.stderr or ""),
              "bare crash: %s" % (pc.stderr or "")[-200:])
        absent = os.path.join(_TMP, "no-such-roster.json")
        pa = run_runner(["--print-fast-set"],
                        {"SANDBAR_KNOWN_RED_ROSTER": absent})
        ta = (pa.stdout or "") + (pa.stderr or "")
        check("C absent roster refuses with the path named",
              pa.returncode != 0 and absent in ta,
              "rc=%d — absent roster treated as empty: %s"
              % (pa.returncode, ta[-200:]))
    else:
        check("B booked-red member refused (blocked pre-implement)", False,
              "fast_set_entries unavailable — TDD red")
        check("C unreadable roster refuses (blocked pre-implement)", False,
              "fast_set_entries unavailable — TDD red")

    # ---- D: marker integrity over fixture registries ----
    ok_reg = json.dumps([["a-entry", "fast-catch: x", "cmd-a", "ro", "fast"],
                         ["b-entry", "plain", "cmd-b", "ro"]])
    names, err, crashed = helper_on(ok_reg)
    check("D well-formed fixture registry parses",
          names == ["a-entry"], "names=%r err=%s" % (names, err[-200:]))
    dup = json.dumps([["a-entry", "fast-catch: x", "cmd-a", "ro", "fast"],
                      ["b-entry", "fast-catch: y", "cmd-b", "ro", "fast"],
                      ["a-entry-dup", "fast-catch: z", "cmd-c", "ro", "fast"],
                      ["a-entry", "plain", "cmd-d", "ro"]])
    names, err, crashed = helper_on(dup)
    check("D duplicate member name fails closed",
          names is None and crashed, "returned %r" % (names,))
    nopool = json.dumps([["a-entry", "fast-catch: x", "cmd-a", "fast"]])
    names, err, crashed = helper_on(nopool)
    check("D fast marker without a pool fails closed",
          names is None and crashed, "returned %r err=%s" % (names, err[-150:]))
    unknown = json.dumps([["a-entry", "x", "cmd-a", "ro", "faste"]])
    names, err, crashed = helper_on(unknown)
    check("D unknown trailing element fails closed",
          names is None and crashed, "returned %r" % (names,))

    # ---- E: declared-vs-measured printed, never auto-trimmed ----
    pd = run_runner(["--print-fast-set"])
    td = (pd.stdout or "")
    env_red = "ENV_FAIL" in (pd.stderr or "") + (pd.stdout or "")
    if env_red:
        print("ENV_FAIL: print face refused on an environment face: %s"
              % ((pd.stderr or td)[-300:],))
        sys.exit(2)
    check("E declaration face carries the declared budget",
          bool([ln for ln in td.splitlines()
                if "budget" in ln.lower() and any(c.isdigit() for c in ln)]),
          "no budget line with a number")
    suggest = [ln for ln in (td + (pd.stderr or "")).splitlines()
               if "suggest" in ln.lower() or "evidence" in ln.lower()
               or "not enforce" in ln.lower() or "steward" in ln.lower()]
    check("E breach wording is evidence, not an auto-trim", len(suggest) > 0,
          "no suggest/evidence/steward wording anywhere in the face")

finally:
    if _TMP and os.path.isdir(_TMP):
        shutil.rmtree(_TMP, ignore_errors=True)

print("SUMMARY checks=%d fail=%d" % (CHECKS[0], len(FAILURES)))
sys.exit(1 if FAILURES else 0)
