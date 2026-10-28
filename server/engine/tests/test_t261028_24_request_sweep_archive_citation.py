# -*- coding: utf-8 -*-
"""t261028-25 — the request sweep may cite the ticket ARCHIVE, and the `request`
class gets a named rule.

Measured 261028 on an isolated copy of the production ledger: `resolved 0 /
unchanged 5 / residue 43` — blocker/not_listed 19, question+finding human_word
15, request/uncited 5 (`residue_class_unhandled:request`), blocker/uncited 4
(`residue_subject_unparsable`). The `not_listed` bucket existed because the
cited ticket is past Temporal's retention window, so the residue pass had no
citable projection row — while the closed ticket's archive manifest is still on
disk.

What this file pins (host ruling 261028, option a — the archive is a lawful
citation, but only where it PROVES closure):

  A. THE WRITER'S PRECONDITION IS THE RULE. Only a manifest carrying
     `terminal_status` is citable: that field is minted by
     `cmd_ticket_archive_terminal` (client.py:1438-1443) AFTER its own
     describe-status guard (client.py:1380-1391), so it IS the terminal fact.
     `meta.status` is a MID-RUN snapshot and is never the witness — measured
     evidence: a definitely-closed ticket's manifest still reads
     status=dispatched / stage=merge / stage_state=running, because the close
     path archives before the stage finishes (dev_lane.py:7491-7500 ->
     teardown -> _finish; a teardown refusal lands _blocked with the archive
     already written). Both directions are pinned here: meta=closed WITHOUT a
     witness stays open, meta=dispatched WITH a witness closes.
  B. THE THREE REFUSALS, each named: a missing manifest
     (`not_listed_unarchived`), an unreadable / non-schema-v1 manifest
     (`archive_malformed`), a `legacy: true` manifest
     (`archive_legacy_uncited` — the same shape is written by
     agent_activities.archive_ticket's legacy branch from no status check at
     all), and the close path's witness-less manifest
     (`archive_no_terminal_witness`). The head stays OPEN in every case.
  C. THE `request` CLASS HAS A NAMED RULE: the same cited-terminal evidence as a
     blocker (cited projection row / ledger landing / archive-proven), never
     inference; an uncited request head stays open in `uncited`. No
     `residue_class_unhandled:request` exists any more.
  D. BOUNDS THAT DO NOT MOVE: `finding`/`question` rows stay byte-identical
     under any evidence; an answered head is untouched; a cited ticket that
     cannot be proven terminal keeps the head open; a second sweep writes
     nothing.
  E. THE RECEIPT NAMES AND COUNTS EVERY BUCKET (`residue_buckets`), so a sweep
     that closes nothing is visible, and the tally travels on the watch tick.

Offline shape: fixture project roots injected through SANDBAR_PROJECTS_DIR /
SANDBAR_PANEL_DIR (the same injection the existing sweep batteries use), a
stub ticket-status channel, and a stub run-watch tick. Zero real ~/.sandbar,
zero Temporal, zero network.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_sweep as rs  # noqa: E402

KEY = "proj-alpha"
NOW = 1730000000000
SEQ = 3

#: the four statuses the terminal-archive exit may record (its own eligibility
#: set, client.py:849-853)
WITNESSES = ("FAILED", "CANCELED", "TIMED_OUT", "TERMINATED")

REQUIRED_BUCKETS = ("archived_closed", "not_listed_unarchived",
                    "archive_malformed", "archive_legacy_uncited",
                    "human_word", "uncited", "unchanged")


# ---------- fixtures ---------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    """An isolated projects root + panel root. Both env names are set for the
    processes under test (the watch tick resolves its own env) and returned so
    direct calls can pass the injected dict."""
    projects = tmp_path / "projects"
    panel = tmp_path / "panel"
    projects.mkdir()
    panel.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("SANDBAR_PANEL_DIR", str(panel))
    env = {"SANDBAR_PROJECTS_DIR": str(projects), "SANDBAR_PANEL_DIR": str(panel)}
    return env, projects, panel


def write_rows(panel: Path, rows):
    path = panel / KEY / "requests.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def read_rows(path: Path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def archive_path(projects: Path, tid: str) -> Path:
    return projects / KEY / "data" / "tickets" / tid / "archive.json"


def write_archive(projects: Path, tid: str, payload) -> Path:
    path = archive_path(projects, tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def terminal_manifest(tid: str, status: str = "TERMINATED") -> dict:
    """The shape cmd_ticket_archive_terminal writes (client.py:1438-1443)."""
    return {"schema": "v1", "ticket_id": tid, "legacy": False,
            "terminal_status": status,
            "archived_at": "2026-10-27T21:14:59+00:00",
            "meta": {}, "files": [], "absent": ["worktree"],
            "reason": "the failure class is retired by a named operator",
            "archived_by": "host", "excluded_rules": []}


def close_path_manifest(tid: str, meta_status: str = "dispatched") -> dict:
    """The shape agent_activities.archive_ticket writes on the ordinary close
    path (measured 261028: 460/460 manifests on the production ledger look like
    this: legacy false, meta present, NO terminal_status)."""
    return {"schema": "v1", "ticket_id": tid, "legacy": False,
            "archived_at": "2026-10-27T21:14:59+00:00",
            "meta": {"status": meta_status, "stage": "merge",
                     "stage_state": "running"},
            "files": [{"src": ".sandbar/stage_implement_gen0.json",
                       "dst": "stages/stage_implement_gen0.json", "bytes": 12}],
            "absent": [], "excluded_rules": []}


def legacy_manifest(tid: str) -> dict:
    """The shape both legacy writers write (client.py:4644-4649 and
    agent_activities.py:9480-9489): no status field at all."""
    return {"schema": "v1", "ticket_id": tid, "legacy": True,
            "archived_at": "2026-10-27T21:14:59+00:00",
            "meta": {"_meta_unavailable": "workflow snapshot unavailable"},
            "files": [], "absent": ["worktree"],
            "reason": "lane torn down before archiving", "excluded_rules": []}


def status_fn(mapping=None, default=("not-listed", "ticket-list-projection")):
    """A stub ticket channel: an explicit mapping, else `default`."""
    mapping = dict(mapping or {})

    def fn(ticket):
        return tuple(mapping[ticket]) if ticket in mapping else default
    return fn


def sweep(env, status=None, ledger_rows=()):
    return rs.sweep_project(
        KEY, NOW + 5, SEQ, env=env,
        ledger_rows_fn=lambda: (list(ledger_rows), 0, ""),
        is_green=lambda rid: True,
        ticket_status_fn=status or status_fn())


def head(hid, kind, question="", detail="", at=NOW):
    return {"type": "request", "id": hid, "kind": kind, "question": question,
            "detail": detail, "at": at, "default_action": "wait",
            "raised_by": "sess-x", "surface": "engine"}


def entry_of(receipt, hid):
    for e in receipt.get("residue") or []:
        if e.get("id") == hid:
            return e
    return None


def states_for(path, hid):
    return [r for r in read_rows(path) if r.get("state_for") == hid]


# ---------- A. the citable face ---------------------------------------------

def test_terminal_manifest_closes_the_blocker_citing_the_archive(store):
    env, projects, panel = store
    tid = "t261026-91"
    row = head("b1", "blocker", question="blocker: %s blocks the landing" % tid)
    path = write_rows(panel, [row])
    cited = write_archive(projects, tid, terminal_manifest(tid, "TERMINATED"))

    receipt = sweep(env)

    entry = entry_of(receipt, "b1")
    assert entry["bucket"] == "closed", entry
    assert entry["via"] == "archive"
    # the evidence names BOTH the path and the fact relied on
    assert str(cited) in entry["evidence"], entry["evidence"]
    assert "terminal_status=TERMINATED" in entry["evidence"], entry["evidence"]
    written = states_for(path, "b1")
    assert len(written) == 1
    assert written[0]["state"] == "resolved"
    assert written[0]["by"] == rs.RESIDUE_BY
    assert str(cited) in written[0]["evidence"]
    assert receipt["residue_buckets"]["archived_closed"] == 1
    assert receipt["residue_buckets"]["closed"] == 1
    assert receipt["residue_buckets"]["unchanged"] == 0


@pytest.mark.parametrize("status", WITNESSES)
def test_every_status_the_archive_exit_can_record_is_citable(store, status):
    env, projects, panel = store
    tid = "t261027-77"
    write_rows(panel, [head("b-" + status, "blocker",
                            question="ticket %s is the blocker" % tid)])
    write_archive(projects, tid, terminal_manifest(tid, status))
    receipt = sweep(env)
    entry = entry_of(receipt, "b-" + status)
    assert entry["bucket"] == "closed" and entry["via"] == "archive", entry
    assert entry["evidence"].endswith(
        "terminal_status=%s (recorded by the ticket-archive-terminal exit, whose "
        "describe guard refuses a non-terminal execution)" % status)


def test_witness_set_is_the_archive_exits_own_eligibility_set():
    """The citable statuses are the terminal-archive exit's own set, read off
    client.py — not a hand-kept list that can drift away from its guard."""
    import client as client_mod
    assert set(rs.ARCHIVE_TERMINAL_WITNESSES) == set(
        client_mod._ARCHIVE_TERMINAL_ELIGIBLE)
    # and the two statuses that writer REFUSES because they belong elsewhere
    # are not citable witnesses
    assert "COMPLETED" not in rs.ARCHIVE_TERMINAL_WITNESSES
    assert "CONTINUED_AS_NEW" not in rs.ARCHIVE_TERMINAL_WITNESSES


def test_meta_status_is_never_the_witness_in_either_direction(store):
    env, projects, panel = store
    # (i) meta says closed, no terminal_status -> NOT citable (the close path's
    #     archive is written before the ticket is finished)
    closed_meta = "t261026-92"
    write_rows(panel, [head("b-meta-closed", "blocker",
                            question="ticket %s" % closed_meta)])
    write_archive(projects, closed_meta, close_path_manifest(closed_meta, "closed"))
    receipt = sweep(env)
    entry = entry_of(receipt, "b-meta-closed")
    assert entry["bucket"] == "archive_no_terminal_witness", entry
    assert not states_for(panel / KEY / "requests.jsonl", "b-meta-closed")

    # (ii) meta says dispatched, terminal_status present -> citable (the field
    #      is minted after the writer's guard, the snapshot is not read)
    dispatched_meta = "t261026-93"
    write_rows(panel, [head("b-meta-run", "blocker",
                            question="ticket %s" % dispatched_meta)])
    manifest = close_path_manifest(dispatched_meta, "dispatched")
    manifest["terminal_status"] = "FAILED"
    write_archive(projects, dispatched_meta, manifest)
    receipt2 = sweep(env)
    assert entry_of(receipt2, "b-meta-run")["bucket"] == "closed"


# ---------- B. the three refusals (head stays open, named) -------------------

def test_missing_manifest_keeps_the_head_open_named(store):
    env, projects, panel = store
    tid = "t261026-94"
    path = write_rows(panel, [head("b-missing", "blocker",
                                   question="ticket %s" % tid)])
    receipt = sweep(env)
    entry = entry_of(receipt, "b-missing")
    assert entry["bucket"] == "not_listed_unarchived", entry
    assert "no_archive_manifest" in entry["reason"]
    assert str(archive_path(projects, tid)) in entry["reason"]
    assert not states_for(path, "b-missing")
    assert receipt["residue_buckets"]["not_listed_unarchived"] == 1


@pytest.mark.parametrize("payload,marker", [
    ("{not json at all\n", "archive_manifest_unreadable"),
    (json.dumps(["not", "an", "object"]), "archive_manifest_schema_invalid"),
    (json.dumps({"schema": "v2", "ticket_id": "t", "terminal_status": "FAILED"}),
     "archive_manifest_schema_invalid"),
    (json.dumps({"ticket_id": "t", "terminal_status": "FAILED"}),
     "archive_manifest_schema_invalid"),
])
def test_malformed_manifest_keeps_the_head_open_named(store, payload, marker):
    env, projects, panel = store
    tid = "t261026-95"
    path = write_rows(panel, [head("b-bad", "blocker", question="ticket %s" % tid)])
    cited = write_archive(projects, tid, payload)
    receipt = sweep(env)
    entry = entry_of(receipt, "b-bad")
    assert entry["bucket"] == "archive_malformed", entry
    assert marker in entry["reason"], entry["reason"]
    assert str(cited) in entry["reason"]
    assert not states_for(path, "b-bad")
    assert receipt["residue_buckets"]["archive_malformed"] == 1


def test_legacy_manifest_is_not_citable(store):
    """Both legacy writers share one shape, and one of them checks no status at
    all — so a legacy manifest proves no terminal fact."""
    env, projects, panel = store
    tid = "t261026-96"
    path = write_rows(panel, [head("b-legacy", "blocker",
                                   question="ticket %s" % tid)])
    write_archive(projects, tid, legacy_manifest(tid))
    receipt = sweep(env)
    entry = entry_of(receipt, "b-legacy")
    assert entry["bucket"] == "archive_legacy_uncited", entry
    assert "archive_manifest_legacy" in entry["reason"]
    assert not states_for(path, "b-legacy")
    assert receipt["residue_buckets"]["archive_legacy_uncited"] == 1


@pytest.mark.parametrize("status", ["COMPLETED", "CONTINUED_AS_NEW", "running",
                                    "", None, 7])
def test_a_status_the_archive_exit_cannot_write_is_not_a_witness(store, status):
    env, projects, panel = store
    tid = "t261026-97"
    path = write_rows(panel, [head("b-odd", "blocker", question="ticket %s" % tid)])
    manifest = terminal_manifest(tid)
    manifest["terminal_status"] = status
    write_archive(projects, tid, manifest)
    receipt = sweep(env)
    entry = entry_of(receipt, "b-odd")
    assert entry["bucket"] == "archive_no_terminal_witness", entry
    assert not states_for(path, "b-odd")


def test_a_listed_non_terminal_ticket_never_consults_the_archive(store):
    """A contradiction is never resolved in favour of a close: a live (or
    blocked) projection outranks an archive witness."""
    env, projects, panel = store
    tid = "t261026-98"
    path = write_rows(panel, [head("b-live", "blocker", question="ticket %s" % tid)])
    write_archive(projects, tid, terminal_manifest(tid, "TERMINATED"))
    receipt = sweep(env, status=status_fn({tid: ("dispatched",
                                                 "ticket-list-projection")},
                                          default=("dispatched",
                                                   "ticket-list-projection")))
    entry = entry_of(receipt, "b-live")
    assert entry["bucket"] == "uncited", entry
    assert entry["reason"] == "cited_ticket_not_terminal:%s:dispatched" % tid
    assert not states_for(path, "b-live")


def test_an_unavailable_channel_keeps_the_head_open_named(store):
    env, projects, panel = store
    tid = "t261026-99"
    path = write_rows(panel, [head("b-dead", "blocker", question="ticket %s" % tid)])
    write_archive(projects, tid, terminal_manifest(tid))
    receipt = sweep(env, status=lambda t: None)
    entry = entry_of(receipt, "b-dead")
    assert entry["bucket"] == "uncited", entry
    assert entry["reason"] == "ticket_reader_unavailable:%s" % tid
    assert not states_for(path, "b-dead")


# ---------- C. the `request` class has a named rule --------------------------

def test_request_head_closes_on_cited_terminal_evidence(store):
    env, projects, panel = store
    listed, archived, uncited = "t261027-01", "t261027-02", None
    path = write_rows(panel, [
        head("r-listed", "request", question="please wire %s to the line" % listed),
        head("r-archived", "request", question="please retire %s" % archived),
        head("r-uncited", "request", question="please look into the red line"),
    ])
    write_archive(projects, archived, terminal_manifest(archived, "CANCELED"))
    receipt = sweep(env, status=status_fn({listed: ("closed",
                                                    "ticket-list-projection")}))
    listed_entry = entry_of(receipt, "r-listed")
    assert listed_entry["bucket"] == "closed", listed_entry
    assert listed_entry["via"] == "ticket_projection"
    assert "status=closed via ticket-list-projection" in listed_entry["evidence"]
    archived_entry = entry_of(receipt, "r-archived")
    assert archived_entry["bucket"] == "closed", archived_entry
    assert archived_entry["via"] == "archive"
    assert "terminal_status=CANCELED" in archived_entry["evidence"]
    uncited_entry = entry_of(receipt, "r-uncited")
    assert uncited_entry["bucket"] == "uncited", uncited_entry
    assert uncited_entry["reason"] == "residue_subject_unparsable"
    # the old "class not handled" face is gone for the request class
    assert "residue_class_unhandled" not in json.dumps(receipt)
    assert len(states_for(path, "r-listed")) == 1
    assert len(states_for(path, "r-archived")) == 1
    assert not states_for(path, "r-uncited")


def test_request_head_on_a_landing_row_closes_on_the_same_cites_as_a_blocker(store):
    env, projects, panel = store
    tid = "t261027-03"
    write_rows(panel, [head("r-land", "request", question="land %s please" % tid)])
    ledger = [{"kind": "landing", "id": "ldg-77", "ticket": tid, "line": "main",
               "at": NOW + 1000}]
    receipt = sweep(env, ledger_rows=ledger)
    entry = entry_of(receipt, "r-land")
    assert entry["bucket"] == "closed" and entry["via"] == "ledger_landing"
    assert entry["evidence"] == "ldg-77"


def test_a_request_head_citing_an_unproven_archive_stays_open(store):
    env, projects, panel = store
    tid = "t261027-04"
    path = write_rows(panel, [head("r-close-path", "request",
                                   question="please close %s" % tid)])
    write_archive(projects, tid, close_path_manifest(tid, "closed"))
    receipt = sweep(env)
    entry = entry_of(receipt, "r-close-path")
    assert entry["bucket"] == "archive_no_terminal_witness", entry
    assert not states_for(path, "r-close-path")


# ---------- D. the bounds that must not move --------------------------------

def test_finding_and_question_rows_are_byte_identical_after_a_sweep(store):
    env, projects, panel = store
    tid = "t261027-05"
    rows = [
        head("f1", "finding", question="finding: %s leaks a temp dir" % tid),
        head("q1", "question", question="question: does %s close?" % tid),
    ]
    path = write_rows(panel, rows)
    # the strongest evidence available: a terminal archive AND a closed row
    write_archive(projects, tid, terminal_manifest(tid, "TERMINATED"))
    before = path.read_bytes()

    receipt = sweep(env, status=status_fn({tid: ("closed",
                                                 "ticket-list-projection")}))

    assert path.read_bytes() == before, "human-word rows must not gain a byte"
    assert [e["bucket"] for e in receipt["residue"]] == ["human_word", "human_word"]
    assert receipt["residue_buckets"]["human_word"] == 2
    assert receipt["residue_buckets"]["unchanged"] == 2


def test_an_answered_head_is_untouched(store):
    env, projects, panel = store
    tid = "t261027-06"
    rows = [
        head("a1", "blocker", question="ticket %s blocks the line" % tid),
        {"type": "state", "id": "st-answered", "state_for": "a1",
         "state": "answered", "at": NOW + 1, "by": "host",
         "evidence": "the host answered this", "surface": "panel"},
    ]
    path = write_rows(panel, rows)
    write_archive(projects, tid, terminal_manifest(tid))
    before = path.read_bytes()
    receipt = sweep(env)
    assert path.read_bytes() == before, "an answered head is never machine-closed"
    assert entry_of(receipt, "a1") is None
    assert receipt["residue_buckets"]["unchanged"] == 0


def test_second_sweep_writes_nothing(store):
    env, projects, panel = store
    tid = "t261027-07"
    path = write_rows(panel, [head("b2", "blocker", question="ticket %s" % tid)])
    write_archive(projects, tid, terminal_manifest(tid))
    first = sweep(env)
    assert first["residue_buckets"]["archived_closed"] == 1
    after_first = path.read_bytes()

    second = sweep(env)

    assert path.read_bytes() == after_first, "a second sweep must append nothing"
    assert second["residue"] == []
    assert second["residue_buckets"]["closed"] == 0
    assert second["residue_buckets"]["unchanged"] == 0


# ---------- E. the receipt buckets, named and counted -----------------------

def test_receipt_names_and_counts_every_bucket(store):
    env, projects, panel = store
    rows = [
        head("c-listed", "blocker", question="ticket t261027-11"),
        head("c-archived", "blocker", question="ticket t261027-12"),
        head("c-missing", "blocker", question="ticket t261027-13"),
        head("c-legacy", "blocker", question="ticket t261027-14"),
        head("c-malformed", "blocker", question="ticket t261027-15"),
        head("c-path", "blocker", question="ticket t261027-16"),
        head("c-finding", "finding", question="finding: human word"),
        head("c-noid", "blocker", question="no ticket id at all"),
    ]
    write_rows(panel, rows)
    write_archive(projects, "t261027-12", terminal_manifest("t261027-12"))
    write_archive(projects, "t261027-14", legacy_manifest("t261027-14"))
    write_archive(projects, "t261027-15", "{broken")
    write_archive(projects, "t261027-16", close_path_manifest("t261027-16"))
    receipt = sweep(env, status=status_fn(
        {"t261027-11": ("closed", "ticket-list-projection")}))

    buckets = receipt["residue_buckets"]
    for name in REQUIRED_BUCKETS:
        assert name in buckets, "the receipt must name bucket %r: %s" % (name, buckets)
    assert buckets["closed"] == 2                    # listed + archive
    assert buckets["archived_closed"] == 1           # the archive subset
    assert buckets["not_listed_unarchived"] == 1
    assert buckets["archive_malformed"] == 1
    assert buckets["archive_legacy_uncited"] == 1
    assert buckets["archive_no_terminal_witness"] == 1
    assert buckets["human_word"] == 1
    assert buckets["uncited"] == 1
    assert buckets["unchanged"] == 6                # every head left open


def test_a_sweep_that_closes_nothing_is_still_visible(store):
    env, projects, panel = store
    write_rows(panel, [head("n1", "blocker", question="ticket t261027-21"),
                       head("n2", "finding", question="finding: nothing to do")])
    receipt = sweep(env)
    assert receipt["residue_buckets"]["closed"] == 0
    assert receipt["residue_buckets"]["archived_closed"] == 0
    assert receipt["residue_buckets"]["unchanged"] == 2
    for name in REQUIRED_BUCKETS:
        assert name in receipt["residue_buckets"]


def test_the_bucket_tally_travels_on_the_watch_tick(store, monkeypatch):
    """The count must reach the tick the board reads — carried on the receipt,
    not re-derived by the tick (a second derivation is a place to drift)."""
    env, projects, panel = store
    tid = "t261027-22"
    write_rows(panel, [head("w1", "blocker", question="ticket %s" % tid)])
    write_archive(projects, tid, terminal_manifest(tid, "FAILED"))
    monkeypatch.setattr(rs, "default_ticket_status_fn", status_fn())

    import develop_certify
    import run_watch as rw
    monkeypatch.setattr(develop_certify, "declared_line_projects", lambda: [KEY])
    monkeypatch.setattr(rw, "run_watch_tick",
                        lambda project_key, now_ms=None:
                        {"lines": [], "summary": "tick"})
    out = rw.run_watch_tick_engine(now_ms=NOW)
    receipt = out["request_sweep"][KEY]
    assert receipt["residue_buckets"]["archived_closed"] == 1, receipt
    assert out["request_sweep_closed_total"] >= 1


# ---------- the archive resolution itself -----------------------------------

def test_the_archive_root_comes_from_the_injected_env(store, tmp_path):
    env, projects, _panel = store
    other = tmp_path / "elsewhere"
    assert str(rs.archive_manifest_path(KEY, "t261027-31",
                                        {"SANDBAR_PROJECTS_DIR": str(other)})[0]) \
        .startswith(str(other)), "the injected env decides the root"
    path, why = rs.archive_manifest_path(KEY, "t261027-31", env)
    assert why == "" and str(path) == str(archive_path(projects, "t261027-31"))
    # a shape the projects whitelist refuses is never spliced into a path
    bad_path, bad_why = rs.archive_manifest_path("../etc", "t261027-31", env)
    assert bad_path is None and "archive_project_key_invalid" in bad_why
    bad_path2, bad_why2 = rs.archive_manifest_path(KEY, "../../etc", env)
    assert bad_path2 is None and "archive_ticket_id_invalid" in bad_why2


def test_the_subject_ticket_prefers_the_structured_detail_key(store):
    env, projects, panel = store
    tid = "t261027-32"
    write_rows(panel, [head("d1", "blocker",
                            question="please handle t261027-99 first (really %s)"
                                     % tid,
                            detail=json.dumps({"ticket": tid}))])
    write_archive(projects, tid, terminal_manifest(tid))
    receipt = sweep(env)
    entry = entry_of(receipt, "d1")
    assert entry["ticket"] == tid, entry
    assert entry["bucket"] == "closed"
