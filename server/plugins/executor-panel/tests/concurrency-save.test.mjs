/**
 * concurrency-save.test.mjs —— t261006-17 (CL-2) 写面 + API 路由 UT：
 *  - 写回执解析真值表（saved:true 带 audit_row / saved:true 无 audit_row 拒收 /
 *    saved:false 透传 / 非零退出+空回执 / 超时 kill / 未知子命令 → engine entry absent）；
 *  - API 层：GET 读面（成功/具名拒收透传）、路由表在案、POST 401 凭据门、
 *    POST limit 形状校验、POST 成功与 writer_mismatch、POST 失败分支同样可见错配。
 * 全部走注入桩，零真引擎、零真盘（审计读面用临时目录）。
 */
import { assert, done, freshDir, cleanup, panelCookieFor, authPass } from './lib.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import {
  parseConcurrencySaveReceipt, parseConcurrencySaveReceiptOrAbsent, readLastLimitAudit, spawnConcurrencyLimitWrite,
} from '../src/host/concurrency.ts'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'

let n = 0

// ---- 写回执解析真值表 ----
{
  const okRow = { ts: 123, by: 'host', from: 2, to: 5 }
  const r = parseConcurrencySaveReceipt(JSON.stringify({ saved: true, project: 'alpha', limit: 5, audit_row: okRow, decl: '/d.json' }))
  assert(r.saved === true && r.limit === 5 && r.audit_row.by === 'host', 'saved receipt with audit_row parses')
  n++
  const r2 = parseConcurrencySaveReceipt(JSON.stringify({ saved: true, project: 'alpha', limit: 'unlimited', audit_row: okRow }))
  assert(r2.saved === true && r2.limit === null, 'unlimited save reads back as null')
  n++
  const r3 = parseConcurrencySaveReceipt(JSON.stringify({ saved: true, project: 'alpha', limit: 5 }))
  assert(r3.saved === false && r3.reason.includes('audit_row'),
    'saved:true without an audit_row shape is refused (the audit line is part of the contract)')
  n++
  const r4 = parseConcurrencySaveReceipt(JSON.stringify({ saved: false, reason: 'out of range' }))
  assert(r4.saved === false && r4.reason === 'out of range', 'saved:false carries the engine reason')
  n++
  const r5 = parseConcurrencySaveReceipt('not json at all')
  assert(r5.saved === false && r5.reason.includes('not valid JSON'), 'non-JSON receipt = refusal, no fallback')
  const r6 = parseConcurrencySaveReceipt(JSON.stringify({ ok: false, error: 'x' }))
  assert(r6.saved === false && r6.reason.includes('unexpected shape'), 'engine-shell error (no saved) = refusal')
  n += 2
  const r7 = parseConcurrencySaveReceiptOrAbsent("{\"ok\":false,\"error\":\"未知子命令 'concurrency-limit-write'。\"}")
  assert(r7.saved === false && r7.reason.includes('engine entry absent'),
    'unknown subcommand -> the pinned engine-entry-absent refusal (CL-2b not landed)')
  const r8 = parseConcurrencySaveReceiptOrAbsent('TypeError: cannot reach the server')
  assert(r8.saved === false && !r8.reason.includes('engine entry absent'),
    'a plain engine failure is NOT misreported as entry-absent')
  n += 2
}

// ---- spawn 全终态 ----
{
  const ok = await spawnConcurrencyLimitWrite({ project: 'a', limit: 3, by: 'host', source: {} },
    { execFileFn: (c, a, o, cb) => setTimeout(() => cb(null, JSON.stringify({ saved: true, project: 'a', limit: 3, audit_row: { ts: 1, by: 'host', from: 2, to: 3 } })), 1) })
  assert(ok.saved === true, 'spawn success settles')
  const killed = await spawnConcurrencyLimitWrite({ project: 'a', limit: 3, by: 'host', source: {} },
    { execFileFn: (c, a, o, cb) => setTimeout(() => cb(Object.assign(new Error('x'), { killed: true }), ''), 1) })
  assert(killed.saved === false && killed.reason.includes('timed out and was killed') && killed.reason.includes('no fallback'),
    'timeout kill = named + no-fallback wording')
  const failed = await spawnConcurrencyLimitWrite({ project: 'a', limit: 3, by: 'host', source: {} },
    { execFileFn: (c, a, o, cb) => setTimeout(() => cb(new Error('exit 1'), ''), 1) })
  assert(failed.saved === false && failed.reason.includes('failed:'), 'non-zero exit + empty stdout = named')
  const thrower = await spawnConcurrencyLimitWrite({ project: 'a', limit: 3, by: 'host', source: {} },
    { execFileFn: () => { throw new Error('cannot spawn') } })
  assert(thrower.saved === false && thrower.reason.includes('could not spawn'), 'spawn throw settles named')
  n += 4
}

