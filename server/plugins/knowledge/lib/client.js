window.__ModuleLoader__.load({ id: "sandbar-knowledge", factory: (require) => { var module = { exports: {} }; var exports = module.exports;
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
let react = require("react");
let react_jsx_runtime = require("react/jsx-runtime");
//#region src/client/inject-contract.ts
/**
* sandbar-knowledge · client entry inject 契约（单一真源）。
*
* 【为什么收窄到 ['slots']（工单 t260916-26，dsh 升级 epic T6）】
* dsh 0.1.1（现生产）的浏览器半由 dsh-client-runtime 提供 `conversationViews`
* 服务（0.1.1 lib/client.js：super(ctx, 「conversationViews」)）；0.1.5 起
* dsh-client-runtime 整包移除，会话视图扩展面迁到 dsh-client-ui-conversation 的
* `uiConversation.views.register`，且 0.1.5 全包已无任何服务注册在
* 「conversationViews」键下。宿主（与浏览器 web boot）按 entry 的 `inject`
* 声明等待服务注入——声明了不存在的服务 = 永久 pending = UI 顶部
* 「Failed to load plugins / web boot: N entries did not activate」。
*
* 双版本容错口径：inject 只声明两版皆存在的服务，同一份 bundle 在 0.1.1 与
* 0.1.5 下都能激活（零运行时分支、零构建期二选一）。白名单取证：
*   - `slots`：0.1.1/0.1.5 皆在（0.1.5 实台活证=workbench 注入
*     ['slots','sessions','workspaces'] 正常激活）；
*   - `sessions`/`workspaces`：同上双版皆在，本插件当前不消费，不声明。
* 本插件 apply 为空操作（260823 起视图由 sandbar-workbench 侧栏承载），
* 对 `uiConversation`/`conversationViews` 均零消费——收窄不改变任何行为。
*
* 【白名单纪律】未来若要恢复插件自持页签：0.1.5 用
* `uiConversation.views.register`、0.1.1 用 `conversationViews.register`
* 双轨探测实现，且必须先核实目标服务在两版都真实存在（宿主 stage +
* 生产各一条活证）再进白名单；同步更新 index.tsx 与 smoke/client-contract.mjs
* 的产物断言。
*
* validateInject 仅供测试与未来装载前校验调用——严禁放进 entry 激活路径
* （浏览器半抛错 = 激活失败 = 恰好炸出本票要避免的整屏横幅）。
*/
/** 双版本（dsh 0.1.x 生产/stage）皆存在的客户端服务白名单——本 entry 消费的子集。 */
const CLIENT_INJECT = ["slots"];
//#endregion
//#region src/client/markdown.ts
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
function escapeHtml(s) {
	return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function safeUrl(url) {
	const u = url.trim();
	if (/^(javascript|data|vbscript):/i.test(u)) return "#";
	return u;
}
function inline(text) {
	return escapeHtml(text).split(/`([^`]*)`/g).map((p, idx) => {
		if (idx % 2 === 1) return `<code>${p}</code>`;
		return inlineFormat(p);
	}).join("");
}
function inlineFormat(s) {
	s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_m, alt, url) => `<img alt="${alt}" src="${safeUrl(url)}" />`);
	s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, txt, url) => `<a href="${safeUrl(url)}">${txt}</a>`);
	s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
	s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
	s = s.replace(/__([^_]+)__/g, "<strong>$1</strong>");
	s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
	s = s.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>");
	return s;
}
const KEYWORDS_JS = "const|let|var|function|return|if|else|for|while|import|export|from|class|interface|type|new|async|await|this|extends|implements|public|private|readonly|typeof|of|in|throw|try|catch|finally|switch|case|break|default";
const KEYWORDS_PY = "def|return|import|from|if|elif|else|for|while|class|try|except|finally|with|as|not|in|is|lambda|yield|raise|None|True|False|and|or|pass|global|nonlocal";
const KEYWORDS_BASH = "if|then|else|fi|for|while|do|done|case|esac|function|echo|export|local|return|source|cd|set|unset";
const KEYWORDS_JSON = "true|false|null";
function specOf(lang) {
	const l = lang.toLowerCase();
	if ([
		"js",
		"javascript",
		"ts",
		"tsx",
		"typescript",
		"jsx"
	].includes(l)) return { re: new RegExp(`(?<comment>\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)|(?<string>'[^'\\n]*'|"[^"\\n]*"|\`[^\`]*\`)|(?<kw>\\b(?:${KEYWORDS_JS})\\b)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) };
	if (["py", "python"].includes(l)) return { re: new RegExp(`(?<comment>#[^\\n]*)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<kw>\\b(?:${KEYWORDS_PY})\\b)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) };
	if ([
		"bash",
		"sh",
		"shell",
		"zsh"
	].includes(l)) return { re: new RegExp(`(?<comment>#[^\\n]*)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<var>\\$\\w+|\\$\\{[^}]+\\})|(?<kw>\\b(?:${KEYWORDS_BASH})\\b)|(?<num>\\b\\d+\\b)`) };
	if (["json"].includes(l)) return { re: new RegExp(`(?<string>"(?:\\\\.|[^"\\\\])*")|(?<kw>\\b(?:${KEYWORDS_JSON})\\b)|(?<num>-?\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)`) };
	if (["yaml", "yml"].includes(l)) return { re: new RegExp(`(?<comment>#[^\\n]*)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<kw>\\b(?:${KEYWORDS_JSON})\\b)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) };
	if ([
		"html",
		"xml",
		"css",
		"scss",
		"less"
	].includes(l)) return { re: new RegExp(`(?<comment>\\/\\*[\\s\\S]*?\\*\\/|<!--[\\s\\S]*?-->)|(?<string>'[^'\\n]*'|"[^"\\n]*")|(?<num>#?[0-9a-fA-F]{3,8}\\b|\\b\\d+(?:\\.\\d+)?(?:px|em|rem|%|vh|vw)?\\b)`) };
	return { re: new RegExp(`(?<comment>\\/\\/[^\\n]*|#[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)|(?<string>'[^'\\n]*'|"[^"\\n]*"|\`[^\`]*\`)|(?<num>\\b\\d+(?:\\.\\d+)?\\b)`) };
}
const TOKEN_CLASS = {
	comment: "tok-c",
	string: "tok-s",
	kw: "tok-k",
	num: "tok-n",
	var: "tok-v"
};
function highlight(code, lang) {
	const { re } = specOf(lang);
	let out = "";
	let i = 0;
	let guard = 0;
	while (i < code.length) {
		const sub = code.slice(i);
		const m = re.exec(sub);
		if (!m) {
			out += escapeHtml(sub);
			break;
		}
		if (m.index > 0) out += escapeHtml(sub.slice(0, m.index));
		const g = m.groups ?? {};
		const cls = Object.keys(g).find((k) => g[k] !== void 0) ?? "";
		const span = cls && TOKEN_CLASS[cls] ? `<span class="${TOKEN_CLASS[cls]}">${escapeHtml(m[0])}</span>` : escapeHtml(m[0]);
		out += span;
		i += m.index + m[0].length;
		if (++guard > 1e5) {
			out += escapeHtml(code.slice(i));
			break;
		}
	}
	return out;
}
function codeBlock(code, lang) {
	const body = lang ? highlight(code, lang) : escapeHtml(code);
	return `<div class="md-code">${lang ? `<span class="md-cl">${escapeHtml(lang)}</span>` : ""}<button class="md-copy" data-code="${encodeURIComponent(code)}">复制</button><pre><code>${body}\n</code></pre></div>`;
}
/** 把源码按行拆成 HTML。 */
function renderMarkdown(src) {
	const lines = src.replace(/\r\n?/g, "\n").split("\n");
	let html = "";
	let i = 0;
	const n = lines.length;
	const isBlank = (s) => s.trim() === "";
	while (i < n) {
		const line = lines[i];
		if (isBlank(line)) {
			i++;
			continue;
		}
		const fence = line.match(/^```\s*([\w+-]*)/);
		if (fence) {
			const lang = fence[1] ?? "";
			const buf = [];
			i++;
			while (i < n && !/^```\s*$/.test(lines[i])) {
				buf.push(lines[i]);
				i++;
			}
			if (i < n) i++;
			html += codeBlock(buf.join("\n"), lang);
			continue;
		}
		if (/^ {4}/.test(line)) {
			const buf = [];
			while (i < n && (/^ {4}/.test(lines[i]) || isBlank(lines[i]))) {
				buf.push(lines[i].replace(/^ {4}/, ""));
				i++;
			}
			html += codeBlock(buf.join("\n"), "");
			continue;
		}
		const h = line.match(/^(#{1,6})\s+(.*)$/);
		if (h) {
			html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`;
			i++;
			continue;
		}
		if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
			html += "<hr/>";
			i++;
			continue;
		}
		if (/^>\s?/.test(line)) {
			const buf = [];
			while (i < n && /^>\s?/.test(lines[i])) {
				buf.push(lines[i].replace(/^>\s?/, ""));
				i++;
			}
			html += `<blockquote>${buf.map(inline).join("<br/>")}</blockquote>`;
			continue;
		}
		if (line.includes("|") && i + 1 < n && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
			const headerCells = splitRow(line);
			i += 2;
			const rows = [];
			while (i < n && lines[i].includes("|") && !isBlank(lines[i])) {
				rows.push(splitRow(lines[i]));
				i++;
			}
			let t = "<table><thead><tr>" + headerCells.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>";
			for (const r of rows) t += "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
			t += "</tbody></table>";
			html += t;
			continue;
		}
		const ul = line.match(/^\s*([-*+])\s+(.*)$/);
		const ol = line.match(/^\s*(\d+)\.\s+(.*)$/);
		if (ul || ol) {
			const isOl = !!ol;
			const items = [];
			while (i < n) {
				const m = isOl ? lines[i].match(/^\s*\d+\.\s+(.*)$/) : lines[i].match(/^\s*[-*+]\s+(.*)$/);
				if (!m) break;
				items.push(inline(m[1]));
				i++;
			}
			const tag = isOl ? "ol" : "ul";
			html += `<${tag}>` + items.map((it) => `<li>${it}</li>`).join("") + `</${tag}>`;
			continue;
		}
		const buf = [line];
		i++;
		while (i < n && !isBlank(lines[i]) && !/^(#{1,6}\s|```|>\s?|\s*[-*+]\s|\s*\d+\.\s)/.test(lines[i])) {
			buf.push(lines[i]);
			i++;
		}
		html += `<p>${buf.map(inline).join("<br/>")}</p>`;
	}
	return html;
}
function splitRow(line) {
	let s = line.trim();
	if (s.startsWith("|")) s = s.slice(1);
	if (s.endsWith("|")) s = s.slice(0, -1);
	return s.split("|").map((c) => c.trim());
}
//#endregion
//#region src/shared/blocks.ts
/** 表格行 → 单元格数组（client 做单元格级对齐也用）。 */
function splitCells(line) {
	let s = line.trim();
	if (s.startsWith("|")) s = s.slice(1);
	if (s.endsWith("|")) s = s.slice(0, -1);
	return s.split("|").map((c) => c.trim());
}
//#endregion
//#region src/client/index.tsx
/**
* sandbar-knowledge —— docs 知识库 · 浏览器半。
*
* 槽位契约沿革：本插件曾向会话视图环注册页签 + `conversationViews.register`
* （260823 前）；260823 起知识库 UI 移到工单台侧栏中栏、由 sandbar-workbench
* 直接 import 本插件的 KnowledgeSection 渲染，apply 改为空操作——插件对
* conversationViews/uiConversation 零消费、零注册。
*
* 功能（工单 t260821-09 → t260821-10 M2/M3）：
*   ① 列表按分类（design/content/ops/reference）/标签/状态过滤；
*   ② 关键词检索（标题 + frontmatter tags）；
*   ③ 读全文（点条目中栏内嵌 list→doc 两态切换）：markdown render（HTML，非 raw；表格/代码块
*      高亮+复制/链接/列表），可切 raw 查看原文；头部「← 返回」按钮回到列表，筛选条件不丢；
*   ④ review（提示缺 frontmatter / status=deprecated / updated 过旧，三组清单）；
*   ⑤ block 级 diff 审阅（t260821-14）：细粒度 block（标题/段落/列表项/表格行/
*      代码块…），主视图=渲染后 markdown（未变渲染新文本/新增绿底/删除红底/
*      修改上下红绿，表格行单元格级对齐），raw 行级 ops 为可切换次要视图（只留
*      变更行）；逐块 approve/reject/注释按稳定 block_key 持久化——进入 diff
*      自动回填最近一轮，「保存 review」显式落盘（含整篇结论），保存后生成
*      可贴工单的 rework 指令；内容变了 key 失效的旧意见标「已过期」不回填。
*
* 数据通道：同源 fetch 打宿主半（../node.ts）挂在 dsh webServer 上的
* /sandbar-knowledge/api/*；写操作只有 review/save（宿主半落 docs/reviews/ +
* server/admin.log 审计）。
*
* 【inject 收窄史（t260916-26）】曾声明 `inject = ['slots','conversationViews']`；
* dsh 0.1.5 起 conversationViews 服务随 dsh-client-runtime 整包移除，声明即
* 永久 pending（UI 报 Failed to load plugins）。现改从 ./inject-contract 导入
* CLIENT_INJECT（=['slots']，双版本稳定白名单），同一 bundle 在 0.1.1/0.1.5
* 都能激活；本插件无页签注册行为（apply 空操作），收窄零行为差异。
*/
const name = "sandbar-knowledge/client";
const inject = CLIENT_INJECT;
const CSS = `
.kb-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:#f6f8fa;color:#1f2328;min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:14px;height:100%;overflow-y:auto;font-size:13px;line-height:1.55}
.kb-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid #d0d7de;padding-bottom:12px;flex-wrap:wrap}
.kb-title{font-size:20px;font-weight:600;color:#1f2328}
.kb-sub{font-size:12px;color:#57606a}
.kb-spacer{flex:1}
.kb-err{background:#ffebe9;border:1px solid #ff9b9b;color:#cf222e;border-radius:6px;
  padding:8px 12px;font-size:12px;white-space:pre-wrap}
.kb-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.kb-select{font:inherit;font-size:13px;background:#ffffff;color:#1f2328;border:1px solid #d0d7de;
  border-radius:6px;padding:5px 10px}
.kb-select:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.kb-input{font:inherit;font-size:13px;background:#ffffff;color:#1f2328;border:1px solid #d0d7de;
  border-radius:6px;padding:5px 10px;min-width:220px}
.kb-input:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.kb-btn{font:inherit;font-size:13px;padding:5px 16px;border-radius:6px;cursor:pointer;
  border:1px solid #d0d7de;background:#ffffff;color:#1f2328;transition:background .12s}
.kb-btn:hover{background:#f6f8fa}
.kb-btn:disabled{opacity:.5;cursor:default}
.kb-btn-blue{border-color:#96c8f2;color:#0969da;background:#ddf4ff}
.kb-btn-active{border-color:#0969da;color:#ffffff;background:#0969da}
.kb-table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;border:1px solid #d0d7de;
  border-radius:8px;background:#ffffff;box-shadow:0 1px 3px rgba(31,35,40,.06);font-size:13px;overflow:hidden}
.kb-table thead th{position:sticky;top:0;z-index:1;background:#f6f8fa;color:#57606a;font-weight:600;
  text-align:left;padding:9px 12px;border-bottom:1px solid #d0d7de;font-size:12px;white-space:nowrap}
.kb-table tbody td{padding:9px 12px;border-bottom:1px solid #e8ebef;vertical-align:middle}
.kb-table tbody tr{cursor:pointer}
.kb-table tbody tr:hover{background:#f6f8fa}
.kb-table tbody tr:last-child td{border-bottom:none}
.kb-cat{font-size:12px;color:#57606a;background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;
  padding:1px 8px;white-space:nowrap}
.kb-cat[data-cat=design]{background:#ddf4ff;color:#0550ae;border-color:#96c8f2}
.kb-cat[data-cat=content]{background:#dafbe1;color:#116329;border-color:#7dd9a0}
.kb-cat[data-cat=ops]{background:#fff8c5;color:#7d4e00;border-color:#eac54f}
.kb-cat[data-cat=reference]{background:#fbefff;color:#6f42c1;border-color:#d3b9f0}
.kb-tag{font-size:11px;color:#57606a;background:#f6f8fa;border:1px solid #e8ebef;border-radius:6px;
  padding:1px 6px;margin-right:4px}
.kb-title-cell{font-weight:600;color:#0969da}
.kb-path{color:#8c959f;font-size:11px}
.kb-status{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:500}
.kb-status[data-status=active]{background:#dafbe1;color:#116329}
.kb-status[data-status=draft]{background:#fff8c5;color:#7d4e00}
.kb-status[data-status=deprecated]{background:#ffebe9;color:#cf222e}
.kb-empty{font-size:12px;color:#57606a;padding:12px 0}
.kb-back-btn{font:inherit;font-size:13px;padding:3px 12px;border-radius:6px;cursor:pointer;
  border:1px solid #d0d7de;background:#ffffff;color:#1f2328;transition:background .12s}
.kb-back-btn:hover{background:#f6f8fa}
.kb-body{font-size:13px;line-height:1.9;color:#1f2328;white-space:pre-wrap;word-break:break-word;
  border:1px solid #e8ebef;border-radius:8px;padding:14px 16px;background:#fbfcfd;margin:0;overflow:auto}
.kb-review-box{border:1px solid #d0d7de;border-radius:8px;background:#ffffff;padding:12px 14px;display:flex;
  flex-direction:column;gap:8px}
.kb-review-title{font-size:14px;font-weight:600;color:#1f2328;border-bottom:1px solid #e8ebef;padding-bottom:6px}
.kb-review-item{color:#0969da;cursor:pointer}
.kb-review-item:hover{text-decoration:underline}
.kb-review-empty{color:#57606a;font-size:12px}
.kb-warn{font-size:12px;color:#bf8700;background:#fff8c5;border:1px solid #eac54f;border-radius:6px;padding:5px 10px}
/* markdown render */
.kb-md{font-size:13.5px;line-height:1.7;color:#1f2328;word-break:break-word}
.kb-md h1,.kb-md h2,.kb-md h3,.kb-md h4,.kb-md h5,.kb-md h6{margin:18px 0 8px;font-weight:600;line-height:1.3}
.kb-md h1{font-size:22px;border-bottom:1px solid #d8dee4;padding-bottom:6px}
.kb-md h2{font-size:18px;border-bottom:1px solid #d8dee4;padding-bottom:4px}
.kb-md h3{font-size:15px}
.kb-md h4,.kb-md h5,.kb-md h6{font-size:14px}
.kb-md p{margin:6px 0}
.kb-md a{color:#0969da;text-decoration:none}
.kb-md a:hover{text-decoration:underline}
.kb-md ul,.kb-md ol{margin:6px 0;padding-left:22px}
.kb-md li{margin:2px 0}
.kb-md blockquote{margin:8px 0;padding:2px 12px;border-left:4px solid #d0d7de;color:#57606a;background:#f6f8fa}
.kb-md code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  background:#eff1f3;border-radius:4px;padding:1px 5px}
.kb-md table{border-collapse:collapse;margin:10px 0;max-width:100%;display:block;overflow-x:auto}
.kb-md table th,.kb-md table td{border:1px solid #d0d7de;padding:6px 12px;text-align:left}
.kb-md table th{background:#f6f8fa;font-weight:600}
.kb-md hr{border:none;border-top:1px solid #d8dee4;margin:14px 0}
.kb-md img{max-width:100%}
.md-code{position:relative;margin:10px 0;border:1px solid #d0d7de;border-radius:8px;background:#f6f8fa;overflow:hidden}
.md-code pre{margin:0;padding:12px 14px;overflow-x:auto}
.md-code pre code{background:none;padding:0;font-size:12px;line-height:1.6;color:#1f2328}
.md-cl{position:absolute;top:6px;right:60px;font-size:11px;color:#57606a;background:#eaeef2;
  border-radius:4px;padding:0 8px;line-height:18px}
.md-copy{position:absolute;top:6px;right:8px;font-size:11px;padding:1px 10px;line-height:18px;cursor:pointer;
  border:1px solid #d0d7de;background:#ffffff;color:#57606a;border-radius:4px}
.md-copy:hover{background:#eaeef2;color:#1f2328}
.tok-c{color:#6e7781;font-style:italic}
.tok-s{color:#0a3069}
.tok-k{color:#cf222e;font-weight:600}
.tok-n{color:#0550ae}
.tok-v{color:#953800}
/* block diff review */
.kb-diff-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kb-diff-sum{font-size:12px;color:#57606a;display:flex;gap:14px;flex-wrap:wrap}
.d-block{border:1px solid #d0d7de;border-radius:8px;background:#ffffff;overflow:hidden}
.d-head{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#f6f8fa;border-bottom:1px solid #e8ebef;flex-wrap:wrap}
.d-head-t{font-weight:600;font-size:13px;color:#1f2328}
.d-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap}
.d-badge[data-s=added]{background:#dafbe1;color:#116329}
.d-badge[data-s=removed]{background:#ffebe9;color:#cf222e}
.d-badge[data-s=modified]{background:#fff8c5;color:#7d4e00}
.d-badge[data-s=unchanged]{background:#f6f8fa;color:#57606a}
.d-ops{padding:6px 0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.6}
.d-line{padding:1px 12px;white-space:pre-wrap;word-break:break-all}
.d-ctx{color:#1f2328}
.d-add{background:#dafbe1;color:#116329}
.d-del{background:#ffebe9;color:#cf222e}
.d-mod{background:#fff8c5}
.d-mod .d-del{background:none;text-decoration:line-through;color:#7d4e00}
.d-mod .d-add{background:none;color:#116329;font-weight:600}
.d-actions{display:flex;gap:8px;align-items:center;padding:8px 12px;border-top:1px solid #e8ebef;flex-wrap:wrap}
.d-btn{font-size:12px;padding:2px 12px;border-radius:6px;cursor:pointer;border:1px solid #d0d7de;background:#fff;color:#1f2328}
.d-btn:hover{background:#f6f8fa}
.d-btn-ap{border-color:#7dd9a0;color:#116329}
.d-btn-ap.on{background:#116329;color:#fff}
.d-btn-rj{border-color:#ff9b9b;color:#cf222e}
.d-btn-rj.on{background:#cf222e;color:#fff}
.d-cmt{width:100%;min-height:52px;font:inherit;font-size:12px;border:1px solid #d0d7de;border-radius:6px;padding:6px 10px}
.d-expand{font-size:11px;color:#0969da;cursor:pointer;background:none;border:none}
/* 渲染态 diff 主视图 */
.d-md{padding:8px 14px;font-size:13px}
.d-md-add{background:#f0fff4;border-left:4px solid #2da44e}
.d-md-del{background:#fff5f5;border-left:4px solid #cf222e}
.d-md-old{background:#fff5f5;border-left:4px solid #ff9b9b}
.d-md-new{background:#f0fff4;border-left:4px solid #7dd9a0}
.d-md-tag{font-size:11px;font-weight:600;color:#57606a;letter-spacing:1px}
.d-md-old .d-md-tag{color:#cf222e}
.d-md-new .d-md-tag{color:#116329}
.d-md-half{border-bottom:1px dashed #e8ebef}
.d-type{font-size:11px;color:#8c959f;border:1px solid #e8ebef;border-radius:6px;padding:0 6px;white-space:nowrap}
/* 表格行单元格级对齐 */
.d-cells{border-collapse:collapse;margin:8px 12px;font-size:12px;max-width:calc(100% - 24px);display:block;overflow-x:auto}
.d-cells th,.d-cells td{border:1px solid #d0d7de;padding:4px 10px;text-align:left;white-space:pre-wrap;word-break:break-word}
.d-cells th{background:#f6f8fa;color:#57606a;font-weight:600}
.cell-old-chg{background:#ffebe9;color:#cf222e;text-decoration:line-through}
.cell-new-chg{background:#dafbe1;color:#116329;font-weight:600}
/* review 持久化 */
.d-conclude{font:inherit;font-size:12px;border:1px solid #d0d7de;border-radius:6px;padding:3px 8px;background:#fff}
.kb-rework{border:1px solid #d0d7de;border-radius:8px;background:#fbfcfd;padding:10px 14px;display:flex;flex-direction:column;gap:8px}
.kb-rework pre{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  line-height:1.6;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto}
.kb-expired{border:1px dashed #d0d7de;border-radius:8px;padding:8px 12px;color:#57606a;font-size:12px}
.kb-expired-item{padding:4px 0;border-bottom:1px solid #f0f2f5}
.kb-expired-item:last-child{border-bottom:none}
.d-badge[data-s=expired]{background:#f6f8fa;color:#8c959f;border:1px dashed #d0d7de}
`;
const CSS_TAG_ID = "sandbar-knowledge/KnowledgeSection.css";
if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(CSS_TAG_ID) + "]") === null) {
	const tag = document.createElement("style");
	tag.dataset.plugin = "sandbar-knowledge";
	tag.dataset.pluginCss = CSS_TAG_ID;
	tag.textContent = CSS;
	document.head.appendChild(tag);
}
const API = "/sandbar-knowledge/api";
/** 多项目化（260823）：当前视图的项目 key，KnowledgeSection 挂载/切换时从 prop 设置。
*  中列同一时刻只挂一个视图，模块单态安全。空串=不拼参（host 会 400，UI 先显占位）。 */
let viewProject = "";
/** 统一拼 ?project=（host 六条路由全部必传）。 */
function withProject(path) {
	if (!viewProject) return path;
	return path + (path.includes("?") ? "&" : "?") + "project=" + encodeURIComponent(viewProject);
}
async function apiGet(path) {
	return (await fetch(withProject(path))).json();
}
async function apiPost(path, body) {
	return (await fetch(withProject(path), {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(body)
	})).json();
}
/** 去掉正文前 YAML frontmatter 块（读全文展示用，正文保持原样）。 */
function stripFrontmatter(md) {
	if (!md.startsWith("---\n")) return md;
	const lines = md.split("\n");
	for (let i = 1; i < lines.length; i++) if (lines[i].trim() === "---") return lines.slice(i + 1).join("\n").replace(/^\n+/, "");
	return md;
}
const TYPE_LABEL = {
	frontmatter: "frontmatter",
	heading: "标题",
	paragraph: "段落",
	"list-item": "列表项",
	"table-head": "表头",
	"table-row": "表格行",
	code: "代码块",
	quote: "引用",
	image: "图片",
	hr: "分隔线"
};
const STATUS_LABEL = {
	added: "新增",
	removed: "删除",
	modified: "修改",
	unchanged: "未变"
};
const CONCLUDE_LABEL = {
	approved: "approved（通过）",
	"changes-requested": "changes-requested（要求修改）",
	"in-progress": "in-progress（审阅中）"
};
/** 生成可贴进工单的 rework 指令（驳回块清单+注释+文档路径+base）。 */
function buildReworkMd(path, diff, conclude, blocks, runId) {
	const rejected = blocks.filter((b) => b.decision === "reject");
	const lines = [
		"## rework 指令（知识库 review）",
		"",
		`- 文档：docs/${path}`,
		`- base：${diff.base}`,
		`- 整篇结论：${conclude}`,
		`- review run-id：${runId}`,
		""
	];
	if (rejected.length === 0) lines.push("无驳回块。");
	else {
		lines.push(`### 驳回块清单（${rejected.length}）`, "");
		rejected.forEach((b, i) => {
			lines.push(`${i + 1}. [${TYPE_LABEL[b.type] ?? b.type} / ${STATUS_LABEL[b.status] ?? b.status}] ${b.summary}`);
			if (b.comment !== void 0 && b.comment !== "") lines.push(`   - 注释：${b.comment}`);
			lines.push(`   - block_key：\`${b.block_key}\``);
		});
	}
	return lines.join("\n");
}
function KnowledgeSection({ projectKey }) {
	const [data, setData] = (0, react.useState)(void 0);
	const [error, setError] = (0, react.useState)("");
	const [filterCat, setFilterCat] = (0, react.useState)("");
	const [filterTag, setFilterTag] = (0, react.useState)("");
	const [filterStatus, setFilterStatus] = (0, react.useState)("");
	const [kw, setKw] = (0, react.useState)("");
	const [showReview, setShowReview] = (0, react.useState)(false);
	const [doc, setDoc] = (0, react.useState)(void 0);
	const [docLoading, setDocLoading] = (0, react.useState)(false);
	const [view, setView] = (0, react.useState)("render");
	const [diff, setDiff] = (0, react.useState)(void 0);
	const [diffLoading, setDiffLoading] = (0, react.useState)(false);
	const [diffBase, setDiffBase] = (0, react.useState)("HEAD");
	const [reviews, setReviews] = (0, react.useState)({});
	const [expanded, setExpanded] = (0, react.useState)({});
	const [rawOps, setRawOps] = (0, react.useState)({});
	const [reviewInfo, setReviewInfo] = (0, react.useState)(void 0);
	const [expired, setExpired] = (0, react.useState)([]);
	const [conclude, setConclude] = (0, react.useState)("in-progress");
	const [saveState, setSaveState] = (0, react.useState)({});
	const [reworkMd, setReworkMd] = (0, react.useState)(void 0);
	async function reload() {
		try {
			const r = await apiGet(`${API}/index`);
			if (r?.ok !== true) throw new Error(r?.error ?? "知识库索引加载失败");
			setData(r.result);
			setError("");
		} catch (err) {
			setError(String(err instanceof Error ? err.message : err));
		}
	}
	async function openDoc(path, title) {
		setDocLoading(true);
		setDoc({
			path,
			title,
			content: ""
		});
		setView("render");
		setDiff(void 0);
		setReviews({});
		try {
			const r = await apiGet(`${API}/doc?path=${encodeURIComponent(path)}`);
			if (r?.ok !== true) throw new Error(r?.error ?? "文档读取失败");
			setDoc({
				path,
				title,
				content: stripFrontmatter(String(r.result?.content ?? ""))
			});
		} catch (err) {
			setDoc({
				path,
				title,
				content: `（读取失败：${String(err instanceof Error ? err.message : err)}）`
			});
		} finally {
			setDocLoading(false);
		}
	}
	async function refresh() {
		setError("");
		try {
			const r = await apiGet(`${API}/refresh`);
			if (r?.ok !== true) throw new Error(r?.error ?? "索引重建失败");
			setData(r.result);
		} catch (err) {
			setError(String(err instanceof Error ? err.message : err));
		}
	}
	async function loadDiff() {
		if (!doc) return;
		setDiffLoading(true);
		setReviews({});
		setExpired([]);
		setReworkMd(void 0);
		setSaveState({});
		try {
			const r = await apiGet(`${API}/diff?path=${encodeURIComponent(doc.path)}&base=${encodeURIComponent(diffBase)}`);
			if (r?.ok !== true) throw new Error(r?.error ?? "diff 读取失败");
			const d = r.result;
			setDiff(d);
			try {
				const rv = await apiGet(`${API}/review?path=${encodeURIComponent(doc.path)}`);
				if (rv?.ok === true) {
					const file = rv.result;
					const latest = file.rounds.length > 0 ? file.rounds[file.rounds.length - 1] : void 0;
					setReviewInfo({
						rounds: file.rounds.length,
						latest
					});
					if (latest !== void 0) {
						setConclude(latest.conclude);
						const currentKeys = new Set(d.blocks.map((b) => b.key));
						const backfill = {};
						const stale = [];
						for (const eb of latest.blocks) if (currentKeys.has(eb.block_key)) backfill[eb.block_key] = {
							decision: eb.decision,
							comment: eb.comment
						};
						else stale.push(eb);
						setReviews(backfill);
						setExpired(stale);
					}
				}
			} catch {}
		} catch (err) {
			setDiff(void 0);
			setError(`block diff 失败：${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setDiffLoading(false);
		}
	}
	/** 保存 review（显式落盘一轮），成功后生成 rework 指令。 */
	async function saveReview() {
		if (!doc || !diff) return;
		setSaveState({ saving: true });
		setReworkMd(void 0);
		try {
			const blocks = diff.blocks.filter((b) => b.status !== "unchanged").map((b) => ({
				block_key: b.key,
				summary: b.summary,
				type: b.type,
				status: b.status,
				decision: reviews[b.key]?.decision,
				comment: reviews[b.key]?.comment
			}));
			const r = await apiPost(`${API}/review/save`, {
				path: doc.path,
				base: diff.base,
				conclude,
				reviewer: "user",
				blocks
			});
			if (r?.ok !== true) throw new Error(r?.error ?? "保存失败");
			setSaveState({ runId: String(r.run_id ?? "") });
			setReviewInfo((prev) => ({
				rounds: (prev?.rounds ?? 0) + 1,
				latest: r.result?.round
			}));
			setReworkMd(buildReworkMd(doc.path, diff, conclude, blocks, String(r.run_id ?? "")));
		} catch (err) {
			setSaveState({ error: String(err instanceof Error ? err.message : err) });
		}
	}
	(0, react.useEffect)(() => {
		viewProject = projectKey ?? "";
		setData(void 0);
		setDoc(void 0);
		setDiff(void 0);
		setReviewInfo(void 0);
		if (viewProject) reload();
	}, [projectKey]);
	(0, react.useEffect)(() => {
		reload();
	}, []);
	function onDocClick(e) {
		const btn = e.target.closest(".md-copy");
		if (!btn) return;
		const code = btn.getAttribute("data-code") ?? "";
		try {
			navigator.clipboard?.writeText(decodeURIComponent(code));
		} catch {}
	}
	const allTags = (0, react.useMemo)(() => {
		const s = /* @__PURE__ */ new Set();
		for (const d of data?.docs ?? []) for (const t of d.tags) s.add(t);
		return [...s].sort();
	}, [data]);
	const filtered = (0, react.useMemo)(() => {
		const q = kw.trim().toLowerCase();
		return (data?.docs ?? []).filter((d) => {
			if (filterCat !== "" && d.category !== filterCat) return false;
			if (filterTag !== "" && !d.tags.includes(filterTag)) return false;
			if (filterStatus !== "" && d.status !== filterStatus) return false;
			if (q !== "") {
				if (!(d.title + " " + d.tags.join(" ")).toLowerCase().includes(q)) return false;
			}
			return true;
		}).sort((a, b) => a.category.localeCompare(b.category) || a.path.localeCompare(b.path));
	}, [
		data,
		filterCat,
		filterTag,
		filterStatus,
		kw
	]);
	const review = data?.review;
	function setReview(key, patch) {
		setReviews((prev) => ({
			...prev,
			[key]: {
				...prev[key],
				...patch
			}
		}));
	}
	/** raw 行级次要视图：只留变更行（ctx 噪音去掉）。 */
	function renderOps(ops) {
		const changed = ops.filter((op) => op.k !== "ctx");
		if (changed.length === 0) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "d-line d-ctx",
			children: "（行级无差异：仅块级别/格式变化）"
		});
		return changed.map((op, i) => {
			if (op.k === "add") return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "d-line d-add",
				children: ["+ ", op.b ?? ""]
			}, i);
			if (op.k === "del") return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "d-line d-del",
				children: ["- ", op.a ?? ""]
			}, i);
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "d-line d-mod",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "d-del",
					children: ["- ", op.a ?? ""]
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "d-add",
					children: ["+ ", op.b ?? ""]
				})]
			}, i);
		});
	}
	/** 表格行修改：单元格级对齐（同列对比，变格高亮）。 */
	function renderCellDiff(oldLine, newLine) {
		const oc = splitCells(oldLine);
		const nc = splitCells(newLine);
		const cols = Math.max(oc.length, nc.length);
		return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("table", {
			className: "d-cells",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("thead", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { style: { width: 40 } }), Array.from({ length: cols }, (_, c) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("th", { children: ["列 ", c + 1] }, c))] }) }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tbody", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "旧" }), Array.from({ length: cols }, (_, c) => {
				return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
					className: (oc[c] ?? "") !== (nc[c] ?? "") ? "cell-old-chg" : "",
					children: oc[c] ?? "—"
				}, c);
			})] }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "新" }), Array.from({ length: cols }, (_, c) => {
				return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
					className: (oc[c] ?? "") !== (nc[c] ?? "") ? "cell-new-chg" : "",
					children: nc[c] ?? "—"
				}, c);
			})] })] })]
		});
	}
	/** 渲染态 diff 主视图：未变渲染新文本；新增绿底；删除红底；修改上下红/绿。 */
	function renderBlockBody(b) {
		if (b.status === "unchanged") return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "d-md kb-md",
			dangerouslySetInnerHTML: { __html: renderMarkdown(b.newText ?? "") }
		});
		if (b.status === "added") return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "d-md d-md-add kb-md",
			dangerouslySetInnerHTML: { __html: renderMarkdown(b.newText ?? "") }
		});
		if (b.status === "removed") return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "d-md d-md-del kb-md",
			dangerouslySetInnerHTML: { __html: renderMarkdown(b.oldText ?? "") }
		});
		if (b.type === "table-row") return renderCellDiff(b.oldText ?? "", b.newText ?? "");
		return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "d-md d-md-old d-md-half kb-md",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "d-md-tag",
				children: "旧"
			}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", { dangerouslySetInnerHTML: { __html: renderMarkdown(b.oldText ?? "") } })]
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "d-md d-md-new kb-md",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "d-md-tag",
				children: "新"
			}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", { dangerouslySetInnerHTML: { __html: renderMarkdown(b.newText ?? "") } })]
		})] });
	}
	const diffSummary = diff !== void 0 ? {
		added: diff.blocks.filter((b) => b.status === "added").length,
		removed: diff.blocks.filter((b) => b.status === "removed").length,
		modified: diff.blocks.filter((b) => b.status === "modified").length,
		unchanged: diff.blocks.filter((b) => b.status === "unchanged").length,
		approved: Object.values(reviews).filter((r) => r.decision === "approve").length,
		rejected: Object.values(reviews).filter((r) => r.decision === "reject").length
	} : void 0;
	if (!projectKey) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "kb-root",
		children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			style: {
				padding: 32,
				color: "var(--dsw-alias-label-secondary, #888)",
				fontSize: 13
			},
			children: "从左侧项目行点 📖 图标打开该项目的知识库。"
		})
	});
	if (data?.empty) return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "kb-root",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "kb-head",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: "kb-title",
				children: "知 识 库"
			}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
				className: "kb-sub",
				children: ["项目 ", projectKey]
			})]
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			style: {
				padding: 32,
				color: "var(--dsw-alias-label-secondary, #888)",
				fontSize: 13
			},
			children: data.reason ?? "该项目还没有 docs 知识库。"
		})]
	});
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "kb-root",
		children: doc === void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "kb-head",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "kb-title",
						children: "知 识 库"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "kb-sub",
						children: [
							"docs 四分类 · 共 ",
							data?.total ?? "…",
							" 篇 · 索引 ",
							data?.generated_at ?? "…"
						]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { className: "kb-spacer" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("button", {
						className: "kb-btn",
						onClick: () => {
							setShowReview((v) => !v);
						},
						children: [showReview ? "收起 review" : "review", review && review.missing_frontmatter.length + review.deprecated.length + review.stale.length > 0 ? `（${review.missing_frontmatter.length + review.deprecated.length + review.stale.length}）` : ""]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "kb-btn kb-btn-blue",
						onClick: () => {
							refresh();
						},
						children: "重建索引"
					})
				]
			}),
			error !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "kb-err",
				children: [
					error,
					"\n",
					"（知识库 API 未挂载？headless profile 无 webServer。）"
				]
			}),
			showReview && review !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "kb-review-box",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "kb-review-title",
						children: "review（frontmatter 完整性 / 时效性）"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "kb-sub",
						children: [
							"缺 frontmatter（",
							review.missing_frontmatter.length,
							"）："
						]
					}), review.missing_frontmatter.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "kb-review-empty",
						children: "无"
					}) : review.missing_frontmatter.map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "kb-review-item",
						onClick: () => {
							openDoc(p, p);
						},
						children: p
					}, p))] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "kb-sub",
						children: [
							"status=deprecated（",
							review.deprecated.length,
							"）："
						]
					}), review.deprecated.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "kb-review-empty",
						children: "无"
					}) : review.deprecated.map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "kb-review-item",
						onClick: () => {
							openDoc(p, p);
						},
						children: p
					}, p))] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "kb-sub",
						children: [
							"updated 过旧（",
							">",
							"180 天，",
							review.stale.length,
							"）："
						]
					}), review.stale.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "kb-review-empty",
						children: "无"
					}) : review.stale.map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "kb-review-item",
						onClick: () => {
							openDoc(p, p);
						},
						children: p
					}, p))] })
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "kb-filters",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
						className: "kb-select",
						value: filterCat,
						onChange: (e) => setFilterCat(e.target.value),
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: "",
							children: "分类：全部"
						}), (data?.categories ?? []).map((c) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: c,
							children: c
						}, c))]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
						className: "kb-select",
						value: filterTag,
						onChange: (e) => setFilterTag(e.target.value),
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: "",
							children: "标签：全部"
						}), allTags.map((t) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: t,
							children: t
						}, t))]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
						className: "kb-select",
						value: filterStatus,
						onChange: (e) => setFilterStatus(e.target.value),
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: "",
							children: "状态：全部"
						}), [
							"active",
							"draft",
							"deprecated"
						].map((s) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: s,
							children: s
						}, s))]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
						className: "kb-input",
						placeholder: "检索标题 / 标签…",
						value: kw,
						onChange: (e) => setKw(e.target.value)
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "kb-sub",
						children: [
							filtered.length,
							"/",
							data?.total ?? 0,
							" 篇"
						]
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("table", {
				className: "kb-table",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("colgroup", { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("col", { style: { width: 240 } }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("col", { style: { width: 84 } }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("col", {}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("col", { style: { width: 96 } }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("col", { style: { width: 104 } })
					] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("thead", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "标题" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "分类" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "标签" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "状态" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "更新时间" })
					] }) }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tbody", { children: [filtered.map((d) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", {
						onClick: () => {
							openDoc(d.path, d.title);
						},
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("td", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "kb-title-cell",
								children: d.title
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "kb-path",
								children: ["　", d.path]
							})] }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "kb-cat",
								"data-cat": d.category,
								children: d.category
							}) }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: d.tags.map((t) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "kb-tag",
								children: t
							}, t)) }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "kb-status",
								"data-status": d.status,
								children: d.status
							}) }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: d.updated })
						]
					}, d.path)), filtered.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("tr", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
						colSpan: 5,
						className: "kb-empty",
						children: "没有符合筛选的文档。"
					}) })] })
				]
			})
		] }) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "kb-head",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "kb-back-btn",
						onClick: () => setDoc(void 0),
						children: "← 返回"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "kb-title",
						children: doc.title
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "kb-path",
						children: doc.path
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "kb-filters",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: view === "render" ? "kb-btn kb-btn-active" : "kb-btn",
						onClick: () => setView("render"),
						children: "渲染"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: view === "raw" ? "kb-btn kb-btn-active" : "kb-btn",
						onClick: () => setView("raw"),
						children: "raw"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: view === "diff" ? "kb-btn kb-btn-active" : "kb-btn",
						onClick: () => {
							setView("diff");
							loadDiff();
						},
						children: "diff 审阅"
					}),
					view === "diff" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "kb-sub",
							children: "base"
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							className: "kb-input",
							style: { minWidth: 120 },
							value: diffBase,
							onChange: (e) => setDiffBase(e.target.value)
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "kb-btn",
							onClick: () => {
								loadDiff();
							},
							children: "拉取 diff"
						})
					] })
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				onClick: onDocClick,
				children: [
					docLoading && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "kb-empty",
						children: "读取全文…"
					}),
					!docLoading && view === "render" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "kb-md",
						dangerouslySetInnerHTML: { __html: renderMarkdown(doc.content) }
					}),
					!docLoading && view === "raw" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
						className: "kb-body",
						children: doc.content
					}),
					!docLoading && view === "diff" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						style: {
							display: "flex",
							flexDirection: "column",
							gap: 10
						},
						children: [
							diffLoading && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "kb-empty",
								children: "计算 block diff…"
							}),
							!diffLoading && diff === void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "kb-empty",
								children: "diff 不可用（文档尚未进入 git，或 base 无此文件）。"
							}),
							!diffLoading && diff !== void 0 && diffSummary !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "kb-diff-sum",
									children: [
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["base：", diff.base] }),
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											style: { color: diff.changed ? "#bf8700" : "#57606a" },
											children: diff.changed ? "有改动" : "无改动"
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["新增 ", diffSummary.added] }),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["删除 ", diffSummary.removed] }),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["修改 ", diffSummary.modified] }),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["未变 ", diffSummary.unchanged] }),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											style: { color: "#116329" },
											children: ["已通过 ", diffSummary.approved]
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											style: { color: "#cf222e" },
											children: ["已驳回 ", diffSummary.rejected]
										}),
										reviewInfo !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
											"已存 review ",
											reviewInfo.rounds,
											" 轮",
											reviewInfo.latest !== void 0 && `（最近：${reviewInfo.latest.reviewer} · ${reviewInfo.latest.conclude}）`
										] })
									]
								}),
								!diff.hasBase && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "kb-warn",
									children: [
										"base（",
										diff.base,
										"）下无此文件，整篇按新增处理。"
									]
								}),
								expired.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "kb-expired",
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										style: {
											fontWeight: 600,
											marginBottom: 4
										},
										children: [
											"已过期意见（",
											expired.length,
											"）——块内容已变，key 失效，不回填："
										]
									}), expired.map((eb, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "kb-expired-item",
										children: [
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
												className: "d-badge",
												"data-s": "expired",
												children: "已过期"
											}),
											" ",
											"[",
											TYPE_LABEL[eb.type] ?? eb.type,
											"] ",
											eb.summary,
											eb.decision !== void 0 && ` · ${eb.decision === "approve" ? "曾通过" : "曾驳回"}`,
											eb.comment !== void 0 && eb.comment !== "" && ` · 注释：${eb.comment}`
										]
									}, i))]
								}),
								diff.blocks.map((b) => {
									const key = b.key;
									const rv = reviews[key] ?? {};
									const isUnchanged = b.status === "unchanged";
									const open = isUnchanged ? expanded[key] ?? false : true;
									const showRaw = rawOps[key] ?? false;
									return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "d-block",
										children: [
											/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
												className: "d-head",
												children: [
													/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
														className: "d-badge",
														"data-s": b.status,
														children: STATUS_LABEL[b.status]
													}),
													/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
														className: "d-type",
														children: [TYPE_LABEL[b.type] ?? b.type, b.type === "heading" ? ` H${b.level}` : ""]
													}),
													/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
														className: "d-head-t",
														children: b.summary
													}),
													isUnchanged && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
														className: "d-expand",
														onClick: () => setExpanded((prev) => ({
															...prev,
															[key]: !(prev[key] ?? false)
														})),
														children: open ? "收起" : "展开"
													}),
													!isUnchanged && b.ops !== void 0 && b.ops.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
														className: "d-expand",
														onClick: () => setRawOps((prev) => ({
															...prev,
															[key]: !showRaw
														})),
														children: showRaw ? "看渲染" : "看行级"
													})
												]
											}),
											open && (showRaw && b.ops !== void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
												className: "d-ops",
												children: renderOps(b.ops)
											}) : renderBlockBody(b)),
											!isUnchanged && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
												className: "d-actions",
												children: [
													/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
														className: "d-btn d-btn-ap" + (rv.decision === "approve" ? " on" : ""),
														onClick: () => setReview(key, { decision: rv.decision === "approve" ? void 0 : "approve" }),
														children: "通过"
													}),
													/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
														className: "d-btn d-btn-rj" + (rv.decision === "reject" ? " on" : ""),
														onClick: () => setReview(key, { decision: rv.decision === "reject" ? void 0 : "reject" }),
														children: "驳回"
													}),
													/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
														className: "d-btn",
														onClick: () => setReview(key, { open: !(rv.open ?? false) }),
														children: "注释"
													}),
													rv.comment !== void 0 && rv.comment !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
														className: "kb-sub",
														children: [
															"已注：",
															rv.comment.slice(0, 40),
															rv.comment.length > 40 ? "…" : ""
														]
													}),
													(rv.open ?? false) && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
														className: "d-cmt",
														placeholder: "写审阅注释…",
														value: rv.comment ?? "",
														onChange: (e) => setReview(key, { comment: e.target.value })
													})
												]
											})
										]
									}, key);
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "d-actions",
									style: {
										border: "1px solid #d0d7de",
										borderRadius: 8,
										background: "#fff"
									},
									children: [
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "kb-sub",
											children: "整篇结论："
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("select", {
											className: "d-conclude",
											value: conclude,
											onChange: (e) => setConclude(e.target.value),
											children: [
												"in-progress",
												"approved",
												"changes-requested"
											].map((c) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
												value: c,
												children: CONCLUDE_LABEL[c]
											}, c))
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
											className: "kb-btn kb-btn-blue",
											disabled: saveState.saving === true,
											onClick: () => {
												saveReview();
											},
											children: saveState.saving === true ? "保存中…" : "保存 review"
										}),
										saveState.runId !== void 0 && saveState.runId !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "kb-sub",
											style: { color: "#116329" },
											children: [
												"已保存（run-id ",
												saveState.runId,
												"）"
											]
										}),
										saveState.error !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "kb-sub",
											style: { color: "#cf222e" },
											children: ["保存失败：", saveState.error]
										})
									]
								}),
								reworkMd !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "kb-rework",
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										style: {
											display: "flex",
											alignItems: "center",
											gap: 10
										},
										children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											style: { fontWeight: 600 },
											children: "rework 指令（可贴进工单派返工活）"
										}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
											className: "d-btn",
											onClick: () => {
												try {
													navigator.clipboard?.writeText(reworkMd);
												} catch {}
											},
											children: "复制"
										})]
									}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", { children: reworkMd })]
								})
							] })
						]
					})
				]
			})
		] })
	});
}
/**
* 260823 起知识库 UI 不再占 chat 顶部页签——移到工单台侧栏中栏，
* 由 sandbar-workbench 的侧栏直接 import KnowledgeSection 渲染（用户拍板：chat 页签只留 chat/trajectory）。
* apply 保留为空操作（宿主装载契约要求导出）。
* t260916-26 注：0.1.5 的会话视图扩展面若将来恢复插件自持页签，走
* uiConversation.views.register（0.1.5）/ conversationViews.register（0.1.1）
* 双轨探测——见 ./inject-contract 白名单纪律。
*/
function apply(_ctx) {}
//#endregion
exports.KnowledgeSection = KnowledgeSection;
exports.apply = apply;
exports.inject = inject;
exports.name = name;

return module.exports; } });