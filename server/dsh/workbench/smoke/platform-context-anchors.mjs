/**
 * smoke/platform-context-anchors.mjs —— 平台自启上下文内容锚冒烟（t260905-09）。
 *
 * 直跑：node smoke/platform-context-anchors.mjs（node ≥22.18 原生 type-stripping）。
 * 被测=src/client/platform-context-anchors.ts（PLATFORM_CONTEXT_ANCHORS 真源 +
 * classifyPlatformContext 纯函数）。锚的固定桩样本与 integration/t260905-09/
 * fixtures/ 同口径（逐字同步的看守归 integration 侧 ro 冻结场景，本文件内嵌
 * 同文样本双保险；跨目录 import 不引入——同 lib_charter 自足纪律）。
 *
 * 覆盖：
 *   A. 真源卫生：锚清单非空、id 唯一、每锚带出处注、match 词表合法。
 *   B. 命中面：每锚的 fixture 同文样本命中；前导空白容错；锚行后带正文命中。
 *   C. 畸形输入：非字符串/空串 → false；纯锚前缀（整条只有锚行）命中。
 *   D. 负向：中段提及锚字样不折（普通消息误折守卫）；首行非锚开头不折。
 *   E. 前缀命中的固有误折面（声明性用例，防后人当缺陷修）：用户粘贴恰好以
 *      锚行开头=命中——设计内不可分辨（PromptContentPart 无 metadata 字段，
 *      KI-046 实锤；声明见模块头注），行为必须是 true。
 */

import { PLATFORM_CONTEXT_ANCHORS, classifyPlatformContext } from '../src/client/platform-context-anchors.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 每锚的 fixture 同文样本（与 integration/t260905-09/fixtures/*.txt 逐字同步）。 */
export const ANCHOR_FIXTURE_TEXT = {
  'runtime-context-snapshot': 'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\nCurrent DSH file policy: workspace-write.',
  'runtime-context-preamble': 'The following workspace instructions may be relevant to your work. Use them as guidance when applicable.',
  'dsh-file-policy': 'Current DSH file policy: workspace-write. Any available operation enforced by the DSH file sandbox may modify files under the session workspace.',
  'instructions-from': 'Instructions from: /Users/x/project/CLAUDE.md\n# sandbar — 多项目工单引擎\n\n硬规则正文……',
  'claude-md-heading': '# sandbar — 多项目工单引擎\n\n从 suyou 仓物理搬迁而来。',
}

section('A 真源卫生')
{
  ok(Array.isArray(PLATFORM_CONTEXT_ANCHORS) && PLATFORM_CONTEXT_ANCHORS.length >= 3, '锚清单非空')
  const ids = PLATFORM_CONTEXT_ANCHORS.map(a => a.id)
  ok(new Set(ids).size === ids.length, '锚 id 唯一')
  ok(PLATFORM_CONTEXT_ANCHORS.every(a => typeof a.note === 'string' && a.note.length > 10), '每锚带出处注')
  ok(PLATFORM_CONTEXT_ANCHORS.every(a => a.match === 'exact' || a.match === 'first-line'), 'match 词表合法')
  ok(PLATFORM_CONTEXT_ANCHORS.every(a => Object.hasOwn(ANCHOR_FIXTURE_TEXT, a.id)), '每锚有 fixture 同文样本')
}

section('B 命中面：逐锚 fixture 同文样本')
{
  for (const anchor of PLATFORM_CONTEXT_ANCHORS) {
    const text = ANCHOR_FIXTURE_TEXT[anchor.id]
    ok(classifyPlatformContext(text) === true, `命中：${anchor.id}`)
    ok(classifyPlatformContext(`\n  ${text}`) === true, `前导空白容错：${anchor.id}`)
  }
}

section('C 畸形输入')
{
  ok(classifyPlatformContext('') === false, '空串 → false')
  ok(classifyPlatformContext(null) === false && classifyPlatformContext(undefined) === false, 'null/undefined → false')
  ok(classifyPlatformContext(42) === false && classifyPlatformContext({}) === false, '非字符串 → false')
  ok(classifyPlatformContext('Current runtime context. This snapshot supersedes earlier runtime-context snapshots.') === true, '纯锚行（整条只有锚）命中')
}

section('D 负向：普通消息零误折')
{
  ok(classifyPlatformContext('帮我看看 CLAUDE.md 的硬规则') === false, '中段提及 CLAUDE.md 不折')
  ok(classifyPlatformContext('这句「Current DSH file policy: workspace-write」是什么意思？') === false, '中段提及锚原文不折')
  ok(classifyPlatformContext('今天想聊聊 Instructions from: 这个短语') === false, '首行含锚字样但非锚开头不折')
  ok(classifyPlatformContext('普通用户消息正文') === false, '纯普通消息不折')
}

section('E 前缀命中的固有误折面（声明性用例）')
{
  // 设计内不可分辨：用户粘贴恰好以锚行开头 → 命中即折（可点开看全文，信息不丢）。
  ok(classifyPlatformContext('# sandbar — 多项目工单引擎\n（用户粘贴的文档开头）') === true,
    '用户粘贴以锚行开头=命中（设计内限制，非缺陷）')
}

console.log(`\nplatform-context-anchors smoke: passed=${passed} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
