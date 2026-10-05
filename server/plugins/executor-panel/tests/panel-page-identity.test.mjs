/**
 * panel-page-identity.test.mjs —— t261005-05（console-ui UI-4）：面板页项目身份徽标 UT。
 *  - 嵌入面：面板页携带徽标运行时（projectIdentity/identityBadgeSvg 等）与常量闭包
 *    （12 色板 / 6 轮廓 / 3 结构 / 兜底身份）——与 workbench shared 单源逐字相同，
 *    不存在第二份实现（漂移守卫）；
 *  - 渲染面：projChip 里有徽标位 + key 位；setProject 调 renderProjBadge；
 *    空/缺项目=徽标位清空（不渲染就是「未定身」，无静默替身）；
 *  - 行为面：跨插件 import 同一模块直测 projectIdentity 确定性 + 畸形 key 兜底
 *    （13px 面板口径产 svg；同 key 恒同 svg）。
 * 零 DOM、零网络、零 3099 触碰。
 */
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import {
  PROJECT_PALETTE_12, IDENTITY_OUTLINES, IDENTITY_STRUCTURES, FALLBACK_IDENTITY,
  projectIdentity, identityBadgeSvg, identityOutlinePath, baseIdentity, identityId,
  fnv1a, isProjectKeyLike,
} from '../../../plugins/workbench/src/shared/project-identity.ts'

let n = 0

// ---- 嵌入面：单源逐字（String(fn) 嵌页 = UT 与页面同一份实现） ----
const EMBED_FNS = { projectIdentity, identityBadgeSvg, identityOutlinePath, baseIdentity, identityId, fnv1a, isProjectKeyLike }
for (const [fnName, fn] of Object.entries(EMBED_FNS)) {
  assert(PANEL_PAGE_HTML.includes(String(fn)), 'page embeds the exact source of ' + fnName)
  n++
}
for (const c of PROJECT_PALETTE_12) assert(PANEL_PAGE_HTML.includes(JSON.stringify(c)), 'palette colour embedded: ' + c)
n++
assert(PANEL_PAGE_HTML.includes('var FALLBACK_IDENTITY = '), 'fallback identity embedded')
n++
assert(!PANEL_PAGE_HTML.includes('Math.random'), 'no random ids in the page (deterministic badge markup)')
n++

// ---- 渲染面：chip 结构与调用点 ----
assert(PANEL_PAGE_HTML.includes('id="projBadge"') && PANEL_PAGE_HTML.includes('id="projKey"'),
  'projChip carries a badge slot and a key slot')
n++
assert(PANEL_PAGE_HTML.includes('renderProjBadge(state.project)'), 'setProject renders the badge')
n++
assert(PANEL_PAGE_HTML.includes('identityBadgeSvg(projectIdentity(key), 13)'),
  'panel badge renders at the declared 13px size')
n++
// Scope-seam regression (found by browser-page-contract): renderProjBadge lives in
// the outer script scope, so it must NOT reach for the IIFE-local el() helper —
// a ReferenceError there aborts the rest of setProject (settings never load).
assert(/function renderProjBadge\(key\)\{[\s\S]*?document\.getElementById\('projBadge'\)/.test(PANEL_PAGE_HTML),
  'renderProjBadge gets its slot via document.getElementById (not the IIFE-local el)')
n++
assert(!/el\('projBadge'\)/.test(PANEL_PAGE_HTML), 'no IIFE-local el() reference to projBadge')
n++

// ---- 行为面：同一模块的确定性 + 畸形兜底 ----
const a = JSON.stringify(projectIdentity('sandbar'))
assert(a === JSON.stringify(projectIdentity('sandbar')), 'same key, same identity across calls')
n++
assert(a !== JSON.stringify(projectIdentity('suyou')), 'sandbar/suyou identities differ')
n++
assert(JSON.stringify(projectIdentity('')) === JSON.stringify(FALLBACK_IDENTITY), 'empty key falls back, no throw')
n++
const svg = identityBadgeSvg(projectIdentity('sandbar'), 13)
assert(svg.includes('<svg') && svg.includes('13'), 'badge svg renders at 13px for the panel chip')
n++
assert(svg === identityBadgeSvg(projectIdentity('sandbar'), 13), 'badge svg is byte-stable for the same key/size')
n++
for (const o of IDENTITY_OUTLINES) assert(typeof o === 'string' && IDENTITY_STRUCTURES.length === 3, 'identity tables intact')
n += IDENTITY_OUTLINES.length

done(n)
