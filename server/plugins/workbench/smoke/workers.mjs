/**
 * smoke/workers.mjs — host half-smoke for /sandbar-workbench/api/wf/workers (one worker per
 * ticket roster).
 *
 * Run: node smoke/workers.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers (node.ts apply + mock webServer/req/res, temporary repo layout):
 *   A. data directory missing → 200 + empty roster (no throw).
 *   B. pidfile parsing: worker.pid = shared pool (queue=suyou-poc, ticket=null);
 *      worker-<tid>.pid = ticket worker (queue=suyou-ticket-<tid>); non-pid files are ignored.
 *   C. online decision: the current process pid → online; a pid that cannot be alive →
 *      offline; count_alive tallies correctly.
 *   D. log_mtime: the matching worker-<tid>.log exists → second-resolution timestamp;
 *      missing → null (no throw).
 */

import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../node.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** mock webServer: collects registered routes, returns the /wf/workers handler. */
function routeOf(repo) {
  const routes = []
  const ws = { register: (x) => { routes.push(x); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  return routes.find(x => x.kind === 'exact' && x.path === '/sandbar-workbench/api/wf/workers')
}
function mockRes() {
  return {
    status: 0, body: null,
    writeHead(s) { this.status = s },
    end(b) { this.body = b ? JSON.parse(b) : null },
  }
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-workers-'))
try {
  /* ------------------------------------------------------------ A. data directory missing */
  section('A data 目录不存在 → 空清单降级')
  {
    const route = routeOf(join(tmp, 'repo-nodata'))
    ok(route !== undefined, 'workers exact 路由已挂')
    const res = mockRes()
    await route.handler({ url: '/sandbar-workbench/api/wf/workers', method: 'GET' }, res)
    ok(res.status === 200 && res.body.ok === true, 'GET 200')
    ok(res.body.result.count === 0 && res.body.result.count_alive === 0
      && Array.isArray(res.body.result.workers), '空清单（count/count_alive=0，不抛错）')
  }

  /* ---------------------------------------------------- B/C/D. pidfile parsing + online check + log time */
  section('B/C/D pidfile 解析 · 在线判定 · log_mtime')
  {
    const repo = join(tmp, 'repo')
    const dataDir = join(repo, 'server', 'engine', 'data')
    await mkdir(dataDir, { recursive: true })
    await writeFile(join(dataDir, 'worker.pid'), `${process.pid}\n`, 'utf8')          // shared pool; the current process = online
    await writeFile(join(dataDir, 'worker-t-smoke01.pid'), '99999999\n', 'utf8')     // ticket worker; a pid that cannot be alive = offline
    await writeFile(join(dataDir, 'worker-t-smoke01.log'), 'log line\n', 'utf8')     // log exists → log_mtime non-null
    await writeFile(join(dataDir, 'other.txt'), 'x', 'utf8')                          // not a pid file; not picked up

    const route = routeOf(repo)
    const res = mockRes()
    await route.handler({ url: '/sandbar-workbench/api/wf/workers', method: 'GET' }, res)
    ok(res.status === 200 && res.body.ok === true, 'GET 200')
    const r = res.body.result
    ok(r.count === 2, '只收 worker*.pid（other.txt 不入）')
    ok(r.count_alive === 1, 'count_alive 只数在线（当前进程在、假 pid 不在）')

    const shared = r.workers.find(w => w.queue === 'suyou-poc')
    ok(shared !== undefined && shared.ticket === null, 'worker.pid → 共享池（ticket=null）')
    ok(shared.pid === process.pid && shared.online === true, '当前进程 pid → 在线')
    ok(shared.log_mtime === null, '共享池无 worker.log → log_mtime=null（不抛错）')

    const tw = r.workers.find(w => w.ticket === 't-smoke01')
    ok(tw !== undefined && tw.queue === 'suyou-ticket-t-smoke01', 'worker-<tid>.pid → 工单队列名')
    ok(tw.online === false, '不可能存活的 pid → 离线')
    ok(typeof tw.log_mtime === 'number' && tw.log_mtime > 0, '日志存在 → 秒级 log_mtime')
  }
} finally {
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
