#!/usr/bin/env node
/**
 * project-icons.mjs —— 组头图标族统一契约（t260904-15 票③，验收 11b）。
 *
 * 直跑：node tests/project-icons.mjs。纯 node 静态断言（tsx 不可 node 直跑——
 * spec-card-ui.mjs 同款「源文本锁」取舍：几何规格是常量表达式，静态锁足够；
 * 渲染行为由侧栏既有三态 CSS 承担）：
 *   A. project-icons.tsx：五枚 specs 齐备、title=aria-label、viewBox/stroke 单源；
 *   B. sidebar 渲染点：四视图换装 + 第五枚设置入口，active 类/onClick 语义保留；
 *   C. emoji 清零：sidebar/index/epics 三文件 📋📖🔀🗂️ 引用清零；
 *      🤖⚙️👤 执行主体徽标白名单豁免（不在 11b 范围）。
 */

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 直跑/经 run_tests.mjs（cwd=仓库根）双口径可跑：REPO 从本文件位置推导。
const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')
const read = (p) => readFileSync(join(REPO, p), 'utf8')
let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const icons = read('server/dsh/workbench/src/client/project-icons.tsx')
const sidebar = read('server/dsh/workbench/src/client/sidebar.tsx')
const index = read('server/dsh/workbench/src/client/index.tsx')
const epics = read('server/dsh/workbench/src/client/epics.tsx')

section('A 图标模块：五枚 specs + 规格单源')
for (const name of ['board', 'knowledge', 'routes', 'epics', 'settings']) {
  ok(icons.includes(`${name}: { title:`), `spec ${name} 在案`)
}
for (const title of ['工单列表', '知识库', '模型路由', '立项单', '项目设置']) {
  ok(icons.includes(`'${title}'`), `title/aria「${title}」齐备`)
}
ok(icons.includes("PROJECT_ICON_VIEWBOX = '0 0 20 20'"), 'viewBox 20×20 单源')
ok(icons.includes('PROJECT_ICON_STROKE_WIDTH = 1.6'), '线宽 1.6 单源')
ok(icons.includes('fill="none"') && icons.includes('strokeLinecap="round"') && icons.includes('strokeLinejoin="round"'), 'fill none + 圆帽圆角')
ok(icons.includes('width="18"') && icons.includes('height="18"'), '显形 18px')
ok(icons.includes('aria-label={spec.ariaLabel}'), 'aria-label 恒同 title')
ok(icons.includes('滑杆') && icons.includes('带箭头分流'), '修订11 两枚重绘语义在案（设置=滑杆/路由=分流）')

section('B sidebar 渲染点：五枚换装 + 语义保留')
ok(sidebar.includes("<ProjectIcon name=\"board\" />"), '工单列表换装')
ok(sidebar.includes("<ProjectIcon name=\"knowledge\" />"), '知识库换装')
ok(sidebar.includes("<ProjectIcon name=\"routes\" />"), '模型路由换装')
ok(sidebar.includes("<ProjectIcon name=\"epics\" />"), '立项单换装')
ok(sidebar.includes("<ProjectIcon name=\"settings\" />"), '第五枚设置入口')
ok(sidebar.includes('data-wb-project-settings-entry=""'), '设置入口语义锚')
ok((sidebar.match(/handleViewIcon\(g\.project\.key, '(board|knowledge|routes|epics)'\)/g) ?? []).length === 4,
  '四视图 onClick 语义零回归')
ok((sidebar.match(/className=\{`wb-view-icon \$\{rightView === '(board|knowledge|routes|epics)' && viewProject === g\.project\.key \? 'active' : ''\}`\}/g) ?? []).length === 4,
  '四视图 active 态零回归')
ok(sidebar.includes("width:26px; height:26px") && sidebar.includes('border-radius:6px'), '命中区 26×26 radius 6')

section('C emoji 清零（三文件）+ 白名单豁免')
for (const [name, src] of [['sidebar', sidebar], ['index', index], ['epics', epics]]) {
  const hits = [...src.matchAll(/📋|📖|🔀|🗂️/g)].map(m => m[0])
  ok(hits.length === 0, `${name}.tsx emoji 引用清零（残留 ${hits.length}）`)
}
ok((index.match(/🤖|⚙️|👤/g) ?? []).length > 0, '执行主体徽标 🤖⚙️👤 白名单保留（不在 11b 范围）')

console.log(`\nPROJECT_ICONS_TESTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
