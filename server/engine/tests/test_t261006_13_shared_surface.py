#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261006-13 unit tests: shared base chain + cross-face dedupe + coverage
self-check + machine noise demoted to machine notes.

Pinned behaviour (ticket B1-B5; the four review conditions):
  B1 one shared change surface per period: compute_surface splits by face, the shared
     file is reused idempotently for matching shas, and stale-sha / absent / corrupt
     each get a named outcome (review cond. 1: absent is NOT blocked, recompute locally).
  B2 the base must be real: the three-level fallback trusts only the previous report
     chain (lane -> suite -> prev base_head); a gap is unavailable, HEAD is never
     invented; an empty resolve_this_base is unavailable too (no hidden endpoint seeding).
  B3 coverage self-check: unavailable fails loudly; a small surface is little-to-review
     WITH the thresholds actually used on the front page (review cond. 3: a named bar);
     a genuinely empty diff is not a collapse.
  B4 cross-face dedupe: same id is suppressed with reported_by recorded; findings that
     merely share a subject survive; wording drift (incl. plain-text evidence) keeps the
     id stable (review cond. 2); a corrupt owner ledger fails open with a name.
  B5 machine noise = machine notes (kind/count/reason), zero added findings; "sweep
     did not run" stays a finding.
  Activity (B5/B1): run_inspection_surface replayed on a real git repo (writes the
     shared file back, reuses it, rejects a stale one).

Run: server/engine/.venv/bin/python -B -m pytest \
     server/engine/tests/test_t261006_13_shared_surface.py -q
