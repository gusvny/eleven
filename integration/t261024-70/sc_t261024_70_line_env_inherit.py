#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261024_70_line_env_inherit.py — t261024-70, a line round inherits the
process environment and a runner that cannot start leaves a NAMED record on
the line's face (grey-box L3, the real develop_certify tick/run_now bodies
driven through the real resolve_runner seam and the real line_round_runner
over a real git fixture + a stub suite, offline seconds, zero
docker/Temporal-server/browser, never touches 3099/7233).

The incident (ticket body, 261025): since ~02:00 every line round on
develop-buffer refuses to start. The scan activity answers
{'line':'develop-buffer','state':'runner_missing'} for both the scheduled
tick and the manual force marker, no round directory appears, and NO ledger
row is written — nothing says why. Root cause: the t261024-50 change builds
``line_env = dict(env) if env else {}`` and the production caller passes
env=None, so the ambient runner command (SANDBAR_LINE_ROUND_RUNNER, present
in the worker's own environment) never reaches resolve_runner, which reads
RUNNER_CMD_ENV from the env it is given.

intent (user-perceivable contract, three basis sources exhausted):
  A. THE incident, scheduled face: a tick wired the way production wires it
     (no env argument) hands the runner seam an env that CONTAINS the
     ambient SANDBAR_LINE_ROUND_RUNNER — the seam resolves a runner, the
     line never answers runner_missing for an ambient-only cause.
  B. The round actually starts: the resolved runner, driven against a real
     candidate tree, produces one real run header and a run directory
     appears under the declared run root (reader side: os.listdir).
  C. THE incident, forced face: line_round_run_now over a real project
     fixture starts the round — the run root gains evidence and the
     delivery ledger gains at least one row naming the line (the empty
     result with no record is the incident, never lawful again).
  D. The refusal is NAMED: with SANDBAR_LINE_ROUND_RUNNER absent from the
     environment both faces answer runner_missing AND a named refusal
     record sits beside the delivery ledger (a jsonl face in the ledger
     directory carrying state=runner_missing and the line name) — an
     operator sees 'the round cannot start' without reading Temporal
     history. The refusal never becomes a delivery-ledger row.
  E. t261024-50 preserved: the known-red roster still comes from the
     candidate tree — the worktree overlay is injected even when an ambient
     SANDBAR_KNOWN_RED_ROSTER is present (the overlay wins), and an
     unreadable book stays a named CertifyError on the entry.

intent split (no intent-level duplication):
  - the roster read/candidate-tree truth table, ambiguity and env-injection
    unit faces belong to developer L1 (test_t261024_50_known_red_candidate_
    roster.py) — this entry only re-signs the two faces the incident ticket
    pins (overlay survives the new ambient base; unreadable book stays
    named through the NEW env merge);
  - the runner command -> one header contract, red-is-a-proof, timeout and
    reclaim belong to t261009-77-line-round-runner and the t261011-21 /
    t261013-04 families (fixture technique shared with t261011-21; shared
    steps are not shared intent);
  - the exclusion-switch default journey belongs to t261016-12;
  - THIS entry uniquely owns 'ambient env reaches the seam through the tick
    and the forced entry, and a missing runner is a named face row'.

Three states: git absent or engine modules unimportable = ENV_FAIL exit 2;
A/C/D red on the pre-implement tree = the named TDD signal — green
required at the integration gate / merge.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261024-70-line-round-env-inherit"

sys.path.insert(0, str(REPO / "integration"))
from lib_env import clean_narrowing_env  # noqa: E402
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

_TMP = None


def _cleanup():
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)

sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    import develop_certify as dc  # noqa: E402
    import shared  # noqa: E402
except Exception as e:  # noqa: BLE001
    env_fail("develop_certify unimportable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)

PROJECT = "sandbar"
LINE = "develop-buffer"
BOOK_REL = "integration/known-red-baseline.json"
RUNNER_VAR = dc.RUNNER_CMD_ENV  # SANDBAR_LINE_ROUND_RUNNER
ROSTER_VAR = "SANDBAR_KNOWN_RED_ROSTER"


def _git(*args, cwd, check=True):
    # SANCTIONED-WAIT: local git fixture subprocess, seconds-scale; a hang
    # is an environment face and raises TimeoutExpired (named failure).
    p = subprocess.run(["git", *args], cwd=str(cwd),  # SANCTIONED-WAIT: git fixture bound
                       capture_output=True, text=True, timeout=120)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed: %s"
                             % (" ".join(args), (p.stderr or "")[-300:]))
    return p


