/**
 * tests/t261026-03-markdown-classifier-everywhere.mjs — classifier regression
 * (t261026-03): the diff classifier must call every .md/.markdown path a doc,
 * not just files under docs/, so the markdown reviewer receives a document for
 * integration/*.md, CLAUDE.md and notes/** too (design §1 entry rule).
 *
 * Run: node server/plugins/workbench/tests/t261026-03-markdown-classifier-everywhere.mjs
 * Pure offline: the diff-face case builds its own throwaway git repo inside a
 * mkdtemp directory OUTSIDE any repo tree; never touches 3099/7233.
 */
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { classifyPath, computeTicketDiff } from '../src/host/changes.ts'

const execFileP = promisify(execFile)
let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* A: classifier pin over the ticket's six shapes */
{
  ok(classifyPath('docs/x.md') === 'doc', 'A1 docs/x.md -> doc')
  ok(classifyPath('integration/x.md') === 'doc', 'A2 integration/x.md -> doc')
  ok(classifyPath('CLAUDE.md') === 'doc', 'A3 CLAUDE.md -> doc')
  ok(classifyPath('notes/x.md') === 'doc', 'A4 notes/x.md -> doc')
  ok(classifyPath('app/public/data/x.json') === 'data', 'A5 data json -> data')
  ok(classifyPath('tool.py') === 'code', 'A6 .py -> code')
}

/* B: edges — no filename special-casing, extension only */
{
  ok(classifyPath('X.MD') === 'doc', 'B1 uppercase extension')
  ok(classifyPath('a/b/x.markdown') === 'doc', 'B2 .markdown second extension')
  ok(classifyPath('docs/x.json') === 'code', 'B3 json outside app/public/data stays code')
  ok(classifyPath('readme.md') === 'doc', 'B4 root readme.md')
  ok(classifyPath('app/public/data/x.md') === 'doc', 'B5 md under data dir is md first')
  ok(classifyPath('integration/x.mdx') === 'code', 'B6 .mdx is not markdown')
  ok(classifyPath('x.md.bak') === 'code', 'B7 md not a suffix match')
}

/* C: diff face returns a non-null document for a fixture integration/*.md */
{
  let dir = ''
  try {
    dir = await mkdtemp(join(tmpdir(), 't261026-03-'))
    const run = (args, cwd = dir) => execFileP('git', ['-c', 'user.email=t@local', '-c', 'user.name=t', ...args], { cwd })
    await run(['init', '-q'])
    await mkdir(join(dir, 'integration'))
    await writeFile(join(dir, 'integration', 'NOTES-landing-queue.md'), '# Queue\n\nold body\n')
    await run(['add', '.'])
    await run(['commit', '-qm', 'base'])
    // change the fixture file in the working tree (uncommitted, like a lane)
    await writeFile(join(dir, 'integration', 'NOTES-landing-queue.md'), '# Queue\n\nnew body\n')
    const diff = await computeTicketDiff(dir, { id: 't261026-03', worktree: '.', base_ref: 'HEAD' })
    const f = diff.files.find((x) => x.path === 'integration/NOTES-landing-queue.md')
    ok(f !== undefined, 'C1 fixture file present in diff')
    ok(f !== undefined && f.kind === 'doc', 'C2 diff face classifies integration/*.md as doc')
    ok(f !== undefined && Array.isArray(f.blocks) && f.blocks.length > 0, 'C3 doc entry carries non-empty blocks')

    // malformed input: no frontmatter, CRLF endings — must still build blocks
    await writeFile(join(dir, 'integration', 'weird.md'), 'no frontmatter\r\nline two\r\n')
    const diff2 = await computeTicketDiff(dir, { id: 't261026-03', worktree: '.', base_ref: 'HEAD' })
    const g = diff2.files.find((x) => x.path === 'integration/weird.md')
    ok(g !== undefined && g.kind === 'doc' && (g.blocks ?? []).length > 0, 'C4 CRLF/frontmatter-less md still yields blocks')
  } catch (err) {
    failed += 1
    console.error(`FAIL C section threw: ${err && err.stack ? err.stack : err}`)
  } finally {
    if (dir !== '') await rm(dir, { recursive: true, force: true })
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
