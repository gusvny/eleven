"""t261028-54 L1: role preset resolution per file, with a trace.

Ticket: a project roles directory that lacks `<role>.yml` falls back to the engine
library and the miss is recorded. Host order (project-vision 261028): modeling needs an
independent role, so the engine must support per-file fallback plus a trace of missing
items.

Two faces are pinned here:

  R - `shared.role_preset_for_spawn` (pure resolution, tmp registry + tmp engine
      library): the chain, the declared-only gate, the state vocabulary, the role-name
      shape guard, the knob, the directory-shaped candidate, and the one-project-leg
      rule (`roles_dir_for_spawn` agrees with the decision).
  S - the spawn face of `_prepare_agent_spawn` (stub dsh binary, no network, no real
      dsh, no real home): which `--patch` argument appears in the command, the trace
      record, the log level per state, the materialization inside the lane, and every
      failure path (copy failure, trace write failure) leaving the spawn alive.

Decisions carried from review_plan (round 2):
  * declared-only engine leg: an UNDECLARED project keeps the pre-ticket behavior byte
    for byte (project leg only, info line, no warning).
  * `patch_arg_added` (not "applied"): the engine only adds the argument; whether dsh
    applies the file is dsh's business (KI-102).
  * role text is external input: it is JSON-escaped and truncated in log lines, and a
    malformed name never stats or reads a file.
  * one trace record and one `[role_preset]` line per spawn, for every state.

Zero network, zero real dsh processes (the stub only answers `--version`), zero real
`~/.dsh` and zero real `~/.sandbar/projects` (both are redirected under tmp_path).
"""
import hashlib
import json
import logging
from pathlib import Path

import pytest

import agent_activities as aa
import shared

REPO = Path(__file__).resolve().parents[3]

#: Stable trace key set of role_preset_<tag>.json (the contract a scenario may assert).
TRACE_KEYS = {
    "role", "role_len", "state", "source", "source_file", "source_sha256_16",
    "declared", "roles_rel", "project_dir", "engine_dir", "fallback_enabled",
    "candidates", "error", "patch", "patch_arg_added", "materialized", "ticket_id",
    "tag", "ts",
}

ROLE_FILE_BODY = "personaPrefix: &role_brief >-\n  tmp persona for %s\n"


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No outer knob may leak into a case (runtime mode, dsh pin, fallback knob)."""
    for name in ("SANDBAR_AGENT_RUNTIME", "SANDBAR_AGENT_IMAGE", "SANDBAR_AGENT_CMD",
                 "SANDBAR_DSH_EXPECTED_VERSION", "SANDBAR_DSH_STRICT",
                 "SANDBAR_AGENT_STUB", shared.ENV_ROLE_PRESET_FALLBACK):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Isolated per-key registry root (never the real ~/.sandbar/projects)."""
    root = tmp_path / "registry"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))

    def write_entry(key, roles_dir=None):
        d = root / key
        d.mkdir(parents=True, exist_ok=True)
        home = tmp_path / ("home-" + key)
        home.mkdir(exist_ok=True)
        lines = ["schema: v1", "project:", "  - key: %s" % key,
                 "    name: %s" % key, "    dirs:", "      - %s" % home]
        if roles_dir is not None:
            lines += ["paths:", "  roles_dir: %s" % roles_dir]
        (d / "project.yaml").write_text("\n".join(lines) + "\n", "utf-8")
        return home

    return write_entry


@pytest.fixture
def engine_lib(tmp_path, monkeypatch):
    """Engine library fixture injected through shared.engine_roles_dir (the documented
    test injection point; production reads the tree that runs the code)."""
    lib = tmp_path / "engine-roles"
    lib.mkdir()

    def put(role, body=None):
        p = lib / (role + ".yml")
        p.write_text(body or (ROLE_FILE_BODY % role), "utf-8")
        return p

    monkeypatch.setattr(shared, "engine_roles_dir", lambda: lib)
    return put


