# 260917 泄漏测试台（3199）与孤儿进程组事故记录

> 记录人：integration 岗位（sandbar 项目会话，宿主授权「记一下吧」）
> 性质：**事故记录 + 定位结论**（只定位不修复；修复须开票走 dev-lane）
> 状态：已止血（台已停、孤儿循环已断）；根因待开票

## 一、现象（时间线）

| 时刻 | 现象 |
| --- | --- |
| 09-16 21:24 | `/private/tmp/dsh-stage` 出现一个独立控制台（端口 3199、`DSH_HOME=/private/tmp/dsh-stage`、profile=`sandbar-stage`） |
| 09-16 22:2x–22:3x | 一批票集体 blocked（worker 侧中断，见 §三 缺陷③） |
| 09-16 23:xx | dengzhufpv `t260916-17` 的 merge 被劫、写 `.git/ORIG_HEAD.lock` 得 `EPERM` |
| 09-17 01:28 | nusuyou `t260916-30` 卡 `workspace/blocked`：`Operation not permitted: /Users/user/Documents/nusuyou/.lane/...` |
| 09-17 03:03 / 04:51 / 06:37 | 在飞 agent 段反复被 `CancelledError` + `Activity task timed out` 砍 |
| 09-17 全天 | 多张票的 agent 段报 `dsh: corrupt Zstandard session log: complete frame contains a torn JSONL record`（会话拒读） |

## 二、根因链（已实证）

1. **测试台连生产 Temporal**：3199 台的 `temporal-tools` 插件加载后，其 keepalive 会给**生产 Temporal 上所有 running 票**起 worker（无项目过滤）。
2. **worker 血统错挂**：这些 worker 的父进程是**测试台**（非生产 console），于是服务对象与实际执行上下文不一致 —— 例：`worker t260916-30` 的父 = 90670（3199 台），而 `worker t260916-23` 的父 = 80526（生产 console，正常）。
3. **同一票被两个 worker 抢**：生产 console 的 keepalive 与测试台的 keepalive 各自给同一票起 worker → 同一队列两个 poller → **同一会话文件被两个进程交替写** → JSONL 记录交错 → 下一个恢复进程报 `torn JSONL record` 拒读。
   - 受害实证：`t260917-01`（sandbar）、`t260916-30`（nusuyou）。
   - **注意**：会话文件本身经 `zstd -t` 完整性 + 逐行 `json.loads` 双验证**全部健康**（6495 行全合法）——「损坏」是**多写者交错**造成的，不是文件坏了。
4. **孤儿循环维持台不自灭**：起台的会话结束/被杀后，其 `bash` 循环逃逸成孤儿（父进程 = launchd(1)），**每 ~25 秒重起一次台**。实测：杀台 → 20 秒后新 pid 出现（90670 → 34907 → 36362），**只有杀掉那个孤儿 bash 才停止**。
   - 该逃逸与 **t260916-29** 所修缺陷同源：worker/agent 停机时**进程组未被干净收割**。

## 三、关联缺陷清单（本事故暴露，均待开票）

| # | 缺陷 | 证据 |
| --- | --- | --- |
| ① | 测试台连生产 Temporal 时，其插件**主动写行为**（keepalive 补 worker）未被禁用——只靠「只读警示横幅」挡不住机器 | `server/tools/stage_console.sh:61`（设计自述「本台连的是生产 Temporal」，护栏=四处横幅） |
| ② | keepalive 补 worker **不看项目归属**：任何 console 实例给生产 Temporal 上所有 running 票补 worker | 事故 §二.1；队列名 `sandbar-ticket-<tid>`（`server/engine/shared.py:83-90`，前缀硬编码，无项目身份） |
| ③ | worker/agent 停机时**进程组未干净收割** → 孤儿循环长驻 | 90670→34907→36362 重起实证；与 t260916-29 同域 |
| ④ | 票面把所有 agent 段失败笼统报成「agent 活动故障」，真因被吞 | 429 撞限、会话拒读、心跳超时三种真因，票面同一句话 |

## 四、处置记录（本次已做，全部可回溯）

| 动作 | 对象 | 备注 |
| --- | --- | --- |
| 停台 | 90670（3199）→ 34907 → 36360/36362 | 前两次均被孤儿循环重起 |
| 断根 | 孤儿循环 bash（36360，父=launchd） | 停后 30 秒复核：3199 释放、无 `dsh-stage` 血缘进程 |
| 停错挂 worker | 68413（nusuyou `t260916-30`）、31121（sandbar `t260917-01`） | 停后 `t260917-01` 由生产 console 补上正确血统 worker（pid 34921，父=80526） |
| 会话处理 | `-26/-28/-01` 的会话文件改名 `.torn-backup-<ts>` | **未删除**，可一键回滚；只碰会话缓存，未碰代码/交付物/票面 |

## 五、未决与下一步

1. **队列/供给面按项目隔离**（治本，需设计决策）：选项 A 队列名带项目身份 + keepalive 限本项目；选项 B worker 启动带项目上下文；选项 C console 从无沙箱终端起（止血）。
2. **测试台治理**：连生产 Temporal 时机械禁用主动写行为；生命周期硬约束（会话结束即自毁、禁止孤儿循环）。
3. **进程组收割**：与 t260916-29 合并考虑或紧随其后。
4. **`EPERM` 归属已钉死（09-17 补记）**：真凶＝**泄漏台的沙箱血统**，不是 console。
   证据链：
   - console **无沙箱**（宿主澄清；血统链亦验证：`worker 80547` 父=80526 生产 console，服务本仓票一切正常）；
   - 报 `Operation not permitted` 的 `worker t260916-30`（pid 68413）**父=90670（3199 泄漏台）**；
   - 泄漏台由 agent 会话侧进程起，因此**继承 DSH 沙箱**（授予面=被服务的会话工作区）→ 它派生的 worker 一碰其他项目目录即 `EPERM`；
   - 停掉泄漏台后，生产 console 补起的新 worker（pid 34922，父=80526）不再受该限制。
   ⇒ **「worker 的权限面＝起它的那个上下文」成立，继承源是泄漏台／agent 会话，而非 console。**
   待验证：`t260916-18`（nusuyou）的 `unable to create temporary file` 是否同源（泄漏台血统的环境差异），重跑即知。

## 六、方法论备忘（本次踩到的两个坑）

1. **筛进程不能只筛 Python**：第一次清理泄漏台时只过滤了 Python 进程，而台本体是 **node**，于是漏掉了 3199 台（90670）——它继续作案数小时。
2. **「文件健康」不等于「可用」**：`zstd -t` + 逐行 JSON 校验通过，仍可能被上层拒读。判断写入面健康必须**同时看写者是否唯一**。
