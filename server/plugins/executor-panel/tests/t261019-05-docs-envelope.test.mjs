/**
 * t261019-05: the executor panel's Docs tab must read the workbench docs-tree in
 * BOTH shapes. The live endpoint answers {ok:true, result:{groups}}; reading
 * state.docs.groups off the envelope printed "The library is empty for this
 * scope." for every project, and countDocsTree could only ever answer null
 * ("— pages"). A bare tree (fixtures, older stubs) must keep working.
 */
import { readFileSync } from 'node:fs'
import { countDocsTree } from '../src/host/page-logic.ts'

const PAGE = readFileSync(new URL('../src/host/panel-page.ts', import.meta.url), 'utf8')
let fails = 0
const ok = (cond, name, detail = '') => {
  if (cond) { console.log('ok   ' + name); return }
  fails += 1; console.log('FAIL ' + name + (detail ? ' — ' + detail : ''))
}

const envelope = { ok: true, result: { empty: false, groups: [
  { dir: '', files: [{ rel: 'README.md' }, { rel: 'terminology.md' }] },
  { dir: 'design', files: [{ rel: 'design/x.md' }] },
] } }
const bare = { groups: [{ dir: '', files: [{ rel: 'a.md' }] }] }

ok(countDocsTree(envelope) === 3, 'countDocsTree reads the envelope (result.groups)', String(countDocsTree(envelope)))
ok(countDocsTree(bare) === 1, 'countDocsTree still reads a bare tree', String(countDocsTree(bare)))
ok(countDocsTree(null) === null, 'malformed input stays null, never a fabricated count')
ok(/state\.docs\s*&&\s*state\.docs\.result/.test(PAGE),
   'renderDocs unwraps the envelope before reading groups')
ok(!/var d=state\.docs;\s*\n/.test(PAGE),
   'the bare-only read is gone (that was the empty-library bug)')
console.log(fails === 0 ? 'done 1' : 'done 0')
process.exit(fails === 0 ? 0 : 1)
