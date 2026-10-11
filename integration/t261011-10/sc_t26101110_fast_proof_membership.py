#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101110_fast_proof_membership.py — t261011-10: the lane's proof is its
own scenarios plus the DECLARED fast set, and the membership is on the receipt.

Grey-box L3, the real run_scenarios.py declaration face (one-inventory read in
a fresh subprocess) plus the real server/engine modules driven offline over
fixture meta, offline seconds, zero docker/Temporal/browser, never touches
3099/7233.

intent (user-perceivable behaviour; truth source = ticket t261011-10 required
outcomes 1/2/3 + design docs/design/develop-buffer-v1.md goals 3/4/5/12/13):
    A. UNION FACE — for a develop-buffer ticket behind the declared patch id,
       the gate-round proof set is exactly own scenarios UNION the fast-set
       members read from the ONE declared CLI face in this worktree: no
       hand-kept second list can shrink or grow it (a member the declaration
       does not carry must never appear; a declaration member must never be
       silently dropped).
    B. RECEIPT FACE — the round's receipt carries the proof membership, the
       declared budget, and the round's wall clock, so the operator can SEE
       what the lane proved and how long it took; a budget breach surfaces as
       a NAMED stewardship warning, never an auto-trim of the set and never a
       fabricated green.
    C. FULL SUITE LEAVES THE LANE — the lane version's closing run carries the
       same scoped selection (never an empty-selection full run), and the
       wiring sits behind the declared patch id consulted at every new
       behaviour site (KI-061 replay discipline: an in-flight history replays
       the byte-identical old path); the legacy version's closing behaviour is
       untouched.

Intent split (anti-duplication):
  · the CLI declaration/refusal faces themselves belong to t261009-16
    (fast-set-declaration / fast-set-gate) — this entry CONSUMES that face and
    pins the lane's use of it, not the face;
  · the pure decision truth table (refused → own-only, both-empty → named
    failure) belongs to sc_t26101110_proof_degradation_named (same ticket);
  · the parser's malformed-input matrix and the spawn fault-mode table belong
    to developer L1.

