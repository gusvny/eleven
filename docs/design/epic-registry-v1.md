# Epic registry v1 — `docs/epics/`, one boolean, enforced at ticket creation

Status: design (host-ruled 261019). Implementation is a separate ticket.

## What an epic is

An epic is a **product intent**: what it wants to do and which problem it solves. It is not a
progress record. Progress, in-flight tickets and outcomes stay in Temporal and on the ticket
face — never in the epic document.

## Why the store moves to `docs/`

Epics describe the product, so they belong beside the design documents, not in the knowledge
ledger (`notes/`, which holds KI entries, discussions and the migration record). One library also
means the Docs tab already lists them, and the writing standard is unambiguous (documents under
`docs/` are English).

## Shape: front-matter + body

```
---
code: develop-buffer
retired: false
summary: The delivery line: land a ticket on develop-buffer, certify the revision, promote it to main.
started: 2026-10-09
---
```

* `code` — the epic code, identical to the file name without `.md` (lowercase letters, digits,
  hyphens). One epic, one code, one file.
* `retired` — **the only state**. `false` = the epic accepts tickets; `true` = it does not.
  A draft epic is `retired: false`: the host has not ruled a draft out of scope, and a draft that
  cannot receive a ticket is indistinguishable from a closed one.
* `summary` — one English sentence, shown in the list. It is the epic's "what and why", not its
  status.
* `started` — the date the epic was opened (YYYY-MM-DD). Optional for old records.
* The body holds the intent, the problem, the design links and the rulings. No status prose, no
  progress, no ticket lists.

## Why one boolean, not a status vocabulary

A prose status field drifts: it is edited by hand, it carries opinion ("草稿（待宿主审定…）"), and
nothing enforces it. A boolean is the fact that has an operational meaning — whether the epic still
accepts work. Everything else (draft, active, finished) is either history (git) or a live reading
(board, tickets), and neither belongs in a hand-maintained cell.

## Enforcement (the reason this is a design, not a rename)

`retired: true` must **refuse a new ticket by name**. The single validation point is
`shared.validate_epic_code` (called by the engine on ticket creation); it already rejects an
unknown code with the directory it queried. It gains one more check, in the same voice:

```
epic 'develop-buffer' is retired — it no longer accepts tickets (docs/epics/develop-buffer.md,
retired: true). Open a new epic or ask the host to un-retire it.
```

A UI that greys the epic out without this refusal is a comment, not a rule. The refusal is
fail-closed: an unreadable front-matter block is treated as retired-by-defect with a named reason,
never as "accepting".

## Migration (one ticket, no dual source)

1. `notes/epics/*.md` (16 files) → `docs/epics/<code>.md`, translated to English, front-matter
   added, body reduced to intent + problem + design links (existing Chinese status prose is dropped,
   not carried).
2. Readers switch to `docs/epics/`: the workbench `GET /api/epics` (and the per-epic tickets
   endpoint), `shared.resolve_epics_dir` / `validate_epic_code`, `ticket.py` list filters.
   Hard cut — a missing directory is a named error, never an empty list pretending to be "no epics".
3. The Docs tab lists `docs/epics/` as its own group (no extra code).
4. The Epics tab renders: code + `retired` badge + `summary` + ticket count + last activity, expands
   in place to the newest five tickets (title on every row) and the document link. No separate
   detail page.
5. `retired` shows as `online` / `retired` in the UI; `summary` is the only prose from the document
   that reaches the surface.

## Out of scope

Progress, ticket lists and status history inside the document; per-epic permissions; the request
ledger; the inspection instances.
