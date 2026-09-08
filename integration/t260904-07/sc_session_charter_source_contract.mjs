// Integration scenario t260904-07 ① — session-charter 交付契约冻结（ro 静态面）。
//
// Intent (gray-box, user perspective):
//   用户验收口径第一依据=宿主定稿真源（notes/discussions/260904-project-session-charter.md
//   附录模板，拍板④）：server/session_charter.md 必须与真源附录逐字同步——该文件
//   是「当前在案授权」栏的授权档案第一环（git 版本化），漂移=授权声明与定稿脱钩；
//   宿主合法定稿变更须两处同步（回真源补口径），本场景红即提示同步缺失或落地缺失。
//   同时冻结端点接线的可感知契约三件：注册路径与客户端请求路径同源（KI-042 同族
//   「两端路径漂移→恒 404 静默吞」的对症看守）、内置回落模板在位（缺文件不 5xx 的
//   前提）。与随票 smoke intent 级不同层：smoke 锚实现守卫源文本锚（L1/L2），本场景
//   锚「交付物↔宿主定稿真源一致性」与跨端接线一致性（用户验收真源面）。
//
// High-level steps:
//   S1 真源附录（最后一个 ```markdown fenced block）与 server/session_charter.md
//      逐字一致（去尾空白后比对；文件缺失=红——实现段落地前红属预期，TDD 信号，
//      arbitrate/merge 期必须绿）。
//   S2 结构契约要素在文：四占位符、两纪律语义锚（notes 落盘攒批 / 点名修复先告知）、
//      「## 当前在案授权」节存在（只锚节存在不锚内容——授权栏被宿主合法写入是设计
//      内变更）、project:sandbar / project:suyou 两分段。
//   S3 端点注册路径与客户端请求路径可各自解析到同一路径字面量（直接字面量，或经
//      同源常量模块间接命中——两种实现形态都过，契约不变的实现重构不得打破本场景）。
//   S4 内置回落模板在位且含占位符（宽松形状匹配，不锚私有命名）。
//   S5 打标同源锚（t260905-04）：charter 机读标记（<!-- workbench:kind:charter -->）
//      在宿主侧 session-charter.ts 同源定义、客户端 session-entry.tsx 经常量引用、
//      node.ts 端点响应体含 kind:'charter' 字段——marker 字面量两处漂移=折叠件失明
//      （静默退化回整段刷屏，用户验收①无声失效），同 KI-042 族「漂移→静默吞」
//      的对症看守。pre-implement 红属预期（TDD 信号）。
//
// Execution contract (三态，定稿 §7.3 闸内无 SKIP): stdout last line
// `SUMMARY pass=<n> fail=<k> env_fail=<e> na=<w>`; FAIL>0 或全 na → exit 1,
// ENV_FAIL>0 → exit 2. 纯只读（双源读取+源码扫描），零写入。

