/**
 * requests-thread.test.mjs —— t261007-02 请求账线程面 UT（面板半）。
 *
 * 覆盖：五态读出（state 行按落账序生效、answer 行仍把头判成 answered——存量零迁移）、
 * waiting 只收 open（工单第 10 条）、reply/link 行合流（代投三字段分列、from 缺席的
 * duplicates link 不解析悬空 id）、宿主 dismissed 面（setThreadState 具名拒收：非
 * dismissed 态 / 终态二次关闭 / 未知 id）、应答面终态拒收 + answered state 行同落
 * （写路径必须落 state 行的不变量）、到期永不改状态、撕裂容（supersedes link 在场
 * 而 state 行缺席 → 读方重算）、存量行（无新字段）容忍。
 */
import { assert, done, memLedgerIo } from './lib.mjs'
import {
  answerRequest, readRequests, setThreadState,
} from '../src/host/requests.ts'
import { splitWaiting } from '../src/host/page-logic.ts'

const env = { HOME: '/nonexistent' }
const f = (k) => `${env.HOME}/.sandbar/projects/${k}/requests.jsonl`

function seed(io, k, rows) {
  io.files[f(k)] = rows.map(r => JSON.stringify(r) + '\n').join('')
}

const head = (id, extra = {}) => ({ type: 'request', id, at: 1000, project: 'alpha',
  kind: 'decision', question: 'q?', detail: '', default_action: 'x', expires_at: null,
  raised_by: 's1', ...extra })

// ---------- 五态读出 ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [
    head('req-1'),
    { type: 'request', id: 'req-2', at: 1001, project: 'alpha', kind: 'k', question: 'b', detail: '', default_action: '', expires_at: null, raised_by: '' },
    { type: 'request', id: 'req-3', at: 1002, project: 'alpha', kind: 'k', question: 'c', detail: '', default_action: '', expires_at: null, raised_by: '' },
    { type: 'request', id: 'req-4', at: 1003, project: 'alpha', kind: 'k', question: 'd', detail: '', default_action: '', expires_at: null, raised_by: '' },
    { type: 'request', id: 'req-5', at: 1004, project: 'alpha', kind: 'k', question: 'e', detail: '', default_action: '', expires_at: null, raised_by: '' },
    { type: 'state', id: 'st-1', state_for: 'req-2', state: 'answered', at: 2000, by: 'host' },
    { type: 'state', id: 'st-2', state_for: 'req-3', state: 'resolved', at: 2001, by: 's1', evidence: 't261007-02' },
    { type: 'state', id: 'st-3', state_for: 'req-4', state: 'dismissed', at: 2002, by: 'host' },
    { type: 'link', id: 'lnk-1', kind: 'supersedes', from: 'req-1', to: 'req-5', at: 2003, by: 's1' },
    { type: 'state', id: 'st-4', state_for: 'req-5', state: 'superseded', at: 2004, by: 's1', note: 'set automatically by the supersedes link' },
  ])
  const read = readRequests(io, env, 'alpha')
  const stOf = id => read.rows.find(r => r.id === id).state
  assert(stOf('req-1') === 'open', 'head without records stays open')
  assert(stOf('req-2') === 'answered', 'state row answered')
  assert(stOf('req-3') === 'resolved', 'state row resolved')
  assert(stOf('req-4') === 'dismissed', 'state row dismissed')
  assert(stOf('req-5') === 'superseded', 'state row superseded')
  // waiting 只收 open（工单第 10 条）：折叠区收其余四态，等待列永不回流。
  const sp = splitWaiting(read.rows)
  assert(sp.waiting.length === 1 && sp.waiting[0].id === 'req-1', 'waiting list = open items only')
  assert(sp.answered.length === 4, 'closed states collapse out of the waiting list')
}

// ---------- answer 行仍判 answered（存量行零迁移）+ answered state 行同落 ----------
{
  const io = memLedgerIo()
  const r = { ...head('req-9') }
  io.files[f('alpha')] = JSON.stringify(r) + '\n'
  const res = answerRequest(io, env, 'alpha', 'req-9', 'go', 'host', 3000)
  assert(res.ok === true, 'answer on open head ok')
  assert(res.stateRow && res.stateRow.state === 'answered', 'answer route also emits the answered state row (write path never skips the state row)')
  const lines = io.files[f('alpha')].split('\n').filter(Boolean)
  const kinds = lines.map(l => JSON.parse(l).type)
  assert(kinds.filter(t => t === 'state').length === 1, 'exactly one state row appended')
  const view = readRequests(io, env, 'alpha').rows[0]
  assert(view.state === 'answered' && view.status === 'answered', 'answer row still merges to answered (legacy rows need no migration)')
  const again = answerRequest(io, env, 'alpha', 'req-9', 'again', 'host', 4000)
  assert(again.ok === false, 'second answer refused (not open any more)')
}

