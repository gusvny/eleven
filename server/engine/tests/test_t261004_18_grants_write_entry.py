# -*- coding: utf-8 -*-
"""t261004-18 (KI-193) executor-grants-write engine-side entry -- unit test.

Coverage (ticket requirements 3/4, item by item):
- positive bar: a host write (by=host) lands via cmd_executor_grants_write and
  the audit row carries source (surface/transport/guarded into the ledger as-is);
- meta-permission lock: the same entry called through the executor identity
  channel (SANDBAR_CALLER_IDENTITY_SRC=cwd) is refused, the on-disk declaration
  does not exist / is byte-identical, and one refuse audit row (with source) lands;
- refusals leave a trace too: missing by / grants not an object -> saved:false +
  refuse audit rows;
- validation refusal passthrough: an unknown op key -> the engine's validate
  refusal returned verbatim;
- malformed args with no key / missing grants: structured refusal, never a half
  write.
Zero Temporal / zero network / zero git throughout; the declaration root is
injected into a temp dir via SANDBAR_PROJECTS_DIR.

Landing history: first written in implement gen0, then wiped five times by the
main-merge/settle window (9a64edc, cb89f07, 45a437a, 59bc4da, 77b6cbc -- one
loss each); this version is the implement gen5 fifth rebuild. Root cause found:
the settle worker only commits tracked files with changes; untracked new files
are dropped by the deterministic checkout. The only way to stop the loss: the
lane's next settle commit must
`git add server/engine/tests/test_t261004_18_grants_write_entry.py`.

Translation note (t261004-28 carrier, host L15 ruling): comments and docstrings
are translated to English; the assertions below match the engine's English
refusal copy verbatim (t261004-36) and carry no copy-language markers.
"""
import asyncio
import json
import os

import pytest

import client as cl  # noqa: E402
import executor_grants as eg  # noqa: E402


@pytest.fixture()
def projects_root(monkeypatch, tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    # Clean identity channel (default env: not the executor channel).
    monkeypatch.delenv("SANDBAR_CALLER_IDENTITY_SRC", raising=False)
    monkeypatch.delenv("SANDBAR_CALLER_SURFACE", raising=False)
    return root


def _call(**args):
    return asyncio.run(cl.cmd_executor_grants_write(args))


def _audit(root, key):
    path = root / key / eg.AUDIT_FILE
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_host_write_saves_and_audits_source(projects_root):
    res = _call(key="alpha", by="host", grants={"sign": True},
                source={"surface": "panel-api", "transport": "http", "guarded": True})
    assert res["saved"] is True
    decl = json.loads((projects_root / "alpha" / eg.DECL_FILE).read_text(encoding="utf-8"))
    assert decl["grants"] == {"sign": True}
    rows = _audit(projects_root, "alpha")
    assert len(rows) == 1 and rows[0]["action"] == "grant-change"
    assert rows[0]["source"] == {"surface": "panel-api", "transport": "http", "guarded": True}


def test_executor_channel_refused_with_refuse_audit(projects_root, monkeypatch):
    monkeypatch.setenv("SANDBAR_CALLER_IDENTITY_SRC", eg.EXECUTOR_CHANNEL)
    res = _call(key="alpha", by="executor", grants={"open-ticket": True},
                source={"surface": "executor-cli"})
    assert res["saved"] is False and "meta-permission lock" in res["reason"]
    assert not (projects_root / "alpha" / eg.DECL_FILE).exists()
    rows = _audit(projects_root, "alpha")
    assert len(rows) == 1 and rows[0]["action"] == "refuse" and rows[0]["op"] == eg.META_OP
    assert rows[0]["source"] == {"surface": "executor-cli"}


def test_named_session_channel_refused(projects_root, monkeypatch):
    # Declaration names the channel: the caller session id is named -> executor
    # identity -> locked (holds even before the declaration read: this case first
    # writes a declaration with the naming, then calls the entry under that same
    # session identity).
    eg.save_declaration("beta", {"sign": True}, "host", 1, executor_sessions=["sess-1"])
    before = (projects_root / "beta" / eg.DECL_FILE).read_bytes()
    monkeypatch.setenv("SANDBAR_CALLER_IDENTITY_SRC", "arg")
    monkeypatch.setenv("DSH_SESSION_ID", "sess-1")
    res = _call(key="beta", by="executor", grants={"sign": True, "rerun": True})
    assert res["saved"] is False
    assert (projects_root / "beta" / eg.DECL_FILE).read_bytes() == before


def test_missing_by_and_bad_grants_refused_and_audited(projects_root):
    res = _call(key="alpha", by="", grants={"sign": True}, source={"surface": "probe"})
    assert res["saved"] is False and "by" in res["reason"]
    res2 = _call(key="alpha", by="host", grants="not-a-dict", source={"surface": "probe"})
    assert res2["saved"] is False and "grants" in res2["reason"]
    assert not (projects_root / "alpha" / eg.DECL_FILE).exists()
    rows = _audit(projects_root, "alpha")
    assert len(rows) == 2 and all(r["action"] == "refuse" for r in rows)
    assert all(r["source"] == {"surface": "probe"} for r in rows)


def test_unknown_op_key_passes_through_validation_refusal(projects_root):
    res = _call(key="alpha", by="host", grants={"fly": True}, source={"surface": "probe"})
    assert res["saved"] is False and "fly" in res["reason"]
    assert not (projects_root / "alpha" / eg.DECL_FILE).exists()


def test_missing_key_structured_refusal(projects_root):
    res = _call(key="", by="host", grants={})
    assert res["saved"] is False and "key" in res["reason"]

