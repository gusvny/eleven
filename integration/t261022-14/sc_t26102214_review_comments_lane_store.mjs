#!/usr/bin/env node
/**
 * sc_t26102214_review_comments_lane_store.mjs — t261022-14, offline L3 leg.
 *
 * User story: a reviewer's per-block comments on a changed markdown doc are
 * stored ONLY in the ticket lane file <lane>/.sandbar/review-comments.json
 * (ticket requirement 6: "the lane is the store"). The lane agents read that
 * same file back, so the schema, the anchor-survival rules and the failure
 * faces of the store are user-perceivable contracts, not internals.
 *
 * Grey-box L3, the REAL delivered modules (server/plugins/workbench/src/host/
 * review-comments.ts + src/client/review-panel-model.ts) under node >=22.18
 * native type-stripping, temp lane roots on disk, offline seconds, zero
 * docker/Temporal/browser, never touches 3099/7233. Bound to the delivered
 * PUBLIC module contracts: readReviewComments(file), mergeReviewComments(file,
 * ticketId, relPath, incoming), isSafeRelPath / reviewCommentsFilePath,
 * resolveAnchor(blocks, thread) / placeThreads — these are the seams the host
 * route and the panel consume; a refactor that keeps them must stay green.
 *
 * Cases (acceptance mapping):
 *   S1 route seam is real on BOTH sides (KI-01M4HMCZAM4ZBC2CKN15HDBZHP
 *      dead-button guard): the GET/PUT review-comments route literal exists in
 *      the REAL server dispatch (node.ts) AND in the REAL client source, and
 *      the dispatch references the store module — a client path without a
 *      server door is the KI's exact shape.
 *   S2 lane-file schema read-back (acceptance g): write through the real
 *      store, read the FILE BACK with a plain read (reader side, not the
 *      writer's receipt) and validate EVERY declared field: ticketId, path,
 *      threads[id, parentId|null, anchor{index, hash, neighbour}, author, at,
 *      text, resolved]; a second merge keeps existing threads and updates a
 *      known id in place (thread-granularity last-write-wins).
 *   S3 per-block-kind persistence (acceptance b, store half): comments
 *      anchored to a heading, a paragraph, a list item and a table CELL each
 *      persist with their own block index and survive a fresh read.
 *   S4 anchor survival (acceptance d, store half): exact hash hit resolves in
 *      place; after a text edit the hash misses and the neighbour snippet
 *      remaps the thread (including a ±1 index shift); when both miss the
 *      thread is outdated and placeThreads STILL returns it, ranked to the end
 *      — never silently dropped (requirement 7).
 *   S5 failure surfaces of the write path: corrupt lane JSON reads as a named
 *      failure and a merge REFUSES with code 'corrupt' leaving the file
 *      byte-identical; traversal-shaped paths are rejected by the path guard;
 *      an over-cap merge refuses with code 'oversize' and the existing file is
 *      never truncated; a missing .sandbar/ dir is created on write and a
 *      missing file reads as ok/doc-null (normal empty state); a forced write
 *      error returns code 'io' and leaves NO temp residue.
 *   S6 hostile lane documents never throw the reader and never lose threads
 *      silently: unsalvageable entries (no id, negative index) are dropped
 *      WITH a named count; sound threads survive; unknown parent ids do not
 *      crash anything.
 *
 * Three states (t260904-12, no SKIP in-gate): last line
 * SUMMARY pass=N fail=K env_fail=E na=W; fail>0 or all-na = exit 1;
 * env_fail>0 = exit 2. node missing or <22 = ENV_FAIL exit 2.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, chmodSync } from 'node:fs'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = resolve(fileURLToPath(new URL('../../', import.meta.url)))
const STORE_TS = join(REPO, 'server/plugins/workbench/src/host/review-comments.ts')
const MODEL_TS = join(REPO, 'server/plugins/workbench/src/client/review-panel-model.ts')
const NODE_TS = join(REPO, 'server/plugins/workbench/node.ts')
const PANEL_TSX = join(REPO, 'server/plugins/workbench/src/client/review-panel.tsx')
const INDEX_TSX = join(REPO, 'server/plugins/workbench/src/client/index.tsx')

const NODE_MAJOR = Number(process.versions.node.split('.')[0])
const NODE_MINOR = Number(process.versions.node.split('.')[1] || 0)
if (!(NODE_MAJOR > 22 || (NODE_MAJOR === 22 && NODE_MINOR >= 18))) {
  console.log(`[ENV_FAIL] node >=22.18 (native type-stripping) required, got ${process.versions.node}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

let passed = 0, failed = 0
function ok(cond, label) { if (cond) { passed++; console.log(`  ok ${label}`) } else { failed++; console.log(`  FAIL ${label}`) } }
function section(t) { console.log(`\n== ${t}`) }
function summarize() {
  console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
  process.exit(failed > 0 ? 1 : 0)
}

// Delivered-module absence is a FAIL with a name (TDD signal), never a skip.
let store = null, model = null
try {
  store = await import('file://' + STORE_TS)
  model = await import('file://' + MODEL_TS)
} catch (e) {
  console.log(`FAIL delivered review modules not loadable: ${String(e).slice(0, 300)}`)
  failed++
  summarize()
}

function makeLaneRoot(tag) {
  const root = mkdtempSync(join(tmpdir(), `t26102214-lane-${tag}-`))
  process.on('exit', () => { try { rmSync(root, { recursive: true, force: true }) } catch {} })
  return root
}
const LANE_FILE_NAME = join('.sandbar', 'review-comments.json')
function laneFile(root) { return join(root, LANE_FILE_NAME) }
function readStore(root) { return JSON.parse(readFileSync(laneFile(root), 'utf8')) }

const TICKET = 't261022-14'
const DOC = 'docs/design/notes.md'
function thread(over) {
  return {
    id: 'th-' + Math.random().toString(36).slice(2, 8), parentId: null,
    anchor: { index: 0, hash: 'h0', neighbour: 'intro sentence' },
    author: 'reviewer', at: 1761108000000, text: 'please reword', resolved: false,
    ...over,
  }
}

/* S1 — the route door exists on both sides (dead-button guard). */
section('S1 route seam registered on server AND client sources')
try {
  const nodeSrc = readFileSync(NODE_TS, 'utf8')
  const clientSrc = readFileSync(PANEL_TSX, 'utf8') + '\n' + readFileSync(INDEX_TSX, 'utf8')
  ok(/review-comments/.test(nodeSrc), 'S1 server dispatch names the review-comments route')
  ok(/review-comments/.test(clientSrc), 'S1 client source names the same route face')
  ok(/PUT/.test(nodeSrc) && /GET/.test(nodeSrc), 'S1 route carries GET and PUT methods')
  ok(/review-comments(\.ts|['"])/.test(nodeSrc) || /review-comments/.test(nodeSrc), 'S1 server dispatch references the store module face')
} catch (e) {
  ok(false, 'S1 source faces readable: ' + String(e).slice(0, 160))
}

/* S1b — settle-survival guard: the seam must exist in the COMMITTED tree, and
 * the ticket's carrier files must not sit modified-but-unsettled in the
 * worktree. Four consecutive worker settles (a21f4d00, cc1afc9e-shaped lineage:
 * 6846bb14, bd27d799) committed the client half while dropping node.ts /
 * tests/, leaving a dead-button tree that imports cleanly. Judged on
 * `git show HEAD:<path>` (the tree the gate certifies), never the worktree. */
section('S1b settle survival: registration lives in the COMMITTED tree')
{
  const { execFileSync } = await import('node:child_process')
  const git = (args) => { try { return execFileSync('git', args, { cwd: REPO, encoding: 'utf8', timeout: 10000 }) } catch { return '' } }
  const rel = (p) => p.slice(REPO.length + 1)
  const headHas = (p, re) => re.test(git(['show', `HEAD:${rel(p)}`]))
  ok(headHas(NODE_TS, /review-comments/), 'S1b committed node.ts names the review-comments route')
  ok(headHas(NODE_TS, /review-comments-routes/), 'S1b committed node.ts wires the routes module')
  ok(headHas(join(REPO, 'server/plugins/workbench/src/host/review-comments-routes.ts'), /handleReviewComments|export/), 'S1b committed routes handler module present')
  ok(headHas(join(REPO, 'server/plugins/workbench/tests/t26102214-review-comments-store.mjs'), /review-comments/), 'S1b committed L1 store test present')
  ok(headHas(join(REPO, 'server/plugins/workbench/tests/t26102214-review-panel-model.mjs'), /review-panel-model|review/), 'S1b committed L1 model test present')
  // modified-but-unsettled carriers: a dirty worktree on these paths after the
  // settle means the NEXT commit is already amputated — fail loud here
  const dirty = git(['status', '--porcelain', '--',
    rel(NODE_TS),
    'server/plugins/workbench/tests/t26102214-review-comments-store.mjs',
    'server/plugins/workbench/tests/t26102214-review-panel-model.mjs',
    'server/plugins/workbench/src/host/review-comments-routes.ts'])
  ok(dirty.trim() === '', 'S1b no ticket carrier file sits modified-but-unsettled' + (dirty.trim() ? `: ${dirty.trim().split('\n').join(' | ').slice(0, 200)}` : ''))
}

/* S2 — schema round-trip, every field, reader side (acceptance g). */
section('S2 lane-file schema read-back (acceptance g)')
{
  const lane = makeLaneRoot('schema')
  const file = laneFile(lane)
  try {
    const th = thread({ anchor: { index: 3, hash: 'abc123', neighbour: 'prev para' } })
    const r1 = await store.mergeReviewComments(file, TICKET, DOC, { threads: [th] })
    ok(r1 && r1.ok === true, 'S2 first merge succeeds')
    const doc = readStore(lane) // plain reader-side read of the real file
    ok(doc.ticketId === TICKET, 'S2 ticketId persisted verbatim')
    ok(doc.path === DOC, 'S2 doc path persisted verbatim')
    ok(typeof doc.updatedAt === 'number' && doc.updatedAt > 0, 'S2 updatedAt stamp persisted')
    ok(Array.isArray(doc.threads) && doc.threads.length === 1, 'S2 threads array persisted')
    const t = doc.threads[0]
    ok(t.id === th.id, 'S2 thread id persisted')
    ok(t.parentId === null, 'S2 parentId null persisted as null (not omitted)')
    ok(t.anchor && t.anchor.index === 3 && t.anchor.hash === 'abc123' && t.anchor.neighbour === 'prev para', 'S2 anchor {index, hash, neighbour} persisted in full')
    ok(t.author === 'reviewer' && t.text === 'please reword', 'S2 author + text persisted')
    ok(t.at === th.at, 'S2 timestamp persisted')
    ok(t.resolved === false, 'S2 resolved persisted as boolean false')
    ok(Array.isArray(t.replies), 'S2 replies array present (thread = root + nested replies, req 5)')
    // merge keeps identity: second PUT-shaped call updates the known id and adds a new one
    const r2 = await store.mergeReviewComments(file, TICKET, DOC, { threads: [thread({ id: th.id, text: 'edited root' }), thread()] })
    ok(r2.ok === true, 'S2 second merge succeeds')
    const doc2 = readStore(lane)
    ok(doc2.threads.length === 2, 'S2 second merge keeps existing thread and adds the new one')
    const edited = doc2.threads.find((x) => x.id === th.id)
    ok(edited && edited.text === 'edited root', 'S2 re-merge of a known thread id updates in place (last-write-wins per thread)')
    // read face agrees with disk
    const read = await store.readReviewComments(file)
    ok(read.ok === true && read.doc && read.doc.threads.length === 2, 'S2 read face agrees with the file on disk')
  } catch (e) {
    ok(false, 'S2 round-trip: ' + String(e).slice(0, 240))
  }
}

/* S3 — per-block-kind anchors persist (heading/paragraph/list-item/table cell). */
section('S3 per-block-kind persistence (acceptance b, store half)')
{
  const lane = makeLaneRoot('kinds')
  const file = laneFile(lane)
  try {
    const kinds = [
      thread({ id: 'th-heading', anchor: { index: 0, hash: 'k0', neighbour: '' } }),
      thread({ id: 'th-para', anchor: { index: 1, hash: 'k1', neighbour: 'heading text' } }),
      thread({ id: 'th-list', anchor: { index: 5, hash: 'k5', neighbour: 'para text' } }),
      thread({ id: 'th-cell', anchor: { index: 9, hash: 'k9', neighbour: 'row text' } }),
    ]
    await store.mergeReviewComments(file, TICKET, DOC, { threads: kinds })
    const doc = readStore(lane)
    const byId = new Map(doc.threads.map((t) => [t.id, t]))
    for (const k of ['th-heading', 'th-para', 'th-list', 'th-cell']) {
      const t = byId.get(k)
      ok(!!t && Number.isInteger(t.anchor.index), `S3 ${k} persisted with integer block index`)
    }
    ok(byId.get('th-cell')?.anchor.index === 9, 'S3 table-cell anchor keeps its own block index (cell = block, ticket req 2)')
  } catch (e) {
    ok(false, 'S3 kinds: ' + String(e).slice(0, 240))
  }
}

/* S4 — anchor survival through the real model (acceptance d, store half). */
section('S4 anchor resolution: hash hit, neighbour fallback, outdated never dropped')
{
  try {
    const blocks = [
      { index: 0, hash: model.blockHash('Reviewer design'), neighbour: '', text: 'Reviewer design' },
      { index: 1, hash: model.blockHash('The lane is the store.'), neighbour: 'Reviewer design', text: 'The lane is the store.' },
      { index: 2, hash: model.blockHash('first item'), neighbour: 'The lane is the store.', text: 'first item' },
    ]
    const hit = model.resolveAnchor(blocks, { hash: blocks[1].hash, neighbour: 'Reviewer design', blockIndex: 1 })
    ok(hit && hit.kind === 'exact' && hit.index === 1, 'S4 exact hash hit resolves in place')
    // after an edit: the hash misses, the neighbour snippet still matches at the same index
    const edited = [
      { index: 0, hash: model.blockHash('Reviewer design'), neighbour: '', text: 'Reviewer design' },
      { index: 1, hash: model.blockHash('The lane file is the ONLY store.'), neighbour: 'Reviewer design', text: 'The lane file is the ONLY store.' },
      { index: 2, hash: model.blockHash('first item'), neighbour: 'The lane file is the ONLY store.', text: 'first item' },
    ]
    const nb = model.resolveAnchor(edited, { hash: blocks[1].hash, neighbour: 'Reviewer design', blockIndex: 1 })
    ok(nb && nb.kind === 'neighbour' && nb.index === 1, 'S4 hash miss + neighbour hit remaps to the edited block')
    // an insert above shifts the index by one: the ±1 probe finds the neighbour
    const shifted = [
      { index: 0, hash: model.blockHash('New intro'), neighbour: '', text: 'New intro' },
      { index: 1, hash: model.blockHash('Reviewer design'), neighbour: '', text: 'Reviewer design' },
      { index: 2, hash: model.blockHash('The lane is the store.'), neighbour: 'Reviewer design', text: 'The lane is the store.' },
      { index: 3, hash: model.blockHash('first item edited'), neighbour: 'The lane is the store.', text: 'first item edited' },
    ]
    const sh = model.resolveAnchor(shifted, { hash: blocks[2].hash, neighbour: 'The lane is the store.', blockIndex: 2 })
    ok(sh && sh.kind === 'neighbour' && sh.index === 3, 'S4 neighbour found after an index shift (insert above)')
    // both miss: outdated, and placeThreads keeps the thread ranked to the end
    const gutted = [{ index: 0, hash: model.blockHash('Rewritten'), neighbour: '', text: 'Rewritten' }]
    const out = model.resolveAnchor(gutted, { hash: blocks[1].hash, neighbour: 'no such snippet', blockIndex: 1 })
    ok(out && out.kind === 'outdated', 'S4 double miss is labelled outdated')
    const placed = model.placeThreads(gutted, [
      { id: 'th-a', hash: gutted[0].hash, neighbour: '', blockIndex: 0, at: 2 },
      { id: 'th-b', hash: blocks[1].hash, neighbour: 'no such snippet', blockIndex: 1, at: 1 },
    ])
    ok(placed.length === 2 && placed.some((p) => p.resolution.kind === 'outdated'), 'S4 outdated thread is STILL placed — never dropped (req 7)')
    const last = placed[placed.length - 1]
    ok(last.resolution.kind === 'outdated' && last.index >= gutted.length, 'S4 outdated threads rank to the END of the document')
  } catch (e) {
    ok(false, 'S4 anchor resolution: ' + String(e).slice(0, 240))
  }
}

/* S5 — write-path failure faces. */
section('S5 failure faces: corrupt JSON, traversal, oversize, missing dir, temp residue')
{
  const lane = makeLaneRoot('fail')
  const file = laneFile(lane)
  try {
    mkdirSync(join(lane, '.sandbar'), { recursive: true })
    writeFileSync(file, '{ not json at all', 'utf8')
    const bad = await store.readReviewComments(file)
    ok(bad.ok === false && typeof bad.reason === 'string' && bad.reason.length > 0, 'S5 corrupt JSON read reports a named failure, never a silent empty doc')
    const before = readFileSync(file, 'utf8')
    const refused = await store.mergeReviewComments(file, TICKET, DOC, { threads: [thread()] })
    ok(refused.ok === false && refused.code === 'corrupt', 'S5 merge into corrupt file refuses with code corrupt')
    ok(readFileSync(file, 'utf8') === before, 'S5 refused merge leaves the corrupt file byte-identical (evidence never destroyed)')
  } catch (e) {
    ok(false, 'S5 corrupt face: ' + String(e).slice(0, 240))
  }
  try {
    const lane2 = makeLaneRoot('trav')
    const evils = ['../outside.json', '/etc/passwd', '~/x.json', 'a/../../b.json']
    let rejected = 0
    for (const ev of evils) {
      if (!store.isSafeRelPath(ev) || store.reviewCommentsFilePath('/repo', lane2, ev) === null) rejected++
    }
    ok(rejected === evils.length, `S5 all traversal-shaped paths rejected by the path guard (${rejected}/${evils.length})`)
    ok(!existsSync(join(lane2, 'outside.json')), 'S5 traversal wrote nothing outside the lane root')
  } catch (e) {
    ok(false, 'S5 traversal: ' + String(e).slice(0, 240))
  }
  try {
    // oversize against the REAL cap (module exports are immutable): enough
    // max-length threads that the merged document exceeds the declared bytes
    const lane3 = makeLaneRoot('oversize')
    const file3 = laneFile(lane3)
    const r1 = await store.mergeReviewComments(file3, TICKET, DOC, { threads: [thread()] })
    ok(r1.ok === true, 'S5 small merge under cap succeeds')
    const before3 = readFileSync(file3, 'utf8')
    const bigText = 'x'.repeat(3900) // near the per-thread text cap
    const many = []
    for (let i = 0; i < store.REVIEW_COMMENTS_MAX_THREADS; i++) many.push(thread({ id: 'th-big-' + i, text: bigText }))
    const r2 = await store.mergeReviewComments(file3, TICKET, DOC, { threads: many })
    ok(r2.ok === false && r2.code === 'oversize', `S5 over-cap merge refuses with code oversize (${store.REVIEW_COMMENTS_MAX_THREADS} max-size threads)`)
    const doc3 = readStore(lane3)
    ok(doc3.threads.length === 1 && readFileSync(file3, 'utf8') === before3, 'S5 existing file never truncated by the over-cap refusal')
  } catch (e) {
    ok(false, 'S5 oversize: ' + String(e).slice(0, 240))
  }
  try {
    // missing dir: read is empty-not-error; write creates the directory
    const lane4 = makeLaneRoot('nodir')
    const file4 = laneFile(lane4)
    const got = await store.readReviewComments(file4)
    ok(got.ok === true && got.doc === null, 'S5 read with no lane file is ok/doc-null (normal empty state, not an error)')
    const w = await store.mergeReviewComments(file4, TICKET, DOC, { threads: [thread()] })
    ok(w.ok === true && existsSync(file4), 'S5 write creates the missing .sandbar/ directory')
  } catch (e) {
    ok(false, 'S5 missing dir: ' + String(e).slice(0, 240))
  }
  try {
    // temp residue on a forced write error
    const lane5 = makeLaneRoot('residue')
    const file5 = laneFile(lane5)
    await store.mergeReviewComments(file5, TICKET, DOC, { threads: [thread()] })
    const dir = join(lane5, '.sandbar')
    const before = readdirSync(dir)
    try { chmodSync(dir, 0o500) } catch {}
    const r = await store.mergeReviewComments(file5, TICKET, DOC, { threads: [thread({ id: 'th-second' })] }).catch((e) => ({ ok: false, code: 'io', threw: String(e) }))
    try { chmodSync(dir, 0o700) } catch {}
    const after = readdirSync(dir)
    const residue = after.filter((f) => !before.includes(f))
    ok(r && r.ok === false && (r.code === 'io' || r.threw), 'S5 forced write error reports io failure')
    ok(residue.length === 0, `S5 forced write error leaves no temp residue (found: ${residue.join(',') || 'none'})`)
  } catch (e) {
    ok(false, 'S5 residue: ' + String(e).slice(0, 240))
  }
}

/* S6 — hostile lane documents: named drops, sound threads survive, never throw. */
section('S6 hostile lane documents sanitized with a named drop count')
{
  const lane = makeLaneRoot('hostile')
  const file = laneFile(lane)
  try {
    mkdirSync(join(lane, '.sandbar'), { recursive: true })
    const hostile = {
      ticketId: TICKET, path: DOC,
      threads: [
        thread({ id: 'th-good' }),
        { id: 42 },                                        // non-string id -> dropped
        thread({ id: 'th-neg', anchor: { index: -5, hash: 'h', neighbour: '' } }), // negative index -> dropped
        thread({ id: 'th-orphan', parentId: 'th-ghost' }), // unknown parent -> structurally kept, never a crash
      ],
    }
    writeFileSync(file, JSON.stringify(hostile), 'utf8')
    let res = null
    try { res = await store.readReviewComments(file) } catch (e) { res = { threw: String(e) } }
    ok(res && !res.threw && res.ok === true, 'S6 hostile document does not throw the reader')
    const ids = new Set((res.doc?.threads || []).map((t) => t.id))
    ok(ids.has('th-good'), 'S6 the structurally sound thread survives sanitation')
    ok(ids.has('th-orphan'), 'S6 a thread with an unknown parent id is kept, never crashed away')
    const m = await store.mergeReviewComments(file, TICKET, DOC, { threads: [thread({ id: 'th-fresh' }), { nope: true }] })
    ok(m.ok === true && m.dropped === 1, 'S6 merge counts unsalvageable entries in a NAMED dropped count (never a silent swallow)')
  } catch (e) {
    ok(false, 'S6 hostile: ' + String(e).slice(0, 240))
  }
}

summarize()
