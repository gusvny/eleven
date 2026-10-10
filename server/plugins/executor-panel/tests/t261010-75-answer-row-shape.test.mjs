/**
 * t261010-75-answer-row-shape.test.mjs —— KI-01M4HPGHVWAKB62TXYV4G7ENEB 面板半 UT。
 *
 * 覆盖（票面验收 1-4）：
 * - 畸形答案行（at 为字符串——KI 现场）不把头清掉：waiting 保留、malformed_rows 点名（安全方向）；
 * - 规范答案行清掉头（防止收得过紧的变异检验）；
 * - 走特许写手 answerRequest 端到端：追加后再读面板自己的拆分（readRequests），
 *   请求离开 waiting（不只看引擎账）；
 * - answerRequest 同落的 answered state 行在场时，畸形 answer 行也翻不了已清的头
 *   （历史面板行保持 answered 的裁决面）。
 * 零真实 ~/.sandbar、零 3099（io 全注入 memLedgerIo）。
 */
import { assert, done, memLedgerIo } from './lib.mjs'
import { answerRequest, readRequests } from '../src/host/requests.ts'

const env = { HOME: '/nonexistent' }
const f = (k) => `${env.HOME}/.sandbar/projects/${k}/requests.jsonl`

function seed(io, k, rows) {
  io.files[f(k)] = rows.map(r => JSON.stringify(r) + '\n').join('')
}

const head = (id) => ({ type: 'request', id, at: 1000, project: 'alpha',
  kind: 'decision', question: 'q?', detail: '', default_action: 'x', expires_at: null,
  raised_by: 's1' })

// 1. KI 现场形状：at 为字符串的答案行 → 头仍 waiting，畸形计数点名。
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-1'), { type: 'answer', answer_for: 'req-1', at: '2000', answer: 'done' }])
  const read = readRequests(io, env, 'alpha')
  const row = read.rows.find(r => r.id === 'req-1')
  assert(row.status === 'waiting', 'string-at answer row keeps the head waiting (KI replay)')
  assert(read.malformed_rows === 1, 'the shape-off answer row is counted as malformed, never silent')
}

// 2. 缺 answer 字段同样不清头、同样点名。
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-1'), { type: 'answer', answer_for: 'req-1', at: 2000 }])
  const read = readRequests(io, env, 'alpha')
  assert(read.rows.find(r => r.id === 'req-1').status === 'waiting', 'answer-less answer row keeps the head waiting')
  assert(read.malformed_rows === 1, 'answer-less answer row counted as malformed')
}

// 3. 变异检验：规范形状的答案行确实清头（防止读侧收得过紧）。
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-1'), { type: 'answer', answer_for: 'req-1', at: 2000, answer: 'done', by: 'host' }])
  const read = readRequests(io, env, 'alpha')
  assert(read.rows.find(r => r.id === 'req-1').status === 'answered', 'a canonical answer row clears the head on the panel face too')
  assert(read.malformed_rows === 0, 'clean ledger has zero malformed rows')
}

// 4. 验收 4 端到端：走特许写手 answerRequest 落账，再读面板自己的拆分，行离开 waiting。
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-1')])
  const before = readRequests(io, env, 'alpha')
  assert(before.rows.find(r => r.id === 'req-1').status === 'waiting', 'before the answer the panel split shows waiting')
  const out = answerRequest(io, env, 'alpha', 'req-1', 'approved', 'host', 2000)
  assert(out.ok === true, 'the sanctioned writer lands the answer')
  const after = readRequests(io, env, 'alpha')
  assert(after.rows.find(r => r.id === 'req-1').status === 'answered', 'after the sanctioned answer the panel split shows answered (acceptance 4)')
  // 落盘行形状读回（读方证据，不信写手回执）。
  const lines = io.files[f('alpha')].split('\n').filter(l => l.trim() !== '').map(l => JSON.parse(l))
  const answerRow = lines.find(r => r.type === 'answer')
  assert(typeof answerRow.at === 'number' && typeof answerRow.answer === 'string'
    && typeof answerRow.answer_for === 'string', 'the landed answer row carries the canonical shape on disk')
}

// 5. 历史裁决面：answer 行畸形但 answered state 行在场（面板写手同落）→ 头仍 answered。
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-1'),
    { type: 'answer', answer_for: 'req-1', at: '2000', answer: 'done' },
    { type: 'state', id: 'st-1', state_for: 'req-1', state: 'answered', at: 2001, by: 'host' }])
  const read = readRequests(io, env, 'alpha')
  assert(read.rows.find(r => r.id === 'req-1').status === 'answered', 'the answered state row keeps panel-written history answered despite the stray malformed twin')
}

done(9)
