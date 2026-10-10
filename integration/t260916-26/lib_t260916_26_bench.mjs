// lib_t260916_26_bench.mjs —— t260916-26 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 复制来源与漂移责任（t260907-08 先例：跨票复制扫描器，漂移责任=两侧头注对齐）：
// 本文件 boot 骨架逐行复制自 integration/t260904-17/lib_fix17.mjs 的
// buildProfile / waitReady / benchEnv / bootConsole（260916 快照），唯一实质差异=
// buildProfile 的插件覆盖面：lib_fix17 只把 sandbar-workbench 覆盖到泳道树，
// 其余四链 realpath 回**主树**——而本票被测对象是 sandbar-knowledge /
// sandbar-providers 的**泳道 lib bundle**，走 lib_fix17 原样会把主树旧产物喂给
// 隔离台（KI-052「盘上×别树」同族假绿，t260906-01 根除的错树形态）。故本文件把
// 覆盖面扩成三插件（workbench/knowledge/providers）全部指向本泳道，并在回执里带
// 三条 realpath 供场景做「锚=泳道树」防错树断言（t260915-19 选 bootConsole 通道
// 的同一理由：docker 供给台在本环境不可得，260916 实录）。
// 其余语义零改动：DSH_HOME 桩、死端口 Temporal（SANDBAR_TARGET_HOST=127.0.0.1:1，
// 勿用 17233——那是供给台实占端口，260910 实锤）、票源走 FIX17 桩、随机高端口
// （freePort 拒 3099=红线零接触）、四路径回收。lib_fix17 侧若改 boot 骨架，本票
// 场景的回归面=「boot 失败=ENV_FAIL 点名」，不会假绿。
// t261009-73: boot failures are attributable. Every failure path of
// bootLaneConsole (readiness timeout included) carries a bounded log tail in the
// message plus a survivor copy OUTSIDE the reclaimed tmpHome, by reusing
// lib_fix17.captureBootFailure directly (no local wrapper — one behaviour, one
// place). Error text reuses the fix17 template verbatim (source: lib_fix17.mjs
// bootFailureError + bootConsole catch), including the "log preserved at"
// dedupe marker. A boot failure stays env-red; the 45 s timeout is unchanged.
// Family receipt: integration/t261009-73/family-sweep.md.
import { captureBootFailure } from '../t260904-17/lib_fix17.mjs';
import { spawn } from 'node:child_process';
import {
  mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync, openSync, closeSync,
  readdirSync, realpathSync, symlinkSync, unlinkSync,
} from 'node:fs';
import { copyFile, mkdir, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { REPO_ROOT, mainRoot, freePort } from '../t260904-17/lib_fix17.mjs';

const DEAD_TEMPORAL = '127.0.0.1:1'; // 死端口兜底红线（与 lib_fix17 同款，理由见其头注）

// 本票覆盖到泳道树的三插件（装载面=沙bar 工单台壳 + 本票两个被测 entry）。
const LANE_OVERRIDES = ['sandbar-workbench', 'sandbar-knowledge', 'sandbar-providers'];

async function buildLaneProfile(tmpHome) {
  const laneProfile = path.join(REPO_ROOT, 'server', 'profile');
  const mainProfileNm = path.join(mainRoot(), 'server', 'profile', 'node_modules');
  const profDir = path.join(tmpHome, 'profiles', 'suyou');
  await mkdir(profDir, { recursive: true });
  for (const f of ['cordis.yml', 'cordis.patch.yml', 'package.json']) {
    const src = path.join(laneProfile, f);
    if (existsSync(src)) await copyFile(src, path.join(profDir, f));
  }
  const tsTools = path.join(laneProfile, 'sandbar-tools.ts');
  if (existsSync(tsTools)) await symlink(tsTools, path.join(profDir, 'sandbar-tools.ts'));
  const nm = path.join(profDir, 'node_modules');
  await mkdir(nm, { recursive: true });
  if (!existsSync(mainProfileNm)) {
    throw new Error(`主树插件依赖缺失：${mainProfileNm} 不存在（env FIX17_MAIN_ROOT 可指主树根）`);
  }
  const laneAnchors = {};
  let overCount = 0;
  for (const name of readdirSync(mainProfileNm)) {
    const dest = LANE_OVERRIDES.includes(name)
      ? path.join(REPO_ROOT, 'server', 'plugins', name.replace('sandbar-', ''))
      : (() => { try { return realpathSync(path.join(mainProfileNm, name)); } catch { return null; } })();
    if (!dest) continue;
    if (LANE_OVERRIDES.includes(name)) {
      if (!existsSync(dest)) {
        throw new Error(`泳道插件目录缺失：${dest}（被测实现未落地态，env 红点名）`);
      }
      laneAnchors[name] = realpathSync(dest);
      overCount++;
    }
    await symlink(dest, path.join(nm, name));
  }
  if (overCount !== LANE_OVERRIDES.length) {
    throw new Error(`主树 profile/node_modules 缺覆盖链：仅 ${overCount}/${LANE_OVERRIDES.length}（${LANE_OVERRIDES.join(',')}）`);
  }
  return { profDir, laneAnchors };
}

// t261009-73: readiness timeout carries evidence instead of naming a log the
// caller's reclamation deletes. Template strings match lib_fix17.bootFailureError
// verbatim so the evidence phrase stays one contract across both faces.
// Exported for the contract face (integration/tests/test_t26100916_26_boot_evidence.mjs,
// same discipline as lib_fix17.waitReady): the timeout-under-test is injected short.
export async function waitReady(port, timeoutMs, logPath) {
  const url = `http://127.0.0.1:${port}/sandbar-workbench/api/wf/projects`;
  const t0 = Date.now();
  for (;;) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (r.ok) return;
    } catch { /* 未就绪，续等 */ }
    if (Date.now() - t0 > timeoutMs) {
      const { survivor, tail } = captureBootFailure(logPath, 't26091626-boot');
      throw new Error(
        `stage console not ready in ${Math.round(timeoutMs / 1000)}s (env red — boot failure, not a scenario fail); `
        + `log tail: ${JSON.stringify(tail)}; full log preserved at: ${survivor || '(copy failed or log empty)'}`,
      );
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

/**
 * t261009-73 (exported for tests and the gate scenario sc_t26091626_boot_evidence.mjs
 * — pure append-and-annotate, no state): attach boot-failure evidence to `err`
 * BEFORE the caller reclaims tmpHome. A missing/unreadable log still annotates —
 * captureBootFailure degrades to a named absence, never a fabricated line. Skips
 * only when the error already carries its own snapshot (the "log preserved at"
 * dedupe marker, same as lib_fix17.bootConsole). Evidence attachment must never
 * mask the original failure, so the whole append is try/caught.
 */
export function attachBootEvidence(err, logPath, label) {
  try {
    if (err instanceof Error && String(err.message).includes('log preserved at')) return err;
    if (err instanceof Error && String(err.message).includes('log preserved at')) return err;
    const { survivor, tail } = captureBootFailure(logPath, label);
    const note = `boot failure evidence — log tail: ${JSON.stringify(tail)}; full log preserved at: ${survivor || '(copy failed)'}`;
    if (err instanceof Error) err.message += `\n${note}`;
    else throw new Error(`${String(err)}\n${note}`);
  } catch { /* never mask the original failure */ }
  return err;
}

function benchEnv(tmpHome, projectsRoot, stub) {
  const env = { ...process.env, DSH_HOME: tmpHome, SANDBAR_PROJECTS_DIR: projectsRoot };
  delete env.SANDBAR_PROJECTS_YAML;
  env.SANDBAR_TARGET_HOST = DEAD_TEMPORAL;
  delete env.SANDBAR_NAMESPACE;
  env.FIX17_CTRL = stub.ctrlPath;
  env.FIX17_TRACE = stub.tracePath;
  // 引擎通道夹具仓（与 lib_fix17 同款：python venv shim 拦 ticket-list，拦截面外炸得响）
  const engineRepo = path.join(stub.dir, 'engine-repo');
  const venvBin = path.join(engineRepo, 'server', 'engine', '.venv', 'bin');
  mkdirSync(venvBin, { recursive: true });
  writeFileSync(path.join(engineRepo, 'server', 'engine', 'client.py'),
    '# fix17 夹具占位：引擎通道由 FIX17 桩按 argv 拦截（ticket-list）；拦截面外到此=桩缺口\n');
  try { unlinkSync(path.join(venvBin, 'python')); } catch { /* 首次无 */ }
  symlinkSync(path.join(stub.dir, 'python3'), path.join(venvBin, 'python'));
  // repo 其余可读面投影（docs|notes 只读软链回真树，同 lib_fix17）
  for (const face of ['docs', 'notes']) {
    const dest = path.join(engineRepo, face);
    try { unlinkSync(dest); } catch { /* 首次无 */ }
    symlinkSync(path.join(REPO_ROOT, face), dest);
  }
  env.SANDBAR_REPO = engineRepo;
  env.PATH = `${stub.dir}:${process.env.PATH || ''}`;
  return env;
}

/** 自举隔离台（三插件覆盖泳道树版）。失败抛错由调用方转环境红（env_fail 点名）。 */
export async function bootLaneConsole(projectsRoot, stub) {
  const tmpHome = mkdtempSync(path.join(tmpdir(), 't26091626-bench-'));
  const clean = () => { try { rmSync(tmpHome, { recursive: true, force: true }); } catch { /* 留警告 */ } };
  try {
    const { laneAnchors } = await buildLaneProfile(tmpHome);
    const port = await freePort();
    if (port === 3099) throw new Error('freePort 撞 3099（概率≈0，命中即拒跑）');
    const patchFile = path.join(tmpHome, 'port.patch.yml');
    writeFileSync(patchFile, `- id: webserver\n  config:\n    host: 127.0.0.1\n    port: ${port}\n`);
    const logFd = openSync(path.join(tmpHome, 'console.log'), 'a');
    const proc = spawn('dsh', ['--profile', 'suyou', '--patch', patchFile,
      '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
      cwd: REPO_ROOT, detached: true, stdio: ['ignore', logFd, logFd],
      env: benchEnv(tmpHome, projectsRoot, stub),
    });
    await waitReady(port, 45000, path.join(tmpHome, 'console.log'));
    return {
      port, tmpHome, projectsRoot, proc, logFd, clean, laneAnchors,
      base: `http://127.0.0.1:${port}`,
      teardown() {
        if (proc.pid && proc.exitCode === null && proc.signalCode === null) {
          try { process.kill(-proc.pid, 'SIGTERM'); } catch { try { proc.kill('SIGKILL'); } catch { /* 已退 */ } }
        }
        try { closeSync(logFd); } catch { /* 已关 */ }
        clean();
      },
    };
  } catch (e) {
    // t261009-73: evidence before reclamation, for every failure path (profile
    // build, freePort, spawn, readiness timeout) — not just waitReady. A boot
    // that failed before any log exists rejects named with nothing quoted (the
    // gate scenario's F case), so the annotation only runs when a log exists.
    const logPath = path.join(tmpHome, 'console.log');
    if (existsSync(logPath)) attachBootEvidence(e, logPath,
      `bootfail-${path.basename(String(projectsRoot))}`);
    clean();
    throw e;
  }
}
