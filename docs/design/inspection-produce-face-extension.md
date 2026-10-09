---
title: Inspection Produce-Face Extension (doc/simplify produce change) and Inspection workflow Generalization
category: design
tags: [finalized design, inspection, doc inspection, simplify inspection, generalization]
status: active
updated: 2026-09-28
---

# Inspection Produce-Face Extension (doc/simplify produce change) and Inspection workflow Generalization

> This document graduated from `notes/discussions/260924-巡检产出面扩展-设计稿.md` (filed with ticket t260925-01).

> Origin: the host's verbatim request in the 260924 session — "besides integration's inspection, I also need doc
> inspection, and code simplify inspection"; four follow-up rulings: **①doc change is limited to documents under the docs
> directory (code comments are out of scope); ②simplify definitely has to run integration, full integration; ③one ticket per
> issue, and it needs a workflow different from dev-lane; ④out-of-the-box declaration must be feasible, and other projects
> must also be able to add their own inspection workflow;** ⑤the write-set stance diverges per workflow (host addition on
> 260924: "doc and dev-lane are different workflows, so the write-set restrictions certainly cannot be the same") — each
> workflow's **whitelist is different**; the shared prohibitions (no writes to the knowledge-base ledger / protection list /
> the single human-review entry) still apply across the whole chain. This draft was written by the integration role from the
> current inspection implementation. **This document states only "what and why"**: interface shapes and implementation
> details are settled in the implementation ticket; for landing status and progress, consult the epic proposal/ticket.

## Problem

1. **One sentence**: the current inspection **only produces a report** — once the report is done, somebody still has to act on
   it and make the edits, so human effort is the bottleneck; yet doc drift and "simplifiable surface" are exactly the two
   classes of problem an agent could fix directly and hand over for human review.
2. **Background knowledge** (what an outsider needs to know first):
   - **Inspection** = on the schedule declared by the project, open one ticket per period, work in the project's own lane, land the output in the ledger, and finally go through human review.
   - The current inspection's **red line is "produce only reports and ticket-opening suggestions, never edit code directly"**; the reviewing agent is pinned down by a **read-only sandbox** and physically cannot change files.
   - The engine **already has five "inspection faces"** (test / doc / stage / mechanism / simplify) plus suite declarations in three tiers,
     but apart from the test face they are **all unwired and have never run**.
   - The project side declares which inspection instances to run (face, schedule, timezone, whether to run the suite) in a single `inspection.yaml`.
   - Two general mechanisms already exist and can be reused: ①**period tickets** (one ticket per period, deduplicated by "instance + period number"); ②**external workflow templates**
     (a project can put workflow classes in its own repo and the engine will run them once it recognizes them — see Project External Workflow Templates).
3. **Evidence**:
   - Current state: the two instances `docs-sync` (doc face) and `simplify-face` (simplify face) **are already enabled in
     sandbar's declaration**, but only the test face has a schedule on the dispatcher — they have never run (zero ledger records).
   - User evidence: the host explicitly wants doc/simplify inspection to **produce a change for human review**, not to keep giving suggestions.
   - Generalization evidence: other projects under the same engine (nusuyou and others) have no `inspection.yaml`; and the host explicitly requires that
     **other projects work out of the box too, and can even add their own inspection workflow**.

## Requirement

Every item can serve as an acceptance criterion:

1. **The doc face produces a change**: the inspection agent directly produces **documentation changes** **inside the lane** (**limited to the project's docs directory**;
    code comments are not touched), and the change is then handed over for human review.
2. **The simplify face produces a change**: the inspection agent produces **code changes**; **before producing a change it must run the full integration suite and pass**
    (no change may be produced on a red light).
3. **One ticket per period**: reuse the existing period-ticket mechanism (one ticket per instance per period, same-number deduplication, ledger trace).
4. **A dedicated inspection workflow**: the change-producing inspection is **not chained with the development workflow (dev-lane)** — it has none of the developer stages
    "implement / arbitrate / design the integration tests"; its stage order is "lane → produce → machine check → report → human review".
