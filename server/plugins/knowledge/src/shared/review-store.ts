/**
 * review-store.ts —— 知识库 block review 的落盘存取（宿主半专用，node:fs）。
 *
 * 落盘：docs/reviews/<path 中 / 换 __>.json（如 docs/reviews/design__knowledge-base-design.md.json）。
 * 结构：
 *   { path, rounds: [ { base, ts, reviewer, conclude, blocks: [
 *       { block_key, summary, type, status, decision?, comment? } ] } ] }
 *   conclude: approved | changes-requested | in-progress
 *
 * path 白名单校验在调用方（node.ts，DOC_PATH_RE 同源）；本模块只做 / → __ 的
 * 安全文件名映射与读改写。reviews 目录不存在则创建。浏览器半不 import 本文件
 * （node:fs 进不了浏览器 bundle）。
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

export type ReviewDecision = 'approve' | 'reject'
export type ReviewConclude = 'approved' | 'changes-requested' | 'in-progress'

export interface ReviewBlockEntry {
  block_key: string
  summary: string
  type: string
  status: string
  decision?: ReviewDecision
  comment?: string
}

export interface ReviewRound {
  base: string
  ts: number
  reviewer: string
  conclude: ReviewConclude
  blocks: ReviewBlockEntry[]
}

export interface ReviewFile {
  path: string
  rounds: ReviewRound[]
}

export const CONCLUDES: readonly ReviewConclude[] = ['approved', 'changes-requested', 'in-progress']

/** path（相对 docs/，已白名单校验）→ reviews 下的 json 绝对路径。 */
export function reviewFilePath(docsDir: string, p: string): string {
  return join(docsDir, 'reviews', p.replace(/\//g, '__') + '.json')
}

/** 读已存 review；不存在返回空 rounds（不是错误）。 */
export async function loadReview(docsDir: string, p: string): Promise<ReviewFile> {
  try {
    const data = JSON.parse(await readFile(reviewFilePath(docsDir, p), 'utf8'))
    const rounds = Array.isArray(data?.rounds) ? (data.rounds as ReviewRound[]) : []
    return { path: p, rounds }
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { path: p, rounds: [] }
    throw err
  }
}

/** 追加一轮 review（读-改-写；reviews 目录不存在则建）。 */
export async function appendReviewRound(docsDir: string, p: string, round: ReviewRound): Promise<ReviewFile> {
  const file = reviewFilePath(docsDir, p)
  await mkdir(join(docsDir, 'reviews'), { recursive: true })
  const cur = await loadReview(docsDir, p)
  cur.rounds.push(round)
  await writeFile(file, JSON.stringify(cur, null, 2) + '\n', 'utf8')
  return cur
}
