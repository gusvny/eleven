/**
 * smoke/hero.mjs —— suyou-workbench hero 零接管 + 顶部行退役冒烟
 * （t260831-02 建；票② R8 t260904-05 顶部行退役收口重写）。
 *
 * 直跑：node smoke/hero.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 *
 * hero 三槽接管（t260829-06）已彻底拆除——不注册任何 conversation.hero.* 槽，
 * 出厂落地页原样。会话入口沿革：顶部行（t260831-02）→ 票② R8 退役（t260904-05，
 * 入口收口为项目内会话区；出厂全局钮由注入 effect 压制，FACTORY_NEW_LABELS
 * 留守）。本文件测两件事：
 *
 *   B. 静态反接管 + 顶部行退役断言：src/ 与 lib/client.js 产物——无 hero 槽
 *      注册、无 wb-heroSlot 类、无出厂类名压制选择器、无 [data-phase= 锚；
 *      **顶部行已退役**：全 src 与产物无 SessionTopEntry/wb-sessTop 残留。
 *   C. 出厂钮压制锚存在性 + 顶部行锚不在场断言：session-entry.tsx 导出
 *      FACTORY_NEW_LABELS（出厂钮 aria-label 全集，zh/en）；data-wb-session-*
 *      顶部行家族锚在 src 中不在场（防锚回潮——ui-check/integration 已全部
 *      改锚至项目行 data-wb-psess-*，无残留消费方）。
 *      （记账层 A 组已随顶部行退役删除：被看守面消失，口径全量在
 *      smoke/sessions.mjs / project-sessions.mjs。）
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
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
  ok(!srcText.includes('SessionTopEntry') && !srcText.includes('wb-sessTop'),
    'src/ 顶部行组件与样式零残留（票② R8 退役）')
  ok(!builtText.includes('SessionTopEntry') && !builtText.includes('wb-sessTop'),
    '产物顶部行组件与样式零残留（票② R8 退役）')
}

section('C 出厂钮压制锚在 + 顶部行锚不在场（session-entry.tsx 文本级断言）')
{
  const text = readFileSync(join(srcRoot, 'client', 'session-entry.tsx'), 'utf8')
  ok(text.includes('FACTORY_NEW_LABELS'), '导出 FACTORY_NEW_LABELS（出厂钮 aria-label 锚集合，压制注入留守）')
  ok(text.includes("'新建会话'") && text.includes("'New session'"), '锚集合含 zh/en 两词条（locale 字典全集）')
  // 顶部行退役反转断言：data-wb-session-* 家族锚全 src 不在场（无残留消费方）
  const allSrc = readFileSync(join(srcRoot, 'client', 'sidebar.tsx'), 'utf8') + '\n' + text
    + '\n' + readFileSync(join(srcRoot, 'client', 'project-session-row.tsx'), 'utf8')
  ok(!allSrc.includes('data-wb-session-entry') && !allSrc.includes('data-wb-session-new')
    && !allSrc.includes('data-wb-session-row') && !allSrc.includes('data-wb-session-reopen'),
    '顶部行 data-wb-session-* 家族锚不在场（防锚回潮；消费面已全改 data-wb-psess-*）')
  ok(!text.includes('<SessionSection') && !text.includes('<HeroSessionEntry'), '左栏会话区/hero 槽版入口组件无渲染（历史注记注释除外）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
