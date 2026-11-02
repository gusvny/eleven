/**
 * sc_t26103036_artifact_view_seam.mjs — the three-half agreement on a ticket's
 * declared artifacts (ticket t261030-36, epic artifact-face slice 3).
 *
 * FACE UNDER JUDGEMENT
 *   One declared artifact row travels through three halves built by three
 *   different changes:
 *     (1) the frame — src/client/artifact-face-model.ts (slice 2, t261030-35):
 *         derives the rows, marks each row `card` / `bytesHref`, names why a
 *         row's bytes cannot be used;
 *     (2) the host  — src/host/artifact-face.ts (slice 2): answers the row's
 *         state and size, the byte answer (ok / code + reason) and the content
 *         type plus disposition;
 *     (3) the view  — src/client/artifact-view-model.ts (this slice): decides
 *         whether the row draws a body, which body, and whether it reads bytes.
 *   The user-visible promise is the epic's: every declared artifact is listed, a
 *   view decides how ONE artifact is drawn and never whether it is listed, and
 *   no panel goes blank or silent on bad data.
 *
 * WHY NO LOWER TIER CARRIES THIS (intent split, no duplication)
 *   Each half has its own battery: the frame's derivation and stat truth tables
 *   (server/plugins/workbench/tests/t261030-35-artifact-face.mjs), the host's
 *   root/cap/UTF-8 rules, and this slice's L1 + L2 batteries
 *   (tests/t261030-36-artifact-views.mjs, ...-artifact-view-ui.mjs). Each of
 *   those drives its subject against stubs or against its own module, so a stub
 *   on either side can agree with itself and disagree with the other half. That
 *   is the fault class this repo has paid for four times (t261028-48: four
 *   readers, four green rules, one receipt; KI-407 lists five more). "The frame,
 *   the host and the view agree about the same row" is not expressible in any one
 *   module's unit test.
 *   THIS entry uniquely owns: that agreement, the one-read-per-row rule, fault
 *   containment across rows, the no-row-authority rule, and the byte-slot
 *   lifecycle.
 *   Deliberately NOT re-asserted here (owned elsewhere): the parsers' malformed
 *   truth tables, the caps arithmetic and the copy (developer L1); the
 *   markdown/innerHTML inertness promise (developer L2, plan A5); the browser
 *   look and the real click (acceptance walkthrough).
 *
 * COST: offline, node only, no browser, no console port, no Temporal, no docker.
 *   Writes only inside its own mkdtemp tree. Never touches 3099 or 7233.
 *
 * THREE-STATE CONTRACT
 *   frame module absent on this lane (the ticket's P0: the base predates
 *     slice 2) -> ENV_FAIL, exit 2, named.
 *   this slice's view module absent/unimportable/incomplete -> FAIL named, exit 1.
 *   a case fails -> FAIL named, exit 1.
 *
 * Run: node integration/t261030-36/sc_t26103036_artifact_view_seam.mjs
 * Registry: integration/run_scenarios.py, name t261030-36-artifact-view-seam.
 */
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { emitCase } from '../lib_result.mjs'

/* ------------------------------------------------------------ result plumbing */

const SUITE = 't261030-36-artifact-view-seam'
let passed = 0
let failed = 0
const failures = []

function okCase(name, evidence) {
  passed += 1
  emitCase({ name, suite: SUITE, status: 'pass', cause: 'self', evidence })
  console.log(`  ok   ${name}`)
}

function badCase(name, evidence) {
  failed += 1
  failures.push(name)
  emitCase({ name, suite: SUITE, status: 'fail', cause: 'self', evidence })
  console.error(`  FAIL ${name} :: ${evidence}`)
}

function check(name, cond, evidence) {
  if (cond) okCase(name, evidence)
  else badCase(name, evidence)
}

