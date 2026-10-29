/**
 * t261029-49 — the docs path admission rule: one data file, two readers, one verdict.
 *
 * INTENT: every category docs/index.json registers (design/content/ops/reference/epics)
 * must be openable, while the containment does not move a millimetre (a category name
 * up front, so absolute paths cannot match; the file segment [^/]+, so traversal and
 * nested directories cannot match; a .md extension). The rule is a single data file
 * (doc-path-rule.json) and it has two readers — the node half (node.ts) and the pipeline
 * half (review_store.py). This test feeds ONE fixture table through both and compares
 * verdicts line by line: that is the proof of "one rule", not two hand-copied mirrors.
 *
 * HIGH-LEVEL STEPS:
 *   A. the rule data is self-consistent: the pattern is exactly the alternation of the
 *      categories, and the categories are the index's five (incl. epics); neither reader
 *      carries its own copy.
 *   B. admission: one path under each of the five categories (including real docs/epics
 *      file names) is admitted.
 *   C. the refusal list, by class: traversal, absolute, non-category directories, nested
 *      directories (incl. the declared-but-unopened content/ku interface), wrong
 *      extension, near-miss vocabulary, whitespace/newline shapes, empty string,
 *      backslash, doubled slash.
 *   D. mirror parity (TS <-> Python): the same fixture table goes through node.ts's
 *      DOC_PATH_RE and through review_store.py `show` (a real CLI subprocess); the
 *      verdicts must match on every line.
 *   E. the negative proof against widening: the python refusal names the five-category
 *      rule instead of only saying "illegal".
 *
 * No temporary resources (nothing is created or written; the rule file is read and a
 * read-only subprocess runs).
 */
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { DOC_PATH_CATEGORIES, DOC_PATH_RE } from '../../knowledge/node.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..', '..', '..', '..')  // tests → workbench → plugins → server → repo root
const KNOWLEDGE = join(REPO, 'server', 'plugins', 'knowledge')
const RULE_FILE = join(KNOWLEDGE, 'doc-path-rule.json')
const REVIEW_STORE = join(KNOWLEDGE, 'review_store.py')

let pass = 0, fail = 0, skip = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** The second column of each row is human-readable only (it labels a FAIL line); it never takes part in the verdict. */
// Boundary note: a URL-encoded form (design/..%2f..%2fX.md) never reaches this rule —
// the HTTP layer's URLSearchParams decodes it first, so the rule sees the decoded
// 'design/../../X.md' (that form is in REFUSE below). This table tests the string the
// RULE receives, not the raw query bytes.
const ADMIT = [
  ['design/x.md', 'design page'],
  ['content/x.md', 'content page'],
  ['ops/x.md', 'ops page'],
  ['reference/x.md', 'reference page'],
  ['epics/agent-backend.md', 'the epic page the Docs tab could not open (real file name)'],
  ['epics/concurrency-limit.md', 'another real epic page'],
  ['epics/2026-future-epic.md', 'a file name the epic store may grow into'],
  ['design/平台架构设计.md', 'non-ASCII file name stays admitted (unchanged semantics)'],
  ['reference/lane-editor.md', 'a real reference page'],
]

const REFUSE = [
  // traversal
  ['../CLAUDE.md', 'traversal to the repo root (parent segment)'],
  ['../../etc/passwd', 'double parent traversal'],
  ['design/../design/x.md', 'traversal inside a category'],
  ['epics/../design/x.md', 'traversal out of epics'],
  ['design/../../CLAUDE.md', 'traversal out of design/ (the form the endpoint sees after URL decoding)'],
  // absolute
  ['/etc/passwd', 'absolute path'],
  ['/Users/user/Documents/sandbar/docs/design/x.md', 'absolute path into this very repo'],
  ['file:///etc/passwd', 'URL form'],
  // directories that are not docs/index.json categories
  ['notes/x.md', 'notes/ is a scope, not a docs category'],
  ['other/x.md', 'unknown category'],
  ['src/x.md', 'a source directory'],
  ['docs/design/x.md', 'the docs/ prefix itself is already stripped (index path form)'],
  ['scratch/design/x.md', 'category nested under an unknown directory'],
  // depth: one plain .md per category, no sub-directories
  ['design/sub/x.md', 'a sub-directory under a category'],
  ['epics/sub/x.md', 'a sub-directory under epics'],
  ['content/ku/260725-ku-03.md', 'the declared-but-unopened content/ku/ interface stays refused'],
  ['design//x.md', 'empty segment'],
  ['design/x.md/', 'trailing slash'],
  // extension
  ['design/x.txt', 'wrong extension'],
  ['design/x', 'no extension'],
  ['design/x.md.bak', 'extension suffix'],
  ['design/x.MD', 'extension case'],
  ['design/.md', 'dotfile with no stem'],
  // vocabulary drift / near misses
  ['Design/x.md', 'category case'],
  ['EPICS/x.md', 'category case (the one this ticket adds)'],
  ['epic/x.md', 'singular is not the category name'],
  ['designs/x.md', 'plural is not the category name'],
  // shape / whitespace / separators
  ['', 'empty string'],
  ['design/x.md\n', 'trailing newline (JS $ is end-of-input; Python would allow it under match())'],
  [' design/x.md', 'leading space'],
  ['design/x.md ', 'trailing space'],
  ['design\\x.md', 'backslash separator'],
  ['design/x.md\u0000', 'NUL byte'],
  ['epics', 'directory only, no file'],
  ['epics/', 'directory with a slash, no file'],
]

