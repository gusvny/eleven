"""t261019-23: the line-landed close-out fence lives in the merge activity.

261019: the fence was written in workflow code, the Temporal sandbox refused its ledger read
(RestrictedWorkflowAccessError), every close-out blocked, and because workflow.patched() never
turns true for a history created before the patch, in-flight tickets could only be rescued by
cancelling and re-opening them.

The fence now lives in agent_activities.merge (activity code, no sandbox): it answers from the
project ledgers alone, so it needs no new workflow input and fences old histories too. The pure
decision (dev_lane.line_landing_closeout_verdict) is unchanged and still the scenario face.

t261103-23 (measured, project-vision 2026-11-03): the fence answered by scanning EVERY project's
ledger, so a SANDBAR landing of a same-named ticket was read as the project-vision ticket's own
landing, and the copy offered "withdraw the landing first" - a human would have destroyed
another project's record. The fence now judges the ledger of the ticket's OWN project (the
project key the merge activity resolves from meta.project) and refuses by name when that key
cannot be resolved; the collision copy never suggests withdrawing a foreign landing. Because the
fence reads one project, this battery builds temp project roots: nothing here touches the real
~/.sandbar store any more (the previous two cases read the host store).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_activities as aa  # noqa: E402

COLLIDING = "t261103-03"   # the id the two projects both used (measured incident)


# --------------------------------------------------------------- fixtures

def _landing(lid, ticket, line):
    """One landing row of the append-only record contract (kind/ticket/line/id are
    all this fence reads)."""
    return {"kind": "landing", "id": lid, "ticket": ticket, "line": line,
            "actor": "ut", "at": 1000,
            "repos": [{"repo": "r", "revision": "0" * 40}]}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Two projects with their OWN delivery ledgers under a temp projects root:
    the exact production layout (<root>/<project>/ledger/delivery.jsonl), mirrored
    into tmp so the battery is hermetic. The flat-ledger override is cleared so the
    per-project store is what both reader and writer resolve."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.delenv("SANDBAR_DELIVERY_LEDGER_DIR", raising=False)
    root = tmp_path / "projects"
    for key in ("sandbar", "project-vision"):
        (root / key / "data" / "develop").mkdir(parents=True)
        (root / key / "ledger").mkdir(parents=True)
    aa._LANDING_CLOSEOUT_PROJECT_KEY.clear()
    yield root
    aa._LANDING_CLOSEOUT_PROJECT_KEY.clear()


def _write(root, key, rows):
    path = root / key / "ledger" / "delivery.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# ------------------------------- same project: the landing IS this ticket's

def test_refuses_a_ticket_that_already_landed_and_names_project_ledger_landing(store):
    """A hit in the ticket's own ledger is its own landing: refuse, and name the
    project, the ledger file and the landing id so the reader never has to guess."""
    ledger = _write(store, "sandbar", [_landing("ldg-AAA", COLLIDING, "develop-buffer")])
    verdict = aa._line_landing_closeout_refusal_for(COLLIDING, "sandbar")
    assert "close-out refused by host ruling 261019" in verdict
    assert "develop-buffer" in verdict
    assert "landing ldg-AAA" in verdict
    assert "project 'sandbar'" in verdict
    assert str(ledger) in verdict
    # the same-project hit IS a landing this project may undo, so the lawful way out
    # that withdraws it stays on the copy (the 261019 ruling's original text)
    assert "withdraw this project's own landing first" in verdict


def test_allows_a_ticket_with_no_landing(store):
    _write(store, "sandbar", [_landing("ldg-AAA", "t261019-not-a-real-ticket",
                                       "develop-buffer")])
    assert aa._line_landing_closeout_refusal_for("t261019-other", "sandbar") == ""


def test_a_malformed_ledger_is_refused_by_name(store):
    path = store / "sandbar" / "ledger" / "delivery.jsonl"
    path.write_text('{"kind": "landing", "ticket": "x"\n', encoding="utf-8")
    verdict = aa._line_landing_closeout_refusal_for(COLLIDING, "sandbar")
    assert "malformed line" in verdict and str(path) in verdict


# ------------------- cross project (t261103-23): never this ticket's landing

def test_a_same_named_ticket_landed_in_ANOTHER_project_does_not_refuse(store):
    """Regression (i) of t261103-23, close-out side: sandbar landed an id that the
    project-vision ticket also carries. The project-vision close-out reads ITS OWN ledger,
    finds nothing, and proceeds - the foreign row is invisible, not a duplicate."""
    _write(store, "sandbar", [_landing("ldg-AAA", COLLIDING, "develop-buffer")])
    _write(store, "project-vision", [])
    assert aa._line_landing_closeout_refusal_for(COLLIDING, "project-vision") == ""


def test_an_unresolvable_key_is_refused_by_name_with_the_collision_named(store):
    """The measured fault shape: the ticket's own key could not be resolved. The
    fence must not read every project's ledger as this ticket's, must not pass, and
    must not suggest withdrawing the foreign landing - it names it as a collision and
    gives the two lawful remedies."""
    ledger = _write(store, "sandbar", [_landing("ldg-BBB", COLLIDING, "develop-buffer")])
    verdict = aa._line_landing_closeout_refusal_for(COLLIDING)
    assert verdict, "an unresolvable project key must refuse the close-out, never pass"
    assert "could not be resolved" in verdict
    assert "project 'sandbar'" in verdict and str(ledger) in verdict
    assert "landing ldg-BBB" in verdict
    assert "id-scheme collision" in verdict
    assert "NOT this ticket's landing" in verdict
    assert "never a landing to undo" in verdict
    assert "do not withdraw it" in verdict
    # the same-project remedy (withdraw) must NOT be offered for a foreign landing
    assert "withdraw this project's own landing first" not in verdict
    assert "Ways out: let the line round certify it" not in verdict
    # the lawful remedies, spelled out
    assert "own project key" in verdict and "re-issue this work under a non-colliding id" in verdict


def test_an_unresolvable_key_with_no_collision_says_so_by_name(store):
    _write(store, "sandbar", [])
    _write(store, "project-vision", [])
    verdict = aa._line_landing_closeout_refusal_for(COLLIDING)
    assert "could not be resolved" in verdict
    assert "no project ledger holds a landing for this id" in verdict
    assert "withdraw" not in verdict


def test_the_callers_key_handoff_is_used_and_consumed_once(store):
    """The merge activity resolves meta.project and primes the handoff; the fence
    consumes it, so a later call cannot be steered by a stale key."""
    _write(store, "sandbar", [_landing("ldg-CCC", COLLIDING, "develop-buffer")])
    aa._LANDING_CLOSEOUT_PROJECT_KEY[COLLIDING] = "sandbar"
    first = aa._line_landing_closeout_refusal_for(COLLIDING)
    assert "close-out refused by host ruling 261019" in first
    assert "landing ldg-CCC" in first
    assert aa._LANDING_CLOSEOUT_PROJECT_KEY == {}
    second = aa._line_landing_closeout_refusal_for(COLLIDING)
    assert "could not be resolved" in second, "the consumed key must not linger"


def test_a_malformed_project_key_is_refused_by_name(store):
    verdict = aa._line_landing_closeout_refusal_for(COLLIDING, "../escape")
    assert "malformed project key" in verdict and "../escape" in verdict


def test_empty_ticket_id_is_refused_by_name():
    assert "needs a ticket id" in aa._line_landing_closeout_refusal_for("  ")


# ------------------------------------------------- call-site / workflow shape

def test_the_merge_activity_resolves_the_project_key_before_the_fence():
    """t261103-23: the fence is judged over the ticket's own project ledger, so the
    activity resolves meta.project FIRST and hands it over. The call shape stays
    (the registered scenario anchors it); the handoff line must precede it."""
    src = Path(aa.__file__).read_text()
    body = src[src.index("async def merge(args: MergeArgs)"):]
    fetch = body.index("_fetch_ticket_project(args.ticket_id)")
    prime = body.index("_LANDING_CLOSEOUT_PROJECT_KEY[args.ticket_id] = project_key")
    fence = body.index("_line_landing_closeout_refusal_for(args.ticket_id)")
    assert fetch < prime < fence


def test_the_merge_activity_checks_before_any_squash():
    src = Path(aa.__file__).read_text()
    body = src[src.index("async def merge(args: MergeArgs)"):]
    body = body[:body.index("_squash_merge(")]
    assert "_line_landing_closeout_refusal_for(args.ticket_id)" in body, \
        "the fence must run before the first _squash_merge call"


def test_the_workflow_no_longer_reads_the_ledger():
    """The in-workflow guard call is gone: replay of an old history must not touch the
    ledger (that read is what the sandbox refuses)."""
    src = (Path(__file__).resolve().parents[1] / "dev_lane.py").read_text()
    marker = "the line-landed close-out fence now"
    assert marker in src
    assert "await self._line_landing_closeout_guard()" not in src
