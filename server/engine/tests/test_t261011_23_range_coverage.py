#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261011-23 — coverage for a waiting landing is RANGE-based (KI-01M4N5ASATAVWP6E38NSPECCAT).

Pure-function tests over ``develop_certify.landable`` / ``ticket_wait_state``
after t261011-23: a landing is covered iff it lies inside the range of a GREEN
certification on its line (``prev_cert(cert).seq < landing.seq <= cert.seq``),
the same predicate ``derive_range()`` computes for ``covered_landings`` and
``_red_range()`` uses for reds — not revision equality (a round certifies the
per-repo HEAD across the range, so only the range's last landing could ever
equal it; every earlier landing waited forever).

Pinned properties (one case each, per the ticket):
  (1) a landing AFTER the newest certification is still only waiting;
  (2) a landing inside a RED certification's range still reads red_implicated;
  (3) a landing inside a GREEN certification's range reads certified, with
      ``covered_by`` naming that certification — including the NON-head
      landing (the t261009-80 shape);
  (4) the two faces answer the same question: pinned on the shapes where both
      faces provably agree (head/solo landings). The residual NON-head
      divergence lives in ``develop_promote.ticket_outcome``'s certified_by
      (per-repo equality on top of the seq rule) and is OUTSIDE this ticket's
      write set — it is pinned here as a NAMED GAP (``test_r4_named_gap_...``)
      and registered on KI-01M4N5ASATAVWP6E38NSPECCAT, never absorbed silently.

Zero docker, zero Temporal, never touches 3099; no integration entry runs.
"""

import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402

LINE = "develop"


def LANDING(idx, ticket="t1", repo="r", revision="rev1", at=1000):
    return {"kind": dc.KIND_LANDING, "id": "ldg-%03d" % idx,
            "ticket": ticket, "line": LINE,
            "repos": [{"repo": repo, "revision": revision}],
            "actor": "engine", "at": at}


def CERT(idx, revision="rev1", run="run-a", at=2000):
    return {"kind": dc.KIND_CERT, "id": "cert-%03d" % idx, "line": LINE,
            "repos": [{"repo": "r", "revision": revision}], "run": run,
            "booked_red": "none", "judged_by": "integration", "at": at}


def stamped(rows):
    """In-memory stand-in for the shared writer's seq stamping."""
    return [dict(r, seq=i + 1) if isinstance(r, dict) else r
            for i, r in enumerate(rows)]


def green(_run_id):
    return True


def red(_run_id):
    return False


def by_run(mapping):
    """Run id -> bool per mapping; unknown ids read False (never guessed)."""
    return lambda run_id: bool(mapping.get(run_id))


NOW = 9000

# ---- property (1): after the newest certification = still only waiting ------

def test_p1_landing_after_newest_certification_is_waiting():
    rows = stamped([LANDING(1), CERT(1, revision="rev1"),
                    LANDING(2, ticket="t2", revision="rev2")])
    face = dc.ticket_wait_state(rows, LINE, rows[2], green, NOW)
    assert face["state"] == dc.WAIT_WAITING
    assert face["covered_by"] is None
    assert face["waiting_for"] == "cert-001"
    assert dc.landable(rows, LINE, rows[2], is_green=green) is False


def test_p1_no_certification_on_line_is_waiting():
    rows = stamped([LANDING(1)])
    face = dc.ticket_wait_state(rows, LINE, rows[0], None, NOW)
    assert face["state"] == dc.WAIT_WAITING
    assert face["waiting_for"] is None


# ---- property (2): inside a RED range = red_implicated (unchanged) ---------

def test_p2_landing_inside_red_range_reads_red_implicated():
    rows = stamped([LANDING(1, revision="bad"),
                    CERT(1, revision="bad", run="run-red")])
    face = dc.ticket_wait_state(rows, LINE, rows[0],
                                by_run({"run-red": False}), NOW)
    assert face["state"] == dc.WAIT_RED_IMPLICATED
    assert face["waiting_for"] == "cert-001"


# ---- property (3): inside a GREEN range = certified, incl. the NON-head ----

def test_p3_non_head_landing_inside_green_range_is_certified():
    # The exact t261009-80 shape: L1 and L2 land, ONE green round certifies
    # the range (repos = L2's revision, the per-repo HEAD). L1 is not the
    # range's head and can never revision-match — it is still covered.
    rows = stamped([LANDING(1, ticket="t1", revision="rev1"),
                    LANDING(2, ticket="t2", revision="rev2"),
                    CERT(1, revision="rev2")])
    face = dc.ticket_wait_state(rows, LINE, rows[0], green, NOW)
    assert face["state"] == dc.WAIT_CERTIFIED
    assert face["covered_by"] == "cert-001"
    assert dc.landable(rows, LINE, rows[0], is_green=green) is True


