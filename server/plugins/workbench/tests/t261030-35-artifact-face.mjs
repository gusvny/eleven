#!/usr/bin/env node
/**
 * tests/t261030-35-artifact-face.mjs — the console artifact inventory and frame
 * (epic artifact-face, slice 2). Developer L1 battery.
 *
 * What is pinned here (the proof faces the plan names):
 *   A DERIVATION — the declared list is read from the snapshot through ONE model:
 *     per-receipt descriptors win, a receipt without a list falls back to its legacy
 *     `deliverables` (kind guessed, labelled as guessed), the engine's own
 *     legacy/kind_known/round flags are consumed verbatim, the snapshot's aggregate
 *     list wins when present, and every refusal is named (dropped entries, malformed
 *     shapes, a declared id that cannot address the byte route).
 *   B FRAME OWNERSHIP — the frame is not a project's to change: descriptor keys
 *     `hidden`/`visible`/`order`/`view`/`render` are ignored and named, order is stage
 *     order then declaration order, and a row is never removed.
 *   C METADATA — the host resolves each row to a real file inside the ticket
 *     workspace and names what it cannot use: missing, directory, `..` escape, symlink
 *     escape, over the in-page cap (per-kind table), absolute/URL source, a member
 *     repo with no workspace entry. A multi-repo row resolves when the ticket declares
 *     the repo.
 *   D BYTES — a declared artifact is served by `<stage>/<id>` with the response
 *     contract the design requires (text kinds as text/plain, an image under its own
 *     type, SVG forced to a download, everything else an attachment); an id declared
 *     twice is refused, a non-addressable id is refused, an over-cap file is refused,
 *     text that is not UTF-8 is refused, and a saturated read pool answers busy
 *     instead of waiting.
 *   E VIEW — labels, states, empty/unavailable text, degrade card, and the machine
 *     verdict through the ONE existing rule (never green when nothing was written).
 *
 * Honest scope note: the HTTP status split and the response headers are proved by the
 * L3 scenario over the real route table (integration/t261030-35); here the source
 * shape of those headers is only an anchor, never the proof.
 *
 * Runs standalone (`node tests/t261030-35-artifact-face.mjs`, cwd = repo root) and is
 * auto-discovered by run_tests.mjs. Temp trees live under mkdtemp and are reclaimed on
 * every exit path.
 */
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const MODEL = new URL('../src/client/artifact-face-model.ts', import.meta.url).pathname
const HOST = new URL('../src/host/artifact-face.ts', import.meta.url).pathname
const NODE_TS = new URL('../node.ts', import.meta.url).pathname

let pass = 0
let fail = 0
const C = {
  case(name, ok, reason = '') {
    if (ok) { pass += 1; console.log(`[PASS] ${name}`) }
    else { fail += 1; console.log(`[FAIL] ${name}${reason === '' ? '' : ' — ' + reason}`) }
  },
  eq(name, actual, expected) {
    const a = JSON.stringify(actual)
    const e = JSON.stringify(expected)
    C.case(name, a === e, `expected ${e}, got ${a}`)
  },
  exit() {
    console.log(`SUMMARY pass=${pass} fail=${fail}`)
    process.exit(fail === 0 ? 0 : 1)
  },
}

const dirs = []
function freshDir(prefix) {
  const d = mkdtempSync(join(tmpdir(), prefix))
  dirs.push(d)
  return d
}
function cleanup() {
  for (const d of dirs) {
    try { rmSync(d, { recursive: true, force: true }) } catch { /* already gone */ }
  }
}
process.on('exit', cleanup)
process.on('SIGINT', () => { cleanup(); process.exit(130) })
process.on('SIGTERM', () => { cleanup(); process.exit(143) })

let M
let H
try {
  M = await import(MODEL)
  H = await import(HOST)
} catch (e) {
  console.error(`ENV_FAIL: model/host module unresolvable: ${e?.message ?? e}`)
  process.exit(2)
}

/* ---------------------------------------------------------------- fixtures */

