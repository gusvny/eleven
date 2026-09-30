/**
 * panel-page.ts —— 面板静态页（t260929-03）：五个 tab、显式降级、页内一声 beep。
 *
 * 为什么是「插件自服务的静态页」而不是 tsdown 构建包：零构建步骤 → 宿主交接=
 * 控制台重启一次装载插件 + 之后纯浏览器刷新；且 beep 决策/降级挑选等纯逻辑
 * **从 page-logic.ts 经 String(fn) 原样嵌入**——单测与页面永远同一份实现，不漂移。
 * 界面文案全英文（宿主令 260925：英文界面+数据不译）；布局参考 mock 260927。
 *
 * 契约偏差（如实声明，review #1）：notify.beep 的已读清除走页面本地 seen-set
 * （localStorage per project）；watchdog 侧 per-key 清除端点属守望者插件改动，
 * 本票 out-of-scope——后果（第二台设备会再响一声）写进交接报告，后续票收口。
 */

import {
  beepDecision, pickDegraded, fmtProportion, fmtWaiting, fmtAge, groupByProject,
} from './page-logic.ts'

/** 纯函数源码嵌入（strip 后即等价 JS；单测直接测这些函数本体）。 */
const EMBEDDED = [
  String(beepDecision), String(pickDegraded), String(fmtProportion),
  String(fmtWaiting), String(fmtAge), String(groupByProject),
].join('\n')

export const PANEL_ROUTE = '/sandbar-executor-panel'
export const PANEL_PAGE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Executor Panel</title>
<style>
:root{--bg:#141a24;--panel:#1b2330;--panel2:#222c3c;--line:#2e394d;--fg:#dbe4f0;--muted:#8ea0b8;--blue:#4da3ff;--red:#ff6b6b;--amber:#ffb454;--green:#7ad48a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 ui-sans-serif,system-ui,sans-serif;padding:14px}
h1{font-size:16px;margin:0 0 10px}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}
select,input[type=text]{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 10px;cursor:pointer}
button:hover{border-color:var(--blue)}
input.tab{position:absolute;opacity:0;pointer-events:none}
.tabs{display:flex;gap:3px;border-bottom:1px solid var(--line);margin-bottom:10px}
.tabs label{padding:5px 10px;font-size:12px;color:var(--muted);border:1px solid transparent;border-bottom:none;cursor:pointer}
.tabs label:hover{color:var(--fg)}
#t-overview:checked~.tabs label[for=t-overview],#t-requests:checked~.tabs label[for=t-requests],#t-alerts:checked~.tabs label[for=t-alerts],#t-ledger:checked~.tabs label[for=t-ledger],#t-settings:checked~.tabs label[for=t-settings]{color:var(--fg);background:var(--panel);border-color:var(--line);border-radius:7px 7px 0 0}
.pane{display:none}
#t-overview:checked~.panes #p-overview,#t-requests:checked~.panes #p-requests,#t-alerts:checked~.panes #p-alerts,#t-ledger:checked~.panes #p-ledger,#t-settings:checked~.panes #p-settings{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.card h3{margin:0 0 4px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.banner{border:1px solid var(--amber);color:var(--amber);background:#2a2313;border-radius:8px;padding:8px 10px;margin-bottom:10px}
.banner.red{border-color:var(--red);color:var(--red);background:#2a1414}
table{width:100%;border-collapse:collapse;font-size:12px;background:var(--panel);border:1px solid var(--line);border-radius:8px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:11px}
.tr-waiting{color:var(--amber)}
.tr-answered{color:var(--muted)}
.flow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12px}
.flow .node{border:1px solid var(--line);border-radius:6px;padding:3px 8px;background:var(--panel2)}
.flow .arr{color:var(--muted)}
.muted{color:var(--muted)}
.master{display:grid;grid-template-columns:280px 1fr;gap:10px}
.mlist{background:var(--panel);border:1px solid var(--line);border-radius:8px;max-height:60vh;overflow:auto}
.mitem{padding:6px 9px;border-bottom:1px solid var(--line);cursor:pointer}
.mitem:hover{background:var(--panel2)}
.mitem.sel{background:var(--panel2);border-left:2px solid var(--blue)}
.grp{padding:4px 9px;font-size:10px;color:var(--muted);text-transform:uppercase;background:var(--panel2)}
.detail{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}
.knob{display:grid;grid-template-columns:180px 1fr 220px;gap:6px;padding:4px 0;border-bottom:1px solid var(--line);align-items:center}
.knob .src{color:var(--muted);font-size:11px;font-family:ui-monospace,monospace}
.bad{color:var(--red)} .good{color:var(--green)}
textarea{width:100%;background:var(--panel2);color:var(--fg);border:1px solid var(--line);border-radius:6px;min-height:60px;font:12px ui-monospace,monospace}
.more{margin:8px 0;color:var(--blue);cursor:pointer}
</style>
</head>
<body>
<h1>Executor Panel</h1>
<div class="bar">
  <label class="muted">Project</label>
  <select id="project"><option value="">(loading projects)</option></select>
  <input type="text" id="freeProject" placeholder="or type any key (undeclared demo)" size="28">
  <button id="go">Load</button>
  <span class="muted" id="pollNote"></span>
