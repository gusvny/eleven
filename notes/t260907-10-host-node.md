# t260907-10 宿主配合节点清单（一次性执行序，开发泳道不可达面）

> 依据：t260907-10 方案 v2 步 5（gen1 复核通过）；执行窗口=本票 merge 前后择机，
> 与 console 重启对齐，**重启前停止派新活**（迁移窗口运行中 worker 的惰性 import
> 不受物理 mv 保护，见方案 B2 改述）。

## 1. 主树 .venv/bin 物理迁移（数据不丢）
```
cd /Users/user/Documents/sandbar
mkdir -p server/engine
mv server/dsh/temporal-poc/.venv  server/engine/.venv
mv server/dsh/temporal-poc/bin    server/engine/bin     # temporal CLI（verify supply 消费）
mv server/dsh/temporal-poc/data   server/engine/data    # server.log/worker.pid/temporal.db（结构不变）
```
判据（全过才算完）：
- `server/engine/.venv/bin/python -c 'import temporalio'` 退出 0
- `./sandbar doctor` 退出 0（compat-matrix 五面绿）
- 老 worker 进程已自然收口（`pgrep -f temporal-poc/worker.py` 为空）或已随 console 重启收尸

## 2. profile 农场软链重定向（写 ~/.dsh，泳道外）
```
ln -sfn /Users/user/Documents/sandbar/server/profile         ~/.dsh/profiles/sandbar
ln -sfn /Users/user/Documents/sandbar/server/profile-headless ~/.dsh/profiles/sandbar-headless
```
旧名链处置（宿主裁定，建议删除）：`~/.dsh/profiles/suyou`（现指 sandbar 仓 server/dsh/profile，迁移后为死链）
与 `~/.dsh/profiles/suyou-headless`（跨仓 suyou 旧链）。
profile 内 node_modules 五插件链由 installer 装链（../../plugins/<name>），主树装链面
若手工维护需同步重指。

## 3. console 重启（3099 用户操作面，宿主手动）
- start-console.sh/stop-console.sh 的路径与 pgrep 谓词更新属**仓根扩权四文件**债
  （verify.yaml/start-console.sh/stop-console.sh/README.md，review gen0 A1 申报），
  扩权未落地前重启后 worker 停靠旧谓词——建议扩权与重启同窗。
- 重启后：跑 `node server/ui-check/capture-lane.mjs` 取插件装载链截图（验收④证据）。

## 4. 随窗裁定回填（三项仲裁）
- 写集扩权四文件落地 → sc_engine_layout/sc_engine_venv_compat/sc_worker_reap_predicate
  三守卫由红转绿，验收① grep 可收口；
- A2 回落切法（方案倾向切法一已落地）如改切法二，sc_engine_venv_compat 随语义改读 env 锚；
- A4 plugins=5 口径（11=沿革子目录总数）确认，异议则只动 plugins 层映射一行。
