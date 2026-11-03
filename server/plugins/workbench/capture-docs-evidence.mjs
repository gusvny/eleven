#!/usr/bin/env node
/**
 * capture-docs-evidence.mjs — the UI evidence driver for t261103-12 (docs roots, index +
 * presentation half).
 *
 * WHAT IT IS
 *   A thin driver over the SANCTIONED isolated bench (server/ui-check/capture-lane.mjs
 *   and its exported helpers). It boots the same bench the other lanes use — temporary
 *   DSH_HOME, temporary profile whose `sandbar-workbench` symlink points at THIS lane's
 *   build, temporary registry, a kernel-picked free port, the bench's own port patch so
 *   the console can never bind 3099 — and then drives the REAL views with Playwright.
 *
 * WHY A DRIVER AND NOT `capture-lane.mjs` ITSELF
 *   The bench's fixed VIEWS list captures the board / ticket detail / sessions /
 *   settings faces. Its docs shot was retired with t261005-10 UI-2 (the sidebar icon
 *   views were removed): the documents view no longer has a sidebar icon, it is the
 *   panel's Docs tab inside the executor-panel iframe. This driver keeps the
 *   bench's boot contract byte-for-byte and only replaces the capture phase, because the
 *   two faces below need a seeded documentation-root declaration and a seeded derived
 *   index that the generic views never create.
 *
 * WHAT IT CAPTURES
 *   1. docs-roots-merged.png — the documents view over DECLARED roots. The seeded project
 *      declares `paths.docs_roots` with two roots (`.`/kb and `repo-b`/kb) and holds a
 *      relative path present in BOTH roots. The shot proves the merged view: one list,
 *      every group labelled `<repo>/<rootPath> / <dir>`, and the colliding path shown in
 *      its selection-token form (`@<n>/<path>`) so the two pages stay distinct.
 *   2. docs-index-state.png — the derived index state banner. The seeded project's index
 *      is stale on purpose (built in the past, a page newer than the build), so the
 *      knowledge feature must render "Index is stale - last built <time> ..." and must
 *      NOT present the index as current, while the rows themselves come from the roots.
 *
 * USAGE (from the lane root; never touches port 3099)
 *   node server/plugins/workbench/capture-docs-evidence.mjs \
 *     --out .sandbar/screenshots [--project docs-t261103-12] [--timeout-ms 180000]
 *
 * EXIT CODES: 0 = every requested shot written and verified; 2 = a precondition or a
 * capture step failed (the failing step and its measured reason are printed; nothing is
 * written in that case for the failed shot).
 */
import { spawn } from "node:child_process"
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync,
         realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs"
import { copyFile as copyFileP, mkdir, mkdtemp, writeFile } from "node:fs/promises"
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
const MAIN_UI_CHECK = process.env.SANDBAR_CAPTURE_MAIN_UI_CHECK
  || path.join(LANE_ROOT, "server", "ui-check")
const PLAYWRIGHT = process.env.SANDBAR_PLAYWRIGHT_MODULE
  || path.join(MAIN_UI_CHECK, "node_modules", "playwright-core")

function arg(name, dflt) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt
}

const OUT = path.resolve(arg("--out", path.join(LANE_ROOT, ".sandbar", "screenshots")))
const PROJECT = arg("--project", "docs-t261103-12")
const TIMEOUT_MS = Number(arg("--timeout-ms", "180000"))
const WITH_KNOWLEDGE = process.argv.includes("--with-knowledge-shot")

const FM = "---\ntitle: %s\ncategory: reference\nstatus: active\nupdated: 2026-11-01\n---\n\nbody of %s\n"

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

/** Seed the bench project: a real `paths.docs_roots` declaration with two roots, one
 *  relative path held by both, and a derived index that is STALE on purpose. */
