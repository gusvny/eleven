#!/usr/bin/env python3
"""t261030-33 (epic artifact-face, engine slice): a stage declares what it produced.

Engine-side contract: a stage may put a structured `artifacts` list in its result file,
next to the legacy `deliverables` paths; the engine carries the declaration into the
ticket snapshot under the additive keys `artifact_descriptors` /
`artifact_descriptors_dropped`, and the legacy paths become descriptors there too.
Nothing is rendered, archived or gated here.

Coverage map:
  A. the normalizer (pure): values the stage wrote are carried verbatim, string entries
     become legacy descriptors, only unformable entries are refused (by index, by name),
     the deliverables guard is minimal, the function is idempotent and mutates nothing;
  B. the seam: `_read_result` is the ONE reader of the receipt (behavior tests with
     receipt fixtures); the two workflow sites copy the three keys and never normalize
     (source lock, the repo's precedent in test_t260917_08_env_fail_signal.py);
  C. the handoff: derived from the stage's own results entry (no call-site argument), and
     absent when the stage declared nothing — so today's entry shape is unchanged;
  D. the aggregator and the snapshot: stored descriptors are trusted, a stage's paths are
     never mirrored behind its declaration, the round is 1-based with a named unknown case,
     the two dropped channels stay separate, and every old key keeps its value;
  E. visibility: a refused declaration leaves one log line;
  F. scope: a refused declaration never changes a status or a gate verdict, and the new
     code adds no timer, no spawn and no fd.
"""

import datetime
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities  # noqa: E402
import base  # noqa: E402
import dev_lane  # noqa: E402
import light_lane  # noqa: E402
import shared  # noqa: E402

NOW = datetime.datetime(2026, 10, 30, 12, 0, 0)
_NOOP = lambda *a, **k: None  # noqa: E731


def _log_ns():
    return SimpleNamespace(info=_NOOP, warning=_NOOP, warn=_NOOP)


# ---------------------------------------------------------------------------
# fixtures: engine shells, no Temporal runtime, no real agent, no network
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_temporal(monkeypatch):
    """Both workflow modules see a fake SDK for the whole module (restored by pytest)."""
    ns = SimpleNamespace(now=lambda: NOW, logger=_log_ns(), patched=lambda pid: True,
                         wait_condition=lambda *a, **k: None)
    monkeypatch.setattr(dev_lane, "workflow", ns)
    monkeypatch.setattr(base, "workflow", ns)


def _dev_shell(results=None, gens=None, meta=None, cls=None):
    wf = object.__new__(cls or dev_lane.DevLaneWorkflow)
    wf.meta = dict(meta or {"stage": "implement", "handoffs": [], "log": []})
    wf.results = dict(results or {})
    wf.timeline = []
    wf.refused = []
    wf.signatures = {}
    wf.gate_runs = []
    wf.human_context = {}
    wf._retry_token = 0
    wf._gens = dict(gens or {})
    wf._ledger_marks = []
    wf._detail_face_on = True
    wf.engine_version = 2
    wf.ticket_id = "t-ut"
    return wf


def _base_shell(results=None, meta=None):
    wf = object.__new__(base.TicketWorkflowBase)
    wf.meta = dict(meta or {"stage": "implement", "handoffs": [], "log": []})
    wf.results = dict(results or {})
    wf.timeline = []
    wf.refused = []
    wf.signatures = {}
    wf.gate_runs = []
    wf.human_context = {}
    wf._retry_token = 0
    wf.engine_version = 2
    wf.ticket_id = "t-ut"
    wf.template_id = "generic"
    return wf


def _receipt(tmp_path, doc, stage="implement"):
    p = tmp_path / "result.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return agent_activities._read_result(p, stage)


def _declared(**over):
    doc = {"source": "out/pic.png", "id": "pic", "title": "The picture", "kind": "image",
           "note": "n", "repo": "r", "stage": "implement", "open": "with Studio",
           "shape": "units[]", "optional": True}
    doc.update(over)
    return doc


# ---------------------------------------------------------------------------
# A. the normalizer (pure)
# ---------------------------------------------------------------------------

