---
title: Ledger Record Models v1 (what the ledgers store, and how)
category: reference
tags:
  - fact ledger
  - record shape
  - data model
  - review draft
status: draft
updated: 2026-10-09
related:
  - mode: dependency
    target: ../design/project-fact-ledgers-v1.md
    note: why the families have the homes they have; this document is only the what and the how
  - mode: dependency
    target: ../design/ticket-relations-v1.md
    note: the relation records and their rules
  - mode: dependency
    target: ../design/develop-buffer-v1.md
    note: the delivery records (landing, certification, batch, freeze, revert)
---

# Ledger Record Models v1 (what the ledgers store, and how)

**What this is.** The design documents state *why* a fact lives where it lives. This document states **what a record is, what question it answers, how it is shaped, and what the values look like**, so it can be reviewed before it is built and so two implementations cannot drift. Every record carries an **example**; every field carries an **example value**. Entries marked **today** exist on disk now (their shapes were read from the store, not remembered); **proposed** means designed and not yet built.

## Naming (the words this document uses, and the collisions it avoids)

| Word | Means | Deliberately not |
|---|---|---|
| **lane** | the per-ticket working copy — where a ticket's own work happens | never the integration container |
| **line** | the integration container between the lanes and `main`: a **declared scope with an owner**, serialized landings, one shared proof | **not** a branch name (a branch is one way of implementing a line), and **not** a piece of work |
| **main** | the delivered target | we no longer say "the delivered line" — that phrasing collided with *line* and caused exactly the confusion this table exists to stop |
| **epic** | a piece of work | we avoid the phrase "a line of work" entirely |
| **buffer** | the role a line plays, and the design's own name for it (develop-buffer) | not a separate object |

## Conventions that apply to every record

| Rule | Example | Status |
|---|---|---|
| **Time is `at`: an integer count of milliseconds since the epoch** | `"at": 1791507005123` | **Decided by the host (261009).** New records use it; older records keep the form they were written in and are read as they are |
| A record carries the version of its own shape | `"v": "event-ledger-v1"` | **Half in place**: only the event ledger has it |
| Facts are appended; a correction is another fact | a correction record names `"supersedes": "rel-261009-0004"` | Today by convention; stated in the ledger design |
| An entity and an observation of it are two records | entity `finding fi-9c1e`, observation `{"finding": "fi-9c1e", "period": "20261007"}` | Proposed; the fault ledger violates it today |
| Identity is minted, never derived, never reused | `"id": "cert-261009-14"` | Today for inspection findings; to be the rule everywhere |
| One direction is stored; the reverse is derived | store `repair: t261009-04 → t261008-45`; read the reverse from it | Proposed |
| Order comes from the ledger, not from a clock | `"seq": 41077` | Proposed; today everything orders by timestamp |
| Records carry references, not payloads | `"evidence": "ledger/scenario-results.jsonl#run-261009-14"`, never the raw log or a token | Proposed |
| **Record what cannot be derived; derive what can** | the state a landing sat on and the range a certification continued from are **not** stored — both are derived from the certification ledger's order | Proposed; `base` and `covered_from` were dropped for this reason (261009) |
| **A summary lives with the data it summarises** | a run's counts, environment, width and duration are fields of the **run** record; a certification cites the run instead of restating it | The test for a summary: would a reader be forced to open the raw body to make a decision they make daily? and can it be checked against the body? If yes it is kept — **at the level of the data, not one level up**. Anything that fails both tests is duplication (`base`, dropped) |
| A machine is provenance, never authority | `"machine": "mac-mini-2"` decides nothing | Proposed |
| **A landing is one act over every repository it names: all or nothing** | see the multi-repository example under *landing* | Proposed — see below for why a partial landing is not an option |

**The older time shapes (kept for reading, not for writing):** `wall_s` as a duration in seconds (run results, and the certification examples before the rename above); `at` as integer milliseconds (executor actions, requests, alerts, grants audit); `ts` as float seconds (capacity limit audit); `at` as float seconds (inspection reviewed-paths); `ts` as an ISO string with offset (run results).

## A. Delivery records (proposed — the buffer flow)

