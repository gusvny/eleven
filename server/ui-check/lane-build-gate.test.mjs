#!/usr/bin/env node
// Unit tests for the lane build-freshness gate (t261026-23).
// The gate must decide freshness by CONTENT (.build-stamp.json written by
// server/plugins/workbench/build-client.sh) and keep the 2 s mtime rule only
// as a fallback for stamp-less trees, fail-closed in every degenerate case.
// Run: node --test server/ui-check/lane-build-gate.test.mjs

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, utimesSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const { laneBuildRejectReason } = await import(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "capture-lane.mjs")
);

const ARTIFACT_BYTES = "// bundled client (fixture bytes, not a real bundle)\n";
const WATCHED = ["src/client", "src/host", "src/shared"];
const ARTIFACTS = ["lib/client.cjs", "lib/client.js"];

const sha256Bytes = (b) => createHash("sha256").update(b).digest("hex");
const sha256File = (p) => sha256Bytes(readFileSync(p));

/** Deterministic stamp writer mirroring build-client.sh's stamp step
 * (sorted relative paths, per-file sha256, artifact hashes). */
function writeStamp(wb) {
  const sources = {};
  for (const sub of WATCHED) {
    const dir = path.join(wb, sub);
    if (!existsSync(dir)) continue;
    const walk = (d) => {
      for (const e of readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) walk(p);
        else sources[path.relative(wb, p).split(path.sep).join("/")] = sha256File(p);
      }
    };
    walk(dir);
  }
  const artifacts = {};
  for (const rel of ARTIFACTS) artifacts[rel] = sha256File(path.join(wb, rel));
  const stamp = { version: 1, algorithm: "sha256", sources, artifacts };
  mkdirSync(path.join(wb, "lib"), { recursive: true });
  writeFileSync(path.join(wb, ".build-stamp.json"), JSON.stringify(stamp));
  return stamp;
}

const readStamp = (wb) =>
  JSON.parse(readFileSync(path.join(wb, ".build-stamp.json"), "utf8"));
const writeRawStamp = (wb, raw) =>
  writeFileSync(path.join(wb, ".build-stamp.json"), raw);

/** Fresh fixture lane: lib artifacts + watched sources. */
function makeLane(t, { withStamp = true } = {}) {
  const wb = mkdtempSync(path.join(tmpdir(), "lane-gate-"));
  t.after(() => rmSync(wb, { recursive: true, force: true }));
  for (const sub of WATCHED) {
    mkdirSync(path.join(wb, sub), { recursive: true });
    writeFileSync(path.join(wb, sub, `${path.basename(sub)}.ts`), `// ${sub}\n`);
  }
  mkdirSync(path.join(wb, "lib"), { recursive: true });
  writeFileSync(path.join(wb, "lib", "client.cjs"), ARTIFACT_BYTES);
  writeFileSync(path.join(wb, "lib", "client.js"), ARTIFACT_BYTES);
  if (withStamp) writeStamp(wb);
  return wb;
}

/** The regression, pinned: make every watched source strictly NEWER than the
 * artifacts by explicit mtimes (not real creation order — order in tmpdirs is
 * exactly the clock-driven bug class this ticket kills). */
function makeSourcesNewerThanLib(wb, ms = 60_000) {
  const libM = 1_000_000_000_000;
  for (const rel of ARTIFACTS) {
    utimesSync(path.join(wb, rel), new Date(libM), new Date(libM));
  }
  for (const sub of WATCHED) {
    const p = path.join(wb, sub, `${path.basename(sub)}.ts`);
    utimesSync(p, new Date(libM + ms), new Date(libM + ms));
  }
}

test("missing lib/client.js is refused regardless of stamp", (t) => {
  const wb = makeLane(t);
  rmSync(path.join(wb, "lib", "client.js"));
  assert.match(laneBuildRejectReason(wb), /缺失/);
});

test("regression t261026: byte-identical tree with src mtimes newer than lib is FRESH via stamp", (t) => {
  const wb = makeLane(t);
  makeSourcesNewerThanLib(wb); // would fail the old mtime rule with a wide margin
  assert.equal(laneBuildRejectReason(wb), null);
});

