/**
 * lib_env.mjs —— 收窄旋钮清理单点（node 侧；与 integration/lib_env.py 同源同纪律）。
 *
 * 260930（真票 t260930-09 全族缺陷）：泳道轮的闸环境带着本轮收窄面
 * （SANDBAR_SCENARIO_ONLY=<改动面>）。mjs 场景自己 spawnSync 起执行器/闸时，子进程
 * **继承**了它 → 内层被收窄成不含夹具点名的面 → 断言成片红。
 * 纪律：被测面必须由夹具显式声明，绝不继承外层泳道轮的收窄/策略旋钮。
 * 守卫：integration/lint_tests.py L12（起执行器/闸的调用点必须出现本单点名）。
 */
const NARROWING_PREFIXES = [
  'SANDBAR_SCENARIO_', 'SANDBAR_INTEG_', 'SANDBAR_KNOWN_RED_', 'SANDBAR_GATE_',
  'SANDBAR_SUPPLY_',
]
// 台面只清**引擎每轮注入的收窄件**（具名），不用 `SANDBAR_STAGE_` 前缀：
// 该前缀下有共享缝 `SANDBAR_STAGE_BATCH`（批台名）与夹具自己的等待/租约旋钮，
// 一前缀清掉=改了被测面（与 lib_env.py 同口径，260930 修正）。
const NARROWING_NAMES = [
  'SANDBAR_POOL_CONC', 'SANDBAR_CONC_POOLS', 'SANDBAR_UNDECLARED_POLICY',
  'SANDBAR_STAGE_SWEEP_ORPHANS', 'SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX',
  // t261017-10（宿主令 261012 实测）：台账复用 kill switch 是轮级行为钉（裸名，
  // 前缀族剥不掉）；夹具自起执行器时必须自己声明那一档（与 lib_env.py 同序，L14 锁）。
  'SANDBAR_LEDGER_REUSE',
]
// 261004（执行器请求 -0023，t261004-26）：继承的**调用方身份**与收窄旋钮同族同纪律——
// ticket.py/client.py 的 spawn 链往下注入这两个；夹具起票入口不剥它们时，继承来的身份
// 让跨项目闸抢在要断言的面之前拒收（79e4cb6 手修两条场景即此族）。要测身份闸本身，
// 用 extra 显式注入敌对值（与 lib_env.py 的 INHERITED_IDENTITY_NAMES 逐元素同序，L14 锁）。
const INHERITED_IDENTITY_NAMES = [
  'SANDBAR_CALLER_PROJECT', 'SANDBAR_CALLER_IDENTITY_SRC',
]

/** 副本 env：剥掉继承来的窄化/策略旋钮与调用方身份，再并入调用方显式声明的 extra。 */
export function cleanNarrowingEnv(extra = {}, base = process.env) {
  const env = { ...base }
  for (const k of Object.keys(env)) {
    if (NARROWING_NAMES.includes(k) || INHERITED_IDENTITY_NAMES.includes(k)
        || NARROWING_PREFIXES.some((p) => k.startsWith(p))) {
      delete env[k]
    }
  }
  for (const [k, v] of Object.entries(extra)) env[k] = String(v)
  return env
}

/** env 里还带着的继承旋钮（收窄 + 调用方身份；诊断/自证用；空对象=干净）。 */
export function inheritedNarrowingKnobs(env = process.env) {
  const out = {}
  for (const [k, v] of Object.entries(env)) {
    if (NARROWING_NAMES.includes(k) || INHERITED_IDENTITY_NAMES.includes(k)
        || NARROWING_PREFIXES.some((p) => k.startsWith(p))) {
      out[k] = v
    }
  }
  return out
}
