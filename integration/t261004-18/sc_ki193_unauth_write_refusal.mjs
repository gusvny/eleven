// sc_ki193_unauth_write_refusal.mjs — KI-193 回归①：面板写端点无凭证必须拒收且零落盘
// （灰盒 L3，harness 缝驱动生产路由面，离线零 docker 零浏览器，红线零接触 3099）。
//
// Intent（用户可感知行为；KI-193 出路① + 工单 requirement 1）：
//   控制台首页的 token 闸（dsh 侧，仓外）不覆盖插件路由——这是工单病灶。治本后，
//   面板自身的每一个写端点（requests append / answer / settings save|revoke|sleep /
//   grants master|save）在请求不带任何凭证时必须回 401 或 403，且账本与授权声明
//   文件一个字节都不变。零凭证直连写端点=今天一条 curl 就能自授六项操作的洞，
//   本场景锁死回归。
//
// 断言锚定公开契约（HTTP 状态 + 盘上字节），不锚实现：拒绝态=401/403；
// 「写没发生」=账本与声明文件的字节哈希写前写后一致。
//
// 三态：harness 缝缺席=FAIL exit 1 且点名（TDD 期红属预期，arbitrate/merge 必须绿）；
// node 缺席=ENV_FAIL exit 2。
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const sha = (p) => existsSync(p) ? createHash('sha256').update(readFileSync(p)).digest('hex') : 'absent'
const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, text: (await r.text()).slice(0, 200) }))

// console root 同款凭证（dsh 浏览器会话 cookie 的名字与形状；灰盒机制理解，
// 断言落在行为上：带它=放行，不带=拒收）。
function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + Buffer.from(createHash('sha256').update(host).digest()).toString('base64url')
  return name + '=v1.AAAA.BBBB'
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs 缺 startHarness（缝契约见 lib_panel_seam.mjs 头注；TDD 期红属预期）')
    return C.exit()
  }
  const iso = makeIsoDir('t261004-18-')
  const panelDir = join(iso.dir, 'panel')
  const H = await harness.startHarness({ panelDir, watchdogDir: join(iso.dir, 'watchdog'), workbenchStub: true })
  try {
    // 前置（用户旅程）：项目已有账本行与已保存的授权声明——拒收面必须「零落盘」，
    // 先给盘上有状态可对照。
    const ledgerPath = join(panelDir, PROJ, 'requests.jsonl')
    mkdirSync(join(panelDir, PROJ), { recursive: true })
    writeFileSync(ledgerPath, JSON.stringify({ type: 'request', id: 'r1', project: PROJ, kind: 'question', question: 'seed?', text: 'seed', at: 1 }) + '\n')
    await jpost(H.base, `/sandbar-executor-panel/api/settings?project=${PROJ}`,
      { op: 'save', config: { enabled: true } })
    await jpost(H.base, `/sandbar-executor-panel/api/grants?project=${PROJ}`,
      { op: 'save', grants: { sign: true } })
    const before = { ledger: sha(ledgerPath), decl: sha(join(panelDir, 'grants', PROJ, 'grants-declaration.json')) }

    // ---- W 族：每个写端点零凭证 POST → 401/403 ----
    const writes = [
      ['W1-requests-append', '/sandbar-executor-panel/api/requests', { project: PROJ, text: 'x' }],
      ['W2-requests-answer', '/sandbar-executor-panel/api/requests/answer', { project: PROJ, id: 'r1', answer: 'forged', by: 'host' }],
      ['W3-settings-save', `/sandbar-executor-panel/api/settings?project=${PROJ}`, { op: 'save', config: { enabled: false } }],
      ['W4-settings-revoke', `/sandbar-executor-panel/api/settings?project=${PROJ}`, { op: 'revoke' }],
      ['W5-settings-sleep', `/sandbar-executor-panel/api/settings?project=${PROJ}`, { op: 'sleep', policy: 'off', until: 9999999999999 }],
      ['W6-grants-master-grant-all', `/sandbar-executor-panel/api/grants?project=${PROJ}`, { op: 'master', enabled: true, by: 'host' }],
      ['W7-grants-master-clear', `/sandbar-executor-panel/api/grants?project=${PROJ}`, { op: 'master', enabled: false }],
      ['W8-grants-save', `/sandbar-executor-panel/api/grants?project=${PROJ}`, { op: 'save', grants: { open: true } }],
    ]
    for (const [name, url, body] of writes) {
      const r = await jpost(H.base, url, body)
      C.case(name, r.status === 401 || r.status === 403, `status=${r.status}（工单病灶：治本前此端点零凭证直通 200）`)
    }

    // W9 畸形体也不放行：身份闸先于语法闸——无凭证 + 坏 JSON → 401/403，绝不 400 后照写。
    const bad = await fetch(H.base + '/sandbar-executor-panel/api/requests/answer', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{not-json',
    })
    C.case('W9-malformed-body-no-credential-refused', bad.status === 401 || bad.status === 403, `status=${bad.status}`)

    // W10 零落盘硬保证：上面全部拒收之后，账本与声明文件字节不变。
    const after = { ledger: sha(ledgerPath), decl: sha(join(panelDir, 'grants', PROJ, 'grants-declaration.json')) }
    C.case('W10-zero-bytes-written-on-refusal', before.ledger === after.ledger && before.decl === after.decl,
      `ledger ${before.ledger === after.ledger ? 'unchanged' : 'CHANGED'} decl ${before.decl === after.decl ? 'unchanged' : 'CHANGED'}`)

    // ---- R 族：读面保持开放（页面要能加载、宿主旅程不破，工单 requirement 5）----
    const g1 = await fetch(H.base + `/sandbar-executor-panel/api/requests?project=${PROJ}`)
    const g2 = await fetch(H.base + `/sandbar-executor-panel/api/grants?project=${PROJ}`)
    C.case('R1-get-requests-still-open', g1.status === 200, `status=${g1.status}`)
    C.case('R2-get-grants-still-open', g2.status === 200, `status=${g2.status}`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 300)); C.exit() })
