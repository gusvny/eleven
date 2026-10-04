/**
 * malformed-project-text.test.mjs —— GAP C 反证（t260929-22）：project 形状 400
 * 的报错文本必须**点名判据**（正则）与**收到什么**（空参显式 <空>），不许以裸冒号收尾。
 *
 * 覆盖面（工单 GAP C 逐位点名）：
 *   - api.ts 四处（requests GET / settings GET / settings POST / grants GET）；
 *   - 家族面：requests.ts（append/answer）、settings.ts（read/save）同文案单源。
 * 畸形输入用例（空参/大写/斜杠穿越/非字符串）全打桩，不触真实外部源。
 */
import { assert, done, freshDir, cleanup, isolatedEnv, fakeClock, authPass } from './lib.mjs'
import { createApi } from '../src/host/api.ts'
import { appendRequest } from '../src/host/requests.ts'
import { readSettings } from '../src/host/settings.ts'
import { malformedProjectMessage, PROJECT_KEY_RE } from '../src/host/project-key.ts'
import { memLedgerIo } from './lib.mjs'

const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const clock = fakeClock()
const api = createApi(env, { now: () => clock.now(), fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'workbench-workflows' }), authFace: authPass })
const Q = (s = '') => new URLSearchParams(s)
let n = 0

const NAMED = (msg) => msg.includes('a-z0-9') && msg.includes('project')

// ---- api.ts 四处：无 project 参数（裸 GET=空 key）----
let r = await api.handle('GET', '/sandbar-executor-panel/api/settings', Q(), '')
assert(r.status === 400 && NAMED(r.json.error), `settings GET: absent project names the check (${++n})`)
assert(!/:\\s*$/.test('') && !r.json.error.trimEnd().endsWith('：') && !r.json.error.trimEnd().endsWith(':'), `settings GET: no bare-colon ending (${++n})`)
r = await api.handle('POST', '/sandbar-executor-panel/api/settings', Q(), '{"op":"save","config":{}}')
assert(r.status === 400 && NAMED(r.json.error), `settings POST: absent project names the check (${++n})`)
r = await api.handle('GET', '/sandbar-executor-panel/api/grants', Q(), '')
assert(r.status === 400 && NAMED(r.json.error), `grants GET: absent project names the check (${++n})`)
// requests GET：有参但非法 → 点名；空参=全项目合法路径（不 400，维持既有契约）
r = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q('project=BAD'), '')
assert(r.status === 400 && NAMED(r.json.error), `requests GET: invalid project names the check (${++n})`)
r = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q(), '')
assert(r.status === 200, `requests GET: absent project still lists all (${++n})`)

// ---- 畸形值：收到的值原文进报错 ----
r = await api.handle('GET', '/sandbar-executor-panel/api/settings', Q('project=../evil'), '')
assert(r.status === 400 && r.json.error.includes('../evil'), `settings GET: malformed value echoed (${++n})`)
r = await api.handle('GET', '/sandbar-executor-panel/api/settings', Q('project=UPPER'), '')
assert(r.status === 400 && r.json.error.includes('UPPER'), `settings GET: uppercase echoed (${++n})`)

// ---- 家族面（requests.ts / settings.ts）同源同文案 ----
const res = appendRequest(memLedgerIo(), env, '', { kind: 'sign', question: 'q?' }, clock.now())
assert(!res.ok && NAMED(res.error) && res.error.includes('<空>'), `requests append: empty key named (${++n})`)
const res2 = readSettings('BAD_KEY', env, clock.now())
assert(res2.ok === false && NAMED(String(res2.error)), `settings read: invalid key named (${++n})`)

// ---- helper 自身：正则单源 + 空参措辞 ----
assert(PROJECT_KEY_RE.test('alpha') && !PROJECT_KEY_RE.test('') && !PROJECT_KEY_RE.test('A'), `regex single-source sanity (${++n})`)
assert(malformedProjectMessage('').includes('<空>'), `helper: empty renders as <空> (${++n})`)

cleanup([wd, pan])
done(n)
