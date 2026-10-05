// ticket-detail-overlay —— t261005-04 L3 system scenario: ticket detail opens as a
// single-layer overlay in the MIDDLE column (epic console-ui item UI-3).
//
// Intent (grey-box L3, user-perceivable; anchored to the epic contract, not to
// implementation): clicking a ticket row opens the ticket detail as an overlay that
// covers the middle column while the left column and the platform chat column stay
// alive; the overlay carries the ticket face, the Spec block and the lane diagram;
// the overlay is ALWAYS one layer deep — drilling to the epic replaces the content
// and a breadcrumb walks back, never a stack; Esc closes back to the underlying view.
// The plan-detail data face ticket has NOT landed, so the deferred fields (structured
// red lines, branch dimensions, queue position) must be absent-by-name, never stubbed
// with fabricated values (ticket scope: "no silent placeholder").
//
// Sub-cases (all page-level, user-perceivable; malformed-input discipline per grey-box
// rules — every detail payload consumed is a fixture we control, including broken ones):
//   T1 open-as-overlay: row click → exactly ONE detail overlay node; the underlying
//      row card stays attached (middle-column overlay, not a page navigation); the
//      overlay shows the ticket face (title/stage), the Spec block (spec text,
//      acceptance checklist, write-set chips, verbatim body).
//   T2 lane diagram: with a chain topology present, diagram nodes render.
//   T3 partial/malformed detail: a ticket whose detail lacks spec/body and carries
//      topology=null still opens (no crash, single node), renders only what exists,
//      and never fabricates a queue position ("Queue" state without a number).
//   T4 single-layer drill: ticket -> epic drill stays ONE overlay node and swaps
//      content (no crumb — the crumb is the epic->ticket walk-back); from the epic,
//      its linked ticket opens WITH the `← <code>` breadcrumb; the breadcrumb walks
//      back to the epic; Esc closes and the underlying view survives.
//   T5 keyboard: Esc closes the overlay; ArrowDown/ArrowUp walk the current project's
//      ticket list inside the same single overlay.
//   T6 served-asset freshness (KI-052/KI-168 family): the client asset actually served
//      by the test console carries the same overlay marker coverage as the repo bundle
//      — mis-supplied tree is an ENV red, not a silent product red.
//   T7 hygiene: zero console.error / pageerror across the whole run.
//
// Intent split (anti-duplication, checked against the registry): t260905-05-modal-
// dialog-semantics owns wb-modal dialog a11y semantics (different face); t260901-22
// approve-modal-ui owns approval-modal presence; no registered entry owns the ticket
// detail overlay's single-layer/breadcrumb/keyboard contract. Pre-implement red is
// the expected TDD signal; arbitrate/merge must be green.
//
// Stage: shared isolated test console (lib_browser/lib_stage_console supply, never
// the production 3099 console) + per-page API stubs for the ticket faces (zero real
// writes). Three-state contract: SUMMARY line + exit 0/1/2; ENV Fail only for stage /
// browser / playwright absence.

import {
  BASE,
  refuseProductionConsole,
  consoleHealthy,
  loadPlaywright,
  openTestPage,
  makeResults,
} from '../t260904-05/lib_browser.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const REPO = process.cwd();
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js');
const SERVED_CLIENT = '/plugins/sandbar-workbench/client.js';
// alnum-only fixture ids; never real tickets
const FA = 'it04a';
const FB = 'it04b';

const results = makeResults();

/** playwright-core resolution with worktree fallback (shared fixture step, same
 *  shape as sc_modal_dialog_semantics): lane ui-check symlink may be absent in a
 *  worktree; resolve the main checkout through the gitfile. null = ENV_FAIL. */
async function loadPlaywrightRobust() {
  const pw = await loadPlaywright();
  if (pw) return pw;
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim();
    if (!common) return null;
    const main = resolve(REPO, common, '..');
    for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
      'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
      const p = join(main, sub);
      if (existsSync(p)) {
        try { return await import(pathToFileURL(p).href); } catch { /* next */ }
      }
    }
  } catch { /* not a worktree */ }
  return null;
}

// ------------------------------------------------------------- fixtures + API stub