# ---------------------------------------------------------------- fixture

# The stub suite stands in for integration/run_scenarios.py: always green,
# one validated record + one validated header through the REAL
# scenario_ledger store, then INTEG_SUMMARY with the run id (the shape the
# line round runner relays).
_STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys, time
sys.path.insert(0, os.getcwd())
import integration.scenario_ledger as sl
candidates = json.loads(os.environ["SANDBAR_LINE_ROUND_CANDIDATES"])
run_id = sl.mint_run_id()
row = {
    "ts": "2026-10-24T19:00:00+00:00", "commit": "0" * 40,
    "env_fp": hashlib.sha256(b"stub").hexdigest(), "conc_width": 1,
    "pool": "serial",
    "scenario": "stub_case", "verdict": "pass", "wall_s": 0.1,
    "source": "lane:stub", "ticket": "t261024-70", "run": run_id,
}
clean, why = sl.validate_row(row)
if clean is None:
    sys.stderr.write("stub row refused: %s\n" % why)
    sys.exit(2)
if sl.append_records([clean])["written"] != 1:
    sys.stderr.write("stub row not written\n")
    sys.exit(2)
cases = {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0}
header = {
    "v": sl.RUN_HEADER_V, "id": run_id, "repos": candidates,
    "suite": "full", "source": "lane:stub", "env_fp": row["env_fp"],
    "conc_width": 1, "pool": "serial",
    "started_at": int(time.time() * 1000), "duration_s": 0.1,
    "cases": cases, "verdict": sl.run_verdict(cases),
}
if sl.append_run_header(header)["written"] != 1:
    sys.stderr.write("stub header refused\n")
    sys.exit(2)
print("INTEG_SUMMARY " + json.dumps(
    {"ran": 1, "passed": 1, "failed": 0, "env_failed": 0,
     "run_id": run_id}))
