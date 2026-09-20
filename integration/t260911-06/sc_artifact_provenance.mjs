#!/usr/bin/env node
/**
 * sc_artifact_provenance.mjs —— t260911-06：产物 provenance 闸侧归因点名（KI-073③）。
 *
 * 用户故事：工单票 diff 里出现 server/plugins/workbench/lib/client.{cjs,js} 改动
 * 时，闸（人审/merge）要能机械回答「这份 lib delta 是什么」——而不是像 260911 夜
 * t260911-02 那样被 4 行压缩器写法抖动顶成「越界写 lib/*」误判卡门，或者像
 * t260910-14 那样改了 src 忘重建、源码层全绿而真台面仍旧行为。本场景=票型触发
 * 的闸侧归因器：lib 与 HEAD 有差（=票 diff 含 lib 产物，闸侧可见的触发条件）时，
 * 经唯一构建入口（bash build-client.sh）真实重建一次，把 lib delta 归因到四态：
 *   SAME_BATCH  绿：重建 == 工作树 lib —— 产物与源码同批，delta 是真实构建产物
 *               （合法交付形态，t260910-14 确立的「同批重建产物」）；
 *   STALE       红：构建输入（src/config/lock/构建脚本/兄弟包 src）相对 HEAD 有
 *               改动但重建 != 工作树 lib —— 改了源没同批重建；
 *   FOREIGN     红：输入与 HEAD 同批、重建 == HEAD lib 但工作树 lib != HEAD lib
 *               —— 工具链能逐字节复现 HEAD，delta 却非本链产出=手改/外来工具链
 *               写入（t260911-02 越界误判现场的病灶形态）；
 *   DRIFT       红：输入与 HEAD 同批且重建 != HEAD lib —— 锁定工具链连 HEAD 都
 *               复现不了=工具链/环境漂移（KI-073 核心病灶），diff 首 40 行点名。
 *
 * intent 分工（去重声明，review C1）：与 t260910-15-build-reproducible（常驻回归
 * 面：重建必然逐字节可复现、重建==committed，不问票型）不同面——本条是**票型触发
 * 的闸侧归因点名**（谁只在 lib 有票型 delta 时付重建成本，并把 delta 归因四态）；
 * 与 t260903-04-client-bundle-sync（新鲜度的**特征词面**快守卫，非逐字节、不重建）
 * 不同面；与 t260903-13-workbench-bundle-loads（产物形态合同：外衣头尾/同体/可
 * 加载）不同面。判定器红绿自证（合成样必绿/必咬/畸形输入点名不 crash）守判定器
 * 本身，同 sc_toolchain_pinned「合成锁样必咬」先例。
 *
 * 成本口径（review C8）：常驻干净树（lib 与 HEAD 无差）不触发重建，秒级；仅票型
 * 触发时付一次 npm ci+tsdown（分钟级，与 t260910-15 同量级）。不做「lockfile 一致
 * 跳过 npm ci」捷径——入口唯一性要求真实走唯一入口。登记 exclusive（独占先跑、
 * 不与任何池重叠）：与 t260910-15 等同树构建场景机械互斥——build-client.sh rm 旧
 * 产物后再建，并发互踩会互染判定面（KI-072 负载敏感教训：互斥靠排他不靠运气，
 * main 池缺省并发 3，「串行池」说法不成立）。
 *
 * 触发与红因口径（design_integration_tests 段收口）：触发=逐文件对比两产物与 HEAD，
 * 任一有差即触发——**票删产物（双缺件）也是闸侧必须点名的 delta，判 MISSING 红，
 * 不允许 na 假绿**；classify 显式含 MISSING 态（锚缺件时不误落 FOREIGN/DRIFT 误导
 * 归因）。唯一入口内 npm ci 失败（脚本显式点名「npm ci 失败」）=ENV_FAIL exit 2——
 * 环境红不诬产品（同 15 号 S1 口径），不以 BUILD_FAIL 误诬产品。改源未重建且 lib
 * 无 delta 的新鲜度面归 t260903-04 特征词触发（本条票型=lib 有 delta）。
 *
 * 非破坏性（闸侧纪律）：触发路径先快照工作树 lib 字节，重建取指纹后在 finally
 * 原样写回（红态证据不被重建覆盖、树状态 as-found）；进程被硬杀（SIGKILL）时
 * finally 不执行，lib 可能留在重建态——此时 lib 必为「当前输入的真实产物」，重跑
 * 本场景或唯一入口重建即可复位，红态不静默。git 调用全部只读；零 3099/7233 接触。
 * Exit contract（三态，t260904-12）：末行 SUMMARY pass=N fail=K env_fail=E na=W；
 * fail>0 或全 na → exit 1；env_fail>0 → exit 2。
 */
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

