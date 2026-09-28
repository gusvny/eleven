// t260901-11 M0 integration test: the /metrics API contract freeze surface
// (request / response / errors / both front doors)
// Under acceptance: the request params, response fields, error and degrade
// behavior, and byte-identity exclusion rules frozen in the contract document.
// t260903-09 same-ticket sync (R2): cache.status gains 'stale', the
// mode=full|fast param, the single KPI anchor windowing policy, and the
// completion of the metrics universe — pinned in the same batch as this
// ticket's contract document edits so the guard is not blind to them.
//
// 260928 re-anchoring (host order: the docs library was translated into English).
// Every assertion below was re-aimed at the *English* wording of the deliverable
// while staying on the same contract surface. Enum literals, field names and
// parameter names — machine contract rather than prose — were never translated
// and are still asserted verbatim.

import { readFileSync, existsSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`ok   ${name}`); }
  else { fail++; console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

const DOC = 'docs/design/metrics-api-contract-v1.md';
if (!existsSync(DOC)) {
  console.log(`FAIL 契约文档存在 — ${DOC} 不存在`);
  console.log(`SUMMARY pass=0 fail=1 env_fail=0 na=0`);
  process.exit(1);
}
const doc = readFileSync(DOC, 'utf8');

// ---- request params frozen (enum literals + field names: never translated) ----
check('端点 GET /metrics', /GET\s+\/metrics/.test(doc));
check('window 枚举 7d|30d|all', /window=7d\|30d\|all/.test(doc));
check('epic 枚举 code|all|none', /epic=<code\|all\|none>/.test(doc));
check('view 枚举 time|delivery|token|health', /view=time\|delivery\|token\|health/.test(doc));
check('view 必填', /(view[^\n]{0,100}(required|mandatory)|(required|mandatory)[^\n]{0,40}view)/i.test(doc));
check('window 默认 7d',
  doc.split('\n').some(l => /^\|\s*window\s*\|/.test(l.trim()) && /\|\s*`7d`\s*\|/.test(l)) ||
  /window[^\n]{0,60}default[^\n]{0,20}7d/i.test(doc));
check('template 默认 dev-lane', /template[^\n]{0,60}dev-lane/i.test(doc));

// ---- invalid input behavior (pinned by review) ----
check('非法值→4xx', /(invalid|illegal)[\s\S]{0,120}4xx|4xx[\s\S]{0,60}error/i.test(doc));
check('重复参数→4xx（无取首个容错）',
  /repeat(ed)? parameter[^\n]{0,80}4xx/i.test(doc) || /4xx[\s\S]{0,80}no "?take the first/i.test(doc));
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
check('stale 语义成文（fast 快照可缺票+后台 full 替换）',
  /`?stale`?[^\n]{0,120}fast mode/i.test(doc) && /(tickets may be missing|replaced)/i.test(doc));
check('KPI 锚点归窗单一口径成文（t260903-09 收口）',
  /single definition for KPI window attribution/i.test(doc) &&
  (/closing terminal-state\s+instant/i.test(doc) || /creation instant/i.test(doc)));
check('度量宇宙补全 reason 语义成文（t260903-09）',
  /metric universe completion/i.test(doc) && /(N tickets|does not (expand|grow))/i.test(doc));
check('donut 人审扇区契约字面钉死（t260903-09/C3）',
  /human review wait[\s\S]{0,200}(frozen literal|isHumanSliceName|renaming)/i.test(doc));

// ---- byte identity across both front doors (exclusion rules pinned by review) ----
check('字节级一致条款存在', /byte-identical|byte for byte|byte-for-byte/i.test(doc));
check('剔除 generated_at', /generated_at/.test(doc));
check('剔除 cache.computed_at', /computed_at/.test(doc));
check('剔除规则成文（两时间戳均出现于字节一致上下文）',
  /(removing|exclud|strip)[\s\S]{0,160}generated_at[\s\S]{0,160}computed_at/i.test(doc) ||
  /generated_at[\s\S]{0,160}computed_at[\s\S]{0,220}byte/i.test(doc));

// ---- CLI front door ----
check('CLI 前门同实现同缓存', /CLI[\s\S]{0,200}(same implementation|same cache|byte-identical)/i.test(doc));

// ---- the health view bypasses the cache ----
check('健康 view 直查不进缓存',
  /(the )?health view[\s\S]{0,160}(does not (go into|read|use) the cache|bypass\w* the cache|not cached|never cached)/i.test(doc));

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
