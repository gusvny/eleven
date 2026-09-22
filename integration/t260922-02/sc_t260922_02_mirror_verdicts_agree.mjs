/**
 * sc_t260922_02_mirror_verdicts_agree.mjs —— 双代类型面 py↔TS 判据镜像同档对拍
 * （t260922-02，KI-046「冻结镜像、同批改」纪律的行为级守卫，灰盒 L3，池=ro）。
 *
 * intent（用户可感知）：同一份会话档，engine 体检面（settle note/merge warns）
 * 与 workbench 判据面（agent-usage/日志面注记）对「认出多少、缺什么、响不响」
 * 必须给同一结论——两面对拍漂移时，工单台与泳道详情页一响一哑，用户看到互相
 * 矛盾的体检结论（KI-046 同族病的呈现面）。developer 的词表源码锁守「字面
 * 一致」；本条守「真档上判据结论一致」（解析/计数/未覆盖/S1 响度五元组），
 * 字面相同但判据逻辑漂移时只有本条能红。
 *
 * 与 t260922-02-engine-face / workbench-faces 两场景不同面：彼守各自侧的
 * 契约行为，本条守两侧对同一输入的**互等性**（镜像纪律的行为化）。
 *
 * 三态：zstd/python3 缺席、TS 直跑不可用、engine venv 回落链断=ENV_FAIL
 * exit 2 点名；对拍不等=FAIL exit 1。直跑：node integration/t260922-02/
 * sc_t260922_02_mirror_verdicts_agree.mjs（cwd=仓库根）。
 */
import { execFile } from 'node:child_process'
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { makeResults } from './lib_results.mjs'

const P = promisify(execFile)
const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '../..')
const ARCHIVES = ['v011', 'v015', 'abort', 'unknown']

const r = makeResults()

/** 判据对象 → 对拍键（两侧命名归一：parsed/known/usage_records/s1Null/uncovered）。 */
function canonTs(j, s1) {
  return {
    parsed: j.parsed,
    known: j.knownTypes,
    usage_records: j.usageRecords,
    s1Null: s1 === null,
    uncovered: JSON.stringify(j.uncoveredTypes ?? null),
  }
}
function canonPy(o) {
  return {
    parsed: o.parsed,
    known: o.known_types,
    usage_records: o.usage_records,
    s1Null: o.s1 === null,
    uncovered: JSON.stringify(Array.isArray(o.uncovered_types) ? o.uncovered_types : null),
  }
}

async function main() {
  try {
    await P('zstd', ['--version'])
  } catch {
    r.record('env-zstd', 'env_fail', 'zstd CLI 缺席（会话档解析通路依赖 zstd）')
    return r.summarize()
  }
  let live
  try {
    live = await import(join(REPO, 'server/plugins/workbench/src/host/agent-live.ts'))
  } catch (e) {
    const msg = String((e && e.message) || e)
    if (/ERR_UNKNOWN_FILE_EXTENSION|ERR_UNSUPPORTED_TYPESCRIPT|TYPESCRIPT_SYNTAX/.test(msg)) {
      r.record('env-ts-import', 'env_fail', `node 无法直跑 .ts（需 >=22.18 type-stripping）: ${msg.slice(0, 160)}`)
    } else {
      r.record('ts-import', 'fail', `agent-live 导入失败: ${msg.slice(0, 300)}`)
    }
    return r.summarize()
  }
  const tmp = await mkdtemp(join(tmpdir(), 'sc-t260922-02-mirror-'))
  let built
  try {
    const out = await P('python3', [join(HERE, 'lib_t260922_02.py'), 'build', tmp], { timeout: 60000 })
    built = JSON.parse(out.stdout.split('\n').find(l => l.startsWith('{')) ?? '{}')
    if (!built || built.ok !== true) throw new Error('build 输出非 ok')
  } catch (e) {
    r.record('env-fixture-build', 'env_fail', `python3 夹具构造失败: ${String(e && e.message).slice(0, 200)}`)
    return r.summarize()
  }

  for (const k of ARCHIVES) {
    const archive = built.workspaces[k][0]
    let py
    try {
      const out = await P('python3', [join(HERE, 'lib_t260922_02.py'), 'judge', archive], { timeout: 120000 })
      py = JSON.parse(out.stdout.split('\n').find(l => l.startsWith('{')) ?? '{}')
      if (py.ok !== true) throw new Error(py.error ?? 'py judge 非 ok')
    } catch (e) {
      const msg = String((e && e.message) || e)
      if (/temporalio|venv/.test(msg)) {
        r.record(`env-py-judge-${k}`, 'env_fail', `engine python 回落链断: ${msg.slice(0, 160)}`)
        continue
      }
      r.record(`mirror-${k}`, 'fail', `py 侧判据失败: ${msg.slice(0, 200)}`)
      continue
    }
    const text = (await P('zstd', ['-dc', archive])).stdout
    const j = live.judgeSessionLines(text.split('\n'))
    const s1 = live.sessionFaceS1Text(archive.split('/').pop(), j)
    const a = canonPy(py)
    const b = canonTs(j, s1)
    r.check(JSON.stringify(a) === JSON.stringify(b),
      `mirror ${k}：py↔TS 判据五元组互等（parsed/known/usage_records/S1 响度/uncovered）`,
      `py=${JSON.stringify(a)} ts=${JSON.stringify(b)}`)
  }

  return r.summarize()
}

main().catch(e => {
  console.log(`[FAIL] 场景未捕获异常 — ${String((e && e.stack) || e).slice(0, 400)}`)
  console.log('SUMMARY pass=0 fail=1 env_fail=0 na=0')
  process.exit(1)
})
