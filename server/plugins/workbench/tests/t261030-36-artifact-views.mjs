#!/usr/bin/env node
/**
 * tests/t261030-36-artifact-views.mjs — the six built-in artifact views, model layer
 * (epic artifact-face, slice 3, ticket t261030-36). Developer L1 battery.
 *
 * What is pinned here:
 *   A THE RENDER RULE — one plan decides whether a row gets a body and whether it needs a
 *     read; the six kinds resolve, an unknown kind resolves to the external seam; a degrade
 *     row, a not-servable row (`card === 'row'` with no bytes) and a non-inline image make
 *     ZERO reads, and a text row makes exactly one.
 *   B THE READ PATH — every failure is named: an HTTP status with the route's own error, a
 *     wrong content type, a network error and an abort; the reader receives the signal.
 *   C TEXT — markdown and plain text, the display caps, binary detection, and the markdown
 *     suffix pin against the repo's own classifier (`classifyPath`).
 *   D STRUCTURE — a JSON table through `shape`, the tree fallback (no shape, a miss, a
 *     scalar), CSV, the YAML/TOML line view, malformed JSON, empty input and the caps.
 *   E DIFF — the model reuses `parseUnifiedDiff`: one file, a multi-file diff, the added-file
 *     synthetic hunk, the named fallbacks and the display cap.
 *   F LEDGER — receipt documents go through the ONE accessor (`buildChecksDetail`): the
 *     script and agent shapes, the conflict rule, the no-signal rule, a dropped empty green
 *     row and a run-level disagreement; the status-word list applies only to non-receipt
 *     documents, where an unknown status stays neutral.
 *   G LIGHTBOX — the shared key contract and the malformed-input navigation.
 *
 * No browser, no network, no console port: a stub fetch feeds the read cases.
 * Run: node server/plugins/workbench/tests/t261030-36-artifact-views.mjs (cwd = repo root)
 */
import assert from 'node:assert/strict'
import { classifyPath } from '../src/host/changes.ts'
import {
  ARTIFACT_KINDS, buildArtifactFaceView, deriveArtifactRows,
} from '../src/client/artifact-face-model.ts'
import {
  ARTIFACT_VIEWS, INLINE_IMAGE_SUFFIXES, LEDGER_DISPLAY_MAX_ENTRIES, MARKDOWN_SUFFIXES, TABLE_DISPLAY_MAX_ROWS,
  TEXT_DISPLAY_MAX_LINES, TREE_DISPLAY_MAX_DEPTH, VIEW_KINDS, VIEW_TITLE,
  buildDiffView, buildLedgerView, buildStructureView, buildTextView, clipText, isMarkdownSource,
  imageIsInline, parseCsvRows, parseShapePath, planArtifactBody, readArtifactText, readShapeTarget,
  resolveArtifactView, runBodyRead, shouldRenderBody, sourceSuffix, textLooksBinary,
} from '../src/client/artifact-view-model.ts'
import { LIGHTBOX_KEYS, lightboxNav } from '../src/client/lightbox-model.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) { pass += 1; console.log(`  ok ${label}`) }
  else { fail += 1; console.error(`  FAIL ${label}`) }
}
function eq(label, actual, expected) {
  const a = JSON.stringify(actual)
  const e = JSON.stringify(expected)
  ok(a === e, `${label} (expected ${e}, got ${a})`)
}
function section(title) { console.log(`\n== ${title}`) }

const OK_STAT = { state: 'ok', sizeBytes: 12, mtimeMs: Date.UTC(2026, 9, 30, 12, 0) }

/**
 * Build the row the console really gets: a declared descriptor through the REAL derivation
 * and the REAL frame view. A fixture that invents a field the production type does not
 * declare is how the missing `kind` field stayed green (arbitrate gen0), so this helper
 * never hand-builds a row.
 */
function row(descriptor = {}, stat = OK_STAT) {
  const detail = {
    id: 't1',
    results: {
      plan: {
        gen: 1,
        artifact_descriptors: [{ id: 'report', title: 'Report', kind: 'text', source: 'out/a.md', ...descriptor }],
      },
    },
  }
  const derived = deriveArtifactRows(detail, ['plan'])
  const key = derived.rows[0].rowKey
  return buildArtifactFaceView(derived, { [key]: stat }, detail).rows[0]
}
const HREF = '/sandbar-workbench/api/wf/tickets/t1/artifacts/plan/report/bytes'

