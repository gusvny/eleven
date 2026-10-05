// t261005-04 UI-3 票详情中栏浮层：渲染面源级守卫（spec-card-ui.mjs 同族——锁
// 「改 src 忘重建 lib」）。断言三处同源：src/index.tsx 浮层结构 + src/spec-block.tsx
// Spec 块四件 + lib/client.cjs 重建产物含浮层标记。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const HERE = new URL('.', import.meta.url).pathname
const indexSrc = readFileSync(join(HERE, '../src/client/index.tsx'), 'utf8')
const specSrc = readFileSync(join(HERE, '../src/client/spec-block.tsx'), 'utf8')
const modelSrc = readFileSync(join(HERE, '../src/client/ticket-overlay-model.ts'), 'utf8')
const libSrc = readFileSync(join(HERE, '../lib/client.cjs'), 'utf8')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}

console.log('== 浮层几何（261004 设计稿 §7.5.1：inset 12px，中栏内，右栏不碰）')
ok(indexSrc.includes('.wb-drawer.wb-overlay{top:12px;right:12px;bottom:12px;left:12px'), '浮层 inset 12px CSS 在场')
ok(indexSrc.includes('className="wb-drawer wb-overlay" data-testid="ticket-overlay"'), '浮层容器挂 wb-overlay 类与测试锚')

console.log('== 单层不变量（渲染面：epic 内容与票详情互斥二选一）')
ok(indexSrc.includes("overlayNav.current !== null && overlayNav.current.kind === 'epic' && ("), 'epic 分支在场')
ok((indexSrc.match(/overlayNav\.current\?\.kind !== 'epic' && /g) || []).length >= 3, '票详情三段（loading/终态卡/详情体）都带 epic 排他守卫')
ok(!/overlayNavs|overlayStack/i.test(indexSrc), '无栈形态残留（current 单条目，never a stack）')

console.log('== 面包屑（下钻回退）')
ok(indexSrc.includes('data-testid="overlay-crumb"') && indexSrc.includes('overlayBreadcrumbBack'), '面包屑按钮与回退处理在场')
ok(indexSrc.includes('const c = crumbOf(overlayNav)'), '可见性走 model 单点 crumbOf')
ok(modelSrc.includes('export function crumbOf'), 'crumbOf 是 model 导出（渲染层不另判）')

console.log('== 键盘：Esc 关 / ↑↓ 换票，监听全终态回收')
ok(indexSrc.includes("ev.key === 'Escape'") && indexSrc.includes("'ArrowUp'") && indexSrc.includes("'ArrowDown'"), '三键处理在场')
ok(/addEventListener\('keydown', onKey\)/.test(indexSrc) && /removeEventListener\('keydown', onKey\)/.test(indexSrc), 'keydown 监听挂载+摘除成对')

console.log('== Spec 块（v11 块序：决策之前先看它）')
ok(indexSrc.includes('<SpecBlock body={detail.body} spec={detail.spec}'), '详情面消费 SpecBlock（旧钉顶正文卡+规格卡已并入）')
ok(!indexSrc.includes('Body (original request)'), '旧展开正文卡已退役（收进折叠 Original request (verbatim)）')
for (const anchor of ['spec-block', 'spec-acceptance', 'spec-write-set', 'spec-red-line', 'spec-original']) {
  ok(specSrc.includes(`data-testid="${anchor}"`), `Spec 块测试锚 ${anchor} 在场`)
}
ok(specSrc.includes('return null'), '全键缺席整块不渲染（老票零侵入，不摆空架子）')

console.log('== lib 重建同源（改 src 忘重建 lib 即红）')
ok(libSrc.includes('wb-overlay') && libSrc.includes('overlay-crumb') && libSrc.includes('spec-write-set'), 'lib/client.cjs 含浮层与 Spec 块标记（已重建）')

console.log(`\nt261005-04-overlay-ui: pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
