/**
 * epics.ts —— 立项单（epic）只读 API 的宿主半纯函数（epic-linkage 拆解工单 4 / Tier 2，
 * t260825-04）。
 *
 * 真源分工（立项单关键决策 2/5）：
 *   - 立项单文档真源 = notes/epics/*.md（文件存在性 = 代号存在性强校验，决策 2）；
 *   - 工单实时状态真源 = Temporal EpicCode 查询——在 node.ts 路由侧 spawn
 *     ticket list --epic（本模块不管），UI 不存状态（决策 5）。本模块全部只读纯函数，
 *     可被 smoke 直测。
 *
 * 与 python 侧真源互指（改一边必须同步另一边）：
 *   - EPIC_CODE_RE 复刻 server/engine/shared.py 的 EPIC_CODE_RE
 *     （形状白名单：小写字母/数字/连字符——字符集本身即防穿，'..'、'/' 全在表外）；
 *   - SANDBAR_EPICS_DIR env 覆盖先例同 shared.py 的 EPICS_DIR（自测/验收临时指向
 *     空目录或 fixture 目录）。
 */

import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { join, resolve, sep } from 'node:path'

/** 立项代号形状白名单：复刻 shared.py EPIC_CODE_RE（互指，勿单边漂移）。 */
export const EPIC_CODE_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

/* ------------------------------------------------ 立项状态枚举（t260831-05，单点真源） */

/**
 * 立项状态四值枚举（派单规格逐字）。单点真源：工单台筛选/写入校验/迁移断言
 * 全部从这里取，不散落字面量。全角括号「（）」与 notes/epics/*.md 档案惯例一致。
 */
export const EPIC_STATUSES = ['已立项（待开工单）', '已立项（执行中）', '已完结', '已归档'] as const

export type EpicStatus = (typeof EPIC_STATUSES)[number]

/** 枚举白名单精确匹配（非法值拒收的第一层；写入口径见 setEpicStatus）。 */
export function isEpicStatus(s: string): s is EpicStatus {
  return (EPIC_STATUSES as readonly string[]).includes(s)
}

/** 备注列最大长度（UTF-16 code unit，UI 输入框同步 maxLength）。 */
export const EPIC_NOTE_MAX = 200

/**
 * 工单截图证据文件名白名单（t260829-02 evidence 端点）：^[A-Za-z0-9._-]+$ 且
 * .png 结尾——'..'、'/'、'\' 全在表外即防穿第一层（resolve 落点断言仍是第二层，
 * 两层都要过）。单出纯函数：node.ts 端点与 smoke 直测同口径，防实现漂移。
 */
export const EVIDENCE_FILE_RE = /^[A-Za-z0-9._-]+$/

export function isEvidenceFileName(file: string): boolean {
  return EVIDENCE_FILE_RE.test(file) && file.endsWith('.png')
}

/** 立项单列表/详情共用的元信息形态。 */
export interface EpicMeta {
  /** 代号 = 文件名主名（notes/epics/<代号>.md）。 */
  code: string
  /** 标题 = 首个 # 行内容（约定形「立项单：<代号>」剥前缀，剥空则保留原文）。 */
  title: string
  /** 状态 = 字段表格里「状态」行的值；缺行给 ''。 */
  status: string
  /** 备注 = 字段表格里「备注」行的值；缺行给 ''（t260831-05：括号细节从状态迁入此列）。 */
  note: string
  /** 立项日期 = 字段表格里「立项日期」行的值；缺行给 ''。 */
  created: string
  // t260910-14 退役注记：原「下一步已备」缓存命中标记随预跑建议整链退役删除。
}

/** readEpicMarkdown 的返回：成功带全文+元信息；失败带 HTTP 状态码与人话 error。 */
export type EpicReadResult =
  | ({ ok: true; markdown: string } & EpicMeta)
  | { ok: false; status: number; error: string }

