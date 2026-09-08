/**
 * smoke/project-sessions.mjs —— 项目内会话区冒烟（session-entry 第 3 面①，R1–R6）。
 *
 * 直跑：node smoke/project-sessions.mjs（node ≥22.18 原生 type-stripping，
 * 纯函数直接 import .ts；react 组件不能 node 直跑，走源文本断言——hero.mjs 先例）。
 *
 * 覆盖两层：
 *   A. 纯函数层（src/shared/sessions.ts 第 3 面① 新面）：
 *      pickProjectTabs（按项目过滤 / seq 升序 / 无上限 / active 唯一三态 /
 *      title 三级兜底 / ticket- 防御 / 缺号条目不显示 / 畸形输入）
 *      backfillProjectSeqs（登记顺序补号 / 幂等引用不变 / 不改入参 /
 *      交错态从项目最大号续 / 多项目独立）
 *      nextProjectSeq（计数器与账册取 max+1 / 计数器丢失兜底 / 畸形容错）
 *      编号不回收全链（关 2 号 → 1/3 保留原号；新登记续 4——拍板 1 核心回归）
 *   B. 源文本层（src/client/project-session-row.tsx + sidebar.tsx +
 *      session-entry.tsx + lib/client.js 产物）：
 *      - 换行不横滚（R2）：flex-wrap:wrap 在场，无 overflow-x:scroll/auto；
 *      - 确认框（R5）：data-wb-psess-confirm/-ok/-cancel 锚全集在场；
 *        无原生 confirm( 调用；position:fixed（C1：滚动容器裁剪对策）在场；
 *      - 高亮（R6）：data-wb-psess-tab[data-active] 锚在场；
 *      - 语义锚纪律：无 [class*= / [class$= 出厂类名匹配选择器；
 *      - 接线在场：sidebar 渲染 ProjectSessionRow + backfill 挂载 effect；
 *        session-entry 登记 seq（nextProjectSeq/backfillProjectSeqs 调用点）；
 *      - 票② R7/R8（t260904-05）：项目色（+ 钮/激活 tab/组头色点/右栏色带锚）、
 *        顶部行退役反转（wb-sessTop 家族不在场）、确认文案无 ↺ 表述；
 *      - lib 产物与 src 同批（锚在 lib/client.js 里同样在场）。
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

/** 造一条账册条目（lastOpenedAt 直接给序数，越大越新=登记越晚）。 */
function ent(id, extra = {}) {
  return { id, project: 'suyou', cwd: '/repo/suyou', lastOpenedAt: 0, ...extra }
}

/* ───────────────────────── A. 纯函数层 ───────────────────────── */

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
  // 无上限（拍板 2）：21 条（>LEDGER_CAP 20）全量参排
  const many = Array.from({ length: 21 }, (_, i) => ent(`s${i}`, { seq: i + 1 }))
  ok(pickProjectTabs(many, { project: 'suyou' }).length === 21, '数量不限：21 条全量参排（tab 无上限）')
  // 畸形：非数组 / project 空串 / project 非字符串
  ok(pickProjectTabs(null, { project: 'suyou' }).length === 0, '账册非数组 → 空列表不抛')
  ok(pickProjectTabs(ledger, {}).length === 0, 'project 缺省 → 空列表')
  ok(pickProjectTabs(ledger, { project: 123 }).length === 0, 'project 非字符串 → 空列表')
  // 缺号 / 坏号条目不显示（backfill 先行的不变式）
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
  // 账册数组序=最新在前（touchEntry 头插）；补号按 lastOpenedAt 升序=登记顺序
  const ledger = [ent('c', { lastOpenedAt: 30 }), ent('a', { lastOpenedAt: 10 }), ent('b', { lastOpenedAt: 20 })]
  const snapshot = JSON.stringify(ledger)
  const out = backfillProjectSeqs(ledger)
  const byId = Object.fromEntries(out.map(e => [e.id, e.seq]))
  ok(byId.a === 1 && byId.b === 2 && byId.c === 3, '补号=项目内登记顺序（oldest→1）')
  ok(JSON.stringify(ledger) === snapshot, '不改入参')
  // 幂等：无缺号时原样返回入参引用（调用方据此免 persist）
  const again = backfillProjectSeqs(out)
  ok(again === out, '幂等：二次跑返回入参引用（免 persist 判据）')
  // 多项目独立补号
  const multi = [ent('s1', { lastOpenedAt: 5 }), ent('k1', { project: 'sandbar', lastOpenedAt: 3 }), ent('s2', { lastOpenedAt: 8 }), ent('k2', { project: 'sandbar', lastOpenedAt: 6 })]
  const mo = backfillProjectSeqs(multi)
  const m = Object.fromEntries(mo.map(e => [e.id, e.seq]))
  ok(m.s1 === 1 && m.s2 === 2 && m.k1 === 1 && m.k2 === 2, '多项目各自从 1 起独立补号')
  // 交错态（异常路径防御）：项目内已有 seq 5 时，缺号条目从 6 续（不重号优先）
  const mixed = [ent('old', { seq: 5 }), ent('gap', { lastOpenedAt: 99 })]
  const mm = backfillProjectSeqs(mixed)
  ok(mm.find(e => e.id === 'gap')?.seq === 6, '交错态：缺号从项目内现存最大号之上续（不重号）')
  // 畸形：非数组 / lastOpenedAt 缺失并列按数组位置稳定破平
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
  // 计数器丢失 + 已关 30 号（账册只剩 3）→ 兜底取 closed 最大 30，续 31 不重发 30
  ok(nextProjectSeq(ledger, 'suyou', undefined, closed) === 31, 'BO-1：计数器丢失时已关 30 号不重发（续 31）')
  // 计数器在场（>closed 最大）时 closed 不拉低（取 max 语义不变）
  ok(nextProjectSeq(ledger, 'suyou', 35, closed) === 36, '计数器 35 > closed 30 → 36（max 语义）')
  // 计数器落后于 closed（closed 30 > 计数器 5）→ 取 31
  ok(nextProjectSeq(ledger, 'suyou', 5, closed) === 31, '计数器落后 closed → 取 closed 最大+1')
  // 他项目 closed 条目按各自项目域参与
  ok(nextProjectSeq(ledger, 'sandbar', undefined, closed) === 89, '他项目 closed 88 参与 sandbar 域（本组口径）')
  // closed 畸形：非数组忽略 / 脏条目（null、缺 project、seq NaN）跳过不崩
  ok(nextProjectSeq(ledger, 'suyou', undefined, 'bad') === 4, 'closed 非数组忽略（账册兜底 4）')
  ok(nextProjectSeq(ledger, 'suyou', undefined, [null, { id: 'x', seq: Number.NaN }, ent('y', { seq: 9 })]) === 10,
    'closed 脏条目跳过、合法 9 号计入（续 10）')
  // 不传 closed（旧调用面，journey J4 兼容）：行为与 B2 完全一致
  ok(nextProjectSeq(ledger, 'suyou', 2) === 4 && nextProjectSeq(ledger, 'suyou', 9) === 10,
    'closed 缺省=旧口径不变（J4 兼容面）')
}

