/**
 * Baseline: epic status enum + note column + status edit endpoint (t260831-05).
 *
 * Intent:
 *   Epic "status" was free-form (seven charters, seven phrasings) so the workbench
 *   could not filter/count by status and agents could not parse it reliably. This
 *   ticket pins status to a 4-value enum, moves free-text detail into a new
 *   "备注" (note) table column, adds POST /api/epics/<code>/status, and migrates
 *   the 7 existing charters. This baseline locks the USER-PERCEIVABLE contract:
 *   only the 4 canonical values are writable, detail text survives the migration
 *   in the note column, malformed input never corrupts a charter file, and the
 *   workbench can filter the list by every enum value.
 *
 * High-level steps (fully offline: tmp fixtures + real-repo read-only assertions):
 *   A. Enum source of truth: exactly 4 canonical values (full-width parens);
 *      isEpicStatus accepts precisely those, rejects half-width parens, padded,
 *      substring, empty and look-alike values.
 *   B. Real-repo migration: the charters under notes/epics all carry a status
 *      in the enum and a parseable note column; the migrated detail text is
 *      preserved (sandbar pointer, 2026-08-30 delivery date, pending-decision
 *      notes); listEpics surfaces the note field.
 *   C. setEpicStatus write contract (fixture): legal rewrite persists status+note
 *      with a pre-write /tmp backup (newest backup for the code = original text);
 *      note omitted/null leaves the column, '' clears it; invalid enum -> 422 and
 *      the file is byte-identical afterwards; malformed note (|, newline, backtick,
 *      >200 chars) -> 422, non-string note -> 400, both leave the file untouched;
 *      anti-traversal 400s; missing status row -> 422; unknown code -> 404;
 *      closeEpic regression: close yields 已完结 (in enum), preserves the note,
 *      and backs up.
 *   D. Route contract (mock req/res over apply()): POST /status 200 with
 *      {code,status,note}; malformed JSON / missing status -> 400; invalid enum /
 *      malformed note -> 422; note nine states end-to-end; GET -> 405; unknown
 *      code -> 404; unknown subpath 404 message lists /status.
 *   E. Frontend model contract: filterEpicsByStatus ('' = all, per-enum match,
 *      zero-match -> empty, unknown value -> empty, never throws) and
 *      EPIC_STATUS_OPTIONS stays in lockstep with the host enum (same values,
 *      same order).
 *   F. Suggest-prompt readability: the migrated status line appears verbatim in
 *      the epic-next suggest prompt (agent-facing parseability win).
 *
 * Note: this baseline FAILS LOUDLY until t260831-05 implement lands (the enum
 * constants, note parsing, setEpicStatus, the /status route and the frontend
 * filter do not exist yet). That is the intended pre-implementation state;
 * run_integration_tests is the judging stage.
 *
 * Reference: .suyou/stage_create_plan_gen1.json (approved plan v2); fault-mode
 * trade-offs of the reused closeEpic skeleton were reviewed item-by-item in
 * review_plan round 2 (all 7 carried over; backup dir shared /tmp/epic-close-backup).
 */

import { mkdtemp, mkdir, writeFile, readFile, readdir, rm, stat } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  EPIC_STATUSES, isEpicStatus, listEpics, parseEpicMeta,
  setEpicStatus, validateEpicNote, closeEpic,
} from './../src/host/epics.ts'
import { buildSuggestPrompt } from './../src/host/epic-next.ts'
import { EPIC_STATUS_OPTIONS, filterEpicsByStatus } from './../src/client/epics-model.ts'
import { apply } from './../node.ts'

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const CANONICAL = ['已立项（待开工单）', '已立项（执行中）', '已完结', '已归档']

const tmp = await mkdtemp(join(tmpdir(), 'integ-epic-status-'))
const savedEnv = { SUYOU_EPICS_DIR: process.env.SUYOU_EPICS_DIR }

/** Newest backup file for <code> under the shared backup dir (null if none). */
async function newestBackup(code) {
  const dir = '/tmp/epic-close-backup'
  if (!existsSync(dir)) return null
  const files = (await readdir(dir)).filter(f => f.startsWith(`${code}-`) && f.endsWith('.md'))
  if (files.length === 0) return null
  let best = null, bestMtime = -1
  for (const f of files) {
    const m = (await stat(join(dir, f))).mtimeMs
    if (m > bestMtime) { bestMtime = m; best = join(dir, f) }
  }
  return best
}

