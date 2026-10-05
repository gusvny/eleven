#!/usr/bin/env node
/**
 * t261005-09 scenario 1 — session handle contract (grey-box L2/L3, offline
 * seconds, zero docker / Temporal / browser / network, never touches 3099).
 *
 * User-visible promise under test (epic console-ui UI-1, dispatch item d):
 * the left-column session area shows each session's handle, the executor
 * session's handle is exactly `executor`, and handles are stable/unique per
 * project so a person can tell sessions apart.
 *
 * Legs:
 *   A  derivation: a session uuid yields the short handle defined by the
 *      plan (first 4 hex chars), deterministic across calls.
 *   B  collision ladder: ids sharing the first 4 chars extend to 6; ids
 *      sharing 6 fall back to the defined tail form (<first6>-<last4>) —
 *      unique whenever the uuid tail is unique, never a throw.
 *   C  malformed input: empty id, too-short id, non-hex id, duplicate/odd
 *      `taken` contents — the module answers with a defined value and never
 *      throws (external-input discipline).
 *   D  purity: the `taken` list is not mutated by a call.
 *   E  executor: the executor handle is the exported constant `executor`,
 *      defined in exactly one place (no parallel literal in the client src).
 *   F  single source: the sidebar client consumes this module (an import
 *      exists in src/client), so handles cannot drift between render paths.
 *
 * Intent split: per-render DOM truth of session rows belongs to
 * t261005-09-left-column-ui-journey; internal string helpers belong to the
 * developer L1 battery (tests/session-handle.mjs); this entry pins the
 * module's public contract and the single-source rule.
 *
 * Pre-implement = FAIL naming the missing module (TDD-phase red expected);
 * must be green at arbitrate/merge. node missing = ENV_FAIL exit 2.
 */
import assert from 'node:assert/strict'
import { readFileSync, existsSync, readdirSync } from 'node:fs'
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

const MOD = join(REPO, 'server', 'plugins', 'workbench', 'src', 'shared', 'session-handle.ts')

let m = null
try {
  m = await import(`file://${MOD}`)
  record('module-loads', 'pass', MOD)
} catch (err) {
  record('module-loads', 'fail', `missing ${MOD} — pre-implement, TDD-phase red expected: ${String(err).slice(0, 160)}`)
  summarize()
}

// ---- A derivation -------------------------------------------------------
try {
  const h1 = m.sessionHandle('3f9c2a7e-1234-4abc-9def-112233445566', [])
  const h2 = m.sessionHandle('3f9c2a7e-1234-4abc-9def-112233445566', [])
  assert.equal(h1, '3f9c', `first-4-hex expected, got ${JSON.stringify(h1)}`)
  assert.equal(h1, h2, 'derivation must be deterministic')
  record('A derivation-first4-deterministic', 'pass', h1)
} catch (err) {
  record('A derivation-first4-deterministic', 'fail', String(err).slice(0, 200))
}

// ---- B collision ladder --------------------------------------------------
try {
  const a = 'ab12ffff-0000-4000-8000-000000000001'
  const b = 'ab12eeee-0000-4000-8000-000000000002'
  // shares the first 6 hex with b's extended handle 'ab12ee' → 6-char form cannot disambiguate
  const c = 'ab12ee00-0000-4000-8000-000000000003'
  const d = 'ab12ee11-0000-4000-8000-000000000004' // second tail-fallback case: still unique
  const ha = m.sessionHandle(a, [])
  const hb = m.sessionHandle(b, [ha])
  assert.equal(ha, 'ab12')
  assert.equal(hb, 'ab12ee', `collision must extend to 6 hex, got ${hb}`)
  const hc = m.sessionHandle(c, [ha, hb])
  assert.match(hc, /^ab12ee-[0-9a-f]{4}$/, `6-char collision must use the defined tail form, got ${hc}`)
  assert.equal(hc.endsWith(c.slice(-4)), true, 'tail suffix must come from the id tail')
  const hd = m.sessionHandle(d, [ha, hb, hc])
  assert.match(hd, /^ab12ee-[0-9a-f]{4}$/)
  const all = [ha, hb, hc, hd]
  assert.equal(new Set(all).size, all.length, 'handles must stay unique across the ladder')
  record('B collision-ladder', 'pass', all.join(' '))
} catch (err) {
  record('B collision-ladder', 'fail', String(err).slice(0, 200))
}

