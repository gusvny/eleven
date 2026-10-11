#!/usr/bin/env python3
"""t261011-17 — the worker registration surface is complete, judged at the system
level (grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
3099).

User need (ticket t261011-17): lane_head_sha / land_to_line / certification_wait
were decorated @activity.defn and executed by the develop-buffer landing path but
never registered on the worker, so the path was never servable end to end and
every green round silently failed to mint shared.green_run_face. The fix is
registration plus a guard; this scenario locks the SYSTEM face of both:

  A. the develop-buffer landing path is registered: lane_head_sha,
     land_to_line and certification_wait are members of the COMPOSED worker
     registration table (worker.compose_worker_activities()), judged by the
     same registered-name rule the worker uses at start (activity_registered_name);
  B. no production @activity.defn under server/engine (tests excluded) is left
     outside the composed table, except the NAMED selfcheck-stub exemptions
     with reasons — the same promise the ticket-level guard makes, asserted
     here on the real tree from the outside;
  C. the @workflow.defn surface is complete against the declared workflow
     lists (ALL_WORKFLOWS + ALL_WORKFLOWS_V2) — the surface is complete today;
     this leg keeps it that way.

Intent split: the guard MECHANICS (negative control, exemption-reason shape,
synthetic collisions) belong to the developer's L1 guard test; this scenario
only judges the real tree's current registration state through the public
composition entry. Pre-implement tree red = the named TDD signal; green
required at the integration gate/merge.

Engine tree or temporalio unimportable = ENV_FAIL exit 2.
"""
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(ROOT, "server", "engine")
if not os.path.isdir(ENGINE):
    print("ENV_FAIL: engine tree missing: %s" % ENGINE)
    sys.exit(2)
sys.path.insert(0, ENGINE)

LANDEING_PATH_NAMES = ["lane_head_sha", "land_to_line", "certification_wait"]

# Named exemption list (ticket spec item 2): (module basename, name prefix or
# exact name, reason). The only legitimate class is self-check stubs. The
# vestigial inspection_period_identity decorator was dropped instead of
# exempted (t261011-17 rework): a production module is not a selfcheck stub.
ACTIVITY_EXEMPTIONS = [
    ("selfcheck_ki061_wake_reset.py", "stub",
     "self-check stub activities, never executed by a production worker"),
    ("selfcheck_t260916_19_join_escape.py", "stub",
     "self-check stub activities, never executed by a production worker"),
    ("selfcheck_graceful_stop_probe.py", "guarded_probe",
     "self-check probe activity, run by the graceful-stop probe only"),
    ("selfcheck_worker_graceful_stop.py", "guarded_probe",
     "self-check probe activity, run by the worker graceful-stop drill only"),
]
# Named workflow exemptions - the self-check probe class only (mirrors the
# developer guard test WORKFLOW_EXEMPT so both guards assert one promise).
WORKFLOW_EXEMPTIONS = [
    ("selfcheck_graceful_stop_probe.py", "ProbeWorkflow",
     "self-check probe workflow, run by the graceful-stop probe only"),
    ("selfcheck_worker_graceful_stop.py", "ProbeWorkflow",
     "self-check probe workflow, imported by the worker graceful-stop drill only"),
]

SCAN_SKIP_DIRS = {"tests", "__pycache__", "fixtures", "bin", ".venv", "node_modules"}


def _fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def _engine_py_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ENGINE):
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _decorated_defs(tree, mod_name, decorator_tail, kind):
    """Names of defs/classes whose decorator is activity.defn / workflow.defn."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                d = dec
                # unwrap @activity.defn / @workflow.defn (plain attribute chains)
                parts = []
                while isinstance(d, ast.Attribute):
                    parts.append(d.attr)
                    d = d.value
                if isinstance(d, ast.Name):
                    parts.append(d.id)
                parts.reverse()
                if len(parts) == 2 and parts[0] == decorator_tail[0] \
                        and parts[1] == decorator_tail[1]:
                    hits.append((mod_name, node.name))
                    break
    return hits


def _activity_defn_names():
    out = []
    for path in _engine_py_files():
        mod = os.path.relpath(path, ENGINE)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as e:
            _fail("engine module does not parse: %s (%s)" % (mod, e))
        out.extend(_decorated_defs(tree, os.path.basename(mod), ("activity", "defn"), "def"))
    return out


def _workflow_defn_names():
    out = []
    for path in _engine_py_files():
        mod = os.path.relpath(path, ENGINE)
        tree = ast.parse(open(path, encoding="utf-8").read())
        out.extend(_decorated_defs(tree, os.path.basename(mod), ("workflow", "defn"), "cls"))
    return out


def _exempt(mod, name, exemptions):
    for emod, ename, _reason in exemptions:
        if mod == emod and (ename.endswith("*") and name.startswith(ename[:-1])
                            or name == ename):
            return True
    return False


def main():
    try:
        import worker  # noqa: E402
        import workflows  # noqa: E402
        import workflows_v2  # noqa: E402
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: engine registration surface unimportable: %s: %s"
              % (type(e).__name__, e))
        sys.exit(2)

    composed = worker.compose_worker_activities()
    table = {worker.activity_registered_name(a) for a in composed}

    # ---- A: the develop-buffer landing path is registered on the composed table
    missing = [n for n in LANDEING_PATH_NAMES if n not in table]
    if missing:
        _fail("develop-buffer landing activities not registered on the composed "
              "worker table: %s (the landing path is not servable end to end and "
              "the green-run face can never mint — ticket t261011-17 root cause)"
              % ", ".join(missing))
    print("PASS A: composed worker table carries %s" % ", ".join(LANDEING_PATH_NAMES))

    # ---- B: no production @activity.defn outside the composed table
    viol = []
    for mod, name in _activity_defn_names():
        if name in table or _exempt(mod, name, ACTIVITY_EXEMPTIONS):
            continue
        viol.append("%s:%s" % (mod, name))
    if viol:
        _fail("unregistered production @activity.defn outside the composed table "
              "and outside the named exemption list: %s" % ", ".join(sorted(viol)))
    print("PASS B: every @activity.defn under server/engine is composed-registered "
          "or on the named exemption list")

    # ---- C: the @workflow.defn surface is complete against the declared lists
    declared = {getattr(c, "__name__", repr(c))
                for c in (workflows.ALL_WORKFLOWS + workflows_v2.ALL_WORKFLOWS_V2)}
    wviol = []
    for mod, name in _workflow_defn_names():
        if name in declared or _exempt(mod, name, WORKFLOW_EXEMPTIONS):
            continue
        wviol.append("%s:%s" % (mod, name))
    if wviol:
        _fail("@workflow.defn outside ALL_WORKFLOWS+ALL_WORKFLOWS_V2 and outside "
              "the (empty) exemption list: %s" % ", ".join(sorted(wviol)))
    print("PASS C: every @workflow.defn is on the declared workflow lists")

    print("PASS t261011-17-registration-surface: registration surface complete "
          "(activities=%d composed, defns scanned with %d named exemptions)"
          % (len(table), len(ACTIVITY_EXEMPTIONS)))
    sys.exit(0)


if __name__ == "__main__":
    main()
