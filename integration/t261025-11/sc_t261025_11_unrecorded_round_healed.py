#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261025_11_unrecorded_round_healed.py — a COMPLETED round whose settle
block never ran leaves zero rows today; the next tick must heal it with
exactly ONE named row (ticket t261025-11, the measured repro of KI-352's
family: run-01M5RJ2MDAEX796E7MV0KE324X and run-01M5RWBFA0A1DPBZ2A1J0RHGTJ
wrote a face and a runner row and no delivery-ledger row at all).

Run directly:
python3 integration/t261025-11/sc_t261025_11_unrecorded_round_healed.py
(cwd = repo root).

Grey-box L3, offline seconds, REAL delivery ledger + scenario-runs store +
guard files on a tmp store via the shared t261009-30 round fixture, driven
through the REAL tick call site (develop_certify.line_round_tick) with
injected seams, zero docker/Temporal/browser, never touches 3099/7233.

The incident this entry owns: the drop happens BEFORE the settle block (the
engine side never processed the finished runner's header — both witnesses
appear exactly once in scenario-runs.jsonl), so in-settle hardening alone
does not close the class. The one-record contract must hold on the
healing path too: driven from the durable runner row, not from the dead
process's memory. The reader side (the delivery ledger and the refusal
face on disk) is the only judge — writer receipts are not evidence.

A  WITNESS REPLAY — a complete runner row (the witness shape: ran=702,
   failed=0, env_failed=12) present once, no ledger row citing the run id:
   one tick heals it with exactly ONE certification row citing the run id
   and the witnessed revision; replaying the tick writes nothing more
   (idempotent, never two). The witness cites a REAL commit of this
   fixture's own line worktree, because the heal may certify only what the
   repository can hand to a checkout (t261030-25, KI-429).
B  UNJUDGABLE HEADER — a runner row whose header cannot be judged lands
   exactly ONE named range-growth row citing the run id (never zero, never
   a guessed cert), idempotent on replay.
C  GUARD HELD — while a round may be in flight (guard held) the tick heals
   nothing: zero rows, no premature record.
D  LINE AMBIGUOUS — the run's revision matches no declared line landing
   and more than one line is declared: no ledger row (never a guess), and
   a named refusal on the tick-refusal face citing the run id.
E  MALFORMED INPUTS — garbage lines in the runs store and the delivery
   ledger are named (stderr), never guessed into rows, never crash the
   tick; the readable rows keep their meaning.
F  SETTLE-ROW REJECTED (not raised) — an append face that answers
   written<len(batch) during the settle row must not leave silent zero
   rows: the failure is retried and/or lands loud on a named second face,
   and the original error still surfaces.
G  REFUSAL PINNED (t261030-25 contract) — the same witness shape whose
   revision the project's line trees cannot produce is REFUSED BY NAME and
   writes NO certification row: G1 names an undeclared line tree
   (certification_refused:repo_not_resolvable:<repo>@<rev>:caller=...), G2
   names a fabricated revision inside a real tree
   (certification_refused:revision_not_a_git_object:<repo>@<rev>:caller=...); each
   records exactly ONE range-growth row carrying that refusal, and a replay
   writes nothing more. The guard is a contract, not a convenience: this
   leg reds when the refusal is bypassed (mutation-checked at delivery).
   A and G share ONE fixture shape and differ only in whether the revision
   resolves — remove the line tree from A and A must fail, remove the
   refusal and G must fail.

