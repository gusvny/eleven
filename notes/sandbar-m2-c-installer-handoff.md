# sandbar M2-C 代码票交接单：安装器 + 版本化 + 兼容矩阵探针

> 工单 t260903-08 implement 段产物（developer，2026-09-03）。方案（gen0/gen1）
> 经 review 两轮收口：gen0 reject（R1 执行钩子/R2 写集边界/R3 集成可执行面）、
> gen1 conditional 放行（附条 V1-V5 已全部吸收）。本单是 **sandbar 仓代码票的
> 硬输入**——代码落点 `/Users/xingu/Documents/sandbar`（suyou 仓写集之外，
> KI-021 写集冻结无扩写集机制，故代码归新票，起票方式见 §6）。
> 契约面真源已先行落地：`docs/design/sandbar-project-onboarding-contract-v1.md` v1.7 ⑧节。

## 1. 交付物（代码票四件，对应工单正文①②③④）

1. **安装器 CLI `sandbar`**（入口脚本 + bash/python 薄壳，落 sandbar 仓）：
   子命令 `init / up / down / status / doctor / upgrade`。管 Temporal dev
   server（7233/8233）与工单 worker 生命周期；**console（3099）永属用户操作面**：
   安装器只探测、只提示（输出「console 属用户操作面，请手动起停」），任何代码
   路径不得 spawn/start/launch/kill/pkill/重启 3099（硬规则 6）。
2. **版本化**：sandbar 仓根 `VERSION`（当前 `0.1.0`，唯一真源）+ `server/version.py`
   单源模块；引擎快照写 `sandbar_version` 键。写点改造范围：
   `base.py:227`、`dev_lane.py:512`（snapshot 组装处各加一键）；**legacy
   `temporal_engine_version` int 键原样保留不删**（消费方 `workbench/src/host/
   metrics.ts:253/301/478` 以 int 键作缓存键，不动）；口径=契约⑧-4（自 0.1.0
   起，不造历史映射，畸形 fail-closed）。
3. **dsh 版本区间**：契约⑧-1 已成文（本票 suyou 侧交付）；代码票只消费——
   `sandbar upgrade` 读契约⑧（或其仓内同源副本）展示区间与已验证点。
4. **兼容矩阵探针集** `server/probes/`（四面最小探针，规格见 §5）；
   `sandbar doctor` 跑全量，绿一行 append 一行到 `~/.sandbar/compat-matrix.json`
   （契约⑧-3 三轴：sandbar 版本 × dsh 已验证点 × 项目 schema 版本）。

## 2. 被借鉴实现故障模式取舍清单（R1 执行钩子，逐项表态；代码票必须照此实现）

| # | 被借鉴项 | 故障面 | 表态 |
| --- | --- | --- | --- |
| 1 | temporal-tools supervisor 端口单例探测（PORT_PROBE_TIMEOUT 1.5s / SERVER_START_TIMEOUT 30s，node.ts:204/:307-311） | 幂等 up 判据 | **带**：up 以 7233 探活为幂等判据，超时常量同量级 |
| 2 | supervisor pidfile 读侧容错（脏值→null，:232-235） | pid 文件损坏 | **带**：读侧 null 化 + 陈旧 pid（进程已不在）自清 |
| 3 | 存活探测 ESRCH/EPERM 分态（:221-225） | 误判死活 | **带**：EPERM=进程还在，报「权限不足需人工」，不判死 |
| 4 | worker SIGTERM 优雅停（:342）/ server SIGTERM 超时后 SIGKILL 升级（:353-357） | down 卡死 | **带**：down 先 TERM 后限时 KILL，超时限显式声明 |
| 5 | **server 意外退出 keepalive 5s 自动重启**（:385） | down 被复活 | **不带**：安装器是唯一拉起方、不装 keepalive 常驻（dev 语义）；见 #9 优先级 |
| 6 | worker.py `--daemon`（fork+setsid）+ 自写 `data/worker.pid`（worker.py:50-63） | 后台化能力 | **带能力不带真源地位**：复用 daemonize 手法，pid 写安装器 pidfile（见 #7） |
| 7 | **双 pid 真源**（安装器 `~/.sandbar/run/` vs `data/worker.pid`） | down 信哪个 | **单真源=安装器 pidfile**；`data/worker.pid` 降级为迁移期回落读侧（安装器 pidfile 缺失且 worker.pid 指向活进程→认领），两写禁止 |
| 8 | run_server.sh retention 校正 60 次静默放弃 | 校正失败无声 | **不带**：改为 fail-closed 显式报错（校正失败=红，不静默）；SQLite 数据卷随引擎新家（manifest ④R1：停 worker→停 server 保护历史真源） |
| 9 | **孤儿 server**（安装器 pidfile 丢、进程活着） | 永远停不掉 | **接管语义**：端口被占时查 pid，核对命令行含 `temporal server start-dev` 且数据卷路径属本安装→认领进 pidfile 后可 down；不匹配→报错不误杀 |

