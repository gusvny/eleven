#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit layer (L1) for the request-layer contract (t261021-08).

Owns: lib_request_contract's validators (green path + named refusal), the
fold (behavior 1/5/6/7), and every defect detector. Malformed-input cases are
mandatory per the engineering convention (adversarial/foreign-shape rows,
torn values, legacy rows); no external source is needed -- all fixtures are
inline dicts shaped like the measured live rows.
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
rc = importlib.import_module("lib_request_contract")


def head(**kw):
    """A well-formed host-facing request head (everything the contract asks)."""
    base = {
        "type": "request", "id": "r1", "at": 1000,
        "project": "proj-a", "kind": "blocker",
        "question": "t261021-08 L16 red blocks t261021-08 merge: proceed?",
        "ticket": "t261021-08", "line": "line-a", "stage": "merge",
        "decision": "yes/no", "cause": "content red on line-a",
        "default_action": {"action": "hold the merge", "after_ms": 3600000},
        "condition_key": "blocker:proj-a:t261021-08:content red",
        "expires_at": 9999999999999, "audience": "host",
    }
    base.update(kw)
    return base


# ---------- behavior 1: condition identity ----------


def test_condition_key_green():
    out = rc.normalize_condition_key(head())
    assert out["ok"] and out["condition_key"] == \
        "blocker:proj-a:t261021-08:content red on line-a"


def test_condition_key_refuses_round_id():
    out = rc.normalize_condition_key(head(cause="run-silent round 7"))
    assert not out["ok"] and out["field"] == "condition_key"
    assert "per-instance" in out["reason"]


def test_condition_key_refuses_timestamp_and_run():
    for cause in ("gate receipt counts 8 at 1729500000000", "run 12 silent"):
        assert not rc.normalize_condition_key(head(cause=cause))["ok"]


def test_condition_key_refuses_missing_kind_project_and_anchor():
    for kw, why in (({"kind": ""}, "kind"),
                    ({"project": ""}, "project"),
                    ({"line": "", "ticket": ""}, "line or ticket")):
        out = rc.normalize_condition_key(head(**kw))
        assert not out["ok"] and why in out["reason"]


def test_condition_key_cause_normalizing_to_empty_refused():
    out = rc.normalize_condition_key(head(cause="round 3"))
    assert not out["ok"]


# ---------- behavior 2: self-contained question ----------


def test_self_contained_green():
    assert rc.check_self_contained(head())["ok"]


def test_self_contained_lists_every_missing_item():
    row = head(question="45 stops on an identical face",
               ticket="", line="", stage="", decision="")
    out = rc.check_self_contained(row)
    assert not out["ok"]
    assert out["field"] == "self_contained"
    for item in ("full_ticket_id", "line", "stage",
                 "decision_yes_no_or_named_options"):
        assert item in out["reason"]


def test_self_contained_named_options_decision_ok():
    row = head(decision=["merge", "hold"])
    assert rc.check_self_contained(row)["ok"]


# ---------- behavior 3: default action ----------


def test_default_green_concrete_and_hold():
    assert rc.check_default_action(head())["ok"]
    assert rc.check_default_action(
        head(default_action={"hold": True}))["default"] == "hold"


def test_default_noop_recheck_refused_by_name():
    for da in ("run-watch re-checks the records next tick",
               "Re-check tomorrow", "watch the ledger"):
        out = rc.check_default_action(head(default_action=da))
        assert not out["ok"] and out["field"] == "default_action"
        assert "no-op-recheck" in out["reason"]


def test_default_missing_and_bad_shape_refused():
    assert not rc.check_default_action(head(default_action=None))["ok"]
    out = rc.check_default_action(
        head(default_action={"action": "x", "after_ms": -1}))
    assert not out["ok"]


# ---------- behavior 4: audience routing ----------


def test_audience_host_and_default_is_host():
    assert rc.route_audience(head())["surface"] == "host"
    assert rc.route_audience(head(audience=None))["surface"] == "host"


def test_audience_other_role_goes_to_role_surface():
    out = rc.route_audience(head(audience="integration"))
    assert out["ok"] and out["surface"] == "role:integration"


def test_audience_bad_shape_refused():
    assert not rc.route_audience(head(audience=7))["ok"]
    assert not rc.route_audience(head(audience="   "))["ok"]


# ---------- behavior 6: expiry ----------


def test_expiry_every_kind_expires():
    now = 1000
    for kind in ("blocker", "notice", "question", "mystery-kind"):
        assert rc.expiry_for(kind, now) > now


# ---------- the fold: behaviors 1/5/6/7 + legacy ----------


def test_fold_duplicate_condition_updates_in_place_in_the_view():
    rows = [head(id="r1", at=1000),
            {"type": "request-update", "condition_key":
             "blocker:proj-a:t261021-08:content red",
             "count": 1, "last_seen": 2000}]
    out = rc.fold_updates(rows, now_ms=3000)
    assert len([h for h in out["heads"] if h["id"] == "r1"]) == 1
    h = out["heads"][0]
    assert h["count"] == 2 and h["last_seen"] == 2000
    assert len(out["open"]) == 1  # ONE card per condition


