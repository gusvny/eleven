---
title: Project external workflow templates
category: design
tags: [design-final, workflow-template, project-external, multi-project, engine-extension]
status: active
updated: 2026-09-28
---

# Project external workflow templates

> Source: the nusuyou project document "Requirements for sandbar: project external workflow
> templates" (the host's verbatim 260924 ruling: "don't chisel the gate open directly; write an
> explanatory document and I'll send it to sandbar to open a ticket and do it").
> This document graduated from `notes/discussions/260924-external-project-workflow-templates.md` (registered
> with ticket t260924-04);
> four points ruled in the host's 260924 session: isolation strength = process pooling for fault
> containment (with ticket 2); blast radius of a bad template = per-template isolated rejection;
> evolution strategy = stage-order changes go to a new template id coexisting alongside the old,
> plus branch-logic changes go to a patch marker (with the project prefix); naming boundary =
> project registration names / template ids belong to the data plane and are written as-is, and
> new sandbar identifiers must not recreate the retired old engine name shapes.
> **This document only writes "what and why"**: for interface shape see §six of the requirements;
> for landing status and progress check the epic proposal / ticket.

## Problem

1. **In one sentence**: the engine's "template as code" welds a **project's business process** into
   the **engine repository** — every time a project changes its process, it has to open a ticket in
   the engine repository.
2. **Background knowledge** (what someone who was not involved needs first):
   - **A template = one workflow class**: it defines a process's stage order (who comes before
     whom), which stage the human gate (manual approval) falls on, and what form each stage runs
     in; the engine recognizes templates through a "template id → class" registry.
   - That registry is **engine-global and built in**: classes are loaded from inside the engine
     package, and the project side has no place at all to declare its own process.
   - The engine **serves multiple projects** (each project registers its own identity and
     dependencies), but the workflow template face is not distributed with the project.
   - **The human gate** is the only entry semantics in the engine: human approval can only advance
     through signing, and there is no bypass whatsoever to "skip a stage / force advancement".
   - Workflow code carries one more hard constraint: **determinism + replayable history** (the
     progress of an in-flight ticket is rebuilt by replaying history, so changing branch logic
     without leaving a marker makes old history mismatch the new code).
3. **Evidence**:
   - Current state: template classes live inside the engine package; after 260904 the default
     available template face narrowed to a single built-in development flow.
   - Requester's hard evidence: nusuyou will add a "content authoring" flow (an eight-stage chain
     with two human gates), and that flow **will keep evolving** — under the present structure
     every process iteration becomes an engine ticket, so accounts are misaligned and schedules
     block each other.
   - Constraint evidence: the replay constraint above means that "projects can change their
     process" itself needs a matching evolution discipline, otherwise the first process change
     strands in-flight tickets.

## Requirement

Each item can serve as an acceptance criterion (parentheses = acceptance reading):

1. **Register and it works**: a project can declare "my template is at this location" in its own
   registration; **not declaring = zero behavior change**, and an existing project's existing
   available face is unchanged to the letter. (A2)
2. **An external template works end to end**: create a ticket with an external template → stages
   execute in the defined order → the human gate advances by signing → the ticket closes; after a
   worker restart it can resume (idempotency relies on the existing result-file mechanism). (A1)
3. **A precise rejection face (fail-closed)**: name collision, malformed (missing stage definition
   / invalid stage shape), and load failure — all three states are **rejected outright and the
   failing check is named**; no silent renaming, no later-arrival overwriting, no playing dead and
   skipping. (A3)
4. **Contained blast radius**: the impact of a bad template **is limited to that template** — it is
   isolated and rejected (named loudly, not registered), while other templates in the same project
   and other projects run as usual; ticket creation and resumption for that template are
   fail-closed. (A7)
5. **Trust and fault isolation**: project templates get "trusted code" treatment (the registrant is
   the host's reviewer), paired with **process pooling for fault containment** — a bad template or
   infinite loop in one project does not drag other projects down; OS-level privilege dropping
   (sandbox / dedicated user) is not done this cycle and is booked explicitly as second-phase debt.
6. **Evolution compatibility**: stage-order/topology changes go to a **new template id coexisting
   alongside the old** (old in-flight tickets are finished by the old class); branch-logic changes
   follow the **patch marker** discipline, with identifiers carrying the project prefix to avoid
   collisions; this includes the acceptance face "old in-flight ticket history replays
   successfully". (A6)
7. **The security face is not downgraded**: the human gate's only entry is still signing (no
   bypass), and the signal face is unchanged; the determinism coding rules apply equally to
   external templates and are stated explicitly in the loader document.
8. **Docs match the implementation**: the tool help text, generated documents, and narrowing guard
   assertions on the available template face are synchronized with the new semantics — the default
   face = built-in + templates **explicitly registered by a project**; fixture templates still
   never reach the production board. (A5)
9. **Ownership constraint**: a template belongs to the project that registers it; "cross-project
   reuse of someone else's template" is not done this cycle, and the engine's own flows stay as
   they are.