const workflow = {
  id: 'dev-lane', name: 'dev-lane', lane: 'worktree',
  stages: [{ id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] }],
};
const rows = [
  {
    id: FA, role: 'developer', status: 'running', title: 'overlay fixture A',
    workflow: 'dev-lane', stage: 'implement', stage_state: 'running',
    handoff_count: 0, pending_count: 0, worktree: '/tmp/fx-a', updated: '—', updated_ts: 0,
  },
  {
    id: FB, role: 'developer', status: 'settled', title: 'overlay fixture B',
    workflow: 'dev-lane', stage: 'implement', stage_state: 'done',
    handoff_count: 0, pending_count: 0, worktree: '/tmp/fx-b', updated: '—', updated_ts: 0,
  },
];
// A: full face — spec/acceptance/write_set/body/chain topology/epic.
const detailA = {
  id: FA, title: rows[0].title, workflow_id: 'dev-lane', epic: 'console-ui',
  status: 'running', role: 'developer', lane: 'worktree',
  stage: 'implement', stage_state: 'running', stage_name: 'implement',
  spec: 'Open the ticket detail as a middle-column overlay with a Spec block.',
  acceptance: ['overlay opens in the middle column', 'single layer only'],
  write_set: ['server/plugins/workbench/src/client/index.tsx'],
  body: 'overlay fixture A verbatim body',
  red_line: 'Do not touch the right-column chat.',
  topology: {
    version: 'topology-v1', template: 'dev-lane',
    nodes: [{ id: 'implement', label: 'implement', role: 'developer', kind: 'agent', parts: ['agent'] }],
    edges: [], groups: [],
  },
  signatures: [], acceptance_walkthrough: {}, checks: {}, results: {},
  handoffs: [], pending: [], log: [], timeline: [], gens: {},
  updated: '—', updated_ts: 0,
};
// B: partial/malformed face — missing spec/body/red_line, null topology. The overlay
// must degrade honestly (render only what exists, linear fallback, no fabricated data).
const detailB = {
  id: FB, title: rows[1].title, workflow_id: 'dev-lane', epic: '',
  status: 'settled', role: 'developer', lane: 'worktree',
  stage: 'implement', stage_state: 'done', stage_name: 'implement',
  topology: null, acceptance: [], write_set: [], signatures: [],
  checks: {}, results: {}, handoffs: [], pending: [], log: [], timeline: [],
  updated: '—', updated_ts: 0,
};
const details = { [FA]: detailA, [FB]: detailB };

async function attachStub(page) {
  await page.route('**/sandbar-workbench/api/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const body = (b, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) });
    // Segment grammar: list (0 extra segments) / detail (1: <id>) / sub-resource
    // (2: <id>/<sub>). NOTE the inner group MUST carry its own `?`: written as
    // `(?:\/([^/]+)(?:\/([^/]+)))?` the outer `?` makes BOTH segments one all-or-
    // nothing unit, so the single-segment detail URL `/tickets/<id>` never matches
    // (acceptance round-1 blocking finding; re-proven by exec before this fix).
    const m = /^\/sandbar-workbench\/api\/wf\/tickets(?:\/([^/]+)(?:\/([^/]+))?)?$/.exec(url.pathname);
    if (m) {
      const [, id, sub] = m;
      if (!id && req.method() === 'GET') return body({ ok: true, result: { tickets: rows, workflows: [workflow] } });
      if (id && !sub && req.method() === 'GET') {
        const d = details[id];
        return d ? body({ ok: true, result: d }) : body({ ok: false, error: 'fixture stub: unknown ticket' }, 404);
      }
      if (id && sub && req.method() === 'POST') return body({ ok: true, result: details[id] });
      // Sub-resource GETs the overlay fires on open (acceptance round-1 finding 2:
      // these used to fall through to the real server → 404 → browser console
      // errors → T7 red spuriously). Each face answers the empty/fact shape the
      // client renders honestly (no fabricated payload, no silent placeholder).
      if (id && sub && req.method() === 'GET') {
        if (sub === 'evidence') return body({ ok: true, result: { files: [] } });
        // AgentUsageResult with exists=false and no suspect markers = the honest
        // "no token accounting for this fixture ticket" face (renders the plain
        // tokens line, no warning, no fabricated numbers).
        if (sub === 'agent-usage') return body({ ok: true, result: { exists: false, files: 0, total: { input: 0, output: 0, cacheRead: 0 }, byStage: {}, models: [] } });
        if (sub === 'agent-live') return body({ ok: true, result: { exists: false, events: [], truncated: false } });
        if (sub === 'agent-logs') return body({ ok: true, result: { lines: [] } });
        return body({ ok: false, error: `fixture stub: unsupported sub-resource ${sub}` }, 404);
      }
      return body({ ok: false, error: 'fixture stub: unsupported' }, 400);
    }
    // Epic faces (landed contract, epics.tsx): GET /api/epics/<code> -> {ok,result:
    // EpicMeta&{markdown}}; GET /api/epics/<code>/tickets -> {ok,result:{tickets:[
    // {id,title,status,stage,stage_state}]}}. The epic lists fixture ticket B so the
    // drill journey ticket->epic->ticket(back-crumb) is drivable end to end.
    {
      const em = /^\/sandbar-workbench\/api\/epics\/([^/]+)(\/tickets)?$/.exec(url.pathname);
      if (em && req.method() === 'GET') {
        if (em[2] === '/tickets') {
          return body({ ok: true, result: { tickets: [{ id: FB, title: detailB.title, status: 'settled', stage: 'implement', stage_state: 'done' }] } });
        }
        return body({ ok: true, result: { id: 'console-ui', name: 'console-ui', title: 'console-ui', status: 'active', markdown: '# console-ui' } });
      }
    }
    try {
      const resp = await route.fetch();
      await route.fulfill({ response: resp });
    } catch {
      await body({ ok: false, error: 'fixture passthrough failed' }, 502);
    }
  });
}

