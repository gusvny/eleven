# -*- coding: utf-8 -*-
"""worker_staleness -- read-only stale-worker visibility face (t261008-29, KI-227).

261008 live evidence: the resident worker (pid 1415, started 10-07 09:58) predated
the commit that added run_inspection_surface by ~15h; the periodic inspection
scheduled it, the ticket died in 3s with NotFoundError, and nothing anywhere had
turned red BEFORE the failure. This face answers "can the running worker serve the
code in this tree?" by reading a file, not a stack trace.

What it does (READ-ONLY, observe-only — it never restarts/stops/supervises a
worker and never writes into a lane; a stale worker stays a WARNING for the
operator, never a blocking failure):

  python3 server/engine/worker_staleness.py [--tree]

  - reads the worker fingerprint doc (SANDBAR_WORKER_REGISTRY_FINGERPRINT >
    <engine>/data/worker-registry.json) + pid liveness;
  - probes the tree identity: git rev-parse HEAD + commit time + dirty flag;
  - with --tree: composes the CURRENT activity registry through the same path
    the worker uses (worker.compose_worker_activities, the KI-121 single source)
    so a subset/missing-activity verdict is provable by name, not by hash
    guessing. This mode imports the full engine (seconds, not ms) — the workbench
    route caches its result;
  - prints ONE JSON summary line (same green-line convention as worker_dryrun).
    Exit 0 always unless an internal error prevents the report (exit 1) — a stale
    verdict is a REPORT, not an error.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import pathlib
import time
from datetime import datetime, timezone

_ENGINE_DIR = pathlib.Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

import worker_registry  # noqa: E402  (stdlib-only module, light-import discipline)


def _head_identity(repo_dir: str) -> dict:
    """HEAD sha + commit time + dirty flag for the tree (read-only git probes).
    Every failure is named; an empty sha makes staleness_report answer unknown,
    never 'fresh'."""
    def _git(*args: str):
        try:
            p = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True,
                               text=True, timeout=10)
            return p.returncode, (p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError) as e:
            return 127, "%s: %s" % (type(e).__name__, e)

    rc, sha = _git("rev-parse", "HEAD")
    if rc != 0 or not sha:
        return {"sha": "", "commit_time_ms": 0, "dirty": False,
                "error": "git rev-parse failed (rc=%s): %s" % (rc, sha)}
    rc2, ts = _git("show", "-s", "--format=%ct", "HEAD")
    commit_ms = 0
    if rc2 == 0 and ts:
        try:
            commit_ms = int(float(ts) * 1000)
        except ValueError:
            commit_ms = 0
    rc3, status = _git("status", "--porcelain")
    return {"sha": sha, "commit_time_ms": commit_ms,
            "dirty": bool(rc3 == 0 and status),
            "error": "" if rc3 == 0 else "git status failed (rc=%s): %s" % (rc3, status)}


def _pid_alive(pid) -> "bool | None":
    try:
        p = int(pid or 0)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def collect(tree_mode: bool) -> dict:
    fp_path = worker_registry.fingerprint_path()
    doc, err = worker_registry.read_fingerprint(fp_path)
    head = _head_identity(str(_ENGINE_DIR))

    tree_names = tree_afp = None
    tree_error = ""
    if tree_mode:
        try:
            import worker  # full engine import — same path the worker itself uses
            acts = worker.compose_worker_activities(worker.PROJECT_TEMPLATE_STAGE_IDS)
            tree_names = sorted({worker.activity_registered_name(a) for a in acts})
            tree_afp = worker_registry.activity_fingerprint(tree_names)
        except Exception as e:  # noqa: BLE001 — visibility face degrades named, never crashes the console
            tree_error = "tree composition failed: %s: %s" % (type(e).__name__, e)

    verdict = worker_registry.staleness_report(
        doc, err,
        head_sha=str(head.get("sha") or ""),
        tree_activity_fingerprint=str(tree_afp or ""),
        tree_activity_names=tree_names)

    return {
        "ok": True,
        "face": "worker-staleness (read-only observe; stale = warning, never a block)",
        "fingerprint_path": fp_path,
        "head": head,
        "tree_mode": tree_mode,
        "tree_activity_fingerprint": tree_afp,
        "tree_activity_names": tree_names,
        "tree_error": tree_error,
        "worker": None if doc is None else {
            "pid": doc.get("pid"),
            "alive": _pid_alive(doc.get("pid")),
            "started_at_ms": doc.get("started_at_ms"),
            "code_fingerprint": doc.get("code_fingerprint"),
            "code_dirty": doc.get("code_dirty"),
            "activity_fingerprint": doc.get("activity_fingerprint"),
            "activities_count": None if doc.get("activities") is None else len(doc["activities"]),
        },
        "verdict": verdict,
    }


def main() -> int:
    tree_mode = "--tree" in sys.argv[1:]
    try:
        summary = collect(tree_mode)
    except Exception as e:  # noqa: BLE001
        print("worker-staleness: INTERNAL-FAIL %s: %s" % (type(e).__name__, e))
        return 1
    print(json.dumps(summary, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
