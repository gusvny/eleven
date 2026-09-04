// t260901-11 M0 集成测试：两文档 schema/枚举冻结同步（防各说各话）
// 验收对象：
//  1. 契约文档缓存 schema 行与 UI 规划 §6 schema 行逐字一致（空白归一后比较）
//     且含 delivery.base 与 delivery_frozen（review 钉死的两个新增字段）
//  2. epic 枚举 <code|all|none> 两文档一致，epic=none 兜底桶有解释
//  3. 缓存失效规则（source_version/engine_version/updated_ts）与立项单关键决策 2 一致

import { readFileSync, existsSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`ok   ${name}`); }
  else { fail++; console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

const DOC = 'docs/design/metrics-api契约v1.md';
const UI = 'docs/design/metrics面板ui规划.md';

if (!existsSync(DOC)) {
  console.log(`FAIL 契约文档存在 — ${DOC} 不存在（implement 段未交付或路径漂移）`);
  console.log(`SUMMARY pass=0 fail=1 env_fail=0 na=0`);
  process.exit(1);
}
const doc = readFileSync(DOC, 'utf8');
const ui = readFileSync(UI, 'utf8');

// ---- 1. schema 行同步 ----
const norm = (s) => s.replace(/\s+/g, '');
const REQUIRED_FIELDS = [
  'ticket_id', 'template', 'durations', 'by_stage', 'by_round', 'human_wait',
  'delivery', 'base', 'add', 'del', 'commits',
  'tokens', 'by_model', 'in', 'out', 'cacheRead',
  'open', 'delivery_frozen', 'source_version', 'engine_version', 'updated_ts', 'computed_at',
  // t260903-09 bump：归窗锚点入缓存（派生字段，不入响应）——语义见契约块 3 增补段
  'created_ms', 'closed_ms',
];
const grabSchema = (text, anchor) => {
  // 正典字段串：锚点提示词后的第一个反引号代码段（契约文档锚「正典字段串」，UI §6 锚「缓存记录 schema」）
  const ai = anchor ? text.indexOf(anchor) : 0;
  if (ai < 0) return null;
  const m = text.slice(ai).match(/`([^`]*ticket_id[^`]*)`/);
  return m ? m[1] : null;
};
const schemaDoc = grabSchema(doc, '正典字段串');
const schemaUi = grabSchema(ui, '缓存记录 schema');
check('契约文档含完整 schema 行', !!schemaDoc);
check('UI 规划 §6 含 schema 行', !!schemaUi);
if (schemaDoc && schemaUi) {
  check('schema 两文档逐字一致（空白归一）', norm(schemaDoc) === norm(schemaUi),
    `doc=${norm(schemaDoc).slice(0, 120)}…\n     ui=${norm(schemaUi).slice(0, 120)}…`);
}
for (const f of REQUIRED_FIELDS) {
  const inDoc = schemaDoc && schemaDoc.includes(f);
  const inUi = schemaUi && schemaUi.includes(f);
  check(`schema 字段 ${f} 两文档均在`, !!inDoc && !!inUi,
    `doc=${!!inDoc} ui=${!!inUi}`);
}

// ---- 2. epic 枚举 ----
check('契约文档 epic 枚举含 none', /epic=<code\|all\|none>/.test(doc) || /`?none`?[^\n]{0,40}(兜底|未标注)/.test(doc));
check('UI 规划 epic 枚举含 none', ui.includes('<code|all|none>'),
  'UI 规划 §6 未同步 epic=none（三处 delta 之二）');
check('epic=none 兜底理由成文', /none[\s\S]{0,120}(兜底|历史无代号|未标注)/.test(doc));

// ---- 3. 失效规则对齐立项单决策 2 ----
for (const f of ['source_version', 'engine_version', 'updated_ts']) {
  check(`失效版本字段 ${f} 在契约中`, doc.includes(f));
}
check('固化不可重算例外成文', /delivery_frozen[\s\S]{0,200}(不可重算|跳过\s*delivery|跳过delivery)/.test(doc) || /固化[\s\S]{0,200}不可重算/.test(doc));

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
