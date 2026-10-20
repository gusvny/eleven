#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261019-45 L1 truth table: the integ gate's NAMED multi-root declaration
resolution.

Measured defect (tickets t261019-08 / t261019-13, project dengzhufpv): a
multi-repo lane whose write set spans member repos reached run_integration_tests
and the gate answered `verify.yaml missing` permanently, even though the
declaration existed at the lane container and at the member trees — the gate
resolved verify.yaml at exactly ONE root and its receipt never said which tree
it judged.

This battery locks the resolution contract introduced by the fix:

  1. single root found — the caller's root wins and the receipt names it;
  2. found at the second candidate — container without a declaration, a write
     set spanning members, declaration in the member tree;
  3. nothing anywhere — a named refusal listing EVERY candidate tree, the
     file looked for, and the RAW caller path (so "caller pointed at the wrong
     tree" and "tree genuinely has no declaration" separate in one round);
  4. malformed declaration at a candidate — immediate named red naming that
     tree, never a silent fallback past a malformed declaration;
  5. the empty `integration.cmd` refusal keeps its byte-identical message
     (no weakening, contract 2b);
  6. container-first precedence is stated, not implicit — a container carrying
     the project-level declaration is judged on it even when members carry
     their own (member judging is merge_check's per-scope territory);
  7. malformed inputs — a corrupt lane manifest, write-set entries that are
     not directories, `.`/`..` segments, non-string entries: each is either a
     named red or skipped by an explicit rule, never a crash and never an
     anonymous judgment;
  8. the gate's manifest spellings stay locked to the engine's single source
     (shared.MULTI_MANIFEST_NAME + the coordination directory names);
  9. the engine translation carries the named tree on the receipt (source
     shape lock on both the red and the success leg).

Gate-level cases run verify_lane.run with a STUB executor and a STUB baseline
(same technique as test_260929_env_red_named_channel.py) — no real integration
entry executes; everything is offline, seconds, zero git/docker/Temporal.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "server" / "engine"))
sys.path.insert(0, str(REPO / "server" / "tools"))

import shared  # noqa: E402
import verify_lane  # noqa: E402

VL = REPO / "server" / "tools" / "verify_lane.py"
AA = REPO / "server" / "engine" / "agent_activities.py"

DECL = ("schema: v1\n"
        "lanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/stub_executor.py\n")

_STUB_EXEC = r'''#!/usr/bin/env python3
import sys
print("PASS [stub] ok")
print("SCENARIOS ran=1 pass=1 fail=0 na=0 (0s)")
sys.exit(0)
'''


def _mk_lane(tmp_path, *, container_decl=False, members=(("member_a", True),
                                                         ("member_b", False)),
             manifest=True, ws=("member_a/game.js", "member_b/tools/x.js")):
    """A multi-repo lane fixture: container + member trees + the manifest."""
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / "integration").mkdir()
    (lane / "integration" / "stub_executor.py").write_text(_STUB_EXEC,
                                                           encoding="utf-8")
    if container_decl:
        (lane / "verify.yaml").write_text(DECL, encoding="utf-8")
    for name, has_decl in members:
        d = lane / name
        d.mkdir()
        if has_decl:
            (d / "verify.yaml").write_text(DECL, encoding="utf-8")
    if manifest:
        sd = lane / ".sandbar"
        sd.mkdir()
        (sd / "repo_worktrees.json").write_text(json.dumps(
            [{"repo": n, "name": n, "branch": "lane/x-%s" % n,
              "base_ref": "0" * 40} for n, _ in members]), encoding="utf-8")
    return lane, ws


def _cands(lane, ws):
    cands, err = verify_lane._integ_root_candidates(
        lane, {"path": str(lane), "write_set": list(ws)})
    return cands, err


def _resolve(lane, ws, raw_path="some/caller/path"):
    cands, err = _cands(lane, ws)
    if err:
        return None, lane, "candidates refused", err
    return verify_lane._integ_cfg_resolve(cands, raw_path)


# ============================ 1-2. found shapes ============================

def test_truth_table_single_root_found(tmp_path):
    """Shape 1: declaration at the caller's root — it wins, named, source=
    explicit path."""
    lane, ws = _mk_lane(tmp_path, container_decl=True)
    cands, err = _cands(lane, ws)
    assert err is None, err
    assert cands[0]["tree"] == lane.resolve()
    assert cands[0]["why"] == "explicit path"
    cfg, judged, src, rerr = _resolve(lane, ws)
    assert rerr is None and cfg is not None
    assert judged == lane.resolve()
    assert src == "explicit path"


