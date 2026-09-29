/**
 * host-session-signals-bench 插件半（t260929-08 验收：三个真信号的真宿主内证）。
 *
 * 被真 dsh 宿主（bench 专用临时 profile）加载：拿**真的** ctx.sessionController，
 * 按 SANDBAR_BENCH_LEG 选子用例分支（progress / selflock / engine / all）证明——
 *   progress: 真 list().updatedAt 真推进；真 updatedAt 作锚 + 时钟拨过阈值 → 真 Watchdog
 *             实例产 stall alert；**反证分支**：同输入 deps 缺省（core 默认 advanced:null）
 *             → 恒 no_signal、无 stall alert（新锁对修复前接线必红）。
 *   selflock: 真 fs 请求账（orchestrator 给的临时 SANDBAR_PANEL_DIR）真追加 raised_by
 *             请求 → wired 实例下一拍 waiting_on_itself（不等超时）；**反证分支**：deps
 *             缺省（无 pendingProvider）恒 unknown、无自锁告警。
 *   engine:   SANDBAR_ENGINE_PORT 指向 orchestrator 自管监听口（零 7233/3099 接触）——
 *             端口开 + 看板读失败 → online=true 且**不**产 engine_down（假警报锁）；
 *             端口关 → offline。
 * 结果写 env 指定结果文件（JSON），每条断言独立记 pass/reason；反证分支判定经结构化
 * 通道回传（results.antiproof_ok）——**不得**在宿主子进程 stdout 打契约标记（宿主
 * stdio 被 orchestrator 重定向进临时 console.log，wrapper 的 grep 面永远看不到——
 * t260929-08 验收打回的确定性闸红教训：跨进程输出契约必须走 result JSON）。
 * orchestrator 读到 antiproof_ok=true 才向自身 stdout 打 ANTIPROOF=ok。
 */

const ok = (b) => Boolean(b)

export const name = 'sandbar-watchdog-bench-signals'

