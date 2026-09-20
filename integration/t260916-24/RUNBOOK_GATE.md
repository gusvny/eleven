# dsh 升级回归门槛（T4 交付文本，交 integration 粘贴进 runbook §1 硬门槛）

> 本文件=t260916-24（dsh-upgrade epic T4）交付的门槛文本块，落点=主检出
> `notes/discussions/260916-dsh-upgrade-runbook.md` §1「硬门槛（不满足不开工）」
> 清单末尾追加一项（notes/ 在工单写集外，故以此交接件交付，由 integration 落笔
> 并在 `notes/epics/dsh-upgrade.md` T4 行勾选）。条数口径随 registry 实时变化，
> 不硬编码。

## 建议追加的门槛条目（粘贴用）

- [ ] **T4 探针与回归全绿（升级候选版本先在隔离面验，全绿才进 §2 执行）**：
  1. **接缝探针 live 档**（t260916-24 交付，`integration/t260916-24/probe_dsh_seam.py`）：
     `python3 integration/t260916-24/probe_dsh_seam.py --version <候选版本>`
     （版本必须显式钉；隔离前缀安装+隔离 DSH_HOME 一次性真会话+五断言：文件名口径/
     解析面必填/记录类型族清单/沙箱不变量/钉模型生效/resume 可用）。任一拦停级红
     → 不开工，逐项点名即破法定位。环境缺（npm/网络/凭据/zstd）=exit 2，补环境重跑。
     可选深查：`--rounds 3` 延伸子用例观测 cacheReadTokens（矩阵 #2 开放问号；非门槛判据，
     结论回填矩阵 #2）。探针离线自检（`--selftest`）已入场景
     t260916-24-dsh-probe-selftest（ro 池），gate 常跑保探针不腐。
  2. **场景全集**：升级候选就位后，在隔离泳道/隔离副本先跑
     `python3 integration/run_scenarios.py`（registry 全集，条数以该文件实时为准）
     全绿；engine 池（docker 台）不得借 SANDBAR_SCENARIO_EXCLUDE_POOLS 豁免本轮。
  3. **巡检套件**：巡检一轮全绿（含次日 07:30 调度触发的完整周期观察，衔接 §2 步骤 7）。
  4. **版本面自检**：重启 worker 后 `cat <worker pidfile>.meta` 的 `dsh` 键应报
     新版本（host=实证 `--version`；docker=镜像 tag 提取）；
     `SANDBAR_DSH_EXPECTED_VERSION=<候选版本>` 置于 worker 环境可让「不符」每次
     spawn 响亮（`SANDBAR_DSH_STRICT=1` 升格硬闸，回退演练时可用）。

## 升级切流与回退（衔接 runbook §2/§3）

- 引擎侧只动 worker 环境旋钮：host=`SANDBAR_AGENT_CMD`（显式二进制路径）、
  docker=`SANDBAR_AGENT_IMAGE`（镜像 tag）——console(3099) 用的全局 dsh 不受影响
  （红线 #1 自动满足）。
- 回退=旋钮切回旧路径/旧 tag + `dsh --version` 复核；meta 的 `dsh` 键即时可查证。
