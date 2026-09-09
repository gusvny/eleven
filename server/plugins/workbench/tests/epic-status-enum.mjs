/**
 * 基线：立项状态枚举 + 备注列 + 状态编辑端点（票 t260831-05）。
 *
 * 背景：立项单「状态」原是自由文本（七张立项单七种写法），工单台无法按状态
 * 筛选/计数，agent 也无法可靠解析。本票把状态钉成 4 值枚举，自由文本细节
 * 迁入新增「备注」列，加 POST /api/epics/<code>/status，并迁移存量 7 张立项单。
 * 本基线锁定用户可感知契约：只有 4 个合法值可写；迁移后细节文本在备注列
 * 存活；畸形输入绝不损坏立项单文件；工单台可按每个枚举值筛选列表。
 *
 * 步骤（全离线：tmp fixture + 真仓性质断言）：
 *   A. 枚举真源：恰好 4 个合法值（全角括号）；isEpicStatus 只收这 4 个，
 *      拒半角括号/首尾空白/子串/空串/形近值。
 *   B. 真仓不变量（性质断言而非快照）：notes/epics 下每张立项单状态 ∈ 枚举、
 *      备注可解析、无自由文本残留——名册跟随目录，无镜像清单。
 *      名册独立性本身用 fixture 测（B2：tmp 目录数量刻意与真仓不同）。
 *   C. setEpicStatus 写契约（fixture）：合法改写落盘 status+note，写前备份到
 *      /tmp（该代号最新备份=原文）；note 缺省/null 不动备注列，'' 清空；
 *      非法枚举 → 422 且文件逐字节不变；畸形备注（|、换行、反引号、>200 字）
 *      → 422，非字符串备注 → 400，两者都不碰文件；防穿越 → 400；缺状态行 → 422；
 *      未知代号 → 404；closeEpic 回归：收口得「已完结」（在枚举内）、保留备注、
 *      有备份。
 *   D. 路由契约（mock req/res 套 apply()）：POST /status 200 带
 *      {code,status,note}；畸形 JSON / 缺 status → 400；非法枚举 / 畸形备注 → 422；
 *      note 九态端到端；GET → 405；未知代号 → 404；未知子路径 404 文案列 /status。
 *   E. 前端模型契约：filterEpicsByStatus（'' = 全部、按枚举匹配、零命中 → 空、
 *      未知值 → 空、永不抛错）；EPIC_STATUS_OPTIONS 与 host 枚举同步（同值同序）。
 *   F. 建议 prompt 可读性：迁移后的状态行原文出现在 epic-next 建议 prompt 里
 *      （agent 侧可解析）。
 *
 * 注意：本基线在票 t260831-05 实现落地前会大声失败（枚举常量、备注解析、
 * setEpicStatus、/status 路由、前端筛选都不存在）——这是实现前的预期状态；
 * run_integration_tests 是裁决场。
 *
 * 参考：已过审方案 v2（.suyou/stage_create_plan_gen1.json）；复用 closeEpic 骨架的
 * 故障模式取舍逐项过审（7 项全带；备份目录共用 /tmp/epic-close-backup）。
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
  //   B1 真数据不变量（性质而非快照）：真实 notes/epics 下每张 status ∈ 枚举、note
  //      可解析、无自由格式残留——真源增删不红，坏数据才红；
  //   B2 roster 独立性（fixture）：tmp 目录受控 charter 集（数量刻意与真实仓不同），
  //      证明 listEpics 跟随目录真源；note 细节保留断言移入 fixture。
  section('B1 real-repo invariant (property over notes/epics; roster follows truth)')
  const realDir = join(process.cwd(), 'notes', 'epics')
  const real = await listEpics(realDir)
  ok(real.length >= 1, 'notes/epics has at least one charter')
  for (const e of real) {
    ok(EPIC_STATUSES.includes(e.status), `${e.code}: status '${e.status}' is a canonical enum value`)
    ok(typeof e.note === 'string', `${e.code}: note column is parsed (string, possibly empty)`)
  }
  // 自由文本残留扫描：状态格不得带枚举外的括号细节。
  const residue = real.filter(e => /（.*）/.test(e.status) && !isEpicStatus(e.status))
  ok(residue.length === 0, 'no free-form residue left in any status cell')

  section('B2 roster independence (fixture dir; listEpics follows the dir, no mirror list)')
  {
    const fxDir = join(tmp, 'epic-roster-fx')
    await mkdir(fxDir, { recursive: true })
    const charter = (code, status, note) =>
      `# ${code}\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | \`${code}\` |\n| 状态 | ${status} |\n| 备注 | ${note} |\n`
    // 数量刻意 ≠ 真实仓（3 张 vs 2 张）：roster 由目录决定，测试不镜像清单
    await writeFile(join(fxDir, 'alpha.md'), charter('alpha', '已立项（执行中）', '方向待拍板：先做哪条线'), 'utf8')
    await writeFile(join(fxDir, 'beta.md'), charter('beta', '已完结（2026-09-01）', ''), 'utf8')
    await writeFile(join(fxDir, 'gamma.md'), charter('gamma', '已归档', 'sandbar 迁移'), 'utf8')
    let fx = await listEpics(fxDir)
    ok(fx.length === 3 && fx.every(e => ['alpha', 'beta', 'gamma'].includes(e.code)),
      'fixture: exactly the 3 written charters listed (roster follows the dir)')
    const fxBy = Object.fromEntries(fx.map(e => [e.code, e]))
    ok(fxBy['alpha'].note.includes('方向待拍板'), 'fixture: pending-direction detail preserved in note')
    ok(fxBy['beta'].status === '已完结（2026-09-01）' && fxBy['beta'].note === '',
      'fixture: completed status with date parses; empty note stays empty')
    // 新 charter 出现 → 清单随之变化（无写死镜像可判败）
    await writeFile(join(fxDir, 'delta.md'), charter('delta', '已立项（执行中）', '第 4 张'), 'utf8')
    fx = await listEpics(fxDir)
    ok(fx.length === 4 && fx.some(e => e.code === 'delta'), 'fixture: new charter appears without mirror-list edits')
    // 非 .md / 非法代号形状不入列（防御面回归）
    await writeFile(join(fxDir, 'not-a-charter.txt'), 'x', 'utf8')
    await writeFile(join(fxDir, 'BAD_CODE.md'), 'x', 'utf8')
    fx = await listEpics(fxDir)
    ok(fx.length === 4, 'fixture: non-md and bad-code files excluded from roster')
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

  /* ------------------------------------------------ D. route contract */
  section('D POST /api/epics/<code>/status route contract (mock req/res over apply())')
  const repoD = join(tmp, 'repo-d')
  await mkdir(repoD, { recursive: true })
  const h = makeHarness(repoD)
  ok(h.prefixEpics !== undefined, 'epics prefix route mounted')

  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST',
    { status: '已归档', note: '路由写入' })
  ok(r.status === 200 && r.body.ok === true && r.body.result?.code === 'integ-st-alpha'
    && r.body.result?.status === '已归档' && r.body.result?.note === '路由写入',
    'POST /status -> 200 {ok,result:{code,status,note}}')
  ok(parseEpicMeta(await read('integ-st-alpha')).status === '已归档',
    'POST /status: rewrite persisted on disk')

  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'GET')
  ok(r.status === 405, 'GET /status -> 405 (write action is POST-only)')
  // 拒收调用批：这些都不得改动立项单（前后快照比对）。
  const snapD = parseEpicMeta(await read('integ-st-alpha'))
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST',
    undefined, '{"status": "已完结", broken')
  ok(r.status === 400 && r.body.ok === false, 'malformed JSON body -> 400')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST', { note: '只有备注' })
  ok(r.status === 400, 'missing status field -> 400')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '半角(执行中)' })
  ok(r.status === 422 && String(r.body.error).includes('已立项（执行中）'),
    'invalid enum -> 422 with legal-value hint')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '已完结', note: 'a|b' })
  ok(r.status === 422, 'note with pipe -> 422')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '已完结', note: 42 })
  ok(r.status === 400, 'non-string note -> 400')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/status', 'POST', { status: '已完结', note: null })
  const afterNull = parseEpicMeta(await read('integ-st-alpha'))
  ok(r.status === 200 && afterNull.status === '已完结' && afterNull.note === '路由写入',
    'note:null -> status applied, note column untouched (null == omitted)')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/no-such-epic/status', 'POST', { status: '已完结' })
  ok(r.status === 404, 'unknown code -> 404')
  r = await call(h.prefixEpics, '/sandbar-workbench/api/epics/integ-st-alpha/bogus-op')
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
  // 终态全回收：还原 env，删除 tmp fixture。
  if (savedEnv.SANDBAR_EPICS_DIR === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv.SANDBAR_EPICS_DIR
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
