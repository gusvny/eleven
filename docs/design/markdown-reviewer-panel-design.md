---
title: "Markdown reviewer panel design"
category: design
tags:
  - design
  - workbench
  - change-review
status: active
updated: 2026-10-22
---

# Markdown reviewer panel design

What the changed-files markdown reviewer is, where its comment store lives, and
which rules the implementation pins (ticket t261022-14; plan reviewed and
passed at review_plan round 2). Visual baseline: the host-approved mock
`~/Documents/markdown-reviewer-mock.html` — behaviour is reproduced, its code
is not copied.

## 1. Surfaces

- Entry: every changed-file link in the ticket detail (status card and the
  Changes fold) routes **markdown files** (`.md`/`.markdown`) to the reviewer
  panel; JSON/code files keep the raw read-only viewer (ticket non-goal — the
  non-markdown viewer is unchanged).
- Panel layout: a left rail (changed doc files, each file's h1/h2 table of
  contents, the comment list in document order with an Open (default) / All /
  Resolved filter), a minimap rail, and the rendered markdown. The rail is a
  flex sibling with its own collapse control — it never overlays the document.
- Module split: pure model in `server/plugins/workbench/src/client/review-panel-model.ts`
  (unit-tested in node), React face in `src/client/review-panel.tsx`, lane file
  store in `src/host/review-comments.ts`, routes in plugin-root `node.ts`
  (`GET/PUT /sandbar-workbench/api/wf/tickets/<id>/review-comments?path=`).

## 2. Block model

The rendered document is split into blocks: one heading, one paragraph, one
list item, **one table cell** each. The diff face (host `changes.ts` →
knowledge `blocks.ts`) ships row-level table blocks, so the client model
subdivides every `table-head`/`table-row` block into per-cell child blocks;
the cell is the unit of diff mark, comment anchor and navigation. Knowledge
`blocks.ts` is read-only reused, never modified (it is outside the plugin
write boundary). A modified row marks exactly its changed cells, via the same
word-level diff used for modified paragraphs (`wordDiff` in the client model:
green inserted runs, red struck-out runs, amber block background).

## 3. Anchoring (never drop a thread)

A thread anchor records the block index, the block text hash
(`blockHash`, djb2-style, computed identically on write and resolve) and a
neighbour snippet (the previous block's summary). On open:

1. exact hash match — the thread sits on its block;
2. hash miss → index plus neighbour fallback (the block at the recorded index
   and its ±1 neighbours are probed);
3. no match → the thread renders at the end of the document labelled
   outdated.

Rule: a thread is never silently dropped. The only removals are structurally
unusable entries at load time, and they are counted and named in the panel.

## 4. The lane is the store

Every comment lives in `<lane>/.sandbar/review-comments.json`
(`schema: review-comments-v1`): `ticketId`, `path`, `updatedAt`, and threads
`{ id, parentId|null, anchor{index,hash,neighbour}, author, at, text,
resolved, replies[] }`. Nothing is written to any server-side store; the
GET/PUT endpoints are plain file IO the console host performs on the browser's
behalf. The panel shows the lane file path and states that the lane agents
read the file at their next turn and act on open threads, leaving thread state
as they find it.

Write-path handling (the fault-mode table from the plan, now fact):

- traversal guard on the lane root and the file path (no `..`, no absolute,
  no `~`; the resolved lane root must sit inside the repo anchor);
- per-file in-process mutex serializes read-modify-write; threads merge by id,
  last write wins per thread;
- temp file + atomic rename; the temp file is unlinked on every error path;
- `.sandbar/` is created recursively; a missing file reads as "no comments";
- corrupt JSON: read reports it by name, PUT refuses (409) — a bad write can
  never destroy evidence; the existing file is never truncated on an over-cap
  refusal (413);
- PUT requires `content-type: application/json` (415 otherwise) and a
  JSON-parseable body under the 64 KB route cap.

Cross-process races are out of scope by the single-owner assumption (one
console process owns a lane).

## 5. Tests

- `server/plugins/workbench/tests/t26102214-review-comments-store.mjs` —
  schema round-trip on every field, merge/resolve/reload, fault modes.
- `server/plugins/workbench/tests/t26102214-review-panel-model.mjs` — blocks,
  cell subdivision, word diff, anchor resolution, filters, badges, TOC,
  minimap, hostile inputs.
- `integration/t261022-14/sc_t26102214_lane_review_comments.mjs` (registered
  as `t261022-14-lane-review-comments`, browser-free pool) — the real store +
  real anchor model end to end against a temp lane directory outside any repo
  tree, with the lane JSON re-read from disk through the plain file-read path
  the lane agents use.
