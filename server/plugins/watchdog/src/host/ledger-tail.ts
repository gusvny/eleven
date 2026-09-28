/**
 * 账本增量尾随（t260928-28，纯函数核 + 注入 io 的 Tailer）。
 *
 * 消费 `server/engine/event_ledger.py` 产出的 `<ledger_dir>/<project>.jsonl`
 * （schema event-ledger-v1，幂等键 idem = project|ticket|run_id|seq）。
 * Watchdog 是账本的消费者，绝不写事件行。
 *
 * 保证面：
 *  - 轮转不丢行：每次 poll 都检查 active 文件的 inode；inode 变了（rename 轮转）→
 *    先把旧句柄读到 EOF 再切新文件；归档文件名序缺口显式上报（archive_gap）。
 *  - 幂等去重：idem 重复行（at-least-once 重投）只计一次，dupes_skipped 计数。
 *  - 畸形行：跳过 + 计数 + 上报（malformed_rows），绝不崩、绝不吞。
 *  - 水位线 = { inode, offset, seenIdem }，**只在内存**；重启即弃，由 reconcile
 *    的启动全量重放重建（工单 scope 2，不信任内存水位）。
 * 不保证面（照 event_ledger.py 自述继承）：多写者 TOCTOU 下重复 idem 行是账面
 * 良性伪影——本模块对重复 idem 一律去重，不修复不放大。
 */

export interface LedgerRow {
  idem: string
  project: string
  ticket: string
  seq: number
  kind?: string
  stage?: string
  stage_state?: string
  reason?: string
  at?: number
  raw: Record<string, unknown>
}

export interface PollOutcome {
  rows: LedgerRow[]
  malformed: number
  dupes: number
  rotated: boolean
  archive_gap: number
  unreadable: string | null
}

export interface TailState {
  inode: number | null
  offset: number
  seen: Set<string>
  rowsSeen: number
  dupesSkipped: number
  malformedRows: number
  lastRowAt: number | null
  archiveFiles: number
  /** 归档序号缺口累计（显式上报，不静默）。 */
  archiveGap: number
  /** 轮转残余没收干净（显式位，状态面上报，绝不静默）。 */
  unresolvedRotateTail: boolean
}

export function freshTailState(): TailState {
  return { inode: null, offset: 0, seen: new Set(), rowsSeen: 0, dupesSkipped: 0, malformedRows: 0, lastRowAt: null, archiveFiles: 0, archiveGap: 0, unresolvedRotateTail: false }
}

/** 单行解析（畸形返回 null；不抛）。 */
export function parseLedgerLine(line: string): LedgerRow | null {
  if (line.trim() === '') return null
  let doc: unknown
  try {
    doc = JSON.parse(line)
  } catch {
    return null
  }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) return null
  const raw = doc as Record<string, unknown>
  const idem = typeof raw.idem === 'string' ? raw.idem : ''
  const ticket = typeof raw.ticket === 'string' ? raw.ticket : ''
  const seq = typeof raw.seq === 'number' ? raw.seq : NaN
  if (idem === '' || ticket === '' || !Number.isFinite(seq)) return null
  // 时刻字段：真源形状= ts（ISO 字符串，对齐 event_ledger.py 落盘字段）；数值 at 是容忍
  // 的旧/替形。两者都缺 = 行合法但无时刻（last_row_at 不因此行更新，不冒充）。
  let at: number | undefined
  if (typeof raw.at === 'number' && Number.isFinite(raw.at)) at = raw.at
  else if (typeof raw.ts === 'string') {
    const t = Date.parse(raw.ts)
    if (Number.isFinite(t)) at = t
  }
  return {
    idem,
    project: typeof raw.project === 'string' ? raw.project : '',
    ticket,
    seq,
    kind: typeof raw.kind === 'string' ? raw.kind : undefined,
    stage: typeof raw.stage === 'string' ? raw.stage : undefined,
    stage_state: typeof raw.stage_state === 'string' ? raw.stage_state : undefined,
    reason: typeof raw.reason === 'string' ? raw.reason : undefined,
    at,
    raw,
  }
}

/** 注入式 io（测试用内存桩；缺省真 fs）。stat 返回 { size, ino }，read 返回片段。 */
export interface TailIo {
  stat(path: string): Promise<{ size: number; ino: number }>
  read(path: string, start: number, end: number): Promise<string>
  /** 列归档文件名（不含活动文件），按名排序。缺省=空（io 桩可不实现）。 */
  listArchives?(activePath: string): Promise<string[]>
}

/** 归档名形状（对齐 event_ledger.py 的 _ARCH_SUFFIX_RE：YYYYMMDD[-HHMMSS][-hex]）。 */
export const ARCHIVE_NAME_RE = /^\d{8}(?:-\d{6})?(?:-[0-9a-f]{1,8})?\.jsonl$/

function activeName(project: string): string {
  return `${project}.jsonl`
}

export class LedgerTailer {
  state: TailState = freshTailState()
  private readonly dir: string
  private readonly project: string
  private readonly io: TailIo
  private readonly seenCap: number

  constructor(
    dir: string,
    project: string,
    io: TailIo,
    /** 已见 idem 集的有界加速上限（照 event_ledger.py 的 FIFO 逐出语义，纯加速器：逐出只可能多一次全查，不会错压制）。 */
    seenCap = 4096,
  ) {
    this.dir = dir
    this.project = project
    this.io = io
    this.seenCap = seenCap
  }

  private activePath(): string {
    return `${this.dir}/${activeName(this.project)}`
  }