def test_fold_resolved_leaves_open_and_stays_in_heads():
    rows = [head(id="r1"),
            {"type": "resolved", "id": "s1", "head": "r1", "at": 1500}]
    out = rc.fold_updates(rows, now_ms=3000)
    assert out["open"] == [] and len(out["heads"]) == 1


def test_fold_expired_leaves_open_and_is_counted():
    rows = [head(id="r1", expires_at=2000)]
    out = rc.fold_updates(rows, now_ms=3000)
    assert out["expired"] == ["r1"] and out["open"] == []


def test_fold_legacy_rows_classified_never_dropped():
    legacy = {"type": "request", "id": "old1", "at": 1,
              "project": "proj-a", "kind": "blocker",
              "question": "45 stops on an identical face"}
    out = rc.fold_updates([legacy], now_ms=3000)
    assert out["legacy"] == ["old1"] and len(out["open"]) == 1


def test_fold_orphan_update_counted_not_fatal():
    rows = [head(id="r1"),
            {"type": "request-update", "condition_key": "no-such-key",
             "count": 1, "last_seen": 1500}]
    out = rc.fold_updates(rows, now_ms=3000)
    assert out["orphans"] == 1 and out["open"][0]["count"] == 1


def test_fold_digest_above_cap_lists_ages_and_defaults():
    rows = [head(id="r%d" % i, at=1000 + i, condition_key="k:%d" % i)
            for i in range(3)]
    rows.append(head(id="r9", at=1100, condition_key="k:9",
                     default_action={"hold": True}))
    out = rc.fold_updates(rows, now_ms=5000, cap=2)
    d = out["digest"]
    assert d is not None and d["type"] == "request-digest"
    assert len(d["folded"]) == 2
    entry = {e["id"]: e for e in d["folded"]}["r9"]
    assert entry["has_default"] is True and entry["age_ms"] == 3900
    assert out["heads"][3]["folded_into"] == d["id"]
    assert len(out["open"]) == 2


def test_fold_torn_and_foreign_shape_rows_never_crash():
    rows = [None, "junk", head(id="r1"),
            {"type": "request"},                     # no id
            {"type": "request-update"},              # no key -> orphan
            head(id="r2", expires_at="not-a-number")]
    out = rc.fold_updates(rows, now_ms=3000)
    assert out["orphans"] == 1


def test_fold_legacy_row_with_huge_question_in_digest_not_crash():
    big = head(id="big", question="x" * 5000 + " t261021-08",
               expires_at=None, condition_key=None)
    rows = [big] + [head(id="r%d" % i, condition_key="k:%d" % i)
                    for i in range(3)]
    out = rc.fold_updates(rows, now_ms=5000, cap=2)
    assert isinstance(out["digest"], dict)


# ---------- detectors: every measured class turns red ----------


def measured_ledger():
    """Fixture copies of the seven measured defect shapes (synthetic; no live
    data)."""
    return [
        head(id="ok1"),
        head(id="d1a", condition_key="run-silent:proj-a:line-a:silent",
             question="run-silent on line-a: round 7 ended with no row",
             ticket="t261019-25"),
        head(id="d1b", condition_key="run-silent:proj-a:line-a:silent",
             question="run-silent on line-a: round 8 ended with no row",
             ticket="t261019-25"),
        head(id="d2", question="45 stops on an identical face",
             ticket="", line="line-a"),
        head(id="d3", question="Gate receipt counts 8 over the list. Why?",
             decision="", ticket="t261020-01", line="line-a", stage="run"),
        head(id="d4", default_action="run-watch re-checks the records next tick"),
        head(id="d5", expires_at=None),
        head(id="d6", audience="integration",
             question="【note for integration side】 t261021-08 annex",
             decision="yes/no"),
        {"type": "correction", "id": "c1", "head": "d5"},
    ]


def test_detectors_catch_every_measured_class():
    found = rc.run_all_detectors(measured_ledger())
    assert "d1b" in found["duplicate_condition_keys"]
    assert "d1a" not in found["duplicate_condition_keys"]
    assert "d2" in found["elided_ticket_ids"]
    assert "d3" in found["why_questions"]
    assert "d4" in found["noop_defaults"]
    assert "d5" in found["null_expiry"]
    assert "d6" in found["cross_role_notices"]
    assert "c1" in found["uncollapsed_corrections"]
    # the well-formed row never appears in any detector output
    for ids in found.values():
        assert "ok1" not in ids


def test_detectors_empty_and_malformed_input():
    assert rc.run_all_detectors([]) == {k: [] for k, _ in rc.DETECTORS}
    out = rc.run_all_detectors([None, 42, {"type": "request"}])
    assert all(isinstance(v, list) for v in out.values())


def test_fold_duplicate_head_rows_converge_to_one_card():
    rows = [head(id="r1", at=1000),
            head(id="r2", at=2000,
                 question="t261019-25 line-a run-silent: round 8, no row")]
    out = rc.fold_updates(rows, now_ms=3000)
    dup = [h for h in out["heads"] if h.get("condition_key") ==
           "blocker:proj-a:t261021-08:content red"]
    assert len(dup) == 1 and dup[0]["count"] == 2 and dup[0]["last_seen"] == 2000
    assert len(out["open"]) == 1
