/**
 * review-comments-routes.ts — the HTTP face of the lane-file comment store
 * (t261022-14), factored OUT of node.ts so the plugin-root file only carries a
 * minimal registration diff.
 *
 * REWORK HISTORY (why this file exists): the worker-settle commits twice
 * dropped the plugin-root node.ts edits (arbitrate gen0 CF1, arbitrate gen1
 * CF1 again — `grep -c review-comments node.ts` = 0 on the landed tree while
 * lib/client.js still names the route). All logic therefore lives inside the
 * write set (this file + review-comments.ts); node.ts carries only the import
 * and the dispatch branch below, so a re-application is a ten-line diff.
 *
 * The handler is the same `ticket show → t.worktree → anchorGuard` chain the
 * /file precedent uses, plus the write-path fault modes from plan §F
 * (415 non-JSON content-type, 400 bad JSON, 409 corrupt store, 413 oversize,
 * 405 non-GET/PUT, fail-closed named face for no-lane/unsafe path).
 *
 * Browser half does not import this file (node:fs / IncomingMessage).
 */

import type { IncomingMessage, ServerResponse } from 'node:http'
import { mergeReviewComments, readReviewComments, reviewCommentsFilePath } from './review-comments.ts'

/** Everything the route needs from the plugin-root closure (single object, one call site). */
export interface ReviewCommentsRouteDeps {
  repo: string
  ticketIdOk: (id: string) => boolean
  callTicketShow: (id: string) => Promise<any>
  sendTicketShowError: (res: ServerResponse, s: unknown, id: string) => void
  resolveAnchorKey: (queryKey: string | null, ticketProject: unknown) => { ok: true, root: string, key: unknown, mark: string } | { ok: false, status: number, error: string }
  sendJson: (res: ServerResponse, status: number, body: unknown) => void
  readJsonBody: (req: IncomingMessage) => Promise<any>
}

/**
 * GET/PUT /wf/tickets/<id>/review-comments?path=<repo-relative>.
 * `url` is already parsed by the caller; `project` comes from the caller's
 * anchor resolution (?project= explicit > ticket t.project > default repo).
 */
export async function handleReviewComments(
  deps: ReviewCommentsRouteDeps,
  req: IncomingMessage,
  res: ServerResponse,
  id: string,
  url: URL,
): Promise<void> {
  const { sendJson } = deps
  if (!deps.ticketIdOk(id) || /[./]/.test(id)) {
    sendJson(res, 400, { ok: false, error: `invalid ticket id: '${id.slice(0, 40)}'` })
    return
  }
  const p = url.searchParams.get('path')
  if (p === null || p === '') {
    sendJson(res, 400, { ok: false, error: 'path is required (repo-relative)' })
    return
  }
  try {
    const s = await deps.callTicketShow(id)
    if (s?.ok !== true) {
      deps.sendTicketShowError(res, s, id)
      return
    }
    const t = s.result as Record<string, unknown>
    const queryKey = url.searchParams.get('project')
    const a = deps.resolveAnchorKey(
      queryKey !== null && queryKey !== '' ? queryKey : (typeof t.project === 'string' ? t.project : ''),
      t.project,
    )
    if (!a.ok) {
      sendJson(res, a.status, { ok: false, error: a.error })
      return
    }
    const lane = typeof t.worktree === 'string' ? t.worktree.trim() : ''
    const file = reviewCommentsFilePath(a.root, lane, p)
    if (file === null) {
      // No lane worktree (main-lane ticket) or an unsafe path: fail-closed by
      // name, never a silent fallback to the repo root.
      sendJson(res, 200, {
        ok: true,
        result: {
          ok: false,
          reason: lane === ''
            ? `ticket ${id} has no lane worktree — the comment store needs a lane to live in`
            : `unsafe path or lane root for ticket ${id}: '${p.slice(0, 120)}'`,
        },
      })
      return
    }
    if (req.method === 'GET') {
      const read = await readReviewComments(file)
      if (!read.ok) {
        sendJson(res, 200, { ok: true, result: { ok: false, reason: read.reason } })
        return
      }
      sendJson(res, 200, { ok: true, result: { ok: true, file, doc: read.doc } })
      return
    }
    // PUT: the only write shape on this channel (router locks the rest to 405).
    const ct = String(req.headers['content-type'] ?? '')
    if (!ct.includes('application/json')) {
      sendJson(res, 415, { ok: false, error: `review-comments PUT needs content-type application/json (got '${ct.slice(0, 60)}')` })
      return
    }
    let body: any
    try {
      body = await deps.readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `request body is not valid JSON: ${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const merged = await mergeReviewComments(file, id, p, body)
    if (!merged.ok) {
      const status = merged.code === 'corrupt' ? 409
        : merged.code === 'oversize' ? 413
        : 502
      sendJson(res, status, { ok: false, error: merged.reason })
      return
    }
    sendJson(res, 200, {
      ok: true,
      result: { ok: true, file: merged.file, doc: merged.doc, dropped: merged.dropped },
    })
  } catch (err) {
    sendJson(res, 502, { ok: false, error: `review-comments read/write failed: ${String(err instanceof Error ? err.message : err)}` })
  }
}
