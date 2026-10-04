/**
 * list-cap-check.test.mjs —— t261004-14：机械检查自身的 UT。
 *  - 真渲染源（src/host 全量）当前必须过（所有上限都已声明或显式豁免）；
 *  - 夹具目录里的未声明截断（Math.min(x, 3)、slice(0, 12)、循环上界字面量）必须逐条红；
 *  - **数值巧合不豁免**：slice(0, 12) 与 recent_actions 声明的 12 数值相同也必须红
 *    （review_plan 条件 1：上限只能以名字引用，不能靠数值相等免费过）；
 *  - LIST-CAP-OK 注释豁免生效，且「写了豁免却没有截断」不误导（不计豁免、不算违规）；
 *  - 未声明上限必须以名字（declaredCap / LIST_CONTRACTS / RECENT_ACTIONS_CAP）引用才放行。
 * 零网络、零 3099 触碰。
 */
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, freshDir, cleanup, done } from './lib.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolveRepo()
function resolveRepo() { return join(here, '../../../..') } // tests → executor-panel → plugins → server → repo root
const CHECK = join(repo, 'server/plugins/executor-panel/check_list_caps.mjs')
let n = 0

function runCheck(target) {
  const r = spawnSync(process.execPath, ['--experimental-strip-types', CHECK, target], { encoding: 'utf8' })
  return { code: r.status, out: (r.stdout || '') + (r.stderr || '') }
}

// ---- 1. 真源当前必须全绿 ----
{
  const r = runCheck(join(repo, 'server/plugins/executor-panel/src/host'))
  assert(r.code === 0, 'real render sources pass the cap check (violations below)\n' + r.out)
  assert(/violations=0/.test(r.out), 'check reports zero violations on the real tree')
}

// ---- 2. 夹具：未声明截断逐条红（含数值巧合案例） ----
const bad = freshDir('capcheck-bad-')
mkdirSync(join(bad, 'nested'), { recursive: true })
const cases = [
  ['a_render.ts', 'const shown = rows.slice(0, 12)\n'],
  ['b_render.ts', 'for(var k=0;k<Math.min(wakes.length,3);k++){}\n'],
  ['nested/c_render.ts', 'for(var i=0;i<8;i++){}\n'],
]
for (const [f, body] of cases) writeFileSync(join(bad, f), body)
{
  const r = runCheck(bad)
  assert(r.code === 1, 'undeclared caps fail the check')
  for (const frag of ['slice(0, <integer>)', 'Math.min with integer', 'loop bound', 'a_render.ts:1', 'b_render.ts:1', 'nested/c_render.ts:1']) {
    assert(r.out.includes(frag), 'violation reported: ' + frag)
  }
  // 数值巧合：12 与已声明上限同值，仍红——目录里没有声明表，检查不认数值
  assert(r.out.includes('slice(0, <integer>) truncation') && r.out.includes('a_render.ts'),
    'slice(0, 12) fails even though 12 equals a declared cap (no value-coincidence pass)')
}
cleanup([bad])

// ---- 3. 豁免与命名引用 ----
const good = freshDir('capcheck-good-')
writeFileSync(join(good, 'ok.ts'),
  'const who = whoRaw.slice(0, 64) // LIST-CAP-OK: storage field length limit, not a list cap\n' +
  'const shown = rows.slice(0, declaredCap("ledger_last_wakes"))\n' +
  'const head = s.slice(0, s.indexOf("/"))\n')
{
  const r = runCheck(good)
  assert(r.code === 0, 'named cap reference and justified exemption pass\n' + r.out)
  assert(/exempted=1/.test(r.out), 'exemption counted once')
}
cleanup([good])

// ---- 4. 空豁免注释（写了 LIST-CAP-OK 但行内没有截断形态）不算违规也不计豁免 ----
const noop = freshDir('capcheck-noop-')
writeFileSync(join(noop, 'noop.ts'), 'const a = 1 // LIST-CAP-OK: nothing to exempt here\n')
{
  const r = runCheck(noop)
  assert(r.code === 0, 'stray exemption marker is not a violation')
  assert(/exempted=0/.test(r.out), 'stray exemption marker not counted as exemption')
}
cleanup([noop])

n += 14
done(n)
