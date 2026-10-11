# 场景退役留痕（tombstone 记录）

本文件是场景退役的留痕面（登记权=integration 岗位）。格式照 lane-parallel-dom
先例（261001 宿主令）：每条答四问——**守什么／为什么退／回归责任移交到哪／
认赔什么**。退役后场景文件从仓里删除（历史在 git 可取），注册表条目撤下并在
原位留一行指针注释；known-red 基线同步删行并下调 max_entries（棘轮只缩不增）。

---

## 261002 退役批（宿主令 261002：批 1 共享台僵尸 9 条 + 批 3 低价值 2 条）

批 1 九条共同背景：全部是共享台 staging 面的浏览器/注入实验场景，史册 verdict
清一色 **env_fail**（环境红，不是产品红），近 50 跑 50/50 红；261001 挂入
known-red 基线后每轮 `known_red_skipped` 跳过、零新台账行（最后一条台账停在
260930 08:24）——**它们已经不提供任何保护，退役是把既成事实落账**。

### t260903-07-chat-project-tag
- 守什么：全局 chat 用户消息项目 tag 契约——引用真实工单 id 的消息行渲染项目
  chip（同项目恒同色、不同项目不同色、页面重载后同色；chip 文本 ∈ 注册项目键，
  不造假 key）。
- 为什么退：共享台环境红 214/234，挂账起每轮 skip。
- 移交：chip 映射的 L1 DOM 桩仍在（注册意图原注「L1 DOM 桩已锁」）。
- 认赔：真浏览器下 chip 渲染与重载同色无人守；共享台稳定后可按本留痕复活。

### t260904-05-chat-band-affiliation
- 守什么：右栏 chat 项目色带归属通道（fresh 空账册不渲染色带；项目行 + 新建后
  会话滚动体带 `data-wb-chat-projband=<项目 key>`；色带色与左栏同源；点工单行
  归属不动；刷新后归属恢复）。
- 为什么退：共享台环境红 215/234，挂账起每轮 skip。
- 移交：无（归属通道的模型层无独立 L1）。
- 认赔：chat 色带归属通道回归裸奔。

### t260904-05-session-lifecycle-ui
- 守什么：项目行会话生命周期 UI 全链（+ 新建续号且 active 恰一；关闭确认取消
  不动/确认才关；序号不回收；刷新后整组 tab 持久；关完全部再新建仍续大号）。
- 为什么退：共享台环境红 216/234，挂账起每轮 skip。
- 移交：账册状态机 t260904-01 journey（纯函数）仍在（原注册意图声明两层不同层）。
- 认赔：真实 UI 呈现面（tab 组、续号、持久）回归裸奔。

### t260904-05-top-entry-retired-form
- 守什么：顶部行退役后的入口形态（lib 产物零退役符号且含新锚；DOM 中退役锚
  全不在场；出厂全局新建钮继续被压制；项目色三处同源）。
- 为什么退：共享台环境红 216/234，挂账起每轮 skip。
- 移交：无（产物符号锚可后移 S0 build-contract，未移）。
- 认赔：入口形态浏览器面回归裸奔。

### t260904-07-charter-injection-journey
- 守什么：charter 注入用户旅程（新建会话不输入内容即见 charter 为首条消息、
  无 `{{` 残留；切换/重载不重复注入；截图证据落盘）。
- 为什么退：共享台环境红 215/234，挂账起每轮 skip。
- 移交：「恢复/切换路径绝不注入」的守卫口径在 L1 面（t260831-08⑥ 族）待核。
- 认赔：注入旅程的浏览器面回归裸奔（含占位符实值化）。

### t260904-11-charter-prompt-wire-contract
- 守什么：charter prompt wire 契约冻结（KI-046 回归网）——客户端发包形状 ×
  平台 zod 门收包形状的接缝两端同场验证，平台供给 bundle 的请求门真源锚。
- 为什么退：共享台供给只读面环境红 217/234，挂账起每轮 skip。
- 移交：ki046 UT（workbench/tests）锚接缝客户端一端仍在（原注册意图注明）。
- 认赔：平台一端与镜像同步责任无人守（07 票事故的回归网缺半边）。

### t260905-07-stale-handshake-banner
- 守什么：插件 staleness 握手横幅注入实验（五分支双向断言：新鲜态无横幅／盘新
  内存旧横幅在场且文案绑定消除动作／看守自身内存旧 405 立案现场等）。
- 为什么退：fixture 真拷贝隔离台=共享台面，环境红 217/234，挂账起每轮 skip。
- 移交：无。
- 认赔：横幅五分支回归裸奔（KI-052 根治面的行为验证缺位）。

### t260905-09-platform-context-fold-stacked
- 守什么：平台上下文叠台折叠用户旅程（恰一个小条、全部候选正文收折、点小条整组
  开/收、中段普通消息全程可见零误折）——宿主实报「还是显示了一堆，只折叠了
  开头一小部分」的验收面。