</div>
<input class="tab" type="radio" name="tb" id="t-overview" checked>
<input class="tab" type="radio" name="tb" id="t-requests">
<input class="tab" type="radio" name="tb" id="t-alerts">
<input class="tab" type="radio" name="tb" id="t-ledger">
<input class="tab" type="radio" name="tb" id="t-settings">
<div class="tabs">
  <label for="t-overview">Overview</label>
  <label for="t-requests">Requests</label>
  <label for="t-alerts">Alerts</label>
  <label for="t-ledger">Ledger</label>
  <label for="t-settings">Settings</label>
</div>
<div class="panes">
  <div class="pane" id="p-overview"><div id="ovBanners"></div><div class="cards" id="ovCards"></div>
    <div class="flow" id="ovFlow"></div></div>
  <div class="pane" id="p-requests">
    <div class="muted" style="margin-bottom:6px">Requests = the executor is asking YOU. Own ledger, never deleted by the machine, never answered by the machine. Alerts tell you; Requests wait for you.</div>
    <div class="master"><div class="mlist" id="reqList"></div>
    <div class="detail" id="reqDetail"><span class="muted">Select a request.</span></div></div>
    <span class="more" id="reqMore">show more (keeps the tail)</span></div>
  <div class="pane" id="p-alerts"><div id="alertBanner"></div><table id="alertTable"></table>
    <div class="muted" style="margin-top:6px">Alerts = "you should know". An open alert stays information only — it never turns into a decision on its own.</div></div>
  <div class="pane" id="p-ledger"><div id="ledgerHealth"></div><table id="ledgerTable"></table></div>
  <div class="pane" id="p-settings"><div id="setBanners"></div><div id="setGrants"></div><div id="setKnobs"></div></div>
