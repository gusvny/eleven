// Integration scenario t260904-07 ② — session-charter 端点活体契约（ro，fetch 级）。
//
// Intent (gray-box, user perspective):
//   GET /suyou-workbench/api/session-charter?project=<key> 的部署后可感知契约：
//   命中项目拿到「占位符已实值化 + 命中分段已追加」的 charter 文本（用户在新会话里
//   读到的就是这份）；未命中项目仍 200 只吃通用段（新项目开箱即用）；畸形 query
//   （缺/空串）=400 形状错误 JSON 而非 5xx/崩溃。与随票 smoke intent 级不同层：
//   smoke 直测渲染纯函数（内存面），本场景锚 HTTP 可达面（真宿主真文件真路由）。
//
// High-level steps:
//   T0 卫兵：拒 3099；隔离台不可达=干净 SKIP。
//   T1 端点活性判定：GET ?project=<在案 key> 得 404 时做源锚复核——node.ts/模块含
//      注册路径字面量=「已实现未部署（lib 未重建或测试台未重启）」→ fail（精确归因）；
//      源锚也不在=「未实现（pre-merge）」→ 干净 skip（merge 部署后自动生效）。
//   T2 命中腿（在案 key 优先 sandbar，key 动态化不绑数据）：200 + {ok,charter} 形状、
//      charter 含 key 实值（{{project_key}} 已替换）、零 {{ 占位符残留（统一渲染）、
//      含命中分段头。
//   T3 未命中腿（不存在的 key）：200 + charter 非空（只回通用段）+ 不含该 key 的
//      分段头 + {{project_name}} 弱化=key 实值仍在文。
//   T4 缺 project → 400 且响应体可 JSON 解析（形状错误，不崩不 5xx）。
//   T5 空串 project= → 400（方案钉死口径）。
//   （「文件缺失回落」「改文件即生效」两腿需对真宿主仓文件做写操作，3099/受控文件
//   红线下不做活体注入——回落由 smoke 纯函数直测覆盖，现读现渲染列入人工走查。）
//
// Execution contract: stdout last line `SUMMARY pass=<n> skip=<m> fail=<k>`;
// 依赖缺失一律干净 SKIP (exit 0)；FAIL>0 → exit 1。隔离台 SUYOU_TEST_CONSOLE
// （默认 127.0.0.1:3199）；硬守卫：绝不 3099。

import { readFileSync } from 'node:fs';
import { BASE, CHARTER_EP, refuseProductionConsole, consoleHealthy, fetchProjectKeys } from './lib_charter.mjs';

refuseProductionConsole();

const results = [];
const emit = (name, status, detail = '') => {
  results.push({ status });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`);
};
const summarize = () => {
  const p = results.filter(r => r.status === 'pass').length;
  const s = results.filter(r => r.status === 'skip').length;
  const f = results.filter(r => r.status === 'fail').length;
  console.log(`SUMMARY pass=${p} skip=${s} fail=${f}`);
  process.exit(f > 0 ? 1 : 0);
};

if (!(await consoleHealthy())) {
  emit('console/health', 'skip', `test console not reachable at ${BASE} (see integration/README.md provisioning)`);
  summarize();
}
emit('console/health', 'pass', BASE);

const get = (qs = '') => fetch(`${BASE}${CHARTER_EP}${qs}`, { signal: AbortSignal.timeout(8000) });

// ---- T0.5 在案 key（命中腿动态化，不绑注册表数据）----
const keys = await fetchProjectKeys();
const hitKey = keys.includes('sandbar') ? 'sandbar' : (keys[0] ?? null);
if (!hitKey) {
  emit('t0/project-registry', 'skip', '测试台项目注册表为空，命中腿无 key 可用');
  summarize();
}

// ---- T1 端点活性判定（404 的精确归因——报错不许说谎，KI-025 口径）----
const probe = await get(`?project=${encodeURIComponent(hitKey)}`);
if (probe.status === 404) {
  let anchored = false;
  try {
    const node = readFileSync('server/dsh/workbench/node.ts', 'utf8');
    const mod = readFileSync('server/dsh/workbench/src/host/session-charter.ts', 'utf8');
    anchored = node.includes(CHARTER_EP) || (node.includes('session-charter') && mod.includes(CHARTER_EP));
  } catch { /* 源读不到按未实现处理 */ }
  if (anchored) emit('t1/endpoint-live', 'fail', '源码已接线但活体 404——lib 未重建或测试台未载新代码');
  else emit('t1/endpoint-live', 'skip', 'endpoint not implemented yet (pre-merge)；merge 部署后本场景自动生效');
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
  emit('t2/section-appended', hitCharter.includes(`## project:${hitKey}`) ? 'pass' : 'fail', '命中分段头未出现在注入文本');
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
