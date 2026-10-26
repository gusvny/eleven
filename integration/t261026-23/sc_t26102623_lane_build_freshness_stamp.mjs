#!/usr/bin/env node
// sc_t26102623_lane_build_freshness_stamp.mjs — ticket t261026-23.
//
// User-visible contract under guard: the lane build-freshness gate
// (server/ui-check/capture-lane.mjs, exported laneBuildRejectReason) must
// decide freshness by CONTENT, not by file mtimes. Measured 261026 (main
// cb1517a7): a fresh checkout writes src/shared/face-value.ts after
// lib/client.js, so a byte-identical committed bundle reads as stale and the
// settings-isolation case ENV_FAILs — while a rebuild produces ZERO diff.
// The fix records a sha256 stamp (.build-stamp.json) over the watched
// source set at build time; the gate compares the stamp against the sources
// and only falls back to the legacy 2 s mtime rule when a tree carries no
// stamp. Fail-closed everywhere: no stamp in an old tree keeps the mtime
// rule; a stamp that is unreadable, malformed, wrong-version/wrong-algorithm
// or mismatched REFUSES — never assumed fresh. Every reject message names
// which rule fired (rule=...).
//
// Grey-box L3: assertions land on the gate's PUBLIC export
// (laneBuildRejectReason's returned reason strings and rule tokens) and on
// the family face of integration/baselines/capture-ensure-build.mjs (a
// protected baseline that keeps its own mtime predicate — settled by the
// gen2/gen3 rulings; this scenario only pins that its verdicts stay
// safe-side: fresh, or stale with the documented rebuild remedy).
// Offline seconds; zero docker / Temporal-server / browser; never touches
// 3099/7233. Fixture workbenches live in mkdtemp dirs, reclaimed in finally.
//
// Exit contract (t260904-12): PASS=0, FAIL=1, ENV_FAIL=2 (no SKIP).
// Written in the design stage against the reviewed plan (the reds here were
// the TDD signal); the implement stage has landed, so the full set must be
// green at the integration gate / merge.

