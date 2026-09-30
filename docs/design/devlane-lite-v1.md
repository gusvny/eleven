---
title: "Lightweight Dev Lane (devlane-lite) v1"
category: design
tags:
  - dev lane
  - ticket workflow
  - machine gate
  - round economy
  - execution environment
status: draft
updated: 2026-09-30
related:
  - mode: dependency
    target: failure-classification-protocol-v1.md
    note: how a red is attributed (lane-red vs main-red) — this document consumes those rules unchanged
  - mode: dependency
    target: deepseek_harness_and_temporal_based_multi-agent_mechanism.md
    note: the stage machinery this document re-profiles rather than replaces
  - mode: practice reference
    target: ../testing-guide.md
    note: the L1/L2/L3 layering and the three-state execution contract (pass / fail / env-fail) used throughout
  - mode: practice reference
    target: ../terminology.md
    note: the terms this document must use (and the retired ones it must not)
---

# Lightweight Dev Lane (devlane-lite) v1

> One sentence: **make the effort proportional to the risk** — a small change must not pay the
> full lane's fixed cost, and no lane may re-run the same suite round after round to rediscover
> the same defect.

## Problem

**What is bad about the status quo.** The dev lane is currently the only disciplined road from a
request to `main`, and it has a single gear: every ticket — a colour value, a wording fix, a
one-file routing change — walks the same long stage sequence and pays a **full-suite machine gate
on every round**. The host has stopped reaching for it and does the work as ad-hoc direct fixes
instead. That is a signal about the lane, not about the work.

**Background knowledge** (for someone who has not been involved):

- A **ticket** runs through a lane: planning and plan review, implementation and integration-test
  design (in parallel), a machine gate, arbitration and acceptance walkthrough (in parallel), a
  merge check, and finally a human merge signature. The lane's work happens in an isolated
  worktree; `main` is the gatekeeper-owned branch that only verified work reaches.
- The **machine gate** runs the project's scenario registry (a few hundred cross-component
  scenarios) inside the lane and, for any red, a baseline pass on `main`; how a red is attributed
  (interrupt the developer vs record it as a pre-existing debt) follows the failure-classification
  protocol.
- **Arbitration** is the stage that reads the gate result and decides: the ticket is fine, the
  tests are at fault, or the code is at fault (and then it hands the developer a repair list).
  A bounded number of machine rounds is allowed before a human is asked.
- A **direct fix** is the informal road we have been using heavily: the host orders a change,
  it is made on `main` (or on a lane) under the host's instruction, verified with the affected
  scenarios, and committed with the reason recorded. It has no lane, no gate round, and — until
  now — no declared minimum discipline.
- `console` (the operator UI on the host) is host-owned and must never be restarted or occupied
  by any lane, test, or installer.

**Evidence** (measured on this repository, 2026-09-30):

| Observation | Measurement |
|---|---|
| Gate cost per round | 353–355 scenarios, **7.5–9.7 min** wall each |
| Repeated work | The ledger holds **76,558 scenario executions of 355 distinct scenarios** — 99.9% of executions are repeats; the most-run scenarios have each run **236 times** |
| Agent/gate time per ticket | t260929-22 **231 min** (14 arbitration rounds = 135 min, 10 implementation rounds = 77 min); t260922-18 **140 min** (one-shot stages alone: plan 17, test design 39, plan review 10); t260925-05 **82 min** |
| Round-to-round interval | ≈1 h per cycle on a stuck ticket; the gate is only ~8 min of that, the rest is stages plus queueing |
| Partial repair lists | On t260929-22 arbitration's ticket face listed **3** failing faces while a full sweep of the same commit found **375** violations of the same family in one polarity. The repair list was a sample, so every round discovered "new" faces |
| Human gate triggered by process, not risk | The same ticket was blocked for a human **twice** because a *round counter* exceeded its cap — both times while the red set was still shrinking and converging |
| Chronic churn occupying gate slots | Four load-sensitive scenarios failed in the lane every round and passed when re-run alone on `main`, yet stayed in the blocker list |
| Environment-dependent results | 2,368 executions recorded as environment-fail; hundreds of leftover worker processes and temporary directories from lane/test runs had to be reaped by hand |

**Why this is worth solving.** The cost is not one slow stage; it is **rounds × fixed cost per
round**, and the round count is inflated by repair lists that are samples rather than complete
sets, by re-running the whole registry per round, and by asking a human to decide on a counter
instead of on risk. The lane is therefore slower than the work it guards, which pushes the host
towards bypassing it — and a bypassed lane protects nothing.

