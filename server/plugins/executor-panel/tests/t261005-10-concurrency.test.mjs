/**
 * t261005-10-concurrency.test.mjs —— UI-2 Overview limit row 的读面 UT：
 * GET /api/concurrency（declared / missing / malformed / out-of-range / non-object
 * / bad project key / 405）+ parseConcurrencyDoc 纯函数（unlimited→null、整数域、
 * 畸形全抛）。外部输入消费 → 畸形输入用例必带（桩/固定文件，不靠真外部源）。
 */
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { assert, done, freshDir, isolatedEnv } from './lib.mjs'
import { createApi, parseConcurrencyDoc } from '../src/host/api.ts'
import { concurrencyDeclarationPath } from '../src/host/concurrency.ts'

const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const api = createApi(env, {})
let n = 0
const Q = (s = '') => new URLSearchParams(s)
// Seed through the DECLARED path resolver (t261008-48 contract): the fixture must
// land where the read face resolves (the projects root — WATCHDOG_DIR here, the
// grants-family precedence), never at a hand-picked directory. Seeding anywhere
// else would pin the old PANEL-first ordering that this ticket settled away.
const proj = (key) => {
  const file = concurrencyDeclarationPath(key, env)
  mkdirSync(dirname(file), { recursive: true })
  return file
}

// ---- parseConcurrencyDoc（纯函数）----
assert(parseConcurrencyDoc('{"version":1,"limit":"unlimited"}') === null, 'unlimited → null (engine None 同义)')
assert(parseConcurrencyDoc('{"version":1,"limit":1}') === 1, 'lower bound 1')
assert(parseConcurrencyDoc('{"version":1,"limit":10}') === 10, 'upper bound 10')
for (const [raw, why] of [
  ['{"version":1,"limit":0}', 'below range'],
  ['{"version":1,"limit":11}', 'above range'],
  ['{"version":1,"limit":2.5}', 'non-integer'],
  ['{"version":1,"limit":"3"}', 'string number'],
  ['{"version":1}', 'missing limit'],
  ['{"limit":3}', 'missing version'],
  ['{"version":2,"limit":3}', 'wrong version'],
  ['[]', 'array body'],
  ['null', 'null body'],
  ['{"version":1,"limit":', 'truncated JSON'],
  ['not json', 'not json'],
]) {
  let threw = false
  try { parseConcurrencyDoc(raw) } catch { threw = true }
  assert(threw, `parse throws: ${why}`)
}

// ---- API: bad key / 405 ----
let r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=../evil'))
assert(r.status === 400, 'bad project key → 400')
r = await api.handle('POST', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'), '{}')
assert(r.status === 405 || r.status === 401, 'write method refused (401 gate precedes 405 shape; never 200)')
r = await api.handle('PUT', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'), '{}')
assert(r.status === 401 || r.status === 405, 'PUT refused')

// ---- API: not declared (no dir) ----
r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=ghost'))
assert(r.status === 200 && r.json.ok === false && r.json.declared === false && r.json.limit === null
  && typeof r.json.path === 'string' && r.json.path.length > 0,
  'not declared: named refusal with provenance path, no guessed number')
assert(String(r.json.note).includes('CL-2'), 'absent write face is named (CL-2 boundary)')

// ---- API: declared ----
const declFile = proj('alpha')
writeFileSync(declFile, '{"version":1,"limit":3}')
r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'))
assert(r.status === 200 && r.json.declared === true && r.json.limit === 3 && r.json.unlimited === false
  && String(r.json.path).endsWith('concurrency-limit.json'),
  'declared: value + declaration path together (provenance)')
writeFileSync(declFile, '{"version":1,"limit":"unlimited"}')
r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'))
assert(r.json.declared === true && r.json.limit === null && r.json.unlimited === true,
  'declared unlimited: declared=true, limit=null (fact, not absence)')

// ---- API: malformed / out-of-range fail closed ----
writeFileSync(declFile, '{"version":1,"limit":')
r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'))
assert(r.json.declared === false && r.json.limit === null && String(r.json.reason).includes('JSON'),
  'malformed: fails closed with the reason verbatim')
writeFileSync(declFile, '{"version":1,"limit":42}')
r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'))
assert(r.json.declared === false && r.json.limit === null && String(r.json.reason).includes('range'),
  'out-of-range: fails closed')

done(`T261005_10_CONCURRENCY ran=${++n}`)
