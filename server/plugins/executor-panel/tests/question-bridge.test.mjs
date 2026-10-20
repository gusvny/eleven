/**
 * question-bridge.test.mjs —— 问题桥 UT（t261001-23，KI-181）：
 * 镜像落账 / 畸形请求拒绝 / 项目反查 / 账上应答映射回会话 / 下游先答补账 /
 * 下游 NO_PROVIDER 继续等账 / abort 与 deadline 全终态收口 / 坏账行不崩轮询。
 */
import { assert, done, memLedgerIo, fakeClock, freshDir, cleanup } from './lib.mjs'
import {
  validateAskRequest, validateQuestionFields, mirrorToLedger, mapLedgerAnswer, projectKeyForCwd,
  waitForLedgerAnswer, createQuestionBridge, readProjectDirsFromYaml, makeRegistryProjectResolver,
} from '../src/host/question-bridge.ts'
import { readRequests } from '../src/host/requests.ts'

const env = { HOME: freshDir('qb-home-') }
let n = 0

const REQ = (over = {}) => ({
  questions: [{ id: 'q1', question: 'Grant writes now?', detail: 'conflicts with t261001-19 item 8', options: [{ label: 'Grant now' }, { label: 'Wait' }] }],
  agent: { id: 'session-09ca0247', cwd: '/repo' },
  ...over,
})

// ── 校验与镜像 ────────────────────────────────────────────────────────────────
{
  const io = memLedgerIo()
  assert(validateAskRequest(REQ()).ok === true, 'well-formed request passes validation')
  assert(validateAskRequest({}).ok === false, 'missing questions rejected')
  assert(validateAskRequest({ questions: [] }).ok === false, 'empty questions rejected')
  assert(validateAskRequest({ questions: [{ question: '  ' }] }).ok === false, 'blank question text rejected')

  const r = mirrorToLedger(io, env, 'sandbar', REQ(), 1000)
  assert(r.ok === true, 'mirror valid request ok')
  const read = readRequests(io, env, 'sandbar')
  assert(read.rows.length === 1, 'mirrored row lands in ledger')
  assert(read.rows[0].kind === 'question', 'mirrored row kind=question')
  assert(read.rows[0].raised_by === 'session-09ca0247', 'raised_by carries the asking session id (self-lock attribution)')
  assert(read.rows[0].question === 'Grant writes now?', 'mirrored question text preserved')
  assert(read.rows[0].detail.includes('conflicts with t261001-19'), 'detail preserved for the human')

  // t261004-17 一问一行：两问 → 两行，各自带 options / default_action / expires_at / group_id。
  const two = mirrorToLedger(io, env, 'sandbar', {
    id: 'ask-42',
    questions: [
      { id: 'a', question: 'Restart the worker?', detail: 'queue is stalled', options: [{ label: 'Restart now' }, { label: 'Leave it' }], default_action: 'leave it running' },
      { id: 'b', question: 'Open the red-clear ticket?', options: [{ label: 'Open it' }, { label: 'Skip' }], expires_at: 1000 + 3600_000 },
    ],
    agent: { id: 'session-09ca0247' },
  }, 1000)
  assert(two.ok === true && two.rows.length === 2, 'two-question ask mirrors as two rows')
  assert(two.group_id === 'ask-42', 'the ask id becomes the group id when given')
  const twoRows = readRequests(io, env, 'sandbar').rows.filter((r) => r.group_id === 'ask-42')
  assert(twoRows[0].question === 'Restart the worker?' && twoRows[1].question === 'Open the red-clear ticket?', 'each row carries its own question')
  assert(JSON.stringify(twoRows[0].options) === JSON.stringify(['Restart now', 'Leave it']), 'question 1 row carries its own options')
  assert(JSON.stringify(twoRows[1].options) === JSON.stringify(['Open it', 'Skip']), 'question 2 row carries its own options')
  assert(twoRows[0].default_action === 'leave it running', 'default action is mirrored')
  assert(twoRows[1].default_action === '' && twoRows[1].expires_at === 1000 + 3600_000, 'expires_at mirrored; absent default action stays empty')
  assert(twoRows[0].group_id === 'ask-42' && twoRows[1].group_id === 'ask-42', 'both rows share the group id')
  const autoGroup = mirrorToLedger(io, env, 'sandbar', REQ({ questions: [{ question: 'a' }, { question: 'b' }] }), 1000)
  assert(autoGroup.ok === true && autoGroup.group_id.startsWith('group-'), 'a group id is minted when the ask has no id')

  // 畸形请求绝不写账；agent.id 畸形显式拒绝（不静默丢归属）。
  const bad = mirrorToLedger(io, env, 'sandbar', REQ({ questions: [{ question: '' }] }), 1001)
  const beforeBad = readRequests(io, env, 'sandbar').rows.length
  assert(bad.ok === false && readRequests(io, env, 'sandbar').rows.length === beforeBad, 'malformed request never touches the ledger')
  const badId = mirrorToLedger(io, env, 'sandbar', REQ({ agent: { id: '   ' } }), 1002)
  assert(badId.ok === false, 'blank agent.id refused (never silently drop attribution)')
  assert(mirrorToLedger(io, env, 'sandbar', REQ({ agent: null }), 1003).ok === true, 'agentless request mirrors with empty raised_by')
  const badOpts = mirrorToLedger(io, env, 'sandbar', REQ({ questions: [{ question: 'x', options: 'yes' }] }), 1004)
  assert(badOpts.ok === false && badOpts.landed_ids.length === 0, 'malformed options refuse the whole mirror before any append')
  const badAct = mirrorToLedger(io, env, 'sandbar', REQ({ questions: [{ question: 'x', options: [{ label: 'A' }], default_action: 3 }] }), 1005)
  assert(badAct.ok === false, 'malformed default_action refuses the mirror (not silently dropped)')
  const badExp = mirrorToLedger(io, env, 'sandbar', REQ({ questions: [{ question: 'x', expires_at: 'not-a-date' }] }), 1006)
  assert(badExp.ok === false, 'malformed expires_at refuses the mirror')
  assert(readRequests(io, env, 'sandbar').rows.filter((r) => r.question === 'x').length === 0, 'refused mirrors leave nothing in the ledger')
}

