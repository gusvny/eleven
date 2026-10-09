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
- **The machine itself is a single point of failure, and that has nothing to do with this design.** The repository has no remote, so the code, the documents, the ledgers and the entire commit history exist on one disk. The workflow engine's history — the truth about every ticket that was ever worked — is served from a loopback address on the same machine, so it is outside version control too. The store sits in a home directory with no backup, and in-flight worktrees live in the operating system's temporary area. Losing the machine is not a slower version of moving to a new one: today there is no second copy of anything, and the knowledge of how to move it all lives in one person's head.

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
14. **Losing the machine is survivable.** Every fact that cannot be rebuilt is kept so that it can be recovered on a different machine, from a different location.
15. **What can be rebuilt is named as rebuildable**, so that backup effort goes to what cannot be — and so that a loss is a loss of work rather than a loss of memory.
16. **Moving to a new machine is a written, checkable procedure** that has been exercised at least once, rather than knowledge held by one person. It covers what must be installed, which locations must be moved, where the engine's own history lives, and how to check that the move succeeded.
17. **Sharing is not synchronising.** For the families that several people write while they are being read, the transport may not require a single shared working copy: a shared repository merges changes in batches, answers a read with whatever was last fetched, and cannot enforce that a record is never rewritten. Whatever carries those families must either serialise writes or be conflict-free by construction.

