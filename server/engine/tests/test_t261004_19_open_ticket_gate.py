"""t261004-19 -- open-ticket epic authorization (judgement-core UT).

Coverage (the engine half of the ticket's acceptance bar; pure core + injected
IO, no Temporal, no real ~/.sandbar):
  - declaration face: open_ticket_epics / open_ticket_cap acceptance and named
    refusal of malformed input (external-input discipline: stub JSON fed
    directly, no real external source);
  - no authority grab: authority_surface_violation hits every protected surface
    plus disguised forms (./ prefix, ../ escape, absolute path); non-covered
    surfaces pass;
  - action-ledger ticket filter: executor_started_ids only accepts
    ticket-start x allowed, malformed lines skipped;
  - judgement core five refusals one allow: no epic named / epic not
    authorized / listed epic without a charter file / authority surface inside
    the write set / cap reached (declared cap and default 3 each) -- every
    refusal names its own condition; the allow verdict carries the epic and
    provenance keys (epic recorded into the action ledger's grant_source chain);
  - C2 per-epic attribution: under one declaration, epic a at cap refuses while
    epic b counts 0 and passes -- the cap is per-epic, not per-project;
  - real IO wrapper: judge_open_ticket checks charter-file existence via the
    SANDBAR_EPICS_DIR anchor.

Translation note (t261004-28 carrier, host L15 ruling): comments and docstrings
are translated to English; the assertions below match the engine's English
refusal copy verbatim (t261004-36) and carry no copy-language markers.
"""
import json

import pytest

import executor_grants as eg


@pytest.fixture
def grants_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def epics_dir(tmp_path, monkeypatch):
    d = tmp_path / "epics"
    d.mkdir()
    monkeypatch.setenv("SANDBAR_EPICS_DIR", str(d))
    return d


def _decl(**kw):
    doc = {"version": 1, "grants": {"open-ticket": True}, "open_ticket_epics": ["proj-exec"]}
    doc.update(kw)
    return doc


def _ok_load(**kw):
    doc, err = eg.validate_declaration(_decl(**kw))
    assert err is None
    return doc


# ---------- declaration face: new keys accepted / malformed refused by name ----------

def test_validate_accepts_open_ticket_keys(grants_root):
    doc, err = eg.validate_declaration({"version": 1, "grants": {},
                                        "open_ticket_epics": ["proj-exec", "ki-x"],
                                        "open_ticket_cap": 5})
    assert err is None
    assert doc["open_ticket_epics"] == ["proj-exec", "ki-x"]
    assert doc["open_ticket_cap"] == 5


def test_validate_defaults_when_absent(grants_root):
    doc, err = eg.validate_declaration({"version": 1, "grants": {}})
    assert err is None
    assert doc["open_ticket_epics"] == []            # default = no epic authorized
    assert doc["open_ticket_cap"] == eg.OPEN_TICKET_CAP_DEFAULT == 3


def test_validate_dedupes_and_strips(grants_root):
    doc, err = eg.validate_declaration({"version": 1, "grants": {},
                                        "open_ticket_epics": [" a ", "a", "b"]})
    assert err is None and doc["open_ticket_epics"] == ["a", "b"]


@pytest.mark.parametrize("bad", [
    "not-a-list",            # not an array
    42,                      # not an array
    [1, 2],                  # non-string items
    [""],                    # empty-string item
    ["UPPER_CASE"],          # illegal code shape
    ["has dot"],             # illegal code shape
])
def test_validate_malformed_epic_list_named(grants_root, bad):
    _, err = eg.validate_declaration({"version": 1, "grants": {}, "open_ticket_epics": bad})
    assert err and "open_ticket_epics" in err


def test_validate_epic_list_cap_named(grants_root):
    _, err = eg.validate_declaration({"version": 1, "grants": {},
                                      "open_ticket_epics": ["e%d" % i for i in range(eg.OPEN_TICKET_EPICS_MAX + 1)]})
    assert err and "open_ticket_epics" in err and str(eg.OPEN_TICKET_EPICS_MAX) in err


@pytest.mark.parametrize("cap", [True, 0, -1, 1.5, "3", []])
def test_validate_malformed_cap_named(grants_root, cap):
    _, err = eg.validate_declaration({"version": 1, "grants": {}, "open_ticket_cap": cap})
    assert err and "open_ticket_cap" in err


def test_save_declaration_carries_open_ticket_keys(grants_root):
    r = eg.save_declaration("sandbar", {"open-ticket": True}, "host", 1234,
                            open_ticket_epics=["proj-exec"], open_ticket_cap=7,
                            audit_sink=lambda k, row: None)
    assert r["saved"] is True
    back, verr = eg.validate_declaration(json.loads(open(r["file"], encoding="utf-8").read()))
    assert verr is None and back["open_ticket_epics"] == ["proj-exec"] and back["open_ticket_cap"] == 7


