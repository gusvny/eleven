---
title: "项目外置工作流模板加载口v1"
category: design
tags: [工作流模板, 项目外置, 加载口, 多项目, 隔离拒收, 演进纪律]
status: active
updated: 2026-09-24
---

# 项目外置工作流模板加载口 v1（t260924-04，票 1）

> 来源：nusuyou《给 sandbar 的需求说明：项目外置工作流模板》（§六接口形状）与
> 设计稿（`notes/discussions/260924-项目外置工作流模板-设计稿.md`）。本文是**加载口
> 的实现契约**：接口形状、拒收语义、消费方必须遵守的编码规约与演进纪律。
> 契约 v1 的 paths 键表见 [sandbar项目接入契约v1](sandbar项目接入契约v1.md) ①d。

## 一、是什么（三句话）

1. 项目在注册条目 `paths.workflow_modules` 声明自己的工作流模板模块清单（`,` 分隔，
   每项相对项目主目录 `dirs[0]`）；引擎启动时逐模块加载，与内置模板合并进同一张
   注册表（`shared.TEMPLATE_CLASS_NAMES` / `workflows_v2.TEMPLATE_CLASSES` 同源合并）。
2. **不声明 = 零行为变化**（契约 ①d 四类回落）；声明了但坏 = **模板级隔离拒收**——
   坏模板不注册、高声点名，同项目其他模块与别项目照常。
3. 生效粒度：启动时加载，**迟到声明（进程启动后写入）下个重启生效**；普通工单跑每票
   专属工人 → 新票启动即吃新码、在途票冻在启动时的码（KI-113；该结论以「票型模板不落
   共享工人」为前提，票 2 进程分池落地时须重审本文此条）。

## 二、接口形状（需求书 §六落地）

```yaml
# ~/.sandbar/projects/<key>/project.yaml
schema: v1
project:
  - key: <key>
    name: <名>
    dirs:
      - /abs/project/root
paths:
  workflow_modules: workflows/templates_a.py,workflows/templates_b.py
```

模板模块（每个 `.py` 恰一个模板类，同 `fixture_two_step` 惯例）：

```python
TEMPLATE_ID = "my-flow"            # 模板 id 全局唯一（数据面，照写不改名；撞名=改自己）
TEMPLATE_NAME = "我的流程"          # 工单台显示名
from temporalio import workflow
from base import TicketWorkflowBase
from shared import Stage

@workflow.defn
class MyFlow(TicketWorkflowBase):
    STAGES = (Stage(id="s1", name="…", role="developer", next="s2", acceptance=("…",)), …)
    PATCH_ID = "<key>-my-flow-v1"  # 见 §四：必须带 <项目key>- 前缀
    TEMPLATE_ID = "my-flow"        # 须与源码声明一致（不一致=拒收点名双方）
    TEMPLATE_NAME = "我的流程"

    @workflow.run
    async def run(self, inp):
        return await self._main(inp)
```

首票消费者 nusuyou 的 `content-studio`（`ContentStudioWorkflow`）按本形状接入；
该 id 若被占用由需求方改名，不争（需求书 §六原样有效）。

## 三、拒绝面（fail-closed 且精确点名）

三态各为结构化拒收记录（project / module / check / detail），经建票文案
（`ticket.py create` 与 `client.py ticket-start` 的「未知模板…」错误）可见——
**拒收 ≠ 装死**：不静默改名、不后到覆盖、不静默跳过。

| 检查 | 触发 | 点名内容 |
|---|---|---|
| 撞名 id | 模板 id 与内置/夹具/其他项目已接受 id 相同 | 检查名＋占用方（id、来源）＋来件方（项目/模块） |
| 畸形 | 缺 `TEMPLATE_ID`（或多值）、模板类不可辨、缺 `STAGES`、`STAGES` 空或非 tuple、段缺 `id/name/role`、`parts` 含非法值、源码声明与类属性不一致 | 检查名＋缺什么/双方值 |
| 加载失败 | 声明锚点缺失、模块不可读、import 抛错 | 检查名＋文件＋异常类型/摘要 |

另：**补丁标识撞引擎面**——项目模块声明的 `*_PATCH_ID` 与引擎面补丁标识集（加载时
从 `server/engine/*.py` 动态收集，不写死列举）相同 → 拒收点名双方值（见 §四）。

解析层（paths 声明值本身坏：空项/绝对/`..` 越界/非标量/条目缺 dirs 首项）沿用
契约 ①d 的 `ProjectPathsError` fail-closed 红；在加载口转为「声明解析失败」结构化
拒收，同样进建票文案，不静默当「未声明」。

