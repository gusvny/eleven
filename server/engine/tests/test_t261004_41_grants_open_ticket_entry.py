# -*- coding: utf-8 -*-
"""t261004-41 executor-grants-write entry -- open-ticket keys travel -- unit test.

t261004-41 rework: these cases first lived appended inside
test_t261004_18_grants_write_entry.py, but that file is pinned code/test-name
verbatim by the t261004-28 carrier guard (its author evidence copy is frozen
under integration/t261004-25/evidence/). Growing a pinned carrier file reds the
guard on every lane run, so the new coverage lives in its own file and the
carrier stays byte-faithful to its author source.

Coverage:
- positive bar: args carrying open_ticket_epics / open_ticket_cap reach
  save_declaration verbatim and land on disk;
- absent keys pass None (inherit the on-disk value — a partial edit never wipes);
- an explicit [] is a real clear-all (absent and empty must stay distinct);
- malformed values ("all" / boolean cap) degrade to absent = inherit, never
  crash the entry, never smuggle a bad type into save_declaration.
Zero Temporal / zero network / zero git; the declaration root is injected into
a temp dir via SANDBAR_PROJECTS_DIR (same fixture discipline as the t261004-18
entry test).
"""
import asyncio
import json

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


def test_open_ticket_fields_round_trip(projects_root):
    res = _call(key="alpha", by="host", grants={"open-ticket": True},
                open_ticket_epics=["epic-a", "epic-b"], open_ticket_cap=5)
    assert res["saved"] is True
    decl = json.loads((projects_root / "alpha" / eg.DECL_FILE).read_text(encoding="utf-8"))
    assert decl["open_ticket_epics"] == ["epic-a", "epic-b"]
    assert decl["open_ticket_cap"] == 5


def test_open_ticket_fields_absent_inherit_on_disk_value(projects_root):
    eg.save_declaration("alpha", {"sign": True}, "host", 1,
                        open_ticket_epics=["epic-a"], open_ticket_cap=7)
    res = _call(key="alpha", by="host", grants={"rerun": True})
    assert res["saved"] is True
    decl = json.loads((projects_root / "alpha" / eg.DECL_FILE).read_text(encoding="utf-8"))
    # The entry must pass None (not []) for the absent keys, or the list/cap get wiped.
    assert decl["open_ticket_epics"] == ["epic-a"]
    assert decl["open_ticket_cap"] == 7


def test_open_ticket_empty_list_is_an_explicit_clear(projects_root):
    eg.save_declaration("alpha", {"sign": True}, "host", 1,
                        open_ticket_epics=["epic-a"], open_ticket_cap=7)
    res = _call(key="alpha", by="host", grants={"rerun": True}, open_ticket_epics=[])
    assert res["saved"] is True
    decl = json.loads((projects_root / "alpha" / eg.DECL_FILE).read_text(encoding="utf-8"))
    assert decl["open_ticket_epics"] == []


def test_open_ticket_malformed_values_dropped_to_inherit(projects_root):
    # External-input discipline: a malformed value must degrade to "absent = inherit",
    # never crash the entry and never smuggle a bad type into save_declaration.
    eg.save_declaration("alpha", {"sign": True}, "host", 1,
                        open_ticket_epics=["epic-a"], open_ticket_cap=7)
    res = _call(key="alpha", by="host", grants={"rerun": True},
                open_ticket_epics="all", open_ticket_cap=True)
    assert res["saved"] is True
    decl = json.loads((projects_root / "alpha" / eg.DECL_FILE).read_text(encoding="utf-8"))
    assert decl["open_ticket_epics"] == ["epic-a"]
    assert decl["open_ticket_cap"] == 7
