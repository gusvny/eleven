/**
 * echarts.esm.min.d.ts —— 让 tsc 把 `./echarts.esm.min.js` 的相对 import 解析到
 * 同目录 echarts.d.ts 的最小声明（构建器打包走 .js 本体，本文件不进 bundle）。
 */
export * from './echarts'
