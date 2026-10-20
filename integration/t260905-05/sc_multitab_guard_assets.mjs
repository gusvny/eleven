// multitab-guard-assets —— t260905-05 静态守卫：多页签基线资产的**退役面**在册（t261012-05 反转）.
//
// Intent (static, repo-asset contract): 本场景原守 sc_multi_tab_coexistence.mjs（19 号
// 已落资产）的四类守卫资产在册（PRE_EXISTING_TAG 诚实红标签 / force 取证守卫 / 三态执行
// 契约 / T1-T7 族清点）。261002 宿主令把 multi-tab-coexistence 场景整体退役
// （integration/retired-scenarios.md「multi-tab-coexistence（t260901-15）」条 +
// run_scenarios.py 退役留痕注记），资产文件随之删除——守卫的**被钉对象没了**，
// G0「基线文件不可读」每跑必红（261012 闸实锤）。同一批退役漏扫的在场清单欠账
// （同族实案：t260912-01 CONSUMERS 清单、本场景自身）。
//
// t261012-05 反转（票面「修合理的、删不合理的；本票不从套件删条目」）：守卫对象反转为
// **退役面本身**——退役是宿主裁定，裁定不得被静默回潮：
//   R1 资产缺席面：sc_multi_tab_coexistence.mjs 不得回来（文件再现=退役被推翻，须走票）；
//   R2 注记在场面：run_scenarios.py 的退役留痕注记（「multi-tab-coexistence：261002 宿主令退役」）在册；
//   R3 台账在场面：retired-scenarios.md 的 multi-tab-coexistence 条目在册（退役三要素之一）；
//   R4 名号休眠面：SCENARIOS 无该名在册条目（「在册恒过=SKIP 复辟变体」同族——退役后
//      重新注册却无场景文件，runner 会以文件缺失红或恒过，两头都不诚实）。
// 检测器红绿自证（扫描器纪律，同 installer-console-line 先例）：对真实仓面先证绿，
// 再对变异样本逐规则证红——检测器失明（规则永真）在此现形。
// 本文件刻意不 import lib_browser（其顶层 await 会拉起 docker 台）——纯静态检查
// 不该有台面依赖，本地实现同款三态 results 助手（词表与退出码契约一致）。
// 若宿主要求把本条目也从套件退役（守卫随被守对象同退），那是票面裁定：删 SCENARIOS
// 条目一行即可，本文件留痕 retired-scenarios.md。本票不执行该删除。

import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const TARGET = join(REPO, 'integration', 'baselines', 'sc_multi_tab_coexistence.mjs')
const REGISTRY = join(REPO, 'integration', 'run_scenarios.py')
const RETIRED_MD = join(REPO, 'integration', 'retired-scenarios.md')

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

/** 对仓面逐规则检测；返回 { rule: [违规明细…] }（空数组=该规则过）。
 *  face = { targetExists, registryText, retiredText }——全部只读事实，便于变异自证。 */
function detect(face) {
  const v = {}
  const abs = []
  if (face.targetExists) abs.push('退役资产文件再现：integration/baselines/sc_multi_tab_coexistence.mjs（退役被推翻须走票，不得静默回流）')
  v['R1 资产缺席面'] = abs

  const marker = []
  if (!/multi-tab-coexistence：261002 宿主令退役/.test(face.registryText)) {
    marker.push('run_scenarios.py 退役留痕注记缺失（退役三要素：定稿条款引用/主库承接/留痕）')
  }
  v['R2 注记在场面'] = marker

  const ledger = []
  if (!/### multi-tab-coexistence/.test(face.retiredText)) {
    ledger.push('retired-scenarios.md 缺 multi-tab-coexistence 条目（退役台账断链）')
  }
  v['R3 台账在场面'] = ledger

  const dormant = []
  const liveEntry = face.registryText.match(/^\s*\("multi-tab-coexistence"/m)
  if (liveEntry) dormant.push('SCENARIOS 出现 multi-tab-coexistence 在册条目（退役名号复用=在册恒过/SKIP 复辟变体，须走票）')
  v['R4 名号休眠面'] = dormant
  return v
}

const flat = (vv) => Object.values(vv).flat()

// ------------------------------------------------------------- main

const face = {
  targetExists: existsSync(TARGET),
  registryText: readFileSync(REGISTRY, 'utf8'),
  retiredText: readFileSync(RETIRED_MD, 'utf8'),
}

// G0 检测器红绿自证：真实仓面逐规则应绿；变异样本各让对应规则红。
const realV = detect(face)
const selfProof = []
const mutations = [
  ['R1 资产缺席面', (f) => ({ ...f, targetExists: true })],
  ['R2 注记在场面', (f) => ({ ...f, registryText: f.registryText.replace('multi-tab-coexistence：261002 宿主令退役', '（注记占位）') })],
  ['R3 台账在场面', (f) => ({ ...f, retiredText: f.retiredText.replace('### multi-tab-coexistence', '### （条目占位）') })],
  ['R4 名号休眠面', (f) => ({ ...f, registryText: f.registryText + '\n    ("multi-tab-coexistence", "intent", "cmd"),\n' })],
]
for (const [rule, mutate] of mutations) {
  const vv = detect(mutate(face))
  if (vv[rule].length === 0) selfProof.push(`变异后「${rule}」未触发（检测器失明）`)
}
if (flat(realV).length !== 0) selfProof.push(`真实仓面被判违规（检测器误报）：${JSON.stringify(realV)}`)
if (selfProof.length === 0) {
  record('G0 detector self-proof', 'pass', '真实仓面全绿 + 四份变异样本逐规则触发')
} else {
  record('G0 detector self-proof', 'fail', selfProof.join('；').slice(0, 200))
}

// R1-R4 对真实仓面逐规则出子用例（违规明细精确到哪条退役面缺）。
for (const rule of ['R1 资产缺席面', 'R2 注记在场面', 'R3 台账在场面', 'R4 名号休眠面']) {
  const vv = realV[rule]
  if (vv.length === 0) record(rule, 'pass', '在册')
  else record(rule, 'fail', vv.join('；').slice(0, 220))
}

summarize()
