/**
 * tests/t261028-23-review-line-anchor.mjs — line anchors end to end at the
 * model + store layer (t261028-23):
 *   A. anchor resolution: exact, relocated (same line/text under a moved hunk),
 *      outdated (line gone / text changed) — a thread is NEVER dropped and
 *      NEVER moved to a different line;
 *   B. the model -> store serialization seam (toStoreLineThread) passes the
 *      store sanitizer and round-trips every field;
 *   C. the store round-trip of a LINE anchor through the real lane file
 *      (mergeReviewComments -> readReviewComments), invariants included
 *      (atomic write, per-file mutex, corrupt JSON refused, temp cleanup);
 *   D. a LEGACY markdown-only document (block anchors, no `path`) still loads
 *      byte-identically — the line anchor is purely additive;
 *   E. per-file scoping of one lane document (threads of several files, legacy
 *      threads belong to the document's own path);
 *   F. hostile input: every malformed shape is counted, never thrown on.
 *
 * Run: node server/plugins/workbench/tests/t261028-23-review-line-anchor.mjs
 * Pure/offline: every case writes into its own mkdtemp directory OUTSIDE any
 * repo tree; no server, no network, never touches 3099/7233.
 */
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { parseUnifiedDiff } from '../src/client/diff-rows-model.ts'
import {
  buildLineRender,
  filterLineThreads,
  hasOnlyResolvedForRow,
  normalizeLineThreads,
  openCountForRow,
  placeLineThreads,
  readLineAnchor,
  resolveLineAnchor,
  threadsForRow,
  toStoreLineThread,
} from '../src/client/review-line-model.ts'
import { scopeThreads, toStoreThread } from '../src/client/review-panel-model.ts'
import {
  REVIEW_COMMENTS_MAX_LINE,
  isSafeRelPath,
  mergeReviewComments,
  readReviewComments,
  reviewCommentsFilePath,
  sanitizeAnchor,
  sanitizeThread,
} from '../src/host/review-comments.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const DIFF = [
  '@@ -1,3 +1,3 @@',
  ' keep me',
  '-old line',
  '+new line',
  '@@ -20,2 +20,2 @@',
  ' second hunk',
  '-gone here',
  '+fresher here',
].join('\n')

function rowsOf(diff) {
  const p = parseUnifiedDiff(diff)
  if (!p.ok) throw new Error(`fixture diff did not parse: ${p.reason}`)
  return p.rows
}

function threadAt(anchor, over = {}) {
  return {
    id: 'ln-1', parentId: null, anchor, author: 'human', at: 1760000000001,
    text: 'a line comment', resolved: false, replies: [], ...over,
  }
}

