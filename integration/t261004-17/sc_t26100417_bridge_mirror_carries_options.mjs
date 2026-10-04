// sc_t26100417_bridge_mirror_carries_options.mjs — t261004-17 缺陷1/缺陷2 写侧面
// （灰盒 L2，直驱真实桥与账模块，离线零 docker 零浏览器，红线零接触 3099）。
//
// Intent（用户可感知行为；工单 Part A）：执行器经桥提出的请求，宿主在面板上看到的
// 是可回答的——每个问题自带选项与默认动作，不退化为纯文本自由问答。
//   M1 一个两问两选项的真形 ask 经 mirrorToLedger 落账为**每个问题一行**，每行自带
//      本问题的 question/options/default_action/expires_at，并带同一 group 标识；
//      经 readRequests 读出（面板读的同一视图）仍逐行带选项与默认动作。
//   M2 单问带选项请求照旧一行、选项原样（顺序保持）——不因多问改写而回归。
//   M3 畸形输入 fail-closed：某问的 options 非数组 / default_action 非字符串 /
//      expires_at 不可解析 → 镜像拒绝且点名字段，台账不落半行。
//   M4 无选项问题照旧自由文本路径（无 options 字段，不报错）。
// intent 分工：append 面的选项规整/4xx 契约归 t261003-06-executor-panel-requests-options
// O1–O5；列表契约（source/order/cap/empty）归 t261004-14；本条只锁「桥不吞数据」
// 与「多问不并行」这两个本票病灶。模块缺席/缺导出=FAIL 点名（TDD 期红属预期，
// arbitrate/merge 期必须绿）。
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const REPO = fileURLToPath(new URL('../../', import.meta.url))
const BRIDGE = join(REPO, 'server/plugins/executor-panel/src/host/question-bridge.ts')
const REQUESTS = join(REPO, 'server/plugins/executor-panel/src/host/requests.ts')

function memIo() {
  const files = {}
  return {
    files,
    existsSync: (f) => f in files,
    readFileSync: (f) => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f] },
    appendFileSync: (f, line) => { files[f] = (files[f] || '') + line },
    mkdirSync: () => {},
  }
}

// 真形两问两选项 ask（工单证据要求的回放形状）。
const TWO_Q = () => ({
  questions: [
    { id: 'q1', question: 'Which ticket does the executor verify first?', detail: 't1 blocks t2; t2 has newer failures.', options: [{ label: 'Verify t1 first' }, { label: 'Verify t2 first' }], default_action: 'Verify t1 first', expires_at: 1_800_000_000_000 },
    { id: 'q2', question: 'May the executor restart the worker?', detail: 'Worker is wedged since the last deploy.', options: [{ label: 'Restart now' }, { label: 'Leave it' }], default_action: 'Leave it', expires_at: null },
  ],
  agent: { id: 'session-261004', cwd: '/repo' },
})