def test_save_declaration_inherits_epics_when_absent(grants_root):
    r1 = eg.save_declaration("sandbar", {"sign": True}, "host", 1234,
                             open_ticket_epics=["proj-exec"], audit_sink=lambda k, row: None)
    assert r1["saved"] is True
    # A second save without the epic list = "leave it alone this time" -- never
    # silently wipe already-authorized epics.
    r2 = eg.save_declaration("sandbar", {"sign": True, "rerun": True}, "host", 2345,
                             audit_sink=lambda k, row: None)
    assert r2["saved"] is True and r2["resolved"]["open_ticket_epics"] == ["proj-exec"]


def test_meta_op_still_host_only_with_new_keys(grants_root):
    """Invariant unchanged: the new keys are host-only too -- an executor identity
    (cwd channel) can never change them."""
    r = eg.save_declaration("sandbar", {}, "executor", 1234, open_ticket_epics=["proj-exec"],
                            caller_channel="cwd")
    assert r["saved"] is False and "meta-permission lock" in (r.get("reason") or "")


# ---------- no authority grab: authority_surface_violation ----------

@pytest.mark.parametrize("entry", [
    "server/engine/executor_grants.py",
    "./server/engine/path_gates.py",
    "../sandbar/server/engine/executor_grants.py",       # ../ escape
    "/Users/x/sandbar/server/engine/executor_grants.py",  # absolute path
    "server/roles/executor.md",
    "server/roles",
    "server/projects.yaml",
    "docs/design/ticket-workflow-console-design.md",
    "somewhere/executor-grants.json",
])
def test_authority_surface_hits(entry):
    assert eg.authority_surface_violation([entry]) is not None
    assert "hits the protected surface" in (eg.authority_surface_violation([entry]) or "")


@pytest.mark.parametrize("entry", [
    "app/src/main.py",
    "docs/designs/other.md",      # directory boundary: designs != design/
    "server/roleset/x.md",        # directory boundary: roleset != roles/
    "docs/notes.md",
])
def test_authority_surface_non_hits(entry):
    assert eg.authority_surface_violation([entry]) is None


def test_authority_surface_normalizes_backslash_and_dotslash():
    assert eg.authority_surface_violation([".\\server\\engine\\path_gates.py"]) is not None


def test_authority_surface_empty_and_malformed():
    assert eg.authority_surface_violation([]) is None
    assert eg.authority_surface_violation(None) is None
    assert eg.authority_surface_violation("not-a-list") is None


# ---------- action-ledger ticket filter ----------

def test_executor_started_ids_filters_op_and_decision():
    rows = [
        json.dumps({"op": "ticket-start", "decision": "allowed", "ticket": "t1"}),
        json.dumps({"op": "ticket-start", "decision": "refused", "ticket": "t2"}),
        json.dumps({"op": "sign", "decision": "allowed", "ticket": "t3"}),
        "{not json",
        json.dumps({"op": "ticket-start", "decision": "allowed"}),  # no ticket id = not accepted
    ]
    assert eg.executor_started_ids(rows) == {"t1"}
    assert eg.executor_started_ids(None) == set()


# ---------- judgement core: five refusals one allow ----------

def _core(epic, write_set=None, open_count=0, exists=True, load=None, sink=None):
    return eg.judge_open_ticket_core(load or _ok_load(), epic, write_set or ["app/src/x.py"],
                                     open_count, exists, 1234, "sandbar", audit_sink=sink)


def test_refuse_no_epic_named():
    v = _core("")
    assert v["allowed"] is False
    assert "must name an epic" in v["why"] and "epic" in v["why"]


def test_refuse_epic_not_on_list():
    v = _core("other-epic")
    assert v["allowed"] is False and "not on project" in v["why"] and "other-epic" in v["why"]


def test_refuse_listed_epic_without_file():
    v = _core("proj-exec", exists=False)
    assert v["allowed"] is False and "no epic file" in v["why"] and "proj-exec" in v["why"]


def test_refuse_authority_surface_in_write_set():
    v = _core("proj-exec", write_set=["app/src/x.py", "server/engine/executor_grants.py"])
    assert v["allowed"] is False and "protected source of truth" in v["why"] and "executor_grants.py" in v["why"]


def test_refuse_cap_reached_declared():
    load = _ok_load(open_ticket_cap=2)
    v = _core("proj-exec", open_count=2, load=load)
    assert v["allowed"] is False and "per-epic cap" in v["why"] and "already has 2" in v["why"]


