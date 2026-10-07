#!/usr/bin/env node
/**
 * t261008-01 scenario 1 — the charter injection opens with a readable title
 * line, not the raw HTML comment (grey-box L3, offline seconds, zero docker /
 * Temporal / browser / network, never touches 3099).
 *
 * User-visible promise under test (host report 261007, ticket Measure 2):
 * the platform names a new project session after the session's first message.
 * Our sessions open with the charter injection, so its FIRST LINE is the name
 * a person sees in the platform workspace list. It must read as text a person
 * chose (a short title naming the project) — never an HTML comment marker.
 *
 * Legs:
 *   A  composition: composeCharterInjection yields line 1 = a human-readable
 *      title containing the project name (fallback to key when the name is
 *      empty; fixed label when both empty), the machine marker on a LATER
 *      line (within the first three non-empty lines — the fold contract),
 *      and the charter body intact after it; non-string charter degrades to
 *      empty body, never throws.
 *   B  comment strip: stripLeadingComment removes a leading HTML comment
 *      block (and its line end), is a no-op without one, and keeps an
 *      UNTERMINATED comment untouched (never swallows the file).
 *   C  real source: the shipped server/session_charter.md keeps its file-doc
 *      comment IN THE FILE (editor metadata) but composeSessionCharter's
 *      rendered output for the real file contains neither the workbench
 *      marker nor the session_charter.md comment at the head — the injected
 *      text starts with the readable title, via composeCharterInjection.
 *   D  fold coupling: classifyContextFold still folds the NEW shape (marker
 *      on line 2) and the LEGACY shape (marker on line 1), and does NOT fold
 *      a mid-text marker mention or a non-string (existing trade-off list).
 *      A broken fold after moving the marker = the charter stops collapsing
 *      — the regression this leg pins.
 *   E  wire shape (KI-046 regression, incident 260904): the injection call
 *      site still sends PromptContentPart[] — `[{ type: 'text', text: ... }]`
 *      — never a bare string (the platform rejects it silently-ish and the
 *      whole injection died once already).
 *   F  endpoint field: node.ts's session-charter 200 response carries the
 *      projectName field so the client composes the title without a second
 *      lookup (source-locked, same face as the KI-042 path-drift guards).
 *
 * Intent split: the session-row/band LABEL rendering (Measure 1) belongs to
 * sc_t26100801_session_label_handle_face; the charter deliverable/endpoint
 * reachability contracts belong to t260904-07-charter-source-contract /
 * -endpoint-live; this entry owns only the injection's first-line readability
 * and its two coupled consumers (fold predicate, wire shape).
 *
 * Pre-implement = FAIL naming the missing piece (TDD-phase red expected);
 * must be green at arbitrate/merge. node missing = ENV_FAIL exit 2.
 */
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

const HOST = join(REPO, 'server', 'plugins', 'workbench', 'src', 'host', 'session-charter.ts')
const FOLD = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'context-fold.ts')
const ENTRY = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'session-entry.tsx')
const NODE = join(REPO, 'server', 'plugins', 'workbench', 'node.ts')
const CHARTER_FILE = join(REPO, 'server', 'session_charter.md')

for (const f of [HOST, FOLD, ENTRY, NODE, CHARTER_FILE]) {
  if (!existsSync(f)) {
    record('source-faces-present', 'fail', `missing ${f}`)
    summarize()
  }
}
record('source-faces-present', 'pass')

const MARKER_RE = /workbench:kind:charter/

// ---- A + B: composed injection and comment strip (module behaviour) ----
let host = null
try {
  host = await import(`file://${HOST}`)
} catch (err) {
  record('host-module-importable', 'env_fail', `import failed: ${err?.message}`)
}
if (host) {
  const compose = host.composeCharterInjection
  const strip = host.stripLeadingComment
  if (typeof compose !== 'function') {
    record('compose-injection-readable-title', 'fail', 'composeCharterInjection missing from host module')
    record('strip-leading-comment-table', 'fail', 'stripLeadingComment missing from host module')
  } else {
    // A1 readable title names the project
    const out = compose('Sandbar', 'sandbar', 'BODY-LINE\nsecond')
    const lines = String(out).split('\n')
    const first = (lines[0] ?? '').trim()
    if (first === '' || first.includes('<!--')) {
      record('compose-injection-readable-title', 'fail', `line 1 is not readable text: ${JSON.stringify(first)}`)
    } else if (!first.includes('Sandbar')) {
      record('compose-injection-readable-title', 'fail', `line 1 does not name the project: ${JSON.stringify(first)}`)
    } else {
      record('compose-injection-readable-title', 'pass', JSON.stringify(first))
    }
    // A2 marker on a later line, within the first three non-empty lines
    const nonEmpty = lines.map(l => l.trim()).filter(l => l !== '')
    const markerIdx = nonEmpty.findIndex(l => MARKER_RE.test(l))
    if (markerIdx === -1) record('marker-within-fold-window', 'fail', 'marker absent from composed injection')
    else if (markerIdx > 2) record('marker-within-fold-window', 'fail', `marker is non-empty line #${markerIdx + 1}, fold window is 3`)
    else record('marker-within-fold-window', 'pass', `marker at non-empty line #${markerIdx + 1}`)
    // A3 body intact after the marker
    const tail = lines.slice(lines.findIndex(l => MARKER_RE.test(l)) + 1).join('\n')
    record(tail.includes('BODY-LINE') && tail.includes('second') ? 'charter-body-intact' : 'charter-body-intact',
      tail.includes('BODY-LINE') && tail.includes('second') ? 'pass' : 'fail')
    // A4 name fallback to key; both empty -> fixed label; non-string charter no-throw
    try {
      const k = compose('', 'k1', 'b')
      const n = compose('', '', 'b')
      const bad = compose('Sandbar', 'sandbar', undefined)
      const okFallback = k.split('\n')[0].includes('k1') && (k.split('\n')[0] ?? '').includes('k1') && !(k.split('\n')[0] ?? '').includes('<!--')
      const okEmpty = (n.split('\n')[0] ?? '').length > 0 && !(n.split('\n')[0] ?? '').includes('<!--')
      const okNonString = typeof bad === 'string'
      record('compose-malformed-tolerance',
        okFallback && okEmpty && okNonString ? 'pass' : 'fail',
        `fallback=${JSON.stringify(k)} empty=${JSON.stringify(n)} nonstring-ok=${okNonString}`)
    } catch (err) {
      record('compose-malformed-tolerance', 'fail', `threw: ${err?.message}`)
    }
    // B strip table
    if (typeof strip !== 'function') {
      record('strip-leading-comment-table', 'fail', 'stripLeadingComment missing')
    } else {
      const withC = strip('<!-- doc -->\nBODY')
      const without = strip('BODY')
      const unterminated = strip('<!-- doc\nBODY')
      const nonStr = strip(undefined)
      const b1 = withC === 'BODY'
      const b2 = without === 'BODY'
      const b3 = unterminated === '<!-- doc\nBODY'
      const b4 = nonStr === undefined
      record('strip-leading-comment-table',
        b1 && b2 && b3 && b4 ? 'pass' : 'fail',
        `with=${JSON.stringify(withC)} without=${JSON.stringify(without)} unterm=${JSON.stringify(unterminated)} nonstr-ok=${b4}`)
    }
  }
}

