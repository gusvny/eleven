# t260904-07 会话开局注入失效定位报告（invalid payload for session prompt）

> 报障（宿主 260904 晚）：3099 新建会话即报错 `invalid payload for session prompt`，
> 07 票交付的「charter 为首条消息」完全未发生。本报告只定位不修复（integration 岗位纪律）。
> 结论三句话：**根因=客户端把裸字符串传给了要求分片数组的平台 prompt API；
> 为什么测试没发现=唯一能抓住它的注入旅程场景在合并闸里干净 SKIP（lane 无
> playwright-core、无 3199 隔离台），闸只看 exit 0 判过；放大器=平台 prompt
> 失败不抛错只回 RpcResult，票内「就地 catch 兜底」从未触发，错误经
> promptError toast 直达用户。**

## 1. 现场与复现链

- 生产台（3099，PID 16042）代码非陈旧：build-info `stale:false`（boot==disk 指纹），
  lib/client.js 17:22 随 d6c4554 重建；charter 端点 `GET ?project=sandbar` 200，
  渲染干净（1979 字符、零 `{{` 残留）——**服务端无恙**。
- 用户失败现场：`~/.dsh/sessions/--Users-xingu-Documents-sandbar--/session-c5ea997f-*`
  转录仅 4 行（session/preset/sandbox/approval），**零注入事件零 prompt 事件**：
  会话创建成功、注入调用在写下任何东西之前就被拒。
- 错误文案来源：dsh-client-ui-conversation `showToast(\`${error.message} (${error.code})\`)`
  → "invalid payload for session prompt (bad-request)"，新建即弹=注入发生在
  handleNew 尾段（注册账册之后），用户感知为「新建就报错」。

## 2. 根因（调用形状错误，非内容非法）

- 平台契约：`dsh-host-apiproxy` 的 `sessionPromptRequestSchema` 要求
  `content: z.array(promptContentPartSchema)`（`{type:'text',text}` 分片）+
  `mode: 'queue'|'steer'`；safeParse 失败 → `invalid payload for ${method}`。
- 客户端透传：`dsh-client-runtime` `Session.prompt(content, mode)` 把 content
  **原样**进 RPC，无 string→分片归一。
- 违规调用：`server/dsh/workbench/src/client/session-entry.tsx` L313
  `await session.prompt(charter, 'queue')` —— charter 是裸字符串。
  charter 文本本身合法（控制字符扫描零命中），非法的是**载荷类型**。
- 为何编译期没拦：`SessionsFace.sessionOf?(actx: any): any`（L155-164）——
  any 面抹掉了 tsc 对 prompt 签名的校验。
- 为何票内兜底没拦：方案 R3 假设 prompt 失败会 throw，实际
  `Session.prompt` 失败**返回** `{ok:false,error}` 并写入 snapshot.promptError
  （blank 位保持 true，会话可被下次 + 复用）——`injectSessionCharter` 的
  try/catch 永不触发，无 console.error、无 notify，错误只有 toast。

## 3. 为什么集成测试没发现（闸记录实证）

worker-t260904-07.log（t260904-07 票机械跑+合并复验，L54/L61/L85/L93-94）：

- `sc_session_charter_source_contract` → 真跑，pass=16（静态源契约，测不到调用形状）；
- `sc_session_charter_endpoint_live` → **[SKIP] 3199 不可达**（curl exit 7、无 docker、无 temporal CLI）；
- `sc_session_charter_injection_journey` → **[SKIP] playwright-core unavailable**——
  本票核心用户旅程，一条断言都没执行；
- 引擎闸：97 跑/97 过/0 败（exit 0 语义），arbitrate 注记
  「t260904-07-charter-injection-journey exit 0（干净 SKIP）」后放行收口。

反事实验证：journey 若真跑必红——T1 30s 等 charter 特征串不上屏、console 零错误
（失败不抛错）→ 不命中凭据噪音豁免 → FAIL exit 1。**该 bug 恰好落在唯一被
SKIP 的那条场景的断言面正中央。**

缺口三层：

