#!/usr/bin/env node
/**
 * project-identity.mjs —— 项目身份徽标单源契约（console-ui UI-4，t261005-05）。
 *
 * 直跑：node tests/project-identity.mjs（cwd=仓库根或本目录均可）。
 *
 * 覆盖（方案验收面 + 畸形输入纪律）：
 *   A. 声明实现：调色板 = mock v11 PALETTE12 逐字 12 色；轮廓 6 / 结构 3 全集；
 *      徽标 216 空间（12×6×3）不越界。
 *   B. 确定性：同 key 恒同三元组；不传集合与传集合时同 key 的首选三元组一致
 *      （去重只动撞身者）；跨调用无状态（纯函数）。
 *   C. 去重：构造两个必撞身的 key，传已知集后第二个沿环形步进拿到不撞身份；
 *      不传集合时两者撞身（规则本身允许，消费面靠传集合消除）。
 *   D. 畸形输入：''/null/undefined/数字/对象/超长/控制字符 → FALLBACK_IDENTITY，
 *      不 throw；badge 渲染同样不 throw。
 *   E. SVG：六种轮廓都产 path；ring 产 mask、half 产 clipPath、solid 无洞；
 *      sparkle <12px 退化为实心（设计稿 §2.4）；id 确定性（同身份同尺寸同 id，
 *      无 Math.random 残留）。
 *   F. 真实注册表 key：sandbar/suyou 身份互异（同 smoke/project-color.mjs 的
 *      用户点名对，换 12 色板 + 三元组后仍要分开）。
 */

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')
const read = (p) => readFileSync(join(REPO, p), 'utf8')
let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const mod = await import(join(REPO, 'server/plugins/workbench/src/shared/project-identity.ts'))
const {
  PROJECT_PALETTE_12, IDENTITY_OUTLINES, IDENTITY_STRUCTURES, FALLBACK_IDENTITY,
  projectIdentity, identityOutlinePath, identityBadgeSvg, projectBadgeSvg,
} = mod

section('A 声明实现（12 色 × 6 轮廓 × 3 结构，声明值逐字）')
{
  const declared = ['#e76a6a', '#e7936a', '#e7c36a', '#c6e76a', '#8ae76a', '#6ae79c',
    '#6ae7d4', '#6aabe7', '#7f6ae7', '#b56ae7', '#e76ad0', '#e76a92']
  ok(JSON.stringify(PROJECT_PALETTE_12) === JSON.stringify(declared), '调色板 = 声明 12 色（mock PALETTE12 逐字）')
  ok(JSON.stringify([...IDENTITY_OUTLINES]) === JSON.stringify(['pentagon', 'hexagon', 'octagon', 'shield', 'sparkle', 'tag']), '轮廓 6 全集（非常见形）')
  ok(JSON.stringify([...IDENTITY_STRUCTURES]) === JSON.stringify(['solid', 'ring', 'half']), '结构 3 全集')
  const space = new Set()
  for (const c of PROJECT_PALETTE_12) for (const o of IDENTITY_OUTLINES) for (const s of IDENTITY_STRUCTURES) space.add(`${c}|${o}|${s}`)
  ok(space.size === 216, '身份空间 = 216')
}

section('B 确定性（跨重启不变的根基=纯函数）')
{
  const keys = ['sandbar', 'suyou', 'a', 'project-x']
  let det = true
  for (const k of keys) {
    const first = JSON.stringify(projectIdentity(k))
    for (let i = 0; i < 50; i++) if (JSON.stringify(projectIdentity(k)) !== first) det = false
    // 集合口径：传集合只依赖集合内容，不依赖传入顺序/重复（同一集合多次调用恒同）。
    if (JSON.stringify(projectIdentity(k, keys)) !== JSON.stringify(projectIdentity(k, [...keys].reverse().concat(keys)))) det = false
  }
  ok(det, '同 key 任意次恒同三元组；去重只依赖集合内容不依赖顺序')
}

