# Known issues — pointer

The fault ledger moved OUT of the repository on 261020 (host order: 「把 KI 从 notes
里移走，不要放在 git 上，后面只有确实需要的 KI 才会落 git」).

**Where the ledger lives now**: the project store, outside git —

```
~/.sandbar/projects/sandbar/kb/known-issues.jsonl   # the ledger: one record per line
```

**One format only (261020)**: the markdown ledger is gone — each record carries its
own body (the reading, the evidence, the lessons), so a separate prose file would
be a second copy of the same text. Read it with
`python3 integration/ki_ledger.py --render` (human view) or `--status open` (query);
write it with `--add-json` / `--set-status` — nobody hand-edits JSON.

**Why out of git**: 326 entries of running case notes — every fault, its reading and
its retirement — turned the repository into a log nobody could review, and the
ledger's churn dominated diffs that should be about the product. The ledger is
operational memory, not deliverable text.

**How to read / write it**
- Read: `python3 integration/ki_ledger.py --render` (full text) or `--status open`
  (ids only). `--check` fails when the ledger is unsound (duplicate id, unknown
  status, empty ledger).
- Write: `--add-json '{"id": "KI-<ULID>", "title": ..., "status": "open", "body": ...}'`
  or `--set-status KI-... fixed`. New ids are `KI-<ULID>` (never reused, never
  renumbered).

**What still lands in git**: only a KI whose TEXT a repository reader genuinely
needs (a design rule that must travel with the code, or a repair-hatch entry the
host authorised). Those are listed below as pinned entries, with the text inline —
a pin is a copy, and it says which ledger entry it mirrors.

## Pinned entries

_(none yet)_