/** A lane tree: <root>/.lane/<id>/… plus the project root. */
function makeLane() {
  const root = freshDir('af-root-')
  const lane = join(root, '.lane', 't1')
  mkdirSync(join(lane, 'out'), { recursive: true })
  mkdirSync(join(lane, 'adr'), { recursive: true })
  writeFileSync(join(lane, 'out', 'a.md'), '# hello\n')
  writeFileSync(join(lane, 'out', 'data.json'), '{"k":1}\n')
  writeFileSync(join(lane, 'out', 'pic.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 1, 2, 3]))
  writeFileSync(join(lane, 'out', 'vector.svg'), '<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>')
  writeFileSync(join(lane, 'out', 'big.txt'), 'x'.repeat(1_048_577))
  writeFileSync(join(lane, 'out', 'big.png'), Buffer.alloc(2_000_000, 7))
  writeFileSync(join(lane, 'out', 'bin.dat'), Buffer.from([0xff, 0xfe, 0x00, 0x41]))
  writeFileSync(join(lane, 'adr', 'x.md'), 'adr body\n')
  mkdirSync(join(lane, 'out', 'adir'), { recursive: true })
  symlinkSync(join(lane, 'out', 'a.md'), join(lane, 'out', 'inside-link.md'))
  symlinkSync('/etc/hosts', join(lane, 'out', 'escape-link.md'))
  // multi-repo: the second repository's tree lives beside the lane root
  mkdirSync(join(lane, 'fpv', 'models'), { recursive: true })
  writeFileSync(join(lane, 'fpv', 'models', 'part.glb'), Buffer.from([1, 2, 3]))
  writeFileSync(join(root, 'outside.md'), 'outside the lane\n')
  return { root, lane }
}

/* The stats map is keyed by the LISTING identity (`<key>@r<round>#<n>`); tests look a
 *  row up by its byte address and read the stat through that row. */
function statOfKey(inv, key) {
  const row = (inv.rows || []).find(r => r.key === key)
  return row === undefined ? undefined : inv.stats[row.rowKey]
}

function descriptor(over = {}) {
  return {
    id: 'report', title: 'Report', kind: 'text', kind_known: true, source: 'out/a.md',
    repo: '', stage: '', note: '', open: '', shape: '', optional: false, legacy: false,
    round: null, ...over,
  }
}

function receiptDetail(descriptorsByStage, extra = {}) {
  const results = {}
  for (const [stage, body] of Object.entries(descriptorsByStage)) results[stage] = body
  return { id: 't1', worktree: '.lane/t1', results, ...extra }
}

/* ---------------------------------------------------------------- A: derivation */

console.log('\n== A. derivation ==')
{
  const detail = receiptDetail({
    plan: { gen: 2, artifact_descriptors: [descriptor({ id: 'report', source: 'out/a.md', title: 'Plan report' })] },
    implement: { gen: 3, deliverables: ['out/pic.png', 'out/data.json', 'out/notes.weird', 42, ''] },
  })
  const d = M.deriveArtifactRows(detail, ['plan', 'implement'])
  C.eq('A1 declared descriptor is read verbatim (id/title/kind)', d.rows[0].id, 'report')
  C.eq('A1 title comes from the declaration', d.rows[0].title, 'Plan report')
  C.eq('A1 round falls back to the receipt gen', d.rows[0].round, 2)
  C.eq('A2 legacy deliverables become rows with a guessed kind', d.rows.slice(1).map(r => r.kind), ['image', 'structure', 'external'])
  C.case('A2 legacy rows are labelled as guessed', d.rows.slice(1).every(r => r.legacy === true))
  C.case('A2 a non-string deliverables entry is named, not silently skipped', d.refusals.some(x => x.includes('[implement] 3:')))
  C.case('A2 a blank deliverables entry is named', d.refusals.some(x => x.includes('[implement] 4:')))
  C.eq('A3 list source names the receipts path', d.listSource, 'receipts')
}
{
  // Engine flags win: kind_known=false on a known kind must NOT be re-guessed to true.
  const d = M.deriveArtifactRows(receiptDetail({
    plan: { gen: 1, artifact_descriptors: [descriptor({ kind: 'text', kind_known: false, legacy: true })] },
  }))
  C.eq('A4 the engine kind_known flag is consumed verbatim', d.rows[0].kindKnown, false)
  C.eq('A4 the engine legacy flag is consumed verbatim', d.rows[0].legacy, true)
}
{
  const d = M.deriveArtifactRows(receiptDetail({
    plan: { gen: 1, artifact_descriptors: [descriptor()], artifact_descriptors_dropped: ['0: source missing — refused'] },
    implement: { gen: 1, artifact_descriptors_shape: 'malformed' },
  }))
  C.case('A5 receipt-level refusals are named with the stage', d.refusals.some(x => x === '[plan] 0: source missing — refused'))
  C.case('A5 a malformed declared list is named as a whole', d.refusals.some(x => x.includes('refused as a whole')))
}
{
  const detail = {
    id: 't1', worktree: '.lane/t1',
    artifact_descriptors: [descriptor({ id: 'agg', stage: 'plan', round: 4 })],
    artifact_descriptors_dropped: ['x: no source — refused'],
    results: { plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'receipt-only' })] } },
  }
  const d = M.deriveArtifactRows(detail)
  C.eq('A6 the snapshot aggregate list wins when present', d.rows.map(r => r.id), ['agg'])
  C.eq('A6 aggregate rows keep their own round', d.rows[0].round, 4)
  C.eq('A6 the aggregate refusal channel is read', d.refusals, ['x: no source — refused'])
  C.eq('A6 list source names the aggregate path', d.listSource, 'aggregate')
}
{
  // ENGINE-SHAPED receipt (walkthrough 1, D1): a stage that declares nothing carries
  // `artifact_descriptors: []` with shape `absent` and its produced paths in
  // `deliverables`. The canonical rule falls back to those paths — treating the empty
  // array as an explicit declaration hid them.
  const d = M.deriveArtifactRows({ results: { plan: { gen: 1, artifact_descriptors: [], artifact_descriptors_shape: 'absent', deliverables: ['out/a.md', 'out/b.png'] } } })
  C.eq('A10 an empty list with shape absent lists the deliverables', d.rows.map(r => r.key), ['plan/out-a-md', 'plan/out-b-png'])
  C.case('A10 the fallback rows are labelled as guessed paths', d.rows.every(r => r.legacy === true))
  C.eq('A10 the fallback is not reported as a refusal', d.refusals, [])
}
{
  // A malformed declaration is named AND falls back (the same floor the canonical rule
  // gives a handoff with no usable declaration).
  const d = M.deriveArtifactRows({ results: { plan: { gen: 2, artifact_descriptors: [], artifact_descriptors_shape: 'malformed', deliverables: ['out/a.md'] } } })
  C.eq('A11 a malformed declaration is named', d.refusals.some(x => x.includes('malformed')), true)
  C.eq('A11 a malformed declaration still lists the deliverables', d.rows.map(r => r.key), ['plan/out-a-md'])
}
{
  // CANONICAL HANDOFF RULE (walkthrough 1, D2): one entry per round; an earlier round's
  // declaration survives a rework; a declaring handoff does not mirror its legacy paths.
  const detail = {
    id: 't1', worktree: '.lane/t1',
    gens: { plan: 2, implement: 3 },
    handoffs: [
      { stage: 'plan', gen: 1, artifacts: ['out/old.md'], artifact_descriptors: [descriptor({ id: 'plan', source: '.sandbar/p0.json' })] },
      { stage: 'plan', gen: 2, artifacts: ['out/old.md'], artifact_descriptors: [descriptor({ id: 'plan', source: '.sandbar/p1.json' })] },
      { stage: 'implement', gen: 1, artifacts: ['out/x.md', 'out/y.md'], artifact_descriptors: [descriptor({ id: 'code', source: 'src/a.ts' })] },
      { stage: 'implement', gen: 3, artifacts: ['out/x.md', 'out/y.md'] },
      { stage: 'acceptance', gen: 0, artifacts: [] },
    ],
    results: { implement: { gen: 3, artifact_descriptors: [], artifact_descriptors_shape: 'absent', deliverables: ['out/x.md', 'out/y.md'] } },
  }
  const d = M.deriveArtifactRows(detail, ['plan', 'implement'])
  C.eq('A12 the canonical list keeps both plan rounds', d.rows.filter(r => r.stage === 'plan').length, 2)
  C.eq('A12 a declaring handoff does not mirror its legacy paths', d.rows.filter(r => r.stage === 'implement' && r.legacy === false).length, 1)
  C.eq('A12 a non-declaring handoff contributes its paths', d.rows.filter(r => r.stage === 'implement' && r.legacy === true).length, 2)
  C.eq('A12 rounds come from the handoff gen', d.rows.map(r => `${r.stage}/${r.id}@${r.round}`),
    ['plan/plan@1', 'plan/plan@2', 'implement/code@1', 'implement/out-x-md@3', 'implement/out-y-md@3'])
  C.eq('A12 the list source names the handoff history', d.listSource, 'handoffs')
  C.eq('A12 two rounds of one artifact get two listing identities', new Set(d.rows.map(r => r.rowKey)).size, d.rows.length)
  C.eq('A12 the newest round is the one the byte route serves', M.selectArtifactRowForBytes(d.rows, 'plan', 'plan').row.source, '.sandbar/p1.json')
  // WALKTHROUGH 2 (A8): the address carries no round, so a row may only offer the link
  // when the route serves ITS source. The older round names the round it does not serve.
  const older = d.rows.find(r => r.stage === 'plan' && r.round === 1)
  const newer = d.rows.find(r => r.stage === 'plan' && r.round === 2)
  C.eq('A15 only the served round offers the byte link', [older.servable, newer.servable], [false, true])
  C.case('A15 the older row names the served round', older.byteRefusal.includes('round 2'), older.byteRefusal)
  C.case('A15 the older row carries the refusal on the row', older.refusals.some(x => x.includes('round 2')))
  const stats = Object.fromEntries(d.rows.map(r => [r.rowKey, { state: 'ok', sizeBytes: 10, mtimeMs: 0 }]))
  const view = M.buildArtifactFaceView(d, stats, null)
  const olderView = view.rows.find(r => r.round === 1 && r.stage === 'plan')
  const newerView = view.rows.find(r => r.round === 2 && r.stage === 'plan')
  C.eq('A15 the older row shows no link and the newer row does', [olderView.bytesHref, newerView.bytesHref], [null, 'bytes'])
  C.case('A15 the older row explains why', olderView.bytesRefusal.includes('round 2'), olderView.bytesRefusal)
  // Identical records (the engine can record one declaration twice) are not confusable:
  // both keep the link, since they serve the same file.
  const twin = M.deriveArtifactRows({
    handoffs: [
      { stage: 'implement', gen: 3, artifacts: ['out/a.md'] },
      { stage: 'implement', gen: 3, artifacts: ['out/a.md'] },
    ],
    gens: { implement: 3 },
  })
  C.eq('A15 identical duplicate records both keep the link', twin.rows.map(r => r.servable), [true, true])
}
{
  // ORDER (plan A2/D4, walkthrough 1 scenario 4): the handoff history is chronological,
  // so a reworked stage's later round lands AFTER the next stage started. The frame is
  // stage order then declaration order: one block per stage, no interleaving.
  const detail = {
    id: 't1', worktree: '.lane/t1',
    handoffs: [
      { stage: 'implement', gen: 1, artifacts: ['out/a.md'] },
      { stage: 'design', gen: 1, artifacts: ['out/b.md'] },
      { stage: 'implement', gen: 3, artifacts: ['out/c.md'] },
    ],
  }
  const d = M.deriveArtifactRows(detail, ['implement', 'design'])
  C.eq('A13 rows follow stage order, not handoff chronology', d.rows.map(r => r.key),
    ['implement/out-a-md', 'implement/out-c-md', 'design/out-b-md'])
  C.eq('A13 a stage keeps its own declaration order', d.rows.filter(r => r.stage === 'implement').map(r => r.round), [1, 3])
  const noOrder = M.deriveArtifactRows(detail)
  C.eq('A13 without a stage order the source order is left alone', noOrder.rows.map(r => r.key),
    ['implement/out-a-md', 'design/out-b-md', 'implement/out-c-md'])
  const unknown = M.deriveArtifactRows(detail, ['design'])
  C.eq('A13 a stage the template does not name follows the named stages', unknown.rows.map(r => r.stage),
    ['design', 'implement', 'implement'])
}
{
  // SUPPLEMENT (walkthrough 1, D1/A3 second half): a mechanical stage records a receipt
  // and no handoff (`ui_evidence` on the live ticket). Its receipt is the only record, so
  // it is read; a stage the history DOES name is never read from its receipt as well.
  const detail = {
    id: 't1', worktree: '.lane/t1',
    handoffs: [{ stage: 'plan', gen: 1, artifact_descriptors: [descriptor({ id: 'plan', source: '.sandbar/p0.json' })] }],
    results: {
      plan: { gen: 1, deliverables: ['out/dup.md'] },
      ui_evidence: { status: 'ok', gen: 0, deliverables: ['console-board.png'] },
    },
  }
  const d = M.deriveArtifactRows(detail, ['plan', 'ui_evidence'])
  C.eq('A14 a stage the history never names lists its receipt deliverables', d.rows.map(r => r.key),
    ['plan/plan', 'ui_evidence/console-board-png'])
  C.eq('A14 a stage the history produced rows for is not read from its receipt as well', d.rows.filter(r => r.key === 'plan/out-dup-md').length, 0)
  C.eq('A14 the list source names both readers', d.listSource, 'handoffs+receipts')
  C.case('A14 the supplemented row is labelled as a guessed path', d.rows[1].legacy === true)
  C.eq('A14 a supplement adds no refusal (it is a read, not a diagnosis)', d.refusals, [])
  const receipt = M.deriveArtifactRows({ results: { ui_evidence: { gen: 0, deliverables: ['console-board.png'] } } }, ['ui_evidence'])
  C.eq('A14 with no handoff history the source stays the receipt path', receipt.listSource, 'receipts')
}
{
  // A handoff entry that carried no paths says nothing usable for its stage, so the
  // receipt is the only record (the remaining half of walkthrough 1's D1).
  const detail = {
    id: 't1', worktree: '.lane/t1',
    handoffs: [{ stage: 'implement', gen: 2, artifacts: [] }],
    results: {
      implement: { gen: 2, deliverables: ['out/kept.md'], artifact_descriptors: [], artifact_descriptors_shape: 'absent' },
    },
  }
  const d = M.deriveArtifactRows(detail, ['implement'])
  C.eq('A14b a handoff with no paths lets the receipt speak', d.rows.map(r => r.key), ['implement/out-kept-md'])
  C.eq('A14b the round comes from the receipt', d.rows[0].round, 2)
  C.eq('A14b the list source names both readers', d.listSource, 'handoffs+receipts')
}
{
  const d = M.deriveArtifactRows(null)
  C.eq('A7 a null snapshot yields no rows and no throw', d.rows.length, 0)
  const d2 = M.deriveArtifactRows({ results: { plan: { gen: 1, deliverables: 'not-a-list' } } })
  C.eq('A7 a non-list deliverables value yields no rows (never char-split)', d2.rows.length, 0)
  const d3 = M.deriveArtifactRows({ results: { plan: { gen: 0, artifact_descriptors: [descriptor({ round: null })] } } })
  C.eq('A7 a zero gen is not a round', d3.rows[0].round, null)
}
{
  const d = M.deriveArtifactRows(receiptDetail({
    plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'a/b' }), descriptor({ id: 'ok-id', source: 'out/data.json' })] },
  }))
  C.case('A8 an id with a slash is not addressable', !d.rows[0].servable)
  C.case('A8 the non-addressable id names itself', d.rows[0].refusals.some(x => x.includes("artifact id 'a/b' is not addressable")))
  C.case('A8 a plain id stays addressable', d.rows[1].servable)
}