let passed = 0
let failed = 0
let envFail = 0
let naCount = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function na(label) {
  naCount++
  console.log(`  na ${label}`)
}
function section(t) { console.log(`\n== ${t}`) }
function tail(s, n = 6) {
  return (s || '').split('\n').filter(Boolean).slice(-n).map((l) => '    | ' + l).join('\n')
}
const sha256Buf = (buf) => createHash('sha256').update(buf).digest('hex')
const isSha = (s) => typeof s === 'string' && /^[0-9a-f]{64}$/.test(s)

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const wbRel = 'server/plugins/workbench'
const wb = join(root, wbRel)
const LIB_RELS = [`${wbRel}/lib/client.cjs`, `${wbRel}/lib/client.js`]

const BUILD_INPUT_PATHS = [
  `${wbRel}/build-client.sh`,
  `${wbRel}/tsdown.config.ts`,
  `${wbRel}/package.json`,
  `${wbRel}/package-lock.json`,
  `${wbRel}/pnpm-lock.yaml`,
  `${wbRel}/src/`,
  'server/plugins/knowledge/src/',
  'server/plugins/providers/src/',
]

/* ===== 归因判定核心（纯函数，先红绿自证再量真树）===== */
/* 入参：head=HEAD lib 期望 sha（两产物同体取一即可，null=不在 HEAD）、
 * lib=工作树 lib sha、rebuild=唯一入口重建 sha（null=构建失败）、
 * inputsDirty=构建输入相对 HEAD 是否有改动。畸形输入（非 64 位 hex）→
 * BAD_INPUT 点名，绝不 throw——判定器自己先守消费外部输入纪律。 */
function classify({ head, lib, rebuild, inputsDirty }) {
  if (![head, lib, rebuild].every((v) => v === null || isSha(v))) {
    return { verdict: 'BAD_INPUT', red: true, reason: `指纹畸形（须 64 位 hex 或 null）：head=${JSON.stringify(head)} lib=${JSON.stringify(lib)} rebuild=${JSON.stringify(rebuild)}` }
  }
  if (lib === null) return { verdict: 'MISSING', red: true, reason: '工作树 lib 产物缺件：唯一入口失败半旧/手删/被误清——票 diff 含产物删除也是闸侧必须点名的 delta（build-client.sh 先拆旧产物后建，缺件即响亮红）' }
  if (lib === head) return { verdict: 'CLEAN', red: false, reason: 'lib 与 HEAD 无差：票 diff 不含产物，闸不触发' }
  if (rebuild === null) return { verdict: 'BUILD_FAIL', red: true, reason: '唯一入口重建失败，无法归因（先修构建）' }
  if (rebuild === lib) return { verdict: 'SAME_BATCH', red: false, reason: '重建 == 工作树 lib：产物与源码同批（合法交付形态）' }
  if (inputsDirty) return { verdict: 'STALE', red: true, reason: '构建输入相对 HEAD 有改动但重建 != 工作树 lib：改了源没同批重建（t260910-14 病灶）' }
  if (rebuild === head) return { verdict: 'FOREIGN', red: true, reason: '输入与 HEAD 同批、重建逐字节复现 HEAD，但工作树 lib != HEAD：delta 非本链产出=手改/外来工具链写入（t260911-02 越界误判现场形态）' }
  return { verdict: 'DRIFT', red: true, reason: '输入与 HEAD 同批且锁定工具链连 HEAD 都复现不了：工具链/环境漂移（KI-073 核心病灶）' }
}

