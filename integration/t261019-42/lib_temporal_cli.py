#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The provisioned Temporal CLI for both idle-worker faces (t261028-07, KI-380).

Incident (KI-380): both faces of scenario t261019-42 called temporalio
``WorkflowEnvironment.start_local()`` with no binary path. temporalio then
fetches the Temporal CLI from https://temporal.download/cli/default. When that
download is slow or refused, start_local raises
``RuntimeError("Failed starting Temporal dev server: error sending request for
url (...)")``, the runner books it as an ordinary assertion red, and a network
condition reddened a whole line round (732 ran / 1 failed / 18 env-failed) and
froze develop-buffer.

Contract (ticket t261028-07 spec points 1 and 2):

  - ``$SANDBAR_TEMPORAL_BIN`` first. An explicit pointer WINS and is never
    silently bypassed: a pointer naming a nonexistent path is a named miss.
  - Else the repo copy ``<repo>/server/engine/bin/temporal``, resolved through
    the suite's one asset resolver (``integration/bench.py``
    ``resolve_temporal_bin``), which also carries the lane-worktree ->
    main-tree fallback the rest of the suite relies on.
  - Nothing obtainable = ``TemporalCliMissing`` naming the env key and every
    path looked at. The faces turn that into ENV_FAIL exit 2 (the suite
    convention in ``integration/lib_env.py``), never an assertion red.
  - The returned path is what a face hands to ``start_local`` as
    ``dev_server_existing_path``; the SDK documents that no download is
    attempted once the path is present, so no face code path can fetch a CLI.

``check_face_source`` is the source lock (spec point 3): a future edit that
reintroduces a bare ``start_local()`` call, or drops the provisioning seam, is
a finding. Tests:
``integration/t261019-42/test_faces_start_local_with_path.py`` (the lock) and
``integration/t261028-04/test_idle_worker_cli_provisioning.py`` (resolution and
the ENV_FAIL miss).
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

INTEG_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = INTEG_DIR.parent

#: The one env key that points the suite at a specific CLI binary.
TEMPORAL_BIN_ENV = "SANDBAR_TEMPORAL_BIN"

#: The repo-provisioned copy (gitignored; provisioned per checkout).
BUNDLED_CLI = REPO_ROOT / "server" / "engine" / "bin" / "temporal"

#: The provisioning seam every face must call (the source lock looks for it).
PROVISION_FUNC = "provision_dev_server_cli"

#: The start_local keyword that turns the download path off.
EXISTING_PATH_KW = "dev_server_existing_path"


class TemporalCliMissing(RuntimeError):
    """No provisioned Temporal CLI: an ENVIRONMENT red (ENV_FAIL exit 2).

    ``tried`` holds every path the resolution looked at, ``env_key`` the key it
    honoured or found unset, and ``detail`` names exactly which check failed —
    a miss must be attributable without a re-run.
    """

    def __init__(self, env_key, tried, detail):
        self.env_key = str(env_key)
        self.tried = tuple(str(p) for p in tried)
        self.detail = str(detail)
        super(TemporalCliMissing, self).__init__(self.reason)

    @property
    def reason(self):
        looked = ", ".join(self.tried) if self.tried else "(no path probed)"
        return ("no provisioned Temporal CLI (%s); looked at: %s. The idle-worker "
                "faces never download a Temporal CLI (KI-380): provide an "
                "existing binary with %s=<path> or provision the bundled copy. "
                "This is an environment failure (ENV_FAIL exit 2), not a red "
                "of the behaviour under test."
                % (self.detail, looked, self.env_key))


def _default_bundled_resolver():
    """The suite's one resolution point for the bundled copy: integration/bench.py.

    bench.resolve_temporal_bin honours SANDBAR_TEMPORAL_BIN itself; we call it
    only after our own pointer check, and its lane -> main-tree fallback is what
    makes a gitignored binary resolvable from a lane worktree.

    The integration directory joins sys.path only for the import (the module
    identity stays the shared one, so a caller's monkeypatch on ``bench`` is
    what runs), and leaves again so a face process never keeps suite modules
    ahead of the engine's own.
    """
    import importlib  # noqa: PLC0415

    if str(INTEG_DIR) in sys.path:
        return str(importlib.import_module("bench").resolve_temporal_bin())
    sys.path.insert(0, str(INTEG_DIR))
    try:
        bench = importlib.import_module("bench")
        return str(bench.resolve_temporal_bin())
    finally:
        try:
            sys.path.remove(str(INTEG_DIR))
        except ValueError:
            pass