5. **Human review is the only merge entry**: after looking at the diff, the human reviewer decides **approve (merge into the main tree) / reject (discard this period's change)**;
    **never auto-merge into the main tree**, an agent may not sign for itself, and the signer's identity is injected by the caller.
6. **Generalization (out of the box)**: all three faces (test / doc / simplify) are driven by **project declaration** — the doc root, code root,
    verification commands, write-set scope, excluded faces and schedule all live in each project's inspection declaration; **the engine side must not hardcode any
    sandbar-specific path**; undeclared = zero behavior change. **Default convention**: the engine ships a **default doc root = `docs`**
    (host 260924: "what we have by default right now is the docs directory"), and treats it as the default protected face; **the protected face (source of truth and expected
    values) is likewise a project declaration item** — today sandbar-specific protection lists are hardcoded in the engine (`docs/design`, `server/roles`
    and so on), which would misfire for other projects and is data that this generalization must move out along with everything else; **once the face is project-declared, ticket creation can
    mechanically check "write set ∩ project protected face", moving today's "one human-review round trip stuck at the landing gate 5 hours later" forward to being named on the spot at ticket creation**.
    **The write-set stance diverges per workflow**: dev-lane = code + integration test assets (as it is now); **doc inspection = the project's doc root only** (code comments are not touched);
    **simplify inspection = the project's code root + the L1 unit test directory** (L1 is white-box, and **rewriting it along with the implementation is not a contract break** — the
    layering stance already held in this repo), **excluding L2/L3 scenario assets (integration/)**; the shared **prohibitions** (no writes to the knowledge-base ledger notes/, the source-of-truth
    protection list, the single human-review entry) still apply across the whole chain — what diverges is each one's whitelist, not the shared red lines.
7. **A project may bring its own inspection workflow**: a project can not only choose among the engine's three built-in faces, but also **add its own inspection workflow**
   (reusing the external workflow template loader) and point to it in its own inspection declaration; **that workflow brings its own write-set
   stance** — dev-lane's mechanism of "automatically folding in integration/" **must not be carried over to inspection workflows** (test assets are not folded into the
   whitelist just because an inspection needs them).
8. **Zero findings must also be explicit**: if there is nothing to change this period, it must explicitly declare "zero change this period" and give the evidence face;
   **no faking a change just to fill the quota**, and no empty-shell zero output either.
9. **The safety face is not downgraded**: the write-set whitelist and the protected-path gate remain in force (writes to the knowledge-base ledger notes/ are still prohibited; the
   source-of-truth protection list still blocks); when the doc face runs into a document on the protection list, it **names it and lists it for human review** rather than silently skipping it or
   hard-failing the whole period; after the human review **grants clearance, the landing is completed within the same period ticket** (authorize → re-run the production in the same ticket → human-review merge),
   **without crossing periods or opening another ticket**.
10. **One ticket per period, everything closed within the ticket**: this proposal introduces no cross-period mechanism for late landing or postponement — "discover → produce → self-check →
    report → human review (including protection-face clearance) → merge/reject" all happen within the same period ticket, consistent with the current inspection's period-ticket model.

## Nongoal

- **The semantics of the test (integration) face are not changed**: the verification face still **produces only a report** — a verification face that edits code itself would be testifying on its own behalf.
- No **auto-merge into the main tree** (human review is the only entry); no agent self-signing.
- The **notes/ knowledge-base ledger is not touched** (tickets/ledgers are managed directly by main).
- **No rewriting of code comments** (that belongs to the simplify face); no out-of-scope refactors such as "rename/move" (the simplify face only does simplifications
  it is confident about and that have a clear payoff).
- **The simplify face must not modify L2/L3 scenario assets to "fix the green"**: if scenarios go red after a refactor, making the light green again by editing scenarios is not allowed (a green-light
  shortcut); if scenario assets genuinely must change = external behavior changed, name it for human review or open a separate ticket. **L1 unit tests may be rewritten along with the implementation**
  (white-box, not a contract net), but they must: ①be self-consistent within the same change; ②explain item by item, in the "test asset change review" section of the report, whether what changed is
  an internal assertion or a weakening of coverage; ③**changes of the delete-a-test / reduce-assertions / loosen-assertions kind = red**, requiring explicit human-review clearance.
- **The doc face must not edit code out of bounds**: any file outside the doc root (including code comments and build artifacts) is not in the whitelist;
  out-of-bounds = rejection and naming.
