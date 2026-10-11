#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101110_proof_degradation_named.py — t261011-10: every degraded lane
proof is NAMED, and the full suite never re-enters the lane path.

Grey-box L3, the real run_scenarios.py CLI face driven into each refusal/
degradation shape plus the real server/engine decision seam over fixture
shapes, offline seconds, zero docker/Temporal/browser, never touches
3099/7233.

intent (user-perceivable behaviour; truth source = ticket t261011-10 required
outcome 3 + review_plan gen0 [R1] ruling + KI-220 (an empty/zero run must
never be read ambiguously) + KI-055 lesson (a quiet surface reads green)):
    A. DECLARATION REFUSED — when the declared face refuses (here: a booked-red
       roster fixture over a REAL member, the t261009-16-proven refusal), the
       lane still proves its OWN scenarios and says BY NAME that the fast set
       is absent this round — never a silent shrink to own-only, never a
       refusal read as an empty legitimate set.
    B. OWN FACE ABSENT — when the ticket's own-scenario face is unresolvable,
       the lane still proves the fast set and says so by name — never a quiet
       fast-only round that the reader mistakes for a full proof.
    C. BOTH SOURCES ABSENT — the round is REFUSED BY NAME before any run: no
       run executes, the full suite is NEVER paid on the lane (the gen0 [R1]
       ruling), and the message names both absent sources so the next reader
       can act instead of debugging a 15-minute red.
    D. LEGACY UNTOUCHED — none of these outcomes exist for a legacy-version
       ticket: the decision seam is unreachable for a meta the version gate
       does not opt in (design goals 12/13: the new proof belongs to the
       tickets that opt in).

Intent split (anti-duplication):
  · the refusal faces of the CLI itself belong to t261009-16-fast-set-gate;
    A here only pins the lane's CONSUMPTION of a refused declaration;
  · the happy union/receipt face belongs to sc_t26101110_fast_proof_membership;
  · the pure truth-table internals belong to developer L1.

Pre-implement red is the expected TDD signal; green required at the
integration gate/merge. server/engine modules unimportable = ENV_FAIL exit 2.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.join(REPO, "integration", "run_scenarios.py")
ENGINE = os.path.join(REPO, "server", "engine")

FAILURES = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    print(("PASS" if cond else "FAIL") + " " + name +
          ((" — " + detail) if (detail and not cond) else ""), flush=True)
    if not cond:
        FAILURES.append(name)


def load_module(name, path):
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)  # dev_lane imports sibling engine modules (base, shared)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass string annotations resolve via sys.modules
    spec.loader.exec_module(mod)
    return mod


def field(obj, *names, **kw):
    default = kw.get("default")
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        else:
            v = getattr(obj, n, None)
            if v is not None:
                return v
    return default


def real_fast_member():
    p = subprocess.run([sys.executable, "-B", RUNNER, "--print-fast-set"],
                       capture_output=True, text=True, timeout=120, cwd=REPO)
    if p.returncode != 0:
        return None, (p.stderr or "")[-300:]
    for line in (p.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("member "):
            return s.split()[1], ""
    return None, "no member line in declaration output"


def refused_declaration():
    """Drive the real face into its booked-red refusal (t261009-16 gate face
    B, reused as the degradation driver)."""
    member, err = real_fast_member()
    if member is None:
        return None, err
    with tempfile.TemporaryDirectory(prefix="t26101110-degrade-") as tmp:
        roster = os.path.join(tmp, "roster.json")
        with open(roster, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"note": "t261011-10 degradation fixture"},
                       "entries": [{"name": member, "owner": "degrade-fixture",
                                    "verdict": "booked", "retire_when": "fixture"}]}, fh)
        env = dict(os.environ)
        env["SANDBAR_KNOWN_RED_ROSTER"] = roster
        p = subprocess.run([sys.executable, "-B", RUNNER, "--print-fast-set"],
                           capture_output=True, text=True, timeout=120, cwd=REPO, env=env)
    text = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        return None, "declaration face did NOT refuse under a booked-red roster"
    if "REFUSED" not in text and "refus" not in text.lower():
        return None, "refusal is not a named REFUSED face: %s" % text[-200:]
    return {"members": [], "budget_min": None, "refusals": [text.strip()[-300:]],
            "error": "refused"}, ""


