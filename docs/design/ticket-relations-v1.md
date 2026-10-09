---
title: Ticket Relations v1 (what one ticket is to another)
category: design
tags:
  - ticket engine
  - relations
  - dependency
  - attribution
status: active
updated: 2026-10-09
related:
  - mode: dependency
    target: develop-buffer-v1.md
    note: the buffer flow is the first consumer — a red is remedied by a new ticket, and the freeze exemption has to name what the fix repairs
  - mode: dependency
    target: failure-classification-protocol-v1.md
    note: how a red is classified and attributed — attribution is what creates the causal relation
  - mode: practice reference
    target: design-doc-writing-guide.md
---

# Ticket Relations v1 (what one ticket is to another)

## Problem

**One sentence:** tickets today cannot say what one ticket *is* to another one, so the reasons tickets exist in relation to each other survive only as prose inside them, and nothing in the engine can act on them.

**Background knowledge** (what someone who was not involved needs first):

- A ticket is a unit of work with a life cycle of its own — it is opened, worked, certified and closed, and the engine drives that life through stages.
- The only ticket-to-ticket structure that exists today is **the epic tag**: a piece of text written on a ticket, whose single consumer is a scan that lists in-flight tickets carrying no epic. It is a label with one consumer, and it works because that consumer exists.
- **Rework** is a relation in the opposite direction: a ticket is sent back to an earlier stage of *itself*. It is a relation inside one ticket, not between two.
- The develop buffer is arriving (see the related design), and it brings a class of ticket whose entire reason for existing is another ticket: when a certification is red and the fault belongs to a landing, the remedy is a **new ticket against the buffer**. Which ticket's landing it repairs is the whole content of that work.

**Evidence** that this is a problem, not a theory:

- The buffer flow cannot be built honestly without it. The freeze exemption has to be granted to remedy work, and granting it requires knowing *what* that work repairs; the benefited ticket's outcome must be able to say it was repaired, or withdrawn, and by what.
- Today the same fact has to be written as prose in the ticket body. Prose is not readable by the engine, cannot be checked, and cannot be shown on a face; the reader has to already know the story.
- A reader of the ticket list cannot tell that two tickets are one problem seen twice, that one exists *because* another broke, or that one has to happen before another.
- **The anti-pattern this must avoid has already bitten us here.** A link that nobody reads is worse than no link, because it will be believed. In a recent incident this project's own submission carried a field the engine accepted silently and never interpreted, and eight tickets came out of it that never had the thing the field named. A relation without a consumer is the same shape of hole: it looks like it records something, and it decides nothing.

## Requirement

### Goals