- Do not revive the template family retired on 260904; no hot reload (it takes a restart to take effect; the granularity of "taking effect" is described as it actually is, see KI-113).

## Proposal

### High level: three things

1. **A new inspection chain: the producing inspection.** Standing alongside the "report-only" verifying inspection: inside the lane an agent edits files →
   machine check (see point 2 below) → the **change itself** plus evidence is landed as a report → human review reads the diff and rules **merge / reject**.
   One ticket per period, and the ticket face is precisely "this one change proposal".
2. **Each face's own self-check threshold (the key difference between the two faces).**
   - **doc face**: changes are limited to the declared doc root; before producing a change, run a **doc self-check** (whether the index / links / referenced documents
     exist — changing a document must not leave references broken).
   - **simplify face**: changes are limited to the declared code root; before producing a change, **run the full integration suite and it must be green** (host ruling 260924).
     This is a hard threshold: if it is red, no change is produced, rather than "handing it over for human review with a red light".
3. **Generalization: both faces and workflows are driven by project declaration.** The engine provides the three face **templates** and the producing inspection **chain**;
   a project supplies parameters in its own inspection declaration (roots, verification commands, write set, excluded faces, schedule), or simply points at
   **its own inspection workflow** (going through the external workflow template gate). Zero project hardcoding on the engine side, zero behavior change when undeclared.

### Key tradeoffs (why these choices)

- **The verification face does not edit code; the producing face does**: a face that can both edit code and judge itself would be testifying on its own behalf. So the test face stays
  report-only, and code-editing capability is given only to doc/simplify.
- **simplify's full-integration threshold is expensive but necessary**: handing an automatic refactor to human review without verification = pushing the regression-testing work onto the human.
  Better to spend one extra full integration run per period (about 3.5 minutes on a single exclusive ticket; under concurrency it multiplies to 10~40 minutes as measured today —
  this must be handled together at implementation time via "width limiting / pinning").
- **Human review is the only entry**: isomorphic with dev-lane's merge gate — the diff is laid out, the human signs, and only then does the engine merge; a rejection = this period's
  change is discarded (with a trace), and the human can open a fix ticket based on it.
- **"Hitting the protection list" must be named rather than skipped**: drift in a source-of-truth document is exactly what most needs fixing; silently skipping it would make people think "there is no drift".
- **Generalization lands in "declaration" rather than "code branches"**: face parameters come from the project declaration, and a project can add its own workflow —
  this points the same way as the Project External Workflow Templates just established in this repo, reusing its loader directly.

### Tie-back

This proposal → solves the **Problem** items "report only, humans do the editing" and "not available out of the box" (the producing inspection chain + declaration-driven faces/workflows)
→ satisfies **Requirement** 1–9 → avoids the **Nongoal** items "do not change test-face semantics, do not auto-merge into the main tree, do not touch notes/, do not rewrite comments".

## Running under the land-and-certify flow

This document's flow assumes a lane and a merge entry into main. The buffer design changes where a change is delivered and what "proved" means, so the following adjustments follow — and they are cheap to make now, because the two producing faces have been declared but have never run (zero ledger records), so nothing has to be migrated.

