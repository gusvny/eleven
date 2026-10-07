/**
 * capture-stale-banner.mjs —— t260902-03 横幅可见态实拍（隔离台，不碰 3099）。
 *
 * 动机：capture-lane 的常规 7 视图只覆盖「新鲜态无横幅」（fingerprint boot==disk）。
 * 本脚本补拍横幅可见态：把泳道 server/plugins/workbench 拷进临时 fixture repo → 隔离台
 * 起真控制台（boot 指纹=fixture）→ 改 fixture 的 node.ts 内容（模拟合并落账不重启）
 * → 等 client 30s 轮询命中 → 拍「工单台视图横幅常驻」。fixture 是真文件拷贝，控制台
 * 全部行为真实，只有「落账」这一步是脚本触发的。
 *
 * 红线：临时端口（内核分配）+ 临时 DSH_HOME（退出即删）+ 不碰 3099 + 不 seed 数据。
 * 用法：node server/plugins/workbench/tests/capture-stale-banner.mjs [outDir]
 * 依赖：系统 Chrome（headless）；playwright-core 从主树供给（泳道不装依赖，先例
 *       boot-and-run-s1.mjs / capture.mjs loadPlaywright 同款）。
 *
 * ⚠️ 260929 修（两道同族伤，都在「本轮直修」批次里）：
 *   ① **会话门**（KI-156 同族）：dsh 0.1.5 起匿名 `GET /` 恒 401，旧 waitReady 只认
 *      `res.ok` ⇒ 台其实已起来却恒判「未就绪」→ 90s 超时退出 1，第 6 步永远走不到。
 *      修法=照 capture-lane.mjs 先例：可达（200/303/401）即算服务在场，并从
 *      console.log 抓 `?token=` 首页地址当导航入口（浏览器不带 token 只会拍到 401 页）。
 *   ② **视图图标锚 + 静默跳过**：第 6 步原用 `[title="立项单"]`（宿主令 260925 英文化后
 *      ＝`Epics`）且写成 `if (epicsBtn) {...}`——锚点一错整步被静默跳过、脚本照样 exit 0，
 *      等于把「横幅跨视图常驻」这条断言悄悄删掉（假绿）。现在：锚=插件英文真源，
 *      元素不在场=明确红并报出 DOM 实有 title 清单；横幅消失也从 WARN 升为红。
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
const LANE_WB = join(LANE, 'server', 'plugins', 'workbench')
const OUT = process.argv[2] || join(LANE, '.suyou', 'screenshots')
const CAPTURE_LANE = pathToFileURL(join(LANE, 'server', 'ui-check', 'capture-lane.mjs')).href

const { buildTempProfile, materializePresets, presetMaterializeRejectReason } = await import(CAPTURE_LANE)

function pickFreePort() {
  return new Promise((res, rej) => {
    const srv = createServer()
    srv.listen(0, '127.0.0.1', () => { const p = srv.address().port; srv.close(() => res(p)) })
    srv.on('error', rej)
  })
}

// 默认 'dsh --profile sandbar'（260908 终切：旧名链已删，正身链指向 server/profile）。
const consoleCmd = (process.env.SANDBAR_CONSOLE_CMD || 'dsh --profile sandbar').split(' ')
const tmpHome = mkdtempSync(join(tmpdir(), 'sandbar-stale-banner-'))
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

/** 从 console.log 抓带 token 的首页地址（会话门兑换用；capture-lane.mjs authUrlFromLog 同款）。
 *  dsh 0.1.5 起匿名 GET / 恒 401——不带 token 导航只会拍到 401 页。 */