/** Mock webServer/req/res harness (same pattern as baselines/epics-api.mjs). */
function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  const find = (kind, path) => routes.find(r => r.kind === kind && r.path === path)
  return {
    exactEpics: find('exact', '/suyou-workbench/api/epics'),
    prefixEpics: find('prefix', '/suyou-workbench/api/epics'),
  }
}
const mockRes = () => ({
  status: 0, body: null,
  writeHead(s) { this.status = s },
  end(b) { this.body = b ? JSON.parse(b) : null },
})
/** bodyObj: JSON object; rawBody: string sent verbatim (for malformed-JSON probe). */
const call = async (handler, url, method = 'GET', bodyObj, rawBody) => {
  const res = mockRes()
  let payload = []
  if (rawBody !== undefined) payload = [Buffer.from(rawBody)]
  else if (bodyObj !== undefined) payload = [Buffer.from(JSON.stringify(bodyObj))]
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* payload } }
  await handler.handler(req, res)
  return res
}

const FIXTURE_MD = (status, noteRow) => `# 立项单：integ-st-alpha

| 字段 | 值 |
| --- | --- |
| 代号 | \`integ-st-alpha\` |
| 状态 | ${status} |
${noteRow ? `| 备注 | ${noteRow} |\n` : ''}| 立项日期 | 2026-08-30 |

## 目标

集成测试桩。
`