function envFail(msg) {
  console.log(`ENV_FAIL: ${msg}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1')
  process.exit(2)
}

function finish() {
  console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0`)
  if (failed > 0) {
    console.error(`FAIL: ${failed} case(s) red: ${failures.join(', ')}`)
    process.exit(1)
  }
  console.log('PASS: the frame, the host and the view agree on every declared row.')
  process.exit(0)
}

/* --------------------------------------------------------------- environment */

const nodeMajor = Number(process.versions.node.split('.')[0])
if (!Number.isFinite(nodeMajor) || nodeMajor < 22) {
  envFail(`node ${process.versions.node} cannot import .ts directly (needs >= 22 type stripping)`)
}

const FRAME_URL = new URL('../../server/plugins/workbench/src/client/artifact-face-model.ts', import.meta.url)
const HOST_URL = new URL('../../server/plugins/workbench/src/host/artifact-face.ts', import.meta.url)
const VIEW_URL = new URL('../../server/plugins/workbench/src/client/artifact-view-model.ts', import.meta.url)

let M
try {
  M = await import(FRAME_URL.pathname)
} catch (err) {
  envFail('P0: the slice-2 frame module is absent or unimportable on this lane '
    + `(${FRAME_URL.pathname}): ${err?.message ?? err}. There is no frame-and-view seam to judge. `
    + 'Re-point the lane base to the develop line, or merge it, before this gate is judged.')
}

let H
try {
  H = await import(HOST_URL.pathname)
} catch (err) {
  envFail(`the slice-2 host module is absent or unimportable (${HOST_URL.pathname}): ${err?.message ?? err}`)
}

let V
try {
  V = await import(VIEW_URL.pathname)
} catch (err) {
  badCase('view-module-present', `the delivered view model is absent or unimportable (${VIEW_URL.pathname}): ${err?.message ?? err}`)
  finish()
}

/* The surface this ticket's plan promises (D2, D4, D8, A1). A smaller surface is
 * a contract red named here, not a crash further down. */
const NEEDED = ['planArtifactBody', 'runBodyRead', 'readArtifactText', 'resolveArtifactView']
{
  const missingNames = NEEDED.filter(n => typeof V[n] !== 'function')
  check('view-module-declares-its-surface', missingNames.length === 0,
    `present: ${NEEDED.filter(n => typeof V[n] === 'function').join(', ') || 'none'}; missing: ${missingNames.join(', ') || 'none'}`)
  if (missingNames.length > 0) finish()
}

/* ------------------------------------------------------------------ fixtures */

const ROOT = mkdtempSync(join(tmpdir(), 't26103036-seam-'))
process.on('exit', () => { try { rmSync(ROOT, { recursive: true, force: true }) } catch { /* best effort */ } })
const LANE = join(ROOT, 'lane')
const OUT = join(LANE, 'out')
mkdirSync(OUT, { recursive: true })

const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

writeFileSync(join(OUT, 'plan.md'), '# Plan\n\nSee [the gate](javascript:alert(1)).\n<script>alert(2)</script>\n')
writeFileSync(join(OUT, 'tiny.txt'), 'first line\nsecond line\nthird line\n')
writeFileSync(join(OUT, 'event.json'), JSON.stringify({ units: [{ id: 'u1', w: 1 }, { id: 'u2', w: 2 }] }))
writeFileSync(join(OUT, 'rows.csv'), 'id,w\nu1,1\nu2,2\n')
writeFileSync(join(OUT, 'patch.diff'), [
  'diff --git a/a.txt b/a.txt',
  '--- a/a.txt',
  '+++ b/a.txt',
  '@@ -1,2 +1,2 @@',
  ' keep',
  '-old',
  '+new',
  'diff --git a/b.txt b/b.txt',
  '--- a/b.txt',
  '+++ b/b.txt',
  '@@ -1,1 +1,2 @@',
  ' base',
  '+added',
  '',
].join('\n'))
writeFileSync(join(OUT, 'receipt.json'), JSON.stringify({
  runs: [{
    stage: 'merge_check',
    green: false,
    checks: [
      { check: 'bundle freshness', level: 'green', count: 2 },
      { check: 'engine tests', level: 'red', count: 1, detail: 'test_x failed' },
      { item: 'human sign', by: 'host', done: true, green: true },
    ],
  }],
}))
writeFileSync(join(OUT, 'pic.png'), PNG_1PX)
writeFileSync(join(OUT, 'art.svg'), '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(3)</script></svg>\n')
writeFileSync(join(OUT, 'model.glb'), Buffer.from([0x67, 0x6c, 0x54, 0x46, 0x02, 0x00, 0x00, 0x00]))
writeFileSync(join(OUT, 'big.txt'), 'x'.repeat(M.ARTIFACT_INLINE_MAX_BYTES + 1))
writeFileSync(join(OUT, 'bin.dat'), Buffer.from([0xff, 0xfe, 0x00, 0x41]))
writeFileSync(join(ROOT, 'outside.md'), 'outside the lane root\n')

