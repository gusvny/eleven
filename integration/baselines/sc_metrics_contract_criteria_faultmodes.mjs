// t260901-11 M0 集成测试：口径钉死与故障面（review 三轮收敛成果的回归守卫）
// 验收对象：
//  1. 三维口径（时间/交付/token）各有真源与已知近似声明
//  2. 故障模式取舍清单：沿用 agent-usage.ts 八项 + 新增独立小节
//  3. 三态用例（畸形/缺失/迟到）各条有预期行为
//  4. 交付维固化与 LOC base 钉死
//  5. 版本与变更纪律

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

// ---- 1. 三维口径 ----
// 时间
check('时间窗公式 [from_i, from_{i+1})', /from_i[\s\S]{0,40}from_\{?i\+1\}?/.test(doc) || /\[from_i,\s*from_/i.test(doc));
check('末窗封口规则 min(closed_ts)', /min[\s(（]+[^\n)]{0,40}closed/.test(doc));
check('rework=多窗加总', /rework[^\n]{0,60}多窗|多窗[^\n]{0,40}rework/i.test(doc));
check('human_wait 人门口径', doc.includes('human_wait'));
check('v2 精确口径仅登记', /v2[\s\S]{0,120}(登记|不在\s*v1|后续)/.test(doc));
// 交付
check('LOC add/del 分列不合并净值', /add[\s\S]{0,30}del/.test(doc) && /分列/.test(doc));
check('base=lane 创建点主干 commit', /base[^\n]{0,60}创建点/.test(doc));
check('base hash 固化进缓存（delivery.base）', /delivery[\s\S]{0,30}base|base[^\n]{0,40}固化/.test(doc));
check('中途主干合入不改 base', /中途[^\n]{0,60}不改变?\s*base|不改变?\s*base[^\n]{0,60}创建点/.test(doc));
check('commits 计数含 worker 代落盘', /rev-list[^\n]{0,60}代落盘|代落盘[^\n]{0,40}commit/.test(doc) || /commits[^\n]{0,80}代落盘/.test(doc));
// token
check('只计 assistant/message', /assistant\/message/.test(doc));
check('chunk 镜像不计入（防翻倍）', /assistant\/chunk[\s\S]{0,80}(不计|防翻倍)/.test(doc) || /不计入[\s\S]{0,40}assistant\/chunk/.test(doc));
check('cacheRead 单列不并入 tokens_total', /cacheRead[\s\S]{0,80}(不并入|单列)/.test(doc));

// ---- 2. 故障模式取舍清单 ----
check('声明参考实现 agent-usage', /agent-usage/.test(doc));
const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧'];
check('八项取舍序号①-⑧齐', CIRCLED.every(c => doc.includes(c)),
  `缺：${CIRCLED.filter(c => !doc.includes(c)).join('')}`);
check('取舍带「带过来」声明', doc.includes('带过来'));
check('取舍带「不带」选项语义', doc.includes('不带'));
check('新增故障模式独立小节', /不覆盖/.test(doc) && /git[\s\S]{0,120}(delivery=null|软降级)/.test(doc));
check('timeline 缺 from 计数不静默丢', /from[\s\S]{0,120}(计\s*0|reason 计数|不静默)/.test(doc));

// ---- 3. 三态用例 ----
check('畸形态用例 window=abc', /window=abc/.test(doc));
check('缺失态 无凭据 SKIP', /SKIP/.test(doc) && /(无凭据|无凭据 SKIP)/.test(doc));
check('缺失态 会话文件不存在软降级', /(会话文件|会话目录)[^\n]{0,80}(软降级|空数据|人话)/.test(doc));
check('缺失态 timeline 无 running 条目', /(无\s*running|无 running)[^\n]{0,80}(计\s*0|0)/.test(doc));
check('迟到位 时间戳非单调处理', /(非单调|乱序)[^\n]{0,80}(排序|排序后)/.test(doc));
check('迟到位 事件越窗丢弃计数', /(越[出窗]|越窗)[^\n]{0,80}(丢弃|计数)/.test(doc));
check('缓存目录不可写→直算不 5xx', /(不可写)[^\n]{0,120}(直算|不\s*5xx)/.test(doc));

// ---- 4. 交付维固化 ----
check('固化时机 merge_check 全绿后落账前', /(全绿)[^\n]{0,80}(落账前|固化)/.test(doc) || /落账前[^\n]{0,60}固化/.test(doc));
check('固化语义（可弃≠可重算例外）', /(可弃|不可重算)/.test(doc));

// ---- 5. 版本纪律 ----
check('v1 冻结后变更须开单 bump', /(bump|v1\.x|v2)/.test(doc) && /(开.{0,4}工单|新工单)/.test(doc));

// ---- 对照小节三处 delta ----
check('对照小节三处 delta', /(三处|3 处)[^\n]{0,40}delta|delta[^\n]{0,40}(三处|3 处)/.test(doc));

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