// ------------------------------------------------------------- shared drivers

// Detail overlay container: public face of "the ticket detail surface". The drawer
// (.wb-drawer) is the pre-ticket surface; the overlay (.wb-overlay) is the UI-3
// surface. Counting both keeps the single-layer assertion meaningful across the
// transition; content assertions bind to user-visible text, not class names.
function overlayNode(page) {
  return page.locator('.wb-overlay, .wb-drawer').first();
}
function overlayCount(page) {
  return page.locator('.wb-overlay, .wb-drawer').count();
}
function rowCard(page, id) {
  return page.locator(`[data-ticket-id="${id}"][data-compact="false"]`);
}

async function openBoard(page) {
  const icon = page.locator('span.wb-view-icon[title="Tickets"]').first();
  for (let i = 0; i < 40; i++) {
    if (await icon.count()) break;
    await page.waitForTimeout(250);
  }
  if (!(await icon.count())) return false;
  await icon.click();
  for (let i = 0; i < 60; i++) {
    if (await rowCard(page, FA).count()) return true;
    await page.waitForTimeout(250);
  }
  return false;
}

async function openDetail(page, id) {
  await rowCard(page, id).first().click({ timeout: 5000 });
  for (let i = 0; i < 32; i++) {
    const n = await overlayCount(page);
    const ov = overlayNode(page);
    if (n === 1 && (await ov.count()) && (await ov.textContent().catch(() => '') || '').includes(details[id].title)) return true;
    await page.waitForTimeout(250);
  }
  return false;
}

async function closeDetail(page) {
  await page.keyboard.press('Escape');
  for (let i = 0; i < 32; i++) {
    if (!(await overlayCount(page))) return true;
    await page.waitForTimeout(250);
  }
  return false;
}

/** every visible check below waits up to ~8s before declaring failure */
async function waitFor(page, probe, ms = 8000) {
  const steps = Math.ceil(ms / 250);
  for (let i = 0; i < steps; i++) {
    if (await probe()) return true;
    await page.waitForTimeout(250);
  }
  return false;
}

// ------------------------------------------------------------- main

