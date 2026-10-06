/**
 * smoke/project-sessions.mjs — smoke for the per-project session area (session-entry surface 3.1, R1-R6).
 *
 * Run: node smoke/project-sessions.mjs (node >= 22.18 native type-stripping; pure functions
 * imported from .ts directly; React components cannot run in node — covered by source-text
 * assertions, the hero.mjs precedent).
 *
 * Covers two layers:
 *   A. Pure-function layer (the new surface 3.1 of src/shared/sessions.ts):
 *      pickProjectTabs (filter by project / ascending seq / no cap / active unique in three
 *      states / three-level title fallback / ticket- defense / entries missing a seq are
 *      not shown / malformed input)
 *      backfillProjectSeqs (assign seqs in registration order / idempotent, input reference
 *      unchanged / does not mutate its argument / interleaved state continues from the
 *      project's max seq / projects independent)
 *      nextProjectSeq (counter vs ledger max+1 / counter-missing fallback / malformed tolerance)
 *      no-seq-recycling chain (closing #2 keeps 1 and 3 at their numbers; a new registration
 *      continues at 4 — the core regression of decision 1)
 *   B. Source-text layer (src/client/project-session-row.tsx + sidebar.tsx +
 *      session-entry.tsx + the lib/client.js artifact):
 *      - no horizontal scroll on wrap (R2): flex-wrap:wrap present, no overflow-x:scroll/auto;
 *      - the confirm dialog (R5): the full data-wb-psess-confirm/-ok/-cancel anchor set
 *        present; no native confirm( calls; position:fixed present (C1: the scroll-container
 *        clipping countermeasure);
 *      - highlight (R6): the data-wb-psess-tab[data-active] anchor present;
 *      - semantic-anchor discipline: no [class*= or [class$= factory-class-name matching
 *        selectors;
 *      - wiring present: sidebar renders ProjectSessionRow + the backfill mount effect;
 *        session-entry registers seqs (nextProjectSeq/backfillProjectSeqs call sites);
 *      - ticket 2 R7/R8 (t260904-05): project color (+ button / active tab / group-header
 *        color dot / right-rail color band anchors), top-row retirement inversion (the
 *        wb-sessTop family absent), the confirm text without the ↺ wording;
 *      - the lib artifact carries the same batch (the anchors are present in lib/client.js too).
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  parseLedger,
  serializeLedger,
  touchEntry,
  removeEntry,
  pickProjectTabs,
  backfillProjectSeqs,
  nextProjectSeq,
} from '../src/shared/sessions.ts'

const here = dirname(fileURLToPath(import.meta.url))
const srcRow = join(here, '..', 'src', 'client', 'project-session-row.tsx')
const srcSidebar = join(here, '..', 'src', 'client', 'sidebar.tsx')
const srcEntry = join(here, '..', 'src', 'client', 'session-entry.tsx')
const libClient = join(here, '..', 'lib', 'client.js')

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** Build one ledger entry (lastOpenedAt given directly as an ordinal, larger = newer = registered later). */
function ent(id, extra = {}) {
  return { id, project: 'suyou', cwd: '/repo/suyou', lastOpenedAt: 0, ...extra }
}

/* A. Pure-function layer */

