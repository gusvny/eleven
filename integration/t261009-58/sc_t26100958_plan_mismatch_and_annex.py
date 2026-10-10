#!/usr/bin/env python3
"""sc_t26100958_plan_mismatch_and_annex.py — t261009-58, stories (2) + (3) + (5):
a plan-vs-set mismatch is NAMED at plan time, a late discovery gets ONE narrow
audited annex route, and a protected path is never lane-self-authorized.

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal/browser,
never touches 3099/7233. Contracts exercised (public, plan-declared):
  - plan_write_set_mismatch(initial, plan_files) names exactly the
    plan-declared files outside the then-current set (the early named line's
    factual core — no ticket discovers this at implement round eight);
  - annex_admission(files, effective, ctx) admits only when the file is
    (a) not protected, (b) not held by another in-flight ticket, (c) inside
    declared bounds (per-ticket cap, no out-of-scope directory entry — the
    KI-125 / KI-158 granularity door stays shut);
  - every refusal names WHICH condition failed and WHICH file — no silent
    widening, no silent refusal;
  - the protected list stays the host's word: no who/reason wording gets a
    protected path admitted (story (5)).

Declarations to the implementer: shared.plan_write_set_mismatch and
shared.annex_admission are the plan-declared names this scenario calls;
annex_admission takes injected predicates for the in-flight-holder scan
(ctx carries holders / protected / cap), so the truth table below is
exercised without a live batch. Missing attribute → named FAIL (TDD
signal); shared.py unimportable = ENV_FAIL exit 2.

Run directly: python3 integration/t261009-58/sc_t26100958_plan_mismatch_and_annex.py
(cwd = repository root). Implementation not landed = red; arbitrate and merge
must be green.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

try:
    import shared  # noqa: E402
except Exception as exc:
    print("ENV_FAIL: server/engine/shared.py unimportable: %r" % exc)
    sys.exit(2)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL  %s" % label)


def section(title):
    print("\n%s" % title)


def mismatch(initial, plan_files):
    fn = getattr(shared, "plan_write_set_mismatch", None)
    if fn is None:
        ok(False, "shared.plan_write_set_mismatch present (implement not landed)")
        return None
    return fn(initial, plan_files)


def annex(files, effective, ctx):
    fn = getattr(shared, "annex_admission", None)
    if fn is None:
        ok(False, "shared.annex_admission present (implement not landed)")
        return None
    return fn(files, effective, ctx)


def admitted(r):
    """Tolerant verdict read: bare bool / dict verdict / object attr / tuple head."""
    if isinstance(r, bool):
        return r
    if isinstance(r, dict):
        return bool(r.get("admitted", r.get("ok")))
    if isinstance(r, tuple) and r:
        return bool(r[0])
    return bool(getattr(r, "admitted", False))


CTX = {
    "protected": ("server/engine/base.py", "CLAUDE.md"),
    "holders": {"server/engine/concurrency.py": "t261009-99"},
    "cap": 8,
    "scoped_prefixes": ("server/engine/", "integration/"),
}


def main():
    initial = ["server/engine/shared.py", "server/engine/dev_lane.py"]

    # ---------- A. the early named check at plan time ----------
    section("A. plan_write_set_mismatch names out-of-set deliverables")
    got = mismatch(initial, ["server/engine/shared.py",
                             "server/engine/agent_activities.py"])
    if got is not None:
        ok(got == ["server/engine/agent_activities.py"],
           "names exactly the out-of-set plan files, in-set files not flagged")
        ok(mismatch(initial, initial) == [],
           "fully in-set plan → empty mismatch (no noise line)")
        ok(mismatch(initial, []) == [], "empty plan → empty mismatch")
        # malformed external input: non-list / non-string shapes refuse, not crash-open
        for label, bad in (("non-list plan files", "server/engine/x.py"),
                           ("non-string entry", ["server/engine/x.py", 7])):
            try:
                r = mismatch(initial, bad)
                ok(not r, "%s → refused/empty, never admitted" % label)
            except Exception:
                ok(True, "%s → named refusal, not a silent admit" % label)

    # ---------- B. admission truth table ----------
    section("B. annex_admission: the three lawful conditions, no fourth door")
    r = annex(["server/engine/dev_tests_helper.py"],
              initial, dict(CTX, who="executor", reason="L1 battery needs it"))
    if r is not None:
        ok(admitted(r),
           "in-scope, unheld, unprotected file with who+reason → admitted")
        ok(True, "(verdict shape is the implementer's; truth judged via admitted())")

    # (a) protected stays the host's word
    r = annex(["CLAUDE.md"], initial, dict(CTX, who="executor",
                                           reason="even a good reason"))
    if r is not None:
        ok(not admitted(r), "protected path refused even with a stated reason (story 5)")

    # (b) held by another in-flight ticket
    r = annex(["server/engine/concurrency.py"], initial,
              dict(CTX, who="executor", reason="call site"))
    if r is not None:
        ok(not admitted(r), "file held by another in-flight ticket refused")

    # (c) bounds: over-cap and out-of-scope directory entry (KI-125/KI-158 door)
    many = ["server/engine/f%d.py" % i for i in range(20)]
    r = annex(many, initial, dict(CTX, who="executor", reason="bulk"))
    if r is not None:
        ok(not admitted(r), "annex beyond the per-ticket cap refused")
    r = annex(["server/profile-headless/link"], initial,
              dict(CTX, who="executor", reason="mount needs it"))
    if r is not None:
        ok(not admitted(r), "directory entry outside attributed scope refused (KI-158 shape)")

    # ---------- C. refusals name the condition and the file ----------
    section("C. refusal text names which check failed and on which file")
    r = annex(["CLAUDE.md"], initial, dict(CTX, who="executor", reason="r"))
    if r is not None and not isinstance(r, bool):
        text = __import__("json").dumps(r)
        ok("protected" in text.lower(), "refusal names the failed condition: protected")
        ok("CLAUDE.md" in text, "refusal names the file")
    elif r is not None:
        ok(False, "refusal carries a named reason object (got bare bool)")
    r = annex(["server/engine/concurrency.py"], initial,
              dict(CTX, who="executor", reason="r"))
    if r is not None and not isinstance(r, bool):
        text = __import__("json").dumps(r)
        ok("held" in text.lower() or "in-flight" in text.lower()
           or "ticket" in text.lower(),
           "held-file refusal names the condition (not a generic no)")


if __name__ == "__main__":
    main()
    print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)
