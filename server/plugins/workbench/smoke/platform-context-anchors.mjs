/**
 * smoke/platform-context-anchors.mjs — smoke for the platform self-start context content anchors (t260905-09).
 *
 * Run: node smoke/platform-context-anchors.mjs (node >= 22.18 native type-stripping).
 * Under test: src/client/platform-context-anchors.ts (the PLATFORM_CONTEXT_ANCHORS source +
 * classifyPlatformContext pure function). The fixed stub samples for the anchors are the
 * same wording as integration/t260905-09/fixtures/ (the cross-directory freeze guard is an
 * integration-side ro scenario; this file embeds the same text as a second line of defense;
 * no cross-directory import — same self-contained discipline as lib_charter).
 *
 * Covers:
 *   A. Source hygiene: the anchor list is non-empty, ids unique, every anchor carries a
 *      provenance note, every match word list is valid.
 *   B. Hit surface: every anchor's fixture sample with identical text hits; leading
 *      whitespace tolerated; a hit with body text after the anchor line.
 *   C. Malformed input: non-string / empty string -> false; a pure anchor prefix (the whole
 *      message is only the anchor line) hits.
 *   D. Negative: an anchor phrase mentioned mid-text does not fold (guard against folding
 *      normal messages); a message whose first line does not start with an anchor does not fold.
 *   E. The inherent false-positive surface of prefix matching (declared case, so future
 *      maintainers do not "fix" it as a bug): a user paste that happens to start with an
 *      anchor line = a hit — indistinguishable by design (PromptContentPart has no metadata
 *      field, KI-046); the behavior must be true.
 */

import { PLATFORM_CONTEXT_ANCHORS, classifyPlatformContext } from '../src/client/platform-context-anchors.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** The fixture sample with identical text for each anchor (byte-synced with integration/t260905-09/fixtures/*.txt). */
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
  // Indistinguishable by design: a user paste starting exactly with an anchor line -> hits and folds (full text is one click away, no information lost).
  ok(classifyPlatformContext('# sandbar — 多项目工单引擎\n（用户粘贴的文档开头）') === true,
    '用户粘贴以锚行开头=命中（设计内限制，非缺陷）')
}

console.log(`\nplatform-context-anchors smoke: passed=${passed} failed=${failed}`)
process.exit(failed === 0 ? 0 : 1)
