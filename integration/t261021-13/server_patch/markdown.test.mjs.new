/**
 * markdown.test.mjs —— renderMarkdown 渲染器 UT（t261004-16 证据 6a/6b）。
 *  - 敌意输入（票面点名清单）：任何输入标签不得以标签形态存活；不抛异常；输出有界。
 *  - 真账本形状样本：粗体对/行内代码/无序列表渲染后字面标记必须消失。
 * 全桩，零外部源、零端口。
 */
import { assert, done } from './lib.mjs'
import { renderMarkdown } from '../src/host/markdown.ts'

let n = 0

// ---- 6a: hostile inputs ----
const HOSTILE = [
  '<img src=x onerror=alert(1)>',
  '</script><script>alert(1)</script>',
  '<a href="javascript:alert(1)">x</a>',
  '[x](javascript:alert(1))',
  '[x](data:text/html;base64,PHNjcmlwdD4=)',
  '```js\nunclosed fence with <b>html</b> inside',
  'x'.repeat(10000),
  '- a\n  - a1\n  - a2\n- b\n1. one\n2. two',
]
for (const input of HOSTILE) {
  let out = null
  try { out = renderMarkdown(input) } catch (e) {
    assert(false, 'no exception for hostile input ' + JSON.stringify(input.slice(0, 40)))
  }
  // no tag from the input survives as a tag: strip everything we generated,
  // then no '<' may remain (generated tags are balanced well-formed known names,
  // so compare: remove generated element names, any leftover raw '<' is a leak).
  const stripped = out.replace(/<\/?(p|h1|h2|h3|h4|ul|ol|li|blockquote|pre|code|strong|em|a|br)\b[^>]*>/g, '')
  assert(!/[<>]/.test(stripped), 'no input tag survives as a tag: ' + JSON.stringify(input.slice(0, 40)) + ' -> ' + stripped.slice(0, 120))
  assert(out.length < input.length * 20 + 5000, 'output length bounded for ' + input.length + ' char input')
  n++
}

// specifically: script tag content never becomes a script element
{
  const out = renderMarkdown('</script><script>alert(1)</script>')
  assert(!/<script/i.test(out), 'script never renders as an element')
  assert(!/<(script|img)\b/i.test(renderMarkdown('<img src=x onerror=alert(1)>')), 'img never renders as an element (onerror can only be inert text)')
  n++
}

// links: allowed schemes get the safety attributes, banned schemes degrade to text
{
  const ok = renderMarkdown('[docs](https://example.com/a?b=1&c=2)')
  assert(ok.includes('href="https://example.com/a?b=1&amp;c=2"'), 'https link href kept (escaped query)')
  assert(ok.includes('target="_blank"'), 'target=_blank present')
  assert(ok.includes('rel="noopener noreferrer"'), 'rel noopener present')
  const mail = renderMarkdown('[me](mailto:a@b.c)')
  assert(mail.includes('href="mailto:a@b.c"'), 'mailto link kept')
  const js = renderMarkdown('[x](javascript:alert(1))')
  assert(!/<a /.test(js), 'javascript: link dropped')
  const data = renderMarkdown('[x](data:text/html,hi)')
  assert(!/<a /.test(data), 'data: link dropped')
  n++
}

// ---- required element coverage ----
{
  const md = '# Title\n\nSome **bold** and *ital* and `code`.\n\n```py\nprint("<b>")\n```\n\n- item one\n- item two\n\n1. first\n2. second\n\n> quoted text\n\n[site](http://x.io)'
  const out = renderMarkdown(md)
  assert(out.includes('<h1>Title</h1>'), 'heading renders')
  assert(out.includes('<strong>bold</strong>'), 'bold renders')
  assert(out.includes('<em>ital</em>'), 'italic renders')
  assert(out.includes('<code>code</code>'), 'inline code renders')
  assert(out.includes('<pre><code>print(&quot;&lt;b&gt;&quot;)</code></pre>'), 'fence escaped into pre+code, html inside inert')
  assert((out.match(/<li>/g) || []).length === 4, 'bullet + numbered list items render')
  assert(out.includes('<ul>') && out.includes('<ol>'), 'ul and ol both present')
  assert(out.includes('<blockquote><p>quoted text</p></blockquote>'), 'blockquote renders')
  assert(out.includes('<a href="http://x.io"'), 'plain http link renders')
  n++
}

