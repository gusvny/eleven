---
title: Develop Buffer v1 (lane → develop → main)
category: design
tags:
  - merge flow
  - integration gate
  - certification
  - develop branch
status: active
updated: 2026-10-09
related:
  - mode: dependency
    target: failure-classification-protocol-v1.md
    note: how a red is classified (product / environment / flake) — this document relies on it for the bisection protocol
  - mode: practice reference
    target: design-doc-writing-guide.md
    note: the four-section admission standard this document was written to
  - mode: context
    target: knowledge-base-design.md
    note: where this document sits in the document-first workflow
---

# Develop Buffer v1 (lane → develop → main)

> Audience: whoever works on the merge flow — the engine, the integration role, and lane agents.
> This document states **what the flow is and why**; the mechanics live in the implementation tickets.

## Problem

**One sentence:** every lane pays a full, expensive suite round per attempt to land, and the only thing standing between a lane and main is a per-ticket precondition ("this ticket's scenarios have a green run on this exact tree") that other people's merges keep invalidating — so the merge line stalls as soon as the fleet gets busy.

**Background knowledge (what an outsider needs first):**

- A ticket is executed in its own **lane** (a git worktree on its own branch). When the lane believes it is done, a **gate** judges it: protected paths, the write set, a rehearsal of the merge into `main`, and a suite of integration scenarios that exercise the product surfaces the change touches.
- `main` is the delivered line, and it is **human-signed**: a person approves the merge.
- The suite is heavy: one full round is hundreds of scenarios and tens of minutes of wall clock; a large part of the cost sits in scenarios that boot a real console or a real browser.
- Two mechanisms interact badly today. First, the gate re-merges `main` into the lane before judging, so a lane's tree changes whenever *anybody* lands. Second, the gate requires a green run of **the ticket's own scenarios on the tree being merged**. Together they mean a ticket's proof is destroyed by other people's work, and a fresh proof needs a long suite round inside a window where nobody else lands.

**Evidence (261008–261009, measured):**

- Four tickets sat blocked on that precondition at the same time (`zero-run`: "the gate never completed a green round here"), holding **all five** concurrency slots while **seven** tickets queued behind them. The host's words: nothing can move any more, we cannot merge concurrently.
- The precondition is not the only stall: one of those tickets' gate rounds took about three minutes and produced **no suite round at all** (the storefront of the round shows the code-verification item with no receipt, and the lane produced no full-suite report), i.e. "the suite did not run" is itself reachable — and the new precondition is what finally makes it visible.
- The "a test run dirtied the main checkout" accident class has now occurred **twice in two days** (a scenario writing generated evidence into a tracked path), both times blocking *other* tickets' merge checks rather than the ticket that ran the scenario.
- The suite's red set is not stable product truth: of eight scenarios red in consecutive full runs, attribution showed **two stale anchors** (a translated message whose scenario still pinned the old text), **two judgment-criteria defects**, **one real product defect**, and **three that pass standalone and fail only under load**.

## Requirement

**Goals (verifiable):**

