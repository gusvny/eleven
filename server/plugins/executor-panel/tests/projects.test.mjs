// projects 端点 UT（t260930-09 scope 8）：面板项目下拉的数据源——列出面板已知的
// 全量项目（注册表根下目录）并逐个标注 declared/enabled/config_error；405/坏 key 面。
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { assert, done, freshDir, cleanup, isolatedEnv } from './lib.mjs'
import { createApi } from '../src/host/api.ts'

const wd = freshDir()
const env = isolatedEnv(wd)
const api = createApi(env, { now: () => 1, fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'stub' }) })
// 注册表根与面板根同目录（isolatedEnv 第一参）——声明与项目目录同住一个根。
const Q = (s = '') => new URLSearchParams(s)
let n = 0

// 三只项目：alpha 已声明启用、beta 未声明、gamma 声明但停用。
mkdirSync(join(wd, 'alpha'), { recursive: true })
mkdirSync(join(wd, 'beta'), { recursive: true })
mkdirSync(join(wd, 'gamma'), { recursive: true })
mkdirSync(join(wd, 'Bad_Key'), { recursive: true }) // 形状不符的目录：绝不能进清单
writeFileSync(join(wd, 'alpha', 'watchdog.json'), JSON.stringify({ enabled: true }))
writeFileSync(join(wd, 'gamma', 'watchdog.json'), JSON.stringify({ enabled: false }))
// beta：无 watchdog.json = 未声明

let r = await api.handle('GET', '/sandbar-executor-panel/api/projects', Q(), '')
assert(r.status === 200 && r.json.ok === true, 'projects: GET ok')
const names = r.json.projects.map((p) => p.project)
assert(names.includes('alpha') && names.includes('beta') && names.includes('gamma'), 'undeclared project listed too (inspectable before anything is declared)')
assert(!names.includes('Bad_Key'), 'key-shape-invalid directories never listed')
const alpha = r.json.projects.find((p) => p.project === 'alpha')
const beta = r.json.projects.find((p) => p.project === 'beta')
const gamma = r.json.projects.find((p) => p.project === 'gamma')
assert(alpha.declared === true && alpha.enabled === true, 'alpha marked declared+enabled')
assert(beta.declared === false, 'beta marked not declared')
assert(gamma.declared === true && gamma.enabled === false, 'gamma marked declared but switched off')
assert(r.json.note.includes('declared=false'), 'note states the declared=false semantics')
n += 6

r = await api.handle('POST', '/sandbar-executor-panel/api/projects', Q(), '')
assert(r.status === 405, 'projects: POST → 405 (read-only surface)')
n += 1

// 空注册表根：真实空清单（不是报错冒充空，也不是空冒充报错）。
const wd2 = freshDir()
const api2 = createApi(isolatedEnv(wd2), { now: () => 1 })
r = await api2.handle('GET', '/sandbar-executor-panel/api/projects', Q(), '')
assert(r.status === 200 && r.json.projects.length === 0, 'empty registry root = real empty list')
n += 1

cleanup([wd, wd2])
done(n)