def test_p3_red_cert_released_by_a_later_green_261016_ruling():
    """261016 host ruling (rule C), INVERTING this case's former expectation.

    It used to assert that a later green whose range excludes the landing does
    NOT certify it. That made the block permanent by construction — ranges are
    disjoint and forward-only, so a landing a red swallowed could never be
    reached by a later range, and four landed tickets sat blocked at their merge
    gates while the line had been certified green several times since. The
    ruling: a red that implicates a landing is RELEASED by the next green
    certification recorded after it (the line advances forward, so that green
    judged a state containing the landing), and the face names both — the
    releasing green and the red it released.
    """
    rows = stamped([LANDING(1, ticket="t1", revision="bad"),
                    CERT(1, revision="bad", run="run-red"),
                    LANDING(2, ticket="t2", revision="fix"),
                    CERT(2, revision="fix", run="run-green")])
    face = dc.ticket_wait_state(rows, LINE, rows[0],
                                by_run({"run-red": False, "run-green": True}),
                                NOW)
    assert face["state"] == dc.WAIT_CERTIFIED
    assert face["covered_by"] == "cert-002"        # the releasing green
    assert face["released_from"] == "cert-001"     # the red it released
    assert "released_from_red" in face["release_rule"]


def test_r4_no_later_green_keeps_red_implicated():
    # Fail closed: a red with NO green recorded after it still blocks the
    # landing, and says which red it is waiting behind.
    rows = stamped([LANDING(1, ticket="t1", revision="bad"),
                    CERT(1, revision="bad", run="run-red")])
    face = dc.ticket_wait_state(rows, LINE, rows[0],
                                by_run({"run-red": False}), NOW)
    assert face["state"] == dc.WAIT_RED_IMPLICATED
    assert face["waiting_for"] == "cert-001"
    assert face.get("released_from") is None


def test_r4_a_green_before_the_red_does_not_release():
    # A green that PREDATES the red proves nothing about it: the release needs
    # the later green, strictly after the red's seq.
    rows = stamped([LANDING(1, ticket="t1", revision="ok"),
                    CERT(1, revision="ok", run="run-green"),
                    LANDING(2, ticket="t2", revision="bad"),
                    CERT(2, revision="bad", run="run-red")])
    face = dc.ticket_wait_state(rows, LINE, rows[2],
                                by_run({"run-green": True, "run-red": False}),
                                NOW)
    assert face["state"] == dc.WAIT_RED_IMPLICATED
    assert face["waiting_for"] == "cert-002"


def test_r4_unreadable_runs_never_guess_a_release():
    # No run reader at all (None) with a certification on the line is refused by
    # name, and the release helper never guesses: is_green None reads as "cannot
    # tell", so no release is invented.
    rows = stamped([LANDING(1, ticket="t1", revision="bad"),
                    CERT(1, revision="bad", run="run-red"),
                    CERT(2, revision="fix", run="run-green")])
    with pytest.raises(dc.CertifyError, match="is_green_not_injected"):
        dc.ticket_wait_state(rows, LINE, rows[0], None, NOW)
    assert dc._releasing_green_cert(rows, LINE, rows[1], None) is None
    assert dc._releasing_green_cert(rows, LINE, rows[1], by_run(
        {"run-green": True}))["id"] == "cert-002"


def test_p3_landing_at_prev_cert_seq_not_inside_next_range():
    # prev_seq is EXCLUSIVE: a landing sharing a previous cert's seq belongs
    # to that cert's range, not the next one's.
    rows = [LANDING(1, ticket="t1", revision="old"),
            CERT(1, revision="old"),                       # seq 2
            LANDING(2, ticket="t2", revision="new"),       # seq 3
            CERT(2, revision="new")]                       # seq 4
    rows = stamped(rows)
    # force the landing onto the first cert's seq (the shared ordering space)
    rows[0]["seq"] = rows[1]["seq"]
    assert dc.landable(rows, LINE, rows[0], is_green=green) is True  # cert-001
    assert dc.landable(rows, LINE, rows[2], is_green=green) is True  # cert-002
    assert dc._covering_green_cert(rows, LINE, rows[0], green)["id"] == "cert-001"


def test_p3_landing_at_covering_cert_seq_is_covered():
    # cert.seq is INCLUSIVE: derive_range orders a landing sharing the cert's
    # seq by the shared space, and the range's upper bound is the cert itself.
    rows = [LANDING(1, ticket="t1", revision="rev1"), CERT(1, revision="rev1")]
    rows = stamped(rows)
    rows[0]["seq"] = rows[1]["seq"]
    assert dc.landable(rows, LINE, rows[0], is_green=green) is True


# ---- property (4): the two faces answer the same question ------------------

def _outcome(ticket, rows):
    ticket_record = {"kind": "change"}
    return dp.ticket_outcome(rows, ticket, is_green=green,
                             ticket_record=ticket_record)


def test_p4_faces_agree_on_solo_landing():
    rows = stamped([LANDING(1, ticket="t1", revision="rev1"),
                    CERT(1, revision="rev1")])
    face = dc.ticket_wait_state(rows, LINE, rows[0], green, NOW)
    out = _outcome("t1", rows)
    assert face["state"] == dc.WAIT_CERTIFIED and face["covered_by"] == "cert-001"
    assert out["certified_by"] == "cert-001"


