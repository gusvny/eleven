#!/usr/bin/env node
/**
 * integration/t261022-14/sc_t26102214_lane_review_comments.mjs — the lane
 * review-comment store, end to end over the REAL modules (ticket t261022-14).
 *
 * Browser-free, offline seconds, never touches 3099/7233, no docker/Temporal.
 * Anchors the REAL host store (src/host/review-comments.ts) and the REAL client
 * model (src/client/review-panel-model.ts) — the same two modules the console
 * panel runs:
 *   A (acceptance b+g) comments on a heading, a paragraph, a list item and a
 *      table cell persist to <lane>/.sandbar/review-comments.json and are read
 *      back with EVERY schema field validated — reader-side evidence: the file
 *      is re-read from disk through the same reader the lane agents use (plain
 *      file read of the JSON), never the writer's echo.
 *   B (acceptance d) the block text is edited after the comment: the thread is
 *      still placed (hash miss → neighbour hit) or labelled outdated — and it
 *      NEVER disappears.
 *   C the merge-by-id path keeps resolve/reply state across reloads.
 *
 * Exit 0 = all green; any assertion failure exits 1; the product modules being
 * unimportable is ENV_FAIL exit 2 (named, not a silent pass).
 */
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const here = new URL('.', import.meta.url).pathname
const repo = join(here, '..', '..')

let ReviewComments, Model
try {
  ReviewComments = await import(join(repo, 'server/plugins/workbench/src/host/review-comments.ts'))
  Model = await import(join(repo, 'server/plugins/workbench/src/client/review-panel-model.ts'))
} catch (err) {
  console.error(`ENV_FAIL: product modules unimportable: ${err?.message ?? err}`)
  process.exit(2)
}

let passed = 0, failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const dir = await mkdtemp(join(tmpdir(), 'sc-t26102214-'))
try {
  const laneRoot = join(dir, 'lane')
  const file = ReviewComments.reviewCommentsFilePath(dir, 'lane', 'docs/design/x.md')
  ok(file !== null && file === join(laneRoot, '.sandbar', 'review-comments.json'), 'store path is <lane>/.sandbar/review-comments.json')

  /* A: four block kinds persist + schema read-back (acceptance b, g) */
  const blocks = Model.buildBlocks([
    { type: 'heading', status: 'unchanged', level: 1, newText: '# Guide', summary: 'Guide' },
    { type: 'paragraph', status: 'modified', oldText: 'old para', newText: 'new para' },
    { type: 'list-item', status: 'added', newText: '- new item' },
    { type: 'table-row', status: 'modified', oldText: '| a | b |', newText: '| a | B!' },
  ])
  const kinds = ['heading', 'paragraph', 'list-item', 'table-cell']
  const threads = kinds.map((k, i) => {
    const b = blocks.find((x) => x.type === k)
    assert(b !== undefined, `fixture has a ${k} block`)
    return {
      id: `th-${k}`, parentId: null,
      anchor: { index: b.index, hash: b.hash, neighbour: b.neighbour },
      author: 'human', at: 1760000000000 + i, text: `comment on the ${k}`, resolved: false,
      replies: [],
    }
  })
  const w = await ReviewComments.mergeReviewComments(file, 't261022-14', 'docs/design/x.md', { threads })
  ok(w.ok === true, 'A1 write of the four block-kind threads ok')

  // Reader-side evidence: plain file read of the lane JSON (the lane agents' path)
  const raw = JSON.parse(await readFile(file, 'utf8'))
  ok(raw.schema === 'review-comments-v1' && raw.ticketId === 't261022-14' && raw.path === 'docs/design/x.md'
    && typeof raw.updatedAt === 'number' && Array.isArray(raw.threads) && raw.threads.length === 4,
    'A2 document fields all present on the raw read-back')
  for (const t of raw.threads) {
    ok(typeof t.id === 'string' && t.parentId === null
      && typeof t.anchor?.index === 'number' && typeof t.anchor?.hash === 'string' && typeof t.anchor?.neighbour === 'string'
      && typeof t.author === 'string' && typeof t.at === 'number' && typeof t.text === 'string'
      && typeof t.resolved === 'boolean' && Array.isArray(t.replies),
      `A3 every field of thread ${t.id} validates`)
  }
  // and the panel-side normalize reads the same file back
  const back = Model.normalizeThreads(raw.threads)
  ok(back.threads.length === 4 && back.dropped === 0, 'A4 panel reload sees all four threads')

  /* B: block edited after the comment (acceptance d) */
  const edited = Model.buildBlocks([
    { type: 'heading', status: 'unchanged', level: 1, newText: '# Guide', summary: 'Guide' },
    { type: 'paragraph', status: 'modified', oldText: 'old para', newText: 'a much longer new paragraph now' },
    { type: 'list-item', status: 'unchanged', newText: '- new item' },
    { type: 'table-row', status: 'modified', oldText: '| a | B! |', newText: '| a | B! |' },
  ])
  const placed = Model.placeThreads(edited, back.threads)
  ok(placed.length === 4, 'B1 no thread disappears after the edit')
  const outcomes = placed.map((p) => p.resolution.kind)
  ok(outcomes.some((k) => k === 'exact') && outcomes.some((k) => k === 'neighbour'),
    `B2 mixed outcomes across the threads (${outcomes.join(',')})`)
  // force a full miss → outdated, still present
  const ghost = { ...back.threads[0], id: "th-ghost", hash: "ffffffff", neighbour: "no such neighbour" }
  const placed2 = Model.placeThreads(edited, [...back.threads, ghost])
  const g = placed2.find((p) => p.thread.id === ghost.id)
  ok(g !== undefined && g.resolution.kind === 'outdated' && g.index >= edited.length,
    'B3 full-miss thread labelled outdated at the end of the file, never dropped')

  /* C: resolve + reload keeps state */
  threads[0].resolved = true
  const w2 = await ReviewComments.mergeReviewComments(file, 't261022-14', 'docs/design/x.md', { threads })
  const re = await ReviewComments.readReviewComments(file)
  ok(w2.ok && re.ok && re.doc !== null && re.doc.threads.find((t) => t.id === threads[0].id)?.resolved === true,
    'C1 resolve survives a write-reload cycle')

  console.log(`\n${passed} passed, ${failed} failed`)
  process.exit(failed === 0 ? 0 : 1)
} finally {
  await rm(dir, { recursive: true, force: true })
}