export function apply(ctx, options = {}) {
  const resultPath = options.resultPath || process.env.SANDBAR_BENCH_RESULT
  const cwd = options.benchCwd || process.env.SANDBAR_BENCH_CWD
  const LEG = process.env.SANDBAR_BENCH_LEG || 'all'
  const results = { ok: false, leg: LEG, checks: [], started_at: Date.now() }
  const check = (name, pass, detail = '') => {
    results.checks.push({ name, pass: ok(pass), detail: String(detail).slice(0, 500) })
    console.log(`[bench] ${pass ? 'ok' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`)
    return ok(pass)
  }
  const finish = (code) => {
    results.ok = results.checks.length > 0 && results.checks.every(c => c.pass)
    // 反证分支结论走结构化字段（不是宿主内 stdout——见头注跨进程教训）。
    results.antiproof_ok = antiproofOk === true
    results.finished_at = Date.now()
    const fs = process.getBuiltinModule('node:fs')
    if (resultPath) {
      try { fs.writeFileSync(resultPath, JSON.stringify(results, null, 2)) } catch (e) { console.error('[bench] result write failed:', e) }
    }
    process.exit(code)
  }
  const STALL_MIN = 15
  // 反证分支结论（finish 写进 results.antiproof_ok；声明在 apply 作用域——闭包可达）。
  let antiproofOk = true

  // 真接线 Watchdog 组装器：账本目录预置一行合法事件（start 全量重放 → lastProgressAt
  // 有锚），boardReader 恒失败（t260929-07 未修期间的真实形态；对账降级显式在案）。
  async function mkWatchdog({ sessionId, engineProbe, sessionStat, pendingProvider, clock, dirs, project = 'benchproj' }) {
    const fs = process.getBuiltinModule('node:fs')
    const { Watchdog, defaultIo } = await import('../../src/host/core.ts')
    const ledgerRow = JSON.stringify({
      schema: 'event-ledger-v1', idem: `${project}|t-bench|run1|1`, project, ticket: 't-bench',
      seq: 1, kind: 'stage-transition', stage: 'implement', stage_state: 'running', at: clock.now(),
    })
    fs.mkdirSync(dirs.ledger, { recursive: true })
    fs.writeFileSync(`${dirs.ledger}/${project}.jsonl`, ledgerRow + '\n')
    fs.mkdirSync(dirs.data, { recursive: true })
    const redline = ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall']
    const cfg = {
      declared: true, enabled: true, config_error: null,
      provenance: { file: 'bench-mem', keys: {} },
      config: {
        enabled: true, executor_session: sessionId, stall_minutes: STALL_MIN, reconcile_seconds: 60,
        alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'normal' }, redline, keep_days: 14 },
      },
    }
    return new Watchdog(project, {
      io: defaultIo,
      boardReader: async () => ({ ok: false, rows: [], error: 'bench: board reader deliberately failing (t260929-07 open shape)' }),
      engineProbe,
      sessionStat,
      pendingProvider,
      now: () => clock.now(),
      dataDir: dirs.data,
      ledgerDir: dirs.ledger,
      configLoader: () => cfg,
    })
  }

  const alertRules = (w) => (w.status().alerts ?? []).map(a => a.rule)

  void (async () => {
    const { makeSessionStat, makePendingProvider, makeEngineProbe } = await import('../../node.ts')
    const { appendRequest, fsLedgerIo } = await import('../../../executor-panel/src/host/requests.ts')
    const fs = process.getBuiltinModule('node:fs')

    let ctl = undefined
    for (let i = 0; i < 100; i++) {
      ctl = ctx.get('sessionController')
      if (ctl) break
      await new Promise(r => setTimeout(r, 100))
    }
    if (!ctl) { check('sessionController present', false, '真宿主 10s 内未注入 sessionController'); return finish(1) }
    check('sessionController present', true)

    // 建真 bench 会话（隔离 cwd；显式身份，非猜测）。
    let sessionId = null
    try {
      const created = await ctl.create({ cwd: cwd || process.cwd() })
      sessionId = created.sessionId
      check('bench session created via host API', true, `sessionId=${sessionId}`)
    } catch (e) {
      check('bench session created via host API', false, e instanceof Error ? e.message : String(e))
      return finish(1)
    }

    const doProgress = LEG === 'progress' || LEG === 'all'
    const doSelflock = LEG === 'selflock' || LEG === 'all'
    const doEngine = LEG === 'engine' || LEG === 'all'

    // ── leg: progress ──
    if (doProgress) {
      const { stat, snapshot } = makeSessionStat(ctx)
      let s0 = null
      for (let i = 0; i < 200; i++) {
        s0 = await stat(sessionId, 0)
        if (s0.advanced === true) break
        await new Promise(r => setTimeout(r, 100))
      }
      check('session visible in real list() with real updatedAt', s0.advanced === true && typeof s0.mtimeMs === 'number' && s0.mtimeMs > 0, JSON.stringify(s0))
      check('running bit read from same real list', snapshot.runningOf(sessionId) !== null, `running=${snapshot.runningOf(sessionId)}`)
      // 推进翻转：以当前 updatedAt 为水位，真投递一轮 → updatedAt 真前进。
      const base = s0.mtimeMs
      let prompted = null
      try {
        prompted = await ctl.prompt({ requestId: `bench-${Date.now()}`, sessionId, mode: 'queue', content: [{ type: 'text', text: '【bench】请只回答一个词：ok' }] }, new AbortController().signal)
      } catch (e) {
        check('progress prompt admitted', false, e instanceof Error ? e.message : String(e))
      }
      check('progress prompt admitted', prompted?.accepted === true)
      let s1 = null
      for (let i = 0; i < 1200; i++) {
        s1 = await stat(sessionId, base)
        if (s1.advanced === true) break
        await new Promise(r => setTimeout(r, 100))
      }
      check('real session activity advances updatedAt past watermark', s1?.advanced === true, JSON.stringify(s1))

      // 真 Watchdog 实例（wired vs 反证）：同一账本、同一时钟、同一会话。
      const dirs = { data: mkdtemp('wd-sig-data-'), ledger: mkdtemp('wd-sig-ledg-') }
      const clock = { t: s1?.mtimeMs ?? base, now() { return this.t } }
      const engineOk = async () => ({ online: true, detail: 'bench: engine ok (progress leg)' })
      const wired = await mkWatchdog({ sessionId, engineProbe: engineOk, sessionStat: stat, pendingProvider: makePendingProvider('benchproj'), clock, dirs })
      await wired.start()
      const preState = wired.status().liveness?.executor?.state
      check('wired instance: first tick sees real progress (advancing)', preState === 'advancing', `state=${preState}`)
      // 会话静默 + 时钟拨过阈值 → stalled + stall alert 落账。
      clock.t += 16 * 60_000
      await wired.tickOnce()
      const post = wired.status()
      check('idle real session crosses threshold -> stalled', post.liveness?.executor?.state === 'stalled', post.liveness?.executor?.evidence)
      check('stall alert raised by wired instance', alertRules(wired).includes('stall'), `rules=${alertRules(wired).join(',')}`)
      // 反证分支：同输入、deps 缺省（core 默认 sessionStat advanced:null）→ 恒 no_signal。
      const dirs2 = { data: mkdtemp('wd-sig-data2-'), ledger: dirs.ledger }
      const antiproof = await mkWatchdog({ sessionId, engineProbe: engineOk, clock, dirs: dirs2 })
      await antiproof.start()
      clock.t += 16 * 60_000
      await antiproof.tickOnce()
      const ap = antiproof.status()
      const apOk = ap.liveness?.executor?.state === 'no_signal' && !alertRules(antiproof).includes('stall')
      antiproofOk = antiproofOk && apOk
      check('ANTIPROOF: deps-omitted instance stays no_signal with no stall alert on identical inputs', apOk, `state=${ap.liveness?.executor?.state} rules=${alertRules(antiproof).join(',')}`)
      wired.dispose(); antiproof.dispose()
    }

    // ── leg: selflock ──
    if (doSelflock) {
      const prov = makePendingProvider('benchproj', () => false)
      const empty = await prov()
      check('missing ledger reads as genuinely no pending (not unknown)', empty.available === true && Array.isArray(empty.pending) && empty.pending.length === 0, JSON.stringify({ available: empty.available, n: empty.pending?.length }))
      const appended = appendRequest(fsLedgerIo, process.env, 'benchproj', { kind: 'approval', question: 'Bench: merge the gate?', raised_by: sessionId }, Date.now())
      check('real append with raised_by lands on real file', appended.ok === true && appended.row?.raised_by === sessionId, JSON.stringify(appended.ok ? { id: appended.row.id } : appended))
      // wired 真 Watchdog：下一拍 self_lock.state = waiting_on_itself + 告警（不等超时）。
      const dirs = { data: mkdtemp('wd-sig-sl-data-'), ledger: mkdtemp('wd-sig-sl-ledg-') }
      const clock = { t: Date.now(), now() { return this.t } }
      const wired = await mkWatchdog({
        sessionId, engineProbe: async () => ({ online: true, detail: 'bench: engine ok' }),
        sessionStat: async () => ({ advanced: null, mtimeMs: null }),
        pendingProvider: makePendingProvider('benchproj', () => false), clock, dirs,
      })
      await wired.start()
      wired.tickOnce()
      const st = wired.status().self_lock
      check('self-raised pending request -> waiting_on_itself on next tick (no timeout wait)', st?.state === 'waiting_on_itself' && st?.target === appended.row?.id, `${st?.state} ${st?.reason}`)
      check('self_lock alert raised by wired instance', alertRules(wired).includes('self_lock'), `rules=${alertRules(wired).join(',')}`)
      // 反证分支：deps 缺省（core 默认 provider available:false）→ 恒 unknown、无自锁告警。
      const antiproof = await mkWatchdog({
        sessionId, engineProbe: async () => ({ online: true, detail: 'bench: engine ok' }),
        sessionStat: async () => ({ advanced: null, mtimeMs: null }), clock,
        dirs: { data: mkdtemp('wd-sig-sl-ap-'), ledger: dirs.ledger },
      })
      await antiproof.start()
      antiproof.tickOnce()
      const aps = antiproof.status().self_lock
      const apOk = aps?.state === 'unknown' && !alertRules(antiproof).includes('self_lock')
      antiproofOk = antiproofOk && apOk
      check('ANTIPROOF: deps-omitted instance stays unknown with no self_lock alert', apOk, `state=${aps?.state} rules=${alertRules(antiproof).join(',')}`)
      // 未归属行：判定不认空归属，显式点名（真文件、真追加）。
      const legacy = appendRequest(fsLedgerIo, process.env, 'benchproj2', { kind: 'question', question: 'Legacy unattributed row' }, Date.now())
      const rY = await makePendingProvider('benchproj2')()
      const { detectSelfLock } = await import('../../src/host/self-lock.ts')
      const vY = detectSelfLock(rY.pending, sessionId, Date.now())
      check('unattributed waiting row named explicitly, never fake none', legacy.ok === true && vY.state === 'none' && vY.reason.includes('raised_by'), vY.reason)
      wired.dispose(); antiproof.dispose()
    }

    // ── leg: engine ──
    if (doEngine) {
      // SANDBAR_ENGINE_PORT 由 orchestrator 指向它自管的真实监听口（零 7233 接触）。
      const portEnv = process.env.SANDBAR_ENGINE_PORT
      const port = Number.parseInt(portEnv ?? '', 10)
      const portValid = Number.isFinite(port) && port > 0 && port < 65536 && port !== 3099
      check('SANDBAR_ENGINE_PORT override valid and not 3099', portValid, `SANDBAR_ENGINE_PORT=${portEnv}`)
      if (!portValid) return finish(1)
      const probe = makeEngineProbe()
      const up = await probe()
      check('engine probe online on orchestrator-held real listener', up.online === true, up.detail)
      // wired 真 Watchdog：探针在线 + 看板读失败 → 不产 engine_down（假警报锁）。
      const dirs = { data: mkdtemp('wd-sig-eng-data-'), ledger: mkdtemp('wd-sig-eng-ledg-') }
      const clock = { t: Date.now(), now() { return this.t } }
      const wired = await mkWatchdog({
        sessionId, engineProbe: makeEngineProbe(),
        sessionStat: async () => ({ advanced: null, mtimeMs: null }),
        pendingProvider: makePendingProvider('benchproj'), clock, dirs,
      })
      await wired.start()
      const st = wired.status()
      check('board failing + probe online -> online=true and NO engine_down (no fake alarm)', st.liveness?.engine?.online === true && !alertRules(wired).includes('engine_down'), `online=${st.liveness?.engine?.online} rules=${alertRules(wired).join(',')}`)
      wired.dispose()
      // 端口关 → offline（真 fd，全终态）。
      const net = process.getBuiltinModule('node:net')
      const srv = net.createServer()
      await new Promise(res => srv.listen(0, '127.0.0.1', res))
      const tmpPort = srv.address().port
      const upTmp = await makeEngineProbe(tmpPort)()
      await new Promise(res => srv.close(res))
      const down = await makeEngineProbe(tmpPort)()
      check('engine probe offline after socket closed', upTmp.online === true && down.online === false && down.detail.length > 0, `${down.detail}`)
    }

    return finish(results.ok ? 0 : 1)
  })()
}

function mkdtemp(prefix) {
  const fs = process.getBuiltinModule('node:fs')
  const os = process.getBuiltinModule('node:os')
  const path = process.getBuiltinModule('node:path')
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix))
}
