// lib_pw_deps.mjs —— 浏览器场景 playwright-core 依赖解析唯一真源（t260912-01 缺陷③）。
// 非 sc_ 前缀 = 共享代码，不进 SCENARIOS（run_scenarios 约定，lint L5 不登记）。
//
// 背景（t260912-01 病灶）：旧三路探测（SANDBAR_PLAYWRIGHT_PATH → 裸导入 →
// `../../server/ui-check/...` 位置算术）在 worktree 不位于 <主仓>/.lane/<票>/ 布局时
// 第三路指错目录（宿主 260912 副本开在 /private/tmp → ../.. 指 /private），依赖
// 在盘可用仍恒报「playwright-core unavailable」——把布局算错说成依赖缺失，掩盖
// 测试自身缺陷。本 lib 统一为位置无关口径：主树经 git-common-dir 解析。
//
// 参考实现故障模式取舍清单（review K1 必做项；参照
// t260904-17/lib_fix17.mjs:220-229 mainRoot() / :312-322 loadPlaywright() 与
// t260904-05/lib_browser.mjs:54-67 同语义实现，逐项声明带过来/不带 + 理由）：
//   1. env 覆盖主树根 —— 带（FIX17_MAIN_ROOT → 中性名 SANDBAR_MAIN_ROOT；
//      理由：git 布局不可解析时的唯一逃生门，测试不得自锁死路）。
//   2. git 缺席/非仓/非 worktree → 回落本树根 —— 带（同款；单仓检出场景下本树
//      即主树，回落语义正确）。
//   3. git-common-dir 解析成功性检查（status===0 且输出非空才采信）—— 带
//      （防把报错文本当路径）。
//   4. 主树候选存在性检查（existsSync 才入列）—— 带（缺席即跳过该路，不产生
//      永远失败的假候选）。
//   5. 逐候选 import 失败即试下一路、全失败返 null 由调用方记 env_fail
//      （不抛不吞——探测失败是环境事实不是断言错）—— 带。
//   6. 不带：lib_fix17 的 FIX17_* 专用常量与其调用侧业务（只取解析语义）。
// 新增面（非照搬，本票新增）：
//   A. 旧 env 名 SANDBAR_PLAYWRIGHT_MODULE 双认（review C3：server/ui-check/
//      capture.mjs、capture-lane.mjs、bench-shot.mjs、sc_capture_redline_gate.mjs
//      等下游仍消费该名，全仓无 MODULE→PATH 桥 setter，只认新名=静默砍通路）；
//      同设时 SANDBAR_PLAYWRIGHT_PATH 优先（新名优先级高，旧名兜底同语义）。
//   B. pwProbeFaces() / pwMissingDetail() 事实文案面：探测失败点名全部候选面与
//      实路径，不做「依赖缺失/沙箱外安装」式归因（归因必须指向事实）。
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

// 泳道/仓根（本文件位置的父一——lib 固定落 <仓根>/integration/ 下；位置无关；
// 合法形态，勿与主树位置算术混淆）。
export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// 主树根：git-common-dir 的 dirname（worktree → 主仓；单仓检出 → 同目录）。
// env SANDBAR_MAIN_ROOT 显式覆盖（取舍清单 #1）；git 缺席/非仓回落本树根（#2）。
export function mainRoot() {
  if (process.env.SANDBAR_MAIN_ROOT) return process.env.SANDBAR_MAIN_ROOT;
  try {
    const r = spawnSync('git', ['-C', REPO_ROOT, 'rev-parse', '--path-format=absolute',
      '--git-common-dir'], { encoding: 'utf8' });
    const dir = (r.stdout || '').trim();
    if (r.status === 0 && dir) return path.dirname(dir);   // 取舍清单 #3：成功性检查
  } catch { /* git 不可执行 → 回落 */ }
  return REPO_ROOT;
}

// 本树候选（相对本文件位置，位置无关）。
const LOCAL_PW = new URL('../server/ui-check/node_modules/playwright-core/index.mjs',
  import.meta.url).href;

function mainPwPath() {
  return path.join(mainRoot(), 'server', 'ui-check', 'node_modules', 'playwright-core',
    'index.mjs');
}

// 全部候选面的事实描述（探测失败文案点名用——B 新增面）。
export function pwProbeFaces() {
  const mainPw = mainPwPath();
  return [
    `env SANDBAR_PLAYWRIGHT_PATH=${process.env.SANDBAR_PLAYWRIGHT_PATH || '(未设)'}`,
    `env SANDBAR_PLAYWRIGHT_MODULE=${process.env.SANDBAR_PLAYWRIGHT_MODULE || '(未设)'}`,
    "裸导入 'playwright-core'",
    `本树 ${LOCAL_PW}`,
    `主树 ${mainPw}${existsSync(mainPw) ? '' : '（不存在）'}`,
  ];
}

// 探测全空时的事实文案（无归因话术——调用方直接用作 env_fail detail）。
export function pwMissingDetail() {
  return 'playwright-core 五路候选均未探得（探测面：' + pwProbeFaces().join('；') + '）';
}

// 逐候选试装（取舍清单 #5）：失败即下一路，全空返 null 由调用方记 env_fail。
// 候选顺序：新名 env → 旧名 env（双认，C3）→ 裸导入 → 本树 → 主树（existsSync 才入列，#4）。
export async function loadPlaywright() {
  const mainPw = mainPwPath();
  for (const c of [process.env.SANDBAR_PLAYWRIGHT_PATH, process.env.SANDBAR_PLAYWRIGHT_MODULE,
    'playwright-core', LOCAL_PW, existsSync(mainPw) ? pathToFileURL(mainPw).href : null]) {
    if (!c) continue;
    try { return await import(c); } catch { /* next */ }
  }
  return null;
}