## 四、演进纪律（对外置模板的硬约束）

1. **段序/拓扑变更 → 新模板 id 并存**：老在途票由老类跑完（每票专属工人冻启动时
   码）；新 id 与老 id 在注册表并存，互不影响。
2. **分支逻辑变更 → `workflow.patched()` ＋补丁标识带项目前缀**：在改动点用
   `workflow.patched("<key>-…-vN")` 分支，老历史走老分支、新历史走新分支，两边都能
   重放。**新补丁标识一律 `<项目key>-` 前缀**（主防线——前缀即不可能撞引擎现有
   `dev-lane-*`/`ki003-*`/`ticket-*` 形）；加载器动态收集引擎面标识集作兜底拒收
   （采集=源码静态扫描 `*_PATCH_ID = "…"`，未守惯例的新引擎补丁可能漏报，后果有限：
   patched 判等只发生在同一模板类自己的历史上）。
3. 真源=代码：改模板=改项目仓内的类定义；引擎仓的 `server/workflows/*.yaml` 参考
   快照**不覆盖外置模板**（`gen_workflows_doc.py` 对 `PROJECT_TEMPLATE_IDS` 显式
   声明式排除，`--check` 防漂移只钉引擎内置模板）。

## 五、安全面与确定性（不降级，原文适用）

- 人门唯一入口仍是 `sign`：外置模板走 `TicketWorkflowBase` 同一基类，无
  set-stage/force_stage 旁路；信号面只 sign/retry_qc（另有 pause/rework 既有面）。
- **确定性编码规约**（workflow 函数体纯确定性：零 IO、零随机、零墙钟，只用
  `workflow.now()`；副作用一律进 activity；改执行逻辑先 bump PATCH_ID 并在改动点
  `workflow.patched()` 分支）对外置模板同等适用。
- **clean-module 约束**（temporalio sandbox 会重执行定义模块）：模块体只允许
  import ＋类定义，零模块级 IO（`pathlib`/`subprocess`/`open` 一律禁止），
  `from shared import …`/`from base import …` 等引擎内 import 照
  `fixture_two_step` 放进 `workflow.unsafe.imports_passed_through()` 块。
- **sandbox 兼容双层防线（D3，t260924-04）**：① worker 构造时把外置模块装载名
  （`sandbar_ext_<key>_<stem>`）注入 `SandboxedWorkflowRunner` 的
  `passthrough_modules`——sandbox importer 按名解析到外层已装载模块，不再
  ModuleNotFoundError 崩工人；② 加载器类面对每个候选模板先用与 worker 同款
  restrictions 做 `prepare_workflow` 预校验，校验失败=「sandbox 校验失败」模板级
  拒收点名，永不进 worker 注册表——坏模板炸不垮工人进程（规格④边界）。
  passthrough 集＝**外置装载名 ∪ 其引擎依赖顶层名**（shared/base/activities/
  agent_activities/workflows/workflows_v2/dev_lane，D6）：activate 期 payload 解码
  要 `typing.get_type_hints` 按名查 `TicketInput` 所属模块，受限 importer 对非
  passthrough 名即 KeyError；worker 与预校验两侧用同一全集，「预校验过了＝worker
  能跑」。

## 六、实现锚点（读代码从这进）

- 加载器：`server/engine/project_templates.py`（名面=stdlib 源码扫描；类面=引擎
  venv importlib 全量加载＋形状深检；零 shared import，依赖全参数注入）。
- 合并：`shared.py` 末尾「项目外置工作流模板面」段（名面并入两表＋拒收清单）；
  `workflows_v2.py` 尾段（类面并入＋深检回写撤下名面已并入但深检拒掉的 id——
  引擎进程内两表恒一致，交叉自检不破）。
- 注册顺序钉死：内置∪夹具（`SANDBAR_FIXTURE_TEMPLATES` 门，语义不动）先占，
  项目模板后到；后到撞名即拒收点名双方。
- 验收用例：`server/engine/tests/test_t260924_04_project_templates.py`（A2/A3/A7
  对应例）；收窄守卫改判：`integration/t260904-08/sc_template_face_narrowing.py`
  （默认面=内置＋当项目显式登记；夹具门用例不动）。

## 相关文档

- [sandbar项目接入契约v1](sandbar项目接入契约v1.md)（①d paths 键表）
- 设计稿：`notes/discussions/260924-项目外置工作流模板-设计稿.md`