def test_a1_declared_values_are_carried_verbatim():
    long_title = "T" * 400
    descs, shape, dropped = shared.normalize_artifacts(
        [_declared(title=long_title, kind="weird", stage="other-stage")], stage="implement")
    assert shape == "ok" and dropped == []
    d = descs[0]
    assert d["title"] == long_title                      # no truncation
    assert d["kind"] == "weird" and d["kind_known"] is False
    assert d["stage"] == "other-stage"                   # a foreign stage is carried, not corrected
    assert d["id"] == "pic" and d["optional"] is True and d["legacy"] is False


def test_a2_no_cap_and_no_rename():
    entries = [_declared(id="same", source="out/%d.png" % i) for i in range(120)]
    descs, shape, dropped = shared.normalize_artifacts(entries, stage="implement")
    assert shape == "ok" and len(descs) == 120 and dropped == []
    # a duplicate id is kept as declared (the engine never invents a new one)
    dup, _, _ = shared.normalize_artifacts(
        [_declared(id="same", source="a.png"), _declared(id="same", source="b.png")],
        stage="implement")
    assert [d["id"] for d in dup] == ["same", "same"]
    assert [d["source"] for d in dup] == ["a.png", "b.png"]


def test_a3_string_entries_become_legacy_descriptors():
    descs, shape, dropped = shared.normalize_artifacts(["out/pic.png", "notes/a.md"], stage="impl")
    assert shape == "ok" and dropped == []
    assert [d["kind"] for d in descs] == ["image", "text"]
    assert all(d["legacy"] is True and d["stage"] == "impl" for d in descs)
    assert descs[0]["id"] == shared.artifact_id_from_path("out/pic.png")


def test_a4_mixed_list_keeps_order_and_accepts_both_shapes():
    descs, shape, _ = shared.normalize_artifacts(
        [_declared(id="declared"), "out/x.glb"], stage="impl")
    assert shape == "ok"
    assert [d["id"] for d in descs] == ["declared", shared.artifact_id_from_path("out/x.glb")]
    assert descs[1]["kind"] == "external" and descs[1]["legacy"] is True


def test_a5_non_list_declaration_is_refused_as_a_whole():
    for bad in ("out/x.png", {"source": "x"}, 7):
        descs, shape, dropped = shared.normalize_artifacts(bad, stage="impl")
        assert descs == [] and shape == "malformed" and len(dropped) == 1
        assert "refused as a whole" in dropped[0]
    # a bare string is never iterated character by character
    descs, _, dropped = shared.normalize_artifacts("out/x.png", stage="impl")
    assert descs == [] and "str" in dropped[0]


def test_a6_wrong_type_elements_are_refused_by_index():
    descs, shape, dropped = shared.normalize_artifacts(
        [7, None, ["nested"], "out/ok.png"], stage="impl")
    assert shape == "ok" and [d["source"] for d in descs] == ["out/ok.png"]
    assert [line.split(":")[0] for line in dropped] == ["0", "1", "2"]


def test_a7_entry_without_a_usable_source_is_refused():
    descs, shape, dropped = shared.normalize_artifacts(
        [{"title": "no source"}, {"source": "   "}, {"source": 7}, _declared()], stage="impl")
    assert shape == "ok" and len(descs) == 1 and descs[0]["id"] == "pic"
    assert len(dropped) == 3 and all("source" in line for line in dropped)


def test_a8_wrongly_typed_optional_fields_fall_back():
    descs, _, _ = shared.normalize_artifacts(
        [{"source": "out/x.png", "id": 7, "title": 9, "kind": 3, "optional": "yes",
          "repo": 1, "note": None}], stage="impl")
    d = descs[0]
    assert d["id"] == shared.artifact_id_from_path("out/x.png")
    assert d["title"] == "x.png" and d["kind"] == "image"
    assert d["optional"] is False and d["repo"] == "" and d["note"] == ""