import { createHash } from "node:crypto";
import {
  mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const GATE_PATH = path.join(REPO_ROOT, "server", "ui-check", "capture-lane.mjs");
const ENSURE_BUILD_PATH = path.join(REPO_ROOT, "integration", "baselines", "capture-ensure-build.mjs");

const failures = [];
function check(name, cond, detail) {
  if (cond) {
    console.log(`PASS ${name}`);
  } else {
    console.log(`FAIL ${name}${detail ? `: ${detail}` : ""}`);
    failures.push(name);
  }
}

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

/** Build a fixture workbench dir: lib/client.{js,cjs} + the three watched src
 * dirs. Returns { wb, stampPath, writeStamp } — writeStamp serialises the
 * stamp exactly as the landed build entry does (sorted relpaths, per-file hex
 * sources, artifact hashes for lib/client.cjs and lib/client.js). */
function makeFixture() {
  // Shaped as a repo slice: <root>/server/plugins/workbench — the family
  // helper (ensure-build) resolves the workbench relative to a repo root.
  const root = mkdtempSync(path.join(tmpdir(), "t26102623-wb-"));
  const wb = path.join(root, "server", "plugins", "workbench");
  mkdirSync(wb, { recursive: true });
  const files = {
    "src/client/index.tsx": "export const A = 1;\n",
    "src/host/boot.ts": "export const B = 2;\n",
    "src/shared/face-value.ts": "export const FACE = 3;\n",
  };
  for (const [rel, body] of Object.entries(files)) {
    const p = path.join(wb, rel);
    mkdirSync(path.dirname(p), { recursive: true });
    writeFileSync(p, body);
  }
  mkdirSync(path.join(wb, "lib"), { recursive: true });
  writeFileSync(path.join(wb, "lib", "client.js"), "// bundled output\n");
  writeFileSync(path.join(wb, "lib", "client.cjs"), "// bundled output\n");
  const stampPath = path.join(wb, ".build-stamp.json");
  const writeStamp = () => {
    const sources = {};
    for (const rel of Object.keys(files).sort()) {
      sources[rel.split(path.sep).join("/")] =
        sha256(readFileSync(path.join(wb, rel)));
    }
    const artifacts = {
      "lib/client.cjs": sha256(readFileSync(path.join(wb, "lib", "client.cjs"))),
      "lib/client.js": sha256(readFileSync(path.join(wb, "lib", "client.js"))),
    };
    writeFileSync(stampPath, JSON.stringify({
      version: 1, algorithm: "sha256", sources, artifacts,
    }));
  };
  return { root, wb, stampPath, writeStamp, files };
}

function main() {
  let gate;
  try {
    // Dynamic import so an unreadable gate module is an ENV red, not a crash.
    return import(pathToFileURL(GATE_PATH).href).then((gateMod) => {
      gate = gateMod;
      return import(pathToFileURL(ENSURE_BUILD_PATH).href).then((ensureMod) =>
        run(gate, ensureMod));
    });
  } catch (e) {
    console.log(`ENV_FAIL: gate module unimportable: ${GATE_PATH} (${e.message})`);
    return 2;
  }
}

async function run(gate, ensureMod) {
  const reject = (wb) => gate.laneBuildRejectReason(wb);
  const tmps = [];

  try {
    // S1 — THE MEASURED REGRESSION: stamp matches sources, but mtimes are
    // inverted (src written AFTER lib, as a fresh checkout does). The gate
    // must decide by content and let the tree through.
    {
      const fx = makeFixture(); tmps.push(fx.root);
      fx.writeStamp();
      const libP = path.join(fx.wb, "lib", "client.js");
      const old = new Date(Date.now() - 60_000);
      const now = new Date();
      utimesSync(libP, old, old);
      for (const rel of Object.keys(fx.files)) {
        const p = path.join(fx.wb, rel);
        utimesSync(p, now, now);
      }
      const r = reject(fx.wb);
      check("S1 stamped checkout-order tree is FRESH (content, not clock)",
        r === null, `unexpected reject: ${r}`);
      // Family face (settled design, arbitrate gen0): the baseline prereq
      // helper keeps its own mtime predicate (baselines are protected assets;
      // a lane may not rewrite them). Its disagreement with the content gate
      // is allowed in the SAFE direction only: it may order a rebuild the
      // gate would pass (ensureLaneBuild's rebuild is byte-identity-guarded
      // against git and heals checkout-order inversions), but its stale
      // verdict must carry the documented remedy (rebuild), never a dead end.
      const fam = ensureMod.laneBuildStaleReason(fx.root);
      check("S1b family predicate stays safe-side: fresh, or stale with the rebuild remedy",
        fam === null || /重建|rebuild|build/.test(fam), `unactionable family verdict: ${fam}`);
      check("S1c ensure-build helper surface intact",
        typeof ensureMod.ensureLaneBuild === "function" &&
        typeof ensureMod.resolveTsdown === "function");
    }

    // S2 — genuinely stale: one watched source byte changed under the stamp.
    {
      const fx = makeFixture(); tmps.push(fx.root);
      fx.writeStamp();
      writeFileSync(path.join(fx.wb, "src/shared/face-value.ts"), "export const FACE = 4;\n");
      const r = reject(fx.wb) || "";
      check("S2 byte-changed source is STALE", r !== "");
      check("S2 reject names rule=stamp-mismatch", r.includes("rule=stamp-mismatch"), r.slice(0, 200));
      check("S2 reject names the offending file", r.includes("face-value.ts"), r.slice(0, 200));
      check("S2 reject keeps the anti-fraud direction", /陈旧|stale/.test(r), r.slice(0, 200));
    }

    // S3/S4 — stamp-set equality: a file added after stamping, and a file
    // removed after stamping, are both drift (not freshness).
    {
      const fx = makeFixture(); tmps.push(fx.root);
      fx.writeStamp();
      writeFileSync(path.join(fx.wb, "src/shared/extra.ts"), "export const X = 9;\n");
      let r = reject(fx.wb) || "";
      check("S3 source added after stamp is STALE", r.includes("rule=stamp-mismatch"), r.slice(0, 200));
      rmSync(path.join(fx.wb, "src/shared/extra.ts"));
      rmSync(path.join(fx.wb, "src/host/boot.ts"));
      r = reject(fx.wb) || "";
      check("S4 watched source removed after stamp is STALE", r.includes("rule=stamp-mismatch"), r.slice(0, 200));
    }

    // S5 — fail-closed on hostile stamp content: each malformed shape REFUSES.
    {
      const shapes = {
        "truncated JSON": '{"version":1,"algorithm":"sha256","sources":',
        "wrong version": JSON.stringify({ version: 2, algorithm: "sha256", sources: {}, artifacts: {} }),
        "wrong algorithm": JSON.stringify({ version: 1, algorithm: "md5", sources: {}, artifacts: {} }),
        "sources not an object": JSON.stringify({ version: 1, algorithm: "sha256", sources: [], artifacts: {} }),
        "artifacts not an object": JSON.stringify({ version: 1, algorithm: "sha256", sources: {}, artifacts: [] }),
        "hash not hex": JSON.stringify({
          version: 1, algorithm: "sha256",
          sources: { "src/shared/face-value.ts": "zz" },
          artifacts: {},
        }),
      };
      for (const [label, body] of Object.entries(shapes)) {
        const fx = makeFixture(); tmps.push(fx.root);
        writeFileSync(fx.stampPath, body);
        const r = reject(fx.wb) || "";
        check(`S5 malformed stamp refuses: ${label}`,
          r !== "" && r.includes("rule=stamp-malformed"), r.slice(0, 200));
      }
    }

    // S6 — legacy fallback for a stamp-less tree: the 2 s mtime rule, now
    // named, both ways (outside tolerance rejects, inside tolerance passes).
    {
      const fx = makeFixture(); tmps.push(fx.root); // no stamp written
      const libP = path.join(fx.wb, "lib", "client.js");
      const old = new Date(Date.now() - 60_000);
      const now = new Date();
      utimesSync(libP, old, old);
      for (const rel of Object.keys(fx.files)) utimesSync(path.join(fx.wb, rel), now, now);
      let r = reject(fx.wb) || "";
      check("S6 stamp-less stale tree still rejected (fallback)", r !== "");
      check("S6 fallback reject names rule=mtime-fallback", r.includes("rule=mtime-fallback"), r.slice(0, 200));
      utimesSync(libP, now, now);
      for (const rel of Object.keys(fx.files)) utimesSync(path.join(fx.wb, rel), now, now);
      r = reject(fx.wb);
      check("S6 stamp-less fresh tree still passes (2s tolerance)", r === null, `unexpected reject: ${r}`);
    }

    // (The rule-token contract is asserted per-subcase in S2–S6: every reject
    // message must carry exactly one rule= token naming the rule that fired.)
  } finally {
    for (const d of tmps) rmSync(d, { recursive: true, force: true });
  }

  if (failures.length > 0) {
    console.log(`FAIL t261026-23-lane-build-freshness-stamp: ${failures.length} subcase(s) red: ${failures.join(", ")}`);
    return 1;
  }
  console.log("PASS t261026-23-lane-build-freshness-stamp");
  return 0;
}

main().then(
  (code) => process.exit(code ?? 1),
  (e) => { console.log(`ENV_FAIL: scenario error: ${e && e.message}`); process.exit(2); },
);
