// multitab-guard-assets —— t260905-05 静态守卫：19 号豁免体系资产在册（多页签基线）.
//
// Intent (static, repo-asset contract): 本票红线「不改 19 号已落资产语义」+ 验收条款
// 「force 取证守卫保留」的机械面。sc_multi_tab_coexistence.mjs（19 号已落资产）里四类
// 守卫资产在 re-anchor 改造后必须原样在册：
//   G1 诚实红定性标签：PRE_EXISTING_TAG 仍挂 T2 / T5 两条 fail 分支 + failWith catch
//      路径——防「红=正常」习惯化的机制（T2/T5 转绿后标签随 fail 分支自消，但资产
//      本体必须保留；删掉=豁免体系失守，下次真红时无定性可挂）；
//   G2 force 取证守卫：「若 force 后抽屉仍不开=产品红如实落」语义注释 + force: true
//      点击通路——T5b 的取证口径（force 只放宽到达手段，行为断言不变）；
//   G3 三态执行契约：SUMMARY 四计数行 + 退出码分家（fail>0→1 / env_fail>0→2）——
//      t260904-12 词汇表守卫的载体面，弱化=闸内红绿语义失真；
//   G4 T1-T7 族腿清点：七腿 record 名零缺失（新增腿不拦；缺腿=族覆盖收缩，须走票）。
// 与 multi-tab-coexistence 场景 intent 不同面：那边守运行时行为（跨页签语义），
// 本场景守守卫资产在册（豁免体系/取证口径/执行契约），纯 fs 零台面。
// 检测器红绿自证（扫描器纪律，同 installer-console-line 先例）：对真实源先证绿，
// 再对四份变异样本逐规则证红——检测器失明（规则永真）在此现形。
// 本文件刻意不 import lib_browser（其顶层 await 会拉起 docker 台）——纯静态检查
// 不该有台面依赖，故本地实现同款三态 results 助手（词表与退出码契约一致）。

import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'

const REPO = process.cwd()
const TARGET = join(REPO, 'integration', 'baselines', 'sc_multi_tab_coexistence.mjs')

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// ------------------------------------------------------------- 检测器（纯函数）

const FAMILY_LEGS = [
  'T1 presence mutual visibility',
  'T2 write cross-invalidation',
  'T3 hidden tab stops polling',
  'T4 stale detail cannot overwrite drawer',
  'T5 hostile traffic tolerated',
  'T6 closed tab leaves viewer list',
  'T7 zero pageerror/console.error',
]

/** 对一份基线源码逐规则检测；返回 { rule: [违规明细…] }（空数组=该规则过）。 */
function detect(src) {
  const lines = src.split('\n')
  const violations = {}

  // G1 诚实红定性标签：定义在册 + T2/T5 fail 分支与 failWith catch 路径三处引用。
  // 注意腿名在 env_fail 分支也出现（先于 fail 分支），必须钉「'fail' 分支行 + 标签
  // 同行共现」，不能 find 首个同名行（gen0 自证实锤的误报形态）。
  const tag = []
  if (!/const PRE_EXISTING_TAG = /.test(src)) tag.push('PRE_EXISTING_TAG 定义缺失')
  const failBranchTagged = (needle) => lines.some(l =>
    l.includes(needle) && l.includes("'fail'") && l.includes('tagPreExisting()'))
  if (!failBranchTagged("record('T2 write cross-invalidation'")) tag.push("T2 fail 分支未挂 tagPreExisting()")
  if (!failBranchTagged("record('T5 hostile traffic tolerated'")) tag.push("T5 fail 分支未挂 tagPreExisting()")
  const tagLineOf = (needle) => lines.find(l => l.includes(needle))
  const fw = tagLineOf('failWith = async')
  if (!fw || !fw.includes('tagPreExisting()')) tag.push('failWith catch 路径未挂 tagPreExisting()')
  violations['G1 诚实红定性标签'] = tag

  // G2 force 取证守卫：语义注释 + force: true 点击通路。
  const force = []
  if (!src.includes('still does not open after force, that is a real product red')) force.push('force 取证守卫注释（产品红如实落口径）缺失')
  if (!/force: true/.test(src)) force.push('force: true 点击通路缺失')
  violations['G2 force 取证守卫'] = force

  // G3 三态执行契约：SUMMARY 四计数 + 退出码分家（fail 优先 1，env_fail 2）。
  const contract = []
  if (!/SUMMARY pass=\$\{p\} fail=\$\{f\} env_fail=\$\{e\} na=\$\{n\}/.test(src)) contract.push('SUMMARY 四计数行缺失或变形')
  if (!/f > 0 \|\| allNa \? 1 : e > 0 \? 2 : 0/.test(src)) contract.push('退出码分家（1=产品红/2=环境红）缺失或变形')
  violations['G3 三态执行契约'] = contract

  // G4 族腿清点：T1-T7 record 名零缺失（新增不拦、缺腿即红）。
  violations['G4 T1-T7 族腿清点'] = FAMILY_LEGS
    .filter(leg => !src.includes(`record('${leg}'`))
    .map(leg => `族腿缺失：${leg}`)
  return violations
}

const flat = (v) => Object.values(v).flat()

// ------------------------------------------------------------- main

let src = null
try { src = readFileSync(TARGET, 'utf8') } catch { /* 恒红由下方 G 腿报 */ }
if (src === null) {
  record('G0 target readable', 'fail', `基线文件不可读：${TARGET}（19 号资产被移走？）`)
  summarize()
}

// G0 检测器红绿自证：真源逐规则应绿；四份变异样本各让对应规则红。
const realV = detect(src)
const selfProof = []
const mutations = [
  ['G1 诚实红定性标签', src => src.replace(/const PRE_EXISTING_TAG = [^\n]+/, 'const __TAG_REMOVED = ""')],
  ['G2 force 取证守卫', src => src.replace('still does not open after force, that is a real product red', '（注释占位）')],
  ['G3 三态执行契约', src => src.replace(/SUMMARY pass=\$\{p\}[^\n]*/, 'console.log("SUMMARY done")')],
  ['G4 T1-T7 族腿清点', src => src.replaceAll('T7 zero pageerror/console.error', 'T7 hygiene')],
]
for (const [rule, mutate] of mutations) {
  const v = detect(mutate(src))
  if (v[rule].length === 0) selfProof.push(`变异后「${rule}」未触发（检测器失明）`)
}
if (flat(realV).length !== 0) selfProof.push(`真实源被判违规（检测器误报）：${JSON.stringify(realV)}`)
if (selfProof.length === 0) {
  record('G0 detector self-proof', 'pass', '真源全绿 + 四份变异样本逐规则触发')
} else {
  record('G0 detector self-proof', 'fail', selfProof.join('；').slice(0, 200))
}

// G1-G4 对真实源逐规则出腿（违规明细精确到哪条资产缺）。
for (const rule of ['G1 诚实红定性标签', 'G2 force 取证守卫', 'G3 三态执行契约', 'G4 T1-T7 族腿清点']) {
  const v = realV[rule]
  if (v.length === 0) record(rule, 'pass', '在册')
  else record(rule, 'fail', v.join('；').slice(0, 220))
}

// G5 基线本体语法可解析（node --check；改坏即红，不到套件执行时才炸）。
try {
  execFileSync('node', ['--check', TARGET], { encoding: 'utf8', timeout: 15000 })
  record('G5 baseline syntax', 'pass', 'node --check 过')
} catch (e) {
  record('G5 baseline syntax', 'fail', String(e.stderr || e).split('\n')[0].slice(0, 180))
}

summarize()
