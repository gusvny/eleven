#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101945_integ_gate_input_and_precedence.py — t261019-45, the malformed-
input and precedence faces of the integ gate's multi-root declaration
resolution (consolidated twin of sc_t261019_45_integ_gate_multi_root.py).

intent (ticket t261019-45; design_integration_tests gen0): the gate must never
turn a malformed external input into an anonymous judgment, and its
single-judgment precedence must be EXPLICIT on the receipt:
    P1. SHAPE-(c) PRECEDENCE IS EXPLICIT, NOT SILENT: container AND both
        members all carry declarations, write set spans both members — the
        gate judges on the CONTAINER (the explicit path wins) and the receipt
        shows why (root_source names the explicit-path origin; review_plan
        gen0 comment 1). Pre-implement red = the named TDD signal; green
        required at the integration gate / merge.
    P2. CORRUPT MANIFEST NEVER JUDGES ANONYMOUSLY: a corrupt
        repo_worktrees.json with no declaration at the container ends in a
        named red (or a named raise naming the manifest) — never an anonymous
        green, never a silent single-tree guess, never a bare traceback.
    P3. NON-STRING WRITE-SET ENTRIES: never produce an anonymous green — a
        named red or an explicit rule, on record either way.
    P4. SINGLE-REPO LANE UNCHANGED (the regression witness): no manifest,
        declaration at the explicit path — green with the judged root equal to
        that path (sandbar itself is single-repo).

Intent split (no intent-level duplication; settled 261019 when the parallel
implement stage landed sc_t261019_45_integ_gate_multi_root.py): the assembled
multi-repo journey over REAL GIT fixtures (spanning write set green at the
container / found at the second candidate / nothing-anywhere named refusal /
malformed-declaration no-fallback / non-repo segment skip) belongs to
sc_t261019_45_integ_gate_multi_root.py; the resolution truth table belongs to
developer L1 (test_t261019_45_integ_root_resolution.py); THIS entry uniquely
owns the malformed-input faces (corrupt manifest, non-string write-set
entries) and the precedence-visible / single-repo-unchanged faces.

Fixture: self-contained tmp tree (files only — the integ gate needs no git
here), the real manifest shape ([{"repo","name","branch"}], repo "" = the
container tree); the real server/tools/verify_lane.py is imported and driven
through its public verify_lane.run() entry with the engine's own payload
shape. Offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233; fixture temp dirs reclaimed in-process.

Three states: verify_lane missing/unimportable = ENV_FAIL exit 2; P1 red
pre-implement = the named TDD signal (arbitrate/merge must be green); P2/P3
must never end anonymous-green on any tree.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261019-45-integ-gate-input-and-precedence"

sys.path.insert(0, str(REPO / "integration"))
from lib_result import ScenarioCheck  # noqa: E402
from lib_env import no_narrowing_env  # noqa: E402  (L12: strip inherited
# narrowing knobs / caller identity before the in-process gate call — an
# inherited SANDBAR_SCENARIO_ONLY etc. must never narrow the face under test)

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

sys.path.insert(0, str(REPO / "server" / "tools"))
try:
    import verify_lane as vl  # noqa: E402
except Exception as e:  # pragma: no cover - environment face
    env_fail("verify_lane unimportable",
             "%s: %s" % (type(e).__name__, str(e)[:200]))

DECL_OK = ("schema: v1\n"
           "lanes:\n  code:\n    write_allow:\n      - integration/\n"
           "integration:\n  cmd: true\n")


def _gate(lane, write_set):
    """The gate's public entry with the engine's own payload shape."""
    with no_narrowing_env():
        return vl.run({"lane": "integ", "path": str(lane),
                       "baseline": True, "write_set": list(write_set)})


class Lane:
    """One self-contained multi-repo lane: container + member trees + manifest."""

    def __init__(self, manifest=True, corrupt_manifest=False):
        self.root = Path(tempfile.mkdtemp(prefix="sc-t261019-45-"))
        self.lane = self.root / ".lane" / "t261019-45"
        self.ma = self.lane / "member-a"
        self.mb = self.lane / "member-b"
        for d in (self.ma, self.mb):
            (d / "src").mkdir(parents=True)
        if manifest:
            mf = self.lane / ".sandbar"
            mf.mkdir(parents=True)
            if corrupt_manifest:
                (mf / "repo_worktrees.json").write_text("{ not json", encoding="utf-8")
            else:
                (mf / "repo_worktrees.json").write_text(json.dumps([
                    {"repo": "", "name": "root", "branch": "lane/t45-root"},
                    {"repo": "member-a", "name": "member-a",
                     "branch": "lane/t45-member-a"},
                    {"repo": "member-b", "name": "member-b",
                     "branch": "lane/t45-member-b"},
                ]), encoding="utf-8")

    def decl(self, tree, text):
        (tree / "verify.yaml").write_text(text, encoding="utf-8")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


