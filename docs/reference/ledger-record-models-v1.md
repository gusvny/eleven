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
    note: the delivery records (landing, certification with its run, promotion, freeze episode) — and why a withdrawal is work rather than a record
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
| **promotion** | the act of moving a certified range of content to `main`, approved by a person (or a delegate) | **not** `batch` — in this project a batch already means a run of the test bench, and the word names the grouping rather than the two things that matter (a person approved it, `main` moved); **not** `delivery` — the engine already has an executor delivery workflow, and one word for two things is how `line` got into trouble; **not** `release`, which would claim versioning this design does not have; **not** `advance`, a retired operation name |

## Identity: what an id has to do, and how to get time into it without collisions

**The question** — "can an id carry the time and still never repeat" — has a clean answer, but only once the id's job is split in two, because this ledger holds two kinds of thing:

| The id is for | How it is minted | Where it is used |
|---|---|---|
| **Recognising the same thing across time** — a fault mode, a finding | **from the content** (a hash of what it is about), so a re-sighting computes the *same* id and deduplication is possible at all | fault modes (`KI-228`), findings (`3d4b305e`) |
| **Naming a moment** — a landing, a certification, a run, a promotion, a sighting | **time prefix + randomness**, e.g. the ULID shape `01J9Z6QK3M7X2P4T8V0N5R` (48-bit millisecond timestamp, then random), optionally after a short family prefix: `ldg-01J9Z6QK3M…` | the delivery, run and relation families |

**Not every record gets an id, and that is the first thing to fix about this model.** The ids above were invented one record at a time and it shows: seven families with a time-ish id, one content id, one human-sequential number, one composite key — and several records with no id at all. The rule that replaces the ad-hoc set:

> **A record gets an id when something else must cite it. A record whose only access is a query keeps its tuple as the key. Minting an id nobody cites is the same fault as a field nobody reads.**

Applied to every record in this document:

