// t260902-12 集成测试 A：roles/integration.yml spec 落地契约检测。
// 断言只认公开契约（cordis patch 可加载 + persona 条款内容），不锚定排版：
// 断言前把双方空白全部剥掉，任何折行/缩进变化都不影响判定（灰盒：绑定浅）。
// 运行：node integration/t260902-12/test_yml_spec_landed.mjs（cwd=仓库根亦可，路径按脚本定位）。
// 失败 => 非零退出。
import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..', '..');

// 零依赖化（宿主令 t260902）：断言全是剥空白后的 persona 文本比对，
// 只需从 roles/integration.yml 提取 persona 块缩进文本——不引 js-yaml（仓库内无此依赖）。
function extractPersona(text) {
  const lines = text.split('\n');
  const i = lines.findIndex((l) => /^\s*persona:\s*(\||>)[-+]?\s*$/.test(l));
  if (i === -1) return null;
  const baseIndent = lines[i].match(/^\s*/)[0].length;
  const block = [];
  for (let j = i + 1; j < lines.length; j++) {
    const ln = lines[j];
    if (!ln.trim()) { block.push(''); continue; }
    const ind = ln.match(/^\s*/)[0].length;
    if (ind <= baseIndent) break;
    block.push(ln.slice(baseIndent + 1));
  }
  return block.join('\n');
}

const strip = (s) => String(s).replace(/[\s*]+/g, '');
const failures = [];
const check = (name, ok) => {
  console.log(`[t260902-12][yml] CHECK ${name}: ${ok ? 'PASS' : 'FAIL'}`);
  if (!ok) failures.push(name);
};

let personaRaw;
try {
  personaRaw = extractPersona(readFileSync(resolve(root, 'server/dsh/roles/integration.yml'), 'utf8'));
} catch (e) {
  console.log('[t260902-12][yml] SETUP FAIL: roles yml 读取异常：', e.message);
  process.exit(1);
}
check('persona 块可提取（cordis patch 结构在位）', typeof personaRaw === 'string' && personaRaw.trim().length > 0);
const persona = strip(personaRaw ?? '');
check('persona 非空（>500 字）', persona.length > 500);

// 修订一：三层归属（含「可白盒」的许可语气字样）+ intent/步骤 结构
check('A1 三层归属（含「可白盒随实现」）', persona.includes('测试按三层口径归属：L1单元层由developer随本票改动交付（可白盒随实现'));
check('A1 L2/L3 一律灰盒', persona.includes('一律灰盒'));
check('A1 intent 级重复与步骤级共享', persona.includes('避免的是intent级重复') && persona.includes('步骤级重复不视为重复用例设计'));
check('A1 intent+high-level steps 用例结构', persona.includes('intent（验证什么）与high-levelsteps（如何到达并断言）'));

// 修订一后半：灰盒与对抗纪律
check('A2 灰盒与对抗纪律小节', persona.includes('灰盒与对抗纪律（L2/L3铁律）'));
check('A2 理解要深/绑定要浅/对抗面', persona.includes('理解要深') && persona.includes('绑定要浅') && persona.includes('的对抗面而非复核面'));
check('A2 绑定浅铁律句', persona.includes('契约不变的实现重构不得打破集成测试，打破了即测试写错'));

// 修订二：用例设计依据（现行术语=用例设计/已知问题清单（KI）/三依据）
check('A3 用例设计依据小节', persona.includes('###用例设计依据（用例设计依据纪律，按序穷尽）'));
check('A3 三依据齐全（KI+对外契约）', persona.includes('②项目声明的已知问题清单（KI）（未闭合条目）') && persona.includes('③组件的对外契约与行为规格'));
check('A3 实现细节不作依据+锚定承诺', persona.includes('实现细节不作用例设计依据') && persona.includes('锚定承诺而非实现'));
check('A3 设计用例前必读 KI 与风险登记', persona.includes('设计用例前必读已知问题清单（KI）与风险登记'));

// 修订三：全局测试资产（顶层 ## 小节）+ 事故回归纪律
check('A4 全局测试资产（## 顶层小节）', persona.includes('##全局测试资产（本角色跨工单的持久产物，实际路径由项目声明给出）'));
check('A4 事故回归纪律', persona.includes('事故回归纪律') && persona.includes('无回归用例的修复不予放过'));
check('A4 场景资产', persona.includes('场景资产：系统场景与错误注入用例包'));

// 红线原样保留
check('红线：不代写代码/测试', persona.includes('不能帮developer实现具体的代码或测试'));
check('红线：不跳人审', persona.includes('不能跳过人类审查环节'));

// 旧口径残留（草案被修订前的术语）不得出现
check('无旧术语「出题」残留', !persona.includes('出题'));
check('无旧术语「故障账」残留', !persona.includes('故障账'));
check('无旧术语「题源纪律/三源」残留', !persona.includes('题源纪律') && !persona.includes('三源'));
check('无「黑盒」残留', !persona.includes('黑盒'));

console.log(`[t260902-12][yml] RESULT: ${failures.length === 0 ? 'PASS' : 'FAIL'}（失败 ${failures.length} 项）`);
process.exit(failures.length === 0 ? 0 : 1);
