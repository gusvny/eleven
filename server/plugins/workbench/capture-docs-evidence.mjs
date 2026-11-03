#!/usr/bin/env node
/**
 * capture-docs-evidence.mjs — the UI evidence driver for the documents face
 * (t261103-12, extended by t261103-19 for the four derived-index states).
 *
 * WHAT IT IS
 *   A thin driver over the SANCTIONED isolated bench (server/ui-check/capture-lane.mjs
 *   and its exported helpers). It boots the same bench the other lanes use — temporary
 *   DSH_HOME, temporary profile whose `sandbar-workbench` AND `sandbar-executor-panel`
 *   symlinks point at THIS lane's tree, temporary registry, a kernel-picked free port,
 *   the bench's own port patch so the console can never bind 3099 — and then drives the
 *   REAL views with Playwright.
 *
 * WHY A DRIVER AND NOT `capture-lane.mjs` ITSELF
 *   The bench's fixed VIEWS list captures the board / ticket detail / sessions /
 *   settings faces. Its docs shot was retired with t261005-10 UI-2 (the sidebar icon
 *   views were removed): the documents view no longer has a sidebar icon, it is the
 *   panel's Docs tab inside the executor-panel iframe. This driver keeps the bench's
 *   boot contract byte-for-byte and only replaces the capture phase, because the faces
 *   below need a seeded documentation-root declaration and a seeded derived index that
 *   the generic views never create.
 *
 * WHAT IT CAPTURES (default: the four index states of t261103-19)
 *   1. docs-index-absent.png  — the project never built the index: the live Docs face
 *      says so, names that the documents are listed from the declared roots, and still
 *      lists them.
 *   2. docs-index-current.png — the index matches the documents: "Index up to date —
 *      built <time>", quiet tone, the list beside it.
 *   3. docs-index-stale.png   — a rebuild is due: the state names the last build time
 *      and why a rebuild is due, and says the list is read from the roots, not from that
 *      index. The list is still shown (a stale index is labelled, never used as the
 *      listing).
 *   4. docs-index-failed.png  — the last rebuild failed: the named reason renders, and
 *      the banner says explicitly that the previous index is NOT shown as current.
 *   Every state is FORCED by seeding the project's derived index in the bench registry,
 *   not by stubbing the page: absent = no index.json; current = built after the pages;
 *   stale = built before the pages; failed = a rebuild-failed record newer than the
 *   build. No state needs to be skipped on this delivery.
 *
 *   --with-merged-shot additionally captures the t261103-12 face (docs-roots-merged.png:
 *   the merged view over two declared roots, with the colliding relative path shown in
 *   its selection-token form).
 *
 * USAGE (from the lane root; never touches port 3099)
 *   node server/plugins/workbench/capture-docs-evidence.mjs \
 *     --out .sandbar/screenshots [--timeout-ms 180000] [--with-merged-shot]
 *
 * OUTPUT CONTRACT
 *   PNGs land at the TOP LEVEL of --out (the evidence gate reads only that level, host
 *   ruling 261005-B). Every PNG is captured this round: the driver unlinks the old *.png
 *   in --out first, so a shot on disk is always a shot from this run. The manifest
 *   (docs-evidence-manifest.json) names what each shot proves, the bench port and the
 *   lane build path.
 *
 * EXIT CODES: 0 = every requested shot written and verified; 2 = a precondition or a
 * capture step failed (the failing step and its measured reason are printed; nothing is
 * written in that case for the failed shot).
 */
import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync,
         realpathSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync } from "node:fs"
import { mkdir, mkdtemp, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import process from "node:process"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

import {
  buildBenchRegistry, buildTempProfile, dshAuthFingerprint, laneBuildRejectReason,
  materializePresets, presetMaterializeRejectReason, waitReady,
} from "../../ui-check/capture-lane.mjs"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const LANE_ROOT = path.resolve(HERE, "..", "..", "..")      // server/plugins/workbench → lane
const LANE_WB = path.join(LANE_ROOT, "server", "plugins", "workbench")
const LANE_PANEL = path.join(LANE_ROOT, "server", "plugins", "executor-panel")
const MAIN_UI_CHECK = process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK
  || path.join(LANE_ROOT, "server", "ui-check")
const PLAYWRIGHT = process.env.SANDBAR_PLAYWRIGHT_MODULE
  || path.join(MAIN_UI_CHECK, "node_modules", "playwright-core")

function arg(name, dflt) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt
}