def resolve_temporal_cli(env=None, bundled_resolver=None):
    """Return the path of an EXISTING Temporal CLI, or raise TemporalCliMissing.

    ``env`` and ``bundled_resolver`` are injectable seams for the unit battery
    (the default resolver is the suite's single resolution point); production
    callers pass nothing.
    """
    env = os.environ if env is None else env
    resolver = _default_bundled_resolver if bundled_resolver is None else bundled_resolver

    pointer = str(env.get(TEMPORAL_BIN_ENV) or "").strip()
    if pointer:
        candidate = Path(pointer)
        detail = ("%s=%s %s"
                  % (TEMPORAL_BIN_ENV, pointer,
                     "does not exist" if not candidate.exists()
                     else "is not a file"))
        if candidate.is_file():
            return pointer
        # An explicit pointer is never silently bypassed: refuse by name.
        raise TemporalCliMissing(TEMPORAL_BIN_ENV,
                                 (pointer, str(BUNDLED_CLI)), detail)

    try:
        found = str(resolver())
    except Exception as exc:  # noqa: BLE001 - any unreadable asset face is a miss
        raise TemporalCliMissing(
            TEMPORAL_BIN_ENV, (str(BUNDLED_CLI),),
            "%s is unset and the bundled lookup failed (%s: %s)"
            % (TEMPORAL_BIN_ENV, type(exc).__name__, exc))
    if not found or not Path(found).is_file():
        raise TemporalCliMissing(
            TEMPORAL_BIN_ENV, (str(BUNDLED_CLI),),
            "%s is unset and the bundled lookup returned %r, which is not a file"
            % (TEMPORAL_BIN_ENV, found))
    return found


# ---- source lock -----------------------------------------------------------
# A source-level assertion, not a comment: the point is that a future edit
# cannot silently reintroduce the download (KI-380). Pure text in, findings out,
# so the lock itself is unit-tested (including its teeth).


def _called_name(func):
    """The last attribute/name of a call target: ``a.b.start_local`` -> ``start_local``."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _called_names(tree):
    return {_called_name(node.func) for node in ast.walk(tree)
            if isinstance(node, ast.Call)}


def check_face_source(source, filename="<source>"):
    """Findings (empty = locked) for one face source text.

    Two things must hold:
      1. every ``start_local`` call pins ``dev_server_existing_path`` with a
         non-constant, non-empty value (a bare call is the download);
      2. the face calls the shared provisioning seam (PROVISION_FUNC), so the
         path comes from the one resolution point and not from a re-invention.
    A source that cannot be parsed is fail-closed: that is a finding, never a
    silent pass (a lock that proves nothing is worse than no lock).
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return ["%s: unparsable source (%s: %s) - the source lock is fail-closed"
                % (filename, type(exc).__name__, exc)]

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _called_name(node.func) != "start_local":
            continue
        pinned = [kw for kw in node.keywords if kw.arg == EXISTING_PATH_KW]
        if not pinned:
            findings.append(
                "%s:%d: start_local() without %s=... - temporalio would download "
                "the CLI from temporal.download (KI-380)"
                % (filename, node.lineno, EXISTING_PATH_KW))
            continue
        value = pinned[0].value
        if isinstance(value, ast.Constant):
            text = "" if value.value is None else str(value.value).strip()
            if not text:
                findings.append(
                    "%s:%d: start_local(%s=%r) pins no usable path - the value "
                    "must be the resolved CLI"
                    % (filename, node.lineno, EXISTING_PATH_KW, value.value))

    if PROVISION_FUNC not in _called_names(tree):
        findings.append(
            "%s: the face never calls %s() - the CLI must come from the shared "
            "resolution point in lib_temporal_cli (KI-380)" % (filename, PROVISION_FUNC))
    return findings