async function seedProject(registryRoot) {
  const workspace = path.join(registryRoot, "workspace-docs")
  const perkey = path.join(registryRoot, PROJECT)
  await mkdir(path.join(workspace, "kb"), { recursive: true })
  await mkdir(path.join(workspace, "repo-b", "kb"), { recursive: true })
  await writeFile(path.join(workspace, "kb", "same.md"), FM.replace(/%s/g, "Left root page"), "utf8")
  await writeFile(path.join(workspace, "kb", "only-left.md"), FM.replace(/%s/g, "Left only page"), "utf8")
  await writeFile(path.join(workspace, "repo-b", "kb", "same.md"), FM.replace(/%s/g, "Member repo page"), "utf8")
  await mkdir(perkey, { recursive: true })
  await writeFile(path.join(perkey, "project.yaml"),
    "schema: v1\nproject:\n  - key: " + PROJECT + "\n    name: " + PROJECT + "\n    dirs:\n"
    + "      - " + workspace + "\n"
    + "paths:\n  docs_roots:\n"
    + "    - repository: .\n      path: kb\n"
    + "    - repository: repo-b\n      path: kb\n", "utf8")
  // A STALE derived index: built an hour ago, while the pages are newer than the build,
  // so the reader must label it stale and must never present it as current.
  const builtAt = new Date(Date.now() - 3600_000)
  const indexDir = path.join(perkey, "data", "docs")
  await mkdir(indexDir, { recursive: true })
  await writeFile(path.join(indexDir, "index.json"), JSON.stringify({
    schema: "v1", project: PROJECT, built_at: builtAt.toISOString(),
    built_at_ts: builtAt.getTime() / 1000, source: "declared",
    declaration: path.join(perkey, "project.yaml"),
    roots: [{ identity: ".:kb" }, { identity: "repo-b:kb" }],
    total: 2, categories: ["reference"],
    docs: [
      { id: ".:kb:same.md", root: ".:kb", repository: ".", root_path: "kb", path: "same.md",
        title: "Left root page", category: "reference", tags: ["x"], status: "active",
        updated: "2026-11-01", has_frontmatter: true },
      { id: ".:kb:only-left.md", root: ".:kb", repository: ".", root_path: "kb",
        path: "only-left.md", title: "Left only page", category: "reference", tags: ["x"],
        status: "active", updated: "2026-11-01", has_frontmatter: true },
    ],
    review: { missing_frontmatter: [], deprecated: [], stale: [], unreadable: [],
      malformed_epics: [] },
    projections: [],
  }, null, 1), "utf8")
  return { workspace, perkey, builtAt: builtAt.toISOString() }
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

  tmpHome = await mkdtemp(path.join(tmpdir(), "docs-evidence-"))
  await buildTempProfile(tmpHome, LANE_WB)
  // The knowledge feature is the surface that renders the derived-index state, so the
  // bench's knowledge plugin symlink points at THIS lane too (the bench itself only
  // overrides the workbench plugin).
  const nm = path.join(tmpHome, "profiles", "sandbar", "node_modules")
  const laneKnowledge = path.join(LANE_ROOT, "server", "plugins", "knowledge")
  if (WITH_KNOWLEDGE && existsSync(laneKnowledge)) {
    const link = path.join(nm, "sandbar-knowledge")
    try { rmSync(link, { force: true }) } catch { /* absent */ }
    try { symlinkSync(realpathSync(laneKnowledge), link) } catch { /* keep the bench copy */ }
  }
  const registryRoot = await buildBenchRegistry(tmpHome)
  const seeded = await seedProject(registryRoot)
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
  console.log(`[docs-evidence] seeded project ${PROJECT}: workspace=${seeded.workspace} stale-index=${seeded.builtAt}`)

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
    // navigations (the panel iframe route, the console) rely on.
    await page.goto(entryUrl, { waitUntil: "domcontentloaded", timeout: 60000 })

    /* ---- 1. the documents view over the declared roots ------------------------ */
    await mkdir(OUT, { recursive: true })
    const panelUrl = `${base}/sandbar-executor-panel/?project=${encodeURIComponent(PROJECT)}`
    await page.goto(panelUrl, { waitUntil: "domcontentloaded", timeout: 60000 })
    // The Docs tab is a radio-labelled tab in the panel; label click = showTab('t-docs').
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
    const measured = await page.evaluate(() => {
      const rows = [...document.querySelectorAll("#docsTree [data-doc]")]
      const labels = [...document.querySelectorAll("#docsTree .sect")]
      return {
        labels: labels.map((n) => n.textContent.trim()),
        rows: rows.map((n) => n.getAttribute("data-doc")),
        banner: (document.getElementById("docsBanner")?.textContent || "").trim(),
      }
    })
    console.log(`[docs-evidence] docs view: labels=${JSON.stringify(measured.labels)}`)
    console.log(`[docs-evidence] docs view: rows=${JSON.stringify(measured.rows)}`)
    const mergedOk = measured.labels.length >= 2
      && measured.labels.every((l) => /repo-b\/kb|\bkb\b/.test(l))
      && measured.rows.some((r) => /^@\d+\//.test(r))
      && measured.rows.some((r) => r === "only-left.md")
    if (!mergedOk) {
      throw new Error(`the merged view did not show two labelled roots and a token row: ${JSON.stringify(measured)}`)
    }
    const shot1 = path.join(OUT, "docs-roots-merged.png")
    await page.screenshot({ path: shot1, fullPage: true })
    written.push({ file: shot1, labels: measured.labels, rows: measured.rows })

    /* ---- 2. the derived index state banner (knowledge feature) ---------------- */
    if (!WITH_KNOWLEDGE) {
      // MEASURED, not guessed (t261103-12): no shipped surface renders the derived
      // index state, so no honest screenshot of it exists yet.
      //   (a) server/plugins/workbench/src/client/docs.tsx — its DocsSection is not
      //       imported by any client entry (index.tsx keeps only the model comment), so
      //       its state banner ships nowhere;
      //   (b) server/plugins/knowledge/src/client/index.tsx — apply() is a no-op (the
      //       view is carried by the workbench sidebar), so its banner mounts nowhere;
      //   (c) server/plugins/executor-panel/src/host/panel-page.ts — the LIVE docs face
      //       clears #docsBanner and renders groups / skipped / empty+reason only; it
      //       never reads the index state.
      // The attempt below stays available (--with-knowledge-shot) for the day a surface
      // renders it.
      console.log("[docs-evidence] docs-index-state.png: UNSATISFIABLE on this delivery — "
        + "measured: workbench docs.tsx DocsSection is not mounted by any client entry; "
        + "the knowledge client's apply() registers nothing; the live panel docs face "
        + "renders groups/skipped/empty+reason only and never reads the index state")
    }
    if (WITH_KNOWLEDGE) {
      // The knowledge page is a dsh session view: open a real session in the bench, then
      // switch the session view to the knowledge feature.
      const opened = await fetch(`${base}/sandbar-workbench/api/global-session/open`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ project: PROJECT }),
      }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }))
      if (!opened?.ok || typeof opened?.result?.session_id !== "string") {
        throw new Error(`knowledge shot: the bench could not open a session (${JSON.stringify(opened?.error ?? opened)})`)
      }
      const sessionId = opened.result.session_id
      await page.goto(`${base}/?project=${encodeURIComponent(PROJECT)}`, { waitUntil: "domcontentloaded", timeout: 60000 })
      await page.evaluate(([id]) => {
        try {
          localStorage.setItem("sandbar-ui-capture-skip-charter", "1")
          localStorage.setItem("sandbar-session-ledger", JSON.stringify([{ id, cwd: "" }]))
        } catch { /* best effort */ }
      }, [sessionId])
      await page.reload({ waitUntil: "domcontentloaded" })
      // Open the seeded session, then look for the knowledge feature's entry point.
      const sessionRow = page.locator("[data-wb-psess-row], [data-wb-session-entry]").first()
      await sessionRow.waitFor({ state: "visible", timeout: 20000 })
      await sessionRow.click()
      const banner = await page.waitForFunction(() => {
        const nodes = [...document.querySelectorAll("[data-kb-index-banner]")]
        return nodes.length > 0 ? nodes[0].textContent.trim() : null
      }, null, { timeout: 45000 }).then((h) => h.jsonValue()).catch(() => null)
      if (!banner) {
        throw new Error("knowledge shot: no [data-kb-index-banner] appeared "
          + "(the knowledge feature's session view did not mount in the bench)")
      }
      if (!/stale/i.test(banner) || /up to date/i.test(banner)) {
        throw new Error(`knowledge shot: the banner does not label the stale state: ${banner}`)
      }
      const shot2 = path.join(OUT, "docs-index-state.png")
      await page.screenshot({ path: shot2, fullPage: true })
      written.push({ file: shot2, banner })
    }
  } finally {
    await browser.close().catch(() => {})
  }

  const manifest = {
    ticket: "t261103-12",
    lane: LANE_ROOT,
    bench: { kind: "isolated (sanctioned capture-lane helpers)", port_hint: "kernel-picked free port",
      console_port_3099_touched: false, dsh_home: "temporary (removed on exit)",
      lane_build: path.join(LANE_WB, "lib", "client.js") },
    project: PROJECT,
    shots: written.map((w) => ({
      file: path.basename(w.file),
      proves: w.labels
        ? "documents view over the DECLARED roots: one merged list, every group labelled <repo>/<rootPath> / <dir>, and the relative path held by both roots shown in its selection-token form"
        : "derived index state banner: the stale state names the last build time and never presents the index as current, while the rows come from the declared roots",
      measured: w.labels ?? w.banner,
    })),
  }
  writeFileSync(path.join(OUT, "docs-evidence-manifest.json"), JSON.stringify(manifest, null, 1), "utf8")
  for (const f of readdirSync(OUT)) {
    const p = path.join(OUT, f)
    if (f.endsWith(".png")) {
      const st = statSync(p)
      const magic = readFileSync(p).subarray(0, 8)
      const isPng = magic[0] === 0x89 && magic.subarray(1, 4).toString("latin1") === "PNG"
      console.log(`[docs-evidence] ${f}: ${st.size} bytes, png=${isPng}`)
    }
  }
  console.log(`[docs-evidence] wrote ${written.length} shot(s) into ${OUT}`)
  teardown()
  // A bench child's inherited pipes can keep the event loop alive; the run is complete
  // once the shots and the manifest are on disk, so exit deterministically.
  process.exit(written.length === 0 ? 2 : 0)
}

main().catch((e) => {
  console.error(`[docs-evidence] FAILED: ${e && e.message ? e.message : e}`)
  teardown()
  process.exit(2)
})
