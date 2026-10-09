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

**What this is.** The design documents state *why* a fact lives where it lives. This document states **what a record is, what question it answers, and how it is shaped**, so it can be reviewed before it is built and so two implementations cannot drift. Everything marked **today** exists on disk now (the shapes below were read from the store, not remembered); everything marked **proposed** is designed and not yet built.

## Conventions that apply to every record

| Rule | Why | Status |
|---|---|---|
| **Time is `at`: an integer count of milliseconds since the epoch** | One convention for every family; four existed when this was written | **Decided by the host (261009).** New records use it. Older records keep the form they were written in and are read as they are — the older forms are listed below, and nothing is rewritten |
| A record carries the version of its own shape | A reader must be able to read older shapes instead of demanding a migration | **Half in place**: the event ledger already has `v:"event-ledger-v1"`; the others do not |
| Facts are appended; a correction is another fact | Rewriting a fact destroys the history that makes attribution auditable | Today, by convention; stated in the ledger design |
| An entity and an observation of it are two records | "How long has this been open" and "was it seen again" are different questions | Proposed as a rule; the fault ledger violates it today (one prose entry per fault mode) |
| Identity is minted, never derived, never reused | A reused id silently rewrites what every report that cited it meant | Today for inspection findings (minted from content); to be the rule everywhere |
| One direction is stored; the reverse is derived | Two rows for one fact drift apart | Proposed |
| Order comes from the ledger, not from a clock | Several machines do not agree on time | Proposed; today everything orders by timestamp |
| Records carry references, not payloads | A shared store must not accumulate credentials, tokens or private paths | Proposed; today some free-text fields carry whatever the writer wrote |
| Which machine produced a record is provenance, never authority | A pin or a machine must not grant a right | Proposed |

**The time shapes found on disk (kept for reading, not for writing):** `at` as integer milliseconds (executor actions, requests, alerts, grants audit); `ts` as float seconds (capacity limit audit); `at` as float seconds (inspection reviewed-paths); `ts` as an ISO string with offset (run results).

## A. Delivery records (proposed — the buffer flow)

| Record | What it is for — the question it answers | Kind | Fields | Written by | Read by |
|---|---|---|---|---|---|
| **landing** | "What content did this ticket put on this line, and on top of what?" It is the anchor every other delivery record points at: a certification says which range it covered, and a ticket's outcome says which landing carried it | fact | ticket, line, repositories `[{repo, revision}]`, move-together flag, base (the previously certified revision), at, actor | the engine, when a ticket lands | certification driver, faces |
| **certification** | "May this content be delivered, and what was actually proved?" It is the only thing that grants landability, and the only record that makes two revisions comparable — so it is also what tells a red apart from a known one | fact | certification id, candidate id, repositories `[{repo, revision}]`, covered-from revision, tickets covered, what ran (suite / fast set, scenario set, wall time), environment fingerprint, environment reds, booked-red inventory version, verdict, driver, at, evidence reference | the certification driver | landability check, faces, patrol |
| **freeze episode** | "Why is nothing landing on this line, and who is fixing it?" Its purpose is to make a stop **visible and bounded**: an open episode names the culprit set and the remedy ticket, so a freeze cannot quietly become the permanent state | entity | freeze id, line, opened at, opened by (certification id), culprit candidates, state (open / closed), closed at, closed by (remedy ticket), reopening reason | engine, on a red that implicates a landing | waiting tickets, patrol, faces |
| **batch** | "What did a person approve, and what did the delivered line become?" It is the only place a human signature attaches, and the only place a ticket's delivery can be confirmed | fact | batch id, certification id, repositories `[{repo, revision}]`, tickets covered, main before, main after, signer, **signed on behalf of**, note, at | the person (or delegate) who signs | delivery provenance, faces |
| **revert** | "This content was withdrawn — where does it still live?" Its purpose is the **propagation obligation**: every line that still carries the withdrawn landing is named, because a branch merge keeps it silently and the next batch would reintroduce it | fact | revert id, the landing withdrawn, on (line or delivered line), at, by, reason, propagated-to `[{line, state}]` | engine / person, per the withdrawal rules | lines that still carry it, provenance |
| **ticket outcome** | "Where did this ticket end up?" — the three stages (landed, certified, delivered) in one projection, so a closed ticket is never mistaken for a delivered one, and a waiting ticket is distinguishable from a stuck one | projection | ticket, landed at (revision set or none), certified by, delivered in (batch id) or reverted at, waiting since | derived | faces, the ticket's own record |

## B. Relation records (proposed)

| Record | What it is for — the question it answers | Kind | Fields |
|---|---|---|---|
| **relation** | "Why does this work exist?" and "who owns this boundary?" Its purpose is that the answer outlives the conversation in which it was decided | fact | relation id, subject A, subject B, kind (`repairs` \| `originates from a finding`), recorded by, reason, evidence, at, shape version |
| **relation correction** | "That attribution was wrong." Its purpose is that a wrong attribution can be superseded without erasing the fact that it was made | fact | the relation it supersedes, the replacement, recorded by, reason, at |
| **repository relation** | "What else must be proved when this repository changes?" Its purpose is that a landing spanning repositories has a **defined** proof set rather than an improvised one | **declaration, not a ledger** — the subjects are repositories, not tickets, and it changes rarely | base repository, dependent repositories, the proof rule |

