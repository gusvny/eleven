#!/usr/bin/env node
// lib_stage_ui_surface.mjs — stage 控制台 UI 兼容面自动断言（t260916-25）。
//
// 用途：对 stage_console.sh 起的人工测试台（独立端口/独立 DSH_HOME 的 host-native
// dsh）做升级前后 UI 面自动断言：首页（token 兑换认证）、组合插件包逐名探测、
// workbench 宿主 API、拷入旧会话数据面。被 `server/tools/stage_console.sh
// selfcheck` 调用（token 由壳自动从 console.log 提取传入），也可独立跑：
//   node integration/lib_stage_ui_surface.mjs --base-url http://127.0.0.1:3199 \
//        --home /tmp/dsh-stage [--token XXX] [--json] [--selftest]
//
// 三态退出码（integration 执行契约同口径）：0=全绿；1=断言红；2=环境红/用法红。
// 绝不造假绿：探不到的口径明示（info/环境红），不冒充通过。
//
// 认证语义（0.1.5-rc.2 实弹实证）：dsh web 需认证——GET / 匿名=401；
//   GET /?token=X → 303 + Set-Cookie（dsh-auth-<instance>，Max-Age 30 天）；
//   带 cookie 的 GET / → 200。undici fetch 默认 redirect:follow 且不带
//   Set-Cookie，会把 303 跟成 401——故本库一律 redirect:manual + 自实现
//   cookie jar，token 由壳从 console.log 提取传入。
//
// 组合包断言口径（review R1，锚定实测不锚定票面措辞）：首页资产（<script src>
//   与 <link href>，&amp; 解码）逐个取回，五个 sandbar 包名逐名报告命中出处。
//   0.1.5-rc.2 首页 HTML 实证：53 文件 combo（/plugins/??...，即票面「组合插件
//   包 13.2MB」）的列表里含 sandbar-admin-ui / sandbar-knowledge / sandbar-
//   providers / sandbar-workbench 四包的 client.js；sandbar-temporal-tools 不在
//   （纯模型工具插件、无浏览器半——cordis.patch.yml 注释吻合）→ 必过下限=实测
//   四名，temporal-tools 记 info（覆盖=五软链在位+人工清单）。
//
// info 断言面（不断言，人工清单覆盖）：/sandbar-admin/api/*、/sandbar-knowledge/api/*
//   等未实测路径只记录状态码，防「未实测路径误红」逼人当场削断言。
//
// 红线静态自保（--selftest 内）：读本库与 stage_console.sh 源码，断言不存在
//   指向保护端口（3099/7233/8233）的 URL、壳侧不存在 pkill/killall。
//
// 边界（review R6 同款声明）：本库只服务 stage_console.sh 人工测试台，不入场景
//   供给链；自动化场景舞台归 integration/stage_docker.py 单点。
import { createServer } from 'node:http';
import {
  existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync,
  statSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
// 壳脚本绝对路径（红线静态自保的第二读面；相对本库=仓库根/server/tools）。
const SHELL_PATH = path.join(HERE, '..', 'server', 'tools', 'stage_console.sh');

// sandbar 插件族五包名（真源 server/profile/cordis.patch.yml + 化石软链）。
export const ALL_PLUGIN_NAMES = [
  'sandbar-workbench', 'sandbar-admin-ui', 'sandbar-knowledge',
  'sandbar-providers', 'sandbar-temporal-tools',
];

// 组合包必过下限（review R1 回填）：0.1.5-rc.2 首页 53 文件 combo 列表实证的
// 四名（temporal-tools 无浏览器半，不在此列，走 info）。
export const DEFAULT_REQUIRED_BUNDLE_NAMES = [
  'sandbar-workbench', 'sandbar-admin-ui', 'sandbar-knowledge', 'sandbar-providers',
];

// workbench 宿主 API 必过候选（票面实测三路径；≥1 条 200+JSON 可解析即绿）。
const WORKBENCH_API_CANDIDATES = [
  '/sandbar-workbench/api/build-info',
  '/sandbar-workbench/api/wf/projects',
  '/sandbar-workbench/api/wf/inspection/tickets',
];
// info 探测面（其余插件 API 前缀 seam——不断言，人工清单覆盖）。
const INFO_API_CANDIDATES = [
  '/sandbar-admin/api/routes',
  '/sandbar-knowledge/api/index',
];

export class UsageError extends Error {}

// ---------- 参数 ----------
export function parseArgs(argv) {
  const opts = { requireBundleNames: DEFAULT_REQUIRED_BUNDLE_NAMES.slice() };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const need = (flag) => {
      if (i + 1 >= argv.length) throw new UsageError(`${flag} 缺值`);
      return argv[++i];
    };
    switch (a) {
      case '--base-url': opts.baseUrl = need(a); break;
      case '--home': opts.home = need(a); break;
      case '--token': opts.token = need(a); break;
      case '--session-dir': opts.sessionDir = need(a); break;
      case '--json': opts.json = true; break;
      case '--selftest': opts.selftest = true; break;
      case '--require-bundle-names':
        opts.requireBundleNames = need(a).split(',').map((s) => s.trim()).filter(Boolean);
        break;
      case '--timeout-ms': {
        const v = Number(need(a));
        if (!Number.isFinite(v) || v <= 0) throw new UsageError('--timeout-ms 必须为正数');
        opts.timeoutMs = v;
        break;
      }
      default: throw new UsageError(`未知参数：${a}`);
    }
  }
  if (opts.baseUrl) opts.baseUrl = opts.baseUrl.replace(/\/+$/, '');
  if (!opts.selftest && !opts.baseUrl) throw new UsageError('缺 --base-url（或改用 --selftest）');
  return opts;
}

