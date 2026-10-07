/**
 * requests.test.mjs —— 请求账 UT：长保留不变量（未答复永不删/永不自动应答）、
 * 应答=追加不改写、畸形行计数不静默丢、等待/到期标注、API 级体解析畸形输入。
 */
import { assert, done, memLedgerIo, fakeClock } from './lib.mjs'
import {
  appendRequest, answerRequest, readRequests, requestUrgency, parseJsonBody, makeRequestId,
} from '../src/host/requests.ts'

const env = { HOME: '/nonexistent' }
const io = memLedgerIo()
const clock = fakeClock()
let n = 0

// 追加面：合法请求落账。
const f = (k) => `${env.HOME}/.sandbar/projects/${k}/requests.jsonl`
const r1 = appendRequest(io, env, 'alpha', { kind: 'approval', question: 'Can ticket T-1 merge now?', default_action: 'approve', expires_at: clock.now() + 3600_000 }, clock.now())
assert(r1.ok === true && r1.row.id.startsWith('req-'), 'append valid request ok')
assert(io.files[f('alpha')].endsWith('\n') && io.files[f('alpha')].split('\n').filter(Boolean).length === 1, 'ledger is append-only JSONL, one line per row')

// id 确定性单调。
assert(makeRequestId(5) !== makeRequestId(5), 'request ids are unique')

// 拒绝面：坏 key / 空 question / 空 kind / 坏 expires_at（kind 词表开放——判定点在引擎）。
assert(appendRequest(io, env, '../evil', { kind: 'sign', question: 'x' }, 1).ok === false, 'append rejects traversal-shaped project key')
assert(appendRequest(io, env, 'alpha', { kind: 'sign', question: '  ' }, 1).ok === false, 'append rejects blank question')
assert(appendRequest(io, env, 'alpha', { kind: '', question: 'x' }, 1).ok === false, 'append rejects empty kind')
assert(appendRequest(io, env, 'alpha', { kind: 'rerun', question: 'x' }, 2).ok === true, 'open kind vocabulary accepted (engine event kinds are not closed)')
assert(appendRequest(io, env, 'alpha', { kind: 'sign', question: 'x', expires_at: 'soon' }, 1).ok === false, 'append rejects unparseable expires_at string')
assert(appendRequest(io, env, 'alpha', { kind: 'sign', question: 'x', expires_at: '2026-09-29T12:00:00Z' }, 1).ok === true, 'append accepts ISO 8601 expires_at string')
assert(!io.files[f('alpha')].includes('"soon"'), 'rejected appends never touch the ledger')

// 应答面：追加 answer 行，原行不改写。
clock.advance(1000)
const a1 = answerRequest(io, env, 'alpha', r1.row.id, 'approved, go', 'host', clock.now())
assert(a1.ok === true, 'answer valid request ok')
const raw = io.files[f('alpha')]
const linesAfterAnswer = raw.split('\n').filter(Boolean)
const lastLine = JSON.parse(linesAfterAnswer[linesAfterAnswer.length - 1])
// t261007-02：应答成功后同落一条 answered state 行（写路径必须落 state 行）；
// answer 行仍是自己一行，原请求行不改写。
const answerLine = JSON.parse(linesAfterAnswer[linesAfterAnswer.length - 2])
assert(answerLine.type === 'answer' && answerLine.answer_for === r1.row.id, 'answer appended as its own row (request row untouched)')
assert(lastLine.type === 'state' && lastLine.state === 'answered' && lastLine.state_for === r1.row.id, 'answered state row appended after the answer row')
assert(linesAfterAnswer.filter(l => JSON.parse(l).type === 'request' && l.includes(r1.row.id)).length === 1, 'original request row still present exactly once')
const read1 = readRequests(io, env, 'alpha')
const answeredRow = read1.rows.find(x => x.id === r1.row.id)
assert(answeredRow && answeredRow.status === 'answered' && answeredRow.answer === 'approved, go', 'read merges answer into view (status=answered)')
assert(raw.includes('"question"') && answeredRow.question.includes('merge'), 'original request row never rewritten')

// 二次应答=显式拒绝（绝不静默二次关闭）。
const a2 = answerRequest(io, env, 'alpha', r1.row.id, 'again', 'host', clock.now())
assert(a2.ok === false && a2.error.includes('second close refused'), 'second answer explicitly rejected')

// 无此 id=显式拒绝。
assert(answerRequest(io, env, 'alpha', 'req-nope', 'x', 'host', 1).ok === false, 'answer unknown id explicitly rejected')

// 畸形输入：坏行计数在案、不静默丢弃（畸形应答行/坏 JSON/指向不存在请求的应答）。
io.files[f('beta')] = [
  '{"type":"request","id":"r1","at":1,"project":"beta","kind":"sign","question":"q"}',
  'not-json-at-all',
  '{"type":"answer","answer_for":"ghost","at":5,"answer":"x","by":"h"}',
  '{"type":"banana"}',
].join('\n')
const read2 = readRequests(io, env, 'beta')
assert(read2.rows.length === 1 && read2.rows[0].status === 'waiting', 'good row survives among malformed ones')
assert(read2.malformed_rows === 3, 'malformed lines counted explicitly (bad json / wrong shape / dangling answer), never silently dropped')

// 截断行（半截 JSON——进程死在写一半）也计数。
io.files[f('gamma')] = '{"type":"request","id":"r'
assert(readRequests(io, env, 'gamma').malformed_rows === 1, 'truncated line counted, not dropped')

