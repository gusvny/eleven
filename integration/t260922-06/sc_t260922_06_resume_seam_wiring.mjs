#!/usr/bin/env node
/**
 * integration/t260922-06/sc_t260922_06_resume_seam_wiring.mjs
 * —— headless-resume 插件装载/物化面：整目录拷贝自足 + sibling 导入形状闭合
 *    （t260922-06 场景②，池=ro）。
 *
 * intent（灰盒 L2，守护的用户可感知行为——t260922-06 方案 §5.1 头号遗留风险的机械代理）：
 *   本票把聚合逻辑拆到 sibling 模块 summarize.js，node.ts 以显式 URL 动态导入
 *   （new URL('./summarize.js', import.meta.url)）。这条装载缝一断，症状是每次
 *   spawn 开跑即死（ERR_MODULE_NOT_FOUND → 泳道 agent 起不来），且只在意想不到的
 *   时机现形：引擎把插件【整目录】物化进泳道/容器（agent_activities copytree，
 *   t260913-04 容器缝），物化副本若丢 sibling 或目录改名，真源树单测全绿也救不了
 *   容器里那个副本。用户可感知承诺：
 *   - 插件目录整拷后仍自足可装载：副本内按 node.ts 同款 URL 形状导入 sibling 成功，
 *     导出面完整（summarizeSession / messages 词汇表 / ShapeError）；
 *   - 副本内双形状聚合语义与真源一致（拷贝不改行为）；
 *   - node.ts 声明的每个相对 sibling 引用在目录内闭合（改名/挪位当场红）；
 *   - summarize.js 零依赖契约保持（头注文档化：零依赖是纯函数单测网的存在前提，
 *     破约=单测网静默死亡——在此响亮，不为过测试放宽）。
 *
 * high-level steps：
 *   W1 整目录拷贝（fs.cp recursive = 引擎物化 copytree 的同语义代理）→ 在【副本内】放
 *      探针模块按 URL 形状导入 ./summarize.js → 导出面齐全 + 双形状（legacy events /
 *      v3 eventAt）同 golden 输出等价；
 *   W2 扫描 node.ts 源内全部 new URL('./…') 相对引用 → 逐个在插件目录内存在
 *      （零匹配=URL 导入形状漂移=响亮红，W1 复放前提失效必须点名不静默）；
 *   W3 summarize.js 零依赖静态守卫：无静态 import / 无动态 import( / 无 require(；
 *   W4 副本完整性：node.ts + summarize.js + test/summarize.test.mjs 在副本内（物化
 *      不得静默丢件，t260913-04 容器物化缝同族）。
 *
 * intent 分工：developer L1（server/headless-resume/test/summarize.test.mjs）在真源
 *   目录守 summarize.js 语义；本条守「拷贝副本仍自足可装载且行为不变」（物化面）+
 *   装载形状契约——真源单测过≠副本可装载。live dsh TS loader 对该导入形状的最终裁决
 *   归升级门槛 live 双版对照（RUNBOOK_GATE；本泳道 implement 段 agent 会话
 *   「已恢复会话」行已是装载成功的在案实证）。faces 场景（同目录场景①）守装配行为，
 *   本条守装载/物化，两面不互替。
 *
 * 直跑：node integration/t260922-06/sc_t260922_06_resume_seam_wiring.mjs（node ≥22.18）。
 * 临时目录不可用=ENV_FAIL exit 2；插件目录缺席=产品红。末行 SUMMARY pass= fail= env_fail= na=0。
 */

