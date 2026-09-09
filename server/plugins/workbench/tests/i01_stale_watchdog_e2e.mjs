/**
 * i01_stale_watchdog_e2e.mjs —— 票 t260902-03 host 陈旧看守，端到端（密封）。
 *
 * 用户故事：host 半代码落盘（merge）后，运行中的 console 进程仍在执行旧代码
 * （「一日三咬」）。看守必须在运行时检出：/sandbar-workbench/api/build-info
 * 端点比对 host 源文件（node.ts + src/host/*.ts）的 boot 时刻指纹与当前磁盘
 * 内容，报 stale=true，让每个视图都能挂「重启控制台」横幅。
 *
 * 步骤（全密封：mock webServer 上的进程内 handler、fixture 仓在临时目录、
 * 零真实端口、零 3099 接触）：
 *   T1 新 boot                → 200，result.stale=false，bootFingerprint === diskFingerprint。
 *   T2 只碰 mtime             → 仍 stale=false（内容哈希，不看 mtime——checkout 触
 *                               碰不得误报）。
 *   T3 内容变更               → result.stale=true，diskFingerprint !== bootFingerprint
 *                               （模拟 host 半 merge 落盘）。
 *   T4 boot 哈希已钉          → 同进程第二次 apply() 不得重置 boot 指纹；T3 之后
 *                               stale 保持 true。
 *   T5 文件全缺               → 200 {stale:false, error:<人话>}——无法判定=不挂横幅。
 *   T6 并发轮询               → 5 个并行请求，全 200，判定/指纹一致。
 *
 * 本基线钉死的契约（实现必须遵守，仓内信封风格）：
 *   - webServer 上注册 exact 路由 GET /sandbar-workbench/api/build-info。
 *   - 200 信封：{ ok: true, result: { stale: boolean, bootFingerprint?: string,
 *                diskFingerprint: string, missing: string[], error?: string } }。
 *
 * 退出契约（integration/README.md）：stdout 末行 `SUMMARY pass=N skip=M fail=K`；
 * fail>0 时 exit 1。实现落地前本基线按设计为红（验收线）。
 */

let passed = 0
let failed = 0
let skipped = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const [maj, min] = process.versions.node.split('.').map(Number)
if (maj < 22 || (maj === 22 && min < 18)) {
  console.log(`SKIP: node ${process.versions.node} < 22.18 (no native type-stripping for .ts imports)`)
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

const { mkdtemp, mkdir, rm, writeFile, utimes } = await import('node:fs/promises')
const { tmpdir } = await import('node:os')
const { join } = await import('node:path')

let apply
try {
  ;({ apply } = await import('./../node.ts'))
} catch (err) {
  console.log(`FAIL: cannot import server/plugins/workbench/node.ts: ${String(err && err.message ? err.message : err)}`)
  console.log('SUMMARY pass=0 skip=0 fail=1')
  process.exit(1)
}

const PATH = '/sandbar-workbench/api/build-info'

/** 捕获 mock webServer 上注册的路由（agent-live.mjs 同款形状）。 */
function makeCtx() {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  return { ctx, routes }
}

function mockRes() {
  return {
    status: 0, body: null, raw: null,
    writeHead(s) { this.status = s },
    end(b) { this.raw = b; this.body = b ? JSON.parse(b) : null },
  }
}
const mockReq = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })

