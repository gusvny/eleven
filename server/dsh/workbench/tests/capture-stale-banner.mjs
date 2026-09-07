/**
 * capture-stale-banner.mjs —— t260902-03 横幅可见态实拍（隔离台，不碰 3099）。
 *
 * 动机：capture-lane 的常规 7 视图只覆盖「新鲜态无横幅」（fingerprint boot==disk）。
 * 本脚本补拍横幅可见态：把泳道 server/dsh/workbench 拷进临时 fixture repo → 隔离台
 * 起真控制台（boot 指纹=fixture）→ 改 fixture 的 node.ts 内容（模拟合并落账不重启）
 * → 等 client 30s 轮询命中 → 拍「工单台视图横幅常驻」。fixture 是真文件拷贝，控制台
 * 全部行为真实，只有「落账」这一步是脚本触发的。
 *
 * 红线：临时端口（内核分配）+ 临时 DSH_HOME（退出即删）+ 不碰 3099 + 不 seed 数据。
 * 用法：node integration/t260902-03/capture-stale-banner.mjs [outDir]
 * 依赖：系统 Chrome（headless）；playwright-core 从主树供给（泳道不装依赖，先例
 *       boot-and-run-s1.mjs / capture.mjs loadPlaywright 同款）。
 */

import { spawn } from 'node:child_process'
import { closeSync, copyFileSync, existsSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync, mkdtempSync } from 'node:fs'
import { cp, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = join(fileURLToPath(import.meta.url), '..')
const LANE = resolve(HERE, '..', '..', '..', '..')
const LANE_WB = join(LANE, 'server', 'dsh', 'workbench')
const OUT = process.argv[2] || join(LANE, '.suyou', 'screenshots')
const CAPTURE_LANE = pathToFileURL(join(LANE, 'server', 'dsh', 'ui-check', 'capture-lane.mjs')).href

const { buildTempProfile, materializePresets, presetMaterializeRejectReason } = await import(CAPTURE_LANE)

function pickFreePort() {
  return new Promise((res, rej) => {
    const srv = createServer()
    srv.listen(0, '127.0.0.1', () => { const p = srv.address().port; srv.close(() => res(p)) })
    srv.on('error', rej)
  })
}

// SUYOU_CONSOLE_CMD 名是历史欠账不动（工单原则）；默认 'dsh --profile suyou' 实测
// 仍通：~/.dsh/profiles/suyou 软链已指向 sandbar 仓 server/dsh/profile（260907 复核）。
const consoleCmd = (process.env.SUYOU_CONSOLE_CMD || 'dsh --profile suyou').split(' ')
const tmpHome = mkdtempSync(join(tmpdir(), 'suyou-stale-banner-'))
/** fixture repo：泳道 workbench 的真拷贝（src/lib/node.ts），boot 指纹算它。 */
const fixtureRepo = join(tmpHome, 'repo')
let proc = null, logFd = null, tornDown = false
function teardown(code = 0) {
  if (tornDown) return
  tornDown = true
  if (proc && proc.pid && proc.exitCode === null && proc.signalCode === null) {
    try { process.kill(-proc.pid, 'SIGTERM') } catch { try { proc.kill('SIGKILL') } catch {} }
  }
  if (logFd !== null) { try { closeSync(logFd) } catch {} }
  try { rmSync(tmpHome, { recursive: true, force: true }) } catch {}
}
process.on('exit', () => teardown())
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { teardown(); process.exit(130) })

async function waitReady(port, timeoutMs, logPath) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    try { const res = await fetch(`http://127.0.0.1:${port}/`); if (res.ok) return } catch {}
    await new Promise(r => setTimeout(r, 500))
  }
  let tail = ''
  try { tail = readFileSync(logPath, 'utf8').slice(-2000) } catch {}
  throw new Error(`隔离台 ${timeoutMs}ms 内未就绪（127.0.0.1:${port}）。日志尾部：\n${tail || '（无日志）'}`)
}

// playwright 加载：候选=本泳道 ui-check/node_modules（泳道 checkout 常不装，KI-036②）
// → SUYOU_PLAYWRIGHT_MODULE 指主树 playwright-core 包目录（既有 env，capture-lane
// 已会传，非本票新增）。镜像 capture.mjs loadPlaywright 先例（t260901-03）。
async function loadPlaywright() {
  const candidates = [
    join(LANE, 'server', 'dsh', 'ui-check', 'node_modules', 'playwright-core'),
  ]
  if (process.env.SUYOU_PLAYWRIGHT_MODULE) candidates.push(process.env.SUYOU_PLAYWRIGHT_MODULE)
  for (const dir of candidates) {
    if (!existsSync(join(dir, 'index.js'))) continue
    const mod = await import(pathToFileURL(join(dir, 'index.js')).href)
    return mod.default ?? mod // CJS 包经 ESM import 时导出在 default 下
  }
  throw new Error('playwright-core 未找到：先在 server/dsh/ui-check/ 下 npm install，'
    + '或设 SUYOU_PLAYWRIGHT_MODULE 指向主树的 playwright-core 包目录')
}

