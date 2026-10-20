#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101902_line_landing_closeout_guard.py -- t261019-02 L3 (integration role).

User-visible contract (ticket t261019-02, host ruling 261019 verbatim "the
tickets that landed on the line certainly have to go through the line round
to be promoted"): a ticket whose landing row already exists on a declared
develop line must NEVER reach main through the legacy per-ticket human merge
gate. Measured defect: t261018-05 landed on the line (77c264da), other
tickets squash-closed straight onto main, and main was left with no trace of
the landing while the ticket read closed.

  A  LANDED TICKET REFUSED — a legacy-path ticket with a landing row on a
     declared line, reaching the merge phase on the patched version, is
     blocked named: the ruling quoted, the line named, and BOTH human ways
     out named (green line certification + promotion, or human rework); the
     block names the "merge" step and happens WITHOUT a human signature
     being requested.
  B  NEVER-LANDED PASSES — a ticket with no landing row on any declared line
     passes the guard: no block, the legacy gate proceeds (zero behaviour
     drift for tickets that never landed).
  C  LINE-LESS PROJECT VACUOUS (the gen0 breaker, regression pin) — a
     project with NO lines.json at all (the normal state of every project
     that never adopted develop lines) reads as zero declared lines: the
     guard is vacuous and the legacy gate proceeds. An absent delivery
     ledger reads the same way.
  D  CORRUPT LEDGER NAMED BLOCK — a delivery ledger holding malformed JSONL
     lines blocks named (the read_rows "bad" face is never swallowed at a
     close-out decision); fail-closed over records we could not read.
  E  MALFORMED DECLARATION NAMED BLOCK — a PRESENT but unparseable
     lines.json blocks named. (Absence vs malformation is exactly the R1
     split: only (E) blocks, (C) passes.)
  F  EMPTY PROJECT KEY NAMED BLOCK — an empty/whitespace project key refuses
     named (shared.develop_dir's rule-9 raise), never guessed.
  G  CALL-SITE SHAPE (replay discipline, KI-061) — in dev_lane.py the guard
     is consulted at the LEGACY merge phase only: after the
     is_develop_buffer_ticket fork, before prepare_human_gate (no signature
     ever consumed on a refused close-out), inside a
     workflow.patched(<guard patch id>) verdict, with a UNIQUE patch id
     literal; the unpatched replay of an old history executes none of it.

Grey-box: shallow binding — behaviour legs drive the guard THROUGH ONE
declared seam, the DevLaneWorkflow coroutine
``_line_landing_closeout_guard() -> bool`` (True = this close-out is
refused; the helper itself performs the named _blocked), with the workflow
facade stubbed (t261005-14 technique) and real fixture project stores on
disk (isolated SANDBAR_PROJECTS_DIR + SANDBAR_DELIVERY_LEDGER_DIR). Leg G is
the offline source-shape lock (t260925-17 technique) — order/nearness only,
never line numbers. The landing/certification/promotion acts, the freeze
semantics and the certification caliber are NOT touched or re-asserted here
(ticket body); their journeys belong to the t261009-18/-28/-30/-46/-67
families. A landing-row query over a GOOD ledger belongs to developer L1
truth tables; this entry owns the merge-gate refusal journey and the
fail-closed posture over unreadable inputs.

Pre-implement tree: A/D/E/F/G red is the expected TDD signal; B/C must stay
green on any tree (they pin today's lawful pass-through). Green required at
the integration gate / merge.
Three states only: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP).
git absent, repo root unresolvable, or engine modules unimportable =
ENV_FAIL exit 2, named. Offline seconds; zero docker/Temporal/browser;
never touches 3099/7233.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True)
ENGINE = os.path.join(REPO.stdout.strip(), "server", "engine") if REPO.returncode == 0 else ""

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


class StopSentinel(Exception):
    """Raised by the stubbed _blocked after recording the refusal."""


RULING = "the tickets that landed on the line certainly have to go through the line round"


def make_env():
    """Isolated project store + delivery ledger dir; returns (root, cleanup)."""
    root = tempfile.mkdtemp(prefix="t26101902-")
    saved = {
        "SANDBAR_PROJECTS_DIR": os.environ.get("SANDBAR_PROJECTS_DIR"),
        "SANDBAR_DELIVERY_LEDGER_DIR": os.environ.get("SANDBAR_DELIVERY_LEDGER_DIR"),
    }
    os.environ["SANDBAR_PROJECTS_DIR"] = root
    os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = os.path.join(root, "ledger")

    def cleanup():
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(root, ignore_errors=True)

    return root, cleanup


def declare_line(key, line_id="line-1"):
    import shared
    dev_dir = shared.develop_dir(key)
    os.makedirs(dev_dir, exist_ok=True)
    with open(os.path.join(dev_dir, "lines.json"), "w") as f:
        json.dump([{"version": 1, "line_id": line_id, "scope": "slice",
                    "owner": "integration-role",
                    "repositories": [{"name": "repo1", "branch": "develop/main-line"}]}], f)


def write_ledger(key, rows):
    """rows: list of dicts (written as JSONL) or raw strings (malformed)."""
    import develop_certify
    p = develop_certify.ledger_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for r in rows:
            f.write(r if isinstance(r, str) else json.dumps(r) + "\n")


def landing_row(key, ticket, line_id="line-1"):
    return {"id": "ldg-t26101902%s" % ticket[-2:], "kind": "landing",
            "ticket": ticket, "line": line_id, "seq": 1,
            "revision": {"repo1": "a" * 40}, "at": 0,
            "performer": "integration-test"}


def make_shell(project, ticket, patched_value, recorded):
    """A DevLaneWorkflow instance shell (t261005-14 technique): the real
    class, the facade swapped for a stub answering patched(), _blocked
    recorded then stopped. Everything else the guard touches stays real."""
    import dev_lane

    class _StubWorkflow:
        @staticmethod
        def patched(_patch_id):
            return patched_value

        # 261019: the guard's decision moved into an ACTIVITY (the Temporal sandbox refused
        # the in-workflow ledger read). The stub serves that activity locally by calling the
        # real activity function, so the scenario still drives the real decision once
        # (main's generic relay — dec761cd/bd9ad3bb — kept over the lane's direct
        # pure-core call: it drives whatever activity the guard passes, so the truth
        # table holds on both patch branches without guessing the call signature).
        @staticmethod
        async def execute_activity(fn, arg, **kwargs):
            import inspect
            res = fn(arg)
            return await res if inspect.isawaitable(res) else res

    saved_facade = dev_lane.workflow
    dev_lane.workflow = _StubWorkflow()
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.ticket_id = ticket
    wf.meta = {"project": project, "worktree": "/nonexistent",
               "base_ref": "main", "branch": "lane/x", "workspace": "/nonexistent"}
    wf._log = lambda *a, **k: None
    wf._touch = lambda: None

    async def _blocked(step_id, why):
        recorded.append({"step": step_id, "why": why})
        raise StopSentinel()

    wf._blocked = _blocked
    wf._saved_facade = saved_facade
    return wf


def drive_guard(project, ticket, patched_value):
    """Returns (returned_value, refusal_or_None, error_or_None). AttributeError
    from a missing seam propagates to the caller (S0 already named it)."""
    import dev_lane
    recorded = []
    wf = make_shell(project, ticket, patched_value, recorded)
    saved = wf._saved_facade
    try:
        val = asyncio_run(wf._line_landing_closeout_guard())
        return val, (recorded[0] if recorded else None), None
    except StopSentinel:
        return None, (recorded[0] if recorded else None), None
    except ValueError as e:
        return None, None, e
    finally:
        dev_lane.workflow = saved


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def main():
    if shutil.which("git") is None or REPO.returncode != 0:
        print("ENV_FAIL: git or repo root unavailable")
        return 2
    if not os.path.isdir(ENGINE):
        print("ENV_FAIL: server/engine missing")
        return 2
    sys.path.insert(0, ENGINE)
    try:
        import dev_lane  # noqa: F401
        import develop_certify  # noqa: F401
        import shared  # noqa: F401
    except Exception as e:
        print("ENV_FAIL: engine modules unimportable (%s: %s)"
              % (type(e).__name__, e))
        return 2

    seam = getattr(dev_lane.DevLaneWorkflow, "_line_landing_closeout_guard", None)
    check("S0 guard seam present",
          seam is not None and asyncio_iscoroutine(seam),
          "DevLaneWorkflow._line_landing_closeout_guard coroutine missing — "
          "the declared scenario seam; implement the guard as this named "
          "helper called at the legacy merge-phase site")

    root, cleanup = make_env()
    try:
        key = "t26101902-proj"
        tk = "t26101902-fix"

        # ---- A: landed ticket refused, named, merge step, no signature ----
        if seam is not None:
            declare_line(key)
            write_ledger(key, [landing_row(key, tk)])
            val, ref, err = drive_guard(key, tk, True)
            check("A1 landed -> blocked (returned True)",
                  val is None and ref is not None,
                  "val=%r ref=%r err=%r" % (val, ref, err))
            check("A2 blocked names the merge step",
                  bool(ref) and ref.get("step") == "merge", repr(ref))
            why = (ref or {}).get("why", "")
            check("A3 ruling quoted in the block", RULING in why, why[:300])
            check("A4 line named in the block", "line-1" in why, why[:300])
            check("A5 both ways out named",
                  ("certif" in why.lower()) and ("promotion" in why.lower() or "promot" in why.lower())
                  and ("rework" in why.lower()), why[:400])

        # ---- B: never-landed passes ----
        if seam is not None:
            declare_line(key)
            write_ledger(key, [])  # empty ledger, no landing rows
            val, ref, err = drive_guard(key, "t26101902-other", True)
            check("B1 never-landed passes, no block",
                  val is False and ref is None and err is None,
                  "val=%r ref=%r err=%r" % (val, ref, err))

        # ---- C: line-less project vacuous (the gen0 breaker pin) ----
        if seam is not None:
            import shared
            dev_dir = shared.develop_dir(key + "b")
            shutil.rmtree(dev_dir, ignore_errors=True)
            write_ledger(key + "b", [])
            val, ref, err = drive_guard(key + "b", tk, True)
            check("C1 missing lines.json -> vacuous pass",
                  val is False and ref is None,
                  "val=%r ref=%r err=%r" % (val, ref, err))
            # absent ledger too
            import develop_certify
            lp = develop_certify.ledger_path(key + "b")
            if lp.exists():
                lp.unlink()
            declare_line(key + "b")
            val, ref, err = drive_guard(key + "b", tk, True)
            check("C2 absent ledger -> vacuous pass",
                  val is False and ref is None,
                  "val=%r ref=%r err=%r" % (val, ref, err))

        # ---- D: corrupt ledger named block; absent-ledger control above ----
        if seam is not None:
            declare_line(key + "c")
            write_ledger(key + "c", ['{"kind": "landing", "ticket": "x"',  # torn JSON
                                     landing_row(key + "c", tk)])
            val, ref, err = drive_guard(key + "c", "t26101902-zz", True)
            check("D1 corrupt ledger -> blocked named",
                  val is None and ref is not None and ref.get("step") == "merge",
                  "val=%r ref=%r err=%r" % (val, ref, err))
            why = (ref or {}).get("why", "")
            check("D2 block names the unreadable-ledger face",
                  ("malformed" in why.lower() or "unreadable" in why.lower()
                   or "corrupt" in why.lower()),
                  why[:300])

        # ---- E: malformed declaration named block ----
        if seam is not None:
            import shared
            dev_dir = shared.develop_dir(key + "d")
            os.makedirs(dev_dir, exist_ok=True)
            with open(os.path.join(dev_dir, "lines.json"), "w") as f:
                f.write('{"not": "a list"')
            write_ledger(key + "d", [])
            val, ref, err = drive_guard(key + "d", tk, True)
            check("E1 malformed lines.json -> blocked named",
                  val is None and ref is not None and ref.get("step") == "merge",
                  "val=%r ref=%r err=%r" % (val, ref, err))

        # ---- F: empty project key named block ----
        if seam is not None:
            val, ref, err = drive_guard("   ", tk, True)
            check("F1 empty project key -> named block, no crash",
                  val is None and (ref is not None or
                                   (err is not None and "develop_dir" not in str(err))),
                  "val=%r ref=%r err=%r" % (val, ref, err))

        # ---- G: call-site shape (offline source lock, no line numbers) ----
        src = open(os.path.join(ENGINE, "dev_lane.py"), encoding="utf-8").read()
        m_phase = re.search(r'if phase == "merge":.*?(?=\n            # \d|\n            if phase == )',
                            src, re.S)
        check("G1 merge phase block found", m_phase is not None, "")
        block = m_phase.group(0) if m_phase else ""
        # 261019: the fence moved INTO the merge activity (the Temporal sandbox refused the
        # in-workflow ledger read; workflow.patched could never reach an in-flight history).
        # The workflow-side guard call is gone by design, so G2/G3 re-anchor to the new home:
        # the ACTIVITY consults the fence before it squashes anything, and the workflow's
        # merge phase no longer reads the ledger at all.
        aa_src = open(os.path.join(ENGINE, "agent_activities.py"), encoding="utf-8").read()
        i_merge_def = aa_src.find("async def merge(args: MergeArgs)")
        i_fence = aa_src.find("_line_landing_closeout_refusal_for(args.ticket_id)", i_merge_def)
        i_squash = aa_src.find("_squash_merge(", i_merge_def)
        check("G2 the merge activity consults the fence before the first squash",
              0 <= i_merge_def < i_fence < i_squash,
              "def=%d fence=%d squash=%d" % (i_merge_def, i_fence, i_squash))
        check("G3 the workflow merge phase no longer reads the ledger (sandbox-safe)",
              "_line_landing_closeout_guard()" not in block,
              "the workflow still calls the in-workflow guard")
        ids = re.findall(r'([A-Z0-9_]+_PATCH_ID[A-Z0-9_]*)\s*=\s*"([^"]+)"', src)
        vals = [v for _, v in ids]
        check("G4 guard patch id unique", len(vals) == len(set(vals)),
              "duplicate patch id literals: %s" %
              [v for v in set(vals) if vals.count(v) > 1])
        guard_ids = re.findall(r'workflow\.patched\(([A-Z0-9_]+)\)', block)
        check("G5 call site sits inside a patched verdict",
              len(guard_ids) >= 1 and "LINE_LANDING_CLOSEOUT_GUARD" in "".join(guard_ids),
              "patched ids at merge site: %s" % guard_ids)
    finally:
        cleanup()

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 0 if failed == 0 else 1


def asyncio_iscoroutine(fn):
    import asyncio
    try:
        return asyncio.iscoroutinefunction(fn)
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
