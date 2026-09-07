/**
 * Baseline: 工单详情「执行规格（spec）」卡契约（t260904-06，B 形态）。
 *
 * Intent:
 *   详情抽屉此前只渲染「工单正文（原始需求）」，引擎 snapshot 顶层一直透传的
 *   spec（开票会话蒸馏的加工后派发规格）在 UI 上不可见。本票在前端补
 *   spec?: string 字段 + 正文卡正下方渲染 spec 卡（宿主样张评审拍板 B 形态：
 *   默认展开 + max-height:260px 限高滚动 + 等宽字数徽标 + 蓝左边条 accent 令牌，fallback=#0969da）。
 *   本测试锁「前端可见面」契约，防两类经典失效：
 *     - 改了 src 忘重建 lib bundle（三产物同源锁，rework-banner-ui.mjs 同族）；
 *     - 守卫/样式被静默弱化（空 spec 渲空卡、限高滚动退撑爆、徽标退化）。
 *   取舍（方案 v2 评审已核）：不带走 banner 测试的「真代码执行」（守卫是 JSX
 *   表达式不可安全 eval）与「跨层键形状锁」（本票零后端改动，spec 透传是引擎
 *   既有契约，无新回归向量）；渲染健壮性三态（缺字段/空值不崩、空整卡不渲染）
 *   以静态守卫 + CSS 锁形式带走。
 *   Pure node 静态断言——无服务器、无 Temporal、无浏览器，随处可跑（含引擎
 *   机械 integration 步）。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const SRC = join(REPO, 'server', 'dsh', 'workbench', 'src', 'client', 'index.tsx')
const LIB_JS = join(REPO, 'server', 'dsh', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'dsh', 'workbench', 'lib', 'client.cjs')
// 后端零改动断言面（只读引用，不属写集）
const NODE_TS = join(REPO, 'server', 'dsh', 'workbench', 'node.ts')
const DEV_LANE = join(REPO, 'server', 'dsh', 'temporal-poc', 'dev_lane.py')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const src = readFileSync(SRC, 'utf8')
const libJs = readFileSync(LIB_JS, 'utf8')
const libCjs = readFileSync(LIB_CJS, 'utf8')

// ---- A. 有 spec 渲染卡：三产物同源锁 ----
section('A. spec 卡渲染分支在 src + lib(client.js/client.cjs) 三产物同源在场')
for (const [name, art] of [['src', src], ['lib/client.js', libJs], ['lib/client.cjs', libCjs]]) {
  ok(art.includes('wb-d2-spec'), `${name}: 卡类名 wb-d2-spec 在场`)
  ok(art.includes('执行规格（spec）'), `${name}: ttl 文案「执行规格（spec）」在场`)
  ok(art.includes('data-v": "B"') || art.includes('data-v="B"'), `${name}: B 形态标记 data-v=B 在场`)
  ok(art.includes('"txt"') || art.includes('className="txt"'), `${name}: 正文 .txt 包裹在场`)
  ok(art.includes('detail.spec.length'), `${name}: 字数徽标取 spec.length 在场`)
  ok(name === 'src' ? /\{detail\.spec\.length\} 字/.test(art) : art.includes('" 字"'),
    `${name}: 徽标「 字」单位字面在场（src=JSX 形态 / lib=字符串字面形态）`)
}
// 接口字段（src 侧白盒；lib 类型擦除不查）
ok(/spec\?: string/.test(src), 'src: TicketDetail 补 spec?: string 字段')

// ---- B. 空 spec 不渲染：truthy 守卫（老票/缺字段/空串整卡消失） ----
section('B. 空 spec 整卡不渲染（detail.spec && 守卫，src 与编译产物都在场）')
ok(src.includes('detail.spec && ('), 'src: 渲染块被 detail.spec && ( 守卫包裹')
ok(libJs.includes('detail.spec &&'), 'lib/client.js: 守卫经 JSX 编译后在场')
ok(libCjs.includes('detail.spec &&'), 'lib/client.cjs: 守卫经 JSX 编译后在场')

// ---- C. B 形态 CSS 锁：默认展开 + 限高滚动 + 蓝左条 + 徽标 ----
section('C. .wb-d2-spec 样式锁（三产物 CSS 逐项）')
for (const [name, art] of [['src', src], ['lib/client.js', libJs], ['lib/client.cjs', libCjs]]) {
  const rule = art.match(/\.wb-d2-spec\{[^}]*\}/)
  ok(rule !== null, `${name}: .wb-d2-spec 规则在场`)
  if (rule) {
    const css = rule[0]
    ok(css.includes('max-height:260px'), `${name}: 限高 260px（B 形态拍板值）`)
    ok(css.includes('overflow-y:auto'), `${name}: 限高滚动 overflow-y:auto`)
    // t260905-08：写死色退役——蓝左边条改 accent 令牌（fallback 仍 #0969da，视觉语义不变）
    ok(css.includes('border-left:4px solid var(--dsw-derive-accent,#0969da)'), `${name}: 蓝左边条 accent 令牌（fallback=#0969da，与正文卡视觉区分）`)
    ok(css.includes('white-space:pre-wrap'), `${name}: pre-wrap（多行规格原文样保留）`)
    ok(css.includes('word-break:break-word'), `${name}: break-word（长行不横向撑爆）`)
  }
  const ttl = art.match(/\.wb-d2-spec \.ttl\{[^}]*\}/)
  ok(ttl !== null && ttl[0].includes('display:flex') && ttl[0].includes('align-items:baseline')
    && ttl[0].includes('gap:8px'), `${name}: ttl 行 flex 基线对齐 + gap:8px（徽标不退化成行内流式）`)
  const cnt = art.match(/\.wb-d2-spec \.cnt\{[^}]*\}/)
  ok(cnt !== null && cnt[0].includes('ui-monospace'), `${name}: cnt 字数徽标等宽小字`)
}

// ---- D. 后端零改动 + 零新路由 ----
section('D. 后端零改动：引擎/workbench 服务侧不出现 spec 卡渲染逻辑与 spec 路由')
const backendFiles = [[NODE_TS, 'node.ts'], [DEV_LANE, 'dev_lane.py']]
import { readdirSync } from 'node:fs'
const hostDir = join(REPO, 'server', 'dsh', 'workbench', 'src', 'host')
for (const f of readdirSync(hostDir)) backendFiles.push([join(hostDir, f), `src/host/${f}`])
for (const [p, name] of backendFiles) {
  const art = readFileSync(p, 'utf8')
  ok(!art.includes('wb-d2-spec') && !art.includes('执行规格'), `${name}: 无 spec 卡渲染逻辑泄漏（前端可见面只在 client bundle）`)
}
const nodeTs = readFileSync(NODE_TS, 'utf8')
ok(!/spec/i.test(nodeTs), 'node.ts: 无任何 spec 相关新路由/分支（/spec/i 零命中）')
ok(nodeTs.includes('/sandbar-workbench/api/wf/tickets/<id>') || /wf\/tickets\/\$/.test(nodeTs),
  'node.ts: 详情仍走既有 GET /wf/tickets/<id>（整包透传，无旁路）')

// ---- E. 畸形输入守卫：徽标取值在守卫内；超长走限高滚动 ----
section('E. 畸形输入：spec undefined/空串不触达 .length；超长 spec 限高滚动')
ok(src.indexOf('detail.spec && (') < src.indexOf('detail.spec.length'),
  'src: .length 取值在 truthy 守卫之后（undefined/空串不触达，不抛 TypeError）')
ok(libJs.indexOf('detail.spec &&') < libJs.indexOf('detail.spec.length'),
  'lib/client.js: 编译后取值顺序保持守卫在前')
ok(src.indexOf('detail.spec && (') < src.indexOf('<D2Reworks'),
  'src: spec 卡位于正文卡正下方、打回横幅之前（钉顶区位置契约）')

console.log(`\nspec-card-ui: pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
