// t261003-04 缺陷 A：四根（声明/数据/注册表/请求账）兜底必须按实例绑定。
//
// 病灶（真机 261001-261003 实测，802/843 条生产台账报警来自临时实例）：四个根是四个
// 独立 env 旋钮、全部兜底 $HOME——场景只注入 DSH_HOME + SANDBAR_PROJECTS_DIR 时，临时
// 实例①读生产声明起守望者②盯自己不存在的账本每拍报 ledger_unreadable③报警写进生产
// 数据根④读生产请求账把生产执行器判成 waiting_on_itself。
//
// 本锁：缺省实例（无 DSH_HOME）兜底路径逐字节不变（历史追加账照读）；非缺省实例
// （DSH_HOME=临时目录）四个兜底全部落 <DSH_HOME>/sandbar/… 与生产物理隔离；显式 env
// 旋钮在任何形态下仍最优先；畸形 DSH_HOME（空串/带尾斜杠）不得误伤生产形态判定。
import { join } from 'node:path'
import {
  watchdogConfigDir, watchdogDataDir, projectsRoot, eventLedgerFile,
  instanceSandbarRoot, instanceProjectsRoot, dshHome, isDefaultInstance,
} from '../src/host/config.ts'
import { requestsLedgerFile } from '../../executor-panel/src/host/requests.ts'
import { assert, done } from './lib.mjs'

let n = 0
const HOME = '/users/fake-home'