/** One declared descriptor (the engine's declaration shape, slice 1). */
function D(over) {
  return {
    id: 'x', title: 'X', kind: 'text', kind_known: true, source: 'out/tiny.txt',
    repo: '', stage: '', note: '', open: '', shape: '', optional: false, legacy: false,
    round: null, ...over,
  }
}

const PLANNED = [
  // The six built-in kinds, each reachable through the frame with usable bytes.
  D({ id: 'plan-md', title: 'Plan (markdown)', kind: 'text', source: 'out/plan.md' }),
  D({ id: 'tiny', title: 'Plain text', kind: 'text', source: 'out/tiny.txt' }),
  D({ id: 'event-json', title: 'Event JSON', kind: 'structure', source: 'out/event.json', shape: 'units' }),
  D({ id: 'rows', title: 'Rows CSV', kind: 'structure', source: 'out/rows.csv' }),
  D({ id: 'patch', title: 'Patch (two files)', kind: 'diff', source: 'out/patch.diff' }),
  D({ id: 'gate', title: 'Gate receipt', kind: 'ledger', source: 'out/receipt.json' }),
  D({ id: 'pic', title: 'Picture', kind: 'image', source: 'out/pic.png' }),
  D({ id: 'model', title: 'Model', kind: 'external', source: 'out/model.glb' }),
  // A known image whose bytes the host will NOT serve inline (SVG leaves as a download).
  D({ id: 'vector', title: 'Vector', kind: 'image', source: 'out/art.svg' }),
]

const REFUSED_OR_UNUSABLE = [
  // The frame keeps every one of these rows; the view draws no body and reads nothing.
  D({ id: 'a/b', title: 'Non-addressable id', kind: 'text', source: 'out/tiny.txt' }),
  D({ id: 'absent', title: 'Absent file', kind: 'text', source: 'out/absent.md' }),
  D({ id: 'big', title: 'Over the in-page cap', kind: 'text', source: 'out/big.txt' }),
  D({ id: 'binary', title: 'Not UTF-8', kind: 'text', source: 'out/bin.dat' }),
  D({ id: 'escape', title: 'Outside the root', kind: 'text', source: '../outside.md' }),
  D({ id: 'web', title: 'URL source', kind: 'external', source: 'https://example.invalid/model.step' }),
  D({ id: 'hologram', title: 'Unknown kind', kind: 'hologram', source: 'out/tiny.txt' }),
]

/** Descriptor keys the frame owns; no view may use them. */
const FRAME_ATTEMPTS = [
  D({ id: 'framed', title: 'Framed', kind: 'text', source: 'out/tiny.txt', hidden: true, order: 99, view: 'external', render: 'x' }),
]