/* ------------------------------------------------------------ A. the rule */

section('A. render rule and the zero-read classes')
{
  eq('A1 the view kinds ARE the engine vocabulary (one source)', VIEW_KINDS, ARTIFACT_KINDS)
  for (const kind of ARTIFACT_KINDS) {
    ok(`A1 ${kind} resolves to its own view function`, resolveArtifactView(kind) === ARTIFACT_VIEWS[kind])
    ok(`A1 ${kind} is a callable view`, typeof resolveArtifactView(kind) === 'function')
  }
  eq('A1 the six view functions are distinct', new Set(ARTIFACT_KINDS.map(k => ARTIFACT_VIEWS[k].name)).size, 6)
  eq('A1 an unknown kind falls to the external view', resolveArtifactView('hologram').name, ARTIFACT_VIEWS.external.name)
  eq('A1 a non-string kind falls to the external view', resolveArtifactView(null).name, ARTIFACT_VIEWS.external.name)
  eq('A1 every kind has an English title', ARTIFACT_KINDS.map(k => VIEW_TITLE[k]),
    ['Image', 'Text', 'Structure', 'Diff', 'Ledger', 'External'])

  const text = planArtifactBody(row(), HREF)
  eq('A2 a text row plans one text read', [text.body, text.read, text.href], [true, 'text', HREF])
  const structure = planArtifactBody(row({ kind: 'structure', source: 'out/x.json' }), HREF)
  eq('A2 a structure row plans one text read', structure.read, 'text')
  const png = planArtifactBody(row({ kind: 'image', source: 'out/x.png' }), HREF)
  eq('A2 a raster image plans an image body (no text read)', [png.body, png.read], [true, 'image'])
  const svg = planArtifactBody(row({ kind: 'image', source: 'out/x.svg' }), HREF)
  eq('A2 an SVG image plans the external card (the host serves it as a download)',
    [svg.body, svg.read, svg.href !== ''], [true, 'none', true])
  ok(svg.why !== '', 'A2 the SVG degrade names why it is not drawn as an image')
  const external = planArtifactBody(row({ kind: 'external', source: 'out/x.glb' }), HREF)
  eq('A2 an external row plans a body with no read', [external.body, external.read], [true, 'none'])

  const degrade = row({}, { state: 'missing', reason: 'no file' })
  eq('A3 a degrade row plans no body', planArtifactBody(degrade, HREF).body, false)
  eq('A3 shouldRenderBody agrees with the plan', shouldRenderBody(degrade, HREF), false)
  const notServable = row({ id: 'a/b' })  // non-addressable id: card row, no servable bytes
  eq('A3 a card-row with no servable bytes plans no body', planArtifactBody(notServable, null).body, false)
  eq('A3 its refusal is carried as the named reason',
    planArtifactBody(notServable, null).why.includes('not addressable'), true)
  eq('A3 a degrade row with an href still plans no body', planArtifactBody(degrade, HREF).body, false)
  eq('A3 the href is optional (the frame byte signal decides)', planArtifactBody(row(), null).body, true)
  const unknown = row({ kind: 'hologram' })
  eq('A3 an unknown-kind row is degraded by the frame and plans no body',
    planArtifactBody(unknown, HREF).body, false)

  const suffixes = INLINE_IMAGE_SUFFIXES
  eq('A4 the inline image list is the host table', suffixes, ['.png', '.jpg', '.jpeg', '.webp', '.gif'])
  for (const s of suffixes) ok(imageIsInline(`a/b${s}`), `A4 ${s} is inline`)
  for (const s of ['.svg', '.bmp', '.ico']) ok(!imageIsInline(`a/b${s}`), `A4 ${s} is not inline`)
  eq('A4 the suffix is case-insensitive', imageIsInline('A/B.PNG'), true)
  eq('A4 a suffix-less source is not an inline image', imageIsInline('out/Makefile'), false)
  eq('A4 sourceSuffix reads the last segment', sourceSuffix('a.b/c.d.png'), '.png')

  eq('A5 the markdown list is .md and .markdown', MARKDOWN_SUFFIXES, ['.md', '.markdown'])
  for (const p of ['docs/x.md', 'notes/x.markdown', 'CLAUDE.md', 'X.MD']) {
    eq(`A5 ${p}: isMarkdownSource agrees with classifyPath`, isMarkdownSource(p), classifyPath(p) === 'doc')
  }
  eq('A5 a text file is not markdown', isMarkdownSource('out/a.txt'), false)

  // The zero-read rule through the ONE read entry.
  const calls = []
  const reader = async (href, signal) => { calls.push([href, signal === undefined ? 'none' : 'signal']); return { ok: true, text: 'x' } }
  const noSignal = undefined
  const cases = [
    ['degrade', degrade],
    ['not-servable', notServable],
    ['external', row({ kind: 'external', source: 'out/x.glb' })],
    ['image', row({ kind: 'image', source: 'out/x.png' })],
  ]
  for (const [name, r] of cases) {
    const plan = planArtifactBody(r, name === 'not-servable' ? null : HREF)
    const got = await runBodyRead(plan, reader, noSignal)
    eq(`A6 ${name}: runBodyRead returns null`, got, null)
    eq(`A6 ${name}: the reader is never called`, calls.length, 0)
  }
  const textPlan = planArtifactBody(row(), HREF)
  const got = await runBodyRead(textPlan, reader, noSignal)
  eq('A6 a text row reaches the reader exactly once', calls.length, 1)
  eq('A6 it passes the plan href and the signal', calls[0][0], HREF)
  eq('A6 the text answer is returned', got.ok, true)
}

