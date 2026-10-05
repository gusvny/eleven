"""t261006-01 unit tests — KI-205 layer 5: the capture's output location and the
merge_check gate's read point must agree, and the refusal text must never name a
different directory than the one being judged.

Covers (zero Temporal server / zero model / zero network; temp dirs self-contained):
  - Shape A (subdirectory): a png under <lane>/.sandbar/screenshots/acceptance/ is
    counted MISSING by the gate (top-level non-recursive stance, host ruling
    261005-B), AND the refusal text / next_action name the resolved top-level
    directory the gate actually globs (never the bare constant shape).
  - Shape B (legacy-named lane): a lane whose sticky resolution pins the retired
    LEGACY dot-dir name (shared.DOT_DIR_OLD) — a
    top-level png there turns the item green, and a red variant's text contains the
    legacy-resolved path, not .sandbar/screenshots.
  - Text/judgement single-source: _ui_evidence_gate_check derives every path it
    prints from ui_evidence_dir(lane_root) — one read point (KI-205 ①/②).
  - Malformed-input discipline: hostile ui_paths entries (non-string) do not crash
    the item build and are stringified into "files".

Grey-box: assertions land on the gate OUTPUT (item / detail / next_action / green),
not on internal names. The producer-side flat contract (agent_activities
acceptance-walkthrough writes ui_evidence_dir(cwd) top level) is pinned by a source
read (the walkthrough body cannot run without a Temporal/worker stage).
"""
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities  # noqa: E402
import shared  # noqa: E402
from agent_activities import _ui_evidence_gate_check  # noqa: E402


def _make_lane(tmp_path, legacy=False):
    """A fake lane root; legacy=True pre-creates the old-name coordination dir so
    sticky resolution pins the lane to the retired LEGACY name (rule 2 in
    shared.resolve_dot_dir)."""
    lane = tmp_path / ("legacy-lane" if legacy else "new-lane")
    lane.mkdir(parents=True)
    if legacy:
        (lane / shared.DOT_DIR_OLD).mkdir()
    return lane


def _shots_dir(lane):
    return agent_activities.ui_evidence_dir(lane)


# ---------- Shape A: png in a subdirectory counts as missing ----------

def test_shape_a_subdir_png_is_missing_and_text_names_resolved_dir(tmp_path):
    lane = _make_lane(tmp_path)
    shots = _shots_dir(lane)
    (shots / "acceptance").mkdir(parents=True)
    (shots / "acceptance" / "console.png").write_bytes(b"\x89PNG")

    item = _ui_evidence_gate_check("judge-line", lane, ["app/src/x.ts"])

    assert item["id"] == "ui_evidence"
    assert item["green"] is False, "subdir png must not satisfy the top-level gate"
    assert item["reason_code"] == "ui_evidence_missing"
    # The text names the directory the gate globs (resolved top level)…
    assert str(shots) in item["detail"]
    assert str(shots) in item["next_action"]
    # …and the next action is runnable (capture command with the resolved --out).
    assert "capture.mjs --out %s" % shots in item["next_action"]
    assert "retry_qc" in item["next_action"]
    # No divergence: the legacy/constant shape must not appear when the lane
    # resolves to the new name — the printed path is exactly the judged directory.
    assert item["item"] == "UI screenshot evidence (%s)" % shots


def test_shape_a_legacy_lane_with_stray_subdir_text_points_at_legacy_dir(tmp_path):
    """Review condition 4: a legacy lane with a stray subdir png cannot pass with
    text pointing at .sandbar — text must name the legacy-resolved directory."""
    lane = _make_lane(tmp_path, legacy=True)
    shots = _shots_dir(lane)
    assert shared.DOT_DIR_OLD in str(shots), "sticky resolution must pin to the legacy name"
    (shots / "after").mkdir(parents=True)
    (shots / "after" / "chat.png").write_bytes(b"\x89PNG")

    item = _ui_evidence_gate_check("judge-line", lane, [])

    assert item["green"] is False
    assert shared.DOT_DIR_OLD in item["detail"] and shared.DOT_DIR_OLD in item["next_action"]
    assert ".sandbar/screenshots" not in item["detail"]
    assert ".sandbar/screenshots" not in item["next_action"]


# ---------- Shape B: png in the legacy-named directory counts ----------