def test_truth_table_found_at_second_candidate(tmp_path):
    """Shape 2: container without a declaration, write set spans two members,
    declaration in the first member tree — resolution finds it there and names
    both the tree and why."""
    lane, ws = _mk_lane(tmp_path, container_decl=False,
                        members=(("member_a", True), ("member_b", False)))
    cands, err = _cands(lane, ws)
    assert err is None, err
    whys = [c["why"] for c in cands]
    assert whys[0] == "explicit path"
    assert "manifest repo member_a" in whys, whys
    assert "manifest repo member_b" in whys, whys
    cfg, judged, src, rerr = _resolve(lane, ws)
    assert rerr is None and cfg is not None
    assert judged == (lane / "member_a").resolve()
    assert src == "manifest repo member_a"


def test_truth_table_found_via_write_set_segment_without_manifest(tmp_path):
    """Shape 2b: no manifest at all (single-repo-looking lane) — the write
    set's directory top segments still become candidates."""
    lane, ws = _mk_lane(tmp_path, container_decl=False, manifest=True)
    (lane / ".sandbar" / "repo_worktrees.json").unlink()
    cfg, judged, src, rerr = _resolve(lane, ws)
    assert rerr is None and cfg is not None
    assert judged == (lane / "member_a").resolve()
    assert src == "write set segment member_a"


# ============================ 3. nothing anywhere ============================

def test_truth_table_nothing_anywhere_named_refusal(tmp_path):
    """Shape 3: no declaration at any candidate — a named refusal listing every
    candidate tree, the file looked for, and the RAW caller path; contract 2b
    wording stays."""
    lane, ws = _mk_lane(tmp_path, container_decl=False,
                        members=(("member_a", False), ("member_b", False)))
    cands, err = _cands(lane, ws)
    assert err is None
    cfg, judged, src, rerr = verify_lane._integ_cfg_resolve(
        cands, "/some/caller/lane")
    assert cfg is None and rerr
    assert "verify.yaml missing at every candidate root" in rerr, rerr
    assert "looked for verify.yaml at:" in rerr, rerr
    for c in cands:
        assert str(c["tree"]) in rerr, (rerr, c)
    assert "contract 2b" in rerr, rerr
    assert "caller path: '/some/caller/lane'" in rerr, rerr
    assert judged == lane.resolve()  # still a tree, never anonymous


def test_gate_red_receipt_names_candidates_and_raw_path(tmp_path):
    """Gate-level shape 3: verify_lane.run returns the named refusal with the
    root face on the receipt."""
    lane, ws = _mk_lane(tmp_path, container_decl=False,
                        members=(("member_a", False), ("member_b", False)))
    res = verify_lane.run({"lane": "integ", "path": str(lane),
                           "write_set": list(ws)})
    assert res["green"] is False
    assert res["root"] == str(lane.resolve()), res.get("root")
    assert res["root_source"] == "resolution exhausted"
    assert len(res["root_candidates"]) == 3, res.get("root_candidates")
    assert "caller path: '%s'" % str(lane) in res["err"], res["err"]


# ============================ 4-6. no weakening ============================

def test_malformed_declaration_named_no_silent_fallback(tmp_path):
    """Shape 4: a malformed verify.yaml at the first candidate that has one is
    an immediate named red naming that tree; the next candidate is NOT
    consulted (never a silent fallback past a malformed declaration)."""
    lane, ws = _mk_lane(tmp_path, container_decl=True,
                        members=(("member_a", True), ("member_b", False)))
    (lane / "verify.yaml").write_text("schema: v9\n", encoding="utf-8")
    cfg, judged, src, rerr = _resolve(lane, ws)
    assert cfg is None and rerr
    assert str(lane.resolve()) in rerr, rerr
    assert "member_a" not in rerr, rerr  # fallback did NOT happen


def test_empty_cmd_message_byte_identical(tmp_path):
    """Shape 5: the missing/empty integration.cmd refusal keeps today's exact
    named message (no weakening)."""
    lane, ws = _mk_lane(tmp_path, container_decl=True)
    (lane / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n",
        encoding="utf-8")
    res = verify_lane.run({"lane": "integ", "path": str(lane),
                           "write_set": list(ws)})
    assert res["green"] is False
    assert res["err"] == (
        'integration.cmd missing or empty = malformed, fail-closed; to express '
        '"this lane has nothing to do", declare an always-succeeding empty '
        'command (e.g. true) and the round is green with zero scenarios '
        '(contract 2b)'), res["err"]
    assert res["root"] == str(lane.resolve())


