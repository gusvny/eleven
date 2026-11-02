---
title: "Optional GitHub Pull-Request Delivery Flow v1"
category: design
tags:
  - ticket workflow
  - delivery
  - human review
  - pull request
  - github
status: draft
updated: 2026-11-02
related:
  - mode: dependency
    target: develop-buffer-v1.md
    note: the line-buffer flow that this document explicitly leaves untouched
  - mode: reference
    target: design-doc-writing-guide.md
    note: the admission standard this document follows
---

# Optional GitHub Pull-Request Delivery Flow v1

## Problem

**What is bad about the status quo.** Every delivery of this engine ends inside this
machine: a ticket's work is judged by machine gates, a person signs a local merge gate,
and the result is squashed onto a local branch. There is no place outside this machine
where a change can be read, commented on, or approved by people who are not sitting at
this console. A team that reviews code on GitHub therefore has to review the same change
twice — once here, in a console only this operator can see, and once again on the
platform — and the second review leaves no trace in the ticket.

**Background knowledge a newcomer needs.**

- A ticket walks a fixed sequence of stages. The last machine judgement before delivery
  is the merge check: it re-runs the lane's own verification battery and refuses when the
  lane is not green. What follows is a human signature and then a landing (a single
  squashed commit per ticket).
- The develop-buffer flow is different: a ticket lands on an internal line of
  accumulation, and that line reaches the main branch later, in a batch, by promotion.
  That flow already has its own release judgement and is not what this document is about.
- A "review request" (pull request) is the standard platform mechanism: a branch, a target
  branch, a diff, a discussion thread, and a merge that records who merged what and when.

**Evidence that this is a problem worth solving.** The operator's own words, 261102: they
want a project-level switch so that a delivery becomes a review request on GitHub, a merge
of that request ends the task, and comments on it send the work back. Today that whole
chord is missing: the engine knows nothing about review comments, so a comment cannot
influence a ticket at all.

## Requirement

**Goals (each one verifiable).**

1. A project carries an attribute that says whether deliveries use the review-request flow.
   A project that has not enabled it behaves exactly as it does today, with no observable
   difference whatsoever.
2. Enabling the attribute requires a credential supplied by the operator. The delivery flow
   cannot start without a usable credential, and an unusable one stops the ticket by name
   instead of failing silently.
3. With the attribute enabled, a delivery that passes the machine gate produces a review
   request on the platform for every repository the ticket actually changed. The delivery
   is not landed locally by the engine in that case.
4. The ticket waits for the platform. Its merge ends the task — that merge, not a local
   signature, is the acceptance record. A rejection or an abandoned request never counts
   as acceptance.
5. Comments on the request send the ticket back for rework, once per comment round, with
   the comment round recorded on the ticket. The engine's own comments never send the
   ticket back.
6. Multi-repository projects: a change that spans repositories produces one request per
   touched repository, and the ticket ends only when all of them are merged. A partly
   merged delivery is a named, non-terminal state.
7. After the platform merges, the local main branch is reconciled with the remote without
   ever rewriting or discarding anyone else's work: only a fast-forward plus a
   content-equality check is allowed; anything else stops the ticket by name for a human.
8. Every failure face is named, and no failure face loses the ticket: an absent or expired
   credential, an unreachable platform, an already existing request for the same branch, a
   deleted branch, red platform checks, platform rate limiting, a partial merge, a content
   mismatch, and a local branch that has drifted.

**Stakeholders.**

- The operator (host): wants one switch, one credential, and a delivery that is reviewable
  and auditable outside this console. They keep the decisions: whether a project enables
  the flow, and which credential is used.
- Reviewers on the platform: they need the request to be readable on its own — what ticket
  it belongs to, what was verified, and where the evidence is.
- This engine's own gates: nothing they judge may be weakened by the switch. The switch
  changes where a delivery is accepted, never what "green" means.
- Agents working tickets: they need one unambiguous answer to "is the delivery done?", and
  the answer must not depend on a human remembering to look at a web page.

