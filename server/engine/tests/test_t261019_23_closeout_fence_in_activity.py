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

t261103-25 (follow-up, measured by the multirepo merge-gate scenario at 7 pass / 6 fail): a
keyless caller was refused even when nothing had landed anywhere, which broke a legitimate
close-out. The keyless branch now refuses only where the risk exists - a landing for this id in
ANY project's ledger - and otherwise proceeds as before t261103-23 while the receipt says the key
was unresolved and no ledger holds the id. The tail of this file carries that ticket's cases.
"""
import asyncio
import json
import subprocess
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
    aa._LANDING_CLOSEOUT_KEYLESS_NOTE.clear()
    yield root
    aa._LANDING_CLOSEOUT_PROJECT_KEY.clear()
    aa._LANDING_CLOSEOUT_KEYLESS_NOTE.clear()


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


def test_an_unresolvable_key_with_no_collision_anywhere_proceeds(store):
    """t261103-25 reverses what t261103-23 made this case assert. A keyless caller
    with NO landing for its id in any project's ledger has nothing to misattribute,
    so the close-out proceeds (the pre-t261103-23 behaviour) instead of being
    refused, and the reason travels on the receipt note."""
    _write(store, "sandbar", [])
    _write(store, "project-vision", [])
    assert aa._line_landing_closeout_refusal_for(COLLIDING) == ""
    note = aa._LANDING_CLOSEOUT_KEYLESS_NOTE.get(COLLIDING, "")
    assert "could not be resolved" in note
    assert "no ledger anywhere holds a landing for this id" in note
    assert "withdraw" not in note


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


# =============================================================================
# t261103-25 — KEYLESS CLOSE-OUT: REFUSE ONLY WHERE THE RISK EXISTS
# (added to this anchored battery so no new test file / anchor entry is needed;
#  a clearly marked section, its own helpers, the same temp project store)
#
# Measured (scenario t260907-06-multirepo-merge-gate, 7 pass / 6 fail on 74b1938c):
# t261103-23's fail-closed guard refused a caller whose own project key genuinely
# cannot be resolved, even when NO project's delivery ledger held a landing for the
# id - a shape with nothing to misattribute (a fixture / legacy caller). The rule
# now: with an unresolvable key, look for a landing of this id in ANY project's
# ledger. A hit anywhere refuses BY NAME (the collision copy, unchanged in what it
# accuses); no hit anywhere proceeds on the pre-t261103-23 path and the receipt
# says the key was unresolved and that no ledger holds the id. No path here writes
# a ledger - the scan is read-only, and the close-out's only write is the squash
# commit in the ticket's own repos.
# =============================================================================

KEYLESS = "t261103-25-keyless"     # an id that no project's ledger mentions


def _store_bytes(root):
    """Every file under the temp projects store, byte for byte: the foreign-ledger
    claim is checked against this map, not against a re-read of one path."""
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_keyless_note_is_one_shot_and_never_rides_a_later_judgement(store):
    """The receipt note is handed over exactly like the key: set by the call that
    judged, consumed once, and cleared at the top of the next call for that id, so a
    stale note can never explain a close-out it did not decide."""
    _write(store, "sandbar", [])
    assert aa._line_landing_closeout_refusal_for(KEYLESS) == ""
    assert KEYLESS in aa._LANDING_CLOSEOUT_KEYLESS_NOTE
    aa._LANDING_CLOSEOUT_KEYLESS_NOTE.pop(KEYLESS)          # what merge() does
    _write(store, "sandbar", [_landing("ldg-ZZZ", KEYLESS, "develop-buffer")])
    assert aa._line_landing_closeout_refusal_for(KEYLESS), "the collision must refuse"
    assert KEYLESS not in aa._LANDING_CLOSEOUT_KEYLESS_NOTE, \
        "a refused judgement must not leave a proceed-note behind"


def test_an_unreadable_ledger_is_not_evidence_of_absence(store):
    """The keyless scan may only answer "nothing landed anywhere" from ledgers it
    actually read. One corrupt ledger among the candidates refuses by name: the
    fence never reads an unreadable record as an absent one, and writes nothing."""
    _write(store, "project-vision", [])
    corrupt = store / "sandbar" / "ledger" / "delivery.jsonl"
    corrupt.write_text('{"kind": "landing", "ticket": "x"\n', encoding="utf-8")
    verdict = aa._line_landing_closeout_refusal_for(KEYLESS)
    assert verdict, "an unreadable ledger must refuse, never pass as 'nothing landed'"
    assert "could not be resolved" in verdict
    assert "could not be read" in verdict and str(corrupt) in verdict
    assert "no ledger anywhere holds a landing" not in verdict
    assert KEYLESS not in aa._LANDING_CLOSEOUT_KEYLESS_NOTE


# ------------------------------ the receipt and the booking, end to end

def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


@pytest.fixture()
def keyless_lane(tmp_path, monkeypatch):
    """A real single-repo project with a real lane worktree, and a caller whose own
    project key cannot be resolved (the shape the failing scenario drives). The temp
    projects store carries two projects whose ledgers must come out byte-identical:
    one already landed an UNRELATED ticket id."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.delenv("SANDBAR_DELIVERY_LEDGER_DIR", raising=False)
    monkeypatch.delenv("SANDBAR_SETTLE_SNAPSHOT_DIR", raising=False)
    monkeypatch.delenv("SANDBAR_METRICS_DIR", raising=False)
    root = tmp_path / "projects"
    for key in ("sandbar", "project-vision"):
        (root / key / "ledger").mkdir(parents=True)
    _write(root, "sandbar", [_landing("ldg-FOREIGN", "t240101-01", "develop-buffer")])
    _write(root, "project-vision", [])
    repo = tmp_path / "proj"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "ut@example.com", cwd=repo)
    _git("config", "user.name", "ut", cwd=repo)
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    lane = repo / ".lane" / KEYLESS
    _git("worktree", "add", "-b", "lane/%s" % KEYLESS, str(lane), cwd=repo)
    (lane / "f.txt").write_text("changed\n", encoding="utf-8")
    _git("commit", "-am", "lane work", cwd=lane)

    async def _no_project_key(ticket_id):
        return ""      # meta.project could not be resolved (the measured shape)

    monkeypatch.setattr(aa, "_fetch_ticket_project", _no_project_key)
    aa._LANDING_CLOSEOUT_PROJECT_KEY.clear()
    aa._LANDING_CLOSEOUT_KEYLESS_NOTE.clear()
    yield {"repo": repo, "lane": lane, "store": root}
    aa._LANDING_CLOSEOUT_PROJECT_KEY.clear()
    aa._LANDING_CLOSEOUT_KEYLESS_NOTE.clear()


