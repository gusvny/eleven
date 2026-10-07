// Integration scenario t260904-07 ① — session-charter 交付契约冻结（ro 静态面）。
//
// Intent (gray-box, user perspective):
//   冻结会话宪章（server/session_charter.md ＝ 会话开局注入源，其「当前在案授权」栏是
//   agent 行使权限的依据）在**工作台链路上的可感知契约**：交付物在位、结构要素在文、
//   端点两端同源、内置回落在位、打标同源。
//   **S1「charter ↔ notes/discussions 真源附录逐字一致」已于 260926 删除**（宿主令
//   「删 S1，不开票」）：它把运行时文本锚死到一份 notes 讨论档，而 notes/ 不在任何
//   泳道写集内（有意设计）→ 任何交付涉及 charter 的票对该断言**结构性不可满足**，
//   只能靠人回主仓手写；实测代价＝卡死 t260925-21 九轮仲裁（每轮附一趟全量）、
//   t260907-05 一次、附录回写当刻主仓立刻出现镜像红；且与本场景 S2 自己的原则
//   （授权栏内容会合法变更 → 不锚内容）自相矛盾——同一套契约不该一边说「内容可变
//   不锚」一边把整份文件的逐字相等焊到另一份文档上。真源同步自此交回**人的流程**：
//   charter 改动落票 + 人审签字时由主审核对（这条风险的真实闸门是 git 版本化 +
//   人门，不是文档复本比对）。
//
// High-level steps:
//   S1 已删（历史面＝260904 拍板④，260926 宿主令删除；见上）。
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
// ENV_FAIL>0 → exit 2. 纯只读（单源读取+源码扫描），零写入。

import { readFileSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`ok   ${name}`); }
  else { fail++; console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

const SRC_CHARTER = 'server/session_charter.md';
const WB = 'server/plugins/workbench';
const EP = '/sandbar-workbench/api/session-charter';

const read = (p) => { try { return readFileSync(p, 'utf8'); } catch { return null; } };

// ---- 交付物在位（S1 删除后此处只保「存在」信号；不锚任何票外文档）----
const charter = read(SRC_CHARTER);
check('charter 文件落地', charter !== null,
  `${SRC_CHARTER} 不存在（实现段落地前红属预期；merge 期必须绿）`);

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
// t261008-01 arbitrate: the client no longer concatenates the marker itself —
// the injection is composed by the host-module function (composeCharterInjection)
// that owns the constant. The contract (single-source marker, no client-side
// literal rewrite) is unchanged, so per this scenario's own S3 principle
// (contract-preserving refactor must not break this scenario) the client leg
// accepts BOTH shapes: a direct CHARTER_MARKER reference, or composing through
// the host module that defines the constant. The drift face is asserted
// directly instead: the client must never carry the raw marker literal.
const clientSameSource = clientSrc !== null
  && (clientSrc.includes('CHARTER_MARKER')
    || /composeCharterInjection|charterTitleLine/.test(clientSrc));
const clientLiteralRewrite = clientSrc !== null && clientSrc.includes(MARK);
check('客户端经同源常量引用标记（session-entry.tsx 引 CHARTER_MARKER 或经宿主模块组装，不重写字面量）',
  hostHasMark && clientSameSource && !clientLiteralRewrite,
  '客户端重写字面量=两处漂移面（R7 同源纪律）；marker 漂移=渲染器不识别=折叠件失明');
check('端点响应体含 kind=charter 打标字段（node.ts）',
  nodeSrc !== null && /kind:\s*'charter'/.test(nodeSrc),
  'node.ts session-charter 端点响应无 kind 字段——消息失去身份锚，折叠件无从归属');

console.log(`SUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`);
process.exit(fail > 0 ? 1 : 0);