async function call(route, url, method = 'GET') {
  const res = mockRes()
  await route.handler(mockReq(url, method), res)
  return res
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-stale-it01-'))
try {
  /* fixture 仓：看守清单恒含 server/plugins/workbench/node.ts（手写的
   * HOST_SOURCE_FILES）；fixture 里缺的被看守文件名在 boot 与轮询时都进
   * missing[]，下方判定才有意义。T2/T3 因此改 node.ts——唯一保证被看守的文件。 */
  const repo = join(tmp, 'repo')
  const wb = join(repo, 'server', 'plugins', 'workbench')
  await mkdir(join(wb, 'src', 'host'), { recursive: true })
  await writeFile(join(wb, 'node.ts'), 'export const BOOT = 1\n', 'utf8')
  await writeFile(join(wb, 'src', 'host', 'a.ts'), 'export const A = 1\n', 'utf8')
  await writeFile(join(wb, 'src', 'host', 'b.ts'), 'export const B = 1\n', 'utf8')
  await mkdir(join(repo, 'notes', 'epics'), { recursive: true })

  const { ctx, routes } = makeCtx()
  apply(ctx, { repo })
  const route = routes.find(r => r.kind === 'exact' && r.path === PATH)
  section('T1 fresh boot')
  if (route === undefined) {
    ok(false, `${PATH} exact route registered (found: ${routes.map(r => r.path).join(', ') || 'none'})`)
  } else {
    const r = await call(route, PATH)
    const res = r.body?.result
    ok(r.status === 200 && r.body?.ok === true, `GET ${PATH} -> 200 ok:true (got ${r.status})`)
    ok(res && res.stale === false, 'result.stale=false on fresh boot')
    ok(typeof res?.bootFingerprint === 'string' && res.bootFingerprint.length > 0, 'bootFingerprint non-empty string')
    ok(res?.bootFingerprint === res?.diskFingerprint, 'bootFingerprint === diskFingerprint')
    ok(Array.isArray(res?.missing), 'result.missing is an array')

    section('T2 mtime-only touch (checkout touch must not false-positive)')
    const now = new Date()
    await utimes(join(wb, 'node.ts'), now, now)
    const r2 = await call(route, PATH)
    ok(r2.status === 200 && r2.body?.result?.stale === false, 'stale stays false after mtime-only touch on a watched file (content hash, not mtime)')

    section('T3 content change lands on disk (host-half merge)')
    await writeFile(join(wb, 'node.ts'), 'export const BOOT = 2\n', 'utf8')
    const r3 = await call(route, PATH)
    const res3 = r3.body?.result
    ok(r3.status === 200 && res3?.stale === true, 'stale=true after host file content change')
    ok(res3?.diskFingerprint !== res3?.bootFingerprint, 'diskFingerprint !== bootFingerprint')
    ok(res3?.bootFingerprint === res?.bootFingerprint, 'bootFingerprint unchanged vs T1')

    section('T4 second apply() must not reset the boot fingerprint')
    const second = makeCtx()
    apply(second.ctx, { repo })
    const route2 = second.routes.find(r => r.kind === 'exact' && r.path === PATH)
    if (route2 === undefined) {
      ok(false, 'route re-registered on second apply')
    } else {
      const r4 = await call(route2, PATH)
      ok(r4.status === 200 && r4.body?.result?.stale === true, 'stale stays true after second apply (boot hash pinned)')
      ok(r4.body?.result?.bootFingerprint === res?.bootFingerprint, 'bootFingerprint identical to first boot')
    }

    section('T6 concurrent polls agree')
    const results = await Promise.all(Array.from({ length: 5 }, () => call(route, PATH)))
    ok(results.every(x => x.status === 200), '5 parallel polls all 200')
    ok(results.every(x => x.body?.result?.stale === true), '5 parallel polls all stale=true')
    ok(new Set(results.map(x => x.body?.result?.diskFingerprint)).size === 1, '5 parallel polls identical diskFingerprint')

    section('T0 method guard (read-only watchdog)')
    const r0 = await call(route, PATH, 'POST')
    ok(r0.status === 405, `POST -> 405 (got ${r0.status})`)
  }

  section('T5 all watched files missing -> cannot judge, no false alarm')
  const repoEmpty = join(tmp, 'repo-empty')
  await mkdir(join(repoEmpty, 'notes', 'epics'), { recursive: true })
  const third = makeCtx()
  apply(third.ctx, { repo: repoEmpty })
  const route3 = third.routes.find(r => r.kind === 'exact' && r.path === PATH)
  if (route3 === undefined) {
    ok(false, 'route registered for empty repo')
  } else {
    const r5 = await call(route3, PATH)
    const res5 = r5.body?.result
    ok(r5.status === 200, `all-missing repo -> 200 (got ${r5.status})`)
    ok(res5?.stale === false, 'stale=false when fingerprint cannot be computed')
    ok(typeof res5?.error === 'string' && res5.error.length > 0, 'human-readable error present')
  }
} finally {
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
