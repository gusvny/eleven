#!/usr/bin/env node
/**
 * tests/t261030-36-artifact-view-ui.mjs — the six views inside the frame, contract layer
 * (epic artifact-face, slice 3, ticket t261030-36). Developer L2 battery.
 *
 * The L1 battery proves the model. This file proves the contract the browser cannot carry
 * cheaper: the view dispatch, the frame's ownership of the row (and of the fields the view
 * may not touch), the two row fields this slice added, the CSS token discipline, and the
 * src/lib same-source lock.
 *
 *   A THE FRAME EXTENSION — `ArtifactViewRow` carries `source` and `shape`, and the frame
 *     projects both verbatim (review B8).
 *   B THE ONE GATE — the frame's call site uses `shouldRenderBody` (the plan rule), not a
 *     second predicate; a row that the frame degrades or cannot serve never reaches a body.
 *   C FRAME OWNERSHIP — the row markup keeps `data-card`, `data-state`, the source label,
 *     the byte refusal, the refusals block and `Open original`; the verdict markup stays.
 *   D NO ROW AUTHORITY — the view reads no frame-owned display key (`FRAME_OWNED_KEYS`),
 *     and neither view module imports the frame's row derivation.
 *   E ONE ROW IN — the component's props carry one `row`, never a list.
 *   F CSS DISCIPLINE — every `var()` in the view CSS carries a hex fallback, and the CSS
 *     declares no new token.
 *   G SAME SOURCE — the built bundle carries the view markers, the six titles and the frame
 *     anchors (a stale bundle is a red).
 *
 * No browser, no console port, no integration entry.
 * Run: node server/plugins/workbench/tests/t261030-36-artifact-view-ui.mjs (cwd = repo root)
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  ARTIFACT_KINDS, FRAME_OWNED_KEYS, buildArtifactFaceView, deriveArtifactRows,
} from '../src/client/artifact-face-model.ts'
import {
  VIEW_TITLE, planArtifactBody, shouldRenderBody,
} from '../src/client/artifact-view-model.ts'
import { ARTIFACT_VIEW_CSS } from '../src/client/artifact-view-css.ts'

const here = dirname(fileURLToPath(import.meta.url))
const workbench = join(here, '..')
const clientDir = join(workbench, 'src', 'client')
const libDir = join(workbench, 'lib')

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) { pass += 1; console.log(`  ok ${label}`) }
  else { fail += 1; console.error(`  FAIL ${label}`) }
}
function eq(label, actual, expected) {
  ok(JSON.stringify(actual) === JSON.stringify(expected),
    `${label} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`)
}
function section(title) { console.log(`\n== ${title}`) }
function readClient(name) { return readFileSync(join(clientDir, name), 'utf8') }
/** Strip comments so a prose mention never counts as code (the repo's source-scan discipline). */
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/[^\n]*/g, '')
}

const MODEL = readClient('artifact-view-model.ts')
const VIEW = readClient('artifact-view.tsx')
const INDEX = readClient('index.tsx')
const MODEL_CODE = stripComments(MODEL)
const VIEW_CODE = stripComments(VIEW)

const OK_STAT = { state: 'ok', sizeBytes: 12, mtimeMs: Date.UTC(2026, 9, 30, 12, 0) }

