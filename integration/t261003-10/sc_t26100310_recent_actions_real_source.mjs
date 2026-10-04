// sc_t26100310_recent_actions_real_source.mjs — t261003-10「最近动作」真实读源契约
// （灰盒 L2/L3，生产注册壳驱动，离线零 docker 零浏览器）。
//
// Intent（用户可感知行为；设计 note §6「做了什么+凭哪条权限」红线 + 工单 Finding 2 /
// Required outcome 1/4/5）：Overview 的 Recent actions 必须来自**真实携带该信息的
// 读源**（裁定=admin.log 审计行；授权键在 summary 解析后对象顶层——gen5 实测裁定，无需引擎改动），
// 夹具一律真实行 verbatim 拷贝（手写 kind 行正是本票点名的缺陷族 t260929-07 / 260930）。
//   A1 中间态诚实（引擎补写落地前）：只有现行形状真实审计行（无顶层 executor_grant_op）
//      → 面板**不得**呈 ok:true + 空 actions 冒充「最近没动作」；必须显式降级，
//      原因点名「源尚不逐动作记录授权（引擎补写未落地）」并点名解析出的源路径。
//   A2 补写后归因：含**顶层 executor_grant_op** 的真实引擎产出行 → 对应行呈现
//      动作+票号+权限（permission=executor_grant_op，词表与 grants 面同族）；夹具
//      文件 fixtures/admin-log-post-widening-line.jsonl 必须是引擎 pytest 产出行的
//      verbatim 拷贝——**缺该文件=FAIL 点名**（不许手写合成顶替，review gen1 附条件1）。
//   A3 坏行纪律（工单外部输入三态钩子）：非 JSON 行 / JSON 数组 / JSON 标量 /
//      caller_project 不匹配 / executor_grant_op 为空 → 计数上报（malformed /
//      missing_authorization / unmapped 族），合法行照常服务，绝不编造动作。
//   A4 显式降级：源文件缺席（SANDBAR_ADMIN_LOG 指向不存在路径）与不可读（chmod 000）
//      → ok:false + 人类可读原因点名路径；ok:true+空 actions=红（设计 §6）。
//   A5 只读红线：读出面绝不写源文件（读前后字节一致）。
//   A6 尾部半行：源文件末行截断半行 → 不崩、不冒充合法行（丢弃或计数皆可，显式）。
//
// 缝契约：harness.mjs startPluginHarness({ panelDir, adminLogPath })（场景 A 同缝；
// 缺=FAIL 点名）。三态：node 缺席=ENV_FAIL exit 2；闸内无 SKIP。
// intent 分工：路由可达性归 sc_t26100310_route_shell_parity；t261003-06 旧
// recent-actions 场景的 R 面随本票由 developer 按 gen1 方案 Step 3 改造到新读源
// （其 R1–R5 intent 由本场景 A 面承接，避免 intent 级重复）。
import { readFileSync, writeFileSync, statSync, chmodSync, copyFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { existsSync } from 'node:fs'
import { makeIsoDir, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const FIX_CUR = new URL('./fixtures/admin-log-real-current-shape.jsonl', import.meta.url)
const FIX_POST = new URL('./fixtures/admin-log-post-widening-line.jsonl', import.meta.url)
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

  // ---- A1 中间态诚实（现行形状真实行）----
  {
    const iso = makeIsoDir()
    const src = join(iso.dir, 'admin.log')
    copyFileSync(fileURLToPath(FIX_CUR), src)
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), adminLogPath: src })
    try {
      const before = statSync(src).size + ':' + readFileSync(src, 'utf8').length
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const okTrueEmpty = b.ok === true && Array.isArray(b.actions) && b.actions.length === 0
      if (okTrueEmpty) {
        C.case('A1-interim-no-empty-posing', false,
          '现行形状真实行（无授权字段）下返回 ok:true+空 actions——空列表冒充「最近没动作」（设计 §6 红线）')
      } else if (b.ok === false || b.degraded === true) {
        const reason = String(b.reason || b.error || '')
        C.case('A1-interim-no-empty-posing', /authorization|permission|授权|权限/i.test(reason) && reason.length > 5,
          'ok:false/degraded，原因=' + reason.slice(0, 160))
      } else {
        // 补写已落地且解析器把现行行计为 missing_authorization 仍服务其余面：只要不空 posing 即过
        C.case('A1-interim-no-empty-posing', true, 'status=' + r.status + '（非空冒充形态；计数面归 A3）')
      }
      const after = statSync(src).size + ':' + readFileSync(src, 'utf8').length
      C.case('A5-readonly-current', before === after, 'bytes ' + before + ' -> ' + after)
    } finally { await H.close() }
  }

  // ---- A2 归因（状态条件双面，闸内无 SKIP）----
  // 补写未落地（夹具缺场）=锁**中间态诚实契约**（ok:false + 原因点名「源尚不逐动作
  // 记录授权」+ 点名源路径）；夹具在场（引擎 pytest 产出行 verbatim 拷贝落位）=锁
  // 归因面（动作+票号+权限行 + 计数器显式）。两面均为 PASS/FAIL 判定，不许手写合成
  // 夹具顶替引擎产出行（review gen1 附条件1）。
  {
    const havePost = existsSync(fileURLToPath(FIX_POST))
    const iso = makeIsoDir()
    const src = join(iso.dir, 'admin.log')
    copyFileSync(fileURLToPath(havePost ? FIX_POST : FIX_CUR), src)
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), adminLogPath: src })
    try {
      const before = statSync(src).size + ':' + readFileSync(src, 'utf8').length
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const after = statSync(src).size + ':' + readFileSync(src, 'utf8').length
      C.case('A5-readonly-' + (havePost ? 'post' : 'interim'), before === after, 'bytes ' + before + ' -> ' + after)
      if (havePost) {
        const rows = Array.isArray(b.actions) ? b.actions : []
        const withPerm = rows.filter((x) => x && x.permission)
        C.case('A2-post-widening-attribution', b.ok === true && withPerm.length >= 1 && rows.every((x) => x.ticket && x.action && x.at),
          'rows=' + rows.length + ' with-permission=' + withPerm.length +
          (withPerm[0] ? ' sample=' + JSON.stringify(withPerm[0]).slice(0, 160) : ''))
        C.case('A2-post-widening-counters-visible', typeof b.malformed_rows === 'number' && typeof b.missing_authorization_rows === 'number',
          'counters=' + JSON.stringify({ malformed: b.malformed_rows, unmapped: b.unmapped_rows, missing_auth: b.missing_authorization_rows }))
      } else {
        const reason = String(b.reason || b.error || '')
        C.case('A2-interim-honest-pending-emission',
          b.ok === false && /permission|authorization|executor_grant_op|授权|权限/i.test(reason)
            && /admin\.log/.test(String(b.source ?? '') + reason),
          '[fixture admin-log-post-widening-line.jsonl 落位时应走归因面；此消息出现=夹具缺场，回锁中间态诚实面（真行 verbatim 拷贝纪律不变）] ok=' + b.ok +
          ' reason=' + reason.slice(0, 160))
      }
    } finally { await H.close() }
  }

  // ---- A3 坏行纪律（真实行 + 注入畸形行；畸形行本身是外部输入用例，非读源形状）----
  {
    const iso = makeIsoDir()
    const src = join(iso.dir, 'admin.log')
    const real = readFileSync(fileURLToPath(FIX_CUR), 'utf8').trim().split('\n')
    const lines = [
      real[0],
      'this line is not json',
      JSON.stringify(['a', 'json', 'array']),
      JSON.stringify('a json scalar'),
      JSON.stringify({ ts: 1790984509, call_id: 'x', source: 'ticket', sub: 'ticket', ok: true, caller_project: 'other-project', summary: '{}' }),
      real[1] ?? real[0],
      JSON.stringify({ ts: 1790984509, call_id: 'y', source: 'ticket', sub: 'ticket', ok: true, caller_project: PROJ, executor_grant_op: '', summary: '{}' }),
    ]
    writeFileSync(src, lines.join('\n') + '\n')
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), adminLogPath: src })
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const counters = JSON.stringify({ malformed: b.malformed_rows, missing_auth: b.missing_authorization_rows, unmapped: b.unmapped_rows })
      const counted = (b.malformed_rows ?? 0) + (b.missing_authorization_rows ?? 0) + (b.unmapped_rows ?? 0)
      const reason = String(b.reason || b.error || '')
      // 状态条件双面（同 A2，闸内无 SKIP）：ok:true（补写面）=坏行计数必须显式上报
      // （not-json/array/scalar 三条至少各计一笔，不静默丢、不编造动作）；ok:false
      // （中间态降级面，响应无计数器字段）=原因必须点名补写未落地的授权缺口——
      // 计数显式面由 A2-post-widening-counters-visible 在补写落位后强制。
      const isInterimDegraded = b.ok === false && /permission|authorization|executor_grant_op|授权|权限/i.test(reason)
      C.case('A3-malformed-counted-not-silent',
        (b.ok === true && counted >= 3) || isInterimDegraded,
        'counters=' + counters + ' ok=' + b.ok + ' reason=' + reason.slice(0, 120) +
        '（ok:true 面要求 counted>=3；中间态降级面要求原因点名授权缺口）')
    } finally { await H.close() }
  }

  // ---- A4 显式降级：缺席 + 不可读 ----
  {
    const iso = makeIsoDir()
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), adminLogPath: join(iso.dir, 'no-such-admin.log') })
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const reason = String(b.reason || b.error || '')
      C.case('A4-absent-source-degrades', b.ok === false && /admin\.log|no-such-admin\.log/.test(reason),
        'ok=' + b.ok + ' reason=' + reason.slice(0, 160))
    } finally { await H.close() }
  }
  {
    const iso = makeIsoDir()
    const src = join(iso.dir, 'admin.log')
    writeFileSync(src, readFileSync(fileURLToPath(FIX_CUR), 'utf8'))
    chmodSync(src, 0o000)
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), adminLogPath: src })
    try {
      const r = await jfetch(H.base, api)
      const b = r.body || {}
      const reason = String(b.reason || b.error || '')
      C.case('A4-unreadable-source-degrades', b.ok === false && reason.length > 5,
        'ok=' + b.ok + ' reason=' + reason.slice(0, 160) + '（root 无权限差异由执行环境定，非 root 下必红）')
    } finally { await H.close() }
  }

  // ---- A6 尾部半行 ----
  {
    const iso = makeIsoDir()
    const src = join(iso.dir, 'admin.log')
    const real = readFileSync(fileURLToPath(FIX_CUR), 'utf8').trim()
    writeFileSync(src, real + '\n{"ts": 17909845, "call_id": "trunc') // 末行截断
    const H = await mod.startPluginHarness({ panelDir: join(iso.dir, 'panel'), adminLogPath: src })
    try {
      const r = await jfetch(H.base, api)
      C.case('A6-tail-partial-line-no-crash', r.status === 200 && r.body !== null,
        'status=' + r.status + '（不崩、不冒充合法行；丢弃或计数皆可）')
    } finally { await H.close() }
  }

  C.exit()
}

main().catch((e) => { console.error('FATAL', e); process.exit(1) })