def test_a9_deliverables_guard_is_minimal():
    # a list keeps today's coercion verbatim (padding, blanks, numbers included)
    assert shared.normalize_deliverables([" b.py ", "", 7]) == ([" b.py ", "", "7"], "ok")
    assert shared.normalize_deliverables(None) == ([], "absent")
    # only the shape-destroying form is refused, and it is named by the reader
    assert shared.normalize_deliverables("out/x.png") == ([], "malformed")


def test_a10_declared_entries_are_not_merged_here():
    # the merge with the legacy path list happens at the snapshot, never in the normalizer
    descs, _, _ = shared.normalize_artifacts([_declared(source="out/pic.png")], stage="impl")
    assert [d["source"] for d in descs] == ["out/pic.png"] and descs[0]["legacy"] is False


def test_a11_determinism_and_input_immutability():
    raw = [_declared(), "out/x.png", 7]
    snapshot_copy = json.loads(json.dumps(raw))
    first = shared.normalize_artifacts(raw, stage="impl")
    second = shared.normalize_artifacts(raw, stage="impl")
    assert first == second
    assert raw == snapshot_copy                      # the input objects are not mutated


def test_a12_normalizer_is_idempotent():
    declared, _, _ = shared.normalize_artifacts([_declared()], stage="impl")
    again, _, _ = shared.normalize_artifacts(declared, stage="impl")
    assert again == declared                         # kind_known / legacy / round carried as stored
    legacy, _, _ = shared.normalize_artifacts(["out/pic.png"], stage="impl")
    legacy_again, _, _ = shared.normalize_artifacts(legacy, stage="impl")
    assert legacy_again == legacy and legacy_again[0]["legacy"] is True


# ---------------------------------------------------------------------------
# B. the seam: one reader, two copiers
# ---------------------------------------------------------------------------

def test_b13_read_result_keeps_existing_fields_and_adds_artifacts(tmp_path):
    res = _receipt(tmp_path, {
        "status": "ok", "summary": "s", "report": "r",
        "deliverables": ["out/a.png"],
        "files_changed": ["server/x.py"],
        "env_fail": True, "env_reason": "sandbox deny",
        "handover_runs": [{"name": "a", "cmd": "pytest -q"}],
        "handover_dropped": ["old drop"],
        "integration_violations": [{"cmd": "x", "entry": "y", "segment": "z", "seq": 1}],
        "integration_scan_note": "scan note",
        "artifacts": [_declared()],
    })
    assert res is not None
    # every pre-existing field keeps its value (parity at the one normalizing site)
    assert res.deliverables == ["out/a.png"] and res.files_changed == ["server/x.py"]
    assert res.files_changed_shape == "ok"
    assert res.env_fail is True and res.env_reason == "sandbox deny"
    assert res.handover_runs == [{"name": "a", "cmd": "pytest -q", "syntax_bad": False}]
    assert res.handover_dropped == ["old drop"]
    assert res.integration_violations == [{"cmd": "x", "entry": "y", "segment": "z",
                                            "seq": "1"}]   # values are strings (as today)
    assert res.integration_scan_note == "scan note"
    # and the declaration arrives
    assert res.artifact_descriptors_shape == "ok"
    assert [d["id"] for d in res.artifact_descriptors] == ["pic"]
    assert res.artifact_descriptors_dropped == []


def test_b14_old_receipt_reads_as_absent(tmp_path):
    res = _receipt(tmp_path, {"status": "ok", "summary": "old", "deliverables": ["out/a.png"]})
    assert res is not None
    assert res.artifact_descriptors == [] and res.artifact_descriptors_shape == "absent"
    assert res.artifact_descriptors_dropped == [] and res.deliverables == ["out/a.png"]


def test_b15_malformed_deliverables_is_named_not_char_iterated(tmp_path):
    res = _receipt(tmp_path, {"status": "ok", "deliverables": "out/x.png"})
    assert res is not None
    assert res.deliverables == []                    # no single-character fake paths
    assert len(res.artifact_descriptors_dropped) == 1
    assert "deliverables" in res.artifact_descriptors_dropped[0]


