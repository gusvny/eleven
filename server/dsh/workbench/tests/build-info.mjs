/**
 * tests/build-info.mjs —— 插件陈旧看守自测（t260902-03 立；t260905-07 KI-052 随方案演进）。
 *
 * 直跑：node server/dsh/workbench/tests/build-info.mjs
 * （node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. computeHostFingerprint / collectSourceFiles（src/host/build-info.ts）：
 *      同输入同 hash；文件内容变→hash 变；单文件缺失→missing 不抛；全缺失→error 不抛；
 *      t260905-07：动态扫描收编新增文件（漏列修复钉住）；vendor/ 与 *.d.ts 不入清单。
 *   B. /suyou-workbench/api/build-info 路由（node.ts apply + mock webServer）：
 *      fresh→stale:false；磁盘文件变→stale:true；同进程二次 apply 不重置 boot 指纹（R3）；
 *      带 error 响应→stale:false+error（R4）；非 GET→405；畸形查询串无害。
 *      t260905-07 同构断言：boot 与 disk 同清单同函数——同输入下两侧 hash 必相等。
 *   C. classifyBuildInfoResponse（src/client/stale-check.ts 纯函数，不 import react）：
 *      JSON 解析失败 / 5xx / 缺 stale 字段 / stale 非布尔 / 带 error → 均 {stale:false} 不抛（R5）。
 * 全程用 tmp fixture root，不真改仓库 host 文件、不碰 3099、不重启任何 console。
 */

import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { collectSourceFiles, computeHostFingerprint } from './../src/host/build-info.ts'
import { classifyBuildInfoResponse } from './../src/client/stale-check.ts'
import { apply } from './../node.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/** fixture 的固定文件面（映射真实扫描面：入口 + host 半 + client 半）。 */
const FIXTURE_FILES = [
  'server/dsh/workbench/node.ts',
  'server/dsh/workbench/src/host/a.ts',
  'server/dsh/workbench/src/host/b.ts',
  'server/dsh/workbench/src/client/a.tsx',
]

