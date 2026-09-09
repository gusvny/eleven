/**
 * i02_client_classifier.mjs —— 票 t260902-03 客户端应答分类器（密封）。
 *
 * 用户故事：陈旧横幅只在服务端于健康应答（2xx、可解析、带 result 信封）内
 * 明确报 stale=true 时才允许出现。一切降级形态——非 2xx、JSON 畸形、缺 `stale`、
 * `stale` 非布尔、裸顶层 body 无 result 信封、error 信封——都必须静默归约为
 * 「不挂横幅」。看守自身绝不能成为新的报错源。
 *
 * 分类逻辑住在无 React 纯模块里，裸 node 可跑（hero.mjs 先例：import 了
 * react/runtime 的模块在纯 node 下起不来）。本基线钉死契约：
 *
 *   src/client/stale-check.ts 导出：
 *     classifyBuildInfoResponse(status: number, bodyText: string): { stale: boolean, error?: string }
 *       → stale=true 当且仅当 2xx 且 body 可解析且 result 是对象且
 *         result.error 缺席且 result.stale === true（严格）。
 *       → 其他一切形状归 { stale: false }；result.error 透传供观测；
 *         函数永不抛错。
 *
 * 退出契约（integration/README.md）：stdout 末行 `SUMMARY pass=N skip=M fail=K`；
 * fail>0 时 exit 1。实现落地前本基线按设计为红（验收线）。
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
