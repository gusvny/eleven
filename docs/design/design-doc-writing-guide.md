---
title: Design Document Writing Guide
category: design
tags: [design doc, writing guideline, guideline, discussion-first]
status: active
updated: 2026-09-28
---

# Design Document Writing Guide (Guideline)

> This file is an **operating guide**: follow it directly, do not read it as an essay.
> Audience: everyone who writes a design document under `docs/design/` (human + agent).
> **Status confirmation (260904, together with the doc-lifecycle epic)**: this guide is the
> admission standard for all finalized documents under docs/ — a document graduating from
> notes into docs must be rewritten to follow it (plain language, all four sections present),
> and anything that does not fit is sent back to notes. "Speak plain language" is at once the
> host's hard requirement for docs and the precondition for agent trust (context you cannot
> understand is not context).

## When to write one

- When you are doing a **new thing**, or **substantially changing an existing thing** (new gameplay, new system, architecture change, process change).
- Test: if speech alone cannot convey "what to do, why, and where the boundary is", write it down.

## Four-section template (copy it and fill in the blanks)

Write in the order below; **not one of the four sections may be missing**. In each section, answer only the question after the colon first, and expand after that.

---

### Problem

**Fill in three things:**

1. One sentence: what is bad about the status quo?
2. Background knowledge: what must someone who was not involved know first in order to understand this problem? (terms, history, prerequisite concepts — write them if they exist, write "none" if they do not)
3. Evidence: what makes this a problem? (symptom / data / pain point / description of the status quo)

> Self-check when done: can someone with no exposure to this at all understand "what the problem is and why it is worth solving"? If not, add more.

---

### Requirement

**Fill in three things:**

1. Goals: once this is done, which **verifiable** requirements must be satisfied? (list)
2. Stakeholders: who can decide / who is affected, and what each of them cares about most?
   - (Example: user — must be able to understand it; content — must keep the iron rules; ops — must be able to build; agent — must be able to use the doc as context)
3. Upfront constraints: which boxes must not be broken? (tech stack, performance, security, compatibility, existing architectural boundaries)

> Self-check when done: can these requirements be used as "acceptance criteria"? Rewrite anything that cannot be quantified or verified.

---

### Nongoal

**Make a list**, each item stating "we are not doing X this time, and why (or when we will)".

- Draw the boundary, prevent scope creep.
- When unsure, err on the side of one more "not this cycle" item.

---

### Proposal

**Write it on two levels:**

1. **High level (mandatory)**: the overall idea + key tradeoffs, understandable on one page. A flow or structure sketch is even better.
2. **Details (on demand)**: write only the details where "not writing them down means someone will get it wrong"; leave the rest to "see the implementation ticket / see the specific implementation doc".

**Close by tying back to the first three sections**: state explicitly that "this proposal → solves X in Problem → satisfies Y in Requirement → avoids Z in Nongoal". It only counts as finished when those three links are visible.

---

## Writing steps (do them in order)

1. Write Problem first, until "someone else can understand it" (this is the step most easily skipped).
2. Then write Requirement and Nongoal (pin the box down first; do not rush to the proposal).
3. Write Proposal last (once the first three are settled, the proposal converges on its own).
4. Read the whole thing through once, going through each section's "self-check".
5. Link it into "Related documents" and hand it to human review (knowledge-base block diff).

## Self-check list (tick before handing it over)

- [ ] All four sections present, in the order Problem → Requirement → Nongoal → Proposal
- [ ] Problem explains the background knowledge clearly enough for an outsider
- [ ] Every item of Requirement can serve as an acceptance criterion
- [ ] Nongoal has concrete items, it is not left blank
- [ ] Proposal starts from high level, details are not laid out prematurely
- [ ] Proposal states only "what and why", with no implementation details (API name / CLI command / route / field name) and no landing status or progress
- [ ] Proposal ties back to Problem/Requirement/Nongoal at the end
- [ ] frontmatter complete (title/category/tags/status/updated)
- [ ] Related documents interlinked

## Common mistakes

| Mistake | How to fix |
|---|---|
| Writing the proposal straight away | Write Problem/Requirement/Nongoal first |
| Problem is just a one-line slogan | Add background knowledge + evidence |
| Requirement written as "build an XX" | Rewrite it as a verifiable goal |
| Nongoal left blank | Write at least 1–2 "not this cycle" items |
| Proposal stuffed with code details | Move the details to the implementation doc |
| Writing landing status/progress in Proposal | Status belongs to tickets and epic proposals; the document states only "what it is" |
| Skipping the concept and writing the mechanism | Open each section with "what this is and why it is needed" |

---

## Related documents

- [Knowledge Base Design](../design/knowledge-base-design.md) — the master outline of the document-first workflow
- [Ticket Workflow Console Design](../design/ticket-workflow-console-design.md) — a complete example written to this guide