// ---------- cookie jar（dsh web 认证：token 兑换 303 → Set-Cookie → 200） ----------
export function makeCookieJar() {
  const m = new Map();
  return {
    header: () => (m.size ? [...m].map(([k, v]) => `${k}=${v}`).join('; ') : ''),
    absorb(resp) {
      const list = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [];
      for (const c of list) {
        const kv = c.split(';')[0];
        const i = kv.indexOf('=');
        if (i > 0) m.set(kv.slice(0, i).trim(), kv.slice(i + 1).trim());
      }
    },
  };
}

// 带认证的取原语：redirect:'manual' + 手动跟跳（带 jar，最多 3 跳）。
// （undici 默认 follow 不带 Set-Cookie，会把 303 跟成 401——实证后弃用。）
async function fetchRaw(url, timeoutMs, jar) {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(new Error(`超时 ${timeoutMs}ms`)), timeoutMs);
  const hdrs = () => (jar && jar.header() ? { cookie: jar.header() } : {});
  try {
    let resp = await fetch(url, { signal: ac.signal, redirect: 'manual', headers: hdrs() });
    if (jar) jar.absorb(resp);
    let hop = 0;
    while (resp.status >= 300 && resp.status < 400 && resp.headers.get('location') && hop < 3) {
      const next = new URL(resp.headers.get('location'), url).toString();
      resp = await fetch(next, { signal: ac.signal, redirect: 'manual', headers: hdrs() });
      if (jar) jar.absorb(resp);
      hop++;
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    return { ok: true, status: resp.status, buf, contentType: resp.headers.get('content-type') || '' };
  } catch (e) {
    return { ok: false, err: String((e && e.message) || e) };
  } finally {
    clearTimeout(timer);
  }
}

// 首页资产提取：<script src> + <link href>（0.1.5 的 53 文件插件 combo 挂在
// link 上，实证），&amp; 解码；只取 .js 或 /plugins/ 开头（favicon/manifest 不取）。
export function extractAssetUrls(html, baseUrl) {
  const out = [];
  const push = (raw) => {
    const u = raw.replace(/&amp;/g, '&');
    if (!(u.includes('.js') || u.startsWith('/plugins/'))) return;
    try {
      const abs = new URL(u, baseUrl);
      if (abs.protocol === 'http:' || abs.protocol === 'https:') out.push(abs.toString());
    } catch { /* 非法 URL 跳过 */ }
  };
  for (const m of html.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)) push(m[1]);
  for (const m of html.matchAll(/<link[^>]+href=["']([^"']+)["']/gi)) push(m[1]);
  return out.slice(0, 20); // 防失控
}

