/**
 * staleness.ts —— host 陈旧全局提醒 hook（t260902-03，一日三咬根治）。
 *
 * 运行时看守：30s 可见性门轮询 /suyou-workbench/api/build-info（页签不可见零请求，
 * 复用 startVisibleInterval），磁盘 host 半与 console 进程启动指纹不一致 → 全局
 * 横幅提示「重启 console 生效」。挂点单例在 sidebar 层（.wb-sb-right 共享容器），
 * 四视图排他渲染也不影响，横幅常驻。
 *
 * 回收纪律（终态全回收）：
 *   - useEffect cleanup 必调 startVisibleInterval 返回的停表函数（幂等）；
 *   - inflight fetch 在组件卸载后回包不得 setState——mounted 标志显式挡（React 18
 *     下无害，按纪律仍显式处理）。
 *
 * 异常取舍（R2 清单对 visibility-poll 模式 4 的声明偏离）：轮询 fn 内自吞
 * 网络/解析类运行错误（分类落 {stale:false}），不向上抛——看守自身不得成为新
 * 报错源；编程错（非 Error 对象等）不在自吞边界内。分类纯函数在 ./stale-check.ts。
 */

import { useEffect, useRef, useState } from 'react'
import { startVisibleInterval } from './visibility-poll.ts'
import { classifyBuildInfoResponse } from './stale-check.ts'

const BUILD_INFO_URL = '../suyou-workbench/api/build-info'
const POLL_MS = 30_000

export function useStaleHost(): boolean {
  const [stale, setStale] = useState(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    const check = async (): Promise<void> => {
      try {
        const res = await fetch(BUILD_INFO_URL, { cache: 'no-store' })
        const verdict = classifyBuildInfoResponse(res.status, await res.text())
        if (mountedRef.current) setStale(verdict.stale)
      } catch {
        // 网络/解析错自吞（有意降级：看守自身不得成为新报错源）。
        if (mountedRef.current) setStale(false)
      }
    }
    const stop = startVisibleInterval(() => { void check() }, POLL_MS)
    return () => {
      mountedRef.current = false
      stop()
    }
  }, [])

  return stale
}