/** 在 fixture root 下落固定文件面（全部同内容即可，指纹按内容聚合）。 */
async function layFixture(root, content, drop) {
  for (const rel of FIXTURE_FILES) {
    if (drop !== undefined && rel === drop) continue
    const p = join(root, rel)
    await mkdir(join(p, '..'), { recursive: true })
    await writeFile(p, content)
  }
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-build-info-'))
try {
  // ── A. 纯函数 ────────────────────────────────────────────────
  {
    await layFixture(tmp, 'v1')
    const list = collectSourceFiles(tmp)
    ok(list.length === FIXTURE_FILES.length && list[0] === FIXTURE_FILES[0],
      'A: 动态扫描=入口首位+全部落盘来源（排序固化）')

    const a = await computeHostFingerprint(tmp)
    const b = await computeHostFingerprint(tmp)
    ok(a.hash !== undefined && a.hash === b.hash, 'A: 同输入同 hash（稳定）')
    ok(a.files === FIXTURE_FILES.length && a.missing.length === 0, 'A: 全文件参与、无 missing')

    await layFixture(tmp, 'v2')
    const c = await computeHostFingerprint(tmp)
    ok(c.hash !== a.hash, 'A: 文件内容变 → hash 变（陈旧可判）')

    // t260905-07 漏列修复钉住：新增来源文件落盘 → 自动入清单（hash 变、files+1）
    await writeFile(join(tmp, 'server/dsh/workbench/src/host/c-new.ts'), 'new')
    const d2 = await computeHostFingerprint(tmp)
    ok(d2.hash !== undefined && d2.files === FIXTURE_FILES.length + 1 && d2.hash !== c.hash,
      'A: 新增文件自动入清单（动态扫描，漏列故障不再复发）')

    // 排除面：vendor/ 与 *.d.ts 不入清单
    await mkdir(join(tmp, 'server/dsh/workbench/src/client/vendor'), { recursive: true })
    await writeFile(join(tmp, 'server/dsh/workbench/src/client/vendor/x.ts'), 'v')
    await writeFile(join(tmp, 'server/dsh/workbench/node-shims.d.ts'), 'd')
    const d3 = await computeHostFingerprint(tmp)
    ok(d3.files === FIXTURE_FILES.length + 1 && d3.hash === d2.hash,
      'A: vendor/ 与 *.d.ts 不参与指纹（排除面钉住）')

    // 单文件缺失（语义随动态扫描更新，t260905-07）：盘上没有的文件不进清单
    // （missing 恒空——清单即盘上实况），「清单项读不到」改用同名目录占位复现
    // （EISDIR）：missing 记录、不抛错、其余文件仍聚合。
    const repoMissing = join(tmp, 'repo-a-missing')
    await layFixture(repoMissing, 'v2')
    await rm(join(repoMissing, 'server/dsh/workbench/src/host/a.ts'))
    await mkdir(join(repoMissing, 'server/dsh/workbench/src/host/a.ts'))
    const d = await computeHostFingerprint(repoMissing)
    ok(d.hash !== undefined && d.missing.length === 1 && d.missing[0].endsWith('a.ts'),
      'A: 清单项不可读 → missing 记录、不抛错、其余文件仍聚合')

    const empty = await mkdtemp(join(tmpdir(), 'wb-build-info-empty-'))
    const e = await computeHostFingerprint(empty)
    ok(e.error !== undefined && e.hash === undefined && e.files === 0, 'A: 全缺失 → error 人话、不抛')
    await rm(empty, { recursive: true, force: true })
  }

  // ── B. 路由（mock webServer） ────────────────────────────────
  {
    const repo = join(tmp, 'repo-b')
    await layFixture(repo, 'boot')
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo })
    const route = routes.find(r => r.kind === 'exact' && r.path === '/suyou-workbench/api/build-info')
    ok(route !== undefined, 'B: build-info exact 路由已挂')

    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })
    const call = async (url, method = 'GET') => {
      const res = mockRes()
      await route.handler(mockReq(url, method), res)
      return res
    }

    // 等 boot 指纹固化（apply 内 fire-and-forget）
    let fresh = null
    for (let i = 0; i < 50; i++) {
      fresh = await call('/suyou-workbench/api/build-info')
      if (fresh.body?.result?.bootFingerprint !== undefined) break
      await new Promise(r => setTimeout(r, 20))
    }
    ok(fresh.status === 200 && fresh.body.result.stale === false, 'B: 磁盘=boot → stale:false')
    ok(typeof fresh.body.result.diskFingerprint === 'string' && fresh.body.result.missing.length === 0,
      'B: 响应带 diskFingerprint 与 missing')
    // t260905-07 同构断言：boot 与 disk 同清单同函数，fresh 态两侧必相等
    ok(fresh.body.result.bootFingerprint === fresh.body.result.diskFingerprint,
      'B: 同构性——boot==disk（fresh），两侧同清单同函数')

    // 磁盘文件变（模拟合并落账）→ stale:true
    await layFixture(repo, 'landed')
    const stale = await call('/suyou-workbench/api/build-info')
    ok(stale.status === 200 && stale.body.result.stale === true, 'B: 磁盘变 → stale:true（一日三咬可提醒）')

    // R3：同进程二次 apply（宿主重放）不重置 boot 指纹
    apply(ctx, { repo })
    const afterReplay = await call('/suyou-workbench/api/build-info')
    ok(afterReplay.body.result.stale === true && afterReplay.body.result.bootFingerprint === fresh.body.result.bootFingerprint,
      'B: 二次 apply 不重置 boot 指纹（stale 仍真）')

    // 恢复磁盘=boot → stale 回假（看守双向，不误报）
    await layFixture(repo, 'boot')
    const back = await call('/suyou-workbench/api/build-info')
    ok(back.body.result.stale === false, 'B: 磁盘还原 → stale:false（不误报）')

    // R4：全缺失 → stale:false + error
    const repoEmpty = join(tmp, 'repo-empty')
    await mkdir(join(repoEmpty, 'server/dsh/workbench/src/host'), { recursive: true })
    const routes2 = []
    const ws2 = { register: (r) => { routes2.push(r); return () => {} } }
    apply({ effect: (fn) => { fn() }, logger: { info() {}, warn() {} }, get: (k) => (k === 'webServer' ? ws2 : undefined), on: () => () => {} }, { repo: repoEmpty })
    const route2 = routes2.find(r => r.kind === 'exact' && r.path === '/suyou-workbench/api/build-info')
    const res2 = mockRes()
    await route2.handler(mockReq('/suyou-workbench/api/build-info'), res2)
    ok(res2.status === 200 && res2.body.result.stale === false && typeof res2.body.result.error === 'string',
      'B: 指纹全缺 → stale:false + error（无法判定=不误报）')

    // 非 GET → 405；畸形查询串无害
    const r405 = await call('/suyou-workbench/api/build-info', 'POST')
    ok(r405.status === 405, 'B: POST → 405（只读看守）')
    const rQuery = await call('/suyou-workbench/api/build-info?%broken&&x=1')
    ok(rQuery.status === 200, 'B: 畸形查询串无害（200）')
  }

  // ── C. 客户端分类纯函数（R5 五态） ──────────────────────────
  {
    ok(classifyBuildInfoResponse(200, '{"ok":true,"result":{"stale":true}}').stale === true,
      'C: stale:true → 显横幅')
    ok(classifyBuildInfoResponse(200, '{"ok":true,"result":{"stale":false}}').stale === false,
      'C: stale:false → 不显')
    ok(classifyBuildInfoResponse(500, '{"ok":false}').stale === false, 'C: 5xx → 不显')
    ok(classifyBuildInfoResponse(200, 'not json').stale === false, 'C: JSON 解析失败 → 不显')
    ok(classifyBuildInfoResponse(200, '{"ok":true,"result":{}}').stale === false, 'C: 缺 stale 字段 → 不显')
    ok(classifyBuildInfoResponse(200, '{"ok":true,"result":{"stale":"yes"}}').stale === false,
      'C: stale 非布尔 → 不显（严格 === true）')
    ok(classifyBuildInfoResponse(200, '{"ok":true,"result":{"stale":true,"error":"x"}}').stale === false,
      'C: 带 error 字段 → 不显（部署形态异常≠陈旧）')
    ok(classifyBuildInfoResponse(200, 'null').stale === false, 'C: 非对象 body → 不显')
  }

  console.log(`\n${passed} passed, ${failed} failed`)
  process.exit(failed === 0 ? 0 : 1)
} finally {
  await rm(tmp, { recursive: true, force: true })
}