/** 立项单目录：env SANDBAR_EPICS_DIR 优先（shared.py EPICS_DIR 同款先例），缺省 <repo>/notes/epics。 */
export function resolveEpicsDir(repo: string): string {
  return process.env.SANDBAR_EPICS_DIR ?? join(repo, 'notes', 'epics')
}

/** 从立项单 Markdown 解析标题/状态/备注/立项日期（容错：缺字段给 ''，不拒收）。 */
export function parseEpicMeta(markdown: string): { title: string; status: string; note: string; created: string } {
  const heading = /^#\s+(.+?)\s*$/m.exec(markdown)?.[1] ?? ''
  // 约定标题形「立项单：<代号>」（notes/README.md）：剥前缀留实质；剥完为空则保留原文。
  const stripped = heading.replace(/^立项单：\s*/, '')
  const title = stripped !== '' ? stripped : heading
  return {
    title,
    status: tableField(markdown, '状态'),
    note: tableField(markdown, '备注'),
    created: tableField(markdown, '立项日期'),
  }
}

/** 取字段表格（| 字段 | 值 |）里指定字段的值；剥反引号，缺行返回 ''。 */
function tableField(markdown: string, key: string): string {
  const m = new RegExp(`^\\|\\s*${key}\\s*\\|\\s*([^|]+?)\\s*\\|`, 'm').exec(markdown)
  return m ? m[1].replace(/`/g, '').trim() : ''
}

/**
 * 列 notes/epics/*.md（只读纯函数）。目录不存在/无文件 → 空数组不报错；
 * 文件名主名不符合代号形状的不入列；单文件读失败跳过，不拖垮整列。按代号排序。
 */
export async function listEpics(epicsDir: string): Promise<EpicMeta[]> {
  let names: string[]
  try {
    names = await readdir(epicsDir)
  } catch {
    return []
  }
  const out: EpicMeta[] = []
  for (const name of names.sort()) {
    if (!name.endsWith('.md')) continue
    const code = name.slice(0, -'.md'.length)
    if (!EPIC_CODE_RE.test(code)) continue
    try {
      const markdown = await readFile(join(epicsDir, name), 'utf8')
      out.push({ code, ...parseEpicMeta(markdown) })
    } catch { /* 单文件读失败跳过 */ }
  }
  return out
}

/**
 * 读单份立项单 Markdown 全文（只读纯函数）。
 * 防穿双保险（仿 agent-logs.ts resolveAgentBaseDir 先例）：①EPIC_CODE_RE 形状白名单
 * （'..'、'/' 本就在字符集外）；②resolve 后断言落在 epicsDir 内。非法 400 / 不存在 404，
 * 人话 error 并附现有代号清单（同 shared.py validate_epic_code 的纠错风格）。
 */
export async function readEpicMarkdown(epicsDir: string, code: string): Promise<EpicReadResult> {
  if (!EPIC_CODE_RE.test(code)) {
    return {
      ok: false, status: 400,
      error: `立项代号形状不合法：'${code}'（要求 ^[a-z0-9][a-z0-9-]{0,40}$，小写字母/数字/连字符）`,
    }
  }
  const root = resolve(epicsDir)
  const abs = resolve(root, code + '.md')
  if (abs !== root && !abs.startsWith(root + sep)) {
    return { ok: false, status: 400, error: `路径越界（拒绝读取）：'${code}'` }
  }
  let markdown: string
  try {
    markdown = await readFile(abs, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') {
      let existing: string[] = []
      try {
        existing = (await readdir(root))
          .filter((f) => f.endsWith('.md') && EPIC_CODE_RE.test(f.slice(0, -'.md'.length)))
          .map((f) => f.slice(0, -'.md'.length))
          .sort()
      } catch { /* 目录不可读则不给清单 */ }
      return {
        ok: false, status: 404,
        error: `立项代号不存在：'${code}'（notes/epics/ 无此档案）。现有代号：${existing.join('、') || '（目录为空或不存在）'}`,
      }
    }
    return { ok: false, status: 500, error: `立项单读取失败：${String(err?.message ?? err)}` }
  }
  return { ok: true, code, markdown, ...parseEpicMeta(markdown) }
}

/* ---------------------------------------------------------------- 状态写函数（t260831-05） */

export type EpicCloseResult =
  | { ok: true; code: string; status: string }
  | { ok: false; status: number; error: string }

export type EpicSetStatusResult =
  | { ok: true; code: string; status: string; note: string }
  | { ok: false; status: number; error: string }

export type EpicNoteValidation = { ok: true; note?: string } | { ok: false; status: number; error: string }

/**
 * 「备注」外部输入形状校验（t260831-05，拒收不转义）——单出纯函数：node.ts 端点
 * 与 smoke 共用同口径，防实现漂移。允许：单行纯文本 ≤ EPIC_NOTE_MAX 字符；
 * 拒收原因逐条写在人话 error 里（哪条检查失败一目了然）：
 *   - 非字符串类型（number/object/…）：400（请求形状缺陷，不到 422 业务校验层；
 *     null/undefined 除外，语义 = 不动备注）；
 *   - 含 `|`：会截断 tableField 取值（取值正则 [^|]+?），可注入假字段列；
 *   - 含换行 \n / \r：会断行注入一整行假字段；
 *   - 含反引号：档案表格值惯例剥反引号（tableField），读写会不一致；
 *   - 超过 EPIC_NOTE_MAX：单行长度上限。
 */
export function validateEpicNote(raw: unknown): EpicNoteValidation {
  if (raw === undefined || raw === null) return { ok: true, note: undefined }
  if (typeof raw !== 'string') {
    return { ok: false, status: 400, error: `备注必须是字符串（收到 ${typeof raw}）；null 表示不动备注，空串表示清空备注` }
  }
  if (raw.includes('|')) return { ok: false, status: 422, error: `备注不能含竖线 |（会破坏字段表格结构，可注入假字段行）` }
  if (raw.includes('\n') || raw.includes('\r')) return { ok: false, status: 422, error: `备注必须是单行（不能含换行符，换行会注入假字段行）` }
  if (raw.includes('`')) return { ok: false, status: 422, error: `备注不能含反引号 \`（表格值惯例剥反引号，会造成读写不一致）` }
  if (raw.length > EPIC_NOTE_MAX) return { ok: false, status: 422, error: `备注超过 ${EPIC_NOTE_MAX} 字符上限（收到 ${raw.length} 字符）` }
  return { ok: true, note: raw }
}

/** 状态行外科改写正则（行首、整行、无捕获组泄漏）。 */
const STATUS_ROW_RE = /^(\|\s*状态\s*\|\s*)([^|]*?)(\s*\|)/m
/** 备注行外科改写正则（行首、整行）。 */
const NOTE_ROW_RE = /^(\|\s*备注\s*\|\s*)([^|]*?)(\s*\|)/m

/**
 * 立项状态外科改写（t260831-05）：把字段表格里「状态」行的值改为枚举白名单内的
 * 规范值，可选同步更新「备注」列。closeEpic 与 POST /epics/<code>/status 共用本函数。
 *
 * 故障分支全部继承 closeEpic（t260828-08）骨架，逐项：
 *   ①代号形状非法 → 400（EPIC_CODE_RE 白名单）；②resolve 落点越界 → 400；
 *   ③ENOENT → 404；④非 ENOENT 读取失败 → 500；⑤无「状态」行 → 422（不模糊成功）；
 *   ⑥写前 /tmp 备份（意外可回滚）；⑦响应形状 {ok:true,code,status} 兼容 close。
 * 新增：状态枚举白名单 422 + 备注形状校验 400/422（validateEpicNote）。
 *
 * note 语义：undefined = 不动备注列；'' = 清空备注（显式动作）；
 * 非空 = 写入备注列（无备注行则新插一行，插在「状态」行之后）。
 *
 * 备份目录与 closeEpic 单点共用 /tmp/epic-close-backup（评审定案：
 * 两函数写同一份档案真源，回滚单点，只查一个目录）。真源分工不变：只改
 * notes/epics/*.md 这一份档案真源；工单状态仍以 Temporal 为真源。
 */
export async function setEpicStatus(
  epicsDir: string,
  code: string,
  status: string,
  note?: string,
): Promise<EpicSetStatusResult> {
  if (!EPIC_CODE_RE.test(code)) {
    return {
      ok: false, status: 400,
      error: `立项代号形状不合法：'${code}'（要求 ^[a-z0-9][a-z0-9-]{0,40}$，小写字母/数字/连字符）`,
    }
  }
  if (!isEpicStatus(status)) {
    return {
      ok: false, status: 422,
      error: `立项状态不合法：'${status}'（只允许：${EPIC_STATUSES.join('、')}）`,
    }
  }
  if (note !== undefined) {
    const v = validateEpicNote(note)
    if (!v.ok) return { ok: false, status: v.status, error: v.error }
    // 采用校验后口径：null 归一为 undefined（=不动备注），后续分支统一只看 note。
    note = v.note
  }
  const root = resolve(epicsDir)
  const abs = resolve(root, code + '.md')
  if (abs !== root && !abs.startsWith(root + sep)) {
    return { ok: false, status: 400, error: `路径越界（拒绝写入）：'${code}'` }
  }
  let markdown: string
  try {
    markdown = await readFile(abs, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { ok: false, status: 404, error: `立项代号不存在：'${code}'` }
    return { ok: false, status: 500, error: `立项单读取失败：${String(err?.message ?? err)}` }
  }
  if (!STATUS_ROW_RE.test(markdown)) {
    return {
      ok: false, status: 422,
      error: `立项单 ${code} 无「状态」字段表格行（| 状态 | 值 |），无法外科改写——请手工编辑归档`,
    }
  }
  // 备份落 /tmp（node-shims 未声明 node:os tmpdir，且派单规格即「备份 /tmp」字面）。
  // 与 closeEpic 单点共用（回滚只查一个目录）；断言备份时按 <code>- 前缀 + mtime 最新取。
  const backupDir = '/tmp/epic-close-backup'
  await mkdir(backupDir, { recursive: true })
  await writeFile(join(backupDir, `${code}-${Date.now()}.md`), markdown, 'utf8')
  let updated = markdown.replace(
    STATUS_ROW_RE,
    (_m, head: string, _val: string, tail: string) => `${head}${status}${tail}`,
  )
  if (note !== undefined) {
    if (NOTE_ROW_RE.test(updated)) {
      updated = updated.replace(
        NOTE_ROW_RE,
        (_m, head: string, _val: string, tail: string) => `${head}${note}${tail}`,
      )
    } else if (note !== '') {
      // 无备注行且要写非空值：新插一行，紧跟「状态」行（字段表格行序约定）。
      const rowM = STATUS_ROW_RE.exec(updated)
      if (rowM !== null) {
        const at = rowM.index + rowM[0].length
        updated = updated.slice(0, at) + `\n| 备注 | ${note} |` + updated.slice(at)
      }
    }
    // note === '' 且无备注行：无需动作（缺行与空备注语义等价，都是 ''）。
  }
  await writeFile(abs, updated, 'utf8')
  return { ok: true, code, status: tableField(updated, '状态'), note: tableField(updated, '备注') }
}

/**
 * 立项结项（t260828-08）：把字段表格里「状态」行的值外科改写为「已完结」。
 * t260831-05 起为 setEpicStatus 薄封装：「已完结」是枚举四值之一（对齐 EPIC_STATUSES），
 * 不再重复防穿/备份骨架。响应形状不变（{ok:true,code,status}），close 路由与
 * smoke 回归网兼容。
 */
export async function closeEpic(epicsDir: string, code: string): Promise<EpicCloseResult> {
  const r = await setEpicStatus(epicsDir, code, '已完结')
  return r.ok ? { ok: true, code: r.code, status: r.status } : r
}
