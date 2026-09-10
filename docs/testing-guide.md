# 溯游测试环境隔离指南（M17）

> **铁律**：开发、测试等工单**不允许重启/停止/修改 `localhost:3099` 上正在运行的 dsh 进程**
> （那是总管/用户正在使用的生产控制台），也不碰生产 Temporal 的 `7233`（gRPC）/`8233`（Web UI）。
> 测试一律走本仓库的 **Docker 隔离测试环境**（`server/docker-compose.test.yml`）。

## 为什么需要隔离

生产环境本机直跑（非 Docker）：dsh 控制台 `3099`、Temporal `7233/8233`、worker 常驻。
开发/测试工单如果直接连生产 Temporal、或去重启 3099 控制台，会互相踩：
测试票面/工作流污染生产状态、控制台重启打断总管/用户会话。

所以测试在 Docker 测试环境里进行：**独立 Temporal + 独立 dsh 实例 + 独立端口 + 独立数据卷**，
与生产零交集。

## 拓扑与端口

| 端口 | 用途 | 谁在用 |
|------|------|--------|
| 3099 | 生产 dsh 控制台 | 总管/用户，**禁止碰** |
| 7233 | 生产 Temporal gRPC | 生产 worker（engine/run_server.sh），**禁止碰** |
| 8233 | 生产 Temporal Web UI | 生产 worker 同源，**禁止碰** |
| 3199 | **测试 dsh 控制台** | Docker 测试环境 |
| 17233 | **测试 Temporal gRPC** | Docker 测试环境（容器内 7233） |
| 18233 | **测试 Temporal Web UI** | Docker 测试环境（容器内 8233） |

测试 Temporal 使用独立 namespace `suyou-test`，数据落独立卷（`temporal-data` / `dsh-home`）。

## 快速启动测试环境

```bash
# 在仓库根执行
docker compose -f server/docker-compose.test.yml up -d
```

两服务镜像均本机自建、无 registry 拉取：`sh server/build-test-temporal.sh`、
`sh server/build-test-dsh.sh`（建镜像时联网一次；dsh 曾是每次起台容器内联网
`npm i` 全局装、每台 ~2 分钟，260908 起烤进镜像）。之后 `up`/`restart` 走缓存
与数据卷，秒级。启动后两个容器：

- `suyou-test-temporal`：独立 Temporal（temporalite dev server，SQLite 落盘）
- `suyou-test-dsh`：独立 dsh 测试控制台（3199）

**新数据卷首次 up 后补一步**：注册多项目化的 ProjectKey 与立项关联的 EpicCode
两个 search attribute（temporalite 无启动参数；注册落数据卷，之后重启自带）：

```bash
server/engine/bin/temporal operator search-attribute create \
  --name ProjectKey --type Keyword --namespace suyou-test --address 127.0.0.1:17233
server/engine/bin/temporal operator search-attribute create \
  --name EpicCode --type Keyword --namespace suyou-test --address 127.0.0.1:17233
```

漏注册 EpicCode 时，带 `--epic` 开工单会大声报错（不静默丢标），按上文补注册即可。

保留期同理（temporalite 默认 24h——关闭的 workflow 24 小时后**物理删除**，工单历史/
审计/验收证据会蒸发）：新数据卷首次 up 后设置一次（落数据卷，之后重启自带）：

```bash
server/engine/bin/temporal operator namespace update \
  --retention 876000h --namespace suyou-test --address 127.0.0.1:17233
```

> 来源立项：epic-linkage（决策缘由见 notes/epics/epic-linkage.md）

## 验证测试环境

```bash
docker compose -f server/docker-compose.test.yml ps

# 测试 Temporal：Web UI（浏览器打开，namespace=suyou-test）
open http://localhost:18233
# 或命令行核对（用仓库内 temporal CLI）
server/engine/bin/temporal --address 127.0.0.1:17233 operator namespace describe -n suyou-test

# 测试 dsh 控制台
open http://localhost:3199

# 健康探针（控制台 HTTP 可达即活）
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3199/
```

## 跑 worker / 自测（本机跑，指向测试 Temporal）

Temporal SDK 工具（`engine/.venv`）不装进容器；在本机用仓库内 venv 跑，
用环境变量指向测试实例——`server/engine/shared.py` 支持
`SANDBAR_TARGET_HOST` / `SANDBAR_NAMESPACE` 覆盖（缺省仍是生产 7233/default）。

```bash
# 测试 worker：连测试 Temporal（17233 / suyou-test）
SANDBAR_TARGET_HOST=127.0.0.1:17233 SANDBAR_NAMESPACE=suyou-test \
  server/engine/.venv/bin/python server/engine/worker.py --daemon

```

