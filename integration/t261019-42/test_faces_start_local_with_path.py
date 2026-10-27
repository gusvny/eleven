#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Source lock: both idle-worker faces pin the dev server CLI (t261028-07).

KI-380: the faces called temporalio ``WorkflowEnvironment.start_local()`` with
no binary path, so the SDK downloaded the Temporal CLI and a network condition
became a content red that froze the line. The fix hands start_local
``dev_server_existing_path=<provisioned CLI>``; this file is the LOCK that keeps
a future edit from silently reintroducing the download.

What is asserted (source level, both faces):
  - every ``start_local`` call carries ``dev_server_existing_path`` with a
    non-constant, non-empty value;
  - the face calls the shared provisioning seam
    (``provision_dev_server_cli``), so the path comes from the one resolution
    point in ``lib_temporal_cli``;
  - the checker has teeth: a synthetic bare ``start_local()``, a constant
    ``None`` path, and a face that skips provisioning are all named findings
    (a lock that cannot fail proves nothing).
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lib_temporal_cli as cli  # noqa: E402

FACES = (
    "sc_t261019_42_idle_worker_fast_turnover.py",
    "face_b_busy_worker_driver.py",
)

#: A face shaped like the fixed one (the positive control of the checker).
COMPLIANT = '''
import asyncio


def provision_dev_server_cli():
    return "/repo/server/engine/bin/temporal"


async def main():
    from temporalio.testing import WorkflowEnvironment
    cli_path = provision_dev_server_cli()
    env_handle = await WorkflowEnvironment.start_local(
        port=1234, dev_server_existing_path=cli_path)
    async with env_handle as env:
        return env
'''


def _read(name):
    return (HERE / name).read_text(encoding="utf-8")


def _call_name(func):
    """Last attribute/name of a call target (test-local, no private import)."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


# ---------- the lock over the two real faces ----------


def test_scenario_face_pins_the_provisioned_cli():
    findings = cli.check_face_source(_read(FACES[0]), FACES[0])
    assert findings == [], findings


def test_face_b_driver_pins_the_provisioned_cli():
    findings = cli.check_face_source(_read(FACES[1]), FACES[1])
    assert findings == [], findings


def test_both_faces_import_the_shared_resolution_point():
    """The path must come from lib_temporal_cli, not a re-invented lookup."""
    for name in FACES:
        tree = ast.parse(_read(name), filename=name)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        assert "lib_temporal_cli" in modules, (name, sorted(modules))


def test_no_face_passes_a_constant_path_or_skips_provisioning():
    """Read back from the parsed source, not from the checker's own report."""
    for name in FACES:
        tree = ast.parse(_read(name), filename=name)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and _call_name(n.func) == "start_local"]
        assert calls, "%s has no start_local call to lock?" % name
        for call in calls:
            pinned = [kw for kw in call.keywords
                      if kw.arg == cli.EXISTING_PATH_KW]
            assert pinned, "%s:%d start_local without %s" % (
                name, call.lineno, cli.EXISTING_PATH_KW)
            assert not isinstance(pinned[0].value, ast.Constant), (
                "%s:%d pins a constant path %r" % (
                    name, call.lineno, getattr(pinned[0].value, "value", None)))


# ---------- the checker's teeth (fail-closed discipline) ----------


def test_compliant_face_has_no_findings():
    assert cli.check_face_source(COMPLIANT, "compliant.py") == []


def test_bare_start_local_is_named():
    """The KI-380 shape itself: a bare call must be a finding, never a pass."""
    src = "import asyncio\n" + COMPLIANT.replace(
        "port=1234, dev_server_existing_path=cli_path", "port=1234")
    findings = cli.check_face_source(src, "bare.py")
    assert any(cli.EXISTING_PATH_KW in f for f in findings), findings
    assert any("KI-380" in f for f in findings), findings


def test_constant_none_path_is_named():
    src = COMPLIANT.replace("dev_server_existing_path=cli_path",
                            "dev_server_existing_path=None")
    findings = cli.check_face_source(src, "none_path.py")
    assert any(cli.EXISTING_PATH_KW in f for f in findings), findings


def test_empty_string_path_is_named():
    src = COMPLIANT.replace("dev_server_existing_path=cli_path",
                            "dev_server_existing_path='  '")
    findings = cli.check_face_source(src, "blank_path.py")
    assert any(cli.EXISTING_PATH_KW in f for f in findings), findings


def test_face_that_skips_provisioning_is_named():
    src = COMPLIANT.replace("cli_path = provision_dev_server_cli()",
                            "cli_path = '/tmp/temporal'")
    findings = cli.check_face_source(src, "no_provision.py")
    assert any(cli.PROVISION_FUNC in f for f in findings), findings


def test_unparsable_source_is_a_finding_not_a_pass():
    """Fail-closed: a lock that cannot read the face proves nothing."""
    findings = cli.check_face_source("def broken(:\n", "broken.py")
    assert findings and "fail-closed" in findings[0], findings
