#!/usr/bin/env node
/**
 * project-admin.mjs —— project CLI 薄 spawn 壳 UT（t260904-15 票③，S2 面）。
 *
 * 直跑：node tests/project-admin.mjs。全走假 CLI 入口（entryPath 测试缝 + tmp
 * fixture 脚本），零触真仓/真注册表。覆盖方案 R1-① 取舍清单的
 * 故障面（含硬性畸形输入用例）：
 *   A. 正常路径：JSON stdout → 解析返回；
 *   B. 非零退出含 stdout JSON 错误体（projects.py FailClosed 口径）→ ProjectCliError
 *      status=409 + body 透传；
 *   C. 非零退出且输出不可解析 → 502，message 含 stderr 截断；
 *   D. exit 0 但 stdout 非 JSON（畸形）→ 502「输出不可解析」；
 *   E. 超时 → 504 点名超时文案，且子进程被回收（kill 后 exit 事件已 await——
 *      调用返回时进程必已退出，用时< 脚本自然时长）；
 *   F. AbortSignal 取消 → 499，同终态回收路径；
 *   G. stdout 超 16MB → 502，进程被回收；
 *   H. repo/entry 锚定：spawn 的 entry=opts.entryPath、cwd=opts.repo（假脚本回显 argv/cwd）。
 */

import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { ProjectCliError, runProjectCli } from './../src/host/project-admin.ts'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const FAKE = `const mode = process.env.PROJECT_FAKE_MODE ?? 'ok'
const argv = JSON.stringify(process.argv.slice(2))
const cwd = process.cwd()
if (mode === 'ok') { console.log(JSON.stringify({ ok: true, mode, argv, cwd })); process.exit(0) }
if (mode === 'fail-json') { console.log(JSON.stringify({ ok: false, error: 'key 形状非法' })); process.exit(1) }
if (mode === 'fail-garbage') { process.stderr.write('traceback: boom'); process.exit(2) }
if (mode === 'reject-text') { console.log('[红] key 不合法：Fix_B'); process.exit(1) }
if (mode === 'garbage') { console.log('not json at all'); process.exit(0) }
if (mode === 'slow') { setTimeout(() => { console.log('{"ok":true}'); process.exit(0) }, 10_000); return }
if (mode === 'big') { let n = 0; const w = () => { while (n < 40 && process.stdout.write('x'.repeat(512 * 1024))) n++; n++; if (n < 40) setTimeout(w, 5); else process.exit(0) }; w(); return }
`

const tmp = mkdtempSync(join(tmpdir(), 'wb-padmin-'))
const entry = join(tmp, 'sandbar')
writeFileSync(entry, FAKE, 'utf8')
const base = { repo: tmp, python: process.execPath, entryPath: entry, timeoutMs: 5_000 }

try {
  section('A 正常路径 + H 锚定回显')
  {
    const out = await runProjectCli(base, ['project', 'list', '--json'])
    ok(out?.ok === true && out.mode === 'ok', 'JSON stdout 解析返回')
    ok(JSON.parse(out.argv).join(' ') === 'project list --json', 'args 原样透传')
    const { realpathSync } = await import('node:fs')
    ok(realpathSync(out.cwd) === realpathSync(tmp), 'spawn cwd=repo（repo 锚定，防异仓执行）')
  }

  section('B 非零退出含 JSON 错误体（FailClosed 口径）')
  {
    let err
    try { await runProjectCli({ ...base }, ['project', 'add'], undefined) } catch (e) { err = e }
    process.env.PROJECT_FAKE_MODE = 'fail-json'
    err = undefined
    try { await runProjectCli(base, ['project', 'add']) } catch (e) { err = e }
    ok(err instanceof ProjectCliError && err.status === 409, '拒收 → 409')
    ok(err?.body?.error === 'key 形状非法', 'stdout JSON 错误体透传（弹层就地显示数据源）')
    ok(err?.message === 'key 形状非法', 'message 取错误体 error 字段')
  }

  section('C exit 2（argv 拼装与 CLI 契约不符）')
  {
    process.env.PROJECT_FAKE_MODE = 'fail-garbage'
    let err
    try { await runProjectCli(base, ['project', 'list']) } catch (e) { err = e }
    ok(err instanceof ProjectCliError && err.status === 502, '→ 502（F3：exit 2=路由自己的 bug，不谎报用户）')
    ok(String(err?.message).includes('参数错误'), '文案点名参数错误')
    ok(String(err?.message).includes('traceback'), 'message 含 stderr 截断原文')
  }

  section('C2 exit 1 且人话非 JSON（票① add 拒收现状口径）')
  {
    process.env.PROJECT_FAKE_MODE = 'reject-text'
    let err
    try { await runProjectCli(base, ['project', 'add']) } catch (e) { err = e }
    ok(err instanceof ProjectCliError && err.status === 409, '→ 409（F3：用户输入拒收≠上游故障）')
    ok(String(err?.message).includes('[红] key 不合法'), '拒收原文转述（就地显示数据源）')
  }

  section('D exit 0 但 stdout 非 JSON（畸形输入硬钩子）')
  {
    process.env.PROJECT_FAKE_MODE = 'garbage'
    let err
    try { await runProjectCli(base, ['project', 'list']) } catch (e) { err = e }
    ok(err instanceof ProjectCliError && err.status === 502, '→ 502 不裸抛 JSON 崩栈')
    ok(String(err?.message).includes('输出不可解析'), '文案点名「输出不可解析」')
  }

  section('E 超时：kill + await exit 终态回收')
  {
    process.env.PROJECT_FAKE_MODE = 'slow'
    const t0 = Date.now()
    let err
    try { await runProjectCli({ ...base, timeoutMs: 300 }, ['project', 'list']) } catch (e) { err = e }
    const dt = Date.now() - t0
    ok(err instanceof ProjectCliError && err.status === 504, '→ 504')
    ok(String(err?.message).includes('超时'), '文案点名超时环节（不谎报无结果）')
    ok(dt < 3_000, `kill 后 await exit 才返回（用时 ${dt}ms ≪ 脚本自然时长 10s，无僵尸）`)
  }

  section('F AbortSignal 取消')
  {
    process.env.PROJECT_FAKE_MODE = 'slow'
    const ac = new AbortController()
    const t0 = Date.now()
    const p = runProjectCli(base, ['project', 'list'], ac.signal).catch(e => e)
    setTimeout(() => ac.abort(), 100)
    const err = await p
    const dt = Date.now() - t0
    ok(err instanceof ProjectCliError && err.status === 499, '取消 → 499')
    ok(dt < 3_000, `取消同终态回收（用时 ${dt}ms，无僵尸）`)
  }

  section('G stdout 超 16MB')
  {
    process.env.PROJECT_FAKE_MODE = 'big'
    let err
    try { await runProjectCli({ ...base, timeoutMs: 15_000 }, ['project', 'list']) } catch (e) { err = e }
    ok(err instanceof ProjectCliError && err.status === 502, '→ 502')
    ok(String(err?.message).includes('16MB'), 'maxBuffer 溢出文案精确')
  }
} finally {
  delete process.env.PROJECT_FAKE_MODE
  rmSync(tmp, { recursive: true, force: true })
}

console.log(`\nPROJECT_ADMIN_TESTS pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
