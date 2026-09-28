---
title: "Project external workflow template loader v1"
category: design
tags: [workflow-template, project-external, loader, multi-project, isolated-rejection, evolution-discipline]
status: active
updated: 2026-09-28
---

# Project external workflow template loader v1 (t260924-04, ticket 1)

> Source: nusuyou's "Requirements for sandbar: project external workflow templates" (§six,
> interface shape) and the design draft
> (`notes/discussions/260924-项目外置工作流模板-设计稿.md`). This document is the **loader's
> implementation contract**: interface shape, rejection semantics, and the coding rules and
> evolution discipline that consumers must follow.
> For the paths key table of contract v1 see [sandbar project onboarding contract v1](sandbar-project-onboarding-contract-v1.md) ①d.

## 1. What it is (three sentences)

1. A project declares its own workflow template module list in the registration entry
   `paths.workflow_modules` (`,`-separated, each item relative to the project's main directory
   `dirs[0]`); at startup the engine loads them module by module and merges them into the same
   registry as the built-in templates (`shared.TEMPLATE_CLASS_NAMES` / `workflows_v2.TEMPLATE_CLASSES`
   merged from the same source).
2. **Not declaring = zero behavior change** (contract ①d, four fallback classes); declaring but
   broken = **per-template isolated rejection** — the bad template is not registered and is named
   loudly, while other modules in the same project and other projects carry on.
