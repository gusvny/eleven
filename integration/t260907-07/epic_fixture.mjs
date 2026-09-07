#!/usr/bin/env node
/**
 * epic_fixture.mjs —— t260907-07 双项目立项单夹具构造器（共享件，方案 C3 卫生口径）。
 *
 * 两项目（engine 桶 + external 桶）均注册进**临时** SANDBAR_PROJECTS_DIR 根，
 * dirs[0] 均指临时目录——被测的是解析代码路径，不往 worktree 根落任何夹具文件；
 * teardown 整树删除。每项目 notes/epics 放同名（gap-b.md）+ 异名（各自独有）立项单。
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/** 生成 per-key 注册条目（与 shared._mk_registry 同构的严格 YAML 子集）。 */
function writeProjectYaml(regRoot, key, name, primary) {
  const d = join(regRoot, key)
  mkdirSync(d, { recursive: true })
  const content = `schema: v1\nproject:\n  - key: ${key}\n    name: ${name}\n    dirs:\n      - ${primary}\n`
  writeFileSync(join(d, 'project.yaml'), content, 'utf8')
}

/**
 * 建夹具。返回 { root, regRoot, engine: {key, dir, epicsDir}, external: {...}, teardown }。
 * 调用方负责在 finally 里调 teardown()（整树删除，无主仓污染）。
 */
export function makeEpicFixture() {
  const root = mkdtempSync(join(tmpdir(), 't260907-07-fixture-'))
  const regRoot = join(root, 'registry')
  mkdirSync(regRoot, { recursive: true })
  const mk = (key, name) => {
    const dir = join(root, key)
    const epicsDir = join(dir, 'notes', 'epics')
    mkdirSync(epicsDir, { recursive: true })
    writeProjectYaml(regRoot, key, name, dir)
    // 同名立项单：两桶都有（各自可各自读）
    writeFileSync(join(epicsDir, 'gap-b.md'), '# 立项单：gap-b\n\n同名单', 'utf8')
    return { key, dir, epicsDir }
  }
  const engine = mk('engine', '引擎项目')
  const external = mk('external', '外部项目')
  // 异名立项单：各自独有（对方桶读不到=不串桶断言面）
  writeFileSync(join(engine.epicsDir, 'engine-only.md'), '# 立项单：engine-only\n', 'utf8')
  writeFileSync(join(external.epicsDir, 'external-only.md'), '# 立项单：external-only\n', 'utf8')
  return {
    root, regRoot, engine, external,
    env: { SANDBAR_PROJECTS_DIR: regRoot },
    teardown() { rmSync(root, { recursive: true, force: true }) },
  }
}

/** 跑 python 片段（temporal-poc venv 优先），stdout 原样返回。 */
export function runPython(code, env = {}) {
  const base = new URL('../../server/dsh/temporal-poc/.venv/bin/python', import.meta.url).pathname
  const exe = existsSync(base) ? base : 'python3'
  return execFileSync(exe, ['-c', code], {
    encoding: 'utf8',
    env: { ...process.env, ...env },
    cwd: new URL('../..', import.meta.url).pathname,
  })
}
