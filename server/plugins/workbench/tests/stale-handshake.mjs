/**
 * tests/stale-handshake.mjs —— 三元组握手判定矩阵真值表（t260905-07，KI-052 根治）。
 *
 * 直跑：node server/plugins/workbench/tests/stale-handshake.mjs
 * 覆盖 classifyHandshake（src/client/stale-check.ts）矩阵 M1-M7 逐格＋方案 review
 * 非阻塞3 三边角格＋review 附条件1 的「200+error」格＋畸形输入不抛纪律：
 *   M1  200 & stale=true                      → restart（boot≠disk，服务端旧）
 *   M2  405 / 404                             → restart（端点内存无，KI-052 主现场）
 *   M3  200 可解析 & 无 error & 缺 boot 指纹   → restart（同构性破坏）
 *   M4  200 & stale=false & injected≠disk     → reload（浏览器旧，含跨重启存活页面）
 *   M5  200 & stale=false & injected==disk/缺失 → 不显
 *   M6  500，或 200+error 字段                 → 不显 + error 透传
 *   M7  502/503/504/畸形 JSON                  → 不显
 * 边角格：注入==boot 但 stale=true → M1；注入≠boot 但 stale=false → M4/M5 按 disk；
 * injected 缺失（L2 阶梯）→ M4 自动失效不误报。
 */

import { classifyHandshake } from './../src/client/stale-check.ts'
import { STALE_BANNER_TEXT, STALE_RELOAD_TEXT } from './../src/client/banner-text.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

const body = (o) => JSON.stringify({ ok: true, result: o })
const F_BOOT = 'boot-aaa', F_DISK_OLD = 'disk-old', F_DISK_NEW = 'disk-new', F_INJ = 'inj-xyz'

/* ── M1：200 & stale=true → restart（injected 任意/缺失） ── */
ok(classifyHandshake(null, 200, body({ stale: true, bootFingerprint: F_BOOT, diskFingerprint: F_DISK_NEW })).banner === 'restart',
  'M1: stale=true + injected 缺失 → restart')
ok(classifyHandshake(F_INJ, 200, body({ stale: true, bootFingerprint: F_BOOT, diskFingerprint: F_DISK_NEW })).banner === 'restart',
  'M1: stale=true + injected 在场 → restart（boot 判定先于 injected 比对）')
ok(classifyHandshake(F_BOOT, 200, body({ stale: true, bootFingerprint: F_BOOT, diskFingerprint: F_DISK_NEW })).banner === 'restart',
  'M1 边角: 注入==boot 但 stale=true → 仍 M1 restart（先重启后刷新，顺序正确）')

/* ── M2：405/404 → restart（KI-052 主现场：看守自身内存旧） ── */
ok(classifyHandshake(null, 405, '').banner === 'restart', 'M2: 405 → restart（端点内存无）')
ok(classifyHandshake(null, 404, '').banner === 'restart', 'M2: 404 → restart')
ok(classifyHandshake(F_INJ, 405, '任何 body 都不影响').banner === 'restart', 'M2: 405 + injected 在场 → restart')

/* ── M3：200 可解析 & 无 error & 缺 boot 指纹 → restart ── */
ok(classifyHandshake(null, 200, body({ stale: false, diskFingerprint: F_DISK_NEW })).banner === 'restart',
  'M3: 可解析应答缺 bootFingerprint → restart（同构性破坏）')
ok(classifyHandshake(null, 200, body({ stale: false, bootFingerprint: 42, diskFingerprint: F_DISK_NEW })).banner === 'restart',
  'M3: bootFingerprint 类型错（非字符串） → restart')
ok(classifyHandshake(null, 200, body({ bootFingerprint: '', diskFingerprint: F_DISK_NEW })).banner === 'restart',
  'M3: bootFingerprint 空串 → restart；stale 缺失（null）同样落本格')