async function main() {
  refuseProductionConsole();

  if (!(await consoleHealthy())) {
    results.record('L0 precheck', 'env_fail', `test console unreachable at ${BASE}`);
    return results.summarize();
  }
  const pw = await loadPlaywrightRobust();
  if (!pw) {
    results.record('L0 precheck', 'env_fail', 'playwright-core not resolvable');
    return results.summarize();
  }

  // Served-asset freshness probe (KI-052/KI-168 family): coverage-count alignment of
  // the overlay marker between the repo bundle (truth source) and the asset the test
  // console actually serves. Substring presence is NOT enough — a foreign tree's
  // bundle naturally carries other overlays (fake-agreement precedent, t260905-05).
  function markerCoverage(js) {
    // occurrence count without matchAll iteration overhead concerns
    return js.split('wb-overlay').length - 1;
  }
  let repoMarkers = null;
  try { repoMarkers = markerCoverage(readFileSync(LIB_JS, 'utf8')); } catch { repoMarkers = null; }
  let servedMarkers = null;
  try {
    const r = await fetch(`${BASE}${SERVED_CLIENT}`, { signal: AbortSignal.timeout(8000) });
    if (r.ok) servedMarkers = markerCoverage(await r.text());
  } catch { servedMarkers = null; }
  const repoHasOverlay = repoMarkers !== null && repoMarkers > 0;
  const servedFresh = repoHasOverlay && servedMarkers === repoMarkers;
  const supplyHint = `—— console client asset supply stale / wrong tree (shared stage /repo not the tested worktree, KI-052/KI-168 family); re-run after the stage re-mounts this tree`;

  const consoleErrors = [];
  const opened = await openTestPage(pw, { results, tag: 'L0', consoleErrors });
  if (!opened) return results.summarize();
  const { page } = opened;
  page.on('dialog', (dlg) => { void dlg.accept(); });

  try {
    await attachStub(page);

    if (!(await openBoard(page))) {
      results.record('L0 precheck', 'env_fail', `board did not render fixture rowcard on ${BASE}`);
      return results.summarize();
    }
    results.record('L0 precheck', 'pass', 'rowcards consume the stub list (t260904-17 contract anchor)');

    // T1 open-as-overlay
    if (!(await openDetail(page, FA))) {
      results.record('T1 open-as-overlay', repoHasOverlay ? 'fail' : 'fail',
        `row click did not open a single detail surface showing "${detailA.title}" (pre-implement red is the expected TDD signal)`);
    } else {
      const n = await overlayCount(page);
      const underlying = await rowCard(page, FA).count();
      const txt = (await overlayNode(page).textContent().catch(() => '')) || '';
      // label case is presentation (the console renders stage labels capitalized)
      const faceOK = txt.toLowerCase().includes('implement');
      const specOK = txt.includes(detailA.spec);
      const accOK = txt.includes(detailA.acceptance[0]);
      const wsOK = txt.includes('index.tsx');
      const bodyOK = txt.includes(detailA.body);
      if (n !== 1) {
        results.record('T1 open-as-overlay', 'fail', `expected exactly 1 overlay node, found ${n} (stack = epic rule broken)`);
      } else if (!underlying) {
        results.record('T1 open-as-overlay', 'fail', 'underlying row card left the DOM — detail replaced the view instead of overlaying');
      } else if (!(faceOK && specOK && accOK && wsOK && bodyOK)) {
        // name each failed check precisely (a bare false in the list named nothing)
        const missing = [
          !faceOK && 'ticket-face', !specOK && 'spec', !accOK && 'acceptance',
          !wsOK && 'write-set', !bodyOK && 'verbatim-body',
        ].filter(Boolean);
        // capture the overlay text alongside the failure so the block check is auditable
        const snap = txt.length > 400 ? txt.slice(0, 400) : txt;
        results.record('T1 open-as-overlay', 'fail', `overlay open but missing blocks: ${missing.join(', ')}; overlay text head: ${JSON.stringify(snap)}`);
      } else {
        results.record('T1 open-as-overlay', 'pass', 'single node, underlying list intact, ticket face + spec + acceptance + write-set + verbatim body all present');
      }
      await closeDetail(page);
    }

    // T2 lane diagram renders from topology
    if (!(await openDetail(page, FA))) {
      results.record('T2 lane diagram', 'fail', 'detail did not reopen for the lane-diagram leg');
    } else {
      const diagram = await waitFor(page, async () =>
        (await overlayNode(page).locator('svg, [class*="lane"], [class*="stage"]').count()) > 0);
      results.record('T2 lane diagram', diagram ? 'pass' : 'fail',
        diagram ? 'diagram/stage nodes render inside the overlay from the fixture topology'
          : 'no lane-diagram/stage nodes inside the overlay despite a valid chain topology');
      await closeDetail(page);
    }

    // T3 partial/malformed detail degrades honestly
    if (!(await openDetail(page, FB))) {
      results.record('T3 partial-detail honesty', 'fail', `detail for ${FB} (missing spec/body, topology=null) did not open at all`);
    } else {
      const n = await overlayCount(page);
      const txt = (await overlayNode(page).textContent().catch(() => '')) || '';
      const fabricatedQueue = /\bqueue\s*(position|pos)?\s*[:#]?\s*\d+/i.test(txt);
      const fabricatedSpec = (txt.includes('undefined') || txt.includes('[object Object]'));
      if (n !== 1) {
        results.record('T3 partial-detail honesty', 'fail', `partial detail produced ${n} overlay nodes`);
      } else if (fabricatedQueue) {
        results.record('T3 partial-detail honesty', 'fail', 'a numeric queue position is rendered although the engine exports no queue-position field (fabricated placeholder = ticket scope violation)');
      } else if (fabricatedSpec) {
        results.record('T3 partial-detail honesty', 'fail', 'raw undefined/[object Object] leaked into the overlay for missing keys');
      } else {
        results.record('T3 partial-detail honesty', 'pass', 'partial detail opens as a single node, renders only existing keys, no fabricated queue position');
      }
      await closeDetail(page);
    }

    // T4 single-layer drill — landed contract journey (261004 §7.5.1 + overlay model):
    // ticket -> epic drill produces NO breadcrumb (the crumb is the epic->ticket
    // walk-back); epic content lists tickets; clicking one swaps to its detail WITH
    // the `← <code>` breadcrumb; the breadcrumb walks back to the epic; Esc closes.
    if (!(await openDetail(page, FA))) {
      results.record('T4 single-layer drill', 'fail', 'detail did not reopen for the drill leg');
    } else {
      // the drill control is the epic chip (span.wb-epic-chip, title "click to open
      // the epic") — it is intentionally NOT a button/a, so probe it as itself
      const epicControl = overlayNode(page).locator('button, a, [role="button"], [data-testid], .wb-epic-chip')
        .filter({ hasText: 'console-ui' }).first();
      const drillable = await waitFor(page, async () => (await epicControl.count()) > 0);
      if (!drillable) {
        results.record('T4 single-layer drill', 'fail', 'no epic drill control found inside the overlay (breadcrumb/drill face missing)');
      } else {
        await epicControl.click({ timeout: 5000 });
        const epicFace = overlayNode(page).locator('[data-testid="overlay-epic"]').first();
        const epicShown = await waitFor(page, async () => (await epicFace.count()) > 0);
        if ((await overlayCount(page)) > 1) {
          results.record('T4 single-layer drill', 'fail', `drill produced ${await overlayCount(page)} stacked overlays — the single-layer invariant is broken`);
        } else if (!epicShown) {
          results.record('T4 single-layer drill', 'fail', 'epic chip click did not swap the overlay content to the epic detail (same layer)');
        } else {
          // from the epic, click fixture ticket B -> its detail WITH a back crumb
          const epRow = epicFace.locator('.wb-ep-ticket').filter({ hasText: FB }).first();
          const rowThere = await waitFor(page, async () => (await epRow.count()) > 0);
          if (!rowThere) {
            results.record('T4 single-layer drill', 'fail', 'epic detail does not list its linked ticket (drill-back journey undrivable)');
          } else {
            await epRow.click({ timeout: 5000 });
            const crumb = overlayNode(page).locator('[data-testid="overlay-crumb"]').first();
            const crumbThere = await waitFor(page, async () => (await crumb.count()) > 0);
            const ticketBShown = await waitFor(page, async () =>
              ((await overlayNode(page).textContent().catch(() => '')) || '').includes(detailB.title));
            if ((await overlayCount(page)) > 1) {
              results.record('T4 single-layer drill', 'fail', `epic->ticket drill stacked ${await overlayCount(page)} overlays`);
            } else if (!crumbThere || !ticketBShown) {
              results.record('T4 single-layer drill', 'fail', `epic->ticket drill incomplete: content=${ticketBShown ? 'ticket B' : 'NOT swapped'}, crumb=${crumbThere ? 'shown' : 'missing'}`);
            } else {
              await crumb.click({ timeout: 5000 });
              const backToEpic = await waitFor(page, async () => (await epicFace.count()) > 0);
              const closed = await closeDetail(page);
              const underlying = await rowCard(page, FA).count();
              if (!backToEpic) {
                results.record('T4 single-layer drill', 'fail', 'breadcrumb click did not walk back to the epic content');
              } else if (!closed || !underlying) {
                results.record('T4 single-layer drill', 'fail', `Esc close=${closed}, underlying view survives=${!!underlying} — close contract broken`);
              } else {
                results.record('T4 single-layer drill', 'pass', 'ticket->epic->ticket stays one layer, crumb walks back to the epic, Esc closes to the surviving underlying view');
              }
            }
          }
        }
      }
      if (await overlayCount(page)) await closeDetail(page);
    }

    // T5 keyboard: Esc close + arrow navigation across the project's tickets
    if (!(await openDetail(page, FA))) {
      results.record('T5 keyboard navigation', 'fail', 'detail did not reopen for the keyboard leg');
    } else {
      const escClosed = await closeDetail(page);
      let arrowOK = false;
      let arrowNote = '';
      if (escClosed && (await openDetail(page, FA))) {
        await page.keyboard.press('ArrowDown');
        arrowOK = await waitFor(page, async () =>
          ((await overlayNode(page).textContent().catch(() => '')) || '').includes(detailB.title), 5000);
        if (arrowOK) {
          await page.keyboard.press('ArrowUp');
          arrowOK = await waitFor(page, async () =>
            ((await overlayNode(page).textContent().catch(() => '')) || '').includes(detailA.title), 5000);
          arrowNote = 'ArrowDown → ticket B, ArrowUp → ticket A inside the same single overlay';
        } else {
          arrowNote = 'ArrowDown did not move to the next ticket of the current project';
        }
        const stillOne = (await overlayCount(page)) === 1;
        if (!stillOne) { arrowOK = false; arrowNote += '; arrow navigation stacked overlays'; }
      } else {
        arrowNote = `Esc close=${escClosed}; could not reopen for the arrow legs`;
      }
      if (await overlayCount(page)) await closeDetail(page);
      results.record('T5 keyboard navigation', escClosed && arrowOK ? 'pass' : 'fail',
        escClosed && arrowOK ? arrowNote : `Esc-close=${escClosed ? 'ok' : 'broken'}; ${arrowNote}`);
    }

    // T6 served-asset freshness (environment attribution guard)
    if (repoMarkers === null) {
      results.record('T6 served-asset freshness', 'fail', `repo bundle unreadable at ${LIB_JS}`);
    } else if (!repoHasOverlay) {
      results.record('T6 served-asset freshness', 'fail', 'repo bundle carries no overlay marker (wb-overlay) — implement stage not landed or bundle not rebuilt (tsdown rebuild debt = KI-052 family); pre-implement red expected');
    } else if (!servedFresh) {
      results.record('T6 served-asset freshness', 'env_fail',
        `served ${SERVED_CLIENT} overlay-marker count ${servedMarkers === null ? 'unreachable' : servedMarkers} vs repo ${repoMarkers}${supplyHint}`);
    } else {
      results.record('T6 served-asset freshness', 'pass', `served asset matches repo bundle (overlay marker count ${repoMarkers})`);
    }

    // T7 hygiene
    if (consoleErrors.length === 0) {
      results.record('T7 zero console.error/pageerror', 'pass');
    } else {
      results.record('T7 zero console.error/pageerror', 'fail',
        `${consoleErrors.length} entries, first=${String(consoleErrors[0]).slice(0, 160)}`);
    }
  } finally {
    try { await opened.browser.close(); } catch { /* already gone */ }
  }
  results.summarize(); // prints SUMMARY and exits with the three-state code
}

main().catch((e) => {
  console.error(String(e));
  results.record('main', 'fail', String(e).slice(0, 180));
  results.summarize();
});
