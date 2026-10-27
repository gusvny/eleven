/**
 * t261028-16 (KI-390) — the SHIPPED page source must define every helper its cores call.
 *
 * panel-page.ts never imports the render modules at run time. It embeds each core's
 * SOURCE through String(fn) (the EMBEDDED list). The unit tests import the real
 * modules, so a helper that a core CALLS but the page never embeds stays green here
 * and dies in the browser. Host report 261028: "runsWindowNote is not defined" - the
 * whole Certification tab was dead.
 *
 * The name a String(fn) embed defines in page scope is the function's OWN declaration
 * name, not the panel page's import alias (value -> faceValue defines `value`). This
 * test reads the declared names from the embedded source, so an alias cannot hide a
 * missing definition.
 *
 * Guard 1 (shipped-source sandbox): rebuild the exact block the page ships
 * (EMBED_CONSTS + the String(fn) sources the EMBEDDED list names, in that order),
 * assert the served HTML carries that block verbatim, run it in new Function, and
 * render the certification face from a payload that carries runs_window.
 * Guard 2 (completeness, derived): import every module under src/host, take the
 * exported functions the page embeds, and require each exported host helper their
 * bodies call to be defined by the embed. No hand-written name list: the names come
 * from source, so the next helper is judged the same way.
 *
 * Pure node: no DOM, no network, no console on 3099.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'

let n = 0
const ok = (cond, name) => { assert(cond, name); n += 1 }

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '../src/host')
const PAGE_SRC = readFileSync(join(SRC, 'panel-page.ts'), 'utf8')
const BASE = pathToFileURL(join(SRC, 'panel-page.ts'))
const DECL_RE = /^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(/

/** Blank out comments. The prose in these files names collaborators, so a scan of
 *  raw source would report names that are not called. Strings stay: a helper call
 *  inside a template literal is still a call. */
function stripComments(src) {
  let out = ''
  let i = 0
  while (i < src.length) {
    const c = src[i], next = src[i + 1]
    if (c === '/' && next === '/') {
      const end = src.indexOf('\n', i)
      out += ' '
      i = end < 0 ? src.length : end
      continue
    }
    if (c === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2)
      out += ' '
      i = end < 0 ? src.length : end + 2
      continue
    }
    if (c === "'" || c === '"') {
      let j = i + 1
      while (j < src.length) {
        if (src[j] === '\\') { j += 2; continue }
        if (src[j] === c) { j += 1; break }
        j += 1
      }
      out += src.slice(i, j)
      i = j
      continue
    }
    out += c
    i += 1
  }
  return out
}

/** The JSON value that starts at `at` (a { or [ in the served page). String aware,
 *  so a brace inside a copy sentence does not end the value. */
function jsonValueAt(text, at) {
  let i = at
  let depth = 0
  while (i < text.length) {
    const c = text[i]
    if (c === '"') {
      i += 1
      while (i < text.length && text[i] !== '"') { if (text[i] === '\\') i += 1; i += 1 }
      i += 1
      continue
    }
    if (c === '{' || c === '[') { depth += 1; i += 1; continue }
    if (c === '}' || c === ']') {
      depth -= 1
      i += 1
      if (depth === 0) return JSON.parse(text.slice(at, i))
      continue
    }
    i += 1
  }
  throw new Error('unterminated JSON value in the served page at ' + at)
}

/** The page-scope table the served script defines as `var <name> = ` + JSON. */
function pageTable(name) {
  const at = PANEL_PAGE_HTML.indexOf('var ' + name + ' = ')
  assert(at > 0, 'the served page defines ' + name)
  return jsonValueAt(PANEL_PAGE_HTML, PANEL_PAGE_HTML.indexOf('{', at))
}