/* ------------------------------------------------------------ B. reads */

section('B. read classification')
{
  const okRes = (text, contentType = 'text/plain; charset=utf-8') => ({
    ok: true, status: 200, headers: { get: () => contentType }, text: async () => text,
  })
  const errRes = (status, body) => ({
    ok: false, status,
    headers: { get: () => 'application/json; charset=utf-8' },
    text: async () => JSON.stringify(body),
    json: async () => body,
  })

  const served = await readArtifactText(HREF, async () => okRes('hello'))
  eq('B1 served text is returned', [served.ok, served.text], [true, 'hello'])

  for (const status of [404, 409, 413, 503, 400]) {
    const got = await readArtifactText(HREF, async () => errRes(status, { ok: false, error: `route says ${status}` }))
    eq(`B2 HTTP ${status} is an http failure`, [got.ok, got.kind, got.status], [false, 'http', status])
    ok(got.message.includes(`route says ${status}`), `B2 HTTP ${status} carries the route's own message`)
  }
  const noBody = await readArtifactText(HREF, async () => ({
    ok: false, status: 502, headers: { get: () => 'application/json' }, text: async () => 'oops',
  }))
  eq('B3 a non-JSON error body still names the status', [noBody.kind, noBody.status, noBody.message], ['http', 502, 'HTTP 502'])

  const wrongType = await readArtifactText(HREF, async () => okRes('\u0000\u0001', 'image/png'))
  eq('B4 a non-text content type is named', [wrongType.ok, wrongType.kind], [false, 'content-type'])
  ok(wrongType.message.includes('image/png'), 'B4 the message names the type')

  const network = await readArtifactText(HREF, async () => { throw new Error('offline') })
  eq('B5 a thrown fetch is a network failure', [network.ok, network.kind, network.message], [false, 'network', 'offline'])

  const abortErr = new Error('aborted'); abortErr.name = 'AbortError'
  const aborted = await readArtifactText(HREF, async () => { throw abortErr })
  eq('B6 an AbortError is a named abort', [aborted.ok, aborted.kind], [false, 'aborted'])
  const controller = new AbortController(); controller.abort()
  const preAborted = await readArtifactText(HREF, async () => { throw new Error('x') }, controller.signal)
  eq('B6 a pre-aborted signal is a named abort', preAborted.kind, 'aborted')

  // The reader receives the signal and the GET shape.
  let seenInit = null
  await readArtifactText(HREF, async (_href, init) => { seenInit = init; return okRes('x') })
  eq('B7 the reader uses GET and asks for text', [seenInit.method, seenInit.headers.accept], ['GET', 'text/plain'])
}

/* ------------------------------------------------------------ C. text */

