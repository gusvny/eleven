// t260926-05 巡检落账报告只读端点宿主半 UT（src/host/inspection-report.ts）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
// 覆盖故障清单（票方案 rev2）：happy path / 缺 path / 非法扩展名 / 相对+绝对路径 /
// 仓库根外拒绝 / 符号链接逃逸拒绝 / 文件不存在 / 超限不 parse（摘录回执）/
// 坏字节拒解析 / JSON 解析失败带原文 / digest 内容正确。tmp fixture，零真仓依赖。
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { readInspectionReportFile, INSPECTION_REPORT_MAX_BYTES } from '../src/host/inspection-report.ts'

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

const repoRoot = mkdtempSync(join(tmpdir(), 't26092605-rep-'))
const outDir = join(repoRoot, 'out', 'inspection')
mkdirSync(outDir, { recursive: true })
const face = {
  kind: 'inspection', instance_id: 'ki', period: '260926', red_line: 'RL',
  findings: [{ severity: 'high', subject: 'S', evidence: [{ path: 'a.ts', line: 3, quote: 'q' }] }],
  suite: { ok: true, ran: 2, passed: 2, failed: 0, env_fail: 0 },
}
const reportRel = join('out', 'inspection', 'inspection-ki-260926.json')
const reportAbs = join(outDir, 'inspection-ki-260926.json')
writeFileSync(reportAbs, JSON.stringify(face, null, 2))
const outside = mkdtempSync(join(tmpdir(), 't26092605-out-'))
writeFileSync(join(outside, 'evil.json'), '{"steal":1}')

try {
  // ---- happy path：相对路径（仓内语义） ----
  const r1 = await readInspectionReportFile(repoRoot, reportRel)
  ok(r1.ok === true && Array.isArray(r1.digest) && r1.digest.length > 3, 'happy path 摘要在')
  ok(r1.digest.some(l => l.text === 'kind: inspection'), 'digest 平铺键值')
  ok(r1.digest.some(l => l.text === 'severity: high'), 'digest 嵌套发现项')
  // ---- happy path：绝对路径在仓内（引擎 report_path=绝对串常态） ----
  const r2 = await readInspectionReportFile(repoRoot, reportAbs)
  ok(r2.ok === true, '仓内绝对路径可读')
  // ---- path 缺失 / 空串 / 非字符串 ----
  const r3 = await readInspectionReportFile(repoRoot, '')
  ok(r3.ok === false && typeof r3.reason === 'string' && r3.reason.length > 0, '空 path 人话拒绝')
  const r3b = await readInspectionReportFile(repoRoot, undefined)
  ok(r3b.ok === false && r3b.reason, '缺 path 人话拒绝')
  // ---- 扩展名白名单 ----
  const r4 = await readInspectionReportFile(repoRoot, 'out/inspection/x.txt')
  ok(r4.ok === false && r4.reason.includes('.json'), '非 .json 拒绝')
  // ---- 仓库根外拒绝（绝对路径越界） ----
  const r5 = await readInspectionReportFile(repoRoot, join(outside, 'evil.json'))
  ok(r5.ok === false && r5.reason.includes('仓库根'), '仓库根外绝对路径拒绝')
  // ---- 遍历形态（../ 逃逸） ----
  const r6 = await readInspectionReportFile(repoRoot, join('out', '..', '..', join(tmpdir(), 'x.json')))
  ok(r6.ok === false, '相对遍历形态拒绝')
  // ---- 文件不存在 ----
  const r7 = await readInspectionReportFile(repoRoot, 'out/inspection/none.json')
  ok(r7.ok === false && r7.reason.includes('不存在'), '缺文件人话')
  // ---- 超限：不 parse，带摘录 ----
  const big = { big: 'x'.repeat(INSPECTION_REPORT_MAX_BYTES + 10) }
  const bigPath = join(outDir, 'big.json')
  writeFileSync(bigPath, JSON.stringify(big))
  const r8 = await readInspectionReportFile(repoRoot, 'out/inspection/big.json')
  ok(r8.ok === false && r8.reason.includes('上限'), '超限人话拒绝')
  ok(typeof r8.raw === 'string' && r8.raw.length <= 8 * 1024 && r8.raw.startsWith('{"big"'), '超限带 8KB 摘录且未解析')
  ok(r8.digest === undefined, '超限绝不出 digest（截断文本不当报告）')
  // ---- JSON 解析失败：人话 + 原文 ----
  writeFileSync(join(outDir, 'broken.json'), '{"cut": tru')
  const r9 = await readInspectionReportFile(repoRoot, 'out/inspection/broken.json')
  ok(r9.ok === false && r9.reason.includes('解析失败'), '坏 JSON 人话')
  ok(r9.raw === '{"cut": tru', '坏 JSON 带原文')
  // ---- 坏字节 ----
  writeFileSync(join(outDir, 'bad.bin.json'), Buffer.from([0x7b, 0x00, 0x7d]))
  const r10 = await readInspectionReportFile(repoRoot, 'out/inspection/bad.bin.json')
  ok(r10.ok === false && r10.reason.includes('UTF-8'), 'NUL 坏字节拒绝')
  // ---- 符号链接逃逸（平台支持 symlink 才跑；Windows 无特权场景可能失败） ----
  try {
    const linkPath = join(outDir, 'escape.json')
    symlinkSync(join(outside, 'evil.json'), linkPath)
    if (existsSync(linkPath)) {
      const r11 = await readInspectionReportFile(repoRoot, 'out/inspection/escape.json')
      ok(r11.ok === false && r11.reason.includes('仓库根'), '符号链接逃逸拒绝（realpath 真身比对）')
    }
  } catch (e) {
    console.log('SKIP symlink-escape（平台不支持 symlink，非产品故障）:', String(e.message).slice(0, 80))
  }
} finally {
  rmSync(repoRoot, { recursive: true, force: true })
  rmSync(outside, { recursive: true, force: true })
}

console.log(`t260926-05-inspection-report-file: ${n} checks pass`)
