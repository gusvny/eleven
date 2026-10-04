/**
 * lib_wake_fixture.mjs — shared fixtures for t261004-29 wake scenarios (non-sc_
 * prefix = shared code, not registered in SCENARIOS, L5 exempt).
 *
 * Grey-box seam notes: everything here binds to *public* faces only —
 *   - `createApi` (panel API, deps-injected ledger/wakeCaller),
 *   - `Watchdog` (public constructor deps + status()/tickOnce()/requestWake()),
 *   - the watchdog plugin `apply(ctx, config)` webServer `register` mount contract.
 * No private names, no internal ordering assumptions. If a contract-faithful
 * implementation moves code around, these fixtures must keep working.
 */
import { mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

/** Isolated temp dir under /tmp (same base as watchdog tests/lib.mjs; /var/folders
 *  reads have shown sandbox flakiness), with guaranteed reclaim. */
export function freshDir(prefix) {
  return mkdtempSync(join(tmpdir().startsWith('/tmp') ? tmpdir() : '/tmp', prefix))
}
export function reclaimDir(dir) {
  try { rmSync(dir, { recursive: true, force: true }) } catch { /* best effort */ }
}

/** Result collector: pass/fail/env_fail/na, SUMMARY line + exit code contract
 *  (0 = all pass; 1 = any FAIL or all N/A; 2 = any ENV_FAIL). Same semantics as
 *  integration/t260922-02/lib_results.mjs; local copy so this ticket dir is
 *  self-contained for `--only` runs. */
export function makeResults() {
  const results = []
  const OK = new Set(['pass', 'fail', 'env_fail', 'na'])
  return {
    record(name, status, detail = '') {
      if (!OK.has(status)) throw new Error(`illegal status ${status} (vocab pass/fail/env_fail/na)`)
      results.push({ name, status, detail })
      console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
    },
    check(cond, name, detail = '') {
      this.record(name, cond ? 'pass' : 'fail', cond ? '' : detail)
      return !!cond
    },
    summarize() {
      const p = results.filter(r => r.status === 'pass').length
      const e = results.filter(r => r.status === 'env_fail').length
      const n = results.filter(r => r.status === 'na').length
      const f = results.filter(r => r.status === 'fail').length
      const allNa = results.length > 0 && n === results.length
      console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
      process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
    },
  }
}

/** Import a repo TypeScript module with node type stripping; an unsupported-node
 *  environment is ENV_FAIL (exit 2 face), any other import error is FAIL-named. */
export async function importTs(r, relPath) {
  try {
    return { mod: await import(relPath) }
  } catch (e) {
    const msg = String((e && e.message) || e)
    if (/ERR_UNKNOWN_FILE_EXTENSION|ERR_UNSUPPORTED_TYPESCRIPT|TYPESCRIPT_SYNTAX|ERR_MODULE_NOT_FOUND.*\.ts/.test(msg) && /type|strip|extension/i.test(msg)) {
      r.record(`env-ts-import-${relPath.split('/').pop()}`, 'env_fail', `node cannot run .ts directly (needs >=22.18 type stripping): ${msg.slice(0, 160)}`)
    } else {
      r.record(`import-${relPath.split('/').pop()}`, 'fail', `import failed: ${msg.slice(0, 300)}`)
    }
    return { mod: null }
  }
}

/** Fake ServerResponse capturing status + JSON body (Node shape, no socket). */
export function fakeRes() {
  const res = {
    statusCode: 0,
    headers: null,
    body: undefined,
    ended: false,
    writeHead(status, headers) { res.statusCode = status; res.headers = headers ?? null; return res },
    end(data) { res.ended = true; if (data !== undefined) { try { res.body = JSON.parse(String(data)) } catch { res.body = String(data) } } },
  }
  return res
}

/** Fake IncomingMessage: method/url/headers + one body chunk via async iteration
 *  (the same minimal shape the plugin readBody helpers consume). */
export function fakeReq({ method = 'POST', url = '/', body = '', headers = {} } = {}) {
  const chunks = body === '' ? [] : [Buffer.from(String(body))]
  const listeners = { data: [], end: [], error: [] }
  const req = {
    method, url, headers,
    destroyed: false,
    on(event, cb) { if (listeners[event]) listeners[event].push(cb); return req },
    destroy() { req.destroyed = true },
  }
  // Emit asynchronously (a real socket delivers after the handler attaches).
  queueMicrotask(() => {
    for (const c of chunks) for (const cb of listeners.data) cb(c)
    for (const cb of listeners.end) cb()
  })
  return req
}

/** Minimal cordis-like ctx stub for watchdog apply(): effect/dispose collection,
 *  logger, internal/service listener fan-out, optional pre-existing services. */
export function fakeCtx({ services = {} } = {}) {
  const disposers = []
  const serviceListeners = []
  const logs = []
  const ctx = {
    effect(fn) { const d = fn(); if (typeof d === 'function') disposers.push(d); return d },
    on(event, cb) { if (event === 'internal/service') serviceListeners.push(cb) },
    get(name) { return services[name] },
    logger: { info: (...a) => logs.push(['info', ...a]), warn: (...a) => logs.push(['warn', ...a]) },
  }
  return {
    ctx, disposers, logs,
    /** Deliver a late-mounting host service (webServer arrives after apply). */
    deliverService(name, value) { for (const cb of serviceListeners) cb(name, value) },
    disposeAll() { for (const d of disposers) d() },
  }
}

/** webServer stub capturing route registrations; handlers can be invoked directly. */
export function fakeWebServer() {
  const routes = []
  return {
    routes,
    register(o) { routes.push(o); return () => { const i = routes.indexOf(o); if (i >= 0) routes.splice(i, 1) } },
    find(path) { return routes.find(r => r.path === path) },
  }
}
