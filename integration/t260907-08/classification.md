# t260907-08 四档归类清单（工单「举一反三全量清单」的落地件）

状态：设计段初版（design_integration_tests 落盘）；implement 段逐处补全归因后定稿；
merge 关卡按本清单抽查。裁决口径见 §1，本清单是 KI-055 修复的交接证据面之一。

## 1. 计数对账口径（裁决式）

三套数并存，**裁决口径=sc_hex_clean.mjs 的「样式消费位」判定**（A 调色板值级豁免＋
B metrics-charts.ts 整文件豁免＋C token 声明位行级判定，零特例新增）：

| 口径 | 数值 | 性质 |
|---|---|---|
| 看守消费位判定（裁决口径，260907 实跑） | docs.tsx 33 行＋index.tsx 7 行（.wb-dsnap-* 尾段），其余文件零点名 | 待令牌化的真集合 |
| 工单举一反三分项（docs 33/index 51/theme 30/ticket-list-model 11/metrics-charts 7/sidebar 5/epics 4/project-modals 1，分项加总 142≠合计 112——工单原文算术，不考古） | ~112/142 | 静态 grep 值出现口径，其「裸奔」多数实为 var() 兜底值（C 类豁免位） |
| 原始 grep 值计数（index 356 行、epics 45 行等） | — | 含定义位/兜底位，仅作穷尽性对账底账 |

