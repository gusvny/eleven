/**
 * blocks.ts —— docs 知识库 block 级 diff 的纯函数核（宿主半 node.ts 与浏览器半
 * src/client/index.tsx 共用；node 冒烟直跑）。
 *
 * 设计依据：docs/design/knowledge-base-design.md §3.3（block 是 diff 与 review 的最小单元）、
 * §5.2（逐 block diff：新增绿/删除红/修改并排）。
 *
 * block 类型枚举：frontmatter / heading（每个标题行独立块，含级别）/ paragraph /
 * list-item（每个 item 独立块，含有序/无序与缩进层级）/ table-head（表头+分隔行）/
 * table-row（每个数据行独立块）/ code（围栏代码块整块）/ quote（块引用）/
 * image（图片/figure 行）/ hr（分隔线）。
 *
 * 对齐：不再按 heading 相等贪心，而是「类型相容 + 内容相似度（bigram Dice）」的
 * 全局最优对齐（DP/LCS 变体，文本量级小 O(n·m) 足够）——标题改了字也对齐成
 * 「修改」而不是「删+增」。
 *
 * 稳定 key：`<type>:<内容归一化短哈希>[:重复序号]`——内容不变则 key 跨轮稳定，
 * 供 review 持久化跨轮引用；内容改了 key 变，旧意见自然「已过期」。
 *
 * 纯函数、零依赖、无 node/DOM API（tsc type-strip / tsdown 双端可跑）。
 */

/* ---------------------------------------------------------------- 类型 */

export type BlockType =
  | 'frontmatter' | 'heading' | 'paragraph' | 'list-item'
  | 'table-head' | 'table-row' | 'code' | 'quote' | 'image' | 'hr'

export interface MdBlock {
  type: BlockType
  /** 原始文本（多行块含 \n；table-row/list-item 为单行+续行）。 */
  text: string
  /** heading: 1–6；list-item: 缩进层级（0 起，2 空格一级）；其余 0。 */
  level: number
  /** list-item: 是否有序。 */
  ordered: boolean
  /** 稳定 key（类型+内容短哈希+重复序号）。 */
  key: string
  /** 归一化文本（对齐/哈希用）：压缩空白、heading 去 # 前缀。 */
  norm: string
  /** 给人看的一行摘要。 */
  summary: string
}

export interface DiffOp { k: 'ctx' | 'add' | 'del' | 'mod'; a?: string; b?: string }

export interface BlockDiff {
  key: string
  type: BlockType
  status: 'added' | 'removed' | 'modified' | 'unchanged'
  summary: string
  level: number
  /** removed / modified 块的旧文本。 */
  oldText?: string
  /** added / modified / unchanged 块的新文本。 */
  newText?: string
  /** 仅 modified 块带行级 ops（raw 次要视图用；未变块不带，降噪）。 */
  ops?: DiffOp[]
}

/* ---------------------------------------------------------------- 短哈希（FNV-1a 32bit） */

