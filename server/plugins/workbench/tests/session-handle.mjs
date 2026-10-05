/**
 * smoke/tests/session-handle.mjs — unit guard for shared/session-handle.ts
 * (console-ui UI-1, t261005-09). Run: node tests/session-handle.mjs
 * (node >= 22 native type-stripping imports the .ts module directly).
 *
 * Covers:
 *   A. Base rule: first 4 hex chars of the uuid body (`session-` prefix stripped).
 *   B. Intra-project collision: extends to 6 chars.
 *   C. Collision beyond 6: exact `<first-6-hex>-<last-4-of-id>` shape.
 *   D. Malformed inputs: empty id, non-hex id, id shorter than 4/6 chars —
 *      never throws, deterministic output.
 *   E. `taken` is not mutated (purity).
 *   F. EXECUTOR_HANDLE is exactly `executor`.
 */

import { sessionHandle, EXECUTOR_HANDLE, HANDLE_PLACEHOLDER } from '../src/shared/session-handle.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('A base rule: first 4 hex of the uuid body')
{
  ok(sessionHandle('session-09ca0247-abcd-4e5f-8a1b-2c3d4e5f6a7b') === '09ca', 'prefix stripped, first 4 hex')
  ok(sessionHandle('09ca0247-abcd') === '09ca', 'works without the session- prefix too')
  ok(sessionHandle('session-F00DABCD-1234') === 'f00d', 'hex lowercased')
}

section('B collision extends to 6')
{
  const taken = ['09ca']
  ok(sessionHandle('session-09caffff-1', taken) === '09caff', 'same 4-prefix -> 6 chars')
}

section('C collision beyond 6: <first6>-<last4-of-id>')
{
  // Two uuids sharing the same first 6 hex chars.
  const taken = ['09ca', '09caff']
  const h = sessionHandle('session-09caff12-xxxx-4444', taken)
  ok(h === '09caff-4444', `beyond-6 shape is first6-last4 (got ${h})`)
  // Same 6-prefix AND same tail → disambiguated again deterministically.
  const taken2 = ['09ca', '09caff', '09caff-4444']
  const h2 = sessionHandle('session-09caff12-xxxx-4444', taken2)
  ok(h2 !== h && h2.startsWith('09caff-'), `exhausted fallback still deterministic and prefixed (got ${h2})`)
  ok(sessionHandle('session-09caff12-xxxx-4444', taken2) === h2, 'repeat call gives the same handle')
}

section('D malformed inputs never throw')
{
  ok(sessionHandle('') === HANDLE_PLACEHOLDER, 'empty id -> placeholder')
  ok(sessionHandle(undefined) === HANDLE_PLACEHOLDER, 'undefined id -> placeholder')
  ok(sessionHandle('zzzz') === HANDLE_PLACEHOLDER, 'non-hex id -> placeholder')
  ok(sessionHandle('ab') === 'ab', 'shorter than 4 -> whatever hex exists')
  ok(sessionHandle('a') === 'a', 'single hex char kept')
  ok(sessionHandle('session--', []) === HANDLE_PLACEHOLDER, 'prefix with empty body -> placeholder')
  const a = sessionHandle('session-1234', [])
  const b = sessionHandle('session-1234', [])
  ok(a === b, 'deterministic across calls')
}

section('E purity: taken is not mutated')
{
  const taken = ['09ca']
  const snapshot = [...taken]
  sessionHandle('session-09ca1', taken)
  ok(JSON.stringify(taken) === JSON.stringify(snapshot), 'taken array unchanged')
}

section('F executor handle constant')
{
  ok(EXECUTOR_HANDLE === 'executor', 'fixed executor handle is exactly `executor`')
}

console.log(`\n${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