1. **环境**：lane 内无 playwright-core（KI-036 族）、无 3199 隔离台——browser 池
   16+ 条场景在该环境全部退化为干净 SKIP，票面设计预先授权了这一退化
   （「缺环境干净 SKIP……依赖恢复自动生效」）。
2. **流程**：核心验收场景 SKIP 时无阻断门——设计承诺「有凭据环境人工复判」
   未留任何记录即收口；arbitrate 有注记无拦截。KI-044 已实证 UI 证据闸同类穿透。
3. **代码面**：any 类型面 + smoke 只测渲染纯函数与源锚，均覆盖不到调用形状。

## 4. 修复方向（开票，不代做）

- 调用改 `session.prompt([{ type: 'text', text: charter }], 'queue')`；
  并按「失败不抛错」语义检查返回值 `result.ok`，失败走 R3 的就地留痕+notify
  （修正 R3 注释的错误假设）；
- 顺带把 SessionsFace 的 any 面收窄到平台 PromptContentPart[]（防同族复发）；
- 修复票验收标准建议：隔离台+playwright 真跑 journey 三腿全 pass，并留
  charter-first-message.png（本机 .suyou/screenshots 至今无此图=历史零真跑）。

## 5. 测试侧改进（integration 自留，另行评审后落）

- journey 场景 T1 失败分支可加归因读数（读 session snapshot 的 promptError，
  把「invalid payload」类错误与凭据噪音区分开），但不得为过测试改断言强度；
- 闸流程：**票的核心旅程场景 SKIP 时要求显式人工复判记录**（或环境在位才许
  收口）——归引擎票，与 KI-036/KI-044 合并考虑。

## 证据锚

| 事实 | 位置 |
| --- | --- |
| 违规调用 | session-entry.tsx L313（L297-318 injectSessionCharter） |
| any 类型面 | session-entry.tsx L155-164 |
| zod 拒收+文案 | dsh-host-apiproxy lib/index.js L614-620 schema、L4824-4831 bad-request |
| 透传+不抛错 | dsh-client-runtime lib/client.js L7196-7240、session.d.ts L137 |
| toast 展示 | dsh-client-ui-conversation lib/client.js L3565/L3589-3590 |
| 闸 SKIP 实证 | server/dsh/temporal-poc/data/worker-t260904-07.log L54/L61/L85/L93-94 |
| 用户失败会话 | ~/.dsh/sessions/--Users-xingu-Documents-sandbar--/session-c5ea997f-*(4 行转录零注入) |
| 服务端健康 | 3099 build-info stale:false；charter 端点 200 零残渣（curl 实测） |
| 设计带病 | notes/discussions/260904-project-session-charter.md L46（`prompt(content,'queue')` 止步方法名未钉类型） |
| smoke 断言面 | server/dsh/workbench/smoke/session-charter.mjs 头注 A-D（D=源文本锚非调用形状） |

## 6. 为什么两个 role 一个小时都没发现（流程归因）

「第三方调用必须有测试覆盖」这条要求**从来没有落成可执行的闸**——它存在于
期望里，不存在于任何机械检查里。逐环拆：

1. **设计/实查环节**（两 role 共享的输入）：讨论档实查记录了正确的方法链
   `scope→sessionOf→prompt(content,'queue')`，但**止步于方法名，没钉参数类型**
   （`PromptContentPart[]`）。`content` 被自然读成「文本内容」——错误形状从
   设计就带进来了，developer 是照设计忠实实现的。
2. **developer（implement）**：随票 smoke A-D 全绿——但 A-C 测渲染纯函数，
   D 测**源文本锚**（「恰一次 prompt 调用点」是 grep 源码不是验调用形状），
   错误参数形状下 D 照样过。any 类型面让 tsc 无从校验。lane 里无浏览器无
   隔离台，手工验证也无从做。单测绿=开发者合理认为完成。
3. **integration（design_integration_tests）**：场景设计本身是对的（journey
   真跑必红）——但**测试金字塔有个洞**：从「渲染纯函数单测」直接跳到「真
   浏览器旅程」，中间缺一层**零环境依赖的调用形状测试**（stub sessions face
   捕获 prompt 实参、断言分片数组——不需要浏览器/隔离台/凭据，毫秒级，任何
   lane 都能跑）。这层缺失是场景设计（integration 自己）的缺口。
