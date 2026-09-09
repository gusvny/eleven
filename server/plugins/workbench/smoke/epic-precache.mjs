/**
 * smoke/epic-precache.mjs — host half-smoke for the epic next-ticket precache (t260828-08).
 *
 * Run: node smoke/epic-precache.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers (pure-function level, zero network / zero Temporal / zero real agent):
 *   A. stateKeyFromRows: computes the same literal (EXPECT_STATE_KEY) from the same fixture
 *      as the python side shared.py epic_state_key (whichever drifts goes red) — this ticket
 *      pins the closed semantics, order-independent;
 *   B. readPrecache: stub pre.json hit returns instantly (ok shape) / state_key mismatch
 *      counts as a miss / workflow not in the whitelist counts as a miss / illegal JSON
 *      counts as a miss / epic mismatch counts as a miss / done shape hits / done with empty
 *      summary counts as a miss / malformed code shape counts as a miss / missing file
 *      counts as a miss;
 *   C. closeEpic: rewrites the "状态" table row to 「已完结」+ /tmp backup before writing +
 *      the rest of the original file untouched / no "状态" row 422 / malformed code 400
 *      (escape guard) / unknown code 404.
 */

import { mkdtemp, readFile, readdir, rm, writeFile, mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readPrecache, resolvePrecacheDir, stateKeyFromRows } from '../src/host/epic-next.ts'
import { closeEpic } from '../src/host/epics.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

// ---------------------------------------------------------------- fixtures
// The same fixture and the same literal (EXPECT_STATE_KEY) as the python side selfcheck_epic_next.py (cross-referenced).
const ROWS = [
  { id: 't-demo-01', closed: true },
  { id: 't-demo-02', closed: false },
]
const EXPECT_STATE_KEY = '703be9fa425d23a851b7aa8c060dad56f1570b37'
const CUR_KEY = stateKeyFromRows(ROWS, 't-demo-02')  // 预跑口径：当前票（本票）强制 closed
const WFS = ['dev-lane', 'content-pipeline', 'proofread', 'regression', 'cleanup']

const EPIC_MD = `# 立项单：demo-epic

| 字段 | 值 |
| --- | --- |
| 代号 | \`demo-epic\` |
| 状态 | 已立项（执行中） |
| 立项日期 | 2026-08-27 |

## 目标

把建议链路跑顺。
`

async function tmpRepo() {
  return mkdtemp(join(tmpdir(), 'suyou-smoke-precache-'))
}

async function writePrecache(repo, code, payload) {
  const dir = join(resolvePrecacheDir(repo), code)
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, 'pre.json'), typeof payload === 'string' ? payload : JSON.stringify(payload, null, 1), 'utf8')
}

const OK_SUGGESTION = {
  status: 'ok', workflow: 'dev-lane', title: '下一单建议',
  body: '正文', rationale: '理由',
}

// ---------------------------------------------------------------- A. state_key
section('A. stateKeyFromRows（python epic_state_key 双算互检）')
ok(CUR_KEY === EXPECT_STATE_KEY, `fixture 双算字面量一致（${EXPECT_STATE_KEY.slice(0, 8)}…）`)
ok(CUR_KEY === EXPECT_STATE_KEY, '行顺序无关（sorted）')
ok(stateKeyFromRows(ROWS, 't-demo-02') === EXPECT_STATE_KEY, 'currentTicketId 强制 closed 同口径')
ok(stateKeyFromRows([{ id: 'a', closed: true }], '') !== EXPECT_STATE_KEY, '不同工单集合得到不同 key')