10. **Naming boundary**: project registration names / template ids belong to the **data plane**
    (written as-is, not renamed); new identifiers added on the sandbar side must not recreate the
    retired old engine name shapes.

## Nongoal

- Do not revive the built-in template family retired on 260904; **do not change the built-in
  development flow itself or its behavior**.
- Do not do **hot loading / swapping templates at runtime** (a restart taking effect is enough —
  and the granularity of that effect must be stated factually, without fudging).
- Do not do a **general-purpose plugin system as a template marketplace** — only this one door is
  opened: "register per project, merge at startup".
- Do not do **OS-level privilege dropping / sandboxing / dedicated-user isolation** (not this
  cycle; booked as second-phase debt).
- Do not do **cross-project template reuse** (not this cycle).
- The class code and machine-check scripts of the content authoring flow **are out of scope for
  this design** (they go through the requester's own ticket).

## Proposal

### High level: three things, one sentence each

1. **One door: register-then-load.** A project declares its template location in its own
   registration → the engine loads it at startup and merges it into the same registry as the
   built-in templates (the same uniqueness checks and self-checks). Declare nothing and nothing
   happens — making "zero behavior change" the default state.
2. **One gate: per-template isolated rejection.** Loading is not "all succeed or all fail": each
   external template goes through its checks (name collision / shape / load) on its own, and the
   one that fails is **loudly rejected but not registered** while the rest proceed as usual; a
   ticket for a rejected template fails right at ticket creation with the reason stated, so no
   half-dead ticket is produced.
3. **Two evolution paths: change the id or apply a patch.** If the stage order/topology changes →
   the new template id coexists with the old id, and old in-flight tickets are finished by the old
   class; if only branch logic changes → leave a patch marker at the change point (identifier
   carrying the project prefix), so old history walks the old branch and new history walks the new
   branch, and both replay.

### Key trade-offs (why these choices)

- **Trusted code vs process isolation**: an external template is **same-privilege code** running
  inside the engine worker process. We choose "trusted (registrant reviewed by the host) + process
  pooling for fault containment" — it stops "a bad write drags others down", but it does not stop
  "reading another project's data without authorization under the same system user"; the latter
  needs OS-level privilege dropping, which is not done this cycle but booked openly as debt, not
  pretended to be blocked.
- **How hard the rejection bites**: a bad template does **not** keep workers from starting
  (otherwise one project's typo halts everyone); instead it is per-template isolation plus loud
  naming, and the rejected template's own tickets are fail-closed. **"Rejected" is not "playing
  dead"**: a rejection must name which check failed and what it collided with.
- **The boundary of evolution freedom**: freedom to change the process must be bounded by
  "in-flight ticket history can be replayed". Without that boundary, the first process change
  strands in-flight tickets — the most easily overlooked and most costly item in this proposal.
- **State the effective granularity factually**: ordinary ticket flows run on **a dedicated worker
  per ticket** (a new ticket picks up new code as soon as it starts; in-flight tickets are frozen
  on the code from their start); the engine's own periodic flows run on **shared workers** (they
  need a restart to pick up new code). Documents and help text must no longer say the vague
  "takes effect after restart".

### Mapping back

This proposal → solves **Problem**'s "process evolution requires changing the engine repository"
(register-then-load + the two evolution paths) → satisfies items 1–10 of **Requirement** → avoids
**Nongoal**'s "no reviving retired templates, no hot loading, no isolation privilege dropping, no
cross-project reuse".

## Appendix: requirements revision points (not part of the design body; for review cross-reference)

1. Two additions to the non-goals: "no OS-level privilege dropping (second-phase debt)" and "no
   cross-project template reuse (this cycle)".
2. The blast-radius semantics of a load failure are made explicit as **per-template isolated
   rejection** (workers start as usual; the bad template is not registered and is named; it is not
   a wholesale refusal to start).
3. Two evolution disciplines added as constraints: "stage-order/topology changes go to a new
   template id coexisting alongside the old" and "patch identifiers carry the project prefix to
   avoid colliding with the engine face".
4. Two acceptance readings added: **A6** (evolution compatibility) and **A7** (isolated rejection
   of a bad template).
5. The narrowing guard is re-judged as "widening the lock without dismantling it" (default face =
   built-in + explicit registrations; fixture gate semantics unchanged).
6. The interface expectation is unchanged and remains in force as-is (for the implementer to match
   the shape).
7. One sentence added on the naming boundary (see Requirement item 10).

## Related documents

- [Design doc writing guide](design-doc-writing-guide.md)
- Requirements (source, nusuyou repo): `notes/discussions/260924-给sandbar需求说明-项目外置工作流模板.md`（that source note lives in the nusuyou repo, not in this one）
- Discussion draft (the original before graduation): [Project external workflow templates (design draft)](../../notes/discussions/260924-external-project-workflow-templates.md)
- [Known issues (KI)](../../notes/debts/known-issues.md) — KI-113 (worker frozen code topology) is directly related to the "effective granularity" item of this document