section('A1 pickProjectTabs：按项目过滤 + seq 升序 + 无上限')
{
  const ledger = [
    ent('c', { seq: 3, lastOpenedAt: 30 }),
    ent('a', { seq: 1, lastOpenedAt: 10 }),
    ent('b', { seq: 2, lastOpenedAt: 20 }),
    ent('x', { project: 'sandbar', seq: 1, lastOpenedAt: 15 }),
  ]
  const r = pickProjectTabs(ledger, { project: 'suyou' })
  ok(r.length === 3 && r.map(t => t.id).join(',') === 'a,b,c', '按 project 过滤 + seq 升序（他项目条目不出现）')
  ok(r.every(t => t.project === undefined), 'ProjectTab 只含渲染面字段')
  // No cap (decision 2): 21 entries (>LEDGER_CAP 20) all join the sort
  const many = Array.from({ length: 21 }, (_, i) => ent(`s${i}`, { seq: i + 1 }))
  ok(pickProjectTabs(many, { project: 'suyou' }).length === 21, '数量不限：21 条全量参排（tab 无上限）')
  // Malformed: non-array / empty-string project / non-string project
  ok(pickProjectTabs(null, { project: 'suyou' }).length === 0, '账册非数组 → 空列表不抛')
  ok(pickProjectTabs(ledger, {}).length === 0, 'project 缺省 → 空列表')
  ok(pickProjectTabs(ledger, { project: 123 }).length === 0, 'project 非字符串 → 空列表')
  // Entries with a missing/bad seq are not shown (the backfill-first invariant)
  const gap = [ent('a', { seq: 1 }), ent('noseq'), ent('bad', { seq: Number.NaN }), ent('zero', { seq: 0 })]
  const rg = pickProjectTabs(gap, { project: 'suyou' })
  ok(rg.length === 1 && rg[0].id === 'a', '缺 seq / NaN / 0 号条目不显示')
}

section('A2 pickProjectTabs：active 高亮三态（R6）')
{
  const ledger = [ent('a', { seq: 1 }), ent('b', { seq: 2 })]
  const other = [ent('x', { project: 'sandbar', seq: 1 })]
  const r1 = pickProjectTabs(ledger, { project: 'suyou', current: 'a' })
  ok(r1.filter(t => t.active).length === 1 && r1[0].active === true, 'current 命中本组 → 恰一高亮')
  const r2 = pickProjectTabs(ledger, { project: 'suyou', current: 'x' })
  ok(r2.every(t => !t.active), 'current 是他项目会话 → 本组全不亮')
  const r3 = pickProjectTabs(ledger, { project: 'suyou', current: 'ticket-t9' })
  ok(r3.every(t => !t.active), 'current 是工单会话 → 全不亮')
  const r4 = pickProjectTabs(ledger, { project: 'suyou' })
  ok(r4.every(t => !t.active), '无 current → 全不亮')
}

section('A3 pickProjectTabs：title 三级兜底 + ticket- 防御')
{
  const ledger = [
    ent('a', { seq: 1, title: '自定义名' }),
    ent('b', { seq: 2, title: '   ' }),
    ent('c', { seq: 3 }),
    ent('t', { seq: 4, id: 'ticket-t9' }),
  ]
  const r = pickProjectTabs(ledger, { project: 'suyou', byId: { b: { displayTitle: 'B 标题' }, c: { displayTitle: '' } } })
  ok(r.find(t => t.id === 'a')?.title === '自定义名', '自定义 title 优先')
  ok(r.find(t => t.id === 'b')?.title === 'B 标题', '空白 title 走 displayTitle 兜底')
  ok(r.find(t => t.id === 'c')?.title === 'c', 'displayTitle 缺失兜底 id')
  ok(!r.some(t => t.id === 'ticket-t9'), 'ticket- 工单会话不进 tab（防御纵深）')
}

