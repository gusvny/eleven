/**
 * t261008-36-settings-faces.test.mjs —— 面板 Settings 页两枚面入口（Model routes /
 * Project settings）的页面生成锁：
 *  - 两枚入口行存在（锚点 data-wb-panel-face，mock 的两行形状），Watchdog 块原样保留
 *    （本票只加入口，不重排 Settings）；
 *  - postMessage 接线：OPEN_FACE 常量与宿主侧 executor-view.tsx 逐字成对；载荷带
 *    projectKey（面板自己的 ?project= 上下文）；独立打开（无父窗）= 禁用+title 点名
 *    去处的显式降级面，不是哑按钮；
 *  - LIST_CONTRACTS 有 settings_faces 固定形状声明，且随 JSON 嵌页；
 *  - 负面断言：面板代码不含任何 model-routes.yaml 直写 / 路由表第二份缓存面
 *    （单一读写路径 = 宿主 overlay 里的 ProvidersSection → providers API）。
 */
import { assert, done } from './lib.mjs'
import { readFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { LIST_CONTRACTS } from '../src/host/list-contracts.ts'

let n = 0
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const hostView = readFileSync(join(repo, 'server/plugins/workbench/src/client/executor-view.tsx'), 'utf8')

// ---- 两枚入口行 + 锚点 ----
assert(PANEL_PAGE_HTML.includes('data-wb-panel-face="routes"'), 'Model routes entry anchored (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes('data-wb-panel-face="project-settings"'), 'Project settings entry anchored (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes('>Model routes</div>'), 'Model routes label (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes('>Project settings</div>'), 'Project settings label (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes('id="faceRoutesBtn"') && PANEL_PAGE_HTML.includes('id="faceSettingsBtn"'), 'both entry buttons present (' + ++n + ')')
assert(PANEL_PAGE_HTML.indexOf('faceEntries') < PANEL_PAGE_HTML.indexOf('id="setKnobs"'), 'entries sit above the Watchdog block in Settings (' + ++n + ')')

// ---- Watchdog 块原样（不重排 Settings）----
for (const id of ['id="saveBtn"', 'id="sleepBtn"', 'id="wakeBtn"', 'id="revokeBtn"', 'id="saveResult"']) {
  assert(PANEL_PAGE_HTML.includes(id), 'watchdog block keeps ' + id + ' (' + ++n + ')')
}

// ---- postMessage 接线：常量成对 + projectKey 入载荷 + 显式降级 ----
const OPEN_FACE = 'sandbar-executor-panel:open-face'
assert(PANEL_PAGE_HTML.includes("'" + OPEN_FACE + "'"), 'panel carries the open-face type (' + ++n + ')')
const hostModel = readFileSync(join(repo, 'server/plugins/workbench/src/client/face-overlay-model.ts'), 'utf8')
assert(hostView.includes('export { OPEN_FACE_MSG_TYPE }') && hostModel.includes("export const OPEN_FACE_MSG_TYPE = '" + OPEN_FACE + "'"), 'host exports the paired type constant (' + ++n + ')')
assert(/OPEN_FACE_MSG_TYPE, face: face, projectKey: state\.project/.test(PANEL_PAGE_HTML.replace(/\n/g, ' ').replace(/ +/g, ' ')) ||
  /OPEN_FACE_MSG_TYPE,\s*face:\s*face,\s*projectKey:\s*state\.project/.test(PANEL_PAGE_HTML), 'payload carries the panel project key (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes("btn.title = 'Open this panel from the console to use this button.'"), 'standalone open = named degraded face, not a dead silent button (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes("bindFaceEntry(document.getElementById('faceRoutesBtn'), 'routes')"), 'routes button bound with the whitelisted face name (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes("bindFaceEntry(document.getElementById('faceSettingsBtn'), 'project-settings')"), 'settings button bound with the whitelisted face name (' + ++n + ')')

// ---- LIST_CONTRACTS：settings_faces 固定形状声明 + 嵌页 ----
assert(LIST_CONTRACTS.settings_faces && LIST_CONTRACTS.settings_faces.cap === 'all', 'settings_faces declared, cap all (' + ++n + ')')
assert(/fixed/i.test(LIST_CONTRACTS.settings_faces.source), 'source is the fixed markup block (' + ++n + ')')
assert(PANEL_PAGE_HTML.includes('settings_faces'), 'contract embedded into the page JSON (' + ++n + ')')

// ---- 负面断言：面板无第二读写路径 ----
const pageJs = PANEL_PAGE_HTML
assert(!/model-routes/.test(pageJs), 'no model-routes.yaml path anywhere in the panel page (' + ++n + ')')
assert(!pageJs.includes('/sandbar-admin/api/routes'), 'panel page never touches the routes API directly (' + ++n + ')')
assert(!pageJs.includes('/sandbar-providers/api'), 'panel page never touches the providers API directly (' + ++n + ')')
const hostApi = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/api.ts'), 'utf8')
assert(!hostApi.includes('model-routes'), 'panel host API has no model-routes route (' + ++n + ')')
const contractsSrc = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/list-contracts.ts'), 'utf8')
assert(!contractsSrc.includes('sandbar-admin/api/routes'), 'panel declares no routes read/write source (' + ++n + ')')

done(n)