const OUT = path.resolve(arg("--out", path.join(LANE_ROOT, ".sandbar", "screenshots")))
const TIMEOUT_MS = Number(arg("--timeout-ms", "180000"))
const WITH_MERGED = process.argv.includes("--with-merged-shot")

const FM = "---\ntitle: %s\ncategory: reference\nstatus: active\nupdated: 2026-11-01\n---\n\nbody of %s\n"

/** The four reader states, one seeded project each. */
const STATES = ["absent", "current", "stale", "failed"]
const PROJECT_OF = {
  absent: "docs-t261103-19-absent",
  current: "docs-t261103-19-current",
  stale: "docs-t261103-19-stale",
  failed: "docs-t261103-19-failed",
  merged: "docs-t261103-12-merged",
}

/** The named reason a failed rebuild carries in the bench (never a generic sentence). */
const FAILED_REASON =
  "the documentation inspection could not read kb/alpha.md (EACCES); the index was not rewritten"

let tmpHome = null
let proc = null
let logFd = null
let tornDown = false
function teardown() {
  if (tornDown) return
  tornDown = true
  if (proc && proc.pid && proc.exitCode === null && proc.signalCode === null) {
    try { process.kill(-proc.pid, "SIGTERM") } catch { try { proc.kill("SIGKILL") } catch { /* gone */ } }
  }
  if (logFd !== null) { try { closeSync(logFd) } catch { /* closed */ } }
  if (tmpHome) { try { rmSync(tmpHome, { recursive: true, force: true }) } catch { /* best effort */ } }
}
process.on("exit", teardown)
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { teardown(); process.exit(130) })

