---
title: "Epic Documents Move into the Docs Library"
category: design
tags:
  - epic
  - docs structure
  - knowledge base
  - ticket linkage
status: draft
updated: 2026-10-04
---

# Epic Documents Move into the Docs Library

> Source: host decision, 261004. The host asked to move the epic proposals into the docs
> library, to keep only the proposal content and its related documents there, and to read
> execution records from tickets by epic code instead of storing them in the document.
> This page is the admission standard for the migration ticket. One item inside is still
> open and is marked as such.

## Problem

**One sentence**: the epic proposals read like finished documents, but they live on the
side of the repository that holds discussion and ledgers, so they follow neither discipline
properly, and their related documents sit in a second place.

**Background knowledge.**

- This repository keeps two libraries. The docs library holds finished documents: it has an
  index, an admission standard, a self-check list, and one language. The notes library holds
  the knowledge base: discussion drafts, the known-issue ledger, and the epic proposals.
  The split is deliberate: a finished document and a ledger that keeps growing are two
  different things.
- An **epic proposal** answers "we are going to do this": the goal, the scope, the
  acceptance criteria, and the boundary. Each epic has a **code**. A ticket carries that
  code, and the engine lists the tickets of one epic by code.
- A **lane** is the workflow that does work. The notes library is closed to lanes: only the
  main side (host plus the integration role) writes it. The docs library is open to lanes:
  a ticket may name it in its write set. So the location decides who may write a thing and
  how the write lands.

**Evidence.**

1. Thirteen epic proposals live in the notes library, 164 KB together, 3.8 KB to 29 KB each.
2. Each proposal already points at its related documents, and those sit in the notes library
   as well: the design page and the interface mock. So the material of one epic is split
   across two libraries.
3. The proposals carry execution records. The number of ticket references per file:
   `project-lifecycle.md` 16, `session-entry.md` 11, `engine-hardening.md` 8,
   `dsh-upgrade.md` 6, `doc-lifecycle.md` 6. The engine is the source of truth for "how far
   did this epic get", so that half of the text is a table that must rot. The charter forbids
   maintaining progress and ticket lists by hand in a document.
4. The write rate is low. Most of the thirteen files were last changed in mid-September; only
   one was touched this week. "Written once, then rarely changed" holds, and that is the shape
   of a finished document, not of a ledger.

## Requirement

1. **One place to see it all**: the proposal body and its related documents (design page,
   interface mock, contract diagrams) live in one directory of the docs library.
2. **No progress in the body**: the body carries what and why, the scope, the acceptance
   criteria and the boundary. It carries no progress table, no ticket list, and no
   "done: N" counter. Anyone who wants progress asks the engine by epic code.
3. **The code stays the only machine key**: opening a ticket against an epic and listing the
   tickets of an epic keep the same observable behaviour. The same code returns the same
   epic and the same set of tickets before and after the move.
4. **The docs discipline applies**: a moved proposal gains frontmatter, an index entry, the
   four-section shape, and the library language.
5. **No silent drift, loud refusal**: the move changes no outcome. A code that resolves to
   zero candidates, or to more than one, fails loudly and names the failed check.
6. **Stakeholders**: the host (reads the plan and the boundary), the integration role (writes
   on the main side), the lanes (read it as context), the engine (resolves the code), and
   later agent readers (use the proposal as context).

## Nongoal

1. **The ledgers do not move.** The known-issue ledger, the discussion drafts and the request
   ledger stay in the notes library, stay Chinese, and keep a single writer.
2. **No new lane here.** The doc lane is a separate design page. The migration uses the
   existing lanes.
3. **No new linkage mechanism.** The engine can list tickets by epic code today. This work
   uses that ability and adds nothing to it.
4. **No content rewrite beyond the language pass.** The migration does not improve, shorten
   or re-decide the proposals.
5. **No hash in the directory name.** The reason is in the Proposal section.
6. **No decision here about who may edit a proposal.** The main side keeps that right for
   now. The doc lane design page takes up the question later.

## Proposal

### High level

Move the epic proposals into the docs library, one directory per epic:

- the directory name starts with a date and ends with the epic code, so a human sees the
  order and the machine reads the code;
