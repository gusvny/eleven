// t260901-11 M0 integration test: pinned metrics definitions and the fault
// surface (a regression guard on what three review rounds converged on)
// Under acceptance:
//  1. each of the three dimensions (time / delivery / token) has a source of
//     truth and a declared known approximation
//  2. the fault-mode tradeoff list: the eight items carried over from
//     agent-usage.ts plus a new standalone section
//  3. each three-state case (malformed / missing / late) has an expected
//     behavior
//  4. the delivery dimension freeze and the pinned LOC base
//  5. versioning and change discipline
//
// 260928 re-anchoring (host order: the docs library was translated into English).
// Anchors were re-aimed at the English wording; identifiers, field names, enum
// literals and the circled trade-off numbers ①–⑧ were never translated and are
// still asserted verbatim.

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

// ---- 1. the three metric definitions ----
// time
check('时间窗公式 [from_i, from_{i+1})', /from_i[\s\S]{0,60}from_\{?i\+1\}?/.test(doc) || /\[from_i,\s*from_/i.test(doc));
check('末窗封口规则 min(closed_ts)',
  /min[\s(（][^\n)]{0,60}closed/i.test(doc) || /last[- ]window closing rule[\s\S]{0,200}min\(/i.test(doc));
check('rework=多窗加总',
  /rework[\s\S]{0,120}(multi|several|multiple)[- ]window|(multi|several|multiple)[- ]window[\s\S]{0,80}rework/i.test(doc));
check('human_wait 人门口径', doc.includes('human_wait'));
check('v2 精确口径仅登记',
  /v2[\s\S]{0,160}(registered|not in v1|logged|follow-?up|later)/i.test(doc));
// delivery
check('LOC add/del 分列不合并净值',
  /add[\s\S]{0,60}del/i.test(doc) && /(listed separately|not merged|separate)/i.test(doc));
check('base=lane 创建点主干 commit',
  /base[^\n]{0,120}(creation|fork|branch[- ]point)[^\n]{0,80}commit/i.test(doc) ||
  /commit[^\n]{0,120}(creation|fork) (point|instant)/i.test(doc));
check('base hash 固化进缓存（delivery.base）',
  /delivery[\s\S]{0,60}base/i.test(doc) && /(frozen|pinned|固化)/i.test(doc));
check('中途主干合入不改 base',
  /(merge|merging)[^\n]{0,120}(does not|never|is not)[^\n]{0,40}(change|alter|move)[^\n]{0,40}base/i.test(doc) ||
  /base[^\n]{0,120}(creation|fork) (point|instant)/i.test(doc));
check('commits 计数含 worker 代落盘',
  /rev-list[\s\S]{0,160}(worker|persist)/i.test(doc) || /commits[\s\S]{0,160}(worker|persist)/i.test(doc));
// token
check('只计 assistant/message', /assistant\/message/.test(doc));
check('chunk 镜像不计入（防翻倍）',
  /assistant\/chunk[\s\S]{0,200}(not counted|double count|mirror)/i.test(doc) ||
  /(not counted|double count)[\s\S]{0,120}assistant\/chunk/i.test(doc));
check('cacheRead 单列不并入 tokens_total',
  /cacheRead[\s\S]{0,160}(listed separately|not folded|separate)/i.test(doc));

// ---- 2. fault-mode tradeoff list ----
check('声明参考实现 agent-usage', /agent-usage/.test(doc));
const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧'];
check('八项取舍序号①-⑧齐', CIRCLED.every(c => doc.includes(c)),
  `缺：${CIRCLED.filter(c => !doc.includes(c)).join('')}`);
check('取舍带「带过来」声明', /carried over/i.test(doc));
check('取舍带「不带」选项语义',
  /not carried over|not carried|dropped|left out/i.test(doc));
check('新增故障模式独立小节',
  /(does not cover|not covered|new failure modes)/i.test(doc) &&
  /git[\s\S]{0,200}(delivery[^\n]{0,40}null|soft degrade)/i.test(doc));
check('timeline 缺 from 计数不静默丢',
  /from[\s\S]{0,160}(counts? as 0|reason count|not silently)/i.test(doc));

// ---- 3. three-state cases ----
check('畸形态用例 window=abc', /window=abc/.test(doc));
check('缺失态 无凭据 SKIP',
  /SKIP/.test(doc) && /(credential|credential-free)/i.test(doc));
check('缺失态 会话文件不存在软降级',
  /session (directory|file)[^\n]{0,120}(does not exist|missing)[\s\S]{0,160}(soft degrade|empty data|plain-language)/i.test(doc) ||
  /(soft degrade|empty data)[\s\S]{0,160}session (directory|file)/i.test(doc));
check('缺失态 timeline 无 running 条目',
  /(no running|without a running)[^\n]{0,120}(counts? as 0|reason count|\b0\b)/i.test(doc));
check('迟到位 时间戳非单调处理',
  /(non-monotonic|out of order)[^\n]{0,160}(sort|sorted)/i.test(doc));
check('迟到位 事件越窗丢弃计数',
  /(outside|beyond)[^\n]{0,80}window[\s\S]{0,120}(discard|reason count)/i.test(doc));
check('缓存目录不可写→直算不 5xx',
  /(not writable)[^\n]{0,160}(compute directly|no 5xx)/i.test(doc));

// ---- 4. delivery-dimension freeze ----
check('固化时机 merge_check 全绿后落账前',
  /merge_check[\s\S]{0,200}(all green|green)[\s\S]{0,200}(before the merge|deterministic script)/i.test(doc) ||
  /(deterministic script)[\s\S]{0,160}merge_check/i.test(doc));
check('固化语义（可弃≠可重算例外）',
  /(discardable|not recomputable|cannot be recomputed)/i.test(doc));

// ---- 5. version discipline ----
check('v1 冻结后变更须开单 bump',
  /(bump|v1\.x|v2)/i.test(doc) && /(new ticket|requires a new)/i.test(doc));

// ---- the cross-reference section's three deltas ----
check('对照小节三处 delta',
  /(three deltas|3 deltas|three differences)/i.test(doc) ||
  /delta[\s\S]{0,80}(three|3)/i.test(doc));

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