/* ---------------------------------------------------------------- B: frame ownership */

console.log('\n== B. frame ownership ==')
{
  const d = M.deriveArtifactRows(receiptDetail({
    plan: {
      gen: 1,
      artifact_descriptors: [
        descriptor({ id: 'one', hidden: true }),
        descriptor({ id: 'two', source: 'out/data.json', order: 0 }),
        descriptor({ id: 'three', source: 'out/pic.png', view: 'custom', visible: false }),
      ],
    },
  }))
  C.eq('B1 every row survives declared display keys', d.rows.map(r => r.id), ['one', 'two', 'three'])
  C.case('B1 a refused key is named on its row', d.rows[0].refusals.some(x => x.includes("'hidden' is owned by the frame")))
  C.eq('B1 order is declaration order, not the declared order field', d.rows.map(r => r.id), ['one', 'two', 'three'])
}
{
  const detail = {
    id: 't1', worktree: '.lane/t1',
    results: {
      plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'a' })] },
      implement: { gen: 1, artifact_descriptors: [descriptor({ id: 'b', source: 'out/data.json' })] },
    },
  }
  const d = M.deriveArtifactRows(detail, ['implement', 'plan'])
  C.eq('B2 stage order drives the row order', d.rows.map(r => r.key), ['implement/b', 'plan/a'])
}

