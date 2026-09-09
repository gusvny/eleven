// t260901-11 M0 integration test: the /metrics API contract freeze surface
// (request / response / errors / both front doors)
// Under acceptance: the request params, response fields, error and degrade
// behavior, and byte-identity exclusion rules frozen in the contract document.
// t260903-09 same-ticket sync (R2): cache.status gains 'stale', the
// mode=full|fast param, the single KPI anchor windowing policy, and the
// completion of the metrics universe — pinned in the same batch as this
// ticket's contract document edits so the guard is not blind to them.

import { readFileSync, existsSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`ok   ${name}`); }
  else { fail++; console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

const DOC = 'docs/design/metrics-api契约v1.md';
if (!existsSync(DOC)) {
  console.log(`FAIL 契约文档存在 — ${DOC} 不存在`);
  console.log(`SUMMARY pass=0 fail=1 env_fail=0 na=0`);
  process.exit(1);
}
const doc = readFileSync(DOC, 'utf8');

// ---- request params frozen ----
check('端点 GET /metrics', /GET\s+\/metrics/.test(doc));
check('window 枚举 7d|30d|all', /window=7d\|30d\|all/.test(doc));
check('epic 枚举 code|all|none', /epic=<code\|all\|none>/.test(doc));
check('view 枚举 time|delivery|token|health', /view=time\|delivery\|token\|health/.test(doc));
check('view 必填', /(view[^\n]{0,100}必填|必填[^\n]{0,40}view)/.test(doc));
check('window 默认 7d',
  doc.split('\n').some(l => /^\|\s*window\s*\|/.test(l.trim()) && /\|\s*`7d`\s*\|/.test(l)) ||
  /window[^\n]{0,40}默认[^\n]{0,10}7d/.test(doc));
check('template 默认 dev-lane', /template[^\n]{0,40}dev-lane/.test(doc));

// ---- invalid input behavior (pinned by review) ----
check('非法值→4xx', /非法[\s\S]{0,80}4xx|4xx[\s\S]{0,40}error/.test(doc));
check('重复参数→4xx（无取首个容错）', /重复参数[^\n]{0,40}4xx/.test(doc));
check('错误体 {error,reason}', /error[,，\s]+reason|reason[,，\s]+error/.test(doc) || /\{error,\s*reason\}/.test(doc));

// ---- response fields frozen ----
for (const k of ['tickets', 'closed', 'avg_delivery_min', 'tokens_total']) {
  check(`kpis 字段 ${k}`, doc.includes(k));
}
for (const k of ['kind', 'title', 'categories', 'series', 'drill']) {
  check(`ChartSpec 字段 ${k}`, doc.includes(k));
}
for (const k of ['bar', 'stackBar', 'hBar', 'donut']) {
  check(`图表 kind 枚举 ${k}`, doc.includes(k));
}
check('cache.status 枚举 hit|miss|computed|stale（t260903-09 bump）', /hit\|miss\|computed\|stale/.test(doc));
check('mode 参数枚举 full|fast（t260903-09 bump）', /mode=full\\\|fast|mode=full\|fast/.test(doc));
check('stale 语义成文（fast 快照可缺票+后台 full 替换）', /stale`=fast[\s\S]{0,200}(缺票|替换)/.test(doc));
check('KPI 锚点归窗单一口径成文（t260903-09 收口）', /KPI 归窗单一口径[\s\S]{0,200}(闭单终态时刻|创建时刻)/.test(doc));
check('度量宇宙补全 reason 语义成文（t260903-09）', /度量宇宙补全[\s\S]{0,200}(N 票|list API 响应集合不因此扩大)/.test(doc));
check('donut 人审扇区契约字面钉死（t260903-09/C3）', /人审等待[\s\S]{0,160}(冻结字面|isHumanSliceName|改名)/.test(doc));

// ---- byte identity across both front doors (exclusion rules pinned by review) ----
check('字节级一致条款存在', doc.includes('字节'));
check('剔除 generated_at', /generated_at/.test(doc));
check('剔除 cache.computed_at', /computed_at/.test(doc));
check('剔除规则成文（两时间戳均出现于字节一致上下文）',
  /剔除[\s\S]{0,120}generated_at[\s\S]{0,120}computed_at/.test(doc) ||
  /generated_at[\s\S]{0,120}computed_at[\s\S]{0,120}(剔除|比较面)/.test(doc));

// ---- CLI front door ----
check('CLI 前门同实现同缓存', /CLI[\s\S]{0,120}(同实现|同缓存|字节)/.test(doc));

// ---- the health view bypasses the cache ----
check('健康 view 直查不进缓存', /health[\s\S]{0,160}不进缓存|健康[\s\S]{0,160}不进缓存/.test(doc));

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