/* A: resolution */
{
  const rows = rowsOf(DIFF)
  const newLine = rows[2] // added row, new line 2
  const oldLine = rows[1] // removed row, old line 2
  const anchor = { kind: 'line', side: 'new', line: newLine.newLine, hunk: newLine.hunk, contextHash: newLine.hash }

  const exact = resolveLineAnchor(rows, anchor)
  ok(exact.kind === 'exact' && exact.row === 2, 'A1 exact anchor resolves to its row')
  const moved = resolveLineAnchor(rows, { ...anchor, hunk: '@@ -1,3 +1,4 @@' })
  ok(moved.kind === 'relocated' && moved.row === 2, 'A2 hunk header moved, same line + text -> relocated (same row)')
  ok(resolveLineAnchor(rows, { ...anchor, contextHash: 'deadbeef' }).kind === 'outdated',
    'A3 different text on that line -> outdated')
  ok(resolveLineAnchor(rows, { ...anchor, line: 99 }).kind === 'outdated',
    'A4 line no longer in the diff -> outdated')
  ok(resolveLineAnchor([], anchor).kind === 'outdated', 'A5 empty diff -> outdated, no throw')

  const oldAnchor = { kind: 'line', side: 'old', line: oldLine.oldLine, hunk: oldLine.hunk, contextHash: oldLine.hash }
  ok(resolveLineAnchor(rows, oldAnchor).row === 1, 'A6 a base-side (removed line) anchor resolves on the old side')
  ok(resolveLineAnchor(rows, { ...oldAnchor, side: 'new' }).kind === 'outdated',
    'A7 the wrong side does not resolve (never moved across sides)')

  const threads = [
    threadAt(anchor, { id: 'a1', at: 3 }),
    threadAt({ ...anchor, contextHash: 'nope' }, { id: 'a2', at: 1 }),
    threadAt({ ...oldAnchor }, { id: 'a3', at: 2, resolved: true }),
  ]
  const placed = placeLineThreads(rows, threads)
  ok(placed.length === 3, 'A8 placeLineThreads never drops a thread')
  ok(placed.filter((p) => p.resolution.kind === 'outdated').length === 1, 'A9 the stale thread is outdated, not dropped')
  ok(placed[0].thread.id === 'a2' && placed[0].resolution.row === null, 'A10 placement is ordered by time, outdated kept')
  ok(threadsForRow(placed, 2).length === 1 && threadsForRow(placed, 1).length === 1, 'A11 threads group under their row')
  ok(openCountForRow(placed, 1) === 0 && hasOnlyResolvedForRow(placed, 1) === true, 'A12 badge-grey rule on a row with only resolved threads')
  ok(openCountForRow(placed, 2) === 1 && hasOnlyResolvedForRow(placed, 2) === false, 'A13 open count per row')
  ok(filterLineThreads(threads, 'open').length === 2 && filterLineThreads(threads, 'resolved').length === 1
    && filterLineThreads(threads, 'all').length === 3, 'A14 open/all/resolved filters')
}

/* A': the render grouping carries the placement decision */
{
  const p = parseUnifiedDiff(DIFF)
  const rows = p.ok ? p.rows : []
  const hunks = p.ok ? p.hunks : []
  const target = rows[3] // first row of the second hunk
  const anchor = { kind: 'line', side: 'new', line: target.newLine, hunk: target.hunk, contextHash: target.hash }
  const render = buildLineRender(rows, hunks, [
    threadAt(anchor, { id: 'r1' }),
    threadAt({ ...anchor, contextHash: 'gone' }, { id: 'r2', text: 'stale thread' }),
  ])
  const hunkHeaders = render.filter((x) => x.kind === 'hunk')
  ok(hunkHeaders.length === 2 && render[0].kind === 'hunk', 'A15 render starts with the first hunk header')
  const rowGroup = render.find((x) => x.kind === 'row' && x.row.index === 3)
  ok(rowGroup !== undefined && rowGroup.threads.length === 1 && rowGroup.threads[0].id === 'r1',
    'A16 the anchored thread is grouped under its own row')
  ok(render.every((x) => x.kind !== 'row' || x.row.index !== 0 || x.threads.length === 0),
    'A17 a thread never leaks onto a neighbouring row')
  const outdated = render.filter((x) => x.kind === 'outdated')
  ok(outdated.length === 1 && outdated[0].thread.id === 'r2', 'A18 the outdated thread is rendered at the end')
  ok(render[render.length - 1].kind === 'outdated', 'A19 outdated threads come last')
}

