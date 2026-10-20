"""Fixture-local quickmanual registration seam (t261019-32 e2e journey).

The production registration of the quickmanual template is the named step-0 host
amendment (workflows_v2 class face + the generated server/workflows yaml, both
outside that ticket's lane, per the host ruling). This module gives the e2e
journey's fixture world a startable template through the SANCTIONED
project-external loader (server/engine/project_templates.py, the t260924-04
contract): the fixture project declares `workflow_modules` pointing at this
file, the loader deep-checks the class (STAGES present, TEMPLATE_ID agreement,
patch-id collision scan against the engine set, clean-module shape) and merges
it into the registration faces for THE FIXTURE PROJECT ONLY. The production
creation face stays fail-closed until the real registration lands.

Clean-module discipline (loader contract): imports + class definition, zero
module-level IO. The subclass keeps every behavior of the shipped
QuickmanualLaneWorkflow; the only deltas, each named:

- PATCH_ID carries the fixture project key prefix (`quickmanual-e2e-`); the
  production patch id `quickmanual-lane-v1` stays reserved for the step-0
  registration and must never collide with the engine patch-id set.
- PATH_GATE is explicitly False in the fixture world: the loader refuses
  PATH_GATE=True without a non-empty PATH_GATE_RULES table (dead configuration),
  and the production stage-path-rule table is not part of this seam. The
  production registration keeps PATH_GATE=True. The journey asserts the chain,
  the settle hand-off and the gates - not the path gate.
"""
from temporalio import workflow

from dev_lane import QuickmanualLaneWorkflow as _QuickmanualLaneWorkflow
from shared import TicketInput

TEMPLATE_ID = "quickmanual-lane"
TEMPLATE_NAME = "Quickmanual Lane"


def _clear_inherited_defn(cls):
    """The base class carries a workflow definition; the SDK refuses to decorate
    a subclass whose MRO already has one (light_lane's measured behavior). Clear
    the inherited marker, then let @workflow.defn above re-decorate THIS class
    with its own definition (own run/signals/queries/type name)."""
    cls.__temporal_workflow_definition = None
    return cls


@workflow.defn
@_clear_inherited_defn
class QuickmanualFixtureWorkflow(_QuickmanualLaneWorkflow):
    # Fixture-scoped patch id: project-key prefix, never the production id.
    PATCH_ID = "quickmanual-e2e-fixture-v1"
    # See the module docstring: named fixture delta, production keeps True.
    PATH_GATE = False

    @workflow.run
    async def run(self, inp: TicketInput):
        """SDK requirement: @workflow.run must be on the decorated class itself
        (the MRO's annotated runs do not count). The body is a pure delegation —
        the orchestration is the shipped QuickmanualLaneWorkflow.run, unchanged."""
        return await _QuickmanualLaneWorkflow.run(self, inp)


QuickmanualFixtureWorkflow.TEMPLATE_ID = "quickmanual-lane"