// ---------- 检查面 ----------
function sessionDirCheck(dir) {
  if (!dir) return { state: 'env_red', detail: '未提供 --home/--session-dir，无法检查会话数据面' };
  if (!existsSync(dir)) return { state: 'env_red', detail: `目录不存在：${dir}（台未 prepare？）` };
  let st;
  try { st = statSync(dir); } catch (e) { return { state: 'env_red', detail: String(e) }; }
  if (!st.isDirectory()) return { state: 'env_red', detail: `不是目录：${dir}` };
  const entries = readdirSync(dir).filter((n) => !n.startsWith('.'));
  if (entries.length === 0) {
    return { state: 'red', detail: 'sessions 为空——prepare 未拷入或源为空（「读得到拷入的旧代会话」不成立）' };
  }
  let dirs = 0; let fileRefs = 0;
  for (const n of entries.slice(0, 200)) {
    const p = path.join(dir, n);
    try {
      if (statSync(p).isDirectory()) {
        dirs++;
        try { fileRefs += readdirSync(p).length; } catch { /* 读不了按 0 */ }
      } else {
        fileRefs++;
      }
    } catch { /* 竞态容忍 */ }
  }
  if (dirs === 0 && fileRefs === 0) return { state: 'red', detail: 'sessions 非空但读不到任何内容' };
  return { state: 'pass', detail: `${entries.length} 项（会话目录 ${dirs}，文件引用 ${fileRefs}）` };
}

// 认证 + 取首页：200 → {ok,html}；401/303 且可兑换 → 兑换后重取；失败带明细。
export async function ensureAuthedHome(base, ctx) {
  const jar = ctx.jar;
  let r = await fetchRaw(base + '/', ctx.timeoutMs, jar);
  if (r.ok && r.status === 200) return { ok: true, html: r.buf.toString('utf8'), bytes: r.buf.length };
  if ((r.status === 401 || r.status === 303) && ctx.token) {
    await fetchRaw(`${base}/?token=${encodeURIComponent(ctx.token)}`, ctx.timeoutMs, jar);
    r = await fetchRaw(base + '/', ctx.timeoutMs, jar);
    if (r.ok && r.status === 200) return { ok: true, html: r.buf.toString('utf8'), bytes: r.buf.length };
    return { ok: false, detail: `token 兑换后首页仍 ${r.ok ? r.status : 'ERR ' + r.err}` };
  }
  if (r.status === 401 || r.status === 303) {
    return { authRequired: true, ok: false, detail: '首页要求认证（401）且未提供 --token——selfcheck 会自动从 console.log 提取 token；独立跑请传 --token' };
  }
  if (!r.ok) return { connFail: true, ok: false, detail: `连接失败：${r.err}` };
  return { ok: false, detail: `首页 HTTP ${r.status}` };
}