**#5 与 #9 的优先级（V1，防幽灵复活回归）**：两行对同一对象（supervisor 拉起的
sandbar server）都可能命中，**认领谓词必须含「非活 supervisor 父进程」判定**
（核对 ppid：父进程是本安装器/supervisor 且 supervisor 仍存活 → 属 #5 只报告
归属与处置指引、不对抗不认领；父进程已死（真孤儿）且 #9 谓词全中 → 才认领）。
认领仅限真孤儿。验收口径：down 一个 supervisor 持有的 server，结果必须是
「报告+不杀+不复活」，绝不能「杀后被 keepalive 5s 复活」。

## 3. 验收口径（代码票 implement 段自检清单）

- up/down/status 全子命令：正常、重复 up 幂等、down 时序（先 worker 后 server）、
  pid 损坏/陈旧、端口被占（含 #5/#9 分态）——全故障路径显式报错不静默。
- **3099 红线**：安装器源码级静态断言（仓内 sc_ 场景），禁词表=
  `kill / pkill / 重启 / spawn / start / launch` × `3099` 上下文（C1 补全后词表；
  「start-console.sh 提示文案」白名单豁免，断言须区分提示与执行）。
- 版本化：VERSION 三态（正常/缺失/脏行非 semver→fail-closed）；快照含
  `sandbar_version` 且 legacy int 键不动；`upgrade --to <ver>` 畸形态
  （C3）：坏 semver / 降版本请求 / 当前 VERSION 脏 → 全 fail-closed。
- 探针：四面各带 fixture 桩（含畸形：坏 json/缺文件/截断 session 流）红绿双向；
  矩阵 append 幂等 + schema 校验。
- 升级路径演练：`sandbar upgrade --dry-run` 输出版本 diff + 必查项命中清单
  （消费契约⑧-2 四条）。

## 4. 3099 与端口纪律

- 3099：只探测（TCP connect 判在位）、只提示；测试用 stub 进程/假端口，不碰真端口。
- 7233/8233：安装器管辖面；迁移窗口操作序=公告→停派活→排空→停 worker→停
  server→数据卷随迁→起服务→冒烟→恢复（manifest ④R5/R1）。
- `~/.dsh/profiles/suyou*` 软链重建（③T4）与 console 重启窗口须与总管协调，
  归 M2-D 切换票，本代码票只提供能力不执行切换。

## 5. 四面探针规格（工单正文④落地载体）

| 探针 | 面 | 对应必查项 | 最小断言 |
| --- | --- | --- | --- |
| probe-home-layout | dsh home 布局 | B1 | profiles/credentials/settings 存在性+文件名指纹（`.credentials.yaml`/`settings.yaml`） |
| probe-session-format | 会话格式 | C1/C2 | 固定 session fixture（zstd 行式事件流）解桩，断言 `assistant/message` 的 `data.usage{inputTokens,outputTokens,cacheReadTokens}` 可取 |
| probe-runner-assembly | runner 装配 | A4/A5 | dsh 安装内 stock `headless-runner` id 与 `inject:[headlessStartup]` 注入点存在性 |
| probe-settings-resolve | settings 层叠 | A3 | resolve 合成顺序探针：声明层 patch 值在合成结果中可观测（不被用户层静默盖掉） |

全部探针读 fixture/只读探测，不起真 dsh 进程、不写 dsh home；对真环境跑是
`doctor` 的可选 `--live` 档（代码票实现，缺省只跑 fixture）。

## 6. 起票方式与范围边界

- 建议宿主令开票（先例：M2-B「v0.1.0 搬迁快照」宿主令），写集=sandbar 仓；
  本单 §1-§5 即票据正文素材。
- suyou 仓侧本票已交付：契约⑧（v1.7）+ 本交接单 + doc-guard 场景
  （`integration/baselines/sc_sandbar_dsh_compat.mjs`）+ manifest 回填。
  suyou 仓 server/ 引擎代码冻结（搬迁快照后引擎一律只改 sandbar 仓，防两仓漂移）。

## 7. 遗留

- dsh 区间第二数据点待探针跑真 dsh 后 append（本票无真环境验证，不预支）。
- manifest ②A4/A5/A6/A7/A8/A9、③T2/T4、④R1/R5/R6 的代码实施全部随本代码票
  +M2-D 切换票闭环（suyou 仓 manifest 已标注承接关系）。
