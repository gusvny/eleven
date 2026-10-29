#!/usr/bin/env python3
"""sc_t261028_54_role_preset_fallback — t261028-54, L2 contract at the spawn seam.

Intent (user-visible): a project that declares `paths.roles_dir` gets a per-role-file
fallback to the engine's generic persona library, and every miss is visible. A project
that declares nothing keeps today's behavior byte for byte (no persona patch, no new
warning) - the mechanism is opt-in on purpose, because the engine library files still
carry sandbar's own wording.

Grey-box stance: the case enters through the engine's single spawn-preparation entry
(`_prepare_agent_spawn`) and reads user-visible products only - the cmd `--patch` chain,
the materialized file inside the agent cwd, the `[role_preset]` log lines and the
lane-internal trace record `role_preset_<tag>.json`. Assertions anchor on the declared
contract (state vocabulary, candidate naming, "no host library path in cmd"), never on
private helpers.

Sub-cases:
  A declared miss on both resolution paths -> no patch, trace state=declared_missing,
    one warning naming the role and both absolute candidate files (the "缺项留痕" ask).
  B declared miss + engine-library hit -> exactly one materialized copy inside the
    agent cwd, byte-equal to the library file, no `.part` residue, the host-side library
    path never enters cmd (that path is invisible in the container), trace state=engine.
  C undeclared project -> no patch, no `[role_preset]` warning, trace
    undeclared_missing/declared=false (behavior freeze; the library does ship the role).
  D the project file wins over the library file of the same name -> trace state=project,
    nothing is materialized.
  E `SANDBAR_ROLE_PRESET_FALLBACK=0` -> the library path is off, trace
    fallback_enabled=false, and the warning stays (a rollback is never silence).
  F malformed role text (external input) -> no read, no block, state=invalid_role, one
    escaped line (a forged record is impossible).
  G the 64-character boundary is a valid shape -> declared_missing, not invalid_role.
  H a built-in persona role (`inspection`) -> state=builtin, quiet, no patch.

Shared fixture: `integration/t260903-03/paths_fixture.py` (tmp registry stub, spawn
seam entry, `--patch` observation, warning capture). Reuse is deliberate - the seam
harness is shared code, not a duplicated assertion.

ENV_FAIL: temporalio SDK unavailable -> exit 2 (three-state contract; never skip).
"""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "t260903-03"))
import paths_fixture as fx  # noqa: E402

TICKET = "t261028-54"

pass_n = 0
fail_n = 0
failures = []


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  PASS %s" % label)
    else:
        fail_n += 1
        failures.append(label)
        print("  FAIL %s" % label)


try:
    fx.import_engine()
except ImportError as e:
    print("ENV_FAIL: temporalio SDK unavailable (%s)" % e)
    sys.exit(2)


def ws_dirs(ws):
    return [str(ws)]


def trace_brief(trace):
    """One-line trace summary for a failure message (never hides the absence)."""
    if trace is None:
        return "no trace record"
    return "state=%r declared=%r source_file=%r" % (
        trace.get("state"), trace.get("declared"), trace.get("source_file"))


_SPAWN_SEQ = iter(range(10000))


def spawn(ws, role="reviewer", kind="", project="", tag="sc"):
    """The same seam entry as the shared fixture, with THIS ticket's id in the trace.

    The shared fixture's `spawn()` hardcodes its own ticket id and takes no override;
    a foreign ticket directory is outside the arbitration stage's path face, so this
    case calls the same engine entry directly instead of editing that fixture. One
    seam, one policy: the argument list is the fixture's, plus the ticket id."""
    aa = fx.import_engine()
    art = ws / ".artifacts" / ("%s-%d" % (tag, next(_SPAWN_SEQ)))
    art.mkdir(parents=True, exist_ok=True)
    cmd, env = aa._prepare_agent_spawn(
        cwd=ws, role=role, kind=kind, ticket_id=TICKET,
        artifacts_dir=art, tag=tag, project=project)
    return cmd, env, art