function fnv1a(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/* ---------------------------------------------------------------- 切块 */

const RE_HEADING = /^(#{1,6})\s+(.*)$/
const RE_HR = /^\s*(---+|\*\*\*+|___+)\s*$/
const RE_FENCE = /^```\s*([\w+-]*)/
const RE_QUOTE = /^>\s?/
const RE_UL = /^(\s*)([-*+])\s+(.*)$/
const RE_OL = /^(\s*)(\d+)[.)]\s+(.*)$/
const RE_IMAGE = /^\s*!\[[^\]]*\]\([^)]*\)\s*$/
const RE_TABLE_DELIM = /^\s*\|?[\s:|-]+\|?\s*$/

function isBlank(s: string): boolean { return s.trim() === '' }

/** 表格行 → 单元格数组（client 做单元格级对齐也用）。 */
export function splitCells(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map(c => c.trim())
}

function normalize(type: BlockType, text: string): string {
  let t = text
  if (type === 'heading') t = t.replace(/^#{1,6}\s+/, '')
  return t.trim().replace(/\s+/g, ' ')
}

function summarize(type: BlockType, text: string, level: number, ordered: boolean): string {
  const cut = (s: string, n: number) => (s.length > n ? s.slice(0, n) + '…' : s)
  switch (type) {
    case 'frontmatter': return 'frontmatter'
    case 'heading': return cut(text.replace(/^#{1,6}\s+/, '').trim(), 40)
    case 'code': {
      const m = text.match(RE_FENCE)
      return `代码块${m && m[1] ? '（' + m[1] + '）' : ''}`
    }
    case 'table-head': return '表头：' + cut(splitCells(text.split('\n')[0]).join(' | '), 40)
    case 'table-row': return cut(splitCells(text).join(' | '), 40)
    case 'list-item': return cut(text.replace(RE_UL, '$3').replace(RE_OL, '$3').trim(), 40)
    case 'image': return cut(text.trim(), 40)
    case 'hr': return '分隔线'
    case 'quote': return cut(text.replace(RE_QUOTE, '').trim(), 40)
    default: return cut(text.trim().split('\n')[0], 40)
  }
}

/** 把 markdown 全文切成细粒度 block 序列。 */
export function parseBlocks(src: string): MdBlock[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const raw: Array<{ type: BlockType; text: string; level: number; ordered: boolean }> = []
  const n = lines.length
  let i = 0

  // frontmatter：文档以 --- 起首，到下一个 --- 行为止（整块）。
  if (n > 0 && lines[0].trim() === '---') {
    let j = 1
    while (j < n && lines[j].trim() !== '---') j++
    if (j < n) {
      raw.push({ type: 'frontmatter', text: lines.slice(0, j + 1).join('\n'), level: 0, ordered: false })
      i = j + 1
    }
  }

  const push = (type: BlockType, text: string, level = 0, ordered = false): void => {
    raw.push({ type, text, level, ordered })
  }

  while (i < n) {
    const line = lines[i]
    if (isBlank(line)) { i++; continue }

    // 围栏代码块（整块，含围栏行）
    if (RE_FENCE.test(line)) {
      const buf = [line]
      i++
      while (i < n && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++ }
      if (i < n) { buf.push(lines[i]); i++ }
      push('code', buf.join('\n'))
      continue
    }
    // 标题（每行独立块）
    const h = line.match(RE_HEADING)
    if (h) { push('heading', line, h[1].length); i++; continue }
    // 表格：当前行含 | 且下一行是分隔行 → 表头块；随后每个数据行独立块
    if (line.includes('|') && i + 1 < n && RE_TABLE_DELIM.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      push('table-head', line + '\n' + lines[i + 1])
      i += 2
      while (i < n && lines[i].includes('|') && !isBlank(lines[i])) {
        push('table-row', lines[i])
        i++
      }
      continue
    }
    // 分隔线
    if (RE_HR.test(line)) { push('hr', line); i++; continue }
    // 图片/figure 行（整行只有一个图片语法）
    if (RE_IMAGE.test(line)) { push('image', line); i++; continue }
    // 块引用（连续 > 行整块）
    if (RE_QUOTE.test(line)) {
      const buf = [line]
      i++
      while (i < n && RE_QUOTE.test(lines[i])) { buf.push(lines[i]); i++ }
      push('quote', buf.join('\n'))
      continue
    }
    // 列表项（每个 item 独立块；更缩进的续行并入本 item）
    const ul = line.match(RE_UL)
    const ol = line.match(RE_OL)
    if (ul || ol) {
      const indent = (ul ?? ol)![1].replace(/\t/g, '  ').length
      const level = Math.floor(indent / 2)
      const buf = [line]
      i++
      while (i < n && !isBlank(lines[i])) {
        const cont = lines[i].match(/^(\s+)\S/)
        if (!cont) break
        const contIndent = cont[1].replace(/\t/g, '  ').length
        // 续行必须比 item 标记更缩进，且不是新的同级/更高级块起点
        if (contIndent <= indent) break
        if (RE_FENCE.test(lines[i])) break
        buf.push(lines[i])
        i++
      }
      push('list-item', buf.join('\n'), level, !!ol)
      continue
    }
    // 段落（到空行或下一个块起点）
    const buf = [line]
    i++
    while (i < n && !isBlank(lines[i])
      && !RE_HEADING.test(lines[i]) && !RE_FENCE.test(lines[i]) && !RE_QUOTE.test(lines[i])
      && !RE_UL.test(lines[i]) && !RE_OL.test(lines[i]) && !RE_HR.test(lines[i])) {
      buf.push(lines[i])
      i++
    }
    push('paragraph', buf.join('\n'))
  }

  // 归一化 + 稳定 key（同 hash 重复块追加序号）
  const seen = new Map<string, number>()
  return raw.map(b => {
    const norm = normalize(b.type, b.text)
    const base = `${b.type}:${fnv1a(norm)}`
    const count = (seen.get(base) ?? 0) + 1
    seen.set(base, count)
    const key = count === 1 ? base : `${base}:${count}`
    return {
      type: b.type, text: b.text, level: b.level, ordered: b.ordered,
      key, norm, summary: summarize(b.type, b.text, b.level, b.ordered),
    }
  })
}

/* ---------------------------------------------------------------- 相似度对齐 */

/** 类型相容才允许对齐（heading 跨级别相容；list-item 有序/无序相容）。 */
function compatible(a: BlockType, b: BlockType): boolean {
  return a === b
}

/** bigram Dice 系数（短串退化字符级）；norm 完全相等 = 1。 */
export function similarity(a: string, b: string): number {
  if (a === b) return 1
  if (a.length === 0 || b.length === 0) return 0
  const grams = (s: string): string[] => {
    if (s.length < 2) return [s]
    const out: string[] = []
    for (let i = 0; i < s.length - 1; i++) out.push(s.slice(i, i + 2))
    return out
  }
  const ga = grams(a)
  const gb = grams(b)
  const count = new Map<string, number>()
  for (const g of ga) count.set(g, (count.get(g) ?? 0) + 1)
  let hit = 0
  for (const g of gb) {
    const c = count.get(g) ?? 0
    if (c > 0) { hit++; count.set(g, c - 1) }
  }
  return (2 * hit) / (ga.length + gb.length)
}

/** 对齐阈值：标题块短、变动容忍低；其余 0.45。 */
function thresholdFor(t: BlockType): number {
  return t === 'heading' ? 0.4 : 0.45
}

interface Pair { oi: number; ni: number }

/** old/new 两序列全局最优对齐（DP，最大化相似度总和；对角优先）。 */
function align(ob: MdBlock[], nb: MdBlock[]): Pair[] {
  const N = ob.length
  const M = nb.length
  const W = M + 1
  // dp[i][j] = ob[i..] 与 nb[j..] 对齐的最大总相似度
  const dp = new Float64Array((N + 1) * W)
  const score = (i: number, j: number): number => {
    if (!compatible(ob[i].type, nb[j].type)) return 0
    const s = similarity(ob[i].norm, nb[j].norm)
    return s >= thresholdFor(ob[i].type) ? s : 0
  }
  for (let i = N - 1; i >= 0; i--) {
    for (let j = M - 1; j >= 0; j--) {
      const diag = dp[(i + 1) * W + j + 1] + score(i, j)
      const skipO = dp[(i + 1) * W + j]
      const skipN = dp[i * W + j + 1]
      dp[i * W + j] = Math.max(diag, skipO, skipN)
    }
  }
  const pairs: Pair[] = []
  let i = 0
  let j = 0
  while (i < N && j < M) {
    const s = score(i, j)
    const diag = dp[(i + 1) * W + j + 1] + s
    // 对角优先（保序稳定），再跳过 old，最后跳过 new
    if (s > 0 && diag >= dp[(i + 1) * W + j] && diag >= dp[i * W + j + 1]) {
      pairs.push({ oi: i, ni: j })
      i++; j++
    } else if (dp[(i + 1) * W + j] >= dp[i * W + j + 1]) {
      i++
    } else {
      j++
    }
  }
  return pairs
}

/* ---------------------------------------------------------------- 行级 ops（modified 块的 raw 次要视图） */

function lineDiff(a: string[], b: string[]): DiffOp[] {
  const N = a.length
  const M = b.length
  const W = M + 1
  const dp = new Uint32Array((N + 1) * W)
  for (let i = N - 1; i >= 0; i--) {
    for (let j = M - 1; j >= 0; j--) {
      dp[i * W + j] = a[i] === b[j]
        ? dp[(i + 1) * W + j + 1] + 1
        : Math.max(dp[(i + 1) * W + j], dp[i * W + j + 1])
    }
  }
  const ops: DiffOp[] = []
  let i = 0
  let j = 0
  while (i < N && j < M) {
    if (a[i] === b[j]) { ops.push({ k: 'ctx', a: a[i] }); i++; j++ }
    else if (dp[(i + 1) * W + j] >= dp[i * W + j + 1]) { ops.push({ k: 'del', a: a[i] }); i++ }
    else { ops.push({ k: 'add', b: b[j] }); j++ }
  }
  while (i < N) { ops.push({ k: 'del', a: a[i] }); i++ }
  while (j < M) { ops.push({ k: 'add', b: b[j] }); j++ }
  return ops
}

/** 相邻 del+add 配对成 mod。 */
function coalesceMods(ops: DiffOp[]): DiffOp[] {
  const out: DiffOp[] = []
  let i = 0
  while (i < ops.length) {
    if (ops[i].k === 'del' && i + 1 < ops.length && ops[i + 1].k === 'add') {
      out.push({ k: 'mod', a: ops[i].a, b: ops[i + 1].b })
      i += 2
      continue
    }
    out.push(ops[i])
    i++
  }
  return out
}

/* ---------------------------------------------------------------- block diff 主入口 */

/** old/new 全文 → 细粒度 block diff（按合并顺序输出，removed 插在其旧序位）。 */
export function diffBlocks(oldText: string, newText: string): BlockDiff[] {
  const ob = parseBlocks(oldText)
  const nb = parseBlocks(newText)
  const pairs = align(ob, nb) // 单调递增（oi/ni 双递增，DP 对角优先保证）
  const pairedN = new Map<number, number>() // ni → oi
  for (const p of pairs) pairedN.set(p.ni, p.oi)

  const out: BlockDiff[] = []
  let prevOi = -1 // 上一个已消费的 old 下标
  const emitRemoved = (oi: number): void => {
    out.push({
      key: ob[oi].key, type: ob[oi].type, status: 'removed',
      summary: ob[oi].summary, level: ob[oi].level, oldText: ob[oi].text,
    })
  }
  for (let ni = 0; ni < nb.length; ni++) {
    const oi = pairedN.get(ni)
    if (oi === undefined) {
      out.push({
        key: nb[ni].key, type: nb[ni].type, status: 'added',
        summary: nb[ni].summary, level: nb[ni].level, newText: nb[ni].text,
      })
      continue
    }
    // 冲刷 (prevOi, oi) 区间里未配对的 old 块 → removed（保持旧文档相对序）
    for (let k = prevOi + 1; k < oi; k++) emitRemoved(k)
    prevOi = oi
    const o = ob[oi]
    const nw = nb[ni]
    if (o.norm === nw.norm && o.level === nw.level && o.ordered === nw.ordered) {
      out.push({
        key: nw.key, type: nw.type, status: 'unchanged',
        summary: nw.summary, level: nw.level, newText: nw.text,
      })
    } else {
      const ops = coalesceMods(lineDiff(o.text.split('\n'), nw.text.split('\n')))
      out.push({
        key: nw.key, type: nw.type, status: 'modified',
        summary: nw.summary, level: nw.level, oldText: o.text, newText: nw.text, ops,
      })
    }
  }
  for (let k = prevOi + 1; k < ob.length; k++) emitRemoved(k)
  return out
}