1. A lane can land without paying a full suite round, and a lane's landing does not have to survive a window in which nobody else lands.
2. Each lane still proves **its own** change: the ticket's own scenarios run per lane, and a failure there is attributed to that ticket without any whole-suite round.
3. Besides its own scenarios, every lane runs a **fast global set** defined by the integration role: a small, curated selection whose job is to catch, at the lane, the breakage that a ticket's own scenarios do not look at — so that fewer defects reach the buffer and have to be solved there. The lane's whole proof (own scenarios plus the fast set) must stay inside a declared time budget.
4. The fast set's membership is **maintained, not fixed**: the integration patrol reviews it periodically and adds or removes members on recorded evidence about both sides of the trade — how much time a member costs and how much breakage it actually catches. A member earns its place by catching cross-cutting breakage early; it loses its place when it is too slow for the budget, flaky, or already covered by another member.
5. The fast set is derived from the **same declared inventory** that feeds the full suite — one inventory with two uses, never a second hand-kept list that can drift away from it. A member that is meant to catch breakage the full suite does not cover says so explicitly.
6. The full suite runs against a **buffer line between lanes and main**, at most once per schedule tick (event-driven trigger, scheduled backstop), not once per lane attempt.
7. "May this land in main?" is answerable **mechanically**, from recorded facts, without asking a human to remember anything: a revision is certified by a passing full run, and a ticket is landable when its landing is contained in a certified revision.
8. The **greatest certified revision is always landable**, even while the buffer is red — a red must never take the already-proven part hostage.
9. A red is attributed with **bounded** cost: the same revision is re-run once before any search, the per-lane scenario results are used as a free first filter, and only then is the range searched.
10. A red never silently holds the fleet: it has a named owner and a named escalation point, and ranges already attributed are not searched twice.
11. `main` keeps a human signature — now **one per batch** instead of one per ticket.
12. The new flow is built **alongside** the current one, not on top of it: while the new one is being built and validated the current flow keeps working unchanged, the new flow exists as a **new lane version** that a ticket opts into, and only after it has proven itself are tickets moved over and the old version retired — gradually, not in one step.
13. Nothing introduced for the new flow applies **retroactively** to tickets running the old flow: a new precondition, a new proof or a new gate check ships inside the new version and is chosen by the tickets that use it, never injected into every ticket's gate.
14. A ticket's life ends at the buffer, not at `main`: the new flow lands it into the buffer automatically, then the ticket **waits for the certification that covers its landing** and ends when that certification arrives. The human review moves from the per-ticket merge gate to the batch that leaves the buffer — so the ticket's record must still show all three stages of its outcome (the revision it landed at, the certification that covered it, and whether it reached `main` or was later reverted there).
15. Waiting for a certification **does not hold a slot**: a ticket that is only waiting for the next scheduled run must not consume the capacity that other tickets need.
16. A red certification **suspends landings into the buffer** until the buffer is green again: while the buffer is red, tickets that are still in flight finish their own proof but do not land. The remedy for a red that implicates a landing is a **new fix ticket opened against the buffer** — never a return of the implicated ticket to work — and the fix ticket is the one kind of work that may still land while the buffer is red.
17. The exemption in 16 is **structural, not self-declared**: the fix ticket runs through its own workflow, so "may land while frozen" is a property of how the work was opened, not a flag any ticket can set on itself.
18. **A landing is a set of repository revisions, not a branch.** In the single-line, single-repository phase the set has one member, but every record that names a landing, a certification or a batch can name a set — and can say **which members must move together**, because a change that is only safe as a pair has to land as one act, or it leaves a window in which the delivered state is broken.
19. **A line is a declaration, not a topology.** What a line covers (a line of work, a component, one or more repositories), who owns it, and when it is expected to end are declared facts. Adding a component line or a repository line is a declaration rather than a change to the protocol, and a long-lived line is a different obligation rather than a different mechanism.
20. **Boundary ownership follows the shared artifact.** When two sides each changed something and broke together, the owner is whoever owns the thing both sides changed — the shared component, or the repository. When the sides share nothing, the owner is whoever formed the batch.
21. **A line's continuing existence is decided by evidence**, and the evidence is the one already collected: how often its landings are blocked, and how much conflict appears when its content is combined. A line that costs more than it isolates is split or ended, which is possible only because a line is a declaration.
22. **The first phase arrives so that the later shapes are declarations plus at most one new mechanism** — a landing that spans repositories and must move as one act — never a rewrite of the certification and landing records.

**Stakeholders and what they care about most:**

- **Host** — throughput without losing the ability to say "a person approved this".
- **Lane agents** — a landing decision they can reach without a long suite round, and a failure they can act on.
- **Integration role** — the ability to attribute a red to a ticket, and to refuse precisely instead of blocking everybody.
- **Engine** — a flow that can be enforced mechanically, with no hand-maintained state.

**Upfront constraints (must not be broken):**

- `main` stays the human-signed line; nothing lands in it without a person approving.
- Zero runs are never proof: a run that executed nothing, or was cut short, or died on the environment, is not evidence of anything.
- The buffer line's history must stay **linear** and one landing per ticket, so that "before" and "after" are well defined.
- The whole-suite run must live where its own output cannot touch the delivered checkout.
- The existing protections (protected paths, write-set gates, the booked-red inventory) keep working unchanged.

## Nongoal

