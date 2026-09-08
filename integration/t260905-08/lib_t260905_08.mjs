// lib_t260905_08.mjs — t260905-08 场景族共享夹具（无 sc_ 前缀=共享代码，按清单约定不登记）。
//
// 夹具复用取舍（t260905-08 方案 R6/gen2，对 review_plan gen1 C6 评审纪律的交代）：
//   带过来：隔离端口避让 freePort（fix17 已解决隔离台端口冲突）；进程树 teardown/超时
//   回收 teardownOnExit（全终态回收纪律同源）；playwright 探测 loadPlaywright + 缺依赖
//   env_fail 有声红（KI-036 家族守卫，三态契约「闸内无 SKIP」）；出厂 notice 关闭 dismissNotice；
//   结果记账 makeResults（SUMMARY 末行契约）。
//   不带：fix17 走查步骤（T 系断言/写操作监控）——本票场景只做对比度与 hex 清零断言，
//   无行为走查语义，带过来=死代码。
//   跨票 import 而非复制：同仓路径稳定，fix17 自有场景守其行为；若 fix17 改夹具契约，
//   其场景与本族场景同时红，由后改方同步（防漂移责任，两侧头注对齐）。
import {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
} from '../t260904-17/lib_fix17.mjs';

export {
  tmpRoot, makeRegistryRoot, writeProjectEntry, makeTicketStub,
  bootConsole, teardownOnExit, loadPlaywright, dismissNotice, makeResults,
};

// fnv1a —— 逐字节复制自 server/plugins/workbench/src/shared/project-color.ts（gen2 方案
// R4/C3 钉死：场景内复制实现以换「无 TS loader 依赖」；漂移责任=两侧头注对齐，后改方
// 同步）。仅用于确定性挑码凑满 EPIC_PALETTE 10 槽（守护面用，不生产真值）。
export function fnv1a(input) {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

// 10 槽挑码：对槽位 0-9 各找一个确定性 epic 码（fnv1a('epic:'+code)%10 === slot），
// 播入桩票后全色板 epilogue chip/彩条两档主题下都有对比度断言（R4：防采样盲区）。
export function pickEpicCodes() {
  const slots = Array.from({ length: 10 }, () => null);
  for (let i = 0; slots.some((s) => s === null); i++) {
    const code = `epic-t08-${i}`;
    const slot = fnv1a(`epic:${code}`) % 10;
    if (slots[slot] === null) slots[slot] = code;
  }
  return slots;
}

// 平台两档令牌代表值（gen2 方案钉死；来源=宿主裁定④「模拟平台深/浅两档令牌」授权，
// 定义侧在平台壳不在本仓——代表值与平台真值若有偏差，深档腿可能假绿/假红，交接宿主
// 确认真值或认可代表值；变异腿值=故意低对比，用于证明对比度断言真的在咬）。
export const TOKEN_SETS = {
  light: {
    '--dsw-alias-bg-primary': '#ffffff',
    '--dsw-alias-label-primary': '#1f2328',
    '--dsw-alias-label-secondary': '#57606a',
    '--dsw-alias-border-l': '#d0d7de',
    '--dsw-alias-brand-primary': '#0969da',
    '--dsw-specific-sidebar-fill': '#f9fafb',
  },
  dark: {
    '--dsw-alias-bg-primary': '#16181d',
    '--dsw-alias-label-primary': '#e6e6e9',
    '--dsw-alias-label-secondary': '#9ea2ad',
    '--dsw-alias-border-l': '#30363d',
    '--dsw-alias-brand-primary': '#4493f8',
    '--dsw-specific-sidebar-fill': '#1a1a2e',
  },
  // 变异腿 = 浅档 + 故意低对比的正文色（on #fff ≈ 3.4:1 < 4.5，稳定可咬）
  mutation: {
    '--dsw-alias-bg-primary': '#ffffff',
    '--dsw-alias-label-primary': '#7a7a85',
    '--dsw-alias-label-secondary': '#57606a',
    '--dsw-alias-border-l': '#d0d7de',
    '--dsw-alias-brand-primary': '#0969da',
    '--dsw-specific-sidebar-fill': '#f9fafb',
  },
  // 旧平台腿（t260907-03 腿①，17b673f 热修 commit message「看守场景补旧平台令牌集
  // 随后立案」的立案兑现）：宿主平台 0.1.1-rc.2 无 bg-primary 名、只有 bg-base。
  // 模拟「名不存在」用 knockout——`initial` 对 custom property 是 guaranteed-invalid
  // 态，var() 链在该作用域走下一级 fallback；测试台平台壳自带 bg-primary（且在
  // BODY 级祖先声明，:root 注入穿不透），故浏览器腿必须经 FAITHFUL_FN 把含
  // knockout 的整套令牌打到壳层声明点才造得出真缺席态。bg-base 注入可辨识代表值
  // #f5f8fa（近白平台底，字符串级可辨）：兜底链没接住（链被拆/名被删/值改错）时
  // canvas 落回 #fff 或平台 bg-primary 现值，都不是 #f5f8fa——精确等值断言可辨。
  // 选值约束（gen0 实测边界）：+ 钮文字=45% 项目色混平台前景，其 AA 线在 canvas
  // ≈#f3f6f8（更深的旧平台底会破 4.5，#eef3f8 实测 4.46）——该脆弱面如实交接宿主
  // 确认 0.1.1-rc.2 bg-base 真值，不为本腿绿而虚报深底档可用。
  legacy: {
    '--dsw-alias-bg-primary': 'initial',
    '--dsw-alias-bg-base': '#f5f8fa',
    '--dsw-alias-label-primary': '#1f2328',
    '--dsw-alias-label-secondary': '#57606a',
    '--dsw-alias-border-l': '#d0d7de',
    '--dsw-alias-brand-primary': '#0969da',
    '--dsw-specific-sidebar-fill': '#f9fafb',
  },
};

// !important：平台壳可能以元素内联/后置样式注入同名令牌（实测隔离台
// --dsw-specific-sidebar-fill 即如此），注入腿必须压过平台现值才能模拟指定档位。
export const cssVarsBlock = (set) =>
  `:root{${Object.entries(set).map(([k, v]) => `${k}:${v} !important`).join(';')}}`;
