# t260921-14 试验协议执行手册（先在一个泳道里试验，绿了才谈切换）

> 宿主令定案③「先在一个泳道里试验，成功才考虑合并」。本手册是**宿主/集成闸的执
> 行剧本**（本票交付的是能力+文档；执行不在 developer 段写集内）。每步的判定读数
> 都来自票面 `dsh_pin_<tag>.json`（face + tri 块）与 spawn 日志 `[dsh_pin]` 行——
> 机器层安装态≠代码态（KI-058），一切以票面自检面为准，不以「我装了」为准。

## Step 0 建镜像（宿主侧，联网窗口一次性）

```sh
sh server/engine/build_agent_image.sh        # 缺省=0.1.5-rc.2 → sandbar-agent:dsh-0.1.5-rc.2-s1
docker image ls | grep sandbar-agent         # 新旧两个 tag 都应在场（旧 tag=回退面，不许删）
```

构建失败不阻塞本票（merge 关卡兜底：宿主已建 0.1.5 镜像，或 worker env
`SANDBAR_AGENT_IMAGE` 指回旧 tag——见 CONTRACT_DOC_ADDENDUM.md 检查项）。

## Step 1 翻转钉（配置一行，回退=同一行删掉）

在试验泳道对应项目的 per-key 条目里加一行（`~/.sandbar/projects/<key>/project.yaml`）：

```yaml
paths:
  dsh_bin: /Users/user/.sandbar/dsh-015/bin/dsh
```

翻转后起第一张票前先看票面：`dsh_pin_<tag>.json` 的 `cmd[0]` 必须就是该绝对路径、
`cmd_source=declared`——face↔spawn 同源（C1），票面报的就是实际被钉的二进制。
`SANDBAR_AGENT_CMD` 与声明并存时 env 胜（face `dsh_bin_shadowed=true` + WARNING
点名）——试验期确保 worker 环境无 `SANDBAR_AGENT_CMD`。

## Step 2 单泳道真票

在同一泳道跑一张真票走完整链（create_plan → … → merge_check）。观察点：

- 每次活动 spawn 的 `[dsh_pin]` 日志行与票面 face/tri 块；
- `tri.consistency`：`consistent`=三面同版（理想）；`divergent`/`incomplete`=
  响亮 WARNING 点名（宿主全局 0.1.1 vs 引擎钉 0.1.5 的试验窗口内属**预期点名
  形态**——引擎钉与容器面一致即试验有效，宿主全局面留待 T2 升级归一）；
- 会话/日志/统计面无 dsh 行为异常（会话完成率、工具调用面、patch 落地面）。

## Step 3 对账（T4 探针 + 隔离副本全集）

```sh
# T4 探针：对 0.1.5-rc.2 做接缝对账（宿主/泳道真机态）
python3 integration/t260916-24/probe_dsh_seam.py --version 0.1.5-rc.2
# 接缝矩阵 #11：隔离副本先跑全集（集成闸 run_integration_tests 段执行）
```

## Step 4 绿了才谈切换 / 不绿即回退

- 绿：镜像 tag 缺省已是 0.1.5-rc.2（三处同步锁已翻新，行为级切换=无需动配置）；
  宿主全局升级归 T2 的 Q1 窗口（宿主操作，届时三面自然归一）。
- 不绿/试验中止：按 **ROLLBACK.md** 三层各自回退（引擎=删/注释 `dsh_bin:` 行；
  镜像=env 指回 `sandbar-agent:dsh-0.1.1-rc.2-s1`；宿主全局不动）——回退动作全是
  配置级，秒级生效，票不停摆。
