// 溯游管理台 UI 插件构建：产物形态对齐 dsh 客户端模块契约
// （window.__ModuleLoader__.load({id, factory}) 惰性 CJS 工厂，react 与
// @deepseek-ai/* 全部外部化走平台模块表）。
// 构建（在 server/plugins/ui/ 下；suyou 仓库无 npm 依赖，tsdown 从外部供给）：
//   npx -y tsdown@0.22.2 -c tsdown.config.ts
// 或本机存在 dsh 源码工作区时：
//   /tmp/dsh-probe/node_modules/.bin/tsdown -c tsdown.config.ts
// 产物 lib/client.js 已随仓库提交；只有改了 src/client/ 才需要重建。

// closure-factory 外衣——与 dsh 共享 clientBundle 预设的产物形态一致。
const CLOSURE_PRELUDE = 'window.__ModuleLoader__.load({ id: "sandbar-admin-ui", factory: (require) => {'
const CLOSURE_POSTLUDE = 'return module.exports; } });'

export default {
  name: 'sandbar-admin-ui/client',
  entry: { client: 'src/client/index.tsx' },
  outDir: 'lib',
  format: 'cjs',
  platform: 'browser',
  entryFileNames: 'client.cjs',
  onSuccess: async () => {
    const { copyFileSync } = await import('node:fs')
    copyFileSync('lib/client.cjs', 'lib/client.js')
  },
  clean: false,
  dts: false,
  banner: { js: CLOSURE_PRELUDE + ' var module = { exports: {} }; var exports = module.exports;' },
  footer: { js: CLOSURE_POSTLUDE },
  // react 与 @deepseek-ai/* 走 dsh 浏览器模块表（平台种子字），不打进包里。
  external: [/^@deepseek-ai\//, /^react(\/|$)/],
}
