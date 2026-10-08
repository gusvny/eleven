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

const icons = read('server/plugins/workbench/src/client/project-icons.tsx')
const sidebar = read('server/plugins/workbench/src/client/sidebar.tsx')
const index = read('server/plugins/workbench/src/client/index.tsx')
const epics = read('server/plugins/workbench/src/client/epics.tsx')

// t261005-10 (UI-2)：图标族随视图归并退役——board/docs/epics 三枚退（Epics/Docs
// 住面板 tab，工单详情走左列行浮层），图标族只留 More views 里的两枚。
section('A 图标模块：两枚 specs + 规格单源')
for (const name of ['routes', 'settings']) {
  ok(icons.includes(`${name}: { title:`), `spec ${name} 在案`)
}
for (const gone of ['board', 'docs', 'epics']) {
  ok(!new RegExp(`${gone}: \\{ title:`).test(icons), `retired spec ${gone} 已退`)
}
for (const title of ['Model Routes', 'Project Settings']) {
  ok(icons.includes(`'${title}'`), `title/aria「${title}」齐备`)
}
ok(icons.includes("PROJECT_ICON_VIEWBOX = '0 0 20 20'"), 'viewBox 20×20 单源')
ok(icons.includes('PROJECT_ICON_STROKE_WIDTH = 1.6'), '线宽 1.6 单源')
ok(icons.includes('fill="none"') && icons.includes('strokeLinecap="round"') && icons.includes('strokeLinejoin="round"'), 'fill none + 圆帽圆角')
ok(icons.includes('width="18"') && icons.includes('height="18"'), '显形 18px')
ok(icons.includes('aria-label={spec.ariaLabel}'), 'aria-label 恒同 title')
ok(icons.includes('滑杆') && icons.includes('带箭头分流'), '修订11 两枚重绘语义在案（设置=滑杆/路由=分流）')

section('B sidebar 渲染点：t261008-36 起 More views 整体退役（两面归面板 Settings）')
ok(!sidebar.includes("<ProjectIcon name=\"board\" />"), 'board 图标退役（UI-2）')
ok(!sidebar.includes("<ProjectIcon name=\"docs\" />"), 'docs 图标退役（UI-2）')
ok(!sidebar.includes("<ProjectIcon name=\"epics\" />"), 'epics 图标退役（UI-2）')
ok(!sidebar.includes("<ProjectIcon name=\"routes\" />"), 'routes 图标退役（t261008-36：改从面板 Settings 开）')
ok(!sidebar.includes("<ProjectIcon name=\"settings\" />"), 'settings 图标退役（t261008-36：改从面板 Settings 开）')
ok(!sidebar.includes('data-wb-project-settings-entry=""'), '设置入口语义锚退役（t261008-36）')
ok(!sidebar.includes('data-wb-more-views'), 'More views 展开钮退役（t261008-36）')
ok((sidebar.match(/onClick=\{\(\) => handleViewIcon\(g\.project\.key, '(\w+)'\)\}/g) ?? []).every(x => x.includes("'executor'")),
  '视图 onClick 只剩 executor（键位行不混入计数）')
ok(!sidebar.includes('knowledge'), 't260905-06：knowledge 提法清零（图标键）')
ok(!sidebar.includes("rightView === 'routes'"), 'per-project 视图 active 态只剩 executor（routes 判式退役）')
ok(sidebar.includes("width:26px; height:26px") && sidebar.includes('border-radius:6px'), '命中区 26×26 radius 6（几何契约不动）')

section('C emoji 清零（三文件）+ 白名单豁免')
for (const [name, src] of [['sidebar', sidebar], ['index', index], ['epics', epics]]) {
  const hits = [...src.matchAll(/📋|📖|🔀|🗂️/g)].map(m => m[0])
  ok(hits.length === 0, `${name}.tsx emoji 引用清零（残留 ${hits.length}）`)
}
ok((index.match(/🤖|⚙️|👤/g) ?? []).length > 0, '执行主体徽标 🤖⚙️👤 白名单保留（不在 11b 范围）')

console.log(`\nPROJECT_ICONS_TESTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