## Requirement

**Goals** (each verifiable, i.e. usable as an acceptance criterion):

1. **R1 — Bounded low-risk path.** A low-risk change reaches `main` within **≤60 min of machine
   and agent time** and **≤3 machine rounds**. (Today: 82–231 min and up to 17 rounds.)
2. **R2 — No guarantee is traded for speed.** Human signature points, the recorded reason for
   landing, gray-box assertion discipline (public contracts and user-visible behaviour only), and
   coverage of the change's surface are all preserved; the count of human gates required for a
   low-risk change does not increase.
3. **R3 — Complete repair lists.** Every machine round that asks for a repair hands over **the
   complete set of violations found on the change's surface** — machine-readable, grouped by fault
   family — with the ticket face carrying a short summary that points at that set.
4. **R4 — Proportional gate.** By default a round verifies the **change surface** (the affected
   scenarios plus everything those depend on, plus any red carried from the previous round). A
   full-suite run happens **once, before landing**, not once per round.
5. **R5 — Human gate keyed on risk.** A human is asked when a verdict is contradictory, when the
   red set stops changing for consecutive rounds, when a contract or design decision is disputed,
   or when the host is explicitly needed — **not** merely because a round counter was exhausted.
6. **R6 — Mechanical routing.** Which profile a ticket takes is derived from the change surface
   (which files/contracts it touches, whether it crosses repositories or engine internals) by a
   rule anyone can re-run and audit; it is not chosen by mood and cannot be quietly overridden.
7. **R7 — Reproducible execution environment.** The same commit under the same profile produces
   the same verdict regardless of host state (installed tools, occupied ports, leftover processes
   from earlier runs). A run must leave no process, port, or temporary directory behind when it
   ends — normally, in error, on timeout, and on cancellation alike.
8. **R8 — Direct fixes are rare and accounted for.** A change reaches `main` through a lane; a
   direct fix happens only under an explicit human order, carries the same minimum discipline as
   any landing (stated criteria, affected-surface verification, a regression case, attribution, a
   green proof on the shared branch), and its reason is recorded as evidence about the lane. The
   measurable form of this requirement: for the classes the light lane covers, direct fixes go to
   zero, and every remaining one carries a stated reason.
9. **R9 — A working agent can finish its own work.** No stage may depend on a hand-off that exists
   only because the execution environment withholds something the work needs (a commit, a build, an
   environment-dependent check). Where such a hand-off exists today, removing it must not remove
   the guarantees it currently carries: scope audit, one commit per stage, attribution, and the
   clean-tree invariants the gate relies on.

**Stakeholders.** Host — decides the profiles and their thresholds; cares that work finishes fast
and that nothing lands without a reason. Integration (main gatekeeper) — owns the gate's meaning;
cares that attribution stays honest and that a green means something. Developer role — consumes
repair lists; cares that one round's list is complete enough to finish the job. Ops/console —
cares that the operator UI stays host-owned and that runs stop eating the machine.

**Upfront constraints** (boxes that must not be broken):

- The operator console on the host stays host-owned: no lane, test, or execution environment may
  restart, occupy, or reach it.
- Human signature points stay; nothing lands in `main` without a recorded who/what/why.
- The failure-classification protocol's semantics (how a red is attributed) are consumed as-is.
- Engine changes remain replay-safe for already-running tickets.
- Ticket-face text stays English; documents stay English; retired terminology stays retired.

## Nongoal

- **Not lowering the bar for risky work.** Engine internals, cross-repository contracts, release
  and publication faces keep the full lane. This document adds a light path; it does not weaken
  the heavy one.
- **Not replacing human review with automation.** The human gate moves to risk signals; it does
  not disappear.
- **Not building a second orchestrator.** The existing stage machinery, gate, and ledger are
  reused; a profile is a configuration of them, not a new system.
- **Not optimising single-stage model latency.** Individual agent stages (17–39 min one-shots
  included) are real cost but the dominant term is round count; latency work is a separate
  document.
- **Not containerising everything in v1.** The execution-environment option is developed and
  adopted in stages, starting where isolation pays immediately (see Proposal §4.4); a full
  containerised fleet is out of scope for this cycle.
- **Not changing what a scenario asserts.** Coverage selection may shrink a round's *scope*; it
  may never relax an assertion or skip a case silently.
