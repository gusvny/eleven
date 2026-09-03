/**
 * smoke/hero.mjs —— suyou-workbench 顶部行替换 + hero 零接管冒烟（t260831-02 重写）。
 *
 * 直跑：node smoke/hero.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 *
 * t260831-02 口径：hero 三槽接管（t260829-06）彻底拆除——不再注册任何
 * conversation.hero.* 槽，出厂落地页原样；会话入口收口为顶部行（出厂「⊕ New
 * Session」钮原地替换，SessionTopEntry + 侧栏注入语义锚）。本文件改测三件事：
 *
 *   A. 记账层关键回归照搬（自 t260831-02 版前的 hero.mjs B 组收编）：与顶部入口
 *      直接相关的四条——ticket- 工单会话不入账/不展示、MRU 降序 ≤5、切项目列表
 *      随项目走（记账层归属生效）、畸形账册输入（坏 JSON/脏条目）容错不崩。
 *      完整记账层口径（parseLedger/touchEntry/... 全分支）在 smoke/sessions.mjs，
 *      不在本文件重复。
 *      【不带过来】旧 A 组 resolveHeroProjectKey 全分支——该函数随 shared/hero.ts
 *      删除（唯一消费者 hero 槽版入口已退场），项目 key 现由侧栏 viewProject+
 *      注册表兜底直接供值，无新纯函数可测。
 *   B. 静态反接管断言（t260828-06 死因回归 + t260831-02 拆除回归）：src/ 与
 *      lib/client.js 产物——无 conversation.hero 槽注册、无 wb-heroSlot 类、
 *      无 CSS 类名压制选择器（[class$= / [class*=）、无 [data-phase= 锚；
 *      hero.tsx 与 shared/hero.ts 已删除。
 *   C. 顶行注入语义锚存在性断言：session-entry.tsx 导出 FACTORY_NEW_LABELS
 *      （出厂钮 aria-label 全集，zh/en；文本级断言——session-entry.tsx 带
 *      react/runtime import，node 直跑会失败，故不 import）。
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  isGlobalSessionId,
  parseLedger,
  touchEntry,
  pickSwitchTargets,
  SWITCH_LIMIT,
} from '../src/shared/sessions.ts'

const here = dirname(fileURLToPath(import.meta.url))
const srcRoot = join(here, '..', 'src')
const libClient = join(here, '..', 'lib', 'client.js')

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 造一条账册条目（lastOpenedAt 直接给序数，越大越新）。 */
function ent(id, extra = {}) {
  return { id, project: 'suyou', cwd: '/repo/suyou', lastOpenedAt: 0, ...extra }
}

section('A 记账层关键回归（顶部入口口径，全量见 smoke/sessions.mjs）')
{
  ok(isGlobalSessionId('chat-a') && !isGlobalSessionId('ticket-t260831-02'), 'ticket- 工单会话被 isGlobalSessionId 拒绝')
  const l = touchEntry([], { id: 'ticket-x', project: 'suyou', lastOpenedAt: 9 })
  ok(l.length === 0, 'touchEntry 拒绝工单会话入账')
  let m = []
  m = touchEntry(m, { id: 'a', project: 'suyou', lastOpenedAt: 1 })
  m = touchEntry(m, { id: 'b', project: 'suyou', lastOpenedAt: 2 })
  m = touchEntry(m, { id: 'c', project: 'suyou', lastOpenedAt: 3 })
  const r = pickSwitchTargets(m, { project: 'suyou', current: 'a' })
  ok(r.map(t => t.id).join(',') === 'c,b,a', 'MRU 降序')
  ok(r.find(t => t.id === 'a')?.active === true, 'current 高亮')
  const big = Array.from({ length: 8 }, (_, i) => ent(`s${i}`, { lastOpenedAt: i + 1 }))
  const r2 = pickSwitchTargets(big, { project: 'suyou' })
  ok(r2.length === SWITCH_LIMIT && r2[0].id === 's7', '≤5 且留最新')
  const mixed = [ent('mine', { lastOpenedAt: 1 }), ent('other', { project: 'other', lastOpenedAt: 9 })]
  const r3 = pickSwitchTargets(mixed, { project: 'suyou' })
  ok(r3.length === 1 && r3[0].id === 'mine', '切项目列表随项目走（他项目不进）')
  ok(parseLedger('not json{').length === 0 && parseLedger('[{"id":""},{"id":"x","project":"p"}]').length === 1,
    '畸形账册输入容错（坏 JSON/脏条目剔除）不崩')
}

section('B 静态反接管断言（src/ 与产物）')
{
  const { readdirSync, statSync, existsSync } = await import('node:fs')
  const tsFiles = []
  ;(function walk(dir) {
    for (const f of readdirSync(dir)) {
      const p = join(dir, f)
      if (statSync(p).isDirectory()) walk(p)
      else if (/\.(ts|tsx|mjs)$/.test(f)) tsFiles.push(p)
    }
  })(srcRoot)
  const srcText = tsFiles.map(f => readFileSync(f, 'utf8')).join('\n')
  ok(!tsFiles.some(f => f.endsWith('hero.tsx')), 'src/client/hero.tsx 已删除')
  ok(!tsFiles.some(f => f.endsWith('hero.ts')), 'src/shared/hero.ts 已删除')
  ok(!srcText.includes("inject('conversation.hero") && !srcText.includes('applyHeroTakeover'), 'src/ 无 hero 槽注册（历史注记类注释除外）')
  ok(!srcText.includes('wb-heroSlot'), 'src/ 无 wb-heroSlot 残留类')
  ok(!srcText.includes('[data-phase='), 'src/ 无 data-phase 语义锚残留（t260828-06 已证伪面）')
  ok(!srcText.includes('[class$=') && !srcText.includes('[class*='), 'src/ 无出厂类名压制选择器')
  ok(existsSync(libClient), 'lib/client.js 产物存在')
  const builtText = readFileSync(libClient, 'utf8')
  ok(!builtText.includes("inject('conversation.hero") && !builtText.includes("name: 'conversation.hero"),
    '产物无 hero 槽注册（历史注记注释除外——右栏出厂元素零接管）')
  ok(!builtText.includes('wb-heroSlot'), '产物无 wb-heroSlot 残留')
  ok(!builtText.includes('applyHeroTakeover'), '产物无 applyHeroTakeover 残留')
  ok(builtText.includes('SessionTopEntry') || builtText.includes('wb-sessTop'), '产物含顶部会话入口')
}

section('C 顶行注入语义锚（session-entry.tsx 文本级断言）')
{
  const text = readFileSync(join(srcRoot, 'client', 'session-entry.tsx'), 'utf8')
  ok(text.includes('FACTORY_NEW_LABELS'), '导出 FACTORY_NEW_LABELS（出厂钮 aria-label 锚集合）')
  ok(text.includes("'新建会话'") && text.includes("'New session'"), '锚集合含 zh/en 两词条（locale 字典全集）')
  ok(text.includes('data-wb-session-entry') && text.includes('data-wb-session-new') && text.includes('data-wb-session-row'),
    '顶部入口带 UI 验收 DOM 断言锚')
  ok(text.includes('SessionTopEntry'), '顶部入口组件在（SessionTopEntry）')
  ok(!text.includes('<SessionSection') && !text.includes('<HeroSessionEntry'), '左栏会话区/hero 槽版入口组件无渲染（历史注记注释除外）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
