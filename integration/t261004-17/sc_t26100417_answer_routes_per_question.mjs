// sc_t26100417_answer_routes_per_question.mjs — t261004-17 缺陷2 读侧面（灰盒 L2，
// 直驱真实桥应答映射，离线零 docker 零浏览器，红线零接触 3099）。
//
// Intent（用户可感知行为；工单 Part A 第 3 条）：宿主对一个问题的回答，只落在那一个
// 问题上——回答哪个问题由宿主选，不是由标签文本撞大运。
//   R1 两问 ask，宿主只答第二问 → 映射结果只含第二问的选择，第一问保持未选/未答。
//   R2 两问带同一个标签（label collision 注入）→ 答其中一行，另一行的同名词不被选中。
//   R3 自由打字的答案落在宿主选中的那一问（不是散到全部问题）。
//   R4 组等待：整组行全部 answered 才算 answered；deadline/abort 终态不悬挂
//      （超时路径明确拒绝，不静默吞）。
// intent 分工：镜像写侧（选项/组标识落账）归本票 sc_t26100417_bridge_mirror_carries_options；
// 选项行的单行答复契约（按 id 闭行、二次答复拒收）归 t261003-06-executor-panel-requests-options O5；
// 本条只锁「跨问题路由」与「组等待」这两个本票病灶。导出缺席/签名未落地=FAIL 点名
// （TDD 期红属预期，arbitrate/merge 期必须绿）。
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const REPO = fileURLToPath(new URL('../../', import.meta.url))
const BRIDGE = join(REPO, 'server/plugins/executor-panel/src/host/question-bridge.ts')
const REQUESTS = join(REPO, 'server/plugins/executor-panel/src/host/requests.ts')

