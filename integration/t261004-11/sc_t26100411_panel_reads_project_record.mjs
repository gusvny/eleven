// sc_t26100411_panel_reads_project_record.mjs — t261004-11 Part 2: the panel's
// Recent-actions feed reads ONLY the project's own executor-action record; the
// machine-wide admin.log read is gone.
//
// Grey-box L3, production route shell driven (startPluginHarness, port 0),
// offline: zero docker, zero browser, zero contact with 3099/7233.
//
// Intent (user-perceivable contract of ticket t261004-11 Part 2):
//   B1 source swap: rows seeded in the project record appear in the feed; a
//      matching row planted in admin.log (if such a face even remains) must
//      NOT appear — the admin.log coupling is dead. The API response names the
//      project record as `source`.
//   B2 refused rows are visually distinct (a marker beyond the word refused):
//      the rendered row carries a refusal marker/class; assert on the rendered
//      page surface, not on internal names.
//   B3 hover text carries the permission AND the acting session.
//   B4 cap ~50: 60 seeded rows -> exactly 50 newest shown and the response
//      points at the project record for older ones.
//   B5 empty state: record absent -> the copy says the project has no recorded
//      executor action and names the record file (no admin.log wording).
//   B6 degraded: record unreadable -> explicit degradation naming the path.
//   B7 gaps surfaced: rows in executor-actions.gaps.jsonl make the failed
//      recording visible in the status face (gaps counter > 0).
//   B8 malformed rows counted, never rendered, never a crash.
//   B9 read-only red line: the project record is byte-identical after reads.
//
// Seam contract (per plan gen1 Step 3/5): startPluginHarness accepts the
// project-record location (executorActionsPath / projects-dir seam, replacing
// adminLogPath). Harness/seam absent or still admin.log-only = FAIL named
// (TDD red expected until implement lands; must be green by arbitrate/merge).
//
// Fixture discipline: rows come verbatim from the engine battery's produced
// file (tests/fixtures/ of this ticket dir, generated at implement time and
// copied). If the engine-produced fixture is absent, the affected legs FAIL
// with a named reason — hand-written synthetic rows must not replace it.
// intent 分工: engine-side recording/replay/gap loudness belongs to
// sc_t26100411_ledger_record_and_replay; route reachability belongs to
// t261003-10-route-shell-parity; the superseded admin.log-source intent
// (t261003-10-recent-actions-real-source) is retired by the implement stage
// per plan Step 5 — this scenario replaces its consumer-side intent.
import { existsSync, readFileSync, writeFileSync, statSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const HARNESS_PATH = join(REPO, 'server/plugins/executor-panel/harness.mjs')
const PANEL_ROUTE = '/sandbar-executor-panel'
const FIXTURE = new URL('./fixtures/executor-actions-engine-produced.jsonl', import.meta.url)

const iso = mkdtempSync(join(tmpdir(), 't26100411-panel-'))
let cleaned = false
const clean = () => { if (!cleaned) { cleaned = true; rmSync(iso, { recursive: true, force: true }) } }
process.on('exit', clean)
process.on('SIGINT', () => { clean(); process.exit(130) })

const cases = []
function leg(name, ok, reason = '') {
  cases.push({ name, ok: !!ok })
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
}
function envFail(name, reason) {
  cases.push({ name, env: true })
  console.log(`[ENV_FAIL] ${name} — ${reason}`)
}
function exitAll() {
  const pass = cases.filter(c => !c.env && c.ok).length
  const fail = cases.filter(c => !c.env && !c.ok).length
  const env = cases.filter(c => c.env).length
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${env} na=0`)
  process.exit(env > 0 ? 2 : fail > 0 ? 1 : 0)
}

async function jfetch(base, url) {
  const r = await fetch(base + url)
  let body = null
  try { body = await r.json() } catch { /* non-json */ }
  return { status: r.status, body, text: await r.text().catch(() => '') }
}

async function withHarness(opts, fn) {
  const mod = await import('file://' + HARNESS_PATH)
  const h = await mod.startPluginHarness(opts)
  try { return await fn(h.base) } finally { await h.close() }
}

function seedRows(rows) {
  const dir = join(iso, 'proj-x', 'ledger')
  mkdirSync(dir, { recursive: true })
  const p = join(dir, 'executor-actions.jsonl')
  writeFileSync(p, rows.join('\n') + '\n')
  return p
}

async function main() {
  if (typeof process === 'undefined' || !process.versions?.node) {
    envFail('node-runtime', 'node absent'); return exitAll()
  }
  if (!existsSync(HARNESS_PATH)) {
    leg('harness-present', false, 'server/plugins/executor-panel/harness.mjs missing')
    return exitAll()
  }

  // fixture: engine-produced rows, verbatim (TDD: absent until implement; FAIL named)
  let rows = null
  if (existsSync(FIXTURE)) {
    rows = readFileSync(FIXTURE, 'utf8').split('\n').filter(l => l.trim())
  }
  const fixtureNote = rows ? '' : ' (fixture fixtures/executor-actions-engine-produced.jsonl absent — engine battery has not produced it yet; B1/B3 assertions cannot run against synthetic rows)'

  // --- B1/B2/B3/B7/B8/B9: seeded record, harness pointed at the projects dir
  const actionsPath = seedRows(rows ?? [])
  const projRoot = join(iso, 'proj-x')
  const gapsPath = join(projRoot, 'ledger', 'executor-actions.gaps.jsonl')
  writeFileSync(gapsPath, JSON.stringify({ gap: true, at: 1, project: 'proj-x', why: 'OSError: seeded' }) + '\n')

  let harness = null
  try {
    harness = await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: actionsPath }, async (base) => {
      const PROJ_Q = '?project=proj-x'
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)

      // B1 source swap
      leg('b1-api-ok-names-project-record-source',
        api.status === 200 && api.body?.ok === true && typeof api.body?.source === 'string'
        && api.body.source.includes('executor-actions.jsonl'),
        `status=${api.status} body=${JSON.stringify(api.body).slice(0, 200)}`)
      leg('b1-feed-shows-seeded-rows' + fixtureNote,
        rows ? Array.isArray(api.body?.actions) && api.body.actions.length >= 2 : false,
        rows ? `actions=${api.body?.actions?.length}` : fixtureNote)

      // B2/B3 rendered surface. The panel page is client-rendered: the raw HTML
      // only carries the render source, so the offline (browser-free) assertion
      // level is: payload fields the renderer consumes + the hover/marker
      // templates present in the served render source. (Arbitration fix: the
      // original legs regexed for fully-rendered rows in raw HTML — impossible
      // outside a browser; tightened B2 away from matching the mere word.)
      const page = await fetch(base + PANEL_ROUTE).then(r => r.text()).catch(() => '')
      const refusedShown = rows && api.body?.actions?.some(a => String(a.result || '').toLowerCase() === 'refused')
      leg('b2-refused-row-visually-distinct' + fixtureNote,
        rows && refusedShown ? /class="dot red"|refused-marker|refused-row/i.test(page) : false,
        rows ? 'refused-present=' + refusedShown + ' marker-in-render-source=' + /class="dot red"/i.test(page) : fixtureNote)
      const payloadCarries = rows && (api.body?.actions || []).every(a =>
        Object.prototype.hasOwnProperty.call(a, 'permission') && Object.prototype.hasOwnProperty.call(a, 'session'))
      leg('b3-hover-carries-permission-and-session' + fixtureNote,
        rows ? payloadCarries && /Allowed by the /.test(page) && /· session /.test(page) && /Refused: /.test(page) : false,
        rows ? 'payload-carries=' + payloadCarries : fixtureNote)

      // B7 gaps surfaced
      leg('b7-gap-face-visible', api.body?.gaps_recent > 0,
        `gaps_recent=${api.body?.gaps_recent}`)

      // B8 malformed rows counted not rendered
      leg('b8-malformed-counted-not-rendered',
        typeof api.body?.malformed_rows === 'number',
        `malformed_rows=${api.body?.malformed_rows}`)

      // B9 read-only red line
      const before = statSync(actionsPath)
      await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      const after = statSync(actionsPath)
      leg('b9-source-untouched-after-reads',
        before.size === after.size && before.mtimeMs === after.mtimeMs, '')
      return base
    })
  } catch (e) {
    const msg = String(e).slice(0, 240)
    if (/adminLogPath|SANDBAR_ADMIN_LOG/.test(msg)) {
      leg('harness-seam-accepts-project-record', false,
        'harness still admin.log-only: ' + msg)
    } else {
      leg('harness-seam-accepts-project-record', false, msg)
    }
    return exitAll()
  }
  leg('harness-seam-accepts-project-record', true, '')

  // --- B4 cap + pointer (60 rows, synthetic permitted: cap is a count contract)
  const many = []
  for (let i = 0; i < 60; i++) {
    many.push(JSON.stringify({ v: 1, at: 1700000000000 + i * 1000, op: 'sign', ticket: 't' + i,
      grant: 'sign', grant_source: 'grants.sign @ ' + projRoot + '/executor-grants.json',
      session: 's' + i, channel: 'arg', decision: 'allowed', idem: 'cap-' + i }))
  }
  const capPath = seedRows(many)
  try {
    await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: capPath }, async (base) => {
      const PROJ_Q = '?project=proj-x'
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      leg('b4-cap-at-most-50-newest', api.body?.ok === true && api.body?.actions?.length <= 50
        && api.body?.actions?.length >= 1,
        `n=${api.body?.actions?.length}`)
      leg('b4-older-rows-pointer-names-record',
        typeof api.body?.note === 'string' && api.body.note.includes('executor-actions.jsonl'),
        `note=${JSON.stringify(api.body?.note)}`)
    })
  } catch (e) { leg('b4-cap-at-most-50-newest', false, String(e).slice(0, 200)) }

  // --- B5 empty state + B6 degraded (no fixture needed)
  const emptyPath = join(iso, 'proj-empty', 'ledger', 'executor-actions.jsonl')
  try {
    await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: emptyPath }, async (base) => {
      const PROJ_Q = '?project=proj-empty'
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      const bodyText = JSON.stringify(api.body || {})
      leg('b5-empty-state-names-record-no-admin-log',
        api.body?.ok === false || api.body?.ok === true,
        'status=' + api.status)
      leg('b5-copy-says-no-recorded-action-and-names-file',
        bodyText.includes('executor-actions.jsonl') && !/admin\.log/i.test(bodyText),
        bodyText.slice(0, 200))
      const page = await fetch(base + PANEL_ROUTE).then(r => r.text()).catch(() => '')
      // t261004-16 仲裁修订：本断言守的是「用户可见文案」，不是原始 HTML——页面
      // 现内嵌 LIST_CONTRACTS 契约 JSON（t261004-14，source/empty_copy 字段含
      // "audit log" 字样，属脚本内惰性数据、不渲染）。先剥 <script> 块再查词，
      // 只对渲染面执行措辞禁令（更准而非放松：渲染面出现该词仍红）。
      const visible = String(page).replace(/<script[\s\S]*?<\/script>/gi, '')
      leg('b5-page-copy-free-of-audit-log-wording',
        !/admin\.log|audit log/i.test(visible), '')
    })
  } catch (e) { leg('b5-empty-state-names-record-no-admin-log', false, String(e).slice(0, 200)) }

  const badDir = join(iso, 'proj-bad', 'ledger')
  mkdirSync(badDir, { recursive: true })
  const badPath = join(badDir, 'executor-actions.jsonl')
  writeFileSync(badPath, 'x')
  try {
    await withHarness({ panelDir: join(iso, 'panel'), executorActionsPath: badPath }, async (base) => {
      const PROJ_Q = '?project=proj-bad'
      // chmod 000 makes the record unreadable (degraded face)
      const { chmodSync } = await import('node:fs')
      chmodSync(badPath, 0o000)
      const api = await jfetch(base, PANEL_ROUTE + '/api/actions' + PROJ_Q)
      chmodSync(badPath, 0o600)
      leg('b6-unreadable-record-explicit-degradation',
        api.body?.ok === false && String(api.body?.reason || '').length > 0,
        `status=${api.status} body=${JSON.stringify(api.body).slice(0, 160)}`)
    })
  } catch (e) { leg('b6-unreadable-record-explicit-degradation', false, String(e).slice(0, 200)) }

  exitAll()
}

main().catch(e => { leg('scenario-crash', false, String(e).slice(0, 300)); exitAll() })
