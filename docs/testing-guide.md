# 溯游测试环境隔离指南（M17）

> **铁律**：开发、测试等工单**不允许重启/停止/修改 `localhost:3099` 上正在运行的 dsh 进程**
> （那是总管/用户正在使用的生产控制台），也不碰生产 Temporal 的 `7233`（gRPC）/`8233`（Web UI）。
> 测试一律走本仓库的 **Docker 隔离测试环境**（`server/dsh/docker-compose.test.yml`）。

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
| 7233 | 生产 Temporal gRPC | 生产 worker（temporal-poc/run_server.sh），**禁止碰** |
| 8233 | 生产 Temporal Web UI | 生产 worker 同源，**禁止碰** |
| 3199 | **测试 dsh 控制台** | Docker 测试环境 |
| 17233 | **测试 Temporal gRPC** | Docker 测试环境（容器内 7233） |
| 18233 | **测试 Temporal Web UI** | Docker 测试环境（容器内 8233） |

测试 Temporal 使用独立 namespace `suyou-test`，数据落独立卷（`temporal-data` / `dsh-home`）。

## 快速启动测试环境

```bash
# 在仓库根执行
docker compose -f server/dsh/docker-compose.test.yml up -d
```

第一次 `up` 需要联网（dsh 服务 `npm i` 全局 dsh + profile bundles、`apt` 补 python3），
之后 `up`/`restart` 走缓存与数据卷，秒级。启动后两个容器：

- `suyou-test-temporal`：独立 Temporal（temporalite dev server，SQLite 落盘）
- `suyou-test-dsh`：独立 dsh 测试控制台（3199）

**新数据卷首次 up 后补一步**：注册多项目化的 ProjectKey 与立项关联的 EpicCode
两个 search attribute（temporalite 无启动参数；注册落数据卷，之后重启自带）：

```bash
server/dsh/temporal-poc/bin/temporal operator search-attribute create \
  --name ProjectKey --type Keyword --namespace suyou-test --address 127.0.0.1:17233
server/dsh/temporal-poc/bin/temporal operator search-attribute create \
  --name EpicCode --type Keyword --namespace suyou-test --address 127.0.0.1:17233
```

漏注册 EpicCode 时，带 `--epic` 开工单会大声报错（不静默丢标），按上文补注册即可。

保留期同理（temporalite 默认 24h——关闭的 workflow 24 小时后**物理删除**，工单历史/
审计/验收证据会蒸发）：新数据卷首次 up 后设置一次（落数据卷，之后重启自带）：

```bash
server/dsh/temporal-poc/bin/temporal operator namespace update \
  --retention 876000h --namespace suyou-test --address 127.0.0.1:17233
```

> 来源立项：epic-linkage（决策缘由见 notes/epics/epic-linkage.md）

## 验证测试环境

```bash
docker compose -f server/dsh/docker-compose.test.yml ps

# 测试 Temporal：Web UI（浏览器打开，namespace=suyou-test）
open http://localhost:18233
# 或命令行核对（用仓库内 temporal CLI）
server/dsh/temporal-poc/bin/temporal --address 127.0.0.1:17233 operator namespace describe -n suyou-test

# 测试 dsh 控制台
open http://localhost:3199

# 健康探针（控制台 HTTP 可达即活）
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3199/
```

## 跑 worker / 自测（本机跑，指向测试 Temporal）

Temporal SDK 工具（`temporal-poc/.venv`）不装进容器；在本机用仓库内 venv 跑，
用环境变量指向测试实例——`server/dsh/temporal-poc/shared.py` 支持
`SUYOU_TARGET_HOST` / `SUYOU_NAMESPACE` 覆盖（缺省仍是生产 7233/default）。

```bash
# 测试 worker：连测试 Temporal（17233 / suyou-test）
SUYOU_TARGET_HOST=127.0.0.1:17233 SUYOU_NAMESPACE=suyou-test \
  server/dsh/temporal-poc/.venv/bin/python server/dsh/temporal-poc/worker.py --daemon

```

> ⚠️ **注意**：worker 一定带 `SUYOU_TARGET_HOST=127.0.0.1:17233` 前缀，否则默认连生产
> `127.0.0.1:7233`（namespace default）——往生产 Temporal 写测试状态，等同碰 3099 级别的事故。

### 每工单专属 worker（260824 起）

工单 workflow 不走共享队列：每张工单一个 task queue（`suyou-ticket-<工单id>`）+
一个专属 worker 进程——`ticket create` 自动拉起（pidfile/log 在
`temporal-poc/data/worker-<工单id>.{pid,log}`），workflow 收口后 worker 查到状态
非 RUNNING 即优雅自退（30s 轮询）；巡检（dispatcher-scan）顺带对账：在跑工单缺
worker 补拉、已收口工单回收漏退 worker。共享队列 `suyou-poc` 只服务
dispatcher-scan / content-pipeline（仍需一个常驻共享 worker）。

测试环境验证专属 worker 生命周期时，环境变量会被 `ticket create` 透传给自动拉起的
专属 worker（spawn 继承调用方 env），所以测试工单连同它的 worker 都落在测试
Temporal 上，与生产零交集。

没有 Docker 的机器可用第二个本地 dev server 代替（同等隔离：独立端口+独立 db 文件）：

```bash
server/dsh/temporal-poc/bin/temporal server start-dev --ip 127.0.0.1 --port 17233 \
  --ui-port 18233 --db-filename /tmp/suyou-test.db \
  --search-attribute ProjectKey=Keyword --search-attribute EpicCode=Keyword
# namespace 用 default 即可（SUYOU_NAMESPACE 缺省），测完 pkill 掉、删 db 文件
```

> 来源立项：epic-linkage（决策缘由见 notes/epics/epic-linkage.md）

## 测试控制台里看不到生产工单？

正常。260823 起工单真源恒为 Temporal workflow（旧 tickets/ JSON 投影目录已删）——
测试控制台连的是测试 Temporal（17233 / suyou-test），与生产（7233 / default）完全隔离。

## 停止 / 清场

```bash
docker compose -f server/dsh/docker-compose.test.yml down      # 停，保留数据卷
docker compose -f server/dsh/docker-compose.test.yml down -v   # 连测试数据卷一起清（测试票面/工作流全没）
```

## 故障排查

- **temporal 起不来**：`temporalio/temporalite` 已停维护；若 flag 不兼容，可删掉该服务的
  `entrypoint`/`command` 两行退回镜像默认（namespace 变 default、数据不落盘），或换成任意
  dev 模式 Temporal（官方 temporal CLI `temporal server start-dev`，同 temporal-poc 路径）。
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

**范式**：`server/dsh/workbench/tests/ki046-charter-prompt-shape.mjs`——行为级 mock
（真加载模块、桩捕获 prompt 实参、对照冻结镜像契约、畸形输入全路径）+ 三方一致锚
（src 与构建产物调用形状一致，防「改 src 没重建 bundle」）。

**分工口径**：形状断言=mock，归 developer 单测，不归集成；集成侧不写 mock，只在
仲裁加固定问句「本票新增外部调用吗？形状单测在哪？」——把关不代做。
