#!/usr/bin/env python3
"""t261024-60 scenario: a ticket's OWN scenario is never ledger-reused out of
its gate round (the reuse wedge behind the live witnesses t261022-12 and
t261022-14 — user words: 'The rule: a ticket's OWN declared scenarios are
always in its gate run, whatever pool they live in. A pool exclusion
schedules work, it never drops the ticket's own case.').

intent (user-perceivable): the t260930-01 ledger green-row reuse is a
SCHEDULING optimization for the rest of the round; for the change's OWN
declared scenarios it must never become a drop reason. A green ledger row for
the same commit+env-fingerprint replaces the RUN, books no fresh green face
(zero-run = no face, KI-220), and starves the landing anchor — so on the
promoted head every gate round reported a legal-looking ran=0 while the
ticket's own proof never ran. The reuse economy for NON-own pointed names
stays intact, the kill switch keeps its named face, and an unchanged-head
re-run repeats the same judgement (no flip-flop).

high-level steps: build a private REAL git tree (committed runner copy + mini
registry whose own fixture entries live under integration/t261024-60/, so the
own-set derivation and the SANDBAR_SCENARIO_OWN face both see them; clean tree
is a reuse PREMISE, so everything is committed and out/__pycache__ are
ignored); seed green ledger rows by one real full round into an isolated
SANDBAR_SCENARIO_LEDGER_DIR; then drive the real executor as a subprocess per
case and judge user-visible faces (SCENARIOS counts, INTEG_REUSE /
INTEG_OWN_RERUN named lines, on-disk run markers read reader-side, and the
round report JSON):
  A THE WEDGE, POSITIVE - pointed round own(in engine pool + browser-free) +
    non-own(main) with a green row for every name and the gate's pool
    exclusion: the OWN scenarios RUN FOR REAL (run counter grows), the non-own
    name is reused (counter frozen, named on INTEG_REUSE), the round reports
    ran>=1, ran+reused==expected, and the receipt names exactly the covered
    own names on the own-rerun face (stderr line + additive receipt key).
  B UNCHANGED-HEAD REPEAT - the same round again on the same commit: same
    judgement (own ran again, non-own reused) - the observed flip-flop
    (reuse hit alternates with a real run) is gone by construction.
  C KILL SWITCH CONTROL - SANDBAR_LEDGER_REUSE=0 on the same shape: reuse is
    disabled with its named stderr reason and EVERYTHING runs (supply rules
    intact, rc=0, no refusal).
  D ECONOMY CONTROL - pointed non-own name alone, no own env: the lawful
    reuse face is byte-stable (reused=1, ran=0, rc=0) - the fix widens
    nothing else.
Offline seconds, zero docker/Temporal-server/browser, never touches 3099/7233.
Intent split (no intent-level duplication): the four-key reuse truth table,
kill-switch reason wording and malformed-row tolerance belong to
t260930-01-ledger-reuse-round; the pool-exclusion and roster peel paths with
the missing-own-name refusal belong to t261024-40-own-scenario-gate-round;
the quick-gate own_names threading and the empty-derivation refusal copy
belong to developer L1 batteries (plan t261024-60 step 2/3) and to the
engine-gate stage driving the two live lanes. THIS entry uniquely owns 'a
green ledger row never substitutes for the ticket's own proof, with the
own-rerun face naming the covered names'. Pre-implement tree red on A/B =
the named TDD signal (the own-rerun face is absent); green required at the
integration gate/merge. git or run_scenarios.py missing = ENV_FAIL exit 2.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261024-60-own-never-ledger-reused"
SLUG = "t261024-60-reuse-wedge-fixture"

TMP = None
MAIN = None
_RECLAIMED = False

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok


def env_fail(reason):
    _ck.env_fail(NAME, reason)


def finish():
    _ck.finish(NAME)


OWN_ENV = "SANDBAR_SCENARIO_OWN"
ONLY_ENV = "SANDBAR_SCENARIO_ONLY"
EXCLUDE_ENV = "SANDBAR_SCENARIO_EXCLUDE_POOLS"
REUSE_ENV = "SANDBAR_LEDGER_REUSE"
LEDGER_DIR_ENV = "SANDBAR_SCENARIO_LEDGER_DIR"

OWN_ENGINE = "t261024-60-fx-own-engine"   # the incident's pool (engine)
OWN_BF = "t261024-60-fx-own-browserfree"  # the other witness's pool
OTHER = "t261024-60-fx-other"             # non-own pointed name (main)
ALL_NAMES = (OWN_ENGINE, OWN_BF, OTHER)
GATE_EXCLUDE = "engine,exclusive"         # the per-ticket gate exclusion shape

RUNNER = REPO / "integration" / "run_scenarios.py"
MAIN_ANCHOR = "\nSCENARIOS = ["


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(MAIN),
                          # SANCTIONED-WAIT: bounded git fixture call, not a state wait
                          capture_output=True, text=True, timeout=120)


def _cleanup():
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    try:
        if TMP is not None:
            shutil.rmtree(str(TMP), ignore_errors=True)
    except Exception:  # noqa: BLE001 - reclaim never raises
        pass


atexit.register(_cleanup)


def _fixture_script(marker: Path, log: Path, name: str) -> str:
    """Fixture scenario: appends one line to a shared log per REAL execution
    (the reader-side 'it really ran' face; a ledger-reused entry never
    appends) and prints the real-shape spec row so the round books a green
    ledger row under the registry name (the reuse fourth key compares the
    registry name verbatim)."""
    return ("import json, os\n"
            "NAME = %r\n"
            "open(%r, 'a').write(NAME + '\\n')\n"
            "print(json.dumps({'name': NAME, 'suite': 'main',\n"
            "                  'status': 'pass', 'cause': None, 'reason': None,\n"
            "                  'evidence': 'fixture', 'dur_s': 0.01,\n"
            "                  'started': '2026-10-24T00:00:00+00:00',\n"
            "                  'git_sha': '', 'attempt': 1},\n"
            "                 ensure_ascii=False))\n"
            % (name, str(log)))


def _build_tree(tmp: Path):
    """A private REAL git tree, fully committed (a clean tree is a reuse
    premise): runner copy + minimal protocol/library deps + a mini registry
    whose own fixture entries live under integration/t261024-60/ inside the
    tree; out/ and __pycache__ ignored so round 1 cannot dirty the tree."""
    global TMP, MAIN
    TMP = tmp
    main = tmp / "tree"
    main.mkdir()
    MAIN = main
    integ = main / "integration"
    integ.mkdir()
    for f in ("run_scenarios.py", "scenario_ledger.py", "lib_env.py",
              "lib_result.py", "lib_tmp_reclaim.py", "conftest.py",
              "conftest_result_protocol.py",
              "batch_stage_exceptions.json"):
        src = REPO / "integration" / f
        if src.is_file():
            shutil.copy2(str(src), str(integ / f))
    eng = main / "server" / "engine"
    eng.mkdir(parents=True)
    shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                 str(eng / "failure_protocol.py"))
    # Own fixture entries live under the ticket dir (the own-set marker),
    # one per witness pool; the non-own name lives outside it.
    own_dir = integ / "t261024-60"
    own_dir.mkdir()
    # stage_docker stub (same technique as the t261024-40 lane fixture): the
    # engine-pool entry is a batch-stage consumer, and the preboot only needs
    # an ensure/down that answer the declared shape - the judgement faces of
    # this scenario are reuse/run-counter faces, not stage faces.
    (integ / "stage_docker.py").write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "cmd = args[0] if args else \"\"\n"
        "proj = args[args.index(\"--project\") + 1] if \"--project\" in args else \"stub\"\n"
        "if cmd == \"ensure\":\n"
        "    print(json.dumps({\"project\": proj, \"state\": \"up\", \"reused\": False,\n"
        "                      \"services\": [\"temporal\"],\n"
        "                      \"ports\": {\"temporal\": 21101, \"ui\": 21102},\n"
        "                      \"sa_registered\": True, \"container_ids\": {\"temporal\": \"stub\"}}))\n"
        "    sys.exit(0)\n"
        "if cmd == \"down\":\n"
        "    print(json.dumps({\"ok\": True, \"residue\": []}))\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n", encoding="utf-8")
    entries = []
    for name, pool, in_dir in ((OWN_ENGINE, "engine", True),
                               (OWN_BF, "browser-free", True),
                               (OTHER, "main", False)):
        d = own_dir if in_dir else integ
        script = d / ("fx_%s.py" % name)
        marker = tmp / ("run-%s.log" % name)
        script.write_text(_fixture_script(marker, marker, name),
                          encoding="utf-8")
        entries.append((name, "t261024-60 fixture entry (scenario-injected, "
                             "not the real registry)",
                        "python3 integration/%sfx_%s.py"
                        % ("t261024-60/" if in_dir else "", name), pool))
    text = RUNNER.read_text(encoding="utf-8")
    if MAIN_ANCHOR not in text:
        env_fail("run_scenarios registry anchor missing (SCENARIOS = [)")
        return None
    head, tail = text.split(MAIN_ANCHOR, 1)
    rest = tail.split("\n]", 1)[1]
    body = "".join("    %r,\n" % (e,) for e in entries)
    (integ / "run_scenarios.py").write_text(
        head + MAIN_ANCHOR + "\n" + body + "]" + rest, encoding="utf-8")
    (main / ".gitignore").write_text("out/\n__pycache__/\n", encoding="utf-8")
    (main / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/run_scenarios.py\n"
        "  exclude_pools: %s\n" % GATE_EXCLUDE, encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.email", "s@example.invalid"),
                 ("config", "user.name", "s"), ("add", "-A"),
                 ("commit", "-q", "-m", "fixture")):
        r = _git(*args)
        if r.returncode != 0:
            env_fail("git fixture commit failed: %s"
                     % (r.stderr or r.stdout)[-300:])
            return None
    head_sha = _git("rev-parse", "HEAD").stdout.strip()
    if not head_sha:
        env_fail("fixture HEAD unresolvable after commit")
        return None
    return main


def _run_round(env=None, timeout=300):  # SANCTIONED-WAIT: bounded subprocess ceiling (declared communicate() budget), not a state wait
    cmd = [sys.executable, "integration/run_scenarios.py"]
    e = clean_narrowing_env()
    e[LEDGER_DIR_ENV] = str(TMP / "ledger")
    e["SANDBAR_POOL_CONC"] = "4"
    e["SANDBAR_CONC_POOLS"] = "main:1"
    e["SANDBAR_INTEG_RUN_LOCK_PATH"] = str(TMP / "run.lock")
    # The run-record identity (the gate sets it live): without it the seeding
    # round honestly books NOTHING (a missing row beats a guessed identity)
    # and the reuse face would never have a row to judge.
    e["SANDBAR_TICKET_ID"] = "t261024-60"
    e.update({k: str(v) for k, v in (env or {}).items()})
    before = _newest_report_mtime()
    try:
        p = subprocess.run(cmd, cwd=str(MAIN), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env=e, start_new_session=True)
    except subprocess.TimeoutExpired as ex:
        return -9, (ex.stdout or ""), (ex.stderr or ""), None
    return p.returncode, p.stdout or "", p.stderr or "", _newest_report(after=before)


def _newest_report_mtime():
    outs = MAIN / "out"
    if not outs.is_dir():
        return None
    reps = sorted(outs.glob("integration-report-*.json"),
                  key=lambda p: p.stat().st_mtime)
    return reps[-1].stat().st_mtime if reps else None


def _newest_report(after=None):
    """Reader-side round report: the newest report written AFTER this round
    started (a per-round attribution face, never a stale one)."""
    outs = MAIN / "out"
    if not outs.is_dir():
        return None
    reps = sorted(outs.glob("integration-report-*.json"),
                  key=lambda p: p.stat().st_mtime)
    if after is not None:
        reps = [p for p in reps if p.stat().st_mtime >= after]
    if not reps:
        return None
    try:
        return json.loads(reps[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _runs(log: Path):
    """How many times the fixture REALLY ran (reader-side: the on-disk run
    counter the fixture appends on execution; reuse never touches it)."""
    if not log.is_file():
        return 0
    return len(log.read_text(encoding="utf-8").splitlines())


def _summary(out):
    for ln in out.splitlines():
        if ln.startswith("INTEG_SUMMARY "):
            try:
                return json.loads(ln[len("INTEG_SUMMARY "):])
            except ValueError:
                return None
    return None


def _scenarios_line(out):
    for ln in out.splitlines():
        if ln.startswith("SCENARIOS ran="):
            return ln
    return ""


def main():
    if shutil.which("git") is None:
        env_fail("git missing (every judgement here is a git face)")
        finish()
        return 2
    if not RUNNER.is_file():
        env_fail("run_scenarios.py missing at %s" % RUNNER)
        finish()
        return 2
    with tempfile.TemporaryDirectory(prefix="t261024-60-") as td:
        if _build_tree(Path(td)) is None:
            finish()
            return 2
        logs = {n: TMP / ("run-%s.log" % n) for n in ALL_NAMES}

        # -------- Round 1: seed - one real full round books green rows ------
        rc, out, err, rep = _run_round()
        summ = _summary(out)
        ok(rc == 0, "R1 the seeding round is judged (rc=0)",
           "rc=%s tail=%s" % (rc, err[-200:] or out[-200:]))
        ok(all(_runs(logs[n]) == 1 for n in ALL_NAMES),
           "R1 every fixture really ran once (run counters = 1)",
           "runs=%s" % {n: _runs(logs[n]) for n in ALL_NAMES})
        ok(isinstance(summ, dict) and summ.get("reused", -1) == 0,
           "R1 the seeding round reused nothing (rows are fresh)",
           "summary=%r" % (summ,))
        ok(isinstance(rep, dict)
           and isinstance(rep.get("reuse_judged_by", {}).get("ledger"), str),
           "R1 the round report carries the ledger judgement face",
           "keys=%s" % sorted((rep or {}).keys()))

        # -------- Round 2: THE WEDGE - own never ledger-reused --------------
        env = {ONLY_ENV: ",".join(ALL_NAMES), OWN_ENV: "%s,%s" % (OWN_ENGINE, OWN_BF),
               EXCLUDE_ENV: GATE_EXCLUDE}
        rc, out, err, rep = _run_round(env=env)
        summ = _summary(out)
        plan = (rep or {}).get("only_plan") or {}
        ok(rc == 0, "A0 the wedge round is judged (rc=0), never refused",
           "rc=%s tail=%s" % (rc, err[-200:] or out[-200:]))
        ok(_runs(logs[OWN_ENGINE]) == 2 and _runs(logs[OWN_BF]) == 2,
           "A1 the OWN scenarios RAN FOR REAL despite green ledger rows "
           "(engine-pool and browser-free both, run counters grew to 2)",
           "runs=%s" % {n: _runs(logs[n]) for n in ALL_NAMES})
        ok(_runs(logs[OTHER]) == 1,
           "A2 the non-own pointed name was ledger-reused (counter frozen, "
           "the economy is intact)",
           "runs=%s" % _runs(logs[OTHER]))
        ok("ran=2" in _scenarios_line(out),
           "A3 the receipt reports ran>=1 carrying the own scenarios "
           "(ran=2, never the legal-looking ran=0 wedge)",
           "line=%s" % _scenarios_line(out))
        ok(isinstance(summ, dict)
           and summ.get("ran") + summ.get("reused", 0) == summ.get("expected"),
           "A4 the completeness invariant ran+reused==expected holds after "
           "the own exemption",
           "summary=%r" % (summ,))
        rerun_face = [ln for ln in out.splitlines()
                      if ln.startswith("INTEG_OWN_RERUN")]
        ok(bool(rerun_face)
           and OWN_ENGINE in " ".join(rerun_face)
           and OWN_BF in " ".join(rerun_face),
           "A5 the own-rerun face is NAMED on the round (INTEG_OWN_RERUN "
           "line carrying exactly the covered own names)",
           "face=%r" % (rerun_face,))
        reuse_face = " ".join(ln for ln in out.splitlines()
                              if ln.startswith("INTEG_REUSE "))
        ok(OTHER in reuse_face and OWN_ENGINE not in reuse_face,
           "A6 the reuse face names only the non-own name (own names never "
           "enter the reuse candidate set)",
           "face=%s" % reuse_face[:200])
        ok(OWN_ENGINE in json.dumps(plan.get("own", []))
           and isinstance(plan.get("own"), list),
           "A7 the attribution face keeps the own set (only_plan.own)",
           "own=%r" % (plan.get("own"),))
        rr = plan.get("own_rerun", (rep or {}).get("own_rerun"))
        ok(sorted(rr or []) == sorted([OWN_ENGINE, OWN_BF]),
           "A8 the receipt names exactly the covered own names (additive "
           "own_rerun key on the round report)",
           "own_rerun=%r report_keys=%s"
           % (rr, sorted((rep or {}).keys())))

        # -------- Round 3: unchanged-head repeat (no flip-flop) -------------
        rc, out, err, rep = _run_round(env=env)
        ok(rc == 0 and _runs(logs[OWN_ENGINE]) == 3 and _runs(logs[OTHER]) == 1,
           "B the same round on the same commit repeats the same judgement "
           "(own ran again, non-own reused again - no flip-flop)",
           "rc=%s runs=%s" % (rc, {n: _runs(logs[n]) for n in ALL_NAMES}))

        # -------- Round 4: kill switch control (supply rules intact) --------
        rc, out, err, rep = _run_round(env=dict(env, **{REUSE_ENV: "0"}))
        ok(rc == 0 and _runs(logs[OTHER]) == 2,
           "C1 with the kill switch the non-own name runs too (reuse fully "
           "off, nothing widened or narrowed)",
           "rc=%s runs=%s" % (rc, _runs(logs[OTHER])))
        ok(REUSE_ENV in err,
           "C2 the disablement is NAMED on stderr with the kill-switch env "
           "(never silent)",
           "stderr=%s" % err[-300:])

        # -------- Round 5: economy control, no own env (byte-stable) --------
        rc, out, err, rep = _run_round(env={ONLY_ENV: OTHER})
        summ = _summary(out)
        ok(rc == 0 and "ran=0" in _scenarios_line(out)
           and _runs(logs[OTHER]) == 2,
           "D the lawful non-own reuse face is unchanged (pointed non-own "
           "name with a green row: reused, ran=0, rc=0)",
           "rc=%s line=%s runs=%s"
           % (rc, _scenarios_line(out), _runs(logs[OTHER])))
        ok(isinstance(summ, dict) and summ.get("reused") == 1,
           "D2 the reuse counts face stays on the receipt (reused=1)",
           "summary=%r" % (summ,))
    finish()
    return 1 if _ck.fails else 0


if __name__ == "__main__":
    sys.exit(main())
