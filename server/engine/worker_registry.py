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

import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

FINGERPRINT_ENV = "SANDBAR_WORKER_REGISTRY_FINGERPRINT"
FINGERPRINT_VERSION = 1
POC_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FINGERPRINT_PATH = os.path.join(POC_DIR, "data", "worker-registry.json")
#: The class this face polices (the named-refusal target of t261004-44).
DELIVERY_WORKFLOW_CLASS = "ExecutorDeliveryWorkflow"


def fingerprint_path(env: Optional[Dict[str, str]] = None) -> str:
    """Fingerprint file path (env injection > engine data dir). Tests point the env
    into a temp directory."""
    env = env if env is not None else os.environ
    return str(env.get(FINGERPRINT_ENV) or DEFAULT_FINGERPRINT_PATH)


def write_fingerprint(path: str, workflow_names: List[str],
                      pid: int, now_ms: int,
                      code_fingerprint: str = "") -> Dict[str, Any]:
    """Atomic write (tmp+rename, engine-side disk discipline); shape::

        {"version": 1, "pid": int, "started_at_ms": int,
         "code_fingerprint": str, "registered": [class name, ...]}

    Returns the written doc (caller logs it). Write failures are swallowed loudly by
    the caller -- a missing fingerprint makes deliver degrade to the bounded wait,
    never blocks worker startup."""
    doc: Dict[str, Any] = {
        "version": FINGERPRINT_VERSION,
        "pid": int(pid),
        "started_at_ms": int(now_ms),
        "code_fingerprint": str(code_fingerprint),
        "registered": [str(n) for n in workflow_names],
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
    if not isinstance(doc, dict) or doc.get("version") != FINGERPRINT_VERSION \
            or not isinstance(doc.get("registered"), list) \
            or any(not isinstance(n, str) for n in doc.get("registered", [])):
        return None, "malformed: fingerprint shape is wrong (need {version:1, registered: [str,...]})"
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
