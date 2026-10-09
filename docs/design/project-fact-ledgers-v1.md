---
title: Project Fact Ledgers v1 (where the project's own facts live)
category: design
tags:
  - fact ledger
  - known issues
  - store
  - multi-user
status: active
updated: 2026-10-09
related:
  - mode: dependency
    target: ticket-relations-v1.md
    note: the relation ledger is a member of this family and follows the same recording rules
  - mode: dependency
    target: develop-buffer-v1.md
    note: the certification ledger and the landing record are members of this family
  - mode: dependency
    target: knowledge-base-design.md
    note: how documents and knowledge are kept — the split between documents and facts
  - mode: practice reference
    target: design-doc-writing-guide.md
---

# Project Fact Ledgers v1 (where the project's own facts live)

## Problem

**One sentence:** the project's own facts — what is known-broken, which case covers it, what the fleet is doing, what capacity it holds, what was asked of whom, how a run ended — are spread over two homes that were chosen by accident rather than by rule, and the ones that matter most sit inside the repository, where every worker reads a copy frozen at the moment it branched.

**Background knowledge** (what someone who was not involved needs first):

- A **fact ledger** here means a record of things that happened or are known, kept so that later work can be governed by it. It is not code: it has no diff relationship with the code, and its entries are not reviewed the way changes are.
- Two homes exist today, and both are real and in use:
  - **Inside the repository** — versioned by version control, reviewed as diffs, and copied into every worktree. Convenient for a reader who wants history; stale for a reader who wants the present.
  - **Outside the repository, in the project's own store** — written by the running system, shared by the several processes of one machine, and already in use by every project in the same shape. Live for a reader who wants the present; and whatever version control used to give (who, when, why, history, backup) is now something the store must supply itself.
- Two shapes must not be confused: a **fact** (appended, never rewritten; a correction is another fact) and **current state** (one row, updated, and read as a whole). Ledgers in the second shape are safe to update only because reads and writes are serialised.

**Evidence** that the current arrangement is costing us:

- The fault-mode ledger is 222 entries in one prose file inside the repository. A lane reads the copy it branched with, so an entry registered ten minutes ago is invisible to work already in flight — for a ledger whose entire purpose is to be read *before* designing a change's proof.
- The same question — "which known failures does my change touch?" — is answered by searching prose, while the family's real value is the join between a fault mode, the case that locks it, and how that case last ran. The join exists only in prose.
- Several machine-read baselines also live inside the repository, and their requirement is the **opposite** of the fault ledger's: they judge a run, so they must be the version that matches the code under test. Treating them as one family with the fault ledger would break one of the two.
- The store outside the repository already holds each project's event log, action log, capacity state, authorisations, requests and run outcomes, in the same shape across seven projects. What is missing is not a home; it is **the rule saying which family goes where** — and the answer to what happens when the machine stops being one machine.

## Requirement

### Goals

1. Every family of the project's own facts has a declared home, and the criterion for the home is **what a reader must read it *with*** — not what the record looks like.
2. A fault-mode ledger is read **as of a version**: the reader can state which revision of the ledger its change was designed against, and can pull a newer one deliberately rather than by accident.
3. Every record names its writer and the reason it exists. Nothing depends on identity being inferable from the machine it was written on.
4. Facts are append-only; corrections are new facts. Current state is read as a whole and read consistently.
5. Identifiers are minted and never reused, and are never derived from a position inside a file or from an accident of what happened to be alive.
6. Ordering comes from the ledger itself, not from a clock.
7. Every record carries the project it belongs to, and can be interpreted without a machine-local path.
8. **Availability is explicit**: a required ledger that cannot be read is a loud failure, never read as "nothing known".
9. **Backup is declared and exercised** before the first family moves: what the backup is, how it is restored, and who notices a loss.
10. **Growth has a policy**: fact logs only grow, and rotation or compaction is a declared operation that is safe while writers are running.
11. **Later goal — real sharing.** The same read path serves several people on several machines. This is what "multi-user" means as a target, and it is not achieved by pointing several machines at one file. What it needs is a **single writing authority** (a service that owns writes) or storage with real transactions. Phase 1 does not build it, and must not foreclose it.
12. **Phase-1 readiness for goal 11**: reads go through one pull interface that answers as of a version, and no record depends on a machine, a path or a clock — so that moving the truth behind a service changes the plumbing and not a single reader.
13. The rules that govern these facts today — who may write the fault ledger, what must accompany a repair — survive the move unchanged. This design changes where facts live, not who may write them.

### Stakeholders

- **The host** — cares that "why does this exist" and "what is known to be broken" are answerable in one look, and that losing a ledger is an incident rather than an amnesia.
- **Whoever attributes and registers faults** — cares that registration is a durable fact with a reason attached, not a sentence someone may or may not find.
- **Lanes and workers** — care that the fault knowledge they are required to consult is the current one, and that a ledger they cannot reach tells them so instead of quietly looking empty.
- **A second person or a second machine** — cares that the read path survives being shared, without a rewrite.
- **Future maintainers** — care that the store is not a second place where the same truth lives.

### Upfront constraints

- Nothing that is already a truth elsewhere is duplicated: the workflow engine's own history is the truth about tickets, and the store may only hold projections of it.
- Long prose whose review mechanism is a diff stays a document.
- The baselines that judge runs are decided by their own criterion, not by this document's family rule.
- Phase 1 introduces no new infrastructure dependency; the store already exists.
- The working system must survive the move: no family is migrated in a way that leaves a reader without its input.

## Nongoal

- **Not moving the workflow engine's own history.** It is the audit truth; the store holds projections and never a second copy.
- **Not moving design documents and other long prose.** Their review mechanism is a diff; a fact store would remove the review and add nothing.
- **Not moving the run-judging baselines under this rule**, and not sweeping them along with the fault ledger. Their requirement (matching the code under test) is the opposite of the fault ledger's (being current).
- **Not building the shared service this cycle.** Goal 11 is a declared target, not this cycle's work; phase 1 is single-machine on purpose.
- **Not making the store the answer to every piece of project knowledge.** A family whose home cannot be argued by goal 1 stays where it is.
- **Not cross-project facts.** Each project's store stays its own.
- **Not migrating all families at once**, and not migrating a family with no identified consumer.
- **Not solving growth by hand-editing a log**, and not letting a store grow unbounded with no declared policy.
- **Not changing write authority as part of the move**, and not letting the move become an occasion to loosen it.

## Proposal

### High level

**One criterion decides a home: what the reader must read it *with*.**

- Knowledge of what is broken must be read **current** — an entry from ten minutes ago has to reach work that is already in flight. That points out of the repository.
- A baseline that judges a run must be read **matching the code under test**. That points into the repository, beside the revision.
- A document must be read **as reviewed**. That is a diff, so it stays a document.

That single sentence is the whole of the family rule, and it is why the fault-mode ledger and the run-judging baselines end up in different homes despite looking alike.

Three homes follow:

1. **The repository** — anything whose meaning is tied to a revision of the code, and all long prose. Version control is doing real work here: it supplies history and review, which the store would have to rebuild.
2. **The project's own store, outside the repository** — the project's operational facts: fault modes and their coverage, what the fleet is doing, capacity, authorisations, requests, findings, how runs ended, and the certification and relation ledgers the buffer flow needs.
3. **The engine's own history** — the truth about tickets. The store may hold projections for reading and for faces, never a competing copy.

### Phase 1 — single machine, several processes, one user

Facts are appended as records in the store and read through **one pull interface that answers as of a version**. That interface is the thing that makes the later move cheap: a reader never opens a file, so what is behind the interface can change without changing readers.

Alongside it, four rules that exist because leaving version control has a price:

- **The writer and the reason are recorded on every record.** Version control used to answer "who did this and why" for free; once facts leave it, the record must carry them. The reason is mandatory for the same reason it is mandatory for relations: a record whose reason cannot be written is a record that should not exist.
- **Identifiers are minted, never reused, never positional.** This project has already seen a ticket identifier handed out twice because the next number was derived from what happened to be alive; a reused fault-mode number would silently rewrite what every report that cited it meant.
- **Ordering comes from the ledger, not the clock.** The clock assumption is exactly the one that breaks when goal 11 arrives.
- **A generated read-only projection stays in the repository.** It serves the reader who wants to see a change in review or reconstruct history offline, and it means a lost store is a recoverable incident. It is generated, so nobody hand-edits it and it cannot conflict.

Availability is treated as part of the contract, because consulting the fault ledger is part of a ticket's normal inputs: a ledger that cannot be read is reported as unreadable and the work stops, rather than proceeding on "nothing known" — the same discipline as a gate that refuses to call missing data green.

### Phase 2 — several people, several machines (the declared target)

Real sharing is a change of writing authority, not a change of file location:

- The truth moves **behind a single writing authority** — a service that owns writes, or storage with real transactions. Writers no longer append to a shared file.
- What makes concurrent appends safe on one machine — the guarantee that a single small append is not interleaved with another — **does not hold over a network filesystem**, and file synchronisation produces conflicts rather than records. Sharing one log file between machines is therefore not a weaker version of the target; it is a different and broken design, and it would produce exactly the kind of quiet divergence this project has already spent effort cleaning up.
- Because phase 1 reads through one interface, as of a version, with records that name no machine, path or clock, this arrival is a plumbing change. That is the entire reason phase 1 is shaped this way rather than simply "moving a file".

### The order of work, and why

- **First family: the fault-mode ledger.** Its staleness already costs us, its consumers are known, and its join to cases and results is the value that prose cannot express.
- **The run-judging baselines stay put** until decided on their own terms. Their requirement is the opposite of the fault ledger's, and the fastest way to break both is to treat them as one family.
- **Before the first move: backup and availability.** Both are cheaper to design than to retrofit, and the fault ledger is on the critical path of every change's proof.

### Key tradeoffs, stated plainly

- **Leaving version control trades a free history for a designed one.** The store must now supply who, when, why, history and backup. That is the real price of the move, and it is why the writer-and-reason rule and the projection are part of phase 1 rather than "later".
- **A pull interface is overhead while there is one machine.** It is paid now so that goal 11 does not become a rewrite.
- **Single-machine phase 1 means "multi-user" is proven by design, not by use.** The readiness criteria in goal 12 are what carry that weight; without them, phase 1 would be a local convenience that phase 2 has to undo.
- **Keeping a projection risks two readers disagreeing.** It is deliberately read-only and generated, and the store remains the truth — the same relationship the store has to the engine's history.

### How this ties back

This proposal addresses the **Problem** by replacing an accidental arrangement with a rule (goal 1's criterion) and by giving the fault knowledge a home where being current is possible; it satisfies the **Requirement** by versioned reads (2), recorded writers and reasons (3), the fact/state split (4), minted identifiers (5), ledger ordering (6), project-tagged and path-free records (7), loud availability (8), declared backup (9) and growth policy (10), and by declaring real sharing as the target (11) with the phase-1 properties that keep it reachable (12) while leaving write authority untouched (13); and it avoids the **Nongoal** items by not duplicating the engine's truth, not moving documents, not sweeping the run-judging baselines along, not building the service this cycle, not admitting families with no consumer, not crossing projects, not migrating everything at once, not editing growth by hand, and not loosening authority in the name of a move.

## Related documents

- [Ticket Relations v1 (what one ticket is to another)](ticket-relations-v1.md) — the first relation ledger in this family, with the same recording rules.
- [Develop Buffer v1 (lane → develop → main)](develop-buffer-v1.md) — the certification and landing ledgers are members of this family.
- [Knowledge Base Design](knowledge-base-design.md) — the split between documents and facts.
- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document follows.
