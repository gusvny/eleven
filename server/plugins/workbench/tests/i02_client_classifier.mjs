/**
 * i02_client_classifier.mjs — t260902-03 client-side response classifier (hermetic).
 *
 * User story: the staleness banner must appear ONLY when the server positively reports
 * stale=true inside a healthy (2xx, parseable, result-envelope) response. Every degraded
 * shape — non-2xx, malformed JSON, missing `stale`, non-boolean `stale`, a bare top-level
 * body without the result envelope, or an error envelope — must silently resolve to
 * "no banner". The watchdog must never become a new error source itself.
 *
 * The classification logic lives in a React-free pure module so it can run in bare node
 * (hero.mjs precedent: modules importing react/runtime fail under plain node). This
 * baseline pins the contract:
 *
 *   src/client/stale-check.ts exports:
 *     classifyBuildInfoResponse(status: number, bodyText: string): { stale: boolean, error?: string }
 *       -> stale=true  iff 2xx AND body parses AND result is an object AND
 *          result.error is absent AND result.stale === true (strict).
 *       -> { stale: false } for every other shape; result.error is passed through for
 *          observability; the function never throws.
 *
 * Exit contract (integration/README.md): last stdout line `SUMMARY pass=N skip=M fail=K`;
 * exit 1 iff fail>0. Pre-implementation this baseline is RED by design (acceptance bar).
 */

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}

const [maj, min] = process.versions.node.split('.').map(Number)
if (maj < 22 || (maj === 22 && min < 18)) {
  console.log(`SKIP: node ${process.versions.node} < 22.18 (no native type-stripping for .ts imports)`)
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

const MODULE = './../src/client/stale-check.ts'
let mod
try {
  mod = await import(MODULE)
} catch (err) {
  console.log(`FAIL: cannot import src/client/stale-check.ts: ${String(err && err.message ? err.message : err)}`)
  console.log('SUMMARY pass=0 skip=0 fail=1')
  process.exit(1)
}

const classify = mod?.classifyBuildInfoResponse
if (typeof classify !== 'function') {
  console.log(`FAIL: stale-check.ts must export classifyBuildInfoResponse (got exports: ${Object.keys(mod ?? {}).join(', ') || 'none'})`)
  console.log('SUMMARY pass=0 skip=0 fail=1')
  process.exit(1)
}

console.log('== classifyBuildInfoResponse matrix (stale=true means show banner)')
/** [status, bodyText, expectedStale, expectedError, label] */
const cases = [
  [200, '{"ok":true,"result":{"stale":true}}', true, undefined, 'healthy {stale:true} -> banner'],
  [200, '{"ok":true,"result":{"stale":false}}', false, undefined, '{stale:false} -> no banner'],
  [200, '{"ok":true,"result":{}}', false, undefined, '{} under result (missing stale) -> no banner'],
  [200, '{"ok":true,"result":{"stale":"true"}}', false, undefined, "{stale:'true'} (string, strict ===) -> no banner"],
  [200, '{"ok":true,"result":{"stale":1}}', false, undefined, '{stale:1} (number) -> no banner'],
  [200, '{"ok":true,"result":{"stale":true,"error":"指纹缺失"}}', false, '指纹缺失', '{stale:true,error:…} -> error wins, no banner, error passed through'],
  [200, '{"ok":true,"result":{"error":"指纹缺失"}}', false, '指纹缺失', '{error:…} -> no banner, error passed through'],
  [200, '{"stale":true}', false, undefined, 'top-level stale without result envelope -> no banner (envelope coherence)'],
  [500, '{"ok":false,"error":"boom"}', false, undefined, 'HTTP 500 -> no banner'],
  [404, 'not found', false, undefined, 'HTTP 404 -> no banner'],
  [200, 'not json at all', false, undefined, 'malformed JSON body -> no banner'],
  [200, '', false, undefined, 'empty body -> no banner'],
  [200, 'null', false, undefined, 'JSON null -> no banner'],
  [200, '[]', false, undefined, 'JSON array (no result) -> no banner'],
  [200, '{"ok":true,"result":{"stale":true,"missing":["x.ts"]}}', true, undefined, '{stale:true,missing:[…]} -> banner (missing does not veto)'],
]

for (const [status, text, expectedStale, expectedError, label] of cases) {
  let got
  let threw = null
  try { got = classify(status, text) }
  catch (err) { threw = err }
  const errNote = threw ? ` (threw: ${String(threw && threw.message ? threw.message : threw)})`
    : got?.stale !== expectedStale ? ` (got stale=${String(got?.stale)})`
    : expectedError !== undefined && got?.error !== expectedError ? ` (got error=${String(got?.error)})` : ''
  ok(threw === null && got?.stale === expectedStale && (expectedError === undefined || got?.error === expectedError),
    `${label}${errNote}`)
}

console.log('\n== never-throw fuzz (deformed status/body shapes must not raise)')
const fuzz = [
  [undefined, '{}'], [null, '{}'], [NaN, '{}'], [0, ''], [200, undefined], [200, null],
  [Infinity, '{"result":{"stale":true}}'], [-1, '{"result":{"stale":true}}'],
]
for (const [status, text] of fuzz) {
  let threw = null
  try { classify(status, text) } catch (err) { threw = err }
  ok(threw === null, `classify(${String(status)}, ${JSON.stringify(text)}) does not throw`)
}

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
