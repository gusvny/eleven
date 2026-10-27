---
title: "Suyou admin × DeepSeek Harness (dsh) Application Plan"
category: ops
tags:
  - admin
  - dsh
  - application plan
status: active
updated: 2026-09-28
---

# Suyou admin × DeepSeek Harness (dsh) Application Plan

> Version: v0.1; date: 2026-08-19; status: research conclusions + route recommendation, no code touched
> Subject of study: `/Users/user/Documents/deepseek-harness` (0.1.0-rc.7 Developer Preview, read statically only, not installed and not built)
> Comparison baseline: `server/serve.py` / `server/admin.py` / `server/tools_registry.py` / `server/tools/*` / Platform Architecture Design §12

---

## 1. dsh architecture at a glance (half a page)

DeepSeek Harness (`dsh`) is DeepSeek's officially open-sourced agent harness: **"everything is a plugin"**, built on a vendored copy of the Cordis framework (`vendor/cordis`, source embedded rather than pulled in as an npm dependency, see `vendor/README.md`). Every part of the product — model adapters, tool registry, session logs, approval policy, the agent loop itself — is a Cordis plugin attached to the shared context `ctx` (`ctx.tools` / `ctx.llm` / `ctx.sessions` / `ctx.approval` …), and every one of them can be replaced from the configuration layer.

**Form**: one Node CLI (`npx @deepseek-ai/dsh`) with two factory profiles:

- `dsh web` — starts the Web UI (default `http://127.0.0.1:3080`, bound to loopback only). In the browser you get a complete agent console: session list plus full-text search, the conversation stream, **every tool call rendered as a card** (five card faces: generic/terminal/diff/search; two states, pending→done), operations that need approval popping an "allow/deny" prompt on the page, and model management on the settings page (enter an API key and it takes effect hot, no restart needed). A session can only run after a workspace is selected.
- `dsh --profile headless "task"` — a one-shot unattended run: it opens a new persistent session, prints the last assistant message to stdout when it finishes, and exits without opening a port. This is a ready-made "call an agent from the CLI" form.

**Assembly**: at runtime it is a plugin tree, built by stacking four patch layers in order — the bundle listed by the profile (`dsh-base` foundation + `dsh-web-app`/`dsh-headless` surface) → the profile's own `cordis.patch.yml` → the global `$DSH_HOME/cordis.patch.yml` → a command-line `--patch` file. A patch locates a row by `id` and replaces its config wholesale, or `insert`s a new row. `dsh --dump-config` prints the actually assembled tree without starting any service.

**Plugins**: a TS module exporting `apply(ctx)` is a plugin; `ctx.tools.register(defineTool({...}))` registers one model-visible tool, its parameter schema automatically goes into the system prompt, and the registration is automatically withdrawn when the plugin unloads. A plugin can be an npm package (`dsh plugin add` installs it into the profile directory through pnpm), or **a .ts file at an absolute path** written straight into the `--patch` cordis.yml (this is exactly what the official "first plugin" tutorial does; Node 22.19+/24 loads .ts directly through native type stripping).

**Sessions**: one append-only event log per session (JSONL, zstd-compressed by default, stored under `$DSH_HOME/sessions/`); `tool/call`/`tool/result`/`approval/asked`/`approval/decided` are all persisted and replayable; format version `SESSION_FORMAT_VERSION = 0` (pre-release, no compatibility promise).

**Models**: ships with a `deepseek-official` route (the `dsh-llm-deepseek` adapter, speaking the streaming protocol to `api.deepseek.com` directly), with deepseek-v4-flash / v4-pro as the default models; the key goes through the credentials seam (`$DSH_HOME/.credentials.yaml` ← `DEEPSEEK_API_KEY` env ← `.env`), and **BYOK is a first-class citizen**: storing a key on the Web settings page takes effect immediately, while the config only ever holds an `apiKeyEnv` reference and never a literal key.