/* ---------------------------------------------------------------- C: metadata */

console.log('\n== C. metadata ==')
{
  const { root } = makeLane()
  const detail = receiptDetail({
    plan: {
      gen: 1,
      artifact_descriptors: [
        descriptor({ id: 'ok' }),
        descriptor({ id: 'gone', source: 'out/none.md' }),
        descriptor({ id: 'dir', source: 'out/adir' }),
        descriptor({ id: 'escape', source: '../outside.md' }),
        descriptor({ id: 'symlink', source: 'out/escape-link.md' }),
        descriptor({ id: 'inside', source: 'out/inside-link.md' }),
        descriptor({ id: 'big', source: 'out/big.txt' }),
        descriptor({ id: 'bigpng', source: 'out/big.png', kind: 'image' }),
        descriptor({ id: 'url', source: 'https://example.test/x.glb', kind: 'external' }),
        descriptor({ id: 'abs', source: '/etc/hosts' }),
        descriptor({ id: 'repo', source: 'models/part.glb', repo: 'fpv', kind: 'external' }),
      ],
    },
  })
  const inv = await H.buildArtifactInventory(root, detail, ['plan'])
  const s = (id) => statOfKey(inv, `plan/${id}`)
  C.eq('C1 an in-workspace file is ok', s('ok').state, 'ok')
  C.eq('C1 ok rows carry size and mtime', typeof s('ok').sizeBytes === 'number' && typeof s('ok').mtimeMs === 'number', true)
  C.eq('C2 a missing file is named', s('gone').state, 'missing')
  C.eq('C2 a directory is not a file', s('dir').state, 'not_a_file')
  C.eq('C3 a `..` escape is refused', s('escape').state, 'outside_root')
  C.eq('C3 a symlink escape is refused', s('symlink').state, 'outside_root')
  C.eq('C3 a symlink inside the lane is allowed', s('inside').state, 'ok')
  C.eq('C4 an over-cap text file is named too_large', s('big').state, 'too_large')
  C.eq('C4 the image cap is wider than the text cap', s('bigpng').state, 'ok')
  C.eq('C5 a URL source is external', s('url').state, 'external')
  C.eq('C5 an absolute path outside the project root is external', s('abs').state, 'external')
  C.eq('C6 an undeclared member repo is named', s('repo').state, 'repo_root_unknown')
  {
    // A legacy handoff can record an ABSOLUTE path. Inside the project anchor it is a
    // usable file (the containment rule decides, not the shape of the string).
    const inAnchor = join(root, 'outside.md')
    const d2 = receiptDetail({ plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'absin', source: inAnchor })] } })
    const inv2 = await H.buildArtifactInventory(root, d2)
    C.eq('C6 an absolute path inside the project root is readable', statOfKey(inv2, 'plan/absin').state, 'ok')
  }
  C.eq('C6 every row keeps a stat record', Object.keys(inv.stats).length, inv.rows.length)
}
{
  const { root } = makeLane()
  const detail = {
    id: 't1', worktree: '.lane/t1',
    repo_worktrees: [{ repo: '', name: 'root', branch: 'lane/t1' }, { repo: 'fpv', name: 'fpv', branch: 'lane/t1-fpv' }],
    results: { plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'part', source: 'models/part.glb', repo: 'fpv', kind: 'external' })] } },
  }
  const inv = await H.buildArtifactInventory(root, detail)
  C.eq('C7 a declared member repo resolves inside the lane', statOfKey(inv, 'plan/part').state, 'ok')
  const bad = { ...detail, repo_worktrees: [{ repo: 'fpv', name: '', branch: '' }] }
  const inv2 = await H.buildArtifactInventory(root, bad)
  C.eq('C8 a malformed repo_worktrees list means no member root (whole-list refusal)', statOfKey(inv2, 'plan/part').state, 'repo_root_unknown')
}
{
  const { root } = makeLane()
  const detail = { id: 't1', workspace: { type: 'dir', path: '/tmp/elsewhere' }, results: { plan: { gen: 1, deliverables: ['out/a.md'] } } }
  const inv = await H.buildArtifactInventory(root, detail)
  C.eq('C9 a workspace outside the project root is refused', statOfKey(inv, 'plan/out-a-md').state, 'outside_root')
  C.eq('C9 the root note names the refusal', inv.roots.note.includes('outside the project root'), true)
}
{
  const { root } = makeLane()
  const detail = { id: 't1', worktree: '.lane/gone', results: { plan: { gen: 1, deliverables: ['out/a.md'] } } }
  const inv = await H.buildArtifactInventory(root, detail)
  C.eq('C10 a torn-down lane is named missing, not blank', statOfKey(inv, 'plan/out-a-md').state, 'missing')
}

