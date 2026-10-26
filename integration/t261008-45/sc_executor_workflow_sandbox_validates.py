#!/usr/bin/env python3
"""sc_executor_workflow_sandbox_validates — the central worker starts and the
workflow sandbox accepts every registered workflow, ExecutorDeliveryWorkflow
included (t261008-45, gray-box L3).

User-perceivable contract (ticket user request, verbatim): "Make the shared.py
path constants lazy so the workflow sandbox validates, and prove it with a real
worker start." The user-visible failure was: the engine pool stayed red because
the worker rejected exactly one workflow class at materialization time
(RestrictedWorkflowAccessError on pathlib.Path.resolve executed while the
sandbox re-imported the workflow's module). The contract guarded here:

  A. REAL WORKER START (the ticket's proof, reader-side evidence): a real
     worker.py process, started as a subprocess against the process bench
     (integration/lib_proc_bench.ensure, a plain-process Temporal server; the
     bench owns the process and reaps it at exit), comes up polling the engine
     task queue — a SECOND process
     (the reader) connects to the same endpoint and sees >=1 poller on that task
     queue via describe_task_queue. The worker log must NOT contain a
     RestrictedWorkflowAccessError. The worker is then terminated with SIGTERM
     and is reaped (no orphan).
  B. SANDBOX RE-IMPORT FAMILY GUARD: replaying the exact sandbox face
     (temporalio's workflow-sandbox importer with default restrictions) over
     every module holding a registered workflow class must succeed — the fix
     must not merely unblock today's class while leaving the trap armed for
     the next module that imports shared at module level.

Anchoring discipline: assertions land on process behavior (poller count seen
from a separate client connection, absence of the named sandbox error, exit
status on TERM) and on the public registry (worker.ALL_WORKFLOWS /
ALL_WORKFLOWS_V2 names) — no internal shared.py names, no import-order
assumptions. A contract-preserving refactor of how the path constants are
made lazy must not break this scenario; a regression that makes the sandbox
reject any registered workflow must.

Three-state: the bench refusing to boot = ENV_FAIL exit 2 (honest red, never
SKIP). Pre-fix tree expected red (TDD signal); green at the integration gate.
Stdlib + engine venv (temporalio) only; never touches 3099/7233/8233.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent      # <ticket>/integration/t261008-45
REPO = HERE.parents[1]                      # <ticket> root
sys.path.insert(0, str(REPO / "integration" / "t260904-02"))  # shared stage helpers (fixture reuse)
sys.path.insert(0, str(REPO / "integration"))

ENGINE = REPO / "server" / "engine"
WORKER = ENGINE / "worker.py"
VENV_PY = ENGINE / ".venv" / "bin" / "python"

GRACE_START_S = 60
GRACE_TERM_S = 30


class Fail(Exception):
    pass


def check(cond, label, detail=""):
    if cond:
        print("PASS: %s" % label)
    else:
        raise Fail("%s%s" % (label, (" — " + detail) if detail else ""))


def engine_python():
    if VENV_PY.exists():
        return [str(VENV_PY)]
    return [sys.executable]


def registry_modules():
    """Workflow modules (name -> source file) from the public registry (same
    source the real worker uses). External template modules register under a
    synthetic name with no importable path, so the sandbox replay below loads
    each module from its real __spec__.origin file instead of import_module."""
    code = (
        "import sys, json; sys.path.insert(0, %r)\n"
        "import worker\n"
        "mods = {}\n"
        "for c in list(worker.ALL_WORKFLOWS) + list(worker.ALL_WORKFLOWS_V2):\n"
        "    n = getattr(c, '__module__', '')\n"
        "    origin = getattr(getattr(sys.modules.get(n), '__spec__', None), 'origin', None)\n"
        "    if origin and n not in mods:\n"
        "        mods[n] = origin\n"
        "print(json.dumps(mods))\n"
    ) % str(ENGINE)
    p = subprocess.run(engine_python() + ["-c", code], capture_output=True, text=True, timeout=120, cwd=str(ENGINE))
    if p.returncode != 0:
        raise Fail("registry read failed (worker.py import): %s" % (p.stderr or p.stdout)[-400:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def case_b_sandbox_family():
    mods = registry_modules()
    check(len(mods) > 0, "B0 registry lists workflow modules", "empty registry")
    for mod, origin in sorted(mods.items()):
        # Fresh execution of the SAME source under the default sandbox — the
        # exact face a real worker start applies to workflow modules. Fresh
        # interpreter: dependencies (shared, executor_*) are imported inside
        # the restricted context too, which is where the original failure
        # (pathlib.Path.resolve at shared.py import time) lived.
        code = (
            "import sys, importlib.util; sys.path.insert(0, %r)\n"
            "from temporalio.worker.workflow_sandbox import _importer\n"
            "imp = _importer.Importer(_importer.SandboxRestrictions.default, _importer.RestrictionContext())\n"
            "with imp.applied():\n"
            "    spec = importlib.util.spec_from_file_location('sc_replay_%s', %r)\n"
            "    m = importlib.util.module_from_spec(spec)\n"
            "    sys.modules[spec.name] = m\n"
            "    spec.loader.exec_module(m)\n"
            "print('OK')\n"
        ) % (str(ENGINE), re.sub(r"\W", "_", mod), origin)
        p = subprocess.run(engine_python() + ["-c", code], capture_output=True, text=True, timeout=180, cwd=str(ENGINE))
        check(p.returncode == 0 and "OK" in p.stdout,
              "B sandbox re-import accepts %s under default restrictions" % mod,
              (p.stderr or p.stdout)[-500:])


def start_real_worker(env, log_path):
    logf = open(log_path, "w")
    return subprocess.Popen(engine_python() + [str(WORKER)], stdout=logf, stderr=subprocess.STDOUT,
                            cwd=str(ENGINE), env=env)


def wait_for_log(log_path, pattern, timeout):
    rx = re.compile(pattern)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            text = Path(log_path).read_text(errors="replace")
        except OSError:
            text = ""
        m = rx.search(text)
        if m:
            return text, m
        time.sleep(1.0)
    return Path(log_path).read_text(errors="replace") if Path(log_path).exists() else "", None


def poller_count(target, namespace, task_queue):
    """Reader-side probe: a separate client connection describes the task
    queue and counts pollers. Runs in the engine venv (temporalio)."""
    code = (
        "import asyncio, json\n"
        "from temporalio.client import Client\n"
        "from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest\n"
        "from temporalio.api.taskqueue.v1 import TaskQueue\n"
        "async def main():\n"
        "    c = await Client.connect(%r, namespace=%r)\n"
        "    try:\n"
        "        resp = await c.workflow_service.describe_task_queue(\n"
        "            DescribeTaskQueueRequest(namespace=%r, task_queue=TaskQueue(name=%r)),\n"
        "            retry=False)\n"
        "    except Exception as e:\n"
        "        print(json.dumps({'error': str(e)[:300]})); return\n"
        "    n = len(getattr(resp, 'pollers', []) or [])\n"
        "    if n == 0:\n"
        "        n = len(getattr(resp, 'poller_info', []) or [])\n"
        "    print(json.dumps({'pollers': n}))\n"
        "asyncio.run(main())\n"
    ) % (target, namespace, namespace, task_queue)
    p = subprocess.run(engine_python() + ["-c", code], capture_output=True, text=True, timeout=60)
    out = p.stdout.strip().splitlines()
    if p.returncode != 0 or not out:
        raise Fail("reader task-queue probe failed: %s" % (p.stderr or "")[-400:])
    data = json.loads(out[-1])
    if "error" in data:
        raise Fail("reader task-queue probe error: %s" % data["error"])
    return int(data["pollers"])


def case_a_real_worker_start(endpoint, fail):
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % endpoint["port"]
    env["SANDBAR_NAMESPACE"] = endpoint["namespace"]
    env["PYTHONUNBUFFERED"] = "1"
    tq_code = "import sys; sys.path.insert(0, %r)\nimport shared\nprint(shared.TASK_QUEUE)\n" % str(ENGINE)
    p = subprocess.run(engine_python() + ["-c", tq_code], capture_output=True, text=True, timeout=60, cwd=str(ENGINE))
    if p.returncode != 0:
        fail("task queue name read failed: %s" % (p.stderr or "")[-300:])
        return
    task_queue = p.stdout.strip().splitlines()[-1]

    with tempfile.TemporaryDirectory() as td:
        log = os.path.join(td, "worker.log")
        proc = start_real_worker(env, log)
        try:
            text, m = wait_for_log(log, r"(polling queues|RestrictedWorkflowAccessError|Traceback)", GRACE_START_S)
            if m and "RestrictedWorkflowAccessError" in m.group(0):
                fail("A worker rejected a workflow at sandbox import: %s" % text[-800:])
                return
            check(m is not None and "polling queues" in m.group(0),
                  "A1 real worker process comes up polling (no sandbox rejection)",
                  text[-800:] if m is None else "")
            n = poller_count(env["SANDBAR_TARGET_HOST"], endpoint["namespace"], task_queue)
            check(n >= 1, "A2 reader-side: engine task queue has pollers (count=%d)" % n,
                  "describe_task_queue saw 0 pollers")
            check("RestrictedWorkflowAccessError" not in text,
                  "A3 worker log free of RestrictedWorkflowAccessError")
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=GRACE_TERM_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
        check(proc.returncode is not None, "A4 worker reaped after SIGTERM (rc=%s)" % proc.returncode,
              "worker did not exit")


def main():
    class _Gate:
        """The endpoint supply expects a gate object with .bail(msg, code);
        env codes (2) pass through as the three-state ENV_FAIL."""
        def bail(self, msg, code=1):
            print("FAIL  %s" % msg)
            sys.exit(code)

    try:
        case_b_sandbox_family()
        # Process-bench supply (host order 261026, batch 1): the bench owns the
        # Temporal process and reaps it at interpreter exit (its own atexit
        # handle) — no docker stage, no orphan process. A bench boot refusal
        # stays the three-state ENV_FAIL exit 2, never a silent skip.
        import lib_proc_bench  # noqa: E402
        endpoint = lib_proc_bench.ensure(namespace="default")
        case_a_real_worker_start(endpoint, _Gate())
        print("ALL PASS")
    except Fail as e:
        print("FAIL: %s" % e)
        sys.exit(1)
    except RuntimeError as e:
        print("ENV_FAIL: process bench boot refused (worker-start journey needs a live "
              "Temporal endpoint): %s" % str(e)[:300])
        sys.exit(2)


if __name__ == "__main__":
    main()