// ── 应答映射 ─────────────────────────────────────────────────────────────────
{
  const a1 = mapLedgerAnswer(REQ(), ['Wait'])
  assert(a1.answers[0].selected[0] === 'Wait' && a1.answers[0].custom === undefined, 'exact option label maps to selected')
  const a2 = mapLedgerAnswer(REQ(), ['grant after t261001-19 lands'])
  assert(a2.answers[0].selected.length === 0 && a2.answers[0].custom === 'grant after t261001-19 lands', 'free text maps to custom')
  // t261004-17：answers[i] 钉在第 i 问自己那行——同一标签出现在两问里只在被答的那问生效。
  const TWO = REQ({ questions: [
    { id: 'a', question: 'Restart the worker?', options: [{ label: 'Yes' }, { label: 'No' }] },
    { id: 'b', question: 'Open the red-clear ticket?', options: [{ label: 'Yes' }, { label: 'No' }] },
  ] })
  const a3 = mapLedgerAnswer(TWO, ['', 'Yes'])
  assert(a3.answers[0].selected.length === 0, 'answering question 2 leaves question 1 untouched')
  assert(a3.answers[1].selected[0] === 'Yes', 'the answer lands on the chosen question only')
  const a4 = mapLedgerAnswer(TWO, ['Yes', 'Yes'])
  assert(a4.answers[0].selected[0] === 'Yes' && a4.answers[1].selected[0] === 'Yes', 'same label in both questions selects each where answered')
  const a5 = mapLedgerAnswer(REQ(), [])
  assert(a5.answers[0].selected.length === 0 && a5.answers[0].custom === undefined, 'missing answer slot maps to empty selection (no fabrication)')
  const a6 = mapLedgerAnswer(REQ(), ['line one\nline two'])
  assert(a6.answers[0].custom === 'line one\nline two', 'multi-line custom answer stays on its own question')
}