4. **integration（arbitrate）**：journey 干净 SKIP 被注记后放行。场景头部
   预先写明了「缺环境干净 SKIP……有凭据环境人工复判」——**承诺的复判没有
   任何机制强制在合并前发生**，注释里的承诺不是闸。这是把门人的直接失误。
5. **闸语义**：引擎只消费 exit code，SKIP≡PASS。核心旅程场景的 SKIP 与
   无关紧要场景的 SKIP 在闸眼里无差别。「覆盖」名存（场景在册）实亡（零执行），
   而没有任何检查区分这两者。
6. **环境（系统性）**：browser 池 16+ 条场景在 lane 全部退化为干净 SKIP
   （worktree 无 node_modules、run_integration_tests 不 boot 隔离台）——
   KI-036 已登记、被预先授权容忍。一小时的开发全程发生在这种环境里，两个
   role 的动态验证都退化成了静态检查。

一句话：**两个 role 不是没设计覆盖，是覆盖被环境静默缴械、而闸不区分
「有覆盖」和「覆盖执行了」；同时最便宜的那层防线（类型面+调用形状测试）
两边都没建。**

## 7. 把规则变成机械（提案，宿主质询后修订版）

1. **修复票**（第 4 节）：分片数组+result.ok+any 面收窄——tsc 从此就是
   平台边界的契约测试。
2. **外部调用形状单测规范**（宿主质询修正：形状断言=mock，归 UT 不归集成）：
   规范条款=凡新增**不由本项目控制的进程外接口**调用点（HTTP API / CLI
   子进程 / 平台 SDK……dsh 与 Temporal 只是本仓实例），该调用必须在
   developer 单测里带 mock 形状断言（捕获实参、对照对端契约校验——真
   schema/d.ts 可导入则 import，否则仓内冻结镜像+声明同步责任）。没有这类
   调用点的项目条款空转。集成侧不写 mock，只在仲裁加固定问句：「本票新增
   外部调用吗？形状单测在哪？」——把关不代做。本票若有这层，实现段当场红。
3. **闸语义票**（引擎；宿主质询定稿：**闸内无 SKIP，改 ENV_FAIL**）：病根=
   执行契约让场景在环境缺失时主动 `exit 0`，闸只读退出码，「放弃」与
   「通过」同数；且「SKIP」字面撒谎（跳过=没事），实际是「没验成，原因
   环境」。定稿状态模型：场景级只有 PASS / FAIL / ENV_FAIL——ENV_FAIL
   也是红，病因归环境（修=按 4 的声明补装备），不归票的代码；场景内部
   以**系统状态**为条件的腿可声明 N/A（不以测试环境为条件），全腿 N/A
   的场景=红。退出码分家（沿屋风：cache_probe/capture-lane 已用 exit 2=
   环境面失败）：0=全过，1=有 FAIL（产品），2=有 ENV_FAIL（环境，
   SUMMARY 写明缺什么）——引擎不解析文本即可分流：1 走打回、2 走供给
   修复、0 才放行。真跑不进闸的（真模型花费/红线禁区/破坏性）不进闸
   清单，归验收段人工清单+签字；急事带红过闸=人显式签字留痕
   （break-glass），不是测试语义。实现=引擎消费场景末行
   `SUMMARY pass/fail/env_fail` 而非只看退出码。早先「core 旗+豁免」
   方案作废——给不该存在的语义打补丁。4 是 3 的前提（先修供给再收紧，
   闸才不会天天拦人）。
4. **测试环境供给声明制**（引擎+接入契约）：不枚举工具——项目在接入声明
   里自报「集成测试需要什么环境+一条幂等装配命令」，引擎开泳道/跑集成段
   时照声明执行，装配失败=显式红不静默；无需求项目零声明。本仓实例=
   软链主树 playwright + browser 池 bench 供给（与 3 互为前提：只立规矩
   不给供给会拦死所有 UI 票，只给供给不立规矩环境坏了仍静默漏过）。