"""
import asyncio
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from temporalio import activity as activity_mod

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import inspection_decl as decl  # noqa: E402
import inspection_inspect as ins  # noqa: E402
import inspection_lane_watchdog as lw  # noqa: E402
import inspection_surface as sf  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Real git repo, two commits: c1 adds a.py; c2 edits a.py + adds b.py + a scenario."""
    d = tmp_path / "repo"
    d.mkdir()
    _git(d, "init")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    (d / "a.py").write_text("value = 1\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "c1")
    (d / "a.py").write_text("value = 2\n", encoding="utf-8")
    sc = d / "integration" / "x"
    sc.mkdir(parents=True)
    (sc / "sc_new_case.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    srv = d / "server" / "engine"
    srv.mkdir(parents=True)
    (srv / "b.py").write_text("other = 1\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "c2")
    return d


@pytest.fixture()
def beats(monkeypatch):
    got = []
    monkeypatch.setattr(activity_mod, "heartbeat", lambda *a, **k: got.append(a))
    return got


# ---------------- B2: the base chain is real ----------------

def test_resolve_prev_base_three_levels_never_invents_head():
    assert sf.resolve_prev_base({})["verdict"] == "unavailable"
    assert sf.resolve_prev_base(None)["verdict"] == "unavailable"
    # a non-string base_ref is unusable (fail-closed, never coerced)
    assert sf.resolve_prev_base({"lane": {"base_ref": 123}})["verdict"] == "unavailable"
    assert sf.resolve_prev_base({"lane": {"base_ref": "aa"}})["base"] == "aa"
    assert sf.resolve_prev_base({"suite": {"base_ref": "cc"}})["base"] == "cc"
    d3 = {"lane": {"base_ref": "aa"}, "suite": {"base_ref": "cc"}}
    r = sf.resolve_prev_base(d3)
    assert r["base"] == "aa" and "lane" in r["base_source"]
    d4 = {"scan_meta": {"inspect": {"base_head": "dd"}}}
    assert sf.resolve_prev_base(d4)["base"] == "dd"


def test_resolve_this_base_empty_is_unavailable_no_hidden_head():
    assert sf.resolve_this_base("")["verdict"] == "unavailable"
    assert sf.resolve_this_base(None)["verdict"] == "unavailable"
    assert sf.resolve_this_base("ee55")["base"] == "ee55"


# ---------------- B1: one shared computation ----------------

GOOD_DIFF = ("M\tserver/engine/a.py\n"
             "A\tintegration/x/sc_new_case.py\n"
             "M\tserver/engine/b.py\n"
             "R100\told.py\tnew.py\n")


def test_compute_surface_splits_by_face_and_counts_scenarios():
    s = sf.compute_surface("p1", "p2", GOOD_DIFF)
    # R100 rename rows sit outside parse_name_status's single-letter-status contract ->
    assert s["faces"] == {"test": 1, "simplify": 2, "other": 0}
    assert s["malformed_lines"] == 1
    assert s["changed_files"]["test"] == ["integration/x/sc_new_case.py"]
    assert s["new_scenarios"] == 1
    assert s["verdict"] == "normal"
    assert s["coverage"]["thresholds"]["min_surface_files"] == sf.DEFAULT_MIN_SURFACE_FILES


def test_compute_surface_malformed_lines_skipped_and_counted():
    s = sf.compute_surface("p1", "p2", "GARBAGE LINE\nM\tserver/engine/ok.py\n\n??\tx\n")
    assert s["malformed_lines"] == 2
    assert s["changed_files"]["simplify"] == ["server/engine/ok.py"]


def test_empty_diff_is_little_to_review_not_unavailable():
    s = sf.compute_surface("p1", "p2", "")
    assert s["verdict"] == "little-to-review"      # a genuinely empty diff is legitimate
    assert s["faces"] == {"test": 0, "simplify": 0, "other": 0}


def test_coverage_verdict_uses_named_thresholds(review_thresholds=None):
    one = sf.compute_surface("p1", "p2", "M\tserver/engine/only.py")
    assert sf.coverage_verdict(one) == "little-to-review"
    # either signal alone is enough: few files but one new scenario stays normal
    with_scn = sf.compute_surface("p1", "p2", "A\tintegration/s/sc_one.py")
    assert sf.coverage_verdict(with_scn) == "normal"
    # declared thresholds lower the bar: min_new_scenarios=0 makes a 1-file surface normal
    assert sf.coverage_verdict(one, {"min_surface_files": 8, "min_new_scenarios": 0}) == "normal"


def test_shared_surface_file_idempotent_reuse_and_stale_mismatch(tmp_path):
    s = sf.compute_surface("p1", "p2", GOOD_DIFF)
    (tmp_path / sf.surface_file_name("20261006")).write_text(
        json.dumps(s), encoding="utf-8")
    got, note = sf.load_shared_surface(tmp_path, "20261006", "p1", "p2")
    assert got is not None and "shared" in note
    # stale: different base points -> rejected with a name (fail-closed)
    got2, note2 = sf.load_shared_surface(tmp_path, "20261006", "p9", "p2")
    assert got2 is None and "other base points" in note2
    # absent: not an incident, named (the consumer recomputes locally — review cond. 1)
    got3, note3 = sf.load_shared_surface(tmp_path, "20261007", "p1", "p2")
    assert got3 is None and "absent" in note3
    # corrupt: named unreadable, never raises
    (tmp_path / sf.surface_file_name("20261008")).write_text("{not json", encoding="utf-8")
    got4, note4 = sf.load_shared_surface(tmp_path, "20261008", "p1", "p2")
    assert got4 is None and "unreadable" in note4


# ---------------- B4: cross-face dedupe ----------------

def _finding(subject, path="src/a.py", line=12, quote="q"):
    return {"subject": subject, "severity": "low", "evidence":
            [{"path": path, "line": line, "quote": quote}], "why": "w"}


def test_cross_face_dedupe_suppresses_and_records_reported_by():
    fid = ins.mint_finding_id(_finding("dup"))
    own = {"findings": [{"id": fid}]}
    mine = [dict(_finding("dup"), id=fid),
            dict(_finding("distinct"), id=ins.mint_finding_id(_finding("distinct")))]
    out, meta = sf.apply_cross_face_dedupe(mine, own, "integration-tests", "simplify-face")
    assert meta["cross_face_deduped"] == 1
    assert out[0]["verified"] == "suppressed"
    assert out[0]["reported_by"] == ["integration-tests", "simplify-face"]
    assert "cross_face_dedup" in out[0]
    assert out[1].get("verified") != "suppressed" and "reported_by" not in out[1], \
        "a distinct object in the same subject family is never swallowed (B4)"


def test_cross_face_dedupe_identity_stable_under_wording_drift():
    a = _finding("dup", quote="stuck 3h")
    b = _finding("dup", quote="stuck 3h (re-checked at 08:00)")
    assert ins.mint_finding_id(a) == ins.mint_finding_id(b), \
        "wording drift keeps the id (design sec.5.1: identity is not wording)"
    # plain-text evidence (legacy lane face) also falls back to subject identity
    c = {"subject": "lane-stuck:t1", "evidence": "stuck 3h"}
    d = {"subject": "lane-stuck:t1", "evidence": "stuck 3h (later)"}
    assert ins.mint_finding_id(c) == ins.mint_finding_id(d)
    assert ins.mint_finding_id({"subject": "lane-stuck:t2"}) != ins.mint_finding_id(c)


def test_cross_face_dedupe_failopen_on_bad_owner_doc():
    fs = [dict(_finding("x"), id="abcd1234")]
    for bad in (None, {}, {"findings": "nope"}):
        out, meta = sf.apply_cross_face_dedupe(fs, bad, "integration-tests", "simplify-face")
        assert out == fs and "cross_face_note" in meta, \
            "a corrupt owner ledger fails open with a name; the non-owner keeps its findings"


# ---------------- B5: machine noise → machine notes ----------------

def test_machine_notes_carry_count_and_reason_zero_findings():
    meta = {"unreadable": ["t1: timeout", "t2: failed"],
            "unreadable_transient": ["t1: timeout"],
            "unreadable_permanent": ["t2: failed"],
            "errors": ["t3: out-of-scope"],
            "enum_note": "enumeration truncated at cap 500"}
    notes, added = lw.machine_notes_from_meta(meta, meta["errors"])
    assert added == []
    kinds = {n["kind"]: n for n in notes}
    assert kinds["unreadable"]["count"] == 1 and kinds["unreadable-transient"]["count"] == 1
    assert kinds["skipped"]["count"] == 1 and kinds["truncated"]["count"] == 1
    assert all("reason" in n and "count" in n for n in notes)
    # legacy receipt (no classification keys) = one combined note (exact count, no guess)
    notes2, added2 = lw.machine_notes_from_meta({"unreadable": ["t9: x", "t8: y"]}, [])
    assert added2 == [] and len(notes2) == 1
    assert notes2[0]["kind"] == "unreadable" and notes2[0]["count"] == 2
    assert lw.machine_notes_from_meta({}, []) == ([], [])


# ---------------- B4/B1 declaration keys (fail-closed) ----------------

_DECL_T = """
schema: v1
instances:
  - id: a
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 30 7 * * *
    workflow: InspectionPeriodicWorkflow
    template: x
%s
"""


def test_decl_shared_scans_and_thresholds_parse_and_plan():
    d = decl.parse_decl_text(_DECL_T % (
        "    shared_scans:\n      lane-watchdog: integration-tests\n"
        "    surface_thresholds:\n      min_surface_files: 4\n      min_new_scenarios: 0\n"),
        "t")
    it = d.instances[0]
    assert it.shared_scans == {"lane-watchdog": "integration-tests"}
    assert it.surface_thresholds == {"min_surface_files": "4", "min_new_scenarios": "0"}
    plan = decl._plan_from_decl(d, "a")
    assert plan["shared_scans"] == {"lane-watchdog": "integration-tests"}
    assert plan["surface_thresholds"]["min_new_scenarios"] == "0"
    assert sf.normalize_thresholds(plan["surface_thresholds"]) == {
        "min_surface_files": 4, "min_new_scenarios": 0}


@pytest.mark.parametrize("bad", [
    "    shared_scans:\n      bogus-scan: integration-tests\n",
    "    shared_scans:\n      lane-watchdog: \"\"\n",
    "    shared_scans: just-a-string\n",
    "    surface_thresholds:\n      min_surface_files: -2\n",
    "    surface_thresholds:\n      nope: 3\n",
    "    surface_thresholds: 12\n",
])
def test_decl_new_keys_fail_closed(bad):
    with pytest.raises(decl.DeclError) as ei:
        decl.parse_decl_text(_DECL_T % bad, "t")
    assert str(ei.value).strip()


# ---------------- surface activity (real git repo) ----------------

def _surface_args(repo: Path, tmp: Path, **kw) -> dict:
    a = {"instance_id": "simplify-face", "period": "20261006",
         "base_dir": str(repo), "base_head": "", "ledger_dir": str(tmp),
         "surface_thresholds": {}, "shared_scans": {}}
    a.update(kw)
    return a


def _prev_ledger(tmp: Path, instance: str, period: str, base: str) -> Path:
    p = tmp / ("inspection-%s-%s.json" % (instance, period))
    p.write_text(json.dumps({"findings": [], "scan_meta": {"inspect": {"base_head": base}}}),
                 encoding="utf-8")
    return p


def test_surface_activity_computes_and_writes_shared_file(repo, tmp_path, beats):
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _prev_ledger(tmp_path, "simplify-face", "20261005", c1)
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    assert res["ok"] is True, res
    s = res["surface"]
    assert s["prev_base"] == c1 and s["this_base"] == _git(repo, "rev-parse", "HEAD")
    assert s["faces"]["test"] == 1 and s["new_scenarios"] == 1
    assert s["verdict"] == "normal"
    assert "never recorded as a future prev-base" in s["note"], \
        "the HEAD endpoint must be named endpoint-only in the note (B2)"
    # the shared file was written back: the second face hits it for the same shas
    res2 = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    assert res2["surface"]["shared"] is True and res2["surface"]["rows"] == s["rows"]


def test_surface_activity_no_prev_base_is_unavailable(repo, tmp_path, beats):
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    assert res["ok"] is True
    s = res["surface"]
    assert s["verdict"] == "unavailable" and s["reason"], \
        "no previous base = unavailable + reason (B2/B3: the workflow blocks the period)"
    assert not (tmp_path / sf.surface_file_name("20261006")).exists(), \
        "an unavailable surface never writes the shared file (not-computed is not computed)"


def test_surface_activity_stale_shared_file_is_recomputed(repo, tmp_path, beats):
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _prev_ledger(tmp_path, "simplify-face", "20261005", c1)
    stale = sf.surface_unavailable("stale placeholder", "pX", "pY")
    (tmp_path / sf.surface_file_name("20261006")).write_text(json.dumps(stale), encoding="utf-8")
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    assert res["ok"] is True
    assert res["surface"]["shared"] is False and res["surface"]["faces"]["test"] == 1, \
        "a stale (other-base) shared file is rejected and recomputed locally (fail-closed)"


def test_surface_activity_carries_owner_ids_for_cross_face_dedupe(repo, tmp_path, beats):
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _prev_ledger(tmp_path, "simplify-face", "20261005", c1)
    owner_doc = {"findings": [{"id": "aa11bb22"}, {"id": "cc33dd44"}]}
    (tmp_path / "inspection-integration-tests-20261006.json").write_text(
        json.dumps(owner_doc), encoding="utf-8")
    res = asyncio.run(aa.run_inspection_surface(
        _surface_args(repo, tmp_path, shared_scans={"lane-watchdog": "integration-tests"})))
    ss = res["shared_scan"]
    assert ss["owner"] == "integration-tests" and ss["exists"] is True
    assert ss["finding_ids"] == ["aa11bb22", "cc33dd44"]
    # owner doc absent -> fail-open with a name (the non-owner sweeps and keeps its findings)
    (tmp_path / "inspection-integration-tests-20261006.json").unlink()
    res2 = asyncio.run(aa.run_inspection_surface(
        _surface_args(repo, tmp_path, shared_scans={"lane-watchdog": "integration-tests"})))
    assert res2["shared_scan"]["exists"] is False and "absent" in res2["shared_scan"]["note"]


def test_surface_activity_missing_inputs_fail_closed(tmp_path):
    for kw in ({"instance_id": ""}, {"period": ""}, {"base_dir": "/nonexistent-dir-xyz"}):
        res = asyncio.run(aa.run_inspection_surface(_surface_args(tmp_path, tmp_path, **kw)))
        assert res["ok"] is False and res["error"], kw