section('C. text, markdown and caps')
{
  const md = buildTextView('# Title\n\nbody', 'x.md')
  eq('C1 a .md source is markdown', md.mode, 'markdown')
  eq('C1 a .markdown source is markdown', buildTextView('x', 'a/x.markdown').mode, 'markdown')
  eq('C1 a .txt source is plain text', buildTextView('x', 'a/x.txt').mode, 'text')
  eq('C1 an absent source is plain text', buildTextView('x', null).mode, 'text')

  const clip = clipText('abcdef', 3, 50)
  eq('C2 a short text is not clipped', clipText('abc', 100, 50).truncated, false)
  ok(clip.truncated && clip.note !== '', 'C2 a long text is clipped and says so')
  eq('C2 the clipped text keeps the prefix', clip.text, 'abc')
  const many = Array.from({ length: TEXT_DISPLAY_MAX_LINES + 5 }, (_, i) => String(i)).join('\n')
  const lineClip = clipText(many, 10_000_000, TEXT_DISPLAY_MAX_LINES - 1)
  eq('C2 the line cap bites', lineClip.lines.length, TEXT_DISPLAY_MAX_LINES - 1)
  ok(lineClip.note.includes('first'), 'C2 the line clip says it is partial')

  eq('C3 a NUL byte is binary', textLooksBinary('a\u0000b'), true)
  eq('C3 a replacement character is binary', textLooksBinary('a\uFFFDb'), true)
  eq('C3 ordinary text is not binary', textLooksBinary('plain'), false)
}

/* --------------------------------------------------------- D. structure */