/* B: serialization seam + store sanitizer */
{
  const rows = rowsOf(DIFF)
  const row = rows[2]
  const anchor = { kind: 'line', side: 'new', line: row.newLine, hunk: row.hunk, contextHash: row.hash }
  const t = threadAt(anchor, { replies: [{ author: 'dev', at: 5, text: 'a reply' }] })
  const wire = toStoreLineThread(t, 'server/x.ts')
  ok(wire.anchor.kind === 'line' && wire.anchor.side === 'new' && wire.anchor.line === row.newLine
    && wire.anchor.hunk === row.hunk && wire.anchor.contextHash === row.hash, 'B1 wire anchor carries the line shape')
  ok(wire.path === 'server/x.ts' && wire.blockIndex === undefined, 'B2 the owning file is stamped on the record')
  const sanitized = sanitizeThread(wire)
  ok(sanitized !== null, 'B3 the serialized shape passes the store sanitizer')
  ok(sanitized !== null && sanitized.anchor.kind === 'line' && sanitized.anchor.line === row.newLine
    && sanitized.replies.length === 1 && sanitized.path === 'server/x.ts', 'B4 every field survives sanitize')
  const bare = normalizeLineThreads([wire])
  ok(bare.threads.length === 1 && bare.dropped === 0, 'B5 the wire shape loads back through the panel model')
  ok(toStoreLineThread(t).path === undefined, 'B6 no path key when the caller does not pass one (legacy shape)')

  ok(sanitizeAnchor({ kind: 'line', side: 'new', line: 3, hunk: 'h', contextHash: 'c' }) !== null,
    'B7 sanitizeAnchor accepts a well-formed line anchor')
  ok(sanitizeAnchor({ kind: 'line', side: 'middle', line: 3 }) === null, 'B8 a bad side is refused')
  ok(sanitizeAnchor({ kind: 'line', side: 'new', line: 0 }) === null, 'B9 line 0 is refused (lines are 1-based)')
  ok(sanitizeAnchor({ kind: 'line', side: 'new', line: REVIEW_COMMENTS_MAX_LINE + 1 }) === null, 'B10 an absurd line number is refused')
  ok(sanitizeAnchor({ kind: 'line', side: 'new', line: 2.7 }).line === 2, 'B11 a fractional line is truncated, kept')
  ok(sanitizeAnchor({ index: 0, hash: 'h' }) !== null, 'B12 the legacy block anchor shape still sanitizes')
  ok(sanitizeAnchor({ kind: 'block', index: 4, hash: 'h', neighbour: 'n' }).index === 4, 'B13 an explicit block kind still sanitizes')
  ok(sanitizeAnchor({ kind: 'weird', index: 1 }) === null, 'B14 an unknown anchor kind is refused, not guessed')
}

/* C: store round-trip of a line anchor through the real lane file */
{
  const dir = await mkdtemp(join(tmpdir(), 'rc-line-'))
  try {
    const file = join(dir, '.sandbar', 'review-comments.json')
    const rows = rowsOf(DIFF)
    const row = rows[2]
    const anchor = { kind: 'line', side: 'new', line: row.newLine, hunk: row.hunk, contextHash: row.hash }
    const wire = toStoreLineThread(threadAt(anchor, {
      id: 'ln-store', text: 'review this line', resolved: false,
      replies: [{ at: 1760000001000, author: 'dev', text: 'done' }],
    }), 'server/x.ts')
    const merged = await mergeReviewComments(file, 't261028-23', 'server/x.ts', { threads: [wire] })
    ok(merged.ok === true && merged.dropped === 0, 'C1 merge of a line-anchored thread is accepted')
    const raw = JSON.parse(await readFile(file, 'utf8'))
    ok(raw.schema === 'review-comments-v1' && raw.path === 'server/x.ts', 'C2 document header unchanged')
    const stored = raw.threads[0]
    ok(stored.anchor.kind === 'line' && stored.anchor.side === 'new' && stored.anchor.line === row.newLine
      && stored.anchor.hunk === row.hunk && stored.anchor.contextHash === row.hash, 'C3 the line anchor is on disk intact')
    ok(stored.path === 'server/x.ts' && stored.replies.length === 1, 'C4 owning path + reply persisted')
    const back = await readReviewComments(file)
    ok(back.ok === true && back.doc !== null, 'C5 the document reads back')
    const loaded = normalizeLineThreads(back.doc.threads)
    ok(loaded.threads.length === 1 && loaded.dropped === 0, 'C6 a reload keeps the thread')
    ok(loaded.threads[0].anchor.line === row.newLine && loaded.threads[0].text === 'review this line'
      && loaded.threads[0].replies[0].text === 'done', 'C7 the anchored line survives a full round-trip')
    ok(resolveLineAnchor(rows, loaded.threads[0].anchor).kind === 'exact', 'C8 the reloaded anchor still resolves exactly')

    // invariants kept: containment + mutex + no temp residue
    ok(isSafeRelPath('../escape') === false && reviewCommentsFilePath(dir, '.lane/t1', 'a/../b') === null,
      'C9 containment guard unchanged for line-mode writes')
    const conc = await Promise.all([
      mergeReviewComments(file, 't261028-23', 'server/x.ts', { threads: [toStoreLineThread(threadAt(anchor, { id: 'c1' }), 'server/x.ts')] }),
      mergeReviewComments(file, 't261028-23', 'server/x.ts', { threads: [toStoreLineThread(threadAt(anchor, { id: 'c2' }), 'server/x.ts')] }),
    ])
    ok(conc.every((r) => r.ok), 'C10 two concurrent line merges both land')
    const after = await readReviewComments(file)
    ok(after.ok && after.doc.threads.some((t) => t.id === 'c1') && after.doc.threads.some((t) => t.id === 'c2'),
      'C11 the per-file mutex still prevents a lost update')
    const sib = await readdir(join(dir, '.sandbar'))
    ok(sib.every((f) => !f.endsWith('.tmp')), 'C12 no temp-file residue after line writes')
  } finally { await rm(dir, { recursive: true, force: true }) }
}