function authUrlFromLog(logPath) {
  try {
    const log = readFileSync(logPath, 'utf8')
    const m = log.match(/https?:\/\/[^\s"'<>]*[?&]token=[A-Za-z0-9._~-]+/g)
    return m ? m[m.length - 1] : ''
  } catch { return '' }
}

async function waitReady(port, timeoutMs, logPath) {
  const t0 = Date.now()
  let reachable = false
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/`)
      // 401=浏览器会话门（服务已在场）；303/200=已放行。只有连不上才继续等。
      if (res.ok || res.status === 401 || res.status === 303) reachable = true
      if (reachable) {
        const auth = authUrlFromLog(logPath)
        if (auth) return auth
      }
    } catch { /* 未就绪，继续轮询 */ }
    await new Promise(r => setTimeout(r, 500))
  }
  let tail = ''
  try { tail = readFileSync(logPath, 'utf8').slice(-2000) } catch {}
  throw new Error(reachable
    ? `隔离台 ${timeoutMs}ms 内已可达但取不到带 token 首页地址（127.0.0.1:${port}；会话门需 /?token= 兑换 cookie）。日志尾部：\n${tail || '（无日志）'}`
    : `隔离台 ${timeoutMs}ms 内未就绪（127.0.0.1:${port}）。日志尾部：\n${tail || '（无日志）'}`)
}

// playwright 加载：候选=本泳道 ui-check/node_modules（泳道 checkout 常不装，KI-036②）
// → SANDBAR_PLAYWRIGHT_MODULE 指主树 playwright-core 包目录（既有 env，capture-lane
// 已会传，非本票新增）。镜像 capture.mjs loadPlaywright 先例（t260901-03）。
async function loadPlaywright() {
  const candidates = [
    join(LANE, 'server', 'ui-check', 'node_modules', 'playwright-core'),
  ]
  if (process.env.SANDBAR_PLAYWRIGHT_MODULE) candidates.push(process.env.SANDBAR_PLAYWRIGHT_MODULE)
  for (const dir of candidates) {
    if (!existsSync(join(dir, 'index.js'))) continue
    const mod = await import(pathToFileURL(join(dir, 'index.js')).href)
    return mod.default ?? mod // CJS 包经 ESM import 时导出在 default 下
  }
  throw new Error('playwright-core 未找到：先在 server/ui-check/ 下 npm install，'
    + '或设 SANDBAR_PLAYWRIGHT_MODULE 指向主树的 playwright-core 包目录')
}

async function main() {
  // 1) fixture repo：拷 workbench（跳过 smoke/node_modules 等无关物）
  await mkdirSync ? null : null
  mkdirSync(fixtureRepo, { recursive: true })
  // 整个 server 拷进 fixture（各 profile 插件都要 repo 结构；跳过 node_modules）
  await cp(join(LANE, 'server'), join(fixtureRepo, 'server'), {
    recursive: true,
    filter: (src) => !src.includes('node_modules'),
  })
  const fixtureWb = join(fixtureRepo, 'server', 'plugins', 'workbench')

  // 2) 临时 profile（workbench 插件指向 fixture build）+ preset + 凭据
  const userDsh = [process.env.DSH_HOME, join(process.env.HOME || '', '.dsh')]
    .filter(Boolean).find(d => existsSync(join(d, '.credentials.yaml')))
    || process.env.DSH_HOME || join(process.env.HOME || '', '.dsh')
  if (existsSync(join(userDsh, '.credentials.yaml'))) {
    copyFileSync(join(userDsh, '.credentials.yaml'), join(tmpHome, '.credentials.yaml'))
  }
  await buildTempProfile(tmpHome, fixtureWb)
  const presetSrc = process.env.SANDBAR_CAPTURE_PRESET_SOURCE
    || join(process.env.HOME || '', '.dsh', '.agent-presets', 'sandbar-integration')
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
      // SANDBAR_REPO 必须钉到 fixture 仓（260929 修前提缺口）：workbench 的 repo 锚=
      // config.repo → SANDBAR_REPO → 按本文件位置推导（node.ts:405），而 /api/build-info
      // 的 disk 指纹按该 repo 根扫 server/plugins/workbench/{node.ts,src/**}——环境里
      // 已导出 SANDBAR_REPO（本机实测 =<主仓>）时，改 fixture 的 node.ts 对指纹**不可见**，
      // boot≡disk ⇒ 横幅永不出现（本步恒红，且是「前提没满足」不是产品缺陷）。
      // 同族先例：integration/t260904-17/lib_fix17.mjs:223 与
      // integration/t260916-26/lib_t260916_26_bench.mjs:104 均显式把 SANDBAR_REPO
      // 指夹具仓，本脚本漏钉。
      SANDBAR_REPO: fixtureRepo,
      SANDBAR_TARGET_HOST: process.env.SANDBAR_CAPTURE_TARGET_HOST
        || process.env.SANDBAR_TARGET_HOST || '127.0.0.1:17233',
    },
    detached: true, stdio: ['ignore', logFd, logFd],
  })
  const navUrl = await waitReady(port, Number(process.env.SANDBAR_STALE_BOOT_MS || 90000), join(tmpHome, 'console.log'))
  console.log(`[capture-stale-banner] 隔离台就绪：127.0.0.1:${port}（带 token 入口=已取到）`)
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
    // 导航入口=带 token 的首页地址（会话门兑换 cookie；匿名 goto 拍到的是 401 页）
    await page.goto(navUrl || `http://127.0.0.1:${port}/`, { waitUntil: 'domcontentloaded' })
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
    try {
      await page.waitForSelector('.wb-stale-banner', { timeout: 45_000 })
    } catch (e) {
      // 报错精确（260929）：横幅不出现时把**判定数据面**打出来——陈旧判定走
      // /api/build-info 的 boot/disk/injected 三元组（build-info.ts 指纹 + staleness.ts
      // 30s 轮询 + stale-check.ts 矩阵），没有这份回执只能猜（是端点没算、指纹根指错、
      // 还是轮询没跑）。
      const diag = await page.evaluate(async () => {
        const out = {}
        try {
          const r = await fetch('/sandbar-workbench/api/build-info')
          out.status = r.status
          out.body = (await r.text()).slice(0, 400)
        } catch (err) { out.fetchError = String(err) }
        out.visibility = document.visibilityState
        out.injected = (() => { try { return window.sessionStorage.getItem('wb.build.fingerprint.atload') } catch { return 'n/a' } })()
        out.comments = document.querySelectorAll('.wb-stale-banner').length
        return out
      }).catch((err) => ({ evaluateError: String(err) }))
      console.error('[capture-stale-banner] 横幅未出现的判定数据面=' + JSON.stringify(diag))
      throw e
    }
    await new Promise(r => setTimeout(r, 1000))
    await page.screenshot({ path: join(OUT, 'stale-banner-1-visible.png') })
    console.log('[capture-stale-banner] 横幅可见态已拍')

    // 6) 切视图验证常驻：t261005-10 (UI-2) 起 Epics/Docs/Tickets 视图图标退役——
    //    中列唯一存活切换=项目名行进入执行器面板（[data-wb-executor-entry]，UI-1 起
    //    项目名即执行器入口）。三态纪律不变：入口缺席=明确红（上方 [data-wb-psess-row]
    //    在场已证插件挂载，缺席只能是入口改名/未渲染=真缺陷），横幅消失=红。
    const viewTitles = await page.$$eval('.wb-view-icon',
      els => [...new Set(els.map(e => e.getAttribute('title')).filter(Boolean))])
    const execEntry = await page.$('[data-wb-executor-entry]')
    if (!execEntry) {
      console.error(`[capture-stale-banner] FAIL：侧栏无执行器入口（DOM 实有 view icon title=${viewTitles.join(',') || '无 .wb-view-icon'}）`
        + '——入口改名或未渲染；本步断言不可跳过（三态纪律：缺席不当通过）')
      teardown(); process.exit(1)
    }
    await execEntry.click()
    await new Promise(r => setTimeout(r, 1500))
    const still = await page.$('.wb-stale-banner')
    if (!still) {
      console.error('[capture-stale-banner] FAIL：executor 面板视图下 stale 横幅消失（应跨视图常驻）')
      teardown(); process.exit(1)
    }
    await page.screenshot({ path: join(OUT, 'stale-banner-2-executor-view.png') })
    console.log('[capture-stale-banner] executor 面板视图横幅常驻已拍（锚 [data-wb-executor-entry]）')
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
