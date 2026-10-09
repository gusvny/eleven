#!/usr/bin/env python3
"""sc_t26100915_quiet_baseline_identity.py — load-sensitive check identity, both
carriers, against the real roster (t261009-15, KI-072).

Run directly: python3 integration/t261009-15/sc_t26100915_quiet_baseline_identity.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches 3099.

Incident (KI-072 instance 1, 261009): ticket t261009-11 was stopped at merge_check
by verify_lane code red=1 -- FAILED
server/engine/tests/test_t260901_25_t03_reap_process_group.py::test_t260901_25_t03_reap_process_group
while five suites ran concurrently; the same check alone on a quiet main passed in
1.29s. The load-sensitive check is the reaping scenario
integration/t260901-25/t03_reap_process_group.py, now ALSO run wrapped as an engine
unit test — one flake, two carriers, and the only booking place
(server/engine/inspection_lane_watchdog.py prefix table) matches neither the
wrapper path nor any roster row.

This scenario owns the cross-role seam that no developer unit test can own, because
both sides of the seam are integration-role assets (the booked roster row) or
user-acceptance facts (the two carrier paths from the incident):

  A  carrier-independent identity — the engine's canonical check name maps BOTH
     carrier spellings of the same incident (the wrapper nodeid and the scenario
     path) to ONE key. This is ticket requirement (3); it is the user acceptance
     fact "the same script must be recognised either way", judged against the real
     incident paths, not synthetic ones.
  B  roster agreement — the integration-roster row booked for this instance
     (verdict=isolated), passed through the SAME engine normalizer, yields the same
     key as both carriers. If engine and roster ever drift (a rename on either
     side), the quiet-baseline mechanism goes silently inert — this subcase turns
     that drift red. The row's presence is a system-state condition (integration
     books it on this ticket), so absence is N/A, not fail.
  C  both carriers exist on disk and reference each other — the wrapper unit test
     drives the real scenario script; if either file moves, the identity contract
     has no referent and must be red, not silently skipped.

Deliberately NOT asserted here (intent split, no duplication): normalizer unit
truth tables, receipt extraction byte-identity, quiet rerun subprocess semantics,
routing truth tables — developer L1 (server/engine/tests/test_t261009_15_quiet_baseline.py)
owns those with stubs. This entry owns the real-asset seam only. It also
deliberately does NOT run the wrapper test: running a known load-sensitive check
inside a gate is exactly the fault mode under repair (KI-072); the quiet verdict is
the engine's job at merge_check, not a gate scenario's.

Engine module unavailable = ENV_FAIL exit 2. Pre-implementation tree = red
(TDD signal, same discipline as t261008-24); green required at the integration
gate / merge.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

WRAPPER = os.path.join(REPO, "server", "engine", "tests",
                       "test_t260901_25_t03_reap_process_group.py")
SCENARIO = os.path.join(REPO, "integration", "t260901-25", "t03_reap_process_group.py")
ROSTER = os.path.join(REPO, "integration", "known-red-baseline.json")

WRAPPER_NODEID = ("server/engine/tests/test_t260901_25_t03_reap_process_group.py"
                  "::test_t260901_25_t03_reap_process_group")
SCENARIO_PATH = "integration/t260901-25/t03_reap_process_group.py"

sys.path.insert(0, os.path.join(REPO, "server", "engine"))

try:
    import agent_activities as aa
except Exception as exc:  # engine module unimportable = environment red
    print("ENV_FAIL: server/engine agent_activities module unavailable (%s)" % exc)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

normalize = getattr(aa, "canonical_check_name", None)

PASS = 0
FAIL = 0
NA = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def na(label):
    global NA
    NA += 1
    print("  N/A  %s" % label)


def section(title):
    print("\n%s" % title)


# ---------- A. carrier-independent identity on the real incident paths ----------
section("A canonical_check_name — wrapper nodeid and scenario path agree")
if normalize is None:
    ok(False, "engine exposes canonical_check_name (missing = pre-implementation "
              "tree, TDD signal)")
else:
    try:
        k_wrap = normalize(WRAPPER_NODEID)
        k_scen = normalize(SCENARIO_PATH)
        ok(isinstance(k_wrap, str) and k_wrap != "", "wrapper nodeid normalizes to a non-empty key (%r)" % k_wrap)
        ok(k_wrap == k_scen,
           "both carriers of the same incident map to ONE key (wrap=%r scen=%r)"
           % (k_wrap, k_scen))
        ok(normalize(WRAPPER_NODEID) == normalize(WRAPPER_NODEID), "normalizer is deterministic")
        ok(normalize("") not in (k_wrap,), "empty input does not collide with the incident key (fail-closed, no false exemption)")
    except Exception as exc:
        ok(False, "normalizer raised on real carrier input (%s: %s)" % (type(exc).__name__, exc))

# ---------- B. roster row agreement, judged through the same normalizer ----------
section("B booked roster row — integration asset and engine agree on the key")
try:
    with open(ROSTER, "r", encoding="utf-8") as f:
        roster = json.load(f)
    entries = roster.get("entries")
    if normalize is None:
        na("roster agreement needs the engine normalizer (judged in A)")
    elif not isinstance(entries, list):
        ok(False, "roster entries is a list (got %s)" % type(entries).__name__)
    else:
        isolated = [e for e in entries
                    if isinstance(e, dict) and e.get("verdict") == "isolated"
                    and "reap" in str(e.get("name", ""))]
        if not isolated:
            na("no isolated roster row booked for the reap instance yet "
               "(integration books it on this ticket; engine stays inert until then)")
        else:
            match = [e for e in isolated
                     if normalize(str(e.get("name", ""))) == normalize(SCENARIO_PATH)]
            ok(bool(match),
               "booked isolated row normalizes to the carrier key (rows=%r)"
               % [e.get("name") for e in isolated])
            booked = match[0] if match else isolated[0]
            ok(bool(booked.get("owner")) and bool(booked.get("retire_when")),
               "booked row carries owner and retire_when (roster discipline)")
except (OSError, ValueError) as exc:
    ok(False, "roster readable as JSON at integration/known-red-baseline.json (%s)" % exc)

# ---------- C. both carriers exist and reference each other ----------
section("C carrier files — the identity contract has real referents")
ok(os.path.isfile(SCENARIO), "integration scenario exists (%s)" % SCENARIO_PATH)
ok(os.path.isfile(WRAPPER), "engine wrapper unit test exists")
if os.path.isfile(WRAPPER) and os.path.isfile(SCENARIO):
    try:
        with open(WRAPPER, "r", encoding="utf-8") as f:
            body = f.read()
        ok("t03_reap_process_group" in body,
           "wrapper drives the reaping scenario (carrier link present)")
    except OSError as exc:
        ok(False, "wrapper readable (%s)" % exc)

# ---------- R. roster integrity: every booked_sha must resolve (261009 incident) ----------
# 事故（261009 16:1x，本岗自伤）：新挂一行时 booked_sha 手写补齐成一个"看着像"的 40 位串，
# 红册卫生测试只查形状 ⇒ 放行；引擎侧数据驱动测试取"最新戳"行当探针、拿它的 sha 解基点
# ⇒ 解不出 ⇒ 全仓 verify_lane code 面转红 ⇒ 各泳道 merge_check 被堵。
# 本段把该护栏搬进**已在册的场景**（不新增场景、不动锚点表）：红册每一行的 booked_sha
# 必须真能解出来；git/仓缺席=具名失败（fail-closed，不静默跳过）。
section("R roster integrity — booked_sha must resolve to a real commit")
try:
    import subprocess as _sp
    with open(ROSTER, "r", encoding="utf-8") as f:
        _book = json.load(f)
    _bad = []
    for _e in (_book.get("entries") or []):
        _s = str((_e or {}).get("booked_sha") or "")
        if not _s:
            _bad.append((str((_e or {}).get("name")), _s, "missing"))
            continue
        _r = _sp.run(["git", "cat-file", "-e", _s + "^{commit}"],
                     capture_output=True, cwd=str(REPO))
        if _r.returncode != 0:
            _bad.append((str((_e or {}).get("name")), _s, "unresolvable"))
    ok(not _bad,
       "every roster row's booked_sha resolves in this tree (%d rows, bad=%s)"
       % (len(_book.get("entries") or []), _bad[:3]))
except (OSError, ValueError) as exc:
    ok(False, "roster readable for the integrity leg (%s)" % exc)

# ---------- summary ----------
total = PASS + FAIL + NA
print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
if total == 0 or (PASS == 0 and FAIL == 0):
    print("ALL_NA: no judgeable subcase — scenario design problem, red per contract")
    sys.exit(1)
sys.exit(1 if FAIL else 0)