def test_shape_b_legacy_top_level_png_is_green_and_text_matches(tmp_path):
    lane = _make_lane(tmp_path, legacy=True)
    shots = _shots_dir(lane)
    shots.mkdir(parents=True)
    (shots / "console.png").write_bytes(b"\x89PNG")

    item = _ui_evidence_gate_check("judge-line", lane, ["app/src/y.ts"])

    assert item["green"] is True, "a top-level png in the legacy dir must count"
    assert "reason_code" not in item
    assert "next_action" not in item
    assert str(shots) in item["item"]
    assert "console.png" in item["detail"]


def test_shape_b_legacy_lane_empty_dir_is_red_with_legacy_path_in_text(tmp_path):
    lane = _make_lane(tmp_path, legacy=True)
    shots = _shots_dir(lane)
    shots.mkdir(parents=True)

    item = _ui_evidence_gate_check("judge-line", lane, [])

    assert item["green"] is False
    assert str(shots) in item["detail"]
    assert str(shots) in item["next_action"]
    assert ".sandbar/screenshots" not in item["detail"]


def test_gate_missing_dir_is_red_not_crash(tmp_path):
    lane = _make_lane(tmp_path)
    item = _ui_evidence_gate_check("judge-line", lane, [])
    assert item["green"] is False
    assert item["reason_code"] == "ui_evidence_missing"


# ---------- Single-source discipline + malformed input ----------

def test_text_path_is_derived_from_ui_evidence_dir_not_the_constant(tmp_path):
    """KI-205 ②: whatever directory ui_evidence_dir() resolves, the printed path is
    that directory — the item must never carry the bare constant default when the
    lane resolves elsewhere (and vice versa on a new lane, where they coincide)."""
    for legacy in (False, True):
        lane = _make_lane(tmp_path, legacy=legacy)
        shots = _shots_dir(lane)
        item = _ui_evidence_gate_check("j", lane, [])
        assert str(shots) in item["item"]
        assert str(shots) in item["detail"]
        assert str(shots) in item["next_action"]


def test_malformed_ui_paths_entries_are_stringified_not_fatal(tmp_path):
    """Consumer-of-external-data discipline: the hit list comes from a git diff —
    hostile entries must not crash the item build. files is carried on the red
    variant (the only shape that emits it)."""
    lane = _make_lane(tmp_path)
    hostile = [42, None, ("tup",), "app/src/ok.ts"]
    item = _ui_evidence_gate_check("j", lane, hostile)
    assert item["green"] is False
    assert item["files"] == [str(x) for x in hostile[:20]]


# ---------- Producer-side flat contract (source pin; body needs a worker stage) ----------

def test_producer_acceptance_walkthrough_writes_gate_dir_flat():
    src = (POC / "agent_activities.py").read_text(encoding="utf-8")
    assert 'ui_evidence_dir(cwd)' in src, \
        "acceptance-walkthrough capture output must land in ui_evidence_dir(cwd)"
    assert 'lane_dot_path(cwd, "screenshots", "acceptance"' not in src, \
        "the screenshots/acceptance subdirectory (gate-invisible) producer is retired"
    assert ".sandbar/screenshots/acceptance/" not in src, \
        "docstring must not advertise the retired subdirectory shape"


def test_capture_lane_env_fail_names_actionable_exit():
    """KI-205 ③: the ENV_FAIL text names real exits (wait threshold via the env the
    bench actually reads, docker-logs access, serialising stage boots) — no flag
    that does not exist, no silent bare-URL fallback."""
    src = (POC.parent / "ui-check" / "capture-lane.mjs").read_text(encoding="utf-8")
    assert "SANDBAR_CAPTURE_LANE_BOOT_MS" in src, "the bench reads this env"
    assert "--stage-wait" not in src, "do not advertise a flag that does not exist"
    assert src.count("SANDBAR_CAPTURE_LANE_BOOT_MS") >= 3
    assert "docker logs" in src
    # The serialise-boots advice lives in server/ui-check (outside the copy gate's
    # scope); pinned via unicode escapes so this gated test file stays marker-free
    # (t261004-36 retired the temporary data-id copy markers under server/engine).
    assert "\u4e32\u884c\u5316" in src  # "serialise stage boots" advice in the bench copy