- **Not removing the human gate on main.** The gate becomes per-batch; it does not disappear.
- **Not letting any ticket declare itself exempt from a freeze.** Only the fix workflow is exempt from stopped landings, and that is decided by how the work was opened.
- **Not building several lines this cycle.** A line per component, a line per repository and coordinated landings across repositories are out of scope; what this cycle owes them is that they arrive as declarations rather than as a rewrite.
- **Not defining a line by its branch.** A line is a declared scope with an owner; a branch is one way of implementing that scope, not its identity.
- **Not keeping a per-ticket human merge gate in the new flow.** A person reviews the batch that leaves the buffer (the certified prefix), not each ticket; the ticket ends when its landing is certified. The old flow keeps its per-ticket gate for as long as it serves tickets.
- **Not letting lanes skip their own scenarios.** The split is "the lane proves its change, the buffer proves the combination" — not "nobody proves anything until later".
- **Not running the full suite after every landing.** Explicitly chosen: scheduled certifications, with the previous certified revision as the anchor that is always landable.
- **Not making the suite faster.** Its cost is addressed here by *when* it runs; making it cheaper is a separate concern.
- **Not letting the fast set grow into a second full suite.** It is a tripwire with a time budget, not a proof; when it starts costing like the full suite it has stopped doing its job.
- **Not freezing the fast set.** A membership that never changes either misses new breakage surfaces or keeps paying for members that no longer earn their time; the review is periodic by design, and "keep" is a verdict that must also be argued.
- **Not rolling this out to other projects in this cycle.** Sandbar first; the flow is per project and the others follow deliberately.
- **Not changing what "blocked" means for a ticket.** The blocking reasons stay the engine's; this document only changes what a lane must prove and where.
- **Not modifying the current lane in place.** The current flow is the fleet's working line; changing it under running tickets is what produces the incidents this document exists to avoid. The new flow arrives as a new version beside it.
- **Not switching the fleet over at once.** Tickets move to the new version deliberately, and the old version keeps serving the tickets that are already on it.
- **Not retiring the old version before the new one has proven itself** on real landings — "stable" is something the record has to show, not something we declare.

## Proposal

### High level

Insert a **buffer line** (`develop`) between the lanes and `main`, and move the expensive proof onto it.

- **Landing:** lanes land into `develop`, one ticket per landing, serially managed by the engine. A lane does **not** have to be rebuilt on the newest buffer before landing — serialized landing keeps the buffer's history linear, which is what makes "before/after" meaningful. A lane still runs its own scenarios first; that run is what attributes a per-ticket failure for free.

### The lane's fast global set

A ticket's own scenarios answer "did I build what I said?"; they say nothing about the surfaces it walked over. The **fast global set** is integration's answer to that gap, and its whole reason to exist is *earliness*: catching a cross-cutting break at the lane is far cheaper than catching it on the buffer, where it costs an attribution round and holds other people's landings.

- **What it is:** a small, curated selection drawn from the same inventory as the full suite, chosen for coverage-per-second rather than depth. It is a tripwire: cheap, deterministic and honest about what it does not cover. It is not proof, and it is never a substitute for the full suite.
- **Budget:** the lane's proof — its own scenarios plus the fast set — carries a declared time budget. The budget is the constraint that keeps the set honest: a candidate that does not fit is either trimmed or left to the full suite.
- **Failure semantics:** a red in the fast set blocks the lane and is attributed to that ticket, and it is classified the same way any other red is (product fault, environment, or flake) — a flaky tripwire would burn exactly the throughput it exists to protect, so flakiness is a removal reason, not something to live with.
- **Stewardship:** the integration patrol reviews membership periodically and records a verdict per member — add, remove, or keep — each argued on evidence about both sides of the trade: how much lane time it costs and what breakage it has actually caught (including what it missed, when a defect reached the buffer it should have caught). "Keep" is a verdict too: the default is not to keep paying silently.
- **Candidates for membership** come from breakage that a lane failure would have caught earlier, from new cross-cutting surfaces, and from members whose cost drops. **Candidates for removal** are those that are too slow for the budget, flaky, or now covered by another member or by a general guard.
- **One inventory, two uses:** the fast set is marked inside the same declared inventory that feeds the full suite, so membership can never drift into a second, hand-kept list; a member meant to catch breakage outside the full suite's reach says so in its declaration.
- **Certification:** a full suite round runs **on the buffer**, in a workspace of its own (never the delivered checkout), on a schedule: triggered when the buffer changes (debounced) with a timed run as backstop. A passing round **certifies** the revision it ran on.
- **The record:** certification is not a status flag but a **fact ledger**: for each certification, which revision was certified and which range of landings it covers, what ran and how it went (scenarios run, failures, environment reds), under which booked-red inventory it was judged, when, by what driver (scheduled / triggered / re-run) and by whom. Alongside it, a **counterpart record for attributed reds**: which range was searched, which landing was found responsible, how that was established, and what happened to it. The ledger is append-only and machine-written; corrections are new rows, never edits.
- **Landability:** a ticket may land in `main` when its landing is contained in a certified revision. The **greatest certified revision is always landable**, regardless of what the buffer looks like now; this is what keeps a red from holding the already-proven part hostage.
- **Red handling:** a red first gets the **same revision re-run once** — the cheapest discriminator between a flake and a fault, and the reason a flaky suite cannot send the search chasing a ghost. Then the per-lane scenario results are consulted (a red there names the culprit for free). Only then is the range searched, and the result is written down so the same range is never searched twice.
- **Culprit handling:** the responsible landing is **reverted** where possible — so the proven prefix can go to `main` and the buffer returns to a good state — and the original ticket is sent back to work; fixing forward on a lane based on the buffer is the fallback when a revert is not possible under the existing protections.
- **Main:** batches are taken from the certified prefix, and a person signs the batch. What a person is approving is now "this group of landings, each of which was already covered by a certified buffer revision".

