// Integration scenario t260904-07 ② — session-charter 端点活体契约（ro，fetch 级）。
//
// Intent (gray-box, user perspective):
//   GET /sandbar-workbench/api/session-charter?project=<key> 的部署后可感知契约：
//   命中项目拿到「占位符已实值化 + 命中分段已追加」的 charter 文本（用户在新会话里
//   读到的就是这份）；未命中项目仍 200 只吃通用段（新项目开箱即用）；畸形 query
//   （缺/空串）=400 形状错误 JSON 而非 5xx/崩溃。与随票 smoke intent 级不同层：
//   smoke 直测渲染纯函数（内存面），本场景锚 HTTP 可达面（真宿主真文件真路由）。
//
// High-level steps:
//   T0 卫兵：拒 3099；隔离台不可达=ENV_FAIL（exit 2）。
//   T1 端点活性判定：GET ?project=<在案 key> 得 404 时做源锚复核——node.ts/模块含
//      注册路径字面量=「已实现未部署（lib 未重建或测试台未重启）」→ fail（精确归因）；
//      源锚也不在=「未实现（pre-merge）」→ na（系统状态：feature 未在案，该腿无对象；
//      全腿 na → exit 1 产品红）。
//   T2 命中腿（key 动态化不绑数据；t260905-04 仲裁修正：「命中分段」前提=key 在
//      session_charter.md 有专属分段，注册表在案≠有分段——实测泳道台注册表只有
//      seedws/suyou 时 seedws 无分段=假红；t260905-02 仲裁修正续：分段前提从
//      真源解析 project:<key>、注册表 key 真源无分段时该腿 na=系统状态条件腿，
//      另钉无分段在案 key 的通用段兜底面，两态都看守）：
//      200 + {ok,charter} 形状、charter 含 key 实值（{{project_key}} 已替换）、
//      零 {{ 占位符残留（统一渲染）、有分段者含命中分段头。
//   T3 未命中腿（不存在的 key）：200 + charter 非空（只回通用段）+ 不含该 key 的
//      分段头 + {{project_name}} 弱化=key 实值仍在文。
//   T4 缺 project → 400 且响应体可 JSON 解析（形状错误，不崩不 5xx）。
//   T5 空串 project= → 400（方案钉死口径）。
//   （「文件缺失回落」「改文件即生效」两腿需对真宿主仓文件做写操作，3099/受控文件
//   红线下不做活体注入——回落由 smoke 纯函数直测覆盖，现读现渲染列入人工走查。）
//
// Execution contract (t260904-12 三态): stdout last line
// `SUMMARY pass=<n> fail=<n> env_fail=<n> na=<n>`; 依赖缺失一律 env_fail (exit 2)；
// FAIL>0 或全腿 na → exit 1。隔离台 SANDBAR_TEST_CONSOLE
// （默认 127.0.0.1:3199）；硬守卫：绝不 3099。

import { readFileSync } from 'node:fs';
import { BASE, CHARTER_EP, refuseProductionConsole, consoleHealthy, fetchProjectKeys } from './lib_charter.mjs';

refuseProductionConsole();

