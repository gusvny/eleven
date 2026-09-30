/**
 * project-key.ts —— project key 白名单与「点名判据」的畸形报错（t260929-22 GAP C）。
 *
 * 单源纪律：api.ts / requests.ts / settings.ts 三处同用同一正则与同一文案——
 * 报错必须**点名失败的判据**（正则）、**收到什么**（空参显式 <空>，不裸冒号收尾）、
 * **要什么**（?project=<project-key>）。措辞族照 workbench/src/host/epics.ts 先例。
 */

/** project key 白名单：小写字母/数字开头，可含连字符，1–41 字符。 */
export const PROJECT_KEY_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

/** 「project 形状不合法」点名判据版文案（单源；三处消费方共用）。 */
export function malformedProjectMessage(key: unknown): string {
  const shown = typeof key === 'string' ? key : String(key)
  const got = shown === ''
    ? '<空>——project 参数缺席'
    : `'${shown}'`
  return `project 形状不合法：${got}（要求 ^[a-z0-9][a-z0-9-]{0,40}$，小写字母/数字/连字符，1–41 字符；请传 ?project=<project-key>）`
}
