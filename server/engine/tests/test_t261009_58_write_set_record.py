"""t261009-58 unit tests: ONE effective write set (durable record + plan-time
named mismatch + narrow audited annex).

Coverage (no Temporal server / no model / no network; disk faces self-contained
in tmp dirs):
  A. record pure faces: build / apply_widening (malformed refused, already-set
     skipped, who/reason required, illegal entries refused by name) / canonical
     bytes idempotency / parse malformed inputs (bad JSON, non-object, missing
     keys, history not a list) / face-line rendering / face read three states
     (missing file = old ticket, zero noise; broken record = named fallback;
     relative path = named refusal).
  B. precedence pinned (plan-review condition 2): meta['effective_write_set']
     beats meta['write_set'] (in-workflow face); the FILE record beats meta
     (cross-process face) - one test each, divergence pinned.
  C. plan-time naming (rule 2): _refresh_write_set_after_plan lights the named
     line + meta cache + initial capture in the union branch; unpatched gate =
     legacy semantics byte for byte (zero new meta keys).
  D. annex admission: already-authorized skipped / illegal shape refused /
     protected refused (the host's word, never self-authorized) / held by
     another in-flight ticket refused (holder named) / out-of-scope refused
     (KI-125 door: a directory-form entry needs an already-authorized entry
     under it) / per-ticket 8-file cap (over-cap refused by name) / intake
     shape faults (missing who/reason, empty list).
  E. disk activity faces: persist_write_set_record idempotency (same input =
     same bytes, second write skipped), named refusals (relative path, wrong
     name); annex_holder_scan sibling-lane scan (holders named, record-less old
     lanes into `unscanned` as named blind spots, own_lane_dir excluded,
     non-absolute root named refusal).

Malformed-input cases (discipline for external-input consumers): bad JSON /
non-object / missing-key records, non-list file lists, absolute-path entries -
all fixed-shape stubs, never a real external source.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402

import shared  # noqa: E402
from shared import (  # noqa: E402
    ANNEX_MAX_FILES,
    WS_WIDEN_ANNEX,
    WS_WIDEN_PLAN_UNION,
    AnnexRequest,
    annex_admission,
    annex_request_faults,
    annex_scope_ok,
    apply_write_set_widening,
    build_write_set_record,
    parse_write_set_record,
    plan_write_set_mismatch,
    write_set_effective,
    write_set_holds,
    write_set_history_lines,
    write_set_record_bytes,
    write_set_record_face,
)


# ---------- A. record pure faces ----------

def test_build_and_widen_roundtrip():
    rec = build_write_set_record("t-1", ["server/a.py", " server/a.py "], "2026-10-10T00:00:00")
    assert rec["initial"] == ["server/a.py"] and rec["effective"] == ["server/a.py"]
    rec2, err = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["server/b.py", "server/a.py"],
                                         "dev", "host-ordered call site", "at-2")
    assert err == ""
    assert rec2["effective"] == ["server/a.py", "server/b.py"]
    assert rec["effective"] == ["server/a.py"]          # input record not mutated in place
    assert rec2["history"] == [{"kind": WS_WIDEN_ANNEX, "files": ["server/b.py"],
                                "who": "dev", "reason": "host-ordered call site", "at": "at-2"}]


def test_widen_malformed_inputs_refused_by_name():
    rec = build_write_set_record("t-1", ["server/a.py"], "at")
    # malformed record
    out, err = apply_write_set_widening(None, WS_WIDEN_ANNEX, ["x.py"], "w", "r", "at")
    assert out is None and "malformed" in err
    # unknown kind
    _, err = apply_write_set_widening(rec, "magic", ["x.py"], "w", "r", "at")
    assert "unknown widening kind" in err
    # who/reason required (a recorded act, never silent)
    _, err = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["x.py"], "", "r", "at")
    assert "who and reason" in err
    # non-list file list
    _, err = apply_write_set_widening(rec, WS_WIDEN_ANNEX, "server/x.py", "w", "r", "at")
    assert "must be a list" in err
    # illegal entries refused by name (external-input stub: absolute path)
    _, err = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["/abs/x.py"], "w", "r", "at")
    assert "/abs/x.py" in err and "illegal entries" in err
    # everything already effective -> zero widening, zero history entries
    out, err = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["server/a.py"], "w", "r", "at")
    assert err == "" and out["history"] == []


def test_record_bytes_canonical_and_parse_malformed():
    rec = build_write_set_record("t-1", ["b.py", "a.py"], "at")
    rec, _ = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["c.py"], "w", "r", "at2")
    b1 = write_set_record_bytes(rec)
    reordered = {k: rec[k] for k in reversed(list(rec.keys()))}
    assert write_set_record_bytes(reordered) == b1          # key order irrelevant -> replay idempotent
    # bad JSON / non-object / missing key / history not a list (malformed-input stubs)
    assert parse_write_set_record("{nope")[1].startswith("write-set record is not valid JSON")
    assert parse_write_set_record([1, 2])[1].startswith("write-set record is list")
    assert "missing key 'history'" in parse_write_set_record(
        {"ticket_id": "t", "initial": [], "effective": []})[1]
    assert parse_write_set_record(
        {"ticket_id": "t", "initial": [], "effective": {}, "history": []})[1] != ""
    ok, err = parse_write_set_record(b1.decode("utf-8"))
    assert ok and err == ""


def test_face_lines_and_face_read_three_states(tmp_path):
    rec = build_write_set_record("t-1", ["server/a.py"], "at")
    rec, _ = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["server/b.py"], "dev",
                                      "host order 261010", "at2")
    lines = write_set_history_lines(rec)
    assert lines[0].startswith("write set initial (1): server/a.py")
    assert "widening annex: +server/b.py who=dev" in lines[1]
    assert lines[-1].startswith("write set effective (2):")
    # three states: missing = old ticket, zero noise; broken = named fallback; relative = named refusal
    assert write_set_record_face(str(tmp_path / "absent" / "x.json")) == ([], "")
    good = tmp_path / ".sandbar" / "write_set_record.json"
    good.parent.mkdir()
    good.write_bytes(write_set_record_bytes(rec))
    lines2, err = write_set_record_face(str(good))
    assert err == "" and lines2 == lines
    good.write_text("{broken", encoding="utf-8")
    _, err = write_set_record_face(str(good))
    assert "not valid JSON" in err
    _, err = write_set_record_face("rel/path.json")
    assert "not absolute" in err


# ---------- B. precedence pinned (plan-review condition 2) ----------

def test_precedence_meta_effective_wins_over_write_set():
    # in-workflow face: a present (non-empty list) cache wins, write_set divergence never read back
    assert write_set_effective({"effective_write_set": ["e1"], "write_set": ["s1"]}) == ["e1"]
    # empty/malformed cache falls back to the stored field; nothing at all = empty (never raises)
    assert write_set_effective({"effective_write_set": [], "write_set": ["s1"]}) == ["s1"]
    assert write_set_effective({"effective_write_set": "x", "write_set": ["s1"]}) == ["s1"]
    assert write_set_effective({}) == []
    assert write_set_effective(None) == []


def test_precedence_file_record_wins_for_cross_process_face(tmp_path):
    # the cross-process face reads the file record - when a (hypothetical) meta
    # disagrees with the file, the face shows the file
    rec = build_write_set_record("t-1", ["s1.py"], "at")
    rec, _ = apply_write_set_widening(rec, WS_WIDEN_ANNEX, ["e1.py"], "w", "r", "at")
    p = tmp_path / ".sandbar" / "write_set_record.json"
    p.parent.mkdir()
    p.write_bytes(write_set_record_bytes(rec))
    lines, _ = write_set_record_face(str(p))
    assert any("e1.py" in ln for ln in lines)
    assert "write set effective (2): s1.py, e1.py" in lines[-1]


# ---------- C. plan-time naming + dev_lane gate 2 (stub workflow shell, t260904-18 style) ----------

def _mk_lane(patched_ids):
    import datetime
    import dev_lane
    orig = dev_lane.workflow
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid in patched_ids,
        now=lambda: datetime.datetime(2026, 10, 10, 12, 0, 0))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"write_set": ["server/a.py"], "ticket_id": "t-ut"}
    wf.results = {}
    wf.timeline = []
    yield wf, dev_lane, orig
    dev_lane.workflow = orig


def test_refresh_patched_caches_effective_and_names_mismatch():
    for wf, dev_lane, _orig in _mk_lane(
            {"dev-lane-refresh-write-set", "dev-lane-write-set-fault",
             "dev-lane-effective-write-set"}):
        wf.results["create_plan"] = {"files_changed": ["server/b.py", "server/a.py"],
                                     "files_changed_shape": "ok"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert wf.meta["write_set"] == ["server/a.py", "server/b.py"]
        assert wf.meta["effective_write_set"] == wf.meta["write_set"]
        assert wf.meta["initial_write_set"] == ["server/a.py"]      # captured on first widening only
        assert wf.meta["write_set_last_widening"]["files"] == ["server/b.py"]
        notes = [e["note"] for e in wf.meta.get("log", [])]
        assert any("write-set gap named at plan time" in n and "server/b.py" in n and
                   "protected path" in n for n in notes)


def test_refresh_patched_no_mismatch_no_named_line():
    for wf, dev_lane, _orig in _mk_lane({"dev-lane-refresh-write-set", "dev-lane-effective-write-set"}):
        wf.results["create_plan"] = {"files_changed": ["server/a.py"], "files_changed_shape": "ok"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        notes = [e["note"] for e in wf.meta.get("log", [])]
        assert not any("write-set gap" in n for n in notes)
        assert wf.meta["write_set_last_widening"]["files"] == []


def test_refresh_unpatched_effective_gate_keeps_legacy_bytes():
    """Old refresh gate on, new gate off (an existing instance replaying): zero new
    meta keys, legacy semantics byte for byte."""
    for wf, dev_lane, _orig in _mk_lane({"dev-lane-refresh-write-set"}):
        wf.results["create_plan"] = {"files_changed": ["server/b.py"], "files_changed_shape": "ok"}
        dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(wf)
        assert wf.meta["write_set"] == ["server/a.py", "server/b.py"]
        for key in ("effective_write_set", "initial_write_set",
                    "write_set_last_widening", "write_set_history"):
            assert key not in wf.meta


def test_effective_write_set_helper_patch_branches():
    for wf, dev_lane, _orig in _mk_lane(set()):
        assert dev_lane.DevLaneWorkflow._effective_write_set(wf) == ["server/a.py"]
    for wf, dev_lane, _orig in _mk_lane({"dev-lane-effective-write-set"}):
        wf.meta["effective_write_set"] = ["cache.py"]
        assert dev_lane.DevLaneWorkflow._effective_write_set(wf) == ["cache.py"]


def test_plan_mismatch_matches_union_added():
    assert plan_write_set_mismatch(["a.py"], ["a.py", "b.py", "c.py"]) == ["b.py", "c.py"]
    assert plan_write_set_mismatch(["a.py"], ["a.py"]) == []
    assert plan_write_set_mismatch(None, ["/abs", "b.py"]) == ["b.py"]   # illegal entries never enter the gap face


# ---------- D. annex admission ----------

def test_annex_scope_and_holds_semantics():
    eff = ["server/a.py", "integration/x.py"]
    assert write_set_holds(eff, "server/a.py") and not write_set_holds(eff, "server/a.py.bak")
    assert write_set_holds(["integration/"], "integration/y/z.py")
    assert annex_scope_ok("server/b.py", eff)[0]
    assert not annex_scope_ok("docs/note.md", eff)[0]
    # a directory-form entry needs an already-authorized entry under it:
    # integration/x.py is in place -> admitted; a directory with no business -> refused
    assert annex_scope_ok("integration/", eff)[0]
    assert not annex_scope_ok("notes/", ["server/a.py"])[0]
    assert annex_scope_ok("notes/", ["server/a.py", "notes/deep/f.md"])[0]


def test_annex_admission_rules_ordered_and_named():
    eff = ["server/a.py"]
    admitted, refused = annex_admission(
        ["server/a.py",            # already authorized -> skipped (not a widening)
         "/abs.py",                # illegal shape -> refused
         "secret/host.pem",        # protected -> refused (the host's word)
         "other/tool.py",          # out of declared scopes -> refused (KI-125 door)
         "server/b.py",            # admitted
         "server/b.py"],           # duplicate
        eff, protected_hits=["secret/host.pem"],
        holders=[{"ticket_id": "t-9", "file": "server/c.py"}],
        annexed_so_far=ANNEX_MAX_FILES - 1, max_files=ANNEX_MAX_FILES)
    assert admitted == ["server/b.py"]
    assert any("/abs.py: illegal entry shape" in r for r in refused)
    assert any("secret/host.pem" in r and "protected" in r for r in refused)
    assert any("other/tool.py" in r and "scopes" in r for r in refused)
    # cap: judged on the WHOLE act — a request beyond the remaining budget refuses
    # everything by name (a partial widening must never read as admitted)
    admitted2, refused2 = annex_admission(["server/c.py", "server/d.py"], eff,
                                          protected_hits=[], holders=[],
                                          annexed_so_far=ANNEX_MAX_FILES)
    assert admitted2 == [] and all("budget" in r for r in refused2)
    # held by another in-flight ticket: the holder is named
    _, refused3 = annex_admission(["server/c.py"], eff, [], [{"ticket_id": "t-9", "file": "server/c.py"}], 0)
    assert any("server/c.py" in r and "t-9" in r for r in refused3)


def test_annex_request_intake_faults():
    assert "who and reason" in annex_request_faults(AnnexRequest(files=["x.py"]))
    assert "non-empty list" in annex_request_faults(AnnexRequest(who="w", reason="r", files=[]))
    assert "illegal entries" in annex_request_faults(
        AnnexRequest(who="w", reason="r", files=["/abs"]))
    assert annex_request_faults(AnnexRequest(who="w", reason="r", files=["x.py"])) == ""


# ---------- E. disk activity faces ----------

def _rec(initial, annex=None, ticket_id="t-me"):
    rec = build_write_set_record(ticket_id, initial, "at0")
    for i, f in enumerate(annex or []):
        rec, err = apply_write_set_widening(rec, WS_WIDEN_ANNEX, [f], "w", "r", "at%d" % i)
        assert err == ""
    return rec


def test_persist_idempotent_and_named_refusals(tmp_path):
    from agent_activities import WriteSetRecordArgs, persist_write_set_record
    p = tmp_path / "lane" / ".sandbar" / "write_set_record.json"
    rec = _rec(["a.py"], ["b.py"])
    r1 = asyncio.run(persist_write_set_record(WriteSetRecordArgs(
        ticket_id="t-me", record_path=str(p), record=rec)))
    assert r1.ok and r1.wrote and p.exists()
    first = p.read_bytes()
    assert first == write_set_record_bytes(rec)
    # idempotent replay: same input = same bytes, second run writes nothing
    r2 = asyncio.run(persist_write_set_record(WriteSetRecordArgs(
        ticket_id="t-me", record_path=str(p), record=rec)))
    assert r2.ok and not r2.wrote and p.read_bytes() == first
    # named refusals: relative path / wrong file name
    r3 = asyncio.run(persist_write_set_record(WriteSetRecordArgs(
        ticket_id="t-me", record_path="rel.json", record=rec)))
    assert not r3.ok and "not absolute" in r3.error
    r4 = asyncio.run(persist_write_set_record(WriteSetRecordArgs(
        ticket_id="t-me", record_path=str(tmp_path / "other.json"), record=rec)))
    assert not r4.ok and "write_set_record.json" in r4.error


def test_holder_scan_named_blind_spots(tmp_path):
    from agent_activities import AnnexHolderScanArgs, annex_holder_scan
    root = tmp_path / "lanes"
    mine = root / "t-me"
    (mine / ".sandbar").mkdir(parents=True)
    other = root / "t-other"
    (other / ".sandbar").mkdir(parents=True)
    (other / ".sandbar" / "write_set_record.json").write_bytes(
        write_set_record_bytes(_rec(["o.py"], ["integration/"], ticket_id="t-other")))
    old = root / "t-old" / ".sandbar"
    old.mkdir(parents=True)     # a record-less old lane
    broken = root / "t-bad" / ".sandbar"
    broken.mkdir(parents=True)
    (broken / "write_set_record.json").write_text("{bad", encoding="utf-8")
    res = asyncio.run(annex_holder_scan(AnnexHolderScanArgs(
        ticket_id="t-me", lanes_root=str(root), own_lane_dir=str(mine),
        files=["o.py", "integration/z.py", "free.py"])))
    assert res.error == ""
    assert res.holders == [{"ticket_id": "t-other", "file": "o.py"},
                           {"ticket_id": "t-other", "file": "integration/z.py"}]
    assert any("t-old" in u for u in res.unscanned) and any("t-bad" in u for u in res.unscanned)
    # named refusal: non-absolute root
    res2 = asyncio.run(annex_holder_scan(AnnexHolderScanArgs(
        ticket_id="t-me", lanes_root="rel", files=["x.py"])))
    assert "not an absolute directory" in res2.error