// 主跑面：返回 { checks: [{id,label,state,detail}] }。state ∈ pass|red|env_red|info。
export async function runChecks(opts) {
  const checks = [];
  const rec = (id, label, state, detail) => checks.push({ id, label, state, detail: detail || '' });
  const timeoutMs = opts.timeoutMs ?? 30000;
  const base = opts.baseUrl;
  const required = opts.requireBundleNames || [];
  const jar = makeCookieJar();
  const ctx = { jar, token: opts.token, timeoutMs };

  // 1) 会话数据面（纯 FS，不依赖网络——台不可达时也如实报告）
  const sessDir = opts.sessionDir || (opts.home ? path.join(opts.home, 'sessions') : null);
  const sess = sessionDirCheck(sessDir);
  rec('sessions-fs', '拷入旧会话数据面（FS 口径）', sess.state, sess.detail);

  // 2) 首页（含 token 兑换认证）
  const home = base ? await ensureAuthedHome(base, ctx) : { connFail: true, ok: false, detail: '未提供 --base-url' };
  const reachable = home.ok === true;
  if (!base) rec('homepage', 'GET /（含 token 兑换）', 'env_red', home.detail);
  else if (home.ok) rec('homepage', 'GET /（含 token 兑换）', 'pass', `200（${home.bytes} bytes）`);
  else if (home.connFail || home.authRequired) rec('homepage', 'GET /（含 token 兑换）', 'env_red', home.detail);
  else rec('homepage', 'GET /（含 token 兑换）', 'red', home.detail);

  // 3) 组合包逐名探测（review R1 口径：逐名报告，必过下限=实测回填）
  const srcs = reachable ? extractAssetUrls(home.html, base) : [];
  const bundles = [];
  for (const u of srcs) {
    const r = await fetchRaw(u, timeoutMs, jar);
    bundles.push({ url: u, res: r });
  }
  if (reachable && srcs.length === 0 && required.length > 0) {
    rec('bundle:scan', '首页资产提取', 'red', '0 个 js 资产——HTML 截断或结构变化（实证首页应引 53 文件级插件 combo）');
  }
  for (const name of ALL_PLUGIN_NAMES) {
    let hit = null;
    for (const b of bundles) {
      if (b.res.ok && b.res.status === 200 && b.res.buf.includes(name)) { hit = b.url; break; }
    }
    const req = required.includes(name);
    if (hit) {
      rec(`bundle:${name}`, `组合包命中 ${name}`, 'pass',
        `${hit.slice(base.length).slice(0, 60)}${hit.length - base.length > 60 ? '…' : ''}`);
    } else if (!reachable) {
      // 台不可达时「没探到」= 环境缺位不是面破——打 env_red 不打 red。
      // 否则「忘了起台」被聚合层误报成产品红（exit 1），三态判据被侵蚀
      // （仲裁 F2：纯环境红必须 exit 2）。
      rec(`bundle:${name}`, req ? `组合包必过名未探 ${name}` : `组合包未命中 ${name}（非必过）`, 'env_red', '跳过：台不可达');
    } else if (req) {
      rec(`bundle:${name}`, `组合包必过名未命中 ${name}`, 'red',
        `探到的 ${bundles.length} 个 bundle 均不含（bundle 状态：${bundles.map((b) => `${b.url.split('/').pop().slice(0, 40)}=${b.res.ok ? b.res.status : 'ERR'}`).join(', ') || '无'}）`);
    } else {
      rec(`bundle:${name}`, `组合包未命中 ${name}（非必过）`, 'info',
        '实测无浏览器半（纯模型工具插件）；覆盖=五软链在位（prepare 校验）+人工清单');
    }
  }
  for (const b of bundles) {
    if (!b.res.ok || b.res.status !== 200) {
      rec(`bundle-fetch:${b.url.slice(base.length)}`, '组合包资产取回', b.res.ok ? 'red' : 'env_red',
        b.res.ok ? `HTTP ${b.res.status}` : `取回失败：${b.res.err}`);
    }
  }

  // 4) workbench 宿主 API（带认证 cookie；≥1 条 200+JSON 即绿；单条汇总 id 稳定）
  if (reachable) {
    const tried = [];
    for (const p of WORKBENCH_API_CANDIDATES) {
      const r = await fetchRaw(base + p, timeoutMs, jar);
      let jsonOk = false;
      if (r.ok && r.status === 200) {
        try { JSON.parse(r.buf.toString('utf8')); jsonOk = true; } catch { /* 非 JSON */ }
      }
      tried.push({ p, status: r.ok ? r.status : null, err: r.ok ? null : r.err, jsonOk });
    }
    const hits = tried.filter((t) => t.status === 200 && t.jsonOk);
    const fmt = (t) => `${t.p}=${t.err ? 'ERR ' + t.err : t.status}${t.status === 200 && !t.jsonOk ? '(非JSON)' : ''}`;
    if (hits.length > 0) {
      rec('workbench-api', 'workbench 宿主 API ≥1 条 200', 'pass',
        `命中 ${hits.map((t) => `${t.p}=200 JSON`).join('；')}｜未命中 ${tried.length - hits.length} 条（${tried.filter((t) => !(t.status === 200 && t.jsonOk)).map(fmt).join('；') || '无'}）`);
    } else {
      rec('workbench-api', 'workbench 宿主 API ≥1 条 200', 'red', tried.map(fmt).join('；'));
    }
  } else {
    rec('workbench-api', 'workbench 宿主 API ≥1 条 200', 'env_red', '跳过：台不可达');
  }

  // 5) info 探测面（不断言——人工清单覆盖）
  if (reachable) {
    for (const p of INFO_API_CANDIDATES) {
      const r = await fetchRaw(base + p, timeoutMs, jar);
      rec(`info:${p}`, `info 探测 ${p}`, 'info',
        r.ok ? `HTTP ${r.status}${r.status === 200 ? `（${r.buf.length}B）` : ''}（info 不断言，人工清单覆盖）` : `ERR ${r.err}`);
    }
  }

  return { checks };
}