/** The row the console really gets (descriptor -> real derivation -> real frame view). */
function rowOf(descriptor = {}, stat = OK_STAT) {
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

/* ------------------------------------------------ A. the frame extension */

section('A. the two-field frame extension (review B8)')
{
  const descriptor = { id: 'units', title: 'Units', source: 'out/units.json', kind: 'structure', shape: 'units[]' }
  const detail = { id: 't1', results: { plan: { gen: 1, artifact_descriptors: [descriptor] } } }
  const derived = deriveArtifactRows(detail, ['plan'])
  eq('A1 the derivation keeps the descriptor fields', [derived.rows[0].source, derived.rows[0].shape], ['out/units.json', 'units[]'])
  const key = derived.rows[0].rowKey
  const frame = buildArtifactFaceView(derived, { [key]: { state: 'ok', sizeBytes: 10, mtimeMs: 1 } }, detail)
  eq('A1 the view row carries the raw source', frame.rows[0].source, 'out/units.json')
  eq('A1 the view row carries the raw kind', frame.rows[0].kind, 'structure')
  eq('A1 the view row carries the shape verbatim', frame.rows[0].shape, 'units[]')
  eq('A1 the display label is unchanged', frame.rows[0].sourceLabel, 'out/units.json')
  eq('A1 the row count is unchanged', frame.rows.length, derived.rows.length)
}

/* ------------------------------------------------------- B. the one gate */

section('B. one render rule at the call site and in the component')
{
  eq('B1 shouldRenderBody is defined from the plan',
    MODEL.includes('return planArtifactBody(row, href).body'), true)
  ok('B1 the call site uses shouldRenderBody', INDEX.includes('shouldRenderBody(r, artifactBytesHref(ticketId, r))'))
  ok('B1 the call site renders ArtifactView with one row',
    INDEX.includes('<ArtifactView row={r} ticketId={ticketId} bytesHref={artifactBytesHref(ticketId, r)} />'))
  ok('B1 the call site does not gate on card alone', !INDEX.includes('{r.card === \'row\' &&'))

  const degrade = rowOf({}, { state: 'missing', reason: 'no file' })
  eq('B2 a degrade row is false', shouldRenderBody(degrade, HREF), false)
  const notServable = rowOf({ id: 'a/b' })
  eq('B2 a not-servable row is false', shouldRenderBody(notServable, null), false)
  const text = rowOf()
  eq('B2 a text row is true', shouldRenderBody(text, HREF), true)
  eq('B2 the plan names the text read', planArtifactBody(text, HREF).read, 'text')
}

/* --------------------------------------------------- C. frame ownership */

section('C. the frame keeps its row and its verdict')
{
  for (const anchor of [
    'data-card={r.card}', 'data-state={r.state}', 'data-testid={`artifact-row-${r.key}`}',
    '{r.sourceLabel}', 'r.bytesRefusal', '{r.refusals.map(', 'Open original',
    'frame.verdict.text', 'data-green={verdictTag}',
  ]) {
    ok(`C1 the frame keeps ${anchor}`, INDEX.includes(anchor))
  }
  ok('C1 the view body sits inside the row card (after the actions block)',
    INDEX.indexOf('<ArtifactView row={r}') > INDEX.indexOf('className="wb-af-actions"'))
  ok('C1 the row card still closes after the view', INDEX.indexOf('<ArtifactView row={r}') < INDEX.indexOf('data-testid={`artifact-row-${r.key}`}') + 4000)
}

/* ------------------------------------------------------ D. no authority */

section('D. the view reads no frame-owned display key')
{
  eq('D1 the frame-owned key list is the frame model\'s', FRAME_OWNED_KEYS,
    ['hidden', 'visible', 'order', 'view', 'render'])
  for (const key of FRAME_OWNED_KEYS) {
    const direct = new RegExp(`row\\.${key}\\b`)
    const indexed = new RegExp(`row\\[['"]${key}['"]\\]`)
    ok(`D1 the model does not read row.${key}`, !direct.test(MODEL_CODE) && !indexed.test(MODEL_CODE))
    ok(`D1 the component does not read row.${key}`, !direct.test(VIEW_CODE) && !indexed.test(VIEW_CODE))
  }
  ok('D2 the model reads no frame derivation',
    !MODEL_CODE.includes('deriveArtifactRows') && !MODEL_CODE.includes('buildArtifactFaceView'))
  ok('D2 the component reads no frame derivation',
    !VIEW_CODE.includes('deriveArtifactRows') && !VIEW_CODE.includes('buildArtifactFaceView'))
  ok('D2 the component never maps a row list', !VIEW_CODE.includes('rows.map('))
}

/* ------------------------------------------------------------ E. one row */

section('E. one row in, one body out')
{
  ok('E1 the component prop is a single row', VIEW.includes('row: ArtifactViewRow'))
  ok('E1 the component has no row-list prop', !VIEW.includes('rows: ArtifactViewRow[]'))
  ok('E1 the body renders inside the row face', VIEW.includes('data-testid={`artifact-view-${kind}`}'))
  for (const kind of ARTIFACT_KINDS) {
    ok(`E1 the titles cover ${kind}`, typeof VIEW_TITLE[kind] === 'string' && VIEW_TITLE[kind] !== '')
  }
}

/* ---------------------------------------------------------------- F. CSS */

section('F. the view CSS keeps the token discipline')
{
  const varRe = /var\(--[a-z0-9-]+,/g
  const opens = (ARTIFACT_VIEW_CSS.match(/var\(/g) ?? []).length
  const withFallback = (ARTIFACT_VIEW_CSS.match(varRe) ?? []).length
  eq('F1 every var() carries a fallback argument', withFallback, opens)
  ok('F1 the CSS declares no new token', !/--[a-z0-9-]+\s*:/.test(ARTIFACT_VIEW_CSS.replace(/^[^{]*\{/gm, '')))
  ok('F1 the status colors are the theme tokens',
    ARTIFACT_VIEW_CSS.includes('--dsw-derive-success') && ARTIFACT_VIEW_CSS.includes('--dsw-derive-danger'))
  ok('F1 the CSS has no bare placeholder dash literal', !/'—'|"—"/.test(ARTIFACT_VIEW_CSS))
}

/* ------------------------------------------------------- G. same source */

section('G. the built bundle carries the view and the frame')
{
  for (const [name, artifact] of [
    ['lib/client.js', readFileSync(join(libDir, 'client.js'), 'utf8')],
    ['lib/client.cjs', readFileSync(join(libDir, 'client.cjs'), 'utf8')],
  ]) {
    for (const marker of [
      'artifact-view-', 'data-view-kind', 'wb-av', 'data-view-body',
      'ledger-receipt', 'ledger-generic', 'artifact-row-', 'Open original',
    ]) {
      ok(`G1 ${name} carries ${marker}`, artifact.includes(marker))
    }
    for (const kind of ARTIFACT_KINDS) ok(`G1 ${name} carries the ${kind} title`, artifact.includes(VIEW_TITLE[kind]))
  }
  ok('G2 the evidence lightbox is shared', INDEX.includes('lightbox.tsx') && VIEW.includes('lightbox.tsx'))
  ok('G2 the frame test is present next to this battery',
    readFileSync(join(here, 't261030-35-artifact-face.mjs'), 'utf8').includes('buildArtifactFaceView'))
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