- the directory holds the proposal, whose file name is the code, plus its related documents;
- the frontmatter carries the one-off facts, including the status field, and links to the
  other documents in the same directory;
- the body keeps what and why, the scope, the acceptance criteria and the boundary. The
  execution records leave the body, and the engine answers progress by code;
- the migration is one atomic change: location, resolution, references and index move
  together, and every observable behaviour stays the same.

### Key tradeoffs

1. **The code is the only key, so the directory name carries no hash.**
   The code is already the unique machine key: tickets attach to an epic by it, and the
   engine lists tickets by it. A second short identifier of unclear origin would give one
   object three names, turn an exact lookup into a search, and invite transcription errors.
   Two directories with the same code could not be told apart. The date prefix stays,
   because it helps a human sort, and because the resolution rule is simple: one candidate
   passes, two candidates refuse by name, no candidate refuses by name.
2. **The status field lives in the frontmatter; progress does not live in the body.**
   A status changes, but it is one machine-readable value. Progress keeps growing, so in a
   body it becomes a table that must rot. The engine already answers "how far did this epic
   get" by code.
3. **The directory holds finished documents only.**
   "Written once, then rarely changed" is the premise of this move. A draft in the same
   directory destroys that premise and hides which text is authoritative. Drafts stay in the
   notes library and move in when they are finished, with their history.
4. **The language follows the docs library.**
   The docs library has one language, with one deliberate exception (the terminology table).
   A second exception would announce that exceptions are normal. A host quotation stays as it
   is: the writing standard exempts quoted text, so no new exception is needed.
5. **One atomic move, not two steps.**
   Location, resolution, references and index bite each other. A half-moved tree leaves two
   plausible sources of truth, and every missed reference turns red, because anything indexed
   by path stops recognising the proposal.

### Details

- **Names**: the directory starts with the date and ends with the code. The proposal file
  is named after the code. Other documents in the directory keep their own descriptive names.
- **Resolution**: every lookup follows one exact code and one unique candidate. Each of the
  three outcomes (one, many, none) has a named result, and the failure text says which check
  failed: no proposal exists, or more than one does.
- **Frontmatter**: title, category, tags, status and updated date, plus a related-documents
  section that links the other files in the same directory.
- **What happens to the removed half**: the execution records leave the body. Their content
  lives in the engine and is read by code.
- **Open item for the host — the ticket roster and engine pruning.** The engine prunes the
  history of closed tickets. If the proposal holds no roster at all, then after a prune
  nobody can reconstruct which tickets belonged to an epic. Two options: (a) at the moment of
  migration, write one dated roster file per epic directory, generated from the engine and
  never maintained by hand; (b) hold no roster anywhere and accept that the roster is
  readable only while the engine keeps the history. The author of this page recommends (a):
  one generated snapshot costs one file, and it keeps the epic readable in git after the
  engine forgets. This item stays open.
- **Effect on existing design pages**: the mechanism design page states that epic proposals
  live in the notes library and that a concluded epic freezes its ticket list into the
  proposal. This design supersedes both statements. The migration ticket updates those lines,
  together with the division-of-labour line in the docs README.

### Tie-back

This proposal solves the three problems named in the Problem section: the wrong home for a
finished document, material split across two libraries, and a body that grows a table which
must rot. It satisfies Requirement 1 to 6: one place, no progress in the body, the code still
the only key, the docs discipline applied, no silent drift. It stays inside the Nongoal
boundary: the ledgers stay, no new lane, no new linkage, no content rewrite, no hash, no
ruling about edit rights.

## Related documents

- Source decision: host session, 261004.
- [Knowledge base design](knowledge-base-design.md) - the split between the two libraries.
- [Design document writing guide](design-doc-writing-guide.md) - the four sections and the
  nine-item self-check this page follows.
- [DeepSeek Harness and Temporal mechanism](deepseek_harness_and_temporal_based_multi-agent_mechanism.md) -
  the epic-to-ticket linkage this design partly supersedes.
- [Doc lane design draft (notes, Chinese)](../../notes/discussions/261004-doclane-设计稿.md) -
  who writes a proposal, taken up after this migration.