// plain prose with no markdown keeps line breaks (single <p>, raw newline kept)
{
  const out = renderMarkdown('line one\nline two\nline three')
  assert(out === '<p>line one\nline two\nline three</p>', 'plain prose stays one paragraph with line breaks: ' + JSON.stringify(out))
  n++
}

// unclosed fence: everything after the opening fence is code, no exception
{
  const out = renderMarkdown('```js\nvar a = "<b>not bold</b>";')
  assert(out.includes('<pre><code>'), 'unclosed fence still opens pre+code')
  assert(!/<b>/.test(out), 'unclosed fence content stays escaped')
  n++
}

// nested list renders nested ul
{
  const out = renderMarkdown('- a\n  - a1\n  - a2\n- b')
  assert(out.includes('<ul><li>a<ul>'), 'nested list nests: ' + out)
  n++
}

// ---- 6b: real requests.jsonl shapes render with markers gone ----
// Shape samples mirroring the live ledger (bold pair / inline code span / bullet
// list). Fixtures are literal strings here — no external file dependency.
const SAMPLES = [
  'Please **update the lockfile** before the merge, the build is red.',
  'Run `python3 integration/lint_tests.py` and paste the output, thanks.',
  'Three things:\n\n- fix the cap\n- add the test\n- write the handoff',
]
for (const s of SAMPLES) {
  const out = renderMarkdown(s)
  assert(!out.includes('**'), 'no literal bold marker left: ' + s.slice(0, 30))
  assert(!out.includes('`'), 'no literal backtick left: ' + s.slice(0, 30))
  assert(!/\n- /.test(out), 'no literal bullet marker left: ' + s.slice(0, 30))
  n++
}
{
  const out = renderMarkdown(SAMPLES[0])
  assert(out.includes('<strong>update the lockfile</strong>'), 'bold pair becomes strong')
  const out2 = renderMarkdown(SAMPLES[1])
  assert(out2.includes('<code>python3 integration/lint_tests.py</code>'), 'inline code span becomes code')
  const out3 = renderMarkdown(SAMPLES[2])
  assert((out3.match(/<li>/g) || []).length === 3, 'bullet list becomes three li')
  n++
}

// inline mode (option labels): block structure suppressed, inline marks kept
{
  const out = renderMarkdown('# Head\n**Go**', { inline: true })
  assert(!out.includes('<h1>') && !out.includes('<p>'), 'inline mode emits no block elements')
  assert(out.includes('<strong>Go</strong>'), 'inline mode keeps strong')
  n++
}

// 10000-char plain prose: bounded, no exception, still one paragraph shape
{
  const long = ('word '.repeat(2000)).trim()
  const out = renderMarkdown(long)
  assert(out.startsWith('<p>') && out.endsWith('</p>'), 'long prose stays a paragraph')
  assert(out.length < 30000, 'long prose output bounded')
  n++
}

// oversized input is clipped with an explicit notice, not silently
{
  const out = renderMarkdown('y'.repeat(25000))
  assert(out.includes('md-clipped'), 'oversized input gets an explicit clip notice')
  n++
}

// ---- t261021-13: pipe tables (the reader must render tables per the ticket) ----
{
  const out = renderMarkdown('| col a | col b |\n| --- | --- |\n| one | two |')
  assert(out.includes('<table>'), 'pipe table becomes a table element')
  assert(out.includes('<thead>') && out.includes('<th>col a</th>'), 'separator row promotes a header')
  assert(out.includes('<td>one</td>') && out.includes('<td>two</td>'), 'body cells render as td')
  assert(!out.includes('|'), 'no literal pipe survives')
  n++
}
{
  const out = renderMarkdown('| a | b |\n| 1 | <b>hostile</b> |')
  assert(out.includes('<table>'), 'table without a separator row still renders (headerless)')
  assert(!out.includes('<b>hostile</b>'), 'a hostile cell never survives as a tag')
  assert(out.includes('&lt;b&gt;hostile&lt;/b&gt;'), 'a hostile cell stays literal text')
  n++
}
{
  const out = renderMarkdown('| a | b |\n| **x** | `y` |')
  assert(out.includes('<strong>x</strong>') && out.includes('<code>y</code>'), 'inline marks still work inside cells')
  n++
}

done(n)
