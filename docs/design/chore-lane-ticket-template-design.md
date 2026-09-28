---
title: "Chore Ticket Template (chore-lane) Design"
category: design
tags:
  - ticket template
  - chore-lane
  - engine
status: draft
updated: 2026-09-28
---

# Chore Ticket Template (chore-lane) Design

> Status: draft (awaiting host sign-off). Drafted by integration, 2026-09-03.
> Motivation: hard evidence from t260903-12 (build-chain revival) — for a purely mechanical
> task under the full dev-lane cycle, the plan quality ring burned 29 minutes while the real
> work took only 10; multiplying stage count by quality rings does not pay off for chores.

## 1. Positioning and boundaries

**chore** = a mechanical task whose complete command chain can be given without any LLM judgment. Typical cases:

- Install dependencies + build/rebuild artifacts (tsdown/pnpm surface)
- Mechanical changes to version numbers / manifest files (bump rc, change a field)
- Re-feeding images, batch sed-style edits (with a precise diff preview)
- File retirement (removal from the repo + gitignore alignment)

**Not allowed through chore** (they still go through dev-lane): anything involving business logic / writing new code / tradeoff judgment / interface changes;
a write set that cannot be enumerated exactly at ticket-creation time; anything that needs human review of the design.

The judgment call belongs to integration at ticket-creation time; using the wrong template = stopped by the human gate and re-opened (the nature of the task is checked at merge sign-off).

## 2. Flow (against the dev-lane eight stages)

**Precondition (host review 2026-09-03: do not assume every project builds the same way)**: a chore's command chain
is **not invented by the ticket author**; it always comes from a **declaration inside the project repo** — carrying on the
"policy travels with the repo" philosophy of verify.yaml/merge-checks.yaml. Where it lands:

- `chores.yaml` at the project repo root (schema in the same family as verify.yaml; field-level definition written up separately):
  each named chore = command chain (item by item) + expected artifact paths + failure semantics (fail-fast/fail-collect)
  + rollback point. Example: sandbar declares `rebuild-bundle`; suyou may declare a completely different chain.
- The ticket only references it: `{"chore": "rebuild-bundle", "args": {...}}` — the engine executes per the project declaration.
- **A chore the project has not declared cannot be opened as a chore ticket**: either open a dev-lane ticket first to add
  the declaration (chores.yaml is itself a code asset and goes through normal review), or run the whole task through dev-lane.
- Missing declaration / parse failure = fail-closed red, never silently skipped (same stance as verify.yaml).

| Stage | dev-lane | chore-lane | Notes |
|---|---|---|---|
| create_plan | LLM drafts | **skipped** | plan = project declaration + ticket parameters, human-reviewed at ticket creation (integration drafts → host approves) |
| review_plan | LLM reviews | **skipped** | same as above |
| implement∥design∥ui_evidence | LLM writes code + design + screenshots | **single implement stage** | see the sub-section below |
| run_integration_tests | scenario suite | kept (programmatic step) | scenarios are declared by the project's verify.yaml; a chore often has zero scenarios = instant pass |
| arbitrate∥acceptance | LLM three-state verdict + walkthrough | **merged into the programmatic step verify** | an all-green verify_lane = pass; red = blocked waiting for retry/rework |
| merge_check | four mechanical checks | kept (as is) | includes the anti-false-completion hard metrics |
| merge human sign-off | human signs | kept (as is) | discipline is not downgraded |

### The two forms of the implement stage

- **A, purely programmatic** (preferred): the worker executes the **project-declared** command chain item by item
  (reusing the programmatic-step mechanism); any non-zero command = red receipt. Zero LLM.
- **B, with a fix-it agent** (escalated when the command chain breaks): after A fails, B may optionally be
  escalated to — spawn an agent with prompt = declared chain + failure output + "only fix blockers, do not change
  semantics". Anti-slippage: B's diff is still bound by the write set + acceptance hard metrics (the write set is
  enumerated at ticket-creation time from the declared artifact face).

The A→B escalation happens automatically once; if B is red too, blocked awaiting a human.

## 3. Anti-false-completion (inherited + new)

1. Lane diff non-empty (a hard metric already added in dev-lane; chore must check it too)
2. Artifact freshness: the declared expected artifact paths must be newer in mtime/content order than the baseline at ticket-creation time
3. The verify red item "sensitive/runtime paths committed to the repo" (landed in 8d39555)
4. merge_check's four items as is (commit chain / clean tree / lane verify / merge-tree)

## 4. Implementation size estimate

- New subclass `ChoreLaneWorkflow(TicketWorkflowBase)`: STAGES with three stages
  (implement programmatic step / verify programmatic step / merge gate), about 120 lines
- Programmatic-step command chain executor: new activity `run_chore_commands` (item by item
  create_subprocess_exec + log archive), about 80 lines — mind the async discipline (t260903-09 lesson)
- Ticket create accepts `workflow:"chore-lane"` + `chore` (named reference) + `args`; the command chain itself lives in the project's chores.yaml
- Tests: 3-5 pytest contract cases (red/green + out-of-bounds + timeout) + one selfcheck case
- Total ≈ half a day, delivered via one dev-lane ticket (we do not eat our own dog food here)

## 5. Decision points for human review

1. Whether the boundary stance is accepted (the red-line list in Section 1)
2. Whether implement defaults to A, or to automatic A→B escalation (I recommend the latter)
3. Keeping the merge human sign-off (I recommend keeping it — today's incident chain proves the last human gate is worth its keep)
4. Scheduling: after the second half of M2-D / immediately (which would crowd out care for the two in-flight tickets)

## 6. Switchover acceptance archive

> This section archives acceptance facts; it does not change the draft-pending-review status of Sections 1-5.
> This section contains no operation against 3099/7233; those two ports are mentioned only for the distinction explained below.

On 2026-09-03 the sandbar M2-D install-based switchover acceptance was completed; the facts are archived below:

| Item | Fact |
|---|---|
| Isolated instance home | `/tmp/suyou-m2d-accept` (a runtime isolation path, possibly cleaned up after acceptance; historical archive only, not a reproducible stance) |
| server port | 7234 (dedicated to this acceptance instance) |
| UI port | 8234 (dedicated to this acceptance instance) |
| Engine form | sandbar v0.2.0 install-based |
| Nature of this ticket | t260903-14 is the first ticket to run the whole flow across the install-based form (ticket authority stance, recorded as is) |

Port distinction: 7234/8234 belong only to this acceptance isolation instance; `3099` (production dsh console)
and `7233` (production Temporal gRPC) are production-side ports whose stance is in `docs/testing-guide.md`;
this section records facts only and contains no operation against them.

The facts recorded in this section are available for human-review decisions such as Section 5 decision point 4 (scheduling);
"install-based" and "switchover acceptance" are newly introduced terms, and registering terminology is
integration's job through human review, outside the scope of this ticket.
