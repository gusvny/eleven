# -*- coding: utf-8 -*-
"""t261009-27 — goal 14, the three faces added to ``ticket_outcome``:

1. endings that are not deliveries (withdrawn-never-delivered, superseded),
   coexisting with landed / certified / delivered;
2. the product's kind (change / report / verification, unknown by name),
   deciding which fact ends the ticket;
3. the rebuild-and-compare (``compare_outcomes``) that names the field
   which disagrees.

Review conditions pinned here:
- C1: the kind mapping is a named table — a real inspection-period ticket
  shape (kind "inspection", instance_id, period) reads ``report``;
- C2: ``supersedes`` is REGISTERED (validate_row accepts it, a genuinely
  unknown relation kind still fails);
- C3: the ``ending`` summary precedence is asserted together with the
  independent fields behind it — the summary is never the only witness;
- C4: ``withdrawn_at`` fires even when the withdrawing ticket has no
  landing; the loud raise stays only on the ``reverted_at`` path.

Pure unit tests: ledger rows are plain dicts, no external source, no git,
no network (UT discipline).

t261009-29: every call passes the ONE ledger list (landings, certifications,
promotions and relations together) — the two-file era's split signature is
gone and ``as_of`` carries the single delivery cursor.
"""
import pytest

import develop_promote as dp


def landing(ticket, seq, at=1000, rev="a1b2c3d4", line="buffer"):
    return {"kind": "landing", "id": "ldg-%d" % seq, "ticket": ticket,
            "line": line, "actor": "developer",
            "repos": [{"repo": "sandbar", "revision": rev, "base": None}],
            "at": at, "seq": seq}


def cert(seq, at=2000, rev="a1b2c3d4", run="run-1", cid=None):
    return {"kind": "certification", "id": cid or "cert-%d" % seq,
            "line": "buffer", "run": run, "booked_red": "none",
            "judged_by": "integration",
            "repos": [{"repo": "sandbar", "revision": rev}],
            "at": at, "seq": seq}


def promotion(seq, tickets, at=3000, pid=None, cid="cert-2"):
    return {"kind": "promotion", "id": pid or "prom-%d" % seq,
            "certification": cid, "line": "buffer", "tickets": tickets,
            "main_before": "x", "main_after": "y", "signer": "human",
            "on_behalf_of": None, "authority": None,
            "at": at, "seq": seq}


def relation(kind, from_t, to_t, at=4000, rid="rel-1"):
    return {"kind": kind, "id": rid, "from": from_t, "to": to_t,
            "recorded_by": "integration", "reason": "goal-14 test",
            "at": at}


# ---- C2: supersedes is registered, unknown kinds still refused -------------

def test_supersedes_relation_passes_validate_row():
    row, why = dp.validate_row(
        relation(dp.REL_KIND_SUPERSEDES, "t-new", "t-old", rid="rel-s1"))
    assert row is not None, why
    assert why == ""


def test_genuinely_unknown_relation_kind_still_fails():
    row, why = dp.validate_row(relation("obliterates", "t-a", "t-b"))
    assert row is None
    # t261009-29: one shared validator — the refusal is the delivery
    # ledger's kind-table name now, and "obliterates" is still not a kind
    assert why == "kind_unknown:'obliterates'"


# ---- baseline behaviour unchanged (what must not change) -------------------

def test_three_stage_landed_delivered_reverted_still_answerable():
    d = [landing("t-a", 1), cert(2)]
    p = [promotion(1, ["t-a"]),
         relation(dp.REL_KIND_WITHDRAWS, "t-w", "t-a", at=5000, rid="rel-w")]
    wland = landing("t-w", 3)
    wprom = promotion(2, ["t-w"], at=6000, pid="prom-w")
    v = dp.ticket_outcome(d + [wland] + p + [wprom], "t-a")
    assert v["landed_at"] == wland["repos"][:0] or v["landed_at"]
    assert v["certified_by"] == "cert-2"
    assert v["delivered_in"] == "prom-1"
    assert v["reverted_at"] == 6000
    assert v["ending"] == "reverted"
    # one ordering space, one cursor (t261009-29)
    assert v["as_of"] == {"delivery": 3}


def test_waiting_still_carries_its_own_moment_for_change_ticket():
    v = dp.ticket_outcome([landing("t-a", 1, at=1111)], "t-a",
                          ticket_record={"kind": "fix"})
    assert v["waiting_since"] == 1111
    assert v["product_kind"] == "change"
    assert v["ending"] == "open"
    # the view still has no id / seq / at of its own
    for stolen in ("id", "seq", "at"):
        assert stolen not in v