/* ---------------------------------------------------------------- D: bytes */

console.log('\n== D. bytes ==')
{
  const { root } = makeLane()
  const detail = receiptDetail({
    plan: {
      gen: 1,
      artifact_descriptors: [
        descriptor({ id: 'text' }),
        descriptor({ id: 'json', source: 'out/data.json', kind: 'structure' }),
        descriptor({ id: 'png', source: 'out/pic.png', kind: 'image' }),
        descriptor({ id: 'svg', source: 'out/vector.svg', kind: 'image' }),
        descriptor({ id: 'glb', source: 'fpv/models/part.glb', repo: 'fpv', kind: 'external' }),
        descriptor({ id: 'big', source: 'out/big.txt' }),
        descriptor({ id: 'bin', source: 'out/bin.dat', kind: 'text' }),
        descriptor({ id: 'dup' }),
        descriptor({ id: 'dup', source: 'out/data.json' }),
        descriptor({ id: 'a/b', source: 'adr/x.md' }),
      ],
    },
  })
  const answer = async (id) => H.readArtifactBytes(root, detail, 'plan', id)
  const text = await answer('text')
  C.eq('D1 a text artifact is served as text/plain', text.ok && text.contentType, 'text/plain; charset=utf-8')
  C.eq('D1 text is inline', text.disposition, 'inline')
  C.eq('D1 the body is the file', text.ok && text.body.toString('utf8'), '# hello\n')
  C.eq('D1 the offered filename is the declared basename', text.filename, 'a.md')
  const st = await answer('json')
  C.eq('D2 a structure artifact is text/plain too', st.contentType, 'text/plain; charset=utf-8')
  const png = await answer('png')
  C.eq('D3 an image is served under its own type, inline', [png.contentType, png.disposition], ['image/png', 'inline'])
  const svg = await answer('svg')
  C.eq('D3 SVG leaves as a download (script on the console origin)', [svg.contentType, svg.disposition], ['application/octet-stream', 'attachment'])
  const big = await answer('big')
  C.eq('D4 an over-cap file is refused by code', [big.ok, big.code], [false, 'too_large'])
  const bin = await answer('bin')
  C.eq('D4 text that is not UTF-8 is refused, never served as mojibake', [bin.ok, bin.code], [false, 'not_utf8'])
  const dup = await answer('dup')
  C.eq('D5 an id declared twice is ambiguous, not a first match', [dup.ok, dup.code], [false, 'ambiguous'])
  const slash = await answer('a/b')
  C.case('D5 an id that cannot address the route is refused', slash.ok === false)
  const absent = await answer('nope')
  C.eq('D6 an undeclared id is not_found', [absent.ok, absent.code], [false, 'not_found'])
  const badStage = await H.readArtifactBytes(root, detail, 'implement', 'text')
  C.eq('D6 the stage is part of the address', [badStage.ok, badStage.code], [false, 'not_found'])
  const glb = await answer('glb')
  C.eq('D7 an undeclared member repo is refused by name', [glb.ok, glb.code], [false, 'refused'])
}
{
  const { root } = makeLane()
  const detail = {
    id: 't1', worktree: '.lane/t1',
    repo_worktrees: [{ repo: '', name: 'root', branch: 'x' }, { repo: 'fpv', name: 'fpv', branch: 'y' }],
    results: { plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'part', source: 'models/part.glb', repo: 'fpv', kind: 'external' })] } },
  }
  const r = await H.readArtifactBytes(root, detail, 'plan', 'part')
  C.eq('D7 the member-repo bytes are served as an attachment', [r.ok, r.contentType, r.disposition], [true, 'application/octet-stream', 'attachment'])
  C.eq('D7 the member-repo body is the file', r.ok && r.body.length, 3)
}
{
  // Slot saturation: four reads in flight, the fifth answers busy (never waits).
  const held = []
  for (let i = 0; i < H.ARTIFACT_BYTES_SLOTS; i++) {
    held.push(H.withArtifactSlot(() => new Promise((resolve) => setTimeout(() => resolve('done'), 5))))
  }
  const refused = await H.withArtifactSlot(async () => 'should-not-run')
  C.eq('D8 a saturated read pool answers busy', [refused.ok, refused.code], [false, 'busy'])
  const done = await Promise.all(held)
  C.eq('D8 the in-flight reads still complete', done.every(x => x === 'done'), true)
  C.eq('D8 the slot counter returns to zero', H.activeArtifactSlots(), 0)
  const after = await H.withArtifactSlot(async () => 'ok')
  C.eq('D8 the pool accepts work again', after, 'ok')
}
{
  // A text row whose bytes cannot be decoded must not claim to be openable: the panel
  // would offer a link that fails on click.
  const { root } = makeLane()
  const detail = receiptDetail({ plan: { gen: 1, artifact_descriptors: [descriptor({ id: 'bin', source: 'out/bin.dat', kind: 'text' })] } })
  const inv = await H.buildArtifactInventory(root, detail)
  C.eq('C11 a non-UTF-8 text row is named at inventory time', statOfKey(inv, 'plan/bin').state, 'not_utf8')
  C.case('C11 the named state carries a reason', String((statOfKey(inv, 'plan/bin') || {}).reason ?? '').length > 0)
}
{
  const { root } = makeLane()
  const detail = receiptDetail({ plan: { gen: 1, deliverables: ['out/a.md', 'out/pic.png'] } })
  const r = await H.readArtifactBytes(root, detail, 'plan', 'out-a-md')
  C.eq('D9 a legacy row is fetchable by its derived id', r.ok, true)
}