def test_container_first_precedence_stated(tmp_path):
    """Shape 6: the container carries the project-level declaration — it is
    judged even though members carry their own; the receipt says so (stated
    semantic, review comment 1)."""
    lane, ws = _mk_lane(tmp_path, container_decl=True,
                        members=(("member_a", True), ("member_b", True)))
    cfg, judged, src, rerr = _resolve(lane, ws)
    assert rerr is None and cfg is not None
    assert judged == lane.resolve()
    assert src == "explicit path"


# ============================ 7. malformed inputs ============================

def test_non_repo_segment_and_traversal_skipped_by_rule(tmp_path):
    """Shape 7: write-set entries whose top segment is not an existing member
    directory (measured: integration/README.md) are skipped by the explicit
    rule; `.`/`..` and empty entries never crash and never become candidates."""
    lane, _ = _mk_lane(tmp_path, container_decl=False,
                       members=(("member_a", False), ("member_b", False)))
    # The measured shape: the lane container has no member tree for that top
    # segment (integration/README.md in a lane without an integration tree).
    import shutil as _sh
    _sh.rmtree(lane / "integration")
    ws = ["integration/README.md", "member_a/game.js", ".", "../escape", ""]
    cands, err = _cands(lane, ws)
    assert err is None, err
    whys = [c["why"] for c in cands]
    assert "write set segment integration" not in whys, whys
    assert any("member_a" in w for w in whys), whys
    assert all(str(c["tree"]).startswith(str(lane.resolve())) for c in cands)


def test_non_string_write_set_entries_named_red(tmp_path):
    """Shape 7 (input-and-precedence face P4): a non-string write-set entry
    means a malformed caller — a NAMED red, never a silent str() coercion into
    an anonymous green (the engine payload always carries strings)."""
    lane, ws = _mk_lane(tmp_path, container_decl=True)
    for bad in ([42, "member_a/game.js"], [None], [{"deep": 1}]):
        cands, err = verify_lane._integ_root_candidates(
            lane, {"path": str(lane), "write_set": list(bad)})
        assert cands is None and err, (bad, cands, err)
        assert "not a string" in err and "fail-closed" in err, err
        res = verify_lane.run({"lane": "integ", "path": str(lane),
                               "write_set": list(bad)})
        assert res["green"] is False and "not a string" in res["err"], res


def test_corrupt_manifest_named_fail_closed(tmp_path):
    """Shape 7: a present-but-malformed lane manifest is a named red, never a
    silent skip and never a guess."""
    lane, ws = _mk_lane(tmp_path, container_decl=False)
    (lane / ".sandbar" / "repo_worktrees.json").write_text("{not json",
                                                           encoding="utf-8")
    cands, err = _cands(lane, ws)
    assert cands is None and err
    assert "manifest malformed" in err, err
    res = verify_lane.run({"lane": "integ", "path": str(lane),
                           "write_set": list(ws)})
    assert res["green"] is False and "manifest malformed" in res["err"]
    assert res["root_candidates"] == []


def test_manifest_non_dict_entries_named(tmp_path):
    """Shape 7: manifest entries that are not objects with a string repo field
    are a named red (fail-closed, not guessed)."""
    lane, ws = _mk_lane(tmp_path, container_decl=False)
    (lane / ".sandbar" / "repo_worktrees.json").write_text(
        json.dumps(["fpv-midnight"]), encoding="utf-8")
    _, err = _cands(lane, ws)
    assert err and "string repo field" in err, err


# ============================ 8-9. cross-tree locks ============================

def test_manifest_spellings_locked_to_engine_source():
    """The gate's read-only manifest spellings stay locked to the engine's
    single source of the name (shared.MULTI_MANIFEST_NAME) and the
    coordination directory names. The legacy name is a read face only —
    the two entries differ exactly in the directory prefix."""
    assert verify_lane._INTEG_MANIFEST_RELPATHS == (
        ".sandbar/" + shared.MULTI_MANIFEST_NAME,
        ".suyou/" + shared.MULTI_MANIFEST_NAME)  # naming-compat (legacy-read lock)


def test_engine_translation_carries_gate_root_source_shape():
    """Shape 9 (source shape): the engine translation passes the gate's named
    tree through on BOTH legs (red and success). The translation is inline in
    _run_scenarios, so the lock is the assignment sites — same technique as
    the call-site shape locks (KI-061 replay discipline family)."""
    src = AA.read_text("utf-8")
    assert src.count('out.gate_root = str(res.get("root") or "")') == 1, src
    assert src.count('out_err.gate_root = str(_res.get("root") or "")') == 1, src


# ============================ gate green naming ============================

def _fake_healthy_baseline(lane):
    import failure_protocol as fp
    lane_fp = fp.env_fingerprint(verify_lane._env_fp_parts(lane))

    def _fake(root, cmd, base, timeout, env=None, **kw):
        return True, [], None, "main@stub", lane_fp, None
    return _fake


