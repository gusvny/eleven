/**
 * smoke/write-lifecycle.mjs — host/client half-smoke for the write-set lifecycle (t260829-07).
 *
 * Run: node smoke/write-lifecycle.mjs (node >= 22.18 native type-stripping).
 * Covers (t260910-14 退役收窄后):
 *   client epics-model.ts pure functions (the popover edit bar — 建票弹层通用写集
 *   编辑栏，独立于已退役的建议预填流存活):
 *      writeSetTextToLines (one entry per line / blank lines tolerated / stripped);
 *      invalidWriteSetLines (illegal lines flagged red, legal ones absent).
 *   （退役注记：原 A 段 host epic-next.ts 纯函数、B 段 host/client 同构断言、
 *    C 段 suggest job 泄漏回归随 suggest_next 整链退役删除。）
 *
 * Python-side counterpart: engine/selfcheck_write_lifecycle.py (write-set validation/refresh/
 * mechanical review).
 */
import { invalidWriteSetLines, writeSetTextToLines } from '../src/client/epics-model.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fail++; console.error(`  ✗ ${label}`) }
}

console.log('client epics-model.ts 弹层编辑栏纯函数')
ok(JSON.stringify(writeSetTextToLines(' a.py\n\n b.py \n')) === JSON.stringify(['a.py', 'b.py']), '每行一条/空行容忍/strip')
ok(JSON.stringify(writeSetTextToLines('')) === JSON.stringify([]), '空文本 → 空数组')
ok(JSON.stringify(invalidWriteSetLines('a.py\n/bad\n..\\x')) === JSON.stringify(['/bad', '..\\x']), '非法行标红清单')
ok(invalidWriteSetLines('a.py\nb.py').length === 0, '全合法 → 空清单')
ok(JSON.stringify(invalidWriteSetLines('')) === JSON.stringify([]), '空文本 → 空清单')

console.log(`\n结果：${pass} 绿 / ${fail} 红`)
process.exit(fail === 0 ? 0 : 1)
