/**
 * markdown.ts —— 请求/应答文本的 markdown 渲染器（t261004-16）。
 *
 * 是什么：一个零依赖、单一实现的渲染函数。面板里**所有**展示请求或应答文本的
 * 元素（行头、详情体、选项按钮标签、应答回显）都走它——票面硬性要求「不许写
 * 第二个渲染器」。它同时以两个面目存在：
 *  - UT 直接 import 本函数（tests/markdown.test.mjs）；
 *  - 面板内联脚本经 renderMarkdown.toString() 注入（panel-page.ts）——所以函数体
 *    必须是纯 JS（不得用 TS 独有语法），且**自含**（不引用任何外部标识符）。
 *
 * 安全管线（顺序不可换）：先整串 HTML 转义，再在已转义文本上识别 markdown 标记。
 * 转义先行意味着输入里任何 `<tag>` 只能以字面文本出现，永远成不了标签；链接的
 * scheme 白名单（http/https/mailto）之外一律降级为普通文本展示。
 */

export function renderMarkdown(src, opts) {
  opts = opts || {}
  var MAX_IN = 20000
  var raw = String(src == null ? '' : src)
  var clipped = raw.length > MAX_IN
  if (clipped) raw = raw.slice(0, MAX_IN)
  var inlineOnly = !!opts.inline

  var entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return entities[c] }) }

  var text = esc(raw)

  // ---- inline pass: code spans first (held out), then links, bold, italic ----
  var held = []
  function hold(html) { held.push(html); return '\x00' + (held.length - 1) + '\x00' }

  function safeHref(url) {
    // 白名单之外（javascript:/data:/畸形）一律拒绝——调用方降级为纯文本。
    return /^(https?:|mailto:)/i.test(url)
  }

  function inline(s) {
    // 1. code spans（先摘出，内部不再做任何标记识别）
    s = s.replace(/`([^`\n]+)`/g, function (m, code) { return hold('<code>' + code + '</code>') })
    // 2. links：[label](url)。url 白名单外的整段保持字面（已转义）文本。
    s = s.replace(/\[([^\]\n]*)\]\(([^)\s]*)\)/g, function (m, label, url) {
      if (!safeHref(url)) return m
      return hold('<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + '</a>')
    })
    // 3. bold → strong；4. italic → em（占位符 \x00N\x00 不会被 * 误伤）。
    s = s.replace(/\*\*([^*\n]+)\*\*/g, function (m, t) { return '<strong>' + t + '</strong>' })
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, function (m, pre, t) { return pre + '<em>' + t + '</em>' })
    s = s.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, function (m, pre, t) { return pre + '<em>' + t + '</em>' })
    return s
  }

  function unhold(s) {
    return s.replace(/\x00(\d+)\x00/g, function (m, i) { return held[Number(i)] })
  }

  function inlineHtml(s) { return unhold(inline(s)) }

  // ---- block pass ----
  function renderBlocks(lines) {
    var out = []
    var i = 0
    var para = []
    function flushPara() {
      if (!para.length) return
      out.push('<p>' + inlineHtml(para.join('\n')) + '</p>')
      para = []
    }
    // 嵌套列表：子项 = 比首项更深的缩进。定义在 renderBlocks 内——嵌套路径递归
    // 回 renderBlocks，需要同一套 inline/unhold 闭包。返回消费到的行号。
    function renderList(lines, start, tag, marker, out) {
      var baseIndent = (lines[start].match(/^(\s*)/) || ['', ''])[1].length
      var items = [] // {parts:[]}，首元素=标记行文本，其余=续行/子列表行
      var i2 = start
      while (i2 < lines.length) {
        var m2 = lines[i2].match(marker)
        var indent = (lines[i2].match(/^(\s*)/) || ['', ''])[1].length
        if (m2 && indent <= baseIndent) {
          items.push([lines[i2].slice(m2[0].length)])
          i2++
        } else if (m2 && indent > baseIndent && items.length) {
          // 深一层缩进的标记行：原样（含缩进）挂到上一项，递归时才识别为子列表。
          items[items.length - 1].push(lines[i2])
          i2++
        } else if (!m2 && !/^\s*$/.test(lines[i2]) && items.length && indent > baseIndent) {
          items[items.length - 1].push(lines[i2].replace(/^\s+/, ''))
          i2++
        } else {
          break // 空行 / 缩进回退的非标记行 = 列表结束（保守：不跨空行续列表）
        }
      }
      var html = '<' + tag + '>'
      for (var k = 0; k < items.length; k++) {
        var first = items[k][0]
        var rest = items[k].slice(1)
        var inner = inlineHtml(first)
        if (rest.length) {
          // 余行若仍是列表标记形状，递归成嵌套列表；否则并入本项文本。
          var nested = renderBlocks(rest)
          if (/<[uo]l>/.test(nested)) inner += nested
          else inner += '\n' + inlineHtml(rest.join('\n'))
        }
        html += '<li>' + inner + '</li>'
      }
      html += '</' + tag + '>'
      out.push(html)
      return i2
    }
    while (i < lines.length) {
      var line = lines[i]
      if (/^\s*$/.test(line)) { flushPara(); i++; continue }
      // fenced code block：内容已转义，绝不做标记识别；未闭合围栏=吃到结尾。
      var fence = line.match(/^```/)
      if (fence) {
        flushPara()
        var body = []
        i++
        while (i < lines.length && !/^```/.test(lines[i])) { body.push(lines[i]); i++ }
        if (i < lines.length) i++ // skip closing fence
        out.push('<pre><code>' + body.join('\n') + '</code></pre>')
        continue
      }
      // t261021-13: pipe tables — a row is a line starting and ending with '|';
      // a separator second row (| --- | --- |) promotes row 1 to a header. Cell
      // content goes through the same inline pass; escaping already happened, so
      // a hostile cell stays literal text.
      if (/^\s*\|.*\|\s*$/.test(line)) {
        flushPara()
        var trows = []
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { trows.push(lines[i]); i++ }
        var tcells = function (r) { return r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|') }
        var tsep = function (r) { return /^\s*\|[\s:|-]+\|\s*$/.test(r) }
        var thead = trows.length >= 2 && tsep(trows[1])
        var tbody = thead ? trows.slice(2) : trows
        var thtml = '<table>'
        if (thead) {
          thtml += '<thead><tr>'
          for (var t1 = 0; t1 < tcells(trows[0]).length; t1++) thtml += '<th>' + inlineHtml(tcells(trows[0])[t1].trim()) + '</th>'
          thtml += '</tr></thead>'
        }
        thtml += '<tbody>'
        for (var t2 = 0; t2 < tbody.length; t2++) {
          thtml += '<tr>'
          var rowCells = tcells(tbody[t2])
          for (var t3 = 0; t3 < rowCells.length; t3++) thtml += '<td>' + inlineHtml(rowCells[t3].trim()) + '</td>'
          thtml += '</tr>'
        }
        thtml += '</tbody></table>'
        out.push(thtml)
        continue
      }
      var h = line.match(/^(#{1,4})\s+(.*)$/)
      if (h) { flushPara(); var lv = h[1].length; out.push('<h' + lv + '>' + inlineHtml(h[2]) + '</h' + lv + '>'); i++; continue }
      if (/^&gt;\s?/.test(line)) {
        flushPara()
        var q = []
        while (i < lines.length && /^&gt;\s?/.test(lines[i])) { q.push(lines[i].replace(/^&gt;\s?/, '')); i++ }
        out.push('<blockquote>' + renderBlocks(q) + '</blockquote>')
        continue
      }
      if (/^\s*([-*])\s+/.test(line)) {
        flushPara()
        i = renderList(lines, i, 'ul', /^\s*([-*])\s+/, out)
        continue
      }
      if (/^\s*\d+[.)]\s+/.test(line)) {
        flushPara()
        i = renderList(lines, i, 'ol', /^\s*\d+[.)]\s+/, out)
        continue
      }
      para.push(line)
      i++
    }
    flushPara()
    return out.join('')
  }

  var lines = text.split('\n')
  var html
  if (inlineOnly) {
    // 选项按钮等单行面：不做块结构，换行折为空格。
    html = unhold(inline(lines.join(' ')))
  } else {
    html = renderBlocks(lines)
  }
  if (clipped) html += '<p class="md-clipped">The text was longer than ' + MAX_IN + ' characters and was cut.</p>'
  return html
}
