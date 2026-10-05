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
 *      （server/README.md、server/projects.yaml、engine/README.md）
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
  'server/README.md',
  'server/projects.yaml',
  'server/engine/README.md',
])
// .sandbar=泳道台面记录（工单原文引用旧路径属历史记录域，与 notes/ 同口径——t260907-10 arbitrate gen1 补排除）
// out/=运行期/测试生成产物面（仓根 out/ 与 server/engine/out/ 同口径）：集成报告/快照把
// 被测进程 traceback 与输出尾逐字转录，含历史绝对路径属**事实记录**；out/sandbox-repo 更是
// 隔离测试自建的沙箱仓副本（非本仓代码）。与 .suyou/.sandbox/data 同类豁免
// （t260907-01 收口同款理由；t260913-02 arbitrate 实测 out/sandbox-repo/* 命中）
// out/=运行产物/报告落档域（进程物目录：out/integration-report-*.json 由执行器每轮写，
//   其 timings.tail 逐字转发场景回执——被转发原文含旧仓绝对路径属事实记录，与 .log/.sandbar
//   同口径排除；不排除即「执行器自己写的报告把自己判成新病灶」的自污染假红，
//   t260914-01 arbitrate gen2 实测：out/integration-report-260914-102037.json 即此形态）。
//   扫描面意图不变=**源码/文档域**零旧仓字面量；out/ 内不放源码（脚本/源码在 server/、integration/）。
// data/（260928 补，与 out/ 同口径）：引擎**运行时数据域**——`server/engine/data/` 下是
// worker PID/meta、`temporal.db`（近 400MB 的 Temporal 本地库）、`admin.log` 等进程物，
// 全部 gitignored 且零跟踪文件（`git ls-files | grep 'data/'` = 0，可复核）。它被 walk 到后
// `readFileSync(utf8)` 照样把二进制读进来：库里逐字存着历史绝对路径 ⇒ 判成「新病灶」假红，
// 顺带每轮白读 400MB（260928 实测红：`新病灶 1 文件：server/engine/data/temporal.db`）。
// 扫描面意图不变=**源码/文档域**零旧仓字面量。
// .dsh（261005 补，与 data/ 同口径）：dsh 运行时会话域——.dsh/storages/session_projcache/ 是
// 控制台会话工程缓存（进程物，gitignored 零跟踪），历史会话记录里带旧仓绝对路径属事实数据
// 而非代码（t261005-16 泳道实红：泳道自身的会话缓存里记着 suyou 路径被误判「新病灶」）。
// 扫描面意图不变=源码/文档域零旧仓字面量。
const SKIP_DIRS = new Set(['node_modules', '.git', '.suyou', '.lane', '.sandbar', 'docs', 'notes', '.venv', 'out', 'data', '.dsh'])

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    let st
    try { st = statSync(p) } catch { continue } // 竞态软链/已删：跳过
    if (st.isDirectory()) {
      if (!SKIP_DIRS.has(name)) yield* walk(p)
    } else if (st.isFile()) {
      // *.log=追加式运行审计流水（gitignored，如 server/admin.log 499MB）：闸口回执
      // 逐字引用历史工单原文（含旧仓绝对路径属事实记录），与 .suyou/.sandbar 运行时
      // 记录同口径排除；顺带省掉每次全量读大日志的扫描成本（t260907-01 收口补）
      if (name.endsWith('.log')) continue
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
    'server/ui-check/.debug-chat.mjs',
    'server/plugins/workbench/smoke/agent-live.mjs',
    'server/plugins/workbench/smoke/sessions.mjs',
    'server/plugins/workbench/smoke/projects.mjs',
    'server/plugins/workbench/tests/capture-stale-banner.mjs',
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