section('B1 backfillProjectSeqs：登记顺序补号（拍板 1 存量迁移）')
{
  // Ledger array order = newest first (touchEntry prepends); backfill sorts by ascending lastOpenedAt = registration order
  const ledger = [ent('c', { lastOpenedAt: 30 }), ent('a', { lastOpenedAt: 10 }), ent('b', { lastOpenedAt: 20 })]
  const snapshot = JSON.stringify(ledger)
  const out = backfillProjectSeqs(ledger)
  const byId = Object.fromEntries(out.map(e => [e.id, e.seq]))
  ok(byId.a === 1 && byId.b === 2 && byId.c === 3, '补号=项目内登记顺序（oldest→1）')
  ok(JSON.stringify(ledger) === snapshot, '不改入参')
  // Idempotent: with no gaps it returns the input reference unchanged (the caller skips persist based on this)
  const again = backfillProjectSeqs(out)
  ok(again === out, '幂等：二次跑返回入参引用（免 persist 判据）')
  // Projects backfill independently
  const multi = [ent('s1', { lastOpenedAt: 5 }), ent('k1', { project: 'sandbar', lastOpenedAt: 3 }), ent('s2', { lastOpenedAt: 8 }), ent('k2', { project: 'sandbar', lastOpenedAt: 6 })]
  const mo = backfillProjectSeqs(multi)
  const m = Object.fromEntries(mo.map(e => [e.id, e.seq]))
  ok(m.s1 === 1 && m.s2 === 2 && m.k1 === 1 && m.k2 === 2, '多项目各自从 1 起独立补号')
  // Interleaved state (abnormal-path defense): with seq 5 already taken in a project, a gap entry continues from 6 (no-reuse wins)
  const mixed = [ent('old', { seq: 5 }), ent('gap', { lastOpenedAt: 99 })]
  const mm = backfillProjectSeqs(mixed)
  ok(mm.find(e => e.id === 'gap')?.seq === 6, '交错态：缺号从项目内现存最大号之上续（不重号）')
  // Malformed: non-array / missing lastOpenedAt ties broken stably by array position
  ok(Array.isArray(backfillProjectSeqs('bad')) === false || backfillProjectSeqs(null).length === 0, '非数组入参容错为空')
  const tie = [ent('p', { lastOpenedAt: 0 }), ent('q', { lastOpenedAt: 0 })]
  const to = backfillProjectSeqs(tie)
  ok(to.find(e => e.id === 'p')?.seq === 1 && to.find(e => e.id === 'q')?.seq === 2, 'lastOpenedAt 并列按数组位置稳定破平')
}

section('B2 nextProjectSeq：计数器与账册取 max+1（拍板 1 续号）')
{
  const ledger = [ent('a', { seq: 3 })]
  ok(nextProjectSeq(ledger, 'suyou', 6) === 7, '计数器 6 > 账册 3 → 取 7')
  ok(nextProjectSeq(ledger, 'suyou') === 4, '无计数器 → 账册最大 3 续 4（计数器丢失兜底）')
  ok(nextProjectSeq(ledger, 'suyou', 2) === 4, '计数器落后 → 仍取账册最大+1（不重号）')
  ok(nextProjectSeq([], 'suyou') === 1, '空账册无计数器 → 1')
  ok(nextProjectSeq(ledger, 'sandbar') === 1, '他项目条目不参与本项目续号')
  ok(nextProjectSeq(ledger, 'suyou', Number.NaN) === 4, '计数器 NaN 容错按 0')
  ok(nextProjectSeq(ledger, 'suyou', -5) === 4, '计数器负数容错按 0')
  ok(nextProjectSeq(null, 'suyou', 9) === 10, '账册非数组容错')
}

section('B3 nextProjectSeq closed 号域（BO-1：已关最大号不重发）')
{
  const ledger = [ent('a', { seq: 3 })]
  const closed = [ent('gone', { seq: 30 }), ent('other', { project: 'sandbar', seq: 88 })]
  // Counter present (> closed max): closed entries do not pull it down (the max semantics unchanged)
  ok(nextProjectSeq(ledger, 'suyou', undefined, closed) === 31, 'BO-1：计数器丢失时已关 30 号不重发（续 31）')
  // Counter present (>closed max) keeps closed from lowering it (max semantics unchanged)
  ok(nextProjectSeq(ledger, 'suyou', 35, closed) === 36, '计数器 35 > closed 30 → 36（max 语义）')
  // Counter behind closed (closed 30 > counter 5) -> take 31
  ok(nextProjectSeq(ledger, 'suyou', 5, closed) === 31, '计数器落后 closed → 取 closed 最大+1')
  // Other projects' closed entries participate in their own project domain
  ok(nextProjectSeq(ledger, 'sandbar', undefined, closed) === 89, '他项目 closed 88 参与 sandbar 域（本组口径）')
  // closed malformed: non-array ignored / dirty entries (null, missing project, seq NaN) skipped without crashing
  ok(nextProjectSeq(ledger, 'suyou', undefined, 'bad') === 4, 'closed 非数组忽略（账册兜底 4）')
  ok(nextProjectSeq(ledger, 'suyou', undefined, [null, { id: 'x', seq: Number.NaN }, ent('y', { seq: 9 })]) === 10,
    'closed 脏条目跳过、合法 9 号计入（续 10）')
  // Without closed (the old call surface, journey J4 compatibility): behaves exactly like B2
  ok(nextProjectSeq(ledger, 'suyou', 2) === 4 && nextProjectSeq(ledger, 'suyou', 9) === 10,
    'closed 缺省=旧口径不变（J4 兼容面）')
}

