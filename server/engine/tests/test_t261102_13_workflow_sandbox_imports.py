# -*- coding: utf-8 -*-
"""t261102-17 — every module a workflow body imports must import clean AT WORKFLOW RUNTIME.

The measured defect (20261031 onward). `inspection_flow._lane_watchdog` does
`from inspection_lane_watchdog import machine_notes_from_meta` INSIDE the workflow method
body (server/engine/inspection_flow.py:2044). A workflow-task-time import runs while the
workflow sandbox is in RUNTIME mode, and in that mode temporalio forbids every `os.path`
call. `inspection_lane_watchdog` called `os.path.join` / `os.path.abspath` at MODULE
IMPORT time, so the import raised:

    RestrictedWorkflowAccessError: Cannot access os.path.join from inside a workflow
    (inspection_lane_watchdog.py:137, TMP_FIXTURE_DECLARATION_RELPATH)

The workflow task retried forever, so all seven inspection period tickets (t261031-10,
t261031-18, t261031-19, t261101-23, t261101-24, t261101-25, t261102-11) are stuck: every
snapshot query answers "Unable to query workflow due to Workflow Task in failed state".

Why the old guard (t261008-45, B family) missed it: that battery replays the sandbox over
the ALL_WORKFLOWS registry with the restriction context in IMPORT mode (is_runtime=False).
In import mode temporalio does not restrict `os` (`os` is `only_runtime=True` in the
default matcher), and a deferred import inside a workflow body never happens during that
replay. The guard was blind to the runtime face.

This battery adds the missing face: import the workflow-reachable modules with
is_runtime=True, exactly like a workflow task does.

Coverage:
  - the import site itself: sandbox import of inspection_flow (worker start), then the
    workflow-runtime import and call the body performs -> notes come out, no restriction;
  - the positive control: a synthetic module that does `os.path.join` at import IS refused
    under the same runtime restrictions (the pre-fix shape stays red, so the guard is not
    vacuous);
  - the family guard / sweep: for every workflow module in the public registry, every
    module imported from INSIDE workflow code is imported under runtime restrictions;
  - the lazy property of inspection_lane_watchdog: no path constant is computed at import,
    and the lazily computed values equal the values the old constants carried.

Family sweep (deferred imports inside workflow code, one level; delivered by t261102-17):

  module                    preloaded at worker start  import-time IO   verdict
  ------------------------  -------------------------  ---------------  ------------------
  activities                yes (workflows -> it)     os.environ.get   safe by preload
  shared                    yes (top-level import)    lazy paths       safe by preload
  develop_line              yes (dev_lane top-level)  os.environ.get   safe by preload
  light_lane                yes (dev_lane top-level)  none             safe
  template_topology         yes (dev_lane top-level)  none             safe
  develop_certify           no                       none             safe
  inspection_deadman        no                       none             safe
  inspection_inspect        no                       none             safe
  inspection_produce        no                       none             safe
  inspection_surface        no                       none             safe
  inspection_ticket_count   no                       none             safe
  inspection_lane_watchdog  no                       os.path.join     SAME DEFECT - fixed

"Preloaded" means the module is already in the sandbox module table when the workflow
starts (a workflow module imports it at module level), so the deferred import inside the
workflow body is a table lookup and no module body runs. The three modules whose import
does need `os.environ.get` are safe only because of that preload edge; cutting the edge
moves them into the checked set and this battery goes red - that is the point.

Out of scope, named:
  - `sandbar_ext_*` project-template modules live outside this repository and the worker
    passes them through (PROJECT_TEMPLATE_PASSTHROUGH_MODULES).
  - Deferred imports inside NON-workflow modules (activities.py, client.py, lane_reclaim.py
    and siblings) run in the activity worker, where the sandbox does not apply.
  - The `os.environ.get` calls at import in activities/shared/develop_line are latent, not
    live: they are preloaded. Splitting env reads out of activity-side modules is its own
    ticket, not this one.

All checks run in separated interpreters with a real temporalio sandbox importer: no
Temporal server, no network, no production writes.
"""

import json
import os
import subprocess
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
_VENV_PY = ENGINE / ".venv" / "bin" / "python"