// ── 单问字段预检（畸形拒绝，绝不静默丢）──────────────────────────────────────
{
  assert(validateQuestionFields({ question: 'x', options: [{ label: 'A' }] }).ok === true, 'valid option labels pass')
  assert(validateQuestionFields({ question: 'x', options: 'yes' }).ok === false, 'string options refused')
  assert(validateQuestionFields({ question: 'x', options: [{ label: '' }] }).ok === false, 'empty label refused')
  assert(validateQuestionFields({ question: 'x', options: [{}] }).ok === false, 'label-less option refused')
  assert(validateQuestionFields({ question: 'x', options: [{ label: 'y'.repeat(81) }] }).ok === false, 'overlong label refused')
  assert(validateQuestionFields({ question: 'x', options: Array.from({ length: 9 }, (_, i) => ({ label: 'o' + i })) }).ok === false, 'more than 8 options refused')
  assert(validateQuestionFields({ question: 'x', default_action: 'hold' }).ok === true, 'string default action passes')
  assert(validateQuestionFields({ question: 'x', default_action: 3 }).ok === false, 'numeric default action refused')
  assert(validateQuestionFields({ question: 'x', expires_at: '2026-10-05T00:00:00Z' }).ok === true, 'ISO expires_at passes')
  assert(validateQuestionFields({ question: 'x', expires_at: 'not-a-date' }).ok === false, 'unparseable expires_at refused')
}

// ── 项目反查 ─────────────────────────────────────────────────────────────────
{
  const dirs = { sandbar: ['/Users/xingu/Documents/sandbar'], other: ['/somewhere'] }
  const readDirs = (k) => dirs[k] ?? null
  assert(projectKeyForCwd(['sandbar', 'other'], readDirs, '/Users/xingu/Documents/sandbar').project === 'sandbar', 'cwd exactly a declared dir hits')
  assert(projectKeyForCwd(['sandbar'], readDirs, '/Users/xingu/Documents/sandbar/.lane/t261001-23').project === 'sandbar', 'cwd under a declared dir hits (prefix)')
  assert(projectKeyForCwd(['other'], readDirs, '/Users/xingu/other-repo').ok === false, 'uncovered cwd explicitly refused')
  assert(projectKeyForCwd(['sandbar'], readDirs, '').ok === false, 'missing cwd explicitly refused')
  assert(projectKeyForCwd(['../evil'], readDirs, '/Users/xingu/Documents/sandbar').ok === false, 'traversal-shaped project key skipped')
  assert(readProjectDirsFromYaml('schema: v1\nproject:\n  - key: k\n    dirs:\n      - /a/b\n      - \'/c d\'\n').join('|') === '/a/b|/c d', 'dirs parser reads quoted and plain entries')
}

// ── 账上应答等待（全终态）────────────────────────────────────────────────────
{
  const io = memLedgerIo()
  const clock = fakeClock()
  const w = waitForLedgerAnswer({ io, env, project: 'sandbar', requestIds: ['req-x'], signal: null, pollMs: 1, deadlineMs: 1000, now: clock.now })
  const ac = new AbortController()
  const w2 = waitForLedgerAnswer({ io, env, project: 'sandbar', requestIds: ['req-y'], signal: ac.signal, pollMs: 1, deadlineMs: 100_000, now: clock.now })
  ac.abort()
  assert((await w2).state === 'aborted', 'pre-aborted signal resolves aborted immediately')
  const w3 = waitForLedgerAnswer({ io, env, project: 'sandbar', requestIds: ['req-z'], signal: null, pollMs: 1, deadlineMs: 10, now: clock.now })
  clock.advance(100)
  assert((await w3).state === 'deadline', 'deadline reached resolves explicitly (no orphan wait)')
  // 人答了 → answered 带原文。
  const m = mirrorToLedger(io, env, 'sandbar', REQ(), clock.now())
  const w4 = waitForLedgerAnswer({ io, env, project: 'sandbar', requestIds: [m.rows[0].id], signal: null, pollMs: 1, deadlineMs: 100_000, now: clock.now })
  const { answerRequest } = await import('../src/host/requests.ts')
  answerRequest(io, env, 'sandbar', m.rows[0].id, 'Wait', 'host', clock.now())
  const out = await w4
  assert(out.state === 'answered' && out.answers[0] === 'Wait', 'ledger answer row resolves the wait with the raw text')
  // 组等待：两问的行，只答一行不结算；两行都答才 answered，answers 与行同序。
  const g = mirrorToLedger(io, env, 'sandbar', REQ({ questions: [{ id: 'a', question: 'a?', options: [{ label: 'Yes' }] }, { id: 'b', question: 'b?', options: [{ label: 'Yes' }] }] }), clock.now())
  const ids = g.rows.map((r) => r.id)
  const wg = waitForLedgerAnswer({ io, env, project: 'sandbar', requestIds: ids, signal: null, pollMs: 1, deadlineMs: 100_000, now: clock.now })
  answerRequest(io, env, 'sandbar', ids[1], 'Yes', 'host', clock.now())
  await new Promise((r) => setTimeout(r, 10))
  const partial = await Promise.race([wg.then(() => 'done'), new Promise((r) => setTimeout(() => r('pending'), 40))])
  assert(partial === 'pending', 'a group wait does not settle while one question row is unanswered')
  answerRequest(io, env, 'sandbar', ids[0], 'Yes', 'host', clock.now())
  const gout = await wg
  assert(gout.state === 'answered' && JSON.stringify(gout.answers) === JSON.stringify(['Yes', 'Yes']), 'a group wait settles when every row is answered, answers in row order')
  // w（req-x）没人答：拨过它的 deadline，显式收口（验证不悬挂）。
  clock.advance(2000)
  assert((await w).state === 'deadline', 'unanswered wait resolves at its deadline (no orphan timer)')
}