// ---- 审计短语读面（真临时目录） ----
{
  const dir = freshDir('conc-audit-')
  try {
    const key = 'alpha'
    mkdirSync(join(dir, key), { recursive: true })
    const r0 = readLastLimitAudit(key, { SANDBAR_PROJECTS_DIR: dir })
    assert(r0.ok === false && r0.reason === 'never changed', 'no audit file = the explicit never-changed phrase')
    writeFileSync(join(dir, key, 'concurrency-limit-audit.jsonl'),
      JSON.stringify({ ts: 1, by: 'host', from: 3, to: 2 }) + '\n' + JSON.stringify({ ts: 2, by: 'you', from: 2, to: 7 }) + '\n')
    const r = readLastLimitAudit(key, { SANDBAR_PROJECTS_DIR: dir })
    assert(r.ok === true && r.row.by === 'you' && r.row.to === 7, 'the LAST audit line is the phrase source')
    writeFileSync(join(dir, key, 'concurrency-limit-audit.jsonl'), '{ torn\n')
    const r2 = readLastLimitAudit(key, { SANDBAR_PROJECTS_DIR: dir })
    assert(r2.ok === false && r2.reason.includes('malformed'), 'a torn audit line is named, never guessed')
    n += 3
  } finally { cleanup([dir]) }
}

