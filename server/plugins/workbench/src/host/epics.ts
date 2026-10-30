/**
 * epics.ts — the epic registry reader of the workbench host (epic-linkage Tier 2,
 * t260825-04; one anchor and one row model since t261030-30).
 *
 * Source of truth:
 *   - the epic documents are <project root>/docs/epics/*.md. The store moved from
 *     notes/epics to docs/epics in t261019-12 (a hard cut, no notes/epics fallback);
 *   - a live ticket status comes from Temporal (the EpicCode query) in node.ts. This
 *     module never stores status (decision 5). Every function here is read-only, so a
 *     test can drive it directly.
 *
 * One anchor — the same rule as server/engine/shared.py resolve_epics_dir: env
 * SANDBAR_EPICS_DIR when it is set and non-empty, else <root>/docs/epics. The root is
 * the repo root in this module; a project-aware caller takes the root from
 * project-anchor.ts (anchorEpicsDir), which applies the same rule per project.
 *
 * One row model (EpicRecord): code / retired / summary / started come from the
 * front-matter record (docs/design/epic-registry-v1.md). The legacy field table
 * (| field | value |) is a fallback for a document that has no front-matter, never the
 * primary face. A document that cannot be read as a record carries a named defect and
 * fails closed (retired: true), exactly like shared.py validate_epic_code.
 *
 * Cross-references to the python side (change one side, change the other):
 *   - EPIC_CODE_RE mirrors shared.py EPIC_CODE_RE (shape whitelist: lowercase letters,
 *     digits and hyphens — '..' and '/' are outside the character set);
 *   - the SANDBAR_EPICS_DIR precedence mirrors shared.py resolve_epics_dir.
 */

import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { join, resolve, sep } from 'node:path'

/** 立项代号形状白名单：复刻 shared.py EPIC_CODE_RE（互指，勿单边漂移）。 */
export const EPIC_CODE_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

/* ------------------------------------------------ 立项状态枚举（t260831-05，单点真源） */

/**
 * The four epic status values, verbatim from the dispatch spec (legacy face).
 * One source: the console filter, the write validation and the migration
 * assertion all read this list, so no literal is scattered. The values keep
 * their legacy full-width parentheses, because they are data, not copy.
 * t261030-30: this enum is the LEGACY write face (docs/epics documents carry the
 * retired boolean instead); it survives because the field-table fallback and its
 * tests still use it.
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

/**
 * The one row shape every console epic reader renders (t261030-30). The front-matter
 * fields are the primary face; the legacy field-table fields stay for a document that
 * has no front-matter (title/note/created are '' when the table is absent).
 */
export interface EpicRecord {
  /** Code = the file name without '.md' (docs/epics/<code>.md). */
  code: string
  /** Fail-closed: true unless the front-matter says exactly 'retired: false'. */
  retired: boolean
  /** The front-matter summary line ('' when absent). */
  summary: string
  /** The front-matter started value ('' when absent). */
  started: string
  /** The status line of the row: 'open' or 'retired' from the front-matter, else the
   *  legacy field-table value, else 'unknown'. Never empty — a row without a readable
   *  status must never look healthy. */
  status: string
  /** Named defect when the record is not a healthy registry entry (absent when healthy). */
  defect?: string
  /** Legacy field-table face (fallback for a document without front-matter). */
  title: string
  note: string
  created: string
  // t260910-14 retirement note: the old 'next step ready' cache marker is gone with the
  // pre-run suggestion chain.
}

/** The row shape before t261030-30 (legacy field table only). Kept as an alias so an
 *  older caller keeps type-checking; new code takes EpicRecord. */
export type EpicMeta = EpicRecord

/** readEpicMarkdown's answer: success carries the full text plus the row; failure
 *  carries an HTTP status and a human error. */
export type EpicReadResult =
  | ({ ok: true; markdown: string } & EpicRecord)
  | { ok: false; status: number; error: string }

/**
 * The epic document directory: env SANDBAR_EPICS_DIR when it is set and non-empty
 * (the same rule as shared.py resolve_epics_dir), else <repo>/docs/epics.
 */
export function resolveEpicsDir(repo: string): string {
  const envDir = process.env.SANDBAR_EPICS_DIR
  if (typeof envDir === 'string' && envDir.trim() !== '') return envDir
  return join(repo, 'docs', 'epics')
}

/**
 * Parse the front-matter block of an epic document (the text between two leading
 * '---' lines, one 'key: value' pair per line). Keys are lowercased, values trimmed.
 * Mirrors shared.py parse_epic_front_matter: a missing block, an unterminated block or
 * a malformed line throws an Error that names the failed check — the caller decides
 * whether that is fatal (the row model fails closed).
 */
export function parseEpicFrontMatter(markdown: string): Record<string, string> {
  if (!markdown.startsWith('---')) throw new Error("no front-matter block (file must start with '---')")
  const lines = markdown.split('\n')
  let end = -1
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === '---') { end = i; break }
  }
  if (end === -1) throw new Error("unterminated front-matter block (no closing '---')")
  const fields: Record<string, string> = {}
  for (let i = 1; i < end; i++) {
    const line = lines[i].trim()
    if (line === '') continue
    const idx = line.indexOf(':')
    if (idx <= 0) throw new Error(`malformed front-matter line (no 'key: value'): ${JSON.stringify(line)}`)
    fields[line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim()
  }
  return fields
}