section('C 已知项目集去重')
{
  // 构造必撞身对：先扫真实哈希流，找到 baseIdentity 三元组相等的两个合成 key。
  const { baseIdentity } = await import(join(REPO, 'server/plugins/workbench/src/shared/project-identity.ts'))
  const byId = new Map()
  let pair = null
  for (let i = 0; i < 5000 && !pair; i++) {
    const k = `collide-${i}`
    const id = JSON.stringify(baseIdentity(k))
    if (byId.has(id)) pair = [byId.get(id), k]
    else byId.set(id, k)
  }
  ok(Array.isArray(pair), '找到一对同首选三元组的 key（撞身可复现）')
  if (pair) {
    const [keeper, loser] = [...pair].sort() // 先到先得按排序序：keeper 排在前面
    const solo = projectIdentity(keeper)
    const dedup = projectIdentity(loser, pair)
    ok(JSON.stringify(dedup) !== JSON.stringify(solo), '去重后撞身者换身份')
    ok(JSON.stringify(projectIdentity(keeper, pair)) === JSON.stringify(solo), '排序在先者身份不动（先到先得）')
    ok(JSON.stringify(projectIdentity(loser)) === JSON.stringify(solo), '不传集合时两者同身（规则声明行为）')
    // 链式撞身回归：找 base 恰等于 loser 去重后身份的第三个 key，三 key 全集去重
    // 后必须两两互异（taken 要记「最终身份」而不是「首选身份」——曾在此翻车）。
    const loserDedup = JSON.stringify(dedup)
    let third = null
    for (let i = 0; i < 20000 && !third; i++) {
      const k = `chain-${i}`
      if (JSON.stringify(baseIdentity(k)) === loserDedup) third = k
    }
    if (third) {
      const set = [keeper, loser, third]
      const ids = set.map(k => JSON.stringify(projectIdentity(k, set)))
      ok(new Set(ids).size === 3, '链式撞身：三 key 全集去重后两两互异')
    } else {
      ok(true, '链式撞身：20000 探针未见第三撞（概率声明，不强行造）')
    }
  }
}

section('D 畸形输入 → 兜底身份，不 throw')
{
  const bad = ['', null, undefined, 42, {}, [], 'k'.repeat(65), 'bad\u0007key', 'a\nb']
  let allFallback = true
  for (const k of bad) {
    const id = projectIdentity(k)
    if (JSON.stringify(id) !== JSON.stringify(FALLBACK_IDENTITY)) allFallback = false
    try { projectBadgeSvg(k, 14) } catch { allFallback = false }
  }
  ok(allFallback, '畸形 key 全部落兜底身份且徽标渲染不 throw')
  ok(FALLBACK_IDENTITY.color === '#9ca3af' && FALLBACK_IDENTITY.outline === 'pentagon', '兜底身份=灰五边实心')
}

section('E SVG 几何与结构')
{
  const mk = (o, s) => ({ color: '#e76a6a', outline: o, structure: s })
  for (const o of IDENTITY_OUTLINES) {
    ok(identityOutlinePath(o, 14).startsWith('M'), `轮廓 ${o} 产 path`)
  }
  ok(identityBadgeSvg(mk('pentagon', 'ring'), 14).includes('<mask'), 'ring 产 mask（挖洞）')
  ok(identityBadgeSvg(mk('pentagon', 'half'), 14).includes('<clipPath'), 'half 产 clipPath（右半实色）')
  ok(!identityBadgeSvg(mk('pentagon', 'solid'), 14).includes('<mask'), 'solid 无洞')
  // sparkle <12px：结构声明 ring 但渲染退化 solid（设计稿 §2.4 小尺寸不画洞）
  const small = identityBadgeSvg(mk('sparkle', 'ring'), 11)
  ok(!small.includes('<mask'), 'sparkle 11px ring 退化为实心（无 mask）')
  const big = identityBadgeSvg(mk('sparkle', 'ring'), 14)
  ok(big.includes('<mask'), 'sparkle 14px ring 保留挖洞')
  ok(identityBadgeSvg(mk('hexagon', 'ring'), 14) === identityBadgeSvg(mk('hexagon', 'ring'), 14), '同身份同尺寸 SVG 逐字节相同（确定性 id）')
  ok(!identityBadgeSvg(mk('hexagon', 'ring'), 14).includes('Math.random'), '无随机 id 残留')
  // 未知轮廓兜底 pentagon（畸形枚举不 throw）
  ok(identityOutlinePath('no-such-shape', 14) === identityOutlinePath('pentagon', 14), '未知轮廓回落 pentagon')
}

section('F 真实注册表 key（用户点名对）')
{
  const a = JSON.stringify(projectIdentity('sandbar'))
  const b = JSON.stringify(projectIdentity('suyou'))
  ok(a !== b, 'sandbar/suyou 身份互异')
  ok(projectBadgeSvg('sandbar', 14).includes('svg'), '便捷入口产 svg')
}

console.log(`\nPROJECT_IDENTITY_TESTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
