#!/usr/bin/env node
/**
 * sc_t261026_03_markdown_everywhere_doc_face.mjs — t261026-03, offline L3.
 *
 * User story: the host clicks a changed markdown file in the ticket Changes
 * list. Design (docs/design/markdown-reviewer-panel-design.md §1) promises
 * EVERY changed markdown file (.md/.markdown, any directory) routes to the
 * reviewer panel and renders a document. Incident (t261025-13, host report
 * 261025): clicking integration/NOTES-landing-queue-261024.md opened an EMPTY
 * panel — indistinguishable from a dead link — because the diff face classified
 * every non-docs markdown as 'code' and shipped no document for it.
 *
 * Intent (this entry uniquely owns it): the diff face serves a rendered
 * document (blocks) for EVERY changed markdown shape in this repo —
 * docs/**, integration/**, root files (CLAUDE.md, README.md), notes/** —
 * judged through the REAL public face computeTicketDiff over a real throwaway
 * git fixture, which is the exact payload the GET review-comments route hands
 * the panel. Not owned here: the panel's rendered DOM face
 * (t261022-14-review-panel-face), the lane-file store contract
 * (t261022-14-review-comments-lane-store), classifier truth tables at unit
 * level (developer L1).
 *
 * Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
 * 3099/7233. Three states (t260904-12, no SKIP): SUMMARY pass=N fail=K
 * env_fail=E na=W; fail>0 or all-na = exit 1; env_fail>0 = exit 2.
 * git missing = ENV_FAIL exit 2.
 */
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const CHANGES_TS = fileURLToPath(new URL('../../server/plugins/workbench/src/host/changes.ts', import.meta.url))
const NODE_MAJOR = Number(process.versions.node.split('.')[0])
const NODE_MINOR = Number(process.versions.node.split('.')[1] || 0)
if (!(NODE_MAJOR > 22 || (NODE_MAJOR === 22 && NODE_MINOR >= 18))) {
  console.log(`ENV_FAIL: node >=22.18 (native type-stripping) required, got ${process.versions.node}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}
try { execFileSync('git', ['--version'], { stdio: 'ignore' }) } catch {
  console.log('ENV_FAIL: git not found on PATH')
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

let passed = 0, failed = 0
const ok = (c, label) => { if (c) { passed++; console.log(`  ok ${label}`) } else { failed++; console.log(`  FAIL ${label}`) } }

const { computeTicketDiff } = await import(CHANGES_TS)

// Fixture: throwaway git repo, base commit carries every shape; working tree
// modifies each. The diff face (base..worktree) is what the reviewer consumes.
const root = mkdtempSync(join(tmpdir(), 't261026-03-'))
const SHAPES = [
  'docs/x.md',
  'integration/NOTES-landing-queue-261024.md', // the incident witness
  'integration/other-note.md',
  'CLAUDE.md',
  'README.md',
  'notes/x.md',
  'UPPER.MD',
  'deck.markdown',
  'app/public/data/x.json',
  'tool.py',
  'crude-no-frontmatter.md', // malformed input: no frontmatter, CRLF
]
try {
  const g = (args, cwd = root) => execFileSync('git', ['-C', cwd, ...args], { stdio: 'pipe' })
  g(['init', '-q'])
  g(['config', 'user.email', 'integ@example.test'])
  g(['config', 'user.name', 'integ'])
  for (const p of SHAPES) {
    mkdirSync(join(root, p, '..'), { recursive: true })
    writeFileSync(join(root, p), `# ${p}\nbase line\n`)
  }
  writeFileSync(join(root, 'app/public/data/x.json'), '{"a": 1}\n')
  g(['add', '-A'])
  g(['commit', '-qm', 'base'])
  const base = g(['rev-parse', 'HEAD']).toString().trim()
  for (const p of SHAPES) {
    if (p.endsWith('.json')) writeFileSync(join(root, p), '{"a": 2, "b": 3}\n')
    else if (p.endsWith('.py')) writeFileSync(join(root, p), 'print("changed")\n')
    else if (p === 'crude-no-frontmatter.md') {
      writeFileSync(join(root, p), 'just prose, no frontmatter\r\nsecond CRLF line\r\n')
    } else writeFileSync(join(root, p), `# ${p}\nbase line\nchanged line\n`)
  }

  const d = await computeTicketDiff(root, { id: 't261026-03', worktree: root, base_ref: base })
  const byPath = new Map((d.files ?? []).map(f => [f.path, f]))
  const get = p => byPath.get(p)

  console.log('\n== A every markdown shape is a rendered document on the diff face')
  for (const p of SHAPES) {
    if (p.endsWith('.json') || p.endsWith('.py')) continue
    const e = get(p)
    ok(e !== undefined, `A ${p} present in diff face`)
    ok(e?.kind === 'doc', `A ${p} kind=doc (got ${e?.kind})`)
    ok(Array.isArray(e?.blocks) && e.blocks.length > 0, `A ${p} renders a non-empty document (blocks=${e?.blocks?.length})`)
  }

  console.log('\n== B the incident witness journey (reader side, not a writer receipt)')
  const w = get('integration/NOTES-landing-queue-261024.md')
  ok(w?.status === 'modified', `B witness status=modified (got ${w?.status})`)
  ok(w?.kind === 'doc' && w?.blocks?.length > 0, 'B the click target now carries a document the panel can render — no empty panel')

  console.log('\n== C data and code classifications untouched')
  const js = get('app/public/data/x.json')
  ok(js?.kind === 'data' && Array.isArray(js?.recon), `C x.json stays kind=data with recon (got ${js?.kind})`)
  ok(!Array.isArray(js?.blocks) || js.blocks.length === 0, 'C json keeps the recon face, no block document')
  const py = get('tool.py')
  ok(py?.kind === 'code' && typeof py.unified === 'string' && py.unified.length > 0, `C tool.py stays kind=code with unified diff (got ${py?.kind})`)
  ok(!Array.isArray(py?.blocks) || py.blocks.length === 0, 'C code keeps the raw viewer (non-markdown non-goal intact)')

  console.log('\n== D no filename special-casing (the rule is the extension)')
  ok(get('integration/other-note.md')?.kind === 'doc' && get('integration/NOTES-landing-queue-261024.md')?.kind === 'doc',
    'D two differently named files in the same non-docs dir both render — no per-file carve-outs')
  ok(get('UPPER.MD')?.kind === 'doc' && get('deck.markdown')?.kind === 'doc', 'D .MD / .markdown spellings render too')

  console.log('\n== E malformed input never blanks the panel')
  ok(get('crude-no-frontmatter.md')?.blocks?.length > 0, 'E frontmatter-less CRLF markdown still renders blocks, no crash')
} catch (err) {
  failed++
  console.log(`  FAIL fixture/diff journey threw: ${err?.message ?? err}`)
} finally {
  rmSync(root, { recursive: true, force: true })
  if (existsSync(root)) { failed++; console.log('  FAIL end-state hygiene: temp fixture repo not removed') } else console.log('  ok end-state hygiene: temp repo removed')
}
console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
process.exit(failed > 0 ? 1 : 0)