Pre-implement red is the expected TDD signal; green required at the
integration gate/merge. server/engine modules unimportable = ENV_FAIL exit 2.
"""
import importlib.util
import json
import os
import subprocess
import sys

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


def declared_fast_set():
    """Members + budget from the ONE declared CLI face, fresh process."""
    p = subprocess.run(
        [sys.executable, "-B", RUNNER, "--print-fast-set"],
        capture_output=True, text=True, timeout=120, cwd=REPO)
    if p.returncode != 0:
        return None, (p.stderr or p.stdout or "")[-400:]
    lines = (p.stdout or "").splitlines()
    header = next((l for l in lines if l.startswith("FAST_SET_DECLARATION")), None)
    if header is None:
        return None, "no FAST_SET_DECLARATION header in output"
    members = [l.strip().split()[1] for l in lines
               if l.strip().startswith("member ")]
    budget = int(header.split("budget_min=")[1].split()[0])
    return {"members": members, "budget_min": budget}, ""


def field(obj, *names, **kw):
    """Read a field from a dict-or-object result without binding to the
    container kind (grey-box: the plan's declared payload keys, either shape)."""
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


def main():
    if not os.path.exists(RUNNER):
        print("ENV_FAIL: integration/run_scenarios.py missing: %s" % RUNNER)
        return 2
    for need in ("dev_lane.py", "develop_line.py"):
        if not os.path.exists(os.path.join(ENGINE, need)):
            print("ENV_FAIL: server/engine/%s missing" % need)
            return 2
    try:
        dev_lane = load_module("t26101110_dev_lane", os.path.join(ENGINE, "dev_lane.py"))
        develop_line = load_module("t26101110_develop_line",
                                   os.path.join(ENGINE, "develop_line.py"))
    except Exception as e:
        print("ENV_FAIL: engine modules unimportable: %r" % (e,))
        return 2

    with open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8") as fh:
        src_text = fh.read()

    # Declared seams this ticket must land (absent = named TDD red, not crash).
    patch_id = getattr(dev_lane, "DEV_BUFFER_FAST_PROOF_PATCH_ID", None)
    check("A declared patch id exists", isinstance(patch_id, str) and bool(patch_id),
          "not landed (TDD red expected): DEV_BUFFER_FAST_PROOF_PATCH_ID absent")
    parse = getattr(develop_line, "parse_fast_set_declaration", None)
    check("A declaration parser seam exists", callable(parse),
          "not landed (TDD red expected): develop_line.parse_fast_set_declaration absent")

    decl, d_err = declared_fast_set()
    if decl is None:
        print("ENV_FAIL: declaration face unreadable on this tree: %s" % d_err)
        return 2
    real_members = decl["members"]
    budget_min = decl["budget_min"]

    if callable(parse) and patch_id:
        try:
            parsed = parse((subprocess.run(
                [sys.executable, "-B", RUNNER, "--print-fast-set"],
                capture_output=True, text=True, timeout=120, cwd=REPO).stdout))
            p_members = list(field(parsed, "members", default=[]))
            check("A parser reads the same declared inventory",
                  sorted(p_members) == sorted(real_members) and p_members,
                  "parser members != CLI face members")
            check("A parser carries the declared budget",
                  field(parsed, "budget_min", default=None) == budget_min,
                  "budget drifted from the declaration face")
        except Exception as e:
            check("A parser reads the same declared inventory", False,
                  "parser raised on the real declaration output: %r" % (e,))

    plan_fn = getattr(dev_lane, "fast_proof_plan", None)
    check("A lane proof-plan seam exists", callable(plan_fn),
          "not landed (TDD red expected): dev_lane.fast_proof_plan absent")

    if callable(plan_fn):
        own = ["t261011-10-scenario-own-face-fixture"]
        try:
            fast_result = {"members": list(real_members),
                           "budget_min": budget_min, "refusals": [], "error": None}
            plan = plan_fn(own, fast_result)
            run_set = list(field(plan, "names", "run_names", "run_only",
                                 "only_names", "members", default=[]))
            check("A proof set is own UNION declared fast members",
                  sorted(run_set) == sorted(set(own) | set(real_members)),
                  "run set %r != own ∪ declared (%d members)" % (run_set[:5], len(real_members)))
            check("A no duplicate / no foreign member",
                  len(run_set) == len(set(run_set)),
                  "duplicates in the run set: a second list is leaking in")
            # B: the plan payload carries the receipt face (membership visible).
            proof = field(plan, "proof", "receipt", "fast_set_proof", default=None)
            payload = proof if proof is not None else plan
            got_members = (list(field(payload, "members", "fast_members", default=[]))
                           or run_set)
            check("B receipt carries the member list",
                  sorted(got_members) == sorted(real_members),
                  "receipt membership not the declared set")
            check("B receipt carries the declared budget",
                  field(payload, "budget_min", "budget", default=None) == budget_min,
                  "declared budget not surfaced per round")
            # B: breach is a NAMED stewardship signal, never an auto-trim.
            breach_flag = field(payload, "breach", "budget_breach", default=None)
            breach_fn = getattr(dev_lane, "fast_budget_verdict", None)
            if breach_flag is None and callable(breach_fn):
                breach_flag = breach_fn(budget_min * 60 + 1, budget_min)
            check("B breach signal seam exists",
                  breach_flag is not None or callable(breach_fn),
                  "no budget-breach signal seam on the plan/receipt (outcome 2)")
            if callable(breach_fn):
                over = breach_fn(budget_min * 60 + 1, budget_min)
                check("B over-budget wall clock flags a breach",
                      bool(over[0] if isinstance(over, tuple) else over),
                      "over-budget run not flagged — the stewardship face is dark")
                at = breach_fn(budget_min * 60, budget_min)
                check("B exactly at budget is no breach",
                      not (at[0] if isinstance(at, tuple) else at),
                      "boundary breach: wall == budget flagged as over")
                check("B breach verdict is NAMED text",
                      isinstance(over, tuple) and "budget" in str(over[1]).lower(),
                      "breach flag carries no named stewardship line")
            # The breach NAMED line lives on the round receipt (meta
            # fast_set_proof), not on the pure plan: anchor the receipt wiring.
            check("B round receipt wires the breach verdict",
                  '"fast_set_proof"' in src_text and "fast_budget_verdict" in src_text,
                  "receipt face or budget verdict not wired into the round")
        except Exception as e:
            check("A proof set is own UNION declared fast members", False,
                  "plan seam raised on the happy shape: %r" % (e,))

    # C: the wiring is patch-gated at every new behaviour site, and the lane's
    # closing run carries the scoped face (source-shape face, t261009-20
    # precedent), while the legacy closing behaviour stays byte-untouched.
    try:
        with open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8") as fh:
            src = fh.read()
        if patch_id:
            check("C patch id literal is unique in the engine",
                  src.count('"%s"' % patch_id) == 1,
                  "patch-id reuse corrupts the boolean-gate family (KI-061)")
            check("C new behaviour consults the patch gate",
                  "workflow.patched" in src and patch_id in src,
                  "wiring present but not behind the declared patch id")
        closing_fn = getattr(dev_lane, "is_develop_buffer_ticket", None)
        check("C legacy version gate predicate intact", callable(closing_fn)
              and not closing_fn({"ticket_type": "chore"}),
              "version gate predicate missing or misfires on a legacy meta")
        check("C legacy closing full-run face untouched",
              "_closing_full_run" in src,
              "closing run face renamed/removed — legacy replay would diverge")
    except Exception as e:
        check("C patch id literal is unique in the engine", False,
              "source face unread: %r" % (e,))

    print("CHECKS %d / FAILURES %d" % (CHECKS[0], len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
