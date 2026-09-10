// lib_transient_retry.mjs — 瞬态故障判定的 mjs 薄包装（t260910-12 目标④，review R9）。
//
// 单一真源纪律：分类白名单只有 integration/lib_transient_retry.py 一份；
// 本文件只是 spawnSync 到 `is-transient` 子命令的桥（仅失败路径一次子进程，
// 成本可忽略），绝不复制正则——两份逻辑必漂移，且漂移发生过
// （stage_docker.mjs 头注原话）。
//
// 场景用法：
//   import { retryTransientOnce } from '../lib_transient_retry.mjs';
//   const page = await retryTransientOnce(() => openPage(base));  // 502/拒连 自动重试一次
// 重试仍红=原样抛出（文案逐字节保留），绝不吞错。
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PY_LIB = path.join(HERE, 'lib_transient_retry.py');

/** 判定一条错误文案是否瞬态（白名单在 py 侧，本函数只搬运）。畸形输入
 * （null/对象/空串）按 py 侧契约落 fatal 侧。 */
export function isTransient(message) {
  const p = spawnSync('python3', [PY_LIB, 'is-transient'],
    { input: String(message ?? ''), encoding: 'utf8', timeout: 15000 });
  if (p.error || p.status === null) return false;   // 分类器自身失败 → fatal 侧倒
  return p.status === 0;
}

/** 跑 fn 一次；命中白名单的异常自动重试一次（默认隔 2s），仍红原样抛出。
 * fn 允许 async。非瞬态异常不重试不吞。 */
export async function retryTransientOnce(fn, { sleepMs = 2000 } = {}) {
  try {
    return await fn();
  } catch (e) {
    const text = String((e && e.message) ?? e);
    if (!isTransient(text)) throw e;
    await new Promise((resolve) => setTimeout(resolve, sleepMs));
    return await fn();
  }
}