const DETAIL = {
  id: 't261030-36',
  worktree: 'lane',
  results: {
    plan: { gen: 1, artifact_descriptors: [...PLANNED, ...FRAME_ATTEMPTS] },
    implement: { gen: 1, artifact_descriptors: REFUSED_OR_UNUSABLE },
  },
}
const STAGE_ORDER = ['plan', 'implement']

/** Run the three halves the way the console does: route inventory -> frame view. */
async function seam(detail) {
  const derived = M.deriveArtifactRows(detail, STAGE_ORDER)
  const inventory = await H.buildArtifactInventory(ROOT, detail, STAGE_ORDER)
  const frame = M.buildArtifactFaceView(derived, inventory.stats, detail)
  return { derived, inventory, frame }
}

let SEAM
try {
  SEAM = await seam(DETAIL)
} catch (err) {
  badCase('seam-builds', `derive/inventory/frame threw: ${err?.stack ?? err}`)
  finish()
}

const keyOf = (row) => `${row.stage}/${row.id}`
const rowByKey = new Map(SEAM.frame.rows.map(r => [keyOf(r), r]))
const sig = (x) => { try { return JSON.stringify(x) ?? 'undefined' } catch { return String(x) } }

/** A throw inside a plan is a red, not a body. */
const planOf = (row) => {
  try { return { plan: V.planArtifactBody(row), threw: null } }
  catch (err) { return { plan: undefined, threw: String(err?.message ?? err) } }
}
const bodyOf = (row) => {
  const { plan, threw } = planOf(row)
  if (threw !== null) return { has: false, plan, threw, text: `threw: ${threw}` }
  const has = !(plan === null || plan === undefined || plan === false
    || (typeof plan === 'object' && plan !== null && plan.body === false))
  return { has, plan, threw: null, text: sig(plan) }
}

/** Exactly how many times the reader is reached through the one read path. */
async function readCount(row) {
  const { plan } = planOf(row)
  let calls = 0
  try {
    await V.runBodyRead(plan, async () => { calls += 1; return 'read' }, undefined)
  } catch { /* the count is the contract; a throw is judged by C-cases */ }
  return calls
}

/* --- A. six kinds, one body each, no row added or hidden ------------------- */

{
  const SIX = ['image', 'text', 'structure', 'diff', 'ledger', 'external']
  const views = SIX.map(k => V.resolveArtifactView(k))
  check('A1-every-kind-resolves', views.every(v => v !== null && v !== undefined),
    `resolveArtifactView -> ${views.map(v => (v === null || v === undefined ? 'null' : typeof v)).join(',')}`)
  const names = views.map(v => (typeof v === 'function' ? v.name : String(v)))
  check('A1-kinds-are-distinct', new Set(names).size === SIX.length,
    `distinct views=${new Set(names).size} of ${SIX.length}: ${names.join(' | ')}`)
  const unknown = V.resolveArtifactView('hologram')
  check('A1-unknown-kind-falls-to-external',
    (typeof unknown === 'function' ? unknown.name : String(unknown)) === names[5],
    `unknown -> ${typeof unknown === 'function' ? unknown.name : String(unknown)}; external -> ${names[5]}`)
}

{
  const expectedCount = DETAIL.results.plan.artifact_descriptors.length
    + DETAIL.results.implement.artifact_descriptors.length
  check('A2-no-row-added-or-hidden', SEAM.frame.rows.length === expectedCount,
    `frame rows=${SEAM.frame.rows.length}, declared=${expectedCount}`)
  const keys = SEAM.frame.rows.map(keyOf)
  check('A2-row-identity-unique', new Set(keys).size === keys.length,
    `unique=${new Set(keys).size} of ${keys.length}: ${keys.join(',')}`)

  const SIX_ROWS = ['plan/plan-md', 'plan/event-json', 'plan/patch', 'plan/gate', 'plan/pic', 'plan/model']
  const withoutPlan = SIX_ROWS.filter(k => {
    const row = rowByKey.get(k)
    if (row === undefined) return true
    const b = bodyOf(row)
    return !b.has || b.threw !== null
  })
  check('A3-six-kinds-each-draw-a-body', withoutPlan.length === 0,
    withoutPlan.length === 0
      ? `all six kinds plan a body: ${SIX_ROWS.join(', ')}`
      : `no body or a throw for: ${withoutPlan.map(k => `${k}=${bodyOf(rowByKey.get(k) ?? { stage: '?', id: '?' }).text}`).join(' ; ')}`)
}