# ---- (1) endings that are not deliveries -----------------------------------

def test_delivered_and_later_superseded_coexist():
    d = [landing("t-a", 1), cert(2)]
    p = [promotion(1, ["t-a"]),
         relation(dp.REL_KIND_SUPERSEDES, "t-b", "t-a", at=7000, rid="rel-s")]
    v = dp.ticket_outcome(d + p, "t-a")
    # the summary names the LATEST ending …
    assert v["ending"] == "superseded"
    # … but the independent faces all stay readable (C3: never the only
    # witness).
    assert v["delivered_in"] == "prom-1"
    assert v["certified_by"] == "cert-2"
    assert v["superseded_by"] == "t-b"
    assert v["superseded_at"] == 7000


def test_superseded_takes_newest_relation():
    p = [relation(dp.REL_KIND_SUPERSEDES, "t-old", "t-a", at=100, rid="rel-1"),
         relation(dp.REL_KIND_SUPERSEDES, "t-new", "t-a", at=200, rid="rel-2")]
    v = dp.ticket_outcome(p, "t-a")
    assert v["superseded_by"] == "t-new"
    assert v["superseded_at"] == 200
    assert v["ending"] == "superseded"


def test_withdrawn_never_delivered_sets_withdrawn_at():
    d = [landing("t-a", 1)]
    p = [relation(dp.REL_KIND_WITHDRAWS, "t-w", "t-a", at=9000, rid="rel-w1")]
    v = dp.ticket_outcome(d + p, "t-a")
    assert v["withdrawn_at"] == 9000
    assert v["reverted_at"] is None
    assert v["delivered_in"] is None
    assert v["ending"] == "withdrawn"


def test_withdrawn_at_fires_even_when_withdrawer_has_no_landing():
    # C4: the relation is the recorded judgement; the withdrawer's landing
    # matters only to reverted_at. No raise here. (The ticket is not
    # delivered, so the reverted path never runs — a delivered ticket plus
    # a landingless withdrawer keeps today's loud raise, tested above.)
    d = [landing("t-a", 1), cert(2)]
    p = [relation(dp.REL_KIND_WITHDRAWS, "t-ghost", "t-a", at=9500,
                  rid="rel-wg")]
    v = dp.ticket_outcome(d + p, "t-a")
    assert v["withdrawn_at"] == 9500
    assert v["delivered_in"] is None
    assert v["reverted_at"] is None
    # precedence: reverted (None here) < superseded (None) < withdrawn.
    assert v["ending"] == "withdrawn"


def test_withdrawn_target_unknown_still_raises_on_reverted_path():
    d = [landing("t-a", 1), cert(2)]
    p = [promotion(1, ["t-a"]),
         relation(dp.REL_KIND_WITHDRAWS, "t-ghost", "t-a", rid="rel-wg")]
    with pytest.raises(dp.WithdrawnTargetUnknown):
        dp.ticket_outcome(d + p, "t-a")


def test_withdrawn_at_takes_earliest_relation_against_the_ticket():
    p = [relation(dp.REL_KIND_WITHDRAWS, "t-w1", "t-a", at=800, rid="rel-1"),
         relation(dp.REL_KIND_WITHDRAWS, "t-w2", "t-a", at=900, rid="rel-2")]
    v = dp.ticket_outcome(p, "t-a")
    assert v["withdrawn_at"] == 800


# ---- (2) the product's kind -------------------------------------------------

def test_inspection_period_ticket_reads_report_and_ends_by_findings():
    # C1: a real inspection-period shape, verbatim field set from the
    # record-models document.
    rec = {"kind": "inspection", "instance_id": "docs-sync",
           "period": "20261009", "at": 1791510000000,
           "findings": [{"subject": "stale doc"}]}
    v = dp.ticket_outcome([], "t-insp", ticket_record=rec)
    assert v["product_kind"] == "report"
    assert v["ended_by"] == "findings"
    assert v["ended_at"] == 1791510000000
    assert v["ending"] == "ended"
    assert v["waiting_since"] is None


def test_report_without_findings_or_period_is_not_ended():
    rec = {"kind": "inspection", "instance_id": "docs-sync",
           "period": "20261009", "findings": []}
    v = dp.ticket_outcome([], "t-insp", ticket_record=rec)
    assert v["product_kind"] == "report"
    assert v["ended_by"] is None
    assert v["ending"] == "open"

    v = dp.ticket_outcome([], "t-insp",
                          ticket_record={"kind": "report", "findings": [{"s": 1}]})
    assert v["ended_by"] is None  # findings recorded, period cursor missing