def _close_out(lane):
    return asyncio.run(aa.merge(aa.MergeArgs(
        ticket_id=KEYLESS, worktree=str(lane), branch="lane/%s" % KEYLESS,
        base_ref="", defer_teardown=True)))


def test_a_keyless_close_out_books_once_and_no_project_ledger_is_written(keyless_lane):
    """Direction (i) + (iii): the keyless close-out that does not double-book
    succeeds, books exactly one squash commit, says on the receipt why it was
    allowed, and leaves every project's delivery ledger byte-identical. A retry
    (Temporal re-entry) books nothing a second time."""
    repo, lane, store = keyless_lane["repo"], keyless_lane["lane"], keyless_lane["store"]
    before_bytes = _store_bytes(store)
    before_commits = int(_git("rev-list", "--count", "main", cwd=repo))

    res = _close_out(lane)
    assert res.ok and res.action == "merged", res.error
    assert "could not be resolved" in res.error
    assert "no ledger anywhere holds a landing for this id" in res.error
    assert "no ledger row was written" in res.error
    after_commits = int(_git("rev-list", "--count", "main", cwd=repo))
    assert after_commits == before_commits + 1, "exactly one squash commit"
    assert (repo / "f.txt").read_text(encoding="utf-8") == "changed\n"

    again = _close_out(lane)
    assert again.ok, again.error
    assert int(_git("rev-list", "--count", "main", cwd=repo)) == after_commits, \
        "a retry must not book the same ticket twice"
    assert "could not be resolved" in again.error, \
        "a retried keyless close-out says the same thing on its receipt"

    assert _store_bytes(store) == before_bytes, \
        "no project's delivery ledger may be written by a close-out"


def test_a_keyless_close_out_refuses_when_the_id_landed_anywhere(keyless_lane):
    """Direction (ii) at the activity face: the moment a landing for this id exists
    in some project's ledger, the same keyless close-out refuses BY NAME instead of
    booking - and still writes nothing."""
    repo, lane, store = keyless_lane["repo"], keyless_lane["lane"], keyless_lane["store"]
    _write(store, "project-vision", [_landing("ldg-COLLIDE", KEYLESS, "develop-buffer")])
    before_bytes = _store_bytes(store)
    before_commits = int(_git("rev-list", "--count", "main", cwd=repo))

    res = _close_out(lane)
    assert not res.ok and res.reason == "line_landing_closeout", res
    assert "project 'project-vision'" in res.error
    assert "landing ldg-COLLIDE" in res.error
    assert "id-scheme collision" in res.error
    assert "do not withdraw it" in res.error
    assert int(_git("rev-list", "--count", "main", cwd=repo)) == before_commits, \
        "a refused close-out must not book"
    assert _store_bytes(store) == before_bytes
