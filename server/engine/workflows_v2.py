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

import os as _os

from dev_lane import DevLaneWorkflow
from shared import FIXTURE_TEMPLATES_ENV

TEMPLATE_CLASSES = {
    "dev-lane": DevLaneWorkflow,
}

ALL_WORKFLOWS_V2 = [
    DevLaneWorkflow,
]

# 夹具模板环境门（工单 t260908-01，与 shared.TEMPLATE_CLASS_NAMES 同门同款）：
# SANDBAR_FIXTURE_TEMPLATES=1 时注册测试夹具模板 fixture-two-step——收窄守卫
# （sc_template_face_narrowing 的默认面断言恰为 {dev-lane}）与生产板不受影响；
# 只有测试场景起 worker 的子进程注入该 env。
if _os.environ.get(FIXTURE_TEMPLATES_ENV) == "1":
    from fixtures.fixture_two_step import FixtureTwoStepWorkflow
    TEMPLATE_CLASSES["fixture-two-step"] = FixtureTwoStepWorkflow
    ALL_WORKFLOWS_V2.append(FixtureTwoStepWorkflow)