/* ---------------------------------------------------------------- E: view */

console.log('\n== E. view ==')
{
  const detail = {
    id: 't1', worktree: '.lane/t1',
    gate_runs: [{ stage: 'merge_check', level: 'green', count: 3, checks: [] }],
    results: {
      plan: { gen: 2, artifact_descriptors: [descriptor({ id: 'report', note: 'look here', open: 'Open in Editor', optional: true })] },
      implement: { gen: 1, artifact_descriptors: [descriptor({ id: 'weird', source: 'out/x.zzz', kind: 'hologram' })] },
    },
  }
  const derived = M.deriveArtifactRows(detail, ['plan', 'implement'])
  const reportRow = derived.rows.find(r => r.key === 'plan/report')
  const stats = { [reportRow.rowKey]: { state: 'ok', sizeBytes: 2048, mtimeMs: Date.UTC(2026, 9, 30, 12, 0) } }
  const frame = M.buildArtifactFaceView(derived, stats, detail)
  C.eq('E1 the frame counts every declared row', frame.countText, '2 declared')
  C.eq('E1 a known kind gets its English label', frame.rows[0].kindLabel, 'Text')
  C.eq('E1 an unknown kind is labelled as not recognized', frame.rows[1].kindLabel, 'hologram (not recognized)')
  C.eq('E2 an unknown kind renders the degrade card', frame.rows[1].card, 'degrade')
  C.eq('E2 a row without metadata is not presented as ok', frame.rows[1].state, 'unreadable')
  C.eq('E3 size and time are rendered', [frame.rows[0].sizeText, frame.rows[0].timeText], ['2.0 KB', '2026-10-30 12:00 UTC'])
  C.eq('E3 the round is labelled from the receipt', frame.rows[0].roundText, 'round 2')
  C.eq('E4 the note and open hint reach the row', [frame.rows[0].note, frame.rows[0].openHint], ['look here', 'Open in Editor'])
  C.eq('E4 optional is marked', frame.rows[0].optionalText, 'optional')
  C.eq('E5 the machine verdict quotes the run through the one rule', [frame.verdict.green, frame.verdict.source], [true, 'level'])
  C.eq('E6 no row is dropped by the view', frame.rows.length, derived.rows.length)
}
{
  const detail = { id: 't1', results: { plan: { gen: 1, deliverables: ['out/a.md'] } }, gate_runs: [] }
  const frame = M.buildArtifactFaceView(M.deriveArtifactRows(detail), {}, detail)
  C.eq('E7 no gate run is named, never green', [frame.verdict.green, frame.verdict.source], [null, 'none'])
  C.case('E7 the absent verdict says so', frame.verdict.text.includes('no gate run yet'))
  C.eq('E7 a legacy row says the kind was guessed', frame.rows[0].legacyText, 'legacy path (kind guessed)')
}
{
  const detail = {
    id: 't1',
    gate_runs: [{ stage: 'merge_check', verdict: 'green', checks: [{ item: 'a', done: true, green: false }] }],
    results: {},
  }
  const frame = M.buildArtifactFaceView(M.deriveArtifactRows(detail), {}, detail)
  C.case('E8 a receipt that disagrees with its own rows is shown verbatim', frame.verdict.disagreement === true)
  C.case('E8 the disagreement is named in the text', frame.verdict.text.includes('disagree'))
}
{
  const frame = M.buildArtifactFaceView(M.deriveArtifactRows(null), {}, null)
  C.eq('E9 an empty ticket says so', frame.emptyText, 'This ticket declares no artifacts.')
  C.eq('E9 no rows and no invented metadata', frame.rows.length, 0)
  C.case('E9 QC is not invented', frame.qcText.includes('no data face'))
}
{
  // English-only copy (host order 260925): no CJK in any new user-visible string.
  const cjk = /[\u3400-\u9fff]/
  const derived = M.deriveArtifactRows(receiptDetail({ plan: { gen: 1, deliverables: ['out/a.md'] } }))
  const frame = M.buildArtifactFaceView(derived, { 'plan/out-a-md': { state: 'missing', reason: 'x' } }, null)
  const strings = [
    frame.title, frame.countText, frame.listSourceText, frame.emptyText, frame.qcText,
    frame.verdict.text,
    ...frame.rows.flatMap(r => [r.kindLabel, r.roundText, r.stateText, r.legacyText, r.bytesRefusal]),
  ]
  C.eq('E10 no CJK in the frame copy', strings.some(s => typeof s === 'string' && cjk.test(s)), false)
  const everyKind = ['image', 'text', 'structure', 'diff', 'ledger', 'external']
  const labels = everyKind.map(k => M.artifactKindLabel(k))
  C.eq('E10 every built-in kind has an English label', labels, ['Image', 'Text', 'Structure', 'Diff', 'Ledger', 'External'])
  C.eq('E10 an unknown kind falls back to its identifier', M.artifactKindLabel('hologram'), 'hologram')
}
{
  // State sentences: every state is named, and 'ok' is silent.
  const states = ['ok', 'missing', 'not_a_file', 'unreadable', 'outside_root', 'repo_root_unknown', 'too_large', 'not_utf8', 'external']
  C.eq('E11 ok carries no sentence', M.artifactStateText('ok', ''), '')
  C.eq('E11 every other state carries a sentence', states.filter(s => s !== 'ok').every(s => M.artifactStateText(s, '').length > 10), true)
}

