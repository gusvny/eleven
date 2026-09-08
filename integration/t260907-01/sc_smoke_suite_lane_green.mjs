#!/usr/bin/env node
/**
 * sc_smoke_suite_lane_green.mjs —— t260907-01：移仓后 smoke 资产面泳道直跑全绿。
 *
 * 用户故事：本票清扫的 smoke 文件不是摆设——下次任何人按 README/注释直跑
 * `node smoke/xxx.mjs`，必须从泳道 worktree 起就全绿，而不是「脚本在场、
 * 一跑环境红」习惯化（KI-038 族教训：红=正常会淹掉真回归）。本场景以仓库根
 * 为 cwd，从泳道内直跑三支零依赖纯函数冒烟（与工单验收③执行面同源）：
 *   projects.mjs（项目注册表解析器）、sessions.mjs（会话记账层）、
 *   agent-live.mjs（cwd-slug/会话定位/动态流路由，zstd 缺席时其 C/D 段自降级，
 *   退出码语义不变）。断言各自 exit 0 且 passed>0 failed=0。
 *
 * 与 L1 的分工：三支 smoke 自身的函数断言是 developer 的 UT 面；本场景守的是
 * 「泳道环境里可执行且绿」这一用户可感知的健康面（环境合同，非函数行为），
 * intent 不同层不重复。
 *
 * 灰盒锚点：锚 smoke 的直跑契约（exit code + passed/failed 末行口径），
 * 不锚其内部断言。零端口、零 3099、零网络。
 * Exit contract（三态）：末行 SUMMARY pass=N fail=K env_fail=E na=W；
 * fail>0→exit 1，else env_fail>0→exit 2，else exit 0。
 */
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
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
const WB = join(REPO, 'server', 'plugins', 'workbench')

section('A 三支纯函数 smoke 泳道直跑全绿')
{
  const smokes = ['smoke/projects.mjs', 'smoke/sessions.mjs', 'smoke/agent-live.mjs']
  for (const rel of smokes) {
    const p = join(WB, rel)
    if (!existsSync(p)) { ok(false, `smoke 资产缺失：${rel}（仓库面破，非环境）`); continue }
    try {
      const { stdout } = await execFileP(process.execPath, [rel], { cwd: WB, timeout: 180_000 })
      const m = stdout.match(/(\d+) passed, (\d+) failed/)
      ok(m && Number(m[1]) > 0 && Number(m[2]) === 0,
        `${rel} exit 0 且 passed>0 failed=0（${m ? `${m[1]} passed` : '末行口径缺失'}）`)
    } catch (e) {
      if (e.code === 'ENOENT') { envDown(`node 不可用（${rel} 无法直跑）`); continue }
      const tail = String(e.stdout || e.stderr || e.message).slice(-300).replace(/\n+/g, ' | ')
      ok(false, `${rel} 直跑红（exit=${e.code}）：${tail}`)
    }
  }
}

const na = 0
console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${na}`)
process.exit(failed > 0 ? 1 : envFail > 0 ? 2 : 0)
