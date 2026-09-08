#!/usr/bin/env node
/**
 * sc_epic_anchor_same_source.mjs — UI×CLI 立项目录同源同规（t260907-07 验收③）。
 *
 * intent（用户可感知）：同一立项单、工单台列得出、CLI 开票也认——同一注册表真源
 * +同一拼装规则 <主目录>/notes/epics。断言：双项目夹具下
 * Py resolve_epics_dir(key) === TS resolveEpicsDir(primaryDir(findProject(key)))
 * 且各指各自主目录（非引擎仓锚）；SANDBAR_EPICS_DIR 覆盖两侧同款（同指 env 目录）。
 * 口径边界（方案 C4）：断言的是「同规」——不覆盖「工单台起在非项目注册主目录」
 * 部署形态（工单台 repo=config.repo 时 UI 仍锚其 repo）。
 *
 * 与 developer L1 intent 不同面：本场景守 Py/TS 两侧解析同源（注册表装载器两侧
 * 同构的接线契约），非单侧函数行为。
 * Run: node integration/t260907-07/sc_epic_anchor_same_source.mjs（cwd=仓库根）
 * 三态：SUMMARY 四计数；exit 0/1/2（python 子进程不可得=ENV_FAIL exit 2）。
 */
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { resolveEpicsDir } from '../../server/plugins/workbench/src/host/epics.ts'
import { findProject, primaryDir } from '../../server/project-registry.ts'
import { makeEpicFixture, runPython } from './epic_fixture.mjs'

const { ok, envFail, done } = (await import('../t260903-09/lib_integration.mjs')).makeChecker()

const POC = new URL('../../server/engine', import.meta.url).pathname

/** 子进程跑 Py 侧解析（同一次夹具、同一份注册表），返回 {engine, external} 或 null。 */
function pyResolveDirs(regRoot, extraEnv = {}) {
  const code = `
import sys, json
sys.path.insert(0, ${JSON.stringify(POC)})
import shared
print(json.dumps({k: str(shared.resolve_epics_dir(k)) for k in ('engine', 'external')}))
`
  try {
    return JSON.parse(runPython(code, { SANDBAR_PROJECTS_DIR: regRoot, SANDBAR_EPICS_DIR: '', ...extraEnv }).trim())
  } catch (e) {
    envFail('Py resolve_epics_dir 子进程', String(e).slice(0, 200))
    return null
  }
}

const fx = makeEpicFixture()
try {
  process.env.SANDBAR_PROJECTS_DIR = fx.regRoot
  delete process.env.SANDBAR_EPICS_DIR

  const py = pyResolveDirs(fx.regRoot)
  if (py) {
    for (const p of [fx.engine, fx.external]) {
      const tsDir = resolveEpicsDir(primaryDir(findProject(p.key)))
      ok(tsDir === p.epicsDir, `A TS ${p.key} 锚项目主目录 notes/epics`, tsDir)
      ok(py[p.key] === p.epicsDir, `B Py ${p.key} 锚项目主目录 notes/epics`, py[p.key])
      ok(tsDir === py[p.key], `C 同源：${p.key} Py==TS`, `${py[p.key]} vs ${tsDir}`)
    }
    ok(resolveEpicsDir(primaryDir(findProject('engine'))) !== fx.external.epicsDir,
       'D 不串桶：engine 锚 ≠ external 桶')
  }

  // env 覆盖两侧同款（自测语义）：SANDBAR_EPICS_DIR 在场 → Py/TS 同指 env 目录
  const envRoot = await mkdtemp(join(tmpdir(), 't26090707-same-src-env-'))
  const envDir = join(envRoot, 'notes', 'epics')
  await mkdir(envDir, { recursive: true })
  await writeFile(join(envDir, 'env-only.md'), '# env-only\n', 'utf8')
  process.env.SANDBAR_EPICS_DIR = envDir
  const pyEnv = pyResolveDirs(fx.regRoot, { SANDBAR_EPICS_DIR: envDir })
  if (pyEnv) {
    for (const p of [fx.engine, fx.external]) {
      const tsDir = resolveEpicsDir(primaryDir(findProject(p.key)))
      ok(tsDir === envDir && pyEnv[p.key] === envDir && tsDir === pyEnv[p.key],
         `E env 覆盖同源：${p.key} Py==TS==env 目录`, `${pyEnv[p.key]} vs ${tsDir}`)
    }
  }
} finally {
  delete process.env.SANDBAR_EPICS_DIR
  fx.teardown()
}
process.exit(done('t260907-07-epic-anchor-same-source'))
