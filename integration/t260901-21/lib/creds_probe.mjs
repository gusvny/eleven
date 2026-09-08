#!/usr/bin/env node
/**
 * creds_probe.mjs —— JS 侧凭据源解析探针（t260901-21 i01 同构断言用，t260901-14 探针模式）。
 *
 * 用法：node lib/creds_probe.mjs '<scenario-json>'
 *   scenario = { projectsDir, dshHome, home, key, chdir }
 *     projectsDir/dshHome/home：env 桩（string = 设该 env；null = 删该 env）
 *     key：projectKey 入参；chdir：真值时先切到该目录（相对路径拒绝用例用）
 * 输出：单行 JSON { resolved: <path|null>, threw?: <msg> }，供 Python 侧与
 * agent_activities._resolve_credentials_source 对表。
 * 不读真实 ~/.sandbar / ~/.dsh（home 桩必传），零网络。
 */

const scenario = JSON.parse(process.argv[2] ?? '{}')

function setEnv(name, value) {
  if (value === null || value === undefined) delete process.env[name]
  else process.env[name] = value
}
setEnv('SANDBAR_PROJECTS_DIR', scenario.projectsDir)
setEnv('DSH_HOME', scenario.dshHome)
setEnv('HOME', scenario.home)
if (scenario.chdir) process.chdir(scenario.chdir)

const mod = await import(new URL('../../../server/ui-check/creds-source.mjs', import.meta.url).href)
let resolved = null
let threw
try {
  resolved = mod.resolveCredentialsSource(scenario.key ?? '') || null
} catch (err) {
  threw = String((err && err.message) || err)
}
console.log(JSON.stringify({ resolved, threw }))
