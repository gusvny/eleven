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

**What this is.** The design documents state *why* a fact lives where it lives. This document states **what a record is, field by field**, so it can be reviewed before it is built and so two implementations cannot drift. Everything marked **today** exists on disk now (shapes below were read from the store, not remembered); everything marked **proposed** is designed and not yet built.

## Conventions that apply to every record

| Rule | Why | Status |
|---|---|---|
| A record carries the version of its own shape | A reader must be able to read older shapes instead of demanding a migration | **Half in place**: the event ledger already has `v:"event-ledger-v1"`; the others do not |
| Facts are appended; a correction is another fact | Rewriting a fact destroys the history that makes attribution auditable | Today, by convention; stated in the ledger design |
| An entity and an observation of it are two records | "How long has this been open" and "was it seen again" are different questions | Proposed as a rule; the fault ledger violates it today (one prose entry per fault mode) |
| Identity is minted, never derived, never reused | A reused id silently rewrites what every report that cited it meant | Today for inspection findings (minted from content); to be the rule everywhere |
| One direction is stored; the reverse is derived | Two rows for one fact drift apart | Proposed |
| Order comes from the ledger, not from a clock | Several machines do not agree on time | Proposed; today everything orders by timestamp |
| Records carry references, not payloads | A shared store must not accumulate credentials, tokens or private paths | Proposed; today some free-text fields carry whatever the writer wrote |
| Which machine produced a record is provenance, never authority | A pin or a machine must not grant a right | Proposed |

**Time is currently stored four different ways in one store** — and that is worth fixing before more records are added:

| Field seen | Example | Where |
|---|---|---|
| `at` as integer milliseconds | `"at":1791188111775` | executor actions, requests, alerts, grants audit |
| `ts` as float seconds | `"ts":1791157240.958244` | capacity limit audit |
| `at` as float seconds | `"at":1791338554.346339` | inspection reviewed-paths |
| `ts` as ISO string with offset | `"ts":"2026-09-22T15:33:10+08:00"` | run results |

## A. Delivery records (proposed — the buffer flow)

| Record | Kind | Fields | Written by | Read by |
|---|---|---|---|---|
| **landing** | fact | ticket, line, repositories `[{repo, revision}]`, move-together flag, base (the previously certified revision), at, actor | the engine, when a ticket lands | certification driver, faces |
| **certification** | fact | certification id, candidate id, repositories `[{repo, revision}]`, covered-from revision, tickets covered, what ran (suite / fast set, scenario set, wall time), environment fingerprint, environment reds, booked-red inventory version, verdict, driver, at, evidence reference | the certification driver | landability check, faces, patrol |
| **freeze episode** | entity | freeze id, line, opened at, opened by (certification id), culprit candidates, state (open / closed), closed at, closed by (remedy ticket), reopening reason | engine, on a red that implicates a landing | waiting tickets, patrol, faces |
| **batch** | fact | batch id, certification id, repositories `[{repo, revision}]`, tickets covered, main before, main after, signer, **signed on behalf of**, note, at | the person (or delegate) who signs | delivery provenance, faces |
| **revert** | fact | revert id, the landing withdrawn, on (line or delivered line), at, by, reason, propagated-to `[{line, state}]` | engine / person, per the withdrawal rules | lines that still carry it, provenance |
| **ticket outcome** | projection | ticket, landed at (revision set or none), certified by, delivered in (batch id) or reverted at, waiting since | derived | faces, the ticket's own record |

## B. Relation records (proposed)

| Record | Kind | Fields | Notes |
|---|---|---|---|
| **relation** | fact | relation id, subject A, subject B, kind (`repairs` \| `originates from a finding`), recorded by, reason, evidence, at, shape version | Subjects are tickets. Only one direction is stored |
| **relation correction** | fact | the relation it supersedes, the replacement, recorded by, reason, at | Corrections are appended, never edited in |
| **repository relation** | **declaration, not a ledger** | base repository, dependent repositories, the proof rule (touching the base means running the dependents) | The subjects are repositories, not tickets, and the fact changes rarely; it belongs with the project layout, and the ledger cites it when a landing spans repositories |