// 等待/到期标注：到期只是标记，永不自动关闭。
const exp = requestUrgency({ ...answeredRow, status: 'waiting', expires_at: 500 }, 1500)
assert(exp.expired === true && exp.waiting_ms === Math.max(0, 1500 - answeredRow.at), 'urgency marks expired + waiting ms (absolute timestamps in, durations out)')
assert(requestUrgency({ ...answeredRow, expires_at: null }, 9).expired === false, 'no expiry = never expires')
assert(answeredRow.status === 'answered', 'answered row never re-expires')

// API 级体解析（review #2）：非 JSON / 非对象。
assert(parseJsonBody('{oops').ok === false, 'non-JSON body rejected')
assert(parseJsonBody('[1,2]').ok === false, 'non-object body rejected')
assert(parseJsonBody('{"a":1}').ok === true, 'valid object body accepted')

// raised_by 归属面（t260929-08 自锁证据源）：合法落账 / 缺省='' / 畸形 fail-closed / 历史行归一化。
const rb = appendRequest(io, env, 'alpha', { kind: 'approval', question: 'Raise the gate?', raised_by: 'executor-sb' }, clock.now())
assert(rb.ok === true && rb.row.raised_by === 'executor-sb', 'append records raised_by attribution when given')
const rbNo = appendRequest(io, env, 'alpha', { kind: 'sign', question: 'Sign T-2?' }, clock.now())
assert(rbNo.ok === true && rbNo.row.raised_by === '', 'append without raised_by defaults to unattributed (empty string)')
assert(appendRequest(io, env, 'alpha', { kind: 'sign', question: 'x', raised_by: 42 }, 1).ok === false, 'non-string raised_by rejected')
assert(appendRequest(io, env, 'alpha', { kind: 'sign', question: 'x', raised_by: '   ' }, 1).ok === false, 'blank raised_by rejected')
assert(appendRequest(io, env, 'alpha', { kind: 'sign', question: 'x', raised_by: 'x'.repeat(121) }, 1).ok === false, 'oversized raised_by (>120) rejected')
const ledgerBeforeRbRej = io.files[f('alpha')].split('\n').filter(Boolean).length
assert(!io.files[f('alpha')].includes('"raised_by":42'), 'rejected raised_by never touches the ledger')
// 历史行（无 raised_by 字段）读出归一化为 ''，不畸形、不丢。
const histFile = f('legacyproj')
io.mkdirSync(histFile.slice(0, histFile.lastIndexOf('/')), { recursive: true })
io.appendFileSync(histFile, JSON.stringify({ type: 'request', id: 'req-old-1', at: 1, project: 'beta', kind: 'sign', question: 'legacy row', detail: '', default_action: '', expires_at: null }) + '\n')
const betaRead = readRequests(io, env, "legacyproj")
assert(betaRead.malformed_rows === 0 && betaRead.rows[0]?.raised_by === '', 'legacy row without raised_by reads back as unattributed, not malformed')
assert(io.files[f('alpha')].split('\n').filter(Boolean).length === ledgerBeforeRbRej, 'rejected raised_by appends never landed on the ledger')

// group_id 组面（t261004-17 一问一行镜像）：合法落账 / 缺省不落键 / 畸形 fail-closed。
const g1 = appendRequest(io, env, 'alpha', { kind: 'question', question: 'Q1?', group_id: 'ask-42' }, clock.now())
assert(g1.ok === true && g1.row.group_id === 'ask-42', 'append records the group id when given')
const g2 = appendRequest(io, env, 'alpha', { kind: 'question', question: 'Q2?' }, clock.now())
assert(g2.ok === true && g2.row.group_id === undefined, 'append without group_id leaves the key absent (single-question row)')
assert(appendRequest(io, env, 'alpha', { kind: 'question', question: 'x', group_id: 42 }, 1).ok === false, 'non-string group_id rejected')
assert(appendRequest(io, env, 'alpha', { kind: 'question', question: 'x', group_id: '   ' }, 1).ok === false, 'blank group_id rejected')
assert(appendRequest(io, env, 'alpha', { kind: 'question', question: 'x', group_id: 'x'.repeat(121) }, 1).ok === false, 'oversized group_id (>120) rejected')
const gRead = readRequests(io, env, 'alpha')
assert(gRead.rows.find((r) => r.id === g1.row.id)?.group_id === 'ask-42', 'group id survives a read round-trip')

// 未答复行长保留：读一百次也不消失。
for (let i = 0; i < 5; i++) readRequests(io, env, 'alpha')
const linesBeforeReads = io.files[f('alpha')].split('\n').filter(Boolean).length
for (let i = 0; i < 5; i++) readRequests(io, env, 'alpha')
assert(io.files[f('alpha')].split('\n').filter(Boolean).length === linesBeforeReads, 'reading never mutates the ledger (long retention)')

// t261004-23：引擎侧投递的行（server/engine/executor_requests.py 落账，带
// surface:"engine"）在面板读出视图里原样可见——读侧零改动透传未知键；来源、
// 归属会话、waiting 状态三样都断言，不碰应答/dismiss 读路径（t261004-17 属地）。
const engineFile = f('gammaproj')
io.appendFileSync(engineFile, JSON.stringify({
  type: 'request', id: 'req-1000-0001', at: 1000, project: 'gammaproj', kind: 'decision',
  question: 'Which plan should the executor adopt?', detail: '', default_action: '',
  expires_at: null, raised_by: 'sess-exec-1', surface: 'engine',
}) + '\n')
const engineRead = readRequests(io, env, 'gammaproj')
const engineRow = engineRead.rows.find(x => x.id === 'req-1000-0001')
assert(engineRow && engineRow.status === 'waiting', 'engine-filed row shows in the waiting list')
assert(engineRow.raised_by === 'sess-exec-1', 'engine-filed row carries the executor session as raised_by')
assert(engineRow.surface === 'engine', 'engine-filed row carries the surface source marker')

n += 38
done(n)