/* --- B. the frame and the host agree about the same row -------------------- */

{
  const rows = SEAM.frame.rows
  const mismatched = []
  for (const row of rows) {
    const answer = await H.readArtifactBytes(ROOT, DETAIL, row.stage, row.id)
    const frameOffers = row.bytesHref !== null
    if (frameOffers && answer.ok !== true) {
      mismatched.push(`${row.rowKey}: frame offers bytes, host answers ${answer.code} (${answer.reason})`)
    }
    if (!frameOffers && answer.ok === true) {
      mismatched.push(`${row.rowKey}: frame withholds bytes, host serves ${answer.contentType}`)
    }
    if (!frameOffers && String(row.bytesRefusal ?? '').trim() === '') {
      mismatched.push(`${row.rowKey}: frame withholds bytes and names no reason`)
    }
  }
  check('B1-servability-agrees', mismatched.length === 0,
    mismatched.length === 0 ? `${rows.length} rows agree` : mismatched.join(' ; '))

  const dispositionFaults = []
  for (const row of rows) {
    if (row.bytesHref === null) continue
    const answer = await H.readArtifactBytes(ROOT, DETAIL, row.stage, row.id)
    if (answer.ok !== true) continue
    if (answer.disposition !== 'inline' && answer.disposition !== 'attachment') {
      dispositionFaults.push(`${row.rowKey}: disposition=${sig(answer.disposition)}`)
    }
    if (row.kindLabel === 'Image' && answer.disposition === 'attachment' && /^image\//.test(answer.contentType)) {
      dispositionFaults.push(`${row.rowKey}: an attachment served as an inline image type (${answer.contentType})`)
    }
  }
  check('B2-disposition-is-carried', dispositionFaults.length === 0,
    dispositionFaults.length === 0 ? 'every served row carries a valid disposition' : dispositionFaults.join(' ; '))
}

/* --- C. the view plans the body the frame and host made possible ----------- */

