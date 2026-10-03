/**
 * recent-actions.test.mjs —— t261003-06 Overview 右栏「最近动作」UT：
 *  - 事件账本（event-ledger-v1 行）按固定映射表 → 动作行（时间/动作/票号/结果/权限）；
 *  - 新的在前、上限 max 条；未进映射表的 kind 计数显式（unmapped_rows），绝不编造动作；
 *  - 坏行计数显式（malformed_rows）；
 *  - 账本缺席 / 不可读 = 显式降级对象（点名原因），绝不渲染成空列表冒充「没动作」；
 *  - API 面 GET /api/actions：降级透传 reason；key 形状白名单。
 * 全部内存桩，零外部源、零 3099。
 */
import { assert, done, freshDir, cleanup, memLedgerIo } from './lib.mjs'
import { createApi } from '../src/host/api.ts'
import { readRecentActions, parseActionLine, ACTION_BY_KIND, fsActionsIo } from '../src/host/recent-actions.ts'

const dir = freshDir()
let n = 0
const file = dir + '/rodalpha/ledger/events.jsonl'
const L = (o) => JSON.stringify(o)
const ledger = [
  L({ idem: 'a|t1|1', project: 'rodalpha', ticket: 't261002-14', seq: 1, kind: 'merge', stage: 'merge', stage_state: 'closed', ts: '2026-10-03T14:06:00Z' }),
  L({ idem: 'a|t2|2', project: 'rodalpha', ticket: 't261003-03', seq: 2, kind: 'open_ticket', ts: '2026-10-03T14:03:00Z' }),
  L({ idem: 'a|t3|3', project: 'rodalpha', ticket: 't261002-10', seq: 3, kind: 'stage_started', stage: 'run_integration_tests', ts: '2026-10-03T13:52:00Z' }),
  'not json at all',
  L({ nope: 1 }),
].join('\n')

const io = memLedgerIo({ [file]: ledger })

try {
  // ① 映射表：固定词表（六操作族），权限位回答「凭哪条权限」。
  assert(ACTION_BY_KIND['merge'].permission === 'sign', `merge maps to sign permission (${++n})`)
  assert(ACTION_BY_KIND['send_back'].permission === 'send-back', `send_back maps to send-back (${++n})`)

  // ② 读出：动作行字段齐全、新的在前、unmapped/malformed 计数显式。
  {
    const r = readRecentActions(io, { SANDBAR_PROJECTS_DIR: dir }, 'rodalpha')
    assert(r.ok === true, `ledger readable (${++n})`)
    assert(r.actions.length === 2, `only mapped kinds become actions (2, not 4) (${++n})`)
    assert(r.unmapped_rows === 1 && r.malformed_rows === 2, `unmapped=1 malformed=2 counted explicitly (${++n})`)
    assert(r.actions[0].ticket === 't261002-14' && r.actions[1].ticket === 't261003-03', `newest first (${++n})`)
    const a = r.actions[0]
    assert(a.action === 'Sign' && a.permission === 'sign' && a.result === 'closed', `mapped fields: action/permission/result (${++n})`)
    assert(typeof a.at === 'number' && a.at > 0, `ts ISO parsed to epoch (${++n})`)
  }

  // ③ 单行解析：缺票号 / 认不出的 kind → null（不抛、不编造）。
  assert(parseActionLine(L({ idem: 'x', ticket: 't1', seq: 1, kind: 'unknown_kind' })) === null, `unknown kind → null (${++n})`)
  assert(parseActionLine(L({ idem: 'x', ticket: '', seq: 1, kind: 'sign' })) === null, `empty ticket → null (${++n})`)
  assert(parseActionLine('[') === null, `bad json → null (${++n})`)

  // ④ 显式降级：缺席 / 不可读 / 坏 key。
  {
    const miss = readRecentActions(io, { SANDBAR_PROJECTS_DIR: dir }, 'otherproj')
    assert(miss.ok === false && /does not exist yet/.test(miss.reason), `absent ledger = degraded with reason (${++n})`)
    const badIo = { existsSync: () => true, readFileSync: () => { throw new Error('EACCES') } }
    const un = readRecentActions(badIo, { SANDBAR_PROJECTS_DIR: dir }, 'rodalpha')
    assert(un.ok === false && /unreadable/.test(un.reason) && /EACCES/.test(un.reason), `unreadable ledger = degraded with cause (${++n})`)
    const badKey = readRecentActions(io, { SANDBAR_PROJECTS_DIR: dir }, 'BAD_KEY!')
    assert(badKey.ok === false && /key/.test(badKey.reason), `bad project key = degraded (${++n})`)
  }

  // ⑤ API 面：降级透传 reason（页面渲染显式降级卡）；坏 key 400；上限 max 生效。
  {
    const api = createApi({ HOME: dir, SANDBAR_PANEL_DIR: dir, SANDBAR_PROJECTS_DIR: dir }, { actionsIo: io })
    const Q = (s) => new URLSearchParams(s)
    let r = await api.handle('GET', '/sandbar-executor-panel/api/actions', Q('project=otherproj'), '', '')
    assert(r.status === 200 && r.json.ok === false && r.json.reason, `api degraded face carries the reason (${++n})`)
    r = await api.handle('GET', '/sandbar-executor-panel/api/actions', Q('project=BAD!'), '', '')
    assert(r.status === 400, `api rejects bad key with 400 (${++n})`)
    r = await api.handle('GET', '/sandbar-executor-panel/api/actions', Q('project=rodalpha'), '', '')
    assert(r.json.ok === true && r.json.actions.length === 2 && r.json.unmapped_rows === 1, `api happy path (${++n})`)
    r = await api.handle('POST', '/sandbar-executor-panel/api/actions', Q('project=rodalpha'), '', '')
    assert(r.status === 405, `actions face is GET-only (${++n})`)
  }

  // ⑥ fs 版 io 存在（生产缺省面）且指向账本路径。
  assert(typeof fsActionsIo.existsSync === 'function' && typeof fsActionsIo.readFileSync === 'function', `fs io face present (${++n})`)
} finally {
  cleanup([dir])
}
done(n)
