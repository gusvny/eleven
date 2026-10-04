// sc_executor_panel_requests_options.mjs — t261003-06 请求选项数据面（灰盒 L2/L3，
// harness 缝驱动真实路由面，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；设计 note §3「有选项的请求给按钮，不让人打字」+ §6 选项
// 数据面）：宿主收到的请求若带选项，回答就是点选而不是打字；这要求提出方在请求里
// 一并给出选项，面板照实呈现、不发明、不吞。
//   O1 带选项的请求经 append 面写入 → 读出行原样带选项（顺序保持）。
//   O2 选项规整：去重、每项去空白、上限（>8 拒收或截断到 ≤8——设计定上限 8，两种
//      处置都可接受，但绝不允许脏值原样入库）。
//   O3 畸形输入 fail-closed：非数组 / 含空串 / 含非字符串 / 全空数组拒绝在 append
//      面（4xx），台账不落半行；坏行不冒充无选项请求。
//   O4 无选项请求照旧自由文本路径（append 不带 options → 读出无 options 且不报错）。
//   O5 选项行的答复面照常工作（按 id 闭行），选项行不允许第二次答复（既有审计链
//      不变量在本数据面上的投影）。
// intent 分工：append-only/答复闭行不删原行/缝重启存活归 t260929-03-executor-panel-api
// R1–R3；本条只锁「选项」这一新增数据面。
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { loadPanelHarness, makeIsoDir, makeCase } from './lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'

async function jfetch(base, url, opts) {
  const r = await fetch(base + url, opts)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body }
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs 缺 startHarness（缝契约见 lib_panel_seam.mjs 头注；TDD 期红属预期）')
    return C.exit()
  }
  const iso = makeIsoDir()
  const H = await harness.startHarness({ panelDir: join(iso.dir, 'panel'), watchdogDir: join(iso.dir, 'watchdog') })
  try {
    const reqApi = '/sandbar-executor-panel/api/requests'

// t261004-18 (KI-193): panel writes require the console session credential;
// fixtures present the same-shaped cookie the console browser carries.
function consoleCookie(base) {
  return 'dsh-auth-' + Buffer.from(createHash('sha256').update(new URL(base).host).digest()).toString('base64url') + '=v1.AAAA.BBBB'
}
    const post = (body, url = reqApi) => jfetch(H.base, url, { method: 'POST', headers: { 'content-type': 'application/json', cookie: consoleCookie(H.base) }, body: JSON.stringify(body) })
    const read = async () => jfetch(H.base, reqApi + '?project=' + PROJ)

    // O1 带选项写入 → 原样读出
    const opts = ['Open a new ticket', 'Extend the current ticket', 'Stop and ask the host']
    const w1 = await post({ project: PROJ, kind: 'decision', question: 'How should the executor proceed?', detail: 'two viable paths', raised_by: 'bench', default_action: 'Open a new ticket', options: opts })
    const r1 = await read()
    const rows1 = (r1.body && (r1.body.rows || r1.body.requests)) || []
    const mine = rows1.find(x => x && x.options && Array.isArray(x.options) && x.options.length === 3)
    C.case('O1-options-roundtrip', w1.status < 300 && !!mine,
      `append=${w1.status} rows=${rows1.length} options-row=${!!mine}`)

    // O2 规整：重复项去重；超上限处置可见
    const dup = await post({ project: PROJ, kind: 'decision', question: 'Pick one', raised_by: 'bench', default_action: 'A', options: [' A ', 'A', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I'] })
    const r2 = await read()
    const rows2 = (r2.body && (r2.body.rows || r2.body.requests)) || []
    const dupRow = rows2[rows2.length - 1]
    const okShape = dup.status >= 400 || (dupRow.options && dupRow.options.length <= 8 && new Set(dupRow.options).size === dupRow.options.length)
    C.case('O2-options-normalized-dedup-capped', okShape,
      `append=${dup.status} last-row-options=${JSON.stringify(dupRow && dupRow.options)}`)

    // O3 畸形 fail-closed
    const bads = [
      { options: 'Open a ticket' },
      { options: ['ok', ''] },
      { options: [1, 2] },
      { options: [] },
    ]
    let all4xx = true
    for (const b of bads) {
      const r = await post({ project: PROJ, kind: 'decision', question: 'bad', raised_by: 'bench', default_action: 'x', ...b })
      if (!(r.status >= 400 && r.status < 500)) { all4xx = false; console.log('  bad-payload not rejected:', JSON.stringify(b), r.status) }
    }
    const r3 = await read()
    const cnt3 = ((r3.body && (r3.body.rows || r3.body.requests)) || []).length
    C.case('O3-malformed-options-fail-closed', all4xx && cnt3 <= 2,
      `bad-payloads-all-4xx=${all4xx} rows-after=${cnt3}（>2=坏行落库）`)

    // O4 无选项照旧自由文本
    const w4 = await post({ project: PROJ, kind: 'question', question: 'Free text question?', raised_by: 'bench', default_action: 'wait' })
    const r4 = await read()
    const rows4 = (r4.body && (r4.body.rows || r4.body.requests)) || []
    const free = rows4.find(x => x && x.question === 'Free text question?')
    C.case('O4-no-options-free-text-path', w4.status < 300 && free && !Array.isArray(free.options),
      `append=${w4.status} free-row=${!!free} options=${JSON.stringify(free && free.options)}`)

    // O5 选项行答复照常；二次答复拒收
    const target = mine || rows4.find(x => x && x.id) || null
    if (!target) {
      C.case('O5-options-row-answer-once', false, 'no readable row to answer — O1/O4 both failed')
    } else {
      const a1 = await post({ project: PROJ, id: target.id, answer: 'Open a new ticket', by: 'host' }, '/sandbar-executor-panel/api/requests/answer')
      const a2 = await post({ project: PROJ, id: target.id, answer: 'second', by: 'host' }, '/sandbar-executor-panel/api/requests/answer')
      C.case('O5-options-row-answer-once', a1.status < 300 && a2.status >= 400,
        `target=${target.id} first=${a1.status} second=${a2.status}`)
    }
  } finally {
    await H.close()
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: 场景自身异常 —', String(e).slice(0, 300)); process.exit(2) })
