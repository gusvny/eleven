#!/usr/bin/env node
// t261007-07 仲裁段诊断探针（非场景，不登记 SCENARIOS）：复刻 lib_fix17 bootConsole
// 的物化与起台，但**不清理**临时台，把 console.log 留在原地并打印 ERR 源文件——
// 用途=隔离台 console 起台即 ERR_INVALID_TYPESCRIPT_SYNTAX 的归因（工单 t261007-07）。
import { spawn, spawnSync } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, writeFileSync, existsSync, openSync, readFileSync,
  readdirSync, realpathSync, symlinkSync, rmSync,
} from 'node:fs';
import { copyFile, mkdir, symlink } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';

const REPO = process.cwd()

function mainRoot() {
  if (process.env.FIX17_MAIN_ROOT) return process.env.FIX17_MAIN_ROOT
  const r = spawnSync('git', ['-C', REPO, 'rev-parse', '--path-format=absolute', '--git-common-dir'], { encoding: 'utf8' })
  const dir = (r.stdout || '').trim()
  return dir ? path.dirname(dir) : REPO
}

const freePort = () => new Promise((res, rej) => {
  const s = createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)) }); s.on('error', rej)
})

const tmpHome = mkdtempSync(path.join(tmpdir(), 'arb7-probe-'))
const profDir = path.join(tmpHome, 'profiles', 'suyou')
await mkdir(profDir, { recursive: true })
const laneProfile = path.join(REPO, 'server', 'profile')
for (const f of ['cordis.yml', 'cordis.patch.yml', 'package.json']) {
  const src = path.join(laneProfile, f)
  if (existsSync(src)) await copyFile(src, path.join(profDir, f))
}
const tsTools = path.join(laneProfile, 'sandbar-tools.ts')
if (existsSync(tsTools)) await symlink(tsTools, path.join(profDir, 'sandbar-tools.ts'))
const nm = path.join(profDir, 'node_modules')
await mkdir(nm, { recursive: true })
const mainNm = path.join(mainRoot(), 'server', 'profile', 'node_modules')
for (const name of readdirSync(mainNm)) {
  const dest = name === 'sandbar-workbench' ? path.join(REPO, 'server', 'plugins', 'workbench')
    : (() => { try { return realpathSync(path.join(mainNm, name)) } catch { return null } })()
  if (!dest) continue
  await symlink(dest, path.join(nm, name))
}
const port = await freePort()
const patchFile = path.join(tmpHome, 'port.patch.yml')
writeFileSync(patchFile, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`)
const logPath = path.join(tmpHome, 'console.log')
const logFd = openSync(logPath, 'a')
const proc = spawn('dsh', ['--profile', 'suyou', '--patch', patchFile,
  '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
  cwd: REPO, detached: true, stdio: ['ignore', logFd, logFd],
  env: { ...process.env, DSH_HOME: tmpHome },
})
await new Promise((r) => setTimeout(r, 25000))
console.log('LOG_PATH=' + logPath)
const txt = readFileSync(logPath, 'utf8')
const i = txt.indexOf('ERR_INVALID')
console.log(i >= 0 ? txt.slice(Math.max(0, i - 3000), i + 200) : txt.slice(-1500))
try { process.kill(-proc.pid, 'SIGKILL') } catch { /* done */ }
// L8 回收纪律：日志原文已在上面打印，临时台就地拆除（要复跑再起，不留 $TMPDIR 债）。
try { rmSync(tmpHome, { recursive: true, force: true }) } catch { /* 兜底不抛 */ }
process.exit(0)
