// 失败分类协议 v1 发射器（mjs 侧，t260910-13）——与 integration/lib_result.py
// 同一契约：一行 JSON = 一个用例；写侧 fail-closed（not-checked 无 evidence 拒发、
// 词表外状态拒发）；evidence 机械一行化；attempt 缺省 1（闸/引擎侧可盖 rework
// 代数，不许双写者并存）。旧文本行暂保留作兼容期观测面（闸双解析期规范行权威）。

export function evidenceOneLine(text) {
  if (text === undefined || text === null) return '';
  return String(text).replace(/\\/g, '\\\\').replace(/\r/g, '').replace(/\n/g, '\\n');
}

const STATUSES = ['pass', 'fail', 'not-checked'];
const CAUSES = ['self', 'external', 'unknown'];

/** 构造规范行对象（校验失败抛 Error=写侧 fail-closed，不静默降级）。 */
export function specCase({ name, suite = '', status, cause = 'unknown',
                           reason = '', evidence = '', dur_s = null,
                           attempt = 1, started, git_sha, artifacts }) {
  if (!name || typeof name !== 'string') throw new Error('规范行缺 name，拒发');
  if (!STATUSES.includes(status)) throw new Error(`status=${status} 不在词表，拒发`);
  if (!CAUSES.includes(cause)) throw new Error(`cause=${cause} 不在词表，拒发`);
  const ev = evidenceOneLine(evidence);
  if (status === 'not-checked' && !ev.trim()) {
    throw new Error('not-checked 无 evidence 拒发（写侧 fail-closed，t260910-13）——把缺什么写进 evidence');
  }
  return {
    name, suite, status, cause, reason, dur_s,
    attempt: attempt ? Number(attempt) : 1,
    started: started || new Date().toISOString().slice(0, 19),
    git_sha: git_sha !== undefined ? git_sha : (globalThis.process?.env?.SANDBAR_GIT_SHA ?? ''),
    evidence: ev, artifacts: artifacts ?? [],
  };
}

/** 打印出口。 */
export function emitCase(kw) {
  console.log(JSON.stringify(specCase(kw)));
}