async function main() {
  if (!existsSync(BRIDGE)) {
    C.case('bridge-module-present', false, 'question-bridge.ts 缺席')
    return C.exit()
  }
  const bridge = await import(pathToFileURL(BRIDGE).href).catch(() => null)
  const map = bridge && bridge.mapLedgerAnswer
  if (typeof map !== 'function') {
    C.case('mapLedgerAnswer-export', false, 'question-bridge.ts 缺 mapLedgerAnswer 导出（TDD 期红属预期）')
    return C.exit()
  }

  // 真形两问 ask（与镜像场景同形状；第二问带与第一问不同的标签）。
  const TWO_Q = () => ({
    questions: [
      { id: 'q1', question: 'Which ticket first?', options: [{ label: 'Verify t1 first' }, { label: 'Verify t2 first' }], default_action: 'Verify t1 first' },
      { id: 'q2', question: 'Restart the worker?', options: [{ label: 'Restart now' }, { label: 'Leave it' }], default_action: 'Leave it' },
    ],
    agent: { id: 's', cwd: '/repo' },
  })

  // 公开契约（实现定稿形）：mapLedgerAnswer(request, answers) —— answers 与 questions
  // 同序、每问一个字符串（该行账本行的 answer 文本）。「答第二问」= answers[1] 带文本、
  // answers[0] 为空。选中的判定=selected 数组含该标签；custom 字段=该问的自由文本。
  const pick = (item) => ({
    selected: Array.isArray(item && item.selected) ? item.selected : [],
    custom: item && typeof item.custom === 'string' ? item.custom : '',
  })

  // R1 只答第二问：q1 不动
  {
    const req = TWO_Q()
    const ans = map(req, ['', 'Leave it'])
    const q1 = pick(ans.answers && ans.answers[0]), q2 = pick(ans.answers && ans.answers[1])
    C.case('R1-answer-q2-q1-untouched', q2.selected.includes('Leave it') && q1.selected.length === 0 && q1.custom === '',
      `q1=${JSON.stringify(q1)} q2=${JSON.stringify(q2)}`)
  }

  // R2 同名词注入：两问都有 "Proceed"，只答第二问不点亮第一问
  {
    const req = TWO_Q()
    req.questions[0].options.push({ label: 'Proceed' })
    req.questions[1].options.push({ label: 'Proceed' })
    const ans = map(req, ['', 'Proceed'])
    const q1 = pick(ans.answers && ans.answers[0]), q2 = pick(ans.answers && ans.answers[1])
    C.case('R2-collision-only-chosen-selected', q2.selected.includes('Proceed') && !q1.selected.includes('Proceed'),
      `q1=${JSON.stringify(q1)} q2=${JSON.stringify(q2)}`)
  }

  // R3 自由打字落在所选那一问（此处=第一问）
  {
    const req = TWO_Q()
    const ans = map(req, ['Wait for the nightly deploy, then re-check', ''])
    const q1 = pick(ans.answers && ans.answers[0]), q2 = pick(ans.answers && ans.answers[1])
    C.case('R3-custom-lands-on-chosen', q1.custom.includes('nightly') && q2.custom === '' && q2.selected.length === 0,
      `q1=${JSON.stringify(q1)} q2=${JSON.stringify(q2)}`)
  }

  // R4 组等待：requestIds 全行 answered 才 resolve（answered.answers 与 requestIds 同序）；
  // deadline 终态={state:'deadline'} 显式收口，不悬挂不抛。
  {
    const wait = bridge.waitForLedgerAnswer
    if (typeof wait !== 'function') {
      C.case('R4-group-wait-export', false, 'question-bridge.ts 缺 waitForLedgerAnswer 导出（TDD 期红属预期）')
    } else {
      // io 缝：内存 jsonl 账，文件键走真 requestsLedgerFile（SANDBAR_PANEL_DIR 注入）。
      const reqMod = await import(pathToFileURL(REQUESTS).href).catch(() => null)
      const ledgerKey = reqMod && reqMod.requestsLedgerFile
        ? reqMod.requestsLedgerFile('sandbar', { SANDBAR_PANEL_DIR: '/t261004-17-panel' })
        : '/t261004-17-panel/sandbar/requests.jsonl'
      const ENV = { SANDBAR_PANEL_DIR: '/t261004-17-panel' }
      const reqLine = (id) => JSON.stringify({ type: 'request', id, at: 1, project: 'sandbar', kind: 'question', question: id, raised_by: 't', default_action: '', expires_at: null })
      const ansLine = (id, a) => JSON.stringify({ type: 'answer', answer_for: id, at: 2, answer: a, by: 'host' })
      const memIo = (answers) => {
        const files = {}
        files[ledgerKey] = [reqLine('g-1'), reqLine('g-2'), ...answers].join('\n') + '\n'
        return {
          existsSync: (f) => f in files,
          readFileSync: (f) => { if (!(f in files)) throw new Error('ENOENT ' + f); return files[f] },
          appendFileSync: (f, line) => { files[f] = (files[f] || '') + line },
          mkdirSync: () => {},
        }
      }
      const run = (io, deadlineMs) => wait({
        io, env: ENV, project: 'sandbar',
        requestIds: ['g-1', 'g-2'], pollMs: 1, deadlineMs, now: Date.now,
      })
      const withTimeout = (p, ms) => Promise.race([p, new Promise(r => setTimeout(() => r('timeout'), ms))])
      const partial = await withTimeout(run(memIo([ansLine('g-2', 'Leave it')]), 5000), 300)
      const full = await withTimeout(run(memIo([ansLine('g-1', 'a'), ansLine('g-2', 'b')]), 5000), 300)
      const deadline = await run(memIo([]), 1)
      const partialHeld = partial === 'timeout' || (partial && partial.state !== 'answered')
      const fullOk = full && full.state === 'answered' && Array.isArray(full.answers) && full.answers[0] === 'a' && full.answers[1] === 'b'
      C.case('R4-group-wait-all-rows-then-deadline', partialHeld && fullOk && deadline && deadline.state === 'deadline',
        `partial=${JSON.stringify(partial).slice(0, 80)} full=${JSON.stringify(full).slice(0, 80)} deadline=${deadline && deadline.state}`)
    }
  }

  C.exit()
}

main().catch((e) => { C.case('scenario-crashed', false, String(e && e.stack || e).slice(0, 300)); C.exit() })