const results = [];
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na']);
const emit = (name, status, detail = '') => {
  if (!STATUSES.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`);
};
const summarize = () => {
  const p = results.filter(r => r.status === 'pass').length;
  const e = results.filter(r => r.status === 'env_fail').length;
  const n = results.filter(r => r.status === 'na').length;
  const f = results.filter(r => r.status === 'fail').length;
  const allNa = results.length > 0 && n === results.length;
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
};

if (!(await consoleHealthy())) {
  emit('console/health', 'env_fail', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
emit('console/health', 'pass', BASE);

const get = (qs = '') => fetch(`${BASE}${CHARTER_EP}${qs}`, { signal: AbortSignal.timeout(8000) });

// ---- T0.5 在案 key（命中腿动态化，不绑注册表数据；t260905-04 仲裁修正见头注 T2：
//      「命中分段」前提=key 在 session_charter.md 有专属分段，注册表在案≠有分段）----
// 「命中分段在文」契约只对 charter 真源里有专属分段（## project:<key>）的项目
// 成立；注册表在案但真源无分段的项目走通用段（不编造分段）。故 hitKey 优先取
// 「在案且有分段」的 key（sandbar 优先）；真源读不到/无分段在案 key 时分段腿按
// na 折算（系统状态条件腿，前提缺对象非产品红），无分段面另以 unsectionedKey 单独钉住。
const keys = await fetchProjectKeys();
let sectionedKeys = [];
try {
  const src = readFileSync('server/session_charter.md', 'utf8');
  sectionedKeys = [...src.matchAll(/^## project:(\S+)\s*$/gm)].map(m => m[1]);
} catch { /* 真源读不到：分段腿按 na 折算 */ }
const hitKey = keys.includes('sandbar') && sectionedKeys.includes('sandbar') ? 'sandbar'
  : (keys.find(k => sectionedKeys.includes(k)) ?? keys[0] ?? null);
const hitKeyHasSection = hitKey !== null && sectionedKeys.includes(hitKey);
const unsectionedKey = keys.find(k => !sectionedKeys.includes(k)) ?? null;
if (!hitKey) {
  emit('t0/project-registry', 'env_fail', '测试台项目注册表为空，命中腿无 key 可用');
  summarize();
}

// ---- T1 端点活性判定（404 的精确归因——报错不许说谎，KI-025 口径）----
const probe = await get(`?project=${encodeURIComponent(hitKey)}`);
if (probe.status === 404) {
  let anchored = false;
  try {
    const node = readFileSync('server/plugins/workbench/node.ts', 'utf8');
    const mod = readFileSync('server/plugins/workbench/src/host/session-charter.ts', 'utf8');
    anchored = node.includes(CHARTER_EP) || (node.includes('session-charter') && mod.includes(CHARTER_EP));
  } catch { /* 源读不到按未实现处理 */ }
  if (anchored) emit('t1/endpoint-live', 'fail', '源码已接线但活体 404——lib 未重建或测试台未载新代码');
  else emit('t1/endpoint-live', 'na', 'endpoint not implemented yet (pre-merge)；merge 部署后本场景自动生效');
  summarize();
}
if (!probe.ok) {
  emit('t1/endpoint-live', 'fail', `GET ${CHARTER_EP} → ${probe.status}（非 404 非 2xx，形状外失败）`);
  summarize();
}
emit('t1/endpoint-live', 'pass', `200 on ?project=${hitKey}`);

// ---- T2 命中腿：占位符实值化 + 分段命中 ----
let hit = null;
try { hit = await probe.json(); } catch { /* 形状腿下判 */ }
emit('t2/shape', hit !== null && typeof hit === 'object' ? 'pass' : 'fail', '响应体应为 JSON 对象');
const hitCharter = typeof hit?.charter === 'string' ? hit.charter : null;
emit('t2/charter-is-string', hitCharter !== null ? 'pass' : 'fail', 'charter 字段缺失或非字符串（客户端畸形输入面对应的服务端根因）');
if (hitCharter !== null) {
  emit('t2/key-materialized', hitCharter.includes(hitKey) ? 'pass' : 'fail', `charter 未含 ${hitKey} 实值（{{project_key}} 未替换？）`);
  emit('t2/no-placeholder-residue', hitCharter.includes('{{') ? 'fail' : 'pass', 'charter 残留 {{ 占位符（统一渲染未覆盖）');
  if (hitKey !== null && hitKeyHasSection) {
    if (hitCharter.includes(`## project:${hitKey}`)) {
      emit('t2/section-appended', 'pass', '');
    } else {
      // 本地在案分段、台端响应无 → 场景读的 md 与台服务读的 md 非同源（共享测试台
      // 挂载树错位，t260905-08 gen2 diff 实证：共享台挂前一票泳道树，其 md 无任何
      // project 分段）。双态：台端响应含他 key 分段=数据漂移实锤（纯供给面）；
      // 台端零分段=「台端 md 无分段」与「端点分段拼装回归」同形不可直判——
      // 归因供给面优先（挂载错位已实证）但留复验通道：台重挂本树后仍红=产品红重开。
      const anySection = /## project:\S+/.test(hitCharter);
      emit('t2/section-appended', 'env_fail', anySection
        ? `台端 session_charter.md 分段集与本地树不同源（台端有他树分段、无本地 project:${hitKey}）——共享台挂载树错位（供给面）`
        : `台端注入文零 project 分段（本地在案 ${sectionedKeys.join('/')}）——台端 md 无分段（挂载树错位，gen2 已实证）或端点分段拼装回归，同形不可直判，供给面优先归因；台重挂本树后仍红＝产品红重开`);
    }
  } else {
    emit('t2/section-appended', 'na', `注册表 key 在 charter 真源无专属分段（真源分段键=[${sectionedKeys.join(', ') || '无'}]）——分段在文腿无对象，系统状态条件腿`);
  }
}
// 无分段在案项目：通用段兜底、不编造分段（注册表在案≠真源有分段，两态分别钉住）
if (unsectionedKey) {
  const r2 = await get(`?project=${encodeURIComponent(unsectionedKey)}`);
  let g = null;
  try { g = await r2.json(); } catch { /* 判 fail */ }
  const gc = typeof g?.charter === 'string' ? g.charter : null;
  emit('t2/unsectioned-generic-fallback',
    (r2.ok && gc !== null && gc.includes(unsectionedKey) && !gc.includes(`## project:${unsectionedKey}`)) ? 'pass' : 'fail',
    `无分段在案 key=${unsectionedKey} 应 200+通用段+key 实值化+不编造分段（实得 http=${r2.status} charter=${gc === null ? '非字符串' : gc.length + '字'}）`);
}

