// Integration test for ticket t260901-03 — capture seed gate red lines & fault surface.
//
// Intent (black-box, user perspective):
//   The capture evidence tool may create sessions and SEND A SEED MESSAGE only inside an
//   isolated lane console and only with an explicit flag; against any other console it
//   must refuse loudly without performing a single write. These are the red lines that
//   keep the evidence chain honest. All cases run against a hermetic MOCK console
//   (localhost ephemeral port, no Docker, no real console) and assert both the process
//   outcome and the mock's request log (writes that never happened must be provable):
//     R1 no flag -> loud nonzero exit whose error names the missing gate, and the mock
//        records ZERO POST /global-session/open (no write was attempted anywhere);
//     R2 flag + seed API returns empty cwd -> fast explicit failure naming the cwd
//        check (blank self-heal can never trigger), NOT a 25s hero-timeout hang;
//     R3 flag + seed API errors -> loud failure naming the in-lane seeding
//        failure (台内造数失败) together with the API error;
//     R4 console unreachable -> loud nonzero exit within budget (no silent hang).
//
// Environment: none required from the caller. playwright-core resolves from the main
// checkout via `git rev-parse --git-common-dir` (same precedent as ticket-validate).
// ENV_FAIL (exit 2) when playwright/browser is unavailable (three-state
// contract §7.3: a missing environment never exits 0).
// Everything else must PASS on
// a correct implementation; the R2 cwd assertion lands with this ticket's fix, so this
// suite is expected to FAIL on pre-fix code (that is the acceptance bar).

import { spawn } from "node:child_process";
import { execFileSync } from "node:child_process";
import http from "node:http";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const LANE_ROOT = process.cwd();
const CAPTURE = path.join(LANE_ROOT, "server", "ui-check", "capture.mjs");
const CASE_TIMEOUT_MS = 150000;
// Campaign 3c (260909): raised from 120s because the four legs now run
// concurrently — 4-way browser contention can stretch a leg's launch/fetch
// phases, and the budget must stay comfortably above the slowest healthy leg
// (~85s idle) while still killing genuine hangs.

