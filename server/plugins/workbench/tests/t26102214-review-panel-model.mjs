/**
 * tests/t26102214-review-panel-model.mjs — the reviewer panel's pure model UT
 * (t261022-14): block building incl. table-cell subdivision, word-level inline
 * marks, anchor resolution (exact / neighbour / outdated, never drop), thread
 * filters + badge-grey rule, TOC, minimap, hostile-input cases, and the
 * arbitrate-gen0 CF2 serialization seam (toStoreThread).
 *
 * Run: node server/plugins/workbench/tests/t26102214-review-panel-model.mjs
 * REWORK NOTE: dropped by settles a21f4d00/6846bb14/bd27d799; recreated with
 * the reviewed, byte-stable suite.
 * Pure functions, offline, never touches 3099/7233.
 */
import assert from 'node:assert/strict'
import {
  blockHash,
  buildBlocks,
  buildMinimap,
  buildToc,
  filterThreads,
  hasOnlyResolved,
  normalizeThreads,
  openCount,
  placeThreads,
  resolveAnchor,
  threadsForBlock,
  toStoreThread,
  wordDiff,
} from '../src/client/review-panel-model.ts'
import { sanitizeThread } from '../src/host/review-comments.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* A: block building */
{
  const raw = [
    { type: 'heading', status: 'unchanged', level: 1, newText: '# Title', summary: 'Title' },
    { type: 'paragraph', status: 'added', newText: 'new paragraph' },
    { type: 'paragraph', status: 'removed', oldText: 'old paragraph' },
    { type: 'paragraph', status: 'modified', oldText: 'the quick brown fox', newText: 'the quick red fox' },
    { type: 'table-head', status: 'modified', oldText: '| a | b |', newText: '| a | B |' },
    { type: 'table-row', status: 'added', newText: '| x | y | z |' },
    { type: 'list-item', status: 'unchanged', level: 1, newText: '- item' },
  ]
  const blocks = buildBlocks(raw)
  ok(blocks.length === 10, `A1 table rows subdivided into cells (${blocks.length} blocks)`)
  ok(blocks.map((b) => b.index).every((v, i) => v === i), 'A2 indexes dense 0..n-1')
  const cells = blocks.filter((b) => b.type === 'table-cell')
  ok(cells.length === 5, 'A3 five cells (2 head + 3 row)')
  ok(cells[0].text === 'a' && cells[0].status === 'unchanged', 'A4 head cell a unchanged')
  ok(cells[1].text === 'B' && cells[1].status === 'modified' && cells[1].inlineOps.length > 0, 'A5 head cell B modified with inline ops')
  ok(cells[1].cell.col === 1, 'A6 cell carries its column')
  ok(blocks[6].text === 'x' && blocks[6].status === 'added', 'A7 added row -> every cell added')
  ok(blocks[2].status === 'removed' && blocks[2].text === 'old paragraph', 'A8 removed block keeps old text')
  const mod = blocks[3]
  ok(mod.status === 'modified' && mod.inlineOps.some((o) => o.del?.includes('brown')) && mod.inlineOps.some((o) => o.add?.includes('red')), 'A9 word-level marks on modified paragraph')
  ok(blocks.every((b) => b.hash.length === 8 && typeof b.neighbour === 'string'), 'A10 every block carries hash + neighbour snippet')
  ok(blockHash('abc') === blockHash('abc') && blockHash('abc') !== blockHash('abd'), 'A11 hash deterministic and text-sensitive')
  ok(buildBlocks('not an array').length === 0 && buildBlocks([null, 42, {}]).length === 0, 'A12 hostile raw blocks never throw')
}

/* B: word diff */
{
  ok(JSON.stringify(wordDiff('same', 'same')) === JSON.stringify([{ add: 'same' }]), 'B1 equal text -> single aligned run')
  const ops = wordDiff('one two three', 'one TWO three')
  ok(ops.some((o) => o.del?.includes('two')) && ops.some((o) => o.add?.includes('TWO')), 'B2 word swap marked both sides')
  ok(wordDiff('', 'brand new').length > 0, 'B3 empty old -> all inserts')
  ok(wordDiff('gone', '').length > 0, 'B4 empty new -> all deletes')
  ok(wordDiff('', '').length === 0, 'B5 both empty -> no runs')
  ok(wordDiff('a b c', 'a b c d').some((o) => o.add === ' d'), 'B6 append detected')
}

