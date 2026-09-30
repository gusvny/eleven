// 项目选择器形状 UT（t260930-09 scope 8）：下拉列全量项目并标 declared/not；
// ?project=<key> 深链缝仍在；executor-session 溯源卡有显式空态与溯源行。
import { assert, done } from './lib.mjs'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'

let n = 0
assert(PANEL_PAGE_HTML.includes('/sandbar-watchdog/api/status'), 'selector feeds from the watchdog status list (declared AND undeclared registry projects, one stubbed surface)')
assert(PANEL_PAGE_HTML.includes('pick a project (declared or not)'), 'empty option states the new selector semantics')
assert(PANEL_PAGE_HTML.includes('· not declared'), 'undeclared projects carry an explicit marker')
assert(PANEL_PAGE_HTML.includes("location.search).get('project')"), '?project=<key> deep-link seam intact')
assert(PANEL_PAGE_HTML.includes('executorSessionCard'), 'executor-session provenance card function present')
assert(PANEL_PAGE_HTML.includes('creates one on demand when this project has work'), 'provenance card has an explicit empty state (never a fake session id)')
assert(PANEL_PAGE_HTML.includes('last.preset'), 'provenance card renders the preset name (who/when/preset)')
assert(PANEL_PAGE_HTML.includes('malformed row'), 'malformed provenance rows surface loudly')
n += 8
done(n)
