#!/usr/bin/env python3
"""t261030-33 artifact declaration: the served ticket face (grey-box L3, offline).

Intent (the user-perceivable promise of the ticket): a stage that declares what it
produced reaches the snapshot the console reads, and a stage that declares nothing
still shows its old path list as guessed descriptors. The declaration is carried
verbatim; the engine only adds what it must (stage row, round, the legacy and
kind-known labels).

Why an integration entry: the units of this change are the normalizer, the intake,
the workflow copy and the aggregator, and the ticket's risk lives BETWEEN them - a
declaration can be normalized and then lost at the activity boundary (the dict the
workflow receives carries StageResult field names, not the receipt key). Developer
L1 pins each unit (the normalizer truth table, the idempotence property, the copy
lines, the aggregator cases); THIS entry drives the assembled chain once, end to
end, and serves the public snapshot:

  receipt file -> REAL intake (_read_result) -> boundary dict -> REAL workflow copy
  (_run_agent_step over a stubbed activity seam) -> REAL _handoff -> REAL snapshot()

Offline seconds: no Temporal server, no Docker, no browser, no console, never
touches 3099/7233. The stubbed seams are the activity transport and the workflow
clock; no production rule is re-implemented here.

Intent split (no intent-level duplication): L1 owns the pure-function truth tables
and the per-site parity; the legacy-replay and malformed-input faces of this same
contract are the sibling entry
sc_t261030_33_artifact_declaration_faults.py; no earlier scenario covers artifact
descriptors (checked against the registry intents).

Checks:
  A  the declared journey: values verbatim, duplicate ids kept, bare strings
     accepted, the boundary dict carries the three keys, the workflow copy and the
     handoff carry the same list, and the snapshot serves it with stage + round;
  A9 a declaring stage's old path list is NOT mirrored into the artifact cards (the
     paths stay in handoffs[].artifacts);
  A10 the snapshot is deterministic and writes nothing;
  A11 the query body calls no SDK gate;
  B  an old ticket (paths only) shows guessed descriptors, round 1, and an unknown
     round when several entries cannot be labelled from one counter;
  C  the light lane inherits the writer: its ui_evidence paths appear as legacy
     image descriptors, and its existing face keys are unchanged;
  D  the existing face keys keep their values and handoffs[].artifacts stays a list
     of strings.

ENV_FAIL exit 2 when the engine modules cannot be imported (no temporalio in the
selected interpreter) - that is the deployment reality being guarded.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

PASS = 0
FAILS = []
ENVS = []


def check(name, cond, why=""):
    global PASS
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s: %s" % (name, why))


def env_fail(name, why):
    ENVS.append(name)
    print("ENV_FAIL %s: %s" % (name, why))


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASS, len(FAILS), len(ENVS)))
    if FAILS:
        print("FAIL t261030-33-artifact-declaration-face (%d): %s"
              % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    if ENVS:
        print("ENV_FAIL t261030-33-artifact-declaration-face: %s" % "; ".join(ENVS))
        sys.exit(2)
    print("PASS t261030-33-artifact-declaration-face")
    sys.exit(0)


try:
    import lib_artifact_face as rig
except Exception as e:  # noqa: BLE001 - the import chain is the deployment reality
    env_fail("rig-import", "engine modules unimportable: %r" % (e,))
    summary()

LONG_TITLE = "L" * 400

DECLARED_PAYLOAD = {
    "status": "ok", "summary": "plan done", "report": "r", "evidence": "e",
    "files_changed": [],
    "deliverables": ["out/plan.md", "out/extra.md"],
    "artifacts": [
        {"id": "plan-main", "title": LONG_TITLE, "kind": "hologram",
         "source": "out/plan.md", "repo": "fpv-parts", "stage": "pi-model",
         "note": "gate 7/12 pending", "open": "open with Studio",
         "shape": "units[]", "optional": True},
        {"id": "dup", "title": "One", "kind": "text", "source": "out/one.md"},
        {"id": "dup", "title": "Two", "kind": "text", "source": "out/two.md"},
        "out/shot.png",
        "out/data.json",
    ],
}


def by_source(descs):
    return {d.get("source"): d for d in descs}


def main():
    with tempfile.TemporaryDirectory(prefix="sandbar-t261030-33-face-") as td:
        # ---------------- A: the declared journey ----------------
        wf, res, boundary, intake_res = rig.chain(td, DECLARED_PAYLOAD)
        intake = list(intake_res.artifact_descriptors or [])

        check("A1 receipt recognized",
              intake_res.artifact_descriptors_shape == "ok"
              and len(intake) == 5
              and intake_res.artifact_descriptors_dropped == [],
              "shape=%r n=%d dropped=%r"
              % (intake_res.artifact_descriptors_shape, len(intake),
                 intake_res.artifact_descriptors_dropped))

        first = intake[0] if intake else {}
        check("A2 declared values verbatim",
              first.get("id") == "plan-main"
              and len(first.get("title") or "") == 400
              and first.get("kind") == "hologram"
              and first.get("kind_known") is False
              and first.get("repo") == "fpv-parts"
              and first.get("stage") == "pi-model"
              and first.get("note") == "gate 7/12 pending"
              and first.get("open") == "open with Studio"
              and first.get("shape") == "units[]"
              and first.get("optional") is True
              and first.get("legacy") is False,
              "first descriptor=%r" % (first,))

        check("A3 duplicate declared ids kept",
              len(intake) >= 3 and intake[1].get("id") == "dup"
              and intake[2].get("id") == "dup",
              "ids=%r" % ([d.get("id") for d in intake[:3]],))

        strings = [d for d in intake if d.get("legacy") is True]
        check("A4 bare path strings accepted",
              len(strings) == 2
              and [d.get("kind") for d in strings] == ["image", "structure"]
              and all(d.get("id") and d.get("title") for d in strings),
              "legacy entries=%r" % (strings,))

        check("A5 activity boundary carries the three keys",
              isinstance(boundary, dict)
              and boundary.get("artifact_descriptors") == intake
              and boundary.get("artifact_descriptors_shape") == "ok"
              and boundary.get("artifact_descriptors_dropped") == [],
              "boundary keys=%r" % (sorted((boundary or {}).keys())[:6],))

        results = (wf.results.get("create_plan") or {})
        check("A6 workflow copy keeps the declaration",
              results.get("artifact_descriptors") == intake
              and results.get("artifact_descriptors_shape") == "ok"
              and results.get("artifact_descriptors_dropped") == [],
              "results descriptors=%r" % (results.get("artifact_descriptors"),))

        rig.handoff(wf, "create_plan", res)
        entry = (wf.meta.get("handoffs") or [{}])[0]
        check("A7 handoff carries the declaration, paths unchanged",
              entry.get("artifact_descriptors") == intake
              and entry.get("artifacts") == ["out/plan.md", "out/extra.md"],
              "handoff=%r" % ({k: entry.get(k) for k in
                               ("artifacts", "artifact_descriptors")},))

        face = rig.snap(wf)
        served = list(face.get("artifact_descriptors") or [])
        check("A8 snapshot serves the declared list with stage and round",
              len(served) == 5
              and [d.get("source") for d in served] ==
              ["out/plan.md", "out/one.md", "out/two.md",
               "out/shot.png", "out/data.json"]
              and served[0].get("stage") == "pi-model"
              and all(d.get("stage") == "create_plan" for d in served[1:])
              and all(d.get("round") == 1 for d in served)
              and face.get("artifact_descriptors_dropped") == [],
              "served=%r" % ([{k: d.get(k) for k in ("source", "stage", "round")}
                              for d in served],))

        sources = {d.get("source") for d in served}
        check("A9 declaring stage's old paths are not mirrored",
              "out/extra.md" not in sources
              and entry.get("artifacts") == ["out/plan.md", "out/extra.md"],
              "sources=%r entry paths=%r" % (sources, entry.get("artifacts")))

        before = json.dumps(wf.meta, sort_keys=True, default=str)
        face_a = rig.snap(wf)
        face_b = rig.snap(wf)
        after = json.dumps(wf.meta, sort_keys=True, default=str)
        check("A10 snapshot deterministic and read-only",
              face_a.get("artifact_descriptors") == face_b.get("artifact_descriptors")
              and before == after,
              "deterministic=%r meta_stable=%r"
              % (face_a.get("artifact_descriptors") == face_b.get("artifact_descriptors"),
                 before == after))

        rig.install_stub(rig.stub_workflow(patched_raises=True))
        try:
            rig.snap(wf)
            gate_free = True
        except Exception as e:  # noqa: BLE001
            gate_free = False
            print("  snapshot raised under a gate probe: %r" % (e,))
        rig.install_stub(rig.stub_workflow())
        check("A11 query body calls no SDK gate", gate_free,
              "the snapshot query reached workflow.patched")

        # ---------------- B: an old ticket (paths only) ----------------
        paths = ["out/plan.md", "out/shot.png", "out/data.json",
                 "out/change.diff", "out/tool.bin"]
        old = rig.shell(rig.dev_lane.DevLaneWorkflow,
                        gens={"create_plan": 1}, stage="create_plan")
        old.meta["handoffs"].append({"stage": "create_plan", "agent_id": "",
                                     "summary": "s", "report": "",
                                     "artifacts": list(paths), "ts": 0,
                                     "engine_version": 2})
        old_face = rig.snap(old)
        old_descs = list(old_face.get("artifact_descriptors") or [])
        check("B1 legacy paths become guessed descriptors",
              [d.get("source") for d in old_descs] == paths
              and [d.get("kind") for d in old_descs] ==
              ["text", "image", "structure", "diff", "external"]
              and all(d.get("legacy") is True for d in old_descs)
              and all(d.get("stage") == "create_plan" for d in old_descs)
              and all(d.get("round") == 1 for d in old_descs),
              "legacy descriptors=%r"
              % ([{k: d.get(k) for k in ("source", "kind", "legacy", "round")}
                  for d in old_descs],))

        two = rig.shell(rig.dev_lane.DevLaneWorkflow,
                        gens={"create_plan": 2}, stage="create_plan")
        for _ in range(2):
            two.meta["handoffs"].append({"stage": "create_plan", "agent_id": "",
                                         "summary": "s", "report": "",
                                         "artifacts": ["out/round-a.md"], "ts": 0,
                                         "engine_version": 2})
        two_descs = list(rig.snap(two).get("artifact_descriptors") or [])
        check("B2 an unlabelable round is unknown, never a guessed number",
              len(two_descs) == 2 and all(d.get("round") is None for d in two_descs),
              "rounds=%r" % ([d.get("round") for d in two_descs],))

        gen = rig.shell(rig.dev_lane.DevLaneWorkflow,
                        gens={"create_plan": 1}, stage="create_plan")
        gen.meta["handoffs"].append({"stage": "create_plan", "agent_id": "",
                                     "summary": "s", "report": "",
                                     "artifacts": [], "gen": 3, "ts": 0,
                                     "engine_version": 2,
                                     "artifact_descriptors": [
                                         rig.descriptor(source="docs/a.md")]})
        gen_descs = list(rig.snap(gen).get("artifact_descriptors") or [])
        check("B3 an entry's own gen wins (the exact round)",
              len(gen_descs) == 1 and gen_descs[0].get("round") == 3,
              "round=%r" % ([d.get("round") for d in gen_descs],))

        # ---------------- C: the light lane inherits the writer ----------------
        light = rig.shell(rig.light_lane.LightLaneWorkflow,
                          gens={"ui_evidence": 1}, stage="ui_evidence")
        light._handoff("ui_evidence", "UI evidence",
                       artifacts=["shots/a.png", "shots/b.png"])
        light_face = rig.snap(light)
        light_descs = list(light_face.get("artifact_descriptors") or [])
        check("C1 light-lane ui_evidence paths appear as legacy images",
              [d.get("source") for d in light_descs] ==
              ["shots/a.png", "shots/b.png"]
              and all(d.get("kind") == "image" for d in light_descs)
              and all(d.get("legacy") is True for d in light_descs)
              and all(d.get("stage") == "ui_evidence" for d in light_descs),
              "light descriptors=%r" % (light_descs,))

        check("C2 light-lane existing face keys unchanged",
              light_face.get("template_id") == "light-lane"
              and light_face.get("stage") == "ui_evidence"
              and light_face.get("handoffs") == light.meta.get("handoffs"),
              "template=%r stage=%r"
              % (light_face.get("template_id"), light_face.get("stage")))

        # ---------------- D: the existing face keeps its values ----------------
        check("D1 existing snapshot keys and path list unchanged",
              face.get("stage") == wf.meta.get("stage")
              and face.get("stage_state") == wf.meta.get("stage_state")
              and face.get("results") == wf.results
              and face.get("handoffs") == wf.meta.get("handoffs")
              and all(isinstance(p, str) for p in (entry.get("artifacts") or [])),
              "stage=%r results_match=%r"
              % (face.get("stage"), face.get("results") == wf.results))


try:
    main()
except Exception as e:  # noqa: BLE001 - a rig crash is a FAIL to investigate
    import traceback
    traceback.print_exc()
    FAILS.append("rig-crash:%r" % (e,))
summary()