/* C: threads + anchors */
{
  const raw = [
    { id: 't1', parentId: null, anchor: { index: 0, hash: 'aaa', neighbour: 'n0' }, author: 'h', at: 2, text: 'root', resolved: false, replies: [{ author: 'd', at: 3, text: 'reply' }] },
    { id: 't2', parentId: 't1', anchor: { index: 1, hash: 'bbb', neighbour: 'n1' }, author: 'x', at: 1, text: 'second', resolved: true },
    { id: '', anchor: {} },
    null,
    { id: 't3', anchor: { index: -5, hash: 'h' } },
    { id: 't1', anchor: { index: 0, hash: 'z' } },
  ]
  const { threads, dropped } = normalizeThreads(raw)
  ok(threads.length === 2 && dropped === 4, `C1 normalize keeps 2, counts ${dropped} drops`)
  ok(threads[0].replies.length === 1 && threads[0].parentId === null, 'C2 reply nesting + root parentId null')
  ok(openCount(threads, 0) === 1 && openCount(threads, 1) === 0, 'C3 open counts')
  ok(hasOnlyResolved(threads, 1) && !hasOnlyResolved(threads, 0), 'C4 badge-grey rule (only resolved)')
  ok(filterThreads(threads, 'open').length === 1 && filterThreads(threads, 'resolved').length === 1 && filterThreads(threads, 'all').length === 2, 'C5 filters open/all/resolved')

  const blocks = buildBlocks([
    { type: 'heading', status: 'unchanged', level: 1, newText: '# T', summary: 'T' },
    { type: 'paragraph', status: 'unchanged', newText: 'para two', summary: 'para two' },
    { type: 'paragraph', status: 'modified', oldText: 'old text here', newText: 'new text here' },
  ])
  ok(resolveAnchor(blocks, { ...threads[0], blockIndex: 99, hash: blocks[2].hash, neighbour: '' }).kind === 'exact', 'C6 exact hash wins over a wrong index')
  ok(resolveAnchor(blocks, { blockIndex: 1, hash: 'deadbeef', neighbour: blocks[1].neighbour }).kind === 'neighbour', 'C7 hash miss falls back to index+neighbour')
  ok(resolveAnchor(blocks, { blockIndex: 2, hash: 'deadbeef', neighbour: blocks[1].neighbour }).kind === 'neighbour', 'C8 neighbour probed on adjacent blocks')
  const placed = placeThreads(blocks, [{ ...threads[0], hash: 'zzz', neighbour: 'gone' }, { ...threads[1], hash: blocks[0].hash, neighbour: '' }])
  ok(placed.length === 2, 'C9 placeThreads never drops')
  ok(placed[1].resolution.kind === 'outdated' && placed[1].index >= blocks.length, 'C10 outdated thread ranked after the document')
  ok(placed[0].resolution.kind === 'exact' && placed[0].index === 0, 'C11 exact thread placed at its block')
}

/* D: TOC + minimap */
{
  const blocks = buildBlocks([
    { type: 'heading', status: 'unchanged', level: 1, newText: '# One' },
    { type: 'paragraph', status: 'unchanged', newText: 'p' },
    { type: 'heading', status: 'modified', level: 2, oldText: '## Two', newText: '## Two!' },
    { type: 'heading', status: 'unchanged', level: 3, newText: '### deep' },
  ])
  const toc = buildToc(blocks)
  ok(toc.length === 2 && toc[0].level === 1 && toc[1].level === 2, 'D1 TOC lists only h1/h2')
  ok(toc[0].text === 'One' && toc[1].text === 'Two!', 'D2 TOC strips the # prefix')
  const threads = normalizeThreads([
    { id: 'a', anchor: { index: 2, hash: blocks[2].hash } },
    { id: 'b', anchor: { index: 1, hash: 'x' } },
    { id: 'c', anchor: { index: 0, hash: 'x' }, resolved: true },
  ]).threads
  const map = buildMinimap(blocks, threads)
  const at = (i) => map.find((m) => m.index === i)
  ok(at(2).status === 'modified' && at(2).open === 1, 'D3 changed block marked with open count')
  ok(at(1).status === 'unchanged' && at(1).open === 1, 'D4 commented-only block still marked')
  ok(at(0).onlyResolved === true, 'D5 only-resolved block flagged grey')
  ok(map.every((m) => m.status !== 'unchanged' || m.open > 0 || m.onlyResolved), 'D6 no bare unchanged marks')
}

/* E: hostile inputs */
{
  ok(buildBlocks([{ type: 'paragraph', status: 'weird', newText: 42 }])[0].status === 'unchanged', 'E1 unknown status -> unchanged')
  ok(normalizeThreads({ not: 'an array' }).threads.length === 0, 'E2 non-array threads -> empty, no throw')
  ok(normalizeThreads([{ id: 'x', anchor: { index: 1e9, hash: 'h' } }]).threads[0].blockIndex === 1e9, 'E3 huge index kept (renders outdated)')
  ok(resolveAnchor([], { blockIndex: 0, hash: 'h', neighbour: 'n' }).kind === 'outdated', 'E4 resolve on empty document -> outdated')
  ok(placeThreads([], []).length === 0, 'E5 place on empty -> empty')
  ok(buildToc(buildBlocks([{ type: 'heading', status: 'added', newText: '# ' }])).length === 1, 'E6 heading without a level defaults to h1')
}

/* F: CF2 serialization seam */
{
  const t = {
    id: 'th-9', parentId: null, blockIndex: 4, hash: 'cafe12', neighbour: 'above snippet',
    author: 'human', at: 1760000000009, text: 'a comment', resolved: true,
    replies: [{ author: 'dev', at: 1760000000010, text: 'a reply' }],
  }
  const s = toStoreThread(t)
  ok(s.anchor !== undefined && s.anchor.index === 4 && s.anchor.hash === 'cafe12' && s.anchor.neighbour === 'above snippet'
    && s.blockIndex === undefined, 'F1 wire shape carries anchor{index,hash,neighbour}, not the flat fields')
  ok(sanitizeThread(s) !== null, 'F2 serialized shape passes the store sanitizer (the CF2 defect is closed)')
  const back = normalizeThreads([s])
  ok(back.threads.length === 1 && back.dropped === 0, 'F3 serialized shape loads back through the panel')
  const rt = back.threads[0]
  ok(rt.id === 'th-9' && rt.blockIndex === 4 && rt.hash === 'cafe12' && rt.neighbour === 'above snippet'
    && rt.author === 'human' && rt.at === 1760000000009 && rt.text === 'a comment'
    && rt.resolved === true && rt.replies.length === 1 && rt.replies[0].text === 'a reply'
    && rt.parentId === null, 'F4 every field survives serialize -> load')
  const child = toStoreThread({ ...t, id: 'th-10', parentId: 'th-9' })
  ok(child.parentId === 'th-9' && sanitizeThread(child) !== null, 'F5 nested thread keeps parentId on the wire')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