> ⚠️ **注意**：worker 一定带 `SANDBAR_TARGET_HOST=127.0.0.1:17233` 前缀，否则默认连生产
> `127.0.0.1:7233`（namespace default）——往生产 Temporal 写测试状态，等同碰 3099 级别的事故。

### 每工单专属 worker（260824 起）

工单 workflow 不走共享队列：每张工单一个 task queue（`suyou-ticket-<工单id>`）+
一个专属 worker 进程——`ticket create` 自动拉起（pidfile/log 在
`engine/data/worker-<工单id>.{pid,log}`），workflow 收口后 worker 查到状态
非 RUNNING 即优雅自退（30s 轮询）；巡检（dispatcher-scan）顺带对账：在跑工单缺
worker 补拉、已收口工单回收漏退 worker。共享队列 `suyou-poc` 只服务
dispatcher-scan / content-pipeline（仍需一个常驻共享 worker）。

测试环境验证专属 worker 生命周期时，环境变量会被 `ticket create` 透传给自动拉起的
专属 worker（spawn 继承调用方 env），所以测试工单连同它的 worker 都落在测试
Temporal 上，与生产零交集。

没有 Docker 的机器可用第二个本地 dev server 代替（同等隔离：独立端口+独立 db 文件）：

```bash
server/engine/bin/temporal server start-dev --ip 127.0.0.1 --port 17233 \
  --ui-port 18233 --db-filename /tmp/suyou-test.db \
  --search-attribute ProjectKey=Keyword --search-attribute EpicCode=Keyword
# namespace 用 default 即可（SANDBAR_NAMESPACE 缺省），测完 pkill 掉、删 db 文件
```

> 来源立项：epic-linkage（决策缘由见 notes/epics/epic-linkage.md）

## 测试控制台里看不到生产工单？

正常。260823 起工单真源恒为 Temporal workflow（旧 tickets/ JSON 投影目录已删）——
测试控制台连的是测试 Temporal（17233 / suyou-test），与生产（7233 / default）完全隔离。

## 停止 / 清场

```bash
docker compose -f server/docker-compose.test.yml down      # 停，保留数据卷
docker compose -f server/docker-compose.test.yml down -v   # 连测试数据卷一起清（测试票面/工作流全没）
```

## 故障排查

- **temporal 起不来**：`temporalio/temporalite` 已停维护；若 flag 不兼容，可删掉该服务的
  `entrypoint`/`command` 两行退回镜像默认（namespace 变 default、数据不落盘），或换成任意
  dev 模式 Temporal（官方 temporal CLI `temporal server start-dev`，同 engine 路径）。
- **3199 打不开**：容器首次启动要装依赖，`docker compose logs dsh` 看进度；装完才 `exec dsh`。
- **worker 连不上测试 Temporal**：确认 `docker compose ps` 里 `suyou-test-temporal` 在跑；
  宿主侧地址是 `127.0.0.1:17233`（不是 7233）。

## 测试数据纪律（260904 宿主裁定）

背景：epic-status-enum 曾把 suyou 时代的真数据快照（写死 9 张 charter 清单+逐张 note
点名）塞进组件单测——sandbar 迁仓后只剩 2 张即红，测试在追真数据跑。裁定分层：

| 层 | 数据源 | 断言什么 |
| --- | --- | --- |
| 组件单测（workbench tests/） | fixture/tmp 受控数据 | 逻辑面：枚举合法性、错误文案、配置驱动语义——与真实仓状态无关 |
| 真数据不变量（可选） | 真实仓文件 | **性质**而非快照：全部可解析、值 ∈ 合法枚举——真源增删不红，坏数据才红 |
| 「恰好 N 项已知清单」类断言 | —— | 不允许：清单真源就是数据目录本身，测试镜像它没有守护任何东西 |

判定口诀：**新增一条真实数据（立项一张 epic、加一张工单）不应让任何测试变红**；
变红了就说明该断言在快照现实，应重构为 fixture（逻辑）或性质（不变量）。
例外：合同冻结类集成场景（契约文档守卫、golden 基线）以「钉住真源」为使命，快照
是其语义本体，不在此列——它们住在 integration/ 场景清单，不在组件单测。

## 外部调用形状单测规范（KI-046，260904）

背景：t260904-07 的 charter 注入把裸字符串传给平台 `session.prompt(content, mode)`，
平台 wire 契约要求 `PromptContentPart[]` 分片数组 → apiproxy zod 拒收
`invalid payload for session prompt`，核心功能上线即 100% 失效。能拦住它的类型闸
被 `any` 类型面抹平、调用形状测试缺失、唯一旅程场景在合并闸干净 SKIP——三层全漏。
本规范把「第三方调用必须有测试覆盖」从期望落成 developer 侧的机械义务。