18. **A machine is a resource, not a home.** A person may work from more than one machine, and a machine may be added, replaced or lost without any ticket, session or record becoming unreachable or unreadable. Which machine produced a record is **provenance**; it is never authority and never identity.
19. **Capacity belongs to the resource; totals are a reading.** A limit is a property of the machine that owns the resources, and the fleet's total is something a reader adds up, not something one machine enforces on behalf of the others.
20. **A ticket is pinned to one machine while it is worked, and the pin is a recorded fact** rather than whatever worker happened to take it first. The pin is the simplification: because the machine is known, the worktree, the conversation and the caches may stay machine-local, and the fleet's shape stops being decided by a race.
21. **A ticket must nevertheless be movable, deliberately** — a machine can die, and the work must be able to continue elsewhere. What makes that possible is that the work is durable outside the machine (pushed commits as the checkpoint, the ticket's facts in the store, the worktree re-creatable from the branch) and that the move is a **recorded act**: who moved it, why, and from which machine to which. A move may repeat a stage; it must never silently duplicate work.
22. **One owner at a time, and a returning machine is refused.** Ownership is a single value; a transfer names the new owner; a machine that comes back after being replaced must not resume a ticket it no longer owns. A machine that stays dead is a smaller problem than one that comes back.
23. **The environment is part of the record.** A result from one machine is comparable with a result from another only if the environment is a declared fact, so the environment a run used is recorded with the run rather than inferred from where it happened.

24. **Every record carries the version of its own shape**, and a reader reads older shapes rather than demanding a migration. An unknown version is a loud failure, never a guess.
25. **Records carry references, not payloads.** What a ledger may never accumulate: credentials, tokens, private host paths, and raw model input that contains them. The rule needs forbidden examples, so that a record can be refused rather than argued about.

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
- **Not using version control as the transport for multi-writer fact streams.** It is the right home for what must match a revision and for what is reviewed as a change; for facts written by several people while they are read, it answers with a batch, not with the present.
- **Not treating a synchronised copy as a shared ledger.** Two writers on two machines appending to one file is not a weaker version of sharing; it is a design that loses the property that made local appending safe.
- **Not a disaster-recovery programme, not high availability, and not a second machine this cycle.** The requirement is that the loss is survivable and the move is written down, not that the system keeps running through it.
- **Not backing up what can be rebuilt.** Copying the large derived family would cost more than it protects and would hide which layer actually matters.
- **Not building a scheduler this cycle.** There is no automatic placement, rebalancing or draining: a ticket is pinned to a machine when it is opened, and moving one is a deliberate act by a person when the machine demands it.
- **Not running a multi-machine fleet this cycle.** The phase-1 obligation is that nothing in the records assumes a single machine, not that several machines are in use.

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

Alongside it, five rules that exist because leaving version control has a price:

- **The writer and the reason are recorded on every record.** Version control used to answer "who did this and why" for free; once facts leave it, the record must carry them. The reason is mandatory for the same reason it is mandatory for relations: a record whose reason cannot be written is a record that should not exist.
- **Identifiers are minted, never reused, never positional.** This project has already seen a ticket identifier handed out twice because the next number was derived from what happened to be alive; a reused fault-mode number would silently rewrite what every report that cited it meant.
- **Ordering comes from the ledger, not the clock.** The clock assumption is exactly the one that breaks when goal 11 arrives.
- **A generated read-only projection stays in the repository.** It serves the reader who wants to see a change in review or reconstruct history offline, and it means a lost store is a recoverable incident. It is generated, so nobody hand-edits it and it cannot conflict.
- **An entity and an observation of it are two records.** Something a ledger keeps may be an entity that persists while the facts about it are observations — seen in this period, against that revision, by this check. Without the split, "how long has this been open" cannot be answered and identity has to be re-derived from content every time. See [Ticket Relations v1](ticket-relations-v1.md).

Availability is treated as part of the contract, because consulting the fault ledger is part of a ticket's normal inputs: a ledger that cannot be read is reported as unreadable and the work stops, rather than proceeding on "nothing known" — the same discipline as a gate that refuses to call missing data green.

### Phase 2 — several people, several machines (the declared target)

Real sharing is a change of writing authority, not a change of file location:

- The truth moves **behind a single writing authority** — a service that owns writes, or storage with real transactions. Writers no longer append to a shared file.
- What makes concurrent appends safe on one machine — the guarantee that a single small append is not interleaved with another — **does not hold over a network filesystem**, and file synchronisation produces conflicts rather than records. Sharing one log file between machines is therefore not a weaker version of the target; it is a different and broken design, and it would produce exactly the kind of quiet divergence this project has already spent effort cleaning up.
- Because phase 1 reads through one interface, as of a version, with records that name no machine, path or clock, this arrival is a plumbing change. That is the entire reason phase 1 is shaped this way rather than simply "moving a file".

### Machines are resources, not homes

Today a person works from one machine, and a lot of the system quietly relies on that: the operator's console, the worker fleet, the worktrees, the agent's conversation, the capacity ledger and the caches are all properties of the machine. That coupling is not written down anywhere, and it is the kind that survives right up until someone has two machines — at which point it turns into questions no record can answer: which console is the real one, which machine's capacity counts, and whose conversation continues a ticket.

The test that decides everything is one question: **can this stage run on a machine that has never seen the ticket?** Given the store, the repository and the ticket's recorded facts — and it does not have to hold in normal operation. A ticket is **pinned to one machine** when it is opened, so ordinary work may rely on that machine's worktree, conversation and caches, and nothing has to be made portable merely to keep the fleet working. The test is the standard for the **move**, and for any stage declared movable: a machine that never saw the ticket must be able to take it over. Four couplings are tolerable under the pin, and each one is something a move has to handle:

- **The worktree.** It lives in an operating-system temporary area on the machine that created it, so the work exists only where it started. A branch that is not pushed is machine-bound by definition; a pushed commit is the durable unit of work, and the working tree above it is a cache.
- **The conversation.** The agent's session is machine-local, so a ticket that moves to another machine restarts without its context. Because every stage must already be re-runnable, this is a cost rather than a correctness problem — but it is a real quality cost, and it is the reason the *recorded* facts (the ticket, its stage notes, the reasons for a send-back) have to be sufficient to reconstruct the work without the conversation.
- **The environment.** Images, browsers and virtual environments are built on the machine that has them. A result is comparable with another result only if the environment is declared with it.
- **The fleet's shape.** Which machine runs which piece of work is not decided anywhere today: it is whatever machine's worker happens to take the work. That is only safe if the work is machine-independent — which is exactly what is being required here.

**Capacity is the one thing that stays machine-scoped, and it is not a contradiction.** A limit protects the resources of the machine that holds them, so a limit per machine is correct. What matters is that the total across the fleet is a **reading**, not an enforced number: whoever is looking adds up the fleet, and the person decides. What may never be per machine is anything that is **authority** (who may sign, who may land, what may be withdrawn) or **truth** (a ticket's state, the ledgers). Provenance — "this ran on that machine, in this environment" — is worth recording for diagnosis and comparability, and must never be what grants a right.

**Pinning is only a simplification if it is written down and if the move is prepared for.**

- **The pin is a recorded fact, not an outcome.** It is set when the ticket is opened and every dispatch respects it; left to whichever worker polls first, we would have pinning in spirit and races in practice — the worst of both.
- **The move is an act with a record.** Someone decides the machine is gone, names the new owner, and the act is written down with its reason. The work resumes on a machine that has never seen the ticket, so the move depends on what is durable: the last pushed commit is the recovery point, the ticket's facts are in the store, and the worktree is re-created from the branch. That is the honest price of pinning — **unpushed work is machine-bound**, so the push is the checkpoint and how often it happens decides how much a lost machine costs. A move may repeat a stage (stages are re-runnable); it may not quietly duplicate work.
- **A returning machine is refused.** Ownership is a single value, and a machine that comes back after being replaced must not resume a ticket it no longer owns: otherwise two machines work one ticket and the result is the same change landed twice. A machine that stays dead is a smaller problem than one that comes back, and this rule is what makes the difference.
- **What pinning must never touch: authority and truth.** A ticket pinned to machine A is still signable and reviewable from a console on machine B, its state stays in the shared history, and its ledgers live in the store. The pin is provenance and placement; it never grants or withholds a right.
- **Some work is pinned by nature, and that is declared too.** A browser capture that depends on a specific local profile, a build too heavy to repeat: such a stage is genuinely unmovable, and saying so up front is what keeps a move from failing halfway. The trap is a ticket pinned **by accident** — one that looks movable and is not.

**And the same applies to a person.** With one operator on one machine, a name the caller supplies is harmless; with several people it is the difference between an audit and a formality. Identity is therefore **authority** — who may sign, land or withdraw is a property the system recognises — and never a value a caller fills in about itself. That is the fifth shape this store has to be ready for, and it is the one that cannot be fixed later by a migration: records written under a forgeable identity cannot be re-authenticated after the fact.

The consequence for this document's own subject is small and worth stating: a record's machine is provenance, and no record's meaning may depend on it. Goals 3, 7 and 12 already said this about *records*; goal 20 extends the same rule to *work*. And the operator's surface follows: a console stops being "the machine I use" and becomes a surface that can be opened anywhere against the same truth — the same shape as the read path, one truth and many surfaces.

**One question, asked where review already happens**: does this change touch a door that a later shape needs — a record's ability to name a set, a fact's ability to leave its machine, an identity that must not be forgeable — and does that door still open? The answer is written on the ticket. A door closed without a recorded reason is sent back, and closing one on purpose with the reason written down is allowed.

### Losing the machine, and moving to another one

Two different events, and only one of them is currently possible without loss:

- **Moving while the old machine still runs** is a copy. It is easy in principle and hard in practice for one reason: it depends on knowing *everything* that has to be copied — the repository, the store, the session data, and the engine's own history — and where the last of those actually lives. That is knowledge, and knowledge that lives in one person's head fails exactly when it is needed. So it becomes a written procedure, exercised once, and the exercise is what proves the procedure rather than the intent.
- **Losing the machine** is survivable only if a copy exists somewhere else. A second copy on the same disk, or on a synchronised folder that follows the machine, is not a copy in this sense: it shares the failure. **Off-device is the requirement**, and "we have a backup" only counts once a restore has been performed from it.

The effort should not be spread evenly, because the families differ enormously in two respects:

| Layer | Examples | Size today | If it is lost |
|---|---|---|---|
| **Cannot be rebuilt** | Fault-mode ledger, the relation and certification records to come, the request channel, the alert stream, the action stream, the event stream, inspection findings, authorisation and capacity audits, and the engine's own ticket history | A few megabytes for the file-based ones, plus the engine's history | Amnesia. No amount of re-running the system brings these back |
| **Can be rebuilt or regenerated** | Per-ticket snapshots, settlements, metrics, run results, runtime workspaces, screenshots and evidence | Roughly 1.3 GB and 14,000 directories | Painful, and remediable — the system can produce them again |

The conclusion is the useful part: **the layer that must survive is small enough to carry**, while the layer that is large is the layer that can be produced again. A backup story that treats the store as one undifferentiated 1.3 GB blob would be both expensive and wrong.

Three things follow, and the first is independent of everything else in this document:

1. **The repository needs a copy somewhere else.** Today it has no remote, so the code, the documents and the whole history share the fate of one disk. This is the largest single exposure in the project, it is cheap to fix, and it is not a design question.
2. **The irrecoverable layer gets an export** that lands off-device, and the export is checked by restoring from it — into a scratch location, not over the original.
3. **The engine's own history is included in the procedure**, whichever way its storage is moved. It is the truth about every ticket, and today its location is not written down anywhere.

A note on in-flight work: worktrees live in the operating system's temporary area, which does not survive a machine change and may not survive a restart. Committed work is safe as long as the repository is, because worktrees share its object store; uncommitted work is not, and that is the part a move cannot rescue.

### Why a shared repository is not the transport for a shared ledger

The repository looks like an obvious answer to "several people, several machines", because it already carries the fault ledger and every ledger in it is a file. It is the wrong answer for the family that has to be read **current**, for three structural reasons rather than a matter of taste:

- **A batch is not the present.** A reader gets whatever was last fetched. That is the same staleness this design exists to remove, only with a network round trip in front of it. A lane consulting live fault knowledge must not have to remember to fetch first, and a fetch is a deliberate act.
- **Two writers on one log is a conflict, not two facts.** Two clones appending to the same file touch the same region, so the merge is a decision somebody has to make. Tooling can be configured for a union merge, and then it works — with the ordering chosen by the tools rather than the ledger, which is exactly the clock-like assumption goal 6 forbids.
- **Nothing enforces "never rewritten".** The append-only property that makes the local store safe is a *convention* in a repository; a history rewrite or a force push can remove records, and the party that would notice is the party that did it.

That is not an argument against version control. It is the same family rule as everywhere else in this document, applied to transport: **content whose meaning is tied to a revision belongs in the repository, and content that must be present tense does not.**

Three shapes are therefore possible, and only the third is the target:

1. **Repository as the transport (interim, tolerable).** Legitimate while there is one writer, and even with several if the records are independent and identified so that merging is a union rather than a decision — the fault ledger's shape happens to allow this. Its ceiling is the fetch: nobody gets ten-minutes-ago for free, and current state (who holds what, what the fleet is doing) can never be carried this way.
2. **One writer per file, several readers (still local).** What the store does today, extended to more readers. It scales to one machine and no further.
3. **The target: one writing authority.** The truth behind a service that owns writes, or storage with real transactions, read through the same versioned pull interface as before. This is what "several people on several machines" actually requires, and it is why phase 1 was shaped as a read path rather than a file — the change is plumbing, not a rewrite of every reader.

The ordering consequence is worth stating plainly: **making the read path exist before making the store shared** is what keeps the second step from being a migration of consumers. It is also why the interim shape is acceptable: as long as readers never open a file, moving from a repository-backed read to a service-backed read is invisible to them.

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

This proposal addresses the **Problem** by replacing an accidental arrangement with a rule (goal 1's criterion) and by giving the fault knowledge a home where being current is possible; it satisfies the **Requirement** by versioned reads (2), recorded writers and reasons (3), the fact/state split (4), minted identifiers (5), ledger ordering (6), project-tagged and path-free records (7), loud availability (8), declared backup (9) and growth policy (10), and by declaring real sharing as the target (11) with the phase-1 properties that keep it reachable (12) while leaving write authority untouched (13); and it avoids the **Nongoal** items by not duplicating the engine's truth, not moving documents, not sweeping the run-judging baselines along, not building the service this cycle, not admitting families with no consumer, not crossing projects, not migrating everything at once, not editing growth by hand, not loosening authority in the name of a move, and keeping a machine a resource rather than a home: a ticket is pinned to a machine as a recorded fact, movable as a deliberate recorded act, owned by exactly one machine at a time, and a returning machine is refused — so that a person with two machines, or with none, is a question about resources and never about where the truth lives (18-23).

## Appendix: the inventory

Every record of facts this project keeps, grouped by the reader criterion of goal 1. Counts and sizes are the state at the time of writing; they are evidence for the Problem, not a plan of record.

### A. Knowledge that must be read current

| Ledger | What it holds | Reader / writer | Where it lives today | What this design says |
|---|---|---|---|---|
| Fault-mode ledger | 222 numbered entries in one prose file, 512 KB: what is known broken, its trigger, what kind of change steps on it | Read before designing any change's proof; written by the integration role at attribution time | In the repository, prose, edited in place | **Moves — first family.** Its staleness is the cost that motivates this design |
| Fault mode ↔ case ↔ result | The join: which case locks which fault mode, and how that case last ran | Nobody can read it as a set; it exists only as prose citations and scenario descriptions | Nowhere | **Missing.** Its absence is why the fault ledger reads as prose and why "which of these does my change touch" is a search |
| Work queue | Tickets waiting to be opened, mostly blocked on write-set collisions | Read and written by the integration role | In the repository, prose, edited in place | **Moves.** It is consulted while planning, so it must be current |
| Queued ticket payloads | 21 per-ticket files last touched in September; no flow names them | Nobody | In the repository | **Decide explicitly: retire or move.** A registration table nobody maintains is a dead table |
| Epic declarations | One file per epic (15): the rationale for a piece of work | Read by whoever opens work under it; written by host / integration | In the repository, prose | **Split.** The membership facts belong to the store as relations; the rationale stays a document |

### B. Baselines that must match the code under test

| Ledger | What it holds | Reader / writer | Where it lives today | What this design says |
|---|---|---|---|---|
| Booked-red baseline | Which cases are expected to be red, and why a red is not new | Read by the gate and by acceptance faces; written when a red is booked | In the repository, machine-read, 57 KB | **Stays.** It judges a run, so it must be the revision that judges that code — the opposite requirement from the fault ledger even though the two look alike |
| Case anchors | What each case pins, so a case is judged against declared anchors rather than implementation names | Read by the suite and the gate | In the repository, machine-read, 152 KB | **Stays**, same reason |
| Terminology baseline (and its floor) | The vocabulary documents may and may not use | Read by the documentation check | In the repository, machine-read, 25 KB | **Stays**, same reason |
| Scenario surfaces | Which surface each case owns, so coverage is not duplicated | Read by the suite | In the repository, machine-read | **Stays**, same reason |
| Batch/stage exceptions and temporary-directory baseline | The declared exceptions a judging step must honour | Read by the judging steps | In the repository, machine-read | **Stays**, same reason |
| Write-set protection list | Which paths a lane may not write | Read by the gate; it is expressed in engine code rather than as a file | In code | **Not a ledger** — a policy input. Named here so that a later reader does not mistake it for a fact store |

### C. Operational facts of the running system

This family is already in the project's store, outside the repository, in the same shape across every project — it is this design's template.

| Ledger | What it holds | Reader / writer | Where it lives today | What this design says |
|---|---|---|---|---|
| Event log | What the engine and the watchdog observed, as it happened | Read by the console faces and by diagnosis | Project store, append-only, 5.7 MB | **Stays**, and becomes the model the moved families follow |
| Action log | What the executor did and on whose authority | Read by the board and by audit | Project store, append-only | **Stays** |
| Run results | One row per case per suite run — the history behind every green and red | Read by the gate, the faces and the patrol | Project store, append-only, **88 MB**, with a rotation cursor | **Stays.** Growth is the thing to decide here, not the location |
| Capacity limit and its audit | The number of tickets allowed at once, and every change to it | Read by the gate; written by host / executor | Project store: a current value plus an append-only audit | **Stays.** The value is current state; the audit is a fact — the two shapes are already separate, which is the pattern goal 4 asks for |
| Capacity state | Who holds a slot, who is queued | Read and written by the gate every few seconds, under a lock | Project store, current state + lock file | **Stays.** The clearest example of why current state is not a fact log |
| Executor authorisation | What the executor session may do, and every grant or revocation | Read by the executor path | Project store: current value plus append-only audit | **Stays** |
| Request channel | What the executor asked the host for, and the answer | Read by the host; written by the executor | Project store, append-only, 279 KB — with **17 hand-made dated backups** beside it | **Stays.** The backups are this design's best evidence for goal 9 |
| Inspection findings | Review outcomes per period | Read by the inspection faces | Project store, append-only | **Stays** |
| Ticket snapshots, settlements, metrics | Per-ticket roll-ups and the numbers behind the panels | Read by the faces | Project store, **1.2 GB** across 273 / 261 / 215 entries | **Stays.** Growth policy applies |
| Runtime declarations | Watchdog state, sessions, project declaration, model routes | Read by the running system | Project store, current state | **Stays** |
| Watchdog streams | Per-project alert stream (574 KB for this project), executor session stream, heartbeat, and a prose backstop | Read by the watchdog faces and by diagnosis | Outside the project store, append-only | **Stays.** Missed in the first pass of this inventory and added here: it is a separate family in a separate directory |
| Runtime workspaces | Stage directories and reclaimable scratch areas — **14,217 entries** | Nobody reads them; the system creates them | Outside the project store | **Not a ledger.** Residue with a lifetime question, not a home |

### D. Facts about tickets

| Ledger | What it holds | Reader / writer | Where it lives today | What this design says |
|---|---|---|---|---|
| Ticket state, stages, signatures, verdicts, sends-back | The truth about every ticket | Read by the console and the engine; written by the workflow | The engine's own history | **Truth stays there.** The store may hold projections for faces, never a second copy |
| Relations between tickets | Which ticket exists because of which | — | Designed, not built ([Ticket Relations v1](ticket-relations-v1.md)) | Belongs to the store |
| Landing and certification record | Which revision of the buffer was certified, by what, and with which faults booked | — | Designed, not built ([Develop Buffer v1](develop-buffer-v1.md)) | Belongs to the store |
| Acceptance and integration reports | What a walkthrough concluded, with its evidence | Read by the host and by whoever picks the work up later | In the repository and in per-ticket directories (267 ticket directories, 68 evidence directories, 1,164 report files) | **Reports are products, not a ledger** — but there is no register of which reports exist or what each concluded, so finding them is a path convention |

A note on the truth's own storage: the engine's history is served from a loopback address on this machine, which means the record of every signature, verdict and send-back is subject to the same loss as the files above, and, like them, it is outside version control.

### E. Documents

| Ledger | What it holds | Reader / writer | Where it lives today | What this design says |
|---|---|---|---|---|
| Design, operations and reference documents | Reasoning that must be read as reviewed | Read by people and by agents as context; written through review | In the repository | **Stays a document.** Version control is the review mechanism |
| Document index | Where each document is and what it is tagged | Read by the knowledge faces | In the repository, **generated** | Stays: generated from the documents, never hand-edited |
| Terminology | The project's agreed vocabulary | Read by people and by the documentation check | In the repository, prose | Stays a document; its machine-checked form is the terminology baseline above |

### F. Residue that is not a ledger

Quarantine directories, rescue runbooks, screenshot piles, overnight autopilot logs and state, scratch caches, and in-repository test stages. These are workspaces and leftovers rather than facts. They need a **lifetime rule** (when is this deleted, who may delete it), not a home in a fact store — and naming them here is deliberate, because a family rule that does not say "not this" would eventually sweep them in.

### What the inventory shows

1. **Two families with opposite requirements currently share one home.** The fault ledger must be current; the baselines that judge a run must match the code under test. Both sit in the repository today, which means the family that needs liveness gets a snapshot and the family that needs revision-matching has no rule at all.
2. **The template already exists.** The operational family is in the store, in one shape, for every project. What is missing is not a store but a **convention set**: identity, writers and reasons, append-only facts versus current state, versioned reads, availability and backup.
3. **The really missing ledger is the join.** Fault mode, the case that locks it, and how that case last ran are three facts that today have no shared home, which is why reading the fault ledger is a search rather than a query.
4. **What the store lacks is what version control gave for free.** Seventeen hand-made dated copies of one request log is what a backup story looks like when there is no backup story; an 88 MB single log with only rename-rotation is what a growth policy looks like when there is none; and "as of which version did my work read this?" has no answer in either home.
5. **The largest exposure is not in this design at all.** The repository has no remote, the engine's history is machine-local, the store has no off-device copy, and the knowledge of how to move it all is held by one person. Every fact family in this inventory shares one fate until that changes, and it is worth fixing before any family moves.


6. **"Share the repository" is not a sharing design.** It answers a batch, not the present, and it cannot enforce the property that makes appending safe. The families that must be read current need either a single writing authority or records that merge as a union — and the read path has to exist first, whichever of the two arrives.

## Related documents

- [Ticket Relations v1 (what one ticket is to another)](ticket-relations-v1.md) — the first relation ledger in this family, with the same recording rules.
- [Develop Buffer v1 (lane → develop → main)](develop-buffer-v1.md) — the certification and landing ledgers are members of this family.
- [Knowledge Base Design](knowledge-base-design.md) — the split between documents and facts.
- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document follows.