- **Not keeping direct fixes as an equal road.** They are an escape hatch for the cases the lanes
  still cannot serve; the measure of success is that those cases shrink, not that the hatch gets
  more comfortable.
- **Not trading the audit trail for agent autonomy.** If a working agent is empowered to finish its
  own work (commit, build, verify), the checks that the environment used to enforce by refusing
  access must be re-established as recorded, auditable contracts — never dropped.

## Proposal

### 4.0 High level

Two lane profiles over one stage machinery — plus an **emergency escape that is not a profile** —
and four disciplines that make the *existing* lane affordable:

| Road | Who it is for | Stages it runs | Gate scope |
|---|---|---|---|
| **Light lane** | low-risk tickets (one plugin, presentation, wording, single-file routing) | plan → implement → gate → merge | change surface per round; full suite once before landing |
| **Full lane** | engine internals, contracts, cross-repo, release faces | planning + plan review + implementation + test design + gate + arbitration + acceptance walkthrough + merge check + merge | full suite per round (unchanged) |
| *Direct fix (escape)* | only under an explicit human order, when the lanes cannot serve; each use is recorded as evidence about the lane | none (no ticket) | affected scenarios only, on the shared branch |

Four disciplines, applied to every road:

1. **Round economy** — a repair list is always complete and grouped by fault family; a round that
   cannot change its verdict is not run; a round whose red set stopped moving escalates to a human.
2. **Proportional gate** — the surface of verification is derived from the change surface; the full
   registry is reserved for the landing check.
3. **Risk-keyed human gate** — humans are asked on disagreement, stagnation, and contract doubt.
4. **Reproducible execution environment** — a lane's verdict depends on the commit and the
   profile, not on the host's mood.

The tradeoff we accept openly: **the light lane purchases speed with scope, and pays it back at
landing** (the full-suite check before merge) and with a stricter rule for appending red names
afterwards. If a light-lane ticket turns out to touch more than its declared surface, it is
promoted to the full lane mid-flight — promotion is cheap, silent scope creep is not.

### 4.1 Profiles and routing

**Settled (host decisions, 260930):**

1. **The light lane is its own workflow, not a mode inside the existing one.** Sharing the existing
   lane's stage machine would mean threading a profile branch through a very large, replay-sensitive
   body of control flow, and would put every in-flight ticket's history at risk. The two lanes
   instead **share the machinery that actually does work** (the activities: workspace preparation,
   agent stages, the machine gate, merge check, merge, settlement, teardown — any workflow may call
   them), and the light lane carries only its own short, simple stage walk. Registration is a
   one-line addition to the workflow registry the engine already keeps, gates are already keyed per
   (template, stage), the stage graph the console draws is already derived per template, and the
   ticket-creation face already discovers templates from the engine rather than a hardcoded list —
   so the surrounding product faces need no change.
2. **A red in the light lane goes to a human, not to an arbitration round.** One machine round, the
   complete violation list, then a person decides. This is deliberate: it keeps the lane light (the
   arbitration loop is the most expensive part of the current lane by measurement) and it matches
   what a light lane is for. If experience later shows that most reds are self-healing, a thin
   arbitration call can be added — the machinery is an activity away.
3. **Routing starts explicit, becomes mechanical later.** For the first phase a ticket is created
   as a light-lane ticket on purpose; the mechanical rule (derived from the change surface, with
   unclassified cases falling to the full lane) is added once there is field data on what the
   light lane can actually carry. A light ticket that turns out to need the full lane is handled by
   creating a full-lane ticket for the remaining work — lanes are not migrated mid-flight, because
   a running workflow cannot change its class.
4. **`main` is synced into the lane once, right before the machine gate.** The gate runs the
   project's integration command inside the lane's own worktree, and that worktree is a snapshot of
   `main` taken when the ticket was created — so a fix that lands in `main` afterwards is invisible
   to the gate, and a red that is really `main`'s account gets attributed to this ticket (the
   developer is then asked to repair something that is not theirs, and the same round repeats).
   The pre-gate sync — the mechanism the full lane already uses, extracted into one shared helper:
   merge `main` into the lane once per round, an is-ancestor fast path when the lane is already
   level, the existing conflict-resolution loop when it conflicts, a loud block for a human when
   the sync itself fails — makes the verified tree the tree that would be merged. It changes only
   the tree under verification: no gate criterion, no attribution rule and no remedy is relaxed,
   and it adds no second implementation of the sync to the light lane.


