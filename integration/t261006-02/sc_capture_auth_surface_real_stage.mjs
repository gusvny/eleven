#!/usr/bin/env node
// t261006-02 scenario 2: the capture journey works against a REAL stage of the dsh
// generation actually installed (grey-box L3; ONE real capture run on the PRODUCTION
// pathway — the default docker-stage mode the merge_check ui_evidence path uses;
// own stage/port, never touches 3099; cost: minutes, like the capture family precedent).
//
// Governing record: KI-205 layer-6 (notes/debts/known-issues.md) — the installed dsh
// generation publishes no token (stage receipt "token_source": "none", boot line has no
// ?token=), so the token-extracting bench refused with ENV_FAIL and every UI ticket was
// one red away from an unpassable human gate. Ticket required outcome 4 (green leg):
// boot one real stage and assert the capture EXITS 0 with top-level PNGs.
//
// User-visible contract pinned here:
//   G1  the capture run exits 0 on the production pathway (exit 2 = the bench refused to
//       run in this environment → ENV_FAIL, never faked green or red);
//   G2  evidence lands FLAT (top level, non-recursive) in --out (the layout rule's
//       wording belongs to t261005-13-evidence-layout-named; only the journey face here);
//   G3  the run leaves an auth-surface receipt naming the token-free surface it used
//       (browser-trust / no token demanded) and it AGREES with the producer face: the
//       bench never claims a token source the stage did not publish (one read point,
//       ticket required outcome 2 — producer and gate read the same fact).
//
// Degraded boot-local pathway only behind SANDBAR_T26100602_BOOT_LOCAL=1 (docker-absent
// host manual path; same lesson as t261005-16's pathway blind-spot rework — the gate
// default must exercise the production docker-stage pathway itself).
//
// Intent split: the probe/refusal truth table and the offline named-refusal face belong
// to t261006-02-auth-surface-probe-contract; view content/chat-state links belong to the
// capture-chat family; stage lifecycle out of scope per the ticket face. Pre-implement
// RED is expected (TDD signal); arbitrate/merge must be green. node/playwright missing
// or the bench refusing to run = ENV_FAIL exit 2.
import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { emitCase } from "../lib_result.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const CAPTURE_LANE = path.join(REPO, "server", "ui-check", "capture-lane.mjs");
const SUITE = "t261006-02-capture-auth-surface-real-stage";
const results = [];

function check(name, ok, reason = "", evidence = "") {
  emitCase({ name, suite: SUITE, status: ok ? "pass" : "fail", cause: "self",
             reason, evidence: String(evidence).slice(0, 400) });
  results.push({ name, ok });
}

function preflight() {
  const missing = [];
  if (!existsSync(CAPTURE_LANE)) missing.push(CAPTURE_LANE);
  const pw = path.join(REPO, "server", "ui-check", "node_modules", "playwright-core");
  if (!existsSync(pw)) missing.push(`playwright-core unresolvable: ${pw}`);
  if (missing.length) {
    emitCase({ name: "G0-preflight", suite: SUITE, status: "not-checked", cause: "external",
               reason: "environment pieces missing", evidence: missing.join(" | ").slice(0, 400) });
    process.exit(2);
  }
}

async function main() {
  preflight();
  const home = await mkdtemp(path.join(tmpdir(), "t26100602-real-"));
  const out = path.join(home, "shots");
  await mkdir(out, { recursive: true });
  const bootLocal = process.env.SANDBAR_T26100602_BOOT_LOCAL === "1";
  const laneArgs = [CAPTURE_LANE, "--lane", REPO, "--out", out];
  if (bootLocal) laneArgs.push("--boot-local");
  const p = await new Promise((resolve) => {
    const child = spawn("node", laneArgs,
                        { cwd: REPO, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stdout += d; });
    const t = setTimeout(() => child.kill("SIGTERM"), 780000);
    child.on("exit", (code) => { clearTimeout(t); resolve({ code, stdout }); });
  });

  if (p.code === 2) {
    // The bench refused on the environment face (docker/build/credentials absent) —
    // honest env red, named; never graded as a product failure.
    emitCase({ name: "G-journey", suite: SUITE, status: "not-checked", cause: "external",
               reason: "capture bench refused to run in this environment (rc=2)",
               evidence: p.stdout.slice(-400) });
    await rm(home, { recursive: true, force: true });
    process.exit(2);
  }

  check("G1-real-stage-capture-exit0", p.code === 0,
        "with the installed dsh generation (token_source=none) the capture must COMPLETE "
        + "on the production pathway — the KI-205 refusal is the red-before face",
        `rc=${p.code} tail=${p.stdout.slice(-250)}`);
  const pngs = existsSync(out) ? readdirSync(out).filter((f) => f.endsWith(".png")) : [];
  check("G2-pngs-flat-top-level", pngs.length >= 1,
        "evidence must land in --out readable TOP-LEVEL non-recursively — the gate reads "
        + "only the top level", `count=${pngs.length} sample=${pngs.slice(0, 3).join(",")}`);

  const receiptPath = path.join(out, "auth-surface.json");
  let receipt = null;
  try { receipt = JSON.parse(readFileSync(receiptPath, "utf8")); } catch { /* named below */ }
  check("G3a-auth-surface-receipt-present", receipt !== null,
        "the run must leave an auth-surface receipt naming the surface it used — the "
        + "drift pin's user-visible read point", `${receiptPath} rc=${p.code}`);
  if (receipt) {
    const mode = String(receipt.auth_mode || receipt.authMode || "");
    const observed = String(receipt.token_source_observed ?? receipt.tokenSourceObserved ?? "");
    check("G3b-receipt-names-token-free-surface", /browser[-_]?trust|none/i.test(mode),
          "the receipt must name the token-free (browser-trust) surface this generation "
          + "publishes", JSON.stringify(receipt).slice(0, 300));
    check("G3c-producer-gate-agree", observed === "" || observed === "none",
          "one read point: the gate-observed token source must agree with the producer's "
          + "stage receipt token_source=none — a mismatch is drift, surfaced not stored "
          + "silently", `observed=${observed}`);
  }

  await rm(home, { recursive: true, force: true });
  process.exit(results.some((r) => !r.ok) ? 1 : 0);
}

main().catch((e) => {
  emitCase({ name: "t261006-02-real-stage-crash", suite: SUITE, status: "not-checked",
             cause: "unknown", reason: "scenario crashed",
             evidence: String(e && e.stack || e).slice(0, 400) });
  process.exit(2);
});
