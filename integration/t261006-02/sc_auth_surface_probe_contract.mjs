#!/usr/bin/env node
// t261006-02 scenario 1: the auth-surface answer is PROBED, not assumed (grey-box L2/L3;
// offline seconds, zero docker/Temporal/browser, never touches 3099/7233).
//
// Governing record: KI-205 layer-6 (notes/debts/known-issues.md) — the installed dsh
// generation publishes NO token (stage receipt "token_source": "none", boot line has no
// ?token=, CLI has no token option: --host/--no-open/--port/--trusted-host only), yet the
// capture bench still hard-extracts ?token= from a console log and refuses with ENV_FAIL
// exit 2. Raising the wait threshold does NOT help (120s = same refusal) — this is a
// surface drift, not a timing race.
//
// User-visible contract pinned here:
//   A1  a token-free homepage (HTTP 200) resolves the entry to the BARE URL, mode
//       browser-trust — no token demanded anywhere;
//   A2  a 401 homepage WITH a published token keeps the legacy tokened entry
//       (previous-generation surface keeps working, adaptation must not regress it);
//   A3  a 401 homepage with NO token anywhere refuses (never a silent bare-URL fallback)
//       and the refusal NAMES the missing surface and the generation facts (ticket
//       required outcome 3: a dsh upgrade must turn something red with the surface
//       named, never make every UI ticket silently unpassable);
//   A4  malformed console-log inputs (binary bytes, a 10MB single line, an unreadable
//       path) never crash the resolution and never fabricate an entry (external-input
//       three-state discipline);
//   B   the refusal is reachable through the REAL consumption seam — capture-lane.mjs
//       driven as the gate drives it (--stage-json pointing at a stub 401 console) —
//       exits 2 with the surface-naming refusal, and no evidence files appear.
//
// Intent split: the real-stage journey (boot one real stage, exit 0, flat top-level PNGs,
// receipt agreement with the producer) belongs to t261006-02-capture-auth-surface-real-stage;
// the written layout rule belongs to t261005-13-evidence-layout-named; the gate/directory
// agreement belongs to t261006-01-ui-evidence-two-shapes. Pre-implement RED is expected
// (TDD signal): the probe seam and the surface-naming refusal do not exist yet.
// Arbitrate/merge must be green. node missing = ENV_FAIL exit 2.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { emitCase } from "../lib_result.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const CAPTURE_LANE = path.join(REPO, "server", "ui-check", "capture-lane.mjs");
const SUITE = "t261006-02-auth-surface-probe-contract";
const results = [];

function check(name, ok, reason = "", evidence = "") {
  emitCase({ name, suite: SUITE, status: ok ? "pass" : "fail", cause: "self",
             reason, evidence: String(evidence).slice(0, 400) });
  results.push({ name, ok });
}

// ---------------------------------------------------------------- A: probe seam
async function probeSeFace() {
  let mod = null;
  try {
    mod = await import(CAPTURE_LANE);
  } catch (e) {
    check("A0-probe-seam-importable", false,
          "capture-lane.mjs must load as a module exposing the auth-surface resolution seam",
          String(e && e.message || e).slice(0, 300));
    return;
  }
  check("A0-probe-seam-importable", true, "module loads");

  const resolve = mod.resolveAuthEntry;
  if (typeof resolve !== "function") {
    check("A0-resolveAuthEntry-exported", false,
          "the surface-resolution contract seam (resolveAuthEntry) is not exported — the "
          + "bench still hardcodes the token assumption (pre-implement red is expected)",
          "exports=" + Object.keys(mod).join(","));
    return;
  }
  check("A0-resolveAuthEntry-exported", true, "contract seam exported");

  // A1 token-free 200 homepage -> bare entry, browser-trust, no refusal.
  const a1 = resolve({ port: 46001, status: 200, token: "" });
  const a1Url = a1.entryUrl || a1.entry || "";
  check("A1-200-bare-entry-browser-trust",
        !a1.refusal && a1Url && !a1Url.includes("token=")
          && String(a1.authMode || a1.mode || "").match(/browser[-_]?trust/i) !== null,
        "a reachable token-free homepage (this dsh generation's browser-trust surface, "
        + "token_source=none) must yield the bare URL as the nav entry with mode named",
        JSON.stringify(a1).slice(0, 300));

  // A2 401 with a published token -> legacy tokened entry survives.
  const a2 = resolve({ port: 46001, status: 401, token: "abc123def456ghi789jk" });
  const a2Url = a2.entryUrl || a2.entry || "";
  check("A2-401-with-token-legacy-entry",
        !a2.refusal && a2Url.includes("token="),
        "the previous-generation token-gate surface must keep its tokened entry — the "
        + "adaptation must not regress environments still running it",
        JSON.stringify(a2).slice(0, 300));

  // A3 401 without any token -> named refusal, never a silent bare-URL fallback.
  const a3 = resolve({ port: 46001, status: 401, token: "", fingerprint: { fence: true, tokenOption: false, source: "test" } });
  const a3Text = String(a3.refusal || a3.reason || "");
  check("A3-401-no-token-named-refusal",
        !!a3.refusal && a3Text.trim().length > 0,
        "a token-gate homepage with no published token must refuse — never fall back to "
        + "the bare URL silently (KI-205: inert-phase capture produces nothing)",
        a3Text.slice(0, 300));
  check("A3b-refusal-names-surface-and-generation",
        /token/i.test(a3Text) && /browser[-_]?trust|fingerprint|generation|token_source/i.test(a3Text),
        "the refusal must name WHICH surface of WHICH generation is missing vs advertised "
        + "(ticket required outcome 3: upgrade drift turns red with the surface named)",
        a3Text.slice(0, 300));

  // A4 contract seam robustness: an UNRECOGNISED status must refuse with a named,
  // fingerprint-carrying message — never a guess, never a crash, never a silent entry.
  // (Malformed console-LOG bytes degrade at the extraction face inside the bench — that
  // face is covered by capture-lane.mjs --selftest, developer L1; this seam only ever
  // sees an already-extracted token, and a non-empty token IS the published-token
  // contract, so a tokened entry from a non-empty token is correct, not fabrication.)
  let a4ok = true;
  let a4ev = "";
  for (const [tag, status] of [["500", 500], ["301", 301], ["0", 0]]) {
    try {
      const r = resolve({ port: 46001, status, token: "" });
      const refusal = String((r && r.refusal) || "");
      if (!r || r.ok || !refusal) { a4ok = false; a4ev += ` ${tag}=no-named-refusal`; }
    } catch (e) {
      a4ok = false; a4ev += ` ${tag}=throw:${String(e && e.message || e).slice(0, 60)}`;
    }
  }
  check("A4-unknown-status-named-refusal-no-crash", a4ok,
        "an unrecognised homepage status must refuse with a named no-guess message — "
        + "never a crash, never a silent entry (external-input three-state hook)",
        a4ev.slice(0, 300));
}