section('P1. 归因判定器红绿自证（合成样，守判定器非守产品）')
{
  const clean = classify({ head: 'a'.repeat(64), lib: 'a'.repeat(64), rebuild: null, inputsDirty: false })
  ok(clean.verdict === 'CLEAN' && clean.red === false, '合成样：lib==HEAD → CLEAN 不触发')

  const missing = classify({ head: 'a'.repeat(64), lib: null, rebuild: null, inputsDirty: false })
  ok(missing.verdict === 'MISSING' && missing.red === true, '合成样：工作树 lib 缺件 → MISSING 红点名（不误落 FOREIGN/DRIFT）')

  const sameBatch = classify({ head: 'a'.repeat(64), lib: 'b'.repeat(64), rebuild: 'b'.repeat(64), inputsDirty: true })
  ok(sameBatch.verdict === 'SAME_BATCH' && sameBatch.red === false, '合成样：重建==工作树 → SAME_BATCH 绿（同批交付）')

  const stale = classify({ head: 'a'.repeat(64), lib: 'b'.repeat(64), rebuild: 'c'.repeat(64), inputsDirty: true })
  ok(stale.verdict === 'STALE' && stale.red === true, '合成样：输入脏+重建!=工作树 → STALE 红必咬')

  const foreign = classify({ head: 'a'.repeat(64), lib: 'b'.repeat(64), rebuild: 'a'.repeat(64), inputsDirty: false })
  ok(foreign.verdict === 'FOREIGN' && foreign.red === true, '合成样：输入净+重建==HEAD≠工作树 → FOREIGN 红必咬')

  const drift = classify({ head: 'a'.repeat(64), lib: 'b'.repeat(64), rebuild: 'c'.repeat(64), inputsDirty: false })
  ok(drift.verdict === 'DRIFT' && drift.red === true, '合成样：输入净+重建!=HEAD → DRIFT 红必咬（KI-073 核心）')

  const buildFail = classify({ head: 'a'.repeat(64), lib: 'b'.repeat(64), rebuild: null, inputsDirty: true })
  ok(buildFail.verdict === 'BUILD_FAIL' && buildFail.red === true, '合成样：重建失败 → BUILD_FAIL 红点名')

  const bad = classify({ head: 'a'.repeat(64), lib: 'not-a-sha', rebuild: undefined, inputsDirty: false })
  ok(bad.verdict === 'BAD_INPUT' && bad.red === true && typeof bad.reason === 'string' && bad.reason.length > 0,
    '畸形输入自证：非 hex/undefined 指纹 → BAD_INPUT 点名不 crash')
}

/* ===== P2 真树子用例：票型触发才付重建成本 ===== */
function gitSha(rel) {
  const r = spawnSync('git', ['show', `HEAD:${rel}`],
    { cwd: root, encoding: 'buffer', timeout: 60000, maxBuffer: 64 * 1024 * 1024 })
  return r.status === 0 ? sha256Buf(r.stdout) : null
}
function headBytes(rel) {
  const r = spawnSync('git', ['show', `HEAD:${rel}`],
    { cwd: root, encoding: 'buffer', timeout: 60000, maxBuffer: 64 * 1024 * 1024 })
  return r.status === 0 ? r.stdout : null
}
function libDirtyPaths() {
  return execFileSync('git', ['status', '--porcelain', '--', `${wbRel}/lib/`],
    { cwd: root, encoding: 'utf8' }).trim()
}
function inputsDirtyNow() {
  return execFileSync('git', ['status', '--porcelain', '--', ...BUILD_INPUT_PATHS],
    { cwd: root, encoding: 'utf8' }).trim() !== ''
}
/* HEAD 字节 vs 工作树盘上文件的 unified diff 首 40 行（判红证据；行数 40 行内、
 * 总量 4000 字符封顶=闸日志卫生）。restore 后取也恒为真 delta：磁盘=快照=进场景
 * 态，HEAD 字节不随重建变。 */
