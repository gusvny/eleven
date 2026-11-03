#!/usr/bin/env node
/**
 * t261102-09-file-claim.mjs — L1 battery for the middle-column file pane model.
 *
 * Scope (white box): the pure rules this ticket adds, and nothing else.
 *
 *   A. The claim matrix: text-like suffixes are claimed; image, PDF and HTML are not,
 *      so the builtin right preview keeps them exactly as today; a non-address string
 *      is never claimed (it falls back instead of throwing in the tab slot).
 *   B. The address grammar (a mirror of the dsh helper, which is not on the platform
 *      module table): both scopes, the drive letter, UNC, encoded segments, query and
 *      fragment suffixes, and a malformed matrix that must answer null and never throw.
 *   C. Display rules: title, extension, line numbering, line clamping, the initial view
 *      (a line-carrying request opens the source view for every claimed kind).
 *   D. Refusal wording: every reason yields one line that carries the path; a route that
 *      is not served at all gets its own name and its own hint, never a bare status.
 *   E. The one-slot store: the same address reuses one entry and only moves the line, a
 *      different address takes a new sequence, close empties the slot.
 *
 * Run: node server/plugins/workbench/tests/t261102-09-file-claim.mjs (node >= 22 native
 * type stripping; .ts imported directly). No IO, no DOM, no network.
 */
import assert from 'node:assert/strict'
import {
  CLAIMED_EXTENSIONS,
  claimsTextFile,
  clampLine,
  describeReadFailure,
  extensionOf,
  fileRefusalLine,
  fileTitleOf,
  initialViewKind,
  lineNoteOf,
  lineOfParams,
  numberedLines,
  parseFileAddress,
  planSourceRows,
  SOURCE_ROW_LIMIT,
  textKindOf,
} from '../src/client/file-pane-model.ts'
import {
  closeFileOpen,
  readFileOpenRequest,
  requestFileOpen,
  subscribeFileOpen,
} from '../src/client/file-open-request.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) {
    pass += 1
    console.log(`  ok ${label}`)
  } else {
    fail += 1
    console.error(`  FAIL ${label}`)
  }
}
function section(title) {
  console.log(`\n== ${title}`)
}

/** Build a session-scope address the same way the dsh helper does. */
function sessionAddress(sessionId, path) {
  const encoded = path.split('/').map((p) => encodeURIComponent(p).replace(/%3A/gi, ':')).join('/')
  return `dsh-resource://file/session/${encodeURIComponent(sessionId)}/${encoded}`
}

/* ---------------------------------------------------------------- A. claim matrix */

section('A. Claim matrix (text claimed; image, PDF and HTML left to the builtin preview)')
{
  for (const ext of ['md', 'markdown', 'mdx', 'txt', 'log', 'csv', 'json', 'yaml', 'yml', 'toml', 'ts', 'tsx', 'py', 'sh', 'go', 'rs', 'sql', 'css', 'patch']) {
    ok(claimsTextFile(sessionAddress('s1', `/repo/notes/file.${ext}`)), `claims .${ext}`)
  }
  for (const ext of ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'pdf', 'html', 'htm']) {
    ok(!claimsTextFile(sessionAddress('s1', `/repo/x/file.${ext}`)), `does not claim .${ext} (builtin preview unchanged)`)
  }
  ok(!CLAIMED_EXTENSIONS.includes('png') && !CLAIMED_EXTENSIONS.includes('pdf') && !CLAIMED_EXTENSIONS.includes('html'),
    'the claim table holds no image, PDF or HTML suffix')
  ok(claimsTextFile('dsh-resource://file/absolute/Users/me/repo/a.md'), 'a text path in the absolute scope is claimed')
  ok(!claimsTextFile('dsh-resource://file/absolute/Users/me/repo/a.png'), 'an image in the absolute scope is not claimed')
  ok(!claimsTextFile('dsh-resource://other/x.md'), 'another resource type is not claimed')
  ok(!claimsTextFile('not-an-address'), 'a non-address string is not claimed (fallback, no throw)')
  ok(!claimsTextFile(undefined) && !claimsTextFile(null) && !claimsTextFile(42) && !claimsTextFile({}), 'a non-string is not claimed and does not throw')
  ok(!claimsTextFile(sessionAddress('s1', '/repo/no-extension')), 'a suffixless path is not claimed')
  ok(!claimsTextFile(sessionAddress('s1', '/repo/.gitignore')), 'a dotfile is not claimed (not in the table)')
}

