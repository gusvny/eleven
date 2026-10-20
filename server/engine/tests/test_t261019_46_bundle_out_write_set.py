# -*- coding: utf-8 -*-
"""261019: the implement stage may write the DECLARED build-chain output.

The declaration deadlock, measured on t261019-09 (and it applies to every ticket
that touches a declared `src`): the merge gate rebuilt the workbench bundle
through the declared entry in a temp copy, found the committed copy stale, and
told the lane to rebuild - but the implement-stage write-set gate refused the
output prefix, so the rebuild could never be committed. Reworks could not clear
it; only a widening could.

The merge gate has widened its own whitelist this way since t261009-38. This
change gives the SAME rule to the stage that produces the bytes:

  * `bundle_out_ws_prefixes` (activity, read-only) reads the lane's
    `server/merge-checks.yaml`, keeps the pairs whose `src` the ticket write set
    covers, and returns the `out` prefixes - plus a note that always says what
    was decided;
  * the workflow calls it ONCE per instance (behind a patch marker, so an
    in-flight history replays its old write set byte for byte), caches the answer
    in `meta["bundle_out_prefixes"]`, and `_effective_write_set()` appends it;
  * fail-closed: no declaration / an unreadable one / a src the write set does
    not cover → nothing is widened and the reason is on the timeline.

Coverage: the activity's four faces over a real fixture tree (covered src
widens; an uncovered src does not; an absent declaration does not; the note is
never empty), the wiring anchors (patched call, cached in meta, appended by
_effective_write_set, registered in the agent activity list - a missing
registration only surfaces at runtime), and the replay guard.
"""
import asyncio
import os

import agent_activities as aa
import dev_lane as dl
import shared

HERE = os.path.dirname(__file__)
DEV_LANE_PY = os.path.join(HERE, "..", "dev_lane.py")
DECL = ("bundle_pairs:\n"
        "  - src: ui/src/\n"
        "    out: ui/lib/\n"
        "    entry: ui/build.sh\n"
        "    budget_s: 60\n")


def _tree(tmp_path, text=DECL):
    (tmp_path / "server").mkdir(parents=True, exist_ok=True)
    if text is not None:
        (tmp_path / "server" / "merge-checks.yaml").write_text(text, encoding="utf-8")
    return str(tmp_path)


def _run(worktree, write_set):
    return asyncio.run(aa.bundle_out_ws_prefixes(shared.BundleOutWsArgs(
        ticket_id="t1", worktree=worktree, write_set=write_set)))


# ---------- the activity ----------

def test_covered_src_widens_its_declared_output(tmp_path):
    res = _run(_tree(tmp_path), ["ui/src/a.tsx"])
    assert res.prefixes == ["ui/lib"]
    assert "ui/lib" in res.note and "write set" in res.note


def test_an_uncovered_src_widens_nothing(tmp_path):
    assert _run(_tree(tmp_path), ["other/a.py"]).prefixes == []


def test_an_empty_write_set_widens_nothing(tmp_path):
    assert _run(_tree(tmp_path), []).prefixes == []


def test_an_absent_declaration_widens_nothing_and_says_so(tmp_path):
    res = _run(_tree(tmp_path, text=None), ["ui/src/a.tsx"])
    assert res.prefixes == []
    assert "merge-checks.yaml" in res.note, "an empty widening must never be silent"


def test_a_malformed_declaration_fails_closed(tmp_path):
    bad = "bundle_pairs:\n  - src: ui/src/\n    out: ui/lib/\n    wat: 1\n"
    res = _run(_tree(tmp_path, text=bad), ["ui/src/a.tsx"])
    assert res.prefixes == []
    assert "fail-closed" in res.note or "unreadable" in res.note


# ---------- the wiring ----------

def test_activity_is_registered():
    names = [getattr(a, "__name__", "") for a in aa.ALL_AGENT_ACTIVITIES]
    assert "bundle_out_ws_prefixes" in names, \
        "a missing registration only surfaces at runtime"


def test_workflow_calls_it_once_behind_a_patch_and_caches_the_answer():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    assert 'BUNDLE_OUT_WS_PATCH_ID = "dev-lane-bundle-out-write-set-v1"' in src
    i = src.index("workflow.patched(BUNDLE_OUT_WS_PATCH_ID)")
    window = src[i:i + 1400]
    assert "bundle_out_ws_prefixes" in window
    assert 'self.meta["bundle_out_prefixes"] = _prefixes' in window
    assert "not self.meta.get(\"bundle_out_prefixes\")" in window, \
        "the lookup must be once per instance, not per stage"


def test_effective_write_set_appends_the_declared_outputs():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("def _effective_write_set")
    window = src[i:i + 1600]
    assert 'self.meta.get("bundle_out_prefixes")' in window, \
        "the widening must live in the ONE write-set answer every face reads"
    assert "if p not in ws" in window, "a duplicate prefix must not appear twice"


def test_old_histories_keep_their_write_set():
    src = open(DEV_LANE_PY, encoding="utf-8").read()
    i = src.index("def _effective_write_set")
    window = src[i:i + 2200]
    j = window.index("workflow.patched(EFFECTIVE_WS_PATCH_ID)")
    k = window.index("bundle_out_prefixes")
    assert j < k, ("the legacy branch must be decided first, so a pre-patch "
                   "history replays its stored field byte for byte")
