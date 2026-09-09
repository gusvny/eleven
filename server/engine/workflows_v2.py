"""workflows_v2 — the registry of v2 template workflow classes (templates as code).

Since 260824 the developer side has only one flow: dev-lane (DevLaneWorkflow,
activities wired directly:
create_plan<->review_plan -> implement<->integration_review -> merge_check -> merge
with a human gate). The old code-lane / build-workbench templates are deleted (all
their tickets are closed, so replay is not a concern).
On 260904 the host ordered content-pipeline / proofread / regression / cleanup
retired. Now only dev-lane remains (standalone regression runs either directly on
the integration main side or as a dev-lane).

TEMPLATE_CLASSES: template id -> workflow class. This is the source of truth for
class selection in client.py ticket-start. Class names must match
shared.TEMPLATE_CLASS_NAMES — a selfcheck cross-asserts the two to catch drift.
"""

from __future__ import annotations

from dev_lane import DevLaneWorkflow

TEMPLATE_CLASSES = {
    "dev-lane": DevLaneWorkflow,
}

ALL_WORKFLOWS_V2 = [
    DevLaneWorkflow,
]