section('C1 编号不回收全链（拍板 1 核心回归：关 2 号 → 1/3 保留；新登记续 4）')
{
  // Scenario: project suyou has 3 sessions registered (seq 1/2/3); close #2; then create one more.
  let ledger = [
    ent('s1', { seq: 1, lastOpenedAt: 10 }),
    ent('s2', { seq: 2, lastOpenedAt: 20 }),
    ent('s3', { seq: 3, lastOpenedAt: 30 }),
  ]
  let counters = { suyou: 3 }
  // Close #2 (after UI confirmation it goes through removeEntry; the counter is untouched)
  ledger = removeEntry(ledger, 's2')
  const tabs = pickProjectTabs(ledger, { project: 'suyou' })
  ok(tabs.map(t => t.seq).join(',') === '1,3', '关闭 2 号后：1/3 保留原号（不回收）')
  // Register a new one (same chain as handleNew: nextProjectSeq + touchEntry carrying the seq)
  const seq = nextProjectSeq(ledger, 'suyou', counters.suyou)
  counters = { ...counters, suyou: seq }
  ledger = touchEntry(ledger, ent('s4', { seq, lastOpenedAt: 40 }))
  const tabs2 = pickProjectTabs(ledger, { project: 'suyou' })
  ok(tabs2.map(t => t.seq).join(',') === '1,3,4', '新会话续号 4（洞保留）')
  // Unchanged after a serialize round-trip
  const back = parseLedger(serializeLedger(ledger))
  ok(pickProjectTabs(back, { project: 'suyou' }).map(t => t.seq).join(',') === '1,3,4', '持久化往返后编号不变')
  // Reopen the closed #2 (↺: touchEntry carries the original seq): #2 returns to its old slot
  ledger = touchEntry(ledger, ent('s2', { seq: 2, lastOpenedAt: 50 }))
  ok(pickProjectTabs(ledger, { project: 'suyou' }).map(t => t.seq).join(',') === '1,2,3,4', '重开带原号归位（稳定身份）')
  // Counter-missing scenario: only 1/3/4 left, no counter -> the next one still does not reuse a number
  ok(nextProjectSeq(removeEntry(ledger, 's2'), 'suyou') === 5, '计数器丢失时以账册现存最大号兜底续号')
}

section('C2 存量迁移全链（第 3 面① 前登记的条目无 seq）')
{
  const legacy = [
    ent('old3', { lastOpenedAt: 30 }),
    ent('old1', { lastOpenedAt: 10 }),
    ent('other', { project: 'sandbar', lastOpenedAt: 20 }),
    ent('old2', { lastOpenedAt: 20 }),
  ]
  const migrated = backfillProjectSeqs(legacy)
  const suyou = pickProjectTabs(migrated, { project: 'suyou', current: 'old2' })
  ok(suyou.map(t => `${t.id}:${t.seq}`).join(',') === 'old1:1,old2:2,old3:3', '存量按登记序补号并按号升序显示')
  ok(suyou.find(t => t.id === 'old2')?.active === true, '迁移后高亮语义正常（R6）')
  ok(pickProjectTabs(migrated, { project: 'sandbar' }).map(t => t.seq).join(',') === '1', '他项目迁移互不干扰')
  // New registration after migration (same chain as handleNew): continues from the existing max
  const seq = nextProjectSeq(migrated, 'suyou', 0)
  ok(seq === 4, '迁移后新建续 4（存量 1-3 已占）')
}

/* B. Source-text layer (src + lib, both sides) */

