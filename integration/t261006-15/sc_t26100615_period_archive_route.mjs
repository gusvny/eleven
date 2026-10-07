#!/usr/bin/env node
/**
 * sc_t26100615_period_archive_route.mjs — t261006-15, grey-box L3, "ro" pool.
 *
 * User-perceivable face under test (design source: notes/discussions/
 * 261004-巡检两面重塑-测试面与简化面.md §7–§8, host rulings; dispatch spec P2/P5):
 * the Inspection tab's period browser is served by a real period-archive route,
 * NOT by the latest-scan endpoint. The tab's periods, per-period report and
 * coverage must come from the report archive
 * (out/inspection/inspection-<instance>-<period>.json) with the ruled
 * semantics:
 *   S1 ordering is EXPLICIT newest-first — never a data source's iteration
 *      order (the mock's numeric-object-key bug put the OLDEST period first;
 *      same discipline as t261004-14).
 *   S2 a period with no report is explicit ("not available"), never a silent
 *      blank; CONSECUTIVE report-less periods merge into ONE item (span +
 *      count, per-period causes kept); merge is judged by LIST ADJACENCY over
 *      the declared sorted sequence only — NO date arithmetic (§7 line 129):
 *      non-adjacent report-less periods stay separate items.
 *   S3 a given period's report + coverage is fetchable; coverage separates
 *      reviewed from not-reviewed — "not reviewed" must never read as
 *      "no problem".
 *   S4 malformed report JSON / unreadable archive → named per-period reason,
 *      never a crash, never fabricated data.
 *   S5 an unknown project key is an explicit client error (project-anchor
 *      contract: 400 named, no silent cross-project fallback).
 *
 * Harness: black-box import of workbench/node.ts (type-stripping) + mock ctx
 * (same discipline as t260907-05/sc_workbench_route_renamed_serves.mjs), repo
 * anchored at an isolated temp dir via apply opts (SANDBAR_REPO chain), reports
 * seeded under <tmp>/out/inspection/. Zero docker/Temporal/browser/3099;
 * offline seconds.
 *
 * Intent split: the tab's rendered journey (period switch, banners, empty
 * copies, layout rule) = sc_t26100615_inspection_tab_journey_layout.mjs; the
 * trigger write face + attribution ledger =
 * sc_t26100615_trigger_gate_attribution.mjs; the pure-model unit truth table =
 * developer L1. This entry owns the SERVED route contract (P5): what the tab
 * can actually download. Route/model not landed = FAIL named (TDD-phase red
 * expected; arbitrate/merge must be green). node missing = ENV_FAIL exit 2.
 */
import http from 'node:http'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = join(HERE, '..', '..')
const ROUTE = '/sandbar-workbench/api/wf/inspection-archive'
const INSTANCE = 'integration-tests'

process.on('unhandledRejection', () => {})

