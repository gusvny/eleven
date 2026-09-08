/**
 * smoke/allow-empty-create.mjs —— 「无文件改动」显式声明（t260901-01）冒烟。
 *
 * 直跑：node smoke/allow-empty-create.mjs（node ≥22.18 原生 type-stripping）。
 * 覆盖：
 *   A. epics-model.ts 纯函数：
 *      createWriteSetBlocked（空写集未勾选拦截且文案含两条出路 / 勾选放行 /
 *      非空写集放行）；buildCreatePayload（空写集+勾选才附 allow_empty_write_set /
 *      非空写集不带 / 空写集不勾不带 / 畸形行已由 invalidWriteSetLines 前置拦截）。
 *   B. 源码锁（桥路三层接通，模式同 selfcheck 源码锁惯例）：
 *      node.ts handleCreate 透传 allow_empty_write_set；epics.tsx 弹层复选框 +
 *      提交走 buildCreatePayload/createWriteSetBlocked + 复位三处；
 *      ticket.py schema + payload 声明字段。
 */

import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  buildCreatePayload, createWriteSetBlocked, invalidWriteSetLines,
} from '../src/client/epics-model.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fail++; console.error(`  ✗ ${label}`) }
}

/* ---------------- A. 纯函数 ---------------- */
console.log('A. epics-model.ts 「无文件改动」纯函数')
const blocked = createWriteSetBlocked('', false)
ok(blocked !== '', '空写集未勾选 → 拦截')
ok(blocked.includes('两条出路') && blocked.includes('allow_empty_write_set'),
  '拦截文案含两条出路口径与声明字段名')
ok(createWriteSetBlocked('', true) === '', '空写集已勾选 → 放行')
ok(createWriteSetBlocked('a.py', false) === '', '非空写集未勾选 → 放行')
ok(createWriteSetBlocked('  \n  ', false) !== '', '纯空白写集视同空 → 拦截')

const payload1 = buildCreatePayload({ workflow: 'dev-lane', title: 't', body: 'b', epic: 'e' }, '', true)
ok(payload1.allow_empty_write_set === true && Array.isArray(payload1.write_set) && payload1.write_set.length === 0,
  '空写集+勾选 → payload 带 allow_empty_write_set=true 且 write_set=[]')
const payload2 = buildCreatePayload({ workflow: 'dev-lane', title: 't', body: 'b', epic: 'e' }, ' a.py \nb.py ', true)
ok(payload2.allow_empty_write_set === undefined && payload2.write_set.join(',') === 'a.py,b.py',
  '非空写集（勾选也不带）→ 写集优先，声明不附')
const payload3 = buildCreatePayload({ workflow: 'dev-lane', title: 't', body: 'b', epic: 'e' }, '', false)
ok(payload3.allow_empty_write_set === undefined, '空写集未勾选 → payload 不带声明（拦截在前）')
ok(buildCreatePayload({ workflow: 'w', title: ' t ', body: 'b', epic: 'e' }, '', true).title === 't',
  '标题 trim 进 payload')
ok(invalidWriteSetLines('/abs\n../up\na\\b\nok.py').length === 3,
  '畸形行仍由 invalidWriteSetLines 前置拦截（3 条非法）')

/* ---------------- B. 源码锁 ---------------- */
console.log('B. 桥路三层源码锁')
const here = path.dirname(fileURLToPath(import.meta.url))
const nodeSrc = await readFile(path.join(here, '..', 'node.ts'), 'utf8')
ok(/body\?\.allow_empty_write_set === true/.test(nodeSrc) && /args\.allow_empty_write_set = true/.test(nodeSrc),
  'node.ts handleCreate 透传 allow_empty_write_set（显式 true 才带）')
const epicsSrc = await readFile(path.join(here, '..', 'src', 'client', 'epics.tsx'), 'utf8')
ok(epicsSrc.includes('createAllowEmpty') && /type="checkbox"/.test(epicsSrc),
  'epics.tsx 弹层有「无文件改动」复选框')
ok(epicsSrc.includes('buildCreatePayload') && epicsSrc.includes('createWriteSetBlocked'),
  'epics.tsx 提交判定走纯函数单点')
ok((epicsSrc.match(/setCreateAllowEmpty\(false\)/g) || []).length >= 3,
  'createAllowEmpty 复位点 ≥3（建议回填 / 关弹层 / 切模板）')
const ticketSrc = await readFile(path.join(here, '..', '..', '..', 'tools', 'ticket.py'), 'utf8')
ok(ticketSrc.includes("'allow_empty_write_set': {'type': 'boolean'"), 'ticket.py schema 声明字段')
ok(ticketSrc.includes("'allow_empty_write_set': bool(a.get('allow_empty_write_set'))"),
  'ticket.py _create payload 透传字段')

console.log(`\n结果：${pass} 绿 / ${fail} 红`)
process.exit(fail === 0 ? 0 : 1)
