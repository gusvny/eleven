/**
 * KI-046 回归：charter 注入的 prompt 调用形状 + RpcResult 检查（t260904-11）。
 *
 * 事故（t260904-07）：injectSessionCharter 把裸字符串传给平台
 * `ISession.prompt(content: PromptContentPart[], mode)` → apiproxy zod 拒收
 * `invalid payload for session prompt`；且平台业务失败**不 throw 只返回
 * RpcResult{ok:false}**，票内 catch 兜底永不触发，错误只经 toast 直达用户。
 *
 * 本用例两层防线：
 *   A 组（行为级 mock——07 票缺失的「最便宜防线」）：真加载 session-entry 模块
 *       （node 剥离类型直跑，零 JSX），桩注入 SessionsFace 捕获 prompt 实参，
 *       断言分片数组形状（对照仓内冻结镜像契约）、ok=false/throw/畸形输入全路径
 *       就地消化不冒泡。外部输入用例全部用桩/固定字面量复现，不依赖真外部源。
 *   B 组（三方一致锚）：src 与 lib/client.js、lib/client.cjs 的调用形状串一致
 *       且恰一次——防「改 src 没重建 bundle」（rework-banner-ui.mjs 同款守卫）。
 *
 * 自包含：harness 在 mkdtemp 内自铸最小 react 桩包（只满足模块顶层 import，
 * 不触 hooks 本体），不依赖 /tmp/wb-deps 或任何仓外供给。
 */

import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pathToFileURL } from 'node:url'
// 注入标记同源常量（t260905-04：A1 精确值断言与 src 内拼装串同源，不重写字面量）。
import { CHARTER_MARKER } from '../src/host/session-charter.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const WB = join(HERE, '..')
const REPO = join(WB, '..', '..', '..')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ── 仓内冻结镜像契约（真源：@deepseek-ai/dsh-host-apiproxy sessionPromptRequestSchema
      + dsh-client-runtime ISession.prompt 签名；两处均不可从浏览器包 import，故冻结
      镜像并声明同步责任：平台契约变更时本常量与 A1 断言同批更新）。── */
const WIRE_CONTRACT = {
  content: { kind: 'array', partTypes: ['text', 'image'] },
  textPart: { type: 'text' /* + text: string */ },
  modes: ['queue', 'steer'],
}