section('D. structure: shape, table, tree, CSV, YAML, malformed')
{
  eq('D1 shape paths split on dots and drop []', parseShapePath('units[]'), ['units'])
  eq('D1 a dotted path and $. prefix', parseShapePath('$.data.items[]'), ['data', 'items'])
  eq('D1 an empty shape is no path', parseShapePath(''), [])
  eq('D1 a numeric segment indexes', readShapeTarget({ a: [{ b: 2 }] }, ['a', '0', 'b']), { found: true, value: 2 })
  eq('D1 a missing key is named', readShapeTarget({ a: 1 }, ['b']), { found: false, value: undefined })
  eq('D1 a scalar mid-path is not found', readShapeTarget({ a: 1 }, ['a', 'b']), { found: false, value: undefined })

  const doc = JSON.stringify({ units: [{ id: 'a', w: 1 }, { id: 'b', w: 2, extra: true }], note: 'x' })
  const table = buildStructureView(doc, 'x.json', 'units[]')
  eq('D2 a shape hit is a table', table.mode, 'table')
  eq('D2 the columns are the record keys', table.columns, ['id', 'w', 'extra'])
  eq('D2 the rows are the values', table.rows, [['a', '1', ''], ['b', '2', 'true']])
  ok(table.note.includes('main table'), 'D2 the note names the declared table')
  eq('D2 the data path also works', buildStructureView(doc, 'x.json', 'data.items').mode, 'tree')

  const noShape = buildStructureView(doc, 'x.json', '')
  eq('D3 no shape is a tree (design §4.1)', noShape.mode, 'tree')
  eq('D3 the tree lists the document keys', noShape.nodes.map(n => n.label), ['units', 'note'])
  const miss = buildStructureView(doc, 'x.json', 'nope[]')
  eq('D3 a shape miss is a tree of the whole document', miss.mode, 'tree')
  ok(miss.note.includes('was not found'), 'D3 the miss is named')
  const scalar = buildStructureView(JSON.stringify({ count: 3 }), 'x.json', 'count')
  eq('D3 a scalar shape is a tree of the document', scalar.mode, 'tree')
  ok(scalar.note.includes('scalar'), 'D3 the scalar case is named')

  const csv = 'id,w\n"a,1",2\nb,3\n'
  const csvTable = buildStructureView(csv, 'x.csv', '')
  eq('D4 CSV is a table without a shape', csvTable.mode, 'table')
  eq('D4 the header names the columns', csvTable.columns, ['id', 'w'])
  eq('D4 a quoted comma stays one cell', csvTable.rows[0], ['a,1', '2'])
  const ragged = buildStructureView('a,b\n1\n', 'x.csv', '')
  ok(ragged.mode === 'table' && ragged.note.includes('different column count'), 'D4 a ragged row is named')
  const badCsv = buildStructureView('a,"b\n', 'x.csv', '')
  ok(badCsv.mode === 'text' && badCsv.note.includes('quoted field'), 'D4 an unterminated quote falls back to text')
  eq('D4 parseCsvRows handles doubled quotes', parseCsvRows('"a""b"\n').rows[0][0], 'a"b')

  const yaml = buildStructureView('a: 1\nb:\n  - x\n', 'x.yaml', '')
  eq('D5 YAML is the indented line view', yaml.mode, 'lines')
  ok(yaml.note.includes('no YAML parser'), 'D5 the line view names the missing parser')
  eq('D5 TOML uses the same line view', buildStructureView('a = 1\n', 'x.toml', '').mode, 'lines')

  const malformed = buildStructureView('{bad', 'x.json', '')
  ok(malformed.mode === 'text' && malformed.note.includes('Not valid JSON'), 'D6 malformed JSON falls back to text')
  const empty = buildStructureView('  ', 'x.json', '')
  ok(empty.mode === 'text' && empty.note.includes('empty'), 'D6 an empty file is named')
  eq('D6 a JSON scalar is a tree', buildStructureView('42', 'x.json', '').mode, 'tree')

  const wide = JSON.stringify(Array.from({ length: TABLE_DISPLAY_MAX_ROWS + 7 }, (_, i) => ({ i })))
  const capTable = buildStructureView(wide, 'x.json', '')
  ok(capTable.mode === 'tree', 'D7 a top-level array without a shape is a tree')
  const capDeclared = buildStructureView(wide, 'x.json', '0')
  ok(capDeclared.mode === 'tree', 'D7 a scalar shape on an array document falls back to the tree')
  const listTable = buildStructureView(JSON.stringify({ rows: JSON.parse(wide) }), 'x.json', 'rows[]')
  ok(listTable.mode === 'table' && listTable.shownRows === TABLE_DISPLAY_MAX_ROWS, 'D7 the table row cap bites')
  ok(listTable.note.includes('of'), 'D7 the table cap is named')

  const deep = { a: { b: { c: { d: { e: { f: { g: 1 } } } } } } }
  const deepTree = buildStructureView(JSON.stringify(deep), 'x.json', '')
  ok(deepTree.mode === 'tree', 'D8 a deep document is a tree')
  const deepNode = deepTree.nodes[0]
  let depth = 0
  let cur = deepNode
  while (cur !== undefined && cur.children.length > 0) { depth += 1; cur = cur.children[0] }
  ok(depth <= TREE_DISPLAY_MAX_DEPTH, 'D8 the depth cap holds')
  const manyKeys = JSON.stringify(Object.fromEntries(Array.from({ length: 700 }, (_, i) => [`k${i}`, i])))
  const capped = buildStructureView(manyKeys, 'x.json', '')
  ok(capped.mode === 'tree' && capped.note.includes('not shown'), 'D8 the node cap is named')
}

/* -------------------------------------------------------------- E. diff */

