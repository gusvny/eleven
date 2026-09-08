/**
 * smoke/epics-status.mjs —— 立项单状态 enum 化（t260831-05）宿主半冒烟。
 *
 * 直跑：node smoke/epics-status.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖：
 *   A. EPIC_STATUSES 枚举常量形状（四值、全角括号）+ parseEpicMeta 读「备注」列；
 *   B. validateEpicNote 备注形状校验（拒收不转义）：含 | / 含换行 / 含反引号 /
 *      超 200 字符 / number / object / null=不动 / undefined=不动 / ''=清空；
 *   C. setEpicStatus 全分支：合法改写、非法枚举 422、无状态行 422、404、代号形状 400、
 *      防穿、写前 /tmp 备份（内容=改写前原文，按 <code>- 前缀取 mtime 最新——共享全局
 *      目录，取到旧备份会假绿）、备注新增行（插在状态行后）/清空/不动、
 *      closeEpic 薄封装（状态=已完结且不动备注）；
 *   D. 路由 POST /epics/<code>/status：200 / 400 畸形 JSON / 400 缺 status / 422 非法枚举 /
 *      422 畸形 note / 405 GET / 404 不存在代号；close 路由回归（响应形状不变、
 *      状态=已完结 ∈ EPIC_STATUSES、备份内容=改写前原文、close 不动备注列）；
 *   E. 前端纯函数：filterEpicsByStatus（全部/单值/未知值 console.warn 返空/空列表）、
 *      isEpicStatusValue、EPIC_STATUS_OPTIONS 与 host EPIC_STATUSES 一致性断言；
 *   F. 存量迁移断言：真目录 notes/epics 七单状态全部 ∈ EPIC_STATUSES、备注列存在、
 *      关键映射抽查（dsh-generalize=已归档+备注含 sandbar；sandbar=已立项（执行中））。
 * 全部桩/fixture 复现（SANDBAR_EPICS_DIR 指向临时目录；fixture 代号带 zz- 前缀防 /tmp
 * 备份串档），不靠真外部源。
 */

import { mkdir, mkdtemp, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  closeEpic, EPIC_CODE_RE, EPIC_NOTE_MAX, EPIC_STATUSES, isEpicStatus, listEpics,
  parseEpicMeta, readEpicMarkdown, setEpicStatus, validateEpicNote,
} from '../src/host/epics.ts'
import { apply } from '../node.ts'
import {
  EPIC_NOTE_INPUT_MAX, EPIC_STATUS_OPTIONS, filterEpicsByStatus, isEpicStatusValue,
} from '../src/client/epics-model.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const FIX_MD = (status, noteRow = '') => `# 立项单：zz-fix

| 字段 | 值 |
| --- | --- |
| 代号 | \`zz-fix\` |
| 状态 | ${status} |${noteRow}
| 立项日期 | 2026-08-25 |

## 目标

状态 enum 化自测桩。
`