@pytest.fixture
def spawn_env(tmp_path, monkeypatch, engine_lib):
    """Minimal host-mode spawn environment: stub dsh, lane-local DSH_HOME, and the
    profile/credential copies stubbed out (they are not this ticket's face)."""
    stub = tmp_path / "bin" / "dsh"
    stub.parent.mkdir(parents=True)
    stub.write_text("#!/usr/bin/env python3\nprint('9.9.9-pin')\n", "utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("SANDBAR_AGENT_CMD", "%s --profile sandbar-headless" % stub)
    home = tmp_path / "dsh-home"
    home.mkdir()
    monkeypatch.setenv("DSH_HOME", str(home))
    monkeypatch.setattr(aa, "_copy_profile", lambda *a, **k: None)
    monkeypatch.setattr(aa, "_copy_creds", lambda *a, **k: None)
    monkeypatch.setattr(aa, "_copy_settings", lambda *a, **k: None)
    monkeypatch.setattr(aa, "_quarantine_torn_sessions", lambda *a, **k: None)
    return stub


def _lane(tmp_path, name="lane", role_files=None, declare_roles_dir=None,
          engine_lib=None):
    """A lane directory shaped like the production one, with the project roles dir at
    the declared relative path (or the convention path)."""
    lane = tmp_path / name
    lane.mkdir()
    rel = declare_roles_dir or "server/roles"
    if role_files or declare_roles_dir:
        # The declared anchor must exist (a missing declared anchor is fail-closed red).
        d = lane / rel
        d.mkdir(parents=True, exist_ok=True)
        for role_name, body in (role_files or {}).items():
            (d / (role_name + ".yml")).write_text(body or (ROLE_FILE_BODY % role_name),
                                                  "utf-8")
    return lane


def _patch_args(cmd):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--patch"]


def _role_patches(cmd):
    return [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")
            or p.endswith(".yml") and "roles" in p]


def _spawn(lane, tmp_path, role, project="", tag="implement_gen1", artifacts=None):
    art = Path(artifacts) if artifacts else (lane / ".sandbar")
    art.mkdir(parents=True, exist_ok=True)
    return aa._prepare_agent_spawn(cwd=lane, role=role, kind="", ticket_id="t26102854",
                                  artifacts_dir=art, tag=tag, project=project)


def _trace(art, tag="implement_gen1"):
    return json.loads((Path(art) / ("role_preset_%s.json" % tag)).read_text("utf-8"))


def _role_lines(caplog, level=None):
    return [r.getMessage() for r in caplog.records
            if "[role_preset]" in r.getMessage()
            and (level is None or r.levelname == level)]


# --------------------------------------------------------------------------------------
# R - the resolver
# --------------------------------------------------------------------------------------

def test_no_role_and_invalid_shapes_never_touch_the_filesystem(tmp_path, engine_lib):
    lane = _lane(tmp_path)
    for role, state in ((None, "no_role"), ("", "no_role"),
                        (42, "invalid_role"), ("../evil", "invalid_role"),
                        ("a/b", "invalid_role"), (".hidden", "invalid_role"),
                        ("x y", "invalid_role"), ("\u0440\u043e\u043b\u044c", "invalid_role"),
                        ("x\n[role_preset] ok", "invalid_role"),
                        ("\x00\x1b", "invalid_role"), (" x ", "invalid_role"),
                        ("a" * 65, "invalid_role")):
        d = shared.role_preset_for_spawn("", lane, role)
        assert d["state"] == state, (role, d["state"])
        assert d["candidates"] == [], "a rejected name must not stat any candidate"
        assert d["source_file"] is None


def test_role_name_boundary_64_is_valid(tmp_path, engine_lib):
    lane = _lane(tmp_path)
    d = shared.role_preset_for_spawn("", lane, "a" * 64)
    assert d["state"] == "undeclared_missing"     # valid shape -> normal lookup
    assert [c["leg"] for c in d["candidates"]] == ["project", "engine"]


def test_undeclared_project_uses_the_project_leg_only(tmp_path, engine_lib):
    engine_lib("developer")
    lane = _lane(tmp_path, role_files={"developer": None})
    d = shared.role_preset_for_spawn("", lane, "developer")
    assert d["state"] == "project"
    assert d["declared"] is False
    assert d["source_file"] == str(lane / "server" / "roles" / "developer.yml")
    assert d["source_sha256_16"] == hashlib.sha256(
        Path(d["source_file"]).read_bytes()).hexdigest()[:16]
    engine_cand = [c for c in d["candidates"] if c["leg"] == "engine"][0]
    assert engine_cand["consulted"] is False, "an undeclared project never consults it"


def test_undeclared_project_without_local_file_reports_undeclared_missing(tmp_path,
                                                                         engine_lib):
    """The engine library has the role, and it is STILL not used: the declaration is
    the opt-in (review_plan round 1 decision D1)."""
    engine_lib("developer")
    lane = _lane(tmp_path)
    d = shared.role_preset_for_spawn("", lane, "developer")
    assert d["state"] == "undeclared_missing"
    assert d["declared"] is False
    assert d["candidates"][1]["consulted"] is False


def test_declared_project_missing_file_uses_the_engine_leg(tmp_path, registry,
                                                           engine_lib):
    registry("proj", roles_dir="cfg/roles")
    src = engine_lib("developer")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles")
    d = shared.role_preset_for_spawn("proj", lane, "developer")
    assert d["state"] == "engine" and d["source"] == "engine"
    assert d["source_file"] == str(src)
    assert d["source_sha256_16"] == hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    assert d["declared"] is True and d["roles_rel"] == "cfg/roles"
    assert [c["consulted"] for c in d["candidates"]] == [True, True]


def test_declared_project_hit_beats_the_engine_leg(tmp_path, registry, engine_lib):
    registry("proj", roles_dir="cfg/roles")
    engine_lib("developer")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles",
                 role_files={"developer": "personaPrefix: project\n"})
    d = shared.role_preset_for_spawn("proj", lane, "developer")
    assert d["state"] == "project"
    assert d["source_file"] == str(lane / "cfg" / "roles" / "developer.yml")
    assert d["candidates"][1]["consulted"] is False, "the engine leg is not read on a hit"


