#!/usr/bin/env node
/**
 * epic_anchor_same_source.mjs —— t260907-07 验收③同源断言（灰盒）。
 *
 * 口径边界（方案 C4）：断言的是「同规」——同一注册表真源 + 同一拼装规则
 * <主目录>/notes/epics；不是「全部署形态同源」（工单台 config.repo 起在别处时
 * UI 仍锚其 repo，该部署形态不在本断言范围）。
 *
 * 断言：夹具两项目下，Python shared.resolve_epics_dir(key) 与
 * TS resolveEpicsDir(primaryDir(findProject(key))) 逐项目相等，且各指各自主目录。
 * Run: node integration/t260907-07/epic_anchor_same_source.mjs（cwd=仓库根）
 */
import { resolveEpicsDir } from '../../server/dsh/workbench/src/host/epics.ts'
import { findProject, primaryDir } from '../../server/dsh/suyou-projects.ts'
import { makeEpicFixture, runPython } from './epic_fixture.mjs'

const { ok, done } = (await import('../t260903-09/lib_integration.mjs')).makeChecker()

const fx = makeEpicFixture()
try {
  // 同一注册表喂两边：TS 走进程 env（每次调用现读），Py 走子进程 env。
  process.env.SANDBAR_PROJECTS_DIR = fx.regRoot
  delete process.env.SUYOU_EPICS_DIR
  const pyCode = `
import sys, json
sys.path.insert(0, ${JSON.stringify(new URL('../../server/dsh/temporal-poc', import.meta.url).pathname)})
import shared
print(json.dumps({k: str(shared.resolve_epics_dir(k)) for k in ('engine', 'external')}))
`
  const py = JSON.parse(runPython(pyCode, { ...fx.env, SUYOU_EPICS_DIR: '' }).trim())

  for (const p of [fx.engine, fx.external]) {
    const tsDir = resolveEpicsDir(primaryDir(findProject(p.key)))
    ok(tsDir === p.epicsDir, `TS ${p.key} 锚项目主目录 notes/epics`, tsDir)
    ok(py[p.key] === p.epicsDir, `Py ${p.key} 锚项目主目录 notes/epics`, py[p.key])
    ok(tsDir === py[p.key], `同源：${p.key} Py==TS`, `${py[p.key]} vs ${tsDir}`)
  }
  // 不串桶：external 的异名只在 external 桶放行
  ok(resolveEpicsDir(primaryDir(findProject('engine'))) !== fx.external.epicsDir,
     'engine 锚 ≠ external 桶（不串桶）')
  done('t260907-07 同源断言')
} finally {
  fx.teardown()
}
