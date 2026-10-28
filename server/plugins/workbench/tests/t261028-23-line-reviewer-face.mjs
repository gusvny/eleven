/**
 * tests/t261028-23-line-reviewer-face.mjs — the rendering leg of the code-file
 * reviewer (t261028-23). Two halves, both required:
 *
 *   1. RENDER DATA (pure): buildLineRender puts a line thread UNDER the row it
 *      anchors to, keeps an outdated thread on the page (at the end, tagged),
 *      and never leaks a thread onto a neighbouring row.
 *   2. RENDER SOURCE (static): the panel actually prints that grouping — it
 *      consumes buildLineRender, marks rows with both line numbers and a +/−
 *      marker, prints the path/stat/ticket header, renders threads through the
 *      SAME ThreadBox that block mode uses (no second thread design), keeps
 *      markdown block mode intact, and the Changes list routes every file into
 *      the reviewer.
 *
 * Why source-level for half 2: the workbench panel is a React component and the
 * repo ships no DOM renderer to node (the L3 browser scenarios own the live
 * face, and those run at the integration gate). This half locks the wiring the
 * model cannot prove: a model that nobody renders must not pass.
 *
 * Run: node server/plugins/workbench/tests/t261028-23-line-reviewer-face.mjs
 * Pure/offline: reads source files of THIS tree, no server, no browser,
 * never touches 3099/7233.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { parseUnifiedDiff } from '../src/client/diff-rows-model.ts'
import {
  buildLineRender,
  hasOnlyResolvedForRow,
  normalizeLineThreads,
  openCountForRow,
  placeLineThreads,
  toStoreLineThread,
} from '../src/client/review-line-model.ts'
import { normalizeThreads, toStoreThread } from '../src/client/review-panel-model.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const HERE = fileURLToPath(new URL('.', import.meta.url))
const SRC = join(HERE, '..', 'src', 'client')
const panel = readFileSync(join(SRC, 'review-panel.tsx'), 'utf8')
const threadBox = readFileSync(join(SRC, 'review-thread-box.tsx'), 'utf8')
const indexSrc = readFileSync(join(SRC, 'index.tsx'), 'utf8')
const lineModel = readFileSync(join(SRC, 'review-line-model.ts'), 'utf8')

/* ------------------------------------------------------- A: render data */

const DIFF = [
  'diff --git a/server/x.ts b/server/x.ts',
  '--- a/server/x.ts',
  '+++ b/server/x.ts',
  '@@ -1,3 +1,3 @@',
  ' keep me',
  '-old line',
  '+new line',
  '@@ -20,3 +20,3 @@ export function later() {',
  ' second hunk',
  '-gone here',
  '+fresher here',
].join('\n')

const parsed = parseUnifiedDiff(DIFF)
const rows = parsed.ok ? parsed.rows : []
const hunks = parsed.ok ? parsed.hunks : []