def test_declared_project_both_legs_missing(tmp_path, registry, engine_lib):
    registry("proj", roles_dir="cfg/roles")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles")
    d = shared.role_preset_for_spawn("proj", lane, "no-such-role")
    assert d["state"] == "declared_missing"
    assert [c["kind"] for c in d["candidates"]] == ["absent", "absent"]


def test_declared_anchor_defect_still_fails_closed(tmp_path, registry, engine_lib):
    registry("proj", roles_dir="cfg/roles")
    lane = _lane(tmp_path)                     # the declared directory does not exist
    with pytest.raises(shared.ProjectPathsError) as ei:
        shared.role_preset_for_spawn("proj", lane, "developer")
    assert "roles_dir" in str(ei.value) and "cfg/roles" in str(ei.value)


def test_declared_dir_equal_to_engine_dir_is_a_project_hit(tmp_path, registry,
                                                           monkeypatch):
    """K8: a declared roles dir that resolves to the engine dir yields state=project and
    the engine leg is never consulted (no false 'fallback' record)."""
    registry("proj", roles_dir="server/roles")
    lane = _lane(tmp_path, role_files={"developer": None})
    monkeypatch.setattr(shared, "engine_roles_dir",
                        lambda: lane / "server" / "roles")
    d = shared.role_preset_for_spawn("proj", lane, "developer")
    assert d["state"] == "project"
    assert [c["consulted"] for c in d["candidates"]] == [True, False]


