#!/usr/bin/env python3
"""sc_t26100965_bundle_out_file_entry_faces.py — t261009-65: the two held
gate-face edits, judged from the PUBLIC path_gates faces a lane's deliverables
actually go through (KI-01M4HR0ECTNFS4RWSQ8M0GE17J regression lock).

Grey-box L3, offline seconds, pure stdlib, zero docker/Temporal/browser,
never touches 3099/7233. Intent (what no existing scenario owns):
  - t261009-38-bundle-out-gate-land pins the DIRECTORY write-set shape
    (ws names the src prefix). t261009-53 measured the FILE-ENTRY shape:
    a write set naming three concrete src/client files left the rebuilt
    lib/client.{cjs,js} refused TWICE (quarantine unauth-implement-gen0 /
    unauth-arbitrate-gen0). This scenario owns that shape end to end.
  - Edit 1: bundle_out_face / bundle_out_prefixes accept entries UNDER the
    declared src prefix (one judge, both faces must agree — no second truth).
  - Edit 2: arbitrate (kind=test_face) gains the _bundle_out_ok() fallback
    the write_set/join/self_heal kinds already carry, so a rebuilt out-prefix
    file written during arbitrate is a NAMED pass (BUNDLE_OUT_FACE_NOTE:
    file (src prefix)), not an "unauthorized write" face.
  - Fail-closed shapes stay shut: empty/None write set, missing/malformed
    declaration, an out file outside every declared prefix, a src prefix the
    write set does not touch, and the OLD directory shape unchanged.

Ruling note (evidence for the legacy-pin reversal): the receipt fallback in
the test_face branch (`integration/<ticket>/`) is REMOVED by host-ruled Edit 2
— that is the ruling reversing a spec, not a test fudge; this scenario does
not pin the removed clause either way, it pins the ruled named-pass contract.

Run: python3 integration/t261009-65/sc_t26100965_bundle_out_file_entry_faces.py
(cwd = repository root). path_gates unimportable = ENV_FAIL exit 2.
Implementation not landed = red, named per check (TDD signal); the
integration gate and merge must be green.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

try:
    import path_gates as pg  # noqa: E402
except Exception as exc:  # unimportable engine module = environment, not a red
    print("ENV_FAIL: server/engine/path_gates.py unimportable: %r" % exc)
    sys.exit(2)

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL  %s" % label)


def section(title):
    print("\n%s" % title)


SRC = "server/plugins/workbench/src/client"
OUT = "lib"
PAIRS = [(SRC, OUT)]
WS_FILES = [
    "server/plugins/workbench/src/client/lane-map.tsx",
    "server/plugins/workbench/src/client/lane-map-model.ts",
    "server/plugins/workbench/src/client/index.tsx",
]


def main():
    section("A. the t261009-53 incident shape: file-entry write set admits the rebuilt out prefix")
    for f in ("lib/client.cjs", "lib/client.js"):
        ok(pg.bundle_out_face(f, WS_FILES, PAIRS) == SRC,
           "bundle_out_face admits %s with src prefix returned (was unauth-%s-gen0)" % (f, "implement/arbitrate"))
    ok(pg.bundle_out_prefixes(WS_FILES, PAIRS) == ["lib"],
       "bundle_out_prefixes == ['lib'] (same predicate, one judge, both faces agree)")

    section("B. unchanged / refused shapes")
    ok(pg.bundle_out_face("lib/client.cjs", [SRC + "/"], PAIRS) == SRC,
       "old directory shape ws ['" + SRC + "/'] still admits (no regression)")
    ok(pg.bundle_out_face("dist/client.cjs", WS_FILES, PAIRS) is None,
       "an out file outside every declared prefix stays refused")
    ok(pg.bundle_out_face("lib/client.cjs", ["server/plugins/workbench/other/x.ts"], PAIRS) is None,
       "a src prefix the write set does not touch stays refused (out side adds nothing the src side does not guard)")
    ok(pg.bundle_out_face("lib/client.cjs", WS_FILES, [(SRC, "lib"), ("src/other", "dist")]) == SRC,
       "two pairs: the matching pair is found, the non-matching pair changes nothing")

    section("C. fail-closed faces (empty / missing / malformed)")
    ok(pg.bundle_out_face("lib/client.cjs", [], PAIRS) is None, "empty write set -> None")
    ok(pg.bundle_out_face("lib/client.cjs", None, PAIRS) is None, "None write set -> None")
    ok(pg.bundle_out_face("lib/client.cjs", WS_FILES, None) is None, "None declaration -> None")
    ok(pg.bundle_out_face("lib/client.cjs", WS_FILES, []) is None, "empty declaration -> None")
    ok(pg.bundle_out_face("lib/client.cjs", WS_FILES, [("only-src",)]) is None,
       "malformed pair (len!=2) -> None, no crash")
    ok(pg.bundle_out_prefixes([], PAIRS) == [] and pg.bundle_out_prefixes(None, PAIRS) == []
       and pg.bundle_out_prefixes(WS_FILES, None) == [],
       "bundle_out_prefixes fail-closed mirrors bundle_out_face (no second truth)")

    section("D. arbitrate (test_face) gains the named bundle-out fallback")
    notes = []
    okv, viol, reason = pg.judge_stage_paths(
        "arbitrate", ["lib/client.cjs"], write_set=WS_FILES,
        ticket_id="t261009-65", notes_out=notes, bundle_pairs=PAIRS)
    ok(okv and not viol and not reason,
       "a rebuilt out-prefix file written during arbitrate is ALLOWED (was unauthorized_path)")
    ok(any(n.startswith(pg.BUNDLE_OUT_FACE_NOTE) and "lib/client.cjs" in n and SRC in n
           for n in notes),
       "the pass is NAMED: %s: file (src prefix), never silent" % pg.BUNDLE_OUT_FACE_NOTE)
    okv, viol, reason = pg.judge_stage_paths(
        "arbitrate", ["dist/client.cjs"], write_set=WS_FILES,
        ticket_id="t261009-65", notes_out=[], bundle_pairs=PAIRS)
    ok(not okv and reason == "unauthorized_path",
       "an out-of-prefix file during arbitrate still reds unauthorized_path")
    okv, viol, reason = pg.judge_stage_paths(
        "arbitrate", ["tests/test_ok.py"], write_set=WS_FILES,
        ticket_id="t261009-65", notes_out=[], bundle_pairs=PAIRS)
    ok(okv, "the test_face kind's own face (tests/ file) still passes first")
    okv, viol, reason = pg.judge_stage_paths(
        "arbitrate", ["lib/client.cjs"], write_set=[],
        ticket_id="t261009-65", notes_out=[], bundle_pairs=PAIRS)
    ok(not okv, "empty write set at arbitrate -> still refused (fail-closed)")
    okv, viol, reason = pg.judge_stage_paths(
        "arbitrate", ["lib/client.cjs"], write_set=WS_FILES,
        ticket_id="t261009-65", notes_out=[], bundle_pairs=None)
    ok(not okv and reason == "unauthorized_path",
       "no declaration at arbitrate -> refused, nothing widens (fail-closed)")

    section("E. the ruled reversal is visible in the promised desc text")
    desc = pg._STAGE_FACE_DESC["test_face"]
    ok("bundle-out-face" in desc and "named" in desc,
       "_STAGE_FACE_DESC['test_face'] carries the widened face text (user-visible contract line)")

    print("\nRESULT: %d passed, %d failed" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
