---
code: doc-lifecycle
retired: false
summary: Two directories, two kinds of text: notes/ is scratch, docs/ is the archive.
---

# doc-lifecycle

## What it does

Separate working text from confirmed text: notes/ holds discussions, KI entries and drafts; docs/ holds the documents a future reader may trust.

## The problem it solves

Drafts, discussions and incident records were mixed with confirmed design, so nothing said which file was authoritative.

## Design and rulings

`docs/README.md` (the split), writing standard `docs/reference/writing-standard.md`.