</div>
<script>
` + EMBEDDED + `
(function(){
  var state = { project:'', status:null, reachable:null, requests:null, grants:null, settings:null, reqLimit:20, selected:null };
  var POLL_MS = 5000;
  // beep 计数持久化（同项目口径）：重轮询/刷新后计数不丢——「重轮询零增量」才能被
  // 真断言（计数器与真实发声同代码路径，persist 只是读数口径，不是第二真相源）。
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
    window.__panelBeepCount += 1; // testability seam: incremented by the SAME code path that plays audio
    try{ localStorage.setItem(beepCountKey(), String(window.__panelBeepCount)); }catch(e){}
  }
  function el(id){ return document.getElementById(id); }
  function esc(s){ var d=document.createElement('span'); d.textContent=String(s==null?'':s); return d.innerHTML; }
  function bannerHtml(label,red){ return '<div class="banner'+(red?' red':'')+'">'+esc(label)+'</div>'; }

  // ---- status polling + beep ----
  function poll(){
    if(!state.project) return;
    fetch('/sandbar-watchdog/api/status?project='+encodeURIComponent(state.project))
      .then(function(r){ return r.json().then(function(j){ return { http:r.status, j:j }; }); })
      .then(function(res){
        var okDoc = res.j && res.j.ok === true && res.j.result;
        state.status = okDoc ? res.j.result : null;
        state.reachable = !!okDoc;
        renderOverview();
        renderAlertsLedger(); // Alerts/Ledger tab 随每次轮询刷新（rework gen1：此前漏调用=两 tab 永空）
        tryBeep();
        el('pollNote').textContent = 'polling every ' + (POLL_MS/1000) + 's · last ok ' + new Date().toISOString().slice(11,19);
      })
      .catch(function(){
        state.status = null; state.reachable = false;
        renderOverview(); // route-down degraded banner — never an empty or normal state, never a beep
        renderAlertsLedger(); // 不可达也点名进 Alerts/Ledger（显式降级，不是空态）
      });
  }
  function tryBeep(){
    var st = state.status;
    if(!st || !st.notify) return;
    var seen = seenSet(state.project);
    var d = beepDecision(st.notify, st.alerts, state.project, seen);
    if(d.play){
      for(var i=0;i<d.keys.length;i++){ playBeepOnce(); seen.add(d.keys[i]); } // one beep per new unseen key; never on re-poll
      saveSeen(state.project, seen);
    }
  }

  // ---- Overview ----
  function renderOverview(){
    var st = state.status, b='';
    var dg = pickDegraded({ reachable: state.reachable === true, declared: st?st.declared:undefined, alive: st&&st.heartbeat?st.heartbeat.alive:undefined, config_error: st?st.config_error:null });
    if(dg.kind==='route-down') b += bannerHtml(dg.label, true);
    if(dg.kind==='not-declared'){ el('ovBanners').innerHTML = bannerHtml(dg.label, false); el('ovCards').innerHTML=''; el('ovFlow').innerHTML=''; return; }
    if(dg.kind==='stale') b += bannerHtml(dg.label + ' — reason: ' + (st&&st.heartbeat?st.heartbeat.reason:''), true);
    if(st && st.config_error) b += bannerHtml(dg.label, true);
    if(st && st.last_error) b += bannerHtml('last_error: '+st.last_error, true);
    if(st && st.ledger && st.ledger.unreadable) b += bannerHtml('Event ledger UNREADABLE: '+st.ledger.unreadable, true);
    if(st && st.liveness && st.liveness.engine && st.liveness.engine.online === null) b += bannerHtml('Engine liveness UNKNOWN: '+(st.liveness.engine.detail||''), false);
    if(st && st.self_lock && st.self_lock.state === 'unknown') b += bannerHtml('Self-lock UNKNOWN: '+(st.self_lock.reason||''), false);
    el('ovBanners').innerHTML = b;
    if(!st){ el('ovCards').innerHTML=''; el('ovFlow').innerHTML=''; return; }
    var hb = st.heartbeat||{}, lg = st.ledger||{}, rc = st.reconcile||{}, ex = st.liveness&&st.liveness.executor||null;
    var doing = ex ? (ex.state + (ex.evidence? ' — '+ex.evidence : '')) : 'executor liveness: no signal surface';
    el('ovCards').innerHTML =
      card('Watchdog alive', (hb.alive? '<span class="good">alive</span>' : '<span class="bad">NOT alive</span>') + '<br>last beat: '+esc(fmtAge(hb.age_seconds)) + (hb.reason? '<br><span class="muted">'+esc(hb.reason)+'</span>':'')) +
      card('Ledger watermark', 'offset '+esc(lg.watermark_offset)+' · rows '+esc(lg.rows_seen)+'<br><span class="muted">dupes '+esc(fmtProportion(lg.dupes_skipped, lg.rows_seen))+' · malformed '+esc(fmtProportion(lg.malformed_rows, lg.rows_seen))+' · gaps '+esc(lg.gaps_seen)+'</span>') +
      card('Reconcile', rc? (rc.state==='ok'?'<span class="good">ok</span>':'<span class="bad">'+esc(rc.state)+'</span>') + (rc.reason? '<br><span class="muted">'+esc(rc.reason)+'</span>':'') : '<span class="muted">no reconcile surface</span>') +
      card('Doing now', esc(doing)) +
      card('Startup replay', 'missing '+esc(st.startup&&st.startup.missing_rows)+' · replayed '+esc(st.startup&&st.startup.replayed_rows)) +
      card('Wakes', (st.wakes||[]).length + ' wake(s) delivered') +
      executorSessionCard(st);
    el('ovFlow').innerHTML = flowHtml();
  }
  function card(t,h){ return '<div class="card"><h3>'+t+'</h3>'+h+'</div>'; }
  // Executor-session provenance (t260930-09 scope 6): who created this session, when,
  // with which preset — answered from the watchdog's per-project event ledger.
  function executorSessionCard(st){
    var es = st.executor_session || null;
    var evs = (st.session_provenance && st.session_provenance.events) || [];
    var last = evs.length? evs[evs.length-1] : null;
    var sid = (es && es.session_id) || (last && last.session_id) || null;
    var h = sid ? esc(sid) : '<span class="muted">none yet — the watchdog creates one on demand when this project has work</span>';
    if(last){
      var when = new Date(typeof last.at==='number'? last.at : Date.parse(last.at)||0).toISOString().slice(0,19);
      h += '<br><span class="muted">'+esc(last.action)+' by '+esc(last.by||'?')+' · preset '+esc(last.preset||'?')+' · '+esc(when)+'</span>';
    }
    if(es && es.reason) h += '<br><span class="muted">'+esc(es.last_action||'')+' — '+esc(es.reason)+'</span>';
    if(st.session_provenance && st.session_provenance.malformed_rows>0) h += '<br><span class="bad">provenance ledger has '+esc(st.session_provenance.malformed_rows)+' malformed row(s)</span>';
    return card('Executor session', h);
  }
  function flowHtml(){
    var wakes = 0; try{ wakes = state.status.wakes.length; }catch(e){}
    return ['ticket changes','event ledger','watchdog','executor'].map(function(n){ return '<span class="node">'+n+'</span>'; }).join('<span class="arr">&rarr;</span>')
      + '<span class="arr">&rarr; exits:</span>'
      + '<span class="node good">auto-advance</span><span class="arr">/</span>'
      + '<span class="node">decision recorded</span><span class="arr">/</span>'
      + '<span class="node" style="border-color:var(--amber);color:var(--amber)">call you ('+wakes+' wake(s), 1 beep each new alert)</span>';
  }

  // ---- Requests ----
  function normalizeRequests(j){
    // server returns {groups:[...]} (all projects) or {rows:[...]} (single project); page tolerates both.
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
    var url = '/sandbar-executor-panel/api/requests';
    if(state.project) url += '?project='+encodeURIComponent(state.project);
    fetch(url).then(function(r){return r.json();}).then(function(j){
      state.requests = normalizeRequests(j);
      renderRequests();
    }).catch(function(){ state.requests = null; renderRequests(); });
  }
  function renderRequests(){
    var st = state.requests;
    if(!st || st.ok!==true){ el('reqList').innerHTML = '<div class="mitem muted">requests ledger unreachable (explicit — not an empty inbox)</div>'; return; }
    var rows = st.rows;
    var groups = groupByProject(rows);
    var shown = 0, html='';
    for(var gi=0; gi<groups.length; gi++){
      var g = groups[gi];
      html += '<div class="grp">'+esc(g.project)+'</div>';
      for(var i=0;i<g.rows.length && shown<state.reqLimit;i++,shown++){
        var r = g.rows[i]; var u = urgencyOf(r);
        var cls = r.status==='answered' ? 'tr-answered' : (u.expired ? 'bad' : 'tr-waiting');
        html += '<div class="mitem '+cls+'" data-id="'+esc(r.id)+'" data-project="'+esc(r.project)+'">'
          + esc(String(r.question).slice(0,90))
          + '<br><span class="muted">'+esc(r.kind)+' · waiting '+esc(fmtWaiting(u.waiting_ms))
          + (u.expired? ' · <span class="bad">EXPIRED (still waiting — never auto-closed)</span>':'')
          + (r.status==='answered'? ' · answered by '+esc(r.answered_by||'?'):'')+'</span></div>';
      }
    }
    if(rows.length===0) html = '<div class="mitem muted">no requests in the ledger (nothing is waiting on you)</div>';
    else if(shown<rows.length) html += '<div class="muted" style="padding:4px 9px">'+(rows.length-shown)+' older — use "show more" (tail is kept)</div>';
    el('reqList').innerHTML = html;
    Array.prototype.forEach.call(el('reqList').querySelectorAll('.mitem[data-id]'), function(n){
      n.onclick = function(){ selectRequest(n.dataset.id); };
      if(state.selected===n.dataset.id) n.className += ' sel';
    });
  }
  function selectRequest(id){
    state.selected = id;
    var r = state.requests.rows.find(function(x){ return x.id===id; });
    if(!r) return;
    var u = urgencyOf(r);
    el('reqDetail').innerHTML =
      '<h3>'+esc(r.question)+'</h3>'
      + '<p class="muted">'+esc(r.detail||'')+'</p>'
      + '<p>Kind: '+esc(r.kind)+' · Default action: <b>'+esc(r.default_action||'(none)')+'</b></p>'
      + '<p class="muted">Waiting '+esc(fmtWaiting(u.waiting_ms))+(r.expires_at? ' · expires at '+String(new Date(Date.parse(r.expires_at)).toISOString()).slice(0,19):' · no expiry')
      + ' · project '+esc(r.project)+'</p>'
      + (r.status==='answered'
          ? '<p class="tr-answered">Answered by '+esc(r.answered_by||'?')+': '+esc(r.answer)+'</p>'
          : '<textarea id="answerBox" placeholder="your answer"></textarea><button id="answerBtn">Answer (appends a closing row — the request row is never rewritten)</button>')
      + '<p class="muted">derived · own ledger, never deleted by the machine, never answered by the machine</p>';
    var btn = el('answerBtn');
    if(btn) btn.onclick = function(){
      postJson('/sandbar-executor-panel/api/requests/answer', {project:r.project, id:r.id, answer: el('answerBox').value, by:'host'})
        .then(function(j){ if(j.ok!==true){ alert('Answer rejected: '+(j.error||'?')); } loadRequests(); });
    };
    renderRequests();
  }
  el('reqMore').onclick = function(){ state.reqLimit += 20; renderRequests(); };

  // ---- Alerts / Ledger ----
  function renderAlertsLedger(){
    var st = state.status;
    if(!st){ el('alertBanner').innerHTML = bannerHtml(pickDegraded({reachable: state.reachable===true}).label, true); el('alertTable').innerHTML=''; el('ledgerTable').innerHTML=''; el('ledgerHealth').innerHTML=''; return; }
    var rows = st.alerts||[];
    var html = '<tr><th>at</th><th>level</th><th>rule</th><th>title</th><th>night</th></tr>';
    for(var i=0;i<rows.length;i++){
      var a = rows[i];
      html += '<tr><td>'+String(new Date(typeof a.at==='number'?a.at:Date.parse(a.at)||0).toISOString()).slice(11,19)+'</td><td>'+esc(a.level)+'</td><td>'+esc(a.rule)+'</td><td>'+esc(a.title)+'</td><td>'+(a.night_muted?'<span class="muted">night-muted</span>':'')+'</td></tr>';
    }
    if(rows.length===0) html += '<tr><td colspan="5" class="muted">no alerts recorded (this is a real empty — alerts exist only when the watchdog wrote them)</td></tr>';
    el('alertTable').innerHTML = html;
    el('alertBanner').innerHTML = rows.some(function(a){return a.night_muted;}) ? bannerHtml('Rows marked night-muted were silenced per the night policy (redline exceptions still beep).') : '';
    var lg = st.ledger||{};
    el('ledgerHealth').innerHTML = '<div class="cards">'
      + card('Health (proportions, absolute numbers mislead)', 'dupes '+esc(fmtProportion(lg.dupes_skipped, lg.rows_seen))+'<br>malformed '+esc(fmtProportion(lg.malformed_rows, lg.rows_seen))+'<br>gaps '+esc(lg.gaps_seen)+' · watermark '+esc(lg.watermark_offset))
      + card('Source', '<span class="muted">'+esc(lg.path||'—')+'</span><br>derived · not the source of truth')
      + '</div>' + (lg.unreadable? bannerHtml('Ledger UNREADABLE: '+lg.unreadable, true) : '');
    el('ledgerTable').innerHTML = '<tr><th colspan="4">raw event stream (paged view lives with the per-project ledger file; health above is from the watchdog status surface)</th></tr>'
      + '<tr><td colspan="4" class="muted">rows_seen '+esc(lg.rows_seen)+' · last row '+esc(lg.last_row_at? String(new Date(typeof lg.last_row_at==='number'?lg.last_row_at:Date.parse(lg.last_row_at)).toISOString()).slice(0,19):'—')+'</td></tr>';
  }

  // ---- Settings ----
  function loadSettings(){
    if(!state.project){ return; }
    fetch('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.settings = j; renderSettings();
    }).catch(function(){ state.settings={ok:false,error:'settings endpoint unreachable'}; renderSettings(); });
    fetch('/sandbar-executor-panel/api/grants?project='+encodeURIComponent(state.project)).then(function(r){return r.json();}).then(function(j){
      state.grants = j; renderSettings();
    }).catch(function(){ state.grants=null; });
  }
  var KNOBS = [
    ['enabled','boolean'],['executor_session','string'],['stall_minutes','number'],['reconcile_seconds','number'],
    ['alerts.enabled','boolean'],['alerts.sound','boolean'],['alerts.desktop','boolean'],
    ['alerts.night.start','hhmm'],['alerts.night.end','hhmm'],['alerts.night.policy','policy'],
    ['alerts.redline','string[]'],['alerts.keep_days','number']
  ];
  function getIn(o,path){ var parts=path.split('.'); for(var i=0;i<parts.length;i++){ if(o==null) return undefined; o=o[parts[i]]; } return o; }
  function setIn(o,path,v){ var parts=path.split('.'); var c=o; for(var i=0;i<parts.length-1;i++){ c[parts[i]]=c[parts[i]]||{}; c=c[parts[i]]; } c[parts[parts.length-1]]=v; }
  function provenanceMap(st){
    return (st && (st.config_provenance && st.config_provenance.keys || st.provenance && st.provenance.keys)) || {};
  }
  function provenanceFor(st, path){
    // WHICH declaration key decided this value (KI-148/149: the host must be able to answer "what decided this").
    if(st && st.night_override && st.night_override_active && path==='alerts.night.policy') return 'panel override (sleep toggle, until '+new Date(st.night_override.until).toISOString()+')';
    var m = provenanceMap(st);
    return m[path] ? String(m[path]) : 'factory-default';
  }
  function renderSettings(){
    var st = state.settings;
    if(!st || st.ok===false){ var eb = bannerHtml(st && st.error ? st.error : 'settings endpoint unreachable', true); el('setBanners').innerHTML=eb; el('setKnobs').innerHTML=''; el('setGrants').innerHTML=''; return; }
    var b='';
    if(st.config_error) b += bannerHtml('Declaration currently REJECTED by loader: '+st.config_error, true);
    if(st.declared===false) b += bannerHtml('Not enrolled — saving below CREATES the declaration (file exists = enrolled).');
    if(st.night_override_expired) b += bannerHtml('Night override EXPIRED (still "'+esc(st.night_override&&st.night_override.policy)+'") — revert or renew explicitly (no silent auto-revert).');
    el('setBanners').innerHTML=b;
    var cfg = st.config||{};
    var html = '';
    for(var i=0;i<KNOBS.length;i++){
      var path=KNOBS[i][0], type=KNOBS[i][1], v=getIn(cfg,path);
      html += '<div class="knob"><div>'+esc(path)+'</div><div>'+inputFor(path,type,v)+'</div><div class="src">decided by: '+esc(provenanceFor(st,path))+'</div></div>';
    }
    html += '<div style="margin-top:8px"><button id="saveBtn">Save (validate-on-write: parsed back through the real loader; rejected saves never touch the file)</button> '
      + '<button id="revokeBtn">One-click revoke (enabled:false)</button> '
      + '<button id="sleepBtn">I am going to sleep (night-only policy + 8h expiry)</button> '
      + '<button id="wakeBtn">Revert night override</button></div><div id="saveResult" class="muted" style="margin-top:6px"></div>';
    el('setKnobs').innerHTML = html;
    el('saveBtn').onclick = function(){
      var next = JSON.parse(JSON.stringify(cfg));
      for(var i=0;i<KNOBS.length;i++){ setIn(next, KNOBS[i][0], readInput(KNOBS[i][0], KNOBS[i][1])); }
      postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'save', config:next})
        .then(function(j){
          el('saveResult').innerHTML = j.saved===true ? '<span class="good">saved & re-validated through the loader</span>' : '<span class="bad">REJECTED (file untouched): '+esc(j.error||j.reason)+'</span>';
          loadSettings();
        });
    };
    el('revokeBtn').onclick = function(){
      postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'revoke'}).then(function(){ loadSettings(); });
    };
    el('sleepBtn').onclick = function(){
      postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'sleep', policy:'redline-only', until: Date.now()+8*3600*1000})
        .then(function(j){ if(j.ok!==true) alert('Sleep toggle rejected: '+(j.error||'?')); loadSettings(); });
    };
    el('wakeBtn').onclick = function(){
      postJson('/sandbar-executor-panel/api/settings?project='+encodeURIComponent(state.project), {op:'save', config: (function(){ var n=JSON.parse(JSON.stringify(cfg)); setIn(n,'alerts.night.policy', st.factory_defaults? st.factory_defaults.alerts.night.policy : 'redline-only'); return n; })()}).then(function(){ loadSettings(); });
    };
    renderGrants();
  }
  function inputFor(path,type,v){
    var id='kb_'+path.replace(/\./g,'_');
    if(type==='boolean') return '<input type="checkbox" id="'+id+'"'+(v?' checked':'')+'>';
    if(type==='policy'){ return '<select id="'+id+'">'+['silent','redline-only','normal'].map(function(p){return '<option'+(p===v?' selected':'')+'>'+p+'</option>';}).join('')+'</select>'; }
    if(type==='string[]') return '<input type="text" id="'+id+'" value="'+esc((v||[]).join(','))+'" size="40">';
    return '<input type="text" id="'+id+'" value="'+esc(v==null?'':v)+'" size="36">';
  }
  function readInput(path,type){
    var id='kb_'+path.replace(/\./g,'_'), n=el(id);
    if(type==='boolean') return n.checked;
    if(type==='number'){ var x=Number(n.value); return Number.isFinite(x)?x:n.value; }
    if(type==='string[]') return n.value.split(',').map(function(s){return s.trim();}).filter(Boolean);
    return n.value;
  }
  function renderGrants(){
    var payload = state.grants;
    if(!payload){ el('setGrants').innerHTML=''; return; }
    var g = payload.grants;
    if(g && g.ok===false){ el('setGrants').innerHTML = bannerHtml('Grants unavailable (explicit, NOT an empty list): '+g.reason); return; }
    var rows = Array.isArray(g) ? g.map(function(x){ return { op:(x.ops||[]).join(', '), template:x.template, template_kind:x.kind||'', reason:'template facts' }; })
      : (g && g.rows) || [];
    var note = g && g.filtered_note;
    var html = '<div class="card" style="margin-bottom:8px"><h3>Grants — derived from the template (decision 10/15), never hand-maintained</h3><table><tr><th>op</th><th>template</th><th>why shown</th></tr>';
    for(var i=0;i<rows.length;i++){
      var r=rows[i];
      html += '<tr><td>'+esc(r.op)+'</td><td>'+esc(r.template)+(r.template_kind? ' ('+esc(r.template_kind)+')':'')+'</td><td class="muted">'+esc(r.reason||'derived: fixed op × template facts')+'</td></tr>';
    }
    if(rows.length===0) html += '<tr><td colspan="3" class="muted">no shown grants (all filtered or revoked)</td></tr>';
    html += '</table>' + (note? '<div class="muted">'+esc(note)+'</div>':'') + '</div>';
    el('setGrants').innerHTML = html;
  }

  function postJson(url, obj){
    return fetch(url, {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(obj)})
      .then(function(r){ return r.json(); });
  }

  // ---- project selection + boot ----
  // t260930-09 scope 8: the dropdown lists EVERY registered project (the watchdog status
  // list endpoint now returns undeclared registry projects too, each carrying its
  // declared flag) — a project can be inspected before anything is declared. The
  // ?project=<key> deep link keeps working.
  function projects(){
    return fetch('/sandbar-watchdog/api/status').then(function(r){return r.json();}).then(function(j){
      var list=[];
      if(j && j.ok===true && j.result && Array.isArray(j.result.projects)){
        j.result.projects.forEach(function(p){ if(p && p.project) list.push({project:p.project, declared:p.declared!==false}); });
      }
      return list;
    }).catch(function(){ return []; });
  }
  function setProject(p){
    state.project = p; state.reqLimit = 20; state.selected = null;
    try{ window.__panelBeepCount = Number(localStorage.getItem(beepCountKey())||'0')||0; }catch(e){}
    if(!p){ el('pollNote').textContent='no project selected'; return; }
    poll(); loadRequests(); loadSettings();
  }
  el('go').onclick = function(){
    var p = el('freeProject').value.trim() || el('project').value;
    setProject(p);
  };
  projects().then(function(list){
    var html = '<option value="">— pick a project (declared or not) —</option>';
    list.forEach(function(p){
      html += '<option value="'+esc(p.project)+'">'+esc(p.project)+(p.declared? '' : ' · not declared')+'</option>';
    });
    el('project').innerHTML = html;
  });
  // deep-link: /?project=<key> selects immediately (bench/scenario entry).
  var urlProj = ''; try{ urlProj = new URLSearchParams(location.search).get('project') || ''; }catch(e){}
  setInterval(function(){ if(state.project){ poll(); loadRequests(); } }, POLL_MS);
  window.__panelSelect = setProject; // testability seam (browser scenario drives project selection)
  if(urlProj){ setProject(urlProj); }
})();
</script>
</body>
</html>`

export const PANEL_HTML = PANEL_PAGE_HTML // 兼容别名（本票内部引用）