def test_report_ended_at_falls_back_to_the_stamped_period_cursor():
    # A period ticket that carries no own moment still names WHEN it ended:
    # the stamped period cursor itself, not a silence.
    rec = {"kind": "inspection", "period": "20261009",
           "findings": [{"subject": "s"}]}
    v = dp.ticket_outcome([], "t-insp", ticket_record=rec)
    assert v["ended_by"] == "findings"
    assert v["ended_at"] == "20261009"


def test_verification_ticket_ends_by_verdict():
    rec = {"kind": "verification", "verdict": "red", "at": 42}
    v = dp.ticket_outcome([], "t-ver", ticket_record=rec)
    assert v["product_kind"] == "verification"
    assert v["ended_by"] == "verdict"
    assert v["ended_at"] == 42


def test_unknown_kind_is_named_not_defaulted():
    for rec in (None, {}, {"kind": "mystery"}, {"kind": 7},
                "not-a-dict"):
        v = dp.ticket_outcome([], "t-x", ticket_record=rec)
        assert v["product_kind"] == "unknown", rec
        assert v["ended_by"] is None


def test_report_ticket_never_waiting_even_with_a_landing_row():
    d = [landing("t-r", 1, at=1234)]
    v = dp.ticket_outcome(d, "t-r",
                          ticket_record={"kind": "inspection",
                                         "period": "20261009",
                                         "findings": [{"s": 1}]})
    assert v["waiting_since"] is None
    assert v["ended_by"] == "findings"


def test_change_ticket_certification_is_the_ending_fact():
    d = [landing("t-a", 1, at=1000), cert(2, at=2000)]
    v = dp.ticket_outcome(d, "t-a", ticket_record={"kind": "fix"})
    assert v["ended_by"] == "certification"
    assert v["ended_at"] == 2000
    assert v["ending"] == "ended"


# ---- (3) rebuild-and-compare ------------------------------------------------

def test_compare_agrees_on_identical_views():
    v = dp.ticket_outcome([landing("t-a", 1)], "t-a")
    r = dp.compare_outcomes(v, v)
    assert r == {"agrees": True, "differs_in": [],
                 "baseline_as_of": v["as_of"], "rebuilt_as_of": v["as_of"]}


def test_compare_names_the_disagreeing_field():
    rec = {"kind": "fix"}
    a = dp.ticket_outcome([landing("t-a", 1)], "t-a", ticket_record=rec)
    b = dp.ticket_outcome([landing("t-a", 1), cert(2)], "t-a",
                          ticket_record=rec)
    r = dp.compare_outcomes(a, b)
    assert r["agrees"] is False
    assert r["differs_in"] == ["certified_by", "ended_by", "ended_at",
                               "ending", "waiting_since"]


def test_compare_cursor_difference_alone_is_not_disagreement():
    a = dp.ticket_outcome([landing("t-a", 1)], "t-a")
    b = dp.ticket_outcome([landing("t-a", 1), landing("t-b", 2)], "t-a")
    b["as_of"] = {"delivery": 99}
    r = dp.compare_outcomes(a, b)
    assert r["agrees"] is True
    assert r["baseline_as_of"] == {"delivery": 1}
    assert r["rebuilt_as_of"] == {"delivery": 99}


def test_compare_absent_and_none_read_the_same():
    r = dp.compare_outcomes({"landed_at": None}, {"landed_at": None})
    assert r["agrees"] is True


def test_compare_refuses_malformed_input_by_name():
    for bad in (None, [], "view", 7):
        with pytest.raises(dp.PromoteError, match="outcome_not_object"):
            dp.compare_outcomes(bad, {})
        with pytest.raises(dp.PromoteError, match="outcome_not_object"):
            dp.compare_outcomes({}, bad)


# ---- malformed ledger rows fed to the ending faces --------------------------

def test_malformed_relation_rows_are_ignored_by_the_ending_faces():
    # non-dict rows, missing at, missing from — never a crash, never a guess
    p = ["junk", 3, None,
         {"kind": dp.REL_KIND_WITHDRAWS, "id": "rel-bad", "to": "t-a"},
         {"kind": dp.REL_KIND_SUPERSEDES, "id": "rel-bad2", "to": "t-a"}]
    v = dp.ticket_outcome(p, "t-a")
    assert v["withdrawn_at"] is None
    assert v["superseded_by"] is None
    assert v["ending"] == "open"


def test_ticket_not_named_still_refused():
    with pytest.raises(dp.PromoteError, match="ticket_not_named"):
        dp.ticket_outcome([], "")