function diff40(headBytesBuf, diskPath) {
  const tmp = mkdtempSync(join(tmpdir(), 'sc-prov-'))
  try {
    const side = join(tmp, 'side')
    writeFileSync(side, headBytesBuf)
    const r = spawnSync('git', ['diff', '--no-index', '-U1', '--', side, diskPath],
      { cwd: root, encoding: 'utf8', timeout: 60000 })
    return (r.stdout || '').split('\n').slice(0, 40).join('\n').slice(0, 4000)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
}

section('P2. 真树子用例：票型触发 → 唯一入口重建 → 四态归因')
const entryDirty = libDirtyPaths()
{
  const head = gitSha(LIB_RELS[0])
  if (head === null) {
    na('lib/client.cjs 不在 HEAD（产物从未入版本库）：归因无基线，先落产物再闸')
  } else {
    const libPath = join(root, LIB_RELS[0])
    const jsPath = join(root, LIB_RELS[1])
    const present = LIB_RELS.filter((rel) => existsSync(join(root, rel)))
    const cjsSha = existsSync(libPath) ? sha256Buf(readFileSync(libPath)) : null
    const jsSha = existsSync(jsPath) ? sha256Buf(readFileSync(jsPath)) : null
    const jsMissing = jsSha === null
    // 两产物同体（onSuccess 复制）是交付前提：仅 js 漂移（半新产物）也必须触发
    // 归因，不得因 cjs 干净而漏判——同体破裂时以漂移的半边为归因对象；
    // 双缺件（票删产物）同样触发，由 classify 的 MISSING 态点名，不 na 假绿。
    const splitBody = !jsMissing && jsSha !== cjsSha
    const anchorIsJs = jsMissing || splitBody
    const lib = anchorIsJs ? jsSha : cjsSha
    const verdict0 = classify({ head, lib, rebuild: null, inputsDirty: false })
    if (verdict0.verdict === 'CLEAN' && !jsMissing) {
      ok(entryDirty === '', 'lib 与 HEAD 无差：票 diff 不含产物，闸不触发（零重建成本）')
    } else {
      // 触发：快照（仅在场的产物；缺席产物不快照，还原时拆掉重建物保 as-found）
      // → 唯一入口重建 → 归因 → finally 原样写回（非破坏性）
      const snapshot = new Map(present.map((rel) => [rel, readFileSync(join(root, rel))]))
      let rebuild = null
      let buildLog = ''
      let ciEnvFail = false
      try {
        const r = spawnSync('bash', [join(wb, 'build-client.sh')],
          { cwd: wb, encoding: 'utf8', timeout: 600000 })
        buildLog = (r.stdout || '') + (r.stderr || '')
        if (/npm ci 失败/.test(buildLog)) {
          // build-client.sh 显式点名依赖装不上（离线/缓存不可用）：环境红不诬产品
          //（同 15 号 S1 口径），不以 BUILD_FAIL 误诬产品。
          ciEnvFail = true
        } else if (r.error || (r.status ?? 1) !== 0 || !existsSync(libPath)) {
          console.log(`  -- 唯一入口重建非零退出/缺件（status=${r.status}），尾段：\n${tail(buildLog)}`)
        } else {
          rebuild = sha256Buf(readFileSync(libPath))
        }
      } finally {
        for (const [rel, bytes] of snapshot) writeFileSync(join(root, rel), bytes)
        for (const rel of LIB_RELS) {
          if (!snapshot.has(rel) && existsSync(join(root, rel))) rmSync(join(root, rel), { force: true })
        }
      }
      if (ciEnvFail) {
        envFail++
        console.log(`ENV_FAIL: 唯一入口内 npm ci 失败（离线/缓存不可用）——重建取不到锁定依赖树，归因子用例环境红不诬产品；尾段：\n${tail(buildLog)}`)
      } else {
        const inputsDirty = inputsDirtyNow()
        const v = classify({ head, lib, rebuild, inputsDirty })
        const anchor = anchorIsJs ? 'lib/client.js（缺件/半新产物漂移半边）' : 'lib/client.cjs'
        const label = `归因=${v.verdict}${v.red ? '（红）' : '（绿）'}（锚 ${anchor}）：${v.reason}`
        if (v.red) {
          // 红态证据：HEAD vs 工作树 lib delta 的 diff 首 40 行（restore 后取，
          // 磁盘=快照=进场景态、HEAD 字节恒定 → diff 恒为真 delta，不会因
          // 快照==磁盘而落空）
          const anchorRel = anchorIsJs ? LIB_RELS[1] : LIB_RELS[0]
          const anchorPath = anchorIsJs ? jsPath : libPath
          const anchorHead = headBytes(anchorRel)
          ok(false, `${label}\n${anchorHead && existsSync(anchorPath) ? diff40(anchorHead, anchorPath) : '(锚产物缺席，无 diff 可附)'}`)
        } else {
          ok(true, label)
        }
        if (jsMissing) {
          ok(false, 'lib/client.js 缺件（交付契约=双产物同体在场）')
        } else if (splitBody) {
          ok(false, 'cjs ≢ js 同体破裂（半新产物，onSuccess 复制面缺失/被手改单边）')
        }
        ok(libDirtyPaths() === entryDirty,
          '非破坏性自证：重建后工作树 lib 已原样写回（as-found，红态证据不被覆盖）')
      }
    }
  }
}

/* ===== P3 终态自证 ===== */
section('P3. 终态：场景净零副作用（lib 状态与进场景时一致）')
{
  const nowDirty = libDirtyPaths()
  ok(nowDirty === entryDirty || nowDirty.split('\n').every((l) => l.startsWith('M ') || l.startsWith('?? ')),
    `场景结束时 lib/ 无半新产物残留${nowDirty && nowDirty !== entryDirty ? '：\n    ' + nowDirty.split('\n').join('\n    ') : ''}`)
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=${envFail} na=${naCount}`)
process.exit(failed > 0 ? 1 : (passed === 0 && naCount > 0 ? 1 : (envFail > 0 ? 2 : 0)))
