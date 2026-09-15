// t260915-10 「文档」视图壳层跟随纯函数 UT（followProjectKey / emptyGuidance 真值表 + 畸形输入矩阵）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过；被 run_tests.mjs 自动收编）。
// 被测=DocsSection 接壳层 projectKey（t260915-10）拆出的可判定逻辑，组件侧只做装配：
//   followProjectKey —— 初值/跟随单源判定：用户没动过选择器（touched=false）→ 跟随壳层
//     当前项目（非字符串/缺省 → ''=缺省引擎仓回落，既有语义不删）；用户手动动过
//     （touched=true）→ 保持现值不被壳层冲掉（spec 验收②手动优先）。
//   emptyGuidance —— 项目语境空目录指引（spec ③）：选择态≠'' 且 scope 目录空诚实降级时
//     给指引文案（点名项目键、scope 目录、「不回落引擎仓」）；缺省语境/非空/畸形输入 →
//     定值 ''（维持既有文案面）。
import assert from 'node:assert/strict'
import { followProjectKey, emptyGuidance } from '../src/client/docs-view-model.ts'

let n = 0
function ok(name, fn) { fn(); n += 1; console.log(`  ok ${n} - ${name}`) }

/* ------------------------------------- followProjectKey：跟随面（touched=false） */

ok('跟随：正常 key 透传', () => {
  assert.equal(followProjectKey('fixa', '', false), 'fixa')
})
ok('跟随：壳层缺省（undefined）→ 缺省引擎仓回落', () => {
  assert.equal(followProjectKey(undefined, 'fixa', false), '')
})
ok('跟随：壳层空串（未选项目）→ 缺省引擎仓回落（既有语义不删）', () => {
  assert.equal(followProjectKey('', 'fixa', false), '')
})
ok('跟随：壳层同值 → 原样（幂等，不惊动 [scope,projectKey] fetch effect）', () => {
  assert.equal(followProjectKey('fixa', 'fixa', false), 'fixa')
})

/* --------------------------------- followProjectKey：手动优先面（touched=true） */

ok('手动优先：壳层变更不冲掉手动选择（spec ②主断言）', () => {
  assert.equal(followProjectKey('fixb', '', true), '')
})
ok('手动优先：壳层回落 undefined 也不冲掉', () => {
  assert.equal(followProjectKey(undefined, 'fixa', true), 'fixa')
})
ok('手动优先：壳层同值同样保持（用户动作后壳层无发言权）', () => {
  assert.equal(followProjectKey('fixa', 'sandbar', true), 'sandbar')
})

/* ------------------------------------- followProjectKey：畸形输入矩阵（定值分支） */

ok('畸形：壳层非字符串（number/null/object/布尔）→ 跟随面回落缺省、手动面保持现值', () => {
  assert.equal(followProjectKey(42, '', false), '')
  assert.equal(followProjectKey(null, '', false), '')
  assert.equal(followProjectKey({ key: 'x' }, '', false), '')
  assert.equal(followProjectKey(true, '', false), '')
  assert.equal(followProjectKey(42, 'fixa', true), 'fixa')
})

/* ------------------------------------------------ emptyGuidance 真值表 */

ok('指引：项目语境空目录 → 文案含项目键、scope 目录与「不回落」语义', () => {
  const g = emptyGuidance(true, 'fixa')
  assert.ok(g.includes('fixa'), `指引含项目键：${g}`)
  assert.ok(/docs\/|notes\//.test(g), `指引提及 scope 目录：${g}`)
  assert.ok(/回落/.test(g), `指引点名不回落：${g}`)
})
ok('缺省语境（projectKey=\'\'）空目录 → 无指引（维持既有文案面）', () => {
  assert.equal(emptyGuidance(true, ''), '')
})
ok('目录非空 → 无指引', () => {
  assert.equal(emptyGuidance(false, 'fixa'), '')
})
ok('畸形：treeEmpty 非严格 true / 项目键非串 → 定值 \'\'，不 throw', () => {
  assert.equal(emptyGuidance(undefined, 'fixa'), '')
  assert.equal(emptyGuidance('yes', 'fixa'), '')
  assert.equal(emptyGuidance(1, 'fixa'), '')
  assert.equal(emptyGuidance(null, 'fixa'), '')
  assert.equal(emptyGuidance(true, 42), '')
  assert.equal(emptyGuidance(true, undefined), '')
  assert.equal(emptyGuidance(undefined, undefined), '')
})

console.log(`\n全部通过：${n} 例`)
