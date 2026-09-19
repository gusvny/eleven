/**
 * smoke/client-contract.mjs —— sandbar-providers client entry inject 契约冒烟
 * （工单 t260916-26，dsh 0.1.5 会话视图扩展面适配）。
 *
 * 直跑：node smoke/client-contract.mjs（node ≥22.18 原生 type-stripping）。
 * 覆盖：
 *   A. 契约纯函数（src/client/inject-contract.ts）：
 *      CLIENT_INJECT 白名单值、validateInject 合法输入、畸形输入全拒绝
 *      （null/undefined/非数组/空数组/空串/非字符串元素/白名单外服务名/去重）。
 *      畸形输入用例即验收③的 UT 面：声明面收窄后 entry 不依赖任何可缺席服务，
 *      pending 结构性不可能；validateInject 锁死白名单防回归（注：它不在生产
 *      装载路径上，是契约防御不是降级路径本身）。
 *   B. 源码防漂移：index.tsx 必须经 ./inject-contract 导入 inject，不得绕开
 *      契约直写数组；死类型 import ConversationViewDefinition 不得回潮；
 *      契约模块注释保持 CJK 引号纪律（保产物断言零误报）。
 *   C. 产物防回归（lib/client.js）：契约常量与 inject 接线编译在产物里；
 *      编译后的字符串字面量面零脆弱服务名（"conversationViews" 双引号形态
 *      出现即红=重新声明了缺席服务）。
 *   D. 双插件契约同构：providers 与 knowledge 的契约模块必须同步（跨插件
 *      相对路径 import 属既定架构，workbench 同款先例）。
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { CLIENT_INJECT, KNOWN_STABLE_SERVICES, validateInject } from '../src/client/inject-contract.ts'
import {
  CLIENT_INJECT as KNOWLEDGE_CLIENT_INJECT,
  KNOWN_STABLE_SERVICES as KNOWLEDGE_STABLE_SERVICES,
} from '../../knowledge/src/client/inject-contract.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function deepEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b) }

/* ------------------------------------------------- A. 契约纯函数 */

section('A. inject 契约（白名单与畸形输入防线）')

ok(Array.isArray(CLIENT_INJECT) && deepEqual(CLIENT_INJECT, ['slots']),
   'CLIENT_INJECT 深等 ["slots"]（双版本稳定白名单子集）')

ok(deepEqual(validateInject(CLIENT_INJECT), ['slots']),
   'validateInject 合法输入放行')

const MUST_THROW = [
  ['null 入参', null],
  ['undefined 入参', undefined],
  ['非数组字符串', 'slots'],
  ['非数组数字', 42],
  ['对象入参', { 0: 'slots', length: 1 }],
  ['空数组', []],
  ['空串元素', ['']],
  ['含空串', ['slots', '']],
  ['白名单外脆弱服务名', ['conversationViews']],
  ['白名单外未知服务名', ['madeUpService']],
  ['非字符串元素', ['slots', 42]],
  ['嵌套数组', [['slots']]],
]
for (const [label, bad] of MUST_THROW) {
  let threw = false
  try { validateInject(bad) } catch { threw = true }
  ok(threw, `畸形输入拒绝：${label}`)
}

ok(deepEqual(validateInject(['slots', 'sessions']), ['slots', 'sessions']),
   '白名单内多服务放行')
ok(deepEqual(validateInject(['slots', 'slots']), ['slots']),
   '重复声明去重后放行')

/* ------------------------------------------------- B. 源码防漂移 */

section('B. 源码防漂移（entry 不得绕开契约）')

const entrySrc = await readFile(join(HERE, '../src/client/index.tsx'), 'utf8')
const contractSrc = await readFile(join(HERE, '../src/client/inject-contract.ts'), 'utf8')

ok(entrySrc.includes("from './inject-contract'"),
   "index.tsx 经 './inject-contract' 导入契约")
ok(!/export const inject = \[/.test(entrySrc),
   'index.tsx 无直写 inject 数组（防绕开契约）')
ok(!entrySrc.includes('ConversationViewDefinition'),
   '死类型 import ConversationViewDefinition 未回潮（0.1.5 已无此导出）')
ok(/\bexport const inject = CLIENT_INJECT\b/.test(entrySrc),
   'entry inject 接线 = CLIENT_INJECT')
ok(!contractSrc.includes('"conversationViews"'),
   '契约模块注释无 ASCII 双引号脆弱名（CJK 引号纪律，保产物断言零误报）')

/* ------------------------------------------------- C. 产物防回归 */

section('C. 产物防回归（lib/client.js / client.cjs）')

const bundle = await readFile(join(HERE, '../lib/client.js'), 'utf8')
const bundleCjs = await readFile(join(HERE, '../lib/client.cjs'), 'utf8')

ok(bundle.includes('const CLIENT_INJECT = ["slots"];'),
   '产物编译进契约常量（["slots"]）')
ok(bundle.includes('const inject = CLIENT_INJECT;'),
   '产物 inject 接线指向契约常量')
ok(bundle.includes('//#region src/client/inject-contract.ts'),
   '产物含契约模块编译段')
ok(!bundle.includes('"conversationViews"'),
   '产物零脆弱服务名字符串字面量（重新声明缺席服务即红）')
ok(bundle === bundleCjs,
   'client.js 与 client.cjs 同一产物（构建 copy 约定）')

/* ------------------------------------------------- D. 双插件契约同构 */

section('D. 双插件契约同构（providers × knowledge 必须同步）')

ok(deepEqual(CLIENT_INJECT, KNOWLEDGE_CLIENT_INJECT),
   '两插件 CLIENT_INJECT 完全一致')
ok(deepEqual([...KNOWN_STABLE_SERVICES], [...KNOWLEDGE_STABLE_SERVICES]),
   '两插件 KNOWN_STABLE_SERVICES 完全一致')

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
