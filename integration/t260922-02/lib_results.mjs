/**
 * lib_results.mjs —— t260922-02 场景族共享三态助手（闸内无 SKIP，t260904-12）。
 *
 * 状态词表 pass/fail/env_fail/na；SUMMARY 行与退出码契约与
 * integration/t260904-05/lib_browser.mjs makeResults() 同款（0=全过；1=有 FAIL
 * 或全 N/A；2=有 ENV_FAIL）。独立小实现的原因：lib_browser 顶层 await
 * ensureStageConsole()（docker 台供给）——纯函数面场景 import 它会被舞台供给
 * 绑架，环境红归因失真。非 sc_ 前缀=共享代码，不登记 SCENARIOS（L5 豁免）。
 */
export function makeResults() {
  const results = []
  const OK = new Set(['pass', 'fail', 'env_fail', 'na'])
  return {
    record(name, status, detail = '') {
      if (!OK.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`)
      results.push({ name, status, detail })
      console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
    },
    /** pass 断言小助手：cond 真=pass，假=fail（detail 自明）。 */
    check(cond, name, detail = '') {
      this.record(name, cond ? 'pass' : 'fail', cond ? '' : detail)
      return !!cond
    },
    summarize() {
      const p = results.filter(r => r.status === 'pass').length
      const e = results.filter(r => r.status === 'env_fail').length
      const n = results.filter(r => r.status === 'na').length
      const f = results.filter(r => r.status === 'fail').length
      const allNa = results.length > 0 && n === results.length
      console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
      process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
    },
  }
}