// 三态聚合（t260904-12 执行契约）：red>0 → 1（产品红，面破了）；
// 否则 envRed>0 → 2（环境红，台没起/连不上/凭据缺——不是升级的错）；
// 否则 0（全绿；info 不影响出口）。前提：检测层必须把「探不到」归 env_red
// （仲裁 F2：不可达时必过名曾误打 red → 纯环境红聚合出 1）。
export function summarize(checks) {
  const red = checks.filter((c) => c.state === 'red').length;
  const envRed = checks.filter((c) => c.state === 'env_red').length;
  const pass = checks.filter((c) => c.state === 'pass').length;
  const info = checks.filter((c) => c.state === 'info').length;
  const code = red > 0 ? 1 : envRed > 0 ? 2 : 0;
  return { red, envRed, pass, info, code };
}

// ---------- 红线静态自保 ----------
export function staticRedlineGuard() {
  const problems = [];
  const protectedUrlRe = /https?:\/\/[^\s'"`]*?(3099|7233|8233)/;
  const killAllRe = /\b(pkill|killall)\b/;
  // 击杀命令面只在壳侧存在——本库对 pkill/killall 的出现仅是注释/正则字面，
  // 按文件定域检查（killScan=false 只查保护端口 URL），防自扫描误报。
  const files = [
    { label: 'lib_stage_ui_surface.mjs', p: fileURLToPath(import.meta.url), killScan: false },
    { label: 'stage_console.sh', p: SHELL_PATH, killScan: true },
  ];
  for (const f of files) {
    if (!existsSync(f.p)) {
      problems.push(`红线自保：文件缺失 ${f.label}（${f.p}）`);
      continue;
    }
    const lines = readFileSync(f.p, 'utf8').split('\n');
    lines.forEach((line, idx) => {
      if (protectedUrlRe.test(line)) problems.push(`${f.label}:${idx + 1} 出现指向保护端口的 URL：${line.trim()}`);
      if (f.killScan && killAllRe.test(line)) problems.push(`${f.label}:${idx + 1} 出现全进程面击杀命令：${line.trim()}`);
    });
  }
  return { ok: problems.length === 0, problems };
}

// ---------- selftest（畸形输入桩，全部本地 stub，不依赖真 dsh） ----------
function makeHandler(routes) {
  return (req, res) => {
    const r = routes[req.url.split('?')[0]];
    if (!r) { res.statusCode = 404; res.end('not found'); return; }
    if (r.hang) return; // 挂起不回——触发客户端超时
    res.statusCode = r.status ?? 200;
    for (const [k, v] of Object.entries(r.headers || {})) res.setHeader(k, v);
    res.end(r.raw ?? r.body ?? '');
  };
}

async function withStub(routes, fn) {
  const server = createServer(makeHandler(routes));
  await new Promise((res) => server.listen(0, '127.0.0.1', res));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    return await fn(base);
  } finally {
    try { if (server.closeAllConnections) server.closeAllConnections(); } catch { /* 容忍 */ }
    server.unref();
    await Promise.race([
      new Promise((res) => server.close(res)),
      new Promise((res) => setTimeout(res, 300).unref()),
    ]);
  }
}

function makeTempHome() {
  const dir = mkdtempSync(path.join(tmpdir(), 'sc-ui-selftest-'));
  const sess = path.join(dir, 'sessions', '--fixture--');
  mkdirSync(sess, { recursive: true });
  writeFileSync(path.join(sess, 'session.jsonl'), '{"role":"user","text":"hi"}\n');
  return dir;
}