import { readFileSync, existsSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`ok   ${name}`); }
  else { fail++; console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

const SRC_DISCUSSION = 'notes/discussions/260904-project-session-charter.md';
const SRC_CHARTER = 'server/session_charter.md';
const WB = 'server/plugins/workbench';
const EP = '/sandbar-workbench/api/session-charter';

const read = (p) => { try { return readFileSync(p, 'utf8'); } catch { return null; } };
const stripTail = (s) => s.replace(/\s+$/, '');

// ---- S1 真源附录 ↔ charter 文件逐字同步 ----
const discussion = read(SRC_DISCUSSION);
check('真源讨论档在位（只读参考源）', discussion !== null, SRC_DISCUSSION);

const fenceRe = /```markdown\n([\s\S]*?)```/g;
let appendix = null, m;
while (discussion && (m = fenceRe.exec(discussion)) !== null) appendix = m[1]; // 取最后一个=附录定稿
check('真源附录模板可提取（```markdown fenced block）', appendix !== null && appendix.trim().length > 0);

const charter = read(SRC_CHARTER);
// 命名迁移 token 容忍（t260907-05 仲裁归因）：charter 文件随宿主令在写集内把插件名/
// 前缀改新（suyou-*→sandbar-*），而其逐字真源附录在 notes/（票外只读，归宿主/后续
// docs 票）——命名迁移票对「两处同步」结构性不可满足。比对分两层：①内容漂移检测=
// 双方命名 token 归一到占位后逐字比对（有人改 charter 不回写真源仍红）；②纯命名
// 迁移差异（归一后逐字一致）有声放行并点名，不静默。断言力不降：非 token 差异=
// 红不变。
const NAME_TOKEN_RE = /\b(?:sandbar|suyou)-(?:workbench|admin-ui|knowledge|providers|temporal-tools|ui-check|tools)\b/g;
const normNames = (s) => s.replace(NAME_TOKEN_RE, '⟪plugin-token⟫');
if (charter === null) {
  check('charter 文件落地', false, `${SRC_CHARTER} 不存在（实现段落地前红属预期；merge 期必须绿）`);
} else {
  const literalEqual = stripTail(charter) === stripTail(appendix ?? '\u0000');
  const normEqual = stripTail(normNames(charter)) === stripTail(normNames(appendix ?? '\u0000'));
  const migratedOnly = !literalEqual && normEqual;
  check('charter 文件与真源附录逐字一致',
    literalEqual || migratedOnly,
    literalEqual
      ? '逐字一致'
      : (migratedOnly
        ? '逐字差异全部为命名迁移 token（t260907-05 宿主令：charter 在写集内改新名，真源附录在 notes/ 票外不可同票同步；归一后逐字一致=零内容漂移；宿主更新 notes 真源后自回逐字一致）'
        : '漂移=授权档案与宿主定稿脱钩（归一后仍不一致）；合法定稿变更须两处同步（回真源补口径后本条自回绿）'));
}

// ---- S2 结构契约要素（锚语义与节存在，不锚会随合法授权变更的内容）----
const body = charter ?? '';
check('占位符 {{project_key}} 在文', body.includes('{{project_key}}'));
check('占位符 {{project_name}} 在文', body.includes('{{project_name}}'));
check('占位符 {{primary_dir}} 在文', body.includes('{{primary_dir}}'));
check('占位符 {{engine_root}} 在文', body.includes('{{engine_root}}'));
check('纪律①notes 落盘攒批在文（语义锚）', /攒批/.test(body), '用户原话：确定了让落盘才提交，不一段一提交');
check('纪律②点名修复可进 lane 但先告知在文（语义锚）', /先告知/.test(body), '用户原话：明确要求修复某个工单可动 lane，但要提前告知');
check('「当前在案授权」节存在（授权档案锚；不锚内容——合法写入是设计内变更）', /^## 当前在案授权/m.test(body));
check('project:sandbar 分段在文', /^## project:sandbar/m.test(body));
check('project:suyou 分段在文', /^## project:suyou/m.test(body));

// ---- S3 端点注册路径 ↔ 客户端请求路径同源（KI-042 同族防漂移）----
// 解析语义：一侧「可解析到路径」=该侧源文件含路径字面量，或 import 了含该字面量的
// 同源常量模块（session-charter.ts）。字面量实现与常量实现两形态都过。
const nodeSrc = read(`${WB}/node.ts`);
const clientSrc = read(`${WB}/src/client/session-entry.tsx`);
const hostModSrc = read(`${WB}/src/host/session-charter.ts`);

const resolvable = (src) => (src !== null && (src.includes(EP) ||
  (src.includes('session-charter') && hostModSrc !== null && hostModSrc.includes(EP))));

check('宿主侧可解析到端点路径（node.ts 字面量或同源常量）', resolvable(nodeSrc),
  `${WB}/node.ts 无 ${EP} 直字面量且无 session-charter 模块引用`);
check('客户端侧可解析到同一路径（session-entry.tsx 字面量或同源常量）', resolvable(clientSrc),
  `${WB}/src/client/session-entry.tsx 无 ${EP} 直字面量且无 session-charter 模块引用`);
check('两侧解析到同一路径字面量（防 KI-042 同族「路径漂移→404 静默吞」）',
  resolvable(nodeSrc) && resolvable(clientSrc));

// ---- S4 内置回落模板在位（缺文件回落的前提；宽松形状匹配，不锚私有命名）----
const fallbackHay = [hostModSrc, nodeSrc].filter(s => s !== null).join('\n');
const hasFallback = /(?:DEFAULT|FALLBACK|BUILTIN|INTERNAL)[A-Z_]*\s*(?::\s*string)?\s*=\s*[`'"][^`'"]{40,}/.test(fallbackHay)
  && fallbackHay.includes('{{project_key}}');
check('内置回落模板在位且含占位符（缺文件/读失败回落不 5xx 的前提）', hasFallback,
  '在 node.ts / src/host/session-charter.ts 找非空模板常量（含 {{project_key}}）');

// ---- S5 打标同源锚（t260905-04；marker 漂移=折叠件失明静默退化，KI-042 同族看守）----
const MARK = '<!-- workbench:kind:charter -->';
const hostHasMark = hostModSrc !== null
  && (hostModSrc.includes(MARK) || /CHARTER_MARKER\s*(?::\s*string)?\s*=/.test(hostModSrc));
check('charter 机读标记在宿主侧同源定义（session-charter.ts 字面量或 CHARTER_MARKER 常量）',
  hostHasMark, `${WB}/src/host/session-charter.ts 无 ${MARK} 字面量亦无 CHARTER_MARKER 常量`);
check('客户端经同源常量引用标记（session-entry.tsx 引 CHARTER_MARKER，不重写字面量）',
  hostHasMark && clientSrc !== null && clientSrc.includes('CHARTER_MARKER'),
  '客户端重写字面量=两处漂移面（R7 同源纪律）；marker 漂移=渲染器不识别=折叠件失明');
check('端点响应体含 kind=charter 打标字段（node.ts）',
  nodeSrc !== null && /kind:\s*'charter'/.test(nodeSrc),
  'node.ts session-charter 端点响应无 kind 字段——消息失去身份锚，折叠件无从归属');

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
