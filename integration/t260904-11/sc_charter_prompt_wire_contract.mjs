// Integration scenario t260904-11 — charter prompt wire 契约冻结（ro 供给只读面）。
//
// Intent (gray-box, user perspective):
//   KI-046 的病根是一条**跨组件接缝**：客户端把什么形状的载荷发给平台 session.prompt，
//   平台 zod 门收不收——07 票正是这条接缝两端从未被同场验证过（客户端单测只测渲染
//   纯函数，旅程场景被环境缴械）。developer 的 ki046 UT（workbench/tests）锚的是
//   接缝的客户端一端（真跑注入函数、桩捕获 prompt 实参）；本场景锚接缝的**平台一端
//   与镜像同步责任**，intent 级不同层，不重复：
//     W1 真源锚：平台供给内 dsh-host-apiproxy bundle 的 session.prompt 请求门
//        确实是「content: array(promptContentPart) 分片数组门」且 text/image 判别
//        联合在文——锚定的是**真实安装工件**，不是镜像自身（防「镜像验镜像」循环）。
//     W2 用户可感知拒收文案真源在文：`invalid payload for ${method}`（用户 toast
//        所见的错误家族来源；平台改文案=契约漂移信号，人审复核）。
//     W3 冻结镜像语义：按「外部调用形状单测规范」（docs/testing-guide.md，真 schema
//        不可导入则仓内冻结镜像+声明同步责任）用 zod 重建请求门——修好的分片载荷
//        必须通过；KI-046 违规形状（裸字符串 content）必须被拒；text 缺 text 字段、
//        非法 mode 同拒。镜像与 W1 真源锚的同步责任由本场景承担：平台门漂移（升级
//        改形状/改文案）→ W1/W2 红 → 人审后同步 W3 镜像。
//   本场景对 KI-046 的回归价值：平台一端的门被冻结——若未来有人「放宽客户端」或
//   「平台改门」任一方向静默漂移，本场景红；配合 developer UT（客户端一端）合拢
//   即接缝两端的完整回归网。
//
// High-level steps:
//   S1 解析平台供给根（DSH_SUPPLY_ROOT env > /tmp/wb-deps/node_modules >
//      ~/.dsh/profiles/node_modules；全只读）。缺供给=显式红并点名缺什么
//      （供给缺失=ENV_FAIL 显式环境红，不 exit 0 假绿——KI-046 闸穿透教训，t260904-12 三态化。）
//   S2 读 dsh-host-apiproxy/lib/index.js 源面，宽松正则锚 W1 两要素（不锚私有
//      压缩变量名——契约不变的实现重构不得打破本场景）。
//   S3 锚 W2 拒收文案模板在文。
//   S4 用供给内 zod 声明冻结镜像（text/image 判别联合 + queue/steer + content
//      数组，宽严与 W1 原文逐条对照），跑四组 safeParse 判定。
//
// Execution contract: stdout last line `SUMMARY ran=<n> pass=<n> fail=<k> env_fail=<e> na=0` (t260904-12 three-state);
// FAIL>0 → exit 1。纯只读（供给文件读取+内存 safeParse），零写入，毫秒级。

import { readFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

// 三态契约（t260904-12）：pass/fail/env_fail 计数；缺环境=env_fail 显式红不 exit 0。
let pass = 0, fail = 0, env = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass += 1; console.log(`ok    ${name}`); }
  else { fail += 1; console.log(`FAIL  ${name}${detail ? ' — ' + detail : ''}`); }
};
const envFail = (name, reason = '') => {
  env += 1; console.log(`ENV_FAIL [${name}] exit=2${reason ? ' —— ' + reason : ''}`);
};

// ---- S1 平台供给根解析（缺供给=ENV_FAIL 环境红，不静默）----
const candidates = [
  process.env.DSH_SUPPLY_ROOT,
  '/tmp/wb-deps/node_modules',
  join(homedir(), '.dsh/profiles/node_modules'),
].filter(Boolean);
const supplyRoot = candidates.find((p) => existsSync(join(p, '@deepseek-ai/dsh-host-apiproxy/lib/index.js'))
  && existsSync(join(p, 'zod')));
