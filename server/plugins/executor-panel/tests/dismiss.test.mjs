/**
 * dismiss.test.mjs —— t261007-01 dismiss 面 UT：账本第三行型、读视图第三状态、
 * 显式拒绝面（二次 dismiss / 已应答再 dismiss / 未知 id / 空白 id）、原样重投
 * 拒绝（scope-6 字节同文规则）、幽灵 dismiss 畸形计数（对齐 ghost-answer 平行面）、
 * answer-after-dismiss 优先（设计 note §9 改主意规则）、API 级凭据门与状态映射。
 * 全注入（内存账本 + 假时钟 + authFace 桩），零真实 ~/.sandbar、零 3099/7233。
 */
import { assert, done, memLedgerIo, fakeClock, authPass, engineWriteStub, isolatedEnv, freshDir, cleanup } from './lib.mjs'
import {
  appendRequest, answerRequest, dismissRequest, readRequests, requestUrgency, parseJsonBody,
} from '../src/host/requests.ts'
import { createApi } from '../src/host/api.ts'

const env = { HOME: '/nonexistent' }
const io = memLedgerIo()
const clock = fakeClock()
let n = 0

const f = (k) => `${env.HOME}/.sandbar/projects/${k}/requests.jsonl`

// ---- append + dismiss 落账 ----
const r1 = appendRequest(io, env, 'alpha', { kind: 'approval', question: 'Can ticket T-1 merge now?', default_action: 'approve' }, clock.now())
assert(r1.ok === true, 'append valid request ok')

const d1 = dismissRequest(io, env, 'alpha', r1.row.id, 'host', clock.now() + 1000)
assert(d1.ok === true && d1.dismissRow.type === 'dismiss' && d1.dismissRow.dismiss_for === r1.row.id, 'dismiss appends its own row')
const lastLine = JSON.parse(io.files[f('alpha')].trim().split('\n').pop())
assert(lastLine.type === 'dismiss' && lastLine.by === 'host' && lastLine.at === clock.now() + 1000, 'dismiss row carries dismiss_for/at/by')

// ---- 读视图第三状态 ----
const read1 = readRequests(io, env, 'alpha')
const v1 = read1.rows.find(x => x.id === r1.row.id)
assert(v1 && v1.status === 'dismissed' && v1.dismissed_by === 'host' && v1.dismissed_at === clock.now() + 1000, 'read view merges dismiss into status=dismissed')
const u1 = requestUrgency(v1, clock.now() + 2000)
assert(u1.answered === false && u1.expired === false, 'dismissed row is not waiting-flagged and not expired-flagged')

// ---- 显式拒绝面 ----
assert(dismissRequest(io, env, 'alpha', r1.row.id, 'host', clock.now()).ok === false, 'second dismiss explicitly rejected')
assert(dismissRequest(io, env, 'alpha', '', 'host', clock.now()).ok === false, 'blank id explicitly rejected')
assert(dismissRequest(io, env, 'alpha', 'req-nope', 'host', clock.now()).ok === false, 'unknown id explicitly rejected')
assert(dismissRequest(io, env, '../evil', r1.row.id, 'host', clock.now()).ok === false, 'bad project key explicitly rejected')

// ---- 已应答再 dismiss：拒绝（开发者决策，方案 fault-mode 第 4 条；§9 只裁 answer-after-dismiss）----
const r2 = appendRequest(io, env, 'alpha', { kind: 'sign', question: 'Sign the release note?' }, clock.now() + 10)
assert(answerRequest(io, env, 'alpha', r2.row.id, 'signed', 'host', clock.now() + 20).ok === true, 'answer valid request ok')
const d2 = dismissRequest(io, env, 'alpha', r2.row.id, 'host', clock.now() + 30)
assert(d2.ok === false && d2.error.includes('dismiss refused'), 'dismiss on an answered request refused (developer decision, no row lands)')
const read2 = readRequests(io, env, 'alpha')
assert(read2.rows.find(x => x.id === r2.row.id).status === 'answered', 'answered row stays answered after the refused dismiss')

// ---- answer-after-dismiss 优先（设计 note §9 改主意）：状态回 answered，两条痕都在 ----
const r3 = appendRequest(io, env, 'alpha', { kind: 'question', question: 'Which epic owns KI-212?' }, clock.now() + 40)
assert(dismissRequest(io, env, 'alpha', r3.row.id, 'host', clock.now() + 50).ok === true, 'dismiss before answer ok')
assert(answerRequest(io, env, 'alpha', r3.row.id, 'epic engine', 'host', clock.now() + 60).ok === true, 'answer after dismiss accepted (change of mind)')
const read3 = readRequests(io, env, 'alpha')
const v3 = read3.rows.find(x => x.id === r3.row.id)
assert(v3.status === 'answered' && v3.dismissed_at !== undefined && v3.answered_at !== undefined, 'answer after dismiss wins; both trace marks kept')