/* ---------------------------------------------------------------- B. address grammar */

section('B. Address grammar (session / absolute / malformed)')
{
  const s = parseFileAddress(sessionAddress('session-abc', 'sub/a b.md'))
  ok(s?.scope === 'session' && s.sessionId === 'session-abc' && s.path === 'sub/a b.md', 'session: id and path decode (space)')

  const hash = parseFileAddress(sessionAddress('s1', 'a#b.md'))
  ok(hash?.path === 'a#b.md', 'an encoded # stays in the path (not a fragment)')

  const suffix = parseFileAddress('dsh-resource://file/session/s1/a.md?line=3#L3')
  ok(suffix?.scope === 'session' && suffix.path === 'a.md', 'query and fragment suffixes are cut')

  const abs = parseFileAddress('dsh-resource://file/absolute/Users/me/repo/a.md')
  ok(abs?.scope === 'absolute' && abs.path === '/Users/me/repo/a.md', 'absolute: the leading slash comes back')
  ok(abs?.sessionId === '', 'absolute: no sessionId')

  const drive = parseFileAddress('dsh-resource://file/absolute/C:/work/a.ts')
  ok(drive?.path === 'C:/work/a.ts', 'absolute: a Windows drive letter takes no leading slash')

  const unc = parseFileAddress('dsh-resource://file/absolute//server/share/a.txt')
  ok(unc?.path === '//server/share/a.txt', 'absolute: UNC keeps its double slash')

  const relative = parseFileAddress('dsh-resource://file/session/s1/.sandbar/plan.md')
  ok(relative?.path === '.sandbar/plan.md', 'session: a relative path stays as it is (dot directory)')

  for (const bad of [
    '', 'dsh-resource://file/', 'dsh-resource://file/session', 'dsh-resource://file/session/s1',
    'dsh-resource://file/session//a.md', 'dsh-resource://file/absolute', 'dsh-resource://file/absolute/',
    'dsh-resource://file/absolute//', 'file:///tmp/a.md', 'dsh-resource://file/unknown/x.md',
    'dsh-resource://file/session/s1/%E0%A4%A.md', null, undefined, 42, {}, [],
  ]) {
    let threw = false
    let parsed = null
    try {
      parsed = parseFileAddress(bad)
    } catch {
      threw = true
    }
    ok(!threw && parsed === null, `a malformed address answers null and does not throw: ${JSON.stringify(bad)}`)
  }
}

/* ---------------------------------------------------------------- C. display rules */