if (!supplyRoot) {
  envFail('平台供给根可解析（apiproxy + zod 在场）',
    `依次试过：${candidates.join(' ; ')}——缺 dsh-host-apiproxy 或 zod；按测试供给声明补装备后重跑`);
  console.log(`SUMMARY ran=${pass+fail+env} pass=${pass} fail=${fail} env_fail=${env} na=0`);
  process.exit(2);
}
check('平台供给根可解析（apiproxy + zod 在场）', true, supplyRoot);

// ---- S2 真源锚：平台门=分片数组门 + text/image 判别联合（宽松正则，不锚压缩名）----
const apiSrc = readFileSync(join(supplyRoot, '@deepseek-ai/dsh-host-apiproxy/lib/index.js'), 'utf8');
check('session.prompt 请求门 content=array(promptContentPart)（分片数组门在文）',
  /content:\s*z[\w$]*\.array\(\s*promptContentPartSchema\s*\)/.test(apiSrc),
  'dsh-host-apiproxy bundle 中 sessionPromptRequestSchema 的 content 门形状漂移');
check('promptContentPart=text/image 判别联合（discriminatedUnion("type")）在文',
  /promptContentPartSchema\s*=\s*z[\w$]*\.discriminatedUnion\(\s*["']type["']\s*,/.test(apiSrc),
  '分片判别联合定义漂移');

// ---- S3 用户可感知拒收文案真源在文 ----
check('拒收文案模板 `invalid payload for ${method}` 在文（用户 toast 错误家族来源）',
  apiSrc.includes('invalid payload for ${method}'),
  '平台改文案=契约漂移信号，人审复核后同步本场景');

// ---- S4 冻结镜像语义（同步责任：与 S2 真源锚对照，平台门漂移须两处同步）----
const { z } = await import('file://' + join(supplyRoot, 'zod/index.js'));
// 镜像宽严对照真源原文（L604-618 promptContentPartSchema / sessionPromptRequestSchema）：
//   text 片 {type:'text', text:string}；image 片 {type:'image', mediaType, data, name?}；
//   mode union queue|steer；content 无 min 约束（空数组平台也收——镜像如实，不私加严）。
//   image 片 mediaType 限 png/jpeg/webp/gif 字面量联合（imageMediaTypeSchema）；
const imageMediaType = z.union([
  z.literal('image/png'), z.literal('image/jpeg'), z.literal('image/webp'), z.literal('image/gif'),
]);
const promptContentPart = z.discriminatedUnion('type', [
  z.object({ type: z.literal('text'), text: z.string() }),
  z.object({ type: z.literal('image'), mediaType: imageMediaType, data: z.string(), name: z.string().optional() }),
]);
const sessionPromptRequest = z.object({
  sessionId: z.string(),
  mode: z.union([z.literal('queue'), z.literal('steer')]),
  content: z.array(promptContentPart),
  clientTimeZone: z.string().optional(),
});
const BASE = { sessionId: 's-fix', mode: 'queue' };
const attempt = (content, mode) => sessionPromptRequest.safeParse({ ...BASE, mode, content }).success;

check('W3a 修复后形状 [{type:text,text}] + queue = 平台收（KI-046 正例）',
  attempt([{ type: 'text', text: '你是…' }], 'queue'));
check('W3b 违规旧形状：content=裸字符串 = 平台拒（KI-046 回归钉）',
  !attempt('你是…', 'queue'));
check('W3c text 片缺 text 字段 = 拒', !attempt([{ type: 'text' }], 'queue'));
check('W3d 非法 mode（send）= 拒；steer 合法 = 收',
  !attempt([{ type: 'text', text: 'x' }], 'send')
  && attempt([{ type: 'text', text: 'x' }], 'steer'));

console.log(`SUMMARY ran=${pass+fail+env} pass=${pass} fail=${fail} env_fail=${env} na=0`);
process.exit(fail > 0 ? 1 : env > 0 ? 2 : 0);
