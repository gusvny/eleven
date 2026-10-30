/**
 * Baseline: the epic registry row model — the retired-enum write face, the note column
 * and the state-edit endpoint (ticket t260831-05), migrated to the docs/epics face by
 * t261030-30.
 *
 * Background: the epic 'status' used to be free text. t260831-05 pinned it to a four
 * value enumeration and added the state-edit endpoint. t261019-12 then moved the store
 * from notes/epics to docs/epics and made the `retired` boolean the only epic state, so
 * the enum writer is a LEGACY face now (no route calls it; it survives for its fixture
 * and smoke contract) and the READ row comes from the front-matter record.
 *
 * Steps (fully offline: tmp fixture + real-repo property assertions):
 *   A. Enum source of truth: exactly four legal values (full-width brackets);
 *      isEpicStatus takes only those — half-width brackets, leading/trailing blanks, a
 *      substring, a look-alike and the empty string are all refused.
 *   B. Real-repo invariant over docs/epics (property, not a snapshot): every row either
 *      carries a healthy front-matter record (retired is a boolean, status is 'open' or
 *      'retired') or a named defect, and no row carries a blank status. The roster
 *      follows the directory — no mirrored list (B2 proves it on a fixture whose size
 *      deliberately differs from the real repo).
 *   C. setEpicStatus write contract (fixture) — the legacy field-table writer: a legal
 *      value rewrites the status row on disk with a /tmp backup = the original text; the
 *      note column is untouched when the note is omitted or null, cleared by '', and
 *      inserted when the document has no note row; every refusal (illegal enum value,
 *      malformed note, non-string note, traversal-shaped code, unknown code, missing
 *      status row) leaves the file byte-identical. closeEpic closes with 「已完结」,
 *      keeps the note and backs the document up.
 *   D. The state-edit route is retired: POST/GET /api/epics/<code>/status answer 410
 *      naming docs/epics/<code>.md, and the document is untouched. (The full close +
 *      status route contract lives in tests/epics-api.mjs section D.)
 *   E. Front-end model contract: filterEpicsByStatus ('' = all, exact enum match, zero
 *      hits = empty, unknown value = empty, never throws); EPIC_STATUS_OPTIONS is
 *      identical to the host enum (same values, same order).
 *   G. Note-column read tolerance: a document without the note row answers ''.
 *   (t260910-14 retirement note: the old section F 'suggestion prompt readability' is
 *   gone with the epic-next retirement.)
 *
 * Reference: the approved plan v2 (.suyou/stage_create_plan_gen1.json); the failure-mode
 * list for the closeEpic skeleton was reviewed item by item (7 of 7 carried over; the
 * backup directory is shared at /tmp/epic-close-backup).
 */

import { mkdtemp, mkdir, writeFile, readFile, readdir, rm, stat } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  EPIC_CODE_RE, EPIC_STATUSES, isEpicStatus, listEpics, parseEpicMeta,
  setEpicStatus, validateEpicNote, closeEpic,
} from './../src/host/epics.ts'
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
const savedEnv = { SANDBAR_EPICS_DIR: process.env.SANDBAR_EPICS_DIR }

/** 共享备份目录下 <code> 的最新备份文件（无则 null）。 */
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