### Ticket completion, and where a person looks

In the new flow the ticket does **not** wait for `main`. Its life cycle ends at the buffer:

1. the lane finishes its own proof (its scenarios plus the fast global set) and the engine **lands it into the buffer automatically**, one landing at a time;
2. the ticket then **waits for a certification that covers its landing** — the next scheduled round, or a run already in flight;
3. that certification arrives green ⇒ **the ticket ends**. No per-ticket merge gate, no waiting for `main`.

What this buys is one fewer stop per ticket and a person who looks at a **batch** instead of at a queue of individual merges. What it costs has to be paid explicitly:

- **"Ended" no longer means "delivered".** A closed ticket may sit on the buffer until the next batch is taken to `main`, and may in principle be reverted there. So the ticket's own record carries the three stages — where it landed, which certification covered it, and whether it reached `main` or was later reverted — and the buffer's record names the tickets each certification covers. The two records must be readable against each other, because "closed" alone would otherwise be a claim nobody can check.
- **A red certification that names my landing is not the end of my ticket, and it is not a return to work either.** The landing is already on the buffer; sending the ticket back would put it on a base that no longer exists. The remedy is a **new fix ticket opened against the buffer**, and the implicated ticket keeps waiting for the certification that finally covers it — or ends as reverted if the fix reverts it. The ticket's face must distinguish "waiting", "red and implicated", and "reverted", because those three look identical from the outside and mean very different things.
- **Waiting is not working.** A ticket waiting for the next run holds no capacity; if waiting held a slot, one tick would pin the whole fleet — which is the very stall this design removes.
- **The batch view is now the human's whole surface.** The person signing the batch must be able to open each member (its diff, its own scenario results, the certification's evidence) before signing; a batch that can only be approved as a black box would move the human further from the work, not closer.
- **An automatic landing that conflicts bounces back to the lane** rather than blocking: the lane re-merges the buffer and lands again. An automatic step must never introduce a new place for tickets to pile up.

**The lesson that shaped this section:** the previous flow's stops per ticket were the human gate AND the full suite. Removing the second without moving the first would just relocate the bottleneck; the two moves have to happen together, and the ticket's record has to stay honest about the difference between "landed", "certified" and "delivered".

### When the buffer is red

A red certification is not one ticket's problem to fix, and it is not free to ignore. Two rules:

**Landings stop.** While the buffer is red, tickets that are still in flight keep running their own proof but do not land into it. The reason is attribution, not caution: the buffer's red is only actionable while the number of candidate culprits is small. If work keeps landing on top of a broken revision, the red stops naming anything, every later ticket inherits it, and the bisect that was supposed to find the culprit now has to guess among an unbounded set. Stopping landings is what keeps a red a fact about one landing.

**The fix ticket may still land.** A freeze that also blocks the fix would be a deadlock, so the fix is the one kind of work exempt from it. That exemption must be **structural**: the fix ticket is opened through its own workflow, so being allowed to land on a red buffer is a property of how the work was opened, not a box any ticket can tick about itself. A self-declared exemption would be a hole in the freeze, and holes in gates get used by accident long before they get used on purpose.