sys.exit(0)
'''


def _mk_repo_at(src, wt, tag):
    """A real git tree whose committed content is exactly the stub suite
    face; a line-branch worktree at ``wt`` carries the book (main never
    does). Returns the main HEAD."""
    src.mkdir(parents=True)
    _git("init", "-b", "main", cwd=src)
    _git("config", "user.email", "scenario@example.invalid", cwd=src)
    _git("config", "user.name", "scenario", cwd=src)
    (src / "integration").mkdir()
    shutil.copy2(str(REPO / "integration" / "scenario_ledger.py"),
                 str(src / "integration" / "scenario_ledger.py"))
    eng = src / "server" / "engine"
    eng.mkdir(parents=True)
    shutil.copy2(str(REPO / "server" / "engine" / "failure_protocol.py"),
                 str(eng / "failure_protocol.py"))
    (src / "integration" / "run_scenarios.py").write_text(
        "# fixture stand-in marker\n", encoding="utf-8")
    tools = src / "tools"
    tools.mkdir()
    (tools / "stub_suite.py").write_text(_STUB, encoding="utf-8")
    (src / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "fixture: t261024-70 %s" % tag, cwd=src)
    _git("worktree", "add", "-b", "line/x", str(wt), "main", cwd=src)
    wt.joinpath(BOOK_REL).parent.mkdir(parents=True, exist_ok=True)
    wt.joinpath(BOOK_REL).write_text(json.dumps(
        {"meta": {"policy": "shrink-only"},
         "entries": [{"name": "old_red", "verdict": "booked",
                      "owner": "integration", "retire_when": "never"}]}),
        encoding="utf-8")
    _git("add", "-A", cwd=wt)
    _git("commit", "-qm", "seed book on the line", cwd=wt)
    return _git("rev-parse", "HEAD", cwd=src).stdout.strip()


class Fixture:
    """One project, one line, one repo; the develop worktree lives at the
    production-shape wt/RA path and IS the line checkout carrying the
    book."""

    def __init__(self, tmp, tag):
        self.tmp = tmp
        self.ledger_dir = tmp / ("ledger-" + tag)
        self.projects = tmp / ("projects-" + tag)
        self.src = tmp / ("repo-" + tag)
        dev = self.projects / PROJECT / "data" / "develop"
        wt_root = dev / "wt"
        wt_root.mkdir(parents=True)
        self.wt = wt_root / "RA"
        self.head = _mk_repo_at(self.src, self.wt, tag)
        (dev / "lines.json").write_text(json.dumps([
            {"line_id": LINE, "scope": "epic", "owner": "integration",
             "repositories": [{"name": "RA", "branch": "line/x"}],
             "extra_scenarios": [], "version": 1}]), encoding="utf-8")

    def base_env(self, tag):
        env = clean_narrowing_env(extra={
            "SANDBAR_PROJECTS_DIR": str(self.projects),
            "SANDBAR_DELIVERY_LEDGER_DIR": str(self.ledger_dir),
            RUNNER_VAR: "python3 %s/integration/line_round_runner.py"
                        % REPO,
            # the repo name is normalized to uppercase, so the per-repo
            # source path key is the uppercase form (census-compliant).
            "SANDBAR_LINE_ROUND_REPO_PATH_RA": str(self.src),
            "SANDBAR_LINE_ROUND_SUITE_CMD": "python3 tools/stub_suite.py",
            "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": "120",
            "SANDBAR_LINE_ROUND_RUN_ROOT":
                str(self.tmp / ("runroot-" + tag)),
            "SANDBAR_LINE_ROUND_FACE_DIR":
                str(self.tmp / ("face-" + tag)),
        })
        return env


def _ambient(env_vars):
    """Patch the ambient os.environ the way the production worker carries
    it; returns the restore list."""
    saved = {k: os.environ.get(k) for k in env_vars}
    for k, v in env_vars.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return saved


def _restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _seam_env():
    """The env an AMBIENT-ONLY worker carries: just the runner command and
    its timeout (the ticket's evidence face), nothing else declared."""
    return {RUNNER_VAR: os.environ.get(RUNNER_VAR, ""),
            "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": "120"}


def _refusal_rows(ledger_dir):
    """Reader side: every refusal-shaped row in any jsonl face in the
    ledger directory EXCEPT the delivery ledger itself. Returns a list of
    (filename, row)."""
    out = []
    if not ledger_dir.is_dir():
        return out
    for f in sorted(ledger_dir.glob("*.jsonl")):
        if f.name == dc.MAIN_NAME:
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row, dict) \
                    and row.get("state") in ("runner_missing", "error"):
                out.append((f.name, row))
    return out


def _ledger_lines(ledger_file):
    if not ledger_file.is_file():
        return []
    return [json.loads(x) for x in
            ledger_file.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def main():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="t26102470-env-inherit-"))
    if shutil.which("git") is None:
        env_fail("git absent", "the fixture needs a real git")
        sys.exit(2)

    fxA = Fixture(_TMP, "main")

    # ---- A: THE incident, scheduled face — ambient env reaches the seam.
    # The ambient base is the WORKER's full environment (fixture mechanics +
    # the runner command), exactly what the production worker carries.
    ambient_a = dict(fxA.base_env("a"))
    ambient_a[RUNNER_VAR] = ("python3 %s/integration/line_round_runner.py"
                             % REPO)
    saved = _ambient(ambient_a)
    try:
        seen = {}
        real_runner = {}

        def delegating_seam(line, env):
            seen["env"] = dict(env or {})
            try:
                r = dc.resolve_runner(line, env)
            except Exception as e:  # noqa: BLE001
                seen["err"] = "%s:%s" % (type(e).__name__, e)
                return None
            real_runner["runner"] = r
            return r

        res = dc.line_round_tick(
            PROJECT, load_lines=lambda p: [LINE],
            read_rows=lambda: ([], []), append_rows=lambda b: None,
            resolve_runner_fn=delegating_seam, guard_path=str(_TMP
                                                              / "guard-a"),
            now_ms=1)
        entry = (res.get("lines") or [{}])[0]
        env_seen = seen.get("env", {})
        ok(RUNNER_VAR in env_seen and str(env_seen.get(RUNNER_VAR, ""))
           .endswith("line_round_runner.py"),
           "A1 the tick hands the seam the AMBIENT runner command "
           "(env=None caller, no declared env)",
           "seam env keys sample: %s" % sorted(env_seen)[:12])
        ok(real_runner.get("runner") is not None and "err" not in seen,
           "A2 the seam RESOLVES a runner — the line never answers "
           "runner_missing for an ambient-only cause",
           "resolve err: %s" % seen.get("err"))
        # ---- B: the round actually starts
        runroot = _TMP / "runroot-a"
        header = None
        runner = real_runner.get("runner")
        if runner is not None:
            try:
                header = runner([{"repo": "RA", "revision": fxA.head}])
            except dc.CouldNotRun as e:
                seen["cnr"] = str(e)
        ok(isinstance(header, dict)
           and str(header.get("id", "")).startswith("run-")
           and header.get("cases", {}).get("env_failed") == 0,
           "B1 the resolved runner produces one real green header",
           "header: %s cnr: %s" % (json.dumps(header or {})[:200],
                                   seen.get("cnr")))
        rounds_a = _TMP / "face-a"
        ok(rounds_a.is_dir() and any(rounds_a.iterdir()),
           "B2 a round directory appears on the line round face dir "
           "(SANDBAR_LINE_ROUND_FACE_DIR, reader side)",
           "rounds: %s" % (sorted(p.name for p in rounds_a.iterdir())
                           if rounds_a.is_dir() else "absent"))
    finally:
        _restore(saved)

    # ---- C: THE incident, forced face — run_now starts the round
    saved = _ambient(_seam_env())
    try:
        fx2 = Fixture(_TMP, "forced")
        env_c = fx2.base_env("c")
        saved2 = _ambient(env_c)
        try:
            res = dc.line_round_run_now(PROJECT)
        finally:
            _restore(saved2)
        entry = (res.get("lines") or [{}])[0]
        state = entry.get("state")
        rows = _ledger_lines(dc.ledger_path(PROJECT))
        runroot = _TMP / "runroot-c"
        ok(state not in (None, "runner_missing", "error"),
           "C1 the FORCED round starts (entry state %r, not "
           "runner_missing)" % state,
           "entry: %s" % json.dumps(entry)[:250])
        rounds_c = _TMP / "face-c"
        ok(rounds_c.is_dir() and any(rounds_c.iterdir()),
           "C2 the forced round leaves a round directory on the line "
           "round face dir (reader side)",
           "face-c: %s" % (sorted(p.name for p in rounds_c.iterdir())
                           if rounds_c.is_dir() else "absent"))
        ok(len(rows) >= 1
           and any(LINE in json.dumps(r) for r in rows),
           "C3 the delivery ledger carries at least one row naming the "
           "line (the record-less refusal is never lawful again)",
           "rows: %d sample: %s" % (
               len(rows), json.dumps(rows[-1])[:250] if rows else "-"))
    finally:
        _restore(saved)

    # ---- D: the refusal is NAMED on a face beside the ledger
    saved = _ambient({RUNNER_VAR: None,
                      "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": None})
    try:
        fx3 = Fixture(_TMP, "refused")
        # production shape: a line with history already owns its ledger dir
        # (past rounds wrote it); the incident line was exactly that.
        fx3.ledger_dir.mkdir(parents=True, exist_ok=True)
        saved2 = _ambient({k: v for k, v in fx3.base_env("d").items()
                           if k not in (RUNNER_VAR,)})
        try:
            res_tick = dc.line_round_tick_activity(PROJECT)
            res_now = dc.line_round_tick_activity(PROJECT)
        finally:
            _restore(saved2)
        e_tick = (res_tick.get("lines") or [{}])[0]
        e_now = (res_now.get("lines") or [{}])[0]
        ok(e_tick.get("state") == "runner_missing"
           and e_now.get("state") == "runner_missing",
           "D1 with the ambient runner command ABSENT both faces answer "
           "runner_missing",
           "tick: %s now: %s" % (json.dumps(e_tick)[:150],
                                 json.dumps(e_now)[:150]))
        refusals = _refusal_rows(fx3.ledger_dir)
        named = [r for _, r in refusals if r.get("line") == LINE]
        ledger_rows_d = _ledger_lines(dc.ledger_path(PROJECT))
        ok(len(named) >= 1
           and all(r.get("state") == "runner_missing" for r in named),
           "D2 the refusal is a NAMED row on a face beside the ledger — "
           "an operator sees it without Temporal history",
           "refusal faces: %s" % json.dumps(refusals)[:250])
        # 261025: a substring scan over the WHOLE row also catches free-text notes -
        # the promotion note written tonight mentions "the runner_missing fix" and
        # tripped this check while no refusal row existed. Judge the STRUCTURED
        # fields only (a refusal row would carry the state/reason in one of these).
        _refusal_fields = ("state", "reason", "error", "verdict", "kind")
        def _is_refusal_row(r):
            for k in _refusal_fields:
                v = r.get(k)
                if isinstance(v, str) and v.strip().lower().startswith(
                        "runner_missing"):
                    return True
            return False
        ok(not any(_is_refusal_row(r) for r in ledger_rows_d),
           "D3 the refusal never becomes a delivery-ledger row "
           "(t261009-50 contract kept)",
           "ledger rows: %d" % len(ledger_rows_d))
    finally:
        _restore(saved)

    # ---- E: t261024-50 preserved through the new env merge
    fx4 = Fixture(_TMP, "roster")
    saved = _ambient({
        RUNNER_VAR: "python3 %s/integration/line_round_runner.py" % REPO,
        "SANDBAR_LINE_ROUND_RUNNER_TIMEOUT_S": "120",
        ROSTER_VAR: "/ambient/roster/must-lose.json",
        "SANDBAR_PROJECTS_DIR": str(fx4.projects),
        "SANDBAR_DELIVERY_LEDGER_DIR": str(fx4.ledger_dir),
        "SANDBAR_LINE_ROUND_REPO_PATH_RA": str(fx4.src)})
    try:
        seen = {}

        def capturing(line, env):
            seen["env"] = dict(env or {})
            return None

        res = dc.line_round_tick(
            PROJECT, load_lines=lambda p: [LINE],
            read_rows=lambda: ([], []), append_rows=lambda b: None,
            resolve_runner_fn=capturing, guard_path=str(_TMP / "guard-e"),
            now_ms=1)
        injected = seen.get("env", {}).get(ROSTER_VAR)
        ok(injected is not None
           and injected.endswith(BOOK_REL)
           and injected != "/ambient/roster/must-lose.json",
           "E1 the candidate-tree overlay is injected and WINS over the "
           "ambient roster (t261024-50 kept)",
           "injected: %r" % injected)
        # unreadable book stays a NAMED error through the new merge
        wt_book = fx4.projects / PROJECT / "data" / "develop" / "wt" \
            / "RA" / BOOK_REL
        wt_book.write_text("{not json at all", encoding="utf-8")
        _git("add", "-A", cwd=str(wt_book.parent))
        _git("commit", "-qm", "break the book", cwd=str(wt_book.parent))
        seen.clear()
        res2 = dc.line_round_tick(
            PROJECT, load_lines=lambda p: [LINE],
            read_rows=lambda: ([], []), append_rows=lambda b: None,
            resolve_runner_fn=capturing, guard_path=str(_TMP / "guard-e2"),
            now_ms=1)
        e2 = (res2.get("lines") or [{}])[0]
        try:
            _rr = dc._line_roster_for_round(PROJECT, LINE)
            _rrd = "returned %s" % json.dumps(_rr[0])[:120]
        except Exception as _e:  # noqa: BLE001
            _rrd = "raised %s:%s" % (type(_e).__name__, str(_e)[:120])
        ok(e2.get("state") == "error"
           and "known_red_roster_unreadable" in str(e2.get("error", "")),
           "E2 an unreadable book stays a NAMED CertifyError on the entry",
           "entry: %s | direct roster: %s"
           % (json.dumps(e2)[:200], _rrd))
    finally:
        _restore(saved)

    finish(NAME)
    sys.exit(0 if _ck.failed == 0 else 1)


if __name__ == "__main__":
    main()