{
  const NO_BODY = [
    'implement/a/b', 'implement/absent', 'implement/big', 'implement/binary',
    'implement/escape', 'implement/web', 'implement/hologram',
  ]
  const BODY_NO_TEXT_READ = ['plan/pic', 'plan/vector', 'plan/model']
  const BODY_ONE_READ = ['plan/plan-md', 'plan/tiny', 'plan/event-json', 'plan/rows', 'plan/patch', 'plan/gate', 'plan/framed']
  /** The view each declared kind must reach. The frame hands the RAW kind down: a view that
   *  cannot see it falls to the external card and draws the wrong body (t261030-36 gen0). */
  const KIND_OF = new Map([
    ['plan/plan-md', 'text'], ['plan/tiny', 'text'], ['plan/event-json', 'structure'],
    ['plan/rows', 'structure'], ['plan/patch', 'diff'], ['plan/gate', 'ledger'],
    ['plan/framed', 'text'], ['plan/pic', 'image'], ['plan/vector', 'image'],
    ['plan/model', 'external'],
  ])

  for (const key of NO_BODY) {
    const row = rowByKey.get(key)
    if (row === undefined) { badCase(`C-row-present-${key}`, 'the frame dropped the row'); continue }
    const b = bodyOf(row)
    check(`C1-no-body-${key}`, b.has === false && b.threw === null,
      `planArtifactBody -> ${b.text} (expected no body: the frame already refused these bytes)`)
    check(`C2-no-read-${key}`, (await readCount(row)) === 0, `reader calls=${await readCount(row)} (expected 0)`)
  }

  for (const key of BODY_NO_TEXT_READ) {
    const row = rowByKey.get(key)
    if (row === undefined) { badCase(`C-row-present-${key}`, 'the frame dropped the row'); continue }
    const b = bodyOf(row)
    check(`C3-body-without-a-text-read-${key}`, b.has && b.threw === null,
      `planArtifactBody -> ${b.text} (expected a body that needs no text read)`)
    check(`C4-no-read-${key}`, (await readCount(row)) === 0,
      `reader calls=${await readCount(row)} (expected 0: image/external bodies do not read text)`)
    check(`C4-kind-${key}`, b.plan?.kind === KIND_OF.get(key),
      `plan.kind=${sig(b.plan?.kind)} (expected ${KIND_OF.get(key)}: the declared kind reaches its own view)`)
  }

  for (const key of BODY_ONE_READ) {
    const row = rowByKey.get(key)
    if (row === undefined) { badCase(`C-row-present-${key}`, 'the frame dropped the row'); continue }
    const b = bodyOf(row)
    check(`C5-body-${key}`, b.has && b.threw === null, `planArtifactBody -> ${b.text} (expected a body)`)
    check(`C6-exactly-one-read-${key}`, (await readCount(row)) === 1,
      `reader calls=${await readCount(row)} (expected exactly 1: one read per row per expand)`)
    check(`C6-kind-${key}`, b.plan?.kind === KIND_OF.get(key),
      `plan.kind=${sig(b.plan?.kind)} (expected ${KIND_OF.get(key)}: the declared kind reaches its own view)`)
  }

  // The SVG row is a KNOWN image whose bytes the host refuses to inline. It must
  // draw the external card, not an <img> body, and that card must differ from the
  // inline PNG body.
  const png = rowByKey.get('plan/pic')
  const svg = rowByKey.get('plan/vector')
  if (png !== undefined && svg !== undefined) {
    check('C7-non-inline-image-is-not-the-inline-body', bodyOf(png).text !== bodyOf(svg).text,
      `png plan=${bodyOf(png).text}; svg plan=${bodyOf(svg).text}`)
    // The two plans also differ by title and size, so the case above holds even when both
    // rows are external cards. Pin the image body itself: only the image view may produce it.
    check('C8-inline-image-plans-the-image-body',
      bodyOf(png).plan?.kind === 'image' && bodyOf(png).plan?.read === 'image',
      `png plan=${bodyOf(png).text} (expected kind=image, read=image: an <img> body, no text read)`)
    check('C9-non-inline-image-is-handed-to-the-image-view-with-its-reason',
      bodyOf(svg).plan?.kind === 'image' && bodyOf(svg).plan?.read === 'none'
        && String(bodyOf(svg).plan?.why ?? '').trim() !== '',
      `svg plan=${bodyOf(svg).text} (expected the image view's named download card, not the external view)`)
  }
}

/* --- D. the view's read classification against route-shaped answers -------- */