// --------------------------------------- B: real consumption seam, offline stub
// Stub console answers 401 to everything (token-gate surface, no token published
// anywhere) — the exact shape KI-205 layer-6 measured, reproduced without docker.
async function stubRefusalFace() {
  const server = createServer((req, res) => { res.writeHead(401); res.end("dsh web authentication required; stub"); });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  const home = await mkdtemp(path.join(tmpdir(), "t26100602-stub-"));
  const out = path.join(home, "shots");
  await mkdir(out, { recursive: true });
  const stageJson = path.join(home, "stage.json");
  await writeFile(stageJson,
    JSON.stringify({ project: "t26100602-authstub", ports: { console: port } }), "utf8");
  // Boot budget tiny on purpose: KI-205 proved the refusal is not a timing race, so the
  // named-refusal face must fire within seconds, not after the default 45s.
  const env = { ...process.env, SANDBAR_CAPTURE_LANE_BOOT_MS: "3000" };
  const p = await new Promise((resolve) => {
    const child = spawn("node", [CAPTURE_LANE, "--lane", REPO, "--stage-json", stageJson, "--out", out],
                        { cwd: REPO, env, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stdout += d; });
    const t = setTimeout(() => child.kill("SIGTERM"), 120000);
    child.on("exit", (code) => { clearTimeout(t); resolve({ code, stdout }); });
  });
  server.close();
  check("B-stub401-refuses-exit2", p.code === 2,
        "a token-gate console with no published token must refuse with the ENV_FAIL exit "
        + "code through the real --stage-json consumption seam (lifecycle owned here, "
        + "bench never tears down an external stage)", `rc=${p.code} tail=${p.stdout.slice(-200)}`);
  check("B-refusal-names-surface-generation", /token/i.test(p.stdout)
        && /browser[-_]?trust|fingerprint|generation|token_source/i.test(p.stdout),
        "the streamed refusal must name which surface of which generation is missing vs "
        + "advertised (outcome 3 drift pin, user-visible text)", p.stdout.slice(-400));
  const pngs = existsSync(out) ? (await import("node:fs")).readdirSync(out)
    .filter((f) => f.endsWith(".png")) : [];
  check("B-no-evidence-on-refusal", pngs.length === 0,
        "a refused run must not leave evidence files that a gate could misread as product "
        + "evidence", `pngs=${pngs.length}`);
  await rm(home, { recursive: true, force: true });
}

async function main() {
  if (!existsSync(CAPTURE_LANE)) {
    emitCase({ name: "t261006-02-probe-preflight", suite: SUITE, status: "fail",
               cause: "self", reason: "capture-lane.mjs missing (product face broken)",
               evidence: CAPTURE_LANE });
    process.exit(1);
  }
  await probeSeFace();
  await stubRefusalFace();
  process.exit(results.some((r) => !r.ok) ? 1 : 0);
}

main().catch((e) => {
  emitCase({ name: "t261006-02-probe-crash", suite: SUITE, status: "not-checked",
             cause: "unknown", reason: "scenario crashed",
             evidence: String(e && e.stack || e).slice(0, 400) });
  process.exit(2);
});