// ── 瀑布监听者：路径矩阵 ─────────────────────────────────────────────────────
{
  const io = memLedgerIo()
  const clock = fakeClock()
  const events = []
  const answerRequest2 = (await import('../src/host/requests.ts')).answerRequest

  // ① 畸形请求 → 透传下游，不镜像。
  {
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 1, onEvent: (e) => events.push(e), resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    const out = await bridge({ questions: [] }, async () => ({ answers: [{ id: 'q', selected: ['ui'] }] }))
    assert(out.answers[0].selected[0] === 'ui', 'malformed request delegates downstream')
    assert(events.at(-1).kind === 'malformed-request', 'malformed request leaves an explicit event, no silent skip')
    assert(readRequests(io, env, 'sandbar').rows.length === 0, 'malformed request never mirrored')
  }

  // ② 项目解析失败 → 透传下游，不镜像。
  {
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 1, onEvent: () => {}, resolveProject: () => ({ ok: false, error: 'no project covers cwd' }) })
    const out = await bridge(REQ(), async () => ({ answers: [{ id: 'q1', selected: ['ui'] }] }))
    assert(out.answers[0].selected[0] === 'ui', 'unresolvable project delegates downstream')
    assert(readRequests(io, env, 'sandbar').rows.length === 0, 'unresolvable project never mirrored')
  }

  // ③ 账上应答先到 → 映射回会话（KI-181 修复路径：无 UI，人经面板答）。
  {
    const events2 = []
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 1, onEvent: (e) => events2.push(e), resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    const p = bridge(REQ(), async () => { await new Promise(r => setTimeout(r, 50)); return { answers: [{ id: 'q1', selected: ['ui'] }] } })
    await new Promise(r => setTimeout(r, 10))
    const row = readRequests(io, env, 'sandbar').rows.find(r => r.status === 'waiting')
    assert(row && row.raised_by === 'session-09ca0247', 'question is on the ledger waiting while the session asks (delivery surface exists)')
    answerRequest2(io, env, 'sandbar', row.id, 'Wait', 'host', clock.now())
    const out = await p
    assert(out.answers[0].selected[0] === 'Wait', 'ledger answer unblocks the session via mapped answer')
    assert(events2.some(e => e.kind === 'answered-by-ledger'), 'ledger-answer path leaves an explicit event')
  }

  // ④ 下游 UI 先答 → 透传并补 answer 行（账是审计真源）。
  {
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 60_000, onEvent: () => {}, resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    const out = await bridge(REQ(), async () => ({ answers: [{ id: 'q1', selected: ['Grant now'] }] }))
    assert(out.answers[0].selected[0] === 'Grant now', 'downstream UI answer passes through')
    const rows = readRequests(io, env, 'sandbar').rows
    assert(rows.some(r => r.status === 'answered' && r.answered_by === 'downstream-ui' && r.answer === 'Grant now'), 'downstream answer appended to its own row for audit')
  }

  // ⑤ 下游显式 NO_PROVIDER（KI-181 形态）→ 不砸会话，继续等账上应答。
  {
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 1, onEvent: () => {}, resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    const p = bridge(REQ(), async () => { throw new Error('no user-questions answerer accepted the request') })
    await new Promise(r => setTimeout(r, 10))
    const row = readRequests(io, env, 'sandbar').rows.find(r => r.status === 'waiting')
    answerRequest2(io, env, 'sandbar', row.id, 'Wait', 'host', clock.now())
    const out = await p
    assert(out.answers[0].selected[0] === 'Wait', 'NO_PROVIDER downstream keeps waiting on the ledger; human answer unblocks')
  }

  // ⑥ abort：会话被取消 → 显式失败收口，不悬挂。
  {
    const ac = new AbortController()
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 1, onEvent: () => {}, resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    const p = bridge(REQ({ signal: ac.signal }), () => new Promise(() => {})) // 下游永不返回
    await new Promise(r => setTimeout(r, 10))
    ac.abort()
    let threw = ''
    try { await p } catch (e) { threw = e.message }
    assert(threw.includes('aborted'), 'aborted ask resolves as an explicit failure (no hang, no fake answer)')
  }

  // ⑦ 下游抛错 + 账上也永远没人答 + deadline → 显式失败（会话不再无限等）。
  {
    const bridge = createQuestionBridge({ io, env, now: clock.now, pollMs: 1, deadlineMs: 30, onEvent: () => {}, resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    let threw = ''
    try {
      const p = bridge(REQ(), async () => { throw new Error('no user-questions answerer accepted the request') })
      clock.advance(1000) // 拨过 deadline（假时钟），deadline 收口可被观测。
      await p
    } catch (e) { threw = e.message }
    assert(threw.includes('超过') || threw.includes('等待'), 'deadline after NO_PROVIDER surfaces as an explicit failure')
  }

  // ⑧ 坏账行（畸形 JSON）不崩轮询：轮询继续等到合法应答。
  {
    const badIo = memLedgerIo()
    badIo.files[`${env.HOME}/.sandbar/projects/sandbar/requests.jsonl`] = '{broken json\n'
    const bridge = createQuestionBridge({ io: badIo, env, now: clock.now, pollMs: 1, onEvent: () => {}, resolveProject: () => ({ ok: true, project: 'sandbar' }) })
    const p = bridge(REQ(), async () => { throw new Error('no user-questions answerer accepted the request') })
    await new Promise(r => setTimeout(r, 10))
    const row = readRequests(badIo, env, 'sandbar')
    assert(row.malformed_rows >= 1, 'pre-existing broken ledger line counted explicitly')
    const rid = row.rows[0].id
    answerRequest2(badIo, env, 'sandbar', rid, 'Wait', 'host', clock.now())
    const out = await p
    assert(out.answers[0].selected[0] === 'Wait', 'polling survives malformed ledger rows and still delivers the answer')
  }
}

// ── 生产版解析面（文件版，临时 HOME）────────────────────────────────────────
{
  const root = `${env.HOME}/.sandbar/projects/sandbar`
  const { mkdirSync, writeFileSync } = await import('node:fs')
  mkdirSync(root, { recursive: true })
  writeFileSync(`${root}/project.yaml`, 'schema: v1\nproject:\n  - key: sandbar\n    dirs:\n      - /repo\n')
  const resolve = makeRegistryProjectResolver(env, () => ['sandbar', 'junk!!'], (p) => {
    if (p.endsWith('project.yaml')) return 'project:\n  - key: sandbar\n    dirs:\n      - /repo\n'
    throw new Error('no file')
  })
  assert(resolve({ agent: { id: 's1', cwd: '/repo/sub/dir' } }).project === 'sandbar', 'registry resolver maps cwd to project via project.yaml')
  assert(resolve({ agent: { id: 's1', cwd: '/nowhere' } }).ok === false, 'registry resolver refuses uncovered cwd explicitly')
  assert(resolve({}).ok === false, 'registry resolver refuses agentless request explicitly')
}

cleanup([env.HOME])
done(n)