section('S1 换行不横滚（R2：flex-wrap 在场，无 overflow-x 横滚）')
{
  const row = readFileSync(srcRow, 'utf8')
  ok(row.includes('flex-wrap:wrap'), '行容器 flex-wrap:wrap 在场（超宽换行）')
  ok(!/overflow-x\s*:\s*(scroll|auto)/.test(row), '无 overflow-x:scroll/auto（不横滚）')
  // The lib side only gets positive assertions: the bundle contains the echarts vendor CSS
  // (which carries its own overflow-x rules), so a bundle-wide negative regex would go red
  // on third-party noise — the "no horizontal scroll" constraint is about this component's
  // own styles, guarded precisely by the src-level negative assertions above.
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('flex-wrap:wrap'), 'lib 产物换行样式在场（同批重建证据）')
}

section('S2 确认框（R5：锚全集 + 非原生 confirm + fixed 定位）')
{
  const row = readFileSync(srcRow, 'utf8')
  for (const anchor of ['data-wb-psess-confirm=', 'data-wb-psess-confirm-ok=', 'data-wb-psess-confirm-cancel=']) {
    ok(row.includes(anchor), `src 锚在场：${anchor}`)
  }
  ok(!/[^a-zA-Z.]confirm\(/.test(row), '无原生 confirm( 调用（插件内轻量弹层）')
  ok(row.includes('position:fixed'), '弹层 position:fixed（C1：滚动容器 .wb-ticket-list 裁剪对策）')
  ok(row.includes('Only the entry is closed; the session content is not deleted'), '确认文案明示「仅关闭入口不删内容」（拍板 3）')
  // The lib-side anchor assertions omit '=': after bundling, JSX attribute names appear as object keys ("data-wb-…":)
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('data-wb-psess-confirm-ok'), 'lib 产物确认锚在场（同批重建证据）')
}

section('S3 方块 tab 与高亮锚（R2/R6）')
{
  const row = readFileSync(srcRow, 'utf8')
  ok(row.includes('data-wb-psess-tab=') && row.includes('data-active='), 'tab 锚 + data-active 高亮锚在场')
  ok(row.includes('data-wb-psess-new='), '+ 新建钮锚在场')
  ok(row.includes('data-wb-psess-close='), '关闭钮锚在场')
  ok(row.includes('box-sizing:border-box') && row.includes('min-width:24px')
    && /width:24px;\s*height:24px/.test(row.replace(/\n/g, ' ')),
    'tab/+ 方块基准：border-box + 24×24（隔离台 DOM 断言校准）')
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('data-wb-psess-tab'), 'lib 产物 tab 锚在场')
}

section('S3b 空态可发现入口（t260906-01：账册空=带字「＋ 新建会话」，有 tab=小方块）')
{
  const row = readFileSync(srcRow, 'utf8')
  ok(row.includes('wb-psess-new-labeled'), 'src 空态带字变体类在场')
  ok(row.includes('＋ 新建会话'), 'src 空态按钮带文字「＋ 新建会话」在场')
  ok(row.includes('tabs.length === 0'), 'src 空态判定=账册 tab 为空')
  ok(row.includes('data-empty='), 'src 空态 data-empty 锚在场')
  // Same-anchor discipline: the empty state and the with-tabs state share data-wb-psess-new (the action chain unchanged)
  ok((row.match(/data-wb-psess-new=/g) || []).length === 1, 'data-wb-psess-new 锚恰一处（两态同钮）')
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('＋ 新建会话') && lib.includes('wb-psess-new-labeled'), 'lib 产物空态带字在场（同批重建证据）')
}

