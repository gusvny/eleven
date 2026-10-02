/**
 * board-reader project 过滤 UT（t261001-22 / KI-180）：watchdog 对账用的读器必须给
 * ticket-list 带本项目 project 过滤（否则全机看板比本项目账本，缺行计数永不收敛），
 * 并对回执行做行级项目裁剪兜底。无 project 选项的全局读面照旧回全机行（t260929-07
 * 真形锁 sc C 段契约：makeBoardReader(repo) 单参调用必须 rows>0——gen0 返工教训：
 * 读器擅自裁空全局面 = 盲掉对账/归属面，真回归）。引擎侧用**桩 client.py**（argv
 * 回显 + 混项目行 + 畸形输出用例），零真引擎、零真 Temporal。
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { assert, done, freshDir } from './lib.mjs'
import { makeBoardReader } from '../node.ts'

let n = 0
const t = (cond, name) => { assert(cond, name); n++ }

/** 造一个假引擎仓：<repo>/server/engine/client.py。
 *  mode='echo'：回执 tickets 首行带 args 字段=argv 里的 argsJSON 原文（断言过滤真传了），
 *  行集合固定混三项目；否则原样吐 stdout（exitCode 可指定，畸形输入用例）。 */
function fakeEngine(spec) {
  const repo = freshDir('wd-boardreader-')
  const engineDir = join(repo, 'server', 'engine')
  mkdirSync(engineDir, { recursive: true })
  const body = spec.mode === 'echo'
    ? [
        'import sys, json',
        "a = sys.argv[2] if len(sys.argv) > 2 else ''",
        'out = {"ok": True, "result": {"count": 3, "tickets": [',
        '  {"id": "t-sb", "project": "sandbar", "stage_state": "running", "args": a},',
        '  {"id": "t-other", "project": "dengzhufpv", "stage_state": "running"},',
        '  {"id": "t-nolabel", "stage_state": "running"}]}}',
        'sys.stdout.write(json.dumps(out))',
        '',
      ]
    : [`import sys`, `sys.stdout.write(${JSON.stringify(spec.stdout ?? '')})`, `sys.exit(${spec.exitCode ?? 0})`, '']
  writeFileSync(join(engineDir, 'client.py'), body.join('\n'))
  return repo
}

// project 过滤真的传进了 ticket-list args（结构假警的根因即「args 为空对象」）；
// 返工回归（gen1 派发规格）：板上确有本项目票时，带 project 选项的读器必须 rows>0。
{
  const read = makeBoardReader(fakeEngine({ mode: 'echo' }), { project: 'sandbar' })
  const r = await read()
  t(r.ok === true && r.rows.length > 0, 'regression: scoped reader yields rows>0 when the board has this project tickets')
  t(r.rows.length === 2, 'reader ok, rows scoped to project')
  const echoRow = r.rows.find(x => x.id === 't-sb')
  const args = JSON.parse(String(echoRow?.args ?? '{}'))
  t(args.project === 'sandbar', 'ticket-list received {"project":"sandbar"} (KI-180 root cause fixed)')
  const ids = r.rows.map(x => String(x.id))
  t(ids.includes('t-sb') && ids.includes('t-nolabel') && !ids.includes('t-other'), 'foreign project rows dropped, label-less kept')
}
// 无 project 选项 = 全局读面：单参调用（真形锁 sc C 段形状）照常回全机行，不被裁空。
{
  const r = await makeBoardReader(fakeEngine({ mode: 'echo' }))()
  t(r.ok === true && r.rows.length === 3, 'no project option = global read face, rows untouched (t260929-07 sc leg C contract)')
}
// 行级兜底：即使引擎侧过滤被绕过（桩无视 args 回全机行），回执行仍裁到本项目。
{
  const r = await makeBoardReader(fakeEngine({ mode: 'echo' }), { project: 'nusuyou' })()
  t(r.ok === true && r.rows.map(x => String(x.id)).join(',') === 't-nolabel',
    'engine-side filter bypassed → row-level scope still drops labeled foreign rows (label-less kept)')
}
// 畸形输入：stdout 非合法 JSON → 结构化失败（不裸抛、不误报成 rows:[] 的假绿）。
{
  const r = await makeBoardReader(fakeEngine({ stdout: 'Traceback (most recent call last): ...' }), { project: 'sandbar' })()
  t(r.ok === false && (r.error ?? '').includes('不是合法 JSON'), 'non-JSON stdout = named structured error')
}
// 畸形输入：result:null → 形状不符的结构化失败。
{
  const r = await makeBoardReader(fakeEngine({ stdout: '{"ok":true,"result":null}' }), { project: 'sandbar' })()
  t(r.ok === false && (r.error ?? '').includes('result 非对象'), 'result:null = shape mismatch, structured')
}
// 非零退出码：execFile 抛错 → 「不可达」措辞的结构化失败。
{
  const r = await makeBoardReader(fakeEngine({ stdout: 'boom', exitCode: 3 }), { project: 'sandbar' })()
  t(r.ok === false && (r.error ?? '').includes('不可达'), 'non-zero exit = unreachable wording, structured failure')
}

done(n)