// ---- C: the real charter file vs its rendered output ----
const raw = readFileSync(CHARTER_FILE, 'utf8')
const fileKeepsDoc = raw.trimStart().startsWith('<!--')
record(fileKeepsDoc ? 'charter-file-keeps-doc-comment' : 'charter-file-keeps-doc-comment',
  fileKeepsDoc ? 'pass' : 'fail',
  fileKeepsDoc ? 'editor metadata stays in the file' : 'file-doc comment vanished from the source file')
try {
  const rendered = host?.composeSessionCharter
    ? host.composeSessionCharter(raw, 'sandbar', {
        projectKey: 'sandbar', projectName: 'Sandbar',
        primaryDir: '/tmp/primary', engineRoot: '/tmp/engine',
      })
    : null
  if (rendered === null) {
    record('rendered-output-no-comment-head', 'fail', 'composeSessionCharter not importable')
  } else {
    const viaInjection = typeof host.composeCharterInjection === 'function'
      ? host.composeCharterInjection('Sandbar', 'sandbar', rendered)
      : rendered
    const head = viaInjection.split('\n')[0] ?? ''
    const bodyHead = (rendered.trimStart().slice(0, 200))
    const noComment = !head.includes('<!--') && !bodyHead.includes('session_charter.md')
    record('rendered-output-no-comment-head', noComment ? 'pass' : 'fail',
      `injection line1=${JSON.stringify(head)} rendered-head=${JSON.stringify(bodyHead.slice(0, 60))}`)
  }
} catch (err) {
  record('rendered-output-no-comment-head', 'fail', `compose threw: ${err?.message}`)
}

// ---- D: fold coupling ----
let fold = null
try {
  fold = await import(`file://${FOLD}`)
} catch (err) {
  record('fold-module-importable', 'env_fail', `import failed: ${err?.message}`)
}
if (fold) {
  const f = fold.classifyContextFold
  if (typeof f !== 'function') {
    record('fold-predicate-table', 'fail', 'classifyContextFold missing')
  } else {
    const title = 'Project session — Sandbar (sandbar)'
    const marker = '<!-- workbench:kind:charter -->'
    const newShape = `${title}\n${marker}\n你是某项目会话`
    const legacy = `${marker}\n你是某项目会话`
    const midText = `开头 ${marker} 中段`
    const t1 = f(newShape) === true
    const t2 = f(legacy) === true
    const t3 = f(midText) === false
    const t4 = f(undefined) === false && f(42) === false
    record('fold-predicate-table', t1 && t2 && t3 && t4 ? 'pass' : 'fail',
      `newShape=${t1} legacy=${t2} midText-not-folded=${t3} nonstring-not-folded=${t4}`)
  }
}

// ---- E: wire shape (KI-046 regression) + F: endpoint projectName field ----
const entrySrc = readFileSync(ENTRY, 'utf8')
const nodeSrc = readFileSync(NODE, 'utf8')
const promptCall = entrySrc.match(/session\.prompt\(([\s\S]{0,200}?)\], 'queue'\)/)
const arrayShape = promptCall !== null && /\[\s*\{\s*type:\s*'text'/.test(promptCall[1])
const noRawConcat = !entrySrc.includes('`${CHARTER_MARKER}')
record('injection-wire-array-shape', arrayShape ? 'pass' : 'fail',
  arrayShape ? 'payload stays PromptContentPart[]' : 'prompt payload no longer array-of-parts (KI-046 face)')
record('no-raw-marker-concat-at-site', noRawConcat ? 'pass' : 'fail',
  noRawConcat ? 'injection site composes via the shared function' : 'raw `${CHARTER_MARKER}` concat still present')
const hasField = /sendJson\(res,\s*200,\s*\{[^}]*projectName/.test(nodeSrc)
record('endpoint-response-carries-projectname', hasField ? 'pass' : 'fail',
  hasField ? 'client can compose the title without a second lookup' : 'projectName missing from the 200 body')

summarize()
