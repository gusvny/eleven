# sandbar-temporal-tools

Temporal 编排工具面的 dsh 插件（模型可见工具 + supervisor 守护）。

- 模型可见工具 = `start / query / signal / schedule-list / cancel / ticket_sign` 六个，全部 spawn
  `engine/.venv/bin/python client.py <子命令>`，逻辑真源在 python 侧（`client.py`）。
  安全红线：**不暴露 set-stage / force_stage / 改状态工具**。
- `ticket_sign`（M3 新增）= 工单人工审批签字，走 `client.py ticket '{"op":"sign",…}'`
  （TicketWorkflow 的签字白名单）。schema 只有
  `ticket_id / who / gate / decision / note`，**无 set-stage**；who 由调用方注入身份
  （agent 不得自签自己的角色名），decision=reject 打回上一段。
- supervisor（t260821-04 新增）= 把 `engine` 的 server + worker 变成「dsh 一启动就有、
  崩了自动重启」的托管服务。

## supervisor 设计

### 一句话

dsh 插件 boot 时探测 temporal gRPC 端口（缺省 `127.0.0.1:7233`）——**端口有没有监听者就是
单例锁**。没监听者就 spawn `run_server.sh`（server），server 就绪后再 spawn
`worker.py --daemon`（worker）；随后 keepalive 定时器周期探测两者存活，崩了自动重启。

### spawn 模式（二选一的决定：托管子进程）

- **server = 托管子进程**（`spawn(run_server.sh, { detached: false })`，持有 `ChildProcess` 句柄）。
  `run_server.sh` 内部 `exec temporal server start-dev`，所以句柄指向的 pid 就是 temporal
  本体；stdout/stderr 重定向到 `engine/data/server.log`。
- **worker = `worker.py --daemon`**（python 侧 `fork + setsid` 自守护，父进程立即退出，真
  worker 是孙进程），supervisor **用 pidfile（`engine/data/worker.pid`）追踪**，不持有
  ChildProcess 句柄。

没有用 `detached: true + unref`（「留 detached」那套）：那样 dispose 之后 server/worker 会
继续孤儿般挂着，违背「起停可控」。这里两条都跟插件生命周期走、dispose 优雅停。

### dispose 行为（重要）

`apply()` 返回 disposer，dsh 关闭时 cordis 自动调用：

1. 停 keepalive 定时器；
2. 给 worker 发 `SIGTERM`（`worker.py` 接 SIGTERM → 在跑 activity 做完后优雅停）；
3. 给 server 发 `SIGTERM`，3 秒后若未退再补 `SIGKILL`。

**只停「本会话 spawn 的」进程**：dispose 之前若 server/worker 是别人（手动起的、或另一个
dsh 会话起的）已经在跑，本会话 boot 时探测到就只「收养」不重启、不持有句柄，dispose 时
也不会去动它。这样多个 dsh 会话共享一个 temporal 实例时，一个会话退出不会误杀共享服务。

### 单例保证

- server：`7233` 端口只允许一个监听者——第二个 boot 探测到端口已通就直接跳过 spawn；
  即使真有两个并发 spawn，temporal 自己的 `EADDRINUSE` 也会让后一个起不来、自然让位。
- worker：boot 时读 pidfile 做 `kill -0` 存活探测，存活就不重复 spawn（`--daemon` 的
  pidfile 由 worker.py 父进程在退出前原子写入，并发窗口极小；同一 task queue 多 worker
  也只多拉活、不破坏状态）。

### 手动停（临时接管/排障）

```sh
kill -TERM "$(cat server/engine/data/worker.pid)"   # 停 worker（优雅）
# 停 server：lsof -iTCP:7233 -sTCP:LISTEN 找 pid 后 kill -TERM
```

## 配置（cordis.patch.yml 的 config: 字段，全部可缺省）

| 键 | 缺省 | 说明 |
| --- | --- | --- |
| `repo` | 按本文件位置推导 | 溯游仓库根 |
| `python` | `engine/.venv/bin/python` | 带 temporalio SDK 的解释器 |
| `timeoutMs` | `120000` | 工具子进程超时 |
| `supervisor` | `true` | 关掉 `supervisor: false` 可只注册工具不起守护（纯工具面用） |
| `port` | `7233` | supervisor 探测的 gRPC 端口（单例锁） |
| `keepaliveMs` | `5000` | keepalive 探测间隔 |
| `pidfile` | `engine/data/worker.pid` | worker pidfile |
| `serverLog` | `engine/data/server.log` | server 日志 |
| `workerLog` | `engine/data/worker.log` | worker 日志 |

## 自测口径

见工单 t260821-04 结算附注：起停 / keepalive（kill worker、kill server 看是否自动重启）/
单例（再起一个不重复）。supervisor 逻辑不依赖 dsh 运行时，可直接
`node --experimental-strip-types` 加载本文件、用一个 stub `ctx` 调 `apply()` 后拿到 disposer 复验。