A profile is defined by three things: which stages run, how wide the gate is, and which human
gates are mandatory. Routing is derived from the change surface: files touched, contracts touched,
repositories crossed, and whether engine internals are involved. The rule must be re-runnable
after the fact, so that any ticket can be asked "why did this go down the light road?" and get an
answer from the artifacts rather than from memory. The host may always override upward; downward
overrides are recorded and, if they recur, are evidence that the rule is wrong.

### 4.2 Round economy (the largest single win)

- **Complete lists.** A round's repair list is the complete set of violations on the change
  surface, written to a machine-readable artifact; the ticket face carries the count, the worst
  offenders, and a pointer. Partial lists are the direct cause of the multi-round churn measured
  above.
- **Family grouping.** Violations are grouped so that one repair pass can clear a family (same
  mechanism, same declaration, same class of element). A repair list that names nine members of one
  family is one task, not nine.
- **No-progress stop.** If consecutive rounds produce an identical red set, the loop stops and a
  human is asked; re-running the same tree is not a strategy.
- **Churn re-probe.** A red that passes when re-run alone on `main` is classified before it may
  occupy a blocker slot again, so load-sensitive names stop taxing every round.
- **Cheap verification of a fix.** The instructions handed to the developer must include the exact
  criteria a fix will be judged by (the measured values and the bar), so the repair is verifiable
  without waiting for the next full round.

### 4.3 Proportional gate

The change surface is computed from what actually changed, then widened by dependencies and by any
red inherited from the previous round; a path that cannot be classified widens to the whole
registry rather than being dropped. The full registry runs **once, at landing**.

Two things worth stating precisely, because they are easy to get backwards:

- **The authorization rule already works this way.** A round that ran a narrowed surface is
  feedback only; when a verdict of "fine" is reached on such a round, a **closing full run** is
  performed before it counts, and new reds from that run void the verdict. So narrowing a round
  never narrows what authorizes progress — it only decides how much the *earlier* rounds cost and
  what they can see.
- **The gap worth fixing is the feedback surface, not the authorization.** Today's narrowed round
  contains the previous round's reds and nothing else, so a change that breaks something **new**
  cannot show up until the closing full run — a wasted cycle. Widening the feedback surface to
  "what this change can actually affect ∪ previous reds" is therefore the point: it catches new
  damage in the cheap round instead of the expensive one.

A name that appears for the first time in the closing run is recorded and attributed before it may
block.

### 4.4 Execution environment

The environment question is worth answering explicitly, because "give the agents a container with
full access" is attractive and only *partly* right.

Options considered:

| Option | What it buys | What it costs / risks |
|---|---|---|
| **A. Host process** (today): agents and the gate run on the host | simplest; maximum visibility of artifacts for human review | results depend on host state (tools, ports, leftovers); permission friction wastes turns; parallel lanes contend for CPU, ports, and shared consoles; residue accumulates |
| **B. Container per lane**, agents and gate inside, lane directory mounted, no host ports | deterministic toolchain; parallel lanes truly isolated; teardown = destroy; permission friction inside the box disappears | the mount is the real trust boundary — mounting the whole repository or the host's state directories lets one mistake damage things outside the lane; credentials must be injected, never baked; nested container needs for some scenarios do not compose cleanly on every host; path/lane identity must be re-aligned or the engine misreads the lane |
| **C. Container for the gate runner only** | kills the entire class of environment-flavoured reds and the residue problem; host keeps running agents as today | does not remove permission friction for agents; two environments to keep in sync |

**Recommendation.** Adopt **B as the target shape, entered from C**: start by moving the *gate*
into a disposable per-lane environment (highest isolation per unit of risk, no change to how
agents think), then move agent execution in, one lane profile at a time. The second step carries a
second payoff beyond isolation — it removes the hand-off described in §4.4.1, which exists only
because the current environment cannot let the agent finish its own work. Non-negotiable properties
of any containerised execution:

- The trust boundary is the **container**, not the host: "full access" means full access *inside*,
  with the mounted lane directory and an injected credential as the only bridges, and no route to
  the operator console.
- Mounts are **lane-scoped**; the shared branch and the host's state directories are read-only at
  most, never writable by an agent.
- The toolchain is **provisioned and pinned** in the image, so "missing tool" stops being a
  category of failure and the environment fingerprint can name the image rather than the machine.
- Teardown is unconditional: normal end, error, timeout, cancellation — every terminal state
  reclaims processes, ports, and temporary areas (this is the discipline the residue measurements
  above show we currently violate).