**Dynamic plugins**: `dsh-tool-cordis` provides five model-visible tools — `cordis_inspect / cordis_define / cordis_run / cordis_stop / cordis_undefine` — so an agent can define and mount/unmount temporary plugins in a vm sandbox inside a running process (the project's own words: "the sandbox isolates globals, but it is not a security boundary", and "it should be treated like bash access"). A temporary plugin lives only in process memory and disappears when the process exits — fine for experiments, unsuitable as a formal tool face.

---

## 2. The four §12 harness contract items ↔ dsh mechanisms

| Suyou contract (§12.2) | Current state (hand-written python) | Corresponding dsh mechanism | Conclusion |
|---|---|---|---|
| ①Toolization: JSON in/out, complete schemas, bindable to any harness | `tools_registry.py`: the TOOL dict is the DeepSeek function-calling schema emitted directly | `ctx.tools.register()` + `defineTool`; **raw JSON Schema tools** are also accepted (they validate their own input) | **Seamless**: the schema dump from the python side can be mapped verbatim onto dsh tool registration |
| ②Idempotent + dry-run | Left to each python tool to implement | dsh does not concern itself with this layer (it is internal to a tool's execute) | Stays in the python tool layer, unchanged |
| ③Two-phase commit + credential isolation | v0 has only admin token layering, no approval queue | the `ctx.approval` seam + `tools/pre-execute` returning `ask` → the Web UI pops a human approval; approval decisions are written as `approval/asked`/`approval/decided` audit events; policies `ask`/`never` | **dsh directly fills the approval step we lack**; but it is single-user, local-UI approval with no TOTP and no remote approval queue, so this item still has to be self-built for cross-machine deployment |
| ④run-id audit | `admin.log` JSONL, one uuid run-id per call | the session event log is append-only on disk (tool/call + tool/result with full parameters and results), with crash recovery built in | **Two-layer audit**: the python-layer run-id is left alone; put run_id into the tool return value and it automatically enters the dsh session log, so the two sides can be cross-checked |

Capabilities dsh throws in for free (which our hand-written loop does not have): a hard ≤8-round cap → dsh has no cap but ships guard plugins (repeat-tool-reminder/timeout-policy) plus an approval circuit breaker; context compaction; session fork/restore/full-text search; subagents; Web UI tool trace cards; hot model switching; and **`dsh --profile headless "task"` directly replacing `admin.py chat`**.

---

## 3. Comparing the three application routes

| | A. Full migration | B. dsh as the console (HTTP thin shell) | C. Hybrid (local thin shell) |
|---|---|---|---|
| In one line | Hand admin's CLI/WebUI/chat entirely to dsh; python tools are rewritten or wrapped one by one as TS plugins | The dsh plugin is only a forwarder that hits `/api/admin/call` | The dsh plugin spawns the existing `admin.py call`, and the WebUI uses `dsh web` |
| Source of truth for tools | Moves to TS (or a TS shell) | **Unchanged**, python | **Unchanged**, python |
| serve.py | Retreats to a pure content service | Unchanged (the admin API stays as before) | Unchanged (the admin API stays as before, kept as the remote form) |
| admin.py chat | Deleted (replaced by headless) | Kept as a fallback | Kept as a fallback |
| Audit | Only the dsh session log remains | run-id stays in the python layer, and the dsh log only records "an HTTP call was made" | run-id enters the tool return value → **consistent across both layers** |
| Approval | dsh approval seam | same as the left | same as the left |
| Change volume | Large (a TS shell per tool + rewritten validation) | Smallest (1 plugin, ~80 lines) | Small (1 plugin, ~150 lines, auto-generating the tool table) |
| New dependencies | Node 22.19+/24 + npx dsh (mandatory install) | same as the left | same as the left |
| Remote admin (future server deployment) | Needs rethinking (dsh is a local process) | **Natively supported** (HTTP to a remote host) | Just add an HTTP backend switch |
| Risk | Tool semantics drift in translation; TS/Python dual implementation | The dsh side cannot see tool detail traces (only one HTTP call card) | Requires dsh and the repo on the same machine; spawn overhead on the order of ~100ms per call |
| Conflict with the "pure stdlib deployment" route | Large | Medium | Medium (Node enters on the admin side; the content service is unaffected) |

### Route A: migrate all of admin to dsh

Rewrite `server/tools/*.py` one by one as dsh plugin packages (TS); heavy logic such as qc_run can still spawn python pipeline scripts, but schema/validation/audit all live on the TS side. Delete `/api/admin/*` from serve.py and retreat to a pure content service.
**Pros**: the "purest" use of dsh, the finest tool trace cards, approval/pre-execute granularity down to a single tool.
**Cons**: the source of truth for tools moves from python to TS, contradicting the status quo of "pipeline and admin in the same language, in the same directory"; risk of writing the QC decision logic twice; when deploying to a server later, dsh is a local-process model, so another layer has to be built.

### Route B: dsh as the agent console only (HTTP forwarding)

Write one dsh plugin that registers a few meta-tools (such as `suyou_admin_call(name, args)`) which internally `fetch` the existing `POST /api/admin/call` (with the admin token). Not one line changes on the python side.
**Pros**: smallest change; remote serve.py works natively.
**Cons**: what the model sees is "a tool that calls a tool", with an opaque schema (unless the schemas from `/api/admin/tools` are also passed through verbatim and registered as dsh raw JSON Schema tools — which starts to approach C); the admin token ends up in the dsh-side config, so the credential-isolation stance has to be spelled out.

### Route C: hybrid (recommended)

Write one dsh plugin package, `dsh-sandbar-admin`:

- At startup, run `python3 server/admin.py tools` to fetch the DeepSeek schema dump of every tool and **register them verbatim as dsh raw JSON Schema tools** (dsh states explicitly: "raw JSON Schema tools registered directly are responsible for their own input validation", `docs/cookbook/adding-a-tool.zh.md`);
- Each tool's `execute` = `spawn('python3', ['server/admin.py', 'call', name, JSON.stringify(args)])`, parse the `{ok, result|error, run_id}` on stdout and return it as is — **the single source of truth for run-id auditing stays in the python `admin.log`**, while run_id travels with the return value into the dsh session log, so the two layers can be cross-checked;
- Also attach a `tools/pre-execute` listener: on a hit against the destructive-tool list (`params_set` and, in the future, §12.4's publish/unpublish/ledger adjustment) → go through `ctx.approval` and pop a human approval (the v1 form of §12.2-③ two-phase commit);
- Use `dsh web` for the WebUI directly (tool cards, approval dialogs, session replay all come for free); use `dsh --profile headless "run the 260627 QC and list the red items"` instead of `admin.py chat` for the CLI;
- Keep `admin.py chat` / `/api/admin/chat` as the fallback path for environments without Node; not one line of serve.py changes.

**Why C**: it satisfies the hard requirement of "genuinely using dsh" (agent loop, WebUI, approval, session audit, plugin mechanism all come from dsh), while leaving three things untouched — the source of truth for tools, run-id auditing, and the stdlib content service; the python tool layer keeps growing against the §12.2 contract, and the dsh side is forever just an auto-generated shell, so **there is no dual-write drift** (the schema is fetched and registered afresh at every startup).

---

## 4. Route C landing steps (file level)

Prerequisite: install Node ≥22.19 (or 24+). No need to clone/build the dsh source; just use `npx @deepseek-ai/dsh`.

1. **Install dsh and smoke-test it** (without touching the suyou repo):
   ```sh
   npx @deepseek-ai/dsh@0.1.0-rc.7 web   # first run auto-initializes ~/.dsh/profiles/web
   ```
   Open 127.0.0.1:3080 in a browser → settings → models, fill in DEEPSEEK_API_KEY (written into `~/.dsh/.credentials.yaml`, effective hot) → add a workspace pointing at the suyou repo → run "list the files in the current directory" to verify the bash tool and the approval dialog.
   (Version pinned to rc.7; upgrades go through a proposal.)

2. **Create the plugin** (the only new suyou-side artifact this plan adds; suggested location `server-plugin/`, touching none of the existing files):
   ```
   server-plugin/
     sandbar-admin.ts        # the plugin body (skeleton below)
     cordis.yml              # --patch overlay
   ```
   `cordis.yml`:
   ```yaml
   - insert:
       - id: sandbar-admin
         name: '/Users/user/Documents/suyou/server-plugin/sandbar-admin.ts'
   ```
   Start it with: `npx @deepseek-ai/dsh@0.1.0-rc.7 web --patch server-plugin/cordis.yml`

3. **Plugin skeleton** (the critical path, about 120 lines; the API shapes come from `docs/cookbook/adding-a-tool.zh.md` and `docs/user/develop/basic/tool.zh.md`, both read directly from the docs):
   ```ts
   import { execFile } from 'node:child_process'
   import { promisify } from 'node:util'
   import type { Context } from '@deepseek-ai/cordis'

   const execFileP = promisify(execFile)
   const REPO = '/Users/user/Documents/suyou'
   // Destructive tool list: a hit routes to human approval (§12.2-③ two-phase commit v1)
   const NEEDS_APPROVAL = new Set(['params_set'])

   export const name = 'sandbar-admin'
   export const inject = ['tools']

   async function py(args: string[]) {
     const { stdout } = await execFileP('python3', ['server/admin.py', ...args],
       { cwd: REPO, maxBuffer: 16 * 1024 * 1024 })
     return JSON.parse(stdout)
   }

   export async function apply(ctx: Context) {
     // ① fetch the tool table from the python registry at startup (DeepSeek function-calling schema straight through)
     const tools: any[] = await py(['tools'])
     for (const t of tools) {
       const fn = t.function
       // ② raw JSON Schema tool registration (input validation follows the python-side tools_registry stance)
       ctx.tools.register({
         name: fn.name,
         description: fn.description,
         parameters: fn.parameters,          // pass the JSON Schema through as is
         async execute(args: any) {
           const res = await py(['call', fn.name, JSON.stringify(args ?? {})])
           // ③ run_id comes back with the result → lands in both the dsh session log and python admin.log
           return res
         },
       } as any)
     }
     // ④ two-phase commit: destructive tools pass human approval first (tools/pre-execute is a waterfall)
     ctx.on('tools/pre-execute', async (exec: any, next: any) => {
       if (NEEDS_APPROVAL.has(exec.name)) {
         const verdict = await (ctx as any).approval?.request?.({
           agent: exec.agent, tool: exec.name, reason: 'Suyou admin destructive operation, human confirmation required',
         })
         if (verdict !== 'allowed-once') return { kind: 'deny', reason: 'human approval not granted' }
       }
       return next()
     })
   }
   ```
   Note: the exact type signature of a raw `ctx.tools.register` registration and the request fields of `ctx.approval.request` are governed by the generated sections of `packages/core/tools/README.md` and `docs/subsystems/approval.md` (this document illustrates them per the documented stance; **calibrate once against the generated docs before the first real run** — that is the only place in the skeleton likely to differ from what rc.7 actually does).

4. **Verification checklist**:
   - In the Web UI, tell the agent "run the QC", and confirm that it calls `qc_run` on its own, that the tool card shows a structured red/green light, and that the same run_id appears both in the JSONL under `~/.dsh/sessions/` and in `server/admin.log`;
   - Ask it to `params_set`, and confirm that the approval dialog pops up and that the tool ends as deny after a rejection;
   - CLI form: `npx @deepseek-ai/dsh@0.1.0-rc.7 --profile headless --patch <same as above> "take stock of the data and report"` (the headless profile has no Web approval responder, so destructive tools fail closed — which is exactly right: with nobody on duty, nobody is present to approve).

5. **Documentation wrap-up**: add a line to CLAUDE.md's "current status" for the dual admin form (python CLI/API as before + the dsh console), and annotate Platform Architecture Design §12.2-③ with "approval step v1 = dsh approval seam (local UI); TOTP/remote approval queue to be reassessed at deployment step ②".

**Explicitly out of scope**: do not change a single line of serve.py/admin.py/tools_registry.py; do not translate the python tools into TS; do not enable the `dsh-tool-cordis` dynamic plugins (the project's own words are "treat it like bash access"; the admin scenario has no such need, and it only enlarges the attack surface).

---

## 5. Risk list

1. **Breaking changes in a Developer Preview (the biggest risk)**. The README is explicit: "breaking changes will appear in the future"; the session log format `SESSION_FORMAT_VERSION = 0` states plainly that compatibility is not promised (after an upgrade, old sessions may simply be refused); the row ids/structure of `packages/bundle/base/cordis.patch.yml` are changing. **Mitigation**: pin the version to `0.1.0-rc.7` (npx with the version number); upgrades go through a proposal process, comparing `--dump-config` first; our plugin only uses three surfaces — `register` + `pre-execute` + `approval` — so the drift radius is small and upgrade calibration costs ≈ half a day.
2. **Maintainability of vendor/cordis**. cordis is vendored into dsh as source (`@deepseek-ai/cordis`, with 18 local patches recorded in `vendor/README.md`, including fiber lifecycle hardening and transactional Include — **dsh-private fixes**) — the upstream cordiverse/cordis and dsh's fork have already diverged. We should never bypass dsh and use cordis directly; the tracking policy is to follow only dsh release tags, not the cordis upstream.
3. **Impact on the "pure stdlib deployment" route**. The admin side goes from "python3 is enough" to "python3 + Node 22.19+/24 + npx pulling the dsh runtime". **Draw the boundary clearly**: the content service (serve.py) stays pure stdlib and unchanged; Node is only a console dependency on the administrator/agent machine and does not enter the server deployment path; environments without Node fall back to `admin.py chat` (functionally equivalent, minus the WebUI and the approval UI). The 81M is the size of the source repository; running only needs the release package installed by npx (its size was not measured; record it at the first smoke test).
4. **Approval ≠ the complete form of §12.2-③**. dsh approval is a one-off grant for a single local user (no allow-always, no persisted approval queue, no TOTP; the "known limitations" section of `packages/interaction/user-approval/README.zh.md`, read directly from the source, lists them item by item). When admin moves to a server in the future (migration steps ②③), the server-side approval queue for two-phase commit still has to be self-built, with the dsh layer serving as "local confirmation".
5. **Security face of dynamic plugins**. `cordis_define/cordis_run` are characterized by the project itself as "not a security boundary". The default profile **does not include** it (it needs an explicit `--patch` mount, see `examples/web-cordis/cordis.yml`), so simply not mounting it is enough; but be aware that dsh's default tool face includes bash and file writes, so an admin session's workspace should be limited to the suyou repo and the permission mode kept at `workspace-write + ask` (the factory default).
6. **The process model of spawning python**. Every tool call forks a python process (~hundreds of milliseconds), which is imperceptible for second-scale tools like QC; if high-frequency small calls appear in the future, add an HTTP backend inside the same plugin (hitting `/api/admin/call`, i.e. route B's capability) as a config switch — the skeleton is already written so that "py() is the single exit", giving exactly one switch point.
7. **TCC/permission environment pitfalls**. On macOS, a dsh process accessing a repo under `~/Documents` triggers the system's Documents-folder authorization (the same TCC prompt as the app hot-update layer); click Allow once by hand on the first run.

---

## 6. Source annotations for the conclusions

**Read directly from source** (file paths, inside the deepseek-harness repo):
- `packages/bundle/base/cordis.patch.yml` — the full set of foundation plugins, the default approval/permission/sandbox policies, how the DeepSeek adapter is mounted, and the credentials seam comments
- `apps/cli/src/plugin.ts` — `dsh plugin` = a pnpm forwarder + bundle declarations automatically entering a layer
- `apps/cli/README.md` — profile directory structure, the four-layer patch stacking order, `--dump-config`
- `vendor/loader/src/internal.ts` + `vendor/README.md` — native TS loading on Node 22/24 (the basis for mounting .ts plugins directly), the vendor sync process and the 18 local patches
- `examples/web-cordis/cordis.yml`, `examples/jsonrpc-agent/minimal.cordis.yml` — real samples of a patch overlay and a minimal composition

**Read directly from docs** (docs/ and package READMEs, zh versions): `docs/architecture.zh.md` (turn flow / event three domains / capability seams / extension-point mapping table), `docs/cordis-primer.zh.md` (the five core concepts / waterfall semantics), `docs/cookbook/adding-a-tool.zh.md` (defineTool conventions, raw JSON Schema tools, the pre-execute policy point), `docs/user/develop/basic/index.zh.md`+`tool.zh.md` (minimal plugin and absolute-path mounting tutorial), `packages/extensions/tool-cordis/README.zh.md` (the five cordis_* tools and the trust stance), `packages/llm/llm-deepseek/README.zh.md` (BYOK / settings hot update / credentials seam), `packages/interaction/user-approval/README.zh.md` (approval seam capabilities and limits), `packages/bundle/headless/README.zh.md` (the headless one-shot runner), `docs/subsystems/persistence.zh.md` (session log backend / crash recovery / format version stance), `docs/user/guide/python-sdk.zh.md` (Python SDK and the macOS arm64 support matrix), `docs/user/guide/index.zh.md` (Web UI usage flow).

**Not measured** (marked in this document as inference, to be verified at the first smoke test): the size and startup cost of the npx release package; the exact TS signature for raw JSON Schema registration; the request fields of `ctx.approval.request`; the combined behavior of `--patch` and the fail-closed approval under the headless profile.

## Related documents

- Platform Architecture Design (§12 admin; this document is its landing) — that document is not in this repository
- [Ticket Workflow Console Design](../design/ticket-workflow-console-design.md) (practice reference: multi-role collaboration)
- [Knowledge Base Design](../design/knowledge-base-design.md) (practice reference: the knowledge-base plugin carrier)
