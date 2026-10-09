---
title: Later Shapes v1 (and the doors today's work must leave open)
category: design
tags:
  - extensibility
  - multi-line
  - multi-repo
  - multi-machine
  - review criteria
status: active
updated: 2026-10-09
related:
  - mode: dependency
    target: develop-buffer-v1.md
    note: several lines and several repositories are shapes this flow expects later
  - mode: dependency
    target: project-fact-ledgers-v1.md
    note: several writers and several machines are shapes that document expects later
  - mode: practice reference
    target: design-doc-writing-guide.md
---

# Later Shapes v1 (and the doors today's work must leave open)

## Problem

**One sentence:** the shapes this project expects to grow into — several lines, several repositories, several machines, several writers, several people — are decided *now*, by small choices made while building the single-line, single-machine, single-repository version, and nothing in a ticket tells the person making those choices that a door is being closed.

**Background knowledge** (what someone who was not involved needs first):

- This project runs one operator, one machine, one line and one repository today. Each of those "ones" is a *current arrangement*, not a decision that the others are impossible.
- The later shapes are not speculation:
  - the engine's lane vocabulary **already** admits projects whose repositories sit side by side, so a landing over several repositories is a shape the system has met;
  - the store **already** serves seven projects, so "the project's own store" is already a piece of shared infrastructure;
  - the fleet is already more than a dozen workers, so "which machine runs this" is already a live question;
  - the fault ledger already has readers in work that is in flight, so "who writes while others read" is already a real situation.
- A door is only discovered at the moment it must be opened, and by then the cost is not the feature: it is a **rewrite of the records everything else reads** — the landing record, the certification record, the batch, the ticket's own outcome. That is the expense this document exists to avoid.

**Evidence**: two examples from this project's own recent history, both of the same shape — a mechanism built for one arrangement, meeting a second one. A precondition injected into every ticket's gate was satisfiable by none of them, and the fleet stopped for hours. A ticket payload carried a field the engine accepted and never interpreted, and eight tickets were created that never had the thing the field named. Neither was a bad decision at the time; both were choices that had never been asked whether they closed a door.

## Requirement

### Goals

1. **The expected later shapes are stated in one place**, each with what it needs, so that a decision can be checked against them without reading four documents.
2. **Each door is stated as a concrete tell** — what closing it *looks like* in a record, a batch or an owner — rather than as a principle. ("A record that says *the revision* in the singular" is checkable; "be extensible" is not.)
3. **The expectation is "do not block it", not "do not build it".** Nothing here authorises building a later shape, and nothing here permits closing one by accident.
4. **A change that touches a door is asked one question at review**, and the answer is recorded rather than remembered: which later shape does this touch, and does it still fit? The question is asked inside the existing review, by the existing reviewer.
5. **Where a door can be checked mechanically, it is checked mechanically.** A shape that cannot express a set of repositories should fail a check, not a conversation — anything that depends on someone remembering will be closed quietly.
6. **A door may be closed on purpose, with a recorded reason.** A list that forbids all simplification becomes a list everybody ignores.
7. **The list is short enough to read before deciding a shape**, and it is referenced from the designs it constrains.

### Stakeholders

- **The developer working today** — cares that the future expectation is concrete enough to check a design against, and does not want to be told to build for it.
- **The review, at the gate** — cares that this is one question inside the existing review, not a new gate or a new proof.
- **Whoever builds the later shape** — cares that the doors are still open and that the reasons are written down, so the shape arrives as a declaration rather than as a rewrite.
- **The host** — cares that the single-machine version is not made expensive for the sake of shapes nobody has asked for yet.

### Upfront constraints

- No new mechanism, no new gate and no new proof: one question, asked where review already happens.
- The list must not become a second design of the later shapes; each gets its own document when it arrives.
- Nothing here applies retroactively to work already running.
- It must not slow down landings: a question that costs minutes is acceptable, a step that costs a round is not.

## Nongoal

- **Not building any later shape this cycle** — no second line, no repository lines, no second machine, no shared writing authority.
- **Not designing the later shapes here.** This document states what they need and what would block them; the designs themselves come when they are built.
- **Not a completeness promise.** The list grows as shapes are discovered; its value is in the tell, not in being exhaustive.
- **Not a ban on simplification.** Closing a door on purpose is allowed and recorded; closing one by accident is what this document is against.
- **Not a new approval step.** The question is asked by the existing review; there is no new signature, no new gate stage and no separate ticket type.

## Proposal

### The shapes, and what each one needs

| Later shape | What it needs |
|---|---|
| **Several lines** (a line per line of work, per component, or per repository) | A line is a declared scope with an owner and an expected end, not a branch name; a batch is a **candidate combination**, and certification certifies that combination |
| **Several repositories** | A landing is a **set of repository revisions**, with a way to say which members must move together |
| **Several machines** | A ticket is **pinned** to one machine as a recorded fact; a move is a recorded act; one owner at a time; a returning machine is refused |
| **Several writers** | For the facts that must be read current, either a single writing authority or records that merge as a union — a shared repository is a batch, not the present |
| **Several people** | Identity is **authority** (who may sign, land, withdraw) rather than a declaration made by the caller |

### The doors, as tells

A door is closed when one of these is true. Each entry names what closing it looks like and what it costs.

| Door | Closing it looks like | What it costs |
|---|---|---|
| The revision set | A record, a batch or a certification that names "the revision" with nowhere to put a second repository | Every landing and certification record has to be rewritten |
| Moving together | A batch that cannot express "these two must land as one act" | A window in which the delivered state is broken, or a new mechanism invented under pressure |
| The line as a declaration | A line identified by a branch name, with its scope and owner implicit | Component lines and repository lines arrive as a protocol change |
| Owners as scopes | An owner attached to a person, a session or a machine | Boundary problems have nobody to belong to |
| Work that cannot move | A stage that can run only on the machine that created the worktree, or a pin nobody recorded | A machine loss takes the ticket with it, silently |
| Identity that is derived | A permission granted because of the machine, the path or a field the caller filled in | Authority becomes forgeable, and the audits mean nothing |
| Records that cannot be shared | A fact whose meaning depends on a local path, a local clock, or the order of lines in a file | The fact cannot leave the machine it was written on |
| The join | A record that can only be read as prose (what is broken, which case locks it, how that case last ran) | The ledger stays a search instead of a query |

### Where this binds

- **At review, one question:** does this change touch a door, and does the door still open? The reviewer asks it; a change that closes a door without a recorded reason is sent back.
- **In the ticket's own record:** the answer is written where the ticket's decisions are written, so the next reader sees why the shape is the way it is.
- **Mechanically where possible:** a record that cannot express a set, a batch that cannot express moving together, an identity derived from a machine — each of these can be made to fail loudly rather than be noticed late. The preference is always the check over the conversation.
- **By reference:** the two designs this constrains point here, so the list is read where a shape is being chosen rather than only where it is being reviewed.

### How this ties back

This proposal addresses the **Problem** by making the expected shapes visible before they are needed and by turning each into a tell that a working decision can be checked against; it satisfies the **Requirement** by putting the shapes in one place (1), stating them as tells (2), keeping the expectation to "do not block it" (3), asking one recorded question inside the existing review (4), preferring mechanical checks (5), allowing deliberate closure with a reason (6) and keeping the list short enough to read (7); and it avoids the **Nongoal** items by building nothing, designing nothing here, promising no completeness, banning no simplification, and adding no approval step.

## Related documents

- [Develop Buffer v1 (lane → develop → main)](develop-buffer-v1.md) — the flow that will carry several lines and several repositories.
- [Project Fact Ledgers v1 (where the project's own facts live)](project-fact-ledgers-v1.md) — the store that will carry several writers and several machines.
- [Ticket Relations v1 (what one ticket is to another)](ticket-relations-v1.md) — the ledger whose kinds and authority must survive being shared.
- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document follows.