section('E. diff: reuse, multi-file, fallbacks, cap')
{
  const one = [
    'diff --git a/src/x.ts b/src/x.ts',
    'index 111..222 100644',
    '--- a/src/x.ts',
    '+++ b/src/x.ts',
    '@@ -1,2 +1,3 @@',
    ' const a = 1',
    '-const b = 2',
    '+const b = 3',
    '+const c = 4',
    '\\ No newline at end of file',
    '',
  ].join('\n')
  const body = buildDiffView(one)
  eq('E1 a unified diff is a diff body', body.mode, 'diff')
  eq('E1 the file is named from the header', body.files[0].name, 'src/x.ts')
  eq('E1 the counts are the parser counts', [body.added, body.removed], [2, 1])
  const lines = body.files[0].hunks[0].lines
  eq('E1 the line kinds are carried', lines.map(l => l.kind), ['context', 'removed', 'added', 'added'])
  eq('E1 both line numbers are carried', [lines[0].oldLine, lines[0].newLine], [1, 1])
  eq('E1 a removed line has no new number', lines[1].newLine, null)

  const two = one + '\ndiff --git a/src/y.ts b/src/y.ts\n--- a/src/y.ts\n+++ b/src/y.ts\n@@ -1 +1 @@\n-a\n+b\n'
  const multi = buildDiffView(two)
  eq('E2 a multi-file diff keeps one file per entry', [multi.mode, multi.files.length], ['diff', 2])
  eq('E2 the second file is named', multi.files[1].name, 'src/y.ts')

  const added = ['diff --git a/new.md b/new.md', 'new file mode 100644', '--- /dev/null', '+++ b/new.md', '+line one', '+line two', ''].join('\n')
  const addedBody = buildDiffView(added)
  eq('E3 the added-file form parses through the synthetic hunk', [addedBody.mode, addedBody.added], ['diff', 2])

  const crlf = one.replace(/\n/g, '\r\n')
  eq('E4 CRLF is normalised', buildDiffView(crlf).mode, 'diff')

  const empty = buildDiffView('')
  ok(empty.mode === 'text' && empty.note.includes('empty'), 'E5 an empty diff is named')
  const prose = buildDiffView('this is not a diff\nnor is this')
  ok(prose.mode === 'text' && prose.note.includes('Not a readable unified diff'), 'E5 non-diff text falls back')

  const huge = ['diff --git a/big.txt b/big.txt', '--- a/big.txt', '+++ b/big.txt', '@@ -0,0 +1,2500 @@']
    .concat(Array.from({ length: 2500 }, (_, i) => `+line ${i}`)).join('\n')
  const capped = buildDiffView(huge)
  eq('E6 the added count covers the whole parse', capped.mode === 'diff' ? capped.added : -1, 2500)
  const shown = capped.mode === 'diff' ? capped.files[0].hunks.reduce((n, h) => n + h.lines.length, 0) : -1
  ok(shown > 0 && shown < 2500, 'E6 the display cap keeps the page bounded')
  ok(capped.mode === 'diff' && capped.files[0].hunks.some(h => h.truncated), 'E6 the truncation is named on the hunk')
}

/* ------------------------------------------------------------ F. ledger */