import { cp, mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = join(HERE, '..', '..')
const PLUGIN_DIR = join(REPO, 'server', 'headless-resume')
const RUNNER = join(PLUGIN_DIR, 'node.ts')
const SUMMARIZE = join(PLUGIN_DIR, 'summarize.js')

let pass = 0, fail = 0, envFail = 0
function ok(cond, label, detail) {
  if (cond) { pass++; return }
  fail++
  console.log(`FAIL ${label}${detail ? '：' + detail : ''}`)
}

const GOLDEN = 'WIRES-OK 标记'

/** 双形状 golden 冒烟（与 faces 场景同构的最小 turn 序列）。 */
function smoke(mod) {
  const turn = [
    { type: 'turn/start', seq: 1 },
    { type: 'assistant/message', seq: 2, data: { message: { content: [{ type: 'text', text: GOLDEN }] } } },
    { type: 'turn/end', seq: 3, data: { reason: { kind: 'completed' } } },
  ]
  const legacy = mod.summarizeSession({ seq: 4, events: turn }, 0, undefined)
  const v3 = mod.summarizeSession({ seq: 3, eventAt: (s) => turn[s] }, 0, (n) => n)
  return { legacy: legacy.text, v3: v3.text }
}

async function main() {
  // 前置：插件目录两真源文件在场（缺席=产品红：真源缺失不是环境缺件）
  let present = true
  for (const f of [RUNNER, SUMMARIZE]) {
    try { await stat(f) } catch { present = false }
  }
  if (!present) {
    console.log('FAIL 前置：插件真源缺席（' + PLUGIN_DIR + ' 下须有 node.ts + summarize.js）')
    console.log('SUMMARY pass=0 fail=1 env_fail=0 na=0')
    process.exit(1)
  }

  // W1 整目录拷贝自足：副本内按 node.ts 同款 URL 形状导入 sibling
  let copyDir = ''
  let copyImport = null
  try {
    copyDir = await mkdtemp(join(tmpdir(), 't26092206-wiring-'))
    await cp(PLUGIN_DIR, join(copyDir, 'headless-resume'), { recursive: true })
    // 探针模块放进【副本内】：import.meta.url 即副本位——与 node.ts 的 URL 导入形状逐字同款
    const probe = join(copyDir, 'headless-resume', '__wiring_probe__.mjs')
    await writeFile(probe, [
      'export const mod = await import(new URL(\'./summarize.js\', import.meta.url).href)',
      '',
    ].join('\n'))
    copyImport = await import(pathToFileURL(probe).href)
  } catch (e) {
    envFail = 1
    console.log('ENV_FAIL: 拷贝/副本内导入失败（临时目录不可用或副本不自足）: ' +
      (e && e.message ? e.message : String(e)))
    console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
    process.exit(2)
  }

  {
    const m = copyImport && copyImport.mod
    ok(m && typeof m.summarizeSession === 'function', 'W1 副本导出 summarizeSession 函数')
    ok(m && m.ShapeError instanceof Function &&
      Object.prototype.toString.call(new m.ShapeError('x')) === '[object Error]',
      'W1 副本导出 ShapeError（Error 子类）')
    const need = ['resumed', 'resumeFailedFallbackCreate', 'sameIdCreateFailedFresh', 'fail',
      'agentReturnShape', 'sessionShapeUnknown', 'sessionSeqMissing', 'seqBad',
      'seqNotReadable', 'eventCorrupt']
    const got = m && m.messages ? Object.keys(m.messages) : []
    ok(need.every((k) => typeof m.messages[k] === 'function'),
      'W1 副本 messages 词汇表齐（4 条 legacy 锚 + 6 条形状面点名）',
      '缺=' + need.filter((k) => !got.includes(k)).join(','))
    if (m && typeof m.summarizeSession === 'function') {
      const r = smoke(m)
      ok(r.legacy === GOLDEN && r.v3 === GOLDEN,
        'W1 副本内双形状聚合语义不变（legacy=golden ∩ v3=golden）', JSON.stringify(r))
    }
  }

  // W2 node.ts 的相对 sibling 引用逐个闭合（零匹配=URL 导入形状漂移=响亮红）
  {
    const src = await readFile(RUNNER, 'utf8')
    const refs = [...src.matchAll(/new URL\('(\.\/[^']+)'/g)].map((mm) => mm[1])
    ok(refs.length > 0, 'W2 node.ts 存在 URL 形状 sibling 引用（形状漂移须当场点名）')
    const missing = refs.filter((r) => !existsSync(join(PLUGIN_DIR, r)))
    ok(missing.length === 0, 'W2 全部 sibling 引用在插件目录内闭合',
      missing.length ? '缺=' + missing.join(',') : undefined)
  }

  // W3 summarize.js 零依赖契约（头注文档化；破约=纯函数单测网静默死亡）
  {
    const src = await readFile(SUMMARIZE, 'utf8')
    const violations = []
    if (/^import\s/m.test(src)) violations.push('静态 import')
    if (/import\s*\(/.test(src)) violations.push('动态 import(')
    if (/\brequire\s*\(/.test(src)) violations.push('require(')
    ok(violations.length === 0, 'W3 summarize.js 零依赖契约保持（无 import/require）',
      violations.join(','))
  }

  // W4 副本完整性（物化不得静默丢件）
  {
    for (const rel of ['node.ts', 'summarize.js', join('test', 'summarize.test.mjs')]) {
      ok(existsSync(join(copyDir, 'headless-resume', rel)), 'W4 副本含 ' + rel)
    }
  }

  await rm(copyDir, { recursive: true, force: true }).catch(() => {})
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=0`)
  process.exit(envFail > 0 ? 2 : fail > 0 ? 1 : 0)
}

main().catch((e) => {
  console.log('ENV_FAIL: 场景自身崩溃（测试缺陷或环境缺件）: ' + (e && e.stack ? e.stack.split('\n')[0] : String(e)))
  console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=${envFail + 1} na=0`)
  process.exit(2)
})
