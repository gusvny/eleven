window.__ModuleLoader__.load({ id: "suyou-providers", factory: (require) => { var module = { exports: {} }; var exports = module.exports;
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
let react = require("react");
let react_jsx_runtime = require("react/jsx-runtime");
//#region src/host/routes-edit.ts
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
//#region src/client/index.tsx
/**
* suyou-providers —— LLM provider 管理与优先级 · 浏览器半（会话主视图「模型」页签版）。
*
* 槽位契约（t260821-11 ①：从 settings 分区迁来，制式照抄 workbench）：向会话视图环
* `conversation.view` 注册一个页签（id 'suyou-providers'，标签「模型」，order 15，
* 与 chat(0)/trajectory(10)/工单台(20) 平级），用户在主会话视图顶部页签切换即见。
* 配套注册 `conversationViews.register`（target 'suyou-providers'）：本视图数据来自
* /suyou-providers/api/* 而非会话事件，builder 为空实现，仅为满足 per-session 契约。
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
*      保存（POST /suyou-admin/api/routes/save，宿主在 suyou-admin-ui 插件，写前备份
*      /tmp；保存即生效——运行时查表，下一个工单 agent spawn 用新表）。
* 所有写操作走宿主半（../node.ts）挂在 dsh webServer 上的 /suyou-providers/api/*；
* 路由表读写走 suyou-admin-ui 的 /suyou-admin/api/routes（同源，M13① 保留的 API）。
*/
const name = "suyou-providers/client";
const inject = ["slots", "conversationViews"];
const CSS = `
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
const CSS_TAG_ID = "suyou-providers/ProvidersSection.css";
if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(CSS_TAG_ID) + "]") === null) {
	const tag = document.createElement("style");
	tag.dataset.plugin = "suyou-providers";
	tag.dataset.pluginCss = CSS_TAG_ID;
	tag.textContent = CSS;
	document.head.appendChild(tag);
}
const API = "/suyou-providers/api";
/** 多项目化（260823）：路由表两条 URL（/suyou-admin/api/routes*，按项目主目录解析
*  model-routes.yaml）统一拼 ?project=；provider 管理（/suyou-providers/api/*）是
*  dsh 全局设施，不分流。
*  260826 修：project 从模块级持有量改为纯函数入参——旧写法靠 ProvidersSection 的
*  effect 落值，但 React 挂载时子组件 effect 先于父组件执行，RoutesTableSection
*  首次 load 永远拿到空 project → 宿主 400「缺 project 参数」。prop 渲染期即有值，
*  不依赖 effect 顺序。 */
function routesUrl(path, projectKey) {
	if (!projectKey) return path;
	return path + (path.includes("?") ? "&" : "?") + "project=" + encodeURIComponent(projectKey);
}
async function apiGet(path) {
	return (await fetch(path)).json();
}
async function apiPost(path, body) {
	return (await fetch(path, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify(body ?? {})
	})).json();
}
const KIND_LABEL = {
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
			const d = await apiGet(`${API}/state`);
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
			const r = await apiPost(path, body);
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
		if (await post(`${API}/add-provider`, {
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
		if (await post(`${API}/set-current`, {
			provider: curId,
			model: curModel,
			reasoningEffort: curRe
		}, `已把 agent-default-model 切到 ${curId} / ${curModel.trim()}`)) setCurId(null);
	}
	async function saveNote(p) {
		const note = noteDraft[p.id] ?? p.note;
		await post(`${API}/update-note`, {
			id: p.id,
			note
		}, `已保存「${p.id}」计费说明`);
	}
	async function reorder(order) {
		setBusy(true);
		setMsg("");
		try {
			const r = await apiPost(`${API}/reorder`, { order });
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
											children: KIND_LABEL[p.kind] ?? p.kind
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
										if (window.confirm(`删除 provider「${p.id}」（从 llm-pi-ai.providers 移除）？`)) post(`${API}/delete-provider`, { id: p.id }, `已删除「${p.id}」`);
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
			const data = await apiGet(routesUrl("/suyou-admin/api/routes", projectKey ?? ""));
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
		if (!window.confirm("保存将改写 server/dsh/model-routes.yaml（真源，写前备份 /tmp）。\n保存即生效：路由表是运行时查表，下一个工单 agent spawn 时就按新表走，无需任何生成/重启步骤。\n确认保存路由表？")) return;
		setBusy(true);
		setMsg("");
		setSaved(false);
		try {
			const r = await apiPost(routesUrl("/suyou-admin/api/routes/save", projectKey ?? ""), { table: draftToPayload(draft) });
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
				"（/suyou-admin/api/routes 返回错误——按上面文案排查：缺参/未知项目=调用问题；表缺失/解析失败=该项目主目录的 model-routes.yaml 问题。）"
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
					"改表红线：保存直接改写 model-routes.yaml（写前备份 /tmp）；模型 ref 不许发明——只用下方 provider 下拉里实证存在的 provider 及其模型 id。保存后",
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
/**
* 260823 起「模型」UI 不再占 chat 顶部页签——移到工单台侧栏中栏，
* 由 suyou-workbench 的侧栏直接 import ProvidersSection 渲染（用户拍板：chat 页签只留 chat/trajectory）。
* apply 保留为空操作（宿主装载契约要求导出）。
*/
function apply(_ctx) {}
//#endregion
exports.ProvidersSection = ProvidersSection;
exports.apply = apply;
exports.inject = inject;
exports.name = name;

return module.exports; } });