section('C. Title / suffix / line numbering / line target')
{
  ok(fileTitleOf(sessionAddress('s1', '/repo/design/a b.md')) === 'a b.md', 'the title is the decoded basename')
  ok(fileTitleOf('not-an-address') === 'not-an-address', 'a non-address title falls back to the string')
  ok(fileTitleOf(undefined) === 'file', 'a non-string title does not throw')

  ok(extensionOf('/a/b.MD') === 'md', 'the suffix is lower-cased')
  ok(extensionOf('/a/b/c') === '' && extensionOf(42) === '', 'no suffix / non-string reads empty')
  ok(textKindOf('/a/b.md') === 'markdown' && textKindOf('/a/b.ts') === 'plain', 'the render kind follows the suffix')

  ok(numberedLines('a\nb\n').length === 2, 'line numbering drops one trailing empty row')
  ok(numberedLines('').length === 1 && numberedLines('')[0] === '', 'an empty file still has one row (no blank pane)')
  ok(numberedLines(42)[0] === '', 'non-string content does not throw')
  ok(numberedLines('a\n\nb').length === 3, 'an inner empty row stays')
  ok(SOURCE_ROW_LIMIT === 5000, 'the source view cap is a stated constant')

  // The clip note must state a fact. The acceptance walkthrough caught the earlier rule
  // (compare the rendered rows with the HOST's physical line count) announcing
  // "showing the first 2 of 3 lines" for an ordinary two-line file, because a file ending
  // in a newline counts one empty tail line on the host side while the view drops it.
  {
    const two = planSourceRows('line1\nline2\n')
    ok(two.rows.length === 2 && two.total === 2 && two.clipped === false, 'a two-line file that ends in a newline reports NO clip')
    const noTail = planSourceRows('line1\nline2')
    ok(noTail.rows.length === 2 && noTail.total === 2 && noTail.clipped === false, 'the same file without the trailing newline reports NO clip')
    const empty = planSourceRows('')
    ok(empty.rows.length === 1 && empty.total === 1 && empty.clipped === false, 'an empty file reports NO clip')
    const huge = planSourceRows(Array.from({ length: SOURCE_ROW_LIMIT + 1 }, (_, i) => `l${i}`).join('\n'))
    ok(huge.rows.length === SOURCE_ROW_LIMIT && huge.total === SOURCE_ROW_LIMIT + 1 && huge.clipped === true,
      'a file past the cap reports the clip, with the rendered and true counts')
    const exact = planSourceRows(Array.from({ length: SOURCE_ROW_LIMIT }, (_, i) => `l${i}`).join('\n'))
    ok(exact.clipped === false && exact.rows.length === SOURCE_ROW_LIMIT, 'a file exactly at the cap reports NO clip')
    ok(planSourceRows(42).clipped === false && planSourceRows(42).total === 1, 'malformed content does not throw')
  }

  ok(clampLine(3, 10) === 3, 'clamp: in range stays')
  ok(clampLine(0, 10) === 0 && clampLine(-5, 10) === 0, 'clamp: zero and negative mean no line')
  ok(clampLine(99, 10) === 10, 'clamp: past the end lands on the last row')
  ok(clampLine(NaN, 10) === 0 && clampLine('abc', 10) === 0, 'clamp: NaN and a non-number mean no line')
  ok(clampLine('4', 10) === 4, 'clamp: a numeric string reads')
  ok(clampLine(3, 0) === 0, 'clamp: no content means no line')

  ok(lineOfParams({ line: 7 }) === 7, 'the line in the navigation params reads')
  ok(lineOfParams({ line: 2.9 }) === 2, 'the line is floored')
  ok(lineOfParams({ line: 0 }) === 0 && lineOfParams({ line: 'x' }) === 0, 'a malformed line means no line')
  ok(lineOfParams(undefined) === 0 && lineOfParams(null) === 0 && lineOfParams('x') === 0, 'a non-object param does not throw')

  ok(initialViewKind('markdown', 0) === 'rendered', 'markdown without a line opens rendered')
  ok(initialViewKind('markdown', 5) === 'source', 'markdown with a line opens source (the line is reachable)')
  ok(initialViewKind('plain', 0) === 'source', 'plain text always opens source')
  ok(lineNoteOf(3, 10)?.row === 3 && lineNoteOf(3, 10)?.text === 'line 3', 'a line inside the file is shown as itself')
  ok(lineNoteOf(999, 2)?.row === 2 && String(lineNoteOf(999, 2)?.text).includes('past the end'),
    'a line past the end says so instead of pretending the last row was requested')
  ok(String(lineNoteOf(999, 2)?.text).includes('(2 lines)'), 'the past-the-end note carries the real row count')
  ok(lineNoteOf(0, 10) === null && lineNoteOf(NaN, 10) === null && lineNoteOf(3, 0) === null, 'no line means no note')
}

/* ---------------------------------------------------------------- D. refusal wording */

section('D. Refusal wording (the path is always on the line)')
{
  for (const reason of ['outside-roots', 'not-found', 'is-directory', 'too-large', 'not-utf8', 'unreadable',
    'no-registered-roots', 'session-workspace-unknown', 'bad-path', 'bad-session']) {
    const line = fileRefusalLine(reason, '/repo/a.md')
    ok(line.includes('/repo/a.md'), `reason ${reason} carries the path`)
    ok(line.startsWith('Cannot open '), `reason ${reason} is a full sentence`)
  }
  ok(fileRefusalLine('mystery', '/repo/a.md').includes('/repo/a.md'), 'an unknown reason still carries the path')
  ok(fileRefusalLine('not-found', '').includes('(no path)'), 'a missing path is named too')
  ok(fileRefusalLine('not-found', '/a.md', 'extra words').includes('extra words'), 'the server words may be attached')

  const fromBody = describeReadFailure(200, JSON.stringify({ ok: false, reason: 'too-large', path: '/big.log', error: 'the file is 2097152 bytes' }), '/big.log')
  ok(fromBody.reason === 'too-large' && fromBody.message.includes('/big.log') && fromBody.message.includes('2097152'), 'a failed read uses the body reason and words')

  const routeGone = describeReadFailure(404, '<html>not found</html>', '/repo/a.md')
  ok(routeGone.reason === 'route-missing' && routeGone.message.includes('/repo/a.md'), 'a non-JSON 404 means the route is not served')
  ok(/restart|old code/.test(routeGone.message), 'the 404 line names the stale-console cause')

  const other = describeReadFailure(500, '', '/repo/a.md')
  ok(other.reason === 'http-500' && other.message.includes('/repo/a.md'), 'another status is named')

  const empty = describeReadFailure(0, '', '/repo/a.md')
  ok(empty.reason === 'network' && empty.message.includes('/repo/a.md'), 'no answer at all is named network')

  const okTrue = describeReadFailure(200, JSON.stringify({ ok: true, result: {} }), '/repo/a.md')
  ok(okTrue.reason === 'http-200' && okTrue.message.includes('/repo/a.md'), 'ok:true without content is named, never blank')
}