section('S4 语义锚纪律（零出厂类名匹配）')
{
  const row = readFileSync(srcRow, 'utf8')
  ok(!/\[class\*=|\[class\$=/.test(row), '无 [class*= / [class$= 出厂类名匹配选择器')
}

section('S5 接线在场（sidebar 渲染 + 存量迁移 effect + 登记分配 seq）')
{
  const sidebar = readFileSync(srcSidebar, 'utf8')
  ok(sidebar.includes('ProjectSessionRow'), 'sidebar 渲染 ProjectSessionRow')
  ok(sidebar.includes('backfillProjectSeqs') && sidebar.includes('persistLedger'), 'sidebar 挂载 effect：存量补号 + 落盘')
  ok(/useSessionEntry\(\{/.test(sidebar), 'sidebar 二号 useSessionEntry 实例在场')
  const entry = readFileSync(srcEntry, 'utf8')
  ok(entry.includes('SEQ_COUNTER_KEY') && entry.includes('nextProjectSeq') && entry.includes('backfillProjectSeqs'),
    'session-entry：计数器 + 续号 + 补号自愈在场')
  ok(entry.includes('writeSeqCounters({ ...counters, [pk]: seq })'), '登记先写计数器再落账（中断=跳号不重号）')
}

section('S6 顶部行已退役（票② R8 反转断言：顶部行锚不在场）')
{
  const entry = readFileSync(srcEntry, 'utf8')
  const sidebar = readFileSync(join(here, '..', 'src', 'client', 'sidebar.tsx'), 'utf8')
  ok(!entry.includes('wb-sessTop') && !sidebar.includes('wb-sessTop'), '顶部行样式族零残留（src 两文件）')
  ok(!entry.includes('data-wb-session-entry=') && !sidebar.includes('data-wb-session-entry'), '顶部行锚不在场（源）')
  const lib = readFileSync(libClient, 'utf8')
  ok(!lib.includes('data-wb-session-entry') && !lib.includes('wb-sessTop'), 'lib 产物顶部行锚不在场')
}

section('S8 项目色贯通（票② R7 拍板 5：+ 钮/激活 tab/组头色点）')
{
  const row = readFileSync(join(here, '..', 'src', 'client', 'project-session-row.tsx'), 'utf8')
  const sidebar = readFileSync(join(here, '..', 'src', 'client', 'sidebar.tsx'), 'utf8')
  ok(row.includes("--wb-psess-color") && row.includes('projectColor(projectKey)'), '+ 钮/激活 tab 项目色：CSS 变量 + projectColor 注入在场')
  ok(row.includes('--wb-psess-hover') && /hexToRgba\(color, 0\.16\)/.test(row), 'hover/淡底 = 项目色 16% 透明展开')
  ok(!row.includes('124,58,237'), '旧紫色 rgba(124,58,237,*) 已替换')
  // Since UI-4 (t261005-05) the group-head dot is the identity badge (colour x
  // outline x structure from project-identity.ts); the psess-dot anchor stays.
  ok(sidebar.includes('data-wb-psess-dot') && sidebar.includes('projectBadgeSvg('), '组头名前项目徽标在场（data-wb-psess-dot 锚 + projectBadgeSvg 单源）')
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('--wb-psess-color') && lib.includes('data-wb-psess-dot'), 'lib 产物项目色与色点同步')
}

section('S9 右栏色带锚（票② R7 拍板 6：data-wb-chat-projband + 平台自声明锚）')
{
  const band = readFileSync(join(here, '..', 'src', 'client', 'chat-project-band.ts'), 'utf8')
  ok(band.includes("'data-wb-chat-projband'") && band.includes('data-wb-chat-projband-style'), '色带自有属性与 head style 锚在场')
  ok(band.includes("'[data-conversation-scroll]'"), '平台自声明滚动体锚在场（勿用 css-module 类名）')
  ok(band.includes('isProjectKeyLike'), '畸形 key 生产闸门（isProjectKeyLike 前置）在场')
  const sidebar = readFileSync(join(here, '..', 'src', 'client', 'sidebar.tsx'), 'utf8')
  ok(sidebar.includes('startChatProjectBandEffect') && sidebar.includes('setChatProjectBand'), 'sidebar 接线：装饰器挂载 + 归属推导 set 在场')
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('data-wb-chat-projband') && lib.includes('data-conversation-scroll'), 'lib 产物色带锚同步')
}

section('S10 确认文案（票②拍板 2：↺ 表述删除）')
{
  const row = readFileSync(join(here, '..', 'src', 'client', 'project-session-row.tsx'), 'utf8')
  ok(row.includes('Only the entry is closed; the session content is not deleted'), '确认文案明示「仅关闭入口不删内容」')
  ok(!row.includes('↺') && !row.includes('最近关闭找回'), '无 ↺/最近关闭找回表述（恢复菜单已退役）')
  const lib = readFileSync(libClient, 'utf8')
  ok(!lib.includes('最近关闭找回'), 'lib 产物文案同步')
}

section('S7 D1 修复接线：closed 状态迁模块级共享 store（跨实例同帧可见）')
{
  const store = readFileSync(join(here, '..', 'src', 'client', 'closed-ledger-store.ts'), 'utf8')
  for (const sym of ['subscribeClosed', 'getClosedSnapshot', 'persistClosed']) {
    ok(store.includes(`function ${sym}`), `closed-ledger-store 导出 ${sym}`)
  }
  ok(store.includes('subscribers'), '共享 store 有订阅集合（广播面）')
  ok(!/from 'react'/.test(store), 'store 不 import react（node 裸跑纪律）')
  const entry = readFileSync(srcEntry, 'utf8')
  ok(entry.includes('useSyncExternalStore(subscribeClosed, getClosedSnapshot)'),
    'closedList 改共享 store 订阅（不再实例 useState 快照——D1 根因）')
  ok(entry.includes('persistClosed(pushClosedLedger(getClosedSnapshot(), entry))'),
    'handleClose 走 persistClosed（落盘+更新单例+广播）')
  ok(!/refreshClosedList/.test(entry), '惰性刷新兜底已移除（空态死锁路径拆除）')
  ok(entry.includes('nextProjectSeq(base, pk, counters[pk], getClosedSnapshot())'),
    'handleNew 续号兜底纳入 closed 号域（BO-1）')
  const lib = readFileSync(libClient, 'utf8')
  ok(lib.includes('persistClosed'), 'lib 产物共享 store 同批在场')
}

section('S11 UI-5（t261005-06）：句柄标签 + 执行器投影门 + 项目文件登记链')
{
  const row = readFileSync(join(here, '..', 'src', 'client', 'project-session-row.tsx'), 'utf8')
  // Tab main label = the handle short code (data-wb-psess-handle); seq stays only as fallback
  // Post main-sync union (t261005-09 landed on main): the label is the composed
  // handle — an assigned sessions.json handle wins (executor included), else the
  // UI-1 sessionHandle derivation. Both sources must stay in the row.
  ok(row.includes('data-wb-psess-handle') && row.includes('sessionHandle') && row.includes('e.handle'),
    'tab 主标签=组合句柄（data-wb-psess-handle；sessions.json 句柄胜，UI-1 sessionHandle 派生兜底）在场')
  const entry = readFileSync(srcEntry, 'utf8')
  ok(entry.includes('pushSessionEntry'), 'session-entry：新建/换绑后登记进项目文件（pushSessionEntry）在场')
  ok(entry.includes('the session was created normally'), '登记失败=行内明示「会话已建」（不静默不谎报）')
  const store = readFileSync(join(here, '..', 'src', 'client', 'session-ledger-store.ts'), 'utf8')
  ok(store.includes("/sandbar-workbench/api/wf/sessions"), 'store：host API 路径同源锚（SESSIONS_API_PATH）在场')
  ok(store.includes('fetchProjectLedger') && store.includes('file-wins'), 'store：file-wins 拉取面在场（localStorage 降级缓存）')
  const sidebar = readFileSync(join(here, '..', 'src', 'client', 'sidebar.tsx'), 'utf8')
  ok(sidebar.includes('fetchProjectLedger('), 'sidebar：项目切换/挂载时拉项目文件（R5 新鲜度契约接线）在场')
  ok(sidebar.includes('setChatProjectBandInfo') && sidebar.includes('displayHandle'),
    'sidebar：身份带归属+句柄一并下发（setChatProjectBandInfo）在场')
  const host = readFileSync(join(here, '..', 'src', 'host', 'session-ledger-file.ts'), 'utf8')
  ok(host.includes('executor-grants.json') && host.includes('executor_sessions'),
    '执行器可见性=grants 合并门（派生显示，不动工作区索引）在场')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