const HTML_WITH = (srcs) => `<!doctype html><html><body>${srcs.map((s) => `<script src="${s}"></script>`).join('')}</body></html>`;

async function selftest() {
  const results = [];
  const expect = (name, cond, detail) => results.push({ name, ok: !!cond, detail: detail || '' });
  const states = (r) => Object.fromEntries(r.checks.map((c) => [c.id, c.state]));
  const tmpHomes = [];

  // S1 happy path：script 形态全绿
  {
    const home = makeTempHome(); tmpHomes.push(home);
    await withStub({
      '/': { headers: { 'content-type': 'text/html' }, body: HTML_WITH(['/app.js']) },
      '/app.js': { headers: { 'content-type': 'application/javascript' }, body: 'var x=1;/* sandbar-workbench code */' },
      '/sandbar-workbench/api/build-info': { body: JSON.stringify({ version: 'stub' }) },
    }, async (base) => {
      const r = await runChecks({ baseUrl: base, home, requireBundleNames: ['sandbar-workbench'], timeoutMs: 3000 });
      const s = states(r);
      expect('S1 happy: homepage pass', s['homepage'] === 'pass');
      expect('S1 happy: 必过名命中 pass', s['bundle:sandbar-workbench'] === 'pass');
      expect('S1 happy: workbench-api pass', s['workbench-api'] === 'pass');
      expect('S1 happy: sessions-fs pass', s['sessions-fs'] === 'pass');
      expect('S1 happy: 退出码 0', summarize(r.checks).code === 0);
    });
  }
  // S2 HTTP 500 → 首页红
  {
    await withStub({ '/': { status: 500, body: 'boom' } }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: [], timeoutMs: 3000 });
      expect('S2 500: homepage red', states(r)['homepage'] === 'red');
      expect('S2 500: 退出码 1', summarize(r.checks).code === 1);
    });
  }
  // S3 慢响应 → 环境红（超时）
  {
    await withStub({ '/': { hang: true } }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: [], timeoutMs: 250 });
      expect('S3 慢响应: homepage env_red', states(r)['homepage'] === 'env_red');
      expect('S3 慢响应: 退出码 2', summarize(r.checks).code === 2);
    });
  }
  // S4 截断 HTML（标签未闭合）→ 0 资产 → 必过名红
  {
    await withStub({ '/': { headers: { 'content-type': 'text/html' }, body: '<html><script src="/b.js' } }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: ['sandbar-workbench'], timeoutMs: 3000 });
      expect('S4 截断: bundle:scan red', r.checks.some((c) => c.id === 'bundle:scan' && c.state === 'red'));
      expect('S4 截断: 必过名 red', states(r)['bundle:sandbar-workbench'] === 'red');
    });
  }
  // S5 无任何资产引用 → 同上红
  {
    await withStub({ '/': { headers: { 'content-type': 'text/html' }, body: '<html><body>hi</body></html>' } }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: ['sandbar-workbench'], timeoutMs: 3000 });
      expect('S5 无资产: 必过名 red', states(r)['bundle:sandbar-workbench'] === 'red');
    });
  }
  // S6 空 bundle（200 空体）→ 名不命中红
  {
    await withStub({
      '/': { headers: { 'content-type': 'text/html' }, body: HTML_WITH(['/b.js']) },
      '/b.js': { body: '' },
    }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: ['sandbar-workbench'], timeoutMs: 3000 });
      expect('S6 空bundle: 必过名 red', states(r)['bundle:sandbar-workbench'] === 'red');
    });
  }
  // S7 二进制乱码 bundle → 不崩、红
  {
    await withStub({
      '/': { headers: { 'content-type': 'text/html' }, body: HTML_WITH(['/b.js']) },
      '/b.js': { raw: Buffer.from([0xff, 0xfe, 0x00, 0x01, 0x80]) },
    }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: ['sandbar-workbench'], timeoutMs: 3000 });
      expect('S7 乱码: 必过名 red（不崩）', states(r)['bundle:sandbar-workbench'] === 'red');
    });
  }
  // S8 API 200 但非 JSON → 不算命中 → 全未命中红
  {
    const home = makeTempHome(); tmpHomes.push(home);
    await withStub({
      '/': { headers: { 'content-type': 'text/html' }, body: 'no scripts' },
      '/sandbar-workbench/api/build-info': { body: 'not-json{' },
    }, async (base) => {
      const r = await runChecks({ baseUrl: base, home, requireBundleNames: [], timeoutMs: 3000 });
      expect('S8 非JSON API: workbench-api red', states(r)['workbench-api'] === 'red');
    });
  }
  // S9 dsh 认证语义（0.1.5 实弹同构）：匿名 401 → ?token= 303+Set-Cookie → 带
  //   cookie 200；combo 挂 <link href> 且含 &amp; 需解码 → 全绿。
  {
    const home = makeTempHome(); tmpHomes.push(home);
    let sawToken = false;
    let sawCookie = false;
    const HTML = '<!doctype html><html><head><link href="/plugins/??sandbar-workbench/client.js&amp;rev=abc" rel="modulepreload"></head><body></body></html>';
    const server = createServer((req, res) => {
      const hasCookie = /dsh-auth/.test(req.headers.cookie || '');
      if (req.url.startsWith('/?token=')) {
        sawToken = true;
        res.statusCode = 303;
        res.setHeader('location', '/');
        res.setHeader('set-cookie', 'dsh-auth-x=v1.abc; Path=/; HttpOnly');
        res.end();
        return;
      }
      if (req.url === '/') {
        if (!hasCookie) { res.statusCode = 401; res.end('unauthorized'); return; }
        sawCookie = true;
        res.statusCode = 200;
        res.setHeader('content-type', 'text/html');
        res.end(HTML);
        return;
      }
      if (req.url.startsWith('/plugins/')) {
        if (!hasCookie) { res.statusCode = 401; res.end('unauthorized'); return; }
        res.statusCode = 200;
        res.setHeader('content-type', 'application/javascript');
        res.end('/* combo */ sandbar-workbench client code');
        return;
      }
      if (req.url.startsWith('/sandbar-workbench/api/build-info')) {
        res.statusCode = 200;
        res.setHeader('content-type', 'application/json');
        res.end(JSON.stringify({ ok: 1 }));
        return;
      }
      res.statusCode = 404; res.end('nope');
    });
    await new Promise((res) => server.listen(0, '127.0.0.1', res));
    const base = `http://127.0.0.1:${server.address().port}`;
    try {
      const r = await runChecks({ baseUrl: base, home, requireBundleNames: ['sandbar-workbench'], token: 't0ken', timeoutMs: 3000 });
      const s = states(r);
      expect('S9 认证流: homepage pass（token 兑换+cookie）', s['homepage'] === 'pass');
      expect('S9 认证流: link combo 提取+&amp; 解码命中', s['bundle:sandbar-workbench'] === 'pass');
      expect('S9 认证流: workbench-api 带 cookie pass', s['workbench-api'] === 'pass');
      expect('S9 认证流: 确实发生 401→兑换→带 cookie', sawToken && sawCookie, `token=${sawToken} cookie=${sawCookie}`);
      expect('S9 认证流: 退出码 0', summarize(r.checks).code === 0);
    } finally {
      try { if (server.closeAllConnections) server.closeAllConnections(); } catch { /* 容忍 */ }
      server.unref();
      server.close();
    }
  }
  // S10 401 且无 token → 环境红（凭据缺失，不是面破）
  {
    await withStub({ '/': { status: 401, body: 'unauthorized' } }, async (base) => {
      const r = await runChecks({ baseUrl: base, requireBundleNames: [], timeoutMs: 3000 });
      expect('S10 401无token: homepage env_red', states(r)['homepage'] === 'env_red');
      expect('S10 401无token: 零产品红（必过名归 env_red）', r.checks.every((c) => c.state !== 'red'));
      expect('S10 401无token: 退出码 2', summarize(r.checks).code === 2);
    });
  }
  // S11 sessions 空目录 → 红；缺目录 → 环境红
  {
    const empty = mkdtempSync(path.join(tmpdir(), 'sc-ui-empty-')); tmpHomes.push(empty);
    mkdirSync(path.join(empty, 'sessions'));
    expect('S11a sessions 空 → red', sessionDirCheck(path.join(empty, 'sessions')).state === 'red');
    expect('S11b sessions 缺 → env_red',
      sessionDirCheck(path.join(empty, 'nope', 'sessions')).state === 'env_red');
  }
  // S12 畸形参数 → UsageError
  {
    let threw = '';
    try { parseArgs(['--timeout-ms', 'abc']); } catch (e) { threw = String(e); }
    expect('S12a 畸形 timeout → usage 红', threw.includes('--timeout-ms'), threw);
    threw = '';
    try { parseArgs([]); } catch (e) { threw = String(e); }
    expect('S12b 缺 base-url → usage 红', threw.includes('--base-url'), threw);
    threw = '';
    try { parseArgs(['--bogus']); } catch (e) { threw = String(e); }
    expect('S12c 未知参数 → usage 红', threw.includes('--bogus'), threw);
  }
  // S13 红线静态自保（本库 + 壳脚本）
  {
    const g = staticRedlineGuard();
    expect('S13 红线自保 ok', g.ok, g.problems.join('；'));
  }
  // S14 资产提取器直测：script+link 混合、&amp; 解码、非 js 过滤
  {
    const html = [
      '<script src="/a.js"></script>',
      '<link href="/plugins/??x/client.js&amp;rev=1" rel="modulepreload">',
      '<link href="./assets/b.js">',
      '<link href="/favicon.svg">',
      '<a href="/somewhere">x</a>',
    ].join('');
    const urls = extractAssetUrls(html, 'http://stub/');
    expect('S14a 提取 script+link 且解码 &amp;',
      urls.includes('http://stub/a.js') && urls.includes('http://stub/plugins/??x/client.js&rev=1'),
      urls.join(' | '));
    expect('S14b favicon/svg 与普通链接不取', !urls.some((u) => u.includes('favicon') || u.includes('somewhere')));
  }

  // 清理临时 home
  for (const d of tmpHomes) { try { rmSync(d, { recursive: true, force: true }); } catch { /* 容忍 */ } }

  let fail = 0;
  for (const r of results) {
    if (r.ok) console.log(`  ok  ${r.name}`);
    else { fail++; console.error(`  RED ${r.name}${r.detail ? ` —— ${r.detail}` : ''}`); }
  }
  console.log(`== selftest：${results.length - fail}/${results.length} 绿 ==`);
  return fail === 0 ? 0 : 1;
}