let passed = 0, failed = 0, envfail = 0
const C = {
  case(name, ok, reason = '') {
    ok ? passed++ : failed++
    console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
  },
  envFail(name, reason) {
    envfail++
    console.log(`[ENV_FAIL] ${name} — ${reason}`)
  },
  exit() {
    console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail} na=0`)
    process.exit(envfail ? 2 : failed ? 1 : 0)
  },
}

if (typeof fetch !== 'function') { C.envFail('node-fetch', 'node >= 18 required'); C.exit() }

// ---- isolated repo: seeded report archive ----
const iso = mkdtempSync(join(tmpdir(), 't26100615-archive-'))
let cleanups = [() => rmSync(iso, { recursive: true, force: true })]
process.on('exit', () => { for (const f of cleanups) { try { f() } catch {} } })
function seedReport(period, body) {
  const dir = join(iso, 'out', 'inspection')
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, `inspection-${INSTANCE}-${period}.json`),
    typeof body === 'string' ? body : JSON.stringify(body))
}

// minimal plausible report; scenario asserts user-perceivable sentinels,
// not the writer's internal schema (P5 contract, not implementation).
function report(period) {
  return {
    instance: INSTANCE,
    period,
    base_head: 'b'.repeat(40),
    findings: { high: 2, med: 1, low: 0, total: 3 },
    named: [
      { id: `find-${period}-1`, severity: 'high', rule: 'dead-code', object: 'server/plugins/watchdog/src/host/config.ts' },
    ],
    coverage: {
      reviewed: ['server/plugins/executor-panel/src/host/api.ts'],
      not_reviewed: ['server/dsh/temporal-poc/base/workflow.ts', 'integration/run_scenarios.py'],
      total_source_files: 1298,
      slice: true,
    },
  }
}

// ---- boot workbench host with repo anchored at the isolated dir ----
async function boot() {
  const routes = []
  const webServer = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    get: (k) => (k === 'webServer' ? webServer : undefined),
    effect: (fn) => { try { fn() } catch { /* tolerate apply-side effects */ } },
    logger: { info: () => {}, warn: () => {}, error: () => {} },
  }
  let nodeApi
  try { nodeApi = await import(join(REPO, 'server/plugins/workbench/node.ts')) } catch (e) {
    C.case('workbench-host-importable', false, String(e?.message ?? e).slice(0, 200)); C.exit()
  }
  nodeApi.apply(ctx, { repo: iso })
  const server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://local').pathname
    const hit = routes.find((r) => r.kind === 'exact' && r.path === pathname)
      ?? routes.find((r) => r.kind === 'prefix' && pathname.startsWith(r.path))
    if (!hit) { res.writeHead(404); res.end(); return }
    Promise.resolve(hit.handler(req, res)).catch(() => {
      try { res.writeHead(500); res.end() } catch { /* head sent */ }
    })
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  cleanups.push(() => server.close())
  return 'http://127.0.0.1:' + server.address().port
}

async function jfetch(base, url) {
  const r = await fetch(base + url)
  const text = await r.text()
  let body = null
  try { body = JSON.parse(text) } catch { /* non-json */ }
  return { status: r.status, body, text }
}

const NO_REPORT_RE = /not available|no report/i

async function main() {
  const base = await boot()

  // ---- S1 explicit newest-first over a deliberately out-of-order archive ----
  // Which periods exist is decided by the report archive (P2 verbatim): a
  // period the archive KNOWS but cannot serve a report for is represented by
  // an unreadable slot (present file, bad content) — a file that was never
  // written is NOT a period, and inventing calendar placeholders here would be
  // exactly the date arithmetic §7 line 129 forbids. Layout: 20261004 report,
  // 20261003 + 20261002 unreadable (consecutive), 20261001 report, 20260928
  // unreadable (lone — separated from the run by 20261001).
  seedReport('20261004', report('20261004'))
  seedReport('20261001', report('20261001'))
  seedReport('20261003', '{oops not json')
  seedReport('20261002', '{also broken')
  seedReport('20260928', '{nope')

  const r0 = await jfetch(base, ROUTE + '?project=')
  // workbench envelope is {ok, result} (scan-report contract family); unwrap
  // the declared envelope, not an accidental top-level shape.
  const payload0 = r0.body && (r0.body.result ?? r0.body)
  const list = payload0 && (payload0.periods ?? payload0.items ?? payload0.list)
  if (r0.status === 404 || !list) {
    C.case('archive-route-serves-period-list', false,
      `status=${r0.status} body=${r0.text.slice(0, 200)} — period-archive route not landed (P5)`)
    return C.exit()
  }
  C.case('archive-route-serves-period-list', Array.isArray(list), 'type=' + typeof list)

  const ids = list.map((p) => String(p.period ?? p.id ?? p.key ?? ''))
  const withReport = ids.filter((id) => {
    const it = list.find((x) => String(x.period ?? x.id ?? x.key ?? '') === id)
    const blob = JSON.stringify(it)
    return /report|available|merged/i.test(blob) ? !NO_REPORT_RE.test(String(it.status ?? it.state ?? it.label ?? '')) || /has|ok|ready/i.test(String(it.status ?? '')) : false
  })
  // S1: the two report-bearing periods appear newest-first among themselves.
  const pos = (p) => ids.indexOf(p)
  C.case('S1-ordering-newest-first-declared',
    pos('20261004') < pos('20261001') && pos('20261001') >= 0,
    `ids=${ids.join(',')}`)

  // S2a: the lone report-less period (20260928) is an explicit own item.
  const items = payload0.items ?? list
  const lone = items.find((x) => String(x.period ?? x.label ?? '').includes('20260928'))
  C.case('S2a-single-missing-period-explicit', !!lone,
    lone ? '' : '20260928 absent from served items: ' + JSON.stringify(items).slice(0, 240))
  if (lone) {
    const blob = JSON.stringify(lone)
    C.case('S2a-not-available-wording', NO_REPORT_RE.test(blob),
      'item=' + blob.slice(0, 200))
  }

  // S2b: consecutive report-less 20261003+20261002 merge into ONE item.
  const merged = items.filter((x) => {
    const p = String(x.period ?? x.label ?? '')
    return p.includes('20261003') || p.includes('20261002')
  })
  C.case('S2b-consecutive-missing-merge-into-one', merged.length === 1,
    `items touching 03/02 = ${merged.length}: ${merged.map((x) => JSON.stringify(x).slice(0, 120)).join(' | ')}`)
  if (merged.length === 1) {
    const blob = JSON.stringify(merged[0])
    C.case('S2b-merge-carries-span-and-count',
      blob.includes('20261003') && blob.includes('20261002'),
      'span=' + blob.slice(0, 200))
    // adjacency discipline: the merged item must NOT swallow 20260928
    // (non-adjacent — 20261001 with a report separates them).
    C.case('S2b-no-date-arithmetic-no-far-merge',
      !String(merged[0].period ?? merged[0].id ?? '').includes('20260928'),
      'merged=' + String(merged[0].period ?? merged[0].id ?? ''))
  }

  // ---- S3: one period's report + coverage fetchable; not-reviewed explicit ----
  const r1 = await jfetch(base, ROUTE + '?project=&instance=integration-tests&period=20261004')
  C.case('S3-period-report-fetchable', r1.status === 200 && !!r1.body,
    `status=${r1.status}`)
  const blob1 = JSON.stringify(r1.body ?? {})
  C.case('S3-report-content-served',
    blob1.includes('dead-code') && blob1.includes('20261004'),
    'body=' + blob1.slice(0, 200))
  const p1 = r1.body && (r1.body.result ?? r1.body)
  const cov = p1 && (p1.coverage ?? (p1.report && p1.report.coverage))
  const covBlob = JSON.stringify(cov ?? {})
  C.case('S3-coverage-separates-not-reviewed',
    covBlob.includes('temporal-poc/base/workflow.ts'),
    'coverage=' + covBlob.slice(0, 240))
  C.case('S3-not-reviewed-never-reads-clean',
    !/\bno problem\b/i.test(covBlob) && !/\ball clear\b/i.test(covBlob),
    '')

  // ---- S4: malformed report JSON → named reason, no crash, no fabrication ----
  seedReport('20260926', '{oops not json')
  const r2 = await jfetch(base, ROUTE + '?project=&instance=integration-tests&period=20260926')
  const b2 = JSON.stringify(r2.body ?? {})
  C.case('S4-malformed-report-named-reason',
    r2.status < 500 && /reason|error|not available|no report|malformed|parse/i.test(b2),
    `status=${r2.status} body=${b2.slice(0, 200)}`)
  C.case('S4-no-crash-no-fabrication', !b2.includes('SyntaxError'), '')

  // ---- S5: unknown project → explicit client error, no silent fallback ----
  const r3 = await jfetch(base, ROUTE + '?project=definitely-not-a-project')
  C.case('S5-unknown-project-explicit-error', r3.status >= 400 && r3.status < 500,
    `status=${r3.status} body=${JSON.stringify(r3.body ?? {}).slice(0, 160)}`)

  C.exit()
}

main().catch((e) => { C.case('scenario-run', false, String(e?.stack ?? e).slice(0, 300)); C.exit() })