def test_b16_workflow_sites_copy_and_never_normalize():
    for name in ("base.py", "dev_lane.py"):
        src = (Path(agent_activities.__file__).resolve().parent / name).read_text("utf-8")
        assert "copy_artifact_descriptors(raw)" in src, name
        assert 'normalize_artifacts(raw.get("artifacts")' not in src, name
        assert 'raw.get("artifacts")' not in src, name
        assert '"artifact_descriptors_dropped"' in src, name


def test_b17_copy_helper_absent_defaults_and_refusals():
    assert shared.copy_artifact_descriptors(None) == ([], "absent", [])
    assert shared.copy_artifact_descriptors({"status": "ok"}) == ([], "absent", [])
    descs, shape, dropped = shared.copy_artifact_descriptors({
        "artifact_descriptors": [{"id": "a", "source": "x"}],
        "artifact_descriptors_shape": "ok",
        "artifact_descriptors_dropped": ["line"]})
    assert [d["id"] for d in descs] == ["a"] and shape == "ok" and dropped == ["line"]
    _, shape2, dropped2 = shared.copy_artifact_descriptors(
        {"artifact_descriptors": "nope", "artifact_descriptors_shape": "bogus"})
    assert shape2 == "absent" and len(dropped2) == 1


# ---------------------------------------------------------------------------
# C. the handoff record
# ---------------------------------------------------------------------------

_ART = {"id": "pic", "title": "The picture", "kind": "image", "kind_known": True,
        "source": "out/pic.png", "repo": "", "stage": "implement", "note": "",
        "open": "", "shape": "", "optional": False, "legacy": False, "round": None}


def test_c17_handoff_carries_the_declaration_from_results():
    wf = _dev_shell(results={"implement": {"artifact_descriptors": [dict(_ART)]}})
    dev_lane.DevLaneWorkflow._handoff(wf, "implement", "done", artifacts=["out/pic.png"])
    entry = wf.meta["handoffs"][-1]
    assert entry["artifact_descriptors"] == [dict(_ART)]
    assert entry["artifacts"] == ["out/pic.png"]     # the legacy path list is unchanged


def test_c18_handoff_without_a_declaration_writes_no_key():
    wf = _dev_shell(results={"merge": {"status": "ok", "deliverables": ["x"]}})
    dev_lane.DevLaneWorkflow._handoff(wf, "merge", "merged", artifacts=["x"])
    entry = wf.meta["handoffs"][-1]
    assert "artifact_descriptors" not in entry
    assert set(entry) == {"stage", "agent_id", "summary", "report", "artifacts", "ts",
                          "engine_version", "gen"}


def test_c19_base_handoff_keys_results_by_stage_id():
    wf = _base_shell(results={"implement": {"artifact_descriptors": [dict(_ART)]}})
    base.TicketWorkflowBase._handoff(wf, SimpleNamespace(id="implement"), "done",
                                     artifacts=["out/pic.png"])
    entry = wf.meta["handoffs"][-1]
    assert entry["stage"] == "implement" and entry["artifact_descriptors"] == [dict(_ART)]
    src = (Path(base.__file__)).read_text("utf-8")
    handoff = src.split("def _handoff(", 1)[1].split("def _apply_rework", 1)[0]
    assert ".get(st.id)" in handoff and "step_id" not in handoff


def test_c20_light_lane_inherits_the_derivation():
    # implement: the declaration is carried although the light lane passes only paths
    wf = _dev_shell(cls=light_lane.LightLaneWorkflow,
                    results={"implement": {"artifact_descriptors": [dict(_ART)]}})
    light_lane.LightLaneWorkflow._handoff(wf, "implement", "landed",
                                          artifacts=["out/pic.png"])
    assert wf.meta["handoffs"][-1]["artifact_descriptors"] == [dict(_ART)]
    # ui_evidence: the conditional record has no declaration → no key, the paths stay
    wf2 = _dev_shell(cls=light_lane.LightLaneWorkflow,
                     results={"ui_evidence": {"deliverables": ["shot.png"]}})
    light_lane.LightLaneWorkflow._handoff(wf2, "ui_evidence", "ui", artifacts=["shot.png"])
    assert "artifact_descriptors" not in wf2.meta["handoffs"][-1]