/* ---------------------------------------------------------------- E. one-slot store */

section('E. One-slot store (one view per file; a new file takes a new sequence)')
{
  closeFileOpen()
  ok(readFileOpenRequest() === null, 'starts empty')

  const seen = []
  const unsubscribe = subscribeFileOpen(() => { seen.push(readFileOpenRequest()) })

  const first = requestFileOpen({ address: 'dsh-resource://file/session/s1/a.md', scope: 'session', sessionId: 's1', path: 'a.md', line: 3 })
  ok(readFileOpenRequest() === first, 'the request enters the slot with a stable snapshot')
  ok(first.line === 3 && first.seq === 1, 'the first request carries its line and sequence')

  const again = requestFileOpen({ address: 'dsh-resource://file/session/s1/a.md', scope: 'session', sessionId: 's1', path: 'a.md', line: 10 })
  ok(again.seq === first.seq, 'the same address keeps the sequence (one view)')
  ok(again.revision > first.revision, 'the same address bumps the revision (re-scroll, no remount)')
  ok(readFileOpenRequest().line === 10, 'the same address only moves the line')

  const other = requestFileOpen({ address: 'dsh-resource://file/session/s1/b.md', scope: 'session', sessionId: 's1', path: 'b.md', line: 0 })
  ok(other.seq === first.seq + 1, 'a different address takes a new sequence')
  ok(readFileOpenRequest() === other, 'the slot now holds the new request')

  ok(seen.length >= 3, 'every subscriber is notified on change')

  const badLine = requestFileOpen({ address: 'x', scope: 'absolute', sessionId: '', path: '/a.md', line: Number.NaN })
  ok(badLine.line === 0, 'a NaN line normalizes to none')

  // The published anchor is the store API itself, so a second reader of the page
  // (the integration case, a debug probe) can find it without importing this module.
  const anchor = Object.getOwnPropertySymbols(globalThis)
    .find((sym) => String(sym.description ?? '').startsWith('sandbar.workbench.fileOpen'))
  const published = anchor === undefined ? null : globalThis[anchor]
  ok(published !== null && typeof published.readFileOpenRequest === 'function', 'the anchor exposes readFileOpenRequest')
  ok(['requestFileOpen', 'readFileOpenRequest', 'subscribeFileOpen', 'closeFileOpen']
    .every((k) => typeof published[k] === 'function'), 'the anchor exposes the whole declared API')
  ok(published.readFileOpenRequest() !== null && published.readFileOpenRequest().address === 'x',
    'a reader of the anchor sees the same slot')

  // A caller that knows only the address must still get the right scope (the seat and
  // the integration case hand {sessionId, path, line, address}, never a scope).
  const derivedSession = requestFileOpen({ address: 'dsh-resource://file/session/s9/a.md', sessionId: 's9', path: 'a.md', line: 4 })
  ok(derivedSession.scope === 'session', 'a session id implies the session scope')
  const derivedAbsolute = requestFileOpen({ address: 'dsh-resource://file/absolute/tmp/a.md', path: '/tmp/a.md', line: 0 })
  ok(derivedAbsolute.scope === 'absolute' && derivedAbsolute.sessionId === '', 'no session id implies the absolute scope')

  closeFileOpen()
  ok(readFileOpenRequest() === null, 'close empties the slot (Back or the close control)')
  const afterClose = seen.length
  closeFileOpen()
  ok(seen.length === afterClose, 'a second close does not notify again')

  unsubscribe()
  const beforeLonely = seen.length
  requestFileOpen({ address: 'y', scope: 'absolute', sessionId: '', path: '/b.md', line: 0 })
  ok(seen.length === beforeLonely, 'an unsubscribed listener is not notified')
  closeFileOpen()
}

console.log(`\nt261102-09-file-claim: pass=${pass} fail=${fail}`)
assert.equal(fail, 0, `${fail} assertion(s) failed`)
process.exit(fail === 0 ? 0 : 1)
