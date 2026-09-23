#!/usr/bin/env node
/**
 * session-start-version-shim.mjs —— 「新建会话」启动面的双版容错回归
 * （260923 事故：dsh 0.1.5 把 UI 工作区服务拆成 `uiWorkspace`（有 startSession）与
 *  `workspaces`（纯控制器，无此方法）；插件按 0.1.1 直呼 `ctx.workspaces.startSession`
 *  → `TypeError: workspaces.startSession is not a function`，用户侧「新建会话失败：
 *  请求异常」，**所有项目一起坏**）。
 *
 * 直跑：node tests/session-start-version-shim.mjs（node ≥22.18 原生 type-stripping）。
 * 覆盖三层：
 *   A. resolveStartSession 纯逻辑：双面在位时取前者（0.1.5 优先）／只有旧面时回落
 *      （0.1.1 兼容）／两面都没有→抛精确错误（点名两版各自所在面，不甩裸 TypeError）／
 *      候选为 null/undefined/非对象一律跳过／`this` 绑回宿主（平台实现是类方法）。
 *   B. 源码静态看守：session-entry.tsx 不得再直呼 `workspaces.startSession(`；
 *      两处调用点都走 startWorkspaceSession；hook 依赖数组带上它；
 *      index.tsx 把 uiWorkspace 传下去且**在渲染期取值**（apply 期取会拿到 undefined）。
 *   C. 产物同构：lib/client.js（浏览器实际跑的那份）里同样有 resolveStartSession 面与
 *      精确报错文案——防「改了 src 没重建」。
 *
 * 为什么要有 B/C：这条链原先**零测试覆盖**（grep startSession 在 tests/ 下 0 命中），
 * 平台服务面换名/迁移没人管，事故就是这么漏出去的。
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { resolveStartSession, START_SESSION_MISSING } from '../src/shared/workspaces-compat.ts'

const here = dirname(fileURLToPath(import.meta.url))
const srcEntry = join(here, '..', 'src', 'client', 'session-entry.tsx')
const srcIndex = join(here, '..', 'src', 'client', 'index.tsx')
const srcSidebar = join(here, '..', 'src', 'client', 'sidebar.tsx')
const libClient = join(here, '..', 'lib', 'client.js')

let passed = 0, failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ── A. 纯逻辑 ───────────────────────────────────────────────────────────── */
section('A. resolveStartSession（双版容错解析）')

{
  const calls = []
  // 0.1.5 平台形态：uiWorkspace 是类方法（依赖 this），workspaces 无 startSession
  const uiWorkspace = { id: 'ui', startSession(id) { calls.push(['ui', id, this?.id]) } }
  const pureController = { list: {}, create() {} }
  const f = resolveStartSession([uiWorkspace, pureController])
  f('ws-1')
  ok(calls.length === 1 && calls[0][0] === 'ui', '0.1.5 形态：取 uiWorkspace 的 startSession')
  ok(calls[0][2] === 'ui', 'this 绑回宿主（类方法不得丢 this）')
  ok(calls[0][1] === 'ws-1', 'workspaceId 透传')
}

{
  const calls = []
  // 0.1.1 形态：只有 workspaces 有 startSession
  const legacy = { startSession(id) { calls.push(id) } }
  resolveStartSession([undefined, legacy, {}])('ws-2')
  ok(calls.length === 1 && calls[0] === 'ws-2', '0.1.1 形态：回落 workspaces 的 startSession')
}

{
  // 两面都没有 → 精确报错（点名两版所在面），不是 TypeError
  let err = null
  try { resolveStartSession([{ list: {} }, {}, null, undefined]) } catch (e) { err = e }
  ok(err instanceof Error, '两面都没有：抛 Error')
  ok(err && err.message === START_SESSION_MISSING, '错误消息＝START_SESSION_MISSING 常量（两端同源）')
  ok(!!err && /uiWorkspace/.test(err.message) && /纯控制器/.test(err.message),
    '消息点名「0.1.5 在 uiWorkspace／workspaces 是纯控制器」——诊断不被引向错误方向')
  ok(!!err && typeof err.message === 'string' && !/is not a function/.test(err.message),
    '不甩裸 TypeError 文案')
}

{
  let err = null
  try { resolveStartSession([]) } catch (e) { err = e }
  ok(err instanceof Error, '空候选列表：同样抛精确错误（不静默返回 undefined）')
}

/* ── B. 源码静态看守 ─────────────────────────────────────────────────────── */
section('B. 源码静态看守（防复发）')

const entry = readFileSync(srcEntry, 'utf8')
const index = readFileSync(srcIndex, 'utf8')
const sidebar = readFileSync(srcSidebar, 'utf8')

// 直呼旧面：只允许出现在注释里（形如 ` * ...workspaces.startSession...`）
const directCalls = entry.split('\n')
  .map((line, i) => ({ line: line.trim(), no: i + 1 }))
  .filter(({ line }) => /(^|[^.\w])workspaces\.startSession\s*\(/.test(line) && !line.startsWith('*') && !line.startsWith('//'))
ok(directCalls.length === 0, `session-entry.tsx 无直呼 workspaces.startSession( 的活代码（发现 ${directCalls.length} 处）`)

const callSites = (entry.match(/startWorkspaceSession\(ws\.workspaceId\)/g) ?? []).length
ok(callSites === 2, `两处调用点都走 startWorkspaceSession（实测 ${callSites} 处）`)

ok(/resolveStartSession\(\[uiWorkspace, workspaces\]\)/.test(entry),
  'hook 内解析＝resolveStartSession([uiWorkspace, workspaces])（0.1.5 优先）')
ok(/\[uiWorkspace, workspaces\],/.test(entry), 'useCallback 依赖数组含两面')
ok(/^\s*}, \[openSession,.*startWorkspaceSession\]\)/m.test(entry), 'handleOpen 依赖数组含 startWorkspaceSession')
ok(/^\s*}, \[workspaces, sessions, projectKey, projectDir, creating, persist, notify, startWorkspaceSession\]\)/m.test(entry),
  'handleNew 依赖数组含 startWorkspaceSession')

ok(/uiWorkspace=\{\(\(ctx as any\)\.uiWorkspace \?\? \(ctx as any\)\.get\?\.\('uiWorkspace'\)\) as any\}/.test(index),
  'index.tsx 在渲染期取 uiWorkspace（两形态：属性面 + ctx.get）')
ok(/uiWorkspace,/.test(sidebar) && /uiWorkspace\?: \{/.test(sidebar), 'sidebar.tsx 透传 uiWorkspace（含类型声明）')
// inject 纪律：不得把 uiWorkspace 加进 inject（0.1.1 无此服务＝永久 pending）
const injectLine = (index.match(/^export const inject = .*$/m) ?? [''])[0]
ok(!/uiWorkspace/.test(injectLine), `inject 未加 uiWorkspace（0.1.1 无此服务＝entry 永久 pending）：${injectLine.trim()}`)

/* ── C. 产物同构 ─────────────────────────────────────────────────────────── */
section('C. lib/client.js 产物同构（防「改了 src 没重建」）')

const lib = readFileSync(libClient, 'utf8')
ok(lib.includes('startSession 不可用：dsh 0.1.5 起该 API 在 uiWorkspace 上'),
  '产物里带精确报错文案（证明已重建）')
ok(/resolveStartSession/.test(lib), '产物里带 resolveStartSession')
ok(!/workspaces\.startSession\(ws\.workspaceId\)/.test(lib),
  '产物里没有旧直呼（否则浏览器仍在跑旧代码）')

console.log(`\n${failed === 0 ? 'PASS' : 'FAIL'} session-start-version-shim: pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