def _run_probe(code: str, timeout: int = 180):
    env = dict(os.environ)
    env["ENGINE_DIR"] = str(ENGINE)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([str(_VENV_PY), "-c", code], capture_output=True, text=True,
                          env=env, timeout=timeout)


def _probe_json(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("PROBE_JSON "):
            return json.loads(line[len("PROBE_JSON "):])
    raise AssertionError("probe printed no PROBE_JSON line: %r" % stdout[-2000:])


# The workflow import site: what the worker does at startup, then what the workflow body
# does inside a task. Failure here is the exact 20261031 shape (RestrictedWorkflowAccessError
# naming os.path.join).
_IMPORT_SITE_PROBE = r'''
import importlib, json, os, sys
engine = os.environ["ENGINE_DIR"]
sys.path.insert(0, engine)
from temporalio.worker.workflow_sandbox import _importer

imp = _importer.Importer(_importer.SandboxRestrictions.default, _importer.RestrictionContext())
out = {}
with imp.applied():
    importlib.import_module("inspection_flow")      # what the worker imports at startup
    imp.restriction_context.is_runtime = True        # what a workflow task runs under
    from inspection_lane_watchdog import machine_notes_from_meta
    meta = {"unreadable": ["t-a"], "unreadable_transient": ["t-b"],
            "unreadable_permanent": ["t-c"], "enum_note": "capped at 5 tickets"}
    notes, extra = machine_notes_from_meta(meta, ["t-out-of-scope"])
    out["notes"] = notes
    out["findings"] = extra
    import inspection_lane_watchdog as wd
    out["watchdog_file"] = str(wd.__file__)
print("PROBE_JSON " + json.dumps(out))
'''

# Positive control: the PRE-FIX shape of inspection_lane_watchdog (a module doing
# os.path.join at import) must still be refused under runtime restrictions. If this test
# ever goes green-with-no-refusal, the guard has become vacuous.
_CONTROL_PROBE = r'''
import importlib, os, shutil, sys, tempfile
engine = os.environ["ENGINE_DIR"]
sys.path.insert(0, engine)
from temporalio.worker.workflow_sandbox import _importer

tmp = tempfile.mkdtemp(prefix="t261102-17-guard-")
try:
    with open(os.path.join(tmp, "t261102_17_import_io_probe.py"), "w", encoding="utf-8") as fh:
        fh.write("import os\nPROBE = os.path.join('integration', 'tools')\n")
    sys.path.insert(0, tmp)
    imp = _importer.Importer(_importer.SandboxRestrictions.default,
                             _importer.RestrictionContext())
    imp.restriction_context.is_runtime = True
    try:
        with imp.applied():
            importlib.import_module("t261102_17_import_io_probe")
    except Exception as exc:  # noqa: BLE001 - the refusal is the assertion
        print("CONTROL_RESTRICTED %s %s" % (type(exc).__name__, exc))
    else:
        print("CONTROL_NOT_RESTRICTED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
'''

# The family guard / sweep. Registry -> workflow modules -> every module imported from
# inside workflow code (AST, one level) -> import each one under runtime restrictions.
_SWEEP_PROBE = r'''
import ast, importlib, json, os, pathlib, sys
engine = pathlib.Path(os.environ["ENGINE_DIR"]).resolve()
sys.path.insert(0, str(engine))
import worker  # host import: read the public registry, no sandbox


def _engine_local(name):
    return (engine / (str(name).split(".")[0] + ".py")).exists()


def _deferred_local_imports(path):
    """Engine-local modules imported from INSIDE a function/class body of `path`."""
    found = set()

    def walk(node, inside):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)) and inside:
                names = ([a.name for a in child.names] if isinstance(child, ast.Import)
                         else [child.module or ""])
                for n in names:
                    if _engine_local(n):
                        found.add(str(n).split(".")[0])
            walk(child, inside or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))

    walk(ast.parse(path.read_text("utf-8")), False)
    return found


registry = sorted({getattr(c, "__module__", "")
                   for c in worker.ALL_WORKFLOWS + worker.ALL_WORKFLOWS_V2} - {""})
workflow_modules = [m for m in registry if (engine / (m + ".py")).exists()]
external = [m for m in registry if m not in workflow_modules]
targets = set()
for name in workflow_modules:
    targets |= _deferred_local_imports(engine / (name + ".py"))

from temporalio.worker.workflow_sandbox import _importer
imp = _importer.Importer(_importer.SandboxRestrictions.default, _importer.RestrictionContext())
out = {"workflow_modules": workflow_modules, "external_workflow_modules": external,
       "targets": sorted(targets), "import_time_failures": [], "preloaded": [],
       "runtime_failures": [], "checked": []}
with imp.applied():
    for name in workflow_modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - collected, judged by the caller
            out["import_time_failures"].append(
                "%s: %s: %s" % (name, type(exc).__name__, exc))
    out["preloaded"] = [t for t in sorted(targets) if t in sys.modules]
    imp.restriction_context.is_runtime = True
    for target in sorted(targets):
        if target in out["preloaded"]:
            continue
        out["checked"].append(target)
        try:
            importlib.import_module(target)
        except Exception as exc:  # noqa: BLE001 - collected, judged by the caller
            out["runtime_failures"].append("%s: %s: %s" % (target, type(exc).__name__, exc))
print("PROBE_JSON " + json.dumps(out))
'''

_SWEEP = {}


# The progression proof: run the workflow METHOD that failed, under runtime restrictions.
# `workflow.execute_activity` is replaced by a stub (no server, no Temporal write), so the
# method body executes for real: the deferred import, the converter, the section merge.
_LANE_WATCHDOG_BODY_PROBE = r'''
import asyncio, importlib, json, os, sys, types
engine = os.environ["ENGINE_DIR"]
sys.path.insert(0, engine)
from temporalio.worker.workflow_sandbox import _importer

RECEIPT = {"ok": True, "result": {
    "section": {"scan": "lane", "scanned": 3, "non_terminal": 2, "finding_count": 0,
                "by_leg": {}, "max_severity": "", "thresholds": {},
                "threshold_source": "default", "skipped": [], "suppressed": [],
                "human_gate": [], "stall": {}},
    "findings": [], "tmp_fixture": {},
    "meta": {"unreadable_transient": ["t261101-23"],
             "unreadable_permanent": ["t261031-10"],
             "enum_note": "capped at 5 tickets"}}}

imp = _importer.Importer(_importer.SandboxRestrictions.default,
                         _importer.RestrictionContext())
out = {}
with imp.applied():
    importlib.import_module("inspection_flow")     # worker start
    imp.restriction_context.is_runtime = True       # a workflow task
    import inspection_flow as flow
    import temporalio.workflow as wf
    calls = []

    async def fake_execute_activity(name, *args, **kwargs):
        calls.append(name)
        return RECEIPT

    wf.execute_activity = fake_execute_activity
    inp = types.SimpleNamespace(instance_id="sandbar")
    plan = {"watchdog": {"rerun_rounds": 3}}
    section, findings = asyncio.run(
        flow.InspectionPeriodicWorkflow._lane_watchdog(object(), inp, plan))
    out["calls"] = calls
    out["section"] = section
    out["findings"] = findings
print("PROBE_JSON " + json.dumps(out))
'''


def _sweep() -> dict:
    """Run the family sweep once per session (it imports the whole registry)."""
    if "data" not in _SWEEP:
        r = _run_probe(_SWEEP_PROBE)
        assert r.returncode == 0, r.stderr[-4000:]
        _SWEEP["data"] = _probe_json(r.stdout)
    return _SWEEP["data"]


def test_workflow_body_import_site_runs_at_workflow_runtime():
    """The exact 20261031 import site: sandbox import of the module must now succeed."""
    r = _run_probe(_IMPORT_SITE_PROBE)
    assert r.returncode == 0, r.stderr[-4000:]
    data = _probe_json(r.stdout)
    # Fail closed if the probe resolved another tree (a lane must test its own engine).
    assert Path(data["watchdog_file"]).resolve().is_relative_to(ENGINE.resolve())
    # The converter still converts (same notes the activity receipt produces).
    kinds = [n["kind"] for n in data["notes"]]
    assert kinds == ["unreadable", "unreadable-transient", "skipped", "truncated"]
    assert data["notes"][0]["count"] == 1
    assert data["findings"] == []


def test_lane_watchdog_body_progresses_under_workflow_runtime():
    """The failing method runs to the end: import, converter, section merge (no server)."""
    r = _run_probe(_LANE_WATCHDOG_BODY_PROBE)
    assert r.returncode == 0, r.stderr[-4000:]
    data = _probe_json(r.stdout)
    assert data["calls"] == ["run_inspection_lane_watchdog"]
    assert data["findings"] == []
    section = data["section"]
    kinds = [n["kind"] for n in section["machine_notes"]]
    assert kinds == ["unreadable", "unreadable-transient", "truncated"]
    assert section["machine_notes"][0]["detail"] == ["t261031-10"]
    # The sweep's own section fields kept their shapes (no silent re-shaping).
    assert section["scanned"] == 3 and section["threshold_source"] == "default"


def test_guard_refuses_import_io_under_runtime_restrictions():
    """Positive control: the pre-fix module shape is still refused (guard is not vacuous)."""
    r = _run_probe(_CONTROL_PROBE)
    assert r.returncode == 0, r.stderr[-4000:]
    assert "CONTROL_RESTRICTED RestrictedWorkflowAccessError" in r.stdout, r.stdout[-2000:]
    assert "os.path.join" in r.stdout
    assert "CONTROL_NOT_RESTRICTED" not in r.stdout


def test_workflow_reachable_modules_import_clean_at_runtime():
    """Family guard: every module imported from inside workflow code passes the runtime face."""
    data = _sweep()
    assert data["import_time_failures"] == []
    assert data["runtime_failures"] == []
    # The sweep must classify every deferred target: checked now or preloaded at startup.
    assert sorted(set(data["checked"]) | set(data["preloaded"])) == data["targets"]
    # The defect module is NOT preloaded, so the guard really imports its body at runtime.
    assert "inspection_lane_watchdog" in data["targets"]
    assert "inspection_lane_watchdog" in data["checked"]


def test_deferred_import_of_the_inspection_workflow_is_covered():
    """The guard derives today's inspection_flow imports from the real source (not a list)."""
    data = _sweep()
    assert "inspection_flow" in data["workflow_modules"]
    for name in ("inspection_lane_watchdog", "inspection_deadman", "inspection_inspect",
                 "inspection_produce", "inspection_surface", "inspection_ticket_count"):
        assert name in data["targets"]


def test_watchdog_import_computes_no_paths_eagerly():
    """No path constant may be computed at import (the root cause of the defect)."""
    import inspection_lane_watchdog as wd
    module_dict = vars(wd)
    for retired in ("TMP_FIXTURE_DECLARATION", "TMP_FIXTURE_DECLARATION_PATH",
                    "TMP_FIXTURE_PREFIXES", "TMP_FIXTURE_OWNERS"):
        assert retired not in module_dict, (
            "%s is computed at import time again: the workflow sandbox forbids that"
            % retired)


def test_lazy_faces_carry_the_old_values():
    """The lazily answered faces equal what the old import-time constants carried."""
    import inspection_lane_watchdog as wd
    module_file = Path(wd.__file__).resolve()
    # The old constant was dirname(dirname(dirname(abspath(__file__)))) + relpath.
    repo_root = module_file.parent.parent.parent          # <repo>/server/engine/<file>
    old_constant = os.path.join(
        str(repo_root), "integration", "tools", "tmp_fixture_families.json")
    assert wd.tmp_fixture_declaration_path() == old_constant
    assert wd.TMP_FIXTURE_DECLARATION_PATH == old_constant
    decl = wd.TMP_FIXTURE_DECLARATION
    assert decl["status"] == "loaded", decl.get("detail")
    assert Path(decl["path"]) == Path(old_constant)
    assert tuple(wd.TMP_FIXTURE_PREFIXES) == tuple(decl["prefixes"])
    assert set(wd.TMP_FIXTURE_OWNERS) == {f["prefix"] for f in decl["families"]
                                         if f.get("producer")}
    # One read per process: the water level cannot change halfway through a period.
    assert wd.tmp_fixture_declaration() is wd.tmp_fixture_declaration()
    assert wd.TMP_FIXTURE_DECLARATION is wd.tmp_fixture_declaration()
