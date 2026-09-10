# 模型路由表迁出 git：真源=项目声明所指向的文件（260910 宿主拍板）

> 状态：设计草案（待开票实施）。起因：宿主 260910 提出「model-route 不该只有 git
> 那一份，要支持另一个位置」；同日实况暴露 git 真源的三重摩擦（改表 → 工作区变脏
> → 撞 KI-048；提交 → 泳道继承过期守卫 → 堵全队列；UI 改的与引擎读的是两份）。

## 一、宿主拍板（260910）

1. **仓内 `server/model-routes.yaml` 不要了**——不再作为真源、不再作为 UI 写入目标；
2. **以 project 里配置的那份为准**：项目注册表条目 `paths.model_routes` 指向哪个文件，
   引擎就读哪个、UI 就写哪个（单一真源，读写同源）；
3. **init 流程**：路由表由用户在建项目时填/选（做一次填表不麻烦），
   必要时做一条 `sandbar project add` 的引导流程；
4. 不引入 env 覆盖层（曾提的 `SANDBAR_MODEL_ROUTES` 否决）；
5. **`epic-next` / `suggest_next` 整条退役**（宿主 260910 拍板：该功能无用，且实测两次
   拖慢合并收口各约 4 分钟）——退掉后本迁移票少一个引用点（见 §三 清单第 3 条）；
6. **init 引导先不做**（宿主拍板）：新项目按 docs 样例手填一份表即可；表缺失按新口径
   点名告警，不静默。

## 二、目标形态

| 面 | 现在 | 迁移后 |
| --- | --- | --- |
| 真源 | 仓内 `server/model-routes.yaml`（git 跟踪）+ 可被 `paths.model_routes` 覆盖 | **仅** `paths.model_routes` 指向的那份（缺省建议机器级 `~/.sandbar/projects/<key>/model-routes.yaml`） |
| 引擎读 | `MODEL_ROUTES_FILE` 常量/`routes_file_for_spawn` | 同一解析函数给出的路径（单一入口，读=写=生效） |
| UI 读/写 | 写 `<项目主目录>/server/model-routes.yaml`（git 文件，当场改工作区） | **同一解析路径**；界面显示「生效路径 + 来源声明 + 是否在 git 内」 |
| 仓内那份 | 真源 | **退役**（删除）；默认表示例移入 docs 或 installer 内置常量，作为 init 的模板 |
| 缺表行为 | 静默回落 profile 默认（KI-030 家族） | 显式点名：声明缺失/文件缺失/内容坏三态分别可辨，票面/日志告警（agent 仍可回落 profile 默认跑，但绝不静默） |

## 三、迁移与配套（实施票必含）

1. **解析放宽**：`paths.model_routes` 现只允许「项目主目录下的相对路径」（`_decl_rel`
   拦逃逸）——需支持机器级/绝对路径形态（建议：`~` 展开 + 绝对路径允许，仍拒绝 `..` 逃逸；
   相对路径语义不变）。
2. **现有两项目迁移**：sandbar 与 dengzhufpv 各把表从仓内拷到机器级目标 + 落声明；
   仓内那份随后删除（含引用清理）。
3. **引用点一并改**（今日实测清单）：
   - `server/engine/shared.py`：`MODEL_ROUTES_FILE` 常量退场，`model_route_for` 收路径参数单点；
   - `server/plugins/ui/src/host/routes.ts`（UI 读写，`:540`/`:203` 两处 `join(repo,'server','model-routes.yaml')`）；
   - ~~`server/plugins/workbench/src/host/epic-next.ts`~~ —— 该文件随 suggest_next 整条退役
     （宿主 260910 拍板），本迁移票不再触及；**前置票=退役票**。
   - 守卫 `integration/t260902-07/tests/test_route_table.py`、`test_route_lookup.py`
     （已去快照化，改读「声明指向的表」并保留性质断言）；
   - `server/plugins/workbench/node.ts` 注释与「模型」页（生效来源展示）。
4. ~~init 引导~~（宿主 260910 拍板先不做）：实施时 UI 的「初始化」动作若保留，落点必须
   是声明指向的文件（不落仓内）；新项目建表=人工按 docs 样例填。
5. **生效时机说明**：引擎在**每次派活时读表**（不需重启即生效）；console 的路由编辑
   端点在内存服务内（重启 3099 才见新逻辑，KI-052 同族）——界面须写明，避免「改了没生效」误读。

## 四、验收（终态优先，见 docs/testing-guide.md）

- **终态**：改声明指向的文件 → 下一张票 spawn 出的 agent 用新模型（spawn 面断言）；
  UI 保存 → 落到声明指向的同一文件（字节级断言），且**不产生任何 git 工作区变更**；
- **对照**：仓内已无 `server/model-routes.yaml` 时全链正常（证明真源已迁）；
- **三态**：声明缺失 / 文件缺失 / 内容坏 → 各自点名告警且可辨（禁静默）；
- **零回归**：单仓/多仓项目、隔离台（`SANDBAR_PROJECTS_DIR` 覆盖）语义不破；
- **守卫**：`test_route_table` / `test_route_lookup` 改为对「声明指向的表」做性质断言并全绿。