// ---- scope-6：被 dismiss 的请求不得原样重投 ----
const ref = appendRequest(io, env, 'alpha', { kind: 'approval', question: 'Can ticket T-1 merge now?', default_action: 'approve' }, clock.now() + 70)
assert(ref.ok === false && ref.error.includes('dismiss') && ref.error.includes(r1.row.id), 'verbatim re-file of a dismissed request refused, naming the prior dismiss id')
const re2 = appendRequest(io, env, 'alpha', { kind: 'approval', question: 'Can ticket T-1 merge now? New evidence: KI-212 landed, re-check the gate.' }, clock.now() + 71)
assert(re2.ok === true, 're-raise with new evidence in the question line passes (different text)')
// answered 的同文不拦（只有 dismissed 未答才拦）。
const re3 = appendRequest(io, env, 'alpha', { kind: 'sign', question: 'Sign the release note?' }, clock.now() + 72)
assert(re3.ok === true, 'byte-identical question over an answered request is not blocked (only dismissed-and-unanswered)')

// ---- 幽灵 dismiss = 畸形留痕（对齐 ghost-answer 平行面），绝不静默 ----
io.files[f('beta')] = [
  '{"type":"request","id":"g1","at":1,"project":"beta","kind":"sign","question":"q"}',
  '{"type":"dismiss","dismiss_for":"ghost","at":5,"by":"host"}',
  '{"type":"dismiss","dismiss_for":42,"at":6,"by":"host"}',
  '{"type":"banana"}',
].join('\n')
const readB = readRequests(io, env, 'beta')
assert(readB.malformed_rows === 3, 'ghost dismiss + shape-off dismiss + junk row all counted malformed, never silent')
assert(readB.rows.length === 1 && readB.rows[0].status === 'waiting', 'the real request row survives as waiting')

// ---- API 面：同门凭据 + 状态映射 + 错配可见 ----
{
  const wd = freshDir(), pan = freshDir()
  const aenv = isolatedEnv(wd, pan)
  const aio = memLedgerIo()
  const api = createApi(aenv, { now: () => clock.now(), ledgerIo: aio, fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'stub' }), authFace: authPass, engineGrantsWrite: engineWriteStub(aenv, () => clock.now()) })
  const Q = (s = '') => new URLSearchParams(s)
  const ar = await api.handle('POST', '/sandbar-executor-panel/api/requests', Q(), JSON.stringify({ project: 'alpha', kind: 'approval', question: 'Run the deploy?' , default_action: 'deploy'}))
  assert(ar.status === 200, 'api append ok')
  const id = ar.json.row.id
  const dr = await api.handle('POST', '/sandbar-executor-panel/api/requests/dismiss', Q(), JSON.stringify({ project: 'alpha', id, by: 'someone-else' }))
  assert(dr.status === 200 && dr.json.dismissed.by === 'host' && dr.json.writer_mismatch === true && dr.json.by_claimed === 'someone-else', 'api dismiss: caller-asserted by kept only as by_claimed + writer_mismatch')
  const rr = await api.handle('GET', '/sandbar-executor-panel/api/requests', Q('project=alpha'), '')
  assert(rr.status === 200 && rr.json.rows[0].status === 'dismissed', 'api read face: dismissed no longer waiting')
  const raw = aio.files[Object.keys(aio.files).find(k => k.endsWith('/alpha/requests.jsonl'))]
  assert(raw.includes('"type":"dismiss"') && raw.includes('"by":"host"'), 'ledger read-back: dismiss row carries the session-derived identity host')
  const d2r = await api.handle('POST', '/sandbar-executor-panel/api/requests/dismiss', Q(), JSON.stringify({ project: 'alpha', id }))
  assert(d2r.status === 409, 'api second dismiss → 409')
  const d3r = await api.handle('POST', '/sandbar-executor-panel/api/requests/dismiss', Q(), JSON.stringify({ project: 'alpha', id: 'req-ghost' }))
  assert(d3r.status === 404, 'api unknown id → 404')
  const d4r = await api.handle('POST', '/sandbar-executor-panel/api/requests/dismiss', Q(), 'not json')
  assert(d4r.status === 400, 'api malformed body → 400')
  const d5r = await api.handle('POST', '/sandbar-executor-panel/api/requests/dismiss', Q(), JSON.stringify({ project: 'alpha' }))
  assert(d5r.status === 400, 'api missing id → 400')
  const d6r = await api.handle('GET', '/sandbar-executor-panel/api/requests/dismiss', Q('project=alpha'), '')
  assert(d6r.status === 405, 'api dismiss GET → 405')
  // 无凭据 = 拒绝且账本逐字节不动（在凭据门前，连体解析都不碰）。
  const aenv2 = isolatedEnv(freshDir(), freshDir())
  const aio2 = memLedgerIo()
  const apiNoAuth = createApi(aenv2, { now: () => clock.now(), ledgerIo: aio2, fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'stub' }), engineGrantsWrite: engineWriteStub(aenv2, () => clock.now()) })
  const nr = await apiNoAuth.handle('POST', '/sandbar-executor-panel/api/requests/dismiss', Q(), 'not json at all', '', '', {})
  assert(nr.status === 401, 'dismiss without credential → 401 (identity gate, not the syntax gate)')
  assert(Object.keys(aio2.files).length === 0, 'refused dismiss round touched nothing (ledger byte-identical)')
  cleanup([wd, pan, aenv.SANDBAR_WATCHDOG_DIR, aenv.SANDBAR_PANEL_DIR, aenv2.SANDBAR_WATCHDOG_DIR, aenv2.SANDBAR_PANEL_DIR])
}

// 畸形 POST 体解析（沿用既有防线，点名不静默）。
assert(parseJsonBody('[]').ok === false, 'parseJsonBody: top-level array refused')

done(++n)