3. Effective granularity: loaded at startup, and **a late declaration (written after the process
   started) takes effect on the next restart**; ordinary tickets run on a dedicated worker per
   ticket → a new ticket picks up new code as soon as it starts, while in-flight tickets are frozen
   on the code from their start (KI-113; that conclusion assumes "ticket-type templates do not land
   on shared workers", and this clause must be re-reviewed when ticket 2's process pooling lands).

## 2. Interface shape (requirements §six made concrete)

```yaml
# ~/.sandbar/projects/<key>/project.yaml
schema: v1
project:
  - key: <key>
    name: <name>
    dirs:
      - /abs/project/root
paths:
  workflow_modules: workflows/templates_a.py,workflows/templates_b.py
```

Template module (each `.py` holds exactly one template class, per the `fixture_two_step`
convention):

```python
TEMPLATE_ID = "my-flow"            # template id, globally unique (data plane, written as-is and not renamed; a collision = you rename)
TEMPLATE_NAME = "My flow"          # display name on the ticket console
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class MyFlow(TicketWorkflowBase):
    STAGES = (Stage(id="s1", name="…", role="developer", next="s2", acceptance=("…",)), …)
    PATCH_ID = "<key>-my-flow-v1"  # see §4: must carry the <project key>- prefix
    TEMPLATE_ID = "my-flow"        # must match the source declaration (a mismatch = rejection naming both sides)
    TEMPLATE_NAME = "My flow"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
```

The first consumer, nusuyou's `content-studio` (`ContentStudioWorkflow`), onboards in this shape;
if that id is taken, the requester renames it rather than contesting it (requirements §six remains
in force as-is).

## 3. Rejection face (fail-closed with precise naming)

Each of the three states is a structured rejection record (project / module / check / detail),
visible through the ticket-creation text (the "unknown template…" error of `ticket.py create` and
`client.py ticket-start`) —
**rejection ≠ playing dead**: no silent renaming, no later-arrival overwriting, no silent skipping.

| Check | Trigger | What is named |
|---|---|---|
| colliding id | the template id equals an id already accepted from built-in/fixture/another project | the check name + the occupying side (id, source) + the incoming side (project/module) |
| malformed | missing `TEMPLATE_ID` (or multiple values), template class not identifiable, missing `STAGES`, `STAGES` empty or not a tuple, a stage missing `id/name/role`, `parts` containing an illegal value, source declaration inconsistent with the class attribute | the check name + what is missing / both sides' values |
| load failure | missing declaration anchor, module unreadable, import raising | the check name + file + exception type/summary |

Also: **a patch identifier colliding with the engine face** — when a project module's declared
`*_PATCH_ID` equals an engine-face patch identifier set (collected dynamically from
`server/engine/*.py` at load time, not hardcoded as a list) → rejected, naming both sides' values
(see §4).

For the parsing layer (the declared paths value itself is bad: empty item / absolute / `..`
escaping / non-scalar / an entry missing its first dirs item), the fail-closed red of contract ①d's
`ProjectPathsError` is reused; at the loader it is converted into a structured "declaration parse
failure" rejection that likewise reaches the ticket-creation text, never silently passed off as
"not declared".

## 4. Evolution discipline (hard constraints on external templates)

1. **Stage order/topology change → a new template id coexisting alongside the old**: old in-flight
   tickets are finished by the old class (each ticket's dedicated worker freezes the code from its
   start); the new id and the old id coexist in the registry without affecting each other.
2. **Branch logic change → `workflow.patched()` plus a patch identifier carrying the project
   prefix**: branch at the change point with `workflow.patched("<key>-…-vN")`, so old history walks
   the old branch and new history walks the new branch, and both replay. **Every new patch
   identifier carries the `<project key>-` prefix** (the main line of defense — that prefix makes a
   collision with the engine's existing `dev-lane-*`/`ki003-*`/`ticket-*` shapes impossible); the
   loader additionally collects the engine-face identifier set as a backstop rejection (collected by
   statically scanning source for `*_PATCH_ID = "…"`, so a new engine patch that does not follow the
   convention may go unreported, with limited consequences: a patched equality check only ever
   happens within a single template class's own history).
3. Truth is the code: changing a template = changing the class definition in the project
   repository; the `server/workflows/*.yaml` reference snapshot in the engine repository **does not
   cover external templates** (`gen_workflows_doc.py` excludes `PROJECT_TEMPLATE_IDS` by explicit
   declaration, and `--check`'s drift protection pins only engine built-in templates).

## 5. Security face and determinism (not downgraded, applies verbatim)

- The human gate's only entry is still `sign`: external templates use the same base class
  `TicketWorkflowBase`, with no set-stage/force_stage bypass; the signal face is only sign/retry_qc
  (plus the existing pause/rework face).
- **Determinism coding rules** (the workflow function body is purely deterministic: zero IO, zero
  randomness, zero wall clock, using only `workflow.now()`; all side effects go into activities;
  changing execution logic requires bumping PATCH_ID first and branching at the change point with
  `workflow.patched()`) apply equally to external templates.
- **Clean-module constraint** (the temporalio sandbox re-executes the definition module): a module
  body may contain only imports and class definitions, with zero module-level IO (`pathlib`/
  `subprocess`/`open` are all forbidden), and engine-internal imports such as
  `from shared import …`/`from base import …` go inside a
  `workflow.unsafe.imports_passed_through()` block, following `fixture_two_step`.
- **Two-layer sandbox-compatibility defense (D3, t260924-04)**: ① at worker construction, the
  external modules' load names (`sandbar_ext_<key>_<stem>`) are injected into
  `SandboxedWorkflowRunner`'s `passthrough_modules` — the sandbox importer resolves them by name to
  the already-loaded outer module, so it no longer crashes the worker with ModuleNotFoundError;
  ② the loader class face first runs a `prepare_workflow` pre-check on every candidate template
  using the same restrictions as the worker, and a failed check = a "sandbox check failed"
  per-template rejection naming the template, never entering the worker registry — a bad template
  cannot blow up the worker process (spec ④ boundary).
  The passthrough set = **external load names ∪ their engine dependency top-level names**
  (shared/base/activities/agent_activities/workflows/workflows_v2/dev_lane, D6): decoding the
  payload during activate needs `typing.get_type_hints` to look up the module owning `TicketInput`
  by name, and for a non-passthrough name the restricted importer raises KeyError; worker and
  pre-check use the same full set, so "the pre-check passed = the worker can run it".

## 6. Implementation anchors (where to start reading the code)

- Loader: `server/engine/project_templates.py` (name face = stdlib source scanning; class face =
  full importlib loading in the engine venv plus deep shape inspection; zero shared imports, with
  all dependencies injected as parameters).
- Merging: the "project external workflow template face" section at the end of `shared.py` (the
  name face merged into both tables plus the rejection list); the tail section of `workflows_v2.py`
  (class face merged in plus deep-inspection write-back withdrawing ids that the name face had
  merged but the deep inspection rejected — within an engine process the two tables are always
  consistent, so the cross self-check does not break).
- Registration order is hardcoded: built-in ∪ fixture (`SANDBAR_FIXTURE_TEMPLATES` gate, semantics
  unchanged) claims slots first, project templates arrive later; a later arrival that collides is
  rejected with both sides named.
- Acceptance cases: `server/engine/tests/test_t260924_04_project_templates.py` (cases corresponding
  to A2/A3/A7); narrowing-guard re-judgment:
  `integration/t260904-08/sc_template_face_narrowing.py` (default face = built-in + templates a
  project explicitly registers; the fixture-gate case is unchanged).

## Related documents

- [sandbar project onboarding contract v1](sandbar-project-onboarding-contract-v1.md) (①d paths key table)
- Design draft: `notes/discussions/260924-项目外置工作流模板-设计稿.md`
