#!/usr/bin/env node
/**
 * sc_project_repo_registry_seam.mjs —— t260904-04 KI-043① L2 接线场景（灰盒）。
 *
 * intent（用户可感知）：多项目用户在面板选 project=suyou 后，git/会话解析指向 suyou
 * 主目录而不是引擎仓（宿主验收：「suyou 50 票历史在面板可选可见」）。R1 裁决的落点=
 * 换根回调随 defaultDeps 公开导出（HTTP 门与 CLI 门共享同一份 defaultDeps → 双门天然
 * 同修），本场景守**真注册表装载链**的接线面：SANDBAR_PROJECTS_DIR 注册表缝 → 项目
 * key → 注册表主目录；未知 key / 注册表坏 → null 回退传入 repo（不抛不炸）。
 *
 * 断言面（锚定 defaultDeps 公开导出面，不锚 findProject/primaryDir 内部）：
 *  A repoForProject 随 defaultDeps 在场（双门共享落点存在性）；
 *  B 合法 key（alpha/beta）→ 各自注册表 dirs 主目录（含默认项目 key——「默认项目也
 *    换根」是 gen1 已裁决语义，此处顺带锚 alpha=defaultProject() 为主目录解析对象）；
 *  C 未知 key → null（回退语义，不抛）；
 *  D 注册表文件坏 → null（fallback 兜底，不抛）；
 *  E defaultProject() 取注册表字母序首 key（换根入口的 key 来源面）。
 *
 * 与 developer L1 intent 区别：L1 用注入桩（手造回调）测 buildMetricsResponse 的换根
 * 行为与双门 stub 一致性；本场景补桩够不到的真 suyou-projects 注册表装载缝（env→
 * yaml 解析→主目录）。双门 stub 一致性由 L1 覆盖（stub 模式换根恒 no-op=已声明语义）。
 *
 * 预期状态：实现段（t260904-04 第 4 步）已随本工作区落地——全绿；若回退实现则全红
 * （repoForProject 不存在）。legacy 单文件注册表模式（SANDBAR_PROJECTS_YAML）下换根行为方案未裁决，不锚。
 * Run: node integration/t260904-04/sc_project_repo_registry_seam.mjs（cwd=仓库根）
 */
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { freshTmp, rmRf, NOW, loadMetrics, makeChecker } from '../t260903-09/lib_integration.mjs'

const { ok, done } = makeChecker()

/** per-key 注册表条目（<root>/<key>/project.yaml，schema v1 固定形状）。 */
const projectYaml = (key, dir) => `schema: v1
project:
  - key: ${key}
    name: ${key}
    dirs:
      - ${dir}
`

const savedDir = process.env.SANDBAR_PROJECTS_DIR
const tmp = await freshTmp('k043')
try {
  await mkdir(join(tmp, 'alpha'), { recursive: true })
  await mkdir(join(tmp, 'beta'), { recursive: true })
  await writeFile(join(tmp, 'alpha', 'project.yaml'), projectYaml('alpha', join(tmp, 'alpha')), 'utf8')
  await writeFile(join(tmp, 'beta', 'project.yaml'), projectYaml('beta', join(tmp, 'beta')), 'utf8')
  process.env.SANDBAR_PROJECTS_DIR = tmp

  const m = await loadMetrics()
  const deps = m.defaultDeps('/stub-repo', () => NOW)

  ok(typeof deps.repoForProject === 'function', 'A repoForProject 随 defaultDeps 公开导出（双门共享落点）')

  const rp = (k) => (typeof deps.repoForProject === 'function' ? deps.repoForProject(k) : undefined)
  ok(rp('alpha') === join(tmp, 'alpha'), 'B1 合法 key alpha → 注册表主目录', `got ${rp('alpha')}`)
  ok(rp('beta') === join(tmp, 'beta'), 'B2 合法 key beta → 各归各目录', `got ${rp('beta')}`)

  const defKey = typeof deps.defaultProject === 'function' ? await deps.defaultProject() : undefined
  ok(defKey === 'alpha', 'E defaultProject=注册表字母序首 key（换根 key 来源面）', `got ${defKey}`)
  ok(rp(defKey) === join(tmp, 'alpha'), 'B3 默认项目 key 同样换根（gen1 裁决语义）')

  ok(rp('nope') === null, 'C 未知 key → null 回退（不抛）', `got ${rp('nope')}`)

  // D 注册表坏：条目 yaml 畸形（schema 缺失/顶层乱行）→ 该条目被隔离/装载抛错 → null 回退（不抛）
  const tmp2 = await freshTmp('k043bad')
  await mkdir(join(tmp2, 'alpha'), { recursive: true })
  await writeFile(join(tmp2, 'alpha', 'project.yaml'), '顶层乱行不是合法 project.yaml\n  - key: alpha\n', 'utf8')
  process.env.SANDBAR_PROJECTS_DIR = tmp2
  ok(deps.repoForProject('alpha') === null, 'D 注册表坏 → null 回退（不抛）', `got ${deps.repoForProject?.('alpha')}`)
  await rmRf(tmp2)
} finally {
  if (savedDir === undefined) delete process.env.SANDBAR_PROJECTS_DIR
  else process.env.SANDBAR_PROJECTS_DIR = savedDir
  await rmRf(tmp)
}
process.exit(done('t260904-04-project-repo-registry-seam'))