# ---------------------------------------------------------------------------
# D. the aggregator and the snapshot
# ---------------------------------------------------------------------------

def test_d22_aggregator_trusts_stored_descriptors():
    stored = dict(_ART, stage="", round=None, legacy=True, kind_known=False)
    out, dropped = shared.snapshot_artifact_descriptors(
        [{"stage": "implement", "artifact_descriptors": [stored], "gen": 2}])
    assert dropped == []
    assert out[0]["stage"] == "implement" and out[0]["round"] == 2
    assert out[0]["legacy"] is True and out[0]["kind_known"] is False   # labels not flipped


def test_d23_round_is_one_based_and_named_when_unknown():
    arts, _ = shared.snapshot_artifact_descriptors(
        [{"stage": "implement", "artifact_descriptors": [dict(_ART)], "gen": 3}])
    assert arts[0]["round"] == 3
    arts, _ = shared.snapshot_artifact_descriptors(
        [{"stage": "implement", "artifact_descriptors": [dict(_ART)]}],
        rounds={"implement": 1})
    assert arts[0]["round"] == 1                     # one entry → the current counter is it
    arts, _ = shared.snapshot_artifact_descriptors(
        [{"stage": "implement", "artifact_descriptors": [dict(_ART)]},
         {"stage": "implement", "artifact_descriptors": [dict(_ART)]}],
        rounds={"implement": 2})
    assert [a["round"] for a in arts] == [None, None]  # several entries → unknown, not guessed
    arts, _ = shared.snapshot_artifact_descriptors(
        [{"stage": "implement", "artifact_descriptors": [dict(_ART)]}])   # base template
    assert arts[0]["round"] is None


def test_d24_old_handoff_paths_become_legacy_descriptors():
    handoffs = [{"stage": "ui_evidence", "artifacts": ["shot.png", "notes/a.md"]}]
    first = shared.snapshot_artifact_descriptors(handoffs)
    second = shared.snapshot_artifact_descriptors(handoffs)
    assert first == second and first[1] == []
    assert [(a["kind"], a["legacy"], a["stage"]) for a in first[0]] == [
        ("image", True, "ui_evidence"), ("text", True, "ui_evidence")]


def test_d25_a_declaring_stage_paths_are_not_mirrored():
    out, dropped = shared.snapshot_artifact_descriptors([
        {"stage": "implement", "artifact_descriptors": [dict(_ART)],
         "artifacts": ["out/pic.png", "out/extra.json"]}])
    assert dropped == []
    assert [a["source"] for a in out] == ["out/pic.png"]   # declared only, no path mirror
    assert out[0]["legacy"] is False


def test_d26_corrupted_handoff_is_named_never_raised():
    out, dropped = shared.snapshot_artifact_descriptors([
        {"stage": "implement", "artifact_descriptors": "nope"},
        {"stage": "merge", "artifacts": "a.png"},
        {"stage": "ui", "artifacts": [7]},
        "not-a-handoff",
    ])
    assert out == []
    assert [line.split("]")[0] for line in dropped] == ["[implement", "[merge", "[ui"]
    assert all("refused" in line or "read" in line for line in dropped)


def test_d27_snapshot_keys_are_additive_and_old_keys_unchanged():
    wf = _dev_shell(results={"implement": {"artifact_descriptors": [dict(_ART)]}},
                    gens={"implement": 1})
    dev_lane.DevLaneWorkflow._handoff(wf, "implement", "done", artifacts=["out/pic.png"])
    snap = dev_lane.DevLaneWorkflow.snapshot(wf)
    assert [a["id"] for a in snap["artifact_descriptors"]] == ["pic"]
    assert snap["artifact_descriptors"][0]["round"] == 1
    assert snap["artifact_descriptors_dropped"] == []
    # the pre-existing face keeps its values and its shape
    assert snap["handoffs"][-1]["artifacts"] == ["out/pic.png"]
    assert isinstance(snap["handoffs"][-1]["artifacts"], list)
    assert snap["stage"] == "implement" and snap["results"] is wf.results
    assert "artifact_descriptors" in snap and "gens" in snap