const results = [];
function record(name, status, detail = "") {
  results.push({ name, status, detail });
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ""}`);
}

// ---------- prechecks ----------

const nodeMajor = Number(process.versions.node.split(".")[0]);
if (nodeMajor < 22) {
  console.log(`ENV_FAIL: node ${process.versions.node} < 22（本套件要求 node >= 22）`);
  console.log("SUMMARY pass=0 fail=0 env_fail=1 na=0");
  process.exit(2);
}

function resolveMainUiCheck() {
  const env = process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK;
  if (env && existsSync(path.join(env, "node_modules", "playwright-core", "index.mjs"))) return env;
  try {
    const common = execFileSync("git", ["rev-parse", "--git-common-dir"], { cwd: LANE_ROOT, encoding: "utf8" }).trim();
    const cand = path.resolve(LANE_ROOT, common, "..", "server", "ui-check");
    if (existsSync(path.join(cand, "node_modules", "playwright-core", "index.mjs"))) return cand;
  } catch { /* not a git checkout — fall through */ }
  const local = path.join(LANE_ROOT, "server", "ui-check");
  if (existsSync(path.join(local, "node_modules", "playwright-core", "index.mjs"))) return local;
  return null;
}

async function loadPlaywright(mainUiCheck) {
  const candidates = [];
  if (process.env.SANDBAR_PLAYWRIGHT_PATH) candidates.push(process.env.SANDBAR_PLAYWRIGHT_PATH);
  if (mainUiCheck) candidates.push(path.join(mainUiCheck, "node_modules", "playwright-core", "index.mjs"));
  candidates.push("playwright-core");
  for (const c of candidates) {
    try { return await import(c); } catch { /* try next */ }
  }
  return null;
}

const mainUiCheck = resolveMainUiCheck();
const playwright = await loadPlaywright(mainUiCheck);

async function browserAvailable() {
  if (!playwright) return false;
  let browser = null;
  try { browser = await playwright.chromium.launch({ channel: "chrome", headless: true }); }
  catch { try { browser = await playwright.chromium.launch({ headless: true }); } catch { return false; } }
  await browser.close().catch(() => {});
  return true;
}

// ---------- mock console ----------

/** Mock console: answers only the three endpoints capture seeding touches, 404 for the rest. Logs every request. */
function startMockConsole(mode) {
  const requests = []; // { method, url }
  let openCalls = 0;
  const server = http.createServer((req, res) => {
    requests.push({ method: req.method, url: req.url });
    const json = (code, body) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.url === "/sandbar-workbench/api/wf/projects") {
      json(200, { ok: true, result: { projects: [{ key: "demo", name: "demo", dirs: ["/tmp/mock-demo"], primary: "/tmp/mock-demo" }] } });
    } else if (req.url === "/sandbar-workbench/api/global-session/open") {
      openCalls += 1;
      if (mode === "error") json(500, { ok: false, error: "mock: 造数端点故障" });
      else if (mode === "emptycwd") json(200, { ok: true, result: { session_id: `chat-mock-${openCalls}`, created: true, cwd: "" } });
      else json(200, { ok: true, result: { session_id: `chat-mock-${openCalls}`, created: true, cwd: "/tmp/mock-demo" } });
    } else if (req.url === "/" || req.url.startsWith("/?")) {
      res.writeHead(200, { "content-type": "text/html" });
      res.end("<!doctype html><html><head><title>mock console</title></head><body></body></html>");
    } else {
      res.writeHead(404); res.end("nope");
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, requests, openCalls: () => openCalls }));
  });
}

// ---------- capture runner ----------

async function runCapture({ url, allowSeed, outDir }) {
  const args = [CAPTURE, "--url", url, "--out", outDir];
  if (allowSeed) args.push("--allow-seed");
  return await new Promise((resolve) => {
    const child = spawn(process.execPath, args, {
      cwd: LANE_ROOT,
      detached: true,
      env: {
        ...process.env,
        // The gate flag travels via argv only; the env flag must be absent in
        // R1, so it is cleared explicitly to avoid environment pollution.
        SANDBAR_UI_CAPTURE_ALLOW_SEED: allowSeed ? "1" : "",
        SANDBAR_PLAYWRIGHT_MODULE: mainUiCheck ? path.join(mainUiCheck, "node_modules", "playwright-core") : process.env.SANDBAR_PLAYWRIGHT_MODULE || "",
      },
    });
    let stdout = "", stderr = "";
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stderr += d; });
    let timedOut = false;
    const t0 = Date.now();
    const timer = setTimeout(() => {
      timedOut = true;
      try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
    }, CASE_TIMEOUT_MS);
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code: timedOut ? "timeout" : code, stdout, stderr, both: `${stdout}\n${stderr}`, elapsedMs: Date.now() - t0, timedOut });
    });
  });
}

async function closedPort() {
  const net = await import("node:net");
  return await new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

// ---------- scenarios ----------

if (!(await browserAvailable())) {
  for (const name of ["R1 no-flag-no-write-redline", "R2 empty-cwd-fast-fail", "R3 seed-api-error-loud",
    "R4 console-unreachable-loud"]) {
    record(name, "env_fail", "playwright-core 不可解析或无可用浏览器");
  }
} else {
  const work = await mkdtemp(path.join(tmpdir(), "capture-redline-"));

  // Campaign 3c (260909): the four legs are self-contained (own mock on an
  // ephemeral port, own capture child, own outDir under work/), so they run
  // concurrently — wall = the slowest leg (~85s) instead of the sum (~240s).
  // record() order becomes completion order (cosmetic; no guard consumes it).

  const legR1 = async () => {
    // R1 read-only red line: no gate flag → an explicit error and zero writes
    // anywhere (proven by the mock's request log)
    const mock = await startMockConsole("ok");
    try {
      const r = await runCapture({ url: `http://127.0.0.1:${mock.port}/`, allowSeed: false, outDir: path.join(work, "r1") });
      const writes = mock.requests.filter((q) => q.method === "POST" && q.url.includes("global-session/open")).length;
      const namedGate = /未带 --allow-seed/.test(r.both);
      const ok = !r.timedOut && r.code !== 0 && namedGate && writes === 0;
      record("R1 no-flag-no-write-redline", ok ? "pass" : "fail",
        `exit=${r.code}；报错点名缺门旗=${namedGate}；造数写请求=${writes}（必须为 0）`);
    } finally { mock.server.close(); }
  };

  const legR2 = async () => {
    // R2 malformed input, empty cwd: gate flag present and the seeding endpoint
    // returns an empty cwd → fast explicit failure (not a 25s hang)
    const mock = await startMockConsole("emptycwd");
    try {
      const r = await runCapture({ url: `http://127.0.0.1:${mock.port}/`, allowSeed: true, outDir: path.join(work, "r2") });
      const namesCwd = /cwd/.test(r.both);
      // Fast-fail budget is 120s (revised by t260907-05 arbitrate gen4: the
      // original 60s was an idle-machine estimate, and on a shared box under
      // resource contention a genuinely-logical explicit failure measured
      // 77.8s and was misjudged — the budget is anchored on "clearly below
      // the 120s hang fallback while keeping non-hang distinguishable"; the
      // four logical assertions (exit≠0 / names cwd / seeding request / no
      // timeout) are unchanged. Campaign 3c revised it 90s→120s: the legs
      // now run 4-way concurrent, and contention stretches launch/fetch —
      // the budget stays "clearly below CASE_TIMEOUT_MS" under load).
      const fast = r.elapsedMs < 120000;
      const ok = !r.timedOut && r.code !== 0 && namesCwd && fast && mock.openCalls() >= 1;
      record("R2 empty-cwd-fast-fail", ok ? "pass" : "fail",
        `exit=${r.code}；报错含 cwd 检查=${namesCwd}；耗时=${(r.elapsedMs / 1000).toFixed(1)}s（须 <120s 快速失败、非 150s 挂死形态）；造数请求=${mock.openCalls()}`);
    } finally { mock.server.close(); }
  };

  const legR3 = async () => {
    // R3 fault injection, seeding endpoint 500: the error must name
    // 「台内造数失败」 and carry the API error back
    const mock = await startMockConsole("error");
    try {
      const r = await runCapture({ url: `http://127.0.0.1:${mock.port}/`, allowSeed: true, outDir: path.join(work, "r3") });
      const named = /台内造数失败/.test(r.both);
      const ok = !r.timedOut && r.code !== 0 && named;
      record("R3 seed-api-error-loud", ok ? "pass" : "fail",
        `exit=${r.code}；报错点名台内造数失败=${named}`);
    } finally { mock.server.close(); }
  };

  const legR4 = async () => {
    // R4 fault injection, console unreachable: a loud nonzero exit within
    // budget, never a silent hang
    const port = await closedPort();
    const r = await runCapture({ url: `http://127.0.0.1:${port}/`, allowSeed: false, outDir: path.join(work, "r4") });
    const ok = !r.timedOut && r.code !== 0 && r.both.trim().length > 0;
    record("R4 console-unreachable-loud", ok ? "pass" : "fail",
      `exit=${r.code}；耗时=${(r.elapsedMs / 1000).toFixed(1)}s（预算 ${CASE_TIMEOUT_MS / 1000}s）；stderr 非空=${r.both.trim().length > 0}`);
  };

  // R2 gets a head start: its fast-fail budget is the contention-sensitive
  // one, so it begins before the other three browsers spin up.
  const r2First = legR2();
  await Promise.all([r2First, legR1(), legR3(), legR4()]);

  await rm(work, { recursive: true, force: true }).catch(() => {});
}

const pass = results.filter((r) => r.status === "pass").length;
const fail = results.filter((r) => r.status === "fail").length;
const envFail = results.filter((r) => r.status === "env_fail").length;
const na = results.filter((r) => r.status === "na").length;
console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail} na=${na}`);
const allNa = na > 0 && pass + fail + envFail === 0;
process.exit(fail > 0 || allNa ? 1 : envFail > 0 ? 2 : 0);