| Record | Role | Id |
|---|---|---|
| ticket | cited everywhere, human-facing | `t261009-10` — the project's existing shape, kept; it is minted by one authority (see the collision below) |
| landing / certification / run / promotion / freeze episode / relation | **cited by other records** | **family prefix + time id, one shape for all of them**: `ldg-01J9Z6QK3M…`, `cert-01J9Z6R2…`, `run-…`, `prom-…`, `frz-…`, `rel-…` |
| finding | cited, and its identity **is** its content | **content id**, widened to 16 hex: `3d4b305e1f7a9c02` |
| fault mode | **cited verbatim in prose, in many places** | **a ULID** — `01J9Z6QK3M7X2P4T8V0N5R` (the host's decision, 261009: coordination-free ids win over short ones). Existing entries keep the numbers they already have; nothing is renumbered (see the note below) |
| inspection period | cited | `insp-<instance>-<period>` — composite, because a period *is* an instance plus a period |
| observation | **never cited; read by query** | **no id** — the key is `(finding, period)` |
| state change (a freeze closing, a period being voided) | never cited | **no id** — the key is `(parent, change)` |
| reviewed path | never cited | **no id** — the key is `(path, period)` |
| run case row | never cited | **no id** — the key is `(run, scenario)` |
| booked-red row | never cited | **no id** — the key is `(case)` |
| repository relation | not a record at all | keyed by the base repository's name |

Two consequences worth stating plainly. **The two minting rules stay two**, and that is not inconsistency: a thing whose identity is its content must be recognisable when it is seen again, and a thing that happened once needs a time; forcing one rule on both would break one of them. **The fault-mode number is the one id whose shape needs an argument, and the argument is citation, not typing.** These numbers are written by hand into committed prose: design documents, code comments, the ledger's own entries, scenario descriptions, reports, and messages between people and agents. So the requirement is that a reference stays **short enough to write and read verbatim in a sentence, and stable enough that changing it later would mean editing files all over the repository**. Nothing about this record needs a time (its dispositions carry those) or a content identity (two registrations of the same pattern are worded differently, so a content id would fail to deduplicate exactly where deduplication matters most — the judgement that this is the same known fault and not a new one). A short sequential number assigned by the registrar is the cheap form that survives being cited in prose.

**The host's decision (261009): the fault ledger uses ULIDs.** The earlier reasoning in this document recommended keeping a short sequential number; the host took the other side, and the deciding argument is the one above — **a sequence is a coordination problem the moment two people can register, and a fault ledger that lives in a repository can be merged by two people at once**. A ULID removes that class of failure entirely rather than managing it, and the price is known and accepted:

- **What is lost is narrower than it first looks.** A ULID **keeps the order and the time** — the first 48 bits are a millisecond timestamp, so lexicographic order *is* time order and the moment can be decoded exactly, which is strictly more than a sequence number ever gave ("roughly when" by position). What it loses is the **count** (how many entries exist is now a query, not something readable off the highest number) and **being sayable in conversation**. Those two are the price, and the second one is simply paid.
- **The price is measured**: fault-mode numbers are cited **4,058 times across 790 tracked files**. Those citations are of the *existing* numbers and keep working, because:
- **Nothing is renumbered.** The ledger holds two shapes from here on: entries registered before this decision keep their `KI-<n>` id (it is their identity, and it stays cited), and entries registered after it carry a ULID. Rewriting 4,058 citations across 790 files would be a history rewrite with no benefit that a reader can see, and the rule from the delivery side applies here too — **old records are not rewritten**.
- **A duplicate id is still refused loudly**, on append and after any merge. A ULID makes that check almost never fire; "almost never" is exactly why the check stays.

**When more than one writer mints, a sequence needs one of three things — and the failure is worse than a race.** Two writers reading the same maximum and appending the same number is the obvious one. The one that actually bites here is quieter: **the fault ledger is a file in a repository**, so two people can each append an entry in their own clone, push, and the merge leaves **two entries with the same number in one file** — with every citation of that number now ambiguous, and nothing raising a hand. So the choice is not "sequence or no sequence", it is which of these three to pay for:

1. **One authority mints them all** and everyone else proposes. Cheapest, keeps the id short, and it is where the store design already points (a single writing authority). The cost is that registration becomes a request rather than a local act — acceptable for a ledger that grows by a few entries a day.
2. **The authority hands out blocks.** A writer leases a range (say 227–276) and increments inside it without asking again. Coordination drops to once per block, and — the useful part — it is **merge-safe**: two clones' appends can be merged because their numbers cannot overlap. What is lost is that the number stops being a count: it becomes an upper bound, and "how many are there" is a query.
3. **Each writer has its own scope inside the id** (`KI-A-12`, `KI-B-7`): no coordination at all, still short and still sayable out loud, at the cost of the global sequence — nothing can read how many exist off the highest number.

**Where a ULID is the wrong choice — three classes, and none of them is about uniqueness.**

1. **Identity that has to be *derived from the content*.** A finding's id is recomputed from what it is about, because that is the only way the *same* problem, seen again in a later period, is recognised as the same one — which is what deduplication and "how long has this been open" rest on. A ULID is minted once at first sighting and cannot be recomputed at the second, so the two sightings would simply be two different things. **Findings cannot use ULIDs**, and neither can anything else whose identity is its content. (The sighting itself could carry a ULID, but it needs no id at all.)
2. **Natural keys, where the key *is* the meaning.** An inspection period is one instance in one period; a scenario is a ticket plus a slug; a project, a repository and a lane have names. Replacing those with a ULID would throw away the only thing they are for and force a lookup for what a reader already knows. The rules that dedupe by nature ("one ticket per instance and period") also depend on the natural key being the key.
3. **Any id that ends up inside a path, a branch name or a typed command.** The ticket id is the clearest case: it is a directory (`.lane/t261009-10`), a branch (`lane/t261009-10`), part of scenario names, and it is typed into commands many times a day. **This class has a length-and-legibility budget, not a uniqueness problem** — and because these ids are baked into directory names and branches, they can never be renumbered later. The same applies to a scenario name and an instance slug.

**"But the ticket id could be a ULID too?" — technically yes, and it is still the wrong trade, for three reasons that the fault-mode number does not have.**

- **The ticket id is load-bearing outside the ledger.** It is a directory (`.lane/t261009-10`), a branch (`lane/t261009-10`), part of scenario names, an argument typed into commands many times a day, and a string in every report and message. Twenty-six characters in all of those places is paid constantly, whereas the fault-mode number is paid only where it is cited.
- **Its date prefix is functional, not decorative.** `t261009-10` answers "which day, and how many that day" without a tool, and the faces group and sort by it. A ULID sorts by time too, but only a machine can read *when*.
- **Its minting is centralised, so the ULID buys nothing here.** The fault-mode problem was "two people can register, and a repository can be merged"; ticket creation goes through one authority per project. So the coordination ULID removes does not exist in this id space — and the collision this project actually suffered was **not** a coordination failure but a minting bug: the next number came from a partial view (the tickets that were alive). The fix belongs in the minter, not in the shape of the id.

**And if tickets ever are minted on several machines, the shape still should not change.** The authority can hand out **blocks** — machine A takes `t261009-10…59`, machine B takes `60…` — which is coordination-safe and invisible to every reader, because the shape they depend on is unchanged. **Choosing an id's shape to solve a coordination problem is the wrong lever when that shape is baked into paths and branches**; solve the coordination in the minter, where it can be solved without touching 400 tickets' worth of names.

**And the largest class of all: records that need no id.** A sighting, a state change, a reviewed path, a run case row, an expected-red row — each is read by a query and cited by nobody, so its tuple is its key. Adding a ULID there would be an id with no citer, which is the same fault as a field with no reader.

**"So a ULID will not collide?" — almost certainly not, which is not the same thing, and the difference decides how it is used.** A ULID's tail is **80 random bits**: two ids minted in the same millisecond collide with probability on the order of one in 2⁸⁰ per pair, so the birthday threshold — the point where a collision has even odds — is around **10¹² ids inside a single millisecond**. Nothing in this project will approach that, and it is worth saying in those terms rather than as a guarantee: **randomness does not remove collisions, it makes them astronomically unlikely**, which is a different kind of assurance from "the counter cannot repeat".

Three things follow, and they matter more than the probability:

- **Monotonic mode turns it from probability into construction, within one writer.** With the tail incremented instead of re-randomised when the millisecond repeats, two ids from one process cannot be equal on a same-millisecond tie. Across processes it goes back to being probabilistic, because each process seeds its own tail from randomness.
- **Uniqueness and ordering are carried by different parts.** The randomness carries uniqueness; the timestamp carries ordering. A wrong clock costs ordering and does **not** cost uniqueness.
- **What a random id cannot do is tell you anything.** No count, no "roughly when", and it cannot be read aloud — the costs already measured above at 4,058 citations.

**Whichever is chosen, one check is mandatory**: the ledger must **refuse a duplicate id loudly**, on append and after any merge. A collision is silent by construction, so the check is the cheapest insurance in this document — and it is what would have caught the ticket number being issued twice.

**And that incident is worth restating, because it was not caused by concurrency**: the ticket number repeated because the next number was derived from a **partial view** (the tickets that happened to be alive). The rule that follows is independent of how many writers there are: **the minter must see the whole id space, retired entries included**. Then the sequence needs coordination it cannot have, and a time id earns its length. Today it is one registrar, a few hundred entries, and references written by hand.

What that choice owes in return: **one registrar**, minting **one more than the highest number in the whole ledger**, and **never reusing a number** — an entry is retired by a disposition, never deleted, so its number stays spent. That last part is not decoration: the reused ticket number is exactly the incident this rule exists to prevent, and it happened because the next number was derived from a partial view (what was alive) instead of the whole id space.

**For the second kind, yes: a time-prefixed id works, and randomness is the part that makes it never repeat.** The prefix gives the time (readable to the millisecond, and sortable) and the random tail removes every need for coordination — no central counter, no "what has already been issued" question, no collision between two machines that mint at the same instant. UUIDv7 is the same idea standardised; ULID is the same idea in a shorter, sortable text form.

**The trap this must not fall into is the one this project already fell into.** A date plus a per-day counter looks friendlier and reads better (`t261009-10`), and it *is* fine — **provided a single authority mints it while seeing the whole id space of that day**. Ours did not: the next ticket number was derived from the tickets that happened to be *alive*, and a cancelled ticket stops being counted, so a number was handed out twice. **Time in an id is never the mechanism for uniqueness; uniqueness comes from randomness (second kind) or from content (first kind), and a counter works only when its issuer sees everything it counts.**

**A related defect worth fixing while we are here: the content-minted ids are too short.** A finding id is eight hex characters — 32 bits. Collisions are unlikely at today's counts and inevitable at scale: at roughly 65,000 findings a 32-bit space has even odds of a collision, and a collision here does not look like an error, it silently merges two different findings into one id. Sixteen hex characters cost six characters and remove the question.

**So can a good id replace `seq`? Yes — if it is a *monotonic* time id, and if three conditions hold.** The ordering and the read cursor were the only two jobs `seq` had, and a time-prefixed id does both: it sorts, and "everything after `<id>`" is a cursor. Two conditions are what turn that from a hope into a property:

1. **Monotonic within the issuer, not merely time-prefixed.** Two records written in the same millisecond must not order arbitrarily, so the id's tail increments rather than being purely random when the millisecond repeats — the monotonic ULID/ULID-with-counter shape. This is the "order comes from the ledger, not from a clock" requirement, kept as a requirement, with the mechanism moved into the id.
2. **Clock-skew protection at the issuer.** The minting reads a wall clock, so a backwards correction must not mint an id below the last one; the issuer keeps a floor of the last timestamp it issued. And in the later shape where several writers exist, monotonicity across writers is a property of the **single writing authority** — exactly the authority `seq` would have needed anyway, which is why this change costs nothing structurally.
3. **No content-minted ids in an ordered stream.** A finding's id is derived from its content and carries no time at all, by design, so it can never be ordered. That is not a problem — nothing needs to order entities; "the oldest open finding" is a question about its *observations*, which do carry time ids.

**What is kept either way is the requirement, not the field.** If the ids are monotonic and sortable, `seq` is redundant and disappears from the records; the derivations that use it are restated as id comparisons ("landings whose id is below this certification's id"), which are just as mechanical. If any of the three conditions cannot be guaranteed, `seq` stays and remains the authority — an explicit counter is easier to reason about than an id whose ordering depends on the minting code behaving.

**"But the store is append-only, so the order is already there" — half true, and the other half is why a key exists.** Append-only gives the *reading* order for free: within a file, records come back in the order they were written. What it does not give is a key that a record can *carry*:

- **A record has to cite a position.** "The landings before this certification" is a comparison between two records — the certification's key against each landing's key. A position in a file cannot be written into another record, because it stops being true the moment anything is rotated or compacted.
- **Rotation moves records.** The store already rotates by renaming, so one logical stream becomes several files; positions are not comparable across them, and a cursor has to be something stable that a reader can hand back ("after this id" or "after this number").
- **The counter is nearly free precisely because the store is append-only.** Appends are already serialised through one writer, so assigning the next number there costs one increment and no cleverness — which is an argument for **keeping** `seq` rather than dropping it.
- **And append-only removes lost updates, not collisions.** A duplicated id does not lose a record; it makes two records indistinguishable — which is worse in a ledger whose only purpose is to be cited.

**And the time in an id is a convenience, not the record's time.** Every record already carries `at` (milliseconds) and the ledger carries `seq`; the prefix is for humans who read ids all day and for sorting, and nobody should read it as "the moment this happened" more precisely than the record's own fields.

## Conventions that apply to every record

| Rule | Example | Status |
|---|---|---|
| **Time is `at`: an integer count of milliseconds since the epoch** | `"at": 1791507005123` | **Decided by the host (261009).** New records use it; older records keep the form they were written in and are read as they are |
| A record carries the version of its own shape | `"v": "event-ledger-v1"` | **Half in place**: only the event ledger has it |
| Facts are appended; a correction is another fact | a correction record names `"supersedes": "rel-261009-0004"` | Today by convention; stated in the ledger design |
| An entity and an observation of it are two records | entity `finding fi-9c1e`, observation `{"finding": "fi-9c1e", "period": "20261007"}` | Proposed; the fault ledger violates it today |
| Identity is minted, never derived, never reused — see the identity section below | `"id": "cert-261009-14"` | Today for inspection findings; to be the rule everywhere |
| One direction is stored; the reverse is derived | store `repair: t261009-04 → t261008-45`; read the reverse from it | Proposed |
| Order comes from the ledger, not from a clock | `"seq": 41077` | Proposed; today everything orders by timestamp |
| Records carry references, not payloads | `"evidence": "ledger/scenario-results.jsonl#run-261009-14"`, never the raw log or a token | Proposed |
| **Record what cannot be derived; derive what can** | the state a landing sat on and the range a certification continued from are **not** stored — both are derived from the certification ledger's order | Proposed; `base` and `covered_from` were dropped for this reason (261009) |
| **`seq` is the store's own order, not a table counter** | `"seq": 41077` — assigned when the record is written, by the one writer the store has, monotonic across record types, never reused, and **gaps are allowed and mean nothing** (a number, not a count). Never read from a clock | Proposed. Two things it buys: "the landings after the previous certification" becomes computable, and "read as of seq N" becomes the version cursor the ledger design asks for. Its total order is for **reading and range computation, not causality**: two lines' landings are concurrent whatever their numbers say, and that is what relations are for |
| **The delivery records share one ordering space** | | the landings and the certifications are ordered by one `seq`, so "the landings after the previous certification" is computable | Proposed, and load-bearing: the freeze's culprit range (filtered to that line), the certified prefix and the uncertified range are all derived from it. Separate counters per record type — an auto-increment per file or per table — would bring back every field that was just dropped |
| **A record's own `at` is when that fact happened** | the freeze's opening record carries `at`; there is no `opened_at`, and no `closed_at` — the closing is a record of its own with its own `at` | Proposed; `opened_at` / `closed_at` were dropped for this reason (261009) |
| **An entity carries only what was true when it came into being; everything after is another record keyed to it** | a freeze opens with its cause and its candidate set; an attribution change, a closure and a reopening are three further records | Proposed; the freeze episode and the inspection period were written as entities with mutable fields and are corrected below |
| **A projection is not a record** | the ticket's outcome is a view over landings, certifications, promotions and reverts — it has no `id`, `seq` or `at` of its own | Proposed. If kept, it is a derived view carrying the cursor it was computed up to, droppable and rebuildable; the rebuild-and-compare is the drift check, and no fact may cite it |
| **A summary lives with the data it summarises** | a run's counts, environment, width and duration are fields of the **run** record; a certification cites the run instead of restating it | The test for a summary: would a reader be forced to open the raw body to make a decision they make daily? and can it be checked against the body? If yes it is kept — **at the level of the data, not one level up**. Anything that fails both tests is duplication (`base`, dropped) |
| A machine is provenance, never authority | `"machine": "mac-mini-2"` decides nothing | Proposed |
| **A landing is one act over every repository it names: all or nothing** | see the multi-repository example under *landing* | Proposed — see below for why a partial landing is not an option |

**The older time shapes (kept for reading, not for writing):** `wall_s` as a duration in seconds (run results, and the certification examples before the rename above); `at` as integer milliseconds (executor actions, requests, alerts, grants audit); `ts` as float seconds (capacity limit audit); `at` as float seconds (inspection reviewed-paths); `ts` as an ISO string with offset (run results).

## A. Delivery records (proposed — the buffer flow)

**Status of this section:** the records are proposed, except the run's case rows, which exist today. Each entry says which.

**One rule covers every field that names a state.** In a multi-repository project a "revision" is really a set of per-repository revisions, so `repos`, `base`, `covered_from`, `main_before` and `main_after` are all **sets**, one entry per repository, and in the single-repository case each has exactly one member. Anything that names a state and is not a set would have to be rewritten the day a second repository appears. The same applies to `main`: in a multi-repository project "main" is per repository, so a promotion advances several of them and records all of them. Where such a state is derived rather than recorded, it is derived **per repository** too.

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
| `id` | `cert-261009-15` | The judgement, cited by promotions and freezes |
| `line` | `default` | Which line this judgement is about |
| `repos[].revision` | `9f3c2a1b` | The exact content the judgement covers |
| `run` | `run-261009-14` | **Which run answered it.** A certification does not restate what a run measured — see below |
| `repos` (above) | — | **The candidate is this set, and nothing else.** It needs no separate record or id: the set of repository revisions *is* the identity, and identifying it by its own content means it cannot drift from what was judged. The rerun-once rule then reads correctly as "a second run on the same set", which is why a run and a certification are separate records |
| `booked_red` | `known-red-baseline@2026-10-04` | Which expected-red list was in force when this was judged. It appears in no run, and without it a later reader cannot tell a new red from a known one |
| `judged_by` | `integration/run_scenarios.py` | What performed the judgement |
| `seq` | `41076` | Order, for the same reason as on a landing: the certified prefix is the certifications on this line, in order — **derived, not restated** |
| `at` | `1791508600000` | Milliseconds since the epoch |

**A run says what happened; a certification says what was judged — and a run has its own record.** Everything measural belongs to the run: what ran, how many cases, how many failed, in which environment, at which width, for how long, and the verdict that follows mechanically from those rows. The certification binds that run to a **candidate** and to the **expected-red list in force**, which is the part no run can know. Two consequences worth stating:

- **No verdict on the certification.** A certification whose run came back red is still a certification — that is how a freeze gets opened — and the verdict is read from the run. Carrying a second verdict here would be a second answer to one question.
- **One run can back more than one certification.** A green row is reusable when the commit, the fingerprint and the width all match, so an unchanged candidate can be re-certified without re-running, and a re-certification cites the same run rather than restating it. That is why runs are records in their own right rather than fields of a certification.

### run (fact) — "what actually executed, and what came of it?"

**Status: the header is proposed; the case rows exist today** (without a run identity, which is the one field this document asks them to gain).

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

### freeze episode (entity) — "why is nothing landing on this line, and who is fixing it?"

What is true when the freeze opens:

```json
{
  "id": "frz-261009-03",
  "line": "default",
  "cause": "cert-261009-14",
  "seq": 41078,
  "at": 1791508600000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `id` | `frz-261009-03` | A thing with a lifetime: "why is nothing landing" must be answerable while it is open |
| `line` | `default` | A freeze is per line — one line's red does not stop another's landings |
| `cause` | `cert-261009-14` | The certification that stopped the line: the freeze **points at its cause** instead of saying "something is red" |
| `seq` / `at` | `41078` / `1791508600000` | Its place in the ledger's order, and **the moment it opened**. That is what `at` means on every record; a field called `opened_at` would be the same instant under a different name |

**The culprit set is not a field either.** What could have caused this red is exactly *the landings in the covered range*, and the range is derived from `cause`: the landings that landed after the previous certification on this line. Two things follow, and both matter:

- **It is a set of landings, not of tickets.** A ticket is what a person talks to; a landing is what can be reverted, and a ticket may own several landings (a rework produces another one). Blaming the ticket when one landing is the culprit would name more content than the evidence supports. The ticket view is a lookup from the landing, and a person wanting "which tickets are implicated" reads it from there.
- **It is derived, so writing it here would be a second answer** — the same reason `base` was dropped. When the range narrows, that is the `attribution` change record below, and its value names a **landing**.

Everything that happens to it afterwards is **another record keyed to it**, because a fact is never edited:

```json
{
  "freeze": "frz-261009-03",
  "change": "attribution",
  "value": "isolated: ldg-261009-0007",
  "by": "integration",
  "reason": "the per-line results pointed at one landing",
  "seq": 41081,
  "at": 1791509900000
}
```

```json
{
  "freeze": "frz-261009-03",
  "change": "closed",
  "by": "t261009-04",
  "reason": "the remedy landed and certified",
  "seq": 41102,
  "at": 1791515000000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `freeze` | `frz-261009-03` | Which episode this is a change to |
| `change` | `attribution` / `closed` / `reopened` | The kind of change. Three, and no more are needed |
| `value` | `isolated: ldg-261009-0007` / `boundary, culprit not isolated` | For an attribution change: a **landing**, not a ticket — and **the design requires that the second sentence be sayable** |
| `by` | `integration` / `t261009-04` | For a closure: the remedy that reopened the line. For a reopening: whoever decided |
| `reason` | `the remedy landed and certified` | Mandatory, as on every record |
| `seq` / `at` | `41102` / `1791515000000` | Order, and when the change happened |

**So there is no `state`, no `closed_at`, no `closed_by` and no `reopened_reason` on the episode** — writing the closure into the opening record would be editing a fact, and a field called `closed_at` sitting next to an `at` that means "opened" is the same instant under a second name. State, age and attribution are all **derived**: the state and the attribution are the latest change of that kind, and "how long was the line stopped" is the closing record's `at` minus the opening record's `at`. A freeze that never closes has no closing record, which is exactly what "still stopped" should look like.

### promotion — "what did a person approve, and what did main become?"

```json
{
  "id": "prom-261009-02",
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
| `id` | `prom-261009-02` | Cited by a ticket's outcome and by any later withdrawal |
| `certification` | `cert-261009-14` | **Which proof justifies this delivery** — a promotion can never name content without one |
| `line` | `default` | Which line it takes content from |
| `repos[].revision` | `7c1d90ab` | What actually moved |
| `tickets` | `["t261008-45", "t261008-46"]` | Whom it delivers — the only source for "delivered" |
| `main_before` / `main_after` | `[{"repo":"sandbar","revision":"de46ce42"}]` / `[… "7c1d90ab"]` | Makes the promotion a fact about a range; rollbacks and withdrawals can name it |
| `signer` | `integration` | Who actually signed |
| `on_behalf_of` | `host` / `null` | Delegation: the record names both sides |
| `authority` | `宿主令 261009「...」` | The order being executed — the third field of the `by`/`who` split |
| `note` | `two engine-hardening landings` | The human's own words about what this promotion is |
| `at` | `1791512000000` | Milliseconds since the epoch |

### withdrawal is work, not a record (priority lowered by the host, 261009)

The original design had a **revert** record: which landing was withdrawn, where the withdrawal was made, and which lines still carried it. The host's call is simpler and better, and it removes a record type:

**If something must be withdrawn, open a ticket whose change is the undo.** It is a ticket like any other — its content lands, is certified and is promoted — and it is a **remedy ticket**, which is the same shape the buffer design already gives to a red that implicates a landing. What the revert record was carrying turns out to be derivable or already covered:

| What the record carried | Where it lives instead |
|---|---|
| Which piece of content was withdrawn | A **relation**: this ticket exists to withdraw that landing (the same relation vocabulary, with the outcome recorded as "withdrawn" rather than "fixed forward") |
| Where the withdrawal was made (`main` or a line) | Where the withdrawal's own landing happened — the ordinary landing record says it |
| Which lines still carry it | Derived: the lines whose history contains that landing |
| Whether a line has actually let go | **Not a stored state at all — a check.** A promotion must not re-introduce a patch that was withdrawn, and that is answered by comparing content at promotion time (patch identity), not by a per-line flag that someone has to remember to update |
| "Closed" versus "delivered" for the affected ticket | The projection: `reverted_at` is derived from the withdrawal's relation plus the promotion that carried it |

**Why the relation is kept, and why it is not another derivable field.** The tempting argument — "the withdrawal is visible in the content, so derive it" — was tested against the cases: an exact `revert` undoes the diff, but a **partial** withdrawal undoes part of it, a change can be the *inverse-looking* diff of an earlier one for an unrelated reason, a revert of a revert withdraws the withdrawal, and once the earlier landing has been edited by later work "its patch" is not a well-defined object. Content tells you *what the diff is*; it cannot tell you *that this work exists to withdraw that landing*. That is a judgement, so it is recorded the way judgements are recorded — with a recorder, a reason and the landing it names.

**It needs no new kind.** The relation is the existing one for "this work exists because of that ticket", whose **outcome is recorded where the work closes** — `withdrawn` rather than `fixed forward`. A separate kind for withdrawals would be a second way to say the same thing, which is what the outcome field exists to prevent.

**And it has its consumers**, which is the ledger's own admission test: the promotion guard (the set of patches that must not come back) and the affected ticket's projection (`reverted_at`). One scope limit is recorded honestly: the relation names a **landing**, while the guard compares **patches**; for an exact withdrawal those are the same thing, and for a partial one the reason must say so rather than the design pretending to a finer granularity than it has.

Two things must survive this simplification, or the guard is lost:

1. **The withdrawal is recorded as a relation**, not just as a diff. A revert commit's message is not a fact the flow can read; the relation is what the promotion check consults, and it is recorded by whoever decided to withdraw (a judgement, with a name and a reason, like any attribution).
2. **The promotion check must actually use it**: refuse — or at minimum name — a candidate that re-introduces the patch of a withdrawn landing. Without that check, the simplification is real and the guard is gone.

What this costs: nothing in correctness, and one thing in presentation — a reader who wants "which lines still carry the withdrawn change" asks for a computation instead of reading a field. That is the same trade the rest of this document already makes.

### ticket outcome — "where did this ticket end up?"

Delivered:

```json
{
  "ticket": "t261008-45",
  "landed_at": "9f3c2a1b",
  "certified_by": "cert-261009-14",
  "delivered_in": "prom-261009-02",
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
| `delivered_in` | `prom-261009-02` / `null` | The promotion that carried it; `null` is normal and is **not** a defect |
| `reverted_at` | `null` / `1791515000000` | Derived from the withdrawal ticket's relation plus the promotion that carried its content — a withdrawal is work, not a record |
| `waiting_since` | `1791510000000` / `null` | **What tells "waiting" apart from "stuck"**: a waiting ticket has a start time and a certification it is waiting for |

**It is not a record in the fact ledger.** It has no `id`, no `seq` and no `at` of its own, because it has no moment of its own — it is a function of the landings, certifications, promotions and reverts. Where a projection is *kept*, it is kept as a **derived view**, and three rules come with that:

- **Derived only.** Nothing writes to it except the derivation, and no other record may cite it: a promotion is cited for "delivered", never "the outcome says delivered". A cached answer that other records lean on has become a second source.
- **It carries the cursor it was computed up to.** A view is stored "as of seq N", so a reader can tell whether it is behind rather than discovering a stale answer. That is the same cursor the ledger design asks for on the read path.
- **It is droppable and rebuildable, and the rebuild is also the check.** Deleting it must cost nothing but a recomputation; rebuilding it and comparing against the facts is exactly the patrol job that catches drift. Whether it exists at all is a performance decision, not a modelling one — and today the project already keeps projections of this kind (the per-ticket mirror of the engine's own history, and the generated document index).

## B. Relation records (proposed)

**Status of this section:** none of it exists. Today the repository layout is *derived* from the directories; the declared relations and the proof rule they carry do not exist, and neither do the relation records or their corrections.

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

## C. Fault knowledge (what is known broken)

**Two of these four exist today, in prose or in a file; two do not exist at all.** Each entry says which.



### fault mode (entity) — "have we seen this before?"

**Status: today** — 228 entries in one prose file, edited in place. The record below is what the entity would look like once the prose is split into an entity and its dispositions.

```json
{
  "id": "KI-227",
  "title": "an uncommitted change on main blocks other tickets' merges",
  "blocking": false,
  "pattern": "merge_check dirty-tree guard",
  "trigger": "anyone leaves an uncommitted change in the main working tree"
}
```

**Today** these are prose entries in one file, edited in place; this is what the entity would look like. It carries no state: `open` / `booked red` / `fixed` / `obsolete` live in its **dispositions** (below), which is why the entity can stay unedited while its status moves.

### fault-mode disposition (fact) — "do we accept this, or must it be fixed?"

**Status: today as prose** — the ledger's own convention already says a fault mode moves `open → fixed（注明修复工单）`, but nothing records that transition as a record; the record below does not exist yet.

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

**Status: missing today** — the join exists only as prose citations inside scenario descriptions and the fault ledger's text.

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

**Status: today** — a machine-read file in the repository, one row per case.

```json
{
  "case": "t261004-26",
  "expected_red": true,
  "reason": "load flake in the full suite",
  "booked_by": "integration"
}
```

**Today**: a machine-read file in the repository.

## D. Inspection records (what a review reported, and where it looked)

**Yes — a `finding` is exactly what an inspection period's agent reports.** The inspect stage spawns a read-only inspection agent that must return one fenced block of findings; each carries a subject, a severity, evidence as `path / line / quote`, a why, a suggestion and a confidence. The id is **minted mechanically from the content** (so the same finding keeps its id across periods), the evidence is **verified mechanically** (the file exists, the line is in range, the quote matches — otherwise the entry is downgraded and named, never silently dropped), and only findings that are verified, confident and at least medium severity may spawn fix tickets. A finding is therefore the inspection subsystem's own unit of "here is a problem", and it is deliberately hard to fake.

Two clarifications that keep this section honest:

- **The section holds more than findings.** Also here: the **observation** (a finding *seen again*, against a named revision — proposed; today only the finding itself exists) and the **reviewed path** (which files a period actually examined — today, and that is a coverage ledger, not a finding).
- **The faces are running now.** An earlier reading of this project's own design notes said the `docs-sync` and `simplify-face` instances had never run; that is no longer true. The docs-sync period for 20261009 closed today with **62 findings**, and its reviewed-path ledger recorded 227 paths for the same period. What matters for this document is the shape of the record, not the count — but the count is worth keeping honest.
- **A change-producing face does not report findings.** The doc and simplify faces produce **a change**, which is a ticket that lands like any other work. "Inspection output" is therefore three different things: findings, changes, and coverage.

### finding (entity) — "what is wrong here?"

**Status: today, and its home is the period ticket.** An inspection period's findings are stored **on the ticket itself** — `t261009-09` ("Inspection docs-sync · period 20261009") carries `findings` as a list of 62 entries together with `instance_id`, `period` and `kind` — plus a report artifact written to `server/engine/out/inspection/<instance>-<period>.json` (a path that is not tracked). So the snapshot has a home. What has none is the **entity that outlives the period**: the ticket holds one period's list, and "the same finding seen again next period" exists only because the ids are minted from content. That is the gap the observation record below is for.

The shape below is **verbatim from a real period** (period 20261009, docs-sync face, 62 findings), not a sketch — which is why it carries `scan` and `verified` and does not carry the `confidence` this document previously invented:

```json
{
  "id": "3d4b305e",
  "scan": "doc-m1-index",
  "severity": "med",
  "subject": "page exists but is not registered in docs/index.json",
  "evidence": [
    { "path": "docs/design/develop-buffer-v1.md", "line": 1, "quote": "---" }
  ],
  "why": "The page exists under docs/ but the machine index has no entry for it; plugins and agents consume the index.",
  "suggestion": "Register the page (python3 docs/scripts/build_index.py) or move it out of docs/.",
  "verified": "verified"
}
```

Closing it is a fact of its own, and it is decided by evidence rather than by a ticket's state:

```json
{
  "finding": "fi-9c1e42a0",
  "change": "closed",
  "evidence": "the quoted text is gone from main as of 7c1d90ab",
  "at": 1791530000000
}
```

**Today**: produced by the inspection agent; the id is minted from the content and stable across periods, and the evidence is verified mechanically. Where the entity is *stored* is **not settled** (see open questions).

### finding observation (fact) — "is it still there, and for how long has it been?"

**What it is for, in one line: the period records the findings it produced, and the observation is the link that says *this finding was seen again, in this period***. Without it, every period starts from zero as far as the record is concerned: the ids are minted from content, so the *same* finding does keep its id across periods, but **nothing states that it was seen again** — a reader would have to open several period tickets and compare id lists by hand.

The questions it answers, none of which have an answer today:

- **How long has this been open?** First sighting to closure — the age of a finding, which is what decides whether it is being lived with or being ignored.
- **Is it persisting, or was it a one-off?** Seen in five of the last five periods is a different thing from seen once.
- **Was it actually fixed?** The finding disappearing next period is not proof: the quote may simply have drifted out of match, and this time the verification says so.
- **Did two faces report the same thing?** The same content found by two scans is one problem, not two.

**A sighting's verification can differ from the last one, and that is the fact worth recording**: the file changes underneath a quote, so the same finding can verify in one period and fail to locate in the next. The proposed shape keeps only what cannot be derived — the pairing, the verification outcome, and the moment.

**Status: proposed** — today only the finding itself exists, so "seen again, against this revision" cannot be recorded.

```json
```json
{
  "finding": "3d4b305e",
  "period": "20261007",
  "verification": "downgraded",
  "verification_note": "the quoted line is no longer in the file at that path",
  "at": 1791520000000
}
```

| Field | Example value | Why it is there |
|---|---|---|
| `finding` | `3d4b305e` | The entity this sighting belongs to — the real id shape, minted from content (as the period ticket's own findings are) |
| `period` | `20261007` | Which period saw it |
| `verification` | `verified` / `downgraded` / `unlocatable` | **The one thing that changes from sighting to sighting**, and therefore the reason a sighting is a record rather than a field on the finding |
| `verification_note` | `the quoted line is no longer in the file at that path` | A downgrade must say which check failed, never just that it failed |
| `at` | `1791520000000` | Milliseconds since the epoch |

Two fields that were in the earlier draft are **gone**, for reasons this document applies everywhere: **the revision the period read is a property of the period**, not of each sighting (the revision is pinned when the period opens, so every finding in it shares it), and **`quote_fp` had no consumer** — the id already encodes the content, and nothing reads a separate quote fingerprint.

### The grain is the fact, not the run

A period that reports sixty-two findings and examines two hundred and twenty-seven paths writes **many records, not one blob**:

| What happened | Records written |
|---|---|
| A finding seen for the first time | one **finding** record (the entity) |
| A finding seen again | one **observation** record |
| Each path the review examined | one **reviewed path** record |
| The period itself | one **period** record: its identity and the revision it pinned |

So a period with forty new findings out of sixty-two seen produces forty entity records, sixty-two observations, and the paths — and **no record anywhere holds a list**.

**Why not one record per run.** The obvious alternative is what exists today: a single blob holding the period's findings list (that is the ticket's `findings` field, and what the report file contains). It is worse on every count that matters here:

- **A list cannot be read as a stream.** "How long has this been open", "how often has it been seen", "was it re-verified against the newer state" are queries over sightings, and a list inside a per-period record turns each of them into a scan-and-parse across files.
- **It makes the run the unit when the problem is the unit.** Findings persist across periods and are fixed independently of the run that noticed them; a per-run blob re-creates the same problem anew in every period and never lets it grow old.
- **The record becomes arbitrarily large.** Sixty-two findings with evidence is a big object to append atomically, and one of them being malformed costs the whole period.
- **It duplicates the entity across periods**, one copy per period, each of which can be verified differently — which is exactly the drift the entity/observation split exists to prevent.

**The counts are not stored.** How many findings a period produced is a count over that period's observations, so it is a projection like any other — the period's record carries its identity and pinned revision, and the number on the face is computed. **The precedent is already in the store**: `reviewed.jsonl` writes one row per path per period rather than one row per period, and every other family in this document writes one row per fact.

### Where a period's output lives — and what the report file becomes

Today a period writes **two** things outside the flow: the findings as a list **on the period ticket** (`t261009-09` carries 62 of them), and a **report file** per period per instance under the engine's `out/`, which nothing tracks. Asked whether the report stays a JSON file or becomes part of a stream, the answer follows from the rules this document already applies:

- **The report file is the weakest home of the three.** It sits in the repository's working tree but is not tracked, so it is neither versioned nor shared nor backed up; it has no cursor, so "which state of the world does this describe" cannot be asked of it; and there is one per period per instance, so a year of them is a directory of files nobody reads. It cannot be the home of the facts.
- **The ticket is better but still per-period.** It is durable and it is the audit surface, and it is what the engine compares against the previous period. What it cannot be is the *entity's* home: it holds one period's list, so "seen again next period" is not a fact anywhere.
- **The store is where they belong.** Findings are operational facts: append-only, read as of a cursor, shared, backed up by the same story as the rest of the store, and queryable as a stream — which is exactly what the four questions in the observation entry need. `reviewed.jsonl` in the same store already shows the shape working for the input side.

So the shape is: **records in the store are the detail; the period ticket carries the period's own face — how many findings, and the cursor it wrote — and cites rather than copies; the JSON report becomes a generated view, or is dropped.** Three notes make that honest:

1. **A generated view may still exist as a file**, for a human who wants to open one period's result, but it is labelled generated and can be rebuilt from the records; it is never cited as the source, and it never has to be reconciled with anything.
2. **Old periods are not rewritten.** Their findings stay on their tickets; new periods write records. A reader therefore meets both shapes, and the period's own face says which one it holds.
3. **The period ticket's count-and-cursor summary is not a second copy** — it is a reference, on the same footing as the ticket-outcome projection: if it disagrees with the records, the records win.

### reviewed path (fact) — "has anyone looked at this file lately?"

**This is the input side of a period, where a finding is the output side.** One row per path per period: which files the review actually examined. Its purpose is coverage — a face that quietly narrows what it reads still reports the same number of findings, and only this ledger shows that it stopped looking at a whole area.

**Status: today** — one row per path per period, verbatim below.

```json
{
  "path": ".gitignore",
  "period": "20261007",
  "ts": 1791338554.34
}
```

**Today**, verbatim: what an inspection period actually examined (not a finding).

## E. Fleet and operations records (today)

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

### inspection period (entity) — "what did this period do, and what became of it?"

```json
{
  "id": "insp-docs-sync-20261007",
  "instance": "docs-sync",
  "period": "20261007",
  "ticket": "t261009-05",
  "seq": 41055,
  "at": 1791400000000
}
```

```json
{
  "period": "insp-docs-sync-20261007",
  "change": "voided",
  "by": "integration",
  "reason": "the line was frozen for the whole period",
  "seq": 41120,
  "at": 1791520000000
}
```

Same shape as the freeze episode, for the same reason: the period comes into being when its ticket is opened, and `blocked` / `completed` / `voided` are changes to it, not fields that get rewritten. The `change` values in use today are `blocked`, `completed`, `voided` and `re-run`, and a disposition carries `who` and `reason` exactly as above.

## F. Ticket truth

The truth about a ticket — its stage, its signature, its verdict, a send-back — lives in the workflow engine's own history and is **not** duplicated here. Everything in this document that mentions a ticket is either a projection of that truth or a fact about something else that names a ticket.

## Open questions for this review

1. **Findings' home is settled (the store, as records — see the note in section D), and what remains is the split**: today the finding and its sightings are one per-period blob on a ticket, so the entity that outlives a period still has to be separated from the sightings that record it.
2. **`by` / `who` must split.** Examples of the prose that cannot be machine-checked are in section D (`capacity limit change.by`, `authorisation change.who`). Proposed: `actor`, `on behalf of`, `authority reference` — all three required when the writer is not the authority.
3. **Shape versions.** The event ledger has one (`event-ledger-v1`); the rest do not. Roll the same convention out, and state what a reader does with an unknown version (fail loudly, not guess).
4. **Retention per family.** Only the event ledger has a rotation cursor; run results are 88 MB and rotate by rename alone. Each family needs a declared lifetime.
5. **What may never be recorded.** "References, not payloads" needs forbidden examples (credentials, tokens, private host paths, raw model input containing them) so a record can be refused rather than argued about.
6. **The case rows need `run` added** (and a repository, once a landing can span repositories). Until they carry it, no certification can point at a run, and the header record is not enough on its own — the rows are what a reader checks the counts against.
7. **What ends a ticket that has no content?** A report-only or verification-only ticket changes no files, so it has nothing to land and nothing to certify by landing. The `landed_at: null` row is representable; the rule for how such a ticket finishes is not written yet, and it is the one gap that this section exposed.