// ---- 1. the embed declaration, read from the page source (never a hand list) ----
const constsAt = PAGE_SRC.indexOf('const EMBED_CONSTS =')
const listAt = PAGE_SRC.indexOf('const EMBEDDED =', constsAt)
const openAt = PAGE_SRC.indexOf('[', listAt)
const closeAt = PAGE_SRC.indexOf("].join('\\n')", openAt)
ok(constsAt > 0 && listAt > constsAt && openAt > listAt && closeAt > openAt,
  'panel-page.ts declares EMBED_CONSTS, then the EMBEDDED list')
const EMBED_CONSTS = new Function('return (' + PAGE_SRC
  .slice(constsAt + 'const EMBED_CONSTS ='.length, listAt).trim().replace(/;\s*$/, '') + ')')()
const embedAliases = [...PAGE_SRC.slice(openAt, closeAt + 1)
  .matchAll(/String\(\s*([A-Za-z_$][\w$]*)\s*\)/g)].map((m) => m[1])
ok(embedAliases.length > 40, 'the EMBEDDED list names ' + embedAliases.length + ' embeds (read from source)')

// ---- 2. resolve every embed to the function it ships, and to the name it DEFINES ----
const importedNames = new Map()
for (const m of PAGE_SRC.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*'([^']+)'/g)) {
  for (const spec of stripComments(m[1]).split(',')) {
    const text = spec.trim()
    if (!text) continue
    const alias = text.split(/\s+as\s+/)
    importedNames.set((alias[1] || alias[0]).trim(), { from: m[2], name: alias[0].trim() })
  }
}
const pageModule = await import(BASE.href)
const moduleCache = new Map()
async function moduleOf(spec) {
  if (!moduleCache.has(spec)) moduleCache.set(spec, await import(new URL(spec, BASE).href))
  return moduleCache.get(spec)
}
const embeds = []
const unresolved = []
const notDeclarations = []
for (const alias of embedAliases) {
  let fn = null
  if (importedNames.has(alias)) {
    const { from, name } = importedNames.get(alias)
    fn = (await moduleOf(from))[name]
  } else if (typeof pageModule[alias] === 'function') {
    fn = pageModule[alias]
  }
  if (typeof fn !== 'function') { unresolved.push(alias); continue }
  const source = String(fn)
  const declared = DECL_RE.exec(source.trim())
  if (!declared) notDeclarations.push(alias)
  embeds.push({ alias, source, declared: declared ? declared[1] : '' })
}
ok(unresolved.length === 0, 'every EMBEDDED name resolves to a module function'
  + (unresolved.length ? ' (unresolved: ' + unresolved.join(', ') + ')' : ''))
ok(notDeclarations.length === 0, 'every embed is a function declaration, so String(fn) defines a'
  + ' page-scope name' + (notDeclarations.length ? ' (not a declaration: ' + notDeclarations.join(', ') + ')' : ''))

// ---- 3. the assembled block IS the block the served page carries ----
const assembled = EMBED_CONSTS + embeds.map((e) => e.source).join('\n')
ok(PANEL_PAGE_HTML.includes(assembled), 'the assembled source is the served page block, byte for byte')
// The page-scope definitions the embed provides (the declaration names, not the aliases).
const defined = new Set(embeds.map((e) => e.declared).filter(Boolean))
ok(defined.size >= embeds.length - 1, 'the embed defines ' + defined.size + ' distinct names at page scope')

// ---- 4. every exported function under src/host, keyed for the two derivations ----
const hostFunctions = new Map()
for (const file of readdirSync(SRC).filter((f) => f.endsWith('.ts'))) {
  const module = await moduleOf('./' + file)
  for (const key of Object.keys(module)) {
    if (typeof module[key] === 'function' && !hostFunctions.has(key)) {
      hostFunctions.set(key, { file, source: String(module[key]) })
    }
  }
}
ok(hostFunctions.size > 20, 'the src/host scan found ' + hostFunctions.size + ' exported functions')

