#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_fast_set_declaration.py — t261009-16 fast global set: the declaration face.

Grey-box L3, real `integration/run_scenarios.py` CLI subprocess on the real tree,
offline seconds, zero docker/Temporal/browser, never touches 3099.

intent (user-perceivable behaviour; truth source = ticket t261009-16 user_request
"members, a time budget, a runnable entry, measured evidence" + design
docs/design/develop-buffer-v1.md §"The lane's fast global set"):
    A. A lane can see the set without running it: `--print-fast-set` exits 0 and
       prints a NON-EMPTY member list whose every name exists exactly once in the
       SAME declared inventory that feeds the full suite (never a second
       hand-kept list — read the full registry in a fresh process and diff).
    B. Every member says what breakage it catches early: each printed member
       carries a `fast-catch:` clause; a member without one has stopped doing
       its job and must be visible here.
    C. The budget is declared, in minutes, honestly: a budget line with a number
       of minutes is present, and the note names the serial/pole accounting
       (serial members sum, parallel pools by the slowest pole) — the serial
       honesty the ticket demands.
    D. Measured evidence per member: each member shows a measured cost, and with
       an EMPTY scenario ledger (SANDBAR_SCENARIO_LEDGER_DIR pointed at a fresh
       temp dir) the face still exits 0 and names the no-measured-cost condition
       per member — it never fabricates a 0s cost for a row it does not have.
    E. Membership rules hold on the real tree: no member is in the booked-red
       roster (integration/known-red-baseline.json), and no member comes from
       the browser pool (the round's serial 19.6-minute pole — exactly what the
       set must not import).

Intent split (anti-duplication):
  · the refusal/fail-closed faces (booked-red member injected, malformed roster,
    mutual exclusion, marker integrity) belong to t261009-16-fast-set-gate
    (same ticket, different face);
  · the pure-function marker/budget arithmetic matrix belongs to developer L1;
  · full-suite execution faces belong to the existing runner scenarios, not here.

Pre-implement red is the expected TDD signal; arbitrate/merge must be green.
python missing / run_scenarios.py absent = ENV_FAIL exit 2.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.join(REPO, "integration", "run_scenarios.py")
ROSTER = os.path.join(REPO, "integration", "known-red-baseline.json")

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    print(("PASS" if cond else "FAIL") + " " + name + ((" — " + detail) if (detail and not cond) else ""), flush=True)
    if not cond:
        FAILURES.append(name)


def run_runner(args, extra_env=None):
    """Bounded subprocess: a read-only declaration face that hangs past 120s is
    itself a named FAIL (never an unbounded gate hang)."""
    import subprocess as _sp
    env = dict(os.environ)
    # 261022: `--print-fast-set` is a READ-ONLY declaration face. Inside a full
    # round the runner's own run lock is held, so the face answered with the
    # concurrency refusal and this case went red at 0.3 s in every round while it
    # was green standalone. A read-only read must not be judged by the lock of the
    # round it runs in; the documented knob is what the runner itself points at.
    env["SANDBAR_INTEG_ALLOW_CONCURRENT"] = "1"
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


def full_inventory_names():
    """The full suite's inventory, read in a FRESH process — the same registry
    the full round runs from; the fast set must be a subset of exactly this."""
    code = ("import json,sys; sys.path.insert(0,%r);"
            "import run_scenarios as rs;"
            "print(json.dumps([e[0] for e in rs.SCENARIOS]))" % (os.path.join(REPO, "integration"),))
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                       text=True, timeout=120, cwd=REPO)
    if p.returncode != 0:
        return None, (p.stderr or "")[-400:]
    return json.loads(p.stdout.strip().splitlines()[-1]), ""