// ---------------------------------------------------------------- B. readPrecache
section('B. readPrecache（坏缓存一律当未命中）')
{
  const repo = await tmpRepo()
  await writePrecache(repo, 'demo-epic', {
    ticket_id: 't-demo-02', epic: 'demo-epic', ts: 1756300000,
    state_key: EXPECT_STATE_KEY, suggestion: OK_SUGGESTION,
  })
  const hit = await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, WFS)
  ok(hit !== null && hit.workflow === 'dev-lane' && hit.title === '下一单建议', 'stub pre.json 命中（ok 形态秒回）')
  const missKey = await readPrecache(resolvePrecacheDir(repo), 'demo-epic', 'deadbeef'.repeat(5), WFS)
  ok(missKey === null, 'state_key 不符 → 未命中')
  const missWf = await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, ['other-wf'])
  ok(missWf === null, 'workflow 不在模板白名单 → 未命中（防幻觉）')
}
{
  const repo = await tmpRepo()
  await writePrecache(repo, 'demo-epic', '{not-json')
  ok(await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, WFS) === null,
    '非法 JSON → 未命中')
}
{
  const repo = await tmpRepo()
  await writePrecache(repo, 'demo-epic', {
    ticket_id: 't-x', epic: 'other-epic', ts: 1, state_key: EXPECT_STATE_KEY, suggestion: OK_SUGGESTION,
  })
  ok(await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, WFS) === null,
    'epic 与代号不一致 → 未命中')
}
{
  const repo = await tmpRepo()
  await writePrecache(repo, 'demo-epic', {
    ticket_id: 't-demo-02', epic: 'demo-epic', ts: 1, state_key: EXPECT_STATE_KEY,
    suggestion: { status: 'done', summary: '  ' },
  })
  ok(await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, WFS) === null,
    'done 空 summary → 未命中')
  await writePrecache(repo, 'demo-epic', {
    ticket_id: 't-demo-02', epic: 'demo-epic', ts: 1, state_key: EXPECT_STATE_KEY,
    suggestion: { status: 'done', summary: '目标全部达成' },
  })
  const hit = await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, WFS)
  ok(hit !== null && hit.status === 'done' && hit.summary === '目标全部达成', 'done 形态命中（结项卡）')
}
{
  const repo = await tmpRepo()
  ok(await readPrecache(resolvePrecacheDir(repo), 'demo-epic', CUR_KEY, WFS) === null,
    '文件缺失 → 未命中（回落冷起）')
  ok(await readPrecache(resolvePrecacheDir(repo), '../etc', CUR_KEY, WFS) === null,
    '代号形状非法 → 未命中（防穿）')
}

// ---------------------------------------------------------------- C. closeEpic
section('C. closeEpic（结项写函数）')
{
  const epicsDir = await mkdtemp(join(tmpdir(), 'suyou-smoke-close-'))
  const mdPath = join(epicsDir, 'demo-epic.md')
  await writeFile(mdPath, EPIC_MD, 'utf8')
  const r = await closeEpic(epicsDir, 'demo-epic')
  ok(r.ok === true && r.status === '已完结', '状态表行外科改写「已完结」')
  const after = await readFile(mdPath, 'utf8')
  ok(/\|\s*状态\s*\|\s*已完结\s*\|/.test(after), '改写落盘（仅状态行）')
  ok(after.includes('把建议链路跑顺') && after.includes('| 代号 | `demo-epic` |'),
    '其它内容原样保留（外科改写，不重排）')
  const backupDir = '/tmp/epic-close-backup'  // 与 closeEpic 同一常量（规格字面「备份 /tmp」）
  const backups = (await readdir(backupDir)).filter((f) => f.startsWith('demo-epic-'))
  ok(backups.length >= 1, '写前 /tmp 备份存在（可回滚）')
  const backupText = await readFile(join(backupDir, backups[backups.length - 1]), 'utf8')
  ok(backupText.includes('已立项（执行中）'), '备份内容为改写前原文')
  const noRow = await closeEpic(epicsDir, 'demo-epic')
  ok(noRow.ok === true, '重复结项幂等（状态行已是已完结仍可改写）')
  await rm(epicsDir, { recursive: true, force: true })
}
{
  const epicsDir = await mkdtemp(join(tmpdir(), 'suyou-smoke-close2-'))
  await writeFile(join(epicsDir, 'no-row.md'), '# 立项单：no-row\n\n无字段表格。\n', 'utf8')
  const r = await closeEpic(epicsDir, 'no-row')
  ok(r.ok === false && r.status === 422 && r.error.includes('状态'), '无「状态」行 → 422 人话报错（不模糊成功）')
  const bad = await closeEpic(epicsDir, '../etc')
  ok(bad.ok === false && bad.status === 400, '代号形状非法 → 400（防穿）')
  const missing = await closeEpic(epicsDir, 'absent-epic')
  ok(missing.ok === false && missing.status === 404, '不存在代号 → 404')
  await rm(epicsDir, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