try {
  /* ------------------------------------------------ A. enum source of truth */
  section('A enum source of truth (4 canonical values, exact-match whitelist)')
  ok(Array.isArray(EPIC_STATUSES) && EPIC_STATUSES.length === 4
    && JSON.stringify([...EPIC_STATUSES].sort()) === JSON.stringify([...CANONICAL].sort()),
    'EPIC_STATUSES = the 4 canonical values')
  for (const s of CANONICAL) ok(isEpicStatus(s), `isEpicStatus('${s}') accepted`)
  for (const bad of [
    '已立项(待开工单)',            // half-width parens
    '已立项（待开工单） ',          // trailing space
    ' 已立项（待开工单）',          // leading space
    '已立项',                      // substring, not a value
    '已完结（2026-08-30）',        // old free-form phrasing
    '已结项',                      // retired free-form value
    '',                           // empty
    '已立项（执行中）\n',          // newline tail
  ]) ok(!isEpicStatus(bad), `isEpicStatus(${JSON.stringify(bad)}) rejected`)

  /* ------------------------------------------------ B. real-repo migration */
  // 断言意图=notes/epics 下全部立项单的状态都是合法枚举值。expected 是清单登记处：
  // 新增立项单时在此加一行（metrics 于 260901 立项，t260901-11 仲裁 7→8）。
  section('B real-repo migration (charters under notes/epics of the lane root)')
  // 人口普查锚点：新增立项单须同步此清单（metrics 于 260901 立项，t260901-11 仲裁 7→8）。
  // 冲突消解取 main 侧精确普查（更新的仲裁决定）；泳道侧「新单合法出现不判败」的
  // 全覆盖精神由下方逐条 status 词表断言承担（对真实清单全部条目生效）。
  const realDir = join(process.cwd(), 'notes', 'epics')
  // t260901-23 冲突消解（gen1）：merge 带入 main 侧第 9 张立项单 conveyor（其工单
  // 漏登记此清单），按本清单自述纪律「新增立项单须同步此清单」补一行——8→9。
  const expected = ['coding-games', 'dsh-generalize', 'epic-linkage', 'metrics', 'observability',
    'sandbar', 'science-content', 'session-entry', 'conveyor']
  const real = await listEpics(realDir)
  ok(real.length === expected.length && expected.every(c => real.some(e => e.code === c)),
    `exactly the ${expected.length} known charters are listed`)
  const byCode = Object.fromEntries(real.map(e => [e.code, e]))
  for (const e of real) {
    ok(EPIC_STATUSES.includes(e.status), `${e.code}: status '${e.status}' is a canonical enum value`)
    ok(typeof e.note === 'string', `${e.code}: note column is parsed (string, possibly empty)`)
  }
  ok(byCode['coding-games'].note.includes('方向待拍板'), 'coding-games: pending-direction detail preserved in note')
  ok(byCode['science-content'].note.includes('先做哪条线'), 'science-content: pending-line detail preserved in note')
  ok(byCode['session-entry'].note.includes('第 1 面'), 'session-entry: first-surface detail preserved in note')
  ok(byCode['dsh-generalize'].note.includes('sandbar'), 'dsh-generalize: sandbar pointer preserved in note')
  ok(byCode['dsh-generalize'].status === '已归档', 'dsh-generalize: retired 已结项 mapped to 已归档')
  ok(byCode['epic-linkage'].status === '已完结' && byCode['epic-linkage'].note.includes('2026-08-30'),
    'epic-linkage: 已完结 with delivery date in note')
  ok(byCode['sandbar'].status === '已立项（执行中）', 'sandbar: bare 已立项 mapped to 已立项（执行中）')
  // Free-form residue scan: no migrated status cell may contain parentheses detail anymore.
  const residue = real.filter(e => /（.*）/.test(e.status) && !isEpicStatus(e.status))
  ok(residue.length === 0, 'no free-form residue left in any status cell')

  /* ------------------------------------------------ C. setEpicStatus write contract */
  section('C setEpicStatus write contract (fixture dir, SUYOU_EPICS_DIR isolated)')
  const epicsDir = join(tmp, 'notes', 'epics')
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'integ-st-alpha.md'), FIXTURE_MD('已立项（执行中）', '原始备注'), 'utf8')
  await writeFile(join(epicsDir, 'integ-st-no-note.md'), FIXTURE_MD('已立项（待开工单）', ''), 'utf8')
  await writeFile(join(epicsDir, 'integ-st-no-status.md'), '# 立项单：integ-st-no-status\n\nno table.\n', 'utf8')
  process.env.SUYOU_EPICS_DIR = epicsDir
  const read = (code) => readFile(join(epicsDir, code + '.md'), 'utf8')

  // validateEpicNote unit surface (same口径 consumed by endpoint + smoke)
  ok(validateEpicNote('单行正常备注').ok === true, 'validateEpicNote: plain single-line note ok')
  ok(validateEpicNote('x'.repeat(200)).ok === true, 'validateEpicNote: 200-char note ok (boundary)')
  ok(validateEpicNote('x'.repeat(201)).ok === false, 'validateEpicNote: 201-char note rejected')
  for (const [bad, why] of [['含|竖线', 'pipe'], ['含\n换行', 'newline'], ['含`反引号`', 'backtick']]) {
    const r = validateEpicNote(bad)
    ok(r.ok === false && r.status === 422 && String(r.error).length > 0, `validateEpicNote: ${why} -> 422 with message`)
  }
  for (const bad of [123, {}, ['a']]) {
    const r = validateEpicNote(bad)
    ok(r.ok === false && r.status === 400, `validateEpicNote: non-string ${JSON.stringify(bad)?.slice(0, 12)} -> 400`)
  }
  ok(validateEpicNote(null).ok === true && validateEpicNote(undefined).ok === true,
    'validateEpicNote: null/undefined = omitted (ok, no-op)')

  // Legal rewrite: status + note persisted, note readable back, backup = original.
  const before = await read('integ-st-alpha')
  let r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已完结', '交付完成')
  ok(r.ok === true && r.status === '已完结', 'setEpicStatus: legal value accepted')
  let after = await read('integ-st-alpha')
  ok(after.includes('| 状态 | 已完结 |') && after.includes('| 备注 | 交付完成 |'),
    'setEpicStatus: status row + note row persisted on disk')
  const metaBack = parseEpicMeta(after)
  ok(metaBack.status === '已完结' && metaBack.note === '交付完成', 'setEpicStatus: parseEpicMeta reads back status+note')
  const backupFile = await newestBackup('integ-st-alpha')
  ok(backupFile !== null && (await readFile(backupFile, 'utf8')) === before,
    'setEpicStatus: pre-write backup in shared /tmp/epic-close-backup equals original text')

  // Note omitted / null / '' semantics.
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项（执行中）')
  ok(r.ok === true && parseEpicMeta(await read('integ-st-alpha')).note === '交付完成',
    'setEpicStatus: note omitted -> note column untouched')
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项（执行中）', null)
  ok(r.ok === true && parseEpicMeta(await read('integ-st-alpha')).note === '交付完成',
    'setEpicStatus: note=null -> same as omitted')
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项（执行中）', '')
  ok(r.ok === true && parseEpicMeta(await read('integ-st-alpha')).note === '',
    "setEpicStatus: note='' -> note column cleared (explicit action)")
  // Note row inserted when the charter has none.
  r = await setEpicStatus(epicsDir, 'integ-st-no-note', '已立项（执行中）', '补写的备注')
  ok(r.ok === true && parseEpicMeta(await read('integ-st-no-note')).note === '补写的备注',
    'setEpicStatus: note row inserted when charter lacked one')

  // Rejections must not touch the file (byte-identical after the call).
  const snap = await read('integ-st-alpha')
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项(执行中)')
  ok(r.ok === false && r.status === 422 && String(r.error).includes('已立项（执行中）')
    && (await read('integ-st-alpha')) === snap,
    'setEpicStatus: half-width-paren value -> 422 listing legal values, file untouched')
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已冻结')
  ok(r.ok === false && r.status === 422 && (await read('integ-st-alpha')) === snap,
    'setEpicStatus: value outside whitelist -> 422, file untouched')
  for (const [bad, why] of [['含|竖线', 'pipe'], ['含\n换行', 'newline'], ['含`反引号`', 'backtick'], ['x'.repeat(201), 'over-200-chars']]) {
    r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已完结', bad)
    ok(r.ok === false && r.status === 422 && (await read('integ-st-alpha')) === snap,
      `setEpicStatus: malformed note (${why}) -> 422, file untouched`)
  }
  for (const bad of [123, { x: 1 }]) {
    r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已完结', bad)
    ok(r.ok === false && r.status === 400 && (await read('integ-st-alpha')) === snap,
      `setEpicStatus: non-string note (${JSON.stringify(bad)}) -> 400, file untouched`)
  }
  r = await setEpicStatus(epicsDir, 'integ-st-alpha/../escape', '已完结')
  ok(r.ok === false && r.status === 400, 'setEpicStatus: traversal-shaped code -> 400 (whitelist, never reaches fs)')
  r = await setEpicStatus(epicsDir, 'no-such-epic', '已完结')
  ok(r.ok === false && r.status === 404, 'setEpicStatus: unknown code -> 404')
  r = await setEpicStatus(epicsDir, 'integ-st-no-status', '已完结')
  ok(r.ok === false && r.status === 422 && String(r.error).includes('状态'),
    'setEpicStatus: charter without status row -> 422 (no vague success)')

  // listEpics surfaces note.
  const listed = (await listEpics(epicsDir)).find(e => e.code === 'integ-st-alpha')
  ok(listed !== undefined && typeof listed.note === 'string', 'listEpics: note field present per charter')

  // closeEpic regression: enum-aligned, note preserved, backup taken.
  const preClose = await read('integ-st-alpha')
  r = await closeEpic(epicsDir, 'integ-st-alpha')
  ok(r.ok === true && r.status === '已完结' && isEpicStatus(r.status),
    'closeEpic: still closes with canonical 已完结 (in enum)')
  ok(parseEpicMeta(await read('integ-st-alpha')).note === parseEpicMeta(preClose).note,
    'closeEpic: note column preserved by close')
  const closeBackup = await newestBackup('integ-st-alpha')
  ok(closeBackup !== null && (await readFile(closeBackup, 'utf8')) === preClose,
    'closeEpic: pre-write backup equals pre-close text')

  /* ------------------------------------------------ D. route contract */
  section('D POST /api/epics/<code>/status route contract (mock req/res over apply())')
  const repoD = join(tmp, 'repo-d')
  await mkdir(repoD, { recursive: true })
  const h = makeHarness(repoD)
  ok(h.prefixEpics !== undefined, 'epics prefix route mounted')

  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST',
    { status: '已归档', note: '路由写入' })
  ok(r.status === 200 && r.body.ok === true && r.body.result?.code === 'integ-st-alpha'
    && r.body.result?.status === '已归档' && r.body.result?.note === '路由写入',
    'POST /status -> 200 {ok,result:{code,status,note}}')
  ok(parseEpicMeta(await read('integ-st-alpha')).status === '已归档',
    'POST /status: rewrite persisted on disk')

  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'GET')
  ok(r.status === 405, 'GET /status -> 405 (write action is POST-only)')
  // Rejected-call batch: none of these may modify the charter (snapshot before/after).
  const snapD = parseEpicMeta(await read('integ-st-alpha'))
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST',
    undefined, '{"status": "已完结", broken')
  ok(r.status === 400 && r.body.ok === false, 'malformed JSON body -> 400')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST', { note: '只有备注' })
  ok(r.status === 400, 'missing status field -> 400')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '半角(执行中)' })
  ok(r.status === 422 && String(r.body.error).includes('已立项（执行中）'),
    'invalid enum -> 422 with legal-value hint')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '已完结', note: 'a|b' })
  ok(r.status === 422, 'note with pipe -> 422')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '已完结', note: 42 })
  ok(r.status === 400, 'non-string note -> 400')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '已完结', note: null })
  const afterNull = parseEpicMeta(await read('integ-st-alpha'))
  ok(r.status === 200 && afterNull.status === '已完结' && afterNull.note === '路由写入',
    'note:null -> status applied, note column untouched (null == omitted)')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/no-such-epic/status', 'POST', { status: '已完结' })
  ok(r.status === 404, 'unknown code -> 404')
  r = await call(h.prefixEpics, '/suyou-workbench/api/epics/integ-st-alpha/bogus-op')
  ok(r.status === 404 && String(r.body.error).includes('/status'),
    'unknown subpath -> 404 message lists /status')
  const afterRejects = parseEpicMeta(await read('integ-st-alpha'))
  ok(afterRejects.status === '已完结' && afterRejects.note === '路由写入',
    'route: charter stable after rejected-call batch')

  /* ------------------------------------------------ E. frontend model contract */
  section('E frontend model contract (filter + options lockstep with host enum)')
  ok(Array.isArray(EPIC_STATUS_OPTIONS) && EPIC_STATUS_OPTIONS.length === 4
    && JSON.stringify(EPIC_STATUS_OPTIONS) === JSON.stringify(EPIC_STATUSES),
    'EPIC_STATUS_OPTIONS identical to host EPIC_STATUSES (values + order)')
  const rows = [
    { code: 'a', title: 'A', status: '已立项（待开工单）', created: '2026-08-01', note: '' },
    { code: 'b', title: 'B', status: '已立项（执行中）', created: '2026-08-02', note: 'x' },
    { code: 'c', title: 'C', status: '已完结', created: '2026-08-03', note: '' },
    { code: 'd', title: 'D', status: '已归档', created: '2026-08-04', note: 'y' },
  ]
  ok(filterEpicsByStatus(rows, '').length === 4, "filter '' -> all rows")
  ok(filterEpicsByStatus(rows, '已完结').length === 1 && filterEpicsByStatus(rows, '已完结')[0].code === 'c',
    'filter by 已完结 -> exactly the matching row')
  ok(filterEpicsByStatus(rows, '已立项（待开工单）').length === 1, 'filter by 已立项（待开工单） -> 1 row')
  ok(Array.isArray(filterEpicsByStatus([], '已完结')) && filterEpicsByStatus([], '已完结').length === 0,
    'empty list -> empty result, no throw')
  ok(Array.isArray(filterEpicsByStatus(rows, '已冻结')) && filterEpicsByStatus(rows, '已冻结').length === 0,
    'unknown value -> empty result, no throw')
  ok(rows.length === 4, 'filter is pure: input list not mutated')

  /* ------------------------------------------------ F. suggest-prompt readability */
  section('F epic-next suggest prompt carries the canonical status line verbatim')
  const prompt = buildSuggestPrompt({
    code: 'integ-st-alpha',
    epicTitle: '集成测试桩',
    epicMarkdown: FIXTURE_MD('已归档', '已迁移的细节'),
    ticketsSummary: '（无关联工单）',
    workflows: [{ id: 'dev-lane', name: 'dev' }],
    resultPath: '/tmp/integ-st-result.json',
  })
  ok(prompt.includes('| 状态 | 已归档 |'), 'suggest prompt inlines the canonical status row (agent-parseable)')

  /* ------------------------------------------------ G. degraded note-column read */
  section('G note-column read tolerance (charters without the row)')
  const noNoteMeta = parseEpicMeta(FIXTURE_MD('已完结', ''))
  ok(noNoteMeta.note === '', 'parseEpicMeta: missing note row -> empty string, no throw')
} finally {
  // Full-terminal-state cleanup: restore env, remove tmp fixtures.
  if (savedEnv.SUYOU_EPICS_DIR === undefined) delete process.env.SUYOU_EPICS_DIR
  else process.env.SUYOU_EPICS_DIR = savedEnv.SUYOU_EPICS_DIR
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