{
  ok(parsed.ok && rows.length === 6 && hunks.length === 2, 'A1 the fixture diff parses into 6 rows / 2 hunks')
  const target = rows[5] // the added row of the second hunk
  const anchor = { kind: 'line', side: 'new', line: target.newLine, hunk: target.hunk, contextHash: target.hash }
  const threads = normalizeLineThreads([
    toStoreLineThread({
      id: 't-anchored', parentId: null, anchor, author: 'human', at: 2, text: 'this line looks wrong',
      resolved: false, replies: [],
    }, 'server/x.ts'),
    toStoreLineThread({
      id: 't-stale', parentId: null, anchor: { ...anchor, contextHash: 'vanished' }, author: 'human', at: 1,
      text: 'stale comment', resolved: false, replies: [],
    }, 'server/x.ts'),
  ]).threads
  ok(threads.length === 2, 'A2 both threads load through the line model')

  const render = buildLineRender(rows, hunks, threads)
  const groups = render.filter((x) => x.kind === 'row')
  ok(groups.length === rows.length, 'A3 every row has a render group')
  const host = groups.find((g) => g.row.index === 5)
  ok(host !== undefined && host.threads.some((t) => t.id === 't-anchored'),
    'A4 the line thread is rendered under ITS row')
  ok(groups.filter((g) => g.row.index !== 5).every((g) => !g.threads.some((t) => t.id === 't-anchored')),
    'A5 the line thread appears under no other row (never moved)')
  const staleGroups = groups.filter((g) => g.threads.some((t) => t.id === 't-stale'))
  ok(staleGroups.length === 0, 'A6 an outdated thread is not parked on an arbitrary row')
  const tail = render.filter((x) => x.kind === 'outdated')
  ok(tail.length === 1 && tail[0].thread.id === 't-stale', 'A7 the outdated thread STILL APPEARS (at the end)')
  ok(render[render.length - 1] === tail[0], 'A8 the outdated thread renders after every row')

  // resolved threads still render under their row (the badge must see them)
  const resolvedThreads = normalizeLineThreads([toStoreLineThread({
    id: 't-done', parentId: null, anchor, author: 'human', at: 3, text: 'fixed', resolved: true, replies: [],
  }, 'server/x.ts')]).threads
  const render2 = buildLineRender(rows, hunks, resolvedThreads)
  const host2 = render2.find((x) => x.kind === 'row' && x.row.index === 5)
  ok(host2 !== undefined && host2.threads.length === 1 && host2.threads[0].resolved === true,
    'A9 a resolved thread still renders under its row')
  const placed2 = placeLineThreads(rows, resolvedThreads)
  ok(hasOnlyResolvedForRow(placed2, 5) === true && openCountForRow(placed2, 5) === 0, 'A10 grey badge state for that row')

  // Hunk headers are part of the render stream, in order, before their rows.
  const firstHunkAt = render.findIndex((x) => x.kind === 'hunk')
  ok(firstHunkAt === 0 && render[0].hunk.id === hunks[0].id, 'A11 the first hunk header leads the render stream')
  const secondHunkAt = render.findIndex((x) => x.kind === 'hunk' && x.hunk.id === hunks[1].id)
  const secondRowAt = render.findIndex((x) => x.kind === 'row' && x.row.index === 3)
  ok(secondHunkAt > 0 && secondHunkAt < secondRowAt, 'A12 the second hunk header sits right above its rows')
}

/* ---------------------------------------------- B: the panel renders it */

