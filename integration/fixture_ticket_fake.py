# fixture_ticket_fake.py — a fake DevLaneWorkflow for fixture tickets (260908).
#
# Why this exists: console-based ticket scenarios (ticket-session-restore,
# the t260903-07 family, ticket-evidence-images) need healthy ticket rows on
# the stage console — a title on the row and a fast drawer. Without a running
# worker, real workflows leave queries hanging until timeout (left rail shows
# "query timeout, retry" and the drawer stalls). The engine already has a way
# out: a COMPLETED workflow can be read back with no worker at all (the
# result() path in client.py cmd_ticket_query). So a fixture ticket just needs
# to reach closed state once, then it stays healthy forever (within the 7-day
# closed-ticket hydrate window, list rows carry full meta).
#
# This module is loaded by fixture_ticket_worker.py inside a real Worker, so
# it must stay a clean module: only temporalio imports plus class definitions,
# no module-level calls like pathlib or subprocess. The temporalio sandbox
# re-executes the defining module when validating @workflow.defn classes, and
# restricted calls at module level break that check (same case as t260902-02).
# The snapshot meta shape mirrors the field surface of dev_lane._init (the
# consumers are client.py _row_from_meta and handleTicketSessionOpen's
# workspace/worktree checks). Only the fields scenarios need are filled; this
# is not a full replica.

from temporalio import workflow


def _now_epoch() -> int:
    # The workflow sandbox blocks time.time() (RestrictedWorkflowAccessError).
    # workflow.now() is the only safe way to read the clock inside the sandbox
    # (deterministic, replay-safe). Epoch conversion goes through timedelta
    # math, never touching any time.* call.
    import datetime as _dt

    return int((workflow.now() - _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc))
               .total_seconds())


def _g(obj, key, default=""):
    """Read a value from either a dict or a dataclass (ticket-start input shape
    follows the engine; we do not guess)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@workflow.defn(name="DevLaneWorkflow")
class FixtureTicket:
    """Fixture ticket workflow: run() returns the final snapshot directly
    (closes instantly, zero activities, zero side effects)."""

    @workflow.run
    async def run(self, inp) -> dict:
        now = _now_epoch()
        tid = str(_g(inp, "ticket_id", ""))
        title = str(_g(inp, "title", ""))
        meta = {
            "id": tid,
            "workflow_id": str(_g(inp, "template_id", "dev-lane")),
            "project": str(_g(inp, "project", "")),
            "title": title,
            "role": "developer",
            "lane": str(_g(inp, "lane", "worktree")),
            # Empty path = the default contract where the host follows the
            # ticket (the open route falls back to cwd = project main dir).
            "workspace": {"type": "worktree", "path": ""},
            "worktree": "",
            "branch": str(_g(inp, "branch", "")),
            "base_ref": str(_g(inp, "base_ref", "")),
            "proposal_id": str(_g(inp, "proposal_id", "")),
            "book_path": str(_g(inp, "book_path", "")),
            "epic": str(_g(inp, "epic", "")),
            "stage": "create_plan",
            "stage_state": "awaiting",
            "write_set": [],
            "no_file_changes": True,
            "acceptance": [],
            "checks": {},
            "deliverables": "",
            "user_request": str(_g(inp, "user_request", "")),
            "spec": str(_g(inp, "spec", "")),
            "body": str(_g(inp, "body", "")),
            "pending": [],
            "handoffs": [],
            "status": "dispatched",
            "created": now,
            "updated": now,
            "last_rework_note": "",
            "temporal": True,
        }
        return {"engine": "template-as-code-v2", "meta": meta}