/** The exported host helpers a function body calls (locals and member calls skipped). */
function calleesOf(name) {
  const record = hostFunctions.get(name)
  if (!record) return []
  const body = stripComments(record.source)
  const locals = new Set([...body.matchAll(/\b(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)/g)]
    .map((m) => m[1]))
  const found = []
  for (const m of body.matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
    const callee = m[1]
    if (callee === name || locals.has(callee)) continue
    if (!hostFunctions.has(callee) || found.includes(callee)) continue
    found.push(callee)
  }
  return found
}

/** The GUARD: for a given set of page-scope names, which called helpers are missing? */
function offendersOf(pageScope) {
  const offenders = new Map()
  for (const name of pageScope) {
    for (const callee of calleesOf(name)) {
      if (pageScope.has(callee)) continue
      if (!offenders.has(callee)) offenders.set(callee, [])
      offenders.get(callee).push(name)
    }
  }
  return offenders
}

// ---- 5. the certification face renders from the SHIPPED source ----
const certRuntime = pageTable('CERT_RUNTIME')
const metricsRuntime = pageTable('METRICS_RUNTIME')
ok(typeof certRuntime.COPIES === 'object' && typeof certRuntime.ROUND === 'object',
  'the page ships the certification copy tables (CERT_RUNTIME.COPIES / .ROUND)')
// The page hands the embedded cert bodies these three identifiers (its own JSON tables).
const pageGlobals = 'var CERT_COPIES = ' + JSON.stringify(certRuntime.COPIES) + ';\n'
  + 'var ROUND_COPIES = ' + JSON.stringify(certRuntime.ROUND) + ';\n'
  + 'var FACE_DASH = ' + JSON.stringify(metricsRuntime.FACE_DASH) + ';\n'

// The page scope holds only what the embed defines. A helper the core calls but the
// embed leaves out is a ReferenceError at call time - the host's dead tab.
const coreScope = new Function(assembled + '\n' + pageGlobals
  + '\nreturn { buildCertificationCore };')()
// The whole shipped block, so the family below runs on page scope too.
const shipped = new Function(assembled + '\n' + pageGlobals
  + '\nreturn { ' + [...defined].join(', ') + ' };')()

