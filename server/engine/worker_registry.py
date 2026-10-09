# -*- coding: utf-8 -*-
"""worker_registry -- worker workflow-registration fingerprint face
(t261004-44, KI-197 way out (2)).

Root cause (261004 night, live evidence): the resident worker started at 10:20:27
while ExecutorDeliveryWorkflow was only registered into workflows.py at 19:30 --
the worker does not know the class, every activation raises NotFoundError, Temporal
retries with backoff forever, and the caller `deliver` waits unbounded, unable to
tell "slow" from "this face was dead the moment you called it".

This face: at startup the worker writes which workflow classes it knows into a
fingerprint file (atomic write); `client.py deliver` reads it BEFORE starting --
class absent = named refusal (rc != 0, names the class and the registered set, no
workflow started, never a hang). The fingerprint is a fast-path refusal ENABLER,
not a health certificate: when the file is readable but provably stale (old pid /
old code fingerprint) and the class IS listed, deliver proceeds under the bounded
wait -- the single definition of that semantics lives in
`delivery_registration_check`.

File location: env SANDBAR_WORKER_REGISTRY_FINGERPRINT > <engine>/data/worker-registry.json.
Light-import discipline: stdlib-only, temporalio-free (same as the audit faces);
tests import it bare.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

FINGERPRINT_ENV = "SANDBAR_WORKER_REGISTRY_FINGERPRINT"
#: t261008-29 (KI-227): version 2 adds the ACTIVITY registry (names + stable hash)
#: and a real code fingerprint (the sha the process started from + dirty flag).
#: v1 files stay readable: `read_fingerprint` treats a missing `activities` key as
#: "unknown", never malformed, so the deliver fast-refusal keeps working across the
#: upgrade window.
FINGERPRINT_VERSION = 2
#: Env override for the code identity (tests, sandboxes without git): "<sha>" or
#: "<sha>:dirty". Absent/empty = probe the tree with git.
CODE_FINGERPRINT_ENV = "SANDBAR_WORKER_CODE_FINGERPRINT"
POC_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FINGERPRINT_PATH = os.path.join(POC_DIR, "data", "worker-registry.json")
#: The class this face polices (the named-refusal target of t261004-44).
DELIVERY_WORKFLOW_CLASS = "ExecutorDeliveryWorkflow"


def fingerprint_path(env: Optional[Dict[str, str]] = None) -> str:
    """Fingerprint file path (env injection > engine data dir). Tests point the env
    into a temp directory."""
    env = env if env is not None else os.environ
    return str(env.get(FINGERPRINT_ENV) or DEFAULT_FINGERPRINT_PATH)


def activity_fingerprint(activity_names: List[str]) -> str:
    """Stable hash of the sorted activity name set (KI-227): the exact thing that
    went stale on 261008 -- a worker that cannot serve an activity a workflow will
    schedule. Sorted before hashing so registration order never moves the hash."""
    return hashlib.sha256(
        "\n".join(sorted(str(n) for n in activity_names)).encode("utf-8")).hexdigest()


def code_identity(repo_dir: str = POC_DIR,
                  env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The code identity the process loaded at startup (KI-227 gap 2): the commit
    sha of the tree it started from + a dirty flag (a worker must not silently
    serve a tree it did not load).

    Resolution order: env SANDBAR_WORKER_CODE_FINGERPRINT ("<sha>" or
    "<sha>:dirty") > git probe of repo_dir. Every failure path is NAMED, never a
    silent empty success: the caller writes whatever this returns into
    code_fingerprint, and `staleness_report` reports unknown (not stale) when the
    sha is empty. Git probe failures are swallowed into a named error string --
    best-effort, same discipline as the fingerprint write itself."""
    env = env if env is not None else os.environ
    override = str(env.get(CODE_FINGERPRINT_ENV) or "")
    if override:
        sha, _, dirty = override.partition(":")
        return {"sha": sha, "dirty": dirty == "dirty", "source": "env",
                "error": "" if sha else "env override carries an empty sha"}

    def _git(*args: str) -> Tuple[int, str]:
        try:
            p = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True,
                               text=True, timeout=10)
            return p.returncode, (p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError) as e:
            return 127, "%s: %s" % (type(e).__name__, e)

    rc, sha = _git("rev-parse", "HEAD")
    if rc != 0 or not sha:
        return {"sha": "", "dirty": False, "source": "git",
                "error": "git rev-parse failed (rc=%s): %s" % (rc, sha or "no output")}
    rc2, status = _git("status", "--porcelain")
    if rc2 != 0:
        return {"sha": sha, "dirty": False, "source": "git",
                "error": "git status failed (rc=%s): %s" % (rc2, status)}
    return {"sha": sha, "dirty": bool(status), "source": "git", "error": ""}