section('F. ledger: the one accessor, the word list, the counts')
{
  const green = buildLedgerView(JSON.stringify({ checks: [{ check: 'units', level: 'green', count: 3 }] }), '')
  eq('F1 a script green row is a receipt', green.mode, 'receipt')
  eq('F1 the run verdict comes from the level field', green.runs[0].verdict, 'green')
  eq('F1 the row is green', green.runs[0].entries[0].color, 'green')
  eq('F1 the row is named from check', green.runs[0].entries[0].name, 'units')
  eq('F1 the count is carried', green.runs[0].entries[0].count, '3')
  eq('F1 the totals count green rows', [green.green, green.red, green.neutral], [1, 0, 0])

  const red = buildLedgerView(JSON.stringify({ checks: [{ check: 'shape', level: 'red', count: 2 }] }), '')
  eq('F2 a script red row is red', [red.runs[0].entries[0].color, red.runs[0].redCount], ['red', 1])
  eq('F2 the run verdict is red', red.runs[0].verdict, 'red')

  const agent = buildLedgerView(JSON.stringify({ checks: [{ item: 'code review', by: 'x', done: true, green: true }] }), '')
  eq('F3 an agent green row is green', agent.runs[0].entries[0].color, 'green')
  const agentRed = buildLedgerView(JSON.stringify({ checks: [{ item: 'code review', by: 'x', done: false }] }), '')
  eq('F3 an agent done:false row is red', agentRed.runs[0].entries[0].color, 'red')

  const conflict = buildLedgerView(JSON.stringify({ checks: [{ item: 'x', green: true, done: false }] }), '')
  eq('F4 conflicting signals resolve red', conflict.runs[0].entries[0].color, 'red')
  const noSignal = buildLedgerView(JSON.stringify({ checks: [{ item: 'y' }] }), '')
  eq('F4 no signal resolves red (the accessor rule)', noSignal.runs[0].entries[0].color, 'red')

  const dropped = buildLedgerView(JSON.stringify({ checks: [{ green: true }] }), '')
  eq('F5 a green row with no name and no payload is not a row', dropped.runs[0].entries.length, 0)
  eq('F5 the totals stay honest', [dropped.green, dropped.red], [0, 0])

  const disagree = buildLedgerView(JSON.stringify({
    stage: 'merge_check', verdict: 'green', checks: [{ item: 'a', done: true, green: false }],
  }), '')
  eq('F6 a run whose verdict and rows disagree is flagged', disagree.runs[0].disagreement, true)
  eq('F6 both signals are shown', [disagree.runs[0].verdict, disagree.runs[0].entries[0].color], ['green', 'red'])

  const runs = buildLedgerView(JSON.stringify({
    runs: [
      { stage: 'a', green: true, checks: [{ item: 'a1', green: true }] },
      { stage: 'b', green: false, checks: [{ item: 'b1', green: false }] },
    ],
  }), '')
  eq('F7 a runs list keeps one section per run', [runs.mode, runs.runs.length], ['receipt', 2])
  eq('F7 the labels are the run stages', runs.runs.map(r => r.label), ['b', 'a'])

  const generic = buildLedgerView(JSON.stringify([
    { name: 'a', status: 'ok' }, { name: 'b', status: 'blocked' }, { name: 'c' },
  ]), '')
  eq('F8 a top-level array is a generic ledger', generic.mode, 'generic')
  eq('F8 the counts sum to the entries', [generic.green, generic.red, generic.neutral], [1, 1, 1])
  eq('F8 an unknown status is neutral', generic.entries[2].color, 'neutral')

  const worded = buildLedgerView(JSON.stringify({ entries: [
    { name: 't', status: true }, { name: 'f', status: false }, { name: 's', status: 'success' },
    { name: 'u', status: 'unknown' }, { name: 'w', status: 'warn' },
  ] }), '')
  eq('F8 the word list maps booleans and words', worded.entries.map(e => e.color),
    ['green', 'red', 'green', 'neutral', 'neutral'])

  const shaped = buildLedgerView(JSON.stringify({ data: { rows: [{ name: 'x', status: 'ok' }] } }), 'data.rows[]')
  ok(shaped.mode === 'generic' && shaped.entries.length === 1, 'F9 a declared shape names the generic list')
  const unknown = buildLedgerView(JSON.stringify({ hello: 'world' }), '')
  ok(unknown.mode === 'text' && unknown.note.includes('not recognized'), 'F9 an unrecognized shape falls back to text')
  const scalar = buildLedgerView('"just a string"', '')
  ok(scalar.mode === 'text' && scalar.note.includes('scalar'), 'F9 a scalar ledger falls back to text')
  const bad = buildLedgerView('{bad', '')
  ok(bad.mode === 'text' && bad.note.includes('Not valid JSON'), 'F9 malformed JSON falls back to text')
  const empty = buildLedgerView('  ', '')
  ok(empty.mode === 'text' && empty.note.includes('empty'), 'F9 an empty ledger is named')

  const many = buildLedgerView(JSON.stringify(Array.from({ length: LEDGER_DISPLAY_MAX_ENTRIES + 3 }, (_, i) => ({ name: `e${i}`, status: 'ok' }))), '')
  ok(many.mode === 'generic' && many.entries.length === LEDGER_DISPLAY_MAX_ENTRIES, 'F10 the entry cap bites')
  ok(many.note.includes('Showing the first'), 'F10 the entry cap is named')
}

/* ---------------------------------------------------------- G. lightbox */

section('G. shared lightbox contract')
{
  eq('G1 the key contract', LIGHTBOX_KEYS, { close: 'Escape', prev: 'ArrowLeft', next: 'ArrowRight' })
  const files = ['a', 'b', 'c']
  eq('G2 forward', lightboxNav(files, 0, 1), 1)
  eq('G2 wrap forward', lightboxNav(files, 2, 1), 0)
  eq('G2 wrap back', lightboxNav(files, 0, -1), 2)
  eq('G2 malformed: empty list', lightboxNav([], 0, 1), 0)
  eq('G2 malformed: out of range', lightboxNav(['a'], 5, 1), 0)
  eq('G2 malformed: non-integer index', lightboxNav(files, 1.5, 1), 1)
  eq('G2 malformed: non-integer delta', lightboxNav(files, 0, 1.5), 0)
  eq('G2 malformed: missing delta', lightboxNav(files, 1, undefined), 1)
  eq('G2 malformed: non-list', lightboxNav(null, 0, 1), 0)
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