// ---------- CLI ----------
async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(`usage红: ${e.message}`);
    console.error('用法: node lib_stage_ui_surface.mjs --base-url URL --home DIR [--token T] [--json] [--selftest] [--require-bundle-names a,b] [--timeout-ms N]');
    process.exit(2);
  }
  if (opts.selftest) process.exit(await selftest());

  const { checks } = await runChecks(opts);
  const sum = summarize(checks);
  if (opts.json) {
    console.log(JSON.stringify({ ok: sum.code === 0, exit_code: sum.code, summary: sum, checks }, null, 2));
  } else {
    console.log('== stage UI 面自检（t260916-25）==');
    for (const c of checks) {
      const tag = c.state === 'pass' ? 'ok     ' : c.state === 'red' ? 'RED    ' : c.state === 'env_red' ? 'ENV_RED' : 'info   ';
      console.log(`${tag} ${c.label}${c.detail ? ` —— ${c.detail}` : ''}`);
    }
    console.log(`== 结果：${sum.code === 0 ? '绿' : sum.code === 1 ? '红' : '环境红'}（pass ${sum.pass} / red ${sum.red} / env_red ${sum.envRed} / info ${sum.info}）==`);
    console.log('⚠ 只读警示：本 stage 连生产 Temporal/项目注册表——UI 写操作会打到生产。');
  }
  process.exit(sum.code);
}

main().catch((e) => {
  console.error(`RED: 未预期异常：${e && e.stack || e}`);
  process.exit(1);
});