async function main() {
  // 1) fixture repo：拷 workbench（跳过 smoke/node_modules 等无关物）
  await mkdirSync ? null : null
  mkdirSync(fixtureRepo, { recursive: true })
  // 整个 server/dsh 拷进 fixture（各 profile 插件都要 repo 结构；跳过 node_modules）
  await cp(join(LANE, 'server', 'dsh'), join(fixtureRepo, 'server', 'dsh'), {
    recursive: true,
    filter: (src) => !src.includes('node_modules'),
  })
  const fixtureWb = join(fixtureRepo, 'server', 'dsh', 'workbench')

  // 2) 临时 profile（workbench 插件指向 fixture build）+ preset + 凭据
  const userDsh = [process.env.DSH_HOME, join(process.env.HOME || '', '.dsh')]
    .filter(Boolean).find(d => existsSync(join(d, '.credentials.yaml')))
    || process.env.DSH_HOME || join(process.env.HOME || '', '.dsh')
  if (existsSync(join(userDsh, '.credentials.yaml'))) {
    copyFileSync(join(userDsh, '.credentials.yaml'), join(tmpHome, '.credentials.yaml'))
  }
  await buildTempProfile(tmpHome, fixtureWb)
  const presetSrc = process.env.SUYOU_CAPTURE_PRESET_SOURCE
    || join(process.env.HOME || '', '.dsh', '.agent-presets', 'suyou-integration')
  const presetReject = presetMaterializeRejectReason(presetSrc)
  if (presetReject) { console.error(`[capture-stale-banner] 拒跑：${presetReject}`); process.exit(2) }
  await materializePresets(tmpHome, presetSrc)

  // 3) 起隔离台控制台
  const port = await pickFreePort()
  logFd = openSync(join(tmpHome, 'console.log'), 'a')
  const portPatch = join(tmpHome, 'port_patch.yml')
  writeFileSync(portPatch, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`, 'utf8')
  proc = spawn(consoleCmd[0], [...consoleCmd.slice(1), '--patch', portPatch,
    '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
    cwd: LANE,
    env: {
      ...process.env,
      DSH_HOME: tmpHome,
      SUYOU_TARGET_HOST: process.env.SUYOU_CAPTURE_TARGET_HOST
        || process.env.SUYOU_TARGET_HOST || '127.0.0.1:17233',
    },
    detached: true, stdio: ['ignore', logFd, logFd],
  })
  await waitReady(port, Number(process.env.SUYOU_STALE_BOOT_MS || 90000), join(tmpHome, 'console.log'))
  console.log(`[capture-stale-banner] 隔离台就绪：127.0.0.1:${port}`)
  await new Promise(r => setTimeout(r, 1500))
  try {
    const probe = await fetch(`http://127.0.0.1:${port}/`)
    console.log(`[capture-stale-banner] 复探：${probe.status}；子进程 exitCode=${proc.exitCode}`)
  } catch (e) {
    console.log(`[capture-stale-banner] 复探失败：${e.message}；子进程 exitCode=${proc.exitCode} signal=${proc.signalCode}`)
  }

  const playwright = await loadPlaywright()
  let browser
  try {
    try { browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
    catch { browser = await playwright.chromium.launch({ headless: true }) }
    const page = await browser.newPage()
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'domcontentloaded' })
    // 等 workbench 侧栏挂载（项目会话区行锚——顶部行入口锚已随票② R8 退役，
    // 项目行是 R8 后恒在场的侧栏锚；C1 顺修，t260904-05）
    await page.waitForSelector('[data-wb-psess-row]', { timeout: 30_000 })
    // 关掉出厂 Internal Testing Notice 弹层（遮横幅），不判失败
    try {
      const cont = await page.$('button:has-text("Continue")')
      if (cont) { await cont.click({ timeout: 5000 }); await new Promise(r => setTimeout(r, 500)) }
    } catch { /* 无弹层或点不动=不阻断 */ }

    // 4) 拍新鲜态（应无横幅）
    mkdirSync(OUT, { recursive: true })
    await page.screenshot({ path: join(OUT, 'stale-banner-0-fresh.png') })
    console.log('[capture-stale-banner] 新鲜态已拍（应无横幅）')

    // 5) 模拟合并落账：改 fixture 的 node.ts 内容 → 等 30s 轮询 + margin
    await writeFile(join(fixtureWb, 'node.ts'),
      readFileSync(join(fixtureWb, 'node.ts'), 'utf8') + '\n// stale-watchdog landed change\n')
    await page.waitForSelector('.wb-stale-banner', { timeout: 45_000 })
    await new Promise(r => setTimeout(r, 1000))
    await page.screenshot({ path: join(OUT, 'stale-banner-1-visible.png') })
    console.log('[capture-stale-banner] 横幅可见态已拍')

    // 6) 切视图验证常驻（点「立项单」图标——若可见）
    const epicsBtn = await page.$('[title="立项单"]')
    if (epicsBtn) {
      await epicsBtn.click()
      await new Promise(r => setTimeout(r, 800))
      const still = await page.$('.wb-stale-banner')
      if (still) {
        await page.screenshot({ path: join(OUT, 'stale-banner-2-epics-view.png') })
        console.log('[capture-stale-banner] 立项单视图横幅常驻已拍')
      } else console.log('[capture-stale-banner] WARN：立项单视图横幅消失（不应发生）')
    }
    const bannerCount = await page.$$eval('.wb-stale-banner', els => els.length)
    console.log(`[capture-stale-banner] 终态横幅数=${bannerCount}`)
    teardown()
    process.exit(0)
  } finally {
    try { await browser?.close() } catch {}
    teardown()
  }
}

main().catch(err => {
  let tail = ''
  try { tail = readFileSync(join(tmpHome, 'console.log'), 'utf8').slice(-2000) } catch {}
  console.error(`[capture-stale-banner] FAIL：${err.message}\nconsole.log 尾部：\n${tail || '（无日志）'}`)
  teardown(); process.exit(1)
})
