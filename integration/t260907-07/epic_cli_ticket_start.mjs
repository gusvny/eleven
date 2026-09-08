#!/usr/bin/env node
/**
 * epic_cli_ticket_start.mjs —— t260907-07 验收①②CLI 开票路径断言（灰盒）。
 *
 * 断言面（cmd_ticket_start 真函数级，stub _connect 不起 Temporal，同
 * tests/test_t260904_02_registry_anchor.py 先例）：
 *  ①外部项目立项单在其自己根下 → 开票校验通过，TicketInput 落参 epic=gap-b；
 *  ②引擎项目行为不变：engine 桶的异名照常关联、external 读不到 engine 异名；
 *  对照：改造前世界（env 指向空目录模拟引擎锚缺失态）同 epic 被拒收——
 *  证明校验走的是项目锚而非别处。
 * Run: node integration/t260907-07/epic_cli_ticket_start.mjs（cwd=仓库根）
 */
import { join } from 'node:path'
import { makeEpicFixture, runPython } from './epic_fixture.mjs'

const { ok, done } = (await import('../t260903-09/lib_integration.mjs')).makeChecker()

const DRIVER = (project, epic) => `
import sys, json, asyncio
sys.path.insert(0, ${JSON.stringify(new URL('../../server/engine', import.meta.url).pathname)})
import client

class _FakeStub:
    async def start_workflow(self, *a, **kw):
        captured['input'] = a[1] if len(a) > 1 else kw.get('arg')
        class R: id = 'w1'; result_run_id = 'run-1'
        return R()

captured = {}
async def _connect():
    return _FakeStub()
client._connect = _connect
r = asyncio.run(client.cmd_ticket_start({
    'template_id': 'dev-lane', 'ticket_id': 't260907-07-t1',
    'project': ${JSON.stringify(project)}, 'epic': ${JSON.stringify(epic)},
    'lane': 'dir', 'title': 'x', 'write_set': ['notes/x.md'],
}))
inp = captured.get('input')
print(json.dumps({'ok': r.get('ok'), 'error': r.get('error', ''),
                  'epic': getattr(inp, 'epic', None), 'project': getattr(inp, 'project', None)}))
`

const fx = makeEpicFixture()
try {
  // 验收①：external epic 在自己根下 → 开票关联成功
  const r1 = JSON.parse(runPython(DRIVER('external', 'gap-b'), { ...fx.env, SUYOU_EPICS_DIR: '' }).trim())
  ok(r1.ok === true, '①external 项目 gap-b 开票校验通过', JSON.stringify(r1))
  ok(r1.epic === 'gap-b' && r1.project === 'external', '①TicketInput 落参 epic/project', JSON.stringify(r1))

  // 验收②：engine 桶异名照常关联（引擎项目行为不变）
  const r2 = JSON.parse(runPython(DRIVER('engine', 'engine-only'), { ...fx.env, SUYOU_EPICS_DIR: '' }).trim())
  ok(r2.ok === true && r2.epic === 'engine-only', '②engine 桶异名开票通过', JSON.stringify(r2))

  // 不串桶：engine-only 对 external 仍拒收，报错带实际查询目录
  const r3 = JSON.parse(runPython(DRIVER('external', 'engine-only'), { ...fx.env, SUYOU_EPICS_DIR: '' }).trim())
  ok(r3.ok === false && r3.error.includes(fx.external.epicsDir),
     '不串桶：external 读 engine 异名拒收且文案带 external 桶', JSON.stringify(r3))

  // 对照红面：env 指空目录（模拟「锚别处」世界）→ 同 epic 拒收，证明校验确走锚点
  const r4 = JSON.parse(runPython(DRIVER('external', 'gap-b'),
    { ...fx.env, SUYOU_EPICS_DIR: join(fx.root, 'empty-epics') }).trim())
  ok(r4.ok === false, '对照：env 锚空目录 → 同 epic 拒收（校验确走锚点）', JSON.stringify(r4))

  done('t260907-07 CLI 开票项目感知断言')
} finally {
  fx.teardown()
}