def main():
    if not os.path.exists(RUNNER):
        print("ENV_FAIL: integration/run_scenarios.py missing: %s" % RUNNER)
        return 2
    for need in ("dev_lane.py", "develop_line.py"):
        if not os.path.exists(os.path.join(ENGINE, need)):
            print("ENV_FAIL: server/engine/%s missing" % need)
            return 2
    try:
        dev_lane = load_module("t26101110b_dev_lane", os.path.join(ENGINE, "dev_lane.py"))
    except Exception as e:
        print("ENV_FAIL: engine modules unimportable: %r" % (e,))
        return 2

    plan_fn = getattr(dev_lane, "fast_proof_plan", None)
    gate = getattr(dev_lane, "is_develop_buffer_ticket", None)
    check("decision seam exists", callable(plan_fn),
          "not landed (TDD red expected): dev_lane.fast_proof_plan absent")
    check("version gate predicate exists", callable(gate),
          "is_develop_buffer_ticket missing")

    refused, r_err = refused_declaration()
    if refused is None:
        print("ENV_FAIL: could not drive the declaration face into a named "
              "refusal on this tree: %s" % r_err)
        return 2

    own = ["t261011-10-scenario-own-face-fixture"]

    if callable(plan_fn):
        # A: refused declaration -> own-only + NAMED warning.
        try:
            plan = plan_fn(own, refused)
            run_set = list(field(plan, "names", "run_names", "run_only",
                                 "only_names", "members", default=[]))
            check("A refused declaration proves own scenarios only",
                  sorted(run_set) == sorted(own),
                  "run set %r != own-only (a refusal must never read as an "
                  "empty legitimate fast set)" % run_set)
            text = json.dumps(plan, default=str) if not isinstance(plan, str) else plan
            check("A fast-set absence is NAMED on the round",
                  ("refus" in text.lower()) or ("fast" in text.lower()),
                  "own-only round carries no named fast-set-absent warning")
            check("A no full-suite flag on the degraded round",
                  not field(plan, "full", "full_suite", "run_full", default=False),
                  "degraded round quietly re-opens the full suite")
        except Exception as e:
            check("A refused declaration proves own scenarios only", False,
                  "plan seam raised on the refused shape: %r" % (e,))

        # B: own face absent -> fast-only + NAMED warning.
        try:
            p = subprocess.run([sys.executable, "-B", RUNNER, "--print-fast-set"],
                               capture_output=True, text=True, timeout=120, cwd=REPO)
            members = [l.strip().split()[1] for l in (p.stdout or "").splitlines()
                       if l.strip().startswith("member ")]
            budget = int(next(l for l in p.stdout.splitlines()
                              if l.startswith("FAST_SET_DECLARATION")
                              ).split("budget_min=")[1].split()[0])
            fast_result = {"members": members, "budget_min": budget,
                           "refusals": [], "error": None}
            plan = plan_fn([], fast_result)
            run_set = list(field(plan, "names", "run_names", "run_only",
                                 "only_names", "members", default=[]))
            check("B own-absent round proves the fast set",
                  sorted(run_set) == sorted(members) and bool(run_set),
                  "run set %r != declared fast members" % run_set[:5])
            text = json.dumps(plan, default=str)
            check("B the reduction is NAMED on the round",
                  ("own" in text.lower()),
                  "fast-only round carries no named own-absent warning")
            check("B no full-suite flag on the fast-only round",
                  not field(plan, "full", "full_suite", "run_full", default=False),
                  "fast-only round quietly re-opens the full suite")
        except Exception as e:
            check("B own-absent round proves the fast set", False,
                  "plan seam raised on the own-absent shape: %r" % (e,))

        # C: BOTH absent -> named refusal BEFORE any run; the full suite is
        # never paid on the lane (review_plan gen0 [R1]).
        try:
            plan = plan_fn([], refused)
            run_set = list(field(plan, "names", "run_names", "run_only",
                                 "only_names", "members", default=[]))
            failed = bool(field(plan, "failed", "refused", "blocked_reason",
                                "error", "failure", default=False))
            check("C both-absent round runs NOTHING",
                  (not run_set) and failed,
                  "empty-plan round produced a run set %r or passed silently"
                  % run_set)
            text = json.dumps(plan, default=str)
            check("C the refusal names both absent sources",
                  ("own" in text.lower()) and ("fast" in text.lower() or "refus" in text.lower()),
                  "refusal does not say which source was absent: %s" % text[:200])
            check("C the full suite is never the fallback",
                  not field(plan, "full", "full_suite", "run_full", default=False),
                  "both-absent round fell back to the full suite — the exact "
                  "gen0 [R1] defect face")
        except Exception as e:
            check("C both-absent round runs NOTHING", False,
                  "plan seam raised on the both-absent shape: %r" % (e,))

    # D: legacy meta stays outside the new proof entirely.
    if callable(gate):
        check("D legacy ticket meta is not opted in",
              not gate({"id": "t-legacy", "ticket_type": "chore"}),
              "legacy meta opts into the new proof — goals 12/13 broken")

    print("CHECKS %d / FAILURES %d" % (CHECKS[0], len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