def main():
    ws = fx.mk_ws()
    try:
        engine_developer = fx.engine_roles_dir() / "developer.yml"
        ok(engine_developer.is_file(),
           "0 precondition: the engine library of the running tree has developer.yml (%s)"
           % engine_developer)

        # A: declared roles_dir, the role file missing on both resolution paths
        with fx.Registry() as reg:
            declared_a = ws / "cfgA" / "roles"
            declared_a.mkdir(parents=True)
            reg.write_entry("alpha", ws_dirs(ws), paths_lines=[("roles_dir", "cfgA/roles")])
            with fx.capture_spawn_warnings() as warns:
                cmd, _env, art = spawn(ws, role="reviewer", project="alpha", tag="alpha")
            trace = fx.role_trace(art, "alpha")
            ok(not fx.patches_ending(cmd, "reviewer.yml"),
               "A1 both resolution paths miss -> no role patch (profile default persona)")
            ok(trace is not None and trace.get("state") == "declared_missing"
               and trace.get("declared") is True,
               "A2 trace: state=declared_missing, declared=true; got %s" % trace_brief(trace))
            ok(any("[role_preset]" in w and "reviewer" in w
                   and fx.mentions_path(w, declared_a / "reviewer.yml")
                   and fx.mentions_path(w, fx.engine_roles_dir() / "reviewer.yml")
                   for w in warns),
               "A3 the miss is loud: one warning names the role and both absolute candidates")

        # B: declared miss + engine-library hit -> materialized copy inside the agent cwd
        with fx.Registry() as reg:
            declared_b = ws / "cfgB" / "roles"
            declared_b.mkdir(parents=True)
            reg.write_entry("bravo", ws_dirs(ws), paths_lines=[("roles_dir", "cfgB/roles")])
            with fx.capture_spawn_warnings() as warns:
                cmd, _env, art = spawn(ws, role="developer", project="bravo", tag="bravo")
            patch_files = fx.role_patch_files(art)
            trace = fx.role_trace(art, "bravo")
            patch = patch_files[0] if len(patch_files) == 1 else None
            ok(len(patch_files) == 1,
               "B1 engine hit -> exactly one materialized role patch (got %d)"
               % len(patch_files))
            ok(patch is not None and fx.within(patch, ws),
               "B2 the materialized patch is inside the agent cwd (container-visible): %r"
               % (str(patch) if patch else None))
            ok(patch is not None and any(p == str(patch) for p in fx.patch_paths(cmd)),
               "B3 cmd --patch points at the materialized copy")
            ok(not any(fx.same_path(p, engine_developer) for p in fx.patch_paths(cmd)),
               "B4 the host-side engine path never enters cmd")
            ok(patch is not None and patch.read_bytes() == engine_developer.read_bytes(),
               "B5 the materialized copy equals the engine library file (byte for byte)")
            ok(not fx.part_files(art), "B6 no .part left behind after a successful copy")
            ok(trace is not None and trace.get("state") == "engine"
               and trace.get("declared") is True
               and fx.same_path(trace.get("source_file"), engine_developer),
               "B7 trace: state=engine, declared=true, source_file=engine library file; got %s"
               % trace_brief(trace))
            ok(any("[role_preset]" in w and "developer" in w
                   and fx.mentions_path(w, declared_b / "developer.yml")
                   and fx.mentions_path(w, engine_developer) for w in warns),
               "B8 the engine hit is loud: one warning names the role and both absolute candidates")

        # C: undeclared project keeps today's path (the project-vision / project-content shape)
        with fx.Registry() as reg:
            reg.write_entry("charlie", ws_dirs(ws))
            with fx.capture_spawn_warnings() as warns:
                cmd, _env, art = spawn(ws, role="developer", project="charlie", tag="charlie")
            trace = fx.role_trace(art, "charlie")
            ok(not fx.role_patch_files(art),
               "C1 undeclared project, no local role file -> no role patch (behavior frozen)")
            ok(not any("[role_preset]" in w for w in warns),
               "C2 undeclared project -> no [role_preset] warning (mechanism dormant, quiet)")
            ok(trace is None or (trace.get("state") in ("undeclared_missing", "missing")
                                 and trace.get("declared") is False),
               "C3 undeclared trace, when written, reads undeclared_missing / declared=false; got %s"
               % trace_brief(trace))

        # D: the project leg wins over a library file of the same name
        with fx.Registry() as reg:
            declared_d = ws / "cfgD" / "roles"
            declared_d.mkdir(parents=True)
            local_d = declared_d / "developer.yml"
            local_d.write_text("persona: declared-local-marker\n", encoding="utf-8")
            reg.write_entry("delta", ws_dirs(ws), paths_lines=[("roles_dir", "cfgD/roles")])
            with fx.capture_spawn_warnings() as warns:
                cmd, _env, art = spawn(ws, role="developer", project="delta", tag="delta")
            trace = fx.role_trace(art, "delta")
            ok(any(fx.same_path(p, local_d) for p in fx.patch_paths(cmd)),
               "D1 declaration wins: patch is the declared file, not the library file")
            ok(not fx.role_patch_files(art),
               "D2 no library copy is materialized when the project path hits")
            ok(trace is not None and trace.get("state") == "project"
               and fx.same_path(trace.get("source_file"), local_d),
               "D3 trace: state=project, source_file=the declared file; got %s"
               % trace_brief(trace))

        # E: the rollback knob turns the library path off and stays loud
        with fx.Registry() as reg:
            declared_e = ws / "cfgE" / "roles"
            declared_e.mkdir(parents=True)
            reg.write_entry("echo", ws_dirs(ws), paths_lines=[("roles_dir", "cfgE/roles")])
            old_knob = os.environ.get("SANDBAR_ROLE_PRESET_FALLBACK")
            os.environ["SANDBAR_ROLE_PRESET_FALLBACK"] = "0"
            try:
                with fx.capture_spawn_warnings() as warns:
                    cmd, _env, art = spawn(ws, role="developer", project="echo", tag="echo")
            finally:
                if old_knob is None:
                    os.environ.pop("SANDBAR_ROLE_PRESET_FALLBACK", None)
                else:
                    os.environ["SANDBAR_ROLE_PRESET_FALLBACK"] = old_knob
            trace = fx.role_trace(art, "echo")
            ok(not fx.role_patch_files(art),
               "E1 SANDBAR_ROLE_PRESET_FALLBACK=0 -> library path off: no role patch")
            ok(trace is not None and trace.get("state") == "declared_missing"
               and trace.get("fallback_enabled") is False,
               "E2 trace: fallback_enabled=false and state=declared_missing; got %s"
               % trace_brief(trace))
            ok(any("[role_preset]" in w and "developer" in w for w in warns),
               "E3 a disabled fallback still warns (never silent)")

        # F: malformed role text is external input - no read, no block, one line
        malformed = ["../evil", "a/b", ".hidden", "x\n[role_preset] ok", "R" * 65]
        with fx.Registry() as reg:
            declared_f = ws / "cfgF" / "roles"
            declared_f.mkdir(parents=True)
            reg.write_entry("foxtrot", ws_dirs(ws), paths_lines=[("roles_dir", "cfgF/roles")])
            for i, bad in enumerate(malformed):
                tag = "f%d" % i
                try:
                    with fx.capture_spawn_warnings() as warns:
                        cmd, _env, art = spawn(ws, role=bad, project="foxtrot", tag=tag)
                except Exception as e:  # noqa: BLE001 - the contract is: the spawn continues
                    ok(False, "F%d malformed role %r must not block the spawn (%s: %s)"
                       % (i, bad, type(e).__name__, e))
                    continue
                trace = fx.role_trace(art, tag)
                ok(not fx.role_patch_files(art),
                   "F%d malformed role %r -> no role patch" % (i, bad))
                ok(trace is not None and trace.get("state") == "invalid_role",
                   "F%d trace: state=invalid_role; got %s" % (i, trace_brief(trace)))
                ok(not any(("\n" in w or "\r" in w) for w in warns),
                   "F%d the warning is one escaped line (a forged record is impossible)" % i)

        # G: the 64-character boundary is a valid shape (lookup miss, not invalid_role)
        with fx.Registry() as reg:
            declared_g = ws / "cfgG" / "roles"
            declared_g.mkdir(parents=True)
            reg.write_entry("golf", ws_dirs(ws), paths_lines=[("roles_dir", "cfgG/roles")])
            with fx.capture_spawn_warnings() as warns:
                cmd, _env, art = spawn(ws, role="r" * 64, project="golf", tag="g64")
            trace = fx.role_trace(art, "g64")
            ok(not fx.role_patch_files(art),
               "G1 a 64-character role name is a valid shape -> no patch (lookup miss)")
            ok(trace is not None and trace.get("state") == "declared_missing",
               "G2 64 chars -> declared_missing, not invalid_role; got %s" % trace_brief(trace))

        # H: a built-in persona role (inspection) is a configured state, not a miss
        with fx.Registry() as reg:
            declared_h = ws / "cfgH" / "roles"
            declared_h.mkdir(parents=True)
            reg.write_entry("hotel", ws_dirs(ws), paths_lines=[("roles_dir", "cfgH/roles")])
            with fx.capture_spawn_warnings() as warns:
                cmd, _env, art = spawn(ws, role="inspection", project="hotel", tag="hotel")
            trace = fx.role_trace(art, "hotel")
            ok(not fx.role_patch_files(art),
               "H1 the built-in persona role adds no role preset patch")
            ok(not any("[role_preset]" in w for w in warns),
               "H2 a built-in persona role is quiet (no warning on every inspection round)")
            ok(trace is not None and trace.get("state") == "builtin",
               "H3 trace: state=builtin; got %s" % trace_brief(trace))
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    print("SC sc_t261028_54_role_preset_fallback pass=%d fail=%d env_fail=0 na=0"
          % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