1. **Read base: `main`, pinned at period start.** The report-producing faces review what has been delivered, because that is what the operator can act on and because the delivered history is linear, one landing per ticket, which makes a finding traceable to the landing that introduced it. What they must not do is read "whatever main is now": the revision is pinned when the period opens and recorded with the period. A finding is only falsifiable if it names the revision it was observed against, and the evidence check has to run against a fixed revision rather than a moving one.
2. **The evidence check gains a second target, not a second base.** A finding whose quoted content no longer exists in the newest state is a finding about something fixed ahead of delivery: it is downgraded rather than turned into a ticket. This reuses the mechanical verification that already exists (the file exists, the line is in range, the quote matches) with the newest state as an additional target.
3. **Producing faces land like any other work.** A face that produces a change lands into a line and is delivered with a batch. Its human review answers "is this change worth making"; the batch's signature answers "may this content be delivered". Keeping the review as a direct merge entry would leave an uncertified door into main — the door the buffer design exists to close.
4. **The suite tier must not be charged twice.** A producing period declares the full suite today. If its change is delivered through a line whose candidate is certified, the same content is being proved twice: either the period relies on the candidate's certification, or it says explicitly what its own run is for and why the candidate's is not enough. There is one source of "passed", and it is named.
5. **The faces have to cover the new surfaces, or the mechanism ships uninspected.** The buffer adds mechanisms (a line, a landing, certification, the freeze, remedy work, the relation ledger) and stages (landing, certification, batch). Each face's declared scan surface must include them: the mechanism face for the new mechanisms, the stage face for the new stage chain, the test face for the new flow's coverage bar, the doc face for this batch of design documents. Two existing constraints apply: the face vocabularies are locked as one set, and coverage is declaration-driven — an enabled instance with a schedule and a scan face, or nobody looks at it.
6. **A finding has to be able to point at something that is not a file.** The evidence model is a path, a line and a quote, verified against files; the buffer's decisive facts — a certification, a freeze, which tickets a batch covered, a withdrawal — live in ledgers rather than files. To review that layer, the evidence model must admit a non-file subject. Without it the mechanism face stops at the code and the ledgers are never inspected.
7. **Watching the fleet is not this mechanism's job.** The new model creates a class of silent stalls — a ticket waiting for a certification that never arrives, a line frozen with no remedy work in flight, a pin whose machine is gone. Those are states of the running fleet and belong to the ticket patrol and the watchdog; inspection reviews artifacts. It is written down here only so that the two are not confused: inspection examines things, the patrol watches the board.

The loop this creates — a finding, the work opened from it, the landing that work made, the batch that carried it — is a chain of relations, and it has consumers of its own: measuring a face by what it catches and what it costs, closing a finding when the quoted content is gone rather than when a ticket was opened, and not filing the same finding twice. See [Ticket Relations v1](ticket-relations-v1.md).

## Appendix 1: Revision points against the current implementation (not part of the design body; for epic cross-reference)

1. The inspection red line diverges per face: the test face "produces only a report"; the doc/simplify faces "produce a change for human review", so the red-line wording must be rewritten.
2. The reviewing agent's read-only pinning is tiered per face: the doc/simplify faces get **restricted write access** (write set = the declared roots), the test face stays read-only.
   The write-set stance **diverges per workflow** (doc = doc root; simplify = code root + **L1 unit test directory**, excluding L2/L3
   scenario assets); the landing gate is fail-closed per whitelist and names out-of-bounds files; **dev-lane's "automatically fold in integration/"
   mechanism must be narrowed per workflow and must not be carried over to the inspection chain**.
2b. Unit-test-change guardrails (simplify face): the report gets a "test asset change review" section explaining each change; a new machine warning is added —
   changes of the delete-a-test / reduce-assertions / loosen-assertions kind are ruled red and require explicit human-review clearance (preventing "edit the test to fix the green").
3. A producing inspection chain is added (a chain separate from dev-lane): lane → produce → check → report (including the diff) → human review (merge/reject).
4. Face prompts lose project hardcoding: doc root, index files, code root and verification commands are injected from the declaration instead.
5. The declaration face is extended: a project can point to its own inspection workflow (wired to the external template loader).
6. The two items "explicit zero-change declaration" and "name what hits the protection list" must land in the report contract; protection-face clearance goes through an
   authorize → complete-the-landing loop "within the same period ticket" (aligned with the current inspection's period-ticket model, **without crossing periods**).
7. Where the suite tier (full integration) sits in a producing inspection: on the simplify face it is fixed as "run before producing a change".

## Related documents

- [Design Document Writing Guide](design-doc-writing-guide.md)
- [Project External Workflow Templates](project-external-workflow-templates.md) — "a project bringing its own inspection workflow" reuses its loader directly
- [Known Issues (KI)](../../notes/debts/known-issues.md) — KI-111/116/117 (inspection budget / zero signal / unbounded evidence face) are lessons this proposal must inherit at implementation time
- [Develop Buffer v1 (lane → develop → main)](develop-buffer-v1.md) — where a change is delivered and what "proved" means, which is what the adjustments above follow from
- [Project Fact Ledgers v1 (where the project's own facts live)](project-fact-ledgers-v1.md) — the store the inspection ledgers belong to, and the entity/observation split
- [Ticket Relations v1 (what one ticket is to another)](ticket-relations-v1.md) — the finding → work → landing → batch chain