/* ---------------------------------------------------------------- F: anchors */

console.log('\n== F. anchors ==')
{
  const { readFileSync } = await import('node:fs')
  const nodeSrc = readFileSync(NODE_TS, 'utf8')
  C.case('F1 the bytes route pins nosniff', nodeSrc.includes("'x-content-type-options': 'nosniff'"))
  C.case('F1 the bytes route pins no-store', nodeSrc.includes("'cache-control': 'no-store'"))
  C.case('F2 the ambiguous id maps to 409', nodeSrc.includes("case 'ambiguous': return 409"))
  C.case('F2 the over-cap id maps to 413', nodeSrc.includes("case 'too_large': return 413"))
  C.case('F2 a saturated pool maps to 503', nodeSrc.includes("case 'busy': return 503"))
  C.case('F3 both artifact routes are registered', nodeSrc.includes("op === 'artifacts'") && nodeSrc.includes("parts[1] === 'artifacts'"))
  C.case('F4 the route never takes a path from the request for artifacts', !/artifacts[\s\S]{0,400}searchParams\.get\('path'\)/.test(nodeSrc))
  C.case('F5 the byte address segments are shape-guarded (never a path)', nodeSrc.includes('/^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$/.test(stage)'))
  C.case('F5 a divided address answers 400, not the family 404', nodeSrc.includes("artifact byte address must be /artifacts/<stage>/<id>/bytes"))
}

C.exit()