def test_gate_receipt_names_judged_tree_end_to_end(tmp_path, monkeypatch):
    """Full gate pass over the stub executor: the receipt (green or red) always
    carries the judged tree, why, and the candidate list — never an anonymous
    root."""
    lane, ws = _mk_lane(tmp_path, container_decl=True,
                        members=(("member_a", True), ("member_b", False)))
    monkeypatch.setenv("SANDBAR_GATE_BASELINE", "1")
    monkeypatch.setattr(verify_lane, "_run_baseline",
                        _fake_healthy_baseline(lane))
    res = verify_lane.run({"lane": "integ", "path": str(lane),
                           "write_set": list(ws)})
    assert res["root"] == str(lane.resolve()), sorted(res)
    assert res["root_source"] == "explicit path"
    assert len(res["root_candidates"]) == 3, res["root_candidates"]
    assert {c["why"] for c in res["root_candidates"]} == {
        "explicit path", "manifest repo member_a", "manifest repo member_b"}
    assert res["green"] is True, (res.get("green"), res.get("detail_red"))

def test_true_cmd_green_zero_scenarios(tmp_path, monkeypatch):
    """The declared 'always-succeeding empty command' face (input-and-
    precedence P1/P5 shape): cmd `true` exits 0, and the parser's zero-signal
    rule names it an explicit red (KI-116: no silent escape hatch) — the
    judged tree is still named on the receipt. NOTE: the empty-cmd refusal
    text promises `e.g. true` reads green with zero scenarios; the parser's
    zero-signal red is the ruling behavior — the wording drift is reported,
    not silently re-judged here."""
    lane, ws = _mk_lane(tmp_path, container_decl=True)
    (lane / "verify.yaml").write_text(
        "schema: v1\n"
        "lanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: true\n", encoding="utf-8")
    res = verify_lane.run({"lane": "integ", "path": str(lane),
                           "write_set": list(ws)})
    assert res["green"] is False, (res.get("green"), res.get("err"))
    assert "zero scenario signal" in (res.get("err") or ""), res.get("err")
    assert res["root"] == str(lane.resolve())
    assert res["root_source"] == "explicit path"

def test_receipt_is_json_serializable_on_every_exit_path(tmp_path, monkeypatch):
    """Regression lock (t261019-45 arbitrate gen0 code-fault): the receipt is a
    JSON contract — tools_registry._summarize json.dumps it, and a Path riding
    in root_candidates killed the summarizer and turned a judged round into an
    invisible ran=0. Every truth-table exit path must serialize."""
    import json as _json
    import shutil as _sh
    # green path (stub executor)
    lane, ws = _mk_lane(tmp_path, container_decl=True)
    monkeypatch.setenv("SANDBAR_GATE_BASELINE", "1")
    monkeypatch.setattr(verify_lane, "_run_baseline",
                        _fake_healthy_baseline(lane))
    def _sub(name):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        return d
    # missing everywhere
    lane2, ws2 = _mk_lane(_sub("c2"), container_decl=False,
                          members=(("member_a", False), ("member_b", False)))
    # empty cmd
    lane3, ws3 = _mk_lane(_sub("c3"), container_decl=True)
    (lane3 / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n",
        encoding="utf-8")
    # corrupt manifest
    lane4, ws4 = _mk_lane(_sub("c4"), container_decl=False)
    (lane4 / ".sandbar" / "repo_worktrees.json").write_text("{ not json",
                                                            encoding="utf-8")
    # non-string write-set entry (named red)
    lane5, ws5 = _mk_lane(_sub("c5"), container_decl=True)
    # zero-signal red (cmd true)
    lane6, ws6 = _mk_lane(_sub("c6"), container_decl=True)
    (lane6 / "verify.yaml").write_text(
        "schema: v1\n"
        "lanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: true\n", encoding="utf-8")
    cases = [
        (lane, ws, {"SANDBAR_GATE_BASELINE": None}),   # env already set above
        (lane2, ws2, {}),
        (lane3, ws3, {}),
        (lane4, ws4, {}),
        (lane5, ["member_a/game.js", 42], {}),
        (lane6, ws6, {}),
    ]
    for ln, w, _env in cases:
        res = verify_lane.run({"lane": "integ", "path": str(ln),
                               "write_set": list(w)})
        s = _json.dumps(res, ensure_ascii=False)   # must not raise
        assert "root" in res and "root_candidates" in res, sorted(res)
        for c in res["root_candidates"]:
            assert isinstance(c["tree"], str), c
        assert isinstance(res["root"], str), res["root"]
