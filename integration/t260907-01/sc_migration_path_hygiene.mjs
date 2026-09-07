#!/usr/bin/env node
/**
 * sc_migration_path_hygiene.mjs —— t260907-01：移仓收尾路径卫生守卫（工单验收①②回归锚）。
 *
 * 用户故事：宿主已把旧仓（/Users/user/Documents/ 下的 suyou 目录）物理移走（sandbar M2 迁移终验）。
 * 任何仍按旧仓绝对路径解析的代码/调试/冒烟文件，移仓后一用即炸——且多为静默炸
 * （REPO_ROOT 指错→profile 拷空→控制台起不来，报错不指向真因）。本场景把本票
 * 验收口径机械化为常驻守卫：
 *   1) 代码域零旧仓字面量：grep 全仓（排 node_modules/.git/.suyou/.lane/docs/notes）
 *      不得再出现旧仓绝对路径字面量（needle 见下，串接构造）——docs/notes 是历史文档豁免域，
 *      .suyou 是工单台面转录域（例举原文属合法引用）；三个已知残留文件
 *      （server/dsh/README.md、server/dsh/projects.yaml、temporal-poc/README.md）
 *      属另开票处置的显式豁免（命中降为 warn 行，不吞掉其它任何新命中）；
 *   2) 清扫面五文件 node --check 语法健康：.debug-chat.mjs、smoke/agent-live.mjs、
 *      smoke/sessions.mjs、smoke/projects.mjs、tests/capture-stale-banner.mjs
 *      全部可解析（验收②；不直跑 boot 类文件——chrome/dsh/凭据重依赖，见工单）。
 *
 * 灰盒锚点：锚工单验收口径与「代码域无旧仓字面量」合同，不锚任何文件的内部
 * 推导写法。自引用免疫：needle 由串接构造，本文件自身不含该字面量。
 * Exit contract（三态）：末行 SUMMARY pass=N fail=K env_fail=E na=W；
 * fail>0→exit 1，else env_fail>0→exit 2，else exit 0。
 */
import { execFile } from 'node:child_process'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)

let passed = 0
let failed = 0
let envFail = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function envDown(label) { envFail++; console.log(`  ENV_FAIL ${label}`) }
function section(t) { console.log(`\n== ${t}`) }

const REPO = resolve(join(fileURLToPath(import.meta.url), '..', '..', '..'))
// 串接构造：本文件自身不得含旧仓字面量（自引用免疫）
const NEEDLE = '/Users/user/Documents/' + 'suyou'

// 另开票处置的已知残留（t260907-01 review 定案：写集外，登记在案才豁免）
const KNOWN_RESIDUE = new Set([
  'server/dsh/README.md',
  'server/dsh/projects.yaml',
  'server/dsh/temporal-poc/README.md',
])
const SKIP_DIRS = new Set(['node_modules', '.git', '.suyou', '.lane', 'docs', 'notes', '.venv'])

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    let st
    try { st = statSync(p) } catch { continue } // 竞态软链/已删：跳过
    if (st.isDirectory()) {
      if (!SKIP_DIRS.has(name)) yield* walk(p)
    } else if (st.isFile()) {
      yield p
    }
  }
}

section('A 代码域零旧仓字面量（工单验收①）')
{
  const hits = []
  const warned = []
  let scanned = 0
  for (const p of walk(REPO)) {
    const rel = p.slice(REPO.length + 1)
    let text
    try { text = readFileSync(p, 'utf8') } catch { continue } // 二进制/不可读：非扫描面
    scanned++
    if (text.includes(NEEDLE)) {
      if (KNOWN_RESIDUE.has(rel.split(sep).join('/'))) warned.push(rel)
      else hits.push(rel)
    }
  }
  ok(scanned > 500, `扫描面非退化（scanned=${scanned}）`)
  ok(hits.length === 0,
    hits.length === 0
      ? `代码域零旧仓字面量（豁免残留 warn ${warned.length} 处）`
      : `新病灶 ${hits.length} 文件（另开票清单外）：${hits.slice(0, 5).join(' ; ')}`)
  for (const w of warned) console.log(`  warn 豁免残留（另开票处置）：${w}`)
}

section('B 清扫面五文件语法健康（工单验收②，node --check）')
{
  const files = [
    'server/dsh/ui-check/.debug-chat.mjs',
    'server/dsh/workbench/smoke/agent-live.mjs',
    'server/dsh/workbench/smoke/sessions.mjs',
    'server/dsh/workbench/smoke/projects.mjs',
    'server/dsh/workbench/tests/capture-stale-banner.mjs',
  ]
  for (const rel of files) {
    try {
      await execFileP(process.execPath, ['--check', join(REPO, rel)], { timeout: 30_000 })
      ok(true, `node --check 过：${rel}`)
    } catch (e) {
      if (e.code === 'ENOENT') { envDown(`node 不可用（${rel} 无法检查）`); continue }
      const first = String(e.stderr || e.message).split('\n')[0] || ''
      ok(false, `node --check 红：${rel}（${first.slice(0, 120)}）`)
    }
  }
}

const na = 0
console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${na}`)
process.exit(failed > 0 ? 1 : envFail > 0 ? 2 : 0)
