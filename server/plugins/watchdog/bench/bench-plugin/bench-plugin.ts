/**
 * host-prompt-bench 插件半（t260929-04 验收⑥「真投递不丢」的宿主内证）。
 *
 * 被真 dsh 宿主（bench 专用临时 profile）加载：拿到**真的** ctx.sessionController，
 * 在其上构造 watchdog 的 makeWakeIo，走完整链：
 *   queue 简报 → accepted 回执 → control 流镜像里认领 rpcId（消息已进权威队列=不丢）
 *   → updateQueue remove（消化）→ 认领翻 false（已消化窗关闭，可再醒）。
 * 结果写 env 指定的结果文件（JSON），每条断言独立记 pass/reason——绝不静默；
 * 然后退出宿主进程（bench 台是一次性台，生命周期归 orchestrator）。
 */

const ok = (b) => Boolean(b)

export const name = 'sandbar-watchdog-bench'

export function apply(ctx, options = {}) {
  const resultPath = options.resultPath || process.env.SANDBAR_BENCH_RESULT
  const cwd = options.benchCwd || process.env.SANDBAR_BENCH_CWD
  const results = { ok: false, checks: [], started_at: Date.now() }
  const check = (name, pass, detail = '') => {
    results.checks.push({ name, pass: ok(pass), detail: String(detail).slice(0, 500) })
    console.log(`[bench] ${pass ? 'ok' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`)
  }
  const finish = (code) => {
    results.ok = results.checks.length > 0 && results.checks.every(c => c.pass)
    results.finished_at = Date.now()
    const fs = process.getBuiltinModule('node:fs')
    if (resultPath) {
      try { fs.writeFileSync(resultPath, JSON.stringify(results, null, 2)) } catch (e) { console.error('[bench] result write failed:', e) }
    }
    process.exit(code)
  }

  // 观测面：订阅真 control 流，把队列帧形状打出来（诊断镜像认领，不作为断言）。
  // 注意：control 流是单播（实测定）——观测流开着会把帧吃掉，生产路径默认关闭；
  // SANDBAR_BENCH_OBSERVE=1 才开，且退出时 it.return() 归还流。
  if (process.env.SANDBAR_BENCH_OBSERVE !== '1') { /* skip observation */ } else void (async () => {
    try {
      let ctl0 = null
      for (let i = 0; i < 100 && !ctl0; i++) { ctl0 = ctx.get('sessionController'); if (!ctl0) await new Promise(r => setTimeout(r, 100)) }
      if (!ctl0) return
      const it = ctl0.control(new AbortController().signal)[Symbol.asyncIterator]()
      for (let i = 0; i < 400; i++) {
        const nxt = await Promise.race([it.next(), new Promise(r => setTimeout(() => r(null), 300))])
        if (!nxt) break
        if (nxt.done) break
        const f = nxt.value
        if (f?.type === 'baseline') {
          const q = Object.fromEntries(Object.entries(f.value?.queues ?? {}).map(([k, v]) => [String(k).slice(0, 8), (v ?? []).length]))
          console.log('[bench-ctl] baseline queues:', JSON.stringify(q).slice(0, 400))
        } else if (f?.type === 'queue') {
          console.log(`[bench-ctl] queue ${String(f.sessionId).slice(0, 8)}: ${(f.items ?? []).length} items`, JSON.stringify(f.items ?? []).slice(0, 400))
        }
      }
      console.log('[bench-ctl] observation window closed')
      await it.return?.()
    } catch (e) { console.log('[bench-ctl] stream error:', e?.message ?? String(e)) }
  })()

  void (async () => {
    const { makeWakeIo } = await import('../../node.ts')
    let ctl = undefined
    for (let i = 0; i < 100; i++) {
      ctl = ctx.get('sessionController')
      if (ctl) break
      await new Promise(r => setTimeout(r, 100))
    }
    if (!ctl) { check('sessionController present', false, '真宿主 10s 内未注入 sessionController'); return finish(1) }
    check('sessionController present', true)

    // 建一个 bench 会话（隔离 cwd；声明面：本 bench 自己铸的显式身份，非猜测）。
    let sessionId = null
    try {
      const created = await ctl.create({ cwd: cwd || process.cwd() })
      sessionId = created.sessionId
      check('bench session created via host API', true, `sessionId=${sessionId}`)
    } catch (e) {
      check('bench session created via host API', false, e instanceof Error ? e.message : String(e))
      return finish(1)
    }

    const io = makeWakeIo(ctx)
    // 镜像先起（先订阅 control 流再投递——帧只在投递时刻发给在场订阅者）。
    // 镜像热身：baseline 到场（idle→live，cap 5s）。
    let warm = null
    for (let i = 0; i < 1000; i++) {
      if ((io.transportState?.() ?? '').startsWith('live')) { warm = true; break }
      await new Promise(r => setTimeout(r, 5))
    }
    const depth0 = await io.queueDepth(sessionId)
    check('mirror subscribed & live before prompt', warm === true && depth0 !== null, `preDepth=${depth0} state=${io.transportState?.()}`)

    // 占位轮：先给 agent 一轮在跑的活，让下一份排队项真正滞留队列（活 agent 会立刻
    // 消费排队项——实测：简报投出即被消费，队列只存在毫秒级窗口）。
    const holder = await io.prompt(sessionId, '【bench 占位轮】请慢慢数到 20 再回答（尽量多花点时间）。', 'queue')
    check('holder turn admitted', holder.accepted === true, holder.accepted ? `requestId=${holder.requestId}` : (holder.error ?? ''))

    // (1) queue 简报：真 host prompt（queue 模式不丢——agent 忙时入 inbox）。
    const r = await io.prompt(sessionId, '【bench】queued brief: 事件账有新内容（t260929-04 真投递验证）', 'queue')
    check('queued prompt accepted', r.accepted === true && typeof r.requestId === 'string', r.accepted ? `requestId=${r.requestId}` : (r.error ?? 'refused'))
    if (!r.accepted) return finish(1)

    // (2) 权威队列认领：control 流镜像里出现 rpcId 回显 = 消息已进队列（不丢）。
    //     窗口可能只有几十毫秒（占位轮结束即消费）——5ms 密 poll，绝不因轮询稀而误判丢。
    let claimed = null
    let everClaimed = false
    for (let i = 0; i < 6000; i++) {
      claimed = await io.ourBriefPending(sessionId, r.requestId)
      if (claimed === true) { everClaimed = true; break }
      if (claimed === false && i > 200) break // 30s 后仍不可见 = 不再等
      await new Promise(r2 => setTimeout(r2, 5))
    }
    check('brief visible in authoritative queue (rpcId claim, NOT LOST)', everClaimed === true, `last=${claimed} state=${io.transportState?.()}`)
    const depth = await io.queueDepth(sessionId)
    check('queueDepth >= 1 while pending', typeof depth === 'number' && depth >= 1, `depth=${depth}`)

    // (3) 已消化窗关闭：先等 agent 自然消化（60s）；不动就 updateQueue remove 主动
    //     消化（这正是镜像跟踪的「队列项消失」事件；命名清楚，不冒充自然消化）。
    let digested = null
    let forced = false
    for (let i = 0; i < 12000 && everClaimed; i++) {
      digested = await io.ourBriefPending(sessionId, r.requestId)
      if (digested === false) break
      await new Promise(r2 => setTimeout(r2, 5))
    }
    if (everClaimed && digested !== false) {
      const itemId = await (io.ourPendingItemId ? io.ourPendingItemId(sessionId, r.requestId) : Promise.resolve(null))
      if (itemId !== null) {
        try {
          await ctl.updateQueue({ sessionId, itemId, action: { kind: 'remove' } })
          forced = true
        } catch (e) {
          check('forced digest via updateQueue remove', false, e instanceof Error ? e.message : String(e))
        }
      }
      for (let i = 0; i < 2000 && digested !== false; i++) {
        digested = await io.ourBriefPending(sessionId, r.requestId)
        if (digested === false) break
        await new Promise(r2 => setTimeout(r2, 5))
      }
    }
    check('after digestion our brief no longer pending (wake can resume)', everClaimed && digested === false, `claimed=${everClaimed} digested=${digested} forced=${forced}`)

    // (4) 不丢的第二证明（与队列窗解耦）：简报文本已 durable 落进会话（inspect 事件前缀）。
    let durable = false
    try {
      const insp = await ctl.inspect(sessionId)
      const text = JSON.stringify(insp ?? {})
      durable = text.includes('queued brief: 事件账有新内容')
    } catch (e) {
      check('inspect readable for durable proof', false, e instanceof Error ? e.message : String(e))
    }
    check('brief durable in session (inspect event prefix)', durable === true)
    return finish(results.ok ? 0 : 1)
  })()
}