/**
 * Build one row from one document (pure). The front-matter decides; the legacy field
 * table is the fallback. A front-matter that cannot be read, or a 'retired' value that
 * is not exactly 'false' or 'true', is a defect: the row keeps a named reason and fails
 * closed as retired (the same rule as shared.py validate_epic_code).
 */
export function epicRecord(code: string, markdown: string): EpicRecord {
  const legacy = parseEpicMeta(markdown)
  let fields: Record<string, string>
  try {
    fields = parseEpicFrontMatter(markdown)
  } catch (err) {
    return {
      code, retired: true, summary: '', started: '',
      status: legacy.status !== '' ? legacy.status : 'unknown',
      defect: String(err instanceof Error ? err.message : err),
      title: legacy.title, note: legacy.note, created: legacy.created,
    }
  }
  const retiredRaw = fields.retired ?? ''
  const defect = retiredRaw !== 'false' && retiredRaw !== 'true'
    ? `front-matter 'retired' must be exactly 'false' or 'true' (found: ${retiredRaw === '' ? '(missing)' : JSON.stringify(retiredRaw)})`
    : undefined
  const retired = retiredRaw !== 'false'
  // A healthy record states its own state. A defect falls back to the legacy field
  // table, and to 'unknown' when that table is absent too.
  const status = defect === undefined
    ? (retired ? 'retired' : 'open')
    : (legacy.status !== '' ? legacy.status : 'unknown')
  const row: EpicRecord = {
    code,
    retired,
    summary: fields.summary ?? '',
    started: fields.started ?? '',
    status,
    title: legacy.title,
    note: legacy.note,
    created: legacy.created,
  }
  if (defect !== undefined) row.defect = defect
  return row
}

/** Parse title/status/note/created from the legacy field table (tolerant: a missing
 *  field is '', never a refusal). This is the fallback face only. */
export function parseEpicMeta(markdown: string): { title: string; status: string; note: string; created: string } {
  const heading = /^#\s+(.+?)\s*$/m.exec(markdown)?.[1] ?? ''
  // The conventional legacy heading carries a Chinese "epic" label before the
  // code: strip that label and keep the substance;
  // an empty remainder keeps the raw heading.
  const stripped = heading.replace(/^立项单：\s*/, '')
  const title = stripped !== '' ? stripped : heading
  return {
    title,
    status: tableField(markdown, '状态'),
    note: tableField(markdown, '备注'),
    created: tableField(markdown, '立项日期'),
  }
}

/** Read one field of the legacy field table (| field | value |); backticks stripped,
 *  a missing row answers ''. */
function tableField(markdown: string, key: string): string {
  const m = new RegExp(`^\\|\\s*${key}\\s*\\|\\s*([^|]+?)\\s*\\|`, 'm').exec(markdown)
  return m ? m[1].replace(/`/g, '').trim() : ''
}

/**
 * List <epicsDir>/*.md as rows (read-only). A name whose stem fails the code shape is
 * not a row; a single unreadable file is skipped and never drags the list down; the
 * answer is sorted by code.
 *
 * An unreadable directory throws a named Error: since t261019-12 the epic store is
 * docs/epics and an absent store must not answer as "this project has no epic"
 * (a face that cannot read the registry says so, it does not fake an empty registry).
 */
export async function listEpics(epicsDir: string): Promise<EpicRecord[]> {
  let names: string[]
  try {
    names = await readdir(epicsDir)
  } catch (err) {
    throw new Error(`epic registry directory not found: ${epicsDir} (docs/epics — the store moved from notes/epics in t261019-12; hard cut, no fallback): ${String(err instanceof Error ? err.message : err)}`)
  }
  const out: EpicRecord[] = []
  for (const name of names.sort()) {
    if (!name.endsWith('.md')) continue
    const code = name.slice(0, -'.md'.length)
    if (!EPIC_CODE_RE.test(code)) continue
    try {
      out.push(epicRecord(code, await readFile(join(epicsDir, name), 'utf8')))
    } catch { /* a single unreadable file is skipped */ }
  }
  return out
}

/**
 * Read one epic document in full (read-only).
 * Two guards against path escape (the resolveAgentBaseDir precedent): (1) the
 * EPIC_CODE_RE shape whitelist ('..' and '/' are outside the character set);
 * (2) the resolved path must stay inside epicsDir. An illegal shape answers 400, a
 * missing document answers 404 with the existing code list in the message (the same
 * correction style as shared.py validate_epic_code).
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
      } catch { /* an unreadable directory gets no list */ }
      return {
        ok: false, status: 404,
        error: `Epic code not found: '${code}' (no document at ${epicsDir}). Known codes: ${existing.join(', ') || '(the directory is empty or absent)'}`,
      }
    }
    return { ok: false, status: 500, error: `立项单读取失败：${String(err?.message ?? err)}` }
  }
  return { ok: true, markdown, ...epicRecord(code, markdown) }
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
 * <epicsDir>/<code>.md is that single source of truth; ticket state still comes
 * from Temporal.
 *
 * t261019-12 retirement note: no route calls this any more (the old close/status
 * routes answer 410). docs/epics documents carry a front-matter record and no status
 * row, so this legacy table writer keeps its fixture/smoke contract only. Retire an
 * epic by editing `retired:` in docs/epics/<code>.md in git.
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
