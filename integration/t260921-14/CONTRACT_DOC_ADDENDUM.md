# t260921-14 契约增补（对外契约 v1 ①d paths 键族：`dsh_bin`）

> 写集边界：本票不动 `docs/design/sandbar项目接入契约v1.md`（受保护知识库）。本文件
> 是**粘贴就绪的增补块**——merge/文档持有人按下面两块落进契约正文即完成文档同步。
> 既有守卫 `integration/t260903-03/sc_paths_contract_doc_guard.py` 断言的是 G1-G7
> 存在性（roles_dir/model_routes 在场、v1.6 推进），非闭合键表——落增补后不撞守卫。

## 块一：§①d paths 节键表追加一行语义段（紧跟 `inspection_decl` 段之后）

```markdown
**`dsh_bin`（t260921-14 增量，dsh 升级 epic T3）**：`paths` 节新增 `dsh_bin` 指路键
——引擎 spawn 的 dsh 可执行体钉到机器级绝对路径（`~/` 展开与绝对路径形态放行；
相对路径拼项目主目录；词法校验同源：空值/非标量/`..` 逃逸/引号剥壳同 `model_routes`
机器级口径）。**未声明=裸 `dsh` 走 PATH 的现状逐字**（缺省=完整配置非降级，回落语义
刻意不照抄 `model_routes` 的仓内兜底表——dsh 无「仓内兜底二进制」概念）。旋钮优先级
`SANDBAR_AGENT_CMD`（env 整命令）> `paths.dsh_bin` > 缺省；声明被 env 遮蔽=face
`dsh_bin_shadowed=true` + WARNING 点名（不静默吞任何一边）。声明面缺陷（锚点缺失/
非文件/不可执行）=fail-closed 红拦 spawn，**不回落裸 dsh**；`--version` 探测失败归
观测面（face `version_state=error` 照记），不挡启动——两级分明。docker 形态不消费
本声明（cmd 在容器内解析，宿主路径不可见；容器内 dsh 版本由镜像承载，旋钮
`SANDBAR_AGENT_IMAGE`），声明在场=WARNING 点名。face↔spawn 同源：票面
`dsh_pin_<tag>.json` 与实际执行的 cmd 出自同一次解析，票面另含 `tri` 块（宿主全局/
引擎生效/容器内实测三面版本对账，divergent/incomplete 响亮点名）。
```

## 块二：修订史追加一行（沿用既有行格式）

```markdown
| v2.7 | 2026-09-21 | t260921-14 dsh 路径钉（dsh 升级 epic T3）：①d `paths` 节新增 `dsh_bin` 机器级指路键（绝对/`~/`/相对拼主目录；词法同源），未声明=裸 `dsh` 现状逐字（回归锚），旋钮优先级 SANDBAR_AGENT_CMD > paths.dsh_bin > 缺省，遮蔽/形态不消费双 warning 点名，声明缺陷 fail-closed 红拦、探测失败归观测面；票面 dsh_pin_<tag>.json 增 tri 三面版本自检块（宿主全局/引擎/容器实测）与 dsh_bin_shadowed 标记；容器镜像缺省同升 0.1.5-rc.2（三处同步锁：DEFAULT_AGENT_IMAGE/Dockerfile ARG/build 脚本缺省），旧 tag sandbar-agent:dsh-0.1.1-rc.2-s1 保留为回退面（回退=env 指回或声明行删/注释，剧本 integration/t260921-14/ROLLBACK.md） | ①/①d；shared.py（PATHS_DECL_KEYS+解析+dsh_bin_for_spawn）、dsh_pin.py（resolve 声明参/is_dsh_runner/tri_face_payload）、agent_runtime.py（DEFAULT_AGENT_IMAGE+probe_image_dsh_version）、agent_activities.py（_dsh_resolved 接线/face↔spawn 同源/keyed memo/预检 basename/巡检同源）、build_agent_image.sh、Dockerfile.agent |
```

## epic dsh-upgrade 关账位

- T3（本票）：**已完成**——引擎 dsh 路径钉（可配置/缺省现状/一键回退）+ 容器镜像
  同升 0.1.5-rc.2（三处同步）+ 三面版本自检点名 + 回退剧本与机械验证
  （L1=test_t260921_14_dsh_path_pin.py；L2=t260921-14-pin-flip / -tri-face /
  -rollback 三场景，集成闸执行）。
- T4（t260916-24）：基座已完成；本票 tri 块把其 TODO(T3/Q3) 关账（tag-derived 弱
  证据的观测缺口由容器实测面补上）。
- T2（宿主全局升级 + 切换执行）：**未开工**——Q1 窗口宿主操作，前置=本票试验协议
  （TRIAL_RUNBOOK.md）绿。

## merge 关卡检查项（集成闸 merge_check 追加观测点）

1. [ ] 宿主已建镜像 `sandbar-agent:dsh-0.1.5-rc.2-s1`（`docker image ls` 可查），
       **或** worker 环境 `SANDBAR_AGENT_IMAGE` 指回
       `sandbar-agent:dsh-0.1.1-rc.2-s1`（缺省已翻新——两者必居其一，否则 docker
       形态真票会因镜像缺席失败）；
2. [ ] 试验协议状态在票面有记录（TRIAL_RUNBOOK.md Step2-4 的绿/红结论）；
3. [ ] 本增补块已落契约 v1（块一/块二），或登记为文档债带票号。
