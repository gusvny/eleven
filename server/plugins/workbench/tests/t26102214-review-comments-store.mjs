/**
 * tests/t26102214-review-comments-store.mjs — lane-file comment store UT
 * (t261022-14 acceptance g: the schema is asserted by a test that writes and
 * reads back every field; plus the fault-mode table rows of the plan §F and
 * the arbitrate-gen0 CF2 regression: the panel's model shape must go through
 * toStoreThread before it is PUT).
 *
 * Run: node server/plugins/workbench/tests/t26102214-review-comments-store.mjs
 * REWORK NOTE: dropped by settles a21f4d00/6846bb14/bd27d799 (the settle
 * followed the incomplete stage receipts — see arbitrate gen3 root cause);
 * recreated with the reviewed, byte-stable suite.
 * Pure offline: every case writes into its own mkdtemp directory OUTSIDE any
 * repo tree, never touches 3099/7233.
 */
import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, readdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  REVIEW_COMMENTS_MAX_BYTES,
  isSafeRelPath,
  mergeReviewComments,
  readReviewComments,
  reviewCommentsFilePath,
  sanitizeDoc,
  sanitizeThread,
} from '../src/host/review-comments.ts'
import { normalizeThreads, toStoreThread } from '../src/client/review-panel-model.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* A: path guards */
{
  ok(isSafeRelPath('docs/design/x.md'), 'A1 safe rel path accepted')
  ok(!isSafeRelPath('../escape.md'), 'A2 dotdot refused')
  ok(!isSafeRelPath('/abs/x.md'), 'A3 absolute refused')
  ok(!isSafeRelPath('~root/x'), 'A4 tilde refused')
  ok(!isSafeRelPath('a\0b'), 'A5 NUL refused')
  ok(!isSafeRelPath(''), 'A6 empty refused')
  const repo = '/repo'
  ok(reviewCommentsFilePath(repo, '.lane/t1', 'docs/a.md') !== null, 'A7 lane inside repo accepted')
  ok(reviewCommentsFilePath(repo, '/etc', 'x.md') === null, 'A8 absolute lane root refused')
  ok(reviewCommentsFilePath(repo, '../outside', 'x.md') === null, 'A9 escaping lane root refused')
  ok(reviewCommentsFilePath(repo, '.lane/t1', '../evil.md') === null, 'A10 traversal in file path refused')
}

/* B: schema round-trip — every field (acceptance g) */
{
  const dir = await mkdtemp(join(tmpdir(), 'rc-store-'))
  try {
    const file = join(dir, '.sandbar', 'review-comments.json')
    const thread = {
      id: 'th1', parentId: null,
      anchor: { index: 3, hash: 'a1b2c3', neighbour: 'previous block snippet' },
      author: 'host', at: 1760000000000, text: 'root comment', resolved: false,
      replies: [{ at: 1760000001000, author: 'dev', text: 'a reply' }],
    }
    const r1 = await mergeReviewComments(file, 't261022-14', 'docs/design/x.md', { threads: [thread] })
    ok(r1.ok === true, 'B1 first merge ok')
    const raw = JSON.parse(await readFile(file, 'utf8'))
    ok(raw.schema === 'review-comments-v1', 'B2 schema field')
    ok(raw.ticketId === 't261022-14', 'B3 ticketId field')
    ok(raw.path === 'docs/design/x.md', 'B4 path field')
    ok(typeof raw.updatedAt === 'number' && raw.updatedAt > 0, 'B5 updatedAt field')
    ok(Array.isArray(raw.threads) && raw.threads.length === 1, 'B6 threads array')
    const t = raw.threads[0]
    ok(t.id === 'th1' && t.parentId === null, 'B7 thread id/parentId')
    ok(t.anchor.index === 3 && t.anchor.hash === 'a1b2c3' && t.anchor.neighbour === 'previous block snippet', 'B8 anchor index/hash/neighbour')
    ok(t.author === 'host' && t.at === 1760000000000 && t.text === 'root comment' && t.resolved === false, 'B9 author/at/text/resolved')
    ok(t.replies.length === 1 && t.replies[0].text === 'a reply' && t.replies[0].author === 'dev', 'B10 reply fields')
    const r2 = await readReviewComments(file)
    ok(r2.ok && r2.doc !== null && r2.doc.threads[0].id === 'th1' && r2.doc.threads[0].replies.length === 1, 'B11 reload keeps thread + reply')
  } finally { await rm(dir, { recursive: true, force: true }) }
}

/* C: merge semantics */
{
  const dir = await mkdtemp(join(tmpdir(), 'rc-store-'))
  try {
    const file = join(dir, '.sandbar', 'review-comments.json')
    await mergeReviewComments(file, 't1', 'a.md', { threads: [{ id: 'th1', anchor: { index: 0, hash: 'h' }, text: 'v1', resolved: false, parentId: null }] })
    const r = await mergeReviewComments(file, 't1', 'a.md', {
      threads: [
        { id: 'th1', anchor: { index: 0, hash: 'h' }, text: 'v1', resolved: true, parentId: null, replies: [{ at: 1, author: 'x', text: 'r' }] },
        { id: 'th2', anchor: { index: 9, hash: 'h9' }, text: 'second', resolved: false, parentId: null },
      ],
    })
    ok(r.ok && r.doc.threads.length === 2, 'C1 merge adds a thread')
    const back = await readReviewComments(file)
    const th1 = back.doc.threads.find((t) => t.id === 'th1')
    ok(th1.resolved === true && th1.replies.length === 1, 'C2 resolve + reply persisted (last write wins per thread)')
    const deep = join(dir, 'nested', 'lane', '.sandbar', 'review-comments.json')
    const r3 = await mergeReviewComments(deep, 't1', 'a.md', { threads: [] })
    ok(r3.ok === true, 'C3 mkdir -p on missing .sandbar dir')
    const r4 = await mergeReviewComments(file, 't1', 'a.md', { threads: [{ nonsense: true }, { id: 'th3', anchor: { index: 1, hash: 'h' }, text: 'ok' }] })
    ok(r4.ok && r4.dropped === 1 && r4.doc.threads.some((t) => t.id === 'th3'), 'C4 unusable entry counted, usable one kept')
  } finally { await rm(dir, { recursive: true, force: true }) }
}