async function main() {
  if (!existsSync(BRIDGE) || !existsSync(REQUESTS)) {
    C.case('bridge-modules-present', false, 'question-bridge.ts / requests.ts 缺席')
    return C.exit()
  }
  const bridge = await import(pathToFileURL(BRIDGE).href).catch((e) => null)
  const req = await import(pathToFileURL(REQUESTS).href).catch(() => null)
  if (!bridge || typeof bridge.mirrorToLedger !== 'function') {
    C.case('mirrorToLedger-export', false, 'question-bridge.ts 缺 mirrorToLedger 导出（TDD 期红属预期）')
    return C.exit()
  }
  if (!req || typeof req.readRequests !== 'function') {
    C.case('readRequests-export', false, 'requests.ts 缺 readRequests 导出')
    return C.exit()
  }

  const env = { HOME: '/nonexistent-t261004-17' }

  // M1 两问两选项 → 每问一行，行行带选项/默认动作/过期；组内同行标识
  {
    const io = memIo()
    const out = bridge.mirrorToLedger(io, env, 'sandbar', TWO_Q(), Date.now())
    const okMirror = !out || out.ok !== false
    const view = req.readRequests(io, env, 'sandbar')
    const qs = view.rows.filter(r => r.kind === 'question' && r.status === 'waiting')
    const q1 = qs.find(r => /verify first/i.test(r.question || ''))
    const q2 = qs.find(r => /restart the worker/i.test(r.question || ''))
    const optOk = (r, want) => r && Array.isArray(r.options) && JSON.stringify(r.options) === JSON.stringify(want)
    const groupIds = qs.map(r => r.group_id ?? r.group ?? null).filter(Boolean)
    C.case('M1-two-questions-two-rows',
      okMirror && qs.length === 2 && optOk(q1, ['Verify t1 first', 'Verify t2 first']) && optOk(q2, ['Restart now', 'Leave it'])
        && q1.default_action === 'Verify t1 first' && q2.default_action === 'Leave it',
      `rows=${qs.length} q1=${JSON.stringify(q1 && q1.options)} q2=${JSON.stringify(q2 && q2.options)}`)
    C.case('M1b-expires-and-group-visible',
      qs.length === 2 && q1 && q1.expires_at === 1_800_000_000_000 && q2 && q2.expires_at === null && new Set(groupIds).size === 1,
      `expires1=${q1 && q1.expires_at} expires2=${q2 && q2.expires_at} groups=${JSON.stringify(groupIds)}`)
  }

  // M2 单问带选项 → 照旧一行选项原样
  {
    const io = memIo()
    const one = { questions: [{ id: 'q1', question: 'Open the batch red-clear ticket?', detail: 'evidence only', options: [{ label: 'Open ticket' }, { label: 'Not now' }], default_action: 'Open ticket' }], agent: { id: 's', cwd: '/repo' } }
    bridge.mirrorToLedger(io, env, 'sandbar', one, Date.now())
    const view = req.readRequests(io, env, 'sandbar')
    const qs = view.rows.filter(r => r.kind === 'question')
    C.case('M2-single-question-intact', qs.length === 1 && JSON.stringify(qs[0].options) === JSON.stringify(['Open ticket', 'Not now']),
      `rows=${qs.length} options=${JSON.stringify(qs[0] && qs[0].options)}`)
  }

  // M3 畸形 fail-closed：拒绝且点名字段，不落半行
  {
    const bad = (over) => { const r = TWO_Q(); Object.assign(r.questions[1], over); return r }
    const cases = [
      ['options-not-array', bad({ options: 'Restart now' }), /option/i],
      ['default-action-not-string', bad({ default_action: { act: 'x' } }), /default/i],
      ['expires-at-garbage', bad({ expires_at: 'next tuesday, maybe' }), /expire/i],
    ]
    for (const [name, reqBody, fieldRe] of cases) {
      const io = memIo()
      let refused = false, namesField = false
      try {
        const out = bridge.mirrorToLedger(io, env, 'sandbar', reqBody, Date.now())
        if (out && out.ok === false) { refused = true; namesField = fieldRe.test(String(out.error || '')) }
        else if (out === false || out === null) { refused = true }
      } catch (e) { refused = true; namesField = fieldRe.test(String(e && e.message)) }
      const view = req.readRequests(io, env, 'sandbar')
      const qs = view.rows.filter(r => r.kind === 'question')
      C.case('M3-failclosed-' + name, refused && qs.length === 0,
        `refused=${refused} rows=${qs.length} namesField=${namesField}`)
    }
  }

  // M4 无选项问题照旧自由文本路径
  {
    const io = memIo()
    const plain = { questions: [{ id: 'q1', question: 'Status check: is the host awake?' }], agent: { id: 's', cwd: '/repo' } }
    bridge.mirrorToLedger(io, env, 'sandbar', plain, Date.now())
    const view = req.readRequests(io, env, 'sandbar')
    const qs = view.rows.filter(r => r.kind === 'question')
    C.case('M4-no-options-free-text-path', qs.length === 1 && !qs[0].options && !view.malformed_rows,
      `rows=${qs.length} options=${JSON.stringify(qs[0] && qs[0].options)} malformed=${view.malformed_rows}`)
  }

  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e && e.stack || e).slice(0, 300)); C.exit() })
