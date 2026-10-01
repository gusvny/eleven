/**
 * integration/t260903-04/sc_t04_client_bundle_sync.mjs
 * —— 工单台 shipped bundle 与 src/client 源码同步守卫（t260903-04 arbitrate 新增）。
 *
 * 用户场景（t260903-04 arbitrate 实锤，t260901-22 同族事故复发）：工单台浏览器半
 * 加载的是仓内产物 lib/client.js（tsdown 构建，node.ts §5/§9）；改了 src/client/
 * 忘跑 `bash build-client.sh` 重建时（t260910-15 起为唯一构建入口），源码层测试（tsc/单测/
 * 数据级场景）全绿、真台面却仍是旧行为——KI-024 修复在真台面静默未交付。
 * lane-parallel-dom 的 S1（真渲染）在无浏览器环境恒环境红退 2（该场景 261001 已删）、S0 anchors 断言旧 bundle
 * 也有，均分不出 bundle 陈旧；本场景常驻守「用户实际被服务的产物含当前契约特征」。
 *
 * 断言：
 *   S1 双产物互相同步（client.js ≡ client.cjs，tsdown onSuccess 复制语义）。
 *   S2 契约特征在产物内在案：
 *      - 'parallel_stages'（KI-024① 真源消费字段，运行时属性访问，minify 不擦除）；
 *      - 'deriveStageStates' / 'wb-d2-par'（既有并行渲染 sanity 锚——若连它都缺
 *        说明产物与源码结构大变，场景先行报红而非误绿）。
 *   后续票改 src/client/ 时按 t260901-22 模式在本场景追加当票特征词，或票内自断言。
 *
 * 直跑：node integration/t260903-04/sc_t04_client_bundle_sync.mjs（node ≥22.18）。
 * 末行 SUMMARY pass=<n> fail=<k> env_fail=<e> na=<w>（三态 §7.3）；fail>0 或全 na→exit 1。
 */

import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const WB = resolve(HERE, '..', '..', 'server', 'plugins', 'workbench')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t} ==`) }

const js = await readFile(resolve(WB, 'lib', 'client.js'), 'utf8')
const cjs = await readFile(resolve(WB, 'lib', 'client.cjs'), 'utf8')
const laneStates = await readFile(resolve(WB, 'src', 'client', 'lane-states.ts'), 'utf8')

section('S1 双产物互相同步')
ok(js === cjs, 'lib/client.js ≡ lib/client.cjs（tsdown onSuccess 复制；不一致=半新半旧）')

section('S2 契约特征：用户被服务的产物含当前源码行为')
{
  // 源码锚（契约字段真在源码里——防「源码也没实现却产物报红」的方向性误诊）
  ok(laneStates.includes('parallel_stages'),
    'sanity：parallel_stages 在 src/client/lane-states.ts 源码在案')
  const count = (js.match(/parallel_stages/g) || []).length
  ok(count > 0,
    `parallel_stages 在 bundle 内在案（actual=${count} 次；0=产物陈旧，改了 src/client 未重建 tsdown——真台面仍是旧行为）`)
  ok(js.includes('deriveStageStates') && js.includes('wb-d2-par'),
    '既有并行渲染 sanity 锚在案（deriveStageStates / wb-d2-par）')
}

section('S3 t260915-09 契约特征：立项单数据通道穿 ?project=（KI-057 client 收口）')
{
  // 源码锚（方向性误诊防线：源码没实现时红在源头点名，而不是只报产物陈旧）。
  const epicsModel = await readFile(resolve(WB, 'src', 'client', 'epics-model.ts'), 'utf8')
  ok(epicsModel.includes('withEpicProject'),
    'sanity：withEpicProject 在 src/client/epics-model.ts 源码在案（实现改名=有意识同步本锚，KI-051 锚语义纪律）')
  // 产物锚：bundle 不压缩、函数名存活（withProject 同族先例实测），穿参 helper 在
  // 用户实际被服务的产物内在案=「改 src 忘重建」的 KI-052 静默穿透在本票面上现形。
  const count = (js.match(/withEpicProject/g) || []).length
  ok(count >= 2,
    `withEpicProject 在 bundle 内在案（actual=${count} 次；0=产物陈旧，epics 真台面仍是裸调串台旧行为）`)
}

console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail > 0 ? 1 : 0)