## C. Knowledge records

| Record | Kind | Fields | Status |
|---|---|---|---|
| **fault mode** | entity | id, title, pattern, trigger, what kind of change steps on it, blocking or not, state | **Today**: one prose entry per mode in a single file, edited in place |
| **fault-mode disposition** | fact | fault mode, from state, to state (open → booked red → fixed → obsolete), who, why, which fix, at | Proposed; today it is prose |
| **case ↔ fault mode link** | fact | case id, fault mode id, marked by, at | **Missing today**: it exists only as prose citations |
| **booked-red inventory** | state | per case: expected-red or not, the reason, who booked it | **Today**: a machine-read file in the repository |
| **finding** | entity | id minted from content, subject, severity, evidence `[{path, line, quote}]`, why, suggestion, confidence, state | **Today**: produced by the inspection agent, id minted mechanically, evidence verified mechanically; where the entity is *stored* is not settled (see open questions) |
| **finding observation** | fact | finding id, period, revision seen against, verification result (verified / downgraded / unlocatable), quote fingerprint | Proposed; today only the finding itself exists |
| **run result** | fact | ts, commit, environment fingerprint, concurrency width, pool, scenario, verdict, wall seconds, source, ticket | **Today**: one row per case per run. Note it already carries the revision and the environment fingerprint — certification should reuse this shape rather than invent another |
| **reviewed path** | fact | path, period, ts | **Today**: which paths an inspection period looked at |

## D. Fleet and operations records (today)

| Record | Kind | Fields | Notes |
|---|---|---|---|
| **event** | fact | `v`, project, scope, ticket, workflow, template, stage, state, reason | The only family that already versions its shape |
| **executor action** | fact | at, channel, decision, grant, grant source, idempotency key, op, session, ticket | Idempotency key present |
| **request** | fact | type, id, at, project, kind, question, detail | The free-text `detail` is exactly what the "references, not payloads" rule should constrain |
| **capacity limit change** | fact | ts, project, **by**, from, to | `by` is free text that mixes identity, delegation and the authorising order |
| **authorisation change** | fact | at, action, project, **who**, from, to, night tier | Same problem as `by` above |
| **capacity state** | state | version, holders `[{ticket, since, reason}]`, queue | Current state, read as a whole under a lock |
| **authorisation state** | state | executor sessions, grants, open-ticket cap, epics | Current state |
| **alert** | fact | at, key, rule, target, level, title, detail | |
| **inspection period** | entity | instance, period, ticket id, state (blocked / completed / voided), disposition (who, reason, at) | Voiding and re-running are recorded as facts |

## E. Ticket truth

The truth about a ticket — its stage, its signature, its verdict, a send-back — lives in the workflow engine's own history and is **not** duplicated here. Everything in this document that mentions a ticket is either a projection of that truth or a fact about something else that names a ticket.

## Open questions for this review

1. **One time convention.** Four exist today (see the table above). Which one, and is the conversion done at read time or on write?
2. **Where do findings live?** The inspected ledger records *paths reviewed*, not findings; the finding entity and its observations have no settled home, and the entity/observation split depends on one.
3. **`by` / `who` must split.** With delegation now allowed, a field that carries "host（经…代写；宿主令…）" as prose cannot be checked by a machine. Proposed: `actor`, `on behalf of`, `authority reference` — three fields, all required when the writer is not the authority.
4. **Shape versions.** The event ledger has one; the rest do not. Roll the same convention out, and state what a reader must do with an unknown version (fail loudly, not guess).
5. **Retention per family.** Only the event ledger has a rotation cursor; run results are 88 MB and rotate by rename alone. Each family needs a declared lifetime, or the store grows without a rule.
6. **What may never be recorded.** The rule "references, not payloads" needs examples of the forbidden kind (credentials, tokens, private host paths, raw model prompts containing them) so that reviewers can refuse a record rather than argue about it.
