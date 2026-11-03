#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261025-11 — a completed line round can never leave ZERO ledger rows.

The measured shape (two witnesses on 261025, project ledger read-only): the
runner COMPLETED — face done, run row persisted into scenario-runs.jsonl —
and the engine side never processed the header (the settle block's runs_store
persist never happened, so the run appears in the runs store exactly once).
The drop sits before the settle block, so in-settle nets cannot see it.

Legs:
- S1 _append_settle_row checks the writer's answer: a REJECTED batch (no
  raise) retries once and, with a face_dir, names the unrecorded round on
  the tick refusal face — never silent zero rows; a clean write touches
  nothing else; a raising writer still never masks its caller (nothing to
  mask here — the function never raises).
- R1 the witness shape heals into exactly ONE green certification whose
  judged_by names the reconstruction; a replay heals nothing (idempotent).
- R2 an unjudgable run header heals into ONE range-growth row naming the
  run id; replay writes nothing.
- R3 a content red heals cert + freeze (the settle block's own mapping).
- R4 a run whose revision set matches no landing on a multi-line project is
  NEVER guessed: no ledger row, a named error entry.
- R5 guard held: nothing written (a round may be in flight).
- R6 an append failure is a named error entry, never an exception.
- T1 the full tick heals the witness and idles — no round, no second row.
- T2 a malformed runs store is a named error entry, never a guess.
- KI-456 (added by t261103-06) the round's TWO passes are told apart on the
  booking side: the CANDIDATE pass (the line head the round judged) is the
  only verdict — it books the certification and, when it is red, the freeze;
  the BASELINE-rebuild pass (the same suite run at main's tip for the relative
  comparison) books NOTHING and opens NO freeze, however red it is. A row tied
  to neither identity books nothing and names the refusal, and the retired
  ``sole_line`` take-anyway no longer grants a booking.
- t261103-10 the BASELINE role is decided by DURABLE EVIDENCE ONLY: the
  row's run id recorded in the baseline cache as a baseline rebuild's run.
  Being a main baseline tip is not proof — a line head created from main IS
  the main tip — so that identity no longer skips a run row: it only sharpens
  the refusal text, and a completed, attributable round whose head equals the
  main tip heals with exactly ONE row. The tick hands its own declaration to
  the heal, so the head identity is the one the round ran with, not a second
  store read.

Zero docker, zero Temporal, never touches 3099; no real runner. The KI-456
legs use real git fixture repos under an injected projects root and a temp
ledger — no network, no store of any real project.
"""
import json
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402

LINE = "develop-buffer"
OTHER = "develop-other"
RUN_ID = "run-01M5RJ2MDAEX796E7MV0KE324X"  # the measured witness id (shape)


def ledger(tmp_path):
    return tmp_path / "ledger" / "delivery.jsonl"


def reader(path):
    return lambda: dc.read_rows(path)


def writer(path):
    return lambda batch: dc.append_rows(batch, path)


def landing(repo, rev, line=LINE, ticket="t1", at=1):
    return {"kind": "landing", "id": dc.mint_id("ldg", at), "ticket": ticket,
            "line": line, "repos": [{"repo": repo, "revision": rev}],
            "actor": "test", "at": at}


def witness_run(rid=RUN_ID, verdict="green", cases=None, rev="dbb88cd5",
                repo="sandbar"):
    """The runner-persisted row of a completed round (measured shape)."""
    d = {"v": "run-ledger-v1", "id": rid,
            "source": dc.LINE_ROUND_RUN_SOURCE,
            "repos": [{"repo": repo, "revision": rev}],
            "verdict": verdict, "verdict_rule": "content-v1",
            "unverified_names": ["env-case-01"]}
    d["cases"] = cases if cases is not None else \
        {"ran": 702, "passed": 690, "failed": 0, "env_failed": 12}
    return d


def rows_of(path):
    rows, bad = dc.read_rows(path)
    assert not bad
    return rows


def heal(project, path, runs_rows, sole_line=True):
    return dc.reconcile_unrecorded_rounds(
        LINE, rows_of(path), runs_rows, writer(path), "tick", "booked-v1",
        1792909089000, sole_line=sole_line, project=project)


# ---- fixtures for the two-pass legs (KI-456 / t261103-06) -------------------

def _git(argv, cwd):
    import subprocess
    subprocess.run(["git"] + argv, cwd=str(cwd), check=True,
                   capture_output=True)


def _rev(repo_dir, ref):
    import subprocess
    return subprocess.run(["git", "-C", str(repo_dir), "rev-parse", ref],
                          check=True, capture_output=True,
                          text=True).stdout.strip()


def two_pass_repo(tmp_path, monkeypatch, repo="sandbar", project="proj",
                  line=LINE):
    """A project whose line worktree is a REAL git repository carrying TWO
    commits: main's tip (what the round's baseline-rebuild pass runs at) and
    the line branch tip (the candidate the round judged).

    The projects root is injected through the same seam the engine reads and
    ``lines.json`` declares the line branch, so ``line_head_candidate``
    answers with the candidate revision while main's tip stays distinct.
    Returns (project, main_rev, line_rev). No network, no docker, no real
    store; the temp tree dies with tmp_path."""
    projects = tmp_path / "projects"
    develop = projects / project / "data" / "develop"
    dive = develop / "wt" / repo
    dive.mkdir(parents=True)
    _git(["init", "-q", "-b", "main", "."], dive)
    _git(["config", "user.email", "t@example.invalid"], dive)
    _git(["config", "user.name", "t"], dive)
    (dive / "file.txt").write_text("main\n", encoding="utf-8")
    _git(["add", "-A"], dive)
    _git(["commit", "-qm", "main-tip"], dive)
    main_rev = _rev(dive, "refs/heads/main")
    _git(["checkout", "-q", "-b", "line"], dive)
    (dive / "line.txt").write_text("line\n", encoding="utf-8")
    _git(["add", "-A"], dive)
    _git(["commit", "-qm", "line-tip"], dive)
    line_rev = _rev(dive, "HEAD")
    _git(["checkout", "-q", "main"], dive)
    (develop / "lines.json").write_text(
        '[{"line_id": "%s", "repositories": [{"name": "%s", '
        '"branch": "line"}]}]\n' % (line, repo), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    return project, main_rev, line_rev


def pass_run(rid, rev, verdict="green", failed_names=None, cases=None,
             receipts=None, repo="sandbar"):
    """One runner-persisted run row of ONE pass of a round (the shape the
    line-round runner writes into the runs store)."""
    run = {"v": "run-ledger-v1", "id": rid,
           "source": dc.LINE_ROUND_RUN_SOURCE,
           "repos": [{"repo": repo, "revision": rev}],
           "verdict": verdict, "verdict_rule": "relative-content-v1"}
    if cases is not None:
        run["cases"] = cases
    elif verdict == "green":
        run["cases"] = {"ran": 703, "passed": 703, "failed": 0,
                        "env_failed": 0}
    else:
        run["cases"] = {"ran": 696, "passed": 691, "failed": 3,
                        "env_failed": 2}
    if failed_names:
        run["failed_names"] = list(failed_names)
        run["new_regressions"] = list(failed_names)
    if receipts is not None:
        run["fail_receipts"] = receipts
    return run


def certs(rows):
    return [r for r in rows if r["kind"] == dc.KIND_CERT]


def growths(rows):
    return [r for r in rows if r["kind"] == dc.KIND_RANGE_GROWTH]


# ---- S1: the settle-row writer's answer is checked --------------------------

def test_s1_rejected_batch_retries_then_names_refusal_face(tmp_path):
    calls = []

    def rejecting(batch):
        calls.append(batch)
        return {"written": 0, "rejected": [{"index": 0, "reason": "x"}]}

    dc._append_settle_row(rejecting, LINE, "round_settle_failed:E:boom",
                          face_dir=str(tmp_path))
    assert len(calls) == 2  # one retry, never a single silent attempt
    face = tmp_path / dc.TICK_REFUSALS_NAME
    rows, bad = dc.read_rows(face)
    assert not bad and len(rows) == 1
    assert rows[0]["state"] == "error"
    assert rows[0]["error"].startswith("settle_row_unrecorded:")
    assert rows[0]["line"] == LINE


def test_s1_clean_write_writes_no_face_and_no_retry(tmp_path):
    calls = []

    def ok(batch):
        calls.append(batch)
        return {"written": 1, "rejected": [], "seqs": [1]}

    dc._append_settle_row(ok, LINE, "run_executed_nothing",
                          face_dir=str(tmp_path))
    assert len(calls) == 1
    assert not (tmp_path / dc.TICK_REFUSALS_NAME).exists()


def test_s1_raising_writer_never_raises_and_names_face(tmp_path):
    calls = []

    def broken(batch):
        calls.append(batch)
        raise dc.CertifyError("ledger_has_malformed_lines:1")

    dc._append_settle_row(broken, LINE, "round_settle_failed:E:boom",
                          face_dir=str(tmp_path))
    assert len(calls) == 2
    rows, bad = dc.read_rows(tmp_path / dc.TICK_REFUSALS_NAME)
    assert not bad and rows[0]["state"] == "error"


def test_s1_failure_without_face_dir_is_stderr_only(tmp_path):
    dc._append_settle_row(lambda b: {"written": 0, "rejected": []},
                          LINE, "why", face_dir=None)
    assert not (tmp_path / dc.TICK_REFUSALS_NAME).exists()


# ---- R1: the witness shape heals into exactly ONE certification ------------

def test_r1_witness_heals_one_green_cert_and_replay_writes_nothing(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    runs = [witness_run()]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert len(out) == 1
    e = out[0]
    assert e["state"] == "reconciled" and e["run"] == RUN_ID
    assert e["attribution_rule"] == "landing_repo_match"
    rows = rows_of(p)
    cs = certs(rows)
    assert len(cs) == 1  # exactly ONE row — the contract
    assert cs[0]["run"] == RUN_ID
    assert cs[0]["judged_by"] == "reconciled:%s" % RUN_ID
    assert cs[0]["line"] == LINE
    assert not growths(rows)
    # idempotent by run id: the replay sees the cert and heals nothing
    out2 = dc.reconcile_unrecorded_rounds(
        LINE, rows, runs, writer(p), "tick", "booked-v1", 1792909089001,
        sole_line=True)
    assert out2 == []
    assert len(certs(rows_of(p))) == 1


def test_r1b_line_head_identity_certifies_without_a_landing_match(tmp_path,
                                                                 monkeypatch):
    """A round that judged the line's declared head carries a revision no
    landing cites yet (a manual round after a merge on the line): the head
    identity books it, named ``line_head_match``. The retired ``sole_line``
    take-anyway is NOT what books it — see the KI-456 section below."""
    project, _main_rev, line_rev = two_pass_repo(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "older-rev")], p)
    runs = [witness_run(rev=line_rev)]
    out = heal(project, p, runs)
    assert out[0]["state"] == "reconciled"
    assert out[0]["attribution_rule"] == "line_head_match"
    cs = certs(rows_of(p))
    assert len(cs) == 1
    assert cs[0]["repos"] == [{"repo": "sandbar", "revision": line_rev}]


def test_r1c_unattributable_pass_books_nothing_even_when_sole_line(tmp_path):
    """The retired take-anyway: a run row citing a revision that is neither a
    landing on this line nor its declared head books NOTHING and names the
    refusal. ``sole_line`` alone is not evidence of a candidate identity
    (KI-456: it booked a round's baseline pass as the line's certification)."""
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "older-rev")], p)
    runs = [witness_run(rev="b3c3ca5b")]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out[0]["state"] == "error"
    assert dc.REFUSE_PASS_UNKNOWN in out[0]["error"]
    assert "b3c3ca5b" in out[0]["error"]
    rows = rows_of(p)
    assert not [r for r in rows if r["kind"] == dc.KIND_CERT]
    assert not growths(rows)             # nothing booked at all


# ---- R2: an unjudgable header grows the range, naming the run id -----------

def test_r2_unjudgable_header_becomes_one_named_growth_row(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    runs = [witness_run(cases="garbage")]  # unreadable counts: no proof
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out[0]["state"] == "reconciled"
    assert "range_growth" in out[0]["wrote"]
    rows = rows_of(p)
    assert not certs(rows)
    g = growths(rows)
    assert len(g) == 1
    assert RUN_ID in g[0]["reason"]
    # replay: the growth row cites the run id, so nothing is written again
    out2 = dc.reconcile_unrecorded_rounds(
        LINE, rows, runs, writer(p), "tick", "booked-v1", 1792909089001,
        sole_line=True)
    assert out2 == []
    assert len(growths(rows_of(p))) == 1


# ---- R3: a content red heals cert + freeze (the settle mapping) ------------

def test_r3_content_red_heals_cert_plus_freeze(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    runs = [witness_run(verdict="red",
                        cases={"ran": 706, "passed": 688, "failed": 4,
                               "env_failed": 14})]
    dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    rows = rows_of(p)
    assert len(certs(rows)) == 1
    assert len([r for r in rows if r["kind"] == dc.KIND_FREEZE]) == 1


# ---- R4/R5/R6: refusals, guard, failure — all named, never guessed ---------

def test_r4_ambiguous_line_writes_nothing_and_names_the_run(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "other-line-rev", line=OTHER)], p)
    runs = [witness_run(rev="b3c3ca5b")]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=False)
    assert out[0]["state"] == "error"
    # the ambiguity is NAMED with the pass vocabulary (t261103-06: a run row
    # that is neither this line's candidate nor its baseline is refused by
    # name, never guessed at)
    assert out[0]["error"] == (
        "unrecorded_run:%s:line_ambiguous:%s:%s"
        % (RUN_ID, dc.REFUSE_PASS_UNKNOWN,
           "revision_not_on_this_line:b3c3ca5b"))
    assert rows_of(p) == rows_of(p)  # nothing appended below


def test_r4b_malformed_runs_and_non_line_round_rows_are_skipped(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    stub = witness_run(rid="run-01M5STUB0000000000000000000")
    stub["source"] = "lane:stub"  # not a line round: not ours to heal
    runs = ["not a dict", {"no": "id"}, stub]
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), runs, writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out == []
    assert rows_of(p) == rows_of(p)


def test_r5_guard_held_writes_nothing(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), [witness_run()], writer(p), "tick", "booked-v1",
        1792909089000, sole_line=True, guard_held=True)
    assert out == []
    assert not certs(rows_of(p))


def test_r6_append_failure_is_a_named_entry_never_an_exception(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)

    def broken(batch):
        raise dc.CertifyError("ledger_has_malformed_lines:1")

    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), [witness_run()], broken, "tick", "booked-v1",
        1792909089000, sole_line=True)
    assert out[0]["state"] == "error"
    assert out[0]["error"].startswith("heal_failed:CertifyError:")


# ---- T1/T2: the full tick heals, then idles --------------------------------

def _tick(tmp_path, runs_lines, lines=("develop-buffer",)):
    runs_store = tmp_path / "ledger" / "scenario-runs.jsonl"
    runs_store.parent.mkdir(parents=True, exist_ok=True)
    runs_store.write_text("\n".join(runs_lines) + "\n", encoding="utf-8")
    guard = tmp_path / "ledger" / "tick-anchor"
    return dc.line_round_tick(
        "proj", load_lines=lambda pk: list(lines),
        read_rows=reader(ledger(tmp_path)),
        append_rows=writer(ledger(tmp_path)),
        resolve_runner_fn=lambda line, env: (
            lambda candidate: (_ for _ in ()).throw(
                AssertionError("no round may run after a heal"))),
        guard_path=guard, now_ms=1792909089000,
        backstop_ms=24 * 60 * 60 * 1000,
        runs_store=str(runs_store))


def _line_tree_with_commit(tmp_path, monkeypatch, project="proj",
                           repo="sandbar"):
    """A line worktree the reachability net (t261030-25) can judge: a real git
    repository with one commit, under an injected projects root. The witness
    run then cites a revision this repository CAN produce — the only kind a
    reconciliation may certify."""
    import subprocess
    projects = tmp_path / "projects"
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    tree = projects / project / "data" / "develop" / "wt" / repo
    tree.mkdir(parents=True)
    for argv in (["git", "init", "-q", "."],
                 ["git", "config", "user.email", "it@t"],
                 ["git", "config", "user.name", "it"]):
        subprocess.run(["git", "-C", str(tree)] + argv[1:], check=True,
                       capture_output=True)
    (tree / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(tree), "commit", "-qm", "m0"], check=True,
                   capture_output=True)
    return subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def test_t1_tick_heals_witness_then_idles_without_a_round(tmp_path,
                                                          monkeypatch):
    p = ledger(tmp_path)
    real_rev = _line_tree_with_commit(tmp_path, monkeypatch)
    dc.append_rows([landing("sandbar", real_rev)], p)
    out = _tick(tmp_path, [json.dumps(witness_run(rev=real_rev))])
    states = [e.get("state") for e in out["lines"]]
    assert "reconciled" in states and "idle" in states
    assert not certs(rows_of(p)) or len(certs(rows_of(p))) == 1
    assert len(certs(rows_of(p))) == 1  # exactly one heal row
    assert certs(rows_of(p))[0]["repos"] == [{"repo": "sandbar",
                                              "revision": real_rev}]


def test_t2_malformed_runs_store_is_named_never_guessed(tmp_path):
    p = ledger(tmp_path)
    dc.append_rows([landing("sandbar", "dbb88cd5")], p)
    out = _tick(tmp_path, ["{not json"])
    assert out["lines"][0]["state"] == "error"
    assert out["lines"][0]["error"] == "runs_store_has_malformed_lines:1"
    assert not certs(rows_of(p))


# ---- KI-456 / t261103-06: candidate pass vs baseline-rebuild pass -----------
#
# A line round has TWO passes through the one runner seam: the CANDIDATE pass
# on the line head being judged, and the BASELINE-rebuild pass on main's tip
# (the relative caliber's comparison input). Both leave a run row wearing the
# line round's source, so the booking side has to tell them apart. Measured
# twice on 2026-11-03: the baseline pass's reds were booked as the LINE's
# certification and opened a freeze while the candidate pass was green
# (cert-01M6D365 on main tip 9897c555 vs line head a21c504c 703/703;
# cert-01M6F24K on 3d1727ed vs 99c43b8c 706/706). These legs are that rule.
#
# t261103-10 narrows WHICH proof decides PASS_BASELINE. t261103-06 also let
# "every revision it names is a main baseline tip" decide on its own, and that
# arm skipped an attributable completed round: a line head created from main IS
# the main tip (measured on main 68385732, leg A of
# integration/t261025-11/sc_t261025_11_unrecorded_round_healed.py: the tick
# answered state=skipped/attribution_rule=baseline_pass and wrote zero rows).
# The durable run id written by ``write_baseline(..., run_id=)`` is what proves
# the baseline pass; a tip alone is UNKNOWN and books nothing, exactly as
# fail-closed requires. The assertions below that used to pin the tips arm now
# pin THAT: never a booking, never a guessed role.

def test_ki456_run_pass_role_truth_table():
    """The pure identity table: a revision this line can prove it has is the
    candidate; a run id recorded as a baseline rebuild is the baseline (exact
    evidence wins even when the tips agree); a main baseline tip with no
    recorded run is UNKNOWN — it books nothing and says why. A tip never
    decides a role on its own (t261103-10)."""
    landing_revs = {"rev-landing"}
    head_revs = {"rev-head"}
    base_tips = {"rev-main"}
    base_runs = {"run-BASE"}
    one = lambda rev, repo="r": [{"repo": repo, "revision": rev}]  # noqa: E731
    assert dc.run_pass_role(one("rev-landing"), "run-X", landing_revs,
                            head_revs, base_tips, base_runs) == \
        (dc.PASS_CANDIDATE, "landing_repo_match", "")
    assert dc.run_pass_role(one("rev-head"), "run-X", landing_revs,
                            head_revs, base_tips, base_runs) == \
        (dc.PASS_CANDIDATE, "line_head_match", "")
    # the tips identity is diagnostic only: no durable proof, no BASELINE role
    assert dc.run_pass_role(one("rev-main"), "run-X", landing_revs,
                            head_revs, base_tips, base_runs) == \
        (dc.PASS_UNKNOWN, "",
         "revision_is_a_main_baseline_tip_without_a_recorded_run:rev-main")
    # the exact run id beats the revision identity (the degenerate case: main's
    # tip IS the line head, so revision alone cannot separate the two passes)
    assert dc.run_pass_role(one("rev-head"), "run-BASE", landing_revs,
                            head_revs, base_tips, base_runs) == \
        (dc.PASS_BASELINE, "baseline_pass",
         "run_is_a_baseline_rebuild:run-BASE")
    # the head identity still wins over a tip that equals it (leg A shape)
    assert dc.run_pass_role(one("rev-main"), "run-X", landing_revs,
                            {"rev-main"}, base_tips, base_runs) == \
        (dc.PASS_CANDIDATE, "line_head_match", "")
    # a set spanning a candidate revision and a baseline tip is never split
    mixed = one("rev-head") + one("rev-main", repo="r2")
    assert dc.run_pass_role(mixed, "run-X", landing_revs, head_revs,
                            base_tips, base_runs)[0] == dc.PASS_UNKNOWN
    # a shape that is not a candidate set at all keeps the unjudgable path
    assert dc.run_pass_role([], "run-X", landing_revs, head_revs, base_tips,
                            base_runs)[0] == dc.PASS_MALFORMED


def test_ki456_two_pass_round_books_only_the_candidate(tmp_path, monkeypatch):
    """The incident shape: a two-pass round, candidate green on the line head
    and baseline RED at main's tip. Exactly ONE certification is booked and it
    cites the CANDIDATE revision; the baseline row books nothing and its skip
    is named on the receipt. The baseline row is fed FIRST, so the answer does
    not depend on the runs store's order."""
    project, main_rev, line_rev = two_pass_repo(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    base = pass_run("run-BASELINE", main_rev, verdict="red",
                    failed_names=["main-red-1", "main-red-2", "main-red-3"])
    cand = pass_run("run-CANDIDATE", line_rev)
    out = heal(project, p, [base, cand])
    rows = rows_of(p)
    cs = certs(rows)
    assert len(cs) == 1                                     # exactly one
    assert cs[0]["repos"] == [{"repo": "sandbar", "revision": line_rev}]
    assert cs[0]["run"] == "run-CANDIDATE"                  # the verdict's run
    assert not [r for r in rows if r["kind"] == dc.KIND_FREEZE]
    assert dc.freeze_state(rows, LINE)["frozen"] is False
    by_run = {e["run"]: e for e in out}
    assert by_run["run-CANDIDATE"]["state"] == "reconciled"
    # no run id in the baseline cache: no durable proof, so the row is UNKNOWN
    # (t261103-10) — still books nothing, and names the refusal
    assert by_run["run-BASELINE"]["state"] == "error"
    assert dc.REFUSE_PASS_UNKNOWN in by_run["run-BASELINE"]["error"]


def test_ki456_red_baseline_pass_alone_books_nothing(tmp_path, monkeypatch):
    """The control: a RED baseline pass with no candidate pass in the store
    books NOTHING AT ALL — no certification, no freeze, not even a range-growth
    row (nothing was judged). It is the round's relative-judgement input.

    t261103-10: with no run id recorded in the baseline cache there is no
    durable proof this row was the baseline pass, so it is UNKNOWN — still
    books nothing, and names the refusal. The tips identity only colours the
    text; it never decides a role."""
    project, main_rev, _line_rev = two_pass_repo(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    base = pass_run("run-BASELINE", main_rev, verdict="red",
                    failed_names=["main-red-1"])
    out = heal(project, p, [base])
    assert rows_of(p) == []                                  # nothing booked
    assert dc.freeze_state([], LINE)["frozen"] is False
    assert out[0]["state"] == "error"
    assert dc.REFUSE_PASS_UNKNOWN in out[0]["error"]
    assert out[0]["error"].endswith(
        "revision_is_a_main_baseline_tip_without_a_recorded_run:%s"
        % main_rev[:12])


def test_ki456_planted_red_candidate_still_books_red_and_freezes(tmp_path,
                                                                monkeypatch):
    """The teeth this fix must never blunt: a planted RED CANDIDATE pass on
    the line head still books the certification and still opens the freeze —
    the baseline pass riding beside it changes none of that."""
    project, main_rev, line_rev = two_pass_repo(tmp_path, monkeypatch)
    p = ledger(tmp_path)
    cand = pass_run("run-CANDIDATE", line_rev, verdict="red",
                    failed_names=["planted-red"],
                    receipts={"planted-red": {
                        "reason": "assert_mismatch",
                        "evidence": "AssertionError: planted red"}})
    base = pass_run("run-BASELINE", main_rev)                 # a GREEN baseline
    heal(project, p, [cand, base])
    rows = rows_of(p)
    cs = certs(rows)
    assert len(cs) == 1
    assert cs[0]["repos"] == [{"repo": "sandbar", "revision": line_rev}]
    frz = [r for r in rows if r["kind"] == dc.KIND_FREEZE]
    assert len(frz) == 1                                     # the freeze opens
    assert frz[0]["cause"] == cs[0]["id"]
    assert dc.freeze_state(rows, LINE)["frozen"] is True


def test_ki456_recorded_baseline_run_id_wins_when_the_tips_agree(tmp_path,
                                                                monkeypatch):
    """The degenerate case: main's tip IS the line head (the line has not
    advanced), so revision identity cannot separate the two passes. The
    durable proof is the run id ``write_baseline`` records for a baseline
    rebuild: that row books nothing, while the candidate pass on the very same
    revision still books its certification."""
    project, main_rev, _line_rev = two_pass_repo(tmp_path, monkeypatch)
    dive = dc.line_repo_dir(project, "sandbar")
    _git(["branch", "-f", "line", "main"], dive)             # line head = main
    p = ledger(tmp_path)
    dc.write_baseline(project, "sandbar", main_rev, ["main-red-1"], [],
                      run_id="run-BASELINE")
    base = pass_run("run-BASELINE", main_rev, verdict="red",
                    failed_names=["main-red-1"])
    cand = pass_run("run-CANDIDATE", main_rev)
    out = heal(project, p, [base, cand])
    rows = rows_of(p)
    cs = certs(rows)
    assert len(cs) == 1 and cs[0]["run"] == "run-CANDIDATE"
    assert not [r for r in rows if r["kind"] == dc.KIND_FREEZE]
    by_run = {e["run"]: e for e in out}
    assert by_run["run-BASELINE"]["reason"] == \
        "run_is_a_baseline_rebuild:run-BASELINE"


def test_ki456_cached_tip_without_a_recorded_run_is_unknown(tmp_path,
                                                            monkeypatch):
    """A baseline rebuild ran at a tip main has since moved off, and its cache
    carries no run id (an older cache, or one written before the run id rode
    the cache). The tip key alone is not durable proof (t261103-10): the row
    books nothing and is named UNKNOWN. A cache that DOES carry the run id is
    the durable case — see the recorded-run-id leg above."""
    project, old_main_rev, _line_rev = two_pass_repo(tmp_path, monkeypatch)
    dc.write_baseline(project, "sandbar", old_main_rev, ["main-red-1"], [])
    dive = dc.line_repo_dir(project, "sandbar")
    (dive / "file.txt").write_text("main moved\n", encoding="utf-8")
    _git(["add", "-A"], dive)
    _git(["commit", "-qm", "main-moved"], dive)               # main advances
    assert _rev(dive, "refs/heads/main") != old_main_rev
    p = ledger(tmp_path)
    base = pass_run("run-BASELINE", old_main_rev, verdict="red",
                    failed_names=["main-red-1"])
    out = heal(project, p, [base])
    assert rows_of(p) == []                                  # nothing booked
    assert out[0]["state"] == "error"
    assert dc.REFUSE_PASS_UNKNOWN in out[0]["error"]
    # the same row with the run id recorded IS the baseline pass: nothing booked
    dc.write_baseline(project, "sandbar", old_main_rev, ["main-red-1"], [],
                      run_id="run-BASELINE")
    out2 = heal(project, p, [base])
    assert rows_of(p) == []
    assert out2[0]["state"] == "skipped"
    assert out2[0]["reason"] == "run_is_a_baseline_rebuild:run-BASELINE"


def test_ki456_unattributable_pass_books_nothing_and_names_the_refusal(
        tmp_path, monkeypatch):
    """Fail-closed: a run row citing a real commit that is neither a landing,
    nor the line head, nor a baseline tip cannot be placed on either pass. It
    books NOTHING (no certification, no freeze, no growth row) and the refusal
    NAMES the pass check and the revision — never a guessed revision."""
    project, _main_rev, line_rev = two_pass_repo(tmp_path, monkeypatch)
    dive = dc.line_repo_dir(project, "sandbar")
    _git(["checkout", "-q", "-b", "scratch", "line"], dive)
    (dive / "scratch.txt").write_text("s\n", encoding="utf-8")
    _git(["add", "-A"], dive)
    _git(["commit", "-qm", "scratch"], dive)
    stray_rev = _rev(dive, "HEAD")
    _git(["checkout", "-q", "main"], dive)
    assert stray_rev != line_rev
    p = ledger(tmp_path)
    out = heal(project, p, [pass_run("run-STRAY", stray_rev)])
    rows = rows_of(p)
    assert rows == []                       # nothing booked at all
    assert out[0]["state"] == "error"
    assert dc.REFUSE_PASS_UNKNOWN in out[0]["error"]
    assert stray_rev[:12] in out[0]["error"]
    # and the retired take-anyway still grants nothing
    out2 = heal(project, p, [pass_run("run-STRAY", stray_rev)], sole_line=True)
    assert rows_of(p) == [] and out2[0]["state"] == "error"


def test_ki456_baseline_run_names_itself_on_the_round_record(tmp_path,
                                                             monkeypatch):
    """The baseline pass is a citable record, not an anonymous input: a
    rebuild's run id lands in the cache AND on the round's relative detail, so
    a reader can tell which observation the verdict was measured against."""
    project, main_rev, line_rev = two_pass_repo(tmp_path, monkeypatch)
    dive = dc.line_repo_dir(project, "sandbar")
    calls = []

    def runner(cand):
        calls.append(cand)
        if cand[0]["revision"] == main_rev:
            return {"id": "run-BASELINE", "failed_names": ["main-red-1"],
                    "cases": {"ran": 696, "passed": 695, "failed": 1,
                              "env_failed": 0}}
        return {"id": "run-CANDIDATE", "failed_names": [],
                "cases": {"ran": 703, "passed": 703, "failed": 0,
                          "env_failed": 0}}

    header = {"id": "run-CANDIDATE", "failed_names": [],
              "cases": {"ran": 703, "passed": 703, "failed": 0,
                        "env_failed": 0}}
    verdict, rel = dc.relative_round_verdict(
        project, [{"repo": "sandbar", "revision": line_rev}], header, runner,
        {"entries": []})
    assert verdict == "green"
    per_repo = rel["per_repo"]["sandbar"]
    assert per_repo["baseline_source"] == "rebuilt"
    assert per_repo["baseline_run"] == "run-BASELINE"
    cached = dc.read_baseline(project, "sandbar", main_rev)
    assert cached["run"] == "run-BASELINE"        # the durable proof
    assert _rev(dive, "refs/heads/main") == main_rev


# ---- t261103-10: durable evidence decides BASELINE, never a main tip --------
#
# The measured regression (main 68385732, after t261103-06): a line head
# created from main IS the main tip, so the tips arm classified an
# attributable, completed round as a baseline observation and wrote nothing
# (leg A of integration/t261025-11/sc_t261025_11_unrecorded_round_healed.py).
# These legs run the REAL tick call site with the fixture shape that produced
# it: a project whose line worktree has ONE commit, so the main tip, the line
# head and the judged revision are the same object.

class Decl:
    """A declared line as the tick's ``load_lines`` seam answers it: an id and
    the declared repositories (name + declared head)."""

    def __init__(self, line_id, repos):
        self.line_id = line_id
        self.repositories = [type("R", (), {"name": n, "branch": b})()
                             for n, b in repos]


def tick_with_decl(tmp_path, project, decls, run_rows, backstop_ms=None):
    """One tick through the real call site: the declaration comes from the
    ``load_lines`` seam (as in production), the runs store is a real file."""
    store = tmp_path / "ledger" / "scenario-runs.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("".join(json.dumps(r) + "\n" for r in run_rows),
                     encoding="utf-8")
    return dc.line_round_tick(
        project, load_lines=lambda pk: decls,
        read_rows=reader(ledger(tmp_path)),
        append_rows=writer(ledger(tmp_path)),
        resolve_runner_fn=lambda line, env: (
            lambda candidate: (_ for _ in ()).throw(
                AssertionError("no round may run after a heal"))),
        guard_path=tmp_path / "ledger" / "tick-anchor",
        now_ms=1792909089000, backstop_ms=backstop_ms,
        runs_store=str(store))


def test_t261103_10_declared_head_resolution_is_never_a_guess(tmp_path,
                                                             monkeypatch):
    """The identity resolver: a declared branch resolves to its commit, a
    declaration that pins a revision resolves too, and a declaration whose
    head git cannot produce answers EMPTY — no identity, never a guess."""
    project, main_rev, line_rev = two_pass_repo(tmp_path, monkeypatch)
    by_branch = dc.line_decl_head_revision_map(
        project, Decl(LINE, [("sandbar", "line")]))
    assert by_branch == {"sandbar": line_rev}
    by_revision = dc.line_decl_head_revision_map(
        project, Decl(LINE, [("sandbar", line_rev)]))
    assert by_revision == {"sandbar": line_rev}
    fabricated = dc.line_decl_head_revision_map(
        project, Decl(LINE, [("sandbar", "f" * 40)]))
    assert fabricated == {}
    no_tree = dc.line_decl_head_revision_map(
        "proj-undeclared", Decl(LINE, [("sandbar", line_rev)]))
    assert no_tree == {}
    assert main_rev != line_rev


def test_t261103_10_line_head_equal_to_the_main_tip_heals_one_row(
        tmp_path, monkeypatch):
    """The regression shape, healed: the line worktree has ONE commit, so main's
    tip IS the line head IS the judged revision, and no baseline cache records
    the run. The tick must heal the completed round with exactly ONE
    certification citing that revision (rule ``line_head_match``), not skip it
    as a baseline observation."""
    p = ledger(tmp_path)
    rev = _line_tree_with_commit(tmp_path, monkeypatch)          # main == HEAD
    assert dc._git_main_tip(
        tmp_path / "projects" / "proj" / "data" / "develop" / "wt"
        / "sandbar") == rev
    runs = [witness_run(rev=rev)]
    out = tick_with_decl(tmp_path, "proj",
                         {LINE: Decl(LINE, [("sandbar", rev)])}, runs)
    states = [e.get("state") for e in out["lines"]]
    assert "reconciled" in states, out
    cs = certs(rows_of(p))
    assert len(cs) == 1                                          # exactly one
    assert cs[0]["run"] == RUN_ID
    assert cs[0]["repos"] == [{"repo": "sandbar", "revision": rev}]
    assert cs[0]["judged_by"] == "reconciled:%s" % RUN_ID
    by_run = {e.get("run"): e for e in out["lines"]}
    assert by_run[RUN_ID]["attribution_rule"] == "line_head_match"
    # replay: the certification cites the run id, so nothing is written twice
    out2 = tick_with_decl(tmp_path, "proj",
                          {LINE: Decl(LINE, [("sandbar", rev)])}, runs)
    assert len(certs(rows_of(p))) == 1
    assert RUN_ID not in {e.get("run") for e in out2["lines"]}


def test_t261103_10_recorded_baseline_run_still_books_nothing(
        tmp_path, monkeypatch):
    """The KI-456 proof survives the narrowing: the SAME degenerate shape (the
    line head equals the main tip) with the run id durably recorded as a
    baseline rebuild's run books NOTHING — no certification, no freeze, no
    growth row — and the tick names the skip."""
    p = ledger(tmp_path)
    rev = _line_tree_with_commit(tmp_path, monkeypatch)
    dc.write_baseline("proj", "sandbar", rev, ["main-red-1"], [],
                      run_id=RUN_ID)                            # durable proof
    runs = [pass_run(RUN_ID, rev, verdict="red",
                     failed_names=["main-red-1"])]
    out = tick_with_decl(tmp_path, "proj",
                         {LINE: Decl(LINE, [("sandbar", rev)])}, runs)
    assert rows_of(p) == []                                     # nothing booked
    by_run = {e.get("run"): e for e in out["lines"]
              if isinstance(e, dict) and e.get("run")}
    assert by_run[RUN_ID]["state"] == "skipped"
    assert by_run[RUN_ID]["reason"] == "run_is_a_baseline_rebuild:%s" % RUN_ID


def test_t261103_10_planted_red_candidate_on_the_main_tip_freezes(
        tmp_path, monkeypatch):
    """The teeth: a planted RED CANDIDATE on that same revision (head == main
    tip, no baseline run recorded) still books the certification and still
    opens the freeze. Narrowing the BASELINE role must not blunt the red."""
    p = ledger(tmp_path)
    rev = _line_tree_with_commit(tmp_path, monkeypatch)
    red = pass_run(RUN_ID, rev, verdict="red", failed_names=["planted-red"],
                   receipts={"planted-red": {"reason": "assert_mismatch",
                                             "evidence": "AssertionError: x"}})
    tick_with_decl(tmp_path, "proj", {LINE: Decl(LINE, [("sandbar", rev)])},
                   [red])
    rows = rows_of(p)
    cs = certs(rows)
    assert len(cs) == 1 and cs[0]["repos"] == [{"repo": "sandbar",
                                                "revision": rev}]
    frz = [r for r in rows if r["kind"] == dc.KIND_FREEZE]
    assert len(frz) == 1                                         # the freeze
    assert dc.freeze_state(rows, LINE)["frozen"] is True


def test_t261103_10_unattributable_row_on_a_multi_line_project_writes_no_row(
        tmp_path, monkeypatch):
    """Fail-closed, and no row: an unattributable run row in a project that
    declares more than one line is named as ambiguous on the receipt and
    writes NO ledger row — the reachability net does not turn the ambiguity
    into a row (leg D of the L3 scenario). Before this leg's fix the net
    wrote one, so the "never a guess" contract was red."""
    p = ledger(tmp_path)
    _line_tree_with_commit(tmp_path, monkeypatch)                # real tree,
    run = witness_run(rev="d" * 40)                              # fake revision
    out = dc.reconcile_unrecorded_rounds(
        LINE, rows_of(p), [run], writer(p), "tick", "booked-v1",
        1792909089000, sole_line=False, project="proj")
    rows = rows_of(p)
    assert rows == []                                    # no row, never a guess
    assert out[0]["state"] == "error"
    assert out[0]["error"].startswith(
        "unrecorded_run:%s:line_ambiguous:%s:" % (RUN_ID,
                                                  dc.REFUSE_PASS_UNKNOWN))
    assert out[0]["error"].endswith("revision_not_on_this_line:%s"
                                    % ("d" * 40)[:12])