/* ── harness：自包含 mkdtemp + 最小 react 桩包 ── */
const tmp = mkdtempSync(join(tmpdir(), 'ki046-'))
try {
  const nm = join(tmp, 'node_modules', 'react')
  mkdirSync(nm, { recursive: true })
  // 桩只满足模块顶层 import（session-entry 不触 JSX/hook 本体；hooks 被调用即视为误用）
  writeFileSync(join(nm, 'package.json'), JSON.stringify({ name: 'react', type: 'module', main: 'index.js' }))
  writeFileSync(join(nm, 'index.js'), `export const useCallback = () => { throw new Error('react 桩误用: useCallback') }
export const useEffect = () => { throw new Error('react 桩误用: useEffect') }
export const useState = () => { throw new Error('react 桩误用: useState') }
export const useSyncExternalStore = () => { throw new Error('react 桩误用: useSyncExternalStore') }
export default {}\n`)

  const cp = (rel, toRel = rel.replace(/\.tsx$/, '.ts')) => {
    mkdirSync(dirname(join(tmp, toRel)), { recursive: true })
    copyFileSync(join(WB, rel), join(tmp, toRel))
  }
  cp('src/client/session-entry.tsx')
  cp('src/client/session-ledger-store.ts')
  cp('src/client/closed-ledger-store.ts')
  cp('src/shared/sessions.ts')
  // 260923：session-entry.tsx 新增「启动面双版解析」依赖（workspaces-compat），
  // 本夹具按文件清单拷贝，漏拷即 ERR_MODULE_NOT_FOUND——新增模块必须同步登记。
  cp('src/shared/workspaces-compat.ts')
  cp('src/host/session-charter.ts')

  const mod = await import(pathToFileURL(join(tmp, 'src/client/session-entry.ts')).href)
  ok(typeof mod.injectSessionCharter === 'function', 'harness：injectSessionCharter 可达（已导出）')

  /* ── 桩件 ── */
  function makeStubs({ blank = true, sessionOf, promptImpl }) {
    const calls = []
    const session = {
      prompt: (content, mode) => {
        calls.push({ content, mode })
        return promptImpl(content, mode)
      },
    }
    const face = {
      open() {},
      scope: (id) => ({ __scope: id }),
      sessionOf,
      list: {
        getSnapshot: () => ({ byId: { s1: { blank } }, current: null }),
        subscribe: () => () => {},
      },
      __session: session,
      __calls: calls,
    }
    return face
  }
  function withEnv(face, { fetchImpl, charterBody }, fn) {
    const errors = [], infos = [], notices = []
    const origError = console.error, origInfo = console.info, origFetch = globalThis.fetch
    console.error = (...a) => errors.push(a)
    console.info = (...a) => infos.push(a)
    globalThis.fetch = fetchImpl
    return Promise.resolve(fn(face)).then(
      (r) => {
        console.error = origError; console.info = origInfo; globalThis.fetch = origFetch
        return { errors, infos, notices, r }
      },
      (e) => {
        console.error = origError; console.info = origInfo; globalThis.fetch = origFetch
        return { errors, infos, notices, threw: e }
      },
    )
  }
  const okFetch = (body) => async () => ({ ok: true, status: 200, text: async () => JSON.stringify(body) })
  const faceWithPrompt = (face, promptImpl) => { face.sessionOf = () => face.__session; face.__session.prompt = promptImpl; return face }

  /* ── A1 调用形状：恰一次 + 分片数组 + queue 模式 ── */
  section('A1 调用形状（KI-046 根因）')
  {
    const face = makeStubs({ blank: true, promptImpl: () => ({ ok: true, value: { accepted: true } }) })
    face.sessionOf = () => face.__session
    const { notices, threw } = await withEnv(face, { fetchImpl: okFetch({ charter: 'CT-文本' }) },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t, p) => {}))
    ok(threw === undefined, 'A1 成功路径不抛')
    ok(notices.length === 0, 'A1 成功路径零 notify')
    ok(face.__calls.length === 1, 'A1 prompt 恰一次调用')
    const c = face.__calls[0]
    ok(Array.isArray(c.content), 'A1 content 是分片数组（镜像契约 content.kind=array）——裸字符串即 07 事故复现')
    // t260905-04：注入文本首行拼 CHARTER_MARKER（渲染端折叠件触发器，同源常量）。
    // 精确值口径不缩水（review C4）：全串相等，非 includes。
    ok(c.content.length === 1 && c.content[0]?.type === 'text' && c.content[0]?.text === `${CHARTER_MARKER}\nCT-文本`,
      `A1 text 分片 {type:'text',text:CHARTER_MARKER+'\\n'+charter}（镜像契约 partTypes 含 text）`)
    ok(c.mode === 'queue', 'A1 mode=queue（镜像契约 modes）')
    ok(WIRE_CONTRACT.modes.includes(c.mode), 'A1 mode 落在冻结镜像契约 closed set 内')
  }

  /* ── A2 RpcResult{ok:false}：平台业务失败不 throw，必须显式检查 ── */
  section('A2 result.ok=false 检查（07 票静默失效的放大器）')
  {
    const face = makeStubs({ blank: true, promptImpl: () => ({ ok: false, error: { code: 'bad-request', message: 'invalid payload for session prompt', details: {} } }) })
    face.sessionOf = () => face.__session
    const notices = []
    const { errors, threw } = await withEnv(face, { fetchImpl: okFetch({ charter: 'CT' }) },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t, p) => notices.push({ t, p })))
    ok(threw === undefined, 'A2 不向上冒泡（就地消化，会话创建不受影响）')
    ok(face.__calls.length === 1, 'A2 prompt 恰一次')
    ok(notices.length === 1, 'A2 ok=false → notify 恰一次（用户可见留痕）')
    ok(errors.length === 1, 'A2 ok=false → console.error 留痕')
    // console.error 的第三实参是 Error，取 message 归因（JSON.stringify(Error) 是空壳）
    const errText = errors.flat().map((a) => (a instanceof Error ? a.message : String(a))).join(' ')
    ok(errText.includes('bad-request'), 'A2 留痕含平台错误 code（可归因）')
  }

  /* ── A3 prompt 直接失败：同步 throw + rejected promise 两变体 ── */
  section('A3 prompt throw / rejected（传输层路径）')
  for (const [label, impl] of [
    ['同步 throw', () => { throw new Error('transport down') }],
    ['rejected promise', () => Promise.reject(new Error('transport down'))],
  ]) {
    const face = makeStubs({ blank: true, promptImpl: impl })
    face.sessionOf = () => face.__session
    const notices = []
    const { errors, threw } = await withEnv(face, { fetchImpl: okFetch({ charter: 'CT' }) },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t, p) => notices.push(t)))
    ok(threw === undefined, `A3[${label}] 不向上冒泡`)
    ok(notices.length === 1 && errors.length === 1, `A3[${label}] notify + console.error 各一次`)
  }

  /* ── A4 畸形输入（桩固定字面量复现，不依赖真外部源） ── */
  section('A4 fetch 侧畸形输入 → 零 prompt、notify 就地')
  for (const [label, fetchImpl] of [
    ['HTTP 500', async () => ({ ok: false, status: 500, text: async () => '' })],
    ['响应非 JSON', async () => ({ ok: true, status: 200, text: async () => '<html>bad</html>' })],
    ['charter 字段缺失', okFetch({})],
    ['charter 非字符串（数字）', okFetch({ charter: 42 })],
    ['charter 空串', okFetch({ charter: '' })],
    ['charter 纯空白', okFetch({ charter: '   \n ' })],
  ]) {
    const face = makeStubs({ blank: true, promptImpl: () => ({ ok: true, value: { accepted: true } }) })
    face.sessionOf = () => face.__session
    const notices = []
    const { threw } = await withEnv(face, { fetchImpl },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t) => notices.push(t)))
    ok(threw === undefined, `A4[${label}] 不冒泡`)
    ok(face.__calls.length === 0, `A4[${label}] prompt 零调用（畸形输入不进平台）`)
    ok(notices.length === 1, `A4[${label}] notify 恰一次`)
  }

  /* ── A5 守卫：非 blank（入口守卫 + TOCTOU 抢先两变体）/ sessionOf 缺失 ── */
  section('A5 注入守卫')
  {
    // 变体1：入口即非 blank → 函数在 fetch 之前就静默返回（零 fetch、零提示）
    const face = makeStubs({ blank: false, promptImpl: () => ({ ok: true, value: { accepted: true } }) })
    face.sessionOf = () => face.__session
    const notices = []
    const { infos } = await withEnv(face, { fetchImpl: okFetch({ charter: 'CT' }) },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t) => notices.push(t)))
    ok(face.__calls.length === 0, 'A5 非 blank（入口守卫）→ prompt 零调用')
    ok(notices.length === 0 && infos.length === 0, 'A5 非 blank（入口守卫）→ 全静默返回')
  }
  {
    // 变体2：TOCTOU——fetch 往返期间用户抢先发首条（blank 翻转）→ console.info 跳过
    const state = { blank: true }
    const face = makeStubs({ blank: true, promptImpl: () => ({ ok: true, value: { accepted: true } }) })
    face.list.getSnapshot = () => ({ byId: { s1: { blank: state.blank } }, current: null })
    face.sessionOf = () => face.__session
    const notices = []
    const flippingFetch = async () => { state.blank = false; return { ok: true, status: 200, text: async () => JSON.stringify({ charter: 'CT' }) } }
    const { infos } = await withEnv(face, { fetchImpl: flippingFetch },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t) => notices.push(t)))
    ok(face.__calls.length === 0, 'A5 TOCTOU 抢先 → prompt 零调用')
    ok(notices.length === 0 && infos.length === 1, 'A5 TOCTOU 抢先 → console.info 静默跳过（不提示噪音）')
  }
  {
    const face = makeStubs({ blank: true, promptImpl: () => ({ ok: true, value: { accepted: true } }) })
    face.sessionOf = undefined
    const notices = []
    const { errors } = await withEnv(face, { fetchImpl: okFetch({ charter: 'CT' }) },
      () => mod.injectSessionCharter(face, 's1', 'sandbar', (t) => notices.push(t)))
    ok(face.__calls.length === 0, 'A5 sessionOf 缺失 → prompt 零调用')
    ok(notices.length === 1 && errors.length === 1, 'A5 sessionOf 缺失 → notify + error 留痕')
  }

  /* ── B 组：三方一致锚（src / lib/client.js / lib/client.cjs）── */
  section('B 三方一致锚（改 src 必须重建 bundle）')
  const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/[^\n]*/g, '$1 ')
  const NEW_SHAPE = /\.prompt\(\s*\[\s*\{\s*type:\s*["']text["']\s*,\s*text:\s*`\$\{CHARTER_MARKER\}\\n\$\{charter\}`\s*\}\s*\]\s*,\s*["']queue["']\s*\)/
  // 宽松锚说明（review 意见3）：bundle 侧打包器会把 `session.` 内联为
  // `sessions.sessionOf(...)` 的链尾，前缀不保证是 `session.prompt(`——锚定
  // `.prompt([{type:'text',text:`${CHARTER_MARKER}\n${charter}`}],'queue')` 全形状
  // （marker 前缀已把断言面钉死在注入调用上，t260905-04），禁止反向改 src 迁就锚。
  const OLD_SHAPE = /\.prompt\(\s*charter\s*,\s*["']queue["']\s*\)/
  for (const rel of ['src/client/session-entry.tsx', 'lib/client.js', 'lib/client.cjs']) {
    const code = stripComments(await import('node:fs').then((fs) => fs.readFileSync(join(WB, rel), 'utf8')))
    const news = code.match(new RegExp(NEW_SHAPE.source, 'g')) ?? []
    const olds = code.match(new RegExp(OLD_SHAPE.source, 'g')) ?? []
    ok(news.length === 1, `B[${rel}] 分片数组调用形状恰一次`)
    ok(olds.length === 0, `B[${rel}] 裸字符串旧形状零残留`)
    ok(/result\?\.ok|!\s*result\?\.ok/.test(code), `B[${rel}] result.ok 检查在场（业务失败不 throw）`)
  }
  /* ── B 扩锚（t260905-04，方案步 4 / review C3）：context-fold 三方一致锚 ──
     新增装饰器文件 ki046 现锚管不到——src 与两份 bundle 同含 startContextFoldEffect
     接线串且各恰一次，防「改 src 没重建 bundle」在新文件上复犯（rework-banner-ui 先例）。 */
  for (const rel of ['src/client/context-fold.ts', 'src/client/sidebar.tsx', 'lib/client.js', 'lib/client.cjs']) {
    const code = stripComments(await import('node:fs').then((fs) => fs.readFileSync(join(WB, rel), 'utf8')))
    const hits = code.match(/startContextFoldEffect/g) ?? []
    ok(hits.length >= 1, `B扩[${rel}] startContextFoldEffect 在场（t260905-04 折叠件）`)
  }
} finally {
  rmSync(tmp, { recursive: true, force: true })
}

console.log(`\n${pass} pass, ${fail} fail`)
process.exit(fail === 0 ? 0 : 1)