**Upfront constraints.**

- The credential is a secret. It must never appear in a ticket face, a receipt, a ledger
  row, an error message, or anything a lane can read. It lives outside every repository
  worktree, in the per-user sandbox home shared by all projects, and it carries the least
  privilege that can open a request on the declared repositories.
- No inbound network path: the engine cannot be called back by the platform. Whatever the
  engine learns, it learns by asking.
- The develop-buffer flow is out of scope for this version: those tickets keep landing on
  the line and being promoted as they are today.
- Default is off. A project that never touches the attribute must not pay any cost —
  not a request, not a credential read, not a poll.

## Nongoal

- **Not a replacement for the machine gates.** The merge check, arbitration, evidence
  declarations and write-set gates keep their present meaning and order. This flow starts
  where they end.
- **Not a code-review tool of our own.** No diff viewer, no inline discussion in this
  console; the platform is the place where people talk.
- **Not a merge-queue or auto-rebase machine.** The engine never rewrites history on the
  platform, never force-pushes, and never resolves a conflicting review request by itself.
- **Not CI orchestration.** Red platform checks are surfaced and recorded, but designing a
  CI pipeline is the project's business, not this flow's.
- **Not the develop-buffer line's business in v1.** Changing how the line accumulates and
  is promoted is a separate decision.
- **Not multi-provider.** GitHub is the platform this version speaks to; a second provider
  is a later decision, and the design keeps the provider boundary visible so that decision
  stays cheap.

## Proposal

**High level.** The switch turns one step of the ticket's life into a different kind of
step. With the switch off, a green machine gate is followed by a local human signature and
a local landing — exactly as today. With the switch on, the same green gate is followed by
a *review request* published for each repository the ticket changed, the ticket enters an
*awaiting review* state, and from that moment the platform owns the verdict:

- **merged** — the delivery is accepted; the ticket ends, citing the platform merge as its
  acceptance record;
- **new comments** — the ticket goes back to work, once per comment round, carrying what
  was said;
- **still open** — the ticket waits, quietly, without holding a working slot.

The engine learns which of these happened by asking the platform on a slow, bounded beat.
That is the only notification channel, and it is deliberately boring: it cannot be spoofed
from outside, it survives restarts, and a missed beat costs a few minutes, never a ticket.

**Two lines of thought that shape the details.**

*Comments are rounds, not events.* A request can collect several comments before anyone
acts; treating each as its own trigger would restart the work five times for one review.
The unit is therefore a comment round: whatever arrived since the ticket last went back to
work is delivered together, and only then does the ticket move. The same rule makes the
engine's own comments harmless — they belong to no round the engine reacts to.

*Merging is a fact, reconciling is work.* The platform's merge settles the delivery, but
this machine's main branch still has to catch up before the next ticket can be judged
against it. Catching up is not a merge: it is allowed to be a fast-forward only, and it is
verified by comparing what the platform says it merged with what the local branch now
contains. Anything else — a local branch ahead, behind by someone else's work, or content
that does not match — is a named stop handed to a human. This is the same discipline the
engine already applies to its own landings: never silently adopt a tree you did not judge.

**What a reviewer sees.** Each request names the ticket and its title, states what the
machine gates verified and where that evidence lives, and points back to the ticket. A
reviewer who has never seen this console must be able to decide from the request alone
whether the change is acceptable.

**Audit trail.** For every ticket that uses the flow, the record answers: which request
belongs to which repository, what the platform reported at each beat, which comment round
sent the ticket back and what was in it, and which merge ended the ticket. The ticket face,
not a web page, is where an operator looks for that.

**Tie back.** This proposal turns the missing review chord of the *Problem* into a
project-level switch with a platform verdict, which satisfies *Requirement* 1 through 8 —
including the default-off promise, the multi-repository rule, the comment-round judgement
and the never-force reconciliation — while staying inside the *Nongoal* boundary by not
touching the machine gates, the develop-buffer flow, or the platform's own CI.
