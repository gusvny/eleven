#!/usr/bin/env node
// stage_client_boot.mjs —— stage 控制台 client 半 web boot 断言（t260916-26，
// 验收②③的 client 半仪器）。
//
// 背景：dsh 的插件装载断言分两半——宿主半 loader entry 经
// POST /api/pluginInventory/list 可编程投影（stage_docker.py plugins 子命令）；
// client 半（浏览器内 web boot）只在浏览器里跑：`web boot: N entries did not
// activate` / `Failed to load plugins` 横幅是前端 assertEntriesActive 的产物，
// 宿主端点看不到。本探针用真浏览器把 client 半的断言补上：
//   token 兑换 cookie（dsh web 进程令牌 → 浏览器会话）→ 打开控制台 →
//   等 boot 收敛 → 断言零失败横幅 → 截图落证。
//
// 用法：
//   node integration/stage_client_boot.mjs --url http://127.0.0.1:3199 \
//        [--token <t>] [--cookie name=value] [--out <png>] [--timeout <sec>]
//   鉴权三选一：--token（GET /?token= 兑换 cookie）/ --cookie（直接带会话
//   cookie，token 已过期但 cookie 仍活的场景）/ 都缺省（试无鉴权台）；
//   401/unauthorized → 如实红并提示 token 来源（dsh web 启动输出行的 ?token=…）。
//
// 退出码（三态契约）：0=boot 收敛且零失败横幅；2=boot 失败/横幅在/
//   unauthorized/超时/环境缺依赖；stdout 回 JSON 回执（含截图路径；所有终态
//   路径都先截屏再退——失败帧就是证据）。
// 全终态回收：browser 在 shutdown 单点关闭；SIGINT/SIGTERM 先收尾再退；
// 看门狗 = --timeout+10s 硬顶（轮询逻辑挂死的最后一道）。

import { mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { loadPlaywright, pwMissingDetail, REPO_ROOT } from './lib_pw_deps.mjs'

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name)
  return i !== -1 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt
}

const url = arg('url')
const token = arg('token')
const cookieArg = arg('cookie')
const timeoutSec = Number(arg('timeout', '60'))
const out = resolve(arg('out', join(REPO_ROOT, '.sandbar', 'screenshots',
  `stage-client-boot-${(url && URL.canParse(url) && new URL(url).port) || 'console'}.png`)))

function emit(obj) { console.log(JSON.stringify(obj, null, 1)) }

if (!url || !/^https?:\/\//.test(url) || !URL.canParse(url)) {
  emit({ ok: false, reason: 'usage', hint: '需要 --url http://127.0.0.1:<端口>；token 见控制台启动输出的 ?token= 行' })
  process.exit(2)
}

// playwright-core 依赖（位置无关解析，lib_pw_deps 唯一真源）
const pw = await loadPlaywright()
if (!pw) {
  emit({ ok: false, reason: 'env', url, detail: pwMissingDetail() })
  process.exit(2)
}

// ---- 浏览器会话：单点 shutdown（正常/失败/超时/信号四路全收）
// 浏览器获取对齐 ui-check/capture.mjs 先例：优先系统 Chrome（channel:"chrome"），
// 探测不到退 playwright 自带 chromium。
async function launchBrowser() {
  try {
    return await pw.chromium.launch({ channel: 'chrome', headless: true })
  } catch { /* 系统 Chrome 不可用 → 退自带 chromium（再失败由调用侧红） */ }
  return pw.chromium.launch({ headless: true })
}
const browser = await launchBrowser()
let page = null
let settled = false
async function shutdown(code, payload) {
  if (settled) return
  settled = true
  try {
    if (page) {
      mkdirSync(resolve(out, '..'), { recursive: true })
      await page.screenshot({ path: out, fullPage: false }).catch(() => {})
    }
  } catch { /* 截图失败不掩盖断言结果 */ }
  try { await browser.close() } catch { /* 已死即达终态 */ }
  if (payload) emit({ screenshot: out, ...payload })
  process.exit(code)
}
process.on('SIGINT', () => void shutdown(2, { ok: false, reason: 'interrupted' }))
process.on('SIGTERM', () => void shutdown(2, { ok: false, reason: 'terminated' }))
const watchdog = setTimeout(() => void shutdown(2, {
  ok: false, reason: 'timeout', url,
  detail: `${timeoutSec + 10}s 看门狗到点（renderer 挂死或网络黑）`,
}), (timeoutSec + 10) * 1000)