- 为什么退：共享台环境红 212/234，挂账起每轮 skip。
- 移交：无。
- 认赔：折叠件回归裸奔（**本批最可惜的一条**，宿主实报过的界面；共享台一稳定
  优先复活它）。

### t260916-26-stage-plugins-selfcheck
- 守什么：stage 启停「全插件激活」自检断言面（假 console 按宿主 typert 线型回
  信封的机器契约 + L3 真台面）。
- 为什么退：共享台面环境红 224/234，挂账起每轮 skip。
- 移交：无（假 console 机器契约半边可拆 L1，未拆）。
- 认赔：stage 启停自检回归裸奔。

### multi-tab-coexistence（t260901-15）
- 守什么：工单台多页签共存黑盒基线（管理台常开多页签的用户场景驱动）。
- 为什么退（批 3）：近 50 跑 14 红；翻转源是共享服务端状态的时序争用（环境耦合），
  非契约缺陷——多标签场景在单机宽面下结构性抖；核心状态机在账册模型层另有锚。
- 移交：无。
- 认赔：跨标签一致性（同账册多视图互见/不互踩）回归裸奔。

### t260913-03-executor-pool-exclude-l1
- 守什么：执行器池排除旋钮机械行为自证（被排除池不计 ran/expected、点名行原文、
  INTEG_SUMMARY 条件键、非法 token 剥离+响亮 WARN、缺省路径与改前执行器逐字节
  一致）。执行体=旧 `integration/tests/test_pool_exclude_executor.py`（零 test_
  函数，pytest 不收集，唯一跑者就是本场景条目）。
- 为什么退（批 3）：近 50 跑 14 红；低频运维旋钮的自检面，夹具重、翻转污染高，
  非用户面。
- 移交：执行器三态出口/条目完整性两条既有电池仍在。
- 认赔：池排除旋钮的机械行为自 261002 起无人守（旋钮若再被人改动，无回归网）。

---

## 批 2 明确不退（留观察位，retire_when 未到期）

- `t260910-09-ms-decl-gate`（近 50 跑 8 红，双向抖动面）：撤账条款要求「隔离/负载
  面稳定后连续 3 轮泳道内 PASS」——未到期，留基线观察位。
- `t260913-02-schedule-daily-deadman`（近 50 跑 1 红）：几乎痊愈；按条款观察
  3 轮绿后走基线纪律删行，不进退役批。

## 批 4 明确不退（判法修复排队，守的界面都在）

泳道图三条（t260915-05-detail-lane-map-dom / t260916-04-lane-map-everblocked-dom /
t260916-05-inspection-detail-lane-map-dom）、t260915-08-board-ui、
t260904-06-spec-card-dom（含 XSS 保真）、t260926-05-inspection-report-ui-dom、
t260905-05-modal-dialog-semantics、t260913-02-integ-run-singleflight（与
t261002-03 并发标定合并处置）——按 261002 直修批同款「终态/结构锚＋两级点击」
修判法；修后仍 >20% 红再议退。


## 261005 退役批（t261005-10 UI-2 中栏 tab 归并的产品性退役；登记=integration 岗位复核项）

产品事实：宿主拍板（epic console-ui item UI-2，mock 261004-concurrency-limit-mock v11）把中栏 tab 归并为
面板内九页签（Overview / Epics / Ledger / Alerts / Inspection / Metrics / Docs / Grants / Settings），
**状态看板删除**、Epics/Docs 迁入 tab、Metrics 自侧栏迁入、旧 Metrics 入口三连同退。下列场景的被测主体
随该产品决定整体消失，退役=把产品决定落账（非红账处理）。回归责任移交：面板 tab 的新在场/降级契约由
本票新场景 t261005-10-ui2-panel-tab-order-contract / -board-metrics-entrance-retired / -epics-docs-metrics-tabs-journey 承接。

### metrics-donut-dom
- 守什么：宿主 echarts 度量面板三 donut 真渲染 + cache-first 角标（黑盒 DOM 基线）。
- 为什么退：宿主度量面板（metrics.tsx 三级入口 + echarts 渲染层）随「Metrics 迁入面板 tab」整体退役；
  面板 tab 是事实面 KPI 卡（mock v11 无仪表盘），无 canvas 可守。
