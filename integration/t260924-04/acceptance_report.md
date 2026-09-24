# t260924-04 票1 验收走查报告（integration，acceptance_walkthrough gen0）

结论：**不通过（status=failed）**——核心功能「登记即加载」在真实引擎路径上不可用：
好模板的类面注册被加载器自身误判「撞名 id」拒收，外置模板类永远进不了注册表。
属代码缺陷（developer 打回），非测试绿灯捷径。

## 走查方法（用户视角，独立实证）

本段不预设「测试已通过」。注入的机械结果里 t260924-04 两个场景被闸拦（未跑），
故走查以独立探针在引擎 venv（server/engine/.venv，含 temporalio）下直读公开真源
（shared.TEMPLATE_CLASS_NAMES / shared.PROJECT_TEMPLATE_REJECTIONS /
workflows_v2.TEMPLATE_CLASSES / ALL_WORKFLOWS_V2），逐状态构造项目注册表实测；
另以本仓离线场景 `integration/t260924-04/sc_project_template_gate.py` 全量复跑。

## 逐场景结论

| 场景 | 结论 |
|---|---|
| A2 零登记零漂移 | **过**：不声明 workflow_modules 时四表恰 {dev-lane}、拒收清单空（独立探针＋场景 4 断言绿） |
| A1 登记即加载（好模板→注册表） | **不过（缺陷 #1）**，见下 |
| A3a 撞名 id 点名双方/不覆盖/不改名 | 过（占用方、来件方、不覆盖均实证；但见缺陷 #2 的误报面） |
| A3b 畸形（缺 STAGES 等） | **不过（缺陷 #2）**：深检在真实路径不可达，点名失真 |
| A3c 加载失败隔离 | 部分过：坏模块确实不注册、不拖同行（隔离语义成立）；点名内容受缺陷 #2 影响失真 |
| 补丁标识纪律 / 夹具门语义 / 文档面 / 建票文案接明细 | 过（场景断言绿＋代码读核；ticket.py 明细段在「可用：」之前，收窄守卫判面保住） |
| UI/泳道图渲染 | 不适用：本票无 UI 改动 |

## 缺陷 #1（阻断级）：好模板类面注册自撞名，功能不可用

机理：`shared.py` 模块级 glue 先做名面并入（`TEMPLATE_CLASS_NAMES` 收进
`projx-good`）；随后 `workflows_v2.py` import 时调 `project_template_classes_merged()`，
内部 `scan()` 用**已并入的** `TEMPLATE_CLASS_NAMES` 初始化 `taken`（占用表）——
名面已接受的外置 id 因此被判「撞名 id，占用方=已注册模板（就是它自己）」，
类面拒收，再被 `reconcile()` 从两表撤下。净效果：**任何在两面目力同一注册表时
被名面接受的外置模板，类面必然被自撞名拒收，TEMPLATE_CLASSES 永不含外置类**。

实证（好模块、干净注册表、引擎 venv）：

```
names: {'dev-lane': 'DevLaneWorkflow'}
rejections: [{"project":"projx","module":"wf_mods/good.py","check":"撞名 id",
  "detail":"…占用方=projx-good（已注册模板）；来件方=projx/wf_mods/good.py"}]
classes: ['dev-lane']    all_wf: ['DevLaneWorkflow']   ← 外置类缺席
```

对照需求「启动时加载项目声明的模板类，与内置合并进同一注册表」——不成立。
场景②（journey）的 A1 全链在本缺陷下必红（本轮该场景被闸拦未跑，与此互洽）。

为何 UT 全绿没兜住：`tests/test_t260924_04_project_templates.py` 全部经
`root=空测试根` 注入，而 shared import 时 glue 用**真实注册根**（无声明项目）——
两面目力不同注册表，自撞名不触发，缺陷结构性逃逸。

修复方向（供 developer 参考，不改判验收）：`project_template_classes_merged()`
里传给 `scan(builtin_names=…)` 的应是**并入前的内置∪夹具快照**（即 `_PT_BUILTIN_KEYS`
对应的原表），而非已被 glue 并入后的 `TEMPLATE_CLASS_NAMES`；同理 `taken` 的
「其他项目已接受」语义需按本次 scan 的 accepted 递进而非共享表回灌。

## 缺陷 #2（点名失真）：深检不可达，三态点名被「撞名 id」吞掉

同一机理的副产品：凡名面放行的模块，类面一律先撞 `taken in` 自撞名短路，
`_load_class` 的深检（缺 STAGES／段形态不合／源码与类属性不一致／import 抛错点名）
在真实路径**全部不可达**。实测缺 STAGES 的模块被拒为：

```
{"check":"撞名 id","detail":"…占用方=projx-nostages（已注册模板）；来件方=projd/wf_mods/nostages.py"}
```

fail-closed 本身成立（确实没注册），但违反需求③「报错点名哪个检查失败」——
用户看到的是莫名的自撞名而非「缺 STAGES」。

## 测试资产变更审查

对照前段（design 交付的场景资产 vs implement 后现状），两处**探针契约漂移**
（测试资产问题，非绿灯捷径；修 test 或修 code 由打回轮定夺）：

1. `sc_project_template_gate.py` 探针读
   `project_templates.PROJECT_TEMPLATE_REJECTIONS`——该属性实现落在
   `shared.PROJECT_TEMPLATE_REJECTIONS`，`project_templates` 模块上不存在 →
   探针侧拒收清单恒空，11 条拒收点名断言假红；
2. 同场景 `base`（同门同源断言用）取自 `PROBE_FULL` 未设的探针输出，`classes`/
   `all_wf` 键恒缺 → 同源两断言结构性假红；探针 `names` 快照又在 workflows_v2
   import **之前**取拷贝，深检撤下结果不可见（A3b「畸形模板不注册」假红）。

以上两处导致场景① 11 项假红——即便缺陷 #1/#2 修复后场景仍不会绿，需同步修正
探针取数面（读 shared 的拒收清单＋full 探针＋v2 import 后取 names 快照）。

## 收口两问（留痕）

- **doc_sediment**：`want=false`——本票设计契约已毕业为
  `docs/design/项目外置工作流模板加载口v1.md`（含确定性规约/演进纪律/生效粒度），
  无新增值得沉淀的事实；本轮发现的实现缺陷走打回修复，不入知识库。
- **doc_conflicts**：核对 docs/README.md 与加载口文档（本轮实际读过全文的两篇；
  契约 v1 仅读 diff 未全文，不计）：
  - doc=`docs/design/项目外置工作流模板加载口v1.md` §一.1/§六
    claim=「引擎启动时加载…与内置合并进同一张注册表（两表同源合并）」
    actual=如缺陷 #1：类面自撞名拒收，外置类永不入表——**实现被文档契约推翻方向
    反置（代码不符文档）**；修复方向=代码侧，文档主张无须改写。
  - 除上述外未见文档既有主张被本票实现推翻。矛盾条目请引擎随打回一并登记
    pending-doc-sync（闭环条件=缺陷 #1/#2 修复后本场景①②转绿，再核文档锚仍成立）。

## 遗留与风险

- 缺陷 #1/#2 打回后，场景①的探针取数面需同步修（见测试资产小节），否则打回轮
  仍会假红空转；
- 场景②（journey，docker serial）本轮被闸拦未跑，本走查未覆盖真 Temporal 链路
  的 A1/续跑行为面——缺陷 #1 修复后必须真跑补证；
- 仲裁若另判归属（tests-fault/code-fault 拆分），以本报告逐条实证为准。