try {
  const context = await browser.newContext()
  let cookies = []
  if (cookieArg) {
    const m = cookieArg.match(/^([^=\s]+)=([^;\s]+)$/)
    if (!m) await shutdown(2, { ok: false, reason: 'usage', url, hint: '--cookie 形状 name=value' })
    cookies.push({ name: m[1], value: m[2], url })
  } else if (token) {
    // 与浏览器地址栏打开同款兑换：GET /?token= → 303 + set-cookie。
    const res = await fetch(new URL('/?token=' + encodeURIComponent(token), url), { redirect: 'manual' })
    const setCookie = res.headers.get('set-cookie')
    if (!setCookie) {
      await shutdown(2, {
        ok: false, reason: 'token_exchange_failed', url,
        hint: 'GET /?token= 未返回会话 cookie——token 过期或不对（dsh web 启动输出行）',
      })
    }
    const m = setCookie.split(';')[0].match(/^([^=]+)=([^;]*)$/)
    if (!m) await shutdown(2, { ok: false, reason: 'token_exchange_failed', url, detail: 'set-cookie 形状不辨' })
    cookies.push({ name: m[1], value: m[2], url })
  }
  if (cookies.length) await context.addCookies(cookies)
  page = await context.newPage()
  const t0 = Date.now()
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutSec * 1000 })

  // boot 收敛判定：轮询页面文本——失败信号出现即红；#root 有渲染内容且连续
  // 两拍无失败文本 → 复查一拍（给 web boot 的 assertEntriesActive 留激活窗）
  // 仍无失败信号 → 绿。
  const FAILURE_PATTERNS = [/did not activate/, /Failed to load plugins/i, /unauthorized/i]
  let calm = 0
  let lastText = ''
  const deadline = Date.now() + timeoutSec * 1000
  while (Date.now() < deadline) {
    lastText = await page.evaluate(() => document.body?.innerText?.slice(0, 4000) ?? '')
    const hit = FAILURE_PATTERNS.find((re) => re.test(lastText))
    if (hit) {
      await shutdown(2, {
        ok: false, reason: 'boot_failure', url,
        detail: `页面出现失败信号 /${hit.source}/`, text: lastText.slice(0, 600),
      })
    }
    const rooted = await page.evaluate(() => {
      const r = document.querySelector('#root')
      return !!r && r.children.length > 0
    })
    calm = rooted ? calm + 1 : 0
    if (calm >= 2) {
      await page.waitForTimeout(1500)
      const recheck = await page.evaluate(() => document.body?.innerText?.slice(0, 4000) ?? '')
      const rehit = FAILURE_PATTERNS.find((re) => re.test(recheck))
      if (rehit) {
        await shutdown(2, {
          ok: false, reason: 'boot_failure', url,
          detail: `收敛复查出现失败信号 /${rehit.source}/`, text: recheck.slice(0, 600),
        })
      }
      await shutdown(0, {
        ok: true, url, elapsedMs: Date.now() - t0,
        note: 'client 半 web boot 收敛：无 did-not-activate / Failed-to-load 横幅',
      })
    }
    await page.waitForTimeout(600)
  }
  await shutdown(2, { ok: false, reason: 'timeout', url, detail: `${timeoutSec}s 内 boot 未收敛`, text: lastText.slice(0, 400) })
} catch (e) {
  await shutdown(2, { ok: false, reason: 'error', url, detail: String(e?.message ?? e).slice(0, 300) })
} finally {
  clearTimeout(watchdog)
  await shutdown(2, { ok: false, reason: 'unexpected_exit', url })
}
