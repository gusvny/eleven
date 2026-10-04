/**
 * panel-page.ts —— 面板静态页（t261003-06 按 261003 定稿 mock 全面改版）。
 *
 * 为什么是「插件自服务的静态页」而不是 tsdown 构建包：零构建步骤 → 宿主交接=
 * 控制台重启一次装载插件 + 之后纯浏览器刷新；且 beep 决策/降级挑选等纯逻辑
 * **从 page-logic.ts 经 String(fn) 原样嵌入**——单测与页面永远同一份实现，不漂移。
 * 界面文案全英文（宿主令 260925：英文界面+数据不译），且全量按设计 note §4 的
 * 80% ASD-STE100 口径改写（短句、主动语态、固定术语、无缩略、无行话）。
 *
 * 版面（设计 note §2 / mock 261003）：顶部只有 Executor + 项目标签——项目选择器
 * （下拉/手填/Load）与轮询状态行**不存在**；项目来自 ?project= 深链（workbench
 * 项目行进面板即该项目）。页签 Overview / Grants / Alerts / Ledger / Settings。
 * Overview 两栏并列（左=等你回，右=最近动作），窄于 760px 叠放（.cols media query）。
 *
 * 语义（设计 note §3）：Overview 的 Disable executor 与 Grants 总开关是**同一份状态**
 * （POST /api/grants op:'master'）——关=收回全部授权（只读和问），会话点名保留，
 * watchdog.json 不动（守望者照常运行）。Settings 里的「Disable watchdog」是另一个面
 * （enabled:false），文案与代码都分开命名，一个词不表两义。
 *
 * 契约偏差（如实声明，沿用 t260929-03 review #1）：notify.beep 的已读清除走页面本地
 * seen-set（localStorage per project）；watchdog 侧 per-key 清除端点属守望者插件改动，
 * out-of-scope——后果（第二台设备会再响一声）写进交接报告，后续票收口。
 */

import {
  beepDecision, pickDegraded, fmtProportion, fmtWaiting, fmtAge, groupByProject,
  splitWaiting, hasOptions, chipLabel, masterOn, hhmmLocal, wakeRowSentence, themeParamOf,
} from './page-logic.ts'

/** 纯函数源码嵌入（strip 后即等价 JS；单测直接测这些函数本体）。 */
const EMBEDDED = [
  String(beepDecision), String(pickDegraded), String(fmtProportion),
  String(fmtWaiting), String(fmtAge), String(groupByProject),
  String(splitWaiting), String(hasOptions), String(chipLabel), String(masterOn),
  String(hhmmLocal), String(wakeRowSentence), String(themeParamOf),
].join('\n')

export const PANEL_ROUTE = '/sandbar-executor-panel'
export const PANEL_PAGE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Executor</title>
<style>
/* t261003-09 缺陷 2：双调色板，随 ?theme= 切（workbench 深链恒带）；缺席/畸形 →
   不设 data-theme，落 prefers-color-scheme 显式降级（standalone 场景），浅色兜底。
   词表对齐控制台 --dsw-alias/--dsw-derive 家族（light=GitHub 浅档、dark=原深档）。 */
html[data-theme="light"],html:not([data-theme]){--bg:#ffffff;--panel:#f6f8fa;--panel2:#eaeef2;--line:#d0d7de;--line-soft:#e4e9ee;--fg:#1f2328;--fg-soft:#424a53;--muted:#57606a;--faint:#6e7781;--blue:#0969da;--red:#cf222e;--amber:#9a6700;--green:#1a7f37;--hover:#eef1f4;--badge-fg:#ffffff;--accent-soft:#dbe9ff;--accent-line:#7aa7e8;--dot-grey:#99a3ad;--sw-off:#d7dde3;--knob:#57606a;--warn-soft:#fff8c5;--danger-soft:#ffebe9;--pill-sign-bg:#ddf4ff;--pill-sign-fg:#0550ae;--pill-open-bg:#dafbe1;--pill-open-fg:#116329;--pill-retry-bg:#fff8c5;--pill-retry-fg:#7d4e00;--pill-send-bg:#fff1d6;--pill-send-fg:#9a5b00;--pill-cancel-bg:#ffebe9;--pill-cancel-fg:#cf222e;--pill-pause-bg:#e7ebef;--pill-pause-fg:#57606a}
html[data-theme="dark"]{--bg:#141a24;--panel:#1b2330;--panel2:#222c3c;--line:#2e394d;--line-soft:#232c3a;--fg:#dbe4f0;--fg-soft:#c3cfdf;--muted:#8ea0b8;--faint:#5b6880;--blue:#4da3ff;--red:#ff6b6b;--amber:#ffb454;--green:#7ad48a;--hover:#1f2937;--badge-fg:#0e1420;--accent-soft:#1d3550;--accent-line:#2f5b8a;--dot-grey:#46536a;--sw-off:#39465c;--knob:#8ea0b8;--warn-soft:#2a2313;--danger-soft:#2a1414;--pill-sign-bg:#183153;--pill-sign-fg:#79b8ff;--pill-open-bg:#16351f;--pill-open-fg:#7ad48a;--pill-retry-bg:#3a2d13;--pill-retry-fg:#ffb454;--pill-send-bg:#3a2a13;--pill-send-fg:#ffc07a;--pill-cancel-bg:#3a1a1a;--pill-cancel-fg:#ff8b8b;--pill-pause-bg:#262f3d;--pill-pause-fg:#9fb0c8}
@media (prefers-color-scheme: dark){ html:not([data-theme]){--bg:#141a24;--panel:#1b2330;--panel2:#222c3c;--line:#2e394d;--line-soft:#232c3a;--fg:#dbe4f0;--fg-soft:#c3cfdf;--muted:#8ea0b8;--faint:#5b6880;--blue:#4da3ff;--red:#ff6b6b;--amber:#ffb454;--green:#7ad48a;--hover:#1f2937;--badge-fg:#0e1420;--accent-soft:#1d3550;--accent-line:#2f5b8a;--dot-grey:#46536a;--sw-off:#39465c;--knob:#8ea0b8;--warn-soft:#2a2313;--danger-soft:#2a1414;--pill-sign-bg:#183153;--pill-sign-fg:#79b8ff;--pill-open-bg:#16351f;--pill-open-fg:#7ad48a;--pill-retry-bg:#3a2d13;--pill-retry-fg:#ffb454;--pill-send-bg:#3a2a13;--pill-send-fg:#ffc07a;--pill-cancel-bg:#3a1a1a;--pill-cancel-fg:#ff8b8b;--pill-pause-bg:#262f3d;--pill-pause-fg:#9fb0c8} }
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 ui-sans-serif,system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:18px 16px 48px;container-type:inline-size}
.top{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.top h1{font-size:14px;font-weight:600;margin:0}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:999px;padding:2px 9px;font-size:11px}
.seg{display:flex;gap:2px;background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:2px;width:max-content;margin-bottom:16px;flex-wrap:wrap}
input.tab{position:absolute;opacity:0;pointer-events:none}
.seg label{color:var(--muted);cursor:pointer;padding:5px 12px;border-radius:7px;display:flex;align-items:center;gap:6px;font-size:12px}
.seg label:hover{color:var(--fg)}
#t-overview:checked~.seg label[for=t-overview],#t-grants:checked~.seg label[for=t-grants],#t-alerts:checked~.seg label[for=t-alerts],#t-ledger:checked~.seg label[for=t-ledger],#t-settings:checked~.seg label[for=t-settings]{background:var(--panel2);color:var(--fg)}
.badge{min-width:18px;height:18px;border-radius:9px;background:var(--blue);color:var(--badge-fg);font-size:11px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;padding:0 5px}
.badge.zero{background:var(--panel2);color:var(--muted);font-weight:500}
.sect{margin:0 0 6px;font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted);display:flex;align-items:center;gap:8px}
.sect.lead{margin-top:18px}
.row{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:8px;overflow:hidden}
.row.wait{border-left:3px solid var(--amber)}
.row.done{border-left:3px solid var(--line);background:transparent}
.head{display:flex;align-items:baseline;gap:8px;padding:10px 12px;cursor:pointer;user-select:none}
.head:hover{background:var(--hover)}
.row.done .head .txt{color:var(--muted)}
.txt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto;margin-top:5px}
.dot.amber{background:var(--amber)}.dot.grey{background:var(--dot-grey)}.dot.red{background:var(--red)}.dot.blue{background:var(--blue)}
.meta{color:var(--muted);font-size:11px;white-space:nowrap}
.chev{color:var(--muted);font-size:10px;flex:0 0 auto;transition:transform .15s}
.row[data-open="true"] .chev{transform:rotate(90deg)}
.body{display:none;padding:0 12px 11px 12px;border-top:1px solid var(--line-soft)}
.row[data-open="true"] .body{display:block}
.detail{margin-top:9px;max-height:170px;overflow:auto;white-space:pre-wrap;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:9px 11px;color:var(--fg-soft);font-size:12px}
.opts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
.opts button{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:6px 14px;font:inherit;cursor:pointer}
.opts button:hover{border-color:var(--blue);color:var(--blue)}
.opts button.primary{background:var(--accent-soft);border-color:var(--accent-line)}
.other{border:0;background:transparent;color:var(--faint);font:inherit;cursor:pointer;padding:6px 4px;text-decoration:underline dotted}
.answer{display:flex;gap:8px;margin-top:10px}
.answer input{flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:7px;padding:6px 9px;font:inherit}
.answer input:focus{outline:0;border-color:var(--blue)}
.answer button{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:6px 12px;font:inherit;cursor:pointer}
.given{color:var(--green);font-size:12px;padding:0 12px 10px 12px}
.trace{color:var(--faint);font-size:11px;margin-top:9px}
.strip{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);font-size:12px;color:var(--muted);margin-bottom:14px;flex-wrap:wrap}
.strip .live{color:var(--green)}
.strip .ro{color:var(--amber)}
.power{border:1px solid var(--line);border-radius:7px;padding:5px 12px;font:inherit;cursor:pointer;background:var(--panel2);color:var(--fg)}
.power[data-on="true"]:hover{border-color:var(--red);color:var(--red)}
.power[data-on="false"]:hover{border-color:var(--green);color:var(--green)}
.openBtn{border:1px solid var(--line);border-radius:7px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer;background:var(--panel2);color:var(--fg)}
.openBtn:disabled{opacity:.45;cursor:not-allowed}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
/* t261003-09 缺陷 1：断点按真实容器宽（container query——面板是 iframe/独立窗口，
   视口宽≠内容盒宽），且两栏各自限高内滚——展开任何一条请求只在**自己那栏**长高，
   另一栏与下方内容永不位移；行内 detail 的 170px 限高不变（滚动锚定稳定）。 */
