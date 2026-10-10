"""t261009-76 — the develop-buffer opt-in is reachable from the REAL intake
(unit tests; zero Temporal server / zero model / zero network).

Contract under test (ticket spec (1)-(4), review conditions C1/C3):
  (1) a create payload naming lane_version + develop_line_id is carried into an
      input the workflow reads as opted-in — asserted THROUGH the real intake
      path (client.lane_optin_intake + client.apply_lane_optin, the exact two
      calls cmd_ticket_start makes), never by hand-instantiating
      DevLaneTicketInput;
  (2) refusals are BY NAME at intake, before the workflow starts: unknown/
      malformed version (registry listed), empty develop_line_id, undeclared
      line id (lines.json is the single truth — the refusal quotes its named
      error, the declared-id list is never duplicated);
  (3) absence stays legacy: a payload with neither field validates clean with
      empty fields and apply_lane_optin returns the SAME plain TicketInput
      object unchanged (byte-identical; the engine's getattr default stays the
      replay guard);
  (4) the list face carries lane_version / develop_line (client._row_from_meta),
      and old-engine rows without the keys render empty honestly.

Fault-mode checklist (review condition C1 — borrowed from the t261009-46 intake
refusal family, each mode declared carried over / dropped):
  carried: non-string version, wrong-shape version (space/underscore/uppercase/
    surrounding dash), unknown well-formed version (registry named),
    whitespace-padded version;
  carried and NEW here (they only exist once intake has the fields): empty
    develop_line_id with the develop-buffer version, undeclared line id,
    line id paired with legacy, foreign template, wrong-container line id;
  dropped: blank-string version handling inside parse_lane_version (covered by
    the t261009-46 suite — intake resolves presence first, then delegates to
    the same function; re-testing the delegated branch would test the borrow
    twice and the original once).
Malformed-input discipline: every bad value below is fixed in-test, never an
external source.
"""
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import client as client_mod  # noqa: E402  (the real production intake module)
import dev_lane  # noqa: E402
import develop_line as dl  # noqa: E402
import shared  # noqa: E402
from shared import TicketInput  # noqa: E402


# ------------------------------------------------------------------ fixtures

@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated project store so develop_line.load_line reads a fixture
    lines.json, never the machine's real declaration."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    return tmp_path


def _declare(env, line_ids=("buffer",), project="proj"):
    decl = [{"line_id": lid, "scope": "epic x", "owner": "integration",
             "repositories": [{"name": "r", "branch": "develop-%s" % lid}],
             "extra_scenarios": [], "version": 1}
            for lid in line_ids]
    d = shared.develop_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")


def _plain_input() -> TicketInput:
    """The pre-opt-in production shape (what client.py:1802 used to build and
    what every legacy in-flight ticket's history stores)."""
    return TicketInput(ticket_id="t-test", template_id="dev-lane", title="t")


# ----------------------------------------------- (1) the opt-in rides intake

def test_optin_carried_into_the_extended_input(env):
    _declare(env)
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer-v1", "develop_line_id": " buffer "},
        "dev-lane", "proj")
    assert ok and err == ""
    assert lv == "develop-buffer-v1" and line_id == "buffer"
    inp = client_mod.apply_lane_optin(_plain_input(), lv, line_id)
    # the extended shape, built through the real intake path — not by hand
    assert isinstance(inp, dev_lane.DevLaneTicketInput)
    assert dl.parse_lane_version(inp.lane_version) == dl.LANE_VERSION_DEVELOP_BUFFER
    assert inp.develop_line_id == "buffer"
    # the workflow's routing reads exactly these (getattr is the seam)
    assert getattr(inp, "lane_version", "") == "develop-buffer-v1"


def test_legacy_version_optin_is_lawful_and_carried(env):
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "legacy-v1"}, "dev-lane", "proj")
    assert ok and lv == "legacy-v1" and line_id == ""
    inp = client_mod.apply_lane_optin(_plain_input(), lv, line_id)
    assert isinstance(inp, dev_lane.DevLaneTicketInput)
    assert inp.lane_version == "legacy-v1" and inp.develop_line_id == ""


# --------------------------------------- (2) refusals are by name at intake