{
  ok(panel.includes('buildLineRender(') && panel.includes('lineRender.map('), 'B1 the panel renders buildLineRender output')
  ok(panel.includes('parseUnifiedDiff(file.unified)'), 'B2 the panel feeds the diff face\'s unified diff into the parser')
  ok(/data-testid="diff-line"/.test(panel), 'B3 each diff row is a named render node')
  ok(panel.includes('data-old-line={row.oldLine ?? undefined}') && panel.includes('data-new-line={row.newLine ?? undefined}'),
    'B4 every row prints BOTH line numbers')
  ok(panel.includes("row.kind === 'added' ? '+' : row.kind === 'removed' ? '−' : ' '"),
    'B5 each row carries its +/− marker')
  ok(panel.includes('data-testid="diff-hunk"'), 'B6 hunk headers render as named nodes')
  ok(panel.includes('data-testid="diff-stat"') && panel.includes('data-testid="review-ticket-id"'),
    'B7 the file header carries the +/− counts and the ticket id')
  ok(panel.includes('const lineMode = !isDocPath(path)'), 'B8 line mode is keyed off the file type')

  // threads render INSIDE the row node (under it), not in a separate pane
  const rowAt = panel.indexOf('data-testid="diff-line"')
  const threadsAt = panel.indexOf('item.threads.map((t) => (')
  const blockModeAt = panel.indexOf('data-testid="reviewer-block"')
  ok(rowAt > 0 && threadsAt > rowAt && threadsAt < blockModeAt, 'B9 row threads are printed inside the row block')
  ok(panel.includes("outdated=\"outdated — the commented line has changed (line text or hunk no longer match)\""),
    'B10 an outdated line thread is rendered with its outdated tag')

  // one thread face for both modes: no second markup, no second look
  ok(panel.includes("review-thread-box.tsx") && panel.includes('<ThreadBox key={t.id} thread={t}'),
    'B11 both modes render threads through the shared ThreadBox')
  ok(!panel.includes('data-testid="thread"') && !panel.includes('data-testid="outdated-thread"'),
    'B12 the panel carries no second thread markup (single design)')
  ok(threadBox.includes("data-testid={tag !== null ? 'outdated-thread' : 'thread'}"), 'B13 ThreadBox owns the thread/outdated anchors')
  for (const anchor of ['data-testid="resolve"', 'data-testid="reopen"', 'data-testid="reply-btn"', 'className="wb-rv-compose"']) {
    ok(threadBox.includes(anchor), `B14 ThreadBox keeps the shared affordance ${anchor}`)
  }

  // the composer for a line
  ok(panel.includes('data-testid="composer"') && panel.includes('onClick={() => addLineComment(row)}'),
    'B15 a row opens the same composer and writes a line comment')
  ok(panel.includes('toStoreLineThread(t, path)'), 'B16 line threads are persisted through the store seam with their path')
  ok(panel.includes('scopeThreads(c.result.doc.threads, path'), 'B17 a reload scopes the document to this file')

  // markdown mode is untouched
  ok(panel.includes('data-testid="reviewer-block"') && panel.includes('data-testid="hide-removed"')
    && panel.includes('data-testid="minimap-mark"') && panel.includes('data-testid="inline-marks"'),
    'B18 markdown block mode keeps its blocks / hide-removed / minimap / inline marks')
  ok(panel.includes("review-panel-model.ts") && panel.includes('toStoreThread(t, path)'),
    'B19 block mode keeps the markdown model and its own serialize seam')
  ok(panel.includes("{lineMode ? 'Line review' : 'Markdown review'} — {path}"), 'B20 the head names the active mode (English copy)')

  // navigation + empty state
  ok(panel.includes('data-testid="toc-entry"') && panel.includes('jumpToRow('), 'B21 the rail lists the hunks and jumps to a row')
  ok(panel.includes('data-testid="diff-empty"') && panel.includes('parse.reason'),
    'B22 a named empty state is rendered instead of a blank body')
  ok(panel.includes('data-testid="rail-file"'), 'B23 the rail lists the changed files in line mode too')

  // the store round-trip of the two shapes stays in one seam each
  ok(lineModel.includes('export function toStoreLineThread'), 'B24 the line serialize seam exists')
  ok(normalizeThreads([toStoreLineThread({
    id: 'x', parentId: null, anchor: { kind: 'line', side: 'new', line: 1, hunk: 'h', contextHash: 'c' },
    author: 'h', at: 1, text: 't', resolved: false, replies: [],
  })]).dropped === 1, 'B25 the block loader refuses a line thread (counted, never mis-placed)')
  ok(normalizeLineThreads([toStoreThread({
    id: 'y', parentId: null, blockIndex: 0, hash: 'h', neighbour: 'n', author: 'h', at: 1, text: 't', resolved: false, replies: [],
  })]).dropped === 1, 'B26 the line loader refuses a block thread (counted, never mis-placed)')
}

/* --------------------------------------- C: the entry from the Changes list */

{
  ok(indexSrc.includes("if (m === 'settle' || /\\.(md|markdown)$/i.test(p)) setReviewer({ ticketId, path: p })"),
    "C1 every changed-set click ('settle') opens the reviewer; markdown still routes there from any face")
  ok(indexSrc.includes('<MarkdownReviewer target={reviewer} onClose={() => setReviewer(null)}'), 'C2 the reviewer overlay is still the render site')
  ok(indexSrc.includes('onFallback={(tid, p) => { setReviewer(null); setFileViewer({ ticketId: tid, path: p, mode: \'settle\' }) }}'),
    'C3 a file without a diff offers the read-only viewer (fail-closed, named)')
  ok(indexSrc.includes("onClick={() => onOpenFile(f.path, 'settle')}"), 'C4 the Changes list rows are the entry')
  ok(indexSrc.includes('.wb-rv-line.s-added{background:var(--dsw-derive-success-bg,#dafbe1)}')
    && indexSrc.includes('.wb-rv-line.s-removed{background:var(--dsw-derive-danger-bg,#ffebe9)}'),
    'C5 added/removed rows carry the reviewer\'s own colours (no second palette)')
  ok(indexSrc.includes('aria-label="Markdown review"'), 'C6 the overlay keeps its recorded dialog label (t260905-05)')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