def booked_red_names():
    try:
        with open(ROSTER, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    names = []
    for ent in payload.get("entries", []):
        if isinstance(ent, dict) and ent.get("name"):
            names.append(ent["name"])
    return names, ""


_TMP = None
if not os.path.exists(RUNNER):
    print("ENV_FAIL: integration/run_scenarios.py missing: %s" % RUNNER)
    sys.exit(2)

try:
    _TMP = tempfile.mkdtemp(prefix="t26100916-decl-")

    # ---- A+B+C+E: the declaration face on the real tree ----
    p = run_runner(["--print-fast-set"])
    out = p.stdout or ""
    if "ENV_FAIL" in (p.stderr or "") + (p.stdout or ""):
        print("ENV_FAIL: --print-fast-set refused on an environment face: %s"
              % ((p.stderr or p.stdout or "")[-300:],))
        sys.exit(2)
    check("A print-fast-set exits 0", p.returncode == 0,
          "rc=%d tail=%s" % (p.returncode, (p.stderr or out)[-300:]))
    check("A member list non-empty", "fast" in out.lower() and len(out.strip()) > 0,
          "empty declaration output")

    inv, inv_err = full_inventory_names()
    if inv is None:
        print("ENV_FAIL: full inventory unreadable: %s" % inv_err)
        sys.exit(2)

    # Members are parsed from the declaration output: lines that carry a
    # fast-catch clause name their member; a member line without the clause is
    # itself the B defect. Every plausible member name token must be in inventory.
    # A member LINE is the declaration's own shape ("  member <name> pool=… ");
    # 261022: the old heuristic also matched the runner's named report lines
    # (FAST_SET_UNMEASURED lists members with no measured cost when the round's
    # ledger is fresh) and read a lawful report as a member missing its clause —
    # green on a machine with a warm ledger, red in every round.
    member_lines = [ln for ln in out.splitlines()
                    if ln.strip().startswith("member ")]
    decl_lines = [ln for ln in member_lines if "fast-catch:" in ln]
    check("B every member line carries fast-catch:", len(decl_lines) > 0,
          "no fast-catch clause anywhere — members do not say what they catch")
    missing_clause = [ln for ln in member_lines if "fast-catch:" not in ln]
    check("B no member-shaped line without a fast-catch clause",
          len(missing_clause) == 0,
          "member lines without clause: %s" % missing_clause[:3])

    member_names = []
    for ln in decl_lines:
        m = re.findall(r"[a-z0-9][a-z0-9-]{11,}", ln)
        for tok in m:
            if tok in inv:
                member_names.append(tok)
    member_names = sorted(set(member_names))
    check("A every member exists in the SAME full-suite inventory",
          len(member_names) > 0 and all(n in inv for n in member_names),
          "members not in inventory: %s" % [n for n in member_names if n not in inv])

    # ---- C: declared budget, minutes, serial honesty ----
    budget_lines = [ln for ln in out.splitlines() if re.search(r"budget", ln, re.I)]
    check("C budget declared", any(re.search(r"\d", ln) and
                                   re.search(r"min", ln, re.I) for ln in budget_lines),
          "budget lines: %s" % budget_lines[:3])
    check("C budget note names serial/pole accounting",
          any(re.search(r"serial", ln, re.I) for ln in out.splitlines()),
          "no line names the serial/serial-pole accounting")

    # ---- D: measured cost, honest when the ledger has nothing ----
    empty_ledger = os.path.join(_TMP, "empty-ledger")
    os.makedirs(empty_ledger, exist_ok=True)
    p2 = run_runner(["--print-fast-set"],
                    {"SANDBAR_SCENARIO_LEDGER_DIR": empty_ledger})
    out2 = p2.stdout or ""
    env_red2 = "ENV_FAIL" in (p2.stderr or "") + (p2.stdout or "")
    if env_red2:
        print("ENV_FAIL: print face refused under empty ledger: %s"
              % ((p2.stderr or out2)[-300:],))
        sys.exit(2)
    check("D print face exits 0 with an empty ledger", p2.returncode == 0,
          "rc=%d tail=%s" % (p2.returncode, (p2.stderr or out2)[-300:]))
    no_cost_named = re.search(r"no (measured )?cost|no ledger|no row|unmeasured|no measured",
                              out2, re.I)
    check("D empty ledger names the no-measured-cost condition", bool(no_cost_named),
          "no named no-cost face in output; head=%s" % out2[:300])
    fabricated = [ln for ln in out2.splitlines()
                  if re.search(r"0\.0+\s*s\b", ln) and "no measured" not in ln.lower()]
    check("D empty ledger never fabricates a 0s measured cost", len(fabricated) == 0,
          "0.0s cost lines present without a no-cost naming: %s" % fabricated[:3])

    # ---- E: membership rules on the real tree ----
    reds, red_err = booked_red_names()
    if reds is None:
        print("ENV_FAIL: booked-red roster unreadable: %s" % red_err)
        sys.exit(2)
    check("E no member is in the booked-red roster",
          not (set(member_names) & set(reds)),
          "overlap: %s" % sorted(set(member_names) & set(reds)))
    # 池判定必须"取 token 再比较"，不能用子串：`\bbrowser\b` 会命中
    # `pool=browser-free`（连字符是词边界），把一个**便宜的另一池**误判成
    # 那根 19.6 分钟串行杆。261011 实测：本集合新增两条 browser-free 成员
    # （lane-map 值绑定面、capture preset 面）当场被误报为违规。
    def _pool_token(line: str) -> str:
        m = re.search(r"pool=([A-Za-z0-9_-]+)", line)
        return (m.group(1) if m else "").lower()
    browser_members = [ln for ln in out.splitlines()
                       if "fast-catch:" in ln and _pool_token(ln) == "browser"]
    check("E no browser-pool member (exact pool token; browser-free is a different, cheap pool)",
          len(browser_members) == 0,
          "browser members: %s" % browser_members[:3])

finally:
    if _TMP and os.path.isdir(_TMP):
        shutil.rmtree(_TMP, ignore_errors=True)

print("SUMMARY checks=%d fail=%d" % (CHECKS[0], len(FAILURES)))
# 261022: the runner keeps only the tail of a case's stdout, so a red used to
# arrive with its failing check truncated away. This line always survives.
if FAILURES:
    print("FAILED_CHECKS %r" % (FAILURES,))
sys.exit(1 if FAILURES else 0)
