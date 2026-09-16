#!/usr/bin/env node
// sc_inspection_dual_source_lock.mjs — t260916-05 双真源同步锁的闸内活性（灰盒 L2 离线）。
//
// Intent (user perspective)：工单验收③「双真源收敛……保留则同步锁在场，两者择一并以
// 源码锁钉住」——锁的**断言内容**由 developer 的 workbench UT 交付
// （server/plugins/workbench/tests/t260916-05-inspection-topology-lock.mjs：读引擎
// inspection_flow.py STAGES 声明 ↔ INSPECTION_TOPOLOGY 逐位比对+变异自证腿）；本条守
// 它的**机制活性**：锁文件在集成闸内被真实执行且绿。全仓核实 run_tests.mjs 没有任何
// integration 场景跑点——没有本条，锁只活在 developer 自检里，merge 后改声明忘改词表
// 没有任何机械闸会红（KI-046/049「测试在场≠测试生效/机制活性」家族；t260913
// golden-freeze 补「唯一自动比对点」同族先例）。
//
// 判定：锁文件缺席=fail 点名交付约定路径（TDD 信号非环境——文件缺失=产品面缺失）；
// 执行非零=fail 带 stdout/stderr 尾部（锁红=双真源漂移已发生，恰是本票要抓的形态）；
// exit 0=pass（锁的牙齿在闸内被真实咬合；变异自证腿由锁文件内部断言自证）。
//
// 分工：developer workbench UT=锁本体（L1）；sc_inspection_detail_lane_map_dom=渲染面；
// sc_inspection_topology_receipt=查询回执缝；本条=锁的闸内执行点。
// 路径解析走爬根 helper（KI-075 族：禁宿主绝对路径、禁裸 process.cwd）。
// 纯离线无 ENV_FAIL 腿——node 本体缺席属机器 broken（spawnSync error 即 FAIL 点名）。
// 实现段落地前红属预期（TDD 信号：锁文件未交付=fail），arbitrate/merge 期必须绿。

import { spawnSync } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 仓库根解析：爬根找 CLAUDE.md（t260915-08-inspection-face.mjs 同款范式）。
const REPO = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 8; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根（爬根 8 层无 CLAUDE.md）')
})()

const LOCK_REL = 'server/plugins/workbench/tests/t260916-05-inspection-topology-lock.mjs'
const LOCK = join(REPO, LOCK_REL)

let pass = 0
let fail = 0
function ok(cond, msg) {
  if (cond) { pass++; console.log('  ok', msg) }
  else { fail++; console.log('  FAIL', msg) }
}

if (!existsSync(LOCK)) {
  ok(false, `同步锁文件缺席：${LOCK_REL}（implement 段交付清单承诺路径；缺席=TDD 红非环境）`)
} else {
  ok(true, `同步锁文件在场：${LOCK_REL}`)
  const r = spawnSync('node', [LOCK], { cwd: REPO, encoding: 'utf8', timeout: 120000 })
  if (r.error) {
    ok(false, `锁执行无法启动：${String(r.error).slice(0, 160)}`)
  } else if (r.status !== 0) {
    const tail = ((r.stdout || '') + (r.stderr || '')).split('\n').filter(Boolean).slice(-6)
      .map(l => '    ' + l).join('\n')
    ok(false, `同步锁红（exit=${r.status}，信号=${r.signal || '无'}）——双真源漂移已发生或锁自身缺陷：\n${tail}`)
  } else {
    ok(true, '同步锁在闸内真实执行且绿（id 序+name 逐位比对+变异自证腿由锁文件内部断言自证）')
  }
}

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail > 0 ? 1 : 0)
