// sc_ki193_writer_identity_and_audit_source.mjs — KI-193 回归②：写者身份不由调用方
// 自报 + 授权写留来源审计（灰盒 L3，harness 缝驱动生产路由面，离线零 docker 零浏览器，
// 红线零接触 3099）。
//
// Intent（用户可感知行为；KI-193 出路②③④ + 工单 requirement 2/3/4）：
//   治本前 `String(b.by ?? 'host')` 让调用方自报身份——账本里落 `by:"host"` 不构成
//   任何证据。治本后：
//   V1 带凭证应答一个请求时，body 里伪造 `by:"someone-else"` 不得改变账上的写者——
//      记录行写者=凭证证明的固定身份（host），且「声称 ≠ 记录」必须可见
//      （by_claimed/writer_mismatch 之类显式字段），绝不静默记账。
//   V2 授权写（grants master 全授）落盘后的声明 updated_by 同样不被 body `by` 支配。
//   V3 每条授权写审计行带来源面信息（panel-api/http 之类），后来的读者能分清
//      「宿主经面板操作」与任何其它来源——requirement 4。
//   V4 授权写走引擎判定：面板不再是声明文件的自由写入者；本离线场景锁其可观测面
//      （审计/声明回执带引擎侧判定产物），executor 身份被引擎 META_OP 反锁拒收的
//      注入面由引擎 pytest 覆盖（L1，developer 随票交付）。
//
// 断言锚公开 JSON 契约（HTTP 回执体），不锚盘上私有布局。
// 三态：缝缺席/新契约面未落地=FAIL exit 1 且点名（TDD 期红属预期）。
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'


const C = makeCase()
const PROJ = 'alpha'
const jpost = (base, url, body, headers = {}) => fetch(base + url, {
  method: 'POST',
  headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify(body),
}).then(async (r) => ({ status: r.status, body: await r.json().catch(() => null), text: (await r.text().catch(() => '')).slice(0, 200) }))

function consoleCookie(base) {
  const host = new URL(base).host
  const name = 'dsh-auth-' + Buffer.from(createHash('sha256').update(host).digest()).toString('base64url')
  return name + '=v1.AAAA.BBBB'
}

async function main() {
  const harness = await loadPanelHarness().catch((e) => { C.case('harness-loadable', false, String(e).slice(0, 200)); return null })
  if (!harness || typeof harness.startHarness !== 'function') {
    C.case('harness-loadable', false, 'server/plugins/executor-panel/harness.mjs 缺 startHarness（TDD 期红属预期）')
    return C.exit()
  }
  const iso = makeIsoDir('t261004-18-id-')
  const panelDir = join(iso.dir, 'panel')
  const H = await harness.startHarness({ panelDir, watchdogDir: join(iso.dir, 'watchdog'), workbenchStub: true })
  try {
    const cookie = () => ({ cookie: consoleCookie(H.base) })
    // 前置：项目有账本行、有守望者声明（用户旅程的宿主侧状态）。
    mkdirSync(join(panelDir, PROJ), { recursive: true })
    writeFileSync(join(panelDir, PROJ, 'requests.jsonl'), JSON.stringify({ type: 'request', id: 'r1', project: PROJ, kind: 'question', question: 'seed?', text: 'seed', at: 1 }) + '\n')
    await jpost(H.base, `/sandbar-executor-panel/api/settings?project=${PROJ}`, { op: 'save', config: { enabled: true } }, cookie())

    // V1 伪造 by 不改写者 + 不一致可见
    const a = await jpost(H.base, '/sandbar-executor-panel/api/requests/answer',
      { project: PROJ, id: 'r1', answer: 'host real answer', by: 'someone-else' }, cookie())
    const row = a.body && (a.body.answered || a.body.row)
    const recBy = row && (row.by ?? row.writer)
    const claimed = row && (row.by_claimed ?? row.claimed_by)
    const mismatch = row && (row.writer_mismatch ?? (claimed != null && claimed !== recBy))
    C.case('V1-forged-by-cannot-name-writer', a.status === 200 && recBy === 'host',
      `status=${a.status} recorded=${JSON.stringify(recBy)}`)
    C.case('V2-claim-mismatch-visible-not-silent', mismatch === true,
      `writer_mismatch=${JSON.stringify(mismatch)} by_claimed=${JSON.stringify(claimed)}`)

    // V3 授权写：updated_by 不被 body by 支配 + 审计带来源
    const g = await jpost(H.base, `/sandbar-executor-panel/api/grants?project=${PROJ}`,
      { op: 'master', enabled: true, by: 'executor-self-grant' }, cookie())
    const decl = g.body && g.body.declaration
    const updBy = decl && decl.updated_by
    C.case('V3-declaration-writer-not-caller-controlled', g.status === 200 && updBy === 'host',
      `status=${g.status} updated_by=${JSON.stringify(updBy)}`)
    // V4 审计账（<root>/<key>/executor-grants-audit.jsonl，公开审计契约面）里
    // 这条授权写带来源（source surface），后来的读者能分清宿主面板动作与其它来源
    // ——requirement 4 断言在审计账，不在 HTTP 回执（回执是给人看的，账是给后来读者的）。
    const auditFile = join(iso.dir, 'watchdog', PROJ, 'executor-grants-audit.jsonl')
    let auditRow = null
    try {
      const lines = readFileSync(auditFile, 'utf8').split('\n').filter((l) => l.trim() !== '')
      auditRow = JSON.parse(lines[lines.length - 1])
    } catch { /* absent → FAIL below names it */ }
    C.case('V4-authority-write-audit-names-source',
      !!auditRow && auditRow.source != null &&
        JSON.stringify(auditRow.source) !== '{}' && /surface|transport|panel|engine/.test(JSON.stringify(auditRow.source)),
      `audit=${auditFile} row=${JSON.stringify(auditRow).slice(0, 200)}`)

    // V5 授权面照常工作：master 写之后 grants GET 顶层 granted_ops 与写回执一致
    // （requirement 5——写的语义不因换通道而漂移；granted_ops=顶层去重授予清单，
    // grants.granted_count/granted_total 为同面的分子分母）。
    const gget = await fetch(H.base + `/sandbar-executor-panel/api/grants?project=${PROJ}`, { headers: cookie() })
    const gb = await gget.json().catch(() => null)
    const granted = gb && Array.isArray(gb.granted_ops) ? gb.granted_ops.length : null
    C.case('V5-panel-keeps-working-after-reroute', gget.status === 200 && granted === 6,
      `status=${gget.status} granted_ops=${JSON.stringify(gb && gb.granted_ops)}`)
  } finally {
    await H.close().catch(() => {})
  }
  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e).slice(0, 300)); C.exit() })