/* C': corrupt store is still refused (409 face) and left byte-identical */
{
  const dir = await mkdtemp(join(tmpdir(), 'rc-line-'))
  try {
    const file = join(dir, '.sandbar', 'review-comments.json')
    await mkdir(join(dir, '.sandbar'), { recursive: true })
    await writeFile(file, '{not json', 'utf8')
    const anchor = { kind: 'line', side: 'new', line: 1, hunk: 'h', contextHash: 'c' }
    const r = await mergeReviewComments(file, 't', 'server/x.ts', { threads: [toStoreLineThread(threadAt(anchor))] })
    ok(r.ok === false && r.code === 'corrupt', 'C13 corrupt document still refuses the merge')
    ok((await readFile(file, 'utf8')) === '{not json', 'C14 corrupt document left byte-identical')
  } finally { await rm(dir, { recursive: true, force: true }) }
}

/* D: a legacy markdown-only document loads unchanged */
{
  const dir = await mkdtemp(join(tmpdir(), 'rc-legacy-'))
  try {
    const file = join(dir, '.sandbar', 'review-comments.json')
    await mkdir(join(dir, '.sandbar'), { recursive: true })
    const legacy = {
      schema: 'review-comments-v1',
      ticketId: 't261022-14',
      path: 'docs/design/x.md',
      updatedAt: 1760000000000,
      threads: [{
        id: 'th1', parentId: null,
        anchor: { index: 3, hash: 'a1b2c3', neighbour: 'previous block snippet' },
        author: 'host', at: 1760000000000, text: 'root comment', resolved: false,
        replies: [{ at: 1760000001000, author: 'dev', text: 'a reply' }],
      }],
    }
    await writeFile(file, JSON.stringify(legacy, null, 2), 'utf8')
    const read = await readReviewComments(file)
    ok(read.ok === true && read.doc !== null && read.doc.threads.length === 1, 'D1 a legacy markdown-only document reads')
    const t = read.doc.threads[0]
    ok(t.anchor.index === 3 && t.anchor.hash === 'a1b2c3' && t.anchor.neighbour === 'previous block snippet',
      'D2 the block anchor is untouched')
    ok(t.anchor.kind === undefined && t.path === undefined, 'D3 no new field is invented on a legacy record')
    ok(JSON.stringify(read.doc).includes('"index":3') && !JSON.stringify(t).includes('"path"'),
      'D4 the legacy record keeps its exact shape (additive only)')
    const merged = await mergeReviewComments(file, 't261022-14', 'docs/design/x.md', { threads: [] })
    ok(merged.ok === true && merged.doc.threads.length === 1, 'D5 a no-op merge keeps the legacy thread')
    const scoped = scopeThreads(merged.doc.threads, 'docs/design/x.md', merged.doc.path)
    ok(scoped.length === 1, 'D6 a legacy thread is shown for the document path it was written for')

    // Writing another file must not steal the legacy thread: the first write
    // backfills its owner from the document path, so it stays with its file.
    const lineAnchor = { kind: 'line', side: 'new', line: 7, hunk: '@@ -7 +7 @@', contextHash: 'abcd1234' }
    const wrote = await mergeReviewComments(file, 't261022-14', 'server/other.ts', {
      threads: [toStoreLineThread(threadAt(lineAnchor, { id: 'ln-other' }), 'server/other.ts')],
    })
    ok(wrote.ok === true, 'D7 a write from another file lands')
    ok(wrote.ok && wrote.doc.threads.find((t) => t.id === 'th1').path === 'docs/design/x.md',
      'D8 the legacy thread is backfilled with the file it belongs to (never drifts)')
    const afterOther = await readReviewComments(file)
    ok(afterOther.ok && scopeThreads(afterOther.doc.threads, 'docs/design/x.md', afterOther.doc.path).length === 1,
      'D9 the legacy thread is still shown for its own file after another file wrote')
    ok(afterOther.ok && scopeThreads(afterOther.doc.threads, 'server/other.ts', afterOther.doc.path).length === 1,
      'D10 the other file sees only its own thread')
  } finally { await rm(dir, { recursive: true, force: true }) }
}