def test_directory_named_like_a_preset_is_not_a_hit(tmp_path, registry, engine_lib):
    """K6: `<role>.yml` as a DIRECTORY is reported as kind=dir and never reads as
    present; the declared engine leg then serves the role."""
    registry("proj", roles_dir="cfg/roles")
    src = engine_lib("developer")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles")
    (lane / "cfg" / "roles" / "developer.yml").mkdir()
    d = shared.role_preset_for_spawn("proj", lane, "developer")
    assert d["candidates"][0]["kind"] == "dir"
    assert d["state"] == "engine" and d["source_file"] == str(src)


def test_knob_disables_the_engine_leg(tmp_path, registry, engine_lib, monkeypatch):
    """K3: the knob turns leg 3 off, the state reads declared_missing and the reason
    names the knob."""
    registry("proj", roles_dir="cfg/roles")
    engine_lib("developer")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles")
    monkeypatch.setenv(shared.ENV_ROLE_PRESET_FALLBACK, "0")
    d = shared.role_preset_for_spawn("proj", lane, "developer")
    assert d["state"] == "declared_missing"
    assert d["fallback_enabled"] is False
    assert shared.ENV_ROLE_PRESET_FALLBACK in d["error"]
    assert [c["consulted"] for c in d["candidates"]] == [True, False]


def test_builtin_persona_role_needs_no_file(tmp_path, registry, engine_lib):
    engine_lib("inspection")
    lane = _lane(tmp_path)
    d = shared.role_preset_for_spawn("", lane, "inspection")
    assert d["state"] == "builtin"
    assert d["source_file"] is None
    assert d["candidates"][1]["consulted"] is False


def test_state_vocabulary_is_closed(tmp_path, registry, engine_lib):
    registry("proj", roles_dir="cfg/roles")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles")
    seen = set()
    for role in (None, "../evil", "inspection", "no-such-role", "developer"):
        seen.add(shared.role_preset_for_spawn("proj", lane, role)["state"])
    assert seen <= set(shared.ROLE_PRESET_STATES)


def test_one_project_leg_rule(tmp_path, registry):
    """K4: the resolver and roles_dir_for_spawn agree (one implementation)."""
    registry("proj", roles_dir="cfg/roles")
    lane = _lane(tmp_path, declare_roles_dir="cfg/roles")
    declared_dir = shared.roles_dir_for_spawn("proj", lane)
    assert declared_dir == lane / "cfg" / "roles"
    assert shared.role_preset_for_spawn("proj", lane, "developer")["project_dir"] == \
        str(declared_dir)
    undeclared = tmp_path / "other"
    undeclared.mkdir()
    assert shared.roles_dir_for_spawn("", undeclared) == undeclared / "server" / "roles"
    assert shared.role_preset_for_spawn("", undeclared, "developer")["project_dir"] == \
        str(undeclared / "server" / "roles")


# --------------------------------------------------------------------------------------
# S - the spawn face
# --------------------------------------------------------------------------------------

def test_project_hit_passes_the_file_through(tmp_path, registry, spawn_env, caplog):
    caplog.set_level(logging.INFO)
    lane = _lane(tmp_path, role_files={"developer": None})
    cmd, env = _spawn(lane, tmp_path, "developer", project="")
    local = str(lane / "server" / "roles" / "developer.yml")
    assert local in _patch_args(cmd), "the project leg keeps the pre-ticket path"
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "project" and trace["patch"] == local
    assert trace["patch_arg_added"] is True and trace["materialized"] is False
    assert set(trace) == TRACE_KEYS
    assert trace["role"] == "developer" and trace["tag"] == "implement_gen1"
    assert _role_lines(caplog, "WARNING") == [], "a project hit is not a warning"
    assert len(_role_lines(caplog)) == 1


