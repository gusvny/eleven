#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261029-76 L3: a retired premise is excluded-and-NAMED, never judged silently.

Ticket t261029-76. Host order 261027 retired docker from the test estate, so two
line-round cases could never pass again; every round booked two env_fail entries
and the red froze the develop-buffer line on a premise that no longer exists
(measured 2026-10-29, round run-01M63CEX71YDHNH56E612BX86C: ran=688 pass=685
fail=1 env_fail=2, freeze frz-01M63HN38C3CFFY5M8WE8H8FAR). This case owns the
mechanism's contract, on public faces only:

  S  the SHIPPED data and roster agree: integration/retired-premises.json parses,
     every excluded entry is still IN the registry (no case may disappear), each
     exclusion names a declared premise with its retirement order and a reason,
     and both measured entries carry a disposition (one EXCLUDED, one
     RE-POINTED).
  X  exclusion BY CONSTRUCTION with a STUB premise: a real suite round over a
     stub registry, where a stub entry's premise is retired -> the entry is NOT
     run (no PASS, no ENV_FAIL, no row), it is NAMED on the round's receipt with
     its premise and reason, it is out of the expected roster count, and the
     round is GREEN under BOTH verdict rules (the engine's run_verdict and the
     face's stricter rule) - the frozen-line defect does not reproduce.
  N  the NEGATIVE BRANCH BITES: the same construction with a LIVE premise (an
     entry that is not on the retired list) and a failing environment leg ->
     ENV_FAIL is booked exactly as before (not_checked=1, the name in
     env_red_names) and the round is RED under both rules. No blanket "env_fail
     does not count" behaviour exists.
  V  the two decisions keep two NAMES: the retired-premise line is not the
     pool-skip vocabulary, and a pool-excluded round prints the pool vocabulary
     and no retired-premise line.
  R  the RECEIPT names the exclusion end to end: the real line_round_runner
     relays it onto the run header and onto the terminal face (face.json), names
     it on stderr, and still reds a round whose cases carry a live env_fail.
  D  the re-pointed observation face has TEETH: the fixture's recording `docker`
     stand-in records real invocations and flags container-creating ones, so
     "zero containers ran" is observable without a daemon and would red a real
     fallback.

Grey-box: assertions bind to the round's public vocabulary (its summary/header/
face fields, its named lines, the registry data file) and to the docker CLI argv
contract - never to implementation internals. Offline, seconds, zero docker,
zero Temporal server, no browser, never touches 3099/7233/8233. The nested stub
rounds run with their own ledger dir, lease lock dir and projects root, so they
cannot write into the project's real ledgers.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "integration"
for _p in (str(INTEG), str(INTEG / "t260910-12"), str(ROOT / "server" / "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lib_retired_premise as RP                     # noqa: E402
import lib_round_face as RF                          # noqa: E402
import lib_tmp_reclaim                                # noqa: E402
import develop_certify as DC                         # noqa: E402
from lib_env import clean_narrowing_env                # noqa: E402
from lib_herd_case import check, envfail, finish      # noqa: E402
from lib_herd_case import container_calls, docker_calls, docker_shim, shim_env  # noqa: E402

STUB_PREMISE = "stub-retired-premise"
STUB_ORDER = "261027"
STUB_REASON = "premise retired 261027: stub premise retired for this case"
STUB_RETIRED = "stub-retired-entry"
STUB_LIVE = "stub-live-entry"
STUB_PASS = "stub-pass-entry"

#: The stub registry driver: run the REAL integration/run_scenarios.py over a
#: stub registry. The registry is data, the executor is the production one, so
#: the exclusion path exercised here is the path a real round takes.
DRIVER = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("rs_stub_round", os.environ["STUB_RS"])
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
rs.SCENARIOS = [tuple(e) for e in
                json.load(open(os.environ["STUB_REGISTRY"], encoding="utf-8"))]
sys.exit(rs.main())
'''

#: The stub SUITE for the runner legs: it writes its run record through the REAL
#: store (so the header the runner relays is one the store validated) and prints
#: the round's INTEG_SUMMARY with the retired-premise records.
STUB_SUITE = r'''
import datetime, json, os, sys, time
sys.path.insert(0, os.environ["STUB_INTEG"])
import scenario_ledger as mod
mode = os.environ.get("STUB_SUITE_MODE", "green")
# `green`: two passes. `envfail`: one pass + one environment failure (the LIVE
# premise leg). `fail`: one pass + one product failure. The counts must be
# self-consistent (ran == passed + failed + env_failed) or the store refuses the
# header - that refusal is the store's, not this fixture's to bypass.
counts = {"green": {"ran": 2, "passed": 2, "failed": 0, "env_failed": 0},
          "envfail": {"ran": 2, "passed": 1, "failed": 0, "env_failed": 1},
          "fail": {"ran": 2, "passed": 1, "failed": 1, "env_failed": 0}}[mode]
spec_cases = [
    {"name": "stub-a", "status": "pass", "suite": "stub", "dur_s": 0.01},
    {"name": "stub-b", "status": {"green": "pass", "envfail": "env_fail",
                                  "fail": "fail"}[mode], "suite": "stub",
     "dur_s": 0.01},
]
run_id = mod.mint_run_id()
ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
rows = [{
    "ts": ts, "commit": os.environ["STUB_COMMIT"], "env_fp": "a" * 64,
    "conc_width": 1, "pool": "stub", "scenario": c["name"],
    "verdict": c["status"],
    "wall_s": c["dur_s"], "source": "lane:line-round", "ticket": "line-round",
    "run": run_id,
} for c in spec_cases]
mod.append_records(rows)
hdr = {"v": mod.RUN_HEADER_V, "id": run_id,
       "repos": [{"repo": "sandbar", "revision": os.environ["STUB_COMMIT"]}],
       "suite": "full", "source": "lane:line-round", "env_fp": "a" * 64,
       "conc_width": 1, "pool": "stub",
       "started_at": int(time.time() * 1000), "duration_s": 0.1,
       "cases": counts, "verdict": mod.run_verdict(counts)}
mod.append_run_header(hdr)
summary = {"ran": counts["ran"], "pass": counts["passed"],
           "fail": counts["failed"], "not_checked": counts["env_failed"],
           "run_id": run_id}
retired = json.loads(os.environ.get("STUB_RETIRED_RECORDS") or "[]")
if retired:
    summary["retired_premise_excluded"] = retired
    summary["retired_premise_count"] = len(retired)
print("INTEG_SUMMARY " + json.dumps(summary))
sys.exit({"green": 0, "envfail": 2, "fail": 1}[mode])
'''


def run(argv, env=None, cwd=None, timeout=300):  # SANCTIONED-WAIT: subprocess ceiling (kill-on-expiry, never a bare wait)
    """One bounded subprocess (kill-on-expiry ceiling, never a bare wait)."""
    return subprocess.run(argv, capture_output=True, text=True, env=env,
                          cwd=cwd, timeout=timeout)


def py_exit(code, line="ok stub entry"):
    """A stub registry command with a fixed exit code (the state under test)."""
    return "%s -c %s" % (sys.executable,
                         json.dumps("import sys; print(%r); sys.exit(%d)"
                                    % (line, code)))


def last_summary(stdout):
    """The round's INTEG_SUMMARY payload (its public machine receipt)."""
    for line in reversed((stdout or "").splitlines()):
        if line.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(line[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


def stub_round(tmp, name, entries, env_extra, premise_data=None):
    """Run ONE real suite round over a stub registry; return (proc, summary).

    Everything the child touches lives under ``tmp``: its ledger dir, its lease
    lock root (so the round's prelude residue sweep sees an empty lease root and
    cannot interfere with sibling cases) and its report directory (cwd).
    """
    work = Path(tmp) / name
    work.mkdir(parents=True, exist_ok=True)
    reg = work / "registry.json"
    reg.write_text(json.dumps(entries), encoding="utf-8")
    drv = work / "driver.py"
    drv.write_text(DRIVER, encoding="utf-8")
    env = clean_narrowing_env({
        "STUB_RS": str(INTEG / "run_scenarios.py"),
        "STUB_REGISTRY": str(reg),
        "SANDBAR_SCENARIO_LEDGER_DIR": str(work / "ledger"),
        "SANDBAR_LEDGER_REUSE": "0",
        "SANDBAR_POOL_CONC": "1",
        "SANDBAR_STAGE_LOCK_DIR": str(work / "leases"),
        "SANDBAR_RETIRED_PREMISE_PATH": str(premise_data or (work / "absent.json")),
    })
    # the stub round is a fixture: only the declarations above may narrow it
    env.update(env_extra or {})
    proc = run([sys.executable, str(drv)], env=env, cwd=str(work))
    return proc, last_summary(proc.stdout)


def write_premise_data(path, entries):
    data = {
        "schema": RP.SCHEMA,
        "premises": [{"id": STUB_PREMISE, "retired": STUB_ORDER,
                      "reason": "stub premise retired for this case"}],
        "excluded": entries,
        "dispositions": [
            {"name": STUB_RETIRED, "disposition": "excluded",
             "detail": "stub entry excluded by the stub retired premise"}],
    }
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def verdict_rules(summary):
    """The two verdict rules over one round's counts: the engine's certifying
    rule (env_failed > 0 is red) and the face's rule (same, plus no-proof)."""
    counts = {"ran": int(summary.get("ran") or 0),
              "failed": int(summary.get("fail") or 0),
              "env_failed": int(summary.get("not_checked") or 0)}
    face_counts = {"ran": counts["ran"], "pass": int(summary.get("pass") or 0),
                   "fail": counts["failed"], "env_fail": counts["env_failed"]}
    return DC.run_verdict(counts), RF.terminal_verdict(face_counts)


def leg_shipped_data():
    """S: the shipped declaration and the roster agree (both measured entries)."""
    data, err = RP.load()
    check(err is None, "S1 integration/retired-premises.json parses and validates "
                       "(err=%s)" % err)
    if data is None:
        return
    records = RP.exclusions(data)
    check(bool(records), "S2 the declaration excludes at least one entry (named: %s)"
                         % ",".join(r["name"] for r in records))
    registry_names = registry_roster()
    missing = [r["name"] for r in records if r["name"] not in registry_names]
    check(missing == [], "S3 every excluded entry is STILL listed in the registry "
                         "(no case disappeared; missing=%s)" % (missing or "none"))
    shaped = [r for r in records
              if r["premise"] and r["retired"] and r["reason"]]
    check(len(shaped) == len(records),
          "S4 every exclusion names its premise, its retirement order and a reason")
    lifted = RP.select(records, [STUB_RETIRED])
    check(lifted == [], "S5 a name that is not in the declaration is not excluded "
                        "(no heuristic over names)")
    disps = {d["name"]: d["disposition"] for d in RP.face_refs(data)}
    check(disps.get("t260921-06-batch-ns-isolation") == "excluded",
          "S6 the measured namespace-isolation entry has a recorded EXCLUDED "
          "disposition (got %r)" % disps.get("t260921-06-batch-ns-isolation"))
    check(disps.get("t261027-11-stage-process-backend-zero-docker") == "repointed",
          "S7 the measured zero-docker entry has a recorded RE-POINTED disposition "
          "(got %r)" % disps.get("t261027-11-stage-process-backend-zero-docker"))
    check("t260921-06-batch-ns-isolation"
          in registry_roster_of(ROOT / "integration" / "run_scenarios.py"),
          "S8 the excluded entry is marked in the registry source (raised premise "
          "comment + RETIRED PREMISE marker), never deleted")


def registry_roster():
    """The real registry's names (read from the tree under test)."""
    return registry_roster_of(INTEG / "run_scenarios.py")


def registry_roster_of(path):
    """Parse the real registry module without importing it (its module body is
    the huge scenario table; a plain import is what the round does, but this case
    only needs the names)."""
    import importlib.util
    cache = getattr(registry_roster_of, "_cache", None)
    if cache and cache[0] == str(path):
        return cache[1]
    spec = importlib.util.spec_from_file_location("rs_roster_probe", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = [e[0] for e in mod.SCENARIOS]
    registry_roster_of._cache = (str(path), names)
    return names


def leg_exclusion_by_construction(tmp):
    """X: a stub retired premise excludes + names its entry; the round stays green."""
    premises = write_premise_data(
        Path(tmp) / "stub-premises.json",
        [{"name": STUB_RETIRED, "premise": STUB_PREMISE,
          "reason": STUB_REASON}])
    entries = [[STUB_PASS, "stub pass entry (t261029-76)", py_exit(0), "ro"],
               [STUB_RETIRED, "stub retired-premise entry (t261029-76)",
                py_exit(2, "ENV_FAIL docker daemon unreachable: stub"),
                "ro"]]
    proc, summary = stub_round(tmp, "exclude", entries, {},
                               premise_data=premises)
    out = proc.stdout or ""
    check(proc.returncode == 0,
          "X1 the round over a stub retired premise exits 0 (rc=%d, stderr tail=%r)"
          % (proc.returncode, (proc.stderr or "").strip()[-200:]))
    named = [ln for ln in out.splitlines()
             if ln.strip().startswith("RETIRED_PREMISE [%s]" % STUB_RETIRED)]
    check(bool(named), "X2 the receipt NAMES the excluded entry with the "
                       "retired-premise vocabulary")
    if named:
        line = named[0]
        check(STUB_PREMISE in line, "X3 the named line carries the PREMISE (%r)"
                                    % line[:160])
        check(STUB_ORDER in line, "X4 the named line carries the RETIREMENT ORDER")
        check("premise retired" in line, "X5 the named line carries the REASON")
    check("ENV_FAIL [%s]" % STUB_RETIRED not in out,
          "X6 the excluded entry booked NO env_fail (it was never judged)")
    check("PASS [%s]" % STUB_RETIRED not in out,
          "X7 the excluded entry did not run at all (never a fake green either)")
    check(summary is not None, "X8 the round published its INTEG_SUMMARY receipt")
    if summary is None:
        return
    check(int(summary.get("ran") or 0) == 1
          and int(summary.get("pass") or 0) == 1
          and int(summary.get("fail") or 0) == 0
          and int(summary.get("not_checked") or 0) == 0,
          "X9 the round judged exactly the live entry (ran=%s pass=%s fail=%s "
          "env_fail=%s)" % (summary.get("ran"), summary.get("pass"),
                            summary.get("fail"), summary.get("not_checked")))
    check(int(summary.get("expected") or -1) == 1,
          "X10 the excluded entry is out of the EXPECTED roster count (expected=%s)"
          % summary.get("expected"))
    recs = summary.get("retired_premise_excluded") or []
    check([r.get("name") for r in recs] == [STUB_RETIRED],
          "X11 the machine receipt names the excluded entry (records=%s)"
          % json.dumps(recs, ensure_ascii=False)[:200])
    if recs:
        r = recs[0]
        check(r.get("premise") == STUB_PREMISE and r.get("retired") == STUB_ORDER
              and bool(r.get("reason")),
              "X12 the receipt record carries premise + retirement order + reason")
    engine_verdict, face_verdict = verdict_rules(summary)
    check(engine_verdict == "green",
          "X13 the ENGINE's certifying rule (develop_certify.run_verdict) reads "
          "GREEN (got %r)" % engine_verdict)
    check(face_verdict == "green",
          "X14 the face's stricter rule reads GREEN too (got %r)" % face_verdict)
    check(summary.get("retired_premise_count") == 1,
          "X15 the receipt carries the exclusion count (got %r)"
          % summary.get("retired_premise_count"))


def leg_negative_branch(tmp):
    """N: a LIVE premise that fails still books ENV_FAIL and still reds the round."""
    premises = write_premise_data(
        Path(tmp) / "stub-premises-2.json",
        [{"name": STUB_RETIRED, "premise": STUB_PREMISE,
          "reason": STUB_REASON}])
    entries = [[STUB_PASS, "stub pass entry (t261029-76)", py_exit(0), "ro"],
               [STUB_LIVE, "stub live-premise entry (t261029-76)",
                py_exit(2, "ENV_FAIL live premise unavailable: stub"), "ro"]]
    proc, summary = stub_round(tmp, "live", entries, {},
                               premise_data=premises)
    out = proc.stdout or ""
    check(proc.returncode == 2,
          "N1 a live environment failure still exits from the suite as an "
          "environment red (rc=%d)" % proc.returncode)
    check("ENV_FAIL [%s]" % STUB_LIVE in out,
          "N2 the live failing entry is booked as ENV_FAIL exactly as before")
    check("RETIRED_PREMISE [%s]" % STUB_LIVE not in out,
          "N3 a live entry is never excluded (no blanket env_fail exemption)")
    if summary is None:
        envfail("N4 the live round published no INTEG_SUMMARY")
        return
    check(int(summary.get("not_checked") or 0) == 1,
          "N5 the count books the environment failure (not_checked=%s)"
          % summary.get("not_checked"))
    check(summary.get("env_red_names") == [STUB_LIVE],
          "N6 the environment red is named on the receipt (env_red_names=%s)"
          % (summary.get("env_red_names"),))
    live_recs = [r.get("name") for r in
                 (summary.get("retired_premise_excluded") or [])]
    check(STUB_LIVE not in live_recs,
          "N7 a live failing entry is never carried as an exclusion "
          "(records=%s)" % (live_recs or "none"))
    engine_verdict, face_verdict = verdict_rules(summary)
    check(engine_verdict == "red",
          "N8 the ENGINE's rule reads RED on a live environment failure (got %r)"
          % engine_verdict)
    check(face_verdict == "red",
          "N9 the face's rule reads RED on a live environment failure (got %r)"
          % face_verdict)


def leg_two_names(tmp):
    """V: a pool skip and a retired premise are two decisions with two names."""
    pool_line = "跳过 [%s]（池=stubpool）" % STUB_PASS
    retired_line = RP.line({"name": STUB_RETIRED, "premise": STUB_PREMISE,
                            "retired": STUB_ORDER, "reason": STUB_REASON})
    check("（池=" not in retired_line and "跳过" not in retired_line,
          "V1 the retired-premise line carries NONE of the pool-skip vocabulary")
    check("前提=" in retired_line and "退役=" in retired_line,
          "V2 the retired-premise line carries its own vocabulary (premise + "
          "retirement order)")
    check(pool_line.split("[")[0] != retired_line.split("[")[0],
          "V3 the two decisions have different prefixes (%r vs %r)"
          % (pool_line.split("[")[0], retired_line.split("[")[0]))
    entries = [[STUB_PASS, "stub pool entry (t261029-76)", py_exit(0), "stubpool"],
               [STUB_LIVE, "stub pool entry 2 (t261029-76)", py_exit(0),
                "stubpool"]]
    proc, _summary = stub_round(tmp, "poolskip", entries,
                                {"SANDBAR_SCENARIO_EXCLUDE_POOLS": "stubpool"})
    out = proc.stdout or ""
    check("本轮跳过池=stubpool" in out,
          "V4 a pool-excluded round prints the POOL vocabulary")
    check("RETIRED_PREMISE [" not in out,
          "V5 a pool-excluded round prints NO retired-premise line (the two "
          "decisions never collapse into one)")
    check(("  跳过 [" in out) or ("跳过 [" in out),
          "V6 the skipped entries are named with the pool-skip vocabulary")


def make_source_repo(tmp):
    """A tiny git repo whose HEAD carries integration/run_scenarios.py - just
    enough for the runner's primary-tree detection."""
    src = Path(tmp) / "source-sandbar"
    (src / "integration").mkdir(parents=True, exist_ok=True)
    (src / "integration" / "run_scenarios.py").write_text("# stub tree\n")
    for argv in (["git", "init", "-q", str(src)],
                 ["git", "-C", str(src), "config", "user.email", "t@t"],
                 ["git", "-C", str(src), "config", "user.name", "t"],
                 ["git", "-C", str(src), "add", "-A"],
                 ["git", "-C", str(src), "commit", "-qm", "fixture"]):
        proc = run(argv)
        if proc.returncode != 0:
            envfail("git fixture failed: %s: %s" % (argv, proc.stderr.strip()))
            finish()
    return src, run(["git", "-C", str(src), "rev-parse", "HEAD"]).stdout.strip()


def leg_round_receipt(tmp):
    """R: the real line_round_runner relays the exclusion onto header + face."""
    if not (run(["git", "--version"]).returncode == 0):
        envfail("git is not available: the line-round receipt leg cannot run")
        finish()
    src, sha = make_source_repo(tmp)
    suite = Path(tmp) / "stub_suite.py"
    suite.write_text(STUB_SUITE, encoding="utf-8")
    retired = [{"name": STUB_RETIRED, "premise": STUB_PREMISE,
                "retired": STUB_ORDER, "reason": STUB_REASON}]
    for mode in ("green", "envfail"):
        base = Path(tmp) / ("round-" + mode)
        projects = base / "projects" / "stubproj" / "ledger"
        projects.mkdir(parents=True)
        (projects / "scenario-runs.jsonl").write_text(
            json.dumps({"id": "run-fixture", "source": "lane:line-round"}) + "\n",
            encoding="utf-8")
        env = clean_narrowing_env({
            "SANDBAR_LINE_ROUND_CANDIDATES":
                json.dumps([{"repo": "sandbar", "revision": sha}]),
            "SANDBAR_LINE_ROUND_REPO_PATH_SANDBAR": str(src),
            "SANDBAR_LINE_ROUND_SUITE_CMD":
                "%s %s" % (sys.executable, suite),
            "SANDBAR_LINE_ROUND_RUN_ROOT": str(base / "run"),
            "SANDBAR_LINE_ROUND_RUN_STATE_DIR": str(base / "state"),
            "SANDBAR_LINE_ROUND_FACE_DIR": str(base / "develop"),
            "SANDBAR_PROJECTS_DIR": str(base / "projects"),
            "SANDBAR_KNOWN_RED_ROSTER": "",
            "STUB_INTEG": str(INTEG),
            "STUB_COMMIT": sha,
            "STUB_SUITE_MODE": mode,
            "STUB_RETIRED_RECORDS": json.dumps(retired),
            "SANDBAR_POC_PYTHON": sys.executable,
            # hand the runner a resolved bench asset only when this process has
            # one (a blank value would read as a pointer to nothing)
            **({"SANDBAR_TEMPORAL_BIN": os.environ["SANDBAR_TEMPORAL_BIN"]}
               if os.environ.get("SANDBAR_TEMPORAL_BIN") else {}),
        })
        proc = run([sys.executable, str(INTEG / "line_round_runner.py")], env=env,
                   cwd=str(base))
        out = (proc.stdout or "").strip()
        check(proc.returncode == 0,
              "R1[%s] the round runner completes (rc=%d, stderr tail=%r)"
              % (mode, proc.returncode, (proc.stderr or "").strip()[-220:]))
        try:
            header = json.loads(out.splitlines()[-1]) if out else {}
        except ValueError:
            header = {}
        if mode == "green":
            check(header.get("retired_premise_excluded") == retired,
                  "R2 the relayed run header NAMES the exclusion (premise + "
                  "retirement order + reason)")
            check((proc.stderr or "").find(STUB_RETIRED) >= 0,
                  "R3 the excluded entry is named on the runner's stderr")
            face = None
            rounds = base / "develop" / "rounds"
            if rounds.is_dir():
                for d in sorted(rounds.iterdir()):
                    cand = d / "face.json"
                    if cand.is_file():
                        try:
                            face = json.loads(cand.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            face = None
                        if face:
                            break
            check(isinstance(face, dict), "R4 the round wrote its terminal face")
            if isinstance(face, dict):
                check(face.get("retired_premise_excluded") == retired,
                      "R5 the terminal face NAMES the exclusion")
                check((face.get("outcome") or {}).get("verdict") == "green",
                      "R6 the face of the exclusion round reads GREEN (got %r)"
                      % (face.get("outcome") or {}).get("verdict"))
                check(face.get("counts", {}).get("env_fail") == 0,
                      "R7 the face books no env_fail for the excluded entry "
                      "(counts=%s)" % (face.get("counts"),))
        else:
            check((header.get("cases") or {}).get("env_failed") == 1,
                  "R8 a round whose live entry failed still carries env_failed=1 "
                  "on the relayed header (cases=%s)" % (header.get("cases"),))
            face = None
            rounds = base / "develop" / "rounds"
            if rounds.is_dir():
                for d in sorted(rounds.iterdir()):
                    cand = d / "face.json"
                    if cand.is_file():
                        try:
                            face = json.loads(cand.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            face = None
                        if face:
                            break
            outcome = (face or {}).get("outcome") or {}
            check(outcome.get("verdict") == "red",
                  "R9 a live environment failure still reds the round's face "
                  "(verdict=%r)" % outcome.get("verdict"))
            # The two declared rules stay DISTINGUISHABLE on the face (t261024-30):
            # the face reds on an environment failure, the RECORD keeps its
            # content rule and says so by name - never a silent disagreement.
            check(outcome.get("record_verdict") == "green"
                  and outcome.get("record_rule") == "content-v1",
                  "R10 the record verdict keeps its declared rule beside the "
                  "stricter face verdict (record_verdict=%r rule=%r)"
                  % (outcome.get("record_verdict"), outcome.get("record_rule")))
            check(outcome.get("verdict") != outcome.get("record_verdict"),
                  "R11 the two verdicts are distinguishable on the receipt, not "
                  "silently merged")


def leg_observation_face_bites(tmp):
    """D: the recording docker stand-in records real calls and flags containers."""
    root = Path(tmp) / "shim-root"
    root.mkdir(parents=True, exist_ok=True)
    shim_dir, log_path = docker_shim(str(root))
    env = shim_env(shim_dir, log_path)
    run([os.path.join(shim_dir, "docker"), "ps", "-a"], env=env)
    run([os.path.join(shim_dir, "docker"), "run", "--rm", "busybox", "true"],
        env=env)
    run([os.path.join(shim_dir, "docker"), "compose", "-f", "x.yml", "up", "-d"],
        env=env)
    calls = docker_calls(log_path)
    check(len(calls) == 3, "D1 the stand-in records every docker invocation (%s)"
                           % calls)
    bad = container_calls(calls)
    check(len(bad) == 2 and any("run" in c for c in bad)
          and any("up" in c for c in bad),
          "D2 the container-creating family is flagged (recorded=%s)" % bad)
    check(container_calls(["ps -a --filter label=x"]) == [],
          "D3 an inspection scan is not a container (never a false red)")
    check(container_calls(["container", "create", "img"]) != [],
          "D4 the container GROUP sub-verb is recognised too")


def main():
    tmp = lib_tmp_reclaim.mkdtemp_reclaimed("t26102976-retired-premise-")
    leg_shipped_data()
    leg_exclusion_by_construction(tmp)
    leg_negative_branch(tmp)
    leg_two_names(tmp)
    leg_round_receipt(tmp)
    leg_observation_face_bites(tmp)
    finish()


if __name__ == "__main__":
    main()