**条款**：凡新增**不由本项目控制的进程外接口**调用点（HTTP API、CLI 子进程、
平台 SDK……dsh 与 Temporal 只是本仓实例），该调用必须在 developer 单测里带
**mock 形状断言**：捕获实参、对照对端契约校验——对端真 schema / d.ts 可导入则
直接 import；不可导入则用**仓内冻结镜像**（常量+注释注明真源位置与同步责任）。
消费外部输入（LLM 产出物、用户输入、文件、网络数据）的畸形输入用例纪律不变，
与此并行适用。没有这类调用点的项目，条款自然空转。另注意两条平台语义陷阱
（KI-046 实锤）：①平台 RPC 的**业务失败不 throw 只返回结果对象**（如
`RpcResult{ok:false}`）——检查返回值，不能只靠 catch；②类型面不收窄，tsc 就不是闸。

**范式**：`server/plugins/workbench/tests/ki046-charter-prompt-shape.mjs`——行为级 mock
（真加载模块、桩捕获 prompt 实参、对照冻结镜像契约、畸形输入全路径）+ 三方一致锚
（src 与构建产物调用形状一致，防「改 src 没重建 bundle」）。

**分工口径**：形状断言=mock，归 developer 单测，不归集成；集成侧不写 mock，只在
仲裁加固定问句「本票新增外部调用吗？形状单测在哪？」——把关不代做。

## 断言落点：终态保底 + 契约层并行（260910）

背景：同一天两次「全绿合并、用户用不了」，加一条同族，三案同骨架——
**断言落在「我造的东西」上，而不是「你要的东西」上**：

1. **暂停功能（t260908-01）**：交付物=列表上点暂停/恢复；场景断言的是引擎查询面
   `paused=True` 与引擎列表数据（中间面），真终态是 console 列表接口 + 页面按钮。
   断点：host 未透传字段 → 场景全绿、票合并，界面无恢复按钮。
2. **多仓修复（t260910-03）**：交付物=成员仓代码真被搬进成员仓；场景断言的是一条
   **契约层**字段（TicketInput.repo_worktrees 持久化，要过 Temporal 编解码，本身是好
   断言），真终态是泳道磁盘上成员仓工作区目录+分支+清单文件。断点：workflow→建泳道
   那一跳丢字段 → 场景全绿、票合并，真项目仍建单仓泳道（KI-071）。
3. **UI 证据闸**：闸断言的是截图**文件存在**，不是截图**内容拍到了该拍的东西**——
   空板废图带全绿进归档，直到人眼一看才发现（KI-069）。

### 条款

**1. 终态层（保底，每票至少一条）**
先写清交付物的「终态面」——它最后被谁消费：人点按钮→页面 DOM/界面接口；别的项目跑票
→磁盘上的仓与目录；文档给人读→渲染后的页面；下游系统吃→接口返回字段。断言必须落在
这一面。

**2. 契约层（并行，鼓励写）**
有明确契约的中间面**应当**断言：活动输入输出结构、HTTP/接口形状、文件格式（如清单）、
状态字段契约。它们是对下游的**承诺**，承诺破了就是真回归——即使这一轮终态碰巧还对。
这正是防「中间错、最后意外对」的唯一手段（否则要等下一个消费者才炸）。

**3. 细节层（不作证据）**
内部变量、私有函数、无人消费的中间文件布局——不作为验收证据（可保留作诊断定位）。

**4. 两个方向都要封口**

| 情形 | 只有谁能发现 |
| --- | --- |
| 契约对、终态错 | 终态断言（装配那一跳断了） |
| 契约错、终态意外对 | 契约断言（主干碰巧绕过，下一个消费者才炸） |

只留一层，必留半个盲区。t260910-03 的教训不是「断言写错了」，而是**写不全**：
契约层验了、终态层没验，而断的恰是没验的那层。

**5. 写场景时两问自查**
① 这条终态断言，能证明用户能做他要做的那件事吗？
② 契约破了，会被谁、在哪一层发现？

**6. 成本配比（不是到处端到端）**
一条终态主干 + 契约层覆盖 + 细节层诊断。终态断言贵（起台/开浏览器/真建票），所以一条
主干即可；但也不能只有函数级直调冒充全链（KI-063 反例：场景全函数级绿、真开票即
TypeError）。

**7. 把关面同步（integration 签字口径）**
签字复核不是「你的断言过了没」，而是先问「**你的断言落在终态了吗；没有的话终态我
怎么自己验一遍**」。t260910-03 签字时 integration 跟着其断言面复核（同样只验载荷），
两双眼睛漏在同一盲区——这条纪律即为此立。