// A realistic /api/certification answer: a green line face, one rounds section, and
// the runs window the adapter states (t261027-16).
const facePayload = {
  ok: true,
  project: 'sandbar',
  line: 'develop-buffer',
  lines: [{ line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host' }],
  face: {
    state: 'idle',
    promotable: 2,
    deliveredTotal: 41,
    roundState: 'idle',
    boundary: { at: '2026-10-27T09:41:00Z' },
    certified: [{
      ticket: 't261027-16', title: 'the runs window word', epic: 'epic-cert',
      certifiedBy: 'run-118', landedAt: '2026-10-27T08:10:00Z', delivered: false,
    }],
    waiting: [{
      ticket: 't261028-16', title: 'the dead certification tab',
      epic: 'epic-cert', landedAt: '2026-10-27T20:00:00Z',
    }],
  },
  raw: { runs: [{ id: 'run-118', source: 'scheduled' }, { id: 'run-119', source: 'person' }] },
  round_faces: {
    dir: '/tmp/rounds',
    rounds: [{
      run_id: 'run-118',
      face: {
        run_id: 'run-118', state: 'done', started_at: '2026-10-27T08:00:00Z',
        counts: { ran: 12, pass: 12, fail: 0, env_fail: 0 },
        outcome: { verdict: 'green', reason: '' },
        revision: { sandbar: '7967b2d7' },
      },
    }],
  },
  runs_window: { shown: 20, total: 3600, older: 3580, cap: 20 },
  notes: [],
}

let rendered = null
try {
  rendered = coreScope.buildCertificationCore(facePayload)
} catch (e) {
  throw new Error('FAIL: the shipped page source cannot render the certification face: '
    + e.name + ': ' + e.message + ' (the served page turns this into a dead tab)')
}
ok(typeof rendered === 'string' && rendered.includes('id="certRunsWindow"'),
  'the shipped source renders the runs-window note (no ReferenceError)')
ok(rendered.includes('showing 20 of 3600 run headers') && rendered.includes('cap 20'),
  'the note names the window the receipt states')
ok(rendered.includes('id="certStateCard"') && rendered.includes('id="certLine"')
  && rendered.includes('id="certRoundRows"'), 'the rest of the tab renders unchanged')
ok(!shipped.buildCertificationCore({ ...facePayload, runs_window: undefined }).includes('certRunsWindow'),
  'an older receipt without a window renders no note')
ok(!shipped.buildCertificationCore({ ...facePayload, runs_window: { older: 'many' } }).includes('certRunsWindow'),
  'a malformed window renders no note and does not throw')

// The whole cert group runs on the shipped source, not only the face core.
const family = [
  ['buildRoundDialogCore', () => shipped.buildRoundDialogCore({ ok: false, reason: 'refused' })],
  ['buildPromoteDialogCore', () => shipped.buildPromoteDialogCore({ owner: 'host', preview: { ok: false, reason: 'refused' } })],
  ['certQueueNoteText', () => shipped.certQueueNoteText({ ok: false, error: 'refused' })],
  ['buildRoundsRows', () => shipped.buildRoundsRows({ dir: '/tmp/rounds', rounds: [] }, [])],
  ['roundsSectionNote', () => shipped.roundsSectionNote({ error: 'ledger malformed' })],
  ['countsCell', () => shipped.countsCell({ ran: 1 }, '')],
  ['roundPill', () => shipped.roundPill({ state: 'done' })],
  ['roundReason', () => shipped.roundReason({ outcome: { reason: 'red round' } })],
  ['roundTrigger', () => shipped.roundTrigger([], 'run-118')],
  ['roundTriggerWord', () => shipped.roundTriggerWord('scheduled')],
  ['roundMeasured', () => shipped.roundMeasured({ sandbar: '7967b2d7' })],
  ['runsWindowNote', () => shipped.runsWindowNote({ shown: 20, total: 3600, older: 3580, cap: 20 })],
]
for (const [name, call] of family) {
  ok(call() !== undefined, 'the shipped source runs ' + name)
}

// Teeth: leave the helpers the cert core calls out of the embed and the SAME call
// throws. That ReferenceError is the host-reported dead tab, here a red test.
const certCallees = calleesOf('buildCertificationCore')
ok(certCallees.length > 0, 'the cert core calls these host helpers: ' + certCallees.join(', '))
const strippedBlock = EMBED_CONSTS
  + embeds.filter((e) => !certCallees.includes(e.declared)).map((e) => e.source).join('\n')
const stripped = new Function(strippedBlock + '\n' + pageGlobals
  + '\nreturn { buildCertificationCore };')()
let strippedError = null
try {
  stripped.buildCertificationCore(facePayload)
} catch (e) {
  strippedError = e
}
ok(strippedError instanceof ReferenceError,
  'teeth: a called helper left out of the embed throws a ReferenceError on the same call')

// ---- 6. completeness: the derivation finds ZERO offenders ----
const offenders = offendersOf(defined)
ok(offenders.size === 0, 'every exported host helper an embedded body calls is defined by the embed'
  + ' (offenders: ' + ([...offenders.keys()].join(', ') || 'none') + ')')
// Teeth: drop the helpers the cert core calls from the page scope and the derivation
// reports them. The check therefore cannot pass by finding nothing.
const dropped = new Set([...defined].filter((name) => !certCallees.includes(name)))
const foundWhenDropped = offendersOf(dropped)
ok(foundWhenDropped.size > 0 && certCallees.every((name) => foundWhenDropped.has(name)),
  'teeth: the derivation reports a dropped helper (' + [...foundWhenDropped.keys()].join(', ') + ')')

done(n)