- 移交：数据聚合 L1（host/metrics.ts、metrics-model、metrics-charts 的 tests/*）原样保留；面板 tab 事实面
  由 t261005-10 journey U4（fixture 数值可见）承接。
- 认赔：真浏览器下 echarts 交付/时间/令牌环形图无人守——若宿主要回迁仪表盘，按本留痕复活。

### t260905-06-doc-entry-present
- 守什么：左列「文档」图标在场/键盘可达/active 高亮。
- 为什么退：Docs 迁入面板 Docs tab，宿主图标退役（More views 只剩 Model Routes + Project Settings）。
- 移交：面板 Docs tab 在场 + 渲染由 t261005-10 journey U3 承接。
- 认赔：无（入口面由 journey 的 data-tab="docs" 契约守）。

### t260905-06-doc-read-through
- 守什么：宿主文档视图目录→篇→正文链路、穿路径拒收、窄栏单栏流。
- 为什么退：被测视图整体退役。数据面契约（tree/doc 白名单/穿路径 fail-closed）不随视图退役。
- 移交：API 契约由 t260910-10-docs-project-anchor 承接（未退役）；面板 Docs tab 的 tree+正文渲染由
  t261005-10 journey U3 承接（同一 renderMarkdown 渲染器）。
- 认赔：窄栏单栏流在面板 Docs tab 内无人守（后续如需，开面板 Docs tab 版面票）。

### t260910-10-docs-ui-mock-v1
- 守什么：宿主文档视图 mock v1 版面旅程（chips/大纲/搜索/折叠/空态）。
- 为什么退：视图退役（同上）。
- 移交：API 锚解析/回落/注入面由 t260910-10-docs-project-anchor 承接（未退役）。
- 认赔：文档阅读 UI 的细粒度旅程（大纲跳转/搜索过滤）在面板 Docs tab 无人守——面板 tab 是精简只读面，
  如宿主要全量旅程，开票补。

### t260915-10-docs-follow-project
- 守什么：DocsSection 跟随壳层项目（初值/手动优先/重挂载/空态指引）。
- 为什么退：跟随语义被 ?project= 深链取代（面板 tab 由宿主按项目深链打开，无第二项目语境源）。
- 移交：面板侧项目语境 = executor-panel 深链（executor-view.tsx executorPanelUrl），由 t260929-22 族先例锚守。
- 认赔：无独立场景守「面板 Docs tab 的 project 参数透传」（t261005-10 journey 的 stub 按 URL 断言可扩展）。

### t260915-09-epics-client-project-wire
- 守什么：宿主立项单视图的 client/host wire（?project= 穿参）。
- 为什么退：宿主 Epics 视图退役；面板 Epics tab 的 wire 由 /epics?project= + /epics/<code>/tickets?project= 承接。
- 移交：面板 epic 面（列表/票行/下钻）由 t261005-10 journey U1/U2 承接。
- 认赔：epics 端点 per-project 锚（KI-057）在面板消费面无独立旅程（API 面仍有 L1/L2）。

### t260915-08-board-ui
- 守什么：状态看板巡检行卡的 UI 渲染层（S0 bundle 锚 + S1 真点）。
- 为什么退：状态看板整体删除（UI-2 票面第一句）；巡检行在左栏的行卡与详情浮层巡检面不随看板退役。
- 移交：巡检数据面由 t260915-08-board-rows / sign-journey 承接（未退役）；面板 Inspection tab 在场由
  t261005-10 journey 承接。
- 认赔：巡检行「等你黄底/去签字钮」的行卡级 DOM 断言无人守（左栏行卡仍有黄调 CSS 与徽标，无专场景）。


## 261005 退役批二（t261005-10 arbitrate round-2 Family C 收口；登记=integration 岗位复核项）

### t260904-17-ticket-list-rowcard-ui
- 守什么：中列状态看板整页契约——四态 chips 计数、行卡动作位（Sign →/View Reason）、收口折叠、分页。
- 为什么退：状态看板整页随 UI-2 删除（票面第一句）；这些判据全是板面页 DOM，无处可迁。
- 移交：左栏行卡 `data-ticket-id` 可测性锚由 t260915-19 / t260916-15 sidebar 场景继续守；
  行卡组件共享（TicketRowCard 同一实现，compact 只是省略站道与动作位）。
- 认赔：板面级「状态分布一眼可见」无人守——这是 UI-2 的既定产品取舍（左栏=有序队列，面板 tab=状态面）。

### t260905-07-ticket-detail-panel
- 守什么：板面全尺寸行卡的行标题契约（data-wb-row-title / data-title-src=first）+ enrich=progress
  数据通道 + 行点击开详情抽屉。
- 为什么退：板面删除后，夹具票（t260903-10 等 9 月初收口票）已出左栏驻留窗（sandbarHours 窗），
  左栏重定位在真实台面上不可达——不是改锚能解，是被测可达面消失。
- 移交：`data-wb-row-title` 属性仍由共享组件 TicketRowCard 渲染（左栏 compact 卡同样带锚），
  组件级断言留待后续票以组件测试接管；enrich=progress 数据通道由 host 契约测试守；
  行点击→详情浮层由 t261005-04-ticket-detail-overlay 承接（已重定位绿）。
- 认赔：行标题契约暂无专场景（组件级补测为后续项，登记为欠账而非静默丢失）。

### t260907-08-wb-contrast-quadrant
- 守什么：四视图（board/docs/epics/metrics 浮层）遍历的中列文字对比度四象限走查。
- 为什么退：被遍历的宿主视图整体退役（board 删除、Docs/Epics 迁面板 tab、度量浮层三连同退）——
  走查对象不复存在，子用例全数落 na 不是「绿」是「无对象」。
- 移交：对比度哨兵语义由主题令牌（DERIVE_TOKENS_CSS）与 t260905-08 contrast-guard 的存活面承接；
  面板九页签的对比度走查属面板 tab 世界，若宿主要求，按面板 tab 版面开新走查票。
- 认赔：面板 tab 面的文字对比度暂无遍历场景（面板页用既有主题词表，零硬编码色——t261004-10 教训口径）。

## 261011 退役批（宿主令「不在名册的要来干嘛，删了」；integration 岗执行，main 直修不开票）

> **判据（本轮新增，写给下一次）**：三条同时成立的场景 = **无主**——①**不在 `known-red` 名册**（⇒ 没有 owner / retire_when 两个必填字段）；②所在池（`engine` / `exclusive`）**被泳道轮排除**（回执里 `excluded_pools`，`excluded_count` 88）⇒ **永不进票头账**；③**线轮跑全量** ⇒ 它们只以"这棵树不绿"的形态反噬认证面。⇒ 三条同时成立时，它们既不被修、也不被挂账、也没有人认领。详见 `KI-01M4MVHTHHS52JXZ9C6JRE8KXM`。
> **先测后删**：退役前先把"承接面"跑绿作为移交证据——`out/integration-report-261011-151427.json`：`ran 4 / pass 4 / fail 0 / wall 24.5s`（`t260913-01-authz-signal-delivery` 10.0s、`t260912-03-authz-cli-queryable` 6.4s、`t260925-08-undeclared-refuse-flip` 0.1s、`t260925-08-lane-caller-injection` 0.1s）。

### t260912-03-authz-overlimit-accept
- 守什么：仲裁上限的人授权回灌消费面（uses≥1 / 推进 / 判决原文），真 docker 台 + 桩脑 + 单票单 worker。
- 为什么退：**不在名册、无 owner**；池 `engine` 被票轮排除 ⇒ 台账最后一行停在 10-10 08:58，期间无人修也无人挂账；线轮（跑全量）里它红 ⇒ 只以"树不绿"形态出现。今日主树定点复跑仍 FAIL（602.7 s）。
- 移交：**授权通道的消费面**由 `t260913-01-authz-signal-delivery`（真信号送达 + 丢失可见化，10.0 s 绿）与 `t260912-03-authz-cli-queryable`（用户可查面，6.4 s 绿）承接。
- 认赔：**"仲裁超限回灌"这一支的具体推进语义**暂无专场景（`uses≥1` 的边界情况没人再看）；真链路（docker 台 + 桩脑）这一层不再有场景。

### t260915-12-gate-real-chain
- 守什么：跨项目写操作闸的**真链路**用户契约（declared 身份 / 越权旗 / 对账面），真 docker 台 + 真 CLI + 真专属 worker + 真 workflow。
- 为什么退：同上的三条（不在名册 ⇒ 无主；`engine` 池票轮不跑；线轮里红）。今日主树定点复跑 FAIL（251.9 s）。
- 移交：**策略契约（undeclared=refuse + 旋钮 + 身份注入链）**由 `t260925-08-undeclared-refuse-flip` 与 `t260925-08-lane-caller-injection` 承接（各 0.1 s，离线、恒可跑）。
- 认赔：**跨项目闸的"真链路"这一层失去场景覆盖**——离线孪生锁的是源码与真函数重放，不覆盖容器边界/真投递；若某天真链路坏了，现在没有场景会叫。这是本轮**最主要的认赔项**。

### t260915-12-cross-project-gate
- 守什么：跨项目写闸的**离线源码锁**（锁 `UNDECLARED_POLICY` 常量与微型重放，无 docker/网络依赖，设计上恒可跑）。
- 为什么退：它锁的是 **`record` 现状**，而该现状已由 `t260925-08`（KI-119 收口）翻成 `refuse` ⇒ **断言对象已被产品自己废弃**（"移除机制时钉住它的东西只扫了一半"，同 `KI-01M4FEPBXC34V3KD5W7CMDZEPR`）；台账 5 行 **fail 5（一次没绿过）**、最后一行 10-10 08:58 ⇒ 典型的陈旧幻影红。它自身第 275-276 行还断言"真链路场景已登记"，与该场景同批退役。
- 移交：翻严后的新契约就由 `t260925-08` 两场景钉住（真源与它同款模式）。
- 认赔：无（断言对象已不存在，属"无对象"而非"降覆盖"）。