// ---------- setThreadState：宿主 dismissed 面，具名拒收 ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [
    head('req-a'),
    { type: 'state', id: 'st-9', state_for: 'req-a', state: 'resolved', at: 2000, by: 's1', evidence: '0194abc' },
  ])
  io.files[f('alpha')] += JSON.stringify(head('req-b')) + '\n'
  // 只有 dismissed 从面板落；其余四态各点名去处。
  for (const bad of ['answered', 'resolved', 'superseded', 'open', 'void']) {
    const r = setThreadState(io, env, 'alpha', 'req-b', bad, 'host', 3000)
    assert(r.ok === false && r.error.includes('dismissed'), `state=${bad} refused with the way out`)
  }
  const ok = setThreadState(io, env, 'alpha', 'req-b', 'dismissed', 'host', 3000)
  assert(ok.ok === true && ok.stateRow.state === 'dismissed', 'host dismisses an open item')
  // void 的一问：2026-10-06 的十条挂账由此可关。
  const again = setThreadState(io, env, 'alpha', 'req-a', 'dismissed', 'host', 3001)
  assert(again.ok === false && again.error.includes('resolved'), 'terminal state refuses a second state row')
  const missing = setThreadState(io, env, 'alpha', 'req-404', 'dismissed', 'host', 3002)
  assert(missing.ok === false, 'unknown id refused')
}

// ---------- reply 合流：代投三字段分列可见 ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [
    head('req-c'),
    { type: 'reply', id: 'rpl-1', reply_for: 'req-c', at: 2000, text: 'host chose plan A',
      by: 'sess-exec-1', intent: 'answer', via: 'integration-agent', anchor: 'go with A' },
  ])
  const view = readRequests(io, env, 'alpha').rows[0]
  assert(view.replies.length === 1, 'reply merged into the head view')
  const rp = view.replies[0]
  assert(rp.by === 'sess-exec-1' && rp.via === 'integration-agent' && rp.anchor === 'go with A',
    'delegated answer carries by/via/anchor as separate fields')
  assert(view.state === 'open', 'a reply never changes the state')
}

// ---------- link 合流：from 缺席的 duplicates link 不解析悬空 id ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [
    head('req-d', { subject: 'fam', epic: 'proj-epic', source_ticket: 't261007-02', source_class: 'executor-session' }),
    { type: 'link', id: 'lnk-2', kind: 'duplicates', to: 'req-d', at: 2000, by: 's2',
      dup_subject: 'fam', dup_epic: 'proj-epic', dup_source_ticket: 't261007-02' },
  ])
  const read = readRequests(io, env, 'alpha')
  const view = read.rows.find(r => r.id === 'req-d')
  assert(view.links.length === 1 && view.links[0].to === 'req-d', 'duplicates link merged onto the target head')
  assert(view.links[0].from === undefined, 're-file link omits from (the denied filing never became a row)')
  assert(read.malformed_rows === 0, 'a from-less duplicates link is not malformed')
  assert(view.state === 'open', 'a duplicates link does not close the head')
}

// ---------- 撕裂容：supersedes link 在场而 state 行缺席 → 读方重算 ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [
    head('req-e'),
    { type: 'link', id: 'lnk-3', kind: 'supersedes', from: 'req-x', to: 'req-e', at: 2000, by: 's1' },
  ])
  const view = readRequests(io, env, 'alpha').rows[0]
  assert(view.state === 'superseded', 'torn supersedes link recomputed to superseded at read (display repair only)')
}

// ---------- 存量行容忍：无新字段的头照常渲染（分类待宿主拍板，不发明） ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-old')])
  const view = readRequests(io, env, 'alpha').rows[0]
  assert(view.subject === undefined && view.epic === undefined && view.source_ticket === undefined,
    'legacy head lacks the new fields without becoming malformed')
  assert(view.state === 'open', 'legacy head is open')
}

// ---------- 到期永不改状态（工单第 8 条） ----------
{
  const io = memLedgerIo()
  seed(io, 'alpha', [head('req-f', { expires_at: 500 })])
  const view = readRequests(io, env, 'alpha').rows[0]
  assert(view.state === 'open', 'an expired item is still open — expiry drives display and reminder level only')
}

done()
