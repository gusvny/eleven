/**
 * markdown.ts — 无依赖的轻量 Markdown 渲染器（供 sandbar-knowledge 知识库插件用）。
 *
 * 支持（docs 知识库设计 §5.1）：
 *   - 标题（#~######）、表格（GFM）、围栏代码块（带语法高亮 + 复制按钮）、
 *     块引用、有序/无序列表、分隔线、段落
 *   - 行内：粗体/斜体/删除线、行内代码、链接、图片
 *
 * 安全口径：先转义所有文本再拼 HTML；链接 URL 拒绝 javascript:/data:/vbscript:。
 * 纯函数（string → string），不碰 DOM，方便 node 冒烟。
 */

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function safeUrl(url: string): string {
  const u = url.trim()
  if (/^(javascript|data|vbscript):/i.test(u)) return '#'
  return u
}

/* ------------------------------------------------------------ 行内渲染 */

function inline(text: string): string {
  const esc = escapeHtml(text)
  // 行内代码优先（反引号包裹）
  const parts = esc.split(/`([^`]*)`/g)
  return parts
    .map((p, idx) => {
      if (idx % 2 === 1) return `<code>${p}</code>`
      return inlineFormat(p)
    })
    .join('')
}

function inlineFormat(s: string): string {
  // 图片 / 链接（先于加粗，避免 URL 内 * 干扰）
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_m, alt: string, url: string) =>
    `<img alt="${alt}" src="${safeUrl(url)}" />`)
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, txt: string, url: string) =>
    `<a href="${safeUrl(url)}">${txt}</a>`)
  // 删除线
  s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>')
  // 粗体
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>')
  // 斜体（避免吃掉粗体里的 *）
  s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
  s = s.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, '$1<em>$2</em>')
  return s
}

/* ------------------------------------------------------------ 代码高亮 */

interface LangSpec { re: RegExp }

const KEYWORDS_JS = 'const|let|var|function|return|if|else|for|while|import|export|from|class|interface|type|new|async|await|this|extends|implements|public|private|readonly|typeof|of|in|throw|try|catch|finally|switch|case|break|default'
const KEYWORDS_PY = 'def|return|import|from|if|elif|else|for|while|class|try|except|finally|with|as|not|in|is|lambda|yield|raise|None|True|False|and|or|pass|global|nonlocal'
const KEYWORDS_BASH = 'if|then|else|fi|for|while|do|done|case|esac|function|echo|export|local|return|source|cd|set|unset'
const KEYWORDS_JSON = 'true|false|null'

function specOf(lang: string): LangSpec {
  const l = lang.toLowerCase()
  if (['js', 'javascript', 'ts', 'tsx', 'typescript', 'jsx'].includes(l)) {
    return { re: new RegExp(`(?<comment>\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)|(?<string>'[^'\\n]*'|"[^"\\n]*"|\`[^\`]*\`)|(?<kw>\\b(?:${KEYWORDS_JS})\\b)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) }
  }
  if (['py', 'python'].includes(l)) {
    return { re: new RegExp(`(?<comment>#[^\\n]*)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<kw>\\b(?:${KEYWORDS_PY})\\b)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) }
  }
  if (['bash', 'sh', 'shell', 'zsh'].includes(l)) {
    return { re: new RegExp(`(?<comment>#[^\\n]*)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<var>\\$\\w+|\\$\\{[^}]+\\})|(?<kw>\\b(?:${KEYWORDS_BASH})\\b)|(?<num>\\b\\d+\\b)`) }
  }
  if (['json'].includes(l)) {
    return { re: new RegExp(`(?<string>"(?:\\\\.|[^"\\\\])*")|(?<kw>\\b(?:${KEYWORDS_JSON})\\b)|(?<num>-?\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)`) }
  }
  if (['yaml', 'yml'].includes(l)) {
    return { re: new RegExp(`(?<comment>#[^\\n]*)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<kw>\\b(?:${KEYWORDS_JSON})\\b)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) }
  }
  if (['html', 'xml', 'css', 'scss', 'less'].includes(l)) {
    return { re: new RegExp(`(?<comment>\\/\\*[\\s\\S]*?\\*\\/|<!--[\\s\\S]*?-->)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<num>#?[0-9a-fA-F]{3,8}\\b|\\b\\d+(?:\\.\\d+)?(?:px|em|rem|%|vh|vw)?\\b)`) }
  }
  return { re: new RegExp(`(?<comment>\\/\\/[^\\n]*|#[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)|(?<string>'[^'\\n]*'|"[^"\\n]*"|\`[^\`]*\`)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) }
}

const TOKEN_CLASS: Record<string, string> = {
  comment: 'tok-c', string: 'tok-s', kw: 'tok-k', num: 'tok-n', var: 'tok-v',
}

function highlight(code: string, lang: string): string {
  const { re } = specOf(lang)
  let out = ''
  let i = 0
  let guard = 0
  while (i < code.length) {
    const sub = code.slice(i)
    const m = re.exec(sub)
    if (!m) {
      out += escapeHtml(sub)
      break
    }
    if (m.index > 0) out += escapeHtml(sub.slice(0, m.index))
    const g = m.groups ?? {}
    const cls = Object.keys(g).find(k => g[k] !== undefined) ?? ''
    const span = cls && TOKEN_CLASS[cls] ? `<span class="${TOKEN_CLASS[cls]}">${escapeHtml(m[0])}</span>` : escapeHtml(m[0])
    out += span
    i += m.index + m[0].length
    if (++guard > 100000) { out += escapeHtml(code.slice(i)); break }
  }
  return out
}

/* ------------------------------------------------------------ 块级渲染 */

function codeBlock(code: string, lang: string): string {
  const body = lang ? highlight(code, lang) : escapeHtml(code)
  const langLabel = lang ? `<span class="md-cl">${escapeHtml(lang)}</span>` : ''
  return `<div class="md-code">${langLabel}<button class="md-copy" data-code="${encodeURIComponent(code)}">复制</button><pre><code>${body}\n</code></pre></div>`
}

/** 把源码按行拆成 HTML。 */
export function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  let html = ''
  let i = 0
  const n = lines.length

  const isBlank = (s: string) => s.trim() === ''

  while (i < n) {
    const line = lines[i]

    if (isBlank(line)) { i++; continue }

    // 围栏代码块
    const fence = line.match(/^```\s*([\w+-]*)/)
    if (fence) {
      const lang = fence[1] ?? ''
      const buf: string[] = []
      i++
      while (i < n && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++ }
      if (i < n) i++ // 跳过收尾 ```
      html += codeBlock(buf.join('\n'), lang)
      continue
    }
    // 缩进代码块（4 空格）
    if (/^ {4}/.test(line)) {
      const buf: string[] = []
      while (i < n && (/^ {4}/.test(lines[i]) || isBlank(lines[i]))) { buf.push(lines[i].replace(/^ {4}/, '')); i++ }
      html += codeBlock(buf.join('\n'), '')
      continue
    }
    // 标题
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) { html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; i++; continue }
    // 分隔线
    if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) { html += '<hr/>'; i++; continue }
    // 块引用
    if (/^>\s?/.test(line)) {
      const buf: string[] = []
      while (i < n && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++ }
      html += `<blockquote>${buf.map(inline).join('<br/>')}</blockquote>`
      continue
    }
    // 表格
    if (line.includes('|') && i + 1 < n && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const headerCells = splitRow(line)
      i += 2 // 跳过表头 + 分隔行
      const rows: string[][] = []
      while (i < n && lines[i].includes('|') && !isBlank(lines[i])) { rows.push(splitRow(lines[i])); i++ }
      let t = '<table><thead><tr>' + headerCells.map(c => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>'
      for (const r of rows) t += '<tr>' + r.map(c => `<td>${inline(c)}</td>`).join('') + '</tr>'
      t += '</tbody></table>'
      html += t
      continue
    }
    // 列表
    const ul = line.match(/^\s*([-*+])\s+(.*)$/)
    const ol = line.match(/^\s*(\d+)\.\s+(.*)$/)
    if (ul || ol) {
      const isOl = !!ol
      const items: string[] = []
      while (i < n) {
        const m = isOl ? lines[i].match(/^\s*\d+\.\s+(.*)$/) : lines[i].match(/^\s*[-*+]\s+(.*)$/)
        if (!m) break
        items.push(inline(m[1]))
        i++
      }
      const tag = isOl ? 'ol' : 'ul'
      html += `<${tag}>` + items.map(it => `<li>${it}</li>`).join('') + `</${tag}>`
      continue
    }
    // 段落（收集到空行或下一个块起点）
    const buf: string[] = [line]
    i++
    while (i < n && !isBlank(lines[i]) && !/^(#{1,6}\s|```|>\s?|\s*[-*+]\s|\s*\d+\.\s)/.test(lines[i])) {
      buf.push(lines[i]); i++
    }
    html += `<p>${buf.map(inline).join('<br/>')}</p>`
  }
  return html
}

function splitRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map(c => c.trim())
}
