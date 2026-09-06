/**
 * staleness.ts —— 插件陈旧全局提醒 hook（t260902-03 立；t260905-07 KI-052 握手矩阵接线）。
 *
 * 运行时看守：30s 可见性门轮询 /suyou-workbench/api/build-info（页签不可见零请求，
 * 复用 startVisibleInterval），判定走 classifyHandshake 三元组矩阵（boot/disk/injected，
 * 见 ./stale-check.ts）：
 *   - restart 支：服务端旧（boot≠disk / build-info 端点 405/404 内存无 / 缺 boot 指纹）
 *     → 「有更新，重启控制台生效」；
 *   - reload 支：服务端一致但浏览器旧（injected≠disk，跨重启存活页面）→
 *     「有更新，刷新页面生效」——重启对此支无效，文案与消除动作一一对应。
 *
 * injected 的取得（L1 机制，写集内实现）：dsh 核心供给链在写集外、无法在 bundle
 * 响应里注入指纹，改用 **sessionStorage 注入代理**——本模块首次加载（=bundle
 * 下载完成时刻）即拉一次 build-info，把当下 disk 指纹写进 sessionStorage（页面
 * 维度，跨刷新存活）；轮询时读它当 injected。语义核对：
 *   - 新开页/刷新后：init 覆写 injected=当下 disk → 恒 M5（消除动作「刷新」可达，
 *     不会刷新后横幅不消）；
 *   - 页面存活跨合并/跨重启（不刷新）：sessionStorage 保留旧盘态 → injected≠disk
 *     → M4 reload（正是 gen1 打回①点名的序列）。
 * 异常（隐私模式禁用 sessionStorage 等）→ injected 恒 null，M4 自动失效退回 L2
 * 行为（仅服务端判定），不误报。
 *
 * 挂点单例在 sidebar 层（.wb-sb-right 共享容器），四视图排他渲染也不影响，横幅常驻。
 *
 * 回收纪律（终态全回收，gen1 打回②c 全带）：
 *   - useEffect cleanup 必调 startVisibleInterval 返回的停表函数（幂等）；
 *   - inflight fetch 在组件卸载后回包不得 setState——mounted 标志显式挡（React 18
 *     下无害，按纪律仍显式处理）。
 *
 * 异常取舍（沿 t260902-03 口径）：轮询 fn 内自吞网络/解析类运行错误（矩阵落
 * 不显），不向上抛——看守自身不得成为新报错源；编程错（非 Error 对象等）不在
 * 自吞边界内。分类纯函数在 ./stale-check.ts，文案常量在 ./banner-text.ts（场景
 * 断言锚同源，KI-051 纪律）。
 */

import { useEffect, useRef, useState } from 'react'
import { startVisibleInterval } from './visibility-poll.ts'
import { classifyHandshake } from './stale-check.ts'

const BUILD_INFO_URL = '../suyou-workbench/api/build-info'
const POLL_MS = 30_000
/** sessionStorage 键（注入代理；页面维度，跨刷新存活、关页即清）。 */
const INJECTED_KEY = 'wb.build.fingerprint.atload'

/** 读注入代理（异常→null：隐私模式等降级为 L2，不误报）。 */
function readInjected(): string | null {
  try {
    return window.sessionStorage.getItem(INJECTED_KEY)
  } catch {
    return null
  }
}

/** 写注入代理（bundle 下载时刻的盘态快照）。 */
function writeInjected(fp: string): void {
  try {
    window.sessionStorage.setItem(INJECTED_KEY, fp)
  } catch { /* 降级 L2，不误报 */ }
}

/** 拉一次 build-info 并取 disk 指纹（init 用；网络/解析错自吞返 null）。 */
async function fetchDiskFingerprint(): Promise<string | null> {
  try {
    const res = await fetch(BUILD_INFO_URL, { cache: 'no-store' })
    if (res.status < 200 || res.status >= 300) return null
    const parsed = await res.json().catch(() => null)
    const fp = parsed?.result?.diskFingerprint
    return typeof fp === 'string' && fp !== '' ? fp : null
  } catch {
    return null
  }
}

/** 横幅文案键：null=不显；'restart'/'reload' 对应 banner-text.ts 两支常量。 */
export type StaleBannerKind = 'restart' | 'reload' | null

export function useStaleBanner(): StaleBannerKind {
  const [banner, setBanner] = useState<StaleBannerKind>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    // init：bundle 下载时刻把当下盘态写入注入代理（页加载即写，先于首个轮询窗）。
    void fetchDiskFingerprint().then((fp) => { if (fp !== null) writeInjected(fp) })
    const check = async (): Promise<void> => {
      try {
        const res = await fetch(BUILD_INFO_URL, { cache: 'no-store' })
        const verdict = classifyHandshake(readInjected(), res.status, await res.text())
        if (mountedRef.current) setBanner(verdict.banner)
      } catch {
        // 网络/解析错自吞（有意降级：看守自身不得成为新报错源；M7 不显）。
        if (mountedRef.current) setBanner(null)
      }
    }
    const stop = startVisibleInterval(() => { void check() }, POLL_MS)
    return () => {
      mountedRef.current = false
      stop()
    }
  }, [])

  return banner
}
