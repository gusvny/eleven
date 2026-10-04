# -*- coding: utf-8 -*-
"""t261004-32 共享夹具：三态出口 / 引擎模块回落链 / 隔离项目根（KI-161：真链测试
必须隔离运行期数据目录，绝不写生产 ~/.sandbar/projects）。纯 stdlib。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B integration/t261004-32/sc_….py
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（闸内无 SKIP）。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO / "server" / "engine"))

_FAILURES = []
_TMPDIRS = []


def isolated_root(prefix="t26100432-"):
    """An isolated absolute projects root (SANDBAR_PROJECTS_DIR contract face)."""
    d = tempfile.mkdtemp(prefix=prefix)
    _TMPDIRS.append(d)
    return Path(d)


def set_projects_root(root):
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)


def engine_modules():
    """Import the engine faces this ticket contracts. Missing engine base (shared)
    = environment red; missing this ticket's own deliverable (concurrency) = FAIL
    face (TDD-phase red), reported via (shared, conc, why)."""
    try:
        import shared
    except Exception as e:
        return None, None, "engine base shared unavailable: %s: %s" % (type(e).__name__, e)
    try:
        import concurrency
        return shared, concurrency, None
    except Exception as e:
        return shared, None, "server/engine/concurrency.py not landed yet (%s: %s)" % (type(e).__name__, e)


def engine_python():
    venv = REPO / "server" / "engine" / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def run_cli(args, project_root, timeout=60, caller_project="pk"):
    """Run server/tools/ticket.py in a subprocess with the isolated root; returns
    (rc, combined_output). L12: the ticket-entry spawn declares its fixture
    identity call-scoped — caller_project is injected into JSON-op payloads in
    this same spawn call, and inherited narrowing/caller knobs are scrubbed so
    the outer lane round cannot narrow the surface under test."""
    import subprocess
    fixed = []
    for a in args:
        if isinstance(a, str) and a.lstrip().startswith("{"):
            try:
                payload = json.loads(a)
                if isinstance(payload, dict):
                    payload.setdefault("caller_project", caller_project)
                    a = json.dumps(payload, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        fixed.append(a)
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(project_root)
    for k in ("SANDBAR_NAMESPACE", "SANDBAR_CALLER_IDENTITY_SRC",
              "SANDBAR_SCENARIO_ONLY"):
        env.pop(k, None)
    # Identity is declared here, not inherited: the fixture project key is the
    # caller identity of this spawn (L12 call-scoped discipline).
    env["SANDBAR_CALLER_PROJECT"] = caller_project
    p = subprocess.run(
        [engine_python(), "-B", str(REPO / "server" / "tools" / "ticket.py")] + fixed,
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print("  [%s] %s%s" % (tag, name, ("  -- " + str(detail)[:300]) if (detail and not cond) else ""))
    if not cond:
        _FAILURES.append(name)


def env_fail(why):
    print("ENV_FAIL: %s" % why)
    cleanup()
    sys.exit(2)


def cleanup():
    for d in _TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)


def summary():
    cleanup()
    if _FAILURES:
        print("\nFAIL: %d case(s) red:" % len(_FAILURES))
        for f in _FAILURES:
            print("  - %s" % f)
        sys.exit(1)
    print("\nPASS: all cases green")
    sys.exit(0)


def guard(fn):
    try:
        fn()
    except SystemExit:
        raise
    except Exception:
        print("FAIL: scenario crashed")
        traceback.print_exc()
        cleanup()
        sys.exit(1)



def register_project(root, key):
    """Write a minimal per-key registry entry (project.yaml, schema v1) inside the
    isolated root so shared.lookup_project can resolve the synthetic project."""
    import json as _json
    d = Path(root) / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
        % (key, key, d), encoding="utf-8")
    return d

def write_decl(root, key, payload):
    d = Path(root) / key
    d.mkdir(parents=True, exist_ok=True)
    f = d / "concurrency-limit.json"
    if isinstance(payload, str):
        f.write_text(payload, encoding="utf-8")
    else:
        f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def expected_waited_older(a, b):
    return a <= b


def now():
    return time.time()