/* ── M4：200 & stale=false & injected≠disk → reload（浏览器旧，跨重启存活页面） ── */
ok(classifyHandshake(F_INJ, 200, body({ stale: false, bootFingerprint: F_DISK_NEW, diskFingerprint: F_DISK_NEW })).banner === 'reload',
  'M4: 服务端一致 + injected≠disk → reload（重启无效，消除动作=刷新）')
ok(classifyHandshake('disk-new', 200, body({ stale: false, bootFingerprint: F_DISK_NEW, diskFingerprint: F_DISK_NEW })).banner === null,
  'M5: injected==disk → 不显（一致态）')
ok(classifyHandshake(F_BOOT, 200, body({ stale: false, bootFingerprint: F_DISK_NEW, diskFingerprint: F_DISK_NEW })).banner === 'reload',
  'M4 边角: 注入≠boot 但 stale=false（boot==disk） → reload（gen2 打回①误报格的修法格）')

/* ── M4/M5 的降级阶梯：injected 缺失 → 仅服务端判定，不误报 ── */
ok(classifyHandshake(null, 200, body({ stale: false, bootFingerprint: F_DISK_NEW, diskFingerprint: F_DISK_NEW })).banner === null,
  'M5: injected 缺失（L2 阶梯/注入失败）→ 不显（M4 自动失效）')

/* ── M4 退化：disk 缺失（无比对基准）→ 不猜测不显 ── */
ok(classifyHandshake(F_INJ, 200, body({ stale: false, bootFingerprint: F_DISK_NEW })).banner === null,
  'M5 变体: 应答缺 diskFingerprint → injected 无基准，不显')

/* ── M6：500 / 200+error → 不显 + error 透传 ── */
ok(classifyHandshake(null, 500, '{"ok":false,"error":"boom"}').banner === null, 'M6: 500 → 不显')
{
  const v = classifyHandshake(F_INJ, 200, body({ stale: false, error: '插件指纹计算失败：部署形态异常', missing: ['x'] }))
  ok(v.banner === null && v.error === '插件指纹计算失败：部署形态异常',
    'M6 附条件1: 200+error 字段 → 不显 + error 人话透传（部署异常≠陈旧，重启对它无效）')
}

/* ── M7：502/503/504/畸形 JSON → 不显 ── */
ok(classifyHandshake(F_INJ, 502, '').banner === null, 'M7: 502 → 不显（反代半开宁漏勿假警）')
ok(classifyHandshake(F_INJ, 503, '').banner === null, 'M7: 503 → 不显')
ok(classifyHandshake(F_INJ, 504, '').banner === null, 'M7: 504 → 不显')
ok(classifyHandshake(F_INJ, 200, 'not json at all').banner === null, 'M7: 畸形 JSON → 不显（畸形≠陈旧）')
ok(classifyHandshake(F_INJ, 200, 'null').banner === null, 'M7: 非对象 body → 不显')
ok(classifyHandshake(F_INJ, 200, '{"ok":true}').banner === null, 'M7: 缺 result 壳 → 不显')

/* ── 畸形输入不抛（消费外部应答=不可信输入纪律） ── */
for (const [desc, fn] of [
  ['injected 非字符串', () => classifyHandshake(42, 200, body({ stale: false, bootFingerprint: 'a', diskFingerprint: 'a' }))],
  ['status 非数值', () => classifyHandshake(null, NaN, '')],
  ['body 全空', () => classifyHandshake(null, 200, '')],
]) {
  let threw = false
  try { fn() } catch { threw = true }
  ok(!threw, `畸形输入不抛: ${desc}`)
}

/* ── 锚常量与矩阵键一致（KI-051：文案锚单一事实，场景 import 断言不走字面量） ── */
ok(STALE_BANNER_TEXT === '有更新，重启控制台生效' && STALE_RELOAD_TEXT === '有更新，刷新页面生效',
  '锚常量: 两支文案在册（restart=重启 / reload=刷新，与消除动作一一对应）')

console.log(`\nSUMMARY pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
