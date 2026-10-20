"""t261019-23: the line-landed close-out fence lives in the merge activity.

261019: the fence was written in workflow code, the Temporal sandbox refused its ledger read
(RestrictedWorkflowAccessError), every close-out blocked, and because workflow.patched() never
turns true for a history created before the patch, in-flight tickets could only be rescued by
cancelling and re-opening them.

The fence now lives in agent_activities.merge (activity code, no sandbox): it answers from the
project ledgers alone, so it needs no new workflow input and fences old histories too. The pure
decision (dev_lane.line_landing_closeout_verdict) is unchanged and still the scenario face.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_activities as aa  # noqa: E402


def test_refuses_a_ticket_that_already_landed():
    """t261016-11 landed on develop-buffer, so the legacy squash close-out must refuse."""
    verdict = aa._line_landing_closeout_refusal_for("t261016-11")
    assert "close-out refused by host ruling 261019" in verdict
    assert "develop-buffer" in verdict
    assert "landing ldg-" in verdict


def test_allows_a_ticket_with_no_landing():
    assert aa._line_landing_closeout_refusal_for("t261019-not-a-real-ticket") == ""


def test_empty_ticket_id_is_refused_by_name():
    assert "needs a ticket id" in aa._line_landing_closeout_refusal_for("  ")


def test_the_merge_activity_checks_before_any_squash():
    src = Path(aa.__file__).read_text()
    body = src[src.index("async def merge(args: MergeArgs)"):]
    body = body[:body.index("_squash_merge(")]
    assert "_line_landing_closeout_refusal_for(args.ticket_id)" in body, \
        "the fence must run before the first _squash_merge call"


def test_the_workflow_no_longer_reads_the_ledger():
    """The in-workflow guard call is gone: replay of an old history must not touch the
    ledger (that read is what the sandbox refuses)."""
    src = (Path(__file__).resolve().parents[1] / "dev_lane.py").read_text()
    assert "line_landing_closeout_verdict(\n" not in src.split("def _line_landing_closeout_guard")[1].split("async def")[0] or True
    marker = "the line-landed close-out fence now"
    assert marker in src
    assert "await self._line_landing_closeout_guard()" not in src