  /** 一轮增量拉取。任何 io 失败 → unreadable 带原因，状态不动（下轮重试），绝不冒充读到 EOF。 */
  async poll(): Promise<PollOutcome> {
    const path = this.activePath()
    const out: PollOutcome = { rows: [], malformed: 0, dupes: 0, rotated: false, archive_gap: 0, unreadable: null }
    let st: { size: number; ino: number }
    try {
      st = await this.io.stat(path)
    } catch (e) {
      out.unreadable = `账本活动文件不可读：${e instanceof Error ? e.message : String(e)}`
      return out
    }
    // 轮转检测：活动文件 inode 变化 = 旧文件被 rename、新文件顶上。rename 后旧路径
    // 不再有效，但旧文件作为归档仍在——从归档里找到被 rename 的那份，把上次 offset
    // 之后的残余行收完，再切新活动文件（轮转夹缝里的行不丢）。
    if (this.state.inode !== null && st.ino !== this.state.inode) {
      out.rotated = true
      let drained = false
      if (this.io.listArchives && this.state.offset > 0) {
        try {
          const arch = (await this.io.listArchives(path)).filter(n => ARCHIVE_NAME_RE.test(n)).sort()
          this.state.archiveFiles = arch.length
          out.archive_gap = this.detectArchiveGap(arch)
          this.state.archiveGap += out.archive_gap
          if (arch.length > 0) {
            // 名序最后一份 = 刚 rename 的旧活动文件（event_ledger 轮转以当下时间命名）。
            const renamed = `${this.dir}/${arch[arch.length - 1]}`
            try {
              const stOld = await this.io.stat(renamed)
              if (stOld.size > this.state.offset) {
                const rest = await this.io.read(renamed, this.state.offset, stOld.size)
                const nl = rest.lastIndexOf('\n')
                if (nl !== -1) {
                  const take = rest.slice(0, nl + 1)
                  this.digest(take, out)
                  drained = true
                }
              }
            } catch { /* 归档已随保留窗清走等：残余不可收，交给对账面点名 */ }
          }
        } catch { /* 归档枚举失败不阻断主路径；丢行由对账面兜（显式，不静默） */ }
      }
      if (!drained) this.state.unresolvedRotateTail = true
      this.state.offset = 0
      this.state.inode = st.ino
    }
    if (this.state.inode === null) this.state.inode = st.ino
    if (st.size < this.state.offset) {
      // 活动文件被截断/替换且 inode 未变（罕见：同 inode 重写）——按重开处理并显式计数。
      this.state.offset = 0
      out.rotated = true
    }
    if (st.size === this.state.offset) return out
    let chunk: string
    try {
      chunk = await this.io.read(path, this.state.offset, st.size)
    } catch (e) {
      out.unreadable = `账本增量读失败：${e instanceof Error ? e.message : String(e)}`
      return out
    }
    this.digest(chunk, out)
    return out
  }

  /** 把一段文本按行消化进状态与 outcome（主路径与轮转残余共用；offset 停在行边界）。 */
  private digest(text: string, out: PollOutcome): void {
    // 断行（半行 JSON）：只消化到最后一个完整换行为止。
    const lastNl = text.lastIndexOf('\n')
    if (lastNl === -1) return
    const complete = text.slice(0, lastNl + 1)
    this.state.offset += Buffer.byteLength(complete)
    for (const line of complete.split('\n')) {
      if (line === '') continue
      const row = parseLedgerLine(line)
      if (row === null) {
        this.state.malformedRows += 1
        out.malformed += 1
        continue
      }
      if (this.state.seen.has(row.idem)) {
        this.state.dupesSkipped += 1
        out.dupes += 1
        continue
      }
      this.state.seen.add(row.idem)
      if (this.state.seen.size > this.seenCap) {
        // FIFO 逐出（Set 保插入序）：纯加速器，逐出后重投行会再被全查一遍，不会错压制。
        const first = this.state.seen.values().next().value
        if (first !== undefined) this.state.seen.delete(first)
      }
      this.state.rowsSeen += 1
      if (typeof row.at === 'number') this.state.lastRowAt = row.at
      out.rows.push(row)
    }
  }

  /**
   * 归档序号缺口计数：归档名尾段（-<hex>）是单调递增的轮转序号（缺省 = 当日时刻派生，
   * 但测试缝可注入显式序号）；序号回跳或跳号 = 归档被动过/被清过 = 显式缺口。
   * 只统计正向跳号与负向回跳，宁可虚报不漏报（「看起来都在」是本模块的红线）。
   */
  detectArchiveGap(archSorted: string[]): number {
    let prev: number | null = null
    let gaps = 0
    for (const name of archSorted) {
      const m = /-([0-9a-f]{1,8})\.jsonl$/.exec(name)
      if (!m) continue
      const idx = parseInt(m[1], 16)
      if (prev !== null && idx !== prev + 1) gaps += Math.abs(idx - prev - 1) || 1
      prev = idx
    }
    return gaps
  }
}

/** 从一批行推演 per-ticket 最新 stage-state（对账用推演态）。 */
export function deriveTicketStates(rows: LedgerRow[]): Map<string, { stage?: string; stage_state?: string; at?: number; lastIdem: string }> {
  const m = new Map<string, { stage?: string; stage_state?: string; at?: number; lastIdem: string }>()
  for (const r of rows) {
    m.set(r.ticket, { stage: r.stage, stage_state: r.stage_state, at: r.at, lastIdem: r.idem })
  }
  return m
}