// ---- T3 未命中腿：通用段兜底 + name 弱化 ----
const absentKey = 'zz-charter-absent-key';
const miss = await get(`?project=${encodeURIComponent(absentKey)}`);
if (!miss.ok) {
  emit('t3/miss-200-with-generic', 'fail', `未命中项目 GET → ${miss.status}（应 200 只回通用段）`);
} else {
  let missBody = null;
  try { missBody = await miss.json(); } catch { /* 判 fail */ }
  const missCharter = typeof missBody?.charter === 'string' ? missBody.charter : null;
  emit('t3/miss-200-with-generic', (missCharter !== null && missCharter.length > 0) ? 'pass' : 'fail',
    missCharter === null ? 'charter 字段缺失或非字符串' : '通用段为空');
  if (missCharter !== null) {
    emit('t3/miss-no-section', missCharter.includes(`## project:${absentKey}`) ? 'fail' : 'pass', '不存在的项目不该有分段');
    emit('t3/miss-name-fallback', missCharter.includes(absentKey) ? 'pass' : 'fail', '查不到项目时 {{project_name}} 应弱化=key（用户仍知道自己在哪个项目）');
  }
}

// ---- T4/T5 畸形 query：400 形状错误 JSON，不崩不 5xx ----
for (const [leg, qs] of [['t4/missing-project-400', ''], ['t5/empty-project-400', '?project=']]) {
  const r = await get(qs);
  if (r.status >= 500) { emit(leg, 'fail', `→ ${r.status}（5xx=畸形输入崩了宿主面）`); continue; }
  if (r.status !== 400) { emit(leg, 'fail', `→ ${r.status}（方案钉死=400 形状错误）`); continue; }
  let parsable = false;
  try { await r.json(); parsable = true; } catch { /* 形状腿 */ }
  emit(leg, parsable ? 'pass' : 'fail', parsable ? '400 + JSON 可解析' : '400 但响应体非 JSON');
}

summarize();