// ---- API 层 ----
function apiWith(deps = {}) {
  return createApi(
    { HOME: '/nonexistent-home', SANDBAR_PANEL_DIR: '/nonexistent-projects', SANDBAR_WATCHDOG_DIR: '/nonexistent-watchdog' },
    { now: () => 1, fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'stub' }), ...deps },
  )
}
const Q = (s = '') => new URLSearchParams(s)
{
  assert(PANEL_API_ROUTES.some(r => r.path === '/sandbar-executor-panel/api/concurrency'
    && r.methods.includes('GET') && r.methods.includes('POST')),
    'route table carries the concurrency face (GET+POST)')
  n++
  const okFace = { ok: true, project: 'alpha', limit: 2, unlimited: false, decl: '/d.json',
    holders: [{ ticket: 't-1', since: 1, reason: 'human-hold', held_s: 5 }], queue: [] }
  const api = apiWith({ engineConcurrencyRead: async () => okFace })
  const r = await api.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'), '')
  assert(r.status === 200 && r.json.ok === true && r.json.at_work === 1 && r.json.waiting === 0
    && r.json.holders.length === 1 && r.json.limit === 2, 'GET face serves ledger numbers + counts')
  assert(r.json.audit && r.json.audit.reason === 'never changed', 'GET face carries the audit phrase face')
  n += 2

  const apiRefuse = apiWith({ engineConcurrencyRead: async () => ({ ok: false, reason: 'ValueError: malformed ledger /abs/path' }) })
  const r2 = await apiRefuse.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=alpha'), '')
  assert(r2.status === 200 && r2.json.ok === false && r2.json.reason.includes('/abs/path'),
    'GET refusal carries the engine text verbatim (never an empty list)')
  assert(r2.json.holders === undefined && r2.json.queue === undefined, 'refusal body has no holders/queue keys')
  n += 2

  const api3 = apiWith({ engineConcurrencyRead: async () => okFace })
  const r3 = await api3.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=BAD_KEY'), '')
  assert(r3.status === 400, 'bad project key -> 400')
  // t261008-48 settled contract: an ABSENT declaration is a NAMED REFUSAL
  // (ok:false) with the engine's text verbatim + the declaration path — never an
  // ok:true fact row (ok:true + limit:null would collide with the unlimited face,
  // and the engine itself refuses). No holders/queue keys, no fabricated number.
  const apiAbsent = apiWith({ engineConcurrencyRead: async () => ({ ok: false, reason: 'ValueError: Concurrency-limit declaration absent: /p/ghost/concurrency-limit.json - fail-closed refusal' }) })
  const ra = await apiAbsent.handle('GET', '/sandbar-executor-panel/api/concurrency', Q('project=ghost'), '')
  assert(ra.status === 200 && ra.json.ok === false && ra.json.declared === false && ra.json.limit === null
    && String(ra.json.path).length > 0 && String(ra.json.note).includes('CL-2')
    && String(ra.json.reason).includes('absent') && String(ra.json.reason).includes('/p/ghost/concurrency-limit.json')
    && ra.json.holders === undefined && ra.json.queue === undefined && ra.json.unlimited === undefined,
    'absent declaration -> named refusal (ok:false + declared:false + engine text + path, no fake numbers/lists)')
  n++

  const post = async (api, body, withAuth = true) => api.handle('POST', '/sandbar-executor-panel/api/concurrency',
    Q('project=alpha'), typeof body === 'string' ? body : JSON.stringify(body), 'http://console.test',
    withAuth ? { cookie: panelCookieFor('console.test'), host: 'console.test' } : { host: 'console.test' })

  const apiGate = apiWith({ engineConcurrencyWrite: async () => ({ saved: false, reason: 'unreachable' }) })
  const r4 = await post(apiGate, { limit: 5 }, false)
  assert(r4.status === 401, 'POST without the session credential -> 401 before any parse (default gate)')
  const api4 = apiWith({ authFace: authPass, engineConcurrencyWrite: async () => ({ saved: false, reason: 'engine entry absent (CL-2b not landed) — nothing written' }) })
  const r5 = await post(api4, { limit: 11 })
  assert(r5.status === 422, 'limit 11 -> 422 (range guard before the engine is asked)')
  const r6 = await post(api4, '{ not json')
  assert(r6.status === 400, 'non-JSON body -> 400')
  const r7 = await post(api4, { limit: 5 })
  assert(r7.status === 200 && r7.json.ok === false && /engine entry absent/i.test(r7.json.reason),
    'CL-2b absent -> the pinned named refusal, nothing written')
  n += 5

  // 成功 + 错配身份可见（成功与失败两个分支都要携带）。
  const savedRow = { ts: 9, by: 'host', from: 2, to: 5 }
  // t261008-37 rework (KI-193): a body by naming another writer is refused BEFORE the
  // spawn — the write face must never be called (a save with mismatch metadata was
  // the arbitrated defect: a report after the fact, not a refusal).
  let mismatchSpawnCalls = 0
  const apiOk = apiWith({ authFace: authPass, engineConcurrencyWrite: async (p) => {
    mismatchSpawnCalls++
    return { saved: true, project: 'alpha', limit: p.limit === 'unlimited' ? null : p.limit,
      audit_row: { ...savedRow, to: p.limit === 'unlimited' ? 'unlimited' : p.limit }, decl: '/d.json' }
  } })
  const r8 = await post(apiOk, { limit: 5, by: 'someone-else' })
  assert(r8.status === 200 && r8.json.ok === false && r8.json.saved === false
    && r8.json.writer_mismatch === true && r8.json.by_claimed === 'someone-else'
    && /writer_mismatch/.test(r8.json.reason),
    'a mismatched body by is refused by name, nothing written')
  assert(mismatchSpawnCalls === 0, 'the write face is NEVER spawned on a mismatch')
  const r9 = await post(apiOk, { limit: 5, by: 'host' })
  assert(r9.status === 200 && r9.json.saved === true && r9.json.audit_row.to === 5,
    'the credential-proven writer saves and carries the audit row')
  const apiFail = apiWith({ authFace: authPass, engineConcurrencyWrite: async () => ({ saved: false, reason: 'engine write failed' }) })
  const r9f = await post(apiFail, { limit: 5, by: 'host' })
  assert(r9f.status === 200 && r9f.json.ok === false && r9f.json.reason === 'engine write failed',
    'the engine-failure branch keeps the named reason')
  const r10 = await post(apiOk, { limit: 'unlimited' })
  assert(r10.status === 200 && r10.json.saved === true && r10.json.limit === null, 'unlimited save accepted')
  n += 5
}

done(n)