/* D: fault modes */
{
  const dir = await mkdtemp(join(tmpdir(), 'rc-store-'))
  try {
    const file = join(dir, '.sandbar', 'review-comments.json')
    const r0 = await readReviewComments(file)
    ok(r0.ok && r0.doc === null, 'D1 missing file reads as ok/empty')
    await mkdir(join(dir, '.sandbar'), { recursive: true })
    await writeFile(file, '{not json', 'utf8')
    const r1 = await readReviewComments(file)
    ok(r1.ok === false && /not valid JSON/.test(r1.reason), 'D2 corrupt JSON named by GET-shaped read')
    const r2 = await mergeReviewComments(file, 't1', 'a.md', { threads: [] })
    ok(r2.ok === false && r2.code === 'corrupt', 'D3 PUT refuses to merge into corrupt file')
    ok((await readFile(file, 'utf8')) === '{not json', 'D4 corrupt file left byte-identical (no silent overwrite)')
    await writeFile(file, '[1,2]', 'utf8')
    const r3 = await readReviewComments(file)
    ok(r3.ok === false && /not a JSON object/.test(r3.reason), 'D5 array-shaped file refused')
    await writeFile(file, JSON.stringify({ schema: 'review-comments-v1', ticketId: 't', path: 'p', updatedAt: 1, threads: [] }), 'utf8')
    const many = []
    for (let i = 0; i < 500; i++) many.push({ id: `t${i}`, anchor: { index: i, hash: 'h' }, text: 'y'.repeat(4000), parentId: null })
    const r4 = await mergeReviewComments(file, 't1', 'a.md', { threads: many })
    ok(r4.ok === false && r4.code === 'oversize', 'D6 over-cap merge refused')
    ok((await readFile(file, 'utf8')).length < REVIEW_COMMENTS_MAX_BYTES, 'D7 existing file untouched after refusal')
    for (const hostile of [null, undefined, 42, 'str', [], {}, { id: '' }, { id: 'x' }, { id: 'y', anchor: { index: -1, hash: 'h' } }, { id: 'z', anchor: { index: 1.9, hash: 'h' } }]) {
      ok(typeof sanitizeThread(hostile) !== 'undefined', `D8 sanitize survives ${JSON.stringify(hostile)?.slice(0, 20) ?? String(hostile)}`)
    }
    ok(sanitizeThread({ id: 'z', anchor: { index: 1.9, hash: 'h' } }) !== null, 'D9 fractional index truncated, kept')
    ok(sanitizeDoc('not-an-object', 't', 'p').dropped >= 0, 'D10 sanitizeDoc on garbage does not throw')
    const conc = await Promise.all([
      mergeReviewComments(file, 't1', 'a.md', { threads: [{ id: 'c1', anchor: { index: 0, hash: 'h' }, text: 'one', parentId: null }] }),
      mergeReviewComments(file, 't1', 'a.md', { threads: [{ id: 'c2', anchor: { index: 1, hash: 'h' }, text: 'two', parentId: null }] }),
    ])
    ok(conc.every((r) => r.ok), 'D11 both concurrent merges ok')
    const after = await readReviewComments(file)
    ok(after.doc !== null && after.doc.threads.some((t) => t.id === 'c1') && after.doc.threads.some((t) => t.id === 'c2'), 'D12 no lost update under the per-file mutex')
    const sib = await readdir(join(dir, '.sandbar'))
    ok(sib.every((f) => !f.endsWith('.tmp')), 'D13 no temp-file residue')
  } finally { await rm(dir, { recursive: true, force: true }) }
}

/* E: CF2 regression — the panel shape must be serialized, not PUT raw */
{
  const panelThread = {
    id: 'th-1', parentId: null, blockIndex: 1, hash: 'abc', neighbour: 'prev',
    author: 'human', at: 1760000000001, text: 'x', resolved: false, replies: [],
  }
  ok(sanitizeThread(panelThread) === null, 'E1 raw model shape IS refused by the store (the CF2 defect)')
  ok(normalizeThreads([panelThread]).dropped === 1, 'E2 raw model shape dropped by the panel loader too')
  const wired = toStoreThread(panelThread)
  ok(sanitizeThread(wired) !== null, 'E3 toStoreThread output passes the store sanitizer')
  const back = normalizeThreads([wired])
  ok(back.threads.length === 1 && back.dropped === 0, 'E4 serialized shape round-trips the panel loader')
  const rt = back.threads[0]
  ok(rt.blockIndex === 1 && rt.hash === 'abc' && rt.neighbour === 'prev' && rt.id === 'th-1'
    && rt.author === 'human' && rt.text === 'x' && rt.resolved === false && rt.parentId === null,
    'E5 every field survives the serialize → load round-trip')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