{
  const HREF = 'http://lane.invalid/wf/tickets/t1/artifacts/plan/tiny/bytes'

  const response = (status, contentType, body) => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    headers: { get: (n) => (String(n).toLowerCase() === 'content-type' ? contentType : null) },
    text: async () => body,
    json: async () => JSON.parse(body),
    arrayBuffer: async () => Buffer.from(body),
    clone() { return this },
  })
  const routeFail = (status, code, error) => async () => response(status, 'application/json', JSON.stringify({ ok: false, code, error }))

  const CASES = [
    { name: 'D1-served-text-is-ok', run: async () => response(200, 'text/plain; charset=utf-8', 'first line\n'), must: null, mustNot: /error|fail|busy/i },
    { name: 'D2-too-large-names-the-answer', run: routeFail(413, 'too_large', '1048577 bytes, over the 1048576 byte in-page limit'), must: /too_large|too large/i },
    { name: 'D3-not-utf8-names-the-answer', run: routeFail(400, 'not_utf8', 'the text is not valid UTF-8'), must: /not_utf8|utf-?8/i },
    { name: 'D4-not-found-names-the-answer', run: routeFail(404, 'not_found', 'no such artifact'), must: /not_found|not found|404/i },
    { name: 'D5-ambiguous-names-the-answer', run: routeFail(409, 'ambiguous', 'two sources in the newest round'), must: /ambiguous|409/i },
    { name: 'D6-busy-names-the-answer', run: routeFail(503, 'busy', 'All 4 artifact read slots are in use; try again'), must: /busy|503/i },
    { name: 'D7-wrong-content-type-is-named', run: async () => response(200, 'application/octet-stream', 'binary'), must: /octet|content[- ]?type/i },
    { name: 'D8-network-error-is-named', run: async () => { throw new TypeError('fetch failed') }, must: /network|fetch|fail/i },
  ]

  for (const cse of CASES) {
    let answer
    try {
      answer = await V.readArtifactText(HREF, cse.run, undefined)
    } catch (err) {
      badCase(cse.name, `readArtifactText threw instead of classifying: ${err?.message ?? err}`)
      continue
    }
    const text = sig(answer)
    const named = cse.must === null ? true : cse.must.test(text)
    const notTheError = cse.mustNot === undefined ? true : !cse.mustNot.test(text)
    check(cse.name, named && notTheError && text !== 'undefined' && text !== 'null',
      `answer=${text}${cse.must === null ? '' : `; expected /${cse.must.source}/`}`)
  }

  {
    // Abort is a named state: it never throws and never reaches the reader.
    const ctrl = new AbortController()
    ctrl.abort()
    let answer
    let threw = null
    try {
      answer = await V.readArtifactText(HREF, async () => { throw new Error('the stub must not be reached after abort') }, ctrl.signal)
    } catch (err) {
      threw = err
    }
    check('D9-abort-is-named-not-thrown', threw === null && /abort|cancel/i.test(sig(answer)),
      threw === null ? `answer=${sig(answer)}` : `threw: ${threw?.message ?? threw}`)
  }
}

/* --- E. one damaged artifact never drops a row, never blanks the panel ----- */

{
  const baseline = new Map(SEAM.frame.rows.map(r => [keyOf(r), bodyOf(r).text]))
  const baselineKeys = SEAM.frame.rows.map(keyOf).join(',')

  const DAMAGE = [
    { file: 'event.json', key: 'plan/event-json', bytes: '{"units":[{"id":' },
    { file: 'rows.csv', key: 'plan/rows', bytes: 'a,b\n"unclosed,2\n' },
    { file: 'patch.diff', key: 'plan/patch', bytes: '@@ -1,2 +1,2 @@\n+x\n' },
    { file: 'receipt.json', key: 'plan/gate', bytes: '12345' },
    { file: 'plan.md', key: 'plan/plan-md', bytes: Buffer.from([0x00, 0x01, 0x02, 0xff]) },
  ]

  for (const dmg of DAMAGE) {
    const target = join(OUT, dmg.file)
    const keep = readFileSync(target)
    writeFileSync(target, dmg.bytes)
    let after
    try {
      after = await seam(DETAIL)
    } catch (err) {
      badCase(`E1-no-throw-${dmg.file}`, `one damaged artifact took the seam down: ${err?.message ?? err}`)
      writeFileSync(target, keep)
      continue
    }
    writeFileSync(target, keep)

    check(`E2-rows-stable-${dmg.file}`, after.frame.rows.map(keyOf).join(',') === baselineKeys,
      `row set changed=${after.frame.rows.map(keyOf).join(',') !== baselineKeys}`)

    const row = after.frame.rows.find(r => keyOf(r) === dmg.key)
    if (row === undefined) { badCase(`E3-row-still-present-${dmg.file}`, `${dmg.key} disappeared`); continue }
    const b = bodyOf(row)
    check(`E3-no-throw-${dmg.file}`, b.threw === null, `planArtifactBody threw: ${b.threw}`)
    check(`E4-damaged-body-differs-or-is-absent-${dmg.file}`, b.text !== baseline.get(dmg.key),
      `healthy=${baseline.get(dmg.key)}; damaged=${b.text}`)

    const sibling = after.frame.rows.find(r => keyOf(r) === 'plan/tiny')
    check(`E5-sibling-untouched-${dmg.file}`, bodyOf(sibling).text === baseline.get('plan/tiny'),
      `sibling plan changed=${bodyOf(sibling).text !== baseline.get('plan/tiny')}`)
  }
}

