// sc_t26100310_recent_actions_real_source.mjs — t261003-10「最近动作」真实读源契约
// （t261004-11 换源重写：读源=项目自己的执行器动作账 executor-actions.jsonl，
// 机器级 admin.log 读取随本票退役。灰盒 L2/L3，生产注册壳驱动，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；票面 Part 2 逐条 + 设计 §6「做了什么+凭哪条权限」红线）：
// 夹具一律引擎产出真行 verbatim 拷贝（手写 kind 行正是 t260929-07/260930 点名的缺陷族）。
//   A1 源缺席：面板不得冒充空列表；必须 ok:false + 新空态文案（「记录启动以来本项目
//      无执行器动作」）并点名项目账本文件路径。
//   A2 真行归因：引擎产出 schema-v1 真行 → 对应行呈现动作+票号+结果；refused 行带
//      reason（hover 用）、行带 acting session；夹具 fixtures/executor-actions-real.jsonl
//      是 executor_actions.record_executor_action 产出行的 verbatim 拷贝——缺该文件=FAIL。
//   A3 坏行纪律（外部输入三态钩子）：非 JSON / JSON 数组 / 标量 / decision 畸形 /
//      缺 idem / gaps 行混入 → 计数上报（malformed / unknown_op 族），合法行照常服务，
//      绝不编造动作。
//   A4 显式降级：源不可读（chmod 000）→ ok:false + 原因点名路径；ok:true+空 actions=红。
//   A5 只读红线：读出面绝不写源文件（读前后字节一致）。
//   A6 尾部半行：源文件末行截断半行 → 不崩、不冒充合法行（丢弃或计数皆可，显式）。
//   A7 上限 50：>50 行 → 恰 50 行 + older_rows>0 + note 指向项目账本文件。
//   A8 gaps 状态面：gaps 旁账非空 → gaps_recent>0（引擎落账失败可见，绝不静默）。
//
// 缝契约：harness.mjs startPluginHarness({ panelDir, executorActionsDir })（t261004-11
// 换缝：SANDBAR_EXECUTOR_ACTIONS_DIR 平铺目录，场景往里放 <project>.jsonl）。
// 三态：node 缺席=ENV_FAIL exit 2；闸内无 SKIP。
// intent 分工：路由可达性归 sc_t26100310_route_shell_parity。
import { readFileSync, writeFileSync, statSync, chmodSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { existsSync } from 'node:fs'
import { makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const FIX_REAL = new URL('../../server/plugins/executor-panel/tests/fixtures/executor-actions-real.jsonl', import.meta.url)
const PANEL_ROUTE = '/sandbar-executor-panel'
const PROJ = 'sandbar'

const C = makeCase()

async function jfetch(base, url) {
  const r = await fetch(base + url)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body }
}

async function main() {
  if (!existsSync(HARNESS_PATH)) {
    C.case('harness-present', false, 'server/plugins/executor-panel/harness.mjs 缺场')
    return C.exit()
  }
  const mod = await import('file://' + HARNESS_PATH).catch((e) => {
    C.case('harness-loadable', false, String(e).slice(0, 300)); return null
  })
  if (!mod) return C.exit()
  if (typeof mod.startPluginHarness !== 'function') {
    C.case('plugin-shell-seam-present', false, 'harness.mjs 缺 startPluginHarness（缝契约见头注）')
    return C.exit()
  }
  const api = PANEL_ROUTE + '/api/actions?project=' + PROJ
  if (!existsSync(fileURLToPath(FIX_REAL))) {
    C.case('real-rows-fixture-present', false,
      'executor-actions-real.jsonl 缺场（引擎产出真行 verbatim 拷贝；缺=FAIL 点名，不许手写合成顶替）')
    return C.exit()
  }
  const realRows = readFileSync(fileURLToPath(FIX_REAL), 'utf8')

  async function harnessWith(content, opts = {}) {
    const iso = makeIsoDir()
    const dir = join(iso.dir, 'ledger')
    mkdirSync(dir, { recursive: true })
    const ledger = join(dir, PROJ + '.jsonl')
    if (content !== null) writeFileSync(ledger, content)
    if (opts.gaps) writeFileSync(join(dir, 'executor-actions.gaps.jsonl'), opts.gaps)
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), executorActionsDir: dir })
    return { H, ledger }
  }

  // ---- A1 源缺席：新空态文案点名文件，绝不冒充空列表 ----
  {
    const { H } = await harnessWith(null)
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const okTrueEmpty = b.ok === true && Array.isArray(b.actions) && b.actions.length === 0
      const reason = String(b.reason || b.error || '')
      C.case('A1-absent-source-new-empty-copy',
        !okTrueEmpty && b.ok === false && reason.includes('no recorded executor action')
          && reason.includes(PROJ + '.jsonl'),
        'ok=' + b.ok + ' reason=' + reason.slice(0, 160))
    } finally { await H.close() }
  }

  // ---- A2 真行归因（引擎产出行 verbatim 拷贝）----
  {
    const { H, ledger } = await harnessWith(realRows)
    try {
      const before = statSync(ledger).size + ':' + readFileSync(ledger, 'utf8').length
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const rows = Array.isArray(b.actions) ? b.actions : []
      const refused = rows.filter((x) => x && x.result === 'refused')
      C.case('A2-real-rows-attribution',
        b.ok === true && rows.length === 4 && rows.every((x) => x.action && x.at !== undefined)
          && rows.every((x) => typeof x.session === 'string')
          && rows.some((x) => x.permission && x.ticket),
        'rows=' + rows.length + ' sample=' + (rows[0] ? JSON.stringify(rows[0]).slice(0, 160) : ''))
      C.case('A2b-refused-rows-carry-reason',
        refused.length >= 1 && refused.every((x) => typeof x.reason === 'string' && x.reason !== ''),
        'refused=' + refused.length)
      C.case('A5-readonly-real', before === statSync(ledger).size + ':' + readFileSync(ledger, 'utf8').length,
        'project ledger bytes unchanged by reads')
    } finally { await H.close() }
  }

  // ---- A3 坏行纪律（真行 + 注入畸形行；畸形行=外部输入用例）----
  {
    const real0 = realRows.trim().split('\n')[0]
    const lines = [
      real0,
      'this line is not json',
      JSON.stringify(['a', 'json', 'array']),
      JSON.stringify('a json scalar'),
      JSON.stringify({ v: 1, at: 1, op: 'sign', decision: 'maybe', idem: 'x' }),
      JSON.stringify({ v: 1, at: 1, op: 'sign', decision: 'allowed' }),
      JSON.stringify({ gap: true, at: 1, project: PROJ, why: 'foreign row' }),
    ]
    const content = lines.join('\n') + '\n'
    const { H, ledger } = await harnessWith(content)
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const counted = (b.malformed_rows ?? 0) + (b.unknown_op_rows ?? 0) + (b.deduped_rows ?? 0)
      C.case('A3-malformed-counted-not-silent',
        b.ok === true && counted >= 4 && Array.isArray(b.actions) && b.actions.length >= 1,
        'counters=' + JSON.stringify({ malformed: b.malformed_rows, unknown_op: b.unknown_op_rows, deduped: b.deduped_rows })
        + ' actions=' + (b.actions || []).length)
      C.case('A5-readonly-mixed', statSync(ledger).size === content.length,
        'project ledger bytes unchanged by reads')
    } finally { await H.close() }
  }

  // ---- A4 源不可读：ok:false + 原因点名路径 ----
  {
    const iso = makeIsoDir()
    const dir = join(iso.dir, 'ledger')
    mkdirSync(dir, { recursive: true })
    const src = join(dir, PROJ + '.jsonl')
    writeFileSync(src, realRows)
    chmodSync(src, 0o000)
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), executorActionsDir: dir })
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const reason = String(b.reason || b.error || '')
      C.case('A4-unreadable-source-degrades', b.ok === false && reason.includes(PROJ + '.jsonl'),
        'ok=' + b.ok + ' reason=' + reason.slice(0, 160) + '（root 无权限差异由执行环境定，非 root 下必红）')
    } finally { await H.close() }
  }

  // ---- A6 尾部半行 ----
  {
    const { H } = await harnessWith(realRows.trim() + '\n{"v": 1, "at": 17909845, "op": "trunc')
    try {
      const r = await jfetch(H.base, api)
      C.case('A6-tail-partial-line-no-crash', r.status === 200 && r.body !== null,
        'status=' + r.status + '（不崩、不冒充合法行；丢弃或计数皆可）')
    } finally { await H.close() }
  }

  // ---- A7 上限 50 + 指针 ----
  {
    let many = ''
    for (let i = 0; i < 55; i++) {
      many += JSON.stringify({ v: 1, at: 1791000000000 + i, op: 'sign', ticket: 'T-' + i,
        grant: 'sign', decision: 'allowed', session: 's', channel: 'cwd', idem: 'id' + i }) + '\n'
    }
    const { H, ledger } = await harnessWith(many)
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      C.case('A7-cap-50-with-pointer',
        b.ok === true && b.actions.length === 50 && b.older_rows === 5
          && typeof b.note === 'string' && b.note.includes(ledger),
        'shown=' + b.actions.length + ' older=' + b.older_rows + ' note=' + String(b.note || '').slice(0, 120))
    } finally { await H.close() }
  }

  // ---- A8 gaps 状态面 ----
  {
    const gaps = '{"gap":true,"at":1,"project":"' + PROJ + '","why":"append failed"}\n'
    const { H } = await harnessWith(realRows, { gaps })
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      C.case('A8-gaps-surface-visible',
        b.ok === true && b.gaps_recent === 1 && typeof b.gaps_file === 'string'
          && b.gaps_file.includes('executor-actions.gaps.jsonl'),
        'gaps_recent=' + b.gaps_recent + ' gaps_file=' + String(b.gaps_file || ''))
    } finally { await H.close() }
  }

  C.exit()
}

main().catch((e) => { console.error('FATAL', e); process.exit(1) })