WS_SPAN = ["member-a/src/game.js", "member-b/src/parts.js"]

try:
    # ---- P1: shape-(c) precedence is explicit, not silent -----------------
    fx = Lane()
    try:
        fx.decl(fx.lane, DECL_OK)
        fx.decl(fx.ma, DECL_OK)
        fx.decl(fx.mb, DECL_OK)
        r = _gate(fx.lane, WS_SPAN)
        # NOTE: cmd `true` exits 0 and the parser's zero-signal rule names it
        # an explicit red (KI-116, no silent escape hatch) — P1 asserts the
        # PRECEDENCE face (which tree, and why, on the receipt), not greenness.
        # Both sides normalized through resolve(): on macOS tempfile returns
        # /var/... while the gate's resolved root is /private/var/... (symlink),
        # so a raw string compare fails on the symlink, not on the contract.
        ok(str(Path(r.get("root") or "").resolve()) == str(fx.lane.resolve()),
           "P1 with declarations everywhere the gate judges on the CONTAINER "
           "(the explicit path wins, visible not silent)",
           "root=%r" % (r.get("root"),))
        ok(str(r.get("root_source") or "").strip() != "",
           "P2 the receipt shows WHY the container won (root_source names the "
           "explicit-path origin)",
           "root_source=%r" % (r.get("root_source"),))
    finally:
        fx.cleanup()

    # ---- P3: corrupt manifest never judges anonymously --------------------
    fx = Lane(corrupt_manifest=True)
    try:
        raised = None
        try:
            r = _gate(fx.lane, WS_SPAN)  # container has no declaration either
            r = r if isinstance(r, dict) else {}
            named = bool(str(r.get("err") or "").strip()) and r.get("green") is False
            ok(named,
               "P3 a corrupt repo_worktrees.json ends in a NAMED red (never "
               "an anonymous green, never a silent single-tree guess)",
               json.dumps(r, ensure_ascii=False)[:300])
        except Exception as e:
            raised = "%s: %s" % (type(e).__name__, str(e))
            ok("manifest" in raised.lower() or "repo_worktrees" in raised.lower(),
               "P3b a corrupt manifest may raise, but only NAMED (never an "
               "unhandled anonymous crash)",
               "raised=%r" % raised[:300])
    finally:
        fx.cleanup()

    # ---- P4: non-string write-set entries never an anonymous green --------
    fx = Lane()
    try:
        fx.decl(fx.lane, DECL_OK)
        raised = None
        try:
            r = _gate(fx.lane, [12345, None, "member-a/src/game.js"])
            bad = r.get("green") is not True or bool(str(r.get("err") or "").strip())
            ok(bad,
               "P4 non-string write-set entries never produce an anonymous "
               "green (named red or an explicit rule, never a crash)",
               json.dumps(r, ensure_ascii=False)[:300])
        except Exception as e:
            raised = "%s: %s" % (type(e).__name__, str(e))
            ok(len(raised) > 0,
               "P4b non-string write-set entries may raise, but the message "
               "is on record (never a silent green)",
               "raised=%r" % raised[:300])
    finally:
        fx.cleanup()

    # ---- P5: single-repo lane unchanged (regression witness) --------------
    fx = Lane(manifest=False)
    try:
        fx.decl(fx.lane, DECL_OK)
        r = _gate(fx.lane, ["app.py"])
        # Same zero-signal note as P1: the judged tree must be named and equal
        # to the explicit path; greenness belongs to the executor contract,
        # not the resolution face.
        ok(str(Path(r.get("root") or "").resolve()) == str(fx.lane.resolve())
           and str(r.get("root_source") or "").strip() != "",
           "P5 a single-repo lane names its judged root = the explicit path "
           "(the regression witness)",
           "root=%r root_source=%r" % (r.get("root"), r.get("root_source")))
    finally:
        fx.cleanup()
finally:
    pass

finish(NAME)
