// lib_platform_context.mjs —— t260905-09 场景族共享夹具（非 sc_ 前缀=共享代码，不登记 SCENARIOS）。
//
// 沿 lib_charter.mjs 口径（t260905-09 review 放行时逐项声明的取舍清单）：
//   ✅ 带 3199 隔离台基址 + 拒 3099 红线 + t260904-12 三态 makeResults（pass/fail/
//      env_fail/na，exit 0/1/2，绝不假绿放行）。
//   ✅ 带 隔离台健康检查。
//   ❌ 不带 charter 端点/项目清单 helpers——本票场景不消费（charter 子用例由 16 号
//      既有场景族守，intent 级不重复；本票 stacked 场景只把 charter 小条在场当
//      前置卫兵，不重断 charter 契约）。
// 自足精简（同 lib_charter 对 t260904-05 的先例）：不跨票目录 import——已收口
// 票的 lib 可能随退役清理，场景族共享代码只允许下沉到 lib_stage_console 这类
// 常驻基建，不挂在单票目录上。

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { ensureStageConsole } from '../lib_stage_console.mjs';

/**
 * 隔离台基址懒取（不顶层 await）：ro 契约场景是纯静态面，不得被供给台健康度
 * 绑架（顶层 ensureStageConsole 会让 ENV_FAIL 抢在场景逻辑之前=静态契约多了
 * 环境依赖子用例）；browser 场景在自己的 T0 卫兵链里显式取台。
 */
let _base = null;
export async function stageBase() {
  if (_base === null) _base = (await ensureStageConsole()).base;
  return _base;
}

/** 生产控制台红线：命中 3099 直接拒跑（宁可自家测试不跑；同 lib_charter）。 */
export function refuseProductionConsole(base) {
  if (base.includes(':3099')) {
    console.error('refusing to run: test console points at the production console (3099)');
    process.exit(1);
  }
}

/** 执行契约（t260904-12 三态，同 lib_charter.makeResults 口径，逐字带过）。 */
export function makeResults() {
  const results = [];
  const OK = new Set(['pass', 'fail', 'env_fail', 'na']);
  return {
    record(name, status, detail = '') {
      if (!OK.has(status)) throw new Error(`非法状态词 ${status}（词表 pass/fail/env_fail/na）`);
      results.push({ name, status, detail });
      console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`);
    },
    summarize() {
      const p = results.filter(r => r.status === 'pass').length;
      const e = results.filter(r => r.status === 'env_fail').length;
      const n = results.filter(r => r.status === 'na').length;
      const f = results.filter(r => r.status === 'fail').length;
      const allNa = results.length > 0 && n === results.length;
      console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`);
      process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0);
    },
  };
}

/** 隔离台健康检查（workbench API 可达=测试台活着；同 lib_charter 口径）。 */
export async function consoleHealthy(base) {
  try {
    const r = await fetch(`${base}/sandbar-workbench/api/wf/projects`, { signal: AbortSignal.timeout(3000) });
    return r.ok;
  } catch { return false; }
}

/** 本票实现真源面（源锚复核用：pre-implement/未部署 精确归因的依据）。 */
export const ANCHORS_MODULE = 'server/plugins/workbench/src/client/platform-context-anchors.ts';
export const FOLD_MODULE = 'server/plugins/workbench/src/client/context-fold.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const FX_DIR = join(HERE, 'fixtures');
const FX_PROVENANCE_SEP = '%%%';

/**
 * 装载平台上下文夹具。
 * 返回 { anchor: string, body: string, provenance: string, name: string }[]，
 * anchor=首非空行（前缀锚匹配口径），provenance=%%% 之后的取证来源注。
 */
export function loadFixtures() {
  return readdirSync(FX_DIR).filter(f => f.endsWith('.txt')).sort().map(name => {
    const raw = readFileSync(join(FX_DIR, name), 'utf8');
    const [main, prov = ''] = raw.split(FX_PROVENANCE_SEP);
    const anchor = main.split('\n').map(l => l.trim()).find(l => l !== '') ?? '';
    return { name, anchor, body: main, provenance: prov.trim() };
  });
}

/**
 * 平台上下文叠台夹具（3199 真页 DOM 注入——工单「怎么算好」原话口径：
 * 「夹具把平台启动上下文消息×N+工单台注入×1 叠进同一会话」）。
 * 注入结构=滚动体直接子层（平台消息列表最常见形态）；每条带 data-fx-id 供
 * 场景定位（场景自有属性，非平台结构赌注）。
 * 返回注入的元素 id 清单。归因纪律（review 意见⑥）：注入后 React 重渲染若
 * 触发 removeChild 类异常，pageerror 卫兵子用例会捕到并 fail 留证——夹具手法≠
 * 产品缺陷，证据必须随 detail 上报，不许静默。
 */
export async function injectPlatformBubbles(page, fixtures) {
  return page.evaluate(fxs => {
    const scroll = document.querySelector('[data-conversation-scroll]');
    if (!scroll) return null;
    const ids = [];
    for (const fx of fxs) {
      const el = document.createElement('div');
      el.setAttribute('data-fx-id', fx.name);
      el.textContent = fx.body;
      scroll.appendChild(el);
      ids.push(fx.name);
    }
    return ids;
  }, fixtures);
}

/** 用户可感知断言面（灰盒：只读可见性与文本，不读实现 attr/类名）。 */
export async function foldProbe(page) {
  return page.evaluate(() => {
    const chips = [...document.querySelectorAll('[data-conversation-scroll] *')]
      .filter(el => (el.textContent ?? '').includes('已注入项目背景') && el.children.length === 0);
    const fx = [...document.querySelectorAll('[data-conversation-scroll] [data-fx-id]')];
    const hidden = el => {
      if (!el.isConnected) return 'detached';
      return getComputedStyle(el).display === 'none' ? 'hidden' : 'visible';
    };
    return {
      chipCount: chips.length,
      chipLabel: chips[0]?.textContent ?? '',
      bubbles: fx.map(el => ({ id: el.getAttribute('data-fx-id'), state: hidden(el) })),
    };
  });
}

/** 小条点击（用户操作面：按文本定位小条元素后真点）。 */
export async function clickChip(page) {
  await page.evaluate(() => {
    const chip = [...document.querySelectorAll('[data-conversation-scroll] *')]
      .find(el => (el.textContent ?? '').includes('已注入项目背景') && el.children.length === 0);
    if (chip) chip.click();
  });
}
