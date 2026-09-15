#!/usr/bin/env node
/**
 * sc_ticket_time_viewer.mjs —— 「本票时刻」查看器与详情链接化契约（t260915-17，mock 260904 标注 D）。
 *
 * 用户可感知契约（工单验收①③ + mock 原话）：
 *   1) 点开文件行 → 文档查看器只读打开，顶部横幅「🕰 本票时刻 · 只读」在场
 *      （契约锚 data-testid="ticket-time-banner"，方案总验收口径钉死）；
 *   2) 「跳到当前版」小链：点击 → 内容切当前版（mode=current）且横幅消失；
 *   3) 查看器零编辑控件（只读刚性：无 textarea/contentEditable/保存语义）；
 *   4) 详情文件行=链接：状态卡 sc-file 与 diff 文件行可点；「背景引用」行组
 *      （refs 非空才渲染，mode=base）；
 *   5) Escape/遮罩关闭（EvidenceLightbox 家族先例的资源终态）；
 *   6) bundle 重建一致：client 源的契约锚必须同批出现在重建产物 lib/client.*。
 *
 * 三依据：①工单验收①③；②KI 触及面=无未闭合项直接触及；③组件对外契约=上列
 * 1-6（文案与 testid 是 mock/方案钉的用户契约锚，不锚内部函数名/文件名）。
 *
 * 档位声明（灰盒）：本场景是离线结构锁档（S0）；浏览器级 DOM 腿（真点击、真渲染）
 * 按项目惯例留隔离台 stage_docker 手法（sc_ticket_detail_lane_map_dom 同族），本场景
 * 红的语义=契约锚缺席/接线断/未重建，不判环境。
 *
 * 直跑：node integration/t260915-17/sc_ticket_time_viewer.mjs（cwd=仓库根）
 * 三态：SUMMARY pass=X fail=Y env_fail=Z na=W；exit 0=全过 / 1=产品红 / 2=环境红。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const REPO_ROOT = resolve(HERE, '..', '..')
const CLIENT_DIR = join(REPO_ROOT, 'server/plugins/workbench/src/client')
const LIB_DIR = join(REPO_ROOT, 'server/plugins/workbench/lib')

let PASS = 0, FAIL = 0, ENVFAIL = 0, NA = 0
function ok(cond, label) { if (cond) { PASS++; console.log('  ok  ' + label) } else { FAIL++; console.log('  FAIL ' + label) } }
function section(t) { console.log('\n== ' + t + ' ==') }

/* 收集 client 源（ts/tsx）为 {file, text} */
function clientFiles() {
  const out = []
  for (const n of readdirSync(CLIENT_DIR)) {
    if (!/\.(tsx?|ts)$/.test(n)) continue
    out.push({ file: n, text: readFileSync(join(CLIENT_DIR, n), 'utf8') })
  }
  return out
}
const files = clientFiles()
section('S0 源域')
ok(files.length > 0, 'workbench client 源目录可读（' + files.length + ' 个 ts/tsx 文件）')

/* 锚定义（用户契约，mock/方案钉死）。KI-051 锚语义不锚字面：testid 锚「值」——
 * 字面量 data-testid="…" 与常量定义 TICKET_TIME_*_TESTID='…' 两种写法都认。 */
