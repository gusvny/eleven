#!/usr/bin/env node
/**
 * t260910-14 场景②：路由真源迁移 UI 面——保存/视图落声明文件 + init 退役。
 *
 * intent（登记于 run_scenarios.py）：
 *   子用例S 保存终态（验收 B/宿主令④d）：saveRoutesTable → 字节级落到声明指向的机器级文件，
 *       且夹具仓 git 工作区零变更（git status --porcelain 空）。
 *   子用例V 视图来源：buildRoutesView.routes_file = 声明指向路径（「生效路径+来源声明」展示面）。
 *   子用例I init 退役（宿主拍板）：initRoutesTable / engineRoutesTemplatePath 导出退场。
 * 三态：node / git 缺席 = ENV_FAIL exit 2；断言破面 = exit 1。
 * 与 t260910-14-routes-resolver-parity 分工（arbitrate 段去重裁定）：python/TS 解析矩阵
 * 一致性守卫归彼条（named 函数双面逐项全等）；本条只锁 UI 读写/展示终态与 init 退役，
 * 不再重复矩阵（原子用例P 已剥，覆盖率由彼条保全，非弱化）。
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const REPO = resolve(new URL('../..', import.meta.url).pathname)
if (!existsSync(join(REPO, 'integration'))) {
  console.log('ENV_FAIL: 仓根解析失败（REPO=' + REPO + '，本文件须在 <repo>/integration/<票>/ 下）')
  process.exit(2)
}
const KEY = 't26091014b'
let fails = 0
const ok = (cond, msg) => { console.log((cond ? 'PASS ' : 'FAIL ') + msg); if (!cond) fails++ }

function envFail (msg) { console.log('ENV_FAIL: ' + msg); process.exit(2) }

// ---- 环境供给（三态 exit 2）----
try { execFileSync('git', ['--version']) } catch { envFail('git 缺席') }

const tmp = mkdtempSync(join(tmpdir(), 't26091014b-'))
try {
  // ---- 夹具：注册表 + 夹具仓（git）+ 机器级表 ----
  const fixRepo = join(tmp, 'fixrepo')
  mkdirSync(join(fixRepo, 'server'), { recursive: true })
  writeFileSync(join(fixRepo, 'server/model-routes.yaml'), 'default:\n  provider: repo-fallback\n  model: repo-model\n')
  execFileSync('git', ['-C', fixRepo, 'init', '-q'])
  execFileSync('git', ['-C', fixRepo, 'add', '-A'])
  execFileSync('git', ['-C', fixRepo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'fixture'])
  const machineDir = join(tmp, 'machine')
  mkdirSync(machineDir, { recursive: true })
  const machine = join(machineDir, 'model-routes.yaml')
  const TABLE_A = 'default:\n  provider: sentinel-default\n  model: default-model\nroles:\n  integration:\n    provider: ui-sentinel\n    model: ui-a\n'
  writeFileSync(machine, TABLE_A)

  const regDir = join(tmp, 'registry')
  const writeReg = (decl) => {
    const d = join(regDir, KEY); mkdirSync(d, { recursive: true })
    const lines = ['schema: v1', 'project:', `  - key: ${KEY}`, '    name: ui parity fixture', '    dirs:', `      - ${fixRepo}`]
    if (decl != null) lines.push('paths:', `  model_routes: ${decl}`)
    writeFileSync(join(d, 'project.yaml'), lines.join('\n') + '\n')
  }

  const routesTs = await import(join(REPO, 'server/plugins/ui/src/host/routes.ts'))
  const ctx = { projectsDir: regDir, projectKey: KEY }

  // ---- 子用例S：保存落声明文件（字节级）+ git 零变更 ----
  writeReg(machine)
  // 载荷形状=现行 RouteTableEdits 契约（{default?, roles?}，RouteEntryEdit {provider?, model?}）
  const res = await routesTs.saveRoutesTable(fixRepo, { default: { model: 'default-model-2' } }, ctx)
  ok(res && res.written === true && String(res.routes_file) === machine,
    `子用例S：保存写声明指向文件（routes_file=${res && res.routes_file}）`)
  const after = readFileSync(machine, 'utf8')
  ok(after.includes('default-model-2'), '子用例S：机器级文件字节级更新（含新 model 值）')
  const dirty = execFileSync('git', ['-C', fixRepo, 'status', '--porcelain'], { encoding: 'utf8' })
  ok(dirty.trim() === '', '子用例S：夹具仓 git 工作区零变更（验收 B/宿主令④d）')

  // ---- 子用例V：视图回传声明路径 ----
  const view = await routesTs.buildRoutesView(fixRepo, ctx)
  ok(String(view.routes_file) === machine, `子用例V：视图生效路径=声明指向文件（${view.routes_file}）`)

  // ---- 子用例I：init 退役 ----
  ok(typeof routesTs.initRoutesTable === 'undefined', '子用例I：initRoutesTable 导出退场（宿主拍板 init 引导不做）')
  ok(typeof routesTs.engineRoutesTemplatePath === 'undefined', '子用例I：engineRoutesTemplatePath 导出退场（仓内模板真源身份终止）')
} catch (e) {
  console.log('FAIL 场景执行中断: ' + String(e && e.message || e).slice(0, 300))
  fails++
} finally {
  try { rmSync(tmp, { recursive: true, force: true }) } catch {}
}
console.log(`t260910-14 routes-ui-parity-save: failed=${fails}`)
process.exit(fails ? 1 : 0)
