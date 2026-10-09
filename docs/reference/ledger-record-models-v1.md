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
| A machine is provenance, never authority | `"machine": "mac-mini-2"` decides nothing | Proposed |
| **A landing is one act over every repository it names: all or nothing** | see the multi-repository example under *landing* | Proposed — see below for why a partial landing is not an option |

**The older time shapes (kept for reading, not for writing):** `at` as integer milliseconds (executor actions, requests, alerts, grants audit); `ts` as float seconds (capacity limit audit); `at` as float seconds (inspection reviewed-paths); `ts` as an ISO string with offset (run results).

## A. Delivery records (proposed — the buffer flow)

**One rule covers every field that names a state.** In a multi-repository project a "revision" is really a set of per-repository revisions, so `repos`, `base`, `covered_from`, `main_before` and `main_after` are all **sets**, one entry per repository, and in the single-repository case each has exactly one member. Anything that names a state and is not a set would have to be rewritten the day a second repository appears. The same applies to `main`: in a multi-repository project "main" is per repository, so a batch advances several of them and records all of them.

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
  "base": "4d2e0f9a",
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
  "base": [
    { "repo": "sandbar", "revision": "9f3c2a1b" },
    { "repo": "dsh", "revision": "0a77e1c3" }
  ],
  "at": 1791510000000,
  "actor": "engine"
}
```

`base` is a **set keyed to the repositories the landing names** — one entry per repository, in the same order as `repos`, so a reader compares entry by entry. It is not a new source of truth: it is the previous certification's `repos` set, snapshotted at the moment of landing. And it is a **checkable claim**: per repository, `base` must be an ancestor of the landing's revision. That single check is what catches a landing that skipped over certified content, or a lane whose base is behind (or, worse, that would revert content the line already certified) — and it reports **per repository**, because in a multi-repository project those failures are per repository too.

Three cases to define, or the field will be read wrongly:

- **A repository the line has never certified.** Its `base` entry is the revision the line was created from in that repository (recorded when the line was declared), so the field is never absent and the check still applies. The uncovered range for that repository then starts at the line's creation, which may be a lot — that is a fact worth seeing rather than hiding.
- **Repositories the landing does not name do not appear in `base`,** and their certified revisions are read from the certification record instead. `base` must not be read as "the whole state of the line"; it is the state of the repositories this landing touched.
- **A lane behind the certified state** fails the ancestry check in exactly the repository where it is behind — which is the signal to merge the certified state in before landing, not to land on a stale base.

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `ldg-261009-0007` | Minted, never reused: the anchor every other delivery record points at |
| `ticket` | `t261008-45` | Whose content this is |
| `line` | `default` / `ui` / `epic-console-ui` | Which line it landed on — freezes and certification are per line |
| `repos[].repo` | `sandbar`, `dsh` | A landing may span repositories; one entry in the single-repository case |
| `repos[].revision` | `9f3c2a1b` | The commit that went onto that repository's line |
| `base` | `[{"repo":"sandbar","revision":"4d2e0f9a"}]` | The previously certified **state**, as a set keyed to `repos`: **the anchor that makes the uncertified range computable** instead of remembered, and a checkable claim (per repository, it must be an ancestor of the revision that landed) |
| `at` | `1791507005123` | Milliseconds since the epoch |
| `actor` | `engine` / `integration` / `host` | Who performed the landing — provenance, not authority |

**All or nothing, and there is no flag for it.** A ticket lands as a whole or it has not landed, and this is not a preference: the line's history stays linear with one landing per ticket so that "before" and "after" are well defined. If a landing could put one repository's revision in place and not another's, then three things stop being answerable at once — what range a certification covers, which content a batch delivered, and what a ticket's `landed_at` points at. Mechanically a multi-repository landing can still *fail halfway* (one repository merges, the other conflicts); that is a state to repair, not a landing to record: **a landing that did not complete on every repository it names has not landed**, the line is brought back to a consistent state, and the record says the attempt failed.

Two questions that look like this one and are not:

- **"Whose coupling is it?"** When a change in one repository is only correct together with a change in another, that is a **proof** question, not a landing question: the repository relation declaration in section B says which dependents must be proved when the base changes.
- **"Could this work have been split?"** If a ticket's changes are genuinely independent of each other, the answer is **two tickets**, not a landing in two pieces — attribution is sharper and the blast radius smaller.

### certification — "may this content be delivered, and what was actually proved?"

```json
{
  "id": "cert-261009-14",
  "candidate": "cand-261009-14",
  "line": "default",
  "repos": [
    { "repo": "sandbar", "revision": "9f3c2a1b" }
  ],
  "covered_from": [
    { "repo": "sandbar", "revision": "4d2e0f9a" }
  ],
  "tickets": ["t261008-45", "t261008-46"],
  "ran": {
    "suite": "full",
    "scenarios": 445,
    "wall_s": 2132
  },
  "env_fp": "0febeeb6da6b25dc...",
  "env_reds": ["t260916-25"],
  "booked_red": "known-red-baseline@2026-10-04",
  "verdict": "green",
  "driver": "integration/run_scenarios.py",
  "at": 1791508600000,
  "evidence": "ledger/scenario-results.jsonl#run-261009-14"
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `cert-261009-14` | This run, cited by batches and freezes |
| `candidate` | `cand-261009-14` | **What is proved is the set of revisions that would be delivered together**, not a branch: the line's head today, a merge of heads once there are several lines |
| `line` | `default` | Which line's candidate this is |
| `repos[].revision` | `9f3c2a1b` | The exact content under proof |
| `covered_from` | `[{"repo":"sandbar","revision":"4d2e0f9a"}]` | The revision this certification continues from — **what makes the certified prefix reconstructible**, and therefore what makes "the greatest certified revision is always landable" true |
| `tickets` | `["t261008-45", "t261008-46"]` | Which tickets' landings are inside the covered range: what lets a batch say whom it delivers |
| `ran.suite` | `full` / `fast-set` | Which proof was run |
| `ran.scenarios` | `445` | How much was run — evidence for arguing the fast set's membership |
| `ran.wall_s` | `2132` | What the proof cost |
| `env_fp` | `0febeeb6da6b25dc...` | Environment fingerprint: two runs in different environments are not comparable |
| `env_reds` | `["t260916-25"]` | Failures that were environmental — **never counted as content reds** ("could not run" is not "red") |
| `booked_red` | `known-red-baseline@2026-10-04` | Which expected-red list this judgement used: what tells a new red from a known one |
| `verdict` | `green` / `red` | The outcome |
| `driver` | `integration/run_scenarios.py` | What produced it |
| `at` | `1791508600000` | Milliseconds since the epoch |
| `evidence` | `ledger/scenario-results.jsonl#run-261009-14` | A reference to the raw rows, not the rows themselves |

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

### run result (fact) — "how did this case behave on this revision, in this environment?"

```json
{
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

**Today**, verbatim. It already carries the revision and the environment fingerprint — certification should reuse this shape rather than invent another.

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
6. **What ends a ticket that has no content?** A report-only or verification-only ticket changes no files, so it has nothing to land and nothing to certify by landing. The `landed_at: null` row is representable; the rule for how such a ticket finishes is not written yet, and it is the one gap that this section exposed.