/* E: per-file scoping of one lane document */
{
  const rows = rowsOf(DIFF)
  const row = rows[2]
  const a = { kind: 'line', side: 'new', line: row.newLine, hunk: row.hunk, contextHash: row.hash }
  const docThreads = [
    toStoreLineThread(threadAt(a, { id: 'for-x' }), 'server/x.ts'),
    toStoreLineThread(threadAt(a, { id: 'for-y' }), 'server/y.ts'),
    toStoreThread({ id: 'legacy-block', parentId: null, blockIndex: 0, hash: 'h', neighbour: 'n', author: 'h', at: 1, text: 'old', resolved: false, replies: [] }),
  ]
  const ownX = scopeThreads(docThreads, 'server/x.ts', 'server/y.ts')
  ok(ownX.length === 1 && ownX[0].id === 'for-x', 'E1 only this file\'s threads are shown')
  const ownY = scopeThreads(docThreads, 'server/y.ts', 'server/y.ts')
  ok(ownY.length === 2 && ownY.some((t) => t.id === 'legacy-block'), 'E2 a legacy thread belongs to the document path')
  const ownZ = scopeThreads(docThreads, 'server/z.ts', 'server/y.ts')
  ok(ownZ.length === 0, 'E3 another file\'s threads never leak into this file')
  ok(scopeThreads('not an array', 'a', 'a').length === 0, 'E4 hostile threads payload -> empty, no throw')
}

/* F: hostile input is counted, never thrown on */
{
  const hostile = [
    null, 42, 'str', [], {}, { id: '' }, { id: 'x' },
    { id: 'y', anchor: { kind: 'line', side: 'new', line: 0 } },
    { id: 'z', anchor: { kind: 'line', side: 'nope', line: 3 } },
    { id: 'w', anchor: { index: 1, hash: 'h' } },
    { id: 'v', anchor: { kind: 'line', side: 'new', line: 4, hunk: 'h', contextHash: 'c' } },
    { id: 'v', anchor: { kind: 'line', side: 'new', line: 5, hunk: 'h', contextHash: 'c' } },
  ]
  const n = normalizeLineThreads(hostile)
  ok(n.threads.length === 1 && n.threads[0].id === 'v' && n.threads[0].anchor.line === 4,
    `F1 only the first well-formed line thread survives (kept ${n.threads.length})`)
  ok(n.dropped === hostile.length - 1, `F2 every unusable entry is counted (${n.dropped})`)
  ok(normalizeLineThreads({ not: 'an array' }).threads.length === 0, 'F3 non-array payload -> empty, no throw')
  ok(readLineAnchor({ kind: 'line', side: 'old', line: 1 }) !== null && readLineAnchor({ index: 1 }) === null,
    'F4 readLineAnchor accepts only the line shape')
  ok(buildLineRender([], [], []).length === 0, 'F5 an empty diff renders nothing')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
