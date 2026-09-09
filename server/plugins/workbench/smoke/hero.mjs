/**
 * smoke/hero.mjs — smoke for zero hero takeover + top-row retirement of sandbar-workbench
 * (created t260831-02; rewritten for the top-row retirement close-out in ticket 2 R8 t260904-05).
 *
 * Run: node smoke/hero.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 *
 * The three hero-slot takeover (t260829-06) has been fully removed — no conversation.hero.*
 * slot is registered, the factory landing page stays as-is. Session entry history: top row
 * (t260831-02) -> retired in ticket 2 R8 (t260904-05; the entry moved into the per-project
 * session area; the factory global button is suppressed by an injected effect,
 * FACTORY_NEW_LABELS remains as the guard). This file checks two things:
 *
 *   B. Static anti-takeover + top-row retirement assertions: src/ and the lib/client.js
 *      artifact — no hero slot registration, no wb-heroSlot class, no factory-class-name
 *      suppression selectors, no [data-phase= anchors; **the top row is retired**: no
 *      SessionTopEntry/wb-sessTop residue anywhere in src or the artifact.
 *   C. Factory-button suppression anchor present + top-row anchors absent: session-entry.tsx
 *      exports FACTORY_NEW_LABELS (the full set of factory button aria-labels, zh/en); the
 *      data-wb-session-* top-row family anchors are absent from src (guard against anchor
 *      resurrection — ui-check/integration have all been re-anchored to the project-row
 *      data-wb-psess-*, no leftover consumers).
 *      (Ledger layer group A was deleted with the top-row retirement: the guarded surface
 *      is gone; full accounting lives in smoke/sessions.mjs / project-sessions.mjs.)
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

/** Build one ledger entry (lastOpenedAt given directly as an ordinal, larger = newer). */
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
  // Top-row retirement inversion assertion: the whole data-wb-session-* family of anchors is absent from src (no leftover consumers)
  const allSrc = readFileSync(join(srcRoot, 'client', 'sidebar.tsx'), 'utf8') + '\n' + text
    + '\n' + readFileSync(join(srcRoot, 'client', 'project-session-row.tsx'), 'utf8')
  ok(!allSrc.includes('data-wb-session-entry') && !allSrc.includes('data-wb-session-new')
    && !allSrc.includes('data-wb-session-row') && !allSrc.includes('data-wb-session-reopen'),
    '顶部行 data-wb-session-* 家族锚不在场（防锚回潮；消费面已全改 data-wb-psess-*）')
  ok(!text.includes('<SessionSection') && !text.includes('<HeroSessionEntry'), '左栏会话区/hero 槽版入口组件无渲染（历史注记注释除外）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