section('C1 编号不回收全链（拍板 1 核心回归：关 2 号 → 1/3 保留；新登记续 4）')
{
  // 场景：项目 suyou 已登记 3 个会话（seq 1/2/3）；关闭 2 号；再新建一个。
  let ledger = [
    ent('s1', { seq: 1, lastOpenedAt: 10 }),
    ent('s2', { seq: 2, lastOpenedAt: 20 }),
    ent('s3', { seq: 3, lastOpenedAt: 30 }),
  ]
  let counters = { suyou: 3 }
  // 关闭 2 号（UI 确认后走 removeEntry；计数器不动）
  ledger = removeEntry(ledger, 's2')
  const tabs = pickProjectTabs(ledger, { project: 'suyou' })
  ok(tabs.map(t => t.seq).join(',') === '1,3', '关闭 2 号后：1/3 保留原号（不回收）')
  // 新登记一个（handleNew 同款：nextProjectSeq + touchEntry 带 seq）
  const seq = nextProjectSeq(ledger, 'suyou', counters.suyou)
  counters = { ...counters, suyou: seq }
  ledger = touchEntry(ledger, ent('s4', { seq, lastOpenedAt: 40 }))
  const tabs2 = pickProjectTabs(ledger, { project: 'suyou' })
  ok(tabs2.map(t => t.seq).join(',') === '1,3,4', '新会话续号 4（洞保留）')
  // 往返持久化后不变
  const back = parseLedger(serializeLedger(ledger))
  ok(pickProjectTabs(back, { project: 'suyou' }).map(t => t.seq).join(',') === '1,3,4', '持久化往返后编号不变')
  // 重开被关的 2 号（↺：touchEntry 带原 seq）：2 号回到原位
  ledger = touchEntry(ledger, ent('s2', { seq: 2, lastOpenedAt: 50 }))
  ok(pickProjectTabs(ledger, { project: 'suyou' }).map(t => t.seq).join(',') === '1,2,3,4', '重开带原号归位（稳定身份）')
  // 计数器丢失场景：只剩 1/3/4，无计数器 → 下一个仍不重号
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
  // 迁移后新建（handleNew 同款链）：从存量最大号续
  const seq = nextProjectSeq(migrated, 'suyou', 0)
  ok(seq === 4, '迁移后新建续 4（存量 1-3 已占）')
}

/* ───────────────────────── B. 源文本层（src + lib 双侧）───────────────────────── */

section('S1 换行不横滚（R2：flex-wrap 在场，无 overflow-x 横滚）')
{
  const row = readFileSync(srcRow, 'utf8')
  ok(row.includes('flex-wrap:wrap'), '行容器 flex-wrap:wrap 在场（超宽换行）')
  ok(!/overflow-x\s*:\s*(scroll|auto)/.test(row), '无 overflow-x:scroll/auto（不横滚）')
  // lib 侧只做正向断言：bundle 含 echarts vendor CSS（自带 overflow-x 串），
  // 全 bundle 负向正则会被第三方噪音误红——「不横滚」约束的是本组件样式，
  // 由上面 src 级负向断言精确看守。
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
  ok(row.includes('仅关闭入口，不删除会话内容'), '确认文案明示「仅关闭入口不删内容」（拍板 3）')
  // lib 侧锚断言不带 '='：打包后 JSX 属性名以对象键形态出现（"data-wb-…":）
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
  // 同锚纪律：空态/有 tab 共用 data-wb-psess-new（动作链不变）
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
  ok(sidebar.includes('data-wb-psess-dot') && sidebar.includes('projectColor(g.project.key)'), '组头名前项目色点在场（data-wb-psess-dot）')
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
  ok(row.includes('仅关闭入口，不删除会话内容'), '确认文案明示「仅关闭入口不删内容」')
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

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