async function freePort() {
  const net = await import("node:net")
  return await new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.once("error", reject)
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

/** A project.yaml in the bench registry's schema v1, declaring one docs root (`kb`). */
async function declareProject(registryRoot, key, workspace, docsRootsBlock) {
  const projectDir = path.join(registryRoot, key)
  await mkdir(projectDir, { recursive: true })
  await writeFile(path.join(projectDir, "project.yaml"),
    "schema: v1\nproject:\n  - key: " + key + "\n    name: " + key + "\n    dirs:\n"
    + "      - " + workspace + "\n"
    + docsRootsBlock, "utf8")
  return projectDir
}

/** Write the pages of one docs root and stamp their mtime (staleness is measured
 *  against the build, so the shots must not depend on wall-clock races). */
async function writePages(workspace, pages, mtimeMs) {
  for (const [rel, title] of pages) {
    const abs = path.join(workspace, rel)
    await mkdir(path.dirname(abs), { recursive: true })
    await writeFile(abs, FM.replace(/%s/g, title), "utf8")
    const at = mtimeMs / 1000
    try { utimesSync(abs, at, at) } catch { /* best effort: the reader also sees now() */ }
  }
}

/** Seed one project per index state. Returns the seeded facts for the manifest. */
async function seedStates(registryRoot) {
  const now = Date.now()
  const pages = [["kb/alpha.md", "Alpha page"], ["kb/design/beta.md", "Beta page"]]
  const docsRoots = "paths:\n  docs_roots:\n    - repository: .\n      path: kb\n"
  const seeded = {}
  for (const state of STATES) {
    const key = PROJECT_OF[state]
    const workspace = path.join(registryRoot, "workspace-" + key)
    // stale: the pages are newer than the build. Every other state: the pages are older.
    await writePages(workspace, pages, state === "stale" ? now : now - 3_600_000)
    const projectDir = await declareProject(registryRoot, key, workspace, docsRoots)
    const indexDir = path.join(projectDir, "data", "docs")
    if (state === "absent") {
      // Never built: no index directory at all (the reader must not create one).
      seeded[state] = { key, workspace, builtAt: "", indexDir }
      continue
    }
    await mkdir(indexDir, { recursive: true })
    const builtMs = state === "stale" ? now - 3_600_000 : now - 60_000
    const builtAt = new Date(builtMs).toISOString()
    await writeFile(path.join(indexDir, "index.json"), JSON.stringify({
      schema: "v1", project: key, built_at: builtAt, built_at_ts: builtMs / 1000,
      source: "declared", declaration: path.join(projectDir, "project.yaml"),
      roots: [{ identity: ".:kb" }], total: 2, categories: ["design", "reference"],
      docs: [
        { id: ".:kb:alpha.md", root: ".:kb", repository: ".", root_path: "kb", path: "alpha.md",
          title: "Alpha page", category: "reference", tags: ["x"], status: "active",
          updated: "2026-11-01", has_frontmatter: true },
        { id: ".:kb:design/beta.md", root: ".:kb", repository: ".", root_path: "kb",
          path: "design/beta.md", title: "Beta page", category: "design", tags: ["x"],
          status: "active", updated: "2026-11-01", has_frontmatter: true },
      ],
      review: { missing_frontmatter: [], deprecated: [], stale: [], unreadable: [],
        malformed_epics: [] },
      projections: [],
    }, null, 1), "utf8")
    if (state === "failed") {
      // A failed rebuild newer than the last successful build: the reader must hand the
      // named reason and must never serve the previous index as current.
      await writeFile(path.join(indexDir, "rebuild-failed.json"), JSON.stringify({
        project: key, failed_at: new Date(now).toISOString(), failed_at_ts: now / 1000,
        code: "docs_index_rebuild_failed", reason: FAILED_REASON,
      }, null, 1), "utf8")
    }
    seeded[state] = { key, workspace, builtAt, indexDir }
  }
  return seeded
}

/** Seed the t261103-12 merged-view project (two declared roots, one colliding path). */
async function seedMerged(registryRoot) {
  const key = PROJECT_OF.merged
  const workspace = path.join(registryRoot, "workspace-" + key)
  await writePages(workspace, [["kb/same.md", "Left root page"]], Date.now() - 3_600_000)
  await writePages(workspace, [["kb/only-left.md", "Left only page"]], Date.now() - 3_600_000)
  await writePages(workspace, [["repo-b/kb/same.md", "Member repo page"]], Date.now() - 3_600_000)
  await declareProject(registryRoot, key, workspace,
    "paths:\n  docs_roots:\n    - repository: .\n      path: kb\n"
    + "    - repository: repo-b\n      path: kb\n")
  return { key, workspace }
}

/** Point one plugin name of the temporary profile at THIS lane's tree, so the shots
 *  prove the lane build rather than the copy the bench inherits from the main tree. */
function linkLanePlugin(tmpHome, name, laneDir) {
  const link = path.join(tmpHome, "profiles", "sandbar", "node_modules", name)
  if (!existsSync(laneDir)) return false
  try { rmSync(link, { force: true }) } catch { /* absent */ }
  symlinkSync(realpathSync(laneDir), link)
  return true
}

function sha256(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex")
}

async function main() {
  if (!existsSync(PLAYWRIGHT)) {
    console.error(`[docs-evidence] ENV_FAIL: playwright-core missing at ${PLAYWRIGHT} `
      + "(the declared supply step symlinks the main tree's copy into the lane)")
    process.exit(2)
  }
  const reject = laneBuildRejectReason(LANE_WB)
  if (reject) { console.error(`[docs-evidence] refused: ${reject}`); process.exit(2) }
  const presetSrc = process.env.SANDBAR_CAPTURE_PRESET_SOURCE
    || path.join(process.env.HOME || "", ".dsh", ".agent-presets", "sandbar-integration")
  const presetReject = presetMaterializeRejectReason(presetSrc)
  if (presetReject) { console.error(`[docs-evidence] refused: ${presetReject}`); process.exit(2) }

  // Evidence is captured this round or not at all: unlink the previous PNGs first, so a
  // file on disk can never be a stale shot from an earlier run.
  if (existsSync(OUT)) {
    for (const f of readdirSync(OUT)) if (f.endsWith(".png")) rmSync(path.join(OUT, f))
  }
  await mkdir(OUT, { recursive: true })

  tmpHome = await mkdtemp(path.join(tmpdir(), "docs-evidence-"))
  await buildTempProfile(tmpHome, LANE_WB)
  // The live documents face is the executor panel's Docs tab: the bench must serve THIS
  // lane's panel page (its source is loaded at runtime, there is no bundle to rebuild).
  const panelOverridden = linkLanePlugin(tmpHome, "sandbar-executor-panel", LANE_PANEL)
  if (!panelOverridden) {
    console.error(`[docs-evidence] refused: the lane's executor-panel is missing at ${LANE_PANEL}`)
    process.exit(2)
  }
  const registryRoot = await buildBenchRegistry(tmpHome)
  const seeded = await seedStates(registryRoot)
  const merged = WITH_MERGED ? await seedMerged(registryRoot) : null
  await materializePresets(tmpHome, presetSrc)

  const port = await freePort()
  if (port === 3099) { console.error("[docs-evidence] refused: the picker returned the console port"); process.exit(2) }
  logFd = openSync(path.join(tmpHome, "console.log"), "a")
  const portPatch = path.join(tmpHome, "port_patch.yml")
  await writeFile(portPatch, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`, "utf8")
  const consoleCmd = (process.env.SANDBAR_CONSOLE_CMD || "dsh --profile sandbar").split(" ")
  proc = spawn(consoleCmd[0],
    [...consoleCmd.slice(1), "--patch", portPatch, "--port", String(port),
      "--host", "127.0.0.1", "--no-open"], {
      cwd: LANE_ROOT,
      env: { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: registryRoot,
        SANDBAR_TARGET_HOST: process.env.SANDBAR_TARGET_HOST || "127.0.0.1:17233" },
      detached: true,
      stdio: ["ignore", logFd, logFd],
    })
  const fingerprint = dshAuthFingerprint({ bin: consoleCmd[0] })
  const ready = await waitReady(port, TIMEOUT_MS, path.join(tmpHome, "console.log"), fingerprint)
  const entryUrl = ready.entryUrl || `http://127.0.0.1:${port}/`
  const base = new URL(entryUrl).origin
  console.log(`[docs-evidence] bench ready: 127.0.0.1:${port} (auth ${ready.authMode}, HTTP ${ready.status})`)
  console.log(`[docs-evidence] lane workbench build: ${path.join(LANE_WB, "lib", "client.js")}`)
  console.log(`[docs-evidence] lane panel page:      ${path.join(LANE_PANEL, "src", "host", "panel-page.ts")}`)
  for (const s of STATES) {
    console.log(`[docs-evidence] seeded ${s}: project=${seeded[s].key} built_at=${seeded[s].builtAt || "(never)"}`)
  }

  // playwright-core is a CommonJS package: load it through require (an ESM import of the
  // package directory is not supported).
  const chromium = createRequire(import.meta.url)(PLAYWRIGHT).chromium
  const browser = await chromium.launch()
  const written = []
  try {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await ctx.newPage()
    // Land on the sanctioned entry URL first: the token exchange there is what the
    // bench's own capture does, and it leaves the auth state that same-origin
    // navigations (the panel route, the console) rely on.
    await page.goto(entryUrl, { waitUntil: "domcontentloaded", timeout: 60000 })

    /** Open the live docs face for one project and wait for its list + index banner. */
    async function openDocsFace(projectKey, expectedState) {
      const panelUrl = `${base}/sandbar-executor-panel/?project=${encodeURIComponent(projectKey)}`
      await page.goto(panelUrl, { waitUntil: "domcontentloaded", timeout: 60000 })
      try {
        await page.waitForSelector('label[for="t-docs"]', { timeout: 30000 })
      } catch (e) {
        const diag = await page.evaluate(() => ({
          title: document.title, url: location.href,
          body: (document.body?.innerText || "").slice(0, 300),
        })).catch(() => ({}))
        throw new Error(`the panel Docs tab did not render (${JSON.stringify(diag)})`)
      }
      await page.click('label[for="t-docs"]')
      await page.waitForSelector("#docsTree [data-doc]", { timeout: 30000 })
      if (expectedState !== null) {
        await page.waitForFunction((s) => {
          const node = document.querySelector("#docsBanner [data-docs-index-state]")
          return !!node && node.getAttribute("data-docs-index-state") === s
        }, expectedState, { polling: 100, timeout: 30000 })
      }
      return await page.evaluate(() => {
        const node = document.querySelector("#docsBanner [data-docs-index-state]")
        return {
          banners: document.querySelectorAll("#docsBanner [data-docs-index-state]").length,
          state: node ? node.getAttribute("data-docs-index-state") : "",
          cls: node ? node.className : "",
          banner: node ? node.textContent.trim() : "",
          rows: [...document.querySelectorAll("#docsTree [data-doc]")]
            .map((n) => n.getAttribute("data-doc")),
        }
      })
    }

    /* ---- the four index states (t261103-19) -------------------------------- */
    const EXPECT = {
      absent: {
        must: [/Index not built yet/, /declared roots/],
        not: [/up to date/i],
        proves: "the derived index was never built: the live documents face says so, names that the "
          + "documents are listed from the declared roots, and still lists them",
      },
      current: {
        must: [/Index up to date/, /banner ok/],
        not: [/stale|failed/i],
        proves: "the index matches the documents: the face states the build time in the quiet tone, "
          + "and the list beside it is the current one",
      },
      stale: {
        must: [/Index is stale/, /A rebuild is due/, /not from that index/],
        not: [/up to date/i, /banner ok/, /banner red/],
        proves: "a rebuild is due: the face names the last build time and why, says the list is read "
          + "from the roots and not from that index, and never presents the stale content as current",
      },
      failed: {
        must: [/Index rebuild failed/, /NOT shown as current/, /EACCES/],
        not: [/up to date/i, /banner ok/],
        proves: "the last rebuild failed: the face gives the named reason, says explicitly that the "
          + "previous index is NOT shown as current, and lists the roots' documents in the red tone",
      },
    }
    for (const state of STATES) {
      const got = await openDocsFace(seeded[state].key, state)
      const exp = EXPECT[state]
      if (got.banners !== 1) {
        throw new Error(`${state}: expected exactly one index banner, got ${got.banners}`)
      }
      const haystack = `${got.banner} ${got.cls}`
      for (const re of exp.must) {
        if (!re.test(haystack)) throw new Error(`${state}: banner does not state ${re} (${JSON.stringify(got)})`)
      }
      for (const re of exp.not) {
        if (re.test(haystack)) throw new Error(`${state}: banner reads as ${re} (${JSON.stringify(got)})`)
      }
      if (got.rows.length < 2) {
        throw new Error(`${state}: the list beside the banner is not rendered (rows=${JSON.stringify(got.rows)})`)
      }
      const shot = path.join(OUT, `docs-index-${state}.png`)
      await page.screenshot({ path: shot, fullPage: true })
      written.push({ state, file: shot, banner: got.banner, cls: got.cls, rows: got.rows, proves: exp.proves })
      console.log(`[docs-evidence] ${state}: "${got.banner}" (rows=${got.rows.length}) → ${path.basename(shot)}`)
    }

    /* ---- t261103-12 face, on request --------------------------------------- */
    if (merged) {
      const got = await openDocsFace(merged.key, null)
      const labels = await page.evaluate(() => [...document.querySelectorAll("#docsTree .sect")]
        .map((n) => n.textContent.trim()))
      const mergedOk = labels.length >= 2
        && labels.every((l) => /repo-b\/kb|\bkb\b/.test(l))
        && got.rows.some((r) => /^@\d+\//.test(r))
        && got.rows.some((r) => r === "only-left.md")
      if (!mergedOk) {
        throw new Error(`the merged view did not show two labelled roots and a token row: ${JSON.stringify({ labels, rows: got.rows })}`)
      }
      const shot = path.join(OUT, "docs-roots-merged.png")
      await page.screenshot({ path: shot, fullPage: true })
      written.push({
        state: "merged", file: shot, banner: got.banner, rows: got.rows, labels,
        proves: "the documents view over two DECLARED roots: one merged list, every group labelled "
          + "<repo>/<rootPath> / <dir>, and the relative path held by both roots in its "
          + "selection-token form so the two pages stay distinct",
      })
      console.log(`[docs-evidence] merged: labels=${JSON.stringify(labels)} rows=${JSON.stringify(got.rows)}`)
    }
  } finally {
    await browser.close().catch(() => {})
  }

  const wbBundle = path.join(LANE_WB, "lib", "client.js")
  const manifest = {
    ticket: "t261103-19",
    title: "the live documents face renders the derived index state in all four cases",
    captured_at: new Date().toISOString(),
    lane: LANE_ROOT,
    face: "executor-panel Docs tab (the documents face the console embeds in its iframe), "
      + "driven at /sandbar-executor-panel/?project=<key> on the isolated bench",
    bench: {
      kind: "isolated (sanctioned capture-lane helpers: temp DSH_HOME, temp profile, temp registry)",
      port,
      console_port_3099_touched: false,
      dsh_home: "temporary (removed on exit)",
      lane_build: {
        panel_page: path.join(LANE_PANEL, "src", "host", "panel-page.ts"),
        index_view: path.join(LANE_PANEL, "src", "host", "docs-index-view.ts"),
        workbench_client_bundle: wbBundle,
        workbench_client_bundle_sha256: existsSync(wbBundle) ? sha256(wbBundle) : "",
      },
      plugins_overridden_to_lane: ["sandbar-workbench", "sandbar-executor-panel"],
    },
    how_each_state_was_forced: {
      absent: "the project has no derived index at all (no index.json in its data directory)",
      current: "the index was built after the pages were last written (roots and schema match)",
      stale: "the index was built an hour before the pages were last written (a rebuild is due)",
      failed: "a rebuild-failed record exists that is newer than the last successful build",
    },
    shots: written.map((w) => ({
      file: path.basename(w.file),
      state: w.state,
      proves: w.proves,
      measured: { banner: w.banner, banner_class: w.cls || "", rows: w.rows, labels: w.labels || null },
    })),
  }
  writeFileSync(path.join(OUT, "docs-evidence-manifest.json"), JSON.stringify(manifest, null, 1), "utf8")
  for (const f of readdirSync(OUT)) {
    if (!f.endsWith(".png")) continue
    const p = path.join(OUT, f)
    const st = statSync(p)
    const magic = readFileSync(p).subarray(0, 8)
    const isPng = magic[0] === 0x89 && magic.subarray(1, 4).toString("latin1") === "PNG"
    console.log(`[docs-evidence] ${f}: ${st.size} bytes, png=${isPng}`)
    if (!isPng || st.size <= 5000) {
      console.error(`[docs-evidence] FAILED: ${f} is not a real PNG above 5 kB (${st.size} bytes)`)
      teardown()
      process.exit(2)
    }
  }
  console.log(`[docs-evidence] wrote ${written.length} shot(s) into ${OUT}`)
  teardown()
  // A bench child's inherited pipes can keep the event loop alive; the run is complete
  // once the shots and the manifest are on disk, so exit deterministically.
  process.exit(written.length === STATES.length ? 0 : 2)
}

main().catch((e) => {
  console.error(`[docs-evidence] FAILED: ${e && e.message ? e.message : e}`)
  teardown()
  process.exit(2)
})
