/**
 * t261008-36-face-overlay.mjs —— 宿主侧面 overlay 的判定层 UT（t261008-36）：
 *  - panelFaceFromMessage（face-overlay-model.ts，纯函数）：两张合法面、face 白名单外
 *    拒绝（R3）、projectKey 不等拒绝（R2：含换项目后的陈旧帧重放）、畸形形状逐例
 *    （null / 非对象 / 缺字段 / 错类型）拒绝不 throw；
 *  - 消息常量面板/宿主两侧逐字成对（改一处必须改另一处）；
 *  - 行为契约的源级锚定：R4 工单 overlay 优先（openTicketWins 先清面）、换项目清面、
 *    open-face 幂等（同面重开 = 同值 setState，不叠层不切换）、Back to Settings
 *    卸面、remove→cancel 回设置步；负面断言：本仓 executor-panel 源码内无
 *    model-routes.yaml 直写。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { panelFaceFromMessage, PANEL_FACES } from '../src/client/face-overlay-model.ts'

let n = 0
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const viewSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/executor-view.tsx'), 'utf8')
const panelSrc = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/panel-page.ts'), 'utf8')
const OPEN_FACE = 'sandbar-executor-panel:open-face'

// ---- 合法载荷：两张面各自放行 ----
for (const face of PANEL_FACES) {
  assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face, projectKey: 'alpha' }, 'alpha'), face, `valid ${face} accepted (${++n})`)
}
// 幂等语义（R1 改良）：同面重开返回同值——handler 以同值 setState，不叠层不切换。
assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face: 'routes', projectKey: 'alpha' }, 'alpha'), 'routes', `repeated open is idempotent (${++n})`)

// ---- R3：face 白名单外 ----
for (const bad of ['bogus', 'board', 'epics', 'docs', '', 'ROUTES', 'routes ', 'project_settings']) {
  assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face: bad, projectKey: 'alpha' }, 'alpha'), null, `unknown face ${JSON.stringify(bad)} rejected (${++n})`)
}

// ---- R2：projectKey 逐字相等；不等/缺失/错类型拒绝（陈旧帧重放面）----
assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face: 'routes', projectKey: 'beta' }, 'alpha'), null, `mismatched projectKey rejected (${++n})`)
assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face: 'routes' }, 'alpha'), null, `missing projectKey rejected (${++n})`)
assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face: 'routes', projectKey: 42 }, 'alpha'), null, `non-string projectKey rejected (${++n})`)
assert.equal(panelFaceFromMessage({ type: OPEN_FACE, face: 'routes', projectKey: '' }, 'alpha'), null, `empty projectKey rejected against non-empty own key (${++n})`)

// ---- 畸形输入逐例（外部输入纪律：拒绝不 throw）----
for (const bad of [null, undefined, 42, 'open-face', [], { type: OPEN_FACE }, { type: 'other', face: 'routes', projectKey: 'alpha' }, { face: 'routes', projectKey: 'alpha' }]) {
  assert.equal(panelFaceFromMessage(bad, 'alpha'), null, `malformed payload ${JSON.stringify(bad)} rejected (${++n})`)
}
let threw = false
try { panelFaceFromMessage({ get face() { throw new Error('x') } }, 'alpha') } catch { threw = true }
assert.equal(threw, false, `getter-throwing payload still rejected via typeof path (${++n})`)

// ---- 常量两侧成对 ----
const modelSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/face-overlay-model.ts'), 'utf8')
assert.ok(modelSrc.includes(`export const OPEN_FACE_MSG_TYPE = '${OPEN_FACE}'`) && viewSrc.includes('export { OPEN_FACE_MSG_TYPE }'), `host constant exported (single source in the model, re-exported by the view) (${++n})`)
assert.ok(panelSrc.includes(`'${OPEN_FACE}'`), `panel constant literal present (${++n})`)

// ---- 行为契约源级锚定 ----
assert.ok(/const openTicketWins = \(ticketId: string\) => \{\s*\n\s*setFace\(null\)/.test(viewSrc), `R4: ticket overlay wins — face cleared before open (${++n})`)
assert.ok(/d\.type === OPEN_TICKET_MSG_TYPE[\s\S]{0,200}openTicketWins\(d\.ticketId\)/.test(viewSrc), `R4: panel open-ticket also routes through the face-clearing path (${++n})`)
assert.ok(/useEffect\(\(\) => \{\s*\n\s*setFace\(null\)[\s\S]{0,200}\}, \[projectKey\]\)/.test(viewSrc), `project switch clears the face (${++n})`)
assert.ok(viewSrc.includes("data-wb-face-overlay="), `overlay anchor present (${++n})`)
assert.ok(viewSrc.includes('>Back to Settings</button>'), `Back to Settings affordance present (${++n})`)
assert.ok(/onClose=\{\(\) => setSettingsStep\('settings'\)\}/.test(viewSrc), `remove close returns to the settings step (${++n})`)
assert.ok(viewSrc.includes('<ProvidersSection projectKey={projectKey} />'), `routes face mounts the existing component (${++n})`)
assert.ok(viewSrc.includes('<ProjectSettingsModal') && viewSrc.includes('<ProjectRemoveModal'), `settings face mounts the existing modal chain (${++n})`)
assert.ok(/import \{ ProvidersSection \} from '\.\.\/\.\.\/\.\.\/providers\/src\/client\/index\.tsx'/.test(viewSrc), `one importer: ProvidersSection imported from the providers plugin (${++n})`)

// ---- 负面断言：面板插件无 model-routes 直写 ----
import { readdirSync } from 'node:fs'
const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
  const p = join(dir, e.name)
  return e.isDirectory() ? walk(p) : (p.endsWith('.ts') ? [p] : [])
})
for (const f of walk(join(repo, 'server/plugins/executor-panel/src'))) {
  const src = readFileSync(f, 'utf8')
  assert.ok(!/model-routes/.test(src), `no model-routes write in ${f.split('/').pop()} (${++n})`)
}

console.log(`done ${n}`)