// —— 缺省实例（生产形态）：只有 HOME、无任何 SANDBAR_* env —— 兜底路径历史不变 ——
{
  const env = { HOME }
  assert(isDefaultInstance(env) === true, 'default instance: HOME-only env is the default (production) instance')
  assert(watchdogConfigDir(env) === join(HOME, '.sandbar', 'projects'), 'default instance: config root unchanged (~/.sandbar/projects)')
  assert(watchdogDataDir(env) === join(HOME, '.sandbar', 'watchdog'), 'default instance: data root unchanged (~/.sandbar/watchdog)')
  assert(projectsRoot(env) === join(HOME, '.sandbar', 'projects'), 'default instance: projects root unchanged')
  assert(requestsLedgerFile('sandbar', env) === join(HOME, '.sandbar', 'projects', 'sandbar', 'requests.jsonl'), 'default instance: requests ledger unchanged')
  n += 5
}
// DSH_HOME 恰为缺省 ~/.dsh（dsh 可能把它写进进程 env）——仍按生产形态，路径不变。
{
  const env = { HOME, DSH_HOME: join(HOME, '.dsh') }
  assert(isDefaultInstance(env) === true, 'default instance: DSH_HOME=~/.dsh still counts as production')
  assert(watchdogDataDir(env) === join(HOME, '.sandbar', 'watchdog'), 'default instance: DSH_HOME=~/.dsh keeps production data root')
  n += 2
}
// 畸形 DSH_HOME：尾斜杠归一后仍是缺省；空串回落 ~/.dsh。不得把生产误判成隔离实例。
{
  assert(isDefaultInstance({ HOME, DSH_HOME: join(HOME, '.dsh') + '/' }) === true, 'malformed input: trailing-slash DSH_HOME normalizes to default instance')
  assert(isDefaultInstance({ HOME, DSH_HOME: '' }) === true, 'malformed input: empty-string DSH_HOME falls back to ~/.dsh (default)')
  assert(dshHome({ HOME }) === join(HOME, '.dsh'), 'dshHome: no DSH_HOME → ~/.dsh')
  n += 3
}
// —— 非缺省实例（场景/泳道形态）：DSH_HOME=临时目录 —— 四根全部离开生产 ——
{
  const tmp = '/tmp/scenario-instance-x'
  const env = { HOME, DSH_HOME: tmp }
  assert(isDefaultInstance(env) === false, 'temp instance: scenario DSH_HOME is NOT the default instance')
  const prodRoot = join(HOME, '.sandbar')
  for (const [name, root] of [
    ['config root', watchdogConfigDir(env)],
    ['data root', watchdogDataDir(env)],
    ['projects root', projectsRoot(env)],
    ['sandbar root', instanceSandbarRoot(env)],
  ]) {
    assert(!root.startsWith(prodRoot), `temp instance: ${name} escapes the production root (${root})`)
    assert(root.startsWith(join(tmp, 'sandbar')), `temp instance: ${name} binds to <DSH_HOME>/sandbar (${root})`)
    n += 2
  }
  assert(instanceProjectsRoot(env) === join(tmp, 'sandbar', 'projects'), 'temp instance: instance projects root = <DSH_HOME>/sandbar/projects')
  // 缺陷 A(2)：临时实例的事件账盯自己的注册表根，不再顺兜底摸到生产 events.jsonl。
  assert(eventLedgerFile('sandbar', env) === join(tmp, 'sandbar', 'projects', 'sandbar', 'ledger', 'events.jsonl'), 'temp instance: event ledger under its own projects root')
  // 缺陷 A(4)：自锁判定的请求账只消费同实例 scope——临时实例的 requests.jsonl 不在生产根。
  assert(requestsLedgerFile('sandbar', env) === join(tmp, 'sandbar', 'projects', 'sandbar', 'requests.jsonl'), 'temp instance: requests ledger under its own projects root (no production self-lock reads)')
  n += 2
}
// 场景真实注入形态（integration/lib_fix17 款）：DSH_HOME + SANDBAR_PROJECTS_DIR 同时给。
// SANDBAR_PROJECTS_DIR 显式赢（显式=听调用方），但声明/数据/请求账仍被实例根隔离住。
{
  const tmp = '/tmp/scenario-instance-y'
  const proj = '/tmp/scenario-projects-y'
  const env = { HOME, DSH_HOME: tmp, SANDBAR_PROJECTS_DIR: proj }
  assert(projectsRoot(env) === proj, 'scenario shape: explicit SANDBAR_PROJECTS_DIR still wins')
  assert(eventLedgerFile('sandbar', env) === join(proj, 'sandbar', 'ledger', 'events.jsonl'), 'scenario shape: event ledger follows explicit projects root')
  assert(watchdogConfigDir(env) === join(tmp, 'sandbar', 'projects'), 'scenario shape: declaration root stays instance-scoped (no production declaration reads)')
  assert(watchdogDataDir(env) === join(tmp, 'sandbar', 'watchdog'), 'scenario shape: alert sink stays instance-scoped (no production ledger writes)')
  assert(requestsLedgerFile('sandbar', env) === join(tmp, 'sandbar', 'projects', 'sandbar', 'requests.jsonl'), 'scenario shape: requests ledger stays instance-scoped')
  n += 5
}
// 只隔离 HOME、ambient DSH_HOME 在场的进程形态（t261003-04 打回定案）：不被支持的
// 生产形态——根**跟着 DSH_HOME 走**（确定性、可预期），绝不退回 $HOME 兜底、也绝不
// 落进换出来的临时 HOME 树；这正是测试构造生产形态必须自钉 DSH_HOME 的依据
// （tests/data-root-single-source.test.mjs 的回归=ambient 值把根拽到 ~/.dsh/sandbar）。
{
  const ambient = '/users/real-host-dsh-home'
  const tempHome = '/tmp/home-only-isolation'
  const env = { HOME: tempHome, DSH_HOME: ambient }
  assert(isDefaultInstance(env) === false, 'hybrid shape: ambient DSH_HOME overrides a swapped HOME (non-default)')
  assert(watchdogConfigDir(env) === join(ambient, 'sandbar', 'projects'), 'hybrid shape: config root follows DSH_HOME, not $HOME')
  assert(watchdogDataDir(env) === join(ambient, 'sandbar', 'watchdog'), 'hybrid shape: data root follows DSH_HOME, not $HOME')
  assert(projectsRoot(env) === join(ambient, 'sandbar', 'projects'), 'hybrid shape: projects root follows DSH_HOME, not $HOME')
  n += 4
}
// 显式旋钮在缺省实例下也照旧赢（不回归既有测试缝）。
{
  const env = { HOME, SANDBAR_WATCHDOG_DIR: '/wdcfg', SANDBAR_WATCHDOG_DATA: '/wddata', SANDBAR_PANEL_DIR: '/panel' }
  assert(watchdogConfigDir(env) === '/wdcfg', 'explicit knobs: SANDBAR_WATCHDOG_DIR wins')
  assert(watchdogDataDir(env) === '/wddata', 'explicit knobs: SANDBAR_WATCHDOG_DATA wins')
  assert(requestsLedgerFile('k', env) === '/panel/k/requests.jsonl', 'explicit knobs: SANDBAR_PANEL_DIR wins')
  n += 3
}

done(n)
