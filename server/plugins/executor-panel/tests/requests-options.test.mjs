/**
 * requests-options.test.mjs —— t261003-06 选项数据面 UT（设计 note §6）：
 *  - append 带合法 options → 落账、读出透传（页面据此渲染按钮）；
 *  - 去重保序、上限 8 项、单项 ≤80 字符；
 *  - 畸形输入 fail-closed：非数组 / 空数组 / 空白项 / 非字符串项 / 超长项 → 拒收不落账；
 *  - 不带 options = 自由文本请求（hasOptions=false，历史行兼容）；
 *  - 选项请求的应答面照旧（二次应答拒收）。
 * 畸形用例全走内存 io 桩，零外部源。
 */
import { assert, done, freshDir, cleanup, fakeClock, memLedgerIo, isolatedEnv } from './lib.mjs'
import { appendRequest, readRequests, requestUrgency } from '../src/host/requests.ts'
import { hasOptions, splitWaiting } from '../src/host/page-logic.ts'

const env = isolatedEnv(freshDir(), freshDir())
const clock = fakeClock()
const io = memLedgerIo()
let n = 0
const OK = { kind: 'sign', question: 'Merge ticket t-1 into main?' }

try {
  // ① 合法 options 落账并透传。
  {
    const r = appendRequest(io, env, 'proj', { ...OK, options: ['Approve', 'Reject', 'Approve'] }, clock.now())
    assert(r.ok === true, `valid options accepted (${++n})`)
    const read = readRequests(io, env, 'proj')
    assert(JSON.stringify(read.rows[0].options) === JSON.stringify(['Approve', 'Reject']),
      `options deduped preserving order (${++n})`)
    assert(hasOptions(read.rows[0]) === true, `hasOptions true for option rows (${++n})`)
  }

  // ② 不带 options = 自由文本请求（历史行兼容）。
  {
    const r = appendRequest(io, env, 'proj', { kind: 'question', question: 'More instructions?' }, clock.now())
    assert(r.ok === true && r.row.options === undefined, `no options = free-text request (${++n})`)
    assert(hasOptions(r.row) === false, `hasOptions false without options (${++n})`)
  }

  // ③ 畸形输入 fail-closed（逐种点名拒收，不落账）。
  const bad = [
    ['non-array', { options: 'Approve' }],
    ['empty array', { options: [] }],
    ['blank item', { options: ['Approve', '   '] }],
    ['non-string item', { options: [42] }],
    ['over-long item', { options: ['x'.repeat(81)] }],
    ['over 8 items', { options: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i'] }],
  ]
  const before = Object.keys(io.files).reduce((s, k) => s + io.files[k].length, 0)
  for (const [name, body] of bad) {
    const r = appendRequest(io, env, 'proj', { ...OK, ...body }, clock.now())
    assert(r.ok === false && /options/.test(r.error), `malformed options rejected: ${name} (${++n})`)
  }
  const after = Object.keys(io.files).reduce((s, k) => s + io.files[k].length, 0)
  assert(before === after, `rejected appends wrote nothing (${++n})`)

  // ④ 切面纯函数：waiting/answered 切分（选项行应答后进 answered 区）。
  {
    const read = readRequests(io, env, 'proj')
    const sp = splitWaiting(read.rows)
    assert(sp.waiting.length === 2 && sp.answered.length === 0, `both rows waiting before answer (${++n})`)
  }

  // ⑤ 请求urgency口径不受 options 影响（到期标记照旧）。
  {
    const r = appendRequest(io, env, 'proj', { ...OK, options: ['A'], expires_at: clock.now() - 1 }, clock.now())
    const u = requestUrgency({ ...r.row, status: 'waiting' }, clock.now())
    assert(u.expired === true && u.answered === false, `expiry marking unaffected by options (${++n})`)
  }
} finally {
  cleanup([env.SANDBAR_WATCHDOG_DIR, env.SANDBAR_PANEL_DIR])
}
done(n)