**One rule covers every field that names a state.** In a multi-repository project a "revision" is really a set of per-repository revisions, so `repos`, `base`, `covered_from`, `main_before` and `main_after` are all **sets**, one entry per repository, and in the single-repository case each has exactly one member. Anything that names a state and is not a set would have to be rewritten the day a second repository appears. The same applies to `main`: in a multi-repository project "main" is per repository, so a batch advances several of them and records all of them. Where such a state is derived rather than recorded, it is derived **per repository** too.

### landing — "what content did this ticket put on this line, and on top of what?"

Single repository:

```json
{
  "id": "ldg-261009-0007",
  "ticket": "t261008-45",
  "line": "default",
  "repos": [
    { "repo": "sandbar", "revision": "9f3c2a1b" }
  ],
  "seq": 41077,
  "at": 1791507005123,
  "actor": "engine"
}
```

Several repositories — still **one** landing, one act:

```json
{
  "id": "ldg-261009-0008",
  "ticket": "t261009-10",
  "line": "default",
  "repos": [
    { "repo": "sandbar", "revision": "7d21c0a4" },
    { "repo": "dsh", "revision": "41b0e771" }
  ],
  "seq": 41098,
  "at": 1791510000000,
  "actor": "engine"
}
```

**Where the state a landing sits on is found — it is not stored here.** A landing says only what content it put on the line; *what it sat on* is **derived**: for each repository, the most recent certification on that line, and before the line's first certification, the revisions the line was declared from. Storing that set on the landing would be a second answer to a question the certification record already answers, and the two would eventually disagree.

Deriving it costs nothing and buys a check. Per repository, **the certified revision must be an ancestor of the revision that landed**: that one check catches a landing that skipped over certified content, a lane whose base is behind, and a landing that would revert content the line has already certified — reported per repository, because in a multi-repository project those failures are per repository. A repository the line has never certified is covered by the declared starting revisions, so the range never has an undefined beginning, and a repository the landing does not name simply takes no part in it.

### certification — "may this content be delivered, and what was actually proved?"