/* --- F. a display hint has no authority over the row list ------------------ */

{
  const plainDetail = { id: 't9', worktree: 'lane', results: { plan: { gen: 1, artifact_descriptors: [
    D({ id: 'a', title: 'A', kind: 'text', source: 'out/tiny.txt' }),
    D({ id: 'b', title: 'B', kind: 'text', source: 'out/plan.md' }),
  ] } } }
  const attackedDetail = { id: 't9', worktree: 'lane', results: { plan: { gen: 1, artifact_descriptors: [
    D({ id: 'a', title: 'A', kind: 'text', source: 'out/tiny.txt', hidden: true, order: 99, view: 'external', render: 'x' }),
    D({ id: 'b', title: 'B', kind: 'text', source: 'out/plan.md', hidden: false }),
  ] } } }

  const plain = await seam(plainDetail)
  const attacked = await seam(attackedDetail)
  const keys = (s) => s.frame.rows.map(keyOf).join(',')
  check('F1-frame-owned-keys-cannot-hide-a-row', keys(plain) === keys(attacked),
    `plain=[${keys(plain)}]; with frame-owned keys=[${keys(attacked)}]`)
  const plans = (s) => s.frame.rows.map(r => bodyOf(r).text).join('|')
  check('F2-frame-owned-keys-cannot-redraw-a-row', plans(plain) === plans(attacked),
    `plans differ=${plans(plain) !== plans(attacked)}`)
}

/* --- G. byte slots: saturation is named, every slot comes back ------------ */

{
  const slots = H.ARTIFACT_BYTES_SLOTS
  let release
  const gate = new Promise(res => { release = res })
  const held = []
  for (let i = 0; i < slots; i += 1) held.push(H.withArtifactSlot(async () => { await gate; return 'held' }))

  const fifth = await H.withArtifactSlot(async () => 'unexpected')
  check('G1-saturation-is-named', fifth !== null && fifth !== undefined && fifth.ok === false && fifth.code === 'busy',
    `fifth slot answer=${sig(fifth)}`)
  check('G2-saturation-names-a-reason', String(fifth?.reason ?? '').trim() !== '',
    `reason=${sig(fifth?.reason)}`)

  release()
  await Promise.all(held)
  check('G3-slots-return-after-success', H.activeArtifactSlots() === 0,
    `active slots after release=${H.activeArtifactSlots()}`)

  let captured = null
  try { await H.withArtifactSlot(async () => { throw new Error('planted reader fault') }) } catch (err) { captured = err }
  check('G4-slot-returns-after-throw', captured !== null && H.activeArtifactSlots() === 0,
    `threw=${captured?.message ?? 'no'}; active slots=${H.activeArtifactSlots()}`)

  const answer = await H.withArtifactSlot(() => H.readArtifactBytes(ROOT, DETAIL, 'plan', 'tiny'))
  check('G5-a-real-read-still-works', answer?.ok === true && H.activeArtifactSlots() === 0,
    `answer.ok=${answer?.ok}; active slots=${H.activeArtifactSlots()}`)
}

finish()
