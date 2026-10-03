// 改版回归锁（t261003-06）：项目选择器已按设计 note §2 **整体移除**——
// 本测试从「选择器形状」反转为「选择器不存在 + 深链缝仍在 + 无项目显式降级」。
// 项目来源只剩 ?project=<key> 深链（workbench 项目行进面板即该项目）。
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'

let n = 0
assert(!PANEL_PAGE_HTML.includes('id="project"'), 'no project dropdown element')
assert(!PANEL_PAGE_HTML.includes('id="freeProject"'), 'no free-key text box')
assert(!PANEL_PAGE_HTML.includes('id="go"'), 'no Load button')
assert(!PANEL_PAGE_HTML.includes('pick a project'), 'no picker copy')
assert(PANEL_PAGE_HTML.includes("location.search).get('project'"), '?project=<key> deep-link seam intact')
assert(PANEL_PAGE_HTML.includes('__panelSelect'), 'programmatic project-selection seam intact (browser scenarios)')
assert(PANEL_PAGE_HTML.includes('No project is selected'), 'missing project = explicit banner (never a silent empty page)')
assert(PANEL_PAGE_HTML.includes('projChip'), 'project shown as a read-only chip next to the title')
n += 8
done(n)