def test_d28_the_two_dropped_channels_stay_separate(tmp_path):
    # a receipt refusal lives on results[stage]; the top-level list is the aggregator's
    res = _receipt(tmp_path, {"status": "ok", "artifacts": "nope"})
    assert res is not None and len(res.artifact_descriptors_dropped) == 1
    wf = _dev_shell(results={"implement": {"artifact_descriptors": [],
                                           "artifact_descriptors_dropped":
                                               res.artifact_descriptors_dropped}},
                    meta={"stage": "implement", "handoffs": [], "log": []})
    dev_lane.DevLaneWorkflow._handoff(wf, "implement", "done", artifacts=[])
    snap = dev_lane.DevLaneWorkflow.snapshot(wf)
    assert snap["artifact_descriptors_dropped"] == []
    assert snap["results"]["implement"]["artifact_descriptors_dropped"] == \
        res.artifact_descriptors_dropped


def test_d29_synthetic_results_without_the_keys_still_aggregate():
    wf = _dev_shell(results={"implement": {"status": "ok", "deliverables": ["out/a.png"]}})
    dev_lane.DevLaneWorkflow._handoff(wf, "implement", "done", artifacts=["out/a.png"])
    snap = dev_lane.DevLaneWorkflow.snapshot(wf)
    assert [a["source"] for a in snap["artifact_descriptors"]] == ["out/a.png"]
    assert snap["artifact_descriptors"][0]["legacy"] is True


def test_d30_base_snapshot_exposes_the_same_keys():
    wf = _base_shell(results={"implement": {"artifact_descriptors": [dict(_ART)]}})
    base.TicketWorkflowBase._handoff(wf, SimpleNamespace(id="implement"), "done",
                                     artifacts=["out/pic.png"])
    snap = base.TicketWorkflowBase.snapshot(wf)
    assert [a["id"] for a in snap["artifact_descriptors"]] == ["pic"]
    assert snap["artifact_descriptors"][0]["round"] is None   # no round counter here
    assert snap["artifact_descriptors_dropped"] == []


# ---------------------------------------------------------------------------
# E. visibility
# ---------------------------------------------------------------------------

def test_e31_a_refused_declaration_leaves_one_log_line(tmp_path):
    res = _receipt(tmp_path, {"status": "ok", "artifacts": [7, {"source": ""}]})
    assert res is not None and len(res.artifact_descriptors_dropped) == 2
    wf = _dev_shell(results={"implement": {"artifact_descriptors": [],
                                           "artifact_descriptors_dropped":
                                               res.artifact_descriptors_dropped}})
    dev_lane.DevLaneWorkflow._log(
        wf, "%s artifact declaration dropped: %s"
        % ("implement", "; ".join(res.artifact_descriptors_dropped)))
    assert any("artifact declaration dropped" in str(x) for x in wf.meta["log"])
    # the receipt-level log call is guarded: no activity context must never raise
    assert agent_activities._read_result(tmp_path / "result.json", "implement") is not None


# ---------------------------------------------------------------------------
# F. scope
# ---------------------------------------------------------------------------

def test_f32_a_refused_declaration_changes_no_status_and_no_gate():
    # the same refusal rules on plain values: nothing here can flip a status or a verdict
    descriptors, shape, dropped = shared.normalize_artifacts({"bad": True})
    assert shape == "malformed" and descriptors == [] and dropped
    stage = shared.StageResult(status="ok")
    assert stage.status == "ok" and stage.artifact_descriptors == []
    assert stage.artifact_descriptors_shape == "absent"       # defaults keep replay safe


def test_f33_no_timer_no_spawn_no_fd_in_the_new_code():
    for fn in (shared.normalize_artifacts, shared.normalize_deliverables,
               shared.snapshot_artifact_descriptors, shared.copy_artifact_descriptors,
               shared.legacy_artifact_descriptor):
        src = inspect.getsource(fn)
        for token in ("subprocess", "threading", "Timer", "open(", "os.open"):
            assert token not in src, (fn.__name__, token)
