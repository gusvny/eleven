# t260921-14 回退剧本（dsh 路径钉 / 容器镜像 / 宿主全局三层各自回退）

> 工单交付④「回退是硬要求」。本剧本每个动作都是**配置/一行命令**级，不需要重建、
> 不需要改代码。机械验证：`integration/run_scenarios.py t260921-14-rollback`（场景
> 子断言④即守本文件的字面锚不腐烂）+ 引擎单测 `test_t260921_14_dsh_path_pin.py`。
>
> 回退后自检读法：spawn 票面 `dsh_pin_<tag>.json` 的 `cmd_source` 应回 `default`、
> `image_source` 应回 `default`；`tri` 块 `consistency` 若报 inconsistent 属实况点名
> （三面版本对账），不挡 spawn——回退是否生效以 `cmd`/`image` 字段为准。

## 第 0 层：事前快照（升级前一次性，宿主操作，**未拍**）

> 状态实况（t260921-14 验收走查 gen1 机检，2026-09-21）：`~/.sandbar/dsh-011-backup`
> **不存在**——快照尚未拍。宿主在 T2/任何升级行动前先执行下面这条（270M 秒级，
> 只读源目录，不动全局 dsh 本体，console 3099 无感）：

```sh
cp -R /opt/homebrew/lib/node_modules/@deepseek-ai/dsh ~/.sandbar/dsh-011-backup
```

快照拍好后，宿主全局层随时可整体换回（见第 3 层）；**拍好之前第 3 层回退只走
B 案（按版本重装）**——A 案（快照换回）必须先确认快照目录在场再动手。

## 第 1 层：引擎层回退（dsh 路径钉 → 回裸 dsh 现状）

声明在 per-key 条目里：`~/.sandbar/projects/<key>/project.yaml`。回退=把
`paths.dsh_bin:` 那一行**删掉或注释掉**（注释形态 `# dsh_bin: …` =声明缺席语义，
引擎解析器两种形态都逐字回裸 `dsh`，不残留死键红、不残留钉态尾巴）：

```yaml
# project.yaml（回退后 paths 节整节消失或整节注释，其余键不动）
schema: v1
project:
  - key: <key>
    name: …
    dirs:
      - /path/to/repo
# paths:
#   dsh_bin: /Users/xingu/.sandbar/dsh-015/bin/dsh   ← 注释掉/删除这一行即回退
```

- 回退立即生效（每次 spawn 现场解析，无缓存进程依赖——worker 重启也不需要）。
- 注意：**不要**把 `dsh_bin:` 留成空值——空值/纯空白=fail-closed 红拦 spawn
  （声明缺陷必须显式删行或注释，不留半吊子声明）。回退一律整行删/注释。
- docker 形态本就不消费该声明（容器内 dsh 由镜像承载），此层回退只影响 host 形态。

## 第 2 层：镜像层回退（新 tag → 指回旧 tag，无需重建）

旧 tag `sandbar-agent:dsh-0.1.1-rc.2-s1` **本机镜像保留未删未覆盖**（同升=新打
tag，不是替换）。回退=把 worker 侧镜像旋钮指回旧 tag：

```sh
# run_worker.sh 启动环境（或 cron/systemd 单元的环境块）
export SANDBAR_AGENT_IMAGE=sandbar-agent:dsh-0.1.1-rc.2-s1
```

- `SANDBAR_AGENT_IMAGE` env 存在时压过代码缺省（`agent_runtime.DEFAULT_AGENT_IMAGE`
  现为 `sandbar-agent:dsh-0.1.5-rc.2-s1`），face `image_source=env`、tag 提取版本立
  即可判，无 docker 调用、无需重建。
- 代码缺省（三处同步位：`DEFAULT_AGENT_IMAGE` / `Dockerfile.agent ARG` /
  `build_agent_image.sh` 缺省）**不改**——配置级回退永远优先，回退不动代码。
- 若本机旧镜像确被清理：重建旧版一条命令 `sh server/engine/build_agent_image.sh
  0.1.1-rc.2 s1`（需联网窗口），产物 tag 与原旧 tag 同名。

## 第 3 层：宿主全局回退（/opt/homebrew 的 dsh → 0.1.1-rc.2）

本层属宿主操作面（console 3099 依赖它），**本票不执行**，剧本成文备用：

```sh
# A. 快照换回（秒级，进程占用需先停相关会话——由宿主选窗口）
#    前置：确认 ~/.sandbar/dsh-011-backup 在场（第 0 层拍过才在）。
#    不在场=改走 B 案，严禁先 rm 再发现无料可回。
rm -rf /opt/homebrew/lib/node_modules/@deepseek-ai/dsh
cp -R ~/.sandbar/dsh-011-backup /opt/homebrew/lib/node_modules/@deepseek-ai/dsh
# B. 或按版本重装（联网）
npm i -g @deepseek-ai/dsh@0.1.1-rc.2
dsh --version   # 应输出 0.1.1-rc.2
```

## 回退演练（试验协议第 4 步的一部分）

1. 翻钉态跑过真票后，执行第 1 层（注释/删除 `dsh_bin:` 行）；
2. 起一张新票：票面 `dsh_pin_<tag>.json` 应 `cmd_source=default` 且 cmd 与缺省
   `dsh --profile sandbar-headless` 逐元素等值（场景 t260921-14-rollback 子断言
   ①② 的机械形态）；
3. `export SANDBAR_AGENT_IMAGE=sandbar-agent:dsh-0.1.1-rc.2-s1` 后再起一张：face
   `image=旧 tag / image_source=env / version=0.1.1-rc.2`（子断言③）。