test("changed source byte after stamping is stale (rule=stamp-mismatch)", (t) => {
  const wb = makeLane(t);
  writeFileSync(path.join(wb, "src", "shared", "shared.ts"), "// edited\n");
  assert.match(laneBuildRejectReason(wb), /rule=stamp-mismatch/);
});

test("source file added after stamping is stale (key set drift)", (t) => {
  const wb = makeLane(t);
  writeFileSync(path.join(wb, "src", "shared", "extra.ts"), "// new file\n");
  assert.match(laneBuildRejectReason(wb), /rule=stamp-mismatch/);
});

test("source file deleted after stamping is stale (key set drift)", (t) => {
  const wb = makeLane(t);
  rmSync(path.join(wb, "src", "host", "host.ts"));
  assert.match(laneBuildRejectReason(wb), /rule=stamp-mismatch/);
});

test("hand-edited lib/client.js (sources untouched) is refused (artifact hash)", (t) => {
  const wb = makeLane(t);
  writeFileSync(path.join(wb, "lib", "client.js"), ARTIFACT_BYTES + "// tampered\n");
  const reason = laneBuildRejectReason(wb);
  assert.match(reason, /rule=stamp-mismatch/);
  assert.match(reason, /client\.js/);
});

test("truncated stamp JSON is refused fail-closed (rule=stamp-malformed)", (t) => {
  const wb = makeLane(t);
  writeRawStamp(wb, '{"version":1,"algorithm":"sha');
  assert.match(laneBuildRejectReason(wb), /rule=stamp-malformed/);
});

test("stamp that is not an object is refused (rule=stamp-malformed)", (t) => {
  const wb = makeLane(t);
  writeRawStamp(wb, '["version",1]');
  assert.match(laneBuildRejectReason(wb), /rule=stamp-malformed/);
});

test("stamp with wrong version is refused (rule=stamp-malformed)", (t) => {
  const wb = makeLane(t);
  const raw = readStamp(wb);
  raw.version = 99;
  writeRawStamp(wb, JSON.stringify(raw));
  assert.match(laneBuildRejectReason(wb), /rule=stamp-malformed/);
});

test("stamp hash value that is not sha256 hex is refused (rule=stamp-malformed)", (t) => {
  const wb = makeLane(t);
  const raw = readStamp(wb);
  raw.sources["src/shared/shared.ts"] = "deadbeef";
  writeRawStamp(wb, JSON.stringify(raw));
  assert.match(laneBuildRejectReason(wb), /rule=stamp-malformed/);
});

test("stamp without artifacts object is refused (rule=stamp-malformed)", (t) => {
  const wb = makeLane(t);
  const raw = readStamp(wb);
  delete raw.artifacts;
  writeRawStamp(wb, JSON.stringify(raw));
  assert.match(laneBuildRejectReason(wb), /rule=stamp-malformed/);
});

test("stamp-less tree falls back to the mtime rule: within tolerance passes, beyond fails and names the rule", (t) => {
  const wb = makeLane(t, { withStamp: false });
  makeSourcesNewerThanLib(wb, 1_500); // inside the 2 s tolerance -> pass
  assert.equal(laneBuildRejectReason(wb), null);
  makeSourcesNewerThanLib(wb, 60_000); // beyond tolerance -> refuse
  assert.match(laneBuildRejectReason(wb), /rule=mtime-fallback/);
});

test("empty watched source set with empty sources stamp is fresh", (t) => {
  const wb = makeLane(t, { withStamp: false });
  for (const sub of WATCHED) rmSync(path.join(wb, sub), { recursive: true, force: true });
  const stamp = writeStamp(wb);
  assert.deepEqual(Object.keys(stamp.sources), []);
  assert.equal(laneBuildRejectReason(wb), null);
});

test("filename with a space round-trips through the stamp (fresh)", (t) => {
  const wb = makeLane(t, { withStamp: false });
  writeFileSync(path.join(wb, "src", "shared", "face value.ts"), "// spaced name\n");
  writeStamp(wb);
  assert.equal(laneBuildRejectReason(wb), null);
});
