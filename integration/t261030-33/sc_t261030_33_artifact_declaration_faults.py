#!/usr/bin/env python3
"""t261030-33 artifact declaration: the fault surface and the old face (grey-box L3).

Intent (the user-perceivable promise of the ticket): a malformed declaration is never
repaired and never blocks a stage; every refusal is named on a face a reader can reach;
an old receipt, an old worker's result dict and an old handoff keep working and keep
their existing values; the generic template face serves the same two keys with an
unknown round.

The declaration is agent-written external input. This entry is the adversarial face of
that input and of replay: the shapes a hurried agent writes (a bare string where a list
belongs, one junk element between good ones, an object without a source, a string
`deliverables`), a dict from an older worker (no new keys), and a corrupted handoff
history. None of them may raise, block, or change a red-green call.

Offline seconds: no Temporal server, no Docker, no browser, no console, never touches
3099/7233. The activity transport and the workflow clock are the only stubs; the intake,
the workflow copy, the handoff and the snapshot are the production code.

Intent split (no intent-level duplication): developer L1 owns the normalizer truth
table, the idempotence property and the copy-line locks; the positive journey of this
contract is the sibling entry sc_t261030_33_artifact_declaration_face.py; no earlier
scenario covers artifact descriptors.

Checks:
  F1 a non-list declaration is refused as a whole and named;
  F2 junk elements are refused by index, the good ones survive;
  F3 an unusable source is refused, the rest survive;
  F4 a string `deliverables` never becomes one artifact per character;
  F5 an old receipt is shape `absent`, nothing breaks;
  F6 an old worker's dict (no new keys) reads as absent and the legacy paths still show;
  F7 a corrupted handoff history never raises, every refusal is named;
  F8 the generic template face serves the two keys with an unknown round;
  F9 a refusal never changes the stage status or the gate surface;
  F10 the existing snapshot keys keep their values.

ENV_FAIL exit 2 when the engine modules cannot be imported.
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
        print("FAIL t261030-33-artifact-declaration-faults (%d): %s"
              % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    if ENVS:
        print("ENV_FAIL t261030-33-artifact-declaration-faults: %s" % "; ".join(ENVS))
        sys.exit(2)
    print("PASS t261030-33-artifact-declaration-faults")
    sys.exit(0)


try:
    import lib_artifact_face as rig
except Exception as e:  # noqa: BLE001
    env_fail("rig-import", "engine modules unimportable: %r" % (e,))
    summary()


def receipt(**kw):
    base = {"status": "ok", "summary": "s", "report": "r", "evidence": "e"}
    base.update(kw)
    return base


def one_char_sources(descs):
    return [d for d in descs if len(str(d.get("source") or "")) <= 1]


def main():
    with tempfile.TemporaryDirectory(prefix="sandbar-t261030-33-faults-") as td:
        # ---------------- F1: a non-list declaration ----------------
        wf1, res1, _b1, i1 = rig.chain(td, receipt(artifacts="out/x.png"))
        d1 = list(i1.artifact_descriptors or [])
        check("F1 non-list declaration refused as a whole",
              i1.artifact_descriptors_shape == "malformed"
              and d1 == []
              and any("not a list" in x for x in
                      (i1.artifact_descriptors_dropped or []))
              and one_char_sources(d1) == [],
              "shape=%r n=%d dropped=%r"
              % (i1.artifact_descriptors_shape, len(d1),
                 i1.artifact_descriptors_dropped))

        # ---------------- F2: junk elements between good ones ----------------
        payload2 = receipt(artifacts=[
            {"source": "out/good.md"}, 7, None, ["nested"], "",
            {"title": "no-source"}])
        _wf2, _r2, _b2, i2 = rig.chain(td, payload2)
        d2 = list(i2.artifact_descriptors or [])
        drops2 = list(i2.artifact_descriptors_dropped or [])
        check("F2 junk elements refused by index, good ones survive",
              len(d2) == 1 and d2[0].get("source") == "out/good.md"
              and len(drops2) == 5
              and all(any(x.startswith("%d:" % i) for x in drops2)
                      for i in (1, 2, 3, 4, 5)),
              "kept=%r drops=%r" % ([x.get("source") for x in d2], drops2))

        # ---------------- F3: an unusable source ----------------
        _wf3, _r3, _b3, i3 = rig.chain(
            td, receipt(artifacts=[{"source": ""}, {"source": 3},
                                   {"id": "no-source"}]))
        check("F3 unusable sources refused, none invented",
              list(i3.artifact_descriptors or []) == []
              and len(i3.artifact_descriptors_dropped or []) == 3,
              "descriptors=%r dropped=%r"
              % (i3.artifact_descriptors, i3.artifact_descriptors_dropped))

        # ---------------- F4: a string deliverables value ----------------
        wf4, res4, _b4, i4 = rig.chain(td, receipt(deliverables="out/x.png"))
        d4 = list(i4.artifact_descriptors or [])
        drops4 = list(i4.artifact_descriptors_dropped or [])
        results4 = wf4.results.get("create_plan") or {}
        check("F4 a string deliverables never becomes one artifact per character",
              one_char_sources(d4) == []
              and any("deliverables" in x for x in drops4)
              and results4.get("deliverables") == [],
              "descriptors=%r drops=%r deliverables=%r"
              % ([x.get("source") for x in d4], drops4,
                 results4.get("deliverables")))

        # ---------------- F5: an old receipt ----------------
        wf5, _res5, _b5, i5 = rig.chain(td, receipt(deliverables=["out/old.md"]))
        check("F5 old receipt reads as absent",
              i5.artifact_descriptors_shape == "absent"
              and list(i5.artifact_descriptors or []) == []
              and i5.artifact_descriptors_dropped == [],
              "shape=%r" % (i5.artifact_descriptors_shape,))

        # ---------------- F6: an old worker's dict (no new keys) ----------------
        old_boundary = {"status": "ok", "summary": "s", "report": "r",
                        "deliverables": ["out/old.md"], "files_changed": [],
                        "evidence": "e"}
        wf6, res6 = rig.drive_step(old_boundary, gens={"create_plan": 1})
        results6 = wf6.results.get("create_plan") or {}
        rig.handoff(wf6, "create_plan", res6)
        entry6 = (wf6.meta.get("handoffs") or [{}])[0]
        face6 = list(rig.snap(wf6).get("artifact_descriptors") or [])
        check("F6 old worker dict reads as absent, legacy paths still show",
              results6.get("artifact_descriptors") == []
              and results6.get("artifact_descriptors_shape") == "absent"
              and "artifact_descriptors" not in entry6
              and [d.get("source") for d in face6] == ["out/old.md"]
              and face6 and face6[0].get("legacy") is True,
              "results=%r entry_keys=%r face=%r"
              % (results6.get("artifact_descriptors"), sorted(entry6.keys()),
                 [d.get("source") for d in face6]))

        # ---------------- F7: a corrupted handoff history ----------------
        corrupt = rig.shell(rig.dev_lane.DevLaneWorkflow, stage="a")
        corrupt.meta["handoffs"] = [
            {"stage": "a", "artifacts": ["x.png"], "artifact_descriptors": "junk"},
            {"stage": "b", "artifacts": [],
             "artifact_descriptors": [{"source": "ok.md"}, 7]},
            {"stage": "c", "artifacts": "junk"},
        ]
        try:
            face7 = rig.snap(corrupt)
            drops7 = list(face7.get("artifact_descriptors_dropped") or [])
            descs7 = list(face7.get("artifact_descriptors") or [])
            named = all(any(x.startswith("[%s]" % s) for x in drops7)
                        for s in ("a", "b", "c"))
            check("F7 corrupted handoff never raises and is named",
                  named and [d.get("source") for d in descs7] == ["ok.md"],
                  "drops=%r descs=%r" % (drops7, descs7))
        except Exception as e:  # noqa: BLE001
            check("F7 corrupted handoff never raises and is named", False,
                  "snapshot raised: %r" % (e,))

        # ---------------- F8: the generic template face ----------------
        bw = rig.shell(rig.base.TicketWorkflowBase)
        st = rig.dev_lane.DevLaneWorkflow.STAGES[0]
        bw.results[st.id] = {"artifact_descriptors": [rig.descriptor(
            receipt_id="a", title="A", kind="text", source="docs/a.md",
            legacy=False, kind_known=True, round=None)]}
        bw._handoff(st, "s", artifacts=["docs/a.md", "docs/extra.md"])
        base_face = rig.snap(bw)
        base_descs = list(base_face.get("artifact_descriptors") or [])
        check("F8 generic template serves the two keys, round unknown",
              len(base_descs) == 1
              and base_descs[0].get("round") is None
              and base_descs[0].get("stage") == st.id
              and "artifact_descriptors_dropped" in base_face
              and [d.get("source") for d in base_descs] == ["docs/a.md"],
              "descriptors=%r" % (base_descs,))

        # ---------------- F9: a refusal never blocks ----------------
        blocked = any(k in (wf1.meta or {}) for k in
                      ("blocked_reason", "blocked_detail"))
        check("F9 a refused declaration never changes status or the gate surface",
              res1.status == "ok" and not blocked and wf1.gate_runs == []
              and res4.status == "ok",
              "status=%r blocked=%r gate_runs=%r"
              % (res1.status, blocked, wf1.gate_runs))

        # ---------------- F10: existing keys keep their values ----------------
        face5 = rig.snap(wf5)
        check("F10 existing snapshot keys keep their values",
              face5.get("stage") == wf5.meta.get("stage")
              and face5.get("stage_state") == wf5.meta.get("stage_state")
              and face5.get("results") == wf5.results
              and face5.get("handoffs") == wf5.meta.get("handoffs")
              and all(isinstance(p, str) for h in (face5.get("handoffs") or [])
                      for p in (h.get("artifacts") or [])),
              "stage=%r results_match=%r"
              % (face5.get("stage"), face5.get("results") == wf5.results))


try:
    main()
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAILS.append("rig-crash:%r" % (e,))
summary()
