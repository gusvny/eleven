window.__ModuleLoader__.load({ id: "sandbar-workbench", factory: (require) => { var module = { exports: {} }; var exports = module.exports;
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
let react = require("react");
let react_jsx_runtime = require("react/jsx-runtime");
//#region src/client/problems-model.ts
const asString$1 = (v) => typeof v === "string" ? v : "";
const asFinite = (v) => typeof v === "number" && Number.isFinite(v) ? v : null;
/** gate_runs 末条（容忍 detail/gate_runs 畸形：非对象/非数组 → undefined）。 */
function lastGateRun(detail) {
	if (detail === null || typeof detail !== "object") return void 0;
	const runs = detail.gate_runs;
	if (!Array.isArray(runs) || runs.length === 0) return void 0;
	const g = runs[runs.length - 1];
	return g !== null && typeof g === "object" ? g : void 0;
}
/** gate 的展示标签：label 优先、stage 兜底，畸形 → 'gate'。 */
function gateStageLabel(g) {
	if (!g) return "gate";
	return asString$1(g.label) || asString$1(g.stage) || "gate";
}
/** merge_check 形态：checks 数组里的红项 → 行（项内畸形逐条跳过不抛）。 */
function rowsFromChecks(checks) {
	if (!Array.isArray(checks)) return [];
	const out = [];
	for (let i = 0; i < checks.length; i++) {
		const c = checks[i];
		if (c === null || typeof c !== "object") continue;
		const co = c;
		if (co.green === true) continue;
		const item = asString$1(co.item) || asString$1(co.id) || `check #${i}`;
		out.push({
			key: `check-${i}-${item}`,
			text: `merge_check red: ${item}`,
			dim: asString$1(co.detail) || void 0
		});
	}
	return out;
}
/** 轻道闸形态（无 checks 键）：自带字段 → 人话原因行。 */
function rowsFromLightGate(g) {
	const out = [];
	const err = asString$1(g.error);
	if (err) out.push({
		key: "error",
		text: `gate error: ${err}`
	});
	const counts = g.counts;
	if (counts !== null && typeof counts === "object" && !Array.isArray(counts)) {
		const parts = [];
		for (const [k, v] of Object.entries(counts)) {
			const n = asFinite(v);
			if (n !== null) parts.push(`${k}=${n}`);
		}
		if (parts.length > 0) out.push({
			key: "counts",
			text: `gate counts: ${parts.join(" / ")}`
		});
	}
	const red = asFinite(g.red_count);
	if (red !== null && red > 0) out.push({
		key: "red_count",
		text: `${red} red item(s) this round`
	});
	const exit = asFinite(g.exit_code);
	if (exit !== null && exit !== 0) out.push({
		key: "exit_code",
		text: `exit_code=${exit}`
	});
	return out;
}
/**
* gate_runs 末条 → 原因行（问题区主数据源，形态容忍）：
* - red（green === false）：checks 形态走逐项行；否则走轻道自带字段；
*   两面都空也要点名「该闸红但无明细」（绝不静默空白）。
* - 非 red / 畸形 / 缺席：空数组（调用方回落 timeline reason / 兜底行）。
*/
function gateProblemRows(detail) {
	const g = lastGateRun(detail);
	if (!g || g.green !== false) return [];
	const label = gateStageLabel(g);
	const rows = Array.isArray(g.checks) ? rowsFromChecks(g.checks) : rowsFromLightGate(g);
	if (rows.length === 0) rows.push({
		key: "no-detail",
		text: `${label}: red (no per-item detail recorded)`
	});
	return rows;
}
/**
* 槽条目渲染崩溃 → 边界 fallback 文案（t261001-11 第二缺陷：一个坏记录
* 曾能打掉整个侧栏——现在边界兜住，点名故障、其余 UI 存活）。
* 畸形 error（非 Error/空 message）也有可读文案，绝不渲染空白。
*/
function slotFaultMessage(error) {
	return `Workbench panel crashed while rendering: ${(error instanceof Error ? error.message : typeof error === "string" ? error : "") || "unknown fault"} — the rest of the console stays usable.`;
}
//#endregion
//#region ../knowledge/src/client/markdown.ts
/**
* markdown.ts — 无依赖的轻量 Markdown 渲染器（供 sandbar-knowledge 知识库插件用）。
*
* 支持（docs knowledge-base-design §5.1）：
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
	s = s.replace(/(^|[^0-9A-Za-z_])__([^_]+)__(?![0-9A-Za-z_])/g, "$1<strong>$2</strong>");
	s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
	s = s.replace(/(^|[^0-9A-Za-z_])_([^_\n]+)_(?![0-9A-Za-z_])/g, "$1<em>$2</em>");
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
//#region ../knowledge/src/shared/blocks.ts
/** 表格行 → 单元格数组（client 做单元格级对齐也用）。 */
function splitCells(line) {
	let s = line.trim();
	if (s.startsWith("|")) s = s.slice(1);
	if (s.endsWith("|")) s = s.slice(0, -1);
	return s.split("|").map((c) => c.trim());
}
//#endregion
//#region src/shared/parts.ts
const PART_ICON = {
	agent: "🤖",
	script: "⚙️",
	human: "👤"
};
/** 悬停说明里的人读标签。 */
const PART_LABEL = {
	agent: "agent",
	script: "script / programmatic",
	human: "human"
};
/** 徽标串：parts 直接拼接（如 ['agent','script'] → '🤖⚙️'）；空/undefined → '—'。 */
function partsIcons(parts) {
	if (!parts || parts.length === 0) return "—";
	return parts.map((p) => PART_ICON[p] ?? "❓").join("");
}
/** 悬停一行说明：「执行主体：🤖 agent 执行 + ⚙️ 脚本/程序化」；空/undefined → 旧数据口径说明。 */
function partsTitle(parts) {
	if (!parts || parts.length === 0) return "Executed by: — (legacy data has no static parts declaration; actual runtime is authoritative)";
	return `Executed by: ${parts.map((p) => {
		const icon = PART_ICON[p];
		const label = PART_LABEL[p];
		return icon ? `${icon} ${label}` : `❓ unknown executor ${p}`;
	}).join(" + ")} (static declaration; dynamic source of truth = Temporal history)`;
}
//#endregion
//#region src/client/lane-states.ts
/** 就地段信号（t260912-03 授权通道 authorized / retry_qc 信号 retry-requested）：
*  引擎 raw append 落当前段、不重进段——显示口径见规则 2 的受阻期判定。 */
const IN_PLACE_MARKS = /* @__PURE__ */ new Set(["authorized", "retry-requested"]);
/** 单值指针口径（回退用，逐字节为 t260901-05 之前的现行行为，勿改）。 */
function pointerStates(detail, order) {
	const states = {};
	const curIdx = order.indexOf(detail.stage ?? "");
	for (const stageId of order) {
		const idx = order.indexOf(stageId);
		if (idx >= 0 && curIdx >= 0) {
			if (idx < curIdx) {
				states[stageId] = "done";
				continue;
			}
			if (idx > curIdx) {
				states[stageId] = "todo";
				continue;
			}
			if (detail.stage_state === "blocked") {
				states[stageId] = "blocked";
				continue;
			}
			if (detail.stage_state === "awaiting-human") {
				states[stageId] = "awaiting-human";
				continue;
			}
			states[stageId] = "running";
			continue;
		}
		if (stageId === detail.stage) {
			if (detail.stage_state === "blocked") {
				states[stageId] = "blocked";
				continue;
			}
			if (detail.stage_state === "awaiting-human") {
				states[stageId] = "awaiting-human";
				continue;
			}
			states[stageId] = "running";
			continue;
		}
		const r = detail.results?.[stageId];
		states[stageId] = r && r.status === "ok" ? "done" : "todo";
	}
	return states;
}
/** KI-024 并行真源提取：meta.parallel_stages（优先）∨ 顶层 parallel_stages，
*  清洗为 order 内的合法 id 列表（去重保序）。缺失/非数组/全非法 → 空数组
*  （=「当前无并行」，调用方走既有推导，零回归）。 */
function parallelIdsOf(detail, order) {
	const metaRaw = detail.meta?.parallel_stages;
	const raw = metaRaw !== void 0 ? metaRaw : detail.parallel_stages;
	if (!Array.isArray(raw)) return [];
	const known = new Set(order);
	const out = [];
	for (const x of raw) if (typeof x === "string" && known.has(x) && !out.includes(x)) out.push(x);
	return out;
}
/** 兄弟段判定（兄弟段干完≠本段推进）：groups 在场（已知拓扑）按同组；缺省按
*  相位——两条目 phase 均非空且相等=兄弟，一空一非空=不同相位=非兄弟，均空
*  （老票无相位标注，无法判兄弟）按兄弟保守处理——宁红不漏（t260916-04 ③）。 */
function siblingOf(s, t, groups, phaseB, phaseE) {
	if (Array.isArray(groups)) return groups.some((g) => Array.isArray(g) && g.includes(s) && g.includes(t));
	if (phaseB && phaseE) return phaseB === phaseE;
	if (!phaseB && !phaseE) return true;
	return false;
}
/** 受阻史与当前性判定（t260916-04）：对每段取最后一次 blocked，按其后的证据判
*  「是否已解除」（E1 rerun / E2 advanced / E3 closed，口径见模块头注）。纯函数、
*  全程不抛；只对 order 内的段产出键，模板外 id 不泄漏。 */
function deriveBlockedHistory(detail, order, opts) {
	const out = {};
	if (!Array.isArray(detail.timeline)) return out;
	const clean = [];
	for (const t of detail.timeline) {
		if (!t || typeof t.stage !== "string" || typeof t.state !== "string") continue;
		if (t.stage === "" || t.state === "") continue;
		clean.push({
			stage: t.stage,
			state: t.state,
			at: typeof t.at === "string" && t.at ? t.at : void 0,
			reason: typeof t.reason === "string" && t.reason ? t.reason : void 0,
			gen: typeof t.gen === "number" && Number.isFinite(t.gen) ? t.gen : void 0,
			phase: typeof t.phase === "string" && t.phase ? t.phase : void 0
		});
	}
	const byStage = {};
	clean.forEach((e, pos) => {
		(byStage[e.stage] ??= []).push(pos);
	});
	const idxOf = new Map(order.map((id, i) => [id, i]));
	const closed = detail.status === "closed";
	for (const id of order) {
		const positions = byStage[id];
		if (!positions || positions.length === 0) continue;
		const passes = positions.map((pos) => ({
			e: clean[pos],
			pos
		})).filter((x) => x.e.state === "blocked");
		if (passes.length === 0) continue;
		const lastB = passes[passes.length - 1];
		let resolved = false;
		let resolvedBy;
		let resolvedAt;
		if (closed) {
			resolved = true;
			resolvedBy = "closed";
		} else {
			const donePos = positions.find((p) => p > lastB.pos && clean[p].state === "done");
			if (donePos !== void 0) {
				resolved = true;
				resolvedBy = "rerun";
				resolvedAt = clean[donePos].at;
			} else {
				const sIdx = idxOf.get(id);
				if (sIdx !== void 0) for (let p = lastB.pos + 1; p < clean.length && !resolved; p++) {
					const e = clean[p];
					const tIdx = idxOf.get(e.stage);
					if (tIdx === void 0 || tIdx <= sIdx) continue;
					if (siblingOf(id, e.stage, opts?.groups, lastB.e.phase, e.phase)) continue;
					resolved = true;
					resolvedBy = "advanced";
					resolvedAt = e.at;
				}
			}
		}
		out[id] = {
			passes: passes.map((x) => ({
				at: x.e.at,
				reason: x.e.reason,
				gen: x.e.gen,
				phase: x.e.phase
			})),
			last: {
				at: lastB.e.at,
				reason: lastB.e.reason,
				gen: lastB.e.gen,
				phase: lastB.e.phase
			},
			resolved,
			...resolvedBy !== void 0 ? { resolvedBy } : {},
			...resolvedAt !== void 0 ? { resolvedAt } : {}
		};
	}
	return out;
}
function deriveStageStates(detail, order, opts) {
	const blockedHistory = deriveBlockedHistory(detail, order, opts);
	if (detail.status === "closed") {
		const states = {};
		for (const id of order) states[id] = "done";
		return {
			states,
			active: [],
			fallback: false,
			blockedHistory
		};
	}
	const tl = detail.timeline;
	if (!tl || tl.length === 0) return {
		states: pointerStates(detail, order),
		active: [],
		fallback: true,
		blockedHistory
	};
	const runningCount = {};
	const latest = {};
	const lastPosOf = {};
	let pos = 0;
	for (const t of tl) {
		if (!t || typeof t.stage !== "string" || typeof t.state !== "string") continue;
		if (t.stage === "" || t.state === "") continue;
		if (t.state === "running") runningCount[t.stage] = (runningCount[t.stage] ?? 0) + 1;
		latest[t.stage] = t.state;
		(lastPosOf[t.stage] ??= {})[t.state] = pos;
		pos++;
	}
	const checks = detail.checks ?? {};
	const results = detail.results ?? {};
	const attemptsOf = (id) => {
		const r = results[id];
		if (r) return typeof r.gen === "number" ? r.gen + 1 : 1;
		const cs = checks[id];
		if (cs && cs.length > 0 && cs.every((c) => c.done)) return 1;
		return 0;
	};
	const doneIdx = [];
	order.forEach((id, idx) => {
		const r = results[id];
		const cs = checks[id];
		if (r && r.status === "ok" || cs && cs.length > 0 && cs.every((c) => c.done)) doneIdx.push(idx);
	});
	const maxDoneIdx = doneIdx.length > 0 ? Math.max(...doneIdx) : -1;
	const states = {};
	const active = [];
	order.forEach((id, idx) => {
		const last = latest[id];
		if (last === "blocked") {
			const h = blockedHistory[id];
			if (h && h.resolved) {
				states[id] = "done";
				return;
			}
			states[id] = "blocked";
			return;
		}
		if (last === "awaiting-human" || last === "done") {
			states[id] = last;
			return;
		}
		if (last !== void 0 && IN_PLACE_MARKS.has(last)) {
			const bp = lastPosOf[id]?.blocked;
			if (bp !== void 0) {
				if (![
					"running",
					"done",
					"awaiting-human"
				].some((st) => {
					const p = lastPosOf[id]?.[st];
					return p !== void 0 && p > bp;
				})) {
					states[id] = "blocked";
					return;
				}
			}
		}
		if ((runningCount[id] ?? 0) > attemptsOf(id)) {
			states[id] = "running";
			active.push(id);
			return;
		}
		const r = results[id];
		const cs = checks[id];
		if (r && r.status === "ok" || cs && cs.length > 0 && cs.every((c) => c.done) || idx <= maxDoneIdx) {
			states[id] = "done";
			return;
		}
		states[id] = "todo";
	});
	const parallelIds = parallelIdsOf(detail, order);
	for (const id of parallelIds) {
		const cur = states[id];
		if (cur === "done" || cur === "blocked" || cur === "awaiting-human") continue;
		states[id] = "running";
		if (!active.includes(id)) active.push(id);
	}
	if (active.length === 0) return {
		states: pointerStates(detail, order),
		active: [],
		fallback: true,
		blockedHistory
	};
	return {
		states,
		active,
		fallback: false,
		blockedHistory
	};
}
//#endregion
//#region src/client/lane-durations.ts
/** handoff 的 stage 键与 lane id 不同词表的显式映射（其余错位键不发明映射，
*  该步回退口径 3/4/5）。acceptance_walkthrough 步的 handoff 键是 "acceptance"
*  （dev_lane.py:1104 vs :1102 _finish 用 "acceptance_walkthrough"）。 */
const HANDOFF_KEY_ALIAS = { acceptance: "acceptance_walkthrough" };
function msOfIso(at) {
	if (typeof at !== "string" || at === "") return null;
	const ms = new Date(at).getTime();
	return Number.isFinite(ms) ? ms : null;
}
/** 收集 order 内的合法 marks 并升序排序（乱序快照不炸、不分叉）。 */
function collectMarks(timeline, order) {
	const inOrder = new Set(order);
	const marks = [];
	for (const t of Array.isArray(timeline) ? timeline : []) {
		if (!t || typeof t.stage !== "string" || typeof t.state !== "string") continue;
		if (t.stage === "" || t.state === "") continue;
		if (!inOrder.has(t.stage)) continue;
		const ms = msOfIso(t.at);
		if (ms === null) continue;
		marks.push({
			stage: t.stage,
			state: t.state,
			ms
		});
	}
	return marks.sort((a, b) => a.ms - b.ms);
}
/** 收集合法 handoff（epoch 秒 → ms；畸形条目映射前跳过）。 */
function collectHandoffs(handoffs) {
	const out = [];
	for (const h of Array.isArray(handoffs) ? handoffs : []) {
		if (!h || typeof h.stage !== "string" || h.stage === "") continue;
		if (typeof h.ts !== "number" || !Number.isFinite(h.ts)) continue;
		out.push({
			stage: HANDOFF_KEY_ALIAS[h.stage] ?? h.stage,
			ms: h.ts * 1e3
		});
	}
	return out;
}
/**
* 推导每个 order stage 的轮窗与人等段。
* 返回 Record 只含 timeline 里出现过 running mark 的 stage（键 ⊆ order）。
*/
function deriveStageDurations(timeline, order, handoffs, opts) {
	const marks = collectMarks(timeline, order);
	const handoffList = collectHandoffs(handoffs);
	const closedMs = typeof opts?.closedTs === "number" && Number.isFinite(opts.closedTs) ? opts.closedTs * 1e3 : null;
	const closedMarkMs = marks.find((m) => m.stage === "merge" && m.state === "closed")?.ms ?? null;
	const out = {};
	for (const stage of order) {
		const runningMs = marks.filter((m) => m.stage === stage && m.state === "running").map((m) => m.ms);
		const ahMarks = marks.filter((m) => m.stage === stage && m.state === "awaiting-human");
		if (runningMs.length === 0 && ahMarks.length === 0) continue;
		const rounds = [];
		for (let i = 0; i < runningMs.length; i++) {
			const fromMs = runningMs[i];
			const ownNext = i + 1 < runningMs.length ? runningMs[i + 1] : null;
			const upper = ownNext ?? Number.POSITIVE_INFINITY;
			let handoffBest = null;
			for (const h of handoffList) {
				if (h.stage !== stage) continue;
				if (h.ms <= fromMs || h.ms > upper) continue;
				handoffBest = handoffBest === null ? h.ms : Math.max(handoffBest, h.ms);
			}
			let toMs;
			if (handoffBest !== null) toMs = handoffBest;
			else if (ownNext !== null) {
				const cm = closedMarkMs !== null && closedMarkMs > fromMs && closedMarkMs <= upper ? closedMarkMs : null;
				const nextOther = marks.find((m) => m.stage !== stage && m.state === "running" && m.ms > fromMs);
				if (cm !== null && (nextOther === void 0 || cm <= nextOther.ms)) toMs = cm;
				else if (nextOther !== void 0 && nextOther.ms <= upper) toMs = nextOther.ms;
				else toMs = ownNext;
			} else if (closedMarkMs !== null && closedMarkMs > fromMs) toMs = closedMarkMs;
			else {
				const nextOther = marks.find((m) => m.stage !== stage && m.state === "running" && m.ms > fromMs);
				if (nextOther !== void 0) toMs = nextOther.ms;
				else if (closedMs !== null) toMs = closedMs;
				else toMs = null;
			}
			rounds.push({
				fromMs,
				toMs
			});
		}
		const humanWaits = [];
		for (const m of ahMarks) {
			const next = marks.find((x) => x.ms > m.ms);
			let toMs = next ? next.ms : null;
			if (toMs === null) {
				if (closedMarkMs !== null && closedMarkMs > m.ms) toMs = closedMarkMs;
				else if (closedMs !== null) toMs = closedMs;
			}
			humanWaits.push({
				fromMs: m.ms,
				toMs
			});
		}
		out[stage] = {
			stage,
			rounds,
			humanWaits
		};
	}
	return out;
}
/** 一段窗的墙钟时长（ms）；开放窗用 nowMs 实时差；负差（时钟回拨）→ null。 */
function windowMs(w, nowMs) {
	const d = (w.toMs ?? nowMs ?? Date.now()) - w.fromMs;
	return Number.isFinite(d) && d >= 0 ? d : null;
}
/** 一个 stage 的总耗时 = Σ各轮（开放轮用 nowMs）；任一轮非法 → null。 */
function stageTotalMs(d, nowMs) {
	if (d.rounds.length === 0) return null;
	let total = 0;
	for (const r of d.rounds) {
		const ms = windowMs(r, nowMs);
		if (ms === null) return null;
		total += ms;
	}
	return total;
}
/** 人等总时长（各段求和，开放段用 nowMs）；无人等段 → 0。 */
function humanWaitTotalMs(d, nowMs) {
	let total = 0;
	for (const w of d.humanWaits) {
		const ms = windowMs(w, nowMs);
		if (ms !== null) total += ms;
	}
	return total;
}
/** 时长格式化：<60s「Xs」；<60m「Xm Ys」（0 秒段省略）；≥1h「Xh Ym」（分段恒显，
*  含 0——「1h 0m」比「1h」更不易误读为分钟）；null/undefined/负/NaN → 「—」。 */
function fmtDur$1(ms) {
	if (ms === null || ms === void 0 || !Number.isFinite(ms) || ms < 0) return "—";
	const totalSec = Math.floor(ms / 1e3);
	const s = totalSec % 60;
	const m = Math.floor(totalSec / 60) % 60;
	const h = Math.floor(totalSec / 3600);
	if (h > 0) return `${h}h ${m}m`;
	if (m > 0) return s > 0 ? `${m}m ${s}s` : `${m}m`;
	return `${s}s`;
}
/** 节点 tooltip 文案：耗时 + 逐轮 + 人等段单列（人等已计入所在轮的总耗时
*  ——见头注真实口径；此处的「人等」是拆看视图，不是从轮里扣减）。 */
function stageDurationTitle(d, nowMs) {
	const parts = [];
	const total = stageTotalMs(d, nowMs);
	if (total !== null) parts.push(`took ${fmtDur$1(total)}`);
	d.rounds.forEach((r, i) => {
		parts.push(`Round ${i + 1} ${fmtDur$1(windowMs(r, nowMs))}`);
	});
	if (d.humanWaits.length > 0) {
		const seg = d.humanWaits.map((w) => fmtDur$1(windowMs(w, nowMs))).join(" + ");
		parts.push(`human wait ${fmtDur$1(humanWaitTotalMs(d, nowMs))} (${seg})`);
	}
	return parts.join(" · ");
}
//#endregion
//#region src/client/lane-map-model.ts
/**
* lane-map-model —— 真泳道图（拓扑驱动）视图模型（t260915-05，mock ③/④）。
*
* 设计样张：notes/discussions/260904-ticket-detail-ui-mock.html 屏③/④
* （并行双道虚线框＋轮次徽章逐轮格 hover 证据＋人门虚线圈＋不画返工弧；
* callout F/G：渲染器只认「节点+边+kind」，标签全部来自拓扑，零业务词）。
*
* 数据源：
*   - topology：模板拓扑导出契约（引擎 template_topology.py topology-v1，经
*     workflow.py list / ticket show 投影面透传）。null/畸形 → buildLaneMap 返回
*     null = 调用方回落现行线性步骤条（零回归降级锚）。
*   - detail：工单详情（ticket show 投影面）。消费 timeline（gen/phase 键，
*     t260915-01 ③）、gens、handoffs（gen 键）、results、checks、gate_runs、
*     meta.parallel_stages/parallel_phase、status/stage/stage_state；
*     t260916-04 起并消费受阻史（blockedHistory：解除判定住 lane-states 推导层，
*     拓扑并行组透传给它做兄弟段判定；节点视图携史供渲染层出「曾受阻」角标）。
*
* 轮次口径（与 lane-durations 的轮窗同族，此处取「轮格」语义）：
*   - 引擎 timeline 条目带 gen（门开的新票）→ 按 gen 分组，一轮一格；
*   - 老票无 gen → 回退「每条 running mark 开新轮」的计数口径
*     （lane-durations 同款真值表），轮内证据无 gen 标注=如实缺省；
*   - 认领行（建票时的 `adopt …` / state=awaiting，带 gen=0 或不带 gen）**不是**
*     该段的一次入场 → 不进轮次带（否则首段凭空多一格 + 徽章 ×N 撒谎，实报
*     t260930-09：轻道首段 implement 被画成两轮）；真实重入（rework/retry_qc）
*     照旧逐轮成格，只剔认领行、不剔「同段首次出现」；
*   - 轮结局=该轮内最后一条显式态（done/blocked/awaiting-human/rework），
*     无显式态=running；hover title=该轮 at/结局/reason/phase/handoff 摘要。
*
* 畸形输入纪律（外部快照不可信，与 lane-states/lane-durations 同款）：
*   非串 id/state 的条目跳过；拓扑外 stage id 不建视图不泄漏；全程不抛。
*   消费本模块的渲染器不得出现任何 dev-lane 专属词（fixture-two-step 对拍锚）。
*/
/** kind 图标（渲染器唯一认识的视觉词，零业务语义）。 */
const LANE_KIND_ICON = {
	agent: "🤖",
	gate: "✓",
	human: "👤"
};
function asString(v) {
	return typeof v === "string" ? v : "";
}
function asStringArray$1(v) {
	return Array.isArray(v) ? v.filter((x) => typeof x === "string" && x.trim() !== "") : [];
}
const EXPLICIT_STATES = /* @__PURE__ */ new Set([
	"done",
	"blocked",
	"awaiting-human",
	"rework"
]);
/** 清洗原始拓扑；不可救（非对象/无合法节点）→ null=调用方回落线性步骤条。 */
function parseTopology(raw) {
	if (raw === null || typeof raw !== "object") return null;
	const r = raw;
	if (!Array.isArray(r.nodes)) return null;
	const nodes = [];
	const ids = /* @__PURE__ */ new Set();
	for (const n of r.nodes) {
		if (n === null || typeof n !== "object") continue;
		const o = n;
		const id = asString(o.id);
		const label = asString(o.label);
		const kind = asString(o.kind);
		if (!id || !label) continue;
		if (kind !== "agent" && kind !== "gate" && kind !== "human") continue;
		if (ids.has(id)) continue;
		ids.add(id);
		nodes.push({
			id,
			label,
			kind,
			role: asString(o.role),
			parts: asStringArray$1(o.parts),
			...asString(o.optional) ? { optional: asString(o.optional) } : {}
		});
	}
	if (nodes.length === 0) return null;
	const edges = [];
	if (Array.isArray(r.edges)) for (const e of r.edges) {
		if (!Array.isArray(e) || e.length !== 2) continue;
		const [a, b] = e;
		if (typeof a === "string" && typeof b === "string" && ids.has(a) && ids.has(b)) edges.push([a, b]);
	}
	const groups = [];
	if (Array.isArray(r.groups)) for (const g of r.groups) {
		if (g === null || typeof g !== "object") continue;
		const o = g;
		const id = asString(o.id);
		const members = asStringArray$1(o.members).filter((m) => ids.has(m));
		if (id && members.length >= 2) groups.push({
			id,
			members,
			phase: asString(o.phase)
		});
	}
	return {
		version: asString(r.version) || void 0,
		template: asString(r.template) || "unknown",
		name: asString(r.name) || void 0,
		nodes,
		edges,
		groups
	};
}
function timelineOf(detail) {
	if (!Array.isArray(detail.timeline)) return [];
	const out = [];
	for (const e of detail.timeline) {
		if (e === null || typeof e !== "object") continue;
		const o = e;
		const stage = asString(o.stage);
		const state = asString(o.state);
		if (!stage || !state) continue;
		out.push({
			stage,
			state,
			at: asString(o.at) || void 0,
			reason: asString(o.reason) || void 0,
			gen: typeof o.gen === "number" && Number.isFinite(o.gen) ? o.gen : void 0,
			phase: asString(o.phase) || void 0
		});
	}
	return out;
}
/**
* 认领行（adopt）识别：建票时引擎在实例初始化里写的第一条条目
* （base.py:761 / dev_lane.py:980 的 `_mark(first.id, "awaiting", "adopt …")`）
* 把票面初段指向本道首段，**不是**该段的入场，不得计成一轮。
*
* 识别只认形状，不认位置（「第几个出现的」不是判据）：
*   state === 'awaiting' 且 reason 以词 'adopt' 起（引擎英文标识，两种模板同词
*   ——dev-lane「adopt dev-lane（步=…）」/ 基类「adopt v2（模版=…）」）。
* 形状不认识（awaiting 但 reason 不是 adopt 起头、或 reason 缺省）→ **保留现行口径**
* （如实成轮）：宁可多一格可见的疑点，也不静默丢行（畸形输入纪律）。
* 真实重入（rework 回打 / retry_qc 重跑）落的是 running/rework/done，形状不撞。
*/
function isAdoptionEntry(e) {
	return e.state === "awaiting" && /^adopt\b/.test(e.reason ?? "");
}
function handoffsOf(detail) {
	if (!Array.isArray(detail.handoffs)) return [];
	const out = [];
	for (const h of detail.handoffs) {
		if (h === null || typeof h !== "object") continue;
		const o = h;
		const stage = asString(o.stage);
		if (!stage) continue;
		out.push({
			stage,
			summary: asString(o.summary) || void 0,
			gen: typeof o.gen === "number" && Number.isFinite(o.gen) ? o.gen : void 0
		});
	}
	return out;
}
/** 段→轮次带。gen 键在场按 gen 分组；缺省回退「running mark 切轮」计数口径。
*  认领行（adopt）先剔除——它既会自成 gen=0 的一桶（新票），也会在无 gen 的
*  老票上被当成「首轮」，两种形态都会给首段凭空多出一格（实报 t260930-09）。 */
function deriveRounds(stageId, detail) {
	const entries = timelineOf(detail).filter((e) => e.stage === stageId && !isAdoptionEntry(e));
	if (entries.length === 0) return [];
	const hasGen = entries.some((e) => typeof e.gen === "number");
	const buckets = [];
	if (hasGen) {
		const byGen = /* @__PURE__ */ new Map();
		for (const e of entries) {
			const g = typeof e.gen === "number" ? e.gen : 1;
			if (!byGen.has(g)) byGen.set(g, []);
			byGen.get(g).push(e);
		}
		for (const g of [...byGen.keys()].sort((a, b) => a - b)) buckets.push(byGen.get(g));
	} else {
		let cur = [];
		for (const e of entries) {
			if (e.state === "running" && cur.length > 0) {
				buckets.push(cur);
				cur = [];
			}
			cur.push(e);
		}
		if (cur.length > 0) buckets.push(cur);
	}
	const handoffs = handoffsOf(detail).filter((h) => (HANDOFF_KEY_ALIAS[h.stage] || h.stage) === stageId);
	let handoffCursor = 0;
	const rounds = [];
	buckets.forEach((bucket, i) => {
		let state = "running";
		let reason;
		for (const e of bucket) if (EXPLICIT_STATES.has(e.state)) {
			state = e.state;
			reason = e.reason;
		}
		const first = bucket[0];
		const gen = typeof first.gen === "number" ? first.gen : i + 1;
		let handoffSummary;
		while (handoffCursor < handoffs.length) {
			const h = handoffs[handoffCursor];
			if (typeof h.gen === "number" && h.gen !== gen) break;
			handoffSummary = h.summary;
			handoffCursor += 1;
			break;
		}
		rounds.push({
			gen,
			state,
			at: first.at,
			reason,
			phase: bucket.find((e) => e.phase)?.phase,
			handoffSummary
		});
	});
	return rounds;
}
/** gate_runs → 检查明细区行模型（最新在前）。畸形条目逐条跳过不抛。 */
function buildChecksDetail(detail) {
	if (detail === null || typeof detail !== "object") return [];
	const runs = detail.gate_runs;
	if (!Array.isArray(runs)) return [];
	const out = [];
	for (const run of [...runs].reverse()) {
		if (run === null || typeof run !== "object") continue;
		const o = run;
		const stage = asString(o.stage);
		if (!stage) continue;
		const rows = [];
		if (Array.isArray(o.checks)) for (const c of o.checks) {
			if (c === null || typeof c !== "object") continue;
			const co = c;
			const item = asString(co.item);
			const green = co.green === true;
			const checkId = asString(co.id) || void 0;
			if (green && !item && !checkId) continue;
			rows.push({
				green,
				item: item || checkId || "",
				detail: asString(co.detail) || void 0,
				checkId,
				reasonCode: asString(co.reason_code) || void 0,
				files: asStringArray$1(co.files),
				nextAction: asString(co.next_action) || void 0
			});
		}
		out.push({
			stage,
			label: asString(o.label) || stage,
			green: o.green === true,
			redCount: typeof o.red_count === "number" && Number.isFinite(o.red_count) ? o.red_count : rows.filter((r) => !r.green).length,
			gen: typeof o.gen === "number" && Number.isFinite(o.gen) ? o.gen : void 0,
			conflict: o.conflict === true,
			rows
		});
	}
	return out;
}
/**
* 构建泳道图视图模型。返回 null = 拓扑不可用，调用方回落现行线性步骤条
* （零回归降级锚：老 host / 未声明拓扑的模板 / 畸形契约面）。
*/
function buildLaneMap(topologyRaw, detailRaw) {
	const topology = parseTopology(topologyRaw);
	if (!topology) return null;
	const detail = detailRaw !== null && typeof detailRaw === "object" ? detailRaw : {};
	const order = topology.nodes.map((n) => n.id);
	const derived = deriveStageStates({
		status: detail.status,
		stage: detail.stage,
		stage_state: detail.stage_state,
		timeline: Array.isArray(detail.timeline) ? detail.timeline : null,
		results: detail.results !== null && typeof detail.results === "object" ? detail.results : void 0,
		checks: detail.checks !== null && typeof detail.checks === "object" ? detail.checks : void 0,
		parallel_stages: Array.isArray(detail.parallel_stages) ? detail.parallel_stages : void 0,
		meta: detail.meta
	}, order, { groups: topology.groups.map((g) => g.members) });
	const nodes = {};
	for (const n of topology.nodes) {
		const rounds = deriveRounds(n.id, detail);
		const bh = derived.blockedHistory[n.id];
		nodes[n.id] = {
			node: n,
			vis: derived.states[n.id] ?? "todo",
			rounds,
			badge: rounds.length > 1 ? `×${rounds.length}` : "",
			...bh ? { blockedHistory: bh } : {}
		};
	}
	const groups = {};
	for (const g of topology.groups) {
		const members = g.members.map((id) => nodes[id]).filter(Boolean);
		if (members.length < 2) continue;
		groups[g.id] = {
			def: g,
			members,
			active: members.some((m) => m.vis === "running"),
			allDone: members.every((m) => m.vis === "done")
		};
	}
	const groupOf = {};
	for (const g of Object.values(groups)) for (const m of g.members) groupOf[m.node.id] = g.def.id;
	const emitted = /* @__PURE__ */ new Set();
	const items = [];
	for (const n of topology.nodes) {
		const gid = groupOf[n.id];
		if (gid) {
			if (!emitted.has(gid)) {
				emitted.add(gid);
				items.push({
					kind: "group",
					id: gid
				});
			}
		} else items.push({
			kind: "node",
			id: n.id
		});
	}
	return {
		topology,
		items,
		nodes,
		groups,
		humanGateActive: topology.nodes.find((n) => n.kind === "human" && nodes[n.id].vis === "awaiting-human")?.id ?? null,
		closed: detail.status === "closed"
	};
}
//#endregion
//#region src/client/ui-labels.ts
/**
* ui-labels —— 控制台 UI 英文文案唯一映射表（t260925-18，CLAUDE.md 规则 6 补充令）。
*
* 口径（宿主令 260925）：
*  - 界面文案一律英文；数据不译（票面正文/交接报告/台账保持原语言）。
*  - 英文标签以**引擎既有英文标识**为真源（stage id / stage_state / status /
*    workflow 模板 id），由本表统一映射；不另造词、不逐页各译。
*  - 未知值回落原始标识本身（永不空白、永不中文）——engine 加新段/新态时
*    UI 显示原 id，等待本表补条目，不做静默降级。
*
* 纯函数层：无 DOM / 无 IO，node 直跑可测（tests/ui-labels.mjs）。
*/
/** 查表回落：表内无此键 → 返回原始标识（trim 后空白串也视为未知）。 */
function labelOf$1(table, id) {
	if (typeof id !== "string") return "";
	const key = id.trim();
	if (key === "") return "";
	return table[key] ?? key;
}
/** 阶段 id → 英文段名（真源：dev_lane.py / inspection_flow.py Stage(id=…)）。 */
const STAGE_TABLE = {
	create_plan: "Create Plan",
	review_plan: "Review Plan",
	implement: "Implement",
	design_integration_tests: "Design Integration Tests",
	ui_evidence: "UI Evidence",
	run_integration_tests: "Run Integration Tests",
	arbitrate: "Arbitrate",
	acceptance_walkthrough: "Acceptance Walkthrough",
	merge_check: "Merge Check",
	merge: "Merge (Human Review)",
	setup: "Setup",
	suite: "Suite",
	inspect: "Inspect",
	produce: "Produce",
	selfcheck: "Self-check",
	report: "Report",
	close: "Close"
};
/** 阶段态 stage_state → 英文（真源：base.py stage_state 写入点）。 */
const STATE_TABLE = {
	running: "In Progress",
	awaiting: "Awaiting Dispatch",
	"awaiting-human": "Awaiting Approval",
	blocked: "Blocked",
	rework: "Rework",
	done: "Done",
	closed: "Done"
};
/** 工作流模板 id → 英文名（真源：模板注册 id；模板 name 字段是中文数据，不译不显）。 */
const WORKFLOW_TABLE = {
	"dev-lane": "Dev Lane",
	"light-lane": "Light Lane",
	"inspection-lite": "Inspection",
	"chore-lane": "Chore Lane"
};
const STATE_LABEL = STATE_TABLE;
function stageLabel(id) {
	return labelOf$1(STAGE_TABLE, id);
}
function workflowLabel(id) {
	return labelOf$1(WORKFLOW_TABLE, id);
}
/** 段名优先级：拓扑/模板节点自带英文时数据侧已可用；此处只认 id 映射（显示层覆盖，
*  不改引擎数据——review 260925 裁定：引擎中文 label 数据不动，仅显示层按 id 覆盖）。 */
function stageDisplayLabel(stageId, engineName) {
	const mapped = stageLabel(stageId);
	if (mapped !== "" && mapped !== stageId) return mapped;
	if (mapped === "" && typeof engineName === "string" && engineName.trim() !== "") return engineName;
	return mapped;
}
//#endregion
//#region src/client/lane-map.tsx
/**
* lane-map.tsx —— 真泳道图（拓扑驱动）+ 检查明细区组件（t260915-05，mock ①③④）。
*
* 渲染器通用性承诺（mock callout G）：本组件只认「节点+边+kind+组」，
* 标签/顺序/并行/人门全部来自 LaneMapModel（引擎 template_topology 导出契约），
* 组件内零 dev-lane 业务词——换模板换项目同一组件（fixture-two-step 对拍锚）。
*
* 图面语义（mock 屏③）：
*   - 并行组=虚线框，成员纵排双道，任一成员 running 时框高亮（active）；
*   - 人门（kind=human）=虚线圈 👤，到站时状态卡变蓝（蓝卡在 status-card）；
*   - 条件段（optional）=虚节点+条件注记；
*   - 轮次带=同段多轮逐轮一格，hover title=该轮证据/打回原因（数据=gen/phase）；
*   - 不画返工弧：返工史归打回横幅与本组件 ×N 徽章，图面单向流
*     （守卫：组件永不渲染 .wb-lm-arc，DOM 场景断言其恒零）；
*   - 受阻着色（t260916-04）：当前受阻=实心红（data-vis=blocked，CSS 实底）；
*     历史已解除受阻=完成色+「曾受阻」角标（.wb-lm-ever，黄点），节点/角标
*     hover 出经过（何时受阻、何因、如何解除；数据=blockedHistory）。
*/
const LM_ICON = {
	done: "✓",
	running: "▶",
	blocked: "✗",
	"awaiting-human": "✋",
	todo: "○",
	rework: "↺"
};
/** 解除方式人话（hover 经过第三拍「如何解除」；词表=lane-states resolvedBy）。 */
const RESOLVED_HOW = {
	rerun: "stage rerun completed",
	advanced: "workflow advanced to later stages",
	closed: "ticket closed"
};
/** 「曾受阻」经过（何时受阻、何因、如何解除）：角标与节点 hover 共用一段话。 */
function everBlockedTitle(h) {
	const bits = [`Blocked ${h.passes.length}× before`];
	if (h.last.at) bits.push(h.last.at);
	if (h.last.reason) bits.push(h.last.reason);
	if (h.last.gen !== void 0) bits.push(`Round ${h.last.gen}`);
	if (h.resolved) bits.push(`Resolved (${RESOLVED_HOW[h.resolvedBy ?? ""] || "resolved"}${h.resolvedAt ? `: ${h.resolvedAt}` : ""})`);
	return bits.join(" · ");
}
function roundTitle(nv, gen, state) {
	const r = nv.rounds.find((x) => x.gen === gen);
	if (!r) return `Round ${gen}`;
	const bits = [`Round ${r.gen}`];
	if (r.at) bits.push(r.at);
	bits.push(state === "rework" ? "reworked" : state);
	if (r.reason) bits.push(r.reason);
	if (r.phase) bits.push(`Phase ${r.phase}`);
	if (r.handoffSummary) bits.push(r.handoffSummary);
	return bits.join(" · ");
}
/** 单个站点（主道与并行道内共用；道内竖排由父级 flex 方向控制）。 */
function LaneMapNode({ nv, inGroup }) {
	const n = nv.node;
	const glyph = n.kind === "human" ? LANE_KIND_ICON.human : LM_ICON[nv.vis] ?? LM_ICON.todo;
	const ever = nv.blockedHistory?.resolved === true && nv.blockedHistory.passes.length > 0 && nv.vis === "done";
	const everTitle = ever && nv.blockedHistory ? everBlockedTitle(nv.blockedHistory) : "";
	const title = `${stageDisplayLabel(n.id, n.label)} · ${n.role} · ${n.kind}${n.optional ? ` · ${n.optional}` : ""}${everTitle ? ` · ${everTitle}` : ""}`;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
		className: `wb-lm-node${inGroup ? " wb-lm-node-inlane" : ""}`,
		"data-id": n.id,
		"data-kind": n.kind,
		"data-vis": nv.vis,
		"data-ever-blocked": ever ? "true" : void 0,
		title,
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {
				className: "wb-lm-dot",
				children: glyph
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
				className: "wb-lm-name",
				children: [
					stageDisplayLabel(n.id, n.label),
					n.optional ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("em", {
						className: "wb-lm-opt",
						title: `Conditional stage: ${n.optional}`,
						children: n.optional
					}) : null,
					nv.badge ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", {
						className: "wb-lm-badge",
						title: `${nv.rounds.length} rounds at this stage (rework history in the rework banner)`,
						children: nv.badge
					}) : null,
					ever && nv.blockedHistory ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {
						className: "wb-lm-ever",
						title: everBlockedTitle(nv.blockedHistory),
						children: "was blocked"
					}) : null
				]
			}),
			nv.rounds.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: "wb-lm-rounds",
				children: nv.rounds.map((r) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					className: "wb-lm-round",
					"data-gen": r.gen,
					"data-state": r.state,
					title: roundTitle(nv, r.gen, r.state),
					children: ["g", r.gen]
				}, r.gen))
			})
		]
	});
}
/** 并行组：虚线框 + 纵排双道（几道都行，mock ④「任意形状」）。 */
function LaneMapGroup({ model, groupId }) {
	const g = model.groups[groupId];
	if (!g) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
		className: "wb-lm-parallel",
		"data-group": g.def.id,
		"data-active": g.active ? "true" : "false",
		"data-done": g.allDone ? "true" : "false",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
			className: "wb-lm-plabel",
			children: [
				"Parallel · ",
				g.members.length,
				" lanes"
			]
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-lm-branches",
			children: g.members.map((m) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)(LaneMapNode, {
				nv: m,
				inGroup: true
			}, m.node.id))
		})]
	});
}
/**
* 真泳道图。model=null 时调用方不渲染本组件（回落现行线性步骤条）。
*/
function LaneMap({ model }) {
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-lanemap",
		"data-template": model.topology.template,
		children: model.items.map((item) => item.kind === "group" ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-lm-item",
			children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(LaneMapGroup, {
				model,
				groupId: item.id
			})
		}, item.id) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-lm-item",
			children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(LaneMapNode, {
				nv: model.nodes[item.id],
				inGroup: false
			})
		}, item.id))
	});
}
/**
* 检查明细区（mock ① ck-rows）：gate_runs 逐轮逐条 ✓/✗ + item + detail，
* 原始输出 details 折叠可展开；红行带文件点名与下一步（与状态卡同一
* blocked_detail/gate_runs 数据源，天然联动）。最新一轮在最上，最多显 3 轮。
*/
function ChecksDetail({ runs, cap = 3 }) {
	if (!runs || runs.length === 0) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-checks",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-checks-ttl",
			children: [
				"Check details · ",
				runs.length,
				" gate runs (engine structured data verbatim; click a row for raw output)"
			]
		}), runs.slice(0, cap).map((run, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-ck-run",
			"data-stage": run.stage,
			"data-green": run.green ? "true" : "false",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-ck-run-head",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: run.label }),
					run.gen !== void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-ck-run-gen",
						children: ["Round ", run.gen]
					}) : null,
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ck-run-verdict",
						children: run.green ? "all green" : `${run.redCount} red`
					})
				]
			}), run.rows.map((row, j) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
				className: "wb-ck-row",
				"data-green": row.green ? "true" : "false",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("summary", { children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", {
						className: `wb-ck-mark ${row.green ? "g" : "r"}`,
						children: row.green ? "✓" : "✗"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ck-name",
						children: row.item || row.checkId || "(unnamed check)"
					}),
					row.detail ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ck-detail",
						children: row.detail
					}) : null
				] }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ck-more",
					children: [
						row.checkId ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: ["check_id: ", row.checkId] }) : null,
						row.reasonCode ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: ["reason_code: ", row.reasonCode] }) : null,
						row.files && row.files.length > 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: ["Files: ", row.files.join(", ")] }) : null,
						row.nextAction ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: ["Next: ", row.nextAction] }) : null,
						row.detail ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", { children: row.detail }) : null
					]
				})]
			}, j))]
		}, `${run.stage}-${i}`))]
	});
}
//#endregion
//#region src/client/inspection-report-model.ts
/**
* inspection-report-model —— 巡检票详情「报告面」纯函数层（t260926-05）。
*
* 零 react / 平台依赖，node 可裸 import 黑盒单测
* （tests/t260926-05-inspection-report-model.mjs）——形态借 ticket-list-model.ts
* （纯函数层先例），故障模式取舍见票 t260926-05 方案 rev2。
*
* 渲染契约（工单验收②）：任何深嵌/未知形状的值都经 asText 走安全文本路径——
* 绝不产出 `[object Object]`、绝不把对象直接喂给 React child；畸形形状走防御
* 回退行，页面不炸。所有 label 英文（260904 宿主令：英文界面 + 数据不译）。
*
* 宿主半（src/host/inspection-report.ts）复用 reportDigest 生成报告 JSON
* 的可读摘要——同源渲染契约：端点摘要与浏览器兜底渲染走同一函数，不各写一套。
*/
/** 对象/数组 → 可读文本（260926 宿主报「report UI 都是 [object Object]」）：
*  字符串原样（超长截断）、数字/布尔 String()、其余走紧凑 JSON（超长截断），
*  **绝不产出 `[object Object]`**；null/undefined → 空串（调用方据此决定是否渲染该行）。 */
function asText(v, limit = 400) {
	if (v === null || v === void 0) return "";
	if (typeof v === "string") return v.length > limit ? v.slice(0, limit) + "…" : v;
	if (typeof v === "number" || typeof v === "boolean") return String(v);
	try {
		const s = JSON.stringify(v);
		if (!s) return "";
		return s.length > limit ? s.slice(0, limit) + "…" : s;
	} catch {
		return `(unserializable ${Array.isArray(v) ? "array" : typeof v === "object" ? "object" : typeof v}, truncated)`;
	}
}
/** 单元格值取行值：键存在且 asText 非空才给行（缺键=老载荷形态，不造假行）。 */
function rowOf(obj, key, label, limit = 400) {
	if (!(key in obj)) return null;
	const value = asText(obj[key], limit);
	if (value === "") return null;
	return {
		label,
		value
	};
}
/** face["suite"]（engine inspection_deadman.suite_section 形状）→ 有标签行 +
*  逐场景红绿 + blockers。畸形（非 dict）→ 单行安全文本，不炸不漏。 */
function suiteSectionView(suite) {
	if (suite === null || suite === void 0) return {
		rows: [],
		cases: [],
		blockers: []
	};
	if (typeof suite !== "object" || Array.isArray(suite)) return {
		rows: [{
			label: "Suite",
			value: asText(suite, 2e3)
		}],
		cases: [],
		blockers: []
	};
	const s = suite;
	const rows = [];
	const cnt = (k) => k in s ? asText(s[k], 40) : "—";
	rows.push({
		label: "Suite ok",
		value: s.ok === void 0 ? "—" : s.ok ? "yes" : "no",
		warn: s.ok === false
	});
	if (typeof s.error === "string" && s.error.trim() !== "") rows.push({
		label: "Suite error",
		value: s.error,
		warn: true
	});
	rows.push({
		label: "Ran",
		value: cnt("ran")
	});
	rows.push({
		label: "Passed",
		value: cnt("passed")
	});
	rows.push({
		label: "Failed",
		value: cnt("failed"),
		warn: Number(s.failed) > 0
	});
	rows.push({
		label: "Env fail",
		value: cnt("env_fail"),
		warn: Number(s.env_fail) > 0
	});
	for (const [key, label] of [
		["wall_seconds", "Wall clock total (wall_seconds)"],
		["supply_used_sec", "Supply phase wall clock (supply_used_sec)"],
		["runner_used_sec", "Runner phase wall clock (runner_used_sec)"],
		["run_budget_sec", "Runner budget (run_budget_sec)"],
		["supply_timeout_sec", "Supply timeout (supply_timeout_sec)"],
		["suite_timeout_sec", "Suite timeout budget (suite_timeout_sec)"]
	]) {
		const r = rowOf(s, key, label);
		if (r) rows.push(r);
	}
	if (s.suite_timeout) rows.push({
		label: "Suite timeout",
		value: `YES — budget exhausted${s.suite_timeout_sec !== void 0 ? ` (${asText(s.suite_timeout_sec, 40)}s)` : ""}`,
		warn: true
	});
	if (s.late) rows.push({
		label: "Late receipt",
		value: `YES — orphan receipt written after activity timeout${typeof s.late_error === "string" && s.late_error ? `: ${s.late_error}` : ""}`,
		warn: true
	});
	for (const [key, label] of [
		["worktree", "Worktree"],
		["base_ref", "Base ref"],
		["report_path", "Full suite receipt"]
	]) {
		const r = rowOf(s, key, label, 2e3);
		if (r) rows.push(r);
	}
	return {
		rows,
		cases: (Array.isArray(s.cases) ? s.cases : []).map((c) => {
			if (c === null || typeof c !== "object" || Array.isArray(c)) return {
				name: asText(c, 200),
				exit: ""
			};
			const cc = c;
			return {
				name: asText(cc.name, 200),
				exit: asText(cc.exit, 20)
			};
		}),
		blockers: Array.isArray(s.blockers) ? s.blockers.map((b) => asText(b, 400)).filter((b) => b !== "") : []
	};
}
/** 有专属渲染块（或有专属展示位）的键：faceRows 不再重复出泛化行。 */
const FACE_DEDICATED = /* @__PURE__ */ new Set([
	"heartbeat_note",
	"budget_note",
	"scan_meta",
	"redirect",
	"id",
	"ticket_id",
	"kind",
	"instance_id",
	"period",
	"template",
	"gate_id",
	"title",
	"status",
	"decision",
	"stage",
	"stage_state",
	"project",
	"heartbeat",
	"summary",
	"findings",
	"suggested_fix_tickets",
	"red_line",
	"human_gate",
	"gate_error",
	"timeline",
	"report_path",
	"suite",
	"worktree",
	"base_ref",
	"session_kb",
	"agent_alive",
	"meta",
	"handoff",
	"paused",
	"engine",
	"exec_status",
	"close_health",
	"urgency",
	"source_inspection",
	"authz",
	"authz_active",
	"authorizations",
	"blocked_detail",
	"parallel_stages"
]);
/** curated 泛化行（有专属英文名的巡检报告面字段）。 */
const FACE_CURATED = [
	["heartbeat_note", "Heartbeat note"],
	["budget_note", "Budget note"],
	["scan_meta", "Scan meta"],
	["redirect", "Redirect"]
];
/** 详情 face → 有标签行：curated 四键在前，其余未知键逐键 asText 兜底
*  （引擎未来加键=自动可读，绝不裸对象）。畸形 detail → 空表（不炸）。 */
function faceRows(detail) {
	if (detail === null || detail === void 0 || typeof detail !== "object" || Array.isArray(detail)) return [];
	const d = detail;
	const rows = [];
	for (const [key, label] of FACE_CURATED) {
		const r = rowOf(d, key, label, 2e3);
		if (r) rows.push(r);
	}
	for (const key of Object.keys(d)) {
		if (FACE_DEDICATED.has(key)) continue;
		const r = rowOf(d, key, key, 2e3);
		if (r) rows.push(r);
	}
	return rows;
}
/** 任意 JSON 值 → 缩进式可读摘要行（全部经 asText；环引用/超深/超行数都有界）。
*  maxLines 封顶防巨报告刷爆 DOM——截断行显式点名，不静默。 */
function reportDigest(v, maxLines = 2e3) {
	const lines = [];
	const seen = /* @__PURE__ */ new Set();
	const walk = (node, depth, label) => {
		if (lines.length >= maxLines) return;
		const push = (text) => {
			if (lines.length < maxLines) lines.push({
				depth,
				text
			});
		};
		if (node !== null && typeof node === "object") {
			if (seen.has(node)) {
				push(`${label}: (circular reference — omitted)`);
				return;
			}
			seen.add(node);
			if (lines.length + 1 >= maxLines) {
				push(`${label}: …(digest truncated at ${maxLines} lines)`);
				return;
			}
			if (Array.isArray(node)) {
				push(`${label}: ${node.length} entries`);
				node.forEach((item, i) => walk(item, depth + 1, `[${i}]`));
			} else {
				const keys = Object.keys(node);
				push(`${label}: {${keys.length} keys}`);
				for (const k of keys) walk(node[k], depth + 1, k);
			}
			seen.delete(node);
		} else {
			const text = asText(node, 2e3);
			push(text === "" ? `${label}: (empty)` : `${label}: ${text}`);
		}
	};
	if (v !== null && typeof v === "object" && !Array.isArray(v)) {
		const keys = Object.keys(v);
		if (keys.length === 0) return [{
			depth: 0,
			text: "report: (empty object)"
		}];
		for (const k of keys) walk(v[k], 0, k);
	} else if (Array.isArray(v)) walk(v, 0, "report");
	else {
		const text = asText(v, 2e3);
		return [{
			depth: 0,
			text: text === "" ? "report: (empty)" : `report: ${text}`
		}];
	}
	if (lines.length >= maxLines) lines.push({
		depth: 0,
		text: `…(digest truncated at ${maxLines} lines)`
	});
	return lines;
}
/** 单条发现项的安全视图（t260926-05 验收②③）：任何形状都有可读出路——
*  非对象发现项 → fallback 一行；对象字段全走 asText；evidence 非数组 →
*  evidenceFallback；证据条目非对象 → loc=asText 整条。 */
function findingView(f, i) {
	const empty = {
		sev: "",
		scan: "",
		confidence: "",
		verified: "",
		subject: "",
		why: "",
		suggestion: "",
		evidence: []
	};
	if (f === null || f === void 0) return {
		...empty,
		fallback: `Finding ${i}: (empty entry)`
	};
	if (typeof f !== "object" || Array.isArray(f)) return {
		...empty,
		fallback: `Finding ${i}: ${asText(f, 2e3)}`
	};
	const o = f;
	const evidence = [];
	let evidenceFallback;
	if (Array.isArray(o.evidence)) for (const e of o.evidence) if (e !== null && typeof e === "object" && !Array.isArray(e)) {
		const ee = e;
		const path = asText(ee.path, 300);
		const line = typeof ee.line === "number" ? `:${ee.line}` : "";
		evidence.push({
			loc: `${path}${line}`,
			quote: asText(ee.quote, 200)
		});
	} else evidence.push({
		loc: asText(e, 300),
		quote: ""
	});
	else if (o.evidence !== void 0 && o.evidence !== null) evidenceFallback = asText(o.evidence, 2e3);
	return {
		fallback: void 0,
		sev: asText(o.severity, 40),
		scan: asText(o.scan, 200),
		confidence: typeof o.confidence === "number" ? String(o.confidence) : asText(o.confidence, 40),
		verified: asText(o.verified, 200),
		subject: asText(o.subject, 400),
		why: asText(o.why, 2e3),
		suggestion: asText(o.suggestion, 2e3),
		evidence,
		evidenceFallback
	};
}
//#endregion
//#region ../providers/src/host/routes-edit.ts
/** 视图 → 编辑草稿（null 条目 → 空串，UI 显示为「继承 default」）。 */
function draftFromView(view) {
	const dft = view.default ?? {
		provider: "",
		model: ""
	};
	const roles = {};
	for (const role of view.roles) {
		const e = role.entry ?? {
			provider: "",
			model: ""
		};
		const tasks = {};
		for (const t of role.tasks) {
			const te = t.entry ?? {
				provider: "",
				model: ""
			};
			tasks[t.kind] = {
				provider: te.provider ?? "",
				model: te.model ?? ""
			};
		}
		roles[role.role] = {
			provider: e.provider ?? "",
			model: e.model ?? "",
			tasks
		};
	}
	return {
		default: {
			provider: dft.provider ?? "",
			model: dft.model ?? ""
		},
		roles
	};
}
/** 草稿 → 保存载荷：所有字段显式携带（含 ''=清空键），宿主 diff 后只改有变化的行。 */
function draftToPayload(d) {
	const payload = {
		default: {
			provider: d.default.provider,
			model: d.default.model
		},
		roles: {}
	};
	for (const [rid, r] of Object.entries(d.roles)) {
		const role = {
			provider: r.provider,
			model: r.model
		};
		const tasks = {};
		for (const [kind, t] of Object.entries(r.tasks)) tasks[kind] = {
			provider: t.provider,
			model: t.model
		};
		role.tasks = tasks;
		payload.roles[rid] = role;
	}
	return payload;
}
//#endregion
//#region ../providers/src/client/index.tsx
/**
* sandbar-providers —— LLM provider 管理与优先级 · 浏览器半。
*
* 槽位契约沿革：本插件曾向会话视图环注册「模型」页签 + `conversationViews.register`
* （t260821-11 ①，260823 前）；260823 起「模型」UI 移到工单台侧栏中栏、由
* sandbar-workbench 直接 import 本插件的 ProvidersSection 渲染，apply 改为
* 空操作——插件对 conversationViews/uiConversation 零消费、零注册。
*
* 功能（t260821-08 B 版 + t260821-11 ②③ + M13 路由表）：
*   ① 列出 provider（deepseek-official/kimi-coding/zai/scnet…）+ 上下移/拖拽排序；
*   ② 每个 provider 计费档说明可编辑；
*   ③ 「设为当前」一键写 agent-default-model（provider+model，可带 reasoningEffort）；
*   ④ 「添加 provider」表单（baseURL/协议/模型 id 列表/key 环境变量 + **key 直填**）：
*      key 直填走宿主半 credentials seam 写 $DSH_HOME/.credentials.yaml，settings.yaml
*      仍只落 apiKeyEnv 引用，写 settings 仍走 assertServiceable dry-run 校验；
*   ⑤ scnet 预置一键填表并**预填 14 个模型 id**（glm/minimax/kimi/qwen/deepseek 系）；
*   ⑥ 「路由表」分区（M13，t260822-m13-model-routes-edit）：展示 model-routes.yaml
*      真源路由表（default/五角色/分工 tasks）+ provider 下拉/模型下拉编辑（换 provider
*      即刷新该家已注册模型清单，260828）+
*      保存（POST /sandbar-admin/api/routes/save，宿主在 sandbar-admin-ui 插件，写前备份
*      /tmp；保存即生效——运行时查表，下一个工单 agent spawn 用新表）。
* 所有写操作走宿主半（../node.ts）挂在 dsh webServer 上的 /sandbar-providers/api/*；
* 路由表读写走 sandbar-admin-ui 的 /sandbar-admin/api/routes（同源，M13① 保留的 API）。
*
* 【inject 收窄史（t260916-26）】曾声明 `inject = ['slots','conversationViews']`；
* dsh 0.1.5 起 conversationViews 服务随 dsh-client-runtime 整包移除，声明即
* 永久 pending（UI 报 Failed to load plugins）。现改从 ./inject-contract 导入
* CLIENT_INJECT（=['slots']，双版本稳定白名单），同一 bundle 在 0.1.1/0.1.5
* 都能激活；本插件无页签注册行为（apply 空操作），收窄零行为差异。
*/
const CSS$3 = `
.syp-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:#f6f8fa;color:#1f2328;min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:16px;font-size:13px;line-height:1.55}
.syp-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid #d0d7de;padding-bottom:12px}
.syp-title{font-size:20px;font-weight:600;color:#1f2328}
.syp-sub{font-size:12px;color:#57606a}
.syp-banner{display:flex;align-items:center;gap:10px;border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:10px 14px;flex-wrap:wrap}
.syp-banner-k{color:#57606a}
.syp-banner-v{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-err{background:#ffebe9;border:1px solid #ff9b9b;color:#cf222e;border-radius:6px;padding:8px 12px;font-size:12px;white-space:pre-wrap}
.syp-ok{background:#dafbe1;border:1px solid #7dd9a0;color:#116329;border-radius:6px;padding:8px 12px;font-size:12px}
.syp-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.syp-btn{font:inherit;font-size:12px;padding:4px 12px;border-radius:6px;cursor:pointer;border:1px solid #d0d7de;background:#fff;color:#1f2328;transition:background .12s}
.syp-btn:hover{background:#f6f8fa}
.syp-btn:disabled{opacity:.45;cursor:default}
.syp-btn-primary{border-color:#0969da;background:#0969da;color:#fff;font-weight:600}
.syp-btn-primary:hover{background:#0857b6}
.syp-btn-danger{border-color:#ff9b9b;color:#cf222e;background:#ffebe9}
.syp-btn-green{border-color:#7dd9a0;color:#1a7f37;background:#dafbe1}
.syp-icon-btn{font:inherit;font-size:13px;padding:2px 8px;border-radius:6px;cursor:pointer;border:1px solid #d0d7de;background:#fff;color:#57606a}
.syp-icon-btn:hover{background:#f6f8fa}
.syp-icon-btn:disabled{opacity:.35;cursor:default}
.syp-list{display:flex;flex-direction:column;gap:8px}
.syp-row{display:flex;align-items:flex-start;gap:10px;border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:10px 12px;transition:box-shadow .12s}
.syp-row[data-current=true]{border-color:#0969da;box-shadow:inset 3px 0 0 #0969da;background:#f0f6ff}
.syp-row[data-drag=true]{opacity:.5;border-style:dashed}
.syp-row-grip{cursor:grab;color:#8c959f;user-select:none;font-size:16px;line-height:1;padding:4px 2px}
.syp-row-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}
.syp-row-line1{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.syp-row-name{font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:500}
.syp-badge[data-kind=external]{background:#fff8c5;color:#7d4e00}
.syp-badge[data-kind=pi-ai]{background:#dafbe1;color:#116329}
.syp-badge[data-kind=preset]{background:#ddf4ff;color:#0550ae}
.syp-badge[data-cur=true]{background:#0969da;color:#fff}
.syp-row-line2{display:flex;gap:8px 16px;flex-wrap:wrap;font-size:11px;color:#57606a}
.syp-kv{display:inline-flex;gap:4px}
.syp-kv b{color:#8c959f;font-weight:500}
.syp-row-line3{display:flex;align-items:center;gap:8px}
.syp-note-label{font-size:11px;color:#8c959f;white-space:nowrap}
.syp-note-input{font:inherit;font-size:12px;flex:1;border:1px solid #d0d7de;border-radius:6px;padding:4px 8px;color:#1f2328;background:#fff}
.syp-note-input:focus{outline:none;border-color:#0969da}
.syp-row-ops{display:flex;flex-direction:column;gap:6px;align-items:flex-end;flex:none}
.syp-row-ops .syp-btn{white-space:nowrap}
.syp-form{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.syp-form-title{font-size:14px;font-weight:600;color:#1f2328}
.syp-field{display:flex;flex-direction:column;gap:4px}
.syp-field label{font-size:12px;color:#57606a}
.syp-field input,.syp-field select,.syp-field textarea{font:inherit;font-size:12px;border:1px solid #d0d7de;border-radius:6px;padding:6px 10px;color:#1f2328;background:#fff}
.syp-field input:focus,.syp-field select:focus,.syp-field textarea:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.syp-field textarea{min-height:72px;resize:vertical;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-hint{font-size:11px;color:#8c959f}
.syp-modal{position:fixed;inset:0;background:rgba(31,35,40,.5);z-index:99;display:flex;align-items:center;justify-content:center;padding:24px}
.syp-modal-box{background:#fff;border:1px solid #d0d7de;border-radius:10px;box-shadow:0 8px 32px rgba(31,35,40,.2);max-width:520px;width:100%;display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.syp-modal-title{font-size:15px;font-weight:600;color:#1f2328}
.syp-empty{font-size:12px;color:#57606a;padding:12px 0}
/* ── M13 路由表（syp-route-*）── */
.syp-route-card{border:1px solid #d0d7de;border-radius:8px;background:#fff;padding:14px 16px;
  display:flex;flex-direction:column;gap:10px}
.syp-route-title{font-size:14px;font-weight:600;color:#1f2328;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.syp-route-note{font-size:11px;color:#57606a;line-height:1.7}
.syp-route-redline{font-size:11px;color:#7d4e00;background:#fff8c5;border:1px solid #d4a72c;
  border-radius:6px;padding:6px 10px;line-height:1.7}
.syp-route-gen{font-size:12px;color:#116329;background:#dafbe1;border:1px solid #7dd9a0;
  border-radius:6px;padding:8px 12px;line-height:1.7;white-space:pre-wrap}
.syp-route-tbl{border:1px solid #eaeef2;border-radius:6px;overflow:hidden}
.syp-route-row{display:grid;grid-template-columns:170px minmax(140px,1fr) minmax(140px,1fr) auto;
  gap:8px;align-items:center;padding:6px 10px;border-bottom:1px solid #eaeef2}
.syp-route-row:last-child{border-bottom:none}
.syp-route-row[data-head=true]{background:#f6f8fa;font-size:11px;color:#8c959f;padding-top:5px;padding-bottom:5px}
.syp-route-row[data-task=true]{padding-left:26px;background:#fbfcfe}
.syp-route-label{font-size:12px;font-weight:600;color:#1f2328;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.syp-route-kind{font-size:11px;font-weight:400;color:#8c959f}
.syp-route-cell{display:flex;flex-direction:column;gap:2px;min-width:0}
.syp-route-cell select,.syp-route-cell input{font:inherit;font-size:12px;border:1px solid #d0d7de;
  border-radius:6px;padding:4px 8px;color:#1f2328;background:#fff;width:100%;box-sizing:border-box}
.syp-route-cell select:focus,.syp-route-cell input:focus{outline:none;border-color:#0969da;box-shadow:0 0 0 3px rgba(9,105,218,.12)}
.syp-route-cell-hint{font-size:10px;color:#8c959f}
.syp-route-cell-warn{font-size:10px;color:#b45309;display:block}
.syp-route-eff{font-size:11px;color:#57606a;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.syp-route-via{font-size:10px;color:#8c959f;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.syp-route-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.syp-route-warn{font-size:11px;color:#9a6700;background:#fff8c5;border-radius:6px;padding:6px 10px;
  margin:0;white-space:pre-wrap;line-height:1.6}
`;
const CSS_TAG_ID$1 = "sandbar-providers/ProvidersSection.css";
if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(CSS_TAG_ID$1) + "]") === null) {
	const tag = document.createElement("style");
	tag.dataset.plugin = "sandbar-providers";
	tag.dataset.pluginCss = CSS_TAG_ID$1;
	tag.textContent = CSS$3;
	document.head.appendChild(tag);
}
const API$1 = "/sandbar-providers/api";
/** 多项目化（260823）：路由表两条 URL（/sandbar-admin/api/routes*，按项目主目录解析
*  model-routes.yaml）统一拼 ?project=；provider 管理（/sandbar-providers/api/*）是
*  dsh 全局设施，不分流。
*  260826 修：project 从模块级持有量改为纯函数入参——旧写法靠 ProvidersSection 的
*  effect 落值，但 React 挂载时子组件 effect 先于父组件执行，RoutesTableSection
*  首次 load 永远拿到空 project → 宿主 400「缺 project 参数」。prop 渲染期即有值，
*  不依赖 effect 顺序。 */
function routesUrl(path, projectKey) {
	if (!projectKey) return path;
	return path + (path.includes("?") ? "&" : "?") + "project=" + encodeURIComponent(projectKey);
}
async function apiGet$1(path) {
	return (await fetch(path)).json();
}
async function apiPost$1(path, body) {
	return (await fetch(path, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(body ?? {})
	})).json();
}
const KIND_LABEL$1 = {
	"pi-ai": "llm-pi-ai 路由",
	external: "官方 deepseek 适配器",
	preset: "预置（未添加）"
};
/** 「手填…」select 选项哨兵值：与真实模型 id 冲突面极小（模型 id 不会长这样）。 */
const HAND_OPT = "__hand__";
/**
* 模型 id 单元。provider 有已注册清单 → 渲染真 <select>（整单随 provider 刷新）；
* 清单为空或选了「手填…」→ 自由输入 + datalist 兜底（catalog 滞后的新模型仍可手输）。
*
* 为什么不用 datalist 当主下拉：datalist 的候选会被输入框现值过滤（框里留着上一家的
* 模型 id 时，下拉看起来永远是空的/旧的），WebKit 还常不随重渲染刷新候选——260828
* 反馈「选了 provider 模型列表不刷新」的根因。真 select 没有这两毛病。
* 调用方用 key={provider id} 挂载：换 provider 即重挂，手填态自动退回下拉。
*/
function ModelIdCell({ pid, models, value, onChange, listId }) {
	const [hand, setHand] = (0, react.useState)(false);
	if (hand || models.length === 0) return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
		/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
			value,
			list: models.length > 0 ? listId : void 0,
			placeholder: "模型 id（手填）",
			onChange: (e) => onChange(e.target.value)
		}),
		models.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("datalist", {
			id: listId,
			children: models.map((m) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", { value: m }, m))
		}),
		models.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("button", {
			type: "button",
			className: "syp-btn",
			onClick: () => setHand(false),
			children: [
				"回 ",
				pid,
				" 清单下拉"
			]
		})
	] });
	const known = models.includes(value);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
		value: known ? value : HAND_OPT,
		onChange: (e) => {
			if (e.target.value === HAND_OPT) {
				setHand(true);
				return;
			}
			onChange(e.target.value);
		},
		children: [
			!known && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
				value,
				children: value === "" ? "（未设）" : `${value}（未注册）`
			}),
			models.map((m) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
				value: m,
				children: m
			}, m)),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
				value: HAND_OPT,
				children: "（手填…）"
			})
		]
	});
}
function ProvidersSection({ projectKey }) {
	const [data, setData] = (0, react.useState)(void 0);
	const [error, setError] = (0, react.useState)("");
	const [busy, setBusy] = (0, react.useState)(false);
	const [msg, setMsg] = (0, react.useState)("");
	const [showForm, setShowForm] = (0, react.useState)(false);
	const [dragId, setDragId] = (0, react.useState)(null);
	const [noteDraft, setNoteDraft] = (0, react.useState)({});
	const [fId, setFId] = (0, react.useState)("");
	const [fDisplay, setFDisplay] = (0, react.useState)("");
	const [fApi, setFApi] = (0, react.useState)("openai-completions");
	const [fBase, setFBase] = (0, react.useState)("");
	const [fKeyEnv, setFKeyEnv] = (0, react.useState)("");
	const [fApiKey, setFApiKey] = (0, react.useState)("");
	const [fModels, setFModels] = (0, react.useState)("");
	const [fNote, setFNote] = (0, react.useState)("");
	const [curId, setCurId] = (0, react.useState)(null);
	const [curModel, setCurModel] = (0, react.useState)("");
	const [curRe, setCurRe] = (0, react.useState)("");
	async function reload() {
		try {
			const d = await apiGet$1(`${API$1}/state`);
			if (d?.ok !== true) throw new Error(d?.error ?? "加载失败");
			setData(d.result);
			setError("");
		} catch (err) {
			setError(String(err instanceof Error ? err.message : err));
		}
	}
	(0, react.useEffect)(() => {
		reload();
	}, []);
	async function post(path, body, okMsg) {
		setBusy(true);
		setMsg("");
		try {
			const r = await apiPost$1(path, body);
			if (r?.ok !== true) {
				setMsg(`失败：${r?.error ?? "未知错误"}`);
				return false;
			}
			setMsg(okMsg);
			await reload();
			return true;
		} catch (err) {
			setMsg(`请求失败：${String(err instanceof Error ? err.message : err)}`);
			return false;
		} finally {
			setBusy(false);
		}
	}
	function fillScnet() {
		const p = data?.scnetPreset;
		if (!p) return;
		setFId(p.id);
		setFDisplay(p.displayName);
		setFApi(p.api);
		setFBase(p.baseURL);
		setFKeyEnv(p.apiKeyEnv);
		setFApiKey("");
		setFModels(Array.isArray(p.models) ? p.models.join("\n") : "");
		setFNote("");
	}
	async function submitAdd() {
		const models = fModels.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
		if (await post(`${API$1}/add-provider`, {
			id: fId,
			displayName: fDisplay,
			api: fApi,
			baseURL: fBase,
			apiKeyEnv: fKeyEnv,
			apiKey: fApiKey,
			models,
			note: fNote
		}, `已添加 provider「${fId.trim()}」到 llm-pi-ai.providers${fApiKey.trim() !== "" ? `，key 已存入 ${fKeyEnv.trim()}` : ""}`)) {
			setShowForm(false);
			setFId("");
			setFDisplay("");
			setFApi("openai-completions");
			setFBase("");
			setFKeyEnv("");
			setFApiKey("");
			setFModels("");
			setFNote("");
		}
	}
	function openSetCurrent(p) {
		setCurId(p.id);
		setCurModel(p.isCurrent ? p.currentModel : p.models[0] ?? "");
		setCurRe(p.isCurrent ? data?.current.reasoningEffort ?? "" : "");
	}
	async function submitSetCurrent() {
		if (!curId) return;
		if (await post(`${API$1}/set-current`, {
			provider: curId,
			model: curModel,
			reasoningEffort: curRe
		}, `已把 agent-default-model 切到 ${curId} / ${curModel.trim()}`)) setCurId(null);
	}
	async function saveNote(p) {
		const note = noteDraft[p.id] ?? p.note;
		await post(`${API$1}/update-note`, {
			id: p.id,
			note
		}, `已保存「${p.id}」计费说明`);
	}
	async function reorder(order) {
		setBusy(true);
		setMsg("");
		try {
			const r = await apiPost$1(`${API$1}/reorder`, { order });
			if (r?.ok !== true) {
				setMsg(`失败：${r?.error ?? "未知错误"}`);
				return;
			}
			setMsg("优先级已保存");
			await reload();
		} catch (err) {
			setMsg(`请求失败：${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setBusy(false);
		}
	}
	function move(id, delta) {
		const list = data?.providers.map((p) => p.id) ?? [];
		const i = list.indexOf(id);
		const j = i + delta;
		if (i < 0 || j < 0 || j >= list.length) return;
		const next = [...list];
		const tmp = next[i];
		next[i] = next[j];
		next[j] = tmp;
		reorder(next);
	}
	function onDrop(id) {
		const list = data?.providers.map((p) => p.id) ?? [];
		const from = dragId;
		const to = id;
		setDragId(null);
		if (!from || from === to) return;
		const next = list.filter((x) => x !== from);
		const idx = next.indexOf(to);
		next.splice(idx, 0, from);
		reorder(next);
	}
	const rows = data?.providers ?? [];
	const modelListForCurrent = (0, react.useMemo)(() => curId ? rows.find((p) => p.id === curId)?.models ?? [] : [], [curId, rows]);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "syp-root",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-head",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "syp-title",
					children: "模 型"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					className: "syp-sub",
					children: ["LLM provider 管理与优先级（手动排序 + 一键切换）· 写 ", data?.settingsPath ?? "settings.yaml"]
				})]
			}),
			data && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-banner",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "syp-banner-k",
						children: "当前 agent-default-model："
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "syp-banner-v",
						children: [
							data.current.provider,
							" / ",
							data.current.model
						]
					}),
					data.current.reasoningEffort && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "syp-badge",
						"data-cur": true,
						children: data.current.reasoningEffort
					})
				]
			}),
			error !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-err",
				children: [
					error,
					"\n",
					"（模型管理 API 未挂载？headless profile 无 webServer。）"
				]
			}),
			msg !== "" && (msg.startsWith("失败") || msg.startsWith("请求失败") ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "syp-err",
				children: msg
			}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "syp-ok",
				children: msg
			})),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-actions",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					className: "syp-btn",
					disabled: busy,
					onClick: () => {
						reload();
					},
					children: "刷 新"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					className: "syp-btn syp-btn-primary",
					onClick: () => setShowForm((v) => !v),
					children: showForm ? "收起添加表单" : "+ 添加 provider"
				})]
			}),
			showForm && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-form",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "syp-form-title",
						children: "添加 provider（写 settings.yaml 的 llm-pi-ai.providers；坏 provider 会被 dry-run 拒绝，绝不落盘）"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-actions",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "syp-btn",
							onClick: fillScnet,
							title: data?.scnetPreset?.description,
							children: "scnet 预置一键填表"
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "syp-hint",
							children: data?.scnetPreset?.description ?? ""
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "provider id（route key，如 scnet / my-gateway）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							value: fId,
							onChange: (e) => setFId(e.target.value),
							placeholder: "scnet"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "显示名（可选）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							value: fDisplay,
							onChange: (e) => setFDisplay(e.target.value),
							placeholder: "SCNet"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "协议 api" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("select", {
							value: fApi,
							onChange: (e) => setFApi(e.target.value),
							children: (data?.protocols ?? [
								"openai-completions",
								"openai-responses",
								"anthropic-messages"
							]).map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
								value: p,
								children: p
							}, p))
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "baseURL" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							value: fBase,
							onChange: (e) => setFBase(e.target.value),
							placeholder: "https://api.scnet.cn/api/llm/v1"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "key 环境变量 apiKeyEnv（key 直填时即存入该名下）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							value: fKeyEnv,
							onChange: (e) => setFKeyEnv(e.target.value),
							placeholder: "SCNET_API_KEY"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "API key 直填（可选；留空则只登记 apiKeyEnv，不写任何 key）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							type: "password",
							value: fApiKey,
							onChange: (e) => setFApiKey(e.target.value),
							autoComplete: "off",
							placeholder: "sk-…（存入 $DSH_HOME/.credentials.yaml，0600）"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "模型 id 列表（每行一个；scnet 预置会预填 14 个模型 id，可增删）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
							value: fModels,
							onChange: (e) => setFModels(e.target.value),
							placeholder: "GLM-5.2\nGLM-5\n…"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "计费档说明（可选）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							value: fNote,
							onChange: (e) => setFNote(e.target.value),
							placeholder: "如：¥0.001/1K tokens"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "syp-actions",
						children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "syp-btn syp-btn-green",
							disabled: busy,
							onClick: () => {
								submitAdd();
							},
							children: "添 加"
						})
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-list",
				children: [rows.map((p, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "syp-row",
					"data-current": p.isCurrent,
					"data-drag": dragId === p.id,
					draggable: !busy,
					onDragStart: () => setDragId(p.id),
					onDragOver: (e) => e.preventDefault(),
					onDrop: (e) => {
						e.preventDefault();
						onDrop(p.id);
					},
					onDragEnd: () => setDragId(null),
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "syp-row-grip",
							title: "拖拽排序",
							children: "⠿"
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "syp-row-main",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "syp-row-line1",
									children: [
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "syp-row-name",
											children: p.id
										}),
										p.displayName && p.displayName !== p.id && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "syp-sub",
											children: p.displayName
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "syp-badge",
											"data-kind": p.kind,
											children: KIND_LABEL$1[p.kind] ?? p.kind
										}),
										p.isCurrent && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "syp-badge",
											"data-cur": true,
											children: "当前"
										})
									]
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "syp-row-line2",
									children: [
										p.api && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "syp-kv",
											children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "协议" }), p.api]
										}),
										p.baseURL && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "syp-kv",
											children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "baseURL" }), p.baseURL]
										}),
										p.apiKeyEnv && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "syp-kv",
											children: [
												/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "key" }),
												p.apiKeyEnv,
												p.keySet === true ? "（已存）" : p.keySet === false ? "（未存）" : ""
											]
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "syp-kv",
											children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "模型" }), p.models.length > 0 ? `${p.models.length} 个` : "—"]
										}),
										p.description && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "syp-kv",
											children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "备注" }), p.description]
										})
									]
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "syp-row-line3",
									children: [
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "syp-note-label",
											children: "计费说明"
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
											className: "syp-note-input",
											value: noteDraft[p.id] ?? p.note,
											placeholder: "（可编辑，如计费档位/价格）",
											onChange: (e) => setNoteDraft((v) => ({
												...v,
												[p.id]: e.target.value
											}))
										}),
										/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
											className: "syp-btn",
											disabled: busy,
											onClick: () => {
												saveNote(p);
											},
											children: "保存说明"
										})
									]
								})
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "syp-row-ops",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "syp-actions",
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
										className: "syp-icon-btn",
										disabled: busy || i === 0,
										title: "上移",
										onClick: () => move(p.id, -1),
										children: "↑"
									}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
										className: "syp-icon-btn",
										disabled: busy || i === rows.length - 1,
										title: "下移",
										onClick: () => move(p.id, 1),
										children: "↓"
									})]
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "syp-btn syp-btn-primary",
									disabled: busy,
									onClick: () => openSetCurrent(p),
									children: "设为当前"
								}),
								p.kind === "preset" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "syp-btn syp-btn-green",
									disabled: busy,
									onClick: () => {
										fillScnet();
										setShowForm(true);
									},
									children: "添加"
								}),
								p.kind === "pi-ai" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "syp-btn syp-btn-danger",
									disabled: busy,
									onClick: () => {
										if (window.confirm(`删除 provider「${p.id}」（从 llm-pi-ai.providers 移除）？`)) post(`${API$1}/delete-provider`, { id: p.id }, `已删除「${p.id}」`);
									},
									children: "删除"
								})
							]
						})
					]
				}, p.id)), rows.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "syp-empty",
					children: "没有 provider（加载中或 API 未挂载）。"
				})]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)(RoutesTableSection, {
				providers: rows,
				projectKey
			}),
			curId !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "syp-modal",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "syp-modal-box",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "syp-modal-title",
							children: ["设为当前 — ", curId]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "syp-field",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", { children: [
								"模型 id（",
								modelListForCurrent.length > 0 ? `${modelListForCurrent.length} 个已注册模型下拉可选，新模型选「手填…」` : "手填模型 id",
								"）"
							] }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ModelIdCell, {
								pid: curId,
								models: modelListForCurrent,
								value: curModel,
								onChange: setCurModel,
								listId: "syp-model-list"
							}, curId)]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "syp-field",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "reasoningEffort（可选，留空则省略；仅当目标适配器支持时有效）" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
								value: curRe,
								onChange: (e) => setCurRe(e.target.value),
								placeholder: "low / medium / high"
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "syp-actions",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "syp-btn syp-btn-primary",
								disabled: busy || !curModel.trim(),
								onClick: () => {
									submitSetCurrent();
								},
								children: "确认切换"
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "syp-btn",
								disabled: busy,
								onClick: () => setCurId(null),
								children: "取 消"
							})]
						})
					]
				})
			})
		]
	});
}
/** 「路由表」分区：展示当前路由表（只读真源）+ 编辑 provider/model + 保存
*  （保存即生效——运行时查表，下一个工单 agent spawn 用新表）。providers 列表
*  （含模型 id）来自本插件 /state，供下拉用。 */
function RoutesTableSection({ providers, projectKey }) {
	const [view, setView] = (0, react.useState)(void 0);
	const [draft, setDraft] = (0, react.useState)(void 0);
	const [error, setError] = (0, react.useState)("");
	const [busy, setBusy] = (0, react.useState)(false);
	const [msg, setMsg] = (0, react.useState)("");
	const [saved, setSaved] = (0, react.useState)(false);
	async function load() {
		setError("");
		try {
			const data = await apiGet$1(routesUrl("/sandbar-admin/api/routes", projectKey ?? ""));
			if (data?.ok !== true) throw new Error(data?.error ?? "模型路由读取失败");
			const v = data.result;
			setView(v);
			setDraft(draftFromView(v));
			setSaved(false);
		} catch (err) {
			setError(String(err instanceof Error ? err.message : err));
		}
	}
	(0, react.useEffect)(() => {
		setView(void 0);
		setDraft(void 0);
		setError("");
		if (projectKey) load();
	}, [projectKey]);
	function setRoleField(rid, field, value) {
		setDraft((d) => d === void 0 ? d : {
			...d,
			roles: {
				...d.roles,
				[rid]: {
					...d.roles[rid],
					[field]: value
				}
			}
		});
	}
	function setTaskField(rid, kind, field, value) {
		setDraft((d) => d === void 0 ? d : {
			...d,
			roles: {
				...d.roles,
				[rid]: {
					...d.roles[rid],
					tasks: {
						...d.roles[rid].tasks,
						[kind]: {
							...d.roles[rid].tasks[kind],
							[field]: value
						}
					}
				}
			}
		});
	}
	async function save() {
		if (draft === void 0) return;
		if (!window.confirm("保存将改写项目声明 paths.model_routes 指向的路由表（真源；未声明时落仓内 server/model-routes.yaml，写前备份 /tmp）。\n保存即生效：路由表是运行时查表，下一个工单 agent spawn 时就按新表走，无需任何生成/重启步骤。\n确认保存路由表？")) return;
		setBusy(true);
		setMsg("");
		setSaved(false);
		try {
			const r = await apiPost$1(routesUrl("/sandbar-admin/api/routes/save", projectKey ?? ""), { table: draftToPayload(draft) });
			if (r?.ok !== true) {
				setMsg(`保存失败：${r?.error ?? "未知错误"}`);
				return;
			}
			const res = r.result ?? {};
			setMsg(res.changed?.length > 0 ? `已保存 ${res.changed.length} 处变更（${res.changed.join("、")}）到 ${res.routes_file}` : "路由表无变更（未写文件）");
			setSaved(true);
			await load();
		} catch (err) {
			setMsg(`请求失败：${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setBusy(false);
		}
	}
	if (!projectKey) return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "syp-route-card",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "syp-route-title",
			children: "路 由 表"
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "syp-sub",
			children: "从左侧项目行点 🔀 图标打开该项目的模型路由。"
		})]
	});
	if (error !== "") return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "syp-route-card",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "syp-route-title",
			children: "路 由 表"
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "syp-err",
			children: [
				error,
				"\n",
				"（/sandbar-admin/api/routes 返回错误——按上面文案排查：缺参/未知项目=调用问题；表缺失/解析失败=声明指向的路由表（或仓内兜底表）问题。）"
			]
		})]
	});
	if (view === void 0 || draft === void 0) return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "syp-route-card",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "syp-route-title",
			children: "路 由 表"
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "syp-empty",
			children: "加载路由表…"
		})]
	});
	const modelsOf = (pid) => providers.find((p) => p.id === pid)?.models ?? [];
	/** 换 provider 时对齐 model：切到「继承/不设」清空；原 model 不在新家清单 → 取新家
	*  首个已注册模型（都没有则清空）。避免留下「A 家 provider + B 家 model」的错配，也
	*  让模型下拉随 provider 切换即见新家清单。 */
	function snapModel(curModel, newPid) {
		if (newPid === "") return "";
		const ms = modelsOf(newPid);
		if (ms.includes(curModel)) return curModel;
		return ms[0] ?? "";
	}
	/** 未注册提示：值非空、该家有已知清单、值不在清单 → 提示（不硬拦——catalog 滞后的
	*  新模型仍需手输入口，但把「模型 ref 不许发明」红线摆到眼前，260826 zai/k3 教训）。 */
	const UnregHint = ({ pid, model }) => {
		const ms = modelsOf(pid);
		if (model === "" || ms.length === 0 || ms.includes(model)) return null;
		return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
			className: "syp-route-cell-warn",
			children: [
				"⚠ 不在 ",
				pid,
				" 已注册清单（",
				ms.length,
				" 个），保存前确认已实测"
			]
		});
	};
	const effOf = (eff) => eff !== null ? `${eff.provider}/${eff.model}` : "未设（继承 profile 默认）";
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "syp-route-card",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-route-title",
				children: ["路 由 表", /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					className: "syp-hint",
					children: [
						"真源 ",
						view.routes_file,
						" · 工单 agent 用哪个模型（运行时查表，下次 spawn 生效）"
					]
				})]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-route-redline",
				children: [
					"改表红线：保存直接改写声明指向的路由表（未声明时落仓内兜底表；写前备份 /tmp）；模型 ref 不许发明——只用下方 provider 下拉里实证存在的 provider 及其模型 id。保存后",
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("strong", { children: "下一个工单 agent 启动即生效" }),
					"，无需任何生成/重启步骤。"
				]
			}),
			view.warnings.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
				className: "syp-route-warn",
				children: view.warnings.join("\n")
			}),
			saved && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-route-gen",
				children: [
					"✅ 路由表已写入 ",
					view.routes_file,
					"。下一个工单 agent 启动即按新表路由（运行时查表，无需任何生成/重启步骤）。"
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-route-tbl",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-route-row",
						"data-head": true,
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: "条目" }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: "provider" }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: "model" }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: "当前查表结果" })
						]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-route-row",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-label",
								children: ["default ", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "syp-route-kind",
									children: "兜底"
								})]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "syp-route-cell",
								children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
									value: draft.default.provider,
									onChange: (e) => setDraft((d) => {
										if (d === void 0) return d;
										const provider = e.target.value;
										return {
											...d,
											default: {
												provider,
												model: snapModel(d.default.model, provider)
											}
										};
									}),
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
										value: "",
										children: "（不设 → 全部不烘焙）"
									}), providers.map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
										value: p.id,
										children: p.id
									}, p.id))]
								})
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-cell",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ModelIdCell, {
									pid: draft.default.provider || "（未设 provider）",
									models: modelsOf(draft.default.provider),
									value: draft.default.model,
									onChange: (v) => setDraft((d) => d === void 0 ? d : {
										...d,
										default: {
											...d.default,
											model: v
										}
									}),
									listId: "syp-ml-default"
								}, draft.default.provider), /* @__PURE__ */ (0, react_jsx_runtime.jsx)(UnregHint, {
									pid: draft.default.provider,
									model: draft.default.model
								})]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-cell",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "syp-route-eff",
									children: effOf(view.default)
								}), view.default !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "syp-route-via",
									children: ["via ", view.default.via]
								})]
							})
						]
					}),
					view.roles.map((role) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-route-row",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-label",
								children: [
									role.display,
									" ",
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "syp-route-kind",
										children: role.role
									})
								]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "syp-route-cell",
								children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
									value: draft.roles[role.role].provider,
									onChange: (e) => setDraft((d) => {
										if (d === void 0) return d;
										const provider = e.target.value;
										const r = d.roles[role.role];
										return {
											...d,
											roles: {
												...d.roles,
												[role.role]: {
													...r,
													provider,
													model: snapModel(r.model, provider)
												}
											}
										};
									}),
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
										value: "",
										children: "（继承 default）"
									}), providers.map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
										value: p.id,
										children: p.id
									}, p.id))]
								})
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-cell",
								children: [
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ModelIdCell, {
										pid: draft.roles[role.role].provider || "（未设 provider）",
										models: modelsOf(draft.roles[role.role].provider),
										value: draft.roles[role.role].model,
										onChange: (v) => setRoleField(role.role, "model", v),
										listId: `syp-ml-${role.role}`
									}, draft.roles[role.role].provider),
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)(UnregHint, {
										pid: draft.roles[role.role].provider,
										model: draft.roles[role.role].model
									}),
									modelsOf(draft.roles[role.role].provider).length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "syp-route-cell-hint",
										children: [
											"已注册 ",
											modelsOf(draft.roles[role.role].provider).length,
											" 个模型，下拉直选"
										]
									})
								]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-cell",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "syp-route-eff",
									children: effOf(role.effective)
								}), role.effective !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "syp-route-via",
									children: ["via ", role.effective.via]
								})]
							})
						]
					}), role.tasks.map((task) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "syp-route-row",
						"data-task": true,
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-label",
								children: [
									task.display,
									"分工 ",
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "syp-route-kind",
										children: task.kind
									})
								]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "syp-route-cell",
								children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
									value: draft.roles[role.role].tasks[task.kind].provider,
									onChange: (e) => setDraft((d) => {
										if (d === void 0) return d;
										const provider = e.target.value;
										const t = d.roles[role.role].tasks[task.kind];
										const tasks = {
											...d.roles[role.role].tasks,
											[task.kind]: {
												...t,
												provider,
												model: snapModel(t.model, provider)
											}
										};
										const r = d.roles[role.role];
										return {
											...d,
											roles: {
												...d.roles,
												[role.role]: {
													...r,
													tasks
												}
											}
										};
									}),
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
										value: "",
										children: "（继承 default）"
									}), providers.map((p) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
										value: p.id,
										children: p.id
									}, p.id))]
								})
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-cell",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ModelIdCell, {
									pid: draft.roles[role.role].tasks[task.kind].provider || "（未设 provider）",
									models: modelsOf(draft.roles[role.role].tasks[task.kind].provider),
									value: draft.roles[role.role].tasks[task.kind].model,
									onChange: (v) => setTaskField(role.role, task.kind, "model", v),
									listId: `syp-ml-${role.role}-${task.kind}`
								}, `${draft.roles[role.role].provider}-${task.kind}`), /* @__PURE__ */ (0, react_jsx_runtime.jsx)(UnregHint, {
									pid: draft.roles[role.role].tasks[task.kind].provider,
									model: draft.roles[role.role].tasks[task.kind].model
								})]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "syp-route-cell",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "syp-route-eff",
									children: effOf(task.effective)
								}), task.effective !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "syp-route-via",
									children: ["via ", task.effective.via]
								})]
							})
						]
					}, task.kind))] }, role.role))
				]
			}),
			msg !== "" && (msg.startsWith("保存失败") || msg.startsWith("请求失败") ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "syp-err",
				children: msg
			}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "syp-ok",
				children: msg
			})),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "syp-route-actions",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "syp-btn syp-btn-primary",
						disabled: busy,
						onClick: () => {
							save();
						},
						children: busy ? "保存中…" : "保存路由表"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "syp-btn",
						disabled: busy,
						onClick: () => {
							load();
						},
						children: "放弃修改（重新加载）"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "syp-hint",
						children: "查表规则：(role, task_kind) → tasks.<kind> → roles.<role> → default；条目留空即向上落兜底。"
					})
				]
			})
		]
	});
}
//#endregion
//#region src/host/session-charter.ts
/**
* sandbar-workbench · session-charter 渲染纯函数（t260904-07）。
*
* 职责：把 `server/session_charter.md`（会话开局注入源，改完即生效）
* 渲染成单项目的注入文本：
*   - the general template (after the file-doc comment is stripped, up to the
*     first `## project:` section — t261008-01 stripLeadingComment) gets its
*     placeholders filled ({{project_key}}/{{project_name}}/{{primary_dir}}/
*     {{engine_root}}, including placeholder-like text inside comments — the
*     unified-rendering rule, 260904 appendix + plan R4);
*   - 命中 `## project:<key>` 分段（重复取首个）把该段原文追加在通用段后，
*     段内占位符统一渲染（如 suyou 段的 {{engine_root}}）；
*   - 文件缺失/读失败/空/渲染结果空 → 回落 DEFAULT_CHARTER_TEMPLATE
*     （插件内置兜底简化版），由 node.ts 侧保证不 5xx。
*
* 本模块**零 node 顶层依赖**（纯字符串函数+常量，文件读取留在 node.ts——
* node.ts 已有 readFile）：SESSION_CHARTER_PATH 同时被 node.ts 路由注册与
* 客户端（session-entry.tsx）fetch URL 引用——同源常量派生，一处改动两端
* 同变（t260904-07 方案 R7，KI-042「两端路径漂移恒 404」的结构性防漂移），
* 也因此 tsdown 打进浏览器包不破（review C1 落位选型）。
* smoke/session-charter.mjs 直测本模块 + 源文本断言两端引用。
*/
/** 会话开局 charter 端点路径（node.ts 注册与客户端 fetch 共用常量）。 */
const SESSION_CHARTER_PATH = "/sandbar-workbench/api/session-charter";
/**
* 上下文注入机读标记（t260905-04）：引擎侧给注入文本打的「消息元数据 kind=charter」
* 落地载体。平台 wire 契约 PromptContentPart 无 metadata 字段（仓内冻结镜像
* server/plugins/workbench/tests/ki046-charter-prompt-shape.mjs WIRE_CONTRACT 实锤），
* so the marker sits on line 2 of the injected text (since t261008-01 line 1
* is the human-readable title line — the platform session title takes the
* first line and must not be a comment; an HTML-comment line is harmless for
* the model to read; the expanded view showing the full text is the agreed
* degradation — folded state hides the whole block, so "a new session opens
* with just a chip" is unaffected). Renderer
* （src/client/context-fold.ts）认本常量为折叠触发器，同源派生防两端漂移（R7 先例）；
* 未来任何上下文注入（项目简介、文档引用）带同一标记即走同一折叠件。
*/
const CHARTER_MARKER = "<!-- workbench:kind:charter -->";
/**
* First line of the injected text (t261008-01): a short, human-readable title
* line naming the project. The platform derives the session's durable title
* from the first message's first line, so this line — not the machine marker —
* is the session name a person sees. composeCharterInjection places the marker
* on line 2 (the fold predicate reads the first 3 lines, same-source constant).
* Tolerance: non-string -> empty-string; empty name -> key; both empty -> the
* fixed label.
*/
function charterTitleLine(projectName, projectKey) {
	const name = typeof projectName === "string" ? projectName.trim() : "";
	const key = typeof projectKey === "string" ? projectKey.trim() : "";
	const label = name !== "" ? name : key !== "" ? key : "project";
	return key !== "" && key !== label ? `Project session — ${label} (${key})` : `Project session — ${label}`;
}
/**
* Compose the full injected text (t261008-01): human-readable title line +
* machine marker + rendered charter body. The fold predicate
* (classifyContextFold) scans the first 3 lines for the marker, so the legacy
* shape (marker on line 1) and this shape both fold. Tolerance: a non-string
* charter counts as empty (the caller validates first; this function itself
* never throws); empty name -> key, both empty -> the fixed label.
*/
function composeCharterInjection(projectName, projectKey, charter) {
	const body = typeof charter === "string" ? charter : "";
	return `${charterTitleLine(projectName, projectKey)}\n${CHARTER_MARKER}\n${body}`;
}
//#endregion
//#region src/shared/charter-title.ts
/**
* charter-title.ts — detect session titles that are the raw charter injection
* text (t261008-01, console session labels).
*
* The platform derives a session's durable title from the first message; our
* project sessions open with the charter injection, so sessions created before
* t261008-01 carry titles that start with the machine marker comment (and the
* charter file's own doc comment). Those titles must not be shown as a row
* label — the session handle shows instead (Measure 1). Sessions created after
* t261008-01 get a human-readable first line (composeCharterInjection) and
* never match this predicate.
*
* Conservative on purpose: only the injection's own comment shapes match —
* the marker line (`CHARTER_MARKER`, same-source constant, R7 anti-drift) or an
* HTML comment that names the charter (`workbench:kind:charter` /
* `session_charter`). A user title that merely starts with `<!--` stays raw.
* Pure module: one same-source import, never throws, non-string → false.
*/
/**
* True when the title is (or starts with) the raw charter injection text.
* @param title the display title under test (first message first line origin).
*/
function isCharterRawTitle(title) {
	if (typeof title !== "string") return false;
	const first = title.split("\n").map((l) => l.trim()).find((l) => l !== "");
	if (first === void 0) return false;
	if (first === "<!-- workbench:kind:charter -->" || first.startsWith("<!-- workbench:kind:charter -->")) return true;
	return first.startsWith("<!--") && (first.includes("workbench:kind:charter") || first.includes("session_charter"));
}
/** 全局会话 id 判定：工单会话固定 `ticket-<工单id>` 前缀，不进账册。 */
function isGlobalSessionId(id) {
	return typeof id === "string" && id !== "" && !id.startsWith("ticket-");
}
/** 行标签：displayTitle 兜底 id（displayTitle 本身已兜底过 id，双保险）。 */
function labelOf(row, id) {
	const t = row?.displayTitle;
	return typeof t === "string" && t !== "" ? t : id;
}
/**
* Row label (t261008-01, Measure 1): a session whose displayTitle is the raw
* charter injection text (see shared/charter-title.ts isCharterRawTitle) must
* not show comment text as its label — the handle shows instead (the executor
* session keeps its fixed name, regular sessions show the short code; the
* caller derives it via displayHandle and passes it in). The raw title stays
* reachable in the tooltip (the rendering face owns that). A missing handle
* (empty/non-string) falls back to the id — never guess an executor locally.
* Non-charter titles keep the exact labelOf behavior: zero change.
*/
function rowLabelOf(row, id, handle) {
	const label = labelOf(row, id);
	if (!isCharterRawTitle(label)) return label;
	return typeof handle === "string" && handle !== "" ? handle : id;
}
/**
* 账册反序列化（localStorage → OpenedEntry[]）：坏 JSON、非数组、脏条目
* （缺 id/project、lastOpenedAt 非有限数）一律容错剔除，全脏则空册——
* 不抛不崩，宁可列表空也不让侧栏挂掉。同 id 重复条目只留最靠前的一份。
*/
function parseLedger(raw) {
	if (!raw) return [];
	let data;
	try {
		data = JSON.parse(raw);
	} catch {
		return [];
	}
	if (!Array.isArray(data)) return [];
	const seen = /* @__PURE__ */ new Set();
	const out = [];
	for (const item of data) {
		if (typeof item !== "object" || item === null) continue;
		const e = item;
		if (typeof e.id !== "string" || e.id === "" || seen.has(e.id)) continue;
		if (typeof e.project !== "string" || e.project === "") continue;
		seen.add(e.id);
		out.push({
			id: e.id,
			project: e.project,
			cwd: typeof e.cwd === "string" ? e.cwd : "",
			lastOpenedAt: typeof e.lastOpenedAt === "number" && Number.isFinite(e.lastOpenedAt) ? e.lastOpenedAt : 0,
			...typeof e.title === "string" ? { title: e.title } : {},
			...typeof e.seq === "number" && Number.isFinite(e.seq) ? { seq: e.seq } : {}
		});
	}
	return out;
}
/** 账册序列化（OpenedEntry[] → localStorage）。 */
function serializeLedger(entries) {
	return JSON.stringify(entries ?? []);
}
/**
* 登记一次打开/新建：同 id upsert（更新 project/cwd/lastOpenedAt，可选带 title）
* 并插到数组头部（=登记顺序最新），其余条目顺序不变；超出 cap 时淘汰最旧的。
* ticket- 前缀的工单会话拒绝入账（有自己的常驻入口，不混入）。返回新数组
* （不改入参）。只服务新建登记、blank 自愈换绑两条显式路径（↺ 恢复已随
* R8 顶部行退役）。
*/
function touchEntry(entries, entry, cap = 20) {
	if (!isGlobalSessionId(entry?.id) || typeof entry?.project !== "string" || entry.project === "") return Array.isArray(entries) ? entries.slice() : [];
	const next = {
		id: entry.id,
		project: entry.project,
		cwd: typeof entry.cwd === "string" ? entry.cwd : "",
		lastOpenedAt: typeof entry.lastOpenedAt === "number" && Number.isFinite(entry.lastOpenedAt) ? entry.lastOpenedAt : Date.now(),
		...typeof entry.title === "string" ? { title: entry.title } : {},
		...typeof entry.seq === "number" && Number.isFinite(entry.seq) ? { seq: entry.seq } : {}
	};
	const out = [next, ...(Array.isArray(entries) ? entries : []).filter((e) => e && e.id !== next.id)];
	return cap > 0 && out.length > cap ? out.slice(0, cap) : out;
}
/**
* 从账册剔除一个 id（打开失败的残留清理：会话已被磁盘清理时点击 open
* 失败，顺手剔除——一行容错，非清理 UI）。返回新数组（不改入参）。
*/
function removeEntry(entries, id) {
	return (Array.isArray(entries) ? entries : []).filter((e) => e && e.id !== id);
}
/**
* 算项目内会话 tab：账册按 project 精确过滤 → 只留有合法 seq（≥1 有限数）的
* 条目 → seq 升序（=登记顺序）→ 标题/高亮装配。无上限（拍板 2）；缺 seq 条目
* 不显示（迁移过渡态——消费方挂载时先走 backfillProjectSeqs 补号，防御纵深）。
* active = id === current（与顶部行同源；current 全局唯一 → 高亮至多一个，
* current 为工单会话/未入账会话时全不亮，R6）。
*/
function pickProjectTabs(entries, opts) {
	const project = typeof opts?.project === "string" ? opts.project : "";
	if (project === "") return [];
	const byId = opts?.byId ?? {};
	const current = opts?.current;
	return (Array.isArray(entries) ? entries : []).filter((e) => e && typeof e.id === "string" && isGlobalSessionId(e.id) && e.project === project).map((e) => ({
		id: e.id,
		seq: typeof e.seq === "number" && Number.isFinite(e.seq) && e.seq >= 1 ? Math.floor(e.seq) : 0,
		title: typeof e.title === "string" && e.title.trim() !== "" ? e.title : labelOf(byId[e.id], e.id),
		active: e.id === current
	})).filter((t) => t.seq >= 1).sort((a, b) => a.seq - b.seq);
}
/**
* 存量编号迁移（幂等）：账册里缺 seq 的条目（第 3 面① 之前登记的存量）按
* 项目内登记顺序（lastOpenedAt 升序——t260831-06 起该键只在登记路径写、单调
* 递增=登记顺序；并列时按数组位置稳定破平）补号，从「该项目现存最大 seq」之上
* 续起，保项目内 seq 唯一不变式。无缺号时**原样返回入参引用**（调用方据此免
* persist——sidebar 挂载 effect 用引用相等判无操作）。返回新数组不改入参。
*
* 交错态说明（常态不可达，防御口径）：迁移后新登记条目都带 seq，账册不应再有
* 缺号条目；若因异常路径（如重开时原号畸形被 touchEntry 剔字段）再现缺号，
* 本函数从该项目现存最大号之上续——不重号（不变式优先），该条目显示顺序
* 排在存量之后（lastOpenedAt 最新，语义上即「重新登记」，可接受）。
*/
function backfillProjectSeqs(entries) {
	const list = Array.isArray(entries) ? entries : [];
	const seqOf = (e) => typeof e?.seq === "number" && Number.isFinite(e.seq) && e.seq >= 1 ? Math.floor(e.seq) : 0;
	const maxByProject = /* @__PURE__ */ new Map();
	let hasGap = false;
	for (const e of list) {
		if (!e || typeof e.project !== "string" || e.project === "") continue;
		const s = seqOf(e);
		if (s > 0) maxByProject.set(e.project, Math.max(maxByProject.get(e.project) ?? 0, s));
		else hasGap = true;
	}
	if (!hasGap) return list;
	const gaps = list.map((e, i) => ({
		e,
		i
	})).filter(({ e }) => e && seqOf(e) === 0 && typeof e.project === "string" && e.project !== "").sort((a, b) => (a.e.lastOpenedAt ?? 0) - (b.e.lastOpenedAt ?? 0) || a.i - b.i);
	const assign = /* @__PURE__ */ new Map();
	for (const { e, i } of gaps) {
		const next = (maxByProject.get(e.project) ?? 0) + 1;
		maxByProject.set(e.project, next);
		assign.set(i, next);
	}
	return list.map((e, i) => assign.has(i) ? {
		...e,
		seq: assign.get(i)
	} : e);
}
/**
* 算某项目的下一个可用编号（登记时调用；号域含「最近关闭」——closed 数据
* 在 ↺ 恢复随顶部行退役后仍保留，仅作防撞号域，BO-1）：max(计数器值, 账册内该项目现存最大
* seq, 「最近关闭」内该项目最大 seq) + 1（closed 号域为 t260904-01 验收走查
* BO-1 修复：计数器丢失时已关的最大号不再重发——重发后再从 ↺ 重开原号条目
* 会撞号，破坏拍板 1 的「稳定身份」）。计数器丢失/落后时以账册与最近关闭
* 兜底——只可能跳号，不可能重号（编号语义=稳定身份而非稠密序列，跳号无害）。
* 畸形容错：计数器非有限数/负数按 0 处理；project 非字符串按「无账册条目」
* 处理；closed 非数组忽略、脏条目（缺 project/seq 非有限数）跳过。
*/
function nextProjectSeq(entries, project, counterMax, closed) {
	let max = typeof counterMax === "number" && Number.isFinite(counterMax) && counterMax > 0 ? Math.floor(counterMax) : 0;
	if (typeof project === "string" && project !== "") {
		for (const e of Array.isArray(entries) ? entries : []) {
			if (!e || e.project !== project) continue;
			if (typeof e.seq === "number" && Number.isFinite(e.seq) && e.seq > max) max = Math.floor(e.seq);
		}
		for (const e of Array.isArray(closed) ? closed : []) {
			if (!e || e.project !== project) continue;
			if (typeof e.seq === "number" && Number.isFinite(e.seq) && e.seq > max) max = Math.floor(e.seq);
		}
	}
	return max + 1;
}
//#endregion
//#region src/client/session-ledger-store.ts
/**
* sandbar-workbench · 会话账册模块级共享 store（t260830-01）。
*
* 为什么存在：侧栏 <SessionSection> 与 hero <HeroSessionEntry> 挂在同一个
* document 里，各自调用 useSessionEntry 时账册曾是实例各自的 useState——
* hero 新建/切换后侧栏要到下次刷新才可见（工单 t260830-01 根因）。同页
* 两组件同 document，W3C 口径 storage 事件只触发于同源**其它** document、
* 同页永不触发，所以跨实例同步走「共享模块级状态 + 订阅」：账册状态收敛
* 到本模块单例，persist 更新单例并通知全部订阅者，两个视图各自
* useSyncExternalStore 订阅，同帧（同一通知周期内）重渲染。
*
* 账册口径零变化：key 与格式沿用 t260828-02（值见 LEDGER_KEY），读写容错
* 全部复用 src/shared/sessions.ts 的 parseLedger/serializeLedger，不放宽。
*
* 【模块顶层零 IO 约束】本模块顶层不得触碰 localStorage/DOM——smoke
* （node 裸跑，无 DOM）必须先 stub globalThis.localStorage 再 import 本
* 模块，顶层一旦有 IO 即静默打断全部 smoke 的 stub 时序。所有 IO 收敛在
* 函数体内（getLedgerSnapshot / persistLedger）。本模块也不得 import
* react 或任何 npm 依赖（node_modules 不随仓库安装，smoke 靠 node
* type-stripping 裸跑）。
*/
/**
* 会话记账层账册的 localStorage key（t260828-02 定值，t260830-01 起定义
* 移入本文件；session-entry.tsx re-export 保持对外符号兼容）。
*/
const LEDGER_KEY = "sandbar-workbench-opened-sessions-v1";
/** 缓存快照。null = 尚未从 localStorage 惰性读入（非空数组后引用不变）。 */
let current$1 = null;
const subscribers$1 = /* @__PURE__ */ new Set();
/** 登记订阅者，返回注销函数（useSyncExternalStore 的 subscribe 协议）。 */
function subscribeLedger(fn) {
	subscribers$1.add(fn);
	return () => {
		subscribers$1.delete(fn);
	};
}
/**
* 账册快照（useSyncExternalStore 的 getSnapshot）。首次调用惰性读入：
* localStorage.getItem 抛异常或 payload 畸形一律按 parseLedger 既有容错
* 剔脏/空册，不抛不崩。之后缓存引用不变，保证快照稳定性（不会触发
* useSyncExternalStore 无限重渲染）。
*/
function getLedgerSnapshot() {
	if (current$1 === null) try {
		current$1 = parseLedger(localStorage.getItem(LEDGER_KEY));
	} catch {
		current$1 = [];
	}
	return current$1;
}
/**
* 落盘 + 广播（useSessionEntry 的 persist 收口到这）：先写 localStorage
* （写不进只丢持久化——沿用原「本次会话内仍可见」语义，且因为无论如何
* 都更新单例并通知，两个视图内存态一致、不产生分叉），再更新缓存快照、
* 逐订阅者通知。单个订阅者回调抛异常被 try/catch 隔离并留痕，不影响
* 其它订阅者收到本次通知——不隔离则一个视图 throw 会中断循环，恰好
* 复发本单要修的「常驻入口静默失同步」。
*/
function persistLedger(entries) {
	try {
		localStorage.setItem(LEDGER_KEY, serializeLedger(entries));
	} catch {}
	current$1 = entries;
	for (const fn of [...subscribers$1]) try {
		fn();
	} catch (err) {
		console.error("[workbench] 会话账册订阅者通知失败（该订阅者本轮跳过，不影响其它订阅者）：", err);
	}
}
/** Session-ledger host API path (verbatim-equal to the path registered in node.ts; KI-042 drift guard). */
const SESSIONS_API_PATH = "/sandbar-workbench/api/wf/sessions";
/** File entry -> ledger entry field mapping (session_id -> id and friends; the single snake->camel point). */
function fileEntryToOpened(e) {
	return {
		id: e.session_id,
		project: "",
		cwd: typeof e.cwd === "string" ? e.cwd : "",
		lastOpenedAt: typeof e.last_opened_at === "number" && Number.isFinite(e.last_opened_at) ? e.last_opened_at : 0,
		...typeof e.title === "string" ? { title: e.title } : {},
		...typeof e.handle === "string" && e.handle !== "" ? { handle: e.handle } : {}
	};
}
/**
* Fetch the project session ledger file and refresh the cache from it:
* GET SESSIONS_API_PATH?project=<key> -> 2xx with a NON-EMPTY entries array ->
* this project's cached entries are replaced wholesale by the file entries
* (file-wins) + persist (into the localStorage cache + broadcast). Anything
* else returns null silently and the cache is untouched (cache fallback, no
* crash) — INCLUDING a 2xx reply that yields an EMPTY entry list: an empty
* reply means the file face is absent/unreachable behind the endpoint (the
* route does not exist yet, a stub answered, or the file is genuinely empty),
* and the fallback contract is display-what-you-have, never display-nothing —
* seeded cache entries must survive a missing file face (regression lock:
* t261005-09's journey seeds only the localStorage cache; the round-8 red
* was the file-empty win wiping them). Executor projection entries
* (handle='executor') enter the cache through the same path - the project row
* and the identity band share one data source.
*/
async function fetchProjectLedger(project) {
	if (typeof project !== "string" || project === "") return null;
	try {
		const res = await fetch(`${SESSIONS_API_PATH}?project=${encodeURIComponent(project)}`);
		if (!res.ok) return null;
		const body = await res.json();
		if (!Array.isArray(body?.entries)) return null;
		const fileEntries = body.entries.filter((e) => e && typeof e.session_id === "string" && e.session_id !== "").map(fileEntryToOpened).map((e) => ({
			...e,
			project
		}));
		if (fileEntries.length === 0) return null;
		const others = getLedgerSnapshot().filter((e) => e.project !== project);
		persistLedger([...fileEntries, ...others]);
		return fileEntries;
	} catch {
		return null;
	}
}
/**
* Register one session into the project file (POST): resolves to the server-
* assigned handle on success (the short code the identity band and the project
* row display); throws on any failure (the caller shows an inline notice - a
* registration failure is never silent, plan step 3 acceptance). A failure does
* not roll back the local ledger entry (the cache and the file diverge briefly
* and converge on the next fetch - declared behavior).
*/
async function pushSessionEntry(entry) {
	const res = await fetch(SESSIONS_API_PATH + (entry.project ? `?project=${encodeURIComponent(entry.project)}` : ""), {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({
			session_id: entry.id,
			cwd: entry.cwd,
			...entry.title !== void 0 ? { title: entry.title } : {},
			...entry.lastOpenedAt !== void 0 ? { lastOpenedAt: entry.lastOpenedAt } : {},
			opened_at: entry.lastOpenedAt,
			last_opened_at: entry.lastOpenedAt
		})
	});
	const text = await res.text();
	let body = {};
	try {
		body = JSON.parse(text);
	} catch {}
	if (!res.ok || body?.ok !== true) throw new Error(`session ledger register failed (HTTP ${res.status}): ${typeof body?.error === "string" ? body.error : text.slice(0, 120)}`);
	return typeof body.handle === "string" ? body.handle : "";
}
//#endregion
//#region src/client/closed-ledger-store.ts
/**
* sandbar-workbench · 「最近关闭」列表模块级共享 store（t260904-01 D1 修复，
* session-entry 第 3 面①验收走查打回项）。
*
* 为什么存在：D1 回归——t260904-01 双实例拆分（顶部行 +
* sidebar 项目行各持一个 useSessionEntry）前，closedList 是 hook 实例各自的
* useState，单实例时代够用；拆分后项目行（二号实例）handleClose 只写
* localStorage + 自身 state，顶部行（一号实例）的 ↺ 钮渲染条件
* `closedRecent.length > 0` 挂在自身挂载时快照上——boot 后首关场景 ↺ 钮
* 不出现，「打开菜单时刷新」的惰性刷新救不了「钮未渲染」的空态死锁（用户
* 须刷新页面才能找回恢复入口，验收标准 4「可从恢复路径找回」断裂）。
*
* 修复=账册主 store（session-ledger-store.ts）同款模式：状态收敛到本模块
* 单例，persist 更新单例并通知全部订阅者，两实例各自 useSyncExternalStore
* 订阅、同一通知周期内重渲染——任意实例关闭/重开，另一实例的 ↺ 钮与菜单
* 即时可见。同页 storage 事件不触发的口径同主 store 头注（W3C：仅同源其它
* document），跨实例同步只能走共享状态。
*
* IO 容错（对齐 session-ledger-store / 原 readClosedLedger 取舍）：
* - 【模块顶层零 IO】顶层不碰 localStorage/DOM（smoke node 裸跑先 stub 再
*   import 的时序约束），全部 IO 收敛在函数体内；不 import react/npm 依赖。
* - 读：localStorage.getItem 抛异常或坏 JSON → parseLedger 容错空表，不抛不崩。
* - 写：写失败丢持久化但**仍更新内存单例并通知**（本次会话内各实例一致，
*   不产生分叉——「写失败丢持久化」语义与主 store 一致）。
* - 单订阅者回调抛异常被隔离并留痕，不中断其余订阅者（主 store 同款）。
*
* cap 10、同 id 重关重提头、超出淘汰最旧——语义沿用 t260831-06 原口径，
* 本模块只改「状态归属」（实例 state → 共享单例），不改任何业务规则。
*/
/** 「最近关闭」列表的 localStorage key（t260831-06 定值，D1 修复起定义随
* IO 迁入本文件；session-entry.tsx re-export 保持对外符号兼容；260908 终切
* 改 sandbar 前缀，旧 key 读入时一次性迁移——KI-058 状态层清单规则）。 */
const CLOSED_LEDGER_KEY = "sandbar.workbench.closedSessions";
const LEGACY_CLOSED_LEDGER_KEY = "suyou.workbench.closedSessions";
/** 缓存快照。null = 尚未从 localStorage 惰性读入。 */
let current = null;
const subscribers = /* @__PURE__ */ new Set();
/** 登记订阅者，返回注销函数（useSyncExternalStore 的 subscribe 协议）。 */
function subscribeClosed(fn) {
	subscribers.add(fn);
	return () => {
		subscribers.delete(fn);
	};
}
/**
* 列表快照（useSyncExternalStore 的 getSnapshot）。首次调用惰性读入
* localStorage（抛异常/坏 JSON → parseLedger 容错空表）；之后缓存引用不变，
* 保证快照稳定性（不触发无限重渲染）。
*/
function getClosedSnapshot() {
	if (current === null) try {
		let raw = localStorage.getItem(CLOSED_LEDGER_KEY);
		if (raw === null) {
			const legacy = localStorage.getItem(LEGACY_CLOSED_LEDGER_KEY);
			if (legacy !== null) {
				localStorage.setItem(CLOSED_LEDGER_KEY, legacy);
				localStorage.removeItem(LEGACY_CLOSED_LEDGER_KEY);
				raw = legacy;
			}
		}
		current = parseLedger(raw);
	} catch {
		current = [];
	}
	return current;
}
/**
* 落盘 + 广播：先写 localStorage（cap 截断后写，写失败只丢持久化），再更新
* 内存单例（同样 cap 收敛，防越界增长）并逐订阅者通知——任意实例调用，全部
* 实例同帧看到（D1 修复核心）。
*/
function persistClosed(entries) {
	const capped = (Array.isArray(entries) ? entries : []).slice(0, 10);
	try {
		localStorage.setItem(CLOSED_LEDGER_KEY, serializeLedger(capped));
	} catch {}
	current = capped;
	for (const fn of [...subscribers]) try {
		fn();
	} catch (err) {
		console.error("[workbench] 最近关闭列表订阅者通知失败（该订阅者本轮跳过，不影响其它订阅者）：", err);
	}
}
//#endregion
//#region src/shared/workspaces-compat.ts
/** 不可用时的精确报错文案（点名两版各自的所在面，避免诊断被引向错误方向）。 */
const START_SESSION_MISSING = "startSession 不可用：dsh 0.1.5 起该 API 在 uiWorkspace 上（dsh-client-ui-workspace），ctx.workspaces 现为纯控制器（dsh-api-workspace-controller，无此方法）；0.1.1 时代它在 ctx.workspaces 上。候选服务面均未提供 startSession。";
/**
* 从候选面里挑出可用的 startSession。
* @param candidates - 按优先级排列的服务面（如 `[ctx.uiWorkspace, ctx.workspaces]`）。
* @throws 所有候选都没有 startSession 时抛错（消息＝START_SESSION_MISSING）。
*/
function resolveStartSession(candidates) {
	for (const face of candidates) {
		const fn = face?.startSession;
		if (typeof fn === "function") return (workspaceId) => fn.call(face, workspaceId);
	}
	throw new Error(START_SESSION_MISSING);
}
//#endregion
//#region src/client/session-entry.tsx
/**
* sandbar-workbench · 会话动作层唯一样态（session-entry t260831-02 → 票② t260904-05 R8 退役收口）。
*
* R8 顶部行退役后，本文件**不再有任何渲染面**——只保留 useSessionEntry()
* 动作层（账册读写 + handleNew/handleOpen/handleClose），供项目行
* （project-session-row.tsx）消费；账册/闭账/编号计数器全部复用
* src/shared/sessions.ts 纯函数（记账层语义零改动）。随顶部行一并退役
* （拍板 2/3/4，notes/epics/session-entry.md 票②拍板）：
*   - ↺「最近关闭」恢复菜单（handleReopen）——不迁移；闭账数据保留，
*     仅作 nextProjectSeq 防撞号域（BO-1），无 UI 消费面；
*   - tab 双击重命名（重命名纯函数随 shared/sessions.ts 一并退役）；
*   - 顶部行组件/SessionTab/SESSION_ENTRY_STYLES 与
*     顶部行家族 data-wb-* 断言锚（无残留消费方，smoke/hero.mjs 有
*     「不在场」反转断言看守）。
*
*   - FACTORY_NEW_LABELS：出厂「⊕ New Session」钮的语义锚——aria-label 全集
*     （dsh-client-ui-sidebar 的 locale 字典只有 zh/en 两份，实查于平台包；
*     若 dsh 新增语言字典，锚集合在此补）。sidebar.tsx 的注入 effect 用它
*     找到出厂钮并隐藏——**职责=压制全局新建入口**（拍板 1：移除注入=出厂
*     全局钮回到左栏顶部，落点=平台当前工作区非项目归属，与「入口长在项目上」
*     直接冲突）；找不到锚时软退化：出厂钮照常显示，console.warn 留痕。
*
* 关闭语义（t260831-06 口径沿用）：tab × 确认弹层后 handleClose =
* removeEntry 剔账册 + 条目移入「最近关闭」（cap 10）+ 尽力调 sessions.close?；
* 会话数据不删，仅剔入口。主账册登记只有新建登记、blank 自愈换绑两条显式路径
* （↺ 恢复已随顶部行退役），无 current 自动登记 effect——关闭当前活跃会话的
* 终态：tab 消失、current 不变（会话仍在运行），不会复活。
*
* 故障模式取舍（票 t260831-04）：
*   - 新建走 services 的 startSession（工厂同款）；服务缺失：行内可见错误 +
*     console.error，按钮不复位为假成功。**260923 起统一经 resolveStartSession
*     取用**：0.1.5 该 API 在 ctx.uiWorkspace、0.1.1 在 ctx.workspaces（混版
*     直呼旧面＝TypeError「workspaces.startSession is not a function」，实弹过）；
*   - 工作区按项目主目录匹配（workspaceForDir：精确→前缀→realtime 归一），
*     找不到且 projectDir 有值 → workspaces.create（host 幂等：已注册同目录
*     返回既存工作区）；create 失败：行内提示，不落账不静默；
*   - startSession 后 current 10s 未落定：行内提示 + warn；工作区已连接，
*     可从列表进入；
*   - 切换路径 sessions.open(id) 失败（throw：未列出 id 是 throw
*     不是静默 no-op）：console.error 留痕 + 行内错误提示，账册条目保留
*     （超时≠磁盘清理，自动 removeEntry 已删——t260831-02 的超时剔账正是
*     「切回内容丢失」成因之一）；账册中 blank 会话条目（自铸 chat- 残留）
*     走 startSession 换绑自愈——blank 零内容，无损失；
*   - open 已调用但 list.current 未指向目标：warn 留痕（激活未生效线索）；
*   - localStorage 读失败/坏 JSON：parseLedger 容错剔脏；写失败：丢持久化但
*     本次会话内 state 仍可见（同一 hook 无第二份实现）；
*   - 工单会话（ticket- 前缀）：isGlobalSessionId 在 touchEntry 里挡在账册外，
*     顶部入口与账册同函数同口径，天然不混入（smoke/sessions.mjs 有断言）。
*
* 第 3 面①（t260904-01，项目内会话区）：handleNew 在登记时分配项目内序号 seq
* （拍板 1「不回收」：每项目计数器续号，见 SEQ_COUNTER_KEY），blank 换绑带原号；
* 项目行消费同一账册（模块级共享 store）与同一组动作。行内通知带归属项目
* （noticeProject）：项目行只显示自己项目的失败提示。BO-1：nextProjectSeq
* 兜底号域纳入「最近关闭」，计数器丢失时不再重发已关最大号。
*/
/**
* 出厂「⊕ New Session」钮的语义锚（aria-label 全集）：dsh-client-ui-sidebar 的
* `session.new.label` 词条，zh=新建会话 / en=New session（实查平台包 locale 字典，
* 全包仅此两份）。侧栏注入 effect 以「SidebarRoot 直接子 button 且 aria-label
* 命中本集合」定位出厂钮——零 CSS 类名匹配（t260828-06 死因不复犯）。
* smoke/hero.mjs 对本集合有存在性断言（新增语言字典时提醒补锚）。
*/
const FACTORY_NEW_LABELS = ["新建会话", "New session"];
/** 条目移入「最近关闭」（同 id 去重重提头 + cap 截断），返回新列表。 */
function pushClosedLedger(prev, entry) {
	return [entry, ...prev.filter((e) => e && e.id !== entry.id)].slice(0, 10);
}
const SEQ_COUNTER_KEY = "sandbar-workbench-project-seq-v1";
/** 读项目编号计数器（localStorage → {[project]: 最大已用 seq}；坏数据容错为空表）。 */
function readSeqCounters() {
	try {
		const raw = window.localStorage.getItem(SEQ_COUNTER_KEY);
		if (!raw) return {};
		const data = JSON.parse(raw);
		if (typeof data !== "object" || data === null || Array.isArray(data)) return {};
		const out = {};
		for (const [k, v] of Object.entries(data)) {
			if (typeof k !== "string" || k === "") continue;
			if (typeof v !== "number" || !Number.isFinite(v) || v < 0) continue;
			out[k] = v;
		}
		return out;
	} catch {
		return {};
	}
}
/** 写回项目编号计数器（写失败丢持久化但不抛——取舍见上方清单）。 */
function writeSeqCounters(map) {
	try {
		window.localStorage.setItem(SEQ_COUNTER_KEY, JSON.stringify(map));
	} catch {}
}
/**
* 等 id 进入客户端会话列表。勘误后口径（票 t260831-02）：open(id) 对未
* 列出 id 是 **throw**（manager.select: 'sessions.select: unknown session …'），
* 不是静默 no-op；scope 的惰性铸造时机是「first resolution」而非「first open」。
* 等 listed 的价值=把「未列出即 throw」挡在调用前、并把等不到的场景转成明确报错，
* 而不是依赖 catch——保留本前置，语义按订正后口径理解。
*/
async function waitForListed(sessions, id, ms = 1e4) {
	const listed = () => {
		try {
			return id in (sessions.list.getSnapshot()?.byId ?? {});
		} catch {
			return false;
		}
	};
	const t0 = Date.now();
	while (!listed() && Date.now() - t0 < ms) {
		try {
			await sessions.refresh?.();
		} catch {}
		await new Promise((r) => setTimeout(r, 200));
	}
	return listed();
}
/**
* 按 cwd 匹配工作区：先精确 path，再目录前缀（工作区是项目目录或其祖先/后代
* 场景都容——平台 realpath canon 对我们的注册表 path 可能带 /private 前缀等）。
* 找不到返回 undefined，调用方决定是否 create。
*/
function workspaceForDir(items, dir) {
	if (!dir) return void 0;
	return items.find((w) => w.path === dir) ?? items.find((w) => dir.startsWith(w.path + "/") || w.path.startsWith(dir + "/")) ?? items.find((w) => w.path.replace(/^\/private/, "") === dir.replace(/^\/private/, ""));
}
/**
* 等 staging 落定：startSession 之后等 list.current **离开 prev**（新开/换绑）。
* 超时未变 = startSession 复用了 prev 指向的 blank 会话（工厂语义：blank 复用，
* current 合法地不动），此时返回 prev 作为 staged 会话（prev 为 null 则 null）。
* ⚠️ 不能「等 current 非 null」——点击前 current 就非空（正在看的会话），
* 那会把旧会话误记进账册（自测探针实锤过的 bug）。
*/
async function waitForStaged(sessions, prev, ms = 1e4) {
	const read = () => {
		try {
			return sessions.list.getSnapshot()?.current ?? null;
		} catch {
			return null;
		}
	};
	const t0 = Date.now();
	let cur = read();
	while ((cur === null || cur === prev) && Date.now() - t0 < ms) {
		try {
			await sessions.refresh?.();
		} catch {}
		await new Promise((r) => setTimeout(r, 200));
		cur = read();
	}
	return cur ?? prev ?? null;
}
/** 读会话 blank 位（平台语义：新会话零内容=blank）。快照读失败一律视为非
*  blank——注入宁可不发，不误注入到读不出状态的会话上。 */
function isBlankSession(sessions, id) {
	try {
		return (sessions.list.getSnapshot()?.byId ?? {})[id]?.blank === true;
	} catch {
		return false;
	}
}
/**
* 会话开局 charter 注入（t260904-07）：blank 新会话恰一次注入项目 charter
* （GET /sandbar-workbench/api/session-charter?project=<key> 现读现渲染）→
* sessions.scope(staged) → sessions.sessionOf(actx) → session.prompt([文本分片],
* 'queue')（平台首条消息正路：blank→engaging，触发一轮 agent 回复=预期
* kick-off）。借鉴取舍清单（t260831-08 ⑥ 口径，方案 R1 八项逐项声明）：
*   1. 恢复/切换路径不注入——带：仅 handleNew 单路径调用本函数；
*   2. 非 blank 二次注入污染——带：blank 守卫（发过首条即非 blank）；
*   3. staged 未落定即注入——带：handleNew 已 waitForStaged+null 提前 return；
*   4. 「本项目行」归属——由构造保证（startSession 绑项目工作区+账册同帧
*      project=pk），不设运行时守卫（冗余）；
*   5. 服务端建会话半——不带：本链路走客户端工厂链，服务端只出只读端点；
*   6. 旧 API conversation.send——不带：改 session.prompt('queue')；
*   7. waitForStaged 超时复用 blank prev——在守卫域内：blank===true 时注入
*      命中复用会话=预期（工厂语义），非 blank 被守卫挡掉；
*   8. 注入失败不回滚——本方案定死：就地捕获+行内提示，会话创建与注入解耦。
*  勘误（t260904-11，KI-046）：「失败」现含两条路——①throw（fetch/解析/传输层）；
*  ②prompt 返回 RpcResult{ok:false}（平台业务失败不 throw）——②原实现漏检，
*  错误只经 toast 直达用户、console 零留痕；现统一转①走下方 catch 就地消化。
* 报错精确纪律（R3，KI-018/025 谎报同族）：全链路 try/catch 就地消化，绝不
* 冒泡 handleNew 外层 catch（外层文案=「新建会话失败」，而此刻会话已创建）。
* TOCTOU 复核（R5）：prompt 前一刻用最新快照复核 blank 位，网络往返期间用户
* 抢先发首条则静默跳过（console.info 留痕——用户已接管对话，提示是噪音）。
*/
async function injectSessionCharter(sessions, staged, projectKey, notify) {
	try {
		if (globalThis.localStorage?.getItem("sandbar-ui-capture-skip-charter") === "1") return;
	} catch {}
	if (!isBlankSession(sessions, staged)) return;
	try {
		const res = await fetch(`${SESSION_CHARTER_PATH}?project=${encodeURIComponent(projectKey)}`);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const text = await res.text();
		let body;
		try {
			body = JSON.parse(text);
		} catch {
			throw new Error(`响应非 JSON：${text.slice(0, 80)}`);
		}
		const charter = body?.charter;
		if (typeof charter !== "string" || charter.trim() === "") throw new Error("charter 字段缺失或非字符串（响应体畸形）");
		const projectName = body?.projectName;
		const displayProjectName = typeof projectName === "string" && projectName.trim() !== "" ? projectName : projectKey;
		if (!isBlankSession(sessions, staged)) {
			console.info("[workbench] charter 注入跳过：会话已非 blank（用户已抢先发首条）：", staged);
			return;
		}
		if (typeof sessions.sessionOf !== "function") throw new Error("ctx.sessions.sessionOf 未注入（运行时面缺失）");
		const result = await sessions.sessionOf(sessions.scope(staged)).prompt([{
			type: "text",
			text: composeCharterInjection(displayProjectName, projectKey, charter)
		}], "queue");
		if (!result?.ok) {
			const detail = result && !result.ok ? `${result.error.code} ${result.error.message}` : "空结果（未返回 RpcResult）";
			throw new Error(`charter prompt 被平台拒收：${detail}`);
		}
	} catch (err) {
		console.error("[workbench] 会话开局 charter 注入失败（会话创建不受影响）：", staged, err);
		notify("Session charter injection failed (see the console for details); the session was created normally", projectKey);
	}
}
/**
* 会话入口共享 hook（动作层）：账册状态 + 新建/打开/关闭动作，渲染面=项目行。
*/
function useSessionEntry({ sessions, workspaces, getService, slotOpen, projectKey, projectDir }) {
	const list = sessions.list;
	const listState = (0, react.useSyncExternalStore)((0, react.useCallback)((fn) => list.subscribe(fn), [list]), (0, react.useCallback)(() => list.getSnapshot(), [list]));
	/** 「绑工作区 + 复用 blank + 正确打开」的启动动作（双版容错，260923）：
	*  **点击时**经 getService('uiWorkspace') 取 0.1.5 的服务面（免注入查找口，不能用
	*  属性形式——未 inject 即抛，260923 实弹），回落 0.1.1 的 ctx.workspaces；
	*  两者都没有时 resolveStartSession 抛精确错误（经外层 catch 进控制台）。 */
	const startWorkspaceSession = (0, react.useCallback)((workspaceId) => resolveStartSession([getService?.("uiWorkspace"), workspaces])(workspaceId), [getService, workspaces]);
	const ledger = (0, react.useSyncExternalStore)(subscribeLedger, getLedgerSnapshot);
	const persist = (0, react.useCallback)((entries) => {
		persistLedger(entries);
	}, []);
	const [creating, setCreating] = (0, react.useState)(false);
	/** 行内可见错误/提示（t260831-04）：open 链失败不再只打 console——用户在
	*  界面上能看见「为什么没切过去」。下一次动作或 8s 后自动清除（timer 有
	*  cleanup，见下方 effect，全终态回收）。 */
	const [entryNotice, setEntryNotice] = (0, react.useState)("");
	/** 通知归属项目（第 3 面①）：项目行据此只显示自己项目的提示（N 个项目组
	*  不重复同一条全局噪音）；undefined=无归属信息（顶部行不区分照常全显）。 */
	const [noticeProject, setNoticeProject] = (0, react.useState)(void 0);
	/** 通知统一入口：text='' 清空（连带清归属）。 */
	const notify = (0, react.useCallback)((text, project) => {
		setEntryNotice(text);
		setNoticeProject(text === "" ? void 0 : project);
	}, []);
	(0, react.useEffect)(() => {
		if (!entryNotice) return;
		const t = setTimeout(() => notify(""), 8e3);
		return () => clearTimeout(t);
	}, [entryNotice, notify]);
	/**
	* 打开一个已入账册的会话（t260831-04 收口：handleOpen/handleNew 共用，
	* 时序唯一实现）：refresh → waitForListed（轮询 200ms，≤10s）→
	* slotOpen || sessions.open → open 后读 list.current 自检。
	* - 超时：账册条目保留 + 行内提示，返回 false（t260831-02 的自动
	*   removeEntry 已删——超时只说明 wire 同步慢，误删=「切回丢内容」成因）；
	* - open throw（未列出 id）：console.error + 行内提示，返回 false；
	* - 成功但 current 未跟上：warn 留痕（激活未生效线索），仍返回 true——
	*   open 调用本身已生效，下一步激活是平台层时序，不在本插件能强制的面内。
	*/
	const openSession = (0, react.useCallback)(async (id, projectHint) => {
		notify("", void 0);
		if (!await waitForListed(sessions, id, 1e4)) {
			console.warn("[workbench] 打开会话：会话未进客户端列表（wire 同步慢或会话已被磁盘清理；账册条目保留，可稍后重试）：", id);
			notify("Session open timed out: the list has not synced yet; the entry was kept, retry later", projectHint);
			return false;
		}
		try {
			if (slotOpen) slotOpen(id);
			else sessions.open(id);
		} catch (err) {
			console.error("[workbench] 打开会话失败：", id, err);
			notify("Failed to open the session (see the console for details)", projectHint);
			return false;
		}
		await new Promise((r) => setTimeout(r, 250));
		let cur;
		try {
			cur = sessions.list.getSnapshot()?.current;
		} catch {
			cur = "<unreadable>";
		}
		if (cur !== id) console.warn("[workbench] open 已调用但 list.current 未指向目标（激活可能未生效，右栏或仍驻留 hero）：", id, "current=", String(cur));
		return true;
	}, [
		sessions,
		slotOpen,
		notify
	]);
	const handleOpen = (0, react.useCallback)(async (id) => {
		const entry = ledger.find((e) => e.id === id);
		if ((() => {
			try {
				return sessions.list.getSnapshot()?.byId ?? {};
			} catch {
				return {};
			}
		})()[id]?.blank === true && workspaces && entry?.cwd) {
			const ws = workspaceForDir(workspaces.list.getSnapshot()?.items ?? [], entry.cwd) ?? await workspaces.create({ path: entry.cwd }).catch((err) => {
				console.warn("[workbench] blank 会话自愈：工作区创建失败，退回普通打开：", entry.cwd, err);
			});
			if (ws) {
				const prev = (() => {
					try {
						return sessions.list.getSnapshot()?.current ?? null;
					} catch {
						return null;
					}
				})();
				startWorkspaceSession(ws.workspaceId);
				const staged = await waitForStaged(sessions, prev, 1e4);
				if (staged && staged !== id) {
					persist(touchEntry(removeEntry(ledger, id), {
						id: staged,
						project: entry.project,
						cwd: entry.cwd,
						title: entry.title,
						seq: entry.seq,
						lastOpenedAt: Date.now()
					}));
					try {
						await pushSessionEntry({
							id: staged,
							project: entry.project,
							cwd: entry.cwd,
							title: entry.title,
							lastOpenedAt: Date.now()
						});
					} catch (err) {
						console.error("[workbench] rebinding the session into the project ledger file failed (the local entry still works):", err);
					}
				}
				return;
			}
		}
		await openSession(id, entry?.project);
	}, [
		openSession,
		workspaces,
		sessions,
		ledger,
		persist,
		projectKey,
		startWorkspaceSession
	]);
	const handleNew = (0, react.useCallback)(async (target) => {
		const pk = target?.key ?? projectKey;
		const pd = target?.dir ?? projectDir;
		if (!pk || creating) return;
		if (!workspaces) {
			notify("New session failed: the workspaces service is unavailable", pk);
			console.error("[workbench] 新建会话失败：ctx.workspaces 未注入（index.tsx inject 列表缺 workspaces）");
			return;
		}
		setCreating(true);
		notify("", void 0);
		try {
			let ws = workspaceForDir(workspaces.list.getSnapshot()?.items ?? [], pd ?? "");
			if (!ws && pd) ws = await workspaces.create({ path: pd }).then((w) => ({
				...w,
				path: pd
			})).catch((err) => {
				console.error("[workbench] 新建会话失败：工作区创建失败：", pd, err);
				notify("New session failed: workspace creation failed (see the console for details)", pk);
			});
			if (!ws) {
				console.error("[workbench] 新建会话失败：项目无对应工作区且无法创建：", pk, pd);
				notify("New session failed: the project main directory is not registered as a workspace", pk);
				return;
			}
			startWorkspaceSession(ws.workspaceId);
			const staged = await waitForStaged(sessions, (() => {
				try {
					return sessions.list.getSnapshot()?.current ?? null;
				} catch {
					return null;
				}
			})(), 1e4);
			if (!staged) {
				console.warn("[workbench] 新建会话：staging 未落定（current 未更新）；工作区已连接，可从列表进入：", ws.workspaceId);
				notify("Session open timed out: the list has not synced yet, retry later", pk);
				return;
			}
			const base = backfillProjectSeqs(getLedgerSnapshot());
			const counters = readSeqCounters();
			const seq = nextProjectSeq(base, pk, counters[pk], getClosedSnapshot());
			writeSeqCounters({
				...counters,
				[pk]: seq
			});
			persist(touchEntry(base, {
				id: staged,
				project: pk,
				cwd: pd ?? "",
				lastOpenedAt: Date.now(),
				seq
			}));
			try {
				await pushSessionEntry({
					id: staged,
					project: pk,
					cwd: pd ?? "",
					lastOpenedAt: Date.now()
				});
			} catch (err) {
				console.error("[workbench] registering the session into the project ledger file failed (the session was created; the local entry works):", err);
				notify("Session could not be registered into the project ledger file (see the console); the session was created normally", pk);
			}
			await injectSessionCharter(sessions, staged, pk, notify);
		} catch (err) {
			console.error("[workbench] 新建会话请求异常：", err);
			notify("New session failed: request error (see the console for details)", pk);
		} finally {
			setCreating(false);
		}
	}, [
		workspaces,
		sessions,
		projectKey,
		projectDir,
		creating,
		persist,
		notify,
		startWorkspaceSession
	]);
	const closedList = (0, react.useSyncExternalStore)(subscribeClosed, getClosedSnapshot);
	return {
		ledger,
		creating,
		entryNotice,
		noticeProject,
		handleNew,
		handleOpen,
		handleClose: (0, react.useCallback)((id) => {
			const entry = ledger.find((e) => e.id === id);
			persist(removeEntry(ledger, id));
			if (entry) persistClosed(pushClosedLedger(getClosedSnapshot(), entry));
			if (typeof sessions.close === "function") try {
				sessions.close(id);
			} catch (err) {
				console.warn("[workbench] 关闭会话：sessions.close 调用失败（入口已剔除，会话数据不受影响）：", id, err);
			}
		}, [
			ledger,
			persist,
			sessions
		]),
		closedList,
		listState
	};
}
//#endregion
//#region src/shared/session-handle.ts
/** Placeholder for an empty/unusable id (visible, clearly not a real code). */
const HANDLE_PLACEHOLDER = "----";
/** Lowercase-alphanumeric tail characters used by the beyond-6 fallback. */
function tail4(id) {
	return id.replace(/[^0-9a-zA-Z]/g, "").slice(-4) || "0000";
}
/**
* Derive the display handle for one session id.
* @param id session uuid as carried by the ledger (`session-…`) — never empty in
*        practice, but tolerated (placeholder).
* @param taken handles already used in the same project (read-only).
*/
function sessionHandle(id, taken = []) {
	if (typeof id !== "string" || id.length === 0) return HANDLE_PLACEHOLDER;
	const body = id.startsWith("session-") ? id.slice(8) : id;
	const hex = body.replace(/[^0-9a-fA-F]/g, "");
	if (hex.length === 0) return HANDLE_PLACEHOLDER;
	const lower = hex.toLowerCase();
	const takenSet = new Set(taken);
	for (const width of [4, 6]) {
		const candidate = lower.slice(0, width);
		if (!takenSet.has(candidate)) return candidate;
	}
	const suffix = `${lower.slice(0, 6)}-${tail4(body.toLowerCase())}`;
	return takenSet.has(suffix) ? `${suffix}-${tail4(lower + body.toLowerCase())}` : suffix;
}
//#endregion
//#region src/shared/project-identity.ts
/**
* project-identity.ts — single-source pure module for the project identity badge
* (console-ui epic item UI-4, t261005-05). One project = one badge
* (12 colours x 6 uncommon outlines x 3 structures) + one project colour, and the
* left column and the panel render the SAME identity for that project.
*
* Declared truth (this module implements declared values, invents nothing):
* - palette / outlines / structures = the settled spec (§2.4) in the 261004 chat
*   identity design note under notes/discussions/ (filename carries CJK by design);
* - geometry is ported verbatim from mock `261004-concurrency-limit-mock.html` v11
*   (`glyphPath` / `shapeSVG`, including the ring's centre-scaled hole and half's
*   right-side clip).
*
* Two declared deviations from the mock (borrowed-implementation tradeoffs, auditable):
* (a) the mock builds mask/clip ids with `Math.random()` — this module derives a
*     deterministic id from identity+size (SSR/snapshot safe; equal ids always carry
*     byte-equal content, so duplicate references in one document have no visual drift);
* (b) the mock hardcodes per-project `PROJ_SHAPE`/`PROJ_COLOR` maps — this module
*     replaces them with the deterministic rule "two hash streams pick the preferred
*     triple + dedupe over the known project set" (ticket requirement: an undeclared
*     project still gets a stable, distinct identity, unchanged across restarts).
*     The `projects.yaml` `color`/`shape` override is an approved upgrade path whose
*     parser lives in server/project-registry.ts (outside this ticket's write set) —
*     recorded as debt for a follow-up ticket, not implemented here.
*
* Tradeoffs vs project-color.ts:
* - the hash REUSES fnv1a (FNV-1a + murmur3 finalizer; plain FNV lacked low-bit
*   avalanche and collided the first real pair suyou/sandbar — see that module's old
*   header; this module does not regress to a plain FNV stream);
* - the palette upgrades to the declared 12 colours (PROJECT_PALETTE_12);
*   project-color.ts re-exports from here — single-source rule: the palette is
*   declared exactly once, in this file.
*
* Malformed-input fallback follows the existing discipline: a non-key gets the grey
* pentagon-solid identity, never a throw.
*/
/**
* This module is self-contained (zero module imports): project-color.ts re-exports
* this module's palette/hash/fallback colour, and the panel page embeds these same
* functions via String(fn) — one source, no drift, no import cycle.
*/
/** Palette: 12 colours (verbatim from mock v11 `PALETTE12`; hues about 30 degrees
*  apart, s about 0.72 / l about 0.66). Declared values win: their measured minimum
*  pairwise hue-ring gap is 19.2 degrees, so the old 10-colour palette's >=20 degree
*  criterion is re-anchored (see smoke/project-color.mjs) rather than bending the
*  declared values to keep a derived number. */
const PROJECT_PALETTE_12 = [
	"#e76a6a",
	"#e7936a",
	"#e7c36a",
	"#c6e76a",
	"#8ae76a",
	"#6ae79c",
	"#6ae7d4",
	"#6aabe7",
	"#7f6ae7",
	"#b56ae7",
	"#e76ad0",
	"#e76a92"
];
/** Fallback colour for malformed input / unattributable projects (neutral grey;
*  true source moved here, project-color.ts re-exports it). */
const FALLBACK_COLOR = "#9ca3af";
/** Outline set (uncommon shapes; deliberately avoids dots/squares/triangles that
*  read as controls — design note §2.4). */
const IDENTITY_OUTLINES = [
	"pentagon",
	"hexagon",
	"octagon",
	"shield",
	"sparkle",
	"tag"
];
/** Structure set: solid / ring (centre-scaled hole) / half (55% base + right half at 100%). */
const IDENTITY_STRUCTURES = [
	"solid",
	"ring",
	"half"
];
/** Fallback identity for malformed keys (neutral grey + plainest shape = "unset"). */
const FALLBACK_IDENTITY = {
	color: FALLBACK_COLOR,
	outline: "pentagon",
	structure: "solid"
};
/** Salt for the second hash stream (independent of the first; changing it reshuffles
*  every identity — think before changing). */
const STREAM2_SALT = "\0wb-identity";
/** Key length cap (longer is treated as malformed; project keys are short ids). */
const KEY_MAX_LEN = 64;
/** FNV-1a 32bit hash + murmur3 finalizer (moved here from project-color.ts in
*  t261005-05: plain FNV lacked low-bit avalanche and the first real registry pair
*  suyou/sandbar landed in one slot — the finalizer separates them). Known vectors
*  are locked by smoke/project-color.mjs; do not hand-tune. */
function fnv1a(input) {
	let h = 2166136261;
	for (let i = 0; i < input.length; i++) {
		h ^= input.charCodeAt(i);
		h = Math.imul(h, 16777619);
	}
	h ^= h >>> 16;
	h = Math.imul(h, 2246822507);
	h ^= h >>> 13;
	h = Math.imul(h, 3266489909);
	h ^= h >>> 16;
	return h >>> 0;
}
/** Project key validity face (loose whitelist: non-empty, <=64, no control chars —
*  the UI renders this text, so it stays display-safe). */
function isProjectKeyLike(key) {
	return typeof key === "string" && key.length > 0 && key.length <= KEY_MAX_LEN && !/[\u0000-\u001f\u007f]/.test(key);
}
/** Preferred triple for one key, no dedupe (set dedupe lives in projectIdentity).
*  Exported only as the panel page's String(fn) embed seam, not a standalone API. */
function baseIdentity(key) {
	const h1 = fnv1a(key);
	const h2 = fnv1a(key + STREAM2_SALT);
	return {
		color: PROJECT_PALETTE_12[h1 % PROJECT_PALETTE_12.length],
		outline: IDENTITY_OUTLINES[h2 % IDENTITY_OUTLINES.length],
		structure: IDENTITY_STRUCTURES[(h1 >>> 9) % IDENTITY_STRUCTURES.length]
	};
}
/** Dedupe key of a triple (a collision needs all three channels equal).
*  Export reason same as baseIdentity (embed seam). */
function identityId(id) {
	return `${id.color}|${id.outline}|${id.structure}`;
}
/**
* Project key -> identity. Same key, same value, always (pure function; the
* "unchanged across restarts" acceptance object).
*
* @param key project key (malformed -> FALLBACK_IDENTITY, never throws).
* @param knownKeys known project set (optional). When passed, dedupe runs in sorted
*        order, first come first served: a later colliding project walks the ring
*        (colour+1, outline+1, structure+1) to the first free slot — the deterministic
*        implementation of design-note §2.4 "preferred pair + dedupe over the known
*        project set". The two consumers (sidebar registry / panel project root) each
*        pass their own set; the extreme divergence that different sets could cause is
*        watched by the collision assertions in tests/project-identity.mjs.
*/
function projectIdentity(key, knownKeys) {
	if (!isProjectKeyLike(key)) return FALLBACK_IDENTITY;
	const k = key;
	const base = baseIdentity(k);
	if (!Array.isArray(knownKeys) || knownKeys.length === 0) return base;
	const valid = Array.from(new Set(knownKeys)).filter(isProjectKeyLike).sort();
	if (!valid.includes(k)) return base;
	const taken = /* @__PURE__ */ new Set();
	let result = base;
	for (const v of valid) {
		const cand = baseIdentity(v);
		result = taken.has(identityId(cand)) ? walkOffset(cand, taken) : cand;
		taken.add(identityId(result));
		if (v === k) break;
	}
	return result;
}
/** Ring walk from a triple to the first slot not in `taken` (colour+1, outline+1,
*  structure+1 per step; the 216 space cannot fill for a <=41-char key set).
*  Export reason same as baseIdentity (panel page embed seam). */
function walkOffset(base, taken) {
	const ci = PROJECT_PALETTE_12.indexOf(base.color);
	const oi = IDENTITY_OUTLINES.indexOf(base.outline);
	const si = IDENTITY_STRUCTURES.indexOf(base.structure);
	for (let n = 1; n < PROJECT_PALETTE_12.length * IDENTITY_OUTLINES.length; n++) {
		const cand = {
			color: PROJECT_PALETTE_12[(ci + n) % PROJECT_PALETTE_12.length],
			outline: IDENTITY_OUTLINES[(oi + n) % IDENTITY_OUTLINES.length],
			structure: IDENTITY_STRUCTURES[(si + n) % IDENTITY_STRUCTURES.length]
		};
		if (!taken.has(identityId(cand))) return cand;
	}
	return base;
}
/**
* SVG path for an outline (mock `glyphPath` ported verbatim; size = viewBox edge).
* An unknown outline name falls back to pentagon (malformed-enum fallback, no throw).
*/
function identityOutlinePath(name, size) {
	const S = size;
	const c = S / 2;
	const R = S * .47;
	const R2 = S * .3;
	const polyPath = (n, rot) => {
		const pts = [];
		for (let k = 0; k < n; k++) {
			const a = rot + k * 2 * Math.PI / n;
			pts.push(`${(c + R * Math.cos(a)).toFixed(2)},${(c + R * Math.sin(a)).toFixed(2)}`);
		}
		return `M${pts.join(" L")} Z`;
	};
	if (name === "hexagon") return polyPath(6, -Math.PI / 2 + Math.PI / 6);
	if (name === "octagon") return polyPath(8, -Math.PI / 2 + Math.PI / 8);
	if (name === "shield") {
		const t = S * .08, b = S * .94;
		return `M${S * .14} ${t} H${S * .86} V${S * .52} Q${S * .86} ${b} ${c} ${b} Q${S * .14} ${b} ${S * .14} ${S * .52} Z`;
	}
	if (name === "sparkle") {
		const p = [];
		for (let k = 0; k < 8; k++) {
			const r = k % 2 === 0 ? R : R2;
			const a = -Math.PI / 2 + k * Math.PI / 4;
			p.push(`${(c + r * Math.cos(a)).toFixed(2)},${(c + r * Math.sin(a)).toFixed(2)}`);
		}
		return `M${p.join(" L")} Z`;
	}
	if (name === "tag") return `M${S * .12} ${S * .12} H${S * .66} L${S * .88} ${S * .34} V${S * .88} H${S * .12} Z`;
	return polyPath(5, -Math.PI / 2 + Math.PI / 5);
}
/**
* Badge SVG text (mock `shapeSVG` port). ring = centre-scaled 0.46 hole (mask);
* half = same colour at 55% base + right half at 100% (clipPath). Design note §2.4:
* thin-pointed shapes like sparkle degrade to solid below 12px (no hole that size
* cannot hold).
*
* Deterministic id (deviation (a) in the header): derived from identity+size by
* default. Two badges with the same identity and size in one document share an id —
* their content is byte-equal, so either definition renders identically.
*/
function identityBadgeSvg(identity, size, uid) {
	const structure = identity.structure === "ring" && size < 12 && identity.outline === "sparkle" ? "solid" : identity.structure;
	const d = identityOutlinePath(identity.outline, size);
	const id = uid ?? `wbid${fnv1a(`${identity.color}|${identity.outline}|${structure}|${size}`).toString(36)}`;
	const wrap = (inner) => `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="flex:0 0 auto;display:block" aria-hidden="true">${inner}</svg>`;
	if (structure === "ring") {
		const c = size / 2;
		return wrap(`<mask id="${id}"><rect x="0" y="0" width="${size}" height="${size}" fill="#fff"/><g transform="translate(${c},${c}) scale(0.46) translate(${-c},${-c})"><path d="${d}" fill="#000"/></g></mask><path d="${d}" fill="${identity.color}" mask="url(#${id})"/>`);
	}
	if (structure === "half") {
		const c = size / 2;
		return wrap(`<defs><clipPath id="${id}"><path d="${d}"/></clipPath></defs><path d="${d}" fill="${identity.color}" fill-opacity="0.55"/><rect x="${c}" y="0" width="${c}" height="${size}" fill="${identity.color}" clip-path="url(#${id})"/>`);
	}
	return wrap(`<path d="${d}" fill="${identity.color}"/>`);
}
/**
* Convenience entry: key -> badge SVG (malformed key -> fallback badge). Consumer
* size rules (design note §2.4): sidebar project row 14, session row 11, panel chip 13.
*/
function projectBadgeSvg(key, size, knownKeys) {
	return identityBadgeSvg(projectIdentity(key, knownKeys), size);
}
//#endregion
//#region src/shared/project-color.ts
/**
* 项目 key → 调色板色。同 key 任意次调用恒同值（纯函数，R3-a 验收对象）。
* 畸形 key → FALLBACK_COLOR，不 throw。
*/
function projectColor(key) {
	if (!isProjectKeyLike(key)) return FALLBACK_COLOR;
	return PROJECT_PALETTE_12[fnv1a(key) % PROJECT_PALETTE_12.length];
}
/**
* 生成 tag 样式 CSS 规则文本（注入 head 的自有 style 用；机制=属性锚 +
* CSS ::before/attr()，对 React 托管容器零 childList 侵入——t260903-07 方案 v2 R1）。
*
* @param keys 已知项目 key 集合（重复自动去重；畸形 key 跳过不产规则）。
* @returns 一段完整可注入的 CSS 文本（含基础规则 + 每项目着色规则）。
*          key 只出现在属性选择器与 content 文本里，含 `"`/`\` 的 key 已在
*          isProjectKeyLike 之外的这里再拦一层（双保险，防选择器注入）。
*/
function projectTagCssRules(keys) {
	const seen = /* @__PURE__ */ new Set();
	for (const k of keys) if (isProjectKeyLike(k) && !k.includes("\"") && !k.includes("\\")) seen.add(k);
	const rules = [[
		`[data-wb-projtag]::before{`,
		`content:attr(data-wb-projtag);`,
		`display:inline-block;`,
		`font-size:10px;line-height:1;padding:2px 6px;margin-right:6px;`,
		`border-radius:8px;border:1px solid transparent;`,
		`vertical-align:1px;`,
		`font-family:var(--ds-font-family-code,monospace);`,
		`white-space:nowrap;`,
		`}`
	].join("")];
	for (const k of seen) {
		const c = projectColor(k);
		const r = parseInt(c.slice(1, 3), 16);
		const g = parseInt(c.slice(3, 5), 16);
		const b = parseInt(c.slice(5, 7), 16);
		rules.push(`[data-wb-projtag="${k}"]::before{color:${c};border-color:${c}55;background:rgba(${r},${g},${b},0.16)}`);
	}
	return rules.join("\n");
}
//#endregion
//#region src/client/chat-project-band.ts
/**
* sandbar-workbench · 全局 chat 项目色带装饰器（票② R7，t260904-05）。
*
* 视觉：右栏 chat 滚动体顶部 border-top 3px 项目色横贯 + 右上角 sticky 零高
* 角标显项目 key（「色+名」双通道，10px 等宽同色，pointer-events:none）。
* 分工：色带管 **chat 归属**；chat-project-tag.ts（已上线）管**消息级工单
* 引用**，两者互不动。
*
* 渲染机制（对齐 chat-project-tag.ts 纪律，零 childList 侵入 React 托管容器）：
* 只给平台渲染的滚动体**设置自有属性** `data-wb-chat-projband="<projectKey>"`，
* 视觉全在注入 head 的自有 <style> 里（CSS 属性选择器 + ::after attr() 出角标
* 文本与着色）。插件卸载时 style 元素与全部自有属性摘除，出厂树恢复原样。
* 平台锚=chat 滚动体自声明属性 `[data-conversation-scroll]`（出处：安装树
* dsh-client-ui-conversation/lib/client.js 6 处实锤，ConversationRoot 滚动体；
* 非 css-module 哈希类，勿用类名锚）。
*
* 归属判定**不在本模块**：装饰器只吃显式入参 setChatProjectBand(key|null)，
* 推导在 sidebar.tsx（listState.current → 账册 project 查表）。不在册（工单
* 会话/磁盘存量/blank hero）→ null=摘属性不渲染——声明行为，不造隐形缺省。
*
* ── 故障模式取舍清单（对照 chat-project-tag.ts 头注 9 项范式展开为 10 项，
*    逐项「带/不带」+理由）──
* 1. ✅ 锚丢失显式降级（分层）：document 失联（isConnected=false）=永久停手，
*    断 Observer + warn 一次（同 tag）；**锚 0 命中=瞬态常态**（blank hero /
*    会话卸载时滚动体不在场，开 chat 后回归）——本轮回调摘全部已设属性即停手，
*    Observer 保持连接，锚再现时下一轮回调自然重设（C4 修订：不得断 Observer，
*    否则 hero↔chat 切换后色带永久失明）。0 锚不 warn（常态不噪音）。
* 2. ✅ 负向排除：**声明不需要**——本模块零自铸 DOM 入 React 树（仅 head 里
*    一个 style），插件任何节点不可能命中平台自声明属性 [data-conversation-scroll]，
*    误伤面不存在；此结论即声明（OWN_SUBTREE_MARKER 教训的对照面）。
* 3. ✅ F1 防呆接线：startChatProjectBandEffect 返回清理函数本身，sidebar 以
*    `useEffect(() => startChatProjectBandEffect(...), [])` 接线——直接返回
*    handle 会被 useEffect 静默忽略→卸载零回收（t260903-07 F1 实案）。
* 4. ✅ 注入防线（attr()-only 免疫）：key 只进属性值与 ::after 的 attr()
*    content，**不拼进 CSS 选择器**——引号/反斜杠等字符无注入面（比 tag 的
*    选择器引号双保险更强的免疫设计，差异声明）；生产闸门另设：set 前过
*    isProjectKeyLike（畸形→按 null 摘除），账册是 localStorage 外部输入。
* 5. ✅ 多锚语义：命中 N 个=全部设同属性（平台滚动体应唯一，N>1 属异常但齐设
*    无害）；命中 0 个=见第 1 项。无「首个」偏好。
* 6. ✅ 畸形 key 生产闸门：见第 4 项 isProjectKeyLike；smoke 另带 localStorage
*    手改坏 project 用例（畸形输入用例纪律，桩复现不靠真外部源）。
* 7. ✅ 幂等先查再设：属性同值跳过、style 文本同值跳过、key=null 且无属性时
*    跳过——React 重渲染/Observer 回调反复触发不抖。
* 8. ✅ MutationObserver 防重建：body 子树 childList（同 tag/metrics-entry
*    先例），React 重建滚动体后重设属性；attributes 不盯（自有属性无人动）。
* 9. Full-terminal-state cleanup: stop() is idempotent = disconnect the
*    Observer + remove the head style + remove every self-set attribute (only
*    our own) + remove the band overlay element and the window-level
*    scroll/resize listeners + warn on degraded paths.
* 10. Body-level overlay pinned to the anchor rect: carried since UI-5
*     (t261005-06 identity band) - the standing band of design 2.1 (14% band
*     face + 3px bottom border + project key + handle + Sessions menu) needs
*     an interactive element; a pure ::after cannot hold one. The overlay
*     hangs off body (no child inserted into the React-managed subtree, so
*     the zero-childList-intrusion discipline holds), position:fixed over the
*     anchor rect, updated on capture scroll + resize (listeners fully
*     cleaned up). Degradation: zero anchors = the overlay hides
*     (display:none); it never disappears silently nor escapes the column.
*/
/** 自有属性名（值=project key）。 */
const PROJBAND_ATTR = "data-wb-chat-projband";
/** Session-handle attribute (UI-5: the band's second text channel; value = short code or executor). */
const PROJBAND_HANDLE_ATTR = "data-wb-chat-projband-handle";
/** Identity-band overlay attribute (body-level element marker; value = project key). */
const PROJBAND_BAND_ATTR = "data-wb-chat-band";
/** 自有 style 元素选择器（head 内，React 树之外）。 */
const STYLE_SELECTOR$1 = "style[data-wb-chat-projband-style]";
/** 平台 chat 滚动体锚（出处见文件头注；平台自声明属性，非 css-module 类名）。 */
const SCROLL_SELECTOR$1 = "[data-conversation-scroll]";
/** hex → rgba() 字符串（16% 透明底等用途；避免 color-mix 兼容性赌注）。 */
function hexToRgba(hex, alpha) {
	return `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${alpha})`;
}
/** Band base styles (self-owned style injected into head; attr()-only, the
*  key never enters a selector). UI-5 upgrade: the three design-2.1 channels
*  all hang off the one --wb-projband-color variable - the 3px top border
*  (the old band face), the 5% column wash (background color-mix) and the
*  corner tag color (::after), so one project switch moves all three in the
*  same frame (integration scenario A4 contract: hits >= 3). */
const PROJBAND_BASE_CSS = `
[${PROJBAND_ATTR}] { border-top: 3px solid var(--wb-projband-color, transparent); position: relative;
  background: color-mix(in srgb, var(--wb-projband-color, transparent) 5%, transparent); }
[${PROJBAND_ATTR}]::after {
  content: attr(${PROJBAND_HANDLE_ATTR}) " \\00b7 " attr(${PROJBAND_ATTR});
  position: sticky; top: 0; float: right; margin-right: 8px; height: 0;
  display: block; font-size: 10px; line-height: 1.4; white-space: nowrap;
  font-family: var(--ds-font-family-code, monospace);
  color: var(--wb-projband-color, transparent);
  pointer-events: none; opacity: 0.9;
}
[${PROJBAND_ATTR}]:not([${PROJBAND_HANDLE_ATTR}])::after { content: attr(${PROJBAND_ATTR}); }
`;
/**
* Identity-band overlay styles (design 2.1: a 32px band face at 14% project
* color + a 3px solid bottom border + a 9px color chip + the project key +
* the handle + a Sessions control; fixed over the anchor rect, zero anchors =
* hidden).
*/
const PROJBAND_BAND_CSS = `
[${PROJBAND_BAND_ATTR}] { position: fixed; z-index: 90; height: 32px;
  display: flex; align-items: center; gap: 6px; padding: 0 10px;
  background: color-mix(in srgb, var(--wb-projband-color, transparent) 14%, var(--dsw-alias-bg-primary, #fff));
  border-bottom: 3px solid var(--wb-projband-color, transparent);
  font-size: 12px; font-weight: 600; pointer-events: auto; }
[${PROJBAND_BAND_ATTR}][data-hidden] { display: none; }
[${PROJBAND_BAND_ATTR}] .wb-projband-chip { width: 9px; height: 9px; flex: none;
  background: var(--wb-projband-color, transparent); }
[${PROJBAND_BAND_ATTR}] .wb-projband-key { font-weight: 600; }
[${PROJBAND_BAND_ATTR}] .wb-projband-handle { font-family: var(--ds-font-family-code, monospace);
  font-size: 11px; font-weight: 400; opacity: 0.75; }
[${PROJBAND_BAND_ATTR}] .wb-projband-sessions { font: inherit; font-size: 11px;
  font-weight: 400; padding: 2px 8px; cursor: pointer; border-radius: 4px;
  border: 1px solid var(--wb-projband-color, transparent); background: none; }
[${PROJBAND_BAND_ATTR}] .wb-projband-menu { position: absolute; top: 34px; right: 0;
  min-width: 180px; max-height: 240px; overflow-y: auto; padding: 4px;
  border-radius: 6px; background: var(--dsw-alias-bg-primary, #fff);
  border: 1px solid var(--wb-projband-color, transparent);
  box-shadow: 0 8px 24px rgba(0,0,0,0.35); display: none; }
[${PROJBAND_BAND_ATTR}][data-menu-open] .wb-projband-menu { display: block; }
[${PROJBAND_BAND_ATTR}] .wb-projband-item { display: flex; align-items: center; gap: 6px;
  width: 100%; padding: 3px 6px; font: inherit; font-size: 11.5px; cursor: pointer;
  border: none; background: none; text-align: left; border-radius: 4px; }
[${PROJBAND_BAND_ATTR}] .wb-projband-item:hover { background: rgba(127,127,127,0.15); }
[${PROJBAND_BAND_ATTR}] .wb-projband-item .wb-projband-handle { flex: none; }
[${PROJBAND_BAND_ATTR}] .wb-projband-new { color: var(--wb-projband-color, inherit);
  border-top: 1px solid rgba(127,127,127,0.25); margin-top: 2px; }
`;
/**
* 设/摘色带属性（纯 DOM 逻辑，smoke 用自有桩直测；幂等）。key=null/畸形=
* removal (not-in-ledger renders nothing, declared behavior; the handle
* attribute goes with it). Returns the number of nodes actually written this
* call (for observation). All N anchors are set together (header item 5).
*/
function applyProjectBand(root, key, handle) {
	let touched = 0;
	let els;
	try {
		els = Array.from(root.querySelectorAll(SCROLL_SELECTOR$1));
	} catch {
		return 0;
	}
	const valid = isProjectKeyLike(key) ? key : null;
	for (const el of els) {
		if (typeof el.setAttribute !== "function" || typeof el.getAttribute !== "function") continue;
		const cur = el.getAttribute(PROJBAND_ATTR);
		if (valid === null) {
			if (cur !== null || el.getAttribute("data-wb-chat-projband-handle") !== null) {
				el.removeAttribute(PROJBAND_ATTR);
				el.removeAttribute(PROJBAND_HANDLE_ATTR);
				touched++;
			}
			continue;
		}
		if (cur !== valid) {
			el.setAttribute(PROJBAND_ATTR, valid);
			if (typeof el.style?.setProperty === "function") el.style.setProperty("--wb-projband-color", projectColor(valid));
			touched++;
		}
		const hCur = el.getAttribute(PROJBAND_HANDLE_ATTR);
		const hNext = typeof handle === "string" && handle !== "" && !handle.includes("\"") ? handle : null;
		if (hNext === null) {
			if (hCur !== null) {
				el.removeAttribute(PROJBAND_HANDLE_ATTR);
				touched++;
			}
		} else if (hCur !== hNext) {
			el.setAttribute(PROJBAND_HANDLE_ATTR, hNext);
			touched++;
		}
	}
	return touched;
}
/**
* useEffect 形态入口（F1 防呆，见头注第 3 项）：返回清理函数本身。
*/
function startChatProjectBandEffect(opts = {}) {
	const h = startChatProjectBand(opts);
	return () => h.stop();
}
/** 当前活跃 handle（模块级单例引用；sidebar 的归属推导 effect 走下面这个
*  免实例透传入口，不必自己持有 handle——单插件单装饰器，多启后写后者）。 */
let active = null;
/** UI-5 entry: project ownership and the current session handle go out together (called by the sidebar after derivation). */
function setChatProjectBandInfo(info) {
	active?.setInfo(info);
}
/**
* Start the decorator: a self-owned style in head (the container attribute
* face + the identity-band overlay face) + a body-subtree childList Observer
* + a body-level overlay element (the design-2.1 band; pinned to the anchor
* rect, following capture scroll + resize, listeners and element fully
* cleaned up). Returns a handle: set/setInfo for the sidebar ownership
* derivation; stop() is mandatory on unload.
*/
function startChatProjectBand(opts = {}) {
	const doc = opts.doc ?? (typeof document !== "undefined" ? document : null);
	if (!doc || doc.documentElement === null) {
		console.warn("[workbench] chat project-band decorator has no document to attach to; soft-degrade, nothing renders");
		return {
			set() {},
			setInfo() {},
			stop() {}
		};
	}
	let style = doc.querySelector(STYLE_SELECTOR$1);
	if (style === null) {
		style = doc.createElement("style");
		style.setAttribute("data-wb-chat-projband-style", "");
		doc.head.appendChild(style);
	}
	const fullCss = PROJBAND_BASE_CSS + "\n" + PROJBAND_BAND_CSS;
	if (style.textContent !== fullCss) style.textContent = fullCss;
	let current = null;
	let currentHandle = void 0;
	let stopped = false;
	let warnedDisconnected = false;
	let band = null;
	if (typeof doc.createElement === "function" && !!doc.body && typeof doc.body.appendChild === "function") try {
		band = doc.createElement("div");
		band.setAttribute(PROJBAND_BAND_ATTR, "");
		if (typeof opts.getSessions === "function") {
			const btn = doc.createElement("button");
			btn.className = "wb-projband-sessions";
			btn.setAttribute("data-wb-band-sessions", "");
			btn.setAttribute("type", "button");
			btn.textContent = "Sessions";
			btn.addEventListener?.("click", (ev) => {
				ev.stopPropagation();
				if (!band) return;
				if (band.getAttribute("data-menu-open") !== null) {
					band.removeAttribute("data-menu-open");
					return;
				}
				renderMenu();
				band.setAttribute("data-menu-open", "");
			});
			band.appendChild(btn);
			const menu = doc.createElement("div");
			menu.className = "wb-projband-menu";
			menu.setAttribute("data-wb-band-menu", "");
			band.appendChild(menu);
		}
		doc.body.appendChild(band);
	} catch {
		band = null;
	}
	/** Redraw the menu content (called when opening; data from getSessions/onOpenSession/onNewSession). */
	const renderMenu = () => {
		if (!band) return;
		const menu = band.querySelector("[data-wb-band-menu]");
		if (!menu) return;
		menu.textContent = "";
		const items = typeof opts.getSessions === "function" ? opts.getSessions() : [];
		for (const it of Array.isArray(items) ? items : []) {
			if (!it || typeof it.id !== "string" || it.id === "") continue;
			if (typeof opts.onOpenSession !== "function") break;
			const row = doc.createElement("button");
			row.className = "wb-projband-item";
			row.setAttribute("data-wb-band-item", it.id);
			row.setAttribute("type", "button");
			const h = doc.createElement("span");
			h.className = "wb-projband-handle";
			h.textContent = it.handle;
			const t = doc.createElement("span");
			t.textContent = it.title;
			if (typeof it.rawTitle === "string" && it.rawTitle !== "" && it.rawTitle !== it.title) row.setAttribute("title", it.rawTitle);
			row.appendChild(h);
			row.appendChild(t);
			if (it.active) row.setAttribute("data-active", "");
			row.addEventListener?.("click", (ev) => {
				ev.stopPropagation();
				band?.removeAttribute("data-menu-open");
				opts.onOpenSession?.(it.id);
			});
			menu.appendChild(row);
		}
		if (typeof opts.onNewSession === "function") {
			const nw = doc.createElement("button");
			nw.className = "wb-projband-item wb-projband-new";
			nw.setAttribute("data-wb-band-new", "");
			nw.setAttribute("type", "button");
			nw.textContent = "+ New session";
			nw.addEventListener?.("click", (ev) => {
				ev.stopPropagation();
				band?.removeAttribute("data-menu-open");
				opts.onNewSession?.();
			});
			menu.appendChild(nw);
		}
	};
	/** The open menu collapses on an ownership switch (a cross-project menu shows the wrong project's data; collapsing is the safe side). */
	const closeMenu = () => {
		band?.removeAttribute("data-menu-open");
	};
	/** Pin the overlay to the anchor rect (zero anchors = hidden; a stub without getBoundingClientRect = best-effort top placement). */
	const placeBand = () => {
		if (!band) return;
		band.setAttribute(PROJBAND_BAND_ATTR, current ?? "");
		if (current === null) {
			band.setAttribute("data-hidden", "");
			return;
		}
		band.removeAttribute("data-hidden");
		const st = band.style;
		if (typeof st?.setProperty !== "function") return;
		const color = projectColor(current);
		st.setProperty("--wb-projband-color", color);
		let anchor;
		try {
			anchor = Array.from(doc.querySelectorAll(SCROLL_SELECTOR$1))[0];
		} catch {
			anchor = void 0;
		}
		const r = anchor?.getBoundingClientRect?.();
		if (r && typeof r.top === "number" && typeof r.left === "number" && typeof r.width === "number") {
			st.setProperty("top", `${Math.max(0, r.top)}px`);
			st.setProperty("left", `${r.left}px`);
			st.setProperty("width", `${r.width}px`);
		} else {
			st.setProperty("top", "0px");
			st.setProperty("left", "0px");
			st.removeProperty("width");
		}
	};
	const scan = () => {
		if (stopped) return;
		if (!doc.documentElement.isConnected) {
			if (!warnedDisconnected) {
				warnedDisconnected = true;
				console.warn("[workbench] chat 项目色带装饰器：document 已失联，停手（软退化不渲染）");
			}
			observer.disconnect();
			return;
		}
		applyProjectBand(doc, current, currentHandle);
		placeBand();
	};
	const observer = new MutationObserver(scan);
	observer.observe(doc.body ?? doc.documentElement, {
		childList: true,
		subtree: true
	});
	const onFollow = () => {
		if (!stopped) placeBand();
	};
	const win = typeof window !== "undefined" ? window : null;
	try {
		doc.addEventListener?.("scroll", onFollow, true);
		win?.addEventListener?.("resize", onFollow);
	} catch {}
	scan();
	const handle = {
		set(key) {
			current = isProjectKeyLike(key) ? key : null;
			currentHandle = void 0;
			closeMenu();
			scan();
		},
		setInfo(info) {
			const key = info?.project ?? null;
			const changed = (isProjectKeyLike(key) ? key : null) !== current;
			current = isProjectKeyLike(key) ? key : null;
			currentHandle = typeof info?.handle === "string" && info.handle !== "" ? info.handle : void 0;
			if (changed) closeMenu();
			scan();
		},
		stop() {
			if (stopped) return;
			stopped = true;
			if (active === handle) active = null;
			observer.disconnect();
			try {
				doc.removeEventListener?.("scroll", onFollow, true);
				win?.removeEventListener?.("resize", onFollow);
			} catch {}
			style.remove();
			try {
				band?.remove();
			} catch {}
			try {
				for (const el of Array.from(doc.querySelectorAll(`[${PROJBAND_ATTR}]`))) {
					el.removeAttribute(PROJBAND_ATTR);
					el.removeAttribute(PROJBAND_HANDLE_ATTR);
					if (typeof el.style?.removeProperty === "function") el.style.removeProperty("--wb-projband-color");
				}
			} catch {}
		}
	};
	active = handle;
	return handle;
}
//#endregion
//#region src/client/theme.ts
/**
* epic 徽标文字色：哈希装饰色向主题前景色方向调和（45%——acceptance 实测 65% 在 fallback 分支半透底链 4.21 压线、忠实深态最低槽 4.43 压线；45% 后全档两分支 ≥4.5），深浅两档下
* EPIC_PALETTE 全 10 档对比度达标（看守场景逐档断言）。`--epic-c` 由消费点
* 行内注入（epicColorOf 结果，纯函数不动）。
*/
function epicChipColor() {
	return "color-mix(in srgb, var(--epic-c, var(--dsw-derive-ink-strong, #9ca3af)) 30%, var(--dsw-derive-ink-strong, #24292f))";
}
/** 弱化文字（审批区 epicLine 等此前恒走 --wb-muted fallback 的点位，t260905-08 收编）。 */
function epicChipMuted() {
	return "var(--dsw-derive-muted, #888)";
}
/**
* :root 级派生令牌定义（注入各组件 CSS 常量头部；多组件各注入一份同值块，
* 重复定义无害，保证任一组件独立挂载时令牌都在场）。
*
* t261008-07 (A8b code-fault fix, arbitrate gen1 direction): the derive
* declarations are emitted at BOTH `:root` and `body[data-ds-dark-theme]`.
* A custom property whose value contains var() substitutes those inner
* references at the element where the property is DECLARED — so a :root-only
* declaration freezes every derive token on the light alias values even after
* the platform shell re-declares the aliases dark at body scope (the t260905-08
* guard documents body-level as the shell's real flip scope; probe: alias flips
* to #151517 at body, --dsw-derive-canvas stays #fff at every scope). The
* body-level copy makes color-mix recompute against the dark aliases inside
* the body subtree exactly when the shell has flipped it; the :root copy keeps
* every out-of-body mount (portal/slot) covered, and every var() consumer keeps
* its light fallback (unchanged discipline).
*/
const DERIVE_DECL = `
/* 文字系：基色 × 平台前景混色——浅档基色微加深（对比度↑），深档自动提亮 */
/* t260929-22 gen9 曾把 fg/muted/warn/ink-* 锁成「浅档深墨裸值」，理由是平台 label
   在浅底实测 rgb(122,122,133)≈4.24。该做法的代价在集测**暗档档位**上暴露：固定深墨落在
   暗底上整片不可读（t260905-08 contrast/dark 违例 375，首例 sidebar/wb-group-name
   1.21）。定值无法同时满足两档——平台浅档底与暗档底互斥，而能翻转的只有 label。
   故一律回到「深基色 P% × 平台 label」形态（与 main 既有形态同构，只把基色压深到
   两档都够）：浅档混出足够深的墨，暗档随 label 提亮。P 与基色由四档位 × 白底/四族淡底
   × 跨族淡底的 WCAG 模型定，悲观假设（浅档 label=真台中层灰）下最差 4.7~5.1、
   乐观假设（闸注入 label=#1f2328）下最差 6.1~7.4；暗档同面 6.0~8.8。 */
--dsw-derive-fg:color-mix(in srgb,#24292f 30%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-ink-blue:color-mix(in srgb,#0550ae 43%,var(--dsw-alias-label-primary,#1f2328));
/* muted/active 的旧基色（#57606a / #7c3aed）偏浅，任何比例都够不着 4.5——基色一并压深。 */
--dsw-derive-muted:color-mix(in srgb,#3d444d 42%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-border:var(--dsw-alias-border-l,#d0d7de);
--dsw-derive-canvas:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff));
--dsw-derive-surface:color-mix(in srgb,var(--dsw-alias-border-l,#d0d7de) 13%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-surface-2:color-mix(in srgb,var(--dsw-alias-border-l,#d0d7de) 26%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
/* t260929-22 直修（宿主令 260930，integration 执行）：accent/danger/success 三个**文字墨**
   的定值不够深。它们不只落在自家淡底上，还落在**跨族淡底**上——blocked 行卡底色是
   danger 12% 铺在旧平台面 #f5f8fa 上，而卡内的 wb-card-id 是蓝墨，实测 4.03。
   两个方向都试过：① 压深「基色」但保留与 --dsw-alias-label-primary 的混色（本改法）；
   ② 直接给浅档深墨定值——②在暗档必翻车（固定深墨落在暗底上不可读，闸的 light/dark 两个档位
   是分别注入两档平台令牌实测的）。故取 ①：浅档混出足够深的墨，暗档自动随 label 提亮。
   四档位 × 白底/三族淡底/跨族淡底全量模型（WCAG 相对亮度）最差：accent 5.06、danger 5.03、
   success 4.75；暗档同面 5.5~6.5。判据真源=integration/t260905-08 与 t260907-08（全 DOM
   扫描非抽样），改值后按四档位实跑复验。 */
--dsw-derive-accent:color-mix(in srgb,#033d8b 40%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-accent-solid:#1f6feb;
--dsw-derive-on-solid:#ffffff;
--dsw-derive-active:color-mix(in srgb,#5a2ea6 41%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-accent-deep:color-mix(in srgb,#0550ae 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-accent-bg:color-mix(in srgb,#0969da 12%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-accent-border:color-mix(in srgb,#0969da 42%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-danger:color-mix(in srgb,#8f1a20 38%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-danger-solid:#d1242f;
--dsw-derive-danger-bg:color-mix(in srgb,#cf222e 12%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-danger-border:color-mix(in srgb,#cf222e 40%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-success:color-mix(in srgb,#0f5323 40%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-success-deep:color-mix(in srgb,#116329 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-success-solid:#2da44e;
--dsw-derive-success-bg:color-mix(in srgb,#1a7f37 12%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-success-border:color-mix(in srgb,#1a7f37 42%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
/* t260929-22 gen5（对比度红 4.24<4.5）：warn 文字加深——基色换 warn-deep 家族的
   #7d4e00、alias 只作 30% 少数项（极性不定时混不出保证对比度，见 UT contrast-palette）。 */
--dsw-derive-warn:color-mix(in srgb,#7d4e00 46%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-ink-strong:color-mix(in srgb,#24292f 30%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-warn-deep:color-mix(in srgb,#7d4e00 45%,var(--dsw-alias-label-primary,#1f2328));
--dsw-derive-warn-bg:color-mix(in srgb,#eac54f 16%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
--dsw-derive-warn-border:color-mix(in srgb,#d4a72c 45%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
/* 固定暗面板：自备深底的表面（终端/代码块），前后景固定搭配不随平台翻转 */
--dsw-derive-dark-bg:#1e1e24;
--dsw-derive-dark-fg:#f0f3f6;
--dsw-derive-dark-muted:#b8b8c8;
--dsw-derive-dark-green:#7ee787;
--dsw-derive-dark-red:#f87171;
--dsw-derive-dark-amber:#ffd166;
--dsw-derive-dark-accent:#7ab8ff;
--dsw-derive-dark-warn-bg:#7a4a06;
--dsw-derive-dark-warn-fg:#ffe9c4;
/* 暗面板面位扩展（t260907-08）：docs 视图代码块（pre/.md-code/.md-cl/.md-copy）需要
 * 与 dark-bg 成对的边框/浮起面/悬停面三个面位——值取 GitHub Dark 系（与改造前
 * docs.tsx 写死值同源），搭配固定不翻转。登记理由：docs.tsx 令牌化时按消费点驱动
 * 盘点，既有 9 个 dark 令牌覆盖不了「面板内边框/浮起 chip」语义，缺才增（方案 §3）。 */
--dsw-derive-dark-border:#2a2f3a;
--dsw-derive-dark-surface:#21262d;
--dsw-derive-dark-surface-2:#30363d;
/* 老浏览器静态回退（t260915-08 仲裁修复，方向①）：warn/danger 底色令牌值为
 * color-mix(...)——不支持的浏览器（Chrome<111）上 var 替换 IACVT=底色透明，
 * 「等你=黄调行」在该类浏览器瞎掉。@supports not 分档在**令牌声明位**直接覆盖
 * 为静态色（hex-clean 看守 allowlist C 合法位），消费位 var() 零改动即两档自适应：
 * 新浏览器吃上方 color-mix 令牌，老浏览器吃本块静态色。探针用 currentcolor（无 hex）。
 * 本块随 DERIVE_TOKENS_CSS 多组件各注入一份，同值重复定义无害。 */
@supports not (background: color-mix(in srgb, currentcolor, currentcolor)) {
  :root{
  --dsw-derive-warn-bg:#fff8c5;
  --dsw-derive-danger-bg:#ffebe9;
  }
  body[data-ds-dark-theme]{
  --dsw-derive-warn-bg:#fff8c5;
  --dsw-derive-danger-bg:#ffebe9;
  }
}`;
const DERIVE_TOKENS_CSS = `:root{${DERIVE_DECL}}
body[data-ds-dark-theme]{${DERIVE_DECL}}`;
//#endregion
//#region src/client/project-session-row.tsx
/**
* sandbar-workbench · 项目内会话区（session-entry 第 3 面①，R1–R6）。
*
* 口径真源 notes/epics/session-entry.md（R1–R6 + 拍板 1/2/3）：
*   - R1 位置：左栏项目组头之下、工单列表之上，一横排；随项目组折叠整体隐藏
*     （挂载点在 sidebar.tsx 的 !collapsed 分支内，折叠=整组收起同隐）。
*   - R2 形态：正方形「+」钮 + 正方形数字 tab（编号=项目内登记顺序 seq，关闭
*     不回收，序列可有洞）；数量不限（无 limit），超宽 flex-wrap 换行不横滚。
*   - R3 新建：onNew → useSessionEntry 的 handleNew({key,dir}) 工厂同款链
*     （绑工作区+复用 blank+正确打开），落点=本组项目主目录。
*   - R4 切换：点 tab → handleOpen 统一链（平台单 current 语义）。
*   - R5 关闭：关闭钮 → 轻量确认弹层（插件内，不用原生 confirm），文案含编号
*     与标题、明示「仅关闭入口不删内容」；确认走既有 handleClose（剔入口+入
*     最近关闭，不删会话数据）；取消不动。
*   - R6 高亮：active = id === current（与顶部行同源；current 全局唯一 → 至多
*     一个 tab 高亮；current 为工单/未入账会话时全不亮）。
*
* 数据：账册按 project 过滤消费（pickProjectTabs 纯函数，shared/sessions.ts）；
* 本组件零 IO、零出厂 DOM 接触——动作全部由 sidebar.tsx 的 useSessionEntry
* 二号实例注入（账册=模块级共享 store，两实例同帧一致）。
*
* 确认弹层定位（review C1 修订；旧恢复菜单已随票② R8 退役，定位模式沿革记此）：
* 旧恢复菜单挂在 .wb-sb-left（无滚动祖先，absolute 自由溢出）；本行挂在 .wb-ticket-list 内
* （overflow-y:auto 滚动容器——CSS 一轴 auto 另一轴计算为 auto，absolute 弹层
* 会被裁剪）。故弹层走 position:fixed 脱离滚动容器裁剪 + 视口钳制（左右不出界、
* 底部放不下向上翻），列表滚动时经 capture scroll 监听跟随锚重摆。点外/Esc
* 收起（document listener，effect cleanup 全终态回收——正常收起/卸载/换确认
* 目标三条路径都摘干净）。
*
* 语义锚（smoke/project-sessions.mjs 源文本断言面）：data-wb-psess-row（根）、
* data-wb-psess-new（+ 钮）、data-wb-psess-tab[data-active]（tab）、
* data-wb-psess-close（tab 关闭钮）、data-wb-psess-confirm（确认弹层）、
* data-wb-psess-confirm-ok / -confirm-cancel（确认/取消）、
* data-wb-psess-notice（行内失败提示）。零 CSS 类名匹配纪律（自有 .wb-psess-*
* 前缀，与出厂类名零交叉）。
*
* UI-5 (t261005-06): the tab's main label is the session-handle short code
* (seq stays history-only); the executor session (fixed handle executor)
* enters this row's data through the session-ledger-file grants-merge door
* (derived display; the grants file stays the single source of who runs).
*/
const PSESS_STYLES = `${DERIVE_TOKENS_CSS}
.wb-psess { display:flex; flex-wrap:wrap; align-items:center; gap:4px;
  padding:4px 8px 4px 20px; border-bottom:1px solid rgba(255,255,255,0.04); }
/* UI-4 (t261005-05): 11px identity badge on the session row (inline svg, flex-aligned). */
.wb-psess-badge { display:inline-flex; align-items:center; flex:none; line-height:0; }
/* 项目色（票② R7 拍板 5）：色源=--wb-psess-color（根节点 inline 注入，
 * 值=projectColor(projectKey) 确定性色板）；淡底由 JS 用同色 16% 透明展开。 */
.wb-psess-new { box-sizing:border-box; width:24px; height:24px; flex:none;
  display:flex; align-items:center; justify-content:center; font:inherit;
  font-size:13px; line-height:1; padding:0; border-radius:4px;
  border:1px solid color-mix(in srgb,var(--wb-psess-color, var(--dsw-alias-label-primary,#1f2328)) 55%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); background:none;
  /* t260929-22 gen8 回归锁定派生（t260904-05 t3 契约未被宿主签发重归属）：45% 混
     平台前景公式原样保留；该派生在 180px 台实测 2.64<4.5，与对比度纪律不可两全，
     已按仲裁指引升级 DESIGN-CONFLICT（数学证明见 integration/t260929-22/）。 */
  color:color-mix(in srgb,var(--wb-psess-color, var(--dsw-alias-label-primary,#1f2328)) 45%,var(--dsw-alias-label-primary,#1f2328)); cursor:pointer; }
.wb-psess-new:hover:not(:disabled) { background:var(--wb-psess-hover, rgba(255,255,255,0.1)); }
/* 空态可发现性（t260906-01）：账册为空时 24px 无字小方块不可认出——换带文字
 * 「＋ 新建会话」按钮（auto 宽 + padding）；有 tab 后回落小方块形态。同锚
 * data-wb-psess-new 不变。 */
.wb-psess-new.wb-psess-new-labeled { width:auto; height:22px; padding:0 8px;
  gap:4px; font-size:11.5px; }
.wb-psess-new:disabled { cursor:default; color:var(--dsw-derive-muted,#57606a); background:var(--dsw-derive-surface,#f6f8fa); }
.wb-psess-tab { box-sizing:border-box; position:relative; min-width:24px;
  height:24px; flex:none; display:inline-flex; align-items:center;
  justify-content:center; padding:0 3px; border-radius:4px;
  border:1px solid transparent; background:none;
  color:var(--dsw-derive-muted,#57606a); font:inherit; font-size:11.5px;
  cursor:pointer; }
.wb-psess-tab:hover { background:color-mix(in srgb,var(--dsw-alias-label-primary,#1f2328) 8%,transparent);
  color:var(--dsw-alias-label-primary,#1f2328); }
.wb-psess-tab.active { background:color-mix(in srgb,var(--wb-psess-color, var(--dsw-alias-label-primary,#1f2328)) 14%,transparent);
  border-color:color-mix(in srgb,var(--wb-psess-color, var(--dsw-alias-label-primary,#1f2328)) 45%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)));
  /* gen8：同上，回归 45% 锁定派生（同 t260904-05 契约）。 */
  color:color-mix(in srgb,var(--wb-psess-color, var(--dsw-alias-label-primary,#1f2328)) 45%,var(--dsw-alias-label-primary,#1f2328)); }
.wb-psess-num { line-height:1; font-family:var(--ds-font-family-code,monospace); }
/* Session-row project badge (UI-5, color channel only; shapes belong to UI-4): an 8px square in the project color, inline in the tab. */
.wb-psess-dot { width:8px; height:8px; flex:none; border-radius:2px;
  background:var(--wb-psess-color, var(--dsw-alias-label-primary,#1f2328)); }
.wb-psess-close { position:absolute; top:-5px; right:-5px; width:12px; height:12px;
  display:flex; align-items:center; justify-content:center; padding:0; font:inherit;
  font-size:9px; line-height:1; border:none; border-radius:3px; background:none;
  color:var(--dsw-derive-danger,#cf222e); cursor:pointer; opacity:0; }
.wb-psess-tab:hover .wb-psess-close, .wb-psess-close:focus-visible { opacity:1; }
.wb-psess-close:hover { background:rgba(248,113,113,0.18); }
.wb-psess-notice { flex-basis:100%; font-size:10.5px; color:var(--dsw-derive-warn,#f59e0b); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.wb-psess-confirm { position:fixed; z-index:97; min-width:200px; max-width:280px;
  padding:8px 10px; border-radius:8px; background:var(--dsw-derive-dark-bg,#1e1e24);
  border:1px solid rgba(255,255,255,0.15); box-shadow:0 8px 24px rgba(0,0,0,0.5);
  display:flex; flex-direction:column; gap:5px; }
.wb-psess-confirm-t { font-size:12px; font-weight:600; }
.wb-psess-confirm-d { font-size:11px; color:var(--dsw-derive-dark-muted,#b8b8c8); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.wb-psess-confirm-m { font-size:10.5px; color:var(--dsw-derive-muted,#8c959f); }
.wb-psess-confirm-btns { display:flex; gap:6px; justify-content:flex-end; }
.wb-psess-confirm-btns button { font:inherit; font-size:11px; padding:2px 10px;
  border-radius:4px; cursor:pointer; border:1px solid rgba(255,255,255,0.2);
  background:none; color:var(--dsw-alias-label-primary,#1f2328); }
.wb-psess-confirm-btns button:hover { background:rgba(255,255,255,0.08); }
.wb-psess-confirm-btns .wb-psess-confirm-ok { border-color:rgba(248,113,113,0.6);
  color:var(--dsw-derive-dark-red,#f87171); }
.wb-psess-confirm-btns .wb-psess-confirm-ok:hover { background:rgba(248,113,113,0.15); }
`;
/**
* 一横排项目会话区：+ 钮 + 数字 tab 行 +（有确认目标时）确认弹层 + 行内提示。
* 纯展示/交互组件，状态只有 confirmId（哪个 tab 在等确认）。
*/
function ProjectSessionRow(props) {
	const { projectKey, projectName, projectDir, ledger, current, byId, creating, notice, noticeProject, onNew, onOpen, onClose } = props;
	const tabs = (0, react.useMemo)(() => pickProjectTabs(ledger, {
		project: projectKey,
		current,
		byId
	}), [
		ledger,
		projectKey,
		current,
		byId
	]);
	const handleOf = (0, react.useMemo)(() => {
		const m = /* @__PURE__ */ new Map();
		for (const t of tabs) {
			const e = ledger.find((x) => x && typeof x.id === "string" && x.project === projectKey && x.id === t.id);
			const h = e && typeof e.handle === "string" && e.handle !== "" ? e.handle : sessionHandle(t.id, []);
			m.set(t.id, h);
		}
		return m;
	}, [
		ledger,
		projectKey,
		tabs
	]);
	const [confirmId, setConfirmId] = (0, react.useState)(null);
	/** 正在确认的 tab 锚（ref 回调按 confirmId 条件挂到对应 tab 上）。 */
	const tabRef = (0, react.useRef)(null);
	const popRef = (0, react.useRef)(null);
	/** 摆位：锚矩形 → 视口钳制（左右不出界）+ 底部放不下向上翻。 */
	const place = (0, react.useCallback)(() => {
		const pop = popRef.current;
		const anchor = tabRef.current;
		if (!pop || !anchor) return;
		const r = anchor.getBoundingClientRect();
		const w = pop.offsetWidth;
		const h = pop.offsetHeight;
		const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
		const below = r.bottom + 4;
		const top = below + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 4) : below;
		pop.style.left = `${left}px`;
		pop.style.top = `${top}px`;
	}, []);
	(0, react.useLayoutEffect)(() => {
		if (confirmId !== null) place();
	}, [
		confirmId,
		place,
		tabs
	]);
	(0, react.useEffect)(() => {
		if (confirmId === null) return;
		const onDocDown = (e) => {
			const t = e.target;
			if (t && (popRef.current?.contains(t) || tabRef.current?.contains(t))) return;
			setConfirmId(null);
		};
		const onKey = (e) => {
			if (e.key === "Escape") setConfirmId(null);
		};
		document.addEventListener("mousedown", onDocDown);
		document.addEventListener("keydown", onKey);
		document.addEventListener("scroll", place, true);
		return () => {
			document.removeEventListener("mousedown", onDocDown);
			document.removeEventListener("keydown", onKey);
			document.removeEventListener("scroll", place, true);
		};
	}, [confirmId, place]);
	const confirmTab = confirmId === null ? null : tabs.find((t) => t.id === confirmId) ?? null;
	const showNotice = notice !== "" && (noticeProject === void 0 || noticeProject === projectKey);
	const color = projectColor(projectKey);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-psess",
		"data-wb-psess-row": "",
		style: {
			"--wb-psess-color": color,
			"--wb-psess-hover": hexToRgba(color, .16)
		},
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: PSESS_STYLES }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: "wb-psess-badge",
				"data-wb-psess-badge": "",
				title: projectKey,
				"aria-label": `${projectName} identity badge`,
				dangerouslySetInnerHTML: { __html: projectBadgeSvg(projectKey, 11) }
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				type: "button",
				className: tabs.length === 0 ? "wb-psess-new wb-psess-new-labeled" : "wb-psess-new",
				"data-wb-psess-new": "",
				"data-empty": tabs.length === 0,
				disabled: creating,
				title: `New ${projectName} session (main dir${projectDir ? `: ${projectDir}` : ""})`,
				"aria-label": `New ${projectName} session`,
				onClick: onNew,
				children: tabs.length === 0 ? "＋ New session" : "+"
			}),
			tabs.map((t) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				ref: confirmId === t.id ? tabRef : void 0,
				className: `wb-psess-tab ${t.active ? "active" : ""}`,
				"data-wb-psess-tab": "",
				"data-active": t.active,
				role: "button",
				tabIndex: 0,
				title: `${projectName} session #${handleOf.get(t.id) || t.seq} (seq ${t.seq}): ${t.title}\n${t.id}`,
				onClick: () => {
					setConfirmId(null);
					onOpen(t.id);
				},
				onKeyDown: (e) => {
					if (e.key === "Enter" || e.key === " ") {
						e.preventDefault();
						setConfirmId(null);
						onOpen(t.id);
					}
				},
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-psess-num",
						"data-wb-psess-handle": "",
						children: handleOf.get(t.id) || t.seq
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						"aria-hidden": true,
						className: "wb-psess-dot",
						"data-wb-psess-dot": ""
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						className: "wb-psess-close",
						"data-wb-psess-close": "",
						title: "Close this session entry (needs confirmation; session content is not deleted)",
						"aria-label": `Close session entry ${handleOf.get(t.id) || t.seq}`,
						onClick: (e) => {
							e.stopPropagation();
							setConfirmId(t.id);
						},
						children: "×"
					})
				]
			}, t.id)),
			confirmTab && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-psess-confirm",
				"data-wb-psess-confirm": "",
				role: "dialog",
				"aria-label": "Confirm closing the session entry",
				ref: popRef,
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-psess-confirm-t",
						children: [
							"Close session #",
							handleOf.get(confirmTab.id) || confirmTab.seq,
							"?"
						]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-psess-confirm-d",
						title: confirmTab.title,
						children: confirmTab.title
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-psess-confirm-m",
						children: "Only the entry is closed; the session content is not deleted."
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-psess-confirm-btns",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							type: "button",
							className: "wb-psess-confirm-cancel",
							"data-wb-psess-confirm-cancel": "",
							onClick: () => setConfirmId(null),
							children: "Cancel"
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							type: "button",
							className: "wb-psess-confirm-ok",
							"data-wb-psess-confirm-ok": "",
							onClick: () => {
								setConfirmId(null);
								onClose(confirmTab.id);
							},
							children: "Close"
						})]
					})
				]
			}),
			showNotice && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: "wb-psess-notice",
				"data-wb-psess-notice": "",
				role: "status",
				children: notice
			})
		]
	});
}
/**
* Short code of a dsh session id: strip the `session-` prefix, take the first N
* hex chars. Non-`session-` shapes (ticket sessions, bare uuids, malformed) take
* the first 4 chars too — the code is a reference, not a classifier, so the shape
* is lenient (classification lives in isGlobalSessionId at the ledger entrance).
* Non-string / empty returns '' (the caller treats it as unassigned; no fake code).
*/
function shortCodeOf(sessionId, len = 4) {
	if (typeof sessionId !== "string" || sessionId === "") return "";
	return (sessionId.startsWith("session-") ? sessionId.slice(8) : sessionId).slice(0, Math.max(1, Math.floor(len)));
}
/** Display handle of an entry: the assigned one, else a temporary short code
*  (display only, never persisted — assignment lands on the register path, the
*  display layer never blocks on "unassigned"). */
function displayHandle(e) {
	if (!e || typeof e.session_id !== "string" || e.session_id === "") return "";
	if (typeof e.handle === "string" && e.handle !== "") return e.handle;
	return shortCodeOf(e.session_id);
}
//#endregion
//#region src/client/visibility-state.ts
/**
* visibility-state.ts —— 页面可见性纯读（t260915-10 gen7 从 visibility-poll.ts 拆出）。
*
* 拆分原因：visibility-poll.ts 顶上 import react（hook 封装需要），而 react 由宿主
* dsh 核心供给、不在插件 node_modules——非 React 模块（project-tag-index.ts 等
* node 裸跑 UT 覆盖面）一旦 import 它即 ERR_MODULE_NOT_FOUND。本模块零依赖，供
* 「只读可见性、不起定时器」的取数路径共用同一门判定，语义单源不复制。
*
* 契约不变（沿 visibility-poll.ts 原实现）：document 不可用（node/smoke 裸跑）→
* 视为可见——那里没有「隐藏页签」概念，不静默改语义。
*/
function pageVisible() {
	return typeof document === "undefined" || document.visibilityState === "visible";
}
//#endregion
//#region src/client/visibility-poll.ts
/**
* visibility-poll.ts —— 不可见页签暂停轮询（t260901-15，多页签共存③）。
*
* 背景：用户常开多个控制台页签，后台页签照常全速轮询（台面 5s/health 5s/
* 巡检 30s/agent-live 8s/侧栏 10s/立项 8~10s），放大查询通道压力（KI-003）。
* 本模块把「定时轮询」统一收口成可见性门：页签不可见即停表、零请求；
* 重新可见立即补刷一次并恢复节拍。
*
* 两条 API：
*   - startVisibleInterval(fn, ms) → 停表函数：命令式（用在已有 effect 内部，
*     替换裸 setInterval，初始 load() 语义不动）；
*   - useVisiblePoll(fn, ms)：useVisiblePoll 的 hook 封装（fn 走 ref 取最新，
*     避免每次渲染重建定时器）。
*
* 故障口径：document 不可用（node/smoke 裸跑）→ 视为可见直接轮询（与旧行为
* 一致，不静默改语义——那里没有「隐藏页签」概念）；fn 异常向上抛给宿主 effect
* 的既有兜底（各 effect 内部已有 try/catch 或静默约定）。
*/
/**
* 启动一个可见性门控的周期任务。返回停表函数（幂等，必调——终态回收纪律）。
* 立即可见时建表；隐藏时清表；回可见时先补跑一次再建表。
*/
function startVisibleInterval(fn, ms) {
	if (typeof document === "undefined") {
		const t = setInterval(fn, ms);
		return () => {
			clearInterval(t);
		};
	}
	let timer = null;
	const start = () => {
		if (timer === null && pageVisible()) timer = setInterval(() => {
			if (pageVisible()) fn();
		}, ms);
	};
	const stop = () => {
		if (timer !== null) {
			clearInterval(timer);
			timer = null;
		}
	};
	const onVis = () => {
		if (pageVisible()) {
			fn();
			start();
		} else stop();
	};
	start();
	document.addEventListener("visibilitychange", onVis);
	return () => {
		stop();
		document.removeEventListener("visibilitychange", onVis);
	};
}
//#endregion
//#region src/client/stale-check.ts
function parseHandshakeBody(status, bodyText) {
	if (status < 200 || status >= 300) return {
		statusOk: false,
		parseOk: false,
		stale: null,
		error: null,
		bootFingerprint: null,
		diskFingerprint: null
	};
	const empty = {
		statusOk: true,
		parseOk: false,
		stale: null,
		error: null,
		bootFingerprint: null,
		diskFingerprint: null
	};
	let parsed;
	try {
		parsed = JSON.parse(bodyText);
	} catch {
		return empty;
	}
	if (typeof parsed !== "object" || parsed === null) return empty;
	const result = parsed.result;
	if (typeof result !== "object" || result === null) return empty;
	const r = result;
	return {
		statusOk: true,
		parseOk: true,
		stale: typeof r.stale === "boolean" ? r.stale : null,
		error: typeof r.error === "string" ? r.error : null,
		bootFingerprint: typeof r.bootFingerprint === "string" && r.bootFingerprint !== "" ? r.bootFingerprint : null,
		diskFingerprint: typeof r.diskFingerprint === "string" && r.diskFingerprint !== "" ? r.diskFingerprint : null
	};
}
/**
* 三元组握手判定（injected + status + 原始文本）。injected=bundle 下载时刻注入的
* 盘上指纹（null=缺失：L2 阶梯/注入失败/纯刷新页面外的旧码），任何畸形输入都不抛。
* 矩阵逐格语义见文件头注 M1-M7；单测真值表（tests/stale-handshake.mjs）逐格对应。
*/
function classifyHandshake(injected, status, bodyText) {
	const b = parseHandshakeBody(status, bodyText);
	if (!b.statusOk) return { banner: status === 405 || status === 404 ? "restart" : null };
	if (b.error !== null) return {
		banner: null,
		error: b.error
	};
	if (!b.parseOk) return { banner: null };
	if (b.stale === true) return { banner: "restart" };
	if (b.stale === null || b.bootFingerprint === null) return { banner: "restart" };
	if (injected !== null && b.diskFingerprint !== null && injected !== b.diskFingerprint) return { banner: "reload" };
	return { banner: null };
}
//#endregion
//#region src/client/staleness.ts
/**
* staleness.ts —— 插件陈旧全局提醒 hook（t260902-03 立；t260905-07 KI-052 握手矩阵接线）。
*
* 运行时看守：30s 可见性门轮询 /sandbar-workbench/api/build-info（页签不可见零请求，
* 复用 startVisibleInterval），判定走 classifyHandshake 三元组矩阵（boot/disk/injected，
* 见 ./stale-check.ts）：
*   - restart 支：服务端旧（boot≠disk / build-info 端点 405/404 内存无 / 缺 boot 指纹）
*     → 「有更新，重启控制台生效」；
*   - reload 支：服务端一致但浏览器旧（injected≠disk，跨重启存活页面）→
*     「有更新，刷新页面生效」——重启对此支无效，文案与消除动作一一对应。
*
* injected 的取得（L1 机制，写集内实现）：dsh 核心供给链在写集外、无法在 bundle
* 响应里注入指纹，改用 **sessionStorage 注入代理**——本模块首次加载（=bundle
* 下载完成时刻）即拉一次 build-info，把当下 disk 指纹写进 sessionStorage（页面
* 维度，跨刷新存活）；轮询时读它当 injected。语义核对：
*   - 新开页/刷新后：init 覆写 injected=当下 disk → 恒 M5（消除动作「刷新」可达，
*     不会刷新后横幅不消）；
*   - 页面存活跨合并/跨重启（不刷新）：sessionStorage 保留旧盘态 → injected≠disk
*     → M4 reload。
* 异常（隐私模式禁用 sessionStorage 等）→ injected 恒 null，M4 自动失效退回 L2
* 行为（仅服务端判定），不误报。
*
* 挂点单例在 sidebar 层（.wb-sb-right 共享容器），四视图排他渲染也不影响，横幅常驻。
*
* 回收纪律（终态全回收）：
*   - useEffect cleanup 必调 startVisibleInterval 返回的停表函数（幂等）；
*   - inflight fetch 在组件卸载后回包不得 setState——mounted 标志显式挡（React 18
*     下无害，按纪律仍显式处理）。
*
* 异常取舍（沿 t260902-03 口径）：轮询 fn 内自吞网络/解析类运行错误（矩阵落
* 不显），不向上抛——看守自身不得成为新报错源；编程错（非 Error 对象等）不在
* 自吞边界内。分类纯函数在 ./stale-check.ts，文案常量在 ./banner-text.ts（场景
* 断言锚同源，KI-051 纪律）。
*/
const BUILD_INFO_URL = "../sandbar-workbench/api/build-info";
const POLL_MS = 3e4;
/** sessionStorage 键（注入代理；页面维度，跨刷新存活、关页即清）。 */
const INJECTED_KEY = "wb.build.fingerprint.atload";
/** 读注入代理（异常→null：隐私模式等降级为 L2，不误报）。 */
function readInjected() {
	try {
		return window.sessionStorage.getItem(INJECTED_KEY);
	} catch {
		return null;
	}
}
/** 写注入代理（bundle 下载时刻的盘态快照）。 */
function writeInjected(fp) {
	try {
		window.sessionStorage.setItem(INJECTED_KEY, fp);
	} catch {}
}
/** 拉一次 build-info 并取 disk 指纹（init 用；网络/解析错自吞返 null）。 */
async function fetchDiskFingerprint() {
	try {
		const res = await fetch(BUILD_INFO_URL, { cache: "no-store" });
		if (res.status < 200 || res.status >= 300) return null;
		const fp = (await res.json().catch(() => null))?.result?.diskFingerprint;
		return typeof fp === "string" && fp !== "" ? fp : null;
	} catch {
		return null;
	}
}
function useStaleBanner() {
	const [banner, setBanner] = (0, react.useState)(null);
	const mountedRef = (0, react.useRef)(true);
	(0, react.useEffect)(() => {
		mountedRef.current = true;
		fetchDiskFingerprint().then((fp) => {
			if (fp !== null) writeInjected(fp);
		});
		const check = async () => {
			try {
				const res = await fetch(BUILD_INFO_URL, { cache: "no-store" });
				const verdict = classifyHandshake(readInjected(), res.status, await res.text());
				if (mountedRef.current) setBanner(verdict.banner);
			} catch {
				if (mountedRef.current) setBanner(null);
			}
		};
		const stop = startVisibleInterval(() => {
			check();
		}, POLL_MS);
		return () => {
			mountedRef.current = false;
			stop();
		};
	}, []);
	return banner;
}
//#endregion
//#region src/client/project-tag-index.ts
/**
* sandbar-workbench · chat 项目 tag 数据索引单态（t260903-07 工单②）。
*
* Owner 落明（方案 v3 N2 修正后的规格句）：
* - 谁写：WorkbenchSidebar.load()（10s 轮询）成功分支调用 publishProjects /
*   publishProjectEntry；catch 分支**不发**（失败不得顶掉 last-known-good，
*   KI-018 同族预防）。侧栏窄模式（wide=false）不轮询。
* - 谁读：chat-project-tag.ts 装饰器（消息文本里的工单 id → 项目归属）。
* - 变更通知（t260911-06 补缺）：publish* 只在**数据实际变化**时通知订阅者
*   （onProjectTagIndexChange）——此前外部发布后装饰器不重扫，行是否补装饰
*   全看「碰巧有无别的 DOM 变动」；新消息行在索引空窗插入即永久裸奔（260911
*   夜 chat-project-tag 间歇红实证签名：新行无 chip、旧行有）。
* - 兜底自取：装饰器挂载时若单态为空（侧栏未挂载/窄模式），自行 fetch 一次
*   /wf/projects + 各项目 /wf/tickets?project=，成功后同样走 publish* 合并语义；
*   60s 重试直到有数据、或侧栏外部发布（publishProjects 被外部调用即停自取定时器，
*   绝不出现两条 10s 轮询）。取舍已声明：允许 decorator 侧一条低频（60s）兜底轮询，
*   换取窄模式下 tag 不死。
* - 按需强取（t260911-06 补缺，nudge）：scan 发现「带票号引用却未归属」的行时，
*   兜底 handle 的 nudge() 单次强取一轮（绕过 hasData/外部发布停止条件——那两个
*   条件防的是**定时轮询双跑**，不防「数据源落后于刚建成的新票」）。有界三闸：
*   在途去重（同时只一轮）、最小间隔（默认 5s）、按引用去重（同一票号只强取一次）。
*   取到即 publish → 变更通知 → 装饰器重扫；仍取不到（假票号）不重试。
* - 失败语义：单态按项目键 last-known-good 合并——新值非空覆盖；新值为空且已有
*   旧值 → 保留旧值 + warn 一次（「fetch 成功但空列表」与失败在数据上同形，统一
*   口径不猜服务端；项目工单真清零属低频事件且 tag 缺失不炸，无过期机制的代价
*   已在方案 v3 声明）。
* - 纯逻辑（合并/查询）与 IO（fetch）分离：startProjectIndexFallback 接受
*   fetchImpl 注入，smoke 桩测全路径（含畸形响应不炸）。
* - 可见性门（t260915-10 gen7 顺手收口，仲裁判别探针终裁的 multi-tab T3 泄漏面）：
*   兜底自取链与 nudge 强取同受 KI-003 族纪律约束——页签不可见即零请求（schedule
*   周期照排但取数被门住、nudge 忽略且不耗最小间隔额度），回可见立即补跑一次并恢
*   复节拍，语义对齐 visibility-poll.ts startVisibleInterval 契约。document 不可用
*   （node/smoke 裸跑）沿用其故障口径：视为可见，取数照常，不静默改语义。
*/
const state$1 = {
	projectDirs: /* @__PURE__ */ new Map(),
	projectByTicket: /* @__PURE__ */ new Map(),
	/** 被外部（侧栏）发布过至少一次 → decorator 兜底自取停止。 */
	externallyPublished: false,
	/** 已 warn 过的项目键（warn 一次纪律）。 */
	warnedEmpty: /* @__PURE__ */ new Set()
};
/** 归一化工单 id 引用（字符串白名单：t\\d{6}-\\d{2} 口径由调用方先行过滤）。 */
function addTicketsOfProject(key, ticketIds) {
	const fresh = /* @__PURE__ */ new Set();
	for (const tid of ticketIds) if (typeof tid === "string" && tid !== "") fresh.add(tid);
	const prev = [];
	for (const [tid, k] of Array.from(state$1.projectByTicket)) if (k === key) prev.push(tid);
	if (prev.length === fresh.size && prev.every((tid) => fresh.has(tid))) return false;
	for (const [tid, k] of Array.from(state$1.projectByTicket)) if (k === key) state$1.projectByTicket.delete(tid);
	for (const tid of fresh) state$1.projectByTicket.set(tid, key);
	return true;
}
const changeListeners = /* @__PURE__ */ new Set();
/** 订阅索引变更（仅实际变化触发）。返回退订函数（幂等）。 */
function onProjectTagIndexChange(listener) {
	changeListeners.add(listener);
	return () => {
		changeListeners.delete(listener);
	};
}
function notifyIndexChange() {
	for (const l of Array.from(changeListeners)) try {
		l();
	} catch {}
}
/**
* 发布项目注册表（/wf/projects 整体一个请求，成功才调；失败不发）。
* 外部发布即关停 decorator 兜底自取。畸形条目跳过，不 throw。
* 数据实际变化才通知订阅者（同值重发=10s 轮询常态，不惊扰）。
*/
function publishProjects(entries) {
	if (!Array.isArray(entries)) return;
	state$1.externallyPublished = true;
	const next = /* @__PURE__ */ new Map();
	for (const e of entries) {
		const key = e?.key;
		const dirs = e?.dirs;
		if (typeof key !== "string" || key === "" || !Array.isArray(dirs)) continue;
		next.set(key, dirs.filter((d) => typeof d === "string" && d !== ""));
	}
	let changed = next.size !== state$1.projectDirs.size;
	if (!changed) for (const [k, v] of next) {
		const cur = state$1.projectDirs.get(k);
		if (cur === void 0 || cur.length !== v.length || v.some((d, i) => cur[i] !== d)) {
			changed = true;
			break;
		}
	}
	state$1.projectDirs = next;
	if (changed) notifyIndexChange();
}
/**
* 逐项目发布工单 id → 项目映射（仅在该项目 fetch 成功分支调用）。
* last-known-good 合并：tickets 空 且 该项目已有旧映射 → 保留旧值 + warn 一次。
* 数据实际变化才通知订阅者。
*/
function publishProjectEntry(projectKey, ticketIds) {
	if (typeof projectKey !== "string" || projectKey === "") return;
	if (!Array.isArray(ticketIds)) return;
	const clean = ticketIds.filter((t) => typeof t === "string" && /^t\d{6}-\d{2}$/.test(t));
	if (clean.length === 0 && [...state$1.projectByTicket.values()].includes(projectKey)) {
		if (!state$1.warnedEmpty.has(projectKey)) {
			state$1.warnedEmpty.add(projectKey);
			console.warn("[workbench] 项目 %s 工单列表为空（可能拉取失败或真清零）：tag 映射保留 last-known-good", projectKey);
		}
		return;
	}
	if (addTicketsOfProject(projectKey, clean)) notifyIndexChange();
}
/** 只读快照（复制 Map 引用不计成本：装饰器每次扫描只读一次）。 */
function readProjectTagIndex() {
	return {
		projectDirs: new Map(state$1.projectDirs),
		projectByTicket: new Map(state$1.projectByTicket),
		hasData: state$1.projectDirs.size > 0 || state$1.projectByTicket.size > 0
	};
}
/**
* 装饰器兜底自取：单态为空时拉 /wf/projects + 各项目 /wf/tickets?project=，
* 60s 重试直至有数据或侧栏外部发布。返回句柄：stop() 清定时器全终态回收；
* nudge() 绕过 hasData/外部发布停止条件单次强取（那两个条件防的是**定时轮询
* 双跑**，不防「数据源落后于刚建成的新票」），受三闸约束：在途去重、最小间隔
* （nudgeMinIntervalMs，默认 5s）、（引用级去重在装饰器侧做——它看得到行）。
* 所有失败路径静默降级（console.warn 一次），不 throw、不影响装饰器主循环。
*/
function startProjectIndexFallback(opts) {
	const { fetchImpl } = opts;
	const initialDelayMs = typeof opts.initialDelayMs === "number" ? opts.initialDelayMs : 0;
	const retryIntervalMs = typeof opts.retryIntervalMs === "number" ? opts.retryIntervalMs : 6e4;
	const maxAttempts = typeof opts.maxAttempts === "number" ? opts.maxAttempts : 60;
	const nudgeMinIntervalMs = typeof opts.nudgeMinIntervalMs === "number" ? opts.nudgeMinIntervalMs : 5e3;
	let timer = null;
	let stopped = false;
	let warned = false;
	let attempts = 0;
	let inFlight = false;
	let lastNudgeAt = 0;
	async function tryOnce(force = false) {
		if (stopped || inFlight) return;
		if (!pageVisible()) return;
		if (!force && (state$1.externallyPublished || readProjectTagIndex().hasData)) return;
		inFlight = true;
		if (!force) attempts++;
		try {
			const list = (await fetchImpl("/sandbar-workbench/api/wf/projects").then((r) => r.json()))?.result?.projects ?? [];
			if (!Array.isArray(list) || list.length === 0) throw new Error("projects 列表为空/畸形");
			publishProjects(list.map((p) => ({
				key: p.key,
				dirs: Array.isArray(p?.dirs) ? p.dirs : []
			})));
			for (const p of list) {
				if (typeof p?.key !== "string") continue;
				try {
					const tickets = (await fetchImpl(`/sandbar-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`).then((r) => r.json()))?.result?.tickets;
					const ids = Array.isArray(tickets) ? tickets.map((t) => t?.id).filter((x) => typeof x === "string") : [];
					publishProjectEntry(p.key, ids);
				} catch {}
			}
			opts.onData?.();
		} catch (err) {
			if (!warned) {
				warned = true;
				console.warn("[workbench] chat 项目 tag 索引兜底拉取失败（将持续低频重试）：", String(err instanceof Error ? err.message : err));
			}
		} finally {
			inFlight = false;
		}
	}
	function schedule() {
		if (stopped) return;
		if (state$1.externallyPublished || readProjectTagIndex().hasData) return;
		if (attempts >= maxAttempts) {
			console.warn("[workbench] chat 项目 tag 索引兜底拉取达上限，停止重试（映射缺失 → tag 不渲染）");
			return;
		}
		timer = setTimeout(() => {
			if (!pageVisible()) {
				schedule();
				return;
			}
			tryOnce().then(schedule);
		}, attempts === 0 ? initialDelayMs : retryIntervalMs);
	}
	let visHandler = null;
	if (typeof document !== "undefined") {
		visHandler = () => {
			if (stopped) return;
			if (pageVisible()) tryOnce().then(schedule);
			else if (timer !== null) {
				clearTimeout(timer);
				timer = null;
			}
		};
		document.addEventListener("visibilitychange", visHandler);
	}
	schedule();
	return {
		stop() {
			stopped = true;
			if (timer !== null) clearTimeout(timer);
			timer = null;
			if (visHandler !== null) {
				document.removeEventListener("visibilitychange", visHandler);
				visHandler = null;
			}
		},
		nudge() {
			if (stopped || inFlight) return;
			if (!pageVisible()) return;
			const now = Date.now();
			if (now - lastNudgeAt < nudgeMinIntervalMs) return;
			lastNudgeAt = now;
			tryOnce(true);
		}
	};
}
//#endregion
//#region src/client/chat-project-tag.ts
/**
* sandbar-workbench · 全局 chat 消息项目 tag 装饰器（t260903-07 工单②）。
*
* 渲染机制（方案 v2 R1 换轨后的定稿，验收硬约束）：
*   **零 childList 侵入 React 托管容器**——只给平台渲染的用户消息行**设置自有属性**
*   `data-wb-projtag="<projectKey>"`，视觉全在注入 head 的自有 <style> 里
*   （CSS ::before + attr() 出 chip 文本与着色）。插件卸载时 style 元素与全部
*   自有属性摘除，出厂树恢复原样。
*   平台锚=chat 行自声明的属性（非 css-module 哈希类，实查 dsh-client-ui-conversation
*   产物 client.js：每条 flow 行 `div[data-chat-anchor-key][data-chat-flow-kind="<kind>"]`，
*   用户消息行 kind="user"）——结构性特征写死为常量并注明出处。
*
* 先例借鉴模式取舍（对照 sidebar.tsx useHideFactoryNewSession /
* metrics-anchor.ts / metrics-entry.tsx 三先例）：
* - ✅ 锚定负向排除（OWN_SUBTREE_MARKER 教训）：正向只认平台 data-chat-* 属性；
*   候选行 closest('[data-wb-projtag-scope]')（本装饰器自留作用域标记位）命中即跳过，
*   杜绝误伤自有/同形节点。
* - ✅ 锚丢失显式降级：扫描前验 document isConnected；失联置 stopped、断 Observer、
*   warn 一次后停手——不进入反复重探风暴。
* - ✅ 全终态回收五项：①断 MutationObserver；②退订索引变更通知（t260911-06 新增，
*   onProjectTagIndexChange 的退订函数）；③兜底自取句柄 stop（定时器清理+nudge 停）；
*   ④摘自铸物：head 里的 style 元素 remove + 自记账 Set 里全部已设属性 removeAttribute
*   （只摘自己设过的，绝不动出厂节点）；⑤降级广播：console.warn 留痕（不新增横幅面）。
* - ✅「移除自铸节点」语义（非「还原出厂值」）：本机制不动任何出厂属性，故无还原义务，
*   卸载=移除自铸物——与 useHideFactoryNewSession 的「还原出厂 display」是两类，不混写。
* - ✅ bounded 上溯 ≤10 层：本机制按属性直接 querySelectorAll，无上溯（不带，理由注明）。
* - ✅ 幂等先查再设：属性同值跳过；style 文本同值跳过——React 重渲染反复触发也不抖。
* - ✅ MutationObserver 兜防复活：盯 body 子树 childList（同 metrics-entry 先例），
*   React 重建行节点后重设属性；attributes 不盯（自有属性无人动）。
* - ✅ 索引数据落地即补扫（t260911-06，260911 夜「新行无 chip、旧行有」间歇红收口）：
*   订阅索引变更通知（外部发布/nudge 成功且数据实际变化 → scan）+ scan 发现
*   「带票号未归属」的新引用时按需 nudge 单次强取（有界：在途去重/最小间隔/
*   按引用去重）——堵住「数据到了没人扫、新票映射要干等下个 10s 轮询」两缺口。
* - ❌ body 级 overlay 贴 rect（metrics-entry 最终形态）：不带——tag 需逐消息行贴装且
*   随流式增长移动，fixed overlay 逐帧跟 rect 成本与脆性远高于属性锚。
*
* 范围收窄（方案 v3 R7）：只装饰用户消息行（assistant/工具行 v1 不 tag）；
* 扩展由后续票按锚稳定性结论决定。
*
* 归属判定（对方案 v3 R5 的一处实现期收窄，如实声明）：
*   ①消息文本含工单 id 引用（/t\\d{6}-\\d{2}/）→ ticket→project 映射（索引单态）；
*   ②方案的「会话 cwd → 项目」兜底**未实现**——平台 client 面的 sessions 快照
*   （SessionListState，实查类型）不含 cwd，chat DOM 亦无 cwd 出处，插件内无可靠
*   来源；强行猜测违反「不造隐形缺省」。缺失即不渲染 tag（验收声明的行为）。
*   派活/工单上下文类消息本就含工单 id 引用，多项目区分主场景已覆盖。
*/
/** 自有属性名（tag 值=project key）。 */
const PROJTAG_ATTR = "data-wb-projtag";
/** 自有 style 元素选择器（head 内，React 树之外）。 */
const STYLE_SELECTOR = "style[data-wb-projtag-style]";
/** 本装饰器作用域标记（负向排除用；本插件任何 DOM 都不设它，纯防御位）。 */
const OWN_SCOPE_ATTR = "data-wb-projtag-scope";
/** 平台 chat flow 行锚（出处：dsh-client-ui-conversation lib/client.js，data-chat-* 为平台自声明属性）。 */
const USER_ROW_SELECTOR = "[data-chat-anchor-key][data-chat-flow-kind=\"user\"]";
/** 工单 id 引用（t260903-07 口径；全局匹配，一行多工单取第一个命中）。 */
const TICKET_REF_RE = /t\d{6}-\d{2}/;
/** 消息文本 → 项目 key（映射缺失/无引用 → null=不渲染 tag，声明行为）。 */
function projectForText(text, projectByTicket) {
	if (typeof text !== "string" || text === "") return null;
	const m = text.match(TICKET_REF_RE);
	if (!m) return null;
	const key = projectByTicket.get(m[0]);
	return isProjectKeyLike(key) ? key : null;
}
/**
* 对一个扫描根内全部用户消息行施加/回收 tag 属性（纯 DOM 逻辑，smoke 用自有桩直测）。
* 幂等：同值跳过；映射消失的行回收属性。返回本次实际写动的行数（观测用）。
*/
function applyProjectTags(root, projectByTicket) {
	let touched = 0;
	let rows;
	try {
		rows = Array.from(root.querySelectorAll(USER_ROW_SELECTOR));
	} catch {
		return 0;
	}
	for (const row of rows) {
		const el = row;
		if (typeof el.setAttribute !== "function" || typeof el.getAttribute !== "function") continue;
		if (el.closest(`[${OWN_SCOPE_ATTR}]`) !== null) continue;
		const key = projectForText(el.textContent ?? "", projectByTicket);
		const cur = el.getAttribute(PROJTAG_ATTR);
		if (key === null) {
			if (cur !== null) {
				el.removeAttribute(PROJTAG_ATTR);
				touched++;
			}
			continue;
		}
		if (cur !== key) {
			el.setAttribute(PROJTAG_ATTR, key);
			touched++;
		}
	}
	return touched;
}
/**
* 找第一个「带工单号引用却未归属」的用户行引用（t260911-06 新增，nudge 判据）。
* 仅统计**当前未装饰**的行——已装饰行不参与；映射里查不到该引用才返回。
* 纯 DOM 逻辑，UT 桩直测。返回 null=没有这种行（不 nudge）。
*/
function firstUnmappedTicketRef(root, projectByTicket) {
	let rows;
	try {
		rows = Array.from(root.querySelectorAll(USER_ROW_SELECTOR));
	} catch {
		return null;
	}
	for (const row of rows) {
		const el = row;
		if (typeof el.getAttribute !== "function") continue;
		if (el.closest(`[${OWN_SCOPE_ATTR}]`) !== null) continue;
		if (el.getAttribute("data-wb-projtag") !== null) continue;
		const m = (typeof el.textContent === "string" ? el.textContent : "").match(TICKET_REF_RE);
		if (m && !projectByTicket.has(m[0])) return m[0];
	}
	return null;
}
/**
* useEffect 形态入口（F1 防呆）：返回的是**清理函数**本身，
* 可直接 `useEffect(() => startChatProjectTagEffect(...), [])`——useEffect 只把
* 返回函数登记为 cleanup，返回 handle 对象会被静默忽略（F1 死因：sidebar 直接
* 返回 handle → 卸载零回收）。本入口从形状上消灭该陷阱；新接线一律走这里，
* startChatProjectTag 保留给需要 scan 面的调用方（smoke/诊断）。
*/
function startChatProjectTagEffect(opts) {
	const h = startChatProjectTag(opts);
	return () => h.stop();
}
/**
* 启动装饰器：head 挂自有 style + body 子树 childList Observer + 索引兜底自取。
* 返回 handle，卸载方（sidebar useEffect cleanup）必须调用 stop()。
*/
function startChatProjectTag(opts) {
	const doc = opts.doc ?? (typeof document !== "undefined" ? document : null);
	if (!doc || doc.documentElement === null) {
		console.warn("[workbench] chat 项目 tag 装饰器无 document 可挂，软退化不渲染");
		return {
			scan() {},
			stop() {}
		};
	}
	let style = doc.querySelector(STYLE_SELECTOR);
	if (style === null) {
		style = doc.createElement("style");
		style.setAttribute("data-wb-projtag-style", "");
		doc.head.appendChild(style);
	}
	let lastCss = "";
	const refreshCss = () => {
		const css = projectTagCssRules([...readProjectTagIndex().projectDirs.keys()]);
		if (css !== lastCss) {
			lastCss = css;
			style.textContent = css;
		}
	};
	refreshCss();
	let stopped = false;
	let warnedDisconnected = false;
	const nudgedRefs = /* @__PURE__ */ new Set();
	const scan = () => {
		if (stopped) return;
		if (!doc.documentElement.isConnected) {
			if (!warnedDisconnected) {
				warnedDisconnected = true;
				console.warn("[workbench] chat 项目 tag 装饰器：document 已失联，停手（软退化不渲染）");
			}
			observer.disconnect();
			return;
		}
		refreshCss();
		const idx = readProjectTagIndex();
		applyProjectTags(doc, idx.projectByTicket);
		if (idx.hasData) {
			const ref = firstUnmappedTicketRef(doc, idx.projectByTicket);
			if (ref !== null && !nudgedRefs.has(ref)) {
				nudgedRefs.add(ref);
				indexFallback.nudge();
			}
		}
	};
	const observer = new MutationObserver(scan);
	observer.observe(doc.body ?? doc.documentElement, {
		childList: true,
		subtree: true
	});
	const unsubscribeIndexChange = onProjectTagIndexChange(() => {
		if (!stopped) scan();
	});
	const indexFallback = startProjectIndexFallback({
		fetchImpl: opts.fetchImpl,
		initialDelayMs: opts.fallback?.initialDelayMs ?? 0,
		retryIntervalMs: opts.fallback?.retryIntervalMs,
		maxAttempts: opts.fallback?.maxAttempts,
		onData: () => {
			if (!stopped) scan();
		}
	});
	return {
		scan,
		stop() {
			if (stopped) return;
			stopped = true;
			observer.disconnect();
			unsubscribeIndexChange();
			indexFallback.stop();
			style.remove();
			for (const row of Array.from(doc.querySelectorAll(`[${PROJTAG_ATTR}]`))) row.removeAttribute(PROJTAG_ATTR);
		}
	};
}
//#endregion
//#region src/client/platform-context-anchors.ts
/**
* 平台自启上下文锚清单（新增锚须带出处注 + fixtures 样本 + 场景同步）。
* 出处口径：宿主 260906 实报（notes/queued-fold-platform-context-ticket.json）
* + 真控制台新会话实文取证（本模块只收平台生成措辞，逐条见 note）。
*/
const PLATFORM_CONTEXT_ANCHORS = [
	{
		id: "runtime-context-snapshot",
		match: "exact",
		text: "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.",
		note: "平台运行时上下文快照的首句（宿主每轮注入的 wrapper 恒定措辞，跨项目恒定）。"
	},
	{
		id: "runtime-context-preamble",
		match: "exact",
		text: "The following workspace instructions may be relevant to your work.",
		note: "平台 workspace instructions 块的开场句（宿主恒定措辞，紧随 runtime context 快照之后）。"
	},
	{
		id: "dsh-file-policy",
		match: "first-line",
		text: "Current DSH file policy:",
		note: "平台文件沙箱策略行（宿主恒定措辞，独立段）。"
	},
	{
		id: "instructions-from",
		match: "first-line",
		text: "Instructions from: ",
		note: "平台注入工作区指令文件的 wrapper 行（恒为「Instructions from: <路径>」形态）；命中即整条消息按注入物折叠。"
	},
	{
		id: "claude-md-heading",
		match: "first-line",
		text: "# sandbar — ",
		note: "CLAUDE.md 头行（项目侧内容锚，工单点名；项目更名/头行改版=场景红人审，非静默）。唯一的项目侧锚，平台侧 wrapper 措辞锚齐备后可审删。"
	}
];
/**
* 平台上下文折叠判定（纯函数，smoke 直测）：
* - 容错口径与 classifyContextFold 同款：非字符串/空串 → false；
* - exact 锚：trimStart 后以锚文本开头；
* - first-line 锚：首个非空行以锚文本开头（允许锚行前有空白）；
* - 中段提及锚字样 → false（误折面声明见头注）。
*/
function classifyPlatformContext(text) {
	if (typeof text !== "string") return false;
	const trimmed = text.trimStart();
	if (trimmed === "") return false;
	for (const anchor of PLATFORM_CONTEXT_ANCHORS) if (anchor.match === "exact") {
		if (trimmed.startsWith(anchor.text)) return true;
	} else if ((trimmed.split("\n", 1)[0] ?? "").startsWith(anchor.text)) return true;
	return false;
}
//#endregion
//#region src/client/context-fold.ts
/**
* sandbar-workbench · 上下文折叠件（t260905-04）——通用「渲染面」装饰器。
*
* 职责：把带引擎打标（首行 CHARTER_MARKER，同源常量在 ../host/session-charter.ts）
* 的上下文注入消息在 chat 会话区收成一条可展开小条（「📋 已注入项目背景 · 点击
* 展开」），点开见全文（占位符已实值化）。未来任何上下文注入（项目简介、文档
* 引用）带同一标记即走本折叠件——机制在引擎（打标），面在渲染（本模块）。
*
* t260905-09 扩面：折叠判定从「仅 CHARTER_MARKER」扩为「marker ∨ 平台自启上下文
* 内容锚」（锚真源=同目录 platform-context-anchors.ts：runtime context 快照句/
* workspace instructions 开场句/Instructions from 行/CLAUDE.md 头行等；锚纪律、
* 误折面声明与漂移看守在彼处头注）。真控制台新会话=平台自启上下文 N 条 + 工单台
* 注入 1 条叠加（宿主 260906 实报「只折叠了开头一小部分」病根：16 号只折了自家
* 注入），施折面同步改聚合语义：同一滚动体内全部候选气泡（按**气泡元素身份**
* 去重——多锚命中同一消息只计一次）全部收折、共享**恰一个小条**；计数文案仅
* N>1 叠加态出现，N=1 保持现行文案逐字不变（与 16 号 journey T1 在场断言、smoke
* C 文案等值断言零回归的最小 diff 前提）。平台消息不含 CHARTER_MARKER，两路
* 触发器互不依赖；「marker 消息恒恰一条」假设只对工单台注入成立，warn 语义随之
* 收窄（取舍第 5 项）。
*
* 平台消息气泡锚（方案步 1 取证结论）：隔离台 DOM 探针在本实现环境不可用
* （stage_docker ensure 容器只读挂载 ENV_FAIL，见工单 evidence），故锚算法取
* 「内容推导式」而非「结构属性式」——不依赖平台气泡类名/属性（非 css-module
* 哈希类不赌、也无处可实查）：在 [data-conversation-scroll] 内找 textContent
* 以 marker 开头的最深元素（markerHost），再沿「唯一元素子链」上爬到父层有
* 兄弟（=同级还有其他消息）或父层即滚动体的那一层为气泡。降级口径：爬到滚动体
* 本体（=会话仅此一条消息、无兄弟可分层）则**跳过折叠**——宁可整段照旧，绝不
* 把整个滚动体藏掉；marker 消失后由孤儿清扫恢复原状。平台气泡结构一旦可实查，
* 可在 findCharterBubble 里补结构锚短路（属性锚成本与脆性 tradeoff 同 band 第 10 项）。
*
* ── 故障模式取舍清单（对照 chat-project-band.ts 头注 10 项范式逐项，t260905-04
*    review C1 打回定稿；「照搬」字样禁用，逐项「带/不带+理由」）──
* 1. ✅ 锚丢失显式降级：滚动体 0 命中=hero/卸载瞬态，Observer 不断、不 warn
*    （同 band）；差异声明：滚动体在场但扫不到候选（marker 或平台锚，t260905-09
*    扩面）=常态（会话无注入物），同样不 warn 不断 Observer。
* 2. ⚠️ 负向排除**收窄声明**（非 band 原样）：本模块需在滚动体内自铸一个小条
*    元素（insertBefore 到气泡父容器，带 CHIP_ATTR 自有属性锚）——这是对 band
*    「零自铸 DOM」的真实扩面。气泡内部子树零触碰（内容隐藏纯靠气泡自身 attr
*    +CSS）。**孤儿小条专项（review 条件 A）**：React commit 只清自己 fiber 记
*    录的节点，外部插入的兄弟不随气泡被清理——会话切换/内容清空后旧小条可残留
*    为幽灵。对策：小条与**候选气泡集合**的配对记入注册表（t260905-09 从
*    1:1 配对扩为 1:N 聚合——一个小条对应同滚动体全部候选气泡），每轮回调
*    逐气泡校验「气泡仍连接 且 候选判定(气泡文本) 仍真」，失效即摘该气泡
*    属性并移出集合，集合空/小条脱树即摘小条——幽灵小条不过夜（无注入物
*    会话开头绝不出现「已注入项目背景」）。
* 3. ✅ F1 防呆接线：startContextFoldEffect 返回清理函数本身，sidebar 以
*    useEffect(() => startContextFoldEffect(), []) 接线（t260903-07 F1 实案不复犯）。
* 4. ✅ 注入防线（attr-only 加码）：marker/文案只进属性值与 textContent，**不进
*    CSS 选择器**——本模块 CSS 全静态字面量，零插值。
* 5. ⚠️ 多锚语义（t260905-09 收窄改写）：**工单台 charter 注入物**仍恒恰一条
*    （t3 ×1 守卫），marker 命中 N>1=console.warn 一次（疑似误打标信号）；
*    **平台自启上下文**叠加 N 条属真控制台常态（宿主 260906 实报），不 warn、
*    全部聚折到同一条小条（气泡元素身份去重，多锚同一消息只计一次）。
* 6. ✅ 畸形输入生产闸门：classifyContextFold 与 classifyPlatformContext 对
*    非字符串/空串容错为 false；只认首行/前缀口径（中段提及 marker 或锚字样
*    的普通消息不误触发）；前缀命中的固有误折面（用户粘贴以锚行开头）=设计内
*    限制，声明见 platform-context-anchors.ts 头注。
* 7. ✅ 幂等先查再设：属性值/小条存在性/style 文本同值跳过——React 重渲染与
*    Observer 回调反复触发不抖。
* 8. ✅ MutationObserver 防重建：滚动体祖先链 childList+subtree；**characterData
*    不盯**——marker 到场必经 childList 变更，盯 characterData 会让 agent 流式
*    逐 token 输出每帧触发全文扫描（性能不值，方案 review C1-② 定稿）。回调内
*    只对新增节点子树扫描（增量），接线时对既有 DOM 跑一次全树兜底（覆盖先于
*    接线已渲染的历史会话）。removedNodes 不盯——孤儿由第 2 项配对校验兜住。
*    增量守门文本节点分支：判定式 t260905-09 起对齐扩面口径（marker ∨ 平台锚，
*    同一谓词常量消费）；现实语义上消息到达恒为元素节点（文本分支纯兜底），
*    两路触发器共用谓词保证未来锚变更不再需要分叉改两处。
* 9. ✅ 全终态回收五项（band 第 9 项是四项，本模块多一项，非照抄）：断 Observer
*    + 摘 head style + 摘全部自设属性与自铸小条（只摘自己设过/铸过的；回收
*    遍历 t260905-09 起按聚合注册表 chip→气泡集合展开，逐气泡摘属性）+ **解绑
*    document click 委托（band 明文无监听面，本模块新增件）** + 降级路径 warn
*    留痕。点击委托防重入=引用计数单例：重复 start 不叠绑（监听器只绑一次），
*    引用归零才真拆——React StrictMode 双挂（挂→清→挂）与多消费方两安全。
* 10. ❌ body 级 overlay 贴 rect：不带（同 band 同 tag 理由——属性锚成本与脆性
*     远低于逐帧 rect 跟随；本模块无逐帧跟随诉求）。
*
* 折叠态语义（方案 D2 裁定）：折叠=气泡 display:none（文本仍在 DOM，textContent
* 可读——journey t2/t3 特征串 ×1 计数零改动兼容）；展开=去折叠态。marker 行展开
* 态随全文可见（C2 定死「接受+声明」，改 DOM 摘行=childList 入气泡、与 React
* 重渲染打架，不做）。
*/
/** 折叠态自有属性（气泡上；值='folded'|'open'）。 */
const FOLD_ATTR = "data-wb-context-fold";
/** 小条自有属性锚。 */
const CHIP_ATTR = "data-wb-context-fold-chip";
/** 自有 style 元素选择器（head 内，React 树之外）。 */
const FOLD_STYLE_SELECTOR = "style[data-wb-context-fold-style]";
/** 平台 chat 滚动体锚（同 chat-project-band；平台自声明属性）。 */
const SCROLL_SELECTOR = "[data-conversation-scroll]";
/** 小条文案（折叠态/展开态；N=1 单注入物形态，与 16 号文案逐字一致）。 */
const CHIP_LABEL_FOLDED = "📋 已注入项目背景 · 点击展开";
const CHIP_LABEL_OPEN = "📋 已注入项目背景 · 点击收起";
/**
* 小条文案生成（纯函数，t260905-09 聚合语义）：N=1 保持现行文案逐字不变
* （零回归最小 diff）；N>1 叠加态在文案中显式带气泡计数。
*/
function chipLabelFor(count, folded) {
	if (count <= 1) return folded ? CHIP_LABEL_FOLDED : CHIP_LABEL_OPEN;
	const n = Math.max(1, Math.trunc(count));
	return folded ? `📋 已注入项目背景 · ${n} 条 · 点击展开` : `📋 已注入项目背景 · ${n} 条 · 点击收起`;
}
/** 折叠件基础样式（全静态字面量，零插值——取舍第 4 项）。 */
const FOLD_BASE_CSS = `
[data-wb-context-fold="folded"] { display: none !important; }
[${CHIP_ATTR}] { cursor: pointer; opacity: 0.85; font-size: 12px; }
`;
/**
* Fold predicate (pure, smoke-tested): true when one of the first 3 non-empty
* lines is exactly CHARTER_MARKER (t261008-01 widened: the marker moved from
* line 1 to line 2 — line 1 now carries the human-readable title because the
* platform derives the session title from the first line — and both shapes
* must fold; the legacy "trimStart().startsWith(marker)" shape is a subset of
* the new one). Non-string / empty / mid-text mention -> false (trade-off 6
* unchanged: only a whole-line marker within the first 3 lines counts).
*/
function classifyContextFold(text) {
	if (typeof text !== "string") return false;
	return text.split("\n").map((l) => l.trim()).filter((l) => l !== "").slice(0, 3).includes(CHARTER_MARKER);
}
/**
* 折叠候选判定（t260905-09 扩面，纯函数）：工单台 marker 路径 ∨ 平台自启上下文
* 锚路径（platform-context-anchors.ts）。两路互不依赖；畸形输入两条路径各自容错
* 为 false。Observer 增量守门的文本节点分支与施折定位共用本谓词（头注取舍第 8 项）。
*/
function isFoldCandidate(text) {
	return classifyContextFold(text) || classifyPlatformContext(text);
}
/**
* 元素子节点集合数组化。真 DOM 的 el.children 是 HTMLCollection（live 集合，
* 无 .some/.map 等数组方法）——必须 Array.from 落成真数组再集合操作；
* 直接 `as El[]` 断言会在浏览器运行期炸（仲裁指认的 code-fault 根因，
* KI 候选「桩集合语义分裂」的修复点）。Array.from 对桩数组/HTMLCollection/
* NodeList 三形态一律成立，遍历期瞬时快照也消除了 live 集合遍历中 DOM 被改
* 的失稳面。
*/
function elementChildren(el) {
	return Array.from(el.children ?? []);
}
/**
* 在滚动体内收集折叠候选气泡（纯函数面，可测；t260905-09 从「单 marker 气泡」
* 扩为「全部候选聚合」，算法口径）：
* ① 单遍扫描收集候选宿主（marker 或平台锚开头、且无子元素命中的独立元素）；
* ② 沿唯一元素子链上爬：父层只有这一个元素子且父层≠滚动体 → 上移；
*    停在「父层有兄弟（=同级还有其他消息）或父层=滚动体」的那层=气泡；
* ③ 气泡=滚动体本身（无兄弟可分层）→ 该宿主丢弃（降级：宁不折，不藏整个
*    滚动体）；同气泡多宿主按元素身份去重（取舍第 2 项）。
*/
/** 气泡爬升（纯函数面）：从候选宿主沿唯一元素子链上爬到气泡层（头注算法①②）。 */
function bubbleOfHost(host, scroll) {
	let bubble = host;
	while (bubble.parentElement && bubble.parentElement !== scroll && elementChildren(bubble.parentElement).length === 1) bubble = bubble.parentElement;
	if (bubble === scroll) return null;
	return bubble;
}
/**
* 在滚动体内收集全部折叠候选气泡（纯函数面，可测，t260905-09 聚合语义）：
* ① 单遍扫描收集候选宿主元素（「自身命中候选判定且无子元素命中」的最深层独立
*    元素——**按宿主元素身份天然去重**：多锚命中同一消息只产生一个宿主）；
* ② 每个宿主沿唯一子链上爬到气泡层（bubbleOfHost）；
* ③ 按气泡元素身份去重（同气泡多宿主只留一个）；
* ④ 爬到滚动体本体的宿主丢弃（降级：宁不折，不藏整个滚动体，逐气泡降级不影响
*    其余候选）。
* 同时返回 marker 宿主计数（多锚 warn 语义只用工单台注入物计数，取舍第 5 项）。
*/
function collectFoldCandidates(scroll) {
	const all = scroll.querySelectorAll("*") ?? [];
	const seenBubbles = /* @__PURE__ */ new Set();
	const bubbles = [];
	let charterHosts = 0;
	for (const el of all) {
		if (!isFoldCandidate(el.textContent)) continue;
		if (elementChildren(el).some((c) => isFoldCandidate(c.textContent))) continue;
		if (classifyContextFold(el.textContent)) charterHosts++;
		const bubble = bubbleOfHost(el, scroll);
		if (!bubble || seenBubbles.has(bubble)) continue;
		seenBubbles.add(bubble);
		bubbles.push(bubble);
	}
	return {
		bubbles,
		charterHosts
	};
}
let state = null;
let refCount = 0;
/** 摘一个配对（小条+集合内全部气泡属性；逐节点容错幂等）。 */
function unpair(st, chip, bubbles) {
	try {
		chip.remove();
	} catch {}
	for (const bubble of bubbles) try {
		bubble.removeAttribute(FOLD_ATTR);
	} catch {}
	st.pairs.delete(chip);
}
/**
* 对单个滚动体施折叠（幂等，t260905-09 聚合语义）：
* 孤儿清扫 → 收集全部候选气泡 → 已配对者保持、未配对者打折叠态并并入共享小条。
* 返回处理结果：'none'=无候选（常态）| 'folded'=折/保持 | 'degraded'=小条铸入失败
* （逐气泡回滚，宁整段照旧不留半态）。
*/
function applyContextFold(scroll, doc) {
	const st = state;
	if (!st) return "none";
	for (const [chip, bubbles] of [...st.pairs]) {
		for (const bubble of [...bubbles]) if (bubble.isConnected === false || !isFoldCandidate(bubble.textContent)) {
			try {
				bubble.removeAttribute(FOLD_ATTR);
			} catch {}
			bubbles.delete(bubble);
		}
		if (chip.isConnected === false || bubbles.size === 0) unpair(st, chip, bubbles);
	}
	const { bubbles: candidates, charterHosts } = collectFoldCandidates(scroll);
	if (candidates.length === 0) return "none";
	if (charterHosts > 1 && !st.warnedMulti) {
		st.warnedMulti = true;
		console.warn("[workbench] context-fold：单滚动体命中多条 charter 注入物（预期恰一条，疑似误打标）：", charterHosts);
	}
	const existing = [...st.pairs.entries()].find(([, bs]) => candidates.some((c) => bs.has(c)));
	let chip = existing?.[0] ?? null;
	const chipBubbles = existing?.[1] ?? null;
	for (const bubble of candidates) {
		if (chipBubbles?.has(bubble)) continue;
		bubble.setAttribute(FOLD_ATTR, "folded");
		if (!chip) {
			chip = doc.createElement("button");
			chip.setAttribute(CHIP_ATTR, "");
			try {
				bubble.parentElement?.insertBefore(chip, bubble);
			} catch (err) {
				bubble.removeAttribute(FOLD_ATTR);
				console.warn("[workbench] context-fold：小条插入失败，本条不折叠：", err instanceof Error ? err.message : err);
				return "degraded";
			}
			st.pairs.set(chip, /* @__PURE__ */ new Set());
		}
		st.pairs.get(chip).add(bubble);
	}
	const finalChip = chip;
	const finalBubbles = st.pairs.get(finalChip);
	if (finalBubbles && finalBubbles.size > 0) {
		const folded = [...finalBubbles].every((b) => b.getAttribute(FOLD_ATTR) === "folded");
		finalChip.textContent = chipLabelFor(finalBubbles.size, folded);
	}
	return "folded";
}
/** 扫全部滚动体（增量回调与全树兜底共用入口）。 */
function scanAll(doc) {
	const scrolls = doc.querySelectorAll(SCROLL_SELECTOR) ?? [];
	if (scrolls.length === 0) return;
	for (const scroll of scrolls) applyContextFold(scroll, doc);
}
/** 小条点击（document 级委托，取舍第 9 项；t260905-09 聚合：整组开/收同点切换）。 */
function onChipClick(ev) {
	const st = state;
	if (!st) return;
	const target = ev.target;
	if (!target || typeof target.closest !== "function") return;
	const chip = target.closest(`[${CHIP_ATTR}]`);
	if (!chip) return;
	const bubbles = st.pairs.get(chip);
	if (!bubbles || bubbles.size === 0) return;
	const folded = [...bubbles].every((b) => b.getAttribute(FOLD_ATTR) === "folded");
	for (const bubble of bubbles) bubble.setAttribute(FOLD_ATTR, folded ? "open" : "folded");
	chip.textContent = chipLabelFor(bubbles.size, !folded);
}
/**
* 启动折叠件（引用计数单例）：head 注入 style + Observer（document 子树
* childList）+ document click 委托；接线时先全树兜底扫一次。二次调用不叠绑
* （监听器只绑一次），返回值=清理函数（引用归零才真拆，取舍第 9 项）。
*/
function startContextFold(opts = {}) {
	const doc = opts.doc ?? (typeof document !== "undefined" ? document : null);
	if (!doc) {
		console.warn("[workbench] context-fold：无 document 可挂，软退化不折叠");
		return () => {};
	}
	refCount++;
	if (!state) {
		const st = {
			observer: null,
			doc,
			pairs: /* @__PURE__ */ new Map(),
			warnedMulti: false
		};
		state = st;
		if (!doc.querySelector("style[data-wb-context-fold-style]")) {
			const style = doc.createElement("style");
			style.setAttribute("data-wb-context-fold-style", "");
			style.textContent = FOLD_BASE_CSS;
			doc.head.appendChild(style);
		}
		scanAll(doc);
		const observer = new MutationObserver((muts) => {
			let interesting = false;
			for (const m of muts) {
				for (const n of m.addedNodes) if (n.nodeType === 1 || typeof n.textContent === "string" && isFoldCandidate(n.textContent)) {
					interesting = true;
					break;
				}
				if (interesting) break;
			}
			if (!interesting) return;
			scanAll(st.doc);
		});
		observer.observe(doc.documentElement ?? doc, {
			childList: true,
			subtree: true
		});
		st.observer = observer;
		doc.addEventListener("click", onChipClick);
	}
	let stopped = false;
	return () => {
		if (stopped) return;
		stopped = true;
		refCount--;
		if (refCount > 0 || !state) return;
		const st = state;
		try {
			st.observer?.disconnect();
		} catch {}
		try {
			st.doc?.removeEventListener("click", onChipClick);
		} catch {}
		for (const [chip, bubbles] of [...st.pairs]) unpair(st, chip, bubbles);
		try {
			const style = st.doc?.querySelector(FOLD_STYLE_SELECTOR);
			if (style) st.doc?.head.removeChild(style);
		} catch {}
		state = null;
	};
}
/** sidebar 接线入口（F1：返回清理函数本身，取舍第 3 项）。 */
function startContextFoldEffect() {
	return startContextFold();
}
//#endregion
//#region src/client/platform-banner.ts
/**
* sandbar-workbench · platform banner-row hide decorator (t261007-07; the last
* open item of the 261004 topbar-banner design note).
*
* Visual: hide the platform's own left-column banner row (brand mark + name +
* fold toggle) so the console opens with our own brand row (t261005-09, 26px,
* `[data-wb-brand-row]`) as the first row. The platform banner is a **sibling
* flex child** of SidebarRoot (not a layer our chrome paints on), so per
* design-note §2 this is HIDE, not COVER: display:none lets the regionArea move
* up, a blank strip is impossible, and the guard path's worst case is the
* platform row simply remaining visible (the degradation the design note
* allows) — never a partial hide. The fold button goes away with the row (host
* ruling 260924: the separator drag already changes the width, clampWidth
* 264–420). This build has no theme button in the row at all (the theme control
* lives in the settings panel, dsh-client-ui-settings-general, footArea), so
* "both buttons stay gone" holds. document.title is platform-owned and this
* module never touches it (design note §2).
*
* ── Anchor (named constants + provenance, discipline ①) ──
* Anchor = the fold toggle's aria-label set (zh/en locale dicts, read in the
* installed tree @deepseek-ai/dsh-client-ui-sidebar/lib/client.js lines 312–313
* (zh) and 320–321 (en); across the platform only the fold toggle uses these
* keys — the brand button and the new-session button both use
* session.new.label, same file — so neither can be mistaken for the anchor).
* A new platform locale dict = add here; drift = guard warn.
* Root landmark = our own brand row `[data-wb-brand-row]` (rendered by
* sidebar.tsx).
*
* ── Row resolution (review C1: never a blind parentElement) ──
* The toggle renders inside a platform Tooltip wrapper; whether that wrapper
* produces a real DOM element cannot be verified from the minified sources
* (dsh-client-ui-primitives has no installed directory and a whole-tree grep
* finds no `function Tooltip` symbol — inlined and renamed). Resolution is
* therefore: **walk up from the toggle collecting ancestors until (excluding)
* the first ancestor that contains our brand row (= the platform SidebarRoot);
* tag every collected element**:
*   - flat DOM (no wrapper): chain = [logoRow], the whole row is hidden;
*   - Tooltip renders a wrapper: chain = [wrapper, logoRow], the full chain is
*     hidden — never a partial hide;
*   - landmark not found (our brand row unmounted / unexpected structure) or
*     the walk exceeds the cap → guard path: hide nothing and log one explicit
*     line (see below). The platform banner staying visible beats any risk of
*     a half-hidden state.
*
* ── Guard (discipline ②): anchor absent = hide nothing + exactly one
* console.warn naming the missing anchor; at most one warn per start (repeated
* scans never spam); a successful hide logs nothing extra.
*
* ── Render mechanism (mirrors chat-project-band.ts; zero childList intrusion
* into React-managed containers): set only a self-owned attribute
* `data-wb-platform-banner-hidden` on platform elements; the visual lives in
* one self-owned <style> injected into head (attribute selector, display:none).
* On plugin unload the style and every self-set attribute are removed and the
* factory tree is restored.
*
* ── Fault-mode tradeoff list (chat-project-tag.ts lines 13–25 form; review
* condition C2) — borrowed from the chat-project-band.ts shape (attr + head
* style + MutationObserver + cleanup), carried / not carried item by item:
* 1. ✅ Late platform mount: a body-subtree childList MutationObserver re-scans
*    — once React builds the row, the next callback hides it (same as band;
*    the observer stays connected, anchor disappear/reappear does not blind it).
* 2. ✅ Double injection / repeated scans: idempotent — same-value attribute
*    writes and same-text style writes are skipped; re-renders and observer
*    callbacks do not churn.
* 3. ✅ Node rebuild: childList rescan re-tags (band C4: never disconnect the
*    observer, so a hero↔chat-style switch does not leave it permanently blind).
* 4. ✅ Full-terminal-state cleanup: stop() is idempotent = disconnect the
*    observer + remove the head style + remove only the attributes this
*    decorator set (tracked per element, never a global sweep) + the guard
*    warn stays on the record; normal / error / timeout / unload all funnel
*    into the same stop().
* 5. ✅ Malformed / missing aria-label: querySelectorAll + getAttribute are
*    fault-tolerant; odd nodes are skipped without throwing (malformed-input
*    case, stub-reproduced, no real platform dependency).
* 6. ✅ Anchor semantics (module-specific): multiple anchors all hidden
*    together; a failed resolution hides nothing — never half-hidden.
*    MAX_WALK bounds the upward walk so an unexpected structure can never hide
*    half the page (safe-side failure = the platform row stays).
* 7. ✅ Guard is not noisy: at most one warn per start (declared: the first
*    unresolved scan logs, a later success does not log a "recovered" line —
*    one console line is enough, no state-machine narration).
* 8. ❌ No document.title writes (design note §2: never fight the platform for
*    the same field).
* 9. ❌ No collapsed-mode special case: the narrow rail renders the same row as
*    a 36px platform mark and it is hidden too — declared behavior (our plugin
*    owns the whole column; the platform mark has no place left to live).
* 10. ❌ No body-level overlay / scroll listeners (band's UI-5 face only; this
*     module has no interactive face, pure display:none, nothing to pin).
*/
/** The fold toggle's aria-label set (provenance in the module header; zh + en dicts). */
const PLATFORM_FOLD_LABELS = [
	"收起侧边栏",
	"打开侧边栏",
	"Collapse sidebar",
	"Open sidebar"
];
/** Our own brand row's self-set attribute selector (rendered by sidebar.tsx; the SidebarRoot landmark). */
const BRAND_ROW_SELECTOR = "[data-wb-brand-row]";
/** Self-owned hidden-attribute name (set on platform elements to hide). */
const BANNER_ATTR = "data-wb-platform-banner-hidden";
/** Self-owned style element selector (in head, outside the React tree). */
const BANNER_STYLE_SELECTOR = "style[data-wb-platform-banner-style]";
/** The injected hide CSS (attribute selector only, zero class/hash dependence). */
const BANNER_CSS = `[${BANNER_ATTR}] { display: none !important; }
`;
/** Guard warn lines (each names the missing anchor by its literal labels; at most one per start). */
const GUARD_NO_ANCHOR = "[workbench] platform banner: fold-toggle anchor (\"Collapse sidebar\" / \"Open sidebar\" / \"收起侧边栏\" / \"打开侧边栏\") not found; nothing hidden";
const GUARD_NO_ROOT = "[workbench] platform banner: fold-toggle found but the sidebar root (an ancestor containing [data-wb-brand-row]) could not be resolved; nothing hidden";
/**
* Row resolution (pure DOM logic, stub-tested): the elements to tag this round,
* or null = guard (anchor missing or root unresolved — hide nothing).
*/
function resolveBannerTargets(root) {
	let buttons;
	try {
		buttons = Array.from(root.querySelectorAll("button"));
	} catch {
		return null;
	}
	const toggles = buttons.filter((b) => {
		try {
			const label = b.getAttribute("aria-label");
			return typeof label === "string" && PLATFORM_FOLD_LABELS.includes(label);
		} catch {
			return false;
		}
	});
	if (toggles.length === 0) return null;
	const targets = [];
	for (const toggle of toggles) {
		let node = null;
		try {
			node = toggle.parentElement;
		} catch {
			return null;
		}
		const chain = [];
		let resolved = false;
		for (let depth = 0; node !== null && depth < 12; depth++) {
			let hasBrandRow = false;
			try {
				hasBrandRow = node.querySelector(BRAND_ROW_SELECTOR) !== null;
			} catch {
				return null;
			}
			if (hasBrandRow) {
				resolved = true;
				break;
			}
			chain.push(node);
			node = node.parentElement;
		}
		if (!resolved) return null;
		for (const el of chain) if (!targets.includes(el)) targets.push(el);
	}
	return targets;
}
/** Set/clear the attribute (idempotent). targets=null or empty = clear everything we set (the guard hides nothing). */
function applyBannerHidden(root, targets) {
	let touched = 0;
	let styled;
	try {
		styled = Array.from(root.querySelectorAll(`[${BANNER_ATTR}]`));
	} catch {
		return 0;
	}
	const wanted = new Set(targets ?? []);
	for (const el of styled) if (!wanted.has(el)) try {
		el.removeAttribute(BANNER_ATTR);
		touched++;
	} catch {}
	if (targets === null) return touched;
	for (const el of targets) try {
		if (el.getAttribute("data-wb-platform-banner-hidden") === null) {
			el.setAttribute(BANNER_ATTR, "");
			touched++;
		}
	} catch {}
	return touched;
}
/** useEffect-shaped entry (F1 guard, same as chat-project-band): returns the cleanup itself. */
function startPlatformBannerHideEffect(opts = {}) {
	const h = startPlatformBannerHide(opts);
	return () => h.stop();
}
/**
* Start the decorator: head style + first scan + a body-subtree childList
* Observer that rescans on platform rebuilds. Guard: a scan that cannot hide
* anything (anchor missing or the root unresolved) hides nothing and warns
* exactly once per start (no spam across repeated scans). stop() is mandatory
* on unload.
*/
function startPlatformBannerHide(opts = {}) {
	const doc = opts.doc ?? (typeof document !== "undefined" ? document : null);
	if (!doc || doc.documentElement === null || typeof doc.createElement !== "function") {
		console.warn("[workbench] platform banner decorator has no document to attach to; soft-degrade, nothing hidden");
		return { stop() {} };
	}
	let stopped = false;
	let warned = false;
	const observer = typeof MutationObserver !== "undefined" ? new MutationObserver(() => {
		if (!stopped) scan();
	}) : null;
	function scan() {
		if (stopped) return;
		let targets;
		try {
			targets = resolveBannerTargets(doc);
		} catch {
			targets = null;
		}
		try {
			applyBannerHidden(doc, targets);
		} catch {}
		if (targets === null && !warned) {
			warned = true;
			const hasToggle = PLATFORM_FOLD_LABELS.some((label) => {
				try {
					return Array.from(doc.querySelectorAll("button")).some((b) => b.getAttribute("aria-label") === label);
				} catch {
					return false;
				}
			});
			console.warn(hasToggle ? GUARD_NO_ROOT : GUARD_NO_ANCHOR);
		}
	}
	let style = null;
	try {
		style = doc.querySelector(BANNER_STYLE_SELECTOR);
	} catch {
		style = null;
	}
	if (!style) {
		style = doc.createElement("style");
		try {
			style.setAttribute("data-wb-platform-banner-style", "");
			style.textContent = BANNER_CSS;
			doc.head.appendChild(style);
		} catch {
			console.warn("[workbench] platform banner decorator cannot inject its style; nothing hidden");
			return { stop() {} };
		}
	}
	scan();
	try {
		observer?.observe(doc.body, {
			childList: true,
			subtree: true
		});
	} catch {
		console.warn("[workbench] platform banner decorator cannot observe the DOM; platform rebuilds will not re-hide");
	}
	return { stop() {
		if (stopped) return;
		stopped = true;
		try {
			observer?.disconnect();
		} catch {}
		try {
			const styled = doc.querySelectorAll(`[${BANNER_ATTR}]`);
			for (const el of Array.from(styled)) el.removeAttribute(BANNER_ATTR);
		} catch {}
		try {
			style?.remove();
		} catch {}
	} };
}
//#endregion
//#region src/client/project-icons.tsx
/** 图标语义元数据：title 与 aria-label 恒同值（可辨识纪律，验收 11b）。 */
const PROJECT_ICON_SPECS = {
	routes: {
		title: "Model Routes",
		ariaLabel: "Model Routes"
	},
	settings: {
		title: "Project Settings",
		ariaLabel: "Project Settings"
	}
};
/** 统一规格常量（单源；显形尺寸由消费方 CSS 定，几何常量在此）。 */
const PROJECT_ICON_VIEWBOX = "0 0 20 20";
const PROJECT_ICON_STROKE_WIDTH = 1.6;
function iconPaths(name) {
	switch (name) {
		case "routes": return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("circle", {
			cx: "4.2",
			cy: "10",
			r: "1.8"
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("path", { d: "M5.8 8.6l5.9-5.9M9.4 2.7h2.3v2.3M5.8 11.4l5.9 5.9M9.4 17.3h2.3v-2.3" })] });
		case "settings": return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("path", { d: "M3 5.6h8.2M15.4 5.6H17M3 10h1.9M9.1 10h7.9M3 14.4h9.4" }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("circle", {
				cx: "13.3",
				cy: "5.6",
				r: "1.9"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("circle", {
				cx: "7",
				cy: "10",
				r: "1.9"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("circle", {
				cx: "14.5",
				cy: "14.4",
				r: "1.9"
			})
		] });
	}
}
/** 图标组件：纯 svg（currentColor），容器态样式归消费方。 */
function ProjectIcon(props) {
	const spec = PROJECT_ICON_SPECS[props.name];
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("svg", {
		className: props.className,
		viewBox: PROJECT_ICON_VIEWBOX,
		width: "18",
		height: "18",
		fill: "none",
		stroke: "currentColor",
		strokeWidth: PROJECT_ICON_STROKE_WIDTH,
		strokeLinecap: "round",
		strokeLinejoin: "round",
		role: "img",
		"aria-label": spec.ariaLabel,
		children: iconPaths(props.name)
	});
}
//#endregion
//#region src/client/project-modals.tsx
/**
* project-modals.tsx —— 项目生命周期四弹层（project-lifecycle 票③面D，验收 11-13）。
*
* 入口（sidebar.tsx 接线）：组头第五枚「项目设置」图标（滑杆）→ ProjectSettingsModal
* （只读信息 + 票计数 + 体检占位 + danger 区）；danger 区「摘除项目…」→
* ProjectRemoveModal（四步流）；左栏末尾「＋ 接入项目」行 → ProjectAddModal；
* 隔离红色行 → QuarantineModal（原因 + <dir>/project.yaml 定位 + 修复指路）。
*
* 骨架先例=session-entry 确认弹层（project-session-row.tsx），取舍（方案 R1-② 定稿）：在飞禁点带（写按钮 busy disabled，结果驱动关闭——成功才关、
* 失败停留就地显示）；ESC/遮罩关闭带但**执行中不可关**（防半途弃置假示完成）；
* 错误就地显示带（验收 12 口径本体）；焦点/aria 基础带。position:fixed 脱离
* .wb-ticket-list 滚动容器裁剪（session-entry C1 同款理由）。
*
* 摘除四步流=显式状态机：gate（在飞闸预检）→ dispose（处置勾选，默认全保留）→
* dry（摘除清单）→ confirm（purge 勾选后输入 key 二次确认）→ executing → done。
* 每态迁移由结果驱动；purge 二次确认是弹层职责（路由不重复）。
*
* 降级口径：票计数 tickets_state 非 ok → 「—」+提示（不红）；体检 chips 本期降档
* =「体检数据源未接入」中性提示位（R2b 定稿：CLI list 无体检字段，UI 禁自行实现
* 体检逻辑——薄壳红线；数据源待宿主/epic 裁定后小票补齐，渲染位已留）。
*
* 语义锚（smoke/project-modals.mjs 源文本断言面）：data-wb-pmod-overlay / -close /
* -settings / -settings-tickets / -settings-health / -remove-danger / -add-row 由
* sidebar 承担 / data-wb-pmod-add / -add-key / -add-name / -add-dir / -add-pre /
* -add-submit / -remove-gate / -remove-purge-data / -remove-purge-cred /
* -remove-dry / -remove-key / -remove-submit / -quarantine-detail。零 CSS 类名
* 匹配纪律（自有 .wb-pmod-* 前缀，与出厂类名零交叉）。
*/
const PMOD_CSS = `${DERIVE_TOKENS_CSS}
.wb-pmod-overlay { position:fixed; inset:0; background:rgba(31,35,40,.35); z-index:200;
  display:flex; align-items:flex-start; justify-content:center; padding-top:8vh; }
.wb-pmod-panel { background:var(--dsw-derive-canvas,#fff); color:var(--dsw-derive-fg,#1f2328); border:1px solid var(--dsw-derive-border,#d0d7de); border-radius:10px;
  width:520px; max-width:94vw; max-height:80vh; overflow-y:auto; box-shadow:0 8px 24px rgba(31,35,40,.18);
  padding:18px 20px; font-size:13px; }
.wb-pmod-panel h3 { margin:0 0 4px; font-size:15px; display:flex; align-items:baseline; gap:10px; }
.wb-pmod-sub { color:var(--dsw-derive-muted,#57606a); font-size:12px; margin:0 0 14px; }
.wb-pmod-x { margin-left:auto; cursor:pointer; color:var(--dsw-derive-muted,#57606a); background:none; border:none; font-size:14px; }
.wb-pmod-field { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.wb-pmod-field label { width:76px; color:var(--dsw-derive-muted,#57606a); text-align:right; flex-shrink:0; }
.wb-pmod-field input { font:inherit; font-size:13px; flex:1; border:1px solid var(--dsw-derive-border,#d0d7de); border-radius:6px; padding:6px 8px; }
.wb-pmod-mono { font-family:ui-monospace,Menlo,monospace; font-size:11.5px; }
.wb-pmod-btn { font:inherit; font-size:13px; border:1px solid var(--dsw-derive-border,#d0d7de); background:var(--dsw-derive-canvas,#fff); color:var(--dsw-derive-fg,#1f2328);
  border-radius:6px; padding:5px 12px; cursor:pointer; }
.wb-pmod-btn:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-pmod-btn:disabled { cursor:not-allowed; color:var(--dsw-derive-muted,#57606a); background:var(--dsw-derive-surface,#f6f8fa); }
.wb-pmod-btn-blue { border-color:var(--dsw-derive-accent-border,#96c8f2); color:var(--dsw-derive-accent,#0969da); background:var(--dsw-derive-accent-bg,#ddf4ff); }
.wb-pmod-btn-danger { border-color:var(--dsw-derive-danger-border,#ff9b9b); color:var(--dsw-derive-danger,#cf222e); background:var(--dsw-derive-danger-bg,#ffebe9); }
.wb-pmod-err { background:var(--dsw-derive-danger-bg,#ffebe9); border:1px solid var(--dsw-derive-danger-border,#ff9b9b); color:var(--dsw-derive-danger,#cf222e); border-radius:6px;
  padding:7px 10px; font-size:12.5px; margin:8px 0; white-space:pre-wrap; }
.wb-pmod-ok { background:var(--dsw-derive-success-bg,#dafbe1); border:1px solid var(--dsw-derive-success-border,#7dd9a0); color:var(--dsw-derive-success,#1a7f37); border-radius:6px;
  padding:7px 10px; font-size:12.5px; margin:8px 0; }
.wb-pmod-warn { background:var(--dsw-derive-warn-bg,#fff8c5); border:1px solid var(--dsw-derive-warn-border,#d4a72c); color:var(--dsw-derive-warn-deep,#7d4e00); border-radius:6px;
  padding:7px 10px; font-size:12.5px; margin:8px 0; }
.wb-pmod-grid { display:grid; grid-template-columns:76px 1fr; row-gap:7px; margin-bottom:6px; }
.wb-pmod-grid .k { color:var(--dsw-derive-muted,#57606a); text-align:right; padding-right:10px; }
.wb-pmod-chip { display:inline-block; font-size:11px; border-radius:10px; padding:1px 8px; margin:1px 4px 1px 0;
  border:1px solid var(--dsw-derive-border,#d0d7de); color:var(--dsw-derive-muted,#57606a); background:var(--dsw-derive-surface,#f6f8fa); white-space:nowrap; }
.wb-pmod-danger { border-top:1px solid var(--dsw-derive-surface-2,#e8ebef); margin-top:14px; padding-top:12px; }
.wb-pmod-check { font-size:13px; line-height:2; }
.wb-pmod-dim { color:var(--dsw-derive-muted,#57606a); font-size:12px; }
`;
/** 弹层公共壳：遮罩 + ESC 关闭（executing 态不可关——防半途弃置假示完成）。 */
function ModalShell(props) {
	const overlayRef = (0, react.useRef)(null);
	(0, react.useEffect)(() => {
		if (props.locked) return;
		const onKey = (e) => {
			if (e.key === "Escape") props.onClose();
		};
		document.addEventListener("keydown", onKey);
		return () => document.removeEventListener("keydown", onKey);
	}, [props.locked, props.onClose]);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		ref: overlayRef,
		className: "wb-pmod-overlay",
		"data-wb-pmod-overlay": "",
		role: "dialog",
		"aria-label": props.label,
		onMouseDown: (e) => {
			if (!props.locked && e.target === overlayRef.current) props.onClose();
		},
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: PMOD_CSS }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-pmod-panel",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				type: "button",
				className: "wb-pmod-x",
				"data-wb-pmod-close": "",
				"aria-label": "Close dialog",
				disabled: props.locked,
				onClick: props.onClose,
				children: "✕"
			}), props.children]
		})]
	});
}
/** CLI 调用统一封装：返回 JSON；失败把 HTTP 错误体（error+body）合成人话抛出。 */
async function callProjectApi(url, init) {
	const res = await fetch(url, init);
	let payload = null;
	try {
		payload = await res.json();
	} catch {}
	if (!res.ok || payload?.ok === false) {
		const detail = payload?.error ?? `HTTP ${res.status}`;
		const extra = payload?.body?.error ? `\n${payload.body.error}` : "";
		const err = /* @__PURE__ */ new Error(`${detail}${extra}`);
		err.payload = payload;
		throw err;
	}
	return payload;
}
/**
* 项目设置弹层（验收 11）：只读信息 [key/显示名/根目录] + 票计数（Temporal 不可达
* 降级「—」不红）+ 体检占位（R2b 降档）+ danger 区「摘除项目…」（进入摘除四步流）。
* 本期只读，编辑器=Nongoal（epic 定稿）。
*/
function ProjectSettingsModal(props) {
	const { project, onClose, onRemove } = props;
	const [detail, setDetail] = (0, react.useState)(null);
	const [error, setError] = (0, react.useState)("");
	(0, react.useEffect)(() => {
		let cancelled = false;
		(async () => {
			try {
				const out = await callProjectApi(`/sandbar-workbench/api/wf/projects/detail?key=${encodeURIComponent(project.key)}`);
				if (!cancelled) setDetail(out?.result ?? null);
			} catch (err) {
				if (!cancelled) setError(String(err.message));
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [project.key]);
	const t = detail?.tickets;
	const degraded = detail != null && detail.tickets_state !== "ok";
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(ModalShell, {
		label: `Project Settings · ${project.name}`,
		onClose,
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("h3", { children: [
				"Project Settings · ",
				project.name,
				" ",
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-pmod-mono wb-pmod-dim",
					children: project.key
				})
			] }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("p", {
				className: "wb-pmod-sub",
				children: [
					"Registry entry · read-only (no editor yet) · ~/.sandbar/projects/",
					project.key,
					"/project.yaml"
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-grid",
				"data-wb-pmod-settings": "",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "k",
						children: "Project key"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-pmod-mono",
						children: project.key
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "k",
						children: "Display name"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: project.name }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "k",
						children: "Root dir"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-pmod-mono",
						children: project.primary
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "k",
						children: "Ticket counts"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						"data-wb-pmod-settings-tickets": "",
						children: detail == null ? error ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-pmod-dim",
							children: [
								"— (",
								error,
								")"
							]
						}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-pmod-dim",
							children: "Loading…"
						}) : degraded ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-pmod-dim",
							children: [
								"— (",
								detail.tickets_note || "Temporal unreachable; ticket counts unavailable",
								")"
							]
						}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
							"Open ",
							t?.open ?? 0,
							" · Closed ",
							t?.closed ?? 0,
							" · Archived ",
							t?.archived ?? 0
						] })
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "k",
						children: "Onboarding health"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						"data-wb-pmod-settings-health": "",
						children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-pmod-chip",
							children: "Health data source not wired up yet (pending a CLI list addition; this dialog only displays it)"
						})
					})
				]
			}),
			error && detail == null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-pmod-err",
				children: error
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-danger",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-pmod-dim",
						style: { marginBottom: 8 },
						children: "Danger zone — actions go through the single CLI source and behave exactly like the command line"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						className: "wb-pmod-btn wb-pmod-btn-danger",
						"data-wb-pmod-remove-danger": "",
						onClick: onRemove,
						children: "Remove project…"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-pmod-dim",
						style: { marginLeft: 8 },
						children: "Reversible by default: retires the registry entry, keeps all data"
					})
				]
			})
		]
	});
}
/**
* 接入弹层（验收 12）：表单 + 预检 + 拒收就地显示 + 黄牌不阻塞。
* 预检口径（CLI `project add` 无 --dry-run 旗，补旗为跨写集
* 裁定项）——预检降档为**本地形状检查**（key 白名单/根目录绝对路径/非空，不调 CLI、
* 零落盘），确认时由 CLI 做深度校验（存在性/交叉/重复/legacy）并就地显示；
* 本地检查=纯形状白名单，不实现 CLI 校验语义（薄壳红线不破）。
*/
function ProjectAddModal(props) {
	const { onClose, onAdded } = props;
	const [key, setKey] = (0, react.useState)("");
	const [name, setName] = (0, react.useState)("");
	const [dir, setDir] = (0, react.useState)("");
	const [pre, setPre] = (0, react.useState)(null);
	const [busy, setBusy] = (0, react.useState)(false);
	const [error, setError] = (0, react.useState)("");
	/** 预检（本地形状检查，F1 降档口径）：纯白名单正则/绝对路径/非空，不调 CLI、零落盘。 */
	const localCheck = () => {
		const problems = [];
		if (!/^[a-z0-9][a-z0-9-]*$/.test(key)) problems.push(`Invalid key shape: ${key || "(empty)"} (allowed: lowercase letters, digits and hyphens; must not start with a hyphen)`);
		if (!name.trim()) problems.push("Display name must not be empty");
		if (!dir.startsWith("/")) problems.push(`Root dir must be an absolute path: ${dir || "(empty)"}`);
		return problems;
	};
	const submit = async () => {
		setBusy(true);
		setError("");
		try {
			await callProjectApi("/sandbar-workbench/api/wf/projects/add", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({
					key,
					name,
					dir
				})
			});
			onAdded();
			onClose();
		} catch (err) {
			setError(String(err.message));
			setPre(null);
		} finally {
			setBusy(false);
		}
	};
	/** 预检产物：本地形状问题的提示条（黄牌语义——不阻塞确认，但深度校验仍会拒）。 */
	const warnings = Array.isArray(pre?.problems) ? pre.problems : [];
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(ModalShell, {
		label: "Add project",
		locked: busy,
		onClose,
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("h3", { children: "Add project" }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("p", {
				className: "wb-pmod-sub",
				children: "Registers into ~/.sandbar/projects/<key>/ · single-root model: multi-repo projects use the parent directory (ticket space = .lane/ under the root) · a missing root dir is created automatically (with parents) plus the container scaffold (zero git throughout: the container holds no repo, so create/clone one before opening tickets)"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-field",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "Project key" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
					className: "wb-pmod-mono",
					"data-wb-pmod-add-key": "",
					value: key,
					onChange: (e) => setKey(e.target.value),
					placeholder: "lowercase letters / digits / hyphens"
				})]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-field",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "Display name" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
					"data-wb-pmod-add-name": "",
					value: name,
					onChange: (e) => setName(e.target.value)
				})]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-field",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("label", { children: "Root dir" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
					className: "wb-pmod-mono",
					"data-wb-pmod-add-dir": "",
					value: dir,
					onChange: (e) => setDir(e.target.value),
					placeholder: "/absolute/path"
				})]
			}),
			error && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-pmod-err",
				"data-wb-pmod-add-error": "",
				children: error
			}),
			pre && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				"data-wb-pmod-add-pre": "",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-pmod-ok",
					children: "Local shape check passed (nothing written) — the CLI runs the deep validation on confirm (cross/duplicate/legacy; a missing root dir is created with the container scaffold); rejection reasons show up in place."
				}), warnings.map((w, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-pmod-warn",
					children: [
						"⚠ ",
						w,
						" (a shape problem does not block confirmation, but the deep CLI validation may still reject)"
					]
				}, i))]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				style: {
					display: "flex",
					gap: 8,
					marginTop: 10
				},
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					type: "button",
					className: "wb-pmod-btn wb-pmod-btn-blue",
					"data-wb-pmod-add-precheck": "",
					disabled: busy || !key || !dir,
					onClick: () => {
						const problems = localCheck();
						setPre({ problems });
						setError("");
					},
					children: "Precheck (local shape check, nothing written)"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					type: "button",
					className: "wb-pmod-btn",
					"data-wb-pmod-add-submit": "",
					disabled: busy || !pre,
					onClick: () => {
						submit();
					},
					children: "Confirm"
				})]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-pmod-dim",
				style: { marginTop: 8 },
				children: "Precheck first, then add; rejection reasons show in place, no need to dig through backend logs."
			})
		]
	});
}
/**
* 摘除弹层（验收 13）四步流：在飞闸预检 → 处置勾选（默认全保留）→ dry-run 清单
* → purge 二次确认 → 执行（executing 态锁定弹层：ESC/遮罩/✕ 全禁）。
*/
function ProjectRemoveModal(props) {
	const { project, onClose, onRemoved } = props;
	const [step, setStep] = (0, react.useState)("gate");
	const [gate, setGate] = (0, react.useState)(null);
	const [dry, setDry] = (0, react.useState)(null);
	const [purgeData, setPurgeData] = (0, react.useState)(false);
	const [purgeCred, setPurgeCred] = (0, react.useState)(false);
	const [confirmKey, setConfirmKey] = (0, react.useState)("");
	const [busy, setBusy] = (0, react.useState)(false);
	const [error, setError] = (0, react.useState)("");
	const [result, setResult] = (0, react.useState)(null);
	const callRemove = (0, react.useCallback)(async (dryRun) => {
		return callProjectApi("/sandbar-workbench/api/wf/projects/remove", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({
				key: project.key,
				dry_run: dryRun,
				purge_data: purgeData,
				purge_credentials: purgeCred,
				confirm_last: false
			})
		});
	}, [
		project.key,
		purgeData,
		purgeCred
	]);
	const precheck = async () => {
		setBusy(true);
		setError("");
		try {
			const out = await callRemove(true);
			setGate(out?.result ?? out);
			setStep("dispose");
		} catch (err) {
			setError(String(err.message));
		} finally {
			setBusy(false);
		}
	};
	const showDry = async () => {
		setBusy(true);
		setError("");
		try {
			const out = await callRemove(true);
			setDry(out?.result ?? out);
			setStep("confirm");
		} catch (err) {
			setError(String(err.message));
		} finally {
			setBusy(false);
		}
	};
	const execute = async () => {
		setBusy(true);
		setError("");
		setStep("executing");
		try {
			const out = await callRemove(false);
			setResult(out?.result ?? out);
			onRemoved();
		} catch (err) {
			setError(String(err.message));
			setStep("confirm");
		} finally {
			setBusy(false);
		}
	};
	const purgeNeedsConfirm = purgeData || purgeCred;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(ModalShell, {
		label: `Remove project · ${project.key}`,
		locked: busy || step === "executing",
		onClose,
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("h3", { children: [
				"Remove project · ",
				project.name,
				" ",
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-pmod-mono wb-pmod-dim",
					children: project.key
				})
			] }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("p", {
				className: "wb-pmod-sub",
				children: "Reversible by default: only the registry entry is retired, all data is kept; re-adding the same key restores it"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-check",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							type: "checkbox",
							"data-wb-pmod-remove-purge-data": "",
							checked: purgeData,
							onChange: (e) => setPurgeData(e.target.checked)
						}),
						" ",
						"Delete data/ (archive + metrics; irreversible, needs a second confirmation)"
					] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("br", {}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							type: "checkbox",
							"data-wb-pmod-remove-purge-cred": "",
							checked: purgeCred,
							onChange: (e) => setPurgeCred(e.target.checked)
						}),
						" ",
						"Delete credentials.yaml"
					] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-pmod-dim",
						children: "Disposition keeps everything by default — checking no purge box means a reversible removal."
					})
				]
			}),
			error && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-pmod-err",
				"data-wb-pmod-remove-error": "",
				children: error
			}),
			step === "gate" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				"data-wb-pmod-remove-gate": "",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					type: "button",
					className: "wb-pmod-btn wb-pmod-btn-blue",
					"data-wb-pmod-remove-precheck": "",
					disabled: busy,
					onClick: () => {
						precheck();
					},
					children: "Precheck (in-flight gate)"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-pmod-dim",
					style: { marginTop: 6 },
					children: "Any in-flight ticket (Temporal query by ProjectKey) not yet closed refuses the removal and reports the ticket ids; an unreachable Temporal refuses too (fail-closed, no bypass flag): run sandbar up first."
				})]
			}),
			step === "dispose" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				"data-wb-pmod-remove-dry": "",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-pmod-ok",
					children: "✓ Precheck passed: no in-flight ticket blocks the removal (same gate result as the CLI dry-run)."
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
					type: "button",
					className: "wb-pmod-btn",
					disabled: busy,
					onClick: () => {
						showDry();
					},
					children: "Removal list (dry-run)"
				})]
			}),
			step === "confirm" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				"data-wb-pmod-remove-confirm": "",
				children: [
					dry && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
						className: "wb-pmod-dim wb-pmod-mono",
						style: { whiteSpace: "pre-wrap" },
						children: JSON.stringify(dry, null, 2)
					}),
					purgeNeedsConfirm && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-pmod-field",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", {
							style: { width: 130 },
							children: [
								"Type ",
								project.key,
								" to confirm"
							]
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
							className: "wb-pmod-mono",
							"data-wb-pmod-remove-key": "",
							value: confirmKey,
							onChange: (e) => setConfirmKey(e.target.value),
							placeholder: project.key
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						className: "wb-pmod-btn wb-pmod-btn-danger",
						"data-wb-pmod-remove-submit": "",
						disabled: busy || purgeNeedsConfirm && confirmKey !== project.key,
						onClick: () => {
							execute();
						},
						children: "Confirm removal"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-pmod-dim",
						style: { marginLeft: 8 },
						children: [
							"Runs sandbar project remove ",
							project.key,
							" --json; same result as the CLI"
						]
					})
				]
			}),
			step === "executing" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-pmod-warn",
				children: "Running… (dialog locked)"
			}),
			result && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-ok",
				"data-wb-pmod-remove-result": "",
				children: ["Removal done: ", JSON.stringify(result)]
			})
		]
	});
}
/** 隔离条目弹层（验收 11）：原因含 <dir>/project.yaml 定位 + 修复指路。 */
function QuarantineModal(props) {
	const { entry, onClose } = props;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(ModalShell, {
		label: `Quarantined entry · ${entry.key}`,
		onClose,
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("h3", { children: ["Quarantined entry · ", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: "wb-pmod-mono",
				children: entry.key
			})] }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("p", {
				className: "wb-pmod-sub",
				children: "Loader fail-closed quarantine; other projects still load. A query by key reports the quarantine reason explicitly"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-pmod-err wb-pmod-mono",
				"data-wb-pmod-quarantine-detail": "",
				children: entry.error
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-pmod-dim",
				children: [
					"Location: ",
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-pmod-mono",
						children: [entry.dir, "/project.yaml"]
					}),
					". Fix: correct that project.yaml by hand and loading resumes automatically (the project group reappears in the left column). While quarantined there is no group header and no project settings entry (nothing loaded to configure)."
				]
			})
		]
	});
}
//#endregion
//#region src/client/ticket-list-model.ts
/**
* ticket-list-model —— 工单列表行卡（t260904-17，mock v5 屏⑤⑥）纯函数层。
*
* 零 react / 平台依赖，node 可裸 import 黑盒单测（tests/t260904-17-ticket-list-model.mjs，
* lane-states.ts 同款分层先例——只借形态不借语义（复用取舍见票 t260904-17 方案）：
* 不带入合并分支内联步排除、并行活跃数组等 dev-lane 专属启发式）。
*
* 通用口径（一套 UI 裁定，260904 宿主令）：
*  - 状态走引擎通用四态枚举 active/done/waiting/blocked（映射单点在本文件）；
*  - epic 色 = 代号稳定哈希（FNV-1a+murmur3 finalizer → 10 色板），零配置零漂移——
*    哈希函数直接复用 shared/project-color.ts 的 fnv1a（已导出，不抽不复制；
*    F2 教训=纯 FNV 短 key 低位雪崩不足会真实撞槽，finalizer 必须带走）；
*  - 阶段短名走拓扑声明 short 字段，缺省截断——UI 不内置任何业务词表；
*  - 本文件（及 ticket-row-card.tsx）不得出现 dev-lane 段名常量串（守卫测试看住）；
*    引擎通用状态词（running/awaiting-human/blocked/closed…）不属禁列。
*/
/** 五态人话短名（状态圆点旁文字，不占块）。 */
const STATE4_LABEL = {
	active: "Active",
	done: "Closed",
	waiting: "Waiting",
	blocked: "Blocked",
	failed: "Failed"
};
/**
* 终态「成功收口」与「在飞」执行状态词表（t260921-03 从 t260919-02 的活/成混称
* 拆出——COMPLETED 是终态对账的正源：已结束的票绝不再显示在跑/阻塞，快照遗留
* 词面不得胜出；CONTINUED_AS_NEW 是换代继续的转场态，沿用词面推导）。
* 与引擎 client.py _EXEC_DONE_OK/_EXEC_ALIVE_OK 同一词表的 UI 侧镜像，改任一侧
* 必须同步另一侧并跑两侧 UT。在飞词表外的一切非空字符串（FAILED/CANCELED/
* TIMED_OUT/未知新终态）→ failed（补集口径：终态非成功即失败类，未知新终态宁可
* 显失败不显在跑；TERMINATED 不上板故板面不可达）。畸形/缺失 exec_status 不参与
* 判别（不 throw）。
*/
const EXEC_STATUS_DONE_OK = /* @__PURE__ */ new Set(["COMPLETED"]);
const EXEC_STATUS_ALIVE = /* @__PURE__ */ new Set(["RUNNING", "CONTINUED_AS_NEW"]);
/**
* 引擎现值 → 五态（t260919-02 增第三参 execStatus 与 failed 态；t260921-03 终态对账）。
*
* 判别顺序：
*  1. exec_status=COMPLETED → done（终态对账：exec 在手即权威，先于一切词面——
*     快照遗留的 blocked/running 词面永不胜出，t260920-02/t260921-01 实案「工作流
*     已完成却显阻塞」的直接根治点）；
*  2. exec_status 非空且不在在飞词表 → failed（失败类终态优先：死票绝不显在飞，
*     也不得被快照遗留的 closed 词面误归收口；t260919-02 口径零回归）；
*  3. status/stage_state 词面 'failed' → failed（断链防御，review①：引擎失败行已
*     带 failed 词面而 exec_status 键在 host 透传丢键/旧行缓存时仍失败可见，不落
*     default active 复发病灶）；
*  4. 沿用既有四态推导：closed 优先（迁移把 closed 票 stage_state 置成了 awaiting，
*     语义上已完成，沿用台面 ticketState 既有口径）；未知/未来 stage_state →
*     active（宁显活跃勿假警报——不作受阻/等你误报，UT 真值表钉此缺省行）。
*/
function deriveTicketState(status, stageState, execStatus) {
	if (typeof execStatus === "string" && execStatus !== "") {
		if (EXEC_STATUS_DONE_OK.has(execStatus)) return "done";
		if (!EXEC_STATUS_ALIVE.has(execStatus)) return "failed";
	}
	if (status === "failed" || stageState === "failed") return "failed";
	const st = typeof status === "string" ? status : void 0;
	const ss = typeof stageState === "string" ? stageState : void 0;
	if (st === "closed") return "done";
	switch (ss) {
		case "blocked": return "blocked";
		case "awaiting-human": return "waiting";
		case "running":
		case "awaiting": return "active";
		default: return "active";
	}
}
const CLOSE_HEALTH_ENUM = /* @__PURE__ */ new Set([
	"ok",
	"failed",
	"abnormal",
	"unreadable"
]);
/** 巡检行识别（引擎行自报家门，两标记任一命中；畸形值按非巡检处理）。 */
function isInspectionRowLike(row) {
	if (row === null || typeof row !== "object") return false;
	return row.kind === "inspection" || row.engine === "inspection";
}
/**
* 行收口健康度：行键合法 → 透传（引擎单点判定的结果）；键缺/畸形 → 本地兜底推导。
*
* 兜底口径（引擎 _close_health_of 镜像）：只对「已知终态」下结论——
*  - exec=COMPLETED：巡检行受阻词面优先（blocked_reason 在=面快照 blocked=没跑成
*    实质工作 → abnormal；无论 report_path 是否在——t260917-02 起 blocked 收口也
*    落账，落账走 report 同名约定，路径在场≠报告在，实案「报告」即受阻面镜像）；
*    无受阻再按 report_path 判 ok/abnormal（无报告=异常收口）；dev-lane 无产物
*    契约恒 ok；
*  - exec 非空不在在飞词表 → failed（t260919-02 补集口径）；
*  - exec 断链（host 丢键）：词面防御 failed 词→failed、closed 词→ok（无 exec
*    无法核产物，绝不给 abnormal——在跑巡检面本来就没报告，宁可少标不撒谎）。
* 已知偏差（review 意见②，UT 夹具钉死）：部署窗老 degraded 行（引擎尚未带
* unreadable 键、面读取失败）在兜底下判 abnormal——徽标「已结束·异常（无报告）」
* 而非「待核」；仍在异常收口族、不撒谎终态，可接受。
*/
function closeHealthOf(row) {
	const carried = row === null || typeof row !== "object" ? void 0 : row.close_health;
	if (typeof carried === "string" && CLOSE_HEALTH_ENUM.has(carried)) return carried;
	const exec = row !== null && typeof row === "object" && typeof row.exec_status === "string" ? row.exec_status : "";
	if (exec !== "") {
		if (EXEC_STATUS_DONE_OK.has(exec)) {
			if (isInspectionRowLike(row)) {
				const r = row;
				const blocked = r.blocked_reason;
				if (typeof blocked === "string" && blocked.trim() !== "") return "abnormal";
				const rp = r.report_path;
				return typeof rp === "string" && rp.trim() !== "" ? "ok" : "abnormal";
			}
			return "ok";
		}
		if (!EXEC_STATUS_ALIVE.has(exec)) return "failed";
		return "";
	}
	const status = row !== null && typeof row === "object" ? row.status : void 0;
	const stageState = row !== null && typeof row === "object" ? row.stage_state : void 0;
	if (status === "failed" || stageState === "failed") return "failed";
	if (status === "closed") return "ok";
	return "";
}
/**
* 收口健康度徽标文案（''=不渲染——正常收口不贴徽标=既有收口行零变化，failed 行
* 已有「已失败」态字不重复贴）。abnormal 文案带「无报告」：当前 abnormal 只从
* 巡检缺报告产生（引擎判定同源），未来新产物域接入时随词表一起扩。
*/
function closeHealthBadgeOf(row) {
	const h = closeHealthOf(row);
	if (h === "abnormal") return "Closed·Abnormal (no report)";
	if (h === "unreadable") return "Closed·Unverified";
	return "";
}
/**
* 段间暂停操作键推导（t260908-01）：未暂停 → 'pause'，已暂停 → 'resume'。
* closed 票由调用方（availableOps）早退不进此函数；畸形输入（undefined/非布尔真值）
* 按真值性归 resume/pause，不 throw。推导住纯函数层（index.tsx 只消费），UT 直测。
*/
function pauseOpOf(paused) {
	return paused ? "resume" : "pause";
}
/**
* 段间暂停徽标二态文案（t260908-01）：pending=已受理待段间生效（当前段还在跑），
* at_gate=已停在段间门口；未知/空相位按 pending 文案兜底（宁可保守提示不可静默）。
*/
function pausedBadgeText(phase) {
	return phase === "at_gate" ? "⏸ Paused at the stage gate" : "⏸ Pausing (takes effect between stages)";
}
/**
* 排序层（t260916-15；t260919-02 增第三参 execStatus 与 failed 档；t260921-03 done
* 拆两层成四档）：等你/受阻/已失败 → 在跑 → **已结束·异常** → 已结束·正常。
* tier 是 deriveTicketState 五态+收口健康度的**纯投影**——状态→五态映射单点仍在
* deriveTicketState（全台唯一归并点），健康度单点在 closeHealthOf，本函数不另起
* 第二套词表；异常收口行 tier2（在跑之上？否——在跑之下、正常收口之上）：不沉底、
* 不被并入「看起来正常」的收口组，既有四类相对序不变（t260916-15 口径零回归）；
* 未知/未来 stage_state 继承「宁显活跃勿假警报」缺省 → tier1；失败票 tier0。
* 第四参 row 供健康度判定（缺省=旧三参形态，done 一律按正常收口 tier3 兜底——
* 老调用点/无行面语境不下异常结论）。
*/
function ticketMergeTierOf(status, stageState, execStatus, row) {
	switch (deriveTicketState(status, stageState, execStatus)) {
		case "waiting":
		case "blocked":
		case "failed": return 0;
		case "done": {
			const h = closeHealthOf(row ?? {
				status,
				stage_state: stageState,
				exec_status: execStatus
			});
			return h === "abnormal" || h === "unreadable" ? 2 : 3;
		}
		default: return 1;
	}
}
/**
* 排序时间源：updated_ts 优先，缺/畸形逐级回落 created → close_ts，全缺 → 0。
* 单位口径（review 意见钉死）：引擎 updated_ts/created/close_ts 全是**秒**
* （base.py _now_epoch 系；toMillis 是消费点显示归一单点，与本排序无关）——
* dev-lane 行与巡检行两数据源同单位，直接比原始值安全；若未来单源换单位，
* 必须先归一再进本函数，否则会以另一形态复刻「沉底」式静默错序。
* 非有限数/≤0（字符串/null/NaN/0/负）不抛不参与、逐级回落；行非对象 → 0。
*/
function ticketSortTsOf(row) {
	if (row === null || typeof row !== "object") return 0;
	for (const v of [
		row.updated_ts,
		row.created,
		row.close_ts
	]) if (typeof v === "number" && Number.isFinite(v) && v > 0) return v;
	return 0;
}
/**
* 左栏项目组合并排序（t260916-15 宿主实报「巡检票恒沉底」）：dev-lane 行与巡检行
* 合并后统一口径——tier 升序（等你/受阻→在跑→已完成）、级内时间源倒序、同 ts 保
* 输入序（显式 index 兜底，不依赖引擎 sort 稳定性）。浅拷贝排序不改输入数组；
* null/非对象元素不抛（tier 走缺省、ts=0，沉底不崩）。中列板面列表不消费本函数
* （排序是左栏项目组的组内呈现口径，工单正文验收①边界）。
*/
function sortMergedTickets(rows) {
	const keyed = rows.map((row, idx) => ({
		row,
		idx
	}));
	keyed.sort((a, b) => {
		const ra = a.row;
		const rb = b.row;
		const ta = ticketMergeTierOf(ra?.status, ra?.stage_state, ra?.exec_status, ra ?? void 0);
		const tb = ticketMergeTierOf(rb?.status, rb?.stage_state, rb?.exec_status, rb ?? void 0);
		if (ta !== tb) return ta - tb;
		const dts = ticketSortTsOf(rb) - ticketSortTsOf(ra);
		return dts !== 0 ? dts : a.idx - b.idx;
	});
	return keyed.map((k) => k.row);
}
/**
* epic 色板：10 色。与项目色板（shared/project-color.ts PROJECT_PALETTE）色相同构
* 但独立声明——两板语义不同（项目 tag vs epic 彩条/chip），互指防漂移不共用实例。
* 撞色口径同 project-color：碰撞无害（chip 有名可辨），不作通过/失败断言。
*/
const EPIC_PALETTE = [
	"#d6604f",
	"#e08214",
	"#b8a021",
	"#66a61e",
	"#35988c",
	"#4393c3",
	"#6b6ecf",
	"#9e5db5",
	"#c05b9c",
	"#7f7f7f"
];
/** 畸形 epic 代号兜底色（中性灰，一眼「未定色」）。 */
const EPIC_FALLBACK_COLOR = "#9ca3af";
/** 代号长度上限（超长按畸形处理）。 */
const EPIC_CODE_MAX_LEN = 64;
/**
* epic 代号 → 稳定色。纯函数无状态：同代号跨刷新/会话恒同色，与其它 epic
* 增删无关（验收②）。空/非字符串/超长 → 兜底灰。
*/
function epicColorOf(code) {
	if (typeof code !== "string") return EPIC_FALLBACK_COLOR;
	const c = code.trim();
	if (c === "" || c.length > EPIC_CODE_MAX_LEN) return EPIC_FALLBACK_COLOR;
	return EPIC_PALETTE[fnv1a(`epic:${c}`) % EPIC_PALETTE.length];
}
const SHORT_MAX = 4;
/**
* 阶段短名：拓扑声明 short 非空用之；否则 name 超 4 字符截断＋…。
* 畸形输入（非对象/无名）→ ''。消费点：行卡悬停 title 与进展行阶段语境（C2）。
*/
function stageShortOf(stage) {
	if (stage === null || stage === void 0 || typeof stage !== "object") return "";
	const short = typeof stage.short === "string" ? stage.short.trim() : "";
	if (short !== "") return short;
	const name = typeof stage.name === "string" ? stage.name.trim() : "";
	if (name === "") return "";
	return [...name].length > SHORT_MAX ? [...name].slice(0, SHORT_MAX).join("") + "…" : name;
}
/**
* 迷你站道点数组：点数=模板阶段数；已过（下标<当前下标）=done、当前=current、未来=todo。
* 边缘钉死（UT 真值表）：status=closed → 全 done；stage=null（未开跑/迁移 legacy）或
* 指针不在拓扑内 → 全 todo（不得误渲「已过」）；wf 缺失/stages 空 → []（行卡不渲染站道）。
*/
function laneDots(wf, ticket) {
	const stages = wf?.stages;
	if (!Array.isArray(stages) || stages.length === 0) return [];
	if (ticket?.status === "closed") return stages.map(() => "done");
	const idx = typeof ticket?.stage === "string" && ticket.stage !== "" ? stages.findIndex((s) => s?.id === ticket.stage) : -1;
	if (idx < 0) return stages.map(() => "todo");
	return stages.map((_, i) => i < idx ? "done" : i === idx ? "current" : "todo");
}
/** 消费点接线的单位归一（F2 回归点）：引擎 updated_ts=**秒**（base.py _now_epoch），
* 而部分调用方（侧栏 created/close_ts×1000）已持毫秒——按量级判别：数值 < 1e11
* 视为秒×1000，≥1e11 视为毫秒原样（1e11ms≈1973 年，两域在可预见时间内无重叠）。
* 畸形输入透传给 relativeTime 自行兜底（null/undefined/非数 → 返 undefined 外原样）。
*/
function toMillis(ts) {
	if (typeof ts !== "number" || !Number.isFinite(ts)) return ts;
	return ts < 1e11 ? ts * 1e3 : ts;
}
/**
* 相对时间：nowMs 注入可测，入参=毫秒（秒级时间戳须经 toMillis 归一）。<1min=「刚刚」、
* <1h=N 分钟前、<24h=N 小时前、其余=N 天前。畸形/缺失/负数/未来超过 1min 容差 →
* null（行卡回落绝对时间）。
*/
function relativeTime(ts, nowMs = Date.now()) {
	if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return null;
	const diff = nowMs - ts;
	if (diff < -6e4) return null;
	if (diff < 6e4) return "just now";
	if (diff < 36e5) return `${Math.floor(diff / 6e4)}m ago`;
	if (diff < 864e5) return `${Math.floor(diff / 36e5)}h ago`;
	return `${Math.floor(diff / 864e5)}d ago`;
}
/** 首句展示截断上限（字符）：超过即截断加省略号——行卡单行放不下长句。 */
const FIRST_SENTENCE_MAX = 48;
/**
* 正文 → 首句话（t260903-10 裸编号现场根治：老票无标题显示首句，不裸编号）。
* 口径：取正文第一个非空行，在第一个句读符（。！？!?；）处截断；无句读取整行；
* 超长截断加「…」。markdown 标记（#/-/>/空白）剥头。畸形输入（非字符串/空白/
* 全是标记）→ null（调用方回退展示选择函数）。host 侧 enrichment（node.ts）与
* 详情头部共用本函数（ticket show 的 body 同源裁剪——两条通道一个口径）。
*/
function firstSentenceOf(body) {
	if (typeof body !== "string") return null;
	const lines = body.split(/\r?\n/);
	let line = "";
	for (const raw of lines) {
		const t = raw.replace(/^[#>\-*\s]+/, "").trim();
		if (t !== "") {
			line = t;
			break;
		}
	}
	if (line === "") return null;
	const m = line.match(/^[^。！？!?；]+[。！？!?；]?/);
	let sentence = m !== null ? m[0] : line;
	if ([...sentence].length > FIRST_SENTENCE_MAX) sentence = [...sentence].slice(0, FIRST_SENTENCE_MAX).join("") + "…";
	return sentence;
}
/** 行卡/详情头部标题展示选择（收窄口径）：title → title_or_first
*  （host enrichment 派生字段，仅 title 为空的票下发）→ 回退工单号（裸编号是
*  最后兜底——enrichment 失败/老数据缺字段时，宁显编号不显「（无标题）」）。 */
function ticketDisplayTitle(t) {
	const title = typeof t.title === "string" ? t.title.trim() : "";
	if (title !== "") return title;
	const first = typeof t.title_or_first === "string" ? t.title_or_first.trim() : "";
	if (first !== "") return first;
	return t.id;
}
//#endregion
//#region src/client/ticket-row-card.tsx
/** Row tooltip title: id + stage context (C2 consumer: stage-short topology) +
*  blocked reason + exec-status verbatim (t260919-02: a failed row is
*  distinguishable in the tooltip by its Temporal terminal word) + the
*  close-health reason (t260921-03: never an unexplained abnormal close).
*  t261008-08 (mock v11): the compact (left-column) row moves the progress
*  sentence and the updated time into the tooltip — the visible row keeps only
*  id/title on line 1 and stage+epic+dots on line 2; absent parts are skipped,
*  never rendered as `undefined`.
*  (Exported for unit tests only — the malformed-input truth table runs in
*  tests/; render assertions belong to the scenarios.) */
function cardTitle(t, wf, compact = false, progress, rel) {
	const parts = [t.id];
	const stage = (wf?.stages ?? []).find((s) => s?.id === t.stage);
	const short = stageDisplayLabel(stage?.id ?? t.stage, stageShortOf(stage));
	if (short !== "") parts.push(`Stage: ${short}`);
	if (t.blocked_reason) parts.push(`Blocked: ${t.blocked_reason}`);
	if (t.exec_status) parts.push(`Exec: ${t.exec_status}`);
	if (t.close_health_reason) parts.push(`Close: ${t.close_health_reason}`);
	if (compact && progress?.text) parts.push(progress.text);
	if (t.updated) parts.push(`Updated ${t.updated}`);
	else if (compact && rel) parts.push(`Updated ${rel}`);
	return parts.join("\n");
}
function TicketRowCard({ t, wf, progress, compact = false, active = false, busy = false, updatedTsMs, kindBadge, ordering, ops = [], peerViewers = [], onOpen, onAdvance, onDispatch, onRework, onUnblock, onClose, onPause, onResume, onOpenEpic }) {
	const state4 = deriveTicketState(t.status, t.stage_state, t.exec_status);
	const epicColor = epicColorOf(t.epic);
	const dots = compact ? [] : laneDots(wf, t);
	const rel = relativeTime(toMillis(t.updated_ts ?? updatedTsMs));
	const stageLabel = stageDisplayLabel((wf?.stages ?? []).find((s) => s?.id === t.stage)?.id ?? t.stage, stageShortOf((wf?.stages ?? []).find((s) => s?.id === t.stage)));
	const stop = (fn) => (ev) => {
		ev.stopPropagation();
		if (!busy) fn?.();
	};
	const orderable = ordering?.kind === "queued";
	const onDragStart = (ev) => {
		if (!orderable) return;
		ev.dataTransfer.effectAllowed = "move";
		ev.dataTransfer.setData("text/plain", t.id);
		ordering?.onDragStart?.();
	};
	const onDrop = (ev) => {
		ev.preventDefault();
		ev.stopPropagation();
		ordering?.onDrop?.();
	};
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-card",
		"data-ticket-id": t.id,
		"data-state": state4,
		"data-active": active,
		"data-compact": compact,
		"data-engine": t.engine,
		"data-order-kind": ordering?.kind,
		draggable: orderable,
		onDragStart,
		onDragOver: orderable ? void 0 : (ev) => {
			if (ordering !== void 0) ev.preventDefault();
		},
		onDrop: ordering !== void 0 ? onDrop : void 0,
		style: compact ? void 0 : { borderLeftColor: epicColor },
		title: cardTitle(t, wf, compact, progress, rel),
		onClick: () => onOpen(),
		role: "button",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-card-l1",
				children: [
					ordering?.kind === "queued" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-order-pos",
						"data-order-pos": ordering.pos ?? 0,
						title: `Queue position ${ordering.pos ?? 0}`,
						children: ordering.pos ?? ""
					}),
					ordering?.kind === "atwork" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-order-dot",
						"data-order-dot": "work",
						title: "At work"
					}),
					(ordering?.kind === "hold" || ordering?.kind === "paused") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-order-dot",
						"data-order-dot": ordering.kind === "hold" ? "hold" : "paused",
						title: ordering.kind === "hold" ? "Holding a slot at the human gate" : "Paused by you (no slot)"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-dot",
						"data-state": state4
					}),
					!compact && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-state",
						"data-state": state4,
						children: STATE4_LABEL[state4]
					}),
					t.paused && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-paused",
						"data-paused": "1",
						"data-paused-phase": t.paused_phase || "pending",
						title: t.paused_phase === "at_gate" ? "Halted at the stage gate: next stage not dispatched; click Resume to continue" : "Pause accepted: the current stage (incl. in-flight agent) finishes, then stops",
						children: pausedBadgeText(t.paused_phase)
					}),
					kindBadge && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-kind",
						"data-kind-badge": kindBadge.text,
						title: `Kind: ${kindBadge.text}`,
						children: kindBadge.text
					}),
					(() => {
						const badge = closeHealthBadgeOf(t);
						return badge !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-card-health",
							"data-close-health": closeHealthOf(t),
							title: t.close_health_reason || badge,
							children: badge
						});
					})(),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-id",
						children: t.id
					}),
					(peerViewers?.length ?? 0) > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						title: `Viewed from another tab: ${(peerViewers ?? []).map((v) => v.who).join(", ")}`,
						children: "👀"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-title",
						"data-wb-row-title": ticketDisplayTitle(t),
						"data-title-src": t.title?.trim() ? "title" : t.title_or_first ? "first" : "id",
						children: ticketDisplayTitle(t)
					}),
					orderable && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-order-ctl",
						"data-order-ctl": "",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-order-grip",
								"data-order-grip": "",
								title: "Drag to reorder",
								"aria-label": `Drag to reorder ${t.id}`,
								children: "⋮⋮"
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								type: "button",
								className: "wb-order-arrow",
								disabled: ordering?.busy,
								"aria-label": `Move ${t.id} up`,
								title: "Move up",
								onClick: (ev) => {
									ev.stopPropagation();
									ordering?.onMove?.(-1);
								},
								children: "⌃"
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								type: "button",
								className: "wb-order-arrow",
								disabled: ordering?.busy,
								"aria-label": `Move ${t.id} down`,
								title: "Move down",
								onClick: (ev) => {
									ev.stopPropagation();
									ordering?.onMove?.(1);
								},
								children: "⌄"
							})
						]
					}),
					!compact && t.epic && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-epic",
						style: {
							borderColor: epicColor,
							["--epic-c"]: epicColor,
							color: epicChipColor()
						},
						title: `Epic: ${t.epic}`,
						onClick: (ev) => {
							ev.stopPropagation();
							onOpenEpic?.(t.epic ?? "");
						},
						children: t.epic
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-card-l2",
				children: [
					compact && stageLabel !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-stage",
						"data-wb-row-stage": stageLabel,
						children: stageLabel
					}),
					compact && t.epic && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-epic",
						style: {
							borderColor: epicColor,
							["--epic-c"]: epicColor,
							color: epicChipColor()
						},
						title: `Epic: ${t.epic}`,
						onClick: (ev) => {
							ev.stopPropagation();
							onOpenEpic?.(t.epic ?? "");
						},
						children: t.epic
					}),
					(!compact || progress) && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-progress",
						"data-state": progress?.state ?? "",
						children: progress ? progress.text : t.updated || ""
					}),
					!compact && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-time",
						children: rel ?? (t.updated || "")
					}),
					t.role && !compact && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-card-role",
						children: ["· ", t.role]
					}),
					!compact && dots.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-card-lane",
						title: `Stage dots (${dots.length})`,
						children: dots.map((d, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-card-lane-dot",
							"data-visual": d,
							"data-state": state4
						}, i))
					}),
					compact && ordering?.dotsLit !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-stage-dots",
						"data-lit": ordering.dotsLit,
						title: `Stage dots: ${ordering.dotsLit} of 10`,
						children: Array.from({ length: 10 }, (_, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-stage-dot",
							"data-on": i < (ordering.dotsLit ?? 0) || void 0
						}, i))
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-card-ops",
				onClick: (ev) => ev.stopPropagation(),
				children: [
					state4 === "waiting" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn wb-card-btn-primary",
						onClick: (ev) => {
							ev.stopPropagation();
							onOpen("review");
						},
						children: "Sign →"
					}),
					state4 === "blocked" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn wb-card-btn-blue",
						onClick: (ev) => {
							ev.stopPropagation();
							onOpen("blocked");
						},
						children: "View Reason"
					}),
					!compact && ops.includes("advance") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn",
						disabled: busy,
						onClick: stop(onAdvance),
						children: "Advance"
					}),
					!compact && ops.includes("dispatch-next") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn",
						disabled: busy,
						onClick: stop(onDispatch),
						children: "Dispatch next"
					}),
					!compact && ops.includes("unblock") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn",
						disabled: busy,
						onClick: stop(onUnblock),
						children: "Unblock"
					}),
					!compact && ops.includes("rework") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn wb-card-btn-danger",
						disabled: busy,
						onClick: stop(onRework),
						children: "Rework"
					}),
					!compact && ops.includes("pause") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn",
						disabled: busy,
						onClick: stop(onPause),
						title: "Pause between stages: current stage (incl. in-flight agent) finishes, then stops; no next stage",
						children: "Pause"
					}),
					!compact && ops.includes("resume") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn wb-card-btn-green",
						disabled: busy,
						onClick: stop(onResume),
						title: "Resume: release the stage gate and keep dispatching",
						children: "Resume"
					}),
					!compact && ops.includes("close") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-card-btn wb-card-btn-green",
						disabled: busy,
						onClick: stop(onClose),
						children: "Done"
					})
				]
			})
		]
	});
}
//#endregion
//#region src/client/sandbar-dwell.ts
/**
* sandbar-dwell —— closed dev-lane ticket dwell window for the sidebar groups
* (pure logic layer, zero react/platform deps so node can black-box import it,
* same layering precedent as ticket-list-model.ts).
*
* Host order 261008 option A: the sidebar Settings popover (gear + "Sandbar
* dwell" input) is retired, so the dwell window is PINNED at 24 hours. The
* window behaviour itself stays real: a closed dev-lane ticket leaves the left
* column 24 h after it closes (close_ts, falling back to created). Inspection
* rows never go through this window — their closed-row window is the engine's
* own R8 window (two-window split, see sidebar.tsx group assembly).
*
* Stored-value policy (chosen over clamp): the legacy localStorage key is
* IGNORED and removed, not clamped. With the knob gone, any surviving stored
* value (e.g. a previously typed 999) silently steering a user-visible window
* is exactly the failure this retirement must rule out; clamping would keep
* hidden state alive for values above the pin.
*
* NOTE: sandbarHours() is now the pin point of this whole rule — the one-shot
* legacy-key removal inside it is deliberate and idempotent, not dead weight.
* Do not "simplify" the delete away: that resurrects hidden stored state with
* no knob to clear it.
*/
/** Legacy localStorage key written by the retired dwell-hours input. */
const SANDBAR_KEY = "sandbar-workbench-sandbar-v1";
/**
* Single reader of the dwell window: always the pinned 24 h. As a one-shot
* side effect it deletes the legacy stored key so a stale custom value can
* never steer the window while the knob is gone (idempotent, guarded for
* non-browser environments).
*/
function sandbarHours() {
	if (typeof localStorage !== "undefined") try {
		localStorage.removeItem(SANDBAR_KEY);
	} catch {}
	return 24;
}
/** Open = lifecycle not closed out; project groups always list these. */
const isDwellOpen = (t) => t.status !== "closed" && t.status !== "verified";
/**
* Dwell predicate: closed rows stay while close_ts (fallback created) is
* inside the pinned window. Boundary is strict `<` — a row at exactly 24 h
* has left.
*/
const inSandbar = (t, nowS) => {
	if (isDwellOpen(t)) return true;
	const h = sandbarHours();
	if (h <= 0) return false;
	const ts = t.close_ts || t.created || 0;
	return ts > 0 && nowS - ts < h * 3600;
};
//#endregion
//#region src/client/queue-model.ts
/**
* Unwrap a read-face HTTP reply into the raw face. Two lawful shapes exist:
* the host wraps (`{ok:true, result:<face>}`) and a bare read_state is accepted
* too (the reply contract allows it). A `{ok:false,...}` refusal or anything
* else unwraps to null — the caller renders the order-free list.
*/
function concFaceFromReply(reply) {
	if (reply === null || typeof reply !== "object" || Array.isArray(reply)) return null;
	const r = reply;
	if (r.ok === true && r.result !== void 0 && r.result !== null) return r.result;
	if ("ok" in r) return null;
	return r;
}
/** Parse + validate the read face. Returns null on any malformed input. */
function parseConcFace(raw) {
	if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
	const r = raw;
	const holderReason = {};
	if (r.holders !== void 0) {
		if (!Array.isArray(r.holders)) return null;
		for (const h of r.holders) {
			if (h === null || typeof h !== "object") return null;
			const id = h.ticket;
			if (typeof id !== "string" || id === "") return null;
			holderReason[id] = String(h.reason ?? "");
		}
	}
	const queue = [];
	if (r.queue !== void 0) {
		if (!Array.isArray(r.queue)) return null;
		for (const e of r.queue) {
			let id = e;
			if (e !== null && typeof e === "object") id = e.ticket;
			if (typeof id !== "string" || id === "") return null;
			if (queue.includes(id)) return null;
			queue.push(id);
		}
	}
	return {
		holderReason,
		queue
	};
}
/**
* Classify one ticket row. `paused` is the engine row's own pause flag
* (host-paused tickets hold no slot, so the face never lists them — the pause
* flag is the only source). Returns undefined for rows the face says nothing
* about (closed tickets, unknown ids): they get no order marks at all.
*/
function orderKindOf(id, face, paused) {
	if (face === null) return void 0;
	if (face.queue.includes(id)) return "queued";
	const reason = face.holderReason[id];
	if (reason === "running") return "atwork";
	if (reason === "human-hold") return "hold";
	if (paused === true) return "paused";
}
/**
* New queue after moving one queued ticket one slot up (-1) or down (+1).
* Returns null when the move is impossible (edge of the queue, id not in the
* queue, malformed direction) — the caller then POSTs nothing.
*/
function moveTicket(queue, id, dir) {
	if (dir !== -1 && dir !== 1) return null;
	const i = queue.indexOf(id);
	if (i < 0) return null;
	const j = i + dir;
	if (j < 0 || j >= queue.length) return null;
	const next = queue.slice();
	[next[i], next[j]] = [next[j], next[i]];
	return next;
}
/**
* New queue after dropping `dragId` onto `dropId`'s slot (the handgrip path —
* arrows use moveTicket). Returns null unless both ids are queued.
*/
function reorderMoveTo(queue, dragId, dropId) {
	const from = queue.indexOf(dragId);
	const to = queue.indexOf(dropId);
	if (from < 0 || to < 0 || from === to) return null;
	const next = queue.slice();
	next.splice(from, 1);
	next.splice(to, 0, dragId);
	return next;
}
/**
* Guard for the POST body: the order must be a permutation of the face's
* current queue (the engine's own reorder() refuses anything else — mirroring
* the check client-side turns an obvious mistake into a no-op instead of a
* round-trip refusal). Returns null when `order` is not a permutation.
*/
function permutationOf(queue, order) {
	if (!Array.isArray(order)) return null;
	const want = [];
	for (const t of order) {
		if (typeof t !== "string" || t === "") return null;
		want.push(t);
	}
	if (want.length !== queue.length) return null;
	const a = [...queue].sort();
	const b = [...want].sort();
	for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return null;
	return want;
}
function stageDotsLit(stageIndex, closed = false) {
	if (closed) return 10;
	if (!Number.isInteger(stageIndex) || stageIndex < 0) return 0;
	return Math.min(stageIndex + 1, 10);
}
/** Project-row counts from the face: `X at work · Y waiting`. Raw numbers only — the sentence lives in CSS/none. */
function faceCounts(face) {
	if (face === null) return {
		atWork: 0,
		waiting: 0
	};
	return {
		atWork: Object.keys(face.holderReason).length,
		waiting: face.queue.length
	};
}
//#endregion
//#region src/client/executor-view-model.ts
/**
* executor-view-model.ts —— 执行器入口视图的纯决策层（t261003-09 修订）。
*
* t260929-22 曾在这里放「Chat 分支裁决」（chatLegVerdict）；宿主实测该分支恒挂在
* 「Resolving the declared executor session…」（无超时/无重试/无失败面），t261003-09
* 把整行切换器连同 Chat 分支一起退役——本模块只剩面板 URL 构造与主题名解析两个纯面。
*
* 主题（t261003-09 缺陷 2）：面板是同源 iframe，父页 CSS 自定义属性穿不过边界，
* 由父页解析出主题名后经 `?theme=` 深链传给面板页（面板侧双调色板，见 panel-page.ts）。
* 主题名全仓统一词表 = 'light' | 'dark'（一词一义，不混第二种拼写）。
* 解析纯函数 resolveThemeName 在 node 可裸 import 直测（tests/executor-entry-model.mjs）。
*/
/**
* 从控制台解析出的背景色推主题名（纯函数；畸形输入显式回落 'light'，不 throw、不猜暗色）。
* 认 #rgb/#rrggbb 与 rgb()/rgba()；相对亮度 >= 0.5 判 light。解析失败（空串、截断值、
* var() 链、'inherit' 等任何非字面色）一律 'light'——错误输入当浅色处理是显式降级，
* 单测逐例锚定。
*/
function resolveThemeName(bg) {
	const s = typeof bg === "string" ? bg.trim().toLowerCase() : "";
	let r = NaN, g = NaN, b = NaN;
	const hex = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
	if (hex) {
		const h = hex[1];
		const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
		r = parseInt(full.slice(0, 2), 16);
		g = parseInt(full.slice(2, 4), 16);
		b = parseInt(full.slice(4, 6), 16);
	} else {
		const fn = s.match(/^rgba?\(([^)]*)\)$/);
		if (fn) {
			const parts = fn[1].split(/[,\s/]+/).filter(Boolean);
			if (parts.length >= 3) {
				const num = (v) => v.endsWith("%") ? Math.round(parseFloat(v) * 2.55) : parseFloat(v);
				r = num(parts[0]);
				g = num(parts[1]);
				b = num(parts[2]);
			}
		}
	}
	if (![
		r,
		g,
		b
	].every((v) => Number.isFinite(v) && v >= 0 && v <= 255)) return "light";
	return (.2126 * r + .7152 * g + .0722 * b) / 255 >= .5 ? "light" : "dark";
}
/**
* 控制台当下主题名（组件侧薄壳读 computed 值，纯判定在 resolveThemeName）。
* 平台外壳未暴露主题翻转事件：视图挂载时解析一次，翻主题后重开视图/刷新生效
* （t261003-09 交接报告已声明的机制限制）。读不到/异常 → 显式 'light'。
*/
function consoleThemeName() {
	try {
		const cs = getComputedStyle(document.documentElement);
		return resolveThemeName(cs.getPropertyValue("--dsw-alias-bg-base") || cs.getPropertyValue("--dsw-alias-bg-primary"));
	} catch {
		return "light";
	}
}
/** 面板页同源 URL（深链 ?project=；空键不带项目参数；theme 恒随父页解析结果拼接；
*  运行时畸形 theme 实参归一 'light'——类型层外的防御，不产出第三种主题名）。 */
function executorPanelUrl(projectKey, theme = "light") {
	const t = theme === "dark" ? "dark" : "light";
	return projectKey === "" ? "/sandbar-executor-panel/?theme=" + t : "/sandbar-executor-panel/?project=" + encodeURIComponent(projectKey) + "&theme=" + t;
}
/** 宿主 → 面板的结果回执（面板只渲染一行 STE 文案，不做轮询/重试/状态条）。 */
const OPEN_SESSION_RESULT_MSG_TYPE = "sandbar-executor-panel:open-session-result";
function ExecutorView({ projectKey, openExecutorSession, openTicketOverlay }) {
	const [panelState, setPanelState] = (0, react.useState)({
		ok: false,
		detail: "checking…"
	});
	const frameRef = (0, react.useRef)(null);
	(0, react.useEffect)(() => {
		const ac = new AbortController();
		setPanelState({
			ok: false,
			detail: "checking…"
		});
		fetch(executorPanelUrl(projectKey), { signal: ac.signal }).then((res) => {
			if (res.ok) setPanelState({
				ok: true,
				detail: ""
			});
			else setPanelState({
				ok: false,
				detail: `panel route answered HTTP ${res.status} — the executor-panel plugin may not be loaded; reload the console after (re)starting it.`
			});
		}).catch((e) => {
			if (ac.signal.aborted) return;
			setPanelState({
				ok: false,
				detail: `panel route unreachable: ${e instanceof Error ? e.message : String(e)}`
			});
		});
		return () => ac.abort();
	}, [projectKey]);
	(0, react.useEffect)(() => {
		const onMessage = (e) => {
			if (e.origin !== window.location.origin) return;
			const frame = frameRef.current;
			if (!frame || e.source !== frame.contentWindow) return;
			const d = e.data;
			if (!d || typeof d !== "object") return;
			if (d.type === "sandbar-executor-panel:open-session") {
				const ok = typeof d.sessionId === "string" && d.sessionId !== "" && openExecutorSession(d.sessionId);
				frame.contentWindow?.postMessage({
					type: OPEN_SESSION_RESULT_MSG_TYPE,
					ok
				}, window.location.origin);
				return;
			}
			if (d.type === "sandbar-executor-panel:open-ticket") {
				if (typeof d.ticketId === "string" && d.ticketId !== "" && openTicketOverlay) openTicketOverlay(d.ticketId);
				return;
			}
		};
		window.addEventListener("message", onMessage);
		return () => window.removeEventListener("message", onMessage);
	}, [openExecutorSession, openTicketOverlay]);
	const theme = consoleThemeName();
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-executor-view",
		"data-wb-executor-view": "",
		"data-project": projectKey,
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: EXECUTOR_CSS }), panelState.ok ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("iframe", {
			ref: frameRef,
			"data-wb-executor-frame": "",
			className: "wb-executor-frame",
			title: `Executor panel — ${projectKey}`,
			src: executorPanelUrl(projectKey, theme)
		}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-executor-note",
			role: "alert",
			"data-wb-executor-note": "",
			children: ["Executor panel unavailable for this project. ", panelState.detail]
		})]
	});
}
const EXECUTOR_CSS = `
.wb-executor-view { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.wb-executor-frame { flex: 1; width: 100%; border: 0; background: transparent; }
.wb-executor-note { margin: 16px; padding: 12px 14px; border: 1px solid var(--dsw-derive-border, #444); border-radius: 8px;
  color: var(--dsw-derive-fg, #ccc); font-size: 13px; line-height: 1.5; max-width: 640px; }
`;
//#endregion
//#region src/host/inspection-face.ts
/**
* inspection-face —— 巡检票板面纯函数层（t260915-08，方案 v2 R4/R5/R6）。
*
* 零 react / 零平台依赖，node 可裸 import 黑盒单测
* （tests/t260915-08-inspection-face.mjs，ticket-list-model.ts 同款分层先例）。
*
* 为什么住 host/：巡检段的**短名排版映射**住这里（行卡/时间线的 ≤4 字压缩，
* 宿主 UI 职责）；阶段词表本身自 t260916-05 起真源在引擎（inspection_flow.py
* STAGES 声明 + template_topology 导出），泳道图吃快照 topology 键（通用渲染器），
* 本表的词表一致性由同步锁源级锚定（tests/t260916-05-inspection-topology-lock.mjs
* ——「STAGES 改了不改本表，锁必红」）。client 侧 context-fold.ts 已有 import
* host 模块的先例（session-charter）。
*
* 行数据源=引擎 client.py ticket-list {kind:"inspection"} 行（_row_from_inspection_face）：
*   {id, title, kind:"inspection", instance_id, period, stage, stage_state, status,
*    findings:{high,med,low,total}, heartbeat, report_path, awaiting_gate,
*    human_gate, blocked_reason, gate_error, engine:"inspection", ...}
* 引擎行是**不可信外部输入**：本层所有函数对畸形输入降级（不抛、不编造）。
*/
/**
* 巡检段短名映射（t260916-05 定性收窄）：**宿主排版职责**，不是阶段词表真源。
* 段词表的编码真源=引擎 inspection_flow.py `InspectionPeriodicWorkflow.STAGES`
* （机器可读阶段声明）；泳道图面消费引擎拓扑导出（快照 topology 键→lane-map
* 通用渲染器，本常量零参与）。本表只剩 ≤4 字短名的行卡/时间线排版压缩，与引擎
* STAGES 的 id 序/name 一致性由同步锁钉死（tests/t260916-05-inspection-topology
* -lock.mjs 源级锚：STAGES 改了不改本表，锁必红）。
*/
const INSPECTION_TOPOLOGY = [
	{
		id: "setup",
		name: "泳道准备",
		short: "Setup"
	},
	{
		id: "suite",
		name: "巡检泳道套件",
		short: "Suite"
	},
	{
		id: "inspect",
		name: "巡检审查",
		short: "Inspect"
	},
	{
		id: "report",
		name: "落账",
		short: "Report"
	},
	{
		id: "close",
		name: "人审收口",
		short: "Close"
	}
];
/** 消费外部行=不可信输入的取串助手（非串→''）。 */
function strOf$1(v) {
	return typeof v === "string" ? v : "";
}
/** 是否巡检行：kind 或 engine 标记任一命中（引擎行带 kind=inspection）。 */
function isInspectionRow(t) {
	return t !== null && typeof t === "object" && (t.kind === "inspection" || t.engine === "inspection");
}
/** 发现数计数的最小形状守卫（引擎 summary/findings 畸形时全 0，不编造）。 */
function findingsCountOf(row) {
	const f = row?.findings;
	if (f !== null && typeof f === "object") {
		const o = f;
		const num = (v) => typeof v === "number" && Number.isFinite(v) ? v : 0;
		return {
			high: num(o.high),
			med: num(o.med),
			low: num(o.low),
			total: num(o.total)
		};
	}
	return {
		high: 0,
		med: 0,
		low: 0,
		total: 0
	};
}
/**
* 详情面发现数计数（t260915-08 实证补）：行（ticket-list）与详情（ticket-query）
* 的发现数据形状不同——行 findings={high,med,low,total} 计数字典；详情 face.summary=
* {high,med,low} 计数字典、face.findings=发现清单（列表）。本函数吃详情形状：
* summary 字典优先（引擎真值），缺/畸形时按 findings 清单逐条 severity 重计，
* 两者皆缺=全 0（不编造）。行形状请用 findingsCountOf。
*/
function inspectionSummaryOf(face) {
	const src = face !== null && typeof face === "object" ? face : {};
	const num = (v) => typeof v === "number" && Number.isFinite(v) ? v : 0;
	const s = src.summary;
	if (s !== null && typeof s === "object") {
		const o = s;
		const high = num(o.high);
		const med = num(o.med);
		const low = num(o.low);
		const total = num(o.total) || high + med + low;
		if (high || med || low || total) return {
			high,
			med,
			low,
			total
		};
	}
	const list = Array.isArray(src.findings) ? src.findings : [];
	const high = list.filter((f) => f?.severity === "high").length;
	const med = list.filter((f) => f?.severity === "med").length;
	const low = list.filter((f) => f?.severity === "low").length;
	return {
		high,
		med,
		low,
		total: high + med + low
	};
}
/** 阶段短名：拓扑命中用短名，未命中截断原词（stageShortOf 同口径），畸形→''。 */
function inspectionStageShort(stage) {
	const s = strOf$1(stage);
	if (s === "") return "";
	const hit = INSPECTION_TOPOLOGY.find((st) => st.id === s);
	if (hit) return hit.short;
	return [...s].length > 4 ? [...s].slice(0, 4).join("") + "…" : s;
}
/**
* 巡检行的一句进展（行卡 progress prop 数据源，t260904-17 同构）。
* 待签判定**只读 stage_state/awaiting_gate**（引擎 R4：face.human_gate 签字前常态缺键，
* 不得依赖）；发现数来自 findings 字段（引擎已并好）。畸形行 → undefined
* （行卡降级只显相对时间）。闭合一律 {state:'done'}（收口折叠吃掉，正常语义）。
*/
function inspectionProgressOf(row) {
	if (row === null || typeof row !== "object") return void 0;
	const stageState = strOf$1(row.stage_state);
	const status = strOf$1(row.status);
	const c = findingsCountOf(row);
	const findingsTxt = `findings H${c.high}/M${c.med}/L${c.low}`;
	if (status === "closed") return {
		state: "done",
		text: `Closed · ${findingsTxt}`
	};
	if (stageState === "awaiting-human" || row.awaiting_gate === true) return {
		state: "awaiting-human",
		text: `Awaiting your signature · ${findingsTxt}`
	};
	if (stageState === "blocked") {
		const reason = strOf$1(row.blocked_reason);
		return {
			state: "blocked",
			text: `Blocked${reason ? ": " + reason : " · see detail"}`
		};
	}
	if (stageState === "running" || stageState === "awaiting" || stageState === "") {
		const stage = inspectionStageShort(row.stage);
		return {
			state: "running",
			text: `${stage ? stage + " · " : ""}${findingsTxt}`
		};
	}
	return {
		state: stageState,
		text: findingsTxt
	};
}
/**
* 巡检板面端点（t260915-08 建的引擎 ticket-list{kind:inspection} 薄壳）。左栏
* 分拣制（t260915-19 方案 v2）与中列合流同吃此端点——URL 串收本单点，防两处
* 字面量漂移（node.ts 注册路径与本串一致性由 UT 源级锚看守）。
*/
const INSPECTION_TICKETS_URL = "/sandbar-workbench/api/wf/inspection/tickets";
/**
* 左栏分拣的行防御过滤（端点行=不可信外部输入，与引擎行同纪律）：非数组→[]、
* 元素非对象或非巡检行（kind/engine 都不标）剔除，其余保序。绝不抛、绝不编造。
*/
function inspectionSidebarRows(rows) {
	if (!Array.isArray(rows)) return [];
	return rows.filter((r) => isInspectionRow(r));
}
/**
* 左栏分拣（t260915-19 方案 v2）：巡检行按行 project（t260915-20 起=ProjectKey
* SA 直读）归位——命中在册项目 key → byProject[key]；project 空/非串/不在册
* （20 之前老票、注册表隔离 key、摘除项目）→ unowned（兜底组显式呈现，绝不
* 静默丢失）。registeredKeys 畸形（非数组）按空集处理；行序输入输出保持端点原序。
*/
function inspectionSplitByProject(rows, registeredKeys) {
	const keySet = new Set((Array.isArray(registeredKeys) ? registeredKeys : []).filter((k) => typeof k === "string" && k !== ""));
	const byProject = {};
	const unowned = [];
	for (const row of inspectionSidebarRows(rows)) {
		const p = strOf$1(row.project);
		if (p !== "" && keySet.has(p)) (byProject[p] ??= []).push(row);
		else unowned.push(row);
	}
	return {
		byProject,
		unowned
	};
}
/**
* 左栏巡检降级文案单点：失败=保上次成功快照 + 显式原文提示，绝不吞成空列表
* （KI-008/t260910-04 R3 同纪律；KI-018① 合规面——错误文案进横幅，不进数据字段）。
* 词表与中列同源（index.tsx「巡检板面拉取失败，显示上次快照（自动重试中）」同族），
* 非串 err 走 String() 兜底不抛。
*/
function inspectionDegradedNote(err) {
	return `Inspection panel fetch failed (showing last snapshot, auto-retrying): ${typeof err === "string" ? err : String(err ?? "")}`;
}
//#endregion
//#region src/client/sidebar.tsx
/**
* sandbar-workbench · 侧栏接管 —— 双列布局（项目分组+工单 | 四视图）
*
* 注册到 sidebar.workspaces 槽（single，priority=-10 抢占 shell 默认浏览器——lowest renders）。
* Shell 传 ownerProps: wide / expandSidebar。
* wide=false 时只显品牌图标；wide=true 时显完整双列。
*
* 左列：项目组（可折叠，项目名分隔，只列进行中工单，两行式条目：行1=title，行2=彩色工单号 + role·创建时长）；
*       每组头名前带项目色点（票② R7，projectColor 确定性色板）；组头下、工单
*       列表上有项目内会话区一横排（session-entry 第 3 面①：正方形「+」+
*       正方形数字 tab，编号=项目内登记顺序关闭不回收，超宽换行；+ 钮与激活
*       tab 带项目色，票② R7；组件 project-session-row.tsx，动作=本组件
*       useSessionEntry 实例）。
*       顶部会话入口行已随票② R8 退役（t260904-05：顶部行组件及其
*       顶部行样式族全清，src 无残留符号）；出厂「⊕ New Session」钮的隐藏注入**留守**
*       （拍板 1：职责=压制全局新建入口，出厂钮不回显——useHideFactoryNewSession
*       effect 以 aria-label（session-entry.tsx FACTORY_NEW_LABELS，zh/en 全集）
*       在 SidebarRoot 直接子 button 上定位出厂钮置 display:none，零 CSS 类名
*       匹配，MutationObserver 兜防复活，卸载/折叠 cleanup 还原）。
*       记账层（localStorage 账册，只登记 UI 主动打开/新建；磁盘存量/工单/
*       subagent 会话不进账册）供项目内会话区消费，规则=shared/sessions.ts。
*       右栏 chat 项目色带（票② R7）：chat-project-band.ts 装饰器，归属=
*       listState.current → 账册 project 推导（下方 effect），不在册不渲染。
*       项目组头行右对齐五个项目级视图入口图标（票③ 11b 统一 SVG 图标族）：工单列表 /
*       文档 / 模型路由 / 立项单 / 项目设置（第五枚=面D 设置弹层入口）
*       （t260905-06：旧提法退役，原位换「文档」入口——仓根 docs/ 定稿库人读
*       视图 + notes/ 观察窗；t260915-10 起默认跟随本行项目，页内选择器可手动切）
*       （t260827-01：立项单从「左列可折叠列表区」改为项目级图标，与其他三视图同款；
*       左列不再显示立项列表，点图标后中列显示立项清单）。
*       项目组 = server/projects.yaml 注册表（260823 多项目化：project 是逻辑概念，
*       1:N 对应目录）；每组工单按 ?project=<key> 单独拉取（Temporal ProjectKey SA 过滤）。
*       t260915-19 起左栏收录巡检票：巡检 workflow 因引擎类型过滤隔离进不了
*       ?project= 通路（client.py cmd_ticket_list 缺省只拼 dev-lane 模板类型），
*       故左栏并行拉 /wf/inspection/tickets 端点做**客户端分拣**——行 project
*       （t260915-20 起=ProjectKey SA 真源）命中在册项目后与该项目 dev 行合并、
*       统一口径排序（t260916-15 宿主实报「巡检票恒沉底」：在等你/受阻→在跑→
*       已完成，级内 updated_ts 倒序，巡检行不因数据来源沉底），空/不在册
*       （20 之前老票、隔离 key）落「巡检」兜底组（显式不静默丢失）；巡检行带
*       类别徽标（INSPECTION_ROW_BADGE chip）一眼可辨数据来源。
* 中列：四视图由 index.tsx 注入（views prop）——工单台 WorkbenchSection（本插件）、
*       文档 DocsSection（本插件，t260905-06）、模型 ProvidersSection（providers 插件）、
*       立项单 EpicSection（本插件，t260826-02；空代号=立项清单，带代号=详情）。
*       260823 起它们不再占 chat 顶部页签。t260903-07 起：点工单只在中列开详情抽屉，
*       右栏 chat 恒为单全局会话不再切换（每工单会话联动下线，数据留存）。
*       未选项目时中列显占位（不自动选第一个项目——不造隐形缺省）。
*/
const CONCURRENCY_URL = "/sandbar-workbench/api/wf/concurrency";
const CONCURRENCY_REORDER_URL = "/sandbar-workbench/api/wf/concurrency/reorder";
/** 巡检行卡的 wf 形状（t260915-19）：compact 无站道点，仅喂悬停阶段短名；
*  拓扑=宿主声明面单点（host/inspection-face.ts），不 import index.tsx 防循环。 */
const INSPECTION_WF_LIKE = { stages: INSPECTION_TOPOLOGY };
/**
* 状态色（用户拍板口径）：红=有问题（blocked/rework）、黄=待审核（awaiting-human/settled）、
* 蓝=运行中（running）、绿=完成（verified/closed）、灰=等待（awaiting）。
*/
/** 未完成 = 生命周期未收口（dispatched/settled/rework）。项目组里只列这些。 */
const isOpen = (t) => t.status !== "closed" && t.status !== "verified";
const CSS$2 = `${DERIVE_TOKENS_CSS}
.wb-sb { display:flex; flex-direction:column; height:100%; /* t260905-08：底改自适应 alias（平台 fill 层级高于 :root 注入无法跟随看守档位，可读性收敛到 alias 对）；装饰性 fill 见 --dsw-specific-sidebar-fill 保留在 group-head */ background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); color:var(--dsw-derive-fg,#1f2328); font-size:12px; }
/* 轨条态：仅图标 */
.wb-sb.rail { width:48px; align-items:center; padding-top:12px; }
.wb-sb.rail .wb-sb-icon { width:28px; height:28px; border-radius:6px; background:var(--dsw-alias-brand-primary,#7c3aed); display:flex; align-items:center; justify-content:center; font-size:14px; cursor:pointer; }
/* 展开态：双列。整窗三栏比例 左(项目+工单)15% : 中(视图)60% : 右(chat)25% ——
   左+中=侧栏占 75%（见下方 frame 第一轨改写），侧栏内部左右子列按 1:4 分。 */
.wb-sb.wide { flex-direction:row; }
/* t260929-22 gen3 勘误（arbitration A/B 实证）：gen2 曾把左列 min-width 提到
   320px 给入口段让宽——被 t260904-17/t260915-09 双场景 A/B 实证为破坏壳层几何的
   单变量（shell resize handle 压住内容），此处归还 180px。gen4 勘误：gen3 的
   行下悬停图标条同样改了行外命中面（t260915-09 A/B 实证），随之退役；可达性
   最终落点=图标簇行内收纳（见 .wb-view-icons gen4 注）。 */
.wb-sb-left { flex:0 1 380px; min-width:180px; display:flex; flex-direction:column; border-right:1px solid var(--dsw-alias-border-l1,#333); }
/* CL-3 (t261006-18, design §2.2): the left column's width base becomes 380px
   (flex-basis; "below 340px the titles are cut too hard"). min-width keeps the
   frozen 180px contract (t260929-22 arbitration A/B proof: raising min-width
   crushes the shell resize geometry) - normal windows get 380px, the column
   may shrink under shell pressure instead of fighting the shell. */

/* position:relative —— 工单详情抽屉（index.tsx .wb-drawer，absolute）的定位祖先，
   让抽屉铺满中列而不是全窗（260824 用户拍板：详情显在中列）。 */
.wb-sb-right { flex:4 1 0; display:flex; flex-direction:column; overflow:hidden; min-width:200px; background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); position:relative; }
/* host 陈旧全局提醒（t260902-03）：中列共享容器顶部横幅，flex:none 不挤占四视图与
   下栏；琥珀底一眼可辨，与 running 绿/blocked 红色板错开。 */
.wb-stale-banner { flex:none; display:flex; align-items:center; gap:10px; padding:8px 12px;
  background:var(--dsw-derive-dark-warn-bg,#7a4a06); color:var(--dsw-derive-dark-warn-fg,#ffe9c4); border-bottom:1px solid var(--dsw-derive-warn,#b8860b); font-size:12px; }
.wb-stale-banner .wb-stale-msg { flex:1; line-height:1.5; }
.wb-stale-banner .wb-stale-msg strong { color:var(--dsw-derive-dark-amber,#ffd166); }
.wb-stale-banner .wb-stale-dismiss { flex:none; border:1px solid var(--dsw-derive-warn,#b8860b); background:transparent;
  color:var(--dsw-derive-dark-warn-fg,#ffe9c4); border-radius:6px; padding:2px 10px; font:inherit; font-size:12px; cursor:pointer; }
.wb-stale-banner .wb-stale-dismiss:hover { background:rgba(255,255,255,0.12); }
/* Bottom strip under the middle column (fixed height, from metrics M2a).
   t261008-21: the metrics entrance and the gear Settings popover are both
   retired; only the spacer span remains, holding the original height (no reflow). */
.wb-sb-foot{display:flex;align-items:center;gap:8px;height:34px;padding:0 10px;border-top:1px solid var(--dsw-alias-border-l1,#333);flex:none;font-size:12px}
.wb-sb-foot-sp{flex:1}
/* 项目组 */
.wb-ticket-list { flex:1; overflow-y:auto; }
/* UI-1 (t261005-09): brand first row — replaces the old "Projects" header slot.
   26px, zero extra height (the row *is* the header; no separate top banner is
   added). Mark = the "slanting sandbar" logo (261004 topbar-banner design note
   section 3, candidate C: two offset rounded slanted bars; Chinese-named file in
   notes/discussions/). No fold button, no theme button (both
   ruled out in the same design note). Hiding the platform's own topbar banner is
   a named follow-up (anchor+guard discipline), NOT done here — worst accepted
   case is the platform banner remaining visible, never a blank sidebar. */
.wb-brand-row { display:flex; align-items:center; gap:6px; height:26px; flex:none;
  padding:0 10px; border-bottom:1px solid var(--dsw-alias-border-l1,#333); }
.wb-brand-mark { display:inline-flex; flex:none; line-height:0; }
.wb-brand-word { font-weight:600; font-size:12px; }
.wb-brand-count { margin-left:auto; font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; }
/* UI-1 (t261005-09) as revised by t261008-08 (mock v11 alignment): the project
   block drops its 3px project-colour left bar — the mock's .proj carries only a
   bottom hairline; project identity stays on the badge + name. The selected
   block keeps its 6% colour wash (colour is not the only channel). */
.wb-project-block { border-bottom:1px solid var(--dsw-derive-border,#d0d7de); }
.wb-project-block[data-selected=true] { background:color-mix(in srgb, var(--wb-proj-color, transparent) 6%, transparent); }
.wb-group-head { display:flex; align-items:center; gap:5px; padding:7px 8px 5px; cursor:pointer; font-weight:600; position:sticky; top:0; background:var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff)); z-index:1; }
.wb-group-head:hover { background:rgba(255,255,255,0.05); }
.wb-group-caret { font-size:9px; color:var(--dsw-derive-muted,#57606a); width:10px; }
/* t260929-22 gen1（acceptance 打回）：入口段=名字+计数+弹性空档，flex:1 吃掉
   行内非图标区——1280 宽默认窗下项目名可读可点（行中部点击落入口段不落图标）；
   name min-width:0 只为 ellipsis 生效，宽度由入口段保证。 */
.wb-group-entry { flex:1 1 0; min-width:0; display:flex; align-items:center; gap:5px; cursor:pointer; }
.wb-group-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.wb-group-count { margin-left:auto; font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; flex:none; }
/* CL-3 (t261006-18): the project row reports two numbers on the right, X at work / Y waiting (numbers only, no sentences). */
.wb-group-conc { font-size:10px; color:var(--dsw-derive-muted,#57606a); font-weight:400; flex:none; white-space:nowrap; }
/* Line-1 order marks: queued = leading position number; at-work = green dot; human-hold / paused = amber dot (no ordering controls). */
.wb-order-pos { flex:none; min-width:14px; text-align:center; font-size:10px; font-weight:600;
  color:var(--dsw-derive-accent,#0969da); background:color-mix(in srgb,var(--dsw-derive-accent,#0969da) 12%,transparent);
  border-radius:4px; padding:0 3px; line-height:14px; }
.wb-order-dot { flex:none; width:8px; height:8px; border-radius:50%; }
.wb-order-dot[data-order-dot=work] { background:var(--dsw-derive-success,#1a7f37); }
.wb-order-dot[data-order-dot=hold], .wb-order-dot[data-order-dot=paused] { background:var(--dsw-derive-warn,#b8860b); }
/* Ordering controls: handgrip (drag anchor) + up/down arrows, rendered on data-order-kind=queued rows only.
   t261008-08 (mock v11): the controls sit at the ROW END (margin-left:auto eats
   the slack after the title); the position number stays first, grip right after it. */
.wb-order-ctl { display:inline-flex; align-items:center; gap:1px; flex:none; margin-left:auto; }
.wb-order-grip { cursor:grab; font-size:9px; letter-spacing:-1px; color:var(--dsw-derive-muted,#57606a); user-select:none; line-height:1; }
.wb-order-grip:active { cursor:grabbing; }
.wb-order-arrow { border:none; background:none; cursor:pointer; font:inherit; font-size:9px; line-height:1;
  color:var(--dsw-derive-muted,#57606a); padding:1px 2px; border-radius:3px; }
.wb-order-arrow:hover { background:rgba(255,255,255,.08); color:var(--dsw-alias-label-primary,#1f2328); }
.wb-order-arrow:disabled { opacity:.4; cursor:default; }
/* Line-2 ten-cell progress dots (design §7.2 default): lit up to the current stage, zero extra row height. */
.wb-stage-dots { display:inline-flex; align-items:center; gap:2px; flex:none; }
.wb-stage-dot { width:5px; height:5px; border-radius:1px; background:var(--dsw-derive-border,#d0d7de); }
.wb-stage-dot[data-on=true] { background:var(--dsw-derive-accent,#0969da); }
/* Reorder-refusal notice (A7): one line with the engine's refusal verbatim (same token family as .wb-insp-degraded, no new palette). */
.wb-order-notice { margin:2px 8px 6px 14px; padding:4px 8px; font-size:10px; line-height:1.5;
  color:var(--dsw-derive-dark-warn-fg,#ffe9c4); background:var(--dsw-derive-dark-warn-bg,#7a4a06);
  border:1px solid var(--dsw-derive-warn,#b8860b); border-radius:5px; word-break:break-all; }
.wb-group-empty { padding:2px 8px 8px 24px; color:var(--dsw-derive-fg,#666); font-size:11px; }
/* t260904-17 list v5: ticket entries = compact TicketRowCard — dark-theme
 * overrides: transparent base, inherited text colour, selected violet wash;
 * closed (data-state=done) dimmed one step.
 * t261008-08 (mock v11): left-column rows drop the inherited 4px epic bar (the
 * mock's .tk row has none) — border-left-width:0 offsets the board baseline
 * (index.tsx .wb-card border-left-width:4px); belt-and-braces with the
 * component side, which no longer writes the borderLeftColor inline colour
 * when compact. */
.wb-sb .wb-card { background:transparent; border-color:var(--dsw-derive-border,#d0d7de);
  border-left-width:0;
  box-shadow:none; color:var(--dsw-derive-fg,#1f2328); margin:0 6px 4px 14px; padding:5px 8px; }
.wb-sb .wb-card:hover { background:var(--dsw-derive-surface,#f6f8fa); }
.wb-sb .wb-card[data-active=true] { background:color-mix(in srgb,var(--dsw-derive-active,#7c3aed) 18%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); border-color:color-mix(in srgb,var(--dsw-derive-active,#7c3aed) 50%,var(--dsw-alias-bg-primary,var(--dsw-alias-bg-base,#fff))); }
.wb-sb .wb-card[data-state=done] { opacity:0.72; } /* 对齐板面 .72：0.55 时次级字混底后 <3:1（看守实测） */
.wb-sb .wb-card-title { color:inherit; font-weight:400; }
/* t261008-08 (mock v11): compact line 2 stage small text — 10px muted, same
   token family as the l2 meta (stage · epic · dots per the mock's .tk .l2). */
.wb-sb .wb-card-stage { flex:none; font-size:10px; color:var(--dsw-derive-muted,#57606a);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
/* t260929-22 gen8（对比度打回实测 rgb(122,122,133)≈4.24 元凶）：左栏 mini 行卡
   状态字曾一律 inherit（继承左栏弱化灰），改按四态消费语义令牌（gen8 起令牌为
   浅档深墨声明位，白底全部 ≥4.5）。 */
.wb-sb .wb-card-state { color:var(--dsw-derive-muted,#57606a); }
.wb-sb .wb-card-state[data-state=waiting] { color:var(--dsw-derive-warn,#7d4e00); }
.wb-sb .wb-card-state[data-state=blocked],.wb-sb .wb-card-state[data-state=failed] { color:var(--dsw-derive-danger,#cf222e); }
.wb-sb .wb-card-state[data-state=active] { color:var(--dsw-derive-accent,#0969da); }
/* t260905-08：原深档固定蓝字——平台浅档下失读（宿主实报同病），归主规则令牌 */
.wb-sb .wb-card-id { color:var(--dsw-derive-accent,#0969da); }
/* t260915-19 左栏「等你」黄调（巡检行）：与中列同 token（index.tsx
 * .wb-root .wb-card[data-state=waiting] 同源色板）——作用域=data-engine=inspection
 * 等值选择器（review C1：dev-lane 行 data-engine 在场-异值 "template-as-code-v2"，
 * 等值判定天然零命中；测试禁写「属性缺席」断言）。项目组行渲染零变化。 */
.wb-sb .wb-card[data-engine=inspection][data-state=waiting] { background:var(--dsw-derive-warn-bg,#fff8c5); }
/* t260916-15 巡检行类别徽标：行1 小 chip（琥珀描边字色=等你黄调族 token，透明底
 * 不与 data-state 底色语义混写）。作用域 .wb-sb=只有左栏消费 kindBadge（中列板面
 * 零变化）；任何状态（在跑/收口）都恒带徽标=数据来源可辨不依赖状态/位置。 */
.wb-sb .wb-card-kind { display:inline-flex; align-items:center; flex:none; padding:0 5px;
  border:1px solid var(--dsw-derive-warn,#b8860b); border-radius:5px;
  color:var(--dsw-derive-warn,#b8860b); font-size:10px; line-height:15px; }
/* t260915-19 巡检降级横幅：色板同 .wb-stale-banner 族（琥珀），不另起色板。 */
.wb-insp-degraded { padding:6px 10px; font-size:11px; line-height:1.5;
  color:var(--dsw-derive-dark-warn-fg,#ffe9c4); background:var(--dsw-derive-dark-warn-bg,#7a4a06);
  border-bottom:1px solid var(--dsw-derive-warn,#b8860b); }
/* 视图入口图标：右对齐放在每个项目组头行内（用户拍板 260823：per-project，不占独立行；
   t260827-01 起四个：工单/文档/模型/立项单；t260905-06 旧提法退役换文档）。
   t260929-22 gen4（宿主 260929 裁决落地：260927 设计胜、260823 放宽由 developer 落地、
   栏宽 180 冻结、行外不许有改命中面的层——gen3 的行下悬停条被 t260915-09 A/B 实证
   截住 .wb-psess 会话行的点击，此形态整体退役）：行内常驻=工单+立项单两枚场景钉住的
   图标 + 一枚「More views」展开钮；其余三枚（文档/模型路由/项目设置）收进展开位，
   展开也在流内（行自身盒内，零绝对定位、零外溢命中面）；展开时入口段名字瞬态让位，
   锚点行为不变。全部几何均 gen1 前同族：行高、列宽、命中区 26×26 冻结契约不动。 */
.wb-view-icons { display:flex; gap:2px; }
/* 图标族统一（票③ 11b）：命中区 26×26 radius 6，显形 18px（svg 由 ProjectIcon 定）；
   三态 idle/hover/active 沿用本侧栏既有色板（深色语境；mock 规格卡三态色为浅色
   语境定稿——图标本体吃 currentColor，几何规格统一是本模块契约）。 */
/* 图标族统一（票③ 11b）：命中区 26×26 radius 6，显形 18px（svg 由 ProjectIcon 定）；
   三态 idle/hover/active 沿用本侧栏既有色板（深色语境；mock 规格卡三态色为浅色
   语境定稿——图标本体吃 currentColor，几何规格统一是本模块契约）。
   t260929-22 gen2 勘误：gen1 曾把命中区缩到 20px 给入口段让宽——被 t260904-17
   A/B 实证为该场景新红单变量，此处恢复冻结契约 26×26（入口可达性见 .wb-view-icons
   gen3 注：悬停现形，不再动任何几何）。 */
.wb-view-icon { width:26px; height:26px; display:flex; align-items:center; justify-content:center; border-radius:6px; cursor:pointer; opacity:0.55; }
.wb-view-icon:hover { background:rgba(255,255,255,0.1); opacity:1; }
.wb-view-icon.active { background:rgba(124,58,237,0.25); opacity:1; }
/* t260929-22 直修（宿主令 260930，integration 执行）：.wb-view-icon 静息档 0.55 透明度
   用在**文字字符**图标（⋯ 更多视图）上时，合成后的有效色在白底只到 3.50、旧平台面
   3.43——透明度压不出 AA（0.55 时即便纯黑也只 4.75，实际墨色达不到）。本元素改走
   muted 墨色（极性自适应）：静息仍是弱化观感，两档都 ≥4.5，几何零改动。
   其余 view icon 不用文字字符（SVG），不受本规则影响。 */
.wb-view-icon[data-wb-more-views] { opacity:1; color:var(--dsw-derive-muted,#57606a); }
/* 隔离行（票③验收 11）：红色一行，常驻可辨。 */
.wb-quar-row { display:flex; align-items:center; gap:8px; padding:7px 10px; font-size:12px;
  color:var(--dsw-derive-danger-border,#ff8183); background:rgba(255,235,233,.08); cursor:pointer; border-bottom:1px solid rgba(255,255,255,.04); }
.wb-quar-row:hover { background:rgba(255,235,233,.16); }
/* 「＋ 接入项目」行（票③面D）：项目组列表末尾，方框＋语言同会话区（.wb-psess-* 方框同款）。 */
.wb-project-add-row { display:flex; align-items:center; gap:8px; padding:9px 10px; font-size:12px;
  color:var(--dsw-derive-muted,#57606a); cursor:pointer; }
.wb-project-add-row:hover { background:rgba(255,255,255,0.06); color:var(--dsw-alias-label-primary,#1f2328); }
.wb-project-add-plus { width:22px; height:22px; border:1px dashed var(--dsw-alias-border-l1,#555); border-radius:6px;
  display:flex; align-items:center; justify-content:center; font-size:14px; flex:none; }
/* Middle column container. Since t261005-10 (UI-2) the content is the machine-level
   status head (carried by the overlay host) plus the executor panel (fills the rest)
   — a vertical flex stack; the overlay covers both when open. */
.wb-right-content { flex:1; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
/* t261008-05: the overlay host must not size itself out of the middle column.
 * The legacy global .wb-root rule (index.tsx) carries height:100% AND
 * min-height:100%; for a flex:none item both resolve against the column's
 * definite height, so the host takes the whole column and leaves the executor
 * panel (flex:1 1 0%; min-height:0) at zero height. height:auto + min-height:0
 * makes the host shrink to its own content. The legacy global rule is
 * intentionally NOT rewritten — views that still use .wb-root as their
 * full-height root keep it. */
.wb-right-content > .wb-root { flex:none; height:auto; min-height:0; }
.wb-right-content > .wb-executor-view { flex:1; min-height:0; }
.wb-right-content > .wb-placeholder { flex:none; }
.wb-placeholder { padding:32px; color:var(--dsw-derive-muted,#57606a); font-size:13px; line-height:1.8; }

/* 顶部会话入口行样式已随票② R8 退役（t260904-05，顶部行样式族全清）。 */
`;
/**
* 出厂「⊕ New Session」钮压制注入面（t260831-02 建；票② R8 后职责=压制全局
* 新建入口，拍板 1——移除注入=出厂全局钮回显，落点非项目归属）：出厂钮不在任何槽里
* （实查 dsh-client-ui-sidebar 包只声明 sidebar.workspaces/settings/footer.action
* 三槽），按工单口径走「注入+语义锚」——
*   锚：从本插件侧栏根（rootRef）上溯 SidebarRoot（出厂钮是它的直接子 button，
*   折叠钮在 logoRow 内部非直接子、不会被误伤），取「aria-label 命中
*   FACTORY_NEW_LABELS」的直接子 button——零 CSS 类名匹配（t260828-06 死因
*   不复犯）；命中即置 display:none——职责=压制全局新建入口（票②拍板 1，
*   出厂钮不回显；顶部行已退役，无「让位」对象）。
*   兜防：MutationObserver 盯 SidebarRoot 的 childList/attributes——工厂重渲染
*   复活新钮（或恢复被隐藏钮的可见性）时重新隐藏。
*   全终态回收：卸载/折叠 cleanup 断开 Observer 并把碰过的钮 style.display
*   还原为原值；锚找不到=软退化（出厂钮照常显示，功能不丢，console.warn 留痕）。
*   作用面仅此一个出厂元素，右栏出厂元素零接触。
*/
function useHideFactoryNewSession(rootRef, wide) {
	(0, react.useEffect)(() => {
		if (!wide) return;
		const root = rootRef.current;
		if (!root) return;
		let sidebarRoot = null;
		for (let e = root.parentElement, i = 0; e && i < 10; i++, e = e.parentElement) if (Array.from(e.children).some((c) => c instanceof HTMLElement && c.tagName === "BUTTON" && FACTORY_NEW_LABELS.includes(c.getAttribute("aria-label") ?? ""))) {
			sidebarRoot = e;
			break;
		}
		if (!sidebarRoot) {
			console.warn("[workbench] 未找到出厂 New Session 钮（软退化：出厂钮照常显示，入口仍在侧栏顶部）");
			return;
		}
		const sb = sidebarRoot;
		const hidden = /* @__PURE__ */ new Map();
		const hide = () => {
			for (const c of Array.from(sb.children)) {
				if (!(c instanceof HTMLElement) || c.tagName !== "BUTTON") continue;
				if (!FACTORY_NEW_LABELS.includes(c.getAttribute("aria-label") ?? "")) continue;
				if (!hidden.has(c)) hidden.set(c, c.style.display);
				if (c.style.display !== "none") c.style.display = "none";
			}
		};
		hide();
		const mo = new MutationObserver(hide);
		mo.observe(sb, {
			childList: true,
			subtree: false,
			attributes: true,
			attributeFilter: ["style", "aria-label"]
		});
		return () => {
			mo.disconnect();
			for (const [el, prev] of hidden) el.style.display = prev;
		};
	}, [rootRef, wide]);
}
function WorkbenchSidebar(props) {
	const { wide, expandSidebar, sessions, views, open: slotOpen, workspaces, getService } = props;
	const [projects, setProjects] = (0, react.useState)([]);
	/** 项目 key → 该项目的工单行（按 ?project= 逐组拉取，来源即归属，不做路径猜测）。 */
	const [ticketsByProject, setTicketsByProject] = (0, react.useState)({});
	const [concByProject, setConcByProject] = (0, react.useState)({});
	/** Reorder in flight (project key -> true): controls disabled against double writes; every write ends in POST -> re-read the same face. */
	const [reorderBusy, setReorderBusy] = (0, react.useState)({});
	/** Named reorder refusal (project key -> verbatim error; '' = none): renders as the group's notice line (acceptance A7). */
	const [orderNotice, setOrderNotice] = (0, react.useState)({});
	/** Currently dragged ticket (project key -> id): the drop row computes the move-to from it; zero local order kept - one permutation, then POST. */
	const dragTicketRef = (0, react.useRef)(null);
	/** Workflow topology (stage-order source of the ten-cell dots; minimal Wf projection). */
	const [wfList, setWfList] = (0, react.useState)([]);
	const [inspectionRows, setInspectionRows] = (0, react.useState)([]);
	const [inspectionNote, setInspectionNote] = (0, react.useState)("");
	const inspectionRowsRef = (0, react.useRef)([]);
	const [inspCollapsed, setInspCollapsed] = (0, react.useState)(false);
	const [selectedId, setSelectedId] = (0, react.useState)("");
	const [rightView, setRightView] = (0, react.useState)("executor");
	/** 当前中列视图所属项目（左列图标点击行）；空=未选（中列显占位）。 */
	const [viewProject, setViewProject] = (0, react.useState)("");
	/** 「又点了一次工单」信号：随 focusId 传给 WorkbenchSection，
	*  同 id 重开（抽屉被 × 关掉后再点同一行）也能触发——focusId 同值时 effect 不 firing。 */
	const [focusNonce, setFocusNonce] = (0, react.useState)(0);
	/** 「点工单列表图标回列表」信号：viewProject/rightView 同值时 setState 跳渲染，
	*  详情抽屉（WorkbenchSection 内部 state）收不到通知——靠这个单调递增计数传达。 */
	const [listNonce, setListNonce] = (0, react.useState)(0);
	const [collapsed, setCollapsed] = (0, react.useState)({});
	const [moreViews, setMoreViews] = (0, react.useState)({});
	const [loading, setLoading] = (0, react.useState)(true);
	const [modal, setModal] = (0, react.useState)(null);
	/** 隔离条目（GET /wf/projects 的 quarantined 面，票③验收 11）：红色行渲染源。 */
	const [quarantined, setQuarantined] = (0, react.useState)([]);
	const rootRef = (0, react.useRef)(null);
	const staleBanner = useStaleBanner();
	const [staleDismissed, setStaleDismissed] = (0, react.useState)(false);
	useHideFactoryNewSession(rootRef, wide);
	const projectSessions = useSessionEntry({
		sessions,
		workspaces,
		getService,
		slotOpen,
		projectKey: viewProject || (projects.length === 1 ? projects[0].key : ""),
		projectDir: projects.find((p) => p.key === (viewProject || (projects.length === 1 ? projects[0].key : "")))?.primary ?? ""
	});
	(0, react.useEffect)(() => {
		if (!wide) return;
		const snapshot = getLedgerSnapshot();
		const backfilled = backfillProjectSeqs(snapshot);
		if (backfilled !== snapshot) persistLedger(backfilled);
	}, [wide, projectSessions.ledger]);
	(0, react.useEffect)(() => {
		if (!wide) return;
		return startChatProjectBandEffect({
			getSessions: () => {
				const pk = projectSessions.listState?.current ? projectSessions.ledger.find((e) => e.id === projectSessions.listState?.current)?.project : void 0;
				const current = projectSessions.listState?.current;
				const byId = projectSessions.listState?.byId ?? {};
				return projectSessions.ledger.filter((e) => pk ? e.project === pk : false).map((e) => {
					const raw = labelOf(byId[e.id], e.id);
					const handle = displayHandle({
						session_id: e.id,
						handle: e.handle
					}) || String(e.seq ?? "");
					return {
						id: e.id,
						handle,
						title: rowLabelOf(byId[e.id], e.id, handle),
						rawTitle: raw,
						active: e.id === current
					};
				});
			},
			onNewSession: () => {
				const pk = projectSessions.listState?.current ? projectSessions.ledger.find((e) => e.id === projectSessions.listState?.current)?.project : viewProject || (projects.length === 1 ? projects[0].key : "");
				const dir = projects.find((p) => p.key === pk)?.primary ?? "";
				if (!pk) return;
				projectSessions.handleNew({
					key: pk,
					dir
				});
			},
			onOpenSession: (id) => {
				projectSessions.handleOpen(id);
			}
		});
	}, [wide]);
	(0, react.useEffect)(() => {
		if (!wide) return;
		return startContextFoldEffect();
	}, [wide]);
	(0, react.useEffect)(() => startPlatformBannerHideEffect(), []);
	(0, react.useEffect)(() => {
		if (!wide) return;
		const cur = projectSessions.listState?.current;
		const entry = cur ? projectSessions.ledger.find((e) => e.id === cur) : void 0;
		setChatProjectBandInfo({
			project: entry?.project ?? null,
			handle: entry ? displayHandle({
				session_id: entry.id,
				handle: entry.handle
			}) : void 0
		});
	}, [
		wide,
		projectSessions.listState?.current,
		projectSessions.ledger
	]);
	const bandProjectKey = viewProject || (projects.length === 1 ? projects[0].key : "");
	(0, react.useEffect)(() => {
		if (!wide || bandProjectKey === "") return;
		fetchProjectLedger(bandProjectKey);
	}, [wide, bandProjectKey]);
	(0, react.useEffect)(() => {
		if (!wide) return;
		const root = rootRef.current;
		if (!root) return;
		let el = root.parentElement;
		let frame = null;
		for (let i = 0; el && i < 10; i++, el = el.parentElement) if (/^\d+px\s|^\d+%\s/.test(el.style.gridTemplateColumns ?? "")) {
			frame = el;
			break;
		}
		let sb = null;
		for (let i = 0, e = root.parentElement; e && i < 6; i++, e = e.parentElement) if (/^\d+px$/.test(e.style.width ?? "")) {
			sb = e;
			break;
		}
		const observers = [];
		let origCols;
		let origW;
		if (frame) {
			const fr = frame;
			origCols = fr.style.gridTemplateColumns;
			const applyCols = () => {
				const cols = (fr.style.gridTemplateColumns || "").split(/\s+/);
				if (cols.length < 3) return;
				if (cols[0] === "75%") return;
				cols[0] = "75%";
				fr.style.gridTemplateColumns = cols.join(" ");
			};
			applyCols();
			const mo = new MutationObserver(applyCols);
			mo.observe(fr, {
				attributes: true,
				attributeFilter: ["style"]
			});
			observers.push(mo);
		}
		if (sb) {
			const s = sb;
			origW = s.style.width;
			const applyW = () => {
				if (s.style.width !== "100%") s.style.width = "100%";
			};
			applyW();
			const mo = new MutationObserver(applyW);
			mo.observe(s, {
				attributes: true,
				attributeFilter: ["style"]
			});
			observers.push(mo);
		}
		return () => {
			observers.forEach((mo) => mo.disconnect());
			if (frame && origCols !== void 0) frame.style.gridTemplateColumns = origCols;
			if (sb && origW !== void 0) sb.style.width = origW;
		};
	}, [wide]);
	(0, react.useEffect)(() => {
		if (!wide) return;
		let cancelled = false;
		async function load() {
			const inspPromise = fetch(INSPECTION_TICKETS_URL).then((r) => r.json()).catch((err) => ({
				ok: false,
				error: err instanceof Error ? err.message : String(err)
			}));
			try {
				const pr = await fetch("/sandbar-workbench/api/wf/projects").then((r) => r.json());
				const list = pr?.result?.projects ?? [];
				if (cancelled) return;
				setProjects(list);
				setQuarantined(Array.isArray(pr?.result?.quarantined) ? pr.result.quarantined : []);
				publishProjects(list.map((p) => ({
					key: p.key,
					dirs: p.dirs
				})));
				const entries = await Promise.all(list.map(async (p) => {
					try {
						const tickets = (await fetch(`/sandbar-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`).then((r) => r.json()))?.result?.tickets ?? [];
						publishProjectEntry(p.key, tickets.map((t) => t.id));
						return [p.key, tickets];
					} catch {
						return [p.key, []];
					}
				}));
				const concEntries = await Promise.all(list.map(async (p) => {
					try {
						const cr = await fetch(`${CONCURRENCY_URL}?project=${encodeURIComponent(p.key)}`).then((r) => r.json());
						return [p.key, parseConcFace(concFaceFromReply(cr))];
					} catch {
						return [p.key, null];
					}
				}));
				if (cancelled) return;
				setTicketsByProject(Object.fromEntries(entries));
				setConcByProject(Object.fromEntries(concEntries));
			} catch {}
			try {
				const wr = await fetch("/sandbar-workbench/api/wf/workflows").then((r) => r.json());
				if (!cancelled && wr?.ok === true) setWfList(wr.result ?? []);
			} catch {}
			try {
				const ir = await inspPromise;
				if (cancelled) return;
				if (ir?.ok === true) {
					inspectionRowsRef.current = ir.result?.tickets ?? [];
					setInspectionRows(inspectionRowsRef.current);
					setInspectionNote("");
				} else setInspectionNote(inspectionDegradedNote(ir?.error !== void 0 ? ir.error : `HTTP response has no JSON body: ${JSON.stringify(ir).slice(0, 120)}`));
			} catch (err) {
				if (cancelled) return;
				setInspectionNote(inspectionDegradedNote(err instanceof Error ? err.message : String(err)));
			} finally {
				if (!cancelled) setLoading(false);
			}
		}
		load();
		const stopPoll = startVisibleInterval(() => {
			load();
		}, 1e4);
		return () => {
			cancelled = true;
			stopPoll();
		};
	}, [wide]);
	const refreshConc = (0, react.useCallback)(async (projectKey) => {
		try {
			const cr = await fetch(`${CONCURRENCY_URL}?project=${encodeURIComponent(projectKey)}`).then((r) => r.json());
			setConcByProject((m) => ({
				...m,
				[projectKey]: parseConcFace(concFaceFromReply(cr))
			}));
		} catch {
			setConcByProject((m) => ({
				...m,
				[projectKey]: null
			}));
		}
	}, []);
	const handleReorder = (0, react.useCallback)(async (projectKey, order) => {
		const want = permutationOf((concByProject[projectKey] ?? null)?.queue ?? [], order);
		if (want === null) return;
		setReorderBusy((m) => ({
			...m,
			[projectKey]: true
		}));
		let refused = "";
		try {
			const r = await fetch(CONCURRENCY_REORDER_URL, {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({
					project: projectKey,
					order: want
				})
			}).then((x) => x.json());
			if (r?.ok !== true) refused = String(r?.error ?? "reorder failed (HTTP body without ok:true)");
		} catch (err) {
			refused = err instanceof Error ? err.message : String(err);
		}
		try {
			await refreshConc(projectKey);
		} finally {
			setOrderNotice((m) => ({
				...m,
				[projectKey]: refused
			}));
			setReorderBusy((m) => ({
				...m,
				[projectKey]: false
			}));
		}
	}, [concByProject, refreshConc]);
	const handleTicketClick = (0, react.useCallback)((t, projectKey) => {
		setSelectedId(t.id);
		setViewProject((p) => projectKey || p || (projects.length > 0 ? projects[0].key : ""));
		setRightView("executor");
		setFocusNonce((n) => n + 1);
	}, [projects]);
	(0, react.useEffect)(() => startChatProjectTagEffect({ fetchImpl: fetch.bind(globalThis) }), []);
	const handleViewIcon = (0, react.useCallback)((projectKey, view) => {
		setViewProject(projectKey);
		setRightView(view);
	}, []);
	const openExecutorSessionById = (0, react.useCallback)((sessionId) => {
		try {
			sessions.open(sessionId);
			return true;
		} catch (err) {
			console.warn("[workbench] open executor session failed:", err);
			return false;
		}
	}, [sessions]);
	/** 项目组：注册表顺序。进行中工单常列；已完成工单在 sandbar 驻留窗口内也列（灰绿标记）。 */
	const inspectionSplit = (0, react.useMemo)(() => inspectionSplitByProject(inspectionRows, projects.map((p) => p.key)), [inspectionRows, projects]);
	const groups = (0, react.useMemo)(() => {
		const nowS = Date.now() / 1e3;
		return projects.map((p) => ({
			project: p,
			tickets: sortMergedTickets([...(ticketsByProject[p.key] ?? []).filter((t) => inSandbar(t, nowS)), ...inspectionSplit.byProject[p.key] ?? []])
		}));
	}, [
		projects,
		ticketsByProject,
		inspectionSplit
	]);
	const Ws = views.overlay;
	const Routes = views.routes;
	if (!wide) return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		ref: rootRef,
		className: "wb-sb rail",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: CSS$2 }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "wb-sb-icon",
			onClick: expandSidebar,
			title: "Console",
			children: "⊞"
		})]
	});
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		ref: rootRef,
		className: "wb-sb wide",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: CSS$2 }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-sb-left",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-brand-row",
					"data-wb-brand-row": "",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-brand-mark",
							"aria-hidden": "true",
							children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("svg", {
								width: "14",
								height: "14",
								viewBox: "0 0 14 14",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("rect", {
									x: "1.2",
									y: "2.6",
									width: "9",
									height: "3.4",
									rx: "1.7",
									transform: "rotate(-18 5.7 4.3)",
									fill: "var(--dsw-alias-brand-primary,#7c3aed)"
								}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("rect", {
									x: "3.8",
									y: "7.6",
									width: "9",
									height: "3.4",
									rx: "1.7",
									transform: "rotate(-18 8.3 9.3)",
									fill: "var(--dsw-alias-brand-primary,#7c3aed)",
									opacity: "0.55"
								})]
							})
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-brand-word",
							children: "Sandbar"
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-brand-count",
							children: loading ? "" : `${groups.length} project${groups.length === 1 ? "" : "s"}`
						})
					]
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ticket-list",
					children: [
						inspectionNote !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-insp-degraded",
							"data-testid": "sidebar-inspection-degraded",
							role: "alert",
							children: inspectionNote
						}),
						loading ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							style: {
								padding: 16,
								color: "var(--dsw-derive-fg,#888)"
							},
							children: "Loading…"
						}) : groups.map((g) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-project-block",
							"data-wb-project-block": "",
							"data-selected": viewProject === g.project.key,
							style: { "--wb-proj-color": projectColor(g.project.key) },
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-group-head",
								style: { cursor: "pointer" },
								children: [
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "wb-group-caret",
										title: collapsed[g.project.key] ? "Expand" : "Collapse",
										onClick: (e) => {
											e.stopPropagation();
											setCollapsed((c) => ({
												...c,
												[g.project.key]: !c[g.project.key]
											}));
										},
										children: collapsed[g.project.key] ? "▸" : "▾"
									}),
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "wb-group-dot",
										"data-wb-psess-dot": "",
										"data-wb-identity-badge": "",
										style: {
											display: "inline-flex",
											flex: "none",
											lineHeight: 0
										},
										title: g.project.key,
										"aria-label": `${g.project.name} identity badge`,
										dangerouslySetInnerHTML: { __html: projectBadgeSvg(g.project.key, 14, groups.map((x) => x.project.key)) }
									}),
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "wb-group-entry",
										"data-wb-executor-entry": "",
										role: "button",
										tabIndex: 0,
										title: `Open ${g.project.name} executor panel`,
										"aria-label": `Open ${g.project.name} executor panel`,
										onKeyDown: (e) => {
											if (e.key === "Enter" || e.key === " ") handleViewIcon(g.project.key, "executor");
										},
										onClick: () => handleViewIcon(g.project.key, "executor"),
										children: [
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
												className: "wb-group-name",
												children: g.project.name
											}),
											concByProject[g.project.key] !== void 0 && concByProject[g.project.key] !== null && (() => {
												const c = faceCounts(concByProject[g.project.key] ?? null);
												return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
													className: "wb-group-conc",
													"data-wb-conc-counts": "",
													"data-at-work": c.atWork,
													"data-waiting": c.waiting,
													title: "At work · waiting (project concurrency)",
													children: [
														c.atWork,
														" at work · ",
														c.waiting,
														" waiting"
													]
												});
											})(),
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
												className: "wb-group-count",
												children: g.tickets.length || ""
											})
										]
									}),
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "wb-view-icons",
										onClick: (e) => e.stopPropagation(),
										children: [moreViews[g.project.key] && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: `wb-view-icon ${rightView === "routes" && viewProject === g.project.key ? "active" : ""}`,
											title: "Model Routes",
											"aria-label": "Model Routes",
											onClick: () => handleViewIcon(g.project.key, "routes"),
											children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ProjectIcon, { name: "routes" })
										}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "wb-view-icon",
											"data-wb-project-settings-entry": "",
											title: "Project Settings",
											"aria-label": "Project Settings",
											onClick: () => {
												setModal({
													kind: "settings",
													project: g.project
												});
											},
											children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ProjectIcon, { name: "settings" })
										})] }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											className: "wb-view-icon",
											role: "button",
											tabIndex: 0,
											"data-wb-more-views": "",
											"data-on": Boolean(moreViews[g.project.key]) || void 0,
											title: moreViews[g.project.key] ? "Fewer views" : "More views",
											"aria-label": moreViews[g.project.key] ? "Fewer views" : "More views",
											onKeyDown: (e) => {
												if (e.key === "Enter" || e.key === " ") setMoreViews((m) => ({
													...m,
													[g.project.key]: !m[g.project.key]
												}));
											},
											onClick: () => setMoreViews((m) => ({
												...m,
												[g.project.key]: !m[g.project.key]
											})),
											children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
												"aria-hidden": "true",
												style: {
													fontSize: 13,
													lineHeight: 1,
													fontWeight: 700
												},
												children: "⋯"
											})
										})]
									})
								]
							}), !collapsed[g.project.key] && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ProjectSessionRow, {
									projectKey: g.project.key,
									projectName: g.project.name,
									projectDir: g.project.primary,
									ledger: projectSessions.ledger,
									current: projectSessions.listState?.current,
									byId: projectSessions.listState?.byId,
									creating: projectSessions.creating,
									notice: projectSessions.entryNotice,
									noticeProject: projectSessions.noticeProject,
									onNew: () => {
										projectSessions.handleNew({
											key: g.project.key,
											dir: g.project.primary
										});
									},
									onOpen: (id) => {
										projectSessions.handleOpen(id);
									},
									onClose: projectSessions.handleClose
								}),
								g.tickets.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-group-empty",
									children: "No active tickets"
								}) : g.tickets.map((t) => {
									const insp = isInspectionRow(t);
									const conc = concByProject[g.project.key] ?? null;
									const kind = insp ? void 0 : orderKindOf(t.id, conc, t.paused === true);
									const pos = kind === "queued" && conc !== null ? conc.queue.indexOf(t.id) + 1 : void 0;
									const wfl = wfList.find((w) => w.id === t.workflow) ?? null;
									const stageIdx = wfl && Array.isArray(wfl.stages) ? wfl.stages.findIndex((s) => s?.id === t.stage) : -1;
									return /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TicketRowCard, {
										t,
										compact: true,
										wf: insp ? INSPECTION_WF_LIKE : void 0,
										progress: insp ? inspectionProgressOf(t) : void 0,
										kindBadge: insp ? { text: "Inspection" } : void 0,
										ordering: kind === void 0 ? void 0 : {
											kind,
											pos,
											dotsLit: kind === "queued" || kind === "atwork" || kind === "hold" ? stageDotsLit(stageIdx, t.status === "closed") : void 0,
											busy: reorderBusy[g.project.key] === true,
											onMove: (dir) => {
												if (conc === null) return;
												const next = moveTicket(conc.queue, t.id, dir);
												if (next !== null) handleReorder(g.project.key, next);
											},
											onDragStart: () => {
												dragTicketRef.current = {
													project: g.project.key,
													id: t.id
												};
											},
											onDrop: () => {
												const drag = dragTicketRef.current;
												dragTicketRef.current = null;
												if (conc === null || drag === null || drag.project !== g.project.key) return;
												const next = reorderMoveTo(conc.queue, drag.id, t.id);
												if (next !== null) handleReorder(g.project.key, next);
											}
										},
										active: selectedId === t.id,
										updatedTsMs: (isOpen(t) ? t.created : t.close_ts || t.created) !== void 0 ? (isOpen(t) ? t.created : t.close_ts || t.created) * 1e3 : void 0,
										onOpen: () => handleTicketClick(t, g.project.key)
									}, t.id);
								}),
								orderNotice[g.project.key] && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-order-notice",
									"data-wb-order-notice": "",
									role: "alert",
									children: orderNotice[g.project.key]
								})
							] })]
						}, g.project.key)),
						!loading && inspectionSplit.unowned.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-group-head",
							"data-testid": "sidebar-inspection-head",
							onClick: () => setInspCollapsed((c) => !c),
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-group-caret",
									children: inspCollapsed ? "▸" : "▾"
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-group-name",
									children: "Inspection"
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-group-count",
									children: inspectionSplit.unowned.length
								})
							]
						}), !inspCollapsed && sortMergedTickets(inspectionSplit.unowned).map((t) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TicketRowCard, {
							t,
							compact: true,
							wf: INSPECTION_WF_LIKE,
							progress: inspectionProgressOf(t),
							kindBadge: { text: "Inspection" },
							active: selectedId === t.id,
							updatedTsMs: (isOpen(t) ? t.created : t.close_ts || t.created) !== void 0 ? (isOpen(t) ? t.created : t.close_ts || t.created) * 1e3 : void 0,
							onOpen: () => handleTicketClick(t, "")
						}, t.id))] }),
						quarantined.map((q) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-quar-row",
							"data-wb-quarantine-row": "",
							role: "button",
							"aria-label": `Quarantined entry ${q.key}`,
							onClick: () => setModal({
								kind: "quarantine",
								entry: q
							}),
							children: [
								"⚠ ",
								q.key,
								" · registry entry quarantined"
							]
						}, q.key)),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-project-add-row",
							"data-wb-project-add-row": "",
							role: "button",
							"aria-label": "Add project",
							onClick: () => setModal({ kind: "add" }),
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-project-add-plus",
								children: "＋"
							}), "Add project"]
						})
					]
				})]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-sb-right",
				children: [
					staleBanner && !staleDismissed && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-stale-banner",
						"data-stale-kind": staleBanner,
						role: "alert",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-stale-msg",
							children: [
								"⚠️ ",
								staleBanner === "restart" ? "Update available — restart the console to apply" : "Update available — refresh the page to apply",
								"(",
								staleBanner === "restart" ? "console process still runs old code" : "this page still runs old code",
								"; metrics/diff may be stale)."
							]
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "wb-stale-dismiss",
							title: "Hide in this tab",
							onClick: () => setStaleDismissed(true),
							children: "Got it"
						})]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-right-content",
						children: [
							!viewProject && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-placeholder",
								children: [
									"Open a project from the left (click a project name row to open its Executor panel,",
									/* @__PURE__ */ (0, react_jsx_runtime.jsx)("br", {}),
									"or click a ticket row to open its detail overlay)."
								]
							}),
							viewProject && rightView === "executor" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)(Ws, {
								focusId: selectedId || void 0,
								focusNonce,
								listNonce,
								projectKey: viewProject
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ExecutorView, {
								projectKey: viewProject,
								openExecutorSession: openExecutorSessionById,
								openTicketOverlay: (id) => handleTicketClick({ id }, viewProject)
							})] }),
							viewProject && rightView === "routes" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(Routes, { projectKey: viewProject })
						]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-sb-foot",
						children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { className: "wb-sb-foot-sp" })
					}),
					modal?.kind === "settings" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ProjectSettingsModal, {
						project: modal.project,
						onClose: () => setModal(null),
						onRemove: () => setModal({
							kind: "remove",
							project: modal.project
						})
					}),
					modal?.kind === "remove" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ProjectRemoveModal, {
						project: modal.project,
						onClose: () => setModal(null),
						onRemoved: () => {
							setModal(null);
						}
					}),
					modal?.kind === "add" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ProjectAddModal, {
						onClose: () => setModal(null),
						onAdded: () => {
							setModal(null);
						}
					}),
					modal?.kind === "quarantine" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(QuarantineModal, {
						entry: modal.entry,
						onClose: () => setModal(null)
					})
				]
			})
		]
	});
}
//#endregion
//#region src/client/epics-model.ts
const EPIC_STATUS_OPTIONS = [
	"已立项（待开工单）",
	"已立项（执行中）",
	"已完结",
	"已归档"
];
/** 枚举精确匹配白名单（前端兜底；后端 setEpicStatus 有同口径最终校验）。 */
function isEpicStatusValue(s) {
	return EPIC_STATUS_OPTIONS.includes(s);
}
/**
* 立项单 API 调用统一拼 ?project=（t260915-09，KI-057 client 侧收口）：epics 族
* 端点按项目根取数，裸调=无参回落引擎仓=跨项目立项单串台病灶（宿主 260915 实报）。
* 语义对齐 index.tsx withProject 家族先例：
*   - projectKey 非空字符串 → 拼 ?project=<encodeURIComponent>（已有 query 用 &）；
*   - path 已带 project= → 幂等原样返回（防双拼）；
*   - 空串/undefined/非字符串（畸形）→ 原样返回不抛——epics 族读端点无参=回落引擎仓
*     （既有语义保留）；写端点的空 key 守卫在调用侧（建票既有禁用口径、saveStatus
*     同款守卫），本函数不代拦不静默造参。
*/
function withEpicProject(path, projectKey) {
	if (typeof projectKey !== "string" || projectKey === "") return path;
	if (/[?&]project=/.test(path)) return path;
	return path + (path.includes("?") ? "&" : "?") + "project=" + encodeURIComponent(projectKey);
}
/**
* 状态筛选（工单台立项单列表，t260831-05）：status 为空串/undefined = 全部不过滤；
* 其余按枚举值精确过滤。未知值（防御性）返回空数组并 console.warn 一条——
* 白名单外状态本不该存在（写入已拒收），出现即迁移漏网，值得看见。
*/
function filterEpicsByStatus(rows, status) {
	const s = String(status ?? "").trim();
	if (s === "") return rows;
	if (!isEpicStatusValue(s)) {
		console.warn(`filterEpicsByStatus：未知状态 '${s}' 不在枚举内，返回空列表（疑似迁移漏网）`);
		return [];
	}
	return rows.filter((r) => String(r?.status ?? "") === s);
}
/** 状态分桶归一（UI 展示口径）：closed/verified→已完成、terminated→已终止、其余→进行中。 */
function bucketOf(status) {
	if (status === "closed" || status === "verified") return "已完成";
	if (status === "terminated") return "已终止";
	return "进行中";
}
/** 桶展示顺序：进行中 → 已完成 → 已终止 → 未知桶字典序殿后（稳定、可预期）。 */
const BUCKET_ORDER = [
	"进行中",
	"已完成",
	"已终止"
];
function sortBucketKeys(keys) {
	return [...keys].sort((a, b) => {
		const ia = BUCKET_ORDER.indexOf(a);
		const ib = BUCKET_ORDER.indexOf(b);
		const oa = ia < 0 ? BUCKET_ORDER.length : ia;
		const ob = ib < 0 ? BUCKET_ORDER.length : ib;
		return oa !== ob ? oa - ob : a.localeCompare(b);
	});
}
/**
* API 的 buckets 按原始 status 分桶（closed/dispatched/…）——UI 展示前先按 bucketOf
* 归并求和（验收口径=分桶计数，「已完成 ×3」比「closed ×2 + verified ×1」更可读）。
*/
function mergeBuckets(buckets) {
	const out = {};
	for (const [k, v] of Object.entries(buckets ?? {})) {
		const b = bucketOf(k);
		out[b] = (out[b] ?? 0) + (Number(v) || 0);
	}
	return out;
}
/** 工单行排序：进行中在前、已收口在后，各自按 id 降序（新工单在上）；缺字段容错不抛。 */
function sortEpicTickets(rows) {
	const rank = (r) => bucketOf(String(r?.status ?? "")) === "进行中" ? 0 : 1;
	return [...rows].sort((a, b) => rank(a) - rank(b) || String(b?.id ?? "").localeCompare(String(a?.id ?? "")));
}
/**
* 所属立项徽标口径（单点）：有 epic → 可点代号 chip；无 → 灰「未归档」chip。
* 人门签字确认区不用本口径（review M1：那里「有则显示无则略」，不显示「未归档」字样）。
*/
function epicBadgeOf(epic) {
	const code = (epic ?? "").trim();
	return code === "" ? {
		label: "No epic",
		code: null
	} : {
		label: code,
		code
	};
}
/** 新建工单正文首行注入的归属说明（验收标准 9：代号由界面带入，正文里留痕、不许手输改绑）。 */
function epicCreateNote(code) {
	return `所属立项：${code}（代号由界面带入，不可修改）`;
}
/** 单条写集路径合法性（建票弹层写集编辑栏自有实现；t260910-14 起 host 同构副本
*  已随预跑建议面退役，本函数为仓内唯一 TS 面）：
*  仓库内相对路径——空串/绝对路径/含 '..'/反斜杠/Windows 盘符一律非法。 */
function validWriteSetEntry(p) {
	if (typeof p !== "string") return false;
	const s = p.trim();
	if (s === "" || s.startsWith("/") || s.startsWith("\\") || s.includes("\\")) return false;
	if (s.length >= 2 && s[1] === ":" && /[a-zA-Z]/.test(s[0])) return false;
	return !s.split("/").includes("..");
}
/** 写集文本 ↔ 数组：每行一条；空行与首尾空白容忍；空白行不产生条目。 */
function writeSetTextToLines(text) {
	return String(text ?? "").split("\n").map((ln) => ln.trim()).filter((ln) => ln !== "");
}
/** 弹层提交前校验：返回非法行清单（合法为空数组）。有非法行 → 前端拦截提交并标红。 */
function invalidWriteSetLines(text) {
	return writeSetTextToLines(text).filter((ln) => !validWriteSetEntry(ln));
}
/** 「无文件改动」声明拦截判定（t260901-01）：写集为空且未勾选声明 → 返回拦截文案
*  （两条出路口径，与引擎 shared.validate_write_set_args 拒收文案同源同义）；
*  其余（写集非空 / 已勾选声明）返回空串放行。 */
function createWriteSetBlocked(text, allowEmpty) {
	if (writeSetTextToLines(text).length > 0) return "";
	if (allowEmpty) return "";
	return "写集为空：agent 将没有白名单护栏、UI 票判定失效。两条出路：① 填写写集，列出本票预计改动文件清单（每行一条）；② 确实无文件改动时勾选下方「本票无文件改动（allow_empty_write_set）」显式声明（meta 记 no_file_changes）。";
}
/** 建票 POST 体组装（t260901-01 单点）：写集文本 → 数组；仅当写集为空且勾选
*  「无文件改动」声明时才附 allow_empty_write_set=true（引擎空写集+声明才放行，
*  非空写集带该字段无意义，不附，保持 payload 最小面）。 */
function buildCreatePayload(base, text, allowEmpty) {
	const writeSet = writeSetTextToLines(text);
	const payload = {
		workflow: base.workflow,
		title: base.title.trim(),
		body: base.body,
		epic: base.epic,
		write_set: writeSet
	};
	if (writeSet.length === 0 && allowEmpty) payload.allow_empty_write_set = true;
	return payload;
}
//#endregion
//#region src/client/epics.tsx
/**
* epics.tsx —— 工单台「立项单」中列第四视图 + 所属立项徽标（epic-linkage Tier 3，t260826-02）。
*
* 落地口径（方案 + 评审拍板）：
*   - 不加路由/不加顶层 tab：本视图挂进 sidebar 中列四视图体系（views.epics），
*     由项目行立项单图标（t260827-01，空代号=立项清单）/ 工单徽标点击（定位详情）切换进来；
*   - 真源=API 渲染、前端不存状态（立项单关键决策 5）：列表=GET /api/epics，
*     详情=GET /api/epics/<code> + /api/epics/<code>/tickets（8s 轮询实时汇总）；
*   - Markdown 渲染复用 knowledge 浏览器半 renderMarkdown（index.tsx 同款 import，
*     零新依赖；立项单是仓库可信内容，与 M9 block diff 同前提）；
*   - 新建工单（验收标准 9）：模板下拉（GET /api/wf/workflows）+ 标题 + 正文，
*     epic 由界面传值（只读行展示，无手输框）→ POST /api/wf/tickets（host
*     handleTicketCreate，t260826-02 新增，需重启 dsh 生效）。
*   - （t260910-14 退役注记：原「继续执行」建议链路——建议 job/预跑缓存卡/
*     结项建议卡/写集建议预填——随预跑建议段整链退役删除；新建工单弹层为纯手工
*     通路，写集编辑栏（通用字段）保留。）
*   - （t260915-09 项目穿参：epics 族六处调用统一经 withEpicProject 拼 ?project=——
*     裸调=无参回落引擎仓=跨项目立项单串台病灶（KI-057 client 半收口）；列表/
*     聚合轮询 deps 带项目键，切项目即重拉；建票/状态写空项目=守卫不裸调；
*     /wf/workflows 模板下拉项目无关，不穿。）
*   - EpicBadge 同时供 index.tsx 工单列表行/详情头部复用；口径单点=epics-model.ts。
*
* 不做（工单红线）：归档按钮/快照 UI（archive API 另单）；立项单编辑 UI（真源=文件，编辑走仓库）。
*/
const CSS$1 = `${DERIVE_TOKENS_CSS}
.wb-ep-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-fg,#1f2328);min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:14px;height:100%;overflow-y:auto;font-size:13px;line-height:1.55}
.wb-ep-head{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de);padding-bottom:10px;flex-wrap:wrap}
.wb-ep-title{font-size:18px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--dsw-derive-accent,#0969da);
  background:var(--dsw-derive-accent-bg,#ddf4ff);border:1px solid var(--dsw-derive-accent-border,#96c8f2);border-radius:6px;padding:1px 8px}
.wb-ep-sub{font-size:12px;color:var(--dsw-derive-muted,#57606a)}
.wb-ep-btn{font:inherit;font-size:13px;padding:4px 14px;border-radius:6px;cursor:pointer;
  border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
/* 禁用态（t260907-08）：弃 opacity 降权（四象限 new-light 格实锤 3.16<4.5），
 * 改灰字＋浅底的令牌化禁用态——对比度全档达标且保留「不可点」affordance。 */
.wb-ep-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-ep-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
.wb-ep-cols{display:flex;gap:14px;align-items:flex-start;min-height:0}
.wb-ep-md{flex:55 1 0;min-width:0;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);
  padding:12px 16px;overflow-x:auto}
.wb-ep-side{flex:45 1 0;min-width:240px;display:flex;flex-direction:column;gap:10px}
.wb-ep-panel{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);padding:10px 12px;
  display:flex;flex-direction:column;gap:8px}
.wb-ep-panel-title{font-size:13px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-chips{display:flex;gap:8px;flex-wrap:wrap}
.wb-ep-bucket{font-size:12px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
.wb-ep-bucket[data-b=进行中]{background:var(--dsw-derive-accent-bg,#ddf4ff);border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-ep-bucket[data-b=已完成]{background:var(--dsw-derive-success-bg,#dafbe1);border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success-deep,#116329)}
.wb-ep-bucket[data-b=已终止]{background:var(--dsw-derive-danger-bg,#ffebe9);border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e)}
.wb-ep-ticket{padding:6px 8px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;cursor:pointer;background:var(--dsw-derive-canvas,#ffffff)}
.wb-ep-ticket:hover{background:var(--dsw-derive-surface,#f6f8fa);border-color:var(--dsw-derive-accent-border,#96c8f2)}
.wb-ep-ticket .l1{display:flex;align-items:baseline;gap:8px;font-size:12px}
.wb-ep-ticket .l1 .id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-derive-accent,#0969da);font-weight:600;flex:none}
.wb-ep-ticket .l1 .ti{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-ticket .l2{font-size:11px;color:var(--dsw-derive-muted,#8c959f);margin-top:2px}
.wb-ep-degraded{font-size:12px;color:var(--dsw-derive-warn-deep,#7d4e00);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:6px 10px;white-space:pre-wrap;word-break:break-word}
.wb-ep-empty{font-size:12px;color:var(--dsw-derive-muted,#57606a);padding:8px 0}
.wb-ep-err{background:var(--dsw-derive-danger-bg,#ffebe9);border:1px solid var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);border-radius:6px;
  padding:8px 12px;font-size:12px;white-space:pre-wrap}
.wb-ep-msgok{font-size:12px;color:var(--dsw-derive-success-deep,#116329);background:var(--dsw-derive-success-bg,#dafbe1);border:1px solid var(--dsw-derive-success-border,#7dd9a0);
  border-radius:6px;padding:6px 10px}
/* 建议结项卡片（t260828-08）：绿色横条 + 说明 + 确认结项按钮 */
.wb-ep-done-card{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
  border:1px solid var(--dsw-derive-success-border,#7dd9a0);background:var(--dsw-derive-success-bg,#dafbe1);border-radius:6px;padding:8px 12px}
.wb-ep-done-title{font-size:12px;font-weight:600;color:var(--dsw-derive-success-deep,#116329)}
  padding:0 6px;color:var(--dsw-derive-success-deep,#116329);background:var(--dsw-derive-success-bg,#dafbe1);border:1px solid var(--dsw-derive-success-border,#a6e0b1)}
.wb-ep-done-reason{font-size:12px;color:var(--dsw-derive-success-deep,#116329);flex:1;min-width:200px}
/* 立项清单表（未选代号时的落列表） */
.wb-ep-table{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);font-size:13px;overflow:hidden}
.wb-ep-table th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600;text-align:left;padding:8px 12px;
  border-bottom:1px solid var(--dsw-derive-border,#d0d7de);font-size:12px;white-space:nowrap}
.wb-ep-table td{padding:8px 12px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);vertical-align:middle}
.wb-ep-table tbody tr{cursor:pointer}
.wb-ep-table tbody tr:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-ep-table tbody tr:last-child td{border-bottom:none}
/* 新建工单弹层（制式照 index.tsx wb-modal） */
.wb-ep-modal{position:fixed;inset:0;background:rgba(31,35,40,.5);z-index:99;display:flex;align-items:center;
  justify-content:center;padding:24px}
.wb-ep-modal-box{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:10px;
  box-shadow:0 8px 32px rgba(31,35,40,.2);max-width:640px;width:100%;max-height:86vh;
  display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.wb-ep-modal-title{font-size:15px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-ep-field{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--dsw-derive-muted,#57606a)}
.wb-ep-input{font:inherit;font-size:13px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:6px 10px;box-sizing:border-box;width:100%}
.wb-ep-input:focus{outline:none;border-color:var(--dsw-derive-accent,#0969da);box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.wb-ep-readonly{font-size:13px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);
  border-radius:6px;padding:6px 10px}
.wb-ep-ops{display:flex;gap:8px;align-items:center}
/* 所属立项徽标（wb-epic-chip：列表行/详情头部复用；灰=未归档，蓝=有归属可点） */
.wb-epic-chip{display:inline-block;font-size:11px;border-radius:6px;padding:1px 7px;flex:none;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap;vertical-align:1px}
.wb-epic-chip[data-archived=true]{color:var(--dsw-derive-muted,#8c959f);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);font-family:inherit}
.wb-epic-chip[data-archived=false]{color:var(--dsw-derive-accent-deep,#0550ae);background:var(--dsw-derive-accent-bg,#ddf4ff);border:1px solid var(--dsw-derive-accent-border,#96c8f2);cursor:pointer}
.wb-epic-chip[data-archived=false]:hover{background:var(--dsw-derive-accent-border,#bfe3ff);border-color:var(--dsw-derive-accent,#0969da)}
`;
const EPICS_API = "/sandbar-workbench/api/epics";
const WF_API = "/sandbar-workbench/api/wf";
async function getJson(path) {
	return (await fetch(path)).json();
}
/**
* 所属立项徽标（验收标准 8）：有 epic → 蓝 chip 显代号、点击 onNavigate(code) 跳立项详情；
* 无 epic → 灰 chip「未归档」（不可点，与有归属视觉区分）。口径单点=epicBadgeOf。
* onNavigate 缺省时一律纯展示（不可点）。
*/
function EpicBadge({ epic, onNavigate }) {
	const b = epicBadgeOf(epic);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
		className: "wb-epic-chip",
		"data-archived": b.code === null,
		title: b.code !== null ? `Epic: ${b.code} (click to open the epic)` : "Not linked to any epic",
		onClick: b.code !== null && onNavigate ? (ev) => {
			ev.stopPropagation();
			onNavigate(b.code);
		} : void 0,
		children: b.label
	});
}
function EpicSection({ epicCode, epicNonce, projectKey, onOpenTicket }) {
	/** 内部选中代号：prop 驱动（外部点击）+ 返回列表可清空（内部导航）。 */
	const [code, setCode] = (0, react.useState)(epicCode ?? "");
	const [list, setList] = (0, react.useState)(void 0);
	const [detail, setDetail] = (0, react.useState)(void 0);
	const [tickets, setTickets] = (0, react.useState)(void 0);
	const [error, setError] = (0, react.useState)("");
	const [templates, setTemplates] = (0, react.useState)([]);
	const [createOpen, setCreateOpen] = (0, react.useState)(false);
	const [createWf, setCreateWf] = (0, react.useState)("");
	const [createTitle, setCreateTitle] = (0, react.useState)("");
	const [createBody, setCreateBody] = (0, react.useState)("");
	/** 写集编辑栏（t260829-07 写集生命周期）：每行一条，建议预填，人可增删。 */
	const [createWsText, setCreateWsText] = (0, react.useState)("");
	/** 「本票无文件改动」显式声明（t260901-01）：空写集 + 勾选 → 引擎放行建票（meta 记
	*  no_file_changes）。复位纪律：建议回填 / 关弹层 / 切模板三处都复位，防脏状态跨票残留。 */
	const [createAllowEmpty, setCreateAllowEmpty] = (0, react.useState)(false);
	const [createBusy, setCreateBusy] = (0, react.useState)(false);
	const [createMsg, setCreateMsg] = (0, react.useState)("");
	/** 立项列表状态筛选（t260831-05）：'' = 全部，其余为四枚举值之一（纯前端过滤）。 */
	const [statusFilter, setStatusFilter] = (0, react.useState)("");
	/** 状态编辑栏（t260831-05）：详情页状态下拉 + 备注输入框 → POST /epics/<code>/status。 */
	const [editStatus, setEditStatus] = (0, react.useState)("");
	const [editNote, setEditNote] = (0, react.useState)("");
	/** 备注是否被改动过（评审拍板）：未改动 → 请求体省略 note 字段（不动备注，
	*  防误清空丢自由文本）；改动过 → 传新值（''=用户显式清空）。显式 dirty 标记比
	*  字符串比较少边界（改了又改回原文仍视为未动，取安全侧）。 */
	const [noteDirty, setNoteDirty] = (0, react.useState)(false);
	const [saveBusy, setSaveBusy] = (0, react.useState)(false);
	const [saveMsg, setSaveMsg] = (0, react.useState)("");
	(0, react.useEffect)(() => {
		setCode(epicCode ?? "");
	}, [epicCode, epicNonce]);
	(0, react.useEffect)(() => {
		let cancelled = false;
		async function load() {
			try {
				const d = await getJson(withEpicProject(EPICS_API, projectKey));
				if (!cancelled && d?.ok === true) setList(d.result?.epics ?? []);
			} catch {}
		}
		load();
		const stopPoll = startVisibleInterval(() => {
			load();
		}, 1e4);
		return () => {
			cancelled = true;
			stopPoll();
		};
	}, [projectKey]);
	(0, react.useEffect)(() => {
		if (!code) {
			setDetail(void 0);
			return;
		}
		let cancelled = false;
		setDetail(void 0);
		setError("");
		(async () => {
			try {
				const d = await getJson(withEpicProject(`${EPICS_API}/${encodeURIComponent(code)}`, projectKey));
				if (cancelled) return;
				if (d?.ok !== true) {
					setError(d?.error ?? "Failed to load the epic");
					return;
				}
				setDetail(d.result);
			} catch (err) {
				if (!cancelled) setError(String(err instanceof Error ? err.message : err));
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [code]);
	(0, react.useEffect)(() => {
		if (detail === void 0) return;
		setEditStatus(isEpicStatusValue(detail.status) ? detail.status : "");
		setEditNote(String(detail.note ?? ""));
		setNoteDirty(false);
		setSaveMsg("");
	}, [detail]);
	/** 状态编辑保存（t260831-05）：POST /epics/<code>/status——noteDirty 时带 note 字段，
	*  未改动省略（后端语义：缺省=不动备注，''=清空）。成功后重拉详情（上面 effect
	*  自动归位），失败人话报错（后端 422 枚举/备注校验原样透出）。 */
	const saveStatus = (0, react.useCallback)(async () => {
		if (saveBusy) return;
		if (!projectKey) {
			setSaveMsg("Unknown current project — cannot save the status");
			return;
		}
		if (editStatus === "") {
			setSaveMsg("Save failed: select a status first");
			return;
		}
		setSaveBusy(true);
		setSaveMsg("");
		try {
			const d = await (await fetch(withEpicProject(`${EPICS_API}/${encodeURIComponent(code)}/status`, projectKey), {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(noteDirty ? {
					status: editStatus,
					note: editNote
				} : { status: editStatus })
			})).json();
			if (d?.ok !== true) {
				setSaveMsg(`Save failed: ${String(d?.error ?? "unknown error")}`);
				return;
			}
			setSaveMsg(`Saved: ${String(d?.result?.status ?? "")}`);
			try {
				const e = await getJson(withEpicProject(`${EPICS_API}/${encodeURIComponent(code)}`, projectKey));
				if (e?.ok === true) setDetail(e.result);
			} catch {}
		} catch (err) {
			setSaveMsg(`Save request failed: ${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setSaveBusy(false);
		}
	}, [
		saveBusy,
		editStatus,
		noteDirty,
		editNote,
		code,
		projectKey
	]);
	(0, react.useEffect)(() => {
		if (!code) {
			setTickets(void 0);
			return;
		}
		let cancelled = false;
		async function load() {
			try {
				const d = await getJson(withEpicProject(`${EPICS_API}/${encodeURIComponent(code)}/tickets`, projectKey));
				if (!cancelled && d?.ok === true) setTickets(d.result);
			} catch {}
		}
		load();
		const stopPoll = startVisibleInterval(() => {
			load();
		}, 8e3);
		return () => {
			cancelled = true;
			stopPoll();
		};
	}, [code, projectKey]);
	(0, react.useEffect)(() => {
		if (!createOpen || templates.length > 0) return;
		(async () => {
			try {
				const d = await getJson(`${WF_API}/workflows`);
				if (d?.ok === true) setTemplates(d.result ?? []);
			} catch {}
		})();
	}, [createOpen, templates.length]);
	const openCreate = (0, react.useCallback)(() => {
		setCreateWf("");
		setCreateTitle("");
		setCreateBody(epicCreateNote(code) + "\n");
		setCreateWsText("");
		setCreateAllowEmpty(false);
		setCreateMsg("");
		setCreateOpen(true);
	}, [code]);
	const submitCreate = (0, react.useCallback)(async () => {
		if (createBusy) return;
		if (!projectKey) {
			setCreateMsg("Unknown target project for the new ticket — select a project on the left first");
			return;
		}
		if (!createWf) {
			setCreateMsg("Select a ticket template");
			return;
		}
		if (createTitle.trim() === "") {
			setCreateMsg("Enter a ticket title");
			return;
		}
		const badWs = invalidWriteSetLines(createWsText);
		if (badWs.length > 0) {
			setCreateMsg(`Write set contains invalid paths (must be repo-relative; absolute paths and '..' are rejected): ${badWs.slice(0, 3).join(", ")}`);
			return;
		}
		const wsBlocked = createWriteSetBlocked(createWsText, createAllowEmpty);
		if (wsBlocked !== "") {
			setCreateMsg(wsBlocked);
			return;
		}
		const payload = buildCreatePayload({
			workflow: createWf,
			title: createTitle.trim(),
			body: createBody,
			epic: code
		}, createWsText, createAllowEmpty);
		setCreateBusy(true);
		setCreateMsg("");
		try {
			const d = await (await fetch(`${WF_API}/tickets?project=${encodeURIComponent(projectKey)}`, {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(payload)
			})).json();
			if (d?.ok !== true) {
				setCreateMsg(`Create failed: ${d?.error ?? "unknown error"}`);
				return;
			}
			const newId = String(d.result?.id ?? "");
			try {
				const t = await getJson(withEpicProject(`${EPICS_API}/${encodeURIComponent(code)}/tickets`, projectKey));
				if (t?.ok === true) setTickets(t.result);
			} catch {}
			setCreateOpen(false);
			setCreateMsg(`Created ticket ${newId} (epic ${code})`);
		} catch (err) {
			setCreateMsg(`Create request failed: ${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setCreateBusy(false);
		}
	}, [
		createBusy,
		projectKey,
		createWf,
		createTitle,
		createBody,
		createWsText,
		createAllowEmpty,
		code
	]);
	if (!code) return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-ep-root",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: CSS$1 }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-ep-head",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ep-title",
						children: "Epics"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ep-sub",
						children: "Source = notes/epics/*.md (edited in the repo; read-only here)"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { style: { flex: 1 } }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", {
						className: "wb-ep-sub",
						style: {
							display: "flex",
							alignItems: "center",
							gap: 6
						},
						children: ["Status filter", /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
							className: "wb-ep-input",
							"data-testid": "epic-status-filter",
							value: statusFilter,
							onChange: (ev) => setStatusFilter(ev.target.value || ""),
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
								value: "",
								children: "All"
							}), EPIC_STATUS_OPTIONS.map((s) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
								value: s,
								children: s
							}, s))]
						})]
					})
				]
			}),
			list === void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-ep-empty",
				children: "Loading…"
			}) : list.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-ep-empty",
				children: "No epics yet (notes/epics/ is empty or missing)."
			}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("table", {
				className: "wb-ep-table",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("thead", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Code" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Title" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Status" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Note" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Created" })
				] }) }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("tbody", { children: filterEpicsByStatus(list, statusFilter).map((e) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", {
					onClick: () => setCode(e.code),
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-ep-code",
							children: e.code
						}) }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: e.title || "—" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: e.status || "—" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: e.note || "—" }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: e.created || "—" })
					]
				}, e.code)) })]
			})
		]
	});
	const sorted = sortEpicTickets(tickets?.tickets ?? []);
	const merged = mergeBuckets(tickets?.buckets ?? {});
	const bucketKeys = sortBucketKeys(Object.keys(merged));
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-ep-root",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: CSS$1 }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-ep-head",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-ep-btn",
						onClick: () => setCode(""),
						children: "← Back to list"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ep-code",
						children: code
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ep-title",
						children: detail?.title ?? ""
					}),
					detail?.created && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-ep-sub",
						children: ["Created ", detail.created]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
						className: "wb-ep-input",
						"data-testid": "epic-status-edit",
						style: { maxWidth: 180 },
						title: "Epic status (one of four enum values; saving rewrites the status row of notes/epics/<code>.md)",
						value: editStatus,
						disabled: detail === void 0,
						onChange: (ev) => setEditStatus(ev.target.value || ""),
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: "",
							children: "Select status…"
						}), EPIC_STATUS_OPTIONS.map((s) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
							value: s,
							children: s
						}, s))]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
						className: "wb-ep-input",
						"data-testid": "epic-note-edit",
						style: { width: 260 },
						title: "Note (single line, ≤200 chars; empty = clear the note; untouched = leave the note column alone)",
						placeholder: "Note (optional)",
						maxLength: 200,
						value: editNote,
						disabled: detail === void 0,
						onChange: (ev) => {
							setEditNote(ev.target.value);
							setNoteDirty(true);
						}
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-ep-btn",
						"data-testid": "epic-status-save",
						disabled: saveBusy || detail === void 0 || editStatus === "",
						title: "Save the status (with optional note) to notes/epics/<code>.md (backed up to /tmp first)",
						onClick: () => {
							saveStatus();
						},
						children: saveBusy ? "Saving…" : "Save status"
					}),
					saveMsg !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-ep-sub",
						children: saveMsg
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { style: { flex: 1 } }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-ep-btn wb-ep-btn-green",
						onClick: openCreate,
						title: "Start a new ticket from this epic (the code is carried in automatically, not hand-typed)",
						children: "＋ New Ticket"
					})
				]
			}),
			createMsg !== "" && !createOpen && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-ep-msgok",
				children: createMsg
			}),
			error !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-ep-err",
				children: error
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-ep-cols",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-ep-md",
					children: detail === void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-ep-empty",
						children: "Loading epic…"
					}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-md",
						dangerouslySetInnerHTML: { __html: renderMarkdown(detail.markdown) }
					})
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-ep-side",
					children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-ep-panel",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-panel-title",
							children: ["Related tickets", tickets?.count !== void 0 ? ` (${tickets.count})` : ""]
						}), tickets?.degraded === true ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-ep-degraded",
							children: tickets.reason ?? "Ticket status query degraded"
						}) : tickets === void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-ep-empty",
							children: "Loading ticket status…"
						}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-chips",
							children: [bucketKeys.map((k) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "wb-ep-bucket",
								"data-b": k,
								children: [
									k,
									" × ",
									merged[k] ?? 0
								]
							}, k)), bucketKeys.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-ep-empty",
								children: "No tickets linked to this epic yet."
							})]
						}), sorted.map((t) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-ticket",
							title: onOpenTicket ? `${t.id}\n${t.title}\nClick to open the ticket detail` : t.id,
							onClick: () => onOpenTicket?.(t.id),
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "l1",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "id",
									children: t.id
								}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "ti",
									children: t.title
								})]
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "l2",
								children: [
									t.status,
									t.stage ? ` · ${t.stage}` : "",
									t.stage_state ? ` · ${t.stage_state}` : ""
								]
							})]
						}, t.id))] })]
					})
				})]
			}),
			createOpen && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-ep-modal",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ep-modal-box",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-modal-title",
							children: ["New Ticket — from epic ", code]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-field",
							children: ["Epic (carried in by the UI, read-only)", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "wb-ep-readonly",
								children: code
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-field",
							children: ["Ticket template", /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
								className: "wb-ep-input",
								value: createWf,
								onChange: (e) => {
									setCreateWf(e.target.value);
									setCreateAllowEmpty(false);
								},
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
									value: "",
									children: "Select a template…"
								}), templates.map((w) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("option", {
									value: w.id,
									children: [
										workflowLabel(w.id),
										" (",
										w.id,
										")"
									]
								}, w.id))]
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-field",
							children: ["Ticket title", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
								className: "wb-ep-input",
								value: createTitle,
								onChange: (e) => setCreateTitle(e.target.value),
								placeholder: "One line on what this ticket should do"
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-field",
							children: ["Ticket body (the epic note is injected as the first line; continue with the request text)", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
								className: "wb-ep-input",
								style: { minHeight: 140 },
								value: createBody,
								onChange: (e) => setCreateBody(e.target.value)
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-field",
							children: ["Write set (files expected to change, one per line; enforced as the agent allow-list after creation and auto-extended once the plan is final)", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
								className: "wb-ep-input",
								style: {
									minHeight: 64,
									fontFamily: "monospace"
								},
								value: createWsText,
								onChange: (e) => setCreateWsText(e.target.value),
								placeholder: "server/engine/client.py\nserver/plugins/workbench/src/client/epics.tsx"
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", {
							className: "wb-ep-sub",
							style: {
								display: "flex",
								alignItems: "flex-start",
								gap: 6
							},
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
								type: "checkbox",
								style: { marginTop: 3 },
								checked: createAllowEmpty,
								onChange: (e) => setCreateAllowEmpty(e.target.checked)
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["No file changes in this ticket (allow_empty_write_set) — checking this lets creation through, and meta records no_file_changes;", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("strong", {
								style: { color: "var(--dsw-derive-warn,#9a6700)" },
								children: "Only for tickets with truly no file changes; otherwise fill in the write set"
							})] })]
						}),
						createMsg !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-ep-err",
							children: createMsg
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ep-ops",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-ep-btn wb-ep-btn-green",
									disabled: createBusy || !projectKey,
									onClick: () => {
										submitCreate();
									},
									title: projectKey ? "" : "Select a project on the left first",
									children: createBusy ? "Creating…" : "Create Ticket"
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-ep-btn",
									onClick: () => {
										setCreateAllowEmpty(false);
										setCreateOpen(false);
									},
									children: "Cancel"
								}),
								!projectKey && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-ep-sub",
									children: "Unknown target project for the new ticket — select a project on the left first"
								})
							]
						})
					]
				})
			})
		]
	});
}
//#endregion
//#region src/client/ticket-overlay-model.ts
const EMPTY_OVERLAY = {
	current: null,
	crumb: null
};
/** Click a row in the ticket list: open the ticket detail (no breadcrumb; any epic content on show is replaced wholesale). */
function openTicket(nav, ticketId) {
	const id = cleanId(ticketId);
	if (id === null) return nav;
	return {
		current: {
			kind: "ticket",
			id
		},
		crumb: null
	};
}
/** Click the epic badge inside a ticket detail: same layer, content becomes the epic detail (the source ticket stays in selectedId; the walk-back goes to the epic). */
function drillToEpic(nav, epicCode) {
	const code = cleanId(epicCode);
	if (code === null) return nav;
	if (nav.current === null || nav.current.kind !== "ticket") return nav;
	return {
		current: {
			kind: "epic",
			id: code
		},
		crumb: null
	};
}
/** Click a ticket row inside the epic detail: same layer, content becomes the ticket detail; crumb = that epic, the head shows the breadcrumb. */
function drillToTicketFromEpic(nav, ticketId, epicCode) {
	const id = cleanId(ticketId);
	const code = cleanId(epicCode);
	if (id === null) return nav;
	return {
		current: {
			kind: "ticket",
			id
		},
		crumb: code
	};
}
/** Click the breadcrumb `← <epic>`: same layer, back to the epic detail; crumb cleared. */
function breadcrumbBack(nav) {
	if (nav.crumb === null) return nav;
	return {
		current: {
			kind: "epic",
			id: nav.crumb
		},
		crumb: null
	};
}
/** Close (×/Esc): back to null = the underlying view is exactly as it was. */
function closeOverlay(_nav) {
	return EMPTY_OVERLAY;
}
/** Single visibility decision for the breadcrumb: only "ticket detail + a source epic" renders `← code`. */
function crumbOf(nav) {
	return nav.current !== null && nav.current.kind === "ticket" ? nav.crumb : null;
}
/**
* ArrowUp/ArrowDown walks the tickets of the current project.
*
* End behavior (pinned explicitly, review condition 2): **stop at the end, no
* wrap-around** — ArrowUp on the first ticket and ArrowDown on the last both
* stay put. Why: this list is "the current project's ticket list"; jumping to
* the other end is a long-distance teleport the eye loses track of; for the
* read-several-tickets flow, "reached the end" is more predictable than
* "wrapped around". A malformed direction (not 'up'/'down') and a malformed
* list (non-strings / empty strings / duplicate ids) are skipped and
* deduplicated, never thrown. Current ticket missing from the list (removed by
* a list refresh) → stay put.
*/
function neighborTicketId(rows, currentId, direction) {
	if (direction !== "up" && direction !== "down") return cleanId(currentId);
	const cur = cleanId(currentId);
	if (cur === null) return null;
	const ids = [];
	if (Array.isArray(rows)) for (const r of rows) {
		const id = cleanId(typeof r === "object" && r !== null ? r.id : r);
		if (id !== null && !ids.includes(id)) ids.push(id);
	}
	const i = ids.indexOf(cur);
	if (i === -1) return cur;
	const j = direction === "up" ? i - 1 : i + 1;
	if (j < 0 || j >= ids.length) return cur;
	return ids[j];
}
/** Accept only a non-empty string; everything else (null/undefined/number/object/empty string) is malformed → null. */
function cleanId(v) {
	return typeof v === "string" && v.trim() !== "" ? v : null;
}
//#endregion
//#region src/client/spec-block.tsx
function strList(v) {
	if (!Array.isArray(v)) return [];
	const out = [];
	for (const x of v) if (typeof x === "string" && x.trim() !== "") out.push(x);
	return out;
}
function SpecBlock({ body, spec, acceptance, writeSet, redLine, specHtml }) {
	const specText = typeof spec === "string" && spec.trim() !== "" ? spec : "";
	const bodyText = typeof body === "string" && body.trim() !== "" ? body : "";
	const acc = strList(acceptance);
	const ws = strList(writeSet);
	const rl = typeof redLine === "string" && redLine.trim() !== "" ? redLine : "";
	if (specText === "" && bodyText === "" && acc.length === 0 && ws.length === 0 && rl === "") return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-spec-block",
		"data-testid": "spec-block",
		children: [
			specText !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-d2-spec",
				"data-v": "B",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "ttl",
					children: ["Execution spec", /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "cnt",
						children: [specText.length, " chars"]
					})]
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "txt wb-md",
					dangerouslySetInnerHTML: { __html: specHtml ?? "" }
				})]
			}),
			acc.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-spec-acc",
				"data-testid": "spec-acceptance",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "ttl",
					children: [
						"Acceptance (",
						acc.length,
						")"
					]
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("ul", { children: acc.map((a, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("li", { children: a }, i)) })]
			}),
			ws.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-spec-ws",
				"data-testid": "spec-write-set",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "ttl",
					children: [
						"Write set (",
						ws.length,
						")"
					]
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "chips",
					children: ws.map((w) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", {
						className: "ws-chip",
						children: w
					}, w))
				})]
			}),
			rl !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-spec-redline",
				"data-testid": "spec-red-line",
				children: ["Red line: ", rl]
			}),
			bodyText !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
				className: "wb-spec-orig",
				"data-testid": "spec-original",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: "Original request (verbatim)" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", { children: bodyText })]
			})
		]
	});
}
//#endregion
//#region src/client/ticket-detail-column-model.ts
function asStr(v) {
	return typeof v === "string" ? v : "";
}
/**
* Decision card text per state (design §7.3 table, host order wording):
* - awaiting-human → 'Waiting for you: sign the merge' + what is being signed
*   + 'send it back instead if the diff is wrong';
* - paused → 'Paused by you' + 'it stops after the current stage ends';
* - queued → 'Queued, position N' (position may be unknown → plain 'Queued',
*   never a fabricated number) + 'it starts when a slot frees';
* - otherwise (running / awaiting / blocked) → 'At work: <stage>' +
*   'nothing to decide yet'.
* null: closed tickets, terminal done state, inspection tickets (the
* inspection face is its own decision surface — no double frame) and any face
* with neither a status nor a stage_state (malformed input renders nothing).
*/
function decisionCard(detail, queuePosition) {
	if (detail === null || typeof detail !== "object") return null;
	if (detail.kind === "inspection" || detail.engine === "inspection") return null;
	const status = asStr(detail.status);
	const ss = asStr(detail.stage_state);
	if (status === "" && ss === "") return null;
	if (status === "closed" || ss === "done") return null;
	const stage = asStr(detail.stage_name) || asStr(detail.stage) || "the current stage";
	if (ss === "awaiting-human") return {
		title: "Waiting for you: sign the merge",
		body: `Sign the ${stage} handoff and the ticket advances. Send it back instead if the diff is wrong.`
	};
	if (detail.paused === true) return {
		title: "Paused by you",
		body: "It stops after the current stage ends."
	};
	if (status === "queued" || ss === "queued") return {
		title: typeof queuePosition === "number" && Number.isFinite(queuePosition) && queuePosition >= 1 ? `Queued, position ${queuePosition}` : "Queued",
		body: "It starts when a slot frees."
	};
	return {
		title: `At work: ${stage}`,
		body: "Nothing to decide yet."
	};
}
/**
* Receipts box (sec 7.3, 'last receipt'): the LAST gate round of the same gate_runs
* face the checks detail consumes. Rows: `<label>: <green> of <total> green`,
* plus the suite counts and the env red count ONLY when the face carries them.
* Absent/empty/malformed face → null (render nothing).
*/
function receiptRows(gateRuns) {
	if (!Array.isArray(gateRuns)) return null;
	let last = null;
	for (let i = gateRuns.length - 1; i >= 0; i--) {
		const r = gateRuns[i];
		if (r !== null && typeof r === "object" && Array.isArray(r.checks)) {
			last = r;
			break;
		}
	}
	if (last === null) return null;
	const rows = [];
	const label = asStr(last.label) || asStr(last.stage) || "check";
	const checks = last.checks;
	const total = checks.length;
	const green = checks.filter((c) => c !== null && typeof c === "object" && c.green === true).length;
	rows.push({
		k: label,
		v: total > 0 ? `${green} of ${total} green` : "no checks recorded"
	});
	const suite = last.suite;
	if (suite !== null && typeof suite === "object" && !Array.isArray(suite)) {
		const s = suite;
		const ran = typeof s.ran === "number" ? s.ran : void 0;
		const passed = typeof s.passed === "number" ? s.passed : void 0;
		if (ran !== void 0 && passed !== void 0) {
			const known = typeof s.known === "number" ? ` / ${s.known} known` : "";
			rows.push({
				k: "suite",
				v: `${ran} ran / ${passed} passed${known}`
			});
		}
	}
	const red = typeof last.red_count === "number" && Number.isFinite(last.red_count) ? last.red_count : void 0;
	if (red !== void 0 && red > 0) rows.push({
		k: "env red",
		v: String(red)
	});
	return rows;
}
/**
* Stage notes (host order: per-stage gen and round counts from the snapshot's
* faces). Round counts come from the snapshot `gens` face (stage → round
* number, t260915-01); entries without it fall back to counting `running`
* timeline entries per stage. Absent faces / no stages → null.
*/
function stageNoteRows(detail) {
	if (detail === null || typeof detail !== "object") return null;
	const d = detail;
	const gens = d.gens !== null && typeof d.gens === "object" && !Array.isArray(d.gens) ? d.gens : null;
	const runsByStage = /* @__PURE__ */ new Map();
	if (Array.isArray(d.timeline)) for (const t of d.timeline) {
		if (t === null || typeof t !== "object") continue;
		const e = t;
		if (e.state !== "running") continue;
		const stage = asStr(e.stage);
		if (!stage) continue;
		runsByStage.set(stage, (runsByStage.get(stage) ?? 0) + 1);
	}
	const stages = /* @__PURE__ */ new Set([...Object.keys(gens ?? {}), ...runsByStage.keys()]);
	if (stages.size === 0) return null;
	const out = [];
	for (const stage of [...stages].sort()) {
		const gen = gens !== null && typeof gens[stage] === "number" ? gens[stage] : null;
		const runs = runsByStage.get(stage) ?? 0;
		if (gen !== null && gen >= 1) out.push({
			stage,
			note: `round ${gen}${runs > 1 ? ` · entered ${runs} times` : ""}`
		});
		else if (runs > 0) out.push({
			stage,
			note: runs === 1 ? "ran once" : `ran ${runs} times`
		});
	}
	return out.length > 0 ? out : null;
}
/** +/− line count over one unified diff text (skips +++/--- header lines). */
function unifiedStats$1(text) {
	if (typeof text !== "string") return {
		add: 0,
		del: 0
	};
	let add = 0;
	let del = 0;
	for (const l of text.split("\n")) {
		if (l.startsWith("+++") || l.startsWith("---")) continue;
		if (l.startsWith("+")) add++;
		else if (l.startsWith("-")) del++;
	}
	return {
		add,
		del
	};
}
/**
* Changes box (mock kv2): file count and the +/− line, the lane path and
* branch. Data: the same diff face the changeset section consumes
* (GET /tickets/:id/diff → {files:[{unified?...}], worktree?}) plus the
* snapshot's worktree/branch keys. No diff face or an unreadable one → null
* (the §7.3 rule: no face, no scaffolding — the collapsed changeset section is
* the place that names read errors).
*/
function changeRows(diff, detail) {
	if (diff === null || typeof diff !== "object") return null;
	const files = diff.files;
	if (!Array.isArray(files)) return null;
	let add = 0;
	let del = 0;
	for (const f of files) {
		if (f === null || typeof f !== "object") continue;
		const st = unifiedStats$1(f.unified);
		add += st.add;
		del += st.del;
	}
	const rows = [{
		k: "files",
		v: `${files.length} · +${add} −${del}`
	}];
	const d = detail !== null && typeof detail === "object" ? detail : {};
	const lane = [asStr(d.worktree), asStr(d.branch)].filter((s) => s !== "").join(" · ");
	if (lane !== "") rows.push({
		k: "lane",
		v: lane
	});
	return rows;
}
/**
* Requests on this ticket: the request-ledger head rows whose source_ticket
* equals this ticket id (field landed with t261007-02; legacy rows without the
* field never match). Malformed rows (non-object, missing/non-string id or
* question) are skipped, never thrown. No rows → null (render nothing).
*/
function requestsForTicket(rows, ticketId) {
	if (!Array.isArray(rows) || typeof ticketId !== "string" || ticketId === "") return null;
	const out = [];
	for (const r of rows) {
		if (r === null || typeof r !== "object") continue;
		const o = r;
		if (o.source_ticket !== ticketId) continue;
		if (asStr(o.id) === "" || asStr(o.question) === "") continue;
		out.push(o);
	}
	return out.length > 0 ? out : null;
}
/**
* Timeline rows (same activity feed the live panel reads: the snapshot's
* timeline face). Malformed entries skipped; empty face → null.
*/
function timelineRows(timeline) {
	if (!Array.isArray(timeline)) return null;
	const out = [];
	for (const t of timeline) {
		if (t === null || typeof t !== "object") continue;
		const e = t;
		const stage = asStr(e.stage);
		const state = asStr(e.state);
		if (stage === "" && state === "") continue;
		out.push({
			at: asStr(e.at),
			stage,
			state,
			reason: asStr(e.reason)
		});
	}
	return out.length > 0 ? out : null;
}
//#endregion
//#region src/client/terminal-face.ts
/** 恒定兜底文案（与引擎 face 面语义一致；face 缺失时 UI 侧唯一免责声明源）。 */
const TERMINAL_FACE_FALLBACKS = {
	execStatus: "Unknown",
	reasonNote: "Reason unavailable: failure-face data missing or malformed — not invented",
	snapshotNote: "No snapshot: a closed workflow no longer runs and no worker answers the snapshot query (deterministic for terminal state, not transient; refreshing will not help)",
	lastStageNote: "Last known stage unavailable: omitted rather than guessed"
};
/** str 消费：非字符串 → ''（畸形降级，不抛）。 */
function strOf(v) {
	return typeof v === "string" ? v : "";
}
/**
* 引擎终态回执 face（unknown，可能 null/非对象/半残）+ 回执错误原文 → 可渲染视图。
* 纯函数：不抛、不编造；缺什么显式写什么。
*/
function terminalFaceView(face, receiptError) {
	const errTxt = strOf(receiptError);
	if (face === null || typeof face !== "object" || Array.isArray(face)) return {
		execStatus: TERMINAL_FACE_FALLBACKS.execStatus,
		reason: "",
		reasonAvailable: false,
		reasonNote: TERMINAL_FACE_FALLBACKS.reasonNote,
		receiptError: errTxt,
		snapshotNote: TERMINAL_FACE_FALLBACKS.snapshotNote,
		lastStage: "",
		lastStageNote: TERMINAL_FACE_FALLBACKS.lastStageNote,
		ticketId: "",
		project: "",
		epic: "",
		instanceId: "",
		period: "",
		startTimeTxt: "",
		closeTimeTxt: ""
	};
	const f = face;
	const reason = strOf(f.reason);
	const reasonAvailable = f.reason_available === true && reason !== "";
	const lastStage = strOf(f.last_stage);
	return {
		execStatus: strOf(f.exec_status) || TERMINAL_FACE_FALLBACKS.execStatus,
		reason,
		reasonAvailable,
		reasonNote: reasonAvailable ? strOf(f.reason_source) || "source: Temporal workflow execution failure info" : strOf(f.reason_source) || strOf(f.reason_unavailable_note) || TERMINAL_FACE_FALLBACKS.reasonNote,
		receiptError: errTxt,
		snapshotNote: strOf(f.snapshot_note) || TERMINAL_FACE_FALLBACKS.snapshotNote,
		lastStage,
		lastStageNote: strOf(f.last_stage_note) || TERMINAL_FACE_FALLBACKS.lastStageNote,
		ticketId: strOf(f.ticket_id),
		project: strOf(f.project),
		epic: strOf(f.epic),
		instanceId: strOf(f.instance_id),
		period: strOf(f.period),
		startTimeTxt: strOf(f.start_time_txt),
		closeTimeTxt: strOf(f.close_time_txt)
	};
}
//#endregion
//#region src/client/tab-presence.ts
/**
* tab-presence.ts —— 工单台多页签共存：在看心跳 + 写事件广播（t260901-15）。
*
* 背景：用户常开多个工单台页签，互相失明——看不到谁在查看/操作哪张工单，
* 两页签对同一工单的写操作（推进/签字/打回/完成等）基于过期前端态互踩；
* 后台页签还照常全速轮询放大查询通道压力。本模块解决前两件（第三件=
* 不可见页签暂停轮询，由 visibility-poll.ts 的可见性门收口）。
*
* 机制（两通道，可独立失效，都不静默）：
*   1. 主通道 BroadcastChannel('sandbar-workbench-tabs')：presence 3s 心跳
*      （含当前查看的工单 id，关抽屉/隐藏页签置 null）+ write 写事件 + bye。
*   2. 兜底通道 localStorage：心跳逐页签写 key（storage 事件跨 document 送达），
*      write 事件写共享 key；BroadcastChannel 不可用（老内核/被禁）时自动走它，
*      行为等价，降级在注释里写明，不静默。
*
* 故障模式取舍：
*   - 页签崩溃发不出 bye → 靠 10s TTL 过期剔除，viewersOf 永不卡死；
*   - 入站消息是外部输入 → 五类畸形（非 JSON/缺字段/未知类型/字段类型不对/
*     超长）一律丢弃不崩；
*   - 心跳/定时器 → stop() 与 pagehide 双终态回收；
*   - 本模块是 UI 层软机制（不做服务端在场登记），崩溃/降级时退化为
*     「无提示」，不影响任何写操作主路径。
*
* 模块顶层零 IO（smoke 在 node 裸跑，须先 stub BroadcastChannel/localStorage/
* document 再 import 后调用 startTabPresence——同 session-ledger-store 先例）。
*/
/** presence 心跳间隔（ms）。 */
const HEARTBEAT_MS = 3e3;
/** 写守门窗口：远端页签在此时间内写过该工单 → 本页签写前二次确认（ms）。 */
const WRITE_WINDOW_MS = 1e4;
/** 写事件留痕保留时长（ms），超时随 prune 丢弃。 */
const WRITE_LOG_TTL_MS = 6e4;
/** 字符串字段长度上限（入站防呆）。 */
const LEN_TAB = 64;
const LEN_WHO = 64;
const LEN_TICKET = 128;
const LEN_OP = 32;
const CHANNEL = "sandbar-workbench-tabs";
const LS_HEARTBEAT_PREFIX = "sandbar-wb-tab-";
const LS_WRITE_KEY = "sandbar-wb-tabwrite";
const PROTO_V = 1;
let clock = () => Date.now();
function str(v, max) {
	return typeof v === "string" && v.length > 0 && v.length <= max ? v : null;
}
function tsNum(v) {
	return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null;
}
/** 严格校验入站消息：五类畸形（非对象/缺字段/未知 k/字段类型不对/超长）→ null。 */
function parseMsg(raw) {
	if (raw === null || typeof raw !== "object") return null;
	const o = raw;
	if (o.v !== PROTO_V) return null;
	const tab = str(o.tab, LEN_TAB);
	const ts = tsNum(o.ts);
	if (tab === null || ts === null) return null;
	if (o.k === "presence") {
		const who = str(o.who, LEN_WHO);
		if (who === null) return null;
		let ticket;
		if (o.ticket === null || o.ticket === void 0) ticket = null;
		else {
			ticket = str(o.ticket, LEN_TICKET);
			if (ticket === null) return null;
		}
		return {
			v: PROTO_V,
			k: "presence",
			tab,
			who,
			ticket,
			ts
		};
	}
	if (o.k === "write") {
		const who = str(o.who, LEN_WHO);
		const ticket = str(o.ticket, LEN_TICKET);
		const op = str(o.op, LEN_OP);
		if (who === null || ticket === null || op === null) return null;
		return {
			v: PROTO_V,
			k: "write",
			tab,
			who,
			ticket,
			op,
			ts
		};
	}
	if (o.k === "bye") return {
		v: PROTO_V,
		k: "bye",
		tab,
		ts
	};
	return null;
}
/** 惰性能力探测 + 句柄获取（全部包 try/catch：能力缺失走兜底，不静默——注释明写）。 */
function getLS() {
	try {
		if (typeof localStorage !== "undefined") return localStorage;
	} catch {}
	return null;
}
function lsSet(ls, key, value) {
	try {
		ls?.setItem(key, value);
	} catch {}
}
function lsRemove(ls, key) {
	try {
		ls?.removeItem(key);
	} catch {}
}
function lsSweepHeartbeat(ls, now) {
	if (ls === null) return;
	try {
		const stale = [];
		for (let i = 0; i < ls.length; i++) {
			const key = ls.key(i);
			if (key === null || !key.startsWith(LS_HEARTBEAT_PREFIX)) continue;
			const m = parseMsg(JSON.parse(ls.getItem(key) ?? "null"));
			if (m === null || now - m.ts > 1e4) stale.push(key);
		}
		for (const k of stale) lsRemove(ls, k);
	} catch {}
}
/**
* 启动本页签的在场广播。调用方负责在卸载时 stop()（React effect 清理）；
* 重复 start 各自独立（smoke 单模块实例模拟双页签依赖这一点）。
* @param who 操作者标识（工单台 operator，展示在「另一页签正在查看」提示里）。
* @param opts.tabId 测试注入：固定本页签 id（smoke 单模块实例模拟双页签）；
*   生产不传，随机生成。
*/
function startTabPresence(who, opts) {
	const ls = getLS();
	const tab = opts?.tabId ?? `t-${Math.random().toString(36).slice(2, 10)}`;
	let ticketNow = null;
	let stopped = false;
	const peers = /* @__PURE__ */ new Map();
	let writes = [];
	const writeListeners = /* @__PURE__ */ new Set();
	let bc = null;
	try {
		if (typeof BroadcastChannel !== "undefined") bc = new BroadcastChannel(CHANNEL);
	} catch {
		bc = null;
	}
	const onBcMessage = (ev) => {
		ingest(ev.data);
	};
	bc?.addEventListener("message", onBcMessage);
	const visible = () => typeof document === "undefined" || document.visibilityState !== "hidden";
	function send(msg) {
		try {
			bc?.postMessage(msg);
		} catch {}
		if (msg.k === "presence") lsSet(ls, LS_HEARTBEAT_PREFIX + tab, JSON.stringify(msg));
		else if (msg.k === "write") lsSet(ls, LS_WRITE_KEY, JSON.stringify(msg));
	}
	function ingest(raw) {
		const m = parseMsg(raw);
		if (m === null || m.tab === tab) return;
		if (m.k === "presence") peers.set(m.tab, {
			who: m.who,
			ticket: m.ticket,
			ts: m.ts
		});
		else if (m.k === "write") {
			writes.push({
				ticket: m.ticket,
				op: m.op,
				who: m.who,
				ts: m.ts
			});
			const w = {
				ticket: m.ticket,
				op: m.op,
				who: m.who,
				ageMs: Math.max(0, clock() - m.ts)
			};
			for (const cb of writeListeners) try {
				cb(w);
			} catch {}
		} else {
			peers.delete(m.tab);
			lsRemove(ls, LS_HEARTBEAT_PREFIX + m.tab);
		}
	}
	function prune(now) {
		for (const [id, p] of peers) if (now - p.ts > 1e4) peers.delete(id);
		if (writes.length > 0) writes = writes.filter((w) => now - w.ts <= WRITE_LOG_TTL_MS);
	}
	function heartbeat() {
		if (stopped) return;
		const now = clock();
		prune(now);
		send({
			v: PROTO_V,
			k: "presence",
			tab,
			who,
			ticket: visible() ? ticketNow : null,
			ts: now
		});
	}
	function onStorage(ev) {
		if (ev.key === null) return;
		if (ev.key === LS_WRITE_KEY || ev.key.startsWith(LS_HEARTBEAT_PREFIX)) {
			if (ev.newValue !== null) {
				let raw;
				try {
					raw = JSON.parse(ev.newValue);
				} catch {
					return;
				}
				ingest(raw);
			}
		}
	}
	ls?.addEventListener?.("storage", onStorage);
	function onVisibility() {
		heartbeat();
	}
	if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisibility);
	function onPageHide() {
		self.stop();
	}
	if (typeof window !== "undefined") window.addEventListener("pagehide", onPageHide);
	lsSweepHeartbeat(ls, clock());
	heartbeat();
	const timer = setInterval(heartbeat, HEARTBEAT_MS);
	const self = {
		setViewingTicket(t) {
			ticketNow = t;
			heartbeat();
		},
		viewersOf(t) {
			const now = clock();
			prune(now);
			const out = [];
			for (const p of peers.values()) if (p.ticket === t) out.push({
				who: p.who,
				ageMs: Math.max(0, now - p.ts)
			});
			return out;
		},
		notifyWrite(t, op) {
			if (stopped) return;
			const now = clock();
			prune(now);
			send({
				v: PROTO_V,
				k: "write",
				tab,
				who,
				ticket: t,
				op: op.slice(0, LEN_OP),
				ts: now
			});
		},
		recentRemoteWrite(t, withinMs = WRITE_WINDOW_MS) {
			const now = clock();
			prune(now);
			let hit;
			for (const w of writes) {
				if (w.ticket !== t) continue;
				if (now - w.ts > withinMs) continue;
				if (hit === void 0 || w.ts > hit.ts) hit = w;
			}
			return hit === void 0 ? void 0 : {
				op: hit.op,
				who: hit.who,
				ageMs: Math.max(0, now - hit.ts)
			};
		},
		onRemoteWrite(cb) {
			writeListeners.add(cb);
			return () => {
				writeListeners.delete(cb);
			};
		},
		stop() {
			if (stopped) return;
			stopped = true;
			clearInterval(timer);
			try {
				bc?.postMessage({
					v: PROTO_V,
					k: "bye",
					tab,
					ts: clock()
				});
			} catch {}
			lsRemove(ls, LS_HEARTBEAT_PREFIX + tab);
			if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
			if (typeof window !== "undefined") window.removeEventListener("pagehide", onPageHide);
			ls?.removeEventListener?.("storage", onStorage);
			bc?.removeEventListener("message", onBcMessage);
			try {
				bc?.close();
			} catch {}
			bc = null;
		}
	};
	return self;
}
//#endregion
//#region src/client/red-light-lexicon.ts
/** 引擎术语 → 人话词条表。改文案=改这张表（非硬编码）。 */
const REASON_LEXICON = {
	main_staged: {
		headline: "Merge blocked: the main worktree has staged but uncommitted changes (local-change protection, not a conflict)",
		next: "Commit or stash (git stash) these changes in main, then send retry_qc to re-verify; the engine never auto-stashes or auto-commits"
	},
	main_dirty: {
		headline: "Merge blocked: the main worktree has uncommitted changes (local-change protection, not a conflict)",
		next: "Commit or stash (git stash) these changes in main, then send retry_qc to re-verify; the engine never auto-stashes or auto-commits"
	},
	untracked_collision: {
		headline: "Merge blocked: untracked files in the main worktree collide with paths in this merge",
		next: "Move the colliding files away or commit them, then send retry_qc to re-verify; the engine never auto-stashes or auto-commits"
	},
	merge_fault: {
		headline: "Merge did not settle: the merge run hit a fault (not a conflict)",
		next: "Handle it manually, then send retry_qc to re-verify"
	},
	conflict: {
		headline: "Merge conflicts with main",
		next: "Resolve the conflicting files, then send retry_qc to re-verify"
	},
	no_commits: {
		headline: "Implementation not on disk yet: the lane branch has no commits",
		next: "Send rework back to the implement stage to write results to disk"
	},
	worktree_dirty: {
		headline: "Lane worktree is dirty: uncommitted changes",
		next: "Commit or clean up inside the lane, then send retry_qc to re-verify"
	},
	status_failed: {
		headline: "Failed to read git status (environment issue)",
		next: "Check the lane repo, then send retry_qc to re-verify"
	},
	merge_base_failed: {
		headline: "Lane merge-base failed (git environment issue)",
		next: "Check the lane repo, then send retry_qc to re-verify"
	},
	verify_red: {
		headline: "Lane self-check red: the change did not pass this ticket's verification",
		next: "Fix the red items listed in the details, then send retry_qc to re-verify"
	},
	bundle_stale: {
		headline: "Frontend build artifacts are stale: source and lib output are out of sync",
		next: "Rebuild the artifacts in the lane (tsdown), then send retry_qc to re-verify"
	},
	ui_evidence_malformed: {
		headline: "UI screenshot evidence missing or malformed (acceptance gate fallback)",
		next: "Re-run UI screenshots (ui-check/capture-lane), then send retry_qc to re-verify"
	},
	unauthorized_path: {
		headline: "Change exceeds the scope this ticket declared (write-set violation)",
		next: "Send rework back to the plan stage to declare the changed files, or move the out-of-scope files out of the commit"
	},
	protected_path: {
		headline: "Change touches a protected path (a source of truth this ticket may not modify)",
		next: "Move the change out of the protected path; if the change is really needed, go through the authorization channel (sign authorize)"
	},
	unknown_stage: {
		headline: "Gate could not resolve the owning stage (config/version mismatch)",
		next: "Check the template rule table, then send retry_qc to re-verify"
	},
	write_set_missing: {
		headline: "Ticket declares no write set (no change list at filing time)",
		next: "Send rework back to the plan stage to declare the change list"
	},
	ui_dirs_missing: {
		headline: "UI screenshot directory missing (the gate cannot check the screenshot surface)",
		next: "Re-run UI screenshots (ui-check/capture-lane), then send retry_qc to re-verify"
	},
	gate_refusal_unknown: {
		headline: "Stage gate refused (reason code missing)",
		next: "Check the worker log for this refusal, then handle it"
	},
	gate_refusal_malformed: {
		headline: "Stage gate refusal receipt malformed (reason code unreadable)",
		next: "Check the worker log for this refusal, then handle it"
	},
	"awaiting-human": { headline: "Waiting on your approval: the flow is parked at the human gate; the engine will not auto-advance" }
};
/**
* reason_code → 人话。表缺词条回落原文（宁显原文不显空白）；
* 原文也没有 → 可辨的「原因码裸展示」（最后一道锚，仍不空白）。
*/
function translateReason(code, fallbackText) {
	const c = typeof code === "string" ? code.trim() : "";
	if (c) {
		const entry = REASON_LEXICON[c];
		if (entry) return {
			headline: entry.headline,
			next: entry.next,
			fromTable: true
		};
	}
	const fb = typeof fallbackText === "string" ? fallbackText.trim() : "";
	if (fb) return {
		headline: fb,
		fromTable: false
	};
	if (c) return {
		headline: `Blocked (reason code ${c})`,
		fromTable: false
	};
	return {
		headline: "Ticket blocked (engine gave no reason)",
		fromTable: false
	};
}
//#endregion
//#region src/host/status-card.ts
/**
* status-card.ts —— 工单详情「人话状态卡」视图模型（KI-048 件④，t260911-05；
* t260915-05 扩展：文案迁 red-light-lexicon 词条表 + 新增人门蓝卡分支）。
*
* 设计样张：notes/discussions/260904-ticket-detail-ui-mock.html A 块状态卡
* （四件构成：人话主文案 ＋ 挡事文件点名 ＋ 下一步安排 ＋ 原始日志折叠；
* mock C 原则：翻译层表驱动——引擎术语→人话词条，UI 不翻译它没拿到的信息）
* ＋ 屏③ callout E（到人门时状态卡变蓝列出「签什么」）。
*
* 数据源优先级：
*   0. 终态收口卡（t260921-03）：close_health ∈ {abnormal, unreadable} → 已结束
*      对账卡（已结束+结束方式+异常原因+缺了什么；amber 调、零操作）——先于一切
*      受阻/人门分支，已结束票不得再渲染成「受阻等你处置」；
*   1. detail.meta.blocked_detail（引擎 dev_lane 落的结构化面：
*      {reason_code, files, next_action}）——文件点名/下一步直接取；
*   2. detail.blocked_reason（blocked 文案，同一 _classify_main_dirty 真源派生
*      的人话句）——主文案取它；文件名从文本抽路径 token 兜底（老票 KI-048
*      降级锚，仅当结构化面缺席时启用，不冒充结构化数据）；
*   3. 人门蓝卡：stage_state==='awaiting-human' → 「签什么」三源
*      （human_context[gate].context_text 摘要 + stage_acceptance 清单 +
*      最近一次 gate_runs 绿结论）；
*   4. 都缺 → 卡不渲染（返回 null，老票零侵入）。
*
* 纯函数无 IO；畸形输入（非对象/字段类型错/列表超长）全部软降级不抛。
*/
/** 文件名兜底抽取：blocked_reason 文本里的路径形 token（含 / 或 . 且非句读）。 */
const PATH_TOKEN_RE = /[A-Za-z0-9_][A-Za-z0-9_./-]*[/.][A-Za-z0-9_.-]+/g;
function asStringArray(v) {
	if (!Array.isArray(v)) return [];
	return v.filter((x) => typeof x === "string" && x.trim() !== "");
}
function extractPathTokens(text) {
	const seen = /* @__PURE__ */ new Set();
	const out = [];
	for (const tok of text.match(PATH_TOKEN_RE) ?? []) {
		if (!tok.includes("/")) continue;
		if (!seen.has(tok)) {
			seen.add(tok);
			out.push(tok);
		}
	}
	return out;
}
/** 「签什么」三源汇聚（畸形输入逐条跳过，封顶防爆长）。 */
function buildSignWhat(detail) {
	const out = [];
	const humanContext = detail.human_context !== null && typeof detail.human_context === "object" ? detail.human_context : {};
	for (const v of Object.values(humanContext)) {
		if (v === null || typeof v !== "object") continue;
		const ctx = v.context_text;
		if (typeof ctx === "string" && ctx.trim()) for (const line of ctx.split("\n")) {
			const t = line.trim();
			if (t) out.push(t);
		}
	}
	const acceptance = asStringArray(detail.stage_acceptance);
	for (const a of acceptance) {
		if (out.length >= 8) break;
		if (!out.includes(a)) out.push(`Acceptance criterion: ${a}`);
	}
	const gateRuns = Array.isArray(detail.gate_runs) ? detail.gate_runs : [];
	for (let i = gateRuns.length - 1; i >= 0; i--) {
		const g = gateRuns[i];
		if (g === null || typeof g !== "object") continue;
		const go = g;
		if (go.green !== true) continue;
		const stage = typeof go.stage === "string" ? go.stage : "";
		out.push(`All prior gates green: ${stage || "programmatic check"} (ready to sign)`);
		break;
	}
	return out.slice(0, 8);
}
/**
* 构建状态卡视图模型。返回 null = 整卡不渲染（非受阻票/非人门/既无结构化面
* 也无 blocked 文案——老票零侵入）。
*/
function buildStatusCard(detail) {
	if (detail === null || typeof detail !== "object") return null;
	const d = detail;
	const stageState = typeof d.stage_state === "string" ? d.stage_state : "";
	const blockedReason = typeof d.blocked_reason === "string" ? d.blocked_reason.trim() : "";
	const meta = d.meta !== null && typeof d.meta === "object" ? d.meta : {};
	const rawBd = d.blocked_detail !== null && typeof d.blocked_detail === "object" ? d.blocked_detail : meta.blocked_detail;
	const bd = rawBd !== null && typeof rawBd === "object" ? rawBd : {};
	const reasonCode = typeof bd.reason_code === "string" ? bd.reason_code : "";
	const structFiles = asStringArray(bd.files);
	const structNext = typeof bd.next_action === "string" ? bd.next_action.trim() : "";
	const strOf = (v) => typeof v === "string" ? v.trim() : "";
	const execStatus = strOf(d.exec_status) || strOf(meta.exec_status);
	const closeHealth = strOf(d.close_health) || strOf(meta.close_health);
	if (closeHealth === "abnormal" || closeHealth === "unreadable") {
		const reason = strOf(d.close_health_reason) || strOf(meta.close_health_reason);
		const reportPath = strOf(d.report_path) || strOf(meta.report_path);
		const findingsObj = d.findings !== null && typeof d.findings === "object" ? d.findings : {};
		const findingsTotal = typeof findingsObj.total === "number" && Number.isFinite(findingsObj.total) ? findingsObj.total : null;
		const missingTxt = reportPath !== "" ? "No report for this period (the ledger file is the blocked-face mirror)" : findingsTotal !== null ? `No report for this period (${findingsTotal} findings)` : "No report for this period";
		const closeFacts = [
			`Ended: workflow${execStatus ? ` ${execStatus}` : " completed (terminal)"} (Temporal terminal state; no further progress)` + (strOf(d.close_time_txt) ? `; terminal at ${strOf(d.close_time_txt)}` : ""),
			...reason ? [`Close reason: ${reason}`] : [],
			...blockedReason && !reason.includes(blockedReason) ? [`Blocked record (before terminal): ${blockedReason}`] : [],
			...closeHealth === "abnormal" ? [`Missing: ${missingTxt}`] : ["Missing: close face unreadable; artifacts unverified"]
		];
		return {
			headline: closeHealth === "abnormal" ? "Closed (abnormal close)" : "Closed (snapshot unreadable; needs review)",
			headlineFromTable: true,
			files: [],
			filesMore: 0,
			next: closeHealth === "abnormal" ? "Terminal ticket, no advance action here: this card offers no advance or rerun action; the next inspection runs on schedule, and reruns go through the existing channel." : "Terminal ticket, no advance action here: the workflow has ended; a refresh can only re-read the snapshot (the terminal conclusion does not change).",
			rawLog: formatLogTail(d),
			severity: "amber",
			signWhat: [],
			terminal: true,
			closeFacts
		};
	}
	if (stageState === "awaiting-human" && !reasonCode) {
		const tr = translateReason("awaiting-human", blockedReason);
		const signWhat = buildSignWhat(d);
		const rawLog = formatLogTail(d);
		return {
			headline: tr.headline,
			headlineFromTable: tr.fromTable,
			files: [],
			filesMore: 0,
			next: "Human approval: approve = sign off; disagree = send back with a reason. The engine does not move until you sign.",
			rawLog,
			severity: "blue",
			signWhat,
			terminal: false,
			closeFacts: []
		};
	}
	if (stageState !== "blocked" && !reasonCode && !blockedReason) return null;
	const tr = translateReason(reasonCode || null, blockedReason);
	const headline = tr.headline || (reasonCode ? `Merge blocked (${reasonCode})` : "Ticket is blocked");
	const filesAll = structFiles.length > 0 ? structFiles : extractPathTokens(blockedReason);
	const files = filesAll.slice(0, 20);
	const filesMore = Math.max(0, filesAll.length - files.length);
	const next = structNext || tr.next || (stageState === "blocked" ? "Waiting for you: resolve the files above, then trigger retry-qc (or rework). The engine never stashes or commits on its own." : "Follow the reason above; the lane is preserved.");
	return {
		headline,
		headlineFromTable: tr.fromTable,
		files,
		filesMore,
		next,
		rawLog: [...typeof bd.evidence === "string" && bd.evidence.trim() ? [`[evidence] ${bd.evidence.trim()}`] : [], ...formatLogTail(d)],
		severity: stageState === "blocked" ? "red" : "amber",
		signWhat: [],
		terminal: false,
		closeFacts: []
	};
}
/** 原始日志折叠：timeline 尾部 N 条（畸形条目逐条跳过；时间线缺省=一行说明）。 */
function formatLogTail(d) {
	const timeline = Array.isArray(d.timeline) ? d.timeline : [];
	const rawLog = [];
	for (const ent of timeline.slice(-8)) {
		if (ent === null || typeof ent !== "object") continue;
		const e = ent;
		const at = typeof e.at === "string" ? e.at : "?";
		const stage = typeof e.stage === "string" ? e.stage : "?";
		const state = typeof e.state === "string" ? e.state : "?";
		const reason = typeof e.reason === "string" ? e.reason : "";
		rawLog.push(`${at} [${stage}/${state}] ${reason}`.trimEnd());
	}
	if (rawLog.length === 0) rawLog.push("(no engine timeline entries)");
	return rawLog;
}
//#endregion
//#region src/shared/ticket-time-model.ts
function isTicketTimeMode(v) {
	return v === "settle" || v === "base" || v === "current";
}
function refSourceLabel(s) {
	switch (s) {
		case "branch-tip": return "Lane branch commit (unmerged)";
		case "merge-commit": return "merge settle commit";
		case "squash-commit": return "squash settle commit";
		case "base-ref": return "base ref";
	}
}
/**
* 横幅视图模型（mock D：顶部横幅「🕰 本票时刻 · 只读」，带「跳到当前版」小链）。
* current 口径返回 null（横幅消失=切到当前版的可见信号，验收口径①锁这点）。
* refShort 畸形（非字符串/空）返回 null——横幅不渲染假版本号，宁可整条不显。
*/
function buildTicketTimeBanner(mode, refSource, refShort) {
	if (mode === "current") return null;
	if (mode !== "settle" && mode !== "base") return null;
	if (typeof refShort !== "string" || refShort.trim() === "") return null;
	return {
		text: "🕰 Ticket time · read-only",
		version: mode === "settle" ? `Settled ${refShort} · ${refSourceLabel(refSource)}` : `Baseline ${refShort} · ${refSourceLabel(refSource)}`,
		canJumpCurrent: true
	};
}
//#endregion
//#region src/client/ticket-time-viewer.tsx
/**
* ticket-time-viewer.tsx —— 「本票时刻 · 只读」文件查看器弹层（t260915-17，
* 260904 详情 mock 标注 D 落地；查看器样张=notes-ui mock 屏②「UI 内查看器（只读）」）。
*
* 数据源=宿主半 GET /sandbar-workbench/api/wf/tickets/<id>/file?path=&mode=
* （node.ts handleTicketTimeFile；settle=收口版 / base=开票基点版 / current=当前版）。
*
* 版面（mock D 原话）：顶部横幅「🕰 本票时刻 · 只读」+版本副文案（ref 短哈希+来源标签）
* +「跳到当前版」小链——点击切 current 口径重取内容且横幅消失（横幅消失=切到当前版的
* 可见信号，验收口径①）。渲染：.md 走 knowledge renderMarkdown（docs.tsx 同款复用，
* 转义先行/危险 URL 拒绝随 import 带入），其余文件等宽纯文本。只读刚性：本组件源码
* 层面不引入任何编辑/保存控件（无 input/textarea/contentEditable/保存钮），集成场景
* 源码锁直断（sc_ticket_time_file）。
*
* 故障模式取舍清单（review C6，对照先例逐项声明带/不带）：
*   - EvidenceLightbox 的 document 级 keydown + isEditableTarget guard：**带**（详情
*     抽屉含输入件，Esc 关闭复用同款 guard 防误关；isEditableTarget 在 index.tsx 不
*     导出且 import 会成环，此处本地复刻同款 8 行并注释互指）。
*   - EvidenceLightbox 的 evidenceNav 越界兜底：**不带**——查看器单文件无左右导航，
*     无越界面可兜。
*   - 单图加载失败占位：**带**（同语义=人话 reason 面板/加载失败条，不拖垮抽屉）。
*   - handleDocsDoc 的 200+{empty,reason} 人话降级：**带**（同风格——fail-closed 的
*     reason 面板走正常响应渲染，不 500）。
*   - t01 临时真 git 仓 fixture 手法：**带**（tests/t260915-17-ticket-time-file.mjs
*     同款 mkdtemp+rmSync+git timeout）。
*
* 资源终态：in-flight fetch 由 AbortController 收口（mode/path/卸载任一变化即 abort
* 前次）；document keydown 挂载/卸载成对（useEffect cleanup 单点回收）；无定时器/
* 轮询/长驻句柄，正常、报错、取消三路径都落定。
*/
const API_PREFIX = "/sandbar-workbench/api/wf/tickets";
/** 契约锚（集成场景/UT 断言用；不可移除/改名）。 */
const TICKET_TIME_VIEWER_TESTID = "ticket-time-viewer";
/** 与 index.tsx isEditableTarget 同款（C6：复用语义、本地复刻防 import 环）。 */
function isEditableTarget$1(t) {
	if (!(t instanceof HTMLElement)) return false;
	return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable;
}
function TicketTimeViewer({ ticketId, path, initialMode, onClose }) {
	const [mode, setMode] = (0, react.useState)(initialMode);
	const [data, setData] = (0, react.useState)(null);
	const [loadErr, setLoadErr] = (0, react.useState)("");
	const abortRef = (0, react.useRef)(null);
	(0, react.useEffect)(() => {
		const ac = new AbortController();
		abortRef.current?.abort();
		abortRef.current = ac;
		setData(null);
		setLoadErr("");
		fetch(`${API_PREFIX}/${encodeURIComponent(ticketId)}/file?path=${encodeURIComponent(path)}&mode=${mode}`, { signal: ac.signal }).then((r) => r.json()).then((d) => {
			if (!ac.signal.aborted) setData(d?.result ?? null);
		}).catch((err) => {
			if (ac.signal.aborted) return;
			setLoadErr(String(err instanceof Error ? err.message : err));
		});
		return () => {
			ac.abort();
		};
	}, [
		ticketId,
		path,
		mode
	]);
	(0, react.useEffect)(() => () => {
		abortRef.current?.abort();
	}, []);
	(0, react.useEffect)(() => {
		const h = (e) => {
			if (e.key === "Escape" && !isEditableTarget$1(e.target)) {
				e.preventDefault();
				onClose();
			}
		};
		document.addEventListener("keydown", h);
		return () => document.removeEventListener("keydown", h);
	}, [onClose]);
	const resOk = data?.ok === true && typeof data.content === "string" && isTicketTimeMode(data.mode);
	const banner = resOk && data !== null ? buildTicketTimeBanner(mode, data.refSource ?? "base-ref", data.refShort) : null;
	const isMd = /\.md$/i.test(path);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-ttv-mask",
		onClick: (e) => {
			if (e.target === e.currentTarget) onClose();
		},
		children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-ttv",
			"data-testid": TICKET_TIME_VIEWER_TESTID,
			role: "dialog",
			"aria-label": `本票时刻只读查看 ${path}`,
			children: [
				/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ttv-head",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", {
						className: "wb-ttv-path",
						children: path
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-ttv-close",
						"aria-label": "关闭查看器",
						onClick: onClose,
						children: "✕"
					})]
				}),
				banner !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ttv-banner",
					"data-testid": "ticket-time-banner",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-ttv-banner-text",
							children: banner.text
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-ttv-banner-ver",
							children: banner.version
						}),
						banner.canJumpCurrent && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "wb-ttv-jump",
							"data-testid": "ticket-time-jump-current",
							onClick: () => setMode("current"),
							children: "跳到当前版"
						})
					]
				}),
				loadErr !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ttv-fail",
					"data-testid": "ticket-time-fail",
					children: ["读取失败：", loadErr]
				}),
				loadErr === "" && data === null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-ttv-loading",
					children: "读取中…"
				}),
				loadErr === "" && data !== null && data.ok === false && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ttv-fail",
					"data-testid": "ticket-time-fail",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-ttv-fail-ttl",
						children: "拿不到本票时刻的这个版本"
					}), data.reason ?? "原因未知"]
				}),
				loadErr === "" && resOk && (isMd ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-ttv-body wb-doc-body",
					dangerouslySetInnerHTML: { __html: renderMarkdown(String(data?.content ?? "")) }
				}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("pre", {
					className: "wb-ttv-body wb-ttv-code",
					children: [data?.content, data?.truncated === true ? "\n\n（内容超封顶已截断——此处不是完整文件，完整内容走 git show）" : ""]
				})),
				loadErr === "" && resOk && data?.truncated === true && isMd && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-ttv-trunc",
					children: "内容超封顶已截断——此处不是完整文件，完整内容走 git show。"
				})
			]
		})
	});
}
//#endregion
//#region src/client/approve-note.ts
/**
* approve-note.ts —— KI-004（t260901-22）：人审 approve 签字的 note 拼接（纯函数层）。
*
* 工单台 approve 弹层的 note 由两段组成：
*   ① 自动摘要 buildApproveSummary（审批意见统计，只读）；
*   ② 审批人手输的自由备注（可空，KI-004 新增）。
* 有备注时随 sign 进不可变事件历史；无备注时行为与现状逐字节一致。
*
* 纯函数、无 React/IO 依赖：smoke/approve-note.mjs 用 node ≥22.18 type-stripping
* 直跑（模式同 epics-model.ts）；不允许把本逻辑内联回 index.tsx——畸形输入断言
* 必须落在 smoke 文件里。
*/
/**
* 拼接 sign 用 note。
* - remark 空/纯空白 → 只返回 summary.trim()（空备注不污染历史口径）；
* - 两者皆有 → summary.trim() + '\n\n' + remark.trim()（备注独立成段）；
* - 两者皆空 → ''。
* 外部输入只做 trim 与分段，不校验/改写内容（纯文本进历史）。
*/
function buildApproveNote(summary, remark) {
	const s = (summary ?? "").trim();
	const r = (remark ?? "").trim();
	if (s === "") return r;
	if (r === "") return s;
	return `${s}\n\n${r}`;
}
//#endregion
//#region src/client/usage-model.ts
/**
* 用量区可见警示文案（非 hover-only）；null=维持既有呈现（tokens — / 正常行）。
* - exists:true 且 suspect → S1 混合态：totals 来自好文件，坏文件也必须可见；
* - exists:false 且 suspect → S1 全灭：统计值不可信；
* - exists:false 且 suspectFiles 非空 → S3：发现集空但目录有未入统计的会话样文件；
* - 其余（普通没跑过/历史单）→ null，不虚报。
*/
function usageSuspectHint(usage) {
	if (!usage || typeof usage !== "object") return null;
	if (usage.exists === true) return usage.suspect === true ? "⚠ 部分会话记录格式不认识（疑似 dsh 版本不匹配），该部分未计入" : null;
	if (usage.suspect === true) return "⚠ 会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信";
	if (Array.isArray(usage.suspectFiles) && usage.suspectFiles.length > 0) return "⚠ 发现未入统计的会话文件（名字/布局与本版本解析面对不上，疑似 dsh 版本不匹配）";
	return null;
}
/** 悬停明细：S1 逐文件人话（suspectDetail）优先，其次端点 reason。 */
function usageSuspectTitle(usage) {
	if (!usage || typeof usage !== "object") return void 0;
	return usage.suspectDetail ?? usage.reason;
}
/**
* API 回执 → 轮询分类。ok:true → ok；kind=not_found/terminal → 对应致命类；
* 其余（transient/internal/kind 缺失/非对象/网络异常路径传 null）→ retryable。
*/
function classifyPollBody(body) {
	if (body && body.ok === true) return "ok";
	const kind = typeof body?.kind === "string" ? body.kind : "";
	if (kind === "not_found") return "not_found";
	if (kind === "terminal") return "terminal";
	return "retryable";
}
const _RANK = {
	ok: 0,
	retryable: 1,
	not_found: 2,
	terminal: 2
};
/** 同一 tick 内多路请求（列表+详情）取最坏分类，作为本拍的健康度输入。 */
function worstOutcome(a, b) {
	return _RANK[a] >= _RANK[b] ? a : b;
}
/** 状态机转移：ok 清零；致命类立即错误态（不诱导重试）；可重试累加，达阈值升错误态。 */
function nextPollState(prev, outcome) {
	if (outcome === "ok") return {
		failStreak: 0,
		degraded: false
	};
	if (outcome === "not_found" || outcome === "terminal") return {
		failStreak: prev.failStreak,
		degraded: true
	};
	const n = prev.failStreak + 1;
	return {
		failStreak: n,
		degraded: n >= 3
	};
}
const INITIAL_POLL_STATE = {
	failStreak: 0,
	degraded: false
};
//#endregion
//#region src/shared/view-project.ts
/**
* sandbar-workbench · 中列当前项目 key 的模块单态（session-entry t260828-06 从
* src/client/index.tsx 迁出为共享模块）。
*
* 为什么共享：hero 接管组件（client/hero.tsx → HeroSessionEntry）挂在
* `conversation.hero.*` 槽上，scope=root——不在中列组件树内，拿不到 WorkbenchSection
* 的 projectKey prop；只能读这份单态。index.tsx 的 apiGet/apiPost 拼 ?project=
* 也走它（原语义不变：WorkbenchSection 挂载/切换时 setViewProject）。
*
* 空串 = 尚无中列视图激活过（首屏直落 hero 的场景）——hero 侧用
* 「单项目注册表兜底」解析（见 HeroSessionEntry 的 projectKey 推导），多项目
* 未选则新建禁用并提示，与侧栏「会话」区同口径（不造隐形缺省）。
*/
let viewProject = "";
/** 当前中列视图的项目 key（空串=未选/未激活）。 */
function getViewProject() {
	return viewProject;
}
/** WorkbenchSection 挂载/切换项目时写入（index.tsx 唯一写入点）。 */
function setViewProject(project) {
	viewProject = typeof project === "string" ? project : "";
}
//#endregion
//#region src/client/index.tsx
/**
* sandbar-workbench —— 工单工作流台 · 浏览器半（侧栏工单中心版）。
*
* 260823 改版（用户拍板）：chat 顶部页签只留 chat/trajectory——工单台/文档/模型
* 三个视图从 conversation.view 环摘除，改由侧栏接管组件的中栏承载：
* 本插件注册 sidebar.workspaces（priority=-10 抢占 shell 默认浏览器），
* WorkbenchSidebar 左列=项目分组+进行中工单+插件入口，中列=四视图
* （WorkbenchSection 本文件 / DocsSection 本插件 ./docs.tsx（t260905-06 起，
* 顶替 knowledge 插件视图——旧提法退役，界面层不再出现） /
* ProvidersSection 从 providers 插件 import）。t260903-07 起：点工单只开中列
* 详情抽屉，右栏 chat 恒为单全局会话不再切换（每工单会话联动下线，数据留存——
* 见 sidebar.tsx 头注与 notes/debts/design-doc-sync-t260903-07.md）。
* 数据来自 /sandbar-workbench/api/wf/* 而非会话事件。
*
* 页面三区（Ticket Workflow Console Design v0.3 §5/§10）：
*   ① 台面区：工单卡片网格（id | 工作流 | 阶段进度条 | 当前角色 | 状态色板
*     running绿/awaiting黄/awaiting-human蓝/blocked红/done灰）+ 状态/工作流/角色筛选。
*   ② 详情抽屉：泳道图（stages 横排箭头=next，当前高亮，fanout 扇出分叉标注）+
*     验收清单打勾（evidence 展示）+ handoff 接力时间线 + log 流水 + pending 挂起项 +
*     worktree 短 slug / base_ref / proposal_id。
*   ③ 操作区：按 v0.3 §10 操作矩阵只显可用按钮——advance（awaiting-human 时
*     「审批→推进」走 Temporal sign）/ dispatch-next（生成可复制 prompt）/ 打回 / 解除阻塞 / 完成。
*
* 数据通道：同源 fetch 打宿主半（../node.ts）挂在 dsh webServer 上的
* /sandbar-workbench/api/wf/*；写操作走 admin.py call ticket（run-id 审计
* 在 server/admin.log，与模型通道同一真源）。
*
* M9 PR 式审批台（t260821-m9-pr-approval）：详情抽屉加「变更」页签——
* 文档 diff 复用 knowledge 渲染态 block diff（renderMarkdown 直接 import
* knowledge 浏览器半同款渲染器；block diff 由宿主半算好下发）；代码 diff=
* 文件级 unified 渲染；数据 diff=前后值对账表。审批意见按块/文件留，
* POST 落盘 server/reviews/<工单id>.json（多轮；key 含内容哈希，
* 内容变→旧意见标「已过期」）。签字联动：approve 摘要随 sign 进历史，
* reject 意见即返工指令一键复制/一键填入打回理由。
*
* M6 inspection-report section (t260821-m6-scan-expand): retired by t261008-18 —
* the /wf/scan-report route and the section went with the strip's Inspection
* button. A future Inspection-content ticket starts from git history.
*
* M12 agent 日志（t260822-m12）：详情抽屉加「Agent 日志」页签——读
* /sandbar-workbench/api/wf/tickets/<id>/agent-logs 列泳道 .suyou/ 的
* agent_<stage>_gen<n>.log（子 agent stdout/stderr 流，诊断失败现场）
* + stage_<stage>_gen<n>.json（段结算结果：status/summary/deliverables），
* 点文件展开；无目录走 reason 人话降级。
*
* t260825-03 运行可见性：详情头部（所有页签可见）加「运行脉搏」行（detail.pulse
* =Temporal pending activity 心跳：阶段 gen/已运行时长/心跳年龄 + session_kb 增速，
* 停涨/心跳停超阈值亮疑似卡死提示；无心跳显「无心跳」软降级）与「实时动态」折叠
* 面板（agent-live 端点：泳道会话 jsonl.zstd 尾 30 条事件流，展开才 8s 轮询）。
*
* t260826-02 立项单 UI（epic-linkage Tier 3）：侧栏加「立项单」分区 + 中列第四视图
* EpicSection（./epics.tsx：左立项单 Markdown 全文 / 右关联工单实时汇总 + 新建工单
* 入口——epic 界面传值不可手输）；工单列表行与详情头部加所属立项徽标（EpicBadge，
* 点击跳立项详情，无 epic 显灰「未归档」）；人门签字确认区有 epic 时显示
* 「所属立项: <代号>」（无则略——review M1，不显示「未归档」字样）。
*
* t260828-01 执行主体可见（observability）：阶段链每步按模版 STAGES 的 parts 静态
* 声明渲染组合徽标（🤖 agent / ⚙️ 脚本 / 👤 人，直接拼接，悬停一行说明），
* 泳道图/步骤条/进展卡三处复用 PartsBadges；无 parts 旧数据显「—」软降级。
*
* t260828-06 hero 整体更换误伤出厂 chat（t260829-01 退场）；t260829-06 又以三槽
* 槽位替换重进（conversation.hero.workspace→HeroEntry、agentPreset/brand.mark→空），
* 顶掉了出厂 workspace 选择器与 preset，右栏 chat 不可用（不能选 workspace、不能
* 开始 chat）——t260831-02 按 UX 契约把 hero 接管**彻底拆除**：不再注册任何
* conversation.hero.* 槽，出厂落地页（大标题/大输入卡/workspace 选择器）原样回弹，
* 右栏零定制。会话入口收口到一处：顶部行（deepseek logo 正下方出厂「⊕ New
* Session」钮的原地替换；该入口行已随票② R8 退役（t260904-05），sidebar.tsx 的
* 注入锚），见两文件头注。工单会话入口（点工单 handleTicketClick 链路）不受影响。
*/
/** 多项目化（260823）：当前视图的项目 key，WorkbenchSection 挂载/切换时从 prop 设置。
*  中列同一时刻只挂一个视图，模块单态安全。空串=不拼参（host 会 400，UI 先显占位）。
*  t260828-06：单态本体迁到 shared/view-project.ts——hero 接管组件（root 作用域，
*  不在中列组件树内）也要读它做「当前项目」推导。 */
const name = "sandbar-workbench/client";
const inject = [
	"slots",
	"sessions",
	"workspaces"
];
const CSS = `${DERIVE_TOKENS_CSS}
/* ── 工单工作流台 · 现代浅色主题（260820 最终版：去 suyou 中式金棕/衬线，
 *     system-ui 无衬线、高对比、细边框+轻阴影、现代状态色，饱和度适中） ── */
.wb-root{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-fg,#1f2328);min-height:100%;box-sizing:border-box;padding:20px 24px 32px;
  display:flex;flex-direction:column;gap:16px;height:100%;overflow-y:auto;font-size:13px;line-height:1.55}
.wb-title{font-size:20px;font-weight:600;color:var(--dsw-derive-ink-strong,#24292f)}/* t260929-22 gen9：4.05→深墨 */
.wb-sub{font-size:12px;color:var(--dsw-derive-muted,#57606a)}
.wb-err{background:var(--dsw-derive-danger-bg,#ffebe9);border:1px solid var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);border-radius:6px;
  padding:8px 12px;font-size:12px;white-space:pre-wrap}
.wb-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.wb-select{font:inherit;font-size:13px;background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:5px 10px}
.wb-select:focus{outline:none;border-color:var(--dsw-derive-accent,#0969da);box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.wb-btn{font:inherit;font-size:13px;padding:5px 16px;border-radius:6px;cursor:pointer;
  border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328);transition:background .12s}
.wb-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-btn-danger{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-btn-blue{border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
/* ---- 工单列表 v5（t260904-17，mock 屏⑤⑥）：平铺行卡 + 筛选 chips ---- */
/* 状态/epic 筛选 chips：过滤非分组；「等你」chip（data-state=waiting）>0 时黄调强调 */
.wb-chip-btn{font-size:12px;padding:2px 10px;border-radius:10px;border:1px solid var(--dsw-derive-border,#d0d7de);
  background:var(--dsw-derive-canvas,#fff);color:var(--dsw-derive-muted,#57606a);cursor:pointer;white-space:nowrap}
.wb-chip-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-chip-btn[data-on=true]{border-color:var(--dsw-derive-accent,#0969da);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff);font-weight:600}
.wb-chip-btn[data-state=waiting]{border-color:var(--dsw-derive-warn-border,#d4a72c)}
.wb-chip-btn[data-state=waiting][data-on=false]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
/* t260919-02「已失败」chip：红系（与 blocked 同 danger 令牌族，文案「已失败」可辨）。
 * hex-clean 纪律（KI-055 家族）：复用 theme.ts 既有 danger 令牌声明位，消费位只经
 * var() fallback 供出，零新增裸 hex（本票未新增令牌=无新声明位需求）。 */
.wb-chip-btn[data-state=failed]{border-color:var(--dsw-derive-danger-border,#ff9b9b)}
.wb-chip-btn[data-state=failed][data-on=false]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
/* t260921-03「异常收口」chip：黄系（注意但非受阻——异常收口=已结束，不动 danger 族）。
 * hex-clean 纪律同上：warn 令牌既有声明位，零新增裸 hex。 */
/* t261008-18 sweep: .wb-chip-health removed — no JSX face has used it since the
close-health chip left the board card; dead at HEAD too (pre-existing). */
/* t260921-03 收口健康徽标（行1 状态字后，中列与左栏共用行卡全局类）：琥珀描边深字
 * =可扫读的「已结束但有问题」，不用受阻红（已结束≠受阻等你处置）。
 * data-close-health=健康度值锚（渲染断言/样式作用域选择器）。 */
.wb-card-health{display:inline-flex;align-items:center;flex:none;padding:0 5px;
  border:1px solid var(--dsw-derive-warn-border,#d4a72c);border-radius:5px;
  color:var(--dsw-derive-warn-deep,#7d4e00);font-size:10px;line-height:15px;font-weight:600}
.wb-chip-epic{border-style:dashed;border-width:1.5px}
/* 搜索框 */
.wb-search{font-size:12px;padding:3px 10px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;width:180px}
/* 平铺行卡：左缘 epic 彩条由行内 style 注入（哈希色）；等你=黄调行/受阻=红调行
 * （底色由行内 style 注入）、活跃=蓝左条强调、收口=灰折叠 */
.wb-card{display:flex;align-items:center;gap:10px;padding:8px 12px;margin-bottom:6px;
  border:1px solid var(--dsw-derive-border,#d0d7de);border-left-width:4px;border-radius:8px;background:var(--dsw-derive-canvas,#fff);
  cursor:pointer;font-size:13px;flex-wrap:wrap;box-shadow:0 1px 2px rgba(31,35,40,.05)}
/* hover 不再改写底色（会盖掉 waiting/blocked 状态行底）——改阴影提层，主题安全 */
.wb-card:hover{box-shadow:0 1px 4px rgba(31,35,40,.14)}
/* 状态行底=主题令牌派生（t260905-08 根因修复：原行内写死浅色×主题字色=深色不可读）。
 * t260915-08 实证补②：板面卡实际渲染在 .wb-sb-right 内，sidebar 后注入样式表的
 * .wb-sb .wb-card {background:transparent} 规则（同特异性 0,2,0、后序胜）会把状态底色
 * 整体压平（先于本票就存在的看板级 bug，dev-lane 等待行同样瞎）——状态行特有规则
 * 一律提特异性到 .wb-root .wb-card[data-state=…]（0,3,0，顺序无关压制 blanket 规则；
 * active 行让位 sidebar 的选中底色，设计如此）。
 * t260915-08 仲裁修复（hex-clean 看守打回项）：老浏览器 color-mix IACVT 的静态回退
 * 色收编进 theme.ts 令牌声明位（@supports not 分档覆盖令牌值），本消费位只经 var()
 * fallback 供出（allowlist C 合法位），零裸 hex。 */
.wb-root .wb-card[data-state=waiting]{background:var(--dsw-derive-warn-bg,#fff8c5)}
.wb-root .wb-card[data-state=blocked]{background:var(--dsw-derive-danger-bg,#ffebe9)}
/* t260919-02「已失败」行卡：红系行底+实红点/状态字（与 blocked 同令牌族不同文案，
 * 与 done 灰/active 蓝可辨；特异性 0,3,0 与 waiting/blocked 同档，压 sidebar blanket）。 */
.wb-root .wb-card[data-state=failed]{background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-card[data-active=true]{border-color:var(--dsw-derive-accent,#0969da);box-shadow:inset 0 0 0 1px var(--dsw-derive-accent,#0969da)}
.wb-card[data-state=done]{color:var(--dsw-derive-muted,#57606a)}
.wb-card-l1{display:flex;align-items:center;gap:8px;min-width:0;flex:1 1 320px}
.wb-card-dot{width:9px;height:9px;flex:none;position:relative}
.wb-card-dot::before{content:'';position:absolute;inset:0;border-radius:50%;background:var(--dsw-derive-muted,#8c959f)}
.wb-card-dot[data-state=waiting]::before{background:var(--dsw-derive-warn,#bf8700)}
.wb-card-dot[data-state=blocked]::before{background:var(--dsw-derive-danger,#cf222e)}
.wb-card-dot[data-state=failed]::before{background:var(--dsw-derive-danger-solid,#d1242f)}
.wb-card-dot[data-state=active]::before{background:var(--dsw-derive-accent,#0969da)}
.wb-card-dot[data-state=done]::before{background:var(--dsw-derive-muted,#8c959f)}
.wb-card-state{font-size:11px;font-weight:600;flex:none}
/* t260929-22 gen5（对比度红 4.24<4.5）：waiting 态文字锁深（#7d4e00，白底 ≈8:1），
   不再走混平台 label 的令牌——label 极性不定时混不出保证对比度。 */
.wb-card-state[data-state=waiting]{color:var(--dsw-derive-warn,#7d4e00)}
.wb-card-state[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e)}
.wb-card-state[data-state=failed]{color:var(--dsw-derive-danger,#cf222e)}
.wb-card-state[data-state=active]{color:var(--dsw-derive-accent,#0969da)}
.wb-card-state[data-state=done]{color:var(--dsw-derive-muted,#57606a)}
/* 段间暂停徽标（t260908-01）：主题令牌着色（warm 系=注意但非故障），
   data-paused-phase 锚点是集成断言面。 */
.wb-card-paused{font-size:11px;font-weight:600;flex:none;padding:0 7px;border:1px solid var(--dsw-derive-warn-border,#eac54f);border-radius:10px;color:var(--dsw-derive-warn-deep,#7d4e00);background:var(--dsw-derive-warn-surface,#fff8e6);white-space:nowrap}
.wb-card-id{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--dsw-derive-accent,#0969da);flex:none}
.wb-card-title{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;color:var(--dsw-derive-ink-strong,#24292f)}/* t260929-22 gen9：4.24→深墨 */
.wb-card-epic{font-size:11px;padding:0 8px;border:1px solid;border-radius:10px;flex:none;white-space:nowrap}
.wb-card-l2{display:flex;align-items:center;gap:8px;color:var(--dsw-derive-muted,#57606a);font-size:12px;flex:1 1 260px;min-width:0}
.wb-card-progress{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--dsw-derive-muted,#57606a)}/* t260929-22 gen5：进展行白底对比度 2.62<4.5，锁 #57606a（≈5.9:1） */
.wb-card-progress[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e)}
.wb-card-progress[data-state=awaiting-human]{color:var(--dsw-derive-warn,#9a6700)}
.wb-card-time{flex:none}
.wb-card-role{flex:none}
.wb-card-pending{font-size:11px;color:var(--dsw-derive-warn-deep,#7d4e00);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#d4a72c);
  border-radius:4px;padding:0 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 迷你站道：点数=模板阶段数；绿=已过/状态色=当前/灰=未来（颜色随 data-state 派生） */
.wb-card-lane{display:inline-flex;gap:4px;align-items:center;flex:none}
.wb-card-lane-dot{width:8px;height:8px;border-radius:50%;background:var(--dsw-derive-border,#d0d7de);display:inline-block}
.wb-card-lane-dot[data-visual=done]{background:var(--dsw-derive-success-solid,#2da44e)}
.wb-card-lane-dot[data-visual=current][data-state=waiting]{background:var(--dsw-derive-warn-border,#d4a72c)}
.wb-card-lane-dot[data-visual=current][data-state=blocked]{background:var(--dsw-derive-danger,#cf222e)}
.wb-card-lane-dot[data-visual=current][data-state=failed]{background:var(--dsw-derive-danger-solid,#d1242f)}
.wb-card-lane-dot[data-visual=current][data-state=active]{background:var(--dsw-derive-accent,#0969da)}
/* 行卡动作位（右侧）：衍生动作（去签字/看原因）+ 管理动作 */
.wb-card-ops{display:flex;gap:6px;align-items:center;flex:none;margin-left:auto}
.wb-card-btn{font-size:12px;padding:2px 10px;border-radius:6px;border:1px solid var(--dsw-derive-border,#d0d7de);
  background:var(--dsw-derive-canvas,#fff);color:var(--dsw-derive-fg,#1f2328);cursor:pointer;white-space:nowrap}
.wb-card-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-card-btn-primary{background:var(--dsw-derive-accent-solid,#1f6feb);border-color:var(--dsw-derive-accent-solid,#1f6feb);color:var(--dsw-derive-on-solid,#fff);font-weight:600}
.wb-card-btn-blue{border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-ink-blue,#0550ae);background:var(--dsw-derive-accent-bg,#ddf4ff)}/* t260929-22 gen9：View Reason 4.38→深蓝墨 */
.wb-card-btn-danger{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-card-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
/* 收口折叠计数行 */
.wb-done-row{display:block;width:100%;text-align:left;font-size:12px;color:var(--dsw-derive-muted,#57606a);
  background:var(--dsw-derive-surface,#f6f8fa);border:1px dashed var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:6px 12px;
  margin:8px 0 6px;cursor:pointer}
.wb-done-row:hover{background:var(--dsw-derive-surface-2,#eef1f4)}
/* 旧台面表格样式已随 t260904-17 列表 v5（平铺行卡）退役——行卡/chips 样式族见上。 */
.wb-dot{width:10px;height:10px;border-radius:50%;display:inline-block;vertical-align:middle;flex:none}
.wb-dot[data-state=running]{background:var(--dsw-derive-success-solid,#2da44e)}
.wb-dot[data-state=awaiting]{background:var(--dsw-derive-warn,#bf8700)}
.wb-dot[data-state=awaiting-human]{background:var(--dsw-derive-accent,#1f6feb)}
.wb-dot[data-state=blocked]{background:var(--dsw-derive-danger-solid,#d1242f)}
.wb-dot[data-state=done]{background:var(--dsw-derive-muted,#6e7781)}
.wb-td-id{white-space:nowrap}
.wb-td-id .wb-id{display:block;color:var(--dsw-derive-accent,#0969da);font-weight:600;white-space:nowrap}
.wb-td-role{color:var(--dsw-derive-fg,#1f2328);white-space:nowrap;width:76px}
.wb-type-chip{font-size:12px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;
  padding:1px 8px;white-space:nowrap}
.wb-type-chip[data-empty=true]{color:var(--dsw-derive-muted,#8c959f)}
.wb-td-step{color:var(--dsw-derive-muted,#57606a);white-space:nowrap;width:150px}
.wb-td-desc{width:100%}
.wb-td-desc .wb-desc{display:block;color:var(--dsw-derive-fg,#1f2328);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wb-row-pending{display:block;color:var(--dsw-derive-danger,#cf222e);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wb-td-state{white-space:nowrap;width:130px}
.wb-state-text{font-size:13px;margin-left:6px;color:var(--dsw-derive-muted,#57606a)}
.wb-state-text[data-state=awaiting-human]{color:var(--dsw-derive-accent,#0969da);font-weight:600}
.wb-state-text[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e)}
.wb-state-text[data-state=running]{color:var(--dsw-derive-success,#1a7f37)}
.wb-state-text[data-state=done]{color:var(--dsw-derive-muted,#6e7781)}
.wb-td-time{color:var(--dsw-derive-muted,#57606a);white-space:nowrap;width:104px}
.wb-td-ops{white-space:nowrap;width:250px;text-align:right}
.wb-row-ops{display:inline-flex;gap:6px}
.wb-row-btn{font:inherit;font-size:12px;padding:3px 10px;border-radius:6px;cursor:pointer;
  border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-fg,#1f2328);white-space:nowrap;transition:background .12s}
.wb-row-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-row-btn:disabled{cursor:default;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa)}
.wb-row-btn-primary{border-color:var(--dsw-derive-accent-solid,#1f6feb);background:var(--dsw-derive-accent-solid,#1f6feb);color:var(--dsw-derive-on-solid,#fff);font-weight:600}
.wb-row-btn-primary:hover{background:var(--dsw-derive-accent,#0857b6)}
.wb-row-btn-danger{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-row-btn-blue{border-color:var(--dsw-derive-accent-border,#96c8f2);color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-row-btn-green{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success,#1a7f37);background:var(--dsw-derive-success-bg,#dafbe1)}
/* 详情抽屉徽章（浅底深字，现代状态色） */
.wb-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:500}
.wb-badge[data-state=running]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-badge[data-state=awaiting]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-badge[data-state=awaiting-human]{background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-badge[data-state=blocked]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-badge[data-state=done]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a)}
.wb-badge[data-kind=status]{background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
/* 详情抽屉：absolute 限定在中列视图区内（260824 起不再做全窗 fixed 覆盖——
   定位祖先 = sidebar.tsx 的 .wb-sb-right（position:relative），铺满中列。 */
.wb-drawer{position:absolute;top:0;right:0;bottom:0;left:0;background:var(--dsw-derive-canvas,#ffffff);z-index:90;
  border-left:1px solid var(--dsw-derive-border,#d0d7de);box-shadow:-12px 0 32px rgba(31,35,40,.18);overflow-y:auto;padding:18px 22px 40px;
  display:flex;flex-direction:column;gap:14px;font-size:13px;color:var(--dsw-derive-fg,#1f2328)}
/* UI-3 (t261005-04): the drawer becomes a middle-column overlay — a 12px gap on
   all sides lets the underlying view show through; closing restores it exactly
   (design 261004 §7.5.1). Still absolute inside .wb-sb-right; the left and right
   columns stay usable throughout (the right-column chat is never touched). The
   overlay is always exactly one layer deep (content replacement, no stacking). */
.wb-drawer.wb-overlay{top:12px;right:12px;bottom:12px;left:12px;
  border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:10px;
  box-shadow:0 12px 40px rgba(31,35,40,.35)}
/* Breadcrumb (epic drill walk-back): a '← code' button at the head's left; same layer, content swap, no stacking. */
.wb-overlay-crumb{flex:none;font:inherit;font-size:12px;border:1px solid var(--dsw-derive-border,#d0d7de);
  background:transparent;color:var(--dsw-derive-accent,#0969da);border-radius:6px;padding:2px 8px;cursor:pointer;white-space:nowrap}
.wb-overlay-crumb:hover{background:var(--dsw-derive-surface,#f6f8fa)}
/* Spec block (t261005-04): execution spec card + acceptance checklist + write-set chips + collapsed verbatim original request. */
.wb-spec-block{display:flex;flex-direction:column;gap:8px}
.wb-spec-block .ttl{font-size:11px;font-weight:700;color:var(--dsw-derive-muted,#57606a);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px}
.wb-spec-acc ul{margin:0;padding-left:18px;font-size:12.5px;line-height:1.7}
.wb-spec-ws .chips{display:flex;flex-wrap:wrap;gap:4px}
.wb-spec-ws .ws-chip{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;padding:1px 6px;border-radius:4px;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
.wb-spec-redline{font-size:12px;color:var(--dsw-derive-danger,#cf222e)}
.wb-spec-orig summary{cursor:pointer;font-size:11px;color:var(--dsw-derive-muted,#57606a)}
.wb-spec-orig summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-spec-orig pre{white-space:pre-wrap;word-break:break-word;font-size:11.5px;color:var(--dsw-derive-muted,#57606a);
  border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;padding:8px 10px;max-height:220px;overflow:auto;margin:6px 0 0}
/* Overlay epic content (same-layer content swap, t261005-04): embeds the existing EpicSection inside a padded wrapper. */
.wb-overlay-epic{border-top:1px solid var(--dsw-derive-border,#d0d7de);padding-top:12px}
.wb-overlay-epic-empty{font-size:12.5px;color:var(--dsw-derive-muted,#57606a)}
/* flex 列布局里子元素默认可缩——带 overflow 的卡（正文 max-height+scroll）会被压到不足一行
   （260824 实测塌陷）；抽屉自己滚，子元素一律不缩。 */
.wb-drawer>*{flex-shrink:0}
.wb-drawer-head{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de);padding-bottom:10px}
.wb-d2-blocked{margin:8px 0;padding:6px 12px;border:1px solid var(--dsw-derive-danger,#cf222e);border-radius:6px;
  background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e);font-size:12.5px}
/* KI-048（t260911-05）人话状态卡：红调=blocked / 黄调=其它态带受阻面；主题令牌派生。 */
.wb-status-card{margin:8px 0;padding:10px 12px;border:1px solid var(--dsw-derive-danger,#cf222e);border-left:4px solid var(--dsw-derive-danger,#cf222e);border-radius:8px;background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-status-card[data-sev=amber]{border-color:var(--dsw-derive-warn,#bf8700);border-left-color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5)}
.wb-status-card .sc-head{font-size:13px;font-weight:700;line-height:1.6;color:var(--dsw-derive-danger,#cf222e)}
.wb-status-card[data-sev=amber] .sc-head{color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-status-card .sc-files{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0 0}
.wb-status-card .sc-file{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;padding:1px 6px;border-radius:4px;background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-danger,#cf222e)}
.wb-status-card .sc-file-more{font-size:11px;color:var(--dsw-derive-muted,#8c959f);align-self:center}
.wb-status-card .sc-next{margin-top:6px;font-size:12px;line-height:1.6;color:var(--dsw-derive-danger,#7d2222)}
/* t260921-03：终态收口事实行（已结束+结束方式+异常原因+缺了什么）——黄调系、
 * 等宽弱化为普通行重；data-terminal 在卡上供渲染断言/样式作用域。 */
.wb-status-card[data-terminal] .sc-head{color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-status-card[data-terminal] .sc-next{color:var(--dsw-derive-warn-deep,#5a4500)}
.wb-status-card .sc-fact{margin-top:5px;font-size:11.5px;line-height:1.7;color:var(--dsw-derive-warn-deep,#7d4e00);word-break:break-all}
.wb-status-card[data-sev=amber] .sc-next{color:var(--dsw-derive-warn-deep,#5a4500)}
.wb-status-card .sc-next b{font-weight:700}
.wb-status-card .sc-raw{margin-top:6px}
.wb-status-card .sc-raw>summary{cursor:pointer;font-size:11.5px;color:var(--dsw-derive-muted,#57606a)}
.wb-status-card .sc-raw[open]>summary{color:var(--dsw-derive-accent,#0969da)}
.wb-status-card .sc-raw pre{margin:4px 0 0;padding:6px 8px;font-size:11px;line-height:1.5;max-height:200px;overflow:auto;background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;white-space:pre-wrap;word-break:break-all}
/* t260915-05：状态卡蓝调（人门等你签）+「签什么」+ 词条缺失降级锚 */
.wb-status-card[data-sev=blue]{border-color:var(--dsw-derive-accent,#0969da);border-left-color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-status-card[data-sev=blue] .sc-head{color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-status-card[data-sev=blue] .sc-next{color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-status-card .sc-fallback{margin-top:4px;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-status-card .sc-signwhat{margin-top:8px;padding:6px 10px;background:var(--dsw-derive-canvas,#fff);border:1px dashed var(--dsw-derive-accent,#0969da);border-radius:6px}
.wb-status-card .sc-signwhat-ttl{font-size:12px;font-weight:700;color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-status-card .sc-signwhat ul{margin:4px 0 0;padding-left:18px}
.wb-status-card .sc-signwhat li{font-size:11.5px;line-height:1.7;word-break:break-all}
/* t260915-05：真泳道图（拓扑驱动）——节点/并行虚线框/人门虚线圈/轮次带/×N 徽章 */
.wb-lanemap{margin:10px 0 4px;padding:14px 10px;overflow-x:auto;background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;display:flex;align-items:stretch;gap:2px;min-height:96px}
.wb-lm-item{display:flex;align-items:center}
.wb-lm-item:not(:first-child)::before{content:'→';color:var(--dsw-derive-border,#d0d7de);margin:0 6px;font-size:14px}
.wb-lm-node{display:inline-flex;flex-direction:column;align-items:center;gap:3px;padding:4px 8px;border-radius:8px;min-width:72px}
.wb-lm-dot{width:26px;height:26px;border-radius:50%;border:2px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#fff);display:flex;align-items:center;justify-content:center;font-size:12px;font-style:normal}
.wb-lm-node[data-vis=done] .wb-lm-dot{border-color:var(--dsw-derive-success,#4ac26b);background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success,#1a7f37)}
.wb-lm-node[data-vis=running] .wb-lm-dot{border-color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent-deep,#0550ae);box-shadow:0 0 0 4px rgba(9,105,218,.12)}
/* t260916-04：当前受阻=实心红（既有强调收实底，反白 glyph），与「曾受阻=完成色+角标」区分 */
.wb-lm-node[data-vis=blocked] .wb-lm-dot{border-color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger,#cf222e);color:var(--dsw-derive-canvas,#fff)}
.wb-lm-node[data-vis=awaiting-human] .wb-lm-dot{border-color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
/* 人门=虚线圈（mock 屏③ callout E：人门站与机械站形状区分） */
.wb-lm-node[data-kind=human] .wb-lm-dot{border-style:dashed;border-color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5)}
/* 程序化闸=方点（kind 形状区分：agent 叙述/程序化闸/人门拍板） */
.wb-lm-node[data-kind=gate] .wb-lm-dot{border-radius:6px}
.wb-lm-name{font-size:11px;font-weight:600;color:var(--dsw-derive-fg,#1f2328);line-height:1.3;text-align:center;white-space:nowrap}
.wb-lm-opt{font-style:normal;font-size:9.5px;color:var(--dsw-derive-muted,#8c959f);border:1px dashed var(--dsw-derive-border,#d0d7de);border-radius:6px;padding:0 4px;margin-left:3px}
.wb-lm-badge{font-size:9.5px;color:var(--dsw-derive-warn-deep,#953800);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn,#d4a72c);border-radius:8px;padding:0 5px;margin-left:3px}
/* t260916-04：历史已解除受阻=完成色+「曾受阻」角标（黄点；hover 出经过，lane-map.tsx） */
.wb-lm-ever{font-style:normal;font-size:9.5px;color:var(--dsw-derive-warn-deep,#953800);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn,#d4a72c);border-radius:8px;padding:0 5px;margin-left:3px;cursor:default;white-space:nowrap}
.wb-lm-ever::before{content:'●';color:var(--dsw-derive-warn,#9a6700);margin-right:2px;font-size:8px;vertical-align:1px}
.wb-lm-rounds{display:flex;gap:3px;flex-wrap:wrap;justify-content:center}
.wb-lm-round{font-size:9px;color:var(--dsw-derive-muted,#57606a);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;padding:0 4px;cursor:default}
.wb-lm-round[data-state=done]{color:var(--dsw-derive-success,#1a7f37);border-color:var(--dsw-derive-success,#4ac26b);background:var(--dsw-derive-success-bg,#dafbe1)}
.wb-lm-round[data-state=running]{color:var(--dsw-derive-accent-deep,#0550ae);border-color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-lm-round[data-state=blocked]{color:var(--dsw-derive-danger,#cf222e);border-color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-lm-round[data-state=awaiting-human]{color:var(--dsw-derive-warn-deep,#7d4e00);border-color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5)}
.wb-lm-round[data-state=rework]{color:var(--dsw-derive-warn-deep,#953800);border-style:dashed;border-color:var(--dsw-derive-warn,#d4a72c)}
/* 并行组：虚线框 + 纵排多道（mock 屏① B：并行双道虚线框，图面单向流） */
.wb-lm-parallel{position:relative;display:inline-flex;flex-direction:column;justify-content:center;border:1.5px dashed var(--dsw-derive-border,#8c959f);border-radius:10px;background:rgba(140,149,159,.04);padding:14px 10px 8px;margin:0 4px}
.wb-lm-parallel[data-active=true]{border-color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-lm-plabel{position:absolute;top:-8px;left:10px;background:var(--dsw-derive-canvas,#fff);padding:0 6px;font-size:9.5px;color:var(--dsw-derive-muted,#57606a)}
.wb-lm-branches{display:flex;flex-direction:column;gap:2px}
.wb-lm-node-inlane{flex-direction:row;min-width:0;padding:2px 6px}
.wb-lm-node-inlane .wb-lm-dot{width:20px;height:20px;font-size:10px;flex:none}
.wb-lm-node-inlane .wb-lm-name{white-space:normal;text-align:left}
.wb-lm-node-inlane .wb-lm-rounds{display:none}
/* t260915-05：检查明细区（mock ① ck-rows） */
.wb-checks{margin:6px 0 10px}
.wb-checks-ttl{font-weight:600;font-size:12.5px;margin-bottom:6px;color:var(--dsw-derive-fg,#1f2328)}
.wb-ck-run{margin-bottom:8px}
.wb-ck-run-head{display:flex;gap:8px;align-items:baseline;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-ck-run-gen{font-size:11px;color:var(--dsw-derive-muted,#57606a)}
.wb-ck-run-verdict{font-size:11px;color:var(--dsw-derive-muted,#57606a);margin-left:auto}
.wb-ck-row{display:block;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;margin-top:4px;background:var(--dsw-derive-canvas,#fff);font-size:12px}
.wb-ck-row[data-green=false]{border-color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-ck-row>summary{display:flex;gap:8px;align-items:baseline;padding:5px 10px;cursor:pointer;list-style:none}
.wb-ck-mark{font-weight:700;width:16px;flex:none}
.wb-ck-mark.g{color:var(--dsw-derive-success,#116329)}
.wb-ck-mark.r{color:var(--dsw-derive-danger,#cf222e)}
.wb-ck-name{font-weight:600;flex:none}
.wb-ck-detail{color:var(--dsw-derive-muted,#57606a);font-size:11.5px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wb-ck-more{padding:4px 10px 8px;font-size:11.5px;color:var(--dsw-derive-muted,#57606a);border-top:1px dashed var(--dsw-derive-border,#d0d7de)}
.wb-ck-more pre{margin:4px 0 0;padding:6px 8px;font-size:11px;background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;white-space:pre-wrap;word-break:break-all;max-height:160px;overflow:auto}
.wb-drawer-id{font-size:12px;color:var(--dsw-derive-muted,#57606a);word-break:break-all}
/* 终态失败票详情面板（t260919-02）：红系结构件——色全部走 theme.ts 既有 danger
 * 令牌声明位（消费位 var() fallback，hex-clean/KI-055 家族纪律，零新增裸 hex）。 */
.wb-tf-panel{border:1px solid var(--dsw-derive-danger-border,#ff9b9b);border-radius:8px;
  background:var(--dsw-derive-danger-bg,#ffebe9);padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.wb-tf-head{display:flex;align-items:center;gap:8px}
.wb-tf-mark{font-size:16px}
.wb-tf-title{font-size:15px;font-weight:700;color:var(--dsw-derive-danger,#cf222e)}
.wb-tf-exec{font-size:11px;font-weight:700;font-family:ui-monospace,Menlo,monospace;color:var(--dsw-derive-danger,#cf222e);
  background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-danger-border,#ff9b9b);border-radius:10px;padding:1px 8px}
.wb-tf-receipt{font-size:12px;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;
  background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-danger-border,#ff9b9b);border-radius:6px;padding:6px 10px}
.wb-tf-k{font-size:11px;font-weight:600;color:var(--dsw-derive-danger,#cf222e)}
.wb-tf-reason-txt{font-size:13px;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;word-break:break-word}
.wb-tf-reason-txt.wb-tf-unavailable{color:var(--dsw-derive-muted,#57606a)}
.wb-tf-src{font-size:11px;color:var(--dsw-derive-muted,#57606a)}
.wb-tf-grid{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;align-items:baseline}
.wb-tf-grid .wb-tf-k{color:var(--dsw-derive-muted,#57606a)}
.wb-tf-v{font-size:12px;color:var(--dsw-derive-fg,#1f2328);word-break:break-all}
.wb-tf-snapshot{font-size:11px;color:var(--dsw-derive-muted,#57606a);border-top:1px dashed var(--dsw-derive-danger-border,#ff9b9b);padding-top:8px}
.wb-tf-honesty{font-size:11px;font-weight:600;color:var(--dsw-derive-danger,#cf222e)}
.wb-close{position:absolute;top:14px;right:16px;font-size:22px;color:var(--dsw-derive-muted,#57606a);cursor:pointer;background:none;border:none}
.wb-close:hover{color:var(--dsw-derive-fg,#1f2328)}
.wb-section{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);padding:12px 14px;display:flex;
  flex-direction:column;gap:8px}
.wb-section-title{font-size:14px;font-weight:600;color:var(--dsw-derive-fg,#1f2328);border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding-bottom:6px}
/* M14 详情五分组层次：编号徽标 + 子块分隔 + 基本信息网格 + 操作区高亮 */
.wb-section-num{font-size:11px;font-weight:700;color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff);border-radius:4px;
  padding:1px 6px;margin-right:8px;letter-spacing:.5px;vertical-align:1.5px}
.wb-section-desc{font-size:11px;color:var(--dsw-derive-muted,#8c959f);font-weight:400;margin-left:8px}
.wb-sub-sec{font-size:12px;font-weight:600;color:var(--dsw-derive-muted,#57606a);margin-top:10px;padding-top:8px;
  border-top:1px dashed var(--dsw-derive-surface-2,#e8ebef)}
.wb-section-title + .wb-sub-sec{border-top:none;margin-top:4px;padding-top:0}
.wb-meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:7px 18px}
.wb-meta-grid .wb-meta-item{display:flex;gap:6px;min-width:0;font-size:12px;color:var(--dsw-derive-fg,#1f2328);align-items:baseline}
.wb-meta-grid .wb-meta-item > .wb-meta-k{flex:none}
.wb-meta-grid .wb-meta-item > span:last-child:not(.wb-meta-k){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wb-section[data-kind=ops]{border-color:var(--dsw-derive-accent-border,#96c8f2);background:var(--dsw-derive-accent-bg,#fbfdff)}
.wb-meta-row{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-meta-k{color:var(--dsw-derive-muted,#8c959f)}
.wb-meta-link{color:var(--dsw-derive-accent,#0969da);text-decoration:none}
.wb-meta-link:hover{text-decoration:underline}
.wb-check{display:flex;flex-direction:column;gap:3px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:7px 2px}
.wb-check-line{display:flex;align-items:baseline;gap:8px}
.wb-check-item{flex:1;color:var(--dsw-derive-fg,#1f2328);line-height:1.6}
.wb-check-item[data-done=true]{color:var(--dsw-derive-muted,#6e7781);text-decoration:line-through;text-decoration-color:var(--dsw-derive-muted,#c0c6cc)}
.wb-check-by{font-size:10px;color:var(--dsw-derive-muted,#57606a)}
.wb-evidence{font-size:11px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border-radius:6px;padding:4px 8px;
  white-space:pre-wrap;word-break:break-word;margin:0}
/* ── t260831-08 详情抽屉「截图证据」区（wb-eimgs-*） ── */
.wb-eimgs{margin:10px 0 2px;border-top:1px solid var(--dsw-derive-surface-2,#e8ebef);padding-top:8px}
.wb-eimgs .ttl{font-size:11px;font-weight:600;color:var(--dsw-derive-muted,#57606a);margin-bottom:6px}
.wb-eimgs-grid{display:flex;flex-wrap:wrap;gap:10px}
.wb-eimgs-item{margin:0;max-width:280px}
.wb-eimgs-img{display:block;max-width:280px;max-height:200px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;
  background:var(--dsw-derive-canvas,#fff);object-fit:contain}
.wb-eimgs-item figcaption{font-size:10px;color:var(--dsw-derive-muted,#8c959f);margin-top:3px;word-break:break-all}
.wb-eimgs-miss{font-size:11px;color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9);border-radius:6px;padding:6px 8px}
/* ── t260901-13 截图证据看图灯箱（wb-lb-*）──
 * 参照 wb-modal 取舍：带 inset:0 fixed + flex 居中（同款全屏遮罩语义）；
 * 不带 wb-modal-box 白底卡片/86vh 上限（灯箱主体是大图，非表单容器）。
 * 背景 .8（wb-modal .5 下透出抽屉内容干扰看图）。z-index 120：显式压过
 * 抽屉（90）与通用弹窗（99），灯箱开着时键盘/点击语义独占，不靠 DOM 顺序。 */
.wb-eimgs-item{cursor:zoom-in}
.wb-lb{position:fixed;inset:0;background:rgba(31,35,40,.8);z-index:120;display:flex;
  flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:20px}
.wb-lb-img{max-width:90vw;max-height:80vh;border-radius:8px;background:var(--dsw-derive-canvas,#fff);object-fit:contain;
  box-shadow:0 8px 32px rgba(0,0,0,.5)}
.wb-lb-miss{font-size:13px;color:var(--dsw-derive-danger,#cf222e);background:var(--dsw-derive-danger-bg,#ffebe9);border-radius:8px;padding:10px 16px}
.wb-lb-bar{display:flex;align-items:center;gap:12px;font-size:12px;color:var(--dsw-derive-dark-fg,#f0f3f6);user-select:none}
.wb-lb-nav{font:inherit;font-size:20px;line-height:1;width:36px;height:36px;border-radius:50%;
  border:1px solid rgba(240,243,246,.4);background:rgba(240,243,246,.12);color:var(--dsw-derive-dark-fg,#f0f3f6);
  cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .12s}
.wb-lb-nav:hover{background:rgba(240,243,246,.25)}
.wb-lb-close{font:inherit;font-size:14px;padding:4px 12px;border-radius:6px;cursor:pointer;
  border:1px solid rgba(240,243,246,.4);background:transparent;color:var(--dsw-derive-dark-fg,#f0f3f6)}
.wb-lb-close:hover{background:rgba(240,243,246,.15)}
.wb-lb-name{max-width:50vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;word-break:break-all}
.wb-ev-input{font:inherit;font-size:13px;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;padding:5px 8px;width:100%;box-sizing:border-box}
.wb-ev-input:focus{outline:none;border-color:var(--dsw-derive-accent,#0969da);box-shadow:0 0 0 3px rgba(9,105,218,.15)}
.wb-hl{font-size:12px;color:var(--dsw-derive-fg,#1f2328);display:flex;flex-direction:column;gap:5px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);
  padding:7px 2px}
.wb-hl-stage{color:var(--dsw-derive-accent,#0969da);font-weight:600}
.wb-log{font-size:11px;color:var(--dsw-derive-muted,#57606a);display:flex;gap:8px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:4px 2px;
  align-items:baseline}
.wb-log-time{color:var(--dsw-derive-muted,#8c959f);flex:none}
.wb-log-note{word-break:break-word}
.wb-ops{display:flex;gap:8px;flex-wrap:wrap}
.wb-modal{position:fixed;inset:0;background:rgba(31,35,40,.5);z-index:99;display:flex;align-items:center;
  justify-content:center;padding:24px}
.wb-modal-box{background:var(--dsw-derive-canvas,#ffffff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:10px;box-shadow:0 8px 32px rgba(31,35,40,.2);
  max-width:760px;width:100%;max-height:86vh;display:flex;flex-direction:column;gap:10px;padding:18px 20px}
.wb-modal-title{font-size:15px;font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-modal-body{overflow-y:auto;display:flex;flex-direction:column;gap:10px}
.wb-prompt{font:12px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-derive-fg,#1f2328);background:var(--dsw-derive-surface,#f6f8fa);
  border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;padding:12px;margin:0;white-space:pre-wrap;word-break:break-word;
  max-height:52vh;overflow-y:auto}
.wb-empty{font-size:12px;color:var(--dsw-derive-muted,#57606a);padding:12px 0}
.wb-copied{font-size:11px;color:var(--dsw-derive-success,#1a7f37)}
.wb-pending{border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:5px 2px;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-body-pre{font-size:12px;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;word-break:break-word;background:var(--dsw-derive-surface,#f6f8fa);
  border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;padding:10px;margin:0;max-height:200px;overflow-y:auto}
.wb-chip{font-size:11px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;padding:1px 6px}
/* 内容预览（审批前过目） */
.wb-preview-box{max-width:860px}
.wb-preview-notice{font-size:12px;color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:5px 10px}
.wb-preview-ch{border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);padding:8px 2px 12px}
.wb-preview-ch-title{font-size:15px;font-weight:600;color:var(--dsw-derive-fg,#1f2328);margin-bottom:6px}
.wb-preview-para{font-size:13px;line-height:1.9;color:var(--dsw-derive-fg,#1f2328);margin:0 0 8px;white-space:pre-wrap}
/* 分页条（260824 用户拍板⑥）。 */
.wb-pager{display:flex;align-items:center;gap:10px;justify-content:flex-end;padding:8px 0}
/* ── M9 变更页签（PR 式审批台；制式照 knowledge block diff，类名 wb-d-* 独立自带不依赖 knowledge CSS） ── */
/* t261008-07 single-column detail (mock v11 ticketView): action row, decision
   card, two-column block, collapsed folds. Theme rides the derive tokens, so
   light and dark are both covered by the token layer (dual-theme captures). */
.wb-detail-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0 0}
.wb-decide{display:flex;flex-direction:column;gap:2px;margin:10px 0 0;padding:8px 12px;border-radius:8px;
  border:1px solid var(--dsw-derive-accent-border,#54aeff);background:var(--dsw-derive-accent-bg,#ddf4ff);
  font-size:12.5px;color:var(--dsw-derive-accent-deep,#0a3069)}
.wb-decide b{font-size:13px}
.wb-detail-two{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0 0}
@media (max-width:720px){.wb-detail-two{grid-template-columns:1fr}}
.wb-detail-col{display:flex;flex-direction:column;gap:12px;min-width:0}
.wb-panelbox{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:8px 12px;background:var(--dsw-derive-canvas,#ffffff)}
.wb-panelbox .ttl{font-size:12px;font-weight:600;color:var(--dsw-derive-muted,#57606a);margin-bottom:5px}
.wb-tl{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px;font-size:12px}
.wb-tl li{display:flex;gap:8px;align-items:baseline}
.wb-tl .at{flex:none;color:var(--dsw-derive-muted,#8c959f);font-variant-numeric:tabular-nums}
.wb-kv2{display:flex;flex-direction:column;gap:3px;font-size:12px}
.wb-kv2-pair{display:flex;gap:10px}
.wb-kv2-pair .k{flex:none;min-width:76px;color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-req-lite{display:flex;gap:8px;align-items:baseline;font-size:12px;padding:2px 0}
.wb-req-lite code{flex:none;color:var(--dsw-derive-accent,#0969da)}
.wb-dfold{margin:12px 0 0;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px}
.wb-dfold>summary{cursor:pointer;font:inherit;font-size:13px;padding:7px 12px;color:var(--dsw-derive-muted,#57606a)}
.wb-dfold[open]>summary{border-bottom:1px solid var(--dsw-derive-border,#d0d7de)}
.wb-dfold>summary:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-dtabs{display:flex;gap:2px;border-bottom:1px solid var(--dsw-derive-border,#d0d7de)}
.wb-dtab{font:inherit;font-size:13px;padding:7px 16px;border:none;background:none;color:var(--dsw-derive-muted,#57606a);cursor:pointer;
  border-bottom:2px solid transparent}
.wb-dtab[data-on=true]{color:var(--dsw-derive-accent,#0969da);font-weight:600;border-bottom-color:var(--dsw-derive-accent,#0969da)}
.wb-d-sum{font-size:12px;color:var(--dsw-derive-muted,#57606a);display:flex;gap:14px;flex-wrap:wrap}
.wb-d-file{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);overflow:hidden}
/* 多仓票逐仓分组（t260911-01 2a）：仓头条 + 组内文件列表 */
.wb-d-repo{margin:10px 0}
.wb-d-repohead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:6px 2px;font-size:12px;
  color:var(--dsw-derive-muted,#57606a);border-bottom:1px dashed var(--dsw-derive-border,#d0d7de);margin-bottom:6px}
.wb-d-fhead{display:flex;align-items:center;gap:8px;padding:7px 12px;background:var(--dsw-derive-surface,#f6f8fa);
  border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);flex-wrap:wrap}
.wb-d-fpath{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--dsw-derive-fg,#1f2328);
  font-weight:600;word-break:break-all}
.wb-d-block{border-top:1px solid var(--dsw-derive-surface-2,#e8ebef)}
.wb-d-bhead{display:flex;align-items:center;gap:8px;padding:5px 12px;background:var(--dsw-derive-surface,#fbfcfd);flex-wrap:wrap}
.wb-d-badge{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:600;white-space:nowrap}
.wb-d-badge[data-s=added]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-d-badge[data-s=removed]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-badge[data-s=modified]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-d-badge[data-s=unchanged]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a)}
.wb-d-badge[data-s=expired]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#8c959f);border:1px dashed var(--dsw-derive-border,#d0d7de)}
.wb-d-type{font-size:11px;color:var(--dsw-derive-muted,#8c959f);border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;padding:0 6px;white-space:nowrap}
.wb-d-md{padding:6px 14px;font-size:13px}
.wb-d-md-add{background:var(--dsw-derive-success-bg,#f0fff4);border-left:4px solid var(--dsw-derive-success-solid,#2da44e)}
.wb-d-md-del{background:var(--dsw-derive-danger-bg,#fff5f5);border-left:4px solid var(--dsw-derive-danger,#cf222e)}
.wb-d-md-old{background:var(--dsw-derive-danger-bg,#fff5f5);border-left:4px solid var(--dsw-derive-danger-border,#ff9b9b);border-bottom:1px dashed var(--dsw-derive-surface-2,#e8ebef)}
.wb-d-md-new{background:var(--dsw-derive-success-bg,#f0fff4);border-left:4px solid var(--dsw-derive-success-border,#7dd9a0)}
.wb-d-md-tag{font-size:11px;font-weight:600;color:var(--dsw-derive-muted,#57606a);letter-spacing:1px}
.wb-d-md-old .wb-d-md-tag{color:var(--dsw-derive-danger,#cf222e)}
.wb-d-md-new .wb-d-md-tag{color:var(--dsw-derive-success-deep,#116329)}
/* 渲染态 markdown 的最小样式（wb-md 作用域，对齐 knowledge kb-md） */
.wb-md h1,.wb-md h2,.wb-md h3,.wb-md h4,.wb-md h5,.wb-md h6{margin:6px 0;font-size:14px;color:var(--dsw-derive-fg,#1f2328)}
.wb-md p{margin:4px 0;line-height:1.7}
.wb-md code{background:var(--dsw-derive-surface-2,#eff1f3);border-radius:4px;padding:0 4px;font-size:12px}
.wb-md pre{background:var(--dsw-derive-surface,#f6f8fa);border-radius:6px;padding:8px 10px;overflow-x:auto;margin:4px 0}
.wb-md pre code{background:none;padding:0}
/* knowledge 出厂件收编（t260907-08）：knowledge 全局 CSS 的 .md-code/.md-cl/.md-copy/
 * .tok-* 固定浅档色不随平台翻——四象限 new-dark 格实锤 epics 详情围栏代码块
 * fg 写死浅档字色 on 派生深底 1.08:1（宿主症状②同族）。knowledge 全局 CSS 与 .wb-md
 * 同特异性且后注入会压过平级规则，故此处全部升一级特异性收编：底=派生 surface（随档翻），
 * 字=派生 fg，语法高亮映到派生语义令牌（fallback=knowledge 原浅档值，浅档视觉不变）。 */
.wb-md .md-code{background:var(--dsw-derive-surface,#f6f8fa);border-color:var(--dsw-derive-border,#d0d7de)}
.wb-md .md-code pre code{color:var(--dsw-derive-fg,#1f2328)}
.wb-md .md-cl{color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface-2,#eaeef2)}
.wb-md .md-copy{border-color:var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#ffffff);color:var(--dsw-derive-muted,#57606a)}
.wb-md .md-copy:hover{background:var(--dsw-derive-surface-2,#eaeef2);color:var(--dsw-derive-fg,#1f2328)}
.wb-md .tok-c{color:var(--dsw-derive-muted,#6e7781)}
.wb-md .tok-s{color:var(--dsw-derive-accent,#0969da)}
.wb-md .tok-k{color:var(--dsw-derive-danger,#cf222e)}
.wb-md .tok-n{color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-md .tok-v{color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-md blockquote{margin:4px 0;padding:2px 10px;border-left:3px solid var(--dsw-derive-border,#d0d7de);color:var(--dsw-derive-muted,#57606a)}
.wb-md table{border-collapse:collapse;margin:4px 0}
.wb-md table th,.wb-md table td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:3px 10px;text-align:left;font-size:12px}
.wb-md ul,.wb-md ol{margin:4px 0;padding-left:22px}
.wb-md hr{border:none;border-top:1px solid var(--dsw-derive-border,#d8dee4);margin:8px 0}
/* unified diff（代码文件） */
.wb-d-uni{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.55;
  padding:6px 0;overflow-x:auto}
.wb-d-line{padding:0 12px;white-space:pre-wrap;word-break:break-all}
.wb-d-line[data-k=add]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-d-line[data-k=del]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-line[data-k=hunk]{color:var(--dsw-derive-accent,#0969da);background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-d-line[data-k=meta]{color:var(--dsw-derive-muted,#8c959f)}
/* 数据对账表 */
.wb-d-recon{border-collapse:collapse;margin:6px 12px;font-size:12px;max-width:calc(100% - 24px);display:block;overflow-x:auto}
.wb-d-recon th,.wb-d-recon td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:4px 10px;text-align:left;
  vertical-align:top;white-space:pre-wrap;word-break:break-word}
.wb-d-recon th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-d-recon td[data-k=path]{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.wb-d-old{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-new{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
/* 表格行单元格级对齐 */
.wb-d-cells{border-collapse:collapse;margin:6px 12px;font-size:12px;max-width:calc(100% - 24px);display:block;overflow-x:auto}
.wb-d-cells th,.wb-d-cells td{border:1px solid var(--dsw-derive-border,#d0d7de);padding:4px 10px;text-align:left;white-space:pre-wrap;word-break:break-word}
.wb-d-cells th{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-d-cell-old{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e);text-decoration:line-through}
.wb-d-cell-new{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329);font-weight:600}
/* 意见动作条 */
.wb-d-actions{display:flex;gap:8px;align-items:center;padding:6px 12px;border-top:1px dashed var(--dsw-derive-surface-2,#e8ebef);flex-wrap:wrap}
.wb-d-btn{font-size:12px;padding:2px 12px;border-radius:6px;cursor:pointer;border:1px solid var(--dsw-derive-border,#d0d7de);background:var(--dsw-derive-canvas,#fff);color:var(--dsw-derive-fg,#1f2328)}
.wb-d-btn:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-d-btn-ap{border-color:var(--dsw-derive-success-border,#7dd9a0);color:var(--dsw-derive-success-deep,#116329)}
.wb-d-btn-ap.on{background:var(--dsw-derive-success-deep,#116329);color:var(--dsw-derive-canvas,#fff)}
.wb-d-btn-rj{border-color:var(--dsw-derive-danger-border,#ff9b9b);color:var(--dsw-derive-danger,#cf222e)}
.wb-d-btn-rj.on{background:var(--dsw-derive-danger,#cf222e);color:var(--dsw-derive-canvas,#fff)}
.wb-d-cmt{width:100%;min-height:44px;font:inherit;font-size:12px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;
  padding:6px 10px;box-sizing:border-box}
.wb-d-expired{border:1px dashed var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:8px 12px;color:var(--dsw-derive-muted,#57606a);font-size:12px}
.wb-d-expired-item{padding:4px 0;border-bottom:1px solid var(--dsw-derive-border,#f0f2f5)}
.wb-d-expired-item:last-child{border-bottom:none}
.wb-d-conclude{font:inherit;font-size:12px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;padding:3px 8px;background:var(--dsw-derive-canvas,#fff)}
.wb-d-rework{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-surface,#fbfcfd);padding:10px 14px;
  display:flex;flex-direction:column;gap:8px}
.wb-d-rework pre{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  line-height:1.6;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow:auto}
.wb-d-trunc{font-size:11px;color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);border-radius:6px;
  padding:3px 10px;margin:4px 12px}
/* ── M12 agent 日志（wb-al-*：详情抽屉「Agent」页签） ── */
.wb-al-meta{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-muted,#57606a);align-items:center}
.wb-al-file{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);overflow:hidden}
.wb-al-fhead{display:flex;align-items:center;gap:8px;padding:6px 12px;background:var(--dsw-derive-surface,#f6f8fa);
  border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef);cursor:pointer;flex-wrap:wrap}
.wb-al-fhead:hover{background:var(--dsw-derive-surface-2,#eef1f4)}
.wb-al-fname{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--dsw-derive-fg,#1f2328);
  font-weight:600;word-break:break-all}
.wb-al-fmeta{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-al-body{max-height:420px;overflow:auto;background:var(--dsw-derive-surface,#fbfcfd)}
.wb-al-pre{font:11px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dsw-derive-fg,#1f2328);
  white-space:pre-wrap;word-break:break-word;padding:10px 12px;margin:0}
.wb-al-trunc{font-size:11px;color:var(--dsw-derive-warn,#bf8700);background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#eac54f);
  border-radius:6px;padding:3px 10px;margin:8px 12px}
.wb-al-result-sum{display:flex;gap:6px 14px;flex-wrap:wrap;font-size:12px;color:var(--dsw-derive-fg,#1f2328);
  padding:8px 12px 0}
.wb-al-result-key{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-al-status{font-size:11px;border-radius:6px;padding:1px 8px;font-weight:600}
.wb-al-status[data-ok=true]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
.wb-al-status[data-ok=false]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-al-summ{font-size:12px;color:var(--dsw-derive-fg,#1f2328);padding:6px 12px 8px;line-height:1.6}
.wb-al-deliverable{font-size:11px;color:var(--dsw-derive-muted,#57606a)}
/* ── t260825-03 运行脉搏行（wb-pulse）+ 实时动态面板（wb-live） ── */
.wb-pulse{margin:6px 0 0;font-size:12px;line-height:1.6;padding:5px 12px;border-radius:6px;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);color:var(--dsw-derive-muted,#57606a)}
.wb-pulse[data-s=ok]{background:var(--dsw-derive-success-bg,#f0fdf4);border-color:var(--dsw-derive-success-border,#bbf7d0);color:var(--dsw-derive-success-deep,#116329)}
.wb-pulse[data-s=warn]{background:var(--dsw-derive-warn-bg,#fff8e6);border-color:var(--dsw-derive-warn-border,#eac54f);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-pulse[data-s=stuck]{background:var(--dsw-derive-danger-bg,#fff0f0);border-color:var(--dsw-derive-danger-border,#ffb3ad);color:var(--dsw-derive-danger,#cf222e);font-weight:600}
.wb-pulse .wb-pulse-k{color:var(--dsw-derive-muted,#8c959f);margin-right:2px}
.wb-live{margin:6px 0 0;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff);overflow:hidden}
.wb-live-head{display:flex;align-items:center;gap:10px;padding:6px 12px;font-size:12px;
  color:var(--dsw-derive-muted,#57606a);cursor:pointer;user-select:none}
.wb-live-head:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-live-head .wb-live-title{font-weight:600;color:var(--dsw-derive-fg,#1f2328)}
.wb-live-meta{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-live-body{border-top:1px solid var(--dsw-derive-surface-2,#e8ebef);max-height:320px;overflow:auto;padding:4px 0;background:var(--dsw-derive-surface,#fbfcfd)}
.wb-live-row{display:flex;gap:8px;padding:2px 12px;font-size:12px;align-items:baseline;line-height:1.7}
.wb-live-ts{flex:0 0 auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-live-type{flex:0 0 auto;font-size:10px;padding:0 6px;border-radius:4px;background:var(--dsw-derive-surface-2,#eef1f4);color:var(--dsw-derive-muted,#57606a)}
.wb-live-type[data-t=tool]{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success-deep,#116329)}
/* KI-024：轮次/重试行——比工具行更弱的信号，配色去饱和（蓝灰/橙灰），不加新色板 */
.wb-live-type[data-t=step]{background:var(--dsw-derive-surface-2,#eef1f4);color:var(--dsw-derive-muted,#57606a)}
.wb-live-type[data-t=retry]{background:var(--dsw-derive-warn-bg,#fff1e5);color:var(--dsw-derive-warn,#9a6700)}
.wb-live-type[data-t=assistant]{background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-live-type[data-t=user]{background:var(--dsw-derive-warn-bg,#fff1e5);color:var(--dsw-derive-warn-deep,#bc4c00)}
.wb-live-sum{color:var(--dsw-derive-fg,#1f2328);word-break:break-all}

/* ── 详情页 v2（260824 重设计：步骤条/一句话现状/操作条/问题区/阶段卡/深查折叠） ── */
/* v2.1（260824 二轮）：正文置顶卡 / id 内联 / 打回横幅 / 步进条圆点化 / 变更分组 / 日志按步分组 */
.wb-d2-id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--dsw-derive-muted,#8c959f);
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:4px;padding:1px 6px}
/* 步骤条：一步一圆点，色=状态（绿✓完成 蓝▶在跑 红✗卡住 黄✋等人 灰○未到）；
   完成判定按模板链序——当前步之前=done（merge_check 等脚本门不落 results 也能打勾） */
.wb-d2-steps{display:flex;align-items:center;flex-wrap:wrap;gap:0;row-gap:6px;margin:12px 0 4px;
  padding:10px 12px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff)}
.wb-d2-step{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--dsw-derive-muted,#8c959f);padding:3px 8px;border-radius:6px}
.wb-d2-par{font-weight:700;color:var(--dsw-derive-accent,#0969da);cursor:default}
.wb-d2-step .ico{font-style:normal;font-weight:700;width:18px;height:18px;border-radius:50%;
  display:inline-flex;align-items:center;justify-content:center;font-size:11px;flex:0 0 18px;
  background:var(--dsw-derive-surface-2,#e8ebef);color:var(--dsw-derive-muted,#8c959f)}
.wb-d2-step[data-s=done]{color:var(--dsw-derive-success,#1a7f37)}
.wb-d2-step[data-s=done] .ico{background:var(--dsw-derive-success-bg,#dafbe1);color:var(--dsw-derive-success,#1a7f37)}
.wb-d2-step[data-s=running]{color:var(--dsw-derive-accent-deep,#0550ae);font-weight:600;background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-d2-step[data-s=running] .ico{background:var(--dsw-derive-accent,#0969da);color:var(--dsw-derive-canvas,#fff)}
.wb-d2-step[data-s=blocked]{color:var(--dsw-derive-danger,#cf222e);font-weight:600;background:var(--dsw-derive-danger-bg,#ffebe9)}
.wb-d2-step[data-s=blocked] .ico{background:var(--dsw-derive-danger,#cf222e);color:var(--dsw-derive-canvas,#fff)}
.wb-d2-step[data-s=awaiting-human]{color:var(--dsw-derive-warn-deep,#7d4e00);font-weight:600;background:var(--dsw-derive-warn-bg,#fff8c5)}
.wb-d2-step[data-s=awaiting-human] .ico{background:var(--dsw-derive-warn,#bf8700);color:var(--dsw-derive-canvas,#fff)}
.wb-d2-link{flex:0 0 14px;height:1px;background:var(--dsw-derive-border,#d0d7de);margin:0 2px}
/* 一句话现状条 */
.wb-d2-status{margin:8px 0 0;font-size:13px;line-height:1.6;padding:7px 12px;border-radius:6px;
  background:var(--dsw-derive-surface,#f6f8fa);border:1px solid var(--dsw-derive-surface-2,#e8ebef);color:var(--dsw-derive-fg,#1f2328)}
.wb-d2-status[data-s=blocked]{background:var(--dsw-derive-danger-bg,#ffebe9);border-color:var(--dsw-derive-danger-border,#ffb3ad);color:var(--dsw-derive-danger,#cf222e)}
.wb-d2-status[data-s=awaiting-human]{background:var(--dsw-derive-warn-bg,#fff8c5);border-color:var(--dsw-derive-warn-border,#eac54f);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-d2-status[data-s=running]{background:var(--dsw-derive-accent-bg,#ddf4ff);border-color:var(--dsw-derive-accent-border,#9cd6ff);color:var(--dsw-derive-accent-deep,#0550ae)}
.wb-d2-status[data-s=done]{background:var(--dsw-derive-success-bg,#dafbe1);border-color:var(--dsw-derive-success-border,#7ddb8a);color:var(--dsw-derive-success-deep,#116329)}
/* 打回横幅：timeline 里 state=rework 的记录（何时/谁/理由/打回到哪步），有才渲染 */
.wb-d2-reworks{margin-top:10px;border:1px solid var(--dsw-derive-warn-border,#eac54f);border-left:4px solid var(--dsw-derive-warn,#bf8700);
  border-radius:6px;background:var(--dsw-derive-warn-bg,#fffdf2);padding:8px 12px}
.wb-d2-reworks .ttl{font-size:12px;font-weight:700;color:var(--dsw-derive-warn-deep,#7d4e00);margin-bottom:4px}
.wb-d2-reworks .row{font-size:12px;color:var(--dsw-derive-warn-deep,#5a4500);line-height:1.7;padding:1px 0}
.wb-d2-reworks .row .when{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;
  color:var(--dsw-derive-warn,#a08517);margin-right:6px}
.wb-d2-reworks .row .tgt{font-weight:600}
/* 操作条：钉在头部下方，主操作平铺、低频收「更多」 */
.wb-d2-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0 0;
  padding:8px 10px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;background:var(--dsw-derive-canvas,#ffffff);
  position:sticky;top:0;z-index:5}
.wb-d2-actions .wb-d2-hint{font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-d2-more{margin-left:auto}
.wb-d2-more>summary{cursor:pointer;font-size:12px;color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d2-more>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-more[open]>summary{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-more-body{display:flex;gap:8px;flex-wrap:wrap;padding-top:8px}
/* 问题区：只在有问题时渲染 */
.wb-d2-problems{margin-top:10px;border:1px solid var(--dsw-derive-danger-border,#ffb3ad);border-left:4px solid var(--dsw-derive-danger,#cf222e);
  border-radius:6px;background:var(--dsw-derive-danger-bg,#fff5f5);padding:8px 12px}
.wb-d2-problems .ttl{font-size:12px;font-weight:700;color:var(--dsw-derive-danger,#cf222e);margin-bottom:4px}
.wb-d2-problems .row{font-size:12px;color:var(--dsw-derive-danger,#7d2222);line-height:1.6;padding:1px 0}
.wb-d2-problems .row .dim{color:var(--dsw-derive-danger,#b06060)}
/* t261001-11：槽错误边界 fallback——崩了只在这一行点名故障，其余 UI 存活 */
.wb-sb-crashed{margin:8px 10px;padding:8px 10px;border:1px dashed var(--dsw-derive-danger-border,#ffb3ad);
  border-radius:6px;background:var(--dsw-derive-danger-bg,#fff5f5);font-size:12px;
  color:var(--dsw-derive-danger,#7d2222);word-break:break-word}
/* 工单正文（原始需求）：钉在详情最顶部，所有页签可见 */
.wb-d2-body{margin-top:10px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff);
  padding:10px 14px;font-size:13px;line-height:1.75;color:var(--dsw-derive-fg,#1f2328);white-space:pre-wrap;
  word-break:break-word;max-height:320px;overflow-y:auto}
.wb-d2-body .ttl{font-size:11px;color:var(--dsw-derive-muted,#8c959f);margin-bottom:4px;font-weight:600}
/* 执行规格卡（t260904-06）：钉在正文卡正下方，蓝左边条与正文卡做视觉区分（原始需求=用户说的，
   spec=开票会话蒸馏的执行规格）；B 形态=默认展开+限高滚动（样张 260904-spec-card-mockup B 卡）。
   样张已评审拍板进方案（impl 段无需回读样张；样式/文案/结构见下方三条规则）。 */
.wb-d2-spec{margin-top:10px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-left:4px solid var(--dsw-derive-accent,#0969da);border-radius:8px;background:var(--dsw-derive-canvas,#fff);
  padding:10px 14px;font-size:13px;line-height:1.75;color:var(--dsw-derive-fg,#1f2328);
  word-break:break-word;max-height:260px;overflow-y:auto}
.wb-d2-spec .txt{max-height:230px;overflow-y:auto}
.wb-d2-spec .txt :first-child{margin-top:0}
.wb-d2-spec .ttl{font-size:11px;color:var(--dsw-derive-muted,#57606a);margin-bottom:4px;font-weight:600;
  display:flex;align-items:baseline;gap:8px}
.wb-d2-spec .cnt{font-weight:400;color:var(--dsw-derive-muted,#8c959f);font-family:ui-monospace,Menlo,monospace;font-size:10px}
/* 阶段卡：进展主体 */
.wb-d2-stages{margin-top:10px;display:flex;flex-direction:column;gap:6px}
/* 执行主体徽标（t260828-01）：🤖⚙️👤 直接拼接，软降级「—」 */
.wb-parts{font-size:11px;letter-spacing:1px;color:var(--dsw-derive-muted,#57606a);white-space:nowrap}
/* token 行内数字（t260828-07）：头部合计与阶段行内数字，克制小字、数字进悬停有精确值 */
.wb-usage{font-size:11px;color:var(--dsw-derive-muted,#57606a);white-space:nowrap}
.wb-usage[data-s=none]{color:var(--dsw-derive-muted,#8c959f)}
.wb-stage-usage{font-size:11px;color:var(--dsw-derive-muted,#57606a);white-space:nowrap;margin-left:4px}
/* 节点耗时徽标（t260901-12）：颜色随视觉态（内联 style 取自 D2_COLOR），走秒用等宽数字防跳宽 */
.wb-stage-dur{font-size:11px;white-space:nowrap;margin-left:4px;font-variant-numeric:tabular-nums}
.wb-d2-card{border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;padding:8px 12px;background:var(--dsw-derive-canvas,#fff)}
.wb-d2-card[data-s=running]{border-color:var(--dsw-derive-accent-border,#9cd6ff);background:var(--dsw-derive-accent-bg,#f6fbff)}
.wb-d2-card[data-s=blocked]{border-color:var(--dsw-derive-danger-border,#ffb3ad);background:var(--dsw-derive-danger-bg,#fff8f7)}
.wb-d2-card[data-s=awaiting-human]{border-color:var(--dsw-derive-warn-border,#eac54f);background:var(--dsw-derive-warn-bg,#fffdf2)}
.wb-d2-card[data-s=todo]{opacity:.62}
.wb-d2-card .hd{display:flex;align-items:baseline;gap:8px;font-size:13px}
.wb-d2-card .hd .ico{font-style:normal;font-weight:700}
.wb-d2-card .hd .nm{font-weight:600}
.wb-d2-card .hd .meta{margin-left:auto;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-d2-card .sum{font-size:12px;color:var(--dsw-derive-fg,#1f2328);line-height:1.6;margin-top:3px;
  white-space:pre-wrap;word-break:break-word}
.wb-d2-card .wb-d2-report{margin-top:5px;padding:6px 10px;background:var(--dsw-derive-surface,#fbfcfd);
  border-left:3px solid var(--dsw-derive-border,#d8dee4);border-radius:0 6px 6px 0;font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-d2-card details{margin-top:4px}
.wb-d2-card details>summary{cursor:pointer;font-size:11px;color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d2-card details>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-card .ev{font-size:11px;color:var(--dsw-derive-muted,#57606a);background:var(--dsw-derive-surface,#f6f8fa);border-radius:4px;
  padding:6px 8px;margin-top:4px;white-space:pre-wrap;word-break:break-word;
  max-height:220px;overflow-y:auto}
/* 深查折叠区 */
.wb-d2-deep{margin-top:12px;border-top:1px solid var(--dsw-derive-surface-2,#e8ebef);padding-top:8px}
.wb-d2-deep>details{border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:6px;margin-bottom:6px;background:var(--dsw-derive-canvas,#fff)}
.wb-d2-deep>details>summary{cursor:pointer;padding:7px 12px;font-size:12px;font-weight:600;
  color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d2-deep>details>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d2-deep>details>summary::before{content:'▸ '}
.wb-d2-deep>details[open]>summary::before{content:'▾ '}
.wb-d2-deep>details>div{padding:0 12px 10px}
/* ── 快照要点（t260905-07：阶段时间线/最近交接/门与签字记录/工作流快照，ticket show 直读） ──
   （t260907-08：本段是 t260905-08 令牌化 sweep 的漏网点——写死浅档色在深色档不可读，全量归位派生令牌） */
.wb-dsnap-block{margin:6px 0}
.wb-dsnap-block>h4{margin:0 0 4px;font-size:11px;color:var(--dsw-derive-muted,#57606a);font-weight:600}
.wb-dsnap-row{display:flex;gap:8px;font-size:12px;line-height:1.7;flex-wrap:wrap}
.wb-dsnap-row .st{color:var(--dsw-derive-muted,#57606a);min-width:88px}
.wb-dsnap-row .at{color:var(--dsw-derive-muted,#8c959f);font-size:11px}
.wb-dsnap-row[data-untime=true] .at{color:var(--dsw-derive-danger,#cf222e)}
.wb-dsnap-chip{display:inline-block;padding:0 6px;border-radius:10px;font-size:11px;margin-right:4px}
.wb-dsnap-chip[data-kind=gate]{background:var(--dsw-derive-surface,#f6f8fa);color:var(--dsw-derive-muted,#57606a);border:1px solid var(--dsw-derive-border,#d0d7de)}
.wb-dsnap-chip[data-kind=signature]{background:var(--dsw-derive-accent-bg,#ddf4ff);color:var(--dsw-derive-accent,#0969da);border:1px solid var(--dsw-derive-accent-border,#96c8f2)}
.wb-dsnap-empty{font-size:12px;color:var(--dsw-derive-muted,#8c959f)}
/* 变更 tab：文件头 +/− 行数；构建产物（lib/ bundle）折叠组 */
.wb-d-stats{font-size:11px;margin-left:auto;white-space:nowrap}
.wb-d-stats .add{color:var(--dsw-derive-success,#1a7f37)}
.wb-d-stats .del{color:var(--dsw-derive-danger,#cf222e)}
.wb-d-gen{margin-top:10px;border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-surface,#f6f8fa)}
.wb-d-gen>summary{cursor:pointer;padding:8px 12px;font-size:12px;color:var(--dsw-derive-muted,#57606a);list-style:none}
.wb-d-gen>summary:hover{color:var(--dsw-derive-accent,#0969da)}
.wb-d-gen>summary::before{content:'▸ '}
.wb-d-gen[open]>summary::before{content:'▾ '}
.wb-d-gen .wb-d-gen-list{padding:0 12px 10px}
.wb-d-gen-row{display:flex;gap:8px;align-items:center;font-size:12px;padding:2px 0;color:var(--dsw-derive-muted,#57606a)}
.wb-d-gen-row .p{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;word-break:break-all}
/* Agent 日志 tab：按工作流步序的分组卡（每步一卡，内含 gen 尝试行） */
.wb-al-stage{border:1px solid var(--dsw-derive-surface-2,#e8ebef);border-radius:8px;background:var(--dsw-derive-canvas,#fff);overflow:hidden;margin-top:8px}
.wb-al-shead{display:flex;align-items:center;gap:8px;padding:7px 12px;background:var(--dsw-derive-surface,#f6f8fa);font-size:12.5px}
.wb-al-shead .nm{font-weight:600}
.wb-al-shead .ico{font-style:normal;font-weight:700}
.wb-al-shead .meta{margin-left:auto;font-size:11px;color:var(--dsw-derive-muted,#8c959f)}
.wb-al-attempt{border-top:1px solid var(--dsw-derive-surface-2,#eef1f4)}
.wb-al-attempt>summary{cursor:pointer;display:flex;align-items:center;gap:8px;padding:6px 12px;
  font-size:12px;color:var(--dsw-derive-fg,#1f2328);list-style:none}
.wb-al-attempt>summary::before{content:'▸ ';color:var(--dsw-derive-muted,#8c959f)}
.wb-al-attempt[open]>summary::before{content:'▾ '}
.wb-al-attempt>summary:hover{background:var(--dsw-derive-surface,#f6f8fa)}
.wb-al-attempt .sum{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:var(--dsw-derive-muted,#57606a);font-size:11.5px}
.wb-al-attempt .wb-al-body{border-top:1px solid var(--dsw-derive-surface-2,#eef1f4)}

/* ── 本票时刻只读查看器（t260915-17，mock 260904 标注 D：文件行=链接） ── */
/* button 化的文件行沿用原视觉 + 指针态（sc-file 原为 code；wb-d-fpath 原为 span） */
button.sc-file{cursor:pointer;text-align:left}
button.wb-d-flink{cursor:pointer;background:none;border:none;padding:0;font:inherit;color:inherit;text-align:left}
button.wb-d-flink:hover{color:var(--dsw-derive-accent,#0969da);text-decoration:underline}
/* 背景引用行组 */
.wb-refs{margin-top:8px}
.wb-refs .ttl{font-weight:600;font-size:12.5px;margin-bottom:4px;color:var(--dsw-derive-muted,#57606a)}
.wb-refs-files{display:flex;flex-wrap:wrap;gap:4px}
.wb-ref-file{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;padding:1px 6px;border-radius:4px;
  background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-border,#d0d7de);
  color:var(--dsw-derive-muted,#57606a);cursor:pointer;text-align:left}
.wb-ref-file:hover{color:var(--dsw-derive-accent,#0969da);border-color:var(--dsw-derive-accent-border,#54aeff)}
/* 查看器遮罩与面板（遮罩层先例=EvidenceLightbox/预览弹层） */
.wb-ttv-mask{position:fixed;inset:0;background:rgba(31,35,40,.55);z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px}
.wb-ttv{background:var(--dsw-derive-canvas,#fff);border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:10px;
  width:min(880px,100%);max-height:88vh;display:flex;flex-direction:column;overflow:hidden;
  box-shadow:0 8px 32px rgba(31,35,40,.25)}
.wb-ttv-head{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--dsw-derive-surface-2,#e8ebef)}
.wb-ttv-path{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;word-break:break-all;flex:1}
.wb-ttv-close{border:none;background:none;font-size:14px;cursor:pointer;color:var(--dsw-derive-muted,#57606a);padding:2px 6px}
.wb-ttv-close:hover{color:var(--dsw-derive-danger,#cf222e)}
/* 横幅（mock D 原话：🕰 本票时刻 · 只读 + 跳到当前版小链） */
.wb-ttv-banner{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:6px 14px;
  background:var(--dsw-derive-accent-bg,#ddf4ff);border-bottom:1px solid var(--dsw-derive-accent-border,#54aeff);
  font-size:12px;color:var(--dsw-derive-accent-deep,#0a3069)}
.wb-ttv-banner-text{font-weight:700}
.wb-ttv-banner-ver{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}
.wb-ttv-jump{border:1px solid var(--dsw-derive-accent-border,#54aeff);background:var(--dsw-derive-canvas,#fff);
  color:var(--dsw-derive-accent,#0969da);font-size:11px;padding:1px 8px;border-radius:10px;cursor:pointer;margin-left:auto}
.wb-ttv-jump:hover{background:var(--dsw-derive-accent-bg,#ddf4ff)}
/* 正文：.md 复用 docs 的 wb-doc-body 渲染约束；其余等宽纯文本 */
.wb-ttv-body{flex:1;overflow:auto;padding:14px;font-size:12.5px;line-height:1.7}
.wb-ttv-code{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;white-space:pre-wrap;word-break:break-all}
.wb-ttv-fail{padding:20px 14px;font-size:12.5px;color:var(--dsw-derive-danger,#cf222e);line-height:1.7}
.wb-ttv-fail-ttl{font-weight:700;margin-bottom:6px}
.wb-ttv-loading{padding:20px 14px;font-size:12.5px;color:var(--dsw-derive-muted,#57606a)}
.wb-ttv-trunc{padding:6px 14px;border-top:1px dashed var(--dsw-derive-border,#d0d7de);font-size:11.5px;color:var(--dsw-derive-warn-deep,#7d4e00)}
`;
const CSS_TAG_ID = "sandbar-workbench/WorkbenchSection.css";
if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(CSS_TAG_ID) + "]") === null) {
	const tag = document.createElement("style");
	tag.dataset.plugin = "sandbar-workbench";
	tag.dataset.pluginCss = CSS_TAG_ID;
	tag.textContent = CSS;
	document.head.appendChild(tag);
}
const API = "/sandbar-workbench/api/wf";
/** 统一拼 ?project=（host 侧工单列表必传；详情/健康/巡检等路由多带的 query 无害——按 path 匹配）。 */
function withProject(path) {
	const viewProject = getViewProject();
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
		body: JSON.stringify(body ?? {})
	})).json();
}
function shortSlug(worktree) {
	return worktree.split("/").pop() || worktree;
}
/** 操作者标识（本机管理台无登录）：LS 持久，首访生成 op-<随机>；accept 的 by 用它，审计落账。 */
const OPERATOR_KEY = "sandbar-workbench-operator-v1";
function operatorOf() {
	try {
		const old = localStorage.getItem(OPERATOR_KEY);
		if (old) return old;
		const id = "op-" + Math.random().toString(36).slice(2, 8);
		localStorage.setItem(OPERATOR_KEY, id);
		return id;
	} catch {
		return "op-local";
	}
}
/** 执行主体徽标（t260828-01，observability「执行主体可见」）：模版 STAGES 的 parts
*  静态声明按组合态直接拼接（🤖 agent / ⚙️ 脚本 / 👤 人），悬停一行说明；
*  无 parts 的旧数据软降级「—」，不报错。动态真源仍是 Temporal history，此处只呈现声明。 */
function PartsBadges({ parts }) {
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
		className: "wb-parts",
		title: partsTitle(parts),
		children: partsIcons(parts)
	});
}
function fmtTs(ts) {
	if (!ts) return "—";
	return (/* @__PURE__ */ new Date(ts * 1e3)).toLocaleString("zh-CN", { hour12: false });
}
/**
* 终态失败票详情面板（t260919-02）：终态回执 kind=terminal 时详情抽屉的唯一详情面
* ——「已失败 + 原因」结构化呈现，绝不出现空面板。
*
* 硬纪律（本组件契约，UT 源级钉死）：
*  - **零操作入口**：组件体内不得出现任何 onClick/apiPost/按钮语义——终态票不再
*    推进，set-stage/force/resume 一概不给（票面边界）；
*  - 诚实口径：视图模型（terminal-face.ts）缺什么显什么（「原因不可得」「最后已知
*    阶段不可得」「无快照及为何无」），绝不编造；「刷新无效」随面板常驻可见，
*    不只闪在操作提示条里。
*/
function TerminalFailurePanel({ view }) {
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-tf-panel",
		"data-testid": "terminal-failure-panel",
		"data-exec": view.execStatus,
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-tf-head",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-mark",
						children: "⛔"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-title",
						children: "Ticket ended in failure"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-exec",
						title: "Temporal execution status",
						children: view.execStatus
					})
				]
			}),
			view.receiptError !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-tf-receipt",
				children: view.receiptError
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-tf-reason",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-tf-k",
						children: "Failure reason"
					}),
					view.reasonAvailable ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-tf-reason-txt",
						children: view.reason
					}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-tf-reason-txt wb-tf-unavailable",
						children: ["Reason unavailable", view.reasonNote ? ` — ${view.reasonNote}` : ""]
					}),
					view.reasonAvailable && view.reasonNote !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-tf-src",
						children: view.reasonNote
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-tf-grid",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Ticket"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-v",
						children: view.ticketId || "unavailable"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Project"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-v",
						children: view.project || "—"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Epic"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-v",
						children: view.epic || "No epic"
					}),
					view.instanceId !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Inspection instance"
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-tf-v",
						children: [view.instanceId, view.period !== "" ? ` · Period ${view.period}` : ""]
					})] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Last known stage"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-v",
						children: view.lastStage !== "" ? view.lastStage : view.lastStageNote
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Started"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-v",
						children: view.startTimeTxt !== "" ? view.startTimeTxt : "unavailable"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-k",
						children: "Closed at"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-tf-v",
						children: view.closeTimeTxt !== "" ? view.closeTimeTxt : "unavailable"
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-tf-snapshot",
				children: view.snapshotNote
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-tf-honesty",
				children: "Closed tickets no longer advance; refreshing has no effect. This panel is read-only — no advance/retry entry."
			})
		]
	});
}
/** 阶段视觉态推导住在纯模块 lane-states.ts（零依赖，node 可裸 import 做行为测试）；
*  index.tsx 只做消费。推导口径（优先级/回退/畸形输入）见 lane-states.ts 头注。 */
function d2StageVisual(detail, stageId, order) {
	if (detail.status === "closed") return "done";
	return deriveStageStates(detail, order).states[stageId] ?? "todo";
}
const D2_ICON = {
	done: "✓",
	running: "▶",
	blocked: "✗",
	"awaiting-human": "✋",
	todo: "○"
};
/** 图标配色（Agent 日志分组卡头等非 .wb-d2-step 场景用，与步进条同口径）。 */
const D2_COLOR = {
	done: "var(--dsw-derive-success,#1a7f37)",
	running: "var(--dsw-derive-accent,#0969da)",
	blocked: "var(--dsw-derive-danger,#cf222e)",
	"awaiting-human": "var(--dsw-derive-warn,#9a6700)",
	todo: "var(--dsw-derive-muted,#8c959f)"
};
/** timeline 的 at 是 ISO 串（base.py _mark）；列表/横幅统一显 MM-DD HH:mm。 */
function fmtAt(iso) {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return iso;
	const p = (n) => String(n).padStart(2, "0");
	return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** 节点耗时（t260901-12，metrics M1b）：纯模块推导 + 1s 走秒。
*  起表条件=抽屉开（父组件随 selectedId 条件渲染整树卸载）且有活跃步或人等段在场；
*  enabled 变 false / 组件卸载即清 interval（全终态回收）。推导本身每次 render 便宜，
*  仅在 nowMs 跳动（1s）或 detail/selWf 变化时重算。 */
function useStageDurations(detail, wf) {
	const order = (0, react.useMemo)(() => wf?.stages.map((s) => s.id) ?? [], [wf]);
	const derived = (0, react.useMemo)(() => detail && order.length > 0 ? deriveStageStates(detail, order) : null, [detail, order]);
	const ticking = derived !== null && (derived.active.length > 0 || order.some((id) => derived.states[id] === "awaiting-human"));
	const [nowMs, setNowMs] = (0, react.useState)(() => Date.now());
	(0, react.useEffect)(() => {
		if (!ticking) return;
		const timer = setInterval(() => setNowMs(Date.now()), 1e3);
		return () => clearInterval(timer);
	}, [ticking]);
	return {
		durs: (0, react.useMemo)(() => detail && order.length > 0 ? deriveStageDurations(detail.timeline, order, detail.handoffs, { closedTs: detail.status === "closed" ? detail.updated ?? null : null }) : {}, [detail, order]),
		nowMs
	};
}
/** 节点耗时徽标（t260901-12）：done 显定值；running 走秒；人审等待显橙「人等 Xm」实时；
*  todo/blocked 不显；done/todo 遇开放窗不显（引擎无 done mark，不发明口径）。
*  总耗时=Σ轮=墙钟占用（含人等/阻塞跨度），tooltip 逐轮 + 人等段单列可拆。 */
function StageDurationInline({ d, vis, nowMs }) {
	if (vis === "todo" || vis === "blocked") return null;
	const openRound = d.rounds.some((r) => r.toMs === null);
	if (vis === "done") {
		if (openRound) return null;
		const total = stageTotalMs(d);
		if (total === null) return null;
		return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-stage-dur",
			style: { color: D2_COLOR.done },
			title: stageDurationTitle(d),
			children: fmtDur$1(total)
		});
	}
	const openWait = d.humanWaits.some((w) => w.toMs === null);
	const text = vis === "awaiting-human" && openWait ? `Human wait ${fmtDur$1(humanWaitTotalMs(d, nowMs))}` : (() => {
		const t = stageTotalMs(d, nowMs);
		return t === null ? null : fmtDur$1(t);
	})();
	if (text === null) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
		className: "wb-stage-dur",
		style: { color: D2_COLOR[vis] },
		title: stageDurationTitle(d, nowMs),
		children: text
	});
}
/** 步骤条：模板步链一字排开，色=状态（与左栏圆点同口径）。
*  t260901-05：并行分叉期多个步同时 ▶（活跃步数组语义，数据源 deriveStageStates；
*  回退口径（活跃空/无 timeline）states 已是单值指针结果，直接消费）。 */
function D2Stepper({ detail, wf, usage, durs, nowMs }) {
	if (!wf || wf.stages.length === 0) return null;
	const derived = deriveStageStates(detail, wf.stages.map((s) => s.id));
	const isParallel = derived.active.length > 1;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-d2-steps",
		children: wf.stages.map((s, i) => {
			const vis = derived.states[s.id] ?? "todo";
			const parallelPeers = isParallel && vis === "running" ? derived.active.filter((id) => id !== s.id).map((id) => stageDisplayLabel(id, wf.stages.find((x) => x.id === id)?.name)) : [];
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
				style: {
					display: "inline-flex",
					alignItems: "center"
				},
				children: [i > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { className: "wb-d2-link" }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					className: "wb-d2-step",
					"data-s": vis,
					title: `${s.id} · ${s.role} · ${partsTitle(s.parts)}`,
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {
							className: "ico",
							children: D2_ICON[vis]
						}),
						stageDisplayLabel(s.id, s.name),
						" ",
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(PartsBadges, { parts: s.parts }),
						parallelPeers.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-d2-par",
							title: `Parallel with ${parallelPeers.join(", ")} (forked rendering)`,
							children: " ∥"
						}),
						(s.parts ?? []).includes("agent") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(StageUsageInline, {
							stageId: s.id,
							usage
						}),
						durs?.[s.id] && nowMs !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(StageDurationInline, {
							d: durs[s.id],
							vis,
							nowMs
						})
					]
				})]
			}, s.id);
		})
	});
}
/** 打回横幅：timeline 里 state=rework 的记录逐条列出（新的在前）——
*  「什么时候打回的、谁打的、理由、打回到哪步」一眼可见，不用去深查区翻流水。 */
function D2Reworks({ detail, wf }) {
	const reworks = (detail.timeline ?? []).filter((t) => t.state === "rework");
	if (reworks.length === 0) return null;
	const nameOf = (id) => stageDisplayLabel(id, wf?.stages.find((s) => s.id === id)?.name);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-d2-reworks",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "ttl",
			children: [
				"⤺ Reworked ",
				reworks.length,
				"× (newest first)"
			]
		}), [...reworks].reverse().map((t, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "row",
			children: [
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "when",
					children: fmtAt(t.at)
				}),
				"Sent back to ",
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "tgt",
					children: nameOf(t.stage)
				}),
				t.reason ? `: ${t.reason}` : ""
			]
		}, i))]
	});
}
/** 一句话现状：从 stage_state + timeline + gate_runs 推导，人话回答「现在到哪了」。
*  t260901-05：并行分叉期活跃步数组多步时改报并行文案（与步骤条双高亮同口径）。 */
function d2StatusLine(detail, wf) {
	if (detail.status === "closed") {
		const sig = detail.signatures?.merge;
		return {
			s: "done",
			text: `Closed${sig ? ` (merged by ${sig.who})` : ""}`
		};
	}
	const name = stageDisplayLabel(detail.stage, detail.stage_name) || detail.stage || "—";
	if (detail.stage_state === "blocked") return {
		s: "blocked",
		text: `Stuck at ${name}: ${[...detail.timeline ?? []].reverse().find((t) => t.state === "blocked")?.reason || "see problems section below"}`
	};
	if (detail.stage_state === "awaiting-human") return {
		s: "awaiting-human",
		text: `Awaiting your approval: ${name}${(detail.gate_runs?.[detail.gate_runs.length - 1])?.green ? " (merge_check green)" : ""}`
	};
	if (detail.stage_state === "running") {
		const order = wf?.stages.map((s) => s.id) ?? [];
		if (order.length > 0) {
			const derived = deriveStageStates(detail, order);
			if (!derived.fallback && derived.active.length > 1) return {
				s: "running",
				text: `Forked in parallel: ${derived.active.map((id) => stageDisplayLabel(id, wf.stages.find((x) => x.id === id)?.name)).join(" ∥ ")}`
			};
		}
		const enters = (detail.timeline ?? []).filter((t) => t.stage === detail.stage && t.state === "running").length;
		const kb = detail.session_kb ? `, agent read ${detail.session_kb}KB` : "";
		return {
			s: "running",
			text: `${name} in progress (enter #${enters || 1}${kb})`
		};
	}
	return {
		s: "todo",
		text: `${name} · ${STATE_LABEL[detail.stage_state] ?? detail.stage_state}`
	};
}
/** 时长人话：75s → 1分15秒；3700s → 1时1分。 */
function fmtDur(sec) {
	const s = Math.max(0, Math.floor(sec));
	if (s < 60) return `${s}s`;
	if (s < 3600) return `${Math.floor(s / 60)}m${s % 60 > 0 ? ` ${s % 60}s` : ""}`;
	return `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`;
}
/** 运行脉搏行（t260825-03）：当前阶段 gen + 本段已运行时长 + 会话日志 KB 及增速 + 心跳年龄。
*  数据源：detail.pulse（Temporal pending activity 心跳，详情 5s 静默刷新自动带上）
*  + detail.session_kb（workbench 侧 stat，宿主半 _sessionKbFast）。
*  软降级：非 running 整行隐藏；running 但无心跳显「无心跳」。疑似卡死（心跳停 >
*  120s，或 session_kb 停涨 ≥180s 且心跳延迟）红色提示——只显示不动作。 */
function PulseLine({ detail }) {
	const kbChangeRef = (0, react.useRef)(null);
	const kb = typeof detail.session_kb === "number" && detail.session_kb > 0 ? detail.session_kb : 0;
	(0, react.useEffect)(() => {
		if (kb <= 0) return;
		const prev = kbChangeRef.current;
		if (prev === null || prev.id !== detail.id) kbChangeRef.current = {
			id: detail.id,
			kb,
			ts: Math.floor(Date.now() / 1e3),
			delta: null
		};
		else if (prev.kb !== kb) kbChangeRef.current = {
			id: detail.id,
			kb,
			ts: Math.floor(Date.now() / 1e3),
			delta: kb - prev.kb
		};
	}, [detail.id, kb]);
	if (detail.stage_state !== "running") return null;
	const pulse = detail.pulse ?? null;
	if (pulse === null) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-pulse",
		"data-s": "none",
		children: "Pulse: no heartbeat (non-agent stage or worker down)"
	});
	const now = Math.floor(Date.now() / 1e3);
	const hb = pulse.heartbeat ?? {};
	const gen = typeof hb.gen === "number" ? hb.gen : null;
	const hbTs = pulse.last_heartbeat_ts ?? 0;
	const hbAge = hbTs > 0 ? Math.max(0, now - hbTs) : null;
	const startedTs = pulse.started_ts ?? 0;
	const runSec = startedTs > 0 ? Math.max(0, now - startedTs) : typeof hb.polls === "number" ? hb.polls * 5 : null;
	const stallSec = kb > 0 && kbChangeRef.current !== null && kbChangeRef.current.id === detail.id ? Math.max(0, now - kbChangeRef.current.ts) : 0;
	const stuck = hbAge !== null && hbAge > 120 || stallSec >= 180 && (hbAge === null || hbAge > 30);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-pulse",
		"data-s": stuck ? "stuck" : !stuck && (hbAge !== null && hbAge > 30 || stallSec >= 120) ? "warn" : "ok",
		children: [
			"Pulse: ",
			stageDisplayLabel(detail.stage, detail.stage_name) || detail.stage || pulse.activity || "—",
			gen !== null ? ` · enter #${gen + 1} (gen${gen})` : "",
			runSec !== null ? ` · stage running ${fmtDur(runSec)}${startedTs > 0 ? "" : " (estimated from heartbeat count)"}` : "",
			" · session log ",
			kb > 0 ? `${kb}KB (${stallSec >= 60 ? `stalled ${fmtDur(stallSec)}` : kbChangeRef.current !== null && kbChangeRef.current.id === detail.id && kbChangeRef.current.delta !== null ? `delta ${kbChangeRef.current.delta >= 0 ? "+" : ""}${kbChangeRef.current.delta}KB` : "growing"})` : "—",
			hbAge !== null ? ` · heartbeat ${hbAge < 5 ? "just now" : `${hbAge}s ago`}` : " · no heartbeat yet",
			pulse.heartbeat_raw !== void 0 ? ` · heartbeat raw: ${pulse.heartbeat_raw.slice(0, 60)}` : "",
			stuck ? " — possibly stuck (advisory only, no auto-action)" : ""
		]
	});
}
const LIVE_TYPE_LABEL = {
	user: "user",
	assistant: "agent",
	tool: "tool",
	result: "result",
	step: "round",
	retry: "retry",
	attempt: "attempt"
};
/**
* spec 卡 markdown HTML（t260925-18）：renderMarkdown（knowledge，转义先行）产出后，
* 把渲染器自带的中文按钮文案「复制」在显示层改英文——knowledge 源不在本票写集，
* 不改共享渲染器；字符串级后处理纯函数，tests/ui-labels.mjs 可测。
*/
function specMarkdownHtml(spec) {
	return renderMarkdown(spec).replace(">复制</button>", ">Copy</button>");
}
/**
* 证据图 src 契约（t260831-08，导出供 smoke 断言）：截图只走服务端端点
* （归档/泳道读取 + 防穿收口 host 一处），不内联 base64（取舍清单 #4：
* 不带 data: 支持）。encodeURI 级防呆：id/文件名含怪字符时 encodeURIComponent。
*/
function evidenceImgSrc(ticketId, file) {
	return `/sandbar-workbench/api/wf/tickets/${encodeURIComponent(ticketId)}/evidence/${encodeURIComponent(file)}`;
}
/** 灯箱键盘键位契约（t260901-13，导出供 smoke 对齐键位，防 handler 与测试漂移）。 */
const evidenceLightboxKeys = {
	close: "Escape",
	prev: "ArrowLeft",
	next: "ArrowRight"
};
/**
* 灯箱下标导航纯函数（t260901-13，导出供 smoke 直测）：index 循环移动 delta，
* 非法入参（空列表/越界/非整数 delta）一律兜底到安全下标，不抛——灯箱 open 期间
* evidence 列表被重拉变短时，同一条兜底保证渲染下标始终落在列表内。
*/
function evidenceNav(files, index, delta) {
	const n = files.length;
	if (n <= 0) return 0;
	return (((Number.isInteger(index) && index >= 0 && index < n ? index : 0) + (Number.isInteger(delta) ? delta : 0)) % n + n) % n;
}
/** 详情抽屉「截图证据」区（t260831-08）：拉 evidence 列表端点渲染泳道/归档截图。
*  降级口径：files 空（无泳道/已合并无归档/端点异常）→ 整区不渲染，不报错；
*  单图加载失败 → 占位人话，不拖垮整区。
*  灯箱（t260901-13）：缩略图点击 → EvidenceLightbox 遮罩层放大看图。
*  C1（review 走查结论）：keydown 挂 document 级，方向键在 input/textarea/select/
*  contentEditable 内触发时忽略（防一边移动光标一边切图），Esc 任何情况都关——
*  见 evidenceKeyGuard。 */
function isEditableTarget(t) {
	if (!(t instanceof HTMLElement)) return false;
	return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable;
}
/** 灯箱 lightbox（t260901-13）：点击放大 + 左右按钮/键盘循环切换 + 计数与文件名
*  + Esc/点遮罩关闭。键盘挂 document 级（fixed 遮罩不可聚焦，绑元素需 autoFocus
*  抢抽屉焦点；document 级覆盖天然）。所有关闭路径（Esc/点遮罩/切工单/关抽屉）
*  都收口到「卸载即 useEffect cleanup removeEventListener」单点回收。 */
function EvidenceLightbox({ ticketId, files, index, onClose, onNav: nav }) {
	(0, react.useEffect)(() => {
		const h = (e) => {
			if (e.key === evidenceLightboxKeys.close) {
				e.preventDefault();
				onClose();
			} else if (e.key === evidenceLightboxKeys.prev && !isEditableTarget(e.target)) {
				e.preventDefault();
				nav(files, index, -1);
			} else if (e.key === evidenceLightboxKeys.next && !isEditableTarget(e.target)) {
				e.preventDefault();
				nav(files, index, 1);
			}
		};
		document.addEventListener("keydown", h);
		return () => document.removeEventListener("keydown", h);
	}, [
		files,
		index,
		onClose
	]);
	const f = files[index] ?? files[0];
	const [broken, setBroken] = (0, react.useState)(false);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-lb",
		onClick: onClose,
		children: [
			files.length > 1 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				type: "button",
				className: "wb-lb-nav",
				"aria-label": "Previous",
				onClick: (e) => {
					e.stopPropagation();
					nav(files, index, -1);
				},
				children: "‹"
			}),
			broken ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-lb-miss",
				children: ["Screenshot failed to load: ", f]
			}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("img", {
				className: "wb-lb-img",
				alt: `Screenshot evidence ${f}`,
				src: evidenceImgSrc(ticketId, f),
				onClick: (e) => e.stopPropagation(),
				onError: () => setBroken(true)
			}),
			files.length > 1 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				type: "button",
				className: "wb-lb-nav",
				"aria-label": "Next",
				onClick: (e) => {
					e.stopPropagation();
					nav(files, index, 1);
				},
				children: "›"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-lb-bar",
				onClick: (e) => e.stopPropagation(),
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: files.length > 0 ? `${index + 1} / ${files.length}` : "0 / 0" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-lb-name",
						children: f
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						className: "wb-lb-close",
						onClick: onClose,
						children: "Close (Esc)"
					})
				]
			})
		]
	});
}
/** 灯箱导航动作收口（t260901-13）：EvidenceImages 持 open 下标 state，经 setOpen
*  落 evidenceNav 结果。抽成模块级函数便于 handler 复用与类型收口。 */
function onNav(files, index, delta, setOpen) {
	setOpen(evidenceNav(files, index, delta));
}
function EvidenceImages({ ticketId }) {
	const [files, setFiles] = (0, react.useState)(null);
	const [broken, setBroken] = (0, react.useState)({});
	const [open, setOpen] = (0, react.useState)(null);
	(0, react.useEffect)(() => {
		let cancelled = false;
		setFiles(null);
		setBroken({});
		setOpen(null);
		apiGet(`/sandbar-workbench/api/wf/tickets/${encodeURIComponent(ticketId)}/evidence`).then((d) => {
			if (!cancelled) setFiles(Array.isArray(d?.result?.files) ? d.result.files : []);
		}).catch(() => {
			if (!cancelled) setFiles([]);
		});
		return () => {
			cancelled = true;
		};
	}, [ticketId]);
	if (files === null || files.length === 0) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-eimgs",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "ttl",
				children: "Screenshot evidence"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-eimgs-grid",
				children: files.map((f, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("figure", {
					className: "wb-eimgs-item",
					role: "button",
					tabIndex: 0,
					"aria-label": `Zoom in ${f}`,
					onClick: () => setOpen(i),
					onKeyDown: (e) => {
						if (e.key === "Enter" || e.key === " ") {
							e.preventDefault();
							setOpen(i);
						}
					},
					children: [broken[f] ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-eimgs-miss",
						children: ["Screenshot failed to load: ", f]
					}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("img", {
						className: "wb-eimgs-img",
						loading: "lazy",
						alt: `Screenshot evidence ${f}`,
						title: f,
						src: evidenceImgSrc(ticketId, f),
						onError: () => setBroken((b) => ({
							...b,
							[f]: true
						}))
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("figcaption", { children: f })]
				}, f))
			}),
			open !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(EvidenceLightbox, {
				ticketId,
				files,
				index: evidenceNav(files, open, 0),
				onClose: () => setOpen(null),
				onNav: (fs, i, d) => onNav(fs, i, d, setOpen)
			})
		]
	});
}
/** 「实时动态」折叠面板（t260825-03）：泳道会话文件尾 30 条事件流（agent 最近在干什么）。
*  折叠时不轮询；展开后每 8s 拉一次 agent-live。降级（exists=false）显 reason，不报错。 */
function AgentLivePanel({ ticketId }) {
	const [open, setOpen] = (0, react.useState)(false);
	const [data, setData] = (0, react.useState)(void 0);
	const [err, setErr] = (0, react.useState)("");
	(0, react.useEffect)(() => {
		if (!open) return;
		let dead = false;
		const load = async () => {
			try {
				const r = await apiGet(`${API}/tickets/${encodeURIComponent(ticketId)}/agent-live?n=30`);
				if (dead) return;
				if (r?.ok === true) {
					setData(r.result);
					setErr("");
				} else setErr(String(r?.error ?? "read failed"));
			} catch (e) {
				if (!dead) setErr(String(e instanceof Error ? e.message : e));
			}
		};
		load();
		const stop = startVisibleInterval(() => {
			if (!dead) load();
		}, 8e3);
		return () => {
			dead = true;
			stop();
		};
	}, [open, ticketId]);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-live",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-live-head",
			onClick: () => setOpen((o) => !o),
			children: [
				/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					className: "wb-live-title",
					children: [open ? "▾" : "▸", " Live activity"]
				}),
				open && data?.exists === true && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					className: "wb-live-meta",
					children: [
						"Latest ",
						data.events.length,
						" entries · session ",
						data.sizeKb ?? 0,
						"KB · updated ",
						fmtTs(data.mtime),
						" · auto-refresh every 8s"
					]
				}),
				!open && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-live-meta",
					children: "Recent agent event stream (auto-refresh every 8s when expanded)"
				})
			]
		}), open && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-live-body",
			children: [
				err !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-err",
					children: ["Live activity read failed: ", err]
				}),
				err === "" && data === void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-empty",
					children: "Loading…"
				}),
				err === "" && data !== void 0 && !data.exists && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-empty",
					children: data.reason ?? "No session data yet"
				}),
				err === "" && data !== void 0 && data.exists && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
					data.events.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-empty",
						children: data.reason ?? "No events to show"
					}),
					[...data.events].reverse().map((ev, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-live-row",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-live-ts",
								children: fmtTs(ev.ts)
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-live-type",
								"data-t": ev.type,
								children: LIVE_TYPE_LABEL[ev.type] ?? ev.type
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-live-sum",
								children: ev.summary
							})
						]
					}, `${ev.ts}-${i}`)),
					data.uncoveredTypes !== void 0 && data.uncoveredTypes.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-al-trunc",
						children: [
							"⚠ Session contains record types this UI does not render: ",
							data.uncoveredTypes.join("; "),
							" (content may be missing)."
						]
					}),
					data.truncated && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-al-trunc",
						children: "Showing latest 30 entries only (full log in the lane session file)."
					})
				] })
			]
		})]
	});
}
/** 问题区：只在有问题时渲染（blocked / 最近一次 merge_check 红）。数据源=gate_runs+timeline，
*  这两个字段接口一直返回、旧版前端没用——「有没有问题一目了然」全靠把它们摆上来。
*  t261001-11：行推导下沉 problems-model.gateProblemRows（gate_runs 双形态容忍——
*  dev-lane 的合门记录（带 checks）走逐项行、轻道闸记录无 checks 走自带字段；
*  此处旧读者曾在轻道 blocked 票上对无 checks 键的记录直接解引用抛 TypeError
*  打掉整个侧栏）。 */
function D2Problems({ detail }) {
	if (detail.status === "closed" || detail.stage_state !== "blocked") return null;
	let rows = gateProblemRows(detail).map((r) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "row",
		children: [r.text, r.dim ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
			className: "dim",
			children: [" — ", r.dim]
		}) : null]
	}, r.key));
	if (rows.length === 0) {
		const lastBlocked = [...detail.timeline ?? []].reverse().find((t) => t.state === "blocked");
		if (lastBlocked?.reason) rows = [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "row",
			children: lastBlocked.reason
		}, "why")];
		else rows = [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "row",
			children: [
				"Stuck at ",
				stageDisplayLabel(detail.stage, detail.stage_name) || detail.stage || "—",
				"; reason not recorded"
			]
		}, "w")];
	}
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-d2-problems",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "ttl",
			children: "⛔ Problems need attention"
		}), rows]
	});
}
/** t261001-11 第二缺陷：槽条目渲染崩溃曾把整个 sidebar.workspaces 条目打掉
*  （dsh 整条回收 → 退回默认 UI）。本地错误边界兜住：崩了只在本面板画一行
*  点名故障的 inline note（slotFaultMessage），其余 UI 存活；console.error 留痕。 */
var SlotErrorBoundary = class extends react.Component {
	state = { message: null };
	static getDerivedStateFromError(error) {
		return { message: slotFaultMessage(error) };
	}
	componentDidCatch(error, info) {
		console.error("[workbench] sidebar slot entry crashed (contained by SlotErrorBoundary):", error, info);
	}
	render() {
		if (this.state.message !== null) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "wb-sb-crashed",
			role: "alert",
			children: this.state.message
		});
		return this.props.children;
	}
};
/** token 数人话格式：≥1M 显 x.xxM、≥1k 显 x.xk，否则原值（悬停有精确值）。 */
function fmtTok(n) {
	if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
	if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
	return String(n);
}
function usageSum(s) {
	return `in ${fmtTok(s.input)} / out ${fmtTok(s.output)}`;
}
/** 阶段/整单的模型名串：≥2 个模型才显示（验收口径：多模型才显示模型名），按消耗排序。 */
function usageModelNames(models) {
	if (models.length < 2) return "";
	return models.map((m) => m.model).filter(Boolean).join(", ");
}
/** 某阶段的使用（无该段数据 → null，UI 软降级不渲染数字）。 */
function stageUsage(u, stageId) {
	if (!u || u.exists !== true) return null;
	return u.byStage[stageId] ?? null;
}
/** agent 段数：timeline 中 state==='running' 且该段执行主体含 agent 的进段次数（含重入）。 */
function agentSegmentCount(detail, wf) {
	const agentStages = new Set((wf?.stages ?? []).filter((s) => (s.parts ?? []).includes("agent")).map((s) => s.id));
	return (detail.timeline ?? []).filter((t) => t.state === "running" && agentStages.has(t.stage)).length;
}
/** 悬停一行：阶段 token 明细（cacheRead 收悬停，验收 6）。 */
function stageUsageTitle(s) {
	const parts = [`in ${s.input} / out ${s.output} / cacheRead ${s.cacheRead}`];
	const names = Object.keys(s.models);
	if (names.length > 0) parts.push(`Models: ${names.join(", ")}`);
	return parts.join(" · ");
}
/** token 消耗拉取（t260828-07）：详情抽屉打开时拉一次 agent-usage（不进轮询，克制）。
*  降级（exists=false，无会话文件/历史已合并单）→ 调用方显「—」，不报错。 */
function useAgentUsage(ticketId, enabled) {
	const [usage, setUsage] = (0, react.useState)(void 0);
	(0, react.useEffect)(() => {
		if (!enabled || ticketId === "") return;
		let dead = false;
		setUsage(void 0);
		(async () => {
			try {
				const r = await apiGet(`${API}/tickets/${encodeURIComponent(ticketId)}/agent-usage`);
				if (!dead && r?.ok === true) setUsage(r.result);
			} catch {}
		})();
		return () => {
			dead = true;
		};
	}, [enabled, ticketId]);
	return usage;
}
/** 头部一行合计（验收 3）：agent 段数 + 输入/输出总量 + 模型；cacheRead 收悬停。
*  t260917-05「可辨」：会话格式不认识/目录有未入统计会话 → 可见警示（非 hover-only）。 */
function UsageSummaryLine({ detail, wf, usage }) {
	if (usage === void 0) {
		if (detail.status === "closed") return null;
		return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-usage",
			title: "loading token usage…",
			children: "tokens …"
		});
	}
	if (!usage.exists) {
		if (detail.status === "closed") return null;
		const hint = usageSuspectHint(usage);
		if (hint !== null) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-usage",
			"data-s": "suspect",
			style: { color: "var(--dsw-derive-danger,#cf222e)" },
			title: usageSuspectTitle(usage),
			children: hint
		});
		return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
			className: "wb-usage",
			"data-s": "none",
			title: usage.reason ?? "no session data",
			children: "tokens —"
		});
	}
	const segs = agentSegmentCount(detail, wf);
	const names = usageModelNames(usage.models);
	const suspectHint = usageSuspectHint(usage);
	const uncoveredHint = usage.uncovered === true ? usage.uncoveredDetail ?? "session contains record types this UI does not render (content may be missing)" : null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
		className: "wb-usage",
		title: [
			`agent stages ${segs}`,
			`in ${usage.total.input} / out ${usage.total.output} / cacheRead ${usage.total.cacheRead}`,
			names !== "" ? `Models: ${names}` : `Model: ${usage.models[0]?.model ?? "—"} (single model)`,
			`session files ${usage.files} (all roles)`,
			suspectHint !== null ? usage.suspectDetail ?? suspectHint : "",
			uncoveredHint ?? ""
		].filter(Boolean).join(" · "),
		children: [
			"🤖 ",
			segs,
			" stages · ",
			usageSum(usage.total),
			names !== "" ? ` · ${names}` : "",
			suspectHint !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				style: { color: "var(--dsw-derive-danger,#cf222e)" },
				title: usage.suspectDetail ?? suspectHint,
				children: " · ⚠"
			}),
			uncoveredHint !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				style: { color: "var(--dsw-derive-danger,#cf222e)" },
				title: uncoveredHint,
				children: " · ⚠ unrendered types"
			})
		]
	});
}
/** 阶段行内数字（验收 2）：agent 步显 in/out；多模型才追加模型名；cacheRead 收悬停。
*  无数据（历史单/该段无 usage）→ 不渲染任何数字（只有图标没有数字，验收 5）。 */
function StageUsageInline({ stageId, usage }) {
	const s = stageUsage(usage, stageId);
	if (s === null) return null;
	const names = Object.entries(s.models).sort((a, b) => b[1].input + b[1].output - (a[1].input + a[1].output)).map(([k]) => k.split("/")[1] ?? k);
	const multi = names.length >= 2 ? ` · ${names.join(", ")}` : "";
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
		className: "wb-stage-usage",
		title: stageUsageTitle(s),
		children: [usageSum(s), multi]
	});
}
function D2Stages({ detail, wf, usage, durs, nowMs }) {
	if (!wf || wf.stages.length === 0) return null;
	const tl = detail.timeline ?? [];
	const handoffs = detail.handoffs ?? [];
	const order = wf.stages.map((s) => s.id);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-d2-stages",
		children: wf.stages.map((s) => {
			const vis = d2StageVisual(detail, s.id, order);
			const r = detail.results?.[s.id];
			const h = [...handoffs].reverse().find((x) => x.stage === s.id);
			const enters = tl.filter((t) => t.stage === s.id && t.state === "running").length;
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-d2-card",
				"data-s": vis,
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "hd",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {
								className: "ico",
								children: D2_ICON[vis]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "nm",
								children: stageDisplayLabel(s.id, s.name)
							}),
							" ",
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)(PartsBadges, { parts: s.parts }),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "meta",
								children: [
									s.role,
									enters > 1 ? ` · enter #${enters}` : "",
									h?.ts ? ` · ${fmtTs(h.ts)}` : ""
								]
							}),
							(s.parts ?? []).includes("agent") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(StageUsageInline, {
								stageId: s.id,
								usage
							}),
							durs?.[s.id] && nowMs !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(StageDurationInline, {
								d: durs[s.id],
								vis,
								nowMs
							})
						]
					}),
					r?.summary && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "sum",
						children: r.summary
					}),
					r?.report && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-md wb-d2-report",
						dangerouslySetInnerHTML: { __html: renderMarkdown(r.report) }
					}),
					r && (r.evidence || (r.files_changed?.length ?? 0) > 0 || (r.deliverables?.length ?? 0) > 0) && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: "Details (evidence / deliverables)" }),
						(r.files_changed?.length ?? 0) > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "ev",
							children: ["Files changed: ", (r.files_changed ?? []).join("; ")]
						}),
						(r.deliverables?.length ?? 0) > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "ev",
							children: ["Deliverables: ", (r.deliverables ?? []).join("; ")]
						}),
						r.evidence && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "ev",
							children: r.evidence
						})
					] })
				]
			}, s.id);
		})
	});
}
/** 按 v0.3 §10 矩阵计算可用操作（accept 内嵌在验收清单逐项打勾，不进操作区）。
*  行式台面（TicketRow）与详情抽屉（TicketDetail）共用：两者都带 status/stage_state/stage。 */
const INSPECTION_FACE_CSS = `
.wb-insp{display:flex;flex-direction:column;gap:8px;margin:4px 0}
.wb-insp-head{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;padding:8px 10px;
  border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px}
.wb-insp-k{color:var(--dsw-derive-muted,#57606a);font-size:12px}
.wb-insp-v{font-weight:600;font-size:13px}
.wb-insp-sev i{font-style:normal;display:inline-block;margin-left:6px;padding:1px 6px;border-radius:9px;font-size:11px}
.wb-insp-sev i[data-sev=high]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-insp-sev i[data-sev=med]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-insp-sev i[data-sev=low]{background:var(--dsw-derive-neutral-bg,#f6f8fa);color:var(--dsw-derive-muted,#57606a)}
.wb-insp-gate{border:1px solid var(--dsw-derive-accent-border,#54aeff);border-radius:8px;padding:8px 10px;
  background:var(--dsw-derive-accent-bg,#ddf4ff)}
.wb-insp-gate .ttl{font-weight:600;font-size:13px;margin-bottom:4px}
.wb-insp-gate-txt{font-size:12px;color:var(--dsw-derive-fg,#1f2328)}
.wb-insp-gateerr{margin-top:4px;font-size:12px;color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-insp-signed{margin-top:6px;font-size:12px;color:var(--dsw-derive-success,#1a7f37)}
.wb-insp-signrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
.wb-insp-note{flex:1;min-width:160px;padding:5px 8px;border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:6px;font-size:12px}
.wb-insp-block{border:1px solid var(--dsw-derive-border,#d0d7de);border-radius:8px;padding:6px 10px}
.wb-insp-block summary{cursor:pointer;font-size:12px;font-weight:600}
.wb-insp-tl{display:flex;gap:10px;align-items:baseline;padding:3px 0;font-size:12px;border-bottom:1px dashed var(--dsw-derive-border,#eaeef2)}
.wb-insp-tl code{font-size:11px;color:var(--dsw-derive-muted,#57606a)}
.wb-insp-f{display:flex;gap:8px;align-items:baseline;padding:4px 0;font-size:12px;border-bottom:1px dashed var(--dsw-derive-border,#eaeef2)}
/* 260926 报告面可读性（宿主报「都是 [object Object]」）：发现项改成块状两行制——
   首行=严重度/扫描面/置信度/核实态/主题，下面逐行 Why / Suggestion / Evidence 清单。 */
.wb-insp-f{flex-direction:column;align-items:stretch;gap:3px}
.wb-insp-f-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.wb-insp-f ul{margin:2px 0 2px 16px;padding:0}
.wb-insp-f li{margin:1px 0;word-break:break-all}
.wb-insp-sev-tag{flex:none;display:inline-block;min-width:34px;text-align:center;padding:1px 6px;border-radius:9px;font-size:11px}
.wb-insp-sev-tag[data-sev=high]{background:var(--dsw-derive-danger-bg,#ffebe9);color:var(--dsw-derive-danger,#cf222e)}
.wb-insp-sev-tag[data-sev=med]{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-insp-sev-tag[data-sev=low]{background:var(--dsw-derive-neutral-bg,#f6f8fa);color:var(--dsw-derive-muted,#57606a)}
.wb-insp-rep{font-size:12px;padding:2px 0}
/* t260926-05 报告面全量上屏：泛化 label:value 行 / 警示行（预算耗尽、迟到回执、
   blockers）/ 报告 JSON 摘要缩进排版。只动巡检详情面，不涉其他 surface。 */
.wb-insp-row{display:flex;gap:8px;align-items:baseline;padding:2px 0;font-size:12px;border-bottom:1px dashed var(--dsw-derive-border,#eaeef2)}
.wb-insp-row .wb-insp-k{flex:none;min-width:150px;color:var(--dsw-derive-muted,#57606a)}
.wb-insp-row .wb-insp-v{word-break:break-all}
.wb-insp-row-warn{background:var(--dsw-derive-warn-bg,#fff8c5);color:var(--dsw-derive-warn-deep,#7d4e00)}
.wb-insp-digest{margin-top:4px;padding:6px 8px;background:var(--dsw-derive-surface,#fbfcfd);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;font-size:11px;font-family:var(--dsw-mono,ui-monospace,monospace);max-height:320px;overflow:auto;word-break:break-all}
.wb-insp-digest-raw{margin:4px 0 0;padding:6px 8px;background:var(--dsw-derive-surface,#fbfcfd);border:1px solid var(--dsw-derive-border,#d0d7de);
  border-radius:6px;font-size:11px;max-height:320px;overflow:auto;white-space:pre-wrap;word-break:break-all}
.wb-insp-note-banner{background:var(--dsw-derive-warn-bg,#fff8c5);border:1px solid var(--dsw-derive-warn-border,#d4a72c);
  color:var(--dsw-derive-warn-deep,#7d4e00);border-radius:6px;padding:5px 10px;font-size:12px;margin-bottom:6px}
`;
/** 套件证据段（t260926-05 报告面全量上屏）：face["suite"] 的有标签可读投影——
*  计数/分相墙钟/预算/超时/迟到回执/逐场景红绿/blockers。数据形状不限
*  （模型层 suiteSectionView 全防御），畸形形状=单行安全文本不炸。 */
function InspectionSuiteFace({ suite }) {
	const sv = suiteSectionView(suite);
	if (sv.rows.length === 0 && sv.cases.length === 0 && sv.blockers.length === 0) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
		className: "wb-insp-block",
		"data-testid": "inspection-suite",
		open: true,
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: "Suite evidence" }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [
			sv.rows.map((r, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: r.warn ? "wb-insp-row wb-insp-row-warn" : "wb-insp-row",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-insp-k",
					children: r.label
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-insp-v",
					children: r.value
				})]
			}, i)),
			sv.blockers.map((b, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-insp-row wb-insp-row-warn",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-insp-k",
					children: "Blocker"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
					className: "wb-insp-v",
					children: b
				})]
			}, `b${i}`)),
			sv.cases.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				"data-testid": "inspection-suite-cases",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-insp-k",
					children: [
						"Cases (",
						sv.cases.length,
						")"
					]
				}), sv.cases.map((cse, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-insp-tl",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", { children: cse.name }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						"data-exit": cse.exit,
						children: cse.exit === "0" ? "pass" : `exit ${cse.exit}`
					})]
				}, i))]
			})
		] })]
	});
}
/** 报告文件 affordance（t260926-05 验收「report_path 可读出路」）：路径原样可读 +
*  「Open report digest」展开宿主摘要端点产出的缩进式可读摘要（reportDigest
*  同源）；端点 fail-closed 人话原因原样上屏（诚实降级，不静默空白）。 */
function InspectionReportFileFace({ ticketId, reportPath }) {
	const [digest, setDigest] = (0, react.useState)(null);
	const [raw, setRaw] = (0, react.useState)(null);
	const [reason, setReason] = (0, react.useState)("");
	const [open, setOpen] = (0, react.useState)(false);
	async function toggle() {
		const next = !open;
		setOpen(next);
		if (!next || digest !== null || reason !== "") return;
		try {
			const r = await apiGet(`${API}/tickets/${encodeURIComponent(ticketId)}/inspection-report?path=${encodeURIComponent(reportPath)}`);
			const res = r?.result;
			if (res?.ok && Array.isArray(res.digest)) setDigest(res.digest);
			else if (res?.ok && res.report !== void 0) setDigest(reportDigest(res.report));
			else {
				setReason(String(res?.reason ?? r?.error ?? "Report digest unavailable"));
				if (typeof res?.raw === "string") setRaw(res.raw);
			}
		} catch (err) {
			setReason(`Report digest request failed: ${String(err instanceof Error ? err.message : err)}`);
		}
	}
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-insp-rep",
		"data-testid": "inspection-report",
		children: [
			"Report file: ",
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", { children: reportPath }),
			" ",
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				className: "wb-btn",
				"data-testid": "inspection-report-open",
				onClick: toggle,
				children: open ? "Hide report digest" : "Open report digest"
			}),
			open && reason !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-insp-row-warn",
				"data-testid": "inspection-report-reason",
				children: reason
			}),
			open && raw !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
				className: "wb-insp-digest-raw",
				"data-testid": "inspection-report-raw",
				children: raw
			}),
			open && digest !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-insp-digest",
				"data-testid": "inspection-report-digest",
				children: digest.map((l, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					style: { paddingLeft: l.depth * 14 },
					children: l.text
				}, i))
			})
		]
	});
}
function InspectionDetailFace({ detail, operator, opBusy, onSign }) {
	const [note, setNote] = (0, react.useState)("");
	const findings = Array.isArray(detail.findings) ? detail.findings : [];
	const timeline = Array.isArray(detail.timeline) ? detail.timeline : [];
	const c = inspectionSummaryOf(detail);
	const awaiting = detail.stage_state === "awaiting-human";
	const signed = detail.human_gate ?? null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-insp",
		"data-kind": "inspection",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("style", { children: INSPECTION_FACE_CSS }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-insp-head",
				"data-testid": "inspection-face",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-insp-k",
						children: "Inspection"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-insp-v",
						children: detail.instance_id || "—"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-insp-k",
						children: "Period"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-insp-v",
						children: detail.period || "—"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-insp-k",
						children: "Heartbeat"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-insp-v",
						"data-heartbeat": detail.heartbeat ? "1" : "0",
						children: detail.heartbeat ? "green-proof period" : "non-heartbeat period"
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-insp-sev",
						"data-testid": "inspection-findings",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("i", {
								"data-sev": "high",
								children: ["H ", c.high]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("i", {
								"data-sev": "med",
								children: ["M ", c.med]
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("i", {
								"data-sev": "low",
								children: ["L ", c.low]
							})
						]
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-insp-gate",
				"data-wb-anchor": "review",
				"data-testid": "inspection-gate",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "ttl",
						children: [
							"Human gate (",
							detail.gate_id || "inspection-close",
							") — what to sign"
						]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-insp-gate-txt",
						children: ["approve=close (findings tracked as dev-lane fix tickets); reject=kill the ticket (this period voided, kept on record). Red line: ", detail.red_line || "—"]
					}),
					detail.gate_error && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-insp-gateerr",
						children: ["⚠ Rejection record: ", detail.gate_error]
					}),
					signed ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-insp-signed",
						"data-testid": "inspection-signed",
						children: [
							"Signed: ",
							signed.decision,
							" (",
							signed.who,
							")",
							signed.note ? ` · ${signed.note}` : ""
						]
					}) : awaiting ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-insp-signrow",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
								className: "wb-insp-note",
								value: note,
								onChange: (e) => setNote(e.target.value),
								placeholder: "Signature note (optional)",
								"data-testid": "inspection-sign-note"
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn wb-btn-green",
								disabled: opBusy,
								"data-testid": "inspection-sign-approve",
								onClick: () => onSign("approve", note),
								children: "✓ approve (close ticket)"
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn wb-btn-danger",
								disabled: opBusy,
								"data-testid": "inspection-sign-reject",
								onClick: () => onSign("reject", note),
								children: "✗ reject (kill ticket)"
							}),
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "wb-sub",
								children: ["Signer: ", operator]
							})
						]
					}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-sub",
						children: [
							"Not at a human gate (stage: ",
							detail.stage ?? "—",
							" · ",
							detail.stage_state,
							")"
						]
					})
				]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
				className: "wb-insp-block",
				open: true,
				"data-testid": "inspection-timeline",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("summary", { children: [
					"Stage timeline (",
					timeline.length,
					" entries)"
				] }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [timeline.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-sub",
					children: "No timeline entries"
				}), timeline.map((e, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-insp-tl",
					"data-state": String(e?.state ?? ""),
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", { children: String(e?.at ?? "—") }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: inspectionStageShort(e?.stage) || String(e?.stage ?? "—") }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: String(e?.state ?? "") }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-sub",
							children: String(e?.reason ?? "")
						})
					]
				}, i))] })]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
				className: "wb-insp-block",
				open: true,
				"data-testid": "inspection-findings-list",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("summary", { children: [
					"Findings (",
					findings.length,
					" entries)"
				] }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", { children: [findings.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-sub",
					children: "No findings (green-proof period)"
				}), findings.map((f, i) => {
					const fv = findingView(f, i);
					return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-insp-f",
						children: fv.fallback !== void 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-sub",
							"data-testid": "inspection-finding-fallback",
							children: fv.fallback
						}) : /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-insp-f-head",
								children: [
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "wb-insp-sev-tag",
										"data-sev": fv.sev,
										children: ["Severity: ", fv.sev || "?"]
									}),
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("code", { children: ["Scan: ", fv.scan] }),
									fv.confidence !== "" ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "wb-sub",
										children: ["Confidence: ", fv.confidence]
									}) : null,
									fv.verified !== "" ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "wb-sub",
										children: ["Verified: ", fv.verified]
									}) : null,
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["Subject: ", fv.subject] })
								]
							}),
							fv.why !== "" ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-sub",
								children: ["Why: ", fv.why]
							}) : null,
							fv.suggestion !== "" ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-sub",
								children: ["Suggestion: ", fv.suggestion]
							}) : null,
							fv.evidence.length > 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("ul", {
								className: "wb-sub",
								children: fv.evidence.map((e, j) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", { children: e.loc }), e.quote !== "" ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [" — ", e.quote] }) : null] }, j))
							}) : fv.evidenceFallback ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-sub",
								children: ["Evidence: ", fv.evidenceFallback]
							}) : null
						] })
					}, fv.fallback !== void 0 ? `fb${i}` : String(f?.id ?? i));
				})] })]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)(InspectionSuiteFace, { suite: detail.suite }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
				className: "wb-insp-block",
				"data-testid": "inspection-face-rows",
				open: true,
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: "Inspection fields" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", { children: (() => {
					const rows = faceRows(detail);
					if (rows.length === 0) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-sub",
						children: "No extra inspection fields"
					});
					return rows.map((r, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-insp-row",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-insp-k",
							children: r.label
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-insp-v",
							children: r.value
						})]
					}, i));
				})() })]
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-insp-block",
				children: [
					(detail.report_path ?? "") !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(InspectionReportFileFace, {
						ticketId: String(detail.id ?? ""),
						reportPath: String(detail.report_path)
					}),
					(detail.report_path ?? "") === "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-sub",
						children: "No report file (period not closed yet)"
					}),
					(detail.suggested_fix_tickets?.length ?? 0) > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-sub",
						children: [
							"Suggested fix tickets: ",
							detail.suggested_fix_tickets.length,
							" (dev-lane, referencing this ticket)"
						]
					})
				]
			})
		]
	});
}
function availableOps(t, wf) {
	const s = t.status;
	const ss = t.stage_state;
	if (t.engine === "inspection") return [];
	if (deriveTicketState(t.status, t.stage_state, t.exec_status) === "failed") return [];
	if (deriveTicketState(t.status, t.stage_state, t.exec_status) === "done") return [];
	if (t.engine === "template-as-code-v2") {
		if (s === "closed") return [];
		const v2ops = [];
		if (ss === "awaiting-human") v2ops.push("advance", "rework");
		else if (ss === "blocked") v2ops.push("unblock", "rework");
		else v2ops.push("rework");
		v2ops.push(pauseOpOf(t.paused));
		return v2ops;
	}
	const ops = [];
	if (s === "dispatched") {
		if (ss === "awaiting" || ss === "blocked") ops.push("dispatch-next", "rework");
	} else if (s === "settled") {
		if (ss === "awaiting" || ss === "awaiting-human") ops.push("advance");
		if (ss === "awaiting-human" || ss === "blocked") ops.push("rework");
	} else if (s === "verified") {
		if (ss === "awaiting") ops.push("dispatch-next");
		if (ss === "awaiting-human") ops.push("advance", "rework");
	} else if (s === "rework") {
		if (ss === "awaiting" || ss === "blocked") ops.push("dispatch-next");
		if (ss === "awaiting") ops.push("rework");
		if (ss === "awaiting-human") ops.push("advance", "rework");
	}
	if (ss === "blocked") ops.push("unblock");
	const cur = wf?.stages.find((st) => st.id === t.stage);
	if (t.stage !== null && cur !== void 0 && !cur.next && s !== "closed" && s !== "rework") ops.push("close");
	return ops;
}
const TYPE_LABEL = {
	frontmatter: "frontmatter",
	heading: "Heading",
	paragraph: "Paragraph",
	"list-item": "List item",
	"table-head": "Table head",
	"table-row": "Table row",
	code: "Code block",
	quote: "Quote",
	image: "Image",
	hr: "Divider",
	doc: "Doc",
	data: "Data",
	file: "File"
};
const STATUS_LABEL = {
	added: "Added",
	removed: "Removed",
	modified: "Modified",
	unchanged: "Unchanged"
};
const KIND_LABEL = {
	doc: "Doc",
	code: "Code",
	data: "Data"
};
const CONCLUDE_LABEL = {
	approved: "approved",
	"changes-requested": "changes-requested",
	"in-progress": "in-progress"
};
/** 审批意见的稳定 key：doc 块=「路径#块key」（块 key 本身含内容哈希）；
*  code/data 文件=「种类:路径:内容哈希」——内容变 key 失效，旧意见自然「已过期」。 */
function entryKeyOf(file, block) {
	if (block !== void 0) return `${file.path}#${block.key}`;
	return `${file.kind}:${file.path}:${file.newHash}`;
}
/** 由一轮 review 生成可贴工单的返工指令（reject 意见即返工指令）。 */
function buildReworkInstruction(ticketId, round, roundNo) {
	const rejected = round.blocks.filter((b) => b.decision === "reject");
	const commented = round.blocks.filter((b) => b.decision !== "reject" && b.comment !== void 0 && b.comment !== "");
	const lines = [
		"## Rework instruction (PR-style review)",
		"",
		`- Ticket: ${ticketId}`,
		`- base: ${round.base || "(none)"}`,
		`- Round conclusion: ${round.conclude}`,
		`- Round #${roundNo} · ${round.reviewer} · ${fmtTs(round.ts)}`,
		`- Written to: server/reviews/${ticketId}.json`,
		""
	];
	if (rejected.length === 0 && commented.length === 0) lines.push("No rejected blocks.");
	else {
		if (rejected.length > 0) {
			lines.push(`### Rejected blocks (${rejected.length})`, "");
			rejected.forEach((b, i) => {
				lines.push(`${i + 1}. [${TYPE_LABEL[b.type] ?? b.type} / ${STATUS_LABEL[b.status] ?? b.status}] ${b.summary}`);
				if (b.comment !== void 0 && b.comment !== "") lines.push(`   - Comment: ${b.comment}`);
				lines.push(`   - key: \`${b.block_key}\``);
			});
		}
		if (commented.length > 0) {
			lines.push("", `### Other comments (${commented.length})`, "");
			commented.forEach((b, i) => {
				lines.push(`${i + 1}. [${TYPE_LABEL[b.type] ?? b.type}] ${b.summary} — ${b.comment ?? ""}`);
			});
		}
	}
	return lines.join("\n");
}
/** approve 摘要（随 sign 进不可变事件历史的 note）。 */
function buildApproveSummary(ticketId, file) {
	const n = file.rounds.length;
	if (n === 0) return "";
	const latest = file.rounds[n - 1];
	const a = latest.blocks.filter((b) => b.decision === "approve").length;
	const r = latest.blocks.filter((b) => b.decision === "reject").length;
	const c = latest.blocks.filter((b) => b.comment !== void 0 && b.comment !== "").length;
	return `Review round ${n}: conclude=${latest.conclude}, blocks approve ${a}/reject ${r}/commented ${c} (written to server/reviews/${ticketId}.json, reviewer ${latest.reviewer})`;
}
/** 渲染态 block diff 主视图（制式照 knowledge：未变渲染新文本；新增绿；删除红；修改上下红/绿；表格行单元格级对齐）。 */
function DiffBlockBody({ b }) {
	if (b.status === "unchanged") return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-d-md wb-md",
		dangerouslySetInnerHTML: { __html: renderMarkdown(b.newText ?? "") }
	});
	if (b.status === "added") return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-d-md wb-d-md-add wb-md",
		dangerouslySetInnerHTML: { __html: renderMarkdown(b.newText ?? "") }
	});
	if (b.status === "removed") return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-d-md wb-d-md-del wb-md",
		dangerouslySetInnerHTML: { __html: renderMarkdown(b.oldText ?? "") }
	});
	if (b.type === "table-row") {
		const oc = splitCells(b.oldText ?? "");
		const nc = splitCells(b.newText ?? "");
		const cols = Math.max(oc.length, nc.length);
		return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("table", {
			className: "wb-d-cells",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("thead", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { style: { width: 40 } }), Array.from({ length: cols }, (_, c) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("th", { children: ["Column ", c + 1] }, c))] }) }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tbody", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Old" }), Array.from({ length: cols }, (_, c) => {
				return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
					className: (oc[c] ?? "") !== (nc[c] ?? "") ? "wb-d-cell-old" : "",
					children: oc[c] ?? "—"
				}, c);
			})] }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "New" }), Array.from({ length: cols }, (_, c) => {
				return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
					className: (oc[c] ?? "") !== (nc[c] ?? "") ? "wb-d-cell-new" : "",
					children: nc[c] ?? "—"
				}, c);
			})] })] })]
		});
	}
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-d-md wb-d-md-old wb-md",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "wb-d-md-tag",
			children: "Old"
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", { dangerouslySetInnerHTML: { __html: renderMarkdown(b.oldText ?? "") } })]
	}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-d-md wb-d-md-new wb-md",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			className: "wb-d-md-tag",
			children: "New"
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", { dangerouslySetInnerHTML: { __html: renderMarkdown(b.newText ?? "") } })]
	})] });
}
/** unified diff 文本逐行着色（+绿/-红/@@蓝/头行灰）。 */
function UnifiedDiffView({ text }) {
	return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-d-uni",
		children: text.split("\n").map((l, i) => {
			return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-d-line",
				"data-k": l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : /^(diff |index |--- |\+\+\+ |new file|deleted file)/.test(l) ? "meta" : "ctx",
				children: l === "" ? " " : l
			}, i);
		})
	});
}
/** 数据前后值对账表。 */
function ReconTable({ recon }) {
	if (recon.length === 0) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-empty",
		children: "No structural diff (formatting/key order only, or no change)."
	});
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("table", {
		className: "wb-d-recon",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("thead", { children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "JSON path" }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Old" }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "New" }),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("th", { children: "Change" })
		] }) }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("tbody", { children: recon.map((e, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("tr", { children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
				"data-k": "path",
				children: e.path
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
				className: e.kind !== "added" ? "wb-d-old" : "",
				children: e.before ?? "—"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", {
				className: e.kind !== "removed" ? "wb-d-new" : "",
				children: e.after ?? "—"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("td", { children: e.kind === "added" ? "Added" : e.kind === "removed" ? "Removed" : "Changed" })
		] }, i)) })]
	});
}
/** 一块/一文件的审批意见动作条（approve/reject 切换 + 注释）。 */
function ReviewActions({ rv, onPatch }) {
	const decision = rv?.decision;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-d-actions",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				className: "wb-d-btn wb-d-btn-ap" + (decision === "approve" ? " on" : ""),
				onClick: () => onPatch({ decision: decision === "approve" ? void 0 : "approve" }),
				children: "Approve"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				className: "wb-d-btn wb-d-btn-rj" + (decision === "reject" ? " on" : ""),
				onClick: () => onPatch({
					decision: decision === "reject" ? void 0 : "reject",
					open: decision === "reject" ? rv?.open : true
				}),
				children: "Reject"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
				className: "wb-d-btn",
				onClick: () => onPatch({ open: !(rv?.open ?? false) }),
				children: rv?.open ? "Collapse comments" : rv?.comment ? "Comment ✎" : "Comment"
			}),
			decision !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: "wb-d-badge",
				"data-s": decision === "approve" ? "added" : "removed",
				children: decision === "approve" ? "Approved" : "Rejected"
			}),
			(rv?.open ?? false) && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
				className: "wb-d-cmt",
				placeholder: "Review comments (rejected-block comments become the rework instruction)",
				value: rv?.comment ?? "",
				onChange: (e) => onPatch({ comment: e.target.value })
			})
		]
	});
}
/** 「变更」页签本体：diff 展示 + 按块留意见 + 落盘 + 返工指令。 */
/** 构建产物判定：dsh 插件的 lib/ bundle 是编译生成物（minified 巨行 diff 没有审阅价值，
*  还会把真源码变更埋掉——260824 -03 实测），折叠成组默认收起。 */
function isGenArtifact(path) {
	return /^server\/dsh\/[^/]+\/lib\//.test(path);
}
/** unified diff 的 +/− 行数统计（跳过 +++/--- 头行）。 */
function unifiedStats(text) {
	let add = 0;
	let del = 0;
	for (const l of text.split("\n")) {
		if (l.startsWith("+++") || l.startsWith("---")) continue;
		if (l.startsWith("+")) add++;
		else if (l.startsWith("-")) del++;
	}
	return {
		add,
		del
	};
}
/** Decision card (design section 7.3): per state, what the list cannot show.
*  The queued position N comes from the engine concurrency read face
*  (GET /wf/concurrency parsed by queue-model; malformed or missing face means
*  no position — the card says plain 'Queued' and never invents a number).
*  Wording comes from the pure decisionCard model; null = no card at all.
*  Fetch teardown: unmount abort + dead flag, both paths covered. */
function DetailDecisionCardFace({ detail }) {
	const [pos, setPos] = (0, react.useState)(null);
	(0, react.useEffect)(() => {
		let dead = false;
		const ctl = new AbortController();
		(async () => {
			try {
				const j = await (await fetch(withProject(`${API}/concurrency`), { signal: ctl.signal })).json();
				if (dead) return;
				const face = parseConcFace(concFaceFromReply(j));
				if (!face) return;
				const i = face.queue.indexOf(detail.id);
				if (i >= 0) setPos(i + 1);
			} catch {}
		})();
		return () => {
			dead = true;
			ctl.abort();
		};
	}, [detail.id]);
	const card = decisionCard(detail, pos);
	if (!card) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-decide",
		"data-testid": "decision-card",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: card.title }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: card.body })]
	});
}
/** Column section 7: two columns (left = Timeline + Stage notes; right =
*  Receipts + Changes + Requests on this ticket). A block with no data renders
*  nothing (section 7.3: no empty scaffolding); all absent = no section at all.
*  The changes/requests read faces (diff face, executor-panel request ledger)
*  failing means that one box does not render — never an error frame, never a
*  stuck spinner (read errors are named by the collapsed changeset section). */
function DetailTwoColumns({ detail, projectKey }) {
	const [diff, setDiff] = (0, react.useState)(void 0);
	const [reqRows, setReqRows] = (0, react.useState)(void 0);
	(0, react.useEffect)(() => {
		let dead = false;
		(async () => {
			try {
				const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/diff`);
				if (!dead && r?.ok === true) setDiff(r.result);
			} catch {}
		})();
		return () => {
			dead = true;
		};
	}, [detail.id]);
	(0, react.useEffect)(() => {
		if (!projectKey) {
			setReqRows(void 0);
			return;
		}
		let dead = false;
		(async () => {
			try {
				const j = await (await fetch(`/sandbar-executor-panel/api/requests?project=${encodeURIComponent(projectKey)}`)).json();
				if (!dead && j?.ok === true) setReqRows(j.rows);
			} catch {}
		})();
		return () => {
			dead = true;
		};
	}, [projectKey, detail.id]);
	const tl = timelineRows(detail.timeline);
	const notes = stageNoteRows(detail);
	const receipts = receiptRows(detail.gate_runs);
	const changes = changeRows(diff, detail);
	const reqs = requestsForTicket(reqRows, detail.id);
	if (!tl && !notes && !receipts && !changes && !reqs) return null;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-detail-two",
		"data-testid": "detail-columns",
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-detail-col",
			children: [tl !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-panelbox",
				"data-testid": "detail-timeline",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "ttl",
					children: "Timeline"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("ul", {
					className: "wb-tl",
					children: tl.map((r, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "at",
						children: r.at ? fmtAt(r.at) : ""
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
						stageDisplayLabel(r.stage),
						r.state ? ` · ${STATE_LABEL[r.state] ?? r.state}` : "",
						r.reason ? ` · ${r.reason}` : ""
					] })] }, i))
				})]
			}), notes !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-panelbox",
				"data-testid": "detail-stage-notes",
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "ttl",
					children: "Stage notes"
				}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("ul", {
					className: "wb-tl",
					children: notes.map((r) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("li", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "at",
						children: stageDisplayLabel(r.stage)
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: r.note })] }, r.stage))
				})]
			})]
		}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-detail-col",
			children: [
				receipts !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-panelbox",
					"data-testid": "detail-receipts",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "ttl",
						children: "Receipts"
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-kv2",
						children: receipts.map((r) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-kv2-pair",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "k",
								children: r.k
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: r.v })]
						}, r.k + r.v))
					})]
				}),
				changes !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-panelbox",
					"data-testid": "detail-changes",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "ttl",
						children: "Changes"
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-kv2",
						children: changes.map((r) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-kv2-pair",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "k",
								children: r.k
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: r.v })]
						}, r.k))
					})]
				}),
				reqs !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-panelbox",
					"data-testid": "ticket-requests",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "ttl",
						children: "Requests on this ticket"
					}), reqs.map((r) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-req-lite",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("code", { children: ["#", String(r.id).slice(0, 4)] }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: String(r.question) })]
					}, String(r.id)))]
				})
			]
		})]
	});
}
/** Lazy fold shell: a closed <details> still mounts its children in the DOM, so
*  here children mount only once opened — keeping ChangesTab/AgentLogsTab's
*  original on-demand fetch semantics (borrowed-implementation discipline: the
*  fault modes stay unchanged). Once opened it stays mounted (review/scroll
*  state survives re-folding). */
function LazyFold({ label, testid, children }) {
	const [opened, setOpened] = (0, react.useState)(false);
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
		className: "wb-dfold",
		"data-testid": testid,
		onToggle: (e) => {
			if (e.target.open) setOpened(true);
		},
		children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: label }), opened && children]
	});
}
function ChangesTab({ detail, operator, onMsg, onOpenFile }) {
	const [diff, setDiff] = (0, react.useState)(void 0);
	const [loading, setLoading] = (0, react.useState)(true);
	const [loadErr, setLoadErr] = (0, react.useState)("");
	const [reviewFile, setReviewFile] = (0, react.useState)(void 0);
	const [reviews, setReviews] = (0, react.useState)({});
	const [expired, setExpired] = (0, react.useState)([]);
	const [conclude, setConclude] = (0, react.useState)("in-progress");
	const [saveState, setSaveState] = (0, react.useState)({});
	const [reworkMd, setReworkMd] = (0, react.useState)(void 0);
	const [copied, setCopied] = (0, react.useState)(false);
	const [showUnchanged, setShowUnchanged] = (0, react.useState)(false);
	(0, react.useEffect)(() => {
		let dead = false;
		(async () => {
			setLoading(true);
			setLoadErr("");
			try {
				const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/diff`);
				if (r?.ok !== true) throw new Error(r?.error ?? "diff read failed");
				if (dead) return;
				const d = r.result;
				setDiff(d);
				try {
					const rv = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/review`);
					if (rv?.ok === true && !dead) {
						const file = rv.result;
						setReviewFile(file);
						const latest = file.rounds.length > 0 ? file.rounds[file.rounds.length - 1] : void 0;
						if (latest !== void 0) {
							setConclude(latest.conclude);
							const currentKeys = /* @__PURE__ */ new Set();
							for (const f of d.files) {
								if (f.kind === "doc") for (const b of f.blocks ?? []) currentKeys.add(entryKeyOf(f, b));
								currentKeys.add(entryKeyOf(f));
							}
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
				if (!dead) setLoadErr(String(err instanceof Error ? err.message : err));
			} finally {
				if (!dead) setLoading(false);
			}
		})();
		return () => {
			dead = true;
		};
	}, [detail.id]);
	function patchReview(key, patch) {
		setReviews((prev) => ({
			...prev,
			[key]: {
				...prev[key],
				...patch
			}
		}));
	}
	/** 保存一轮审批意见（显式落盘），成功后生成返工指令。 */
	async function saveReview() {
		if (diff === void 0) return;
		setSaveState({ saving: true });
		setReworkMd(void 0);
		try {
			const blocks = [];
			for (const f of diff.files) if (f.kind === "doc") for (const b of (f.blocks ?? []).filter((x) => x.status !== "unchanged")) {
				const key = entryKeyOf(f, b);
				blocks.push({
					block_key: key,
					summary: `${f.path}: ${b.summary}`,
					type: b.type,
					status: b.status,
					decision: reviews[key]?.decision,
					comment: reviews[key]?.comment
				});
			}
			else {
				const key = entryKeyOf(f);
				blocks.push({
					block_key: key,
					summary: f.path,
					type: f.kind,
					status: f.status,
					decision: reviews[key]?.decision,
					comment: reviews[key]?.comment
				});
			}
			const r = await apiPost(`${API}/tickets/${encodeURIComponent(detail.id)}/review`, {
				base: diff.base,
				conclude,
				reviewer: operator,
				blocks
			});
			if (r?.ok !== true) throw new Error(r?.error ?? "save failed");
			const round = r.result?.round;
			const rounds = Number(r.result?.rounds ?? 0);
			setSaveState({ runId: String(r.run_id ?? "") });
			setReviewFile((prev) => ({
				path: detail.id,
				rounds: [...prev?.rounds ?? [], round]
			}));
			setReworkMd(buildReworkInstruction(detail.id, round, rounds));
			onMsg(`Review saved (round ${rounds}, run_id ${String(r.run_id ?? "")})`);
		} catch (err) {
			setSaveState({ error: String(err instanceof Error ? err.message : err) });
		}
	}
	async function copyText(text) {
		setCopied(false);
		try {
			await navigator.clipboard.writeText(text);
			setCopied(true);
		} catch {
			const ta = document.createElement("textarea");
			ta.value = text;
			document.body.appendChild(ta);
			ta.select();
			try {
				document.execCommand("copy");
				setCopied(true);
			} catch {}
			document.body.removeChild(ta);
		}
	}
	if (loading) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-empty",
		children: "Computing changeset (git diff)…"
	});
	if (loadErr !== "") return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-err",
		children: ["Changeset load failed: ", loadErr]
	});
	if (diff === void 0) return null;
	const latestRound = reviewFile !== void 0 && reviewFile.rounds.length > 0 ? reviewFile.rounds[reviewFile.rounds.length - 1] : void 0;
	const summary = {
		doc: diff.files.filter((f) => f.kind === "doc").length,
		code: diff.files.filter((f) => f.kind === "code").length,
		data: diff.files.filter((f) => f.kind === "data").length,
		approved: Object.values(reviews).filter((r) => r.decision === "approve").length,
		rejected: Object.values(reviews).filter((r) => r.decision === "reject").length
	};
	const realFiles = diff.files.filter((f) => !isGenArtifact(f.path));
	const genFiles = diff.files.filter((f) => isGenArtifact(f.path));
	const sourceLabel = diff.source === "worktree" ? "lane worktree vs base" : diff.source === "merged" ? "merged into main (merge commit replay)" : diff.source === "main" ? "main tree write_set + git log" : "no source";
	const renderFile = (f) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-d-file",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-d-fhead",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-d-badge",
						"data-s": f.status,
						children: STATUS_LABEL[f.status]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-d-type",
						children: KIND_LABEL[f.kind]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-d-fpath wb-d-flink",
						title: "Open read-only as of this ticket",
						onClick: () => onOpenFile(f.path, "settle"),
						children: f.path
					}),
					f.kind === "code" && f.unified !== void 0 && (() => {
						const st = unifiedStats(f.unified);
						return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-d-stats",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "add",
									children: ["+", st.add]
								}),
								" ",
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "del",
									children: ["−", st.del]
								})
							]
						});
					})()
				]
			}),
			f.kind === "doc" && (f.blocks ?? []).filter((b) => showUnchanged || b.status !== "unchanged").map((b) => {
				const key = entryKeyOf(f, b);
				return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-d-block",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-d-bhead",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-d-badge",
									"data-s": b.status,
									children: STATUS_LABEL[b.status]
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-d-type",
									children: TYPE_LABEL[b.type] ?? b.type
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-sub",
									children: b.summary
								})
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(DiffBlockBody, { b }),
						b.status !== "unchanged" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ReviewActions, {
							rv: reviews[key],
							onPatch: (p) => patchReview(key, p)
						})
					]
				}, key);
			}),
			f.kind === "code" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
				f.unifiedTruncated === true && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-d-trunc",
					children: "Diff truncated (full diff in lane git)."
				}),
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)(UnifiedDiffView, { text: f.unified ?? "(no unified diff)" }),
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ReviewActions, {
					rv: reviews[entryKeyOf(f)],
					onPatch: (p) => patchReview(entryKeyOf(f), p)
				})
			] }),
			f.kind === "data" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
				f.reconTruncated === true && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-d-trunc",
					children: "Reconciliation entries truncated (over cap)."
				}),
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ReconTable, { recon: f.recon ?? [] }),
				/* @__PURE__ */ (0, react_jsx_runtime.jsx)(ReviewActions, {
					rv: reviews[entryKeyOf(f)],
					onPatch: (p) => patchReview(entryKeyOf(f), p)
				})
			] })
		]
	}, f.path);
	const renderRepoSection = (r) => {
		const prefix = r.repo === "" ? "" : r.repo + "/";
		return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-d-repo",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-d-repohead",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-d-fpath",
						children: r.repo === "" ? "root repo" : r.repo
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "wb-sub",
						children: [
							r.name,
							" · ",
							r.branch
						]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["base: ", /* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", { children: r.base === "" ? "(none)" : r.base.slice(0, 12) })] }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
						"Files ",
						r.files.length,
						r.filesTruncated ? " (truncated)" : ""
					] }),
					r.emptyReason !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-sub",
						children: r.emptyReason
					}),
					r.excludedCount !== void 0 && r.excludedCount > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						style: { color: "var(--dsw-derive-muted,#57606a)" },
						children: [
							"Excluded ",
							r.excludedCount,
							" process artifacts",
							r.excludedPaths !== void 0 && r.excludedPaths.length > 0 ? `: ${r.excludedPaths.join(", ")}` : ""
						]
					})
				]
			}), r.files.map((f) => renderFile({
				...f,
				path: prefix + f.path
			}))]
		}, r.repo || "(root)");
	};
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
		/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-section",
			children: [
				/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-section-title",
					children: [
						"Changeset (",
						sourceLabel,
						")"
					]
				}),
				/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-d-sum",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
							diff.source === "merged" ? "merge" : "base",
							": ",
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", { children: diff.base === "" ? "(none)" : diff.base.slice(0, 12) })
						] }),
						diff.worktree !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: ["Worktree: ", shortSlug(diff.worktree)] }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
							"Files ",
							diff.files.length,
							diff.filesTruncated ? " (truncated)" : "",
							" (docs ",
							summary.doc,
							" / code ",
							summary.code,
							" / data ",
							summary.data,
							")"
						] }),
						diff.excludedEngineFiles !== void 0 && diff.excludedEngineFiles > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							style: { color: "var(--dsw-derive-muted,#57606a)" },
							children: [
								"Excluded ",
								diff.excludedEngineFiles,
								" engine process artifacts",
								diff.excludedPaths !== void 0 && diff.excludedPaths.length > 0 ? `: ${diff.excludedPaths.join(", ")}${diff.excludedPaths.length < diff.excludedEngineFiles ? "…" : ""}` : ""
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
							"Review: approve ",
							summary.approved,
							" / reject ",
							summary.rejected
						] }),
						latestRound !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
							"Saved ",
							reviewFile.rounds.length,
							" rounds (latest: ",
							CONCLUDE_LABEL[latestRound.conclude] ?? latestRound.conclude,
							" · ",
							latestRound.reviewer,
							" · ",
							fmtTs(latestRound.ts),
							")"
						] })
					]
				}),
				diff.emptyReason !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: "wb-empty",
					children: diff.emptyReason
				}),
				diff.files.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("label", {
					style: {
						fontSize: 12,
						color: "var(--dsw-derive-muted,#57606a)"
					},
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("input", {
						type: "checkbox",
						checked: showUnchanged,
						onChange: (e) => setShowUnchanged(e.target.checked)
					}), " Show unchanged doc blocks"]
				})
			]
		}),
		diff.repos !== void 0 ? diff.repos.map(renderRepoSection) : realFiles.map(renderFile),
		genFiles.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
			className: "wb-d-gen",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("summary", { children: [
				"Build artifacts (",
				genFiles.length,
				") — compiled lib/ bundles, regenerated from source, normally no need to review"
			] }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-d-gen-list",
				children: genFiles.map((f) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-d-gen-row",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-d-badge",
							"data-s": f.status,
							children: STATUS_LABEL[f.status]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "p",
							children: f.path
						}),
						f.unified !== void 0 && (() => {
							const st = unifiedStats(f.unified);
							return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
								className: "wb-d-stats",
								children: [
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "add",
										children: ["+", st.add]
									}),
									" ",
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
										className: "del",
										children: ["−", st.del]
									})
								]
							});
						})()
					]
				}, f.path))
			})]
		}),
		diff.files.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-section",
			children: [
				/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-section-title",
					children: [
						"Review (written to server/reviews/",
						detail.id,
						".json)"
					]
				}),
				/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-ops",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("select", {
							className: "wb-d-conclude",
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
							className: "wb-btn wb-btn-blue",
							disabled: saveState.saving === true,
							onClick: () => {
								saveReview();
							},
							children: saveState.saving === true ? "Saving…" : "Save review (one round)"
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "wb-btn",
							disabled: reviewFile === void 0 || reviewFile.rounds.length === 0,
							title: "reject comments become the rework instruction; copy into the ticket/rework reason",
							onClick: () => {
								const file = reviewFile;
								if (file === void 0 || file.rounds.length === 0) return;
								copyText(buildReworkInstruction(detail.id, file.rounds[file.rounds.length - 1], file.rounds.length));
							},
							children: copied ? "Copied ✓" : "Copy rework instruction"
						}),
						saveState.runId !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: "wb-copied",
							children: ["saved ✓ run_id ", saveState.runId]
						}),
						saveState.error !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-err",
							children: saveState.error
						})
					]
				}),
				expired.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-d-expired",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						style: {
							fontWeight: 600,
							marginBottom: 4
						},
						children: [
							"Expired comments (",
							expired.length,
							") — block/file content changed, key no longer valid, not backfilled:"
						]
					}), expired.map((eb, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-d-expired-item",
						children: [
							/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-d-badge",
								"data-s": "expired",
								children: "Expired"
							}),
							" ",
							"[",
							TYPE_LABEL[eb.type] ?? eb.type,
							"] ",
							eb.summary,
							eb.comment !== void 0 && eb.comment !== "" && ` — ${eb.comment}`
						]
					}, i))]
				}),
				reworkMd !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-d-rework",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-sub",
							children: "Rework instruction (generated on save; rejected-block list, paste into ticket)"
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", { children: reworkMd }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ops",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: () => {
									copyText(reworkMd);
								},
								children: copied ? "Copied ✓" : "Copy"
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: () => setReworkMd(void 0),
								children: "Collapse"
							})]
						})
					]
				})
			]
		})
	] });
}
/** 「Agent」页签：.suyou/ 的 agent_*.log + stage_*.json 按工作流步序分组——
*  每步一张卡，里面按 gen 列每次尝试（状态+摘要一行，展开看日志/结果/prompt）。
*  260824 二轮：原来是按文件名字母序平铺（步序丢失、log/result 拆两行），不可用。 */
function AgentLogsTab({ detail, wf, onMsg }) {
	const [logs, setLogs] = (0, react.useState)(void 0);
	const [loading, setLoading] = (0, react.useState)(true);
	const [loadErr, setLoadErr] = (0, react.useState)("");
	const [promptOpen, setPromptOpen] = (0, react.useState)({});
	(0, react.useEffect)(() => {
		let dead = false;
		(async () => {
			setLoading(true);
			setLoadErr("");
			try {
				const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/agent-logs`);
				if (r?.ok !== true) throw new Error(r?.error ?? "agent log read failed");
				if (dead) return;
				setLogs(r.result);
				if (r.result?.reason !== void 0 && r.result?.reason !== "") onMsg(String(r.result.reason));
			} catch (err) {
				if (!dead) setLoadErr(String(err instanceof Error ? err.message : err));
			} finally {
				if (!dead) setLoading(false);
			}
		})();
		return () => {
			dead = true;
		};
	}, [detail.id]);
	if (loadErr !== "") return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-err",
		children: ["Agent log load failed: ", loadErr]
	});
	if (loading) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-empty",
		children: "Loading agent logs…"
	});
	if (logs === void 0) return null;
	const byStage = /* @__PURE__ */ new Map();
	for (const f of logs.files) {
		const arr = byStage.get(f.stage) ?? [];
		let at = arr.find((a) => a.gen === f.gen);
		if (at === void 0) {
			at = { gen: f.gen };
			arr.push(at);
		}
		if (f.kind === "log") at.log = f;
		else at.result = f;
		byStage.set(f.stage, arr);
	}
	const wfOrder = wf?.stages.map((s) => s.id) ?? [];
	const stageName = (id) => stageDisplayLabel(id, wf?.stages.find((s) => s.id === id)?.name);
	const stageIds = [...byStage.keys()].sort((a, b) => {
		const ia = wfOrder.indexOf(a);
		const ib = wfOrder.indexOf(b);
		if (ia >= 0 && ib >= 0) return ia - ib;
		if (ia >= 0) return -1;
		if (ib >= 0) return 1;
		return a < b ? -1 : 1;
	});
	const lastStage = stageIds[stageIds.length - 1];
	const lastGen = lastStage !== void 0 ? Math.max(...(byStage.get(lastStage) ?? []).map((a) => a.gen)) : -1;
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-section",
		children: [
			/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-section-title",
				children: "Agent logs (.suyou/)"
			}),
			/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-al-meta",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "wb-meta-k",
						children: logs.base
					}),
					logs.agentAlive && logs.sessionKb > 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						style: { color: "var(--dsw-derive-accent,#0969da)" },
						children: [
							"agent running · read ",
							logs.sessionKb,
							"KB",
							logs.lastActivity ? " · " + logs.lastActivity : ""
						]
					}) : null,
					logs.sessionNote ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						style: { color: "var(--dsw-derive-danger,#cf222e)" },
						children: ["⚠ ", logs.sessionNote]
					}) : null,
					logs.exists ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
						logs.files.length,
						" files",
						logs.truncated ? ` (over cap, truncated)` : ""
					] }) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: logs.reason ?? "directory missing" }),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-btn",
						disabled: loading,
						onClick: () => {
							(async () => {
								setLoading(true);
								try {
									const r = await apiGet(`${API}/tickets/${encodeURIComponent(detail.id)}/agent-logs`);
									if (r?.ok === true) {
										setLogs(r.result);
										onMsg("Refreshed");
									}
								} finally {
									setLoading(false);
								}
							})();
						},
						children: "Refresh"
					})
				]
			}),
			logs.files.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-empty",
				children: [
					"No agent log / stage result files (",
					logs.reason ?? "directory empty",
					")."
				]
			})
		]
	}), stageIds.map((stageId) => {
		const attempts = (byStage.get(stageId) ?? []).sort((a, b) => a.gen - b.gen);
		const vis = d2StageVisual(detail, stageId, wfOrder);
		const lastMtime = Math.max(0, ...attempts.flatMap((a) => [a.log?.mtime ?? 0, a.result?.mtime ?? 0]));
		return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
			className: "wb-al-stage",
			children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-al-shead",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {
						className: "ico",
						style: { color: D2_COLOR[vis] },
						children: D2_ICON[vis]
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: "nm",
						children: stageName(stageId)
					}),
					/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
						className: "meta",
						children: [
							attempts.length,
							" attempts",
							lastMtime > 0 ? ` · latest ${fmtTs(lastMtime)}` : ""
						]
					})
				]
			}), attempts.map((a) => {
				const r = a.result !== void 0 && typeof a.result.result === "object" && a.result.result !== null ? a.result.result : void 0;
				const status = r !== void 0 ? String(r.status ?? "ok") : "no result";
				const summary = typeof r?.summary === "string" ? r.summary : "";
				const pkey = `${stageId}:${a.gen}`;
				return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
					className: "wb-al-attempt",
					open: stageId === lastStage && a.gen === lastGen,
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("summary", { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-al-status",
							"data-ok": status !== "failed",
							children: status
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
							"Attempt ",
							a.gen + 1,
							" (gen",
							a.gen,
							")"
						] }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "wb-al-fmeta",
							children: fmtTs(a.result?.mtime ?? a.log?.mtime ?? 0)
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: "sum",
							children: summary
						})
					] }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-al-body",
						children: [
							r !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "wb-al-result-sum",
									children: [
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
												className: "wb-al-result-key",
												children: "deliverables"
											}),
											" ",
											Array.isArray(r.deliverables) ? r.deliverables.length : "—"
										] }),
										/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
												className: "wb-al-result-key",
												children: "files_changed"
											}),
											" ",
											Array.isArray(r.files_changed) ? r.files_changed.length : "—"
										] }),
										Array.isArray(r.files_changed) && r.files_changed.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
											style: { wordBreak: "break-all" },
											children: r.files_changed.map(String).join(", ")
										})
									]
								}),
								summary !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-al-summ",
									children: summary
								}),
								Array.isArray(r.deliverables) && r.deliverables.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-al-summ",
									children: r.deliverables.map(String).map((d, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "wb-chip",
										children: d
									}, i))
								}),
								typeof r.prompt === "string" && r.prompt !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									style: { marginTop: 6 },
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "wb-d-btn",
										onClick: () => setPromptOpen((o) => ({
											...o,
											[pkey]: !o[pkey]
										})),
										children: promptOpen[pkey] ? "Hide injected prompt ▲" : "View injected prompt ▼"
									}), promptOpen[pkey] && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
										className: "wb-al-pre",
										style: {
											maxHeight: 360,
											marginTop: 4
										},
										children: r.prompt
									})]
								})
							] }),
							a.result?.parseError !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "wb-al-summ",
								children: a.result.parseError
							}),
							a.log !== void 0 && a.log.content !== void 0 && a.log.content.trim() !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "wb-al-result-key",
									style: { padding: "6px 12px 0" },
									children: [
										"Agent output tail (",
										a.log.name,
										")"
									]
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
									className: "wb-al-pre",
									children: a.log.content
								}),
								a.log.contentTruncated === true && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
									className: "wb-al-trunc",
									children: [
										"Content truncated (full content in lane .suyou/",
										a.log.name,
										")."
									]
								})
							] }),
							a.result === void 0 && a.log === void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "wb-empty",
								children: "Failed to read content."
							})
						]
					})]
				}, a.gen);
			})]
		}, stageId);
	})] });
}
function WorkbenchSection({ focusId, focusNonce, listNonce, projectKey }) {
	const [tickets, setTickets] = (0, react.useState)(void 0);
	const [workflows, setWorkflows] = (0, react.useState)([]);
	const [operator] = (0, react.useState)(operatorOf);
	const [error, setError] = (0, react.useState)("");
	const inspectionRowsRef = (0, react.useRef)([]);
	const [inspectionNote, setInspectionNote] = (0, react.useState)("");
	const [selectedId, setSelectedId] = (0, react.useState)(null);
	const [overlayNav, setOverlayNav] = (0, react.useState)(EMPTY_OVERLAY);
	const [detail, setDetail] = (0, react.useState)(void 0);
	const [detailLoading, setDetailLoading] = (0, react.useState)(false);
	const [opBusy, setOpBusy] = (0, react.useState)(false);
	const [opMsg, setOpMsg] = (0, react.useState)("");
	/** t260919-02 终态失败面视图：openDetail 捕获 terminal 回执的 face 后装配；
	*  切单/重开/关抽屉即清（openDetail 开头 + 关闭钮兜底），绝不串票。 */
	const [terminalFace, setTerminalFace] = (0, react.useState)(null);
	const [promptBox, setPromptBox] = (0, react.useState)(null);
	const [reworkId, setReworkId] = (0, react.useState)(null);
	const [reworkHuman, setReworkHuman] = (0, react.useState)(false);
	const [reworkNote, setReworkNote] = (0, react.useState)("");
	const [reworkTo, setReworkTo] = (0, react.useState)("");
	/** KI-004：approve 签字弹层。summary=自动统计摘要（只读，''=无已存审批意见），
	*  epicLine=所属立项确认行（''=不显示）。 */
	const [approveBox, setApproveBox] = (0, react.useState)(null);
	const [approveRemark, setApproveRemark] = (0, react.useState)("");
	/** approve 摘要 fetch 的请求序号：迟到回调若与当前弹层不同批，丢弃不误写。 */
	const approveSeqRef = (0, react.useRef)(0);
	const [copied, setCopied] = (0, react.useState)(false);
	const [preview, setPreview] = (0, react.useState)(void 0);
	const [fileViewer, setFileViewer] = (0, react.useState)(null);
	const [previewLoading, setPreviewLoading] = (0, react.useState)(false);
	/** token 消耗聚合（t260828-07）：详情抽屉打开时拉一次，头部合计与阶段行内数字共用。 */
	const usage = useAgentUsage(detail?.id ?? "", detail !== void 0);
	/** 本页签 presence 句柄：挂载即建、卸载 stop（effect 清理收口，见下）。 */
	const presenceRef = (0, react.useRef)(null);
	/** selectedId 的 ref 镜像：异步回调（轮询响应/远端写事件）按发起时刻校验，
	*  旧选中工单的在途响应不得覆盖新选中的详情——「点 13 跳回 11」竞态守卫。 */
	const selectedIdRef = (0, react.useRef)(null);
	/** 远端页签刚对本页签在看的工单做过写操作 → 顶部黄条（× 关闭，下一条覆盖）。 */
	const [peerNote, setPeerNote] = (0, react.useState)("");
	/** 1s tick：驱动 👀 徽标/在看提示随心跳 TTL 刷新（纯本地渲染，不发请求）。 */
	const [, setViewerTick] = (0, react.useState)(0);
	/** 轮询健康度（KI-003③ 优雅降级，t260903-06）：连续失败计数 + 错误态。
	*  ref 镜像供异步回调读最新值（setState 异步，回调内直读 state 拿旧值）。 */
	const [pollHealth, setPollHealth] = (0, react.useState)(INITIAL_POLL_STATE);
	const pollHealthRef = (0, react.useRef)(INITIAL_POLL_STATE);
	/** 最近一次轮询失败的摘要（角标 title / 错误条附注；成功即清）。 */
	const [pollLastError, setPollLastError] = (0, react.useState)("");
	/** in-flight 守卫（review C6）：RUNNING 查询退避后最坏 ~27.5s 未归，5s 节拍
	*  若不设守卫会同票并发堆叠——正是 KI-003 登记的「多页签轮询风暴」共犯路径，
	*  本票 UI 段不得放大它。上一发未归 → 跳过本拍。 */
	const listInFlight = (0, react.useRef)(false);
	const detailInFlight = (0, react.useRef)(false);
	/** 健康度转移唯一写入口：ref 与 state 同步；恢复（ok）清错误条。 */
	function applyPollOutcome(outcome, errMsg = "") {
		const next = nextPollState(pollHealthRef.current, outcome);
		pollHealthRef.current = next;
		setPollHealth(next);
		setPollLastError(errMsg);
		if (outcome === "ok") setError("");
		else if (next.degraded) setError(outcome === "retryable" ? `Board refresh failed ${next.failStreak}× in a row; data may be stale. Switched to slow auto-retry — no manual refresh needed. Last error: ${errMsg}` : `Selected ticket not queryable (missing or terminal) — see detail panel note; other tickets may be stale.`);
	}
	const wfById = (0, react.useMemo)(() => {
		const m = {};
		for (const w of workflows) m[w.id] = w;
		return m;
	}, [workflows]);
	/** 台面列表拉取：返回本拍分类供 pollOnce 记账。失败保留上次成功快照
	*  （不清 tickets/workflows——「保持上次成功快照」是本票硬口径）。 */
	async function reloadTickets() {
		listInFlight.current = true;
		try {
			const [data, insp] = await Promise.all([apiGet(`${API}/tickets`), apiGet(INSPECTION_TICKETS_URL).catch(() => void 0)]);
			if (data?.ok !== true) throw new Error(data?.error ?? "board load failed");
			const baseRows = data.result?.tickets ?? [];
			if (insp?.ok === true) {
				inspectionRowsRef.current = insp.result?.tickets ?? [];
				const f = insp.result?.inspection_filter;
				setInspectionNote(f?.degraded ? String(f.note ?? "inspection panel degraded") : "");
			} else setInspectionNote("inspection panel fetch failed; showing last snapshot (auto-retrying)");
			setTickets([...baseRows, ...inspectionRowsRef.current]);
			setWorkflows(data.workflows ?? []);
			return "ok";
		} catch (err) {
			return "retryable";
		} finally {
			listInFlight.current = false;
		}
	}
	/** 一拍轮询（健康度唯一入账口）：列表 + 打开中的详情，取最坏分类。
	*  in-flight 守卫在此收口：上一发未归整拍跳过（不记账不叠加）。 */
	async function pollOnce() {
		if (listInFlight.current || detailInFlight.current) return;
		const detailOpen = selectedIdRef.current !== null;
		const [listOut, detailOut] = await Promise.all([reloadTickets(), detailOpen ? refreshDetailSilent() : Promise.resolve("ok")]);
		const out = worstOutcome(listOut, detailOut);
		applyPollOutcome(out, out === "ok" ? "" : "snapshot query transient failure (stage switch window?)");
	}
	(0, react.useEffect)(() => {
		setViewProject(projectKey ?? "");
		setTickets(void 0);
		if (getViewProject()) pollOnce();
	}, [projectKey]);
	(0, react.useEffect)(() => {
		if (focusId) openTicketOverlay(focusId);
	}, [focusId, focusNonce]);
	const listNonceRef = (0, react.useRef)(listNonce);
	(0, react.useEffect)(() => {
		if (listNonceRef.current === listNonce) return;
		listNonceRef.current = listNonce;
		selectedIdRef.current = null;
		setSelectedId(null);
		setOverlayNav(EMPTY_OVERLAY);
		setDetail(void 0);
	}, [listNonce]);
	(0, react.useEffect)(() => {
		const p = startTabPresence(operator);
		presenceRef.current = p;
		const unsub = p.onRemoteWrite((w) => {
			if (selectedIdRef.current !== null && w.ticket === selectedIdRef.current) {
				setPeerNote(`Ticket ${w.ticket} was just operated from another tab (${w.op} · ${w.who}); auto-refreshed`);
				pollOnce();
			}
		});
		const stopTick = startVisibleInterval(() => {
			setViewerTick((t) => t + 1);
		}, 1e3);
		return () => {
			unsub();
			stopTick();
			p.stop();
			presenceRef.current = null;
		};
	}, [operator]);
	(0, react.useEffect)(() => {
		selectedIdRef.current = selectedId;
		presenceRef.current?.setViewingTicket(selectedId);
	}, [selectedId]);
	async function openDetail(id) {
		selectedIdRef.current = id;
		setSelectedId(id);
		setDetailLoading(true);
		setOpMsg("");
		setTerminalFace(null);
		try {
			const data = await apiGet(`${API}/tickets/${encodeURIComponent(id)}`);
			if (data?.ok !== true) {
				const e = new Error(data?.error ?? "detail load failed");
				e.kind = data?.kind;
				e.face = data?.face;
				throw e;
			}
			if (selectedIdRef.current !== id) return;
			setDetail(data.result);
		} catch (err) {
			if (selectedIdRef.current === id) {
				const kind = err?.kind;
				if (kind === "not_found") setOpMsg(`Ticket not found: ${id} (no such Temporal workflow)`);
				else if (kind === "terminal") {
					setTerminalFace(terminalFaceView(err?.face, err instanceof Error ? err.message : String(err)));
					setOpMsg(String(err instanceof Error ? err.message : err));
				} else setOpMsg(`Detail load failed (transient query error), retrying: ${String(err instanceof Error ? err.message : err)}`);
			}
		} finally {
			if (selectedIdRef.current === id) setDetailLoading(false);
		}
	}
	/** Click a row in the list/board: overlay content = ticket detail, no breadcrumb (the model is inert on malformed ids: no state change). */
	function openTicketOverlay(id) {
		setOverlayNav((nav) => openTicket(nav, id));
		openDetail(id);
	}
	/** Click the epic badge inside a ticket detail: same layer, content becomes the epic detail (the source ticket id stays in selectedId, but the crumb records the epic code — the breadcrumb goes back to the epic, not the ticket). */
	function drillOverlayToEpic(code) {
		setOverlayNav((nav) => drillToEpic(nav, code));
	}
	/** Click a ticket row inside the epic detail: same layer, content becomes the ticket detail; crumb = that epic (the model is inert on a malformed code). */
	function drillOverlayToTicket(id, epicCode) {
		setOverlayNav((nav) => drillToTicketFromEpic(nav, id, epicCode));
		openDetail(id);
	}
	/** The `← code` breadcrumb: same layer, back to the epic detail. */
	function overlayBreadcrumbBack() {
		setOverlayNav((nav) => breadcrumbBack(nav));
	}
	/** ×/Esc: close the overlay all the way — epic content and crumb are cleared together; the underlying view is exactly as it was. */
	function closeTicketOverlay() {
		selectedIdRef.current = null;
		setSelectedId(null);
		setOverlayNav((nav) => closeOverlay(nav));
		setDetail(void 0);
		setTerminalFace(null);
	}
	/** ArrowUp/Down ticket walk (only while the overlay is open; no walk in the epic content state — the list-walk semantics apply to the ticket detail only).
	*  A walk = a fresh open from the list context: the crumb is cleared (an arrow jump carries no epic origin). */
	function overlayStepTicket(dir) {
		const next = neighborTicketId(tickets, selectedIdRef.current, dir);
		if (next === null || next === selectedIdRef.current) return;
		setOverlayNav((nav) => openTicket(nav, next));
		openDetail(next);
	}
	(0, react.useEffect)(() => {
		if (!(selectedId !== null || overlayNav.current !== null)) return;
		const onKey = (ev) => {
			if (ev.key === "Escape") {
				ev.preventDefault();
				closeTicketOverlay();
			} else if (ev.key === "ArrowUp") {
				ev.preventDefault();
				overlayStepTicket("up");
			} else if (ev.key === "ArrowDown") {
				ev.preventDefault();
				overlayStepTicket("down");
			}
		};
		window.addEventListener("keydown", onKey);
		return () => {
			window.removeEventListener("keydown", onKey);
		};
	}, [
		selectedId !== null || overlayNav.current !== null,
		selectedId,
		overlayNav.current,
		tickets
	]);
	/** t260901-15 写前守门：远端页签守门窗口内写过该工单、或正有其它页签在看 →
	*  confirm 二次确认（管理台宁提醒不强禁，写后广播兑现读后失效）。返回 true=可继续写。
	*  在场通道不可用（presenceRef=null）→ 退化为旧行为不阻断，降级写明不静默。 */
	function peerWriteAllowed(id, op) {
		const p = presenceRef.current;
		if (p === null) return true;
		const hit = p.recentRemoteWrite(id);
		const viewers = p.viewersOf(id);
		if (hit === void 0 && viewers.length === 0) return true;
		const lines = [];
		if (hit !== void 0) lines.push(`Another tab (${hit.who}) ran "${hit.op}" on this ticket ${Math.max(1, Math.round(hit.ageMs / 1e3))}s ago`);
		if (viewers.length > 0) lines.push(`Another tab is viewing this ticket (${viewers.map((v) => v.who).join(", ")})`);
		return window.confirm(`Continue "${op}" on ticket ${id}?\n${lines.join("\n")}`);
	}
	async function doOp(id, op, args, msgOk) {
		if (!peerWriteAllowed(id, op)) {
			setOpMsg("Cancelled: another tab just operated this ticket");
			return;
		}
		setOpBusy(true);
		setOpMsg("");
		try {
			const data = await apiPost(`${API}/tickets/${encodeURIComponent(id)}/${op}`, args);
			if (data?.ok !== true) {
				setOpMsg(`Failed: ${data?.error ?? "unknown error"}${data?.run_id ? ` (run_id ${data.run_id})` : ""}`);
				return;
			}
			const result = data.result;
			if (op === "dispatch-next") setPromptBox({
				role: result?.role ?? "",
				stage: result?.stage ?? "",
				prompt: result?.prompt ?? ""
			});
			setOpMsg(msgOk + (data.run_id ? ` (run_id ${data.run_id})` : ""));
			presenceRef.current?.notifyWrite(id, op);
			await Promise.all([reloadTickets(), ...id === selectedId ? [openDetail(id)] : []]);
		} catch (err) {
			setOpMsg(`Operation failed: ${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setOpBusy(false);
		}
	}
	/** 读工单审批意见（server/reviews/<id>.json；没有=undefined，不报错）。 */
	async function fetchReviewFile(id) {
		try {
			const r = await apiGet(`${API}/tickets/${encodeURIComponent(id)}/review`);
			if (r?.ok === true) return r.result;
		} catch {}
	}
	function doAdvance(id, stageState, epic) {
		if (stageState === "awaiting-human") {
			const code = (epic ?? "").trim();
			const epicLine = code !== "" ? `Epic: ${code}` : "";
			const seq = ++approveSeqRef.current;
			(async () => {
				const file = await fetchReviewFile(id);
				if (approveSeqRef.current !== seq) return;
				const summary = file !== void 0 ? buildApproveSummary(id, file) : "";
				setApproveBox({
					id,
					summary,
					epicLine
				});
				setApproveRemark("");
			})();
			return;
		}
		doOp(id, "advance", {}, "Advanced to next stage");
	}
	function doSign(id, decision, note, gate) {
		doOp(id, "sign", gate ? {
			decision,
			note,
			who: operator,
			gate
		} : {
			decision,
			note,
			who: operator
		}, decision === "approve" ? "Approved and advanced" : "Rework requested (sign reject)");
	}
	/** KI-004 approve 弹层确认：同 doRework 口径——先复位弹层 state 再签字，
	*  失败信息由 doOp 的 setOpMsg 外露；buildApproveNote 兜底 remark 可空。 */
	function doApprove() {
		if (!approveBox) return;
		const { id, summary } = approveBox;
		const note = buildApproveNote(summary, approveRemark);
		setApproveBox(null);
		setApproveRemark("");
		doSign(id, "approve", note);
	}
	/** KI-004 approve 弹层取消：四路径（确认/取消/Esc 外点/换单重开）统一走这里复位。 */
	function closeApprove() {
		approveSeqRef.current++;
		setApproveBox(null);
		setApproveRemark("");
	}
	/** 打开打回弹层。M9 签字联动：有已存审批意见且含驳回/注释时，自动把返工指令填进理由框（可改）。 */
	function openRework(id, human) {
		setReworkId(id);
		setReworkHuman(human);
		setOpMsg("");
		(async () => {
			const file = await fetchReviewFile(id);
			if (file === void 0 || file.rounds.length === 0) return;
			const latest = file.rounds[file.rounds.length - 1];
			if (latest.blocks.some((b) => b.decision === "reject" || (b.comment ?? "") !== "")) setReworkNote((prev) => prev === "" ? buildReworkInstruction(id, latest, file.rounds.length) : prev);
		})();
	}
	function doRework() {
		if (!reworkId) return;
		if (reworkNote.trim() === "") {
			setOpMsg("Rework reason required");
			return;
		}
		if (reworkHuman) doSign(reworkId, "reject", reworkNote);
		else doOp(reworkId, "rework", {
			note: reworkNote,
			...reworkTo ? { to_stage: reworkTo } : {}
		}, "Rework requested");
		setReworkNote("");
		setReworkTo("");
		setReworkId(null);
		setReworkHuman(false);
	}
	async function copyPrompt(text) {
		setCopied(false);
		try {
			await navigator.clipboard.writeText(text);
			setCopied(true);
		} catch {
			const ta = document.createElement("textarea");
			ta.value = text;
			document.body.appendChild(ta);
			ta.select();
			try {
				document.execCommand("copy");
				setCopied(true);
			} catch {}
			document.body.removeChild(ta);
		}
	}
	/** 内容预览（按工单 book_path 定位，审批前过目）：只读 book API，前若干章；无 book_path 不显示入口。 */
	async function openPreview() {
		if (!detail?.book_path) return;
		setPreviewLoading(true);
		setOpMsg("");
		try {
			const data = await apiGet(`${API}/book?path=${encodeURIComponent(detail.book_path)}&limit=5`);
			if (data?.ok !== true) {
				setOpMsg(`Preview failed: ${data?.error ?? "unknown error"}`);
				return;
			}
			setPreview(data.result);
		} catch (err) {
			setOpMsg(`Preview failed: ${String(err instanceof Error ? err.message : err)}`);
		} finally {
			setPreviewLoading(false);
		}
	}
	/** 详情静默刷新（自动轮询用，不置 loading 不闪屏）。t260901-15 跳单守卫：
	*  按发起时刻的 id 校验——响应到达时选中已变则丢弃（旧代码无条件 setDetail 是
	*  「点 13 详情跳回 11」的竞态根因）。t260903-06：返回本拍分类供 pollOnce 记账；
	*  失败保留上次成功快照（不清 detail）；致命类（不存在/终态）在详情区精确提示。 */
	async function refreshDetailSilent() {
		const id = selectedIdRef.current;
		if (!id) return "ok";
		detailInFlight.current = true;
		try {
			const data = await apiGet(`${API}/tickets/${encodeURIComponent(id)}`);
			if (data?.ok === true) {
				if (selectedIdRef.current === id) setDetail(data.result);
				return "ok";
			}
			const out = classifyPollBody(data);
			if (out !== "retryable" && selectedIdRef.current === id) setOpMsg(String(data?.error ?? "ticket query failed"));
			return out;
		} catch {
			return "retryable";
		} finally {
			detailInFlight.current = false;
		}
	}
	const pollMs = pollHealth.degraded ? 3e4 : 5e3;
	(0, react.useEffect)(() => {
		return startVisibleInterval(() => {
			pollOnce();
		}, pollMs);
	}, [selectedId, pollMs]);
	(0, react.useEffect)(() => {
		pollOnce();
	}, []);
	const selWf = (0, react.useMemo)(() => {
		if (!detail) return void 0;
		const hit = wfById[detail.workflow_id];
		if (hit) return hit;
		const parsed = parseTopology(detail.topology);
		if (!parsed || !parsed.nodes.length) return void 0;
		return {
			id: detail.workflow_id,
			name: parsed.name ?? detail.workflow_id,
			lane: "",
			stages: parsed.nodes.map((n) => ({
				id: n.id,
				role: n.role ?? "",
				name: n.label ?? n.id
			})),
			topology: parsed
		};
	}, [detail, wfById]);
	/** Node durations (t260901-12): shared by the lane stepper and the stage cards. */
	const stageDurs = useStageDurations(detail, selWf);
	const laneModel = (0, react.useMemo)(() => buildLaneMap(detail?.topology ?? selWf?.topology ?? null, detail), [detail, selWf]);
	const checksRuns = (0, react.useMemo)(() => detail ? buildChecksDetail(detail) : [], [detail]);
	const ops = detail ? availableOps(detail, selWf) : [];
	const reworkStages = selWf?.stages.map((s) => s.id) ?? [];
	const detailCloseHealth = detail ? closeHealthOf(detail) : "";
	const peerViewersByTicket = /* @__PURE__ */ new Map();
	if (presenceRef.current !== null) for (const t of tickets ?? []) {
		const v = presenceRef.current.viewersOf(t.id);
		if (v.length > 0) peerViewersByTicket.set(t.id, v);
	}
	const drawerPeerViewers = selectedId !== null ? presenceRef.current?.viewersOf(selectedId) ?? [] : [];
	if (!projectKey) return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
		className: "wb-root",
		children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
			style: {
				padding: 32,
				color: "var(--dsw-alias-label-secondary, #888)",
				fontSize: 13
			},
			children: "Pick a project row on the left (or click a ticket row) — the middle column opens the executor panel."
		})
	});
	return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
		className: "wb-root",
		children: [
			error !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-err",
				children: [
					error,
					"\n",
					"(Board API not mounted? headless profile has no webServer.)"
				]
			}),
			(selectedId !== null || overlayNav.current !== null) && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
				className: "wb-drawer wb-overlay",
				"data-testid": "ticket-overlay",
				children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						className: "wb-close",
						onClick: closeTicketOverlay,
						children: "×"
					}),
					peerNote !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						style: {
							background: "var(--dsw-derive-warn-bg,#fff8c5)",
							border: "1px solid var(--dsw-derive-warn-border,#d4a72c)",
							borderRadius: 6,
							padding: "6px 10px",
							fontSize: 12,
							color: "var(--dsw-derive-warn-deep,#7d4e00)",
							display: "flex",
							gap: 8,
							alignItems: "center"
						},
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							style: { flex: 1 },
							children: peerNote
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
							className: "wb-close",
							style: { position: "static" },
							onClick: () => {
								setPeerNote("");
							},
							children: "×"
						})]
					}),
					overlayNav.current !== null && overlayNav.current.kind === "epic" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-overlay-epic",
						"data-testid": "overlay-epic",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-drawer-head",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
								className: "wb-title",
								children: "Epic"
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", {
								className: "wb-d2-id",
								children: overlayNav.current.id
							})]
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)(EpicSection, {
							epicCode: overlayNav.current.id,
							projectKey,
							onOpenTicket: (tid) => drillOverlayToTicket(tid, overlayNav.current !== null ? overlayNav.current.id : "")
						})]
					}),
					detailLoading && overlayNav.current?.kind !== "epic" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: "wb-empty",
						children: "Loading detail…"
					}),
					!detailLoading && overlayNav.current?.kind !== "epic" && terminalFace !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TerminalFailurePanel, { view: terminalFace }),
					!detailLoading && overlayNav.current?.kind !== "epic" && detail !== void 0 && detail.id === selectedId && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-drawer-head",
							children: [
								(() => {
									const c = crumbOf(overlayNav);
									return c !== null ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("button", {
										className: "wb-overlay-crumb",
										"data-testid": "overlay-crumb",
										title: `Back to epic ${c}`,
										onClick: overlayBreadcrumbBack,
										children: ["← ", c]
									}) : null;
								})(),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-title",
									"data-title-src": detail.title?.trim() ? "title" : "first-or-id",
									children: detail.title?.trim() || firstSentenceOf(detail.body) || detail.id
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("code", {
									className: "wb-d2-id",
									children: detail.id
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-badge",
									"data-kind": "status",
									children: detail.status
								}),
								detail.close_health === "abnormal" || detail.close_health === "unreadable" ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-badge",
									"data-state": "done",
									"data-close-health": detailCloseHealth,
									children: detailCloseHealth === "unreadable" ? "Closed·Unverified" : "Closed·Abnormal"
								}) : detail.status !== "closed" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-badge",
									"data-state": detail.stage_state,
									children: STATE_LABEL[detail.stage_state] ?? detail.stage_state
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
									className: "wb-sub",
									children: selWf ? workflowLabel(selWf.id) : "no template"
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)(EpicBadge, {
									epic: detail.epic,
									onNavigate: (code) => drillOverlayToEpic(code)
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)(UsageSummaryLine, {
									detail,
									wf: selWf,
									usage
								})
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-detail-actions",
							"data-testid": "detail-actions",
							children: [
								ops.includes("advance") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-btn wb-btn-green",
									disabled: opBusy,
									onClick: () => {
										doAdvance(detail.id, detail.stage_state, detail.epic);
									},
									children: detail.stage_state === "awaiting-human" ? "Sign" : "Continue"
								}),
								ops.includes("rework") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-btn wb-btn-danger",
									disabled: opBusy,
									onClick: () => {
										openRework(detail.id, detail.stage_state === "awaiting-human");
									},
									children: "Send back"
								}),
								ops.includes("unblock") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-btn wb-btn-blue",
									disabled: opBusy,
									onClick: () => {
										if (detail.engine === "template-as-code-v2") doOp(detail.id, "retry-qc", { who: operator }, "Retry requested (retry_qc)");
										else doOp(detail.id, "update", {
											stage_state: "awaiting",
											note: "(board) unblock"
										}, "Unblocked");
									},
									children: "Retry check"
								}),
								ops.includes("pause") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-btn",
									disabled: opBusy,
									onClick: () => void doOp(detail.id, "pause", { who: operator }, "Pause sent (stops after current stage finishes)"),
									children: "Pause"
								}),
								ops.includes("resume") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
									className: "wb-btn",
									disabled: opBusy,
									onClick: () => void doOp(detail.id, "resume", {}, "Resume sent; dispatching continues"),
									children: "Resume"
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
									className: "wb-d2-more",
									children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: "More" }), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "wb-d2-more-body",
										children: [
											ops.includes("dispatch-next") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
												className: "wb-btn",
												disabled: opBusy,
												onClick: () => {
													doOp(detail.id, "dispatch-next", {}, "Dispatch prompt generated");
												},
												children: "Dispatch next"
											}),
											ops.includes("close") && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
												className: "wb-btn wb-btn-green",
												disabled: opBusy,
												onClick: () => {
													if (window.confirm("Mark as completed (closed)?")) doOp(detail.id, "update", {
														status: "closed",
														note: "(board) done"
													}, "Marked closed");
												},
												children: "Done"
											}),
											detail.book_path && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
												className: "wb-btn",
												disabled: opBusy || previewLoading,
												onClick: () => {
													openPreview();
												},
												children: previewLoading ? "Loading…" : "Preview content"
											}),
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("a", {
												className: "wb-meta-link",
												href: `http://127.0.0.1:8233/namespaces/default/workflows/${encodeURIComponent(detail.id)}`,
												target: "_blank",
												rel: "noreferrer",
												children: "Temporal execution ↗"
											})
										]
									})]
								}),
								ops.length === 0 && detail.status !== "closed" && detail.kind !== "inspection" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "wb-d2-hint",
									children: [
										"No operation available for this state (",
										detail.status,
										"×",
										detail.stage_state,
										")"
									]
								})
							]
						}),
						opMsg !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-sub",
							style: { marginTop: 6 },
							children: opMsg
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(DetailDecisionCardFace, { detail }),
						detail.blocked_reason && detail.close_health !== "abnormal" && detail.close_health !== "unreadable" && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-d2-blocked",
							children: ["⛔ Blocked: ", detail.blocked_reason]
						}),
						(() => {
							const card = buildStatusCard(detail);
							if (!card) return null;
							return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-status-card",
								"data-sev": card.severity,
								"data-testid": "status-card",
								"data-terminal": card.terminal || void 0,
								children: [
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "sc-head",
										children: [
											card.terminal ? "⏹" : card.severity === "blue" ? "🔑" : "⛔",
											" ",
											card.headline
										]
									}),
									card.terminal && card.closeFacts.map((f, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
										className: "sc-fact",
										"data-testid": "close-fact",
										children: f
									}, i)),
									!card.headlineFromTable && !card.terminal && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
										className: "sc-fallback",
										children: "Above is engine verbatim (no lexicon entry for this reason code; not guessed)"
									}),
									card.severity === "blue" && card.signWhat.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "sc-signwhat",
										"data-testid": "sign-what",
										children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
											className: "sc-signwhat-ttl",
											children: "What to sign"
										}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("ul", { children: card.signWhat.map((s, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("li", { children: s }, i)) })]
									}),
									(card.files.length > 0 || card.filesMore > 0) && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "sc-files",
										children: [card.files.map((f) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
											className: "sc-file",
											title: "Open read-only as of this ticket",
											onClick: () => setFileViewer({
												ticketId: detail.id,
												path: f,
												mode: "settle"
											}),
											children: f
										}, f)), card.filesMore > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
											className: "sc-file-more",
											children: [
												"+",
												card.filesMore,
												" more"
											]
										})]
									}),
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
										className: "sc-next",
										children: [
											/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: card.severity === "blue" ? "Waiting on you: " : card.terminal ? "Note: " : "Next: " }),
											" ",
											card.next
										]
									}),
									/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("details", {
										className: "sc-raw",
										children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("summary", { children: "Raw engine log (debug only)" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", { children: card.rawLog.join("\n") })]
									})
								]
							});
						})(),
						(() => {
							const refs = Array.isArray(detail.refs) ? detail.refs.filter((x) => typeof x === "string" && x.trim() !== "") : [];
							if (refs.length === 0) return null;
							return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-refs",
								"data-testid": "ticket-refs",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "ttl",
									children: "Background references (not part of this ticket · open to see baseline version)"
								}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-refs-files",
									children: refs.map((f) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
										className: "wb-ref-file",
										title: "Open read-only at ticket-open baseline",
										onClick: () => setFileViewer({
											ticketId: detail.id,
											path: f,
											mode: "base"
										}),
										children: f
									}, f))
								})]
							});
						})(),
						drawerPeerViewers.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							style: {
								background: "var(--dsw-derive-accent-bg,#ddf4ff)",
								border: "1px solid var(--dsw-derive-accent-border,#54aeff)",
								borderRadius: 6,
								padding: "6px 10px",
								fontSize: 12,
								color: "var(--dsw-derive-accent-deep,#0a3069)"
							},
							children: ["👀 Another tab is viewing this ticket: ", drawerPeerViewers.map((v) => v.who).join(", ")]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(SpecBlock, {
							body: detail.body,
							spec: detail.spec,
							acceptance: detail.acceptance,
							writeSet: detail.write_set,
							redLine: detail.red_line,
							specHtml: typeof detail.spec === "string" ? specMarkdownHtml(detail.spec) : ""
						}),
						detail.kind === "inspection" && laneModel && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(LaneMap, { model: laneModel }),
						detail.kind === "inspection" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(InspectionDetailFace, {
							detail,
							operator,
							opBusy,
							onSign: (decision, note) => doSign(detail.id, decision, note, detail.gate_id || "inspection-close")
						}),
						detail.kind !== "inspection" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(D2Reworks, {
							detail,
							wf: selWf
						}),
						detail.kind !== "inspection" && (laneModel ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)(LaneMap, { model: laneModel }) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)(D2Stepper, {
							detail,
							wf: selWf,
							usage,
							durs: stageDurs.durs,
							nowMs: stageDurs.nowMs
						})),
						detail.kind !== "inspection" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ChecksDetail, { runs: checksRuns }),
						(() => {
							const st = d2StatusLine(detail, selWf);
							return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "wb-d2-status",
								"data-s": st.s,
								children: st.text
							});
						})(),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(PulseLine, { detail }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(AgentLivePanel, { ticketId: detail.id }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(EvidenceImages, { ticketId: detail.id }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(D2Problems, { detail }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(DetailTwoColumns, {
							detail,
							projectKey
						}),
						detail.kind !== "inspection" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(LazyFold, {
							label: "Changeset (full diff and review)",
							testid: "fold-changes",
							children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(ChangesTab, {
								detail,
								operator,
								onMsg: setOpMsg,
								onOpenFile: (p, m) => setFileViewer({
									ticketId: detail.id,
									path: p,
									mode: m
								})
							})
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(LazyFold, {
							label: "Agent log",
							testid: "fold-agent-log",
							children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(AgentLogsTab, {
								detail,
								wf: selWf,
								onMsg: setOpMsg
							})
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(LazyFold, {
							label: "Stage progress (per-stage cards and durations)",
							testid: "fold-stage-progress",
							children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(D2Stages, {
								detail,
								wf: selWf,
								usage,
								durs: stageDurs.durs,
								nowMs: stageDurs.nowMs
							})
						})
					] })
				]
			}),
			approveBox !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-modal",
				role: "dialog",
				"aria-modal": "true",
				"aria-label": "Approve and advance",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-modal-box",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-modal-title",
							children: ["Approve and advance — ", approveBox.id]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-modal-body",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-ops",
									style: {
										justifyContent: "flex-start",
										marginBottom: 6
									},
									children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
										className: "wb-d-badge",
										"data-s": "added",
										children: "Auto summary (read-only)"
									})
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
									className: "wb-prompt",
									style: {
										maxHeight: 120,
										overflow: "auto"
									},
									children: approveBox.summary !== "" ? approveBox.summary : "(no stored review; no summary this round)"
								}),
								approveBox.epicLine !== "" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									style: {
										margin: "6px 0",
										color: epicChipMuted()
									},
									children: approveBox.epicLine
								}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
									className: "wb-ev-input",
									style: { minHeight: 80 },
									maxLength: 2e3,
									placeholder: "Free-form note (optional; stored immutably with the signature, ≤2000 chars)",
									value: approveRemark,
									onChange: (e) => setApproveRemark(e.target.value)
								})
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ops",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn wb-btn-green",
								disabled: opBusy,
								onClick: doApprove,
								children: "Approve and advance"
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: closeApprove,
								children: "Cancel"
							})]
						})
					]
				})
			}),
			reworkId !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-modal",
				role: "dialog",
				"aria-modal": "true",
				"aria-label": "Rework",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-modal-box",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-modal-title",
							children: [
								reworkHuman ? "Rework (Temporal sign, decision=reject)" : "Rework",
								" — ",
								reworkId
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-modal-body",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("select", {
								className: "wb-select",
								value: reworkTo,
								onChange: (e) => setReworkTo(e.target.value),
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
									value: "",
									children: "Rework target: default (auto by stage semantics)"
								}), reworkStages.map((s) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("option", {
									value: s,
									children: s
								}, s))]
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("textarea", {
								className: "wb-ev-input",
								style: { minHeight: 80 },
								placeholder: "Rework reason (required)",
								value: reworkNote,
								onChange: (e) => setReworkNote(e.target.value)
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ops",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn wb-btn-danger",
								disabled: opBusy,
								onClick: doRework,
								children: "Confirm rework"
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: () => {
									setReworkId(null);
									setReworkNote("");
									setReworkTo("");
								},
								children: "Cancel"
							})]
						})
					]
				})
			}),
			promptBox !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-modal",
				role: "dialog",
				"aria-modal": "true",
				"aria-label": "Dispatch prompt",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-modal-box",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-modal-title",
						children: [
							"Dispatch prompt (dispatch-next · ",
							promptBox.role,
							"@",
							promptBox.stage,
							")"
						]
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						className: "wb-modal-body",
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("pre", {
							className: "wb-prompt",
							children: promptBox.prompt
						}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-ops",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: () => {
									copyPrompt(promptBox.prompt);
								},
								children: copied ? "Copied ✓" : "Copy prompt"
							}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: () => {
									setPromptBox(null);
									setCopied(false);
								},
								children: "Close"
							})]
						})]
					})]
				})
			}),
			preview !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: "wb-modal",
				role: "dialog",
				"aria-modal": "true",
				"aria-label": "Content preview",
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					className: "wb-modal-box wb-preview-box",
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-modal-title",
							children: [
								"Content preview · ",
								preview.meta.主题 || "後漢書",
								preview.meta.期次 ? ` (${preview.meta.期次})` : "",
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
									className: "wb-sub",
									children: [
										" ",
										preview.meta.类型,
										" · ",
										preview.meta.total_chapters,
										" chapters · previewing first ",
										preview.chapters.length,
										" · ",
										preview.meta.size_kb,
										"KB"
									]
								})
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-preview-notice",
							children: "Preview · final rendering lives in the app (traditional Chinese, scrollable)"
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: "wb-modal-body",
							children: [preview.chapters.map((ch) => /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
								className: "wb-preview-ch",
								children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
									className: "wb-preview-ch-title",
									children: ch.标题
								}), ch.paras.map((p, i) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("p", {
									className: "wb-preview-para",
									children: p
								}, i))]
							}, ch.id)), preview.chapters.length === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
								className: "wb-empty",
								children: "No previewable chapters in this file."
							})]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: "wb-ops",
							children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								className: "wb-btn",
								onClick: () => {
									setPreview(void 0);
								},
								children: "Close"
							})
						})
					]
				})
			}),
			fileViewer !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TicketTimeViewer, {
				ticketId: fileViewer.ticketId,
				path: fileViewer.path,
				initialMode: fileViewer.mode,
				onClose: () => setFileViewer(null)
			})
		]
	});
}
/**
* Workbench 视图的 per-session snapshot builder（引擎契约空实现）。
* 工单台数据来自 /sandbar-workbench/api/wf/*（宿主半 API），不消费会话事件流；
* create 返回的 builder 仅需满足 ConversationViewBuilder 形状（empty/replace/apply）。
* target 与 conversation.view 槽条目 id（'workbench'）一致，与 chat/trajectory 同机制。
*/
function apply(ctx) {
	const getService = typeof ctx.get === "function" ? ctx.get.bind(ctx) : void 0;
	ctx.slots.inject("sidebar.workspaces", () => ctx.slots.register({
		name: "sidebar.workspaces",
		priority: -10
	}, (props) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)(SlotErrorBoundary, { children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(WorkbenchSidebar, {
		sessions: ctx.sessions,
		workspaces: ctx.workspaces,
		getService,
		views: {
			overlay: WorkbenchSection,
			routes: ProvidersSection
		},
		...props
	}) })));
}
//#endregion
exports.TerminalFailurePanel = TerminalFailurePanel;
exports.apply = apply;
exports.evidenceImgSrc = evidenceImgSrc;
exports.evidenceLightboxKeys = evidenceLightboxKeys;
exports.evidenceNav = evidenceNav;
exports.inject = inject;
exports.name = name;
exports.specMarkdownHtml = specMarkdownHtml;

return module.exports; } });