The scenario frees nothing to the machine: every tick runs against tmp
ledgers and, for the reachability net, a tmp projects root
(SANDBAR_PROJECTS_DIR pinned for this process) — the REAL projects root is
never read or written (KI-429's fixture leak). Git is required by the net;
git absent = ENV_FAIL.

Pre-implementation tree: A/B/D/F red is the expected TDD signal (the
healing path does not exist yet); green required at the integration gate /
merge. Engine tree missing = ENV_FAIL exit 2.
"""

import contextlib
import io
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "integration" / "t261009-30"))

import lib_round_fixture as fx  # noqa: E402


def fail(name, why):
    print("FAIL %s: %s" % (name, why))
    sys.exit(1)


def ok(name):
    print("PASS %s" % name)


RUN_ID = "run-01M5RJ2MDAEX796E7MV0KE324X"
REV = "dbb88cd5aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"[:40]
#: The project keys the reachability net is asked about: one whose line tree
#: this scenario builds, one whose line tree is real but whose witness cites
#: a fabricated revision, and one that declares no line tree at all.
PROJECT = "itg11"
PROJECT_NO_TREE = "itg11-norepo"
PROJECT_FAKE_REV = "itg11-fabrev"
FAKE_REV = "f" * 40


def runner_row(rid=RUN_ID, cases=None, verdict="green", rev=REV):
    return {"id": rid, "kind": "line-round",
            "source": "lane:line-round", "verdict": verdict,
            "cases": cases if cases is not None else
            {"ran": 702, "passed": 690, "failed": 0, "env_failed": 12},
            "repos": fx.line_repos(rev)}


def refusal(why, rev, repo="sandbar", rid=RUN_ID):
    """The ONE named refusal the ledger side must answer for a candidate
    revision the repository cannot hand to a checkout (t261030-25). Written
    out HERE on purpose: the scenario states the contract, it does not ask
    the implementation what the contract is."""
    return "certification_refused:%s:%s@%s:caller=reconciled:%s" % (
        why, repo, rev, rid)


def pin_projects_root(projects):
    """Point the reachability net at THIS fixture's projects root.

    ``perkey_projects_root`` reads SANDBAR_PROJECTS_DIR fresh on every call,
    so one assignment covers the tick under test. Never the real projects
    root: a fixture once wrote fabricated revisions into the REAL one and
    the reconciliation booked them (KI-429)."""
    os.environ["SANDBAR_PROJECTS_DIR"] = str(projects)


def write_runs_store(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")


def read_ledger(mod, ledger):
    rows, bad = mod.read_rows(str(ledger))
    return rows, bad


def rows_citing(rows, rid):
    return [r for r in rows if rid in json.dumps(r, ensure_ascii=False)]


class FakeLine:
    """Minimal declared-line stand-in: the tick's own seams read only what
    the declaration contract promises (an id and the declared repos)."""

    def __init__(self, line_id, revision):
        self.line_id = line_id
        self.repositories = [type("R", (), {"name": "sandbar",
                                            "branch": revision})()]


def tick(mod, root, ledger, guard, lines, now_ms=1700000000000,
         runs_store=None, project=PROJECT):
    """One tick through the REAL call site with injected seams."""
    return mod.line_round_tick(
        project_key=project, load_lines=lambda pk: lines,
        read_rows=lambda: mod.read_rows(str(ledger)),
        append_rows=lambda batch: mod.append_rows(batch, str(ledger)),
        resolve_runner_fn=lambda line, env: None,  # no live round is asked
        guard_path=guard, now_ms=now_ms, runs_store=runs_store)


def main():
    mod = fx.load_module()
    if mod is None or not callable(getattr(mod, "line_round_tick", None)):
        fail("engine", "develop_certify.line_round_tick missing — the "
                       "engine tree this ticket owes has not landed")
    # The healing seam this ticket owes: the tick must expose a way to
    # reconcile unrecorded completed rounds. Pre-implementation this
    # attribute is absent and A–D fail by name.
    if not hasattr(mod, "TICK_REFUSALS_NAME"):
        fail("engine", "TICK_REFUSALS_NAME missing — refusal-face contract "
                       "absent from this tree")
    if shutil.which("git") is None:
        fx.env_fail("git absent — the reachability net (t261030-25) is "
                    "judged by a git subprocess")
    # KI-429 discipline: the net resolves its line trees through
    # SANDBAR_PROJECTS_DIR, read fresh on every call. Pin it to a tmp root
    # this scenario owns BEFORE any leg, so no leg can reach the REAL
    # projects root — a fixture once wrote fabricated revisions into it and
    # the reconciliation booked them.
    projects = fx.projects_root()
    pin_projects_root(projects)

    # ---- A: witness replay -------------------------------------------------
    # The witness cites a REAL commit object of this fixture's own line
    # worktree: the heal may certify only what the repository can hand to a
    # checkout (t261030-25, KI-429).
    root, ledger, guard = fx.round_fixture()
    real_rev = fx.git_line_tree(projects, PROJECT, "sandbar")
    runs = root / "scenario-runs.jsonl"
    write_runs_store(runs, [runner_row(rev=real_rev)])
    out = tick(mod, root, ledger, guard,
               {"default": FakeLine("default", real_rev)}, runs_store=str(runs))
    rows, bad = read_ledger(mod, ledger)
    if bad:
        fail("A-witness-replay", "ledger grew malformed lines: %r" % bad)
    citing = rows_citing(rows, RUN_ID)
    if len(citing) != 1:
        fail("A-witness-replay", "expected exactly ONE healed row citing "
             "%s after the tick, got %d (rows=%r) out=%r"
             % (RUN_ID, len(citing), citing, out))
    if citing[0].get("kind") != mod.KIND_CERT:
        fail("A-witness-replay", "healed row kind %r is not a certification "
             "for a green-shaped header" % citing[0].get("kind"))
    if citing[0].get("repos") != fx.line_repos(real_rev):
        fail("A-witness-replay", "healed certification cites %r, not the "
             "witnessed revision %r" % (citing[0].get("repos"), real_rev))
    # replay: idempotent, never two
    tick(mod, root, ledger, guard, {"default": FakeLine("default", real_rev)},
         now_ms=1700000001000, runs_store=str(runs))
    rows2, _ = read_ledger(mod, ledger)
    if len(rows_citing(rows2, RUN_ID)) != 1:
        fail("A-witness-replay", "second tick wrote a duplicate — heal is "
             "not idempotent by run id")
    ok("A-witness-replay")

    # ---- B: unjudgable header ---------------------------------------------
    root, ledger, guard = fx.round_fixture()
    runs = root / "scenario-runs.jsonl"
    write_runs_store(runs, [runner_row(cases="not-a-dict")])
    tick(mod, root, ledger, guard, {"default": FakeLine("default", REV)},
         runs_store=str(runs))
    rows, _ = read_ledger(mod, ledger)
    citing = rows_citing(rows, RUN_ID)
    if len(citing) != 1:
        fail("B-unjudgable-header", "expected exactly ONE named row citing "
             "the run id for an unjudgable header, got %d" % len(citing))
    if citing[0].get("kind") != mod.KIND_RANGE_GROWTH:
        fail("B-unjudgable-header", "unjudgable header must grow the range "
             "with a NAMED row, got kind %r" % citing[0].get("kind"))
    tick(mod, root, ledger, guard, {"default": FakeLine("default", REV)},
         now_ms=1700000001000, runs_store=str(runs))
    rows2, _ = read_ledger(mod, ledger)
    if len(rows_citing(rows2, RUN_ID)) != 1:
        fail("B-unjudgable-header", "heal not idempotent for the range-"
             "growth path")
    ok("B-unjudgable-header")

    # ---- C: guard held ------------------------------------------------------
    root, ledger, guard = fx.round_fixture()
    runs = root / "scenario-runs.jsonl"
    write_runs_store(runs, [runner_row()])
    mod.guard_acquire(guard, "itg11-live-round")
    try:
        tick(mod, root, ledger, guard, {"default": FakeLine("default", REV)},
             runs_store=str(runs))
    finally:
        rows, _ = read_ledger(mod, ledger)
        with contextlib.suppress(Exception):
            mod.guard_release(guard)
    if rows_citing(rows, RUN_ID):
        fail("C-guard-held", "tick healed while a round could be in flight "
             "(guard held) — rows %r" % rows_citing(rows, RUN_ID))
    ok("C-guard-held")

    # ---- D: line ambiguous --------------------------------------------------
    root, ledger, guard = fx.round_fixture()
    runs = root / "scenario-runs.jsonl"
    write_runs_store(runs, [runner_row()])
    lines = {"a": FakeLine("a", REV), "b": FakeLine("b", REV)}
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = tick(mod, root, ledger, guard, lines, runs_store=str(runs))
    rows, _ = read_ledger(mod, ledger)
    if rows_citing(rows, RUN_ID):
        fail("D-line-ambiguous", "an ambiguous run was guessed onto a line: "
             "%r" % rows_citing(rows, RUN_ID))
    face = ledger.parent / mod.TICK_REFUSALS_NAME
    face_txt = face.read_text(encoding="utf-8") if face.is_file() else ""
    if ("unrecorded_run:%s" % RUN_ID) not in json.dumps(out, default=str) \
            and RUN_ID not in face_txt:
        fail("D-line-ambiguous", "the ambiguity is silent: neither the tick "
             "entries nor the refusal face names the run id")
    ok("D-line-ambiguous")

    # ---- E: malformed inputs -------------------------------------------------
    root, ledger, guard = fx.round_fixture()
    runs = root / "scenario-runs.jsonl"
    write_runs_store(runs, [runner_row(), {"id": "garbage"},
                            "not-json-at-all"])
    seed = {"kind": "certification", "id": "cert-x", "line": "default",
            "run": "run-keep", "repos": fx.line_repos(REV), "at": 1,
            "judged_by": "seed", "verdict": "green"}
    ledger.write_text(json.dumps(seed) + "\n}}}broken{{{ \n",
                      encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            out = tick(mod, root, ledger, guard,
                       {"default": FakeLine("default", REV)},
                       runs_store=str(runs))
        except Exception as e:  # noqa: BLE001
            fail("E-malformed-inputs", "tick raised on malformed input: "
                 "%s: %s" % (type(e).__name__, e))
    named = err.getvalue() + json.dumps(out, default=str) + \
        (ledger.parent / mod.TICK_REFUSALS_NAME).read_text(
            encoding="utf-8") if (ledger.parent /
                                  mod.TICK_REFUSALS_NAME).is_file() \
        else err.getvalue() + json.dumps(out, default=str)
    if "malformed" not in named and "garbage" not in named:
        fail("E-malformed-inputs", "malformed lines were skipped silently — "
             "some face must name them (stderr/out=%r)"
             % named[:400])
    rows, _ = read_ledger(mod, ledger)
    for r in rows:
        if "not-json" in json.dumps(r, ensure_ascii=False):
            fail("E-malformed-inputs", "a garbage line was guessed into a "
                 "row: %r" % r)
    ok("E-malformed-inputs")

    # ---- F: settle-row rejected (not raised) ---------------------------------
    root, ledger, guard = fx.round_fixture()
    # the range must be non-empty or the round never asks (range_empty):
    # seed one landing row through the REAL append (it assigns seq); only
    # the SETTLE batch is rejected afterwards
    fx.append(mod, ledger, [fx.landing_row("t261025-11-f", REV,
                                           1700000000000)])
    attempts = {"n": 0}
    state = {"fail": True}

    def rejecting_append(batch):
        if state["fail"]:
            attempts["n"] += 1
            # rejected, NOT raised: the shape _append_settle_row must not
            # swallow (written != len(batch))
            return {"written": 0, "rejected": list(batch)}
        return mod.append_rows(batch, str(ledger))

    err = io.StringIO()
    original = None
    with contextlib.redirect_stderr(err):
        try:
            mod.run_line_round(
                line="default", trigger="change", guard_path=guard,
                runner=fx.FakeRunner(
                    headers=[fx.run_header("run-itg11-f", 3)]),
                read_rows=lambda: mod.read_rows(str(ledger)),
                append_rows=rejecting_append,
                judged_by="itg11", booked_red="br@itg11")
        except Exception as e:  # noqa: BLE001
            original = "%s: %s" % (type(e).__name__, e)
    if original is None:
        # the round claims success — then the record MUST be on the ledger
        rows, _ = read_ledger(mod, ledger)
        if not any(r.get("run") == "run-itg11-f" for r in rows):
            fail("F-settle-row-rejected", "append rejected, no retry landed, "
                 "no error surfaced: silent zero rows (the forbidden shape)")
    else:
        loud = err.getvalue()
        if "SETTLE" not in loud and "settle" not in loud:
            fail("F-settle-row-rejected", "persistent rejection must be loud "
                 "on a named second face (stderr=%r)" % loud[:300])
        if "run_append_rejected" not in original and \
                "round_append_rejected" not in original:
            fail("F-settle-row-rejected", "surfaced error does not name the "
                 "rejection: %r" % original)
    ok("F-settle-row-rejected")

    # ---- G: the reachability refusal is pinned (t261030-25 contract) --------
    # The SAME witness shape as A, differing in ONE fact: the revision cannot
    # be produced by the repository the line claims to judge. The heal must
    # refuse BY NAME and write NO certification — a fabricated revision that
    # becomes a certification is what froze the line once (KI-429).
    #
    # G1: the project declares no line tree at all  -> repo_not_resolvable
    # G2: the tree is real, the revision is not     -> revision_not_a_git_object
    fx.git_line_tree(projects, PROJECT_FAKE_REV, "sandbar")
    for name, project, rev, why in (
            ("G1-refusal-repo-not-resolvable", PROJECT_NO_TREE, "a" * 40,
             "repo_not_resolvable"),
            ("G2-refusal-not-a-git-object", PROJECT_FAKE_REV, FAKE_REV,
             "revision_not_a_git_object")):
        root, ledger, guard = fx.round_fixture()
        runs = root / "scenario-runs.jsonl"
        write_runs_store(runs, [runner_row(rev=rev)])
        try:
            out = tick(mod, root, ledger, guard,
                       {"default": FakeLine("default", rev)},
                       runs_store=str(runs), project=project)
        except Exception as e:  # noqa: BLE001
            fail(name, "the tick raised instead of refusing by name: %s: %s"
                 % (type(e).__name__, e))
        want = refusal(why, rev)
        entries = [e for e in out.get("lines", []) if e.get("run") == RUN_ID]
        if len(entries) != 1:
            fail(name, "expected ONE named entry for the refused run, got %r "
                 "(out=%r)" % (entries, out))
        if entries[0].get("error") != want:
            fail(name, "the refusal is not the named contract: got %r, want %r"
                 % (entries[0].get("error"), want))
        rows, bad = read_ledger(mod, ledger)
        if bad:
            fail(name, "ledger grew malformed lines: %r" % bad)
        certs = [r for r in rows if r.get("kind") == mod.KIND_CERT]
        if certs:
            fail(name, "an unreachable revision was CERTIFIED: %r" % certs)
        if any(r.get("kind") == mod.KIND_FREEZE for r in rows):
            fail(name, "an unreachable revision opened a freeze: %r" % rows)
        citing = rows_citing(rows, RUN_ID)
        if len(citing) != 1:
            fail(name, "expected exactly ONE refusal row citing the run id, "
                 "got %d (rows=%r)" % (len(citing), citing))
        if citing[0].get("kind") != mod.KIND_RANGE_GROWTH \
                or want not in str(citing[0].get("reason") or ""):
            fail(name, "the refusal must land as ONE named range-growth row, "
                 "got %r" % citing[0])
        # replay: the refusal row cites the run id, so nothing is written twice
        out2 = tick(mod, root, ledger, guard,
                    {"default": FakeLine("default", rev)},
                    now_ms=1700000001000, runs_store=str(runs),
                    project=project)
        rows2, _ = read_ledger(mod, ledger)
        if len(rows2) != len(rows) or rows_citing(rows2, RUN_ID) != citing:
            fail(name, "the refusal was re-written on replay: %d rows before, "
                 "%d after (out2=%r)" % (len(rows), len(rows2), out2))
        ok(name)

    print("INTEG_T261025_11_OK all seven faces green")
    sys.exit(0)


if __name__ == "__main__":
    main()
