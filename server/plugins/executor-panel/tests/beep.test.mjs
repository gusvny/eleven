/**
 * beep.test.mjs —— 页内 beep 决策表驱动（票面硬性要求：一声就够、不重复、
 * 尊重 alerts.sound 与夜间口径）。决策函数与页面是同一份实现（String(fn) 嵌入）。
 */
import { assert, done } from './lib.mjs'
import { beepDecision, pickDegraded, fmtProportion, fmtWaiting, fmtAge, groupByProject } from '../src/host/page-logic.ts'

let n = 0
const A = (key, over = {}) => ({ key, rule: 'stall', level: 'red', night_muted: false, ...over })

// 新 key + beep → 响；同一 key 再轮询 → 永不重响。
{
  const seen = new Set()
  const d1 = beepDecision({ beep: true }, [A('k1')], 'p', seen)
  assert(d1.play === true && d1.keys.join() === 'k1', 'new unseen key + notify.beep = play that key')
  seen.add('k1')
  assert(beepDecision({ beep: true }, [A('k1')], 'p', seen).play === false, 're-poll same key after seen = zero beeps')
}
// notify.beep=false（含 alerts.sound=false / 夜间静音与过的结果）→ 永不响。
assert(beepDecision({ beep: false }, [A('k1')], 'p', new Set()).play === false, 'notify.beep=false = silent (sound switch + night policy already ANDed watchdog-side)')
assert(beepDecision(null, [A('k1')], 'p', new Set()).play === false, 'missing notify = silent')
assert(beepDecision({ beep: true }, null, 'p', new Set()).play === false, 'missing alerts = silent')

// 夜间已静音行：非红线绝不响；红线例外仍响（redline-only 口径，防御纵深）。
assert(beepDecision({ beep: true }, [A('k2', { night_muted: true, level: 'amber' })], 'p', new Set()).play === false, 'night-muted non-redline row = silent')
assert(beepDecision({ beep: true }, [A('k3', { night_muted: true, level: 'redline' })], 'p', new Set()).keys.join() === 'k3', 'night-muted redline row still beeps (redline exception)')

// 已见集合之外取第一条未见：多新 key 一次只响一声（「一声就够」）。
{
  const seen = new Set()
  const d = beepDecision({ beep: true }, [A('a'), A('b')], 'p', seen)
  assert(d.play === true && d.keys.join() === 'a,b', 'multiple new keys = one beep PER new key (一声就够按 key 计)')
}

// 降级挑选：三种不可达 + config_error，绝不 null 化成正常态。
assert(pickDegraded({ reachable: false }).kind === 'route-down', 'route-down degraded explicit')
assert(pickDegraded({ reachable: true, declared: false }).kind === 'not-declared', 'declared:false degraded explicit')
assert(pickDegraded({ reachable: true, declared: true, alive: false }).kind === 'stale', 'alive:false degraded explicit')
assert(pickDegraded({ reachable: true, declared: true, alive: true, config_error: 'boom' }).kind === 'config-error', 'config_error degraded explicit')
assert(pickDegraded({ reachable: true, declared: true, alive: true, config_error: null }).kind === null, 'only fully healthy renders normal')

// 健康度比例口径（绝对数误导）：0/0 显式「no rows」，不显示 0%。
assert(fmtProportion(0, 0) === '— (no rows)', 'no rows = explicit dash')
assert(fmtProportion(2, 8) === '2/8 rows (25%)', 'proportion format')

// 等待/年龄口径。
assert(fmtWaiting(65_000) === '1m 5s', 'waiting format minutes')
assert(fmtWaiting(3_600_000) === '1h 0m', 'waiting format hours')
assert(fmtAge(null) === '—', 'null age explicit dash')
assert(fmtAge(45) === '45s ago', 'age format')

// 分组（主列按项目分组；空输入=空组，不是报错）。
assert(groupByProject([{ project: 'b' }, { project: 'a' }, { project: 'b' }]).map(g => g.project).join() === 'b,a', 'groups in first-seen order')
assert(groupByProject([]).length === 0, 'empty rows = zero groups')

n += 20
done(n)