// ---- C malformed input ----------------------------------------------------
try {
  const cases = [
    ['', []], ['ab', []], ['zzzz-0000', []], ['3F9C', []],
    ['3f9c', ['3f9c', '3f9c']],
  ]
  const seen = new Set()
  for (const [id, taken] of cases) {
    let out
    try { out = m.sessionHandle(id, [...taken]) } catch (err) {
      throw new Error(`threw on id=${JSON.stringify(id)}: ${err}`)
    }
    assert.equal(typeof out, 'string', `non-string result for ${JSON.stringify(id)}`)
    assert.ok(out.length >= 1, `empty result for ${JSON.stringify(id)}`)
    seen.add(out)
  }
  record('C malformed-no-throw-defined', 'pass', `${cases.length} hostile inputs, all answered`)
} catch (err) {
  record('C malformed-no-throw-defined', 'fail', String(err).slice(0, 200))
}

// ---- D purity -------------------------------------------------------------
try {
  const taken = ['ab12', 'ab12ee']
  const snapshot = JSON.stringify(taken)
  m.sessionHandle('ab12cd00-0000-4000-8000-000000000003', taken)
  assert.equal(JSON.stringify(taken), snapshot, 'taken list mutated')
  record('D taken-not-mutated', 'pass')
} catch (err) {
  record('D taken-not-mutated', 'fail', String(err).slice(0, 200))
}

// ---- E executor constant --------------------------------------------------
try {
  assert.equal(m.EXECUTOR_HANDLE, 'executor', `executor handle must be exactly 'executor', got ${JSON.stringify(m.EXECUTOR_HANDLE)}`)
  record('E executor-constant', 'pass', m.EXECUTOR_HANDLE)
} catch (err) {
  record('E executor-constant', 'fail', String(err).slice(0, 200))
}

// ---- F single source ------------------------------------------------------
try {
  const srcRoot = join(REPO, 'server', 'plugins', 'workbench', 'src')
  const clientDir = join(srcRoot, 'client')
  const clientFiles = existsSync(clientDir)
    ? readDirSafe(clientDir).filter(f => f.endsWith('.ts') || f.endsWith('.tsx'))
    : []
  const consumers = clientFiles.filter(f =>
    readFileSync(join(clientDir, f), 'utf8').includes('session-handle'))
  assert.ok(consumers.length >= 1, `no src/client consumer imports session-handle (single-source rule)`)
  // no parallel executor literal: the constant lives in the module, not inline elsewhere
  const offenders = []
  for (const dir of [['src', 'client'], ['src', 'shared']]) {
    for (const f of readDirSafe(join(srcRoot, ...dir)).filter(f => f.endsWith('.ts') || f.endsWith('.tsx'))) {
      const src = readFileSync(join(srcRoot, ...dir, f), 'utf8')
      if (/EXECUTOR_HANDLE\s*=\s*['"]executor['"]/.test(src)
        && join(...dir) + '/' + f !== 'shared/session-handle.ts') offenders.push(dir.join('/') + '/' + f)
    }
  }
  assert.deepEqual(offenders, [], `parallel executor-handle literals found: ${offenders.join(', ')}`)
  record('F single-source', 'pass', `consumers: ${consumers.join(', ')}`)
} catch (err) {
  record('F single-source', 'fail', String(err).slice(0, 200))
}

function readDirSafe(p) {
  try { return readdirSync(p) } catch { return [] }
}

summarize()
