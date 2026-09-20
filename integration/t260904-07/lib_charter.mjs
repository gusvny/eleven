import { ensureStageConsole } from '../lib_stage_console.mjs';
// lib_charter.mjs —— t260904-07 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 口径对齐 t260904-05/lib_browser.mjs（隔离台基址/3099 红线/SUMMARY 执行契约），此处
// 自足精简实现：本票场景只用到 fetch 级卫兵（browser 旅程场景同样自足，避免跨票目录
// import 耦合——已收口票的 lib 可能随退役清理，同 t260831-08 顶部行基线退役先例）。
//
// 安全红线：本目录场景只碰隔离台（lib_stage_console 供给，绝不连生产 3099）。

export const BASE = (await ensureStageConsole()).base;

/** 本票端点路径（与被测契约同一字面值；场景侧独立声明，防被测源漂移时场景跟着哑）。 */
export const CHARTER_EP = '/sandbar-workbench/api/session-charter';

/** 生产控制台红线：命中 3099 直接拒跑（宁可自家测试不跑）。 */
export function refuseProductionConsole() {
  if (BASE.includes(':3099')) {
    console.error('refusing to run: SANDBAR_TEST_CONSOLE points at the production console (3099)');
    process.exit(1);
  }
}

/** 执行契约（t260904-12 三态，同 t260904-05/lib_browser.makeResults 口径）：状态词表只认
 *  pass / fail / env_fail / na——环境缺失一律 env_fail（绝不 exit 0 假绿）；na 仅给以
 *  系统状态为条件的子用例。退出码：fail>0 或全部子用例 na → 1（产品红优先）；env_fail>0 → 2；
 *  全过 → 0。SUMMARY 末行 pass= fail= env_fail= na=。 */
export function makeResults() {
  const results = [];
  const OK = new Set(['pass', 'fail', 'env_fail', 'na']);
  return {
    record(name, status, detail = '') {
      if (!OK.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
      results.push({ name, status, detail });
      console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`);
    },
    summarize() {
      const p = results.filter(r => r.status === 'pass').length;
      const e = results.filter(r => r.status === 'env_fail').length;
      const n = results.filter(r => r.status === 'na').length;
      const f = results.filter(r => r.status === 'fail').length;
      const allNa = results.length > 0 && n === results.length;
      console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
      process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
    },
  };
}

/** 隔离台健康检查（workbench API 可达=测试台活着；与 t260904-05 口径同源接口）。 */
export async function consoleHealthy() {
  try {
    const r = await fetch(`${BASE}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

/** 项目清单（key 列表；响应三态兼容：裸数组 / {projects} / {result:{projects}} 包装）。 */
export async function fetchProjectKeys() {
  try {
    const r = await fetch(`${BASE}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    if (!r.ok) return [];
    const data = await r.json();
    const list = Array.isArray(data) ? data : (data?.result?.projects ?? data?.projects ?? []);
    return list.map(p => p.key ?? p.id ?? '').filter(Boolean);
  } catch { return []; }
}
