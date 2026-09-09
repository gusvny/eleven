/**
 * smoke/allow-empty-create.mjs — smoke for the explicit "no file changes" declaration (t260901-01).
 *
 * Run: node smoke/allow-empty-create.mjs (node >= 22.18 native type-stripping).
 * Covers:
 *   A. epics-model.ts pure functions:
 *      createWriteSetBlocked (empty write set blocked without the checkbox, message names both
 *      ways out / allowed when checked / allowed when non-empty); buildCreatePayload
 *      (allow_empty_write_set only attached when empty+checked / not attached when non-empty /
 *      not attached when empty+unchecked / malformed lines already blocked earlier by
 *      invalidWriteSetLines).
 *   B. Source-text locks (bridge wiring lock, same pattern as the selfcheck source locks):
 *      node.ts handleCreate passes allow_empty_write_set through; epics.tsx modal checkbox +
 *      submit goes through buildCreatePayload/createWriteSetBlocked + three reset points;
 *      ticket.py schema declares the payload field.
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

/* ---------------- A. Pure functions ---------------- */
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

/* ---------------- B. Source-text locks ---------------- */
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
