/**
 * docs.ts —— 「文档」视图宿主半（t260905-06；KI-070 起按项目根解析=t260910-10）：
 * docs/ 定稿库与 notes/ 观察窗的只读枚举/读取（node.ts docs 端点的实作单源，
 * 纯 fs 无进程/无监听，便于直测）。root 由调用方（node.ts docs 端点）按 ?project=
 * 项目锚解析后显式传入——本模块对项目语义无感，装载语义与单仓时代完全一致。
 *
 * 降级口径（R1 取舍清单 2 承接——精确报错，对照 KI-025「不许谎报没有」）：
 *   - scope 目录缺席 → { empty:true, reason:'<scope>/ 目录不存在（项目根=<root>）' }（真没有）；
 *   - rel 白名单拒 → 每类检查失败的 reason 各不相同（点了哪个检查就报哪个）；
 *   - 白名单允许但读不到（ENOENT）→ '文件不存在'（白名单真允许、读后确无）；
 *   - 超限 → '文件超过大小上限'；读失败 → '读取失败: <原文>'。
 *
 * 资源终态：readdir/readFile 一次性调用自回收，无长驻句柄/定时器/子进程；
 * 全路径（正常/目录缺/读失败）无遗留资源。
 */
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import {
  buildDocTree, docTitleOf, isSafeDocRel, parseFrontmatter,
  type DocMeta, type DocTreeGroup,
} from '../shared/docs-model.ts'

/** 单篇大小上限（utf8 字符数；定稿库最大篇 ~60KB，2MB 上限=10 倍余量防误配大文件拖爆响应）。 */
export const DOC_MAX_CHARS = 2_000_000

export interface DocsTreeResult {
  empty: boolean
  reason?: string
  scope: 'docs' | 'notes'
  /** 白名单通过的篇（树形分组）。 */
  groups: DocTreeGroup[]
  /** 白名单拒收文件（可见性：计数+理由，C3——完整性可判定，不静默消失）。 */
  skipped: { path: string; reason: string }[]
}

/** 递归收集 root 下文件；root 不存在返回 null（=真没有）。links=符号链接条目（拒收可见）。 */
interface WalkResult { files: string[]; links: string[] }

async function walkMd(root: string): Promise<WalkResult | null> {
  const files: string[] = []
  const links: string[] = []
  let entries
  try {
    entries = await readdir(root, { withFileTypes: true })
  } catch (err: any) {
    if (err?.code === 'ENOENT') return null
    throw err
  }
  for (const e of entries) {
    const rel = e.name
    if (e.isDirectory()) {
      const sub = await walkMd(join(root, rel))
      if (sub === null) continue // 目录在读之间被删=空集，不放大为错
      files.push(...sub.files.map((s) => `${rel}/${s}`))
      links.push(...sub.links.map((s) => `${rel}/${s}`))
    } else if (e.isFile()) {
      files.push(rel) // 非 .md 也收集——进 skipped 可见（拒收面完整，不静默消失）
    } else if (e.isSymbolicLink()) {
      links.push(rel) // 符号链接不枚举进树（只读面防外指，验收登记项 C）：进 skipped 可见
    }
  }
  return { files, links }
}

/** 枚举 scope 目录：白名单内进树，白名单外进 skipped（拒收可见）。 */
export async function listDocs(root: string, scope: 'docs' | 'notes'): Promise<DocsTreeResult> {
  const walk = await walkMd(root)
  if (walk === null) {
    return { empty: true, reason: `${scope}/ 目录不存在（项目根=${root}）`, scope, groups: [], skipped: [] }
  }
  const files = walk.files.sort()
  const skipped: { path: string; reason: string }[] = walk.links.map((rel) => ({
    path: rel, reason: '符号链接不枚举（只读面防外指）',
  }))
  const ok: { rel: string; title: string }[] = []
  for (const rel of files) {
    if (isSafeDocRel(rel)) {
      // 树形条目需要 title：读每篇头 4KB 解 frontmatter（大文件不整读）。
      try {
        const head = await readFile(join(root, rel), { encoding: 'utf8', flag: 'r' })
          .then((t) => t.slice(0, 4096))
        ok.push({ rel, title: docTitleOf(parseFrontmatter(head).meta, rel) })
      } catch {
        ok.push({ rel, title: rel }) // 头部读不动不隐篇：回落路径名，标题读失败可见（正文端点再报精确错）
      }
    } else {
      skipped.push({ path: rel, reason: skipReason(rel) })
    }
  }
  return { empty: false, scope, groups: buildDocTree(ok), skipped }
}

/** 白名单拒收理由（逐检查点名，不笼统「不合法」）。 */
function skipReason(rel: string): string {
  if (!rel.endsWith('.md')) return '仅 .md 入视图'
  if (rel.includes('\\')) return '含反斜杠（非 POSIX 路径段）'
  if (rel.includes('%')) return '含 URL 编码残留字符 %'
  if (rel.split('/').some((seg) => seg.includes(' '))) return '路径段含空格'
  if (rel.split('/').includes('..')) return '含 .. 段（穿路径拒绝）'
  return '路径含白名单外字符（段仅允许字母/数字/下划线/中文/连字符）'
}

export interface DocReadResult {
  empty: boolean
  reason?: string
  rel: string
  title: string
  meta: DocMeta
  body: string
  truncated?: boolean
}

/**
 * 读单篇：白名单 → 越界 → 大小 → ENOENT → 读失败，每步失败 reason 点名该检查。
 * rel 已由调用方保证为字符串；本函数再做白名单判定（单源 isSafeDocRel）。
 */
export async function readDoc(root: string, rel: string): Promise<DocReadResult> {
  const fail = (reason: string): DocReadResult => ({ empty: true, reason, rel, title: '', meta: {}, body: '' })
  if (typeof rel !== 'string' || rel === '') return fail('path 参数缺失（?path=<scope 下相对路径>.md）')
  if (rel.includes('\\')) return fail('path 不合法：含反斜杠（POSIX 相对路径才接受）')
  if (rel.includes('%')) return fail('path 不合法：含 URL 编码残留字符 %（请传解码后的路径）')
  if (rel.startsWith('/')) return fail('path 不合法：不接受绝对路径（传 scope 下相对路径）')
  if (rel.split('/').includes('..')) return fail('path 不合法：含 .. 段（穿路径拒绝）')
  if (!isSafeDocRel(rel)) return fail(`path 不合法（${'<目录/'}<文件>.md，段字符限字母/数字/下划线/中文/连字符）: ${rel}`)
  // 越界防呆：isSafeDocRel 已拒 .. 段与绝对路径，abs 恒在 root 下；此处再显式判一次（fail-closed 双闸）。
  const abs = join(root, rel)
  if (!abs.startsWith(root)) return fail('path 越界（穿路径拒绝）')
  let text: string
  try {
    text = await readFile(abs, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') return fail(`文件不存在: ${rel}`)
    return fail(`读取失败: ${String(err?.message ?? err)}`)
  }
  if (text.length > DOC_MAX_CHARS) return fail(`文件超过大小上限（${DOC_MAX_CHARS} 字符）: ${rel}`)
  const parsed = parseFrontmatter(text)
  return {
    empty: false,
    rel,
    title: docTitleOf(parsed.meta, rel),
    meta: parsed.meta,
    body: parsed.body,
    truncated: text.length >= DOC_MAX_CHARS ? true : undefined,
  }
}