The rest follows from those two:

- **A ticket waiting for landings to reopen is waiting, not working** — it holds no capacity, exactly like a ticket waiting for the next certification.
- **The fix lands as the only landing on the buffer**, and that fact is recorded as such: when landings have been stopped, the culprit set for the next red is not "whatever landed since the last green" but a set that has to be read off the record.
- **If the fix does not turn the buffer green, the freeze stays** and the next fix ticket names the fix landing as its candidate culprit; the chain of fix tickets must stay visible, because a freeze that quietly becomes the permanent state is worse than the red it was hiding.
- **The freeze is visible to people, not just to the machine.** Whoever signs the next batch has to be able to see that the buffer was frozen, for what, and by which fix ticket it reopened.
- **What a fix repairs is a recorded fact, not a sentence in its description.** The relation between remedy work and the landing it repairs is what grants the exemption and what lets the benefited ticket record how it ended; see [Ticket Relations v1](ticket-relations-v1.md).

### What comes after one line, and what the first phase must not foreclose

One line is the first phase. The shapes that follow differ in **what a line is scoped to**, not in how a line works:

- a line per line of work (an epic) — the shape a single developer reaches for first;
- the same, for an epic that lives a long time: the mechanism is identical, and what differs is the **duration of the obligation** it creates;
- a line per **component inside one project**, owned by the group that maintains that component;
- and lines over **several repositories**, where the groups maintaining those repositories may be different groups again, and where the repositories can be managed separately.

Two properties make those arrivals cheap later, and both have to be in place from the first phase because neither can be retrofitted:

1. **A landing is a set of repository revisions, not a branch.** In the single-line phase the set has one member, but the records must be able to name a set — including which members have to move together. This is not speculative: the engine's lane vocabulary already admits projects whose repositories are separate, so a ledger that assumed one repository would be the part that has to be rewritten. And a change spanning two repositories that is only safe as a pair has to land as one act, or the delivered state has a window in which it is broken.
2. **A line is a declaration, not a topology.** What it covers, who owns it, and when it is expected to end are declared facts. Then adding a component line or a repository line is a declaration rather than a protocol change, and a line declared long-lived is a *different obligation* rather than a different mechanism.

Three consequences worth writing down now, because the single-line phase must not make them impossible:

- **Certification generalizes upward, not sideways.** What gets certified is the **candidate set of revisions that would be delivered together**. One line is the special case where the candidate is that line's head; several lines, or several repositories, is the general case — and the rule is unchanged: landability means being contained in a certified candidate.
- **Boundary ownership follows the shared artifact.** When two sides each changed something and broke together, the owner is whoever owns the thing both sides changed — the shared component, or the repository. When the sides share nothing, there is no artifact to own the boundary and the owner is whoever formed the batch. Without this rule, boundary problems belong to everyone and therefore to nobody.
- **A line's existence is decided by evidence, not by habit.** A long-lived line pays a continuing obligation: it must keep taking in the certified state, and a withdrawn landing must be removed from it explicitly. Whether that is worth paying is a question about the line, and the evidence already exists — how often its landings are blocked, and how much conflict appears when its content is combined. A line that costs more than it isolates should be split or ended, which is possible only because a line is a declaration.

**What "too simple" would look like**, stated so that a reviewer can catch it:

- a record that says "the revision of the buffer", in the singular, with nowhere to put a second repository;
- a batch that assumes one repository, or that cannot express "these two must land together";
- a line identified by a branch name rather than by a declared scope and owner;
- an owner attached to a person or a session rather than to a scope;
- boundary problems with no owner, or with the batch's preparer as the only owner even when a shared component exists.
- a stage that can only run on the machine that created the worktree, or a line whose state cannot be reconstructed from the repository and the recorded facts (see [Project Fact Ledgers v1](project-fact-ledgers-v1.md): a machine is a resource, not a home).

### Coexistence and rollout

The new flow is a **new lane version that runs beside the current one**. That is not caution for its own sake: the fleet is working on the current version right now, and the incidents this document reacts to were caused by mechanisms landing *into* that working line — a precondition that started judging tickets which had never been able to satisfy it, and a suite whose output reached the delivered checkout. A second version makes the boundary explicit: everything the new flow needs (its own proof rules, its own gate, its own landing line and its own record) belongs to the tickets that opted in.

