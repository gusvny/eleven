/**
 * t260902-05 t06 —— 用户反馈①②「入口位置 / 中 pane 化」构建产物黑盒门。
 *
 * 用户场景：①「📊 度量」入口出现在出厂侧栏最底一排（与 dsh settings 同排），
 * 不再浮在工单台 settings 上方；②面板不再全屏盖住整窗，只在中列内打开，
 * body 滚动不再被锁（中 pane 不该锁全页）；Esc 关闭、焦点归还、图表实例释放
 * 等既有交互纪律不许丢。
 *
 * 断言面（对浏览器真实加载的那份产物做静态门——同 t260902-01 i02 先例）：
 * （t261005-10 UI-2 改写 B/E：侧栏 Metrics 浮层与入口整体退役、Metrics 迁入
 * executor 面板 tab——本门随之改钉「退役零残留」，断言方向反转但门槛不放松。）
 *  A 双产物同字节（client.js === client.cjs，漂移=忘了重建或只建了一半）；
 *  B 中 pane：.wb-m 规则不再是 position:fixed，而是 position:absolute
 *    （挂载祖先 .wb-sb-right 已是 position:relative）；
 *  C 滚动锁移除：document.body.style.overflow 在产物中零命中
 *    （现值 3 处全来自 metrics.tsx 滚动锁，中 pane 化后应删）；
 *  D 三 tab 灰置移除：data-dis:true 与 M2b/M2c 标记零命中（与 t02 E 互为双保险）；
 *  E 入口与交互纪律残留：📊 度量入口、出厂 footer.action 注入点、面板 aria
 *    「度量面板」、Esc 关闭处理在产物中都在（入口迁移不许把功能迁丢）。
 *
 * 入口「与 dsh settings 同排」的最终确认属浏览器级人工项
 * （见 manual_browser_checklist.md 第 1 条）——静态门锁的是实现路径在产物里
 * 真实存在（footer.action slot 注入 + 现位软退化），排位肉眼验收不交给机器。
 *
 * Run: node integration/t260902-05/t06_ui_build_gate.mjs  (cwd = lane root)
 */
import { readFileSync } from 'node:fs'

const LIB_JS = new URL('../../server/plugins/workbench/lib/client.js', import.meta.url)
const LIB_CJS = new URL('../../server/plugins/workbench/lib/client.cjs', import.meta.url)

let pass = 0, fail = 0
const ok = (name, cond, detail = '') => {
  if (cond) { pass++; console.log(`  ok ${name}`) } else { fail++; console.log(`  FAIL ${name}${detail ? ' — ' + detail : ''}`) }
}

let js = '', cjs = ''
try { js = readFileSync(LIB_JS, 'utf8') } catch {}
try { cjs = readFileSync(LIB_CJS, 'utf8') } catch {}

if (js === '' || cjs === '') {
  // t260904-12 三态：产物未构建=环境缺件（没验成，原因归环境）→ ENV_FAIL，绝不 exit 0 假绿。
  console.log('  ENV_FAIL — lib/client.js 或 client.cjs 不存在（产物未构建）')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

console.log('A. 双产物同字节')
ok('client.js === client.cjs', js === cjs, '字节漂移=构建产物只更新一半')

console.log('B. 侧栏 Metrics 浮层退役（t261005-10 UI-2：Metrics 迁入面板 tab）')
{
  const n = (js.match(/\.wb-m\{/g) ?? []).length
  ok('.wb-m 浮层规则在产物中零命中（浮层随入口一并退役）', n === 0, `count=${n}`)
}

console.log('C. 滚动锁移除')
{
  const n = (js.match(/document\.body\.style\.overflow/g) ?? []).length
  ok('document.body.style.overflow 零命中（现 3 处全属 metrics 滚动锁）', n === 0, `count=${n}`)
}

console.log('D. tab 灰置移除')
{
  const n = (js.match(/data-dis": "true"/g) ?? []).length
  ok('data-dis 灰置零命中（现 3 处）', n === 0, `count=${n}`)
  ok('M2b/M2c 灰置标记零命中', !js.includes('"M2b"') && !js.includes('"M2c"'))
}

console.log('E. 入口退役与残留纪律（t261005-10 UI-2）')
ok('「📊 度量」入口在产物中零命中（入口退役，Metrics 在面板 tab）', !js.includes('📊 Metrics'))
ok('面板 aria-label「度量面板」在产物中零命中', !js.includes('Metrics panel'))
ok('面板状态持久化 key 零命中（浮层面板不复存在）', !js.includes('sandbar-workbench-metrics-panel-v1'))
ok('出厂 footer.action 注入点在产物中（settings 弹层仍走该槽）', js.includes('footer.action'), '入口迁移的实现路径必须真实存在于交付产物')
ok('Esc 关闭处理在产物中（其余浮层纪律不变）', js.includes('Escape'))

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail === 0 ? 0 : 1)