归因三式（每条非令牌化归类必须落到其中一式并带 file:line 证据）：
1. **单行 var() 兜底位**：`var(--name, #hex)` 单行可见——C 类豁免，看守已放行；
2. **token 定义位**：`--name: #hex`（自定义属性定义值）——C 类豁免；
3. **跨行 var() 看守盲区**：hex 兜底值写在 var( 的后续行——看守行级判定不保证，
   标注「人工核 verify」，若为真消费位→令牌化，并登记看守改进项另票（不在本票扩权）。

## 2. 今日裁决口径点名（260907 实跑 sc_hex_clean，SUMMARY pass=2 fail=1）

- `docs.tsx` 33 行：DOCS_STYLE 全量样式消费位裸 hex（#2a2f3a/#161b22/#c9d1d9/#8b949e/
  #3a404c/#21262d/#30363d/#fff/#a5d6ff/#ff7b72/#79c0ff/#ffa657 等）——**待令牌化**，
  本票交付主面；tok-* 语法高亮 5 色（#8b949e/#a5d6ff/#ff7b72/#79c0ff/#ffa657）→
  --dsw-derive-dark-* 派生族映射（dark-muted/dark-accent/dark-red/dark-accent/dark-amber 系），
  映射后目视裁量区分度，不够才在 theme.ts 增补并头注登记。
- `index.tsx` 7 行（:655-661 .wb-dsnap-* 尾段：#57606a/#8c959f/#cf222e/#f6f8fa/#d0d7de）——
  **待令牌化**；全文件其余 grep 命中=定义位/兜底位（豁免），implement 段逐条对账。

## 3. 四档归类总表（初版；implement 段补全 file:line 级归因）

| 文件 | 工单口径数 | 归类 | 依据/证据 |
|---|---|---|---|
| docs.tsx | 33 | **令牌化**（本票交付） | 看守今日点名；t260905-06 按深色写死、08 号漏网＝宿主实报源 |
| index.tsx | 51 | 尾段 7 行**令牌化**；其余=兜底位豁免（逐条补证） | 看守今日点名 ：655-661；epics 抽查同款先例 |
| theme.ts | 30 | **token 定义位豁免**（C 类） | ALIAS/TOKEN/DERIVE 定义值位，令牌体系的定义侧＝合法固定面 |
| ticket-list-model.ts | 11 | **调色板声明豁免**（A 类值级） | EPIC_PALETTE 10 档＋EPIC_FALLBACK_COLOR，确定性哈希色，看守按值解析放行，17 号断言守着 |
| metrics-charts.ts | 7 | **B 类整文件豁免** | HUMAN_COLOR/PALETTE=echarts 数据可视化编码色（:19-20），非文本对比度语义，头注声明在位 |
| sidebar.tsx | 5 | 兜底位豁免（抽查全单行 var()，逐条补证） | :216-241 抽查=var(--dsw-alias-*/derive-*， #hex) 单行兜底 |
| epics.tsx | 4 | 兜底位豁免（抽查全单行 var()，逐条补证） | :53-62 抽查同上 |
| project-modals.tsx | 1 | 兜底位豁免（抽查全单行 var()，逐条补证） | :41-51 抽查同上 |
| metrics.tsx | （工单未列，实扫 21 行） | **逐行复核归类**（implement 段） | 全族排查扩面（实报即全族线索）；消费位→令牌化，兜底位→豁免+证据 |
| project-icons.tsx / metrics-entry.tsx | （工单未列，各 1 行） | 逐行复核归类（implement 段） | 同上 |

## 4. KI-055 根因注记（④的答案，交接 integration 岗位登记台账修正）

工单④问「08 号为何没网住：豁免清单还是扫描范围」——**两者都不是**：hex 看守扫描面
覆盖 client 全目录、docs.tsx 不在任何豁免清单，看守今日即红并逐行点名（§2）；
红因=**t260905-08 的令牌化实现腿本身未落地**（看守头注自述「实现落地前红属预期，
TDD 信号」）。本票交付=把红修绿，看守扫描逻辑零改动。known-issues.md KI-055 症状①行
「hex 看守未网住（豁免或扫描面缺口待查）」与实况相反，登记权在 integration 岗位
（工单代理不直接写清单文件），本节即修正依据。

## 5. implement 段收尾清单（全部完成，260907 结算）

- [x] metrics.tsx / project-icons.tsx / metrics-entry.tsx 逐行归类落 file:line：
      见同目录 `hex-inventory.txt`（看守同款判定逻辑机打全量 928 位：
      兜底位 859＋定义位 56＋调色板值级 11＋metrics-charts 整文件豁免＋消费位 **0**）。
      metrics.tsx 36 位全为单行 var() 兜底位；project-icons.tsx:12 为注释位引用
      （配色卡文档，形态同 var() 兜底）；metrics-entry.tsx:152 为字符串内联样式
      `var(--dsw-derive-accent,#0969da)`（C 类豁免）。
- [x] index.tsx / epics / sidebar / project-modals 全量 grep 命中行按归因三式对账：
      同上 inventory 文件逐行可查，消费位=0。
- [x] 跨行 var() 盲区核查：inventory 以「行级+回看 var( 前缀」判定，未见跨行消费位；
      四象限场景（真渲染断言）亦未咬出兜底位外的遗漏——两道独立证据互证。
- [x] 裁决口径终态：`node integration/t260905-08/sc_hex_clean.mjs` →
      `SUMMARY pass=3 fail=0 env_fail=0 na=0`（红→绿）。
- [x] docs.tsx tok-* 映射表定稿（按实际色值盘点）：

| 原 hex（docs.tsx） | 语义 | 落点 |
|---|---|---|
| #8b949e（tok-c） | 注释灰 | --dsw-derive-dark-muted（#b8b8c8） |
| #a5d6ff（tok-s 字符串） | 字符串蓝 | --dsw-derive-dark-accent（#7ab8ff） |
| #ff7b72（tok-k 关键字） | 关键字红 | --dsw-derive-dark-red（#f87171） |
| #79c0ff（tok-n 数字） | 数字蓝 | --dsw-derive-dark-accent（#7ab8ff） |
| #ffa657（tok-v 变量） | 参数橙 | --dsw-derive-dark-amber（#ffd166） |

## 6. implement 段实际改动账（260907，developer 落）

| 文件 | 改动 | 驱动 |
|---|---|---|
| docs.tsx | DOCS_STYLE 全量令牌化（33 位：普通面→derive-*；代码块面→dark-* 家族）＋DERIVE_TOKENS_CSS 前置注入（独立挂载纪律） | 症状①实报源；看守今日点名 |
| index.tsx | .wb-dsnap-* 尾段 11 位令牌化（gate/signature chip→surface/accent-bg 族）；**四象限实咬后收编** .wb-md 作用域 knowledge 出厂件（.md-code/.md-cl/.md-copy/.tok-* 固定浅色→派生令牌，升特异性压同特异性后注入）；禁用钮 opacity 降权→令牌化灰字（3 处） | 看守今日点名＋四象限 new-dark 格 1.08:1 实锤 |
| theme.ts | dark 家族 +3：dark-border/dark-surface/dark-surface-2（#2a2f3a/#21262d/#30363d，GitHub Dark 系与改造前 docs 写死值同源）；theme-tokens.mjs UT 不变量同步 9→12 精确点名 | docs 代码块面位缺口（方案 §3「缺才增」） |
| epics.tsx | 禁用钮 opacity:.5→令牌化灰字 | 四象限 new-light 格 3.16<4.5 实锤 |
| project-modals.tsx / project-session-row.tsx | 禁用钮 opacity .45/.4→令牌化灰字（全族同款 sweep） | 全族排查纪律 |
| tests/theme-tokens.mjs | ①ALIAS fallback 判定补「平台契约式嵌套兜底」形态（t260907-03 双兜底入账时 UT 漏更的存量红，本票顺便修正）；②dark 家族不变量 9→12 精确点名（登记制收紧非放水） | 既有红＋设计变更同步 |
| lib/client.cjs+js | tsdown 重建（隔离台加载 bundle，src 改后必须重建——README 既有约定） | 构建链 |

## 7. KI-055 台账修正证据（交接 integration 岗位）

工单④「08 号为何没网住」**答案=都不是**：扫描面覆盖 client 全目录、docs.tsx 不在
豁免清单、看守当日即红并逐行点名——红因=t260905-08 令牌化实现腿未落地（看守头注
自述「实现落地前红属预期，TDD 信号」）。known-issues.md KI-055 症状①行
「hex 看守未网住（豁免或扫描面缺口待查）」与实况相反，登记权在 integration 岗位，
本节＋`hex-inventory.txt` 即修正依据。

## 8. 遗留（merge 关卡跟进）

- legacy×深格：0.1.1-rc.2 深底 bg-base 代表值待宿主按 walkthrough.md C2 步确认，
  确认后填 sc_wb_contrast_quadrant.mjs 的 `LEGACY_DARK_BG_BASE` 常量（na→硬腿）。
- tok-* 语义高亮走「固定暗面板」档（docs.tsx 内深面板成对），若宿主要求语法高亮
  随外观翻转为浅底系，另开裁量票（现口径=代码块自备深底，前后景成对合法）。