const tmp = await mkdtemp(join(tmpdir(), 'wb-epic-status-'))
const savedEnv = process.env.SANDBAR_EPICS_DIR
try {
  /* ------------------------------------------------------------ A. 枚举常量 + 备注列解析 */
  section('A EPIC_STATUSES 枚举 + parseEpicMeta 备注列')
  {
    ok(EPIC_STATUSES.length === 4
      && EPIC_STATUSES[0] === '已立项（待开工单）' && EPIC_STATUSES[1] === '已立项（执行中）'
      && EPIC_STATUSES[2] === '已完结' && EPIC_STATUSES[3] === '已归档',
      '四枚举值逐字对齐派单规格（全角括号）')
    ok(isEpicStatus('已完结') && !isEpicStatus('已完结（2026-08-30）') && !isEpicStatus('已立项')
      && !isEpicStatus('') && !isEpicStatus('已完结 '), 'isEpicStatus 精确匹配（带细节/裸值/空串/尾空格全拒）')
    const meta = parseEpicMeta(FIX_MD('已立项（执行中）', '\n| 备注 | 第 1 面已落地 |'))
    ok(meta.status === '已立项（执行中）' && meta.note === '第 1 面已落地',
      'parseEpicMeta 读「备注」列')
    const noNote = parseEpicMeta(FIX_MD('已立项（执行中）'))
    ok(noNote.note === '', '无备注行 → 容错空串不拒收')
  }

  /* ------------------------------------------------------------ B. validateEpicNote 畸形用例 */
  section('B validateEpicNote 备注形状校验（拒收不转义）')
  {
    ok(validateEpicNote(undefined).ok === true && validateEpicNote(undefined).note === undefined, 'undefined = 不动备注')
    ok(validateEpicNote(null).ok === true && validateEpicNote(null).note === undefined, 'null = 不动备注')
    ok(validateEpicNote('').ok === true, "'' = 显式清空（合法动作）")
    ok(validateEpicNote('单行正常备注').ok === true, '单行纯文本放行')
    const long = '长'.repeat(EPIC_NOTE_MAX + 1)
    const vLong = validateEpicNote(long)
    ok(vLong.ok === false && vLong.status === 422 && String(vLong.error).includes(`${EPIC_NOTE_MAX}`),
      `超 ${EPIC_NOTE_MAX} 字符 → 422 报错写明上限`)
    ok(validateEpicNote('x'.repeat(EPIC_NOTE_MAX)).ok === true, `恰 ${EPIC_NOTE_MAX} 字符放行（边界）`)
    for (const [bad, why] of [['含|竖线', '竖线截断 tableField 取值'], ['含\n换行', '换行注入假字段行'], ['含`反引号', '剥反引号读写不一致']]) {
      const v = validateEpicNote(bad)
      ok(v.ok === false && v.status === 422 && String(v.error).includes(why.slice(0, 2)),
        `备注${why} → 422 拒收`)
    }
    const vNum = validateEpicNote(123)
    ok(vNum.ok === false && vNum.status === 400 && String(vNum.error).includes('number'),
      'note=number → 400 形状层拒收（不强转，不到 422 业务层）')
    const vObj = validateEpicNote({ a: 1 })
    ok(vObj.ok === false && vObj.status === 400 && String(vObj.error).includes('object'),
      'note=object → 400 形状层拒收')
  }

  /* ------------------------------------------------------------ C. setEpicStatus 全分支 */
  section('C setEpicStatus 外科改写全分支')
  const dirC = join(tmp, 'epics-c')
  await mkdir(dirC, { recursive: true })
  const BACKUP_DIR = '/tmp/epic-close-backup'
  /** 取共享 /tmp 备份目录里 <code>- 前缀 mtime 最新的备份全文（取旧档会假绿）。 */
  async function latestBackup(code) {
    let best = null
    try {
      for (const f of await readdir(BACKUP_DIR)) {
        if (!f.startsWith(code + '-') || !f.endsWith('.md')) continue
        const p = join(BACKUP_DIR, f)
        const s = await stat(p)
        if (best === null || s.mtimeMs > best.mtimeMs) best = { p, mtimeMs: s.mtimeMs }
      }
    } catch { /* 目录不存在视为无备份 */ }
    return best === null ? null : await readFile(best.p, 'utf8')
  }
  {
    // fixture 代号带 zz- 前缀：共享 /tmp 备份目录防串档（review gen4 提示）。
    await writeFile(join(dirC, 'zz-fix.md'), FIX_MD('已立项（待开工单）', '\n| 备注 | 旧备注 |'), 'utf8')

    const r1 = await setEpicStatus(dirC, 'zz-fix', '已立项（执行中）')
    ok(r1.ok === true && r1.status === '已立项（执行中）' && r1.note === '旧备注',
      '合法改写状态（note 缺省不动备注列）')
    const after1 = await readFile(join(dirC, 'zz-fix.md'), 'utf8')
    const bak1 = await latestBackup('zz-fix')
    ok(bak1 !== null && bak1.includes('| 状态 | 已立项（待开工单） |') && bak1.includes('| 备注 | 旧备注 |'),
      '写前备份存在且内容=改写前原文')

    const r2 = await setEpicStatus(dirC, 'zz-fix', '已完结', '全部交付完毕')
    ok(r2.ok === true && r2.note === '全部交付完毕', '非空 note 写入备注列')
    const after2 = await readFile(join(dirC, 'zz-fix.md'), 'utf8')
    ok(after2.includes('| 状态 | 已完结 |') && after2.includes('| 备注 | 全部交付完毕 |')
      && parseEpicMeta(after2).note === '全部交付完毕', '备注行被外科改写（行序不变）')

    const r3 = await setEpicStatus(dirC, 'zz-fix', '已完结', '')
    ok(r3.ok === true && r3.note === '', "'' = 清空备注")
    ok((await readFile(join(dirC, 'zz-fix.md'), 'utf8')).includes('| 备注 |  |'), '清空后备注行为空值')

    const bad1 = await setEpicStatus(dirC, 'zz-fix', '已结项（并入 sandbar）')
    ok(bad1.ok === false && bad1.status === 422 && String(bad1.error).includes('已归档')
      && String(bad1.error).includes('已立项（待开工单）'),
      '非法枚举（旧自由写法）→ 422 报错附合法值清单')

    await writeFile(join(dirC, 'zz-nonote.md'), FIX_MD('已立项（待开工单）'), 'utf8')
    const r4 = await setEpicStatus(dirC, 'zz-nonote', '已立项（执行中）', '新插备注')
    ok(r4.ok === true && r4.note === '新插备注', '无备注行 + 非空 note → 新插备注行')
    const after4 = await readFile(join(dirC, 'zz-nonote.md'), 'utf8')
    ok(/^\| 状态 \| 已立项（执行中） \|\n\| 备注 \| 新插备注 \|/m.test(after4),
      '新备注行紧跟状态行（字段表格行序约定）')

    const bad2 = await setEpicStatus(dirC, 'zz-nonote', '已立项（执行中）', '含|竖线')
    ok(bad2.ok === false && bad2.status === 422, '畸形 note（含 |）→ 422 拒收，不写档')

    const bad3 = await setEpicStatus(dirC, 'no-such-zz', '已完结')
    ok(bad3.ok === false && bad3.status === 404, '不存在代号 → 404')
    const bad4 = await setEpicStatus(dirC, 'ZZ-UPPER', '已完结')
    ok(bad4.ok === false && bad4.status === 400 && !EPIC_CODE_RE.test('ZZ-UPPER'), '代号形状非法 → 400')
    const bad5 = await setEpicStatus(dirC, '../zz-escape', '已完结')
    ok(bad5.ok === false && bad5.status === 400 && String(bad5.error).includes('形状'),
      'resolve 越界（../ 前缀先撞形状白名单）→ 400')

    await writeFile(join(dirC, 'zz-norow.md'), '# 立项单：zz-norow\n\n没有字段表格。\n', 'utf8')
    const bad6 = await setEpicStatus(dirC, 'zz-norow', '已完结')
    ok(bad6.ok === false && bad6.status === 422 && String(bad6.error).includes('无「状态」'),
      '无「状态」行 → 422 不模糊成功')

    const rc = await closeEpic(dirC, 'zz-nonote')
    ok(rc.ok === true && rc.status === '已完结' && isEpicStatus(rc.status),
      'closeEpic 薄封装：状态=已完结且 ∈ EPIC_STATUSES（close 与枚举对齐）')
    const afterClose = await readFile(join(dirC, 'zz-nonote.md'), 'utf8')
    ok(parseEpicMeta(afterClose).note === '新插备注', 'close 不动备注列')
  }

  /* ------------------------------------------------------------ D. 路由 POST /status + close 回归 */
  section('D 路由：POST /epics/<code>/status + close 回归')
  {
    const mockRes = () => ({
      status: 0, body: null,
      writeHead(s) { this.status = s },
      end(b) { this.body = b ? JSON.parse(b) : null },
    })
    const mockReq = (url, method = 'GET', body) => ({
      url, method,
      async *[Symbol.asyncIterator]() { if (body !== undefined) yield Buffer.from(body) },
    })
    const repoD = join(tmp, 'repo-d')
    await mkdir(join(repoD, 'server'), { recursive: true })
    // stub admin.py：tickets 聚合返回空（走降级或空集均可，本段不验聚合）。
    await writeFile(join(repoD, 'server', 'admin.py'), `import json, sys
print(json.dumps({"ok": True, "result": {"count": 0, "tickets": []}}))
sys.exit(0)
`, 'utf8')
    await mkdir(join(repoD, 'notes', 'epics'), { recursive: true })
    await writeFile(join(repoD, 'notes', 'epics', 'zz-route.md'),
      FIX_MD('已立项（待开工单）', '\n| 备注 | 路由旧备注 |'), 'utf8')
    const routes = []
    const ws = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      effect: (fn) => { fn() },
      logger: { info() {}, warn() {} },
      get: (k) => (k === 'webServer' ? ws : undefined),
      on: () => () => {},
    }
    apply(ctx, { repo: repoD })
    const prefix = routes.find((r) => r.kind === 'prefix' && r.path === '/sandbar-workbench/api/epics')
    const call = async (url, method = 'GET', body) => {
      const res = mockRes()
      await prefix.handler(mockReq(url, method, body), res)
      return res
    }
    const B = '/sandbar-workbench/api/epics'

    let r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: '已立项（执行中）' }))
    ok(r.status === 200 && r.body.ok === true && r.body.result.status === '已立项（执行中）'
      && r.body.result.code === 'zz-route' && r.body.result.note === '路由旧备注',
      'POST /status 200：响应含 code/status/note（note 缺省不动）')
    let md = await readFile(join(repoD, 'notes', 'epics', 'zz-route.md'), 'utf8')
    ok(parseEpicMeta(md).status === '已立项（执行中）' && parseEpicMeta(md).note === '路由旧备注',
      '端点真实落档：状态行改写、备注列未动')

    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: '已完结', note: '端点备注' }))
    ok(r.status === 200 && r.body.result.note === '端点备注', 'POST /status 带 note → 备注列更新')
    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: '已完结', note: null }))
    ok(r.status === 200 && r.body.result.note === '端点备注', 'note=null → 不动备注（200 原样）')

    r = await call(`${B}/zz-route/status`, 'POST', '{broken json')
    ok(r.status === 400, '畸形 JSON body → 400')
    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ note: '缺 status' }))
    ok(r.status === 400, '缺 status 字段 → 400')
    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: 42 }))
    ok(r.status === 400, 'status 非字符串 → 400')
    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: '自由发挥状态' }))
    ok(r.status === 422 && String(r.body.error).includes('已归档'), '白名单外状态 → 422 附合法值清单')
    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: '已完结', note: 'a|b' }))
    ok(r.status === 422, '畸形 note（含 |）→ 422')
    r = await call(`${B}/zz-route/status`, 'POST', JSON.stringify({ status: '已完结', note: 123 }))
    ok(r.status === 400, 'note=number → 400 形状层')
    r = await call(`${B}/zz-route/status`, 'GET')
    ok(r.status === 405, 'GET /status → 405（写动作只支持 POST）')
    r = await call(`${B}/no-such-zz/status`, 'POST', JSON.stringify({ status: '已完结' }))
    ok(r.status === 404, '不存在代号 → 404')

    // close 回归网（现有 smoke/epics.mjs 对 closeEpic 零覆盖，本段补齐）。
    md = await readFile(join(repoD, 'notes', 'epics', 'zz-route.md'), 'utf8')
    r = await call(`${B}/zz-route/close`, 'POST')
    ok(r.status === 200 && r.body.ok === true && r.body.result.code === 'zz-route'
      && r.body.result.status === '已完结',
      'close 路由响应形状不变（{ok,result:{code,status}}）')
    ok(r.body.result.status === '已完结' && isEpicStatus(r.body.result.status), 'close 后状态=已完结 ∈ EPIC_STATUSES')
    const bak = await latestBackup('zz-route')
    ok(bak !== null && bak === md, 'close 写前备份内容=改写前原文')
    const afterClose = await readFile(join(repoD, 'notes', 'epics', 'zz-route.md'), 'utf8')
    ok(parseEpicMeta(afterClose).note === '端点备注', 'close 不动备注列')
    r = await call(`${B}/zz-route/close`, 'GET')
    ok(r.status === 405, 'GET /close → 405（人审确认语义不变）')
  }

  /* ------------------------------------------------------------ E. 前端纯函数 */
  section('E epics-model 前端纯函数')
  {
    ok(EPIC_STATUS_OPTIONS.length === 4 && EPIC_STATUS_OPTIONS.every((s, i) => s === EPIC_STATUSES[i]),
      'EPIC_STATUS_OPTIONS 与 host EPIC_STATUSES 逐字一致（两端一致性断言，防单边漂移）')
    ok(EPIC_NOTE_INPUT_MAX === EPIC_NOTE_MAX, 'EPIC_NOTE_INPUT_MAX 与 host EPIC_NOTE_MAX 互指一致')
    ok(isEpicStatusValue('已归档') && !isEpicStatusValue('已立项'), 'isEpicStatusValue 白名单精确匹配')
    const rows = [
      { code: 'a', status: '已立项（待开工单）' },
      { code: 'b', status: '已立项（执行中）' },
      { code: 'c', status: '已完结' },
    ]
    ok(filterEpicsByStatus(rows).length === 3 && filterEpicsByStatus(rows, '').length === 3,
      "筛选 ''/缺省 = 全部不过滤")
    ok(filterEpicsByStatus(rows, '已立项（执行中）').length === 1 && filterEpicsByStatus(rows, '已立项（执行中）')[0].code === 'b',
      '按枚举值精确过滤')
    ok(filterEpicsByStatus(rows, '已归档').length === 0, '无匹配 → 空数组')
    ok(filterEpicsByStatus([], '已完结').length === 0, '空列表 → 空数组不抛')
    const warns = []
    const origWarn = console.warn
    console.warn = (m) => warns.push(String(m))
    const unknown = filterEpicsByStatus(rows, '自由发挥')
    console.warn = origWarn
    ok(unknown.length === 0 && warns.length === 1 && warns[0].includes('自由发挥'),
      '未知状态（防御性）→ 空数组 + console.warn 一条（迁移漏网可见）')
  }

  /* ------------------------------------------------------------ F. 存量迁移断言（真目录） */
  section('F 存量迁移断言（notes/epics 真目录）')
  {
    const epics = await listEpics(join(process.cwd(), '..', '..', '..', 'notes', 'epics'))
    ok(epics.length >= 7, `真目录立项单 ≥7（存量只增不减，t260903-07 顺修：钉死计数随新立项单腐烂；实得 ${epics.length}）`)
    ok(epics.every((e) => isEpicStatus(e.status)), '全部立项单状态 ∈ EPIC_STATUSES（迁移断言）')
    const byCode = Object.fromEntries(epics.map((e) => [e.code, e]))
    ok(byCode['dsh-generalize']?.status === '已归档' && String(byCode['dsh-generalize']?.note ?? '').includes('sandbar'),
      'dsh-generalize = 已归档 + 备注含 sandbar（并入信息零丢失）')
    ok(byCode['sandbar']?.status === '已立项（执行中）', 'sandbar 裸「已立项」→ 已立项（执行中）')
    ok(byCode['coding-games']?.status === '已立项（待开工单）' && byCode['coding-games']?.note === '方向待拍板',
      'coding-games 细节迁入备注列')
    ok(byCode['epic-linkage']?.status === '已完结' && String(byCode['epic-linkage']?.note ?? '').includes('2026-08-30'),
      'epic-linkage 长状态 → 已完结 + 备注保留交付信息')
    ok(byCode['observability']?.status === '已立项（待开工单）', 'observability 本就是规范值，不变')
    // 详情读取链路带 note 字段（readEpicMarkdown 走 parseEpicMeta）。
    const rd = await readEpicMarkdown(join(process.cwd(), '..', '..', '..', 'notes', 'epics'), 'science-content')
    ok(rd.ok === true && rd.status === '已立项（待开工单）' && rd.note === '先做哪条线待拍板',
      'readEpicMarkdown 详情链路带 note（science-content 抽查）')
  }
} finally {
  if (savedEnv === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv
  await rm(tmp, { recursive: true, force: true })
}

console.log(`\n${failed === 0 ? 'PASS' : 'FAIL'} epics-status：${passed} ok, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