def write_fingerprint(path: str, workflow_names: List[str],
                      pid: int, now_ms: int,
                      code_fingerprint: str = "",
                      activity_names: Optional[List[str]] = None,
                      code_dirty: bool = False) -> Dict[str, Any]:
    """Atomic write (tmp+rename, engine-side disk discipline); shape (v2)::

        {"version": 2, "pid": int, "started_at_ms": int,
         "code_fingerprint": str, "registered": [class name, ...],
         "activities": [activity name, ...], "activity_fingerprint": sha256,
         "code_dirty": bool}
    `code_fingerprint` empty = the identity probe failed (named in
    `code_identity().error`, logged by the caller) -- an empty value is an honest
    "unknown", never a made-up hash. Returns the written doc (caller logs it).
    Write failures are swallowed loudly by the caller -- a missing fingerprint
    makes deliver degrade to the bounded wait, never blocks worker startup."""
    acts = [str(n) for n in (activity_names or [])]
    doc: Dict[str, Any] = {
        "version": FINGERPRINT_VERSION,
        "pid": int(pid),
        "started_at_ms": int(now_ms),
        "code_fingerprint": str(code_fingerprint),
        "registered": [str(n) for n in workflow_names],
        "activities": acts,
        "activity_fingerprint": activity_fingerprint(acts),
        "code_dirty": bool(code_dirty),
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".worker-registry-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return doc


def read_fingerprint(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Read the fingerprint. Returns (doc, None) or (None, named error). Three error
    classes: absent (worker predates this face / foreground mode wrote none) /
    unreadable / malformed -- none of them blocks the startup decision; the caller
    degrades explicitly (named, never silently treated as healthy)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None, "absent"
    except (OSError, UnicodeDecodeError) as e:
        return None, "unreadable: %s: %s" % (type(e).__name__, e)
    except json.JSONDecodeError as e:
        return None, "malformed: JSON parse failed (%s)" % e
    if not isinstance(doc, dict) or doc.get("version") not in (1, FINGERPRINT_VERSION) \
            or not isinstance(doc.get("registered"), list) \
            or any(not isinstance(n, str) for n in doc.get("registered", [])):
        return None, ("malformed: fingerprint shape is wrong "
                      "(need {version: 1|2, registered: [str,...]})")
    # v1 upgrade window: a v1 doc carries no activities. Normalise it to an
    # explicit unknown instead of a KeyError downstream (named absence, never a
    # guess that the worker serves nothing).
    if doc.get("version") == 1:
        doc.setdefault("activities", None)
        doc.setdefault("activity_fingerprint", "")
        doc.setdefault("code_dirty", False)
    if "activities" in doc and doc["activities"] is not None \
            and (not isinstance(doc["activities"], list)
                 or any(not isinstance(n, str) for n in doc["activities"])):
        return None, "malformed: activities must be a list of strings (or null)"
    if not isinstance(doc.get("code_fingerprint", ""), str) \
            or not isinstance(doc.get("activity_fingerprint", ""), str) \
            or not isinstance(doc.get("code_dirty", False), bool):
        return None, "malformed: code_fingerprint/activity_fingerprint must be strings, code_dirty a bool"
    return doc, None


def delivery_registration_check(doc: Optional[Dict[str, Any]],
                                workflow_class: str = DELIVERY_WORKFLOW_CLASS,
                                ) -> Dict[str, Any]:
    """The pre-flight registry check for deliver (single semantics point; review C3).

    - doc None/malformed -> ``{"ok": True, "degraded": "<named>"}``: proceed, the
      bounded wait is the backstop (a missing fingerprint never means healthy, only
      that the fast refusal is unavailable);
    - class listed -> ``{"ok": True}``: proceed -- **a stale fingerprint (dead pid /
      old code) does NOT change this verdict**; staleness risk is carried by the
      bounded wait (review C3's explicit rule);
    - class absent -> ``{"ok": False, "registered": [...], "pid", "started_at_ms"}``:
      the caller refuses immediately with a named message, no workflow started.
    """
    if doc is None:
        return {"ok": True, "degraded": "worker registration fingerprint absent -- "
                "worker predates the fingerprint face; falling back to the bounded wait"}
    reg = [str(n) for n in doc.get("registered", [])]
    if workflow_class in reg:
        return {"ok": True}
    return {
        "ok": False,
        "registered": reg,
        "pid": doc.get("pid"),
        "started_at_ms": doc.get("started_at_ms"),
        "workflow_class": workflow_class,
    }


# ---- staleness visibility face (t261008-29, KI-227 gap 3) ----
#
# Root cause (261008 live evidence): worker pid 1415 started 10-07 09:58, fifteen
# hours before the commit that added run_inspection_surface; when the periodic
# inspection scheduled it, the ticket died in 3 seconds with NotFoundError and the
# blame landed on the ticket. Nothing compares the RUNNING process with the tree
# before a workflow schedules the new activity.
#
# This face is a PURE comparison: it takes a fingerprint doc + the tree's HEAD
# identity + the tree's current activity fingerprint and returns verdicts. It has
# no handles, spawns nothing, writes nothing, never restarts/stops a worker, never
# touches a lane -- the callers (workbench route / CLI) own the reads, and they
# are read-only too. A stale worker is a WARNING, never a blocking failure: no
# verdict here feeds any refusal path.

VERDICT_OK = "ok"
VERDICT_CODE_STALE = "stale_code"
VERDICT_ACTIVITY_STALE = "stale_activities"
VERDICT_OFFLINE = "offline"
VERDICT_UNKNOWN = "unknown"


def _pid_alive(pid: Any) -> Optional[bool]:
    """pid liveness (signal 0 probe, POSIX); None = we cannot tell."""
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
        return True  # exists, owned by someone else
    except OSError:
        return None


def staleness_report(reg_doc: Optional[Dict[str, Any]],
                     reg_error: Optional[str],
                     head_sha: str,
                     tree_activity_fingerprint: str,
                     now_ms: int = 0,
                     max_age_ms: int = 0,
                     tree_activity_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Compare ONE running worker (its fingerprint doc) with the current tree.

    - head_sha empty (probe failed) -> unknown(code identity unavailable): the
      face degrades honestly, it never guesses "fresh".
    - doc sha != head_sha -> stale_code (the process serves code HEAD replaced).
    - doc activity_fingerprint != tree fingerprint: worker set a STRICT SUBSET of
      the tree's set -> stale_activities (the KI-227 shape: the tree gained an
      activity the worker cannot serve); a superset/diff that is not a subset is
      reported as mismatch with the same verdict only when the worker predates
      the file -- otherwise plain mismatch (still a warning, never a hard fail).
    - dead pid -> offline; absent/malformed doc -> unknown(<named reg_error>).

    The verdict ranks as a warning at the face layer; nothing here blocks work.
    """
    if reg_doc is None:
        return {"verdict": VERDICT_UNKNOWN,
                "why": "fingerprint unavailable: %s" % (reg_error or "absent")}
    alive = _pid_alive(reg_doc.get("pid"))
    if alive is False:
        return {"verdict": VERDICT_OFFLINE,
                "why": "worker pid %s is not alive" % reg_doc.get("pid")}
    doc_sha = str(reg_doc.get("code_fingerprint") or "")
    if not head_sha:
        return {"verdict": VERDICT_UNKNOWN,
                "why": "code identity of the tree unavailable (HEAD probe failed); "
                       "the worker's code fingerprint is %s%s" % (
                           doc_sha or "(empty)", " -- DIRTY tree" if reg_doc.get("code_dirty") else "")}
    if not doc_sha:
        return {"verdict": VERDICT_UNKNOWN,
                "why": "worker wrote an empty code fingerprint (v1 file or its "
                       "identity probe failed) -- cannot prove freshness"}
    if alive is None:
        return {"verdict": VERDICT_UNKNOWN,
                "why": "pid liveness unverifiable for pid %s" % reg_doc.get("pid")}
    doc_afp = str(reg_doc.get("activity_fingerprint") or "")
    if not doc_afp:
        return {"verdict": VERDICT_UNKNOWN,
                "why": "worker predates the activity fingerprint (v1 file) -- "
                       "restart to record one"}
    if doc_sha != head_sha:
        why = "worker code %s != HEAD %s" % (doc_sha[:12], head_sha[:12])
        if reg_doc.get("code_dirty"):
            why += " (worker tree was dirty at start)"
        return {"verdict": VERDICT_CODE_STALE, "why": why}
    if doc_afp != str(tree_activity_fingerprint or ""):
        acts = reg_doc.get("activities") if isinstance(reg_doc.get("activities"), list) else None
        if tree_activity_names and acts is not None:
            worker_set = set(str(n) for n in acts)
            tree_set = set(str(n) for n in tree_activity_names)
            if worker_set < tree_set:
                missing = ", ".join(sorted(tree_set - worker_set))
                return {"verdict": VERDICT_ACTIVITY_STALE,
                        "why": "worker activity set is a strict subset of the tree's "
                               "composition (%d vs %d); it cannot serve: %s -- restart "
                               "the worker or a workflow scheduling these dies with "
                               "NotFoundError" % (len(worker_set), len(tree_set), missing)}
            return {"verdict": VERDICT_ACTIVITY_STALE,
                    "why": "worker activity set differs from the tree's composition "
                           "(worker %d names, tree %d names; not a subset -- local "
                           "or reverted change?)" % (len(worker_set), len(tree_set))}
        return {"verdict": VERDICT_ACTIVITY_STALE,
                "why": "worker activity fingerprint %s... != tree %s... (names "
                       "unavailable for a subset check)" % (doc_afp[:12], str(tree_activity_fingerprint)[:12])}
    return {"verdict": VERDICT_OK, "why": "worker code and activity set match HEAD"}