def test_engine_leg_is_copied_inside_the_lane(tmp_path, registry, spawn_env,
                                              engine_lib, caplog):
    """The engine preset is materialized in the lane: a host path into the engine tree
    would be invisible to the docker runtime. One warning names the role, both
    candidates and the wording caveat."""
    caplog.set_level(logging.INFO)
    registry("proj", roles_dir="server/roles")
    src = engine_lib("developer")
    lane = _lane(tmp_path)                      # declared dir exists? create it
    (lane / "server" / "roles").mkdir(parents=True)
    cmd, env = _spawn(lane, tmp_path, "developer", project="proj")
    patch = [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    assert len(patch) == 1, cmd
    patch_path = Path(patch[0])
    assert patch_path.is_relative_to(lane), "the patch argument must live in the lane"
    assert str(patch_path).startswith(str(lane / ".sandbar")), "next to dsh_pin_*.json"
    assert patch_path.read_bytes() == src.read_bytes(), "copied byte for byte"
    assert not list(patch_path.parent.glob("*.part")), "no partial file left behind"
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "engine" and trace["materialized"] is True
    assert trace["source_file"] == str(src)
    assert trace["source_sha256_16"] == hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    warnings = _role_lines(caplog, "WARNING")
    assert len(warnings) == 1
    assert "developer" in warnings[0]
    assert str(lane / "server" / "roles" / "developer.yml") in warnings[0]
    assert str(src) in warnings[0]
    assert "another project's wording" in warnings[0]


def test_undeclared_project_keeps_the_old_silence(tmp_path, spawn_env, engine_lib,
                                                  caplog):
    """Acceptance 1: no role patch, no warning, info only, trace says
    undeclared_missing. The engine library exists and is deliberately not used."""
    caplog.set_level(logging.INFO)
    engine_lib("developer")
    lane = _lane(tmp_path)
    cmd, env = _spawn(lane, tmp_path, "developer", project="")
    assert not [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    assert not [p for p in _patch_args(cmd) if p.endswith("/developer.yml")]
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "undeclared_missing" and trace["declared"] is False
    assert trace["patch"] is None and trace["patch_arg_added"] is False
    assert _role_lines(caplog, "WARNING") == []
    assert len(_role_lines(caplog, "INFO")) == 1


def test_declared_both_miss_warns_and_adds_nothing(tmp_path, registry, spawn_env,
                                                   engine_lib, caplog):
    caplog.set_level(logging.INFO)
    registry("proj", roles_dir="server/roles")
    engine_lib("developer")
    lane = _lane(tmp_path)
    (lane / "server" / "roles").mkdir(parents=True)
    cmd, env = _spawn(lane, tmp_path, "modeler", project="proj")
    assert not [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "declared_missing"
    warnings = _role_lines(caplog, "WARNING")
    assert len(warnings) == 1
    assert "modeler" in warnings[0] and "profile default persona" in warnings[0]
    assert str(lane / "server" / "roles" / "modeler.yml") in warnings[0]
    assert str(shared.engine_roles_dir() / "modeler.yml") in warnings[0]


def test_knob_off_spawn_face_still_warns(tmp_path, registry, spawn_env, engine_lib,
                                          monkeypatch, caplog):
    """K3: the knob turns the engine leg off; the state reads declared_missing, the
    trace says fallback_enabled=false and the warning stays."""
    caplog.set_level(logging.INFO)
    registry("proj", roles_dir="server/roles")
    engine_lib("developer")
    lane = _lane(tmp_path)
    (lane / "server" / "roles").mkdir(parents=True)
    monkeypatch.setenv(shared.ENV_ROLE_PRESET_FALLBACK, "0")
    cmd, env = _spawn(lane, tmp_path, "developer", project="proj")
    assert not [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "declared_missing"
    assert trace["fallback_enabled"] is False
    warnings = _role_lines(caplog, "WARNING")
    assert len(warnings) == 1 and "developer" in warnings[0]


def test_directory_shaped_preset_spawns_the_engine_copy(tmp_path, registry, spawn_env,
                                                        engine_lib, caplog):
    """K6: `<role>.yml` as a DIRECTORY is not a preset; the declared project gets the
    engine-library copy and the trace records kind=dir."""
    caplog.set_level(logging.INFO)
    registry("proj", roles_dir="server/roles")
    src = engine_lib("developer")
    lane = _lane(tmp_path)
    (lane / "server" / "roles" / "developer.yml").mkdir(parents=True)
    cmd, env = _spawn(lane, tmp_path, "developer", project="proj")
    copies = [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    assert len(copies) == 1 and Path(copies[0]).read_bytes() == src.read_bytes()
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "engine"
    assert trace["candidates"][0]["kind"] == "dir"
    assert trace["candidates"][1]["kind"] == "file"


def test_invalid_role_is_one_escaped_line_and_reads_nothing(tmp_path, spawn_env,
                                                            caplog):
    """Acceptance 7: a hostile role value cannot forge a log line and no path is built
    from it."""
    caplog.set_level(logging.INFO)
    lane = _lane(tmp_path)
    cmd, env = _spawn(lane, tmp_path, "x\n[role_preset] forged", project="")
    assert not [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    warnings = _role_lines(caplog, "WARNING")
    assert len(warnings) == 1
    assert "\n" not in warnings[0], "one line, escaped"
    assert 'x\\n[role_preset] forged' in warnings[0]
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "invalid_role" and trace["candidates"] == []
    leftovers = [p.name for p in (lane / ".sandbar").iterdir()]
    assert not [n for n in leftovers if "forged" in n or "evil" in n]


def test_materialize_failure_never_passes_a_host_path(tmp_path, registry, spawn_env,
                                                      engine_lib, caplog):
    caplog.set_level(logging.INFO)
    registry("proj", roles_dir="server/roles")
    src = engine_lib("developer")
    lane = _lane(tmp_path)
    (lane / "server" / "roles").mkdir(parents=True)
    src.chmod(0o000)                            # unreadable source -> copy fails
    try:
        cmd, env = _spawn(lane, tmp_path, "developer", project="proj")
    finally:
        src.chmod(0o644)
    assert str(src) not in _patch_args(cmd), "a host path is never the argument"
    assert not [p for p in _patch_args(cmd) if Path(p).name.startswith("role_patch_")]
    trace = _trace(lane / ".sandbar")
    assert trace["state"] == "engine" and trace["materialized"] is False
    assert trace["patch"] is None and "materialize failed" in trace["error"]
    warnings = _role_lines(caplog, "WARNING")
    assert len(warnings) == 1 and "could not copy" in warnings[0]


def test_trace_write_failure_does_not_block_the_spawn(tmp_path, spawn_env, caplog):
    caplog.set_level(logging.INFO)
    lane = _lane(tmp_path)
    art = lane / ".sandbar"
    art.mkdir()
    (art / "role_preset_implement_gen1.json").mkdir()   # a directory in the way
    cmd, env = _spawn(lane, tmp_path, "developer", project="", artifacts=art)
    assert isinstance(cmd, list) and env, "the spawn survives a trace write failure"
    warnings = _role_lines(caplog, "WARNING")
    assert any("trace write failed" in w for w in warnings)


def test_spawn_returns_a_two_tuple(tmp_path, spawn_env):
    lane = _lane(tmp_path)
    result = _spawn(lane, tmp_path, "developer", project="")
    cmd, env = result
    assert isinstance(cmd, list) and isinstance(env, dict)
    assert len(result) == 2


def test_one_record_and_one_line_per_spawn(tmp_path, spawn_env, caplog):
    """K9: the per-spawn footprint is stated and pinned: one JSON file per tag and one
    [role_preset] line per spawn, for the dormant (undeclared) shape too."""
    caplog.set_level(logging.INFO)
    lane = _lane(tmp_path)
    _spawn(lane, tmp_path, "developer", project="")
    files = sorted(p.name for p in (lane / ".sandbar").glob("role_preset_*.json"))
    assert files == ["role_preset_implement_gen1.json"]
    assert len(_role_lines(caplog)) == 1


def test_role_text_for_log_escapes_and_truncates():
    assert "\n" not in aa._role_text_for_log("a\nb")
    assert aa._role_text_for_log("a\nb") == '"a\\nb"'
    long_text = aa._role_text_for_log("x" * 200)
    assert len(long_text) <= 82 and long_text.endswith("...")