section('A. one rule, read by both sides')
const rule = JSON.parse(readFileSync(RULE_FILE, 'utf8'))
ok(Array.isArray(rule.categories) && rule.categories.length === 5, 'rule file carries five categories')
ok(rule.categories.join('|') === 'design|content|ops|reference|epics',
  'the categories are docs/index.json five categories (incl. epics): design|content|ops|reference|epics')
ok(rule.pattern === `^(${rule.categories.join('|')})/[^/]+\\.md$`,
  'the pattern is exactly the alternation of those categories plus the unchanged containment tail')
ok(DOC_PATH_CATEGORIES.join('|') === rule.categories.join('|'),
  'node.ts reads the same file (its exported category list matches)')
// Static proof of "one rule": neither reader may carry its own category vocabulary —
// both must read the same file. (The behavioural proof is section D: the fixture table's
// verdicts agree line by line.)
const nodeSrc = readFileSync(join(KNOWLEDGE, 'node.ts'), 'utf8')
ok(!/design\|content\|ops/.test(nodeSrc),
  'node.ts holds no hard-coded category alternation (it derives from doc-path-rule.json)')
ok(nodeSrc.includes("'doc-path-rule.json'"), 'node.ts names the one rule file')
const pySrc = readFileSync(REVIEW_STORE, 'utf8')
ok(!/design\|content\|ops/.test(pySrc),
  'review_store.py holds no hard-coded category alternation (same one file)')
ok(pySrc.includes("'doc-path-rule.json'"), 'review_store.py names the same rule file')
ok(new RegExp(rule.pattern).source === DOC_PATH_RE.source,
  'the node side compiles the rule file pattern verbatim (no second pattern source)')

section('B. admitted: one path under each of the five categories')
for (const [p, why] of ADMIT) ok(DOC_PATH_RE.test(p), `admit ${JSON.stringify(p)} — ${why}`)

section('C. refused: containment guarantees unchanged')
for (const [p, why] of REFUSE) ok(!DOC_PATH_RE.test(p), `refuse ${JSON.stringify(p)} — ${why}`)

section('D. mirror agreement: the same fixtures through review_store.py (real CLI, real subprocess)')
const py = process.env.SANDBAR_TEST_PYTHON || 'python3'
const probe = spawnSync(py, ['-c', 'print(1)'], { encoding: 'utf8' })
if (probe.error || probe.status !== 0) {
  skip += 1
  console.log(`  skip python mirror leg: interpreter unavailable (${py}: ${probe.error?.message ?? probe.status})`)
} else {
  let pyAdmit = 0, pyRefuse = 0
  for (const [p, why] of [...ADMIT.map(([p, w]) => [p, w, true]), ...REFUSE.map(([p, w]) => [p, w, false])]) {
    // A NUL byte cannot travel in argv (an OS limit, not a rule face): that fixture keeps
    // only the node-side verdict, and the skip is stated out loud.
    if (p.includes('\u0000')) {
      skip += 1
      console.log(`  skip python leg for ${JSON.stringify(p)} — carries a NUL byte, argv cannot carry it (the node side already asserts the refusal)`)
      continue
    }
    // review_store.py show <path>: admitted -> exit 0 with ok:true; refused -> exit 1 with ok:false.
    const r = spawnSync(py, [REVIEW_STORE, 'show', p], { encoding: 'utf8', timeout: 30_000 })
    const out = String(r.stdout ?? '').trim()
    const jsVerdict = DOC_PATH_RE.test(p)
    const pyVerdict = r.status === 0 && out.includes('"ok": true')
    if (pyVerdict) pyAdmit += 1; else pyRefuse += 1
    ok(pyVerdict === jsVerdict, `same verdict ${jsVerdict ? 'admit' : 'refuse'} on ${JSON.stringify(p)} — ${why}`
      + (pyVerdict === jsVerdict ? '' : ` (js=${jsVerdict} py=${pyVerdict} exit=${r.status} out=${out.slice(0, 160)})`))
  }
  ok(pyAdmit === ADMIT.length, `python admitted exactly the ${ADMIT.length} admitted fixtures (got ${pyAdmit})`)
  ok(pyRefuse === REFUSE.length - 1, `python refused exactly the ${REFUSE.length - 1} argv-carryable refused fixtures (got ${pyRefuse}; the NUL one is asserted on the node side only)`)

  section('E. the python refusal names the five-category rule (not a vague "illegal path")')
  const refusal = spawnSync(py, [REVIEW_STORE, 'show', 'epics/../design/x.md'], { encoding: 'utf8', timeout: 30_000 })
  ok(refusal.status !== 0, 'traversal refusal is a non-zero exit')
  const msg = String(refusal.stdout ?? '')
  ok(msg.includes('path 不合法'), 'refusal is named as an illegal path')
  for (const cat of ['design', 'content', 'ops', 'reference', 'epics']) {
    ok(msg.includes(cat), `refusal message names the admitted category ${cat}`)
  }
}

console.log(`\nSUMMARY pass=${pass} skip=${skip} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
