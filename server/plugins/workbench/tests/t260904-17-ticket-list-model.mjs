// t260904-17 工单列表行卡纯函数层 UT（ticket-list-model.ts 真值表 + 零硬编码守卫）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  deriveTicketState, STATE4_LABEL, epicColorOf, EPIC_PALETTE, EPIC_FALLBACK_COLOR,
  stageShortOf, progressLineOf, laneDots, filterRows, countByState, relativeTime, toMillis,
  ticketMergeTierOf,
} from '../src/client/ticket-list-model.ts'

const repo = resolveRepo()
function resolveRepo() {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
}
let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${name}`) }

/* ------------------------------------------------ 四态映射真值表（含 R8 缺省行） */

ok('四态映射：closed 优先 / blocked / waiting / active 各归位', () => {
  assert.equal(deriveTicketState('closed', 'awaiting'), 'done')       // 迁移 legacy：closed 优先
  assert.equal(deriveTicketState('closed', 'blocked'), 'done')
  assert.equal(deriveTicketState('open', 'blocked'), 'blocked')
  assert.equal(deriveTicketState('open', 'awaiting-human'), 'waiting')
  assert.equal(deriveTicketState('open', 'running'), 'active')
  assert.equal(deriveTicketState('open', 'awaiting'), 'active')
})

ok('四态映射：未知/新增 stage_state → active 缺省（宁显活跃勿假警报）+ 畸形不 throw', () => {
  assert.equal(deriveTicketState('open', 'some_future_state'), 'active')
  assert.equal(deriveTicketState(undefined, undefined), 'active')
  assert.equal(deriveTicketState('', ''), 'active')
  assert.equal(deriveTicketState(123, {}), 'active')
})

// t260919-02 伴生改（只增不放宽，票面点名）：STATE4_LABEL 词表增 failed:'已失败'。
ok('五态短名表齐备（等你/受阻/在飞/收口/已失败，mock ⑥ chips 词表 + t260919-02）', () => {
  assert.deepEqual(STATE4_LABEL, {
    active: '在飞', done: '收口', waiting: '等你', blocked: '受阻', failed: '已失败',
  })
})

ok('五态短名两两互异（「已失败」不与在飞/收口/受阻/等你混同，t260919-02 验收①）', () => {
  const labels = Object.values(STATE4_LABEL)
  assert.equal(new Set(labels).size, labels.length)
})

/* ---------------------------------------- 五态推导真值表（t260919-02，验收①UI 面） */

ok('五态：失败类终态 exec_status → failed（FAILED/CANCELED/TIMED_OUT/未知新终态补集口径）', () => {
  assert.equal(deriveTicketState('dispatched', 'running', 'FAILED'), 'failed')
  assert.equal(deriveTicketState('dispatched', 'running', 'CANCELED'), 'failed')
  assert.equal(deriveTicketState('dispatched', 'running', 'TIMED_OUT'), 'failed')
  assert.equal(deriveTicketState('open', 'awaiting', 'SOME_NEW_TERMINAL_STATE'), 'failed')
  // 死票不被快照遗留 closed 词面误归收口（失败类终态 > 词面 closed）
  assert.equal(deriveTicketState('closed', 'awaiting', 'FAILED'), 'failed')
  // 与 running 可区分、且不与 done 混同
  assert.notEqual(deriveTicketState('failed', 'failed', 'FAILED'), 'active')
  assert.notEqual(deriveTicketState('failed', 'failed', 'FAILED'), 'done')
})

ok('五态：活/成白名单 exec_status → 沿用四态旧值（逐条不变，零回归）', () => {
  assert.equal(deriveTicketState('open', 'running', 'RUNNING'), 'active')
  assert.equal(deriveTicketState('closed', 'awaiting', 'COMPLETED'), 'done')
  assert.equal(deriveTicketState('open', 'blocked', 'RUNNING'), 'blocked')
  assert.equal(deriveTicketState('open', 'awaiting-human', 'RUNNING'), 'waiting')
  assert.equal(deriveTicketState('open', 'running', 'CONTINUED_AS_NEW'), 'active')
})

/* ---------------------------------------- 终态对账（t260921-03，实案 t260920-02/t260921-01） */

ok('终态对账：COMPLETED → done 先于一切词面（快照遗留 blocked/running 词面永不胜出）', () => {
  // 实案复现用例②：面快照 blocked + 工作流 COMPLETED → 行不得显 blocked
  assert.equal(deriveTicketState('blocked', 'blocked', 'COMPLETED'), 'done')
  // 陈旧在跑词面同查抹平（已完成≠在跑）
  assert.equal(deriveTicketState('dispatched', 'running', 'COMPLETED'), 'done')
  assert.equal(deriveTicketState('settled', 'awaiting-human', 'COMPLETED'), 'done')
  // 真 closed 行为不变（旧值零回归）
  assert.equal(deriveTicketState('closed', 'done', 'COMPLETED'), 'done')
})

ok('五态：exec_status 缺失/空/畸形 → 四态旧值逐条不变（畸形按缺失处理不 throw）', () => {
  assert.equal(deriveTicketState('open', 'running'), 'active')
  assert.equal(deriveTicketState('open', 'running', undefined), 'active')
  assert.equal(deriveTicketState('open', 'running', ''), 'active')
  assert.equal(deriveTicketState('closed', 'awaiting', ''), 'done')
  assert.equal(deriveTicketState('open', 'running', null), 'active')
  assert.equal(deriveTicketState('open', 'running', 42), 'active')
  assert.equal(deriveTicketState('open', 'running', {}), 'active')
})

ok('五态断链防御（review①）：status/stage_state 词面 failed → failed（exec_status 键断链不复发在飞）', () => {
  assert.equal(deriveTicketState('failed', 'failed'), 'failed')
  assert.equal(deriveTicketState('dispatched', 'failed'), 'failed')
  assert.equal(deriveTicketState('failed', 'running'), 'failed')
  // 非失败词面零误伤（旧值逐条不变）
  assert.equal(deriveTicketState('dispatched', 'running'), 'active')
  assert.equal(deriveTicketState('open', 'blocked'), 'blocked')
})

/* ------------------------------------------------ epic 哈希色（R7：确定性 + F2 教训） */

// fixture epic 名册：notes/epics/ 真实四枚代号固化（不动态读名册追现实）。
const FIXTURE_EPICS = ['doc-lifecycle', 'engine-hardening', 'project-lifecycle', 'session-entry']

ok('哈希色确定性：同码恒同色，与他 epic 增删无关（验收②）', () => {
  const a = epicColorOf('session-entry')
  assert.equal(a, epicColorOf('session-entry'))
  // 增删别的 epic 前后同码同色（纯函数无状态的结构性保证，显式断言看住回归）
  const before = FIXTURE_EPICS.map(epicColorOf)
  const withExtra = [...FIXTURE_EPICS, 'zz-temp-epic'].map(epicColorOf)
  assert.deepEqual(before, withExtra.slice(0, FIXTURE_EPICS.length))
})

ok('F2 教训回归：fixture 名册两两异槽（真实代号不重演纯 FNV 撞槽事故）', () => {
  const slots = FIXTURE_EPICS.map(c => epicColorOf(c))
  assert.equal(new Set(slots).size, FIXTURE_EPICS.length,
    `fixture epic 出现同槽撞色：${FIXTURE_EPICS.map((c, i) => `${c}=${slots[i]}`).join(' ')}`)
})

ok('哈希色值域：全部落在 10 色板内', () => {
  for (const code of ['a', 'zz', 'epic-x', 'long-code-'.repeat(4), '项目生命周期']) {
    assert.ok(EPIC_PALETTE.includes(epicColorOf(code)), `${code} 不在色板内`)
  }
})

ok('畸形 epic 代号 → 兜底灰（空/非字符串/超长）', () => {
  for (const bad of [undefined, null, '', '   ', 42, {}, 'x'.repeat(65)]) {
    assert.equal(epicColorOf(bad), EPIC_FALLBACK_COLOR)
  }
})

/* ------------------------------------------------ 阶段短名（C2 消费点在行卡 title/进展行） */

ok('阶段短名：short 声明优先 / 缺省截断 4 字＋… / 短名不截', () => {
  assert.equal(stageShortOf({ id: 's', name: '实现', short: '实现步' }), '实现步')
  assert.equal(stageShortOf({ id: 's', name: '集成场景设计' }), '集成场景…')
  assert.equal(stageShortOf({ id: 's', name: '实现' }), '实现')
  assert.equal(stageShortOf({ id: 's', name: '  审批  ' }), '审批')
})

ok('阶段短名畸形：非对象/无名/空名 → 空（不 throw）', () => {
  for (const bad of [undefined, null, 42, 'x', {}, { id: 's' }, { name: '' }, { name: '   ' }]) {
    assert.equal(stageShortOf(bad), '')
  }
})

/* ------------------------------------------------ 进展行（R8③ 未知 state → undefined） */

ok('进展行：timeline 末条映射人话（表驱动）', () => {
  assert.deepEqual(progressLineOf([{ stage: 'a', state: 'running', at: 'x' }]), { state: 'running', text: '执行中' })
  assert.deepEqual(progressLineOf([
    { stage: 'a', state: 'running' },
    { stage: 'b', state: 'awaiting-human' },
  ]), { state: 'awaiting-human', text: '等你签字' })
  assert.deepEqual(progressLineOf([{ stage: 'b', state: 'blocked' }]), { state: 'blocked', text: '受阻 · 原因见详情' })
})

ok('进展行畸形：末条畸形向前跳 / 全畸形/缺/非数组/空 → undefined', () => {
  assert.deepEqual(progressLineOf([{ state: 'running' }, null, { stage: 'b', state: 'done' }]),
    { state: 'done', text: '本步已完成' })
  assert.equal(progressLineOf(undefined), undefined)
  assert.equal(progressLineOf([]), undefined)
  assert.equal(progressLineOf('nope'), undefined)
  assert.equal(progressLineOf([42, null, {}]), undefined)
})

ok('进展行：未知引擎 state → undefined（引擎词不得漏进 UI 文案）', () => {
  assert.equal(progressLineOf([{ stage: 'x', state: 'some_future_state' }]), undefined)
  assert.equal(progressLineOf([{ stage: 'x', state: '' }]), undefined)
})

/* ------------------------------------------------ 迷你站道（R8② 三边缘） */

const wf2 = { id: 'wf-a', stages: [{ id: 's1', name: '一' }, { id: 's2', name: '二' }, { id: 's3', name: '三' }] }
const wf5 = {
  id: 'wf-b',
  stages: [{ id: 'p1', name: '甲' }, { id: 'p2', name: '乙' }, { id: 'p3', name: '丙' }, { id: 'p4', name: '丁' }, { id: 'p5', name: '戊' }],
}

ok('站道点数=模板阶段数（≥2 模板各一例，验收③模型面）', () => {
  assert.equal(laneDots(wf2, { status: 'open', stage: 's2' }).length, 3)
  assert.equal(laneDots(wf5, { status: 'open', stage: 'p1' }).length, 5)
})

ok('站道：已过=done / 当前=current / 未来=todo', () => {
  assert.deepEqual(laneDots(wf2, { status: 'open', stage: 's2' }), ['done', 'current', 'todo'])
  assert.deepEqual(laneDots(wf2, { status: 'open', stage: 's1' }), ['current', 'todo', 'todo'])
})

ok('站道边缘：closed 全 done / stage=null 全 todo / 指针漂移全 todo / wf 缺失 []', () => {
  assert.deepEqual(laneDots(wf2, { status: 'closed', stage: 's1' }), ['done', 'done', 'done'])
  assert.deepEqual(laneDots(wf2, { status: 'open', stage: null }), ['todo', 'todo', 'todo'])
  assert.deepEqual(laneDots(wf2, { status: 'open', stage: 'ghost' }), ['todo', 'todo', 'todo'])
  assert.deepEqual(laneDots(undefined, { status: 'open', stage: 's1' }), [])
  assert.deepEqual(laneDots({ id: 'x', stages: [] }, { status: 'open', stage: 's1' }), [])
})

/* ------------------------------------------------ 筛选 / 计数 */

const ROWS = [
  { id: 't-1', title: '修好第一句话不上屏', epic: 'session-entry', status: 'open', stage_state: 'awaiting-human' },
  { id: 't-2', title: '让测试老实亮红', epic: 'engine-hardening', status: 'open', stage_state: 'blocked' },
  { id: 't-3', title: '项目可接入也可移出', epic: 'project-lifecycle', status: 'open', stage_state: 'running' },
  { id: 't-4', title: '已收口的旧票', epic: 'doc-lifecycle', status: 'closed', stage_state: 'awaiting' },
]

ok('chips=过滤非分组：四态按归并态筛（closed 旧票归收口非待分派）', () => {
  assert.deepEqual(filterRows(ROWS, { state: 'waiting' }).map(r => r.id), ['t-1'])
  assert.deepEqual(filterRows(ROWS, { state: 'blocked' }).map(r => r.id), ['t-2'])
  assert.deepEqual(filterRows(ROWS, { state: 'active' }).map(r => r.id), ['t-3'])
  assert.deepEqual(filterRows(ROWS, { state: 'done' }).map(r => r.id), ['t-4'])
  assert.equal(filterRows(ROWS, { state: '' }).length, 4)
})

ok('chips：epic 精确筛 + 搜索大小写不敏感匹配 id+标题', () => {
  assert.deepEqual(filterRows(ROWS, { epic: 'session-entry' }).map(r => r.id), ['t-1'])
  assert.deepEqual(filterRows(ROWS, { q: '亮红' }).map(r => r.id), ['t-2'])
  assert.deepEqual(filterRows(ROWS, { q: 'T-1' }).map(r => r.id), ['t-1'])
  assert.deepEqual(filterRows(ROWS, { epic: 'session-entry', q: '不存在' }), [])
})

// t260919-02 伴生改（只增不放宽，票面点名）：countByState 返回形状增 failed 键。
ok('chips 计数：countByState Σ=行数（收口折叠计数行数据源）', () => {
  const c = countByState(ROWS)
  assert.deepEqual(c, { active: 1, done: 1, waiting: 1, blocked: 1, failed: 0 })
  assert.equal(c.active + c.done + c.waiting + c.blocked + c.failed, ROWS.length)
})

// t260919-02：失败票进 failed 桶（不进 active/done 的显式失败态，验收①对照面）。
const ROWS5 = [
  ...ROWS,
  { id: 't-5', title: '终态失败票', epic: 'engine-hardening', status: 'failed', stage_state: 'failed', exec_status: 'FAILED' },
]

ok('五态 chips：失败票过滤进 failed 桶、计数五键齐全（t260919-02）', () => {
  assert.deepEqual(filterRows(ROWS5, { state: 'failed' }).map(r => r.id), ['t-5'])
  assert.deepEqual(filterRows(ROWS5, { state: 'active' }).map(r => r.id), ['t-3'])
  assert.deepEqual(filterRows(ROWS5, { state: 'done' }).map(r => r.id), ['t-4'])
  const c = countByState(ROWS5)
  assert.deepEqual(c, { active: 1, done: 1, waiting: 1, blocked: 1, failed: 1 })
  assert.equal(c.active + c.done + c.waiting + c.blocked + c.failed, ROWS5.length)
})

ok('五态 tier 投影：失败票 tier0 置顶（等你/受阻同档）、活/成不误伤（t260919-02）', () => {
  assert.equal(ticketMergeTierOf('dispatched', 'running', 'FAILED'), 0)
  assert.equal(ticketMergeTierOf('dispatched', 'running', 'CANCELED'), 0)
  assert.equal(ticketMergeTierOf('failed', 'failed'), 0)
  // exec_status 键断链时词面 failed 同样 tier0（与推导断链防御同源）
  assert.equal(ticketMergeTierOf('dispatched', 'failed', undefined), 0)
  // 活/成/收口不误伤（t260916-15 旧值逐条不变；t260921-03 拆档：正常收口 2→3，
  // 异常收口插层 tier2——有意更新，根因见 t260916-15 UT 同名注释）
  assert.equal(ticketMergeTierOf('dispatched', 'running', 'RUNNING'), 1)
  assert.equal(ticketMergeTierOf('closed', 'awaiting', 'COMPLETED'), 3)
  assert.equal(ticketMergeTierOf('closed', 'awaiting', 'FAILED'), 0)
})

/* ------------------------------------------------ 相对时间（R8④ 畸形 → null） */

const NOW = Date.parse('2026-09-04T12:00:00Z')
ok('toMillis 接线归一（F2 回归用例）：秒→×1000 / 毫秒原样 / 畸形透传', () => {
  const nowS = Math.floor(Date.now() / 1000)
  assert.equal(toMillis(nowS), nowS * 1000)                    // 引擎 updated_ts=秒（F2 错显根因）
  assert.equal(toMillis(nowS * 1000), nowS * 1000)             // 侧栏已 ×1000 的毫秒不动
  assert.equal(toMillis(1e11), 1e11)                           // 量级边界：1e11=毫秒域
  assert.equal(toMillis(1e11 - 1), (1e11 - 1) * 1000)          // 秒域
  for (const bad of [undefined, null, NaN, 'x']) {
    assert.ok(toMillis(bad) !== toMillis(bad) || toMillis(bad) === bad || toMillis(bad) === null,
      `畸形 ${String(bad)} 透传 relativeTime 兜底`)
  }
  assert.equal(relativeTime(toMillis(nowS - 120)), '2 分钟前')  // 接线端到端：秒入→人话出
})

ok('相对时间：刚刚/分钟/小时/天 四档', () => {
  assert.equal(relativeTime(NOW - 10_000, NOW), '刚刚')
  assert.equal(relativeTime(NOW - 5 * 60_000, NOW), '5 分钟前')
  assert.equal(relativeTime(NOW - 3 * 3_600_000, NOW), '3 小时前')
  assert.equal(relativeTime(NOW - 2 * 86_400_000, NOW), '2 天前')
})

ok('相对时间畸形：缺失/非数/非正数/未来超容差 → null（行卡回落绝对时间）', () => {
  for (const bad of [undefined, null, NaN, 0, -5, 'x', NOW + 61_000]) {
    assert.equal(relativeTime(bad, NOW), null)
  }
  assert.equal(relativeTime(NOW + 30_000, NOW), '刚刚') // 1min 内时钟漂移容差
})

/* ------------------------------------------------ 零硬编码守卫（C3 形态 b：整文件扫描＋显式豁免数组） */

// 禁词=dev-lane 段名常量（引擎通用状态词 running/awaiting-human/blocked/closed 不属禁列，
// dispatch-next/advance 等操作词亦不属禁列——禁的是「流程段名」不是「操作/状态」）。
const BANNED_TOKENS = [
  'create_plan', 'review_plan', 'implement', 'integration_scene', 'arbitrate',
  'acceptance_walkthrough', 'merge_check', 'parallel_impl_design',
]
// 扫描范围=本票列表面四文件（整文件扫描，不按行号段——行号随编辑漂移会假红/假绿）。
const SCAN_FILES = [
  'src/client/ticket-list-model.ts',
  'src/client/ticket-row-card.tsx',
  'src/client/index.tsx',
  'src/client/sidebar.tsx',
]
// 豁免=存量字面量（本票之前的详情面文案，理由各注；扩清单须改本测试=有意识行为）。
const EXEMPT_LITERALS = [
  'merge_check 等脚本门不落 results 也能打勾',   // index.tsx 步骤条注释（存量）
  'merge_check 等程序化门的一次运行记录',         // index.tsx 类型注释（存量）
  '（merge_check 全绿）',                        // index.tsx 详情状态行文案（存量）
  '最近一次 merge_check 红',                     // index.tsx 问题区注释（存量）
  'merge_check 红：',                            // index.tsx 问题区文案（存量）
]

ok('零硬编码守卫：列表面四文件禁现 dev-lane 段名常量（豁免清单显式化）', () => {
  for (const rel of SCAN_FILES) {
    const src = readFileSync(join(repo, 'server/plugins/workbench', rel), 'utf8')
    const lines = src.split('\n')
    lines.forEach((line, i) => {
      // 豁免行：含任一显式豁免字面量则整行放行（存量文案不动，本票不新增同类字面量）
      if (EXEMPT_LITERALS.some(lit => line.includes(lit))) return
      for (const tok of BANNED_TOKENS) {
        const re = new RegExp(`\\b${tok}\\b`)
        assert.ok(!re.test(line), `${rel}:${i + 1} 出现禁词「${tok}」：${line.trim().slice(0, 80)}`)
      }
    })
  }
})

console.log(`t260904-17-ticket-list-model all ${n} groups passed`)
