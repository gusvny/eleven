#!/usr/bin/env node
/**
 * t261008-01 scenario 2 — a charter-titled session shows its HANDLE, not the
 * raw injected text, in the session rows and the session band; the raw title
 * stays reachable (ticket Measure 1, grey-box L3, offline seconds, zero
 * docker / Temporal / browser / network, never touches 3099).
 *
 * User-visible promise under test (host report 261007): sessions whose only
 * content is the charter injection currently render the raw comment block as
 * their visible name in the session band. After the fix, such a session is
 * named by its handle (the executor session by the fixed handle `executor`,
 * any other by the short code the shared session-handle module produces),
 * while the full raw title stays reachable (tooltip) — nothing is hidden,
 * only the visible label is readable.
 *
 * Legs:
 *   A  predicate truth table: isCharterRawTitle recognises the legacy
 *      charter-comment titles (marker-shaped first line, session_charter
 *      comment head) and rejects readable titles, plain titles, empty and
 *      non-string input — never throws.
 *   B  label face: the shared row-label helper returns the HANDLE for a
 *      charter-raw title (executor handle for the executor session, short
 *      code otherwise) and passes every other title through UNCHANGED.
 *   C  band wiring: the sidebar band items consume the guarded label (not
 *      the raw labelOf passthrough) and the band item carries the raw title
 *      in a tooltip attribute — visible label readable, raw text reachable.
 *   D  single source: the guard lives in one shared module and both faces
 *      (row + band) resolve handles through the shared session-handle
 *      module — no parallel literal in client src.
 *
 * Intent split: the injection's first-line readability and its coupled
 * consumers (fold predicate, wire shape, endpoint field) belong to
 * sc_t26100801_charter_injection_readable; the handle module's derivation
 * and collision contract belongs to t261005-09-session-handle-contract; the
 * band's channel-switch/entrance faces belong to t261005-06; this entry owns
 * only the charter-raw-title label replacement and tooltip reachability.
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

const SHARED = join(REPO, 'server', 'plugins', 'workbench', 'src', 'shared')
const CANDIDATES = [join(SHARED, 'sessions.ts'), join(SHARED, 'session-handles.ts'),
  join(SHARED, 'charter-title.ts'), join(SHARED, 'session-handle.ts')]
const SIDEBAR = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'sidebar.tsx')
const BAND = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'chat-project-band.ts')
for (const f of [SIDEBAR, BAND]) {
  if (!existsSync(f)) {
    record('client-faces-present', 'fail', `missing ${f}`)
    summarize()
  }
}
record('client-faces-present', 'pass')

// Locate the guard and the label helper wherever the implementation homed
// them (declared in the ticket plan as one of the shared homes; the guard
// itself is the contract, the file is not).
const guardHomes = []
const labelHomes = []
const guardName = 'isCharterRawTitle'
const labelName = 'rowLabelOf'
for (const f of CANDIDATES) {
  if (!existsSync(f)) continue
  const src = readFileSync(f, 'utf8')
  if (src.includes(`export function ${guardName}`) || src.includes(`export const ${guardName}`)) guardHomes.push(f)
  if (src.includes(`export function ${labelName}`) || src.includes(`export const ${labelName}`)) labelHomes.push(f)
}
const home = guardHomes[0] ?? labelHomes[0] ?? null

// ---- A + B: module behaviour ----
if (!home) {
  record('guard-module-present', 'fail', `neither ${guardName} nor ${labelName} found under src/shared`)
} else {
  record('guard-module-present', 'pass', home)
  let guardMod = null
  let labelMod = null
  try {
    guardMod = home === guardHomes[0] ? await import(`file://${home}`) : (guardHomes[0] ? await import(`file://${guardHomes[0]}`) : null)
  } catch (err) {
    record('guard-module-importable', 'env_fail', `guard import failed: ${err?.message}`)
  }
  try {
    labelMod = home === labelHomes[0] ? guardMod : (labelHomes[0] ? await import(`file://${labelHomes[0]}`) : null)
  } catch (err) {
    record('guard-module-importable', 'env_fail', `label import failed: ${err?.message}`)
  }
  const mod = { guard: guardMod, label: labelMod }
  if (mod.guard || mod.label) {
    const guard = mod.guard?.[guardName]
    if (typeof guard === 'function') {
      const marker = '<!-- workbench:kind:charter -->'
      const legacy1 = `${marker}\n你是某项目会话`
      const legacy2 = '<!-- session_charter.md —— 说明 -->\n正文'
      const readable = 'Project session — Sandbar (sandbar)'
      const plain = '帮我看一下在跑工单'
      const t = [
        guard(legacy1) === true,
        guard(legacy2) === true,
        guard(readable) === false,
        guard(plain) === false,
        guard('') === false,
        guard(undefined) === false,
        guard(42) === false,
      ]
      record('charter-title-predicate-table', t.every(Boolean) ? 'pass' : 'fail',
        `legacy1=${t[0]} legacy2=${t[1]} readable=${t[2]} plain=${t[3]} empty=${t[4]} nonstr=${t[5]}/${t[6]}`)
    } else {
      record('charter-title-predicate-table', 'fail', `${guardName} missing (predicate may be folded into the label helper — then leg B carries the truth table)`)
    }
    const label = mod.label?.[labelName]
    if (typeof label !== 'function') {
      record('row-label-handle-fallback', 'fail', `${labelName} missing from ${home}`)
    } else {
      const marker = '<!-- workbench:kind:charter -->'
      const row = { displayTitle: `${marker}\n你是某项目会话` }
      const execRow = { displayTitle: `${marker}\nx` }
      const plainRow = { displayTitle: '帮我看一下在跑工单' }
      try {
        const id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        const got = label(row, id, 'a1b2')
        const gotExec = label(execRow, id, 'executor')
        const gotPlain = label(plainRow, id, 'a1b2')
        const handleUsed = got === 'a1b2'
        const notRaw = gotPlain === '帮我看一下在跑工单'
        const execOk = gotExec === 'executor'
        const missingHandle = label(row, id) === id
        record('row-label-handle-fallback',
          handleUsed && notRaw && execOk && missingHandle ? 'pass' : 'fail',
          `charterTitle→${JSON.stringify(got)} executor→${JSON.stringify(gotExec)} plainPassthrough=${notRaw} missingHandleFallsBackToId=${missingHandle}`)
      } catch (err) {
        record('row-label-handle-fallback', 'fail', `label helper threw: ${err?.message}`)
      }
    }
  }
}

// ---- C + D: wiring (source-locked, KI-042 family: drifted wiring = silent regression) ----
const sidebarSrc = readFileSync(SIDEBAR, 'utf8')
const bandSrc = readFileSync(BAND, 'utf8')
// C1: the band no longer feeds the raw labelOf output as the visible title.
const bandUsesGuard = /rowLabelOf|isCharterRawTitle|charterTitle|CharterRawTitle/.test(sidebarSrc)
record('band-uses-guarded-label', bandUsesGuard ? 'pass' : 'fail',
  bandUsesGuard ? 'sidebar band labels go through the charter-raw guard' : 'sidebar still feeds raw labelOf into band item title')
// C2: the raw title stays reachable — band item carries a tooltip/attr face.
const tooltipFace = /rawTitle|title\s*[:=]\s*(?:item\.)?rawTitle|setAttribute\(['"]title/.test(bandSrc) || /rawTitle/.test(sidebarSrc)
record('raw-title-tooltip-reachable', tooltipFace ? 'pass' : 'fail',
  tooltipFace ? 'band item carries the raw title as a tooltip face' : 'no raw-title tooltip face found on the band item')
// D: handle resolution stays in the shared module (no local short-code copy).
const sharedImport = /session-handle|sessionHandle|displayHandle|EXECUTOR_HANDLE/.test(sidebarSrc)
record('handle-single-source-in-band', sharedImport ? 'pass' : 'fail',
  sharedImport ? 'band resolves handles via the shared session-handle module' : 'band invents handle text locally')

summarize()