def test_unknown_version_refused_with_registry_named():
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer"}, "dev-lane", "proj")
    assert not ok and lv == "" and line_id == ""
    assert "develop-buffer" in err and "legacy-v1" in err and "develop-buffer-v1" in err


@pytest.mark.parametrize("bad", ["develop-buffer-V1", "develop buffer",
                                 "develop_buffer_v1", " develop-buffer-v1",
                                 "-lead", 7, ["develop-buffer-v1"]])
def test_malformed_versions_refused_by_name(bad):
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": bad}, "dev-lane", "proj")
    assert not ok and lv == "" and line_id == ""
    assert err.strip()  # named, never an empty refusal


def test_develop_buffer_without_line_id_refused():
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer-v1"}, "dev-lane", "proj")
    assert not ok
    assert "develop_line_id" in err


def test_undeclared_line_refused_by_name_with_declared_list(env):
    _declare(env, line_ids=("buffer", "spare"))
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer-v1", "develop_line_id": "ghost"},
        "dev-lane", "proj")
    assert not ok and lv == "" and line_id == ""
    # the single truth is the declaration file: the refusal quotes its named
    # error, which lists exactly the declared ids — never a local copy
    assert "ghost" in err and "buffer" in err and "spare" in err


def test_missing_declaration_file_refused(env):
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer-v1", "develop_line_id": "buffer"},
        "dev-lane", "proj")
    assert not ok and "declaration" in err.lower()


def test_line_id_with_legacy_version_refused():
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "legacy-v1", "develop_line_id": "buffer"},
        "dev-lane", "proj")
    assert not ok and "develop-buffer-v1" in err


def test_fields_on_a_foreign_template_refused():
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer-v1", "develop_line_id": "buffer"},
        "inspection-lite", "proj")
    assert not ok and "dev-lane" in err and lv == ""


def test_wrong_container_line_id_refused_not_stringified(env):
    _declare(env)
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "develop-buffer-v1", "develop_line_id": ["buffer"]},
        "dev-lane", "proj")
    assert not ok  # a list must not be silently joined into a line id


# ------------------------------------------------ (3) absence stays legacy

def test_absence_validates_clean_and_stays_plain():
    ok, lv, line_id, err = client_mod.lane_optin_intake({}, "dev-lane", "proj")
    assert ok and lv == "" and line_id == "" and err == ""
    inp = _plain_input()
    out = client_mod.apply_lane_optin(inp, "", "")
    # the SAME plain object, untouched — no silent migration, byte-identical
    # legacy shape (spec (3)); the engine's getattr default stays the replay guard
    assert out is inp
    assert type(out) is TicketInput
    assert not hasattr(out, "lane_version")
    assert getattr(out, "lane_version", "") == ""


def test_blank_strings_count_as_absence():
    ok, lv, line_id, err = client_mod.lane_optin_intake(
        {"lane_version": "  ", "develop_line_id": ""}, "dev-lane", "proj")
    assert ok and lv == "" and line_id == ""


# ------------------------------------------------------- (4) the list face

def test_list_row_carries_lane_fields():
    row = client_mod._row_from_meta(
        "t-test", {"lane_version": "develop-buffer-v1", "develop_line": "buffer"},
        "RUNNING")
    assert row["lane_version"] == "develop-buffer-v1"
    assert row["develop_line"] == "buffer"


def test_list_row_legacy_and_old_engine_rows_render_empty():
    legacy = client_mod._row_from_meta(
        "t-test", {"lane_version": "", "develop_line": ""}, "RUNNING")
    assert legacy["lane_version"] == "" and legacy["develop_line"] == ""
    # old-engine row: the keys are missing entirely — empty, never a KeyError
    old = client_mod._row_from_meta("t-test", {}, "RUNNING")
    assert old["lane_version"] == "" and old["develop_line"] == ""


# --------------------------------------- replay guard intact (spec (3) tail)

def test_engine_routing_still_routes_a_plain_input_legacy():
    # getattr on the plain shape returns "" → parse resolves legacy → the
    # predicate routes False. An older history replayed by new code stays legacy.
    plain = _plain_input()
    assert dl.parse_lane_version(getattr(plain, "lane_version", "")) == \
        dl.LANE_VERSION_LEGACY
    assert not dev_lane.is_develop_buffer_ticket({"lane_version": ""})