/** mock webServer/req/res 支架（与 baselines/epics-api.mjs 同模式）。 */
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
    exactEpics: find('exact', '/sandbar-workbench/api/epics'),
    prefixEpics: find('prefix', '/sandbar-workbench/api/epics'),
  }
}
const mockRes = () => ({
  status: 0, body: null,
  writeHead(s) { this.status = s },
  end(b) { this.body = b ? JSON.parse(b) : null },
})
/** bodyObj：JSON 对象；rawBody：原样发送的字符串（畸形 JSON 探针用）。 */
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
    '已立项(待开工单)',            // 半角括号
    '已立项（待开工单） ',          // 尾部空格
    ' 已立项（待开工单）',          // 首部空格
    '已立项',                      // 子串，不是合法值
    '已完结（2026-08-30）',        // 旧自由文本写法
    '已结项',                      // 已退役的自由文本值
    '',                           // 空串
    '已立项（执行中）\n',          // 尾部换行
  ]) ok(!isEpicStatus(bad), `isEpicStatus(${JSON.stringify(bad)}) rejected`)

  /* ---------------------------------- B. real-repo invariant + roster independence */
  // 260904 重构（宿主质疑「真实数据自测」）：本段原为 suyou 时代真数据快照——写死
  // 9 张 charter 清单+逐张 note 点名，每新增/迁移一张 epic 就红一次，测试在追真数据
  // 跑。重构为两层，快照镜像删除：
  //   B1 real-data invariant (a property, not a snapshot): every row under the real
  //      docs/epics either is a healthy front-matter record or carries a named defect,
  //      and no row carries a blank status — new or removed documents do not turn it
  //      red, bad data does;
  //   B2 roster independence (fixture): a controlled document set whose size
  //      deliberately differs from the real repo proves listEpics follows the directory.
  section('B1 real-repo invariant (property over docs/epics; roster follows truth)')
  const realDir = join(process.cwd(), 'docs', 'epics')
  const real = await listEpics(realDir)
  ok(real.length >= 1, 'docs/epics has at least one epic document')
  ok(real.every((e) => typeof e.status === 'string' && e.status !== ''),
    'every real row carries a status line (never a blank, healthy-looking row)')
  const healthy = real.filter((e) => e.defect === undefined)
  const defective = real.filter((e) => e.defect !== undefined)
  ok(healthy.every((e) => typeof e.retired === 'boolean' && (e.status === 'open' || e.status === 'retired')),
    'every healthy row: retired is a boolean and status is open|retired')
  for (const e of defective) {
    ok(typeof e.defect === 'string' && e.defect !== '' && e.retired === true,
      `${e.code}: unreadable record carries a named defect and fails closed`)
  }
  ok(real.every((e) => EPIC_CODE_RE.test(e.code)), 'every listed code passes the engine code shape')

  section('B2 roster independence (fixture dir; listEpics follows the dir, no mirror list)')
  {
    const fxDir = join(tmp, 'epic-roster-fx')
    await mkdir(fxDir, { recursive: true })
    const doc = (code, retired, summary) =>
      `---\ncode: ${code}\nretired: ${retired}\nsummary: ${summary}\nstarted: 2026-08-30\n---\n\n# ${code}\n`
    // The fixture size deliberately differs from the real repo: the roster is decided
    // by the directory, so the test never mirrors a list.
    await writeFile(join(fxDir, 'alpha.md'), doc('alpha', 'false', 'Alpha line.'), 'utf8')
    await writeFile(join(fxDir, 'beta.md'), doc('beta', 'true', 'Beta is closed.'), 'utf8')
    await writeFile(join(fxDir, 'gamma.md'), doc('gamma', 'false', 'Gamma line.'), 'utf8')
    let fx = await listEpics(fxDir)
    ok(fx.length === 3 && fx.every(e => ['alpha', 'beta', 'gamma'].includes(e.code)),
      'fixture: exactly the 3 written documents listed (roster follows the dir)')
    const fxBy = Object.fromEntries(fx.map(e => [e.code, e]))
    ok(fxBy['alpha'].summary === 'Alpha line.' && fxBy['alpha'].status === 'open',
      'fixture: front-matter summary and open status parsed')
    ok(fxBy['beta'].status === 'retired' && fxBy['beta'].retired === true,
      'fixture: retired: true reads as retired')
    // A new document appears -> the list changes (nothing to mirror, so a stale mirror fails).
    await writeFile(join(fxDir, 'delta.md'), doc('delta', 'false', 'Delta line.'), 'utf8')
    fx = await listEpics(fxDir)
    ok(fx.length === 4 && fx.some(e => e.code === 'delta'), 'fixture: new document appears without mirror-list edits')
    // Non-md files and illegal code shapes are not rows (defense regression).
    await writeFile(join(fxDir, 'not-a-charter.txt'), 'x', 'utf8')
    await writeFile(join(fxDir, 'BAD_CODE.md'), 'x', 'utf8')
    fx = await listEpics(fxDir)
    ok(fx.length === 4, 'fixture: non-md and bad-code files excluded from roster')
    let missing = ''
    try { await listEpics(join(fxDir, 'no-such-dir')) } catch (e) { missing = String(e && e.message) }
    ok(missing.includes('epic registry directory not found'),
      'fixture: an absent registry throws a named error (no fake empty roster)')
  }

  /* ------------------------------------------------ C. setEpicStatus write contract */
  section('C setEpicStatus write contract (fixture dir, SANDBAR_EPICS_DIR isolated)')
  const epicsDir = join(tmp, 'notes', 'epics')
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'integ-st-alpha.md'), FIXTURE_MD('已立项（执行中）', '原始备注'), 'utf8')
  await writeFile(join(epicsDir, 'integ-st-no-note.md'), FIXTURE_MD('已立项（待开工单）', ''), 'utf8')
  await writeFile(join(epicsDir, 'integ-st-no-status.md'), '# 立项单：integ-st-no-status\n\nno table.\n', 'utf8')
  process.env.SANDBAR_EPICS_DIR = epicsDir
  const read = (code) => readFile(join(epicsDir, code + '.md'), 'utf8')

  // validateEpicNote 单测面（端点 + smoke 消费的同一口径）
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

  // 合法改写：status + note 落盘，备注可读回，备份=原文。
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

  // 备注缺省 / null / '' 语义。
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项（执行中）')
  ok(r.ok === true && parseEpicMeta(await read('integ-st-alpha')).note === '交付完成',
    'setEpicStatus: note omitted -> note column untouched')
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项（执行中）', null)
  ok(r.ok === true && parseEpicMeta(await read('integ-st-alpha')).note === '交付完成',
    'setEpicStatus: note=null -> same as omitted')
  r = await setEpicStatus(epicsDir, 'integ-st-alpha', '已立项（执行中）', '')
  ok(r.ok === true && parseEpicMeta(await read('integ-st-alpha')).note === '',
    "setEpicStatus: note='' -> note column cleared (explicit action)")
  // 立项单无备注行时新插一行。
  r = await setEpicStatus(epicsDir, 'integ-st-no-note', '已立项（执行中）', '补写的备注')
  ok(r.ok === true && parseEpicMeta(await read('integ-st-no-note')).note === '补写的备注',
    'setEpicStatus: note row inserted when charter lacked one')

  // 拒收绝不能碰文件（调用后逐字节一致）。
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

  // listEpics 透出备注。
  const listed = (await listEpics(epicsDir)).find(e => e.code === 'integ-st-alpha')
  ok(listed !== undefined && typeof listed.note === 'string', 'listEpics: note field present per charter')

  // closeEpic 回归：枚举对齐、备注保留、有备份。
  const preClose = await read('integ-st-alpha')
  r = await closeEpic(epicsDir, 'integ-st-alpha')
  ok(r.ok === true && r.status === '已完结' && isEpicStatus(r.status),
    'closeEpic: still closes with canonical 已完结 (in enum)')
  ok(parseEpicMeta(await read('integ-st-alpha')).note === parseEpicMeta(preClose).note,
    'closeEpic: note column preserved by close')
  const closeBackup = await newestBackup('integ-st-alpha')
  ok(closeBackup !== null && (await readFile(closeBackup, 'utf8')) === preClose,
    'closeEpic: pre-write backup equals pre-close text')

  /* ------------------------------------------------ D. the retired route */
  section('D POST /api/epics/<code>/status is retired (410, named, file untouched)')
  const repoD = join(tmp, 'repo-d')
  await mkdir(repoD, { recursive: true })
  const h = makeHarness(repoD)
  ok(h.prefixEpics !== undefined, 'epics prefix route mounted')
  const beforeD = await read('integ-st-alpha')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST',
    { status: '已归档', note: '路由写入' })
  ok(r.status === 410 && String(r.body.error).includes('t261019-12')
    && String(r.body.error).includes('docs/epics/integ-st-alpha.md'),
    'POST /status -> 410 naming docs/epics/<code>.md (retired is the only state now)')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'GET')
  ok(r.status === 410, 'GET /status -> 410 (the same named retirement)')
  ok((await read('integ-st-alpha')) === beforeD, 'the retired route leaves the document byte-identical')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/bogus-op')
  ok(r.status === 404, 'unknown subpath -> 404')

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

  /* ------------------------------------------------ G. degraded note-column read */
  section('G note-column read tolerance (charters without the row)')
  const noNoteMeta = parseEpicMeta(FIXTURE_MD('已完结', ''))
  ok(noNoteMeta.note === '', 'parseEpicMeta: missing note row -> empty string, no throw')
} finally {
  // 终态全回收：还原 env，删除 tmp fixture。
  if (savedEnv.SANDBAR_EPICS_DIR === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv.SANDBAR_EPICS_DIR
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
