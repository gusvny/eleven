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
3. The full suite runs against a **buffer line between lanes and main**, at most once per schedule tick (event-driven trigger, scheduled backstop), not once per lane attempt.
4. "May this land in main?" is answerable **mechanically**, from recorded facts, without asking a human to remember anything: a revision is certified by a passing full run, and a ticket is landable when its landing is contained in a certified revision.
5. The **greatest certified revision is always landable**, even while the buffer is red — a red must never take the already-proven part hostage.
6. A red is attributed with **bounded** cost: the same revision is re-run once before any search, the per-lane scenario results are used as a free first filter, and only then is the range searched.
7. A red never silently holds the fleet: it has a named owner and a named escalation point, and ranges already attributed are not searched twice.
8. `main` keeps a human signature — now **one per batch** instead of one per ticket.

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
- **Not letting lanes skip their own scenarios.** The split is "the lane proves its change, the buffer proves the combination" — not "nobody proves anything until later".
- **Not running the full suite after every landing.** Explicitly chosen: scheduled certifications, with the previous certified revision as the anchor that is always landable.
- **Not making the suite faster.** Its cost is addressed here by *when* it runs; making it cheaper is a separate concern.
- **Not rolling this out to other projects in this cycle.** Sandbar first; the flow is per project and the others follow deliberately.
- **Not changing what "blocked" means for a ticket.** The blocking reasons stay the engine's; this document only changes what a lane must prove and where.

## Proposal

### High level

Insert a **buffer line** (`develop`) between the lanes and `main`, and move the expensive proof onto it.

- **Landing:** lanes land into `develop`, one ticket per landing, serially managed by the engine. A lane does **not** have to be rebuilt on the newest buffer before landing — serialized landing keeps the buffer's history linear, which is what makes "before/after" meaningful. A lane still runs its own scenarios first; that run is what attributes a per-ticket failure for free.
- **Certification:** a full suite round runs **on the buffer**, in a workspace of its own (never the delivered checkout), on a schedule: triggered when the buffer changes (debounced) with a timed run as backstop. A passing round **certifies** the revision it ran on.
- **The record:** certification is not a status flag but a **fact ledger**: for each certification, which revision was certified and which range of landings it covers, what ran and how it went (scenarios run, failures, environment reds), under which booked-red inventory it was judged, when, by what driver (scheduled / triggered / re-run) and by whom. Alongside it, a **counterpart record for attributed reds**: which range was searched, which landing was found responsible, how that was established, and what happened to it. The ledger is append-only and machine-written; corrections are new rows, never edits.
- **Landability:** a ticket may land in `main` when its landing is contained in a certified revision. The **greatest certified revision is always landable**, regardless of what the buffer looks like now; this is what keeps a red from holding the already-proven part hostage.
- **Red handling:** a red first gets the **same revision re-run once** — the cheapest discriminator between a flake and a fault, and the reason a flaky suite cannot send the search chasing a ghost. Then the per-lane scenario results are consulted (a red there names the culprit for free). Only then is the range searched, and the result is written down so the same range is never searched twice.
- **Culprit handling:** the responsible landing is **reverted** where possible — so the proven prefix can go to `main` and the buffer returns to a good state — and the original ticket is sent back to work; fixing forward on a lane based on the buffer is the fallback when a revert is not possible under the existing protections.
- **Main:** batches are taken from the certified prefix, and a person signs the batch. What a person is approving is now "this group of landings, each of which was already covered by a certified buffer revision".

### Key tradeoffs, stated plainly

- **A shared proof has a wider blast radius than a per-ticket one.** What keeps it bounded here is the prefix rule (the last certified revision always lands) plus the fact that only landings *after* that revision wait for attribution. A shared proof is also why the rerun-once rule must come before any search: bisecting on a flake would cost hours.
- **Interaction failures are blamed on the boundary landing.** If two tickets are individually fine and break together, the red appears at the later landing. The record must be able to say "attributed at the boundary, culprit not isolated", and the per-lane results decide whether to search further.
- **The schedule adds latency.** A landing made just after a tick waits for the next trigger plus the round. A trigger-on-change rule keeps this small; the backstop exists so a quiet buffer still gets certified.
- **"A lane need not be newest" moves a class of failure later.** A lane that lands without incorporating the newest buffer content may pass its own scenarios and still break the combination. That is exactly what certification exists to catch, and it is attributed to the landing, not to the lane's scenario run.

### How this ties back

This proposal addresses the **Problem** by taking the heavy proof off the per-lane attempt and putting it on a line whose revisions are certified once, and by replacing a proof that other people's merges destroy with one recorded against revisions; it satisfies the **Requirement** by keeping per-lane proof of the ticket's own change (goal 2), running the heavy suite at most once per tick (3), making landability mechanical (4) with the last certified revision always landable (5), bounding attribution cost (6) and escalation (7), and keeping the human signature on `main` (8); and it avoids the **Nongoal** items by not touching the human gate's existence, not letting lanes skip their own scenarios, not running the suite per landing, not rebuilding the suite, and staying inside one project.

## Related documents

- [Design Document Writing Guide](design-doc-writing-guide.md) — the admission standard this document follows.
- [Failure Classification Protocol v1 and Mechanical Attribution](failure-classification-protocol-v1.md) — how a red is classified as product / environment / flake; the bisection protocol here depends on it.
- [Knowledge Base Design](knowledge-base-design.md) — where this document sits in the document-first workflow.