def test_refuse_cap_reached_default_three():
    v = _core("proj-exec", open_count=3)
    assert v["allowed"] is False and "at the cap of 3" in v["why"] and "default 3" in v["why"]


def test_allow_carries_epic_and_provenance():
    sink = []
    v = _core("proj-exec", open_count=2, sink=sink)
    assert v["allowed"] is True and v["epic"] == "proj-exec" and v["enforced"] is True
    keys = (v.get("provenance") or {}).get("keys") or {}
    assert "open_ticket_epics.proj-exec" in keys and "authorized" in keys["open_ticket_epics.proj-exec"]
    assert sink == []  # an allow writes no refusal audit row


def test_c2_cap_is_per_epic_not_per_project():
    """Same declaration: epic a at cap refuses, epic b (a different epic) counts 0
    and passes -- attribution is per-epic."""
    load = _ok_load(open_ticket_epics=["epic-a", "epic-b"], open_ticket_cap=1)
    va = eg.judge_open_ticket_core(load, "epic-a", [], 1, True, 1234, "sandbar", audit_sink=lambda *a: None)
    vb = eg.judge_open_ticket_core(load, "epic-b", [], 0, True, 1234, "sandbar", audit_sink=lambda *a: None)
    assert va["allowed"] is False
    assert vb["allowed"] is True and vb["epic"] == "epic-b"


def test_refusal_appends_audit_row_with_epic():
    sink = []

    def _appender(key, row):
        sink.append((key, row))

    _core("other-epic", sink=_appender)
    assert len(sink) == 1
    key, row = sink[0]
    assert key == "sandbar" and row["action"] == "refuse" and row["op"] == "ticket-start"
    assert row["grant_op"] == "open-ticket" and row["epic"] == "other-epic" and row["why"]


# ---------- real IO wrapper: judge_open_ticket ----------

def test_judge_open_ticket_io_checks_file(epics_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path))
    (epics_dir / "proj-exec.md").write_text("# epic charter\n", encoding="utf-8")  # fixture domain text
    v = eg.judge_open_ticket(_ok_load(), "sandbar", "proj-exec", ["app/x.py"], 0)
    assert v["allowed"] is True
    v2 = eg.judge_open_ticket(_ok_load(open_ticket_epics=["ghost"]), "sandbar", "ghost",
                              ["app/x.py"], 0)
    assert v2["allowed"] is False and "no epic file" in v2["why"]


def test_judge_open_ticket_bad_declaration_fail_closed(grants_root):
    v = eg.judge_open_ticket({"ok": False, "kind": "malformed"}, "sandbar", "proj-exec",
                             ["app/x.py"], 0)
    assert v["allowed"] is False


def test_corrupt_declaration_with_named_session_fails_closed():
    """Scenario A8 unit face: the declaration channel carries a trusted session id
    and the on-disk declaration is corrupt -> named refusal, fail-closed (never an
    open gate); the lane-agent injection channel stays exempt under the same
    corruption (zero-regression red line); a plain call without a session id also
    stays exempt (t261001-20 fixture semantics)."""
    bad = {"ok": False, "declared": True, "kind": "malformed", "file": "/x/decl.json"}

    def face(_key):
        return bad

    v = eg.judge_core("arg", "ticket-start", "sandbar", face, 1234,
                      audit_sink=lambda *a: None, declared_sessions=(),
                      caller_session="sess-1")
    assert v["allowed"] is False and "fail-closed" in v["why"] and "malformed" in v["why"]
    v2 = eg.judge_core("env", "ticket-start", "sandbar", face, 1234,
                       audit_sink=lambda *a: None, lane_surface="lane-agent",
                       declared_sessions=(), caller_session="sess-1")
    assert v2["allowed"] is True and v2["enforced"] is False
    v3 = eg.judge_core("arg", "ticket-start", "sandbar", face, 1234,
                       audit_sink=lambda *a: None, declared_sessions=(),
                       caller_session="")
    assert v3["allowed"] is True and v3["enforced"] is False


# ---------- load_declaration ok face with the new keys ----------

def test_load_declaration_returns_open_ticket_face(grants_root):
    d = grants_root / "sandbar"
    d.mkdir(parents=True)
    (d / eg.DECL_FILE).write_text(json.dumps(
        {"version": 1, "grants": {"open-ticket": True}, "open_ticket_epics": ["proj-exec"],
         "open_ticket_cap": 5}), encoding="utf-8")
    r = eg.load_declaration("sandbar")
    assert r["ok"] is True and r["open_ticket_epics"] == ["proj-exec"] and r["open_ticket_cap"] == 5
