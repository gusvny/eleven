# t261021-13 — server patch bundle (write-set escalation handover)

## Why a bundle and not a direct edit
The ticket's declared write set is `integration/` only, but the incident's root
cause lives in `server/plugins/executor-panel/src/host/panel-page.ts` (the epic
doc anchor aimed straight at `/sandbar-workbench/api/wf/docs/doc`, which answers
JSON). The engine mechanically reverts out-of-write-set edits and the
merge_check gate refuses foreign files (t261021-06 precedent, ledger seq 47–48
on 2026-10-21). Landing the edit directly would burn rounds in a revert loop.
So the change is carried here as full replacement files; the host must widen
the ticket write set to include:

    server/plugins/executor-panel/src/host/panel-page.ts
    server/plugins/executor-panel/src/host/markdown.ts
    server/plugins/executor-panel/tests/markdown.test.mjs

then one round applies it: `sh integration/t261021-13/server_patch/apply.sh`
(from the lane root; refuses on tree drift via sha256 pins of the pre-patch
files).

## What the patch does
1. `panel-page.ts`
   - `epicDocLink(code)` emits `<a class="btn" role="button" tabindex="0"
     data-epicdoc="CODE">Open docs/epics/CODE.md</a>` — no href, no target, so
     nothing on the page can navigate at an api/ route.
   - new `openEpicDoc(code)`: sets `state.docsScope='docs'`, `state.docSel=
     'epics/CODE.md'`, checks the `t-docs` radio, calls `showTab('t-docs')` —
     the tab's lazy loader fetches the tree and `renderDocs()` renders the
     reader because the selection is already set. The existing reader path
     (`renderDocBody`) is reused; there is no second markdown renderer.
   - `renderDocs()` empty-tree branch: when `state.docSel` is set the reader
     renders instead of being wiped (an epic document click must survive an
     empty library answer; a vanished file shows the reader's named red
     banner, never an empty box).
   - click/keyboard binding for `[data-epicdoc]` in `renderEpics()`.
2. `markdown.ts` — pipe-table support in the ONE shared renderer (the ticket
   requires tables; the renderer had none, so the reader could never satisfy
   it). A line starting and ending with `|` opens a table; a `| --- |`
   separator second row promotes a `<thead>`; cells go through the same
   escape-then-inline pipeline, so hostile cell content stays literal text.
   Pure self-contained JS (the function is embedded via `toString()`).
3. `tests/markdown.test.mjs` — three table UT blocks: header table, headerless
   table with a hostile cell (must stay literal), inline marks inside cells.

## Evidence already gathered (implement stage, isolated /tmp copy)
- The patched module loads and `PANEL_PAGE_HTML` contains 0 `href=".../api/`
  occurrences, emits `data-epicdoc`, defines `openEpicDoc`.
- Headless chromium smoke against the patched page (stub API, no docker, never
  3099/7233): link click stays on the same page, Docs tab activates with docs
  scope, reader shows title path + h1/li/table/pre, missing document shows the
  "could not be read" red banner, empty-tree project still renders the reader,
  zero api-aimed anchors in the DOM, zero pageerror.
- `node --test tests/markdown.test.mjs` green on the patched copy (hostile
  matrix + new table cases).
- `integration/lint_tests.py` green; `node --check` and `py_compile` green on
  the integration/t261021-13 entries.
