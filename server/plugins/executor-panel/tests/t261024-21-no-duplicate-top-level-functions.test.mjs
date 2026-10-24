/**
 * t261024-21: guard against duplicate top-level function declarations in the
 * executor-panel page. panel-page.ts is one big closure; two same-named
 * `function` declarations at closure top level are BOTH hoisted and the LATER
 * one silently wins everywhere — that shadowing left the Epics tab blank
 * (a later metrics renderEpics twin won over the tab's renderer) and the same
 * mechanism left a stale openTicketInHost twin as dead code.
 *
 * Two-space indentation marks closure-level declarations in this file (nested
 * declarations sit deeper), so a line-start-anchored scan is the detector:
 *   - positive control: the fixed panel-page.ts has zero duplicated names;
 *   - negative control: a synthetic source with two same-named top-level
 *     functions is reported, while a same-named NESTED function does not count.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const REPO = join(fileURLToPath(import.meta.url), '..', '..', '..', '..', '..')
const PAGE_PATH = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')

// Returns the sorted list of closure-top-level function names declared more
// than once in `src`. Anchor at line start: exactly two leading spaces.
const dupNames = (src) => {
  const counts = new Map()
  for (const line of src.split('\n')) {
    const m = /^  function ([A-Za-z_$][\w$]*)/.exec(line)
    if (m) counts.set(m[1], (counts.get(m[1]) || 0) + 1)
  }
  return [...counts.entries()].filter(([, n]) => n > 1).map(([name]) => name).sort()
}

let fails = 0
const ok = (cond, name, detail = '') => {
  if (cond) { console.log('ok   ' + name); return }
  fails += 1; console.log('FAIL ' + name + (detail ? ' — ' + detail : ''))
}

// ---- positive control: the fixed page ----
const PAGE = readFileSync(PAGE_PATH, 'utf8')
const dups = dupNames(PAGE)
ok(dups.length === 0, 'panel-page.ts has no duplicate top-level function declarations',
   'duplicates: ' + dups.join(', '))

// ---- negative control: the detector catches a real twin ----
const BAD = [
  '  function renderThing(a){',
  '    var inner = function renderThing(){ return 1 }', // nested, deeper indent: must NOT count
  '  }',
  '  function renderThing(b){ return b }',
  '  function other(){',
  '    function nested(){ return 2 }',
  '  }'
].join('\n')
ok(JSON.stringify(dupNames(BAD)) === JSON.stringify(['renderThing']),
   'the detector reports a duplicated top-level name (and ignores a nested same-name)',
   'got: ' + JSON.stringify(dupNames(BAD)))

// ---- negative control: clean synthetic source stays clean ----
ok(dupNames('  function a(){}\n  function b(){}\n').length === 0,
   'the detector reports nothing on a duplicate-free source')

console.log(fails === 0 ? 'done 1' : 'done 0')
process.exit(fails === 0 ? 0 : 1)