1. A relation between two tickets can be recorded once and read from **either side**.
2. Every relation kind must name the behaviour it changes. A kind whose only consumer would be a human reading it does not qualify as a relation kind.
3. Recording is **append-only**: a relation is a fact about what happened, never an editable attribute of a ticket, and a mistaken relation is corrected by recording a correction rather than by rewriting it away.
4. Every relation carries who recorded it, on what evidence, and a reason in words. A relation whose reason cannot be written is one that should not be recorded.
5. **Authority is part of the design**: for any relation kind whose effect is a permission, the ticket that benefits may not be the one that records it.
6. The causal kind alone (phase 1, below) must make two behaviours possible: landing on a frozen buffer is permitted for remedy work that names what it repairs, and the benefited ticket's outcome can say it was repaired — or withdrawn — and by what.
7. Remedy work that names nothing it repairs is **incomplete** and does not get the permission in goal 6.
8. The structures that already exist — epic membership and rework lineage — are readable in the same place as the new relations. One place to look, not three.
9. An ordering kind (phase 2) may not be introduced until it can refuse to create a cycle, and it must not change the meaning of any gate for tickets that predate it.
10. The ticket's own face, and the promotion record that takes a certified prefix further, both show the relations of the tickets they contain.
11. No relation kind may change the meaning of an existing gate for tickets that predate it.
12. **A second kind is load-bearing in phase 1: work that exists because a finding produced it** (inspection's loop). Its consumers are different from the first kind's — not a permission, but the closing of a finding, the deduplication of a finding across periods, and the evidence that decides whether a face earns its keep.
13. **An entity and its observations are different records.** A finding persists; each period records an observation of it, naming the revision it was seen against. Without that split, "how long has this been reported" and "was this seen again" cannot be answered, and dedup has to lean on content alone.
14. **Whether a finding is closed is decided by evidence, not by a ticket's state.** The quoted content no longer existing in main is a checkable condition; "a ticket was opened" is not.
15. **Relations are project-level facts, not line-level ones.** The work that answers a finding may land on a different line and travel in a different promotion, so the ledger lives in one place and is read across lines.


### Stakeholders

- **The host / the person signing a promotion** — cares that "why does this ticket exist" and "is the chain closed" are answerable in one look, without reading a story.
- **Whoever attributes a red** — cares that the attribution, once made, is a durable fact and not a sentence that the next reader may or may not find.
- **Lanes and workers** — care that nothing here lets them award themselves a permission.
- **Future maintainers** — care that the vocabulary stays small and each word means something the system actually does.

### Upfront constraints

- Relations are facts with a direction; the two tickets involved belong to the same project (cross-project relations are out of scope).
- Nothing here may become a scheduling engine in this cycle.
- The flow that exists today keeps working exactly as it does now, for the tickets already running in it.
- The storage shape is the implementation ticket's business; this document fixes the concepts, the vocabulary and the rules of who may record what.

## Nongoal

- **Not a general dependency solver or scheduler this cycle.** The ordering kind is phase 2 precisely because scheduling changes the meaning of gates that already exist.
- **Not transitive closure, critical paths, or priority inversion handling.** Each of those is a decision the engine would then have to defend; we have no case that needs them yet.
- **Not a free-form "related to" link.** A kind that changes nothing is not admitted (goal 2).
- **Not a graph visualisation in this cycle.** A relation must first exist and be shown on a face; drawing it is a separate question.
- **Not cross-project relations**, and not relations to things that are not tickets.
- **Not retroactive.** Tickets that predate this do not acquire relations, and no existing gate re-judges them.
- **Not a rework of what an epic means.** Epic membership is folded in for reading; it does not become a dependency, and a ticket is still allowed to be unfiled.
- **Not a way for a ticket to edit its own relations** (goal 5), including "I am the fix for X".
- **Not storing both directions as two rows.** One fact is stored once; the other side is derived when read.

## Proposal

### High level

One append-only ledger of **typed, directed facts between tickets**. A record says: this ticket, that ticket, which kind of relation, who recorded it, when, on what evidence, and why in words.

The load-bearing rule is this: **a kind is admitted only together with the behaviour it changes.** The ledger is not a place to keep notes; every kind in it is read by something that then acts differently. A kind nobody reads is refused admission, because a relation that changes nothing will still be believed by a person reading the list — and being believed while deciding nothing is worse than being absent.

The second rule is that **permissions come from two things at once, never from one**. Landing on a frozen buffer requires both (i) the work was opened as remedy work and (ii) the ledger names what it repairs. The kind of work carries the capability; the relation carries the subject. A ticket that has only the first can do nothing with it, and a ticket that has only the second has not been opened as remedy work at all. This closes the self-declaration hole from both sides, which is deliberate: the exemption has to be impossible to award oneself, and the only way to make that structural is to require a fact that the ticket cannot write about itself.

### The vocabulary

**One kind of relation that is not a ledger entry, deliberately.** A landing may span several repositories, and a change to a base repository may require the dependents to be proved as well. That fact belongs to the project's layout and changes rarely, so it is a **declaration** (base repository, dependents, and the proof rule) rather than an appended record: the ledger's subjects are tickets, and keeping repositories out of it preserves the rule that only kinds with a live consumer enter the vocabulary. A landing that spans repositories cites the declaration.


Small on purpose. Phase 1:

- **repairs** — this ticket exists to repair a landing that another ticket made (or the defect that landing introduced). Its consumers: the freeze exemption, and the benefited ticket's outcome record.
- **originates from a finding** — this work exists because an inspection period produced a finding it answers. Its consumers: closing the finding when the quoted content is gone, refusing to file the same finding twice, and measuring whether the face that produced it earns its keep by what it catches against what it costs.

Phase 1, folded in for reading (not new kinds, and not changed in meaning):

- **epic membership** — already a tag with one consumer; it lands in the same place so that a reader has one place to look.
- **rework lineage** — already recorded inside a ticket; it lands in the same place for the same reason.

Phase 2, named now and deliberately not built now:

- **ordering** — this ticket's landing must happen before that ticket's. Its consumer is readiness. It is phase 2 because ordering decides when work may proceed, which is exactly the class of change that must first run where it cannot judge the tickets that already exist.

### Details worth writing down

- **What a record carries, and why the reason is mandatory.** Two tickets, the kind, the recorder, the moment, the evidence (which red, which certification, which observation) and a reason in words. The reason is not decoration: it is the thing that makes the relation reviewable by a person who was not there, and requiring it filters out relations that are guesses.
- **One direction is stored; the other side is derived.** If both directions were stored as two facts, they would drift, and a reader could not tell which one was right.
- **Append-only means corrections are recorded, not erased.** A relation that turns out to be wrong is superseded by another record saying so. This means a reader must read the current state of a relation rather than its first record — and that the history of a wrong attribution stays visible, which is the point.
- **Who may record what.** The lineage the engine observes itself is recorded by the engine. The causal relation is recorded by whoever attributes the red — a person or the patrol — because attribution is a judgement. What no ticket may record is a relation that grants itself a permission.
- **Outcome, not a second kind.** Whether a repair *fixed* the implicated landing or *withdrew* it is recorded where the repair closes, not as a separate relation kind: it is the same relation with a different ending, and two kinds with near-identical consumers would drift apart.
- **What this looks like when read.** A ticket's relations are visible in both directions: the benefited ticket shows what repaired or withdrew it, the remedy shows what it repairs, and the promotion record names both the tickets it covers and the repairs it contains. A chain of repairs stays visible as a chain, because a repair that did not turn the buffer green produces the next repair, and a freeze that quietly becomes permanent is worse than the red it was hiding.
- **Phase 2's ordering, when it comes.** Its consumer is readiness on the new lane only; it refuses to create a cycle, and refusing is loud rather than silent — a cycle that is quietly broken somewhere else would move the mistake away from where it was made.

- **Where a relation is derivable, it is derived, and where it is not, a person records it.** On a main whose history is linear, one landing per ticket, the content a finding quotes can often be traced to the landing that introduced it — so the causal relation is derived mechanically rather than judged. Attribution by a person is for the cases where the trace fails, and it carries the recorder's name and reason like any other record.
- **A finding is an entity; its observations are facts.** The entity persists across periods with an identity minted from its content; each observation says which period saw it and which revision it was seen against. Closing the entity is a separate fact, and it is decided by evidence (the quoted content is gone from `main`) rather than by the state of any ticket.
- **The chain is read across lines.** A finding may describe content on one line while the work answering it lands on another and travels in a different promotion, so these relations cannot live with a line: they are project-level facts, read the same way as the certification record.

### Key tradeoffs, stated plainly

- **Append-only costs convenience.** Every reader must ask for the current state instead of trusting a row, and wrong attributions stay on the record forever. That is the price of attribution being auditable, and it is worth paying because attribution is the thing people are tempted to rewrite.
- **Requiring a reason costs friction at exactly the moment people are busy** — when a red has just been found and the pressure is to open the fix and move on. The friction is deliberate: a fix ticket with no named subject is a fix ticket nobody can check.
- **The two-part exemption is slightly more machinery than a flag.** A flag would be one line; it would also be awardable by the ticket itself. The machinery buys the property that the permission cannot be self-granted.
- **Phase 1 has exactly one new kind.** That is a feature: the ordering kind is where the design risk lives, and it should be introduced against a ledger that has already proven it is read by something.

### How this ties back

This proposal addresses the **Problem** by giving causality between tickets a durable, machine-readable home instead of leaving it in prose, and by refusing the shape of link that the incident above showed to be a hole; it satisfies the **Requirement** by recording once and reading from both sides (1), admitting only kinds with a named consumer (2), keeping the ledger append-only (3), attaching recorder, evidence and reason (4), fixing authority in the design (5), making the buffer flow's two behaviours possible (6) while refusing an unnamed remedy work (7), folding existing structures into one place to look (8), gating the ordering kind behind cycle refusal and non-retroactivity (9–11); and it avoids the **Nongoal** items by not building a scheduler, not computing closures, not admitting free-form links, not drawing graphs, not crossing projects, not judging pre-existing tickets, not redefining epics, not letting a ticket edit its own relations, and not storing one fact twice.

## Related documents

- [Develop Buffer v1 (lane → develop → main)](develop-buffer-v1.md) — the first consumer: a red is remedied by a new ticket, and the freeze exemption has to name what the fix repairs.
- [Failure Classification Protocol v1 and Mechanical Attribution](failure-classification-protocol-v1.md) — how a red is classified and attributed; attribution is what creates the causal relation.
- [Project Fact Ledgers v1 (where the project's own facts live)](project-fact-ledgers-v1.md) — the family this ledger belongs to, and the rules it shares with the others.
- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document follows.