- **What is shared and must stay compatible:** the declared scenario inventory (one inventory, two uses), the classification of a red as product fault / environment / flake, the protected-path and write-set protections, and the delivered line's human signature. Sharing these is what keeps the two versions comparable — a ticket moved to the new flow must not need a second definition of any of them.
- **What is separate:** the new version's landing line and its certification record, its per-lane proof (own scenarios plus the fast global set within a budget), and the checks that enforce them. The old version's gate keeps judging its tickets exactly as it does today, including the checks that were added to it while it was already running.
- **How a ticket chooses:** per ticket, at the moment it is opened, by naming the version; there is no global switch and no silent migration. A ticket already running on the old version is never moved by a change to the new one.
- **What "stable enough to move over" means (evidence, not a feeling):** a run of real landings on the new flow whose certification record shows the whole path working — landings made, revisions certified, at least one red attributed and bounded (including the flake-first rerun doing its job), and no class of incident that the old flow did not have. The numbers are set when the implementation is planned; what matters here is that the promotion decision is read off the record.
- **Retirement of the old version** follows the same rule in reverse: tickets stop being opened on it, the tickets already on it finish, and it is removed only when nothing is running on it — the old flow is not switched off under anybody's feet.
- **The lesson that shaped this section:** a mechanism that changes the meaning of an existing gate must first run where it cannot judge tickets that predate it. Today's evidence is four tickets blocked by a precondition none of them could satisfy, holding every concurrency slot while others queued.

### Key tradeoffs, stated plainly

- **A shared proof has a wider blast radius than a per-ticket one.** What keeps it bounded here is the prefix rule (the last certified revision always lands) plus the fact that only landings *after* that revision wait for attribution. A shared proof is also why the rerun-once rule must come before any search: bisecting on a flake would cost hours.
- **Interaction failures are blamed on the boundary landing.** If two tickets are individually fine and break together, the red appears at the later landing. The record must be able to say "attributed at the boundary, culprit not isolated", and the per-lane results decide whether to search further.
- **The schedule adds latency.** A landing made just after a tick waits for the next trigger plus the round. A trigger-on-change rule keeps this small; the backstop exists so a quiet buffer still gets certified.
- **"A lane need not be newest" moves a class of failure later.** A lane that lands without incorporating the newest buffer content may pass its own scenarios and still break the combination. That is exactly what certification exists to catch, and it is attributed to the landing, not to the lane's scenario run.

### How this ties back

This proposal addresses the **Problem** by taking the heavy proof off the per-lane attempt and putting it on a line whose revisions are certified once, and by replacing a proof that other people's merges destroy with one recorded against revisions; it satisfies the **Requirement** by keeping per-lane proof of the ticket's own change (goal 2), adding the curated fast global set with its time budget and its maintained membership (3–5), running the heavy suite at most once per tick (6), making landability mechanical (7) with the last certified revision always landable (8), bounding attribution cost (9) and escalation (10), and keeping the human signature on `main` (11); it answers goals 12–13 by arriving as a new lane version that a ticket chooses, with the current flow's gate and its running tickets untouched; and it avoids the **Nongoal** items by not touching the human gate's existence, not letting lanes skip their own scenarios, not running the suite per landing, not rebuilding the suite, not modifying the current lane in place, not switching the fleet at once, not retiring the old version before the record shows the new one is stable, and staying inside one project.

## Related documents

- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document follows.
- [Failure Classification Protocol v1 and Mechanical Attribution](failure-classification-protocol-v1.md) — how a red is classified as product / environment / flake; the bisection protocol here depends on it.
- [Ticket Relations v1 (what one ticket is to another)](ticket-relations-v1.md) — the relation ledger; the freeze exemption and the benefited ticket's outcome both rest on a recorded repair relation.
- [Later Shapes v1 (and the doors today's work must leave open)](later-shapes-v1.md) — the later line and repository shapes, and the tells that show a door has been closed.
- [Project Fact Ledgers v1 (where the project's own facts live)](project-fact-ledgers-v1.md) — where the certification and landing ledgers live, and how they are shared.
- [Knowledge Base Design](knowledge-base-design.md) — where this document sits in the document-first workflow.