def test_p4_faces_agree_on_head_landing():
    rows = stamped([LANDING(1, ticket="t1", revision="rev1"),
                    LANDING(2, ticket="t2", revision="rev2"),
                    CERT(1, revision="rev2")])
    face = dc.ticket_wait_state(rows, LINE, rows[1], green, NOW)
    out = _outcome("t2", rows)
    assert face["state"] == dc.WAIT_CERTIFIED
    assert out["certified_by"] == "cert-001"


def test_p4_faces_agree_on_waiting_landing():
    rows = stamped([LANDING(1, ticket="t1", revision="rev1"),
                    CERT(1, revision="rev1"),
                    LANDING(2, ticket="t2", revision="rev2")])
    face = dc.ticket_wait_state(rows, LINE, rows[2], green, NOW)
    out = _outcome("t2", rows)
    assert face["state"] == dc.WAIT_WAITING
    assert out["certified_by"] is None


def test_r4_named_gap_closed_the_two_faces_agree():
    """The gap this case used to pin is CLOSED (261016 host ruling).

    It documented that a NON-head landing inside a green range read certified on
    the waiting face while ``ticket_outcome.certified_by`` — then outside the
    write set — still required per-repo revision equality on top of the seq rule
    and answered None; its own docstring said removing the pin and asserting
    agreement IS the fix. The 261016 ruling dropped the equality: the order rule
    is the authority on both faces, so the non-head landing reads certified
    everywhere.
    """
    rows = stamped([LANDING(1, ticket="t1", revision="rev1"),
                    LANDING(2, ticket="t2", revision="rev2"),
                    CERT(1, revision="rev2")])
    face = dc.ticket_wait_state(rows, LINE, rows[0], green, NOW)
    out = _outcome("t1", rows)
    assert face["state"] == dc.WAIT_CERTIFIED
    assert out["certified_by"] == face["covered_by"] == "cert-001"


# ---- edges: run reader contract, precedence, malformed inputs --------------

def test_is_green_refusal_preserved():
    rows = stamped([LANDING(1), CERT(1)])
    with pytest.raises(dc.CertifyError, match="is_green_not_injected"):
        dc.ticket_wait_state(rows, LINE, rows[0], None, NOW)


def test_red_run_reader_hides_green_coverage():
    rows = stamped([LANDING(1, revision="rev1"), CERT(1, revision="rev1")])
    assert dc.landable(rows, LINE, rows[0], is_green=red) is False
    face = dc.ticket_wait_state(rows, LINE, rows[0], red, NOW)
    assert face["state"] == dc.WAIT_RED_IMPLICATED


def test_red_released_by_the_FIRST_green_after_it():
    # 261016 ruling, and this case's former expectation ("the red outranks the
    # green when both ranges contain the landing") is inverted by it. The
    # release names the FIRST green recorded after the red — deterministic, and
    # the earliest proof that the line was green again — not the newest one.
    rows = stamped([LANDING(1, ticket="t1", revision="bad"),
                    LANDING(2, ticket="t2", revision="fix"),
                    CERT(1, revision="fix", run="run-red"),
                    CERT(2, revision="fix", run="run-green"),
                    CERT(3, revision="fix", run="run-green-2")])
    face = dc.ticket_wait_state(rows, LINE, rows[0],
                                by_run({"run-red": False, "run-green": True,
                                        "run-green-2": True}),
                                NOW)
    assert face["state"] == dc.WAIT_CERTIFIED
    assert face["covered_by"] == "cert-002"        # the first green after the red
    assert face["released_from"] == "cert-001"


def test_landing_not_object_raises():
    with pytest.raises(dc.CertifyError, match="landing_not_object"):
        dc.landable([], LINE, "not-a-dict", is_green=green)
    with pytest.raises(dc.CertifyError, match="landing_not_landing"):
        dc.ticket_wait_state([], LINE, {"kind": "certification"}, green, NOW)


def test_landing_seq_missing_reads_uncovered():
    # A landing without a seq is not ordered in the shared space; the range
    # reader answers "not covered" instead of guessing.
    ldg = LANDING(1)
    ldg.pop("seq", None)
    assert dc._covering_green_cert(stamped([ldg, CERT(1)]), LINE, ldg,
                                   green) is None


def test_wait_bound_overdue_surfaced_on_waiting():
    # A landing AFTER the newest (green) certification still waits; the wait
    # bound surfaces as overdue on top of waiting, never as a fake green.
    rows = stamped([LANDING(1, ticket="t0", revision="old", at=1000),
                    CERT(1, revision="old"),
                    LANDING(2, ticket="t2", revision="new", at=2000)])
    face = dc.ticket_wait_state(rows, LINE, rows[2], green, NOW,
                                wait_bound_ms=1000)
    assert face["state"] == dc.WAIT_WAITING
    assert face["overdue"] is True
    face_fresh = dc.ticket_wait_state(rows, LINE, rows[2], green, NOW,
                                      wait_bound_ms=10_000_000)
    assert face_fresh["overdue"] is False
