#!/usr/bin/env python3
"""sc_t261009_01_gate_preexisting_red_face.py -- t261009-01 acceptance 2/3.

Contract under test (user-visible, the gate's NEW receipt face): when the lane
gate sees a red whose name the known-red ledger cannot answer, the gate probes
a LIVE CLEAN BASELINE at the lane base and the receipt names the split:
  D1 a red that reproduces on the clean base (baseline answer "red") is named
     pre_existing_main in the receipt face -- a record, not this lane's
     blocker (failure_protocol.decide: baseline_red existing debt);
  D2 a red the clean base does NOT reproduce (baseline green / absent / no
     answer) is NEVER read as pre-existing -- it stays a blocker;
  D3 every no-answer path (baseline missing / disabled probe) keeps the
     conservative blocker direction -- fail-closed, never a silent pass;
  D4 malformed input (non-dict cases, blank names) is skipped without crash;
  D5 the probe is bounded: names beyond the cap get no probe but stay listed
     as blockers;
  D6 the probe is env-gated: with the gate off, the face reports enabled=False
     and classifies nothing pre-existing.

Landed shape (arbitrate gen0 note): the discriminator is NOT a standalone
classify helper -- it is single-sourced in server/engine/failure_protocol.py
(baseline_answers / decide) and surfaces in the verify receipt as
`main_side_reds`, built by verify_lane's receipt-face builder. This scenario
pins that landed public contract chain (answers -> receipt face -> decide);
no internals beyond those module surfaces, no fixture repo, no subprocess,
offline seconds.

Three-state exit contract: FAIL>0 -> exit 1; module/function absent = FAIL
named (pre-implement red expected); pure stdlib, no environment face. Must be
green at arbitrate/merge.
"""
import importlib.util
import os
import sys

FP_PATH = os.path.join("server", "engine", "failure_protocol.py")
VL_PATH = os.path.join("server", "tools", "verify_lane.py")

passed = 0
failed = 0
env_fail = 0


def ok(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


def env_down(label):
    global env_fail
    env_fail += 1
    print(f"  ENV_FAIL {label}")


def section(t):
    print(f"\n== {t}")


def load(path, label):
    if not os.path.exists(path):
        env_down(f"{label} missing: {path}")
        return None
    spec = importlib.util.spec_from_file_location(label.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def case(name, status="fail", **kw):
    d = {"name": name, "suite": "s", "status": status, "cause": "self",
         "reason": "r", "dur_s": 0.1, "attempt": 1, "started": 0,
         "git_sha": "a" * 40, "evidence": "", "artifacts": []}
    d.update(kw)
    return d


def main():
    section("landed contract surfaces are reachable")
    fp = load(FP_PATH, "failure_protocol-under-test")
    vl = load(VL_PATH, "verify_lane-under-test")
    ok(fp is not None and hasattr(fp, "baseline_answers") and hasattr(fp, "decide"),
       "failure_protocol.baseline_answers/decide importable (absent = FAIL named)")
    ok(vl is not None and hasattr(vl, "_main_side_face") and hasattr(vl, "_main_side_probe_plan"),
       "verify_lane main_side_reds receipt face importable (absent = FAIL named)")
    if fp is None or vl is None:
        print(f"\nSUMMARY pass={passed} fail={failed} env_fail={env_fail} na=0")
        return 1

    red_a = case("red-reproduces-zz")
    red_b = case("red-not-reproduced-zz")
    base_cases = [case("red-reproduces-zz")]          # clean base runs this name RED
    base_green = [case("red-not-reproduced-zz", status="pass")]

    section("D1 reproduces on the clean base -> named pre_existing_main")
    ans = fp.baseline_answers([red_a, red_b], base_cases + base_green, {}, {}, True)
    ok(ans.get("red-reproduces-zz") == "red", "baseline answer for reproducing red is red")
    ok(ans.get("red-not-reproduced-zz") == "green", "baseline answer for non-reproducing red is green")
    face = vl._main_side_face(list(ans), ans, list(ans), [], 0.0, True)
    ok(face.get("pre_existing_main") == ["red-reproduces-zz"],
       f"receipt names pre_existing_main (got {face.get('pre_existing_main')})")

    section("D2/D3 fail-closed: no answer is never pre-existing, blocker stays")
    ok(face.get("still_lane_blockers") == ["red-not-reproduced-zz"],
       "non-reproducing red stays in still_lane_blockers")
    verdict_block = fp.decide(red_b, set(), True)     # clean base does NOT carry it red
    ok(verdict_block.get("verdict") == "block", "decide blocks a red the clean base does not reproduce")
    verdict_record = fp.decide(red_a, {"red-reproduces-zz"}, True)
    ok(verdict_block.get("verdict") == "block" and verdict_record.get("verdict") != "block",
       "the same red flips blocker->record only via the baseline-red set")
    no_answer = fp.baseline_answers([red_a], [], {}, {}, False)   # baseline missing
    ok(no_answer == {}, "missing baseline yields no answers (never fabricated red)")
    face_na = vl._main_side_face(["red-reproduces-zz"], {}, ["red-reproduces-zz"], [], 0.0, True)
    ok(face_na.get("pre_existing_main") == []
       and "red-reproduces-zz" in face_na.get("still_lane_blockers", []),
       "unanswered red stays a blocker in the receipt face")

    section("D4 malformed input skipped, no crash")
    try:
        messy = fp.baseline_answers(
            [{"no": "name"}, "junk", None, case("  ")], base_cases, {}, {}, True)
        ok(messy == {}, "non-dict/blank-name lane cases skipped without crash")
    except Exception as e:                            # noqa: BLE001
        ok(False, f"malformed input crashed baseline_answers: {e}")
    try:
        face_none = vl._main_side_face(None, None, None, None, None, None)
        ok(face_none.get("pre_existing_main") == [], "receipt face tolerates None inputs")
    except Exception as e:                            # noqa: BLE001
        ok(False, f"receipt face crashed on None inputs: {e}")

    section("D5 bounded probe plan: capped-out names stay blockers")
    probe_plan = vl._main_side_probe_plan(
        [f"amb-{i}-zz" for i in range(6)], [f"amb-{i}-zz" for i in range(6)] + ["other-red"],
        True, cap=4)
    targeted, capped, applied = probe_plan
    ok(applied is True and len(targeted) == 4 and capped == ["amb-4-zz", "amb-5-zz"],
       f"probe capped at 4, extras surfaced ({targeted} | {capped})")
    face_c = vl._main_side_face(capped, {}, [], capped, 0.0, True)
    ok(face_c.get("capped_out_stay_blockers") == ["amb-4-zz", "amb-5-zz"]
       and face_c.get("pre_existing_main") == [],
       "capped-out names listed as stay-blockers, never pre-existing")

    section("D6 probe env gate: off -> face disabled, nothing pre-existing")
    off_plan = vl._main_side_probe_plan(["a-zz"], ["a-zz"], False)
    ok(off_plan[2] is False, "probe plan honours the off switch (applied=False)")
    face_off = vl._main_side_face(["a-zz"], {}, [], [], 0.0, False)
    ok(face_off.get("enabled") is False and face_off.get("pre_existing_main") == [],
       "probe disabled -> face enabled=False, no pre-existing classification")

    print(f"\nSUMMARY pass={passed} fail={failed} env_fail={env_fail} na=0")
    if failed > 0:
        return 1
    if env_fail > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