## C. Knowledge records

| Record | What it is for — the question it answers | Kind | Fields | Status |
|---|---|---|---|---|
| **fault mode** | "Have we seen this before?" The catalogue entry: the pattern, what triggers it, what kind of change steps on it | entity | id, title, pattern, trigger, what kind of change steps on it, blocking or not, state | **Today**: one prose entry per mode in a single file, edited in place |
| **fault-mode disposition** | "Do we accept this, or must it be fixed?" The decision about a fault mode, recorded as a fact so that "we decided to live with it" is distinguishable from "we just hit it again" | fact | fault mode, from state, to state (open → booked red → fixed → obsolete), who, why, which fix, at | Proposed; today it is prose |
| **case ↔ fault mode link** | "Is this fault mode actually locked by a case?" The join whose absence turns the ledger into a search | fact | case id, fault mode id, marked by, at | **Missing today**: it exists only as prose citations |
| **booked-red inventory** | "Is this red new?" The expected-red list the gate compares against | state | per case: expected-red or not, the reason, who booked it | **Today**: a machine-read file in the repository |
| **finding** | "What is wrong here?" — with evidence a machine can check, so that a finding is a fact rather than an opinion | entity | id minted from content, subject, severity, evidence `[{path, line, quote}]`, why, suggestion, confidence, state | **Today**: produced by the inspection agent, id minted mechanically, evidence verified mechanically; where the entity is *stored* is not settled (see open questions) |
| **finding observation** | "Is it still there, and for how long has it been?" — the sighting, against a named revision | fact | finding id, period, revision seen against, verification result (verified / downgraded / unlocatable), quote fingerprint, at | Proposed; today only the finding itself exists |
| **run result** | "How did this case behave on this revision, in this environment?" The evidence behind every green and red | fact | at, commit, environment fingerprint, concurrency width, pool, scenario, verdict, wall seconds, source, ticket | **Today**: one row per case per run. It already carries the revision and the environment fingerprint — certification should reuse this shape rather than invent another |
| **reviewed path** | "Has anyone looked at this file lately?" What an inspection period actually examined | fact | path, period, at | **Today** |

## D. Fleet and operations records (today)

| Record | What it is for — the question it answers | Kind | Fields |
|---|---|---|---|
| **event** | "What did the engine or the watchdog see?" The running account behind the faces and behind diagnosis | fact | `v`, project, scope, ticket, workflow, template, stage, state, reason, at |
| **executor action** | "What did the executor do, and on whose authority?" | fact | at, channel, decision, grant, grant source, idempotency key, op, session, ticket |
| **request** | "What was asked of the host, and what was answered?" The executor's channel to the person | fact | type, id, at, project, kind, question, detail |
| **capacity limit change** | "Who changed how many tickets may run at once, and why?" The audit behind a current value | fact | at, project, by, from, to |
| **authorisation change** | "Who was given what, and by whose order?" | fact | at, action, project, who, from, to, night tier |
| **capacity state** | "Who holds a slot right now, and who is waiting?" — read as a whole, under a lock | state | version, holders `[{ticket, since, reason}]`, queue |
| **authorisation state** | "What may the executor session do right now?" | state | executor sessions, grants, open-ticket cap, epics |
| **alert** | "What did the watchdog shout about, and at what level?" | fact | at, key, rule, target, level, title, detail |
| **inspection period** | "What did this period do, and was its outcome served, voided or re-run?" | entity | instance, period, ticket id, state (blocked / completed / voided), disposition (who, reason, at) |

## E. Ticket truth

The truth about a ticket — its stage, its signature, its verdict, a send-back — lives in the workflow engine's own history and is **not** duplicated here. Everything in this document that mentions a ticket is either a projection of that truth or a fact about something else that names a ticket.

## Open questions for this review

1. **Where do findings live?** The inspected ledger records *paths reviewed*, not findings; the finding entity and its observations have no settled home, and the entity/observation split depends on one.
2. **`by` / `who` must split.** With delegation allowed, a field carrying "host（经…代写；宿主令…）" as prose cannot be checked by a machine. Proposed: `actor`, `on behalf of`, `authority reference` — all three required when the writer is not the authority.
3. **Shape versions.** The event ledger has one; the rest do not. Roll the same convention out, and state what a reader must do with an unknown version (fail loudly, not guess).
4. **Retention per family.** Only the event ledger has a rotation cursor; run results are 88 MB and rotate by rename alone. Each family needs a declared lifetime, or the store grows without a rule.
5. **What may never be recorded.** The rule "references, not payloads" needs forbidden examples (credentials, tokens, private host paths, raw model input containing them) so that a record can be refused rather than argued about.