.cols>div{min-width:0;height:calc(100vh - 230px);overflow-y:auto;overscroll-behavior:contain}
@container (max-width:760px){ .cols{grid-template-columns:1fr} }
.act{display:flex;align-items:center;gap:9px;padding:7px 10px;border-bottom:1px solid var(--line-soft)}
.act:last-child{border-bottom:0}
.act .t{color:var(--muted);font-size:11px;width:38px;flex:0 0 auto}
.pill{font-size:10px;font-weight:700;letter-spacing:.6px;border-radius:5px;padding:2px 7px;min-width:52px;text-align:center}
.pill.sign{background:var(--pill-sign-bg);color:var(--pill-sign-fg)}
.pill.open{background:var(--pill-open-bg);color:var(--pill-open-fg)}
.pill.retry{background:var(--pill-retry-bg);color:var(--pill-retry-fg)}
.pill.sendback{background:var(--pill-send-bg);color:var(--pill-send-fg)}
.pill.cancel{background:var(--pill-cancel-bg);color:var(--pill-cancel-fg)}
.pill.pause{background:var(--pill-pause-bg);color:var(--pill-pause-fg)}
.act .tk{font-weight:600}
.act .say{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.cell{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 11px}
.cell b{display:block;font-size:15px;font-weight:600}
.cell span{color:var(--muted);font-size:11px}
.file{color:var(--faint);font-size:11px;margin-top:8px}
.grp{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.line{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid #232c3a}
.line:last-child{border-bottom:0}
.line .lab{flex:1;min-width:0}
.line .lab small{display:block;color:var(--muted);font-size:11px}
.line input[type=text],.line input[type=number],.line input[type=time],.line select{background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:7px;padding:5px 8px;font:inherit;width:150px}
.sw{width:38px;height:21px;border-radius:11px;background:var(--sw-off);border:1px solid var(--line);position:relative;cursor:pointer;flex:0 0 auto;transition:background .15s}
.sw::after{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px;border-radius:50%;background:var(--knob);transition:left .15s,background .15s}
.sw[data-on="true"]{background:var(--accent-soft);border-color:var(--accent-line)}
.sw[data-on="true"]::after{left:18px;background:var(--blue)}
.sw.locked{opacity:.35;cursor:not-allowed}
.linkbtn{border:0;background:transparent;color:var(--muted);font:inherit;cursor:pointer;text-decoration:underline dotted;margin-left:auto}
.linkbtn:hover{color:var(--blue)}
.bar{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.bar button{border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:7px;padding:7px 14px;font:inherit;cursor:pointer}
.bar button.primary{background:#1d3550;border-color:#2f5b8a}
.bar button:hover{border-color:var(--blue)}
.doneWrap{margin-top:14px}
.doneHead{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;padding:4px 0}
.chev2{color:var(--muted);transition:transform .15s}
.doneWrap[data-open="false"] .chev2{transform:rotate(-90deg)}
.doneWrap[data-open="false"] .doneList{display:none}
.empty{color:var(--muted);padding:22px 4px}
.banner{border:1px solid var(--amber);color:var(--amber);background:var(--warn-soft);border-radius:10px;padding:9px 12px;margin-bottom:10px;font-size:12px}
.banner.red{border-color:var(--red);color:var(--red);background:var(--danger-soft)}
.knob{display:grid;grid-template-columns:200px 1fr 240px;gap:6px;padding:5px 12px;border-bottom:1px solid #232c3a;align-items:center;font-size:12px}
.knob .src{color:var(--muted);font-size:11px;font-family:ui-monospace,monospace}
table{width:100%;border-collapse:collapse;font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:11px}
.good{color:var(--green)} .bad{color:var(--red)} .muted{color:var(--muted)}
.foot{margin-top:26px;color:var(--faint);font-size:11px}
</style>
</head>
<body>
<div class="wrap">
  <div class="top"><h1>Executor</h1><span class="chip" id="projChip"></span></div>

  <input class="tab" type="radio" name="tb" id="t-overview" checked>
  <input class="tab" type="radio" name="tb" id="t-grants">
  <input class="tab" type="radio" name="tb" id="t-alerts">
  <input class="tab" type="radio" name="tb" id="t-ledger">
  <input class="tab" type="radio" name="tb" id="t-settings">

  <div class="seg">
    <label for="t-overview">Overview <span id="reqBadge" class="badge zero">0</span></label>
    <label for="t-grants">Grants</label>
    <label for="t-alerts">Alerts</label>
    <label for="t-ledger">Ledger</label>
    <label for="t-settings">Settings</label>
  </div>

  <div id="noProject" class="banner red" style="display:none">No project is selected. Open this panel from a project row, or add ?project=&lt;project-key&gt; to the address.</div>

  <section id="paneOv">
    <div class="strip">
      <span id="liveDot" class="ro">● read-only</span>
      <span id="stateTxt">The executor state is not known yet.</span>
      <span id="grantChip" class="chip">Permissions: 0 of 6</span>
      <span id="sessionChip" class="chip">Session: none</span>
      <button class="openBtn" id="openSessionBtn" disabled>Open session</button><span class="meta" id="sessionMsg"></span>
      <button class="power" id="powerBtn" data-on="false" style="margin-left:auto">Enable executor</button>
    </div>
    <div id="ovBanners"></div>
    <div class="cols">
      <div>
        <div class="sect" id="waitHead">Needs your answer · 0</div>
        <div id="waitList"></div>
        <div class="empty" id="waitEmpty" style="display:none">Nothing waits on you.</div>
        <div class="doneWrap" data-open="false" id="doneWrap" style="display:none">
          <div class="doneHead" id="doneHeadBtn">
            <span class="chev2">&#9662;</span><span class="sect" style="margin:0" id="doneHead2">Answered · 0</span>
          </div>
          <div class="doneList" id="doneList"></div>
        </div>
      </div>
      <div>
        <div class="sect">Recent actions</div>
        <div class="muted" style="margin:2px 0 4px;font-size:11px">Times are local.</div>
        <div class="row" style="padding:2px 4px" id="actList"></div>
      </div>
    </div>
  </section>

  <section id="paneGrants" style="display:none">
    <div id="grantsBanner"></div>
    <div class="sect">Executor
      <button class="linkbtn" id="giveAllBtn">Give all</button>
      <button class="linkbtn" id="giveNoneBtn" style="margin-left:0">Give none</button>
    </div>
    <div class="grp">
      <div class="line"><div class="lab">Executor permissions <small>Off: the executor can only read and ask. The watchdog keeps running.</small></div>
        <div class="sw" id="masterSw" data-on="false"></div></div>
      <div class="line"><div class="lab">Executor session <small>The session that works as the executor.</small></div>
        <input type="text" id="grantSession" placeholder="session id"></div>
    </div>
    <div class="sect lead">Permissions you can give</div>
    <div class="grp" id="permList"></div>
    <div class="sect lead">Your permissions only</div>
    <div class="grp">
      <div class="line"><div class="lab">Change permissions <small>Only you can change this list.</small></div>
        <div class="sw locked" data-on="false"></div></div>
    </div>
    <div class="bar">
      <button class="primary" id="grantsSave">Save</button>
      <span id="grantsSaveOut" class="meta"></span>
    </div>
    <div id="grantsReadout" class="muted" style="margin-top:10px"></div>
    <div id="grantsMatrix"></div>
  </section>

  <section id="paneAlert" style="display:none">
    <div id="alertBanner"></div>
    <div class="sect" id="alertHead">Recent · 0</div>
    <div class="muted" style="margin:2px 0 4px;font-size:11px">Times are local.</div>
    <div id="alertList"></div>
  </section>

  <section id="paneLedger" style="display:none">
    <div class="sect">Health</div>
    <div class="grid" id="ledgerGrid"></div>
    <div class="file" id="ledgerFile"></div>
    <div class="sect lead">Last wakes</div>
    <div class="muted" style="margin:2px 0 4px;font-size:11px">Times are local.</div>
    <div class="row" style="padding:2px 4px" id="ledgerEvents"></div>
  </section>

  <section id="paneSet" style="display:none">
    <div id="setBanners"></div>
    <div class="sect lead">Watchdog</div>
    <div class="grp" id="setKnobs"></div>
    <div class="bar">
      <button class="primary" id="saveBtn">Save</button>
      <button id="sleepBtn">Sleep until morning</button>
      <button id="wakeBtn">Revert the night policy</button>
      <button id="revokeBtn">Disable watchdog</button>
      <span id="saveResult" class="meta"></span>
    </div>
    <div class="muted" style="margin-top:8px;font-size:11px">Save writes the file only after the real loader accepts it. A rejected save does not change the file. Disable watchdog stops all watchdog behavior. It does not change the grants.</div>
  </section>

  <div class="foot" id="footNote"></div>
</div>
<script>
` + EMBEDDED + `
(function(){
  var state = { project:'', status:null, reachable:null, requests:null, actions:null, grants:null, settings:null, session:'' };
  var saveMsg = '';
  var grantsSaveMsg = '';
  // t261003-14：UI 态搬到 JS state（键=请求 id），轮询重建 DOM 不再抹掉宿主视图。
  // openIds=宿主展开的行；drafts=自由文本草稿（含展开出的「Type an answer」框）；
  // revealedIds=点过「Type an answer」的行（下次渲染直接给输入框，不再给按钮排）；
  // detailScroll=详情块滚动位置。id 从台账消失的行下一次渲染自然缺席，不会复活。
  state.openIds = new Set();
  state.drafts = {};
  state.revealedIds = new Set();
  state.detailScroll = {};
  var POLL_MS = 5000;
  // 声明键（与引擎 GRANT_OPS 同一词表；'send-back' 是声明键，显示名 Send back）。
  var PERMS = [
    ['sign','Sign','Agree to a gate or a merge.'],
    ['send-back','Send back','Send a ticket to the previous stage.'],
    ['rerun','Rerun','Run the checks of a stage again.'],
    ['open-ticket','Open ticket','Start a new ticket.'],
    ['pause-resume','Pause and resume','Stop or continue a ticket between stages.'],
    ['cleanup','Cleanup','Cancel a ticket.']
  ];
  function beepCountKey(){ return 'sandbar-panel-beepcount-' + (state.project||'global'); }
  try{ window.__panelBeepCount = Number(localStorage.getItem(beepCountKey())||'0')||0; }catch(e){ window.__panelBeepCount = 0; }
  function seenKey(p){ return 'sandbar-panel-seen-' + p; }
  function seenSet(p){ try{ return new Set(JSON.parse(localStorage.getItem(seenKey(p))||'[]')); }catch(e){ return new Set(); } }
  function saveSeen(p,s){ try{ localStorage.setItem(seenKey(p), JSON.stringify(Array.from(s))); }catch(e){} }
  var audioCtx = null;
  function playBeepOnce(){
    // WebAudio oscillator: the page produces the sound (dsh has no sound capability — epic-verified).
    try{
      audioCtx = audioCtx || new (window.AudioContext||window.webkitAudioContext)();
      var o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type='sine'; o.frequency.value=880; g.gain.value=0.08;
      o.connect(g); g.connect(audioCtx.destination);
      var t = audioCtx.currentTime; o.start(t);
      g.gain.setValueAtTime(0.08,t); g.gain.exponentialRampToValueAtTime(0.0001,t+0.35);
      o.stop(t+0.4);
    }catch(e){}
    window.__panelBeepCount += 1;
    try{ localStorage.setItem(beepCountKey(), String(window.__panelBeepCount)); }catch(e){}
  }
  function el(id){ return document.getElementById(id); }
  function esc(s){ var d=document.createElement('span'); d.textContent=String(s==null?'':s); return d.innerHTML; }
  function bannerHtml(label,red){ return '<div class="banner'+(red?' red':'')+'">'+esc(label)+'</div>'; }
  // 时间口径（t261003-13 Finding 3）：全部走 hhmmLocal（本地时区），页头带「Times are local.」标签。

  // ---- polling + beep ----
  function poll(){
    if(!state.project) return;
    fetch('/sandbar-watchdog/api/status?project='+encodeURIComponent(state.project))
      .then(function(r){ return r.json().then(function(j){ return { http:r.status, j:j }; }); })
      .then(function(res){
        var okDoc = res.j && res.j.ok === true && res.j.result;
        state.status = okDoc ? res.j.result : null;
        state.reachable = !!okDoc;
        renderOverviewStrip();
        renderAlertsLedger();
        tryBeep();
      })
      .catch(function(){
        state.status = null; state.reachable = false;
        renderOverviewStrip();
        renderAlertsLedger();
      });
  }
  function tryBeep(){
    var st = state.status;
    if(!st || !st.notify) return;
    var seen = seenSet(state.project);
    var d = beepDecision(st.notify, st.alerts, state.project, seen);
    if(d.play){
      for(var i=0;i<d.keys.length;i++){ playBeepOnce(); seen.add(d.keys[i]); }
      saveSeen(state.project, seen);
    }
  }

  // ---- Overview: strip + two columns ----
  function degradedBanners(){
    var st = state.status, b='';
    var dg = pickDegraded({ reachable: state.reachable === true, declared: st?st.declared:undefined, alive: st&&st.heartbeat?st.heartbeat.alive:undefined, config_error: st?st.config_error:null });
    if(dg.kind==='route-down') b += bannerHtml(dg.label, true);
    // t261003-06 rework（仲裁 code-fault D2）：not-declared 是显式非正常态，必须在
    // Overview 落一条横幅——改版时这一支被漏掉，未声明项目首次到达只剩标题（读起来
    // 像「一切正常但没数据」，正是 panel 契约禁止的冒充）。label 由 pickDegraded 给出
    // （「Not enrolled — no watchdog.json … zero behavior by design」），单测有锚。
    if(dg.kind==='not-declared') b += bannerHtml(dg.label, false);
    if(dg.kind==='stale') b += bannerHtml(dg.label + '. Reason: ' + (st&&st.heartbeat?st.heartbeat.reason:''), true);
    if(dg.kind==='config-error') b += bannerHtml(dg.label, true);
    if(st && st.config_error && dg.kind!=='config-error') b += bannerHtml('The watchdog rejected the declaration: '+st.config_error, true);
    if(st && st.last_error) b += bannerHtml('The last watchdog error: '+st.last_error, true);
    if(st && st.ledger && st.ledger.unreadable) b += bannerHtml('The event ledger is unreadable: '+st.ledger.unreadable, true);
    if(st && st.liveness && st.liveness.engine && st.liveness.engine.online === null) b += bannerHtml('Engine state unknown: '+(st.liveness.engine.detail||''), false);
    if(st && st.self_lock && st.self_lock.state === 'unknown') b += bannerHtml('Self-lock state unknown: '+(st.self_lock.reason||''), false);
    return b;
  }
  function renderOverviewStrip(){
    el('ovBanners').innerHTML = degradedBanners();
    var st = state.status;
    var g = state.grants && state.grants.ok !== false ? state.grants : null;
    var count = g && g.granted_ops ? g.granted_ops.length : null;
    var total = g && typeof g.granted_total === 'number' ? g.granted_total : 6;
    var on = count !== null ? masterOn(count) : false;
    el('grantChip').textContent = chipLabel(count !== null ? count : 0, total);
    el('powerBtn').dataset.on = String(on);
    el('powerBtn').textContent = on ? 'Disable executor' : 'Enable executor';
    el('liveDot').className = on ? 'live' : 'ro';
    el('liveDot').textContent = on ? '● active' : '● read-only';
    var sr = g && g.session_readout ? g.session_readout : null;
    // 点名回落链：读出面 sessions → 声明顶层 executor_sessions（读出面缺席时的声明位）。
    var sess = (sr && sr.sessions && sr.sessions.length ? sr.sessions[0] : '')
      || (g && g.executor_sessions && g.executor_sessions.length ? g.executor_sessions[0] : '');
    state.session = sess;
    el('sessionChip').textContent = 'Session: ' + (sess ? sess : 'none');
    updateOpenBtn(sess);
    var stTxt = st && st.heartbeat ? (st.heartbeat.alive ? 'The watchdog is alive. Last beat: '+fmtAge(st.heartbeat.age_seconds) : 'The watchdog is not alive.') : 'The watchdog state is not known.';
    el('stateTxt').textContent = stTxt + (on ? '' : ' The executor can only read and ask. The watchdog keeps running.');
    renderWaitColumn();
    renderActions();
  }
  // ---- requests (left column) ----
  function normalizeRequests(j){
    var rows = [];
    if(j && Array.isArray(j.rows)) rows = j.rows;
    else if(j && Array.isArray(j.groups)){
      j.groups.forEach(function(g){ (g.rows||[]).forEach(function(r){ rows.push(Object.assign({}, r, {project:r.project||g.project})); }); });
    }
    var msOf = function(v){ return typeof v==='number'? v : (typeof v==='string'? (Date.parse(v)||0) : 0); };
    rows.sort(function(a,b){ return msOf(b.at)-msOf(a.at); });
    return { rows: rows, malformed_rows: (j && j.malformed_rows) || 0, ok: !!(j && (j.ok===true||j.rows||j.groups)) };
  }
  function urgencyOf(r){
    if(r.urgency) return r.urgency;
    var at = typeof r.at==='number'? r.at : Date.parse(r.at);
    return { waiting_ms: Math.max(0, Date.now()-(isNaN(at)?Date.now():at)),
      expired: r.status==='waiting' && r.expires_at!=null && Date.now()>Date.parse(r.expires_at),
      answered: r.status==='answered' };
  }
  function loadRequests(){
    if(!state.project){ state.requests=null; renderWaitColumn(); return; }
    fetch('/sandbar-executor-panel/api/requests?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.requests = normalizeRequests(j);
      renderWaitColumn();
    }).catch(function(){ state.requests = null; renderWaitColumn(); });
  }
  function traceLine(r){
    var t = 'Request id: ' + r.id;
    if(r.raised_by) t = 'Raised by session ' + r.raised_by + '. ' + t;
    t += '. Default action: ' + (r.default_action ? r.default_action : 'none') + '.';
    return t;
  }
  function rowHead(r, cls){
    var u = urgencyOf(r);
    var meta = esc(r.kind) + ' · ' + esc(fmtWaiting(u.waiting_ms));
    if(u.expired) meta += ' · expired. It still waits.';
    if(r.status==='answered') meta = esc(r.kind);
    return '<div class="head" data-id="'+esc(r.id)+'"><span class="dot '+cls+'"></span>'
      + '<span class="txt">'+esc(r.question)+'</span>'
      + '<span class="meta">'+meta+'</span><span class="chev">&#9656;</span></div>';
  }
  function rowBody(r){
    if(r.status==='answered'){
      return '<div class="body"><div class="detail">'+esc(r.detail||'(no detail was given)')+'</div>'
        + '<div class="given">You answered: '+esc(r.answer||'')+'</div>'
        + '<div class="trace">'+esc(traceLine(r))+'</div></div>';
    }
    var controls;
    // t261003-14（review #2）：宿主点过「Type an answer」的行，下次渲染直接给输入框，
    // 不再给按钮排——否则 revealed 的草稿在重建时无处安放。
    if(hasOptions(r) && !state.revealedIds.has(r.id)){
      controls = '<div class="opts">';
      var opts = r.options;
      for(var i=0;i<opts.length;i++){
        controls += '<button data-answer="'+esc(opts[i])+'"'+(i===0?' class="primary"':'')+'>'+esc(opts[i])+'</button>';
      }
      controls += '<button class="other" data-reveal="1">Type an answer</button></div>';
    } else {
      controls = '<div class="answer"><input placeholder="Type an answer" data-answerbox="1"><button data-sendbox="1">Send</button></div>';
    }
    return '<div class="body"><div class="detail">'+esc(r.detail||'(no detail was given)')+'</div>'
      + controls
      + '<div class="trace">'+esc(traceLine(r))+'</div></div>';
  }
  // t261003-09 缺陷 3：Overview 里唯一的会话入口。standalone（无父页）= 显式禁用
  // 并一句话说明原因；无声明会话同样禁用点名去处。按钮只发一条 postMessage，
  // 结果只落一行文案——不造轮询/重试/状态条（t261003-06 已删的形态不还魂）。
  function updateOpenBtn(sess){
    var btn = el('openSessionBtn');
    if(window.parent === window){ btn.disabled = true; var hint = 'Open this panel from the console to use this button.'; btn.title = hint; el('sessionMsg').textContent = hint; return; }
    if(!sess){ btn.disabled = true; btn.title = 'No executor session is declared. Declare one in Settings.'; return; }
    btn.disabled = false; btn.title = 'Open session ' + sess + ' in the console.';
  }
  function renderWaitColumn(){
    var st = state.requests;
    var waitHtml = '', doneHtml = '';
    var waiting = [], answered = [];
    if(st && st.ok===true){ var sp = splitWaiting(st.rows); waiting = sp.waiting; answered = sp.answered; }
    else if(!st){ waitHtml = '<div class="act" style="border:0"><span class="say muted">The request ledger could not be reached. This is not an empty inbox.</span></div>'; }
    // t261003-14：展开态来自 state.openIds（键=id），轮询重建不折叠宿主展开的行。
    var openOf = function(id){ return state.openIds.has(String(id)) ? 'true' : 'false'; };
    for(var i=0;i<waiting.length;i++) waitHtml += '<div class="row wait" data-open="'+openOf(waiting[i].id)+'" data-row="'+esc(waiting[i].id)+'">'+rowHead(waiting[i],'amber')+rowBody(waiting[i])+'</div>';
    for(var j=0;j<answered.length;j++) doneHtml += '<div class="row done" data-open="'+openOf(answered[j].id)+'" data-row="'+esc(answered[j].id)+'">'+rowHead(answered[j],'grey')+rowBody(answered[j])+'</div>';
    // 重建前快照焦点（输入框光标）与各详情块滚动位置，重建后原样放回。
    // 滚动位置直接从 DOM 读——scroll 事件是异步派的，程序化滚动在重建前可能还没派到，
    // 只靠监听器记会有竞态（t261003-14 截图证据里真实踩到过）。
    var focusSnap = null;
    var active = document.activeElement;
    if(active && active.tagName === 'INPUT'){
      var frow = active.closest('[data-row]');
      if(frow) focusSnap = { id: frow.dataset.row, selStart: active.selectionStart, selEnd: active.selectionEnd };
    }
    var scrollSnap = {};
    Array.prototype.forEach.call(document.querySelectorAll('[data-row] .detail'), function(d){
      scrollSnap[d.closest('[data-row]').dataset.row] = d.scrollTop;
    });
    el('waitList').innerHTML = waitHtml;
    el('doneList').innerHTML = doneHtml;
    el('waitHead').textContent = 'Needs your answer · ' + waiting.length;
    el('waitEmpty').style.display = (waiting.length===0 && st && st.ok===true) ? '' : 'none';
    el('doneHead2').textContent = 'Answered · ' + answered.length;
    el('doneWrap').style.display = answered.length===0 ? 'none' : '';
    var badge = el('reqBadge');
    badge.textContent = String(waiting.length);
    badge.className = 'badge' + (waiting.length===0 ? ' zero' : '');
    bindRows(el('waitList'));
    bindRows(el('doneList'));
    restoreRowState(focusSnap, scrollSnap);
  }
  // t261003-14：重建后按 id 放回滚动位置、草稿文本与焦点光标。
  // 滚动优先用重建前的 DOM 快照（无竞态），缺席才回落 onscroll 监听器记下的值。
  function restoreRowState(focusSnap, scrollSnap){
    Array.prototype.forEach.call(document.querySelectorAll('[data-row]'), function(row){
      var id = row.dataset.row;
      if(id in state.drafts){
        var box = row.querySelector('input[data-answerbox]');
        if(box) box.value = state.drafts[id];
      }
      var det = row.querySelector('.detail');
      if(det){
        var top = scrollSnap && (id in scrollSnap) ? scrollSnap[id] : state.detailScroll[id];
        if(top) det.scrollTop = top;
      }
    });
    if(focusSnap){
      var escId = window.CSS && window.CSS.escape ? window.CSS.escape(focusSnap.id) : focusSnap.id.replace(/"/g, '\\"');
      var frow = document.querySelector('[data-row="'+escId+'"]');
      var input = frow && frow.querySelector('input');
      if(input){
        input.focus();
        try{ input.setSelectionRange(focusSnap.selStart, focusSnap.selEnd); }catch(e){}
      }
    }
  }
  function bindRows(root){
    Array.prototype.forEach.call(root.querySelectorAll('.head[data-id]'), function(h){
      h.onclick = function(){
        var row = h.parentElement;
        // t261003-14：开合写进 state（真源），dataset 只是渲染投影。
        var id = row.dataset.row;
        if(state.openIds.has(id)){ state.openIds.delete(id); row.dataset.open = 'false'; }
        else { state.openIds.add(id); row.dataset.open = 'true'; }
      };
    });
    // 详情块滚动位置：滚动即记，重建后放回（读长内容跨轮询不掉位）。
    Array.prototype.forEach.call(root.querySelectorAll('.detail'), function(d){
      d.onscroll = function(){ state.detailScroll[d.closest('[data-row]').dataset.row] = d.scrollTop; };
    });
    // 自由文本草稿：每敲一次记一次，轮询重建后原样填回；Enter=发送。
    // t261003-14：Enter 绑定从「点开 reveal 那一刻的内联闭包」移到这里——否则轮询重建出
    // 的输入框（含 restored 的 reveal 框）没有任何 Enter 处理，敲回车就没了。
    Array.prototype.forEach.call(root.querySelectorAll('input[data-answerbox]'), function(inp){
      var rowId = inp.closest('[data-row]').dataset.row;
      inp.addEventListener('input', function(){ state.drafts[rowId] = inp.value; });
      inp.onkeydown = function(e){ if(e.key==='Enter' && inp.value.trim()!=='') sendAnswer(rowId, inp.value); };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-answer]'), function(b){
      b.onclick = function(){ sendAnswer(b.closest('[data-row]').dataset.row, b.dataset.answer); };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-reveal]'), function(b){
      b.onclick = function(){
        var opts = b.parentElement;
        var box = document.createElement('div');
        box.className = 'answer';
        box.innerHTML = '<input placeholder="Type an answer"><button>Send</button>';
        opts.replaceWith(box);
        var input = box.querySelector('input');
        var rowId = box.closest('[data-row]').dataset.row;
        // t261003-14：点开即记 revealedIds + 草稿监听——下一次轮询渲染直接给输入框并填回草稿。
        state.revealedIds.add(rowId);
        input.addEventListener('input', function(){ state.drafts[rowId] = input.value; });
        box.querySelector('button').onclick = function(){ if(input.value.trim()!=='') sendAnswer(rowId, input.value); else input.focus(); };
        input.onkeydown = function(e){ if(e.key==='Enter' && input.value.trim()!=='') sendAnswer(rowId, input.value); };
        input.focus();
      };
    });
    Array.prototype.forEach.call(root.querySelectorAll('button[data-sendbox]'), function(b){
      b.onclick = function(){
        var input = b.parentElement.querySelector('input');
        if(input.value.trim()!=='') sendAnswer(b.closest('[data-row]').dataset.row, input.value); else input.focus();
      };
    });
  }
  function sendAnswer(id, answer){
    postJson('/sandbar-executor-panel/api/requests/answer', {project: state.project, id: id, answer: answer, by:'host'})
      .then(function(j){
        if(j.ok!==true){ alert('The answer was rejected: '+(j.error||'?')); }
        else {
          // t261003-14（review #3）：发送成功才清草稿与 reveal 态——被拒的草稿原样保留。
          delete state.drafts[id];
          state.revealedIds.delete(id);
        }
        loadRequests();
      })
      .catch(function(e){ alert('The answer failed to send: '+((e&&e.message)||e)); });
  }
  // ---- recent actions (right column) ----
  function loadActions(){
    if(!state.project){ state.actions=null; renderActions(); return; }
    fetch('/sandbar-executor-panel/api/actions?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.actions = j; renderActions();
    }).catch(function(){ state.actions = {ok:false, reason:'the actions endpoint could not be reached'}; renderActions(); });
  }
  function renderActions(){
    var a = state.actions, html = '';
    if(!state.project){ html = ''; }
    else if(!a || a.ok!==true){
      // 显式降级：点名原因，绝不渲染成空列表冒充「最近没动作」。
      html = '<div class="act" style="border:0"><span class="say muted">No action list. ' + esc(a&&a.reason ? a.reason : 'The source is not known.') + '</span></div>';
    } else if(a.actions.length===0){
      html = '<div class="act" style="border:0"><span class="say muted">The audit log holds no showable action. Rows: bad ' + esc(a.malformed_rows) + ' · unknown kind ' + esc(a.unmapped_rows) + ' · missing permission ' + esc(a.missing_authorization_rows) + '.</span></div>';
    } else {
      for(var i=0;i<a.actions.length;i++){
        var x = a.actions[i];
        var cls = {Sign:'sign','Send back':'sendback',Rerun:'retry','Open ticket':'open',Pause:'pause',Resume:'pause','Pause or resume':'pause',Cancel:'cancel'}[x.action]||'pause';
        html += '<div class="act"><span class="t">'+esc(hhmmLocal(x.at))+'</span>'
          + '<span class="pill '+cls+'" title="Allowed by the '+esc(x.permission)+' permission.">'+esc(x.action)+'</span>'
          + '<span class="tk">'+esc(x.ticket)+'</span>'
          + '<span class="say">'+esc(x.result||'done')+'</span></div>';
      }
    }
    el('actList').innerHTML = html;
  }

  // ---- Alerts / Ledger (STE copy) ----
  function renderAlertsLedger(){
    var st = state.status;
    if(!st){
      el('alertBanner').innerHTML = bannerHtml(pickDegraded({reachable: state.reachable===true}).label, true);
      el('alertList').innerHTML=''; el('alertHead').textContent='Recent · 0';
      el('ledgerGrid').innerHTML=''; el('ledgerFile').textContent=''; el('ledgerEvents').innerHTML='';
      return;
    }
    var rows = st.alerts||[];
    el('alertHead').textContent = 'Recent · ' + rows.length;
    var html = '';
    for(var i=0;i<rows.length;i++){
      var a2 = rows[i];
      var cls = a2.level==='redline' ? 'red' : (a2.night_muted ? 'blue' : 'amber');
      html += '<div class="row"><div class="head" style="cursor:default"><span class="dot '+cls+'"></span>'
        + '<span class="txt">'+esc(a2.title)+'</span>'
        + '<span class="meta">'+esc(hhmmLocal(a2.at))+(a2.night_muted?' · night-muted':'')+'</span></div></div>';
    }
    if(rows.length===0) html = '<div class="empty">No alerts exist. The watchdog writes an alert only when a rule fires.</div>';
    el('alertList').innerHTML = html;
    el('alertBanner').innerHTML = rows.some(function(x){return x.night_muted;}) ? bannerHtml('Rows marked night-muted were silenced by the night policy. Redline alerts still play a sound.') : '';
    var lg = st.ledger||{};
    el('ledgerGrid').innerHTML =
      '<div class="cell"><b>'+esc(lg.rows_seen!=null?lg.rows_seen:'—')+'</b><span>rows</span></div>'
      + '<div class="cell"><b>'+esc(fmtProportion(lg.dupes_skipped, lg.rows_seen))+'</b><span>duplicates</span></div>'
      + '<div class="cell"><b>'+esc(lg.malformed_rows!=null?lg.malformed_rows:'—')+'</b><span>bad rows</span></div>'
      + '<div class="cell"><b>'+esc(lg.gaps_seen!=null?lg.gaps_seen:'—')+'</b><span>gaps</span></div>';
    el('ledgerFile').textContent = lg.path || 'The ledger path is not known.';
    var ev = '';
    var wakes = st.wakes||[];
    for(var k=0;k<Math.min(wakes.length,3);k++){
      var w2 = wakes[k];
      ev += '<div class="act"><span class="t">'+esc(hhmmLocal(w2.at))+'</span><span class="pill open">WAKE</span>'
        + '<span class="tk">'+esc(w2.ticket||w2.id||'')+'</span><span class="say">'+esc(wakeRowSentence(w2))+'</span></div>';
    }
    if(!ev) ev = '<div class="act" style="border:0"><span class="say muted">No wakes yet. The watchdog adds a row here when it wakes an executor.</span></div>';
    el('ledgerEvents').innerHTML = ev;
  }

  // ---- Grants tab ----
  function loadGrants(){
    if(!state.project){ state.grants=null; renderGrants(); return; }
    fetch('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.grants = j; renderGrants(); renderOverviewStrip();
    }).catch(function(){ state.grants = {ok:false, error:'the grants endpoint could not be reached'}; renderGrants(); });
  }
  function declaredSessions(){
    var g = state.grants;
    if(g && g.session_readout && Array.isArray(g.session_readout.sessions)) return g.session_readout.sessions;
    var d = g && g.declaration;
    return d && Array.isArray(d.executor_sessions) ? d.executor_sessions : [];
  }
  function renderGrants(){
    if(state.grants && state.grants.ok===false){
      el('grantsBanner').innerHTML = bannerHtml('Grants are not available. Reason: '+(state.grants.error||'?'), true);
      return;
    }
    var g = state.grants || {};
    var sr = g.session_readout || null;
    var sessions = declaredSessions();
    if(!el('grantSession').value) el('grantSession').value = sessions[0] || '';
    // 有活跃夜间档=读出面的 granted_ops 已含全部六项——开关跟着 granted_ops 走。
    var grantedSet = {};
    (g.granted_ops||[]).forEach(function(op){ grantedSet[op]=1; });
    var html = '';
    for(var i=0;i<PERMS.length;i++){
      var p = PERMS[i];
      var on = grantedSet[p[0]]===1;
      html += '<div class="line"><div class="lab">'+esc(p[1])+' <small>'+esc(p[2])+'</small></div>'
        + '<div class="sw grant" data-op="'+esc(p[0])+'" data-on="'+String(on)+'"></div></div>';
    }
    el('permList').innerHTML = html;
    Array.prototype.forEach.call(el('permList').querySelectorAll('.sw.grant'), function(s){
      s.onclick = function(){ s.dataset.on = s.dataset.on==='true' ? 'false' : 'true'; syncMaster(); };
    });
    var count = g.granted_ops ? g.granted_ops.length : 0;
    el('masterSw').dataset.on = String(masterOn(count));
    el('masterSw').onclick = function(){
      var on = el('masterSw').dataset.on==='true';
      setAllSwitches(!on);
      syncMaster();
    };
    el('grantsReadout').textContent = sr ? sr.sentence : (g.grants && g.grants.readout_note ? g.grants.readout_note : '');
    if(g.declaration_state && g.declaration_state.kind && g.declaration_state.kind!=='ok'){
      el('grantsBanner').innerHTML = bannerHtml('The grants declaration cannot be read ('+g.declaration_state.kind+'). Nothing is granted. Detail: '+(g.declaration_state.error||'none'), true);
    } else if(!g.declaration_state || g.declaration_state.declared===false){
      el('grantsBanner').innerHTML = bannerHtml('No grants declaration exists yet. Save once to create it. Nothing is granted before that.', false);
    } else {
      el('grantsBanner').innerHTML = '';
    }
    el('grantsMatrix').innerHTML = g.grants && g.grants.rows && g.grants.rows.length
      ? '<div class="sect lead">Capability matrix</div><div class="muted" style="font-size:11px">The list below shows what each permission means per template. A row here is not a grant. Only the switches above grant.</div><table style="margin-top:6px"><tr><th>Permission</th><th>Template</th><th>Granted</th></tr>'
        + g.grants.rows.map(function(r){ return '<tr><td>'+esc(r.op)+'</td><td>'+esc(r.template)+'</td><td>'+(r.granted===true?'<span class="good">yes</span>':'<span class="muted">no</span>')+'</td></tr>'; }).join('') + '</table>'
      : '';
    el('grantsSaveOut').innerHTML = grantsSaveMsg;
  }
  function setAllSwitches(on){
    Array.prototype.forEach.call(el('permList').querySelectorAll('.sw.grant'), function(s){ s.dataset.on = String(on); });
  }
  function syncMaster(){
    var n = el('permList').querySelectorAll('.sw.grant[data-on="true"]').length;
    el('masterSw').dataset.on = String(masterOn(n));
    el('grantChip').textContent = chipLabel(n, 6);
  }
  function saveGrants(){
    if(!state.project) return;
    var grants = {};
    Array.prototype.forEach.call(el('permList').querySelectorAll('.sw.grant'), function(s){
      if(s.dataset.on==='true') grants[s.dataset.op] = true;
    });
    var body = { grants: grants, by: 'host' };
    var sess = el('grantSession').value.trim();
    if(sess) body.executor_sessions = [sess];
    postJson('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project), body)
      .then(function(j){
        grantsSaveMsg = j.saved===true ? '<span class="good">Saved.</span>'
          : '<span class="bad">The save was rejected. The file did not change. Reason: '+esc(j.error||j.reason||'?')+'</span>';
        el('grantsSaveOut').innerHTML = grantsSaveMsg;
        loadGrants();
      })
      .catch(function(e){ grantsSaveMsg = '<span class="bad">The save failed to send: '+esc((e&&e.message)||String(e))+'</span>'; el('grantsSaveOut').innerHTML = grantsSaveMsg; });
  }
  function masterSwitch(enabled){
    if(!state.project) return;
    postJson('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project), {op:'master', enabled: enabled, by:'host'})
      .then(function(j){
        if(j.saved!==true){ alert('The change was rejected: '+(j.error||j.reason||'?')); }
        loadGrants();
      })
      .catch(function(e){ alert('The change failed to send: '+((e&&e.message)||e)); });
  }

  // ---- Settings (watchdog knobs; a different face from the executor switch) ----
  function loadSettings(){
    if(!state.project){ return; }
    fetch('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.settings = j; renderSettings();
    }).catch(function(){ state.settings={ok:false,error:'the settings endpoint could not be reached'}; renderSettings(); });
  }
  var KNOBS = [
    ['enabled','boolean','The watchdog runs.'],
    ['executor_session','string','The session the watchdog serves.'],
    ['stall_minutes','number','Minutes without motion raise a stall alert.'],
    ['reconcile_seconds','number','Seconds between two reconciles.'],
    ['alerts.enabled','boolean','The watchdog raises alerts.'],
    ['alerts.sound','boolean','A new alert plays a sound.'],
    ['alerts.desktop','boolean','A new alert shows on the desktop.'],
    ['alerts.night.start','hhmm','Night starts at this time.'],
    ['alerts.night.end','hhmm','Night ends at this time.'],
    ['alerts.night.policy','policy','The night alert policy.'],
    ['alerts.redline','string[]','These rules always alert, even at night.'],
    ['alerts.keep_days','number','Days to keep alerts.']
  ];
  function getIn(o,path){ var parts=path.split('.'); for(var i=0;i<parts.length;i++){ if(o==null) return undefined; o=o[parts[i]]; } return o; }
  function setIn(o,path,v){ var parts=path.split('.'); var c=o; for(var i=0;i<parts.length-1;i++){ c[parts[i]]=c[parts[i]]||{}; c=c[parts[i]]; } c[parts[parts.length-1]]=v; }
  function provenanceMap(st){
    return (st && (st.config_provenance && st.config_provenance.keys || st.provenance && st.provenance.keys)) || {};
  }
  function provenanceFor(st, path){
    if(st && st.night_override && st.night_override_active && path==='alerts.night.policy') return 'The sleep toggle set this. It ends at '+new Date(st.night_override.until).toISOString().slice(0,16)+'.';
    var m = provenanceMap(st);
    return m[path] ? String(m[path]) : 'The factory default sets this.';
  }
  function renderSettings(){
    var st = state.settings;
    if(!st || st.ok===false){ el('setBanners').innerHTML = bannerHtml(st && st.error ? st.error : 'The settings endpoint could not be reached.', true); el('setKnobs').innerHTML=''; return; }
    var b='';
    if(st.config_error) b += bannerHtml('The loader rejected the declaration: '+st.config_error, true);
    if(st.declared===false) b += bannerHtml('No watchdog declaration exists. A save creates it.');
    if(st.night_override_expired) b += bannerHtml('The night policy expired. The policy is still "'+esc(st.night_override&&st.night_override.policy)+'". Save to change it. Nothing reverts on its own.');
    el('setBanners').innerHTML=b;
    var cfg = st.config||{};
    var html = '';
    for(var i=0;i<KNOBS.length;i++){
      var path=KNOBS[i][0], type=KNOBS[i][1], v=getIn(cfg,path);
      html += '<div class="knob"><div>'+esc(path)+'</div><div>'+inputFor(path,type,v)+'</div><div class="src">'+esc(provenanceFor(st,path))+'</div></div>';
    }
    el('setKnobs').innerHTML = html;
    el('saveResult').innerHTML = saveMsg;
  }
  // idFor 是 id 生成的唯一真源（inputFor 建面 + readInput 读面共用）——
  // 用 split/join 而不是正则（模板字符串吃反斜杠的教训，t261001-10）。
  function idFor(path){ return 'kb_'+path.split('.').join('_'); }
  function inputFor(path,type,v){
    var id=idFor(path);
    if(type==='boolean') return '<input type="checkbox" id="'+id+'"'+(v?' checked':'')+'>';
    if(type==='policy'){ return '<select id="'+id+'">'+['silent','redline-only','normal'].map(function(p){return '<option'+(p===v?' selected':'')+'>'+p+'</option>';}).join('')+'</select>'; }
    if(type==='string[]') return '<input type="text" id="'+id+'" value="'+esc((v||[]).join(','))+'" size="40">';
    return '<input type="text" id="'+id+'" value="'+esc(v==null?'':v)+'" size="36">';
  }
  function readInput(path,type){
    var n=el(idFor(path));
    if(type==='boolean') return n.checked;
    if(type==='number'){ var x=Number(n.value); return Number.isFinite(x)?x:n.value; }
    if(type==='string[]') return n.value.split(',').map(function(s){return s.trim();}).filter(Boolean);
    return n.value;
  }
  el('saveBtn').onclick = function(){
    if(!state.project) return;
    var st = state.settings; if(!st || st.ok===false) return;
    var cfg = st.config||{};
    var next = JSON.parse(JSON.stringify(cfg));
    for(var i=0;i<KNOBS.length;i++){ setIn(next, KNOBS[i][0], readInput(KNOBS[i][0], KNOBS[i][1])); }
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'save', config:next})
      .then(function(j){
        saveMsg = j.saved===true ? '<span class="good">Saved. The loader accepted the file.</span>'
          : '<span class="bad">REJECTED. The file did not change: '+esc(j.error||j.reason||'?')+'</span>';
        el('saveResult').innerHTML = saveMsg;
        loadSettings();
      })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  el('revokeBtn').onclick = function(){
    if(!state.project) return;
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'revoke'})
      .then(function(j){ if(j.saved!==true){ saveMsg='<span class="bad">REJECTED: '+esc(j.error||'?')+'</span>'; el('saveResult').innerHTML = saveMsg; } loadSettings(); })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  el('sleepBtn').onclick = function(){
    if(!state.project) return;
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'sleep', policy:'redline-only', until: Date.now()+8*3600*1000})
      .then(function(j){ if(j.ok!==true){ saveMsg = '<span class="bad">The sleep toggle was rejected: '+esc(j.error||'?')+'</span>'; el('saveResult').innerHTML = saveMsg; } loadSettings(); })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  el('wakeBtn').onclick = function(){
    if(!state.project) return;
    var st = state.settings; if(!st || st.ok===false) return;
    var cfg = st.config||{};
    var next = JSON.parse(JSON.stringify(cfg));
    setIn(next,'alerts.night.policy', st.factory_defaults? st.factory_defaults.alerts.night.policy : 'redline-only');
    postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'save', config:next})
      .then(function(){ loadSettings(); })
      .catch(function(e){ saveMsg = saveFailHtml(e); el('saveResult').innerHTML = saveMsg; });
  };
  function saveFailHtml(e){
    return '<span class="bad">SAVE FAILED. Nothing was written: '+esc((e&&e.message)||String(e))+'</span>';
  }
  function postJson(url, obj){
    return fetch(url, {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(obj)})
      .then(function(r){ return r.json(); });
  }

  // ---- tab switching ----
  var PANES = [['t-overview','paneOv'],['t-grants','paneGrants'],['t-alerts','paneAlert'],['t-ledger','paneLedger'],['t-settings','paneSet']];
  function showTab(id){
    for(var i=0;i<PANES.length;i++){
      el(PANES[i][1]).style.display = (PANES[i][0]===id) ? '' : 'none';
    }
  }
  Array.prototype.forEach.call(document.querySelectorAll('input.tab'), function(r){
    r.onchange = function(){ if(r.checked) showTab(r.id); };
  });

  // ---- boot ----
  el('giveAllBtn').onclick = function(){ setAllSwitches(true); syncMaster(); };
  el('giveNoneBtn').onclick = function(){ setAllSwitches(false); syncMaster(); };
  el('grantsSave').onclick = saveGrants;
  el('powerBtn').onclick = function(){
    masterSwitch(el('powerBtn').dataset.on !== 'true');
  };
  el('openSessionBtn').onclick = function(){
    if(window.parent === window || !state.session) return;
    el('sessionMsg').textContent = 'Opening the session in the console.';
    window.parent.postMessage({ type: 'sandbar-executor-panel:open-session', sessionId: state.session }, window.location.origin);
  };
  window.addEventListener('message', function(ev){
    if(ev.origin !== window.location.origin) return;
    var d = ev.data;
    if(!d || d.type !== 'sandbar-executor-panel:open-session-result') return;
    el('sessionMsg').textContent = d.ok === true ? 'The session is open in the console.' : 'The console could not open the session.';
  });
  el('doneHeadBtn').onclick = function(){
    var w = el('doneWrap');
    w.dataset.open = w.dataset.open==='true' ? 'false' : 'true';
  };
  var urlProj = ''; try{ urlProj = new URLSearchParams(location.search).get('project') || ''; }catch(e){}
  // t261003-09 缺陷 2：workbench 深链恒带 theme=light|dark；缺席/畸形 → 不设
  // data-theme，落 prefers-color-scheme（themeParamOf 纯函数，单测与页面同一份实现）。
  try{ var themeParam = themeParamOf(new URLSearchParams(location.search).get('theme')); if(themeParam) document.documentElement.dataset.theme = themeParam; }catch(e){}
  function setProject(p){
    state.project = p || '';
    el('projChip').textContent = state.project;
    el('noProject').style.display = state.project ? 'none' : '';
    el('footNote').textContent = state.project ? ('Project: ' + state.project + '. The lists refresh every ' + (POLL_MS/1000) + ' seconds.') : '';
    saveMsg=''; grantsSaveMsg=''; el('grantSession').value='';
    try{ window.__panelBeepCount = Number(localStorage.getItem(beepCountKey())||'0')||0; }catch(e){}
    if(!state.project){ renderWaitColumn(); renderActions(); renderGrants(); return; }
    poll(); loadRequests(); loadActions(); loadSettings(); loadGrants();
  }
  setInterval(function(){ if(state.project){ poll(); loadRequests(); loadActions(); } }, POLL_MS);
  window.__panelSelect = setProject; // testability seam (browser scenario drives project selection)
  // t261003-14（review #1）：手动触发一轮轮询（poll+loadRequests+loadActions），浏览器
  // 测试注入周期用它，不等真实 5s 墙钟。
  window.__panelTick = function(){ if(state.project){ poll(); loadRequests(); loadActions(); } };
  setProject(urlProj);
})();
</script>
</body>
</html>`

export const PANEL_HTML = PANEL_PAGE_HTML // 兼容别名（本票内部引用）
