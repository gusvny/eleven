#!/usr/bin/env python3
"""t261022-09 — the quickmanual gate is driven by the ticket's evidence declaration.

Grey-box L3, offline seconds, zero docker / Temporal-server / browser, never
touches 3099/7233. Anchored ONLY to the declared faces of the accepted plan
(create_plan gen1, review_plan gen1 verdict=pass):

  - `shared.quick_scope_plan(kind, names, registry_names, check_ids,
    path_exists)` — the pure scope plan (mode in {full, scenario, check,
    battery}; the reserved full-gate token `integ` wins before any declared
    checks lookup; unknown targets are named in the error).
  - `QuickmanualLaneWorkflow` receipt faces: the gate receipt SUMMARY names the
    declared scope ("narrowed by declaration: ..." / "(full registry)");
    `gate_runs` carries `narrowed` as the declared-name list ([] = full,
    falsy like today's constant 0); an unresolvable declaration is a named
    GATE red `quick_scope_unresolved` — a ticket defect, NEVER inside the
    env-red channel (`_tests_env_red_names`), so the B2 rule can never
    exempt it.
  - `IntegrationRunArgs` carries a defaulted `quick_scope` (empty dict =
    today's FULL round, replay-safe) and dev_lane declares the new patch id
    `QUICKMANUAL_SCOPE_PATCH_ID` (old histories replay with the patch off).
  - `verify_lane` gains `only_check` (run exactly one declared checks entry;
    unknown id = named red; the full-gate token `integ` is NOT shadowed —
    verify.yaml has no such id, so it refuses by name) and `pytest_node`
    (only with a pytest-form check). Absent params = byte-identical old
    behavior over a fixture project.

Intent split (no intent-level duplication): the pure-function truth tables
and malformed-declaration matrices belong to developer L1
(test_quickmanual_lane.py); the real-Temporal session journey (orchestration,
settle, no-self-sign) belongs to quickmanual-lane-e2e (engine pool); the
registration/table-agreement faces belong to quickmanual-lane-faces; THIS
entry uniquely owns the assembled narrowed-gate contract: the declaration
drives the round, the receipt and the face name the narrowing honestly, an
unresolvable claim is a named product red outside the environment channel,
the full gate stays reachable on purpose, and the named-check tool entry
refuses what it cannot resolve.

Pre-implement tree red on A–E = the named TDD signal; green required at the
integration gate / merge.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(HERE))  # integration/ (lib_env)
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

_PASS = _FAIL = _ENV = 0


def _ok(name):
    global _PASS
    _PASS += 1
    print("PASS %s" % name)


def _bad(name, why):
    global _FAIL
    _FAIL += 1
    print("FAIL %s: %s" % (name, why))


def _env(name, why):
    global _ENV
    _ENV += 1
    print("ENV_FAIL %s: %s" % (name, why))


def _import_engine(modname):
    try:
        import importlib
        return importlib.import_module(modname)
    except Exception as e:  # noqa: BLE001
        _env("import:" + modname, "engine module unimportable: %r" % (e,))
        return None


def _declared(obj, name, label):
    """The plan-declared surface must exist; missing = named FAIL (the TDD
    signal), never a silent pass and never an environment red."""
    if obj is None or not hasattr(obj, name):
        _bad(label, "declared surface missing: %s.%s (plan gen1 step)" % (
            getattr(obj, "__name__", obj), name))
        return None
    return getattr(obj, name)


def _wf_instance(dev_lane):
    """A bare QuickmanualLaneWorkflow shell for the receipt/args faces (no
    Temporal context needed: these faces are pure derivations over the run
    result). Methods that need instance state get the minimal meta dict."""
    cls = getattr(dev_lane, "QuickmanualLaneWorkflow", None)
    if cls is None:
        return None
    inst = cls.__new__(cls)
    inst.ticket_id = "t261022-09-sc"
    inst._gens = {}
    inst.meta = {"worktree": REPO, "write_set": ["server/"],
                 "env_handover_pending": [], "handover_runs": []}
    return inst


def _call(fn, *a, **kw):
    return fn(*a, **kw)


def leg_a_receipt_and_verdict(dev_lane, agent_activities):
    """A: the receipt names the declared scope honestly; an unresolvable
    declaration is a named product red OUTSIDE the env-red channel."""
    label = "A.quick-gate-scope-faces"
    cls_ir = getattr(agent_activities, "IntegrationRunResult", None)
    inst = _wf_instance(dev_lane)
    if cls_ir is None or inst is None:
        _bad(label, "declared surface missing: IntegrationRunResult / "
                    "QuickmanualLaneWorkflow")
        return
    receipt_fn = _declared(inst, "_quick_gate_receipt", label + ".receipt")
    verdict_fn = _declared(inst, "_quick_gate_verdict", label + ".verdict")
    envred_fn = _declared(inst, "_tests_env_red_names", label + ".envred")
    if not (receipt_fn and verdict_fn and envred_fn):
        return

    def ir(**kw):
        base = dict(ran=1, passed=1, failed=0, env_fail=0, details=[],
                    error="", blockers=[], excluded_pools=[], excluded_count=0,
                    only_names=[])
        base.update(kw)
        try:
            return cls_ir(**base)
        except TypeError as e:
            _env(label + ".ctor", "IntegrationRunResult shape changed: %s" % e)
            return None

    narrowed = ir(only_names=["a", "b"])
    if narrowed is None:
        return
    # A1 narrowed receipt names the scope: the receipt consumes the DECLARED
    # scope (mode + names) and says what the round actually ran; the default
    # (no scope handed in) stays the full-registry face (A2).
    try:
        rec = _call(receipt_fn, narrowed, 1,
                    quick_scope={"mode": "scenario", "names": ["a", "b"]})
        summ = str(rec.get("summary", ""))
        if "narrowed by declaration: scenario=a,b" in summ:
            _ok("A1.receipt-names-scope: %s" % summ.split("|")[0].strip())
        else:
            _bad("A1.receipt-names-scope",
                 "summary does not name the declared scope verbatim: %r" % summ)
    except TypeError as e:
        _bad("A1.receipt-names-scope",
             "receipt does not accept the declared scope: %s" % e)
    except Exception as e:  # noqa: BLE001
        _bad("A1.receipt", "receipt face raised: %r" % (e,))
    # A1b a full gate DECLARED on purpose is named as a declaration, not an
    # accident (requirement 7: the full gate stays reachable on purpose).
    try:
        rec = _call(receipt_fn, ir(only_names=[]), 1,
                    quick_scope={"mode": "full", "names": ["integ"]})
        summ = str(rec.get("summary", ""))
        if "full registry (declared: check=integ)" in summ:
            _ok("A1b.declared-full-named")
        else:
            _bad("A1b.declared-full-named", "summary says: %r" % summ)
    except Exception as e:  # noqa: BLE001
        _bad("A1b.declared-full-named", "receipt face raised: %r" % (e,))
    # A2 full receipt says full registry
    try:
        rec = _call(receipt_fn, ir(only_names=[]), 1)
        summ = str(rec.get("summary", ""))
        if "full registry" in summ:
            _ok("A2.full-registry-named")
        else:
            _bad("A2.full-registry-named", "full summary says: %r" % summ)
    except Exception as e:  # noqa: BLE001
        _bad("A2.full", "receipt face raised: %r" % (e,))
    # A3 unresolved declaration = named product red, never env-red
    unresolved = ir(ran=0, passed=0, error="quick_scope_unresolved: scenario "
                                            "no_such_scenario is not in the registry",
                    only_names=["no_such_scenario"])
    try:
        if _call(verdict_fn, unresolved) == "red":
            _ok("A3.unresolved-is-red")
        else:
            _bad("A3.unresolved-is-red", "unresolved round judged %r"
                 % _call(verdict_fn, unresolved))
        env_names, _okc = _call(envred_fn, unresolved)
        if "no_such_scenario" not in [str(x) for x in (env_names or [])] and \
                not str(getattr(unresolved, "error")).lower().startswith("env"):
            _ok("A3.unresolved-outside-env-channel")
        else:
            _bad("A3.unresolved-outside-env-channel",
                 "unresolved leaked into the env-red channel: %r" % (env_names,))
    except Exception as e:  # noqa: BLE001
        _bad("A3.unresolved", "verdict face raised: %r" % (e,))


class _NoWorkflow:
    """Offline stub of the Temporal workflow seam: the args writer only consults
    workflow.patched(...) (replay switches) — answered False (old branch)."""

    @staticmethod
    def patched(*_a, **_k):
        return False


def leg_b_args_and_patch(dev_lane, agent_activities):
    """B: the single-writer args carry the declared scope; the full gate stays
    reachable; the narrowed path sits behind a declared patch id; old payloads
    default to the full round."""
    label = "B.args-single-writer"
    saved_wf = getattr(dev_lane, "workflow", None)
    dev_lane.workflow = _NoWorkflow
    try:
        return _leg_b_body(label, dev_lane, agent_activities)
    finally:
        dev_lane.workflow = saved_wf


def _leg_b_body(label, dev_lane, agent_activities):
    cls_args = getattr(agent_activities, "IntegrationRunArgs", None)
    inst = _wf_instance(dev_lane)
    if cls_args is None or inst is None:
        _bad(label, "declared surface missing: IntegrationRunArgs / workflow")
        return
    args_fn = _declared(inst, "_integ_run_args", label)
    if args_fn is None:
        return
    # B1 declared scenario scope reaches the single-writer args
    try:
        got = _call(args_fn, inst, only_names=["a", "b"]) if \
            _takes_inst(args_fn) else _call(args_fn, only_names=["a", "b"])
        if list(getattr(got, "only_names") or []) == ["a", "b"]:
            _ok("B1.args-carry-only-names")
        else:
            _bad("B1.args-carry-only-names", "only_names=%r"
                 % (getattr(got, "only_names", None),))
    except Exception as e:  # noqa: BLE001
        _bad("B1.args", "args face raised: %r" % (e,))
        return
    # B2 full gate: empty scope -> only_names == [] (the unchanged FULL round)
    try:
        got = _call(args_fn, inst) if _takes_inst(args_fn) else _call(args_fn)
        if list(getattr(got, "only_names") or []) == []:
            _ok("B2.full-round-default")
        else:
            _bad("B2.full-round-default", "only_names=%r"
                 % (getattr(got, "only_names", None),))
    except Exception as e:  # noqa: BLE001
        _bad("B2.full-round-default", "args face raised: %r" % (e,))
    # B3 replay safety: defaulted quick_scope + declared patch id
    try:
        kw_only = cls_args(ticket_id="t", worktree=REPO, attempt=1)
        if not (getattr(kw_only, "quick_scope", None) or {}):
            _ok("B3.quick_scope-defaults-empty")
        else:
            _bad("B3.quick_scope-defaults-empty",
                 "quick_scope defaults to %r" % (getattr(kw_only, "quick_scope", "?"),))
    except TypeError as e:
        _bad("B3.quick_scope-defaults-empty",
             "old payload shape no longer legal: %s" % e)
    except Exception as e:  # noqa: BLE001
        _env("B3.ctor", "IntegrationRunArgs ctor: %r" % (e,))
    pid = getattr(dev_lane, "QUICKMANUAL_SCOPE_PATCH_ID", None)
    if isinstance(pid, str) and pid.strip():
        _ok("B3.patch-id-declared: %s" % pid)
    else:
        _bad("B3.patch-id-declared",
             "QUICKMANUAL_SCOPE_PATCH_ID missing/empty (requirement 6)")


def _takes_inst(fn):
    import inspect
    try:
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        return len(params) >= 1 and params[0].name == "self"
    except (TypeError, ValueError):
        return False


def leg_c_scope_plan(shared):
    """C: the pure scope plan — scenario targets resolve against a registry,
    the reserved `integ` wins before the checks lookup, unknown targets are
    named in the error. The landed face returns (error, plan); plan carries
    mode / only_names / check / pytest_node / note."""
    label = "C.scope-plan"
    fn = _declared(shared, "quick_scope_plan", label)
    if fn is None:
        return
    registry = ["alpha", "beta", "gamma"]
    checks = ["py-compile", "lint"]

    def plan(kind, names, regs=registry, cks=checks, exists=lambda p: True):
        return _call(fn, kind, names, regs, cks, exists)

    # C1 declared scenario resolves
    try:
        err, p = plan("scenario", ["alpha", "beta"])
        if not err and p.get("mode") == "scenario" and \
                list(p.get("only_names") or []) == ["alpha", "beta"]:
            _ok("C1.scenario-resolves")
        else:
            _bad("C1.scenario-resolves", "got (%r, %r)" % (err, p))
    except Exception as e:  # noqa: BLE001
        _bad("C1.scenario-resolves", "raised: %r" % (e,))
    # C2 unknown scenario named in the error
    try:
        err, p = plan("scenario", ["alpha", "nope"])
        if err and "nope" in str(err) and not p:
            _ok("C2.unknown-named")
        else:
            _bad("C2.unknown-named", "got (%r, %r)" % (err, p))
    except Exception as e:  # noqa: BLE001
        _bad("C2.unknown-named", "raised: %r" % (e,))
    # C3 reserved full-gate token wins before the checks lookup (an empty
    # declared-checks list must NOT make it error)
    try:
        err, p = plan("check", ["integ"], cks=[])
        if not err and p.get("mode") == "full":
            _ok("C3.reserved-integ-full")
        else:
            _bad("C3.reserved-integ-full", "got (%r, %r)" % (err, p))
    except Exception as e:  # noqa: BLE001
        _bad("C3.reserved-integ-full", "raised: %r" % (e,))
    # C4 declared check resolves against the checks list
    try:
        err, p = plan("check", ["lint"])
        if not err and p.get("mode") == "check" and p.get("check") == "lint":
            _ok("C4.check-resolves")
        else:
            _bad("C4.check-resolves", "got (%r, %r)" % (err, p))
    except Exception as e:  # noqa: BLE001
        _bad("C4.check-resolves", "raised: %r" % (e,))
    # C5 battery target must exist (and stay a relative lane path)
    try:
        err, p = plan("l1_battery", ["no/such/file.py"], exists=lambda pth: False)
        if err and "no/such/file.py" in str(err):
            _ok("C5.battery-missing-named")
        else:
            _bad("C5.battery-missing-named", "got (%r, %r)" % (err, p))
    except Exception as e:  # noqa: BLE001
        _bad("C5.battery-missing-named", "raised: %r" % (e,))


def leg_d_verify_lane_only_check():
    """D: the named-check tool entry over a REAL fixture project — exactly the
    declared check runs, an unknown id is a named red, the reserved full-gate
    token is not shadowed, and the absent-params face is unchanged."""
    label = "D.verify-lane-only-check"
    sys.path.insert(0, os.path.join(REPO, "server", "tools"))
    try:
        import verify_lane  # noqa: E402
        from lib_env import no_narrowing_env  # noqa: E402 (L12: the in-process
        # tool face must not inherit the outer lane round's narrowing knobs)
    except Exception as e:  # noqa: BLE001
        _env(label, "verify_lane/lib_env unimportable: %r" % (e,))
        return
    if shutil.which("git") is None:
        _env(label, "git absent (fixture needs a real repo)")
        return
    root = tempfile.mkdtemp(prefix="t26102209-fixture-")
    try:
        with open(os.path.join(root, "verify.yaml"), "w") as f:
            f.write(
                "schema: v1\nlanes:\n  code:\n"
                "    write_allow: [src/]\n    checks:\n"
                "      - id: probe-ok\n        cmd: exit 0\n"
                "      - id: probe-red\n        cmd: exit 1\n")
        env = dict(os.environ)
        env.setdefault("GIT_AUTHOR_NAME", "fixture")
        env.setdefault("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
        env.setdefault("GIT_COMMITTER_NAME", "fixture")
        env.setdefault("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "commit", "-qm", "fixture"]):
            r = subprocess.run(cmd, cwd=root, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if r.returncode != 0:
                _env(label, "git fixture failed: %s" % r.stdout.decode()[:200])
                return
        # D1 exactly the declared check runs, green
        try:
            with no_narrowing_env():
                res = verify_lane.run({"lane": "code", "path": root,
                                       "only_check": "probe-ok"})
            checks = [c for c in (res.get("checks") or [])
                      if str(c.get("check", "")).startswith("probe")]
            if res.get("green") is True and \
                    [c.get("check") for c in checks] == ["probe-ok"] and \
                    checks[0].get("level") == "green":
                _ok("D1.only-check-runs-declared")
            else:
                _bad("D1.only-check-runs-declared", "res=%s" % json.dumps(res)[:400])
        except (KeyError, TypeError, ValueError) as e:
            _bad("D1.only-check-runs-declared",
                 "only_check not honored: %s" % e)
        except Exception as e:  # noqa: BLE001
            _env("D1", "verify_lane raised: %r" % (e,))
            return
        # D2 unknown id = named red
        try:
            with no_narrowing_env():
                res = verify_lane.run({"lane": "code", "path": root,
                                       "only_check": "no-such-check"})
            items = json.dumps(res)[:400]
            flat = json.dumps(res, ensure_ascii=False)
            if res.get("green") is not True and "no-such-check" in flat:
                _ok("D2.unknown-id-named-red")
            else:
                _bad("D2.unknown-id-named-red", "res=%s" % items)
        except (KeyError, TypeError, ValueError) as e:
            _bad("D2.unknown-id-named-red", "raised instead of named red: %s" % e)
        except Exception as e:  # noqa: BLE001
            _env("D2", "verify_lane raised: %r" % (e,))
            return
        # D3 the reserved full-gate token is not shadowed: verify.yaml declares
        # no check id `integ`, so only_check=integ must refuse BY NAME (the
        # full gate keeps its own workflow path, never this tool entry).
        try:
            with no_narrowing_env():
                res = verify_lane.run({"lane": "code", "path": root,
                                       "only_check": "integ"})
            flat = json.dumps(res, ensure_ascii=False)
            if res.get("green") is not True and "integ" in flat:
                _ok("D3.reserved-token-not-shadowed")
            else:
                _bad("D3.reserved-token-not-shadowed", "res=%s"
                     % json.dumps(res)[:400])
        except (KeyError, TypeError, ValueError) as e:
            _bad("D3.reserved-token-not-shadowed", "raised: %s" % e)
        # D4 absent params = the old face still runs the whole checks list
        try:
            with no_narrowing_env():
                res = verify_lane.run({"lane": "code", "path": root})
            names = sorted(str(c.get("check")) for c in (res.get("checks") or [])
                           if str(c.get("check", "")).startswith("probe"))
            if names == ["probe-ok", "probe-red"] and res.get("green") is False:
                _ok("D4.absent-params-old-face")
            else:
                _bad("D4.absent-params-old-face", "names=%r green=%r"
                     % (names, res.get("green")))
        except Exception as e:  # noqa: BLE001
            _bad("D4.absent-params-old-face", "old face raised: %r" % (e,))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    shared = _import_engine("shared")
    dev_lane = _import_engine("dev_lane")
    agent_activities = _import_engine("agent_activities")
    if shared is not None:
        leg_c_scope_plan(shared)
    if dev_lane is not None and agent_activities is not None:
        leg_a_receipt_and_verdict(dev_lane, agent_activities)
        leg_b_args_and_patch(dev_lane, agent_activities)
    leg_d_verify_lane_only_check()
    total = _PASS + _FAIL + _ENV
    if total == 0:
        print("ENV_FAIL: no leg produced a verdict (imports failed)")
        globals()["_ENV"] = _ENV + 1
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (_PASS, _FAIL, _ENV))
    if _ENV and not _FAIL:
        sys.exit(2)
    if _FAIL or _ENV:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
