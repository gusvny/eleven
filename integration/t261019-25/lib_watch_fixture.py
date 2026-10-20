"""Shared grey-box fixture for the t261019-25 run-watch scenarios.

Every scenario here drives the REAL watch entry
(``server/engine/activities.py::run_watch_tick_engine``, the face the plan
declared and the scan workflow calls) over REAL fixture ledgers written
through the real writers (``develop_certify.append_rows``,
``scenario_ledger.append_records`` / ``append_run_header``), isolated from
the machine via env seams. Assertions read records back from the files on
disk (reader side); writer receipts are never evidence.

Declared seams this test set binds to (set at review_plan gen1 and kept in
the plan's changed-file table):
- ``activities.run_watch_tick_engine``   -- the per-tick entry (no args).
- ``run_watch.start_fix_ticket``         -- module-level callable, the ONLY
  injectable ticket seam (default: engine client dev-lane start). The
  scenarios swap it for a recorder; nothing else about tickets is bound.
- ``run_watch_state.json`` under the project develop dir -- the declared
  idempotency file (review ruling R2).

Offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233.
"""
import asyncio
import atexit
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
for _p in (str(ENGINE), str(REPO), str(REPO / "integration")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import develop_certify  # noqa: E402
import executor_requests  # noqa: E402
import scenario_ledger as sl  # noqa: E402

PROJECT = "proj26101925"
LINE = "line-main"
REPO_NAME = "proj26101925"
TICKET = "t261019-25"
SESSION = "sc26101925"

ENV_LEDGER = "SANDBAR_DELIVERY_LEDGER_DIR"
ENV_SCEN = "SANDBAR_SCENARIO_LEDGER_DIR"
ENV_PROJECTS = "SANDBAR_PROJECTS_DIR"
ENV_PANEL = "SANDBAR_PANEL_DIR"
ENV_FACE = "SANDBAR_LINE_ROUND_FACE_DIR"

ENV_FAIL = 2


class SurfaceMissing(Exception):
    """The declared watch face is absent on this tree."""


class EnvMissing(Exception):
    """The engine tree / its imports are unusable (ENV_FAIL)."""


def reclaim(root):
    """Reclaim the fixture root (rmtree) - every scenario calls this on its
    way out so the fixture never leaks into the host temp area (KI tmp
    hygiene family)."""
    shutil.rmtree(str(root), ignore_errors=True)


def hexs(n):
    return hashlib.sha256(("%s%s" % (n, time.time_ns())).encode()).hexdigest()[:n]


def build_env():
    """Isolated fixture env: tmp ledger, scenario ledger, projects root,
    requests panel root, rounds face dir. Caller-env values are taken from
    the engine's own grant module, never hardcoded."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="sc26101925-"))
    atexit.register(reclaim, root)
    env = dict(os.environ)
    env[ENV_LEDGER] = str(root / "ledger")
    env[ENV_SCEN] = str(root / "scenledger")
    env[ENV_PROJECTS] = str(root / "projects")
    env[ENV_PANEL] = str(root / "panel")
    env[ENV_FACE] = str(root / "face")
    for d in (ENV_LEDGER, ENV_SCEN, ENV_PROJECTS, ENV_PANEL):
        os.makedirs(env[d], exist_ok=True)
    (pathlib.Path(env[ENV_FACE]) / "rounds").mkdir(parents=True, exist_ok=True)
    try:
        import shared
        import executor_grants
        env[shared.CALLER_PROJECT_ENV] = PROJECT
        for name in executor_grants.CALLER_SESSION_ENVS:
            env[name] = SESSION
    except Exception:
        pass
    return root, env


def declare_project(env):
    decl = pathlib.Path(env[ENV_PROJECTS]) / PROJECT / "data" / "develop"
    decl.mkdir(parents=True, exist_ok=True)
    (decl / "lines.json").write_text(json.dumps([
        {"line_id": LINE,
         "repositories": [{"name": REPO_NAME, "branch": "develop"}]}
    ]), encoding="utf-8")
    # the host's executor-session declaration (the request identity gate is
    # fail-closed without it - the watch files no request)
    grants = pathlib.Path(env[ENV_PROJECTS]) / PROJECT / "executor-grants.json"
    grants.write_text(json.dumps({
        "version": 1,
        "executor_sessions": [SESSION + "-exec"],
        "grants": {},
    }), encoding="utf-8")
    return decl


def ledger_file(env):
    return develop_certify.ledger_path(PROJECT, ledger_dir=env[ENV_LEDGER])


def delivery_append(env, rows):
    out = develop_certify.append_rows(rows, path=ledger_file(env))
    bad = out.get("rejected") if isinstance(out, dict) else None
    if bad:
        raise AssertionError("fixture delivery rows refused: %r" % (bad,))
    return out


def case_row(run_id, commit, verdict, scenario, at_s):
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(at_s)),
        "commit": commit, "env_fp": hexs(64), "conc_width": 1,
        "pool": "fast", "scenario": scenario, "verdict": verdict,
        "wall_s": 1, "source": "lane:line-round", "ticket": TICKET,
        "run": run_id,
    }


def env_applied(env):
    """Context manager: the fixture env IS the process env while the real
    writers run (their isolation reads os.environ, e.g. the header recount)."""

    class _Ctx:
        def __enter__(self):
            self.old = {k: os.environ.get(k) for k in
                        (ENV_LEDGER, ENV_SCEN, ENV_PROJECTS, ENV_PANEL, ENV_FACE)}
            os.environ.update({k: env[k] for k in self.old})
            return env

        def __exit__(self, *exc):
            for k, v in self.old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            return False

    return _Ctx()


def write_run(env, run_id, verdicts, at_s, revision="rev1"):
    """Write case rows through the real writer, then the header through
    append_run_header (which recounts and refuses a fake summary)."""
    commit = hexs(40)
    rows = [case_row(run_id, commit, v, "sc-%02d" % i, at_s + i)
            for i, v in enumerate(verdicts)]
    with env_applied(env):
        out = sl.append_records(rows, path=_scen_main(env))
        if out.get("rejected"):
            raise AssertionError("fixture case rows refused: %r" % (out["rejected"],))
        counts = {"ran": len(verdicts), "passed": verdicts.count("pass"),
                  "failed": verdicts.count("fail"),
                  "env_failed": verdicts.count("env_fail")}
        header = {
            "v": sl.RUN_HEADER_V, "id": run_id,
            "repos": [{"repo": REPO_NAME, "revision": revision}],
            "suite": "full", "source": "lane:line-round", "env_fp": hexs(64),
            "conc_width": 1, "pool": "fast",
            "started_at": int(at_s * 1000), "duration_s": 1.0,
            "cases": counts, "verdict": sl.run_verdict(counts),
        }
        rout = sl.append_run_header(
            header, path=pathlib.Path(env[ENV_LEDGER]) / sl.RUNS_NAME)
    if rout.get("written") != 1:
        raise AssertionError("fixture run header refused: %r" % (rout,))
    return header


def _scen_dir(env):
    return pathlib.Path(env[ENV_SCEN])


def _scen_main(env):
    return _scen_dir(env) / sl.MAIN_NAME


def _scen_runs(env):
    return _scen_dir(env) / sl.RUNS_NAME


def cert_row_for(run_header, at_ms, booked_red="none"):
    return develop_certify.build_certification(
        [{"repo": REPO_NAME, "revision": "rev1"}], run_header,
        booked_red=booked_red, judged_by="line-round", line=LINE, at_ms=at_ms)


def landing_row(ticket, at_ms, ldg_id=None):
    return {
        "kind": develop_certify.KIND_LANDING,
        "id": ldg_id or ("ldg-" + hexs(10)),
        "ticket": ticket, "line": LINE,
        "repos": [{"repo": REPO_NAME, "revision": "rev1"}],
        "actor": SESSION, "at": int(at_ms),
    }


def tick(env):
    """One real watch tick under the isolated env. Returns the tick result
    dict. Absent face = named SurfaceMissing (pre-implement TDD signal)."""
    old = {k: os.environ.get(k) for k in
           (ENV_LEDGER, ENV_SCEN, ENV_PROJECTS, ENV_PANEL, ENV_FACE)}
    os.environ.update({k: env[k] for k in old})
    try:
        try:
            import activities
        except Exception as e:  # engine tree unusable in this lane
            raise EnvMissing("activities unimportable: %r" % (e,))
        face = getattr(activities, "run_watch_tick_engine", None)
        if face is None:
            raise SurfaceMissing("activities.run_watch_tick_engine missing")
        return asyncio.run(face())
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def read_delivery(env):
    rows, bad = develop_certify.read_rows(ledger_file(env))
    return rows, bad


def read_runs(env):
    rows, bad = sl.read_rows(_scen_main(env))
    return rows, bad


def read_run_headers(env):
    """The watch's run-header store: scenario-runs.jsonl BESIDE the delivery
    ledger (the store the round itself writes)."""
    rows, bad = sl.read_rows(pathlib.Path(env[ENV_LEDGER]) / sl.RUNS_NAME)
    return rows, bad


def requests_file(env):
    return executor_requests.ledger_file(PROJECT, env=env)


def read_requests(env):
    f = requests_file(env)
    if not f.is_file():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


def freeze_change_rows(rows):
    return [r for r in rows
            if r.get("kind") == develop_certify.KIND_FREEZE_CHANGE]


def silent_round(env, run_id, verdict="red", at_s=None):
    """A terminal round face with NO run header behind it (the round ended,
    the row never landed) - the watch's silent-end shape."""
    d = pathlib.Path(env[ENV_FACE]) / run_id
    d.mkdir(parents=True, exist_ok=True)
    ts = int((at_s or time.time()) * 1000)
    (d / "face.json").write_text(json.dumps({
        "run_id": run_id, "state": "done",
        "outcome": {"verdict": verdict, "reason": ""},
        "started_at": ts, "updated_at": ts,
    }), encoding="utf-8")


def snapshot(roots):
    """sha256 over every file under roots (reader-side read-only proof)."""
    out = {}
    for root in roots:
        root = pathlib.Path(root)
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def tick_deep(env, **seams):
    """One tick through the module's own per-project entry
    (``run_watch.run_watch_tick``) with its DECLARED injectable seams
    (``start_fix_ticket`` / ``retry_round``) swapped for scenario recorders.
    Returns the per-line decision dict."""
    os.environ.update({k: env[k] for k in
                       (ENV_LEDGER, ENV_SCEN, ENV_PROJECTS, ENV_PANEL, ENV_FACE)})
    try:
        import run_watch
        fn = getattr(run_watch, "run_watch_tick", None)
        if fn is None:
            raise SurfaceMissing("run_watch.run_watch_tick missing")
        return fn(PROJECT, **seams)
    finally:
        for k in (ENV_LEDGER, ENV_SCEN, ENV_PROJECTS, ENV_PANEL, ENV_FACE):
            os.environ.pop(k, None)


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def ok(msg):
    print("PASS: %s" % msg)
