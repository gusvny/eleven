#!/usr/bin/env node
/**
 * metrics-cli.mjs —— metrics 的 node CLI 前门（t260901-20，工具桥契约⑤消费者）。
 *
 * 单实现双前门（契约块 2 L158「同实现同缓存」）：本文件只做 argv 收口 + 直调
 * src/host/metrics.ts 的 buildMetricsResponse + stdout 序列化，聚合/缓存/降级
 * 逻辑零自有——与 HTTP 前门同一函数、同一缓存目录，字节级一致由
 * integration/t260901-20/t05 双前门基线锁（剔除 generated_at/cache.computed_at
 * 后全量比对）。
 *
 * 用法：node metrics-cli.mjs '<json 参数>'
 *   参数 JSON：{"view":"time","window":"7d","epic":"all","project":"<key>","template":"dev-lane"}
 *   成功：stdout = 与 HTTP 前门同构的响应 JSON，exit 0
 *   失败：stderr = {error} 人话，exit 2
 *
 * 运行环境：Node >= 22.18（type-stripping 直跑 TS import，同 integration 执行
 * 契约）；直连三真源（admin.py spawn / git / ~/.dsh 会话文件），不依赖 console
 * 或 3099 在线，泳道/Docker 隔离环境可独立出数。测试缝 SANDBAR_METRICS_STUB
 * 见 metrics.ts 文件头。
 */

import { buildMetricsResponse, defaultDeps } from './src/host/metrics.ts'

const arg = process.argv[2]
if (arg === undefined || arg === '-h' || arg === '--help') {
  process.stderr.write('用法：node metrics-cli.mjs \'<json 参数>\'，例：\'{"view":"time","window":"7d"}\'\n')
  process.exit(arg === undefined ? 2 : 0)
}
let params
try {
  params = JSON.parse(arg)
} catch (err) {
  process.stderr.write(JSON.stringify({ error: `参数不是合法 JSON：${String(err instanceof Error ? err.message : err)}` }) + '\n')
  process.exit(2)
}
if (params === null || typeof params !== 'object' || Array.isArray(params)) {
  process.stderr.write(JSON.stringify({ error: '参数必须是 JSON 对象（键：view/window/epic/project/template）' }) + '\n')
  process.exit(2)
}

// 本文件固定落在 <repo>/server/plugins/workbench/ 下，上三级即仓库根（无机器绝对路径写死）
const repo = process.env.SANDBAR_REPO ?? new URL('../../..', import.meta.url).pathname.replace(/\/+$/, '')
const deps = defaultDeps(repo)

try {
  const r = await buildMetricsResponse(params, deps)
  if (r.status !== 200) {
    // 4xx 防穿：错误只走 stderr（stdout 成功时才是契约 JSON，供管道消费方安全解析）
    process.stderr.write(JSON.stringify(r.body) + '\n')
    process.exit(2)
  }
  process.stdout.write(JSON.stringify(r.body) + '\n')
  process.exit(0)
} catch (err) {
  // 兜底终态：聚合抛错（正常/报错/超时三路里未经软降级收口的意外）不裸栈
  process.stderr.write(JSON.stringify({ error: `metrics 聚合失败：${String(err instanceof Error ? err.message : err)}` }) + '\n')
  process.exit(2)
}