**What containerisation does *not* buy.** It does not shorten rounds, and permission friction is
not the measured bottleneck (environment-fail is ~3% of executions; the repeat tax is ~100%). Its
justification is determinism, isolation, concurrency headroom, and clean teardown — all of which
it buys well — so it should be sequenced *after* or *alongside* round economy, not instead of it.
Equally important: a full-access environment with a generous mount would make the **audit trail**
the only remaining control, so attribution (who changed what, under whose order) becomes more
important under containers, not less.

#### 4.4.1 One layer of hand-off that exists only because of the sandbox

There is a sharper reason to give the working agent a self-contained, fully empowered environment
than "permissions are annoying": **today the agent cannot finish its own work, so another process
has to finish it.**

As the engine's own documentation states it: a lane's repository metadata lives *outside* the
agent's writable scope, so the agent committing its own change is physically impossible; the
stage's work is therefore settled on the agent's behalf by an unsandboxed process afterwards, and
the engine documents the commit as "not part of the dispatch contract". In other words the
hand-off is a **workaround for the execution environment, not a designed boundary** — and it is
paid for on every single stage:

- an extra hop whose semantics have to be re-derived (what counts as "the agent's work"; how to
  isolate edits made outside the declared scope; what to do when the workspace is already clean,
  is mid-merge, or contains engine runtime directories);
- a failure family of its own (a settlement that produces nothing, the wrong thing, or the wrong
  message), which then has to be diagnosed by reading the settling process's log rather than the
  agent's;
- a weaker answer to "what did the agent actually do?" — the agent's evidence and the settled
  commit are produced by two different processes.

A scoped container removes the *reason* for the hand-off: give the agent a self-contained writable
view of its lane and it can commit, build, and test as one actor. What must **not** disappear with
it (these move from "enforced by who is allowed to write" to "enforced by an audited contract"):

1. **Scope audit** — the boundary is checked and violations named, before or immediately after the
   change lands; gaining write access never means losing the write-scope check.
2. **One commit per stage** — the single revert unit and the history convention survive; a stage
   that scatters commits is a contract violation, not a style preference.
3. **Attribution** — every commit says which stage produced it and under whose instruction. With
   the mount no longer the control, the record is the control.
4. **Clean-tree invariants** — whatever the gate and the merge check rely on (a committed, clean
   lane tree) stays true by construction.

Net effect: one fewer hand-off, one fewer failure family, and one fewer place where the engine has
to reason about "uncommitted work that is not the agent's". That is a **simplification** — which is
why it belongs in this document even though containers do not, by themselves, shorten rounds.

### 4.5 Direct fix: intentionally rare, not a road

Direct fixes were how this project kept moving while the lane was too slow, and they are the thing
this document exists to make unnecessary: **the goal is that a change completes inside a lane fast
enough that nobody wants to reach around it.** A direct fix is therefore an **emergency escape**,
not a profile on equal footing with the lanes:

- it is admissible only under an explicit human order, and the reason for going around the lane is
  recorded with the change;
- it carries the same minimum discipline as any other landing (stated criteria, affected-surface
  verification, a regression case so the fix cannot silently revert, attribution, and a green
  result on the shared branch) — a change that cannot satisfy these is a ticket, not a shortcut;
- **each use is treated as evidence about the lane**, not as a neutral choice: the class of change
  that needed bypassing becomes an input to profile thresholds and to the gate's scope rules, and
  the success criterion is that bypasses for light-lane classes go to zero.

### 4.6 How we will know it worked

Machine-time per ticket and rounds per ticket become recorded, comparable numbers (the same way the
figures in Problem were obtained), together with the repeat rate of scenarios. Success looks like:
low-risk tickets inside R1, full-suite repeats reduced by an order of magnitude, human gates
triggered by risk signals, environment-flavoured failures no longer appearing as a category, and
**direct fixes for light-lane classes at zero** (with each remaining bypass carrying its reason).

### 4.7 Tie-back

This proposal **solves** the Problem's round-count inflation (complete lists, family grouping,
no-progress stop, churn re-probe), the per-round full-suite tax (proportional gate), the
process-keyed human gate (risk-keyed gate), and the environment-dependent verdicts and residue
(scoped, disposable execution environments) — while **satisfying** R1–R9 and **avoiding** the
Nongoals: risky work keeps the full lane, human signature points stay, a scenario's assertion is
never relaxed, and no second orchestrator is built.
