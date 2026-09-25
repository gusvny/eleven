/**
 * Baseline: wb-modal 弹层 a11y 角色契约（t260905-05）。
 *
 * Intent:
 *   四类 wb-modal（审批通过并推进 / 打回 / 派活指令 / 内容预览）此前是裸
 *   div.modal——无 role/aria，屏幕阅读器不可辨，集成层的 [role="dialog"]
 *   消费面（dismissOverlays 类 helper）恒空=形同虚设。t260905-05 多页签
 *   场景再锚定时坐实：审批弹层是 awaiting-human 写链的必经交互，可测性
 *   契约缺位会让「弹层在场但场景探不到」静默吞断言。本测试锁三件事：
 *     1) src 四处 wb-modal 容器全部带 role="dialog" + aria-modal="true"
 *        + aria-label（防新弹层漏配）；
 *     2) lib 双产物同步重建（改 src 忘重建 bundle 的经典失效，三产物同源
 *        锁，rework-banner-ui.mjs 同族）；
 *     3) aria-label 与弹层标题词一致（防串语义）。
 *   Pure node 静态断言——无服务器、无 Temporal、无浏览器，随处可跑。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'index.tsx')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const src = readFileSync(SRC, 'utf8')
const libJs = readFileSync(LIB_JS, 'utf8')
const libCjs = readFileSync(LIB_CJS, 'utf8')

/* ---- 1) src：四处 wb-modal 全部配齐 role/aria-modal/aria-label ---- */
section('1 src 弹层角色配齐')

// 逐类点名（审批/打回/派活/预览），防「配了三处漏一处」——review C1 口径：
// 按实际枚举，不按类计数。
// t260925-18：aria-label（=UI 文案）随界面英文化改英文；语义锚一致，label 列保留中文备注。
const MODALS = [
  { label: 'Approve and advance', anchor: 'aria-label="Approve and advance"' },
  { label: 'Rework', anchor: 'aria-label="Rework"' },
  { label: 'Dispatch prompt', anchor: 'aria-label="Dispatch prompt"' },
  { label: 'Content preview', anchor: 'aria-label="Content preview"' },
]
// 容器行形状：className="wb-modal" + role + aria-modal 同标签行内出现
const containerRe = /<div className="wb-modal" role="dialog" aria-modal="true" aria-label="([^"]+)">/g
const found = [...src.matchAll(containerRe)].map(m => m[1])
ok(found.length === MODALS.length,
  `src：wb-modal 容器带完整 role/aria 的数量=${found.length}（期望 ${MODALS.length}，防漏配/防新弹层不配）`)
for (const m of MODALS) {
  ok(found.includes(m.label), `src：${m.label} 弹层 role="dialog"+aria-modal+aria-label 配齐`)
}
// 裸 wb-modal（无 role）不允许再出现——防新弹层回退
ok(!/<div className="wb-modal">/.test(src), 'src：不存在缺 role 的裸 wb-modal 容器')

/* ---- 2) lib 双产物同步：bundle 里四组 role/aria 全在、双包一致 ----
   （bundle 是编译产物：JSX 属性落成对象字面量 `role: "dialog"` /
   `"aria-label": "…"`，断言按编译形态锚，不锚 JSX 原文） */
section('2 bundle 同步重建')
for (const m of MODALS) {
  ok(libJs.includes(`"aria-label": "${m.label}"`), `lib/client.js：${m.label} aria-label 在册`)
  ok(libCjs.includes(`"aria-label": "${m.label}"`), `lib/client.cjs：${m.label} aria-label 在册`)
}
const countRe = (s, re) => (s.match(re) ?? []).length
ok(countRe(libJs, /role: "dialog"/g) >= MODALS.length,
  `lib/client.js：role: "dialog" 计数=${countRe(libJs, /role: "dialog"/g)}（期望 ≥${MODALS.length}）`)
ok(countRe(libJs, /"aria-modal": "true"/g) === MODALS.length,
  `lib/client.js：aria-modal 计数=${countRe(libJs, /"aria-modal": "true"/g)}（期望 ${MODALS.length}）`)
ok(countRe(libCjs, /role: "dialog"/g) >= MODALS.length
  && countRe(libCjs, /"aria-modal": "true"/g) === MODALS.length,
  'lib/client.cjs：role/aria-modal 计数同步')
ok(libJs === libCjs, 'lib/client.js === lib/client.cjs（双包同源）')

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