```json
{
  "id": "cert-261009-15",
  "candidate": "cand-261009-15",
  "line": "default",
  "repos": [
    { "repo": "sandbar", "revision": "9f3c2a1b" }
  ],
  "run": "run-261009-14",
  "booked_red": "known-red-baseline@2026-10-04",
  "judged_by": "integration/run_scenarios.py",
  "seq": 41076,
  "at": 1791508600000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `cert-261009-15` | The judgement, cited by batches and freezes |
| `candidate` | `cand-261009-15` | **What is judged is the set of revisions that would be delivered together**, not a branch: the line's head today, a merge of heads once there are several lines |
| `line` | `default` | Which line this judgement is about |
| `repos[].revision` | `9f3c2a1b` | The exact content the judgement covers |
| `run` | `run-261009-14` | **Which run answered it.** A certification does not restate what a run measured — see below |
| `booked_red` | `known-red-baseline@2026-10-04` | Which expected-red list was in force when this was judged. It appears in no run, and without it a later reader cannot tell a new red from a known one |
| `judged_by` | `integration/run_scenarios.py` | What performed the judgement |
| `seq` | `41076` | Order, for the same reason as on a landing: the certified prefix is the certifications on this line, in order — **derived, not restated** |
| `at` | `1791508600000` | Milliseconds since the epoch |

**A run says what happened; a certification says what was judged — and a run has its own record.** Everything measural belongs to the run: what ran, how many cases, how many failed, in which environment, at which width, for how long, and the verdict that follows mechanically from those rows. The certification binds that run to a **candidate** and to the **expected-red list in force**, which is the part no run can know. Two consequences worth stating:

- **No verdict on the certification.** A certification whose run came back red is still a certification — that is how a freeze gets opened — and the verdict is read from the run. Carrying a second verdict here would be a second answer to one question.
- **One run can back more than one certification.** A green row is reusable when the commit, the fingerprint and the width all match, so an unchanged candidate can be re-certified without re-running, and a re-certification cites the same run rather than restating it. That is why runs are records in their own right rather than fields of a certification.

### freeze episode — "why is nothing landing on this line, and who is fixing it?"

```json
{
  "id": "frz-261009-03",
  "line": "default",
  "opened_at": 1791508600000,
  "opened_by": "cert-261009-14",
  "culprit_candidates": ["t261008-45", "t261008-46"],
  "attribution": "boundary, culprit not isolated",
  "state": "open",
  "closed_at": null,
  "closed_by": null,
  "reopened_reason": null
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `frz-261009-03` | A thing with a lifetime, not an event: "why is nothing landing" must be answerable while it is open |
| `line` | `default` | A freeze is per line — one line's red does not stop another's landings |
| `opened_at` | `1791508600000` | When the line stopped; with `closed_at`, **how long it was stopped** |
| `opened_by` | `cert-261009-14` | The certification that caused it: the freeze **points at its cause** instead of saying "something is red" |
| `culprit_candidates` | `["t261008-45", "t261008-46"]` | The landings inside the covered range — **deliberately a set**, narrowed later |
| `attribution` | `isolated: t261008-45` / `boundary, culprit not isolated` | The design requires that the second sentence be sayable |
| `state` | `open` / `closed` | Current state, held as its own record rather than by editing the episode |
| `closed_at` / `closed_by` | `1791515000000` / `t261009-04` | When and by what remedy the line reopened |
| `reopened_reason` | `null` / `the remedy did not hold` | If the same content red comes back |

### batch — "what did a person approve, and what did main become?"

```json
{
  "id": "batch-261009-02",
  "certification": "cert-261009-14",
  "line": "default",
  "repos": [
    { "repo": "sandbar", "revision": "7c1d90ab" }
  ],
  "tickets": ["t261008-45", "t261008-46"],
  "main_before": [
    { "repo": "sandbar", "revision": "de46ce42" }
  ],
  "main_after": [
    { "repo": "sandbar", "revision": "7c1d90ab" }
  ],
  "signer": "integration",
  "on_behalf_of": "host",
  "authority": "宿主令 261009「resume 2 个 ticket，按优先级」",
  "note": "two engine-hardening landings",
  "at": 1791512000000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `batch-261009-02` | Cited by a ticket's outcome and by any later withdrawal |
| `certification` | `cert-261009-14` | **Which proof justifies this delivery** — a batch can never name content without one |
| `line` | `default` | Which line it takes content from |
| `repos[].revision` | `7c1d90ab` | What actually moved |
| `tickets` | `["t261008-45", "t261008-46"]` | Whom it delivers — the only source for "delivered" |
| `main_before` / `main_after` | `[{"repo":"sandbar","revision":"de46ce42"}]` / `[… "7c1d90ab"]` | Makes the batch a fact about a range; rollbacks and withdrawals can name it |
| `signer` | `integration` | Who actually signed |
| `on_behalf_of` | `host` / `null` | Delegation: the record names both sides |
| `authority` | `宿主令 261009「...」` | The order being executed — the third field of the `by`/`who` split |
| `note` | `two engine-hardening landings` | The human's own words about what this batch is |
| `at` | `1791512000000` | Milliseconds since the epoch |

### revert — "this content was withdrawn; where does it still live?"

```json
{
  "id": "rev-261009-01",
  "landing": "ldg-261009-0007",
  "on": "main",
  "at": 1791515000000,
  "by": "host",
  "reason": "the lazy-path rewrite renamed a public constant",
  "propagated_to": [
    { "line": "default", "state": "pending" },
    { "line": "ui", "state": "applied" }
  ]
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `rev-261009-01` | The withdrawal is a fact about a landing |
| `landing` | `ldg-261009-0007` | The obligation attaches to **a specific piece of content**, not to a file or a ticket |
| `on` | `main` / `default` | Withdrawing from main and from a line are different acts with different propagation |
| `at` / `by` | `1791515000000` / `host` | When, and who decided |
| `reason` | `the lazy-path rewrite renamed a public constant` | Why the content had to go |
| `propagated_to[].line` | `default`, `ui` | **The point of the record**: every line that still carries the withdrawn landing is named, because a merge keeps it silently and the next batch would reintroduce it |
| `propagated_to[].state` | `pending` / `applied` / `line retired` | The obligation's state on that line — visible instead of remembered |

### ticket outcome — "where did this ticket end up?"

Delivered:

```json
{
  "ticket": "t261008-45",
  "landed_at": "9f3c2a1b",
  "certified_by": "cert-261009-14",
  "delivered_in": "batch-261009-02",
  "reverted_at": null,
  "waiting_since": null
}
```

Waiting for a certification:

```json
{
  "ticket": "t261008-50",
  "landed_at": "3b9ca940",
  "certified_by": null,
  "delivered_in": null,
  "reverted_at": null,
  "waiting_since": 1791510000000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `ticket` | `t261008-45` | One row per ticket |
| `landed_at` | `9f3c2a1b` / `null` | The content it put on the line, if it has landed |
| `certified_by` | `cert-261009-14` / `null` | The certification covering its landing — this, not delivery, is where the ticket's life ends |
| `delivered_in` | `batch-261009-02` / `null` | The batch that carried it; `null` is normal and is **not** a defect |
| `reverted_at` | `null` / `1791515000000` | Set when the content it landed was withdrawn |
| `waiting_since` | `1791510000000` / `null` | **What tells "waiting" apart from "stuck"**: a waiting ticket has a start time and a certification it is waiting for |

A projection, not a source: it is recomputed from the facts above, and if it disagrees with them, the projection is what is wrong.

## B. Relation records (proposed)

### relation — "why does this work exist?" / "who owns this boundary?"

```json
{
  "id": "rel-261009-0004",
  "from": "t261009-04",
  "to": "t261008-45",
  "kind": "repairs",
  "recorded_by": "integration",
  "reason": "the same lazy path constant",
  "evidence": "cert-261009-13",
  "at": 1791505000000,
  "v": "relation-v1"
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `rel-261009-0004` | Minted; a correction cites it |
| `from` / `to` | `t261009-04` / `t261008-45` | One direction stored; the reverse is derived |
| `kind` | `repairs` / `originates from a finding` | Only kinds with a live consumer |
| `recorded_by` | `integration` / `engine` | **Who may record what** is part of the design: a ticket may not record a relation that grants itself a permission |
| `reason` | `the same lazy path constant` | Mandatory — a relation whose reason cannot be written should not exist |
| `evidence` | `cert-261009-13` | What the record rests on |
| `at` / `v` | `1791505000000` / `relation-v1` | When, and the shape's version |

### relation correction — "that attribution was wrong"

```json
{
  "id": "rel-261009-0011",
  "supersedes": "rel-261009-0004",
  "from": "t261009-04",
  "to": "t261008-43",
  "kind": "repairs",
  "recorded_by": "integration",
  "reason": "the first attribution named the wrong landing",
  "at": 1791509000000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `supersedes` | `rel-261009-0004` | A wrong attribution is superseded, never erased |

### repository relation — a declaration, not a ledger

```yaml
base: sandbar
dependents:
  - dsh
proof_rule: touching base runs the dependents' scenarios too
```

| Field | Example value | Why it is there |
|---|---|---|
| `base` / `dependents` | `sandbar` / `[dsh]` | The subjects are repositories, not tickets; it changes rarely, so it is declared with the project layout |
| `proof_rule` | `touching base runs the dependents' scenarios too` | The **proof set** for a landing that spans repositories — a defined set instead of an improvised one |

## C. Knowledge records

### fault mode (entity) — "have we seen this before?"

```json
{
  "id": "KI-227",
  "title": "an uncommitted change on main blocks other tickets' merges",
  "state": "open",
  "blocking": false,
  "pattern": "merge_check dirty-tree guard",
  "trigger": "anyone leaves an uncommitted change in the main working tree"
}
```

**Today** these are prose entries in one file, edited in place; this is what the entity would look like. States: `open` / `booked red` / `fixed` / `obsolete`.

### fault-mode disposition (fact) — "do we accept this, or must it be fixed?"

```json
{
  "fault_mode": "KI-220",
  "from": "open",
  "to": "fixed",
  "who": "integration",
  "why": "removed the injected precondition",
  "fix": "t261008-24",
  "at": 1791520000000
}
```

The decision about a fault mode, as a fact — so that "we decided to live with it" is distinguishable from "we just hit it again".

### case ↔ fault mode link (fact) — "is this fault mode actually locked by a case?"

```json
{
  "case": "t261008-26-lane-vocabulary-fail-closed",
  "fault_mode": "KI-226",
  "marked_by": "integration",
  "at": 1791520000000
}
```

**Missing today**: the join exists only as prose citations, which is why the ledger reads as a search instead of a query.

### booked-red inventory (state) — "is this red new?"

```json
{
  "case": "t261004-26",
  "expected_red": true,
  "reason": "load flake in the full suite",
  "booked_by": "integration"
}
```

**Today**: a machine-read file in the repository.

### finding (entity) — "what is wrong here?"

```json
{
  "id": "fi-9c1e42a0",
  "subject": "stage-entry titles fall back to Chinese",
  "severity": "med",
  "evidence": [
    { "path": "server/plugin/x.ts", "line": 412, "quote": "阶段开始" }
  ],
  "why": "the UI copy contract is English",
  "suggestion": "use the stage id",
  "confidence": "high",
  "state": "open"
}
```

**Today**: produced by the inspection agent; the id is minted from the content and stable across periods, and the evidence is verified mechanically. Where the entity is *stored* is **not settled** (see open questions).

### finding observation (fact) — "is it still there, and for how long has it been?"

```json
{
  "finding": "fi-9c1e42a0",
  "period": "20261007",
  "revision": "de46ce42",
  "verification": "verified",
  "quote_fp": "a1b2c3",
  "at": 1791520000000
}
```

Proposed; today only the finding itself exists. Verification values: `verified` / `downgraded` / `unlocatable`.

### run (fact) — "what actually executed, and what came of it?"

The run's own record, written once at the end of a run:

```json
{
  "id": "run-261009-14",
  "line": "default",
  "repos": [
    { "repo": "sandbar", "revision": "9f3c2a1b" }
  ],
  "suite": "full",
  "source": "scheduled",
  "env_fp": "0febeeb6da6b25dc...",
  "conc_width": 3,
  "pool": "main:3,ro:3,browser-free:3",
  "started_at": 1791506200000,
  "duration_s": 2132,
  "cases": {
    "ran": 445,
    "passed": 443,
    "failed": 2,
    "env_failed": 0
  },
  "verdict": "red"
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `run-261009-14` | The identity the case rows and the certifications point at — without it, "this run" is not something a record can name |
| `repos` | `[{"repo": "sandbar", "revision": "9f3c2a1b"}]` | What was under test; a set, because a candidate may span repositories |
| `suite` | `full` / `fast-set` | Which proof this was: the certification's heavy one, or the set a lane runs |
| `source` | `scheduled` / `lane` / `change-triggered` | Why the run happened |
| `env_fp` / `conc_width` / `pool` | `0febeeb6...` / `3` / `main:3,ro:3,browser-free:3` | The comparability key: a green row may be reused **only** when the revision, this fingerprint and the width all match |
| `started_at` / `duration_s` | `1791506200000` / `2132` | What it cost and when — the numbers the budget and the throughput argument are made of |
| `cases.ran` / `passed` / `failed` / `env_failed` | `445` / `443` / `2` / `0` | **The pair that makes a run a proof.** `ran: 0` is never a proof, however green it looks — that was a live incident, and this counter is where that rule can be enforced |
| `verdict` | `red` | The mechanical roll-up of those counts |

**Its absence means the run did not finish.** The header is written when the run ends; rows without a header are an interrupted run, which is a state to see rather than a summary to invent. This is also the home of the two fixes the certification needed: the run identity, and (once landings span repositories) the repository.

#### run case rows (today's shape, with one addition)

```json
{
  "run": "run-261009-14",
  "ts": "2026-09-22T15:33:10+08:00",
  "commit": "da942b8f...",
  "env_fp": "0febeeb6...",
  "conc_width": 1,
  "pool": "ro",
  "scenario": "t260903-10-installer-console-line",
  "verdict": "pass",
  "wall_s": 0.043,
  "source": "baseline",
  "ticket": ""
}
```

**Today** these rows exist as shown, verbatim, except for `run`: the rows carry no run identity yet, which is why a certification could not point at a run and had to restate the counts. Adding `run` to each row is the one change this document asks of them.

### reviewed path (fact) — "has anyone looked at this file lately?"

```json
{
  "path": ".gitignore",
  "period": "20261007",
  "ts": 1791338554.34
}
```

**Today**, verbatim: what an inspection period actually examined (not a finding).

## D. Fleet and operations records (today)

### event — "what did the engine or the watchdog see?"

```json
{
  "v": "event-ledger-v1",
  "project": "sandbar",
  "scope": "project",
  "ticket": "t260928-20",
  "workflow": "DevLaneWorkflow",
  "template": "dev-lane",
  "stage": "create_plan",
  "state": "awaiting",
  "reason": "adopt dev-lane ..."
}
```

The only family that versions its shape.

### executor action — "what did the executor do, and on whose authority?"

```json
{
  "at": 1791188111775,
  "channel": "arg",
  "decision": "allowed",
  "grant": "sign",
  "grant_source": "grants.sign @ .../executor-grants.json",
  "idem": "a93cc061b4fcb867",
  "op": "sign",
  "session": "session-7685c51a-...",
  "ticket": "t261005-14"
}
```

Carries an idempotency key.

### request — "what was asked of the host, and what was answered?"

```json
{
  "type": "request",
  "id": "req-1790950261961-0001",
  "at": 1790950261961,
  "project": "sandbar",
  "kind": "question",
  "question": "给 sandbar 执行器开哪些授权？",
  "detail": "..."
}
```

`detail` is free text — exactly what "references, not payloads" should constrain.

### capacity limit change — "who changed how many tickets may run at once, and why?"

```json
{
  "ts": 1791503148.53,
  "project": "sandbar",
  "by": "host",
  "from": 8,
  "to": 10
}
```

`by` is free text that mixes identity, delegation and the order — see open question 2.

### authorisation change — "who was given what, and by whose order?"

```json
{
  "at": 1791007438979,
  "action": "grant-change",
  "project": "sandbar",
  "who": "宿主（经 sandbar 项目会话代写）",
  "from": {},
  "to": {
    "sign": true,
    "send-back": true,
    "rerun": true,
    "open-ticket": true,
    "pause-resume": true,
    "cleanup": true
  },
  "night_tier": null
}
```

Same problem as `by` above.

### capacity state — "who holds a slot right now, and who is waiting?"

```json
{
  "version": 1,
  "holders": [
    { "ticket": "t261008-29", "since": 1791495146.2, "reason": "human-hold" }
  ],
  "queue": []
}
```

Current state, read as a whole under a lock. Reasons seen: `running`, `human-hold`.

### authorisation state — "what may the executor session do right now?"

```json
{
  "executor_sessions": ["session-7685c51a-..."],
  "grants": {
    "cleanup": true,
    "open-ticket": true,
    "sign": true
  },
  "open_ticket_cap": 3,
  "open_ticket_epics": ["concurrency-limit"]
}
```

### alert — "what did the watchdog shout about, and at what level?"

```json
{
  "at": 1790841884993,
  "key": "reconcile_mismatch:sandbar",
  "rule": "reconcile_mismatch",
  "target": "sandbar",
  "level": "redline",
  "title": "对账不一致 99 票",
  "detail": "..."
}
```

Levels seen: `redline`.

### inspection period (entity) — "what did this period do, and was its outcome served, voided or re-run?"

```json
{
  "instance": "docs-sync",
  "period": "20261007",
  "ticket": "t261009-05",
  "state": "voided",
  "disposition": {
    "who": "integration",
    "reason": "blocked by a red line",
    "at": 1791520000000
  }
}
```

States: `blocked` / `completed` / `voided`.

## E. Ticket truth

The truth about a ticket — its stage, its signature, its verdict, a send-back — lives in the workflow engine's own history and is **not** duplicated here. Everything in this document that mentions a ticket is either a projection of that truth or a fact about something else that names a ticket.

## Open questions for this review

1. **Where do findings live?** The inspected ledger records *paths reviewed*, not findings; the finding entity and its observations have no settled home, and the entity/observation split depends on one.
2. **`by` / `who` must split.** Examples of the prose that cannot be machine-checked are in section D (`capacity limit change.by`, `authorisation change.who`). Proposed: `actor`, `on behalf of`, `authority reference` — all three required when the writer is not the authority.
3. **Shape versions.** The event ledger has one (`event-ledger-v1`); the rest do not. Roll the same convention out, and state what a reader does with an unknown version (fail loudly, not guess).
4. **Retention per family.** Only the event ledger has a rotation cursor; run results are 88 MB and rotate by rename alone. Each family needs a declared lifetime.
5. **What may never be recorded.** "References, not payloads" needs forbidden examples (credentials, tokens, private host paths, raw model input containing them) so a record can be refused rather than argued about.
6. **The case rows need `run` added** (and a repository, once a landing can span repositories). Until they carry it, no certification can point at a run, and the header record is not enough on its own — the rows are what a reader checks the counts against.
7. **What ends a ticket that has no content?** A report-only or verification-only ticket changes no files, so it has nothing to land and nothing to certify by landing. The `landed_at: null` row is representable; the rule for how such a ticket finishes is not written yet, and it is the one gap that this section exposed.
