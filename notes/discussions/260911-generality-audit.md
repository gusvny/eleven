# 通用性审计：昨晚（260910 夜）改的引擎与测试有没有把 sandbar 私货写进通用层

- 触发：宿主 260911 质询「昨晚改的引擎的、测试的一些东西，从通用的角度来说（别的项目也要用），我们有没有违背这个逻辑」
- 立场：机制在引擎，内容在项目声明。判定标准取自本项目已定稿的两条：KI-050 修复方向
  （「声明制，引擎只留机制」）与 260908 层错修正（「TicketInput 契约是引擎私货，不得污染
  多项目通用面」）。
- 方法：全仓字面量扫描（`/Users/user`、项目键、主机名）+ 逐条读实现 + 实测宿主侧路径存在性
  （只列文件名与存在与否，不读凭证内容）。
- 结论：**有 1 处是真违背，且正是昨晚新引入的，落在引擎正层（server/engine/）**；另有 1 组
  同族老债，昨晚那个文件被重写过但没顺手清。

---

## 一、真违背：受保护路径名单写死在引擎里（昨晚新引入）

**位置**：`server/engine/path_gates.py:55-72` `PROTECTED_PATHS`
**出生**：`0dd1df9`（t260911-03 squash 收口，260911 凌晨）——即昨晚的交付物。

名单内容全是 **sandbar 这个项目的文件**：

```
integration/t260902-07/tests/test_route_table.py
integration/t260902-07/tests/test_route_lookup.py
integration/baselines
verify.yaml
server/model-routes.yaml
server/merge-checks.yaml
server/projects.yaml
server/project-registry.ts
server/roles
docs/design
server/engine/path_gates.py
```

**为什么算违背**：「哪些文件是真源/期望值」是**项目的内容**，不是引擎的机制。引擎应该只留
「机制」——按项目声明给出的名单，判「泳道不得改名单内且基点已存在的文件」。现状是名单作为
引擎常量写死，**且没有任何项目声明入口**：全仓 `grep PROTECTED_PATHS` 只有定义处、
`judge_protected_paths`（`:282`）与它自己的单测引用，无注入参数、无 override 读取。

**对别的项目的实际后果（两种，都不好）**：

1. **闸静默全绿**：闸的语义是「存在才拦」（`:270-293`，`exists_at_base`）。别的项目仓里没有
   `verify.yaml` / `server/roles` / `docs/design` 这些路径 → 名单永不命中 → 闸永远放行。
   表现是「检查项在、看着验过了，其实什么都没验」。注意这里的 fail-closed 只针对**锚不可知**
   （谓词故障/None），不针对名单内容为空命中——所以它不会因为「别的项目」而报红示警。
2. **他项目自己的真源不拦**：别的项目自己的真源文件（命名/位置未必相同）不在名单里，本来
   想防的「泳道改期望值给自己发免红令」在那项目上照旧没有防护。

**同族登记在案**：KI-050（UI 证据闸写死 sandbar 五条 UI 路径，他项目=闸盲）是同一族病，
修复方向已定为声明制。本条是这一族的**第二例，且落点更核心**（受保护路径闸保护的是真源与
期望值，正是「人审环节不可被绕」的机械保障）。

**同类小项（不单列票，随上条一起想）**：
- `STAGE_PATH_RULES["design_integration_tests"]["prefixes"] = ("integration",)`（`:91`）：
  把「测试目录叫 integration/」当作所有项目的约定；
- `RESULT_FILE_PREFIXES = (".sandbar", ".suyou")`（`:48`）：平台级 dot 目录，可接受
  （`.suyou` 已标 naming-compat）。
- **风险提示**：待审清单里我原先列的「闸第二层（受保护名单扩到共享测试基建 + 他票场景目录）」
  若照现写法做，会把这个违背加深一层——这正是应改声明制的直接理由。

---

## 二、同族老债：共享起台工具里的宿主路径与项目键（260906 引入，不是昨晚）

**位置**：`integration/stage_docker.py`——**所有项目**的容器类场景都走它。

| 行 | 内容 | 实测 |
|---|---|---|
| `:932` | 候选 `~/.sandbar/projects/suyou/credentials.yaml`（**写死项目键 suyou**） | `~/.sandbar/projects/{suyou,sandbar,dengzhufpv}/credentials.yaml` **全都不存在** → 今天这条是死候选 |
| `:934` | 候选 `/Users/user/Documents/sandbar/.dsh/.credentials.yaml` | 与上一候选 `str(REPO/".dsh"/".credentials.yaml")` **是同一个文件**（`REPO = integration/..`，`:125`）→ 今天零功能价值 |
| `:952` | 候选 `/Users/user/Documents/sandbar/.dsh/.agent-presets` | 上文 `~/.dsh/.agent-presets` 实测**命中**（预设真身在那里），后两条恒为死候选 |

**危害（按严重度）**：

1. **跨项目串凭证隐患（`:932`）**：今天全项目都没有 per-key 凭证所以不触发；但只要有谁把
   suyou 的 per-key 凭证放上去，**任意项目**（如 dengzhufpv）起台都会静默使用 suyou 的凭证
   ——身份错位且无日志。引擎侧已有正确写法可抄：`agent_activities._resolve_credentials_source
   (project_key)`（`:226`）与 `shared.perkey_projects_root()`（按 key 解析 + env 缝）；
   而 stage_docker 手上本来就有 `project` 变量（`:936` 就用来拼临时文件名）。
2. **换机/换检出位置即死（`:934`/`:952`）**：症状是「容器里凭证/人格缺失」，即当初加这两行
   要修的那个 bug（shell-access overlay 挡住 pointer 全屏）原地复发，且外观像环境假红。
3. 泳道实测 8 条里 7 条有 `.dsh/.credentials.yaml` → 实际从来轮不到 `:934`，属纯负载。

**引入时间**：`e936847`（2026-09-06，t260904-19）——老债，不是昨晚的；但 t260910-12 昨夜
重写了这个文件（`c1b1971`），没顺手清。

---

## 三、干净的部分（正向）

- `server/engine/failure_protocol.py`（昨晚新生）：零项目字面量，协议本身项目无关
  （name/suite/三态 status/cause/reason/dur_s/attempt/git_sha/evidence/artifacts + 门生成摘要）。
- 模型路由表迁移（t260910-14）：`shared.resolve_routes_table()` 改为**读项目声明**并给出
  `decl_missing|file_missing|bad_content` 三态 + 仓内兜底——这是**方向正确的通用化**，与上条
  相反，值得作为后续修法的样板。
- `integration/t260911-*/` 新场景里写死具体票 id 与路径：场景局部本就该具体，不算违背。
- `server/engine/path_gates.py` 的阶段闸规则表（段×允许面）是通用的，只有上面第一节的名单是私货。

**诚实边界**：昨晚 13 号（结果协议 conftest/lib）我只做了字面量扫描，未逐行读实现；若要盖章
「零违背」需要补一遍精读。

---

## 四、处置建议（票未开，等宿主拍板）

1. **小票（引擎侧）**：受保护名单改声明制——引擎留机制 + 项目声明给出名单；须同时定死
   「缺声明」的行为（建议：闸拓扑级缺席，明确报告，不得静默全绿——同 KI-050 的立场），
   并把 `:932/:934/:952` 三条候选一并清成「按 project_key 解析」。
2. **或仅低风险清理**：先只清 stage_docker 三条候选（不进引擎语义，改动面小）。
3. **登记**：本条可作为 KI-050 同族第二例并入登记，冻结解除后再开票。