const ANCHOR_TESTID_VALUE = 'ticket-time-banner'
const ANCHOR_BANNER = '🕰 本票时刻 · 只读'
const ANCHOR_JUMP = '跳到当前版'
function stripComments(t) { return t.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ') }

section('S1 查看器横幅契约锚（mock D 原话）')
const hitTestid = files.filter(f => f.text.includes(ANCHOR_TESTID_VALUE))
const hitBanner = files.filter(f => f.text.includes(ANCHOR_BANNER))
const hitJump = files.filter(f => f.text.includes(ANCHOR_JUMP))
ok(hitTestid.length > 0, '横幅契约锚值在场（ticket-time-banner，字面或常量定义）')
ok(hitBanner.length > 0, '横幅人话文案在场（' + ANCHOR_BANNER + '）')
ok(hitJump.length > 0, '「跳到当前版」小链在场')
/* 横幅锚文件集 = 后续只读/接线锁的扫描域（不锚文件名，锚契约字面） */
const anchorFiles = [...new Map([...hitTestid, ...hitBanner, ...hitJump].map(f => [f.file, f])).values()]

section('S2 跳到当前版接线（点击 → mode=current + 横幅消失语义）')
/* 静态档只钉「current 口径在锚域被消费」；点击→清横幅的行为面留隔离台 DOM 腿
 * （t260915-05-detail-lane-map-dom 同族分层），静态钉不动的不断言。 */
for (const f of anchorFiles) {
  ok(/['"`]current['"`]|\bcurrent\b/.test(stripComments(f.text)), f.file + '：current 口径在锚域被消费（跳转切换证据）')
}
if (anchorFiles.length === 0) ok(false, '无锚文件可查接线（查看器实现缺席）')

section('S3 查看器零编辑控件（只读刚性，验收③）')
/* 扫描域=查看器自有文件（文件名含 ticket-time）——index.tsx 是宿主页，其
 * textarea/contentEditable 属会话等其他功能域，不归本票只读刚性管。注释剥离
 * （头注自述「无 …contentEditable」不是控件）。 */
const viewerFiles = files.filter(f => /ticket[-_]time/i.test(f.file))
let editHits = []
if (viewerFiles.length === 0) {
  ok(false, '查看器自有文件缺席（ticket-time*，实现缺席）')
} else {
  for (const f of viewerFiles) {
    const code = stripComments(f.text)
    const low = code.toLowerCase()
    // 只锁「控件形态」：<textarea 标签、contentEditable 作为 JSX 属性/对象键（=/:跟随）；
    // isContentEditable 属性读（keydown 编辑焦点 guard，EvidenceLightbox 带过来的故障
    // 防护，C6 取舍清单在案）不是编辑控件，不命中。
    if (low.includes('<textarea')) editHits.push(f.file + ':<textarea')
    if (/contenteditable\s*[=:]/.test(low)) editHits.push(f.file + ':contentEditable 属性')
    if (/保存/.test(code)) editHits.push(f.file + ':保存语义')
  }
  ok(editHits.length === 0, '查看器文件零编辑控件/零保存语义' + (editHits.length ? '——命中：' + editHits.join(', ') : ''))
}

section('S4 详情文件行=链接 + 背景引用行组')
const idx = files.find(f => f.file === 'index.tsx')
if (!idx) { ok(false, 'client 源缺 index.tsx（详情宿主面）') } else {
  // sc-file 行可点：sc-file 出现处邻近有可点语义（onClick/button/role=button/href）
  let linked = false
  for (const m of idx.text.matchAll(/sc-file/g)) {
    const win = idx.text.slice(m.index, m.index + 400)
    if (/onClick|<button|role="button"|href=/.test(win)) { linked = true; break }
  }
  ok(linked, '状态卡 sc-file 文件行已链接化（邻近可点语义）')
  const refsRow = idx.text.includes('背景引用') && /refs\s*&&|refs\?\.|refs\.length/.test(idx.text)
  ok(refsRow, '「背景引用」行组在场且按 refs 条件渲染（非空才渲染）')
}

section('S5 Escape/遮罩关闭接线（资源终态家族先例）')
let escOk = false
for (const f of anchorFiles) {
  if (/Escape|keydown/.test(f.text) && /onClose|遮罩/.test(f.text)) { escOk = true; break }
}
ok(escOk, '查看器域 Escape/遮罩关闭接线在场')

section('S6 bundle 重建一致（源锚=产物锚，漂移=未同批重建）')
let libText = ''
for (const n of ['client.cjs', 'client.js']) {
  try { libText += readFileSync(join(LIB_DIR, n), 'utf8') } catch { /* 缺一个试下一个 */ }
}
if (!libText) { ok(false, '重建产物 lib/client.cjs|client.js 均不可读（build 缺席）') } else {
  ok(libText.includes(ANCHOR_TESTID_VALUE), 'bundle 含横幅契约锚值（ticket-time-banner）')
  ok(libText.includes('本票时刻'), 'bundle 含横幅人话文案（本票时刻）')
}

console.log('\nSUMMARY pass=' + PASS + ' fail=' + FAIL + ' env_fail=' + ENVFAIL + ' na=' + NA)
process.exit(ENVFAIL > 0 ? 2 : FAIL > 0 ? 1 : 0)
